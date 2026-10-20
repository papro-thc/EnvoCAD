"""Po vložení prvku jdou upravit jeho parametry v panelu Vlastnosti – ve všech editorech."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QLineEdit

from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project
from envocad.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _pump(app, n=6):
    for _ in range(n):
        app.processEvents()


def _edit_ref_field(win, app, value):
    """Přepíše pole „Označení“ (ref) v panelu Vlastnosti a simuluje ztrátu fokusu."""
    fields = win.props_panel.findChildren(QLineEdit)
    assert fields, "panel Vlastnosti je prázdný (Nic není vybráno)"
    fields[0].setText(value)
    fields[0].editingFinished.emit()
    _pump(app)


def _sb_window(app, tmp_path, open_jps):
    p = Project(name="Vlastnosti")
    sb = p.sheets[0]
    sb.kind = "switchboard"
    win = MainWindow(LibraryStore(tmp_path / "lib.db"), p)
    win._edit_element_anywhere = lambda *a, **k: None   # bez modálního dialogu
    if open_jps:
        win.open_sheet(sb, "schematic")
    win.open_sheet(sb, "multipole")
    win.show()
    _pump(app)
    return win, sb


@pytest.mark.parametrize("open_jps", [True, False])
def test_multipole_insert_then_edit_in_panel(app, tmp_path, open_jps):
    win, sb = _sb_window(app, tmp_path, open_jps)
    sc = win.view.scene()
    sc.start_place("fve.breaker_mcb")
    sc._place_at(QPointF(300, -100))
    _pump(app)
    new = sb.elements[-1]
    sc.rebuild()
    next(it for it in sc._pole_items[new.id]).setSelected(True)
    _pump(app)
    _edit_ref_field(win, app, "F77")
    assert sb.element(new.id).attrs["ref"] == "F77"
    win.undo.undo()
    assert sb.element(new.id).attrs["ref"] != "F77"
    win.undo.redo()
    assert sb.element(new.id).attrs["ref"] == "F77"
    win.undo.setClean()
    win.close()


def test_layout_select_then_edit_in_panel(app, tmp_path):
    win, sb = _sb_window(app, tmp_path, open_jps=False)
    e = Element("fve.breaker_mcb", 0, 0, attrs={"ref": "F1", "modules": "2"})
    sb.elements.append(e)
    win.open_sheet(sb, "layout")
    sc = win.view.scene()
    sc.rebuild()
    item = sc.items_by_id[e.id]
    item.setSelected(True)
    _pump(app)
    fields = win.props_panel.findChildren(QLineEdit)
    assert fields
    fields[0].setText("F9")
    fields[0].editingFinished.emit()
    _pump(app)
    assert sb.element(e.id).attrs["ref"] == "F9"
    win.undo.undo()
    assert sb.element(e.id).attrs["ref"] == "F1"
    win.undo.setClean()
    win.close()


@pytest.mark.parametrize("sid", ["fve.breaker_mcb", "sb.feed", "fve.interrupt", "fve.inverter"])
def test_schematic_place_then_edit_in_panel(app, tmp_path, sid):
    p = Project(name="JPS")
    win = MainWindow(LibraryStore(tmp_path / "lib.db"), p)
    win.show()
    _pump(app)
    sc = win.scene
    sym = win.library.get_symbol(sid)
    e = Element(sid, 100, 100, attrs={a.key: a.default for a in sym.attributes})
    e.attrs["ref"] = "Z1"
    win.undo.push(__import__("envocad.ui.commands", fromlist=["x"]).AddElementCommand(sc, e))
    _pump(app)
    sc.clearSelection()
    sc.element_items[e.id].setSelected(True)
    _pump(app)
    _edit_ref_field(win, app, "Z5")
    assert sc.sheet.element(e.id).attrs["ref"] == "Z5"
    win.undo.undo()
    assert sc.sheet.element(e.id).attrs["ref"] == "Z1"
    win.undo.redo()
    assert sc.sheet.element(e.id).attrs["ref"] == "Z5"
    win.undo.setClean()
    win.close()
