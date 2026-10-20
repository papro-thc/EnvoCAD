"""Rozdělení velkého JPS na listy (docs/design/dluhy_dxf_jps.md, bod B + rozhodnutí 10/2026): AC list jako přehled
první, za ním listy střídačů (A2); AC kabel přes pár přerušovacích bodů je jeden kabel (data jen u bloku AC
rozvaděče); `xref.through_interrupt` ve výkazech, výpočtech, vazbách přívodů a potenciálech; kontroly F7."""
import math
import re
from collections import Counter

import pytest

from envocad.export import reports
from envocad.generate import JPS_AC_SHEET_NAME, build_project, ref_ranges
from envocad.library.store import LibraryStore
from envocad.model import calc
from envocad.model.checks import AGGREGATED_INFO, WARNING, check_project
from envocad.model.frame import paper_exceeds
from envocad.model.potential import nets
from envocad.model.project import FORMAT_VERSION, INTERRUPT_SYMBOL, Element, Project, Sheet, Wire, WireEnd
from envocad.model.xref import (
    ThroughEnd,
    continuation_main,
    has_cable_data,
    interrupt_xref,
    is_blank_wire,
    is_continuation,
    split_cable_partner,
    through_interrupt,
)

INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


def spec(n, per=4, **kw):
    s = {"inverters": [{"ref": f"T{i + 1}", **INV, "strings": [20] * per} for i in range(n)]}
    s.update(kw)
    return s


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


@pytest.fixture(scope="module")
def big():
    """8 střídačů × 4 stringy – jeden list by měl vlastní formát 505 × 1615 mm."""
    return build_project(spec(8))


@pytest.fixture(scope="module")
def big_one_sheet():
    return build_project(spec(8, jps={"split": "none"}))


def jps_sheets(p):
    return [s for s in p.sheets if not s.is_switchboard]


def interrupts(s):
    return [e for e in s.elements if e.symbol_id == INTERRUPT_SYMBOL]


# ---- generátor: listy, pořadí, formát -------------------------------------------------------------------------
def test_big_jps_split_ac_first_then_inverter_sheets_a2(big):
    js = jps_sheets(big)
    assert len(js) == 5                                     # AC + 4 listy po 2 střídačích
    assert big.sheets[:5] == js                             # listy JPS před listy rozvaděčů
    ac = js[0]
    assert ac.name == JPS_AC_SHEET_NAME
    assert {e.symbol_id for e in ac.elements} == {"fve.switchboard", "fve.grid", "fve.earth", INTERRUPT_SYMBOL}
    assert sorted(e.ref for e in interrupts(ac)) == sorted(f"AC-T{i}" for i in range(1, 9))
    assert [s.name for s in js[1:]] == [f"Blokové schéma – T{i}, T{i + 1}" for i in (1, 3, 5, 7)]
    for s in js:
        assert (s.paper, s.width, s.height) == ("A2", 594.0, 420.0), s.name
    # každý střídač s celým DC řetězcem (stringy, DC rozvaděče) na jednom listu; na listu přerušení jeho AC kabelu
    for s in js[1:]:
        invs = [e.ref for e in s.elements if e.symbol_id == "fve.inverter"]
        assert sorted(e.ref for e in interrupts(s)) == sorted(f"AC-{r}" for r in invs)
        assert any(e.symbol_id == "fve.pv_string" for e in s.elements)
    checks = calc.check_strings(big)
    assert len(checks) == 32 and all(c.inverter for c in checks)   # string najde svůj střídač (stejný list)
    assert big.to_dict()["format_version"] == FORMAT_VERSION


def test_small_projects_stay_on_one_sheet():
    for n in (1, 2):
        p = build_project(spec(n))
        js = jps_sheets(p)
        assert len(js) == 1 and js[0].name == "Blokové schéma" and js[0].paper in ("A3", "A2")
        assert not interrupts(js[0])
    # jeden střídač s mnoha stringy se nedělí (DC řetězec zůstává na jednom listu, větší formát)
    p = build_project(spec(1, per=12))
    assert len(jps_sheets(p)) == 1 and paper_exceeds(p.sheets[0].paper, "A2")


