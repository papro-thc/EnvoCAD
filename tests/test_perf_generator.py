"""Zrychlení generátoru (bez Qt): rychlejší cesty dávají stejný výsledek jako původní (úplný průchod).

Každá optimalizace má tu svou referenční (pomalou) podobu z doby před zrychlením a test porovná výsledek na
vygenerovaných projektech (firma s AC listy vestavěným kódem, rodinný dům, rozdělené JPS) i na náhodných datech.
Výstup generátoru celkově hlídá snímek `tests/data/generate_snapshot.json` (`test_macros.py`).
"""
from __future__ import annotations

import random
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pytest

from envocad.generate import build_project
from envocad.library.store import LibraryStore, _rel
from envocad.model import frame, routing, textlayout
from envocad.model.project import (
    FEED_SYMBOLS,
    Element,
    Project,
    Sheet,
    Wire,
    WireEnd,
    element_symbol,
    feed_link_index,
    linked_wire,
)

INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
SPECS = {
    "firma_3": {"inverters": [{"ref": f"T{i}", **INV, "strings": [20, 18]} for i in range(1, 4)]},
    "rd_2": {"building": "house", "inverters": [{"ref": f"T{i}", **INV, "strings": [14, 14]} for i in range(1, 3)]},
    "split_4x8": {"inverters": [{"ref": f"T{i}", **INV, "strings": [20] * 8} for i in range(1, 5)],
                  "jps": {"split": "auto", "max_paper": "A2", "paper": "A2"}},
}


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "lib.db")


@pytest.fixture(scope="module")
def projects(ac_builtin) -> dict[str, Project]:
    return {name: build_project(spec) for name, spec in SPECS.items()}


# ---- referenční (původní) implementace ------------------------------------------------------------------------
def _ref_route_score(pts, others) -> float:
    mine = routing._inner_segments(pts)
    sc = 0.0
    for s in mine:
        for segs in others:
            for o in segs:
                if routing.segments_conflict(s, o):
                    sc += 1.0
                elif routing.segments_cross(s, o):
                    sc += 0.3
    return sc


def _ref_best_route(project, sheet, lib, w, others):
    mine = routing.ends(w)
    others = [segs for e, segs in others if not (e & mine)]
    base = routing.wire_route(project, sheet, lib, w)
    if not routing.is_staggerable(base, w) or not others:
        return base
    best, best_n = base, _ref_route_score(base, others)
    horiz = abs(base[1][1] - base[2][1]) < 1e-6
    k = 0 if horiz else 1
    lo, hi = sorted((base[1][k], base[4][k]))
    for st in routing.STAGGERS[1:]:
        if best_n == 0:
            break
        pts = routing.wire_route(project, sheet, lib, w, st)
        if not (lo + 1e-6 < pts[2][k] < hi - 1e-6):
            continue
        n = _ref_route_score(pts, others) + 0.01 * abs(st)
        if n < best_n - 1e-9:
            best, best_n = pts, n
    return best


def _ref_route_sheet(project, sheet, lib):
    routes = {}
    placed = []
    for w in sorted(sheet.wires, key=lambda w: 0 if w.points else 1):
        try:
            pts = _ref_best_route(project, sheet, lib, w, placed)
        except (KeyError, ValueError, AttributeError, StopIteration):
            continue
        routes[w.id] = pts
        placed.append((routing.ends(w), routing._inner_segments(pts)))
    return routes


def _ref_feed_link_index(project):
    out = {}
    for s in project.sheets:
        for e in s.elements:
            if e.symbol_id not in FEED_SYMBOLS:
                continue
            hit = linked_wire(project, s, e)
            if hit is not None:
                out.setdefault(hit[1].id, []).append((s, e))
    return out


def _ref_score(grid, boxes, own) -> float:
    s = 0.0
    for b in boxes:
        for ob, kind, owner in grid.near(b):
            if kind == "line":
                if textlayout.segment_hits_box((ob[0], ob[1]), (ob[2], ob[3]), b):
                    s += textlayout.WEIGHT["line"]
            elif owner != own and textlayout.boxes_overlap(b, ob):
                s += textlayout.WEIGHT["text"]
    return s


