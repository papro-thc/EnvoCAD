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
    _, rows = reports.bom(p, lib, s)
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
    assert set(wb.sheetnames) == {n[:31] for n, _ in reports.ALL_REPORTS}
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


def test_cables_as_objects_and_wiring_list(tmp_path):
    from envocad.model.project import CORE_COLORS, Cable, Element, Project, Wire, WireEnd, sync_cables
    lib = LibraryStore(tmp_path / "lib.db")
    p = Project(name="Kabely")
    s = p.sheets[0]
    t = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    f = Element("fve.breaker_mcb", 120, 150, attrs={"ref": "F1", "poles": "3"})
    s.elements += [t, f]
    w = Wire(WireEnd(t.id, "AC"), WireEnd(f.id, "1"), attrs={"ref": "W2", "cable": "CYKY-J 5x16", "cross": "16"},
             conductors=["L1", "L2", "L3", "N", "PE"])
    s.wires.append(w)
    assert sync_cables(p) > 0
    c = p.cable_of_wire(w)
    assert isinstance(c, Cable) and c.ref == "W2" and c.type == "CYKY-J 5x16" and c.cross == "16"
    assert [(x.name, x.number, x.color) for x in c.cores][:2] == [("L1", "1", "hnědá"), ("L2", "2", "černá")]
    assert c.core("PE").color == CORE_COLORS["PE"]
    # ruční barva zůstane i po změně žil
    c.core("N").color = "světle modrá"
    w.conductors = ["L1", "N", "PE"]
    sync_cables(p)
    assert [x.name for x in c.cores] == ["L1", "N", "PE"] and c.core("N").color == "světle modrá"
    assert sync_cables(p) == 0
    # uložení/načtení
    p.save(tmp_path / "k.ecp")
    p2 = Project.load(tmp_path / "k.ecp")
    assert p2.cables[0].core("N").color == "světle modrá" and p2.sheets[0].wires[0].attrs["cable_id"] == c.id
    head, rows = reports.cable_plan(p, lib)
    assert [r[3] for r in rows] == ["L1", "N", "PE"] and rows[0][6] == "T1:AC" and rows[0][7] == "F1:1"
    _, rows = reports.wiring_list(p, lib)
    assert len(rows) == 3 and rows[0][1] == "W2" and rows[0][3] == "hnědá"
    # artikl kabelu v knihovně
    assert any(cc.category == "cable" for cc in lib.components(category="cable"))
