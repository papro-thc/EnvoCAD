"""Rozměry přístrojů v rozložení z artiklů (`model/device_size.py`), Pv z artiklu do oteplení, kontroly rozměrů,
můstky jako artikl ve výkazu materiálu. Návrh `docs/design/rozlozeni_z_artiklu.md`."""
from __future__ import annotations

import pytest

from envocad.library.components import Component, bridge_candidates, is_bridge
from envocad.model.device_size import (
    SHAPE_BOX,
    SHAPE_DIN,
    SHAPE_TERMINAL,
    SRC_ARTICLE,
    SRC_DEFAULT,
    SRC_MANUAL,
    device_modules,
    device_size,
    is_box,
    size_problems,
)
from envocad.model.project import DEVICE_HEIGHT_MM, MODULE_WIDTH, Element, Layout, Project, Sheet


def comp(cid: str, category: str, **params) -> Component:
    return Component(id=cid, manufacturer=params.pop("manufacturer", "X"), part_number=params.pop("pn", cid.upper()),
                     name=cid, category=category, symbol_id="", params={k: str(v) for k, v in params.items()})


VA = comp("3va", "mccb", width_mm="76,2", height_mm=130, depth_mm=88, in_=63, poles=3)
MCB = comp("mcb", "mcb", modules=1, width_mm="17.5", height_mm=80, depth_mm=70, p_loss_w="2,44")
TERM = comp("term", "terminal", width_mm="3.5", height_mm=55, depth_mm="33.5", manufacturer="Weidmüller")
BRIDGE = comp("zqv", "accessory", terminal_kind="mustek", poles=2, manufacturer="Weidmüller", pn="ZQV 2.5N/2")
SW_3VA = comp("3va-sw", "switch", width_mm="76.2", height_mm=130, depth_mm=88)


class FakeLib:
    """Duck-typed knihovna: jen `component(id)` (jako `LibraryStore.component`)."""

    def __init__(self, *comps):
        self.comps = {c.id: c for c in comps}

    def component(self, cid):
        return self.comps.get(cid)


LIB = FakeLib(VA, MCB, TERM, BRIDGE, SW_3VA)


def el(symbol: str, cid: str | None = None, **attrs) -> Element:
    return Element(symbol, attrs={k: str(v) for k, v in attrs.items()}, component_id=cid)


# ---- rozměry ----------------------------------------------------------------------------------------------------
def test_no_article_same_as_before():
    """Bez artiklu (i bez knihovny): šířka = `Element.modules`, výška 45 mm, zdroj podle atributu."""
    e = el("fve.breaker_mcb", modules=3)
    for lib in (None, LIB):
        sz = device_size(e, lib)
        assert sz.modules == e.modules == 3 and sz.height_mm == DEVICE_HEIGHT_MM and sz.depth_mm is None
        assert sz.shape == SHAPE_DIN and sz.source == SRC_MANUAL and not sz.real
        assert device_modules(e, lib) == 3
    assert device_size(el("fve.breaker_mcb")).width_mm == 0 and device_size(el("fve.breaker_mcb")).source == SRC_DEFAULT


def test_terminals_without_article_match_element_modules():
    t = el("sb.terminal_block", terminal="1 2 3 4 5")
    sz = device_size(t, LIB)
    assert sz.modules == t.modules and sz.source == SRC_DEFAULT and sz.shape == SHAPE_TERMINAL and not sz.real


def test_compact_breaker_is_box_from_article():
    """3VA: obdélník 76,2 × 130 mm z artiklu; výchozí `modules` značky („6“) se nepoužije."""
    e = el("fve.breaker_mccb", "3va", modules=6)
    sz = device_size(e, LIB)
    assert (sz.width_mm, sz.height_mm, sz.depth_mm) == (76.2, 130, 88)
    assert sz.shape == SHAPE_BOX and sz.source == SRC_ARTICLE and sz.real and sz.modules == round(76.2 / 17.5, 2)
    assert sz.label() == "76,2 × 130 mm"
    assert is_box(VA) and is_box(SW_3VA) and not is_box(MCB) and not is_box(None)
    assert device_size(el("fve.switch_disconnector", "3va-sw"), LIB).shape == SHAPE_BOX


