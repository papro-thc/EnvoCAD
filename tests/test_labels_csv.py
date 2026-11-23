"""Export štítků do CSV bez Qt (issue #134): `envocad.export.labels_csv.write_labels_csv(project, lib, path) -> int`.
Charakterizační test drží BAJTY dnešního výstupu GUI (`MainWindow.export_labels_csv`): UTF-8 s BOM, oddělovač „;“,
konce řádků CRLF, hlavička „Štítek;Popis;List“, uvozovky jen kde je potřeba (středník, uvozovka v textu)."""
from __future__ import annotations

import csv
import subprocess
import sys

from envocad.export import reports
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project

HEADER_ONLY = b"\xef\xbb\xbf\xc5\xa0t\xc3\xadtek;Popis;List\r\n"

EXPECTED = (
    b'\xef\xbb\xbf\xc5\xa0t\xc3\xadtek;Popis;List\r\n'
    b'F1;"Jisti\xc4\x8d; hlavn\xc3\xad ""p\xc5\x99\xc3\xadp.""";Blokov\xc3\xa9 sch\xc3\xa9ma\r\n'
    b'F2;\xc5\x98\xc3\xaddic\xc3\xad obvod \xe2\x80\x93 \xc5\xbelu\xc5\xa5ou\xc4\x8dk\xc3\xbd k\xc5\xaf\xc5\x88;'
    b'Blokov\xc3\xa9 sch\xc3\xa9ma\r\n'
    b'F10;Jisti\xc4\x8d 16 A;Blokov\xc3\xa9 sch\xc3\xa9ma\r\n'
)


def make_project() -> Project:
    """Tři štítky: středník + uvozovky v popisu, diakritika s en-dash, popis odvozený z názvu symbolu a proudu."""
    p = Project(name="T")
    p.sheets[0].elements += [
        Element("fve.breaker_mcb", 50, 100, attrs={"ref": "F1", "desc": 'Jistič; hlavní "příp."'}),
        Element("fve.breaker_mcb", 80, 100, attrs={"ref": "F2", "desc": "Řídicí obvod – žluťoučký kůň"}),
        Element("fve.breaker_mcb", 110, 100, attrs={"ref": "F10", "in_": "16"}),
    ]
    return p


def _lib(tmp_path) -> LibraryStore:
    return LibraryStore(tmp_path / "lib.db")


def test_write_labels_csv_bytes(tmp_path):
    from envocad.export.labels_csv import write_labels_csv
    out = tmp_path / "stitky.csv"
    n = write_labels_csv(make_project(), _lib(tmp_path), out)
    assert n == 3
    assert out.read_bytes() == EXPECTED


def test_write_labels_csv_accepts_str_path(tmp_path):
    from envocad.export.labels_csv import write_labels_csv
    out = tmp_path / "s.csv"
    assert write_labels_csv(make_project(), _lib(tmp_path), str(out)) == 3
    assert out.read_bytes() == EXPECTED


def test_write_labels_csv_roundtrip_matches_reports(tmp_path):
    from envocad.export.labels_csv import write_labels_csv
    p, lib = make_project(), _lib(tmp_path)
    out = tmp_path / "s.csv"
    n = write_labels_csv(p, lib, out)
    head, rows = reports.labels(p, lib, None)
    with open(out, encoding="utf-8-sig", newline="") as f:
        got = list(csv.reader(f, delimiter=";"))
    assert got == [head] + [[str(c) for c in r] for r in rows]
    assert n == len(rows)


def test_write_labels_csv_empty_project_header_only(tmp_path):
    from envocad.export.labels_csv import write_labels_csv
    out = tmp_path / "e.csv"
    assert write_labels_csv(Project(name="Prázdný"), _lib(tmp_path), out) == 0
    assert out.read_bytes() == HEADER_ONLY


def test_write_labels_csv_overwrites_existing_file(tmp_path):
    from envocad.export.labels_csv import write_labels_csv
    out = tmp_path / "s.csv"
    out.write_bytes(b"x" * 5000)
    write_labels_csv(Project(name="P"), _lib(tmp_path), out)
    assert out.read_bytes() == HEADER_ONLY


def test_labels_csv_module_has_no_qt():
    code = ("import sys, envocad.export.labels_csv; "
            "bad = [m for m in sys.modules if m.startswith(('PySide6', 'envocad.ui'))]; assert not bad, bad")
    r = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
