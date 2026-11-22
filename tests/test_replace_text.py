"""Najít a nahradit text v projektu (issue #74): model bez Qt, `envocad/cmd/edits.py`."""
import copy

import pytest

from envocad.cmd import default_registry
from envocad.cmd.edits import TextMatch, find_text, replace_text
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Sheet, SheetText, Wire, WireEnd, sheets_state


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


@pytest.fixture
def proj():
    """Dva listy; hledaný text „kabel“ je v textech, popisech, atributu vodiče i v chráněných polích."""
    p = Project(name="Replace")
    s1 = p.sheets[0]
    s1.name = "Kabel hlavní"
    s1.func = "kabel"
    s1.loc = "kabel"
    a = Element("fve.hds", 30, 150, attrs={"ref": "kabel1", "desc": "Kabel k měniči, kabel 2", "func": "kabel",
                                             "loc": "kabel"})
    b = Element("fve.hds", 80, 150, attrs={"ref": "Q2", "desc": "bez shody"})
    s1.elements += [a, b]
    s1.wires.append(Wire(WireEnd(a.id, "1"), WireEnd(b.id, "1"),
                         attrs={"ref": "kabel-W1", "route": "v zemi, kabel KABEL"}))
    s1.texts.append(SheetText(10, 10, "Poznámka: kabel"))
    s2 = Sheet(name="Druhý")
    c = Element("fve.hds", 30, 150, attrs={"ref": "Q3", "desc": "druhý kabel"})
    s2.elements.append(c)
    s2.texts.append(SheetText(10, 10, "kabel na druhém listu"))
    p.sheets.append(s2)
    return p


def test_empty_find_raises(proj, lib):
    with pytest.raises(ValueError):
        find_text(proj, lib, "")
    with pytest.raises(ValueError):
        replace_text(proj, lib, "", "x")


def test_project_scope_replaces_all_sheets(proj, lib):
    n = replace_text(proj, lib, "kabel", "vodič")
    s1, s2 = proj.sheets
    assert s1.texts[0].text == "Poznámka: vodič"
    assert s2.texts[0].text == "vodič na druhém listu"
    assert s2.elements[0].attrs["desc"] == "druhý vodič"
    # volný text 1 + popis a 2x + route 2x + druhý list: text 1 + desc 1
    assert n == 1 + 2 + 2 + 1 + 1


def test_sheet_scope_changes_only_that_sheet(proj, lib):
    s1, s2 = proj.sheets
    before2 = copy.deepcopy(s2.to_dict())
    n = replace_text(proj, lib, "kabel", "vodič", sheet=s1)
    assert s1.texts[0].text == "Poznámka: vodič"
    assert s2.to_dict() == before2
    assert n == 1 + 2 + 2


@pytest.mark.parametrize("match_case, expected, count", [
    (False, "A-X, X, X", 3),
    (True, "A-X, KABEL, Kabel", 1),
])
def test_match_case(lib, match_case, expected, count):
    p = Project(name="Case")
    p.sheets[0].texts.append(SheetText(0, 0, "A-kabel, KABEL, Kabel"))
    n = replace_text(p, lib, "kabel", "X", match_case=match_case)
    assert n == count
    assert p.sheets[0].texts[0].text == expected


def test_nothing_found_returns_zero_and_keeps_project(proj, lib):
    before = (proj.to_dict(), sheets_state(proj))
    assert replace_text(proj, lib, "neexistuje", "x") == 0
    assert (proj.to_dict(), sheets_state(proj)) == before


def test_literal_no_regex_non_overlapping(lib):
    p = Project(name="Lit")
    t = SheetText(0, 0, "a.b a*b aab aaaa")
    p.sheets[0].texts.append(t)
    assert replace_text(p, lib, ".", "!") == 1
    assert replace_text(p, lib, "*", "?") == 1
    assert t.text == "a!b a?b aab aaaa"
    assert replace_text(p, lib, "aa", "X") == 3      # „aab“ 1x, „aaaa“ 2x (zleva, bez překryvu)
    assert t.text == "a!b a?b Xb XX"


def test_protected_fields_unchanged(proj, lib):
    replace_text(proj, lib, "kabel", "vodič")
    s1 = proj.sheets[0]
    a = s1.elements[0]
    assert a.attrs["ref"] == "kabel1"
    assert a.attrs["func"] == "kabel" and a.attrs["loc"] == "kabel"
    assert s1.wires[0].attrs["ref"] == "kabel-W1"
    assert (s1.func, s1.loc, s1.name) == ("kabel", "kabel", "Kabel hlavní")
    assert a.attrs["desc"] == "vodič k měniči, vodič 2"
    assert s1.wires[0].attrs["route"] == "v zemi, vodič vodič"
    assert "kabel" not in a.attrs["desc"].lower()


def test_unknown_attr_key_and_wire_id_untouched(lib):
    p = Project(name="Keys")
    e = Element("fve.hds", 0, 0, attrs={"ref": "Q1", "desc": "x", "zzz_cizi": "kabel", "wire_id": "kabel"})
    p.sheets[0].elements.append(e)
    assert replace_text(p, lib, "kabel", "X") == 0
    assert e.attrs["zzz_cizi"] == "kabel" and e.attrs["wire_id"] == "kabel"


