"""Undo/redo všech příkazů z ui/commands.py: undo vrátí projekt přesně do původního stavu, redo zopakuje změnu."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from envocad.library.store import LibraryStore
from envocad.model.project import Cable, Element, Project, Wire, WireEnd
from envocad.ui import commands
from envocad.ui.canvas import SchematicScene


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _project():
    p = Project(name="Undo")
    s = p.sheets[0]
    g = Element("fve.pv_string", 30, 150, attrs={"ref": "G1"})
    q = Element("fve.dc_disconnect", 70, 152.5, attrs={"ref": "Q1"})
    t = Element("fve.inverter", 120, 150, attrs={"ref": "T1"})
    f = Element("fve.breaker_mcb", 170, 150, attrs={"ref": "F1", "in_": "80 A"})
    s.elements += [g, q, t, f]
    s.wires += [
        Wire(WireEnd(g.id, "DC"), WireEnd(q.id, "1"), attrs={"ref": "W1"}),
        Wire(WireEnd(q.id, "2"), WireEnd(t.id, "DC1"), points=[(95.0, 152.5)]),
        Wire(WireEnd(t.id, "AC"), WireEnd(f.id, "1"), attrs={"ref": "W2"}),
    ]
    return p


def _state(p: Project) -> str:
    return json.dumps(p.to_dict(), sort_keys=True, ensure_ascii=False)


def _check(p: Project, undo: QUndoStack, cmd, scene=None) -> None:
    """Pushne příkaz (redo), ověří změnu, undo → původní stav, redo → stav po změně. Scéna musí sedět s modelem."""
    before = _state(p)
    undo.push(cmd)
    after = _state(p)
    assert after != before, f"{cmd.text()}: příkaz nic nezměnil"
    undo.undo()
    assert _state(p) == before, f"{cmd.text()}: undo nevrátilo původní stav"
    if scene is not None:
        _scene_matches(scene)
    undo.redo()
    assert _state(p) == after, f"{cmd.text()}: redo nedalo stejný stav"
    if scene is not None:
        _scene_matches(scene)


def _scene_matches(sc) -> None:
    if hasattr(sc, "element_items"):
        assert set(sc.element_items) == {e.id for e in sc.sheet.elements}
        assert set(sc.wire_items) == {w.id for w in sc.sheet.wires}


@pytest.fixture
def jps(app, lib):
    p = _project()
    undo = QUndoStack()
    sc = SchematicScene(p, p.sheets[0], lib, undo)
    yield p, sc, undo
    undo.clear()


def _el(p, ref):
    return next(e for e in p.sheets[0].elements if e.ref == ref)


def test_add_element(jps):
    p, sc, undo = jps
    _check(p, undo, commands.AddElementCommand(sc, Element("fve.meter", 200, 100, attrs={"ref": "P1"})), sc)


def test_remove_items_keeps_order(jps):
    p, sc, undo = jps
    q = _el(p, "Q1")
    w2 = next(w for w in p.sheets[0].wires if w.attrs.get("ref") == "W2")
    # Q1 je uprostřed seznamu a má dva vodiče – po undo musí být na svém místě (pořadí určuje číslování a rozmístění)
    _check(p, undo, commands.RemoveItemsCommand(sc, [q.id], [w2.id]), sc)


def test_move_elements(jps):
    p, sc, undo = jps
    t = _el(p, "T1")
    old, new = (t.x, t.y), (t.x + 10, t.y - 5)
    w = p.sheets[0].wires[1]
    pts_old, pts_new = list(w.points), [(105.0, 152.5)]
    # posun proběhl interaktivně (první redo se přeskočí) → stav po posunu nastavíme ručně
    t.x, t.y = new
    w.points = pts_new
    sc.element_items[t.id].sync_from_model()
    moved = _state(p)
    undo.push(commands.MoveElementsCommand(sc, {t.id: (old, new)}, {w.id: (pts_old, pts_new)}))
    assert _state(p) == moved
    undo.undo()
    assert (t.x, t.y) == old and w.points == pts_old
    undo.redo()
    assert _state(p) == moved


def test_set_wire_points(jps):
    p, sc, undo = jps
    w = p.sheets[0].wires[1]
    _check(p, undo, commands.SetWirePointsCommand(sc, {w.id: (list(w.points), [])}), sc)


def test_rotate(jps):
    p, sc, undo = jps
    _check(p, undo, commands.RotateElementCommand(sc, _el(p, "F1").id, 90), sc)
    _check(p, undo, commands.RotateElementCommand(sc, _el(p, "F1").id, 270), sc)


def test_add_wire(jps):
    p, sc, undo = jps
    f, t = _el(p, "F1"), _el(p, "T1")
    _check(p, undo, commands.AddWireCommand(sc, Wire(WireEnd(f.id, "2"), WireEnd(t.id, "DC2"))), sc)


def test_split_wire_keeps_order(jps):
    p, sc, undo = jps
    old = p.sheets[0].wires[0]
    j = Element("sb.junction", 50, 150)
    w1 = Wire(old.a, WireEnd(j.id, "W"), attrs=dict(old.attrs))
    w2 = Wire(WireEnd(j.id, "E"), old.b)
    _check(p, undo, commands.SplitWireCommand(sc, old.id, j, w1, w2), sc)


def test_set_attr_element_and_wire(jps):
    p, sc, undo = jps
    f = _el(p, "F1")
    _check(p, undo, commands.SetAttrCommand(sc, f.id, False, "in_", "80 A", "63 A"), sc)
    w = p.sheets[0].wires[0]
    _check(p, undo, commands.SetAttrCommand(sc, w.id, True, "ref", "W1", "W9"), sc)


def test_set_attr_new_key_is_removed_on_undo(jps):
    """Undo nového atributu nesmí nechat v projektu prázdný klíč (projekt by se lišil od původního)."""
    p, sc, undo = jps
    f = _el(p, "F1")
    assert "desc" not in f.attrs
    _check(p, undo, commands.SetAttrCommand(sc, f.id, False, "desc", "", "hlavní jistič"), sc)


def test_set_component(jps):
    p, sc, undo = jps
    f = _el(p, "F1")
    _check(p, undo, commands.SetComponentCommand(sc, f.id, f.component_id, "TEST-123"), sc)


def test_paste(jps):
    p, sc, undo = jps
    a = Element("fve.breaker_mcb", 220, 150, attrs={"ref": "F2"})
    b = Element("fve.breaker_mcb", 260, 150, attrs={"ref": "F3"})
    _check(p, undo, commands.PasteCommand(sc, [a, b], [Wire(WireEnd(a.id, "2"), WireEnd(b.id, "1"))]), sc)


def test_conductors_terminals_bridges(jps):
    p, sc, undo = jps
    w = p.sheets[0].wires[2]
    old = list(w.conductors)
    _check(p, undo, commands.SetConductorsCommand(sc, w.id, old, ["L1", "N", "PE"]), sc)
    _check(p, undo, commands.SetTerminalsCommand(sc, w.id, dict(w.terminals),
                                                 {w.conductors[0]: {"a": "X1:1"}}), sc)
    _check(p, undo, commands.SetBridgesCommand(p, p.sheets[0], "X1", [], [["1", "2"]]))


def test_set_cable(jps):
    p, _sc, undo = jps
    c = Cable(ref="WC1")
    p.cables.append(c)
    old = c.to_dict()
    new = dict(old, note="přes střechu")
    _check(p, undo, commands.SetCableCommand(p, c.id, old, new))


def test_multipole_commands(app, lib):
    from envocad.generate import build_project
    from envocad.ui.multipole_view import MultipoleScene
    spec = {"name": "MP", "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200,
                                        "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [20, 20]}]}
    p = build_project(spec)
    sb = next(s for s in p.switchboards() if s.loc == "RFVE.AC")
    undo = QUndoStack()
    sc = MultipoleScene(p, sb, lib, undo)
    sc.rebuild()
    e = next(e for e in sb.elements if e.ref == "X1")
    _check(p, undo, commands.MoveMultipoleCommand(sc, {e.id: (e.mp_pos, (100.0, 100.0))}))
    f = Element("fve.breaker_mcb", 0, 0, attrs={"ref": "F99"})
    f.mp_pos = (200.0, 150.0)
    _check(p, undo, commands.MultipoleAddCommand(sc, element=f))
    undo.clear()


# ---- v8: strukturní označení a revize ---------------------------------------------------------------------
def _roundtrip(p, make_cmd, mutate_check=None):
    """Příkaz: redo změní model, undo ho vrátí přesně (to_dict), druhé redo zopakuje výsledek."""
    undo = QUndoStack()
    before = p.to_dict()
    undo.push(make_cmd())
    after = p.to_dict()
    assert after != before
    undo.undo()
    assert p.to_dict() == before
    undo.redo()
    assert p.to_dict() == after
    undo.undo()
    assert p.to_dict() == before


def test_sheet_designation_and_rename_structure_undo(app):
    from envocad.model.project import StructureId
    p = _project()
    s = p.sheets[0]
    s.loc = "RS1"
    s.elements[0].attrs["loc"] = "RS1"
    p.structures.append(StructureId("+", "RS1", "rozvaděč"))
    _roundtrip(p, lambda: commands.SetSheetDesignationCommand(s, (s.func, s.loc), ("AC", "RS2")))
    _roundtrip(p, lambda: commands.RenameStructureCommand(p, "+", "RS1", "RS9"))
    assert p.structures[0].code == "RS1" and s.elements[0].attrs["loc"] == "RS1"
    new = [StructureId("=", "AC", "střídavá část"), StructureId("+", "RS1", "jiný popis")]
    _roundtrip(p, lambda: commands.SetStructuresCommand(p, p.structures, new))


def test_replace_revisions_undo_and_record(app):
    from envocad.model.diff import diff_projects
    from envocad.model.project import Project as P
    from envocad.model.revision import apply_changes, open_revision, restore_revisions_state, revisions_state
    p = _project()
    old = P.from_dict(p.to_dict())
    p.sheets[0].elements[0].attrs["ref"] = "G9"
    changes = diff_projects(old, p)
    assert changes
    before = revisions_state(p)
    rev = open_revision(p, "B", "1.1.2026", "ENVO")
    apply_changes(p, rev, changes)
    after = revisions_state(p)
    restore_revisions_state(p, before)
    assert p.revisions == [] or p.to_dict()["revisions"] == [r.to_dict() for r in before[0]]
    _roundtrip(p, lambda: commands.ReplaceRevisionsCommand(p, before, after))
    undo = QUndoStack()
    undo.push(commands.ReplaceRevisionsCommand(p, before, after))
    assert p.revisions[-1].label == "B" and p.meta["revision"] == "B"


def test_replace_revisions_undo_keeps_other_meta(app):
    """Undo revize vrátí jen meta „revision“/„changes“ – úprava investora mimo příkaz zůstane."""
    from envocad.model.revision import apply_changes, open_revision, restore_revisions_state, revisions_state
    p = _project()
    p.meta.update({"investor": "Původní", "revision": "A"})
    undo = QUndoStack()
    before = revisions_state(p)
    rev = open_revision(p, "B")
    apply_changes(p, rev, [])
    p.meta["changes"] = "B | 1.1.2026 | změna | ENVO"
    after = revisions_state(p)
    restore_revisions_state(p, before)
    undo.push(commands.ReplaceRevisionsCommand(p, before, after))
    assert p.meta["revision"] == "B" and p.meta["changes"]
    p.meta["investor"] = "Nový"                                   # změna mimo příkaz
    undo.undo()
    assert p.meta["investor"] == "Nový" and p.meta["revision"] == "A" and "changes" not in p.meta
    assert p.revisions == []
    undo.redo()
    assert p.meta["investor"] == "Nový" and p.meta["revision"] == "B"


def test_rename_sheet_undo(app, monkeypatch):
    """Název listu přes undo (RenameSheetCommand), s označením v jednom makru, bez resetClean."""
    from PySide6.QtWidgets import QMessageBox

    from envocad.ui.main_window import MainWindow
    p = _project()
    s = p.sheets[0]
    _roundtrip(p, lambda: commands.RenameSheetCommand(s, s.name, "Nový název"))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    w = MainWindow(library=LibraryStore(), project=p)
    try:
        w.undo.setClean()
        name0 = s.name
        before = p.to_dict()
        assert w.set_sheet_props(s, "Přejmenovaný", "AC", "RS1")
        assert (s.name, s.func, s.loc) == ("Přejmenovaný", "AC", "RS1")
        assert not w.undo.isClean() and w.undo.count() == 1    # jeden krok undo (makro)
        assert any(w.tabs.tabText(i).startswith("Přejmenovaný") for i in range(w.tabs.count()))
        w.undo.undo()
        assert p.to_dict() == before and s.name == name0 and w.undo.isClean()
        assert any(w.tabs.tabText(i).startswith(name0) for i in range(w.tabs.count()))
        w.undo.redo()
        assert s.name == "Přejmenovaný"
        assert w.set_sheet_props(s, "Jen název", "AC", "RS1") and s.name == "Jen název" and w.undo.count() == 2
        n = w.undo.count()
        assert not w.set_sheet_props(s, "Neplatný", "1X", "RS1")     # neplatný kód → nic se nezmění
        assert s.name == "Jen název" and w.undo.count() == n
        assert w.set_sheet_props(s, "Jen název", "AC", "RS1") and w.undo.count() == n   # beze změny = bez kroku
    finally:
        w.undo.setClean()
        w.close()


# ---- připomínky ------------------------------------------------------------------------------
def test_replace_note_command(jps):
    import copy

    from envocad.model.notes import note
    from envocad.model.project import Note
    p, _sc, undo = jps
    sid = p.sheets[0].id
    before = _state(p)
    a = Note(sid, x=10, y=20, text="první", author="Jan")
    undo.push(commands.ReplaceNoteCommand(p, None, a, "Přidat připomínku"))
    assert [n.no for n in p.notes] == [1] and p.notes[0] is not a      # hluboká kopie, číslo přidělené
    undo.undo()
    assert _state(p) == before
    undo.redo()
    assert p.notes[0].no == 1
    b = Note(sid, x=30, y=40, w=10, h=5, text="druhá")
    c = Note(sid, x=50, y=60, text="třetí")
    for n in (b, c):
        undo.push(commands.ReplaceNoteCommand(p, None, n, "Přidat připomínku"))
    assert [n.no for n in p.notes] == [1, 2, 3]

    # stav (vyřešit / znovu otevřít) a posun
    cur = note(p, b.id)
    done = copy.deepcopy(cur)
    done.status, done.resolved_by, done.resolved = "resolved", "Jan", "2026-10-16T10:00"
    _check(p, undo, commands.ReplaceNoteCommand(p, cur, done, "Vyřešit"))
    assert note(p, b.id).status == "resolved"
    moved = copy.deepcopy(note(p, a.id))
    moved.x, moved.y = 12.5, 22.5
    _check(p, undo, commands.ReplaceNoteCommand(p, note(p, a.id), moved, "Posunout"))
    assert (note(p, a.id).x, note(p, a.id).y) == (12.5, 22.5)

    # smazání prostřední: undo ji vrátí na původní místo (pořadí), číslo se nemění; nová nepoužije smazané číslo
    # (čítač meta["note_seq"] – viz test_note_numbers_not_reused_after_deleting_highest)
    mid = note(p, b.id)
    undo.push(commands.ReplaceNoteCommand(p, mid, None, "Smazat"))
    assert [n.no for n in p.notes] == [1, 3]
    undo.undo()
    assert [n.no for n in p.notes] == [1, 2, 3] and [n.id for n in p.notes] == [a.id, b.id, c.id]
    undo.redo()
    undo.push(commands.ReplaceNoteCommand(p, None, Note(sid, x=0, y=0), "Přidat připomínku"))
    assert [n.no for n in p.notes] == [1, 3, 4]
    undo.undo()
    undo.undo()
    assert [n.id for n in p.notes] == [a.id, b.id, c.id]

    # on_change se volá při redo i undo
    calls = []
    undo.push(commands.ReplaceNoteCommand(p, note(p, c.id), None, "Smazat", lambda: calls.append(1)))
    undo.undo()
    assert len(calls) == 2


def test_note_numbers_not_reused_after_deleting_highest(jps):
    """1, 2, 3 → smazat 3 → přidat → 4 (čítač meta["note_seq"]); undo vrátí i čítač."""
    from envocad.model.project import Note
    p, _sc, undo = jps
    sid = p.sheets[0].id
    for i in range(3):
        undo.push(commands.ReplaceNoteCommand(p, None, Note(sid, x=10 * i, y=0), "Přidat připomínku"))
    assert [n.no for n in p.notes] == [1, 2, 3]
    undo.push(commands.ReplaceNoteCommand(p, p.notes[-1], None, "Smazat"))
    assert [n.no for n in p.notes] == [1, 2]
    undo.push(commands.ReplaceNoteCommand(p, None, Note(sid, x=99, y=0), "Přidat připomínku"))
    assert [n.no for n in p.notes] == [1, 2, 4] and p.meta["note_seq"] == "4"
    undo.undo()                                   # undo vrátí přesný stav včetně čítače
    assert [n.no for n in p.notes] == [1, 2] and p.meta["note_seq"] == "3"
    undo.redo()
    assert [n.no for n in p.notes] == [1, 2, 4] and p.meta["note_seq"] == "4"
    undo.undo()
    undo.undo()                                   # vrátit smazání č. 3
    assert [n.no for n in p.notes] == [1, 2, 3] and p.meta["note_seq"] == "3"
    for _ in range(3):
        undo.undo()
    assert not p.notes and "note_seq" not in p.meta
