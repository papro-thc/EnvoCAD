"""Křížové odkazy (envocad/model/xref.py): kontaktní obraz, skupiny přístrojů, zrcadlo kontaktů, přerušovací body
(dvojice, řetěz, hvězda) a oprava chyby stykač + cívka se stejným označením."""
import ezdxf
import pytest

from envocad.export import reports
from envocad.library.store import LibraryStore
from envocad.model import xref as X
from envocad.model.checks import ERROR, WARNING, check_project
from envocad.model.frame import position_ref
from envocad.model.project import (
    Element,
    Project,
    Sheet,
    coil_candidates,
    coil_of,
    contact_mirror,
    contact_terminals,
    contacts_of,
    element_xref,
    interrupt_partner,
)


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _codes(findings, code):
    return [f for f in findings if f.code == code]


# ---- kontaktní obraz a páry ----------------------------------------------------------------------------------
def test_parse_contact_image():
    slots, bad = X.parse_contact_image("1/2 3/4, 5/6 13/14 21/22 57/58 67/68")
    assert [(s.kind, s.pair) for s in slots] == [("power", "1/2"), ("power", "3/4"), ("power", "5/6"), ("no", "13/14"),
                                                 ("nc", "21/22"), ("no", "57/58"), ("no", "67/68")]
    assert bad == []
    slots, bad = X.parse_contact_image("NO:11/14 nc:11/12 NO:DO1 P:L1/T1")
    assert [(s.kind, s.pair) for s in slots] == [("no", "11/14"), ("nc", "11/12"), ("no", "DO1"), ("power", "L1/T1")]
    assert bad == []
    slots, bad = X.parse_contact_image("13/24 2/4 XX:1/2 abc NO: 33/34")
    assert bad == ["13/24", "2/4", "XX:1/2", "abc", "NO:"] and [s.pair for s in slots] == ["33/34"]
    assert X.parse_contact_image("") == ([], [])


def test_contact_pairs_and_kinds():
    no = Element("ctl.contact_no", attrs={"ref": "K1"})
    nc = Element("ctl.contact_nc", attrs={"ref": "K1"})
    pw = Element("ctl.contact_power", attrs={"ref": "K1", "poles": "3"})
    km = Element("fve.contactor", attrs={"ref": "K1", "poles": "4"})
    multi = Element("ctl.contact_no", attrs={"ref": "K1", "terminals": "13/14, 23/24"})
    assert X.contact_pairs(no) == ["13/14"] and X.contact_pairs(nc) == ["21/22"]
    assert X.contact_pairs(pw) == ["1/2", "3/4", "5/6"]
    assert X.contact_pairs(km) == ["1/2", "3/4", "5/6", "7/8"]
    assert X.contact_pairs(multi) == ["13/14", "23/24"]
    assert contact_terminals(pw) == "1/2 3/4 5/6"
    assert X.contact_kind(no) == "no" and X.contact_kind(nc) == "nc" and X.contact_kind(km) == "power"
    assert X.contact_kind(Element("ctl.coil")) is None and X.contact_pairs(Element("ctl.coil")) == []
    assert sorted(["13/14", "5/6", "1/2", "21/22", "3/4"], key=X.natural_key) == ["1/2", "3/4", "5/6", "13/14", "21/22"]


# ---- skupiny přístrojů ----------------------------------------------------------------------------------------
def _km_project():
    """Regrese: fve.contactor K1 (silové schéma) + ctl.coil K1 + pomocné kontakty K1 v jednom prostoru."""
    p = Project(name="NS ochrana")
    power, ctl = p.sheets[0], Sheet(name="Ovládání")
    p.sheets.append(ctl)
    km = Element("fve.contactor", 100, 150, attrs={"ref": "K1", "poles": "3", "modules": "3", "type": "DILM25",
                                                   "in_": "25"})
    coil = Element("ctl.coil", 200, 200, attrs={"ref": "K1", "modules": "3", "p_loss_w": "5"})
    c_no = Element("ctl.contact_no", 100, 200, attrs={"ref": "K1", "terminals": "13/14"})
    c_nc = Element("ctl.contact_nc", 300, 100, attrs={"ref": "K1", "terminals": "21/22"})
    power.elements.append(km)
    ctl.elements += [coil, c_no, c_nc]
    return p, power, ctl, km, coil, c_no, c_nc


def test_device_index_groups():
    p, power, ctl, km, coil, c_no, c_nc = _km_project()
    idx = X.DeviceIndex.build(p)
    g = idx.group_of(coil)
    assert g is idx.group_of(km) is idx.group_of(c_no) is idx.group_of(c_nc)
    assert g.host == (ctl, coil) and g.device == (power, km) and g.secondary == [(power, km)]
    assert [e for _, e in g.contacts] == [c_no, c_nc] and not g.dup
    assert not idx.is_bom_device(coil) and idx.is_bom_device(km) and idx.is_secondary(km)
    # bez cívky je stykač hlavní přístroj (hostitel i položka výkazu), kontakty patří jemu
    ctl.elements.remove(coil)
    g = X.DeviceIndex.build(p).group_of(km)
    assert g.host == (power, km) and g.device == (power, km) and g.secondary == []
    # samotná cívka je položkou výkazu
    q = Project()
    lone = Element("ctl.coil", attrs={"ref": "K5"})
    q.sheets[0].elements.append(lone)
    assert X.DeviceIndex.build(q).is_bom_device(lone)


