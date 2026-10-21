"""Generátor F2 – nové články řetězce (docs/design/topologie_f1_f2.md, kap. 2; rozhodnutí docs/NAVRH_TOPOLOGIE.md,
kap. 8): označení z presetů, společný RFVE.DC, HDS, RE na nn, stávající RD / HR, kabely mezi články."""
from __future__ import annotations

import functools

import pytest

from envocad.generate import build_project
from envocad.generator.spec import chain_flag, chain_options, node_ref
from envocad.library.topologies import load_topologies
from envocad.model.project import element_symbol


@functools.cache
def _lib():
    from envocad.library.store import LibraryStore
    return LibraryStore()


_INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


def _blocks(p) -> dict[str, object]:
    """Bloky rozvaděčů ze všech listů blokového schématu (i rozděleného)."""
    return {e.ref: e for s in p.sheets if not s.is_switchboard for e in s.elements if e.symbol_id == "fve.switchboard"}


_EXIST_NN = {"hr": {"main_in": 250}, "re": {"main_in": 250}, "hds": {"in_": 315}}


# ---- krok 1: označení z presetu, dřívější klíče jako přepis ----------------------------------------------------
def test_node_ref_precedence():
    topo = load_topologies()["nn"]
    assert node_ref({}, topo, "rfve_ac", default="X") == "RFVE.AC"            # preset
    assert node_ref({}, topo, "rfve_ac", legacy="RH1") == "RH1"               # zadaný dřívější klíč
    assert node_ref({"chain": {"rfve_ac": {"ref": "RA"}}}, topo, "rfve_ac", legacy="RH1") == "RA"
    assert node_ref({}, topo, "tr", default="TR9") == "TR9"                   # role mimo preset → konstanta
    assert node_ref({}, None, "rfve_ac", default="RFVE.AC") == "RFVE.AC"


def test_chain_options_spec_over_preset():
    topo = load_topologies()["rd"]
    assert chain_options({}, topo, "re")["metering"] == "direct"
    o = chain_options({"chain": {"re": {"metering": "indirect", "main_in": 63}}}, topo, "re")
    assert o["metering"] == "indirect" and o["main_in"] == 63 and o["boundary"] == "hds"
    assert chain_options({}, topo, "xx") == {}
    assert chain_flag("1") and chain_flag(True) and chain_flag("true") and not chain_flag("0")
    assert chain_flag("", True) and not chain_flag(None)


def test_refs_from_preset_and_overrides(tmp_path, monkeypatch):
    """Označení bloků bere generátor z presetu (`node.ref`); `chain.<role>.ref` a dřívější `switchboard.ref` /
    `connection.main_board.ref` zadané uživatelem ho přepíšou. Vlastní preset s jiným označením se projeví."""
    inv = [{"ref": "T1", **_INV, "strings": [20]}]
    p = build_project({"inverters": inv})
    assert "RFVE.AC" in _blocks(p) and "RFVE.DC" in _blocks(p)
    p = build_project({"inverters": inv, "chain": {"rfve_ac": {"ref": "RA1"}, "rfve_dc": {"ref": "RD9"}}})
    assert {"RA1", "RD9"} <= set(_blocks(p))
    p = build_project({"inverters": inv, "switchboard": {"ref": "RH1"}})
    assert "RH1" in _blocks(p)
    p = build_project({"inverters": inv, "connection": {"level": "vn", "main_board": {"ref": "RHN"}},
                       "chain": {"rvn": {"ref": "RVN2"}, "re": {"ref": "RE7"}}})
    assert {"RHN", "RVN2", "RE7"} <= set(_blocks(p))
    house = build_project({"building": "house", "inverters": [{"ref": "T1", **_INV, "strings": [12]}]})
    assert _blocks(house)["RFVE"].attrs["desc"] == "rozvaděč FVE (DC + AC)"


# ---- krok 2: společný RFVE.DC (výchozí), `chain.rfve_dc.per_inverter` = DC rozvaděč na střídač --------------------
def _two(**kw):
    return {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20, 18]}, {"ref": "T2", **_INV, "strings": [20, 20]}],
            "chain": _EXIST_NN, **kw}


def test_rfve_dc_common_by_default():
    from envocad.library.store import LibraryStore
    from envocad.model.checks import ERROR, WARNING, check_project
    from envocad.model.feed import is_feed_in, is_feed_out
    p = build_project(_two())
    assert [s.loc for s in p.switchboards() if s.loc.startswith(("RDC", "RFVE.DC"))] == ["RDC1", "RDC2", "RFVE.DC"]
    sh = next(s for s in p.switchboards() if s.loc == "RFVE.DC")
    assert sorted(e.ref for e in sh.elements if is_feed_in(e)) == sorted(f"X{k}" for k in range(1, 6))
    assert sorted(e.ref for e in sh.elements if is_feed_out(e)) == sorted([*(f"X{k}" for k in range(6, 11)), "XPE"])
    # makro „DC string v rozvaděči“ po střídačích: ENVO číslování i.j
    assert {e.ref for e in sh.elements if e.symbol_id == "fve.fuse_disconnect"} == {"FU1.1", "FU1.2", "FU1.3",
                                                                                     "FU2.1", "FU2.2"}
    lib = LibraryStore()
    assert not [f for f in check_project(p, lib) if f.severity in (ERROR, WARNING)]
    # stringy vedou přes společný rozvaděč každý na svůj střídač a DC vstup
    from envocad.model.calc import check_strings
    assert {(c.ref, c.inverter) for c in check_strings(p)} == {
        ("G1", "T1"), ("G2", "T1"), ("G3", "T1"), ("G4", "T2"), ("G5", "T2")}


def test_rfve_dc_common_code_path_in_per_string():
    """Bez maker: kódem, In pojistek po stringu podle jeho střídače (`fuse_of`)."""
    p = build_project(_two(macros={"dc_tech": "", "dc_route": "", "ac_feed": "", "ac_core": ""}))
    sh = next(s for s in p.switchboards() if s.loc == "RFVE.DC")
    assert len([e for e in sh.elements if e.symbol_id == "fve.fuse_disconnect"]) == 5


