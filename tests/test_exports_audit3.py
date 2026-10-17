"""Regrese nálezů QA auditu exportů (audit 3) a zbytku auditu rozvaděčů (audit 2 #2, #3, #11): stránkování plánu
svorkovnice, obsahu a změnového listu, tabulky v PDF, popisové pole, revize, výkazy, docx, xlsx, překlady Qt."""
import os
import re
from pathlib import Path

import pytest

from envocad.export import reports
from envocad.generate import build_project
from envocad.library.store import LibraryStore
from envocad.library.templates import apply_template
from envocad.model.project import Element, Project

SPEC = {"name": "Audit", "meta": {"investor": "Jan Novák", "order": "2026-045", "author": "P. Rychlík",
                                  "date": "17.10.2026"},
        "inverters": [
            {"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30,
             "strings": [20, 20]},
            {"ref": "T2", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30,
             "strings": [20, 20]}]}


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "l.db")


@pytest.fixture(scope="module")
def base_proj():
    return build_project(SPEC)


@pytest.fixture
def proj(base_proj):
    return Project.from_dict(base_proj.to_dict())


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _frame(on: bool, company: str | None = None) -> None:
    from envocad.settings import load_settings, save_settings
    s = load_settings()
    s["frame"] = on
    if company:
        s["standard"]["company"] = company
    save_settings(s)


def _sb(tid="ac_fve", params=None, n=1):
    p = Project()
    out = []
    for i in range(n):
        blk = Element("fve.switchboard", 120 + 10 * i, 150, attrs={"ref": f"R{i + 1}"})
        p.sheets[0].elements.append(blk)
        sb = p.create_switchboard_sheet(blk)
        apply_template(p, sb, tid, params or {})
        out.append(sb)
    return p, out


# ---- 1. plán svorkovnice: další sloupec / strana, nic se nevynechá ---------------------------------------------
def test_terminal_plan_layout_keeps_every_terminal():
    from envocad.model.frame import inner_box
    from envocad.model.terminal_plan import (
        BOTTOM_PAD,
        EXT_H,
        INT_H,
        T_H,
        T_W,
        StripPlan,
        TerminalRow,
        layout_plan_pages,
    )
    inner = inner_box(420.0, 297.0)
    plans = [StripPlan(f"X{i}", [TerminalRow(f"X{i}", str(k + 1), "L1", "e") for k in range(n)])
             for i, n in enumerate([50, 3, 2, 5, 5, 5, 5, 5, 5, 5, 5, 12, 40, 1], start=1)]
    pages = layout_plan_pages(plans, inner)
    placed = [(c.strip, r.number) for pg in pages for c in pg for r in c.rows]
    assert sorted(placed) == sorted((p.strip, r.number) for p in plans for r in p.rows)    # vše právě jednou
    assert len(pages) >= 2
    x0, y0, x1, y1 = inner
    for pg in pages:
        for c in pg:
            assert x0 < c.x and c.x + c.width <= x1 + 1e-6
            assert c.top + EXT_H <= y1 and c.top - T_H - INT_H >= y0 + BOTTOM_PAD - 1e-6
        # úseky jedné strany se nepřekrývají (ani nadpisy vedle sebe)
        for a in pg:
            for b in pg:
                if a is not b and a.top == b.top:
                    assert a.x + a.width <= b.x or b.x + b.width <= a.x
    # dlouhá svorkovnice se zalomí (pokračování), krátké jdou vedle sebe (víc úseků v jednom pásu)
    x1_chunks = [c for pg in pages for c in pg if c.strip == "X1"]
    assert len(x1_chunks) == 2 and x1_chunks[1].title.endswith("(pokračování)")
    assert max(len(x1_chunks[0].rows), len(x1_chunks[1].rows)) * T_W <= x1 - x0
    assert any(len({c.top for c in pg}) < len(pg) for pg in pages)


