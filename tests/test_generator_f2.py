"""Generátor F2 – nové články řetězce (docs/design/topologie_f1_f2.md, kap. 2; rozhodnutí docs/NAVRH_TOPOLOGIE.md,
kap. 8): označení z presetů, společný RFVE.DC, HDS, RE na nn, stávající RD / HR, kabely mezi články."""
from __future__ import annotations

from envocad.generate import build_project
from envocad.generator.spec import chain_flag, chain_options, node_ref
from envocad.library.topologies import load_topologies

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