def test_split_none_and_limits(big_one_sheet):
    assert len(jps_sheets(big_one_sheet)) == 1 and big_one_sheet.sheets[0].paper == "vlastní"
    # limit ze specifikace: 4 střídače se vejdou na A1 → bez dělení
    p = build_project(spec(4, jps={"max_paper": "A1"}))
    assert len(jps_sheets(p)) == 1 and p.sheets[0].paper == "A1"
    # 3 střídače přesahují A2 → dělí se (výchozí standard)
    assert len(jps_sheets(build_project(spec(3)))) == 3


def test_limit_from_company_standard():
    from envocad.settings import load_settings, save_settings
    st = load_settings()
    st["standard"]["jps_max_paper"] = "A0"
    save_settings(st)
    p = build_project(spec(6))                       # A0 – v limitu
    assert len(jps_sheets(p)) == 1 and p.sheets[0].paper == "A0"


def test_paper_exceeds():
    assert paper_exceeds("A1", "A2") and paper_exceeds("vlastní", "A0") and paper_exceeds("A0", "A1")
    assert not paper_exceeds("A2", "A2") and not paper_exceeds("A3", "A2")
    assert paper_exceeds("A1", "nesmysl") and not paper_exceeds("A2", "nesmysl")   # neznámý limit = A2


# ---- kabel jen jednou ----------------------------------------------------------------------------------------
def test_ac_cable_once_data_on_switchboard_side(big):
    ac = big.sheets[0]
    blk = next(e for e in ac.elements if e.symbol_id == "fve.switchboard")
    for s in jps_sheets(big)[1:]:
        for i in interrupts(s):
            ws = [w for w in s.wires if w.touches(i.id)]
            assert len(ws) == 1 and not has_cable_data(ws[0]) and not ws[0].attrs.get("cable_id")
            assert is_continuation(big, s, ws[0])
    for i in interrupts(ac):
        (w,) = [w for w in ac.wires if w.touches(i.id)]
        assert w.attrs["ref"] and w.attrs["cable"] == "CYKY-J 5x16" and w.b.element_id == blk.id
        assert not is_continuation(big, ac, w)
    n_ref = sum(1 for s in jps_sheets(big) for w in s.wires if w.attrs.get("ref"))
    assert len(big.cables) == n_ref


def test_reports_same_as_one_sheet(big, big_one_sheet, lib):
    """Seznam kabelů, kabelový plán, kusovník a výpočet kabelů jsou stejné jako u nerozděleného JPS (kabel se
    nezdvojí, „Odkud“ = T1:AC) – liší se jen sloupce List a odkaz na místo."""
    _head, rows = reports.cables(big, lib)
    refs = [r[0] for r in rows]
    assert len(refs) == len(set(refs)) == len(big.cables)
    w13 = next(r for r in rows if r[1] == "T1:AC")
    assert w13[2] == "+RFVE.AC-X1" and w13[3] == "CYKY-J 5x16" and w13[9] == JPS_AC_SHEET_NAME

    def strip(rows, drop):
        return sorted(tuple(c for k, c in enumerate(r) if k not in drop) for r in rows)
    one = reports.cables(big_one_sheet, lib)[1]
    assert strip(rows, {8, 9}) == strip(one, {8, 9})
    assert strip(reports.cable_plan(big, lib)[1], {10}) == strip(reports.cable_plan(big_one_sheet, lib)[1], {10})
    assert reports.bom(big, lib) == reports.bom(big_one_sheet, lib)
    assert not any("Přerušovací" in str(r[1]) for r in reports.bom(big, lib)[1])

    def jps_wiring(p):
        return strip([r for r in reports.wiring_list(p, lib)[1] if r[0].startswith("Blokové")], {0})
    assert jps_wiring(big) and jps_wiring(big) == jps_wiring(big_one_sheet)       # úsek pokračování nemá řádek „vodič“

    def cc(p):
        return sorted((c.ref, c.i_a, c.du_pct, tuple(c.issues)) for c in calc.check_cables(p))
    assert cc(big) == cc(big_one_sheet)
    w13c = next(c for c in calc.check_cables(big) if c.ref == "W13")
    assert w13c.i_a == round(25000 / (math.sqrt(3) * 400), 1)   # proud z P_AC střídače přes přerušení


