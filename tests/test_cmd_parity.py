"""Parita příkazového řádku s GUI: `to_dict` po příkazu z řádku = po stejné změně přes existující QUndoCommand
(scéna offscreen) – INSERT, MOVE (i ruční lomy), ROTATE, MIRROR, COPY, ERASE a SET ref včetně navázaných změn
(`rename_followups`: popisy „od T1“, port vodiče JPS u přívodu, název listu a kód umístění bloku rozvaděče).
Undo v GUI i ChangeSet z řádku vrátí stejný výchozí stav."""
import itertools
import json
import os
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from envocad.cmd import CommandRunner, default_registry
from envocad.library.store import LibraryStore
from envocad.model.grid import snap
from envocad.model.project import (
    Element,
    Project,
    Wire,
    WireEnd,
    restore_sheets_state,
    sync_cables,
    sync_feed_links,
)
from envocad.ui import commands
from envocad.ui.canvas import SchematicScene
from envocad.ui.items import ElementItem


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


@pytest.fixture
def ids(monkeypatch):
    """Deterministická id nových prvků a vodičů (`_uid` → uuid4) – obě cesty dostanou stejná id."""
    state = {}

    def reset():
        state["n"] = itertools.count(10_000)   # mimo id výchozího projektu
    reset()
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(state["n"]) << 80))   # _uid = hex[:12]
    return reset


def _source() -> dict:
    """JPS: G1 → T1 (ruční lom), T1:AC → blok R1:X1 (vodič W1, 5 žil), F1 s popisem „od T1“; list rozvaděče R1:
    přívod X1 navázaný na W1 → jistič Q1."""
    p = Project(name="Parita")
    s = p.sheets[0]
    g = Element("fve.pv_string", 30.0, 150.0, attrs={"ref": "G1"})
    t = Element("fve.inverter", 100.0, 150.0, attrs={"ref": "T1"})
    blk = Element("fve.switchboard", 200.0, 150.0, attrs={"ref": "R1"})
    f = Element("fve.breaker_mcb", 100.0, 80.0, attrs={"ref": "F1", "desc": "od T1"})
    s.elements += [g, t, blk, f]
    sb = p.create_switchboard_sheet(blk)
    feed = Element("sb.feed", 40.0, 200.0, rotation=180, attrs={"dir": "in", "ref": "X1"})
    q = Element("fve.breaker_mcb", 40.0, 150.0, attrs={"ref": "Q1"})
    sb.elements += [feed, q]
    sb.wires.append(Wire(WireEnd(feed.id, "1"), WireEnd(q.id, "1"), conductors=["L1", "N", "PE"]))
    s.wires += [Wire(WireEnd(g.id, "DC"), WireEnd(t.id, "DC1"), points=[(60.0, 155.0)], attrs={"ref": "W2"}),
                Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X1"), attrs={"ref": "W1"},
                     conductors=["L1", "L2", "L3", "N", "PE"])]
    sync_feed_links(p)          # jako otevření projektu v GUI
    sync_cables(p)
    return json.loads(json.dumps(p.to_dict()))


@pytest.fixture(scope="module")
def source():
    """Výchozí projekt – vzniká před `ids` (vyšší rozsah), takže jeho id nekolidují s deterministickými."""
    return _source()


def _state(p: Project) -> str:
    return json.dumps(p.to_dict(), sort_keys=True, ensure_ascii=False)


def _el(p: Project, ref: str, sheet: int = 0) -> Element:
    return next(e for e in p.sheets[sheet].elements if e.ref == ref)


def _both(d: dict, lib, ids, line: str, gui, sheet: int = 0):
    """Stejná změna z řádku (projekt A) a přes QUndoCommand (projekt B); vrací výsledek příkazu z řádku."""
    pa, pb = Project.from_dict(d), Project.from_dict(d)
    start = _state(pa)
    ids()
    r = CommandRunner(pa, lib, default_registry(user_aliases=False), sheet=pa.sheets[sheet])
    res = r.execute(line)
    assert res.ok, res.messages
    ids()
    undo = QUndoStack()
    sc = SchematicScene(pb, pb.sheets[sheet], lib, undo)
    assert _state(pb) == start                          # scéna sama model nemění
    gui(pb, sc, undo)
    assert _state(pa) == _state(pb), line
    # zpět: undo GUI i ChangeSet z řádku vrátí výchozí stav
    while undo.canUndo():
        undo.undo()
    restore_sheets_state(pa, res.changeset.before)
    assert _state(pb) == start, "undo GUI"
    assert _state(pa) == start, "ChangeSet.before"
    return res


def _select(sc, eids):
    sc.clearSelection()
    for eid in eids:
        sc.element_items[eid].setSelected(True)


def test_insert(app, lib, ids, source):
    def gui(p, sc, undo):
        sym = lib.get_symbol("fve.breaker_mcb")
        e = Element(symbol_id=sym.id, x=snap(201.0), y=snap(51.0))
        e.attrs = {a.key: a.default for a in sym.attributes}
        e.attrs["ref"] = p.next_ref(sym.iec_ref)
        undo.push(commands.AddElementCommand(sc, e))
    _both(source, lib, ids, "INSERT fve.breaker_mcb 201,51", gui)


