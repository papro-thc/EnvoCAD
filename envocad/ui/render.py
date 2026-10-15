"""Vykreslení primitiv symbolu přes QPainter. Scéna je v mm, osa Y převrácená (scene_y = -model_y)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen

from envocad.model.symbol import Primitive, Symbol

LINE_WIDTH = 0.35  # mm


def sp(x: float, y: float) -> QPointF:
    """model (Y nahoru) → scéna (Y dolů)"""
    return QPointF(x, -y)


def symbol_path(sym: Symbol) -> QPainterPath:
    """Čárová geometrie symbolu (bez textů) jako jedna cesta – pro hit-test a bounding box."""
    path = QPainterPath()
    for p in sym.primitives:
        _add_primitive(path, p)
    return path


def _add_primitive(path: QPainterPath, p: Primitive) -> None:
    t = p["type"]
    if t == "line":
        path.moveTo(sp(p["x1"], p["y1"]))
        path.lineTo(sp(p["x2"], p["y2"]))
    elif t == "rect":
        path.addRect(QRectF(p["x"], -(p["y"] + p["h"]), p["w"], p["h"]))
    elif t == "circle":
        path.addEllipse(sp(p["cx"], p["cy"]), p["r"], p["r"])
    elif t == "arc":
        r = p["r"]
        rect = QRectF(p["cx"] - r, -p["cy"] - r, 2 * r, 2 * r)
        start, end = p["start"], p["end"]
        sweep = (end - start) % 360 or 360
        path.arcMoveTo(rect, start)
        path.arcTo(rect, start, sweep)
    elif t == "polyline":
        pts = p["points"]
        if len(pts) >= 2:
            path.moveTo(sp(*pts[0]))
            for x, y in pts[1:]:
                path.lineTo(sp(x, y))
            if p.get("closed"):
                path.closeSubpath()


def paint_symbol(painter: QPainter, sym: Symbol, pen: QPen | None = None) -> None:
    painter.save()
    painter.setPen(pen or QPen(Qt.black, LINE_WIDTH))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(symbol_path(sym))
    for p in sym.primitives:
        if p["type"] == "text":
            draw_text(painter, p["x"], p["y"], p["text"], p.get("height", 2.5), p.get("align", "center"))
    painter.restore()


def draw_text(painter: QPainter, x: float, y: float, text: str, height: float = 2.5, align: str = "left") -> None:
    """Text ve výšce `height` mm, (x, y) = levý/střed/pravý bod základny (dle align)."""
    font = QFont("Arial")
    font.setPixelSize(max(1, round(height * 1.4 * 10)))  # pixelSize je v logických jednotkách malíře
    painter.save()
    painter.translate(sp(x, y))
    painter.scale(0.1, 0.1)  # font kreslíme 10× větší a zmenšíme → hladší rasterizace
    painter.setFont(font)
    w = painter.fontMetrics().horizontalAdvance(text)
    dx = {"left": 0.0, "center": -w / 2, "right": -w}.get(align, 0.0)
    painter.drawText(QPointF(dx, 0), text)
    painter.restore()


def draw_frame(painter: QPainter, geom, color) -> None:
    """Rámeček a popisové pole z `model/frame.py` (geometrie v mm, Y nahoru)."""
    painter.save()
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(color, 0.5))
    for x1, y1, x2, y2 in geom.lines[:4]:
        painter.drawLine(sp(x1, y1), sp(x2, y2))
    painter.setPen(QPen(color, 0.25))
    for x1, y1, x2, y2 in geom.lines[4:]:
        painter.drawLine(sp(x1, y1), sp(x2, y2))
    painter.setPen(QPen(color, 0.2))
    for x, y, text, h, align in geom.texts:
        if text:
            draw_text(painter, x, y, text, h, align)
    if geom.rects:
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        for x, y, w, h in geom.rects:
            painter.drawRect(QRectF(x, -(y + h), w, h))
    painter.restore()
