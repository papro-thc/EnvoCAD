"""Záložky (osnova) v PDF „Celá dokumentace“: `pdf_outline.add_bookmarks` (pypdf, bez Qt) a jeho použití v
`DocBuilder.export` – jedna plochá záložka na každý řádek obsahu, cíl = první strana položky."""
import os

import pypdf
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from envocad.generate import build_project
from envocad.library.store import LibraryStore

SPEC = {"name": "Záložky", "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200,
                                          "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [20, 20]}]}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


@pytest.fixture
def proj():
    p = build_project(SPEC)
    for s in p.switchboards():
        s.width = 200.0          # úzký list → vícepól na 2 strany, další položky se posunou
    return p


def _plan(proj, lib):
    from envocad.export.doc_pdf import DocBuilder
    b = DocBuilder(proj, lib)
    b.plan()
    b._count_pages()
    return b


def _flat(outline) -> bool:
    return all(not isinstance(o, list) for o in outline)


def _blank_pdf(path, n_pages=4):
    wr = pypdf.PdfWriter()
    for i in range(n_pages):
        wr.add_blank_page(width=300 + 10 * i, height=200 + 5 * i)
    with open(path, "wb") as f:
        wr.write(f)


def _text_pdf(path, n_pages=4):
    """PDF s textem na každé straně (jiný rozměr i obsah každé strany), vyrobené QPdfWriterem."""
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter
    w = QPdfWriter(str(path))
    w.setResolution(72)
    painter = QPainter(w)
    for i in range(n_pages):
        if i:
            w.setPageLayout(QPageLayout(QPageSize(QSizeF(200 + 20 * i, 150), QPageSize.Millimeter),
                                        QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
            w.newPage()
        painter.drawText(20, 40, f"Strana číslo {i + 1}")
    painter.end()


def _snapshot(path):
    r = pypdf.PdfReader(path)
    return [(tuple(float(v) for v in p.mediabox), p.get_contents().get_data()) for p in r.pages]


# ---- add_bookmarks (jednotkově) -----------------------------------------------------------------------------
def test_add_bookmarks_flat_outline_in_order(tmp_path):
    from envocad.export.pdf_outline import add_bookmarks
    f = tmp_path / "a.pdf"
    _blank_pdf(f)
    items = [("Titulní list", 0), ("Změnový list", 3), ("Obsah", 1)]     # pořadí zadání = pořadí osnovy
    assert add_bookmarks(f, items) == 3
    r = pypdf.PdfReader(f)
    assert _flat(r.outline)
    assert [o.title for o in r.outline] == [t for t, _ in items]
    assert [r.get_destination_page_number(o) for o in r.outline] == [0, 3, 1]


def test_add_bookmarks_keeps_pages_unchanged(tmp_path):
    from envocad.export.pdf_outline import add_bookmarks
    f = tmp_path / "t.pdf"
    _text_pdf(f)
    before = _snapshot(f)
    assert len(before) == 4 and len({m for m, _ in before}) > 1          # smíšené formáty stran
    assert add_bookmarks(f, [("Úvod", 0), ("Konec", 3)]) == 2
    assert _snapshot(f) == before
    assert len(pypdf.PdfReader(f).outline) == 2


def test_add_bookmarks_nothing_to_add_keeps_file(tmp_path):
    from envocad.export.pdf_outline import add_bookmarks
    f = tmp_path / "e.pdf"
    _blank_pdf(f, 2)
    raw = f.read_bytes()
    assert add_bookmarks(f, []) == 0
    assert f.read_bytes() == raw


def test_add_bookmarks_out_of_range(tmp_path):
    from envocad.export.pdf_outline import add_bookmarks
    f = tmp_path / "r.pdf"
    _blank_pdf(f, 2)
    with pytest.raises(IndexError):
        add_bookmarks(f, [("Mimo", 5)])
    with pytest.raises(IndexError):
        add_bookmarks(f, [("Ok", 0), ("Záporný", -1)])


def test_add_bookmarks_diacritics(tmp_path):
    from envocad.export.pdf_outline import add_bookmarks
    f = tmp_path / "d.pdf"
    _blank_pdf(f, 2)
    names = ["Titulní list", "Změnový list", "Řídicí rozvaděč – plán svorkovnice"]
    add_bookmarks(f, [(n, i % 2) for i, n in enumerate(names)])
    assert [o.title for o in pypdf.PdfReader(f).outline] == names


# ---- export celé dokumentace --------------------------------------------------------------------------------
def test_documentation_pdf_has_outline_matching_toc(app, lib, proj, tmp_path):
    from envocad.export.doc_pdf import export_documentation_pdf
    b = _plan(proj, lib)
    expected = [r[1] for r in b._toc_rows(b.page_starts)]
    assert any(c > 1 for c in b.page_counts)                       # vícestránkové položky → čísla nejsou 0, 1, 2…
    assert b.page_starts != list(range(1, len(b.pages) + 1))
    out = tmp_path / "dok.pdf"
    n = export_documentation_pdf(proj, lib, out)
    r = pypdf.PdfReader(out)
    assert n == len(r.pages) == b._total
    assert _flat(r.outline)
    titles = [o.title for o in r.outline]
    assert titles == expected
    assert titles[0] == "Titulní list" and titles[1] == "Obsah" and titles[-1] == "Změnový list"
    pages = [r.get_destination_page_number(o) for o in r.outline]
    assert pages == [s - 1 for s in b.page_starts]
    assert pages == sorted(pages) and len(set(pages)) == len(pages)


def test_documentation_pdf_outline_names_with_diacritics(app, lib, proj, tmp_path):
    from envocad.export.doc_pdf import export_documentation_pdf
    out = tmp_path / "dia.pdf"
    export_documentation_pdf(proj, lib, out)
    titles = [o.title for o in pypdf.PdfReader(out).outline]
    assert "Titulní list" in titles and "Změnový list" in titles


def test_documentation_pdf_outline_with_notes(app, lib, proj, tmp_path):
    """Záložky i anotace připomínek v jednom PDF (druhý průchod pypdf nesmí osnovu ani anotace ztratit)."""
    from envocad.export.doc_pdf import DocBuilder
    from envocad.model.project import Note
    jps = proj.sheets[0]
    proj.notes = [Note(jps.id, 100.0, 100.0, "Doplnit SPD", no=1)]
    out = tmp_path / "pozn.pdf"
    b = DocBuilder(proj, lib)
    b.export(out, notes=True)
    r = pypdf.PdfReader(out)
    assert [o.title for o in r.outline] == [row[1] for row in b._toc_rows(b.page_starts)]
    assert [r.get_destination_page_number(o) for o in r.outline] == [s - 1 for s in b.page_starts]
    notes = [a.get_object() for pg in r.pages for a in (pg.get("/Annots") or [])
             if a.get_object()["/Subtype"] == "/Text"]
    assert [a["/Contents"] for a in notes] == ["Doplnit SPD"]
