"""Duplikování listu v GUI (issue #71): `DuplicateSheetCommand` (undo/redo), `MainWindow.duplicate_sheet`, akce v menu
List a dialog hromadného přepsání označení `SheetRefsDialog` (`MainWindow.edit_sheet_refs`)."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Sheet, Wire, WireEnd
from envocad.ui import commands
from envocad.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def lib(tmp_path):
    return LibraryStore(tmp_path / "lib.db")


def _state(p: Project) -> str:
    return json.dumps(p.to_dict(), sort_keys=True, ensure_ascii=False)


def _project() -> Project:
    p = Project(name="A")
    s = p.sheets[0]
    t = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    f = Element("fve.breaker_mcb", 100, 150, attrs={"ref": "F1"})
    s.elements += [t, f]
    s.wires.append(Wire(WireEnd(t.id, "AC"), WireEnd(f.id, "1"), attrs={"ref": "W1"}))
    p.sheets.append(Sheet(name="Druhý"))
    return p


def _switchboard_project() -> tuple[Project, Sheet, Element]:
    p = Project(name="B")
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "RDC1", "desc": "AC rozvaděč"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    sb.elements.append(Element("fve.breaker_mcb", 50, 100, attrs={"ref": "F1"}))
    return p, sb, blk


def _win(lib, p: Project) -> MainWindow:
    w = MainWindow(library=lib, project=p)
    w.show()
    w.undo.setClean()
    return w


def _done(w: MainWindow) -> None:
    w.undo.setClean()
    w.close()


def test_prikaz_prida_list_za_original_undo_redo(app, lib):
    p = _project()
    s0 = p.sheets[0]
    w = _win(lib, p)
    before = _state(p)
    cmd = commands.DuplicateSheetCommand(p, s0, lib)
    w.undo.push(cmd)
    c = cmd.result.sheet
    assert p.sheets[1] is c and len(p.sheets) == 3
    after = _state(p)
    w.undo.undo()
    assert _state(p) == before and c not in p.sheets
    w.undo.redo()
    assert _state(p) == after and p.sheets[1].id == c.id           # stejná id po redo
    _done(w)


def test_prikaz_listu_rozvadece_undo_odebere_i_blok_a_strukturu(app, lib):
    p, sb, blk = _switchboard_project()
    w = _win(lib, p)
    before = _state(p)
    cmd = commands.DuplicateSheetCommand(p, sb, lib)
    w.undo.push(cmd)
    res = cmd.result
    assert res.block is not None and res.block in p.sheets[0].elements
    assert any(x.code == "RDC2" for x in p.structures)
    after = _state(p)
    w.undo.undo()
    assert _state(p) == before
    assert all(e.id != res.block.id for e in p.sheets[0].elements) and not any(x.code == "RDC2" for x in p.structures)
    assert p.switchboard_sheet(blk.id) is sb
    w.undo.redo()
    assert _state(p) == after and p.switchboard_sheet(res.block.id).id == res.sheet.id
    _done(w)


def test_duplicate_sheet_okna_otevre_kopii_jednim_krokem_undo(app, lib):
    p = _project()
    w = _win(lib, p)
    w.open_sheet(p.sheets[0])
    n = w.undo.count()
    c = w.duplicate_sheet()
    assert c is p.sheets[1] and c is w.current_sheet
    assert w.undo.count() == n + 1 and not w.undo.isClean()
    w.undo.undo()
    assert len(p.sheets) == 2 and w.undo.isClean()
    _done(w)


def test_duplicate_sheet_zadaneho_listu(app, lib):
    p = _project()
    w = _win(lib, p)
    w.open_sheet(p.sheets[0])
    c = w.duplicate_sheet(p.sheets[1])
    assert p.sheets.index(c) == 2 and c.name == "Druhý – kopie"
    _done(w)


def test_menu_list_ma_akci_duplikovat_list(app, lib):
    w = _win(lib, _project())
    menu = next(a.menu() for a in w.menuBar().actions() if a.text().replace("&", "") == "List")
    assert "Duplikovat list" in [a.text().replace("&", "") for a in menu.actions()]
    _done(w)


def _two_interrupts() -> tuple[Project, Sheet, Element, Element]:
    p = Project(name="C")
    s = p.sheets[0]
    a, b = Element("fve.interrupt", 50, 100, attrs={"ref": ""}), Element("fve.interrupt", 80, 100, attrs={"ref": ""})
    s.elements += [a, b]
    return p, s, a, b


def test_dialog_prepisu_oznaceni_vraci_zmeny(app):
    from envocad.ui.sheet_refs_dialog import SheetRefsDialog
    p, s, a, b = _two_interrupts()
    dlg = SheetRefsDialog(p, s, None)
    dlg.set_ref(a.id, "L1")
    dlg.set_ref(b.id, "L2")
    ch = dlg.changes()
    assert {(c.kind, c.target_id, c.key, c.old, c.new) for c in ch} == \
           {("element", a.id, "ref", "", "L1"), ("element", b.id, "ref", "", "L2")}


def test_edit_sheet_refs_je_jeden_krok_undo(app, lib, monkeypatch):
    from envocad.ui.sheet_refs_dialog import SheetRefsDialog
    p, s, a, b = _two_interrupts()
    w = _win(lib, p)

    def fake_exec(self):
        self.set_ref(a.id, "L1")
        self.set_ref(b.id, "L2")
        return QDialog.Accepted
    monkeypatch.setattr(SheetRefsDialog, "exec", fake_exec)
    n = w.undo.count()
    w.edit_sheet_refs(s)
    assert (a.ref, b.ref) == ("L1", "L2") and w.undo.count() == n + 1
    w.undo.undo()
    assert (a.ref, b.ref) == ("", "")
    _done(w)
