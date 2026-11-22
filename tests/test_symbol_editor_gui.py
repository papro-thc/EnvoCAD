"""Editor symbolů v GUI (issue #85, fáze 1) – offscreen. QMessageBox se vždy monkeypatchuje (modální dialog by zasekl sadu)."""
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from envocad.library.store import LibraryStore
from envocad.model.project import Project
from envocad.model.symbol import Attribute, Port, Symbol

BUILTIN = "fve.breaker_mcb"
YES, NO = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No


@pytest.fixture
def lib(tmp_path):
    store = LibraryStore(tmp_path / "lib.db")
    yield store
    store.close()


@pytest.fixture
def boxes(monkeypatch):
    """Zachytí QMessageBox.warning / question; odpověď na question se nastavuje `boxes.answer`."""
    c = SimpleNamespace(warning=[], question=[], answer=YES)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: c.warning.append(a) or QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: c.question.append(a) or c.answer)
    return c


def _dialog(lib, sid):
    from envocad.ui.symbol_editor import SymbolEditorDialog
    d = SymbolEditorDialog(lib, sid)
    QApplication.processEvents()
    return d


def _user_symbol(sid="user.test"):
    return Symbol(id=sid, name="Test", category="Uživatelské",
                  ports=[Port("A", 0, 0, "W"), Port("B", 5, 0, "E")],
                  attributes=[Attribute("ref", "Označení", "", True)])


def test_open_add_port_and_save_builtin_as_copy(lib, boxes):
    d = _dialog(lib, BUILTIN)
    n = len(lib.get_symbol(BUILTIN).ports)
    assert d.ports_table.rowCount() == n and d.original.id == BUILTIN and d.saved_symbol is None
    assert d.attrs_table.rowCount() == len(d.symbol.attributes)
    p = d.add_port("X9", 3.1, -4.9, "S")
    assert p is not None and (p.x, p.y) == (pytest.approx(2.5), pytest.approx(-5.0))
    assert d.ports_table.rowCount() == n + 1
    assert len(lib.get_symbol(BUILTIN).ports) == n            # originál (cache knihovny) se nemění
    assert d.save() is True
    assert d.saved_symbol is not None and d.saved_symbol.id != BUILTIN
    saved = lib.get_symbol(d.saved_symbol.id)
    assert "X9" in [q.name for q in saved.ports] and not lib.is_builtin(saved.id)
    assert [q.name for q in lib.get_symbol(BUILTIN).ports] == ["1", "2"] and lib.is_builtin(BUILTIN)
    assert boxes.warning == [] and boxes.question == []       # vestavěná značka: bez otázky na ubyté porty


def test_add_port_generates_free_name(lib, boxes):
    d = _dialog(lib, BUILTIN)
    p1, p2 = d.add_port(), d.add_port()
    assert p1 is not None and p2 is not None and p1.name and p1.name != p2.name
    assert len({q.name for q in d.symbol.ports}) == len(d.symbol.ports)


def test_duplicate_port_name_warns(lib, boxes):
    d = _dialog(lib, BUILTIN)
    n = d.ports_table.rowCount()
    assert d.add_port("1", 0, 0, "E") is None
    assert len(boxes.warning) == 1
    assert d.ports_table.rowCount() == n and len(d.symbol.ports) == n


def test_user_symbol_remove_port_asks_no_then_yes(lib, boxes):
    lib.put_symbol(_user_symbol())
    d = _dialog(lib, "user.test")
    d.ports_table.selectRow(0)
    d.remove_selected_port()
    assert [p.name for p in d.symbol.ports] == ["B"] and d.ports_table.rowCount() == 1
    boxes.answer = NO
    assert d.save() is False
    assert len(boxes.question) == 1 and d.saved_symbol is None
    assert [p.name for p in lib.get_symbol("user.test").ports] == ["A", "B"]
    boxes.answer = YES
    assert d.save() is True
    assert len(boxes.question) == 2 and d.saved_symbol.id == "user.test"
    assert [p.name for p in lib.get_symbol("user.test").ports] == ["B"]