def test_find_text_does_not_change_and_reports(proj, lib):
    before = (proj.to_dict(), sheets_state(proj))
    ms = find_text(proj, lib, "kabel", "vodič")
    assert (proj.to_dict(), sheets_state(proj)) == before
    assert all(isinstance(m, TextMatch) for m in ms)
    s1, s2 = proj.sheets
    by = {(m.kind, m.target_id, m.key): m for m in ms}
    assert len(ms) == 5
    m = by[("text", s1.texts[0].id, "text")]
    assert (m.sheet_id, m.old, m.new, m.count) == (s1.id, "Poznámka: kabel", "Poznámka: vodič", 1)
    m = by[("element", s1.elements[0].id, "desc")]
    assert (m.old, m.new, m.count) == ("Kabel k měniči, kabel 2", "vodič k měniči, vodič 2", 2)
    m = by[("wire", s1.wires[0].id, "route")]
    assert (m.old, m.new, m.count) == ("v zemi, kabel KABEL", "v zemi, vodič vodič", 2)
    assert sum(x.count for x in ms) == 7
    assert {x.sheet_id for x in ms} == {s1.id, s2.id}
    only1 = find_text(proj, lib, "kabel", "vodič", sheet=s1)
    assert {x.sheet_id for x in only1} == {s1.id}
    assert find_text(proj, lib, "neexistuje") == []


def test_replace_command_registered():
    cmd = default_registry(user_aliases=False).resolve("replace")
    assert cmd is not None
    assert not cmd.needs_gui


# ---- chráněné technické atributy (review PR #98): vazby a čísla svorek / kontaktů se nahrazením nesmí změnit ----------
# (značka, klíč, hodnota, hledaný text, náhrada)
PROTECTED_CASES = [
    ("fve.switchboard", "ports_in", "X1 X2", "X1", "X9"),
    ("fve.switchboard", "ports_out", "XOUT X1B", "X1", "X9"),
    ("fve.switchboard", "protect", "X1=63, X3=40", "X1", "X9"),
    ("fve.switchboard", "sheet", "RDC1 – DC rozvaděč", "RDC1", "RDC5"),
    ("fve.grid_protection", "acts_on", "Q1", "Q1", "Q9"),
    ("sb.busbar", "taps", "3", "3", "5"),
    ("sb.busbar", "outs", "3", "3", "5"),
    ("sb.busbar", "tap_pitch", "30", "3", "5"),
    ("sb.terminal_block", "terminal", "1 2 3", "3", "5"),
    ("sb.feed", "terminal", "1 2 3", "3", "5"),
    ("ctl.contact_no", "terminals", "13/14", "13", "23"),
    ("ctl.contact_nc", "terminals", "21/22", "21", "31"),
    ("ctl.coil", "contacts", "1/2 3/4 13/14", "13", "23"),
    ("fve.contactor", "contacts", "1/2 3/4 13/14", "13", "23"),
]


@pytest.mark.parametrize("symbol_id, key, value, find, new", PROTECTED_CASES,
                         ids=[f"{c[0]}:{c[1]}" for c in PROTECTED_CASES])
def test_protected_technical_attr_unchanged(lib, symbol_id, key, value, find, new):
    assert key in {a.key for a in lib.get_symbol(symbol_id).attributes}     # klíč je atributem značky, ne cizí
    p = Project(name="Protected")
    e = Element(symbol_id, 30, 150, attrs={"ref": "A1", key: value})
    p.sheets[0].elements.append(e)
    p.sheets[0].texts.append(SheetText(10, 10, f"popis {find}"))
    ms = find_text(p, lib, find, new)
    assert [(m.kind, m.key) for m in ms] == [("text", "text")]
    assert replace_text(p, lib, find, new) == 1
    assert e.attrs[key] == value
    assert p.sheets[0].texts[0].text == f"popis {new}"                       # běžný text se přitom nahradí


def test_protected_keys_cover_busbar_params():
    from envocad.cmd.edits import REPLACE_PROTECTED_KEYS
    from envocad.model.busbar import PARAM_KEYS
    assert set(PARAM_KEYS) <= REPLACE_PROTECTED_KEYS


def test_replace_keeps_wire_on_block_port(lib):
    """`REPLACE X1 X9` nesmí přejmenovat port bloku rozvaděče pod vodičem (kontrola `bad_port`)."""
    from envocad.model.checks import check_project
    p = Project(name="Ports")
    s = p.sheets[0]
    blk = Element("fve.switchboard", 100, 150, attrs={"ref": "RD1", "ports_in": "X1", "desc": "přívod X1"})
    src = Element("fve.hds", 30, 150, attrs={"ref": "Q1"})
    s.elements += [blk, src]
    s.wires.append(Wire(WireEnd(src.id, "1"), WireEnd(blk.id, "X1")))
    def bad():
        return [f for f in check_project(p, lib, standard_paper="A3") if f.code == "bad_port"]

    assert bad() == []
    assert replace_text(p, lib, "X1", "X9") == 1
    assert blk.attrs["ports_in"] == "X1" and blk.attrs["desc"] == "přívod X9"
    assert bad() == []


def test_hidden_text_attrs_still_replaced(lib):
    """Skryté atributy (`show: false`) se obecně nevynechávají – trasa vodiče i skrytý popis jsou běžné texty."""
    p = Project(name="Hidden")
    s = p.sheets[0]
    a = Element("ctl.contact_no", 30, 150, attrs={"ref": "K1", "desc": "pomocný kabel", "terminals": "13/14"})
    b = Element("fve.hds", 80, 150, attrs={"ref": "Q2"})
    s.elements += [a, b]
    s.wires.append(Wire(WireEnd(a.id, "1"), WireEnd(b.id, "1"), attrs={"route": "kabel v zemi"}))
    assert not next(x for x in lib.get_symbol("ctl.contact_no").attributes if x.key == "desc").show
    assert replace_text(p, lib, "kabel", "vodič") == 2
    assert a.attrs["desc"] == "pomocný vodič" and s.wires[0].attrs["route"] == "vodič v zemi"
