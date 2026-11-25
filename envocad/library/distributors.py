"""Pravidla distributorů (instalovaný výkon, kategorie výrobního modulu) – načtení z `builtin/distributors/*.json`.

Bez Qt. Vadný soubor se vynechá (záznam v logu). Model pravidel: `envocad/model/dso_rules.py`.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from envocad.model.dso_rules import DistributorRule, parse_rule

log = logging.getLogger("envocad.library")

BUILTIN_DIR = Path(__file__).parent / "builtin" / "distributors"


@lru_cache(maxsize=1)
def load_distributor_rules() -> tuple[DistributorRule, ...]:
    out = []
    for f in sorted(BUILTIN_DIR.glob("*.json")):
        try:
            out.append(parse_rule(json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError) as e:
            log.warning("pravidlo distributora %s vynecháno: %s", f.name, e)
    return tuple(out)
