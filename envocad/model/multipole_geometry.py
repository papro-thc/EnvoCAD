"""Geometrie vícepólového pohledu bez Qt – texty a čáry tak, jak je kreslí `ui/multipole_view.py`, pro kontrolu
překryvů textů ve vícepólu (`checks.text_findings`) a kreslicí seznam `MultipoleGeometry.prims` pro export DXF
(`export/dxf_export.export_multipole_dxf`).

Rozmístění, stránkování, popisky prvků a trasy žil se počítají sdílenými funkcemi z `model/multipole.py`
(`auto_layout`, `paginate`, `pole_label_lines`, `conductor_route`), které používá i scéna – kontrola tedy vidí
stejný výkres. Obálky textů jsou odhad podle `textlayout.text_box` (průměrná šířka znaku).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

from envocad.model import multipole as mp
from envocad.model.designation import element_name
from envocad.model.project import Project, Sheet, element_symbol, linked_wire, switchboard_title, wire_label
from envocad.model.symbol import rotate_dir, rotate_point
from envocad.model.textlayout import (
    CHAR_W,
    GAP,
    Box,
    _IndexGrid,
    boxes_overlap,
    segment_hits_box,
    symbol_segments,
    symbol_text_boxes,
    text_box,
)

Point = tuple[float, float]
Seg = tuple[Point, Point]
BUS = "sb.busbar"
BUS_PITCH = 5.0       # rozteč čar potenciálů sběrnice (jako `multipole_view.BUS_PITCH`)
TAG_ROW = 3.2         # řádek štítku kabelu (`CableTagItem.ROW`)
END_TEXT_OFFSET = {"E": (1.5, 0.8), "W": (-1.5, 0.8), "N": (0.8, 1.5), "S": (0.8, -3.0)}


@dataclass
class _At:
    """Prvek posunutý na místo pólu ve vícepólu (pro `symbol_segments` / `symbol_text_boxes`)."""
    x: float
    y: float
    rotation: int


@dataclass
class Rail:
    """Sběrná čára jedné strany: žíly z více stran do jednoho pólu (PE stringů do XPE) se na každé straně spojí
    do vodorovné čáry, která pokračuje přes strany s jedním přerušením a odkazem na každém okraji."""
    page: int
    y: float                                     # výška čáry (souřadnice pohledu, strany pod sebou)
    x0: float
    x1: float
    owner: str                                   # „id pólu#rail…“ – vlastník čar a odkazů (kontrola překryvů)
    conductor: str
    stub: tuple[Point, Point] | None = None      # svislý úsek od sběrného pólu k čáře (jen na jeho straně)
    dots: list[Point] = field(default_factory=list)                     # tečky odboček
    breaks: list[tuple[float, float, bool, str]] = field(default_factory=list)   # (x, y, vpravo, odkaz)


@dataclass(frozen=True)
class Prim:
    """Kreslicí primitivum vícepólu (jediný zdroj pro export bez Qt). Souřadnice jsou LOKÁLNÍ na straně `page`
    (mm, Y nahoru, počátek levý dolní roh strany) – strana k pohledu (strany pod sebou) = y + k·rozteč stran.

    kind: `line` (pts = 2 body), `poly` (lomená čára), `text` (pts = (bod,), `text`, `h`, `align`, `rot`),
    `dot` (plná tečka, pts = (střed,), `r`), `symbol` (značka pólu, pts = (počátek,), `rot`, `symbol`).
    `style` solid | dashed, `weight` thin | wire | bus | fan, `layer` = vrstva DXF (VODICE, SBERNICE, MUSTKY…)."""
    kind: str
    page: int
    pts: tuple[Point, ...] = ()
    text: str = ""
    h: float = 0.0
    align: str = "left"
    rot: float = 0.0
    r: float = 0.0
    layer: str = "VODICE"
    style: str = "solid"
    weight: str = "thin"
    symbol_id: str = ""
    symbol: object = field(default=None, compare=False, hash=False, repr=False)   # `Symbol` značky pólu


@dataclass
class MultipoleGeometry:
    texts: list[tuple[Box, str, str]] = field(default_factory=list)            # obálka, vlastník, popis
    lines: list[tuple[Point, Point, str, str]] = field(default_factory=list)   # úsečka, vlastník, popis
    pages: int = 1
    # popisky žil: (id vodiče, žíla, část) → (x, y, text, zarovnání); část 0 = žíla / úsek k přerušení na straně
    # zdroje, 1 = úsek za přerušením. Scéna je kreslí přesně tady (rozmístěné mimo cizí čáry a texty).
    conductor_labels: dict[tuple[str, str, int], tuple[float, float, str, str]] = field(default_factory=dict)
    origins: dict[str, Point] = field(default_factory=dict)    # prvek → poloha (po stránkování a posunu)
    page_of: dict[str, int] = field(default_factory=dict)      # prvek → strana
    layout_pos: dict[str, Point] = field(default_factory=dict)  # automatické rozmístění před stránkováním
    page_size: tuple[float, float] = (420.0, 297.0)            # rozměr strany (A4 na šířku = 297 × 210)
    paper: str = "A3"                                          # formát strany do popisového pole
    col_gap: float = mp.COL_GAP                                # mezera mezi sloupci po zhuštění na stranu
    # přerušení žíly na okraji strany: (id vodiče, žíla) → [(x, y, vpravo, odkaz) na straně zdroje, … na straně cíle]
    page_breaks: dict[tuple[str, str], list[tuple[float, float, bool, str]]] = field(default_factory=dict)
    # křížové odkazy na koncích čar sběrnice: id sběrnice → [(strana, x, y, text, zarovnání)]
    bus_refs: dict[str, list[tuple[int, float, float, str, str]]] = field(default_factory=dict)
    rails: list[Rail] = field(default_factory=list)              # sběrné čáry přes strany (PE stringů do XPE)
    bus_desc: dict[str, tuple[float, float, str]] = field(default_factory=dict)   # popis sběrnice: (x, y, zarovnání)
    # odbočka žíly ke sběrné čáře: (id vodiče, žíla) → (pól, směr portu, bod na čáře, směr u čáry, text svorky)
    rail_taps: dict[tuple[str, str], tuple[Point, str, Point, str, str]] = field(default_factory=dict)
    bridges: list[mp.Bridge] = field(default_factory=list)       # můstky svorkovnic po stranách (`bridge_paths`)
    bus_taps: dict[tuple[str, int], list[Point]] = field(default_factory=dict)   # (sběrnice, strana) → odbočky
    prims: list[Prim] = field(default_factory=list)              # kreslicí seznam (lokální souřadnice stran)

    @property
    def page_pitch(self) -> float:
        return self.page_size[1] + mp.MP_PAGE_GAP


TERMINAL_NUMBER = "číslo svorky"   # popis textu čísla svorky (kontrola překryvů ho bere bez tolerance)
TB_PAD = 2.5          # odstup kresby od popisového pole a QR kódu
BREAK_INSET = 4.0     # hrot šipky přerušení od vnitřního rámečku (odkaz je uvnitř rámečku před šipkou)
BREAK_TEXT_DX = 3.5   # odkaz přerušení: vodorovně od hrotu šipky (za křidélky šipky, směrem do strany)
REF_TEXT_DY = 0.7     # odkaz přerušení / sběrnice: základna nad čarou (text 1,8 mm se vejde mezi čáry po 2,5 mm)
REF_TEXT_H = 1.8
RAIL_BAR_SYMBOLS = {"sb.pe_bar"}   # lišta = jeden pól přes všechny svorky (sběrná čára z více stran)
RAIL_OFFSET = 7.5     # sběrná čára za svislým portem sběrného pólu (nad svorkami vývodů, ne přes jejich čísla)
BUS_REF_DY = -3.3     # odkaz sběrnice na sousední stranu: základna pod názvem potenciálu na konci čáry


TITLE_UNDERLINE = 0.72  # délka podtržení nadpisu na znak (× výška písma)
BUS_ARROW = (2.5, 1.2)  # šipka potenciálu na konci čáry sběrnice (délka, rozevření)


def break_arrow(x: float, y: float, at_right: bool) -> list[Seg]:
    """Šipka přerušení žíly s hrotem v x, y: vpravo ven na pozdější stranu, vlevo zpět na dřívější."""
    d = 1.0 if at_right else -1.0
    return [((x, y), (x - 3.0 * d, y + 2.0)), ((x, y), (x - 3.0 * d, y - 2.0))]


def bus_arrows(x0: float, x1: float, y: float) -> list[Seg]:
    """Šipky potenciálu na obou koncích čáry sběrnice."""
    ln, sp = BUS_ARROW
    return [((x, y), (x - ln * d, y + s * sp)) for x, d in ((x0, -1.0), (x1, 1.0)) for s in (1.0, -1.0)]


def title_underline(x: float, y: float, text: str, h: float) -> Seg:
    """Podtržení prvního řádku nadpisu rozvaděče (základna textu v y)."""
    return ((x, y - 1.0), (x + len(text) * h * TITLE_UNDERLINE, y - 1.0))


def page_prims(g: MultipoleGeometry, k: int) -> list[Prim]:
    """Primitiva strany k (lokální souřadnice strany)."""
    return [p for p in g.prims if p.page == k]


def break_text_pos(x: float, y: float, at_right: bool) -> tuple[float, float, str]:
    """Poloha odkazu u přerušení žíly (hrot šipky v x, y): nad žílou, před šipkou směrem dovnitř strany."""
    return (x - BREAK_TEXT_DX, y + REF_TEXT_DY, "right") if at_right else (x + BREAK_TEXT_DX, y + REF_TEXT_DY, "left")


def title_height(title: list[str]) -> float:
    """Výška nadpisu rozvaděče (první řádek 5 mm + podtržení, další po 3 mm)."""
    return 9.0 + 4.2 * max(len(title) - 1, 0) if title else 0.0


def _layout(sheet: Sheet, poles: dict[str, mp.ElementPoles], size: tuple[float, float], y_top: float,
            col_gap: float, info: dict) -> tuple[dict[str, Point], dict[str, int], int]:
    layout = mp.auto_layout(sheet, poles, x0=mp.layout_x0(sheet), y_top=y_top, bridges=sheet.bridges,
                            page_w=mp.page_width(sheet, size), col_gap=col_gap, info=info)
    for eid, ep in poles.items():
        ep.origin = layout.get(eid, (ep.element.x, ep.element.y))
    page_of, n_pages = mp.paginate(sheet, poles, size)
    return layout, page_of, n_pages


def multipole_geometry(project: Project, sheet: Sheet, lib) -> MultipoleGeometry:
    """Texty a čáry vícepólu listu rozvaděče (souřadnice pohledu, strany pod sebou).

    Strana má formát `multipole.paper_choice` (list rozvaděče výchozí A4 na šířku). Když kresba automaticky
    rozmístěných prvků sahá pod horní hranu popisového pole (s rámečkem i bez něj – rozmístění na zapnutí rámečku
    nezávisí), posune se nejdřív celé rozmístění nahoru (nejvýš pod nadpis rozvaděče) a pak se zmenší mezery mezi
    sloupci (nejvýš na `multipole.MIN_COL_GAP`). Posun i mezery jsou stejné na všech stranách (sběrnice zůstane
    ve stejné výšce). Výsledné polohy prvků jsou v `origins` – scéna (`ui/multipole_view.py`) je převezme, takže
    kreslí totéž."""
    from envocad.model.frame import MARGIN, TB_H
    choice = mp.paper_choice(sheet)
    size = mp.page_size(sheet, choice)
    poles: dict[str, mp.ElementPoles] = {}
    for e in sheet.elements:
        poles[e.id] = mp.element_poles(sheet, e, element_symbol(project, e, lib))
    title = switchboard_title(project, sheet)
    top_limit = size[1] - MARGIN - 4.0 - title_height(title) - TB_PAD
    bottom_limit = MARGIN + TB_H + TB_PAD
    y_top, gap = size[1] - mp.MP_Y_TOP, mp.COL_GAP
    for _attempt in range(4):
        info: dict = {}
        layout, page_of, n_pages = _layout(sheet, poles, size, y_top, gap, info)
        g = _build(project, sheet, poles, page_of, n_pages, size)
        if info.get("horizontal", True):
            break
        lo, hi = _auto_extent(g, poles, page_of, size[1])
        deficit = bottom_limit - lo
        if lo == float("inf") or deficit <= 0.01:
            break
        dy = max(0.0, min(deficit, top_limit - hi))
        dy = (dy // mp.GRID) * mp.GRID
        rest = deficit - dy
        new_gap = gap
        if rest > 0.01 and info.get("gaps"):
            new_gap = max(mp.MIN_COL_GAP, gap - -(-rest / info["gaps"] // 0.5) * 0.5)   # po 0,5 mm
        if dy <= 0 and new_gap >= gap:
            break
        y_top, gap = y_top + dy, new_gap
    g.origins = {eid: ep.origin for eid, ep in poles.items()}
    g.page_of = dict(page_of)
    g.layout_pos = dict(layout)
    g.paper = mp.page_paper_label(sheet, choice)
    g.col_gap = gap
    return g


def _auto_extent(g: MultipoleGeometry, poles, page_of: dict[str, int], height: float) -> tuple[float, float]:
    """Nejnižší a nejvyšší bod kresby automaticky rozmístěných prvků (souřadnice strany, přes všechny strany).
    Sběrnice a sběrné čáry se nepočítají (kreslí se i na jiných stranách a leží uvnitř rozmístění)."""
    pitch = height + mp.MP_PAGE_GAP
    auto = {eid for eid, ep in poles.items() if not ep.element.mp_pos and ep.element.symbol_id != BUS}
    lo, hi = float("inf"), float("-inf")
    for box, owner, _w in g.texts:
        eid, _, part = owner.partition("#")
        if eid in auto and not part.startswith("rail"):
            k = page_of.get(eid, 0) * pitch
            lo, hi = min(lo, box[1] + k), max(hi, box[3] + k)
    for a, b, owner, _w in g.lines:
        eid, _, part = owner.partition("#")
        if eid in auto and not part.startswith("rail"):
            k = page_of.get(eid, 0) * pitch
            lo, hi = min(lo, a[1] + k, b[1] + k), max(hi, a[1] + k, b[1] + k)
    return lo, hi


def _build(project: Project, sheet: Sheet, poles: dict[str, mp.ElementPoles], page_of: dict[str, int],
           n_pages: int, size: tuple[float, float]) -> MultipoleGeometry:
    from envocad.model.frame import MARGIN, MARGIN_LEFT, sheet_number
    g = MultipoleGeometry()
    g.pages = n_pages
    g.page_size = size
    W, H = size
    pitch = H + mp.MP_PAGE_GAP
    sheet_no = sheet_number(project, sheet).split("/")[0]

    def page_at(y: float) -> int:
        """Strana podle výšky – jen pro kresbu bez vlastníka na straně (nadpis, sběrné čáry); prvky a jejich žíly
        předávají stranu explicitně (`page_of`), prvek s ruční polohou nad horní hranou strany k ≥ 1 by jinak
        skončil na straně k − 1."""
        return max(0, min(n_pages - 1, int((H - y) // pitch)))

    def prim(kind: str, pts, page: int | None = None, **kw) -> None:
        """Primitivum do kreslicího seznamu: souřadnice pohledu → lokální souřadnice strany."""
        k = page_at(pts[0][1]) if page is None else page
        off = k * pitch
        g.prims.append(Prim(kind, k, tuple((x, y + off) for x, y in pts), **kw))

    def text(x: float, y: float, s: str, h: float, align: str, owner: str, what: str, layer: str = "TEXTY",
             page: int | None = None) -> None:
        if s:
            g.texts.append((text_box(x, y, s, h, align), owner, what))
            prim("text", ((x, y),), page, text=s, h=h, align=align, layer=layer)

    def line(a: Point, b: Point, owner: str, what: str, layer: str = "VODICE", weight: str = "thin",
             style: str = "solid", page: int | None = None, draw: bool = True) -> None:
        """Čára pro kontrolu překryvů (`g.lines`) a (s `draw`) i do kreslicího seznamu."""
        if a != b:
            g.lines.append((a, b, owner, what))
            if draw:
                prim("line", (a, b), page, layer=layer, weight=weight, style=style)

    def deco(a: Point, b: Point, layer: str, weight: str = "thin", page: int | None = None) -> None:
        """Jen kresba (šipky, oddělovače štítku, podtržení nadpisu) – kontrola překryvů ji nevidí."""
        if a != b:
            prim("line", (a, b), page, layer=layer, weight=weight)

    # prvky (póly, popisky, vazby, obtoky, příčky PE svodiče)
    for e in sheet.elements:
        ep = poles[e.id]
        if e.symbol_id == BUS:
            continue
        name = element_name(e)
        ke = page_of.get(e.id, 0)
        conds = list(ep.switched) if ep.per_pole else [None]
        for i, c in enumerate(conds):
            sym = mp.pole_symbol_for(ep, c)
            at = _At(*mp.pole_anchor(ep, c), e.rotation)
            for a, b in symbol_segments(at, sym):
                line(a, b, e.id, f"značku {name}", draw=False)
            for b in symbol_text_boxes(at, sym):
                g.texts.append((b, e.id, f"text značky {name}"))
            prim("symbol", ((at.x, at.y),), ke, rot=e.rotation, layer="SYMBOLY", symbol_id=e.symbol_id, symbol=sym)
            common = ep.symbol.common_symbol() if i == 0 and c is not None else None
            if common is not None:
                for a, b in symbol_segments(at, common):
                    line(a, b, e.id, f"značku {name}", draw=False)
                prim("symbol", ((at.x, at.y),), ke, rot=e.rotation, layer="SYMBOLY", symbol_id=e.symbol_id,
                     symbol=common)
            if c is not None and mp.is_terminal_block(e):
                num = mp.terminal_numbers(e, len(ep.slots))[ep.slot(c)] or "?"
                _x0, y0, x1, _y1 = sym.bounds()
                rx, ry = rotate_point(x1 + 1.0, y0 + 1.0, e.rotation)
                text(at.x + rx, at.y + ry, num, 2.0, "left", e.id, f"{TERMINAL_NUMBER} {name}", page=ke)
        for x, y, s, h, align in mp.pole_label_lines(ep):
            text(x, y, s, h, align, e.id, f"popisek {name}", page=ke)
        if ep.per_pole:
            if ep.symbol.pole_link and len(ep.switched) > 1:
                lx, ly = rotate_point(*ep.symbol.link_at, e.rotation)
                pts = [(ep.origin[0] + ep.pole_offset(c)[0] + lx, ep.origin[1] + ep.pole_offset(c)[1] + ly)
                       for c in ep.switched]
                line(pts[0], pts[-1], e.id, f"vazbu pólů {name}", layer="VAZBY", style="dashed", page=ke)
            for c in ep.bypass:
                a, b = ep.through
                line(ep.pole_pos(a, c), ep.pole_pos(b, c), e.id, f"žílu {c} kolem {name}", weight="wire", page=ke)
            for a, b in mp.pe_join_segments(ep):
                line(a, b, e.id, f"spojení PE {name}", weight="wire", page=ke)
        else:
            for port, cs in ep.per_port.items():
                if len(cs) >= 2:
                    last = max(cs, key=ep.slot)
                    line(ep.pole_pos(port, ep.slots[0]), ep.pole_pos(port, last), e.id, f"vývod {name}",
                         weight="fan", page=ke)

    # můstky svorkovnic (čárkovaně, s tečkami na svorkách) – i do kontroly překryvů
    g.bridges = mp.bridge_paths(sheet, poles, page_of)
    strip_owner: dict[str, str] = {}
    for e in sheet.elements:
        if mp.is_terminal_block(e):
            strip_owner.setdefault(e.ref, e.id)
    for bi, br in enumerate(g.bridges):
        owner = f"{strip_owner.get(br.strip, br.strip)}#bridge{bi}"
        for a, b in pairwise(br.pts):
            line(a, b, owner, f"můstek {br.strip}", layer="MUSTKY", style="dashed", page=br.page)
        for pt in br.pts:
            prim("dot", (pt,), br.page, r=0.5, layer="MUSTKY")

    # žíly
    breaks: dict[tuple[int, bool], int] = {}
    break_ys: dict[tuple[int, bool], set[float]] = {}
    bus_taps: dict[tuple[str, int], list[Point]] = {}

    pending: list[tuple[tuple[str, str, int], str, list[Point], str, bool]] = []
    label_page: dict[tuple[str, str, int], int] = {}     # strana popisku žíly = strana jejího úseku

    def conductor(w, c: str, idx: int, pa: Point, da: str, pb: Point, db: str, ends: tuple[str, str],
                  page: int, staggered: bool = False, part: int = 0) -> None:
        """Úsek žíly na straně `page` (strana prvku, ze kterého vede – ne podle výšky bodu)."""
        pts = mp.conductor_route(pa, da, pb, db, stagger=idx * mp.GRID, jog=0.8)
        what = f"žílu {c}" + (f" vodiče {w.attrs['ref']}" if w.attrs.get("ref") else "")
        owner = f"{w.id}#{c}"   # každá žíla zvlášť – popisek L− přes žílu L+ téhož vodiče je překryv
        for a, b in pairwise(pts):
            line(a, b, owner, what, draw=False)
        prim("poly", tuple(pts), page, weight="wire")
        label = c
        if idx == 0:
            lbl = wire_label(w.attrs)
            label = f"{lbl}  {c}" if lbl else c
        pending.append(((w.id, c, part), owner, pts, label, staggered))   # rozmístí se, až budou známé všechny čáry
        label_page[(w.id, c, part)] = page
        for t, (px, py), d in ((ends[0], pts[0], da), (ends[1], pts[-1], db)):
            if t:
                dx, dy = END_TEXT_OFFSET[d]
                text(px + dx, py + dy, t, 1.8, "right" if d == "W" else "left", owner, f"svorku {t}", page=page)

    def bus_y(ep: mp.ElementPoles, c: str, page: int) -> float:
        k0 = page_of.get(ep.element.id, 0)
        return ep.origin[1] + k0 * pitch - ep.slot(c) * BUS_PITCH - page * pitch

    rail_of = _rail_hubs(sheet, poles, page_of)
    rail_span: dict[tuple[str, str, str], tuple[int, int]] = {}         # sběrný pól → rozsah stran čáry
    wires_by_id = {w.id: w for w in sheet.wires}
    for (wid, _c), (key, side) in rail_of.items():
        w = wires_by_id[wid]
        ks = page_of.get(w.a.element_id if side == "a" else w.b.element_id, 0)
        k0, k1 = rail_span.get(key, (page_of.get(key[0], 0),) * 2)
        rail_span[key] = (min(k0, ks), max(k1, ks))
    rail_taps: dict[tuple[str, str, str], list[tuple[int, Point]]] = {}    # sběrný pól → [(strana, bod odbočky)]
    rail_y: dict[tuple[str, str, str], float] = {}                        # sběrný pól → výška čáry (strana 0)
    used_rails: list[tuple[int, int, float]] = []                        # (od strany, do strany, výška)

    def rail_height(key: tuple[str, str, str], pages: tuple[int, int]) -> float:
        """Výška sběrné čáry (souřadnice strany): u sběrného pólu se svislým portem 3 rozteče mřížky za ním
        (nad svorkami vývodů, ne přes jejich čísla), u vodorovného v úrovni portu; jiná čára na týchž stranách
        o rozteč přerušení dál."""
        if key in rail_y:
            return rail_y[key]
        eid, port, c = key
        ep = poles[eid]
        d = rotate_dir(ep.symbol.port(port).dir, ep.element.rotation)
        py = ep.pole_pos(port, c)[1]
        k = page_of.get(eid, 0)
        step = -mp.BREAK_PITCH if d == "S" else mp.BREAK_PITCH
        y = py + k * pitch + {"N": RAIL_OFFSET, "S": -RAIL_OFFSET}.get(d, 0.0)
        while any(a <= pages[1] and pages[0] <= b and abs(y - u) < mp.BREAK_PITCH - 1e-6 for a, b, u in used_rails):
            y += step
        used_rails.append((pages[0], pages[1], y))
        rail_y[key] = y
        return y

    for w in sheet.wires:
        ea, eb = poles.get(w.a.element_id), poles.get(w.b.element_id)
        if not ea or not eb:
            continue
        try:
            da = rotate_dir(ea.symbol.port(w.a.port).dir, ea.element.rotation)
            db = rotate_dir(eb.symbol.port(w.b.port).dir, eb.element.rotation)
        except (KeyError, StopIteration):
            continue
        ka, kb = page_of.get(w.a.element_id, 0), page_of.get(w.b.element_id, 0)
        if ea.element.symbol_id == BUS or eb.element.symbol_id == BUS:
            if ea.element.symbol_id == BUS and eb.element.symbol_id == BUS:
                continue
            dev, ddir, kd, bus, dport = (eb, db, kb, ea, w.b.port) if ea.element.symbol_id == BUS else \
                (ea, da, ka, eb, w.a.port)
            side = "b" if dev is eb else "a"
            for c in mp.wire_conductors(w):
                if c not in bus.slots:
                    continue
                px, py = dev.pole_pos(dport, c)
                y = bus_y(bus, c, kd)
                t = "" if mp.is_terminal_block(dev.element) else mp.terminal_text(w, c, side)
                conductor(w, c, 0, (px, py), ddir, (px, y), "S" if y > py else "N", (t, ""), kd)
                bus_taps.setdefault((bus.element.id, kd), []).append((px, y))
            continue
        for i, c in enumerate(mp.wire_conductors(w)):
            pa, pb = ea.pole_pos(w.a.port, c), eb.pole_pos(w.b.port, c)
            ta = "" if mp.is_terminal_block(ea.element) else mp.terminal_text(w, c, "a")
            tb = "" if mp.is_terminal_block(eb.element) else mp.terminal_text(w, c, "b")
            if (w.id, c) in rail_of:      # do sběrné čáry: odbočka svisle od pólu zdroje k čáře
                key, side = rail_of[(w.id, c)]
                ks, ps, ds, ts = (ka, pa, da, ta) if side == "a" else (kb, pb, db, tb)
                y = rail_height(key, rail_span[key]) - ks * pitch
                tap = (ps[0], y)
                dtap = "S" if y > ps[1] else "N"
                conductor(w, c, 0, ps, ds, tap, dtap, (ts, ""), ks)
                g.rail_taps[(w.id, c)] = (ps, ds, tap, dtap, ts)
                rail_taps.setdefault(key, []).append((ks, tap))
                continue
            if ka == kb:
                conductor(w, c, i, pa, da, pb, db, (ta, tb), ka, len(mp.wire_conductors(w)) > 1)
                continue
            right = ka < kb
            xa = (W - MARGIN - BREAK_INSET) if right else (MARGIN_LEFT + BREAK_INSET)
            xb = (MARGIN_LEFT + BREAK_INSET) if right else (W - MARGIN - BREAK_INSET)
            na = breaks.setdefault((ka, right), 0)
            nb = breaks.setdefault((kb, not right), 0)
            breaks[(ka, right)] = na + 1
            breaks[(kb, not right)] = nb + 1
            ya = mp.break_y(pa, da, na, break_ys.setdefault((ka, right), set()))
            yb = mp.break_y(pb, db, nb, break_ys.setdefault((kb, not right), set()))
            conductor(w, c, i, pa, da, (xa, ya), "W" if right else "E", (ta, ""), ka)
            conductor(w, c, i, (xb, yb), "E" if right else "W", pb, db, ("", tb), kb, part=1)
            ref_a = mp.page_ref(sheet_no, kb, xb, yb + kb * pitch, size)   # u zdroje: odkaz na pokračování
            ref_b = mp.page_ref(sheet_no, ka, xa, ya + ka * pitch, size)   # u cíle: odkaz zpět
            g.page_breaks[(w.id, c)] = [(xa, ya, right, ref_a), (xb, yb, not right, ref_b)]
            for (x, y, at_right, ref), kp in zip(g.page_breaks[(w.id, c)], (ka, kb), strict=True):
                tx, ty, align = break_text_pos(x, y, at_right)
                text(tx, ty, ref, REF_TEXT_H, align, w.id, "odkaz přerušení", layer="ODKAZY", page=kp)
                for a, b in break_arrow(x, y, at_right):
                    deco(a, b, "ODKAZY", page=kp)

    # sběrné čáry přes strany: na každé straně od první do poslední odbočky, k okraji, kde pokračuje
    xl, xr = MARGIN_LEFT + BREAK_INSET, W - MARGIN - BREAK_INSET
    for key, taps in rail_taps.items():
        eid, port, c = key
        ep = poles[eid]
        kh = page_of.get(eid, 0)
        ph = ep.pole_pos(port, c)
        y_loc = rail_y[key]
        owner = f"{eid}#rail{port}{c}"
        pages = [kh] + [k for k, _pt in taps]
        k0, k1 = min(pages), max(pages)
        for k in range(k0, k1 + 1):
            y = y_loc - k * pitch
            xs = [pt[0] for kk, pt in taps if kk == k] + ([ph[0]] if k == kh else [])
            left = xl if k > k0 else min(xs)
            right = xr if k < k1 else max(xs)
            r = Rail(k, y, left, right, owner, c)
            if k == kh and abs(ph[1] - y) > 1e-6:
                r.stub = (ph, (ph[0], y))
            r.dots = [(x, y) for x in xs if left + 1e-6 < x < right - 1e-6]
            if k > k0:
                r.breaks.append((left, y, False, mp.page_ref(sheet_no, k - 1, xr, y_loc, size)))
            if k < k1:
                r.breaks.append((right, y, True, mp.page_ref(sheet_no, k + 1, xl, y_loc, size)))
            g.rails.append(r)
            line((left, y), (right, y), owner, f"sběrnou čáru {c}", layer="SBERNICE", weight="wire", page=k)
            if r.stub:
                line(*r.stub, owner, f"sběrnou čáru {c}", layer="SBERNICE", weight="wire", page=k)
            for pt in r.dots:
                prim("dot", (pt,), k, r=0.7, layer="SBERNICE")
            for bx, by, at_right, ref in r.breaks:
                tx, ty, align = break_text_pos(bx, by, at_right)
                text(tx, ty, ref, REF_TEXT_H, align, owner, "odkaz sběrné čáry", layer="ODKAZY", page=k)
                for a, b in break_arrow(bx, by, at_right):
                    deco(a, b, "ODKAZY", page=k)

    # sběrnice potenciálů – na každé straně s odbočkami; mezi stranami křížové odkazy na koncích čar
    x0, x1 = bus_span(W)
    for e in sheet.elements:
        if e.symbol_id != BUS:
            continue
        ep = poles[e.id]
        conds = list(ep.slots) or mp.parse_conductors(e.attrs.get("conductors", "")) or ["L1"]
        pages = sorted({page_of.get(e.id, 0)} | {k for (bid, k) in bus_taps if bid == e.id})
        refs = g.bus_refs.setdefault(e.id, [])
        for j, k in enumerate(pages):
            ys = {c: (bus_y(ep, c, k) if c in ep.slots else ep.origin[1] - i * BUS_PITCH) for i, c in enumerate(conds)}
            for c, y in ys.items():
                line((x0, y), (x1, y), e.id, f"sběrnici {e.ref}{c}", layer="SBERNICE", weight="bus", page=k)
                for a, b in bus_arrows(x0, x1, y):
                    deco(a, b, "SBERNICE", page=k)
                text(x0 - 1.5, y - 0.8, f"{e.ref}{c}", 2.0, "right", e.id, f"název potenciálu {e.ref}{c}", page=k)
                text(x1 + 1.5, y - 0.8, f"{e.ref}{c}", 2.0, "left", e.id, f"název potenciálu {e.ref}{c}", page=k)
                y_loc = y + k * pitch
                # odkaz pod názvem potenciálu na konci čáry (mimo odbočky, mezi čarami po 5 mm)
                if j > 0:          # pokračování z předchozí strany se sběrnicí (odkaz na její pravý konec)
                    refs.append((k, x0 - 1.5, y + BUS_REF_DY,
                                 mp.page_ref(sheet_no, pages[j - 1], x1, y_loc, size), "right"))
                if j < len(pages) - 1:   # pokračuje na další straně (odkaz na její levý konec)
                    refs.append((k, x1 + 1.5, y + BUS_REF_DY,
                                 mp.page_ref(sheet_no, pages[j + 1], x0, y_loc, size), "left"))
            for pt in bus_taps.get((e.id, k), []):
                prim("dot", (pt,), k, r=0.7, layer="SBERNICE")
            if k == pages[0] and e.attrs.get("desc"):
                pos = _bus_desc_pos(g, e.id, e.attrs["desc"], x0, x1, max(ys.values()) + 4.5)
                g.bus_desc[e.id] = pos
                text(*pos[:2], e.attrs["desc"], 2.0, pos[2], e.id, "popis sběrnice", page=k)

    # štítky kabelů u přívodů a vývodů
    for e in sheet.elements:
        if e.symbol_id not in ("sb.feed_in", "sb.feed_out"):
            continue
        ep = poles.get(e.id)
        if ep is None or not ep.switched:
            continue
        xs = [ep.origin[0] + ep.pole_offset(c)[0] for c in ep.switched]
        hit = linked_wire(project, sheet, e)
        w = hit[1] if hit else None
        cable = wire_label({k: v for k, v in w.attrs.items() if k != "ref"}, w.conductors) if w is not None \
            else e.attrs.get("cable", "")
        rows = [r for r in [(w.attrs.get("ref") if w else "") or e.ref, e.attrs.get("desc", ""), cable] if r] or ["?"]
        width = max(max(xs) - min(xs) + 4.0, max(len(r) for r in rows) * 1.25 + 3.0)
        cx = (min(xs) + max(xs)) / 2
        tx0, tx1 = cx - width / 2, cx + width / 2
        up = e.symbol_id == "sb.feed_in"
        h = TAG_ROW * len(rows)
        y_edge = ep.origin[1] + (3.0 if up else -3.0)
        top = y_edge + h if up else y_edge
        ke = page_of.get(e.id, 0)
        for a, b in pairwise([(tx0, top), (tx1, top), (tx1, top - h), (tx0, top - h), (tx0, top)]):
            line(a, b, e.id, f"štítek kabelu {rows[0]}", layer="STITKY", page=ke)
        for i, r in enumerate(rows):
            # text štítku je uvnitř rámečku (zmenšený odhad šířky – písmo 1,7–2 mm je užší než průměr)
            y = top - (i + 1) * TAG_ROW
            hh = 2.0 if i == 0 else 1.7
            b = text_box(cx, y + 0.8, r, hh, "center")
            g.texts.append(((max(b[0], tx0 + 0.3), b[1], min(b[2], tx1 - 0.3), min(b[3], top - i * TAG_ROW)), e.id,
                            f"štítek kabelu {rows[0]}"))
            prim("text", ((cx, y + 0.8),), ke, text=r, h=hh, align="center", layer="STITKY")
            if i:
                deco((tx0, y + TAG_ROW), (tx1, y + TAG_ROW), "STITKY", page=ke)

    for eid, refs in g.bus_refs.items():
        for k, x, y, s, align in refs:
            text(x, y, s, REF_TEXT_H, align, eid, "odkaz sběrnice", layer="ODKAZY", page=k)
    g.bus_taps = bus_taps

    # popisky žil: výchozí poloha, a když vede přes cizí čáru nebo text, první volná z kandidátů
    _place_conductor_labels(g, pending)
    for key, (x, y, s, align) in g.conductor_labels.items():
        if s:
            prim("text", ((x, y),), label_page.get(key), text=s, h=1.8, align=align, layer="TEXTY")

    # nadpis rozvaděče
    title = switchboard_title(project, sheet)
    for k in range(g.pages if title else 0):
        ls = list(title)
        if g.pages > 1:
            ls[0] = f"{ls[0]}  ({k + 1}/{g.pages})"
        tx, ty = MARGIN_LEFT + 5.0, H - MARGIN - 4.0 - k * pitch
        y = 0.0
        for i, s in enumerate(ls):
            h = 5.0 if i == 0 else 3.0
            y -= h
            text(tx, ty + y, s, h, "left", "#title", "nadpis rozvaděče", page=k)
            if i == 0:
                deco(*title_underline(tx, ty + y, s, h), "TEXTY", page=k)
                y -= 2.8
            y -= 1.2
    return g


def _bus_desc_pos(g: MultipoleGeometry, owner: str, desc: str, x0: float, x1: float, y: float
                  ) -> tuple[float, float, str]:
    """Poloha popisu sběrnice nad horní čarou: vpravo na konci, jinak vlevo na začátku, jinak první volné místo
    zprava (odbočky přístrojů u konce sběrnice by ho přeškrtly)."""
    cands = [(x1, y, "right"), (x0 + 1.5, y, "left")]
    x = x1 - 5.0
    while x - len(desc) * 2.0 * CHAR_W > x0:
        cands.append((x, y, "right"))
        x -= 5.0
    for cx, cy, align in cands:
        box = text_box(cx, cy, desc, 2.0, align)
        if not any(o.split("#")[0] != owner and segment_hits_box(a, b, box) for a, b, o, _w in g.lines) and \
                not any(o != owner and boxes_overlap(box, tb) for tb, o, _w in g.texts):
            return cx, cy, align
    return cands[0]


def _rail_hubs(sheet: Sheet, poles: dict[str, mp.ElementPoles], page_of: dict[str, int]
               ) -> dict[tuple[str, str], tuple[tuple[str, str, str], str]]:
    """Žíly vedené přes sběrnou čáru: pól (prvek, port, žíla), do kterého vedou žíly aspoň ze dvou prvků na
    jiných stranách (PE svodičů všech stringů do XPE). Na čáru se napojí všechny jeho žíly, i z jeho strany.
    PE lišta (`sb.pe_bar`) je jeden pól přes všechny své svorky (sběrná čára vede k první použité).
    Vrací {(id vodiče, žíla): (sběrný pól, konec zdroje a/b)}."""
    cross: dict[tuple[str, str, str], int] = {}
    ends: list[tuple[str, str, tuple[str, str, str], tuple[str, str, str]]] = []
    bar_port: dict[tuple[str, str], str] = {}

    def key(eid: str, port: str, c: str) -> tuple[str, str, str]:
        if poles[eid].element.symbol_id in RAIL_BAR_SYMBOLS:
            port = bar_port.setdefault((eid, c), port)
        return (eid, port, c)

    for w in sheet.wires:
        ea, eb = poles.get(w.a.element_id), poles.get(w.b.element_id)
        if not ea or not eb or BUS in (ea.element.symbol_id, eb.element.symbol_id):
            continue
        other_page = page_of.get(w.a.element_id, 0) != page_of.get(w.b.element_id, 0)
        for c in mp.wire_conductors(w):
            ka, kb = key(w.a.element_id, w.a.port, c), key(w.b.element_id, w.b.port, c)
            ends.append((w.id, c, ka, kb))
            if other_page:
                cross[ka] = cross.get(ka, 0) + 1
                cross[kb] = cross.get(kb, 0) + 1
    out: dict[tuple[str, str], tuple[tuple[str, str, str], str]] = {}
    for wid, c, ka, kb in ends:
        na, nb = cross.get(ka, 0), cross.get(kb, 0)
        if max(na, nb) < 2:
            continue
        out[(wid, c)] = (ka, "b") if na >= nb else (kb, "a")
    return out


def bus_span(page_w: float) -> tuple[float, float]:
    """Začátek a konec čar sběrnice na straně šířky `page_w` (vlevo a vpravo názvy potenciálů)."""
    from envocad.model.frame import MARGIN, MARGIN_LEFT
    return MARGIN_LEFT + 12.0, page_w - MARGIN - 14.0


def _label_candidates(pts: list[Point], staggered: bool, label: str) -> list[tuple[float, float, str]]:
    """Kandidáti polohy popisku žíly: výchozí (`conductor_label_anchor`), pak na každém úseku (nejdelší první)
    nad vodorovným vlevo/uprostřed/vpravo a vpravo/vlevo od svislého ve třetinách."""
    x, y, align, _v = mp.conductor_label_anchor(pts, staggered)
    out = [(x, y, align)]
    width = len(label) * 1.8 * CHAR_W
    segs = [(a, b) for i, (a, b) in enumerate(pairwise(pts))
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1e-6 and not (staggered and len(pts) == 6 and i == 2)]
    segs.sort(key=lambda s: -(abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1])))
    for a, b in segs:
        if abs(a[1] - b[1]) < 1e-6:
            x1, x2 = sorted((a[0], b[0]))
            if x2 - x1 >= width + 2 * GAP:
                yy = a[1] + GAP
                out += [((x1 + x2) / 2, yy, "center"), (x1 + GAP, yy, "left"), (x2 - GAP, yy, "right"),
                        ((x1 + x2) / 2, a[1] - GAP - 1.8, "center")]
        else:
            y1, y2 = sorted((a[1], b[1]))
            if y2 - y1 >= 6.0:
                for f in (0.5, 0.25, 0.75, 0.1, 0.9):
                    yy = y1 + (y2 - y1) * f - 1.0
                    out += [(a[0] + GAP, yy, "left"), (a[0] - GAP, yy, "right")]
    # nakonec svislé běhy složené z navazujících úseků (vývod + úsek + vývod): krátká odbočka ke sběrnici na
    # zhuštěné straně A4 nemá úsek ≥ 6 mm, celý běh ale ano – popisek se vejde mezi čáru sběrnice a přístroj
    run: list[Point] = []
    for i, (a, b) in enumerate(pairwise(pts)):
        vertical = abs(a[0] - b[0]) < 1e-6 and not (staggered and len(pts) == 6 and i == 2)
        if vertical and run and abs(run[-1][0] - a[0]) < 1e-6 and abs(run[-1][1] - a[1]) < 1e-6:
            run.append(b)
            continue
        if len(run) > 2:
            out += _run_candidates(run)
        run = [a, b] if vertical else []
    if len(run) > 2:
        out += _run_candidates(run)
    return out


def _run_candidates(run: list[Point]) -> list[tuple[float, float, str]]:
    y1, y2 = sorted((run[0][1], run[-1][1]))
    if y2 - y1 < 6.0:
        return []
    out = []
    for f in (0.2, 0.3, 0.7, 0.8, 0.4, 0.6):
        yy = y1 + (y2 - y1) * f - 1.0
        out += [(run[0][0] + GAP, yy, "left"), (run[0][0] - GAP, yy, "right")]
    return out


def _place_conductor_labels(g: MultipoleGeometry, pending) -> None:
    lgrid = _IndexGrid()
    for k, (a, b, _o, _w) in enumerate(g.lines):
        lgrid.add((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])), k)
    tgrid = _IndexGrid()
    for i, (b, _o, _w) in enumerate(g.texts):
        tgrid.add(b, i)

    def score(box: Box, owner: str) -> float:
        s = 0.0
        for k in lgrid.near(box):
            a, b, lo, _w = g.lines[k]
            if lo != owner and segment_hits_box(a, b, box):
                s += 3.0
        for i in tgrid.near(box):
            ob, oo, _w = g.texts[i]
            if oo != owner and boxes_overlap(box, ob):
                s += 10.0
        return s

    placed: list[tuple[str, Point, Point, Point]] = []   # (text, úsek trasy, bod popisku) – už rozmístěné popisky

    def nearest_seg(pts: list[Point], x: float, y: float) -> tuple[Point, Point] | None:
        best_d, best_seg = None, None
        for a, b in pairwise(pts):
            if a == b:
                continue
            cx = min(max(x, min(a[0], b[0])), max(a[0], b[0]))
            cy = min(max(y, min(a[1], b[1])), max(a[1], b[1]))
            d = (cx - x) ** 2 + (cy - y) ** 2
            if best_d is None or d < best_d:
                best_d, best_seg = d, (a, b)
        return best_seg

    def duplicate(pts: list[Point], label: str) -> bool:
        """Stejný popisek už leží u úseku, který tato žíla sdílí (žíly několika vodičů vedené po stejné čáře
        do jedné svorky – např. PE ze svodičů do XPE): druhý popisek by se jen opakoval."""
        for text, a, b, (lx, ly) in placed:
            if text != label:
                continue
            for c, d in pairwise(pts):
                if abs(a[0] - b[0]) < 1e-6 and abs(c[0] - d[0]) < 1e-6 and abs(a[0] - c[0]) < 1e-6:
                    lo, hi = max(min(a[1], b[1]), min(c[1], d[1])), min(max(a[1], b[1]), max(c[1], d[1]))
                    if hi - lo > 1.0 and lo - 2.0 <= ly <= hi + 2.0:
                        return True
                elif abs(a[1] - b[1]) < 1e-6 and abs(c[1] - d[1]) < 1e-6 and abs(a[1] - c[1]) < 1e-6:
                    lo, hi = max(min(a[0], b[0]), min(c[0], d[0])), min(max(a[0], b[0]), max(c[0], d[0]))
                    if hi - lo > 1.0 and lo - 2.0 <= lx <= hi + 2.0:
                        return True
        return False

    for key, owner, pts, label, staggered in pending:
        if duplicate(pts, label):
            x, y, _a, _v = mp.conductor_label_anchor(pts, staggered)
            g.conductor_labels[key] = (x, y, "", "left")    # prázdný = scéna popisek nekreslí
            continue
        best, best_s = None, None
        for i, (x, y, align) in enumerate(_label_candidates(pts, staggered, label)):
            box = text_box(x, y, label, 1.8, align)
            sc = score(box, owner) + 0.01 * i
            if best_s is None or sc < best_s:
                best, best_s = (x, y, align, box), sc
            if sc < 0.5:
                break
        x, y, align, box = best
        g.conductor_labels[key] = (x, y, label, align)
        seg = nearest_seg(pts, x, y)
        if seg is not None:
            placed.append((label, seg[0], seg[1], (x, y)))
        tgrid.add(box, len(g.texts))
        g.texts.append((box, owner, f"popisek žíly {key[1]}"))


def multipole_text_overlaps(project: Project, sheet: Sheet, lib,
                            geometry: MultipoleGeometry | None = None) -> list[tuple[str, str, str]]:
    """Překryvy ve vícepólu: text přes cizí text, text přes cizí čáru (žílu, značku, sběrnici, štítek).
    [(vlastník textu, vlastník druhého, popis)] – vlastník = id prvku nebo vodiče (žíla „id#L1“ se hlásí jako vodič);
    každá dvojice jen jednou."""
    g = geometry or multipole_geometry(project, sheet, lib)
    found: dict[tuple, tuple[str, str, str]] = {}
    tgrid = _IndexGrid()
    for i, (b, _o, _w) in enumerate(g.texts):
        tgrid.add(b, i)
    for i, (a, oa, wa) in enumerate(g.texts):
        for j in tgrid.near(a, after=i):
            b, ob, wb = g.texts[j]
            if oa == ob or not boxes_overlap(a, b):
                continue
            key = frozenset((oa, ob))
            if key not in found:
                found[key] = (oa, ob, f"{wa} přes {wb}")
    lgrid = _IndexGrid()
    for k, (a, b, _o, _w) in enumerate(g.lines):
        lgrid.add((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])), k)
    for box, owner, what in g.texts:
        # čísla svorek (písmo 2 mm těsně pod svorkou): bez tolerance – čára po okraji obálky už číslo přeškrtne
        tol = 0.0 if what.startswith(TERMINAL_NUMBER) else 0.2
        for k in lgrid.near(box):
            a, b, lo, lwhat = g.lines[k]
            if lo == owner:
                continue
            key = (owner, lo, "line")
            if key in found or not segment_hits_box(a, b, box, tol):
                continue
            found[key] = (owner, lo, f"{what} přes {lwhat}")
    out: dict[tuple, tuple[str, str, str]] = {}
    for a, b, what in found.values():
        a, b = a.split("#")[0], b.split("#")[0]
        out.setdefault((a, b, what), (a, b, what))
    return list(out.values())
