"""Přehled použitých značek (legenda, issue #76): výkaz `reports.symbol_legend` (bez Qt), volitelná strana v PDF
„Celá dokumentace“ (`DocBuilder(legend=True)`, obsah, záložky) a otázka v `MainWindow.export_documentation`."""
import os
from collections import Counter

import pypdf
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from envocad.export import reports
from envocad.generate import build_project
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Sheet

NAME = "Přehled použitých značek"
HEAD = ["Značka", "Název", "Počet"]
SPEC = {"name": "Legenda", "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200,
                                          "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [20, 20]}]}
# skutečná symbol_id z knihovny a jejich názvy (řazení podle názvu: Pojistkový < Svodič < Svorkovnice)
FUSE, SPD, TERM = "fve.fuse_disconnect", "fve.spd", "sb.terminal_block"
FUSE_N, SPD_N, TERM_N = "Pojistkový odpínač", "Svodič přepětí (SPD)", "Svorkovnice"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


@pytest.fixture
def proj():
    return build_project(SPEC)


def _els(*ids):
    return [Element(i, attrs={"ref": f"X{n}"}) for n, i in enumerate(ids, 1)]


@pytest.fixture
def small():
    s1 = Sheet(name="List 1", elements=_els(SPD, TERM, SPD))
    s2 = Sheet(name="List 2", elements=_els(TERM, SPD, FUSE, TERM, TERM))
    return Project(name="Malý", sheets=[s1, s2])


# ---- a) výkaz (headless) ------------------------------------------------------------------------------------
def test_symbol_legend_exact_rows(lib, small):
    head, rows = reports.symbol_legend(small, lib)
    assert head == HEAD
    assert rows == [[FUSE, FUSE_N, 1], [SPD, SPD_N, 3], [TERM, TERM_N, 4]]
    assert all(isinstance(r[2], int) for r in rows)


def test_symbol_legend_sheet_filter(lib, small):
    _, rows = reports.symbol_legend(small, lib, small.sheets[0])
    assert rows == [[SPD, SPD_N, 2], [TERM, TERM_N, 1]]
    _, rows = reports.symbol_legend(small, lib, sheet=small.sheets[1])
    assert rows == [[FUSE, FUSE_N, 1], [SPD, SPD_N, 1], [TERM, TERM_N, 3]]


def test_symbol_legend_sorted_by_name_casefold_then_id(lib):
    p = Project(name="Řazení", sheets=[Sheet(elements=_els("zz.b", "aa.c", "zz.a", TERM, FUSE))])
    _, rows = reports.symbol_legend(p, lib)
    keys = [(r[1].casefold(), r[0]) for r in rows]
    assert keys == sorted(keys)
    ids = [r[0] for r in rows]
    assert ids[0] == "aa.c" and ids[-1] == "zz.b"


def test_symbol_legend_unknown_symbol_uses_id_as_name(lib):
    p = Project(name="Neznámé", sheets=[Sheet(elements=_els("nic.neexistuje", "nic.neexistuje", TERM))])
    _, rows = reports.symbol_legend(p, lib)
    assert ["nic.neexistuje", "nic.neexistuje", 2] in rows
    assert [TERM, TERM_N, 1] in rows


def test_symbol_legend_empty_project(lib):
    head, rows = reports.symbol_legend(Project(name="Prázdný", sheets=[Sheet()]), lib)
    assert head == HEAD and rows == []


def test_symbol_legend_total_equals_element_count(lib, proj):
    _, rows = reports.symbol_legend(proj, lib)
    expected = Counter(e.symbol_id for s in proj.sheets for e in s.elements)
    assert sum(r[2] for r in rows) == sum(len(s.elements) for s in proj.sheets) > 0
    assert {r[0]: r[2] for r in rows} == dict(expected)
    assert len({r[0] for r in rows}) == len(rows)


def test_symbol_legend_not_in_all_reports():
    assert reports.SYMBOL_LEGEND_NAME == NAME
    assert NAME not in [n for n, _fn in reports.ALL_REPORTS]
    assert reports.symbol_legend not in [fn for _n, fn in reports.ALL_REPORTS]


# ---- b) výchozí = vypnuto, beze změny -----------------------------------------------------------------------
def _plan(proj, lib, **kw):
    from envocad.export.doc_pdf import DocBuilder
    b = DocBuilder(proj, lib, **kw)
    b.plan()
    b._count_pages()
    return b


def test_default_has_no_legend_page(app, lib, proj):
    b = _plan(proj, lib)
    assert "legend" not in [k for k, _n, _d in b.pages]
    assert NAME not in [n for _k, n, _d in b.pages]
    assert b.pages[-1][0] == "changes"
    off = _plan(proj, lib, legend=False)
    assert [(k, n) for k, n, _d in off.pages] == [(k, n) for k, n, _d in b.pages]


def test_default_export_same_as_legend_false(app, lib, proj, tmp_path):
    from envocad.export.doc_pdf import export_documentation_pdf
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    na = export_documentation_pdf(proj, lib, a)
    nb = export_documentation_pdf(proj, lib, b, legend=False)
    ra, rb = pypdf.PdfReader(a), pypdf.PdfReader(b)
    assert na == nb == len(ra.pages) == len(rb.pages)
    ta, tb = [o.title for o in ra.outline], [o.title for o in rb.outline]
    assert ta == tb and NAME not in ta


# ---- c) zapnuto ---------------------------------------------------------------------------------------------
def test_legend_page_planned_before_changes(app, lib, proj):
    off = _plan(proj, lib)
    on = _plan(proj, lib, legend=True)
    assert [k for k, _n, _d in on.pages].count("legend") == 1
    k, name, data = on.pages[-2]
    assert (k, name) == ("legend", NAME)
    assert on.pages[-1] == ("changes", "Změnový list", None)
    assert [(k, n) for k, n, _d in on.pages[:-2]] + [on.pages[-1][:2]] == [(k, n) for k, n, _d in off.pages]
    head, rows = data
    assert (head, rows) == reports.symbol_legend(proj, lib)


def test_legend_export_adds_pages_toc_and_bookmark(app, lib, proj, tmp_path):
    from envocad.export.doc_pdf import export_documentation_pdf
    off = _plan(proj, lib)
    on = _plan(proj, lib, legend=True)
    idx = [k for k, _n, _d in on.pages].index("legend")
    out_off, out_on = tmp_path / "off.pdf", tmp_path / "on.pdf"
    n_off = export_documentation_pdf(proj, lib, out_off)
    n_on = export_documentation_pdf(proj, lib, out_on, legend=True)
    assert n_on == n_off + on.page_counts[idx] and on.page_counts[idx] >= 1
    r = pypdf.PdfReader(out_on)
    assert len(r.pages) == n_on == on._total
    assert (len(on.pages), len(off.pages)) == (len(off.pages) + 1, len(on.pages) - 1)
    # obsah
    toc = {row[1]: row for row in on._toc_rows(on.page_starts)}
    assert NAME in toc and str(on.page_starts[idx]) in [str(c) for c in toc[NAME]]
    # záložky
    marks = {o.title: r.get_destination_page_number(o) for o in r.outline}
    assert marks[NAME] == on.page_starts[idx] - 1
    assert [o.title for o in r.outline] == [row[1] for row in on._toc_rows(on.page_starts)]
    assert list(marks)[-2:] == [NAME, "Změnový list"]
    # text na straně legendy
    text = " ".join(r.pages[on.page_starts[idx] - 1].extract_text().split())
    assert NAME in text


# ---- d) GUI: otázka při exportu -----------------------------------------------------------------------------
@pytest.fixture
def window(app, tmp_path):
    from envocad.ui.main_window import MainWindow
    w = MainWindow(library=LibraryStore(tmp_path / "lib.db"), project=build_project(SPEC))
    w.undo.setClean()
    yield w
    w.undo.setClean()
    w.close()


def _mock_export(monkeypatch, tmp_path, answer=None):
    from PySide6.QtWidgets import QFileDialog, QInputDialog

    from envocad.export import doc_pdf
    asked: list[tuple[str, list, int]] = []
    answer = answer or {}

    def get_item(_parent, _title, label, items, current=0, _editable=False):
        asked.append((label, list(items), current))
        return answer.get(label[:12], items[current]), True
    calls: list[dict] = []
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(get_item))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda _p, _t, _l, text="": (text, True)))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(tmp_path / "d.pdf"), "")))
    monkeypatch.setattr(doc_pdf, "export_documentation_pdf", lambda *a, **k: calls.append(k) or 1)
    return asked, calls