def test_rfve_dc_per_inverter_option():
    p = build_project(_two(chain={**_EXIST_NN, "rfve_dc": {"per_inverter": True}}))
    assert [s.loc for s in p.switchboards() if s.loc.startswith(("RDC", "RFVE.DC"))] == [
        "RDC1", "RFVE.DC1", "RDC2", "RFVE.DC2"]
    blocks = _blocks(p)
    assert blocks["RFVE.DC1"].attrs["desc"] == "DC rozvaděč u T1"
    # jeden střídač: společný = na střídač (beze změny)
    one = build_project({"inverters": [{"ref": "T1", **_INV, "strings": [20]}]})
    assert "RFVE.DC" in _blocks(one) and _blocks(one)["RFVE.DC"].attrs["desc"] == "DC rozvaděč u T1"


def test_rfve_dc_common_split_jps():
    """Dělení JPS: společný RFVE.DC zůstává na listu „AC a připojení“, DC vodiče řad přes páry přerušení (body u DC
    vstupů střídače rozestoupené); odvozené JPS s DC částí najde všechny stringy; F7 bez chyb a varování."""
    from envocad.generate import JPS_AC_SHEET_NAME
    from envocad.library.store import LibraryStore
    from envocad.model.checks import ERROR, WARNING, check_project
    from envocad.model.single_line import build_tree
    spec = {"inverters": [{"ref": f"T{i}", **_INV, "strings": [20] * 8} for i in range(1, 5)],
            "jps": {"split": "auto", "max_paper": "A2", "paper": "A2"}, "chain": _EXIST_NN}
    p = build_project(spec)
    jps = [s for s in p.sheets if not s.is_switchboard]
    assert len(jps) == 5 and jps[0].name == JPS_AC_SHEET_NAME
    assert any(e.ref == "RFVE.DC" for e in jps[0].elements)
    lib = LibraryStore()
    assert not [f for f in check_project(p, lib) if f.severity in (ERROR, WARNING)]
    _root, nodes = build_tree(p, lib, dc=True)
    assert sum(n.element.symbol_id == "fve.pv_string" for n in nodes.values()) == 32


# ---- krok 3: HDS ------------------------------------------------------------------------------------------------
def test_hds_symbol_contract():
    from envocad.library.store import LibraryStore
    sym = LibraryStore().get_symbol("fve.hds")
    assert [(p.name, p.x, p.y, p.dir) for p in sym.ports] == [("1", -12.5, 0, "W"), ("2", 12.5, 0, "E")]
    assert {a.key for a in sym.attributes} >= {"ref", "desc", "in_", "char", "poles"}
    assert all(p.x % 2.5 == 0 and p.y % 2.5 == 0 for p in sym.ports)


def test_hds_block_before_grid_without_cable():
    """Řetězec nn i rd končí HDS → DS: blok `fve.hds` (In a charakteristika z `chain.hds`), vodič do DS bez kabelu
    a bez označení; odvozené JPS ho nese (neotáčí se)."""
    from envocad.library.store import LibraryStore
    from envocad.model.single_line import NO_ROTATE_PREFIXES, build_tree
    for spec in ({"inverters": [{"ref": "T1", **_INV, "strings": [20]}], "chain": {"hds": {"in_": 100}}},
                 {"building": "house", "inverters": [{"ref": "T1", **_INV, "strings": [12]}],
                  "chain": {"hds": {"in_": 100}}}):
        p = build_project(spec)
        s = p.sheets[0]
        hds = next(e for e in s.elements if e.symbol_id == "fve.hds")
        grid = next(e for e in s.elements if e.symbol_id == "fve.grid")
        assert hds.ref == "HDS" and hds.attrs["in_"] == "100" and hds.attrs["char"] == "gG"
        w = next(w for w in s.wires if w.touches(hds.id) and w.touches(grid.id))
        assert (w.a.port, w.b.port) == ("2", "1") and w.attrs == {"ref": ""}
        _root, nodes = build_tree(p, LibraryStore())
        assert any(n.element.id == hds.id for n in nodes.values())
    assert "fve.hds" in NO_ROTATE_PREFIXES


def test_hds_in_selectivity():
    """Pojistky HDS jsou jisticí přístroj selektivity: jistič za nimi s větším In → nález."""
    from envocad.model.calc import SELECTIVITY_DEVICES, check_selectivity
    from envocad.model.project import Element, Project, Wire, WireEnd
    assert "fve.hds" in SELECTIVITY_DEVICES and "fve.fuse_disconnect" in SELECTIVITY_DEVICES
    p = Project()
    s = p.sheets[0]
    g = Element("fve.grid", 100, 0, attrs={"ref": ""})
    h = Element("fve.hds", 70, 0, attrs={"ref": "HDS", "in_": "50"})
    q = Element("fve.breaker_mccb", 40, 0, attrs={"ref": "Q1", "in_": "63"})
    s.elements += [g, h, q]
    s.wires += [Wire(WireEnd(h.id, "2"), WireEnd(g.id, "1")), Wire(WireEnd(q.id, "2"), WireEnd(h.id, "1"))]
    (row,) = check_selectivity(p)
    assert row[:4] == ("Q1", "HDS", 63.0, 50.0) and "menší In" in row[4]


# ---- krok 4: RE na nn --------------------------------------------------------------------------------------------
_NN1 = {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}]}


def _re(p):
    return next(s for s in p.switchboards() if s.loc == "RE")


def _chain_order(sheet, start):
    """Prvky listu od přívodu `start` po vodičích hlavní cesty (bez odboček k elektroměru na MTP)."""
    out, cur, seen = [], start, {start.id}
    while True:
        nxt = [w for w in sheet.wires if w.touches(cur.id)
               and (w.a.port if w.a.element_id == cur.id else w.b.port) in ("1", "2")]
        cand = [sheet.element(w.b.element_id if w.a.element_id == cur.id else w.a.element_id) for w in nxt]
        cand = [e for e in cand if e.id not in seen and e.symbol_id != "fve.meter" or
                (e.id not in seen and e.symbol_id == "fve.meter" and not any(x.symbol_id == "fve.ct" for x in out))]
        if not cand:
            return out
        cur = cand[0]
        seen.add(cur.id)
        out.append(cur)


def test_re_direct_series():
    """RE nn přímé měření: XIN → HJ (MCB do 125 A) → elektroměr v sérii → vypínač instalace → XOUT; blok zrcadlený
    (XIN k DS vpravo), vodič RE → HDS bez kabelu (stávající)."""
    p = build_project({**_NN1, "chain": {"re": {"main_in": 63}}})
    sh = _re(p)
    xin = next(e for e in sh.elements if e.ref == "XIN")
    assert [e.symbol_id for e in _chain_order(sh, xin)] == ["fve.breaker_mcb", "fve.meter", "sb.main_switch",
                                                           "sb.feed"]
    hj = next(e for e in sh.elements if e.symbol_id == "fve.breaker_mcb")
    q = next(e for e in sh.elements if e.symbol_id == "sb.main_switch")
    assert hj.attrs["in_"] == "63" and q.attrs["in_"] == "63" and q.attrs["desc"] == "vypínač instalace"
    blk = _blocks(p)["RE"]
    assert blk.mirror
    hds = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.hds")
    w = next(w for w in p.sheets[0].wires if w.touches(blk.id) and w.touches(hds.id))
    assert w.attrs == {"ref": ""} and {w.a.port, w.b.port} == {"XIN", "1"}


