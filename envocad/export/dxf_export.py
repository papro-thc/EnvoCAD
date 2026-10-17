"""Export listu do DXF (otevřitelné v ZWCAD/AutoCAD). Bez Qt – vodiče se trasují vlastní logikou."""
from __future__ import annotations

from pathlib import Path

import ezdxf

from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Sheet, element_symbol
from envocad.model.symbol import GRID, Symbol, rotate_point

LAYERS = {
    "SYMBOLY": 7, "VODICE": 7, "TEXTY": 7, "RAMECEK": 8, "REVIZE": 1,   # REVIZE = červená (porty se do DXF nekreslí)
}
NOTES_LAYER, NOTES_COLOR = "PRIPOMINKY", 6     # purpurová – odlišná od červené revize
DIR_VEC = {"N": (0, 1), "E": (1, 0), "S": (0, -1), "W": (-1, 0)}


def _snap(v: float) -> float:
    return round(v / GRID) * GRID


def _tr(e: Element, x: float, y: float) -> tuple[float, float]:
    rx, ry = rotate_point(x, y, e.rotation)
    return (e.x + rx, e.y + ry)


def _draw_symbol(msp, e: Element, sym: Symbol, label=None) -> None:
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
    if label is not None:
        for x, y, text, h in label.lines:
            _text(msp, x, y, text, h, label.align, 0, layer="TEXTY")
        return
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


def _draw_geometry(msp, g, layer: str) -> None:
    """Geometrie z modelu (rámeček `FrameGeometry`, revize `RevisionGeometry`, zrcadlo `MirrorGeometry`) do vrstvy:
    `lines` → LINE, `texts` → TEXT, `rects` → SOLID (QR kód), `polylines` → uzavřená LWPOLYLINE."""
    if g is None:
        return
    a = {"layer": layer}
    for x1, y1, x2, y2 in getattr(g, "lines", ()):
        msp.add_line((x1, y1), (x2, y2), dxfattribs=a)
    for pts in getattr(g, "polylines", ()):
        msp.add_lwpolyline(pts, close=True, dxfattribs=a)
    for x, y, w, h in getattr(g, "rects", ()):
        msp.add_solid([(x, y), (x + w, y), (x, y + h), (x + w, y + h)], dxfattribs=a)
    for x, y, text, h, align in getattr(g, "texts", ()):
        if text:
            _text(msp, x, y, text, h, align, 0, layer=layer)


def _wire_points(project: Project, sheet: Sheet, lib: LibraryStore, w) -> list[tuple[float, float]]:
    from envocad.model.textlayout import wire_route
    return wire_route(project, sheet, lib, w)


def export_sheet_dxf(project: Project, sheet: Sheet, lib: LibraryStore, path: Path | str, notes: bool = False) -> None:
    """DXF listu. `notes=True` přidá otevřené připomínky (s textem) do vrstvy `PRIPOMINKY` – jen tehdy vrstva vznikne.
    Vodiče na neexistující prvek (poškozený soubor) se vynechají, neznámá značka se kreslí jako zástupná."""
    from envocad.model.project import without_dangling
    clean = without_dangling(project)
    if clean is not project:
        sheet = next((s for s in clean.sheets if s.id == sheet.id), sheet)
        project = clean
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # mm
    for name, color in LAYERS.items():
        doc.layers.add(name, color=color)
    if notes:
        doc.layers.add(NOTES_LAYER, color=NOTES_COLOR)
    msp = doc.modelspace()
    from envocad.model.frame import MARGIN, MARGIN_LEFT, frame_enabled, frame_geometry
    _draw_geometry(msp, frame_geometry(project, sheet) if frame_enabled() else None, "RAMECEK")
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
    from envocad.model.textlayout import compute_layout
    lay = compute_layout(project, sheet, lib)
    for e in sheet.elements:
        _draw_symbol(msp, e, element_symbol(project, e, lib), lay.elements.get(e.id))
    for m in lay.mirrors.values():           # zrcadla kontaktů pod hostiteli
        _draw_geometry(msp, m, "TEXTY")
    for w in sheet.wires:
        pts = lay.routes.get(w.id) or _wire_points(project, sheet, lib, w)
        msp.add_lwpolyline(pts, dxfattribs={"layer": "VODICE"})
        lp = lay.wires.get(w.id)
        if lp is None:
            continue
        for x, y, text, h in lp.lines:
            _text(msp, x, y, text, h, lp.align, 0, layer="TEXTY")
        if lp.mark is not None:
            mx, my = lp.mark
            msp.add_line((mx - 1.2, my - 1.2), (mx + 1.2, my + 1.2), dxfattribs={"layer": "VODICE"})
    # značky revize listu (trojúhelník s označením revize) – stejné trasy vodičů jako výše
    from envocad.model.revision import revision_geometry
    _draw_geometry(msp, revision_geometry(project, sheet, lib, lay.routes), "REVIZE")
    if notes:
        from envocad.model.notes import notes_geometry
        for g in notes_geometry(project, sheet, ("open",), with_text=True):
            _draw_geometry(msp, g, NOTES_LAYER)
    doc.saveas(str(path))

