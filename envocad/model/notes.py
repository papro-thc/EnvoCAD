"""Připomínky (redlining) – pomocné funkce a geometrie pro editor i DXF. Čistá data, bez Qt.

Připomínky leží v `Project.notes` (ne v listu: kopie listu je neduplikuje, smazání listu je neztratí). Nejsou
součástí dokumentace – `diff_projects` ani `sheet_fingerprint` je nevidí a do obsahu PDF se nevypalují
(v PDF jsou jen jako anotace, `export/pdf_annots.py`). Návrh: `docs/design/pripominky.md`.
"""
from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass, field

from envocad.model.project import NOTE_STATUSES, Note, Project, Sheet
from envocad.model.symbol import GRID

FLAG_H = 5.0          # výška praporku s číslem [mm]
TEXT_H = 2.5          # výška písma [mm]
CROSS = 1.0           # velikost křížku v kotvě bodu [mm]
LEADER = 2.5          # odkazová čára bodu do (x + 2,5; y + 2,5)
WRAP = 40             # zalomení textu připomínky v DXF (with_text) [znaků]
LINE_PITCH = 3.5      # řádkování textu [mm]
STATUS_LABELS = {"open": "otevřeno", "resolved": "vyřešeno"}
# barva podle stavu (RGB 0–255, neukládá se): otevřeno purpurová (odlišná od červené revize), vyřešeno šedá
STATUS_COLORS = {"open": (190, 0, 190), "resolved": (128, 128, 128)}


# ---- správa seznamu ------------------------------------------------------------------------------
def next_note_no(project: Project) -> int:
    """Další pořadové číslo připomínky = nejvyšší + 1 (čísla se při smazání nepřečíslovávají)."""
    return max((n.no for n in project.notes), default=0) + 1


def note(project: Project, note_id: str) -> Note | None:
    return next((n for n in project.notes if n.id == note_id), None)


def notes_on_sheet(project: Project, sheet_id: str, statuses: tuple[str, ...] | None = None) -> list[Note]:
    """Připomínky listu (v pořadí čísel); `statuses=None` = všechny stavy."""
    out = [n for n in project.notes if n.sheet_id == sheet_id and (statuses is None or n.status in statuses)]
    return sorted(out, key=lambda n: n.no)


def put_note(project: Project, n: Note, index: int | None = None) -> int:
    """Vloží připomínku, nebo nahradí existující se stejným `id` na jejím místě. Bez čísla (`no == 0`) dostane
    další volné. `index` = pozice vložení nové (undo smazání ji vrátí na původní místo). Vrací index v seznamu."""
    if n.no <= 0:
        n.no = next_note_no(project)
    for i, old in enumerate(project.notes):
        if old.id == n.id:
            project.notes[i] = n
            return i
    if index is None or not 0 <= index <= len(project.notes):
        project.notes.append(n)
        return len(project.notes) - 1
    project.notes.insert(index, n)
    return index


def remove_note(project: Project, note_id: str) -> tuple[Note, int] | None:
    """Odebere připomínku; vrací (připomínka, původní index) pro undo, nebo None."""
    for i, n in enumerate(project.notes):
        if n.id == note_id:
            del project.notes[i]
            return n, i
    return None


def resolve(n: Note, by: str, when: str, reply: str = "") -> Note:
    """Označí připomínku jako vyřešenou (kdo, kdy ISO, volitelně odpověď). Mění `n` na místě a vrací ji."""
    n.status = "resolved"
    n.resolved_by, n.resolved = by, when
    if reply:
        n.reply = reply
    return n


def reopen(n: Note) -> Note:
    """Znovu otevře připomínku; odpověď zůstává (historie), údaje o vyřízení se smažou."""
    n.status = "open"
    n.resolved_by = n.resolved = ""
    return n


def orphan_notes(project: Project) -> list[Note]:
    """Připomínky na listech, které už v projektu nejsou."""
    ids = {s.id for s in project.sheets}
    return [n for n in project.notes if n.sheet_id not in ids]


def note_target_label(project: Project, n: Note) -> str:
    """Popis prvku/vodiče, ke kterému se připomínka vztahuje („F3“, „W2“, „vodič“), „(smazáno)“ pro cíl, který už
    na listu není, „“ bez cíle."""
    if not n.target_id:
        return ""
    sheet = next((s for s in project.sheets if s.id == n.sheet_id), None)
    if sheet is None:
        return "(smazáno)"
    if n.is_wire:
        w = next((w for w in sheet.wires if w.id == n.target_id), None)
        return "(smazáno)" if w is None else (w.attrs.get("ref", "") or "vodič")
    e = next((e for e in sheet.elements if e.id == n.target_id), None)
    return "(smazáno)" if e is None else (e.ref or e.symbol_id)


