"""Atribuce značek QElectroTech (CC BY 3.0) – issue #81."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEAD_LINK = "qelectrotech.org/wiki/doc/elements_license"
ML_RE = re.compile(r"strojov\w+\s+učení|machine[\s-]learning", re.IGNORECASE)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def attribution() -> str:
    return _read("envocad/library/builtin/qet/ATTRIBUTION.md")


@pytest.mark.parametrize(
    "needle",
    [
        "creativecommons.org/licenses/by/3.0",
        "github.com/qelectrotech/qelectrotech-elements",
        "ELEMENTS.LICENSE",
        "JSON",
        "2,5 mm",
        "mřížk",
    ],
)
def test_attribution_contains(attribution, needle):
    assert needle.lower() in attribution.lower()


def test_attribution_no_dead_link(attribution):
    assert DEAD_LINK not in attribution


def test_attribution_modification_notice(attribution):
    assert re.search(r"[uú]prav", attribution, re.IGNORECASE)


def test_attribution_forbids_ml_training(attribution):
    assert ML_RE.search(attribution)


def test_license_mit_preserved_and_qet_mentioned():
    text = _read("LICENSE")
    assert text.lstrip().startswith("MIT License")
    assert "Permission is hereby granted, free of charge" in text
    assert "envocad/library/builtin/qet" in text
    assert re.search(r"CC[ -]BY 3\.0", text)


def test_readme_licence_section():
    text = _read("README.md")
    assert "builtin/qet" in text
    assert "ATTRIBUTION.md" in text
    assert "výjimka z MIT" in text
    assert "creativecommons.org/licenses/by/3.0" in text


def _claude_license_section() -> str:
    text = _read("CLAUDE.md")
    m = re.search(r"^## Licencovaná data.*?(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    assert m, "sekce Licencovaná data chybí"
    return m.group(0)


def test_claude_md_mentions_qet_and_ml_ban():
    section = _claude_license_section()
    assert re.search(r"QElectroTech|QET", section)
    assert ML_RE.search(section) or re.search(r"trénink", section, re.IGNORECASE)


@pytest.mark.parametrize(
    "rel",
    [
        "envocad/library/qet_import.py",
        "docs/SOURCES.md",
        "README.md",
        "envocad/library/builtin/qet/ATTRIBUTION.md",
    ],
)
def test_no_dead_license_link(rel):
    assert DEAD_LINK not in _read(rel)
