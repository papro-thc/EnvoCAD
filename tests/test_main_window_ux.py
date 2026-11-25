"""Hlavní okno: jednoznačné zkratky, tooltipy se zkratkou, zapamatování okna a rozložení panelů."""
import os
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QDockWidget

from envocad.ui.main_window import MainWindow


def _window():
    w = MainWindow()
    w.show()
    QApplication.processEvents()
    return w


def test_shortcuts_unique():
    """Dvě akce se stejnou zkratkou Qt vyhodnotí jako nejednoznačné a nespustí ani jednu (Ctrl+Shift+S)."""
    w = _window()
    keys = Counter()
    for a in w.findChildren(QAction):
        for k in {k.toString(QKeySequence.PortableText) for k in a.shortcuts()}:   # Redo = Ctrl+Y i na Windows
            keys[k] += 1
    dup = {k: n for k, n in keys.items() if n > 1}
    assert not dup, f"zkratka přiřazená více akcím: {dup}"
    w.close()


def test_shortcut_tooltips():
    w = _window()
    acts = {a.text(): a for a in w.findChildren(QAction)}
    assert acts["Uložit &jako…"].toolTip() == f"Uložit jako ({QKeySequence('Ctrl+Shift+S').toString(QKeySequence.NativeText)})"
    assert acts["Kontrola projektu…"].toolTip().endswith("(F7)")
    undo = next(a for a in w.findChildren(QAction) if a.text().startswith("Zpět"))
    assert "(" in undo.toolTip()
    w.close()


def test_window_state_saved_and_reset():
    w = _window()
    w.resize(700, 500)                          # offscreen obrazovka má 800×600
    dock = next(d for d in w.findChildren(QDockWidget) if d.objectName() == "Knihovna")
    dock.hide()
    QApplication.processEvents()
    size = (w.width(), w.height())              # po minimální šířce doků
    assert size != (1400, 900)
    w.close()                                   # undo je čistý → zavře se bez dotazu a uloží stav
    w2 = _window()
    assert (w2.width(), w2.height()) == size
    dock2 = next(d for d in w2.findChildren(QDockWidget) if d.objectName() == "Knihovna")
    assert not dock2.isVisible()
    w2.reset_layout()
    QApplication.processEvents()
    assert dock2.isVisible()
    assert w2.dockWidgetArea(dock2) == Qt.LeftDockWidgetArea
    w2.close()


# ---- lišty a ikony (krok 2 návrhu docs/design/ux_lista.md) ---------------------------------------------
def _sb_window():
    from envocad.library.store import LibraryStore
    from envocad.model.project import Element, Layout, Project, Sheet, Wire, WireEnd
    p = Project(name="Rozv")
    s = Sheet(name="RDC1", kind="switchboard", loc="RDC1", layout=Layout(rows=2, modules_per_row=24))
    p.sheets.append(s)
    a = Element("fve.breaker_mcb", attrs={"ref": "F1", "in_": "16", "poles": "1"})
    b = Element("sb.terminal_block", attrs={"ref": "X1", "terminal": "1 2"})
    s.elements += [a, b]
    s.wires.append(Wire(WireEnd(a.id, "2"), WireEnd(b.id, "1"), conductors=["L1"], attrs={"ref": "W1"}))
    w = MainWindow(LibraryStore(), p)
    w.show()
    QApplication.processEvents()
    return w, p, s


def test_icons_render_in_both_themes():
    from envocad.ui import icons, theme
    assert set(MainWindow.ICONS.values()) <= set(icons.names())
    was = theme.is_dark()
    try:
        px = {}
        for dark in (False, True):
            theme.apply(dark)
            for name in icons.names():
                assert not icons.icon(name).pixmap(24, 24).isNull(), name
            img = icons.icon("save").pixmap(24, 24).toImage()
            px[dark] = max((img.pixelColor(x, y) for x in range(24) for y in range(24)), key=lambda c: c.alpha())
        assert px[False].lightness() < 100 < px[True].lightness()     # tmavá ikona na světlém, světlá na tmavém
    finally:
        theme.apply(was)


