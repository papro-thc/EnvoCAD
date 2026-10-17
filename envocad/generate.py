"""Generování celého projektu ze specifikace (průvodce v GUI i rozhraní pro agenty). Bez Qt.

    python -m envocad.generate spec.json vystup.ecp

Specifikace (JSON, vše kromě `inverters` volitelné – viz `DEFAULT_SPEC`):
{
  "name": "FVE Firma s.r.o.", "meta": {"investor": "…", "place": "…", "order": "…", "author": "…"},
  "module": {"p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9, "beta_voc": -0.27, "type": "JA Solar …"},
  "optimizer": {"type": "", "per_module": 1},                        # optimizéry (prázdný typ = bez optimizérů)
  "inverters": [{"ref": "T1", "type": "SMA STP 25-50", "p_ac": 25, "phases": 3, "u_dc_max": 1100,
                 "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [20, 20, 18, 18],
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
které specifikace nezadala (typ, výrobce, mppt…).
"""
from __future__ import annotations

import json
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
from envocad.model.project import (
    PORT_PITCH,
    Element,
    Project,
    Sheet,
    Wire,
    WireEnd,
    sync_cables,
    sync_feed_links,
)

DEFAULT_SPEC = {
    "name": "Nový projekt FVE",
    "meta": {},
    "module": {"p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9, "beta_voc": -0.27, "type": ""},
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


def build_project(spec: dict) -> Project:
    """Sestaví projekt: JPS (stringy → DC rozvaděče → střídač, každý string na vlastní DC vstup → AC rozvaděč → síť) + listy rozvaděčů."""
    spec = _merge(DEFAULT_SPEC, spec)
    invs = spec.get("inverters") or []
    if not invs:
        raise ValueError("Specifikace musí obsahovat alespoň jeden střídač (`inverters`).")
    p = Project(name=spec["name"], meta={k: _s(v) for k, v in spec["meta"].items()})
    s = p.sheets[0]
    s.name = "Jednopólové schéma"
    mod, dc, ac = spec["module"], spec["dc"], spec["ac"]
    opt = spec.get("optimizer") or {}
    opt_per = float(opt.get("per_module") or 1) if opt.get("type") else 0.0
    # svislé rozestupy řad střídačů podle počtu stringů
    row_h = [max(60.0, 45.0 * max(len(inv.get("strings") or [1]), 1) + 15.0) for inv in invs]   # 45 mm na string (popisek nad ním)
    total_h = sum(row_h)
    if total_h + 70.0 > s.height:   # hodně stringů → vyšší list
        s.height, s.paper = total_h + 70.0, "vlastní"
    y_top = min(s.height - 45.0, 150.0 + total_h / 2)
    n_route = max(0, int(dc.get("route_boxes") or 0))
    n_boxes = n_route + (1 if dc.get("tech_box") else 0)
    box_pitch = 85.0            # mezi rozvaděči se vejde popisek kabelu i dvojitý křížový odkaz
    x_str = 35.0
    n_max = max(len(inv.get("strings") or [1]) for inv in invs)
    x_box0 = x_str + 60.0 + 5.0 * n_max   # lomy stringů až za popisky kabelů u stringů
    x_boxes = [x_box0 + j * box_pitch for j in range(n_boxes)]
    x_dc = 130.0                                                   # samostatný odpínač DC (bez rozvaděčů)
    x_inv = (x_boxes[-1] + 80.0) if n_boxes else 200.0             # před střídačem víc místa: stringy se slévají do DC1/DC2
    x_blk, x_grid = x_inv + 110.0, x_inv + 185.0   # mezi střídačem a rozvaděčem se vejde popisek AC kabelu
    if x_grid + 25.0 > s.width:    # víc DC rozvaděčů po trase → širší list (A2 na výšku A3)
        s.width, s.paper = x_grid + 25.0, "vlastní"
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
            "mppt": _s(inv.get("mppt", max(1, -(-len(strings) // int(inv.get("strings_per_mppt") or 2))))),
            "strings_per_mppt": _s(inv.get("strings_per_mppt") or 2),
            "u_dc_max": _s(inv.get("u_dc_max")), "u_mppt_min": _s(inv.get("u_mppt_min")),
            "u_mppt_max": _s(inv.get("u_mppt_max")), "i_mppt_max": _s(inv.get("i_mppt_max")),
            "p_dc_max": _s(inv.get("p_dc_max"))}, component_id=inv.get("component_id"))
        _apply_inverter_component(t, inv)
        s.elements.append(t)
        inverter_elements.append(t)
        gens: list[Element] = []
        for k, n_mod in enumerate(strings):
            ys = y - 35.0 - k * 45.0
            p_str = round(n_mod * float(mod.get("p_wp") or 0) / 1000, 2)
            p_total += p_str
            g = Element("fve.pv_string", x_str, ys, attrs={
                "ref": p.next_ref("G"), "type": _s(mod.get("type")), "n_modules": _s(n_mod), "p_module": _s(mod.get("p_wp")),
                "p_string": f"{p_str:g} kWp", "voc": _s(mod.get("voc")), "vmp": _s(mod.get("vmp")),
                "isc": _s(mod.get("isc")), "beta_voc": _s(mod.get("beta_voc")),
                "n_optimizers": _s(round(n_mod * opt_per)) if opt_per else "", "optimizer": _s(opt.get("type")) if opt_per else ""})
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
        n_in = max(2, int(t.attrs["mppt"]) * int(t.attrs["strings_per_mppt"]), n_str)   # DC vstupy střídače (viz inverter_symbol)
        for k, g in enumerate(gens):
            port_inv = f"DC{k + 1}"   # každý string má na střídači vlastní vstup – stringy se nespojují
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
                xb = prev.x + 50.0 + 5.0 * k   # lomy až za popisky
                y_inv = t.y + (2.5 * (n_in - 1) - 5.0 * k if n_in > 2 else (5.0 if k == 0 else -5.0))
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
        y -= row_h[i]
    if spec.get("battery"):
        b = spec["battery"]
        bat = Element("fve.battery", x_inv, y_top - total_h - 15.0, attrs={"ref": "G" + str(len([e for e in s.elements if e.symbol_id == "fve.pv_string"]) + 1),
                                                                            "type": _s(b.get("type")), "e_kwh": _s(b.get("e_kwh")), "p_kw": _s(b.get("p_kw"))})
        s.elements.append(bat)
        s.wires.append(Wire(WireEnd(inverter_elements[0].id, "BAT"), WireEnd(bat.id, "DC"), conductors=list(DC_CONDUCTORS),
                            attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": "25", "length": "5"}))
    grid = Element("fve.grid", x_grid, 150.0, attrs={"ref": "", "voltage": _s(spec["grid"].get("voltage")), "dso": _s(spec["grid"].get("dso"))})
    s.elements.append(grid)
    w_grid = Wire(WireEnd(blk.id, "XOUT"), WireEnd(grid.id, "1"), conductors=list(AC_CONDUCTORS),
                  attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("grid_cable")), "cross": _s(ac.get("grid_cross")),
                         "length": _s(ac.get("grid_length")), "method": "D"})
    s.wires.append(w_grid)
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
    sync_feed_links(p)
    sync_cables(p)
    _align_bends(p)
    return p


def _apply_inverter_component(t: Element, inv: dict) -> None:
    """Artikl střídače (`component_id`) doplní atributy, které specifikace nezadala (chybí nebo jsou prázdné) –
    např. typ, výrobce, `mppt` (→ počet DC vstupů), p_dc_max. Zadané hodnoty specifikace mají přednost.
    Neznámý artikl se ignoruje (prvek si `component_id` ponechá, kontrola projektu ho nahlásí)."""
    cid = inv.get("component_id")
    if not cid:
        return
    from envocad.library.store import LibraryStore
    comp = LibraryStore().component(cid)
    if comp is None:
        return
    probe = Element(t.symbol_id, t.x, t.y, attrs=dict(t.attrs))
    for key, val in comp.apply_to(probe).items():
        if inv.get(key) in (None, ""):
            t.attrs[key] = val
    t.component_id = comp.id


def _align_bends(project: Project) -> None:
    """Lomy vodičů JPS podle skutečných poloh portů (porty bloků rozvaděčů a střídačů se dopočítají až z listů):
    svislý úsek [(x, y1), (x, y2)] dostane y1 = port A, y2 = port B – vodič je pak jen vodorovný–svislý–vodorovný."""
    from envocad.library.store import LibraryStore
    from envocad.model.project import element_symbol
    lib = LibraryStore()
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
    from envocad.library.store import LibraryStore
    entry = _macro_ref(name)
    m = find_macro(entry[0]) if entry[0] else None
    if m is None:
        return False
    lib = LibraryStore()
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
    from envocad.library.store import LibraryStore
    ef, ec = _macro_ref(macros.get("ac_feed", "")), _macro_ref(macros.get("ac_core", ""))
    mf = find_macro(ef[0]) if ef[0] else None
    mc = find_macro(ec[0]) if ec[0] else None
    if mf is None or mc is None or (ac.get("distribution") or "bus") != "bus":
        return False
    lib = LibraryStore()
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
    _place_sequential(sheet, [q, spd, *breakers])
    if ac.get("enclosure"):
        sheet.layout.params["type"] = _s(ac["enclosure"])


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