def test_save_invalid_warns_and_keeps_open(lib, boxes):
    d = _dialog(lib, BUILTIN)
    d.symbol.attributes = [a for a in d.symbol.attributes if a.key != "ref"]
    assert d.save() is False
    assert len(boxes.warning) == 1 and d.saved_symbol is None
    assert not lib.has_symbol(f"{BUILTIN}_2")


def test_main_window_has_edit_symbol_action_and_opens_dialog(lib, monkeypatch, boxes):
    from envocad.ui import symbol_editor
    from envocad.ui.main_window import MainWindow
    w = MainWindow(LibraryStore(), Project())
    created = []
    orig_init = symbol_editor.SymbolEditorDialog.__init__

    def spy(self, library, symbol_id, parent=None):
        created.append(symbol_id)
        orig_init(self, library, symbol_id, parent)
    monkeypatch.setattr(symbol_editor.SymbolEditorDialog, "__init__", spy)
    monkeypatch.setattr(symbol_editor.SymbolEditorDialog, "exec", lambda self: 0)
    menu = next(a.menu() for a in w.menuBar().actions() if a.menu() and "Knihovna" in a.text().replace("&", ""))
    acts = [a for a in menu.actions() if "Upravit značku" in a.text()]
    assert len(acts) == 1
    w.edit_symbol(BUILTIN)
    assert created == [BUILTIN]
    w._autosave_timer.stop()


def _menu_action(w):
    menu = next(a.menu() for a in w.menuBar().actions() if a.menu() and "Knihovna" in a.text().replace("&", ""))
    return next(a for a in menu.actions() if "Upravit značku" in a.text())


def _spy_dialog(monkeypatch):
    from envocad.ui import symbol_editor
    created = []
    orig_init = symbol_editor.SymbolEditorDialog.__init__

    def spy(self, library, symbol_id, parent=None):
        created.append(symbol_id)
        orig_init(self, library, symbol_id, parent)
    monkeypatch.setattr(symbol_editor.SymbolEditorDialog, "__init__", spy)
    monkeypatch.setattr(symbol_editor.SymbolEditorDialog, "exec", lambda self: 0)
    return created


def _select_symbol_in_tree(w, sid):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    it = QTreeWidgetItemIterator(w.lib_panel.tree)
    while it.value():
        if it.value().data(0, Qt.UserRole) == sid:
            w.lib_panel.tree.setCurrentItem(it.value())
            return
        it += 1
    raise AssertionError(f"{sid} není ve stromu")


def test_menu_action_opens_editor_for_selected_symbol(monkeypatch):
    from envocad.ui.main_window import MainWindow
    w = MainWindow(LibraryStore(), Project())
    infos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: infos.append(a))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: infos.append(a))
    created = _spy_dialog(monkeypatch)
    _select_symbol_in_tree(w, BUILTIN)
    _menu_action(w).trigger()
    assert created == [BUILTIN] and infos == []
    w._autosave_timer.stop()


def test_menu_action_without_selection_informs(monkeypatch):
    from envocad.ui.main_window import MainWindow
    w = MainWindow(LibraryStore(), Project())
    infos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: infos.append(a))
    created = _spy_dialog(monkeypatch)
    w.lib_panel.tree.setCurrentItem(None)
    _menu_action(w).trigger()
    assert created == [] and len(infos) == 1
    w._autosave_timer.stop()


def test_edit_symbol_same_id_rebuilds_open_scene(monkeypatch, boxes):
    from envocad.ui import symbol_editor
    from envocad.ui.main_window import MainWindow
    st = LibraryStore()
    st.put_symbol(_user_symbol())
    w = MainWindow(st, Project())
    rebuilt = []
    sc = w._unwrap(w.tabs.widget(0)).scene()
    monkeypatch.setattr(type(sc), "rebuild", lambda self, *a, **k: rebuilt.append(self))

    def fake_exec(self):
        self.add_port("Z", 10, 0)
        self.save()
        return 1
    monkeypatch.setattr(symbol_editor.SymbolEditorDialog, "exec", fake_exec)
    w.edit_symbol("user.test")
    assert "Z" in [p.name for p in st.get_symbol("user.test").ports]
    assert sc in rebuilt
    w._autosave_timer.stop()


