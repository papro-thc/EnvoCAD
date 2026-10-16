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
        Wire(WireEnd(g.id, "DC"), WireEnd(q.id, "1"), attrs={"ref": "W1"}),
        Wire(WireEnd(q.id, "2"), WireEnd(t.id, "DC1")),
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
    apply_template(p, sheet, "ac_fve", {"n_out": "4", "distribution": "terminals"})
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
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    w.open_sheet(sb, "schematic")
    n = w.scene.auto_number_terminals()
    assert n > 0 and any(w_.terminals for w_ in sb.wires)
    w.open_sheet(sb, "multipole")
    assert w.tabs.tabText(w.tabs.currentIndex()).endswith("schéma")  # schéma rozvaděče = vícepól
    # export PDF vícepólu
    from envocad.export.pdf_export import export_scene_pdf
    out = tmp_path / "mp.pdf"
    export_scene_pdf(w.view.scene(), out)
    assert out.stat().st_size > 500
    w.undo.setClean()
    w.close()


def test_strip_dialog_and_bridges(app, tmp_path):
    from envocad.library.templates import apply_template
    from envocad.ui.dialogs import StripDialog
    from envocad.ui.multipole_view import BridgeItem
    p = Project(name="Svorky")
    s = p.sheets[0]
    blk = Element("fve.switchboard", 100, 150, attrs={"ref": "R1"})
    s.elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    assert "X2" in sb.bridges and len(sb.bridges["X2"]) == 5
    w = MainWindow(LibraryStore(), p)
    w.open_sheet(sb, "schematic")
    dlg = StripDialog(p, sb, w, "X2")
    assert dlg.strip.currentText() == "X2" and dlg.table.rowCount() == 20
    assert dlg.table.item(0, 4).text() == "1-6-11-16"
    dlg.bridges.setPlainText("1-6\n2-7-12")
    strip, groups = dlg.values()
    assert strip == "X2" and groups == [["1", "6"], ["2", "7", "12"]]
    from envocad.ui import commands
    w.undo.push(commands.SetBridgesCommand(p, sb, strip, p.bridge_groups(strip, sb), groups))
    assert p.bridge_groups("X2", sb) == groups
    w.open_sheet(sb, "multipole")
    assert len([it for it in w.view.scene().items() if isinstance(it, BridgeItem)]) == 2
    w.undo.undo()
    assert len(p.bridge_groups("X2", sb)) == 5
    # výkaz svorkovnice obsahuje můstky a čísla ze skupin svorek
    from envocad.export import reports
    _, rows = reports.terminals(p, w.library, sb)
    x2 = [r for r in rows if r[0] == "X2"]
    assert any(r[1] == "7" and r[5] == "2-7-12-17" for r in x2), x2[:5]
    w.undo.setClean()
    w.close()


def test_terminal_plan_view_and_pdf(app, tmp_path):
    from envocad.library.templates import apply_template
    from envocad.ui.terminal_plan_view import TerminalPlanView
    p = Project(name="Plán")
    s = p.sheets[0]
    t = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    s.elements += [t, blk]
    s.wires.append(Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "1"), attrs={"ref": "W2", "cable": "CYKY-J 5x16"},
                        conductors=["L1", "L2", "L3", "N", "PE"]))
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    w = MainWindow(LibraryStore(), p)
    w.open_sheet(sb, "terminals")
    assert isinstance(w.view, TerminalPlanView)
    sc = w.view.scene()
    assert [pl.strip for pl in sc.plans][:2] == ["X1", "X2"] and sc.plans[0].rows[0].external == "T1:AC"
    from envocad.export.pdf_export import export_scene_pdf
    out = tmp_path / "plan.pdf"
    export_scene_pdf(sc, out)
    assert out.stat().st_size > 500
    w.undo.setClean()
    w.close()