def test_re_big_main_breaker_and_indirect():
    p = build_project({**_NN1, "chain": {"re": {"main_in": 200, "metering": "nepřímé", "switch_in": 250}}})
    sh = _re(p)
    hj = next(e for e in sh.elements if e.attrs.get("desc") == "hlavní jistič před elektroměrem")
    assert hj.symbol_id == "fve.breaker_mccb"
    ct = next(e for e in sh.elements if e.symbol_id == "fve.ct")
    assert ct.attrs["ratio"] == "200/5 A"
    meter = next(e for e in sh.elements if e.symbol_id == "fve.meter")
    assert any(w.touches(ct.id) and w.touches(meter.id) and w.conductors == ["S1", "S2"] for w in sh.wires)
    assert next(e for e in sh.elements if e.symbol_id == "sb.main_switch").attrs["in_"] == "250"
    p = build_project({**_NN1, "chain": {"re": {"main_in": 200, "metering": "indirect", "ct_ratio": "300/5 A"}}})
    assert next(e for e in _re(p).elements if e.symbol_id == "fve.ct").attrs["ratio"] == "300/5 A"


def test_re_unknown_main_in_is_f7_error():
    from envocad.library.store import LibraryStore
    from envocad.model.checks import ERROR, check_project
    p = build_project(_NN1)
    hj = next(e for e in _re(p).elements if e.symbol_id == "fve.breaker_mcb")
    assert hj.attrs["in_"] == "" and "chain.re.main_in" in hj.attrs["in_unresolved"]
    fs = [f for f in check_project(p, LibraryStore()) if f.code == "breaker_no_in" and f.target_id == hj.id]
    assert fs and fs[0].severity == ERROR


def test_re_boundary_variants():
    p = build_project({**_NN1, "chain": {"re": {"main_in": 63}}})        # preset: hds
    hds = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.hds")
    assert hds.attrs.get("boundary") == "1"
    (t,) = p.sheets[0].texts
    assert t.text == "hranice vlastnictví DS / odběratel" and abs(t.x - (hds.x - 10)) < 5 and t.y > hds.y
    p = build_project({**_NN1, "chain": {"re": {"main_in": 63, "boundary": "re_main"}}})
    hj = next(e for e in _re(p).elements if e.symbol_id == "fve.breaker_mcb")
    assert hj.attrs.get("boundary") == "1"
    assert not any(e.attrs.get("boundary") for e in p.sheets[0].elements)
    blk = _blocks(p)["RE"]
    (t,) = p.sheets[0].texts
    assert abs(t.x - (blk.x - 15)) < 5 and t.y > blk.y
    p = build_project({**_NN1, "chain": {"re": {"main_in": 63, "boundary": "re_meter"}}})
    assert next(e for e in _re(p).elements if e.symbol_id == "fve.meter").attrs.get("boundary") == "1"


def test_re_invalid_options_raise():
    import pytest
    with pytest.raises(ValueError, match="hranice vlastnictví"):
        build_project({**_NN1, "chain": {"re": {"boundary": "xx"}}})
    with pytest.raises(ValueError, match="neznámé měření"):
        build_project({**_NN1, "chain": {"re": {"metering": "xx"}}})


def test_single_line_meter_in_series_is_tree_node():
    """Odvozené JPS: elektroměr v sérii (přímé měření v RE) je uzel stromu – strom pokračuje přes něj ke
    střídačům (návrh „Riziko“); elektroměr na MTP zůstává měřicím obvodem vedle MTP."""
    from envocad.library.store import LibraryStore
    from envocad.model.single_line import build_tree, single_line_geometry
    lib = LibraryStore()
    p = build_project({**_NN1, "chain": {"re": {"main_in": 63}}})
    _root, nodes = build_tree(p, lib)
    meter = next(n for n in nodes.values() if n.element.symbol_id == "fve.meter")
    assert meter.children and not meter.links
    assert any(n.element.symbol_id == "fve.inverter" for n in nodes.values())
    single_line_geometry(p, lib)
    p = build_project({**_NN1, "chain": {"re": {"main_in": 200, "metering": "indirect"}}})
    _root, nodes = build_tree(p, lib)
    ct = next(n for n in nodes.values() if n.element.symbol_id == "fve.ct")
    assert len(ct.meters) == 1 and any(n.element.symbol_id == "fve.inverter" for n in nodes.values())
    single_line_geometry(p, lib)


def test_apply_placement_moves_sheet_texts():
    from envocad.model.frame import apply_placement
    from envocad.model.project import Project, SheetText
    p = Project()
    s = p.sheets[0]
    s.texts.append(SheetText(x=10, y=20, text="a"))
    apply_placement(s, ("A3", 420.0, 297.0, 5.0, -2.5))
    assert (s.texts[0].x, s.texts[0].y) == (15.0, 17.5)


