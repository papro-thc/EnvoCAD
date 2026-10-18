"""Vykreslení primitiv symbolu přes QPainter. Scéna je v mm, osa Y převrácená (scene_y = -model_y)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QPainter, QPainterPath, QPen

from envocad.model.symbol import MIRROR_ALIGN, Primitive, Symbol

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


def paint_symbol(painter: QPainter, sym: Symbol, pen: QPen | None = None, mirror: bool = False) -> None:
    """Značka v souřadnicích malíře. `mirror` = malíř je zrcadlený (prvek `mirror`) – texty značky se kreslí
    znovu zrcadlené, aby zůstaly čitelné, s prohozeným zarovnáním."""
    painter.save()
    painter.setPen(pen or QPen(Qt.black, LINE_WIDTH))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(symbol_path(sym))
    for p in sym.primitives:
        if p["type"] == "text" and mirror:
            painter.save()
            painter.translate(sp(p["x"], p["y"]))
            painter.scale(-1, 1)
            align = p.get("align", "center")
            draw_text(painter, 0, 0, p["text"], p.get("height", 2.5), MIRROR_ALIGN.get(align, align))
            painter.restore()
        elif p["type"] == "text" and _upside_down(painter):
            # značka otočená o 180° (přívod pole VN zdola): text otočený zpět kolem svého středu, aby byl čitelný
            h = p.get("height", 2.5)
            painter.save()
            painter.translate(sp(p["x"], p["y"] + 0.35 * h))
            painter.rotate(180)
            align = p.get("align", "center")
            draw_text(painter, 0, -0.35 * h, p["text"], h, MIRROR_ALIGN.get(align, align))
            painter.restore()
        elif p["type"] == "text":
            draw_text(painter, p["x"], p["y"], p["text"], p.get("height", 2.5), p.get("align", "center"))
        elif p["type"] == "circle" and p.get("filled"):   # vyplněný bod (uzel odbočky)
            painter.setBrush((pen or QPen(Qt.black)).color())
            painter.drawEllipse(sp(p["cx"], p["cy"]), p["r"], p["r"])
            painter.setBrush(Qt.NoBrush)
    painter.restore()


def _upside_down(painter: QPainter) -> bool:
    """Malíř otočený o 180° (bez zrcadlení): osa x i y obrácené."""
    t = painter.worldTransform()
    return t.m11() < -1e-6 and t.m22() < -1e-6 and abs(t.m12()) < 1e-6


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


_METRICS: dict[int, QFontMetricsF] = {}


def text_width(text: str, height: float = 2.5) -> float:
    """Šířka textu v mm tak, jak ho nakreslí `draw_text` (stejné písmo a měřítko)."""
    px = max(1, round(height * 1.4 * 10))
    fm = _METRICS.get(px)
    if fm is None:
        font = QFont("Arial")
        font.setPixelSize(px)
        fm = _METRICS[px] = QFontMetricsF(font)
    return fm.horizontalAdvance(text) * 0.1


def wrap_text(text: str, width: float, height: float = 2.5) -> list[str]:
    """Zalomí text do řádků široké nejvýš `width` mm (po slovech, příliš dlouhé slovo po znacích). Zalomení řádku
    v textu se zachová; prázdný text = jeden prázdný řádek."""
    out: list[str] = []
    for para in str(text).split("\n"):
        line = ""
        for word in para.split():
            cand = f"{line} {word}" if line else word
            if text_width(cand, height) <= width:
                line = cand
                continue
            if line:
                out.append(line)
                line = ""
            while text_width(word, height) > width and len(word) > 1:   # slovo širší než sloupec → po znacích
                k = len(word) - 1
                while k > 1 and text_width(word[:k], height) > width:
                    k -= 1
                out.append(word[:k])
                word = word[k:]
            line = word
        out.append(line)
    return out or [""]


def elide_text(text: str, width: float, height: float = 2.5) -> str:
    """Text zkrácený na `width` mm s „…“ na konci (beze změny, když se vejde)."""
    if text_width(text, height) <= width:
        return text
    k = len(text)
    while k > 0 and text_width(text[:k].rstrip() + "…", height) > width:
        k -= 1
    return text[:k].rstrip() + "…" if k else "…"


def draw_frame(painter: QPainter, geom, color) -> None:
    """Rámeček a popisové pole z `model/frame.py` (geometrie v mm, Y nahoru). Nic, když je rámeček vypnutý."""
    from envocad.model.frame import frame_enabled
    if not frame_enabled():
        return
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


def draw_geometry(painter: QPainter, geom, color, width: float = 0.25) -> None:
    """Geometrie z modelu (čáry, texty, plné obdélníky; mm, Y nahoru) jednotnou tenkou čarou, bez ohledu na rámeček."""
    painter.save()
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(color, width))
    for x1, y1, x2, y2 in geom.lines:
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


def draw_revision_marks(painter: QPainter, geom, color) -> None:
    """Značky revize (trojúhelníky s označením) z `model/revision.py:revision_geometry` – geometrie v mm, Y nahoru."""
    if not geom.polylines:
        return
    painter.save()
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(color, 0.35))
    for pts in geom.polylines:
        painter.drawPolygon([sp(x, y) for x, y in pts])
    painter.setPen(QPen(color, 0.2))
    for x, y, text, h, align in geom.texts:
        if text:
            draw_text(painter, x, y, text, h, align)
    painter.restore()


def draw_note_shape(painter: QPainter, shape, color, dash_first: bool = False) -> None:
    """Kresba připomínky z `model/notes.py:note_shape` (mm, Y nahoru). `dash_first` = první polyline (obrys
    obdélníku) čárkovaně; praporek a čáry plně."""
    painter.save()
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(color, 0.35))
    for x1, y1, x2, y2 in shape.lines:
        painter.drawLine(sp(x1, y1), sp(x2, y2))
    for i, pts in enumerate(shape.polylines):
        painter.setPen(QPen(color, 0.35, Qt.DashLine if dash_first and i == 0 else Qt.SolidLine))
        painter.drawPolygon([sp(x, y) for x, y in pts])
    painter.setPen(QPen(color, 0.2))
    for x, y, text, h, align in shape.texts:
        if text:
            draw_text(painter, x, y, text, h, align)
    painter.restore()