def test_toolbars_follow_active_view():
    from PySide6.QtWidgets import QToolBar
    w, _p, s = _sb_window()
    tbs = {t.objectName(): t for t in w.findChildren(QToolBar)}
    assert {MainWindow.TOOLBARS[i][0] for i in range(len(MainWindow.TOOLBARS))} <= set(tbs)
    for t in tbs.values():
        for a in t.actions():
            assert a.isSeparator() or not a.icon().isNull(), a.text()
    # JPS: Kreslení ano, Dispozice ne; pohled Jednopól zaškrtnutý, nástroj Výběr aktivní
    w.tabs.setCurrentIndex(0)
    QApplication.processEvents()
    assert tbs["tb_draw"].isVisible() and not tbs["tb_layout"].isVisible()
    assert w.actions["view_singlepole"].isChecked() and w.actions["select_mode"].isChecked()
    w.actions["wire"].trigger()
    assert w.actions["wire"].isChecked() and not w.actions["select_mode"].isChecked()
    w.actions["select_mode"].trigger()
    assert w.actions["select_mode"].isChecked()
    # rozložení: Dispozice místo Kreslení, kopírování a mazání vypnuté
    w.open_sheet(s, "layout")
    QApplication.processEvents()
    assert tbs["tb_layout"].isVisible() and not tbs["tb_draw"].isVisible()
    assert w.actions["view_layout"].isChecked() and not w.actions["view_singlepole"].isChecked()
    assert not w.actions["copy_clipboard"].isEnabled() and not w.actions["delete"].isEnabled()
    # schéma rozvaděče (vícepól): kreslí se tam → Kreslení zpět
    w.open_sheet(s, "multipole")
    QApplication.processEvents()
    assert tbs["tb_draw"].isVisible() and w.actions["view_multipole"].isChecked()
    # klik na už zaškrtnutý pohled ho nechá zaškrtnutý (přepínač nejde „vypnout“)
    w.actions["view_multipole"].trigger()
    assert w.actions["view_multipole"].isChecked()
    w.close()


def test_insert_symbol_and_delete_from_toolbar():
    from envocad.ui.canvas import Mode
    from envocad.ui.multipole_view import PoleItem
    w, _p, s = _sb_window()
    w.tabs.setCurrentIndex(0)
    # bez vybrané značky se ukáže Knihovna a nápověda
    w.lib_panel.tree.setCurrentItem(None)
    w.actions["insert_symbol"].trigger()
    assert "Knihovn" in w.statusBar().currentMessage()
    # vybraná značka → režim vkládání, nástroj Vložit značku zaškrtnutý
    tree = w.lib_panel.tree
    leaf = next(it for it in (tree.topLevelItem(0).child(i) for i in range(tree.topLevelItem(0).childCount()))
                if it.data(0, Qt.UserRole))
    tree.setCurrentItem(leaf)
    w.actions["insert_symbol"].trigger()
    assert w.scene.mode == Mode.PLACE and w.actions["insert_symbol"].isChecked()
    w.scene.set_mode(Mode.SELECT)
    # Smazat ve schématu rozvaděče (vícepól) – akce menu dřív mazala jen v JPS
    w.open_sheet(s, "multipole")
    QApplication.processEvents()
    sc = w.view.scene()
    pole = next(it for it in sc.items() if isinstance(it, PoleItem) and it.element.attrs.get("ref") == "F1")
    pole.setSelected(True)
    n = len(s.elements)
    w.actions["delete"].trigger()
    assert len(s.elements) == n - 1
    w.undo.undo()
    assert len(s.elements) == n
    w.undo.setClean()
    w.close()


def test_zoom_actions():
    w, _p, _s = _sb_window()
    w.tabs.setCurrentIndex(0)
    m = w.view.transform().m11()
    w.actions["zoom_in"].trigger()
    assert w.view.transform().m11() > m
    w.actions["zoom_out"].trigger()
    assert abs(w.view.transform().m11() - m) < 1e-9
    w.close()