def _ref_chain_score_cross(p, s, lib, lay, wires) -> int:
    """Křížení v `_chain_layout_score` před zrychlením (obálka značky pro každý úsek znovu)."""
    from envocad.generator.chain import _segments_cross
    from envocad.model.textlayout import segment_hits_box, symbol_box
    segs = {wid: [(a, b) for a, b in pairwise(pts) if a != b] for wid, pts in lay.routes.items()}
    ends = {w.id: {w.a.element_id, w.b.element_id} for w in s.wires}
    cross = 0
    for wid in wires & set(segs):
        for a, b in segs[wid]:
            for oid, other in segs.items():
                if oid == wid:
                    continue
                for c, d in other:
                    if _segments_cross((a, b), (c, d)):
                        cross += 1
            for e in s.elements:
                if e.id in ends.get(wid, ()):
                    continue
                x1, y1, x2, y2 = symbol_box(e, element_symbol(p, e, lib))
                if segment_hits_box(a, b, (x1 + 0.5, y1 + 0.5, x2 - 0.5, y2 - 0.5)):
                    cross += 1
    return cross


# ---- trasování ------------------------------------------------------------------------------------------------
def _random_segs(rng: random.Random, n: int) -> list:
    out = []
    for _ in range(n):
        x, y = rng.randrange(0, 40) * 2.5, rng.randrange(0, 40) * 2.5
        d = rng.randrange(-12, 13) * 2.5
        out.append(((x, y), (x + d, y)) if rng.random() < 0.5 else ((x, y), (x, y + d)))
    return out


def test_route_score_matches_full_scan():
    """Obálkový filtr `route_score` vynechá jen úseky bez souběhu a křížení – výsledek bit po bitu stejný."""
    rng = random.Random(7)
    for _ in range(300):
        others = [_random_segs(rng, rng.randrange(0, 5)) for _ in range(rng.randrange(0, 8))]
        pts = [(0.0, 0.0)]
        for _ in range(rng.randrange(2, 7)):
            x, y = pts[-1]
            d = rng.randrange(-16, 17) * 2.5
            pts.append((x + d, y) if len(pts) % 2 else (x, y + d))
        assert routing.route_score(pts, others) == _ref_route_score(pts, others)


def test_route_sheet_matches_reference(projects, lib):
    """`route_sheet` (obálky položených vodičů jednou, prvky přes mapu) = původní průchod všech listů."""
    for p in projects.values():
        for s in p.sheets:
            assert routing.route_sheet(p, s, lib) == _ref_route_sheet(p, s, lib), s.name


def test_best_route_public_signature(projects, lib):
    """`best_route` (editor: `others` = [(konce, úseky)]) i s mapou prvků vrací totéž co původní."""
    p = projects["firma_3"]
    s = p.sheets[0]
    placed = []
    els = routing.element_map(s)
    for w in s.wires:
        ref = _ref_best_route(p, s, lib, w, placed)
        assert routing.best_route(p, s, lib, w, placed) == ref
        assert routing.best_route(p, s, lib, w, placed, els) == ref
        placed.append((routing.ends(w), routing._inner_segments(ref)))


def test_element_map_and_wire_route_els(projects, lib):
    s = Sheet()
    a, b = Element("fve.earth", 0, 0), Element("fve.earth", 50, 0)
    dup = Element("fve.earth", 99, 99, id=a.id)          # duplicitní id: první jako `Sheet.element`
    s.elements = [a, b, dup]
    m = routing.element_map(s)
    assert m[a.id] is a and m[b.id] is b and len(m) == 2
    p = projects["rd_2"]
    s = p.sheets[0]
    els = routing.element_map(s)
    for w in s.wires:
        assert routing.wire_route(p, s, lib, w, els=els) == routing.wire_route(p, s, lib, w)
    w = Wire(WireEnd("neni", "1"), WireEnd(s.elements[0].id, "1"))
    with pytest.raises(KeyError):
        routing.wire_route(p, s, lib, w, els=els)


