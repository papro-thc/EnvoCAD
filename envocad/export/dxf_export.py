"""Export listu do DXF (otevřitelné v ZWCAD/AutoCAD). Bez Qt – vodiče se trasují vlastní logikou."""
from __future__ import annotations

from pathlib import Path

import ezdxf

from envocad.library.store import LibraryStore
from envocad.model.geometry import wire_label_anchor
from envocad.model.project import Element, Project, Sheet, element_symbol, wire_label, wire_xref
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
            if p.get("filled"):
                h = msp.add_hatch(color=7, dxfattribs=a)
                h.paths.add_edge_path().add_arc(_tr(e, p["cx"], p["cy"]), p["r"], 0, 360)
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
    for text in sym.label_lines(e.attrs):
        _text(msp, lx, ly + line, text, 2.0, "left", 0, layer="TEXTY")
        line -= 3.0


def _text(msp, x, y, text, height, align, rot, layer="SYMBOLY"):
    t = msp.add_text(text, dxfattribs={"layer": layer, "height": height, "rotation": rot})
    al = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}.get(align, "LEFT")
    t.set_placement((x, y), align=getattr(ezdxf.enums.TextEntityAlignment, al))


def _wire_points(project: Project, sheet: Sheet, lib: LibraryStore, w) -> list[tuple[float, float]]:
    ea, eb = sheet.element(w.a.element_id), sheet.element(w.b.element_id)
    sa, sb = element_symbol(project, ea, lib), element_symbol(project, eb, lib)
    pa, pb = ea.port_pos(sa, w.a.port), eb.port_pos(sb, w.b.port)
    da, db = rotate_dir(sa.port(w.a.port).dir, ea.rotation), rotate_dir(sb.port(w.b.port).dir, eb.rotation)
    va, vb = DIR_VEC[da], DIR_VEC[db]
    s1 = (pa[0] + va[0] * GRID, pa[1] + va[1] * GRID)
    s2 = (pb[0] + vb[0] * GRID, pb[1] + vb[1] * GRID)
    pts = [pa, s1]
    if w.points:
        from envocad.model.geometry import orthogonalize
        mid = orthogonalize([s1, *w.points, s2], end_horizontal=db in ("E", "W"))
        return [pa, *mid, pb]
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
    from envocad.model.frame import MARGIN, MARGIN_LEFT, frame_enabled, frame_geometry
    g = frame_geometry(project, sheet) if frame_enabled() else None
    for x1, y1, x2, y2 in (g.lines if g else []):
        msp.add_line((x1, y1), (x2, y2), dxfattribs={"layer": "RAMECEK"})
    for x, y, text, h, align in (g.texts if g else []):
        if text:
            _text(msp, x, y, text, h, align, 0, layer="RAMECEK")
    for x, y, w, h in (g.rects if g else []):  # QR kód jako vyplněné čtverce
        msp.add_solid([(x, y), (x + w, y), (x, y + h), (x + w, y + h)], dxfattribs={"layer": "RAMECEK"})
    if sheet.is_switchboard:
        from envocad.model.project import switchboard_header
        rows = switchboard_header(project, sheet)
        x0, y0, lh = MARGIN_LEFT + 4.0, sheet.height - MARGIN - 4.0, 4.0
        w, h = 95.0, lh * len(rows) + 3
        msp.add_lwpolyline([(x0 - 2, y0 + 2), (x0 - 2 + w, y0 + 2), (x0 - 2 + w, y0 + 2 - h), (x0 - 2, y0 + 2 - h)],
                           close=True, dxfattribs={"layer": "RAMECEK"})
        msp.add_line((x0 + 30, y0 + 2), (x0 + 30, y0 + 2 - h), dxfattribs={"layer": "RAMECEK"})
        for i, (k, v) in enumerate(rows):
            y = y0 - 2.5 - i * lh
            _text(msp, x0, y, k, 2.5, "left", 0, layer="TEXTY")
            _text(msp, x0 + 32, y, v, 2.5, "left", 0, layer="TEXTY")
    for e in sheet.elements:
        _draw_symbol(msp, e, element_symbol(project, e, lib))
    from envocad.model.project import feed_link_index
    idx = feed_link_index(project)
    for w in sheet.wires:
        pts = _wire_points(project, sheet, lib, w)
        msp.add_lwpolyline(pts, dxfattribs={"layer": "VODICE"})
        label = wire_label(w.attrs, w.conductors)
        xref = wire_xref(project, w.id, idx) if not sheet.is_switchboard else ""
        if label or xref:
            x, y, align, vertical = wire_label_anchor(pts)
            if w.points and len(pts) >= 2 and abs(pts[1][1] - pts[0][1]) < 1e-6:
                x, y, align, vertical = min(pts[0][0], pts[1][0]) + 1.5, pts[0][1] + 1.5, "left", False
            if label:
                _text(msp, x, y, label, 2.0, align, 0, layer="TEXTY")
            if xref:
                _text(msp, x, y - (3.0 if label else 0.0) - (1.5 if not vertical and label else 0.0), xref, 1.8, align, 0, layer="TEXTY")
            if vertical:
                msp.add_line((x - 2.7, y - 0.2), (x - 0.3, y + 2.2), dxfattribs={"layer": "VODICE"})
    doc.saveas(str(path))