def test_manual_overrides_article():
    """Ruční `width_mm` / `height_mm` mají přednost; ruční `modules` jen když se liší od modulů artiklu."""
    e = el("fve.breaker_mccb", "3va", width_mm=100, height_mm=150)
    sz = device_size(e, LIB)
    assert (sz.width_mm, sz.height_mm, sz.source, sz.height_source) == (100, 150, SRC_MANUAL, SRC_MANUAL)
    m = el("fve.breaker_mcb", "mcb", modules=1)
    assert device_size(m, LIB).source == SRC_ARTICLE and device_size(m, LIB).height_mm == 80
    m.attrs["modules"] = "2"
    assert device_size(m, LIB).modules == 2 and device_size(m, LIB).source == SRC_MANUAL
    m.attrs["modules"] = ""
    assert device_size(m, LIB).modules == 1 and device_size(m, LIB).label() == "1 M"


def test_terminal_strip_width_from_article():
    """Svorkovnice: počet svorek × `width_mm` artiklu + koncové desky (`end_mm`); ruční `modules` vyhrává."""
    t = el("sb.terminal_block", "term", terminal="1 2 3 4 5 6")
    sz = device_size(t, LIB)
    assert sz.width_mm == pytest.approx(21.0) and sz.source == SRC_ARTICLE and sz.pitch_mm == 3.5
    assert sz.height_mm == 55 and sz.label(6) == "6 × 3,5 mm"
    t.attrs["end_mm"] = "2,5"
    assert device_size(t, LIB).width_mm == pytest.approx(23.5) and device_size(t, LIB).end_mm == 2.5
    t.attrs["modules"] = "2"
    assert device_size(t, LIB).width_mm == pytest.approx(2 * MODULE_WIDTH)
    assert device_size(t, LIB).source == SRC_MANUAL
    # bez knihovny jako dřív (6,2 mm na svorku) + koncové desky
    t.attrs["modules"] = ""
    assert device_size(t).source == SRC_DEFAULT


def test_missing_article_or_library_error_falls_back():
    class Broken:
        def component(self, cid):
            raise RuntimeError("db")
    e = el("fve.breaker_mccb", "3va", modules=6)
    assert device_size(e, Broken()).modules == 6
    assert device_size(el("fve.breaker_mccb", "neznamy", modules=6), LIB).modules == 6


# ---- rozložení a kontroly -----------------------------------------------------------------------------------
def _board(**params) -> tuple[Project, Sheet, dict[str, Element]]:
    s = Sheet(name="RDC1", kind="switchboard")
    s.layout = Layout(rows=2, modules_per_row=12, params={k: str(v) for k, v in params.items()})
    els = {"Q1": el("fve.breaker_mccb", "3va", ref="Q1", modules=6),
           "F1": el("fve.breaker_mcb", "mcb", ref="F1", modules=1, in_=16, poles=1),
           "X1": el("sb.terminal_block", "term", ref="X1", terminal="1 2 3 4 5 6")}
    s.elements = list(els.values())
    s.layout.set_placement(els["Q1"].id, 0, 0)
    s.layout.set_placement(els["F1"].id, 1, 0)
    s.layout.set_placement(els["X1"].id, 1, 2)
    return Project(sheets=[s]), s, els


def test_layout_used_modules_with_library():
    p, s, els = _board()
    without = s.layout.used_modules(s, p)
    assert without == pytest.approx(6 + 1 + els["X1"].modules)
    assert s.layout.used_modules(s, p, LIB) == pytest.approx(round(76.2 / 17.5, 2) + 1 + round(21 / 17.5, 2))
    assert {e.id for e in s.layout.devices(s, p, LIB)} == {e.id for e in els.values()}


def test_size_problems_height_enclosure_depth():
    """3VA 130 mm v rozteči 100 mm → jen `layout_height` (svisle stačí rozteč – řady jsou v obrysu na střed);
    hloubka; řada mimo skříň se nekontroluje."""
    p, s, els = _board(row_pitch_mm=100, height_mm=200, depth_mm=80)
    codes = {(x.code, x.element.ref) for x in size_problems(s, p, LIB)}
    assert ("layout_height", "Q1") in codes and ("layout_depth", "Q1") in codes
    assert ("layout_enclosure", "Q1") not in codes
    assert not any(ref == "F1" and c == "layout_height" for c, ref in codes)
    s.layout.set_placement(els["Q1"].id, 5, 0)       # řada mimo skříň (hlásí `outside_enclosure`)
    assert ("layout_height", "Q1") not in {(x.code, x.element.ref) for x in size_problems(s, p, LIB)}
    s.layout.set_placement(els["Q1"].id, 0, 0)
    # dost místa – nic
    _p, s2, _ = _board(row_pitch_mm=200, height_mm=500, depth_mm=200)
    assert size_problems(s2, _p, LIB) == []
    # bez knihovny a bez ručních rozměrů se nic nehlásí (staré projekty beze změny)
    assert size_problems(s, p) == []
    # široký přístroj z artiklu
    els["Q1"].attrs["width_mm"] = "300"
    assert ("layout_enclosure", "Q1") in {(x.code, x.element.ref) for x in size_problems(s, p, LIB)}


