"""Rozmístění a kontrola textů ve výkresu (popisky prvků a vodičů) – bez Qt.

Popisek vodiče se umístí na první volné místo z kandidátů (výchozí poloha, začátek/střed/konec každého úseku,
u svislého úseku vpravo i vlevo), aby nepřekrýval popisky prvků, značky, cizí vodiče ani jiné popisky vodičů.
Co se nepodaří rozmístit, hlásí kontrola projektu (`text_overlap_findings`). Stejný výpočet používá editor i DXF.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from itertools import pairwise

from envocad.model.designation import display_designation, element_name
from envocad.model.geometry import Point, wire_label_anchor
from envocad.model.project import Element, Project, Sheet, element_symbol, element_xref, wire_label, wire_xref
from envocad.model.symbol import MIRROR_ALIGN, place_point, rotate_point

Box = tuple[float, float, float, float]   # x1, y1, x2, y2 (x1<x2, y1<y2)
DIR_VEC = {"N": (0, 1), "E": (1, 0), "S": (0, -1), "W": (-1, 0)}
CHAR_W = 0.72     # průměrná šířka znaku Arial / výška textu
GAP = 1.5


def text_box(x: float, y: float, text: str, h: float, align: str = "left") -> Box:
    """Obdélník textu: (x, y) = bod základny podle zarovnání (stejně jako `draw_text`)."""
    w = len(text) * h * CHAR_W
    x1 = {"left": x, "center": x - w / 2, "right": x - w}.get(align, x)
    return (x1, y - 0.3 * h, x1 + w, y + 1.0 * h)


def sheet_text_boxes(t) -> list[Box]:
    """Obálky řádků volného textu listu (`project.SheetText`)."""
    from envocad.model.project import TEXT_LINE
    return [text_box(t.x, t.y - i * TEXT_LINE * t.height, line, t.height) for i, line in enumerate(t.lines())
            if line.strip()]


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
        out.append((x, y + line, display_designation(sheet, e), 2.5))
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
    pts = [place_point(px, py, e.rotation, getattr(e, "mirror", False)) for px, py in ((x1, y1), (x2, y2))]
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
    return list(_iter_candidates(pts, manual, label, xref))


def _iter_candidates(pts: list[Point], manual: bool, label: str, xref: str):
    """Kandidátní polohy popisku vodiče v pořadí přednosti (`_candidates`) – postupně: rozmístění končí na prvním
    volném, další se pak nepočítají."""
    x, y, align, vertical = wire_label_anchor(pts)
    if manual and len(pts) >= 2 and abs(pts[1][1] - pts[0][1]) < 1e-6:
        x, y, align, vertical = min(pts[0][0], pts[1][0]) + GAP, pts[0][1] + GAP, "left", False
    yield _place(x, y, align, vertical, label, xref, (x - GAP, y + 1.0) if vertical else None)
    width = max([len(t) * 2.0 * CHAR_W for t in (label, xref) if t] or [0.0])
    segs = sorted(((a, b) for a, b in pairwise(pts) if abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1e-6),
                  key=lambda s: -(abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1])))
    for a, b in segs:
        if abs(a[1] - b[1]) < 1e-6:            # vodorovný úsek: nad vodičem vlevo / uprostřed / vpravo
            x1, x2 = sorted((a[0], b[0]))
            if x2 - x1 < width + 2 * GAP:
                continue
            yy = a[1] + GAP
            yield _place(x1 + GAP, yy, "left", False, label, xref, None)
            yield _place((x1 + x2) / 2, yy, "center", False, label, xref, None)
            yield _place(x2 - GAP, yy, "right", False, label, xref, None)
        else:                                  # svislý úsek: vpravo nebo vlevo, ve třetinách délky
            y1, y2 = sorted((a[1], b[1]))
            if y2 - y1 < 6.0:
                continue
            for f in (0.5, 0.75, 0.25, 0.9, 0.1):
                yy = y1 + (y2 - y1) * f - 1.0
                yield _place(a[0] + GAP, yy, "left", True, label, xref, (a[0], yy + 1.0))
                yield _place(a[0] - GAP - 1.5, yy, "right", True, label, xref, (a[0], yy + 1.0))


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


class _IndexGrid:
    """Mřížka indexů obdélníků (buňka 20 mm): `near` vrátí indexy položek ze sousedních buněk vzestupně."""
    CELL = 20.0

    def __init__(self) -> None:
        self.cells: dict[tuple[int, int], list[int]] = {}

    def _keys(self, b: Box):
        c = self.CELL
        for i in range(int(b[0] // c), int(b[2] // c) + 1):
            for j in range(int(b[1] // c), int(b[3] // c) + 1):
                yield (i, j)

    def add(self, b: Box, idx: int) -> None:
        for k in self._keys(b):
            self.cells.setdefault(k, []).append(idx)

    def near(self, b: Box, after: int = -1) -> list[int]:
        out: set[int] = set()
        for k in self._keys(b):
            out.update(i for i in self.cells.get(k, ()) if i > after)
        return sorted(out)


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
        rx, ry = place_point(x, y, e.rotation, getattr(e, "mirror", False))
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
            x, y = place_point(pr["x"], pr["y"], e.rotation, getattr(e, "mirror", False))
            h = pr.get("height", 2.5)
            if e.rotation % 180:
                w = len(pr["text"]) * h * CHAR_W
                # otočený text: výška písma míří u 270° k +x, u 90° k −x
                up, down = (1.0 * h, 0.3 * h) if e.rotation % 360 == 270 else (0.3 * h, 1.0 * h)
                out.append((e.x + x - down, e.y + y - w / 2, e.x + x + up, e.y + y + w / 2))
            else:
                align = pr.get("align", "center")
                out.append(text_box(e.x + x, e.y + y, pr["text"], h, MIRROR_ALIGN.get(align, align) if getattr(e, "mirror", False) else align))
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
        out.append((display_designation(sheet, e), 2.5))
    out += [(t, 2.0) for t in sym.label_lines(e.attrs)]
    if xref is None:
        try:
            xref = element_xref(project, sheet, e)
        except Exception:  # noqa: BLE001
            xref = ""
    out += [(t, 2.0) for t in xref.splitlines()]
    return out


def _el_candidates(e: Element, sym, texts) -> list[ElementLabel]:
    return list(_iter_el_candidates(e, sym, texts))


def _iter_el_candidates(e: Element, sym, texts):
    """Kandidátní polohy popisku prvku v pořadí přednosti (`_el_candidates`) – postupně, jako `_iter_candidates`."""
    lx, ly = rotate_point(*sym.label_pos, e.rotation)
    yield _el_label(e.x + lx, e.y + ly, "left", texts)
    bx1, by1, bx2, by2 = symbol_box(e, sym)
    n_h = 2.5 if texts and texts[0][1] >= 2.5 else 2.0
    block = (3.5 if n_h >= 2.5 else 3.0) + 3.0 * (len(texts) - 2) if len(texts) > 1 else 0.0
    cy = (by1 + by2) / 2
    top_mid = cy + block / 2 - n_h / 2          # blok svisle na střed značky
    yield _el_label(bx2 + GAP, top_mid, "left", texts)                    # vpravo od značky
    yield _el_label(bx1 - GAP, top_mid, "right", texts)                   # vlevo
    yield _el_label(bx2 + GAP, by2 - n_h, "left", texts)                  # vpravo nahoře
    yield _el_label(bx1 - GAP, by2 - n_h, "right", texts)                 # vlevo nahoře
    yield _el_label(bx2 + GAP, by1 + block, "left", texts)                # vpravo dole
    yield _el_label(bx1 - GAP, by1 + block, "right", texts)               # vlevo dole
    yield _el_label(bx1, by2 + GAP + 0.3 * n_h + block, "left", texts)    # nad
    yield _el_label(bx1, by1 - GAP - n_h, "left", texts)                  # pod


@dataclass
class SheetTextLayout:
    elements: dict[str, ElementLabel] = field(default_factory=dict)
    wires: dict[str, LabelPos] = field(default_factory=dict)
    routes: dict[str, list[Point]] = field(default_factory=dict)
    mirrors: dict = field(default_factory=dict)      # id hostitele → xref.MirrorGeometry (pevná poloha pod značkou)


def _score(grid: _Grid, boxes: list[Box], own: str) -> float:
    """Kolize obdélníků `boxes` s mřížkou: čára přes text `WEIGHT["line"]`, cizí text `WEIGHT["text"]`. Jako
    průchod `grid.near` (každá položka jednou na obdélník), čáry mimo obálku textu se vyřadí bez Liang–Barsky."""
    s = 0.0
    w_line, w_text = WEIGHT["line"], WEIGHT["text"]
    cells, c = grid.cells, grid.CELL
    for b in boxes:
        bx0, by0, bx1, by1 = b
        lx0, ly0, lx1, ly1 = bx0 + 0.2, by0 + 0.2, bx1 - 0.2, by1 - 0.2     # tolerance `segment_hits_box`
        seen: set[int] = set()
        for i in range(int(bx0 // c), int(bx1 // c) + 1):
            for j in range(int(by0 // c), int(by1 // c) + 1):
                for item in cells.get((i, j), ()):
                    k = id(item)
                    if k in seen:
                        continue
                    seen.add(k)
                    ob, kind, owner = item
                    if kind == "line":
                        x0, x1 = (ob[0], ob[2]) if ob[0] <= ob[2] else (ob[2], ob[0])
                        y0, y1 = (ob[1], ob[3]) if ob[1] <= ob[3] else (ob[3], ob[1])
                        if x1 < lx0 or x0 > lx1 or y1 < ly0 or y0 > ly1:
                            continue              # úsečka celá mimo obdélník – `segment_hits_box` by vrátil False
                        if segment_hits_box((ob[0], ob[1]), (ob[2], ob[3]), b):
                            s += w_line
                    elif owner != own and boxes_overlap(b, ob):
                        s += w_text
    return s


def _add_line(grid: _Grid, p: Point, q: Point, owner: str) -> None:
    # do mřížky jde obálka, ale uložené souřadnice jsou krajní body úsečky (ne min/max) – pro šikmé čáry
    box = (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))
    for k in grid._keys(box):
        grid.cells.setdefault(k, []).append(((p[0], p[1], q[0], q[1]), "line", owner))


_LAYOUT_CACHE: dict | None = None


@contextmanager
def layout_cache():
    """Mezipaměť `compute_layout` po dobu bloku (generátor: zkoušení rozložení blokového schématu a rozmístění na
    listy počítá rozložení textů téhož stavu listu opakovaně). Klíč je úplný stav projektu, na kterém rozložení
    závisí (`_layout_key`: listy v pořadí, jejich formát a aspekty, prvky, vodiče a volné texty s atributy) – změna
    čehokoli z toho znamená nový výpočet, takže výsledek je stejný jako bez mezipaměti. Vrácené rozložení je sdílené
    – volající ho nesmí měnit. Jen jedno vlákno (GUI ji nepoužívá); vnořený blok sdílí vnější mezipaměť."""
    global _LAYOUT_CACHE
    outer = _LAYOUT_CACHE
    if outer is None:
        _LAYOUT_CACHE = {}
    try:
        yield
    finally:
        if outer is None:
            _LAYOUT_CACHE = None


def _sheet_key(s: Sheet) -> tuple:
    return (s.id, s.kind, s.parent_element_id, s.name, s.paper, s.width, s.height, s.func, s.loc, s.mp_paper,
            tuple((e.id, e.symbol_id, e.x, e.y, e.rotation, e.mirror, e.component_id, tuple(e.attrs.items()))
                  for e in s.elements),
            tuple((w.id, w.a.element_id, w.a.port, w.b.element_id, w.b.port, tuple(w.points), tuple(w.attrs.items()),
                   tuple(w.conductors)) for w in s.wires),
            tuple((t.id, t.x, t.y, t.text, t.height) for t in s.texts))


def _layout_key(project: Project, sheet: Sheet, lib) -> tuple:
    """Klíč `layout_cache`: rozložení listu závisí i na ostatních listech (křížové odkazy přerušení a kontaktů,
    vazby přívodů rozvaděčů, čísla listů, porty bloků podle listů rozvaděčů)."""
    return (id(project), id(lib), _sheet_key(sheet), tuple(_sheet_key(s) for s in project.sheets),
            tuple(project.meta.items()))


def compute_layout(project: Project, sheet: Sheet, lib, routes: dict[str, list[Point]] | None = None,
                   xref_of=None, auto: bool = True, index=None) -> SheetTextLayout:
    """`_compute_layout`; v bloku `layout_cache` (a jen s výchozími parametry) z mezipaměti."""
    cache = _LAYOUT_CACHE
    if cache is None or routes is not None or xref_of is not None or not auto or index is not None:
        return _compute_layout(project, sheet, lib, routes, xref_of, auto, index)
    key = _layout_key(project, sheet, lib)
    try:
        hit = cache.get(key)
    except TypeError:                 # nehashovatelná hodnota atributu – bez mezipaměti
        return _compute_layout(project, sheet, lib)
    if hit is None:
        hit = cache[key] = _compute_layout(project, sheet, lib)
    return hit


def _compute_layout(project: Project, sheet: Sheet, lib, routes: dict[str, list[Point]] | None = None,
                    xref_of=None, auto: bool = True, index=None) -> SheetTextLayout:
    """Rozmístí popisky prvků (výchozí poloha značky, když je volná, jinak vpravo/vlevo/nad/pod) a pak popisky
    vodičů. `routes` = trasy z editoru (jinak `wire_route`); `auto=False` = jen výchozí polohy (pro kontrolu).
    Zrcadla kontaktů (`mirrors`) mají pevnou polohu pod hostitelem a jejich místo se rezervuje před popisky.
    `index` = `xref.DeviceIndex` (jinak se postaví jednou pro celý list)."""
    from envocad.model.xref import DeviceIndex, sheet_mirrors
    if index is None:
        index = DeviceIndex.build(project)
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
    for t in sheet.texts:                      # volné texty listu: popisky se jim vyhnou
        for b in sheet_text_boxes(t):
            grid.add(b, "text", t.id)
    for wid, pts in routes.items():
        for a, b in pairwise(pts):
            _add_line(grid, a, b, wid)
    out.mirrors = sheet_mirrors(project, sheet, lib, index, syms)
    for hid, m in out.mirrors.items():
        for x1, y1, x2, y2 in m.lines:
            _add_line(grid, (x1, y1), (x2, y2), hid + "#mirror")
        for b in m.boxes:
            grid.add(b, "text", hid + "#mirror")
    for e in sheet.elements:
        sym = syms[e.id]
        try:
            xref = element_xref(project, sheet, e, index)
        except Exception:  # noqa: BLE001
            xref = ""
        texts = element_label_texts(project, sheet, e, sym, xref)
        if not texts:
            continue
        best, best_s = None, None
        for i, c in enumerate(_iter_el_candidates(e, sym, texts)):     # postupně – většinou stačí první
            sc = _score(grid, c.boxes, e.id) + 0.01 * i
            if best_s is None or sc < best_s:
                best, best_s = c, sc
            if sc < 0.5 or not auto:
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
        best, best_s = None, None
        for i, c in enumerate(_iter_candidates(pts, bool(w.points), label, xref)):
            sc = _score(grid, c.boxes, w.id) + 0.01 * i
            if best_s is None or sc < best_s:
                best, best_s = c, sc
            if sc < 0.5 or not auto:
                break
        out.wires[w.id] = best
        for b in best.boxes:
            grid.add(b, "text", w.id)
    return out


def layout_wire_labels(project: Project, sheet: Sheet, lib, routes=None, xref_of=None) -> dict[str, LabelPos]:
    return compute_layout(project, sheet, lib, routes, xref_of).wires


PORT_MARK_R = 0.75   # kroužek portu v editoru přesahuje obálku značky


def sheet_content_boxes(project: Project, sheet: Sheet, lib, layout: SheetTextLayout | None = None) -> list[Box]:
    """Obálky všeho, co se na listu kreslí: značky (s kroužky portů), texty značek, popisky prvků a vodičů,
    úseky tras vodičů (jako tenké obdélníky) a zrcadla kontaktů. Pro kontrolu „obsah uvnitř listu“ a rozmístění
    generovaného schématu na list (`frame.fit_sheet_to_content`)."""
    lay = layout or compute_layout(project, sheet, lib)
    out: list[Box] = []
    r = PORT_MARK_R
    for e in sheet.elements:
        sym = element_symbol(project, e, lib)
        x1, y1, x2, y2 = symbol_box(e, sym)
        out.append((x1 - r, y1 - r, x2 + r, y2 + r))
        out += symbol_text_boxes(e, sym)
        if e.id in lay.elements:
            out += lay.elements[e.id].boxes
    for pts in lay.routes.values():
        for a, b in pairwise(pts):
            out.append((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])))
    for lp in lay.wires.values():
        out += lp.boxes
    for m in lay.mirrors.values():
        out += list(m.boxes)
        out += [(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)) for x1, y1, x2, y2 in m.lines]
    for t in sheet.texts:
        out += sheet_text_boxes(t)
    return out


def union_box(boxes: list[Box]) -> Box | None:
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


# ---- kontrola ------------------------------------------------------------------------------------------------
def text_overlaps(project: Project, sheet: Sheet, lib, layout: SheetTextLayout | None = None) -> list[tuple[str, str, str]]:
    """Překryvy textů na listu po automatickém rozmístění: [(id, id druhého, popis)] – text přes text,
    popisek přes vodič, čáru značky nebo čáru tabulky zrcadla kontaktů. Zrcadlo patří hostiteli: kolize zrcadla
    s vlastní značkou se nehlásí, kolize s popiskem hostitele ano (id druhého = id hostitele)."""
    lay = layout or compute_layout(project, sheet, lib)
    names: dict[str, str] = {}
    texts: list[tuple[Box, str, bool]] = []          # (obálka, vlastník, je text zrcadla)
    for e in sheet.elements:
        names[e.id] = element_name(e)
        for b in (lay.elements[e.id].boxes if e.id in lay.elements else []):
            texts.append((b, e.id, False))
    for w in sheet.wires:
        names[w.id] = w.attrs.get("ref") or "vodič"
        for b in (lay.wires[w.id].boxes if w.id in lay.wires else []):
            texts.append((b, w.id, False))
    mirrors = {hid: m for hid, m in lay.mirrors.items() if hid in names}
    for hid, m in mirrors.items():
        texts += [(b, hid, True) for b in m.boxes]

    def text_word(owner: str, mirror: bool) -> str:
        return f"zrcadlo kontaktů {names[owner]}" if mirror else f"text {names[owner]}"

    found: dict[tuple, tuple[str, str, str]] = {}
    # prostorový index (mřížka po `_Grid.CELL` mm) – porovnávají se jen texty a čáry v sousedních buňkách; pořadí
    # kandidátů zůstává jako při porovnání každý s každým (výsledek je stejný, jen O(n) místo O(n²))
    tgrid = _IndexGrid()
    for i, (a, _o, _m) in enumerate(texts):
        tgrid.add(a, i)
    for i, (a, oa, ma) in enumerate(texts):
        for j in tgrid.near(a, after=i):
            b, ob, mb = texts[j]
            if (oa, ma) == (ob, mb) or not boxes_overlap(a, b):
                continue
            key = frozenset(((oa, ma), (ob, mb)))
            if key not in found:
                found[key] = (oa, ob, f"{text_word(oa, ma)} přes {text_word(ob, mb)}")
    lines: list[tuple[Point, Point, str, str]] = [(a, b, wid, "vodič") for wid, pts in lay.routes.items()
                                                  for a, b in pairwise(pts)]
    for e in sheet.elements:
        lines += [(a, b, e.id, "značku") for a, b in symbol_segments(e, element_symbol(project, e, lib))]
    for hid, m in mirrors.items():
        lines += [((x1, y1), (x2, y2), hid, "zrcadlo") for x1, y1, x2, y2 in m.lines]
    lgrid = _IndexGrid()
    for k, (a, b, _lo, _kind) in enumerate(lines):
        lgrid.add((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])), k)
    for box, owner, mirror in texts:
        for k in lgrid.near(box):
            a, b, lo, kind = lines[k]
            if mirror and lo == owner and kind in ("značku", "zrcadlo"):
                continue                  # zrcadlo vs. vlastní značka / vlastní čáry tabulky
            key = ((owner, mirror), lo, kind == "zrcadlo")
            if key in found or not segment_hits_box(a, b, box):
                continue
            if kind == "vodič":
                what = f"vodič {names[lo]}"
            elif kind == "zrcadlo":
                what = "vlastní zrcadlo kontaktů" if lo == owner else f"zrcadlo kontaktů {names[lo]}"
            else:
                what = "vlastní značku" if lo == owner else f"značku {names[lo]}"
            found[key] = (owner, lo, f"{text_word(owner, mirror)} přes {what}")
    return list(found.values())
