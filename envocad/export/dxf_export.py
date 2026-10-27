"""Export listu do DXF (otevřitelné v ZWCAD/AutoCAD). Bez Qt – vodiče se trasují vlastní logikou.

`export_sheet_dxf` kreslí pohled listu (JPS, u rozvaděče jednopólovou editační podobu), `export_multipole_dxf`
vícepólové schéma listu z kreslicího seznamu modelu (`multipole_geometry.MultipoleGeometry.prims`)."""
from __future__ import annotations

from pathlib import Path

import ezdxf

from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Sheet, element_symbol
from envocad.model.symbol import MIRROR_ALIGN, Symbol, place_point

LAYERS = {
    "SYMBOLY": 7, "VODICE": 7, "TEXTY": 7, "RAMECEK": 8, "REVIZE": 1,   # REVIZE = červená (porty se do DXF nekreslí)
}
NOTES_LAYER, NOTES_COLOR = "PRIPOMINKY", 6     # purpurová – odlišná od červené revize
DIR_VEC = {"N": (0, 1), "E": (1, 0), "S": (0, -1), "W": (-1, 0)}
# vrstvy navíc ve vícepólu: (barva, typ čáry)
MP_LAYERS = {
    "SBERNICE": (7, "CONTINUOUS"),   # sběrnice, sběrné čáry, tečky odboček
    "MUSTKY": (7, "DASHED"),         # můstky svorkovnic
    "VAZBY": (7, "DASHED"),          # mechanická vazba pólů
    "ODKAZY": (7, "CONTINUOUS"),     # šipky přerušení a křížové odkazy „/3.2.B4“
    "STITKY": (7, "CONTINUOUS"),     # štítky kabelů
}
LINEWEIGHT = {"thin": 18, "wire": 35, "bus": 50, "fan": 50}   # setiny mm
DASH_SCALE = 2.0      # DASHED z `ezdxf.new(setup=True)` má čárku 1,27 mm – ×2 odpovídá čárkování ve scéně
MP_PAGE_GAP = 20.0    # mezera mezi stranami vedle sebe v modelspace


class _At:
    """Počátek a natočení značky (rozhraní jako `Element` pro `_tr`)."""

    def __init__(self, x: float, y: float, rotation: float):
        self.x, self.y, self.rotation = x, y, rotation
        self.mirror = False



def _tr(e: Element, x: float, y: float) -> tuple[float, float]:
    rx, ry = place_point(x, y, e.rotation, getattr(e, "mirror", False))
    return (e.x + rx, e.y + ry)


def _draw_symbol(msp, e: Element, sym: Symbol, label=None) -> None:
    _draw_symbol_at(msp, e, sym)
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


def _draw_symbol_at(msp, e, sym: Symbol) -> None:
    """Grafika značky (bez portů a popisků) v počátku `e.x, e.y` natočená o `e.rotation` – prvek listu nebo pól
    ve vícepólu (`_At`). Oblouky a kružnice zůstanou přesné."""
    rot = e.rotation
    mirror = getattr(e, "mirror", False)
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
            start, end = (180 - p["end"], 180 - p["start"]) if mirror else (p["start"], p["end"])
            msp.add_arc(_tr(e, p["cx"], p["cy"]), p["r"], start + rot, end + rot, dxfattribs=a)
        elif t == "polyline":
            msp.add_lwpolyline([_tr(e, x, y) for x, y in p["points"]], close=p.get("closed", False), dxfattribs=a)
        elif t == "text":
            align = p.get("align", "center")
            _text(msp, *_tr(e, p["x"], p["y"]), p["text"], p.get("height", 2.5),
                  MIRROR_ALIGN.get(align, align) if mirror else align, rot)


def _text(msp, x, y, text, height, align, rot, layer="SYMBOLY"):
    t = msp.add_text(text, dxfattribs={"layer": layer, "height": height, "rotation": rot})
    al = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}.get(align, "LEFT")
    t.set_placement((x, y), align=getattr(ezdxf.enums.TextEntityAlignment, al))


