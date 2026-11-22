"""Výkaz artiklů po výrobcích (issue #68) – `reports.bom_by_manufacturer` a jeho xlsx list."""
import pytest
from openpyxl import load_workbook
from test_reports import _proj

from envocad.export import reports
from envocad.export.xlsx_export import export_reports_xlsx
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project

HEAD = ["Výrobce", "Objednací číslo", "Název", "Ks"]
SHEET_NAME = "Výkaz po výrobcích"


def _small_project():
    p = Project(name="Vyrobci")
    s = p.sheets[0]
    s.elements += [
        Element("fve.breaker_mcb", 10, 10, attrs={"ref": "F1", "type": "B-16", "manufacturer": "Beta"}),
        Element("fve.breaker_mcb", 30, 10, attrs={"ref": "F2", "type": "B-16", "manufacturer": "Beta"}),
        Element("fve.inverter", 50, 10, attrs={"ref": "T1", "type": "INV-5", "manufacturer": "alfa"}),
        Element("fve.breaker_mcb", 70, 10, attrs={"ref": "F3", "type": "B-10", "manufacturer": "  "}),
    ]
    return p, s


def _total(rows, col):
    return sum(r[col] for r in rows)


def test_bom_by_manufacturer_grouping_and_order(tmp_path):
    lib = LibraryStore(tmp_path / "lib.db")
    p, s = _small_project()
    _, bom_rows = reports.bom(p, lib, s)
    assert _total(bom_rows, 5) == 4          # předpoklad: všechny 4 prvky jsou v bom
    head, rows = reports.bom_by_manufacturer(p, lib, s)
    assert head == HEAD
    assert [r[0] for r in rows] == ["alfa", "Beta", reports.NO_MANUFACTURER]
    assert reports.NO_MANUFACTURER == "bez výrobce"
    assert [r[1] for r in rows] == ["INV-5", "B-16", "B-10"]
    assert [r[3] for r in rows] == [1, 2, 1]          # dva stejné jističe Beta sloučeny
    assert rows[1][2] == next(r[1] for r in bom_rows if r[2] == "B-16")   # název = sloupec Přístroj


def test_bom_by_manufacturer_merges_different_params():
    # parametry se nerozlišují – stejný (výrobce, typ, název) se sloučí
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        lib = LibraryStore(Path(d) / "lib.db")
        p = Project()
        s = p.sheets[0]
        s.elements += [
            Element("fve.breaker_mcb", 10, 10, attrs={"ref": "F1", "type": "X", "manufacturer": "M", "poles": "1"}),
            Element("fve.breaker_mcb", 30, 10, attrs={"ref": "F2", "type": "X", "manufacturer": "M", "poles": "3"}),
        ]
        _, rows = reports.bom_by_manufacturer(p, lib, s)
        assert len(rows) == 1 and rows[0][3] == 2


def test_bom_by_manufacturer_sort_inside_group(tmp_path):
    lib = LibraryStore(tmp_path / "lib.db")
    p = Project()
    p.sheets[0].elements += [
        Element("fve.breaker_mcb", 10, 10, attrs={"ref": "F1", "type": "B-10", "manufacturer": "Z"}),
        Element("fve.breaker_mcb", 30, 10, attrs={"ref": "F2", "type": "B-2", "manufacturer": "Z"}),
        Element("fve.breaker_mcb", 50, 10, attrs={"ref": "F3", "type": "A", "manufacturer": ""}),
    ]
    _, rows = reports.bom_by_manufacturer(p, lib)
    assert [(r[0], r[1]) for r in rows] == [("Z", "B-2"), ("Z", "B-10"), ("bez výrobce", "A")]


@pytest.mark.parametrize("use_sheet", [False, True])
def test_bom_by_manufacturer_total_matches_bom_small(tmp_path, use_sheet):
    lib = LibraryStore(tmp_path / "lib.db")
    p, s = _small_project()
    sh = s if use_sheet else None
    assert _total(reports.bom_by_manufacturer(p, lib, sh)[1], 3) == _total(reports.bom(p, lib, sh)[1], 5)


@pytest.mark.parametrize("use_sheet", [False, True])
def test_bom_by_manufacturer_total_matches_bom_switchboard(tmp_path, use_sheet):
    lib = LibraryStore(tmp_path / "lib.db")
    p, s = _proj()
    sh = s if use_sheet else None
    _, rows = reports.bom_by_manufacturer(p, lib, sh)
    total = _total(reports.bom(p, lib, sh)[1], 5)
    assert total > 0 and _total(rows, 3) == total


def test_bom_by_manufacturer_empty_project(tmp_path):
    lib = LibraryStore(tmp_path / "lib.db")
    head, rows = reports.bom_by_manufacturer(Project(), lib)
    assert head == HEAD and rows == []


def test_registration():
    names = [n for n, _ in reports.ALL_REPORTS]
    assert names[names.index("Výkaz materiálu") + 1] == SHEET_NAME
    assert dict(reports.ALL_REPORTS)[SHEET_NAME] is reports.bom_by_manufacturer
    assert SHEET_NAME in reports.NOT_IN_DOC


def test_xlsx_sheet(tmp_path):
    lib = LibraryStore(tmp_path / "lib.db")
    p, s = _small_project()
    x = tmp_path / "r.xlsx"
    export_reports_xlsx(p, lib, x, s)
    wb = load_workbook(x)
    assert SHEET_NAME in wb.sheetnames
    ws = wb[SHEET_NAME]
    assert [c.value for c in ws[4]] == HEAD
    _, rows = reports.bom_by_manufacturer(p, lib, s)
    data = [[c.value for c in r] for r in ws.iter_rows(min_row=5, max_col=4)]
    assert data == rows
    assert all(type(r[3]) is int for r in data)
