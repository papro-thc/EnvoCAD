"""Porovnání revizí (bez Qt)."""

import pytest

from envocad.generate import build_project
from envocad.model.diff import change_list_text, diff_projects, summary
from envocad.model.project import Element, Project

pytestmark = pytest.mark.usefixtures("ac_builtin")   # AC listy vestavěným kódem (standard `ac_builtin`)


def test_diff_projects(tmp_path):
    spec = {"name": "Diff", "inverters": [{"ref": "T1", "p_ac": 25, "strings": [20, 20]}],
            "dc": {"route_boxes": 0, "tech_box": False, "disconnect": True}, "ac": {"distribution": "terminals"}}
    p1 = build_project(spec)
    p1.save(tmp_path / "r0.ecp")
    p2 = Project.load(tmp_path / "r0.ecp")
    assert diff_projects(p1, p2) == []
    s = p2.sheets[0]
    f1 = next(e for e in s.elements if e.symbol_id == "fve.dc_disconnect")
    f1.attrs["in_"] = "40"
    s.elements.append(Element("fve.meter", 200, 100, attrs={"ref": "P1"}))
    w = s.wires[0]
    w.attrs["cross"] = "10"
    w.conductors = ["DC+", "DC-"]
    removed = s.wires.pop()  # kabel do HDS
    p2.set_bridges("X2", [["1", "6"]], p2.sheets[1])
    from envocad.model.project import sync_cables
    sync_cables(p2)
    ch = diff_projects(p1, p2)
    kinds = {(c.kind, c.what, c.ref) for c in ch}
    assert ("změněno", "prvek", f1.ref) in kinds
    assert ("přidáno", "prvek", "P1") in kinds
    assert ("změněno", "vodič", w.attrs["ref"]) in kinds
    assert ("odebráno", "vodič", removed.attrs["ref"]) in kinds
    assert ("změněno", "můstky", "X2") in kinds
    assert any(c.what == "kabel" and c.kind == "odebráno" for c in ch) or any(c.what == "kabel" for c in ch)
    assert "in_: 32 → 40" in next(c.detail for c in ch if c.ref == f1.ref and c.what == "prvek")
    txt = change_list_text(ch, "1", "16.10.2026", "PR")
    assert txt.startswith("1 | 16.10.2026 | ") and txt.count("\n") == len(ch) - 1
    assert "přidáno" in summary(ch)


SPEC = {"name": "Diff", "inverters": [{"ref": "T1", "p_ac": 25, "strings": [20, 20]}],
        "dc": {"route_boxes": 0, "tech_box": False, "disconnect": True}, "ac": {"distribution": "terminals"}}


def _pair(tmp_path):
    p1 = build_project(SPEC)
    p1.save(tmp_path / "r0.ecp")
    return p1, Project.load(tmp_path / "r0.ecp")


def test_diff_positions_and_sheet_ids(tmp_path):
    from envocad.library.store import LibraryStore
    from envocad.model.diff import removed_wire_pos
    p1, p2 = _pair(tmp_path)
    s = p2.sheets[0]
    gone = s.elements[-1]
    removed_wires = s.remove_element(gone.id)
    w_old = next(w for w in p1.sheets[0].wires if w.id not in {x.id for x in removed_wires})
    s.wires = [w for w in s.wires if w.id != w_old.id]
    ch = diff_projects(p1, p2)
    el = next(c for c in ch if c.what == "prvek" and c.kind == "odebráno")
    assert el.sheet_id == s.id and (el.x, el.y) == (gone.x, gone.y)
    wc = next(c for c in ch if c.what == "vodič" and c.kind == "odebráno" and c.ref == w_old.attrs.get("ref", ""))
    assert wc.is_wire and wc.sheet_id == s.id and wc.x is not None and wc.y is not None
    # bez lomů = střed mezi konci; s knihovnou střed mezi porty
    lib = LibraryStore()
    pos = removed_wire_pos(p1, p1.sheets[0], w_old, lib)
    ch2 = diff_projects(p1, p2, lib)
    wc2 = next(c for c in ch2 if c.what == "vodič" and c.kind == "odebráno" and c.ref == w_old.attrs.get("ref", ""))
    assert (wc2.x, wc2.y) == pos
    # změny na listech nesou sheet_id, kabely ne
    assert all(c.sheet_id for c in ch if c.what in ("prvek", "vodič", "můstky"))
    assert all(not c.sheet_id for c in ch if c.what == "kabel")


