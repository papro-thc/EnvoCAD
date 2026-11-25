"""Referenční sady (tests/data/ref_*.json) a jejich mechanismus (tests/ref_sets.py). Syntetické sady používají
VYMYSLENÁ čísla; reálné sady jsou v gitu prázdné (`cases: []`), dokud vlastník nedodá případy ze Sichru."""
from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path

import pytest
import ref_sets

from envocad.model import norm_tables, thermal

DATA = Path(__file__).parent / "data"
SETS = {"ref_iz.json": "iz", "ref_thermal.json": "thermal"}
FAKE_B1 = {1.5: 1, 2.5: 2, 4: 3}
FAKE = dataclasses.replace(norm_tables.BUILTIN, iz3={**norm_tables.BUILTIN.iz3, "B1": FAKE_B1})


@pytest.fixture(autouse=True)
def _clean_norm_cache():
    norm_tables.clear_cache()
    yield
    norm_tables.clear_cache()


def origin(**over) -> dict:
    o = {"tool": "Sichr", "tool_version": "0.0", "date": "2099-01-01", "url": "", "supplied_by": "PR", "note": ""}
    o.update(over)
    return o


def iz_case(cid="iz-001", expected=2, tol=None, **inputs) -> dict:
    base = {"function": "ampacity", "cross": 2.5, "method": "B1", "loaded": 3, "aluminium": False,
            "t_ambient": 30, "grouping": 1}
    base.update(inputs)
    case = {"id": cid, "description": "", "tables": "builtin", "inputs": base, "expected": {"iz_a": expected},
            "origin": origin()}
    if tol is not None:
        case["tolerance"] = {"iz_a": tol}
    return case


def thermal_case(cid="th-001", expected=None, tol=None) -> dict:
    case = {"id": cid, "tables": "builtin",
            "inputs": {"width_mm": 600, "height_mm": 800, "depth_mm": 250, "mounting": "nástěnná", "p_total_w": 50,
                       "partitions": 0, "plastic": False},
            "expected": expected or {"dt_mid_k": 1.0}, "origin": origin()}
    if tol is not None:
        case["tolerance"] = tol
    return case


def iz_set(*cases, tol=None) -> dict:
    return {"format": "envocad-refset", "format_version": 1, "kind": "iz",
            "tolerance": {"iz_a": tol or {"abs": None, "rel": None}}, "cases": list(cases)}


NO_TOL = {"iz_a": {"abs": None, "rel": None}}


# ---- reálné sady -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(SETS))
def test_real_refset_schema_is_valid(name):
    doc = ref_sets.load_refset(DATA / name)
    assert ref_sets.validate_refset(doc) == []
    assert doc["kind"] == SETS[name]
    ids = [c["id"] for c in doc["cases"]]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("name", sorted(SETS))
def test_real_refset_tolerance_shape(name):
    """Tvar tolerance v sadě v gitu: každá veličina má právě klíče abs a rel (hodnoty smí být null; žádná výchozí konstanta)."""
    doc = ref_sets.load_refset(DATA / name)
    assert doc["tolerance"]
    for tol in doc["tolerance"].values():
        assert set(tol) == {"abs", "rel"}


@pytest.mark.parametrize("name", sorted(SETS))
def test_real_refset_cases_pass(name):
    """Projde všechny případy sady; prázdná sada není chyba. Případy `tables: norms` bez `ENVOCAD_REF_NORMS` skip."""
    doc = ref_sets.load_refset(DATA / name)
    problems, skipped = [], 0
    for case in doc["cases"]:
        try:
            tables = ref_sets.resolve_tables(case)
        except pytest.skip.Exception:
            skipped += 1
            continue
        problems += ref_sets.run_case(case, doc["tolerance"], tables)
    assert problems == []
    if doc["cases"] and skipped == len(doc["cases"]):
        pytest.skip("všechny případy vyžadují ENVOCAD_REF_NORMS")


