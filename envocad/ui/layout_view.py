"""Pohled fyzického rozložení rozvaděče: řady DIN lišt, přístroje jako obdélníky v modulech (17,5 mm)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QUndoCommand, QUndoStack
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from envocad.library.store import LibraryStore
from envocad.model.project import MODULE_WIDTH, Element, Project, Sheet
from envocad.ui.render import draw_text
from envocad.ui.theme import colors

ROW_H = 90.0        # mm – výška řady (přístroj + prostor na vodiče)
DEV_H = 45.0        # mm – výška přístroje (modulové přístroje ~ 45 mm na liště)
MARGIN = 20.0
UNPLACED_X_GAP = 30.0
SNAP = 0.5          # modulu


class SetPlacementCommand(QUndoCommand):
    def __init__(self, scene: LayoutScene, eid: str, old: tuple | None, new: tuple | None):
        super().__init__("Umístit přístroj")
        self.scene, self.eid, self.old, self.new = scene, eid, old, new
        self._first = True

    def _apply(self, v):
        self.scene.sheet.layout.set_placement(self.eid, *(v or (None, None)))
        self.scene.sync_positions()

    def redo(self):
        self._first = False
        self._apply(self.new)

    def undo(self):
        self._apply(self.old)


class DeviceItem(QGraphicsRectItem):
    def __init__(self, element: Element, name: str, placed: bool):
        w = max(element.modules, 1.0) * MODULE_WIDTH
        super().__init__(0, 0, w, DEV_H)
        self.element, self.name, self.placed = element, name, placed
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(5)

    def paint(self, painter, option, widget=None):
        c = colors()
        painter.setRenderHint(QPainter.Antialiasing)
        fill = QColor(c.selection) if self.isSelected() else QColor(c.ink)
        fill.setAlpha(40 if self.placed else 15)
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(c.selection if self.isSelected() else c.ink, 0.4, Qt.SolidLine if self.placed else Qt.DashLine))
        painter.drawRect(self.rect())
        r = self.rect()
        painter.setPen(QPen(c.ink, 0.2))
        draw_text(painter, r.center().x(), -(r.top() + 8), self.element.ref, 3.0, "center")
        typ = self.element.attrs.get("type") or self.name
        if typ:
            draw_text(painter, r.center().x(), -(r.top() + 14), typ[:18], 2.0, "center")
        info = " ".join(x for x in (self.element.attrs.get("in_", ""), self.element.attrs.get("char", "")) if x)
        if info:
            draw_text(painter, r.center().x(), -(r.top() + 19), info, 2.0, "center")
        draw_text(painter, r.center().x(), -(r.bottom() - 2), f"{self.element.modules:g} M", 1.8, "center")


class LayoutScene(QGraphicsScene):
    selection_info = Signal(object)

    def __init__(self, project: Project, sheet: Sheet, library: LibraryStore, undo: QUndoStack):
        super().__init__()
        self.project, self.sheet, self.library, self.undo = project, sheet, library, undo
        self.items_by_id: dict[str, DeviceItem] = {}
        self._drag_start: dict[str, tuple | None] = {}
        self.selectionChanged.connect(lambda: self.selection_info.emit(
            self.selectedItems()[0] if len(self.selectedItems()) == 1 else None))
        self.rebuild()

    # ---- geometrie ----------------------------------------------------------
    @property
    def enclosure_w(self) -> float:
        return self.sheet.layout.modules_per_row * MODULE_WIDTH

    def row_rect(self, row: int) -> QRectF:
        return QRectF(MARGIN, MARGIN + row * ROW_H, self.enclosure_w, ROW_H)

    def rail_y(self, row: int) -> float:
        return MARGIN + row * ROW_H + (ROW_H - DEV_H) / 2

    def pos_to_scene(self, row: int, pos: float) -> QPointF:
        return QPointF(MARGIN + pos * MODULE_WIDTH, self.rail_y(row))

    def scene_to_placement(self, p: QPointF, width_modules: float) -> tuple[int, float] | None:
        """Bod levého horního rohu přístroje → (řada, pozice) nebo None (mimo skříň)."""
        lay = self.sheet.layout
        cy = p.y() + DEV_H / 2
        if p.x() < MARGIN - MODULE_WIDTH or p.x() > MARGIN + self.enclosure_w or cy < MARGIN or cy > MARGIN + lay.rows * ROW_H:
            return None
        row = int((cy - MARGIN) // ROW_H)
        pos = round((p.x() - MARGIN) / MODULE_WIDTH / SNAP) * SNAP
        pos = max(0.0, min(pos, lay.modules_per_row - width_modules))
        return (max(0, min(row, lay.rows - 1)), pos)

    # ---- sestavení ----------------------------------------------------------
    def sync_positions(self) -> None:
        """Přesune existující položky podle layoutu (bez mazání – bezpečné i během obsluhy myši)."""
        lay = self.sheet.layout
        unplaced_y = MARGIN
        ux = MARGIN + self.enclosure_w + UNPLACED_X_GAP
        for e in self.sheet.elements:
            it = self.items_by_id.get(e.id)
            if it is None:
                continue
            pl = lay.placement(e.id)
            it.placed = pl is not None
            if pl:
                it.setPos(self.pos_to_scene(pl.row, pl.pos))
            else:
                it.setPos(ux, unplaced_y)
                unplaced_y += DEV_H + 8
            it.update()

    def rebuild(self) -> None:
        """Úplná přestavba – volat jen mimo obsluhu událostí myši (po šabloně, změně skříně, tématu)."""
        self.clear()
        self.items_by_id.clear()
        lay = self.sheet.layout
        c = colors()
        encl = QGraphicsRectItem(MARGIN - 10, MARGIN - 10, self.enclosure_w + 20, lay.rows * ROW_H + 20)
        encl.setPen(QPen(c.paper, 0.8))
        encl.setZValue(-2)
        self.addItem(encl)
        for r in range(lay.rows):
            rail = QGraphicsRectItem(MARGIN, self.rail_y(r) + DEV_H / 2 - 17.5, self.enclosure_w, 35)
            rail.setPen(QPen(c.grid_major, 0.3))
            rail.setBrush(QBrush(QColor(c.grid)))
            rail.setZValue(-1)
            self.addItem(rail)
            for m in range(lay.modules_per_row + 1):
                x = MARGIN + m * MODULE_WIDTH
                tick = self.addLine(x, self.rail_y(r) + DEV_H, x, self.rail_y(r) + DEV_H + (3 if m % 6 else 6), QPen(c.grid_major, 0.2))
                tick.setZValue(-1)
        # přístroje
        unplaced_y = MARGIN
        ux = MARGIN + self.enclosure_w + UNPLACED_X_GAP
        for e in self.sheet.elements:
            if e.modules <= 0:
                continue
            sym = self.library.get_symbol(e.symbol_id)
            pl = lay.placement(e.id)
            it = DeviceItem(e, sym.name, pl is not None)
            if pl:
                it.setPos(self.pos_to_scene(pl.row, pl.pos))
            else:
                it.setPos(ux, unplaced_y)
                unplaced_y += DEV_H + 8
            self.addItem(it)
            self.items_by_id[e.id] = it
        label = self.addSimpleText("")
        label.setZValue(-1)
        self.setSceneRect(QRectF(0, 0, ux + 6 * MODULE_WIDTH + MARGIN, max(lay.rows * ROW_H, unplaced_y) + 2 * MARGIN))

    # ---- interakce -----------------------------------------------------------
    def mousePressEvent(self, ev):
        super().mousePressEvent(ev)
        self._drag_start = {}
        for it in self.selectedItems():
            if isinstance(it, DeviceItem):
                pl = self.sheet.layout.placement(it.element.id)
                self._drag_start[it.element.id] = (pl.row, pl.pos) if pl else None

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        moves = []
        for eid, old in self._drag_start.items():
            it = self.items_by_id.get(eid)
            if it is None:
                continue
            new = self.scene_to_placement(it.pos(), it.element.modules)
            if new != old:
                moves.append((eid, old, new))
        self._drag_start = {}
        if moves:
            self.undo.beginMacro("Umístit přístroje") if len(moves) > 1 else None
            for eid, old, new in moves:
                self.undo.push(SetPlacementCommand(self, eid, old, new))
            self.undo.endMacro() if len(moves) > 1 else None
        else:
            self.sync_positions()  # přitáhnout zpět na mřížku

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        c = colors()
        painter.fillRect(rect, c.background)
        painter.setPen(QPen(c.ink, 0.2))
        draw_text(painter, MARGIN, -(MARGIN - 13), f"{self.sheet.name}   skříň: {self.sheet.layout.enclosure or '–'}   "
                  f"{self.sheet.layout.rows} řady × {self.sheet.layout.modules_per_row} modulů", 3.5, "left")
        draw_text(painter, MARGIN + self.enclosure_w + UNPLACED_X_GAP, -(MARGIN - 6), "Nerozmístěno", 3.0, "left")

    def used_modules(self) -> dict[int, float]:
        out: dict[int, float] = {}
        for pl in self.sheet.layout.placements:
            e = self.sheet.element(pl.element_id)
            out[pl.row] = out.get(pl.row, 0) + e.modules
        return out


class LayoutView(QGraphicsView):
    def __init__(self, scene: LayoutScene):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self._panning, self._pan_last = False, None
        self.scale(2, 2)

    def wheelEvent(self, ev):
        f = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        cur = self.transform().m11()
        if 0.3 < cur * f < 40:
            self.scale(f, f)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MiddleButton:
            self._panning, self._pan_last = True, ev.position()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._panning and self._pan_last is not None:
            d = ev.position() - self._pan_last
            self._pan_last = ev.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MiddleButton:
            self._panning = False
            return
        super().mouseReleaseEvent(ev)

    def zoom_fit(self) -> None:
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
