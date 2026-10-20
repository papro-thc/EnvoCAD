"""Společný kontext generátoru FVE (bez Qt): knihovna sdílená během jednoho sestavení, pomocné převody hodnot
specifikace a konstanty označení. Návrh `docs/design/topologie_f1_f2.md`, kap. 1.3 (krok 1).

Všechny moduly generátoru berou knihovnu přes `context._lib()` (volání atributu modulu, ne kopie importovaná jménem) –
jediné místo pro `monkeypatch.setattr(context, "_lib", …)` v testech; `_BUILD_LIB` nastavuje `build_project`.
Logger zůstává `"envocad.generate"` (zachované jméno pro nastavení logování a testy).
"""
from __future__ import annotations

import logging

log = logging.getLogger("envocad.generate")


BATTERY_ROW_EXTRA = 40.0   # místo pro baterii pod hybridním střídačem (mm)
INV_LABEL_SPACE = 40.0     # popisek DC kabelu („W12  2× H1Z2Z2-K 1x6 mm²“) mezi blokem rozvaděče a lomy ke střídači


# Označení rozvaděčů (docs/NAVRH_TOPOLOGIE.md, kap. 8 bod 9): AC rozvaděč FVE RFVE.AC, DC rozvaděč u technologie
# RFVE.DC (víc rozvaděčů u technologie – jeden na střídač – RFVE.DC1, RFVE.DC2… v pořadí střídačů), rozvaděče po
# trase RDC1…n (číslované jen mezi sebou), hlavní rozvaděč nn u přípojky VN HR; rodinný dům jeden rozvaděč RFVE.
AC_SWITCHBOARD_REF = "RFVE.AC"
DC_TECH_BOX_REF = "RFVE.DC"
DC_ROUTE_BOX_PREFIX = "RDC"
MAIN_LV_BOARD_REF = "HR"


# kabel baterie (hybridní střídač → baterie), když ho specifikace (`battery.cable/cross/length`) nezadá
BATTERY_CABLE = {"cable": "H1Z2Z2-K 1x25", "cross": 25, "length": 5}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def _s(v) -> str:
    return "" if v is None else str(v)


_BUILD_LIB = None    # knihovna sdílená během jednoho `build_project` (otevření LibraryStore = synchronizace souborů)
# Globál modulu, ne stav vlákna: `build_project` ho nastaví na začátku a v `finally` vrátí None. Neplatí pro souběžné
# sestavení z více vláken – druhé vlákno by vidělo cizí knihovnu jako „vnořené volání“ (SQLite spojení patří vláknu,
# které ho otevřelo → ProgrammingError) a konec prvního sestavení by ji druhému vzal. Generátor se volá z jednoho
# vlákna (GUI, CLI, testy); sestavení v pracovním vlákně jen tehdy, když jiné neběží.


def _lib():
    """Knihovna pro generátor: během `build_project` jedna instance pro celé sestavení (`_BUILD_LIB`), jinak nová.
    `_BUILD_LIB` je společný pro celý proces – z jiného vlákna během běžícího sestavení se `_lib` nevolá (viz výše)."""
    if _BUILD_LIB is not None:
        return _BUILD_LIB
    from envocad.library.store import LibraryStore
    return LibraryStore()


AC_MAX_INVERTERS_BUS = 12   # přívody T1…T12 sběrnice sb.busbar (`tools/gen_builtin_fve.BUSBAR_INPUTS`)


def _num_or(v, default: float) -> float:
    try:
        return float(str(v).replace(",", ".").split()[0])
    except (TypeError, ValueError, IndexError):
        return default


def _int_attr(v) -> int | None:
    """Kladné celé číslo z atributu („2“, „2.0“, „2,0“), jinak None."""
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(x) if x >= 1 else None


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
