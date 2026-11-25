"""Normové tabulky výpočtů Iz (`calc`) a oteplení (`thermal`) jako data – a jejich lokální přepsání (#82). Bez Qt.

Vestavěné hodnoty zůstávají v modulových konstantách `calc.py` / `thermal.py` (orientační). Projektant je může
přepsat souborem `~/.envocad/norms/*.json` (formát `envocad-norms`, popis v `docs/NORMY_FORMAT.md`); soubory norem
do gitu nepatří. Tento modul je čistá logika: `apply_document` ověří jeden dokument a vrátí nové tabulky (nic
nemutuje, nečte soubory). Čtení složky dělá `envocad.library.norms`, které `current()` líně naimportuje (stejný
vzor jako `model/checks.py` → `library.batteries`). Výpočet nikdy nespadne kvůli vadnému souboru: soubor se
odmítne celý a platí tabulky z dosavadního stavu (nejhůř vestavěné).

`BUILTIN` se skládá líně z konstant `calc` / `thermal` (modulové `__getattr__`), protože ty samy importují tento
modul kvůli `current()`.
"""
from __future__ import annotations

import dataclasses
import math
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

NORMS_FORMAT = "envocad-norms"
NORMS_FORMAT_VERSION = 1

MOUNTINGS = ("volně stojící", "nástěnná", "zapuštěná", "stojanová")
SURFACES = ("top", "bottom", "front", "back", "side")          # pořadí v n-tici činitele b
CURVES = ("k_large_no_vents", "k_small", "c_large_no_vents", "c_small")
SCALARS = {"iz_2_factor": "iz2_factor", "al_factor": "al_factor", "x_large": "x_large", "x_small": "x_small",
           "ae_limit_m2": "ae_limit_m2"}
TABLE_KEYS = ("iz", "k_temp_air", "d_partitions_no_vents", "b_factors") + CURVES + tuple(SCALARS)
IZ_KEY = "iz/cu/pvc70/3/"                                    # + způsob uložení
K_TEMP_KEY = "k_temp_air/pvc70"
SOURCE_REQUIRED = ("standard", "edition", "transcribed_by", "transcribed_on")
SOURCE_FIELDS = SOURCE_REQUIRED + ("year", "amendments", "checked_by", "note")


@dataclass(frozen=True)
class NormSource:
    """Odkud pochází přepsaná položka: soubor (cesta, SHA-256 jeho bajtů) a údaje z `source` + `ref` položky."""
    path: str
    sha256: str
    standard: str
    edition: str
    year: int
    ref: str
    transcribed_by: str
    transcribed_on: str


@dataclass(frozen=True)
class NormTables:
    """Všechny tabulky a činitele výpočtů. `sources[klíč]` = `NormSource`, nebo None = vestavěná hodnota.
    Klíče zdrojů: `iz/cu/pvc70/3/<způsob>`, `iz_2_factor`, `al_factor`, `k_temp_air/pvc70`, `k_large_no_vents`,
    `k_small`, `c_large_no_vents`, `c_small`, `d_partitions_no_vents`, `b_factors`, `x_large`, `x_small`,
    `ae_limit_m2`."""
    iz3: Mapping[str, Mapping[float, float]]
    iz2_factor: float
    al_factor: float
    k_t_pvc_air: Mapping[int, float]
    k_large_no_vents: tuple[tuple[float, float], ...]
    k_small: tuple[tuple[float, float], ...]
    c_large_no_vents: tuple[tuple[float, float], ...]
    c_small: tuple[tuple[float, float], ...]
    d_partitions_no_vents: Mapping[int, float]
    b_factors: Mapping[str, tuple[float, float, float, float, float]]   # (top, bottom, front, back, side)
    x_large: float
    x_small: float
    ae_limit_m2: float
    sources: Mapping[str, NormSource | None] = field(default_factory=dict)