def test_terminal_plan_scene_pages_in_pdf_and_doc(qapp, lib, tmp_path):
    """Audit 2 #3: AC rozvaděč se svorkami a 9 vývody – všechny svorkovnice na stranách plánu (scéna, PDF listu,
    dokumentace)."""
    import pypdf

    from envocad.export.doc_pdf import DocBuilder
    from envocad.export.pdf_export import export_scene_pdf
    from envocad.ui.terminal_plan_view import TerminalPlanScene
    _frame(True)
    p, (sb,) = _sb("ac_fve", {"distribution": "terminals", "n_out": "9"})
    # jedna dlouhá svorkovnice (50 svorek) navíc
    from envocad.model.terminal_plan import StripPlan, TerminalRow
    sc = TerminalPlanScene(p, sb, lib, None)
    sc.plans.append(StripPlan("X99", [TerminalRow("X99", str(k + 1), "L1", "e") for k in range(50)]))
    from envocad.model.frame import frame_geometry
    from envocad.model.terminal_plan import layout_plan_pages
    sc.page_chunks = layout_plan_pages(sc.plans, frame_geometry(p, sb, view="plán svorkovnice").inner)
    rows = sorted((c.strip, r.number, r.conductor) for pg in sc.page_chunks for c in pg for r in c.rows)
    assert rows == sorted((pl.strip, r.number, r.conductor) for pl in sc.plans for r in pl.rows)
    sc.rebuild()
    strips = {pl.strip for pl in sc.plans if pl.rows}
    assert {c.strip for pg in sc.page_chunks for c in pg} == strips
    out = tmp_path / "plan.pdf"
    export_scene_pdf(sc, out)
    assert len(pypdf.PdfReader(out).pages) == len(sc.pages) >= 1
    b = DocBuilder(p, lib)
    n = b.export(tmp_path / "doc.pdf")
    i = next(k for k, (kind, _n, d) in enumerate(b.pages) if kind == "sheet" and d[1] == "terminals")
    assert b.page_counts[i] == len(sc.pages) and n == sum(b.page_counts)


# ---- 2., 3., 9. obsah, změnový list a tabulky stránkované, zalomené ---------------------------------------------
def test_toc_lists_all_items_with_page_and_sheet_numbers(qapp, lib, tmp_path):
    """Audit 2 #11: 20 rozvaděčů – obsah na víc stranách, všechny položky, čísla stran = skutečné strany."""
    from envocad.export.doc_pdf import DocBuilder
    from envocad.model.frame import sheet_number
    _frame(True)
    p, _sbs = _sb("dc", {"n_strings": "2"}, n=20)
    b = DocBuilder(p, lib)
    n = b.export(tmp_path / "doc.pdf")
    toc = b.pages.index(next(pg for pg in b.pages if pg[0] == "toc"))
    assert b.page_counts[toc] >= 2
    rows = b._toc_rows(b.page_starts)
    assert [r[1] for r in rows] == [name for _k, name, _d in b.pages]
    for r, st, cnt in zip(rows, b.page_starts, b.page_counts):
        assert r[0] == (str(st) if cnt == 1 else f"{st}–{st + cnt - 1}")
    assert b.page_starts[-1] + b.page_counts[-1] - 1 == n
    sheet_rows = [r for r, pg in zip(rows, b.pages) if pg[0] == "sheet"]
    assert all(r[2] == sheet_number(p, pg[2][0]) for r, pg in zip(sheet_rows, [x for x in b.pages if x[0] == "sheet"]))


def test_change_list_paginated_and_above_title_block(qapp, lib, proj, tmp_path):
    from envocad.export.doc_pdf import DocBuilder, _table_area, table_layout
    from envocad.model.frame import MARGIN, TB_H
    _frame(True)
    proj.meta["changes"] = "\n".join(f"B | 20.10.2026 | změna {i} " + "dlouhý popis " * (i % 4) * 12 + "| PR"
                                     for i in range(70))
    b = DocBuilder(proj, lib)
    b.export(tmp_path / "doc.pdf")
    i = next(k for k, pg in enumerate(b.pages) if pg[0] == "changes")
    lay = b._layout(i)
    assert lay.page_count >= 2 and b.page_counts[i] == lay.page_count
    assert [r for a, z in lay.pages for r in range(a, z)] == list(range(70))       # všechny řádky
    x0, bottom, x1, top = _table_area(proj)
    assert bottom >= MARGIN + TB_H                                                # nad popisovým polem
    for a, z in lay.pages:
        assert lay.head_h + sum(lay.heights[a:z]) <= top - bottom + 1e-6
    assert any(len(c[2]) > 1 for c in lay.cells)                                  # dlouhý popis se zalomí
    # tabulka s dlouhým textem: sloupce v šířce strany, žádný řádek buňky není širší než sloupec
    from envocad.ui.render import text_width
    head = ["Část", "Prvek", "Hodnoty", "Mez", "Výsledek"]
    rows = [["String", "G1", "20 modulů, Uoc(-10 °C) = 1083.6 V " * 6, "T1: Umax 1100 V " * 5, "OK"]] * 3
    t = table_layout(proj, head, rows)
    assert sum(t.widths) <= x1 - x0 + 1e-6
    for cells in t.cells:
        for w, lines in zip(t.widths, cells):
            assert all(text_width(s, 2.2) <= w for s in lines)
    assert len(t.cells[0][2]) > 1