# ---- křížové odkazy ------------------------------------------------------------------------------------------
def test_interrupt_xrefs_and_feed_link(big):
    js = jps_sheets(big)
    ac = js[0]
    for i in interrupts(ac):
        inv_sheet = next(s for s in js[1:] if any(e.ref == i.ref for e in interrupts(s)))
        no = big.sheets.index(inv_sheet) + 1
        assert re.fullmatch(rf"→ /{no}\.[A-H]\d", interrupt_xref(big, ac, i)), i.ref
        partner = next(e for e in interrupts(inv_sheet) if e.ref == i.ref)
        assert re.fullmatch(r"→ /1\.[A-H]\d", interrupt_xref(big, inv_sheet, partner))
    sb = next(s for s in big.sheets if s.is_switchboard and s.loc == "RFVE.AC")
    x1 = next(e for e in sb.elements if e.symbol_id == "sb.feed_in" and e.ref == "X1")
    assert re.fullmatch(r"W13 T1:AC /2\.[A-H]\d", x1.attrs["from"]) and x1.attrs["cable"] == "CYKY-J 5x16 16"


def test_potential_joins_inverter_with_switchboard_block(big, lib):
    ac = big.sheets[0]
    blk = next(e for e in ac.elements if e.symbol_id == "fve.switchboard")
    for n in nets(big, lib):
        if any(e.ref == "T1" and port == "AC" and c == "L1" for _, e, port, c in n.members):
            assert any(e is blk and port == "X1" and c == "L1" for _, e, port, c in n.members)
            assert not n.short_issue()
            break
    else:
        pytest.fail("síť T1:AC L1 nenalezena")


# ---- kontroly F7 ---------------------------------------------------------------------------------------------
def test_checks_no_new_findings_on_split_project(big, big_one_sheet, lib):
    f_split, f_one = check_project(big, lib), check_project(big_one_sheet, lib)
    codes = {f.code for f in f_split}
    assert not codes & {"interrupt_alone", "cable_split", "no_cable", "dup_ref", "text_overlap", "free_port",
                        "unconnected", "potential", "calc_cable", "calc_string"}
    # mimo souhrnné INFO (ty se slučují po listech – víc listů = víc souhrnných řádků) stejné nálezy jako jeden list
    def count(fs):
        return Counter((f.severity, f.code) for f in fs if f.code not in AGGREGATED_INFO)
    assert count(f_split) == count(f_one)


def test_cable_split_warning_when_both_segments_carry_cable(lib):
    p = build_project(spec(3))
    s = p.sheets[1]
    cont = next(w for w in s.wires if is_continuation(p, s, w))
    cont.attrs.update({"ref": "W999", "cable": "CYKY-J 5x16", "cross": "16"})
    found = [f for f in check_project(p, lib) if f.code == "cable_split"]
    assert len(found) == 1 and found[0].severity == WARNING   # jednou za dvojici úseků


# ---- through_interrupt a spol. na ručním projektu ------------------------------------------------------------
def _manual():
    """List A: T1:AC → přerušení „P“ (bez kabelu); list B: přerušení „P“ → F1:1 (kabel W1)."""
    p = Project(name="ruční")
    a = p.sheets[0]
    b = Sheet(name="B")
    p.sheets.append(b)
    t = Element("fve.inverter", 0, 0, attrs={"ref": "T1", "p_ac": "25", "phases": "3"})
    ia = Element(INTERRUPT_SYMBOL, 30, 0, attrs={"ref": "P"})
    ib = Element(INTERRUPT_SYMBOL, 0, 0, rotation=180, attrs={"ref": "P"})
    f = Element("fve.breaker_mcb", 50, 0, attrs={"ref": "F1", "in_": "50", "poles": "3"})
    cont = Wire(WireEnd(t.id, "AC"), WireEnd(ia.id, "1"), conductors=["L1", "L2", "L3", "N", "PE"], attrs={"ref": ""})
    main = Wire(WireEnd(ib.id, "1"), WireEnd(f.id, "1"), conductors=["L1", "L2", "L3", "N", "PE"],
                attrs={"ref": "W1", "cable": "CYKY-J 5x16", "cross": "16", "length": "30", "method": "B1"})
    a.elements += [t, ia]
    a.wires.append(cont)
    b.elements += [ib, f]
    b.wires.append(main)
    return p, a, b, t, ia, ib, f, cont, main


