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
    SWITCHBOARD_WIRE_ATTRIBUTES,
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
from envocad.ui.notes_view import NoteItem
from envocad.ui.render import draw_frame, draw_geometry, draw_revision_marks, draw_text, sp
from envocad.ui.theme import PRINT, colors

log = logging.getLogger("envocad.ui")


class Mode(Enum):
    SELECT = 0
    PLACE = 1
    WIRE = 2
    NOTE = 3


class SchematicScene(QGraphicsScene):
    selection_info = Signal(object)       # ElementItem | WireItem | None
    attrs_changed = Signal(str)           # id elementu/vodiče
    mode_changed = Signal(object)         # Mode
    open_switchboard = Signal(str)        # id bloku ROZVADĚČ
    followup_wires = Signal(list)         # id vodičů (i jiných listů) změněných follow-upy příkazu (commands)

    def __init__(self, project: Project, sheet: Sheet, library: LibraryStore, undo: QUndoStack):
        super().__init__()
        self.project, self.sheet, self.library, self.undo = project, sheet, library, undo
        self.element_items: dict[str, ElementItem] = {}
        self.wire_items: dict[str, WireItem] = {}
        self.note_items: dict[str, NoteItem] = {}
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
        self._note_move_start: dict[str, tuple[float, float]] = {}
        self._note_draw: tuple[QPointF, QPointF, str, bool] | None = None   # kotva (scéna), snap, cíl, vodič?
        self._note_preview = QGraphicsRectItem()
        self._note_preview.setPen(QPen(colors().preview, 0.3, Qt.DashLine))
        self._note_preview.setZValue(20)
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
            if w.a.element_id in self.element_items and w.b.element_id in self.element_items:
                self.add_wire_item(w)   # vodič na neexistující prvek se nekreslí (kontrola ho hlásí)
        from envocad.model.routing import route_sheet
        for wid, pts in route_sheet(self.project, self.sheet, self.library).items():   # stejné trasy jako PDF/DXF
            if wid in self.wire_items:
                self.wire_items[wid].set_points(pts)
        self.invalidate_text_layout()
        self.rebuild_notes()

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
        self.route_wire(it)
        return it

    def remove_wire_item(self, wid: str) -> None:
        it = self.wire_items.pop(wid, None)
        if it:
            self.removeItem(it)

    def route_wire(self, it: WireItem) -> None:
        """Trasa z modelu (model/routing.py): ruční lomy, jinak Z-trasa s odstupem od ostatních vodičů."""
        from envocad.model.routing import _inner_segments, best_route, ends
        from envocad.ui.items import path_points
        others = [(ends(o.wire), _inner_segments(path_points(o.path()))) for o in self.wire_items.values()
                  if o is not it and o.path().elementCount() > 1]
        try:
            it.set_points(best_route(self.project, self.sheet, self.library, it.wire, others))
        except (KeyError, ValueError, AttributeError, StopIteration):
            a = self.element_items.get(it.wire.a.element_id)
            b = self.element_items.get(it.wire.b.element_id)
            if a and b:
                it.update_route(a, b)
        self.invalidate_text_layout()

    # ---- připomínky (redlining) -------------------------------------------------
    notes_visible = False   # výchozí vypnuto; zapíná Zobrazit → Připomínky (exportní scény ho nechávají vypnuté)

    def set_notes_visible(self, visible: bool) -> None:
        self.notes_visible = visible
        self.rebuild_notes()

    def rebuild_notes(self) -> None:
        """Znovu vytvoří položky připomínek listu (otevřené i vyřešené); při vypnutém zobrazení žádné nevzniknou.
        Výběr se zachová podle id."""
        from envocad.model.notes import notes_on_sheet
        from envocad.ui.notes_view import tooltip_text
        selected = {i for i, it in self.note_items.items() if it.isSelected()}
        for it in self.note_items.values():
            self.removeItem(it)
        self.note_items.clear()
        if not self.notes_visible:
            return
        for n in notes_on_sheet(self.project, self.sheet.id):
            it = NoteItem(n)
            it.setToolTip(tooltip_text(self.project, n))
            self.addItem(it)
            self.note_items[n.id] = it
            if n.id in selected:
                it.setSelected(True)

    def edit_note_later(self, nid: str) -> None:
        """Dialog až po doběhnutí události (menu / dvojklik)."""
        QTimer.singleShot(0, lambda: self.edit_note(nid))

    def edit_note(self, nid: str) -> bool:
        from envocad.model.notes import note
        from envocad.ui.dialogs import NoteDialog
        n = note(self.project, nid)
        if n is None:
            return False
        dlg = NoteDialog(n, self._parent_widget(), f"Připomínka č. {n.no}")
        if dlg.exec() != NoteDialog.Accepted:
            return False
        new = dlg.result_note()
        if new == n:
            return False
        self.undo.push(commands.ReplaceNoteCommand(self.project, n, new, f"Upravit připomínku č. {n.no}",
                                                   self.rebuild_notes))
        return True

    def set_note_status(self, nid: str, status: str) -> None:
        from envocad.model.notes import note
        from envocad.settings import current_user
        from envocad.ui.notes_view import reopened_copy, resolved_copy
        n = note(self.project, nid)
        if n is None or n.status == status:
            return
        new = resolved_copy(n, current_user()) if status == "resolved" else reopened_copy(n)
        text = f"Vyřešit připomínku č. {n.no}" if status == "resolved" else f"Znovu otevřít připomínku č. {n.no}"
        self.undo.push(commands.ReplaceNoteCommand(self.project, n, new, text, self.rebuild_notes))

    def delete_note(self, nid: str) -> None:
        from envocad.model.notes import note
        n = note(self.project, nid)
        if n is not None:
            self.undo.push(commands.ReplaceNoteCommand(self.project, n, None, f"Smazat připomínku č. {n.no}",
                                                       self.rebuild_notes))

    def start_note(self) -> None:
        self.set_mode(Mode.NOTE)

    def _note_target(self, pos: QPointF) -> tuple[str, bool]:
        """Prvek, nebo vodič pod bodem (id, je_vodič); prázdné id = nic."""
        for it in self.items(pos):
            if isinstance(it, ElementItem) and it is not self._ghost:
                return it.element.id, False
        for it in self.items(pos):
            if isinstance(it, WireItem):
                return it.wire.id, True
        return "", False

    def _note_from_drag(self, a: QPointF, b: QPointF, target: str, is_wire: bool):
        """Nová připomínka z tahu kotva → bod (obě na mřížce); tah menší než mřížka v některém směru = bod."""
        from envocad.model.project import Note
        from envocad.settings import current_user
        from envocad.ui.notes_view import now_iso
        ax, ay, bx, by = snap(a.x()), -snap(a.y()), snap(b.x()), -snap(b.y())
        w, h = abs(bx - ax), abs(by - ay)
        n = Note(self.sheet.id, x=ax, y=ay, target_id=target, is_wire=is_wire, author=current_user(),
                 created=now_iso())
        if w >= GRID and h >= GRID:
            n.x, n.y, n.w, n.h = min(ax, bx), min(ay, by), w, h
        return n

    def _finish_note(self, n) -> None:
        from envocad.ui.dialogs import NoteDialog
        log.info("dialog: připomínka")
        dlg = NoteDialog(n, self._parent_widget(), "Nová připomínka")
        if dlg.exec() != NoteDialog.Accepted:
            return
        self.undo.push(commands.ReplaceNoteCommand(self.project, None, dlg.result_note(), "Přidat připomínku",
                                                   self.rebuild_notes))

    # ---- rozmístění popisků (model/textlayout) – počítá se líně při kreslení, ruší se při změně geometrie
    _text_layout = None

    _device_index = None

    def device_index(self):
        """`xref.DeviceIndex` projektu – staví se jednou za přepočet (ruší se s rozmístěním popisků)."""
        if self._device_index is None:
            from envocad.model.xref import DeviceIndex
            self._device_index = DeviceIndex.build(self.project)
        return self._device_index

    def invalidate_text_layout(self) -> None:
        self._device_index = None
        if self._text_layout is not None:
            self._text_layout = None
            self.update()

    def text_layout(self):
        if self._text_layout is None:
            from envocad.model.textlayout import compute_layout
            from envocad.ui.items import path_points
            routes = {wid: path_points(it.path()) for wid, it in self.wire_items.items()}
            try:
                self._text_layout = compute_layout(self.project, self.sheet, self.library, routes,
                                                   xref_of=self.wire_xref if not self.sheet.is_switchboard else (lambda w: ""),
                                                   index=self.device_index())
            except Exception:  # noqa: BLE001 – rozmístění nesmí shodit kreslení
                from envocad.model.textlayout import SheetTextLayout
                self._text_layout = SheetTextLayout()
        return self._text_layout

    def element_label(self, e: Element):
        return self.text_layout().elements.get(e.id)

    def wire_label_pos(self, w: Wire):
        return self.text_layout().wires.get(w.id)

    def update_wires_of(self, eid: str) -> None:
        for it in self.wire_items.values():
            if it.wire.touches(eid):
                self.route_wire(it)

    _dragging = False
    _seg = None
    _move_wire_pts: ClassVar[dict] = {}   # při stisku se nahradí vlastním slovníkem instance

    def element_moved(self, it: ElementItem) -> None:
        it.element.x, it.element.y = it.pos().x(), -it.pos().y()
        if self._dragging and it.element.id in self._move_start:
            self._follow_bends(it.element.id)
        self.update_wires_of(it.element.id)

    def _follow_bends(self, eid: str) -> None:
        """Ruční lomy vodičů jdou s posouvanými prvky (oba konce → celý vodič, jeden → lom u něj)."""
        from envocad.model.routing import follow_points, port_geometry
        for w in self.sheet.wires:
            orig = self._move_wire_pts.get(w.id)
            if orig is None or not w.touches(eid):
                continue
            ends = []
            for end in (w.a, w.b):
                e = self.sheet.element(end.element_id)
                _, d = port_geometry(self.project, self.sheet, self.library, e, end.port)
                st = self._move_start.get(end.element_id)
                ends.append((d, (e.x - st[0], e.y - st[1]) if st else (0.0, 0.0)))
            # model-write-ok: živý náhled tažení prvku, uzavře ho MoveElementsCommand při puštění
            w.points = follow_points(orig, ends[0][0], ends[0][1], ends[1][0], ends[1][1])

    # ---- režimy -------------------------------------------------------------
    def set_mode(self, mode: Mode) -> None:
        if self._ghost:
            self.removeItem(self._ghost)
            self._ghost = None
        if self._wire_preview.scene():
            self.removeItem(self._wire_preview)
        self._wire_from = None
        self._place_symbol_id = None
        self._note_draw = None
        if self._note_preview.scene():
            self.removeItem(self._note_preview)
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
        if self.mode == Mode.NOTE and self._note_draw is not None:
            a = self._note_draw[1]
            b = QPointF(snap(p.x()), snap(p.y()))
            if abs(b.x() - a.x()) >= GRID or abs(b.y() - a.y()) >= GRID:
                if not self._note_preview.scene():
                    self.addItem(self._note_preview)
                self._note_preview.setRect(QRectF(a, b).normalized())
            elif self._note_preview.scene():
                self.removeItem(self._note_preview)
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
        if self.mode == Mode.SELECT and self._seg is not None:
            from envocad.model.routing import drag_segment
            it, idx, start, pts, _old = self._seg
            a, b = pts[idx], pts[idx + 1]
            off = snap(-p.y() - start[1]) if abs(a[1] - b[1]) < 1e-6 else snap(p.x() - start[0])
            new = drag_segment(pts, idx, off) if off else None
            # model-write-ok: živý náhled tažení úseku, uzavře ho SetWirePointsCommand při puštění
            it.wire.points = new if new is not None else list(_old)
            self.route_wire(it)
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
            # model-write-ok: nový prvek (ještě není v listu), vloží ho AddElementCommand
            e.attrs = {a.key: a.default for a in sym.attributes}
            e.attrs["ref"] = self.project.next_ref(sym.iec_ref)
            if self.ask_attributes:
                # modální dialog až po doběhnutí události myši (uvnitř obsluhy stisku padá Qt na Windows)
                QTimer.singleShot(0, lambda: self._finish_place(sym, e))
            else:
                self.undo.push(commands.AddElementCommand(self, e))
            return  # zůstáváme v režimu vkládání (Esc / pravé tlačítko ukončí)
        if self.mode == Mode.NOTE:
            if ev.button() == Qt.LeftButton:
                target, is_wire = self._note_target(p)
                self._note_draw = (p, QPointF(snap(p.x()), snap(p.y())), target, is_wire)
            return
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
                    # model-write-ok: nový vodič (ještě není v listu), vloží ho AddWireCommand
                    w.conductors = default_conductors(a.element, pa, b.element, pb)
                    for j in (a.element, b.element):   # odbočka z uzlu: žíly a kabel podle vodiče, na kterém uzel je
                        if j.symbol_id == "sb.junction":
                            src = next((x for x in self.sheet.wires if x.touches(j.id)), None)
                            if src is not None:
                                w.conductors = list(src.conductors)  # model-write-ok: nový vodič, viz výše
                            break
                    # model-write-ok: nový vodič (ještě není v listu), vloží ho AddWireCommand
                    w.attrs = {at.key: at.default for at in WIRE_ATTRIBUTES}
                    w.attrs["ref"] = self.project.next_ref("W")
                    if self.ask_attributes:
                        heading = f"<b>Vodič</b> {a.element.ref}:{pa} → {b.element.ref}:{pb}"
                        QTimer.singleShot(0, lambda: self._finish_wire(w, heading))
                    else:
                        self.undo.push(commands.AddWireCommand(self, w))
            return
        # SELECT: úsek vodiče se dá chytit a posunout kolmo (vodorovný nahoru/dolů, svislý do stran)
        self._seg = None
        self._note_move_start = {}
        if ev.button() == Qt.LeftButton:
            from PySide6.QtGui import QTransform

            from envocad.model.routing import nearest_segment
            from envocad.ui.items import path_points
            top = self.itemAt(p, QTransform())
            if isinstance(top, WireItem):
                pts = path_points(top.path())
                idx = nearest_segment(pts, p.x(), -p.y(), tol=2.5)
                if idx is not None and 0 < idx < len(pts) - 2:
                    self._seg = (top, idx, (p.x(), -p.y()), pts, [tuple(x) for x in top.wire.points])
        # SELECT: zapamatovat výchozí pozice pro undo posunu
        super().mousePressEvent(ev)
        if self._seg is not None:
            self.clearSelection()
            self._seg[0].setSelected(True)
            self._move_start = {}
            return
        self._move_start = {it.element.id: (it.element.x, it.element.y)
                            for it in self.selectedItems() if isinstance(it, ElementItem)}
        self._move_wire_pts = {w.id: [tuple(x) for x in w.points] for w in self.sheet.wires if w.points and
                               (w.a.element_id in self._move_start or w.b.element_id in self._move_start)}
        self._dragging = bool(self._move_start)
        self._note_move_start = {it.note.id: (it.note.x, it.note.y) for it in self.selectedItems()
                                 if isinstance(it, NoteItem)}

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
        # model-write-ok: nový prvek z dialogu, do modelu ho vloží AddElementCommand
        e.attrs = dlg.values()
        if dlg.wire_combo is not None:
            e.attrs.update(feed_link_attrs(self.project, self.sheet, e, dlg.wire_id))
        e.component_id = dlg.component_id
        self.undo.push(commands.AddElementCommand(self, e))

    def _wire_dialog_extra(self, w: Wire) -> dict:
        """Na listu rozvaděče navíc výrobní atributy vodiče (barva, koncovky, do výrobního seznamu) a jejich placeholdery."""
        if not self.sheet.is_switchboard:
            return {}
        from dataclasses import replace

        from envocad.model.wiring import wire_end_labels
        from envocad.ui.dialogs import wire_auto_hints
        labels = wire_end_labels(self.sheet, w)   # „Koncovka A (F2:2)“ – u popisku konec vodiče
        return {"attributes": WIRE_ATTRIBUTES + [replace(a, label=labels.get(a.key, a.label))
                                                 for a in SWITCHBOARD_WIRE_ATTRIBUTES],
                "hints": wire_auto_hints(self.project, self.sheet, w)}

    def _finish_wire(self, w: Wire, heading: str) -> None:
        from envocad.ui.dialogs import WireDialog
        log.info("dialog: vložit vodič")
        dlg = WireDialog(w.attrs, w.conductors, self._parent_widget(), "Vložit vodič", heading,
                         **self._wire_dialog_extra(w))
        dlg.used_refs = self.project.used_refs(self.sheet)
        if dlg.exec() != WireDialog.Accepted:
            return
        # model-write-ok: nový vodič z dialogu, do modelu ho vloží AddWireCommand
        w.attrs = dlg.values()
        w.conductors = dlg.conductors()
        self.undo.push(commands.AddWireCommand(self, w))

    def mouseDoubleClickEvent(self, ev):
        if self.mode != Mode.SELECT:
            return super().mouseDoubleClickEvent(ev)
        for nit in self.items(ev.scenePos()):
            if isinstance(nit, NoteItem):
                self.edit_note_later(nit.note.id)
                return None
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
        dlg = WireDialog(w.attrs, w.conductors, self._parent_widget(), f"Upravit vodič {w.attrs.get('ref', '')}",
                         **self._wire_dialog_extra(w))
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
        # vazba přívodu (`wire_id`) před označením: přejmenování (`feed_port_followups`) pak přejmenuje port nově
        # navázaného vodiče JPS; v opačném pořadí by port dostal dosavadní vodič a nová vazba by se ztratila
        changed.sort(key=lambda kv: kv[0] != "wire_id")
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
        from envocad.model.project import effective_feed_wire
        lw = effective_feed_wire(self.project, self.sheet, self.sheet.element(eid))
        if lw is None or not lw.conductors:
            return
        conds = list(lw.conductors)
        for w in self.sheet.wires:
            if w.touches(eid) and w.conductors != conds:
                self.undo.push(commands.SetConductorsCommand(self, w.id, w.conductors, conds))

    _xref_index: dict | None = None   # cache vazeb přívodů na vodiče pro překreslení; ruší se při změně modelu

    def invalidate_xrefs(self) -> None:
        self._xref_index = None
        self.invalidate_text_layout()

    def wire_xref(self, w: Wire) -> str:
        from envocad.model.project import feed_link_index, wire_xref
        if self._xref_index is None:
            self._xref_index = feed_link_index(self.project)
        return wire_xref(self.project, w.id, self._xref_index)

    def element_xref(self, e: Element) -> str:
        from envocad.model.project import element_xref
        return element_xref(self.project, self.sheet, e, self.device_index())

    def mouseReleaseEvent(self, ev):
        if self.mode == Mode.NOTE:
            draw, self._note_draw = self._note_draw, None
            if self._note_preview.scene():
                self.removeItem(self._note_preview)
            if draw is not None and ev.button() == Qt.LeftButton:
                n = self._note_from_drag(draw[0], ev.scenePos(), draw[2], draw[3])
                if self.ask_attributes:
                    QTimer.singleShot(0, lambda: self._finish_note(n))
                else:
                    self.undo.push(commands.ReplaceNoteCommand(self.project, None, n, "Přidat připomínku",
                                                               self.rebuild_notes))
            return
        super().mouseReleaseEvent(ev)
        note_moves = self._take_note_moves()
        if self._seg is not None:
            self._push_note_moves(note_moves)
            it, _idx, _start, _pts, old = self._seg
            self._seg = None
            new = [tuple(x) for x in it.wire.points]
            if new != old:
                self.undo.push(commands.SetWirePointsCommand(self, {it.wire.id: (old, new)}))
            return
        self._dragging = False
        moves, wp = {}, {}
        if self.mode == Mode.SELECT and self._move_start:
            for eid, old in self._move_start.items():
                it = self.element_items.get(eid)
                if it and (it.element.x, it.element.y) != old:
                    moves[eid] = (old, (it.element.x, it.element.y))
            if moves:
                for wid, old_pts in self._move_wire_pts.items():
                    w = next((x for x in self.sheet.wires if x.id == wid), None)
                    if w is not None and [tuple(x) for x in w.points] != old_pts:
                        wp[wid] = (old_pts, [tuple(x) for x in w.points])
            self._move_start = {}
            self._move_wire_pts = {}
        both = bool(moves) and bool(note_moves)
        if both:            # prvky i připomínky jedním tahem = jeden krok zpět
            self.undo.beginMacro("Posunout")
        if moves:
            self.undo.push(commands.MoveElementsCommand(self, moves, wp))
        self._push_note_moves(note_moves)
        if both:
            self.undo.endMacro()

    def _take_note_moves(self) -> list:
        """Posuny vybraných připomínek od začátku tahu (Qt je už přesunul a přichytil) jako (stará, nová)."""
        import copy

        from envocad.model.notes import note
        start, self._note_move_start = self._note_move_start, {}
        moves = []
        for nid, (ox, oy) in start.items():
            it, n = self.note_items.get(nid), note(self.project, nid)
            if it is None or n is None:
                continue
            nx, ny = it.pos().x(), -it.pos().y()
            if (nx, ny) != (ox, oy):
                new = copy.deepcopy(n)
                new.x, new.y = nx, ny
                moves.append((n, new))
        return moves

    def _push_note_moves(self, moves: list) -> None:
        """Posun připomínek se zapíše jedním příkazem (makrem)."""
        if not moves:
            return
        self.undo.beginMacro("Posunout připomínku" if len(moves) == 1 else "Posunout připomínky")
        for n, new in moves:
            self.undo.push(commands.ReplaceNoteCommand(self.project, n, new, "Posunout připomínku", self.rebuild_notes))
        self.undo.endMacro()

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
        elif ev.key() == Qt.Key_N:
            self.straighten_selected()
        elif ev.matches(QKeySequence.Copy):
            self.copy_selected()
        elif ev.matches(QKeySequence.Paste):
            self.paste()
        else:
            super().keyPressEvent(ev)

    # ---- akce ---------------------------------------------------------------
    CLIPBOARD: ClassVar[dict] = {}  # sdílená schránka všech scén (výřez listu + počet vložení pro posun)

    def straighten_selected(self) -> int:
        """Zruší ruční lomy vybraných vodičů – trasa se znovu spočítá automaticky (s odstupem od ostatních)."""
        ch = {it.wire.id: ([tuple(x) for x in it.wire.points], []) for it in self.selectedItems()
              if isinstance(it, WireItem) and it.wire.points}
        if ch:
            self.undo.push(commands.SetWirePointsCommand(self, ch, "Narovnat vodič"))
        return len(ch)

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
        self.undo.push(commands.PasteCommand(self, els, wires, f"Vložit makro {m.name}"))
        return len(els)

    def delete_selected(self) -> None:
        eids = [it.element.id for it in self.selectedItems() if isinstance(it, ElementItem)]
        wids = [it.wire.id for it in self.selectedItems() if isinstance(it, WireItem)]
        nids = [it.note.id for it in self.selectedItems() if isinstance(it, NoteItem)]
        # mazaný blok ROZVADĚČ: nabídnout smazání i jeho listu (jeden krok undo); bez dotazu list zůstane a kontrola
        # ho hlásí jako „list rozvaděče bez bloku“
        block_sheets = [s for s in (self.project.switchboard_sheet(eid) for eid in eids) if s is not None]
        ask = getattr(self, "ask_delete_block_sheets", None)
        drop_sheets = bool(block_sheets) and ask is not None and bool(ask(block_sheets))
        macro = (nids and (eids or wids)) or drop_sheets
        if macro:
            self.undo.beginMacro("Smazat")
        if eids or wids:
            self.undo.push(commands.RemoveItemsCommand(self, eids, wids))
        if drop_sheets:
            on_change = getattr(self, "sheet_presence_changed", None)
            for s in block_sheets:
                self.undo.push(commands.DeleteSheetCommand(self.project, s, on_change=on_change))
        if nids:
            from envocad.model.notes import note
            for nid in nids:
                n = note(self.project, nid)
                if n is not None:
                    self.undo.push(commands.ReplaceNoteCommand(self.project, n, None, f"Smazat připomínku č. {n.no}",
                                                               self.rebuild_notes))
        if macro:
            self.undo.endMacro()

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
        if old == value:
            return
        if key == "ref" and not is_wire:
            from envocad.model.project import rename_followups
            location = self._renames_location(target_id, old, value)
            texts = rename_followups(self.project, self.sheet.element(target_id), old, value)
            if location or texts:
                # jeden krok undo: ref, kód umístění (blok rozvaděče = umístění: registr, listy, override prvků)
                # a automaticky vygenerované texty se starým označením (název listu, „od T1“…)
                self.undo.beginMacro(f"Přejmenovat {old} na {value}")
                self.undo.push(commands.SetAttrCommand(self, target_id, is_wire, key, old, value))
                if location:
                    self.undo.push(commands.RenameStructureCommand(self.project, "+", old, value, self.invalidate_xrefs))
                if texts:
                    self.undo.push(commands.TextChangesCommand(self.project, texts, self._project_texts_changed))
                self.undo.endMacro()
                return
        self.undo.push(commands.SetAttrCommand(self, target_id, is_wire, key, old, value))

    def _project_texts_changed(self) -> None:
        """Navázané texty jiných prvků / názvy listů se změnily: popisky tohoto listu a obnova oken (`on_project_texts`)."""
        self.invalidate_xrefs()
        for it in self.element_items.values():
            it.update()
        cb = getattr(self, "on_project_texts", None)
        if cb is not None:
            cb()

    def _renames_location(self, element_id: str, old: str, new: str) -> bool:
        from envocad.model.designation import LOCATION_SYMBOLS
        if not old or not new or self.sheet.element(element_id).symbol_id not in LOCATION_SYMBOLS:
            return False
        p = self.project
        used = {s.loc for s in p.sheets} | {e.attrs.get("loc", "") for s in p.sheets for e in s.elements}
        known = lambda code: p.structure("+", code) is not None or code in used
        return known(old) and not known(new)

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

    def _draw_revision_marks(self, painter: QPainter) -> None:
        """Značky revize (červeně) u změněných míst; trasy vodičů jsou ty, které scéna právě kreslí."""
        from PySide6.QtGui import QColor

        from envocad.model.revision import revision_geometry
        from envocad.ui.items import path_points
        if not self.project.revisions:
            return
        routes = {wid: path_points(it.path()) for wid, it in self.wire_items.items()}
        try:
            geom = revision_geometry(self.project, self.sheet, self.library, routes)
        except Exception:  # noqa: BLE001 – značky nesmí shodit kreslení
            return
        draw_revision_marks(painter, geom, QColor(204, 0, 0))

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        """Rámeček s popisovým polem, můstky mezi skupinami svorek (čárkovaně) a informační blok rozvaděče."""
        from envocad.model.frame import MARGIN, MARGIN_LEFT, frame_geometry
        c = PRINT if not self.draw_grid else colors()
        draw_frame(painter, frame_geometry(self.project, self.sheet), c.ink)
        for geom in self.text_layout().mirrors.values():   # zrcadla kontaktů pod hostiteli (PDF jde přes scene.render)
            draw_geometry(painter, geom, c.ink)
        self._draw_revision_marks(painter)
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