def test_export_documentation_legend_off_by_default(window, tmp_path, monkeypatch):
    asked, calls = _mock_export(monkeypatch, tmp_path)
    window.export_documentation()
    q = [a for a in asked if a[0].startswith("Přehled použitých značek")]
    assert len(q) == 1
    label, items, current = q[0]
    assert label == "Přehled použitých značek (legenda):"
    assert items == ["Nepřidávat", "Přidat na konec dokumentace"] and current == 0
    assert asked.index(q[0]) < len(asked) - 1                 # JPS otázka zůstává poslední
    assert len(calls) == 1 and calls[0]["legend"] is False


def test_export_documentation_legend_on(window, tmp_path, monkeypatch):
    _asked, calls = _mock_export(monkeypatch, tmp_path, {"Přehled použ": "Přidat na konec dokumentace"})
    window.export_documentation()
    assert len(calls) == 1 and calls[0]["legend"] is True


def test_export_documentation_legend_cancel_skips_export(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    asked, calls = _mock_export(monkeypatch, tmp_path)

    def get_item(_parent, _title, label, items, current=0, _editable=False):
        asked.append((label, list(items), current))
        return ("", not label.startswith("Přehled použitých značek"))
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(get_item))
    window.export_documentation()
    assert any(a[0].startswith("Přehled použitých značek") for a in asked)
    assert calls == []
