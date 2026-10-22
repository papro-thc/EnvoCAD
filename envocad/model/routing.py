"""Trasování vodičů listu (bez Qt): ortogonální trasy, odstup souběžných vodičů, lomy při posunu prvků.

- `wire_route` – trasa jednoho vodiče (porty → ruční lomy → porty, jen svisle/vodorovně).
- `route_sheet` – trasy všech vodičů; automatické (bez ručních lomů) Z-trasy posune o násobek odstupu, aby
  nevedly po jiném vodiči (souběh blíž než `MIN_GAP`).
- `follow_points` – ruční lomy po posunu konců vodiče (lom u posunutého konce jde s ním, trasa zůstane pravoúhlá).
- `wire_overlaps` – souběhy, které zbyly (pro kontrolu projektu).
"""
from __future__ import annotations

from itertools import pairwise

from envocad.model.geometry import Point, orthogonalize
from envocad.model.grid import snap as _snap
from envocad.model.project import Element, Project, Sheet, Wire, element_symbol
from envocad.model.symbol import GRID, place_dir

DIR_VEC = {"N": (0, 1), "E": (1, 0), "S": (0, -1), "W": (-1, 0)}
MIN_GAP = 2 * GRID          # souběžné vodiče blíž než 5 mm = „přes sebe“
STAGGERS = (0.0, 5.0, -5.0, 10.0, -10.0, 15.0, -15.0, 20.0, -20.0)



def port_geometry(project: Project, sheet: Sheet, lib, e: Element, port: str) -> tuple[Point, str]:
    sym = element_symbol(project, e, lib)
    return e.port_pos(sym, port), place_dir(sym.port(port).dir, e.rotation, e.mirror)


def wire_route(project: Project, sheet: Sheet, lib, w: Wire, stagger: float = 0.0,
               els: dict[str, Element] | None = None) -> list[Point]:
    """Trasa vodiče v souřadnicích modelu. `stagger` posune lom automatické Z-trasy. `els` = prvky listu podle id
    (`element_map`; trasování celého listu tak nehledá prvky lineárně)."""
    if els is None:
        ea, eb = sheet.element(w.a.element_id), sheet.element(w.b.element_id)
    else:
        ea, eb = els[w.a.element_id], els[w.b.element_id]
    pa, da = port_geometry(project, sheet, lib, ea, w.a.port)
    pb, db = port_geometry(project, sheet, lib, eb, w.b.port)
    return route_points(pa, da, pb, db, w.points, stagger)


def element_map(sheet: Sheet) -> dict[str, Element]:
    """Prvky listu podle id – při duplicitním id první (jako `Sheet.element`)."""
    out: dict[str, Element] = {}
    for e in sheet.elements:
        out.setdefault(e.id, e)
    return out


def route_points(pa: Point, da: str, pb: Point, db: str, mid: list[Point], stagger: float = 0.0) -> list[Point]:
    va, vb = DIR_VEC[da], DIR_VEC[db]
    s1 = (pa[0] + va[0] * GRID, pa[1] + va[1] * GRID)
    s2 = (pb[0] + vb[0] * GRID, pb[1] + vb[1] * GRID)
    if mid:
        return [pa, *orthogonalize([s1, *mid, s2], end_horizontal=db in ("E", "W")), pb]
    pts = [pa, s1]
    hor = da in ("E", "W")
    if hor and db in ("E", "W") and abs(s1[1] - s2[1]) > 1e-6:
        mx = _snap((s1[0] + s2[0]) / 2) + stagger
        pts += [(mx, s1[1]), (mx, s2[1])]
    elif not hor and db in ("N", "S") and abs(s1[0] - s2[0]) > 1e-6:
        my = _snap((s1[1] + s2[1]) / 2) + stagger
        pts += [(s1[0], my), (s2[0], my)]
    elif hor:
        pts.append((s2[0], s1[1]))
    else:
        pts.append((s1[0], s2[1]))
    return pts + [s2, pb]


def is_staggerable(pts_no_stagger: list[Point], w: Wire) -> bool:
    return not w.points and len(pts_no_stagger) == 6


# ---- souběhy ---------------------------------------------------------------------------------------------------
def _inner_segments(pts: list[Point]) -> list[tuple[Point, Point]]:
    """Úseky bez krátkých vývodů u portů (vodiče ze stejného portu je sdílejí)."""
    segs = [(a, b) for a, b in pairwise(pts) if abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1e-6]
    return segs[1:-1] if len(segs) > 2 else []


