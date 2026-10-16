"""Vlastnosti (property-based, hypothesis): trasy vodičů jen svisle/vodorovně, úpravy lomů, stabilita formátu a rozložení."""
import copy
from itertools import pairwise

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Wire, WireEnd
from envocad.model.routing import DIR_VEC, drag_segment, follow_points, route_points, simplify_points
from envocad.model.symbol import GRID

DIRS = list(DIR_VEC)
grid = st.integers(-80, 80).map(lambda i: i * GRID)
point = st.tuples(grid, grid)
direction = st.sampled_from(DIRS)

FAST = settings(max_examples=300, deadline=None)


def _orthogonal(pts) -> bool:
    return all(abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6 for a, b in pairwise(pts))


def _close(a, b) -> bool:
    return abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6


@FAST
@given(point, direction, point, direction, st.lists(point, max_size=5), st.sampled_from([0.0, 5.0, -5.0, 10.0]))
def test_route_is_orthogonal_and_leaves_ports_straight(pa, da, pb, db, mid, stagger):
    pts = route_points(pa, da, pb, db, mid, stagger)
    assert _close(pts[0], pa) and _close(pts[-1], pb)
    assert _orthogonal(pts), pts
    # první a poslední úsek vede ve směru portu (vývod), ne šikmo ani zpět do značky
    va, vb = DIR_VEC[da], DIR_VEC[db]
    assert _close(pts[1], (pa[0] + va[0] * GRID, pa[1] + va[1] * GRID))
    assert _close(pts[-2], (pb[0] + vb[0] * GRID, pb[1] + vb[1] * GRID))


@FAST
@given(st.lists(point, min_size=1, max_size=10))
def test_simplify_points(pts):
    out = simplify_points(pts)
    assert simplify_points(out) == out                       # idempotentní
    assert _close(out[0], pts[0]) and _close(out[-1], pts[-1])
    assert all(not _close(a, b) for a, b in pairwise(out))   # žádné duplicity
    for a, b, c in zip(out, out[1:], out[2:]):
        assert not (abs(a[0] - b[0]) < 1e-6 and abs(b[0] - c[0]) < 1e-6)   # žádné tři body ve svislé přímce
        assert not (abs(a[1] - b[1]) < 1e-6 and abs(b[1] - c[1]) < 1e-6)


@FAST
@given(point, direction, point, direction, st.lists(point, max_size=4), st.data())
def test_drag_segment_keeps_route_orthogonal(pa, da, pb, db, mid, data):
    route = route_points(pa, da, pb, db, mid)
    if len(route) < 4:
        return
    idx = data.draw(st.integers(0, len(route) - 2))
    off = data.draw(st.integers(-8, 8).map(lambda i: i * GRID))
    new = drag_segment(route, idx, off)
    if new is None:
        assert idx <= 0 or idx >= len(route) - 2
        return
    assert _orthogonal(route_points(pa, da, pb, db, new))


@FAST
@given(st.lists(point, min_size=1, max_size=6), direction, direction, point)
def test_follow_points_same_delta_is_translation(pts, da, db, d):
    out = follow_points(pts, da, d, db, d)
    assert out == [(x + d[0], y + d[1]) for x, y in pts]


@FAST
@given(st.lists(point, min_size=1, max_size=6), direction, direction, point)
def test_follow_points_one_end_moves_only_perpendicular(pts, da, db, d):
    out = follow_points(pts, da, d, db, (0.0, 0.0))
    assert len(out) == len(pts)
    x0, y0 = pts[0]
    if da in ("E", "W"):
        assert out[0] == (x0, y0 + d[1])
    else:
        assert out[0] == (x0 + d[0], y0)
    assert out[1:] == [tuple(map(float, p)) for p in pts[1:]]


# ---- náhodné projekty -------------------------------------------------------------------------------
SYMS = [("fve.breaker_mcb", "1", "2"), ("fve.dc_disconnect", "1", "2"), ("fve.meter", "1", "2")]


@st.composite
def projects(draw):
    p = Project(name=draw(st.text(min_size=1, max_size=12)))
    s = p.sheets[0]
    n = draw(st.integers(1, 6))
    used = set()
    for i in range(n):
        sym = draw(st.sampled_from(SYMS))
        x = draw(st.integers(4, 60)) * 5.0
        y = draw(st.integers(4, 50)) * 5.0
        if (x, y) in used:
            continue
        used.add((x, y))
        e = Element(sym[0], x, y, rotation=draw(st.sampled_from([0, 90, 180, 270])),
                    attrs={"ref": f"F{i + 1}", "desc": draw(st.text(max_size=8))})
        s.elements.append(e)
    els = s.elements
    for _ in range(draw(st.integers(0, len(els)))):
        a, b = draw(st.sampled_from(els)), draw(st.sampled_from(els))
        if a is b:
            continue
        pts = draw(st.lists(st.tuples(st.integers(4, 80).map(lambda v: v * 5.0),
                                      st.integers(4, 55).map(lambda v: v * 5.0)), max_size=2))
        s.wires.append(Wire(WireEnd(a.id, "2"), WireEnd(b.id, "1"), points=pts,
                            attrs={"ref": draw(st.sampled_from(["", "W1", "W2"]))}))
    return p


LIB = None


def _lib():
    global LIB
    if LIB is None:
        LIB = LibraryStore()
    return LIB


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(projects())
def test_project_roundtrip(p):
    d = p.to_dict()
    assert Project.from_dict(copy.deepcopy(d)).to_dict() == d


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(projects())
def test_sheet_routes_orthogonal_and_layout_deterministic(p):
    from envocad.model.routing import route_sheet
    from envocad.model.textlayout import compute_layout
    lib, s = _lib(), p.sheets[0]
    routes = route_sheet(p, s, lib)
    assert set(routes) == {w.id for w in s.wires}
    for pts in routes.values():
        assert _orthogonal(pts), pts
    a = compute_layout(p, s, lib)
    b = compute_layout(p, s, lib)
    assert a.routes == b.routes
    assert {k: (v.x, v.y, v.lines) for k, v in a.elements.items()} == {k: (v.x, v.y, v.lines) for k, v in b.elements.items()}
    assert {k: (v.x, v.y, v.lines) for k, v in a.wires.items()} == {k: (v.x, v.y, v.lines) for k, v in b.wires.items()}
