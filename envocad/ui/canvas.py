"""Scéna a pohled editoru: mřížka, snap, režimy (výběr / vkládání / vodič), zoom a posun."""
from __future__ import annotations

import logging
from enum import Enum

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QPen, QUndoStack, QWheelEvent
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from envocad.library.store import LibraryStore
from envocad.model.project import WIRE_ATTRIBUTES, Element, Project, Sheet, Wire, WireEnd
from envocad.model.symbol import GRID
from envocad.ui import commands
from envocad.ui.items import ElementItem, WireItem, route, snap
from envocad.ui.render import sp
from envocad.ui.theme import PRINT, colors

log = logging.getLogger("envocad.ui")


class Mode(Enum):
    SELECT = 0
    PLACE = 1
    WIRE = 2


class SchematicScene(QGraphicsScene):
    selection_info = Signal(object)       # ElementItem | WireItem | None
    attrs_changed = Signal(str)           # id elementu/vodiče
    mode_changed = Signal(object)         # Mode
    open_switchboard = Signal(str)        # id bloku ROZVADĚČ

    def __init__(self, project: Project, sheet: Sheet, library: LibraryStore, undo: QUndoStack):
        super().__init__()
        self.project, self.sheet, self.library, self.undo = project, sheet, library, undo
        self.element_items: dict[str, ElementItem] = {}
        self.wire_items: dict[str, WireItem] = {}
        self.mode = Mode.SELECT
        self.draw_grid = True
        self.ask_attributes = True  # dialog s parametry při vložení prvku (testy vypínají)
        self._ghost: ElementItem | None = None
        self._place_symbol_id: str | None = None
        self._wire_from: tuple[ElementItem, str] | None = None
        self._wire_preview = QGraphicsPathItem()
        self._wire_preview.setPen(QPen(colors().preview, 0.3, Qt.DashLine))
        self._wire_preview.setZValue(20)
        self._move_start: dict[str, tuple[float, float]] = {}
        self.setSceneRect(QRectF(-50, -sheet.height - 50, sheet.width + 100, sheet.height + 100))
        self._paper = QGraphicsRectItem(QRectF(0, -sheet.height, sheet.width, sheet.height))
        self._paper.setPen(QPen(colors().paper, 0.5))
        self._paper.setZValue(-1)
        self.addItem(self._paper)
        self.selectionChanged.connect(self._on_selection)
        self.rebuild()

    # ---- synchronizace s modelem ------------------------------------------
    def rebuild(self) -> None:
        for it in list(self.element_items.values()) + list(self.wire_items.values()):
            self.removeItem(it)
        self.element_items.clear()
        self.wire_items.clear()
        for e in self.sheet.elements:
            self.add_element_item(e)
        for w in self.sheet.wires:
            self.add_wire_item(w)

    def add_element_item(self, e: Element) -> ElementItem:
        it = ElementItem(e, self.library.get_symbol(e.symbol_id))
        self.addItem(it)
        self.element_items[e.id] = it
        return it

    def remove_element_item(self, eid: str) -> None:
        it = self.element_items.pop(eid, None)
        if it:
            self.removeItem(it)

    def add_wire_item(self, w: Wire) -> WireItem:
        it = WireItem(w)
        self.addItem(it)
        self.wire_items[w.id] = it
        self._route(it)
        return it

    def remove_wire_item(self, wid: str) -> None:
        it = self.wire_items.pop(wid, None)
        if it:
            self.removeItem(it)

    def _route(self, it: WireItem) -> None:
        a = self.element_items.get(it.wire.a.element_id)
        b = self.element_items.get(it.wire.b.element_id)
        if a and b:
            it.update_route(a, b)

    def update_wires_of(self, eid: str) -> None:
        for it in self.wire_items.values():
            if it.wire.touches(eid):
                self._route(it)

    def element_moved(self, it: ElementItem) -> None:
        it.element.x, it.element.y = it.pos().x(), -it.pos().y()
        self.update_wires_of(it.element.id)

    # ---- režimy -------------------------------------------------------------
    def set_mode(self, mode: Mode) -> None:
        if self._ghost:
            self.removeItem(self._ghost)
            self._ghost = None
        if self._wire_preview.scene():
            self.removeItem(self._wire_preview)
        self._wire_from = None
        self._place_symbol_id = None
        self.mode = mode
        log.info("režim: %s", mode.name)
        self.mode_changed.emit(mode)

    def start_place(self, symbol_id: str) -> None:
        self.set_mode(Mode.PLACE)
        self._place_symbol_id = symbol_id
        sym = self.library.get_symbol(symbol_id)
        self._ghost = ElementItem(Element(symbol_id=symbol_id), sym)
        self._ghost.setOpacity(0.5)
        for fl in (ElementItem.ItemIsSelectable, ElementItem.ItemIsMovable, ElementItem.ItemSendsGeometryChanges):
            self._ghost.setFlag(fl, False)
        self.addItem(self._ghost)

    def start_wire(self) -> None:
        self.set_mode(Mode.WIRE)

    def _element_at(self, pos: QPointF) -> ElementItem | None:
        for it in self.items(pos):
            if isinstance(it, ElementItem) and it is not self._ghost:
                return it
        return None

    def _port_near(self, pos: QPointF) -> tuple[ElementItem, str] | None:
        best = None
        for it in self.element_items.values():
            name = it.port_at(pos, tol=GRID)
            if name:
                d = (it.port_scene_pos(name) - pos).manhattanLength()
                if best is None or d < best[0]:
                    best = (d, it, name)
        return (best[1], best[2]) if best else None

    # ---- události myši -----------------------------------------------------
    def mouseMoveEvent(self, ev):
        p = ev.scenePos()
        if self.mode == Mode.PLACE and self._ghost:
            self._ghost.setPos(snap(p.x()), snap(p.y()))
            return
        if self.mode == Mode.WIRE and self._wire_from:
            a, port = self._wire_from
            hit = self._port_near(p)
            if hit:
                end, d = hit[0].port_scene_pos(hit[1]), hit[0].port_dir(hit[1])
            else:
                end, d = QPointF(snap(p.x()), snap(p.y())), "W"
            self._wire_preview.setPath(route(a.port_scene_pos(port), a.port_dir(port), end, d, []))
            return
        super().mouseMoveEvent(ev)

    def mousePressEvent(self, ev):
        p = ev.scenePos()
        if ev.button() == Qt.RightButton and self.mode != Mode.SELECT:
            self.set_mode(Mode.SELECT)
            return
        if self.mode == Mode.PLACE and ev.button() == Qt.LeftButton and self._place_symbol_id:
            sym = self.library.get_symbol(self._place_symbol_id)
            e = Element(symbol_id=sym.id, x=snap(p.x()), y=-snap(p.y()), rotation=self._ghost.element.rotation)
            e.attrs = {a.key: a.default for a in sym.attributes}
            e.attrs["ref"] = self.project.next_ref(sym.iec_ref)
            if self.ask_attributes:
                # modální dialog až po doběhnutí události myši (uvnitř obsluhy stisku padá Qt na Windows)
                QTimer.singleShot(0, lambda: self._finish_place(sym, e))
            else:
                self.undo.push(commands.AddElementCommand(self, e))
            return  # zůstáváme v režimu vkládání (Esc / pravé tlačítko ukončí)
        if self.mode == Mode.WIRE and ev.button() == Qt.LeftButton:
            hit = self._port_near(p)
            if not hit:
                return
            if self._wire_from is None:
                self._wire_from = hit
                self._wire_preview.setPath(route(hit[0].port_scene_pos(hit[1]), hit[0].port_dir(hit[1]), p, "W", []))
                self.addItem(self._wire_preview)
            else:
                a, pa = self._wire_from
                b, pb = hit
                self._wire_from = None
                self.removeItem(self._wire_preview)
                if not (a is b and pa == pb):
                    w = Wire(WireEnd(a.element.id, pa), WireEnd(b.element.id, pb))
                    w.attrs = {at.key: at.default for at in WIRE_ATTRIBUTES}
                    w.attrs["ref"] = self.project.next_ref("W")
                    if self.ask_attributes:
                        heading = f"<b>Vodič</b> {a.element.ref}:{pa} → {b.element.ref}:{pb}"
                        QTimer.singleShot(0, lambda: self._finish_wire(w, heading))
                    else:
                        self.undo.push(commands.AddWireCommand(self, w))
            return
        # SELECT: zapamatovat výchozí pozice pro undo posunu
        super().mousePressEvent(ev)
        self._move_start = {it.element.id: (it.element.x, it.element.y)
                            for it in self.selectedItems() if isinstance(it, ElementItem)}

    def _parent_widget(self):
        return self.views()[0] if self.views() else None

    def _finish_place(self, sym, e: Element) -> None:
        from envocad.ui.dialogs import ElementDialog
        log.info("dialog: vložit %s", sym.id)
        dlg = ElementDialog(sym, e.attrs, self._parent_widget())
        if dlg.exec() != ElementDialog.Accepted:
            return
        e.attrs = dlg.values()
        self.undo.push(commands.AddElementCommand(self, e))

    def _finish_wire(self, w: Wire, heading: str) -> None:
        from envocad.ui.dialogs import AttrDialog
        log.info("dialog: vložit vodič")
        dlg = AttrDialog(WIRE_ATTRIBUTES, w.attrs, self._parent_widget(), "Vložit vodič", heading)
        if dlg.exec() != AttrDialog.Accepted:
            return
        w.attrs = dlg.values()
        self.undo.push(commands.AddWireCommand(self, w))

    def mouseDoubleClickEvent(self, ev):
        if self.mode != Mode.SELECT:
            return super().mouseDoubleClickEvent(ev)
        it = self._element_at(ev.scenePos())
        if it is not None:
            if it.symbol.id == "fve.switchboard":
                self.open_switchboard.emit(it.element.id)
                return None
            eid = it.element.id
            QTimer.singleShot(0, lambda: self.edit_element(eid))
            return None
        for w in self.items(ev.scenePos()):
            if isinstance(w, WireItem):
                wid = w.wire.id
                QTimer.singleShot(0, lambda: self.edit_wire(wid))
                return None
        super().mouseDoubleClickEvent(ev)

    def edit_wire(self, wid: str) -> None:
        from envocad.ui.dialogs import AttrDialog
        w = next(w for w in self.sheet.wires if w.id == wid)
        dlg = AttrDialog(WIRE_ATTRIBUTES, w.attrs, self._parent_widget(), f"Upravit vodič {w.attrs.get('ref', '')}")
        if dlg.exec() != AttrDialog.Accepted:
            return
        self._apply_attr_changes(wid, True, w.attrs, dlg.values(), f"Upravit {w.attrs.get('ref') or 'vodič'}")

    def _apply_attr_changes(self, tid: str, is_wire: bool, old: dict, new: dict, label: str) -> None:
        changed = [(k, v) for k, v in new.items() if old.get(k, "") != v]
        if not changed:
            return
        self.undo.beginMacro(label)
        for k, v in changed:
            self.set_attr(tid, is_wire, k, v)
        self.undo.endMacro()

    def edit_element(self, eid: str) -> None:
        """Dialog s atributy existujícího prvku; změny jdou přes undo příkazy."""
        from envocad.ui.dialogs import ElementDialog
        e = self.sheet.element(eid)
        sym = self.library.get_symbol(e.symbol_id)
        dlg = ElementDialog(sym, e.attrs, self._parent_widget(), title=f"Upravit: {e.ref or sym.name}")
        if dlg.exec() != ElementDialog.Accepted:
            return
        self._apply_attr_changes(eid, False, e.attrs, dlg.values(), f"Upravit {e.ref or sym.name}")

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        if self.mode == Mode.SELECT and self._move_start:
            moves = {}
            for eid, old in self._move_start.items():
                it = self.element_items.get(eid)
                if it and (it.element.x, it.element.y) != old:
                    moves[eid] = (old, (it.element.x, it.element.y))
            if moves:
                self.undo.push(commands.MoveElementsCommand(self, moves))
            self._move_start = {}

    def keyPressEvent(self, ev: QKeyEvent):
        if ev.key() == Qt.Key_Escape:
            self.set_mode(Mode.SELECT)
            self.clearSelection()
        elif ev.key() == Qt.Key_Delete:
            self.delete_selected()
        elif ev.key() == Qt.Key_R:
            self.rotate_selected()
        elif ev.key() == Qt.Key_W:
            self.start_wire()
        else:
            super().keyPressEvent(ev)

    # ---- akce ---------------------------------------------------------------
    def delete_selected(self) -> None:
        eids = [it.element.id for it in self.selectedItems() if isinstance(it, ElementItem)]
        wids = [it.wire.id for it in self.selectedItems() if isinstance(it, WireItem)]
        if eids or wids:
            self.undo.push(commands.RemoveItemsCommand(self, eids, wids))

    def rotate_selected(self) -> None:
        if self.mode == Mode.PLACE and self._ghost:
            self._ghost.element.rotation = (self._ghost.element.rotation + 90) % 360
            self._ghost.sync_from_model()
            return
        for it in self.selectedItems():
            if isinstance(it, ElementItem):
                self.undo.push(commands.RotateElementCommand(self, it.element.id))

    def set_attr(self, target_id: str, is_wire: bool, key: str, value: str) -> None:
        if is_wire:
            old = next(w for w in self.sheet.wires if w.id == target_id).attrs.get(key, "")
        else:
            old = self.sheet.element(target_id).attrs.get(key, "")
        if old != value:
            self.undo.push(commands.SetAttrCommand(self, target_id, is_wire, key, old, value))

    def _on_selection(self) -> None:
        sel = self.selectedItems()
        self.selection_info.emit(sel[0] if len(sel) == 1 else None)

    # ---- pozadí -------------------------------------------------------------
    def retheme(self) -> None:
        """Po přepnutí tématu obnoví barvy položek."""
        self._paper.setPen(QPen(colors().paper, 0.5))
        self._wire_preview.setPen(QPen(colors().preview, 0.3, Qt.DashLine))
        for it in self.wire_items.values():
            it.setPen(QPen(colors().wire, it.pen().widthF(), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.update()

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


class SchematicView(QGraphicsView):
    def __init__(self, scene: SchematicScene):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setMouseTracking(True)
        self._panning = False
        self._pan_last = None
        self.scale(3, 3)
        self.centerOn(sp(scene.sheet.width / 2, scene.sheet.height / 2))

    def wheelEvent(self, ev: QWheelEvent):
        f = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        cur = self.transform().m11()
        if 0.3 < cur * f < 60:
            self.scale(f, f)

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MiddleButton:
            self._panning, self._pan_last = True, ev.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QMouseEvent):
        if self._panning and self._pan_last is not None:
            d = ev.position() - self._pan_last
            self._pan_last = ev.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MiddleButton:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            return
        super().mouseReleaseEvent(ev)

    def zoom_fit(self) -> None:
        self.fitInView(self.scene()._paper, Qt.KeepAspectRatio)
