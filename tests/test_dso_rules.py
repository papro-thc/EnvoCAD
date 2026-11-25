"""Instalovaný výkon a kategorie výrobního modulu podle distributora (issue #133)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from envocad.export.tz_data import dso_data
from envocad.generator.build import build_project
from envocad.library.distributors import BUILTIN_DIR, load_distributor_rules
from envocad.library.store import LibraryStore
from envocad.model.dso_rules import category_of, find_rule, installed_power, parse_rule

RULES = list(load_distributor_rules())


def rule(rid: str):
    return next(r for r in RULES if r.id == rid)


@pytest.mark.parametrize("kw,cat", [
    (0.8, "A1"), (10.999, "A1"), (11, "A1"), (11.001, "A2"), (99.999, "A2"), (100, "B1"), (999.999, "B1"),
    (1000, "B2"), (29999.999, "B2"), (30000, "C"), (74999.999, "C"), (75000, "D"), (200000, "D"),
])
@pytest.mark.parametrize("rid", ["cez", "egd", "pre", "zsd"])
def test_category_boundaries(rid, kw, cat):
    assert category_of(rule(rid), kw) == cat


def test_float_sum_on_boundary():
    assert category_of(rule("cez"), sum([0.1] * 110)) == "A1"   # 11.000000000000002
    assert category_of(rule("cez"), sum([0.1] * 1000)) == "B1"


@pytest.mark.parametrize("rid", ["cez", "egd", "pre"])
def test_hybrid_pv_basis(rid):
    res = installed_power(rule(rid), p_pv_kwp=15.0, p_ac_kw=10.0)
    assert (res.kw, res.category) == (15.0, "A2")


def test_hybrid_zsd_uses_ac():
    res = installed_power(rule("zsd"), p_pv_kwp=15.0, p_ac_kw=10.0)
    assert (res.kw, res.category) == (10.0, "A1")
    res = installed_power(rule("zsd"), p_pv_kwp=9.0, p_ac_kw=100.0)
    assert (res.kw, res.category) == (100.0, "B1")


def test_hybrid_cez_boundary_differs_from_zsd():
    assert installed_power(rule("cez"), 11.04, 11.0).category == "A2"
    assert installed_power(rule("zsd"), 11.04, 11.0).category == "A1"


def test_no_power_no_result():
    assert installed_power(rule("cez"), 0, 10) is None
    assert installed_power(rule("zsd"), 10, 0) is None


def test_find_rule():
    assert find_rule(RULES, "ČEZ Distribuce").id == "cez"
    assert find_rule(RULES, "EG.D").id == "egd"
    assert find_rule(RULES, "PREdistribuce").id == "pre"
    assert find_rule(RULES, "PRE").id == "pre"
    assert find_rule(RULES, "ZSD").id == "zsd"
    assert find_rule(RULES, "") is None
    assert find_rule(RULES, "Neznámý distributor") is None


def test_rules_are_data_with_sources():
    files = sorted(Path(BUILTIN_DIR).glob("*.json"))
    assert {f.stem for f in files} == {"cez", "egd", "pre", "zsd"}
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["source_url"].startswith("https://") and len(d["verified_on"]) == 10
    assert [r.basis for r in RULES if r.id != "zsd"] == ["pv_kwp"] * 3 and rule("zsd").basis == "inverter_ac_kw"


def test_parse_rule_rejects_bad_data():
    with pytest.raises(ValueError):
        parse_rule({"id": "x"})
    with pytest.raises(ValueError):
        parse_rule({"id": "x", "installed_power_basis": "foo", "categories": [{"id": "A", "upper_kw": None}]})


def _spec(dso, p_ac=25, strings=(20, 20)):
    return {"name": "FVE", "inverters": [{"ref": "T1", "p_ac": p_ac, "u_dc_max": 1100, "u_mppt_min": 200,
                                          "u_mppt_max": 1000, "strings": list(strings)}], "grid": {"dso": dso}}


def test_report_rows_cez_uses_panels():
    rows = dict(dso_data(build_project(_spec("ČEZ Distribuce", p_ac=10)), LibraryStore()))
    assert rows["Instalovaný výkon Pi dle distributora"].startswith("18 kW (Σ kWp panelů")
    assert rows["Kategorie výrobního modulu"] == "A2"


def test_report_rows_zsd_uses_ac():
    rows = dict(dso_data(build_project(_spec("ZSD", p_ac=10)), LibraryStore()))
    assert rows["Instalovaný výkon Pi dle distributora"].startswith("10 kW (Σ AC výkonů střídačů")
    assert rows["Kategorie výrobního modulu"] == "A1"


def test_report_rows_unknown_distributor_neuvedeno():
    for dso in ("", "Jiný provozovatel"):
        rows = dict(dso_data(build_project(_spec(dso)), LibraryStore()))
        assert rows["Instalovaný výkon Pi dle distributora"] == "neuvedeno"
        assert rows["Kategorie výrobního modulu"] == "neuvedeno"


def test_manual_total_has_priority():
    p = build_project(_spec("EG.D"))
    p.meta["p_installed_total_kw"] = "100"
    rows = dict(dso_data(p, LibraryStore()))
    assert rows["Instalovaný výkon Pi dle distributora"].startswith("100 kW (zadáno ručně")
    assert rows["Kategorie výrobního modulu"] == "B1"
