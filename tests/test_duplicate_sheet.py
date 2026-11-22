"""Duplikování listu (issue #71, `envocad.cmd.edits.duplicate_sheet`) – headless, bez Qt: schéma se přečísluje jako
při kopii prvků, list rozvaděče si ponechá označení a kopie se přeznačí (blok ROZVADĚČ, LOC, struktury)."""
import copy

import pytest

from envocad.cmd.edits import SheetCopy, duplicate_sheet
from envocad.library.store import LibraryStore
from envocad.model.checks import check_project
from envocad.model.project import (
    LOC,
    Element,
    Note,
    Placement,
    Project,
    Revision,
    RevisionMark,
    Sheet,
    SheetText,
    Wire,
    WireEnd,
    interrupt_partner,
)


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _dup_refs(p: Project, lib) -> int:
    return sum(1 for f in check_project(p, lib, standard_paper="A4") if f.code == "dup_ref")


def _all_ids(p: Project) -> list[str]:
    ids = [s.id for s in p.sheets]
    for s in p.sheets:
        ids += [e.id for e in s.elements] + [w.id for w in s.wires] + [t.id for t in s.texts]
    return ids


def _schematic() -> tuple[Project, Sheet]:
    p = Project(name="Dup")
    s = p.sheets[0]
    s.name, s.func, s.loc = "Silové schéma", "AC", "RFVE"
    t = Element("fve.inverter", 50, 150, rotation=90, mirror=True, attrs={"ref": "T1"})
    f = Element("fve.breaker_mcb", 100, 150, attrs={"ref": "F1", "in_": "50 A"})
    x = Element("sb.terminal_block", 150, 150, attrs={"ref": "X1", "terminal": "7"})
    s.elements += [t, f, x]
    s.wires += [Wire(WireEnd(t.id, "AC"), WireEnd(f.id, "1"), points=[(75.0, 160.0)], conductors=["L1", "N"],
                     attrs={"ref": "W1", "cable_id": "C-ORIG"}),
                Wire(WireEnd(f.id, "2"), WireEnd(x.id, "1"), attrs={"ref": "W2"})]
    s.texts.append(SheetText(x=10, y=20, text="Poznámka", height=3.5))
    return p, s


# ---- schéma ---------------------------------------------------------------------------------------------------
def test_kopie_je_hned_za_originalem_a_ma_stejne_vlastnosti(lib):
    p, s = _schematic()
    p.sheets.append(Sheet(name="Další"))
    s.paper, s.width, s.height, s.mp_paper = "A4", 297.0, 210.0, "A4"
    res = duplicate_sheet(p, s, lib)
    assert isinstance(res, SheetCopy)
    c = res.sheet
    assert p.sheets.index(c) == p.sheets.index(s) + 1 and p.sheets[2].name == "Další"
    assert c.id != s.id and c.kind == "schematic"
    assert (c.paper, c.width, c.height, c.func, c.loc, c.mp_paper) == ("A4", 297.0, 210.0, "AC", "RFVE", "A4")
    assert res.block is None and res.parent is None


def test_kopie_ma_nova_id_a_stejnou_geometrii(lib):
    p, s = _schematic()
    res = duplicate_sheet(p, s, lib)
    c = res.sheet
    ids = _all_ids(p)
    assert len(ids) == len(set(ids))
    assert [(e.symbol_id, e.x, e.y, e.rotation, e.mirror) for e in c.elements] == \
           [(e.symbol_id, e.x, e.y, e.rotation, e.mirror) for e in s.elements]
    assert set(res.element_ids) == {e.id for e in s.elements}
    assert [res.element_ids[e.id] for e in s.elements] == [e.id for e in c.elements]
    assert [res.wire_ids[w.id] for w in s.wires] == [w.id for w in c.wires]
    for w, cw in zip(s.wires, c.wires):
        assert (res.element_ids[w.a.element_id], w.a.port) == (cw.a.element_id, cw.a.port)
        assert (res.element_ids[w.b.element_id], w.b.port) == (cw.b.element_id, cw.b.port)
        assert (cw.points, cw.conductors) == (w.points, w.conductors)


def test_originalni_list_zustane_beze_zmeny(lib):
    p, s = _schematic()
    before = copy.deepcopy(s.to_dict())
    duplicate_sheet(p, s, lib)
    assert s.to_dict() == before


def test_volne_texty_se_kopiruji_s_novymi_id(lib):
    p, s = _schematic()
    c = duplicate_sheet(p, s, lib).sheet
    assert [(t.x, t.y, t.text, t.height) for t in c.texts] == [(10, 20, "Poznámka", 3.5)]
    assert c.texts[0].id != s.texts[0].id