# ---- krok 3: stavový řádek, Ctrl+K, panel Kontrola, kontextové menu, úvodní obrazovka ------------------
def test_status_bar_coords_zoom_dirty():
    import re

    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    w, _p, _s = _sb_window()
    w.tabs.setCurrentIndex(0)
    QApplication.processEvents()
    z = w._sb_zoom.text()
    assert re.fullmatch(r"Zoom \d+ %", z)
    w.actions["zoom_in"].trigger()
    assert w._sb_zoom.text() != z
    vp = w.view.viewport()
    pt = QPointF(vp.width() / 2, vp.height() / 2)    # QTest.mouseMove nepošle nic, je-li kurzor už na místě
    QApplication.sendEvent(vp, QMouseEvent(QEvent.MouseMove, pt, vp.mapToGlobal(pt), Qt.NoButton, Qt.NoButton,
                                           Qt.NoModifier))
    assert re.fullmatch(r"X -?\d+,\d  Y -?\d+,\d mm", w._sb_coords.text()), w._sb_coords.text()
    assert w._sb_checks.text() == "F7: –" and not w._sb_dirty.isVisible()
    w.undo.push(_noop_command(w))
    assert w._sb_dirty.isVisible()
    w.undo.setClean()
    assert not w._sb_dirty.isVisible()
    w.close()


def _noop_command(w):
    from PySide6.QtGui import QUndoCommand
    return QUndoCommand("test")


def test_checks_panel_is_dock_and_refreshes():
    from envocad.model.checks import ERROR
    w, _p, _s = _sb_window()
    w.tabs.setCurrentIndex(0)
    w.actions["checks"].trigger()                    # F7 – žádný modální dialog, panel dole
    QApplication.processEvents()
    assert w.checks_dock.isVisible()
    assert w.checks_panel.tree.topLevelItemCount() == len(w._findings) > 0
    assert w._sb_checks.text().startswith("F7: ")
    # filtr „Chyby“
    w.checks_panel.filter.setCurrentIndex(1)
    shown = w.checks_panel.tree.topLevelItemCount()
    assert shown == sum(f.severity == ERROR for f in w._findings)
    # změna projektu → nálezy se obnoví samy (odložené)
    before = list(w._findings)
    w.undo.push(_noop_command(w))
    assert w._checks_timer.isActive()
    w._checks_timer.timeout.emit()
    assert w._findings is not before
    w.undo.setClean()
    w.close()


def test_findings_badge_czech_plural():
    from envocad.model.checks import ERROR, WARNING, Finding
    from envocad.ui.navigator import findings_badge

    def f(sev):
        return Finding(sev, "s", "List", "", False, "", "x")
    assert findings_badge(None) == "F7: –"
    assert findings_badge([]) == "F7: bez chyb"
    assert findings_badge([f(ERROR)]) == "F7: 1 chyba"
    assert findings_badge([f(ERROR)] * 3 + [f(WARNING)] * 2) == "F7: 3 chyby, 2 varování"
    assert findings_badge([f(ERROR)] * 5) == "F7: 5 chyb"


def test_command_palette_filters_and_runs():
    from envocad.ui.command_palette import CommandPalette, collect_actions, matches
    w, _p, _s = _sb_window()
    labels = [lab for lab, _a in collect_actions(w.menuBar())]
    assert "Soubor › Uložit jako" in labels and any(lab.startswith("Zobrazit › Tmavý") for lab in labels)
    assert matches("ulozit jak", "Soubor › Uložit jako") and not matches("export xyz", "Soubor › Export DXF")
    assert w.actions["palette"].shortcut().toString() == "Ctrl+K"
    assert w.actions["enclosure"].shortcut().toString() == "Ctrl+Alt+K"
    pal = CommandPalette(w.menuBar(), w)
    pal.edit.setText("prizpusobit list")
    assert pal.list.count() == 1 and "Přizpůsobit list" in pal.list.item(0).text()
    hit = []
    w.actions["fit"].triggered.connect(lambda: hit.append(1))
    pal.run_current()
    QApplication.processEvents()
    assert hit == [1] and pal.result() == pal.DialogCode.Accepted
    w.close()