def _pdf_text(page) -> str:
    return " ".join(page.extract_text().split())


def test_doc_without_frame_has_page_numbers(qapp, lib, proj, tmp_path):
    """Bez rámečku (není popisové pole) má každá strana „strana n/N“ v pravém dolním rohu."""
    import pypdf

    from envocad.export.doc_pdf import export_documentation_pdf
    _frame(False)
    out = tmp_path / "doc.pdf"
    n = export_documentation_pdf(proj, lib, out)
    r = pypdf.PdfReader(out)
    for k in (0, 1, n - 1):
        assert f"strana {k + 1}/{n}" in _pdf_text(r.pages[k])
    _frame(True)
    out2 = tmp_path / "doc2.pdf"
    export_documentation_pdf(proj, lib, out2)
    assert "strana 1/" not in _pdf_text(pypdf.PdfReader(out2).pages[0])


def test_doc_title_page_uses_company_from_standard(qapp, lib, proj, tmp_path):
    import pypdf

    from envocad.export.doc_pdf import export_documentation_pdf
    _frame(False, company="Firma Test a.s.")
    out = tmp_path / "doc.pdf"
    export_documentation_pdf(proj, lib, out)
    text = _pdf_text(pypdf.PdfReader(out).pages[0])
    assert "Firma Test a.s." in text and "ENVO s.r.o." not in text


# ---- 4., 5. změnový list v revizích ------------------------------------------------------------------------
def test_change_text_pipe_is_escaped_and_split_robust():
    from envocad.model.diff import Change, change_list_text, split_change_line
    t = change_list_text([Change("změněno", "JPS", "T1", "prvek", "type: A → B | C")], "B", "1.1.2026", "P|R")
    assert len(t.split("|")) == 4 and "B ¦ C" in t and t.endswith("P¦R")
    assert split_change_line("B | 1.1. | a | b | PR") == ["B", "1.1.", "a ¦ b", "PR"]
    assert split_change_line("B | 1.1.") == ["B", "1.1.", "", ""]


def test_merge_change_lines_replaces_open_revision_rows():
    from envocad.model.revision import merge_change_lines
    cur = "A | 1.1. | první | PR\nB | 2.1. | stará změna | PR"
    out = merge_change_lines(cur, {"B"}, "B | 3.1. | nová | PR\nB | 3.1. | druhá | PR")
    assert out.splitlines() == ["A | 1.1. | první | PR", "B | 3.1. | nová | PR", "B | 3.1. | druhá | PR"]
    assert merge_change_lines(out, {"B"}, "B | 3.1. | nová | PR\nB | 3.1. | druhá | PR") == out


def test_record_revision_twice_does_not_duplicate(qapp, lib, proj):
    from envocad.model.diff import change_list_text, diff_projects
    from envocad.ui.main_window import MainWindow
    old = Project.from_dict(proj.to_dict())
    proj.sheets[0].elements[0].attrs["type"] = "jiný | typ"
    ch = diff_projects(old, proj, lib)
    txt = change_list_text(ch, "B", "1.1.2026", "PR")
    w = MainWindow(library=lib, project=proj)
    try:
        assert w.record_revision(ch, "B", "1.1.2026", "PR", txt)
        once = proj.meta["changes"]
        assert w.record_revision(ch, "B", "1.1.2026", "PR", txt)
        assert proj.meta["changes"] == once and len(once.splitlines()) == len(set(once.splitlines()))
        # přejmenování otevřené revize nahradí její řádky (pod starým označením)
        assert w.record_revision(ch, "C", "2.1.2026", "PR", change_list_text(ch, "C", "2.1.2026", "PR"))
        assert all(ln.startswith("C ") for ln in proj.meta["changes"].splitlines())
        w.undo.undo()
        assert proj.meta["changes"] == once
    finally:
        w.undo.setClean()
        w.close()