# ---- vazby přívodů, listy prvků -------------------------------------------------------------------------------
def test_feed_link_index_matches_linked_wire(projects):
    for p in projects.values():
        assert feed_link_index(p) == _ref_feed_link_index(p)


def test_feed_link_index_manual_wire_id():
    """Ruční `wire_id` má přednost; neexistující `wire_id` → vazba podle portu bloku (jako `linked_wire`)."""
    p = Project()
    jps = p.sheets[0]
    blk = Element("fve.switchboard", 0, 0, attrs={"ref": "R1"})
    other = Element("fve.earth", 50, 0)
    jps.elements += [blk, other]
    w1 = Wire(WireEnd(other.id, "PE"), WireEnd(blk.id, "X1"))
    w2 = Wire(WireEnd(other.id, "PE"), WireEnd(blk.id, "X2"))
    jps.wires += [w1, w2]
    sb = p.create_switchboard_sheet(blk)
    f1 = Element("sb.feed", 0, 0, attrs={"ref": "X1", "dir": "in"})
    f2 = Element("sb.feed", 0, 20, attrs={"ref": "X1", "dir": "in", "wire_id": w2.id})
    f3 = Element("sb.feed", 0, 40, attrs={"ref": "X2", "dir": "in", "wire_id": "chybi"})
    f4 = Element("sb.feed", 0, 60, attrs={"ref": "X9", "dir": "in"})
    sb.elements += [f1, f2, f3, f4]
    idx = feed_link_index(p)
    assert idx == _ref_feed_link_index(p)
    assert [e for _s, e in idx[w1.id]] == [f1] and [e for _s, e in idx[w2.id]] == [f2, f3]


def test_sheet_of_element_first_sheet():
    p = Project()
    e = Element("fve.earth")
    s2 = Sheet(name="2")
    p.sheets.append(s2)
    s2.elements.append(e)
    assert p.sheet_of_element(e.id) is s2
    p.sheets[0].elements.append(Element("fve.earth", id=e.id))
    assert p.sheet_of_element(e.id) is p.sheets[0]
    assert p.sheet_of_element("neni") is None


# ---- rozmístění textů -----------------------------------------------------------------------------------------
def test_iter_candidates_same_as_lists(projects, lib):
    p = projects["firma_3"]
    s = p.sheets[0]
    routes = routing.route_sheet(p, s, lib)
    for w in s.wires:
        pts = routes[w.id]
        assert list(textlayout._iter_candidates(pts, bool(w.points), "W1", "→ X")) == \
            textlayout._candidates(pts, bool(w.points), "W1", "→ X")
    for e in s.elements:
        sym = element_symbol(p, e, lib)
        texts = textlayout.element_label_texts(p, s, e, sym, "")
        assert list(textlayout._iter_el_candidates(e, sym, texts)) == textlayout._el_candidates(e, sym, texts)


def test_score_matches_near_scan(projects, lib):
    """`_score` (vlastní průchod mřížkou a obálkový filtr čar) = průchod `_Grid.near`."""
    p = projects["split_4x8"]
    rng = random.Random(3)
    for s in p.sheets[:3]:
        grid = textlayout._Grid()
        for e in s.elements:
            sym = element_symbol(p, e, lib)
            for a, b in textlayout.symbol_segments(e, sym):
                textlayout._add_line(grid, a, b, e.id)
            for b in textlayout.symbol_text_boxes(e, sym):
                grid.add(b, "text", e.id)
        for wid, pts in routing.route_sheet(p, s, lib).items():
            for a, b in pairwise(pts):
                textlayout._add_line(grid, a, b, wid)
        for _ in range(400):
            x, y = rng.uniform(0, 600), rng.uniform(0, 400)
            boxes = [(x, y, x + rng.uniform(1, 30), y + rng.uniform(1, 6)) for _ in range(rng.randrange(1, 3))]
            own = rng.choice(s.elements).id
            assert textlayout._score(grid, boxes, own) == _ref_score(grid, boxes, own)


