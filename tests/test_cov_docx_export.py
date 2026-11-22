"""Charakterizační testy pomocných funkcí `envocad/export/docx_export.py` (bez Qt, zápis jen do tmp_path).

Doplňují `tests/test_export_content.py`, `tests/test_exports_audit3.py` a `tests/test_tz_dsps.py`."""
import pytest
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn

from envocad.export import docx_export as dx
from envocad.library.store import LibraryStore
from envocad.model.project import Project, Sheet


# ---- setup_document: chybějící prvky stylů ---------------------------------------------------------------------
def test_setup_document_creates_missing_doc_defaults():
    doc = Document()
    styles = doc.styles.element
    old = styles.find(qn("w:docDefaults"))
    if old is not None:
        styles.remove(old)
    dx.setup_document(doc, "Název")
    defaults = styles.find(qn("w:docDefaults"))
    assert defaults is not None and styles.index(defaults) == 0   # vloženo na začátek
    lang = defaults.find(qn("w:rPrDefault")).find(qn("w:rPr")).find(qn("w:lang"))
    assert lang.get(qn("w:val")) == "cs-CZ" and lang.get(qn("w:eastAsia")) == "cs-CZ"


def test_setup_document_creates_missing_rpr_default_and_rpr():
    doc = Document()
    defaults = doc.styles.element.find(qn("w:docDefaults"))
    rpr_default = defaults.find(qn("w:rPrDefault"))
    if rpr_default is not None:
        defaults.remove(rpr_default)
    dx.setup_document(doc, "Název")
    rpr_default = defaults.find(qn("w:rPrDefault"))
    assert rpr_default is not None and rpr_default.find(qn("w:rPr")) is not None
    assert rpr_default.find(qn("w:rPr")).find(qn("w:lang")).get(qn("w:val")) == "cs-CZ"


def test_setup_document_creates_missing_rpr_inside_rpr_default():
    doc = Document()
    rpr_default = doc.styles.element.find(qn("w:docDefaults")).find(qn("w:rPrDefault"))
    for child in list(rpr_default):
        rpr_default.remove(child)
    dx.setup_document(doc, "Název")
    assert rpr_default.find(qn("w:rPr")).find(qn("w:lang")).get(qn("w:val")) == "cs-CZ"


def test_setup_document_properties_and_a4():
    doc = Document()
    dx.setup_document(doc, "Název", author="Autor", subject="Předmět")
    cp = doc.core_properties
    assert (cp.title, cp.subject, cp.author, cp.language) == ("Název", "Předmět", "Autor", "cs-CZ")
    assert cp.comments == "Vygenerováno programem EnvoCAD"
    sec = doc.sections[0]
    assert round(sec.page_width.mm) == 210 and round(sec.page_height.mm) == 297
    assert round(sec.left_margin.mm) == 20


# ---- doc_author -----------------------------------------------------------------------------------------------
def test_doc_author_prefers_project_meta():
    p = Project()
    p.meta["author"] = "  Jan Novák "
    assert dx.doc_author(p) == "Jan Novák"


def test_doc_author_falls_back_to_standard(monkeypatch):
    import envocad.settings as st
    monkeypatch.setattr(st, "load_settings", lambda: {"standard": {"author": " Firma "}})
    assert dx.doc_author(Project()) == "Firma"


def test_doc_author_returns_empty_when_settings_fail(monkeypatch):
    import envocad.settings as st

    def boom():
        raise OSError("nelze číst")
    monkeypatch.setattr(st, "load_settings", boom)
    assert dx.doc_author(Project()) == ""


# ---- set_landscape --------------------------------------------------------------------------------------------
def test_set_landscape_noop_when_orientation_already_matches():
    doc = Document()
    dx.set_landscape(doc, False)           # výchozí je na výšku → nic se nemění
    assert len(doc.sections) == 1 and doc.sections[-1].orientation == WD_ORIENT.PORTRAIT


def test_set_landscape_adds_section_with_swapped_dimensions():
    doc = Document()
    w, h = doc.sections[-1].page_width, doc.sections[-1].page_height
    dx.set_landscape(doc, True)
    assert len(doc.sections) == 2
    new = doc.sections[-1]
    assert new.orientation == WD_ORIENT.LANDSCAPE and (new.page_width, new.page_height) == (h, w)
    dx.set_landscape(doc, True)            # podruhé už nic
    assert len(doc.sections) == 2
    dx.set_landscape(doc, False)
    assert len(doc.sections) == 3 and doc.sections[-1].orientation == WD_ORIENT.PORTRAIT


# ---- _col_widths_mm -------------------------------------------------------------------------------------------
def test_col_widths_scales_minimums_when_even_longest_words_do_not_fit():
    head = [f"Sloupec{i}" for i in range(10)]
    rows = [["x" * 18 + " " + "y" * 30] * 10]
    widths = dx._col_widths_mm(head, rows, 50.0)
    assert len(widths) == 10 and sum(widths) == pytest.approx(50.0)
    assert len({round(w, 6) for w in widths}) == 1   # stejná minima → stejné šířky


def test_col_widths_interpolates_between_minimum_and_natural():
    head = ["A", "B"]
    rows = [["slovo " * 20, "slovo " * 20]]
    widths = dx._col_widths_mm(head, rows, 100.0)
    assert sum(widths) == pytest.approx(100.0)
    # minimum = nejdelší slovo (5 znaků), přirozená šířka = celý text (119 znaků) > šířka strany
    assert widths[0] == pytest.approx(widths[1]) and 10.0 < widths[0] <= 50.0


def test_col_widths_natural_fits_is_stretched_to_available():
    widths = dx._col_widths_mm(["A", "B"], [["a", "bbbbbbbbbb"]], 170.0)
    assert sum(widths) == pytest.approx(170.0) and widths[1] > widths[0]


# ---- _with_unit, _count ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("value, unit, expected", [
    ("125", "A", "125 A"), ("125 A", "A", "125 A"), ("125a", "A", "125a"), (None, "A", ""), ("  ", "kA", ""),
    (16, "A", "16 A"),
])
def test_with_unit(value, unit, expected):
    assert dx._with_unit(value, unit) == expected


@pytest.mark.parametrize("n, expected", [
    (1, "1 řada"), (3, "3 řady"), (5, "5 řad"), (2.5, "2.5 řady"), ("4", "4 řady"),
    ("abc", "abc řad"), (None, "None řad"),
])
def test_count_czech_forms_and_non_numeric_fallback(n, expected):
    assert dx._count(n, "řada", "řady", "řad") == expected


# ---- _thermal_text --------------------------------------------------------------------------------------------
def test_thermal_text_is_empty_when_calculation_fails(monkeypatch):
    import envocad.model.thermal as th

    def boom(*a, **k):
        raise ValueError("výpočet selhal")
    monkeypatch.setattr(th, "temperature_rise", boom)
    p = Project()
    s = Sheet(name="R", kind="switchboard")
    p.sheets.append(s)
    assert dx._thermal_text(p, LibraryStore(), s) == ""


def test_thermal_text_summarises_result_for_empty_board():
    p = Project()
    s = Sheet(name="R", kind="switchboard")
    p.sheets.append(s)
    text = dx._thermal_text(p, LibraryStore(), s)
    assert text.startswith("ΣPv ") and " W" in text and "okolí" in text and "horní část ≈" in text
