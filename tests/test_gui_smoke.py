"""Smoke test GUI – běží s QT_QPA_PLATFORM=offscreen."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from envocad.library.store import LibraryStore
from envocad.model.feed import is_feed_out
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
    assert w._recent() == []                   # QSettings testu jsou v tmp (conftest) – bez seznamu uživatele
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
    dc = [s.loc for s in p.sheets if s.loc.startswith(("RDC", "RFVE.DC"))]
    assert len(dc) == 2 * 2 + 1 and dc[-1] == "RFVE.DC"     # po trase na střídač + společný u technologie (F2)
    d.dc_tech_box.setChecked(False)
    d.dc_route_boxes.setText("0")
    spec = d.spec()
    assert spec["dc"]["disconnect"] is True
    p = build_project(spec)
    assert not [s for s in p.sheets if s.loc.startswith(("RDC", "RFVE.DC"))]
    assert any(e.symbol_id == "fve.dc_disconnect" for e in p.sheets[0].elements)
    # rodinný dům: jeden rozvaděč RFVE (DC + AC), přípojka VN nejde zvolit
    d.dc_tech_box.setChecked(True)
    d.conn_level.setCurrentIndex(1)
    d.building.setCurrentIndex(d.building.findData("house"))
    assert d.conn_level.currentData() == "nn" and not d.conn_level.isEnabled()
    spec = d.spec()
    assert spec["building"] == "house"
    p = build_project(spec)
    assert [s.loc for s in p.sheets if s.is_switchboard and s.loc.startswith("RFVE")] == ["RFVE"]


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
    # list rozvaděče na A4 na šířku: 3 stringy na stranu → 12 stringů na 4 strany
    assert sc.paper_size == (297.0, 210.0)
    assert len(sc.pages) == 4 and set(sc.page_of.values()) == {0, 1, 2, 3}
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


def test_structure_ui_and_revision_flow(app, monkeypatch, tmp_path):
    shot = tmp_path / "revision.png"
    from PySide6.QtWidgets import QMessageBox

    from envocad.model.diff import diff_projects
    from envocad.model.project import StructureId
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    p = _project()
    s = p.sheets[0]
    w = MainWindow(LibraryStore(), p)
    # popisek: bez overridu holý ref, s overridem plné označení; panel vlastností má řádky func/loc
    f1 = next(e for e in s.elements if e.ref == "F1")
    from envocad.model.designation import display_designation
    assert display_designation(s, f1) == "F1"
    w.goto_target(s.id, f1.id, False)
    w.props_panel.show_item(w.scene.element_items[f1.id])
    assert w.props_panel.form.rowCount() >= 3
    w.scene.set_attr(f1.id, False, "loc", "RS1")
    assert display_designation(s, f1) == "+RS1-F1"
    w.undo.undo()
    assert "loc" not in f1.attrs or not f1.attrs["loc"]
    # označení listu + registr, undo
    before = p.to_dict()
    assert w.set_sheet_designation(s, "AC", "RS1")
    assert (s.func, s.loc) == ("AC", "RS1") and p.structure("+", "RS1") is not None
    w.undo.undo()
    assert p.to_dict() == before
    w.undo.redo()
    w.set_structures([StructureId("+", "RS1", "Rozvaděč")])
    assert p.structure("+", "RS1").description == "Rozvaděč"
    # přejmenování ref bloku rozvaděče = přejmenování umístění
    from envocad.model.project import Element
    blk = Element("fve.switchboard", 300, 150, attrs={"ref": "RS1"})
    s.elements.append(blk)
    w.scene.add_element_item(blk)
    w.scene.set_attr(blk.id, False, "ref", "RS5")
    assert s.loc == "RS5" and p.structure("+", "RS5") is not None
    w.undo.undo()
    assert s.loc == "RS1" and blk.attrs["ref"] == "RS1"
    # revize: porovnání + uzavření jako undo příkazy, bez resetClean
    from envocad.model.project import Project as P
    old = P.from_dict(p.to_dict())
    f1.attrs["in_"] = "100 A"
    changes = diff_projects(old, p, w.library)
    assert changes
    w.undo.setClean()
    import copy
    snap = copy.deepcopy(p.to_dict())
    w.record_revision(changes, "B", "1.1.2026", "ENVO", "B | 1.1.2026 | test | ENVO")
    assert p.revisions[-1].label == "B" and p.revisions[-1].marks and not w.undo.isClean()
    assert w.close_open_revision(None) and p.revisions[-1].closed
    w.undo.undo()
    assert not p.revisions[-1].closed
    w.undo.undo()
    assert p.to_dict() == snap and w.undo.isClean()
    assert not w.close_open_revision(None)          # není otevřená revize → hláška, nic se neděje
    w.undo.redo()
    # značky ve výkresu: scéna je nakreslí (screenshot)
    w.scene.invalidate_text_layout()
    from envocad.model.revision import revision_geometry
    geom = revision_geometry(p, s, w.library)
    assert geom.polylines and geom.texts[0][2] == "B"
    pm = w.view.grab()
    assert not pm.isNull()
    assert pm.save(str(shot))
    w.undo.setClean()
    w.close()


def test_revision_labels_panel_codes_and_structures_note(app, monkeypatch):
    """Další označení revize v dialogu porovnání, odmítnutí označení uzavřené revize, func/loc v panelu velkými
    písmeny, upozornění v dialogu struktur."""
    from PySide6.QtWidgets import QLabel, QMessageBox

    from envocad.model.diff import diff_projects
    from envocad.model.revision import close_revision, open_revision
    from envocad.ui.dialogs import StructuresDialog
    from envocad.ui.navigator import DiffDialog
    from envocad.ui.panels import PropertiesPanel
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text, *a, **k: warned.append(text) or QMessageBox.Ok)
    p = _project()
    w = MainWindow(LibraryStore(), p)
    try:
        assert DiffDialog.default_label(p) == "1"                  # bez revizí → meta / „1“ jako dřív
        rev = open_revision(p, "A")
        assert DiffDialog.default_label(p) == "A"                  # otevřená revize
        close_revision(p, rev)
        dlg = DiffDialog([], p, w)
        assert dlg.rev.text() == "B"                               # po uzavřené revizi další označení
        dlg.rev.setText("A")
        dlg.accept()
        assert dlg.result() != DiffDialog.Accepted and warned and "uzavřená" in warned[-1]
        dlg.rev.setText("B")
        dlg.accept()
        assert dlg.result() == DiffDialog.Accepted
        # record_revision: označení uzavřené revize → hláška, projekt ani undo se nezmění
        from envocad.model.project import Project as P
        old = P.from_dict(p.to_dict())
        p.sheets[0].elements[0].attrs["desc"] = "změna"
        changes = diff_projects(old, p, w.library)
        snap, n = p.to_dict(), w.undo.count()
        assert not w.record_revision(changes, "A", "", "", "A | | x | ")
        assert p.to_dict() == snap and w.undo.count() == n and "uzavřená" in warned[-1]
        assert w.record_revision(changes, "B", "", "", "B | | x | ") and p.revisions[-1].label == "B"
        # panel vlastností: kód funkce/umístění ořezaný a velkými písmeny
        assert PropertiesPanel.normalize("loc", "  rh1 ") == "RH1"
        assert PropertiesPanel.normalize("func", "ac") == "AC"
        assert PropertiesPanel.normalize("desc", " text ") == " text "
        emitted = []
        panel = PropertiesPanel()
        panel.attr_edited.connect(lambda *a: emitted.append(a))
        panel._target = ("e1", False)
        panel._commit("loc", " rdc1 ")
        app.processEvents()
        assert emitted == [("e1", False, "loc", "RDC1")]
        # dialog struktur upozorní, že úprava kódu nepřejmenuje použití
        sd = StructuresDialog([], w)
        assert any("nepřejmenuje" in lb.text() for lb in sd.findChildren(QLabel))
    finally:
        w.undo.setClean()
        w.close()


def _mirror_project():
    p = Project(name="Zrcadlo")
    s = p.sheets[0]
    coil = Element("ctl.coil", 100, 150, attrs={"ref": "K1", "contacts": "1/2 3/4 5/6 13/14 21/22"})
    pw = Element("fve.contactor", 100, 100, attrs={"ref": "K1", "modules": "3"})
    no = Element("ctl.contact_no", 200, 150, attrs={"ref": "K1"})
    nc = Element("ctl.contact_nc", 250, 150, attrs={"ref": "K1"})
    s.elements += [coil, pw, no, nc]
    return p, coil


def test_contact_mirror_drawn_and_pdf(app, tmp_path):
    from PySide6.QtGui import QImage, QPainter, QUndoStack
    from PySide6.QtPrintSupport import QPrinter

    from envocad.ui.canvas import SchematicScene
    p, coil = _mirror_project()
    lib = LibraryStore(tmp_path / "lib.db")
    sc = SchematicScene(p, p.sheets[0], lib, QUndoStack())
    mirrors = sc.text_layout().mirrors
    assert coil.id in mirrors and mirrors[coil.id].lines
    r = sc.sceneRect()
    img = QImage(int(r.width() * 4), int(r.height() * 4), QImage.Format_ARGB32)
    img.fill(Qt.white)
    ptr = QPainter(img)
    sc.render(ptr)
    ptr.end()
    assert not img.isNull()
    # PDF: zrcadlo se kreslí v drawForeground → scene.render ho zahrne; počet kreslených čar roste s ním
    pdf = tmp_path / "m.pdf"
    pr = QPrinter(QPrinter.HighResolution)
    pr.setOutputFormat(QPrinter.PdfFormat)
    pr.setOutputFileName(str(pdf))
    ptr = QPainter(pr)
    sc.render(ptr)
    ptr.end()
    assert pdf.exists() and pdf.stat().st_size > 500
    text = "13/14"
    assert any(text in t[2] for t in mirrors[coil.id].texts)


def test_star_source_checkbox_undo(app, tmp_path):
    from PySide6.QtWidgets import QCheckBox
    p = Project(name="Hvezda")
    s = p.sheets[0]
    ip = Element("fve.interrupt", 50, 50, attrs={"ref": "A"})
    s.elements.append(ip)
    win = MainWindow(library=LibraryStore(tmp_path / "lib.db"), project=p)
    win.show()
    app.processEvents()
    sc = win.scene
    sc.element_items[ip.id].setSelected(True)
    app.processEvents()
    cb = next(c for c in win.props_panel.findChildren(QCheckBox) if c.text() == "Zdroj hvězdy")
    cb.setChecked(True)
    for _ in range(5):
        app.processEvents()
    assert sc.sheet.element(ip.id).attrs.get("star_source") == "1"
    sc.undo.undo()
    assert sc.sheet.element(ip.id).attrs.get("star_source", "") == ""
    sc.undo.redo()
    assert sc.sheet.element(ip.id).attrs.get("star_source") == "1"


def test_contacts_hint_and_layout_hides_coil(app, tmp_path):
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QLineEdit

    from envocad.ui.layout_view import LayoutScene
    p, coil = _mirror_project()
    lib = LibraryStore(tmp_path / "lib.db")
    coil.attrs["modules"] = "1"
    sw = p.sheets[0]
    sw.kind = "switchboard"
    ls = LayoutScene(p, sw, lib, QUndoStack())
    mods = {it.element.id for it in ls.items() if hasattr(it, "element")}
    assert coil.id not in mods and any(e.symbol_id == "fve.contactor" and e.id in mods for e in sw.elements)
    win = MainWindow(library=lib, project=p)
    win.show()
    app.processEvents()
    win.scene.element_items[coil.id].setSelected(True)
    app.processEvents()
    assert any("NO:11/14" in e.placeholderText() for e in win.props_panel.findChildren(QLineEdit))


def test_mirror_checkbox_undo(app, tmp_path):
    """Zaškrtávátko „Zobrazit zrcadlo kontaktů“ jen u hostitele zrcadla; přepíná atribut mirror ("0" / "") přes undo
    a zrcadlo zmizí/objeví se ve scéně."""
    from PySide6.QtWidgets import QCheckBox
    p = Project(name="Zrcadlo")
    s = p.sheets[0]
    coil = Element("ctl.coil", 100, 200, attrs={"ref": "K1"})
    contact = Element("ctl.contact_no", 250, 100, attrs={"ref": "K1"})
    lone = Element("fve.breaker_mcb", 300, 200, attrs={"ref": "F1"})
    s.elements += [coil, contact, lone]
    win = MainWindow(library=LibraryStore(tmp_path / "lib.db"), project=p)
    win.show()
    app.processEvents()
    sc = win.scene

    def boxes(eid):
        sc.clearSelection()
        sc.element_items[eid].setSelected(True)
        app.processEvents()
        return [c for c in win.props_panel.findChildren(QCheckBox) if c.text() == "Zobrazit zrcadlo kontaktů"]

    assert not boxes(lone.id) and not boxes(contact.id)          # jistič bez kontaktů, kontakt = bez zrcadla
    (cb,) = boxes(coil.id)
    assert cb.isChecked() and coil.id in sc.text_layout().mirrors
    cb.setChecked(False)
    for _ in range(5):
        app.processEvents()
    assert sc.sheet.element(coil.id).attrs.get("mirror") == "0"
    assert coil.id not in sc.text_layout().mirrors
    (cb,) = boxes(coil.id)                                        # zrcadlo potlačené, zaškrtávátko zůstává
    assert not cb.isChecked()
    sc.undo.undo()
    assert sc.sheet.element(coil.id).attrs.get("mirror", "") == ""
    assert coil.id in sc.text_layout().mirrors
    sc.undo.redo()
    assert sc.sheet.element(coil.id).attrs.get("mirror") == "0"
    # obraz bez kontaktů stačí (jistič s kontaktním obrazem = hostitel)
    lone.attrs["contacts"] = "13/14"
    sc.invalidate_text_layout()
    assert boxes(lone.id)


def _dc_macro():
    from envocad.library.macros import list_macros
    return next(x for x in list_macros() if x.name == "DC string v rozvaděči")


def _check_macro_insert(w, sheet, sc, lib, values):
    """Společná kontrola: žádné „{“, žádné when, jeden XPE, jedno undo = původní stav, redo znovu."""
    m = _dc_macro()
    before = sheet.to_dict()
    n = sc.insert_macro(m, values, (150, 150))
    assert n > 0
    for e in sheet.elements:
        assert "when" not in e.attrs
        assert not any("{" in str(v) for v in e.attrs.values()), e.attrs
    for wr in sheet.wires:
        assert not any("{" in str(v) for v in wr.attrs.values())
    assert len([e for e in sheet.elements if e.ref == "XPE"]) == 1
    assert len([e for e in sheet.elements if e.ref.startswith("FU")]) == 2
    after = sheet.to_dict()
    assert w.undo.undoText() == f"Vložit makro {m.name}"
    w.undo.undo()
    assert sheet.to_dict() == before
    w.undo.redo()
    assert sheet.to_dict() == after
    w.undo.undo()
    assert sheet.to_dict() == before


def test_macro_insert_with_values_undo(app):
    from envocad.model.project import Element, Project
    from envocad.ui.main_window import MainWindow
    lib = LibraryStore()
    m = _dc_macro()
    values, errs = __import__("envocad.library.macros", fromlist=["x"]).resolve_values(
        m, given={"n": "2", "fuse_in": "20"}, components=lib.component)
    assert not errs
    p = Project(name="Makro hodnoty")
    s = p.sheets[0]
    # XPE už v listu je (sdílený prvek se nesmí zdvojit a undo ho nesmí smazat)
    s.elements.append(Element("sb.feed", 10, 10, attrs={"dir": "out", "ref": "XPE"}))
    w = MainWindow(lib, p)
    w.open_sheet(s, "schematic")
    _check_macro_insert(w, s, w.view.scene(), lib, values)
    assert any(e.ref == "XPE" for e in s.elements)
    w.undo.setClean()
    w.close()
    # bez XPE v listu
    p2 = Project(name="Makro hodnoty 2")
    w2 = MainWindow(lib, p2)
    w2.open_sheet(p2.sheets[0], "schematic")
    _check_macro_insert(w2, p2.sheets[0], w2.view.scene(), lib, values)
    w2.undo.setClean()
    w2.close()


def test_macro_insert_in_multipole(app):
    from envocad.library.macros import resolve_values
    from envocad.model.project import Project
    from envocad.ui.main_window import MainWindow
    lib = LibraryStore()
    values, _ = resolve_values(_dc_macro(), given={"n": "2", "fuse_in": "20"}, components=lib.component)
    p = Project(name="Makro vícepól")
    sb = p.sheets[0]
    sb.kind = "switchboard"
    w = MainWindow(lib, p)
    w.open_sheet(sb, "multipole")
    sc = w.view.scene()
    _check_macro_insert(w, sb, sc, lib, values)
    sc.insert_macro(_dc_macro(), values, (150, 150))
    assert all(e.mp_pos is not None for e in sb.elements)
    w.undo.setClean()
    w.close()


def test_macro_values_dialog(app):
    from envocad.ui.dialogs import MacroValuesDialog
    lib = LibraryStore()
    m = _dc_macro()
    dlg = MacroValuesDialog(m, lib)
    assert dlg.value_set() is None and dlg.set_combo.count() == len(m.value_sets) + 1
    dlg.set_combo.setCurrentText("Pojistka 20 A gPV, SPD T1+T2")
    v = dlg.values()
    assert dlg.value_set() == "Pojistka 20 A gPV, SPD T1+T2"
    assert v["fuse_in"] == "20" and v["spd"] == "T1+T2" and not dlg.errors
    # povinná hodnota chybí → chyba, dialog zůstane otevřený
    dlg.set_combo.setCurrentIndex(0)
    dlg._fields["fuse_in"].setText("")
    dlg.show()
    dlg.accept()
    assert dlg.errors and dlg.isVisible() and dlg.error_label.isVisible()
    assert "povinná" in dlg.error_label.text()
    dlg._fields["fuse_in"].setText("16,0")
    dlg.accept()
    assert not dlg.errors and dlg.result() == 1 and dlg.values()["fuse_in"] == "16"


def test_macro_values_dialog_repeat_numbers_each_instance(app):
    """Nález 1: dialog → values() → insert_macro s n=3 dá FU1.1…FU1.3 a popisy G1…G3 (dřív všude 1);
    pole k a nk jsou v režimu opakování zakázaná („doplní se automaticky“)."""
    from envocad.model.project import Project
    from envocad.ui.dialogs import MacroValuesDialog
    from envocad.ui.main_window import MainWindow
    lib = LibraryStore()
    m = _dc_macro()
    dlg = MacroValuesDialog(m, lib)
    from PySide6.QtCore import Qt
    dlg.extra.setChecked(True)               # skupina „Další (číslování)“ rozbalená
    for name in ("k", "nk"):
        f = dlg._fields[name]
        assert f.testAttribute(Qt.WA_ForceDisabled) and not f.isEnabled()
        assert f.placeholderText() == "doplní se automaticky" and f.text() == ""
    assert dlg._fields["j"].isEnabled() and dlg._fields["n"].isEnabled()
    dlg._fields["n"].setText("3")
    dlg._fields["nk"].setText("7")          # zakázané pole se nepošle, ani kdyby v něm něco bylo
    vals = dlg.values()
    assert not dlg.errors and vals["j"] == "{k}" and vals["string"] == "G{k}"
    p = Project(name="Makro opakování")
    s = p.sheets[0]
    w = MainWindow(lib, p)
    w.open_sheet(s, "schematic")
    assert w.view.scene().insert_macro(m, vals, (150, 150)) > 0
    assert sorted(e.ref for e in s.elements if e.ref.startswith("FU")) == ["FU1.1", "FU1.2", "FU1.3"]
    descs = sorted(e.attrs["desc"] for e in s.elements if e.symbol_id == "fve.spd")
    assert descs == ["string G1", "string G2", "string G3"]
    assert sorted(e.ref for e in s.elements if is_feed_out(e) and e.ref != "XPE") == ["X4", "X5", "X6"]
    # automatické pole změněné uživatelem se pošle (číslo střídače)
    dlg._fields["i"].setText("2")
    assert dlg.values()["inverter"] == "T2"
    w.undo.setClean()
    w.close()


def test_macro_values_dialog_rejects_bad_count(app):
    """Nález 6: dialog nepustí počet 2.5 ani prázdný."""
    from envocad.ui.dialogs import MacroValuesDialog
    dlg = MacroValuesDialog(_dc_macro(), LibraryStore())
    dlg.show()
    for raw in ("2.5", ""):
        dlg._fields["n"].setText(raw)
        dlg.accept()
        assert dlg.errors and dlg.isVisible() and "Počet stringů" in dlg.error_label.text()
    dlg._fields["n"].setText("2")
    dlg.accept()
    assert not dlg.errors and dlg.result() == 1


def test_czech_dialog_buttons(app):
    """Nález 4: standardní tlačítka dialogů česky (MacroValuesDialog má „Zrušit“, ne „Cancel“)."""
    from PySide6.QtWidgets import QDialogButtonBox, QPushButton

    from envocad.ui.dialogs import MacroValuesDialog, button_box
    dlg = MacroValuesDialog(_dc_macro(), LibraryStore())
    texts = {b.text() for b in dlg.findChildren(QPushButton)}
    assert {"OK", "Zrušit"} <= texts and "Cancel" not in texts
    bb = button_box(QDialogButtonBox.Yes | QDialogButtonBox.No | QDialogButtonBox.Close | QDialogButtonBox.Apply)
    assert {b.text() for b in bb.buttons()} == {"Ano", "Ne", "Zavřít", "Použít"}


def test_insert_macro_count_zero_status_message(app, tmp_path, monkeypatch):
    """Nález 7: makro s počtem 0 nic nevloží a stavový řádek to řekne."""
    import json

    from envocad.model.project import Project
    from envocad.ui import dialogs
    from envocad.ui.main_window import MainWindow
    path = tmp_path / "nula.json"
    path.write_text(json.dumps({
        "version": 2, "name": "Nula", "repeat": {"count": "n"},
        "variables": [{"name": "n", "type": "number", "default": "0", "min": 0}],
        "fragment": {"elements": [{"id": "a", "symbol_id": "fve.breaker_mcb", "x": 0, "y": 0, "attrs": {"ref": "F1"}}],
                     "wires": []}}), encoding="utf-8")

    class FakeDialog:
        def __init__(self, macro, library, parent=None, **_kw):   # project, sheet (navazující číslování)
            self.macro, self.library = macro, library

        def exec(self):
            return 1

        def values(self):
            from envocad.library.macros import resolve_values
            return resolve_values(self.macro, given={"n": "0"})[0]

    monkeypatch.setattr(dialogs, "MacroValuesDialog", FakeDialog)
    p = Project(name="Makro nula")
    w = MainWindow(LibraryStore(), p)
    w.open_sheet(p.sheets[0], "schematic")
    w.insert_macro(str(path))
    assert not p.sheets[0].elements and not w.undo.canUndo()
    assert w.statusBar().currentMessage() == "Makro nevložilo žádné prvky (počet 0)"
    w.close()


def test_insert_macro_without_parameters_is_copy(app, tmp_path):
    """Nález 3: uživatelské makro bez proměnných se z knihovny vloží jako kopie výřezu (jako dřív paste_fragment):
    čísla svorek se vymažou, vývody se přečíslují, jedno undo na vložení."""
    import json

    from envocad.model.project import Project
    from envocad.ui.main_window import MainWindow
    path = tmp_path / "v1.json"
    path.write_text(json.dumps({"name": "v1", "fragment": {"elements": [
        {"id": "a", "symbol_id": "fve.terminal", "x": 0, "y": 0, "attrs": {"ref": "X1", "terminal": "1"}},
        {"id": "b", "symbol_id": "fve.breaker_mcb", "x": 20, "y": 0, "attrs": {"ref": "F1"}},
        {"id": "c", "symbol_id": "sb.feed_out", "x": 40, "y": 0, "attrs": {"ref": "X5", "sheet": "3"}}],
        "wires": []}}), encoding="utf-8")
    p = Project(name="Makro v1")
    s = p.sheets[0]
    w = MainWindow(LibraryStore(), p)
    w.open_sheet(s, "schematic")
    w.insert_macro(str(path))
    w.insert_macro(str(path))
    assert [e.attrs["terminal"] for e in s.elements if e.symbol_id == "fve.terminal"] == ["", ""]
    assert [e.ref for e in s.elements if e.symbol_id == "fve.breaker_mcb"] == ["F1", "F2"]
    feeds = [e.ref for e in s.elements if is_feed_out(e)]
    assert len(set(feeds)) == 2 and "X5" not in feeds
    w.undo.undo()
    assert len(s.elements) == 3
    w.undo.setClean()
    w.close()


# ---- připomínky: panel, skok, export, uzavření revize -------------------------------------------
def _notes_window(app, tmp_path):
    from envocad.model.project import Note
    p = _project()
    s2 = p.sheets[0].__class__(name="List 2")
    p.sheets.append(s2)
    s1 = p.sheets[0]
    g = s1.elements[0]
    p.notes += [
        Note(s1.id, x=50, y=100, text="Zkontrolovat proud", no=1, target_id=g.id, author="Jan"),
        Note(s1.id, x=100, y=60, w=20, h=10, text="Přidat popisek", no=2, author="Eva", status="resolved",
             resolved_by="Jan", resolved="2026-10-16T10:00"),
        Note(s2.id, x=40, y=40, text="Chybí svorka", no=3, author="Jan"),
    ]
    win = MainWindow(library=LibraryStore(tmp_path / "lib.db"), project=p)
    win.show()
    app.processEvents()
    return win, p, s1, s2


def test_notes_panel_filter_and_goto(app, tmp_path):
    win, p, _s1, s2 = _notes_window(app, tmp_path)
    try:
        panel = win.notes_panel
        nums = lambda: [panel.tree.topLevelItem(i).text(0) for i in range(panel.tree.topLevelItemCount())]
        assert nums() == ["1", "3"]                                  # výchozí filtr = Otevřené
        assert panel.tree.topLevelItem(0).text(2) == "G1" and panel.tree.topLevelItem(0).text(4) == "Jan"
        panel.status.setCurrentIndex(1)
        assert nums() == ["2"]
        panel.status.setCurrentIndex(2)
        assert nums() == ["1", "2", "3"]
        panel.only_sheet.setChecked(True)
        assert nums() == ["1", "2"]                                  # aktuální list = první
        panel.only_sheet.setChecked(False)
        panel.search.setText("svorka")
        assert nums() == ["3"]
        panel.search.setText("")

        # skok: přepne list, zapne zobrazení, vybere a vycentruje
        panel.goto_note.emit(s2.id, p.notes[2].id)
        assert win.current_sheet is s2 and win.act_notes.isChecked()
        sel = win.scene.selectedItems()
        assert len(sel) == 1 and sel[0].note.id == p.notes[2].id

        # Vyřešit / Otevřít a Smazat z panelu jdou přes undo a obnoví seznam
        panel.status.setCurrentIndex(2)
        panel.tree.topLevelItem(0).setSelected(True)
        assert panel.btn_toggle.text() == "Vyřešit"
        panel.btn_toggle.click()
        assert p.notes[0].status == "resolved" and p.notes[0].resolved_by
        win.undo.undo()
        assert p.notes[0].status == "open" and nums() == ["1", "2", "3"]
        win.undo.redo()
        panel.tree.clearSelection()
        panel.tree.topLevelItem(1).setSelected(True)
        assert panel.btn_toggle.text() == "Otevřít"
        panel.btn_delete.click()
        assert [n.no for n in p.notes] == [1, 3] and nums() == ["1", "3"]
        win.undo.undo()
        assert [n.no for n in p.notes] == [1, 2, 3]
    finally:
        win.undo.setClean()
        win.close()


def _note_annots(path) -> list[list]:
    """Anotace připomínek EnvoCAD (`/NM envocad:…`) po stranách; vlastní odkazy QPdfWriter se nepočítají."""
    import pypdf
    out = []
    for pg in pypdf.PdfReader(path).pages:
        items = [a.get_object() for a in (pg.get("/Annots") or [])]
        out.append([a for a in items if str(a.get("/NM", "")).startswith("envocad:")])
    return out


def test_notes_export_pdf_from_gui(app, tmp_path):
    win, p, s1, _s2 = _notes_window(app, tmp_path)
    try:
        out = tmp_path / "bez.pdf"
        win.act_export_notes.setChecked(False)
        from envocad.export.pdf_export import export_scene_pdf
        assert export_scene_pdf(win.scene, out, notes=win._export_notes()) == 0
        assert _note_annots(out) == [[]]
        win.act_export_notes.setChecked(True)
        assert win._export_notes()
        out2 = tmp_path / "s.pdf"
        n = export_scene_pdf(win.scene, out2, notes=win._export_notes())
        assert n == 1                                                 # jen otevřená připomínka listu
        annots = _note_annots(out2)[0]
        assert len(annots) == 1 and "Zkontrolovat" in str(annots[0]["/Contents"])
        # dokumentace
        from envocad.export.doc_pdf import export_documentation_pdf
        out3 = tmp_path / "d.pdf"
        export_documentation_pdf(p, win.library, out3, notes=win._export_notes())
        total = sum(len(a) for a in _note_annots(out3))
        assert total == 2                                             # otevřené na obou listech
        # DXF
        from envocad.export.dxf_export import export_sheet_dxf
        out4 = tmp_path / "s.dxf"
        export_sheet_dxf(p, s1, win.library, out4, notes=win._export_notes())
        assert "PRIPOMINKY" in out4.read_text(errors="ignore")
        # v obsahu PDF se připomínky nevypalují a zobrazení scény se po exportu vrátí
        win.set_notes_visible(True)
        export_scene_pdf(win.scene, out2, notes=False)
        assert win.scene.notes_visible and win.scene.note_items
    finally:
        win.undo.setClean()
        win.close()


def test_close_revision_asks_about_open_notes(app, tmp_path):
    from envocad.model.diff import diff_projects
    win, p, _s1, s2 = _notes_window(app, tmp_path)
    try:
        old = Project.from_dict(p.to_dict())
        p.sheets[0].elements[0].attrs["p_string"] = "99 kWp"
        win.record_revision(diff_projects(old, p, win.library), "B", "1.1.2026", "ENVO", "B | test")
        asked = []
        win._confirm_close_with_notes = lambda n: asked.append(n) or False
        assert not win.close_open_revision(None) and asked == [2] and not p.revisions[-1].closed
        assert not win.close_open_revision([s2.id]) and asked == [2, 1]
        win._confirm_close_with_notes = lambda n: asked.append(n) or True
        assert win.close_open_revision(None) and p.revisions[-1].closed
        # bez otevřených připomínek na uzavíraných listech se nikdo neptá
        for n in p.notes:
            n.status = "resolved"
        asked.clear()
        win.undo.undo()
        assert win.close_open_revision(None) and not asked
    finally:
        win.undo.setClean()
        win.close()


@pytest.mark.parametrize("n, text", [(1, "1 otevřená připomínka – přesto uzavřít?"),
                                     (3, "3 otevřené připomínky – přesto uzavřít?"),
                                     (5, "5 otevřených připomínek – přesto uzavřít?")])
def test_confirm_close_with_notes_czech_plural(app, monkeypatch, n, text):
    from PySide6.QtWidgets import QMessageBox
    seen = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: seen.append(self.text()) or QMessageBox.No)
    w = MainWindow(LibraryStore(), Project(name="P"))
    try:
        assert not w._confirm_close_with_notes(n) and seen == [text]
    finally:
        w.close()


@pytest.mark.parametrize("count, suffix", [(1, " (1 připomínka)"), (2, " (2 připomínky)"), (7, " (7 připomínek)"),
                                           (0, "")])
def test_export_pdf_status_czech_plural(app, tmp_path, monkeypatch, count, suffix):
    from PySide6.QtWidgets import QFileDialog

    import envocad.export.pdf_export as pe
    out = str(tmp_path / "x.pdf")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (out, ""))
    monkeypatch.setattr(pe, "export_scene_pdf", lambda *a, **k: count)
    w = MainWindow(LibraryStore(), Project(name="P"))
    try:
        w.export_pdf()
        assert w.statusBar().currentMessage() == f"Exportováno: {out}{suffix}"
    finally:
        w.close()


def test_note_dialog_resolve_fills_user(app):
    from envocad.model.project import Note
    from envocad.ui.dialogs import NoteDialog
    n = Note("s", text="a", author="Jan", created="2026-10-16T09:00")
    d = NoteDialog(n)
    d.text.setPlainText("  upraveno ")
    d.status.setCurrentIndex(1)
    r = d.result_note()
    assert r.status == "resolved" and r.resolved and r.resolved_by == d.note.resolved_by and r.text == "upraveno"
    assert n.status == "open" and not n.resolved                     # originál zůstává
    d.status.setCurrentIndex(0)
    assert d.result_note().status == "open" and not d.result_note().resolved


# ---- výrobní data rozvaděče (GUI) -------------------------------------------------------------------------------
def _sb_project():
    from envocad.model.project import Layout, Sheet
    p = Project(name="Rozv")
    s = Sheet(name="RDC1", kind="switchboard", loc="RDC1", layout=Layout(rows=2, modules_per_row=24))
    p.sheets.append(s)
    a = Element("fve.breaker_mcb", attrs={"ref": "F1", "in_": "16", "poles": "1"})
    b = Element("sb.terminal_block", attrs={"ref": "X1", "terminal": "1 2"})
    s.elements += [a, b]
    w = Wire(WireEnd(a.id, "2"), WireEnd(b.id, "1"), conductors=["L1"], attrs={"ref": "W1"})
    s.wires.append(w)
    return p, s, w


def test_wire_dialog_production_fields_only_on_switchboard(app):
    from envocad.model.project import SWITCHBOARD_WIRE_ATTRIBUTES, WIRE_ATTRIBUTES
    from envocad.ui.dialogs import WireDialog, wire_auto_hints
    p, s, w = _sb_project()
    plain = WireDialog(w.attrs, w.conductors)
    assert "color" not in plain.values() and plain.prod is None
    hints = wire_auto_hints(p, s, w)
    assert hints["color"] and hints["cross"]
    d = WireDialog({**w.attrs, "prod": "0"}, w.conductors, attributes=WIRE_ATTRIBUTES + SWITCHBOARD_WIRE_ATTRIBUTES,
                   hints=hints)
    assert {"color", "end_a", "end_b", "prod"} <= set(d.values())
    assert d.prod is not None and not d.prod.isChecked() and d.values()["prod"] == "0"
    assert d._edits["color"].placeholderText() == hints["color"]
    d.prod.setChecked(True)
    assert d.values()["prod"] == ""
    d.grab().save("/tmp/claude-0/-home-user-EnvoCAD/218ef7e0-ef83-5cc1-9211-57e519398ff2/scratchpad/wire_dialog.png")


def test_canvas_wire_dialog_scope_and_panel_prod_undo(app, tmp_path):
    from PySide6.QtWidgets import QCheckBox, QFormLayout, QLabel

    from envocad.ui.canvas import SchematicScene
    from envocad.ui.panels import PropertiesPanel
    lib = LibraryStore(tmp_path / "lib.db")
    p, s, w = _sb_project()
    sc = SchematicScene(p, s, lib, __import__("PySide6.QtGui", fromlist=["QUndoStack"]).QUndoStack())
    assert "attributes" in sc._wire_dialog_extra(w)
    sc2 = SchematicScene(_project(), _project().sheets[0], lib,
                         __import__("PySide6.QtGui", fromlist=["QUndoStack"]).QUndoStack())
    assert sc2._wire_dialog_extra(sc2.sheet.wires[0]) == {}

    def labels(panel):
        out = []
        for r in range(panel.form.rowCount()):
            it = panel.form.itemAt(r, QFormLayout.LabelRole)
            if it is not None and isinstance(it.widget(), QLabel):
                out.append(it.widget().text())
            fi = panel.form.itemAt(r, QFormLayout.FieldRole)
            if fi is not None and isinstance(fi.widget(), QCheckBox):
                out.append(fi.widget().text())
        return out

    panel = PropertiesPanel(lib)
    panel.show_item(sc.wire_items[w.id])
    got = labels(panel)
    # (12) u popisku koncovky je konec vodiče (ref:port)
    assert {"Barva vodiče", "Koncovka A (F1:2)", "Koncovka B (X1:1)", "Do výrobního seznamu"} <= set(got)
    labels_dlg = {a.key: a.label for a in sc._wire_dialog_extra(w)["attributes"]}
    assert labels_dlg["end_a"] == "Koncovka A (F1:2)" and labels_dlg["end_b"] == "Koncovka B (X1:1)"
    panel.show_item(sc2.wire_items[sc2.sheet.wires[0].id])
    assert "Barva vodiče" not in labels(panel) and "Do výrobního seznamu" not in labels(panel)

    panel.show_item(sc.wire_items[w.id])
    panel.attr_edited.connect(sc.set_attr)
    cb = next(c for c in panel.findChildren(QCheckBox) if c.text() == "Do výrobního seznamu")
    assert cb.isChecked()
    cb.setChecked(False)
    app.processEvents()
    assert w.attrs["prod"] == "0"
    sc.undo.undo()
    assert w.attrs.get("prod", "") == ""
    sc.undo.redo()
    assert w.attrs["prod"] == "0"


def test_enclosure_panel_keeps_unknown_params_and_saves_wire_keys(app):
    from envocad.model.project import Layout, Sheet
    from envocad.ui.dialogs import EnclosurePanel
    s = Sheet(kind="switchboard", layout=Layout(params={"nezname": "x", "wire_end_mm": "80"}))
    panel = EnclosurePanel(s)
    assert panel.wiring_group.isChecked() and panel._edits["wire_end_mm"].text() == "80"
    assert panel._edits["wire_reserve_pct"].placeholderText()
    panel._edits["wire_reserve_pct"].setText("15")
    panel._edits["ip"].setText("IP 55")
    lay = panel.apply()
    assert lay.params["nezname"] == "x"
    assert lay.params["wire_reserve_pct"] == "15" and lay.params["wire_end_mm"] == "80" and lay.params["ip"] == "IP 55"
    panel._edits["wire_end_mm"].setText("")
    assert "wire_end_mm" not in panel.apply().params


def test_enclosure_panel_uncheck_wiring_removes_wire_keys(app):
    """(11) Odškrtnutí skupiny „Výrobní data“ odebere klíče wire_* (platí standard), ostatní klíče zůstanou."""
    from envocad.model.project import Layout, Sheet
    from envocad.ui.dialogs import EnclosurePanel
    s = Sheet(kind="switchboard", layout=Layout(params={"foo": "bar", "wire_end_mm": "80", "wire_unplaced": "none"}))
    panel = EnclosurePanel(s)
    assert panel.wiring_group.isChecked()
    panel.wiring_group.setChecked(False)          # toggled → apply hned
    assert s.layout.params["foo"] == "bar" and not any(k.startswith("wire_") for k in s.layout.params)
    panel.wiring_group.setChecked(True)           # texty zůstaly → vrátí se
    assert s.layout.params["wire_end_mm"] == "80" and s.layout.params["wire_unplaced"] == "none"


def test_enclosure_panel_unplaced_combo_czech(app):
    """(13) wire_unplaced jako výběr s českými popisky, uložená hodnota estimate / none."""
    from envocad.model.project import Layout, Sheet
    from envocad.ui.dialogs import EnclosurePanel
    s = Sheet(kind="switchboard", layout=Layout(params={"wire_unplaced": "none"}))
    panel = EnclosurePanel(s)
    assert "wire_unplaced" not in panel._edits
    texts = [panel.unplaced.itemText(i) for i in range(panel.unplaced.count())]
    assert texts[1:] == ["odhad", "bez délky"] and texts[0].startswith("výchozí")
    assert panel.unplaced.currentText() == "bez délky"
    panel.unplaced.setCurrentIndex(panel.unplaced.findData("estimate"))
    assert s.layout.params["wire_unplaced"] == "estimate"
    panel.unplaced.setCurrentIndex(0)
    assert "wire_unplaced" not in s.layout.params


def test_menu_export_production_xlsx(app, tmp_path, monkeypatch):
    from openpyxl import load_workbook
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    p, _s, _w = _sb_project()
    out = str(tmp_path / "vyroba.xlsx")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (out, ""))
    win = MainWindow(LibraryStore(tmp_path / "lib.db"), p)
    try:
        win.export_production()
        assert win.statusBar().currentMessage() == f"Exportováno: {out}"
        assert "Výrobní seznam" in load_workbook(out).sheetnames
    finally:
        win.close()
    seen = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: seen.append(a[2]))
    win = MainWindow(LibraryStore(tmp_path / "lib.db"), Project(name="P"))
    try:
        win.export_production()
        assert seen
    finally:
        win.close()


def test_wizard_vn_connection_and_single_line_tab(app, tmp_path):
    from envocad.generate import build_project
    from envocad.ui.dialogs import ProjectWizard
    from envocad.ui.single_line_view import SingleLineView
    d = ProjectWizard()
    d.strings.setText("20,20; 18")
    assert not d.tr_sn.isEnabled()
    d.conn_level.setCurrentIndex(d.conn_level.findData("vn"))
    d.conn_metering.setCurrentIndex(d.conn_metering.findData("vn"))
    d.tr_sn.setText("1000")
    assert d.tr_sn.isEnabled()
    spec = d.spec()
    assert spec["connection"] == {"level": "vn", "metering": "vn", "station": "kiosk", "loop": True,
                                  "transformer": {"sn": 1000}}
    d.conn_station.setCurrentIndex(d.conn_station.findData("sloup"))     # sloupová TS: měření jen na nn
    assert not d.conn_metering.isEnabled() and d.conn_metering.currentData() == "nn" and not d.conn_loop.isEnabled()
    d.conn_station.setCurrentIndex(d.conn_station.findData("kiosk"))
    d.conn_metering.setCurrentIndex(d.conn_metering.findData("vn"))
    p = build_project(d.spec())
    assert {s.name.split()[0] for s in p.switchboards()} >= {"HR", "RVN", "RE"}
    w = MainWindow(LibraryStore(), p)
    w.open_single_line()
    assert isinstance(w.view, SingleLineView) and w.current_sheet is None and w.scene is None
    sc = w.view.scene()
    assert sc.geometry.root is not None and sc.paper_label in ("A2", "A1")
    # ruční posun: transformátor (i vše pod ním) o 20 mm doprava, undo vrátí automatickou polohu
    tr = next(n for n in sc.geometry.nodes.values() if n.element.symbol_id == "fve.transformer")
    hr_x = next(n.x for n in sc.geometry.nodes.values() if n.element.ref == "XT" and n.sheet.name.startswith("HR"))
    x0 = tr.x
    sc.move(tr.key, None, (20.0, 0.0))
    assert tr.element.sl_pos == (20.0, 0.0) and w.undo.canUndo()
    moved = {n.key: n for n in sc.geometry.nodes.values()}
    assert moved[tr.key].x == pytest.approx(x0 + 20)
    assert next(n.x for n in moved.values() if n.element.ref == "XT" and n.sheet.name.startswith("HR")) == \
        pytest.approx(hr_x + 20)
    w.undo.undo()
    assert tr.element.sl_pos is None
    assert next(n.x for n in sc.geometry.nodes.values() if n.key == tr.key) == pytest.approx(x0)
    w.undo.redo()
    sc.reset_offsets()
    assert tr.element.sl_pos is None
    w.open_single_line()                         # druhé otevření aktivuje stejnou záložku
    assert sum(isinstance(w._unwrap(w.tabs.widget(i)), SingleLineView) for i in range(w.tabs.count())) == 1
    w.undo.setClean()
    w.close()


def test_busbar_taps_change_refreshes_symbol(app, tmp_path):
    """Změna počtu přívodů parametrické sběrnice ve Vlastnostech: položka dostane novou značku (délka, porty B{k})
    a vodiče se překreslí k novým portům; undo vrátí původní značku."""
    from PySide6.QtGui import QUndoStack

    from envocad.ui import commands
    from envocad.ui.canvas import SchematicScene
    p = Project()
    s = p.sheets[0]
    bus = Element("sb.busbar", 165, 175, attrs={"ref": "1", "taps": "2"})
    f = Element("fve.breaker_mcb", 135, 140, rotation=90, attrs={"ref": "F1"})
    s.elements += [bus, f]
    s.wires.append(Wire(WireEnd(f.id, "2"), WireEnd(bus.id, "B2")))
    lib = LibraryStore(tmp_path / "lib.db")
    undo = QUndoStack()
    sc = SchematicScene(p, s, lib, undo)
    names = lambda: {q.name for q in sc.element_items[bus.id].symbol.ports}
    assert "B2" in names() and "B4" not in names()
    undo.push(commands.SetAttrCommand(sc, bus.id, False, "taps", "2", "4"))
    assert bus.attrs["taps"] == "4" and {"B3", "B4"} <= names()
    undo.undo()
    assert bus.attrs["taps"] == "2" and "B4" not in names()
