"""Generování celého projektu ze specifikace (průvodce v GUI i rozhraní pro agenty). Bez Qt.

    python -m envocad.generate spec.json vystup.ecp

Specifikace (JSON, vše kromě `inverters` volitelné – viz `DEFAULT_SPEC`):
{
  "name": "FVE Firma s.r.o.", "meta": {"investor": "…", "place": "…", "order": "…", "author": "…"},
  "building": "company",                                              # company (firma) | house (rodinný dům) | apartment (bytový dům)
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
         "route_boxes": 1, "route_length": 20,                        # DC rozvaděče po trase (jen SPD, bez odpínače), kabel mezi nimi
         "tech_box": true, "tech_length": 5,                          # DC rozvaděč u technologie (pojistkové odpínače + SPD), kabel ke střídači
         "spd": "T1+T2", "fuse_in": "",                              # "" = podle stringu (gPV ≥ 1,5·Isc; SolarEdge 25 A)
         "disconnect_in": 32, "fuse_component": "eti-efh-10-dc-2p",   # pojistkový odpojovač ETI EFH 10 DC 2p
         "spd_component": "weidmuller-vpu-pv-i-ii-3-1000",            # artikl SPD (typ, Uc, Up, ISCPV), když typ odpovídá
         "disconnect": false},                                        # jen samostatný odpínač v JPS bez DC rozvaděčů (stará varianta)
  "ac": {"cable": "CYKY-J 5x16", "cross": 16, "length": 30, "breaker_in": 40, "main_in": 125,
         "grid_cable": "CYKY-J 5x35", "grid_cross": 35, "grid_length": 20, "spd": "T1+T2", "enclosure": "",
         "distribution": "bus"},                                      # rozvod v AC rozvaděči: "bus" (sběrnice potenciálů) | "terminals" (svorky s můstky)
  "switchboard": {"ref": "RFVE.AC", "desc": "AC rozvaděč FVE"},
  "grid": {"dso": "ČEZ Distribuce", "voltage": "3×400 V"},
  "connection": {"level": "vn", "metering": "nn",                     # "nn" = do HDS (výchozí), "vn" = trafostanice
                 "station": "kiosk", "ts": {"ref": "TS1", "desc": ""}, # kiosk | kobky (zděná) | sloup (sloupová)
                 "u_vn": "22 kV", "loop": true,                       # smyčka = 2 kabelová pole v rozvaděči VN
                 "transformer": {"sn": 630, "ratio": "22/0,42 kV", "group": "Dyn1", "uk": 6},
                 "main_board": {"ref": "RHN", "main_in": "", "load_in": ""},   # "" = ze Sn transformátoru
                 "ct_ratio": "", "fuse_vn": "", "vn_cable": "22-AXEKVCEY 3×1×70", "tr_cable": "4× 1-AYKY 3×240+120"},
  "battery": {"e_kwh": 10, "p_kw": 5, "type": "…"},       # volitelné, jen u hybridního střídače
  "macros": {"dc_tech": "DC string v rozvaděči", "dc_route": "DC string po trase",   # rozvaděče se skládají z maker
             "ac_feed": "AC přívod střídače", "ac_core": "AC jádro rozvaděče"},      # (knihovna → Makra); "" = kód
  "jps": {"split": "auto", "max_paper": "A2", "paper": "A2"}   # rozdělení velkého JPS na listy (viz níže)
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
`building` = druh objektu: u rodinného domu (`house`) je DC i AC rozvaděč v jednom – rozvaděč FVE (RFVE) má přívody
od střídačů X1…Xn, DC přívody stringů a vývody ke střídači (pojistkové odpínače + SPD) a vývod do HDS; samostatný DC
rozvaděč u technologie se netvoří (rozvaděče po trase zůstávají). Firma a bytový dům: DC rozvaděče a AC rozvaděč zvlášť.
Rozvaděče po trase mají jen SPD (přívod vede rovně na vývod) – odpojovací místo stringů jsou pojistkové odpínače
v rozvaděči u střídače.
`site.t_min` / `site.t_max` [°C] se zapíšou do `meta["pv_t_min"]` / `meta["pv_t_max"]` (kontrola stringů,
`calc.design_temperatures`); bez nich platí výchozí −10 / 70 °C.
`jps.split` "auto" (výchozí) rozdělí JPS, které by se nevešlo na `jps.max_paper` (výchozí firemní standard
`jps_max_paper` = A2), na listy formátu `jps.paper` (výchozí = limit): první „Blokové schéma – AC a připojení“
(AC rozvaděč, síť, HOP; u přípojky VN celá přípojka – hlavní rozvaděč nn, transformátor, rozvaděč VN, elektroměrový
rozvaděč, rámeček TS; u rodinného domu rozvaděč FVE s DC i AC částí) jako přehled, za ním listy střídačů („Blokové
schéma – T1–T3“). Vodiče mezi řadou střídače a listem AC (AC kabel „AC-T1“, u rodinného domu i DC vodiče do RFVE a
z něj „RFVE-X5“) vedou přes páry přerušovacích bodů, údaje kabelu nese jen úsek na listu AC. "none" = vždy jeden
list (zvětší se formát). Odvozené jednopólové schéma je stejné jako bez rozdělení. Návrh
`docs/design/dluhy_dxf_jps.md`, bod B.
"""
from __future__ import annotations

import json
import logging
import math
import re
import sys
from itertools import pairwise
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
    element_symbol,
    sync_cables,
    sync_feed_links,
)

log = logging.getLogger("envocad.generate")

BATTERY_ROW_EXTRA = 40.0   # místo pro baterii pod hybridním střídačem (mm)
INV_LABEL_SPACE = 40.0     # popisek DC kabelu („W12  2× H1Z2Z2-K 1x6 mm²“) mezi blokem rozvaděče a lomy ke střídači

# druh objektu (`spec["building"]`) → text v projektu (meta „building“)
BUILDINGS = {"company": "firma", "house": "rodinný dům", "apartment": "bytový dům"}
HOUSE_SWITCHBOARD = {"ref": "RFVE", "desc": "rozvaděč FVE (DC + AC)"}