def segments_conflict(s1: tuple[Point, Point], s2: tuple[Point, Point], gap: float = MIN_GAP) -> bool:
    """Dva rovnoběžné (vodorovné nebo svislé) úseky vedou po sobě nebo blíž než `gap`, a překrývají se po délce."""
    (a1, b1), (a2, b2) = s1, s2
    h1, h2 = abs(a1[1] - b1[1]) < 1e-6, abs(a2[1] - b2[1]) < 1e-6
    v1, v2 = abs(a1[0] - b1[0]) < 1e-6, abs(a2[0] - b2[0]) < 1e-6
    if h1 and h2:
        if abs(a1[1] - a2[1]) >= gap - 1e-6:
            return False
        lo1, hi1 = sorted((a1[0], b1[0]))
        lo2, hi2 = sorted((a2[0], b2[0]))
    elif v1 and v2:
        if abs(a1[0] - a2[0]) >= gap - 1e-6:
            return False
        lo1, hi1 = sorted((a1[1], b1[1]))
        lo2, hi2 = sorted((a2[1], b2[1]))
    else:
        return False
    return min(hi1, hi2) - max(lo1, lo2) > 1e-6


def conflicts(pts: list[Point], others: list[list[tuple[Point, Point]]]) -> int:
    mine = _inner_segments(pts)
    return sum(1 for s in mine for segs in others for o in segs if segments_conflict(s, o))


def segments_cross(s1: tuple[Point, Point], s2: tuple[Point, Point]) -> bool:
    """Vodorovný a svislý úsek se kříží uvnitř obou."""
    (a1, b1), (a2, b2) = s1, s2
    if abs(a1[1] - b1[1]) < 1e-6 and abs(a2[0] - b2[0]) < 1e-6:
        h, v = s1, s2
    elif abs(a1[0] - b1[0]) < 1e-6 and abs(a2[1] - b2[1]) < 1e-6:
        h, v = s2, s1
    else:
        return False
    x, y = v[0][0], h[0][1]
    hx1, hx2 = sorted((h[0][0], h[1][0]))
    vy1, vy2 = sorted((v[0][1], v[1][1]))
    return hx1 + 1e-6 < x < hx2 - 1e-6 and vy1 + 1e-6 < y < vy2 - 1e-6


def route_score(pts: list[Point], others: list[list[tuple[Point, Point]]]) -> float:
    """Souběh = 1, křížení = 0,3 (křížení se dá snést, souběh ne)."""
    return _route_score_boxed(pts, _boxed(others))


def _seg_box(s: tuple[Point, Point]) -> tuple[float, float, float, float]:
    (ax, ay), (bx, by) = s
    return (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))


def _box_entry(segs: list[tuple[Point, Point]]):
    """Úseky jednoho vodiče s obálkami zvětšenými o `MIN_GAP` a obálka celého vodiče; None = bez úseků."""
    if not segs:
        return None
    items = []
    for o in segs:
        x0, y0, x1, y1 = _seg_box(o)
        items.append((o, x0 - MIN_GAP, y0 - MIN_GAP, x1 + MIN_GAP, y1 + MIN_GAP))
    return (min(b[1] for b in items), min(b[2] for b in items), max(b[3] for b in items),
            max(b[4] for b in items), items)


def _boxed(others: list[list[tuple[Point, Point]]]) -> list:
    """Úseky ostatních vodičů s obálkami (`_box_entry`) – po vodičích, v původním pořadí."""
    return [b for b in map(_box_entry, others) if b is not None]


def _route_score_boxed(pts: list[Point], boxed: list) -> float:
    """`route_score` nad `_boxed`: úsek, jehož obálka (+ `MIN_GAP`) se nedotkne obálky úseku trasy, nemůže být
    souběh ani křížení – přeskočí se. Pořadí sčítání nenulových příspěvků je stejné jako u úplného průchodu, takže
    výsledek je bit po bitu shodný."""
    sc = 0.0
    for s in _inner_segments(pts):
        sx0, sy0, sx1, sy1 = _seg_box(s)
        for gx0, gy0, gx1, gy1, items in boxed:
            if gx0 > sx1 or gx1 < sx0 or gy0 > sy1 or gy1 < sy0:
                continue
            for o, ox0, oy0, ox1, oy1 in items:
                if ox0 > sx1 or ox1 < sx0 or oy0 > sy1 or oy1 < sy0:
                    continue
                if segments_conflict(s, o):
                    sc += 1.0
                elif segments_cross(s, o):
                    sc += 0.3
    return sc


