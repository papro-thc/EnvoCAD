"""Volitelné značení rozvaděčů generátoru (issue #144): `board_prefix` = předpona podle druhu rozvaděče + číslo.
Bez volby zůstává dnešní značení beze změny."""
from __future__ import annotations

import pytest
from chain_data import build_project

pytestmark = pytest.mark.usefixtures("ac_builtin")

_INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
_SPEC = {"inverters": [{"ref": "T1", **_INV, "strings": [20]}, {"ref": "T2", **_INV, "strings": [20]}],
         "dc": {"route_boxes": 1}}


def _locs(p):
    return [sh.loc for sh in p.sheets if sh.is_switchboard]


def test_default_marking_unchanged():
    assert _locs(build_project(_SPEC)) == ["RDC1", "RDC2", "RFVE.DC", "RFVE.AC", "HR", "RE"]
    assert _locs(build_project({**_SPEC, "board_prefix": {}})) == _locs(build_project(_SPEC))


def test_board_prefix_applied_consistently():
    spec = {**_SPEC, "board_prefix": {"dc_route": "RDS", "dc_tech": "RTD", "ac": "RAC", "main": "HRN"},
            "chain": {"rfve_dc": {"per_inverter": True}}}
    p = build_project(spec)
    assert _locs(p) == ["RDS1", "RTD1", "RDS2", "RTD2", "RAC", "HRN", "RE"]
    blocks = {e.ref for e in p.sheets[0].elements if e.symbol_id == "fve.switchboard"}
    assert {"RDS1", "RDS2", "RTD1", "RTD2", "RAC", "HRN"} <= blocks
    assert not blocks & {"RDC1", "RDC2", "RFVE.DC1", "RFVE.AC", "HR"}
    # každý list rozvaděče má blok se stejným označením
    assert all(sh.loc in blocks | {"RE"} for sh in p.switchboards())


def test_explicit_chain_ref_beats_prefix():
    p = build_project({**_SPEC, "board_prefix": {"ac": "RAC"}, "chain": {"rfve_ac": {"ref": "RX"}}})
    assert "RX" in _locs(p) and "RAC" not in _locs(p)


def test_house_board_prefix():
    spec = {"building": "house", "inverters": [{"ref": "T1", **_INV, "strings": [10]}],
            "board_prefix": {"ac": "RHF"}}
    assert "RHF" in _locs(build_project(spec))


@pytest.mark.parametrize("prefix, msg", [
    ({"neznamy": "A"}, "Neznámý druh rozvaděče"),
    ({"ac": "rac x"}, "Neplatná předpona"),
    ({"ac": 5}, "Neplatná předpona"),
    ({"dc_route": "RX", "dc_tech": "RX"}, "stejná předpona"),
])
def test_invalid_prefix_czech_error(prefix, msg):
    with pytest.raises(ValueError, match=msg):
        build_project({**_SPEC, "board_prefix": prefix})


def test_prefix_not_a_mapping():
    with pytest.raises(ValueError, match="board_prefix"):
        build_project({**_SPEC, "board_prefix": "RDC"})


def test_vn_connection_prefix_and_feed_text():
    spec = {**_SPEC, "connection": {"level": "vn"},
            "board_prefix": {"ac": "RAC", "main": "HRN", "mv": "RV", "meter": "REM"}}
    p = build_project(spec)
    locs = _locs(p)
    assert {"RAC", "HRN", "REM"} <= set(locs) and not {"RFVE.AC", "HR", "RE"} & set(locs)
    texts = " ".join(str(e.attrs.get("desc", "")) for sh in p.sheets for e in sh.elements)
    assert "k RAC (FVE)" in texts and "RFVE.AC" not in texts