@dataclass
class LoadReport:
    """Výsledek načtení složky norem: použité soubory, odmítnuté (cesta, chyby) a varování (i konflikty)."""
    files_used: list[str] = field(default_factory=list)
    files_rejected: list[tuple[str, list[str]]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---- BUILTIN (líně z konstant calc / thermal) ------------------------------------------------------------------
def _build_builtin() -> NormTables:
    from envocad.model import calc, thermal
    iz3 = {m: dict(t) for m, t in calc.IZ_3.items()}
    keys = [IZ_KEY + m for m in iz3] + [K_TEMP_KEY, "d_partitions_no_vents", "b_factors", *CURVES, *SCALARS]
    sources: dict[str, NormSource | None] = {k: None for k in keys}
    return NormTables(
        iz3=iz3, iz2_factor=calc.IZ_2_FACTOR, al_factor=calc.AL_FACTOR, k_t_pvc_air=dict(calc.K_T_PVC_AIR),
        k_large_no_vents=tuple(thermal.K_LARGE_NO_VENTS), k_small=tuple(thermal.K_SMALL),
        c_large_no_vents=tuple(thermal.C_LARGE_NO_VENTS), c_small=tuple(thermal.C_SMALL),
        d_partitions_no_vents=dict(thermal.D_PARTITIONS_NO_VENTS),
        b_factors={m: tuple(v) for m, v in thermal.B_FACTORS.items()},
        x_large=thermal.X_LARGE, x_small=thermal.X_SMALL, ae_limit_m2=thermal.AE_LIMIT_M2, sources=sources)


def __getattr__(name: str):
    if name == "BUILTIN":
        value = _build_builtin()
        globals()["BUILTIN"] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _builtin() -> NormTables:
    return globals().get("BUILTIN") or __getattr__("BUILTIN")


# ---- validace jednoho dokumentu --------------------------------------------------------------------------------
def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _text(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _warn_unknown(d: dict, allowed: Iterable[str], where: str, warnings: list[str]) -> None:
    for k in d:
        if k not in allowed:
            warnings.append(f"{where}: neznámé pole „{k}“ (ignorováno)")


def _points(item: dict, where: str, errors: list[str], *, x_min: float | None = 0.0, x_open: bool = False,
            y_positive: bool = True) -> list[tuple[float, float]]:
    """Body [[x, y], …]: ≥ 2 body, konečná čísla, x ostře vzestupně (x ≥ `x_min`, při `x_open` x > `x_min`),
    y > 0. Chyby do `errors`; vrací seznam bodů (při chybě může být neúplný)."""
    pts = item.get("points")
    if not isinstance(pts, list) or len(pts) < 2:
        errors.append(f"{where}: `points` musí být pole aspoň 2 bodů [x, y]")
        return []
    out: list[tuple[float, float]] = []
    for i, p in enumerate(pts):
        if not isinstance(p, (list, tuple)) or len(p) != 2 or not _num(p[0]) or not _num(p[1]):
            errors.append(f"{where}: bod #{i + 1} musí být dvojice konečných čísel [x, y]")
            return []
        x, y = p
        if x_min is not None and (x <= x_min if x_open else x < x_min):
            errors.append(f"{where}: bod #{i + 1}: x = {x:g} {'musí být > ' if x_open else 'nesmí být < '}"
                          f"{x_min:g}")
        if y_positive and y <= 0:
            errors.append(f"{where}: bod #{i + 1}: hodnota {y:g} musí být > 0")
        out.append((float(x), float(y)))
    for a, b in pairwise(out):
        if b[0] <= a[0]:
            errors.append(f"{where}: x musí růst ostře vzestupně ({a[0]:g} → {b[0]:g})")
            break
    return out


def _need_ref(item: Any, where: str, errors: list[str]) -> bool:
    if not isinstance(item, dict):
        errors.append(f"{where}: položka musí být objekt")
        return False
    if not _text(item.get("ref")):
        errors.append(f"{where}: chybí `ref` (odkaz na místo v normě)")
        return False
    return True


def _scalar(item: Any, where: str, errors: list[str], warnings: list[str]) -> float | None:
    if not _need_ref(item, where, errors):
        return None
    _warn_unknown(item, ("ref", "value", "unit", "note"), where, warnings)
    v = item.get("value")
    if not _num(v) or v <= 0:
        errors.append(f"{where}: `value` musí být konečné číslo > 0")
        return None
    return float(v)


def apply_document(doc: object, base: NormTables, path: str = "", sha256: str = "") -> tuple[NormTables | None,
                                                                                            list[str], list[str]]:
    """Ověří dokument `envocad-norms` a vrátí `(tabulky, chyby, varování)`; tabulky = `base` s přepsanými
    položkami, nebo None, když je soubor odmítnut (chyby neprázdné). Čistá funkce: `doc` ani `base` nemění."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        result = _apply(doc, base, path, sha256, errors, warnings)
    except Exception as ex:  # noqa: BLE001 – vadný soubor nesmí shodit výpočet
        errors.append(f"vnitřní chyba při ověření: {ex}")
        result = None
    if errors:
        return None, errors, warnings
    return result, errors, warnings


def _apply(doc: object, base: NormTables, path: str, sha256: str, errors: list[str],
           warnings: list[str]) -> NormTables | None:
    if not isinstance(doc, dict):
        errors.append("kořen souboru musí být objekt")
        return None
    if doc.get("format") != NORMS_FORMAT:
        errors.append(f"`format` musí být „{NORMS_FORMAT}“")
    ver = doc.get("format_version")
    if ver is None or isinstance(ver, bool) or not isinstance(ver, int):
        errors.append("`format_version` chybí nebo není celé číslo")
    elif not 1 <= ver <= NORMS_FORMAT_VERSION:
        errors.append(f"`format_version` {ver} program nepodporuje (umí 1 až {NORMS_FORMAT_VERSION})")
    src = doc.get("source")
    source_ok = isinstance(src, dict)
    if not source_ok:
        errors.append("chybí objekt `source` (údaje o normě)")
    else:
        for k in SOURCE_REQUIRED:
            if not _text(src.get(k)):
                errors.append(f"`source.{k}` chybí nebo je prázdné")
        year = src.get("year")
        if isinstance(year, bool) or not isinstance(year, int):
            errors.append("`source.year` chybí nebo není celé číslo")
        _warn_unknown(src, SOURCE_FIELDS, "source", warnings)
    tables = doc.get("tables")
    if not isinstance(tables, dict):
        errors.append("chybí objekt `tables`")
        return None
    for k in tables:
        if k not in TABLE_KEYS:
            errors.append(f"tables: neznámý klíč „{k}“")

    def make_source(item: dict) -> NormSource | None:
        if not source_ok:
            return None
        return NormSource(path, sha256, str(src.get("standard", "")), str(src.get("edition", "")),
                          src.get("year") if isinstance(src.get("year"), int) else 0, str(item.get("ref", "")),
                          str(src.get("transcribed_by", "")), str(src.get("transcribed_on", "")))

    iz3 = {m: dict(t) for m, t in base.iz3.items()}
    new: dict[str, Any] = {}
    sources = dict(base.sources)

    def put(key: str, item: dict) -> None:
        sources[key] = make_source(item)

    # Iz
    if "iz" in tables:
        items = tables["iz"]
        if not isinstance(items, list):
            errors.append("tables.iz: musí být pole položek")
            items = []
        seen: set[str] = set()
        for i, it in enumerate(items):
            where = f"tables.iz[{i}]"
            if not _need_ref(it, where, errors):
                continue
            _warn_unknown(it, ("conductor", "insulation", "loaded", "t_ref_c", "method", "ref", "unit", "points",
                               "note"), where, warnings)
            method, conductor, insulation = it.get("method"), it.get("conductor"), it.get("insulation")
            loaded, t_ref = it.get("loaded"), it.get("t_ref_c")
            if not _text(method) or not _text(conductor) or not _text(insulation):
                errors.append(f"{where}: `method`, `conductor` a `insulation` musí být neprázdný text")
                continue
            if isinstance(loaded, bool) or not isinstance(loaded, int) or not _num(t_ref):
                errors.append(f"{where}: `loaded` musí být celé číslo a `t_ref_c` číslo")
                continue
            if it.get("unit", "A") != "A":
                errors.append(f"{where}: `unit` musí být „A“")
                continue
            pts = _points(it, where, errors, x_min=0.0, x_open=True)
            if any(b[1] < a[1] for a, b in pairwise(pts)):
                errors.append(f"{where}: Iz nesmí s průřezem klesat")
            method = method.strip().upper()
            ident = f"{conductor}/{insulation}/{loaded}/{t_ref:g}/{method}"
            if ident in seen:
                errors.append(f"{where}: duplicitní položka {ident}")
                continue
            seen.add(ident)
            if (conductor, insulation, loaded, t_ref) != ("cu", "pvc70", 3, 30):
                warnings.append(f"{where}: kombinace {conductor}/{insulation}/{loaded} vodiče/{t_ref:g} °C se "
                                f"zatím nepoužívá (implementováno jen cu/pvc70/3/30) – přeskočeno")
            elif method not in base.iz3:
                warnings.append(f"{where}: způsob uložení „{method}“ program nezná "
                                f"({', '.join(base.iz3)}) – přeskočeno")
            elif pts:
                iz3[method] = dict(pts)
                put(IZ_KEY + method, it)
    # skaláry
    for key, attr in SCALARS.items():
        if key in tables:
            v = _scalar(tables[key], f"tables.{key}", errors, warnings)
            if v is not None:
                new[attr] = v
                put(key, tables[key])
    # křivky
    for key in CURVES:
        if key in tables:
            it = tables[key]
            where = f"tables.{key}"
            if _need_ref(it, where, errors):
                _warn_unknown(it, ("ref", "points", "unit", "note"), where, warnings)
                pts = _points(it, where, errors)
                if pts:
                    new[key] = tuple(pts)
                    put(key, it)
    # činitel přepážek
    if "d_partitions_no_vents" in tables:
        it, where = tables["d_partitions_no_vents"], "tables.d_partitions_no_vents"
        if _need_ref(it, where, errors):
            _warn_unknown(it, ("ref", "points", "unit", "note"), where, warnings)
            pts = _points(it, where, errors)
            if pts and any(x != int(x) for x, _ in pts):
                errors.append(f"{where}: počet přepážek (x) musí být celé číslo")
            elif pts:
                d = {int(x): y for x, y in pts}
                if not all(n in d for n in range(4)):
                    errors.append(f"{where}: chybí hodnota pro 0, 1, 2 nebo 3 přepážky")
                else:
                    new["d_partitions_no_vents"] = d
                    put("d_partitions_no_vents", it)
    # teplotní činitel
    if "k_temp_air" in tables:
        items = tables["k_temp_air"]
        if not isinstance(items, list):
            errors.append("tables.k_temp_air: musí být pole položek")
            items = []
        seen_ins: set[str] = set()
        for i, it in enumerate(items):
            where = f"tables.k_temp_air[{i}]"
            if not _need_ref(it, where, errors):
                continue
            _warn_unknown(it, ("insulation", "ref", "points", "unit", "note"), where, warnings)
            ins = it.get("insulation")
            if not _text(ins):
                errors.append(f"{where}: `insulation` musí být neprázdný text")
                continue
            pts = _points(it, where, errors, x_min=None)
            if ins in seen_ins:
                errors.append(f"{where}: duplicitní položka pro izolaci {ins}")
                continue
            seen_ins.add(ins)
            if ins != "pvc70":
                warnings.append(f"{where}: izolace „{ins}“ se zatím nepoužívá (implementováno jen pvc70) – "
                                f"přeskočeno")
            elif pts:
                keys = [round(x) for x, _ in pts]
                if len(set(keys)) != len(keys):
                    errors.append(f"{where}: teploty po zaokrouhlení na celé °C nejsou jedinečné")
                else:
                    new["k_t_pvc_air"] = {k: y for k, (_, y) in zip(keys, pts)}
                    put(K_TEMP_KEY, it)
    # činitel b
    if "b_factors" in tables:
        it, where = tables["b_factors"], "tables.b_factors"
        if _need_ref(it, where, errors):
            _warn_unknown(it, ("ref", "value", "unit", "note"), where, warnings)
            b = _b_factors(it.get("value"), where, errors, warnings)
            if b is not None:
                new["b_factors"] = b
                put("b_factors", it)
    if errors:
        return None
    return dataclasses.replace(base, iz3=iz3, sources=sources, **new)


def _b_factors(value: Any, where: str, errors: list[str], warnings: list[str]):
    if not isinstance(value, dict):
        errors.append(f"{where}: `value` musí být objekt (montáž → plochy)")
        return None
    out: dict[str, tuple[float, ...]] = {}
    ok = True
    for m in MOUNTINGS:
        faces = value.get(m)
        if not isinstance(faces, dict):
            errors.append(f"{where}: chybí montáž „{m}“")
            ok = False
            continue
        vals = []
        for s in SURFACES:
            v = faces.get(s)
            if not _num(v) or v < 0 or (v == 0 and s != "bottom"):
                errors.append(f"{where}.{m}.{s}: musí být konečné číslo "
                              f"{'≥ 0' if s == 'bottom' else '> 0'}")
                ok = False
                vals.append(0.0)
            else:
                vals.append(float(v))
        _warn_unknown(faces, SURFACES, f"{where}.{m}", warnings)
        out[m] = tuple(vals)
    _warn_unknown(value, MOUNTINGS, where, warnings)
    return out if ok else None


# ---- vyhledání položky / přepsání zpět na vestavěné -------------------------------------------------------------
def reset_keys(tables: NormTables, keys: Iterable[str], builtin: NormTables | None = None) -> NormTables:
    """Vrátí `tables`, kde se položky `keys` (klíče zdrojů) vrátily na vestavěné hodnoty."""
    b = builtin or _builtin()
    iz3 = {m: dict(t) for m, t in tables.iz3.items()}
    changes: dict[str, Any] = {}
    sources = dict(tables.sources)
    for key in keys:
        if key.startswith("iz/"):
            m = key.rsplit("/", 1)[-1]
            if m in b.iz3:
                iz3[m] = dict(b.iz3[m])
        elif key == K_TEMP_KEY:
            changes["k_t_pvc_air"] = dict(b.k_t_pvc_air)
        else:
            attr = SCALARS.get(key, key)
            changes[attr] = getattr(b, attr)
        sources[key] = None
    return dataclasses.replace(tables, iz3=iz3, sources=sources, **changes)


# ---- aktuální tabulky (cache) ----------------------------------------------------------------------------------
_state: dict[str, Any] = {}


def _load() -> None:
    env = os.environ.get("ENVOCAD_HOME") or ""
    if _state and _state.get("env") == env:
        return
    builtin = _builtin()
    try:
        from envocad.library import norms
        key = str(norms.norms_dir().resolve())
        if _state and _state.get("key") == key:
            _state["env"] = env
            return
        tables, report = norms.load_dir(norms.norms_dir(), builtin)
    except Exception as ex:  # noqa: BLE001 – složka norem nesmí shodit výpočet
        key, tables = "", builtin
        report = LoadReport(warnings=[f"složku norem se nepodařilo načíst: {ex}"])
    _state.clear()
    _state.update(env=env, key=key, tables=tables, report=report)


def current() -> NormTables:
    """Tabulky platné pro výpočty: vestavěné přepsané soubory z `~/.envocad/norms/` (při prvním volání načteno,
    změny souborů se nesledují – až `reload()`). Bez souborů je to přímo `BUILTIN`."""
    _load()
    return _state["tables"]


def load_report() -> LoadReport:
    _load()
    return _state["report"]


def provenance(keys: Iterable[str] | None = None) -> dict[str, NormSource | None]:
    """Zdroj položek (None = vestavěná hodnota); bez `keys` všechny."""
    src = current().sources
    if keys is None:
        return dict(src)
    return {k: src.get(k) for k in keys}


def is_builtin(key: str) -> bool:
    return current().sources.get(key) is None


def clear_cache() -> None:
    _state.clear()


def reload() -> NormTables:
    clear_cache()
    return current()