def test_check_project_reports_size_findings():
    from envocad.model.checks import layout_findings
    p, _s, _els = _board(row_pitch_mm=100, height_mm=200, depth_mm=80)
    codes = {f.code for f in layout_findings(p, LIB)}
    assert {"layout_height", "layout_depth"} <= codes
    assert not ({"layout_height", "layout_depth", "layout_enclosure"} & {f.code for f in layout_findings(p)})


def test_layout_overlap_uses_article_width():
    """Bez knihovny se 3VA (6 M) a přístroj na pozici 5 překrývají, s artiklem (4,35 M) ne."""
    from envocad.model.checks import layout_problems
    p, s, els = _board()
    s.layout.set_placement(els["F1"].id, 0, 5)
    assert any(x.code == "layout_overlap" for x in layout_problems(s, p))
    assert not any(x.code == "layout_overlap" for x in layout_problems(s, p, lib=LIB))


# ---- oteplení ---------------------------------------------------------------------------------------------------
def test_thermal_loss_from_article_and_source():
    from envocad.model.thermal import LOSS_ARTICLE, LOSS_ESTIMATE, LOSS_MANUAL, rated_loss, temperature_rise
    p, s, els = _board()
    f1 = els["F1"]
    assert rated_loss(f1, MCB) == (2.44, LOSS_ARTICLE)          # bez atributu z artiklu
    f1.attrs["p_loss_w"] = "2,44"
    assert rated_loss(f1, MCB) == (2.44, LOSS_ARTICLE)          # atribut shodný s artiklem
    f1.attrs["p_loss_w"] = "3"
    assert rated_loss(f1, MCB) == (3.0, LOSS_MANUAL)            # ruční přepis
    assert rated_loss(f1, None) == (3.0, LOSS_MANUAL)
    f1.attrs["p_loss_w"] = ""
    assert rated_loss(els["Q1"], VA) == (None, LOSS_ESTIMATE)   # 3VA: katalog Pv nemá
    els["Q1"].attrs["in_"] = "63"
    r = temperature_rise(s, rdf=1.0, project=p, lib=LIB)
    by_ref = {x.ref: x for x in r.losses}
    assert by_ref["F1"].source == LOSS_ARTICLE and by_ref["F1"].p_w == pytest.approx(2.44)
    assert by_ref["Q1"].source == LOSS_ESTIMATE and by_ref["Q1"].p_rated_w is None
    assert r.loss_summary() == "Pv: 1× artikl, 1× odhad"
    assert any("odhad z In" in n for n in r.notes)
    # bez knihovny jako dřív: F1 odhadem z In
    r0 = temperature_rise(s, rdf=1.0, project=p)
    assert {x.ref: x.source for x in r0.losses}["F1"] == LOSS_ESTIMATE
    assert r0.p_devices_w != r.p_devices_w
    assert any("odhadnuty z In" in n for n in r0.notes)


def test_device_power_loss_backward_compatible():
    from envocad.model.thermal import device_power_loss
    e = el("fve.breaker_mcb", in_=32, poles=3)
    assert device_power_loss(e, rdf=1.0) == round(0.09 * 32 * 3, 2)
    e.attrs["p_loss_w"] = "4"
    assert device_power_loss(e, rdf=0.5) == 1.0
    e.attrs["p_loss_w"] = "x"
    assert device_power_loss(e, rdf=1.0) == round(0.09 * 32 * 3, 2)
    assert device_power_loss(el("fve.breaker_mcb", in_=16), rdf=1.0, comp=MCB) == pytest.approx(2.44)


# ---- můstky ------------------------------------------------------------------------------------------------------
def test_bridge_candidates():
    assert is_bridge(BRIDGE) and not is_bridge(TERM)
    assert bridge_candidates([VA, TERM, BRIDGE], TERM) == [BRIDGE]
    assert bridge_candidates([BRIDGE], comp("t2", "terminal", manufacturer="Bečov")) == []
    assert bridge_candidates([BRIDGE, TERM]) == [BRIDGE]


