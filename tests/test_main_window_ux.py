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