def _draw_geometry(msp, g, layer: str, dx: float = 0.0) -> None:
    """Geometrie z modelu (rámeček `FrameGeometry`, revize `RevisionGeometry`, zrcadlo `MirrorGeometry`) do vrstvy:
    `lines` → LINE, `texts` → TEXT, `rects` → SOLID (QR kód), `polylines` → uzavřená LWPOLYLINE. `dx` = posun
    v ose X (strana vícepólu vedle ostatních v modelspace)."""
    if g is None:
        return
    a = {"layer": layer}
    for x1, y1, x2, y2 in getattr(g, "lines", ()):
        msp.add_line((x1 + dx, y1), (x2 + dx, y2), dxfattribs=a)
    for pts in getattr(g, "polylines", ()):
        msp.add_lwpolyline([(x + dx, y) for x, y in pts], close=True, dxfattribs=a)
    for x, y, w, h in getattr(g, "rects", ()):
        x += dx
        msp.add_solid([(x, y), (x + w, y), (x, y + h), (x + w, y + h)], dxfattribs=a)
    for x, y, text, h, align in getattr(g, "texts", ()):
        if text:
            _text(msp, x + dx, y, text, h, align, 0, layer=layer)


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
    from envocad.model.frame import MARGIN, MARGIN_LEFT, frame_geometry
    from envocad.settings import company, frame_enabled
    _draw_geometry(msp, frame_geometry(project, sheet, company=company()) if frame_enabled() else None, "RAMECEK")
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
    from envocad.model.project import TEXT_LINE
    for t in sheet.texts:                    # volné texty listu
        for i, line in enumerate(t.lines()):
            if line.strip():
                _text(msp, t.x, t.y - i * TEXT_LINE * t.height, line, t.height, "left", 0, layer="TEXTY")
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



# ---- vícepólové schéma ----------------------------------------------------------------------------------------
def _new_doc():
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # mm
    for name, color in LAYERS.items():
        doc.layers.add(name, color=color)
    for name, (color, ltype) in MP_LAYERS.items():
        doc.layers.add(name, color=color, linetype=ltype)
    return doc


def _draw_prim(msp, p, dx: float = 0.0) -> None:
    """Jedno primitivum `multipole_geometry.Prim` (lokální souřadnice strany posunuté o `dx` v ose X)."""
    a: dict = {"layer": p.layer}
    pts = [(x + dx, y) for x, y in p.pts]
    if p.kind in ("line", "poly"):
        a["lineweight"] = LINEWEIGHT.get(p.weight, 18)
        if p.style == "dashed":
            a["linetype"] = "DASHED"
            a["ltscale"] = DASH_SCALE
        if p.kind == "line":
            msp.add_line(pts[0], pts[1], dxfattribs=a)
        else:
            msp.add_lwpolyline(pts, dxfattribs=a)
    elif p.kind == "text":
        _text(msp, pts[0][0], pts[0][1], p.text, p.h, p.align, p.rot, layer=p.layer)
    elif p.kind == "dot":
        a["linetype"] = "CONTINUOUS"     # tečka i na čárkované vrstvě (MUSTKY) má plný obrys
        msp.add_circle(pts[0], p.r, dxfattribs=a)
        h = msp.add_hatch(color=7, dxfattribs=a)
        h.paths.add_edge_path().add_arc(pts[0], p.r, 0, 360)
    elif p.kind == "symbol" and p.symbol is not None:
        _draw_symbol_at(msp, _At(pts[0][0], pts[0][1], p.rot), p.symbol)


def _draw_mp_page(msp, project: Project, sheet: Sheet, g, k: int, dx: float) -> None:
    """Strana k vícepólu do modelspace posunutá o `dx`: rámeček (jinak obrys strany) a primitiva strany."""
    from envocad.model.frame import doc_page, frame_geometry, page_label
    from envocad.model.multipole_geometry import page_prims
    from envocad.settings import company, frame_enabled
    w, h = g.page_size
    if frame_enabled():
        _draw_geometry(msp, frame_geometry(project, sheet, w, h, "vícepólové schéma",
                                           page_label(project, sheet, k, g.pages), g.paper, company(),
                                           doc_page(project, sheet.id, "multipole", k)), "RAMECEK", dx)
    else:      # obrys strany, aby byly strany vedle sebe rozlišitelné i bez rámečku
        msp.add_lwpolyline([(dx, 0), (dx + w, 0), (dx + w, h), (dx, h)], close=True, dxfattribs={"layer": "RAMECEK"})
    for p in page_prims(g, k):
        _draw_prim(msp, p, dx)


