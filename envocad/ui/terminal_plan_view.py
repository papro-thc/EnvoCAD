"""Kreslený plán svorkovnice (jako v EPLAN): svorky v řadě, nad nimi vnější připojení, pod nimi vnitřní, můstky.

Scéna nemá položky – vše kreslí `drawForeground` z dat `model/terminal_plan.py`, takže PDF export je stejný.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPen, QUndoStack
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene

from envocad.library.store import LibraryStore
from envocad.model.frame import frame_geometry
from envocad.model.project import Project, Sheet
from envocad.model.terminal_plan import StripPlan, terminal_plan
from envocad.ui.canvas import SchematicView
from envocad.ui.render import draw_frame, draw_text, sp
from envocad.ui.theme import PRINT, colors

T_W, T_H = 8.0, 14.0     # svorka (š × v)
EXT_H, INT_H = 42.0, 42.0  # výška pásma textů nad/pod svorkami
STRIP_GAP = 12.0


class TerminalPlanScene(QGraphicsScene):
    def __init__(self, project: Project, sheet: Sheet, library: LibraryStore, undo: QUndoStack):
        super().__init__()
        self.project, self.sheet, self.library, self.undo = project, sheet, library, undo
        self.draw_grid = True
        self.mode = None
        self.paper_size = (sheet.width, sheet.height)
        w, h = self.paper_size
        self.setSceneRect(QRectF(-50, -h - 50, w + 100, h + 100))
        self._paper = QGraphicsRectItem(QRectF(0, -h, w, h))
        self._paper.setZValue(-1)
        self.addItem(self._paper)
        self.rebuild()

    def rebuild(self) -> None:
        self._paper.setPen(QPen(colors().paper, 0.5))
        self.plans: list[StripPlan] = terminal_plan(self.project, self.sheet)
        self.update()

    def retheme(self) -> None:
        self.rebuild()

    # ---- kreslení ---------------------------------------------------------------
    def _vtext(self, painter: QPainter, x: float, y: float, text: str, h: float = 2.0, up: bool = True) -> None:
        """Svislý text čtený zdola nahoru; up = roste od (x, y) nahoru, jinak končí v (x, y) a roste dolů."""
        painter.save()
        painter.translate(sp(x, y))
        painter.rotate(-90)
        draw_text(painter, 0, 0, text, h, "left" if up else "right")
        painter.restore()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        c = PRINT if not self.draw_grid else colors()
        g = frame_geometry(self.project, self.sheet, view="plán svorkovnice")
        draw_frame(painter, g, c.ink)
        x0, y0, x1, y1 = g.inner
        painter.setRenderHint(QPainter.Antialiasing)
        y = y1 - 8.0
        for plan in self.plans:
            if not plan.rows:
                continue
            per_row = max(1, int((x1 - x0 - 10) // T_W))
            chunks = [plan.rows[i:i + per_row] for i in range(0, len(plan.rows), per_row)]
            painter.setPen(QPen(c.ink, 0.2))
            draw_text(painter, x0 + 4, y, f"Svorkovnice {plan.strip}", 3.5, "left")
            y -= 3.0
            for chunk in chunks:
                if y - (EXT_H + T_H + INT_H) < y0 + 40:  # dole už je popisové pole – zbytek se nevejde
                    draw_text(painter, x0 + 4, y - 4, "… pokračování se nevešlo na list", 2.5, "left")
                    return
                top = y - EXT_H  # horní hrana svorek
                xs: dict[str, float] = {}
                for i, r in enumerate(chunk):
                    x = x0 + 6 + i * T_W
                    xs[r.number] = x + T_W / 2
                    painter.setPen(QPen(c.ink, 0.3))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRect(QRectF(x, -top, T_W, T_H))
                    painter.setPen(QPen(c.ink, 0.2))
                    draw_text(painter, x + T_W / 2, top - 4.0, r.number, 2.2, "center")
                    draw_text(painter, x + T_W / 2, top - T_H + 1.2, r.conductor, 1.5, "center")  # žíla ve spodní části
                    # vnější připojení nahoru, vnitřní dolů (svisle)
                    painter.setPen(QPen(c.wire, 0.35))
                    if r.external or r.ext_cable:
                        painter.drawLine(sp(x + T_W / 2, top), sp(x + T_W / 2, top + 6))
                        painter.setPen(QPen(c.ink, 0.2))
                        self._vtext(painter, x + T_W / 2 + 0.8, top + 7, r.external, 2.0)
                        if r.ext_cable:
                            self._vtext(painter, x + T_W / 2 - 2.0, top + 7, r.ext_cable, 1.6)
                    if r.internal or r.int_cable:
                        painter.setPen(QPen(c.wire, 0.35))
                        painter.drawLine(sp(x + T_W / 2, top - T_H), sp(x + T_W / 2, top - T_H - 6))
                        painter.setPen(QPen(c.ink, 0.2))
                        self._vtext(painter, x + T_W / 2 + 0.8, top - T_H - 7, r.internal, 2.0, up=False)
                        if r.int_cable:
                            self._vtext(painter, x + T_W / 2 - 2.0, top - T_H - 7, r.int_cable, 1.6, up=False)
                # můstky: čáry pod čísly uvnitř svorek, každá skupina v jiné výšce
                for gi, grp in enumerate(plan.bridges):
                    pts = sorted(xs[n] for n in grp if n in xs)
                    if len(pts) < 2:
                        continue
                    by = top - 6.0 - 0.9 * (gi % 6)  # mezi číslem a žílou
                    painter.setPen(QPen(c.ink, 0.5))
                    painter.drawLine(sp(pts[0], by), sp(pts[-1], by))
                    painter.setBrush(c.ink)
                    for px in pts:
                        painter.drawEllipse(sp(px, by), 0.6, 0.6)
                    painter.setBrush(Qt.NoBrush)
                y = top - T_H - INT_H - STRIP_GAP

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        c = PRINT if not self.draw_grid else colors()
        painter.fillRect(rect, c.background)


class TerminalPlanView(SchematicView):
    pass
