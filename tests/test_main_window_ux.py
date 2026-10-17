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
    assert w.actions["view_singlepole"].isChecked() and w.actions["select"].isChecked()
    w.actions["wire"].trigger()
    assert w.actions["wire"].isChecked() and not w.actions["select"].isChecked()
    w.actions["select"].trigger()
    assert w.actions["select"].isChecked()
    # rozložení: Dispozice místo Kreslení, kopírování a mazání vypnuté
    w.open_sheet(s, "layout")
    QApplication.processEvents()
    assert tbs["tb_layout"].isVisible() and not tbs["tb_draw"].isVisible()
    assert w.actions["view_layout"].isChecked() and not w.actions["view_singlepole"].isChecked()
    assert not w.actions["copy"].isEnabled() and not w.actions["delete"].isEnabled()
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