# ---- krok 5: stávající RD / HR -----------------------------------------------------------------------------------
_HOUSE = {"building": "house", "inverters": [{"ref": "T1", "p_ac": 10, "u_dc_max": 1100, "u_mppt_min": 200,
                                              "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [12, 12]}]}
_EXIST_RD = {"rd": {"main_in": 40}, "re": {"main_in": 40}, "hds": {"in_": 50}}


def _board(p, loc):
    return next(s for s in p.switchboards() if s.loc == loc)


def _el(sheet, ref):
    return next(e for e in sheet.elements if e.ref == ref)


def _fve_device(sheet):
    x1 = _el(sheet, "X1")
    w = next(w for w in sheet.wires if w.touches(x1.id))
    return sheet.element(w.a.element_id if w.b.element_id == x1.id else w.b.element_id)


def test_rd_existing_board():
    """RD: XIN → hlavní vypínač (main_in) → přípojnice → vývod FVE X1 (jistič ≥ Σ In střídačů: 10 kW → 16 A) a
    stávající rozvody X2 (v blokovém schématu spotřeba pod blokem); řetězec RFVE → RD → RE → HDS → DS."""
    p = build_project({**_HOUSE, "chain": _EXIST_RD})
    assert p.meta["topology"] == "rd"
    sh = _board(p, "RD")
    q = next(e for e in sh.elements if e.attrs.get("desc") == "hlavní vypínač")
    assert q.symbol_id == "sb.main_switch" and q.attrs["in_"] == "40"
    f = _fve_device(sh)
    assert f.symbol_id == "fve.breaker_mcb" and f.attrs["in_"] == "16"
    assert _el(sh, "X1").attrs["desc"] == "k RFVE (FVE)" and _el(sh, "X2").attrs["desc"] == "stávající rozvody objektu"
    s = p.sheets[0]
    blk = _blocks(p)["RD"]
    assert blk.mirror
    load = next(e for e in s.elements if e.symbol_id == "fve.load")
    assert any(w.touches(blk.id) and w.touches(load.id) and w.attrs == {"ref": ""} for w in s.wires)
    order = [_blocks(p)["RFVE"]]
    for _ in range(4):
        cur = order[-1]
        nxt = [s.element(w.b.element_id) for w in s.wires if w.a.element_id == cur.id
               and w.a.port in ("XOUT", "XIN", "2") and s.element(w.b.element_id).symbol_id != "fve.earth"]
        order.append(nxt[0])
    assert [e.ref or e.symbol_id for e in order] == ["RFVE", "RD", "RE", "HDS", "fve.grid"]


def test_rd_unknown_main_in_is_f7_error():
    from envocad.library.store import LibraryStore
    from envocad.model.checks import ERROR, check_project
    p = build_project({**_HOUSE, "chain": {**_EXIST_RD, "rd": {}}})
    q = next(e for e in _board(p, "RD").elements if e.attrs.get("desc") == "hlavní vypínač")
    assert q.attrs["in_"] == "" and "chain.rd.main_in" in q.attrs["in_unresolved"]
    fs = [f for f in check_project(p, LibraryStore()) if f.target_id == q.id and f.severity == ERROR]
    assert [f.code for f in fs] == ["breaker_no_in"]


def test_hr_main_breaker_and_fve_device():
    spec = {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}], "chain": _EXIST_NN}
    hr = _board(build_project(spec), "HR")
    q = next(e for e in hr.elements if e.attrs.get("desc") == "hlavní jistič")
    assert q.symbol_id == "fve.breaker_mccb" and q.attrs["in_"] == "250"
    assert _fve_device(hr).attrs["in_"] == "40"                    # 25 kW → 36 A → 40 A
    hr = _board(build_project({**spec, "chain": {**_EXIST_NN, "hr": {"main_in": 100}}}), "HR")
    assert next(e for e in hr.elements if e.attrs.get("desc") == "hlavní jistič").symbol_id == "fve.breaker_mcb"
    hr = _board(build_project({**spec, "chain": {**_EXIST_NN, "hr": {"main_in": 400, "fve_device": "fuse_disconnect",
                                                                       "fve_in": 125}}}), "HR")
    f = _fve_device(hr)
    assert f.symbol_id == "fve.fuse_disconnect" and f.attrs["in_"] == "125" and f.attrs["char"] == "gG"
    hr = _board(build_project({**spec, "chain": {**_EXIST_NN, "rd": {}, "hr": {"main_in": 250,
                                                                               "main_device": "switch"}}}), "HR")
    assert any(e.symbol_id == "sb.main_switch" for e in hr.elements)


def test_fve_fuse_up_to_80a_raises():
    import pytest
    spec = {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}]}
    for fve_in in (63, 80, None):          # None = dopočtené 40 A
        hr = {"main_in": 250, "fve_device": "fuse_disconnect", **({"fve_in": fve_in} if fve_in else {})}
        with pytest.raises(ValueError, match="do 80 A musí být jistič"):
            build_project({**spec, "chain": {**_EXIST_NN, "hr": hr}})
    with pytest.raises(ValueError, match="hlavní přístroj"):
        build_project({**spec, "chain": {**_EXIST_NN, "hr": {"main_device": "xx"}}})


def test_nn_hr_meter_metering_in_hr():
    """Topologie nn_hr_meter: bez RE, měření v HR stejnou funkcí jako v RE (HJ → elektroměr → vypínač instalace →
    přípojnice); hranice vlastnictví z presetu v HDS."""
    spec = {"topology": "nn_hr_meter", "inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}],
            "chain": _EXIST_NN}
    p = build_project(spec)
    assert "RE" not in _blocks(p)
    hr = _board(p, "HR")
    assert {e.attrs.get("desc") for e in hr.elements} >= {"hlavní jistič před elektroměrem", "vypínač instalace",
                                                          "vývod FVE"}
    assert any(e.symbol_id == "fve.meter" for e in hr.elements)
    hds = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.hds")
    assert hds.attrs.get("boundary") == "1" and len(p.sheets[0].texts) == 1
    p = build_project({**spec, "chain": {**_EXIST_NN, "hr": {"main_in": 250, "boundary": "re_meter"}}})
    assert next(e for e in _board(p, "HR").elements if e.symbol_id == "fve.meter").attrs.get("boundary") == "1"


def test_vn_chain_unchanged_by_nn_builders():
    """Na vn obsluhuje HR / RE dál přípojka VN (`mv`) – stávající RD / HR / RE builder nn se nepoužije."""
    p = build_project({"inverters": [{"ref": "T1", **_INV, "strings": [20]}], "connection": {"level": "vn"}})
    assert not any(e.symbol_id == "fve.hds" for e in p.sheets[0].elements)
    assert "XT" in {e.ref for e in _board(p, "HR").elements}


def test_chain_layout_compact_on_a2():
    """Řetězec stávajících článků: u firmy v řadě pod FV částí, u RD hned za RFVE – výkres 1–2 střídačů zůstane na
    jednom listu A2."""
    for spec in ({"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}], "chain": _EXIST_NN},
                 {**_HOUSE, "chain": _EXIST_RD},
                 {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}, {"ref": "T2", **_INV, "strings": [20]}],
                  "chain": _EXIST_NN}):
        p = build_project(spec)
        jps = [s for s in p.sheets if not s.is_switchboard]
        assert len(jps) == 1 and jps[0].paper == "A2", [s.paper for s in jps]