def test_contactor_with_coil_regression(lib):
    p, power, ctl, km, coil, c_no, c_nc = _km_project()
    fs = check_project(p, lib, standard_paper="A4")
    assert not _codes(fs, "dup_ref") and not _codes(fs, "contact_ambiguous")
    assert coil_of(p, c_no) == (ctl, coil) and coil_of(p, c_nc, ctl)[1] is coil
    assert [e for _, e in coil_candidates(p, c_no)] == [coil]
    assert {e.id for _, e in contacts_of(p, "K1", coil)} == {c_no.id, c_nc.id} == \
           {e.id for _, e in contacts_of(p, "K1", km)}
    # zrcadlo cívky: tři silové řádky (póly stykače) + NO + NC
    km_ref = X.place_ref(p, ctl, coil, power, km)
    assert km_ref == position_ref(p, power, km.x, km.y)
    mirror = contact_mirror(p, coil)
    assert [t for t, _ in mirror] == ["1/2", "3/4", "5/6", "13/14", "21/22"]
    assert [r for t, r in mirror if t in ("1/2", "3/4", "5/6")] == [km_ref] * 3
    table = X.contact_table(p, ctl, coil)
    assert list(table.columns) == ["power", "no", "nc"] and len(table.columns["power"]) == 3
    assert X.contact_table(p, power, km).empty                 # stykač není hostitel, když existuje cívka
    # stykač i kontakty odkazují na cívku, cívka sama text odkazu nemá (kreslí se zrcadlo)
    coil_ref = position_ref(p, ctl, coil.x, coil.y)
    assert element_xref(p, power, km) == "→ " + coil_ref
    assert element_xref(p, ctl, c_no) == "→ " + coil_ref
    assert element_xref(p, ctl, coil) == ""
    # výkazy: jeden K1 (stykač) s kontakty
    head, rows = reports.device_list(p, lib)
    k1 = [r for r in rows if r[0] == "K1"]
    assert len(k1) == 1 and k1[0][head.index("Kontakty")] == "1/2, 3/4, 5/6, 13/14, 21/22"
    assert k1[0][head.index("Přístroj")] == "Stykač"
    _, bom = reports.bom(p, lib)
    assert sum(1 for r in bom if "K1" in r[6].split(", ")) == 1
    assert [e.symbol_id for e in reports.devices(p, lib)] == ["fve.contactor"]
    assert [r[0] for r in reports.labels(p, lib)[1]].count("K1") == 1        # jen stykač: kontakty ani cívka štítek nemají
    # kontrola artiklu nehlásí cívku (artikl má stykač)
    assert not [f for f in _codes(fs, "no_article") if f.target_id == coil.id]


