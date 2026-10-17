"""Vícepólový pohled: odvozená scéna nad stejným listem jako JPS.

Geometrie se počítá v `model/multipole.py`; tady se jen kreslí. Prvky se v tomto pohledu neposouvají
(JPS je řídící), dvojklik na prvek upraví parametry, dvojklik na žílu otevře přiřazení svorek vodiče.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPainterPathStroker, QPen, QTransform, QUndoStack
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene

from envocad.library.store import LibraryStore
from envocad.model import multipole as mp
from envocad.model.project import Element, Project, Sheet, Wire, element_symbol, wire_label
from envocad.model.symbol import GRID, Symbol, rotate_dir
from envocad.ui import commands
from envocad.ui.canvas import Mode, SchematicView
from envocad.ui.items import PORT_R, path_points, snap
from envocad.ui.render import LINE_WIDTH, draw_frame, draw_text, paint_symbol, sp, symbol_path
from envocad.ui.theme import PRINT, colors

log = logging.getLogger("envocad.ui")


class PoleItem(QGraphicsItem):
    """Jeden pól prvku (opakovaný symbol) nebo celý neprůchozí prvek."""
    Type = QGraphicsItem.UserType + 11

    def __init__(self, ep: mp.ElementPoles, conductor: str | None, first: bool):
        super().__init__()
        self.ep, self.conductor, self.first = ep, conductor, first
        self.element: Element = ep.element
        self.full_symbol: Symbol = ep.symbol
        # průchozí prvek ve vícepólu: značka jednoho pólu (+ společná část u prvního pólu)
        self.symbol: Symbol = ep.symbol.pole_symbol() if conductor else ep.symbol
        self.common: Symbol | None = ep.symbol.common_symbol() if (conductor and first) else None
        self._path = symbol_path(self.symbol)
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable)
        self.setZValue(10)
        ox, oy = ep.pole_offset(conductor) if conductor else (0.0, 0.0)
        self._offset = (ox, oy)
        self.setPos(sp(ep.origin[0] + ox, ep.origin[1] + oy))
        self.setRotation(-self.element.rotation)

    def element_origin(self) -> tuple[float, float]:
        """Pozice prvku ve vícepólu odvozená z aktuální pozice položky (po tažení myší)."""
        return (snap(self.pos().x()) - self._offset[0], -snap(self.pos().y()) - self._offset[1])

    def type(self) -> int:
        return self.Type

    def boundingRect(self) -> QRectF:
        x0, y0, x1, y1 = self.full_symbol.bounds()
        r = QRectF(x0, -y1, x1 - x0, y1 - y0).adjusted(-3, -8, 20, 3).united(self.shape().boundingRect())
        if self.first:
            from envocad.model.symbol import rotate_point
            from envocad.model.textlayout import text_box
            for dx, dy, text, h, align in self._label_lines():
                bx0, by0, bx1, by1 = text_box(dx, dy, text, h, align)
                # osy scény → lokální osy položky (otočené o −rotation)
                pts = [rotate_point(px, py, -self.element.rotation) for px, py in ((bx0, by0), (bx1, by1), (bx0, by1), (bx1, by0))]
                xs, ys = [q[0] for q in pts], [q[1] for q in pts]
                r = r.united(QRectF(min(xs) - 1, -max(ys) - 1, max(xs) - min(xs) + 2, max(ys) - min(ys) + 2))
        return r

    def _terminal_num(self) -> str | None:
        """Číslo svorky kreslené vedle pólu svorkovnice (None, když se nekreslí)."""
        if not (self.conductor and mp.is_terminal_block(self.element)):
            return None
        return mp.terminal_numbers(self.element, len(self.ep.slots))[self.ep.slot(self.conductor)] or "?"

    def shape(self) -> QPainterPath:
        x0, y0, x1, y1 = self.symbol.bounds()
        p = QPainterPath()
        p.setFillRule(Qt.WindingFill)
        p.addRect(QRectF(x0, -y1, x1 - x0, y1 - y0).adjusted(-1, -1, 1, 1))
        num = self._terminal_num()
        if num is not None:
            # svorka: chytit jde i za číslo; to je ve scéně vždy vodorovně, proto plochu otočíme stejně jako text
            a = sp(x1 + 1.0, y0 + 1.0)
            t = QTransform().translate(a.x(), a.y()).rotate(self.element.rotation)
            p.addPolygon(t.map(QRectF(-0.5, -2.8, len(num) * 1.6 + 1.0, 3.5)))
        return p

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        c = colors()
        color = c.selection if self.isSelected() else c.ink
        pen = QPen(color, LINE_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        paint_symbol(painter, self.symbol, pen)
        if self.common is not None:
            paint_symbol(painter, self.common, pen)
        painter.setPen(QPen(c.port, 0.2))
        painter.setBrush(Qt.NoBrush)
        for p in self.symbol.ports:
            painter.drawEllipse(sp(p.x, p.y), PORT_R, PORT_R)
        num = self._terminal_num()
        if num is not None:
            # číslo svorky vedle značky (vždy vodorovně)
            painter.save()
            _x0, y0, x1, _y1 = self.symbol.bounds()
            painter.translate(sp(x1 + 1.0, y0 + 1.0))
            painter.rotate(self.element.rotation)
            painter.setPen(QPen(color, 0.2))
            draw_text(painter, 0, 0, num, 2.0, "left")
            painter.restore()
        if not self.first:
            return
        # popisek prvku (označení, parametry) – poloha z modelu (`mp.pole_label_lines`, stejně počítá kontrola
        # překryvů); kreslí se vodorovně relativně k položce, aby se při tažení posouval s ní
        painter.setPen(QPen(color, 0.2))
        for dx, dy, text, h, align in self._label_lines():
            painter.save()
            painter.rotate(self.element.rotation)   # zpět do os scény (položka je otočená o −rotation)
            draw_text(painter, dx, dy, text, h, align)
            painter.restore()

    def _label_lines(self) -> list[tuple[float, float, str, float, str]]:
        """Řádky popisku relativně k počátku položky (osy scény, Y nahoru)."""
        ax, ay = self.ep.origin[0] + self._offset[0], self.ep.origin[1] + self._offset[1]
        return [(x - ax, y - ay, text, h, align) for x, y, text, h, align in mp.pole_label_lines(self.ep)]


class PoleLinkItem(QGraphicsPathItem):
    """Čárkovaná mechanická vazba pólů (jistič, vypínač, stykač…)."""

    def __init__(self, ep: mp.ElementPoles):
        super().__init__()
        from envocad.model.symbol import rotate_point
        e, sym = ep.element, ep.symbol
        lx, ly = sym.link_at
        rx, ry = rotate_point(lx, ly, e.rotation)
        pts = []
        for c in ep.switched:
            ox, oy = ep.pole_offset(c)
            pts.append((ep.origin[0] + ox + rx, ep.origin[1] + oy + ry))
        path = QPainterPath(sp(*pts[0]))
        path.lineTo(sp(*pts[-1]))
        self.setPath(path)
        self.setZValue(9)
        self.setPen(QPen(colors().ink, LINE_WIDTH * 0.8, Qt.DashLine))

    def paint(self, painter, option, widget=None):
        painter.setPen(QPen(colors().ink, LINE_WIDTH * 0.8, Qt.DashLine))
        painter.drawPath(self.path())


class BypassItem(QGraphicsPathItem):
    """Žíla, která prochází kolem prvku (N u 3p jističe, PE)."""

    def __init__(self, ep: mp.ElementPoles, conductor: str):
        super().__init__()
        a, b = ep.through
        pa, pb = ep.pole_pos(a, conductor), ep.pole_pos(b, conductor)
        path = QPainterPath(sp(*pa))
        path.lineTo(sp(*pb))
        self.setPath(path)
        self.setZValue(5)
        self.setPen(QPen(colors().wire, LINE_WIDTH * 1.5, Qt.SolidLine, Qt.RoundCap))


class PeJoinItem(QGraphicsPathItem):
    """Příčka spojující konce pólů na portu PE (svodič přepětí) s PE vodičem; tečka v místě odbočky PE."""

    def __init__(self, a: tuple[float, float], b: tuple[float, float]):
        super().__init__()
        path = QPainterPath(sp(*a))
        path.lineTo(sp(*b))
        self.setPath(path)
        self.setZValue(5)
        self.setPen(QPen(colors().wire, LINE_WIDTH * 1.5, Qt.SolidLine, Qt.RoundCap))


class BridgeItem(QGraphicsPathItem):
    """Můstek (propoj) mezi svorkami jedné svorkovnice – čárkovaná čára podél řady svorek (u portu 1), ne sběrnice."""

    def __init__(self, strip: str, group: list[str], points: list[tuple[float, float]]):
        super().__init__()
        self.strip, self.group, self.points = strip, group, points
        path = QPainterPath(sp(*points[0]))
        for pt in points[1:]:
            path.lineTo(sp(*pt))
        self.setPath(path)
        self.setZValue(7)
        self.setToolTip(f"Můstek {strip}: {'-'.join(group)}")
        self.setPen(QPen(colors().ink, LINE_WIDTH * 0.8, Qt.DashLine, Qt.FlatCap, Qt.RoundJoin))

    def paint(self, painter, option, widget=None):
        painter.setPen(QPen(colors().ink, LINE_WIDTH * 0.8, Qt.DashLine, Qt.FlatCap, Qt.RoundJoin))
        painter.drawPath(self.path())
        painter.setBrush(colors().ink)
        painter.setPen(QPen(colors().ink, LINE_WIDTH))
        for x, y in self.points:
            painter.drawEllipse(sp(x, y), 0.5, 0.5)


class PageBreakItem(QGraphicsItem):
    """Přerušení žíly na okraji strany: šipka a odkaz na pokračování („/3.2.B4“ = list 3, strana 2, sloupec B řádek 4)."""

    def __init__(self, x: float, y: float, outgoing: bool, text: str):
        super().__init__()
        self.x_, self.y_, self.outgoing, self.text = x, y, outgoing, text
        self.setZValue(6)
        self.setPos(sp(x, y))

    def boundingRect(self) -> QRectF:
        return QRectF(-40, -6, 80, 12)

    def paint(self, painter, option, widget=None):
        c = colors().ink if self.scene() is None or self.scene().draw_grid else PRINT.ink
        painter.setPen(QPen(c, LINE_WIDTH))
        d = 1.0 if self.outgoing else -1.0
        # šipka ve směru toku ze strany ven (odchozí) / do strany (příchozí)
        painter.drawLine(QPointF(0, 0), QPointF(-3 * d, -2))
        painter.drawLine(QPointF(0, 0), QPointF(-3 * d, 2))
        painter.setPen(QPen(c, 0.2))
        draw_text(painter, 1.5 if self.outgoing else -1.5, 1.0, self.text, 1.8, "left" if self.outgoing else "right")


BUS = "sb.busbar"
BUS_PITCH = 5.0   # rozteč čar potenciálů sběrnice (mm)


class BusItem(QGraphicsItem):
    """Sběrnice potenciálů na jedné straně jako v EPLAN: vodorovná čára na každou žílu přes šířku strany,
    název potenciálu (1L1…) se šipkou na obou koncích, tečky v místech odboček."""

    def __init__(self, element: Element, conductors: list[str], x0: float, x1: float, ys: dict[str, float],
                 taps: list[tuple[float, float]], first: bool, prefix: str):
        super().__init__()
        self.element, self.conductors, self.x0, self.x1, self.ys, self.taps, self.first, self.prefix = \
            element, conductors, x0, x1, ys, taps, first, prefix
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setZValue(4)

    def boundingRect(self) -> QRectF:
        ys = list(self.ys.values()) or [0.0]
        return QRectF(self.x0 - 20, -max(ys) - 8, self.x1 - self.x0 + 40, max(ys) - min(ys) + 16)

    def paint(self, painter, option, widget=None):
        c = colors()
        ink = c.selection if self.isSelected() else c.ink
        pen = QPen(ink, LINE_WIDTH * 1.5, Qt.SolidLine, Qt.FlatCap)
        for cond in self.conductors:
            y = self.ys[cond]
            painter.setPen(pen)
            painter.drawLine(sp(self.x0, y), sp(self.x1, y))
            # šipky potenciálu na koncích + název (předpona sběrnice + žíla)
            name = f"{self.prefix}{cond}"
            for x, d in ((self.x0, -1.0), (self.x1, 1.0)):
                painter.drawLine(sp(x, y), sp(x - 2.5 * d, y + 1.2))
                painter.drawLine(sp(x, y), sp(x - 2.5 * d, y - 1.2))
            painter.setPen(QPen(ink, 0.2))
            draw_text(painter, self.x0 - 1.5, y - 0.8, name, 2.0, "right")
            draw_text(painter, self.x1 + 1.5, y - 0.8, name, 2.0, "left")
        painter.setBrush(ink)
        painter.setPen(QPen(ink, LINE_WIDTH))
        for x, y in self.taps:
            painter.drawEllipse(sp(x, y), 0.7, 0.7)
        if self.first and self.element.attrs.get("desc"):
            painter.setPen(QPen(ink, 0.2))
            top = max(self.ys.values())
            draw_text(painter, self.x1, top + 4.5, self.element.attrs.get("desc", ""), 2.0, "right")


class CableTagItem(QGraphicsItem):
    """Štítek kabelu na hraně rozvaděče (styl ENVO/EPLAN): rámeček se třemi řádky – označení kabelu, název
    (odkud/kam), typ kabelu; žíly přívodu/vývodu do něj vstupují."""

    ROW = 3.2

    def __init__(self, x0: float, x1: float, y_edge: float, rows: list[str], up: bool, element_id: str = ""):
        super().__init__()
        self.element_id = element_id   # přívod/vývod, ke kterému štítek patří: dvojklik = parametry, tažení = posun
        self.highlight = False         # vybrán přívod/vývod (štítek sám vybrat nejde, výběr drží jeho svorky)
        if element_id:
            self.setFlags(QGraphicsItem.ItemIsMovable)
            self.setCursor(Qt.SizeAllCursor)
        self.rows = [r for r in rows if r] or ["?"]
        w = max(x1 - x0 + 4.0, max(len(r) for r in self.rows) * 1.25 + 3.0)
        cx = (x0 + x1) / 2
        self.x0, self.x1 = cx - w / 2, cx + w / 2
        self.y_edge, self.up = y_edge, up
        self.h = self.ROW * len(self.rows)
        self.setZValue(6)

    def _rect(self) -> QRectF:
        top = self.y_edge + self.h if self.up else self.y_edge
        return QRectF(sp(self.x0, top), sp(self.x1, top - self.h)).normalized()

    def boundingRect(self) -> QRectF:
        return self._rect().adjusted(-1, -1, 1, 1)

    def paint(self, painter, option, widget=None):
        ink = colors().ink if self.scene() is None or self.scene().draw_grid else PRINT.ink
        if self.highlight:
            ink = colors().selection
        painter.setPen(QPen(ink, LINE_WIDTH))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self._rect())
        top = self.y_edge + self.h if self.up else self.y_edge
        for i, text in enumerate(self.rows):
            y = top - (i + 1) * self.ROW
            if i:
                painter.setPen(QPen(ink, LINE_WIDTH * 0.6))
                painter.drawLine(sp(self.x0, y + self.ROW), sp(self.x1, y + self.ROW))
            painter.setPen(QPen(ink, 0.2))
            draw_text(painter, (self.x0 + self.x1) / 2, y + 0.8, text, 2.0 if i == 0 else 1.7, "center")


class TitleItem(QGraphicsItem):
    """Nadpis výkresu rozvaděče vlevo nahoře na každé straně: označení (podtržené) a pod ním parametry
    (soustava, Un, In, Ik'', skříň, krytí) – jako na výkresech ENVO."""

    def __init__(self, x: float, y_top: float, lines: list[str]):
        super().__init__()
        self.lines = lines
        self.setPos(sp(x, y_top))
        self.setZValue(3)

    def boundingRect(self) -> QRectF:
        return QRectF(-2, -2, 200, 20)

    def paint(self, painter, option, widget=None):
        ink = colors().ink if self.scene() is None or self.scene().draw_grid else PRINT.ink
        painter.setPen(QPen(ink, 0.25))
        y = 0.0
        for i, text in enumerate(self.lines):
            h = 5.0 if i == 0 else 3.0
            y -= h
            draw_text(painter, 0, y, text, h, "left")
            if i == 0:
                painter.drawLine(sp(0, y - 1.0), sp(len(text) * h * 0.72, y - 1.0))
                y -= 2.8
            y -= 1.2


class ConductorItem(QGraphicsPathItem):
    """Jedna žíla vodiče mezi póly dvou prvků."""
    Type = QGraphicsItem.UserType + 12

    def __init__(self, wire: Wire, conductor: str, idx: int, pa: QPointF, da: str, pb: QPointF, db: str,
                 end_text: tuple[str, str] = ("", "")):
        super().__init__()
        self.wire, self.conductor, self.idx = wire, conductor, idx
        self.end_text = end_text
        self.staggered = False   # žíla vícežilového vodiče na Z-trase (popisek mimo příčku) – nastaví scéna
        self.label: tuple[float, float, str, str] | None = None   # (x, y, text, zarovnání) z modelu – nastaví scéna
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setZValue(5)
        self.setPen(QPen(colors().wire, LINE_WIDTH * 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        pts = mp.conductor_route((pa.x(), -pa.y()), da, (pb.x(), -pb.y()), db, stagger=idx * GRID, jog=0.8)
        path = QPainterPath(sp(*pts[0]))
        for q in pts[1:]:
            path.lineTo(sp(*q))
        self.setPath(path)
        self._da, self._db = da, db

    def type(self) -> int:
        return self.Type

    def shape(self) -> QPainterPath:
        s = QPainterPathStroker()
        s.setWidth(2.5)
        return s.createStroke(self.path())

    def paint(self, painter, option, widget=None):
        pen = QPen(self.pen())
        pen.setColor(colors().selection if self.isSelected() else colors().wire)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())
        painter.setPen(QPen(pen.color(), 0.2))
        pts = path_points(self.path())
        if self.label is not None:   # rozmístěno modelem (`multipole_geometry`) mimo cizí čáry a texty
            x, y, text, align = self.label
        else:
            x, y, align, _vertical = mp.conductor_label_anchor(pts, self.staggered)
            text = self.conductor
            if self.idx == 0:
                lbl = wire_label(self.wire.attrs)
                text = f"{lbl}  {text}" if lbl else text
        draw_text(painter, x, y, text, 1.8, align)
        # svorky na koncích
        for t, (px, py), d in ((self.end_text[0], pts[0], self._da), (self.end_text[1], pts[-1], self._db)):
            if not t:
                continue
            dx, dy = {"E": (1.5, 0.8), "W": (-1.5, 0.8), "N": (0.8, 1.5), "S": (0.8, -3.0)}[d]
            draw_text(painter, px + dx, py + dy, t, 1.8, "right" if d == "W" else "left")


class MultipoleScene(QGraphicsScene):
    selection_info = Signal(object)   # PoleItem | ConductorItem | None
    edit_element_requested = Signal(str)
    delete_requested = Signal(list, list)  # element_ids, wire_ids
    mode_changed = Signal(object)

    # ---- editace přímo ve schématu rozvaděče ---------------------------------------------------------
    def set_mode(self, mode) -> None:
        if getattr(self, "_ghost", None) is not None:
            self.removeItem(self._ghost)
        self._ghost = None
        if getattr(self, "_preview", None) is not None:
            self.removeItem(self._preview)
        self._preview = None
        self._wire_from = None
        self._place_sid = None
        self.mode = mode
        self.mode_changed.emit(mode)

    def start_place(self, symbol_id: str) -> None:
        """Vložení prvku z knihovny: klik umístí (ruční pozice ve vícepólu), R otočí, Esc/pravé tlačítko ukončí."""
        self.set_mode(Mode.PLACE)
        self._place_sid = symbol_id
        sym = self.library.get_symbol(symbol_id)
        # ve schématu rozvaděče teče proud shora dolů – průchozí přístroje (porty W/E) se otočí svisle
        self._place_rot = 270 if {p.dir for p in sym.ports} == {"W", "E"} and len(sym.ports) == 2 else 0
        self._ghost = QGraphicsPathItem(symbol_path(sym))
        self._ghost.setPen(QPen(colors().preview, LINE_WIDTH, Qt.DashLine))
        self._ghost.setRotation(-self._place_rot)
        self._ghost.setZValue(50)
        self.addItem(self._ghost)

    def start_wire(self) -> None:
        self.set_mode(Mode.WIRE)

    def insert_fragment(self, fragment: dict, at: tuple[float, float] | None = None) -> int:
        """Makro do schématu rozvaděče: prvky dostanou ruční pozice ve vícepólu kolem bodu `at`."""
        from envocad.library.macros import fragment_bounds
        from envocad.model.project import paste_fragment
        x0, y0, x1, y1 = fragment_bounds(fragment)
        tx, ty = at if at is not None else (self.sheet.width / 2, self.sheet.height / 2)
        dx, dy = snap(tx - (x0 + x1) / 2), snap(ty - (y0 + y1) / 2)
        els, wires = paste_fragment(self.project, fragment, lambda sid: self.library.get_symbol(sid).iec_ref, dx, dy)
        for e in els:
            e.mp_pos = (e.x, e.y)
        if els:
            self.undo.push(commands.MultipoleAddCommand(self, elements=els, wires=wires))
        return len(els)

    def insert_macro(self, m, values: dict, at: tuple[float, float] | None = None) -> int:
        """Vloží makro s hodnotami proměnných (`expand`, opakování) jedním undo příkazem. Vrací počet nových prvků
        (sloučené `shared` prvky nejsou nové)."""
        from envocad.library.macros import expand, fragment_bounds
        x0, y0, x1, y1 = fragment_bounds(m.fragment)
        tx, ty = at if at is not None else (self.sheet.width / 2, self.sheet.height / 2)
        dx, dy = snap(tx - (x0 + x1) / 2), snap(ty - (y0 + y1) / 2)
        els, wires = expand(self.project, self.sheet, m, values, dx, dy,
                            ref_prefix_of=lambda sid: self.library.get_symbol(sid).iec_ref,
                            components=self.library.component, repeat=True)
        if not els and not wires:
            return 0
        for e in els:
            e.mp_pos = (e.x, e.y)
        self.undo.push(commands.MultipoleAddCommand(self, elements=els, wires=wires, text=f"Vložit makro {m.name}"))
        return len(els)

    def rotate_selected(self) -> None:
        if self.mode == Mode.PLACE and self._ghost is not None:
            self._place_rot = (self._place_rot + 90) % 360
            self._ghost.setRotation(-self._place_rot)

    def _pole_end_at(self, pos: QPointF) -> tuple[str, str, str | None, tuple[float, float]] | None:
        """Konec pólu pod kurzorem: (prvek, port, žíla nebo None, pozice v modelu)."""
        x, y = pos.x(), -pos.y()
        best = None
        for e in self.sheet.elements:
            ep = self._poles.get(e.id)
            if ep is None:
                continue
            conds = list(ep.slots) or [None]
            for p in ep.symbol.ports:
                for c in conds:
                    try:
                        px, py = ep.pole_pos(p.name, c) if c else ep.pole_pos(p.name, "")
                    except (KeyError, ValueError):
                        continue
                    d = abs(px - x) + abs(py - y)
                    if d <= GRID * 1.2 and (best is None or d < best[0]):
                        best = (d, e.id, p.name, c, (px, py))
        return best[1:] if best else None

    def _place_at(self, pos: QPointF) -> None:
        from envocad.model.project import Element
        sym = self.library.get_symbol(self._place_sid)
        x, y = snap(pos.x()), -snap(pos.y())
        e = Element(symbol_id=sym.id, x=x, y=y, rotation=self._place_rot)
        e.attrs = {a.key: a.default for a in sym.attributes}
        e.attrs["ref"] = self.project.next_ref(sym.iec_ref) if sym.iec_ref else ""
        e.mp_pos = (x, y)
        self.undo.push(commands.MultipoleAddCommand(self, element=e))
        eid = e.id
        QTimer.singleShot(0, lambda: self.edit_element_requested.emit(eid))   # parametry hned po vložení

    def _wire_click(self, pos: QPointF) -> None:
        from envocad.model.project import WIRE_ATTRIBUTES, Wire, WireEnd
        hit = self._pole_end_at(pos)
        if hit is None:
            return
        if self._wire_from is None:
            self._wire_from = hit
            self._preview = QGraphicsPathItem()
            self._preview.setPen(QPen(colors().preview, 0.3, Qt.DashLine))
            self._preview.setZValue(50)
            self.addItem(self._preview)
            return
        (ea, pa, ca, _), (eb, pb, cb, _) = self._wire_from, hit
        if self._preview is not None:
            self.removeItem(self._preview)
        self._preview = None
        self._wire_from = None
        if ea == eb and pa == pb:
            return
        a, b = self.sheet.element(ea), self.sheet.element(eb)
        conds = [ca or cb] if (ca or cb) else mp.default_conductors(a, pa, b, pb)
        w = Wire(WireEnd(ea, pa), WireEnd(eb, pb), conductors=conds)
        w.attrs = {at.key: at.default for at in WIRE_ATTRIBUTES}
        self.undo.push(commands.MultipoleAddCommand(self, wire=w))

    def mouseMoveEvent(self, ev):
        p = ev.scenePos()
        if self.mode == Mode.PLACE and self._ghost is not None:
            self._ghost.setPos(QPointF(snap(p.x()), snap(p.y())))
        elif self.mode == Mode.WIRE and self._wire_from is not None and self._preview is not None:
            x0, y0 = self._wire_from[3]
            path = QPainterPath(sp(x0, y0))
            path.lineTo(QPointF(sp(x0, y0).x(), snap(p.y())))
            path.lineTo(QPointF(snap(p.x()), snap(p.y())))
            self._preview.setPath(path)
        super().mouseMoveEvent(ev)

    def __init__(self, project: Project, sheet: Sheet, library: LibraryStore, undo: QUndoStack):
        super().__init__()
        self.project, self.sheet, self.library, self.undo = project, sheet, library, undo
        self.draw_grid = True
        self.mode = Mode.SELECT
        self._ghost = self._preview = None
        self._wire_from = None
        self._place_sid = None
        self._place_rot = 0
        self._poles: dict[str, mp.ElementPoles] = {}
        self.paper_size = (sheet.width, sheet.height)
        self._paper = QGraphicsRectItem(QRectF(0, -sheet.height, sheet.width, sheet.height))
        self._paper.setZValue(-1)
        self.addItem(self._paper)
        self._items: list[QGraphicsItem] = []
        self._pole_items: dict[str, list[PoleItem]] = {}   # prvek → jeho póly ve scéně
        self._tags: list[CableTagItem] = []
        self._move_start: dict[str, tuple[float, float]] = {}
        self.layout_pos: dict[str, tuple[float, float]] = {}
        self.pages: list[QRectF] = []          # strany (scénové obdélníky, shora dolů)
        self.page_of: dict[str, int] = {}      # prvek → index strany
        self.selectionChanged.connect(self._on_selection)
        self.rebuild()

    PAGE_GAP = mp.MP_PAGE_GAP   # mezera mezi stranami pod sebou (mm)
    X0 = mp.MP_X0               # začátek rozmístění – vlevo názvy potenciálů sběrnice
    Y_TOP = mp.MP_Y_TOP         # odstup první řady od horního okraje listu (nahoře nadpis rozvaděče)

    @property
    def page_pitch(self) -> float:
        return self.sheet.height + self.PAGE_GAP

    def page_index_at(self, y: float) -> int:
        """Strana podle modelové souřadnice y (strana 0 = y ∈ [0, H], další pod ní)."""
        return max(0, int((self.sheet.height - y) // self.page_pitch))

    def page_ref(self, k: int, x: float, y: float) -> str:
        """Odkaz „/list.strana.sloupecřádek“ na místo na straně k (scénové souřadnice)."""
        from envocad.model.frame import grid_coord, sheet_number
        n = sheet_number(self.project, self.sheet).split("/")[0]
        y_local = y + k * self.page_pitch
        return f"/{n}.{k + 1}.{grid_coord(self.sheet, x, y_local)}"

    @property
    def page_w(self) -> float:
        """Použitelná šířka strany pro rozmístění (bez okrajů rámečku)."""
        return mp.page_width(self.sheet)

    def _paginate(self, poles: dict[str, mp.ElementPoles]) -> None:
        """Rozmístění (strany za sebou v x) → strany pod sebou: prvek na straně k se posune o k·šířka doleva
        a o k·(výška + mezera) dolů. Ruční pozice (`mp_pos`) jsou už scénové – strana se jim jen určí."""
        from envocad.model.frame import MARGIN_LEFT
        pitch = self.page_pitch
        self.page_of, n_pages = mp.paginate(self.sheet, poles)
        w, h = self.sheet.width, self.sheet.height
        # strana k: model y ∈ [−k·pitch, h − k·pitch] → scéna y ∈ [k·pitch − h, k·pitch]
        self.pages = [QRectF(0, k * pitch - h, w, h) for k in range(n_pages)]
        self.paper_size = (w, h)
        total_h = n_pages * pitch - self.PAGE_GAP
        self._paper.setRect(QRectF(0, -h, w, total_h))
        self.setSceneRect(QRectF(-50 - MARGIN_LEFT, -h - 50, w + 100, total_h + 100))

    # ---- stavba z modelu ----------------------------------------------------
    def rebuild(self) -> None:
        for it in self._items:
            self.removeItem(it)
        self._items.clear()
        self._pole_items.clear()
        self._tags.clear()
        self._paper.setPen(QPen(colors().paper, 0.5))
        poles: dict[str, mp.ElementPoles] = {}
        self._poles = poles
        for e in self.sheet.elements:
            sym = element_symbol(self.project, e, self.library)
            poles[e.id] = mp.element_poles(self.sheet, e, sym)
        self._breaks: dict[tuple[int, bool], int] = {}
        self._break_ys: dict[tuple[int, bool], set[float]] = {}
        # popisky žil rozmístěné modelem (stejné rozmístění a trasy jako tato scéna, viz model/multipole_geometry)
        from envocad.model.multipole_geometry import multipole_geometry
        origins: dict[str, tuple[float, float]] = {}
        try:
            geo = multipole_geometry(self.project, self.sheet, self.library)
            self._labels, origins = geo.conductor_labels, geo.origins
        except Exception:
            log.exception("vícepól: rozmístění popisků žil selhalo")
            self._labels = {}
        bus_taps: dict[tuple[str, int], list[tuple[float, float]]] = {}
        self.layout_pos = mp.auto_layout(self.sheet, poles, x0=self.X0, y_top=self.sheet.height - self.Y_TOP,
                                         bridges=self.sheet.bridges, page_w=self.page_w)
        for eid, ep in poles.items():
            ep.origin = self.layout_pos.get(eid, (ep.element.x, ep.element.y))
        self._paginate(poles)
        for eid, o in origins.items():     # polohy z modelu (posun mimo popisové pole s QR kódem)
            if eid in poles:
                poles[eid].origin = o
        for e in self.sheet.elements:
            ep = poles[e.id]
            if e.symbol_id == BUS:
                continue   # sběrnice se kreslí jako čáry potenciálů až podle odboček (níže)
            if ep.per_pole:
                for i, c in enumerate(ep.switched):
                    self._add(PoleItem(ep, c, first=(i == 0)))
                if ep.symbol.pole_link and len(ep.switched) > 1:
                    self._add(PoleLinkItem(ep))
                for c in ep.bypass:
                    self._add(BypassItem(ep, c))
                for a, b in mp.pe_join_segments(ep):   # SPD: spodní konce pólů spojené s PE
                    self._add(PeJoinItem(a, b))
            else:
                self._add(PoleItem(ep, None, first=True))
                self._add_fan(ep)
        for w in self.sheet.wires:
            ea, eb = poles.get(w.a.element_id), poles.get(w.b.element_id)
            if not ea or not eb:
                continue
            da = rotate_dir(ea.symbol.port(w.a.port).dir, ea.element.rotation)
            db = rotate_dir(eb.symbol.port(w.b.port).dir, eb.element.rotation)
            ka, kb = self.page_of.get(w.a.element_id, 0), self.page_of.get(w.b.element_id, 0)
            if ea.element.symbol_id == BUS or eb.element.symbol_id == BUS:
                self._add_bus_taps(w, ea, da, ka, eb, db, kb, bus_taps)
                continue
            for i, c in enumerate(mp.wire_conductors(w)):
                pa, pb = ea.pole_pos(w.a.port, c), eb.pole_pos(w.b.port, c)
                # svorka na konci: ruční přiřazení; u svorkového prvku je číslo přímo na pólu
                ta = "" if mp.is_terminal_block(ea.element) else mp.terminal_text(w, c, "a")
                tb = "" if mp.is_terminal_block(eb.element) else mp.terminal_text(w, c, "b")
                if ka == kb:
                    it = ConductorItem(w, c, i, sp(*pa), da, sp(*pb), db, (ta, tb))
                    it.staggered = len(mp.wire_conductors(w)) > 1
                    it.label = self._labels.get((w.id, c, 0))
                    self._add(it)
                else:
                    self._add_page_break(w, c, i, pa, da, ka, pb, db, kb, (ta, tb))
        self._add_bridges(poles)
        self._add_buses(poles, bus_taps)
        self._add_cable_tags(poles)
        self._add_title()

    def _add_title(self) -> None:
        from envocad.model.frame import MARGIN, MARGIN_LEFT
        from envocad.model.project import switchboard_title
        lines = switchboard_title(self.project, self.sheet)
        if not lines:
            return
        n = max(1, len(self.pages))
        for k in range(n):
            ls = list(lines)
            if n > 1:
                ls[0] = f"{ls[0]}  ({k + 1}/{n})"
            self._add(TitleItem(MARGIN_LEFT + 5.0, self.sheet.height - MARGIN - 4.0 - k * self.page_pitch, ls))

    def _add_cable_tags(self, poles) -> None:
        """Štítky kabelů u přívodů a vývodů: označení kabelu (W2), název (od G1 / k HOP), typ (2× H1Z2Z2-K 1x6 mm²)."""
        from envocad.model.project import linked_wire
        for e in self.sheet.elements:
            if e.symbol_id not in ("sb.feed_in", "sb.feed_out"):
                continue
            ep = poles.get(e.id)
            if ep is None or not ep.switched:
                continue
            xs = [ep.origin[0] + ep.pole_offset(c)[0] for c in ep.switched]
            hit = linked_wire(self.project, self.sheet, e)
            w = hit[1] if hit else None
            ref = (w.attrs.get("ref") if w else "") or e.ref
            name = e.attrs.get("desc", "")
            cable = ""
            if w is not None:
                cable = wire_label({k: v for k, v in w.attrs.items() if k != "ref"}, w.conductors)
            elif e.attrs.get("cable"):
                cable = e.attrs["cable"]
            up = e.symbol_id == "sb.feed_in"
            y_edge = ep.origin[1] + (3.0 if up else -3.0)
            self._add(CableTagItem(min(xs), max(xs), y_edge, [ref, name, cable], up, e.id))

    def _bus_y(self, ep: mp.ElementPoles, c: str, page: int) -> float:
        """Výška čáry potenciálu `c` sběrnice na dané straně (žíly pod sebou po BUS_PITCH)."""
        k0 = self.page_of.get(ep.element.id, 0)
        base = ep.origin[1] + k0 * self.page_pitch   # výška v „nestránkovaných“ souřadnicích
        return base - ep.slot(c) * BUS_PITCH - page * self.page_pitch

    def _add_bus_taps(self, w, ea, da, ka, eb, db, kb, bus_taps) -> None:
        """Vodič mezi přístrojem a sběrnicí: každá žíla svisle od pólu přístroje k čáře potenciálu na téže straně."""
        if ea.element.symbol_id == BUS and eb.element.symbol_id == BUS:
            return
        dev, ddir, kd, bus, dport = (eb, db, kb, ea, w.b.port) if ea.element.symbol_id == BUS else (ea, da, ka, eb, w.a.port)
        side = "b" if dev is eb else "a"
        for c in mp.wire_conductors(w):
            if c not in bus.slots:
                continue
            px, py = dev.pole_pos(dport, c)
            y = self._bus_y(bus, c, kd)
            tap = (px, y)
            t = "" if mp.is_terminal_block(dev.element) else mp.terminal_text(w, c, side)
            it = ConductorItem(w, c, 0, sp(px, py), ddir, sp(*tap), "S" if y > py else "N", (t, ""))
            it.label = self._labels.get((w.id, c, 0))
            self._add(it)
            bus_taps.setdefault((bus.element.id, kd), []).append(tap)

    def _add_buses(self, poles, bus_taps) -> None:
        """Čáry potenciálů sběrnice na každé straně, kde má odbočky (a na své vlastní)."""
        from envocad.model.frame import MARGIN, MARGIN_LEFT
        x0, x1 = MARGIN_LEFT + 12.0, self.sheet.width - MARGIN - 14.0
        for e in self.sheet.elements:
            if e.symbol_id != BUS:
                continue
            ep = poles[e.id]
            conds = list(ep.slots) or mp.parse_conductors(e.attrs.get("conductors", "")) or ["L1"]
            pages = sorted({self.page_of.get(e.id, 0)} | {k for (bid, k) in bus_taps if bid == e.id})
            for k in pages:
                ys = {c: (self._bus_y(ep, c, k) if c in ep.slots else ep.origin[1] - i * BUS_PITCH) for i, c in enumerate(conds)}
                self._add(BusItem(e, conds, x0, x1, ys, bus_taps.get((e.id, k), []), k == pages[0], e.ref))

    def _add_page_break(self, w, c, i, pa, da, ka, pb, db, kb, texts) -> None:
        """Žíla přes hranici stran: na každé straně úsek k okraji s přerušovacím bodem a odkazem na protějšek."""
        from envocad.model.frame import MARGIN, MARGIN_LEFT
        right = ka < kb   # pokračování je na pozdější straně → odchod pravým okrajem, příchod levým
        xa = (self.sheet.width - MARGIN - 6.0) if right else (MARGIN_LEFT + 6.0)
        xb = (MARGIN_LEFT + 6.0) if right else (self.sheet.width - MARGIN - 6.0)
        # každé přerušení na daném okraji strany v jiné výšce (řady po 2,5 mm), aby se šipky a odkazy nekryly
        na = self._breaks.setdefault((ka, right), 0)
        nb = self._breaks.setdefault((kb, not right), 0)
        self._breaks[(ka, right)] = na + 1
        self._breaks[(kb, not right)] = nb + 1
        ya = mp.break_y(pa, da, na, self._break_ys.setdefault((ka, right), set()))
        yb = mp.break_y(pb, db, nb, self._break_ys.setdefault((kb, not right), set()))
        ea_pt = (xa, ya)
        eb_pt = (xb, yb)
        for part, (a_, da_, b_, db_, ends_) in enumerate(((pa, da, ea_pt, "W" if right else "E", (texts[0], "")),
                                                           (eb_pt, "E" if right else "W", pb, db, ("", texts[1])))):
            it = ConductorItem(w, c, i, sp(*a_), da_, sp(*b_), db_, ends_)
            it.label = self._labels.get((w.id, c, part))
            self._add(it)
        self._add(PageBreakItem(xa, ya, right, self.page_ref(kb, xb, yb)))
        self._add(PageBreakItem(xb, yb, not right, self.page_ref(ka, xa, ya)))

    def _add_bridges(self, poles: dict[str, mp.ElementPoles]) -> None:
        """Můstky svorkovnic: spojí středy svorek (posunuté k portu 1) se stejným označením X:n na tomto listu."""
        pos: dict[tuple[str, str], tuple[float, float, float, float]] = {}  # (střed x, y, směr k portu 1)
        for ep in poles.values():
            e = ep.element
            if not mp.is_terminal_block(e) or not ep.per_pole:
                continue
            nums = mp.terminal_numbers(e, len(ep.slots))
            px, py = e.port_pos(ep.symbol, ep.through[0] if ep.through else ep.symbol.ports[0].name)
            dx, dy = px - e.x, py - e.y
            n = (dx * dx + dy * dy) ** 0.5 or 1.0
            for c, num in zip(ep.slots, nums):
                if num:
                    ox, oy = ep.pole_offset(c)
                    pos[(e.ref, num)] = (ep.origin[0] + ox, ep.origin[1] + oy, dx / n, dy / n, self.page_of.get(e.id, 0))
        for strip, groups in self.sheet.bridges.items():
            for gi, g in enumerate(groups):
                hits = [pos[(strip, n)] for n in g if (strip, n) in pos]
                if len(hits) < 2:
                    continue
                # každá skupina můstků v jiné výšce (od 2 mm po 0,6 mm směrem k portu 1), aby se nepřekrývaly;
                # přes hranici stran se můstek kreslí po stranách zvlášť
                off = 2.0 + 0.6 * (gi % 6)
                for k in sorted({h[4] for h in hits}):
                    part = [h for h in hits if h[4] == k]
                    if len(part) < 2:
                        continue
                    pts = sorted((x + ux * off, y + uy * off) for x, y, ux, uy, _ in part)
                    self._add(BridgeItem(strip, g, pts))

    def _add_fan(self, ep: mp.ElementPoles) -> None:
        """Neprůchozí prvek: od portu vede kolmá sběrná čárka přes všechny sloty."""
        for port, conds in ep.per_port.items():
            if len(conds) < 2:
                continue
            last = max(conds, key=ep.slot)
            path = QPainterPath(sp(*ep.pole_pos(port, ep.slots[0])))
            path.lineTo(sp(*ep.pole_pos(port, last)))
            it = QGraphicsPathItem(path)
            it.setZValue(6)
            it.setPen(QPen(colors().wire, LINE_WIDTH * 2.5, Qt.SolidLine, Qt.RoundCap))
            self._add(it)

    def _add(self, it: QGraphicsItem) -> None:
        self.addItem(it)
        self._items.append(it)
        if isinstance(it, PoleItem):
            self._pole_items.setdefault(it.element.id, []).append(it)
        elif isinstance(it, CableTagItem) and it.element_id:
            self._tags.append(it)

    def retheme(self) -> None:
        self.rebuild()

    # ---- interakce ------------------------------------------------------------
    def _on_selection(self) -> None:
        sel = self.selectedItems()
        eids = {it.element.id for it in sel if isinstance(it, PoleItem)}
        for tag in self._tags:
            on = tag.element_id in eids
            if tag.highlight != on:
                tag.highlight = on
                tag.update()
        # všechny vybrané položky jsou póly jednoho prvku (např. přívod vybraný přes štítek) → vlastnosti prvku
        one = len(eids) == 1 and all(isinstance(it, PoleItem) for it in sel)
        self.selection_info.emit(sel[0] if len(sel) == 1 or one else None)

    def mouseDoubleClickEvent(self, ev):
        for it in self.items(ev.scenePos()):
            if isinstance(it, CableTagItem) and it.element_id:
                eid = it.element_id
                QTimer.singleShot(0, lambda eid=eid: self.edit_element_requested.emit(eid))
                return
            if isinstance(it, PoleItem):
                eid = it.element.id
                QTimer.singleShot(0, lambda eid=eid: self.edit_element_requested.emit(eid))
                return
            if isinstance(it, ConductorItem):
                wid = it.wire.id
                QTimer.singleShot(0, lambda wid=wid: self.edit_terminals(wid))
                return
        super().mouseDoubleClickEvent(ev)

    def edit_terminals(self, wid: str) -> None:
        from envocad.ui.dialogs import TerminalsDialog
        w = next((w for w in self.sheet.wires if w.id == wid), None)
        if w is None:
            return
        log.info("dialog: svorky vodiče %s", w.attrs.get("ref", ""))
        dlg = TerminalsDialog(self.sheet, w, self.views()[0] if self.views() else None)
        if dlg.exec() != TerminalsDialog.Accepted:
            return
        new = dlg.values()
        if new != w.terminals:
            self.undo.push(commands.SetTerminalsCommand(self, wid, w.terminals, new))

    def mousePressEvent(self, ev):
        if ev.button() == Qt.RightButton and self.mode in (Mode.PLACE, Mode.WIRE):
            self.set_mode(Mode.SELECT)
            return
        if ev.button() == Qt.LeftButton and self.mode == Mode.PLACE and self._place_sid:
            self._place_at(ev.scenePos())
            return
        if ev.button() == Qt.LeftButton and self.mode == Mode.WIRE:
            self._wire_click(ev.scenePos())
            return
        if ev.button() == Qt.LeftButton:
            # štítek kabelu u přívodu/vývodu: chytit = vybrat celý přívod (všechny svorky) a táhnout ho;
            # štítek je jen posuvný (ne vybíratelný), Qt ho při tažení posune spolu s vybranými póly
            top = self.itemAt(ev.scenePos(), QTransform())
            if isinstance(top, CableTagItem) and top.element_id:
                poles = self._pole_items.get(top.element_id, [])
                if ev.modifiers() & Qt.ControlModifier:
                    on = not all(it.isSelected() for it in poles)   # Ctrl = přepnout přívod ve výběru
                else:
                    on = True
                    if not (ev.modifiers() & Qt.ShiftModifier) and not all(it.isSelected() for it in poles):
                        self.clearSelection()
                for it in poles:
                    it.setSelected(on)
        super().mousePressEvent(ev)
        self._move_start = {it.element.id: it.element_origin() for it in self.selectedItems() if isinstance(it, PoleItem)}

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        if not self._move_start:
            self._reset_tags()
            return
        moves: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {}
        for it in self.selectedItems():
            if isinstance(it, PoleItem) and it.element.id in self._move_start:
                old = self._move_start[it.element.id]
                new = it.element_origin()
                if new != old and it.element.id not in moves:
                    moves[it.element.id] = (old, new)
        self._move_start = {}
        if not moves:
            self._reset_tags()
        if moves:
            # pozice se zapíše do modelu přes undo; scéna se přestaví (až po doběhnutí události myši)
            QTimer.singleShot(0, lambda: self.undo.push(commands.MoveMultipoleCommand(self, moves)))

    def _reset_tags(self) -> None:
        """Štítky posunuté myší bez změny modelu (tažení pod krok mřížky, štítek bez vybraných pólů) zpět na místo."""
        for tag in self._tags:
            if not tag.pos().isNull():
                tag.setPos(0, 0)

    def reset_layout(self) -> None:
        """Zruší ruční pozice na listu – vše se rozmístí automaticky."""
        moves = {e.id: (tuple(e.mp_pos), None) for e in self.sheet.elements if e.mp_pos}
        if moves:
            self.undo.push(commands.MoveMultipoleCommand(self, moves))

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape and self.mode in (Mode.PLACE, Mode.WIRE):
            self.set_mode(Mode.SELECT)
        elif ev.key() == Qt.Key_W and self.mode != Mode.WIRE:
            self.start_wire()
        elif ev.key() == Qt.Key_R:
            self.rotate_selected()
        elif ev.key() == Qt.Key_Escape:
            self.clearSelection()
        elif ev.key() == Qt.Key_Delete:
            eids = sorted({it.element.id for it in self.selectedItems() if isinstance(it, PoleItem)})
            wids = sorted({it.wire.id for it in self.selectedItems() if isinstance(it, ConductorItem)})
            if eids or wids:
                self.delete_requested.emit(eids, wids)
        else:
            super().keyPressEvent(ev)

    # ---- pozadí ---------------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        c = PRINT if not self.draw_grid else colors()
        painter.fillRect(rect, c.background)
        if not self.draw_grid:
            return
        scale = painter.worldTransform().m11()
        step = GRID if scale > 2.5 else GRID * 4
        painter.setPen(QPen(c.grid, 0))
        x = int(rect.left() / step) * step
        while x < rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += step
        y = int(rect.top() / step) * step
        while y < rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += step

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        from envocad.model.frame import frame_geometry
        c = PRINT if not self.draw_grid else colors()
        w, h = self.paper_size
        n = max(1, len(self.pages))
        for k in range(n):
            painter.save()
            painter.translate(0, k * self.page_pitch)
            page = f"{k + 1}/{n}" if n > 1 else ""
            draw_frame(painter, frame_geometry(self.project, self.sheet, w, h, "vícepólové schéma", page), c.ink)
            painter.restore()
            if k:  # dělicí čára mezi stranami i bez rámečku
                painter.setPen(QPen(c.grid, 0, Qt.DashLine))
                y = k * self.page_pitch - h - self.PAGE_GAP / 2   # scénové y uprostřed mezery nad stranou k
                painter.drawLine(QPointF(0, y), QPointF(w, y))


class MultipoleView(SchematicView):
    """Stejné ovládání (zoom, posun) jako JPS; obsah je jen pro čtení a výběr."""

    def zoom_fit(self) -> None:
        sc = self.scene()
        w, h = sc.paper_size
        pages = getattr(sc, "pages", None)
        if pages:
            r = QRectF(pages[0])
            for p in pages[1:]:
                r = r.united(p)
            self.fitInView(r, Qt.KeepAspectRatio)
        else:
            self.fitInView(QRectF(0, -h, w, h), Qt.KeepAspectRatio)
