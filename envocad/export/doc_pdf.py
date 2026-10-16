"""Celá dokumentace do jednoho PDF: titulní list, obsah, listy JPS, schéma + plán svorkovnice každého rozvaděče,
tabulkové výkazy a změnový list. Všechny strany A3 na šířku, stránkované tabulky."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter, QPen, QUndoStack

from envocad.export import reports
from envocad.export.pdf_export import _set_notes_visible
from envocad.model.frame import frame_geometry
from envocad.model.project import Project, Sheet
from envocad.ui import theme
from envocad.ui.render import draw_frame, draw_text, sp

PAGE_W, PAGE_H = 420.0, 297.0
ROW_H = 5.0


def _page_painter_setup(painter: QPainter, writer: QPdfWriter) -> None:
    """Souřadnice stránky v mm (model, Y nahoru → scénové Y dolů řeší sp())."""
    painter.resetTransform()
    sx = writer.width() / PAGE_W
    sy = writer.height() / PAGE_H
    painter.scale(sx, sy)
    painter.translate(0, PAGE_H)  # model Y nahoru: y_scene = -y_model → posun o výšku


def _pseudo_sheet(name: str, project: Project) -> Sheet:
    s = Sheet(name=name, width=PAGE_W, height=PAGE_H)
    return s


def _draw_frame_page(painter, project, sheet_for_frame, view="", page=""):
    g = frame_geometry(project, sheet_for_frame, PAGE_W, PAGE_H, view, page)
    draw_frame(painter, g, theme.PRINT.ink)
    return g


class DocBuilder:
    """Sestaví seznam stran (pro obsah) a pak je vykreslí."""

    def __init__(self, project: Project, library):
        self.project, self.library = project, library
        self.pages: list[tuple[str, str, object]] = []  # (druh, název, data)
        self._page = ""  # „3/16“ aktuální strany pro popisové pole
        self._pdf_page = 0  # index aktuální fyzické strany PDF (od 0), zvyšuje se u každého newPage()
        self._total = 0  # počet fyzických stran (vícepól a pokračování tabulek mají víc stran)
        self.page_starts: list[int] = []  # první fyzická strana (od 1) každé položky self.pages – pro obsah
        self.note_pages: list[tuple[int, object, list]] = []  # (fyzická strana od 0, PageMap, připomínky) – JPS
        self._cap = 0  # řádků tabulky na stranu (spočítá se jednou)
        self._scenes: dict[tuple[str, str], tuple[object, QUndoStack]] = {}

    def plan(self) -> None:
        p = self.project
        self.pages = [("title", "Titulní list", None), ("toc", "Obsah", None)]
        for s in p.sheets:
            if not s.is_switchboard:
                self.pages.append(("sheet", s.name, (s, "schematic")))
        for s in p.sheets:
            if s.is_switchboard:
                self.pages.append(("sheet", f"{s.name} – schéma", (s, "multipole")))
                self.pages.append(("sheet", f"{s.name} – plán svorkovnice", (s, "terminals")))
        for name, fn in reports.ALL_REPORTS:
            head, rows = fn(p, self.library, None)
            if rows:
                self.pages.append(("table", name, (head, rows)))
        self.pages.append(("changes", "Změnový list", None))

    # ---- strany ----------------------------------------------------------------
    def _title(self, painter, writer):
        p = self.project
        m = p.meta
        s = _pseudo_sheet("Titulní list", p)
        _draw_frame_page(painter, p, s, page=self._page)
        painter.setPen(QPen(theme.PRINT.ink, 0.2))
        draw_text(painter, PAGE_W / 2, 200, "ENVO s.r.o.", 8, "center")
        draw_text(painter, PAGE_W / 2, 180, "Elektrotechnická dokumentace", 6, "center")
        draw_text(painter, PAGE_W / 2, 160, p.name, 10, "center")
        y = 130
        for label, val in (("Investor", m.get("investor", "")), ("Místo", m.get("place", "")),
                           ("Číslo zakázky", m.get("order", "")), ("Zpracoval", m.get("author", "")),
                           ("Datum", m.get("date", "")), ("Revize", m.get("revision", ""))):
            if val:
                draw_text(painter, PAGE_W / 2 - 5, y, label + ":", 4, "right")
                draw_text(painter, PAGE_W / 2 + 5, y, val, 4, "left")
                y -= 8

    def _toc(self, painter, writer):
        p = self.project
        s = _pseudo_sheet("Obsah", p)
        g = _draw_frame_page(painter, p, s, page=self._page)
        x0, y0, _x1, y1 = g.inner
        painter.setPen(QPen(theme.PRINT.ink, 0.2))
        draw_text(painter, x0 + 10, y1 - 15, "Obsah dokumentace", 5, "left")
        y = y1 - 28
        starts = self.page_starts or list(range(1, len(self.pages) + 1))
        for i, (_kind, name, _d) in zip(starts, self.pages):
            draw_text(painter, x0 + 10, y, f"{i:>3}", 3, "left")
            draw_text(painter, x0 + 25, y, name, 3, "left")
            y -= 6
            if y < y0 + 45:
                break

    def _scene(self, sheet: Sheet, kind: str):
        """Exportní scéna listu (sdílená mezi počítáním stran a vykreslením). Připomínky nekreslí – v PDF jsou jen
        jako anotace (`pdf_annots`)."""
        key = (sheet.id, kind)
        if key not in self._scenes:
            from envocad.ui.canvas import SchematicScene
            from envocad.ui.multipole_view import MultipoleScene
            from envocad.ui.terminal_plan_view import TerminalPlanScene
            undo = QUndoStack()
            cls = {"schematic": SchematicScene, "multipole": MultipoleScene, "terminals": TerminalPlanScene}[kind]
            scene = cls(self.project, sheet, self.library, undo)
            scene.draw_grid = False
            _set_notes_visible(scene, False)
            self._scenes[key] = (scene, undo)
        return self._scenes[key][0]

    def _sheet_pages(self, sheet: Sheet, kind: str) -> int:
        if kind != "multipole":
            return 1
        return max(1, len(getattr(self._scene(sheet, kind), "pages", None) or []))

    def _new_page(self, painter, writer) -> None:
        writer.newPage()
        self._pdf_page += 1
        _page_painter_setup(painter, writer)

    def _sheet(self, painter, writer, sheet: Sheet, kind: str):
        scene = self._scene(sheet, kind)
        pw, ph = getattr(scene, "paper_size", (sheet.width, sheet.height))
        painter.resetTransform()
        # vejít do strany A3; vícepól může mít víc stran (každá na vlastní stranu PDF)
        scale = min(writer.width() / pw, writer.height() / ph)
        target = QRectF(0, 0, pw * scale, ph * scale)
        pages = getattr(scene, "pages", None) or [QRectF(0, -ph, pw, ph)]
        for i, src in enumerate(pages):
            if i:
                self._new_page(painter, writer)
                painter.resetTransform()
            scene.render(painter, target, src, Qt.KeepAspectRatio)
        if kind == "schematic":
            from envocad.export.pdf_annots import PageMap
            from envocad.model.notes import notes_on_sheet
            notes = notes_on_sheet(self.project, sheet.id, ("open",))
            if notes:   # list u levého horního rohu strany (target začíná v 0, 0 a má poměr listu)
                r = writer.pageLayout().fullRect(QPageLayout.Millimeter)
                pm = PageMap.fit(pw, ph, r.width(), r.height(), center=False)
                self.note_pages.append((self._pdf_page, pm, notes))

    def _table_capacity(self) -> int:
        """Počet řádků tabulky na jednu stranu (stejná geometrie jako `_table`)."""
        if self._cap:
            return self._cap
        g = frame_geometry(self.project, _pseudo_sheet("", self.project), PAGE_W, PAGE_H, "", "")
        _x0, y0, _x1, y1 = g.inner
        y = y1 - 18 - ROW_H
        n = 0
        while y - ROW_H > y0 + 40:
            y -= ROW_H
            n += 1
        self._cap = max(1, n)
        return self._cap

    def _count_pages(self) -> None:
        """Fyzické strany předem: popisové pole ukazuje „n/N“ a obsah skutečná čísla stran."""
        cap = self._table_capacity()
        self.page_starts = []
        total = 0
        for kind, _name, data in self.pages:
            self.page_starts.append(total + 1)
            if kind == "sheet":
                total += self._sheet_pages(*data)
            elif kind == "table":
                total += max(1, -(-len(data[1]) // cap))
            else:
                total += 1
        self._total = total

    def _table(self, painter, writer, name: str, head: list[str], rows: list[list], start: int) -> int:
        """Nakreslí tabulku od řádku `start`; vrátí index prvního nevykresleného řádku (len(rows) = hotovo)."""
        p = self.project
        s = _pseudo_sheet(name, p)
        g = _draw_frame_page(painter, p, s, page=self._page)
        x0, _y0, x1, y1 = g.inner
        painter.setPen(QPen(theme.PRINT.ink, 0.2))
        draw_text(painter, x0 + 5, y1 - 10, name, 4.5, "left")
        n = len(head)
        widths = [max(12.0, min(70.0, 2.0 + 1.6 * max([len(str(h))] + [len(str(r[i])) for r in rows[:200]])))
                  for i, h in enumerate(head)]
        total = sum(widths)
        avail = x1 - x0 - 10
        if total > avail:
            widths = [w * avail / total for w in widths]
        y = y1 - 18
        x = x0 + 5
        painter.setPen(QPen(theme.PRINT.ink, 0.3))
        for i, h in enumerate(head):
            draw_text(painter, x + 1, y - 3.5, str(h), 2.2, "left")
            x += widths[i]
        painter.drawLine(sp(x0 + 5, y - ROW_H), sp(x0 + 5 + sum(widths), y - ROW_H))
        y -= ROW_H
        painter.setPen(QPen(theme.PRINT.ink, 0.2))
        i = start
        stop = min(len(rows), start + self._table_capacity())
        while i < stop:
            x = x0 + 5
            for c, v in enumerate(rows[i][:n]):
                txt = str(v)
                maxc = int(widths[c] / 1.5)
                if len(txt) > maxc:
                    txt = txt[: max(1, maxc - 1)] + "…"
                draw_text(painter, x + 1, y - 3.5, txt, 2.2, "left")
                x += widths[c]
            y -= ROW_H
            i += 1
        return i

    def _changes(self, painter, writer):
        p = self.project
        s = _pseudo_sheet("Změnový list", p)
        g = _draw_frame_page(painter, p, s, page=self._page)
        x0, _y0, _x1, y1 = g.inner
        painter.setPen(QPen(theme.PRINT.ink, 0.2))
        draw_text(painter, x0 + 10, y1 - 15, "Změnový list", 5, "left")
        y = y1 - 28
        draw_text(painter, x0 + 10, y, "Revize", 3, "left")
        draw_text(painter, x0 + 35, y, "Datum", 3, "left")
        draw_text(painter, x0 + 65, y, "Popis změny", 3, "left")
        draw_text(painter, x0 + 250, y, "Zpracoval", 3, "left")
        y -= 7
        for line in (p.meta.get("changes", "") or "").splitlines():
            parts = [x.strip() for x in line.split("|")]
            parts += [""] * (4 - len(parts))
            for x, txt in zip((10, 35, 65, 250), parts):
                draw_text(painter, x0 + x, y, txt, 3, "left")
            y -= 6
        if not p.meta.get("changes"):
            draw_text(painter, x0 + 10, y, f"{p.meta.get('revision') or '0'}  {p.meta.get('date', '')}  první vydání", 3, "left")

    # ---- export --------------------------------------------------------------------
    def export(self, path: Path | str, notes: bool = False) -> int:
        """Vykreslí dokumentaci; `notes=True` doplní otevřené připomínky listů JPS jako anotace PDF.
        Vrací počet fyzických stran."""
        self.plan()
        self._pdf_page = 0
        self.note_pages = []
        writer = QPdfWriter(str(path))
        writer.setPageSize(QPageSize(QSizeF(PAGE_W, PAGE_H), QPageSize.Millimeter))
        # rozměr strany už orientaci nese (420×297); Landscape by ji otočil podruhé → strana na výšku 297×420
        # a nerovnoměrně roztažený obsah (stejná oprava jako v pdf_export)
        writer.setPageLayout(QPageLayout(QPageSize(QSizeF(PAGE_W, PAGE_H), QPageSize.Millimeter),
                                         QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
        writer.setResolution(300)
        writer.setTitle(f"{self.project.name} – dokumentace")
        writer.setCreator("EnvoCAD")
        prev_dark = theme.is_dark()
        theme._current = theme.PRINT
        painter = QPainter(writer)
        painter.setRenderHint(QPainter.Antialiasing)
        try:
            self._count_pages()
            for idx, (kind, name, data) in enumerate(self.pages):
                if idx:
                    self._new_page(painter, writer)
                else:
                    _page_painter_setup(painter, writer)
                self._page = f"{self._pdf_page + 1}/{self._total}"
                if kind == "title":
                    self._title(painter, writer)
                elif kind == "toc":
                    self._toc(painter, writer)
                elif kind == "sheet":
                    self._sheet(painter, writer, *data)
                elif kind == "table":
                    head, rows = data
                    i = self._table(painter, writer, name, head, rows, 0)
                    while i < len(rows):
                        self._new_page(painter, writer)
                        self._page = f"{self._pdf_page + 1}/{self._total}"
                        i = self._table(painter, writer, name + " (pokračování)", head, rows, i)
                elif kind == "changes":
                    self._changes(painter, writer)
        finally:
            painter.end()
            theme._current = theme.DARK if prev_dark else theme.LIGHT
            for scene, _undo in self._scenes.values():
                scene.deleteLater()
            self._scenes.clear()
        count = self._pdf_page + 1
        if notes and self.note_pages:
            from envocad.export.pdf_annots import add_note_annotations
            add_note_annotations(path, self.note_pages, self.project.name)
        return count


def export_documentation_pdf(project: Project, library, path: Path | str, notes: bool = False) -> int:
    """Vrátí počet stran. `notes=True` = otevřené připomínky jako anotace PDF."""
    return DocBuilder(project, library).export(path, notes=notes)