# ---- validate_refset -------------------------------------------------------------------------------------------
def test_validate_accepts_synthetic_sets():
    assert ref_sets.validate_refset(iz_set(iz_case())) == []
    assert ref_sets.validate_refset(iz_set()) == []
    doc = {"format": "envocad-refset", "format_version": 1, "kind": "thermal",
           "tolerance": {"dt_mid_k": {"abs": 1, "rel": None}}, "cases": [thermal_case()]}
    assert ref_sets.validate_refset(doc) == []
    min_case = iz_case("m-1", 2.5, function="min_cross")
    min_case["inputs"] = {"function": "min_cross", "in_a": 2, "method": "B1"}
    min_case["expected"] = {"cross_mm2": 2.5}
    assert ref_sets.validate_refset(iz_set(min_case)) == []


def test_validate_reports_duplicate_ids():
    errs = ref_sets.validate_refset(iz_set(iz_case("a"), iz_case("a")))
    assert errs and any("a" in e for e in errs)


@pytest.mark.parametrize("field", ["tool", "tool_version", "date", "supplied_by"])
def test_validate_origin_fields_required(field):
    for broken in (None, "", "  "):
        case = iz_case()
        if broken is None:
            del case["origin"][field]
        else:
            case["origin"][field] = broken
        assert ref_sets.validate_refset(iz_set(case)), (field, broken)


def test_validate_origin_url_may_be_empty_and_origin_required():
    case = iz_case()
    case["origin"]["url"] = ""
    assert ref_sets.validate_refset(iz_set(case)) == []
    del case["origin"]
    assert ref_sets.validate_refset(iz_set(case))


def test_validate_origin_date_format():
    case = iz_case()
    case["origin"]["date"] = "1.1.2099"
    assert ref_sets.validate_refset(iz_set(case))


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(format="x"),
    lambda d: d.update(format_version=2),
    lambda d: d.update(kind="jine"),
    lambda d: d.pop("cases"),
    lambda d: d.update(cases={}),
    lambda d: d["cases"][0].pop("id"),
    lambda d: d["cases"][0].update(tables="jine"),
    lambda d: d["cases"][0].pop("expected"),
    lambda d: d["cases"][0].update(expected={}),
    lambda d: d["cases"][0].update(expected={"iz_a": "dva"}),
    lambda d: d["cases"][0]["inputs"].pop("cross"),
    lambda d: d["cases"][0]["inputs"].update(function="jina"),
    lambda d: d["cases"][0]["inputs"].update(neznamy=1),
    lambda d: d["cases"][0].update(tolerance={"iz_a": {"abs": -1, "rel": None}}),
    lambda d: d["cases"][0].update(tolerance={"iz_a": {"abs": "1", "rel": None}}),
    lambda d: d["cases"][0].update(tolerance={"neco": {"abs": 1, "rel": None}}),
    lambda d: d.update(tolerance={"iz_a": {"abs": True}}),
])
def test_validate_rejects_schema_errors(mutate):
    doc = iz_set(iz_case())
    mutate(doc)
    assert ref_sets.validate_refset(doc)


def test_validate_non_object_root():
    assert ref_sets.validate_refset([]) and ref_sets.validate_refset(None)


def test_validate_thermal_expected_subset():
    doc = {"format": "envocad-refset", "format_version": 1, "kind": "thermal", "tolerance": {},
           "cases": [thermal_case(expected={"ae_m2": 1, "dt_top_k": 2})]}
    assert ref_sets.validate_refset(doc) == []
    doc["cases"][0]["expected"] = {"neznama": 1}
    assert ref_sets.validate_refset(doc)
    doc["cases"][0]["expected"] = {}
    assert ref_sets.validate_refset(doc)


def test_load_refset_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(iz_set(iz_case()), ensure_ascii=False), encoding="utf-8")
    assert ref_sets.load_refset(p) == iz_set(iz_case())