# ---- krok 6: kabely mezi články, jednofázový střídač ------------------------------------------------------------
def _link(p, a_ref, b_ref):
    s = next(s for s in p.sheets if not s.is_switchboard and any(e.ref == a_ref for e in s.elements))
    a = next(e for e in s.elements if e.ref == a_ref)
    b = next(e for e in s.elements if e.ref == b_ref)
    return next(w for w in s.wires if w.touches(a.id) and w.touches(b.id))


def test_min_cross():
    from envocad.model.calc import ampacity, min_cross
    assert min_cross(40, "D") == 10.0 and ampacity(6, "D") < 40 <= ampacity(10, "D")
    assert min_cross(16, "B1") == 2.5 and min_cross(15, "B1") == 1.5 and min_cross(0, "C") is None and min_cross(10_000, "C") is None
    assert min_cross(37, "B1", loaded=2) == 6.0


def test_chain_cables():
    """RFVE.AC → HR: kabel `chain.rfve_ac` > `ac.grid_*`; prázdný průřez nového úseku → min. průřez pro In vývodu
    FVE (40 A, uložení D → 10 mm²). Stávající HR → RE a RE → HDS bez údajů = vodič bez označení, se zadaným kabelem
    (prázdný průřez → pro In HJ v RE); HDS → DS vždy bez kabelu."""
    base = {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}]}
    p = build_project({**base, "chain": _EXIST_NN})
    w = _link(p, "RFVE.AC", "HR")
    assert (w.attrs["cable"], w.attrs["cross"], w.attrs["method"]) == ("CYKY-J 5x35", "35", "D")
    assert _link(p, "HR", "RE").attrs == {"ref": ""} and _link(p, "RE", "HDS").attrs == {"ref": ""}
    p = build_project({**base, "chain": {**_EXIST_NN, "rfve_ac": {"cable": "CYKY-J 5x10", "cross": "", "length": 12},
                                         "hr": {"main_in": 250, "cable": "AYKY 4x120", "method": "D"}}})
    w = _link(p, "RFVE.AC", "HR")
    assert (w.attrs["cable"], w.attrs["cross"], w.attrs["length"]) == ("CYKY-J 5x10", "10", "12")
    w = _link(p, "HR", "RE")
    assert w.attrs["ref"].startswith("W") and w.attrs["cable"] == "AYKY 4x120" and w.attrs["cross"] == "240"   # In HJ v RE 250 A, D
    assert w.conductors == ["L1", "L2", "L3", "N", "PE"]


def test_single_phase_inverter_ac_cable():
    """Jednofázový střídač: AC kabel 3 žíly L1 N PE s průřezem podle proudu (5 kW → 21,7 A, jistič 25 A, B1, úbytek
    do 3 % na 30 m → 6 mm²), v RFVE.AC přívodní větev se stejnými žilami a jistič 1+N 25 A; třífázový beze změny."""
    spec = {"inverters": [{"ref": "T1", "p_ac": 5, "phases": 1, **{k: v for k, v in _INV.items() if k != "p_ac"},
                           "strings": [12]},
                          {"ref": "T2", **_INV, "strings": [20]}], "chain": _EXIST_NN}
    p = build_project(spec)
    w1, w3 = _link(p, "T1", "RFVE.AC"), _link(p, "T2", "RFVE.AC")
    assert w1.conductors == ["L1", "N", "PE"] and (w1.attrs["cable"], w1.attrs["cross"]) == ("CYKY-J 3x6", "6")
    assert w3.conductors == ["L1", "L2", "L3", "N", "PE"] and w3.attrs["cable"] == "CYKY-J 5x16"
    ac = _board(p, "RFVE.AC")
    x1 = _el(ac, "X1")
    f = next(ac.element(w.b.element_id if w.a.element_id == x1.id else w.a.element_id) for w in ac.wires
             if w.touches(x1.id))
    assert (f.attrs["in_"], f.attrs["poles"]) == ("25", "2")
    assert all(w.conductors == ["L1", "N", "PE"] for w in ac.wires if w.touches(f.id))
    from envocad.library.store import LibraryStore
    from envocad.model.calc import check_cables
    assert not [c for c in check_cables(p) if c.ref == w1.attrs["ref"] and c.issues]
    assert LibraryStore() is not None


# ---- rozhodnutí (d): řetězec stávajících článků svisle – výkres jako před F2 --------------------------------------
# počet listů JPS případů snímku, které se na main (před F2) vešly na A2 / A3 – musí se vejít i teď
MAIN_JPS_SHEETS = {"default_1inv": 1, "two_inv": 1, "route2_terminals": 1, "with_component": 1,
                   "house_code_battery": 1, "house_2inv": 1, "house_3inv": 1, "apartment_optimizer": 1,
                   "vn_kobky_vn_1250": 2, "split_4x8": 5, "dc_disconnect": 1, "house_ac_only": 1, "house_terminals": 1,
                   "company_battery": 1, "fuse_in_unresolved": 1, "macro_values": 1, "two_inv_per_inverter": 1,
                   "nn_existing_fuse": 2, "nn_hr_meter": 1, "house_existing": 1, "inverter_1phase": 1}


@pytest.mark.parametrize("name", sorted(MAIN_JPS_SHEETS))
def test_snapshot_cases_fit_like_main(name):
    """Případy snímku, které se před F2 vešly na A2: stejný počet listů JPS, žádný větší než A2, vodiče se nekříží."""
    from generate_snapshot import CASES
    from test_feed_review import _crossings

    from envocad.generate import build_project as build
    p = build(CASES[name])
    jps = [s for s in p.sheets if not s.is_switchboard]
    assert [s.paper for s in jps if s.paper not in ("A3", "A2")] == [] and len(jps) == MAIN_JPS_SHEETS[name], \
        [s.paper for s in jps]
    if name in KNOWN_CROSSINGS:      # křížení mimo řetězec stávajících článků – stejně na main (ROADMAP)
        return
    lib = _lib()
    assert [(s.name, a, b) for s in jps for a, b in _crossings(p, s, lib)] == []


# známá křížení z doby před F2 (i na main): DC vodiče rozvaděče FVE ke 3. střídači rodinného domu, měřicí obvody
# XMI / XMU k RE u přípojky VN (kobky) – řeší se samostatně
KNOWN_CROSSINGS = {"house_3inv", "vn_kobky_vn_1250"}