def test_through_interrupt_pair():
    p, a, b, t, ia, ib, _f, cont, main = _manual()
    hit = through_interrupt(p, b, ib, "1")
    assert hit == ThroughEnd(a, t, "AC", cont, "a") and hit[:3] == (a, t, "AC")
    assert through_interrupt(p, a, ia, "1") is None          # od pokračování se nesleduje
    assert through_interrupt(p, a, t, "AC") is None                     # není přerušovací bod
    assert continuation_main(p, a, cont) == (b, main)
    assert continuation_main(p, b, main) is None and split_cable_partner(p, b, main) is None
    cont.attrs["cable"] = "CYKY-J 5x16"
    assert split_cable_partner(p, a, cont) == (b, main) and split_cable_partner(p, b, main) == (a, cont)
    assert through_interrupt(p, b, ib) is None                          # oba úseky s daty – žádné pokračování


def test_cable_data_rule_ref_alone_is_not_data():
    """Pravidlo: data kabelu = typ/průřez; pokračování = úsek úplně prázdný (ani označení)."""
    w = Wire(WireEnd("a", "1"), WireEnd("b", "1"), attrs={"ref": "W7"})
    assert not has_cable_data(w) and not is_blank_wire(w)
    w.attrs = {"cross": "16"}
    assert has_cable_data(w) and not is_blank_wire(w)
    w.attrs = {"ref": ""}
    assert not has_cable_data(w) and is_blank_wire(w)


def test_through_interrupt_none_for_alone_chain_star_and_branching():
    p, a, b, _t, ia, ib, _f, cont, _main = _manual()
    ia.attrs["ref"] = "Q"                                               # osamělý
    assert through_interrupt(p, b, ib) is None and through_interrupt(p, a, ia) is None
    ia.attrs["ref"] = "P"
    third = Element(INTERRUPT_SYMBOL, 0, -50, attrs={"ref": "P"})       # řetěz ze 3 bodů
    b.elements.append(third)
    assert through_interrupt(p, b, ib) is None
    third.attrs["star_source"] = "1"                                    # hvězda
    assert through_interrupt(p, b, ib) is None
    b.elements.remove(third)
    g = Element("fve.breaker_mcb", 50, -30, attrs={"ref": "F2"})        # protějšek se 2 vodiči
    a.elements.append(g)
    a.wires.append(Wire(WireEnd(ia.id, "1"), WireEnd(g.id, "1")))
    assert through_interrupt(p, b, ib) is None
    assert not is_continuation(p, a, cont)          # odbočka na přerušení: úsek není jednoznačné pokračování


def test_manual_pair_reports_calc_potential_checks(lib):
    p, _a, b, t, _ia, _ib, f, _cont, main = _manual()
    row = next(r for r in reports.cables(p, lib)[1] if r[0] == "W1")
    assert row[1] == "T1:AC" and row[2] == "F1:1"
    assert [r[0] for r in reports.cables(p, lib)[1]] == ["W1"]
    plan = reports.cable_plan(p, lib)[1]
    assert len(plan) == 5 and all(r[6] == "T1:AC" for r in plan)
    assert not [r for r in reports.wiring_list(p, lib)[1] if r[1] == "vodič"]
    (cc,) = calc.check_cables(p)
    assert cc.i_a == 36.1 and "P_AC" in calc._source_current(p, b, main, None)[1]
    net = next(n for n in nets(p, lib) if any(e is t and c == "L1" for _, e, _, c in n.members))
    assert any(e is f and c == "L1" for _, e, _, c in net.members)
    codes = [x.code for x in check_project(p, lib)]
    assert "no_cable" not in codes and "cable_split" not in codes and "interrupt_alone" not in codes


def _all_reports(p, lib):
    return {name: fn(p, lib, None) for name, fn in reports.ALL_REPORTS}