def test_contactor_coil_layout_and_thermal():
    from envocad.library.templates import _place_sequential
    from envocad.model.thermal import temperature_rise
    p = Project()
    blk = Element("fve.switchboard", attrs={"ref": "RH"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    km = Element("fve.contactor", attrs={"ref": "K1", "modules": "3", "p_loss_w": "4", "poles": "3"})
    coil = Element("ctl.coil", attrs={"ref": "K1", "modules": "3", "p_loss_w": "50"})
    sb.elements += [km, coil]
    _place_sequential(sb, [km, coil])
    assert sb.layout.placement(km.id) is not None and sb.layout.placement(coil.id) is None
    sb.layout.set_placement(coil.id, 0, 10)                      # i ručně umístěná cívka se nezapočítá
    assert sb.layout.used_modules(sb) == 3 and sb.layout.used_modules(sb, p) == 3
    assert [e.id for e in sb.layout.devices(sb)] == [km.id]
    r = temperature_rise(sb, rdf=1.0, project=p)
    assert r.p_devices_w == pytest.approx(4.0)
    assert temperature_rise(sb, rdf=1.0).p_devices_w == pytest.approx(4.0)
    sb.elements.remove(km)                                       # cívka bez stykače se počítá
    assert sb.layout.used_modules(sb) == 3
    assert temperature_rise(sb, rdf=1.0).p_devices_w == pytest.approx(50.0)


def test_coil_on_switchboard_with_contactor_on_other_sheet(lib):
    """Regrese: cívka K1 na listu rozvaděče +RH a stykač K1 na silovém listu se stejným umístěním (jeden přístroj).
    Cívka zůstává položkou listu rozvaděče (rozložení, teplo, výkaz/štítky listu); celoprojektový výkaz ji nemá."""
    from envocad.library.templates import _place_sequential
    from envocad.model.designation import scope_key
    from envocad.model.thermal import temperature_rise
    p = Project()
    blk = Element("fve.switchboard", attrs={"ref": "RH"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    coil = Element("ctl.coil", attrs={"ref": "K1", "modules": "3", "p_loss_w": "50"})
    sb.elements.append(coil)
    power = Sheet(name="Silové RH", loc="RH")
    km = Element("fve.contactor", attrs={"ref": "K1", "modules": "3", "p_loss_w": "4", "poles": "3"})
    power.elements.append(km)
    p.sheets.append(power)
    assert scope_key(sb, coil) == scope_key(power, km)
    assert X.DeviceIndex.build(p).group_of(coil).device[1] is km
    _place_sequential(sb, [coil])
    assert sb.layout.placement(coil.id) is not None
    assert [e.id for e in sb.layout.devices(sb, p)] == [coil.id] == [e.id for e in sb.layout.devices(sb)]
    assert sb.layout.used_modules(sb, p) == 3 == sb.layout.used_modules(sb)
    assert temperature_rise(sb, rdf=1.0, project=p).p_devices_w == pytest.approx(50.0)
    assert temperature_rise(sb, rdf=1.0).p_devices_w == pytest.approx(50.0)
    assert [e.id for e in reports.devices(p, lib, sb)] == [coil.id]
    assert [r[0] for r in reports.device_list(p, lib, sb)[1]] == [r[0] for r in reports.labels(p, lib, sb)[1]]
    assert len(reports.labels(p, lib, sb)[1]) == 1
    # celý projekt: jedna položka K1 (stykač), cívka ne
    assert [e.id for e in reports.devices(p, lib) if e.ref == "K1"] == [km.id]
    assert sum(1 for r in reports.labels(p, lib)[1] if r[0].endswith("K1")) == 1
    # stykač na stejném listu → cívka se vynechá i z položek listu
    power.elements.remove(km)
    sb.elements.append(km)
    sb.layout.set_placement(km.id, 1, 0)
    assert [e.id for e in sb.layout.devices(sb, p)] == [km.id]
    assert temperature_rise(sb, rdf=1.0, project=p).p_devices_w == pytest.approx(4.0)
    assert [e.id for e in reports.devices(p, lib, sb)] == [km.id]


def test_docx_routine_test_counts_coil_with_contactor_elsewhere(lib, tmp_path):
    pytest.importorskip("docx")
    from docx import Document

    from envocad.export.docx_export import export_routine_test_docx
    p = Project()
    blk = Element("fve.switchboard", attrs={"ref": "RH"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    coil = Element("ctl.coil", attrs={"ref": "K1", "modules": "3"})
    sb.elements.append(coil)
    sb.layout.set_placement(coil.id, 0, 0)
    p.sheets.append(Sheet(name="Silové RH", loc="RH", elements=[Element("fve.contactor", attrs={"ref": "K1"})]))
    out = tmp_path / "kusova.docx"
    export_routine_test_docx(p, lib, sb, out)
    text = "\n".join(c.text for t in Document(str(out)).tables for r in t.rows for c in r.cells)
    assert "obsazeno 3 M" in text


def test_dup_ref_rules(lib):
    def dups(*elements):
        p = Project()
        p.sheets[0].elements += list(elements)
        return {f.target_id for f in _codes(check_project(p, lib, standard_paper="A4"), "dup_ref")}

    def el(sym, **a):
        return Element(sym, attrs={"ref": "K1", **a})

    assert not dups(el("ctl.coil"), el("fve.contactor"))
    c1, c2 = el("ctl.coil"), el("ctl.coil")
    assert dups(c1, c2) == {c1.id, c2.id}
    a, b, c = el("ctl.coil"), el("fve.contactor"), el("fve.contactor")
    assert dups(a, b, c) == {a.id, b.id, c.id}
    a, b = el("ctl.coil"), el("fve.breaker_mcb")
    assert dups(a, b) == {a.id, b.id}
    a, b = el("fve.contactor"), el("fve.breaker_mcb")
    assert dups(a, b) == {a.id, b.id}
    # různé umístění = různé přístroje
    assert not dups(el("ctl.coil"), el("ctl.coil", loc="RH"))
    # přerušovací body se stejným označením tvoří skupinu (řetěz/hvězda), nejsou duplicitou
    assert not dups(Element("fve.interrupt", attrs={"ref": "L1"}), Element("fve.interrupt", 50, attrs={"ref": "L1"}))
    # prvek a vodič se stejným označením v jednom prostoru (list rozvaděče)
    from envocad.model.project import Wire, WireEnd
    p = Project()
    blk = Element("fve.switchboard", attrs={"ref": "RH"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    f1, f2, coil = Element("fve.breaker_mcb", attrs={"ref": "F1"}), Element("fve.breaker_mcb", 50, attrs={"ref": "F2"}), \
        el("ctl.coil")
    sb.elements += [f1, f2, coil]
    w = Wire(WireEnd(f1.id, "2"), WireEnd(f2.id, "1"), attrs={"ref": "K1"})
    sb.wires.append(w)
    assert {f.target_id for f in _codes(check_project(p, lib, standard_paper="A4"), "dup_ref")} == {coil.id, w.id}


def test_interrupt_ref_collides_with_device_or_wire(lib):
    """Regrese: přerušovací body se stejným ref jako přístroj (F1) nebo vodič (W1) v prostoru → dup_ref; body
    mezi sebou (dvojice L1) duplicitou nejsou."""
    from envocad.model.project import Wire, WireEnd
    p = Project()
    blk = Element("fve.switchboard", attrs={"ref": "RH"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    f1, f2 = Element("fve.breaker_mcb", attrs={"ref": "F1"}), Element("fve.breaker_mcb", 50, attrs={"ref": "F2"})
    i1, i2 = Element("fve.interrupt", 100, attrs={"ref": "F1"}), Element("fve.interrupt", 150, attrs={"ref": "W1"})
    l1a, l1b = Element("fve.interrupt", 200, attrs={"ref": "L1"}), Element("fve.interrupt", 250, attrs={"ref": "L1"})
    sb.elements += [f1, f2, i1, i2, l1a, l1b]
    w = Wire(WireEnd(f1.id, "2"), WireEnd(f2.id, "1"), attrs={"ref": "W1"})
    sb.wires.append(w)
    dup = _codes(check_project(p, lib, standard_paper="A4"), "dup_ref")
    assert {f.target_id for f in dup} == {f1.id, i1.id, i2.id, w.id}
    assert all(f.severity == ERROR for f in dup)
    # jiný prostor (list bez umístění rozvaděče) → bez kolize
    i1.attrs["loc"] = "RDC1"
    assert i1.id not in {f.target_id for f in _codes(check_project(p, lib, standard_paper="A4"), "dup_ref")}


# ---- odkaz na místo --------------------------------------------------------------------------------------------
def test_place_ref_aspects():
    p = Project(sheets=[Sheet(name="A", func="AC", loc="RDC1"), Sheet(name="B", func="AC", loc="RH")])
    a, b = Element("ctl.contact_no", 100, 100), Element("ctl.coil", 200, 150)
    p.sheets[0].elements.append(a)
    p.sheets[1].elements.append(b)
    pos = position_ref(p, p.sheets[1], 200, 150)
    assert X.place_ref(p, p.sheets[0], a, p.sheets[1], b) == "+RH" + pos
    b.attrs["func"] = "DC"
    assert X.place_ref(p, p.sheets[0], a, p.sheets[1], b) == "=DC+RH" + pos
    assert X.place_ref(p, p.sheets[1], b, p.sheets[1], b) == pos
    # anonymní rozvaděč (bez umístění) → jen „/n.XY“
    blk = Element("fve.switchboard", attrs={"ref": ""})
    p.sheets[0].elements.append(blk)
    sb = Sheet(name="Rozvaděč", kind="switchboard", parent_element_id=blk.id)
    p.sheets.append(sb)
    c = Element("ctl.coil", 50, 50)
    sb.elements.append(c)
    assert X.place_ref(p, p.sheets[0], a, sb, c) == position_ref(p, sb, 50, 50)


# ---- zrcadlo kontaktů ------------------------------------------------------------------------------------------
def test_contact_table_reserves_and_order():
    p = Project()
    s = p.sheets[0]
    coil = Element("ctl.coil", 100, 200, attrs={"ref": "K1", "contacts": "1/2 3/4 5/6 13/14 21/22 33/34"})
    c1 = Element("ctl.contact_no", 300, 100, attrs={"ref": "K1", "terminals": "33/34"})
    c2 = Element("ctl.contact_power", 200, 100, attrs={"ref": "K1", "poles": "1"})
    s.elements += [coil, c1, c2]
    t = X.contact_table(p, s, coil)
    assert [(r.pair, bool(r.ref)) for r in t.columns["power"]] == [("1/2", True), ("3/4", False), ("5/6", False)]
    assert [(r.pair, bool(r.ref)) for r in t.columns["no"]] == [("13/14", False), ("33/34", True)]
    assert [(r.pair, r.ref) for r in t.columns["nc"]] == [("21/22", "")]
    row = t.columns["no"][1]
    assert row.element_id == c1.id and row.sheet_id == s.id and row.text == f"33/34 {row.ref}"
    assert contact_mirror(p, coil) == [("1/2", position_ref(p, s, 200, 100)), ("33/34", position_ref(p, s, 300, 100))]
    # zrcadlo dostane i jistič s pomocným kontaktem a přístroj jen se zadaným obrazem
    q = Project()
    f1 = Element("fve.breaker_mcb", 100, 200, attrs={"ref": "F1"})
    f2 = Element("fve.breaker_mcb", 200, 200, attrs={"ref": "F2", "contacts": "NO:13/14"})
    q.sheets[0].elements += [f1, f2, Element("ctl.contact_no", 50, 50, attrs={"ref": "F1"})]
    assert not X.contact_table(q, q.sheets[0], f1).empty
    assert [r.pair for r in X.contact_table(q, q.sheets[0], f2).rows()] == ["13/14"]
    assert X.contact_table(q, q.sheets[0], Element("ctl.coil", attrs={"ref": "X"})).empty


def test_mirror_geometry_layout(lib):
    p = Project()
    s = p.sheets[0]
    coil = Element("ctl.coil", 100, 200, attrs={"ref": "K1"})
    s.elements += [coil, Element("ctl.contact_no", 300, 100, attrs={"ref": "K1"}),
                   Element("ctl.contact_nc", 300, 150, attrs={"ref": "K1"}),
                   Element("ctl.contact_power", 250, 100, attrs={"ref": "K1", "poles": "3"})]
    sym = lib.get_symbol("ctl.coil")
    g = X.mirror_geometry(coil, sym, X.contact_table(p, s, coil))
    x1, y1, x2, y2 = g.bounds
    top = y2
    assert top == pytest.approx(200 - 10)                          # spodek cívky −7,5 → −2,5 mm → na mřížku
    axis = [ln for ln in g.lines if ln[0] == ln[2] == 100]
    assert axis and axis[0][1] == pytest.approx(top) and axis[0][3] == pytest.approx(y1)
    assert x1 < 100 < x2 and not hasattr(g, "rects") and len(g.boxes) == len(g.texts) == 5
    assert y1 == pytest.approx(top - X.HEADER_H - X.ROW_PITCH * 3)
    left = [t for t in g.texts if t[0] < 100]
    right = [t for t in g.texts if t[0] > 100]
    assert {t[2].split()[0] for t in right} == {"21/22"}
    assert {t[2].split()[0] for t in left} == {"1/2", "3/4", "5/6", "13/14"}
    # NO u osy, silové vlevo od něj; texty nezasahují osu
    no_x = next(t[0] for t in g.texts if t[2].startswith("13/14"))
    pw_x = next(t[0] for t in g.texts if t[2].startswith("1/2"))
    assert pw_x < no_x < 100
    assert all(b[2] < 100 - 0.2 or b[0] > 100 + 0.2 for b in g.boxes)
    for x in (b[0] for b in g.boxes):
        assert x == pytest.approx(round(x - 1.0, 6) // 2.5 * 2.5 + 1.0)   # sloupce na mřížce
    # prázdné zrcadlo = žádná geometrie
    assert X.mirror_geometry(coil, sym, X.ContactMirror(coil.id)).empty


def test_layout_reserves_mirror(lib):
    from envocad.model.textlayout import boxes_overlap, compute_layout, text_overlaps
    p = Project()
    s = p.sheets[0]
    coil = Element("ctl.coil", 100, 200, attrs={"ref": "K1", "desc": "NS ochrana"})
    s.elements += [coil, Element("ctl.contact_no", 300, 100, attrs={"ref": "K1"}),
                   Element("ctl.contact_nc", 300, 150, attrs={"ref": "K1"})]
    lay = compute_layout(p, s, lib)
    assert set(lay.mirrors) == {coil.id}
    m = lay.mirrors[coil.id]
    for e in s.elements:
        for b in lay.elements[e.id].boxes:
            assert not any(boxes_overlap(b, mb) for mb in m.boxes)
    assert not text_overlaps(p, s, lib, lay)
    # cizí značka v místě zrcadla → překryv hlášený na hostiteli
    f = Element("fve.breaker_mcb", 95, 180, attrs={"ref": "F1"})
    s.elements.append(f)
    hits = text_overlaps(p, s, lib)
    assert any(a == coil.id and "K1" in t for a, _, t in hits)
    # mirror="0" zrcadlo potlačí
    s.elements.remove(f)
    coil.attrs["mirror"] = "0"
    assert compute_layout(p, s, lib).mirrors == {}


def test_text_overlaps_mirror_lines_and_host_label(lib):
    """Regrese: cizí popisek přes čáru tabulky zrcadla se hlásí; popisek hostitele přes vlastní zrcadlo (texty
    i čáry) se hlásí; zrcadlo vs. vlastní značka a vlastní čáry tabulky se nehlásí."""
    from envocad.model.textlayout import ElementLabel, compute_layout, text_overlaps
    p = Project()
    s = p.sheets[0]
    coil = Element("ctl.coil", 100, 200, attrs={"ref": "K1"})
    f1 = Element("fve.breaker_mcb", 300, 50, attrs={"ref": "F1"})
    s.elements += [coil, f1, Element("ctl.contact_no", 300, 150, attrs={"ref": "K1"}),
                   Element("ctl.contact_nc", 350, 150, attrs={"ref": "K1"})]
    lay = compute_layout(p, s, lib)
    assert not text_overlaps(p, s, lib, lay)
    m = lay.mirrors[coil.id]
    x0, top = coil.x, m.bounds[3]
    # popisek F1 v hlavičce tabulky přes osu (čáry), mimo texty zrcadla
    head_box = (x0 - 1.0, top - 2.0, x0 + 1.0, top - 1.0)
    assert not any(b[3] > head_box[1] for b in m.boxes)
    lay.elements[f1.id] = ElementLabel(x0, top, "center", boxes=[head_box])
    hits = text_overlaps(p, s, lib, lay)
    assert (f1.id, coil.id, "text F1 přes zrcadlo kontaktů K1") in hits
    # popisek hostitele přes texty vlastního zrcadla
    lay = compute_layout(p, s, lib)
    lay.elements[coil.id] = ElementLabel(0, 0, "left", boxes=[lay.mirrors[coil.id].boxes[0]])
    hits = text_overlaps(p, s, lib, lay)
    assert (coil.id, coil.id, "text K1 přes zrcadlo kontaktů K1") in hits
    assert (coil.id, coil.id, "text K1 přes vlastní zrcadlo kontaktů") not in hits     # box textu nekříží osu
    # popisek hostitele přes čáry vlastního zrcadla
    lay = compute_layout(p, s, lib)
    lay.elements[coil.id] = ElementLabel(0, 0, "left", boxes=[head_box])
    assert (coil.id, coil.id, "text K1 přes vlastní zrcadlo kontaktů") in text_overlaps(p, s, lib, lay)


def test_is_mirror_host():
    p = Project()
    s = p.sheets[0]
    coil = Element("ctl.coil", 100, 200, attrs={"ref": "K1"})
    km = Element("fve.contactor", 50, 50, attrs={"ref": "K1"})
    c = Element("ctl.contact_no", 300, 100, attrs={"ref": "K1"})
    f1 = Element("fve.breaker_mcb", 200, 200, attrs={"ref": "F1"})
    s.elements += [coil, km, c, f1]
    assert X.is_mirror_host(p, s, coil)
    assert not X.is_mirror_host(p, s, km) and not X.is_mirror_host(p, s, c) and not X.is_mirror_host(p, s, f1)
    coil.attrs["mirror"] = "0"                                   # potlačené zrcadlo – hostitelem zůstává
    assert X.is_mirror_host(p, s, coil)
    f1.attrs["contacts"] = "13/14"
    assert X.is_mirror_host(p, s, f1)


def test_dxf_mirror_in_texts_layer(lib, tmp_path):
    from envocad.export.dxf_export import export_sheet_dxf
    p = Project()
    s = p.sheets[0]
    coil = Element("ctl.coil", 100, 200, attrs={"ref": "K1"})
    s.elements += [coil, Element("ctl.contact_no", 300, 100, attrs={"ref": "K1"})]
    export_sheet_dxf(p, s, lib, tmp_path / "zrcadlo.dxf")
    msp = ezdxf.readfile(tmp_path / "zrcadlo.dxf").modelspace()
    texts = [t.dxf.text for t in msp.query("TEXT") if t.dxf.layer == "TEXTY"]
    assert f"13/14 {position_ref(p, s, 300, 100)}" in texts
    m = X.sheet_mirrors(p, s, lib)[coil.id]
    assert len([ln for ln in msp.query("LINE") if ln.dxf.layer == "TEXTY"]) == len(m.lines)


# ---- kontroly kontaktů -----------------------------------------------------------------------------------------
def test_contact_checks(lib):
    p = Project()
    s = p.sheets[0]
    coil = Element("ctl.coil", 100, 200, attrs={"ref": "K1"})
    a = Element("ctl.contact_no", 200, 100, attrs={"ref": "K1"})
    b = Element("ctl.contact_no", 250, 100, attrs={"ref": "K1"})          # druhé výchozí 13/14
    s.elements += [coil, a, b]
    fs = check_project(p, lib, standard_paper="A4")
    dup = _codes(fs, "contact_dup")
    assert len(dup) == 1 and dup[0].target_id == b.id and dup[0].severity == WARNING
    assert dup[0].text == "K1: svorky 13/14 jsou u více kontaktů"
    assert not _codes(fs, "contact_count") and not _codes(fs, "contact_unknown")      # obraz nezadán
    b.attrs["terminals"] = "23/24"
    coil.attrs["contacts"] = "13/14 21/22"
    fs = check_project(p, lib, standard_paper="A4")
    assert not _codes(fs, "contact_dup")
    unk = _codes(fs, "contact_unknown")
    assert len(unk) == 1 and unk[0].target_id == b.id and unk[0].text == "Kontakt 23/24 není v kontaktním obrazu K1"
    cnt = _codes(fs, "contact_count")
    assert len(cnt) == 1 and cnt[0].text == "K1: použity 2 spínací kontakty, kontaktní obraz má 1" and cnt[0].target_id == coil.id
    coil.attrs["contacts"] = "13/14 23/24 xx/yy"
    fs = check_project(p, lib, standard_paper="A4")
    syn = _codes(fs, "contact_image_syntax")
    assert len(syn) == 1 and "xx/yy" in syn[0].text and syn[0].target_id == coil.id
    assert not _codes(fs, "contact_count") and not _codes(fs, "contact_unknown")
    # obraz ze stykače (položka výkazu) má přednost; póly stykače se počítají jako silové
    km = Element("fve.contactor", 50, 50, attrs={"ref": "K1", "poles": "3", "contacts": "1/2 3/4 13/14 23/24"})
    s.elements.append(km)
    cnt = _codes(check_project(p, lib, standard_paper="A4"), "contact_count")
    assert [f.text for f in cnt] == ["K1: použity 3 silové kontakty, kontaktní obraz má 2"]


def test_contact_count_czech_words():
    assert X.count_words(1, "nc") == "použit 1 rozpínací kontakt"
    assert X.count_words(4, "power") == "použity 4 silové kontakty"
    assert X.count_words(5, "no") == "použito 5 spínacích kontaktů"
    assert X.count_words(12, "power") == "použito 12 silových kontaktů"
    assert set(X.KIND_WORD) == set(X.COLUMN_ORDER)


def test_contact_alone_and_ambiguous_via_index(lib):
    p = Project(sheets=[Sheet(name="A", loc="RDC1"), Sheet(name="B", loc="RH"), Sheet(name="C")])
    p.sheets[0].elements.append(Element("ctl.coil", attrs={"ref": "K1"}))
    p.sheets[1].elements.append(Element("ctl.coil", attrs={"ref": "K1"}))
    c = Element("ctl.contact_no", attrs={"ref": "K1"})
    lone = Element("ctl.contact_no", 20, attrs={"ref": "K7"})
    p.sheets[2].elements += [c, lone]
    fs = check_project(p, lib, standard_paper="A4")
    assert [f.target_id for f in _codes(fs, "contact_ambiguous")] == [c.id]
    assert [f.target_id for f in _codes(fs, "contact_alone")] == [lone.id]
    # cívka + stykač v jednom prostoru nejsou dvě cívky
    p.sheets[1].elements.append(Element("fve.contactor", attrs={"ref": "K1"}))
    c.attrs["loc"] = "RH"
    assert not _codes(check_project(p, lib, standard_paper="A4"), "contact_ambiguous")


def test_next_contact_pair():
    p = Project()
    s = p.sheets[0]
    coil = Element("ctl.coil", attrs={"ref": "K1"})
    s.elements.append(coil)
    g = X.DeviceIndex.build(p).group_of(coil)
    assert X.next_contact_pair(None, "no") == "13/14" and X.next_contact_pair(g, "nc") == "21/22"
    assert X.next_contact_pair(g, "power") == "1/2"
    s.elements += [Element("ctl.contact_no", attrs={"ref": "K1"}), Element("ctl.contact_nc", attrs={"ref": "K1"})]
    g = X.DeviceIndex.build(p).group_of(coil)
    assert X.next_contact_pair(g, "no") == "33/34" and X.next_contact_pair(g, "nc") == "31/32"
    coil.attrs["contacts"] = "13/14 21/22 43/44 NO:DO1"
    g = X.DeviceIndex.build(p).group_of(coil)
    assert X.next_contact_pair(g, "no") == "43/44"


# ---- přerušovací body ------------------------------------------------------------------------------------------
def _interrupt_project(n: int):
    p = Project(sheets=[Sheet(name=f"L{i + 1}") for i in range(n)])
    pts = []
    for i, s in enumerate(p.sheets):
        e = Element("fve.interrupt", 100 + 10 * i, 150, attrs={"ref": "L1"})
        s.elements.append(e)
        pts.append(e)
    return p, pts


def _pos(p, i, e):
    return position_ref(p, p.sheets[i], e.x, e.y)


def test_interrupt_pair_and_chain(lib):
    p, (a, b) = _interrupt_project(2)
    assert X.interrupt_link(p, p.sheets[0], a).mode == "pair"
    assert element_xref(p, p.sheets[0], a) == "→ " + _pos(p, 1, b)
    assert element_xref(p, p.sheets[1], b) == "→ " + _pos(p, 0, a)
    p, (a, b, c) = _interrupt_project(3)
    assert X.interrupt_link(p, p.sheets[1], b).mode == "chain"
    assert element_xref(p, p.sheets[0], a) == "→ " + _pos(p, 1, b)
    assert element_xref(p, p.sheets[1], b) == f"← {_pos(p, 0, a)}\n→ {_pos(p, 2, c)}"
    assert element_xref(p, p.sheets[2], c) == "← " + _pos(p, 1, b)
    assert interrupt_partner(p, b)[1] is c and interrupt_partner(p, c)[1] is b
    assert not _codes(check_project(p, lib, standard_paper="A4"), "interrupt_alone")
    # řazení v listu: x, pak −y (shora dolů)
    q = Project()
    e1, e2, e3 = (Element("fve.interrupt", 50, 100, attrs={"ref": "N"}), Element("fve.interrupt", 20, 100, attrs={"ref": "N"}),
                  Element("fve.interrupt", 20, 200, attrs={"ref": "N"}))
    q.sheets[0].elements += [e1, e2, e3]
    assert [e for _, e in X.interrupt_groups(q)["N"]] == [e3, e2, e1]


def test_interrupt_star(lib):
    p, pts = _interrupt_project(6)
    src = pts[2]
    src.attrs["star_source"] = "1"
    targets = [x for x in pts if x is not src]
    link = X.interrupt_link(p, p.sheets[2], src)
    assert link.mode == "star_source" and [e for _, e in link.targets] == targets
    refs = [_pos(p, i, e) for i, e in enumerate(pts) if e is not src]
    assert element_xref(p, p.sheets[2], src) == f"→ {refs[0]}, {refs[1]}, {refs[2]},\n  {refs[3]}, {refs[4]}"
    assert element_xref(p, p.sheets[0], pts[0]) == "← " + _pos(p, 2, src)
    assert X.interrupt_link(p, p.sheets[5], pts[5]).mode == "star_target"
    assert interrupt_partner(p, pts[4])[1] is src and interrupt_partner(p, src)[1] is pts[0]
    assert not _codes(check_project(p, lib, standard_paper="A4"), "interrupt_star_multi")
    pts[4].attrs["star_source"] = "1"                         # druhý zdroj → varování, zdrojem zůstává první
    multi = _codes(check_project(p, lib, standard_paper="A4"), "interrupt_star_multi")
    assert [f.target_id for f in multi] == [pts[4].id] and multi[0].severity == WARNING
    assert X.interrupt_link(p, p.sheets[4], pts[4]).mode == "star_target"


def test_interrupt_pair_across_locations():
    """Dvojice přerušovacích bodů na listech s různým umístěním: odkaz do jiného umístění předřadí aspekty cíle
    (`→ +RH/2.D3`, jako EPLAN); stejné umístění → jen `/n.XY`."""
    p = Project(sheets=[Sheet(name="A", loc="RDC1"), Sheet(name="B", loc="RH")])
    a = Element("fve.interrupt", 100, 100, attrs={"ref": "L1"})
    b = Element("fve.interrupt", 200, 150, attrs={"ref": "L1"})
    p.sheets[0].elements.append(a)
    p.sheets[1].elements.append(b)
    assert X.interrupt_link(p, p.sheets[0], a).mode == "pair"
    assert element_xref(p, p.sheets[0], a) == "→ +RH" + _pos(p, 1, b)
    assert element_xref(p, p.sheets[1], b) == "→ +RDC1" + _pos(p, 0, a)
    p.sheets[1].loc = "RDC1"
    assert element_xref(p, p.sheets[0], a) == "→ " + _pos(p, 1, b)


def test_interrupt_alone(lib):
    p, (a,) = _interrupt_project(1)
    assert X.interrupt_link(p, p.sheets[0], a).mode == "alone"
    assert element_xref(p, p.sheets[0], a) == "→ ?" and interrupt_partner(p, a) is None
    assert _codes(check_project(p, lib, standard_paper="A4"), "interrupt_alone")
    a.attrs["ref"] = ""
    assert element_xref(p, p.sheets[0], a) == "→ ?"


# ---- knihovna a artikly ----------------------------------------------------------------------------------------
def test_library_attributes_and_component(lib, tmp_path):
    from envocad.library.components import PARAM_TO_ATTR, Component, validate
    for sid in ("ctl.coil", "fve.contactor"):
        a = next(x for x in lib.get_symbol(sid).attributes if x.key == "contacts")
        assert a.default == "" and not a.show
    assert any(x.key == "star_source" and x.default == "" for x in lib.get_symbol("fve.interrupt").attributes)
    assert PARAM_TO_ATTR["contacts"] == "contacts"
    comp = Component("eaton-dilm25", "Eaton", "DILM25-10", "Stykač", "contactor", "fve.contactor",
                     params={"contacts": "1/2 3/4 5/6 13/14"})
    e = Element("fve.contactor", attrs={"ref": "K1"})
    assert comp.apply_to(e)["contacts"] == "1/2 3/4 5/6 13/14"
    csv = tmp_path / "a.csv"
    csv.write_text("id;manufacturer;part_number;name;category;symbol_id;datasheet_url;source;contacts\n"
                   "x-1;X;1;Stykač;contactor;fve.contactor;;seed;1/2 3/4 13/14\n"
                   "x-2;X;2;Stykač;contactor;fve.contactor;;seed;1/2 99/98\n", encoding="utf-8")
    errs = validate(csv)
    assert len(errs) == 1 and "99/98" in errs[0] and "x-2" in errs[0]


# ---- ukázkové a generované projekty ----------------------------------------------------------------------------
NEW_CODES = {"contact_dup", "contact_count", "contact_unknown", "contact_image_syntax", "interrupt_star_multi",
             "contact_alone", "contact_ambiguous", "dup_ref"}


def test_example_generated_and_templates_clean(lib):
    from pathlib import Path

    from envocad.generate import build_project
    from envocad.library import templates as T
    p = Project.load(Path(__file__).parent.parent / "examples" / "ukazka_fve.ecp")
    fs = check_project(p, lib, standard_paper="A4")
    assert not [f for f in fs if f.severity == ERROR or f.code in NEW_CODES]
    spec = {"name": "X", "inverters": [{"ref": "T1", "p_ac": 25, "strings": [20, 20]}],
            "dc": {"route_boxes": 1, "tech_box": True, "disconnect": True}, "ac": {"distribution": "bus"}}
    g = build_project(spec)
    assert not [f.text for f in check_project(g, lib, standard_paper="A4") if f.code in NEW_CODES]
    for t in T.TEMPLATES:
        tp = Project()
        blk = Element("fve.switchboard", attrs={"ref": "RH"})
        tp.sheets[0].elements.append(blk)
        T.apply_template(tp, tp.create_switchboard_sheet(blk), t.id, {}, standard_paper="A4")
        assert not [f.text for f in check_project(tp, lib, standard_paper="A4") if f.code in NEW_CODES], t.id