@pytest.mark.parametrize("n,k,sheets", [(1, 6, 1), (2, 3, 1), (2, 4, 1), (3, 2, 1), (2, 6, 2), (4, 2, 2), (3, 3, 2)])
def test_company_chain_column_keeps_a2(n, k, sheets):
    """Firma (řetězec HR → RE → HDS → DS svisle pod RFVE.AC): jako před F2 – 1–2 střídače do 4 stringů na jednom
    listu A2, větší dělené listy A2 (žádný A1); vedení RFVE.AC → HR neobchází list (vede k HR shora zprava)."""
    p = build_project({"inverters": [{"ref": f"T{i}", **_INV, "strings": [20] * k} for i in range(1, n + 1)]})
    jps = [s for s in p.sheets if not s.is_switchboard]
    assert all(s.paper == "A2" for s in jps) and len(jps) == sheets, [s.paper for s in jps]   # listy jako na main
    s = jps[0]
    hr = _el(s, "HR")
    w = _link(p, "RFVE.AC", "HR")
    assert len(w.points) == 2 and w.points[0][0] == w.points[1][0]       # vpravo, svisle dolů, do X1 zprava
    lib = _lib()
    x1 = hr.port_pos(element_symbol(p, hr, lib), "X1")
    assert w.points[1][1] == x1[1] and w.points[1][0] > x1[0]


def test_house_chain_column_on_a2():
    """Rodinný dům se 2 střídači × 4 stringy (před F2 jeden list A2): řetězec RD → RE → HDS → DS svisle vpravo."""
    p = build_project({**_HOUSE, "inverters": [{"ref": f"T{i}", **_INV, "strings": [20] * 4} for i in (1, 2)]})
    jps = [s for s in p.sheets if not s.is_switchboard]
    assert [s.paper for s in jps] == ["A2"]


def test_close_gaps_and_stack_components():
    """Rozdělené JPS se společným RFVE.DC: list střídače bez prázdného pruhu po RFVE.DC (A2, ne A1); na listu AC
    a připojení u přípojky VN je RFVE.DC pod řetězcem (A2)."""
    p = build_project({"inverters": [{"ref": f"T{i}", **_INV, "strings": [20] * 8} for i in range(1, 5)],
                       "jps": {"split": "auto", "max_paper": "A2", "paper": "A2"}})
    assert [s.paper for s in p.sheets if not s.is_switchboard] == ["A2"] * 5
    p = build_project({"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}, {"ref": "T2", **_INV, "strings": [20]}],
                       "connection": {"level": "vn", "station": "kobky", "loop": False, "metering": "vn",
                                      "u_vn": "35 kV", "transformer": {"sn": 1250}}})
    assert [s.paper for s in p.sheets if not s.is_switchboard] == ["A2", "A2"]


# ---- krok 7: selektivita v řetězci přes listy, F7 ---------------------------------------------------------------
def _codes(p) -> dict[str, list]:
    from envocad.model.checks import check_project
    out: dict[str, list] = {}
    for f in check_project(p, _lib()):
        out.setdefault(f.code, []).append(f)
    return out


def _with_chain(**chain):
    return {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}], "chain": {**_EXIST_NN, **chain}}


def test_chain_roles_on_devices():
    """Generátor označí přístroje řetězce atributem `chain` (kontrola selektivity přes listy)."""
    p = build_project(_with_chain())
    roles = {e.attrs.get("chain") for s in p.sheets for e in s.elements if e.attrs.get("chain")}
    assert {"inv", "rfve_main", "fve_out", "main", "meter_main", "inst_switch"} <= roles
    hr = _board(p, "HR")
    assert next(e for e in hr.elements if e.attrs.get("chain") == "fve_out").attrs["desc"] == "vývod FVE"


def test_chain_selectivity_findings():
    """Nadřazené jištění přes list menší (HR 250 A → RE 160 A), rovné u HDS (RE 250 A = HDS 250 A) → varování
    `chain_selectivity`; hodnoty se nepřepisují."""
    from envocad.model.calc import check_selectivity_tree
    p = build_project(_with_chain(re={"main_in": 160}))
    msgs = [c.msg for c in check_selectivity_tree(p, _lib())]
    assert any("menší In (160 A < 250 A)" in m for m in msgs)
    assert "chain_selectivity" in _codes(p)
    assert next(e for e in _board(p, "RE").elements if e.attrs.get("chain") == "meter_main").attrs["in_"] == "160"
    p = build_project(_with_chain(hds={"in_": 250}))
    assert any("stejné In 250 A" in c.msg for c in check_selectivity_tree(p, _lib()))
    # zadaná In v pořádku → bez nálezů
    assert check_selectivity_tree(build_project(_with_chain()), _lib()) == []


def test_switch_below_protection_and_main_switch_sizing():
    """Hlavní vypínač RFVE.AC zadaný menší než vývod FVE, který ho chrání → varování (zadané se nepřepíše);
    nezadaný se dimenzuje nejméně na vývod FVE (9 střídačů → 400 A)."""
    spec = {"inverters": [{"ref": f"T{i}", **_INV, "strings": [20]} for i in range(1, 5)], "chain": dict(_EXIST_NN),
            "ac": {"main_in": 63}}
    p = build_project(spec)
    q = next(e for e in _board(p, "RFVE.AC").elements if e.attrs.get("chain") == "rfve_main")
    assert q.attrs["in_"] == "63"
    assert any("odpínač" in f.text for f in _codes(p)["chain_selectivity"])
    p = build_project({"inverters": [{"ref": f"T{i}", **_INV, "strings": [20]} for i in range(1, 10)],
                       "chain": {"hr": {"main_in": 630}, "re": {"main_in": 630}, "hds": {"in_": 800}}})
    q = next(e for e in _board(p, "RFVE.AC").elements if e.attrs.get("chain") == "rfve_main")
    assert q.attrs["in_"] == "400" and "chain_selectivity" not in _codes(p)


def test_hds_without_in_is_f7_error():
    p = build_project({"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}],
                       "chain": {"hr": {"main_in": 250}, "re": {"main_in": 250}}})
    hds = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.hds")
    assert hds.attrs["in_"] == "" and hds.attrs["in_unresolved"]
    f = [f for f in _codes(p)["breaker_no_in"] if f.target_id == hds.id]
    assert f and f[0].severity == "chyba"


def test_fve_out_fuse_le80_finding():
    """Ručně změněný vývod FVE na pojistku do 80 A → `fve_out_fuse_le80` (generátor to nedovolí – ValueError)."""
    p = build_project(_with_chain())
    qf = next(e for e in _board(p, "HR").elements if e.attrs.get("chain") == "fve_out")
    qf.symbol_id, qf.attrs["in_"] = "fve.fuse_disconnect", "63"
    assert "fve_out_fuse_le80" in _codes(p)


