"""Proudy střídačů a jištění na straně AC (bez Qt): jistič přívodu střídače, vývod FVE v RD / HR a hlavní vypínač
AC rozvaděče FVE. Jedno místo pro pravidla – používá je list RFVE.AC (vestavěný kód i mustr), blok bez listu
(atributy `inv_protect`, `protect`), stávající RD / HR (vývod FVE) i EPS (přepínač sítí).

Pravidla (review F2, D1 / D2 / B3):
- proud střídače: `i_ac_max_a` artiklu (`component_id`), jinak z P AC (3f: P / (√3 · 400 V), 1f: P / 230 V);
- automatický jistič přívodu střídače: nejbližší velikost řady ≥ 1,25 × proud (z artiklu i z P AC); nad
  řadou (3f do 250 A, 1f do 63 A) zůstane In prázdné s důvodem (`in_unresolved`, chyba F7) – nic se nedosazuje;
- vývod FVE v RD / HR (nezadaný): nejbližší velikost ≥ max(Σ proudů střídačů, největší jistič střídače) – jako u vn;
- hlavní vypínač AC rozvaděče FVE (nezadaný): nejméně výchozí 125 A a nejméně vývod FVE (jinak by odpínač ležel
  pod In jištění, které ho chrání – F7 `chain_selectivity`); proud z vygenerovaných prvků střídačů (i z artiklu
  bez `p_ac` ve specifikaci).
"""
from __future__ import annotations

import math

from envocad.generator import context
from envocad.generator.context import _num, _s
from envocad.model.project import Element

AC3_BREAKER_SIZES = (10, 13, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125, 160, 200, 250)
AC1_BREAKER_SIZES = (10, 13, 16, 20, 25, 32, 40, 50, 63)
BREAKER_FACTOR = 1.25          # jistič ≥ 1,25 × max. AC proud střídače (z artiklu i z P AC)
U_3F, U_1F = 400.0, 230.0
MAIN_SWITCH_MIN = 125.0        # výchozí hlavní vypínač AC rozvaděče FVE (`DEFAULT_SPEC.ac.main_in`)


def _attrs(inv) -> dict:
    return inv.attrs if isinstance(inv, Element) else (inv or {})


def single_phase(inv) -> bool:
    return (_num(_attrs(inv).get("phases")) or 3) == 1


def _article_current(inv) -> float | None:
    cid = inv.component_id if isinstance(inv, Element) else _attrs(inv).get("component_id")
    if not cid:
        return None
    try:
        comp = context._lib().component(cid)
    except Exception:  # noqa: BLE001 – knihovna nedostupná → bez artiklu
        return None
    v = comp.num("i_ac_max_a") if comp is not None else None
    return v if v and v > 0 else None


def inverter_current(inv) -> tuple[float | None, str]:
    """(max. AC proud střídače [A], zdroj „artikl“ | „P“); neznámý → (None, ""). `inv` = prvek nebo slovník
    specifikace."""
    i = _article_current(inv)
    if i is not None:
        return i, "artikl"
    p_kw = _num(_attrs(inv).get("p_ac"))
    if not p_kw:
        return None, ""
    return p_kw * 1000 / (U_1F if single_phase(inv) else math.sqrt(3) * U_3F), "P"


def inverter_breaker(inv) -> tuple[str, str]:
    """In automatického jističe přívodu střídače a důvod prázdného In (nad řadou). Neznámý proud → ("", "")
    (volající ponechá zadanou / výchozí hodnotu)."""
    i, _src = inverter_current(inv)
    if i is None:
        return "", ""
    need = i * BREAKER_FACTOR
    sizes = AC1_BREAKER_SIZES if single_phase(inv) else AC3_BREAKER_SIZES
    x = next((s for s in sizes if s >= need - 1e-9), None)
    if x is None:
        ref = _s(_attrs(inv).get("ref"))
        return "", (f"proud střídače {ref} {need:.0f} A je nad řadou jističů přívodu (max. {sizes[-1]} A) – "
                    "zvolte jištění ručně")
    return f"{x:g}", ""


def breaker_ins(spec: dict, inverters) -> list[float]:
    """In jističů přívodů střídačů: automatické (`ac.breaker_in_auto`) podle proudu, jinak zadané `ac.breaker_in`."""
    ac = spec.get("ac") or {}
    auto = bool(_s(ac.get("breaker_in_auto")))
    out = []
    for t in inverters:
        v = _num(inverter_breaker(t)[0]) if auto else None
        if v is None:
            v = _num(ac.get("breaker_in"))
        if v:
            out.append(v)
    return out


def fve_current(inverters) -> float:
    """Σ max. AC proudů střídačů [A] (`inverter_current`); neznámé = 0."""
    return sum(inverter_current(t)[0] or 0.0 for t in inverters)


def fve_out_in(spec: dict, inverters) -> str:
    """In vývodu FVE (RD / HR) pro střídače `inverters`: nejbližší velikost ≥ max(Σ proudů, největší jistič
    střídače); nic neznámého → ""."""
    from envocad.generator.boards.mv import LV_FEEDER_SIZES, _next_size
    need = max([fve_current(inverters), *breaker_ins(spec, inverters)], default=0.0)
    return f"{_next_size(need, LV_FEEDER_SIZES):g}" if need else ""


def main_switch_in(spec: dict, inverters) -> str:
    """In nezadaného hlavního vypínače AC rozvaděče FVE: nejméně 125 A a nejméně vývod FVE (`fve_out_in`)."""
    return f"{max(MAIN_SWITCH_MIN, _num(fve_out_in(spec, inverters)) or 0.0):g}"
