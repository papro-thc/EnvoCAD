from openpyxl import load_workbook

from envocad.export import reports
from envocad.export.docx_export import export_routine_test_docx
from envocad.export.xlsx_export import export_reports_xlsx
from envocad.library.store import LibraryStore
from envocad.library.templates import apply_template
from envocad.model.project import Element, Project, Sheet


def _proj():
    p = Project(name="Test", meta={"order": "2026-042", "investor": "ENVO"})
    block = Element("fve.switchboard", 100, 100, attrs={"ref": "R1", "desc": "AC"})
    p.sheets[0].elements.append(block)
    s = p.create_switchboard_sheet(block)
    apply_template(p, s, "ac_fve", {"n_out": "3"})
    # dva stejné jističe → BOM sloučí
    s.wires[0].attrs.update({"ref": "W1", "cable": "CYKY-J", "cross": "5x16", "length": "12"})
    s.wires[0].terminals = {"L1": {"a": "1"}, "L2": {"a": "2"}}
    return p, s


def test_reports_content(tmp_path):
    lib = LibraryStore(tmp_path / "lib.db")
    p, s = _proj()
    head, rows = reports.bom(p, lib, s)
    jistice = [r for r in rows if r[1] == "Jistič"]
    assert len(jistice) == 1 and jistice[0][5] == 3 and "F2" in jistice[0][6]
    _, rows = reports.cables(p, lib, s)
    assert rows and rows[0][0] == "W1" and rows[0][5] == "L1 L2 L3 N PE"
    _, rows = reports.terminals(p, lib, s)
    x1 = [r for r in rows if r[0] == "X1"]
    assert {r[2] for r in x1} == {"L1", "L2", "L3", "N", "PE"}
    assert next(r for r in x1 if r[2] == "L1")[1] == "1"  # ruční svorka z Wire.terminals
    _, rows = reports.labels(p, lib, s)
    assert any(r[0] == "Q1" for r in rows)
    _, rows = reports.device_list(p, lib)  # celý projekt – blok R1 není přístroj
    assert not any(r[0] == "R1" for r in rows)


def test_xlsx_and_docx(tmp_path):
    lib = LibraryStore(tmp_path / "lib.db")
    p, s = _proj()
    x = tmp_path / "r.xlsx"
    export_reports_xlsx(p, lib, x, s)
    wb = load_workbook(x)
    assert set(wb.sheetnames) == {"Přístroje", "Výkaz materiálu", "Kabely", "Svorkovnice", "Štítky"}
    assert wb["Výkaz materiálu"].max_row > 4
    d = tmp_path / "p.docx"
    export_routine_test_docx(p, lib, s, d)
    from docx import Document
    doc = Document(str(d))
    text = "\n".join(par.text for par in doc.paragraphs)
    assert "kusovém ověření" in text and len(doc.tables) >= 5
    assert any("Q1" in c.text for t in doc.tables for row in t.rows for c in row.cells)


def test_empty_sheet_reports(tmp_path):
    lib = LibraryStore(tmp_path / "lib.db")
    p = Project()
    for _, fn in reports.ALL_REPORTS:
        head, rows = fn(p, lib, Sheet())
        assert head and rows == []