def test_compute_layout_auto_false_first_candidate(projects, lib):
    p = projects["firma_3"]
    s = p.sheets[0]
    lay = textlayout.compute_layout(p, s, lib, auto=False)
    for e in s.elements:
        if e.id in lay.elements:
            sym = element_symbol(p, e, lib)
            texts = textlayout.element_label_texts(p, s, e, sym)
            assert lay.elements[e.id] == textlayout._el_candidates(e, sym, texts)[0]


def _same_layout(a, b) -> bool:
    return (a.elements, a.wires, a.routes) == (b.elements, b.wires, b.routes) and a.mirrors.keys() == b.mirrors.keys()


def test_layout_cache(projects, lib):
    p = projects["split_4x8"]
    s = p.sheets[1]
    assert textlayout.compute_layout(p, s, lib) is not textlayout.compute_layout(p, s, lib)   # bez bloku nic
    with textlayout.layout_cache():
        first = textlayout.compute_layout(p, s, lib)
        assert textlayout.compute_layout(p, s, lib) is first
        with textlayout.layout_cache():                       # vnořený blok sdílí mezipaměť
            assert textlayout.compute_layout(p, s, lib) is first
        assert textlayout.compute_layout(p, s, lib, auto=False) is not first     # jiné parametry mimo mezipaměť
        e = s.elements[0]
        e.x += 2.5                                            # změna listu → nový výpočet
        moved = textlayout.compute_layout(p, s, lib)
        assert moved is not first and _same_layout(moved, textlayout._compute_layout(p, s, lib))
        e.x -= 2.5
        assert textlayout.compute_layout(p, s, lib) is first
        other = p.sheets[2]                                   # změna jiného listu (křížové odkazy) → nový výpočet
        other.width += 1.0
        assert textlayout.compute_layout(p, s, lib) is not first
        other.width -= 1.0
        e.attrs["seznam"] = ["nehashovatelné"]                # nehashovatelný atribut → bez mezipaměti, bez chyby
        try:
            assert _same_layout(textlayout.compute_layout(p, s, lib), textlayout._compute_layout(p, s, lib))
        finally:
            del e.attrs["seznam"]
    assert textlayout._LAYOUT_CACHE is None


# ---- zvětšení listů --------------------------------------------------------------------------------------------
def test_grow_sheet_long_skips_boxes_without_long_paper(monkeypatch, lib):
    p = Project()
    s = p.sheets[0]
    s.paper, s.width, s.height = "A2", 594.0, 420.0 + 1      # výška bez prodlouženého formátu

    def boom(*_a, **_k):
        raise AssertionError("obálky se nemají počítat")
    monkeypatch.setattr(textlayout, "sheet_content_boxes", boom)
    assert frame.grow_sheet_long(p, s, lib) is False


def test_grow_sheet_given_boxes(monkeypatch, lib):
    """Předané obálky se použijí místo výpočtu (`layout._grow_switchboards` je počítá jednou pro obě funkce)."""
    p = Project()
    s = p.sheets[0]
    s.paper, s.width, s.height = "A3", 420.0, 297.0
    monkeypatch.setattr(textlayout, "sheet_content_boxes", lambda *_a, **_k: pytest.fail("výpočet obálek"))
    wide = [(30.0, 30.0, 800.0, 200.0)]                       # přetéká jen vpravo → A4×5 (výška 297 mm)
    assert frame.grow_sheet_long(p, s, lib, wide) is True and s.paper == "A4×5"
    s.paper, s.width, s.height = "A3", 420.0, 297.0
    assert frame.grow_sheet_to_content(p, s, lib, [(30.0, 30.0, 100.0, 100.0)]) is False
    # přetéká vpravo, nad popisovým polem A2 → A2 bez posunu
    assert frame.grow_sheet_to_content(p, s, lib, [(30.0, 150.0, 500.0, 250.0)]) is True and s.paper == "A2"