def test_manual_auto_ref_on_both_segments_reports_as_before(lib):
    """Ruční projekt z GUI: každý vodič má automatické označení (W1, W2) – přes přerušení se nesleduje, výkazy jsou
    stejné jako na dbb6a72 (= jako s neprovázanými přerušeními), F7 nehlásí cable_split."""
    def make(chain):
        p, _a, b, _t, _ia, _ib, _f, cont, main = _manual()
        cont.attrs["ref"] = "W2"
        if chain:                          # řetěz – přes něj se nesleduje nikdy (chování před rozdělením JPS)
            b.elements.append(Element(INTERRUPT_SYMBOL, 0, -50, attrs={"ref": "P"}))
        return p, cont, main
    p, cont, _main = make(False)
    ref, _, _ = make(True)
    got, exp = _all_reports(p, lib), _all_reports(ref, lib)
    for name in got:
        assert got[name] == exp[name], name
    rows = {r[0]: r for r in got["Kabely"][1]}
    assert rows["W1"][1:3] == ["P:1", "F1:1"] and rows["W2"][1:3] == ["T1:AC", "P:1"]
    assert {r[1] for r in reports.wiring_list(p, lib)[1]} == {"W1", "W2"}
    codes = Counter(x.code for x in check_project(p, lib))
    assert codes["cable_split"] == 0 and codes["no_cable"] == 1          # W2 bez typu/průřezu – jako dřív
    # typ a průřez na obou úsecích → cable_split, texty zůstávají „P:1“
    cont.attrs.update({"cable": "CYKY-J 5x16", "cross": "16"})
    assert [x.code for x in check_project(p, lib)].count("cable_split") == 1
    rows = {r[0]: r for r in reports.cables(p, lib)[1]}
    assert rows["W1"][1] == "P:1" and rows["W2"][2] == "P:1"


def test_through_interrupt_terminal_number_from_continuation_wire(lib):
    """Konec za přerušením na svorce: číslo svorky z vodiče pokračování (X1:5…), ne port svorky (X1:1)."""
    p, a, b, _t, _ia, ib, _f, cont, _main = _manual()
    x1 = Element("sb.terminal_block", 0, 0, attrs={"ref": "X1", "terminal": "5"})
    a.elements.append(x1)
    cont.a = WireEnd(x1.id, "2")
    plan = reports.cable_plan(p, lib)[1]
    assert [r[6] for r in plan] == ["X1:5", "X1:6", "X1:7", "X1:8", "X1:9"]
    wl = reports.wiring_list(p, lib)[1]
    assert [r[5] for r in wl] == ["X1:5", "X1:6", "X1:7", "X1:8", "X1:9"]
    hit = through_interrupt(p, b, ib)
    assert hit.wire is cont and hit.side == "a" and hit.element is x1


def test_interrupt_chain_info(lib):
    p, _a, b, _t, _ia, _ib, _f, _cont, _main = _manual()
    third = Element(INTERRUPT_SYMBOL, 0, -50, attrs={"ref": "P"})
    b.elements.append(third)
    found = [x for x in check_project(p, lib) if x.code == "interrupt_chain"]
    assert len(found) == 1 and found[0].text == "Přerušení P je v 3 bodech (řetěz)" and found[0].severity == "info"
    third.attrs["star_source"] = "1"                                    # hvězda – žádné INFO
    assert not [x for x in check_project(p, lib) if x.code == "interrupt_chain"]
    b.elements.remove(third)                                            # dvojice – žádné INFO
    assert not [x for x in check_project(p, lib) if x.code == "interrupt_chain"]


def test_oversized_inverter_row_gets_bigger_paper():
    """Výjimka z limitu: řada jednoho střídače (12 stringů) se nevejde na A2 → její list má větší formát."""
    p = build_project(spec(3, per=12))
    js = jps_sheets(p)
    assert js[0].name == JPS_AC_SHEET_NAME and js[0].paper == "A2"
    assert [s.name for s in js[1:]] == [f"Blokové schéma – T{i}" for i in (1, 2, 3)]
    assert all(paper_exceeds(s.paper, "A2") and s.paper != "vlastní" for s in js[1:])


def test_sheet_name_ranges():
    assert ref_ranges(["T1", "T2"]) == "T1, T2"
    assert ref_ranges([f"T{i}" for i in range(1, 10)]) == "T1–T9"
    assert ref_ranges(["T1", "T2", "T3", "T5", "X", "T8", "T9", "T10"]) == "T1–T3, T5, X, T8–T10"
    p = build_project(spec(12, per=1))
    assert [s.name for s in jps_sheets(p)][1:] == ["Blokové schéma – T1–T9", "Blokové schéma – T10–T12"]


def test_split_project_roundtrip(big, lib):
    p2 = Project.from_dict(big.to_dict())
    assert [s.name for s in p2.sheets] == [s.name for s in big.sheets]
    assert reports.cables(p2, lib) == reports.cables(big, lib)