def test_removed_wire_pos_bends():
    from envocad.model.diff import removed_wire_pos
    from envocad.model.project import Sheet, Wire, WireEnd
    p = Project()
    s = p.sheets[0]
    w = Wire(WireEnd("a", "1"), WireEnd("b", "1"), points=[(0, 0), (10, 0), (10, 10)])
    assert removed_wire_pos(p, s, w) == (10, 0)
    s2 = Sheet()
    s2.elements = [Element("fve.meter", 0, 0, id="a"), Element("fve.meter", 20, 10, id="b")]
    w2 = Wire(WireEnd("a", "1"), WireEnd("b", "1"))
    assert removed_wire_pos(p, s2, w2) == (10, 5)


def test_diff_bridges_target_and_move_only(tmp_path):
    from envocad.model import multipole as mp
    from envocad.model.diff import MOVE_DETAIL
    p1, p2 = _pair(tmp_path)
    sb = p2.sheets[1]
    strip = next(e for e in sb.elements if mp.is_terminal_block(e) and e.ref == "X2")
    p2.set_bridges("X2", [["1", "6"]], sb)
    moved = p2.sheets[0].elements[0]
    moved.x += 10
    ch = diff_projects(p1, p2)
    br = next(c for c in ch if c.what == "můstky")
    assert br.target_id == strip.id and br.sheet_id == sb.id
    mv = next(c for c in ch if c.target_id == moved.id)
    assert mv.detail == MOVE_DETAIL


def test_diff_sheet_designation_and_structures(tmp_path):
    from envocad.model.project import StructureId
    p1, p2 = _pair(tmp_path)
    s = p2.sheets[0]
    s.func, s.loc = "AC", "RS1"
    p2.structures.append(StructureId("=", "AC", "Střídavá část"))
    ch = diff_projects(p1, p2)
    lc = next(c for c in ch if c.what == "list")
    assert lc.kind == "změněno" and lc.sheet_id == s.id and lc.target_id == ""
    assert "funkce: – → =AC" in lc.detail and "umístění: – → +RS1" in lc.detail
    st = next(c for c in ch if c.what == "struktura")
    assert (st.kind, st.ref, st.sheet_id) == ("přidáno", "=AC", "")
    p1.structures.append(StructureId("=", "AC", "jiný popis"))
    st = next(c for c in diff_projects(p1, p2) if c.what == "struktura")
    assert st.kind == "změněno" and "jiný popis" in st.detail


def test_sheet_fingerprint(tmp_path):
    from envocad.model.diff import sheet_fingerprint
    p1, p2 = _pair(tmp_path)
    for a, b in zip(p1.sheets, p2.sheets, strict=True):
        assert sheet_fingerprint(a) == sheet_fingerprint(b)
    s = p2.sheets[0]
    fp = sheet_fingerprint(s)
    s.elements.reverse()
    assert sheet_fingerprint(s) == fp            # pořadí nevadí
    s.elements[0].attrs["sheet"] = "x"             # technický atribut nevadí
    assert sheet_fingerprint(s) == fp
    s.wires[0].points = [(1.0, 2.0)]               # lomy diff neporovnává
    assert sheet_fingerprint(s) == fp
    s.loc = "RS1"
    assert sheet_fingerprint(s) != fp
    s.loc = ""
    s.elements[0].x += 2.5                         # posun ani otočení otisk nemění (MARK_MOVES = False)
    s.elements[0].rotation = (s.elements[0].rotation + 90) % 360
    assert sheet_fingerprint(s) == fp
    s.elements[0].attrs["desc"] = "jiný popis"
    assert sheet_fingerprint(s) != fp
