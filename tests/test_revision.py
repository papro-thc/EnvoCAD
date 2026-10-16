"""Revize ve výkresu: značky z porovnání, uzavření (měkký zámek), revize listu, geometrie (bez Qt)."""
import math
from itertools import pairwise

import pytest

from envocad.generate import build_project
from envocad.library.store import LibraryStore
from envocad.model.checks import check_project
from envocad.model.diff import MOVE_DETAIL, Change, diff_projects
from envocad.model.frame import qr_text, title_rows
from envocad.model.project import Element, Project, Revision, RevisionMark, Sheet
from envocad.model.revision import (
    MARK_MOVES,
    apply_changes,
    changed_after_close,
    close_revision,
    marks_from_changes,
    open_revision,
    restore_revisions_state,
    revision_geometry,
    revisions_state,
    sheet_revision,
    triangle,
)
from envocad.model.symbol import GRID

SPEC = {"name": "Rev", "inverters": [{"ref": "T1", "p_ac": 25, "strings": [20, 20]}],
        "dc": {"route_boxes": 0, "tech_box": False, "disconnect": True}, "ac": {"distribution": "terminals"}}


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _pair(tmp_path):
    p1 = build_project(SPEC)
    p1.save(tmp_path / "r0.ecp")
    return p1, Project.load(tmp_path / "r0.ecp")


def _revision_label(rows) -> str:
    return next(v for row in rows for k, v in row if k == "Revize")


# ---- marks_from_changes ------------------------------------------------------------------------------------
def test_marks_from_changes_rules():
    ch = [
        Change("změněno", "S", "F1", "prvek", "in_: 32 → 40", "e1", sheet_id="s1"),
        Change("změněno", "S", "X1", "můstky", "– → 1-2", "e1", sheet_id="s1"),          # stejné místo → 1 značka
        Change("změněno", "S", "F2", "prvek", MOVE_DETAIL, "e2", sheet_id="s1"),         # jen posun → bez značky
        Change("odebráno", "S", "F3", "prvek", "x", sheet_id="s1", x=10.0, y=20.0),
        Change("odebráno", "S", "W1", "vodič", "", is_wire=True, sheet_id="s1", x=30.0, y=20.0),
        Change("změněno", "S", "", "skříň", "ip", sheet_id="s1"),
        Change("změněno", "S", "", "list", "přejmenován", sheet_id="s1"),                # list + skříň → 1 značka listu
        Change("změněno", "", "W1", "kabel", "typ"),                                     # kabel → bez značky
        Change("přidáno", "", "=AC", "struktura", "AC"),
        Change("odebráno", "Old", "", "list", "list Old odstraněn"),
        Change("přidáno", "N", "", "list", "nový list N", sheet_id="s2"),
        Change("přidáno", "N", "F9", "prvek", "x", "e9", sheet_id="s2"),                 # nový list → jen značka listu
    ]
    marks = marks_from_changes(ch)
    by = {(m.sheet_id, m.target_id, m.x): m for m in marks}
    assert len(marks) == 5
    m1 = by[("s1", "e1", None)]
    assert "in_" in m1.text and "můstky" in m1.text and m1.kind == "změněno"
    assert ("s1", "e2", None) not in by and not MARK_MOVES
    assert by[("s1", "", 10.0)].kind == "odebráno" and by[("s1", "", 10.0)].y == 20.0
    assert by[("s1", "", 30.0)].is_wire
    assert by[("s1", "", None)].x is None
    assert ("s2", "", None) in by and ("s2", "e9", None) not in by


def test_marks_merge_kinds():
    ch = [Change("přidáno", "S", "X1", "můstky", "a", "e1", sheet_id="s"),
          Change("změněno", "S", "X1", "prvek", "b", "e1", sheet_id="s")]
    (m,) = marks_from_changes(ch)
    assert m.kind == "změněno" and m.text.count(";") == 1


