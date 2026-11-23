"""GUI export štítků do CSV (issue #134): `MainWindow.export_labels_csv` jen vybere soubor a zavolá
`envocad.export.labels_csv.write_labels_csv`; výstup je bajtově shodný s tou funkcí."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog
from test_labels_csv import EXPECTED, make_project

from envocad.library.store import LibraryStore
from envocad.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, tmp_path):
    w = MainWindow(library=LibraryStore(tmp_path / "lib.db"), project=make_project())
    w.show()
    w.undo.setClean()
    yield w
    w.undo.setClean()
    w.close()


def _dialog(monkeypatch, result: str):
    calls = []

    def fake(*a, **kw):
        calls.append(a)
        return result, ""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake))
    return calls


def test_gui_export_writes_expected_bytes(win, tmp_path, monkeypatch):
    out = tmp_path / "stitky.csv"
    _dialog(monkeypatch, str(out))
    win.export_labels_csv()
    assert out.read_bytes() == EXPECTED
    assert "3 štítků" in win.statusBar().currentMessage()


def test_gui_export_identical_to_write_labels_csv(win, tmp_path, monkeypatch):
    from envocad.export.labels_csv import write_labels_csv
    ref = tmp_path / "ref.csv"
    write_labels_csv(win.project, win.library, ref)
    out = tmp_path / "gui.csv"
    _dialog(monkeypatch, str(out))
    win.export_labels_csv()
    assert out.read_bytes() == ref.read_bytes()


def test_gui_calls_write_labels_csv(win, tmp_path, monkeypatch):
    import envocad.export.labels_csv as mod
    seen = []

    def fake(project, lib, path):
        seen.append((project, lib, str(path)))
        return 7
    monkeypatch.setattr(mod, "write_labels_csv", fake)
    out = tmp_path / "x.csv"
    _dialog(monkeypatch, str(out))
    win.export_labels_csv()
    assert seen == [(win.project, win.library, str(out))]
    assert "7 štítků" in win.statusBar().currentMessage()


def test_gui_cancelled_dialog_writes_nothing(win, tmp_path, monkeypatch):
    import envocad.export.labels_csv as mod
    called = []
    monkeypatch.setattr(mod, "write_labels_csv", lambda *a, **k: called.append(a) or 0)
    _dialog(monkeypatch, "")
    win.export_labels_csv()
    assert not called
    assert not [f for f in tmp_path.iterdir() if f.suffix == ".csv"]