def test_bom_bridge_article_per_group(monkeypatch):
    """Můstek bere `bridge_id` skupiny svorek, na které leží; póly artiklu vs. velikost skupiny: shoda = typ, víc =
    „zkrátit“, míň = bez typu s poznámkou; neznámé id a artikl, který není můstek, hlásí F7."""
    from envocad.export.reports import bom
    from envocad.model import terminal_plan
    from envocad.model.bridges import CUT, NOT_BRIDGE, OK, POLES, UNKNOWN, bridge_findings, resolve_bridge

    class Lib(FakeLib):
        def get_symbol(self, sid):
            from envocad.model.symbol import placeholder_symbol
            return placeholder_symbol(sid)
    zqv10 = comp("zqv10", "accessory", terminal_kind="mustek", poles=10, manufacturer="Weidmüller", pn="ZQV 2.5N/10")
    lib = Lib(TERM, BRIDGE, zqv10)
    monkeypatch.setattr(terminal_plan, "strip_numbers", lambda project, sheet, strip: {str(i) for i in range(1, 13)})
    p, s, els = _board()
    x2 = el("sb.terminal_block", "term", ref="X1", terminal="7 8 9 10 11 12")
    s.elements.append(x2)
    p.set_bridges("X1", [["1", "2"], ["7", "8", "9"]], s)

    def bridge_rows():
        return [r for r in bom(p, lib, s)[1] if r[1] == "Můstek svorek"]
    assert {(r[2], r[4]) for r in bridge_rows()} == {("", "2 pólů"), ("", "3 pólů")}     # bez bridge_id jako dřív
    els["X1"].attrs["bridge_id"] = "zqv"
    x2.attrs["bridge_id"] = "zqv10"
    assert resolve_bridge(s, "X1", ["1", "2"], lib).status == OK
    assert resolve_bridge(s, "X1", ["7", "8", "9"], lib).status == CUT
    rows = {r[4]: r for r in bridge_rows()}
    assert rows["2 pólů"][2:4] == ["ZQV 2.5N/2", "Weidmüller"]
    assert rows["3 pólů, zkrátit z 10 pólů"][2:4] == ["ZQV 2.5N/10", "Weidmüller"]
    assert bridge_findings(p, lib) == []
    # málo pólů → bez typu, F7
    x2.attrs["bridge_id"] = "zqv"
    r = resolve_bridge(s, "X1", ["7", "8", "9"], lib)
    assert r.status == POLES and r.type == "" and "má 2 pólů" in r.note
    assert any(r[2] == "" and "má 2 pólů" in r[4] for r in bridge_rows())
    # artikl, který není můstek / neznámé id
    x2.attrs["bridge_id"] = "term"
    assert resolve_bridge(s, "X1", ["7", "8", "9"], lib).status == NOT_BRIDGE
    els["X1"].attrs["bridge_id"] = "neznamy"
    assert resolve_bridge(s, "X1", ["1", "2"], lib).status == UNKNOWN
    found = bridge_findings(p, lib)
    assert {f.code for f in found} == {"bridge_article"} and len(found) == 2
    assert bridge_findings(p, None) == []
    assert resolve_bridge(s, "X1", ["1", "2"], None).type == "neznamy"     # bez knihovny id jako typ


# ---- skutečný katalog -------------------------------------------------------------------------------------------
def test_builtin_catalog_sizes(tmp_path):
    """Vestavěný katalog: 3VA11 76,2 × 130 mm (obdélník), Hager MBN 1 M × 83 mm s Pv 2,44 W, svorka Weidmüller A2C 1.5
    3,5 mm; můstky ZQV jsou kandidáti pro svorku Weidmüller."""
    from envocad.library.store import LibraryStore
    lib = LibraryStore(tmp_path / "lib.db")
    q = el("fve.breaker_mccb", "oez-3va1163-3ef36-0aa0", modules=6)
    assert device_size(q, lib).shape == SHAPE_BOX and device_size(q, lib).width_mm == 76.2
    f = el("fve.breaker_mcb", "hager-mbn116", modules=1)
    assert device_size(f, lib).height_mm == 83 and device_size(f, lib).source == SRC_ARTICLE
    t = el("sb.terminal_block", "weidmuller-1552790000", terminal="1 2 3 4")
    assert device_size(t, lib).width_mm == pytest.approx(14.0)
    term = lib.component("weidmuller-1552790000")
    cands = bridge_candidates(lib.components(), term)
    assert cands and all(c.manufacturer == "Weidmüller" and is_bridge(c) for c in cands)
    assert any("ZQV" in c.name for c in cands)