def test_multipole_move_and_reset(app, tmp_path):
    from envocad.library.templates import apply_template
    from envocad.ui import commands
    from envocad.ui.multipole_view import PoleItem
    p = Project(name="Posun")
    s = p.sheets[0]
    blk = Element("fve.switchboard", 100, 150, attrs={"ref": "R1"})
    s.elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    w = MainWindow(LibraryStore(), p)
    w.open_sheet(sb, "multipole")
    sc = w.view.scene()
    f2 = next(e for e in sb.elements if e.ref == "F2")
    auto = sc.layout_pos[f2.id]
    new = (auto[0] + 21.5, 120.0)  # na mřížce 2,5 mm
    w.undo.push(commands.MoveMultipoleCommand(sc, {f2.id: (None, new)}))
    assert f2.mp_pos == new
    it = next(it for it in sc.items() if isinstance(it, PoleItem) and it.element is f2)
    assert it.element_origin() == new
    sc.reset_layout()
    assert f2.mp_pos is None
    w.undo.undo()
    assert f2.mp_pos == new
    # líná přestavba: při změně modelu na jiné záložce se vícepól přestaví až po přepnutí
    w.open_sheet(sb, "schematic")
    w.scene.set_attr(f2.id, False, "in_", "25")
    assert getattr(w._unwrap(w.tabs.widget(w._find_tab(sb, "multipole"))), "_dirty", False)
    w.open_sheet(sb, "multipole")
    assert not getattr(w.view, "_dirty", False)
    w.undo.setClean()
    w.close()


def test_switchboard_opens_as_multipole_and_delete(app, tmp_path, monkeypatch):
    from envocad.ui.multipole_view import MultipoleView, PoleItem
    p = Project(name="RH")
    s = p.sheets[0]
    blk = Element("fve.switchboard", 100, 150, attrs={"ref": "RH"})
    s.elements.append(blk)
    w = MainWindow(LibraryStore(), p)
    monkeypatch.setattr(MainWindow, "_choose_template", lambda self, sheet: (
        __import__("envocad.library.templates", fromlist=["apply_template"]).apply_template(p, sheet, "ac_fve", {"distribution": "terminals"}) or True))
    w._open_switchboard_now(blk.id, "schematic")
    assert isinstance(w.view, MultipoleView) and w.tabs.tabText(w.tabs.currentIndex()) == "RH – schéma"
    sb = w.view.scene().sheet
    assert w._find_tab(sb, "schematic") < 0  # jednopólový editor se neotvírá automaticky
    f2 = next(e for e in sb.elements if e.ref == "F2")
    sc = w.view.scene()
    for it in sc.items():
        if isinstance(it, PoleItem) and it.element is f2:
            it.setSelected(True)
    n_before = len(sb.elements)
    sc.delete_requested.emit([f2.id], [])
    assert len(sb.elements) == n_before - 1 and isinstance(w.view, MultipoleView)
    w.undo.undo()
    assert len(sb.elements) == n_before
    w.undo.setClean()
    w.close()


def test_block_ports_refresh_without_moving(app, tmp_path, monkeypatch):
    """Po založení listu rozvaděče se blok v JPS přestaví hned (bez posunu)."""
    p = Project(name="Blok")
    s = p.sheets[0]
    t = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    s.elements += [t, blk]
    s.wires.append(Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "1"), attrs={"ref": "W2"}))
    w = MainWindow(LibraryStore(), p)
    jps = w.scene
    assert [pt.name for pt in jps.element_items[blk.id].symbol.ports] == ["1", "2", "3", "4"]
    monkeypatch.setattr(MainWindow, "_choose_template", lambda self, sheet: (
        __import__("envocad.library.templates", fromlist=["apply_template"]).apply_template(p, sheet, "ac_fve", {"distribution": "terminals"}),
        self._rebuild_sheet_views(sheet))[1] or True)
    w._open_switchboard_now(blk.id, "schematic")
    assert [pt.name for pt in jps.element_items[blk.id].symbol.ports] == ["X1", "X4", "X5", "X6"]
    assert s.wires[0].b.port == "X1"
    w.undo.setClean()
    w.close()


