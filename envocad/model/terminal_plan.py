"""Plán svorkovnice (terminal diagram) – data pro výkaz i kreslený list. Bez Qt.

Pro každou svorkovnici (X…) na listu: svorky v pořadí čísel, u každé vnější připojení (kabel odcházející
z rozvaděče – přívod/vývod, resp. vodič JPS navázaný na přívod/vývod), vnitřní připojení (přístroj v rozvaděči)
a můstek. Strana se neurčuje podle portu, ale podle toho, co je na druhém konci vodiče.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from envocad.model import multipole as mp
from envocad.model.designation import element_name
from envocad.model.project import FEED_SYMBOLS, Element, Project, Sheet, Wire, linked_wire
from envocad.model.xref import natural_key


@dataclass
class TerminalRow:
    strip: str
    number: str
    conductor: str
    element_id: str
    external: str = ""      # odkud/kam vně rozvaděče (W2 T1:AC)
    ext_cable: str = ""
    internal: str = ""      # přístroj v rozvaděči (F2:1)
    int_cable: str = ""
    bridge: str = ""

    @property
    def sort_key(self) -> tuple:
        return (not self.number.isdigit(), int(self.number) if self.number.isdigit() else 0, self.number, self.conductor)


@dataclass
class StripPlan:
    strip: str
    rows: list[TerminalRow] = field(default_factory=list)
    bridges: list[list[str]] = field(default_factory=list)


def _wire_text(project: Project, sheet: Sheet, w: Wire, side: str, conductor: str) -> tuple[str, str]:
    """Druhý konec žíly (strana `side`) a kabel: svorka jako zapojovací/výrobní seznam (`wiring.conductor_end` –
    pól přístroje „Q1:3“, svorka, potenciál sběrnice), bez aspektů (plán je po listech)."""
    from envocad.model.wiring import conductor_end
    end = w.a if side == "a" else w.b
    try:
        sheet.element(end.element_id)
    except KeyError:
        return "", ""
    cable = " ".join(x for x in (w.attrs.get("cable", ""), w.attrs.get("cross", "")) if x)
    return conductor_end(project, sheet, w, conductor, side).terminal, w.attrs.get("ref", "") + (f" {cable}" if cable else "")


def _external_of_feed(project: Project, sheet: Sheet, e: Element) -> tuple[str, str]:
    """Vnější připojení přívodu/vývodu: navázaný vodič JPS, jinak text z atributů."""
    hit = linked_wire(project, sheet, e)
    if hit is not None:
        s, w = hit
        far_end = w.b if w.a.element_id == sheet.parent_element_id else w.a
        far = s.element(far_end.element_id)
        cable = " ".join(x for x in (w.attrs.get("cable", ""), w.attrs.get("cross", "")) if x)
        return f"{element_name(far)}:{far_end.port}", (w.attrs.get("ref", "") + " " + cable).strip()
    return e.attrs.get("from") or e.attrs.get("to") or e.attrs.get("desc", ""), e.attrs.get("cable", "")


def terminal_plan(project: Project, sheet: Sheet) -> list[StripPlan]:
    strips: dict[str, StripPlan] = {}
    for e in sheet.elements:
        if e.symbol_id not in mp.TERMINAL_SYMBOLS or not e.ref:
            continue
        plan = strips.setdefault(e.ref, StripPlan(e.ref, bridges=project.bridge_groups(e.ref, sheet)))
        ends = [(w, side, end) for w in sheet.wires for side, end in (("a", w.a), ("b", w.b)) if end.element_id == e.id]
        slots = sorted({c for w, _, _ in ends for c in mp.wire_conductors(w)}, key=mp.canon_key)
        nums = mp.terminal_numbers(e, len(slots)) if mp.is_terminal_block(e) else [""] * len(slots)
        for c, num in zip(slots, nums):
            row = TerminalRow(e.ref, num, c, e.id)
            if e.symbol_id in FEED_SYMBOLS:
                row.external, row.ext_cable = _external_of_feed(project, sheet, e)
            for w, side, end in ends:
                if c not in mp.wire_conductors(w):
                    continue
                if not row.number:
                    t = mp.terminal_text(w, c, side)
                    row.number = t.partition(":")[2] or t
                other = w.b if side == "a" else w.a
                try:
                    oe = sheet.element(other.element_id)
                except KeyError:
                    continue
                text, cable = _wire_text(project, sheet, w, "b" if side == "a" else "a", c)
                if oe.symbol_id in FEED_SYMBOLS:
                    # vodič k přívodu/vývodu = vnější strana (kabel ven z rozvaděče)
                    ext, ext_cable = _external_of_feed(project, sheet, oe)
                    row.external = row.external or ext or text
                    row.ext_cable = row.ext_cable or ext_cable or cable
                elif row.internal:
                    row.internal += ", " + text
                else:
                    row.internal, row.int_cable = text, cable
            if not row.number:
                row.number = str(len(plan.rows) + 1)
            b = project.bridge_of(e.ref, row.number, sheet)
            row.bridge = "-".join(b) if b else ""
            plan.rows.append(row)
    for plan in strips.values():
        plan.rows.sort(key=lambda r: r.sort_key)
    return sorted(strips.values(), key=lambda p: natural_key(p.strip))


# ---- rozmístění kresleného plánu na strany ------------------------------------------------------------------
T_W, T_H = 8.0, 14.0         # svorka (š × v)
EXT_H, INT_H = 42.0, 42.0    # výška pásma textů nad/pod svorkami (vnější / vnitřní připojení)
STRIP_GAP = 12.0             # mezera mezi pásy svorek pod sebou
COL_GAP = 10.0               # mezera mezi svorkovnicemi vedle sebe v jednom pásu
HEAD_H = 3.0                 # nadpis svorkovnice nad pásmem vnějších připojení
TITLE_H = 3.5                # výška písma nadpisu
TOP_PAD = 8.0                # odstup prvního nadpisu od horního okraje kreslicí plochy
BOTTOM_PAD = 35.0            # spodek pásu nad popisovým polem (32 mm) s odstupem (od spodního okraje kreslicí plochy)
LEFT_PAD = 6.0               # odstup první svorky od levého okraje kreslicí plochy
BAND_H = HEAD_H + EXT_H + T_H + INT_H   # výška jednoho pásu (bez mezery)


@dataclass
class PlanChunk:
    """Úsek svorkovnice na straně: svorky `rows` vedle sebe od `x` (levá hrana první svorky), horní hrana svorek
    `top` (mm, Y nahoru, souřadnice strany). `title` = nadpis nad úsekem (u pokračování „(pokračování)“)."""
    strip: str
    rows: list[TerminalRow]
    bridges: list[list[str]]
    x: float
    top: float
    title: str
    ext_h: float = EXT_H     # výška pásma vnějších připojení nad svorkami (podle nejdelšího textu plánu)
    int_h: float = INT_H     # výška pásma vnitřních připojení pod svorkami

    @property
    def title_pos(self) -> tuple[float, float]:
        return self.x - 2.0, self.top + self.ext_h + HEAD_H

    @property
    def width(self) -> float:
        return len(self.rows) * T_W


def _title_w(text: str) -> float:
    return 0.62 * TITLE_H * len(text)      # odhad šířky nadpisu (Arial ~0,55–0,6 výšky na znak)


MIN_BAND_TEXT = 18.0      # nejnižší pásmo připojení (vývod 7 mm + krátký text)


def band_heights(rows: list[TerminalRow]) -> tuple[float, float]:
    """Výšky pásem vnějších a vnitřních připojení pásu svorek podle nejdelšího svislého textu (vývod 7 mm + text,
    odhad 0,62 výšky písma na znak, + 2 mm), nejvýš `EXT_H` / `INT_H` – krátké texty (DC rozvaděč) nechají víc
    pásů na stranu A4."""
    def need(texts: list[tuple[str, float]], cap: float) -> float:
        longest = max((0.62 * h * len(t) for t, h in texts if t), default=0.0)
        return min(cap, max(MIN_BAND_TEXT, 7.0 + longest + 2.0))
    ext = need([(r.external, 2.0) for r in rows] + [(r.ext_cable, 1.6) for r in rows], EXT_H)
    inn = need([(r.internal, 2.0) for r in rows] + [(r.int_cable, 1.6) for r in rows], INT_H)
    return ext, inn


def layout_plan_pages(plans: list[StripPlan], inner: tuple[float, float, float, float]) -> list[list[PlanChunk]]:
    """Rozmístí svorkovnice listu na strany: pásy pod sebou, v pásu svorkovnice vedle sebe (další sloupec),
    dlouhá svorkovnice se zalomí do dalšího pásu, pás, který se pod sebe nevejde, jde na další stranu. Výška pásu
    podle jeho textů (`band_heights`). Žádná svorka se nevynechá. `inner` = kreslicí plocha strany (x0, y0, x1, y1)
    – rozměr strany (A4 listu rozvaděče, `sheet_plan_pages`). Vrací strany (aspoň jednu, i prázdnou)."""
    x0, y0, x1, y1 = inner
    left, right = x0 + LEFT_PAD, x1 - 4.0
    per_row = max(1, int((right - left) // T_W))
    # 1) úseky do pásů zleva doprava
    bands: list[list[tuple[StripPlan, list[TerminalRow], str, float]]] = [[]]
    cursor = left
    for plan in plans:
        if not plan.rows:
            continue
        chunks = [plan.rows[i:i + per_row] for i in range(0, len(plan.rows), per_row)]
        for ci, rows in enumerate(chunks):
            title = f"Svorkovnice {plan.strip}" + (" (pokračování)" if ci else "")
            need = max(len(rows) * T_W, _title_w(title))
            if cursor > left and cursor + need > right:
                bands.append([])
                cursor = left
            bands[-1].append((plan, rows, title, cursor))
            cursor += need + COL_GAP
    # 2) pásy pod sebou, co se nevejde, na další stranu
    first_band = y1 - TOP_PAD - HEAD_H            # nadpis prvního pásu
    pages: list[list[PlanChunk]] = [[]]
    band_title_y = first_band
    for band in bands:
        if not band:
            continue
        ext_h, int_h = band_heights([r for _p, rows, _t, _x in band for r in rows])
        band_h = HEAD_H + ext_h + T_H + int_h
        if pages[-1] and band_title_y - (band_h - HEAD_H) < y0 + BOTTOM_PAD:
            pages.append([])
            band_title_y = first_band
        for plan, rows, title, x in band:
            pages[-1].append(PlanChunk(plan.strip, rows, plan.bridges, x, band_title_y - ext_h, title, ext_h, int_h))
        band_title_y -= band_h + STRIP_GAP
    return pages


def sheet_plan_pages(project: Project, sheet: Sheet, plans: list[StripPlan] | None = None,
                     standard_paper: str = mp.DEFAULT_SWITCHBOARD_PAPER
                     ) -> tuple[tuple[float, float], list[list[PlanChunk]]]:
    """Plán svorkovnice listu rozmístěný na strany formátu vícepólu listu (`multipole.page_size`, list rozvaděče
    bez volby formát firemního standardu `standard_paper`, výchozí A4 na šířku). Vrací (rozměr strany, strany)."""
    from envocad.model.frame import inner_box
    size = mp.page_size(sheet, standard_paper=standard_paper)
    if plans is None:
        plans = terminal_plan(project, sheet)
    return size, layout_plan_pages(plans, inner_box(*size))


def strip_numbers(project: Project, sheet: Sheet, strip: str) -> set[str]:
    """Čísla svorek, která na svorkovnici `strip` listu existují (podle plánu svorkovnice)."""
    return {r.number for p in terminal_plan(project, sheet) if p.strip == strip for r in p.rows if r.number}


def parse_bridges(text: str) -> list[list[str]]:
    """Text můstků (jedna skupina na řádek, čísla oddělená pomlčkou / čárkou / mezerou) → skupiny (≥ 2 svorky)."""
    groups = []
    for line in (text or "").splitlines():
        toks = [t.strip() for t in line.replace(",", "-").replace(" ", "-").split("-") if t.strip()]
        if len(toks) >= 2:
            groups.append(toks)
    return groups


def bridge_errors(strip: str, text: str, existing: set[str]) -> list[str]:
    """Chyby zadání můstků svorkovnice: řádek s jedinou svorkou, svorka, která na svorkovnici není, svorka ve dvou
    můstcích. Česky, prázdné = v pořádku."""
    errs: list[str] = []
    seen: dict[str, int] = {}
    for i, line in enumerate((text or "").splitlines(), start=1):
        toks = [t.strip() for t in line.replace(",", "-").replace(" ", "-").split("-") if t.strip()]
        if not toks:
            continue
        if len(toks) < 2:
            errs.append(f"{strip}, řádek {i}: můstek musí spojovat aspoň 2 svorky („{line.strip()}“)")
            continue
        missing = [t for t in toks if t not in existing]
        if missing:
            errs.append(f"{strip}, řádek {i}: svorka {', '.join(missing)} na svorkovnici {strip} není")
        for t in toks:
            if t in seen and seen[t] != i:
                errs.append(f"{strip}, řádek {i}: svorka {t} je už v můstku na řádku {seen[t]}")
            seen.setdefault(t, i)
    return errs
