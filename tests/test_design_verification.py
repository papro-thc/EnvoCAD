"""Issue #126: ověření návrhu (ČSN EN 61439-1 čl. 10) v parametrech skříně, kontrole F7 a protokolu kusové zkoušky."""
import pytest

from envocad.model.project import Element, Layout, Project, Sheet

METHODS = ("zkouška", "výpočet", "pravidla konstrukce", "doklad výrobce skříně")


def _add_board(p: Project, name: str, **params) -> Sheet:
    blk = Element("fve.switchboard", 0, 0, attrs={"ref": name})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    sb.name = name
    sb.layout.params = dict(params)
    return sb


def _project(**params):
    p = Project()
    return p, _add_board(p, "RH", **params)


def _docx_text(path) -> str:
    from docx import Document
    d = Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    return "\n".join(parts)


def _docx_rows(path) -> list[list[str]]:
    from docx import Document
    return [[c.text for c in row.cells] for t in Document(str(path)).tables for row in t.rows]


@pytest.fixture(scope="module")
def lib():
    from envocad.library.store import LibraryStore
    return LibraryStore()


# ---- model ---------------------------------------------------------------------------------------------------
def test_methods_constant():
    from envocad.model.project import DESIGN_VERIFICATION_METHODS
    assert tuple(DESIGN_VERIFICATION_METHODS) == METHODS


def test_enclosure_params_have_dv_keys():
    from envocad.model.project import ENCLOSURE_PARAMS
    d = {k: (lab, default) for k, lab, default in ENCLOSURE_PARAMS}
    assert d["dv_method"] == ("Ověření návrhu – způsob", "")
    assert d["dv_document"] == ("Ověření návrhu – doklad", "")


@pytest.mark.parametrize("params, expected", [
    ({}, ("", "")),
    ({"dv_method": "výpočet", "dv_document": "P-2026-017"}, ("výpočet", "P-2026-017")),
    ({"dv_method": "  zkouška ", "dv_document": "   "}, ("zkouška", "")),
    ({"dv_document": " D-1 "}, ("", "D-1")),
])
def test_design_verification_accessor(params, expected):
    from envocad.model.project import design_verification
    assert design_verification(Layout(params=params)) == expected


def test_layout_roundtrip_keeps_dv_params():
    lay = Layout(params={"dv_method": "pravidla konstrukce", "dv_document": "Doklad č. 5"})
    back = Layout.from_dict(lay.to_dict())
    assert back.params["dv_method"] == "pravidla konstrukce" and back.params["dv_document"] == "Doklad č. 5"


# ---- kontrola F7 ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("params, words, absent", [
    ({}, ("způsob", "doklad"), ()),
    ({"dv_method": "   ", "dv_document": ""}, ("způsob", "doklad"), ()),
    ({"dv_document": "P-1"}, ("způsob",), ("doklad",)),
    ({"dv_method": "výpočet"}, ("doklad",), ("způsob",)),
])
def test_design_verification_findings_missing(params, words, absent):
    from envocad.model.checks import INFO, design_verification_findings
    p, sb = _project(**params)
    f = design_verification_findings(p)
    assert len(f) == 1, f
    x = f[0]
    assert x.code == "design_verification_missing" and x.severity == INFO
    assert x.sheet_id == sb.id and x.sheet_name == sb.name and x.target_id == "" and x.is_wire is False
    assert "61439-1" in x.text
    tail = x.text.split("není uveden", 1)[1]
    assert all(w in tail for w in words) and not any(w in tail for w in absent), x.text


def test_design_verification_findings_complete_is_clean():
    from envocad.model.checks import design_verification_findings
    p, _sb = _project(dv_method="zkouška", dv_document="P-1")
    assert design_verification_findings(p) == []


def test_design_verification_findings_ignores_non_switchboard():
    from envocad.model.checks import design_verification_findings
    assert design_verification_findings(Project()) == []


def test_check_project_reports_per_switchboard(lib):
    from envocad.model.checks import INFO, check_project
    p = Project()
    a = _add_board(p, "RA")
    b = _add_board(p, "RB", dv_method="výpočet", dv_document="X")
    c = _add_board(p, "RC", dv_document="Y")
    for aggregate in (False, True):
        f = [x for x in check_project(p, lib, standard_paper="A4", aggregate=aggregate)
             if x.code == "design_verification_missing"]
        assert {x.sheet_id for x in f} == {a.id, c.id}, aggregate
        assert len(f) == 2 and all(x.severity == INFO for x in f)
        assert b.id not in {x.sheet_id for x in f}


def test_check_project_single_switchboard(lib):
    from envocad.model.checks import check_project
    p, sb = _project()
    f = [x for x in check_project(p, lib, standard_paper="A4", aggregate=False)
         if x.code == "design_verification_missing"]
    assert [x.sheet_id for x in f] == [sb.id]


# ---- protokol ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("params, value", [
    ({}, "způsob: neuvedeno; doklad: neuvedeno"),
    ({"dv_method": "výpočet", "dv_document": "P-2026-017"}, "způsob: výpočet; doklad: P-2026-017"),
    ({"dv_method": "zkouška"}, "způsob: zkouška; doklad: neuvedeno"),
    ({"dv_document": "D-9"}, "způsob: neuvedeno; doklad: D-9"),
])
def test_protocol_identification_row(lib, tmp_path, params, value):
    from envocad.export.docx_export import export_routine_test_docx
    p, sb = _project(**params)
    out = tmp_path / "p.docx"
    export_routine_test_docx(p, lib, sb, out)
    rows = [r for r in _docx_rows(out) if r and r[0] == "Ověření návrhu (čl. 10)"]
    assert len(rows) == 1 and rows[0][1] == value, rows


