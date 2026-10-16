"""Obsah exportů: DXF (hladiny, entity, texty, ortogonální vodiče, rámeček), XLSX (buňky = výkazy), PDF (stránky)."""
import re
from itertools import pairwise

import ezdxf
import pytest
from openpyxl import load_workbook

from envocad.export import reports
from envocad.export.dxf_export import export_sheet_dxf
from envocad.export.xlsx_export import export_reports_xlsx
from envocad.generate import build_project
from envocad.library.store import LibraryStore

SPEC = {"name": "Export", "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200,
                                         "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [20, 20]}]}


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


@pytest.fixture
def proj():
    return build_project(SPEC)


def _texts(doc, layer=None) -> list[str]:
    return [t.dxf.text for t in doc.modelspace().query("TEXT") if layer is None or t.dxf.layer == layer]


def _check_dxf(p, s, lib, path):
    export_sheet_dxf(p, s, lib, path)
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    for name in ("SYMBOLY", "VODICE", "TEXTY", "RAMECEK", "PORTY"):
        assert name in doc.layers
    assert doc.header["$INSUNITS"] == 4
    # jeden polyline na vodič, jen svislé a vodorovné úseky
    wires = [e for e in msp.query("LWPOLYLINE") if e.dxf.layer == "VODICE"]
    assert len(wires) == len(s.wires)
    for pl in wires:
        pts = [(round(x, 6), round(y, 6)) for x, y, *_ in pl.get_points()]
        assert len(pts) >= 2
        for (x1, y1), (x2, y2) in pairwise(pts):
            assert x1 == x2 or y1 == y2, f"šikmý úsek {pts}"
    # označení každého prvku je v textech
    texts = _texts(doc, "TEXTY")
    for e in s.elements:
        if e.ref and e.symbol_id not in ("sb.junction",):
            assert any(e.ref in t for t in texts), f"chybí popisek {e.ref}"
    # značky se kreslí v hladině SYMBOLY
    assert len(msp.query('*[layer=="SYMBOLY"]')) >= len(s.elements)
    return doc


def test_dxf_schematic_content(proj, lib, tmp_path):
    s = proj.sheets[0]
    doc = _check_dxf(proj, s, lib, tmp_path / "jps.dxf")
    assert not doc.modelspace().query('*[layer=="RAMECEK"]')   # rámeček je ve výchozím nastavení vypnutý


def test_dxf_switchboard_header(proj, lib, tmp_path):
    from envocad.model.project import switchboard_header
    sb = next(s for s in proj.sheets if s.is_switchboard)
    doc = _check_dxf(proj, sb, lib, tmp_path / "rh.dxf")
    texts = _texts(doc, "TEXTY")
    for k, v in switchboard_header(proj, sb):
        assert k in texts and v in texts


def test_dxf_with_frame_and_qr(proj, lib, tmp_path):
    pytest.importorskip("segno")
    from envocad.model.frame import frame_geometry
    from envocad.settings import load_settings, save_settings
    save_settings({**load_settings(), "frame": True})
    s = proj.sheets[0]
    doc = _check_dxf(proj, s, lib, tmp_path / "frame.dxf")
    msp = doc.modelspace()
    g = frame_geometry(proj, s)
    frame_lines = [e for e in msp.query("LINE") if e.dxf.layer == "RAMECEK"]
    assert len(frame_lines) == len(g.lines)
    assert len(msp.query("SOLID")) == len(g.rects) > 0            # QR kód
    frame_texts = _texts(doc, "RAMECEK")
    assert proj.name in frame_texts or any(proj.name in t for t in frame_texts)
    assert {"A", "B", "1", "2"} <= set(frame_texts)                 # souřadnicová síť


def test_xlsx_cells_match_reports(proj, lib, tmp_path):
    out = tmp_path / "r.xlsx"
    sb = next(s for s in proj.sheets if s.is_switchboard)
    export_reports_xlsx(proj, lib, out, sb)
    wb = load_workbook(out)
    for name, fn in reports.ALL_REPORTS:
        head, rows = fn(proj, lib, sb)
        ws = wb[name[:31]]
        values = [list(r) for r in ws.iter_rows(values_only=True)]
        hi = next(i for i, r in enumerate(values) if [c for c in r[:len(head)]] == list(head))
        body = values[hi + 1:hi + 1 + len(rows)]
        assert len(body) == len(rows), name
        for got, exp in zip(body, rows):
            norm = ["" if c is None else c for c in got[:len(exp)]]
            assert norm == [("" if c is None else c) for c in exp], f"{name}: {got} ≠ {exp}"


def test_bom_counts_every_device(proj, lib):
    """Výkaz materiálu: každý přístroj je v právě jedné položce a „Ks“ sedí s výčtem označení (X1 (2) = 2 ks)."""
    sb = next(s for s in proj.sheets if s.is_switchboard)
    head, rows = reports.bom(proj, lib, sb)
    qi, ri = head.index("Ks"), head.index("Označení")
    seen: list[str] = []
    for r in rows:
        n = 0
        for part in str(r[ri]).split(", "):
            m = re.fullmatch(r"(.+?)(?: \((\d+)\))?", part)
            seen.append(m.group(1))
            n += int(m.group(2) or 1)
        assert n == r[qi], r
    refs = [e.ref for e in sb.elements if e.ref]
    assert sorted(seen) == sorted(refs)


def test_documentation_pdf_pages(proj, lib, tmp_path, qapp):
    from envocad.export.doc_pdf import DocBuilder, export_documentation_pdf
    b = DocBuilder(proj, lib)
    b.plan()
    out = tmp_path / "dok.pdf"
    n = export_documentation_pdf(proj, lib, out)
    data = out.read_bytes()
    pages = len(re.findall(rb"/Type\s*/Page(?!s)", data))
    assert pages == n >= len(b.pages)


@pytest.fixture(scope="module")
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