# ---- within ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("actual,expected,tol,ok", [
    (2.5, 2.0, {"abs": 0.5, "rel": None}, True),           # přesně na hranici
    (2.6, 2.0, {"abs": 0.5, "rel": None}, False),
    (1.5, 2.0, {"abs": 0.5, "rel": None}, True),
    (1.4, 2.0, {"abs": 0.5, "rel": None}, False),
    (105, 100, {"abs": None, "rel": 0.05}, True),
    (106, 100, {"abs": None, "rel": 0.05}, False),
    (-105, -100, {"abs": None, "rel": 0.05}, True),
    (101, 100, {"abs": 0.1, "rel": 0.05}, True),            # platí větší z obou
    (110, 100, {"abs": 20, "rel": 0.05}, True),
    (2, 2, {"abs": 0, "rel": None}, True),
    (2.1, 2, {"abs": 0, "rel": None}, False),
])
def test_within(actual, expected, tol, ok):
    assert ref_sets.within(actual, expected, tol) is ok


# ---- run_case --------------------------------------------------------------------------------------------------
def test_run_case_inside_and_outside_tolerance():
    inside = iz_case(expected=2.4, tol={"abs": 0.5, "rel": None})
    outside = iz_case(expected=2.6, tol={"abs": 0.5, "rel": None})
    assert ref_sets.run_case(inside, NO_TOL, FAKE) == []
    probs = ref_sets.run_case(outside, NO_TOL, FAKE)
    assert len(probs) == 1 and "iz-001" in probs[0]


def test_run_case_relative_tolerance():
    assert ref_sets.run_case(iz_case(expected=2.04, tol={"abs": None, "rel": 0.05}), NO_TOL, FAKE) == []
    assert ref_sets.run_case(iz_case(expected=2.2, tol={"abs": None, "rel": 0.05}), NO_TOL, FAKE)


def test_run_case_missing_tolerance_fails_with_message():
    probs = ref_sets.run_case(iz_case(expected=2), NO_TOL, FAKE)
    assert len(probs) == 1 and "tolerance neurčena" in probs[0]
    probs = ref_sets.run_case(iz_case(expected=2), {}, FAKE)
    assert len(probs) == 1 and "tolerance neurčena" in probs[0]


def test_run_case_default_tolerance_and_case_override():
    default = {"iz_a": {"abs": 1, "rel": None}}
    assert ref_sets.run_case(iz_case(expected=2.9), default, FAKE) == []
    assert ref_sets.run_case(iz_case(expected=2.9, tol={"abs": 0.1, "rel": None}), default, FAKE)   # případ přepisuje
    assert ref_sets.run_case(iz_case(expected=2.9, tol={"abs": 5, "rel": None}), NO_TOL, FAKE) == []


def test_run_case_min_cross_is_exact():
    case = iz_case("m-1")
    case["inputs"] = {"function": "min_cross", "in_a": 2, "method": "B1", "loaded": 3, "aluminium": False,
                      "t_ambient": 30}
    case["expected"] = {"cross_mm2": 2.5}
    assert ref_sets.run_case(case, {}, FAKE) == []                   # tolerance se neuplatní ani nevyžaduje
    case["expected"] = {"cross_mm2": 4}
    case["tolerance"] = {"cross_mm2": {"abs": 100, "rel": None}}
    probs = ref_sets.run_case(case, {}, FAKE)
    assert len(probs) == 1 and "m-1" in probs[0]


def test_run_case_thermal_subset_and_tolerance():
    exp = thermal.enclosure_rise(600, 800, 250, "nástěnná", 50)
    case = thermal_case(expected={"ae_m2": exp.ae_m2, "dt_mid_k": exp.dt_mid_k + 0.4})
    tol = {"ae_m2": {"abs": 1e-9, "rel": None}, "dt_mid_k": {"abs": 0.5, "rel": None}}
    assert ref_sets.run_case(case, tol, norm_tables.BUILTIN) == []
    case["expected"]["dt_mid_k"] = exp.dt_mid_k + 0.6
    assert len(ref_sets.run_case(case, tol, norm_tables.BUILTIN)) == 1
    # veličina bez tolerance → "tolerance neurčena", ostatní se porovnají
    probs = ref_sets.run_case(case, {"ae_m2": tol["ae_m2"]}, norm_tables.BUILTIN)
    assert len(probs) == 1 and "tolerance neurčena" in probs[0]