# ---- open / apply / close ----------------------------------------------------------------------------------
def test_open_apply_close(tmp_path):
    p1, p2 = _pair(tmp_path)
    s0 = p2.sheets[0]
    f = s0.elements[0]
    f.attrs["type"] = "NOVÝ"
    ch = diff_projects(p1, p2)
    rev = open_revision(p2, "B", "16.10.2026", "PR")
    assert p2.revisions[-1] is rev and not rev.closed
    assert open_revision(p2, "", "", "") is rev                 # otevřená se použije znovu
    apply_changes(p2, rev, ch)
    marks = list(rev.marks)
    assert any(m.target_id == f.id for m in marks) and p2.meta["revision"] == "B"
    apply_changes(p2, rev, ch)                                    # idempotentní
    assert [m.to_dict() for m in rev.marks] == [m.to_dict() for m in marks]
    # uzavření jednoho listu: jeho značky se dalším porovnáním nemění
    close_revision(p2, rev, [s0.id])
    assert set(rev.fingerprints) == {s0.id} and not rev.closed
    apply_changes(p2, rev, [])
    assert [m.to_dict() for m in rev.marks] == [m.to_dict() for m in marks if m.sheet_id == s0.id]
    close_revision(p2, rev)
    assert rev.closed and set(rev.fingerprints) == {s.id for s in p2.sheets}
    with pytest.raises(ValueError):
        apply_changes(p2, rev, ch)
    nxt = open_revision(p2, "", "", "")                           # po uzavření nová revize
    assert nxt is not rev and nxt.label == "C"
    # uložení a načtení zachová revize
    p2.save(tmp_path / "r1.ecp")
    p3 = Project.load(tmp_path / "r1.ecp")
    assert [r.to_dict() for r in p3.revisions] == [r.to_dict() for r in p2.revisions]


def test_revisions_state_roundtrip():
    p = Project()
    before = revisions_state(p)
    rev = open_revision(p, "A")
    apply_changes(p, rev, [Change("změněno", "S", "", "list", "x", sheet_id=p.sheets[0].id)])
    after = revisions_state(p)
    restore_revisions_state(p, before)
    assert p.revisions == [] and "revision" not in p.meta
    restore_revisions_state(p, after)
    restore_revisions_state(p, before)
    restore_revisions_state(p, after)
    assert p.revisions[0].label == "A" and p.meta["revision"] == "A"
    assert p.revisions[0] is not after[0][0]                      # stav se kopíruje


# ---- sheet_revision, popisové pole -------------------------------------------------------------------------
def test_sheet_revision_and_title_rows():
    p = Project(meta={"revision": "X"})
    s1, s2 = p.sheets[0], Sheet(name="Druhý")
    p.sheets.append(s2)
    assert sheet_revision(p, s1) is None
    assert _revision_label(title_rows(p, s1)) == "X" and "rev. X" in qr_text(p, s1)
    p.revisions = [Revision("A", closed=True), Revision("B", closed=True), Revision("C")]
    assert sheet_revision(p, s1) is None                          # bez značek (migrovaný projekt) → meta
    p.revisions[2].marks.append(RevisionMark(s1.id, "e1"))
    assert sheet_revision(p, s1).label == "C"
    assert sheet_revision(p, s2).label == "B"                     # stav před první revizí se značkami
    assert _revision_label(title_rows(p, s1)) == "C" and _revision_label(title_rows(p, s2)) == "B"
    assert "rev. C" in qr_text(p, s1) and "rev. B" in qr_text(p, s2)
    p.revisions[0].marks.append(RevisionMark(s2.id))
    assert sheet_revision(p, s2).label == "A"


# ---- měkký zámek -------------------------------------------------------------------------------------------
def test_changed_after_close_and_check(tmp_path, lib):
    _, p = _pair(tmp_path)
    s = p.sheets[0]
    rev = open_revision(p, "B")
    close_revision(p, rev)
    assert changed_after_close(p) == []
    assert not [f for f in check_project(p, lib) if f.code == "rev_closed_changed"]
    orig = dict(s.elements[0].attrs)
    s.elements[0].attrs["type"] = "jiný"
    assert changed_after_close(p) == [(s, rev)]
    found = [f for f in check_project(p, lib) if f.code == "rev_closed_changed"]
    assert len(found) == 1 and found[0].sheet_id == s.id and found[0].severity == "varování"
    assert "revize B" in found[0].text
    # porovnání do nové revize varování odstraní
    nxt = open_revision(p, "C")
    apply_changes(p, nxt, [Change("změněno", s.name, "", "prvek", "type", s.elements[0].id, sheet_id=s.id)])
    assert changed_after_close(p) == []
    # vrácení změny = stejný otisk → bez varování i bez nové revize
    p.revisions.remove(nxt)
    assert changed_after_close(p) == [(s, rev)]
    s.elements[0].attrs = orig
    assert changed_after_close(p) == []


