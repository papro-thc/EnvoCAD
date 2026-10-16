"""Rozmístění a kontrola textů ve výkresu (popisky prvků a vodičů) – bez Qt.

Popisek vodiče se umístí na první volné místo z kandidátů (výchozí poloha, začátek/střed/konec každého úseku,
u svislého úseku vpravo i vlevo), aby nepřekrýval popisky prvků, značky, cizí vodiče ani jiné popisky vodičů.
Co se nepodaří rozmístit, hlásí kontrola projektu (`text_overlap_findings`). Stejný výpočet používá editor i DXF.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

from envocad.model.geometry import Point, wire_label_anchor
from envocad.model.project import Element, Project, Sheet, element_symbol, element_xref, wire_label, wire_xref
from envocad.model.symbol import rotate_point

Box = tuple[float, float, float, float]   # x1, y1, x2, y2 (x1<x2, y1<y2)
DIR_VEC = {"N": (0, 1), "E": (1, 0), "S": (0, -1), "W": (-1, 0)}
CHAR_W = 0.72     # průměrná šířka znaku Arial / výška textu
GAP = 1.5


def text_box(x: float, y: float, text: str, h: float, align: str = "left") -> Box:
    """Obdélník textu: (x, y) = bod základny podle zarovnání (stejně jako `draw_text`)."""
    w = len(text) * h * CHAR_W
    x1 = {"left": x, "center": x - w / 2, "right": x - w}.get(align, x)
    return (x1, y - 0.3 * h, x1 + w, y + 1.0 * h)


def boxes_overlap(a: Box, b: Box, tol: float = 0.15) -> bool:
    return a[0] < b[2] - tol and b[0] < a[2] - tol and a[1] < b[3] - tol and b[1] < a[3] - tol


def box_hits_segment(b: Box, p: Point, q: Point, tol: float = 0.2) -> bool:
    """Protíná vodorovný/svislý úsek p–q obdélník textu?"""
    x1, x2 = sorted((p[0], q[0]))
    y1, y2 = sorted((p[1], q[1]))
    return x1 <= b[2] - tol and x2 >= b[0] + tol and y1 <= b[3] - tol and y2 >= b[1] + tol


def element_label_lines(project: Project, sheet: Sheet, e: Element, sym) -> list[tuple[float, float, str, float]]:
    """Řádky popisku prvku (x, y, text, výška) – stejně jako `ElementItem.paint`/DXF."""
    lx, ly = rotate_point(*sym.label_pos, e.rotation)
    x, y = e.x + lx, e.y + ly
    out = []
    line = 0.0
    if e.ref:
        out.append((x, y + line, e.ref, 2.5))
        line -= 3.5
    for t in sym.label_lines(e.attrs):
        out.append((x, y + line, t, 2.0))
        line -= 3.0
    try:
        xref = element_xref(project, sheet, e)
    except Exception:  # noqa: BLE001
        xref = ""
    for t in xref.splitlines():
        out.append((x, y + line, t, 2.0))
        line -= 3.0
    return out


def symbol_box(e: Element, sym) -> Box:
    x1, y1, x2, y2 = sym.bounds()
    pts = [rotate_point(px, py, e.rotation) for px, py in ((x1, y1), (x2, y2))]
    xs, ys = [e.x + p[0] for p in pts], [e.y + p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def wire_route(project: Project, sheet: Sheet, lib, w) -> list[Point]:
    from envocad.model.routing import wire_route as _wr
    return _wr(project, sheet, lib, w)


@dataclass
class LabelPos:
    x: float
    y: float
    align: str
    vertical: bool
    mark: Point | None = None                       # střed šikmé čárky na svislém vodiči
    lines: list[tuple[float, float, str, float]] = field(default_factory=list)   # (x, y, text, výška)
    boxes: list[Box] = field(default_factory=list)


def _place(x: float, y: float, align: str, vertical: bool, label: str, xref: str, mark: Point | None) -> LabelPos:
    lp = LabelPos(x, y, align, vertical, mark)
    if label:
        lp.lines.append((x, y, label, 2.0))
    if xref:
        lp.lines.append((x, y - (3.0 if label else 0.0) - (1.5 if not vertical and label else 0.0), xref, 1.8))
    lp.boxes = [text_box(lx, ly, t, h, align) for lx, ly, t, h in lp.lines]
    return lp


def _candidates(pts: list[Point], manual: bool, label: str, xref: str) -> list[LabelPos]:
    out: list[LabelPos] = []
    x, y, align, vertical = wire_label_anchor(pts)
    if manual and len(pts) >= 2 and abs(pts[1][1] - pts[0][1]) < 1e-6:
        x, y, align, vertical = min(pts[0][0], pts[1][0]) + GAP, pts[0][1] + GAP, "left", False
    out.append(_place(x, y, align, vertical, label, xref, (x - GAP, y + 1.0) if vertical else None))
    width = max([len(t) * 2.0 * CHAR_W for t in (label, xref) if t] or [0.0])
    segs = sorted(((a, b) for a, b in pairwise(pts) if abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1e-6),
                  key=lambda s: -(abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1])))
    for a, b in segs:
        if abs(a[1] - b[1]) < 1e-6:            # vodorovný úsek: nad vodičem vlevo / uprostřed / vpravo
            x1, x2 = sorted((a[0], b[0]))
            if x2 - x1 < width + 2 * GAP:
                continue
            yy = a[1] + GAP
            out += [_place(x1 + GAP, yy, "left", False, label, xref, None),
                    _place((x1 + x2) / 2, yy, "center", False, label, xref, None),
                    _place(x2 - GAP, yy, "right", False, label, xref, None)]
        else:                                  # svislý úsek: vpravo nebo vlevo, ve třetinách délky
            y1, y2 = sorted((a[1], b[1]))
            if y2 - y1 < 6.0:
                continue
            for f in (0.5, 0.75, 0.25, 0.9, 0.1):
                yy = y1 + (y2 - y1) * f - 1.0
                out.append(_place(a[0] + GAP, yy, "left", True, label, xref, (a[0], yy + 1.0)))
                out.append(_place(a[0] - GAP - 1.5, yy, "right", True, label, xref, (a[0], yy + 1.0)))
    return out


class _Grid:
    """Jednoduchý prostorový index obdélníků (buňka 20 mm)."""
    CELL = 20.0

    def __init__(self) -> None:
        self.cells: dict[tuple[int, int], list[tuple[Box, str, str]]] = {}

    def _keys(self, b: Box):
        c = self.CELL
        for i in range(int(b[0] // c), int(b[2] // c) + 1):
            for j in range(int(b[1] // c), int(b[3] // c) + 1):
                yield (i, j)

    def add(self, b: Box, kind: str, owner: str) -> None:
        for k in self._keys(b):
            self.cells.setdefault(k, []).append((b, kind, owner))

    def near(self, b: Box):
        seen = set()
        for k in self._keys(b):
            for item in self.cells.get(k, ()):
                if id(item) not in seen:
                    seen.add(id(item))
                    yield item


WEIGHT = {"text": 10.0, "line": 3.0}


def segment_hits_box(p: Point, q: Point, b: Box, tol: float = 0.2) -> bool:
    """Protíná úsečka p–q (libovolného směru) obdélník zmenšený o `tol`? (Liang–Barsky)"""
    x1, y1, x2, y2 = b[0] + tol, b[1] + tol, b[2] - tol, b[3] - tol
    if x1 >= x2 or y1 >= y2:
        return False
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, p[0] - x1), (dx, x2 - p[0]), (-dy, p[1] - y1), (dy, y2 - p[1])):
        if abs(pp) < 1e-12:
            if qq < 0:
                return False
        else:
            t = qq / pp
            if pp < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


def symbol_segments(e: Element, sym) -> list[tuple[Point, Point]]:
    """Čáry značky v souřadnicích listu (čáry, hrany obdélníků a lomených čar, kružnice jako čtverec)."""
    def tr(x, y):
        rx, ry = rotate_point(x, y, e.rotation)
        return (e.x + rx, e.y + ry)
    out = []
    for pr in sym.primitives:
        t = pr["type"]
        if t == "line":
            out.append((tr(pr["x1"], pr["y1"]), tr(pr["x2"], pr["y2"])))
        elif t == "rect":
            x, y, w, h = pr["x"], pr["y"], pr["w"], pr["h"]
            c = [tr(x, y), tr(x + w, y), tr(x + w, y + h), tr(x, y + h)]
            out += list(zip(c, c[1:] + c[:1]))
        elif t == "polyline":
            c = [tr(x, y) for x, y in pr["points"]]
            out += list(pairwise(c + ([c[0]] if pr.get("closed") else [])))
        elif t in ("circle", "arc"):
            cx, cy, r = pr["cx"], pr["cy"], pr["r"]
            c = [tr(cx - r, cy - r), tr(cx + r, cy - r), tr(cx + r, cy + r), tr(cx - r, cy + r)]
            out += list(zip(c, c[1:] + c[:1]))
    return out


def symbol_text_boxes(e: Element, sym) -> list[Box]:
    out = []
    for pr in sym.primitives:
        if pr["type"] == "text":
            x, y = rotate_point(pr["x"], pr["y"], e.rotation)
            h = pr.get("height", 2.5)
            if e.rotation % 180:
                w = len(pr["text"]) * h * CHAR_W
                out.append((e.x + x - 1.0 * h, e.y + y - w / 2, e.x + x + 0.3 * h, e.y + y + w / 2))
            else:
                out.append(text_box(e.x + x, e.y + y, pr["text"], h, pr.get("align", "center")))
    return out


@dataclass
class ElementLabel:
    x: float
    y: float
    align: str
    lines: list[tuple[float, float, str, float]] = field(default_factory=list)
    boxes: list[Box] = field(default_factory=list)


def _el_label(x: float, y: float, align: str, texts: list[tuple[str, float]]) -> ElementLabel:
    lab = ElementLabel(x, y, align)
    line = 0.0
    for i, (t, h) in enumerate(texts):
        lab.lines.append((x, y + line, t, h))
        line -= 3.5 if (i == 0 and h >= 2.5) else 3.0
    lab.boxes = [text_box(lx, ly, t, h, align) for lx, ly, t, h in lab.lines]
    return lab


def element_label_texts(project: Project, sheet: Sheet, e: Element, sym, xref: str | None = None) -> list[tuple[str, float]]:
    out = []
    if e.ref:
        out.append((e.ref, 2.5))
    out += [(t, 2.0) for t in sym.label_lines(e.attrs)]
    if xref is None:
        try:
            xref = element_xref(project, sheet, e)
        except Exception:  # noqa: BLE001
            xref = ""
    out += [(t, 2.0) for t in xref.splitlines()]
    return out


def _el_candidates(e: Element, sym, texts) -> list[ElementLabel]:
    lx, ly = rotate_point(*sym.label_pos, e.rotation)
    out = [_el_label(e.x + lx, e.y + ly, "left", texts)]
    bx1, by1, bx2, by2 = symbol_box(e, sym)
    n_h = 2.5 if texts and texts[0][1] >= 2.5 else 2.0
    block = (3.5 if n_h >= 2.5 else 3.0) + 3.0 * (len(texts) - 2) if len(texts) > 1 else 0.0
    cy = (by1 + by2) / 2
    top_mid = cy + block / 2 - n_h / 2          # blok svisle na střed značky
    out += [
        _el_label(bx2 + GAP, top_mid, "left", texts),                    # vpravo od značky
        _el_label(bx1 - GAP, top_mid, "right", texts),                   # vlevo
        _el_label(bx2 + GAP, by2 - n_h, "left", texts),                  # vpravo nahoře
        _el_label(bx1 - GAP, by2 - n_h, "right", texts),                 # vlevo nahoře
        _el_label(bx2 + GAP, by1 + block, "left", texts),                # vpravo dole
        _el_label(bx1 - GAP, by1 + block, "right", texts),               # vlevo dole
        _el_label(bx1, by2 + GAP + 0.3 * n_h + block, "left", texts),    # nad
        _el_label(bx1, by1 - GAP - n_h, "left", texts),                  # pod
    ]
    return out


@dataclass
class SheetTextLayout:
    elements: dict[str, ElementLabel] = field(default_factory=dict)
    wires: dict[str, LabelPos] = field(default_factory=dict)
    routes: dict[str, list[Point]] = field(default_factory=dict)


def _score(grid: _Grid, boxes: list[Box], own: str) -> float:
    s = 0.0
    for b in boxes:
        for ob, kind, owner in grid.near(b):
            if kind == "line":
                if segment_hits_box((ob[0], ob[1]), (ob[2], ob[3]), b):
                    s += WEIGHT["line"]
            elif owner != own and boxes_overlap(b, ob):
                s += WEIGHT["text"]
    return s


def _add_line(grid: _Grid, p: Point, q: Point, owner: str) -> None:
    # do mřížky jde obálka, ale uložené souřadnice jsou krajní body úsečky (ne min/max) – pro šikmé čáry
    box = (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))
    for k in grid._keys(box):
        grid.cells.setdefault(k, []).append(((p[0], p[1], q[0], q[1]), "line", owner))


def compute_layout(project: Project, sheet: Sheet, lib, routes: dict[str, list[Point]] | None = None,
                   xref_of=None, auto: bool = True) -> SheetTextLayout:
    """Rozmístí popisky prvků (výchozí poloha značky, když je volná, jinak vpravo/vlevo/nad/pod) a pak popisky
    vodičů. `routes` = trasy z editoru (jinak `wire_route`); `auto=False` = jen výchozí polohy (pro kontrolu)."""
    if routes is None:
        from envocad.model.routing import route_sheet
        routes = route_sheet(project, sheet, lib)
    if xref_of is None:
        if sheet.is_switchboard:
            xref_of = lambda w: ""
        else:
            from envocad.model.project import feed_link_index
            idx = feed_link_index(project)
            xref_of = lambda w: wire_xref(project, w.id, idx)
    out = SheetTextLayout(routes=routes)
    grid = _Grid()
    syms = {}
    for e in sheet.elements:
        sym = syms[e.id] = element_symbol(project, e, lib)
        for a, b in symbol_segments(e, sym):
            _add_line(grid, a, b, e.id)
        for b in symbol_text_boxes(e, sym):
            grid.add(b, "text", e.id + "#sym")
    for wid, pts in routes.items():
        for a, b in pairwise(pts):
            _add_line(grid, a, b, wid)
    for e in sheet.elements:
        sym = syms[e.id]
        texts = element_label_texts(project, sheet, e, sym)
        if not texts:
            continue
        cands = _el_candidates(e, sym, texts) if auto else _el_candidates(e, sym, texts)[:1]
        best, best_s = cands[0], None
        for i, c in enumerate(cands):
            sc = _score(grid, c.boxes, e.id) + 0.01 * i
            if best_s is None or sc < best_s:
                best, best_s = c, sc
            if sc < 0.5:
                break
        out.elements[e.id] = best
        for b in best.boxes:
            grid.add(b, "text", e.id)
    for w in sheet.wires:
        pts = routes.get(w.id)
        if not pts or len(pts) < 2:
            continue
        label = wire_label(w.attrs, w.conductors)
        xref = xref_of(w)
        if not (label or xref):
            continue
        cands = _candidates(pts, bool(w.points), label, xref)
        if not auto:
            cands = cands[:1]
        best, best_s = cands[0], None
        for i, c in enumerate(cands):
            sc = _score(grid, c.boxes, w.id) + 0.01 * i
            if best_s is None or sc < best_s:
                best, best_s = c, sc
            if sc < 0.5:
                break
        out.wires[w.id] = best
        for b in best.boxes:
            grid.add(b, "text", w.id)
    return out


def layout_wire_labels(project: Project, sheet: Sheet, lib, routes=None, xref_of=None) -> dict[str, LabelPos]:
    return compute_layout(project, sheet, lib, routes, xref_of).wires


# ---- kontrola ------------------------------------------------------------------------------------------------
def text_overlaps(project: Project, sheet: Sheet, lib, layout: SheetTextLayout | None = None) -> list[tuple[str, str, str]]:
    """Překryvy textů na listu po automatickém rozmístění: [(id, id druhého, popis)] – text přes text,
    popisek přes vodič nebo čáru značky."""
    lay = layout or compute_layout(project, sheet, lib)
    names: dict[str, str] = {}
    texts: list[tuple[Box, str]] = []
    for e in sheet.elements:
        names[e.id] = e.ref or e.symbol_id.split(".")[-1]
        for b in (lay.elements[e.id].boxes if e.id in lay.elements else []):
            texts.append((b, e.id))
    for w in sheet.wires:
        names[w.id] = w.attrs.get("ref") or "vodič"
        for b in (lay.wires[w.id].boxes if w.id in lay.wires else []):
            texts.append((b, w.id))
    found: dict[tuple[str, str], str] = {}
    for i, (a, oa) in enumerate(texts):
        for b, ob in texts[i + 1:]:
            if oa != ob and boxes_overlap(a, b):
                found.setdefault(tuple(sorted((oa, ob))), f"text {names[oa]} přes text {names[ob]}")
    lines: list[tuple[Point, Point, str, str]] = [(a, b, wid, "vodič") for wid, pts in lay.routes.items()
                                                  for a, b in pairwise(pts)]
    for e in sheet.elements:
        lines += [(a, b, e.id, "značku") for a, b in symbol_segments(e, element_symbol(project, e, lib))]
    for box, owner in texts:
        for a, b, lo, kind in lines:
            if (owner, lo) not in found and segment_hits_box(a, b, box):
                what = f"vodič {names[lo]}" if kind == "vodič" else ("vlastní značku" if lo == owner else f"značku {names[lo]}")
                found[(owner, lo)] = f"text {names[owner]} přes {what}"
    return [(a, b, t) for (a, b), t in found.items()]