DEFAULT_SPEC = {
    "name": "Nový projekt FVE",
    "meta": {},
    "building": "company",   # company | house (DC i AC rozvaděč v jednom) | apartment
    "module": {"p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9, "beta_voc": -0.27, "type": ""},
    "site": {},   # {"t_min": -20, "t_max": 70} – návrhové teploty stringů (průvodce předvyplní ze standardu)
    "optimizer": {"type": "", "per_module": 1},
    "dc": {"cable": "H1Z2Z2-K 1x6", "cross": 6, "length": 30, "route_boxes": 1, "route_length": 20,
           "tech_box": True, "tech_length": 5, "spd": "T1+T2", "fuse_in": "", "disconnect_in": 32, "disconnect": False,
           # pojistkový odpojovač stringu (DC-20B – nespínat pod zátěží); "" = bez artiklu
           "fuse_component": "eti-efh-10-dc-2p",
           # artikl svodiče DC (typ, Uc, Up, ISCPV do výkresu) – použije se, když typ `spd` odpovídá artiklu; "" = bez
           "spd_component": "weidmuller-vpu-pv-i-ii-3-1000"},
    "ac": {"cable": "CYKY-J 5x16", "cross": 16, "length": 30, "breaker_in": 40, "main_in": 125,
           "grid_cable": "CYKY-J 5x35", "grid_cross": 35, "grid_length": 20, "spd": "T1+T2", "enclosure": "",
           "distribution": "bus"},
    "switchboard": {"ref": "RFVE.AC", "desc": "AC rozvaděč FVE"},
    "grid": {"dso": "", "voltage": "3×400 V"},
    # připojení k DS: "nn" = AC rozvaděč FVE přímo do DS (HDS); "vn" = trafostanice: hlavní rozvaděč nn,
    # transformátor, rozvaděč VN (pole kioskové TS / kobky zděné TS; sloupová TS bez rozvaděče VN – odpínač, pojistky
    # a svodiče na sloupu) a elektroměrový rozvaděč. Fakturační měření na straně nn (MTP v hlavním rozvaděči) nebo vn
    # (MTP + MTN v měřicím poli VN; ne u sloupové TS). Prázdné hodnoty (main_in, ct_ratio, fuse_vn) se dopočtou ze Sn.
    "connection": {"level": "nn", "metering": "nn", "station": "kiosk", "u_vn": "22 kV", "loop": True,
                   "ts": {"ref": "TS1", "desc": ""},
                   "transformer": {"sn": 630, "type": "", "ratio": "22/0,42 kV", "group": "Dyn1", "uk": 6},
                   "mv_board": {"ref": "RVN", "desc": "rozvaděč VN"},
                   "main_board": {"ref": "RHN", "desc": "hlavní rozvaděč nn", "main_in": "", "load_in": ""},
                   "meter_board": {"ref": "RE", "desc": "elektroměrový rozvaděč"},
                   "ct_ratio": "", "fuse_vn": "",
                   "vn_cable": "22-AXEKVCEY 3×1×70", "vn_cross": 70, "vn_length": 10,
                   "tr_cable": "4× 1-AYKY 3×240+120", "tr_cross": 240, "tr_length": 10,
                   "meas_i_cable": "CYKY-O 7×4", "meas_i_cross": 4, "meas_u_cable": "CYKY-J 5×2,5", "meas_u_cross": "2,5",
                   "meas_length": 5, "load": "spotřeba objektu"},
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
    building = building_kind(spec.get("building"))
    if building == "house" and not spec.get("switchboard"):
        spec["switchboard"] = dict(HOUSE_SWITCHBOARD)
    spec = _merge(DEFAULT_SPEC, spec)
    invs = spec.get("inverters") or []
    if not invs:
        raise ValueError("Specifikace musí obsahovat alespoň jeden střídač (`inverters`).")
    if (spec["ac"].get("distribution") or "bus") == "bus" and len(invs) > AC_MAX_INVERTERS_BUS:
        raise ValueError(f"AC rozvaděč: sběrnice má {AC_MAX_INVERTERS_BUS} přívodů – nejvýš {AC_MAX_INVERTERS_BUS} "
                         f"střídačů (zadáno {len(invs)}). Zvolte rozvod svorkami nebo rozdělte FVE na více rozvaděčů.")
    # rodinný dům: DC část (pojistkové odpínače + SPD, místo rozvaděče u technologie) je v rozvaděči FVE s AC částí
    combined = building == "house" and bool(spec["dc"].get("tech_box"))
    if combined and _s((spec.get("connection") or {}).get("level")).lower() == "vn":
        raise ValueError("Rodinný dům: rozvaděč FVE (DC + AC) se připojuje do HDS – přípojka VN se negeneruje.")
    p = Project(name=spec["name"], meta={k: _s(v) for k, v in spec["meta"].items()})
    p.meta.setdefault("building", BUILDINGS[building])
    site = spec.get("site") or {}
    for key, meta_key in (("t_min", "pv_t_min"), ("t_max", "pv_t_max")):
        if site.get(key) not in (None, ""):
            p.meta[meta_key] = _s(site[key])
    s = p.sheets[0]
    s.name = "Blokové schéma"
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
    n_boxes = n_route + (1 if dc.get("tech_box") else 0)   # u rodinného domu je posledním „rozvaděčem“ rozvaděč FVE
    box_pitch = 85.0            # mezi rozvaděči se vejde popisek kabelu i dvojitý křížový odkaz
    x_str = 35.0
    n_max = max(len(inv.get("strings") or [1]) for inv in invs)
    n_all = sum(len(inv.get("strings") or [1]) for inv in invs)
    # rozvaděč FVE: lomy všech stringů do jednoho bloku a vlevo od něj svislé úseky AC vodičů od střídačů
    n_lanes = n_all + len(invs) if combined else n_max
    dc_first = len(invs) + (1 if (spec["ac"].get("distribution") or "bus") == "bus" else 2)   # za AC přívody (a svorkami X(n+1))
    x_box0 = x_str + 60.0 + 5.0 * n_lanes   # lomy stringů až za popisky kabelů u stringů
    x_boxes = [x_box0 + j * box_pitch for j in range(n_boxes)]
    x_dc = 130.0                                                   # samostatný odpínač DC (bez rozvaděčů)
    # před střídačem: popisek kabelu za blokem rozvaděče + vějíř lomů (5 mm na string) před DC vstupy střídače
    x_inv = (x_boxes[-1] + max(80.0, 15.0 + INV_LABEL_SPACE + 5.0 * n_max + 10.0)) if n_boxes else 200.0
    x_blk, x_grid = x_inv + 110.0, x_inv + 185.0   # mezi střídačem a rozvaděčem se vejde popisek AC kabelu
    if combined:   # rozvaděč FVE na místě DC rozvaděče u technologie (před střídači), síť za střídači
        x_blk, x_grid = x_boxes[-1], x_inv + 75.0
    p_total = 0.0
    blk = Element("fve.switchboard", x_blk, 150.0, attrs={"ref": spec["switchboard"]["ref"], "desc": spec["switchboard"]["desc"]})
    s.elements.append(blk)
    ac_wires: list[Wire] = []
    k_all = 0                   # pořadí stringu v rozvaděči FVE (přes všechny střídače)
    y = y_top
    inverter_elements: list[Element] = []
    rows: list[list[Element]] = []      # prvky řady střídače (střídač, stringy, DC rozvaděče…) – rozdělení JPS na listy
    inverter_strings: list[list[Element]] = []
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
        # pás svorek typu střídače (záloha, komunikace – `inverter_io`) visí pod značkou: místo v řadě
        from envocad.model.inverter_io import inverter_io
        row_extra[i] += 5.0 * len(inverter_io(t.attrs))
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
        row = [t]
        rows.append(row)
        gens: list[Element] = []
        inverter_strings.append(gens)
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
            row.append(g)
        # DC rozvaděče: po trase (jen SPD) a u technologie (pojistkové odpínače + SPD); stringy jimi procházejí odděleně
        boxes: list[Element] = []
        for j in range(n_boxes):
            kind = "tech" if (dc.get("tech_box") and j == n_boxes - 1) else "route"
            if kind == "tech" and combined:
                boxes.append(blk)
                break
            desc = f"DC rozvaděč u {ref_t}" if kind == "tech" else (f"DC rozvaděč po trase {ref_t}" + (f" ({j + 1})" if n_route > 1 else ""))
            b = Element("fve.switchboard", x_boxes[j], y_mid, attrs={"ref": p.next_ref("RDC"), "desc": desc})
            s.elements.append(b)
            boxes.append(b)
            row.append(b)
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
                    port_in, port_out = f"X{k + 1}", f"X{n_str + k + 1}"
                    if b is blk:   # rozvaděč FVE: stringy všech střídačů za AC přívody, lomy (doladí `_align_bends`)
                        port_in, port_out = f"X{dc_first + k_all}", f"X{dc_first + n_all + k_all}"
                        xj = b.x - 15.0 - 5.0 * len(invs) - 5.0 * (n_all - k_all)
                        pts = [(xj, prev.y if j == 0 else port_y[k]), (xj, port_y[k])]
                    s.wires.append(Wire(WireEnd(prev.id, prev_port), WireEnd(b.id, port_in), conductors=list(DC_CONDUCTORS),
                                        points=pts,
                                        attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                               "length": _s(length), "method": "E"}))
                    prev, prev_port = b, port_out
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
                row.append(q)
                s.wires.append(Wire(WireEnd(g.id, "DC"), WireEnd(q.id, "1"), conductors=list(DC_CONDUCTORS),
                                    attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                           "length": _s(dc.get("length")), "method": "E"}))
                s.wires.append(Wire(WireEnd(q.id, "2"), WireEnd(t.id, port_inv), conductors=list(DC_CONDUCTORS), attrs={"ref": ""}))
            else:
                s.wires.append(Wire(WireEnd(g.id, "DC"), WireEnd(t.id, port_inv), conductors=list(DC_CONDUCTORS),
                                    attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                           "length": _s(dc.get("length")), "method": "E"}))
            k_all += 1
        # AC vodič ke bloku rozvaděče – port podle přívodu (X1, X2…), doplní se po vytvoření listu
        w_ac = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, f"X{i + 1}"), conductors=list(AC_CONDUCTORS),
                    attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("cable")), "cross": _s(ac.get("cross")),
                           "length": _s(ac.get("length")), "method": "B1"})
        s.wires.append(w_ac)
        ac_wires.append(w_ac)
        y -= row_h[i] + row_extra[i]
    if spec.get("battery"):
        b = spec["battery"]
        t0 = inverter_elements[0]
        # baterie přímo pod svým (hybridním) střídačem: port BAT dole (pod pásem svorek, je-li) → port DC baterie
        # nahoře, svisle 15 mm
        bat_y = element_symbol(p, t0, _lib()).port("BAT").y
        bat = Element("fve.battery", t0.x, t0.y + bat_y - 25.0, attrs={
            "ref": "G" + str(len([e for e in s.elements if e.symbol_id == "fve.pv_string"]) + 1),
            "type": _s(b.get("type")), "e_kwh": _s(b.get("e_kwh")), "p_kw": _s(b.get("p_kw"))})
        s.elements.append(bat)
        rows[0].append(bat)
        s.wires.append(Wire(WireEnd(t0.id, "BAT"), WireEnd(bat.id, "DC"), conductors=list(DC_CONDUCTORS),
                            attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": "25", "length": "5"}))
    conn = spec.get("connection") or {}
    chain = None
    if _s(conn.get("level")).lower() == "vn":
        # přípojka VN: AC rozvaděč FVE → hlavní rozvaděč nn → transformátor → rozvaděč VN → DS (listy rozvaděčů níže)
        chain = _connection_blocks(p, s, spec, blk, x_blk)
        grid = chain["grids"][0]
    else:
        grid = Element("fve.grid", x_grid, 150.0, attrs={"ref": "", "voltage": _s(spec["grid"].get("voltage")),
                                                         "dso": _s(spec["grid"].get("dso"))})
        s.elements.append(grid)
        s.wires.append(Wire(WireEnd(blk.id, "XOUT"), WireEnd(grid.id, "1"), conductors=list(AC_CONDUCTORS),
                            attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("grid_cable")),
                                   "cross": _s(ac.get("grid_cross")), "length": _s(ac.get("grid_length")), "method": "D"}))
    earth = None
    if (ac.get("distribution") or "bus") == "bus" or combined:
        # PE rozvaděče je uzemněný na ekvipotenciální svorkovnici (HOP) vně rozvaděče – vývod XPE → uzemnění
        earth = Element("fve.earth", x_blk + (42.5 if chain is not None else 35.0), 150.0 - 40.0, attrs={"ref": "", "desc": "ekvipotenciální svorkovnice (HOP)"})
        s.elements.append(earth)
        s.wires.append(Wire(WireEnd(blk.id, "XPE"), WireEnd(earth.id, "PE"), conductors=["PE"],
                            attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("pe_cable") or "CYA 16"), "cross": _s(ac.get("pe_cross") or 16),
                                   "length": _s(ac.get("pe_length") or 5)}))
    p.meta.setdefault("p_installed_kwp", f"{p_total:g}")
    # listy DC rozvaděčů a AC rozvaděče
    macros = spec.get("macros") or {}
    inv_by_ref = {t.ref: t for t in inverter_elements}
    for b, gens, kind, inv_no, inv_ref in dc_boxes:
        sheet = p.create_switchboard_sheet(b)
        sheet.layout.params.setdefault("network", "DC IT")
        sheet.layout.params.setdefault("un", "max. 1000 V DC")
        entry = macros.get("dc_tech" if kind == "tech" else "dc_route", "")
        dc_box = {**dc, "fuse_in": _fuse_in(dc, mod, opt, inv_by_ref.get(inv_ref))}
        if not _dc_box_from_macro(p, sheet, [g.ref for g in gens], entry, dc_box, inv_no, inv_ref):
            build_dc_strings(p, sheet, [g.ref for g in gens], kind, _s(dc_box["fuse_in"]),
                             _s(dc.get("disconnect_in") or 32), _s(dc.get("spd") or "T2"))
        _apply_spd_component(sheet, dc.get("spd_component"))
        _apply_component(sheet, dc.get("fuse_component"), "fve.fuse_disconnect")
    sb = p.create_switchboard_sheet(blk)
    sb.layout.params.setdefault("network", "3NPE, 50 Hz")
    sb.layout.params.setdefault("un", "230/400 V")
    sb.layout.params.setdefault("in_", _s(ac.get("main_in") or 125))
    if not _ac_box_from_macros(p, sb, invs, ac, macros):
        _build_ac_switchboard(p, sb, invs, ac, spec)
    if combined:
        sb.layout.params["network"] = "3NPE, 50 Hz / DC IT"
        sb.layout.params["un"] = "230/400 V AC / max. 1000 V DC"
        groups = [(i + 1, t.ref, [g.ref for g in gens], _fuse_in(dc, mod, opt, t))
                  for i, (t, gens) in enumerate(zip(inverter_elements, inverter_strings))]
        # DC přívody za vším, co AC část označila X<číslo> (PE lišta, svorkovnice); porty JPS se posunou s nimi
        used = [int(m.group(1)) for e in sb.elements if (m := re.fullmatch(r"X(\d+)", e.ref or ""))]
        first = max([dc_first - 1, *used]) + 1
        if first != dc_first:
            for w in s.wires:
                for end in (w.a, w.b):
                    m = re.fullmatch(r"X(\d+)", end.port) if end.element_id == blk.id else None
                    if m and int(m.group(1)) >= dc_first:
                        end.port = f"X{int(m.group(1)) + first - dc_first}"
        _add_dc_part(p, sb, groups, macros.get("dc_tech", ""), dc, first)
        _apply_spd_component(sb, dc.get("spd_component"))
        _apply_component(sb, dc.get("fuse_component"), "fve.fuse_disconnect")
    if chain is not None:
        _build_main_lv_board(p, p.create_switchboard_sheet(chain["rhn"]), conn, ac)
        if chain["rvn"] is not None:
            _build_mv_board(p, p.create_switchboard_sheet(chain["rvn"]), conn)
        _build_meter_board(p, p.create_switchboard_sheet(chain["re"]), conn)
    if combined:
        _align_route_boxes(p, blk, [[b for b, _g, _k, no, _r in dc_boxes if no == i + 1] for i in range(len(invs))])
    _align_bends(p)
    if combined:
        _route_house(p, blk, ac_wires, grid, earth)
    else:
        _align_outputs(p, blk, None if chain else grid, earth)
    if chain is not None:
        _align_connection(p, blk, chain)
    _place_jps(p, s, spec.get("jps") or {}, rows, ac_wires, blk)
    # až po rozmístění na list: vazby přívodů ukládají texty s polohou v JPS („W3 T1:DC1 /1.F3“)
    sync_feed_links(p)
    sync_cables(p)
    return p


