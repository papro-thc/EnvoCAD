"""Pomocný modul referenčních sad (tests/data/ref_*.json): kontrola schématu a porovnání výpočtu EnvoCAD s hodnotami
z externího nástroje (např. Sichr). Formát a postup zápisu případu: docs/NORMY_FORMAT.md.

Modul neobsahuje žádné normové hodnoty ani výchozí tolerance – tolerance určuje vlastník v souboru sady."""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

import pytest

REFSET_FORMAT = "envocad-refset"
REFSET_FORMAT_VERSION = 1
ENV_NORMS = "ENVOCAD_REF_NORMS"
KINDS = {"iz": ("iz_a", "cross_mm2"), "thermal": ("ae_m2", "k", "c", "dt_mid_k", "dt_top_k")}
IZ_FUNCTIONS = {
    "ampacity": ({"cross"}, {"method", "loaded", "aluminium", "t_ambient", "grouping"}, "iz_a"),
    "min_cross": ({"in_a"}, {"method", "loaded", "aluminium", "t_ambient"}, "cross_mm2"),
}
THERMAL_INPUTS = ({"width_mm", "height_mm", "depth_mm", "mounting", "p_total_w"}, {"partitions", "plastic"})
THERMAL_QUANTITIES = KINDS["thermal"]
ORIGIN_REQUIRED = ("tool", "tool_version", "date", "supplied_by")
ORIGIN_ALLOWED = ORIGIN_REQUIRED + ("url", "note")
TABLES_MODES = ("builtin", "norms")


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def load_refset(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _tolerance_errors(tol: Any, where: str, allowed: tuple[str, ...]) -> list[str]:
    if not isinstance(tol, dict):
        return [f"{where}: tolerance musí být objekt"]
    errs = []
    for name, spec in tol.items():
        if name not in allowed:
            errs.append(f"{where}: neznámá veličina tolerance „{name}“")
            continue
        if not isinstance(spec, dict) or set(spec) - {"abs", "rel"}:
            errs.append(f"{where}.{name}: očekáváno {{\"abs\": …, \"rel\": …}}")
            continue
        for key in ("abs", "rel"):
            v = spec.get(key)
            if v is not None and (not _is_number(v) or v < 0):
                errs.append(f"{where}.{name}.{key}: musí být null nebo číslo ≥ 0")
    return errs


def _case_errors(case: Any, idx: int, kind: str) -> list[str]:
    if not isinstance(case, dict):
        return [f"případ #{idx}: musí být objekt"]
    cid = case.get("id")
    name = f"případ {cid!r}" if isinstance(cid, str) and cid else f"případ #{idx}"
    errs = []
    if not isinstance(cid, str) or not cid:
        errs.append(f"{name}: chybí id")
    if case.get("tables", "norms") not in TABLES_MODES:
        errs.append(f"{name}: tables musí být {' / '.join(TABLES_MODES)}")
    inputs, expected = case.get("inputs"), case.get("expected")
    if not isinstance(inputs, dict):
        errs.append(f"{name}: chybí inputs")
        inputs = {}
    if not isinstance(expected, dict) or not expected:
        errs.append(f"{name}: expected musí být neprázdný objekt")
        expected = {}
    allowed_tol: tuple[str, ...] = ("iz_a", "cross_mm2")
    if kind == "iz":
        fn = inputs.get("function")
        if fn not in IZ_FUNCTIONS:
            errs.append(f"{name}: inputs.function musí být {' / '.join(IZ_FUNCTIONS)}")
        else:
            req, opt, out = IZ_FUNCTIONS[fn]
            keys = set(inputs) - {"function"}
            if req - keys:
                errs.append(f"{name}: chybí vstupy {sorted(req - keys)}")
            if keys - req - opt:
                errs.append(f"{name}: neznámé vstupy {sorted(keys - req - opt)}")
            if expected and set(expected) != {out}:
                errs.append(f"{name}: expected musí obsahovat právě {out}")
            allowed_tol = (out,)
    else:
        req, opt = THERMAL_INPUTS
        keys = set(inputs)
        if req - keys:
            errs.append(f"{name}: chybí vstupy {sorted(req - keys)}")
        if keys - req - opt:
            errs.append(f"{name}: neznámé vstupy {sorted(keys - req - opt)}")
        if set(expected) - set(THERMAL_QUANTITIES):
            errs.append(f"{name}: neznámé veličiny v expected {sorted(set(expected) - set(THERMAL_QUANTITIES))}")
        allowed_tol = THERMAL_QUANTITIES
    for k, v in expected.items():
        if not _is_number(v):
            errs.append(f"{name}: expected.{k} musí být číslo")
    if "tolerance" in case:
        errs += _tolerance_errors(case["tolerance"], f"{name}.tolerance", allowed_tol)
    origin = case.get("origin")
    if not isinstance(origin, dict):
        errs.append(f"{name}: chybí origin")
    else:
        for k in ORIGIN_REQUIRED:
            if not isinstance(origin.get(k), str) or not origin[k].strip():
                errs.append(f"{name}: origin.{k} je povinné a nesmí být prázdné")
        if isinstance(origin.get("date"), str) and origin["date"].strip() \
                and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", origin["date"]):
            errs.append(f"{name}: origin.date musí být RRRR-MM-DD")
        if "url" in origin and not isinstance(origin["url"], str):
            errs.append(f"{name}: origin.url musí být text")
        extra = set(origin) - set(ORIGIN_ALLOWED)
        if extra:
            errs.append(f"{name}: neznámá pole origin {sorted(extra)}")
    return errs


def validate_refset(doc: Any) -> list[str]:
    """Chyby schématu referenční sady (prázdný seznam = v pořádku); včetně duplicitních `id`."""
    if not isinstance(doc, dict):
        return ["kořen sady musí být objekt"]
    errs = []
    if doc.get("format") != REFSET_FORMAT:
        errs.append(f"format musí být „{REFSET_FORMAT}“")
    if doc.get("format_version") != REFSET_FORMAT_VERSION or isinstance(doc.get("format_version"), bool):
        errs.append(f"format_version musí být {REFSET_FORMAT_VERSION}")
    kind = doc.get("kind")
    if kind not in KINDS:
        errs.append(f"kind musí být {' / '.join(KINDS)}")
        return errs
    errs += _tolerance_errors(doc.get("tolerance"), "tolerance", KINDS[kind])
    cases = doc.get("cases")
    if not isinstance(cases, list):
        return errs + ["cases musí být pole"]
    seen: set[str] = set()
    for i, case in enumerate(cases):
        errs += _case_errors(case, i, kind)
        cid = case.get("id") if isinstance(case, dict) else None
        if isinstance(cid, str) and cid:
            if cid in seen:
                errs.append(f"duplicitní id „{cid}“")
            seen.add(cid)
    return errs


def within(actual: float, expected: float, tol: dict) -> bool:
    """|a − e| ≤ max(abs or 0, (rel or 0)·|e|)."""
    limit = max(tol.get("abs") or 0.0, (tol.get("rel") or 0.0) * abs(expected))
    return abs(actual - expected) <= limit


def resolve_tables(case: dict):
    """Tabulky pro případ: `builtin` vždy vestavěné; `norms` (výchozí) jen s `ENVOCAD_REF_NORMS=<složka>` – jinak
    `pytest.skip`. Tabulky se načtou přes `library.norms.load_dir` a předají parametrem, nikdy do cache."""
    from envocad.library import norms
    from envocad.model import norm_tables
    if case.get("tables", "norms") == "builtin":
        return norm_tables.BUILTIN
    folder = os.environ.get(ENV_NORMS)
    if not folder:
        pytest.skip(f"případ {case.get('id')}: bez {ENV_NORMS} (lokální normové tabulky) se neběží")
    tables, _report = norms.load_dir(Path(folder))
    return tables


def _compute(inputs: dict, tables) -> dict[str, float | None]:
    from envocad.model import calc, thermal
    args = dict(inputs)
    if "function" in args:
        fn = args.pop("function")
        if fn == "ampacity":
            return {"iz_a": calc.ampacity(**args, tables=tables)}
        return {"cross_mm2": calc.min_cross(**args, tables=tables)}
    r = thermal.enclosure_rise(**args, tables=tables)
    return {"ae_m2": r.ae_m2, "k": r.k, "c": r.c, "dt_mid_k": r.dt_mid_k, "dt_top_k": r.dt_top_k}


def run_case(case: dict, default_tolerance: dict, tables) -> list[str]:
    """Porovná výpočet s `expected`; vrací seznam neshod (prázdný = OK). `min_cross` se porovnává přesně. Druh
    případu se pozná podle `inputs.function` (iz) – jinak jde o `thermal.enclosure_rise`."""
    cid = case.get("id", "?")
    actual = _compute(case["inputs"], tables)
    exact = case["inputs"].get("function") == "min_cross"
    problems = []
    for name, exp in case["expected"].items():
        act = actual.get(name)
        if act is None:
            problems.append(f"{cid}: {name}: výpočet nevrátil hodnotu, očekáváno {exp}")
            continue
        if exact:
            if act != exp:
                problems.append(f"{cid}: {name}: vypočteno {act}, očekáváno {exp}")
            continue
        tol = dict((default_tolerance or {}).get(name) or {})
        tol.update((case.get("tolerance") or {}).get(name) or {})
        if tol.get("abs") is None and tol.get("rel") is None:
            problems.append(f"{cid}: {name}: tolerance neurčena")
        elif not within(act, exp, tol):
            problems.append(f"{cid}: {name}: vypočteno {act}, očekáváno {exp}, tolerance {tol}")
    return problems
