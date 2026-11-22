"""Issue #80: výpočty (oteplení, Iz / jištění kabelu) jsou orientační – jednotné označení z jedné konstanty."""
from pathlib import Path

import pytest
from openpyxl import load_workbook

from envocad.model.project import Element, Project, Wire, WireEnd

NOTE = "orientační – neověřeno proti normě"
ROOT = Path(__file__).resolve().parents[1]


def _board(*devs):
    """List rozvaděče: `devs` = (ref, řada, atributy); 3 řady, skříň 500 × 500 × 200 mm."""
    p = Project()
    blk = Element("fve.switchboard", 0, 0, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    sb.layout.rows = 3
    sb.layout.params = {"width_mm": "500", "height_mm": "500", "depth_mm": "200", "row_pitch_mm": "150"}
    for i, (ref, row, attrs) in enumerate(devs):
        e = Element("fve.breaker_mcb", 0, 0, attrs={"ref": ref, "modules": "1", "p_loss_w": "15", **attrs})
        sb.elements.append(e)
        sb.layout.set_placement(e.id, row, float(i))
    return p, sb


def _docx_text(path) -> str:
    from docx import Document
    d = Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    return "\n".join(parts)


def _note() -> str:
    """Import uvnitř funkce: chybějící modul shodí jen testy, ne sběr souboru."""
    from envocad.model.advisory import ADVISORY_NOTE
    return ADVISORY_NOTE


@pytest.fixture(scope="module")
def lib():
    from envocad.library.store import LibraryStore
    return LibraryStore()


def _project_with_cable():
    """Rozvaděč s přístrojem nad limitem (oteplení) + na prvním listu kabel s Iz a jističem."""
    p, sb = _board(("F1", 2, {"t_max": "70"}), ("F3", 0, {"t_max": "42"}))
    sb.name = "RH"
    s = p.sheets[0]
    prot = Element("fve.breaker_mcb", 0, 0, attrs={"ref": "F9", "in_": "125"})
    load = Element("fve.load", 100, 0, attrs={"ref": "M1"})
    s.elements += [prot, load]
    s.wires.append(Wire(WireEnd(prot.id, "2"), WireEnd(load.id, "1"),
                        attrs={"ref": "W1", "cross": "50", "method": "B1", "length": "10"},
                        conductors=["L1", "L2", "L3", "N", "PE"]))
    return p, sb


def test_advisory_constant_wording():
    assert _note() == NOTE


def test_advisory_literal_only_in_advisory_module():
    """Text nesmí být kopírovaný – jen v model/advisory.py."""
    hits = [str(f.relative_to(ROOT)) for f in (ROOT / "envocad").rglob("*.py") if NOTE in f.read_text("utf-8")]
    assert hits == [str(Path("envocad/model/advisory.py"))], hits


def test_verdict_uses_note():
    note = _note()
    p, sb = _board(("F1", 2, {"t_max": "70"}), ("F3", 0, {"t_max": "42"}))
    from envocad.model.thermal import temperature_rise
    v = temperature_rise(sb, project=p, t_ambient_c=35).verdict()
    assert v.startswith(f"NEVYHOVUJE ({note}) – F3 v řadě 1:"), v
    assert "(orientačně)" not in v


def test_f7_thermal_warning_uses_note():
    from envocad.model.checks import WARNING, thermal_findings
    note = _note()
    p, _sb = _board(("F1", 2, {"t_max": "70"}), ("F3", 0, {"t_max": "42"}))   # F1 pod F3 ohřeje řadu F3 nad 42 °C
    f = [x for x in thermal_findings(p) if x.severity == WARNING]
    assert f and all(x.text.startswith(f"Oteplení ({note}): ") for x in f), f


def test_routine_test_protocol_has_no_thermal_row(lib, tmp_path):
    from envocad.export.docx_export import export_routine_test_docx
    p, sb = _project_with_cable()
    export_routine_test_docx(p, lib, sb, tmp_path / "p.docx")
    prot = _docx_text(tmp_path / "p.docx")
    assert "Oteplení" not in prot and "60890" not in prot
    assert "Krytí / IK" in prot and "Výrobce rozvaděče" in prot


def test_calculations_report_has_thermal_row(lib):
    from envocad.export import reports
    note = _note()
    p, sb = _project_with_cable()
    _head, rows = reports.calculations(p, lib)
    th = [r for r in rows if r[0] == "Oteplení"]
    assert len(th) == 1 and th[0][1] == "RH" and note in th[0][-1], rows
    _head, rows = reports.calculations(p, lib, sb)           # filtr listu rozvaděče
    assert [r[1] for r in rows if r[0] == "Oteplení"] == ["RH"]
    _head, rows = reports.calculations(p, lib, p.sheets[0])  # jiný list: oteplení rozvaděče tam není
    assert not [r for r in rows if r[0] == "Oteplení"]


def test_calculations_report_cable_has_note(lib):
    from envocad.export import reports
    p, _sb = _project_with_cable()
    _head, rows = reports.calculations(p, lib)
    cab = [r for r in rows if r[0] == "Kabel"]
    assert cab and all(_note() in r[3] for r in cab), cab
    assert all("Iz = " in r[3] for r in cab)
    assert all(r[4] == "OK" or _note() not in r[4] for r in cab)      # sloupec výsledku se nemění


def test_xlsx_calculations_sheet_has_note(lib, tmp_path):
    from envocad.export.xlsx_export import export_reports_xlsx
    note = _note()
    p, _sb = _project_with_cable()
    out = tmp_path / "r.xlsx"
    export_reports_xlsx(p, lib, out, None)
    ws = load_workbook(out)["Výpočty"]
    rows = [[str(c) for c in r if c is not None] for r in ws.iter_rows(values_only=True)]
    th = [r for r in rows if "Oteplení" in r]
    cab = [r for r in rows if "Kabel" in r]
    assert th and any(note in c for c in th[0]), rows
    assert cab and any(note in c for c in cab[0]), rows


def test_tz_cables_section_has_note(lib, tmp_path):
    from envocad.export.tz_export import export_tz_docx
    p, _sb = _project_with_cable()
    export_tz_docx(p, lib, tmp_path / "tz.docx")
    tz = _docx_text(tmp_path / "tz.docx")
    assert "Zatížitelnost Iz" in tz
    para = next(line for line in tz.splitlines() if line.startswith("Zatížitelnost Iz"))
    assert _note() in para, para
    assert f"Výsledek ({_note()})" in tz      # hlavička sloupce výsledku tabulky kabelů
