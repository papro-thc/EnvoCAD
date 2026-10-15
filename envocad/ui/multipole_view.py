"""Vícepólový pohled: odvozená scéna nad stejným listem jako JPS.

Geometrie se počítá v `model/multipole.py`; tady se jen kreslí. Prvky se v tomto pohledu neposouvají
(JPS je řídící), dvojklik na prvek upraví parametry, dvojklik na žílu otevře přiřazení svorek vodiče.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPainterPathStroker, QPen, QUndoStack
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene

from envocad.library.store import LibraryStore
from envocad.model import multipole as mp
from envocad.model.geometry import wire_label_anchor
from envocad.model.project import Element, Project, Sheet, Wire, element_symbol
from envocad.model.symbol import GRID, Symbol, rotate_dir
from envocad.ui import commands
from envocad.ui.canvas import SchematicView
from envocad.ui.items import PORT_R, path_points, route, snap, wire_label
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
        return QRectF(x0, -y1, x1 - x0, y1 - y0).adjusted(-3, -8, 20, 3)

    def shape(self) -> QPainterPath:
        x0, y0, x1, y1 = self.symbol.bounds()
        p = QPainterPath()
        p.addRect(QRectF(x0, -y1, x1 - x0, y1 - y0).adjusted(-1, -1, 1, 1))
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
        if self.conductor and mp.is_terminal_block(self.element):
            # číslo svorky vedle značky (vždy vodorovně)
            num = mp.terminal_numbers(self.element, len(self.ep.slots))[self.ep.slot(self.conductor)] or "?"
            painter.save()
            x0, y0, x1, _y1 = self.symbol.bounds()
            painter.translate(sp(x1 + 1.0, y0 + 1.0))
            painter.rotate(self.element.rotation)
            painter.setPen(QPen(color, 0.2))
            draw_text(painter, 0, 0, num, 2.0, "left")
            painter.restore()
        if not self.first:
            return
        lines = [(self.element.ref, 2.5)] if self.element.ref else []
        skip = {"ref", "terminal"} if mp.is_terminal_block(self.element) else {"ref"}  # čísla svorek jsou u pólů
        lines += [(self.element.attrs[a.key], 2.0) for a in self.symbol.attributes
                  if a.show and a.key not in skip and self.element.attrs.get(a.key)]
        multi = len(self.ep.switched) > 1
        if multi:
            # vícepólový prvek: popisek nad prvním pólem, řádky skládané nahoru (pod ním jsou další póly)
            x0, _y0, _x1, y1 = self.symbol.bounds()
            lx, ly = x0, y1 + (7.5 if mp.is_terminal_block(self.element) else 1.5)  # nad můstky
            y = sum(h + 1.0 for _, h in lines[1:])
        else:
            lx, ly = self.symbol.label_pos
            y = 0.0
        painter.save()
        painter.translate(sp(lx, ly))
        painter.rotate(self.element.rotation)
        painter.setPen(QPen(color, 0.2))
        for text, h in lines:
            draw_text(painter, 0, y, text, h, "left")
            y -= h + 1.0
        painter.restore()


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


class BridgeItem(QGraphicsPathItem):
    """Můstek (propoj) mezi svorkami jedné svorkovnice – tlustá čára s tečkami na svorkách."""

    def __init__(self, strip: str, group: list[str], points: list[tuple[float, float]]):
        super().__init__()
        self.strip, self.group, self.points = strip, group, points
        path = QPainterPath(sp(*points[0]))
        for pt in points[1:]:
            path.lineTo(sp(*pt))
        self.setPath(path)
        self.setZValue(7)
        self.setToolTip(f"Můstek {strip}: {'-'.join(group)}")
        self.setPen(QPen(colors().ink, LINE_WIDTH * 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    def paint(self, painter, option, widget=None):
        painter.setPen(QPen(colors().ink, LINE_WIDTH * 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(self.path())
        painter.setBrush(colors().ink)
        for x, y in self.points:
            painter.drawEllipse(sp(x, y), 0.7, 0.7)


class ConductorItem(QGraphicsPathItem):
    """Jedna žíla vodiče mezi póly dvou prvků."""
    Type = QGraphicsItem.UserType + 12

    def __init__(self, wire: Wire, conductor: str, idx: int, pa: QPointF, da: str, pb: QPointF, db: str,
                 end_text: tuple[str, str] = ("", "")):
        super().__init__()
        self.wire, self.conductor, self.idx = wire, conductor, idx
        self.end_text = end_text
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setZValue(5)
        self.setPen(QPen(colors().wire, LINE_WIDTH * 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.setPath(route(pa, da, pb, db, [], stagger=idx * GRID))
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
        x, y, align, _vertical = wire_label_anchor(pts)
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

    def __init__(self, project: Project, sheet: Sheet, library: LibraryStore, undo: QUndoStack):
        super().__init__()
        self.project, self.sheet, self.library, self.undo = project, sheet, library, undo
        self.draw_grid = True
        self.mode = None
        self.paper_size = (sheet.width, sheet.height)
        self._paper = QGraphicsRectItem(QRectF(0, -sheet.height, sheet.width, sheet.height))
        self._paper.setZValue(-1)
        self.addItem(self._paper)
        self._items: list[QGraphicsItem] = []
        self._move_start: dict[str, tuple[float, float]] = {}
        self.layout_pos: dict[str, tuple[float, float]] = {}
        self.selectionChanged.connect(self._on_selection)
        self.rebuild()

    def _fit_paper(self, poles: dict[str, mp.ElementPoles]) -> None:
        """List vícepólu: rozměr JPS listu, podle potřeby zvětšený, aby se rozmístění vešlo (s okrajem)."""
        from envocad.model.frame import MARGIN, MARGIN_LEFT
        w, h = self.sheet.width, self.sheet.height
        for ep in poles.values():
            x, y = ep.origin
            w = max(w, x + mp.flow_extent(ep) + mp.perp_extent(ep) + MARGIN + 40)
            h = max(h, (self.sheet.height - y) + mp.perp_extent(ep) + MARGIN + 20)
        self.paper_size = (w, h)
        self._paper.setRect(QRectF(0, -h, w, h))
        self.setSceneRect(QRectF(-50 - MARGIN_LEFT, -h - 50, w + 100, h + 100))

    # ---- stavba z modelu ----------------------------------------------------
    def rebuild(self) -> None:
        for it in self._items:
            self.removeItem(it)
        self._items.clear()
        self._paper.setPen(QPen(colors().paper, 0.5))
        poles: dict[str, mp.ElementPoles] = {}
        for e in self.sheet.elements:
            sym = element_symbol(self.project, e, self.library)
            poles[e.id] = mp.element_poles(self.sheet, e, sym)
        self.layout_pos = mp.auto_layout(self.sheet, poles, y_top=self.sheet.height - 40.0, bridges=self.project.bridges)
        for eid, ep in poles.items():
            ep.origin = self.layout_pos.get(eid, (ep.element.x, ep.element.y))
        self._fit_paper(poles)
        for e in self.sheet.elements:
            ep = poles[e.id]
            if ep.through and ep.switched:
                for i, c in enumerate(ep.switched):
                    self._add(PoleItem(ep, c, first=(i == 0)))
                if ep.symbol.pole_link and len(ep.switched) > 1:
                    self._add(PoleLinkItem(ep))
                for c in ep.bypass:
                    self._add(BypassItem(ep, c))
            else:
                self._add(PoleItem(ep, None, first=True))
                self._add_fan(ep)
        for w in self.sheet.wires:
            ea, eb = poles.get(w.a.element_id), poles.get(w.b.element_id)
            if not ea or not eb:
                continue
            da = rotate_dir(ea.symbol.port(w.a.port).dir, ea.element.rotation)
            db = rotate_dir(eb.symbol.port(w.b.port).dir, eb.element.rotation)
            for i, c in enumerate(mp.wire_conductors(w)):
                pa, pb = ea.pole_pos(w.a.port, c), eb.pole_pos(w.b.port, c)
                # svorka na konci: ruční přiřazení; u svorkového prvku je číslo přímo na pólu
                ta = "" if mp.is_terminal_block(ea.element) else mp.terminal_text(w, c, "a")
                tb = "" if mp.is_terminal_block(eb.element) else mp.terminal_text(w, c, "b")
                self._add(ConductorItem(w, c, i, sp(*pa), da, sp(*pb), db, (ta, tb)))
        self._add_bridges(poles)

    def _add_bridges(self, poles: dict[str, mp.ElementPoles]) -> None:
        """Můstky svorkovnic: spojí středy svorek (posunuté k portu 1) se stejným označením X:n na tomto listu."""
        pos: dict[tuple[str, str], tuple[float, float, float, float]] = {}  # (střed x, y, směr k portu 1)
        for ep in poles.values():
            e = ep.element
            if not mp.is_terminal_block(e) or not ep.through:
                continue
            nums = mp.terminal_numbers(e, len(ep.slots))
            px, py = e.port_pos(ep.symbol, ep.through[0])
            dx, dy = px - e.x, py - e.y
            n = (dx * dx + dy * dy) ** 0.5 or 1.0
            for c, num in zip(ep.slots, nums):
                if num:
                    ox, oy = ep.pole_offset(c)
                    pos[(e.ref, num)] = (ep.origin[0] + ox, ep.origin[1] + oy, dx / n, dy / n)
        for strip, groups in self.project.bridges.items():
            for gi, g in enumerate(groups):
                hits = [pos[(strip, n)] for n in g if (strip, n) in pos]
                if len(hits) < 2:
                    continue
                # každá skupina můstků v jiné výšce (1,5 mm + 0,8 mm na skupinu směrem k portu 1), aby se nepřekrývaly
                off = 1.0 + 1.0 * (gi % 6)
                pts = sorted((x + ux * off, y + uy * off) for x, y, ux, uy in hits)
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

    def retheme(self) -> None:
        self.rebuild()

    # ---- interakce ------------------------------------------------------------
    def _on_selection(self) -> None:
        sel = self.selectedItems()
        self.selection_info.emit(sel[0] if len(sel) == 1 else None)

    def mouseDoubleClickEvent(self, ev):
        for it in self.items(ev.scenePos()):
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
        super().mousePressEvent(ev)
        self._move_start = {it.element.id: it.element_origin() for it in self.selectedItems() if isinstance(it, PoleItem)}

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        if not self._move_start:
            return
        moves: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {}
        for it in self.selectedItems():
            if isinstance(it, PoleItem) and it.element.id in self._move_start:
                old = self._move_start[it.element.id]
                new = it.element_origin()
                if new != old and it.element.id not in moves:
                    moves[it.element.id] = (old, new)
        self._move_start = {}
        if moves:
            # pozice se zapíše do modelu přes undo; scéna se přestaví (až po doběhnutí události myši)
            QTimer.singleShot(0, lambda: self.undo.push(commands.MoveMultipoleCommand(self, moves)))

    def reset_layout(self) -> None:
        """Zruší ruční pozice na listu – vše se rozmístí automaticky."""
        moves = {e.id: (tuple(e.mp_pos), None) for e in self.sheet.elements if e.mp_pos}
        if moves:
            self.undo.push(commands.MoveMultipoleCommand(self, moves))

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
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
        draw_frame(painter, frame_geometry(self.project, self.sheet, w, h, "vícepólové schéma"), c.ink)


class MultipoleView(SchematicView):
    """Stejné ovládání (zoom, posun) jako JPS; obsah je jen pro čtení a výběr."""

    def zoom_fit(self) -> None:
        w, h = self.scene().paper_size
        self.fitInView(QRectF(0, -h, w, h), Qt.KeepAspectRatio)