# ---- geometrie -------------------------------------------------------------------------------------
@dataclass
class NoteShape:
    """Kresba jedné připomínky (mm, Y nahoru). `polylines` jsou uzavřené (praporek, obrys obdélníku – Qt ho kreslí
    čárkovaně, DXF plně); `texts` jako `FrameGeometry.texts` (x, účaří y, text, výška, zarovnání)."""
    note_id: str
    status: str
    lines: list[tuple[float, float, float, float]] = field(default_factory=list)
    polylines: list[list[tuple[float, float]]] = field(default_factory=list)
    texts: list[tuple[float, float, str, float, str]] = field(default_factory=list)
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)   # x0, y0, x1, y1


def _ceil_grid(v: float) -> float:
    return math.ceil(v / GRID - 1e-9) * GRID


def flag_width(label: str) -> float:
    """Šířka praporku s číslem – jako trojúhelník revize `max(5, 1,6·len + 3)`, zaokrouhleno nahoru na mřížku."""
    return _ceil_grid(max(FLAG_H, 1.6 * len(label) + 3.0))


def note_label(n: Note) -> str:
    return str(n.no) if n.no > 0 else "?"


def rect_pts(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def flag_origin(n: Note) -> tuple[float, float]:
    """Levý dolní roh praporku: bod → konec odkazové čáry, obdélník → pravý horní roh."""
    if n.is_rect:
        return n.x + n.w, n.y + n.h
    return n.x + LEADER, n.y + LEADER


def note_shape(n: Note, with_text: bool = False) -> NoteShape:
    """Kresba připomínky. Bod: křížek v kotvě, odkazová čára a praporek s číslem. Obdélník: obrys a praporek na
    pravém horním rohu. `with_text` (DXF) přidá vpravo od praporku text zalomený na 40 znaků."""
    g = NoteShape(n.id, n.status)
    label = note_label(n)
    fx, fy = flag_origin(n)
    fw = flag_width(label)
    if n.is_rect:
        g.polylines.append(rect_pts(n.x, n.y, n.x + n.w, n.y + n.h))
    else:
        c = CROSS / 2
        g.lines += [(n.x - c, n.y - c, n.x + c, n.y + c), (n.x - c, n.y + c, n.x + c, n.y - c),
                    (n.x, n.y, fx, fy)]
    g.polylines.append(rect_pts(fx, fy, fx + fw, fy + FLAG_H))
    g.texts.append((fx + fw / 2, fy + (FLAG_H - TEXT_H) / 2, label, TEXT_H, "center"))
    x0 = min(n.x, fx) - (0 if n.is_rect else CROSS / 2)
    y0 = min(n.y, fy) - (0 if n.is_rect else CROSS / 2)
    x1, y1 = fx + fw, fy + FLAG_H
    if with_text and n.text.strip():
        tx = fx + fw + 1.0
        y = fy + (FLAG_H - TEXT_H) / 2          # první řádek na účaří čísla v praporku
        wrapped = [w for para in n.text.splitlines() for w in (textwrap.wrap(para, WRAP) or [""])]
        for line in wrapped:
            g.texts.append((tx, y, line, TEXT_H, "left"))
            y -= LINE_PITCH
        x1 = max(x1, tx + 0.6 * TEXT_H * max(len(s) for s in wrapped))   # odhad šířky písma
        y0 = min(y0, y + LINE_PITCH - 0.5)
    g.bbox = (x0, y0, x1, y1)
    return g


def notes_geometry(project: Project, sheet: Sheet, statuses: tuple[str, ...] | None = ("open",),
                   with_text: bool = False) -> list[NoteShape]:
    """Kresby připomínek listu ve stavech `statuses` (`None` = všechny), v pořadí čísel."""
    return [note_shape(n, with_text) for n in notes_on_sheet(project, sheet.id, statuses)]


__all__ = ["FLAG_H", "NOTE_STATUSES", "STATUS_COLORS", "STATUS_LABELS", "TEXT_H", "NoteShape", "flag_width", "next_note_no", "note",
           "note_label", "note_shape", "note_target_label", "notes_geometry", "notes_on_sheet", "orphan_notes",
           "put_note", "remove_note", "reopen", "resolve"]