def test_run_case_uses_tables_param_not_cache():
    case = iz_case(expected=2, tol={"abs": 0.01, "rel": None})
    assert ref_sets.run_case(case, NO_TOL, FAKE) == []
    assert ref_sets.run_case(case, NO_TOL, norm_tables.BUILTIN)      # vestavěné B1(2,5 mm²) není 2
    assert norm_tables.current() is norm_tables.BUILTIN


# ---- resolve_tables: builtin / norms ---------------------------------------------------------------------------
def _norm_file(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    doc = {"format": "envocad-norms", "format_version": 1,
           "source": {"standard": "PŘÍKLAD", "edition": "e", "year": 2099, "transcribed_by": "PR",
                      "transcribed_on": "2099-01-01"},
           "tables": {"iz": [{"conductor": "cu", "insulation": "pvc70", "loaded": 3, "t_ref_c": 30, "method": "B1",
                              "ref": "r", "unit": "A", "points": [[1.5, 1], [2.5, 2], [4, 3]]}]}}
    (folder / "a.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_builtin_case_runs_without_env(monkeypatch):
    monkeypatch.delenv("ENVOCAD_REF_NORMS", raising=False)
    assert ref_sets.resolve_tables({"id": "x", "tables": "builtin"}) is norm_tables.BUILTIN


def test_norms_case_skips_without_env(monkeypatch):
    monkeypatch.delenv("ENVOCAD_REF_NORMS", raising=False)
    for case in ({"id": "x", "tables": "norms"}, {"id": "y"}):             # norms je výchozí
        with pytest.raises(pytest.skip.Exception):
            ref_sets.resolve_tables(case)


def test_norms_case_uses_tables_from_env_folder(tmp_path, monkeypatch):
    folder = tmp_path / "moje_normy"
    _norm_file(folder)
    monkeypatch.setenv("ENVOCAD_REF_NORMS", str(folder))
    tables = ref_sets.resolve_tables({"id": "x", "tables": "norms"})
    assert tables.iz3["B1"] == FAKE_B1
    case = iz_case(expected=2, tol={"abs": 0.01, "rel": None})
    case["tables"] = "norms"
    assert ref_sets.run_case(case, NO_TOL, tables) == []
    assert norm_tables.current() is norm_tables.BUILTIN                  # nikdy do cache


def test_norms_case_in_real_set_flow(tmp_path, monkeypatch):
    """Celý tok: sada v tmp_path → validace → resolve_tables → run_case."""
    folder = tmp_path / "n"
    _norm_file(folder)
    monkeypatch.setenv("ENVOCAD_REF_NORMS", str(folder))
    case = iz_case(expected=2.2, tol={"abs": 0.5, "rel": None})
    case["tables"] = "norms"
    doc = iz_set(case, copy.deepcopy(case) | {"id": "iz-002", "expected": {"iz_a": 9}})
    p = tmp_path / "s.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    loaded = ref_sets.load_refset(p)
    assert ref_sets.validate_refset(loaded) == []
    results = [ref_sets.run_case(c, loaded["tolerance"], ref_sets.resolve_tables(c)) for c in loaded["cases"]]
    assert results[0] == [] and len(results[1]) == 1


def test_norms_case_fails_when_folder_rejected_or_empty(tmp_path, monkeypatch):
    """Nenačtené tabulky nesmí tiše skončit u vestavěných hodnot: odmítnutý soubor / prázdná složka = fail."""
    bad = tmp_path / "spatne"
    bad.mkdir()
    (bad / "a.json").write_text("{nejson", encoding="utf-8")
    empty = tmp_path / "prazdna"
    empty.mkdir()
    for folder in (bad, empty):
        monkeypatch.setenv("ENVOCAD_REF_NORMS", str(folder))
        with pytest.raises(pytest.fail.Exception) as ex:
            ref_sets.resolve_tables({"id": "x", "tables": "norms"})
        assert "vestavěnými" in str(ex.value)
    assert "a.json" in _fail_text(bad, monkeypatch)


def _fail_text(folder, monkeypatch) -> str:
    monkeypatch.setenv("ENVOCAD_REF_NORMS", str(folder))
    with pytest.raises(pytest.fail.Exception) as ex:
        ref_sets.resolve_tables({"id": "x", "tables": "norms"})
    return str(ex.value)
