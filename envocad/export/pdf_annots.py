"""Připomínky jako anotace PDF (komentáře v Acrobatu / prohlížečích) – post-processing hotového PDF přes pypdf.
Bez Qt. QPdfWriter anotace neumí, proto se doplní do souboru až po vykreslení (`pdf_export`, `doc_pdf`).

Bod → `/Text` (ikona komentáře), obdélník → `/Square`; každá má `/Popup` a `/NM envocad:<id>` (pro budoucí
import odpovědí). Vyřešená připomínka dostane odpověď (`/IRT`) se stavem `/StateModel /Review /State /Completed`.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

from envocad.model.notes import STATUS_COLORS
from envocad.model.project import Note

MM_TO_PT = 72 / 25.4
ICON_PT = 18.0          # strana obdélníku ikony /Text [pt]
POPUP_W, POPUP_H = 180.0, 100.0


@dataclass
class PageMap:
    """Převod modelu listu (mm, Y nahoru) na stranu PDF (mm od levého horního rohu, Y dolů):
    `(tx + x·scale, ty + (sheet_h − y)·scale)`. `sheet_h` = výška vykreslené oblasti listu v modelu."""
    scale: float
    tx: float
    ty: float
    sheet_h: float

    def to_page_mm(self, x: float, y: float) -> tuple[float, float]:
        return self.tx + x * self.scale, self.ty + (self.sheet_h - y) * self.scale

    @classmethod
    def fit(cls, src_w: float, src_h: float, page_w: float, page_h: float, center: bool = False) -> PageMap:
        """Jako `QGraphicsScene.render(painter, strana, list, Qt.KeepAspectRatio)`: list `src_w × src_h` zvětšený
        do strany `page_w × page_h` (mm) se zachováním poměru, **u levého horního rohu** – `QGraphicsScene.render`
        na rozdíl od `QGraphicsView.render` nevystředí, zbytek strany zůstane vpravo/dole prázdný.
        `center=True` = vystředěný (jen pokud se list kreslí do vystředěného cíle)."""
        s = min(page_w / src_w, page_h / src_h)
        tx = (page_w - src_w * s) / 2 if center else 0.0
        ty = (page_h - src_h * s) / 2 if center else 0.0
        return cls(s, tx, ty, src_h)


def _pt(pm: PageMap, x: float, y: float, page_h_pt: float) -> tuple[float, float]:
    u, v = pm.to_page_mm(x, y)
    return u * MM_TO_PT, page_h_pt - v * MM_TO_PT


def note_rect_pt(n: Note, pm: PageMap, page_h_pt: float) -> tuple[float, float, float, float]:
    """Obdélník anotace v bodech PDF (x0, y0, x1, y1; počátek vlevo dole). Obdélník připomínky = jeho obrys,
    bod = ikona `ICON_PT` s levým dolním rohem v kotvě (jako praporek v editoru, vpravo nahoře od kotvy)."""
    if n.is_rect:
        x0, y0 = _pt(pm, n.x, n.y, page_h_pt)
        x1, y1 = _pt(pm, n.x + n.w, n.y + n.h, page_h_pt)
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    x, y = _pt(pm, n.x, n.y, page_h_pt)
    return x, y, x + ICON_PT, y + ICON_PT


def pdf_date(iso: str) -> str:
    """„2026-10-16T14:05“ → „D:202610161405“ (formát data PDF); prázdné/nečitelné → „“."""
    digits = re.sub(r"\D", "", iso or "")[:14]
    return f"D:{digits}" if len(digits) >= 8 else ""


def _color(status: str):
    from pypdf.generic import ArrayObject, FloatObject
    r, g, b = STATUS_COLORS.get(status, STATUS_COLORS["open"])
    return ArrayObject([FloatObject(round(c / 255, 4)) for c in (r, g, b)])


def _rect(r):
    from pypdf.generic import ArrayObject, FloatObject
    return ArrayObject([FloatObject(round(v, 3)) for v in r])


def add_note_annotations(path: Path | str, pages: list[tuple[int, PageMap, list[Note]]], project_name: str = "") -> int:
    """Doplní do hotového PDF `path` anotace připomínek. `pages` = (index fyzické strany od 0, převod, připomínky).
    Výška strany se bere z MediaBoxu. `project_name` je náhradní autor u připomínek bez autora. Soubor se přepíše
    jen pokud je co přidat. Vrací počet přidaných připomínek (bez popupů a odpovědí)."""
    items = [(i, pm, ns) for i, pm, ns in pages if ns]
    if not items:
        return 0
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import BooleanObject, DictionaryObject, NameObject, NumberObject, TextStringObject

    p = Path(path)
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(p.read_bytes())))
    count = 0

    def name(v: str) -> NameObject:
        return NameObject(v)

    def text(v: str) -> TextStringObject:
        return TextStringObject(v)

    for page_idx, pm, notes in items:
        if not 0 <= page_idx < len(writer.pages):
            raise IndexError(f"PDF nemá stranu {page_idx + 1}")
        page = writer.pages[page_idx]
        mb = page.mediabox
        page_h_pt, left, bottom = float(mb.height), float(mb.left), float(mb.bottom)
        for n in notes:
            x0, y0, x1, y1 = note_rect_pt(n, pm, page_h_pt)
            rect = (x0 + left, y0 + bottom, x1 + left, y1 + bottom)
            annot = DictionaryObject({
                name("/Type"): name("/Annot"),
                name("/Subtype"): name("/Square" if n.is_rect else "/Text"),
                name("/Rect"): _rect(rect),
                name("/Contents"): text(n.text),
                name("/T"): text(n.author or project_name),
                name("/Subj"): text(f"Připomínka č. {n.no}"),
                name("/NM"): text(f"envocad:{n.id}"),
                name("/C"): _color(n.status),
                name("/F"): NumberObject(4),          # tisknout
            })
            date = pdf_date(n.created)
            if date:
                annot[name("/M")] = text(date)
                annot[name("/CreationDate")] = text(date)
            if n.is_rect:
                annot[name("/BS")] = DictionaryObject({name("/W"): NumberObject(1), name("/S"): name("/S")})
            else:
                annot[name("/Name")] = name("/Comment")
                annot[name("/Open")] = BooleanObject(False)
            added = writer.add_annotation(page_idx, annot)
            ref = added.indirect_reference
            px, py = rect[2], rect[3]
            popup = DictionaryObject({
                name("/Type"): name("/Annot"), name("/Subtype"): name("/Popup"),
                name("/Rect"): _rect((px, py - POPUP_H, px + POPUP_W, py)),
                name("/Parent"): ref, name("/Open"): BooleanObject(False),
            })
            pop = writer.add_annotation(page_idx, popup)
            ref.get_object()[name("/Popup")] = pop.indirect_reference   # starší pypdf to samo nedělá
            if n.status == "resolved":
                reply = DictionaryObject({
                    name("/Type"): name("/Annot"), name("/Subtype"): name("/Text"),
                    name("/Rect"): _rect(rect),
                    name("/Contents"): text(n.reply or "Vyřešeno"),
                    name("/T"): text(n.resolved_by or n.author or project_name),
                    name("/Subj"): text(f"Připomínka č. {n.no} – vyřešeno"),
                    name("/NM"): text(f"envocad:{n.id}:resolved"),
                    name("/IRT"): ref,
                    name("/StateModel"): text("Review"),
                    name("/State"): text("Completed"),
                    name("/Name"): name("/Comment"),
                    name("/C"): _color(n.status),
                    name("/F"): NumberObject(4),
                    name("/Open"): BooleanObject(False),
                })
                rdate = pdf_date(n.resolved)
                if rdate:
                    reply[name("/M")] = text(rdate)
                writer.add_annotation(page_idx, reply)
            count += 1
    buf = io.BytesIO()
    writer.write(buf)
    p.write_bytes(buf.getvalue())
    return count