# ---- 6. výpočty pro jeden list -------------------------------------------------------------------------------
def test_calculations_filtered_by_sheet(lib, proj):
    rh = proj.switchboards()[-1]
    _h, rows = reports.calculations(proj, lib, rh)
    assert not [r for r in rows if r[0] == "String"]
    jps = proj.sheets[0]
    _h, rows = reports.calculations(proj, lib, jps)
    assert [r for r in rows if r[0] == "String"]
    from envocad.model import calc
    sel_all = calc.check_selectivity(proj)
    assert sum(len(calc.check_selectivity(proj, s)) for s in proj.sheets) == len(sel_all)
    assert all(sc.sheet for sc in calc.check_strings(proj))


# ---- 7. export z pohledů --------------------------------------------------------------------------------------
def test_exports_from_derived_views(qapp, lib, proj, tmp_path, monkeypatch):
    import pypdf
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from envocad.ui.main_window import MainWindow
    msgs = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: msgs.append(a[1:3])))
    w = MainWindow(library=lib, project=proj)
    try:
        sb = proj.switchboards()[0]
        for kind in ("multipole", "terminals", "layout"):
            w.open_sheet(sb, kind)
            out = tmp_path / f"{kind}.pdf"
            monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, o=out, **k: (str(o), "")))
            w.export_pdf()
            assert out.exists() and len(pypdf.PdfReader(out).pages) >= 1, kind
            dxf = tmp_path / f"{kind}.dxf"
            monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, o=dxf, **k: (str(o), "")))
            n0 = len(msgs)
            w.export_dxf()
            assert not dxf.exists() and len(msgs) == n0 + 1 and "PDF" in msgs[-1][1], kind
    finally:
        w.undo.setClean()
        w.close()


# ---- 10. popisové pole a QR ------------------------------------------------------------------------------------
def test_title_block_text_fits_cell(proj):
    from envocad.model.frame import TB_W, TEXT_CHAR_W, fit_text, frame_geometry
    t, h = fit_text("x" * 200, 70.0, 2.5)
    assert t.endswith("…") and TEXT_CHAR_W * h * len(t) <= 70.0 + 1e-6
    assert fit_text("krátký", 70.0, 2.5) == ("krátký", 2.5)
    t, h = fit_text("RH – AC rozvaděč FVE – vícepólové schéma", 71.0, 2.5)
    assert not t.endswith("…") and h < 2.5
    s = proj.sheets[1]
    s.name = "Velmi dlouhý název listu rozvaděče, který by přetekl do sousední buňky"
    g = frame_geometry(proj, s, view="vícepólové schéma")
    lst = next(x for x in g.texts if x[2].startswith("Velmi"))
    assert lst[2].endswith("…") and lst[0] + TEXT_CHAR_W * lst[3] * len(lst[2]) <= lst[0] + (TB_W - 34) / 2 - 2 + 1e-6


def test_multipole_drawing_clear_of_title_block_and_qr(lib, proj):
    from envocad.model.frame import title_block_box
    from envocad.model.multipole_geometry import multipole_geometry
    _frame(True)
    rh = proj.switchboards()[-1]
    g = multipole_geometry(proj, rh, lib)
    tb = title_block_box(rh.width, rh.height)
    pitch = rh.height + 20.0
    for box, owner, _w in g.texts:
        k = g.page_of.get(owner.split("#")[0], 0)
        y0, y1 = box[1] + k * pitch, box[3] + k * pitch
        assert not (box[2] > tb[0] and box[0] < tb[2] and y0 < tb[3] and y1 > tb[1]), owner


def test_duplicate_pe_labels_on_shared_segment(lib, proj):
    """Vícepól DC rozvaděče: PE ze svodičů do XPE po společné čáře – popisek „PE“ jen jednou na úsek."""
    from itertools import combinations

    from envocad.model.multipole_geometry import multipole_geometry
    sb = next(s for s in proj.switchboards() if any(e.ref == "XPE" for e in s.elements))
    g = multipole_geometry(proj, sb, lib)
    pe = [(x, y) for (_w, c, _p), (x, y, text, _a) in g.conductor_labels.items() if text == "PE"]
    for (ax, ay), (bx, by) in combinations(pe, 2):
        assert not (abs(ax - bx) < 0.5 and abs(ay - by) < 6.0), (ax, ay, bx, by)


# ---- 11., 13. docx -----------------------------------------------------------------------------------------
def _docx_text(path) -> str:
    from docx import Document
    d = Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    return "\n".join(parts)


