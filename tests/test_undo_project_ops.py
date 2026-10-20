"""Operace nad projektem z GUI jdou přes undo (CLAUDE.md): smazání a přidání listu, list rozvaděče, šablona,
vlastnosti projektu, skříň (dialog i panel), nový projekt. Každá změna → undo vrátí `Project.to_dict` přesně →
redo zopakuje; čistý stav a titulek („*“) odpovídají."""
import ast
import copy
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

from envocad.library.store import LibraryStore
from envocad.library.templates import apply_template
from envocad.model.feed import is_feed_in, is_feed_out
from envocad.model.project import Element, Layout, Project, Sheet, Wire, WireEnd
from envocad.ui import commands
from envocad.ui.main_window import MainWindow

SPEC = {"name": "FVE Test", "module": {"p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9},
        "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000,
                       "i_mppt_max": 30, "strings": [20, 20, 18]}], "ac": {"breaker_in": 50, "main_in": 125}}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def lib(tmp_path):
    return LibraryStore(tmp_path / "lib.db")


@pytest.fixture
def asked(monkeypatch):
    """Zaznamená otázky a hlášky; otázky odpoví podle `answers` (výchozí Yes)."""
    seen: list[tuple[str, str]] = []
    answers: list = []

    def question(*a, **k):
        seen.append(("question", a[2]))
        return answers.pop(0) if answers else QMessageBox.Yes
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    for kind in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind,
                            staticmethod(lambda *a, _k=kind, **kw: seen.append((_k, a[2])) or QMessageBox.Ok))
    return type("A", (), {"seen": seen, "answers": answers})


def _state(p: Project) -> str:
    return json.dumps(p.to_dict(), sort_keys=True, ensure_ascii=False)


def _jps_project() -> Project:
    p = Project(name="A")
    s = p.sheets[0]
    t = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    s.elements += [t, blk]
    s.wires.append(Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "1"), attrs={"ref": "W2"}))
    return p


def _win(lib, p: Project) -> MainWindow:
    w = MainWindow(library=lib, project=p)
    w.show()
    w.undo.setClean()
    return w


def _done(*wins) -> None:
    for w in wins:
        w.undo.setClean()
        w.close()


def _sheet_tabs(w: MainWindow, sheet: Sheet) -> list[str]:
    return sorted(w._kind_of(w._unwrap(w.tabs.widget(i))) for i in range(w.tabs.count())
                  if w._unwrap(w.tabs.widget(i)).scene().sheet is sheet)


def _roundtrip(w: MainWindow, before: str, steps: int = 1) -> str:
    """Po změně: neuloženo a „*“; undo → přesně původní stav, čisto; redo → stav po změně. Vrací stav po změně."""
    after = _state(w.project)
    assert after != before
    assert not w.undo.isClean() and "*" in w.windowTitle()
    for _ in range(steps):
        w.undo.undo()
    assert _state(w.project) == before
    assert w.undo.isClean() and "*" not in w.windowTitle()
    for _ in range(steps):
        w.undo.redo()
    assert _state(w.project) == after and not w.undo.isClean()
    return after


# ---- 1: smazání listu --------------------------------------------------------------------------------------------
def test_delete_sheet_undo_restores_sheet_and_tabs(app, lib, asked):
    p = _jps_project()
    s2 = Sheet(name="S2")
    p.sheets.append(s2)
    w = _win(lib, p)
    w.open_sheet(s2)
    w.open_sheet(s2, "multipole")
    w.tabs.setCurrentIndex(0)
    w.scene.set_attr(p.sheets[0].elements[0].id, False, "ref", "T9")   # dřívější historie musí zůstat
    w.undo.setClean()
    w.open_sheet(s2)
    before = _state(p)
    w.delete_sheet()
    assert s2 not in p.sheets and _sheet_tabs(w, s2) == []
    assert w.undo.count() == 2 and w.undo.undoText().startswith("Odstranit list")
    _roundtrip(w, before)
    assert s2 not in p.sheets and _sheet_tabs(w, s2) == []
    w.undo.undo()
    assert p.sheets[1] is s2 and _sheet_tabs(w, s2) == ["multipole", "schematic"]
    w.undo.undo()                                     # i předchozí krok jde vrátit
    assert p.sheets[0].elements[0].ref == "T1"
    _done(w)