# ---- geometrie ---------------------------------------------------------------------------------------------
def test_triangle():
    pts, (tx, ty, text, h, align) = triangle(10.0, 20.0, "B")
    assert len(pts) == 3
    sides = [math.dist(pts[i], pts[(i + 1) % 3]) for i in range(3)]
    assert all(abs(x - 6.0) < 1e-9 for x in sides)                 # rovnostranný, min. strana 6 mm
    assert pts[2][1] > pts[0][1] == pts[1][1]                      # vrchol nahoru
    cx, cy = sum(p[0] for p in pts) / 3, sum(p[1] for p in pts) / 3
    assert abs(cx - 10) < 1e-9 and abs(cy - 20) < 1e-9
    assert (tx, text, h, align) == (10.0, "B", 2.5, "center") and pts[0][1] < ty < pts[2][1]
    long_pts, _ = triangle(0, 0, "10a")
    assert math.dist(long_pts[0], long_pts[1]) == pytest.approx(1.6 * 3 + 3)


def test_revision_geometry_positions(lib):
    from envocad.model.project import element_symbol
    from envocad.model.textlayout import symbol_box
    p = build_project(SPEC)
    s = p.sheets[0]
    e = s.elements[0]
    w = s.wires[0]
    rev = Revision("B", marks=[
        RevisionMark(s.id, e.id),
        RevisionMark(s.id, w.id, is_wire=True),
        RevisionMark(s.id, "", kind="odebráno", x=50.0, y=60.0),
        RevisionMark(s.id),                                         # značka listu – nekreslí se
        RevisionMark(s.id, "neexistuje"),                           # smazaný prvek – nekreslí se
        RevisionMark("jiny_list", e.id),
    ])
    p.revisions.append(rev)
    g = revision_geometry(p, s, lib)
    assert len(g.polylines) == 3 and len(g.texts) == 3 and all(t[2] == "B" for t in g.texts)
    centers = [(sum(x for x, _ in pts) / 3, sum(y for _, y in pts) / 3) for pts in g.polylines]
    # prvek: pravý horní roh obálky + 2,5 mm, na mřížce
    _x1, _y1, x2, y2 = symbol_box(e, element_symbol(p, e, lib))
    ex, ey = centers[0]
    assert ex >= x2 + GRID - 1e-6 and ey >= y2 + GRID - 1e-6
    assert abs(ex / GRID - round(ex / GRID)) < 1e-6 and abs(ey / GRID - round(ey / GRID)) < 1e-6
    # vodič: u nejdelšího úseku trasy
    from envocad.model.routing import route_sheet
    routes = route_sheet(p, s, lib)
    g2 = revision_geometry(p, s, lib, routes)
    assert g2.polylines == g.polylines
    pts = routes[w.id]
    (ax, ay), (bx, by) = max(pairwise(pts), key=lambda q: math.dist(*q))
    wx, wy = centers[1]
    assert min(ax, bx) - 5 <= wx <= max(ax, bx) + 5 and min(ay, by) - 5 <= wy <= max(ay, by) + 5
    # odebraný: uložená poloha
    assert centers[2] == pytest.approx((50.0, 60.0))
    # explicitní revize / bez revize
    assert revision_geometry(p, s, lib, revision=Revision("C")).polylines == []
    assert revision_geometry(Project(), Project().sheets[0], lib).polylines == []


def test_compare_flow_end_to_end(tmp_path, lib):
    """Postup jako `compare_revision` v GUI: diff → open → apply → značky v geometrii i v popisovém poli."""
    p1, p2 = _pair(tmp_path)
    s = p2.sheets[0]
    s.elements.append(Element("fve.meter", 200, 100, attrs={"ref": "P1"}))
    gone = s.elements[0]
    s.remove_element(gone.id)
    rev = open_revision(p2, "B", "16.10.2026", "PR")
    apply_changes(p2, rev, diff_projects(p1, p2, lib))
    g = revision_geometry(p2, s, lib)
    centers = [(sum(x for x, _ in pts) / 3, sum(y for _, y in pts) / 3) for pts in g.polylines]
    assert any(c == pytest.approx((gone.x, gone.y)) for c in centers)    # značka odebraného prvku
    assert _revision_label(title_rows(p2, s)) == "B"
    other = p2.sheets[1]
    assert _revision_label(title_rows(p2, other)) == "B"           # jediná revize = první → i nezměněný list
