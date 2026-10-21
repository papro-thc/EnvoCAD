"""Údaje stávajících článků řetězce pro testy generátoru (F2, docs/design/topologie_f1_f2.md, kap. 2): In
stávajících přístrojů projektant zadá (průvodce je vyžaduje) – bez nich generátor nechá In prázdné a kontrola projektu
hlásí chybu `breaker_no_in`. Testy, které ověřují „F7 bez chyb“, je doplní přes `with_existing`."""
from __future__ import annotations

EXIST_NN = {"hr": {"main_in": 250}, "re": {"main_in": 250}, "hds": {"in_": 315}}
EXIST_RD = {"rd": {"main_in": 40}, "re": {"main_in": 40}, "hds": {"in_": 50}}


def with_existing(spec: dict) -> dict:
    """Specifikace doplněná o In stávajících článků (RD u rodinného domu, jinak HR); zadané `chain` má přednost.
    Velká FVE (vývod FVE nad 25 A u RD / 156 A u firmy): hlavní jistič ≥ 1,6 × vývod FVE (selektivita v listu)."""
    from envocad.generator.boards.mv import LV_FEEDER_SIZES, _next_size, inverters_ac_current
    house = str(spec.get("building") or "").strip().lower() in ("house", "rodinný dům", "rd")
    base = {k: dict(v) for k, v in (EXIST_RD if house else EXIST_NN).items()}
    i_fve = inverters_ac_current(spec.get("inverters") or [])
    if i_fve:
        main = _next_size(1.6 * _next_size(i_fve, LV_FEEDER_SIZES), LV_FEEDER_SIZES)
        for role in ("rd", "hr", "re"):
            if role in base and main > base[role]["main_in"]:
                base[role]["main_in"] = main
        if main * 1.25 > base["hds"]["in_"]:
            base["hds"]["in_"] = _next_size(main * 1.25, LV_FEEDER_SIZES)
    given = spec.get("chain") or {}
    return {**spec, "chain": {**base, **given}}


def build_project(spec: dict):
    """`envocad.generate.build_project` se specifikací doplněnou o stávající články (`with_existing`)."""
    from envocad.generate import build_project as _build
    return _build(with_existing(spec))
