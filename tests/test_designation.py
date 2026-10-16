"""Strukturní označení IEC 81346 (model/designation.py) – bez Qt."""
import pytest

from envocad.model.designation import (
    CABLE_SCOPE,
    MAX_REF_LEN,
    Designation,
    class_matches,
    designation,
    display_designation,
    full_designation,
    letter_code,
    parse_designation,
    scope_key,
    validate_code,
    validate_ref,
)
from envocad.model.project import Element, Project, Sheet, Wire, WireEnd


def test_designation_str_omits_empty_parts():
    assert str(Designation("AC", "RS1", "F3")) == "=AC+RS1-F3"
    assert str(Designation("", "RS1", "F3")) == "+RS1-F3"
    assert str(Designation(ref="F3")) == "-F3"
    assert str(Designation("AC", "RS1")) == "=AC+RS1"
    assert str(Designation()) == ""
    assert Designation("AC", "RS1", "F3").aspects == "=AC+RS1"


@pytest.mark.parametrize("text, expected", [
    ("=AC+RS1-F3", Designation("AC", "RS1", "F3")),
    ("+RS1-F3", Designation("", "RS1", "F3")),
    ("F3", Designation("", "", "F3")),
    ("-F3", Designation("", "", "F3")),
    ("+RS1=AC", Designation("AC", "RS1", "")),
    ("  =AC  ", Designation("AC", "", "")),
    ("", Designation()),
    ("+RDC1-SPD-DC1.1", Designation("", "RDC1", "SPD-DC1.1")),   # firemní číslování zůstane celé
])
def test_parse_designation(text, expected):
    assert parse_designation(text) == expected


@pytest.mark.parametrize("text", ["=AC=A1-F3", "+A+B", "=AC.1-F3", "-F3+RS1"])
def test_parse_designation_rejects_multilevel(text):
    with pytest.raises(ValueError):
        parse_designation(text)


def test_parse_roundtrip():
    for d in (Designation("AC", "RS1", "F3"), Designation("", "RDC1", "X1"), Designation(ref="Q1")):
        assert parse_designation(str(d)) == d


def test_letter_code_and_class_matches():
    assert letter_code("F3") == "F"
    assert letter_code("QA12") == "QA"
    assert letter_code("101") == ""
    assert letter_code("f3") == "F"
    assert class_matches("F3", ["F"]) and class_matches("FA1", ["F"]) and class_matches("FC2", ["F", "Q"])
    assert class_matches("Q1", ["F", "Q"])
    assert not class_matches("T1", ["F", "Q"])
    assert not class_matches("101", ["F"])
    assert class_matches("whatever", [])      # bez tříd se nekontroluje


def test_validate_code():
    assert validate_code("RS1", "+") == []
    assert validate_code("", "=") == []
    assert validate_code("AC_2", "=") == []
    for bad in ("RS 1", "rs1", "1RS", "A-B", "ABCDEFGHIJK"):
        issues = validate_code(bad, "+", "listu X")
        assert [i.code for i in issues] == ["struct_syntax"] and issues[0].error, bad
    assert "Umístění „RS 1“ listu X" in validate_code("RS 1", "+", "listu X")[0].text
    assert validate_code("ac", "=")[0].text.startswith("Funkce")