def jps_max_paper() -> str:
    """Největší formát jednoho listu JPS z firemního standardu (`standard.jps_max_paper`, výchozí „A2“)."""
    from envocad.settings import load_settings
    try:
        return str(load_settings()["standard"].get("jps_max_paper") or "A2")
    except (OSError, ValueError, KeyError, TypeError):
        return "A2"


JPS_AC_SUFFIX = "AC a připojení"
JPS_AC_SHEET_NAME = "Blokové schéma – " + JPS_AC_SUFFIX   # list generátoru se jmenuje „Blokové schéma“
INTERRUPT_GAP_INV = 15.0   # AC port střídače → port přerušovacího bodu na listu střídače (mm)
INTERRUPT_GAP_BLOCK = 30.0  # port bloku rozvaděče v řadě střídače → přerušovací bod (místo pro odkaz vazby vývodu)
INTERRUPT_GAP_AC = 60.0    # port přerušovacího bodu → port bloku AC rozvaděče (místo pro popisek AC kabelu)


def _place_jps(p: Project, s: Sheet, opts: dict, rows: list[list[Element]], ac_wires: list[Wire],
               blk: Element) -> None:
    """Rozmístí JPS na list (`frame.fit_placement`). Přesáhl by jeden list `jps.max_paper` (jinak standard
    `jps_max_paper`, výchozí A2) a `jps.split` není „none“, rozdělí se JPS na listy formátu `jps.paper` (výchozí
    = limit; jen při 2+ střídačích): první list „AC a připojení“ (blok AC rozvaděče, síť, HOP) jako přehled, za ním
    listy střídačů (stringy → DC rozvaděče → střídač, baterie) balené hladově, dokud se vejdou. Řez vede AC kabelem:
    pár `fve.interrupt` „AC-T1“; údaje kabelu nese jen úsek u bloku AC rozvaděče, úsek u střídače je pokračování bez
    označení a kabelu (`xref.is_blank_wire`).

    Výjimka: řada jednoho střídače (DC řetězec se nedělí), která se sama nevejde ani na `jps.paper`, dostane svůj
    list v nejmenším normalizovaném formátu, do kterého se vejde (A1, A0, jinak „vlastní“) – limit tedy platí pro
    balení řad, ne pro jednu přerostlou řadu (např. 3 střídače × 12 stringů: listy střídačů A1, AC list A2)."""
    from envocad.model.frame import PAPER_SIZES, apply_placement, fit_placement, paper_exceeds
    from envocad.model.textlayout import sheet_content_boxes
    lib = _lib()
    boxes = sheet_content_boxes(p, s, lib)
    if not boxes:
        return
    placement = fit_placement(boxes)
    limit = _s(opts.get("max_paper")) or jps_max_paper()
    if (_s(opts.get("split")) or "auto") == "none" or len(rows) < 2 or not paper_exceeds(placement[0], limit):
        apply_placement(s, placement)     # jeden střídač: DC řetězec se nedělí, oddělit jen AC část nemá smysl
        return
    paper = _s(opts.get("paper")) or limit
    sizes = [x for x in PAPER_SIZES if x[0] == paper] or [x for x in PAPER_SIZES if x[0] == "A2"]
    sheets = _split_jps(p, s, rows, ac_wires, blk, sizes)
    for sh in [s, *sheets]:
        bx = sheet_content_boxes(p, sh, lib)
        if bx:
            pl = fit_placement(bx, sizes)
            if pl[0] == "vlastní":        # řada střídače sama přesahuje formát listu → nejmenší normalizovaný
                pl = fit_placement(bx)
            apply_placement(sh, pl)


