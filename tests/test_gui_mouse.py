"""Interakce myší nad SchematicScene/SchematicView – skutečné události přes viewport (offscreen).

Souřadnice scény jsou v mm s osou Y dolů (Qt); model má Y nahoru. Převod na pixely dělá view.mapFromScene.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from envocad.library.store import LibraryStore
from envocad.model.multipole import default_conductors
from envocad.model.project import Element, Project, Wire, WireEnd
from envocad.ui import dialogs
from envocad.ui.canvas import Mode
from envocad.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app):
    made = []

    def make(project=None):
        w = MainWindow(LibraryStore(), project or Project(name="Mouse"))
        w.resize(1400, 900)
        w.show()
        app.processEvents()
        w.view.zoom_fit()
        app.processEvents()
        made.append(w)
        return w

    yield make
    for w in made:
        w.undo.setClean()
        w.close()


def vp(w, x_mm, y_mm):
    """Pixel ve viewportu pro bod daný v modelových mm (Y nahoru)."""
    return w.view.mapFromScene(QPointF(x_mm, -y_mm))


def vp_scene(w, p: QPointF) -> QPoint:
    return w.view.mapFromScene(p)


def pump(app, n=5):
    for _ in range(n):
        app.processEvents()
    QTest.qWait(10)


def two_elements():
    p = Project(name="Mouse")
    a = Element("fve.breaker_mcb", 60, 150, attrs={"ref": "F1"})
    b = Element("fve.breaker_mcb", 140, 150, attrs={"ref": "F2"})
    p.sheets[0].elements += [a, b]
    return p, a, b


def test_place_with_mouse(app, win):
    w = win()
    sc, view = w.scene, w.view
    sc.ask_attributes = False
    sc.start_place("fve.breaker_mcb")
    assert sc.mode == Mode.PLACE and sc._ghost is not None
    port = view.viewport()

    QTest.mouseMove(port, vp(w, 100, 100))
    g1 = sc._ghost.pos()
    QTest.mouseMove(port, vp(w, 120, 110))
    g2 = sc._ghost.pos()
    assert g1 != g2  # ghost sleduje myš
    for g in (g1, g2):
        assert g.x() % 2.5 == pytest.approx(0) and g.y() % 2.5 == pytest.approx(0)

    n0 = w.undo.count()
    QTest.mouseClick(port, Qt.LeftButton, Qt.NoModifier, vp(w, 120, 110))
    assert len(sc.sheet.elements) == 1 and w.undo.count() == n0 + 1
    e = sc.sheet.elements[0]
    assert e.x % 2.5 == pytest.approx(0) and e.y % 2.5 == pytest.approx(0)
    assert e.x == pytest.approx(120, abs=1.3) and e.y == pytest.approx(110, abs=1.3)
    assert (e.x, e.y) == (g2.x(), -g2.y())  # shodně s pozicí ghostu
    assert sc.mode == Mode.PLACE

    QTest.mouseClick(port, Qt.LeftButton, Qt.NoModifier, vp(w, 60, 60))
    assert len(sc.sheet.elements) == 2 and sc.mode == Mode.PLACE

    QTest.mouseClick(port, Qt.RightButton, Qt.NoModifier, vp(w, 60, 60))
    assert sc.mode == Mode.SELECT and sc._ghost is None
    assert len(sc.sheet.elements) == 2


def test_place_with_dialog_deferred(app, win, monkeypatch):
    w = win()
    sc = w.scene
    calls = []

    def fake_exec(self):
        calls.append(1)
        return dialogs.ElementDialog.Accepted

    monkeypatch.setattr(dialogs.ElementDialog, "exec", fake_exec)
    sc.ask_attributes = True
    sc.start_place("fve.breaker_mcb")
    n0 = w.undo.count()
    QTest.mouseClick(w.view.viewport(), Qt.LeftButton, Qt.NoModifier, vp(w, 100, 100))
    # dialog je odložen mimo obsluhu události
    assert not calls and len(sc.sheet.elements) == 0 and w.undo.count() == n0
    pump(app)
    assert calls == [1]
    assert len(sc.sheet.elements) == 1 and w.undo.count() == n0 + 1
    assert sc.mode == Mode.PLACE


def test_draw_wire_with_mouse(app, win):
    p, a, b = two_elements()
    w = win(p)
    sc, view = w.scene, w.view
    sc.ask_attributes = False
    ia, ib = sc.element_items[a.id], sc.element_items[b.id]
    port = view.viewport()

    QTest.keyClick(port, Qt.Key_W)
    assert sc.mode == Mode.WIRE
    pa = vp_scene(w, ia.port_scene_pos("2"))
    pb = vp_scene(w, ib.port_scene_pos("1"))

    QTest.mouseClick(port, Qt.LeftButton, Qt.NoModifier, pa)
    assert sc._wire_from == (ia, "2")
    assert sc._wire_preview.scene() is sc
    QTest.mouseMove(port, pb)
    assert not sc._wire_preview.path().isEmpty()

    n0 = w.undo.count()
    QTest.mouseClick(port, Qt.LeftButton, Qt.NoModifier, pb)
    assert sc._wire_from is None and sc._wire_preview.scene() is None
    assert len(sc.sheet.wires) == 1 and w.undo.count() == n0 + 1
    wire = sc.sheet.wires[0]
    assert (wire.a.element_id, wire.a.port, wire.b.element_id, wire.b.port) == (a.id, "2", b.id, "1")
    assert wire.conductors == default_conductors(a, "2", b, "1")
    assert wire.id in sc.wire_items

    w.undo.undo()
    assert not sc.sheet.wires and not sc.wire_items
    w.undo.redo()
    assert len(sc.sheet.wires) == 1 and len(sc.wire_items) == 1


def test_drag_element_updates_wire(app, win):
    p, a, b = two_elements()
    p.sheets[0].wires.append(Wire(WireEnd(a.id, "2"), WireEnd(b.id, "1")))
    w = win(p)
    sc, view = w.scene, w.view
    ia = sc.element_items[a.id]
    wi = next(iter(sc.wire_items.values()))
    port = view.viewport()
    n0 = w.undo.count()
    start = vp(w, a.x, a.y)
    end = vp(w, a.x + 20, a.y + 20)

    QTest.mousePress(port, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(port, vp(w, a.x + 10, a.y + 10))
    QTest.mouseMove(port, end)
    QTest.mouseRelease(port, Qt.LeftButton, Qt.NoModifier, end)

    assert (a.x, a.y) != (60, 150)
    assert a.x == pytest.approx(80, abs=1.5) and a.y == pytest.approx(170, abs=1.5)
    assert a.x % 2.5 == pytest.approx(0) and a.y % 2.5 == pytest.approx(0)
    assert w.undo.count() == n0 + 1
    assert type(w.undo.command(n0)).__name__ == "MoveElementsCommand"
    # vodič končí v portu 1 druhého prvku a začíná v portu 2 posunutého
    path = wi.path()
    first, last = path.elementAt(0), path.elementAt(path.elementCount() - 1)
    p2 = ia.port_scene_pos("2")
    p1b = sc.element_items[b.id].port_scene_pos("1")
    assert (first.x, first.y) == pytest.approx((p2.x(), p2.y()))
    assert (last.x, last.y) == pytest.approx((p1b.x(), p1b.y()))

    w.undo.undo()
    assert (a.x, a.y) == (60, 150)
    assert ia.pos() == QPointF(60, -150)
    path = wi.path()
    first = path.elementAt(0)
    p2 = ia.port_scene_pos("2")
    assert (first.x, first.y) == pytest.approx((p2.x(), p2.y()))


def test_double_click_edits_attribute(app, win, monkeypatch):
    p, a, b = two_elements()
    w = win(p)
    monkeypatch.setattr(dialogs.ElementDialog, "exec", lambda self: dialogs.ElementDialog.Accepted)
    monkeypatch.setattr(dialogs.ElementDialog, "values",
                        lambda self: {**a.attrs, "type": "NOVY TYP"})
    n0 = w.undo.count()
    QTest.mouseDClick(w.view.viewport(), Qt.LeftButton, Qt.NoModifier, vp(w, a.x, a.y))
    assert a.attrs.get("type") != "NOVY TYP"  # dialog až po doběhnutí události
    pump(app)
    assert a.attrs["type"] == "NOVY TYP"
    assert w.undo.count() == n0 + 1  # jedno makro
    w.undo.undo()
    assert a.attrs.get("type", "") != "NOVY TYP"
    assert b.attrs.get("type", "") != "NOVY TYP"


def test_double_click_switchboard_emits(app, win, monkeypatch):
    p = Project(name="SB")
    blk = Element("fve.switchboard", 100, 100, attrs={"ref": "R1", "desc": "AC"})
    p.sheets[0].elements.append(blk)
    w = win(p)
    monkeypatch.setattr(w, "_choose_template", lambda sheet: False)  # jinak modální dialog šablony
    got = []
    w.scene.open_switchboard.connect(got.append)
    tabs0 = w.tabs.count()
    QTest.mouseDClick(w.view.viewport(), Qt.LeftButton, Qt.NoModifier, vp(w, 100, 100))
    assert got == [blk.id]
    pump(app)
    assert w.tabs.count() == tabs0 + 1


def test_rubber_band_select_and_delete(app, win):
    p, a, b = two_elements()
    p.sheets[0].wires.append(Wire(WireEnd(a.id, "2"), WireEnd(b.id, "1")))
    w = win(p)
    sc, view = w.scene, w.view
    port = view.viewport()
    # tažení z prázdné plochy (vlevo nahoře) přes oba prvky
    s = vp(w, 30, 190)
    e = vp(w, 175, 115)
    QTest.mousePress(port, Qt.LeftButton, Qt.NoModifier, s)
    QTest.mouseMove(port, vp(w, 100, 150))
    QTest.mouseMove(port, e)
    QTest.mouseRelease(port, Qt.LeftButton, Qt.NoModifier, e)
    sel = {it.element.id for it in sc.selectedItems() if hasattr(it, "element")}
    assert sel == {a.id, b.id}

    n0 = w.undo.count()
    QTest.keyClick(view, Qt.Key_Delete)
    assert w.undo.count() == n0 + 1
    assert not sc.sheet.elements and not sc.sheet.wires
    assert not sc.element_items and not sc.wire_items
    w.undo.undo()
    assert len(sc.sheet.elements) == 2 and len(sc.sheet.wires) == 1
    assert len(sc.element_items) == 2 and len(sc.wire_items) == 1


def test_bends_follow_moved_element_and_segment_drag(app, win):
    from envocad.model.routing import wire_route
    p, a, b = two_elements()
    b.y = 120.0
    s = p.sheets[0]
    wire = Wire(WireEnd(a.id, "2"), WireEnd(b.id, "1"), points=[(110.0, 150.0), (110.0, 120.0)])
    s.wires.append(wire)
    w = win(p)
    sc, view = w.scene, w.view
    port = view.viewport()
    start, end = vp(w, a.x, a.y), vp(w, a.x, a.y + 20)
    QTest.mousePress(port, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(port, vp(w, a.x, a.y + 10))
    QTest.mouseMove(port, end)
    QTest.mouseRelease(port, Qt.LeftButton, Qt.NoModifier, end)
    # lom u posunutého konce šel s prvkem nahoru, trasa je dál pravoúhlá
    assert wire.points[0] == pytest.approx((110.0, a.y)) and a.y == pytest.approx(170, abs=1.5)
    pts = wire_route(p, s, w.library, wire)
    assert all(abs(x1 - x2) < 1e-6 or abs(y1 - y2) < 1e-6 for (x1, y1), (x2, y2) in __import__("itertools").pairwise(pts))
    w.undo.undo()
    assert wire.points == [(110.0, 150.0), (110.0, 120.0)]
    # svislý úsek x=110 chytit a posunout doprava o 10 mm
    pts = wire_route(p, s, w.library, wire)
    i = next(k for k, (q, r) in enumerate(__import__("itertools").pairwise(pts)) if abs(q[0] - 110) < 1e-6 and abs(r[0] - 110) < 1e-6)
    y_mid = (pts[i][1] + pts[i + 1][1]) / 2
    n0 = w.undo.index()
    QTest.mousePress(port, Qt.LeftButton, Qt.NoModifier, vp(w, 110, y_mid))
    QTest.mouseMove(port, vp(w, 115, y_mid))
    QTest.mouseMove(port, vp(w, 120, y_mid))
    QTest.mouseRelease(port, Qt.LeftButton, Qt.NoModifier, vp(w, 120, y_mid))
    assert w.undo.index() == n0 + 1 and (a.x, a.y) == (60, 150)
    assert type(w.undo.command(n0)).__name__ == "SetWirePointsCommand"
    assert any(abs(x - 120) < 1e-6 for x, _ in wire.points)
    sc.clearSelection()
    sc.wire_items[wire.id].setSelected(True)
    assert sc.straighten_selected() == 1 and wire.points == []


def test_parallel_auto_wires_keep_distance():
    from envocad.library.store import LibraryStore
    from envocad.model.routing import route_sheet, wire_overlaps
    lib = LibraryStore()
    p = Project()
    s = p.sheets[0]
    # jako RDC1 → RDC2 posunutý nahoru: Z-trasy se stejným lomem by vedly přes sebe
    srcs = [Element("fve.breaker_mcb", 50, 150 - 10 * k, attrs={"ref": f"A{k}"}) for k in range(4)]
    dsts = [Element("fve.breaker_mcb", 120, 170 - 10 * k, attrs={"ref": f"B{k}"}) for k in range(4)]
    s.elements += srcs + dsts
    pa, pb = "2", "1"
    for a_, b_ in zip(srcs, dsts):
        s.wires.append(Wire(WireEnd(a_.id, pa), WireEnd(b_.id, pb)))
    routes = route_sheet(p, s, lib)
    assert not wire_overlaps(s, routes)
