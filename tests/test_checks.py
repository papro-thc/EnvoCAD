"""Kontroly projektu (bez Qt)."""

from envocad.library.store import LibraryStore
from envocad.library.templates import apply_template
from envocad.model.checks import ERROR, INFO, WARNING, check_project, summary
from envocad.model.project import Element, Project, Wire, WireEnd


def test_checks_find_typical_problems():
    lib = LibraryStore()
    p = Project(name="Kontrola")
    s = p.sheets[0]
    g = Element("fve.pv_string", 30, 150, attrs={"ref": "G1"})
    t = Element("fve.inverter", 100, 150, attrs={"ref": "T1"})
    f = Element("fve.breaker_mcb", 150, 150, attrs={"ref": "T1"})       # duplicitní označení
    blk = Element("fve.switchboard", 200, 150, attrs={"ref": "R1"})     # bez listu
    lonely = Element("fve.meter", 250, 100, attrs={"ref": "P1"})        # nezapojený
    s.elements += [g, t, f, blk, lonely]
    s.wires.append(Wire(WireEnd(g.id, "DC"), WireEnd(t.id, "DC1"), attrs={"ref": "W1"}))  # bez kabelu, bez žil
    s.wires.append(Wire(WireEnd(t.id, "AC"), WireEnd(f.id, "9"), attrs={"ref": "W2", "cable": "CYKY"}))  # špatný port
    fs = check_project(p, lib)
    codes = {(x.code, x.ref) for x in fs}
    assert ("dup_ref", "T1") in codes
    assert ("bad_port", "W2") in codes
    assert ("no_sheet", "R1") in codes
    assert ("unconnected", "P1") in codes
    assert ("no_cable", "W1") in codes and ("no_cond", "W1") in codes
    assert ("free_port", "T1") not in codes  # volný DC vstup střídače je rezerva, ne chyba
    assert any(x.severity == ERROR for x in fs) and any(x.severity == WARNING for x in fs) and any(x.severity == INFO for x in fs)
    assert fs[0].severity == ERROR  # seřazeno podle závažnosti
    assert "chyb" in summary(fs)


def test_checks_switchboard_template_is_mostly_clean():
    lib = LibraryStore()
    p = Project(name="Šablona")
    s = p.sheets[0]
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    s.elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    fs = [x for x in check_project(p, lib) if x.sheet_id == sb.id]
    assert not any(x.severity == ERROR for x in fs), [x.text for x in fs if x.severity == ERROR]
    # vývody bez vazby na JPS jsou jen informace
    assert all(x.code in ("feed_unlinked", "no_article", "no_cable") for x in fs), {x.code for x in fs}
