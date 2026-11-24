"""GUI import z PVsyst (.PAN/.OND) – `MainWindow.import_pvsyst` (issue #86). Offscreen; knihovna v tmp_path,
`ENVOCAD_HOME` izoluje `tests/conftest.py`."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from envocad.library import pvsyst_import as pi
from envocad.library.store import LibraryStore, user_library_dir
from envocad.model.project import Project
from envocad.ui.main_window import MainWindow

DATA = Path(__file__).parent / "data" / "pvsyst"
MENU_TEXT = "Importovat z PVsyst (.PAN/.OND)…"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def lib(tmp_path):
    return LibraryStore(tmp_path / "lib.db", load_builtin=False)


@pytest.fixture
def msgs(monkeypatch):
    seen: list[tuple[str, str]] = []
    for kind in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(
            lambda *a, kind=kind, **k: seen.append((kind, a[2])) or QMessageBox.Ok))
    return seen


@pytest.fixture
def win(app, lib):
    w = MainWindow(library=lib, project=Project())
    w.show()
    w.undo.setClean()
    yield w
    w.undo.setClean()
    w.close()


def _pick(monkeypatch, path):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), "")))


def _components_ids(lib):
    return {c.id for c in lib.components()}


def test_menu_has_pvsyst_import_action(win):
    texts = [a.text().replace("&", "") for a in win.findChildren(QAction)]
    assert MENU_TEXT in texts


@pytest.mark.parametrize("name,cat,pn", [("smysleny_modul.PAN", "pv_module", "SD-430M"),
                                         ("smysleny_stridac.OND", "inverter", "SD-10K-T2")])
def test_import_pvsyst_adds_component(win, lib, msgs, monkeypatch, name, cat, pn):
    before = _components_ids(lib)
    _pick(monkeypatch, DATA / name)
    win.import_pvsyst()
    new = _components_ids(lib) - before
    assert len(new) == 1
    c = lib.component(next(iter(new)))
    assert c is not None and c.category == cat and c.part_number == pn and c.source == "user"
    assert not [m for m in msgs if m[0] == "warning"]
    assert (user_library_dir() / "pvsyst" / f"pvsyst-{c.id}.csv").is_file()


def test_import_pvsyst_broken_file_warns_without_exception(win, lib, msgs, monkeypatch, tmp_path):
    bad = tmp_path / "rozbity.PAN"
    bad.write_bytes(b"\x00\x01\x02 neni to PVsyst")
    before = _components_ids(lib)
    _pick(monkeypatch, bad)
    win.import_pvsyst()
    assert [m for m in msgs if m[0] == "warning"]
    assert _components_ids(lib) == before


def test_import_pvsyst_cancel_does_nothing(win, lib, msgs, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    win.import_pvsyst()
    assert msgs == [] and _components_ids(lib) == set()


def _existing(lib, tmp_path):
    """Do knihovny vloží artikl se stejným id jako ukázkový PAN, ale s jiným výrobcem (kurátorovaný řádek)."""
    comp, _ = pi.import_pvsyst(DATA / "smysleny_modul.PAN")
    comp.manufacturer = "Kurátor"
    csv_path = tmp_path / "kurator.csv"
    pi.write_components_csv([comp], csv_path)
    assert lib.import_components_csv_v2(csv_path) == 1
    return comp.id


def _answer(monkeypatch, answer):
    asked: list[str] = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or answer))
    return asked


def test_import_pvsyst_existing_article_declined_keeps_library(win, lib, msgs, monkeypatch, tmp_path):
    cid = _existing(lib, tmp_path)
    asked = _answer(monkeypatch, QMessageBox.No)
    _pick(monkeypatch, DATA / "smysleny_modul.PAN")
    win.import_pvsyst()
    assert len(asked) == 1 and cid in asked[0] and "Kurátor" in asked[0]
    assert lib.component(cid).manufacturer == "Kurátor"
    assert not list((user_library_dir() / "pvsyst").glob("*.csv"))
    assert not [m for m in msgs if m[0] == "information"]


def test_import_pvsyst_existing_article_accepted_overwrites(win, lib, msgs, monkeypatch, tmp_path):
    cid = _existing(lib, tmp_path)
    asked = _answer(monkeypatch, QMessageBox.Yes)
    _pick(monkeypatch, DATA / "smysleny_modul.PAN")
    win.import_pvsyst()
    assert len(asked) == 1
    assert lib.component(cid).manufacturer == "Solární Dílna Pribram"
    assert (user_library_dir() / "pvsyst" / f"pvsyst-{cid}.csv").is_file()


def test_import_pvsyst_save_failure_warns(win, lib, msgs, monkeypatch):
    monkeypatch.setattr(LibraryStore, "import_components_csv_v2", lambda self, path: 0)
    _pick(monkeypatch, DATA / "smysleny_modul.PAN")
    win.import_pvsyst()
    assert [m for m in msgs if m[0] == "warning" and "nepodařilo uložit" in m[1]]
    assert not [m for m in msgs if m[0] == "information"]
