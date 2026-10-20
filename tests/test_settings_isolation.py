"""Testy nepíšou do skutečných QSettings uživatele (autouse fixture `_isolated_qsettings` v conftest)."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_qsettings_go_to_tmp(app, _isolated_qsettings):
    from PySide6.QtCore import QSettings

    from envocad.ui import theme
    from envocad.ui.main_window import MainWindow
    tmp = Path(_isolated_qsettings).resolve()
    home = Path(os.environ["ENVOCAD_HOME"]).resolve()
    user = (Path.home() / ".config" / "ENVO" / "EnvoCAD.conf").resolve()
    # nastavení GUI jde přes `theme.app_settings()` → `<ENVOCAD_HOME>/gui.ini` (i na Windows, kde by holé
    # QSettings("ENVO", "EnvoCAD") psalo do registru a setPath z conftestu ho nepřesměruje)
    for s in (theme.app_settings(), MainWindow._settings()):
        f = Path(s.fileName()).resolve()
        assert f.is_relative_to(home) and f != user
    if os.name != "nt":
        assert Path(QSettings("ENVO", "EnvoCAD").fileName()).resolve().is_relative_to(tmp)
    s = MainWindow._settings()
    s.setValue("files/recent", ["/x/test.ecp"])
    s.sync()
    assert "test.ecp" in Path(s.fileName()).read_text()


def test_each_test_starts_with_empty_settings(app):

    from envocad.ui import theme
    s = theme.app_settings()
    assert s.value("files/recent", None) is None          # zápis z předchozího testu sem neprosákne
    assert s.value("ui/dark", None) is None
    was_dark = theme.is_dark()
    theme.apply(not was_dark, app)                          # zapisuje ui/dark – jen do tmp
    try:
        assert str(theme.app_settings().value("ui/dark")).lower() == str(not was_dark).lower()
    finally:
        theme.apply(was_dark, app)


def test_main_window_starts_with_empty_recent_and_notes_off(app):
    from envocad.library.store import LibraryStore
    from envocad.model.project import Project
    from envocad.ui.main_window import MainWindow
    w = MainWindow(LibraryStore(), Project(name="S"))
    try:
        assert w._recent() == []
        assert not w._notes_visible_setting() and not w._export_notes()
    finally:
        w.close()