def test_routine_test_docx_a4_lang_properties_and_texts(lib, proj, tmp_path):
    from docx import Document

    from envocad.export.docx_export import export_routine_test_docx
    _frame(False, company="Firma Test a.s.")
    rh = proj.switchboards()[-1]
    rh.layout.params.update({"in_": "125 A", "mounting": "nástěnná", "material": "", "door": "", "depth_mm": ""})
    out = tmp_path / "p.docx"
    export_routine_test_docx(proj, lib, rh, out)
    d = Document(str(out))
    sec = d.sections[0]
    assert round(sec.page_width.mm) == 210 and round(sec.page_height.mm) == 297
    assert d.core_properties.author == "P. Rychlík" and d.core_properties.language == "cs-CZ"
    assert "Protokol" in d.core_properties.title and d.core_properties.created is not None
    assert 'w:val="cs-CZ"' in d.styles.element.xml
    text = _docx_text(out)
    assert "A A" not in text and "125 A" in text
    assert "/ /" not in text and "Montáž | nástěnná" in text
    assert "Rozměry (š × v) |" in text and " × 0 mm" not in text
    assert re.search(r"\b3 řady\b", text) and "Firma Test a.s." in text and "ENVO s.r.o." not in text


def test_tz_docx_header_and_wide_tables(lib, proj, tmp_path):
    from docx import Document
    from docx.enum.section import WD_ORIENT

    from envocad.export.tz_export import export_tz_docx
    proj.meta["revision"] = ""
    out = tmp_path / "tz.docx"
    export_tz_docx(proj, lib, out)
    d = Document(str(out))
    text = _docx_text(out)
    assert "Revize:" not in text and "Zpracoval: P. Rychlík" in text
    assert d.core_properties.title.startswith("Technická zpráva") and d.core_properties.language == "cs-CZ"
    assert round(d.sections[0].page_width.mm) == 210
    assert d.sections[-1].orientation == WD_ORIENT.LANDSCAPE                     # výkazy na šířku
    for t in d.tables:                                                           # šířky sloupců v šířce strany
        assert sum(c.width.mm for c in t.rows[0].cells) <= 297 - 40 + 1


# ---- 12. xlsx ----------------------------------------------------------------------------------------------
def test_xlsx_designations_text_and_numbers(qapp, lib, tmp_path):
    """Audit 2 #2: „=AC+RDC1-F1“ jako text (ne vzorec); audit 3 #19: průřez, délka, číslo žíly/svorky jako čísla."""
    from openpyxl import load_workbook

    from envocad.export.xlsx_export import export_reports_xlsx
    p = build_project(SPEC)
    for s in p.switchboards():
        s.func = "AC"
    out = tmp_path / "r.xlsx"
    export_reports_xlsx(p, lib, out)
    wb = load_workbook(out)
    formulas = [(ws.title, c.coordinate) for ws in wb for row in ws.iter_rows() for c in row if c.data_type == "f"]
    assert not formulas
    assert any(isinstance(c.value, str) and c.value.startswith("=AC")
               for ws in wb for row in ws.iter_rows() for c in row)

    def column(sheet, name):
        ws = wb[sheet]
        rows = list(ws.iter_rows(values_only=True))
        hi = next(i for i, r in enumerate(rows) if name in r)
        ci = rows[hi].index(name)
        return [r[ci] for r in rows[hi + 1:] if r[ci] not in (None, "")]
    for sheet, col in (("Kabely", "Průřez [mm²]"), ("Kabely", "Délka [m]"), ("Kabelový plán", "Č."),
                       ("Kabelový plán", "Průřez [mm²]"), ("Zapojovací seznam", "Průřez [mm²]")):
        vals = column(sheet, col)
        assert vals and all(isinstance(v, (int, float)) for v in vals), (sheet, col, vals[:3])
    nums = column("Svorkovnice", "Svorka")
    assert any(isinstance(v, int) for v in nums)
    assert all(isinstance(v, (int, float)) or not str(v).isdigit() for v in nums)


def test_number_conversion_rules():
    from envocad.export.xlsx_export import _number
    assert _number("6") == 6 and _number("1,5") == 1.5 and _number("2.5") == 2.5
    for keep in ("PE", "", "01", "+RDC1", "1/2", "X1:3", "nan", "inf"):
        assert _number(keep) == keep


