"""Export listu do DXF (otevřitelné v ZWCAD/AutoCAD). Bez Qt – vodiče se trasují vlastní logikou."""
from __future__ import annotations

from pathlib import Path

import ezdxf

from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Sheet
from envocad.model.symbol import GRID, Symbol, rotate_dir, rotate_point

LAYERS = {
    "SYMBOLY": 7, "VODICE": 7, "TEXTY": 7, "RAMECEK": 8, "PORTY": 1,
}
DIR_VEC = {"N": (0, 1), "E": (1, 0), "S": (0, -1), "W": (-1, 0)}


def _snap(v: float) -> float:
    return round(v / GRID) * GRID


def _tr(e: Element, x: float, y: float) -> tuple[float, float]:
    rx, ry = rotate_point(x, y, e.rotation)
    return (e.x + rx, e.y + ry)


def _draw_symbol(msp, e: Element, sym: Symbol) -> None:
    rot = e.rotation
    for p in sym.primitives:
        t = p["type"]
        a = {"layer": "SYMBOLY"}
        if t == "line":
            msp.add_line(_tr(e, p["x1"], p["y1"]), _tr(e, p["x2"], p["y2"]), dxfattribs=a)
        elif t == "rect":
            x, y, w, h = p["x"], p["y"], p["w"], p["h"]
            pts = [_tr(e, x, y), _tr(e, x + w, y), _tr(e, x + w, y + h), _tr(e, x, y + h)]
            msp.add_lwpolyline(pts, close=True, dxfattribs=a)
        elif t == "circle":
            msp.add_circle(_tr(e, p["cx"], p["cy"]), p["r"], dxfattribs=a)
        elif t == "arc":
            msp.add_arc(_tr(e, p["cx"], p["cy"]), p["r"], p["start"] + rot, p["end"] + rot, dxfattribs=a)
        elif t == "polyline":
            msp.add_lwpolyline([_tr(e, x, y) for x, y in p["points"]], close=p.get("closed", False), dxfattribs=a)
        elif t == "text":
            _text(msp, *_tr(e, p["x"], p["y"]), p["text"], p.get("height", 2.5), p.get("align", "center"), rot)
    # popisky
    lx, ly = _tr(e, *sym.label_pos)
    line = 0.0
    if e.ref:
        _text(msp, lx, ly + line, e.ref, 2.5, "left", 0, layer="TEXTY")
        line -= 3.5
    for at in sym.attributes:
        if at.show and at.key != "ref" and e.attrs.get(at.key):
            _text(msp, lx, ly + line, e.attrs[at.key], 2.0, "left", 0, layer="TEXTY")
            line -= 3.0


def _text(msp, x, y, text, height, align, rot, layer="SYMBOLY"):
    t = msp.add_text(text, dxfattribs={"layer": layer, "height": height, "rotation": rot})
    al = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}.get(align, "LEFT")
    t.set_placement((x, y), align=getattr(ezdxf.enums.TextEntityAlignment, al))


def _wire_points(sheet: Sheet, lib: LibraryStore, w) -> list[tuple[float, float]]:
    ea, eb = sheet.element(w.a.element_id), sheet.element(w.b.element_id)
    sa, sb = lib.get_symbol(ea.symbol_id), lib.get_symbol(eb.symbol_id)
    pa, pb = ea.port_pos(sa, w.a.port), eb.port_pos(sb, w.b.port)
    da, db = rotate_dir(sa.port(w.a.port).dir, ea.rotation), rotate_dir(sb.port(w.b.port).dir, eb.rotation)
    va, vb = DIR_VEC[da], DIR_VEC[db]
    s1 = (pa[0] + va[0] * GRID, pa[1] + va[1] * GRID)
    s2 = (pb[0] + vb[0] * GRID, pb[1] + vb[1] * GRID)
    pts = [pa, s1]
    if w.points:
        pts += list(w.points)
    else:
        hor = da in ("E", "W")
        if hor and db in ("E", "W") and abs(s1[1] - s2[1]) > 1e-6:
            mx = _snap((s1[0] + s2[0]) / 2)
            pts += [(mx, s1[1]), (mx, s2[1])]
        elif not hor and db in ("N", "S") and abs(s1[0] - s2[0]) > 1e-6:
            my = _snap((s1[1] + s2[1]) / 2)
            pts += [(s1[0], my), (s2[0], my)]
        elif hor:
            pts.append((s2[0], s1[1]))
        else:
            pts.append((s1[0], s2[1]))
    pts += [s2, pb]
    return pts


def export_sheet_dxf(project: Project, sheet: Sheet, lib: LibraryStore, path: Path | str) -> None:
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # mm
    for name, color in LAYERS.items():
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (sheet.width, 0), (sheet.width, sheet.height), (0, sheet.height)],
                       close=True, dxfattribs={"layer": "RAMECEK"})
    _text(msp, 5, 5, f"{project.name}  –  {sheet.name}", 3.5, "left", 0, layer="RAMECEK")
    for e in sheet.elements:
        _draw_symbol(msp, e, lib.get_symbol(e.symbol_id))
    for w in sheet.wires:
        pts = _wire_points(sheet, lib, w)
        msp.add_lwpolyline(pts, dxfattribs={"layer": "VODICE"})
        if w.attrs.get("ref"):
            i = len(pts) // 2 - 1
            mx, my = (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2
            _text(msp, mx, my + 1.5, w.attrs["ref"], 2.0, "center", 0, layer="TEXTY")
    doc.saveas(str(path))