def test_delete_switchboard_sheet_undo_restores_block_attr(app, lib, asked):
    p = _jps_project()
    blk = p.sheets[0].elements[1]
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    w = _win(lib, p)
    w.open_sheet(sb, "multipole")
    before = _state(p)
    w.delete_sheet()
    assert "sheet" not in blk.attrs and sb not in p.sheets
    jps = w._jps_scene(p.sheets[0])
    assert "X1" in jps.element_items[blk.id].symbol.orphan_ports
    _roundtrip(w, before)
    w.undo.undo()
    assert blk.attrs["sheet"] == sb.name and p.switchboard_sheet(blk.id) is sb
    assert not jps.element_items[blk.id].symbol.orphan_ports     # blok má zase porty podle listu
    assert _sheet_tabs(w, sb) == ["multipole", "schematic"]      # záložky otevřené před smazáním
    _done(w)


def test_delete_parent_sheet_undo_reattaches_switchboards(app, lib, asked):
    p = _jps_project()
    blk = p.sheets[0].elements[1]
    sb = p.create_switchboard_sheet(blk)
    w = _win(lib, p)
    w.tabs.setCurrentIndex(0)
    parent = p.sheets[0]
    before = _state(p)
    w.delete_sheet()
    assert p.sheets == [sb] and sb.parent_element_id is None and w.tabs.count() >= 1
    _roundtrip(w, before)
    w.undo.undo()
    assert p.sheets[0] is parent and sb.parent_element_id == blk.id
    _done(w)


def test_delete_parent_sheet_with_linked_feeds_undo_is_exact(app, lib, asked):
    """List JPS s blokem, jehož list rozvaděče má přívody navázané na vodič (šablona): smazání → undo vrátí
    `to_dict` přesně (přívod nedostane navíc prázdný klíč „to“), redo zopakuje."""
    p = _jps_project()
    blk = p.sheets[0].elements[1]
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    feed = next(e for e in sb.elements if is_feed_in(e) and e.attrs.get("wire_id"))
    attrs_before = dict(feed.attrs)
    assert "to" not in attrs_before
    w = _win(lib, p)
    w.tabs.setCurrentIndex(0)
    before = _state(p)
    w.delete_sheet()
    assert feed.attrs["wire_id"] == "" and "to" not in feed.attrs
    after = _roundtrip(w, before)
    w.undo.undo()
    assert feed.attrs == attrs_before and _state(p) == before
    w.undo.redo()
    assert _state(p) == after
    _done(w)


def test_sync_feed_links_does_not_add_empty_keys():
    from envocad.model.project import sync_feed_links
    p = _jps_project()
    blk = p.sheets[0].elements[1]
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    before = _state(p)
    parent = p.sheets.pop(0)
    assert sync_feed_links(p)
    assert all("to" not in e.attrs for e in sb.elements if is_feed_in(e))
    assert all("from" not in e.attrs for e in sb.elements if is_feed_out(e))
    p.sheets.insert(0, parent)
    sync_feed_links(p)
    assert _state(p) == before


