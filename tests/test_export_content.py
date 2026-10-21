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
    for name in ("SYMBOLY", "VODICE", "TEXTY", "RAMECEK"):
        assert name in doc.layers
    assert "PORTY" not in doc.layers          # nepoužitá hladina se nezakládá (porty se do DXF nekreslí)
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
        from envocad.export.xlsx_export import NUMERIC_COLUMNS, _number
        for got, exp in zip(body, rows):
            norm = ["" if c is None else c for c in got[:len(exp)]]
            # číselné sloupce (průřez, délka, číslo žíly/svorky) jsou v xlsx čísla
            exp = [_number(c) if i < len(head) and head[i] in NUMERIC_COLUMNS else c for i, c in enumerate(exp)]
            assert norm == [("" if c is None else c) for c in exp], f"{name}: {got} ≠ {exp}"


def test_production_xlsx_numeric_cells(proj, lib, tmp_path):
    """Výrobní seznam pro dílnu: buňky = výkaz, průřez a délka jsou čísla, list Parametry s hodnotami a zdroji."""
    from envocad.export.xlsx_export import export_production_xlsx
    sb = next(s for s in proj.sheets if s.is_switchboard)
    sb.layout.params["wire_end_mm"] = "150"
    out = tmp_path / "vyroba.xlsx"
    export_production_xlsx(proj, lib, out, None, base={"wire_reserve_pct": "0"})
    wb = load_workbook(out)
    assert wb.sheetnames == ["Výrobní seznam", "Návlečky", "Parametry"]
    ws = wb["Výrobní seznam"]
    head, rows = reports.production_wiring_list(proj, lib, None, {"wire_reserve_pct": "0"})
    assert rows
    values = [list(r) for r in ws.iter_rows(values_only=True)]
    assert any(str(r[0]).startswith("Parametry") and "přídavek na konec" in str(r[0]) for r in values[:6])
    hi = next(i for i, r in enumerate(values) if list(r[:len(head)]) == head)
    body = values[hi + 1:hi + 1 + len(rows)]
    assert len(body) == len(rows)
    ci, li = head.index("Průřez [mm²]"), head.index("Délka [mm]")
    for got, exp in zip(body, rows):
        assert ["" if c is None else c for c in got[:len(exp)]] == exp
        # průřez je číslo; prázdný jen tam, kde ho určí projektant (SPD), s poznámkou
        ni = head.index("Poznámka")
        assert (isinstance(got[ci], (int, float)) and got[ci] > 0) or (got[ci] is None and "SPD" in got[ni])
    assert any(isinstance(r[ci], (int, float)) for r in body)
    lengths = [r[li] for r in body if r[li] is not None]
    assert lengths and all(isinstance(x, int) and x % 50 == 0 for x in lengths)
    # list Parametry: rozvaděč, klíč, hodnota, zdroj
    prm = [list(r) for r in wb["Parametry"].iter_rows(values_only=True)]
    assert any(r[:2] == [sb.name, "wire_end_mm"] and r[3:5] == ["150", "rozvaděč"] for r in prm)
    assert any(r[1] == "wire_reserve_pct" and r[3] == "0" and r[4] == "firemní standard" for r in prm)
    assert any(r[0] == "Dutinky DIN 46228" for r in prm)


def test_reports_xlsx_production_subtitle(proj, lib, tmp_path):
    out = tmp_path / "r.xlsx"
    export_reports_xlsx(proj, lib, out)
    ws = load_workbook(out)["Výrobní zapojovací seznam"]
    assert str(ws["A3"].value).startswith("Parametry") and "2k+1" in str(ws["A4"].value)


def test_documentation_plan_skips_production_list(proj, lib, qapp):
    from envocad.export.doc_pdf import DocBuilder
    b = DocBuilder(proj, lib)
    b.plan()
    names = [n for _, n, _ in b.pages]
    assert "Zapojovací seznam" in names and "Výrobní zapojovací seznam" not in names


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
    # plná označení s aspekty (+RDC1-F1); skupiny svorek jedné svorkovnice = jedna položka se součtem kusů
    refs = sorted({reports._tag(proj, sb, e) for e in sb.elements if e.ref})
    assert sorted(seen) == refs


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
    # rozvaděče FVE se na úzký list nevejdou (2 strany); stávající HR / RE (F2, pár přístrojů) mají stranu jednu
    fve = ("RDC", "RFVE")
    assert n_mp and all(c == 2 for (k, _, d), c in zip(b.pages, b.page_counts)
                        if k == "sheet" and d[1] == "multipole" and d[0].loc.startswith(fve))
    assert all(c in (1, 2) for (k, _, d), c in zip(b.pages, b.page_counts) if k == "sheet" and d[1] == "multipole")
    assert n == sum(b.page_counts)                       # každý vícepól má o stranu víc, dlouhé tabulky pokračují
    assert b.page_starts == [1 + sum(b.page_counts[:i]) for i in range(len(b.pages))]
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
                  Note(proj.sheets[1].id, 50.0, 50.0, "List rozvaděče", no=3)]
    # bez notes žádné anotace
    out = tmp_path / "bez.pdf"
    export_documentation_pdf(proj, lib, out)
    assert not any(_pdf_annots(out))
    assert not any(_pdf_annots(out))   # QPdfWriter píše prázdné /Annots [], anotace žádné
    # s notes: otevřené připomínky – list JPS na jeho straně (titul, obsah → 3. strana), připomínka listu rozvaděče
    # (bez vazby na přístroj) na první straně jeho vícepólu (hned za JPS)
    out = tmp_path / "s.pdf"
    b = DocBuilder(proj, lib)
    n = b.export(out, notes=True)
    ann = _pdf_annots(out)
    assert len(ann) == n
    pages_with = [i for i, a in enumerate(ann) if a]
    mp_first = next(st for (k, _, d), st in zip(b.pages, b.page_starts)
                    if k == "sheet" and d[0].id == proj.sheets[1].id and d[1] == "multipole") - 1
    assert pages_with == [2, mp_first]
    sb_note = [a for a in ann[mp_first] if a["/Subtype"] == "/Text"]
    assert len(sb_note) == 1 and sb_note[0]["/Contents"].startswith("List rozvaděče")
    main = [a for a in ann[2] if a["/Subtype"] == "/Text"]
    assert len(main) == 1 and main[0]["/Contents"] == "Doplnit SPD"
    # list JPS 480 mm na A3 (420) u levého horního rohu: měřítko 420/480, Y od horního okraje
    s = 420 / jps.width
    x = float(main[0]["/Rect"][0])
    y = float(main[0]["/Rect"][1])
    assert x == pytest.approx(100 * s * MM_TO_PT, abs=0.5)
    assert y == pytest.approx((297 - (jps.height - 100) * s) * MM_TO_PT, abs=0.5)

    # list JPS za vícepólem na 2 strany → anotace na správné fyzické straně
    proj.notes = proj.notes[:2]                       # jen připomínky JPS

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


