"""Generátor F2 – nové články řetězce (docs/design/topologie_f1_f2.md, kap. 2; rozhodnutí docs/NAVRH_TOPOLOGIE.md,
kap. 8): označení z presetů, společný RFVE.DC, HDS, RE na nn, stávající RD / HR, kabely mezi články."""
from __future__ import annotations

from envocad.generate import build_project
from envocad.generator.spec import chain_flag, chain_options, node_ref
from envocad.library.topologies import load_topologies

_INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


def _blocks(p) -> dict[str, object]:
    return {e.ref: e for e in p.sheets[0].elements if e.symbol_id == "fve.switchboard"}


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
            **kw}


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
    p = build_project(_two(chain={"rfve_dc": {"per_inverter": True}}))
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
            "jps": {"split": "auto", "max_paper": "A2", "paper": "A2"}}
    p = build_project(spec)
    jps = [s for s in p.sheets if not s.is_switchboard]
    assert len(jps) == 5 and jps[0].name == JPS_AC_SHEET_NAME
    assert any(e.ref == "RFVE.DC" for e in jps[0].elements)
    lib = LibraryStore()
    assert not [f for f in check_project(p, lib) if f.severity in (ERROR, WARNING)]
    _root, nodes = build_tree(p, lib, dc=True)
    assert sum(n.element.symbol_id == "fve.pv_string" for n in nodes.values()) == 32