# ---- 2: šablona -------------------------------------------------------------------------------------------------
def test_insert_template_single_undo_step(app, lib, asked, monkeypatch):
    p = _jps_project()
    blk = p.sheets[0].elements[1]
    sb = p.create_switchboard_sheet(blk)
    w = _win(lib, p)
    w.open_sheet(sb, "layout")
    w.open_sheet(sb, "schematic")
    w.tabs.setCurrentIndex(0)
    w.scene.set_attr(p.sheets[0].elements[0].id, False, "desc", "x")   # historie před šablonou zůstane
    w.undo.setClean()
    w.open_sheet(sb, "schematic")
    monkeypatch.setattr(MainWindow, "_ask_template", lambda self: ("ac_fve", {"distribution": "terminals"}))
    before = _state(p)
    w.insert_template()
    assert not [t for k, t in asked.seen if k == "question"]   # prázdný list → bez otázky
    assert sb.elements and sb.layout.placements and p.sheets[0].wires[0].b.port == "X1"
    assert w.undo.count() == 2 and w.undo.undoText().startswith("Šablona")
    _roundtrip(w, before)
    sc = w._jps_scene(sb)
    assert set(sc.element_items) == {e.id for e in sb.elements}
    w.undo.undo()
    assert sb.elements == [] and set(sc.element_items) == set() and p.sheets[0].wires[0].b.port == "1"
    w.undo.redo()
    # vložení do neprázdného listu se zeptá; Ne = nic se nezmění
    asked.answers.append(QMessageBox.No)
    n, state = w.undo.count(), _state(p)
    w.insert_template()
    assert "už obsahuje" in [t for k, t in asked.seen if k == "question"][-1]
    assert w.undo.count() == n and _state(p) == state
    _done(w)


# ---- 3: nové listy ------------------------------------------------------------------------------------------------
def test_new_schematic_sheet_undo(app, lib, asked, monkeypatch):
    p = _jps_project()
    w = _win(lib, p)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Nový list", True)))
    before = _state(p)
    w.new_schematic_sheet()
    sheet = p.sheets[-1]
    assert sheet.name == "Nový list" and _sheet_tabs(w, sheet) == ["schematic"]
    _roundtrip(w, before)
    w.undo.undo()
    assert sheet not in p.sheets and _sheet_tabs(w, sheet) == []
    w.undo.redo()
    assert p.sheets[-1] is sheet and _sheet_tabs(w, sheet) == ["schematic"]
    _done(w)


def test_open_new_switchboard_with_template_is_one_step(app, lib, asked, monkeypatch):
    p = _jps_project()
    blk = p.sheets[0].elements[1]
    w = _win(lib, p)
    monkeypatch.setattr(MainWindow, "_ask_template", lambda self: ("ac_fve", {"distribution": "terminals"}))
    before = _state(p)
    w._open_switchboard_now(blk.id, "schematic")
    sb = p.switchboard_sheet(blk.id)
    assert sb is not None and sb.elements and blk.attrs["sheet"] == sb.name
    assert p.structure("+", "R1") is not None and w.undo.count() == 1
    jps = w._jps_scene(p.sheets[0])
    assert jps.element_items[blk.id].symbol.ports[0].name == "X1"
    _roundtrip(w, before)
    w.undo.undo()
    assert "sheet" not in blk.attrs and p.structures == [] and _sheet_tabs(w, sb) == []
    assert [pt.name for pt in jps.element_items[blk.id].symbol.ports] == ["1", "2", "3", "4"]
    w.undo.redo()
    assert _sheet_tabs(w, sb) == ["multipole"]
    _done(w)


def test_create_switchboard_sheet_without_template(app, lib, asked, monkeypatch):
    p = _jps_project()
    blk = p.sheets[0].elements[1]
    blk.attrs["sheet"] = "starý"
    w = _win(lib, p)
    monkeypatch.setattr(MainWindow, "_ask_template", lambda self: None)   # Zrušit výběr šablony
    before = _state(p)
    w._open_switchboard_now(blk.id, "layout")
    sb = p.switchboard_sheet(blk.id)
    assert sb.elements == [] and blk.attrs["sheet"] == sb.name
    _roundtrip(w, before)
    w.undo.undo()
    assert blk.attrs["sheet"] == "starý"
    _done(w)