# ---- PDF dokumentace se všemi listy ---------------------------------------------------------------------------
def test_documentation_pdf_contains_all_jps_sheets_a2(lib, tmp_path):
    pytest.importorskip("PySide6")
    import pypdf

    from envocad.export.doc_pdf import DocBuilder, export_documentation_pdf
    p = build_project(spec(3))
    js = jps_sheets(p)
    assert len(js) == 3
    b = DocBuilder(p, lib)
    b.plan()
    sheet_items = [(i, d[0]) for i, (k, _n, d) in enumerate(b.pages) if k == "sheet" and d[1] == "schematic"]
    assert [s.id for _, s in sheet_items] == [s.id for s in js]          # AC list první, pak střídače
    out = tmp_path / "jps.pdf"
    n = export_documentation_pdf(p, lib, out)
    reader = pypdf.PdfReader(out)
    assert len(reader.pages) == n
    b2 = DocBuilder(p, lib)
    b2.export(tmp_path / "jps2.pdf")
    # dokumentace zmenší každý list JPS na stranu A3 (jako dřív jeden list) – každý list má vlastní stranu s obsahem
    texts = [reader.pages[b2.page_starts[i] - 1].extract_text() for i, _s in sheet_items]
    assert all(f"AC-T{k}" in texts[0] for k in (1, 2, 3)) and "RFVE.AC" in texts[0]
    assert "AC-T1" in texts[1] and "AC-T2" in texts[1] and "AC-T3" not in texts[1]
    assert "AC-T3" in texts[2] and "AC-T1" not in texts[2]


def test_dxf_export_each_jps_sheet(lib, tmp_path):
    import ezdxf

    from envocad.export.dxf_export import export_sheet_dxf
    p = build_project(spec(3))
    for k, s in enumerate(jps_sheets(p)):
        out = tmp_path / f"jps{k}.dxf"
        export_sheet_dxf(p, s, lib, out)
        texts = " ".join(e.dxf.text for e in ezdxf.readfile(out).modelspace().query("TEXT"))
        assert "AC-T" in texts, s.name


@pytest.mark.parametrize("mode", ["A3", "list"])
def test_documentation_pdf_jps_page_mode(lib, tmp_path, mode):
    """Volba listů JPS v PDF dokumentace: „A3“ = strana A3 (zmenšeno), „list“ = strana ve formátu listu (A2)."""
    pytest.importorskip("PySide6")
    import pypdf

    from envocad.export.doc_pdf import DocBuilder, export_documentation_pdf
    p = build_project(spec(3))
    out = tmp_path / f"jps_{mode}.pdf"
    export_documentation_pdf(p, lib, out, jps_page=mode)
    b = DocBuilder(p, lib, jps_page=mode)
    b.plan()
    b._count_pages()
    reader = pypdf.PdfReader(out)
    pt = 72 / 25.4
    for i, (kind, _n, data) in enumerate(b.pages):
        box = reader.pages[b.page_starts[i] - 1].mediabox
        size = (round(float(box.width) / pt), round(float(box.height) / pt))
        if kind == "sheet" and data[1] == "schematic":
            assert size == ((594, 420) if mode == "list" else (420, 297)), (data[0].name, size)
        elif kind in ("title", "toc", "table"):
            assert size == (420, 297)


def test_documentation_pdf_jps_page_default_from_standard(lib):
    pytest.importorskip("PySide6")
    from envocad.export.doc_pdf import DocBuilder
    from envocad.settings import load_settings, save_settings
    p = build_project(spec(3))
    assert DocBuilder(p, lib).jps_page == "A3"                          # dnešní chování
    st = load_settings()
    st["standard"]["doc_jps_page"] = "list"
    save_settings(st)
    try:
        assert DocBuilder(p, lib).jps_page == "list" and DocBuilder(p, lib, "A3").jps_page == "A3"
    finally:
        st["standard"]["doc_jps_page"] = "A3"
        save_settings(st)


