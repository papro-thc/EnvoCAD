from openpyxl import load_workbook

from envocad.export import reports
from envocad.export.docx_export import export_routine_test_docx
from envocad.export.xlsx_export import export_reports_xlsx
from envocad.library.store import LibraryStore
from envocad.library.templates import apply_template
from envocad.model.project import Element, Project, Sheet, Wire, WireEnd


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
    assert any(r[0] == "+R1-Q1" for r in rows)          # list rozvaděče má umístění = označení bloku
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
    # datum protokolu = dnešek v místním čase (stejně jako popisové pole, bez DTZ011)
    from datetime import datetime
    today = datetime.now().astimezone().strftime("%d.%m.%Y")
    cells = [[c.text for c in row.cells] for t in doc.tables for row in t.rows]
    assert ["Datum", today] in [r[:2] for r in cells]


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
    _, rows = reports.cable_plan(p, lib)
    assert [r[3] for r in rows] == ["L1", "N", "PE"] and rows[0][6] == "T1:AC" and rows[0][7] == "F1:1"
    _, rows = reports.wiring_list(p, lib)
    assert len(rows) == 3 and rows[0][1] == "W2" and rows[0][3] == "hnědá"
    # artikl kabelu v knihovně
    assert any(cc.category == "cable" for cc in lib.components(category="cable"))


def test_reports_full_designation(tmp_path):
    from envocad.model.project import Wire, WireEnd
    lib = LibraryStore(tmp_path / "lib.db")
    p = Project(name="Označení")
    jps = p.sheets[0]
    t = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    f_jps = Element("fve.breaker_mcb", 80, 150, attrs={"ref": "F5"})
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "RDC1"})
    jps.elements += [t, f_jps, blk]
    sb = p.create_switchboard_sheet(blk)
    x1 = Element("sb.terminal_block", 20, 100, attrs={"ref": "X1", "terminal": "1 2 3"})
    f3 = Element("fve.breaker_mcb", 60, 100, attrs={"ref": "F3"})
    f2 = Element("fve.breaker_mcb", 60, 120, attrs={"ref": "F2"})
    g = Element("fve.breaker_mcb", 60, 140, attrs={"ref": "F1", "loc": "RH"})        # override umístění
    sb.elements += [x1, f3, f2, g]
    sb.wires.append(Wire(WireEnd(x1.id, "2"), WireEnd(f3.id, "1"), conductors=["L1", "N", "PE"]))
    w = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X1"), attrs={"ref": "W1", "cable": "CYKY"}, conductors=["L1"])
    w.terminals = {"L1": {"b": "X1:3"}}
    jps.wires += [w, Wire(WireEnd(t.id, "AC"), WireEnd(f_jps.id, "1"), attrs={"ref": "W2", "cable": "CYKY"})]
    _, rows = reports.device_list(p, lib)
    # projekt bez struktur: JPS zůstává „F5“ (ne „-F5“); řazení (func, loc, přirozené ref)
    assert [r[0] for r in rows] == ["F5", "T1", "+RDC1-F2", "+RDC1-F3", "+RDC1-X1", "+RH-F1"]
    _, rows = reports.labels(p, lib)
    assert "+RDC1" in [r[0] for r in rows] and "+RDC1-X1" in [r[0] for r in rows]
    _, rows = reports.cables(p, lib)
    w1 = next(r for r in rows if r[0] == "W1")
    assert (w1[1], w1[2]) == ("T1:AC", "+RDC1-X1")                   # port bloku = přívod X1 v RDC1
    assert next(r for r in rows if r[0] == "W2")[2] == "F5:1"
    _, rows = reports.wiring_list(p, lib)
    assert any(r[1] == "W1" and r[5] == "T1:AC" and r[6] == "+RDC1-X1:3" for r in rows)
    assert any(r[5] == "+RDC1-X1:1" and r[6] == "+RDC1-F3:1" for r in rows)
    _, rows = reports.cable_plan(p, lib)
    assert any(r[0] == "W1" and r[7] == "+RDC1-X1:3" for r in rows)
    _, rows = reports.terminals(p, lib, sb)
    # svorkovnice v RDC1: protější konec ve stejném umístění bez opakování „+RDC1“
    # protější konec po žílách jako zapojovací seznam (`wiring.conductor_end`): fáze na pól, N/PE vedou kolem
    assert {(r[0], r[1], r[4]) for r in rows} == {("X1", "1", "F3:1"), ("X1", "2", "F3:N"), ("X1", "3", "F3:PE")}
    sb.wires.append(Wire(WireEnd(x1.id, "2"), WireEnd(g.id, "1"), conductors=["L1"]))
    _, rows = reports.terminals(p, lib, sb)
    assert any(r[4] == "+RH-F1:1" for r in rows)


def test_cable_material_sums_by_type():
    """Kabely a vodiče k objednání: kabely sečtené podle typu a průřezu, kabel přes více vodičů jednou, bez délky."""
    from envocad.export.reports import NOT_IN_DOC, cable_material
    from envocad.model.project import Cable
    lib = LibraryStore()
    p = Project()
    s = p.sheets[0]
    a = Element("fve.pv_string", 0, 100, attrs={"ref": "G1"})
    b = Element("fve.pv_string", 0, 50, attrs={"ref": "G2"})
    t = Element("fve.inverter", 100, 100, attrs={"ref": "T1"})
    f = Element("fve.breaker_mcb", 200, 100, attrs={"ref": "F1"})
    s.elements += [a, b, t, f]
    s.wires += [Wire(WireEnd(a.id, "DC"), WireEnd(t.id, "DC1"), attrs={"ref": "W1", "cable": "H1Z2Z2-K 1x6", "cross": "6", "length": "25"}),
                Wire(WireEnd(b.id, "DC"), WireEnd(t.id, "DC2"), attrs={"ref": "W2", "cable": "H1Z2Z2-K 1x6", "cross": "6", "length": "12,5 m"}),
                Wire(WireEnd(t.id, "AC"), WireEnd(f.id, "1"), attrs={"ref": "W3", "cable_id": "k1"}),
                Wire(WireEnd(t.id, "AC"), WireEnd(f.id, "2"), attrs={"ref": "W4", "cable_id": "k1"})]
    p.cables.append(Cable(ref="W3", type="CYKY-J 5x10", cross="10", id="k1"))
    head, rows = cable_material(p, lib)
    by = {(r[1], r[2]): r for r in rows}
    dc = by[("Kabel", "H1Z2Z2-K 1x6")]
    assert dc[head.index("Ks")] == 2 and dc[head.index("Délka [m]")] == 37.5 and dc[head.index("Označení")] == "W1, W2"
    ac = by[("Kabel", "CYKY-J 5x10")]
    assert ac[head.index("Ks")] == 1 and ac[head.index("Délka [m]")] == "" and ac[head.index("Bez délky")] == 1
    assert "Kabely a vodiče k objednání" in NOT_IN_DOC


def test_cable_material_switchboard_wires_and_ferrules():
    from envocad.export.reports import cable_material
    lib = LibraryStore()
    p = Project()
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    head, rows = cable_material(p, lib, sb)
    kinds = {r[1] for r in rows}
    assert {"Vodič rozvaděče", "Dutinka"} <= kinds
    wires = [r for r in rows if r[1] == "Vodič rozvaděče"]
    assert all(r[head.index("Ks")] >= 1 for r in wires) and any(r[head.index("Délka [m]")] for r in wires)
