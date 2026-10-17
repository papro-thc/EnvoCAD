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
    # vývody bez vazby na JPS jsou jen informace; přístroje šablony nemají rozsah teplot → jedna agregovaná INFO
    assert all(x.code in ("feed_unlinked", "no_article", "no_cable", "thermal_device") for x in fs), {x.code for x in fs}
    th = [x for x in fs if x.code == "thermal_device"]
    assert len(th) == 1 and th[0].severity == INFO and "chybí rozsah teplot" in th[0].text


def _codes(fs, code):
    return [f for f in fs if f.code == code]


def test_dup_ref_by_scope_key():
    from envocad.model.project import Sheet
    lib = LibraryStore()
    p = Project()
    jps = p.sheets[0]
    b1 = Element("fve.switchboard", 0, 0, attrs={"ref": "RDC1"})
    b2 = Element("fve.switchboard", 50, 0, attrs={"ref": "RH"})
    jps.elements += [b1, b2]
    s1, s2 = p.create_switchboard_sheet(b1), p.create_switchboard_sheet(b2)
    s1.elements.append(Element("fve.breaker_mcb", attrs={"ref": "F1"}))
    s2.elements.append(Element("fve.breaker_mcb", attrs={"ref": "F1"}))       # jiné umístění → OK
    assert not _codes(check_project(p, lib), "dup_ref")
    # druhý list se stejným umístěním sdílí prostor označení
    s3 = Sheet(name="RDC1 – 2", kind="switchboard", loc="RDC1")
    p.sheets.append(s3)
    s3.elements.append(Element("fve.breaker_mcb", attrs={"ref": "F1"}))
    assert {f.sheet_id for f in _codes(check_project(p, lib), "dup_ref")} == {s1.id, s3.id}
    # override umístění prvku ho přesune jinam
    s3.elements[0].attrs["loc"] = "RX"
    assert not _codes(check_project(p, lib), "dup_ref")
    # anonymní list rozvaděče = vlastní prostor (dnešní chování)
    a1, a2 = Sheet(name="A1", kind="switchboard"), Sheet(name="A2", kind="switchboard")
    p.sheets += [a1, a2]
    a1.elements.append(Element("fve.breaker_mcb", attrs={"ref": "F1"}))
    a2.elements.append(Element("fve.breaker_mcb", attrs={"ref": "F1"}))
    assert not _codes(check_project(p, lib), "dup_ref")
    # vodiče JPS (kabely) mají společný prostor pro celý projekt, prvek se stejným ref nevadí
    jps2 = Sheet(name="JPS 2", func="AC")
    p.sheets.append(jps2)
    jps.wires.append(Wire(WireEnd(b1.id, "1"), WireEnd(b2.id, "1"), attrs={"ref": "W1"}))
    g = Element("fve.pv_string", attrs={"ref": "W1"})
    jps2.elements.append(g)
    jps2.wires.append(Wire(WireEnd(g.id, "DC"), WireEnd(g.id, "DC"), attrs={"ref": "W1"}))
    dups = _codes(check_project(p, lib), "dup_ref")
    assert {(f.ref, f.is_wire) for f in dups} == {("W1", True)} and len(dups) == 2


def test_designation_findings_codes():
    from envocad.model.project import Sheet, StructureId
    lib = LibraryStore()
    p = Project()
    jps = p.sheets[0]
    jps.func = "AC"
    p.structures.append(StructureId("=", "AC"))
    els = {
        "syntax": Element("fve.breaker_mcb", attrs={"ref": "Q1:2"}),
        "house": Element("fve.fuse_disconnect", attrs={"ref": "FU1.1"}),
        "chars": Element("fve.breaker_mcb", attrs={"ref": "f3"}),
        "length": Element("fve.breaker_mcb", attrs={"ref": "F12345678901"}),
        "class": Element("fve.breaker_mcb", attrs={"ref": "T1"}),
        "class_ok": Element("fve.breaker_mcb", attrs={"ref": "Q7"}),
        "unchecked": Element("fve.grid", attrs={"ref": "xx 1"}),          # bez tříd – nekontroluje se
        "contact": Element("ctl.contact_no", attrs={"ref": "K 1"}),       # kontakty se nekontrolují
        "override": Element("fve.pv_string", attrs={"ref": "G1", "loc": "STR", "func": "dc x"}),
        "full": Element("fve.breaker_mcb", attrs={"ref": "F123456789", "func": "ABCDEFGHIJ",
                                                     "loc": "KLMNOPQRST"}),
    }
    jps.elements += els.values()
    jps.wires.append(Wire(WireEnd(els["class"].id, "1"), WireEnd(els["class_ok"].id, "1"), attrs={"ref": "W 1"}))
    blk = Element("fve.switchboard", attrs={"ref": "RDC1"})
    jps.elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    sb.loc = "RS1"                                                        # liší se od bloku
    anon = Sheet(name="Anonymní", kind="switchboard")
    p.sheets.append(anon)
    p.structures.append(StructureId("+", "bad code"))
    fs = check_project(p, lib)
    by = {}
    for f in fs:
        by.setdefault(f.code, []).append(f)
    assert {f.ref for f in by["ref_syntax"] if f.severity == ERROR} == {"Q1:2", "W 1"}
    assert not {f.ref for f in by["ref_syntax"] if f.severity == INFO} & {"FU1.1"}   # tečka = firemní standard
    assert [f.ref for f in by["ref_chars"]] == ["f3"] and by["ref_chars"][0].severity == WARNING
    refs_len = {f.ref for f in by["ref_length"]}
    assert refs_len == {"F12345678901", "F123456789"}
    assert any("32 znaků" in f.text for f in by["ref_length"] if f.ref == "F123456789")
    assert [f.ref for f in by["ref_class"]] == ["T1"]
    assert "Jistič" in by["ref_class"][0].text and "F, Q" in by["ref_class"][0].text
    assert {f.ref for f in by["struct_syntax"]} == {"bad code", "G1"} and all(f.severity == ERROR
                                                                            for f in by["struct_syntax"])
    undefined = {f.text for f in by["struct_undefined"]}
    assert "Umístění +STR není v seznamu struktur projektu" in undefined
    assert "Umístění +RS1 není v seznamu struktur projektu" in undefined
    assert all(f.severity == INFO for f in by["struct_undefined"])
    assert [f.sheet_id for f in by["sb_no_loc"]] == [anon.id] and by["sb_no_loc"][0].severity == WARNING
    assert by["loc_mismatch"][0].text == "Umístění listu +RS1 se liší od označení bloku RDC1"
    assert by["loc_mismatch"][0].severity == INFO
    assert not any(f.target_id in (els["unchecked"].id, els["contact"].id) for f in fs
                   if f.code.startswith("ref_"))


