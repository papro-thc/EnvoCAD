"""Ukázkový plugin: vlastní kontrola projektu (`ctx.add_check`). Slouží jako vzor pro vlastní pluginy.

Čistě formální kontrola bez oborových pravidel: upozorní (INFO), že dva listy mají stejný název."""
from __future__ import annotations

from collections import Counter

from envocad.model.checks import INFO, Finding

REQUIRES_API = 1


def duplicate_sheet_names(project, lib) -> list[Finding]:
    counts = Counter(s.name for s in project.sheets)
    return [Finding(INFO, s.id, s.name, "", False, "", f"Více listů se stejným názvem „{s.name}“", "dup_sheet_name")
            for s in project.sheets if counts[s.name] > 1]


def register(ctx) -> None:
    ctx.add_check(duplicate_sheet_names)
