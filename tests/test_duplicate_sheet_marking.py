"""Duplikování listu rozvaděče: nové označení podle schématu generátoru (issue #159, navazuje na #144) –
předpona podle druhu rozvaděče (`generator.spec.BOARD_DEFAULT_PREFIX`) + další volné číslo v projektu."""
import pytest

from envocad.cmd.edits import duplicate_sheet
from envocad.generator.spec import board_kind_of_ref, next_board_ref
from envocad.library.store import LibraryStore
from envocad.model.designation import scope_key
from envocad.model.project import LOC, Element, Project, StructureId


@pytest.fixture
def lib(tmp_path):
    return LibraryStore(tmp_path / "lib.db")


def _board(ref, extra=()):
    p = Project(name="B")
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": ref, "desc": "rozvaděč"})
    p.sheets[0].elements.append(blk)
    for r in extra:
        p.sheets[0].elements.append(Element("fve.switchboard", 220, 150, attrs={"ref": r}))
    sb = p.create_switchboard_sheet(blk)
    sb.elements.append(Element("fve.breaker_mcb", 50, 100, attrs={"ref": "F1"}))
    return p, sb


@pytest.mark.parametrize("ref,kind", [
    ("RDC1", "dc_route"), ("RDC12", "dc_route"), ("RFVE.DC", "dc_tech"), ("RFVE.DC2", "dc_tech"),
    ("RFVE.AC", "ac"), ("HR", "main"), ("RVN", "mv"), ("RE", "meter"),
    ("RDX1", None), ("RDC1A", None), ("F1", None), ("", None),
])
def test_board_kind_of_ref(ref, kind):
    assert board_kind_of_ref(ref) == kind


def test_board_kind_of_ref_custom_prefix():
    assert board_kind_of_ref("RDS3", {"board_prefix": {"dc_route": "RDS"}}) == "dc_route"
    assert board_kind_of_ref("RDC3", {"board_prefix": {"dc_route": "RDS"}}) is None


def test_next_board_ref_first_free_number():
    assert next_board_ref("RDC1", {"RDC1", "RDC3"}) == "RDC2"
    assert next_board_ref("RFVE.DC", {"RFVE.DC"}) == "RFVE.DC1"
    assert next_board_ref("F1", set()) is None


@pytest.mark.parametrize("ref,new", [("RDC1", "RDC2"), ("RFVE.DC", "RFVE.DC1"), ("RFVE.AC", "RFVE.AC1"),
                                     ("HR", "HR1"), ("RE", "RE1")])
def test_duplikace_listu_rozvadece_novy_nazev_a_cislo(lib, ref, new):
    p, sb = _board(ref)
    c = duplicate_sheet(p, sb, lib)
    assert c.block.ref == new and c.sheet.loc == new
    assert c.sheet.name == f"{new} – rozvaděč"            # název listu sleduje nové označení
    assert c.block.attrs["sheet"] == c.sheet.name
    assert p.structure(LOC, new) is not None
    assert all(scope_key(c.sheet, e) != scope_key(sb, e) for e in c.sheet.elements)


def test_duplikace_bere_dalsi_volne_cislo_v_projektu(lib):
    p, sb = _board("RDC1", extra=("RDC2", "RDC3"))
    p.structures.append(StructureId(LOC, "RDC4", ""))
    c = duplicate_sheet(p, sb, lib)
    assert c.block.ref == "RDC5" and c.sheet.loc == "RDC5"


def test_duplikace_bez_schematu_dnesni_chovani(lib):
    p, sb = _board("XY7")
    c = duplicate_sheet(p, sb, lib)
    assert c.block.ref == "XY1" and c.sheet.loc == "XY1"   # beze změny proti dřívějšímu chování
    p, sb = _board("ROZV")           # bez čísla a bez druhu → dnešní označení z kopie prvku
    assert duplicate_sheet(p, sb, lib).block.ref == "R1"


def test_duplikace_listu_bez_bloku_se_schematem(lib):
    p, sb = _board("RFVE.DC")
    sb.parent_element_id = None
    sb.loc = "RFVE.DC"
    c = duplicate_sheet(p, sb, lib)
    assert c.block is None and c.sheet.loc == "RFVE.DC1"
