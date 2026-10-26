"""Skripty pro Windows: PowerShell 5.1 čte .ps1 bez BOM jako ANSI – čeština a „–“ v UTF-8 pak rozbijí parser
(„The string is missing the terminator“). Skript s ne-ASCII znaky proto musí mít UTF-8 BOM; .cmd jen ASCII."""
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BOM = b"\xef\xbb\xbf"


@pytest.mark.parametrize("path", sorted(SCRIPTS.glob("*.ps1")), ids=lambda p: p.name)
def test_ps1_non_ascii_has_bom(path):
    data = path.read_bytes()
    body = data[len(BOM):] if data.startswith(BOM) else data
    body.decode("utf-8")
    assert body.isascii() or data.startswith(BOM), f"{path.name}: ne-ASCII text bez UTF-8 BOM"


@pytest.mark.parametrize("path", sorted(SCRIPTS.glob("*.cmd")), ids=lambda p: p.name)
def test_cmd_wrappers_ascii(path):
    assert path.read_bytes().isascii(), f"{path.name}: cmd.exe čte v kódové stránce konzole – jen ASCII"


def test_windows_wrappers_exist():
    assert {"install.cmd", "run.cmd"} <= {p.name for p in SCRIPTS.glob("*.cmd")}
