"""Pravidla distributorů: instalovaný výkon Pi a kategorie výrobního modulu (A1…D). Bez Qt.

Čistá funkce nad daty pravidla (`DistributorRule`); samotná pravidla a hranice jsou data v
`envocad/library/builtin/distributors/*.json` (načítá `envocad.library.distributors`), ne v kódu.
Hranice: dolní mez patří do vyšší kategorie (11 kW včetně = A1, 100 kW = B1, 1 MW = B2); `upper_inclusive` říká,
zda horní mez patří do kategorie (jen A1).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

BASES = ("pv_kwp", "inverter_ac_kw")   # Σ kWp panelů | Σ AC výkonů střídačů


@dataclass(frozen=True)
class Category:
    id: str
    upper_kw: float | None       # None = bez horní meze
    upper_inclusive: bool = False


@dataclass(frozen=True)
class DistributorRule:
    id: str
    name: str
    basis: str
    categories: tuple[Category, ...]
    aliases: tuple[str, ...] = ()
    source_url: str = ""
    verified_on: str = ""
    note: str = field(default="", compare=False)


@dataclass(frozen=True)
class InstalledPower:
    kw: float
    category: str
    basis: str


def parse_rule(data: dict) -> DistributorRule:
    """Pravidlo z JSON slovníku; `ValueError` při chybějícím/neplatném údaji."""
    try:
        basis = data["installed_power_basis"]
        if basis not in BASES:
            raise ValueError(f"neznámý základ výkonu {basis!r}")
        cats = tuple(Category(str(c["id"]), None if c.get("upper_kw") is None else float(c["upper_kw"]),
                              bool(c.get("upper_inclusive", False))) for c in data["categories"])
        if not cats or cats[-1].upper_kw is not None:
            raise ValueError("poslední kategorie musí být bez horní meze")
        bounds = [c.upper_kw for c in cats[:-1]]
        if any(b is None for b in bounds) or bounds != sorted(bounds):
            raise ValueError("hranice kategorií musí růst")
        return DistributorRule(str(data["id"]), str(data.get("name", data["id"])), basis, cats,
                               tuple(str(a) for a in data.get("aliases", ())), str(data.get("source_url", "")),
                               str(data.get("verified_on", "")), str(data.get("note", "")))
    except (KeyError, TypeError) as e:
        raise ValueError(f"neúplné pravidlo distributora: {e}") from e


def _tokens(text: str) -> list[str]:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower().replace(".", "")
    return "".join(ch if ch.isalnum() else " " for ch in s).split()


def find_rule(rules: list[DistributorRule], name: str) -> DistributorRule | None:
    """Pravidlo podle volného názvu distributora („ČEZ Distribuce“, „EG.D“…); neznámý/prázdný název → None."""
    toks = _tokens(name)
    if not toks:
        return None
    for r in rules:
        for alias in (r.id, *r.aliases):
            a = _tokens(alias)
            if a and any(toks[i:i + len(a)] == a for i in range(len(toks) - len(a) + 1)):
                return r
    return None


def category_of(rule: DistributorRule, p_kw: float) -> str:
    """Kategorie podle výkonu v kW (zaokrouhleno na 1 mW proti chybě součtu desetinných čísel)."""
    p = round(p_kw, 6)
    for c in rule.categories:
        if c.upper_kw is None or p < c.upper_kw or (c.upper_inclusive and p == c.upper_kw):
            return c.id
    return rule.categories[-1].id


def installed_power(rule: DistributorRule, p_pv_kwp: float, p_ac_kw: float) -> InstalledPower | None:
    """Pi a kategorie podle pravidla distributora; chybí-li výkon základu (≤ 0), vrací None (nehádat)."""
    p = p_pv_kwp if rule.basis == "pv_kwp" else p_ac_kw
    if not p or p <= 0:
        return None
    return InstalledPower(p, category_of(rule, p), rule.basis)
