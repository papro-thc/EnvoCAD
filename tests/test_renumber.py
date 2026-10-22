"""Přečíslování označení (model.renumber) – bez Qt."""
import pytest

from envocad.library.store import LibraryStore
from envocad.model import renumber
from envocad.model.checks import check_project
from envocad.model.project import Cable, Element, Project, Sheet, Wire, WireEnd, apply_text_changes


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _wire(a, pa, b, pb, ref, **attrs):
    return Wire(WireEnd(a.id, pa), WireEnd(b.id, pb), attrs={"ref": ref, **attrs})


def _refs(sheet):
    return {e.id: e.ref for e in sheet.elements}


def test_fix_fills_empty_and_duplicates_keeps_rest(lib):
    p = Project()
    s = p.sheets[0]
    q1 = Element("fve.breaker_mcb", 50, 100, attrs={"ref": "F1"})
    q2 = Element("fve.breaker_mcb", 100, 100, attrs={"ref": "F1"})     # duplicita – dostane F3 (F2 obsazené)
    q3 = Element("fve.breaker_mcb", 150, 100, attrs={"ref": "F2"})
    q4 = Element("fve.breaker_mcb", 200, 100, attrs={"ref": ""})       # bez označení → další volné
    custom = Element("fve.breaker_mcb", 250, 100, attrs={"ref": "F1.5"})   # firemní – nemění se
    s.elements += [q1, q2, q3, q4, custom]
    ch = renumber.plan(p, lib, renumber.FIX)
    apply_text_changes(p, ch)
    assert _refs(s) == {q1.id: "F1", q2.id: "F3", q3.id: "F2", q4.id: "F4", custom.id: "F1.5"}
    assert renumber.plan(p, lib, renumber.FIX) == []          # podruhé nic
    assert not [f for f in check_project(p, lib, standard_paper="A4") if f.code == "dup_ref"]


def test_all_numbers_by_position_columns_then_rows(lib):
    p = Project()
    s = p.sheets[0]
    a = Element("fve.breaker_mcb", 200, 100, attrs={"ref": "F1"})
    b = Element("fve.breaker_mcb", 50, 50, attrs={"ref": "F2"})
    c = Element("fve.breaker_mcb", 50, 150, attrs={"ref": "F3"})       # stejný sloupec jako b, výš → dřív
    s.elements += [a, b, c]
    apply_text_changes(p, renumber.plan(p, lib, renumber.ALL))
    assert (c.ref, b.ref, a.ref) == ("F1", "F2", "F3")


def test_undo_restores(lib):
    p = Project()
    s = p.sheets[0]
    a = Element("fve.breaker_mcb", 200, 100, attrs={"ref": "F7"})
    s.elements.append(a)
    ch = renumber.plan(p, lib, renumber.ALL)
    apply_text_changes(p, ch)
    assert a.ref == "F1"
    apply_text_changes(p, ch, undo=True)
    assert a.ref == "F7"


def test_contacts_follow_coil(lib):
    p = Project()
    s = p.sheets[0]
    coil = Element("ctl.coil", 100, 100, attrs={"ref": "K5"})
    no = Element("ctl.contact_no", 150, 100, attrs={"ref": "K5"})
    other = Element("ctl.coil", 50, 100, attrs={"ref": "K9"})
    s.elements += [coil, no, other]
    apply_text_changes(p, renumber.plan(p, lib, renumber.ALL))
    assert other.ref == "K1" and coil.ref == "K2" and no.ref == "K2"


def test_scopes_number_separately_and_skipped_symbols(lib):
    p = Project()
    jps = p.sheets[0]
    b1 = Element("fve.switchboard", 0, 0, attrs={"ref": "RDC1"})
    b2 = Element("fve.switchboard", 50, 0, attrs={"ref": "RH"})
    jps.elements += [b1, b2]
    s1, s2 = p.create_switchboard_sheet(b1), p.create_switchboard_sheet(b2)
    f1 = Element("fve.breaker_mcb", 10, 10, attrs={"ref": "F4"})
    f2 = Element("fve.breaker_mcb", 10, 10, attrs={"ref": "F8"})
    x = Element("sb.feed", 0, 10, rotation=180, attrs={"dir": "in", "ref": "X7"})              # přívod se nečísluje
    s1.elements += [f1, x]
    s2.elements.append(f2)
    apply_text_changes(p, renumber.plan(p, lib, renumber.ALL))
    assert (f1.ref, f2.ref, x.ref, b1.ref, b2.ref) == ("F1", "F1", "X7", "RDC1", "RH")


def test_only_chosen_sheets_reserve_others(lib):
    p = Project()
    s1 = p.sheets[0]
    s2 = Sheet(name="List 2")
    p.sheets.append(s2)
    a = Element("fve.breaker_mcb", 10, 10, attrs={"ref": "F1"})
    b = Element("fve.breaker_mcb", 10, 10, attrs={"ref": "F5"})
    s1.elements.append(a)
    s2.elements.append(b)
    apply_text_changes(p, renumber.plan(p, lib, renumber.ALL, sheets=[s2]))
    assert a.ref == "F1" and b.ref == "F2"


def test_wires_and_cable_by_ref(lib):
    p = Project()
    s = p.sheets[0]
    g = Element("fve.pv_string", 0, 100, attrs={"ref": "G1"})
    t = Element("fve.inverter", 100, 100, attrs={"ref": "T1"})
    f = Element("fve.breaker_mcb", 200, 100, attrs={"ref": "F1"})
    s.elements += [g, t, f]
    w_late = _wire(t, "AC", f, "1", "W9")
    w_early = _wire(g, "DC", t, "DC1", "W4")
    s.wires += [w_late, w_early]
    p.cables.append(Cable(ref="W9", type="CYKY-J 5x6"))
    ch = renumber.plan(p, lib, renumber.ALL, devices=False)
    apply_text_changes(p, ch)
    assert (w_early.attrs["ref"], w_late.attrs["ref"]) == ("W1", "W2")
    assert p.cables[0].ref == "W2" and p.cable_of_wire(w_late) is p.cables[0]
    assert "2 vodiče" in renumber.summary(ch)
    apply_text_changes(p, ch, undo=True)
    assert p.cables[0].ref == "W9" and w_late.attrs["ref"] == "W9"


def test_bad_mode(lib):
    with pytest.raises(ValueError):
        renumber.plan(Project(), lib, "x")
