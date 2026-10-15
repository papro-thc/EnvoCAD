"""Generování celého projektu ze specifikace (průvodce v GUI i rozhraní pro agenty). Bez Qt.

    python -m envocad.generate spec.json vystup.ecp

Specifikace (JSON, vše kromě `inverters` volitelné – viz `DEFAULT_SPEC`):
{
  "name": "FVE Firma s.r.o.", "meta": {"investor": "…", "place": "…", "order": "…", "author": "…"},
  "module": {"p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9, "beta_voc": -0.27, "type": "JA Solar …"},
  "inverters": [{"ref": "T1", "type": "SMA STP 25-50", "p_ac": 25, "phases": 3, "u_dc_max": 1100,
                 "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [20, 20, 18, 18],
                 "component_id": "sma-stp-25-50"}],
  "dc": {"cable": "H1Z2Z2-K 1x6", "cross": 6, "length": 40,          # string → první DC rozvaděč
         "route_boxes": 1, "route_length": 20,                        # DC rozvaděče po trase (odpínač + SPD), kabel mezi nimi
         "tech_box": true, "tech_length": 5,                          # DC rozvaděč u technologie (pojistkové odpínače + SPD), kabel ke střídači
         "spd": "T2", "fuse_in": 15, "disconnect_in": 32,
         "disconnect": false},                                        # jen samostatný odpínač v JPS bez DC rozvaděčů (stará varianta)
  "ac": {"cable": "CYKY-J 5x16", "cross": 16, "length": 30, "breaker_in": 40, "main_in": 125,
         "grid_cable": "CYKY-J 5x35", "grid_cross": 35, "grid_length": 20, "spd": "T1+T2", "enclosure": ""},
  "switchboard": {"ref": "RH", "desc": "AC rozvaděč FVE"},
  "grid": {"dso": "ČEZ Distribuce", "voltage": "3×400 V"},
  "battery": {"e_kwh": 10, "p_kw": 5, "type": "…"}        # volitelné, jen u hybridního střídače
}
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
    "dc": {"cable": "H1Z2Z2-K 1x6", "cross": 6, "length": 30, "route_boxes": 1, "route_length": 20,
           "tech_box": True, "tech_length": 5, "spd": "T2", "fuse_in": 15, "disconnect_in": 32, "disconnect": False},
    "ac": {"cable": "CYKY-J 5x16", "cross": 16, "length": 30, "breaker_in": 40, "main_in": 125,
           "grid_cable": "CYKY-J 5x35", "grid_cross": 35, "grid_length": 20, "spd": "T1+T2", "enclosure": ""},
    "switchboard": {"ref": "RH", "desc": "AC rozvaděč FVE"},
    "grid": {"dso": "", "voltage": "3×400 V"},
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
    # svislé rozestupy řad střídačů podle počtu stringů
    row_h = [max(55.0, 30.0 * max(len(inv.get("strings") or [1]), 1) + 20.0) for inv in invs]
    total_h = sum(row_h)
    if total_h + 70.0 > s.height:   # hodně stringů → vyšší list
        s.height, s.paper = total_h + 70.0, "vlastní"
    y_top = min(s.height - 45.0, 150.0 + total_h / 2)
    n_route = max(0, int(dc.get("route_boxes") or 0))
    n_boxes = n_route + (1 if dc.get("tech_box") else 0)
    box_pitch = 60.0
    x_str = 35.0
    x_boxes = [95.0 + j * box_pitch for j in range(n_boxes)]
    x_dc = 130.0                                                   # samostatný odpínač DC (bez rozvaděčů)
    x_inv = (x_boxes[-1] + 80.0) if n_boxes else 200.0             # před střídačem víc místa: stringy se slévají do DC1/DC2
    x_blk, x_grid = x_inv + 80.0, x_inv + 155.0
    if x_grid + 25.0 > s.width:    # víc DC rozvaděčů po trase → širší list (A2 na výšku A3)
        s.width, s.paper = x_grid + 25.0, "vlastní"
    p_total = 0.0
    blk = Element("fve.switchboard", x_blk, 150.0, attrs={"ref": spec["switchboard"]["ref"], "desc": spec["switchboard"]["desc"]})
    s.elements.append(blk)
    y = y_top
    inverter_elements: list[Element] = []
    dc_boxes: list[tuple[Element, list[Element], str]] = []   # (blok, stringy, druh) – listy se dostaví po JPS
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
        s.elements.append(t)
        inverter_elements.append(t)
        gens: list[Element] = []
        for k, n_mod in enumerate(strings):
            ys = y - 15.0 - k * 30.0
            p_str = round(n_mod * float(mod.get("p_wp") or 0) / 1000, 2)
            p_total += p_str
            g = Element("fve.pv_string", x_str, ys, attrs={
                "ref": p.next_ref("G"), "type": _s(mod.get("type")), "n_modules": _s(n_mod), "p_module": _s(mod.get("p_wp")),
                "p_string": f"{p_str:g} kWp", "voc": _s(mod.get("voc")), "vmp": _s(mod.get("vmp")),
                "isc": _s(mod.get("isc")), "beta_voc": _s(mod.get("beta_voc"))})
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
            dc_boxes.append((b, gens, kind))
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
    p.meta.setdefault("p_installed_kwp", f"{p_total:g}")
    # listy DC rozvaděčů a AC rozvaděče
    for b, gens, kind in dc_boxes:
        build_dc_strings(p, p.create_switchboard_sheet(b), [g.ref for g in gens], kind, _s(dc.get("fuse_in") or 15),
                         _s(dc.get("disconnect_in") or 32), _s(dc.get("spd") or "T2"))
    sb = p.create_switchboard_sheet(blk)
    _build_ac_switchboard(p, sb, invs, ac, spec)
    sync_feed_links(p)
    sync_cables(p)
    return p


def _build_ac_switchboard(project: Project, sheet: Sheet, invs: list[dict], ac: dict, spec: dict) -> None:
    """AC rozvaděč FVE: přívody od střídačů (X1…Xn) → jističe → rozvodné svorky s můstky → hlavní vypínač → vývod do HDS;
    SPD na rozvodných svorkách, PE lišta."""
    nc = len(AC_CONDUCTORS)
    y = 200.0
    x0 = 60.0
    n = len(invs)
    strip = "X" + str(n + 1)
    feeds: list[Element] = []
    breakers: list[Element] = []
    groups: list[Element] = []
    firsts: list[int] = []
    for i, inv in enumerate(invs):
        x = x0 + i * GROUP_PITCH
        feed = _el(project, sheet, "sb.feed_in", x, y + 40, "", desc=f"od {inv.get('ref') or f'T{i + 1}'}")
        feed.attrs["ref"] = f"X{i + 1}"
        f = _el(project, sheet, "fve.breaker_mcb", x, y + 10, "F", rot=270, in_=str(ac.get("breaker_in") or 40),
                char="B", poles="3", modules="3")
        first = 1 + i * nc
        firsts.append(first)
        grp = _terminal_group(project, sheet, x, y - 30, strip, first, nc, f"střídač {i + 1}")
        _wire(project, sheet, feed, "1", f, "1", AC_CONDUCTORS)
        _wire(project, sheet, f, "2", grp, "1", AC_CONDUCTORS)
        feeds.append(feed)
        breakers.append(f)
        groups.append(grp)
    # skupina pro SPD a skupina pro hlavní vypínač / vývod
    x_spd = x0 + n * GROUP_PITCH
    first = 1 + n * nc
    firsts.append(first)
    g_spd = _terminal_group(project, sheet, x_spd, y - 30, strip, first, nc, "SPD")
    x_out = x0 + (n + 1) * GROUP_PITCH
    first = 1 + (n + 1) * nc
    firsts.append(first)
    g_out = _terminal_group(project, sheet, x_out, y - 30, strip, first, nc, "vývod")
    project.set_bridges(strip, _bridge_groups(firsts, nc), sheet)
    spd = _el(project, sheet, "fve.spd", x_spd, y - 60, "F", spd_type=_s(ac.get("spd") or "T1+T2"), poles="4", modules="4")
    pe = _el(project, sheet, "sb.pe_bar", x_spd, y - 90, "X", kind="PE")
    _wire(project, sheet, g_spd, "2", spd, "L", AC_CONDUCTORS[:4])
    _wire(project, sheet, g_spd, "2", pe, "2", ["PE"])   # PE svorka skupiny → PE lišta
    _wire(project, sheet, spd, "PE", pe, "1", ["PE"])
    q = _el(project, sheet, "sb.main_switch", x_out, y - 60, "Q", rot=270, in_=str(ac.get("main_in") or 125), poles="4", modules="4")
    out = _el(project, sheet, "sb.feed_out", x_out, y - 95, "", desc="do HDS / DS")
    out.attrs["ref"] = "XOUT"
    _wire(project, sheet, g_out, "2", q, "1", AC_CONDUCTORS)
    _wire(project, sheet, q, "2", out, "1", AC_CONDUCTORS)
    _place_sequential(sheet, [q, spd, *breakers])
    if ac.get("enclosure"):
        sheet.layout.params["type"] = _s(ac["enclosure"])


def load_spec(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


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