def test_navigator_and_goto(app, tmp_path):
    p = _project()
    s = p.sheets[0]
    w = MainWindow(LibraryStore(), p)
    w.nav_panel.refresh()
    assert w.nav_panel.tree.topLevelItemCount() == 1 and w.nav_panel.tree.topLevelItem(0).childCount() >= 5
    f1 = next(e for e in s.elements if e.ref == "F1")
    w.goto_target(s.id, f1.id, False)
    assert [it.element.id for it in w.scene.selectedItems() if hasattr(it, "element")] == [f1.id]
    w.nav_panel.filter.setText("W2")
    w.nav_panel.refresh()
    top = w.nav_panel.tree.topLevelItem(0)
    assert top.childCount() == 1 and top.child(0).text(0) == "W2"
    from envocad.model.checks import check_project
    from envocad.ui.navigator import ChecksDialog
    dlg = ChecksDialog(check_project(p, w.library), w)
    assert dlg.tree.topLevelItemCount() >= 1
    w.undo.setClean()
    w.close()


def test_documentation_pdf(app, tmp_path):
    from envocad.export.doc_pdf import DocBuilder, export_documentation_pdf
    from envocad.library.templates import apply_template
    p = _project()
    p.meta.update(investor="Investor a.s.", order="2026-042", changes="0 | 15.10.2026 | první vydání | PR")
    s = p.sheets[0]
    blk = Element("fve.switchboard", 260, 150, attrs={"ref": "R1"})
    s.elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    b = DocBuilder(p, LibraryStore())
    b.plan()
    kinds = [k for k, _, _ in b.pages]
    assert kinds[:2] == ["title", "toc"] and kinds[-1] == "changes" and kinds.count("sheet") == 3
    out = tmp_path / "dok.pdf"
    n = export_documentation_pdf(p, LibraryStore(), out)
    assert n >= len(b.pages) and out.stat().st_size > 5000