def test_grow_switchboards_same_as_separate_calls(ac_builtin, lib):
    """`_grow_switchboards` se sdílenými obálkami = `grow_sheet_long` nebo `grow_sheet_to_content` zvlášť."""
    from envocad.generator import context
    from envocad.generator.layout import _grow_switchboards
    spec = {"inverters": [{"ref": "T1", **INV, "strings": [20] * 9}]}
    a, b = build_project(spec), build_project(spec)
    for p in (a, b):
        for sh in p.sheets:
            if sh.is_switchboard:
                sh.paper, sh.width, sh.height = "A4", 297.0, 210.0
    context._BUILD_LIB = lib
    try:
        _grow_switchboards(a, [sh for sh in a.sheets if sh.is_switchboard])
    finally:
        context._BUILD_LIB = None
    for sh in (sh for sh in b.sheets if sh.is_switchboard):
        frame.grow_sheet_long(b, sh, lib) or frame.grow_sheet_to_content(b, sh, lib)
    assert [(s.paper, s.width, s.height) for s in a.sheets] == [(s.paper, s.width, s.height) for s in b.sheets]


# ---- hodnocení rozložení řetězce -------------------------------------------------------------------------------
def test_chain_layout_score_cross_matches_reference(lib):
    """Křížení v `_chain_layout_score` (obálky značek jednou, filtr úseků mimo značku) = původní průchod."""
    from envocad.generator import context
    from envocad.generator.chain import _chain_layout_score
    spec = {"inverters": [{"ref": f"T{i}", **INV, "strings": [20, 20]} for i in (1, 2, 3)],
            "chain": {"hr": {"main_in": 250}, "re": {"main_in": 250}, "hds": {"in_": 315}}}
    p = build_project(spec)
    context._BUILD_LIB = lib
    try:
        for s in p.sheets:
            if s.is_switchboard:
                continue
            lay = textlayout.compute_layout(p, s, lib)
            ctx = SimpleNamespace(project=p, sheet=s)
            for wires in ({w.id for w in s.wires}, {w.id for w in s.wires[::2]}, set()):
                got = _chain_layout_score(ctx, wires)
                assert got[0] - _owner_cross(p, s, lib, lay, wires) == _ref_chain_score_cross(p, s, lib, lay, wires)
    finally:
        context._BUILD_LIB = None


def _owner_cross(p, s, lib, lay, wires) -> int:
    """Druhá a třetí část křížení `_chain_layout_score` (beze změny): cizí vodiče a značky přes značky řetězce."""
    from envocad.model.textlayout import segment_hits_box, symbol_box
    segs = {wid: [(a, b) for a, b in pairwise(pts) if a != b] for wid, pts in lay.routes.items()}
    ends = {w.id: {w.a.element_id, w.b.element_id} for w in s.wires}
    owners = {w.a.element_id for w in s.wires if w.id in wires} | {w.b.element_id for w in s.wires if w.id in wires}
    sym_boxes = {e.id: symbol_box(e, element_symbol(p, e, lib)) for e in s.elements}
    cross = 0
    for wid, sg in segs.items():
        if wid in wires:
            continue
        for eid in owners & set(sym_boxes):
            if eid in ends.get(wid, ()):
                continue
            x1, y1, x2, y2 = sym_boxes[eid]
            cross += sum(1 for a, b in sg if segment_hits_box(a, b, (x1 + 0.5, y1 + 0.5, x2 - 0.5, y2 - 0.5)))
    for a in owners & set(sym_boxes):
        ax = sym_boxes[a]
        for b, bx in sym_boxes.items():
            if b != a and b not in owners and ax[0] < bx[2] - 0.5 and bx[0] < ax[2] - 0.5 \
                    and ax[1] < bx[3] - 0.5 and bx[1] < ax[3] - 0.5:
                cross += 1
    return cross


# ---- knihovna --------------------------------------------------------------------------------------------------
def test_store_rel(tmp_path):
    root = tmp_path / "lib"
    for f in (root / "a.json", root / "fve" / "x.json", root / "macros" / "m" / "y.json"):
        assert _rel(f, root) == str(f.relative_to(root))
    with pytest.raises(ValueError):                           # jen řetězcový prefix → `relative_to` (chyba)
        _rel(Path("/jinde/a.json"), Path("/jin"))