def test_contact_ambiguous():
    lib = LibraryStore()
    p = Project()
    jps = p.sheets[0]
    b1 = Element("fve.switchboard", attrs={"ref": "RDC1"})
    b2 = Element("fve.switchboard", attrs={"ref": "RH"})
    c = Element("ctl.contact_no", attrs={"ref": "K1"})
    jps.elements += [b1, b2, c]
    s1, s2 = p.create_switchboard_sheet(b1), p.create_switchboard_sheet(b2)
    s1.elements.append(Element("ctl.coil", attrs={"ref": "K1"}))
    assert not _codes(check_project(p, lib), "contact_ambiguous")
    s2.elements.append(Element("ctl.coil", attrs={"ref": "K1"}))
    amb = _codes(check_project(p, lib), "contact_ambiguous")
    assert len(amb) == 1 and amb[0].severity == WARNING and amb[0].target_id == c.id
    assert "(+RDC1, +RH)" in amb[0].text
    c.attrs["loc"] = "RH"                       # umístění kontaktu vybere jednu cívku
    assert not _codes(check_project(p, lib), "contact_ambiguous")
    c.attrs["loc"] = "XX"                       # v prostoru kontaktu žádná cívka → nejednoznačné
    assert len(_codes(check_project(p, lib), "contact_ambiguous")) == 1
    # kontakt přímo na listu rozvaděče +RH (bez overridu) – prostor listu vybere cívku v +RH, žádné varování
    del c.attrs["loc"]
    jps.elements.remove(c)
    s2.elements.append(c)
    assert not _codes(check_project(p, lib), "contact_ambiguous")
    from envocad.model.project import coil_of
    assert coil_of(p, c)[0] is s2


def test_example_has_no_new_errors():
    """Ukázkový projekt (v1) po migraci na v8: žádná chyba a žádné nové nálezy označení."""
    from pathlib import Path
    p = Project.load(Path(__file__).parent.parent / "examples" / "ukazka_fve.ecp")
    fs = check_project(p, LibraryStore())
    assert not [f for f in fs if f.severity == ERROR]
    new_codes = {"ref_syntax", "ref_chars", "ref_length", "ref_class", "struct_syntax", "struct_undefined",
                 "sb_no_loc", "loc_mismatch", "contact_ambiguous"}
    assert not [f for f in fs if f.code in new_codes], [f.text for f in fs if f.code in new_codes]


def test_generated_projects_have_no_ref_warnings():
    """Vygenerované projekty (firemní číslování FU1.1, SPD-DC1.1) a šablony rozvaděčů: označení jen jako INFO."""
    from envocad.generate import build_project
    from envocad.library import templates as T
    lib = LibraryStore()
    spec = {"name": "Ref", "inverters": [{"ref": "T1", "p_ac": 25, "strings": [20, 20]},
                                          {"ref": "T2", "p_ac": 25, "strings": [20]}],
            "dc": {"route_boxes": 1, "tech_box": True, "disconnect": True}, "ac": {"distribution": "bus"}}
    p = build_project(spec)
    fs = [f for f in check_project(p, lib) if f.code.startswith("ref_")]
    assert fs and all(f.severity == "info" for f in fs), [f.text for f in fs if f.severity != "info"]
    assert any(f.ref.startswith("SPD-DC") for f in fs)
    for t in T.TEMPLATES:
        for dist in ("bus", "terminals"):
            tp = Project()
            blk = Element("fve.switchboard", attrs={"ref": "RH"})
            tp.sheets[0].elements.append(blk)
            T.apply_template(tp, tp.create_switchboard_sheet(blk), t.id, {"distribution": dist})
            bad = [f.text for f in check_project(tp, lib) if f.code.startswith("ref_") and f.severity != "info"]
            assert not bad, (t.id, dist, bad)