# ---- spolupráce s trafostanicí (přípojka VN) a rodinným domem (rozvaděč FVE) -----------------------------------
def _same_reports_and_no_new_findings(p, one, lib):
    def strip(rows, drop):
        return sorted(tuple(c for k, c in enumerate(r) if k not in drop) for r in rows)
    assert strip(reports.cables(p, lib)[1], {8, 9}) == strip(reports.cables(one, lib)[1], {8, 9})
    assert strip(reports.cable_plan(p, lib)[1], {10}) == strip(reports.cable_plan(one, lib)[1], {10})
    assert reports.bom(p, lib) == reports.bom(one, lib)
    assert sorted((c.ref, c.i_a, c.du_pct) for c in calc.check_cables(p)) == \
        sorted((c.ref, c.i_a, c.du_pct) for c in calc.check_cables(one))
    strings = calc.check_strings(p)
    assert strings and all(c.inverter for c in strings)
    fs, f1 = check_project(p, lib), check_project(one, lib)
    assert not [f for f in fs if f.severity == "chyba"]
    new = {(f.severity, f.code) for f in fs if f.severity == WARNING} - {(f.severity, f.code) for f in f1}
    assert not new, [f.text for f in fs if (f.severity, f.code) in new]
    assert not {f.code for f in fs} & {"interrupt_alone", "cable_split", "dangling", "calc_string"}
    assert Counter(f.code for f in fs)["no_cable"] == Counter(f.code for f in f1)["no_cable"]


def test_split_with_transformer_station(lib):
    """Přípojka VN (trafostanice, rozvaděč VN, transformátor, hlavní rozvaděč nn, elektroměrový rozvaděč) zůstává
    na listu „AC a připojení“; jednopólové schéma odvozené z blokového je stejné jako bez rozdělení."""
    from envocad.model.single_line import single_line_geometry
    conn = {"connection": {"level": "vn", "station": "zdena", "metering": "vn"}}
    p, one = build_project(spec(6, **conn)), build_project(spec(6, jps={"split": "none"}, **conn))
    js = jps_sheets(p)
    assert len(js) == 4 and js[0].name == JPS_AC_SHEET_NAME and len(jps_sheets(one)) == 1
    ac = js[0]
    blocks = {e.ref for e in ac.elements if e.symbol_id == "fve.switchboard"}
    all_blocks = {e.ref for s in jps_sheets(one) for e in s.elements if e.symbol_id == "fve.switchboard"
                  and not e.ref.startswith(("RDC", "RFVE.DC"))}
    assert blocks == all_blocks and any(e.symbol_id == "fve.transformer" for e in ac.elements)
    for s in js[1:]:
        assert {e.symbol_id for e in s.elements} <= {"fve.inverter", "fve.pv_string", "fve.switchboard", INTERRUPT_SYMBOL}
    assert all(s.paper == "A2" for s in js)
    _same_reports_and_no_new_findings(p, one, lib)
    assert single_line_geometry(p, lib).prims == single_line_geometry(one, lib).prims


@pytest.mark.parametrize("route", [0, 1])
def test_split_house_combined_switchboard(lib, route):
    """Rodinný dům nad A2: rozvaděč FVE (DC + AC) zůstává na listu „AC a připojení“ se sítí a HOP; DC vodiče
    stringů / rozvaděčů po trase do RFVE a z RFVE do střídače i AC kabel vedou přes páry přerušení, údaje kabelu
    nese úsek u RFVE."""
    from envocad.model.single_line import single_line_geometry
    extra = {"building": "rodinný dům", "dc": {"route_boxes": route}}
    p, one = build_project(spec(3, **extra)), build_project(spec(3, jps={"split": "none"}, **extra))
    js = jps_sheets(p)
    assert len(js) >= 3 and js[0].name == JPS_AC_SHEET_NAME
    ac = js[0]
    assert [e.ref for e in ac.elements if e.symbol_id == "fve.switchboard"] == ["RFVE"]
    assert {e.symbol_id for e in ac.elements} <= {"fve.switchboard", "fve.grid", "fve.earth", INTERRUPT_SYMBOL}
    rfve = next(e for e in ac.elements if e.ref == "RFVE")
    for w in ac.wires:                                   # vše u RFVE nese údaje kabelu, pokračování je u řady
        if rfve.id in (w.a.element_id, w.b.element_id):
            assert has_cable_data(w) and not is_continuation(p, ac, w)
    for s in js[1:]:
        for i in interrupts(s):
            (w,) = [w for w in s.wires if w.touches(i.id)]
            assert is_continuation(p, s, w)
    assert all(s.paper == "A2" for s in js)
    _same_reports_and_no_new_findings(p, one, lib)
    assert single_line_geometry(p, lib).prims == single_line_geometry(one, lib).prims