def test_revize_a_pripominky_se_nekopiruji(lib):
    p, s = _schematic()
    rev = Revision(label="A")
    rev.marks.append(RevisionMark(sheet_id=s.id, x=1, y=2))
    p.revisions.append(rev)
    p.notes.append(Note(sheet_id=s.id, x=1, y=2, text="pozn"))
    duplicate_sheet(p, s, lib)
    assert len(p.revisions) == 1 and len(p.revisions[0].marks) == 1 and len(p.notes) == 1


@pytest.mark.parametrize("n_copies, expected", [(1, "Silové schéma – kopie"), (2, "Silové schéma – kopie 2"),
                                                (3, "Silové schéma – kopie 3")])
def test_nazev_kopie_je_jedinecny(lib, n_copies, expected):
    p, s = _schematic()
    for _ in range(n_copies):
        c = duplicate_sheet(p, s, lib).sheet
    assert c.name == expected


def test_schema_se_precisluje_jako_pri_kopii_prvku(lib):
    p, s = _schematic()
    c = duplicate_sheet(p, s, lib).sheet
    refs = {e.symbol_id: e.ref for e in c.elements}
    assert refs["fve.inverter"] == "T2" and refs["fve.breaker_mcb"] == "F2"
    assert [w.attrs["ref"] for w in c.wires] == ["W3", "W4"]
    assert all(w.attrs.get("cable_id", "") == "" for w in c.wires)        # kabel originálu se nepřebírá
    assert s.wires[0].attrs["cable_id"] == "C-ORIG"
    xb = next(e for e in c.elements if e.symbol_id == "sb.terminal_block")
    assert xb.ref == "X1" and xb.attrs["terminal"] == ""                  # svorkovnice stejná, číslo se vymaže
    assert _dup_refs(p, lib) == 0


def test_prerusovaci_body_v_kopii_nemaji_oznaceni(lib):
    p = Project(sheets=[Sheet(name="L1"), Sheet(name="L2")])
    a, b = (Element("fve.interrupt", 100, 150, attrs={"ref": "L1"}) for _ in range(2))
    p.sheets[0].elements.append(a)
    p.sheets[1].elements.append(b)
    assert interrupt_partner(p, a)[1] is b
    c = duplicate_sheet(p, p.sheets[0], lib).sheet
    assert [e.ref for e in c.elements] == [""]
    assert interrupt_partner(p, a)[1] is b and interrupt_partner(p, b)[1] is a


def test_kontakty_sleduji_precislovanou_civku(lib):
    p = Project(sheets=[Sheet(name="Ovládání")])
    s = p.sheets[0]
    coil = Element("ctl.coil", 50, 150, attrs={"ref": "K1"})
    no = Element("ctl.contact_no", 100, 150, attrs={"ref": "K1"})
    nc = Element("ctl.contact_nc", 150, 150, attrs={"ref": "K1"})
    pw = Element("ctl.contact_power", 200, 150, attrs={"ref": "K1", "poles": "3"})
    orphan = Element("ctl.contact_no", 250, 150, attrs={"ref": "K7"})     # cívka K7 na listu není
    s.elements += [coil, no, nc, pw, orphan]
    c = duplicate_sheet(p, s, lib).sheet
    assert [e.ref for e in c.elements] == ["K2", "K2", "K2", "K2", "K7"]
    assert [e.ref for e in s.elements] == ["K1", "K1", "K1", "K1", "K7"]


# ---- list rozvaděče -------------------------------------------------------------------------------------------
def _switchboard(name_desc: str = "AC rozvaděč") -> tuple[Project, Sheet, Element, Sheet]:
    """JPS s blokem RDC1 a jeho list rozvaděče (jistič, svorkovnice s čísly, přívod, můstek, rozložení)."""
    p = Project(name="RDC")
    jps = p.sheets[0]
    t = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "RDC1", "desc": name_desc})
    jps.elements += [t, blk]
    jps.wires.append(Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "1"), attrs={"ref": "W1"}))
    sb = p.create_switchboard_sheet(blk)
    f = Element("fve.breaker_mcb", 50, 100, attrs={"ref": "F1"})
    x = Element("sb.terminal_block", 100, 100, attrs={"ref": "X1", "terminal": "1"})
    x2 = Element("sb.terminal_block", 130, 100, attrs={"ref": "X1", "terminal": "2"})
    feed = Element("sb.feed", 20, 100, attrs={"ref": "X2", "wire_id": jps.wires[0].id})
    sb.elements += [f, x, x2, feed]
    sb.wires.append(Wire(WireEnd(f.id, "2"), WireEnd(x.id, "1")))
    sb.bridges = {"X1": [["1", "2"]]}
    sb.layout.enclosure = "Skříň 4×24"
    sb.layout.params = {"width_mm": "600"}
    sb.layout.placements = [Placement(f.id, 0, 3.0), Placement(x.id, 1, 0.0)]
    return p, jps, blk, sb


