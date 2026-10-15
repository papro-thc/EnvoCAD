"""Rámeček listu a popisové pole ENVO – čistá geometrie (mm, Y nahoru), kreslí ji Qt i DXF export stejně."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date

from envocad.model.project import Project, Sheet

MARGIN = 10.0        # okraj rámečku
MARGIN_LEFT = 20.0   # širší okraj pro vazbu
TB_W, TB_H = 180.0, 32.0  # popisové pole (š × v)
COMPANY = "ENVO s.r.o."   # výchozí; přepíše `standard.company` v ~/.envocad/settings.json


def frame_enabled() -> bool:
    """Kreslit rámeček s popisovým polem? (nastavení `frame`, výchozí vypnuto – souřadnicová síť /2.B4 funguje i bez něj)"""
    try:
        from envocad.settings import load_settings
        return bool(load_settings().get("frame", False))
    except Exception:  # noqa: BLE001
        return False


def company_names() -> tuple[str, str]:
    """(krátký název do loga, plný název firmy) z firemního standardu."""
    try:
        from envocad.settings import load_settings
        full = (load_settings()["standard"].get("company") or COMPANY).strip()
    except Exception:  # noqa: BLE001
        full = COMPANY
    short = full.split()[0].rstrip(",") if full else "ENVO"
    return short, full
COLS = "ABCDEFGH"   # sloupce souřadnicové sítě (zleva doprava)
ROWS = 6            # řádky 1…6 (shora dolů)


@dataclass
class FrameGeometry:
    lines: list[tuple[float, float, float, float]] = field(default_factory=list)      # x1, y1, x2, y2
    texts: list[tuple[float, float, str, float, str]] = field(default_factory=list)  # x, y, text, výška, zarovnání
    inner: tuple[float, float, float, float] = (0, 0, 0, 0)                           # x0, y0, x1, y1 kreslicí plochy
    rects: list[tuple[float, float, float, float]] = field(default_factory=list)      # vyplněné obdélníky (QR): x, y, w, h


def grid_coord(sheet: Sheet, x: float, y: float, width: float | None = None, height: float | None = None) -> str:
    """Souřadnice v síti listu („B4“) pro bod (x, y) v mm – sloupce A–H zleva, řádky 1–6 shora."""
    w = width or sheet.width
    h = height or sheet.height
    x0, y0, x1, y1 = MARGIN_LEFT, MARGIN, w - MARGIN, h - MARGIN
    ci = int((x - x0) / (x1 - x0) * len(COLS)) if x1 > x0 else 0
    ri = int((y1 - y) / (y1 - y0) * ROWS) if y1 > y0 else 0
    ci = min(max(ci, 0), len(COLS) - 1)
    ri = min(max(ri, 0), ROWS - 1)
    return f"{COLS[ci]}{ri + 1}"


def position_ref(project: Project, sheet: Sheet, x: float, y: float) -> str:
    """Odkaz na místo ve výkresu jako v EPLAN: „/3.B4“ = list 3, sloupec B, řádek 4."""
    n = sheet_number(project, sheet).split("/")[0]
    return f"/{n}.{grid_coord(sheet, x, y)}"


def qr_modules(text: str) -> list[list[bool]] | None:
    """Matice QR kódu (True = tmavý modul) přes `segno`; None, když knihovna chybí."""
    try:
        import segno
    except ImportError:
        return None
    q = segno.make(text, error="m")
    return [[bool(v) for v in row] for row in q.matrix]


def qr_text(project: Project, sheet: Sheet, view: str = "") -> str:
    m = project.meta
    parts = [project.name, m.get("order", ""), sheet.name + (f" – {view}" if view else ""), f"rev. {m.get('revision', '') or '0'}"]
    return " | ".join(x for x in parts if x)


def sheet_number(project: Project, sheet: Sheet) -> str:
    ids = [s.id for s in project.sheets]
    i = ids.index(sheet.id) + 1 if sheet.id in ids else 0
    return f"{i}/{len(ids)}"


def title_rows(project: Project, sheet: Sheet, view: str = "", page: str = "") -> list[list[tuple[str, str]]]:
    """Řádky popisového pole jako [(popisek, hodnota), …] – vlevo doleva, vpravo doprava."""
    m = project.meta
    date = m.get("date") or _date.today().strftime("%d.%m.%Y")  # noqa: DTZ011
    name = sheet.name + (f" – {view}" if view else "")
    return [
        [("Projekt", project.name), ("Zakázka", m.get("order", ""))],
        [("Investor", m.get("investor", "")), ("Místo", m.get("place", ""))],
        [("List", name), ("Číslo listu", page or sheet_number(project, sheet))],
        [("Zpracoval", m.get("author", "")), ("Datum", date), ("Revize", m.get("revision", "")),
         ("Formát", sheet.paper)],
    ]


def frame_geometry(project: Project, sheet: Sheet, width: float | None = None, height: float | None = None,
                   view: str = "", page: str = "") -> FrameGeometry:
    """Rámeček s popisovým polem vpravo dole. Pro odvozené pohledy (vícepól) lze zadat jiný rozměr listu."""
    w = width or sheet.width
    h = height or sheet.height
    g = FrameGeometry()
    x0, y0, x1, y1 = MARGIN_LEFT, MARGIN, w - MARGIN, h - MARGIN
    g.inner = (x0, y0, x1, y1)
    g.lines += [(x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)]
    # souřadnicová síť v okraji: sloupce A–H nahoře i dole, řádky 1–6 vlevo i vpravo
    cw = (x1 - x0) / len(COLS)
    for i, c in enumerate(COLS):
        cx = x0 + i * cw
        if i:
            g.lines += [(cx, y1, cx, y1 + 3), (cx, y0, cx, y0 - 3)]
        g.texts += [(cx + cw / 2, y1 + 1.5, c, 2.5, "center"), (cx + cw / 2, y0 - 4.0, c, 2.5, "center")]
    rh = (y1 - y0) / ROWS
    for r in range(ROWS):
        ry = y1 - r * rh
        if r:
            g.lines += [(x0 - 3, ry, x0, ry), (x1, ry, x1 + 3, ry)]
        g.texts += [(x0 - 2.0, ry - rh / 2 - 1.0, str(r + 1), 2.5, "right"), (x1 + 2.0, ry - rh / 2 - 1.0, str(r + 1), 2.5, "left")]
    # popisové pole
    tx0, ty0 = x1 - TB_W, y0
    tx1, ty1 = x1, y0 + TB_H
    g.lines += [(tx0, ty0, tx0, ty1), (tx0, ty1, tx1, ty1)]
    rows = title_rows(project, sheet, view, page)
    rh = TB_H / len(rows)
    logo_w = 34.0
    g.lines.append((tx0 + logo_w, ty0, tx0 + logo_w, ty1))
    short, full = company_names()
    g.texts.append((tx0 + logo_w / 2, ty0 + TB_H / 2 - 2.0, short, 5.0, "center"))
    g.texts.append((tx0 + logo_w / 2, ty0 + TB_H / 2 - 6.0, full, 1.8, "center"))
    # QR kód s identifikací výkresu vlevo od popisového pole (projekt | zakázka | list | revize)
    mods = qr_modules(qr_text(project, sheet, view))
    if mods:
        n = len(mods)
        size = TB_H - 6.0
        cell = size / n
        qx0, qy0 = tx0 - size - 4.0, ty0 + 3.0
        for r, row in enumerate(mods):
            for c, dark in enumerate(row):
                if dark:
                    g.rects.append((qx0 + c * cell, qy0 + size - (r + 1) * cell, cell, cell))
    cx0 = tx0 + logo_w
    cw = TB_W - logo_w
    for r, cells in enumerate(rows):
        top = ty1 - r * rh
        if r:
            g.lines.append((cx0, top, tx1, top))
        colw = cw / len(cells)
        for c, (label, value) in enumerate(cells):
            cx = cx0 + c * colw
            if c:
                g.lines.append((cx, top - rh, cx, top))
            g.texts.append((cx + 1.0, top - 2.2, label, 1.5, "left"))
            g.texts.append((cx + 1.0, top - rh + 1.3, value, 2.5 if r < 3 else 2.2, "left"))
    return g
