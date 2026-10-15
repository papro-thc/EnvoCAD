"""Scéna a pohled editoru: mřížka, snap, režimy (výběr / vkládání / vodič), zoom a posun."""
from __future__ import annotations

import logging
from enum import Enum
from itertools import pairwise
from typing import ClassVar

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence, QMouseEvent, QPainter, QPen, QUndoStack, QWheelEvent
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from envocad.library.store import LibraryStore
from envocad.model.multipole import default_conductors
from envocad.model.project import (
    WIRE_ATTRIBUTES,
    Element,
    Project,
    Sheet,
    Wire,
    WireEnd,
    element_symbol,
    feed_link_attrs,
)
from envocad.model.symbol import GRID
from envocad.ui import commands
from envocad.ui.items import ElementItem, WireItem, route, snap
from envocad.ui.render import draw_frame, draw_text, sp
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
        it = ElementItem(e, element_symbol(self.project, e, self.library))
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
            hit = self._port_near(p) or self._branch_at(p)   # port, nebo T-odbočka na vodiči
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
                    w.conductors = default_conductors(a.element, pa, b.element, pb)
                    for j in (a.element, b.element):   # odbočka z uzlu: žíly a kabel podle vodiče, na kterém uzel je
                        if j.symbol_id == "sb.junction":
                            src = next((x for x in self.sheet.wires if x.touches(j.id)), None)
                            if src is not None:
                                w.conductors = list(src.conductors)
                            break
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

    def _branch_at(self, pos: QPointF) -> tuple[ElementItem, str] | None:
        """Klik na vodič v režimu kreslení: vodič se rozdělí uzlem odbočky a vrátí se jeho volný port."""
        from envocad.model.potential import junction_free_port, split_wire
        wit = next((it for it in self.items(pos) if isinstance(it, WireItem)), None)
        if wit is None:
            return None
        x, y = snap(pos.x()), -snap(pos.y())
        j, w1, w2 = split_wire(self.sheet, wit.wire, x, y)
        self.undo.push(commands.SplitWireCommand(self, wit.wire.id, j, w1, w2))
        port = junction_free_port(self.sheet, j)
        return (self.element_items[j.id], port) if port else None

    def _used_refs_for(self, symbol_id: str) -> set[str]:
        """Označení pro kontrolu duplicit; skupiny svorek sdílejí označení svorkovnice, ty se nekontrolují."""
        if symbol_id in ("sb.terminal_block", "fve.terminal"):
            return set()
        return self.project.used_refs(self.sheet)

    def _parent_widget(self):
        return self.views()[0] if self.views() else None

    def _finish_place(self, sym, e: Element) -> None:
        from envocad.ui.dialogs import ElementDialog
        log.info("dialog: vložit %s", sym.id)
        dlg = ElementDialog(sym, e.attrs, self._parent_widget(), library=self.library,
                            wire_choices=self._wire_choices(sym.id))
        dlg.used_refs = self._used_refs_for(sym.id)
        if dlg.exec() != ElementDialog.Accepted:
            return
        e.attrs = dlg.values()
        if dlg.wire_combo is not None:
            e.attrs.update(feed_link_attrs(self.project, self.sheet, e, dlg.wire_id))
        e.component_id = dlg.component_id
        self.undo.push(commands.AddElementCommand(self, e))

    def _finish_wire(self, w: Wire, heading: str) -> None:
        from envocad.ui.dialogs import WireDialog
        log.info("dialog: vložit vodič")
        dlg = WireDialog(w.attrs, w.conductors, self._parent_widget(), "Vložit vodič", heading)
        dlg.used_refs = self.project.used_refs(self.sheet)
        if dlg.exec() != WireDialog.Accepted:
            return
        w.attrs = dlg.values()
        w.conductors = dlg.conductors()
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
                QTimer.singleShot(0, lambda wid=wid: self.edit_wire(wid))
                return None
        super().mouseDoubleClickEvent(ev)

    def edit_wire(self, wid: str) -> None:
        from envocad.ui.dialogs import WireDialog
        w = next(w for w in self.sheet.wires if w.id == wid)
        dlg = WireDialog(w.attrs, w.conductors, self._parent_widget(), f"Upravit vodič {w.attrs.get('ref', '')}")
        dlg.used_refs = self.project.used_refs(self.sheet)
        if dlg.exec() != WireDialog.Accepted:
            return
        label = f"Upravit {w.attrs.get('ref') or 'vodič'}"
        new, conds = dlg.values(), dlg.conductors()
        attr_changed = any(w.attrs.get(k, "") != v for k, v in new.items())
        cond_changed = conds != w.conductors
        if not (attr_changed or cond_changed):
            return
        self.undo.beginMacro(label)
        if attr_changed:
            self._apply_attr_changes(wid, True, w.attrs, new, label)
        if cond_changed:
            self.undo.push(commands.SetConductorsCommand(self, wid, w.conductors, conds))
        self.undo.endMacro()

    def edit_terminals(self, wid: str) -> None:
        from envocad.ui.dialogs import TerminalsDialog
        w = next(w for w in self.sheet.wires if w.id == wid)
        dlg = TerminalsDialog(self.sheet, w, self._parent_widget())
        if dlg.exec() != TerminalsDialog.Accepted:
            return
        if dlg.values() != w.terminals:
            self.undo.push(commands.SetTerminalsCommand(self, wid, w.terminals, dlg.values()))

    def auto_number_terminals(self) -> int:
        """Automatické číslování svorek na listu; vrací počet změněných vodičů."""
        from envocad.model.multipole import auto_number_terminal_blocks, auto_number_terminals
        blocks = auto_number_terminal_blocks(self.sheet)
        changes = auto_number_terminals(self.sheet)
        if blocks or changes:
            self.undo.beginMacro("Očíslovat svorky")
            for eid, nums in blocks.items():
                self.undo.push(commands.SetAttrCommand(self, eid, False, "terminal",
                                                       self.sheet.element(eid).attrs.get("terminal", ""), nums))
            for wid, new in changes.items():
                old = next(w for w in self.sheet.wires if w.id == wid).terminals
                self.undo.push(commands.SetTerminalsCommand(self, wid, old, new))
            self.undo.endMacro()
        return len(blocks) + len(changes)

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
        sym = element_symbol(self.project, e, self.library)
        dlg = ElementDialog(sym, e.attrs, self._parent_widget(), title=f"Upravit: {e.ref or sym.name}",
                            library=self.library, component_id=e.component_id, wire_choices=self._wire_choices(sym.id))
        dlg.used_refs = self._used_refs_for(sym.id)
        if dlg.exec() != ElementDialog.Accepted:
            return
        vals = dlg.values()
        if dlg.wire_combo is not None:
            vals.update(feed_link_attrs(self.project, self.sheet, e, dlg.wire_id))
        self.undo.beginMacro(f"Upravit {e.ref or sym.name}")
        if dlg.component_id != e.component_id:
            self.undo.push(commands.SetComponentCommand(self, eid, e.component_id, dlg.component_id))
        self._apply_attr_changes(eid, False, e.attrs, vals, f"Upravit {e.ref or sym.name}")
        if dlg.wire_combo is not None and dlg.wire_id:
            self._take_conductors_from_link(eid, dlg.wire_id)
        self.undo.endMacro()

    def _wire_choices(self, symbol_id: str):
        from envocad.model.project import FEED_SYMBOLS, wire_choices
        return wire_choices(self.project, self.sheet) if symbol_id in FEED_SYMBOLS else None

    def _take_conductors_from_link(self, eid: str, wire_id: str) -> None:
        """Vodiče napojené na přívod/vývod převezmou žíly z navázaného vodiče JPS."""
        from envocad.model.project import linked_wire
        hit = linked_wire(self.project, self.sheet, self.sheet.element(eid))
        if hit is None or not hit[1].conductors:
            return
        conds = list(hit[1].conductors)
        for w in self.sheet.wires:
            if w.touches(eid) and w.conductors != conds:
                self.undo.push(commands.SetConductorsCommand(self, w.id, w.conductors, conds))

    def wire_xref(self, w: Wire) -> str:
        from envocad.model.project import wire_xref
        return wire_xref(self.project, w.id)

    def element_xref(self, e: Element) -> str:
        from envocad.model.project import element_xref
        return element_xref(self.project, self.sheet, e)

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
        elif ev.matches(QKeySequence.Copy):
            self.copy_selected()
        elif ev.matches(QKeySequence.Paste):
            self.paste()
        else:
            super().keyPressEvent(ev)

    # ---- akce ---------------------------------------------------------------
    CLIPBOARD: ClassVar[dict] = {}  # sdílená schránka všech scén (výřez listu + počet vložení pro posun)

    def copy_selected(self) -> int:
        from envocad.model.project import copy_fragment
        eids = [it.element.id for it in self.selectedItems() if isinstance(it, ElementItem)]
        if not eids:
            return 0
        SchematicScene.CLIPBOARD = {"fragment": copy_fragment(self.sheet, eids), "n": 0}
        log.info("copy %d prvků", len(eids))
        return len(eids)

    def paste(self) -> int:
        from envocad.model.project import paste_fragment
        clip = SchematicScene.CLIPBOARD
        if not clip:
            return 0
        clip["n"] += 1
        d = 10.0 * clip["n"]
        els, wires = paste_fragment(self.project, clip["fragment"],
                                    lambda sid: self.library.get_symbol(sid).iec_ref, d, -d)
        if not els:
            return 0
        self.undo.push(commands.PasteCommand(self, els, wires))
        return len(els)

    def insert_fragment(self, fragment: dict, at: tuple[float, float] | None = None) -> int:
        """Vloží výřez (makro) se středem v bodě `at` (model mm); bez bodu doprostřed listu. Označení se přečíslují."""
        from envocad.library.macros import fragment_bounds
        from envocad.model.project import paste_fragment
        x0, y0, x1, y1 = fragment_bounds(fragment)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        tx, ty = at if at is not None else (self.sheet.width / 2, self.sheet.height / 2)
        dx, dy = snap(tx - cx), snap(ty - cy)
        els, wires = paste_fragment(self.project, fragment, lambda sid: self.library.get_symbol(sid).iec_ref, dx, dy)
        if not els:
            return 0
        self.undo.push(commands.PasteCommand(self, els, wires))
        return len(els)

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

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        """Rámeček s popisovým polem, můstky mezi skupinami svorek (čárkovaně) a informační blok rozvaděče."""
        from envocad.model.frame import MARGIN, MARGIN_LEFT, frame_geometry
        c = PRINT if not self.draw_grid else colors()
        draw_frame(painter, frame_geometry(self.project, self.sheet), c.ink)
        self._draw_bridges(painter)
        if not self.sheet.is_switchboard:
            return
        from envocad.model.project import switchboard_header
        rows = switchboard_header(self.project, self.sheet)
        if not rows:
            return
        x0, y0 = MARGIN_LEFT + 4.0, self.sheet.height - MARGIN - 4.0  # model (Y nahoru), uvnitř rámečku
        lh = 4.0
        w, h = 95.0, lh * len(rows) + 3
        painter.setPen(QPen(c.ink, 0.25))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(x0 - 2, -(y0 + 2), w, h))
        painter.drawLine(sp(x0 + 30, y0 + 2), sp(x0 + 30, y0 + 2 - h))
        for i, (k, v) in enumerate(rows):
            y = y0 - 2.5 - i * lh
            painter.setPen(QPen(c.ink, 0.2))
            draw_text(painter, x0, y, k, 2.5, "left")
            draw_text(painter, x0 + 32, y, v, 2.5, "left")

    def _draw_bridges(self, painter: QPainter) -> None:
        """Skupiny svorek jedné svorkovnice spojené můstkem: čárkovaná čára mezi prvky (JPS nemá jednotlivé svorky)."""
        if not self.sheet.bridges:
            return
        from envocad.model.multipole import is_terminal_block, terminal_numbers, wire_conductors
        owner: dict[tuple[str, str], Element] = {}
        for e in self.sheet.elements:
            if not is_terminal_block(e) or not e.ref:
                continue
            n = len({c for w in self.sheet.wires for end in (w.a, w.b) if end.element_id == e.id
                     for c in wire_conductors(w)}) or 1
            for num in terminal_numbers(e, n):
                if num:
                    owner[(e.ref, num)] = e
        pairs: set[tuple[str, str]] = set()
        for strip, groups in self.sheet.bridges.items():
            for g in groups:
                els = {owner[(strip, n)].id: owner[(strip, n)] for n in g if (strip, n) in owner}
                lst = sorted(els.values(), key=lambda e: (e.x, e.y))
                for a, b in pairwise(lst):
                    pairs.add((a.id, b.id))
        if not pairs:
            return
        c = PRINT if not self.draw_grid else colors()
        painter.setPen(QPen(c.wire, 0.3, Qt.DashLine))
        for aid, bid in pairs:
            a, b = self.sheet.element(aid), self.sheet.element(bid)
            painter.drawLine(sp(a.x, a.y), sp(b.x, b.y))

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