def test_protocol_still_has_no_thermal_rise(lib, tmp_path):
    from envocad.export.docx_export import export_routine_test_docx
    p, sb = _project(dv_method="výpočet", dv_document="P-1")
    out = tmp_path / "p.docx"
    export_routine_test_docx(p, lib, sb, out)
    text = _docx_text(out)
    assert "Ověření návrhu (čl. 10)" in text
    assert "oteplení" not in text.lower() and "60890" not in text


def test_signer_default_empty():
    from envocad.settings import DEFAULTS, routine_test_signer
    assert DEFAULTS["standard"]["routine_test_signer"] == ""
    assert routine_test_signer() == ""


def _signature_row(path) -> list[str]:
    from docx import Document
    for t in Document(str(path)).tables:
        if [c.text for c in t.rows[0].cells] == ["Zkoušku provedl", "Datum", "Podpis"]:
            return [c.text for c in t.rows[1].cells]
    raise AssertionError("tabulka se podpisem nenalezena")


def test_signer_from_settings_prefills_signature(lib, tmp_path):
    from envocad.export.docx_export import export_routine_test_docx
    from envocad.settings import load_settings, routine_test_signer, save_settings
    data = load_settings()
    data["standard"]["routine_test_signer"] = "  Testovací Technik  "   # ENVOCAD_HOME je izolovaný (conftest)
    save_settings(data)
    assert routine_test_signer() == "Testovací Technik"
    p, sb = _project()
    out = tmp_path / "p.docx"
    export_routine_test_docx(p, lib, sb, out)
    assert _signature_row(out) == ["Testovací Technik", "", ""]


def test_signature_empty_without_signer(lib, tmp_path):
    from envocad.export.docx_export import export_routine_test_docx
    p, sb = _project()
    out = tmp_path / "p.docx"
    export_routine_test_docx(p, lib, sb, out)
    assert _signature_row(out) == ["", "", ""]


# ---- GUI -----------------------------------------------------------------------------------------------------
@pytest.fixture
def gui_panel():
    """Panel skříně napojený na QUndoStack stejně jako v `MainWindow._build_tab` + `commit_layout`."""
    from PySide6.QtGui import QUndoStack

    from envocad.ui import commands
    from envocad.ui.dialogs import EnclosurePanel
    sb = Sheet(kind="switchboard", layout=Layout(params={"ip": "IP 55"}))
    undo = QUndoStack()
    holder = {}

    def commit(before, after, key=None):
        undo.push(commands.SetLayoutCommand(sb, before, after, "Skříň rozvaděče",
                                            on_change=lambda s: holder["panel"].load_from_model(), merge_key=key))

    panel = EnclosurePanel(sb, commit=commit)
    holder["panel"] = panel
    return sb, panel, undo


def test_panel_dv_widgets(gui_panel):
    from PySide6.QtWidgets import QComboBox, QLineEdit
    _sb, panel, _undo = gui_panel
    combo = panel._choices["dv_method"]
    assert isinstance(combo, QComboBox) and isinstance(panel._edits["dv_document"], QLineEdit)
    assert [combo.itemData(i) for i in range(combo.count())] == ["", *METHODS]
    assert combo.itemText(0) == "neuvedeno"
    assert [combo.itemText(i) for i in range(1, combo.count())] == list(METHODS)


def test_panel_dv_method_undo_redo(gui_panel):
    sb, panel, undo = gui_panel
    combo = panel._choices["dv_method"]
    combo.setCurrentIndex(combo.findData("výpočet"))
    assert sb.layout.params["dv_method"] == "výpočet" and undo.count() == 1
    undo.undo()
    assert "dv_method" not in sb.layout.params and combo.currentData() == ""
    undo.redo()
    assert sb.layout.params["dv_method"] == "výpočet" and combo.currentData() == "výpočet"


def test_panel_dv_method_neuvedeno_removes_key(gui_panel):
    sb, panel, _undo = gui_panel
    combo = panel._choices["dv_method"]
    combo.setCurrentIndex(combo.findData("zkouška"))
    assert sb.layout.params["dv_method"] == "zkouška"
    combo.setCurrentIndex(0)
    assert "dv_method" not in sb.layout.params


def test_panel_dv_document_undo_redo(gui_panel):
    sb, panel, undo = gui_panel
    ed = panel._edits["dv_document"]
    ed.setText("P-2026-017")
    ed.editingFinished.emit()
    assert sb.layout.params["dv_document"] == "P-2026-017" and undo.count() == 1
    undo.undo()
    assert "dv_document" not in sb.layout.params and ed.text() == ""
    undo.redo()
    assert sb.layout.params["dv_document"] == "P-2026-017" and ed.text() == "P-2026-017"


def test_panel_dv_independent_of_wiring_group(gui_panel):
    sb, panel, _undo = gui_panel
    assert not panel.wiring_group.isChecked()
    combo = panel._choices["dv_method"]
    combo.setCurrentIndex(combo.findData("pravidla konstrukce"))
    panel._edits["dv_document"].setText("D-1")
    panel._edits["dv_document"].editingFinished.emit()
    assert sb.layout.params["dv_method"] == "pravidla konstrukce" and sb.layout.params["dv_document"] == "D-1"
    assert not any(k.startswith("wire_") for k in sb.layout.params)


def test_panel_loads_dv_from_model():
    from envocad.ui.dialogs import EnclosurePanel
    sb = Sheet(kind="switchboard", layout=Layout(params={"dv_method": "doklad výrobce skříně", "dv_document": "Z-3"}))
    panel = EnclosurePanel(sb)
    assert panel._choices["dv_method"].currentData() == "doklad výrobce skříně"
    assert panel._edits["dv_document"].text() == "Z-3"
