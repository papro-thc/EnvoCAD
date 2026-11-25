"""Dokumentace uvádí aktuální `FORMAT_VERSION` – hlídá, aby se číslo v docs nerozešlo s kódem (issue #130)."""
import re
from pathlib import Path

from envocad.model.project import FORMAT_VERSION

DOCS = Path(__file__).resolve().parent.parent / "docs"


def test_architecture_states_current_format_version():
    text = (DOCS / "ARCHITECTURE.md").read_text(encoding="utf-8")
    found = re.findall(r"`FORMAT_VERSION` \+ migrace, aktuálně \*\*(\d+)\*\*", text)
    assert found == [str(FORMAT_VERSION)], "docs/ARCHITECTURE.md: doplň popis nové verze formátu projektu"
    assert re.search(rf"; v{FORMAT_VERSION - 1} \S", text), "popis předchozí verze má v ARCHITECTURE.md zůstat"


def test_library_format_states_current_format_version():
    text = (DOCS / "LIBRARY_FORMAT.md").read_text(encoding="utf-8")
    found = re.findall(r"aktuální `FORMAT_VERSION` je (\d+)", text)
    assert found == [str(FORMAT_VERSION)], "docs/LIBRARY_FORMAT.md uvádí starou verzi formátu projektu"
