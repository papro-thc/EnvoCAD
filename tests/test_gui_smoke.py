"""Smoke test GUI – běží s QT_QPA_PLATFORM=offscreen."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Wire, WireEnd
from envocad.ui.canvas import Mode
from envocad.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _project():
    p = Project(name="Smoke")
    s = p.sheets[0]
    g = Element("fve.pv_string", 30, 150, attrs={"ref": "G1", "p_string": "20 kWp"})
    q = Element("fve.dc_disconnect", 70, 152.5, attrs={"ref": "Q1"})
    t = Element("fve.inverter", 120, 150, attrs={"ref": "T1", "p_ac": "50 kW"})
    f = Element("fve.breaker_mcb", 170, 150, attrs={"ref": "F1", "in_": "80 A"})
    n = Element("fve.grid", 220, 150, attrs={"ref": ""})
    s.elements += [g, q, t, f, n]
    s.wires += [
        Wire(WireEnd(g.id, "DC+"), WireEnd(q.id, "1"), attrs={"ref": "W1"}),
        Wire(WireEnd(q.id, "2"), WireEnd(t.id, "DC+")),
        Wire(WireEnd(t.id, "AC"), WireEnd(f.id, "1"), attrs={"ref": "W2"}),
        Wire(WireEnd(f.id, "2"), WireEnd(n.id, "1")),
    ]
    return p


def test_window_and_commands(app, tmp_path):
    lib = LibraryStore(tmp_path / "lib.db")
    win = MainWindow(library=lib, project=_project())
    win.show()
    app.processEvents()
    sc = win.scene
    sc.ask_attributes = False
    assert len(sc.element_items) == 5 and len(sc.wire_items) == 4

    # vložení symbolu přes režim PLACE
    sc.start_place("fve.meter")
    assert sc.mode == Mode.PLACE
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent
    ev = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.GraphicsSceneMousePress)
    ev.setScenePos(QPointF(200, -100))
    ev.setButton(Qt.LeftButton)
    sc.mousePressEvent(ev)
    assert len(sc.sheet.elements) == 6
    new = sc.sheet.elements[-1]
    assert new.ref == "P1" and (new.x, new.y) == (200, 100)
    sc.set_mode(Mode.SELECT)

    # rotace + undo
    sc.element_items[new.id].setSelected(True)
    sc.rotate_selected()
    assert new.rotation == 90
    win.undo.undo()
    assert new.rotation == 0
    win.undo.undo()  # vrátí vložení
    assert len(sc.sheet.elements) == 5
    win.undo.redo()
    assert len(sc.sheet.elements) == 6

    # změna atributu přes panel
    sc.set_attr(new.id, False, "type", "DTS 353")
    assert sc.sheet.element(new.id).attrs["type"] == "DTS 353"

    # smazání včetně vodičů
    sc.clearSelection()
    t = next(e for e in sc.sheet.elements if e.ref == "T1")
    sc.element_items[t.id].setSelected(True)
    sc.delete_selected()
    assert len(sc.sheet.wires) == 2 and len(sc.wire_items) == 2
    win.undo.undo()
    assert len(sc.sheet.wires) == 4 and len(sc.wire_items) == 4

    # export PDF
    from envocad.export.pdf_export import export_scene_pdf
    out = tmp_path / "s.pdf"
    export_scene_pdf(sc, out)
    assert out.stat().st_size > 1000 and out.read_bytes()[:4] == b"%PDF"

    # uložení
    win.project.path = tmp_path / "s.ecp"
    assert win.save_project()
    assert {e.ref for e in Project.load(tmp_path / "s.ecp").sheets[0].elements} >= {"P1", "T1", "G1"}
    del QMouseEvent


def test_attr_dialog_and_wire_refs(app, tmp_path):
    from envocad.model.project import WIRE_ATTRIBUTES
    from envocad.ui.dialogs import AttrDialog, ElementDialog
    lib = LibraryStore(tmp_path / "lib.db")
    sym = lib.get_symbol("fve.inverter")
    d = ElementDialog(sym, {"ref": "T1", "p_ac": "50"})
    v = d.values()
    assert v["ref"] == "T1" and v["p_ac"] == "50" and "phases" in v
    d2 = AttrDialog(WIRE_ATTRIBUTES, {"ref": "W1", "cable": "CYKY 5x16"})
    assert d2.values()["cable"] == "CYKY 5x16"
    # číslování vodičů bere v úvahu existující W-označení
    p = _project()
    assert p.next_ref("W") == "W3"


def test_switchboard_tabs_and_layout(app, tmp_path):
    from envocad.library.templates import apply_template
    from envocad.ui.layout_view import LayoutView, SetPlacementCommand
    lib = LibraryStore(tmp_path / "lib.db")
    p = Project(name="SB")
    block = Element("fve.switchboard", 100, 100, attrs={"ref": "R1", "desc": "AC"})
    p.sheets[0].elements.append(block)
    win = MainWindow(library=lib, project=p)
    win.show()
    app.processEvents()
    assert win.tabs.count() == 1
    # založení listu rozvaděče bez dialogu šablony (šablonu vložíme přímo)
    sheet = p.create_switchboard_sheet(block)
    apply_template(p, sheet, "ac_fve", {"n_out": "4"})
    win.open_sheet(sheet, "schematic")
    win.open_sheet(sheet, "layout")
    assert win.tabs.count() == 3 and isinstance(win.view, LayoutView)
    lsc = win.view.scene()
    assert lsc.items_by_id
    # posun přístroje přes undo příkaz
    eid = next(iter(lsc.items_by_id))
    old = lsc.sheet.layout.placement(eid)
    win.undo.push(SetPlacementCommand(lsc, eid, (old.row, old.pos), (1, 2.0)))
    assert lsc.sheet.layout.placement(eid).row == 1
    win.undo.undo()
    assert lsc.sheet.layout.placement(eid).row == old.row
    # znovuotevření existující záložky nevytvoří novou
    win.open_sheet(sheet, "layout")
    assert win.tabs.count() == 3
    # uložení a načtení zachová list rozvaděče
    p.path = tmp_path / "sb.ecp"
    assert win.save_project()
    q = Project.load(p.path)
    assert len(q.switchboards()) == 1 and q.switchboards()[0].parent_element_id == block.id


def test_deferred_place_dialog(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    from envocad.ui import dialogs
    lib = LibraryStore(tmp_path / "lib.db")
    win = MainWindow(library=lib, project=Project())
    win.show()
    sc = win.scene
    monkeypatch.setattr(dialogs.ElementDialog, "exec", lambda self: dialogs.ElementDialog.Accepted)
    sc.start_place("fve.fuse")
    ev = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.GraphicsSceneMousePress)
    ev.setScenePos(QPointF(50, -50))
    ev.setButton(Qt.LeftButton)
    sc.mousePressEvent(ev)
    assert len(sc.sheet.elements) == 0  # dialog je odložený
    for _ in range(5):
        app.processEvents()
    assert len(sc.sheet.elements) == 1 and sc.sheet.elements[0].ref == "F1"


def test_properties_panel_edit_during_focus_loss(app, tmp_path):
    """Úprava v panelu + okamžitá přestavba panelu nesmí sahat na smazané widgety."""
    from PySide6.QtWidgets import QLineEdit
    lib = LibraryStore(tmp_path / "lib.db")
    win = MainWindow(library=lib, project=_project())
    win.show()
    app.processEvents()
    sc = win.scene
    t = next(it for it in sc.element_items.values() if it.element.ref == "T1")
    t.setSelected(True)
    app.processEvents()
    edits = win.props_panel.findChildren(QLineEdit)
    assert edits
    ed = edits[1]  # "type"
    ed.setText("STP 50")
    ed.editingFinished.emit()      # simulace ztráty fokusu
    win.props_panel.show_item(None)  # a okamžitá přestavba panelu (jako při přepnutí záložky)
    for _ in range(5):
        app.processEvents()
    assert sc.sheet.element(t.element.id).attrs["type"] == "STP 50"


def test_enclosure_dialog(app, tmp_path):
    from envocad.model.project import Sheet
    from envocad.ui.dialogs import EnclosureDialog
    s = Sheet(kind="switchboard")
    d = EnclosureDialog(s)
    d.name.setText("Hager Volta VU48")
    d.rows.setValue(4)
    d._edits["width_mm"].setText("550")
    d._edits["ip"].setText("IP 44")
    lay = d.apply()
    assert lay.rows == 4 and lay.enclosure == "Hager Volta VU48" and lay.params["ip"] == "IP 44" and lay.width_mm == 550
    assert "modulů" in d.info.text()


def test_component_picker_and_apply(app, tmp_path):
    from envocad.ui.component_picker import ComponentPicker
    from envocad.ui.dialogs import ElementDialog
    lib = LibraryStore(tmp_path / "lib.db")
    pk = ComponentPicker(lib, symbol_id="fve.breaker_mcb", preset_filters={"in_": "16", "poles": "3", "char": "B"})
    assert pk.table.rowCount() >= 1
    assert all(c.num("in_") == 16 and c.params.get("poles") == "3" for c in pk._rows)
    comp = pk.current()
    sym = lib.get_symbol("fve.breaker_mcb")
    d = ElementDialog(sym, {"ref": "F1"}, library=lib)
    d.apply_component(comp)
    v = d.values()
    assert v["type"] == comp.part_number and v["in_"] == "16" and v["poles"] == "3" and d.component_id == comp.id
    # skříň z knihovny
    from envocad.model.project import Sheet
    from envocad.ui.dialogs import EnclosurePanel
    s = Sheet(kind="switchboard")
    EnclosurePanel(s, library=lib)
    enc = ComponentPicker(lib, category="enclosure")
    assert enc.table.rowCount() >= 1 and all(c.category == "enclosure" for c in enc._rows)


def test_plugins_and_user_library(app, tmp_path, monkeypatch):
    monkeypatch.setenv("ENVOCAD_HOME", str(tmp_path))
    from envocad.library.store import LibraryStore, user_library_dir
    from envocad.plugins import plugin_dirs
    # uživatelský balíček knihovny: symbol + artikl
    ud = user_library_dir() / "muj_balicek"
    ud.mkdir(parents=True)
    (ud / "user.test.json").write_text('{"id":"user.test","name":"Můj symbol","category":"Moje","primitives":[{"type":"circle","cx":0,"cy":0,"r":2.5}],"ports":[{"name":"1","x":0,"y":2.5,"dir":"N"}],"attributes":[]}', encoding="utf-8")
    (ud / "moje.csv").write_text("id;manufacturer;part_number;name;category;symbol_id;datasheet_url;source\nx-1;X;1;Test;mcb;fve.breaker_mcb;;user\n", encoding="utf-8")
    # plugin
    (plugin_dirs()[1] / "hello.py").write_text("def register(ctx):\n    ctx.add_menu_action('Nástroje', 'Ahoj', lambda w: None)\n    ctx.add_importer('Import X…', lambda w: None)\n", encoding="utf-8")
    lib = LibraryStore()  # výchozí DB v ENVOCAD_HOME → načte i uživatelský balíček
    assert lib.get_symbol("user.test").name == "Můj symbol"
    assert lib.component("x-1") is not None
    win = MainWindow(library=lib, project=Project())
    assert "hello" in win.plugins.loaded and "example_counts" in win.plugins.loaded
    titles = [a.text() for m in win.menuBar().findChildren(type(win.menuBar().actions()[0].menu())) for a in m.actions()]
    assert "Ahoj" in titles and "Import X…" in titles and "Statistika projektu" in titles


def test_multipole_view_and_terminals(app, tmp_path):
    from envocad.ui.multipole_view import ConductorItem, MultipoleView, PoleItem
    p = _project()
    s = p.sheets[0]
    s.wires[2].conductors = ["L1", "L2", "L3", "N", "PE"]
    s.wires[3].conductors = ["L1", "L2", "L3", "N", "PE"]
    s.element(s.elements[3].id).attrs["poles"] = "3"
    w = MainWindow(LibraryStore(), p)
    w.open_multipole()
    assert isinstance(w.view, MultipoleView)
    sc = w.view.scene()
    poles = [it for it in sc.items() if isinstance(it, PoleItem)]
    conds = [it for it in sc.items() if isinstance(it, ConductorItem)]
    # F1 (3p) = 3 póly, ostatní prvky po jednom; žíly: 1 + 1 + 5 + 5
    assert sum(1 for it in poles if it.element.ref == "F1") == 3
    assert len(conds) == 12
    # svorky přes příkaz na JPS scéně → vícepól se přestaví a ukáže je
    jps = w._jps_scene(s)
    from envocad.ui import commands
    w.undo.push(commands.SetTerminalsCommand(jps, s.wires[2].id, {}, {"L1": {"a": "T1:L1", "b": "F1:1"}}))
    assert s.wires[2].terminals["L1"]["b"] == "F1:1"
    w.undo.undo()
    assert s.wires[2].terminals == {}
    w.undo.redo()
    # změna žil přes příkaz → počet čar se změní
    w.undo.push(commands.SetConductorsCommand(jps, s.wires[3].id, s.wires[3].conductors, ["L1", "N"]))
    conds = [it for it in sc.items() if isinstance(it, ConductorItem)]
    assert len(conds) == 9
    # automatické číslování na listu rozvaděče ze šablony
    from envocad.library.templates import apply_template
    blk = Element("fve.switchboard", 260, 150, attrs={"ref": "R1"})
    s.elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve")
    w.open_sheet(sb, "schematic")
    n = w.scene.auto_number_terminals()
    assert n > 0 and any(w_.terminals for w_ in sb.wires)
    w.open_sheet(sb, "multipole")
    assert w.tabs.tabText(w.tabs.currentIndex()).endswith("vícepól")
    # export PDF vícepólu
    from envocad.export.pdf_export import export_scene_pdf
    out = tmp_path / "mp.pdf"
    export_scene_pdf(w.view.scene(), out)
    assert out.stat().st_size > 500
    w.undo.setClean()
    w.close()
