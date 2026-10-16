"""Připomínky (redlining) v editoru: `NoteItem` nad `Project.notes`. Samotný item model nemění – změny jdou
přes `ReplaceNoteCommand` (posun při puštění tlačítka řeší scéna, stav a mazání kontextové menu přes scénu)."""
from __future__ import annotations

import copy
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker
from PySide6.QtWidgets import QGraphicsItem, QMenu

from envocad.model.notes import STATUS_COLORS, STATUS_LABELS, note_shape, note_target_label, reopen, resolve
from envocad.model.project import Note
from envocad.ui.render import draw_note_shape, sp
from envocad.ui.theme import colors


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="minutes")[:16]   # místní čas, bez pásma


def resolved_copy(n: Note, by: str, when: str | None = None) -> Note:
    """Kopie připomínky označená jako vyřešená (kdo, kdy)."""
    return resolve(copy.deepcopy(n), by, when or now_iso())


def reopened_copy(n: Note) -> Note:
    return reopen(copy.deepcopy(n))


def tooltip_text(project, n: Note) -> str:
    """Text bubliny: číslo a stav, text, autor a datum, cíl, odpověď."""
    lines = [f"Připomínka č. {n.no} ({STATUS_LABELS.get(n.status, n.status)})"]
    if n.text.strip():
        lines.append(n.text.strip())
    meta = ", ".join(x for x in (n.author, n.created.replace("T", " ")) if x)
    if meta:
        lines.append(meta)
    target = note_target_label(project, n)
    if target:
        lines.append(f"Prvek: {target}")
    if n.reply:
        lines.append(f"Vyřízení: {n.reply}")
    if n.status == "resolved" and n.resolved:
        lines.append(f"Vyřešil: {n.resolved_by}, {n.resolved.replace('T', ' ')}")
    return "\n".join(lines)


class NoteItem(QGraphicsItem):
    """Připomínka na listu. Pozice itemu = kotva (bod / levý dolní roh obdélníku); kreslí se v absolutních
    souřadnicích listu, takže posun itemu je přímo posun připomínky."""
    Type = QGraphicsItem.UserType + 3

    def __init__(self, note: Note):
        super().__init__()
        self.note = note
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(30)
        self.sync_from_model()

    def type(self) -> int:
        return self.Type

    def sync_from_model(self) -> None:
        self.prepareGeometryChange()
        self._shape = note_shape(self.note)
        self.setPos(sp(self.note.x, self.note.y))
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            from envocad.ui.items import snap
            return QPointF(snap(value.x()), snap(value.y()))
        return super().itemChange(change, value)

    # ---- geometrie -------------------------------------------------------------
    def _origin(self) -> QPointF:
        return sp(self.note.x, self.note.y)

    def boundingRect(self) -> QRectF:
        x0, y0, x1, y1 = self._shape.bbox
        r = QRectF(x0, -y1, x1 - x0, y1 - y0).adjusted(-1, -1, 1, 1)
        return r.translated(-self._origin())

    def shape(self) -> QPainterPath:
        """Zásahová oblast: praporek, křížek s odkazovou čárou, u obdélníku jen obrys (prvky uvnitř zůstanou klikací)."""
        s = self._shape
        path = QPainterPath()
        for x1, y1, x2, y2 in s.lines:
            path.moveTo(sp(x1, y1))
            path.lineTo(sp(x2, y2))
        stroker = QPainterPathStroker()
        stroker.setWidth(2.0)
        out = stroker.createStroke(path)
        for i, pts in enumerate(s.polylines):
            poly = QPainterPath()
            poly.addPolygon([sp(x, y) for x, y in pts])
            poly.closeSubpath()
            if self.note.is_rect and i == 0:
                out.addPath(stroker.createStroke(poly))
            else:
                out.addPath(poly)
        c = 1.5
        out.addRect(QRectF(self._origin().x() - c, self._origin().y() - c, 2 * c, 2 * c))
        return out.translated(-self._origin())

    # ---- kreslení ----------------------------------------------------------------
    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        color = colors().selection if self.isSelected() else QColor(*STATUS_COLORS.get(self.note.status, (190, 0, 190)))
        painter.translate(-self._origin())      # kresba je v absolutních souřadnicích listu
        draw_note_shape(painter, self._shape, color, dash_first=self.note.is_rect)

    # ---- kontextové menu (bublinu nastavuje scéna – zná projekt) ---------------------------
    def build_menu(self) -> QMenu:
        sc = self.scene()
        nid = self.note.id
        m = QMenu()
        m.addAction("Upravit…").triggered.connect(lambda: sc.edit_note_later(nid))
        if self.note.status == "open":
            m.addAction("Vyřešit").triggered.connect(lambda: sc.set_note_status(nid, "resolved"))
        else:
            m.addAction("Znovu otevřít").triggered.connect(lambda: sc.set_note_status(nid, "open"))
        m.addAction("Smazat").triggered.connect(lambda: sc.delete_note(nid))
        return m

    def contextMenuEvent(self, ev) -> None:
        if self.scene() is None:
            return
        if not self.isSelected():
            self.scene().clearSelection()
            self.setSelected(True)
        self.build_menu().exec(ev.screenPos())
        ev.accept()