def _split_jps(p: Project, s: Sheet, rows: list[list[Element]], ac_wires: list[Wire], blk: Element,
               sizes) -> list[Sheet]:
    """Přesune řady střídačů z `s` na nové listy (hned za `s`) a vodiče mezi řadou a zbytkem listu (AC kabel; u
    rodinného domu i DC vodiče přes rozvaděč FVE, který zůstává na listu „AC a připojení“) přeruší párem
    přerušovacích bodů; `s` zůstane listem „AC a připojení“. Vrací listy střídačů v pořadí."""
    from envocad.model.frame import fit_placement
    from envocad.model.project import INTERRUPT_SYMBOL, element_symbol
    from envocad.model.symbol import rotate_dir
    from envocad.model.textlayout import sheet_content_boxes
    lib = _lib()
    base = s.name or "Blokové schéma"
    s.name = f"{base} – {JPS_AC_SUFFIX}"
    sym_int = lib.get_symbol(INTERRUPT_SYMBOL)
    port_dx = sym_int.port("1").x            # port přerušovacího bodu vlevo od jeho středu (rotace 0)
    ac_ids = {w.id for w in ac_wires}

    def side(e: Element, port: str) -> tuple[float, float, int]:
        """Poloha portu a směr ven (+1 vpravo, −1 vlevo) – přerušovací bod stojí ve směru vodiče od portu."""
        sym = element_symbol(p, e, lib)
        x, y = e.port_pos(sym, port)
        d = rotate_dir(sym.port(port).dir, e.rotation)
        if e.mirror and d in ("E", "W"):
            d = "W" if d == "E" else "E"
        return x, y, (-1 if d == "W" else 1)

    def interrupt(e: Element, port: str, ref: str, gap: float) -> Element:
        x, y, sgn = side(e, port)
        # rotace 0: port vlevo, šipka vpravo (bod vpravo od portu); 180: port vpravo, šipka vlevo
        i = Element(INTERRUPT_SYMBOL, x + sgn * (gap - port_dx), y, rotation=0 if sgn > 0 else 180,
                    attrs={"ref": ref})
        return i

    moves: list[tuple[set[str], list[Wire]]] = []       # (id prvků řady, vodiče řady) pro každý střídač
    for row in rows:
        t = row[0]
        row_ids = {e.id for e in row}
        new_ids: set[str] = set()
        # každý vodič mezi řadou a zbytkem listu (AC kabel k bloku AC rozvaděče; u rodinného domu i DC vodiče
        # stringů do rozvaděče FVE a z něj do střídače) se přeruší párem přerušovacích bodů; údaje kabelu zůstávají
        # u úseku mimo řadu (list „AC a připojení“), úsek u řady je prázdné pokračování
        for w in [w for w in s.wires if (w.a.element_id in row_ids) != (w.b.element_id in row_ids)]:
            inside, outside = (w.a, w.b) if w.a.element_id in row_ids else (w.b, w.a)
            e_in, e_out = s.element(inside.element_id), s.element(outside.element_id)
            ref = f"AC-{t.ref}" if w.id in ac_ids else f"{e_out.ref or 'P'}-{outside.port}"
            # u bloku rozvaděče (DC rozvaděč po trase) má úsek odkaz vazby na vývod („/5.A1“) – delší úsek
            i_in = interrupt(e_in, inside.port, ref,
                             INTERRUPT_GAP_BLOCK if e_in.symbol_id == "fve.switchboard" else INTERRUPT_GAP_INV)
            i_out = interrupt(e_out, outside.port, ref, INTERRUPT_GAP_AC)
            s.elements += [i_in, i_out]
            s.wires.append(Wire(WireEnd(e_in.id, inside.port), WireEnd(i_in.id, "1"), conductors=list(w.conductors),
                                attrs={"ref": ""}))
            if inside is w.a:
                w.a = WireEnd(i_out.id, "1")
            else:
                w.b = WireEnd(i_out.id, "1")
            w.points = []                    # přerušovací bod stojí na výšce portu – vodič vede rovně
            new_ids.add(i_in.id)
        ids = row_ids | new_ids
        moves.append((ids, [w for w in s.wires if w.a.element_id in ids and w.b.element_id in ids]))

    def move(src: Sheet, dst: Sheet, ids: set[str], wires: list[Wire]) -> None:
        dst.elements += [e for e in src.elements if e.id in ids]
        src.elements = [e for e in src.elements if e.id not in ids]
        wset = {w.id for w in wires}
        dst.wires += [w for w in src.wires if w.id in wset]
        src.wires = [w for w in src.wires if w.id not in wset]

    def new_sheet(after: Sheet) -> Sheet:
        sh = Sheet(name=base, func=s.func, loc=s.loc)
        p.sheets.insert(p.sheets.index(after) + 1, sh)
        return sh

    def fits(sh: Sheet) -> bool:
        bx = sheet_content_boxes(p, sh, lib)
        return not bx or fit_placement(bx, sizes)[0] != "vlastní"

    sheets: list[Sheet] = []
    groups: list[list[int]] = []
    for i, (ids, wires) in enumerate(moves):
        if not sheets:
            sheets.append(new_sheet(s))
            groups.append([])
        cur = sheets[-1]
        move(s, cur, ids, wires)
        groups[-1].append(i)
        if len(groups[-1]) > 1 and not fits(cur):     # řada se nevešla – začne nový list
            nxt = new_sheet(cur)
            move(cur, nxt, ids, wires)
            groups[-1].pop()
            sheets.append(nxt)
            groups.append([i])
    for sh, grp in zip(sheets, groups):
        sh.name = f"{base} – " + ref_ranges([rows[i][0].ref for i in grp])
    return sheets


def ref_ranges(refs: list[str]) -> str:
    """Označení do názvu listu: souvislé řady 3+ stejné předpony jako rozsah („T1–T9“), jinak výčet
    („T1, T2“, „T1–T3, T5“). Pořadí se zachová."""
    out: list[str] = []
    run: list[tuple[str, int, str]] = []          # (předpona, číslo, označení)

    def flush() -> None:
        if len(run) >= 3:
            out.append(f"{run[0][2]}–{run[-1][2]}")
        else:
            out.extend(r[2] for r in run)
        run.clear()

    for ref in refs:
        m = re.fullmatch(r"(.*?)(\d+)", ref)
        if m and run and run[-1][0] == m.group(1) and run[-1][1] + 1 == int(m.group(2)):
            run.append((m.group(1), int(m.group(2)), ref))
            continue
        flush()
        if m:
            run.append((m.group(1), int(m.group(2)), ref))
        else:
            out.append(ref)
    flush()
    return ", ".join(out)


def building_kind(v) -> str:
    """Druh objektu ze specifikace: "company" | "house" | "apartment" (přijme i české „firma“, „rodinný dům“, „RD“,
    „bytový dům“, „BD“); prázdné = firma. Neznámá hodnota → ValueError."""
    t = _s(v).strip().lower()
    if not t:
        return "company"
    aliases = {**{k: k for k in BUILDINGS}, **{c: k for k, c in BUILDINGS.items()},
               "rd": "house", "bd": "apartment", "rodinny dum": "house", "bytovy dum": "apartment"}
    if t not in aliases:
        raise ValueError(f"Neznámý druh objektu „{v}“ – zadejte firma, rodinný dům nebo bytový dům.")
    return aliases[t]


def _add_dc_part(p: Project, sheet: Sheet, groups: list[tuple[int, str, list[str], str]], entry, dc: dict,
                 first: int) -> None:
    """DC část rozvaděče FVE rodinného domu (za AC částí): na každý string pojistkový odpínač + SPD (makro
    `dc_tech`, jinak `build_dc_strings`); přívody X{first}…, vývody X{first + n}… přes všechny střídače.
    `groups` = [(č. střídače, střídač, stringy, In pojistek)]. Přístroje se pak rozmístí: DC část, za ní AC."""
    ac_ids = [pl.element_id for pl in sheet.layout.placements]
    dx0 = max((e.x for e in sheet.elements), default=0.0) + 60.0
    n = sum(len(g[2]) for g in groups)
    k0 = first - 1
    done = False
    for inv_no, inv_ref, strings, fuse_in in groups:
        box = {**dc, "fuse_in": fuse_in}
        done = _dc_box_from_macro(p, sheet, strings, entry, box, inv_no, inv_ref, k0=k0, n=n, dx0=dx0)
        if not done:
            break
        k0 += len(strings)
    if not done:   # makro chybí (pak pro žádný střídač): kódem, všechny stringy najednou, číslování jako u makra
        build_dc_strings(p, sheet, [g for grp in groups for g in grp[2]], "tech", _s(groups[0][3]),
                         spd=_s(dc.get("spd") or "T2"), first=first, dx=dx0)
    new = [pl.element_id for pl in sheet.layout.placements if pl.element_id not in ac_ids]
    by_id = {e.id: e for e in sheet.elements}
    _place_sequential(sheet, [by_id[i] for i in [*new, *ac_ids] if i in by_id])


def _align_route_boxes(p: Project, blk: Element, chains: list[list[Element]]) -> None:
    """Rozvaděče po trase rodinného domu na výšku přívodů rozvaděče FVE: vývody posledního rozvaděče trasy leží
    proti DC přívodům RFVE, vodiče vedou rovně (bez lomů, přes které by šly popisky kabelů). Celý řetěz rozvaděčů
    střídače se posune stejně; kdyby se rozvaděče různých střídačů překryly, zůstane lom."""
    lib = _lib()
    s = p.sheets[0]
    plan: list[tuple[list[Element], float, list[Wire]]] = []
    spans: list[tuple[float, float]] = []
    for chain in chains:
        if not chain:
            continue
        last = chain[-1]
        ws = [w for w in s.wires if w.a.element_id == last.id and w.b.element_id == blk.id]
        if not ws:
            continue
        dys = {round(blk.port_pos(element_symbol(p, blk, lib), w.b.port)[1]
                     - last.port_pos(element_symbol(p, last, lib), w.a.port)[1], 3) for w in ws}
        if len(dys) != 1:
            return
        dy = dys.pop()
        half = max(abs(pt.y) for pt in element_symbol(p, last, lib).ports) + PORT_PITCH
        spans.append((last.y + dy - half, last.y + dy + half))
        plan.append((chain, dy, ws))
    spans.sort()
    if any(a[1] > b[0] for a, b in pairwise(spans)):
        return
    for chain, dy, ws in plan:
        for b in chain:
            b.y += dy
        for w in ws:
            w.points = []


