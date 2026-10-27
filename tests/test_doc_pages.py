"""Číslování stran celé dokumentace v rámečku listů: `meta["doc_pages"]` (`frame.doc_page`), čísla stran z PDF
dokumentace (`doc_pdf.documentation_page_numbers`) a popisové pole „Číslo listu“ + „Strana“."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from envocad.generate import build_project
from envocad.library.store import LibraryStore
from envocad.model.frame import DOC_PAGES_KEY, doc_page, doc_page_key, frame_geometry, title_rows


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _project():
    return build_project({"inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200,
                                         "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [18, 18]}]})


def test_doc_page_lookup_and_title_rows():
    p = _project()
    s = p.sheets[0]
    assert doc_page(p, s.id) == ""                                   # bez číslování: jen číslo listu
    rows = title_rows(p, s)
    assert [c[0] for c in rows[2]] == ["List", "Číslo listu"]
    p.meta[DOC_PAGES_KEY] = json.dumps({"total": 28, "pages": {doc_page_key("schematic", s.id): 3,
                                                                 doc_page_key("multipole", "x", 1): 9}})
    assert doc_page(p, s.id) == "3/28" and doc_page(p, "x", "multipole", 1) == "9/28"
    assert doc_page(p, "x", "multipole", 2) == ""
    g = frame_geometry(p, s)                                         # JPS: strana podle uložených čísel
    texts = [t[2] for t in g.texts]
    assert "Strana" in texts and "3/28" in texts and "Číslo listu" in texts
    p.meta[DOC_PAGES_KEY] = "{rozbité"
    assert doc_page(p, s.id) == ""                                   # poškozená hodnota nevadí


def test_documentation_page_numbers_match_pdf_plan(app, tmp_path):
    from envocad.export.doc_pdf import DocBuilder, documentation_page_numbers, export_documentation_pdf
    p = _project()
    lib = LibraryStore()
    data = json.loads(documentation_page_numbers(p, lib))
    assert DOC_PAGES_KEY not in p.meta                               # projekt se nemění
    b = DocBuilder(p, lib)
    b.plan()
    b._count_pages()
    assert data["total"] == b._total
    jps = [s for s in p.sheets if not s.is_switchboard]
    assert data["pages"][doc_page_key("schematic", jps[0].id)] == 3  # titulní list, obsah, první list JPS
    boards = [s for s in p.sheets if s.is_switchboard]
    assert any(doc_page_key("multipole", s.id, 0) in data["pages"] for s in boards)
    nums = sorted(data["pages"].values())
    assert len(nums) == len(set(nums))                               # každá strana jen jednou
    out: list[str] = []
    n = export_documentation_pdf(p, lib, tmp_path / "doc.pdf", page_numbers=out)
    assert n == data["total"] and json.loads(out[0]) == data