def test_autosave_recent_and_a4(app, tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("ENVOCAD_HOME", str(tmp_path / "home"))
    p = _project()
    w = MainWindow(LibraryStore(), p)
    w._settings().setValue("files/recent", [])
    # autosave jen když je co ukládat
    w.autosave()
    assert not list((tmp_path / "home").glob("autosave/*.ecp"))
    f1 = next(e for e in p.sheets[0].elements if e.ref == "F1")
    w.scene.set_attr(f1.id, False, "in_", "63")
    w.autosave()
    files = list((tmp_path / "home" / "autosave").glob("*.autosave.ecp"))
    assert len(files) == 1 and p.path is None
    # uložení projekt → autosave pryč, poslední projekty
    p.path = tmp_path / "proj.ecp"
    assert w.save_project()
    assert not list((tmp_path / "home" / "autosave").glob("*.autosave.ecp"))
    assert w._recent()[0].endswith("proj.ecp") and not w.m_recent.isEmpty()
    # PDF na A4
    from envocad.export.pdf_export import export_scene_pdf
    out = tmp_path / "a4.pdf"
    export_scene_pdf(w.scene, out, paper="A4")
    assert out.stat().st_size > 500
    # QR v rámečku
    from envocad.model.frame import frame_geometry
    assert frame_geometry(p, p.sheets[0]).rects
    w.undo.setClean()
    w.close()
    os.environ.pop("ENVOCAD_HOME", None)


def test_wizard_spec_dc_boxes(app):
    from envocad.generate import build_project
    from envocad.ui.dialogs import ProjectWizard
    d = ProjectWizard()
    d.strings.setText("20,20; 18")
    d.dc_route_boxes.setText("2")
    spec = d.spec()
    assert spec["dc"]["route_boxes"] == 2 and spec["dc"]["tech_box"] is True and spec["dc"]["disconnect"] is False
    p = build_project(spec)
    assert len([s for s in p.sheets if s.is_switchboard]) == 2 * 3 + 1
    d.dc_tech_box.setChecked(False)
    d.dc_route_boxes.setText("0")
    spec = d.spec()
    assert spec["dc"]["disconnect"] is True
    p = build_project(spec)
    assert len([s for s in p.sheets if s.is_switchboard]) == 1
    assert any(e.symbol_id == "fve.dc_disconnect" for e in p.sheets[0].elements)


def test_macro_insert_and_branch_gui(app):
    from PySide6.QtCore import QPointF

    from envocad.library.macros import list_macros
    from envocad.model.project import Element, Project, Wire, WireEnd
    from envocad.ui.canvas import Mode
    from envocad.ui.main_window import MainWindow
    p = Project(name="Makra")
    s = p.sheets[0]
    a = Element("fve.breaker_mcb", 100, 200, attrs={"ref": "F1"})
    b = Element("fve.breaker_mcb", 200, 200, attrs={"ref": "F2"})
    s.elements += [a, b]
    s.wires.append(Wire(WireEnd(a.id, "2"), WireEnd(b.id, "1"), conductors=["L1", "N", "PE"], attrs={"ref": "W1"}))
    w = MainWindow(LibraryStore(), p)
    w.open_sheet(s, "schematic")
    sc = w.view.scene()
    # T-odbočka: klik na vodič v režimu kreslení vodiče rozdělí vodič uzlem
    sc.set_mode(Mode.WIRE)
    hit = sc._branch_at(QPointF(150, -200))
    assert hit is not None and hit[0].element.symbol_id == "sb.junction"
    assert len(s.wires) == 2 and any(e.symbol_id == "sb.junction" for e in s.elements)
    w.undo.undo()
    assert len(s.wires) == 1 and not any(e.symbol_id == "sb.junction" for e in s.elements)
    # makro z knihovny se vloží doprostřed pohledu
    sc.set_mode(Mode.SELECT)
    m = next(x for x in list_macros() if x.name.startswith("String"))
    w.insert_macro(str(m.path))
    assert len(s.elements) == 4 and len(s.wires) == 2
    w.undo.undo()
    assert len(s.elements) == 2
    w.undo.setClean()
    w.close()


def test_multipole_pagination(app):
    import tempfile
    from pathlib import Path

    from PySide6.QtGui import QUndoStack

    from envocad.export.pdf_export import export_scene_pdf
    from envocad.generate import build_project
    from envocad.ui.multipole_view import MultipoleScene, PageBreakItem
    spec = {"name": "Velká", "inverters": [{"ref": "T1", "p_ac": 100, "mppt": 6, "u_dc_max": 1100, "u_mppt_min": 200,
                                           "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [20] * 12}], "dc": {"route_boxes": 0}}
    p = build_project(spec)
    sc = MultipoleScene(p, p.sheets[1], LibraryStore(), QUndoStack())
    assert len(sc.pages) == 3 and set(sc.page_of.values()) == {0, 1, 2}
    # prvky nepřesahují okraj své strany
    for e in p.sheets[1].elements:
        k = sc.page_of[e.id]
        assert sc.page_index_at(sc.layout_pos[e.id][1] - k * sc.page_pitch) == k
    breaks = [it for it in sc.items() if isinstance(it, PageBreakItem)]
    assert breaks and any(it.text.startswith("/2.2.") for it in breaks) and any(it.text.startswith("/2.1.") for it in breaks)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "mp.pdf"
        export_scene_pdf(sc, out)
        assert out.stat().st_size > 5000


def test_edit_in_switchboard_schematic(app):
    """Ve schématu rozvaděče (vícepól) jde vkládat prvky a kreslit žíly – i u vygenerovaného projektu."""
    from PySide6.QtCore import QPointF

    from envocad.generate import build_project
    from envocad.ui.canvas import Mode
    from envocad.ui.main_window import MainWindow
    from envocad.ui.multipole_view import MultipoleScene
    spec = {"name": "Edit", "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200,
                                          "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [20, 20]}]}
    p = build_project(spec)
    w = MainWindow(LibraryStore(), p)
    w._edit_element_anywhere = lambda *a, **k: None   # bez modálního dialogu
    sb = p.sheets[-1]
    w.open_sheet(sb, "multipole")
    sc = w.view.scene()
    assert isinstance(sc, MultipoleScene) and w.draw_scene is sc
    n0 = len(sb.elements)
    sc.start_place("fve.breaker_mcb")
    assert sc.mode == Mode.PLACE
    sc._place_at(QPointF(300, -100))
    assert len(sb.elements) == n0 + 1
    new = sb.elements[-1]
    assert new.mp_pos == (300.0, 100.0) and new.rotation == 270 and new.ref.startswith("F")
    # žíla z konce pólu existujícího vývodu na nový jistič
    sc.set_mode(Mode.SELECT)
    sc.rebuild()
    out = next(e for e in sb.elements if e.ref == "XOUT")
    ep = sc._poles[out.id]
    x, y = ep.pole_pos(ep.symbol.ports[0].name, ep.slots[0])
    sc.start_wire()
    sc._wire_click(QPointF(x, -y))
    ep2 = sc._poles[new.id]
    x2, y2 = ep2.pole_pos(ep2.symbol.ports[0].name, "")
    nw = len(sb.wires)
    sc._wire_click(QPointF(x2, -y2))
    assert len(sb.wires) == nw + 1 and sb.wires[-1].conductors == [ep.slots[0]]
    w.undo.undo()
    assert len(sb.wires) == nw
    w.undo.setClean()
    w.close()


def test_feed_cable_tag_edit_and_move(app):
    """Štítek kabelu u přívodu: dvojklik otevře parametry přívodu, tažení posune celý přívod."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from envocad.generate import build_project
    from envocad.ui.main_window import MainWindow
    from envocad.ui.multipole_view import CableTagItem, PoleItem
    spec = {"name": "Tag", "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200,
                                         "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [20, 20]}]}
    p = build_project(spec)
    w = MainWindow(LibraryStore(), p)
    w.resize(1400, 900)
    w.show()
    calls = []
    w._edit_element_anywhere = lambda sh, eid: calls.append(eid)
    sb = p.sheets[-1]
    w.open_sheet(sb, "multipole")
    app.processEvents()
    w.view.zoom_fit()
    app.processEvents()
    sc = w.view.scene()
    x1 = next(e for e in sb.elements if e.ref == "X1")
    tag = next(it for it in sc.items() if isinstance(it, CableTagItem) and it.element_id == x1.id)
    vp = w.view.viewport()
    pt = w.view.mapFromScene(tag.sceneBoundingRect().center())
    QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, pt)
    QTest.qWait(30)
    app.processEvents()
    assert calls == [x1.id]

    def tag_pt():   # panel vlastností mění velikost pohledu → bod štítku přepočítat
        return w.view.mapFromScene(tag.sceneBoundingRect().center())

    def x1_poles():
        return sorted((it for it in sc.items() if isinstance(it, PoleItem) and it.element.id == x1.id),
                      key=lambda it: (it.scenePos().x(), it.scenePos().y()))

    # klik bez tažení: vybrané zůstanou všechny svorky přívodu, štítek zvýrazněný, vlastnosti ukazují X1
    shown = []
    sc.selection_info.connect(shown.append)
    poles = x1_poles()
    assert len(poles) > 1
    gap = app.styleHints().mouseDoubleClickInterval() + 50
    sc.clearSelection()
    QTest.qWait(gap)
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, tag_pt())
    app.processEvents()
    assert all(it.isSelected() for it in poles)
    assert {it.element.id for it in sc.selectedItems()} == {x1.id}
    assert tag.highlight
    assert shown and shown[-1] is not None and shown[-1].element.id == x1.id
    # Ctrl+klik přepne celý přívod
    QTest.qWait(gap)   # jinak by Qt dva kliky za sebou vzal jako dvojklik
    QTest.mouseClick(vp, Qt.LeftButton, Qt.ControlModifier, tag_pt())
    app.processEvents()
    assert not any(it.isSelected() for it in poles) and not tag.highlight
    QTest.qWait(gap)   # jinak by Qt dva kliky za sebou vzal jako dvojklik
    QTest.mouseClick(vp, Qt.LeftButton, Qt.ControlModifier, tag_pt())
    app.processEvents()
    assert all(it.isSelected() for it in poles) and tag.highlight

    # tažení posune celý přívod
    QTest.qWait(gap)
    before = [it.scenePos() for it in poles]
    pt = tag_pt()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, pt)
    QTest.mouseMove(vp, pt + QPoint(30, 30))
    QTest.mouseMove(vp, pt + QPoint(60, 60))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, pt + QPoint(60, 60))
    QTest.qWait(30)
    app.processEvents()
    assert x1.mp_pos is not None
    after = [it.scenePos() for it in x1_poles()]
    d = {(round(b.x() - a.x(), 3), round(b.y() - a.y(), 3)) for a, b in zip(before, after)}
    assert len(d) == 1 and d != {(0.0, 0.0)}
    w.undo.setClean()
    w.close()
