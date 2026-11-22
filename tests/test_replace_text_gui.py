"""Najít a nahradit z GUI (issue #74): `MainWindow.apply_replace` = jeden krok undo."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Sheet, SheetText
from envocad.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def lib(tmp_path):
    return LibraryStore(tmp_path / "lib.db")


def _project():
    p = Project(name="Replace GUI")
    s1 = p.sheets[0]
    s1.elements.append(Element("fve.hds", 30, 150, attrs={"ref": "Q1", "desc": "hlavní kabel"}))
    s1.texts.append(SheetText(10, 10, "kabel A"))
    s2 = Sheet(name="Druhý")
    s2.elements.append(Element("fve.hds", 30, 150, attrs={"ref": "Q2", "desc": "kabel kabel"}))
    s2.texts.append(SheetText(10, 10, "poznámka kabel"))
    p.sheets.append(s2)
    return p


def _state(p: Project) -> str:
    return json.dumps(p.to_dict(), sort_keys=True, ensure_ascii=False)


@pytest.fixture
def win(app, lib):
    p = _project()
    w = MainWindow(library=lib, project=p)
    w.show()
    w.undo.setClean()
    yield w
    w.undo.setClean()
    w.close()


def test_action_present(win):
    assert "replace" in win.actions
    assert "nahradit" in win.actions["replace"].text()


def test_replace_is_one_undo_step(win):
    p = win.project
    before = _state(p)
    n0 = win.undo.count()
    n = win.apply_replace("kabel", "vodič")
    assert n == 5
    assert win.undo.count() == n0 + 1
    after = _state(p)
    assert after != before
    assert p.sheets[0].texts[0].text == "vodič A"
    assert p.sheets[1].elements[0].attrs["desc"] == "vodič vodič"
    assert p.sheets[0].elements[0].attrs["ref"] == "Q1"
    win.undo.undo()
    assert _state(p) == before
    win.undo.redo()
    assert _state(p) == after


def test_nothing_found_pushes_nothing(win):
    n0 = win.undo.count()
    before = _state(win.project)
    assert win.apply_replace("neexistuje", "x") == 0
    assert win.undo.count() == n0
    assert _state(win.project) == before


def test_match_case_option(win):
    assert win.apply_replace("KABEL", "x", match_case=True) == 0
    assert win.apply_replace("KABEL", "x", match_case=False) == 5


def test_sheet_scope_only_current_sheet(win):
    s1, s2 = win.project.sheets
    assert win.current_sheet is s1
    before2 = json.dumps(s2.to_dict(), sort_keys=True)
    n0 = win.undo.count()
    assert win.apply_replace("kabel", "vodič", scope="sheet") == 2
    assert win.undo.count() == n0 + 1
    assert s1.texts[0].text == "vodič A"
    assert json.dumps(s2.to_dict(), sort_keys=True) == before2
    win.undo.undo()
    assert s1.texts[0].text == "kabel A"
