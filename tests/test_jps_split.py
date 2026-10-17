"""Rozdělení velkého JPS na listy (docs/design/dluhy_dxf_jps.md, bod B + rozhodnutí 10/2026): AC list jako přehled
první, za ním listy střídačů (A2); AC kabel přes pár přerušovacích bodů je jeden kabel (data jen u bloku AC
rozvaděče); `xref.through_interrupt` ve výkazech, výpočtech, vazbách přívodů a potenciálech; kontroly F7."""
import math
import re
from collections import Counter

import pytest

from envocad.export import reports
from envocad.generate import JPS_AC_SHEET_NAME, build_project
from envocad.library.store import LibraryStore
from envocad.model import calc
from envocad.model.checks import AGGREGATED_INFO, WARNING, check_project
from envocad.model.frame import paper_exceeds
from envocad.model.potential import nets
from envocad.model.project import FORMAT_VERSION, INTERRUPT_SYMBOL, Element, Project, Sheet, Wire, WireEnd
from envocad.model.xref import (
    continuation_main,
    has_cable_data,
    interrupt_xref,
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
    assert [s.name for s in js[1:]] == [f"Jednopólové schéma – T{i}, T{i + 1}" for i in (1, 3, 5, 7)]
    for s in js:
        assert (s.paper, s.width, s.height) == ("A2", 594.0, 420.0), s.name
    # každý střídač s celým DC řetězcem (stringy, DC rozvaděče) na jednom listu; na listu přerušení jeho AC kabelu
    for s in js[1:]:
        invs = [e.ref for e in s.elements if e.symbol_id == "fve.inverter"]
        assert sorted(e.ref for e in interrupts(s)) == sorted(f"AC-{r}" for r in invs)
        assert any(e.symbol_id == "fve.pv_string" for e in s.elements)
    checks = calc.check_strings(big)
    assert len(checks) == 32 and all(c.inverter for c in checks)   # string najde svůj střídač (stejný list)
    assert big.to_dict()["format_version"] == FORMAT_VERSION == 9


def test_small_projects_stay_on_one_sheet():
    for n in (1, 2):
        p = build_project(spec(n))
        js = jps_sheets(p)
        assert len(js) == 1 and js[0].name == "Jednopólové schéma" and js[0].paper in ("A3", "A2")
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
    head, rows = reports.cables(big, lib)
    refs = [r[0] for r in rows]
    assert len(refs) == len(set(refs)) == len(big.cables)
    w13 = next(r for r in rows if r[1] == "T1:AC")
    assert w13[2] == "+RH-X1" and w13[3] == "CYKY-J 5x16" and w13[9] == JPS_AC_SHEET_NAME

    def strip(rows, drop):
        return sorted(tuple(c for k, c in enumerate(r) if k not in drop) for r in rows)
    one = reports.cables(big_one_sheet, lib)[1]
    assert strip(rows, {8, 9}) == strip(one, {8, 9})
    assert strip(reports.cable_plan(big, lib)[1], {10}) == strip(reports.cable_plan(big_one_sheet, lib)[1], {10})
    assert reports.bom(big, lib) == reports.bom(big_one_sheet, lib)
    assert not any("Přerušovací" in str(r[1]) for r in reports.bom(big, lib)[1])

    def jps_wiring(p):
        return strip([r for r in reports.wiring_list(p, lib)[1] if r[0].startswith("Jednopólové")], {0})
    assert jps_wiring(big) == jps_wiring(big_one_sheet)       # úsek pokračování nemá řádek „vodič“

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
    sb = next(s for s in big.sheets if s.is_switchboard and s.loc == "RH")
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
    p, a, b, t, ia, ib, f, cont, main = _manual()
    assert through_interrupt(p, b, ib, "1") == (a, t, "AC")
    assert through_interrupt(p, a, ia, "1") == (b, f, "1")
    assert through_interrupt(p, a, t, "AC") is None                     # není přerušovací bod
    assert continuation_main(p, a, cont) == (b, main)
    assert continuation_main(p, b, main) is None and split_cable_partner(p, b, main) is None
    cont.attrs["cable"] = "CYKY-J 5x16"
    assert split_cable_partner(p, a, cont) == (b, main) and split_cable_partner(p, b, main) == (a, cont)


def test_through_interrupt_none_for_alone_chain_star_and_branching():
    p, a, b, t, ia, ib, f, cont, main = _manual()
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
    assert through_interrupt(p, b, ib) is None and not is_continuation(p, a, cont)


def test_manual_pair_reports_calc_potential_checks(lib):
    p, a, b, t, ia, ib, f, cont, main = _manual()
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
    a2 = (594 / 25.4 * 72, 420 / 25.4 * 72)
    for i, _s in sheet_items:
        mb = reader.pages[b2.page_starts[i] - 1].mediabox
        assert abs(float(mb.width) - a2[0]) < 2 and abs(float(mb.height) - a2[1]) < 2