def test_eps_unconnected_finding():
    """Hybridní střídač s baterií, EPS vývod očekávaný (`eps`), BACKUP nevede na přepínač sítí → varování."""
    p = build_project({**_with_chain(), "battery": {"e_kwh": 10, "p_kw": 5, "type": "BYD"}})
    t = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.inverter_hybrid")
    assert "eps_unconnected" not in _codes(p)          # firma: EPS se nekreslí ani nehlásí
    t.attrs["eps"] = "1"
    assert "eps_unconnected" in _codes(p)


@pytest.mark.parametrize("spec", [
    {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}], "chain": _EXIST_NN},
    {"building": "apartment", "inverters": [{"ref": f"T{i}", **_INV, "strings": [20] * 3} for i in (1, 2)],
     "chain": _EXIST_NN},
    {"topology": "nn_hr_meter", "inverters": [{"ref": f"T{i}", **_INV, "strings": [20] * 3} for i in (1, 2)],
     "chain": {"hr": {"main_in": 250}, "hds": {"in_": 315}}},
    {"building": "house", "inverters": [{"ref": "T1", **_INV, "strings": [16, 16]}],
     "chain": {"rd": {"main_in": 80}, "re": {"main_in": 80}, "hds": {"in_": 100}}},
    # RD se 2 střídači nad 30 kWp (síťová ochrana): vícepól RFVE – DC stringy mimo stranu se sběrnými čarami
    {"building": "house", "inverters": [{"ref": f"T{i}", **_INV, "strings": [20, 20]} for i in (1, 2)],
     "chain": {"rd": {"main_in": 160}, "re": {"main_in": 160}, "hds": {"in_": 200}}},
])
def test_chain_f7_clean(spec):
    """Řetězec firma / BD / měření v HR / RD: F7 bez chyb a varování (vč. kódů F2), bez křížení na listech JPS."""
    from test_feed_review import _crossings

    from envocad.model.checks import ERROR, WARNING, check_project
    p = build_project(spec)
    lib = _lib()
    bad = [(f.code, f.ref, f.text) for f in check_project(p, lib) if f.severity in (ERROR, WARNING)]
    assert bad == []
    assert [(s.name, a, b) for s in p.sheets if not s.is_switchboard for a, b in _crossings(p, s, lib)] == []


# ---- krok 8: síťová ochrana nad 30 kWp ----------------------------------------------------------------------------
def _gp(p):
    return [e for s in p.sheets for e in s.elements if e.symbol_id == "fve.grid_protection"]


@pytest.mark.parametrize("macros", [None, {"dc_tech": "", "dc_route": "", "ac_feed": "", "ac_core": ""}])
@pytest.mark.parametrize("p_wp,expect", [(500, False), (501, True)])
def test_grid_protection_auto_threshold(p_wp, expect, macros):
    """30,0 kWp DC bez síťové ochrany, 30,06 kWp s ní (makra i kód); relé měří z vývodu 4 sběrnice a působí na
    hlavní vypínač; projekt nese hranici v meta."""
    spec = {"module": {"p_wp": p_wp}, "inverters": [{"ref": "T1", **_INV, "strings": [20, 20, 20]}],
            "chain": dict(_EXIST_NN)}
    if macros:
        spec["macros"] = macros
    p = build_project(spec)
    gp = _gp(p)
    assert bool(gp) is expect and p.meta["grid_protection_kwp"] == "30"
    if expect:
        sb = _board(p, "RFVE.AC")
        q = next(e for e in sb.elements if e.attrs.get("chain") == "rfve_main")
        assert gp[0].attrs["acts_on"] == q.ref
        bus = next(e for e in sb.elements if e.symbol_id == "sb.busbar")
        w = next(w for w in sb.wires if w.touches(gp[0].id))
        assert {w.a.element_id, w.b.element_id} == {bus.id, gp[0].id} and "4" in (w.a.port, w.b.port)
        assert "grid_protection_missing" not in _codes(p)


def test_grid_protection_override_and_house():
    base = {"inverters": [{"ref": "T1", **_INV, "strings": [20]}]}          # 9 kWp
    assert _gp(build_project({**base, "chain": {**_EXIST_NN, "rfve_ac": {"grid_protection": "1"}}}))
    big = {"inverters": [{"ref": "T1", **_INV, "strings": [20] * 4}]}         # 36 kWp
    p = build_project({**big, "chain": {**_EXIST_NN, "rfve_ac": {"grid_protection": "0"}}})
    assert not _gp(p) and "grid_protection_missing" in _codes(p)
    with pytest.raises(ValueError, match="grid_protection"):
        build_project({**base, "chain": {"rfve_ac": {"grid_protection": "možná"}}})
    p = build_project({"building": "house", **big})
    assert _gp(p) and _gp(p)[0] in _board(p, "RFVE").elements


def test_grid_protection_limit_from_standard(tmp_path, monkeypatch):
    import json

    from envocad.settings import settings_path
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"standard": {"grid_protection_kwp": 50}}), encoding="utf-8")
    p = build_project({"inverters": [{"ref": "T1", **_INV, "strings": [20] * 4}], "chain": dict(_EXIST_NN)})
    assert not _gp(p) and p.meta["grid_protection_kwp"] == "50" and "grid_protection_missing" not in _codes(p)


