"""Rámeček listu a popisové pole ENVO – čistá geometrie (mm, Y nahoru), kreslí ji Qt i DXF export stejně."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime as _datetime

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
TEXT_CHAR_W = 0.72   # odhad průměrné šířky znaku / výška písma (Arial, jako `textlayout.CHAR_W`)
MIN_TEXT_H = 1.6     # nejmenší výška písma hodnoty v popisovém poli


def fit_text(text: str, width: float, height: float, min_height: float = MIN_TEXT_H) -> tuple[str, float]:
    """Text do buňky široké `width` mm: když je širší, zmenší se písmo (nejvýš na `min_height`), a když se nevejde
    ani tak, zkrátí se s „…“ na konci. Šířka je odhad (`TEXT_CHAR_W`). Vrací (text, výška písma)."""
    text = str(text or "")
    if not text or width <= 0:
        return text, height
    est = TEXT_CHAR_W * len(text)
    if est * height <= width:
        return text, height
    h = max(min_height, width / est)
    if est * h <= width:
        return text, round(h, 2)
    n = max(1, int(width / (TEXT_CHAR_W * h)) - 1)
    return text[:n].rstrip() + "…", h


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


def sheet_revision_label(project: Project, sheet: Sheet) -> str:
    """Revize listu do popisového pole a QR: revize listu (`revision.sheet_revision`). Nezměněný list bez výchozí
    revize před první revizí se značkami → prázdná (výchozí stav, ne nová revize). Projekt bez značek revizí
    (revize se po listech nesledují) → `meta["revision"]`."""
    from envocad.model.revision import revisions_marked, sheet_revision
    rev = sheet_revision(project, sheet)
    if rev is not None:
        return rev.label
    if revisions_marked(project):
        return ""
    return str(project.meta.get("revision", "") or "")


def qr_text(project: Project, sheet: Sheet, view: str = "") -> str:
    m = project.meta
    parts = [project.name, m.get("order", ""), sheet.name + (f" – {view}" if view else ""),
             f"rev. {sheet_revision_label(project, sheet) or '0'}"]
    return " | ".join(x for x in parts if x)


def sheet_number(project: Project, sheet: Sheet) -> str:
    ids = [s.id for s in project.sheets]
    i = ids.index(sheet.id) + 1 if sheet.id in ids else 0
    return f"{i}/{len(ids)}"


def page_label(project: Project, sheet: Sheet, k: int, n: int) -> str:
    """„Číslo listu“ strany odvozeného pohledu (vícepól, plán svorkovnice): číslo listu projektu a u více stran
    „str. k/n“ v rámci listu („3/7, str. 2/4“)."""
    no = sheet_number(project, sheet)
    return f"{no}, str. {k + 1}/{n}" if n > 1 else no


def title_rows(project: Project, sheet: Sheet, view: str = "", page: str = "", paper: str = ""
               ) -> list[list[tuple[str, str]]]:
    """Řádky popisového pole jako [(popisek, hodnota), …] – vlevo doleva, vpravo doprava. `paper` = formát strany
    odvozeného pohledu (vícepól na A4), jinak formát listu."""
    m = project.meta
    date = m.get("date") or _datetime.now().astimezone().strftime("%d.%m.%Y")   # dnešní datum v místním čase
    name = sheet.name + (f" – {view}" if view else "")
    return [
        [("Projekt", project.name), ("Zakázka", m.get("order", ""))],
        [("Investor", m.get("investor", "")), ("Místo", m.get("place", ""))],
        [("List", name), ("Číslo listu", page or sheet_number(project, sheet))],
        [("Zpracoval", m.get("author", "")), ("Datum", date), ("Revize", sheet_revision_label(project, sheet)),
         ("Formát", paper or sheet.paper)],
    ]


QR_SIZE = TB_H - 6.0   # QR kód vlevo od popisového pole (strana čtverce)
QR_GAP = 4.0           # mezera QR kódu od popisového pole


def qr_fits(width: float) -> bool:
    """Vejde se QR kód vlevo od popisového pole do vnitřního rámečku? (A4 na výšku: popisové pole 180 mm vyplní
    celou šířku kreslicí plochy, QR se vynechá – identifikace je v popisovém poli.)"""
    return width - MARGIN - TB_W - QR_SIZE - QR_GAP >= MARGIN_LEFT


def frame_geometry(project: Project, sheet: Sheet, width: float | None = None, height: float | None = None,
                   view: str = "", page: str = "", paper: str = "") -> FrameGeometry:
    """Rámeček s popisovým polem vpravo dole. Pro odvozené pohledy (vícepól) lze zadat jiný rozměr listu a jeho
    formát (`paper`) do popisového pole. QR kód jen, když se vlevo od popisového pole vejde (`qr_fits`)."""
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
    rows = title_rows(project, sheet, view, page, paper)
    rh = TB_H / len(rows)
    logo_w = 34.0
    g.lines.append((tx0 + logo_w, ty0, tx0 + logo_w, ty1))
    short, full = company_names()
    g.texts.append((tx0 + logo_w / 2, ty0 + TB_H / 2 - 2.0, *fit_text(short, logo_w - 3.0, 5.0, 2.5), "center"))
    g.texts.append((tx0 + logo_w / 2, ty0 + TB_H / 2 - 6.0, *fit_text(full, logo_w - 2.0, 1.8, 1.2), "center"))
    # QR kód s identifikací výkresu vlevo od popisového pole (projekt | zakázka | list | revize)
    mods = qr_modules(qr_text(project, sheet, view)) if qr_fits(w) else None
    if mods:
        n = len(mods)
        size = QR_SIZE
        cell = size / n
        qx0, qy0 = tx0 - size - QR_GAP, ty0 + 3.0
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
            # dlouhá hodnota se zmenší, případně zkrátí s „…“ – nepřetéká do sousední buňky
            g.texts.append((cx + 1.0, top - rh + 1.3, *fit_text(str(value or ""), colw - 2.0, 2.5 if r < 3 else 2.2),
                            "left"))
    return g


# ---- rozmístění obsahu na list (generátor) ----------------------------------------------------------------------
PAPER_SIZES = (("A3", 420.0, 297.0), ("A2", 594.0, 420.0), ("A1", 841.0, 594.0), ("A0", 1189.0, 841.0))
CONTENT_PAD = 5.0     # odstup obsahu od vnitřního rámečku a od popisového pole


def inner_box(width: float, height: float) -> tuple[float, float, float, float]:
    """Vnitřní rámeček (kreslicí plocha) listu daného rozměru: x0, y0, x1, y1 (mm, Y nahoru)."""
    return (MARGIN_LEFT, MARGIN, width - MARGIN, height - MARGIN)


def title_block_box(width: float, height: float) -> tuple[float, float, float, float]:
    """Obálka popisového pole včetně QR kódu vlevo od něj (vpravo dole uvnitř rámečku; QR jen, když se vejde)."""
    del height
    qr = QR_SIZE + QR_GAP if qr_fits(width) else 0.0
    return (width - MARGIN - TB_W - qr, MARGIN, width - MARGIN, MARGIN + TB_H)


def _snap(v: float) -> float:
    return round(v / 2.5) * 2.5


def _boxes_hit(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def fit_placement(boxes: list, sizes=None) -> tuple[str, float, float, float, float]:
    """Nejmenší formát (A3…A0, na šířku i na výšku), do jehož vnitřního rámečku se obsah (`boxes`) vejde
    s odstupem `CONTENT_PAD` a nezasahuje do popisového pole; jinak vlastní rozměr. Vrací (formát, šířka, výška,
    dx, dy) – posun obsahu v násobcích mřížky 2,5 mm (obsah na středu, kvůli popisovému poli případně výš)."""
    x1 = min(b[0] for b in boxes)
    y1 = min(b[1] for b in boxes)
    x2 = max(b[2] for b in boxes)
    y2 = max(b[3] for b in boxes)
    bw, bh = x2 - x1, y2 - y1
    pad = CONTENT_PAD
    cands = []
    for name, w, h in (sizes or PAPER_SIZES):
        cands += [(w * h, 0, name, w, h), (w * h, 1, name, h, w)]
    cands.sort()
    custom_w = max(420.0, -(-(bw + MARGIN_LEFT + MARGIN + 2 * pad + 2.5) // 5) * 5)
    custom_h = max(297.0, -(-(bh + 2 * MARGIN + 3 * pad + TB_H + 2.5) // 5) * 5)
    for _, _, name, w, h in [*cands, (0, 0, "vlastní", custom_w, custom_h)]:
        ix0, iy0, ix1, iy1 = inner_box(w, h)
        ix0, iy0, ix1, iy1 = ix0 + pad, iy0 + pad, ix1 - pad, iy1 - pad
        if bw > ix1 - ix0 - 2.5 or bh > iy1 - iy0 - 2.5:
            continue
        dx = _snap((ix0 + ix1) / 2 - (x1 + x2) / 2)
        dy = _snap((iy0 + iy1) / 2 - (y1 + y2) / 2)
        tb = title_block_box(w, h)
        tb = (tb[0] - pad, tb[1] - pad, tb[2] + pad, tb[3] + pad)
        need = max((tb[3] - (b[1] + dy) for b in boxes
                    if _boxes_hit((b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy), tb)), default=0.0)
        if need > 0:
            dy += -(-need // 2.5) * 2.5
            if y2 + dy > iy1:
                continue
        return name, w, h, dx, dy
    raise AssertionError("vlastní formát se vejde vždy")   # pragma: no cover


def apply_placement(sheet: Sheet, placement: tuple[str, float, float, float, float]) -> None:
    """Nastaví listu formát z `fit_placement` a posune všechny prvky, lomy vodičů a volné texty o (dx, dy)."""
    name, w, h, dx, dy = placement
    sheet.paper, sheet.width, sheet.height = name, w, h
    for e in sheet.elements:
        e.x, e.y = e.x + dx, e.y + dy
    for wire in sheet.wires:
        wire.points = [(x + dx, y + dy) for x, y in wire.points]
    for t in sheet.texts:          # volné texty listu (hranice vlastnictví v blokovém schématu) s obsahem
        t.x, t.y = t.x + dx, t.y + dy


def fit_sheet_to_content(project: Project, sheet: Sheet, lib, sizes=None) -> None:
    """Zvolí formát listu podle obsahu (`fit_placement`, `sizes` = povolené formáty, jinak A3…A0) a posune všechny
    prvky a lomy vodičů tak, aby obsah (značky, popisky, vodiče) ležel celý uvnitř vnitřního rámečku a mimo popisové
    pole – i při zapnutém rámečku."""
    from envocad.model.textlayout import sheet_content_boxes
    boxes = sheet_content_boxes(project, sheet, lib)
    if not boxes:
        return
    apply_placement(sheet, fit_placement(boxes, sizes))


def _fits_unmoved(boxes: list, w: float, h: float) -> bool:
    ix0, iy0, ix1, iy1 = inner_box(w, h)
    pad = CONTENT_PAD
    if any(b[0] < ix0 + pad or b[1] < iy0 + pad or b[2] > ix1 - pad or b[3] > iy1 - pad for b in boxes):
        return False
    tb = title_block_box(w, h)
    tb = (tb[0] - pad, tb[1] - pad, tb[2] + pad, tb[3] + pad)
    return not any(_boxes_hit(b, tb) for b in boxes)


def grow_sheet_to_content(project: Project, sheet: Sheet, lib) -> bool:
    """Zvětší formát listu, když obsah přetéká vnitřní rámeček nebo leží v popisovém poli (např. DC rozvaděč
    s 9 stringy po 50 mm na A3). Obsah, který se vejde, se nemění (formát ani polohy); jinak nejmenší větší formát
    na šířku (A3…A0), do kterého se obsah vejde bez posunu, a teprve když žádný, `fit_sheet_to_content` (s posunem).
    Nikdy nezmenšuje. Vrací True, když se list změnil.

    List rozvaděče bez volby formátu vícepólu (`mp_paper`) ji dostane podle stavu před zvětšením (firemní standard,
    A4) – jiný formát listu by jinak přepnul vícepól a plán svorkovnice na rozměr listu (`multipole.paper_choice`)."""
    from envocad.model.textlayout import sheet_content_boxes
    boxes = sheet_content_boxes(project, sheet, lib)
    if not boxes or _fits_unmoved(boxes, sheet.width, sheet.height):
        return False
    if sheet.is_switchboard and not getattr(sheet, "mp_paper", ""):
        from envocad.model.multipole import paper_choice
        sheet.mp_paper = paper_choice(sheet)
    for name, w, h in PAPER_SIZES:
        if w * h <= sheet.width * sheet.height + 1e-6:
            continue
        if _fits_unmoved(boxes, w, h):
            sheet.paper, sheet.width, sheet.height = name, w, h
            return True
    apply_placement(sheet, fit_placement(boxes))
    return True


# prodloužené formáty ISO 5457 na šířku podle výšky listu: (název, šířka) od nejužšího
LONG_PAPERS = {
    297.0: (("A4×3", 630.0), ("A4×4", 841.0), ("A4×5", 1051.0), ("A4×6", 1261.0), ("A4×7", 1471.0),
            ("A4×8", 1682.0), ("A4×9", 1892.0)),
    420.0: (("A3×3", 891.0), ("A3×4", 1189.0), ("A3×5", 1486.0), ("A3×6", 1783.0), ("A3×7", 2080.0)),
}


def grow_sheet_long(project: Project, sheet: Sheet, lib) -> bool:
    """Zvětší list jen do šířky (prodloužený formát na šířku, ISO 5457 A4×n / A3×n se stejnou výškou), když obsah
    přetéká jen vpravo a na výšku se vejde – široký list rozvaděče (RFVE s mnoha stringy) pak nedostane A0. Obsah se
    neposouvá. False = list se vejde beze změny, výška nemá prodloužený formát nebo obsah přetéká i jinam."""
    from envocad.model.textlayout import sheet_content_boxes
    sizes = LONG_PAPERS.get(float(sheet.height))
    boxes = sheet_content_boxes(project, sheet, lib)
    if sizes is None or not boxes or _fits_unmoved(boxes, sheet.width, sheet.height):
        return False
    for name, w in sizes:
        if w > sheet.width + 1e-6 and _fits_unmoved(boxes, w, sheet.height):
            if sheet.is_switchboard and not getattr(sheet, "mp_paper", ""):
                from envocad.model.multipole import paper_choice
                sheet.mp_paper = paper_choice(sheet)
            sheet.paper, sheet.width = name, w
            return True
    return False


def paper_exceeds(name: str, limit: str) -> bool:
    """Je formát `name` (z `fit_placement`) větší než `limit` („A2“)? Vlastní formát je větší vždy; neznámý limit = A2."""
    order = [n for n, _, _ in PAPER_SIZES]
    if limit not in order:
        limit = "A2"
    return name not in order or order.index(name) > order.index(limit)
