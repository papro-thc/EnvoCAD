"""GUI: Knihovna → Import artiklů z BMEcat (`MainWindow.import_bmecat`, issue #84). Offscreen.

Izolace: `conftest._isolated_home` přesměruje `ENVOCAD_HOME` do tmp, takže `user_library_dir()` neleží v `~/.envocad`."""
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from envocad.library.store import LibraryStore, user_library_dir
from envocad.model.project import Project
from envocad.ui.main_window import MainWindow

XML_12 = Path(__file__).parent / "data" / "bmecat" / "smysleny_1_2.xml"


@pytest.fixture
def lib(tmp_path):
    s = LibraryStore(tmp_path / "lib.db", load_builtin=False)
    yield s
    s.close()


@pytest.fixture
def msgs(monkeypatch):
    seen: list[tuple[str, str]] = []
    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(
            lambda *a, kind=kind, **k: seen.append((kind, a[2])) or QMessageBox.Ok))
    return seen


def _pick(monkeypatch, path):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), "")))


@pytest.fixture
def window(lib):
    w = MainWindow(library=lib, project=Project())
    w.show()
    w.undo.setClean()
    yield w
    w.undo.setClean()
    w.close()


def test_import_bmecat_adds_articles_to_library(window, lib, msgs, monkeypatch):
    _pick(monkeypatch, XML_12)
    window.import_bmecat()
    assert {c.part_number for c in lib.components()} >= {"FK-MCB-B16-3", "FK-TERM-4"}
    mcb = next(c for c in lib.components() if c.part_number == "FK-MCB-B16-3")
    assert mcb.params["etim_class"] == "EC000042"
    assert msgs and msgs[-1][0] == "information"
    assert list(user_library_dir().rglob("smysleny_1_2.csv"))          # CSV v izolované uživatelské knihovně


def test_import_bmecat_cancel_does_nothing(window, lib, msgs, monkeypatch):
    _pick(monkeypatch, "")
    window.import_bmecat()
    assert lib.components() == [] and msgs == []


def test_import_bmecat_bad_file_shows_czech_warning(window, lib, msgs, tmp_path, monkeypatch):
    bad = tmp_path / "vadny.xml"
    bad.write_text("<BMECAT><ARTICLE>", encoding="utf-8")
    _pick(monkeypatch, bad)
    window.import_bmecat()
    assert msgs and msgs[-1][0] == "warning" and str(bad) in msgs[-1][1]
    assert lib.components() == []