# ---- krok 9: EPS a přepínač sítí jen u RD ---------------------------------------------------------------------
_BAT = {"e_kwh": 10, "p_kw": 5, "type": "BYD HVS 10.2"}
_RD_INV = {"p_ac": 10, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
_EXIST_RD63 = {"rd": {"main_in": 63}, "re": {"main_in": 63}, "hds": {"in_": 80}}


@pytest.mark.parametrize("extra", [{}, {"macros": {"ac_eps": "EPS přepínač sítí"}}, {"dc": {"tech_box": False}},
                                   {"macros": {"dc_tech": "", "dc_route": "", "ac_feed": "", "ac_core": ""}}])
def test_eps_changeover_in_house(extra):
    """RD s hybridním střídačem a baterií: BACKUP → přerušení EPS-T1 → RFVE.XE1 → přepínač sítí (port 2), síť ze
    sběrnice (port 1), výstup → XB1 → „zálohované okruhy“; makro `ac_eps` i kód; F7 čisté, bez křížení."""
    from test_feed_review import _crossings

    from envocad.model.checks import ERROR, WARNING, check_project
    from envocad.model.inverter_io import inverter_io
    p = build_project({"building": "house", "inverters": [{"ref": "T1", **_RD_INV, "strings": [16, 16]}],
                       "battery": _BAT, "chain": _EXIST_RD63, **extra})
    s = p.sheets[0]
    t = next(e for e in s.elements if e.symbol_id == "fve.inverter_hybrid")
    assert t.attrs["eps"] == "1" and "BACKUP" in inverter_io(t.attrs)
    sb = _board(p, "RFVE")
    q = next(e for e in sb.elements if e.symbol_id == "fve.changeover_switch")
    by_id = {e.id: e for e in sb.elements}
    ends = {(w.a.port if w.a.element_id == q.id else w.b.port):
            by_id[w.b.element_id if w.a.element_id == q.id else w.a.element_id] for w in sb.wires if w.touches(q.id)}
    assert ends["1"].symbol_id == "sb.busbar" and ends["2"].ref == "XE1" and ends["3"].ref == "XB1"
    load = next(e for e in s.elements if e.symbol_id == "fve.load" and e.attrs.get("desc") == "zálohované okruhy")
    assert any(w.touches(load.id) and "XB1" in (w.a.port, w.b.port) for w in s.wires)
    assert len([e for e in s.elements if e.symbol_id == "fve.interrupt" and e.ref == "EPS-T1"]) == 2
    lib = _lib()
    bad = [(f.code, f.ref, f.text) for f in check_project(p, lib) if f.severity in (ERROR, WARNING)]
    assert bad == []
    assert [(a, b) for sh in p.sheets if not sh.is_switchboard for a, b in _crossings(p, sh, lib)] == []


def test_eps_not_for_company_or_without_battery():
    p = build_project({"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}], "battery": _BAT,
                       "chain": dict(_EXIST_NN)})
    assert not any(e.symbol_id == "fve.changeover_switch" for s in p.sheets for e in s.elements)
    assert not any(e.attrs.get("eps") for s in p.sheets for e in s.elements)
    p = build_project({"building": "house", "inverters": [{"ref": "T1", **_RD_INV, "strings": [16, 16]}],
                       "chain": _EXIST_RD63})
    assert not any(e.symbol_id in ("fve.changeover_switch", "fve.interrupt") for s in p.sheets for e in s.elements)


def test_eps_unconnected_when_backup_wire_removed():
    p = build_project({"building": "house", "inverters": [{"ref": "T1", **_RD_INV, "strings": [16, 16]}],
                       "battery": _BAT, "chain": _EXIST_RD63})
    assert "eps_unconnected" not in _codes(p)
    s = p.sheets[0]
    t = next(e for e in s.elements if e.symbol_id == "fve.inverter_hybrid")
    s.wires = [w for w in s.wires if not (w.touches(t.id) and "BACKUP" in (w.a.port, w.b.port))]
    assert "eps_unconnected" in _codes(p)


# ---- krok 10: skupiny střídačů na jiném místě (ac_group) ----------------------------------------------------------
def _grp(**kw):
    return {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]},
                          {"ref": "T2", **_INV, "strings": [20], "ac_group": "hala B"},
                          {"ref": "T3", **_INV, "strings": [20, 20]}], "chain": dict(_EXIST_NN), **kw}


def test_ac_groups_own_rfve_ac_and_feeder():
    """Střídače skupiny „hala B“ mají vlastní RFVE.AC2 (přívod X1), hlavní skupina RFVE.AC1 (X1, X2); HR má vývody FVE
    X1 (RFVE.AC1) a X3 (RFVE.AC2), X2 = stávající rozvody; kabel RFVE.AC2 → HR.X3 přes pár přerušení."""
    p = build_project(_grp(jps={"split": "none"}))
    b = _blocks(p)
    assert {"RFVE.AC1", "RFVE.AC2", "HR"} <= set(b)
    assert [e.ref for e in p.sheets[0].elements if e.symbol_id == "fve.inverter"] == ["T1", "T3", "T2"]  # po skupinách
    s = p.sheets[0]
    t2 = _el(s, "T2")
    w = next(w for w in s.wires if w.touches(t2.id) and "AC" in (w.a.port, w.b.port))
    assert {w.a.element_id, w.b.element_id} == {t2.id, b["RFVE.AC2"].id} and "X1" in (w.a.port, w.b.port)
    hr = _board(p, "HR")
    feeds = {e.ref: e for e in hr.elements if e.symbol_id == "sb.feed"}
    assert {"X1", "X2", "X3"} <= set(feeds)
    assert len([e for e in hr.elements if e.attrs.get("chain") == "fve_out"]) == 2
    ints = [e for e in s.elements if e.symbol_id == "fve.interrupt" and e.ref == "AC2-HR"]
    assert len(ints) == 2
    w_g = next(w for w in s.wires if w.touches(b["RFVE.AC2"].id) and "XOUT" in (w.a.port, w.b.port))
    assert w_g.attrs["cable"] and w_g.attrs["ref"].startswith("W")
    assert len(_board(p, "RFVE.AC2").elements) > 0 and "RFVE.AC" not in b


@pytest.mark.parametrize("extra", [{}, {"macros": {"dc_tech": "", "dc_route": "", "ac_feed": "", "ac_core": ""}},
                                   {"topology": "nn_hr_meter"}, {"building": "apartment"}])
def test_ac_groups_f7_clean(extra):
    from test_feed_review import _crossings

    from envocad.model.checks import ERROR, WARNING, check_project
    spec = _grp(**extra)
    if extra.get("topology") == "nn_hr_meter":
        spec["chain"] = {"hr": {"main_in": 250}, "hds": {"in_": 315}}
    p = build_project(spec)
    lib = _lib()
    assert [(f.code, f.ref, f.text) for f in check_project(p, lib) if f.severity in (ERROR, WARNING)] == []
    assert [(a, b) for s in p.sheets if not s.is_switchboard for a, b in _crossings(p, s, lib)] == []
    assert all(s.paper in ("A3", "A2") for s in p.sheets if not s.is_switchboard)


def test_ac_groups_only_nn_with_rfve_ac():
    with pytest.raises(ValueError, match="ac_group"):
        build_project(_grp(building="house"))
    with pytest.raises(ValueError, match="ac_group"):
        build_project(_grp(connection={"level": "vn"}))
    # jediná skupina (i pojmenovaná) = jeden společný RFVE.AC jako dřív
    p = build_project({"inverters": [{"ref": "T1", **_INV, "strings": [20], "ac_group": "A"}], "chain": _EXIST_NN})
    assert "RFVE.AC" in _blocks(p)