def test_validate_ref_codes():
    assert validate_ref("F3", ["F", "Q"]) == []
    assert validate_ref("", ["F"]) == []
    i = validate_ref("Q1-2", ["Q"])
    assert [x.code for x in i] == ["ref_syntax"] and i[0].info and not i[0].error   # firemní „-“ = jen informace
    for bad, ch in (("X1:3", ":"), ("Q1 2", "mezeru"), ("A=1", "="), ("A+1", "+"), ("K1/2", "/")):
        i = validate_ref(bad, None)
        assert [x.code for x in i] == ["ref_syntax"] and i[0].error and ch in i[0].text, bad
    i = validate_ref("-F3", ["F"])
    assert i[0].error and "bez „-“" in i[0].text
    i = validate_ref("FU1.1", ["F"])
    assert [x.code for x in i] == ["ref_syntax"] and i[0].info
    i = validate_ref("f3", ["F"])
    assert [x.code for x in i] == ["ref_chars"] and not i[0].error and not i[0].info
    assert [x.code for x in validate_ref("Fč1", ["F"])] == ["ref_chars"]
    long_ref = "F" + "1" * MAX_REF_LEN
    assert [x.code for x in validate_ref(long_ref, ["F"])] == ["ref_length"]
    i = validate_ref("T1", ["F", "Q"], name="Jistič")
    assert [x.code for x in i] == ["ref_class"]
    assert i[0].text == "Označení T1 neodpovídá funkci značky Jistič (povolené třídy: F, Q)"
    assert validate_ref("T1", None) == [] and validate_ref("T1", []) == []
    # vodič: smí začínat číslicí, třída se nekontroluje
    assert validate_ref("101", ["W"], is_wire=True) == []
    assert validate_ref("W1:2", None, is_wire=True)[0].code == "ref_syntax"


def _sheets():
    jps = Sheet(name="JPS", func="AC")
    sb = Sheet(name="RDC1", kind="switchboard", loc="RDC1")
    anon = Sheet(name="R?", kind="switchboard")
    return jps, sb, anon


def test_designation_inherits_and_overrides():
    jps, sb, _ = _sheets()
    f3 = Element("fve.breaker_mcb", attrs={"ref": "F3"})
    assert designation(jps, f3) == Designation("AC", "", "F3")
    assert designation(sb, f3) == Designation("", "RDC1", "F3")
    g1 = Element("fve.pv_string", attrs={"ref": "G1", "loc": "STR"})
    assert designation(jps, g1) == Designation("AC", "STR", "G1")
    w = Wire(WireEnd("a", "1"), WireEnd("b", "1"), attrs={"ref": "W1", "loc": "XX"})
    assert designation(sb, w) == Designation("", "RDC1", "W1")      # vodiče override nemají


def test_scope_key():
    jps, sb, anon = _sheets()
    f3 = Element("fve.breaker_mcb", attrs={"ref": "F3"})
    assert scope_key(jps, f3) == ("AC", "")
    assert scope_key(sb, f3) == ("", "RDC1")
    assert scope_key(anon, f3) == ("", "#" + anon.id)
    assert scope_key(anon, Element("x", attrs={"ref": "F1", "loc": "RH"})) == ("", "RH")
    w = Wire(WireEnd("a", "1"), WireEnd("b", "1"), attrs={"ref": "W1"})
    assert scope_key(jps, w) == CABLE_SCOPE
    assert scope_key(sb, w) == ("", "RDC1")
    assert scope_key(anon, w) == ("", "#" + anon.id)


def test_full_and_display_designation():
    p = Project()
    jps, sb, anon = _sheets()
    f3 = Element("fve.breaker_mcb", attrs={"ref": "F3"})
    assert full_designation(p, jps, f3) == "=AC-F3"
    assert full_designation(p, sb, f3) == "+RDC1-F3"
    assert full_designation(p, anon, f3) == "-F3"
    blk = Element("fve.switchboard", attrs={"ref": "RDC1"})
    assert full_designation(p, jps, blk) == "=AC+RDC1"         # blok = prvek umístění
    assert full_designation(p, Sheet(), Element("fve.switchboard", attrs={})) == ""
    # výkres: bez overridu jen ref, s overridem jen odlišné části
    assert display_designation(sb, f3) == "F3"
    g1 = Element("fve.pv_string", attrs={"ref": "G1", "loc": "STR"})
    assert display_designation(jps, g1) == "+STR-G1"
    same = Element("fve.pv_string", attrs={"ref": "G2", "func": "AC"})
    assert display_designation(jps, same) == "G2"
    assert display_designation(jps, blk) == "RDC1"
    assert display_designation(jps, Wire(WireEnd("a", "1"), WireEnd("b", "1"), attrs={"ref": "W1"})) == "W1"
