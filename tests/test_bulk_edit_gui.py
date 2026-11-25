"""Hromadná úprava vlastností vybraných prvků (issue #77), GUI offscreen: `SchematicScene.apply_bulk_edit` (jedno
makro undo), `edit_elements_bulk`, `BulkElementDialog`, pole Poznámka v panelu Vlastnosti; shoda s headless
`bulk_edit_elements`."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFormLayout, QLabel, QLineEdit, QMessageBox, QPushButton

from envocad.cmd.edits import bulk_edit_elements
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project
from envocad.ui.canvas import SchematicScene, SchematicView
from envocad.ui.dialogs import BulkElementDialog, ElementDialog
from envocad.ui.panels import PropertiesPanel

ART = "eaton-az-3-b100"      # reálný artikl značky fve.breaker_mcb
MIXED = "(různé)"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _project():
    p = Project(name="Hromadna GUI")
    s = p.sheets[0]
    f1 = Element("fve.breaker_mcb", 30.0, 150.0, attrs={"ref": "F1", "func": "AC", "loc": "R1", "note": "společná",
                                                     "width_mm": "35"})
    f2 = Element("fve.breaker_mcb", 70.0, 150.0, attrs={"ref": "F2", "func": "DC", "loc": "R1", "note": "společná"})
    f3 = Element("fve.breaker_mcb", 110.0, 150.0, attrs={"ref": "F3", "loc": "R1", "note": "společná"})
    t1 = Element("fve.inverter", 150.0, 150.0, attrs={"ref": "T1"})
    s.elements += [f1, f2, f3, t1]
    return p


@pytest.fixture
def jps(app, lib):
    p = _project()
    undo = QUndoStack()
    sc = SchematicScene(p, p.sheets[0], lib, undo)
    yield p, sc, undo
    undo.clear()


def _state(p) -> str:
    return json.dumps(p.to_dict(), sort_keys=True, ensure_ascii=False)


def _ids(p, *refs):
    return [e.id for e in p.sheets[0].elements if e.ref in refs]


def _el(p, ref):
    return next(e for e in p.sheets[0].elements if e.ref == ref)


# ---- SchematicScene.apply_bulk_edit ------------------------------------------------------------------------
def test_apply_bulk_edit_is_one_undo_step(jps):
    p, sc, undo = jps
    eids = _ids(p, "F1", "F2", "F3")
    before = _state(p)
    n = sc.apply_bulk_edit(eids, func="rfve", loc="Q1", note=" pozn ", component=ART)
    assert n == 3
    after = _state(p)
    assert after != before
    assert undo.count() == 1 and undo.undoText().startswith("Upravit 3")
    for ref in ("F1", "F2", "F3"):
        e = _el(p, ref)
        assert (e.attrs["func"], e.attrs["loc"], e.attrs["note"], e.component_id) == ("RFVE", "Q1", "pozn", ART)
    assert "width_mm" not in _el(p, "F1").attrs or not _el(p, "F1").attrs["width_mm"]   # ruční rozměr zrušen
    undo.undo()                                      # jediný krok vrátí všechno
    assert _state(p) == before
    assert not undo.canUndo()
    undo.redo()
    assert _state(p) == after


def test_apply_bulk_edit_without_change_pushes_nothing(jps):
    p, sc, undo = jps
    before = _state(p)
    assert sc.apply_bulk_edit(_ids(p, "F1", "F2", "F3"), loc="R1") == 0       # už je R1
    assert sc.apply_bulk_edit(_ids(p, "F1", "F2", "F3")) == 0                  # vše None
    assert sc.apply_bulk_edit([], note="x") == 0
    assert undo.count() == 0 and _state(p) == before


def test_apply_bulk_edit_partial_count_and_clear(jps):
    p, sc, undo = jps
    assert sc.apply_bulk_edit(_ids(p, "F1", "F2", "F3"), func="DC") == 2       # F2 už DC
    assert undo.count() == 1
    assert sc.apply_bulk_edit(_ids(p, "F1", "F2", "F3"), note="") == 3
    assert all(not _el(p, r).attrs.get("note") for r in ("F1", "F2", "F3"))
    undo.undo()
    assert all(_el(p, r).attrs["note"] == "společná" for r in ("F1", "F2", "F3"))


def test_apply_bulk_edit_invalid_code_or_mixed_component_changes_nothing(jps):
    p, sc, undo = jps
    before = _state(p)
    with pytest.raises(ValueError):
        sc.apply_bulk_edit(_ids(p, "F1", "F2"), func="1x")
    with pytest.raises(ValueError):
        sc.apply_bulk_edit(_ids(p, "F1", "T1"), component=ART)
    assert undo.count() == 0 and _state(p) == before


def test_gui_matches_headless(jps):
    p, sc, _undo = jps
    twin = Project.from_dict(p.to_dict())
    eids = _ids(p, "F1", "F2", "F3")
    kw = {"func": "ac", "loc": "", "note": "n", "component": ART}
    n_gui = sc.apply_bulk_edit(eids, **kw)
    n_cmd = bulk_edit_elements(twin, twin.sheets[0], eids, **kw)
    assert n_gui == n_cmd == 3
    assert _state(p) == _state(twin)


# ---- BulkElementDialog -------------------------------------------------------------------------------------
def _dlg(p, lib, *refs):
    els = [_el(p, r) for r in refs]
    return BulkElementDialog(els, lib, None, p.sheets[0])


def test_dialog_mixed_and_common_fields(app, lib):
    p = _project()
    dlg = _dlg(p, lib, "F1", "F2", "F3")
    assert set(dlg.edits) >= {"func", "loc", "note"}
    assert dlg.edits["func"].text() == "" and dlg.edits["func"].placeholderText() == MIXED
    assert dlg.edits["loc"].text() == "R1"
    assert dlg.edits["note"].text() == "společná"
    assert dlg.values() == {}                       # nic se nezměnilo, ani „(různé)“
    assert dlg.component_id is None


def test_dialog_values_only_changed_fields(app, lib):
    p = _project()
    dlg = _dlg(p, lib, "F1", "F2", "F3")
    dlg.edits["func"].setText("rfve")               # (různé) → nová hodnota
    dlg.edits["note"].setText("")                   # společná → vymazat
    assert dlg.values() == {"func": "rfve", "note": ""}      # dialog vrací text jak je, velká písmena až bulk_changes
    assert "loc" not in dlg.values()
    dlg.edits["func"].setText("")                   # zpět na prázdné („(různé)“ nedotčené)
    assert "func" not in dlg.values()


def test_dialog_component(app, lib):
    p = _project()
    dlg = _dlg(p, lib, "F1", "F2", "F3")
    assert isinstance(dlg.comp_button, QPushButton) and dlg.comp_button.isEnabled()
    assert "component" not in dlg.values()
    dlg.set_component(ART)
    assert dlg.component_id == ART and dlg.values()["component"] == ART
    dlg.set_component(None)                         # „Zrušit“ – artikl se odebere všem
    assert dlg.component_id is None and "component" in dlg.values() and not dlg.values()["component"]


def test_dialog_component_same_for_all_is_not_a_change(app, lib):
    p = _project()
    for r in ("F1", "F2"):
        _el(p, r).component_id = ART
    dlg = _dlg(p, lib, "F1", "F2")
    assert dlg.component_id == ART and "component" not in dlg.values()


def test_dialog_component_disabled_for_different_symbols(app, lib):
    p = _project()
    dlg = _dlg(p, lib, "F1", "T1")
    assert dlg.comp_button.isEnabled() is False
    assert dlg.edits["note"].isEnabled()
    dlg.edits["note"].setText("x")
    assert dlg.values() == {"note": "x"}


@pytest.mark.parametrize("key", ["func", "loc"])
def test_dialog_invalid_code_does_not_close(app, lib, monkeypatch, key):
    for name in ("warning", "critical", "information"):     # kdyby dialog hlásil chybu modálně, test se nezasekne
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Ok))
    p = _project()
    dlg = _dlg(p, lib, "F1", "F2", "F3")
    dlg.edits[key].setText("1 neplatný!")
    dlg.accept()
    assert dlg.result() != QDialog.Accepted
    dlg.edits[key].setText("ok_1")
    dlg.accept()
    assert dlg.result() == QDialog.Accepted


# ---- SchematicScene.edit_elements_bulk ---------------------------------------------------------------------
def test_edit_elements_bulk_accepted_is_one_undo_step(jps, monkeypatch):
    p, sc, undo = jps

    def fake_exec(self):
        self.edits["func"].setText("rfve")
        self.edits["note"].setText("z dialogu")
        return QDialog.Accepted
    monkeypatch.setattr(BulkElementDialog, "exec", fake_exec)
    eids = _ids(p, "F1", "F2", "F3")
    before = _state(p)
    sc.edit_elements_bulk(eids)
    assert undo.count() == 1
    for ref in ("F1", "F2", "F3"):
        assert _el(p, ref).attrs["func"] == "RFVE" and _el(p, ref).attrs["note"] == "z dialogu"
        assert _el(p, ref).attrs["loc"] == "R1"             # nedotčené pole zůstalo
    undo.undo()
    assert _state(p) == before


def test_edit_elements_bulk_rejected_changes_nothing(jps, monkeypatch):
    p, sc, undo = jps
    monkeypatch.setattr(BulkElementDialog, "exec", lambda self: (self.edits["note"].setText("x"), QDialog.Rejected)[1])
    before = _state(p)
    sc.edit_elements_bulk(_ids(p, "F1", "F2"))
    assert undo.count() == 0 and _state(p) == before


def test_edit_elements_bulk_untouched_dialog_changes_nothing(jps, monkeypatch):
    p, sc, undo = jps
    monkeypatch.setattr(BulkElementDialog, "exec", lambda self: QDialog.Accepted)
    before = _state(p)
    sc.edit_elements_bulk(_ids(p, "F1", "F2", "F3"))
    assert undo.count() == 0 and _state(p) == before


# ---- panel Vlastnosti --------------------------------------------------------------------------------------
def test_properties_panel_has_note_field(jps):
    p, sc, _undo = jps
    panel = PropertiesPanel(sc.library)
    panel.show_item(sc.element_items[_el(p, "F1").id])
    labels = []
    for r in range(panel.form.rowCount()):
        it = panel.form.itemAt(r, QFormLayout.LabelRole)
        if it is not None and isinstance(it.widget(), QLabel):
            labels.append(it.widget().text())
    assert "Poznámka" in labels
    # úprava jde přes signál attr_edited s klíčem „note“
    got = []
    panel.attr_edited.connect(lambda *a: got.append(a))
    ed = next(w for w in panel.findChildren(QLineEdit) if w.text() == "společná")
    ed.setText("jiná")
    ed.editingFinished.emit()
    QApplication.processEvents()   # panel vysílá attr_edited odloženě (QTimer.singleShot po editingFinished)
    assert got and got[-1][2:] == ("note", "jiná")


# ---- oprava: nezměněné neplatné pole nebrání OK, skloňování, tooltip ---------------------------------------
def test_dialog_unchanged_invalid_common_code_does_not_block_ok(app, lib):
    p = _project()
    for ref in ("F1", "F2", "F3"):
        _el(p, ref).attrs["func"] = "1 neplatný!"      # starý společný neplatný kód
    dlg = _dlg(p, lib, "F1", "F2", "F3")
    assert dlg.edits["func"].text() == "1 neplatný!"
    dlg.edits["note"].setText("jen poznámka")
    dlg.accept()
    assert dlg.result() == QDialog.Accepted and dlg.values() == {"note": "jen poznámka"}
    dlg2 = _dlg(p, lib, "F1", "F2", "F3")
    dlg2.edits["func"].setText("1 jiný neplatný!")      # změněné pole se validuje dál
    dlg2.accept()
    assert dlg2.result() != QDialog.Accepted


def test_dialog_mixed_tooltip_and_plural(app, lib):
    p = _project()
    dlg = _dlg(p, lib, "F1", "F2", "F3")
    assert "Prázdné pole = ponechat rozdílné hodnoty" in dlg.edits["func"].toolTip()
    assert "Prázdné pole = ponechat" not in dlg.edits["loc"].toolTip()
    assert dlg.windowTitle() == "Upravit 3 prvky"
    assert _dlg(p, lib, "F1", "F2", "F3", "T1").windowTitle() == "Upravit 4 prvky"


def test_undo_text_plural(jps):
    p, sc, undo = jps
    sc.apply_bulk_edit(_ids(p, "F1", "F2", "F3", "T1"), note="a")
    assert undo.undoText() == "Upravit 4 prvky"
    sc.apply_bulk_edit(_ids(p, "F1", "F2"), note="b")
    assert undo.undoText() == "Upravit 2 prvky"


# ---- ElementDialog: pole Poznámka --------------------------------------------------------------------------
def _edlg(attrs):
    from envocad.library.store import LibraryStore
    sym = LibraryStore().get_symbol("fve.breaker_mcb")
    return ElementDialog(sym, attrs)


def test_element_dialog_note(app):
    dlg = _edlg({"ref": "F9"})
    assert "note" not in dlg.values()                   # prázdná poznámka při vložení nepřidá klíč
    dlg.note_edit.setText("  pozn  ")
    assert dlg.values()["note"] == "pozn"
    dlg2 = _edlg({"ref": "F9", "note": "stará"})
    assert dlg2.note_edit.text() == "stará"
    dlg2.note_edit.setText("")
    assert dlg2.values()["note"] == ""                  # vymazání existující
    assert dlg2._form.rowCount() > 0


# ---- dvojklik přes viewport (reálná sekvence stisků) --------------------------------------------------------
@pytest.fixture
def view(jps):
    p, sc, _undo = jps
    v = SchematicView(sc)
    v.resize(1200, 900)
    v.show()
    QTest.qWaitForWindowExposed(v)
    calls = []
    sc.edit_elements_bulk = lambda ids: calls.append(("bulk", sorted(ids)))
    sc.edit_element = lambda eid: calls.append(("single", eid))
    yield p, sc, v, calls
    v.close()


def _real_double_click(v, pt):
    vp = v.viewport()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, pt)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, pt)
    QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, pt)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, pt)
    QTest.qWait(30)


def test_double_click_in_multi_selection_opens_bulk_dialog(view):
    p, sc, v, calls = view
    ids = _ids(p, "F1", "F2", "F3")
    for i in ids:
        sc.element_items[i].setSelected(True)
    pt = v.mapFromScene(sc.element_items[ids[1]].sceneBoundingRect().center())
    _real_double_click(v, pt)
    assert calls == [("bulk", sorted(ids))]
    assert len([x for x in sc.selectedItems() if x.__class__.__name__ == "ElementItem"]) == 3


def test_double_click_with_single_selection_opens_element_dialog(view):
    p, sc, v, calls = view
    ids = _ids(p, "F1", "F2", "F3")
    sc.element_items[ids[1]].setSelected(True)
    pt = v.mapFromScene(sc.element_items[ids[1]].sceneBoundingRect().center())
    _real_double_click(v, pt)
    assert calls == [("single", ids[1])]


def test_double_click_outside_selection_opens_single_dialog(view):
    p, sc, v, calls = view
    ids = _ids(p, "F1", "F2", "F3")
    for i in ids[:2]:
        sc.element_items[i].setSelected(True)
    pt = v.mapFromScene(sc.element_items[ids[2]].sceneBoundingRect().center())
    _real_double_click(v, pt)                           # F3 nebyl ve výběru → obyčejná úprava jednoho prvku
    assert calls == [("single", ids[2])]