def test_rozvadec_zachova_oznaceni_svorky_mustky_a_rozlozeni(lib):
    p, _, _, sb = _switchboard()
    res = duplicate_sheet(p, sb, lib)
    c = res.sheet
    assert [e.ref for e in c.elements] == [e.ref for e in sb.elements]
    assert [e.attrs.get("terminal") for e in c.elements] == [e.attrs.get("terminal") for e in sb.elements]
    assert c.bridges == sb.bridges and c.bridges is not sb.bridges
    assert c.bridges["X1"] is not sb.bridges["X1"]
    assert c.layout is not sb.layout
    assert (c.layout.rows, c.layout.modules_per_row, c.layout.enclosure, c.layout.params) == \
           (sb.layout.rows, sb.layout.modules_per_row, "Skříň 4×24", {"width_mm": "600"})
    assert [(pl.element_id, pl.row, pl.pos) for pl in c.layout.placements] == \
           [(res.element_ids[pl.element_id], pl.row, pl.pos) for pl in sb.layout.placements]
    assert {e.id for e in c.elements} >= {pl.element_id for pl in c.layout.placements}


def test_rozvadec_kopie_privodu_nema_vazbu_na_vodic(lib):
    p, _, _, sb = _switchboard()
    c = duplicate_sheet(p, sb, lib).sheet
    feed = next(e for e in c.elements if e.symbol_id == "sb.feed")
    assert feed.attrs.get("wire_id", "") == ""
    assert next(e for e in sb.elements if e.symbol_id == "sb.feed").attrs["wire_id"]


def test_rozvadec_s_blokem_prida_blok_loc_a_nazev(lib):
    p, jps, blk, sb = _switchboard()
    before_blk, before_sb = copy.deepcopy(blk.to_dict()), copy.deepcopy(sb.to_dict())
    res = duplicate_sheet(p, sb, lib)
    c, nb = res.sheet, res.block
    assert nb is not None and res.parent is jps and nb in jps.elements and nb.id != blk.id
    assert nb.symbol_id == "fve.switchboard" and nb.ref == "RDC2"
    assert not any(w.touches(nb.id) for w in jps.wires)                   # bez vodičů
    assert c.parent_element_id == nb.id and c.loc == "RDC2"
    assert c.name == "RDC2 – AC rozvaděč" and nb.attrs["sheet"] == c.name
    assert p.structure(LOC, "RDC2") is not None and p.structure(LOC, "RDC1") is not None
    assert p.switchboard_sheet(nb.id) is c and p.switchboard_sheet(blk.id) is sb
    assert blk.to_dict() == before_blk and sb.to_dict() == before_sb


def test_rozvadec_nazev_bez_oznaceni_dostane_kopie(lib):
    p, _, _, sb = _switchboard()
    sb.name = "Hlavní rozvaděč"
    assert duplicate_sheet(p, sb, lib).sheet.name == "Hlavní rozvaděč – kopie"


def test_rozvadec_kontrola_nehlasi_nova_duplicitni_oznaceni(lib):
    p, _, _, sb = _switchboard()
    before = _dup_refs(p, lib)
    duplicate_sheet(p, sb, lib)
    assert _dup_refs(p, lib) == before
    duplicate_sheet(p, sb, lib)                                           # i druhá kopie → RDC3
    assert _dup_refs(p, lib) == before
    assert p.switchboard_sheet(p.sheets[1].parent_element_id) is p.sheets[1]


@pytest.mark.parametrize("loc, expected", [("RDC1", "RDC2"), ("Rozvodna", "")])
def test_rozvadec_bez_bloku(lib, loc, expected):
    p = Project(name="Sirotek")
    sb = Sheet(name="Rozvaděč", kind="switchboard", loc=loc)
    sb.elements.append(Element("fve.breaker_mcb", 50, 100, attrs={"ref": "F1"}))
    p.sheets.append(sb)
    res = duplicate_sheet(p, sb, lib)
    assert res.block is None and res.parent is None
    assert res.sheet.parent_element_id is None and res.sheet.loc == expected
    assert res.sheet.elements[0].ref == "F1"


def test_neznama_znacka_duplikaci_neshodi(lib):
    """Prvek se značkou, kterou knihovna nezná (cizí / smazaná značka), se zkopíruje se svým označením."""
    p, s = _schematic()
    s.elements.append(Element(symbol_id="x.neznama", x=50.0, y=50.0, attrs={"ref": "Z9"}))
    res = duplicate_sheet(p, s, lib)
    assert [e.ref for e in res.sheet.elements if e.symbol_id == "x.neznama"] == ["Z9"]
