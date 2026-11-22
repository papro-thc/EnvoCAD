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


def _user_symbol():
    return Symbol(id="user.test", name="Test", category="Uživatelské",
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