def _route_house(p: Project, blk: Element, ac_wires: list[Wire], grid: Element, earth: Element | None) -> None:
    """JPS rodinného domu: rozvaděč FVE stojí před střídači. AC vodiče od střídačů vedou nad vším zpět na přívody
    X1…Xn vlevo (vnější lom pro dolní střídač – bez křížení), vývod XOUT pod vším k síti za střídači, uzemnění (HOP)
    hned pod vývod XPE."""
    from envocad.model.textlayout import sheet_content_boxes
    lib = _lib()
    s = p.sheets[0]

    def port(e: Element, name: str) -> tuple[float, float]:
        return e.port_pos(element_symbol(p, e, lib), name)

    def snap(v: float) -> float:
        return round(v / 2.5) * 2.5

    sheet = p.switchboard_sheet(blk.id)
    names = {e.ref for e in (sheet.elements if sheet else []) if e.symbol_id == "sb.feed_out"}
    w_grid = next(w for w in s.wires if grid.id in (w.a.element_id, w.b.element_id))
    w_earth = next((w for w in s.wires if earth is not None and earth.id in (w.a.element_id, w.b.element_id)), None)
    if earth is not None and "XPE" not in names:   # bez svodičů a PE vývodu (rozvod svorkami) – uzemnění nekreslit
        s.elements.remove(earth)
        s.wires.remove(w_earth)
        earth, w_earth = None, None
    bx = blk.x
    if earth is not None:
        xpe = port(blk, "XPE")
        earth.x, earth.y = bx + 22.5, snap(xpe[1] - 15.0)
        w_earth.points = [(bx + 22.5, xpe[1])]
    # obálky obsahu bez AC vodičů a vodiče k síti (ty se teprve trasují)
    routed = {w.id for w in ac_wires} | {w_grid.id}
    keep = s.wires
    s.wires = [w for w in keep if w.id not in routed]
    try:
        boxes = sheet_content_boxes(p, s, lib)
    finally:
        s.wires = keep
    x_lo = bx - 15.0 - 5.0 * len(ac_wires)
    x_hi = max(port(s.element(w.a.element_id), "AC")[0] for w in ac_wires) + 10.0 + 5.0 * len(ac_wires)
    top = max((b[3] for b in boxes if b[2] >= x_lo and b[0] <= x_hi), default=blk.y)
    y_top = snap(top + 7.5)
    for i, w in enumerate(ac_wires):
        ac = port(s.element(w.a.element_id), "AC")
        feed = port(blk, w.b.port)
        x_r, x_l, lane = ac[0] + 10.0 + 5.0 * i, bx - 20.0 - 5.0 * i, y_top + 5.0 * i
        w.points = [(x_r, ac[1]), (x_r, lane), (x_l, lane), (x_l, feed[1])]
    out = port(blk, "XOUT")
    x_out = bx + 30.0
    if w_earth is not None:   # svislý úsek k síti až za popiskem vodiče k uzemnění
        from envocad.model.textlayout import compute_layout
        lp = compute_layout(p, s, lib).wires.get(w_earth.id)
        x_out = max([x_out, *(snap(b[2] + 5.0) for b in (lp.boxes if lp else []))])
    bottom = min((b[1] for b in boxes if b[2] >= x_out - 5.0 and b[0] <= grid.x + 10.0), default=blk.y)
    grid.y = snap(bottom - 7.5)
    w_grid.points = [(x_out, out[1]), (x_out, grid.y)]


def _fuse_in(dc: dict, mod: dict, opt: dict, inv: Element | None) -> str:
    """In pojistek stringů DC rozvaděče: zadané `dc.fuse_in`, jinak podle stringu (`calc.string_fuse_in`) –
    SolarEdge (střídač nebo optimizéry) 25 A, jinak gPV ≥ 1,5·Isc modulu do 2,4·Isc a max. jištění modulu;
    bez údajů 15 A."""
    if _s(dc.get("fuse_in")).strip() not in ("", "auto"):
        return _s(dc["fuse_in"])
    from envocad.model.calc import string_fuse_in

    def num(v) -> float | None:
        try:
            return float(str(v).replace(",", "."))
        except (TypeError, ValueError):
            return None

    mfr = (inv.attrs.get("manufacturer", "") if inv is not None else "") + " " + _s(opt.get("type"))
    se = "solaredge" in mfr.lower().replace(" ", "")
    fin = string_fuse_in(num(mod.get("isc")), num(mod.get("i_fuse_max")), optimizer=se)
    return f"{fin:g}" if fin else "15"


def _apply_component(sheet: Sheet, cid, symbol_id: str) -> None:
    """Artikl (`dc.fuse_component`) na všechny prvky `symbol_id` listu – typ, výrobce, póly, šířka; In vložky
    zůstává (artikl držáku In nemá). Neznámý nebo prázdný artikl → beze změny."""
    comp = _lib().component(cid) if cid else None
    if comp is None:
        return
    for e in sheet.elements:
        if e.symbol_id == symbol_id:
            comp.apply_to(e)


def _apply_spd_component(sheet: Sheet, cid) -> None:
    """Artikl svodiče DC (`dc.spd_component`) na SPD listu DC rozvaděče, jejichž typ SPD artiklu odpovídá („T1+T2“ =
    „T1+T2 DC“) – typ, výrobce, Uc, Up, ISCPV ve výkresu. Jiný zadaný typ (`dc.spd` „T2“) artikl nepřepíše;
    neznámý nebo prázdný artikl → beze změny."""
    comp = _lib().component(cid) if cid else None
    if comp is None:
        return

    def norm(t: str) -> str:
        return "".join(t.upper().replace("DC", "").split())

    for e in sheet.elements:   # jen svodiče DC (rozvaděč FVE rodinného domu má i svodič AC)
        if e.symbol_id == "fve.spd" and "DC" in e.attrs.get("spd_type", "").upper() \
                and norm(e.attrs.get("spd_type", "")) == norm(comp.params.get("spd_type", "")):
            comp.apply_to(e)


def _align_outputs(project: Project, blk: Element, grid: Element | None, earth: Element | None) -> None:
    """Síť (DS) na výšku vývodu XOUT bloku AC rozvaděče (vodič vede rovně) a uzemnění (HOP) pod vývod XPE –
    porty bloku jsou známé až po vytvoření listu rozvaděče."""
    from envocad.model.project import element_symbol
    sym = element_symbol(project, blk, _lib())
    names = {pt.name for pt in sym.ports}
    if "XOUT" in names and grid is not None:
        grid.y = blk.port_pos(sym, "XOUT")[1]
    if earth is not None and "XPE" in names:
        earth.y = blk.port_pos(sym, "XPE")[1] - 20.0


# ---- přípojka VN: hlavní rozvaděč nn, transformátor, rozvaděč VN -------------------------------------------------
LV_BREAKER_SIZES = (100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3200, 4000)
CT_PRIMARY_SIZES = (5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 150, 200, 250, 300, 400, 500, 600, 750, 800, 1000,
                    1200, 1250, 1500, 1600, 2000, 2500, 3000, 4000)
VN_FUSE_SIZES = (6.3, 10, 16, 20, 25, 31.5, 40, 50, 63, 80, 100)
VN_FUSE_FACTOR = 1.8          # pojistka VN transformátoru ≈ 1,8 × In VN (tabulky výrobců pojistek – ověřit)
VN_BREAKER_FROM_KVA = 1000.0  # nad 1000 kVA transformátorové pole s vypínačem a ochranou místo pojistek
U_LV, U_MV_DEFAULT = 400.0, 22000.0
VN_CONDUCTORS = ["L1", "L2", "L3"]
CT_CONDUCTORS, VT_CONDUCTORS = ["S1", "S2"], ["a", "n"]   # sekundár MTP / MTN k elektroměru


def _next_size(value: float, sizes) -> float:
    """Nejmenší normalizovaná hodnota ≥ value (nad řadou největší)."""
    return next((x for x in sizes if x >= value - 1e-9), sizes[-1])


def _num_or(v, default: float) -> float:
    try:
        return float(str(v).replace(",", ".").split()[0])
    except (TypeError, ValueError, IndexError):
        return default


STATIONS = {"kiosk": ("kiosková trafostanice", "P", "pole"),
            "kobky": ("zděná trafostanice", "K", "kobka"),
            "sloup": ("sloupová trafostanice", "", "")}
CELL_NAMES = {"pole": {"cable": "kabelové pole", "meas": "měřicí pole", "tr": "transformátorové pole"},
              "kobka": {"cable": "kabelová kobka", "meas": "měřicí kobka", "tr": "transformátorová kobka"}}


def station_kind(conn: dict) -> str:
    """Druh trafostanice: kiosk (výchozí, rozvaděč VN po polích) | kobky (zděná TS) | sloup (bez rozvaděče VN)."""
    k = _s(conn.get("station") or "kiosk").lower()
    return k if k in STATIONS else "kiosk"


def station_label(conn: dict) -> str:
    """Text rámečku trafostanice v jednopólovém schématu (atribut `station` bloků): „TS1 kiosková trafostanice“."""
    ts = conn.get("ts") or {}
    desc = _s(ts.get("desc")) or STATIONS[station_kind(conn)][0]
    return f"{_s(ts.get('ref') or 'TS1')} {desc}".strip()


def connection_currents(conn: dict) -> dict:
    """Jmenovité proudy přípojky VN ze Sn transformátoru: In nn / vn, hlavní jistič nn, převod MTP, pojistky VN.
    Zadané `main_board.main_in`, `ct_ratio`, `fuse_vn` mají přednost. Sloupová TS měří vždy na nn."""
    tr = conn.get("transformer") or {}
    sn = _num_or(tr.get("sn"), 630.0)
    u_mv = _num_or(conn.get("u_vn"), U_MV_DEFAULT / 1000) * 1000
    i_lv = sn * 1000 / (math.sqrt(3) * U_LV)
    i_mv = sn * 1000 / (math.sqrt(3) * u_mv)
    mb = conn.get("main_board") or {}
    main_in = _num_or(mb.get("main_in"), 0) or _next_size(i_lv, LV_BREAKER_SIZES)
    metering = _s(conn.get("metering") or "nn").lower()
    if station_kind(conn) == "sloup":
        metering = "nn"
    i_ct = i_lv if metering == "nn" else i_mv
    ct = _s(conn.get("ct_ratio")) or f"{_next_size(i_ct, CT_PRIMARY_SIZES):g}/5 A"
    fuse = _s(conn.get("fuse_vn")) or f"{_next_size(i_mv * VN_FUSE_FACTOR, VN_FUSE_SIZES):g}".replace(".", ",")
    return {"sn": sn, "u_mv": u_mv, "i_lv": i_lv, "i_mv": i_mv, "main_in": f"{main_in:g}", "ct_ratio": ct,
            "fuse_vn": fuse, "metering": metering, "breaker_vn": sn > VN_BREAKER_FROM_KVA}