# ---- úpravy v tabulkách ------------------------------------------------------------------------------------------------
def test_cell_x_rounds_and_accepts_decimal_comma(lib, boxes):
    lib.put_symbol(_user_symbol())
    d = _dialog(lib, "user.test")
    d.ports_table.item(1, 1).setText("3,6")
    assert d.symbol.port("B").x == pytest.approx(2.5)
    assert d.ports_table.item(1, 1).text() == "2.5" and boxes.warning == []


def test_cell_rename_port_then_delete(lib, boxes):
    lib.put_symbol(_user_symbol())
    d = _dialog(lib, "user.test")
    d.ports_table.item(0, 0).setText("L")
    assert [p.name for p in d.symbol.ports] == ["L", "B"] and boxes.warning == []
    d.ports_table.selectRow(1)
    d.remove_selected_port()
    assert [p.name for p in d.symbol.ports] == ["L"]
    d.ports_table.selectRow(0)
    d.remove_selected_port()
    assert d.symbol.ports == []


def test_cell_rename_duplicate_warns_and_reverts(lib, boxes):
    lib.put_symbol(_user_symbol())
    d = _dialog(lib, "user.test")
    d.ports_table.item(0, 0).setText("B")
    assert len(boxes.warning) == 1
    assert d.ports_table.item(0, 0).text() == "A" and [p.name for p in d.symbol.ports] == ["A", "B"]


@pytest.mark.parametrize("bad", ["abc", "nan", "inf", "-inf", "1e400"])
def test_cell_invalid_number_warns_and_reverts(lib, boxes, bad):
    lib.put_symbol(_user_symbol())
    d = _dialog(lib, "user.test")
    seen = []
    from PySide6.QtWidgets import QMessageBox as QMB

    def warn(*a, **k):
        seen.append(d.ports_table.item(0, 1).text())       # pod hláškou už není vidět neplatný text
        boxes.warning.append(a)
        return QMB.StandardButton.Ok
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    mp.setattr(QMB, "warning", warn)
    try:
        d.ports_table.item(0, 1).setText(bad)
    finally:
        mp.undo()
    assert len(boxes.warning) == 1 and seen == ["0"]
    assert d.ports_table.item(0, 1).text() == "0" and d.symbol.port("A").x == 0


def test_cell_direction_combo_changes_model(lib, boxes):
    lib.put_symbol(_user_symbol())
    d = _dialog(lib, "user.test")
    d.ports_table.cellWidget(0, 3).setCurrentText("N")
    assert d.symbol.port("A").dir == "N"


def test_cell_attribute_edits(lib, boxes):
    from PySide6.QtCore import Qt
    lib.put_symbol(_user_symbol())
    d = _dialog(lib, "user.test")
    keys = [a.key for a in d.symbol.attributes]
    r = keys.index("ref")
    d.attrs_table.item(r, 1).setText("Označ.")
    d.attrs_table.item(r, 2).setText("Q1")
    d.attrs_table.item(r, 3).setCheckState(Qt.Unchecked)
    a = next(x for x in d.symbol.attributes if x.key == "ref")
    assert (a.label, a.default, a.show) == ("Označ.", "Q1", False)
    d.attrs_table.item(r, 3).setCheckState(Qt.Checked)
    assert next(x for x in d.symbol.attributes if x.key == "ref").show is True


def test_add_existing_attribute_key_warns(lib, boxes, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    lib.put_symbol(_user_symbol())
    d = _dialog(lib, "user.test")
    n = len(d.symbol.attributes)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("ref", True))
    d.add_attribute()
    assert len(boxes.warning) == 1 and "ref" in boxes.warning[0][2]
    assert len(d.symbol.attributes) == n


def test_file_symbol_dialog_saves_copy_and_asks_nothing_on_lost_ports(boxes):
    from envocad.library.store import user_library_dir
    f = user_library_dir() / "firma" / "x.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    _user_symbol("firma.x").to_json(f)
    st = LibraryStore()
    d = _dialog(st, "firma.x")
    from PySide6.QtWidgets import QLabel
    assert d.findChild(QLabel, "builtin_info") is not None
    d.ports_table.selectRow(0)
    d.remove_selected_port()
    assert d.save() is True
    assert boxes.question == [] and d.saved_symbol.id == "firma.x_2"
    assert [p.name for p in st.get_symbol("firma.x").ports] == ["A", "B"]
    st.close()
