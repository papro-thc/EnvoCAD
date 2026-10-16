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
    import pypdf

    from envocad.export.doc_pdf import DocBuilder, export_documentation_pdf
    b = DocBuilder(proj, lib)
    b.plan()
    out = tmp_path / "dok.pdf"
    n = export_documentation_pdf(proj, lib, out)
    data = out.read_bytes()
    pages = len(re.findall(rb"/Type\s*/Page(?!s)", data))
    assert pages == n >= len(b.pages)
    # A3 na šířku (dřív Landscape u rozměru 420×297 otočil stranu na výšku)
    mb = pypdf.PdfReader(out).pages[0].mediabox
    assert float(mb.width) > float(mb.height)


@pytest.fixture(scope="module")
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dxf_revision_layer(proj, lib, tmp_path):
    from envocad.model.project import Revision, RevisionMark
    s = proj.sheets[0]
    # bez značek: vrstva existuje, ale je prázdná
    doc = _check_dxf(proj, s, lib, tmp_path / "bez_revize.dxf")
    assert "REVIZE" in doc.layers and doc.layers.get("REVIZE").color == 1
    assert not doc.modelspace().query('*[layer=="REVIZE"]')
    proj.revisions.append(Revision("B", marks=[RevisionMark(s.id, s.elements[0].id),
                                               RevisionMark(s.id, s.wires[0].id, is_wire=True),
                                               RevisionMark(s.id, "", kind="odebráno", x=100.0, y=100.0)]))
    doc = _check_dxf(proj, s, lib, tmp_path / "revize.dxf")
    msp = doc.modelspace()
    tri = [e for e in msp.query("LWPOLYLINE") if e.dxf.layer == "REVIZE"]
    assert len(tri) == 3 and all(pl.closed and len(pl.get_points()) == 3 for pl in tri)
    assert _texts(doc, "REVIZE") == ["B", "B", "B"]
    # jiný list stejného projektu značky nemá
    other = proj.sheets[1]
    export_sheet_dxf(proj, other, lib, tmp_path / "jiny.dxf")
    assert not ezdxf.readfile(tmp_path / "jiny.dxf").modelspace().query('*[layer=="REVIZE"]')


# ---- strany dokumentace a připomínky jako anotace PDF ---------------------------------------------------------
def _pdf_annots(path) -> list[list]:
    import pypdf
    r = pypdf.PdfReader(path)
    return [[a.get_object() for a in (pg.get("/Annots") or [])] for pg in r.pages]


def _multipage_switchboards(p) -> None:
    for s in p.switchboards():
        s.width = 200.0          # úzký list → vícepól na 2 strany


