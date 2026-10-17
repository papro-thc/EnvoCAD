"""Generování celého projektu ze specifikace (průvodce v GUI i rozhraní pro agenty). Bez Qt.

    python -m envocad.generate spec.json vystup.ecp

Specifikace (JSON, vše kromě `inverters` volitelné – viz `DEFAULT_SPEC`):
{
  "name": "FVE Firma s.r.o.", "meta": {"investor": "…", "place": "…", "order": "…", "author": "…"},
  "module": {"p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9, "beta_voc": -0.27, "type": "JA Solar …",
             "imp": 13.2, "u_sys_max": 1500,                          # nepovinné: Impp, max. napětí systému modulu
             "alpha_isc": 0.045, "gamma_pmax": -0.29,                 # nepovinné [%/K]: oba → součinitel Umpp = γ − α
             "component_id": "ja-solar-jam54d40-450"},                # nepovinné: artikl modulu (pv_modules.csv)
  "site": {"t_min": -20, "t_max": 70},                                # návrhové teploty stringů → meta pv_t_min/pv_t_max
  "optimizer": {"type": "", "per_module": 1,                         # optimizéry (prázdný typ = bez optimizérů)
                "component_id": "solaredge-s440-1gm4mrm"},            # nepovinné: artikl optimizéru (optimizers.csv)
  "inverters": [{"ref": "T1", "type": "SMA STP 25-50", "p_ac": 25, "phases": 3, "u_dc_max": 1100,
                 "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [20, 20, 18, 18],
                 "isc_mppt_max": 40, "strings_per_mppt": 2, "mppt": 2,       # nepovinné (jinak z artiklu, mppt dopočet)
                 "string_mode": "", "u_string": 750, "n_opt_min": 14,        # nepovinné: režim stringů a pravidla
                 "n_opt_max": 50, "p_string_max": 11250,                     # (jinak z artiklů střídače a optimizéru)
                 "component_id": "sma-stp-25-50"}],
  "dc": {"cable": "H1Z2Z2-K 1x6", "cross": 6, "length": 40,          # string → první DC rozvaděč
         "route_boxes": 1, "route_length": 20,                        # DC rozvaděče po trase (odpínač + SPD), kabel mezi nimi
         "tech_box": true, "tech_length": 5,                          # DC rozvaděč u technologie (pojistkové odpínače + SPD), kabel ke střídači
         "spd": "T2", "fuse_in": 15, "disconnect_in": 32,
         "disconnect": false},                                        # jen samostatný odpínač v JPS bez DC rozvaděčů (stará varianta)
  "ac": {"cable": "CYKY-J 5x16", "cross": 16, "length": 30, "breaker_in": 40, "main_in": 125,
         "grid_cable": "CYKY-J 5x35", "grid_cross": 35, "grid_length": 20, "spd": "T1+T2", "enclosure": "",
         "distribution": "bus"},                                      # rozvod v AC rozvaděči: "bus" (sběrnice potenciálů) | "terminals" (svorky s můstky)
  "switchboard": {"ref": "RH", "desc": "AC rozvaděč FVE"},
  "grid": {"dso": "ČEZ Distribuce", "voltage": "3×400 V"},
  "battery": {"e_kwh": 10, "p_kw": 5, "type": "…"},       # volitelné, jen u hybridního střídače
  "macros": {"dc_tech": "DC string v rozvaděči", "dc_route": "DC string po trase",   # rozvaděče se skládají z maker
             "ac_feed": "AC přívod střídače", "ac_core": "AC jádro rozvaděče"}       # (knihovna → Makra); "" = kód
}
Položka `macros` smí být i objekt {"name": "DC string v rozvaděči", "value_set": "Pojistka 20 A gPV, SPD T1+T2",
"values": {"fuse_in": 25}} – sada hodnot a hodnoty proměnných makra přebijí základ ze `dc`/`ac` (docs/LIBRARY_FORMAT.md,
„Formát makra“). Neplatná hodnota → ValueError s názvem makra. In (`fuse_in`, `disconnect_in`, `breaker_in`, `main_in`)
jsou čísla v A (ne „C40“), `spd` je text (T1, T2, T1+T2, T1+T2+T3…). Artikl střídače (`component_id`) doplní atributy,
které specifikace nezadala (typ, výrobce, mppt, strings_per_mppt…) – ještě před dopočtem `mppt` z počtu stringů.
Se známým `mppt` (specifikace nebo artikl) se stringy zapojí na MPPT rovnoměrně (string k → MPPT k mod mppt), jinak
za sebou DC1, DC2… (`calc.string_ports`). Neznámé `strings_per_mppt` zůstane v atributu prázdné (kontrola pak proudy
paralelních stringů nesčítá); pro počet DC vstupů se počítá se 2 na MPPT.
Artikl modulu (`module.component_id`) stejně doplní prázdné údaje modulu (p_wp, voc, vmp, isc, imp, beta_voc,
u_sys_max, alpha_isc, gamma_pmax, typ, výrobce); zadané hodnoty specifikace vyhrávají a stringy dostanou `component_id` artiklu.
Artikl optimizéru (`optimizer.component_id`, docs/design/optimizery.md) doplní prázdný typ (part_number) a
`per_module` = 1 / modulů na optimizér; stringy dostanou atributy `opt_*` (`Component.optimizer_values(phases)`)
a `n_optimizers` = ⌈n / modulů na optimizér⌉. Režim stringů střídače (`string_mode`): specifikace > artikl střídače >
artikl optimizéru > classic (prázdné); pravidla `n_opt_min` / `n_opt_max` / `p_string_max` nejpřísnější ze známých
(artikl střídače, artikl optimizéru pro fázi střídače), zadaná ve specifikaci vyhrávají. Bez `component_id` beze změny.
`site.t_min` / `site.t_max` [°C] se zapíšou do `meta["pv_t_min"]` / `meta["pv_t_max"]` (kontrola stringů,
`calc.design_temperatures`); bez nich platí výchozí −10 / 70 °C.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from envocad.library.templates import (
    AC_CONDUCTORS,
    DC_CONDUCTORS,
    GROUP_PITCH,
    _bridge_groups,
    _el,
    _place_sequential,
    _terminal_group,
    _wire,
    build_dc_strings,
)
from envocad.model.calc import DC_INPUTS_PER_MPPT_DEFAULT, InverterData, string_ports
from envocad.model.project import (
    PORT_PITCH,
    Element,
    Project,
    Sheet,
    Wire,
    WireEnd,
    inverter_dc_inputs,
    sync_cables,
    sync_feed_links,
)

BATTERY_ROW_EXTRA = 40.0   # místo pro baterii pod hybridním střídačem (mm)
INV_LABEL_SPACE = 40.0     # popisek DC kabelu („W12  2× H1Z2Z2-K 1x6 mm²“) mezi blokem rozvaděče a lomy ke střídači

DEFAULT_SPEC = {
    "name": "Nový projekt FVE",
    "meta": {},
    "module": {"p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9, "beta_voc": -0.27, "type": ""},
    "site": {},   # {"t_min": -20, "t_max": 70} – návrhové teploty stringů (průvodce předvyplní ze standardu)
    "optimizer": {"type": "", "per_module": 1},
    "dc": {"cable": "H1Z2Z2-K 1x6", "cross": 6, "length": 30, "route_boxes": 1, "route_length": 20,
           "tech_box": True, "tech_length": 5, "spd": "T2", "fuse_in": 15, "disconnect_in": 32, "disconnect": False},
    "ac": {"cable": "CYKY-J 5x16", "cross": 16, "length": 30, "breaker_in": 40, "main_in": 125,
           "grid_cable": "CYKY-J 5x35", "grid_cross": 35, "grid_length": 20, "spd": "T1+T2", "enclosure": "",
           "distribution": "bus"},
    "switchboard": {"ref": "RH", "desc": "AC rozvaděč FVE"},
    "grid": {"dso": "", "voltage": "3×400 V"},
    # makra, ze kterých se rozvaděče skládají (název makra z knihovny; "" = vestavěný kód); výkresy ladí projektant
    "macros": {"dc_tech": "DC string v rozvaděči", "dc_route": "DC string po trase",
               "ac_feed": "AC přívod střídače", "ac_core": "AC jádro rozvaděče"},
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def _s(v) -> str:
    return "" if v is None else str(v)


_BUILD_LIB = None    # knihovna sdílená během jednoho `build_project` (otevření LibraryStore = synchronizace souborů)


def _lib():
    """Knihovna pro generátor: během `build_project` jedna instance pro celé sestavení, jinak nová."""
    if _BUILD_LIB is not None:
        return _BUILD_LIB
    from envocad.library.store import LibraryStore
    return LibraryStore()


AC_MAX_INVERTERS_BUS = 12   # přívody T1…T12 sběrnice sb.busbar (`tools/gen_builtin_fve.BUSBAR_INPUTS`)


def build_project(spec: dict) -> Project:
    """Sestaví projekt: JPS (stringy → DC rozvaděče → střídač, každý string na vlastní DC vstup → AC rozvaděč → síť) + listy rozvaděčů."""
    global _BUILD_LIB
    if _BUILD_LIB is not None:          # vnořené volání – knihovna už je otevřená
        return _build_project(spec)
    from envocad.library.store import LibraryStore
    _BUILD_LIB = LibraryStore()
    try:
        return _build_project(spec)
    finally:
        _BUILD_LIB = None


def _build_project(spec: dict) -> Project:
    spec = dict(spec or {})
    if isinstance(spec.get("module"), dict) and spec["module"].get("component_id"):
        # artikl modulu doplní jen to, co specifikace nezadala – proto před doplněním výchozích hodnot
        spec["module"] = _apply_module_component(spec["module"])
    opt_comp = None
    if isinstance(spec.get("optimizer"), dict) and spec["optimizer"].get("component_id"):
        spec["optimizer"], opt_comp = _apply_optimizer_component(spec["optimizer"])
    spec = _merge(DEFAULT_SPEC, spec)
    invs = spec.get("inverters") or []
    if not invs:
        raise ValueError("Specifikace musí obsahovat alespoň jeden střídač (`inverters`).")
    if (spec["ac"].get("distribution") or "bus") == "bus" and len(invs) > AC_MAX_INVERTERS_BUS:
        raise ValueError(f"AC rozvaděč: sběrnice má {AC_MAX_INVERTERS_BUS} přívodů – nejvýš {AC_MAX_INVERTERS_BUS} "
                         f"střídačů (zadáno {len(invs)}). Zvolte rozvod svorkami nebo rozdělte FVE na více rozvaděčů.")
    p = Project(name=spec["name"], meta={k: _s(v) for k, v in spec["meta"].items()})
    site = spec.get("site") or {}
    for key, meta_key in (("t_min", "pv_t_min"), ("t_max", "pv_t_max")):
        if site.get(key) not in (None, ""):
            p.meta[meta_key] = _s(site[key])
    s = p.sheets[0]
    s.name = "Jednopólové schéma"
    mod, dc, ac = spec["module"], spec["dc"], spec["ac"]
    opt = spec.get("optimizer") or {}
    opt_per = float(opt.get("per_module") or 1) if opt.get("type") else 0.0
    # svislé rozestupy řad střídačů podle počtu stringů; souřadnice jsou zatím pracovní – na list (formát, střed,
    # vnitřní rámeček, popisové pole) se obsah rozmístí až na konci (`frame.fit_sheet_to_content`)
    row_h = [max(60.0, 45.0 * max(len(inv.get("strings") or [1]), 1) + 15.0) for inv in invs]   # 45 mm na string (popisek nad ním)
    # hybridní střídač: baterie pod ním, v řadě se pro ni přidá místo (kabel jde krátce dolů, přes nic jiného)
    row_extra = [BATTERY_ROW_EXTRA if spec.get("battery") and i == 0 else 0.0 for i in range(len(invs))]
    total_h = sum(row_h) + sum(row_extra)
    y_top = 150.0 + total_h / 2
    n_route = max(0, int(dc.get("route_boxes") or 0))
    n_boxes = n_route + (1 if dc.get("tech_box") else 0)
    box_pitch = 85.0            # mezi rozvaděči se vejde popisek kabelu i dvojitý křížový odkaz
    x_str = 35.0
    n_max = max(len(inv.get("strings") or [1]) for inv in invs)
    x_box0 = x_str + 60.0 + 5.0 * n_max   # lomy stringů až za popisky kabelů u stringů
    x_boxes = [x_box0 + j * box_pitch for j in range(n_boxes)]
    x_dc = 130.0                                                   # samostatný odpínač DC (bez rozvaděčů)
    # před střídačem: popisek kabelu za blokem rozvaděče + vějíř lomů (5 mm na string) před DC vstupy střídače
    x_inv = (x_boxes[-1] + max(80.0, 15.0 + INV_LABEL_SPACE + 5.0 * n_max + 10.0)) if n_boxes else 200.0
    x_blk, x_grid = x_inv + 110.0, x_inv + 185.0   # mezi střídačem a rozvaděčem se vejde popisek AC kabelu
    p_total = 0.0
    blk = Element("fve.switchboard", x_blk, 150.0, attrs={"ref": spec["switchboard"]["ref"], "desc": spec["switchboard"]["desc"]})
    s.elements.append(blk)
    y = y_top
    inverter_elements: list[Element] = []
    dc_boxes: list[tuple[Element, list[Element], str, int, str]] = []   # (blok, stringy, druh, č. střídače, střídač)
    for i, inv in enumerate(invs):
        strings = inv.get("strings") or [1]
        y_mid = y - row_h[i] / 2
        ref_t = inv.get("ref") or f"T{i + 1}"
        t = Element("fve.inverter_hybrid" if spec.get("battery") and i == 0 else "fve.inverter", x_inv, y_mid, attrs={
            "ref": ref_t, "type": _s(inv.get("type")), "p_ac": _s(inv.get("p_ac")), "phases": _s(inv.get("phases", 3)),
            "mppt": _s(inv.get("mppt")), "strings_per_mppt": _s(inv.get("strings_per_mppt")),
            "u_dc_max": _s(inv.get("u_dc_max")), "u_mppt_min": _s(inv.get("u_mppt_min")),
            "u_mppt_max": _s(inv.get("u_mppt_max")), "i_mppt_max": _s(inv.get("i_mppt_max")),
            "p_dc_max": _s(inv.get("p_dc_max"))}, component_id=inv.get("component_id"))
        for key in ("isc_mppt_max", *INVERTER_MODE_KEYS):   # jen zadané – starší specifikace beze změny výstupu
            if inv.get(key) not in (None, ""):
                t.attrs[key] = _s(inv[key])
        # artikl dřív než dopočet MPPT: jeho strings_per_mppt / mppt určí počet DC vstupů
        _apply_inverter_component(t, inv)
        if opt_comp is not None:
            _apply_optimizer_rules(t, inv, opt_comp)
        # neznámé stringů na MPPT zůstane prázdné (kontrola pak proudy na MPPT nesčítá); výchozí 2 jen pro DC vstupy
        spm_known, mppt_known = _int_attr(t.attrs.get("strings_per_mppt")), _int_attr(t.attrs.get("mppt"))
        if not spm_known:
            t.attrs["strings_per_mppt"] = ""
        spm = spm_known or DC_INPUTS_PER_MPPT_DEFAULT
        # známé mppt: stringy rovnoměrně po MPPT (string k → MPPT k mod mppt), jinak DC1, DC2… za sebou (`calc.string_ports`)
        ports = string_ports(len(strings), InverterData(mppt=mppt_known, strings_per_mppt=spm_known))
        if not mppt_known:
            t.attrs["mppt"] = str(max(1, -(-len(strings) // spm)))
        s.elements.append(t)
        inverter_elements.append(t)
        gens: list[Element] = []
        for k, n_mod in enumerate(strings):
            ys = y - 35.0 - k * 45.0
            p_str = round(n_mod * float(str(mod.get("p_wp") or 0).replace(",", ".")) / 1000, 2)
            p_total += p_str
            g = Element("fve.pv_string", x_str, ys, attrs={
                "ref": p.next_ref("G"), "type": _s(mod.get("type")), "n_modules": _s(n_mod), "p_module": _s(mod.get("p_wp")),
                "p_string": f"{p_str:g} kWp", "voc": _s(mod.get("voc")), "vmp": _s(mod.get("vmp")),
                "isc": _s(mod.get("isc")), "beta_voc": _s(mod.get("beta_voc")),
                "n_optimizers": _s(round(n_mod * opt_per)) if opt_per else "", "optimizer": _s(opt.get("type")) if opt_per else ""},
                component_id=mod.get("component_id") or None)
            if opt_comp is not None and opt_per:
                # artikl optimizéru: parametry pro kontrolu stringů, počet zaokrouhlený nahoru (2:1 a lichý počet)
                g.attrs.update(opt_comp.optimizer_values(t.attrs.get("phases") or 3))
                g.attrs["optimizer"] = _s(opt.get("type"))
                g.attrs["n_optimizers"] = _s(math.ceil(n_mod / _modules_per_optimizer(opt_comp)))
            for key in ("imp", "u_sys_max", "manufacturer", "alpha_isc", "gamma_pmax"):   # jen zadané – starší specifikace beze změny výstupu
                if mod.get(key) not in (None, ""):
                    g.attrs[key] = _s(mod[key])
            s.elements.append(g)
            gens.append(g)
        # DC rozvaděče: po trase (odpínač + SPD) a u technologie (pojistkové odpínače + SPD); stringy jimi procházejí odděleně
        boxes: list[Element] = []
        for j in range(n_boxes):
            kind = "tech" if (dc.get("tech_box") and j == n_boxes - 1) else "route"
            desc = f"DC rozvaděč u {ref_t}" if kind == "tech" else (f"DC rozvaděč po trase {ref_t}" + (f" ({j + 1})" if n_route > 1 else ""))
            b = Element("fve.switchboard", x_boxes[j], y_mid, attrs={"ref": p.next_ref("RDC"), "desc": desc})
            s.elements.append(b)
            boxes.append(b)
            dc_boxes.append((b, gens, kind, i + 1, ref_t))
        n_str = len(gens)
        # porty bloku DC rozvaděče (viz switchboard_symbol): rozteč PORT_PITCH, shora dolů
        half = max(20.0, n_str * PORT_PITCH + PORT_PITCH) / 2
        port_y = [y_mid + round((half - PORT_PITCH / 2 - k * PORT_PITCH) / 2.5) * 2.5 for k in range(n_str)]
        n_in = max(2, int(t.attrs["mppt"]) * spm, n_str)   # DC vstupy střídače (viz inverter_symbol)
        for k, g in enumerate(gens):
            port_inv = f"DC{ports[k]}"   # každý string má na střídači vlastní vstup – stringy se nespojují
            j_in = ports[k] - 1          # pořadí vstupu shora (DC1 nahoře)
            if boxes:
                prev, prev_port = g, "DC"
                for j, b in enumerate(boxes):
                    length = dc.get("length") if j == 0 else dc.get("route_length")
                    # string → 1. rozvaděč: lom každého stringu na vlastním x, aby se svislé úseky nekryly
                    pts = [] if j else [(b.x - 15.0 - 5.0 * (n_str - k), g.y), (b.x - 15.0 - 5.0 * (n_str - k), port_y[k])]
                    s.wires.append(Wire(WireEnd(prev.id, prev_port), WireEnd(b.id, f"X{k + 1}"), conductors=list(DC_CONDUCTORS),
                                        points=pts,
                                        attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                               "length": _s(length), "method": "E"}))
                    prev, prev_port = b, f"X{n_str + k + 1}"
                # vějíř lomů těsně před DC vstupy střídače (5 mm rozestup) – za popiskem kabelu, mimo značku střídače;
                # pořadí lomů bez křížení doladí `_align_bends`
                xb = t.x - 10.0 - 5.0 * (n_str - k)
                y_inv = t.y + (2.5 * (n_in - 1) - 5.0 * j_in if n_in > 2 else (5.0 if j_in == 0 else -5.0))
                s.wires.append(Wire(WireEnd(prev.id, prev_port), WireEnd(t.id, port_inv), conductors=list(DC_CONDUCTORS),
                                    points=[(xb, port_y[k]), (xb, y_inv)],
                                    attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                           "length": _s(dc.get("tech_length")), "method": "E"}))
            elif dc.get("disconnect"):
                q = Element("fve.dc_disconnect", x_dc, g.y, attrs={"ref": p.next_ref("Q"), "in_": _s(dc.get("disconnect_in") or 32),
                                                                  "poles": "2", "modules": "2"})
                s.elements.append(q)
                s.wires.append(Wire(WireEnd(g.id, "DC"), WireEnd(q.id, "1"), conductors=list(DC_CONDUCTORS),
                                    attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                           "length": _s(dc.get("length")), "method": "E"}))
                s.wires.append(Wire(WireEnd(q.id, "2"), WireEnd(t.id, port_inv), conductors=list(DC_CONDUCTORS), attrs={"ref": ""}))
            else:
                s.wires.append(Wire(WireEnd(g.id, "DC"), WireEnd(t.id, port_inv), conductors=list(DC_CONDUCTORS),
                                    attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                           "length": _s(dc.get("length")), "method": "E"}))
        # AC vodič ke bloku rozvaděče – port podle přívodu (X1, X2…), doplní se po vytvoření listu
        w_ac = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, f"X{i + 1}"), conductors=list(AC_CONDUCTORS),
                    attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("cable")), "cross": _s(ac.get("cross")),
                           "length": _s(ac.get("length")), "method": "B1"})
        s.wires.append(w_ac)
        y -= row_h[i] + row_extra[i]
    if spec.get("battery"):
        b = spec["battery"]
        t0 = inverter_elements[0]
        n_in0 = inverter_dc_inputs(p, t0)
        inv_half = max(20.0, 5.0 * n_in0 + 5.0) / 2 if n_in0 > 2 else 10.0
        # baterie přímo pod svým (hybridním) střídačem: port BAT dole → port DC baterie nahoře, svisle 15 mm
        bat = Element("fve.battery", t0.x, t0.y - inv_half - 25.0, attrs={
            "ref": "G" + str(len([e for e in s.elements if e.symbol_id == "fve.pv_string"]) + 1),
            "type": _s(b.get("type")), "e_kwh": _s(b.get("e_kwh")), "p_kw": _s(b.get("p_kw"))})
        s.elements.append(bat)
        s.wires.append(Wire(WireEnd(t0.id, "BAT"), WireEnd(bat.id, "DC"), conductors=list(DC_CONDUCTORS),
                            attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": "25", "length": "5"}))
    grid = Element("fve.grid", x_grid, 150.0, attrs={"ref": "", "voltage": _s(spec["grid"].get("voltage")), "dso": _s(spec["grid"].get("dso"))})
    s.elements.append(grid)
    w_grid = Wire(WireEnd(blk.id, "XOUT"), WireEnd(grid.id, "1"), conductors=list(AC_CONDUCTORS),
                  attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("grid_cable")), "cross": _s(ac.get("grid_cross")),
                         "length": _s(ac.get("grid_length")), "method": "D"})
    s.wires.append(w_grid)
    earth = None
    if (ac.get("distribution") or "bus") == "bus":
        # PE rozvaděče je uzemněný na ekvipotenciální svorkovnici (HOP) vně rozvaděče – vývod XPE → uzemnění
        earth = Element("fve.earth", x_blk + 35.0, 150.0 - 40.0, attrs={"ref": "", "desc": "ekvipotenciální svorkovnice (HOP)"})
        s.elements.append(earth)
        s.wires.append(Wire(WireEnd(blk.id, "XPE"), WireEnd(earth.id, "PE"), conductors=["PE"],
                            attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("pe_cable") or "CYA 16"), "cross": _s(ac.get("pe_cross") or 16),
                                   "length": _s(ac.get("pe_length") or 5)}))
    p.meta.setdefault("p_installed_kwp", f"{p_total:g}")
    # listy DC rozvaděčů a AC rozvaděče
    macros = spec.get("macros") or {}
    for b, gens, kind, inv_no, inv_ref in dc_boxes:
        sheet = p.create_switchboard_sheet(b)
        sheet.layout.params.setdefault("network", "DC IT")
        sheet.layout.params.setdefault("un", "max. 1000 V DC")
        entry = macros.get("dc_tech" if kind == "tech" else "dc_route", "")
        if not _dc_box_from_macro(p, sheet, [g.ref for g in gens], entry, dc, inv_no, inv_ref):
            build_dc_strings(p, sheet, [g.ref for g in gens], kind, _s(dc.get("fuse_in") or 15),
                             _s(dc.get("disconnect_in") or 32), _s(dc.get("spd") or "T2"))
    sb = p.create_switchboard_sheet(blk)
    sb.layout.params.setdefault("network", "3NPE, 50 Hz")
    sb.layout.params.setdefault("un", "230/400 V")
    sb.layout.params.setdefault("in_", _s(ac.get("main_in") or 125))
    if not _ac_box_from_macros(p, sb, invs, ac, macros):
        _build_ac_switchboard(p, sb, invs, ac, spec)
    _align_bends(p)
    _align_outputs(p, blk, grid, earth)
    from envocad.model.frame import fit_sheet_to_content
    fit_sheet_to_content(p, s, _lib())
    # až po rozmístění na list: vazby přívodů ukládají texty s polohou v JPS („W3 T1:DC1 /1.F3“)
    sync_feed_links(p)
    sync_cables(p)
    return p


def _align_outputs(project: Project, blk: Element, grid: Element, earth: Element | None) -> None:
    """Síť (DS) na výšku vývodu XOUT bloku AC rozvaděče (vodič vede rovně) a uzemnění (HOP) pod vývod XPE –
    porty bloku jsou známé až po vytvoření listu rozvaděče."""
    from envocad.model.project import element_symbol
    sym = element_symbol(project, blk, _lib())
    names = {pt.name for pt in sym.ports}
    if "XOUT" in names:
        grid.y = blk.port_pos(sym, "XOUT")[1]
    if earth is not None and "XPE" in names:
        earth.y = blk.port_pos(sym, "XPE")[1] - 20.0


def _int_attr(v) -> int | None:
    """Kladné celé číslo z atributu („2“, „2.0“, „2,0“), jinak None."""
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(x) if x >= 1 else None


# údaje modulu ve specifikaci ← atribut prvku `fve.pv_string` (`Component.attr_values()`)
MODULE_SPEC_FROM_ATTR = {"p_module": "p_wp", "voc": "voc", "vmp": "vmp", "isc": "isc", "imp": "imp",
                         "beta_voc": "beta_voc", "u_sys_max": "u_sys_max", "type": "type", "manufacturer": "manufacturer",
                         "alpha_isc": "alpha_isc", "gamma_pmax": "gamma_pmax"}


def _apply_module_component(mod: dict) -> dict:
    """Artikl modulu (`module.component_id`) doplní údaje modulu, které specifikace nezadala (chybí nebo prázdné);
    zadané hodnoty mají přednost. Vrací novou specifikaci modulu; neznámý artikl → beze změny (stringy si
    `component_id` ponechají, kontrola projektu ho nahlásí). Desetinná čárka z CSV se převede na tečku."""
    out = dict(mod)
    comp = _lib().component(mod.get("component_id"))
    if comp is None:
        return out
    for akey, val in comp.attr_values().items():
        skey = MODULE_SPEC_FROM_ATTR.get(akey)
        if skey and out.get(skey) in (None, ""):
            out[skey] = val if skey in ("type", "manufacturer") else val.replace(",", ".")
    out["component_id"] = comp.id
    return out


def _apply_inverter_component(t: Element, inv: dict) -> None:
    """Artikl střídače (`component_id`) doplní atributy, které specifikace nezadala (chybí nebo jsou prázdné) –
    např. typ, výrobce, `mppt` (→ počet DC vstupů), p_dc_max. Zadané hodnoty specifikace mají přednost.
    Neznámý artikl se ignoruje (prvek si `component_id` ponechá, kontrola projektu ho nahlásí)."""
    cid = inv.get("component_id")
    if not cid:
        return
    comp = _lib().component(cid)
    if comp is None:
        return
    probe = Element(t.symbol_id, t.x, t.y, attrs=dict(t.attrs))
    for key, val in comp.apply_to(probe).items():
        if inv.get(key) in (None, ""):
            t.attrs[key] = val
    t.component_id = comp.id


INVERTER_MODE_KEYS = ("string_mode", "u_string", "n_opt_min", "n_opt_max", "p_string_max")


def _modules_per_optimizer(comp) -> int:
    mpo = comp.num("modules_per_optimizer")
    return 2 if mpo == 2 else 1


def _apply_optimizer_component(opt: dict) -> tuple[dict, object | None]:
    """Artikl optimizéru (`optimizer.component_id`): prázdný typ ← part_number, `per_module` ← 1 / modulů na
    optimizér. Vrací (nová specifikace optimizéru, artikl | None); neznámý artikl → beze změny a None."""
    out = dict(opt)
    comp = _lib().component(opt.get("component_id"))
    if comp is None or comp.category != "optimizer":
        return out, None
    if not str(out.get("type") or "").strip():
        out["type"] = comp.part_number
    out["per_module"] = 1 / _modules_per_optimizer(comp)
    out["component_id"] = comp.id
    return out, comp


def _apply_optimizer_rules(t: Element, inv: dict, comp) -> None:
    """Režim stringů a pravidla z artiklu optimizéru do střídače: `string_mode` jen když ho nezadala specifikace ani
    artikl střídače; `n_opt_min` = max, `n_opt_max` = min, `p_string_max` = min ze známých (artikl střídače, artikl
    optimizéru pro fázi střídače); hodnoty ze specifikace vyhrávají."""
    vals = comp.optimizer_values(t.attrs.get("phases") or 3)
    mode = (comp.params.get("string_mode") or "").strip()
    if not str(t.attrs.get("string_mode") or "").strip() and mode:
        t.attrs["string_mode"] = mode
    for key, okey, pick in (("n_opt_min", "opt_n_min", max), ("n_opt_max", "opt_n_max", min),
                            ("p_string_max", "opt_p_string_max", min)):
        if inv.get(key) not in (None, ""):
            continue
        known = [x for x in (_num(t.attrs.get(key)), _num(vals.get(okey))) if x is not None]
        if known:
            t.attrs[key] = f"{pick(known):g}"


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _align_bends(project: Project) -> None:
    """Lomy vodičů JPS podle skutečných poloh portů (porty bloků rozvaděčů a střídačů se dopočítají až z listů):
    svislý úsek [(x, y1), (x, y2)] dostane y1 = port A, y2 = port B – vodič je pak jen vodorovný–svislý–vodorovný."""
    from envocad.model.project import element_symbol
    lib = _lib()
    s = project.sheets[0]
    groups: dict[str, list] = {}
    for w in s.wires:
        if len(w.points) != 2 or abs(w.points[0][0] - w.points[1][0]) > 1e-6:
            continue
        ea, eb = s.element(w.a.element_id), s.element(w.b.element_id)
        try:
            ya = ea.port_pos(element_symbol(project, ea, lib), w.a.port)[1]
            yb = eb.port_pos(element_symbol(project, eb, lib), w.b.port)[1]
        except (KeyError, StopIteration, AttributeError):
            continue
        x = w.points[0][0]
        w.points = [(x, ya), (x, yb)]
        groups.setdefault(w.b.element_id, []).append((w, ya, yb))
    # svislé úseky vodičů do jednoho prvku bez křížení: vodiče shora dolů – nejvyšší nejdál, zdola nahoru – nejnižší nejdál
    for items in groups.values():
        if len(items) < 2:
            continue
        xs = sorted({w.points[0][0] for w, _, _ in items}, reverse=True)
        if len(xs) != len(items):
            continue
        down = sorted((it for it in items if it[2] <= it[1]), key=lambda it: -it[1])
        up = sorted((it for it in items if it[2] > it[1]), key=lambda it: it[1])
        for (w, ya, yb), x in zip(down + up, xs):
            w.points = [(x, ya), (x, yb)]


def _macro_vars(dc: dict, ac: dict) -> dict:
    """Základ hodnot proměnných maker ze specifikace (v `resolve_values` hned za výchozími hodnotami makra)."""
    return {"fuse_in": _s(dc.get("fuse_in") or 15), "disc_in": _s(dc.get("disconnect_in") or 32), "spd": _s(dc.get("spd") or "T2"),
            "breaker_in": _s(ac.get("breaker_in") or 40), "main_in": _s(ac.get("main_in") or 125), "ac_spd": _s(ac.get("spd") or "T1+T2")}


def _macro_ref(entry) -> tuple[str, str | None, dict]:
    """Položka `spec["macros"][role]`: název makra (řetězec) nebo {"name", "value_set", "values"} → (název, sada, hodnoty)."""
    if isinstance(entry, dict):
        return (_s(entry.get("name")).strip(), _s(entry.get("value_set")).strip() or None,
                {str(k): _s(v) for k, v in (entry.get("values") or {}).items()})
    return _s(entry).strip(), None, {}


def _macro_values(m, entry: tuple[str, str | None, dict], base: dict, context: dict, components) -> dict:
    """Hodnoty proměnných makra pro generátor; chyba → ValueError s názvem makra."""
    from envocad.library.macros import resolve_values
    _, value_set, given = entry
    vals, errs = resolve_values(m, given=given, value_set=value_set, components=components, context=context, base=base,
                                repeat=False)   # smyčku stringů drží generátor (počet není omezen max makra)
    if errs:
        raise ValueError(f"Makro „{m.name}“: " + "; ".join(e.removeprefix(f"Makro „{m.name}“: ") for e in errs))
    return vals


def _insert_macro(project: Project, sheet: Sheet, m, values: dict, dx: float, lib) -> list[Element]:
    """Rozvine makro (bez opakování – smyčku drží generátor) a vloží ho do listu; vrací nové přístroje pro rozmístění."""
    from envocad.library.macros import expand, insert
    els, wires = expand(project, sheet, m, values, dx=dx, ref_prefix_of=lambda sid: lib.get_symbol(sid).iec_ref,
                        components=lib.component, repeat=False, copy=False)   # označení z makra beze změny
    insert(sheet, els, wires)
    return [e for e in els if e.modules > 0 and e.symbol_id not in ("sb.feed_in", "sb.feed_out", "sb.busbar")]


def _dc_box_from_macro(project: Project, sheet: Sheet, strings: list[str], name, dc: dict,
                       inv_no: int = 1, inv_ref: str = "") -> bool:
    """DC rozvaděč složený z makra na string. Kontext: k (pořadí v rozvaděči), nk (n + k), n, string (G3),
    i (číslo střídače), j (string u střídače) – ENVO číslování FU{i}.{j}, XS{i}.{j}, STRING {i}.{j} –, inverter;
    základ ze specifikace fuse_in, disc_in, spd. `name` = položka `spec["macros"]` (název nebo objekt). False = makro chybí."""
    from envocad.library.macros import find_macro, macro_pitch
    entry = _macro_ref(name)
    m = find_macro(entry[0]) if entry[0] else None
    if m is None:
        return False
    lib = _lib()
    n = len(strings)
    pitch = macro_pitch(m)
    base = _macro_vars(dc, {})
    devices = []
    for k, g in enumerate(strings, start=1):
        ctx = {"k": k, "nk": n + k, "n": n, "string": g, "i": inv_no, "j": k, "inverter": inv_ref}
        vals = _macro_values(m, entry, base, ctx, lib.component)
        devices += _insert_macro(project, sheet, m, vals, (k - 1) * pitch, lib)
    _place_sequential(sheet, devices)
    return True


def _ac_box_from_macros(project: Project, sheet: Sheet, invs: list[dict], ac: dict, macros: dict) -> bool:
    """AC rozvaděč: makro přívodu na každý střídač (k, i, inverter; breaker_in, main_in) + makro jádra (spd = ac.spd, main_in)."""
    from envocad.library.macros import find_macro, macro_pitch
    ef, ec = _macro_ref(macros.get("ac_feed", "")), _macro_ref(macros.get("ac_core", ""))
    mf = find_macro(ef[0]) if ef[0] else None
    mc = find_macro(ec[0]) if ec[0] else None
    if mf is None or mc is None or (ac.get("distribution") or "bus") != "bus":
        return False
    lib = _lib()
    pitch = macro_pitch(mf)
    devices = []
    base = _macro_vars({}, ac)
    base["spd"] = base["ac_spd"]
    for k, inv in enumerate(invs, start=1):
        ctx = {"k": k, "i": k, "inverter": inv.get("ref") or f"T{k}"}
        devices += _insert_macro(project, sheet, mf, _macro_values(mf, ef, base, ctx, lib.component), (k - 1) * pitch, lib)
    devices += _insert_macro(project, sheet, mc, _macro_values(mc, ec, base, {}, lib.component), len(invs) * pitch, lib)
    _place_sequential(sheet, devices)
    if ac.get("enclosure"):
        sheet.layout.params["type"] = _s(ac["enclosure"])
    return True


def _build_ac_switchboard(project: Project, sheet: Sheet, invs: list[dict], ac: dict, spec: dict) -> None:
    """AC rozvaděč FVE: přívody od střídačů (X1…Xn) → jističe → rozvod → hlavní vypínač → vývod do HDS; SPD, PE lišta.
    Rozvod podle `ac.distribution`: "bus" = sběrnice potenciálů (vodič, jako v EPLAN), "terminals" = rozvodné svorky s můstky."""
    nc = len(AC_CONDUCTORS)
    y = 200.0
    x0 = 60.0
    n = len(invs)
    use_bus = (ac.get("distribution") or "bus") == "bus"
    strip = "X" + str(n + 1)
    feeds: list[Element] = []
    breakers: list[Element] = []
    groups: list[Element] = []
    firsts: list[int] = []
    bus = None
    if use_bus:
        bus = _el(project, sheet, "sb.busbar", x0 + 60, y - 25, "", desc="rozvod AC", in_=str(ac.get("main_in") or 125),
                  conductors=" ".join(AC_CONDUCTORS))
        bus.attrs["ref"] = "1"   # předpona potenciálů: 1L1, 1L2, 1L3, 1N, 1PE
    for i, inv in enumerate(invs):
        x = x0 + i * GROUP_PITCH
        feed = _el(project, sheet, "sb.feed_in", x, y + 40, "", desc=f"od {inv.get('ref') or f'T{i + 1}'}")
        feed.attrs["ref"] = f"X{i + 1}"
        f = _el(project, sheet, "fve.breaker_mcb", x, y + 10, "F", rot=270, in_=str(ac.get("breaker_in") or 40),
                char="B", poles="3", modules="3")
        _wire(project, sheet, feed, "1", f, "1", AC_CONDUCTORS)
        if use_bus:
            _wire(project, sheet, f, "2", bus, f"T{i + 1}", AC_CONDUCTORS)   # shora (od jističů)
        else:
            first = 1 + i * nc
            firsts.append(first)
            grp = _terminal_group(project, sheet, x, y - 30, strip, first, nc, f"střídač {i + 1}")
            _wire(project, sheet, f, "2", grp, "1", AC_CONDUCTORS)
            groups.append(grp)
        feeds.append(feed)
        breakers.append(f)
    x_spd = x0 + n * GROUP_PITCH
    x_out = x0 + (n + 1) * GROUP_PITCH
    spd = _el(project, sheet, "fve.spd", x_spd, y - 60, "F", spd_type=_s(ac.get("spd") or "T1+T2"), poles="4", modules="4")
    q = _el(project, sheet, "sb.main_switch", x_out, y - 60, "Q", rot=270, in_=str(ac.get("main_in") or 125), poles="4", modules="4")
    out = _el(project, sheet, "sb.feed_out", x_out, y - 95, "", desc="do HDS / DS")
    out.attrs["ref"] = "XOUT"
    if use_bus:
        # PE je potenciál sběrnice (1PE); SPD i PE rozvaděče jdou na ekvipotenciální svorkovnici (HOP) vně – vývod XPE
        _wire(project, sheet, bus, "1", spd, "L", AC_CONDUCTORS[:4])   # zdola (vývody)
        _wire(project, sheet, bus, "3", q, "1", AC_CONDUCTORS)
        xpe = _el(project, sheet, "sb.feed_out", x_spd - GROUP_PITCH, y - 95, "", desc="k HOP")
        xpe.attrs["ref"] = "XPE"
        _wire(project, sheet, spd, "PE", xpe, "1", ["PE"])
        _wire(project, sheet, bus, "4", xpe, "1", ["PE"])
    else:
        pe = _el(project, sheet, "sb.pe_bar", x_spd, y - 90, "X", kind="PE")
        # skupina pro SPD a skupina pro hlavní vypínač / vývod
        first = 1 + n * nc
        firsts.append(first)
        g_spd = _terminal_group(project, sheet, x_spd, y - 30, strip, first, nc, "SPD")
        first = 1 + (n + 1) * nc
        firsts.append(first)
        g_out = _terminal_group(project, sheet, x_out, y - 30, strip, first, nc, "vývod")
        project.set_bridges(strip, _bridge_groups(firsts, nc), sheet)
        _wire(project, sheet, g_spd, "2", spd, "L", AC_CONDUCTORS[:4])
        _wire(project, sheet, g_spd, "2", pe, "2", ["PE"])   # PE svorka skupiny → PE lišta
        _wire(project, sheet, g_out, "2", q, "1", AC_CONDUCTORS)
        _wire(project, sheet, spd, "PE", pe, "1", ["PE"])
    _wire(project, sheet, q, "2", out, "1", AC_CONDUCTORS)
    # skupiny rozvodných svorek zabírají na liště počet svorek × šířka svorky (`Element.modules`)
    _place_sequential(sheet, [q, spd, *breakers, *groups, *([g_spd, g_out] if not use_bus else [])])
    if ac.get("enclosure"):
        sheet.layout.params["type"] = _s(ac["enclosure"])


# ---- vstupy průvodce (bez Qt, testovatelné) -------------------------------------------------------------------
def parse_strings(text: str) -> list[list[int]]:
    """„20,20,18; 20 20“ → [[20, 20, 18], [20, 20]]: střídače oddělené středníkem, stringy čárkou nebo mezerou.
    Počet modulů musí být celé kladné číslo; prázdné úseky (koncový středník) se přeskočí. Chyba → ValueError
    s českou hláškou."""
    out: list[list[int]] = []
    for i, part in enumerate(str(text or "").split(";"), start=1):
        tokens = [t for t in part.replace(",", " ").split() if t]
        if not tokens:
            continue
        nums = []
        for t in tokens:
            if not t.isdigit() or int(t) <= 0:
                raise ValueError(f"Stringy (střídač {i}): „{t}“ není celé kladné číslo (počet modulů ve stringu).")
            nums.append(int(t))
        out.append(nums)
    if not out:
        raise ValueError("Stringy: zadejte alespoň jeden string (počty modulů oddělené čárkou nebo mezerou, "
                         "střídače středníkem).")
    return out


def parse_number(text: str, label: str, *, integer: bool = False, minimum: float = 0.0, strict: bool = True,
                 allow_empty: bool = False) -> int | float | str:
    """Číslo z pole průvodce (desetinná čárka i tečka). `strict` = musí být > minimum, jinak ≥ minimum.
    Prázdné pole s `allow_empty` → "". Chyba → ValueError s českou hláškou s názvem pole."""
    t = str(text or "").strip().replace(",", ".")
    if not t:
        if allow_empty:
            return ""
        raise ValueError(f"{label}: zadejte hodnotu.")
    try:
        v = float(t)
    except ValueError:
        raise ValueError(f"{label}: „{text.strip()}“ není číslo.") from None
    if not math.isfinite(v):
        raise ValueError(f"{label}: „{text.strip()}“ není číslo.")
    if integer and not v.is_integer():
        raise ValueError(f"{label}: zadejte celé číslo (ne „{text.strip()}“).")
    if (strict and v <= minimum) or (not strict and v < minimum):
        cmp = "větší než" if strict else "alespoň"
        raise ValueError(f"{label}: hodnota musí být {cmp} {minimum:g}.")
    if integer or v.is_integer() and "." not in t:
        return int(v)
    return v


def load_spec(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__)
        return 2
    spec = load_spec(argv[0])
    p = build_project(spec)
    p.save(argv[1])
    n_el = sum(len(s.elements) for s in p.sheets)
    print(f"{argv[1]}: {len(p.sheets)} listů, {n_el} prvků, {p.meta.get('p_installed_kwp')} kWp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
