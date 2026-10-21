"""Parametrická sběrnice v GUI: po příkazech, které mění vodiče (makro / schránka, vodič, smazání, undo / redo),
má položka sběrnice značku podle `element_symbol` – porty B{k} existují a leží tam, kde je počítá model."""
import os

import pytest

pytestmark = pytest.mark.usefixtures("ac_builtin")   # AC listy vestavěným kódem (standard `ac_builtin`)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from envocad.generate import build_project
from envocad.library.macros import find_macro, resolve_values
from envocad.library.store import LibraryStore
from envocad.model.project import Wire, WireEnd, element_symbol
from envocad.ui import commands
from envocad.ui.main_window import MainWindow
from envocad.ui.render import sp

INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, tmp_path):
    lib = LibraryStore(tmp_path / "lib.db")
    p = build_project({"inverters": [{"ref": "T1", **INV, "strings": [20]}]})
    w = MainWindow(library=lib, project=p)
    w.show()
    s = next(s for s in p.sheets if s.loc == "RFVE.AC")
    w.open_sheet(s, "schematic")
    yield w, p, s, w._active_schematic()
    w.undo.setClean()
    w.close()


def _bus(sheet):
    return next(e for e in sheet.elements if e.symbol_id == "sb.busbar")


def _ports(sc, bus) -> list[str]:
    return [p.name for p in sc.element_items[bus.id].symbol.ports]


def _in_sync(sc, p, bus) -> None:
    """Položka má stejnou značku jako model a každý port leží tam, kde ho počítá model."""
    sym = element_symbol(p, bus, sc.library)
    it = sc.element_items[bus.id]
    assert [q.name for q in it.symbol.ports] == [q.name for q in sym.ports]
    for q in sym.ports:
        assert it.port_scene_pos(q.name) == it.mapToScene(sp(q.x, q.y))


def _wires_at_ports(sc, bus) -> None:
    """Trasa každého vodiče sběrnice začíná / končí v poloze portu na položce (vývod 3 se s přívody posouvá)."""
    from envocad.ui.items import path_points
    it = sc.element_items[bus.id]
    for wi in sc.wire_items.values():
        for end in (wi.wire.a, wi.wire.b):
            if end.element_id == bus.id:
                pts = path_points(wi.path())
                pos = it.port_scene_pos(end.port)
                assert any(abs(x - pos.x()) < 1e-6 and abs(y + pos.y()) < 1e-6   # path_points: Y nahoru
                           for x, y in (pts[0], pts[-1])), (end.port, pts, pos)


def test_macro_twice_then_undo_redo(win):
    """Repro z review: dvakrát makro „AC přívod střídače“ → `port_scene_pos("B2")` dřív padalo na KeyError."""
    w, p, s, sc = win
    bus = _bus(s)
    assert "B2" not in _ports(sc, bus)
    m = find_macro("AC přívod střídače")
    vals, errs = resolve_values(m, components=sc.library.component)
    assert errs == []
    for k in (2, 3):
        assert sc.insert_macro(m, {**vals, "k": str(k)}, (100.0 + 60 * k, 50.0)) > 0
    assert {"B2", "B3"} <= set(_ports(sc, bus))
    sc.element_items[bus.id].port_scene_pos("B2")
    _in_sync(sc, p, bus)
    _wires_at_ports(sc, bus)
    w.undo.undo()
    assert "B3" not in _ports(sc, bus) and "B2" in _ports(sc, bus)
    w.undo.undo()
    assert "B2" not in _ports(sc, bus)
    _in_sync(sc, p, bus)
    _wires_at_ports(sc, bus)
    w.undo.redo()
    w.undo.redo()
    assert {"B2", "B3"} <= set(_ports(sc, bus))
    _in_sync(sc, p, bus)
    _wires_at_ports(sc, bus)


def test_add_wire_and_remove_items(win):
    """Ruční vodič na B5 (AddWireCommand) sběrnici prodlouží, smazání (RemoveItemsCommand) zkrátí; undo / redo."""
    w, p, s, sc = win
    bus = _bus(s)
    f = next(e for e in s.elements if e.symbol_id == "fve.breaker_mcb")
    wire = Wire(WireEnd(f.id, "2"), WireEnd(bus.id, "B5"), conductors=["L1", "L2", "L3", "N"])
    w.undo.push(commands.AddWireCommand(sc, wire))
    assert "B5" in _ports(sc, bus)
    _in_sync(sc, p, bus)
    w.undo.push(commands.RemoveItemsCommand(sc, [], [wire.id]))
    assert "B5" not in _ports(sc, bus)
    w.undo.undo()
    assert "B5" in _ports(sc, bus)
    w.undo.undo()
    assert "B5" not in _ports(sc, bus)
    _in_sync(sc, p, bus)
    w.undo.redo()
    assert "B5" in _ports(sc, bus)
    _in_sync(sc, p, bus)


def test_paste_copy_of_feed_branch(win):
    """Schránka (PasteCommand) s vodičem na nový přívod sběrnice: položka sběrnice port má, undo ho vezme zpět."""
    w, p, s, sc = win
    bus = _bus(s)
    f = next(e for e in s.elements if e.symbol_id == "fve.breaker_mcb")
    from envocad.model.project import Element
    g = Element(f.symbol_id, f.x + 60, f.y, attrs=dict(f.attrs, ref="F9"))
    wire = Wire(WireEnd(g.id, "2"), WireEnd(bus.id, "B3"), conductors=["L1", "L2", "L3", "N"])
    w.undo.push(commands.PasteCommand(sc, [g], [wire]))
    assert "B3" in _ports(sc, bus)
    _in_sync(sc, p, bus)
    w.undo.undo()
    assert "B3" not in _ports(sc, bus)
    _in_sync(sc, p, bus)
