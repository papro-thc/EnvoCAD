"""GUI archivu projektu `.ecpz` (issue #75): menu Soubor, export, otevření s importem do knihovny.
Dialogy jsou monkeypatchnuté, jen smyšlená data."""
import os
import zipfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from envocad.library.archive import pack_project
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project
from envocad.model.symbol import Symbol
from envocad.ui import main_window as mw
from envocad.ui.main_window import MainWindow

MAKER = "Testovací s.r.o."


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_modal(monkeypatch):
    """Žádný modální dialog nesmí test zablokovat; zprávy se zachytí."""
    msgs = []
    for name in ("information", "critical", "warning"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, _n=name, **k: msgs.append((_n, a[1:])) or 0))
    return msgs


def _sym(name="Testovací značka"):
    return Symbol("test.znacka", name, category="Test", iec_ref="F")


def _fill(store, sym_name="Testovací značka", comp_name="Testovací artikl"):
    store.put_symbol(_sym(sym_name))
    store.put_component("test.artikl", MAKER, "TA-1", comp_name, "test.znacka", {"in_": "16"}, 12.5, None)


def _project():
    p = Project(name="Archivní")
    p.sheets[0].elements.append(Element("test.znacka", 30, 30, attrs={"ref": "F1"}, component_id="test.artikl"))
    return p


@pytest.fixture
def archive(tmp_path, app):
    src = LibraryStore(tmp_path / "src.db")
    _fill(src)
    path = tmp_path / "a.ecpz"
    pack_project(_project(), src, path)
    return path


def _window(tmp_path, name="dst.db"):
    w = MainWindow(library=LibraryStore(tmp_path / name), project=Project(name="Původní"))
    return w


def test_menu_actions(app, tmp_path):
    w = _window(tmp_path)
    texts = {a.text() for a in w.findChildren(type(w.menuBar().actions()[0])) if a.text()}
    assert {"Archiv projektu…", "Otevřít archiv projektu…"} <= texts
    w.close()


def test_export_creates_archive(app, tmp_path, monkeypatch, no_modal):
    lib = LibraryStore(tmp_path / "src.db")
    _fill(lib)
    w = MainWindow(library=lib, project=_project())
    target = tmp_path / "out"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    assert w.export_archive()
    out = tmp_path / "out.ecpz"
    assert zipfile.is_zipfile(out)
    kind, args = no_modal[-1]
    assert kind == "information" and "1 značek, 1 artiklů" in args[1] and "licencovaná" in args[1]
    w.close()


def test_export_cancel_and_error(app, tmp_path, monkeypatch, no_modal):
    w = _window(tmp_path)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    assert not w.export_archive()
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "neni" / "x.ecpz"), "")))
    assert not w.export_archive()
    assert no_modal[-1][0] == "critical"
    w.close()


def test_open_imports_missing(app, tmp_path, archive, monkeypatch):
    w = _window(tmp_path)
    asked = []
    monkeypatch.setattr(MainWindow, "_ask_archive_import", lambda self, r: asked.append(r) or "import")
    assert w._open_archive_file(archive)
    assert asked[0].new_symbols == ["test.znacka"] and asked[0].new_components == ["test.artikl"]
    assert w.library.has_symbol("test.znacka") and w.library.get_component("test.artikl")
    assert w.project.name == "Archivní" and w.project.path is None
    w.close()


def _conflict_window(tmp_path):
    w = _window(tmp_path)
    _fill(w.library, "Jiná značka", "Jiný artikl")
    return w


def test_conflict_keep(app, tmp_path, archive, monkeypatch):
    w = _conflict_window(tmp_path)
    monkeypatch.setattr(MainWindow, "_ask_archive_import", lambda self, r: "keep" if r.conflicts else None)
    assert w._open_archive_file(archive)
    assert w.library.get_symbol("test.znacka").name == "Jiná značka"
    assert w.library.get_component("test.artikl")["name"] == "Jiný artikl"
    assert w.project.name == "Archivní"
    w.close()


def test_conflict_overwrite(app, tmp_path, archive, monkeypatch):
    w = _conflict_window(tmp_path)
    monkeypatch.setattr(MainWindow, "_ask_archive_import", lambda self, r: "overwrite")
    assert w._open_archive_file(archive)
    assert w.library.get_symbol("test.znacka").name == "Testovací značka"
    assert w.library.get_component("test.artikl")["name"] == "Testovací artikl"
    w.close()


def test_conflict_cancel(app, tmp_path, archive, monkeypatch):
    w = _conflict_window(tmp_path)
    monkeypatch.setattr(MainWindow, "_ask_archive_import", lambda self, r: None)
    before = w.project
    assert not w._open_archive_file(archive)
    assert w.project is before and w.project.name == "Původní"
    assert w.library.get_symbol("test.znacka").name == "Jiná značka"
    assert w.library.get_component("test.artikl")["name"] == "Jiný artikl"
    w.close()


def test_broken_file(app, tmp_path, monkeypatch, no_modal):
    w = _window(tmp_path)
    bad = tmp_path / "bad.ecpz"
    bad.write_bytes(b"to neni zip")
    monkeypatch.setattr(MainWindow, "_ask_archive_import",
                        lambda self, r: pytest.fail("nemá se ptát"))
    before = w.project
    assert not w._open_archive_file(bad)
    assert w.project is before
    assert no_modal[-1][0] == "critical"
    w.close()


def test_open_archive_dialog_flow(app, tmp_path, archive, monkeypatch):
    w = _window(tmp_path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(archive), "")))
    monkeypatch.setattr(MainWindow, "_ask_archive_import", lambda self, r: "import")
    assert w.open_archive()
    assert w.project.name == "Archivní"
    w.close()


def test_filter_constant():
    assert "*.ecpz" in mw.ARCHIVE_FILTER