def test_context_menu_on_element_and_wire():
    from envocad.ui.items import ElementItem, WireItem
    from envocad.ui.multipole_view import PoleItem
    w, _p, s = _sb_window()
    w.open_sheet(s, "schematic")
    QApplication.processEvents()
    sc = w.scene
    el = next(it for it in sc.items() if isinstance(it, ElementItem))
    m = w.context_menu(el.sceneBoundingRect().center())
    texts = [a.text() for a in m.actions() if not a.isSeparator()]
    assert el.isSelected() and "Vlastnosti…" in texts and "Otočit o 90°" in texts and "Smazat" in texts
    wi = next(it for it in sc.items() if isinstance(it, WireItem))
    pos = next(wi.mapToScene(wi.path().pointAtPercent(t / 20)) for t in range(1, 20)
               if not any(isinstance(i, ElementItem) for i in sc.items(wi.mapToScene(wi.path().pointAtPercent(t / 20)))))
    m = w.context_menu(pos)
    texts = [a.text() for a in m.actions() if not a.isSeparator()]
    assert "Svorky vybraného vodiče…" in texts and wi.isSelected() and not el.isSelected()
    # prázdné místo: jen vložit/vodič/přizpůsobit
    m = w.context_menu(sc.sceneRect().topLeft())
    assert "Smazat" not in [a.text() for a in m.actions()]
    # schéma rozvaděče
    w.open_sheet(s, "multipole")
    QApplication.processEvents()
    pole = next(it for it in w.view.scene().items() if isinstance(it, PoleItem))
    m = w.context_menu(pole.mapToScene(pole.shape().boundingRect().center()))
    assert "Vlastnosti…" in [a.text() for a in m.actions()]
    # rozložení: žádné menu výkresu
    w.open_sheet(s, "layout")
    assert w.context_menu(sc.sceneRect().center()) is None
    w.close()


def test_welcome_overlay_for_empty_project(tmp_path):
    from envocad.library.store import LibraryStore
    from envocad.model.project import Project
    w = MainWindow(LibraryStore(), Project())
    w.show()
    QApplication.processEvents()
    assert w.welcome.isVisible()
    assert w.welcome.btn_wizard.text().startswith("Nový projekt z průvodce")
    w.undo.push(_noop_command(w))                     # první změna → úvodní obrazovka zmizí
    assert not w.welcome.isVisible()
    w.undo.setClean()
    w.close()
    w2, _p, _s = _sb_window()                         # projekt s obsahem → bez úvodní obrazovky
    assert not w2.welcome.isVisible()
    w2.close()


