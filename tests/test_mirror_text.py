"""Zrcadlení prvků a volné texty listu (v10): model, DXF, výkres a undo."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ezdxf
import pytest

from envocad.export.dxf_export import export_sheet_dxf
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, SheetText, Wire, WireEnd, element_symbol
from envocad.model.symbol import place_dir, place_point
from envocad.model.textlayout import compute_layout, sheet_content_boxes, sheet_text_boxes


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def test_place_point_and_dir():
    assert place_point(5, 2, 0, True) == (-5, 2)
    assert place_point(5, 2, 90, False) == (-2, 5)
    assert place_point(5, 2, 90, True) == (-2, -5)        # nejdřív zrcadlení, pak otočení
    assert place_dir("E", 0, True) == "W" and place_dir("N", 0, True) == "N"
    assert place_dir("E", 90, True) == place_dir("W", 90)


def test_mirrored_ports_and_routing(lib):
    """Port vpravo se zrcadlením přesune doleva, vodič vede z nové polohy."""
    p = Project()
    s = p.sheets[0]
    t = Element("fve.inverter", 100, 100, attrs={"ref": "T1"})
    s.elements.append(t)
    sym = element_symbol(p, t, lib)
    side = next(pt for pt in sym.ports if pt.x != 0)
    x0 = t.port_pos(sym, side.name)[0]
    t.mirror = True
    x1 = t.port_pos(sym, side.name)[0]
    assert x1 - 100 == pytest.approx(-(x0 - 100))


def test_texts_are_label_obstacles_and_content(lib):
    p = Project()
    s = p.sheets[0]
    s.texts.append(SheetText(50, 50, "Popis části\nDruhý řádek", 3.5))
    boxes = sheet_text_boxes(s.texts[0])
    assert len(boxes) == 2 and boxes[1][1] < boxes[0][1]      # druhý řádek pod prvním
    content = sheet_content_boxes(p, s, lib)
    assert all(b in content for b in boxes)
    compute_layout(p, s, lib)                                  # nespadne s texty


def test_dxf_texts_and_mirrored_symbol(lib, tmp_path):
    p = Project()
    s = p.sheets[0]
    s.texts.append(SheetText(30, 40, "Hlavní rozvaděč\nRH", 5.0))
    f = Element("fve.breaker_mcb", 100, 100, attrs={"ref": "F1"}, mirror=True)
    g = Element("fve.breaker_mcb", 200, 100, attrs={"ref": "F2"})
    s.elements += [f, g]
    s.wires.append(Wire(WireEnd(f.id, "2"), WireEnd(g.id, "1"), attrs={"ref": "W1"}))
    path = tmp_path / "a.dxf"
    export_sheet_dxf(p, s, lib, path)
    msp = ezdxf.readfile(path).modelspace()
    texts = {t.dxf.text: t for t in msp.query("TEXT")}
    assert "Hlavní rozvaděč" in texts and "RH" in texts
    assert texts["RH"].dxf.height == 5.0 and texts["RH"].dxf.insert.y == pytest.approx(40 - 7.0)


# ---- výkres (Qt) ----------------------------------------------------------------------------------------------
def _scene(lib):
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QApplication

    from envocad.ui.canvas import SchematicScene
    QApplication.instance() or QApplication([])
    p = Project()
    undo = QUndoStack()
    sc = SchematicScene(p, p.sheets[0], lib, undo)
    sc.ask_attributes = False
    return p, sc, undo


def test_mirror_command_ports_match_model(lib):
    p, sc, undo = _scene(lib)
    t = Element("fve.inverter", 100, 100, attrs={"ref": "T1"})
    p.sheets[0].elements.append(t)
    sc.rebuild()
    it = sc.element_items[t.id]
    it.setSelected(True)
    sc.mirror_selected()
    assert t.mirror and undo.undoText() == "Zrcadlit"
    sym = it.symbol
    for port in sym.ports:
        sp = it.port_scene_pos(port.name)
        mx, my = t.port_pos(sym, port.name)
        assert (sp.x(), -sp.y()) == pytest.approx((mx, my)), port.name
        assert it.port_dir(port.name) == place_dir(port.dir, 0, True)
    t2 = Element("fve.breaker_mcb", 50, 50, rotation=90, attrs={"ref": "F1"}, mirror=True)
    p.sheets[0].elements.append(t2)
    sc.rebuild()
    it2 = sc.element_items[t2.id]
    for port in it2.symbol.ports:
        sp = it2.port_scene_pos(port.name)
        assert (sp.x(), -sp.y()) == pytest.approx(t2.port_pos(it2.symbol, port.name))
    undo.undo()
    assert not t.mirror


def test_text_add_edit_move_delete_undo(lib, monkeypatch):
    from envocad.ui.canvas import Mode
    from envocad.ui.text_dialog import TextDialog
    p, sc, undo = _scene(lib)
    s = p.sheets[0]
    sc.add_text(20, 30, "Pole 1", 3.5)
    assert len(s.texts) == 1 and len(sc.text_items) == 1 and undo.undoText() == "Přidat text"
    tid = s.texts[0].id
    monkeypatch.setattr(TextDialog, "exec", lambda self: TextDialog.Accepted)
    monkeypatch.setattr(TextDialog, "values", lambda self: ("Pole 1 – DC", 5.0))
    sc.edit_text(tid)
    assert s.text(tid).text == "Pole 1 – DC" and s.text(tid).height == 5.0
    sc.text_items[tid].setSelected(True)
    sc._text_move_start = {tid: (20, 30)}
    sc.text_items[tid].setPos(40, -60)
    undo.push(sc._take_text_moves())
    assert (s.text(tid).x, s.text(tid).y) == (40, 60)
    sc.text_items[tid].setSelected(True)
    sc.delete_selected()
    assert s.texts == [] and not sc.text_items
    for _ in range(3):
        undo.undo()
    assert s.texts[0].text == "Pole 1" and (s.texts[0].x, s.texts[0].y) == (20, 30)
    sc.set_mode(Mode.TEXT)
    assert sc.mode == Mode.TEXT


def test_main_window_actions(lib):
    from PySide6.QtWidgets import QApplication

    from envocad.ui.canvas import Mode
    from envocad.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    QApplication.processEvents()
    tb = [a for a in w.toolbars["tb_draw"].actions() if not a.isSeparator()]
    assert {w.actions[k] for k in ("mirror", "text", "interrupt")} <= set(tb)
    w.actions["text"].trigger()
    assert w.scene.mode == Mode.TEXT and w.actions["text"].isChecked()
    w.actions["interrupt"].trigger()
    assert w.scene.mode == Mode.PLACE and w.scene._place_symbol_id == "fve.interrupt"
    w.close()