def test_explicit_zero_modules_is_not_layout_device():
    """`modules="0"` (generátory: měření, VN přístroje; výchozí „0“ značek fve.disconnector…) = mimo rozložení, i když
    artikl má moduly nebo jen `width_mm`; ruční `width_mm` ale platí."""
    for cid, sym in (("mcb", "fve.breaker_mcb"), ("3va", "fve.breaker_mccb")):
        e = el(sym, cid, modules=0)
        assert device_size(e, LIB).width_mm == 0 and device_modules(e, LIB) == 0
        p = Project(sheets=[Sheet(kind="switchboard", elements=[e])])
        assert p.sheets[0].layout.devices(p.sheets[0], p, LIB) == []
        e.attrs["width_mm"] = "50"
        assert device_modules(e, LIB) == round(50 / MODULE_WIDTH, 2)
    t = el("sb.terminal_block", "term", terminal="1 2", modules=0)
    assert device_size(t, LIB).width_mm == 0


def test_device_modules_without_article_is_element_modules():
    e = el("fve.breaker_mcb", modules="2,5")
    assert device_modules(e, LIB) == e.modules == 2.5
    t = el("sb.terminal_block", terminal="1 2 3")
    assert device_modules(t, LIB) == t.modules


def test_memo_lib_reads_article_once():
    from envocad.model.device_size import MemoLib, memo_lib

    class Counting(FakeLib):
        calls = 0

        def component(self, cid):
            Counting.calls += 1
            return super().component(cid)
    lib = Counting(VA, MCB, TERM)
    p, s, _els = _board()
    s.layout.used_modules(s, p, lib)
    assert Counting.calls == 3          # Q1, F1, X1 – každý jednou (devices + součet)
    m = memo_lib(lib)
    assert isinstance(m, MemoLib) and memo_lib(m) is m and memo_lib(None) is None
    assert m.comps is lib.comps         # ostatní atributy předává knihovně


def test_terminal_point_uses_article_height():
    """Délky vodičů: svorka přístroje je na hraně jeho skutečné výšky (artikl 80 mm), bez artiklu 45 mm."""
    from envocad.model.wiring import WiringParams, terminal_point
    p, s, els = _board(row_pitch_mm=150)
    f1 = els["F1"]
    params = WiringParams.resolve(s.layout, {})
    axis = -(1 + 0.5) * 150
    with_art = terminal_point(p, s, f1, "1", "L1", "F1:1", params, lib=LIB)
    without = terminal_point(p, s, f1, "1", "L1", "F1:1", params)
    assert with_art.y == pytest.approx(axis + 80 / 2) and without.y == pytest.approx(axis + DEVICE_HEIGHT_MM / 2)
    assert "výška přístroje z artiklu, jinak 45 mm" in params.describe()


def test_tz_thermal_losses_decimal_comma(tmp_path):
    """TZ: ΣPv se zdrojem a tabulka ztrát po přístrojích s desetinnou čárkou."""
    from docx import Document

    from envocad.export.tz_export import export_tz_docx
    from envocad.library.store import LibraryStore
    lib = LibraryStore(tmp_path / "lib.db")
    s = Sheet(name="RFVE.AC", kind="switchboard")
    f1 = el("fve.breaker_mcb", ref="F1", modules=1, in_=16, poles=1)
    lib.component("hager-mbn116").apply_to(f1)
    s.elements = [f1, el("fve.breaker_mcb", ref="F2", modules=1, in_=10, poles=1)]
    p = Project(name="TZ", sheets=[s])
    export_tz_docx(p, lib, tmp_path / "tz.docx")
    doc = Document(str(tmp_path / "tz.docx"))
    text = "\n".join(par.text for par in doc.paragraphs)
    assert "Pv: 1× artikl, 1× odhad" in text and "Ae = " in text and "Ae = 0." not in text
    cells = [[c.text for c in row.cells] for t in doc.tables for row in t.rows]
    assert ["Přístroj", "Pv při In [W]", "Pv při 0,8·In [W]", "Zdroj"] in cells
    assert ["F1", "2,44", "1,56", "artikl"] in cells
