"""Jednopólové schéma: odvozená scéna (geometrie z `model/single_line.py`).

Kreslí kreslicí seznam modelu (`Prim`) – stejný zdroj jako DXF; obsah se mění úpravou blokového schématu a listů
rozvaděčů. Jediná úprava přímo ve scéně je ruční posun: tažením myší se posune prvek, pole, rozvaděč nebo
trafostanice i se vším pod sebou (`Element.sl_pos`, `SetSingleLineOffsetCommand`), pravým tlačítkem se vrátí
automatická poloha. Scéna slouží náhledu v záložce i exportu dokumentace do PDF.
"""
from __future__ import annotations

import itertools

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QUndoStack
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView, QMenu

from envocad.library.store import LibraryStore
from envocad.model.project import Project, Sheet
from envocad.model.single_line import TITLE, page_label, single_line_geometry
from envocad.ui import commands
from envocad.ui.canvas import SchematicView
from envocad.ui.items import snap
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
        self.project, self.library, self.undo = project, library, undo
        self.draw_grid = True
        self._drag = None          # (cíl, výchozí bod, výchozí posun, poslední posun)
        self._hover = None
        self.rebuild()

    def rebuild(self, offsets=None) -> None:
        """Přepočet z projektu (po změně blokového schématu nebo listů rozvaděčů); `offsets` = náhled tažení."""
        for it in list(self.items()):
            self.removeItem(it)
        self.geometry = single_line_geometry(self.project, self.library, offsets=offsets)
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
        t = self._drag[0] if self._drag else self._hover
        if t is not None and self.draw_grid:       # zvýraznění toho, co se táhne (jen v náhledu, ne v tisku)
            box = self._box_of(t)
            if box is not None:
                x0, y0, x1, y1 = box
                painter.setPen(QPen(QColor(40, 120, 220), 0.4, Qt.DashLine))
                painter.setBrush(QColor(40, 120, 220, 25))
                painter.drawRect(QRectF(sp(x0, y1), sp(x1, y0)))
                painter.setBrush(Qt.NoBrush)

    # ---- ruční posun ---------------------------------------------------------------------------------------
    def _box_of(self, target):
        """Obálka cíle v aktuální geometrii (po přestavění při tažení se posune s ním)."""
        same = [t for t in self.geometry.targets if t.key == target.key and t.kind == target.kind]
        return same[0].box if same else None

    def _element(self, key):
        try:
            return self.project.sheet(key[0]).element(key[1])
        except KeyError:
            return None

    def _offsets(self) -> dict:
        return {k: n.element.sl_pos for k, n in self.geometry.nodes.items() if n.element.sl_pos}

    @staticmethod
    def _page_point(ev) -> tuple[float, float]:
        p = ev.scenePos()
        return p.x(), -p.y()

    def mousePressEvent(self, ev) -> None:
        if ev.button() != Qt.LeftButton:
            super().mousePressEvent(ev)
            return
        x, y = self._page_point(ev)
        t = self.geometry.target_at(x, y)
        e = self._element(t.key) if t is not None else None
        if t is None or e is None:
            super().mousePressEvent(ev)
            return
        start = tuple(e.sl_pos) if e.sl_pos else (0.0, 0.0)
        self._drag = (t, (x, y), start, start)
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        x, y = self._page_point(ev)
        if self._drag is None:
            t = self.geometry.target_at(x, y)
            if (t and (t.key, t.kind)) != (self._hover and (self._hover.key, self._hover.kind)):
                self._hover = t
                self.update()
            super().mouseMoveEvent(ev)
            return
        t, (x0, y0), start, last = self._drag
        new = (start[0] + snap(x - x0), start[1] + snap(y - y0))
        if new != last:
            offs = self._offsets()
            offs[t.key] = new
            self._drag = (t, (x0, y0), start, new)
            self.rebuild(offs)
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:
        if self._drag is None or ev.button() != Qt.LeftButton:
            super().mouseReleaseEvent(ev)
            return
        t, _p0, start, new = self._drag
        self._drag = None
        if new != start:
            self.move(t.key, start, new)
        else:
            self.update()
        ev.accept()

    def move(self, key, old, new) -> None:
        """Zapíše posun prvku (undo); nulový posun = automatická poloha."""
        self._push({key: (tuple(old) if old and any(old) else None, tuple(new) if new and any(new) else None)})

    def _push(self, changes: dict, text: str = "Posun v jednopólovém schématu") -> None:
        cmd = commands.SetSingleLineOffsetCommand(self.project, changes, self.rebuild, text)
        if self.undo is not None:
            self.undo.push(cmd)
        else:
            cmd.redo()

    def reset_offsets(self, key=None) -> None:
        """Automatická poloha prvku `key`, bez něj celého schématu."""
        moved = self._offsets()
        if key is not None:
            moved = {k: v for k, v in moved.items() if k == key}
        if moved:
            self._push({k: (tuple(v), None) for k, v in moved.items()},
                       "Automatické rozmístění jednopólového schématu")

    def contextMenuEvent(self, ev) -> None:
        x, y = self._page_point(ev)
        t = self.geometry.target_at(x, y)
        e = self._element(t.key) if t is not None else None
        menu = QMenu()
        name = (t.label or "prvek") if t is not None else "prvek"
        one = menu.addAction(f"Vrátit automatickou polohu: {name}")
        one.setEnabled(bool(e is not None and e.sl_pos))
        every = menu.addAction("Vrátit automatické rozmístění celého schématu")
        every.setEnabled(bool(self._offsets()))
        chosen = menu.exec(ev.screenPos())
        if chosen is one and t is not None:
            self.reset_offsets(t.key)
        elif chosen is every:
            self.reset_offsets()


class SingleLineView(SchematicView):
    """Ovládání (zoom, posun prostředním tlačítkem) jako ostatní pohledy; levým tlačítkem se táhnou části."""

    def __init__(self, scene):
        super().__init__(scene)
        self.setDragMode(QGraphicsView.NoDrag)

    def zoom_fit(self) -> None:
        w, h = self.scene().paper_size
        self.fitInView(QRectF(0, -h, w, h), Qt.KeepAspectRatio)