def test_documentation_pages_counted_with_multipole(proj, lib, tmp_path, qapp, monkeypatch):
    """Vícepól na víc stran: vrácený počet = strany PDF, popisové pole „n/N“ s fyzickým číslem a správným N."""
    import pypdf

    from envocad.export import doc_pdf
    _multipage_switchboards(proj)
    seen: list[str] = []
    orig = doc_pdf._draw_frame_page

    def spy(painter, project, sheet, view="", page=""):
        seen.append(page)
        return orig(painter, project, sheet, view, page)
    monkeypatch.setattr(doc_pdf, "_draw_frame_page", spy)
    b = doc_pdf.DocBuilder(proj, lib)
    out = tmp_path / "dok.pdf"
    n = b.export(out)
    assert n == len(pypdf.PdfReader(out).pages)
    n_mp = sum(1 for k, _, d in b.pages if k == "sheet" and d[1] == "multipole")
    cap = b._table_capacity()
    n_cont = sum(-(-len(d[1]) // cap) - 1 for k, _, d in b.pages if k == "table")
    assert n_mp and n == len(b.pages) + n_mp + n_cont    # každý vícepól má o stranu víc, dlouhé tabulky pokračují
    totals = {pg.split("/")[1] for pg in seen}
    assert totals == {str(n)} and seen[-1] == f"{n}/{n}"   # změnový list = poslední strana
    nums = [int(pg.split("/")[0]) for pg in seen]
    assert nums == sorted(set(nums))
    # obsah: první strana každé položky, vícepól posouvá další položky
    assert b.page_starts[0] == 1 and b.page_starts[-1] == n
    mp_idx = next(i for i, (k, _, d) in enumerate(b.pages) if k == "sheet" and d[1] == "multipole")
    assert b.page_starts[mp_idx + 1] == b.page_starts[mp_idx] + 2


def test_documentation_pdf_note_annotations(proj, lib, tmp_path, qapp):
    from envocad.export.doc_pdf import DocBuilder, export_documentation_pdf
    from envocad.export.pdf_annots import MM_TO_PT
    from envocad.model.project import Note
    jps = proj.sheets[0]
    _multipage_switchboards(proj)
    proj.notes = [Note(jps.id, 100.0, 100.0, "Doplnit SPD", no=1),
                  Note(jps.id, 10.0, 10.0, "Vyřešeno", no=2, status="resolved"),
                  Note(proj.sheets[1].id, 50.0, 50.0, "Ve vícepólu ne", no=3)]
    # bez notes žádné anotace
    out = tmp_path / "bez.pdf"
    export_documentation_pdf(proj, lib, out)
    assert not any(_pdf_annots(out))
    assert not any(_pdf_annots(out))   # QPdfWriter píše prázdné /Annots [], anotace žádné
    # s notes: jen otevřená připomínka listu JPS, na jeho straně (titul, obsah → 3. strana)
    out = tmp_path / "s.pdf"
    n = export_documentation_pdf(proj, lib, out, notes=True)
    ann = _pdf_annots(out)
    assert len(ann) == n
    pages_with = [i for i, a in enumerate(ann) if a]
    assert pages_with == [2]
    main = [a for a in ann[2] if a["/Subtype"] == "/Text"]
    assert len(main) == 1 and main[0]["/Contents"] == "Doplnit SPD"
    # list JPS 480 mm na A3 (420) u levého horního rohu: měřítko 420/480, Y od horního okraje
    s = 420 / jps.width
    x = float(main[0]["/Rect"][0])
    y = float(main[0]["/Rect"][1])
    assert x == pytest.approx(100 * s * MM_TO_PT, abs=0.5)
    assert y == pytest.approx((297 - (jps.height - 100) * s) * MM_TO_PT, abs=0.5)

    # list JPS za vícepólem na 2 strany → anotace na správné fyzické straně
    class Reordered(DocBuilder):
        def plan(self):
            super().plan()
            i = next(k for k, pg in enumerate(self.pages) if pg[0] == "sheet" and pg[2][1] == "schematic")
            j = next(k for k, pg in enumerate(self.pages) if pg[0] == "sheet" and pg[2][1] == "terminals")
            self.pages.insert(j, self.pages.pop(i))     # JPS až za první vícepól a plán svorkovnice
    b = Reordered(proj, lib)
    out = tmp_path / "poradi.pdf"
    b.export(out, notes=True)
    idx = next(k for k, pg in enumerate(b.pages) if pg[0] == "sheet" and pg[2][1] == "schematic")
    assert b.pages[idx - 2][2][1] == "multipole"
    ann = _pdf_annots(out)
    assert [i for i, a in enumerate(ann) if a] == [b.page_starts[idx] - 1] == [b.note_pages[0][0]]
    assert b.page_starts[idx] - 1 > idx               # posunuto o druhou stranu vícepólu


def test_scene_pdf_note_annotations(proj, lib, tmp_path, qapp):
    import pypdf
    from PySide6.QtGui import QUndoStack

    from envocad.export.pdf_annots import MM_TO_PT
    from envocad.export.pdf_export import export_scene_pdf
    from envocad.model.project import Note
    from envocad.ui.canvas import SchematicScene
    from envocad.ui.multipole_view import MultipoleScene
    jps = proj.sheets[0]
    proj.notes = [Note(jps.id, 50.0, 40.0, "Obdélníková připomínka", no=1, w=20.0, h=10.0)]
    sc = SchematicScene(proj, jps, lib, QUndoStack())
    out = tmp_path / "bez.pdf"
    assert export_scene_pdf(sc, out) == 0
    assert not any(_pdf_annots(out))   # QPdfWriter píše prázdné /Annots [], anotace žádné
    assert "Obdélníková" not in pypdf.PdfReader(out).pages[0].extract_text()   # do obsahu se nevypaluje
    # skutečný rozměr listu: měřítko 1, bez posunu
    out = tmp_path / "s.pdf"
    assert export_scene_pdf(sc, out, notes=True) == 1
    sq = _pdf_annots(out)[0][0]
    assert sq["/Subtype"] == "/Square"
    assert [float(v) for v in sq["/Rect"]] == pytest.approx(
        [50 * MM_TO_PT, 40 * MM_TO_PT, 70 * MM_TO_PT, 50 * MM_TO_PT], abs=0.5)
    assert "Obdélníková" not in pypdf.PdfReader(out).pages[0].extract_text()
    # A4: list 480×297 zmenšený na 297×210 se zachováním poměru a vystředěný (KeepAspectRatio)
    out = tmp_path / "a4.pdf"
    export_scene_pdf(sc, out, paper="A4", notes=True)
    sq = _pdf_annots(out)[0][0]
    s = min(297 / jps.width, 210 / jps.height)
    ty = (210 - jps.height * s) / 2
    assert float(sq["/Rect"][0]) == pytest.approx(50 * s * MM_TO_PT, abs=0.5)
    assert float(sq["/Rect"][1]) == pytest.approx((ty + 40 * s) * MM_TO_PT, abs=0.5)
    # vícepól připomínky nemá
    sb = proj.switchboards()[0]
    proj.notes.append(Note(sb.id, 50.0, 50.0, "x", no=2))
    out = tmp_path / "mp.pdf"
    assert export_scene_pdf(MultipoleScene(proj, sb, lib, QUndoStack()), out, notes=True) == 0
    assert not any(_pdf_annots(out))   # QPdfWriter píše prázdné /Annots [], anotace žádné