def _connection_blocks(p: Project, s: Sheet, spec: dict, blk: Element, x0: float) -> dict:
    """Bloky přípojky VN v blokovém schématu: AC rozvaděč FVE (XOUT) → hlavní rozvaděč nn → transformátor → rozvaděč VN → DS;
    u sloupové TS místo rozvaděče VN pojistky VN, svodiče přepětí a úsekový odpínač na sloupu. Rozvaděče nn a VN
    jsou napájené ze strany DS (přívod = XT u hlavního rozvaděče, XDS1/XDS2 u rozvaděče VN), FVE je vývod X1
    hlavního rozvaděče – bloky i transformátor jsou zrcadlené, aby přívody ležely vpravo (k DS) a vodiče vedly zleva
    doprava rovně. Spotřeba objektu (vývod X2) leží pod vývodem FVE, elektroměrový rozvaděč (měřicí obvody XMI/XMU
    od MTP/MTN) pod rozvaděčem s měřením. Všechny části trafostanice mají atribut `station` (rámeček TS)."""
    conn, ac = spec["connection"], spec["ac"]
    tr_spec, mb, vb = conn.get("transformer") or {}, conn.get("main_board") or {}, conn.get("mv_board") or {}
    eb = conn.get("meter_board") or {}
    kind = station_kind(conn)
    station = station_label(conn)
    c = connection_currents(conn)
    u = _s(conn.get("u_vn") or "22 kV")
    x_rhn = x0 + 85.0
    x_tr = x_rhn + 75.0
    x_rvn = x_tr + 75.0
    x_grid = x_rvn + 70.0
    rhn = Element("fve.switchboard", x_rhn, 150.0, mirror=True, attrs={
        "ref": _s(mb.get("ref") or "RHN"), "desc": _s(mb.get("desc") or "hlavní rozvaděč nn"), "station": station})
    s.elements.append(rhn)
    tr = Element("fve.transformer", x_tr, 150.0, mirror=True, attrs={
        "ref": p.next_ref("TR"), "type": _s(tr_spec.get("type")), "sn": _s(tr_spec.get("sn")),
        "ratio": _s(tr_spec.get("ratio")), "group": _s(tr_spec.get("group")), "uk": _s(tr_spec.get("uk")),
        "station": station})
    s.elements.append(tr)
    rvn = None
    pole: list[Element] = []
    if kind == "sloup":
        # na sloupu (tok zprava = od DS): úsekový odpínač → pojistky VN → transformátor, svodiče přepětí za pojistkami
        qs = Element("fve.switch_disconnector_vn", x_tr + 70.0, 150.0, mirror=True, attrs={
            "ref": p.next_ref("QS"), "type": "úsekový odpínač VN", "poles": "3", "station": station})
        fu = Element("fve.fuse_vn", x_tr + 40.0, 150.0, mirror=True, attrs={
            "ref": p.next_ref("FU"), "type": "pojistka VN", "in_": c["fuse_vn"], "poles": "3", "station": station})
        fv = Element("fve.surge_arrester", x_tr + 22.5, 130.0, rotation=270, attrs={
            "ref": p.next_ref("FV"), "type": "svodič přepětí VN", "poles": "3", "station": station})
        pole = [qs, fu, fv]
        s.elements.extend(pole)
        x_grid = x_tr + 110.0
    else:
        rvn = Element("fve.switchboard", x_rvn, 150.0, mirror=True, attrs={
            "ref": _s(vb.get("ref") or "RVN"), "desc": _s(vb.get("desc") or "rozvaděč VN"), "station": station})
        s.elements.append(rvn)
    re_ = Element("fve.switchboard", x_rhn if c["metering"] == "nn" or rvn is None else x_rvn, 70.0, attrs={
        "ref": _s(eb.get("ref") or "RE"), "desc": _s(eb.get("desc") or "elektroměrový rozvaděč"), "station": station})
    s.elements.append(re_)
    grids = []
    for k in range(2 if conn.get("loop") and kind != "sloup" else 1):
        g = Element("fve.grid", x_grid, 150.0 - 10.0 * k, attrs={"ref": "", "voltage": f"3~ {u}, 50 Hz",
                                                                 "dso": _s(spec["grid"].get("dso"))})
        s.elements.append(g)
        grids.append(g)
    # spotřeba objektu: vývod X2 je vlevo (zrcadlený blok) – značka pod blokem, otočená portem nahoru
    load = Element("fve.load", x_rhn, 110.0, attrs={"ref": "", "desc": _s(conn.get("load") or "spotřeba objektu")})
    s.elements.append(load)

    def cable(a, pa, b, pb, conductors, prefix, points=None, cross=None):
        s.wires.append(Wire(WireEnd(a.id, pa), WireEnd(b.id, pb), conductors=list(conductors), points=points or [],
                            attrs={"ref": p.next_ref("W"), "cable": _s(conn.get(f"{prefix}_cable")),
                                   "cross": _s(conn.get(cross or f"{prefix}_cross")),
                                   "length": _s(conn.get(f"{prefix}_length") or conn.get("meas_length")),
                                   "method": "D"}))

    def plain(a, pa, b, pb, conductors):          # spoj bez kabelu (na sloupu: vodiče, lana)
        s.wires.append(Wire(WireEnd(a.id, pa), WireEnd(b.id, pb), conductors=list(conductors), attrs={"ref": ""}))

    s.wires.append(Wire(WireEnd(blk.id, "XOUT"), WireEnd(rhn.id, "X1"), conductors=list(AC_CONDUCTORS),
                        attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("grid_cable")), "cross": _s(ac.get("grid_cross")),
                               "length": _s(ac.get("grid_length")), "method": "D"}))
    cable(rhn, "XT", tr, "2", AC_CONDUCTORS, "tr")
    if rvn is not None:
        cable(tr, "1", rvn, "X1", VN_CONDUCTORS, "vn")
        for k, g in enumerate(grids):
            cable(rvn, f"XDS{k + 1}", g, "1", VN_CONDUCTORS, "vn")
    else:
        qs, fu, fv = pole
        plain(grids[0], "1", qs, "1", VN_CONDUCTORS)
        plain(qs, "2", fu, "1", VN_CONDUCTORS)
        plain(fu, "2", tr, "1", VN_CONDUCTORS)
        plain(fu, "2", fv, "1", VN_CONDUCTORS)
    # měřicí obvody do elektroměrového rozvaděče: proud z MTP (XMI), napětí z přípojnice nn / MTN (XMU)
    src = rhn if c["metering"] == "nn" or rvn is None else rvn
    cable(src, "XMI", re_, "XMI", CT_CONDUCTORS, "meas_i", cross="meas_i_cross")
    cable(src, "XMU", re_, "XMU", AC_CONDUCTORS[:4] if src is rhn else VT_CONDUCTORS, "meas_u", cross="meas_u_cross")
    # stávající rozvod objektu – bez kabelu (projektant doplní podle skutečnosti)
    s.wires.append(Wire(WireEnd(rhn.id, "X2"), WireEnd(load.id, "1"), conductors=list(AC_CONDUCTORS), attrs={"ref": ""}))
    return {"rhn": rhn, "tr": tr, "rvn": rvn, "re": re_, "src": src, "pole": pole, "grids": grids, "load": load}


def _build_main_lv_board(p: Project, sheet: Sheet, conn: dict, ac: dict) -> None:
    """Hlavní rozvaděč nn (napájený z transformátoru): přívod XT → [MTP, měření na nn: sekundár → XMI, napětí
    z přípojnice → XMU k elektroměrovému rozvaděči] → hlavní jistič → přípojnice nn → vývody: FVE (jistič → X1 k AC rozvaděči FVE),
    SPD T1, spotřeba objektu (jistič → X2)."""
    c = connection_currents(conn)
    mb = conn.get("main_board") or {}
    sheet.layout.params.setdefault("network", "3NPE, 50 Hz")
    sheet.layout.params.setdefault("un", "230/400 V")
    sheet.layout.params.setdefault("in_", c["main_in"])
    x0, y = 60.0, 165.0
    feed = _el(p, sheet, "sb.feed_in", x0, y + 70, "", desc="od transformátoru")
    feed.attrs["ref"] = "XT"
    qm = _el(p, sheet, "fve.breaker_mccb", x0, y + 10, "Q", rot=270, in_=c["main_in"], poles="3", modules="9")
    bus = _el(p, sheet, "sb.busbar", x0 + 75, y - 25, "", desc="přípojnice nn", in_=c["main_in"],
              conductors=" ".join(AC_CONDUCTORS))
    bus.attrs["ref"] = "2"
    if c["metering"] == "nn":
        ta = _el(p, sheet, "fve.ct", x0, y + 40, "TA", rot=270, ratio=c["ct_ratio"], cls="0,5S", burden="5", n="3",
                 poles="3")
        # měřicí obvody vpravo nahoru: proud ze sekundáru MTP (XMI), napětí z přípojnice (XMU, jištění v RE)
        xmi = _el(p, sheet, "sb.feed_out", x0 + 105, y + 50, "", desc="proudové obvody k RE")
        xmi.attrs["ref"] = "XMI"
        xmu = _el(p, sheet, "sb.feed_out", x0 + 120, y + 50, "", desc="napěťové obvody k RE")
        xmu.attrs["ref"] = "XMU"
        _wire(p, sheet, feed, "1", ta, "1", AC_CONDUCTORS)
        _wire(p, sheet, ta, "2", qm, "1", AC_CONDUCTORS)
        _wire(p, sheet, ta, "S", xmi, "1", CT_CONDUCTORS).points = [(x0 + 105, y + 40)]
        _wire(p, sheet, bus, "T8", xmu, "1", AC_CONDUCTORS[:4])
    else:
        _wire(p, sheet, feed, "1", qm, "1", AC_CONDUCTORS)
    _wire(p, sheet, qm, "2", bus, "IN", AC_CONDUCTORS)
    qf = _el(p, sheet, "fve.breaker_mccb", x0 + 7.5, y - 60, "Q", rot=270, in_=str(ac.get("main_in") or 125), poles="3",
             modules="6")
    out_f = _el(p, sheet, "sb.feed_out", x0 + 7.5, y - 95, "", desc="k RFVE.AC (FVE)")
    out_f.attrs["ref"] = "X1"
    spd = _el(p, sheet, "fve.spd", x0 + 37.5, y - 60, "F", spd_type="T1", poles="4", modules="4")
    pe = _el(p, sheet, "sb.pe_bar", x0 + 37.5, y - 90, "X", kind="PE")
    # vývod spotřeby nejvýš In hlavního jističe / 1,6 (selektivita – poměr jako kontrola `calc_selectivity`)
    load_in = _s(mb.get("load_in")) or f"{max([x for x in LV_BREAKER_SIZES if x * 1.6 <= float(c['main_in'])] or [100]):g}"
    qs = _el(p, sheet, "fve.breaker_mccb", x0 + 67.5, y - 60, "Q", rot=270, in_=load_in,
             poles="3", modules="6")
    out_s = _el(p, sheet, "sb.feed_out", x0 + 67.5, y - 95, "", desc=_s(conn.get("load") or "spotřeba objektu"))
    out_s.attrs["ref"] = "X2"
    _wire(p, sheet, bus, "1", qf, "1", AC_CONDUCTORS)
    _wire(p, sheet, qf, "2", out_f, "1", AC_CONDUCTORS)
    _wire(p, sheet, bus, "3", spd, "L", AC_CONDUCTORS[:4])
    _wire(p, sheet, spd, "PE", pe, "1", ["PE"])
    _wire(p, sheet, bus, "5", qs, "1", AC_CONDUCTORS)
    _wire(p, sheet, qs, "2", out_s, "1", AC_CONDUCTORS)
    _place_sequential(sheet, [qm, qf, qs, spd])


