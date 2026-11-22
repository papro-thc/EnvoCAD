"""Celá dokumentace do jednoho PDF: titulní list, obsah, listy JPS, schéma + plán svorkovnice každého rozvaděče,
tabulkové výkazy a změnový list. Strany A3 na šířku; schéma (vícepól) a plán svorkovnice listu rozvaděče mají
formát svých stran (`multipole.page_size`, výchozí A4 na šířku) – PDF má smíšené formáty stran (`QPdfWriter.
setPageLayout` před každou novou stranou). Listy JPS se zmenší na A3 (výchozí), nebo mají stranu ve skutečném
formátu listu (A2, A1…) – volba `jps_page` při exportu, výchozí z firemního standardu `doc_jps_page`.

Obsah, výkazy i změnový list jsou tabulky (`_TableLayout`): šířky sloupců podle obsahu a šířky strany, dlouhý
text se v buňce zalomí, tabulka pokračuje na dalších stranách. Počet stran se spočítá předem (obsah ukazuje
skutečná čísla stran, popisové pole „n/N“). Bez rámečku má každá strana malé „strana n/N“ v pravém dolním rohu.
PDF má záložky (osnovu): jedna na každý řádek obsahu, doplněné po vykreslení (`pdf_outline`).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter, QPen, QUndoStack

from envocad.export import reports
from envocad.export.pdf_export import set_scene_notes_visible
from envocad.model import multipole as mp
from envocad.model.frame import DOC_PAGES_KEY, TB_H, doc_page_key, frame_geometry, sheet_number
from envocad.model.project import Project, Sheet
from envocad.settings import company, frame_enabled, switchboard_paper
from envocad.ui import theme
from envocad.ui.render import draw_frame, draw_text, sp, text_width, wrap_text

PAGE_W, PAGE_H = 420.0, 297.0
ROW_H = 5.0               # nejmenší výška řádku tabulky
FONT_H = 2.2              # písmo tabulky (mm)
LINE_PITCH = 3.2          # řádkování zalomeného textu v buňce
CELL_PAD = 1.0            # vnitřní okraj buňky vlevo/vpravo
TABLE_TOP = 18.0          # začátek tabulky pod horním okrajem kreslicí plochy (nad ní název)
MIN_COL = 8.0             # nejužší sloupec
MAX_WORD = 30.0           # delší slovo se smí lámat po znacích (nesnižuje min. šířku sloupce víc)
FOOTER_H = 2.5            # „strana n/N“ bez rámečku
# listy JPS v dokumentaci: zmenšit na stranu A3 (dosavadní chování) / strana ve skutečném formátu listu
JPS_PAGE_A3, JPS_PAGE_SHEET = "A3", "list"
JPS_PAGE_LABELS = {JPS_PAGE_A3: "Zmenšit na A3", JPS_PAGE_SHEET: "Skutečný formát listu"}


def standard_jps_page() -> str:
    """Výchozí volba listů JPS v PDF dokumentace z firemního standardu (`standard.doc_jps_page`, výchozí „A3“)."""
    from envocad.settings import load_settings
    try:
        v = str(load_settings()["standard"].get("doc_jps_page") or JPS_PAGE_A3)
    except (OSError, ValueError, KeyError, TypeError):
        v = JPS_PAGE_A3
    return v if v in JPS_PAGE_LABELS else JPS_PAGE_A3


def _page_layout(size: tuple[float, float]) -> QPageLayout:
    """Rozvržení strany PDF daného rozměru (mm) bez okrajů. Rozměr už orientaci nese (420×297 = na šířku);
    Landscape by ji otočil podruhé → strana na výšku a nerovnoměrně roztažený obsah (oprava jako v pdf_export)."""
    return QPageLayout(QPageSize(QSizeF(*size), QPageSize.Millimeter), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0))


def _page_painter_setup(painter: QPainter, writer: QPdfWriter, size: tuple[float, float] = (PAGE_W, PAGE_H)) -> None:
    """Souřadnice stránky v mm (model, Y nahoru → scénové Y dolů řeší sp())."""
    painter.resetTransform()
    sx = writer.width() / size[0]
    sy = writer.height() / size[1]
    painter.scale(sx, sy)
    painter.translate(0, size[1])  # model Y nahoru: y_scene = -y_model → posun o výšku


def _pseudo_sheet(name: str, project: Project) -> Sheet:
    s = Sheet(name=name, width=PAGE_W, height=PAGE_H)
    return s


def _draw_frame_page(painter, project, sheet_for_frame, view="", page=""):
    g = frame_geometry(project, sheet_for_frame, PAGE_W, PAGE_H, view, page, company=company())
    draw_frame(painter, g, theme.PRINT.ink)
    return g


def _table_area(project: Project) -> tuple[float, float, float, float]:
    """Plocha tabulky na straně (x0, spodek, x1, vršek tabulky) – s rámečkem nad popisovým polem."""
    x0, y0, x1, y1 = frame_geometry(project, _pseudo_sheet("", project), PAGE_W, PAGE_H).inner
    bottom = y0 + TB_H + 5.0 if frame_enabled() else y0 + 3.0
    return x0 + 5.0, bottom, x1 - 5.0, y1 - TABLE_TOP


@dataclass
class _TableLayout:
    """Rozvržení tabulky: šířky sloupců, zalomené buňky, výšky řádků a rozdělení řádků na strany."""
    widths: list[float]
    head: list[list[str]]                       # zalomená hlavička (řádky každé buňky)
    head_h: float
    cells: list[list[list[str]]] = field(default_factory=list)   # řádek → buňka → řádky textu
    heights: list[float] = field(default_factory=list)
    pages: list[tuple[int, int]] = field(default_factory=list)   # (od, do) řádků na stranu

    @property
    def page_count(self) -> int:
        return max(1, len(self.pages))


def _col_widths(head: list[str], rows: list[list], avail: float) -> list[float]:
    """Šířky sloupců: přirozená šířka (nejdelší text) se vejde → ta; jinak každý sloupec aspoň na nejdelší slovo
    a zbytek šířky strany podle toho, kolik by sloupec chtěl navíc (dlouhé texty se zalomí)."""
    n = len(head)
    nat = [0.0] * n
    mn = [0.0] * n
    for i in range(n):
        texts = [str(head[i])] + [str(r[i]) for r in rows if i < len(r) and r[i] not in (None, "")]
        for t in dict.fromkeys(texts):
            for line in t.split("\n"):
                nat[i] = max(nat[i], text_width(line, FONT_H))
                for word in line.split():
                    mn[i] = max(mn[i], min(MAX_WORD, text_width(word, FONT_H)))
    pad = 2 * CELL_PAD + 0.5
    nat = [max(MIN_COL, w + pad) for w in nat]
    mn = [min(nat[i], max(MIN_COL, mn[i] + pad)) for i in range(n)]
    if sum(nat) <= avail:
        return nat
    if sum(mn) >= avail:
        return [w * avail / sum(mn) for w in mn]
    k = (avail - sum(mn)) / (sum(nat) - sum(mn))
    return [mn[i] + k * (nat[i] - mn[i]) for i in range(n)]


def _row_height(lines: list[list[str]]) -> float:
    return max(ROW_H, max(len(c) for c in lines) * LINE_PITCH + 1.8)


def table_layout(project: Project, head: list[str], rows: list[list], widths: list[float] | None = None
                 ) -> _TableLayout:
    """Rozvrhne tabulku na strany dokumentace. `widths` = pevné šířky (obsah: spočítané s nejdelšími čísly)."""
    x0, bottom, x1, top = _table_area(project)
    widths = widths or _col_widths(head, rows, x1 - x0)
    n = len(head)
    cw = [max(1.0, w - 2 * CELL_PAD) for w in widths]
    hl = [wrap_text(str(h), cw[i], FONT_H) for i, h in enumerate(head)]
    lay = _TableLayout(widths, hl, _row_height(hl))
    room = top - bottom - lay.head_h
    max_lines = max(1, int((room - 1.8) // LINE_PITCH))
    for r in rows:
        cells = []
        for i in range(n):
            v = r[i] if i < len(r) else ""
            lines = wrap_text("" if v is None else str(v), cw[i], FONT_H)
            if len(lines) > max_lines:          # buňka vyšší než strana – zkrátit (nemělo by nastat)
                lines = lines[:max_lines - 1] + [lines[max_lines - 1] + " …"]
            cells.append(lines)
        lay.cells.append(cells)
        lay.heights.append(_row_height(cells))
    start, used = 0, 0.0
    for i, h in enumerate(lay.heights):
        if used + h > room and i > start:
            lay.pages.append((start, i))
            start, used = i, 0.0
        used += h
    lay.pages.append((start, len(rows)))
    return lay


class DocBuilder:
    """Sestaví seznam stran (pro obsah) a pak je vykreslí."""

    def __init__(self, project: Project, library, jps_page: str | None = None):
        import dataclasses

        from envocad.model.project import without_dangling
        # bez vodičů na neexistující prvek; vlastní meta – čísla stran dokumentace (`doc_pages`) jen pro tento export
        self.project = dataclasses.replace(without_dangling(project), meta=dict(project.meta))
        self.library = library
        # listy JPS: „A3“ = zmenšit na A3, „list“ = strana ve skutečném formátu listu; None = firemní standard
        self.jps_page = jps_page if jps_page in JPS_PAGE_LABELS else standard_jps_page()
        self.pages: list[tuple[str, str, object]] = []  # (druh, název, data)
        self._page = ""  # „3/16“ aktuální strany pro popisové pole
        self._pdf_page = 0  # index aktuální fyzické strany PDF (od 0), zvyšuje se u každého newPage()
        self._total = 0  # počet fyzických stran (vícepól, plán svorkovnice a tabulky mají víc stran)
        self.page_starts: list[int] = []  # první fyzická strana (od 1) každé položky self.pages – pro obsah
        self.page_counts: list[int] = []  # počet fyzických stran každé položky self.pages
        self.note_pages: list[tuple[int, object, list]] = []  # (fyzická strana od 0, PageMap, připomínky)
        self._layouts: dict[int, _TableLayout] = {}   # index položky → rozvržení tabulky (obsah, výkazy, změny)
        self._scenes: dict[tuple[str, str], tuple[object, QUndoStack]] = {}
        self._size: tuple[float, float] = (PAGE_W, PAGE_H)   # rozměr aktuální strany PDF (mm)
        self.page_sizes: list[tuple[float, float]] = []       # rozměr první strany každé položky self.pages

    def plan(self) -> None:
        p = self.project
        self.pages = [("title", "Titulní list", None), ("toc", "Obsah", None)]
        for s in p.sheets:
            if not s.is_switchboard:
                self.pages.append(("sheet", s.name, (s, "schematic")))
        if self._has_single_line():
            from envocad.ui.single_line_view import single_line_sheet
            self.pages.append(("sheet", "Jednopólové schéma", (single_line_sheet(p), "single_line")))
        for s in p.sheets:
            if s.is_switchboard and mp.has_multipole(s):
                self.pages.append(("sheet", f"{s.name} – schéma", (s, "multipole")))
                self.pages.append(("sheet", f"{s.name} – plán svorkovnice", (s, "terminals")))
        for name, fn in reports.ALL_REPORTS:
            if name in reports.NOT_IN_DOC:
                continue
            head, rows = fn(p, self.library, None)
            if rows:
                self.pages.append(("table", name, (head, rows)))
        self.pages.append(("changes", "Změnový list", None))
        self._layouts = {}

    # ---- tabulky (obsah, výkazy, změnový list) ------------------------------------------------------------
    TOC_HEAD = ("Strana", "Název", "List výkresu")

    def _has_single_line(self) -> bool:
        """Jednopólové schéma do dokumentace: projekt s rozvaděčem napojeným na DS (strom má rozvaděč)."""
        from envocad.model.single_line import build_tree
        try:
            _root, nodes = build_tree(self.project, self.library)
        except (KeyError, ValueError, AttributeError):
            return False
        return any(n.sheet.is_switchboard for n in nodes.values())

    def _toc_sheet_no(self, data) -> str:
        """Číslo listu výkresu (jako v popisovém poli listu) – jen u listů, u tabulek prázdné."""
        if isinstance(data, tuple) and len(data) > 1 and data[1] == "single_line":
            from envocad.model.single_line import page_label
            return page_label(self.project)
        if isinstance(data, tuple) and data and isinstance(data[0], Sheet):
            return sheet_number(self.project, data[0])
        return ""

    def _toc_rows(self, starts: list[int] | None = None) -> list[list]:
        rows = []
        for i, (_kind, name, data) in enumerate(self.pages):
            if starts is None:
                num = "9999"
            else:
                first, cnt = starts[i], (self.page_counts[i] if i < len(self.page_counts) else 1)
                num = f"{first}–{first + cnt - 1}" if cnt > 1 else str(first)
            rows.append([num, name, self._toc_sheet_no(data)])
        return rows

    def _change_rows(self) -> list[list]:
        from envocad.model.diff import split_change_line
        p = self.project
        rows = [split_change_line(ln) for ln in (p.meta.get("changes", "") or "").splitlines() if ln.strip()]
        if not rows:
            rows = [[p.meta.get("revision") or "0", p.meta.get("date", ""), "první vydání", p.meta.get("author", "")]]
        return rows

    CHANGES_HEAD = ("Revize", "Datum", "Popis změny", "Zpracoval")

    def _layout(self, idx: int) -> _TableLayout:
        lay = self._layouts.get(idx)
        if lay is None:
            kind, _name, data = self.pages[idx]
            if kind == "toc":
                # šířky a stránkování s nejdelšími možnými čísly stran – skutečná čísla se do nich vejdou
                ph = self._toc_rows()
                ph = [[f"{r[0]}–{r[0]}", r[1], r[2]] for r in ph]
                lay = table_layout(self.project, list(self.TOC_HEAD), ph)
            elif kind == "changes":
                lay = table_layout(self.project, list(self.CHANGES_HEAD), self._change_rows())
            else:
                head, rows = data
                lay = table_layout(self.project, head, rows)
            self._layouts[idx] = lay
        return lay

    def _draw_table(self, painter, name: str, head: list[str], rows: list[list], lay: _TableLayout,
                    page_no: int) -> None:
        """Jedna strana tabulky (`page_no` = index strany v rozvržení)."""
        p = self.project
        title = name + (" (pokračování)" if page_no else "")
        _draw_frame_page(painter, p, _pseudo_sheet(title, p), page=self._page)
        x0, _bottom, _x1, top = _table_area(p)
        painter.setPen(QPen(theme.PRINT.ink, 0.2))
        draw_text(painter, x0, top + 8.0, title, 4.5, "left")
        total_w = sum(lay.widths)
        y = top
        # hlavička
        painter.setPen(QPen(theme.PRINT.ink, 0.2))
        x = x0
        for i, lines in enumerate(lay.head):
            for j, t in enumerate(lines):
                draw_text(painter, x + CELL_PAD, y - 3.5 - j * LINE_PITCH, t, FONT_H, "left")
            x += lay.widths[i]
        y -= lay.head_h
        painter.setPen(QPen(theme.PRINT.ink, 0.3))
        painter.drawLine(sp(x0, top), sp(x0 + total_w, top))
        painter.drawLine(sp(x0, y), sp(x0 + total_w, y))
        a, b = lay.pages[page_no]
        for r in range(a, b):
            painter.setPen(QPen(theme.PRINT.ink, 0.2))
            x = x0
            for i, lines in enumerate(lay.cells[r]):
                for j, t in enumerate(lines):
                    draw_text(painter, x + CELL_PAD, y - 3.5 - j * LINE_PITCH, t, FONT_H, "left")
                x += lay.widths[i]
            y -= lay.heights[r]
            painter.setPen(QPen(theme.PRINT.ink, 0.08))
            painter.drawLine(sp(x0, y), sp(x0 + total_w, y))
        # svislé dělicí čáry sloupců (tence) – zalomený text zůstane čitelně ve svém sloupci
        painter.setPen(QPen(theme.PRINT.ink, 0.08))
        x = x0
        for w in lay.widths[:-1]:
            x += w
            painter.drawLine(sp(x, top), sp(x, y))

    # ---- strany ----------------------------------------------------------------
    def _title(self, painter, writer):
        p = self.project
        m = p.meta
        s = _pseudo_sheet("Titulní list", p)
        _draw_frame_page(painter, p, s, page=self._page)
        painter.setPen(QPen(theme.PRINT.ink, 0.2))
        draw_text(painter, PAGE_W / 2, 200, company(), 8, "center")
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

    def _scene(self, sheet: Sheet, kind: str):
        """Exportní scéna listu (sdílená mezi počítáním stran a vykreslením). Připomínky nekreslí – v PDF jsou jen
        jako anotace (`pdf_annots`)."""
        key = (sheet.id, kind)
        if key not in self._scenes:
            from envocad.ui.canvas import SchematicScene
            from envocad.ui.multipole_view import MultipoleScene
            from envocad.ui.single_line_view import SingleLineScene
            from envocad.ui.terminal_plan_view import TerminalPlanScene
            undo = QUndoStack()
            cls = {"schematic": SchematicScene, "multipole": MultipoleScene, "terminals": TerminalPlanScene,
                   "single_line": SingleLineScene}[kind]
            scene = cls(self.project, sheet, self.library, undo)
            scene.draw_grid = False
            set_scene_notes_visible(scene, False)
            self._scenes[key] = (scene, undo)
        return self._scenes[key][0]

    def _sheet_pages(self, sheet: Sheet, kind: str) -> int:
        """Počet stran listu: vícepól a plán svorkovnice mohou mít víc stran (`scene.pages`)."""
        if kind == "schematic":
            return 1
        return max(1, len(getattr(self._scene(sheet, kind), "pages", None) or []))

    def _footer(self, painter, writer) -> None:
        """Bez rámečku (není popisové pole s číslem strany): malé „strana n/N“ v pravém dolním rohu."""
        if frame_enabled():
            return
        _page_painter_setup(painter, writer, self._size)
        painter.setPen(QPen(theme.PRINT.ink, 0.2))
        draw_text(painter, self._size[0] - 10.0, 4.0, f"strana {self._pdf_page + 1}/{self._total}", FOOTER_H, "right")

    def _new_page(self, painter, writer, size: tuple[float, float] = (PAGE_W, PAGE_H)) -> None:
        """Další strana PDF rozměru `size` (rozvržení se nastaví těsně před `newPage`, platí pro novou stranu)."""
        self._footer(painter, writer)
        if size != self._size:
            writer.setPageLayout(_page_layout(size))
            self._size = size
        writer.newPage()
        self._pdf_page += 1
        self._page = f"{self._pdf_page + 1}/{self._total}"
        _page_painter_setup(painter, writer, size)

    def _item_size(self, idx: int) -> tuple[float, float]:
        """Rozměr stran položky: vícepól a plán svorkovnice listu rozvaděče = formát jejich stran (výchozí A4);
        list JPS = A3 (list se do ní zmenší), při `jps_page` „list“ skutečný rozměr listu (A2, A1, vlastní…);
        tabulky a vícepól ve formátu listu („list“, starší projekty) = A3."""
        from envocad.model import multipole as mp
        kind, _name, data = self.pages[idx]
        if kind == "sheet":
            sheet, view = data
            if view == "single_line":
                return tuple(float(v) for v in self._scene(sheet, view).paper_size)
            if view == "schematic" and self.jps_page == JPS_PAGE_SHEET:
                return (float(sheet.width), float(sheet.height))
            if view != "schematic" and mp.paper_choice(sheet, switchboard_paper()) != mp.SHEET_PAPER:
                w, h = getattr(self._scene(sheet, view), "paper_size", (PAGE_W, PAGE_H))
                return (float(w), float(h))
        return (PAGE_W, PAGE_H)

    def _sheet(self, painter, writer, sheet: Sheet, kind: str):
        scene = self._scene(sheet, kind)
        pw, ph = getattr(scene, "paper_size", (sheet.width, sheet.height))
        size = self._size
        painter.resetTransform()
        # vejít do strany (list JPS A3, vícepól a plán svorkovnice ve formátu svých stran – výchozí A4);
        # vícepól a plán svorkovnice mohou mít víc stran (každá na vlastní stranu PDF)
        pages = getattr(scene, "pages", None) or [QRectF(0, -ph, pw, ph)]
        first = self._pdf_page
        for i, src in enumerate(pages):
            if i:
                self._new_page(painter, writer, size)
                painter.resetTransform()
            scale = min(writer.width() / pw, writer.height() / ph)
            scene.render(painter, QRectF(0, 0, pw * scale, ph * scale), src, Qt.KeepAspectRatio)
        if kind in ("terminals", "single_line"):
            return
        from envocad.export.pdf_annots import PageMap
        from envocad.model.notes import notes_on_sheet
        notes = notes_on_sheet(self.project, sheet.id, ("open",))
        if not notes:
            return
        r = writer.pageLayout().fullRect(QPageLayout.Millimeter)
        pm = PageMap.fit(pw, ph, r.width(), r.height(), center=False)   # list u levého horního rohu strany
        if kind == "schematic":
            self.note_pages.append((self._pdf_page, pm, notes))
            return
        # list rozvaděče: připomínka je v kresbě listu rozvaděče – ve vícepólu se ukáže u přístroje, ke kterému
        # patří (bod u jeho polohy ve vícepólu); bez vazby na přístroj vlevo nahoře na první straně
        by_page: dict[int, list] = {}
        for i, n in enumerate(notes):
            k, x, y, where = self._multipole_anchor(scene, sheet, n, i)
            text = n.text if where else f"{n.text}\n(připomínka k listu rozvaděče {sheet.name}, bez vazby na přístroj)"
            by_page.setdefault(k, []).append(replace(n, x=x, y=y, w=0.0, h=0.0, text=text))
        for k, ns in sorted(by_page.items()):
            self.note_pages.append((first + k, pm, ns))

    @staticmethod
    def _multipole_anchor(scene, sheet: Sheet, note, i: int) -> tuple[int, float, float, bool]:
        """Strana vícepólu a bod (souřadnice strany, mm) pro připomínku listu rozvaděče: u přístroje, na který je
        navázaná (vodič → jeho první konec); jinak vlevo nahoře na první straně. Poslední hodnota = má vazbu."""
        from envocad.model.frame import MARGIN, MARGIN_LEFT
        eid = note.target_id
        if note.is_wire:
            w = next((w for w in sheet.wires if w.id == eid), None)
            eid = w.a.element_id if w is not None else ""
        ep = getattr(scene, "_poles", {}).get(eid) if eid else None
        if ep is not None:
            k = scene.page_of.get(eid, 0)
            x, y = ep.origin
            return k, x + 2.5, y + k * scene.page_pitch + 2.5, True
        ph = getattr(scene, "paper_size", (sheet.width, sheet.height))[1]
        return 0, MARGIN_LEFT + 5.0 + 8.0 * i, ph - MARGIN - 30.0, False

    def _count_pages(self) -> None:
        """Fyzické strany předem: popisové pole ukazuje „n/N“ a obsah skutečná čísla stran."""
        self.page_starts, self.page_counts, self.page_sizes = [], [], []
        total = 0
        for idx, (kind, _name, data) in enumerate(self.pages):
            self.page_starts.append(total + 1)
            self.page_sizes.append(self._item_size(idx))
            if kind == "sheet":
                cnt = self._sheet_pages(*data)
            elif kind in ("table", "toc", "changes"):
                cnt = self._layout(idx).page_count
            else:
                cnt = 1
            self.page_counts.append(cnt)
            total += cnt
        self._total = total
        self.project.meta[DOC_PAGES_KEY] = self.page_numbers()   # popisová pole listů: „Strana n/N“

    def page_numbers(self) -> str:
        """Čísla stran listů v dokumentaci jako JSON pro `meta["doc_pages"]` (`frame.doc_page`): list JPS, vícepól,
        plán svorkovnice a jednopólové schéma – každá jejich strana."""
        import json
        pages: dict[str, int] = {}
        for idx, (kind, _name, data) in enumerate(self.pages):
            if kind != "sheet":
                continue
            sheet, view = data
            sid = "" if view == "single_line" else sheet.id
            for k in range(self.page_counts[idx]):
                pages[doc_page_key(view, sid, k)] = self.page_starts[idx] + k
        return json.dumps({"total": self._total, "pages": pages}, separators=(",", ":"))

    def _table_kind(self, painter, writer, idx: int) -> None:
        kind, name, data = self.pages[idx]
        lay = self._layout(idx)
        if kind == "toc":
            head, rows, name = list(self.TOC_HEAD), self._toc_rows(self.page_starts), "Obsah dokumentace"
            # skutečná čísla stran do šířek spočítaných s nejdelšími čísly – zalomení ani počet stran se nezmění
            lay = table_layout(self.project, head, rows, widths=lay.widths)
        elif kind == "changes":
            head, rows = list(self.CHANGES_HEAD), self._change_rows()
        else:
            head, rows = data
        for k in range(lay.page_count):
            if k:
                self._new_page(painter, writer, (PAGE_W, PAGE_H))
            self._draw_table(painter, name, head, rows, lay, k)

    # ---- export --------------------------------------------------------------------
    def export(self, path: Path | str, notes: bool = False) -> int:
        """Vykreslí dokumentaci; `notes=True` doplní otevřené připomínky listů jako anotace PDF (listy rozvaděčů
        u přístroje ve vícepólu). Vrací počet fyzických stran."""
        self.plan()
        self._pdf_page = 0
        self.note_pages = []
        self._size = (PAGE_W, PAGE_H)      # titulní list je vždy první a A3
        writer = QPdfWriter(str(path))
        writer.setPageSize(QPageSize(QSizeF(PAGE_W, PAGE_H), QPageSize.Millimeter))
        writer.setPageLayout(_page_layout(self._size))
        writer.setResolution(300)
        writer.setTitle(f"{self.project.name} – dokumentace")
        writer.setCreator("EnvoCAD")
        prev_dark = theme.is_dark()
        theme._current = theme.PRINT
        painter = QPainter(writer)
        painter.setRenderHint(QPainter.Antialiasing)
        try:
            self._count_pages()
            for idx, (kind, _name, data) in enumerate(self.pages):
                if idx:
                    self._new_page(painter, writer, self.page_sizes[idx])
                else:
                    _page_painter_setup(painter, writer, self._size)
                    self._page = f"1/{self._total}"
                if kind == "title":
                    self._title(painter, writer)
                elif kind == "sheet":
                    self._sheet(painter, writer, *data)
                else:
                    self._table_kind(painter, writer, idx)
            self._footer(painter, writer)
        finally:
            painter.end()
            theme._current = theme.DARK if prev_dark else theme.LIGHT
            for scene, _undo in self._scenes.values():
                scene.deleteLater()
            self._scenes.clear()
        count = self._pdf_page + 1
        from envocad.export.pdf_outline import add_bookmarks  # záložky = řádky obsahu; před anotacemi
        add_bookmarks(path, [(name, self.page_starts[i] - 1) for i, (_k, name, _d) in enumerate(self.pages)])
        if notes and self.note_pages:
            from envocad.export.pdf_annots import add_note_annotations
            add_note_annotations(path, self.note_pages, self.project.name)
        return count


def export_documentation_pdf(project: Project, library, path: Path | str, notes: bool = False,
                             jps_page: str | None = None, page_numbers: list | None = None) -> int:
    """Vrátí počet stran. `notes=True` = otevřené připomínky jako anotace PDF. `jps_page` = „A3“ (listy JPS zmenšit
    na A3) / „list“ (strana ve skutečném formátu listu); None = firemní standard `doc_jps_page`. Do `page_numbers`
    (seznam) se připojí čísla stran listů (JSON pro `meta["doc_pages"]`) – projekt sám se nemění."""
    b = DocBuilder(project, library, jps_page)
    n = b.export(path, notes=notes)
    if page_numbers is not None:
        page_numbers.append(b.project.meta[DOC_PAGES_KEY])
    return n


def documentation_page_numbers(project: Project, library, jps_page: str | None = None) -> str:
    """Čísla stran listů celé dokumentace bez exportu (JSON pro `meta["doc_pages"]`, příkaz Přečíslovat strany)."""
    b = DocBuilder(project, library, jps_page)
    b.plan()
    b._count_pages()
    return b.project.meta[DOC_PAGES_KEY]
