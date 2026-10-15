"""Barevná témata (světlé / tmavé). Výkres má své barvy nezávisle na Qt paletě."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class DrawingColors:
    background: QColor
    grid: QColor
    grid_major: QColor
    paper: QColor
    ink: QColor        # symboly, texty
    wire: QColor
    port: QColor
    selection: QColor
    preview: QColor


LIGHT = DrawingColors(
    background=QColor(250, 250, 250), grid=QColor(222, 222, 222), grid_major=QColor(205, 205, 205),
    paper=QColor(120, 120, 120), ink=QColor(0, 0, 0), wire=QColor(0, 0, 0), port=QColor(200, 0, 0),
    selection=QColor(0, 120, 215), preview=QColor(0, 120, 215),
)
DARK = DrawingColors(
    background=QColor(30, 31, 34), grid=QColor(46, 48, 52), grid_major=QColor(60, 62, 68),
    paper=QColor(120, 122, 128), ink=QColor(225, 227, 230), wire=QColor(225, 227, 230),
    port=QColor(255, 110, 100), selection=QColor(90, 170, 255), preview=QColor(90, 170, 255),
)
PRINT = DrawingColors(  # export PDF: vždy černá na bílé
    background=QColor(255, 255, 255), grid=QColor(255, 255, 255), grid_major=QColor(255, 255, 255),
    paper=QColor(0, 0, 0), ink=QColor(0, 0, 0), wire=QColor(0, 0, 0), port=QColor(255, 255, 255, 0),
    selection=QColor(0, 0, 0), preview=QColor(0, 0, 0),
)

_current: DrawingColors = LIGHT


def colors() -> DrawingColors:
    return _current


def is_dark() -> bool:
    return _current is DARK


def _dark_palette() -> QPalette:
    p = QPalette()
    bg, base, text = QColor(43, 45, 48), QColor(33, 34, 37), QColor(225, 227, 230)
    p.setColor(QPalette.Window, bg)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, bg)
    p.setColor(QPalette.ToolTipBase, base)
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, bg)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor(255, 90, 90))
    p.setColor(QPalette.Highlight, QColor(60, 120, 200))
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.Link, QColor(90, 170, 255))
    p.setColor(QPalette.PlaceholderText, QColor(130, 132, 136))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(120, 122, 126))
    return p


def apply(dark: bool, app: QApplication | None = None) -> None:
    """Přepne téma celé aplikace a uloží volbu do nastavení."""
    global _current
    app = app or QApplication.instance()
    _current = DARK if dark else LIGHT
    if app is not None:
        app.setStyle("Fusion")
        app.setPalette(_dark_palette() if dark else app.style().standardPalette())
    QSettings("ENVO", "EnvoCAD").setValue("ui/dark", dark)


def load_saved() -> bool:
    v = QSettings("ENVO", "EnvoCAD").value("ui/dark", True)
    return v in (True, "true", "True", 1, "1")