def test_move_with_bends(app, lib, ids, source):
    """Tah myší: scéna posune položky (lomy vodičů jdou s nimi), puštění = MoveElementsCommand."""
    def gui(p, sc, undo):
        moving = [_el(p, "T1"), _el(p, "F1")]
        sc._move_start = {e.id: (e.x, e.y) for e in moving}
        sc._move_wire_pts = {w.id: [tuple(x) for x in w.points] for w in sc.sheet.wires if w.points}
        sc._dragging = True
        for e in moving:
            it: ElementItem = sc.element_items[e.id]
            it.setPos(e.x + 10, -(e.y - 5))
        moves = {eid: (old, (sc.sheet.element(eid).x, sc.sheet.element(eid).y)) for eid, old in sc._move_start.items()}
        wp = {wid: (old, [tuple(x) for x in next(w for w in sc.sheet.wires if w.id == wid).points])
              for wid, old in sc._move_wire_pts.items()}
        sc._dragging = False
        undo.push(commands.MoveElementsCommand(sc, moves, wp))
    res = _both(source, lib, ids, "MOVE T1 F1 0,0 @10,-5", gui)
    w2 = next(w for w in res.changeset.after["sheets"][source["sheets"][0]["id"]]["wires"] if w["attrs"]["ref"] == "W2")
    assert w2["points"] == [[60.0, 150.0]]               # lom u posunutého konce jde s ním


def test_rotate(app, lib, ids, source):
    def gui(p, sc, undo):
        _select(sc, [_el(p, "T1").id, _el(p, "F1").id])
        sc.rotate_selected()
    _both(source, lib, ids, "RO T1 F1", gui)


def test_mirror(app, lib, ids, source):
    def gui(p, sc, undo):
        _select(sc, [_el(p, "G1").id])
        sc.mirror_selected()
    _both(source, lib, ids, "MI G1", gui)


def test_copy(app, lib, ids, source):
    """COPY o (10, -10) = Ctrl+C, Ctrl+V (první vložení posune o 10 mm doprava a dolů)."""
    def gui(p, sc, undo):
        _select(sc, [_el(p, "G1").id, _el(p, "T1").id])
        sc.copy_selected()
        sc.paste()
    _both(source, lib, ids, "COPY G1 T1 0,0 @10,-10", gui)


def test_erase(app, lib, ids, source):
    def gui(p, sc, undo):
        _select(sc, [_el(p, "T1").id])
        sc.delete_selected()
    _both(source, lib, ids, "E T1", gui)


def test_insert_feed_with_link(app, lib, ids, source):
    """Vývod s vazbou na vodič JPS: dialog vložení doplní odvozené atributy vazby (kam, kabel) – řádek taky;
    `wire_id` z řádku smí být označení vodiče (W1)."""
    def gui(p, sc, undo):
        from envocad.model.project import feed_link_attrs
        sym = lib.get_symbol("sb.feed")
        e = Element(symbol_id=sym.id, x=snap(120.0), y=snap(200.0))
        e.attrs = {a.key: a.default for a in sym.attributes}
        e.attrs["ref"] = p.next_ref(sym.iec_ref)
        e.attrs.update({"dir": "out", "wire_id": next(w.id for w in p.sheets[0].wires if w.attrs.get("ref") == "W1")})
        e.attrs.update(feed_link_attrs(p, sc.sheet, e, e.attrs["wire_id"]))
        undo.push(commands.AddElementCommand(sc, e))
    res = _both(source, lib, ids, "INSERT sb.feed 120,200 dir=out wire_id=W1", gui, sheet=1)
    after = res.changeset.after["sheets"][Project.from_dict(source).sheets[1].id]
    new = next(e for e in after["elements"] if e["attrs"].get("dir") == "out")
    assert "W1" in new["attrs"]["to"]


@pytest.mark.parametrize("sheet, old, new", [(0, "T1", "T7"), (1, "X1", "X5"), (0, "R1", "R5")])
def test_set_ref_with_followups(app, lib, ids, source, sheet, old, new):
    def gui(p, sc, undo):
        sc.set_attr(_el(p, old, sheet).id, False, "ref", new)
    res = _both(source, lib, ids, f"SET {old} ref={new}", gui, sheet)
    # navázané změny opravdu proběhly (jinak by parita nic neověřila)
    redo = Project.from_dict(source)
    restore_sheets_state(redo, res.changeset.after)
    if old == "T1":
        assert _el(redo, "F1").attrs["desc"] == "od T7"
    elif old == "X1":
        w1 = next(w for w in redo.sheets[0].wires if w.attrs.get("ref") == "W1")
        assert w1.b.port == "X5" and len(res.changeset.changed_sheets) == 2
    else:
        assert redo.sheets[1].name.startswith("R5") and redo.sheets[1].loc == "R5"
        assert any(x.code == "R5" for x in redo.structures)


def test_changeset_pushes_as_sheets_state_command(app, lib, source):
    """Fáze 2: GUI pushne ChangeSet z řádku jako jeden SheetsStateCommand – první redo nic nemění, Ctrl+Z vrátí
    stav před příkazem, Ctrl+Y ho zopakuje (i navázané změny na jiném listu)."""
    p = Project.from_dict(source)
    start = _state(p)
    r = CommandRunner(p, lib, default_registry(user_aliases=False), sheet=p.sheets[1])
    res = r.execute("SET X1 ref=X5")
    after = _state(p)
    seen = []
    undo = QUndoStack()
    cs = res.changeset
    undo.push(commands.SheetsStateCommand(p, cs.before, cs.after, cs.label, on_change=seen.append))
    assert _state(p) == after and undo.undoText() == "Nastavit atributy"
    undo.undo()
    assert _state(p) == start and sorted(seen[-1]) == sorted(cs.changed_sheets)
    undo.redo()
    assert _state(p) == after