# ---- 14. české Qt ------------------------------------------------------------------------------------------
def test_qt_buttons_czech(qapp):
    from PySide6.QtWidgets import QDialogButtonBox, QMessageBox

    from envocad.app import install_qt_translations
    assert install_qt_translations(qapp)
    m = QMessageBox(QMessageBox.Question, "t", "x", QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
    texts = {b.text().replace("&", "") for b in m.buttons()}
    assert {"Ano", "Ne"} <= texts
    bb = QDialogButtonBox(QDialogButtonBox.Cancel)
    assert bb.buttons()[0].text().replace("&", "") != "Cancel"


def test_pyinstaller_spec_bundles_qt_translations():
    spec = (Path(__file__).resolve().parent.parent / "envocad.spec").read_text(encoding="utf-8")
    assert "qtbase_cs.qm" in spec and "qt_cs.qm" in spec and "TranslationsPath" in spec


# ---- 15. revize nezměněného listu ----------------------------------------------------------------------------
def test_unchanged_sheet_shows_initial_revision(lib, proj):
    from envocad.model.diff import diff_projects
    from envocad.model.frame import sheet_revision_label
    from envocad.model.revision import apply_changes, open_revision
    proj.meta["revision"] = "A"
    old = Project.from_dict(proj.to_dict())
    proj.sheets[0].elements[0].attrs["type"] = "jiný"
    rev = open_revision(proj, "B", "1.1.2026", "PR")
    apply_changes(proj, rev, diff_projects(old, proj, lib))
    assert [r.label for r in proj.revisions] == ["A", "B"] and proj.revisions[0].closed
    assert sheet_revision_label(proj, proj.sheets[0]) == "B"
    assert sheet_revision_label(proj, proj.sheets[1]) == "A"           # nezměněný list = výchozí stav
    # bez revize ve vlastnostech projektu: nezměněný list prázdná revize (ne nová B)
    p2 = Project.from_dict(old.to_dict())
    p2.meta["revision"] = ""
    p2.sheets[0].elements[0].attrs["type"] = "jiný"
    rev = open_revision(p2, "B")
    apply_changes(p2, rev, diff_projects(old, p2, lib))
    assert sheet_revision_label(p2, p2.sheets[0]) == "B" and sheet_revision_label(p2, p2.sheets[1]) == ""


def test_conftest_installs_translator_for_session():
    from PySide6.QtWidgets import QApplication, QMessageBox
    assert QApplication.instance() is not None
    assert os.environ.get("QT_QPA_PLATFORM")
    m = QMessageBox(QMessageBox.Question, "t", "x", QMessageBox.Yes)
    assert m.buttons()[0].text().replace("&", "") == "Ano"


# ---- 16. rychlost: knihovna se při generování otevírá jednou, nezměněné soubory se nečtou znovu -----------------
def test_build_project_opens_library_once(monkeypatch):
    from envocad import generate
    from envocad.library import store
    n = []
    orig = store.LibraryStore.__init__

    def counting(self, *a, **k):
        n.append(1)
        orig(self, *a, **k)
    monkeypatch.setattr(store.LibraryStore, "__init__", counting)
    p = generate.build_project(SPEC)
    assert len(n) == 1 and generate._BUILD_LIB is None and p.switchboards()


def test_library_parse_cache_sees_changed_files(tmp_path, monkeypatch):
    import json
    import time

    from envocad.library.store import user_library_dir
    monkeypatch.setenv("ENVOCAD_HOME", str(tmp_path / "home"))
    d = user_library_dir() / "test"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "muj.json"
    from envocad.library.store import BUILTIN_DIR
    sym = json.loads((BUILTIN_DIR / "fve" / "fve.battery.json").read_text(encoding="utf-8"))
    sym.update(id="test.muj", name="Můj")
    f.write_text(json.dumps(sym), encoding="utf-8")
    c = d / "artikly.csv"
    c.write_text("id;manufacturer;part_number;name;symbol_id\nA1;ENVO;P1;První;test.muj\n", encoding="utf-8")
    assert LibraryStore().get_symbol("test.muj").name == "Můj"
    assert LibraryStore().component("A1").name == "První"
    time.sleep(0.01)
    f.write_text(json.dumps(dict(sym, name="Můj nový")), encoding="utf-8")
    c.write_text("id;manufacturer;part_number;name;symbol_id\nA1;ENVO;P1;Druhý název;test.muj\n", encoding="utf-8")
    assert LibraryStore().get_symbol("test.muj").name == "Můj nový"
    assert LibraryStore().component("A1").name == "Druhý název"
