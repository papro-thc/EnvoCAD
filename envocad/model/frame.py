"""Rámeček listu a popisové pole ENVO – čistá geometrie (mm, Y nahoru), kreslí ji Qt i DXF export stejně."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date

from envocad.model.project import Project, Sheet

MARGIN = 10.0        # okraj rámečku
MARGIN_LEFT = 20.0   # širší okraj pro vazbu
TB_W, TB_H = 180.0, 32.0  # popisové pole (š × v)
COMPANY = "ENVO s.r.o."


@dataclass
class FrameGeometry:
    lines: list[tuple[float, float, float, float]] = field(default_factory=list)      # x1, y1, x2, y2
    texts: list[tuple[float, float, str, float, str]] = field(default_factory=list)  # x, y, text, výška, zarovnání
    inner: tuple[float, float, float, float] = (0, 0, 0, 0)                           # x0, y0, x1, y1 kreslicí plochy


def sheet_number(project: Project, sheet: Sheet) -> str:
    ids = [s.id for s in project.sheets]
    i = ids.index(sheet.id) + 1 if sheet.id in ids else 0
    return f"{i}/{len(ids)}"


def title_rows(project: Project, sheet: Sheet, view: str = "") -> list[list[tuple[str, str]]]:
    """Řádky popisového pole jako [(popisek, hodnota), …] – vlevo doleva, vpravo doprava."""
    m = project.meta
    date = m.get("date") or _date.today().strftime("%d.%m.%Y")  # noqa: DTZ011
    name = sheet.name + (f" – {view}" if view else "")
    return [
        [("Projekt", project.name), ("Zakázka", m.get("order", ""))],
        [("Investor", m.get("investor", "")), ("Místo", m.get("place", ""))],
        [("List", name), ("Číslo listu", sheet_number(project, sheet))],
        [("Zpracoval", m.get("author", "")), ("Datum", date), ("Revize", m.get("revision", "")),
         ("Formát", sheet.paper)],
    ]


def frame_geometry(project: Project, sheet: Sheet, width: float | None = None, height: float | None = None,
                   view: str = "") -> FrameGeometry:
    """Rámeček s popisovým polem vpravo dole. Pro odvozené pohledy (vícepól) lze zadat jiný rozměr listu."""
    w = width or sheet.width
    h = height or sheet.height
    g = FrameGeometry()
    x0, y0, x1, y1 = MARGIN_LEFT, MARGIN, w - MARGIN, h - MARGIN
    g.inner = (x0, y0, x1, y1)
    g.lines += [(x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)]
    # popisové pole
    tx0, ty0 = x1 - TB_W, y0
    tx1, ty1 = x1, y0 + TB_H
    g.lines += [(tx0, ty0, tx0, ty1), (tx0, ty1, tx1, ty1)]
    rows = title_rows(project, sheet, view)
    rh = TB_H / len(rows)
    logo_w = 34.0
    g.lines.append((tx0 + logo_w, ty0, tx0 + logo_w, ty1))
    g.texts.append((tx0 + logo_w / 2, ty0 + TB_H / 2 - 2.0, "ENVO", 5.0, "center"))
    g.texts.append((tx0 + logo_w / 2, ty0 + TB_H / 2 - 6.0, COMPANY, 1.8, "center"))
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
