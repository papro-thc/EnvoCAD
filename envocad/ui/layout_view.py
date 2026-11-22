"""Pohled fyzického rozložení rozvaděče: řady DIN lišt, přístroje ve skutečné šířce a výšce (`model/device_size`:
ruční rozměr > artikl > moduly z atributu, výška 45 mm), svisle na střed osy lišty."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QUndoCommand, QUndoStack
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from envocad.library.store import LibraryStore
from envocad.model.device_size import SHAPE_BOX, SHAPE_TERMINAL, DeviceSize, device_size
from envocad.model.layout_geometry import (  # noqa: F401 – konstanty zůstávají dostupné i odsud
    MARGIN,
    ROW_H,
    UNPLACED_X_GAP,
    device_width_mm,
)
from envocad.model.project import DEVICE_HEIGHT_MM, MODULE_WIDTH, Element, Project, Sheet, terminal_count
from envocad.ui.render import draw_text
from envocad.ui.theme import colors

SNAP = 0.5          # modulu


class SetPlacementCommand(QUndoCommand):
    def __init__(self, scene: LayoutScene, eid: str, old: tuple | None, new: tuple | None):
        super().__init__("Umístit přístroj")
        self.scene, self.eid, self.old, self.new = scene, eid, old, new
        self._first = True

    def _apply(self, v):
        self.scene.sheet.layout.set_placement(self.eid, *(v or (None, None)))
        self.scene.sync_positions()
        self.scene.layout_changed.emit()

    def redo(self):
        self._first = False
        self._apply(self.new)

    def undo(self):
        self._apply(self.old)


class DeviceItem(QGraphicsRectItem):
    """Přístroj v rozložení. Kreslí footprint artiklu (symbol v mm), jinak generický tvar podle `DeviceSize.shape`:
    modulový přístroj (páčky po pólech), obdélník š × v (kompaktní jistič), svorky (úzké obdélníky)."""

    def __init__(self, element: Element, name: str, placed: bool, footprint=None, kind: str = "",
                 size: DeviceSize | None = None):
        self.size = size if size is not None else device_size(element)
        # skutečný rozměr (artikl / ruční mm) se kreslí, jak je; šířka z modulů nejméně 1 modul jako dřív
        super().__init__(0, 0, device_width_mm(self.size), self.size.height_mm)
        self.element, self.name, self.placed, self.footprint, self.kind = element, name, placed, footprint, kind
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(5)

    @property
    def modules(self) -> float:
        return self.size.modules

    def paint(self, painter, option, widget=None):
        c = colors()
        painter.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        pen = QPen(c.selection if self.isSelected() else c.ink, 0.4, Qt.SolidLine if self.placed else Qt.DashLine)
        fill = QColor(c.selection) if self.isSelected() else QColor(c.ink)
        fill.setAlpha(40 if self.placed else 15)
        painter.setBrush(QBrush(fill))
        painter.setPen(pen)
        painter.drawRect(r)
        if self.footprint is not None:
            # footprint = symbol v mm, počátek v levém horním rohu přístroje (Y nahoru → převrátit)
            from envocad.ui.render import paint_symbol
            painter.save()
            painter.translate(r.left(), r.top())  # paint_symbol převrací Y sám (model Y nahoru → scéna Y dolů)
            paint_symbol(painter, self.footprint, QPen(pen.color(), 0.25))
            painter.restore()
        else:
            self._paint_generic(painter, pen, r)
        painter.setPen(QPen(c.ink, 0.2))
        draw_text(painter, r.center().x(), -(r.top() + 8), self.element.ref, 3.0, "center")
        typ = self.element.attrs.get("type") or self.name
        if typ:
            draw_text(painter, r.center().x(), -(r.top() + 14), typ[:18], 2.0, "center")
        info = " ".join(x for x in (self.element.attrs.get("in_", ""), self.element.attrs.get("char", "")) if x)
        if self.size.shape == SHAPE_TERMINAL and self.size.real:   # svorka z artiklu: průřez místo In
            cross = self.element.attrs.get("cross", "")
            info = f"{cross} mm²" if cross else ""
        if info:
            draw_text(painter, r.center().x(), -(r.top() + 19), info, 2.0, "center")
        draw_text(painter, r.center().x(), -(r.bottom() - 2), self.size_label(), 1.8, "center")

    def size_label(self) -> str:
        """Popisek pod přístrojem: „3 M“, obdélník „76,2 × 130 mm“, svorky „5 × 3,5 mm“ (z artiklu)."""
        return self.size.label(terminal_count(self.element))

    def _paint_generic(self, painter, pen, r):
        """Generický tvar: modulový přístroj (páčky po pólech, svorky nahoře/dole), kompaktní jistič / MCCB (obdélník
        s pákou uprostřed), svorkovnice (úzké obdélníky po svorkách)."""
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(pen.color(), 0.25))
        poles = max(self.element.poles, 1)
        if self.size.shape == SHAPE_TERMINAL and self.size.real:   # bez artiklu kreslí jako dřív (moduly)
            n = terminal_count(self.element)
            tw = (r.width() - self.size.end_mm) / max(n, 1)
            for i in range(1, n):
                x = r.left() + i * tw
                painter.drawLine(QPointF(x, r.top() + 2), QPointF(x, r.bottom() - 2))
            return
        if self.size.shape == SHAPE_BOX or self.kind in ("mccb",):
            hw = r.width() * 0.5
            hh = min(10.0, r.height() * 0.2)
            painter.drawRect(QRectF(r.center().x() - hw / 2, r.center().y() - hh / 2, hw, hh))
            # svorky po pólech nahoře a dole
            pw = r.width() / poles
            for i in range(poles):
                cx = r.left() + (i + 0.5) * pw
                painter.drawRect(QRectF(cx - min(pw * 0.3, 6), r.top() + 2, min(pw * 0.6, 12), 6))
                painter.drawRect(QRectF(cx - min(pw * 0.3, 6), r.bottom() - 8, min(pw * 0.6, 12), 6))
            return
        mods = max(self.modules, 1.0)
        lever_y = r.top() + 22 + (r.height() - DEVICE_HEIGHT_MM) / 2   # páčka uprostřed výšky (45 mm: jako dřív)
        pole_w = r.width() / max(min(poles, mods), 1)
        n = int(min(poles, mods)) if mods >= 1 else 1
        for i in range(n):
            x = r.left() + i * pole_w
            painter.drawRect(x + pole_w * 0.25, lever_y, pole_w * 0.5, 9)  # páčka
            painter.drawEllipse(x + pole_w / 2 - 2.5, r.top() + 2, 5, 5)        # svorka nahoře
            painter.drawEllipse(x + pole_w / 2 - 2.5, r.bottom() - 7, 5, 5)     # svorka dole


class LayoutScene(QGraphicsScene):
    selection_info = Signal(object)
    enclosure_requested = Signal()  # dvojklik do prázdné plochy → fokus do panelu skříně
    layout_changed = Signal()       # po umístění přístroje (přepočet obsazenosti)

    def __init__(self, project: Project, sheet: Sheet, library: LibraryStore, undo: QUndoStack):
        super().__init__()
        self.project, self.sheet, self.library, self.undo = project, sheet, library, undo
        self.items_by_id: dict[str, DeviceItem] = {}
        self._drag_start: dict[str, tuple | None] = {}
        self.selectionChanged.connect(self._on_selection)  # vázaná metoda – Qt ji při smazání scény odpojí
        self.rebuild()

    def _on_selection(self) -> None:
        try:
            sel = self.selectedItems()
        except RuntimeError:  # scéna se právě likviduje
            return
        self.selection_info.emit(sel[0] if len(sel) == 1 else None)

    # ---- geometrie ----------------------------------------------------------
    @property
    def enclosure_w(self) -> float:
        return self.sheet.layout.modules_per_row * MODULE_WIDTH

    @property
    def row_h(self) -> float:
        return self.sheet.layout.row_pitch_mm

    def row_rect(self, row: int) -> QRectF:
        return QRectF(MARGIN, MARGIN + row * self.row_h, self.enclosure_w, self.row_h)

    def rail_y(self, row: int) -> float:
        """Horní hrana modulového přístroje (45 mm) v řadě – lišta a značky modulů."""
        return MARGIN + row * self.row_h + (self.row_h - DEVICE_HEIGHT_MM) / 2

    def axis_y(self, row: int) -> float:
        """Osa řady (DIN lišty) – přístroje jsou na ní svisle na střed."""
        return MARGIN + (row + 0.5) * self.row_h

    def pos_to_scene(self, row: int, pos: float, height: float = DEVICE_HEIGHT_MM) -> QPointF:
        return QPointF(MARGIN + pos * MODULE_WIDTH, self.axis_y(row) - height / 2)

    def scene_to_placement(self, p: QPointF, width_modules: float,
                           height: float = DEVICE_HEIGHT_MM) -> tuple[int, float] | None:
        """Bod levého horního rohu přístroje výšky `height` → (řada, pozice) nebo None (mimo skříň)."""
        lay = self.sheet.layout
        cy = p.y() + height / 2
        if p.x() < MARGIN - MODULE_WIDTH or p.x() > MARGIN + self.enclosure_w or cy < MARGIN or cy > MARGIN + lay.rows * self.row_h:
            return None
        row = int((cy - MARGIN) // self.row_h)
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
                it.setPos(self.pos_to_scene(pl.row, pl.pos, it.rect().height()))
            else:
                it.setPos(ux, unplaced_y)
                unplaced_y += it.rect().height() + 8
            it.update()

    def rebuild(self) -> None:
        """Úplná přestavba – volat jen mimo obsluhu událostí myši (po šabloně, změně skříně, tématu)."""
        self.clear()
        self.items_by_id.clear()
        lay = self.sheet.layout
        c = colors()
        # obrys skříně ve skutečných rozměrech (DIN lišty vycentrované uvnitř)
        inner_w, inner_h = self.enclosure_w, lay.rows * self.row_h
        ew, eh = lay.outline_mm      # stejný obrys jako kontrola rozměrů (`device_size.size_problems`)
        self._encl_rect = QRectF(MARGIN - (ew - inner_w) / 2, MARGIN - (eh - inner_h) / 2, ew, eh)
        encl = QGraphicsRectItem(self._encl_rect)
        encl.setPen(QPen(c.paper, 0.8))
        encl.setZValue(-2)
        self.addItem(encl)
        # tisk (PDF): lišty světle šedé – tiskové barvy mřížky jsou bílé
        rail_line = QColor(150, 150, 150) if getattr(self, "printing", False) else c.grid_major
        rail_fill = QColor(235, 235, 235) if getattr(self, "printing", False) else QColor(c.grid)
        for r in range(lay.rows):
            rail = QGraphicsRectItem(MARGIN, self.rail_y(r) + DEVICE_HEIGHT_MM / 2 - 17.5, self.enclosure_w, 35)
            rail.setPen(QPen(rail_line, 0.3))
            rail.setBrush(QBrush(rail_fill))
            rail.setZValue(-1)
            self.addItem(rail)
            for m in range(lay.modules_per_row + 1):
                x = MARGIN + m * MODULE_WIDTH
                tick = self.addLine(x, self.rail_y(r) + DEVICE_HEIGHT_MM, x, self.rail_y(r) + DEVICE_HEIGHT_MM + (3 if m % 6 else 6), QPen(rail_line, 0.2))
                tick.setZValue(-1)
        # přístroje
        unplaced_y = MARGIN
        ux = MARGIN + self.enclosure_w + UNPLACED_X_GAP
        for e in self.sheet.layout.devices(self.sheet, self.project, self.library):
            sym = self.library.get_symbol(e.symbol_id)
            pl = lay.placement(e.id)
            fp, kind, comp = None, "", None
            if e.component_id:
                comp = self.library.component(e.component_id)
                if comp:
                    kind = comp.category
                    if comp.footprint_id:
                        try:
                            fp = self.library.get_symbol(comp.footprint_id)
                        except KeyError:
                            fp = None
            it = DeviceItem(e, sym.name, pl is not None, fp, kind, device_size(e, comp=comp))
            if pl:
                it.setPos(self.pos_to_scene(pl.row, pl.pos, it.rect().height()))
            else:
                it.setPos(ux, unplaced_y)
                unplaced_y += it.rect().height() + 8
            self.addItem(it)
            self.items_by_id[e.id] = it
        label = self.addSimpleText("")
        label.setZValue(-1)
        self.setSceneRect(self._encl_rect.united(QRectF(0, 0, ux + 6 * MODULE_WIDTH + MARGIN,
                                                         max(lay.rows * self.row_h, unplaced_y) + 2 * MARGIN)).adjusted(-10, -25, 10, 10))

    # ---- interakce -----------------------------------------------------------
    def mousePressEvent(self, ev):
        super().mousePressEvent(ev)
        self._drag_start = {}
        lay = self.sheet.layout
        for it in self.selectedItems():
            if isinstance(it, DeviceItem):
                # (platné umístění, uložené umístění) – uložené může ležet mimo skříň (po zmenšení počtu řad);
                # o přesunu rozhoduje platné, undo vrací uložené
                pl, st = lay.placement(it.element.id), lay.stored_placement(it.element.id)
                self._drag_start[it.element.id] = ((pl.row, pl.pos) if pl else None, (st.row, st.pos) if st else None)

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        self.finish_drag()

    def finish_drag(self) -> None:
        """Konec tažení: přesunuté přístroje → SetPlacementCommand (undo vrací uložené umístění), jinak snap zpět."""
        moves = []
        for eid, (shown, stored) in self._drag_start.items():
            it = self.items_by_id.get(eid)
            if it is None:
                continue
            new = self.scene_to_placement(it.pos(), it.modules, it.rect().height())
            if new != shown:
                moves.append((eid, stored, new))
        self._drag_start = {}
        if moves:
            self.undo.beginMacro("Umístit přístroje") if len(moves) > 1 else None
            for eid, old, new in moves:
                self.undo.push(SetPlacementCommand(self, eid, old, new))
            self.undo.endMacro() if len(moves) > 1 else None
        else:
            self.sync_positions()  # přitáhnout zpět na mřížku

    def mouseDoubleClickEvent(self, ev):
        if not any(isinstance(it, DeviceItem) for it in self.items(ev.scenePos())):
            self.enclosure_requested.emit()
            return
        super().mouseDoubleClickEvent(ev)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        c = colors()
        lay = self.sheet.layout
        painter.fillRect(rect, c.background)
        painter.setPen(QPen(c.ink, 0.2))
        top = self._encl_rect.top() if hasattr(self, "_encl_rect") else MARGIN
        dims = f"{lay.width_mm:g} × {lay.height_mm:g}" + (f" × {lay.depth_mm:g}" if lay.depth_mm else "") + " mm"
        used, total = lay.used_modules(self.sheet, self.project, self.library), lay.total_modules
        printing = getattr(self, "printing", False)     # PDF: bez nápovědy editoru
        enc = lay.enclosure or ("–" if printing else "– (dvojklik = nastavení)")
        line1 = f"{self.sheet.name}   skříň: {enc}   {dims}   {lay.params.get('ip', '')}"
        line2 = (f"{lay.rows} řad × {lay.modules_per_row} modulů = {total} M, obsazeno {used:g} M "
                 f"({(used / total * 100) if total else 0:.0f} %), rezerva {total - used:g} M")
        draw_text(painter, self._encl_rect.left() if hasattr(self, "_encl_rect") else MARGIN, -(top - 13), line1, 3.5, "left")
        draw_text(painter, self._encl_rect.left() if hasattr(self, "_encl_rect") else MARGIN, -(top - 7), line2, 2.5, "left")
        if not printing or any(lay.placement(e.id) is None for e in lay.devices(self.sheet, self.project, self.library)):
            draw_text(painter, MARGIN + self.enclosure_w + UNPLACED_X_GAP, -(MARGIN - 6), "Nerozmístěno", 3.0, "left")


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