# ---- 4: vlastnosti projektu -----------------------------------------------------------------------------------------
def test_project_meta_dialog_cancel_and_ok(app, lib, asked, monkeypatch):
    from envocad.ui.dialogs import ProjectMetaDialog
    p = _jps_project()
    p.meta.update({"investor": "Inv", "vlastni": "zůstane"})
    w = _win(lib, p)
    before = _state(p)

    def cancel(dlg):
        dlg.edits["name"].setText("Jiný")
        dlg.edits["investor"].setText("Jiný investor")
        return QDialog.Rejected
    monkeypatch.setattr(ProjectMetaDialog, "exec", cancel)
    w.edit_project_meta()
    assert _state(p) == before and w.undo.count() == 0 and w.undo.isClean()

    def ok(dlg):
        assert [dlg.edits[k].text() for k in ("name", "investor")] == ["A", "Inv"]
        dlg.edits["name"].setText("Nový název")
        dlg.edits["order"].setText("Z-1")
        dlg.changes.setPlainText("A | 2026 | první | X")
        return QDialog.Accepted
    monkeypatch.setattr(ProjectMetaDialog, "exec", ok)
    w.edit_project_meta()
    assert p.name == "Nový název" and p.meta["order"] == "Z-1" and p.meta["changes"].startswith("A |")
    assert p.meta["vlastni"] == "zůstane" and "place" not in p.meta    # prázdné nové pole klíč nepřidá
    assert w.undo.count() == 1
    _roundtrip(w, before)
    monkeypatch.setattr(ProjectMetaDialog, "exec", lambda dlg: QDialog.Accepted)   # OK beze změny = bez kroku
    w.edit_project_meta()
    assert w.undo.count() == 1
    _done(w)


# ---- 5 + 6: skříň ----------------------------------------------------------------------------------------------------
def _sb_window(lib):
    p = _jps_project()
    blk = p.sheets[0].elements[1]
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals", "n_out": "9"})
    sb.layout.rows = 3
    sb.layout.placements[-1].row = 2
    w = _win(lib, p)
    return p, sb, w


def test_enclosure_dialog_cancel_changes_nothing(app, lib, asked, monkeypatch):
    from envocad.ui.dialogs import EnclosureDialog
    p, sb, w = _sb_window(lib)
    w.open_sheet(sb, "layout")
    before = _state(p)

    def cancel(dlg):
        dlg.rows.setValue(1)
        dlg.name.setText("Hager VU36")
        dlg.name.editingFinished.emit()
        dlg._edits["ip"].setText("IP 65")
        dlg._edits["ip"].editingFinished.emit()
        return QDialog.Rejected
    monkeypatch.setattr(EnclosureDialog, "exec", cancel)
    w.edit_enclosure()
    assert _state(p) == before and w.undo.count() == 0 and w.undo.isClean() and "*" not in w.windowTitle()

    def ok(dlg):
        dlg.rows.setValue(2)
        dlg.name.setText("Hager VU36")
        dlg.name.editingFinished.emit()
        return QDialog.Accepted
    monkeypatch.setattr(EnclosureDialog, "exec", ok)
    w.edit_enclosure()
    assert sb.layout.rows == 2 and sb.layout.enclosure == "Hager VU36" and w.undo.count() == 1
    panel = w.view.side_panel
    assert panel.rows.value() == 2 and panel.name.text() == "Hager VU36"
    _roundtrip(w, before)
    w.undo.undo()
    assert panel.rows.value() == 3 and panel.name.text() == ""      # panel rozložení se načte z modelu
    _done(w)


