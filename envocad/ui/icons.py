"""Ikony lišt a menu: SVG (Lucide, ISC + vlastní elektro ve stejném stylu) v `envocad/resources/icons/`,
obarvené podle aktuální palety – ve světlém i tmavém motivu. SVG mají `stroke="currentColor"`."""
from __future__ import annotations

from functools import cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"
SIZES = (16, 24, 32, 48)


@cache
def _svg(name: str) -> str:
    return (ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")


def _pixmap(name: str, color: QColor, size: int) -> QPixmap:
    data = _svg(name).replace("currentColor", color.name())
    r = QSvgRenderer(QByteArray(data.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def _colors() -> tuple[QColor, QColor]:
    app = QApplication.instance()
    pal = app.palette() if app is not None else QPalette()
    return pal.color(QPalette.Active, QPalette.ButtonText), pal.color(QPalette.Disabled, QPalette.ButtonText)


_cache: dict[tuple[str, str, str], QIcon] = {}


def icon(name: str) -> QIcon:
    """Ikona v barvě textu tlačítek aktuální palety (vypnutá akce = barva vypnutého textu)."""
    on, off = _colors()
    key = (name, on.name(), off.name())
    ic = _cache.get(key)
    if ic is None:
        ic = QIcon()
        for s in SIZES:
            ic.addPixmap(_pixmap(name, on, s), QIcon.Normal)
            ic.addPixmap(_pixmap(name, off, s), QIcon.Disabled)
        _cache[key] = ic
    return ic


def names() -> list[str]:
    return sorted(p.stem for p in ICON_DIR.glob("*.svg"))
