"""Jednopólové schéma: odvozená scéna jen pro čtení (geometrie z `model/single_line.py`).

Kreslí kreslicí seznam modelu (`Prim`) – stejný zdroj jako DXF; obsah se mění jen úpravou blokového schématu a
listů rozvaděčů. Scéna slouží náhledu v záložce i exportu dokumentace do PDF.
"""
from __future__ import annotations

import itertools

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPen, QUndoStack
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene

from envocad.library.store import LibraryStore
from envocad.model.project import Project, Sheet
from envocad.model.single_line import TITLE, page_label, single_line_geometry
from envocad.ui.canvas import SchematicView
from envocad.ui.render import LINE_WIDTH, draw_frame, draw_text, paint_symbol, sp
from envocad.ui.theme import PRINT, colors

WEIGHT = {"thin": 0.18, "wire": LINE_WIDTH, "bus": 0.7, "fan": 0.5}


def single_line_sheet(project: Project, paper: str = "", size: tuple[float, float] | None = None) -> Sheet:
    """Pomocný (neuložený) list pro popisové pole jednopólového schématu."""
    s = Sheet(name=TITLE)
    if paper:
        s.paper = paper
    if size:
        s.width, s.height = size
    return s


class PrimItem(QGraphicsItem):
    """Celý kreslicí seznam jednou položkou (scéna je jen pro čtení)."""

    def __init__(self, prims, rect: QRectF):
        super().__init__()
        self.prims, self._rect = prims, rect

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        ink = PRINT.ink if not getattr(self.scene(), "draw_grid", False) else colors().ink
        for p in self.prims:
            if p.kind in ("line", "poly"):
                pen = QPen(ink, WEIGHT.get(p.weight, LINE_WIDTH), Qt.DashLine if p.style == "dashed" else Qt.SolidLine)
                if p.style == "dashed":
                    pen.setDashPattern([6, 4])
                painter.setPen(pen)
                pts = [sp(x, y) for x, y in p.pts]
                for a, b in itertools.pairwise(pts):
                    painter.drawLine(a, b)
            elif p.kind == "text":
                painter.setPen(QPen(ink, 0.2))
                (x, y), = p.pts
                draw_text(painter, x, y, p.text, p.h, p.align)
            elif p.kind == "dot":
                painter.setPen(Qt.NoPen)
                painter.setBrush(ink)
                painter.drawEllipse(sp(*p.pts[0]), p.r, p.r)
                painter.setBrush(Qt.NoBrush)
            elif p.kind == "symbol" and p.symbol is not None:
                painter.save()
                painter.translate(sp(*p.pts[0]))
                painter.rotate(-p.rot)
                paint_symbol(painter, p.symbol, QPen(ink, LINE_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.restore()


class SingleLineScene(QGraphicsScene):
    """Scéna jednopólového schématu (rozhraní jako vícepól: `paper_size`, `pages`). `sheet` se nepoužívá – schéma
    je odvozené z celého projektu; parametr drží jednotný konstruktor exportních scén."""

    def __init__(self, project: Project, sheet: Sheet | None, library: LibraryStore, undo: QUndoStack | None = None):
        super().__init__()
        self.project, self.library = project, library
        self.draw_grid = True
        self.rebuild()

    def rebuild(self) -> None:
        """Přepočet z projektu (po změně blokového schématu nebo listů rozvaděčů)."""
        for it in list(self.items()):
            self.removeItem(it)
        self.geometry = single_line_geometry(self.project, self.library)
        self.paper_size = self.geometry.page_size
        self.paper_label = self.geometry.paper
        self.sheet = single_line_sheet(self.project, self.paper_label, self.paper_size)
        w, h = self.paper_size
        self.pages = [QRectF(0, -h, w, h)]
        self.setSceneRect(QRectF(-20, -h - 20, w + 40, h + 40))
        self.addItem(PrimItem(self.geometry.prims, QRectF(0, -h, w, h)))

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        c = PRINT if not self.draw_grid else colors()
        painter.fillRect(rect, c.background)
        if self.draw_grid:      # obrys strany v náhledu
            w, h = self.paper_size
            painter.setPen(QPen(c.grid, 0))
            painter.drawRect(QRectF(0, -h, w, h))

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        from envocad.model.frame import frame_geometry
        c = PRINT if not self.draw_grid else colors()
        w, h = self.paper_size
        draw_frame(painter, frame_geometry(self.project, self.sheet, w, h, "", page_label(self.project),
                                           self.paper_label), c.ink)


class SingleLineView(SchematicView):
    """Ovládání (zoom, posun) jako ostatní pohledy; obsah jen pro čtení."""

    def zoom_fit(self) -> None:
        w, h = self.scene().paper_size
        self.fitInView(QRectF(0, -h, w, h), Qt.KeepAspectRatio)