def test_enclosure_panel_changes_are_merged_undo_steps(app, lib, asked):
    p, sb, w = _sb_window(lib)
    w.open_sheet(sb, "layout")
    panel = w.view.side_panel
    before = _state(p)
    panel.name.editingFinished.emit()                  # průchod polem beze změny = žádný krok
    assert w.undo.count() == 0 and w.undo.isClean()
    for v in (4, 5, 6):                               # šipky / psaní v poli počtu řad = jeden krok
        panel.rows.setValue(v)
    assert sb.layout.rows == 6 and w.undo.count() == 1
    panel._edits["ip"].setText("IP 54")
    panel._edits["ip"].editingFinished.emit()
    assert sb.layout.params["ip"] == "IP 54" and w.undo.count() == 2
    panel.mods.setValue(30)
    assert w.undo.count() == 3
    _roundtrip(w, before, steps=3)
    w.undo.undo()
    assert panel.mods.value() == sb.layout.modules_per_row
    w.undo.undo()
    assert panel._edits["ip"].text() == sb.layout.params.get("ip", "IP 40")
    w.undo.undo()
    assert panel.rows.value() == 3 and w.undo.isClean()
    panel.rows.setValue(4)                             # nová změna po undo …
    panel.rows.setValue(3)                             # … a návrat na původní hodnotu = krok zmizí
    assert sb.layout.rows == 3 and w.undo.count() == 0
    assert _state(p) == before and w.undo.isClean()
    _done(w)


def test_enclosure_panel_rows_there_and_back_is_no_step_and_no_defaults(app, lib, asked):
    """Počet řad 3 → 1 → 3: krok zmizí a parametry skříně zůstanou beze změny (panel nedoplní výchozí hodnoty
    polí, která v parametrech nebyla); změna jednoho pole zapíše jen to pole."""
    p, sb, w = _sb_window(lib)
    sb.layout.params = {}
    w.open_sheet(sb, "layout")
    panel = w.view.side_panel
    before = _state(p)
    panel.rows.setValue(1)
    assert sb.layout.rows == 1 and sb.layout.params == {} and w.undo.count() == 1
    panel.rows.setValue(3)
    assert w.undo.count() == 0 and w.undo.isClean() and _state(p) == before and sb.layout.params == {}
    panel._edits["ip"].setText("IP 54")
    panel._edits["ip"].editingFinished.emit()
    assert sb.layout.params == {"ip": "IP 54"} and w.undo.count() == 1
    panel._edits["ip"].setText("IP 40")               # výchozí hodnota u klíče, který už v parametrech je, zůstane
    panel._edits["ip"].editingFinished.emit()
    assert sb.layout.params == {"ip": "IP 40"}
    _done(w)


def test_enclosure_panel_no_merge_across_save(app, lib, asked, tmp_path):
    _p, sb, w = _sb_window(lib)
    w.open_sheet(sb, "layout")
    panel = w.view.side_panel
    panel.rows.setValue(4)
    assert w._save_to(tmp_path / "s.ecp") and w.undo.isClean()
    panel.rows.setValue(5)                             # uložený stav se slučováním nepřepíše
    assert w.undo.count() == 2 and not w.undo.isClean()
    w.undo.undo()
    assert sb.layout.rows == 4 and w.undo.isClean()
    _done(w)


def test_reducing_rows_keeps_placements(app, lib, asked):
    from envocad.model.checks import check_project
    from envocad.ui.layout_view import LayoutView
    p, sb, w = _sb_window(lib)
    w.open_sheet(sb, "layout")
    panel = w.view.side_panel
    moved = sb.layout.placements[-1].element_id
    n = len(sb.layout.placements)
    panel.rows.setValue(2)
    assert len(sb.layout.placements) == n                     # umístění zůstalo v modelu
    assert sb.layout.placement(moved) is None and sb.layout.stored_placement(moved).row == 2
    scene = w._unwrap(w.tabs.widget(w._find_tab(sb, "layout"))).scene()
    assert isinstance(w.view, LayoutView) and scene.items_by_id[moved].placed is False   # kreslí se nerozmístěný
    assert any(f.code == "outside_enclosure" and f.target_id == moved for f in check_project(p, lib))
    panel.rows.setValue(3)                                    # zvětšení řad umístění vrátí
    assert sb.layout.placement(moved).row == 2 and scene.items_by_id[moved].placed is True
    assert not any(f.code == "outside_enclosure" for f in check_project(p, lib))
    _done(w)