def _build_mv_board(p: Project, sheet: Sheet, conn: dict) -> None:
    """Rozvaděč VN napájený z DS, samostatná pole (kiosková TS) / kobky (zděná TS) pod přípojnicí – každý přístroj
    nese atribut `cell` (název pole, v jednopólovém schématu vlastní rámeček):
    kabelová pole (přívod XDS1, u smyčky i XDS2 ← kabelová koncovka ← odpínač VN z přípojnice; uzemňovač
    a kapacitní indikátor napětí na straně kabelu) → přípojnice VN → [měřicí pole: odpínač, MTP, MTN, sekundáry →
    XMI/XMU k elektroměrovému rozvaděči → přípojnice odběratele] → transformátorové pole (odpínač + pojistky VN
    s úderníkem, nad 1000 kVA vypínač VN s ochranou; uzemňovač, kabelová koncovka) → vývod XT k transformátoru.
    Přístroje se na DIN lišty nerozmísťují, rozvaděč nemá vícepól ani plán svorkovnice."""
    c = connection_currents(conn)
    u = _s(conn.get("u_vn") or "22 kV")
    _desc, letter, word = STATIONS[station_kind(conn)]
    names = CELL_NAMES[word]
    sheet.layout.params.setdefault("network", "3~ 50 Hz")
    sheet.layout.params.setdefault("un", u)
    sheet.layout.params["voltage_level"] = "vn"     # bez vícepólu a plánu svorkovnice (`multipole.has_multipole`)
    x0, y = 60.0, 240.0 if c["metering"] == "vn" else 210.0
    cell_no = 0

    def cell(kind: str) -> str:
        nonlocal cell_no
        cell_no += 1
        return f"{letter}{cell_no} {names[kind]}"

    def el(sid, x, yy, prefix, cell_name, rot=270, **attrs):
        e = _el(p, sheet, sid, x, yy, prefix, rot=rot, **attrs)
        e.attrs["cell"] = cell_name
        return e

    bus = _el(p, sheet, "sb.busbar", x0 + 75, y, "", desc="přípojnice VN", conductors=" ".join(VN_CONDUCTORS))
    bus.attrs["ref"] = "1"
    port_x = lambda b, k: b.x - 67.5 + 15 * (k - 1)      # spodní port k přípojnice
    for k in range(2 if conn.get("loop") else 1):
        cn = cell("cable")
        x = port_x(bus, 1 + 3 * k)
        ql = el("fve.switch_disconnector_vn", x, y - 22.5, "Q", cn, type="odpínač VN", poles="3", modules="0")
        ke = el("fve.cable_end", x, y - 67.5, "XK", cn, poles="3", modules="0")
        qe = el("fve.earthing_switch", x + 12.5, y - 45, "Q", cn)
        pv = el("fve.voltage_indicator", x - 12.5, y - 45, "P", cn, type="VDS")
        feed = el("sb.feed_in", x, y - 97.5, "", cn, rot=180, desc="z DS")
        feed.attrs["ref"] = f"XDS{k + 1}"
        _wire(p, sheet, feed, "1", ke, "2", VN_CONDUCTORS)
        _wire(p, sheet, ke, "1", ql, "2", VN_CONDUCTORS)
        _wire(p, sheet, ql, "2", qe, "1", VN_CONDUCTORS).points = [(x + 12.5, y - 30)]
        _wire(p, sheet, ql, "2", pv, "1", VN_CONDUCTORS).points = [(x - 12.5, y - 30)]
        _wire(p, sheet, bus, str(1 + 3 * k), ql, "1", VN_CONDUCTORS)
    k_next = 7 if conn.get("loop") else 4
    xc = port_x(bus, k_next)
    last, port = bus, str(k_next)
    y_t = y
    if c["metering"] == "vn":
        cn = cell("meas")
        qm = el("fve.switch_disconnector_vn", xc, y - 22.5, "Q", cn, type="odpínač VN", poles="3", modules="0")
        ta = el("fve.ct", xc, y - 45, "TA", cn, ratio=c["ct_ratio"], cls="0,2S", burden="5", n="3", poles="3")
        tv = el("fve.vt", xc + 30, y - 62.5, "TV", cn, ratio=f"{u.split()[0]}/√3 / 0,1/√3 kV", cls="0,2", n="3")
        # sekundáry vpravo dolů do vývodů měřicích obvodů (k elektroměrovému rozvaděči)
        xmi = el("sb.feed_out", xc + 50, y - 60, "", cn, rot=0, desc="proudové obvody k RE")
        xmi.attrs["ref"] = "XMI"
        xmu = el("sb.feed_out", xc + 50, y - 95, "", cn, rot=0, desc="napěťové obvody k RE")
        xmu.attrs["ref"] = "XMU"
        _wire(p, sheet, bus, port, qm, "1", VN_CONDUCTORS)
        _wire(p, sheet, qm, "2", ta, "1", VN_CONDUCTORS)
        _wire(p, sheet, ta, "2", tv, "1", VN_CONDUCTORS).points = [(xc + 30, y - 52.5)]
        _wire(p, sheet, ta, "S", xmi, "1", CT_CONDUCTORS).points = [(xc + 50, y - 45)]
        _wire(p, sheet, tv, "S", xmu, "1", VT_CONDUCTORS).points = [(xc + 30, y - 85), (xc + 50, y - 85)]
        # přípojnice odběratele pod měřicím polem (měření je v sérii s transformátorovým polem)
        y_t = y - 115
        bus2 = _el(p, sheet, "sb.busbar", xc + 60, y_t, "", desc="přípojnice VN odběratele",
                   conductors=" ".join(VN_CONDUCTORS))
        bus2.attrs["ref"] = "1.1"
        _wire(p, sheet, ta, "2", bus2, "T1", VN_CONDUCTORS)
        last, port = bus2, "1"
        xc = port_x(bus2, 1)
    cn = cell("tr")
    if c["breaker_vn"]:
        qt = el("fve.breaker_vn", xc, y_t - 22.5, "Q", cn, type="vypínač VN", protection="nadproudová 50/51",
                poles="3", modules="0")
        _wire(p, sheet, last, port, qt, "1", VN_CONDUCTORS)
        prot = qt
    else:
        qt = el("fve.switch_disconnector_vn", xc, y_t - 22.5, "Q", cn, type="odpínač VN", poles="3", modules="0")
        fu = el("fve.fuse_vn", xc, y_t - 45, "F", cn, in_=c["fuse_vn"], poles="3", modules="0", type="pojistka VN")
        _wire(p, sheet, last, port, qt, "1", VN_CONDUCTORS)
        _wire(p, sheet, qt, "2", fu, "1", VN_CONDUCTORS)
        prot = fu
    ke = el("fve.cable_end", xc, y_t - 85, "XK", cn, poles="3", modules="0")
    qe = el("fve.earthing_switch", xc + 12.5, y_t - 67.5, "Q", cn)
    out = el("sb.feed_out", xc, y_t - 110, "", cn, rot=0, desc="k transformátoru")
    out.attrs["ref"] = "X1"          # řadí se před vývody měřicích obvodů XMI/XMU (port bloku nahoře, k transformátoru)
    _wire(p, sheet, prot, "2", ke, "1", VN_CONDUCTORS)
    _wire(p, sheet, prot, "2", qe, "1", VN_CONDUCTORS).points = [(xc + 12.5, y_t - 55)]
    _wire(p, sheet, ke, "2", out, "1", VN_CONDUCTORS)