def test_right_click_shows_menu_only_in_select_mode(monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtTest import QTest

    from envocad.ui.canvas import Mode
    shown = []
    monkeypatch.setattr(MainWindow, "_exec_menu", lambda self, m, _p: shown.append([x.text() for x in m.actions()]))
    w, _p, _s = _sb_window()
    w.tabs.setCurrentIndex(0)
    vp = w.view.viewport()
    pt = QPoint(vp.width() // 2, vp.height() // 2)

    def right_click():
        QTest.mousePress(vp, Qt.RightButton, Qt.NoModifier, pt)
        QTest.mouseRelease(vp, Qt.RightButton, Qt.NoModifier, pt)
        QApplication.sendEvent(vp, QContextMenuEvent(QContextMenuEvent.Mouse, pt, vp.mapToGlobal(pt)))

    w.scene.start_wire()
    right_click()                                    # v režimu Vodič pravé tl. jen ukončí režim
    assert w.scene.mode == Mode.SELECT and shown == []
    right_click()                                    # ve výběru menu
    assert len(shown) == 1 and "Přizpůsobit list" in shown[0]
    w.close()


def test_checks_panel_restored_from_last_run_fills_itself():
    w, _p, _s = _sb_window()
    w.run_checks()
    w.close()                                        # stav okna s otevřeným panelem Kontrola se uloží
    w2, _p2, _s2 = _sb_window()
    assert w2.checks_dock.isVisible()
    # časovač (800 ms) mohl na pomalém běhu (Windows CI) už vypršet a nálezy se doplnily samy
    assert w2._checks_timer.isActive() or w2._findings is not None
    w2._checks_timer.timeout.emit()
    assert w2._findings is not None and w2.checks_panel.tree.topLevelItemCount() > 0
    w2.close()


def test_drawing_only_and_compact_checks_panel():
    from PySide6.QtWidgets import QDockWidget
    w, _p, _s = _sb_window()
    w.resize(1400, 900)
    w.tabs.setCurrentIndex(0)
    QApplication.processEvents()
    full, full_w = w.view.viewport().height(), w.view.viewport().width()
    w.run_checks()
    QApplication.processEvents()
    assert w.checks_dock.height() <= MainWindow.CHECKS_HEIGHT + 40        # výkres má přednost
    assert w.view.viewport().height() >= full - MainWindow.CHECKS_HEIGHT - 60
    w.actions["focus"].trigger()                                          # F11: jen výkres
    QApplication.processEvents()
    assert not any(d.isVisible() for d in w.findChildren(QDockWidget))
    assert w.view.viewport().height() >= full and w.view.viewport().width() > full_w + 200   # bez bočních panelů
    w.actions["focus"].trigger()
    QApplication.processEvents()
    assert w.checks_dock.isVisible() and w.findChild(QDockWidget, "Knihovna").isVisible()
    w.actions["focus"].trigger()
    w.close()                                                             # uloží se rozložení s panely
    w2, _p2, _s2 = _sb_window()
    assert w2.findChild(QDockWidget, "Knihovna").isVisible() and not w2.act_focus.isChecked()
    w2.close()


def test_renumber_dialog_and_undo(monkeypatch):
    """Úpravy → Přečíslovat označení: náhled v dialogu, jeden krok undo, popisky ve výkresu se překreslí."""
    from envocad.model.project import Element
    from envocad.ui.renumber_dialog import RenumberDialog
    w = _window()
    s = w.project.sheets[0]
    a = Element("fve.breaker_mcb", 100, 100, attrs={"ref": "F1"})
    b = Element("fve.breaker_mcb", 150, 100, attrs={"ref": "F1"})
    s.elements += [a, b]
    w.scene.rebuild()
    dlg = RenumberDialog(w.project, w.library, s, w)
    assert dlg.tree.topLevelItemCount() == 1 and dlg.tree.topLevelItem(0).text(2) == "F2"
    dlg.mode.setCurrentIndex(dlg.mode.findData("all"))
    assert dlg.changes and "1 prvek" in dlg.summary.text()
    monkeypatch.setattr(RenumberDialog, "exec", lambda self: RenumberDialog.Accepted)
    n = w.undo.count()
    w.renumber_refs()
    assert (a.ref, b.ref) == ("F1", "F2") and w.undo.count() == n + 1
    assert w.undo.undoText() == "Přečíslovat označení"
    w.undo.undo()
    assert b.ref == "F1"
    w.close()


# ---- zbytek návrhu: lišty (ikona + tooltip), kontextová menu, souřadnice ---------------------------------
def test_every_toolbar_action_has_icon_and_tooltip_with_shortcut():
    from PySide6.QtWidgets import QToolBar
    w, _p, _s = _sb_window()
    n = 0
    for tb in w.findChildren(QToolBar):
        for a in tb.actions():
            if a.isSeparator():
                continue
            n += 1
            assert not a.icon().isNull() and not a.icon().pixmap(20, 20).isNull(), a.text()
            assert a.toolTip().strip(), a.text()
            keys = a.shortcut().toString(QKeySequence.NativeText)
            if keys:
                assert keys in a.toolTip(), (a.text(), a.toolTip())
    assert n >= 25
    w.close()


def _menu_texts(m):
    return [a.text() for a in m.actions() if not a.isSeparator()]


def test_context_menu_actions_work_and_undo():
    from envocad.ui.items import ElementItem, WireItem
    w, _p, s = _sb_window()
    w.open_sheet(s, "schematic")
    QApplication.processEvents()
    sc = w.scene
    el = next(it for it in sc.items() if isinstance(it, ElementItem) and it.element.attrs.get("ref") == "F1")
    for it in sc.items():
        if isinstance(it, ElementItem) and it.element.attrs.get("ref") == "X1":
            it.setPos(80, 0)
    m = w.context_menu(el.sceneBoundingRect().center())
    assert el.isSelected()
    texts = _menu_texts(m)
    for t in ("Vlastnosti…", "Otočit o 90°", "Zrcadlit", "Kopírovat", "Smazat", "Vložit kopii",
              "Vložit značku z knihovny", "Přizpůsobit list"):
        assert t in texts, t
    act = {a.text(): a for a in m.actions()}
    rot, mir = el.element.rotation, el.element.mirror
    act["Otočit o 90°"].trigger()
    assert el.element.rotation != rot
    act["Zrcadlit"].trigger()
    assert el.element.mirror != mir
    w.undo.undo()
    w.undo.undo()
    assert (el.element.rotation, el.element.mirror) == (rot, mir)
    n = len(s.elements)
    act["Smazat"].trigger()
    assert len(s.elements) == n - 1
    w.undo.undo()
    assert len(s.elements) == n
    # vodič: svorky, kabel, smazat
    wi = next(it for it in sc.items() if isinstance(it, WireItem))
    pos = next(wi.mapToScene(wi.path().pointAtPercent(t / 20)) for t in range(1, 20)
               if not any(isinstance(i, ElementItem) for i in sc.items(wi.mapToScene(wi.path().pointAtPercent(t / 20)))))
    texts = _menu_texts(w.context_menu(pos))
    for t in ("Svorky vybraného vodiče…", "Kabel vybraného vodiče (žíly, barvy, stínění)…", "Smazat"):
        assert t in texts, t
    # prázdná plocha: Vložit, Vložit značku, Přizpůsobit; bez Smazat
    texts = _menu_texts(w.context_menu(sc.sceneRect().topLeft()))
    assert "Vložit kopii" in texts and "Vložit značku z knihovny" in texts and "Přizpůsobit list" in texts
    assert "Smazat" not in texts
    w.undo.setClean()
    w.close()


def test_context_menu_open_switchboard_block(monkeypatch):
    from envocad.model.project import Element
    from envocad.ui.items import ElementItem
    w, _p, _s = _sb_window()
    from envocad.library.store import LibraryStore
    from envocad.model.project import Project, Sheet
    blk = Element("fve.switchboard", attrs={"ref": "RDC1"})
    jps = Sheet(name="JPS")
    jps.elements.append(blk)
    w.close()
    w = MainWindow(LibraryStore(), Project(name="P", sheets=[jps]))
    w.show()
    w.open_sheet(jps, "schematic")
    QApplication.processEvents()
    it = next(i for i in w.scene.items() if isinstance(i, ElementItem) and i.element.id == blk.id)
    called = []
    monkeypatch.setattr(w, "open_switchboard_from_block", lambda eid: called.append(eid))
    m = w.context_menu(it.sceneBoundingRect().center())
    assert "Otevřít rozvaděč" in _menu_texts(m)
    next(a for a in m.actions() if a.text() == "Otevřít rozvaděč").trigger()
    assert called == [blk.id]
    w.close()


def test_context_menu_in_multipole_and_cursor_on_grid():
    import re

    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    from envocad.ui.multipole_view import PoleItem
    w, _p, s = _sb_window()
    w.open_sheet(s, "multipole")
    QApplication.processEvents()
    pole = next(it for it in w.view.scene().items() if isinstance(it, PoleItem))
    m = w.context_menu(pole.mapToScene(pole.shape().boundingRect().center()))
    texts = _menu_texts(m)
    assert "Vlastnosti…" in texts and "Smazat" in texts and "Přizpůsobit list" in texts
    vp = w.view.viewport()
    pt = QPointF(vp.width() / 3, vp.height() / 3)
    QApplication.sendEvent(vp, QMouseEvent(QEvent.MouseMove, pt, vp.mapToGlobal(pt), Qt.NoButton, Qt.NoButton,
                                           Qt.NoModifier))
    mm = re.fullmatch(r"X (-?\d+),(\d)  Y (-?\d+),(\d) mm", w._sb_coords.text())
    assert mm, w._sb_coords.text()
    for v in (float(f"{mm[1]}.{mm[2]}"), float(f"{mm[3]}.{mm[4]}")):
        assert abs(v / 2.5 - round(v / 2.5)) < 1e-9, v          # na mřížce 2,5 mm
    w.close()


def test_context_menu_bulk_properties_for_multi_selection():
    from envocad.ui.items import ElementItem
    w, _p, s = _sb_window()
    w.open_sheet(s, "schematic")
    QApplication.processEvents()
    sc = w.scene
    items = [it for it in sc.items() if isinstance(it, ElementItem)]
    f1 = next(it for it in items if it.element.attrs.get("ref") == "F1")
    m = w.context_menu(f1.sceneBoundingRect().center())
    assert not any("vybraných prvků" in t for t in _menu_texts(m))      # jeden prvek: bez hromadné položky
    for it in items:
        it.setSelected(True)
    m = w.context_menu(f1.sceneBoundingRect().center())
    act = next(a for a in m.actions() if a.text().startswith("Vlastnosti vybraných prvků"))
    assert act.text() == f"Vlastnosti vybraných prvků ({len(items)})…"
    got = []
    sc.edit_elements_bulk = lambda ids: got.append(sorted(ids))
    act.trigger()
    assert got == [sorted(it.element.id for it in items)]
    w.close()