def ends(w: Wire) -> set[tuple[str, str]]:
    return {(w.a.element_id, w.a.port), (w.b.element_id, w.b.port)}


def best_route(project: Project, sheet: Sheet, lib, w: Wire, others,
               els: dict[str, Element] | None = None) -> list[Point]:
    """Trasa vodiče s nejmenším souběhem s ostatními (u ručních lomů beze změny). `others` = [(konce, úseky)];
    vodiče ze stejného portu (odbočka téhož potenciálu) smějí vést spolu. `els` jako u `wire_route`."""
    return _best_route(project, sheet, lib, w, [(e, _box_entry(segs)) for e, segs in others], els)


def _best_route(project: Project, sheet: Sheet, lib, w: Wire, placed: list,
                els: dict[str, Element] | None) -> list[Point]:
    """`best_route` nad položenými vodiči s obálkami: `placed` = [(konce, `_box_entry`)]."""
    mine = ends(w)
    base = wire_route(project, sheet, lib, w, els=els)
    if not is_staggerable(base, w):
        return base
    boxed = [b for e, b in placed if b is not None and not (e & mine)]
    if not boxed:
        return base                   # bez ostatních úseků je skóre 0 – základní trasa
    best, best_n = base, _route_score_boxed(base, boxed)
    horiz = abs(base[1][1] - base[2][1]) < 1e-6        # Z-trasa vodorovně–svisle–vodorovně
    k = 0 if horiz else 1
    lo, hi = sorted((base[1][k], base[4][k]))
    for st in STAGGERS[1:]:
        if best_n == 0:
            break
        pts = wire_route(project, sheet, lib, w, st, els=els)
        if not (lo + 1e-6 < pts[2][k] < hi - 1e-6):    # lom mimo rozpětí → vodič by se vracel
            continue
        n = _route_score_boxed(pts, boxed) + 0.01 * abs(st)
        if n < best_n - 1e-9:
            best, best_n = pts, n
    return best


def route_sheet(project: Project, sheet: Sheet, lib) -> dict[str, list[Point]]:
    """Trasy všech vodičů listu: nejdřív ručně lomené (pevné), pak automatické s odstupem od již položených.
    Obálky úseků položených vodičů se počítají jednou (`_box_entry`), prvky listu se hledají přes mapu."""
    routes: dict[str, list[Point]] = {}
    order = sorted(sheet.wires, key=lambda w: 0 if w.points else 1)
    placed: list = []
    els = element_map(sheet)
    for w in order:
        try:
            pts = _best_route(project, sheet, lib, w, placed, els)
        except (KeyError, ValueError, AttributeError, StopIteration):
            continue
        routes[w.id] = pts
        placed.append((ends(w), _box_entry(_inner_segments(pts))))
    return routes