def _red_bbox_pt(path, page: int = 0, px_per_pt: float = 2.0) -> tuple[float, float, float, float]:
    """Rasterizuje stranu PDF (QtPdf / PDFium) a vrátí obálku čistě červených pixelů v bodech PDF
    (x0, y0, x1, y1; počátek vlevo dole jako /Rect)."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QImage
    from PySide6.QtPdf import QPdfDocument
    doc = QPdfDocument()
    assert doc.load(str(path)) == QPdfDocument.Error.None_
    size_pt = doc.pagePointSize(page)
    img = doc.render(page, QSize(round(size_pt.width() * px_per_pt), round(size_pt.height() * px_per_pt)))
    img = img.convertToFormat(QImage.Format_RGB32)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    data = bytes(img.constBits())
    red = b"\x00\x00\xff\xff"                         # 0xFFFF0000 v RGB32 (little-endian BGRA)
    xs, ys = [], []
    for row in range(h):
        line = data[row * bpl:row * bpl + w * 4]
        i = line.find(red)
        while i >= 0 and i % 4:
            i = line.find(red, i + 1)
        if i < 0:
            continue
        j = line.rfind(red)
        while j >= 0 and j % 4:
            j = line.rfind(red, 0, j + 3)
        xs += [i // 4, j // 4 + 1]
        ys.append(row)
    assert xs, "na straně není žádná červená značka"
    k = px_per_pt
    page_h = h / k
    return min(xs) / k, page_h - (max(ys) + 1) / k, max(xs) / k, page_h - min(ys) / k


@pytest.mark.parametrize("paper", [None, "A3", "A4"])
def test_scene_pdf_note_annotations_match_render(proj, lib, tmp_path, qapp, paper):
    """/Rect anotace musí ležet na skutečně vykresleném místě listu: do scény se přidají plné červené obdélníky
    na místa obdélníkových připomínek (u levého dolního a pravého horního rohu listu), PDF se rasterizuje
    a obálka červených pixelů se porovná s /Rect. Odhalí vystředění vs. kreslení od rohu i chybné měřítko."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QBrush, QColor, QUndoStack
    from PySide6.QtWidgets import QGraphicsRectItem

    from envocad.export.pdf_export import export_scene_pdf
    from envocad.model.project import Note
    from envocad.ui.canvas import SchematicScene
    jps = proj.sheets[0]
    boxes = [(20.0, 15.0, 30.0, 12.0), (jps.width - 60.0, jps.height - 40.0, 30.0, 12.0)]
    proj.notes = [Note(jps.id, x, y, f"značka {i}", no=i + 1, w=w, h=h) for i, (x, y, w, h) in enumerate(boxes)]
    sc = SchematicScene(proj, jps, lib, QUndoStack())
    marks = []
    for x, y, w, h in boxes:
        it = QGraphicsRectItem(x, -(y + h), w, h)      # model Y nahoru → scéna Y dolů
        it.setBrush(QBrush(QColor(255, 0, 0)))
        it.setPen(Qt.NoPen)
        it.setZValue(1e6)
        sc.addItem(it)
        marks.append(it)
    for i in range(len(boxes)):
        out = tmp_path / f"{paper}_{i}.pdf"
        for j, it in enumerate(marks):        # jedna značka na průchod → obálka červené = jedna anotace
            it.setVisible(i == j)
        assert export_scene_pdf(sc, out, paper=paper, notes=True) == 2
        rect = next(a for a in _pdf_annots(out)[0] if str(a.get("/NM", "")) == f"envocad:{proj.notes[i].id}")
        got = [float(v) for v in rect["/Rect"]]
        assert got == pytest.approx(list(_red_bbox_pt(out)), abs=1.5), (paper, i)


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
    # A4/A3: poloha anotací vůči skutečnému vykreslení listu viz test_scene_pdf_note_annotations_match_render
    # vícepól připomínky nemá
    sb = proj.switchboards()[0]
    proj.notes.append(Note(sb.id, 50.0, 50.0, "x", no=2))
    out = tmp_path / "mp.pdf"
    assert export_scene_pdf(MultipoleScene(proj, sb, lib, QUndoStack()), out, notes=True) == 0
    assert not any(_pdf_annots(out))   # QPdfWriter píše prázdné /Annots [], anotace žádné
