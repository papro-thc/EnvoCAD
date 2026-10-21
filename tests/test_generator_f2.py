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