def wire_overlaps(sheet: Sheet, routes: dict[str, list[Point]]) -> list[tuple[str, str]]:
    """Dvojice vodičů, které vedou přes sebe (souběh blíž než 5 mm)."""
    segs = {wid: _inner_segments(pts) for wid, pts in routes.items()}
    wires = {w.id: w for w in sheet.wires}
    ids = [w.id for w in sheet.wires if segs.get(w.id)]
    # prostorový index obálek (zvětšených o MIN_GAP): porovnají se jen vodiče v sousedních buňkách mřížky
    cell = 20.0
    grid: dict[tuple[int, int], list[int]] = {}
    boxes = []
    for i, wid in enumerate(ids):
        xs = [x for s in segs[wid] for x in (s[0][0], s[1][0])]
        ys = [y for s in segs[wid] for y in (s[0][1], s[1][1])]
        b = (min(xs) - MIN_GAP, min(ys) - MIN_GAP, max(xs) + MIN_GAP, max(ys) + MIN_GAP)
        boxes.append(b)
        for gx in range(int(b[0] // cell), int(b[2] // cell) + 1):
            for gy in range(int(b[1] // cell), int(b[3] // cell) + 1):
                grid.setdefault((gx, gy), []).append(i)
    out = []
    for i, a in enumerate(ids):
        ba = boxes[i]
        near = set()
        for gx in range(int(ba[0] // cell), int(ba[2] // cell) + 1):
            for gy in range(int(ba[1] // cell), int(ba[3] // cell) + 1):
                near.update(j for j in grid.get((gx, gy), ()) if j > i)
        for j in sorted(near):
            b = ids[j]
            if ends(wires[a]) & ends(wires[b]):
                continue   # odbočka ze stejného portu
            if any(segments_conflict(s, o) for s in segs[a] for o in segs[b]):
                out.append((a, b))
    return out


# ---- lomy při posunu ---------------------------------------------------------------------------------------------
def follow_points(points: list[Point], dir_a: str, delta_a: Point, dir_b: str, delta_b: Point) -> list[Point]:
    """Ruční lomy po posunu konců vodiče o `delta_a` / `delta_b`.

    Oba konce stejně → celý vodič se posune. Jinak se posune jen bod u posunutého konce, a to kolmo k vývodu portu
    (vodorovný vývod → bod jde svisle s portem), takže první úsek zůstane rovný; zbytek trasy drží."""
    if not points:
        return []
    pts = [tuple(p) for p in points]
    if abs(delta_a[0] - delta_b[0]) < 1e-9 and abs(delta_a[1] - delta_b[1]) < 1e-9:
        return [(x + delta_a[0], y + delta_a[1]) for x, y in pts]

    def shift(i: int, d: str, delta: Point) -> None:
        x, y = pts[i]
        pts[i] = (x, y + delta[1]) if d in ("E", "W") else (x + delta[0], y)
    if delta_a != (0.0, 0.0):
        shift(0, dir_a, delta_a)
    if delta_b != (0.0, 0.0):
        if len(pts) == 1 and delta_a != (0.0, 0.0):
            pts.append(pts[0])          # jeden lom a oba konce jinak: rozdělit na dva body
        shift(len(pts) - 1, dir_b, delta_b)
    return [(float(x), float(y)) for x, y in pts]


def simplify_points(pts: list[Point]) -> list[Point]:
    """Sloučí duplicitní a v přímce ležící body (ruční lomy po úpravě úseku)."""
    out: list[Point] = []
    for p in pts:
        if out and abs(p[0] - out[-1][0]) < 1e-6 and abs(p[1] - out[-1][1]) < 1e-6:
            continue
        out.append(p)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        if (abs(a[0] - b[0]) < 1e-6 and abs(b[0] - c[0]) < 1e-6) or (abs(a[1] - b[1]) < 1e-6 and abs(b[1] - c[1]) < 1e-6):
            out.pop(i)
            # trasa tam a zpět po přímce: po odebrání středu můžou zůstat dva stejné body za sebou
            if abs(a[0] - c[0]) < 1e-6 and abs(a[1] - c[1]) < 1e-6:
                out.pop(i)
            i = max(1, i - 1)
        else:
            i += 1
    return out


def drag_segment(route: list[Point], index: int, offset: float) -> list[Point] | None:
    """Posun úseku `index` trasy (route = celá trasa vč. portů) kolmo o `offset`: vrací nové ruční lomy, nebo None
    (úsek u portu se neposouvá)."""
    if index <= 0 or index >= len(route) - 2:
        return None
    a, b = route[index], route[index + 1]
    pts = [tuple(p) for p in route[1:-1]]          # bez portů; vývody (stub) jako ruční body
    i = index - 1
    if abs(a[1] - b[1]) < 1e-6:                     # vodorovný → svisle
        pts[i] = (pts[i][0], pts[i][1] + offset)
        pts[i + 1] = (pts[i + 1][0], pts[i + 1][1] + offset)
    else:
        pts[i] = (pts[i][0] + offset, pts[i][1])
        pts[i + 1] = (pts[i + 1][0] + offset, pts[i + 1][1])
    # krajní body = vývody portů: route() si vývod přidá sám, posunutý vývod se z nich napojí kolmo
    return simplify_points([(float(x), float(y)) for x, y in pts])


def nearest_segment(route: list[Point], x: float, y: float, tol: float = 2.0) -> int | None:
    best, best_d = None, tol
    for i, (a, b) in enumerate(pairwise(route)):
        x1, x2 = sorted((a[0], b[0]))
        y1, y2 = sorted((a[1], b[1]))
        dx = max(x1 - x, 0, x - x2)
        dy = max(y1 - y, 0, y - y2)
        d = (dx * dx + dy * dy) ** 0.5
        if d <= best_d:
            best, best_d = i, d
    return best