def test_layout_drag_of_outside_device_keeps_stored_placement(app, lib, asked):
    """Klik na přístroj mimo skříň (bez přesunu) nic nemění; přesun do skříně jde vrátit na uložené umístění."""
    from envocad.ui.layout_view import SetPlacementCommand
    p, sb, w = _sb_window(lib)
    w.open_sheet(sb, "layout")
    w.view.side_panel.rows.setValue(2)
    w.undo.setClean()
    scene = w.view.scene()
    moved = sb.layout.placements[-1].element_id
    it = scene.items_by_id[moved]
    scene.clearSelection()
    it.setSelected(True)
    stored = sb.layout.stored_placement(moved)
    scene._drag_start = {moved: (None, (stored.row, stored.pos))}
    scene.finish_drag()
    assert w.undo.isClean() and sb.layout.stored_placement(moved).row == 2
    before = _state(p)
    w.undo.push(SetPlacementCommand(scene, moved, (stored.row, stored.pos), (0, 0.0)))
    w.undo.undo()
    assert _state(p) == before
    _done(w)


# ---- 7: nový projekt -------------------------------------------------------------------------------------------------
def test_new_project_from_spec_and_wizard_are_dirty(app, lib, asked, monkeypatch, tmp_path):
    from envocad.ui.dialogs import ProjectWizard
    w = _win(lib, _jps_project())
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(SPEC), encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(spec), "")))
    w.new_project_from_spec()
    assert w.project.name == "FVE Test" and not w.undo.isClean() and "*" in w.windowTitle()
    assert not w.undo.canUndo()                    # neuložený stav nejde „vrátit“ do čistého
    w.autosave()
    assert w._autosave_path().exists()             # autosave běží
    asked.answers.append(QMessageBox.Cancel)
    assert not w._confirm_discard()                # zavření se zeptá
    assert asked.seen[-1][0] == "question"
    w._clear_autosave()

    w.undo.setClean()
    monkeypatch.setattr(ProjectWizard, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(ProjectWizard, "spec", lambda self: dict(SPEC, name="Z průvodce"))
    w.new_project_wizard()
    assert w.project.name == "Z průvodce" and not w.undo.isClean() and "*" in w.windowTitle()

    w.undo.setClean()
    w.new_project()                                # prázdný nový projekt bez změn zůstane čistý
    assert w.undo.isClean() and "*" not in w.windowTitle()
    _done(w)


# ---- příkazy a model -----------------------------------------------------------------------------------------------
def test_sheet_restore_state_keeps_identity(app):
    p = _jps_project()
    s = p.sheets[0]
    t, blk = s.elements
    d = copy.deepcopy(s.to_dict())
    blk.attrs["ref"] = "R9"
    s.elements.append(Element("fve.grid", 0, 0))
    s.layout.rows = 7
    s.restore_state(d)
    assert s.to_dict() == d and s.elements[0] is t and s.elements[1] is not blk and len(s.elements) == 2


def test_sheets_state_command_roundtrip(app):
    from PySide6.QtGui import QUndoStack
    p = _jps_project()
    blk = p.sheets[0].elements[1]
    sb = p.create_switchboard_sheet(blk)
    before = commands.sheets_state(p)
    s0 = _state(p)
    apply_template(p, sb, "ac_fve", {})
    after = commands.sheets_state(p)
    commands.restore_sheets_state(p, before)
    assert _state(p) == s0
    seen = []
    cmd = commands.SheetsStateCommand(p, before, after, on_change=seen.append)
    assert set(cmd.after["sheets"]) == {p.sheets[0].id, sb.id}      # jen změněné listy
    undo = QUndoStack()
    undo.push(cmd)
    s1 = _state(p)
    undo.undo()
    assert _state(p) == s0
    undo.redo()
    assert _state(p) == s1 and seen


def test_set_layout_command_merge(app):
    from PySide6.QtGui import QUndoStack
    s = Sheet(kind="switchboard")
    undo = QUndoStack()
    b = s.layout.to_dict()
    lay = s.layout
    for v in (4, 5):
        cur = s.layout.to_dict()
        undo.push(commands.SetLayoutCommand(s, cur, dict(cur, rows=v), merge_key="rows"))
    assert undo.count() == 1 and s.layout.rows == 5 and s.layout is lay
    cur = s.layout.to_dict()
    undo.push(commands.SetLayoutCommand(s, cur, dict(cur, rows=b["rows"]), merge_key="rows"))
    assert undo.count() == 0 and s.layout.to_dict() == b        # návrat na původní hodnotu → krok zmizí
    for v in (4, 5):
        cur = s.layout.to_dict()
        undo.push(commands.SetLayoutCommand(s, cur, dict(cur, rows=v), merge_key="rows"))
    cur = s.layout.to_dict()
    undo.push(commands.SetLayoutCommand(s, cur, dict(cur, enclosure="X"), merge_key="enclosure"))
    assert undo.count() == 2
    undo.undo()
    undo.undo()
    assert s.layout.to_dict() == b


def test_layout_outside_placements_model():
    from envocad.model.checks import layout_findings
    from envocad.model.thermal import temperature_rise
    p = Project()
    blk = Element("fve.switchboard", 0, 0, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    e = Element("fve.breaker_mcb", 0, 0, attrs={"ref": "F1", "modules": "2"})
    sb.elements.append(e)
    sb.layout = Layout(rows=3)
    sb.layout.set_placement(e.id, 2, 0.0)
    assert sb.layout.used_modules(sb) == e.modules and not layout_findings(p)
    sb.layout.rows = 2
    assert sb.layout.placement(e.id) is None and sb.layout.stored_placement(e.id).row == 2
    assert sb.layout.used_modules(sb) == 0 and sb.layout.outside_placements()[0].element_id == e.id
    f = layout_findings(p)
    assert len(f) == 1 and f[0].code == "outside_enclosure" and f[0].target_id == e.id and "řadě 3" in f[0].text
    other = Layout(params={"width_mm": "1000", "height_mm": "1200", "depth_mm": "300"})
    assert temperature_rise(sb, layout=other).ae_m2 != temperature_rise(sb).ae_m2


# ---- 8: hlídání resetClean / clear ---------------------------------------------------------------------------------
ALLOWED_UNDO_RESETS = {
    ("main_window.py", "_load_project", "clear"),                 # načtení projektu (otevření, nový, obnova autosave)
    ("main_window.py", "_mark_new_project_dirty", "resetClean"),  # nový projekt z průvodce / specifikace
    ("main_window.py", "offer_recovery", "resetClean"),           # obnova autosave – neuložený stav
}


def _is_undoish(node, aliases_names, aliases_attrs) -> bool:
    """Výraz, který je (nejspíš) undo stack: `undo`, `self.undo`, `self.undo_stack`, `x.undo_stack()`,
    `QUndoStack(...)` nebo alias – proměnná / atribut, do kterého se undo stack přiřadil."""
    if isinstance(node, ast.Call):
        return _is_undoish(node.func, aliases_names, aliases_attrs)
    if isinstance(node, ast.Attribute):
        return "undo" in node.attr.lower() or node.attr in aliases_attrs
    if isinstance(node, ast.Name):
        return "undo" in node.id.lower() or node.id in aliases_names
    return False


def _undo_reset_calls(src: str) -> list[tuple[str, str, int]]:
    """Všechna volání `resetClean()` a `clear()` na undo stacku v modulu: (nadřazená funkce, metoda, řádek).
    Volání v lambdě / vnořené funkci se přiřadí nejbližší pojmenované funkci, volání mimo funkci „<module>“."""
    tree = ast.parse(src)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    # aliasy: `st = self.undo`, `self.stack = self.undo`, `with ... as st`, `(st := self.undo)` – opakovaně, aby
    # se zachytil i řetěz `a = self.undo; b = a`
    names, attrs = set(), set()
    for _ in range(3):
        for node in ast.walk(tree):
            pairs = []
            if isinstance(node, ast.Assign):
                pairs = [(t, node.value) for t in node.targets]
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                pairs = [(node.target, node.value)]
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                pairs = [(node.optional_vars, node.context_expr)]
            for target, value in pairs:
                if _is_undoish(value, names, attrs):
                    if isinstance(target, ast.Name):
                        names.add(target.id)
                    elif isinstance(target, ast.Attribute):
                        attrs.add(target.attr)

    def owner(node) -> str:
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # vnořená pojmenovaná funkce (callback) se přiřadí vnější metodě
                outer = node
                while outer in parents:
                    outer = parents[outer]
                    if isinstance(outer, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        node = outer
                    elif isinstance(outer, ast.ClassDef):
                        break
                return node.name
        return "<module>"

    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        if attr == "resetClean" or (attr == "clear" and _is_undoish(node.func.value, names, attrs)):
            found.append((owner(node), attr, node.lineno))
    return found


def test_undo_reset_scanner_sees_lambda_alias_and_class_level():
    samples = {
        "def f(self):\n    panel.changed.connect(lambda: self.undo.resetClean())\n": ("f", "resetClean"),
        "def f(self):\n    st = self.undo\n    st.clear()\n": ("f", "clear"),
        "def f(self):\n    st = self.undo\n    b = st\n    b.resetClean()\n": ("f", "resetClean"),
        "def f(self):\n    self.undo_stack.clear()\n": ("f", "clear"),
        "def f(self):\n    self.scene.undo_stack().clear()\n": ("f", "clear"),
        "def f(self):\n    self.undo.resetClean()\n": ("f", "resetClean"),
        "def f(self):\n    def cb():\n        self.undo.clear()\n    return cb\n": ("f", "clear"),
        "class A:\n    def __init__(self):\n        self.stack = self.undo\n    def g(self):\n"
        "        self.stack.clear()\n": ("g", "clear"),
        "class A:\n    x = undo.clear()\n": ("<module>", "clear"),
    }
    for code, expected in samples.items():
        assert [c[:2] for c in _undo_reset_calls(code)] == [expected], code
    # běžné clear() na jiném objektu se nehlásí
    assert _undo_reset_calls("def f(self):\n    self.items.clear()\n    d = {}\n    d.clear()\n") == []


def test_no_undo_reset_outside_allowed_places():
    """V envocad/ui smí `undo.resetClean()` / `undo.clear()` zůstat jen při načtení projektu, po založení nového
    projektu a po obnově autosave – a každé volání má komentář `undo-reset-ok` (proč). Hlídají se všechna volání
    včetně lambd, vnořených funkcí, kódu mimo funkce a aliasů undo stacku (`st = self.undo; st.clear()`)."""
    ui = Path(__file__).resolve().parent.parent / "envocad" / "ui"
    found = set()
    for path in sorted(ui.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        lines = src.splitlines()
        for fn_name, attr, lineno in _undo_reset_calls(src):
            key = (path.name, fn_name, attr)
            assert key in ALLOWED_UNDO_RESETS, f"{path.name}:{lineno} {fn_name}: undo.{attr}() mimo undo"
            near = " ".join(lines[max(0, lineno - 3):lineno])
            assert "undo-reset-ok" in near, f"{path.name}:{lineno}: chybí komentář undo-reset-ok"
            found.add(key)
    assert found == ALLOWED_UNDO_RESETS
