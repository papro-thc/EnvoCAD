"""Kreslený plán svorkovnice (jako v EPLAN): svorky v řadě, nad nimi vnější připojení, pod nimi vnitřní, můstky.

Scéna nemá položky – vše kreslí `drawForeground` z dat `model/terminal_plan.py`, takže PDF export je stejný.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen, QUndoStack
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene

from envocad.library.store import LibraryStore
from envocad.model.frame import doc_page, frame_geometry, page_label
from envocad.model.multipole import MP_PAGE_GAP, page_paper_label, page_size
from envocad.model.project import Project, Sheet
from envocad.model.terminal_plan import (  # noqa: F401 – rozměry zůstávají dostupné i odsud (testy, nástroje)
    EXT_H,
    INT_H,
    STRIP_GAP,
    T_H,
    T_W,
    TITLE_H,
    PlanChunk,
    StripPlan,
    layout_plan_pages,
    sheet_plan_pages,
    terminal_plan,
)
from envocad.settings import company, switchboard_paper
from envocad.ui.canvas import SchematicView
from envocad.ui.render import draw_frame, draw_text, sp
from envocad.ui.theme import PRINT, colors


class TerminalPlanScene(QGraphicsScene):
    """Plán svorkovnic listu rozvaděče. Svorkovnice, které se nevejdou na jednu stranu, pokračují na dalších
    stranách pod sebou (`pages`, stejně jako vícepól) – PDF listu i dokumentace je vykreslí každou zvlášť."""

    PAGE_GAP = MP_PAGE_GAP

    def __init__(self, project: Project, sheet: Sheet, library: LibraryStore, undo: QUndoStack):
        super().__init__()
        self.project, self.sheet, self.library, self.undo = project, sheet, library, undo
        self.draw_grid = True
        self.mode = None
        std = switchboard_paper()               # firemní standard (model nastavení nečte)
        self.paper_size = page_size(sheet, standard_paper=std)   # strana jako vícepól listu (výchozí A4 na šířku)
        self.paper_label = page_paper_label(sheet, standard_paper=std)
        w, h = self.paper_size
        self._paper = QGraphicsRectItem(QRectF(0, -h, w, h))
        self._paper.setZValue(-1)
        self.addItem(self._paper)
        self.pages: list[QRectF] = []
        self.rebuild()

    @property
    def page_pitch(self) -> float:
        return self.paper_size[1] + self.PAGE_GAP

    def rebuild(self) -> None:
        self._paper.setPen(QPen(colors().paper, 0.5))
        from envocad.model.project import clean_view
        self.plans: list[StripPlan] = terminal_plan(*clean_view(self.project, self.sheet))
        std = switchboard_paper()
        self.paper_size, self.page_chunks = sheet_plan_pages(self.project, self.sheet, self.plans, standard_paper=std)
        self.paper_label = page_paper_label(self.sheet, standard_paper=std)
        w, h = self.paper_size
        n = len(self.page_chunks)
        pitch = self.page_pitch
        self.pages = [QRectF(0, k * pitch - h, w, h) for k in range(n)]
        total_h = n * pitch - self.PAGE_GAP
        self._paper.setRect(QRectF(0, -h, w, total_h))
        self.setSceneRect(QRectF(-50, -h - 50, w + 100, total_h + 100))
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
        w, h = self.paper_size
        n = max(1, len(self.page_chunks))
        firm = company()
        painter.setRenderHint(QPainter.Antialiasing)
        for k in range(n):
            painter.save()
            painter.translate(0, k * self.page_pitch)
            draw_frame(painter, frame_geometry(self.project, self.sheet, w, h, "plán svorkovnice",
                                               page_label(self.project, self.sheet, k, n), self.paper_label,
                                               firm, doc_page(self.project, self.sheet.id, "terminals", k)), c.ink)
            for chunk in self.page_chunks[k] if k < len(self.page_chunks) else []:
                self._draw_chunk(painter, chunk, c)
            painter.restore()
            if k:  # dělicí čára mezi stranami i bez rámečku
                painter.setPen(QPen(c.grid, 0, Qt.DashLine))
                y = k * self.page_pitch - h - self.PAGE_GAP / 2   # scénové y uprostřed mezery nad stranou k
                painter.drawLine(QPointF(0, y), QPointF(w, y))

    def _draw_chunk(self, painter: QPainter, chunk: PlanChunk, c) -> None:
        painter.setPen(QPen(c.ink, 0.2))
        tx, ty = chunk.title_pos
        draw_text(painter, tx, ty, chunk.title, TITLE_H, "left")
        top = chunk.top  # horní hrana svorek
        xs: dict[str, float] = {}
        for i, r in enumerate(chunk.rows):
            x = chunk.x + i * T_W
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
        for gi, grp in enumerate(chunk.bridges):
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

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        c = PRINT if not self.draw_grid else colors()
        painter.fillRect(rect, c.background)


class TerminalPlanView(SchematicView):
    def zoom_fit(self) -> None:
        sc = self.scene()
        r = QRectF(sc.pages[0]) if sc.pages else QRectF(0, -sc.paper_size[1], *sc.paper_size)
        for p in sc.pages[1:]:
            r = r.united(p)
        self.fitInView(r, Qt.KeepAspectRatio)