def _page_layout(doc, name: str, w: float, h: float, cx: float) -> None:
    """Paperspace layout jedné strany: formát strany, viewport 1 : 1 na stranu v modelspace se středem `cx`."""
    lay = doc.layouts.new(name)
    lay.page_setup(size=(w, h), margins=(0, 0, 0, 0), units="mm")    # výchozí měřítko 16 = 1 : 1
    lay.add_viewport(center=(w / 2, h / 2), size=(w, h), view_center_point=(cx, h / 2), view_height=h)


def export_single_line_dxf(project: Project, lib: LibraryStore, path: Path | str) -> Path:
    """DXF jednopólového schématu (`single_line.single_line_geometry`): strana v počátku modelspace, rámeček
    s popisovým polem a paperspace layout 1 : 1. Vrací cestu zapsaného souboru."""
    from envocad.model.frame import doc_page, frame_geometry
    from envocad.model.project import without_dangling
    from envocad.model.single_line import TITLE, page_label, single_line_geometry
    from envocad.settings import company, frame_enabled
    project = without_dangling(project)
    g = single_line_geometry(project, lib)
    w, h = g.page_size
    path = Path(path)
    if path.suffix.lower() != ".dxf":
        path = path.with_name(path.name + ".dxf")
    doc = _new_doc()
    doc.layers.add("ROZVADECE", color=8, linetype="DASHED")
    msp = doc.modelspace()
    sheet = Sheet(name=TITLE, paper=g.paper, width=w, height=h)
    if frame_enabled():
        _draw_geometry(msp, frame_geometry(project, sheet, w, h, "", page_label(project), g.paper, company(),
                                           doc_page(project, "", "single_line")), "RAMECEK")
    else:
        msp.add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h)], close=True, dxfattribs={"layer": "RAMECEK"})
    for p in g.prims:
        _draw_prim(msp, p)
    _page_layout(doc, TITLE, w, h, w / 2)
    doc.layouts.delete("Layout1")
    doc.saveas(str(path))
    return path


def export_multipole_dxf(project: Project, sheet: Sheet, lib: LibraryStore, path: Path | str,
                         split_pages: bool = False) -> list[Path]:
    """DXF vícepólového schématu listu (strany podle `multipole.paper_choice`, např. A4 297 × 210).

    Výchozí je jeden soubor: strany leží v modelspace vedle sebe (strana k posunutá o k·(šířka + 20 mm)) a každá
    má vlastní paperspace layout „Strana k“ s viewportem 1 : 1 (tisk po stranách v ZWCAD). `split_pages=True`
    uloží soubor na stranu `<název>_s<k>.dxf` (strana v počátku, bez layoutů navíc). Kreslí se kreslicí seznam
    modelu (`MultipoleGeometry.prims`) – stejné polohy jako scéna i kontrola překryvů; porty se nekreslí.
    Vrací cesty zapsaných souborů."""
    from envocad.model.multipole_geometry import multipole_geometry
    from envocad.model.project import without_dangling
    clean = without_dangling(project)
    if clean is not project:
        sheet = next((s for s in clean.sheets if s.id == sheet.id), sheet)
        project = clean
    from envocad.settings import switchboard_paper
    g = multipole_geometry(project, sheet, lib, standard_paper=switchboard_paper())
    w, h = g.page_size
    path = Path(path)
    if path.suffix.lower() != ".dxf":     # bez přípony (i „projekt.v2“) se doplní – stejně pro jeden i více souborů
        path = path.with_name(path.name + ".dxf")
    if split_pages:
        out = []
        for k in range(g.pages):
            doc = _new_doc()
            _draw_mp_page(doc.modelspace(), project, sheet, g, k, 0.0)
            pk = path.with_name(f"{path.stem}_s{k + 1}{path.suffix}")
            doc.saveas(str(pk))
            out.append(pk)
        return out
    doc = _new_doc()
    msp = doc.modelspace()
    for k in range(g.pages):
        dx = k * (w + MP_PAGE_GAP)
        _draw_mp_page(msp, project, sheet, g, k, dx)
        _page_layout(doc, f"Strana {k + 1}", w, h, dx + w / 2)
    doc.layouts.delete("Layout1")
    doc.saveas(str(path))
    return [path]
