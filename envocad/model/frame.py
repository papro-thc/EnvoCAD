"""Rámeček listu a popisové pole ENVO (razítko podle „Razítko fixed.dwg“) – čistá geometrie (mm, Y nahoru), kreslí
ji Qt i DXF export stejně."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime as _datetime

from envocad.model.grid import snap as _snap
from envocad.model.project import Project, Sheet

MARGIN = 10.0        # okraj rámečku
MARGIN_LEFT = 20.0   # širší okraj pro vazbu
TB_W, TB_H = 180.0, 32.0  # popisové pole (š × v)
# výchozí název firmy; `standard.company` z ~/.envocad/settings.json čte `envocad.settings.company` a volající ho
# předá parametrem `company` (model nastavení nečte). Zapnutí rámečku: `envocad.settings.frame_enabled`.
COMPANY = "ENVO s.r.o."


def company_names(company: str = COMPANY) -> tuple[str, str]:
    """(krátký název do loga, plný název firmy) z názvu firmy firemního standardu (prázdný → `COMPANY`)."""
    full = (str(company or "").strip() or COMPANY)
    short = full.split()[0].rstrip(",")
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
    polys: list[tuple[list[tuple[float, float]], str]] = field(default_factory=list)  # vyplněné mnohoúhelníky (logo), barva


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


def sheet_revision_label(project: Project, sheet: Sheet) -> str:
    """Revize listu do popisového pole: revize listu (`revision.sheet_revision`). Nezměněný list bez výchozí
    revize před první revizí se značkami → prázdná (výchozí stav, ne nová revize). Projekt bez značek revizí
    (revize se po listech nesledují) → `meta["revision"]`."""
    from envocad.model.revision import revisions_marked, sheet_revision
    rev = sheet_revision(project, sheet)
    if rev is not None:
        return rev.label
    if revisions_marked(project):
        return ""
    return str(project.meta.get("revision", "") or "")


def sheet_number(project: Project, sheet: Sheet) -> str:
    ids = [s.id for s in project.sheets]
    i = ids.index(sheet.id) + 1 if sheet.id in ids else 0
    return f"{i}/{len(ids)}"


DOC_PAGES_KEY = "doc_pages"   # meta: strany celé dokumentace (JSON {"total": N, "pages": {"pohled:id listu:k": n}})


def doc_page_key(view: str, sheet_id: str, k: int = 0) -> str:
    """Klíč strany v `meta["doc_pages"]`: pohled (schematic | multipole | terminals | single_line), id listu, strana."""
    return f"{view}:{sheet_id}:{k}"


def doc_page(project: Project, sheet_id: str, view: str = "schematic", k: int = 0) -> str:
    """„Strana n/N“ celé dokumentace pro popisové pole – z čísel stran uložených při exportu dokumentace (nebo
    příkazem Přečíslovat strany dokumentace); neznámá strana (nový list od posledního číslování) = ""."""
    import json
    try:
        data = json.loads(project.meta.get(DOC_PAGES_KEY) or "{}")
        n = data.get("pages", {}).get(doc_page_key(view, sheet_id, k))
        return f"{int(n)}/{int(data['total'])}" if n else ""
    except (ValueError, TypeError, KeyError, AttributeError):
        return ""


def page_label(project: Project, sheet: Sheet, k: int, n: int) -> str:
    """„Číslo listu“ strany odvozeného pohledu (vícepól, plán svorkovnice): číslo listu projektu a u více stran
    „str. k/n“ v rámci listu („3/7, str. 2/4“)."""
    no = sheet_number(project, sheet)
    return f"{no}, str. {k + 1}/{n}" if n > 1 else no


# Razítko ENVO (podle „Razítko fixed.dwg“, blok RAZITKO_FVE 185 × 85 mm) zhuštěné do popisového pole TB_W × TB_H:
# vlevo logo s adresou, uprostřed stavba / investor, místo / 2 řádky osob / název výkresu, vpravo údaje výkresu.
STAMP_LOGO_W = 32.0                    # sloupec loga
STAMP_RIGHT_W = 58.0                   # sloupec údajů výkresu (popisek | hodnota)
STAMP_RIGHT_LABEL_W = 21.0
STAMP_WIDE_PAD = 14.0                  # rezerva vpravo u buněk přes celý prostředek (stavba, název výkresu)
STAMP_MID_ROWS = (7.0, 6.0, 5.0, 5.0, 9.0)  # stavba | investor, místo | 2 × osoby | název výkresu (součet = TB_H)
ENVO_ADDRESS = ("Bělehradská 858/23", "120 00 Praha 2")
# klíče `Project.meta` údajů razítka navíc k investor / place / order / author / date (Soubor → Vlastnosti projektu)
STAMP_META = (("approved", "Schválil"), ("responsible", "Zodp. projektant"), ("coordinator", "Koordinátor"),
              ("stage", "Stupeň"), ("archive", "Archivní číslo"), ("scale", "Měřítko"))


def stamp_fields(project: Project, sheet: Sheet, view: str = "", page: str = "", paper: str = "", doc: str = ""
                 ) -> dict[str, list[tuple[str, str]]]:
    """Údaje razítka po skupinách: „stavba“, „misto“ (investor, místo), „osoby“, „osoby2“, „nazev“ (uprostřed) a „vykres“
    (vpravo pod sebou). `paper` = formát strany odvozeného pohledu (vícepól na A4), jinak formát listu. Číslo
    výkresu = číslo listu (sedí s křížovými odkazy „/3.B4“), s `doc` i strana celé dokumentace („3/7 · str. 5/28“)."""
    m = project.meta
    date = m.get("date") or _datetime.now().astimezone().strftime("%d.%m.%Y")   # dnešní datum v místním čase
    name = sheet.name + (f" – {view}" if view else "")
    number = page or sheet_number(project, sheet)
    if doc:
        number = f"{number} · str. {doc}"
    return {
        "stavba": [("Stavba", project.name)],
        "misto": [("Investor", m.get("investor", "")), ("Místo", m.get("place", ""))],
        "osoby": [("Vypracoval", m.get("author", "")), ("Schválil", m.get("approved", ""))],
        "osoby2": [("Zodpovědný projektant", m.get("responsible", "")), ("Koordinátor projektu", m.get("coordinator", ""))],
        "nazev": [("Název", name)],
        "vykres": [("Stupeň", m.get("stage", "")), ("Zakázkové číslo", m.get("order", "")),
                   ("Archivní číslo", m.get("archive", "")), ("Datum", date), ("Formát", paper or sheet.paper),
                   ("Měřítko", m.get("scale", "") or "–"), ("Revize", sheet_revision_label(project, sheet)),
                   ("Číslo výkresu", number)],
    }


def title_rows(project: Project, sheet: Sheet, view: str = "", page: str = "", paper: str = "", doc: str = ""
               ) -> list[list[tuple[str, str]]]:
    """Údaje razítka jako řádky [(popisek, hodnota), …] (`stamp_fields` po skupinách) – pro výpisy a testy."""
    return list(stamp_fields(project, sheet, view, page, paper, doc).values())


_LOGO: dict | None = None


def envo_logo() -> dict | None:
    """Logo ENVO z razítka (`resources/envo_logo.json`: šířka, výška, mnohoúhelníky s barvou), nebo None."""
    global _LOGO
    if _LOGO is None:
        import json
        from pathlib import Path
        try:
            _LOGO = json.loads((Path(__file__).resolve().parent.parent / "resources" / "envo_logo.json")
                               .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _LOGO = {}
    return _LOGO or None


def _stamp(g: FrameGeometry, tx0: float, ty0: float, fields: dict, company: str) -> None:
    """Razítko do popisového pole s levým dolním rohem (tx0, ty0)."""
    tx1, ty1 = tx0 + TB_W, ty0 + TB_H
    xm, xr = tx0 + STAMP_LOGO_W, tx1 - STAMP_RIGHT_W
    g.lines += [(xm, ty0, xm, ty1), (xr, ty0, xr, ty1)]
    # logo: ENVO s adresou (jako v razítku), jiná firma = název textem
    short, full = company_names(company)
    logo = envo_logo() if short.upper() == "ENVO" else None
    cx = tx0 + STAMP_LOGO_W / 2
    if logo:
        sc = (STAMP_LOGO_W - 6.0) / logo["width"]
        lx, ly = cx - logo["width"] * sc / 2, ty0 + TB_H / 2 - logo["height"] * sc / 2 + 1.0
        for poly in logo["polygons"]:
            g.polys.append(([(lx + x * sc, ly + y * sc) for x, y in poly["points"]], poly["color"]))
        g.texts.append((cx, ty1 - 4.0, "Projektant profese", 1.5, "center"))
        g.texts.append((cx, ty0 + 4.6, ENVO_ADDRESS[0], 1.5, "center"))
        g.texts.append((cx, ty0 + 2.0, ENVO_ADDRESS[1], 1.5, "center"))
    else:
        g.texts.append((cx, ty0 + TB_H / 2 - 2.0, *fit_text(short, STAMP_LOGO_W - 3.0, 5.0, 2.5), "center"))
        g.texts.append((cx, ty0 + TB_H / 2 - 6.0, *fit_text(full, STAMP_LOGO_W - 2.0, 1.8, 1.2), "center"))
    # prostředek: řádky stavba / investor + místo / osoby / název výkresu, buňky v řádku stejně široké
    value_h = {"stavba": 3.0, "misto": 2.2, "osoby": 1.9, "osoby2": 1.9, "nazev": 3.2}
    top = ty1
    for key, rh in zip(("stavba", "misto", "osoby", "osoby2", "nazev"), STAMP_MID_ROWS):
        cells = fields[key]
        if top < ty1:
            g.lines.append((xm, top, xr, top))
        colw = (xr - xm) / len(cells)
        for c, (label, value) in enumerate(cells):
            x = xm + c * colw
            if c:
                g.lines.append((x, top - rh, x, top))
            g.texts.append((x + 1.0, top - 1.8, label, 1.3, "left"))
            # dlouhá hodnota se zmenší, případně zkrátí s „…“ – nepřetéká do sousední buňky
            # jediná buňka v řádku (stavba, název) – rezerva vpravo, ať text nesahá k údajům výkresu ani při širším písmu
            room = colw - 2.0 - (STAMP_WIDE_PAD if len(cells) == 1 else 0.0)
            g.texts.append((x + 1.0, top - rh + 0.9, *fit_text(str(value or ""), room, value_h[key]), "left"))
        top -= rh
    # vpravo: údaje výkresu pod sebou (popisek | hodnota)
    rows = fields["vykres"]
    rh = TB_H / len(rows)
    xv = xr + STAMP_RIGHT_LABEL_W
    g.lines.append((xv, ty0, xv, ty1))
    for r, (label, value) in enumerate(rows):
        top = ty1 - r * rh
        if r:
            g.lines.append((xr, top, tx1, top))
        g.texts.append((xr + 1.0, top - rh + 1.0, *fit_text(label, STAMP_RIGHT_LABEL_W - 2.0, 1.6, 1.2), "left"))
        g.texts.append((xv + 1.0, top - rh + 0.9, *fit_text(str(value or ""), tx1 - xv - 2.0, 2.0), "left"))


def frame_geometry(project: Project, sheet: Sheet, width: float | None = None, height: float | None = None,
                   view: str = "", page: str = "", paper: str = "", company: str = COMPANY,
                   doc: str | None = None) -> FrameGeometry:
    """Rámeček s popisovým polem vpravo dole. Pro odvozené pohledy (vícepól) lze zadat jiný rozměr listu a jeho
    formát (`paper`) do popisového pole. `doc` = strana celé dokumentace; None = podle uložených čísel stran
    (`doc_page`, pohled listu JPS). `company`
    = název firmy do loga (firemní standard, `envocad.settings.company`)."""
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
    if doc is None:
        doc = doc_page(project, sheet.id) if not sheet.is_switchboard else ""
    _stamp(g, tx0, ty0, stamp_fields(project, sheet, view, page, paper, doc), company)
    return g


# ---- rozmístění obsahu na list (generátor) ----------------------------------------------------------------------
PAPER_SIZES = (("A3", 420.0, 297.0), ("A2", 594.0, 420.0), ("A1", 841.0, 594.0), ("A0", 1189.0, 841.0))
CONTENT_PAD = 5.0     # odstup obsahu od vnitřního rámečku a od popisového pole


def inner_box(width: float, height: float) -> tuple[float, float, float, float]:
    """Vnitřní rámeček (kreslicí plocha) listu daného rozměru: x0, y0, x1, y1 (mm, Y nahoru)."""
    return (MARGIN_LEFT, MARGIN, width - MARGIN, height - MARGIN)


def title_block_box(width: float, height: float) -> tuple[float, float, float, float]:
    """Obálka popisového pole (razítka) vpravo dole uvnitř rámečku."""
    del height
    return (width - MARGIN - TB_W, MARGIN, width - MARGIN, MARGIN + TB_H)



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


def grow_sheet_to_content(project: Project, sheet: Sheet, lib, boxes: list | None = None, *,
                          standard_paper: str) -> bool:
    """Zvětší formát listu, když obsah přetéká vnitřní rámeček nebo leží v popisovém poli (např. DC rozvaděč
    s 9 stringy po 50 mm na A3). Obsah, který se vejde, se nemění (formát ani polohy); jinak nejmenší větší formát
    na šířku (A3…A0), do kterého se obsah vejde bez posunu, a teprve když žádný, `fit_sheet_to_content` (s posunem).
    Nikdy nezmenšuje. Vrací True, když se list změnil.

    List rozvaděče bez volby formátu vícepólu (`mp_paper`) ji dostane podle stavu před zvětšením (firemní standard
    `standard_paper` od volajícího, výchozí A4) – jiný formát listu by jinak přepnul vícepól a plán svorkovnice na
    rozměr listu (`multipole.paper_choice`). `boxes` = obálky obsahu (`sheet_content_boxes`), když je volající už má."""
    from envocad.model.textlayout import sheet_content_boxes
    if boxes is None:
        boxes = sheet_content_boxes(project, sheet, lib)
    if not boxes or _fits_unmoved(boxes, sheet.width, sheet.height):
        return False
    if sheet.is_switchboard and not getattr(sheet, "mp_paper", ""):
        from envocad.model.multipole import paper_choice
        sheet.mp_paper = paper_choice(sheet, standard_paper)
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


def grow_sheet_long(project: Project, sheet: Sheet, lib, boxes: list | None = None, *,
                    standard_paper: str) -> bool:
    """Zvětší list jen do šířky (prodloužený formát na šířku, ISO 5457 A4×n / A3×n se stejnou výškou), když obsah
    přetéká jen vpravo a na výšku se vejde – široký list rozvaděče (RFVE s mnoha stringy) pak nedostane A0. Obsah se
    neposouvá. False = list se vejde beze změny, výška nemá prodloužený formát nebo obsah přetéká i jinam (list se
    pak nezmění). `boxes` a `standard_paper` jako u `grow_sheet_to_content`; obálky se počítají, jen když má výška
    prodloužený formát."""
    from envocad.model.textlayout import sheet_content_boxes
    sizes = LONG_PAPERS.get(float(sheet.height))
    if sizes is None:
        return False
    if boxes is None:
        boxes = sheet_content_boxes(project, sheet, lib)
    if not boxes or _fits_unmoved(boxes, sheet.width, sheet.height):
        return False
    for name, w in sizes:
        if w > sheet.width + 1e-6 and _fits_unmoved(boxes, w, sheet.height):
            if sheet.is_switchboard and not getattr(sheet, "mp_paper", ""):
                from envocad.model.multipole import paper_choice
                sheet.mp_paper = paper_choice(sheet, standard_paper)
            sheet.paper, sheet.width = name, w
            return True
    return False


# formát listu volený uživatelem (vlastnosti listu): pevné formáty na šířku a volný A4 (výška 297, šířka n × 210)
SHEET_FORMATS = {"A4": (297.0, 210.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0), "A1": (841.0, 594.0)}
FREE_A4_MAX = 40          # nejvýš A4×40 (8,4 m) – volný A4 se dál nerozšiřuje


def sheet_format(sheet: Sheet) -> str:
    """Formát listu pro volbu ve vlastnostech: „A4“…„A1“, „volný A4“ (výška 297, název A4×n), jinak "" (jiný)."""
    from envocad.model.multipole import FREE_A4
    size = SHEET_FORMATS.get(sheet.paper)
    if size and (float(sheet.width), float(sheet.height)) == size:
        return sheet.paper
    if float(sheet.height) == 297.0 and str(sheet.paper).startswith("A4×"):
        return FREE_A4
    return ""


def sheet_format_placement(project: Project, sheet: Sheet, lib, choice: str
                           ) -> tuple[str, float, float, float, float]:
    """Formát listu pro volbu ve vlastnostech jako (název, šířka, výška, dx, dy) pro `apply_placement`. Pevný formát
    (A4…A1 na šířku) obsah neposouvá. Volný A4: nejmenší A4×n (výška 297, šířka n × 210 mm), do kterého se obsah
    listu vejde mimo popisové pole – bez posunu, když to jde, jinak s posunem jako `fit_placement` (na mřížku);
    obsah vyšší než strana (nevejde se ani na A4×40) → ValueError s českou hláškou. Prázdný list = A4×2."""
    from envocad.model.multipole import FREE_A4, FREE_A4_HEIGHT, FREE_A4_STEP, free_a4_label
    if choice in SHEET_FORMATS:
        return (choice, *SHEET_FORMATS[choice], 0.0, 0.0)
    if choice != FREE_A4:
        raise ValueError(f"Neznámý formát listu {choice!r}")
    from envocad.model.textlayout import sheet_content_boxes
    boxes = sheet_content_boxes(project, sheet, lib)
    h = FREE_A4_HEIGHT
    if not boxes:
        return (free_a4_label(2 * FREE_A4_STEP), 2 * FREE_A4_STEP, h, 0.0, 0.0)
    for k in range(1, FREE_A4_MAX + 1):
        w = k * FREE_A4_STEP
        if _fits_unmoved(boxes, w, h):
            return (free_a4_label(w), w, h, 0.0, 0.0)
        name, pw, ph, dx, dy = fit_placement(boxes, [(free_a4_label(w), w, h)])
        if (pw, ph) == (w, h):
            return (name, w, h, dx, dy)
    raise ValueError("Obsah listu je vyšší než 297 mm – volný A4 (výška 297 mm) nejde použít; zvol A3, A2 nebo A1")


def sheet_format_size(project: Project, sheet: Sheet, lib, choice: str) -> tuple[str, float, float]:
    """(název, šířka, výška) listu pro zvolený formát (`sheet_format_placement` bez posunu)."""
    return sheet_format_placement(project, sheet, lib, choice)[:3]


def paper_exceeds(name: str, limit: str) -> bool:
    """Je formát `name` (z `fit_placement`) větší než `limit` („A2“)? Vlastní formát je větší vždy; neznámý limit = A2."""
    order = [n for n, _, _ in PAPER_SIZES]
    if limit not in order:
        limit = "A2"
    return name not in order or order.index(name) > order.index(limit)
