"""QGraphicsItem obaly nad modelem (Element, Wire). Nemění model samy – to dělají příkazy v commands.py."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QStyleOptionGraphicsItem, QWidget

from envocad.model.project import Element, Wire, wire_label
from envocad.model.symbol import GRID, Symbol, rotate_dir
from envocad.ui.render import LINE_WIDTH, draw_text, paint_symbol, sp, symbol_path
from envocad.ui.theme import colors

PORT_R = 0.8

DIR_VEC = {"N": (0, 1), "E": (1, 0), "S": (0, -1), "W": (-1, 0)}


def snap(v: float) -> float:
    return round(v / GRID) * GRID


class ElementItem(QGraphicsItem):
    Type = QGraphicsItem.UserType + 1

    def __init__(self, element: Element, symbol: Symbol):
        super().__init__()
        self.element = element
        self.symbol = symbol
        self._path = symbol_path(symbol)
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setZValue(10)
        self.sync_from_model()

    def type(self) -> int:
        return self.Type

    # ---- model ↔ item ----------------------------------------------------
    def sync_from_model(self) -> None:
        self.setPos(sp(self.element.x, self.element.y))
        self.setRotation(-self.element.rotation)  # Qt otáčí po směru hod. ručiček
        self.prepareGeometryChange()
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            return QPointF(snap(value.x()), snap(value.y()))
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            self.scene().element_moved(self)
        return super().itemChange(change, value)

    # ---- geometrie --------------------------------------------------------
    def boundingRect(self) -> QRectF:
        x0, y0, x1, y1 = self.symbol.bounds()
        lx, ly = self.symbol.label_pos
        x0, x1, y0, y1 = min(x0, lx), max(x1, lx), min(y0, ly), max(y1, ly)
        texts = [self.element.ref] + self.symbol.label_lines(self.element.attrs)
        w = max((len(t) for t in texts), default=0) * 2.5 * 0.75 + 4
        h = 3.5 * len(texts) + 4
        m = max(w, h)   # popisek může být vpravo/vlevo/nad/pod značkou (rozmístění) a prvek otočený
        return QRectF(x0, -y1, x1 - x0, y1 - y0).adjusted(-m, -m, m, m)

    def shape(self) -> QPainterPath:
        x0, y0, x1, y1 = self.symbol.bounds()
        p = QPainterPath()
        p.addRect(QRectF(x0, -y1, x1 - x0, y1 - y0).adjusted(-1, -1, 1, 1))
        return p

    def port_scene_pos(self, name: str) -> QPointF:
        p = self.symbol.port(name)
        return self.mapToScene(sp(p.x, p.y))

    def port_dir(self, name: str) -> str:
        return rotate_dir(self.symbol.port(name).dir, self.element.rotation)

    def port_at(self, scene_pos: QPointF, tol: float = 2.0) -> str | None:
        for p in self.symbol.ports:
            if (self.port_scene_pos(p.name) - scene_pos).manhattanLength() <= tol:
                return p.name
        return None

    # ---- kreslení ---------------------------------------------------------
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        c = colors()
        color = c.selection if self.isSelected() else c.ink
        paint_symbol(painter, self.symbol, QPen(color, LINE_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        # porty
        painter.setPen(QPen(c.port, 0.2))
        painter.setBrush(Qt.NoBrush)
        for p in self.symbol.ports:
            painter.drawEllipse(sp(p.x, p.y), PORT_R, PORT_R)
        # popisky – vždy vodorovně (kompenzuje se rotace); poloha z rozmístění scény (volné místo), jinak výchozí
        sc = self.scene()
        lab = sc.element_label(self.element) if hasattr(sc, "element_label") else None
        painter.save()
        painter.setPen(QPen(color, 0.2))
        if lab is not None:
            painter.rotate(self.element.rotation)   # do souřadnic listu (bez otočení prvku), počátek = prvek
            for x, y, text, h in lab.lines:
                draw_text(painter, x - self.element.x, y - self.element.y, text, h, lab.align)
            painter.restore()
            return
        lx, ly = self.symbol.label_pos
        painter.translate(sp(lx, ly))
        painter.rotate(self.element.rotation)
        line = 0.0
        if self.element.ref:
            draw_text(painter, 0, line, self.element.ref, 2.5, "left")
            line -= 3.5
        for text in self.symbol.label_lines(self.element.attrs):
            draw_text(painter, 0, line, text, 2.0, "left")
            line -= 3.0
        xref = sc.element_xref(self.element) if hasattr(sc, "element_xref") else ""
        for ln in xref.splitlines():  # zrcadlo kontaktů může mít více řádků
            draw_text(painter, 0, line, ln, 2.0, "left")
            line -= 3.0
        painter.restore()


class WireItem(QGraphicsPathItem):
    Type = QGraphicsItem.UserType + 2

    def __init__(self, wire: Wire):
        super().__init__()
        self.wire = wire
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setZValue(5)
        self.setPen(QPen(colors().wire, LINE_WIDTH * 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    def type(self) -> int:
        return self.Type

    def shape(self) -> QPainterPath:
        from PySide6.QtGui import QPainterPathStroker
        s = QPainterPathStroker()
        s.setWidth(2.5)
        return s.createStroke(self.path())

    def set_points(self, pts: list[tuple[float, float]]) -> None:
        """Trasa z modelu (souřadnice listu, Y nahoru) – viz model/routing.py."""
        path = QPainterPath(sp(*pts[0]))
        for x, y in pts[1:]:
            path.lineTo(sp(x, y))
        self.setPath(path)

    def update_route(self, a: ElementItem, b: ElementItem) -> None:
        pa, pb = a.port_scene_pos(self.wire.a.port), b.port_scene_pos(self.wire.b.port)
        da, db = a.port_dir(self.wire.a.port), b.port_dir(self.wire.b.port)
        self.setPath(route(pa, da, pb, db, [sp(x, y) for x, y in self.wire.points]))

    def paint(self, painter, option, widget=None):
        pen = QPen(self.pen())
        pen.setColor(colors().selection if self.isSelected() else colors().wire)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())
        sc = self.scene()
        lp = sc.wire_label_pos(self.wire) if hasattr(sc, "wire_label_pos") else None
        if lp is None:
            label = wire_label(self.wire.attrs, self.wire.conductors)
            xref = sc.wire_xref(self.wire) if hasattr(sc, "wire_xref") else ""
            if not (label or xref):
                return
            from envocad.model.textlayout import _candidates
            lp = _candidates(path_points(self.path()), bool(self.wire.points), label, xref)[0]
        painter.setPen(QPen(pen.color(), 0.2))
        for x, y, text, h in lp.lines:
            draw_text(painter, x, y, text, h, lp.align)
        if lp.mark is not None:  # značka na vodiči jako v EPLAN (krátká šikmá čárka u popisku)
            mx, my = lp.mark
            painter.setPen(QPen(pen.color(), 0.3))
            painter.drawLine(sp(mx - 1.2, my - 1.2), sp(mx + 1.2, my + 1.2))


def path_points(path: QPainterPath) -> list[tuple[float, float]]:
    """Body lomené čáry z QPainterPath převedené do souřadnic modelu (Y nahoru)."""
    return [(path.elementAt(i).x, -path.elementAt(i).y) for i in range(path.elementCount())]




def route(pa: QPointF, da: str, pb: QPointF, db: str, mid: list[QPointF], stagger: float = 0.0,
          jog: float = 0.5) -> QPainterPath:
    """Ortogonální trasa port→port. S ručními body (mid) jde přes ně, jinak jednoduché L/Z vedení.
    `stagger` posune lom Z-trasy (vícepól: rovnoběžné žíly se nepřekrývají), `jog` = kde po délce je příčka
    (0,5 uprostřed; vícepól používá 0,8 – blízko cíle, aby příčka nevedla přes prvky v mezilehlých sloupcích)."""
    stub = GRID
    va, vb = DIR_VEC[da], DIR_VEC[db]
    sa = QPointF(pa.x() + va[0] * stub, pa.y() - va[1] * stub)
    sb = QPointF(pb.x() + vb[0] * stub, pb.y() - vb[1] * stub)
    path = QPainterPath(pa)
    path.lineTo(sa)
    if mid:
        # ruční body: jen svislé/vodorovné úseky (roh se doplní, kdyby bod nebyl v ose portu)
        from envocad.model.geometry import orthogonalize
        pts = orthogonalize([(sa.x(), sa.y())] + [(m.x(), m.y()) for m in mid] + [(sb.x(), sb.y())],
                            end_horizontal=db in ("E", "W"))
        path = QPainterPath(pa)
        for x, y in pts:
            path.lineTo(QPointF(x, y))
        path.lineTo(pb)
        return path
    else:
        horizontal_first = da in ("E", "W")
        if horizontal_first and db in ("E", "W") and abs(sa.y() - sb.y()) > 1e-6:
            # Z-trasa: lom uprostřed
            mx = snap(sa.x() + (sb.x() - sa.x()) * jog) + stagger
            path.lineTo(QPointF(mx, sa.y()))
            path.lineTo(QPointF(mx, sb.y()))
        elif not horizontal_first and db in ("N", "S") and abs(sa.x() - sb.x()) > 1e-6:
            my = snap(sa.y() + (sb.y() - sa.y()) * jog) + stagger
            path.lineTo(QPointF(sa.x(), my))
            path.lineTo(QPointF(sb.x(), my))
        elif horizontal_first:
            path.lineTo(QPointF(sb.x(), sa.y()))
        else:
            path.lineTo(QPointF(sa.x(), sb.y()))
    path.lineTo(sb)
    path.lineTo(pb)
    return path