def _build_meter_board(p: Project, sheet: Sheet, conn: dict) -> None:
    """Elektroměrový rozvaděč: přívody měřicích obvodů XMI (proud z MTP) a XMU (napětí z přípojnice nn / MTN) →
    fakturační elektroměr (DS)."""
    c = connection_currents(conn)
    sheet.layout.params.setdefault("network", "měřicí obvody")
    sheet.layout.params.setdefault("un", "3×230/400 V, 5 A" if c["metering"] == "nn" else "3×100/√3 V, 5 A")
    x0, y = 60.0, 165.0
    xmi = _el(p, sheet, "sb.feed_in", x0, y + 40, "", desc="proudové obvody z MTP")
    xmi.attrs["ref"] = "XMI"
    xmu = _el(p, sheet, "sb.feed_in", x0 + 30, y + 40, "", desc="napěťové obvody")
    xmu.attrs["ref"] = "XMU"
    # elektroměr svisle (jako dřív v hlavním rozvaděči): proud zleva shora do 1, napětí zprava zdola do 2 – ve
    # vícepólu žíly míjí popisek elektroměru
    pm = _el(p, sheet, "fve.meter", x0 + 15, y, "P", rot=270, kind="fakturační (DS)", modules="0")
    xmi.x, xmu.x = x0 - 15, x0 + 45
    _wire(p, sheet, xmi, "1", pm, "1", CT_CONDUCTORS).points = [(x0 - 15, y + 20), (x0 + 15, y + 20)]
    _wire(p, sheet, xmu, "1", pm, "2", AC_CONDUCTORS[:4] if c["metering"] == "nn" else VT_CONDUCTORS).points = [
        (x0 + 45, y - 20), (x0 + 15, y - 20)]


def _align_connection(project: Project, blk: Element, chain: dict) -> None:
    """Bloky přípojky na výšku vodičů (vodiče vedou rovně): hlavní rozvaděč nn na XOUT bloku AC rozvaděče FVE, transformátor na
    přívod XT, rozvaděč VN vývodem X1 na transformátor (u sloupové TS přístroje na sloupu na port transformátoru),
    sítě na přívody XDS; spotřeba pod vývod X2, elektroměrový rozvaděč pod rozvaděč s měřením."""
    lib = _lib()
    sheet = project.sheets[0]

    def port_pos(e: Element, port: str) -> tuple[float, float] | None:
        sym = element_symbol(project, e, lib)
        return e.port_pos(sym, port) if any(pt.name == port for pt in sym.ports) else None

    def align(e: Element, port: str, target) -> None:
        pos = port_pos(e, port)
        if pos is not None and target is not None:
            e.y += target[1] - pos[1]

    def bottom_of(e: Element) -> float:
        sym = element_symbol(project, e, lib)
        return e.y - max(abs(pt.y) for pt in sym.ports)

    def wire_to(eid: str, port: str | None = None):
        return [w for w in sheet.wires if w.touches(eid) and (port is None or port in (w.a.port, w.b.port))]

    align(chain["rhn"], "X1", port_pos(blk, "XOUT"))
    align(chain["tr"], "2", port_pos(chain["rhn"], "XT"))
    t1 = port_pos(chain["tr"], "1")
    if chain["rvn"] is not None:
        align(chain["rvn"], "X1", t1)
        feeds = [port_pos(chain["rvn"], f"XDS{k + 1}") for k in range(len(chain["grids"]))]
    else:
        qs, fu, fv = chain["pole"]
        align(fu, "2", t1)
        align(qs, "2", t1)
        fv.x += t1[0] + 12.5 - port_pos(fv, "1")[0]
        fv.y += t1[1] - 12.5 - port_pos(fv, "1")[1]
        for w in wire_to(fv.id):
            w.points = [(t1[0] + 12.5, t1[1])]
        feeds = [port_pos(qs, "1")]
    for k, g in enumerate(chain["grids"]):
        pos = feeds[k]
        if pos is None:
            continue
        align(g, "1", (pos[0], pos[1] - 15.0 * k))
        if k:
            x_bend = port_pos(g, "1")[0] - 20.0
            for w in sheet.wires:
                if w.touches(g.id):
                    w.points = [(x_bend, pos[1]), (x_bend, pos[1] - 15.0 * k)]
    xs = port_pos(chain["rhn"], "X2")
    low = bottom_of(chain["rhn"]) - 25.0
    if xs is not None:
        # spotřeba pod blokem: z X2 (vlevo, blok je zrcadlený) kousek vlevo, svisle dolů pod blok a vpravo do značky
        load = chain["load"]
        x_bend = xs[0] - 20.0          # za svislými měřicími obvody (ty vedou těsně u bloku)
        lp = port_pos(load, "1")
        load.x += xs[0] + 7.5 - lp[0]
        load.y += low - lp[1]
        for w in wire_to(load.id):
            w.points = [(x_bend, xs[1]), (x_bend, low)]
    # elektroměrový rozvaděč pod rozvaděčem s měřením (pod spotřebou) a vpravo: měřicí obvody vedou z bloku vlevo,
    # svisle dolů (XMI blíž bloku) a vodorovně do přívodů RE – vodorovný úsek je nejdelší, popisky kabelů leží nad
    # ním a nepřekrývají se (svislý úsek by popisek nesl vpravo přes druhý vodič)
    src, re_ = chain["src"], chain["re"]
    top = min(low - 20.0, bottom_of(src) - 25.0) if src is chain["rhn"] else bottom_of(src) - 25.0
    a, ps0 = port_pos(re_, "XMI"), port_pos(src, "XMI")
    if a is not None and ps0 is not None:
        re_.y += top - a[1]
        x_bend = ps0[0] - 3.0
        re_.x += x_bend + (ps0[1] - top) + 15.0 - port_pos(re_, "XMI")[0]
        for n, name in enumerate(("XMI", "XMU")):
            ps, pr = port_pos(src, name), port_pos(re_, name)
            if ps is None or pr is None:
                continue
            xb = x_bend - 5.0 * n
            for w in wire_to(re_.id, name):
                w.points = [(xb, ps[1]), (xb, pr[1])]


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
                         "alpha_isc": "alpha_isc", "gamma_pmax": "gamma_pmax", "i_fuse_max": "i_fuse_max"}


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
    optimizér (zadané jiné `per_module` se nepoužije – počet optimizérů musí odpovídat `opt_*` atributům; zaloguje
    se varování, průvodce to hlásí v asistentu). Vrací (nová specifikace optimizéru, artikl | None); neznámý artikl →
    beze změny a None. Průvodce při vymazaném typu `component_id` neposílá (= bez optimizérů)."""
    out = dict(opt)
    comp = _lib().component(opt.get("component_id"))
    if comp is None or comp.category != "optimizer":
        return out, None
    if not str(out.get("type") or "").strip():
        out["type"] = comp.part_number
    per = 1 / _modules_per_optimizer(comp)
    given = _num(opt.get("per_module"))
    if given is not None and abs(given - per) > 1e-9:
        log.warning("optimizer.per_module %g neodpovídá artiklu %s (%g ks/modul) – použije se hodnota z artiklu",
                    given, comp.id, per)
    out["per_module"] = per
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
    vodič s jediným svislým úsekem [(x, y1), (x, y2)] dostane y1 = y portu A, y2 = y portu B – je pak jen
    vodorovný–svislý–vodorovný. Svislé úseky víc vodičů do jednoho prvku (konec B) se přeskládají na svých x tak,
    aby se nekřížily (shora dolů: nejvyšší nejdál, zdola nahoru: nejnižší nejdál). Volá se před rozdělením JPS na
    listy (`_place_jps` – rozmístění posouvá prvky i lomy celého listu stejně), projde všechny listy, které nejsou
    rozvaděč."""
    lib = _lib()
    for s in project.sheets:
        if not s.is_switchboard:
            _align_bends_sheet(project, s, lib)


def _align_bends_sheet(project: Project, s: Sheet, lib) -> None:
    from envocad.model.project import element_symbol
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
    # prázdné / „auto“ `fuse_in` (podle stringu) doplní `_fuse_in` před voláním; sem jde už číslo
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
                       inv_no: int = 1, inv_ref: str = "", k0: int = 0, n: int | None = None, dx0: float = 0.0) -> bool:
    """DC rozvaděč složený z makra na string. Kontext: k (pořadí v rozvaděči), nk (n + k), n, string (G3),
    i (číslo střídače), j (string u střídače) – ENVO číslování FU{i}.{j}, XS{i}.{j}, STRING {i}.{j} –, inverter;
    základ ze specifikace fuse_in, disc_in, spd. `name` = položka `spec["macros"]` (název nebo objekt). False = makro chybí.
    Rozvaděč FVE rodinného domu: `k0` = počet přívodů před stringy (k = k0 + pořadí), `n` = stringů celkem v rozvaděči,
    `dx0` = posun DC části v listu."""
    from envocad.library.macros import find_macro, macro_pitch
    entry = _macro_ref(name)
    m = find_macro(entry[0]) if entry[0] else None
    if m is None:
        return False
    lib = _lib()
    n = len(strings) if n is None else n
    pitch = macro_pitch(m)
    base = _macro_vars(dc, {})
    devices = []
    for j, g in enumerate(strings, start=1):
        k = k0 + j
        ctx = {"k": k, "nk": n + k, "n": n, "string": g, "i": inv_no, "j": j, "inverter": inv_ref}
        vals = _macro_values(m, entry, base, ctx, lib.component)
        devices += _insert_macro(project, sheet, m, vals, dx0 + (k - 1) * pitch, lib)
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
