"""QGraphicsItem obaly nad modelem (Element, Wire). Nemění model samy – to dělají příkazy v commands.py."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QStyleOptionGraphicsItem, QWidget

from envocad.model.geometry import wire_label_anchor
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
        r = QRectF(x0, -y1, x1 - x0, y1 - y0).adjusted(-3, -8, 20, 3)
        return r

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
        # popisky – vždy vodorovně, proto se při otočení kompenzuje rotace
        painter.save()
        lx, ly = self.symbol.label_pos
        painter.translate(sp(lx, ly))
        painter.rotate(self.element.rotation)
        painter.setPen(QPen(color, 0.2))
        line = 0.0
        if self.element.ref:
            draw_text(painter, 0, line, self.element.ref, 2.5, "left")
            line -= 3.5
        for a in self.symbol.attributes:
            if a.show and a.key != "ref" and self.element.attrs.get(a.key):
                draw_text(painter, 0, line, self.element.attrs[a.key], 2.0, "left")
                line -= 3.0
        sc = self.scene()
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
        label = wire_label(self.wire.attrs, self.wire.conductors)
        sc = self.scene()
        xref = sc.wire_xref(self.wire) if hasattr(sc, "wire_xref") else ""
        if label or xref:
            pts = path_points(self.path())
            x, y, align, vertical = wire_label_anchor(pts)
            if self.wire.points and len(pts) >= 2 and abs(pts[1][1] - pts[0][1]) < 1e-6:
                # ručně lomený vodič: popisek u začátku prvního (vodorovného) úseku jako v EPLAN, ne na nejdelším
                x, y, align, vertical = min(pts[0][0], pts[1][0]) + 1.5, pts[0][1] + 1.5, "left", False
            painter.setPen(QPen(pen.color(), 0.2))
            # křížový odkaz na druhý řádek (pod vodorovný vodič / pod popisek u svislého), aby se krátké úseky nepřekrývaly
            if label:
                draw_text(painter, x, y, label, 2.0, align)
            if xref:
                draw_text(painter, x, y - (3.0 if label else 0.0) - (1.5 if not vertical and label else 0.0), xref, 1.8, align)
            if vertical:  # značka na vodiči jako v EPLAN (krátká šikmá čárka u popisku)
                painter.setPen(QPen(pen.color(), 0.3))
                painter.drawLine(sp(x - 1.5 - 1.2, y + 1.0 - 1.2), sp(x - 1.5 + 1.2, y + 1.0 + 1.2))


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
        for m in mid:
            path.lineTo(m)
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
