"""Šablony listů rozvaděčů – vygenerují přístroje a vodiče do listu. Bez Qt.

Šablona je funkce (project, sheet, params) → None. Souřadnice v mm, Y nahoru, mřížka 2,5 mm.
Přístroje se zároveň rozmístí na DIN lišty (layout), aby pohled rozložení nebyl prázdný.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from envocad.model.project import Element, Project, Sheet, Wire, WireEnd

AC_CONDUCTORS = ["L1", "L2", "L3", "N", "PE"]
DC_CONDUCTORS = ["DC+", "DC-"]


@dataclass
class TemplateParam:
    key: str
    label: str
    default: str


@dataclass
class Template:
    id: str
    name: str
    description: str
    params: list[TemplateParam]
    build: Callable[[Project, Sheet, dict[str, str]], None]


def _el(project: Project, sheet: Sheet, sid: str, x: float, y: float, prefix: str, rot: int = 0, **attrs) -> Element:
    e = Element(symbol_id=sid, x=x, y=y, rotation=rot)
    e.attrs = {"ref": project.next_ref(prefix) if prefix else "", **{k: str(v) for k, v in attrs.items()}}
    sheet.elements.append(e)
    return e


def _wire(project: Project, sheet: Sheet, a: Element, pa: str, b: Element, pb: str,
          conductors: list[str], **attrs) -> Wire:
    w = Wire(WireEnd(a.id, pa), WireEnd(b.id, pb), conductors=list(conductors))
    w.attrs = {"ref": "", **{k: str(v) for k, v in attrs.items()}}
    sheet.wires.append(w)
    return w


def _auto_link_feed(project: Project, sheet: Sheet, feed: Element, port_hint: str = "") -> None:
    """Přívod rozvaděče naváže na první vodič JPS napojený na blok ROZVADĚČ (přebere kabel a žíly)."""
    from envocad.model.project import feed_link_attrs, parent_sheet
    ps = parent_sheet(project, sheet)
    if ps is None:
        return
    block = sheet.parent_element_id
    cands = [w for w in ps.wires if w.touches(block)]
    cands.sort(key=lambda w: 0 if port_hint and (w.a.port == port_hint or w.b.port == port_hint) else 1)
    if not cands:
        return
    w = cands[0]
    # konec vodiče na bloku se přejmenuje na označení přívodu (X1) – blok má porty podle přívodů/vývodů
    for end in (w.a, w.b):
        if end.element_id == block and feed.ref:
            end.port = feed.ref
    feed.attrs.update(feed_link_attrs(project, sheet, feed, w.id))
    if cands[0].conductors:
        for w in sheet.wires:
            if w.touches(feed.id):
                w.conductors = list(cands[0].conductors)


def _place_sequential(sheet: Sheet, elements: list[Element]) -> None:
    """Rozmístí přístroje za sebou po řadách DIN lišt podle jejich šířky v modulech."""
    row, pos = 0, 0.0
    for e in elements:
        m = e.modules
        if m <= 0:
            continue
        if pos + m > sheet.layout.modules_per_row:
            row, pos = row + 1, 0.0
        sheet.layout.set_placement(e.id, row, pos)
        pos += m
    sheet.layout.rows = max(sheet.layout.rows, row + 1)


# ---------------------------------------------------------------------------
GROUP_PITCH = 30.0  # rozteč skupin svorek (mm) – ve vícepólu se roztáhne 2×, aby se vešlo 5 svorek po 7,5 mm


def _terminal_group(project: Project, sheet: Sheet, x: float, y: float, strip: str, first: int, n: int,
                    desc: str = "") -> Element:
    """Skupina n svorek svorkovnice `strip` s čísly first…first+n-1 (prvek sb.terminal_block)."""
    e = Element(symbol_id="sb.terminal_block", x=x, y=y)
    e.attrs = {"ref": strip, "terminal": " ".join(str(first + i) for i in range(n)), "desc": desc}
    sheet.elements.append(e)
    return e


def _bridge_groups(first_numbers: list[int], n: int) -> list[list[str]]:
    """Můstky mezi skupinami: žíla i spojuje svorky first+i všech skupin."""
    return [[str(f + i) for f in first_numbers] for i in range(n)]


def build_ac_fve(project: Project, sheet: Sheet, p: dict[str, str]) -> None:
    """AC rozvaděč FVE: přívod od střídače → hlavní vypínač → rozvodné svorky X2 s můstky → SPD, vývody s jističi."""
    n_out = max(1, min(int(p.get("n_out", "3")), 9))
    i_main = p.get("i_main", "80")
    i_out = p.get("i_out", "32")
    y = 200.0
    x0 = 60.0
    nc = len(AC_CONDUCTORS)
    feed = _el(project, sheet, "sb.feed_in", x0, y + 20, "X", desc=p.get("feed_desc", "od střídače"))
    q = _el(project, sheet, "sb.main_switch", x0, y, "Q", rot=270, in_=i_main, poles="4", modules="4")
    strip = project.next_ref("X")
    # skupina 0 = napájení (od Q) + SPD, skupiny 1…n = vývody; napájení přes můstky
    firsts: list[int] = []
    groups: list[Element] = []
    for i in range(n_out + 1):
        first = 1 + i * nc
        firsts.append(first)
        groups.append(_terminal_group(project, sheet, x0 + i * GROUP_PITCH, y - 30, strip, first, nc,
                                      "napájení" if i == 0 else f"vývod {i}"))
    project.set_bridges(strip, _bridge_groups(firsts, nc), sheet)
    spd = _el(project, sheet, "fve.spd", x0, y - 60, "F", spd_type="T1+T2", poles="4", modules="4")
    pe = _el(project, sheet, "sb.pe_bar", x0, y - 90, "X", kind="PE")
    _wire(project, sheet, feed, "1", q, "1", AC_CONDUCTORS)
    _wire(project, sheet, q, "2", groups[0], "1", AC_CONDUCTORS)
    _wire(project, sheet, groups[0], "2", spd, "L", AC_CONDUCTORS[:4])
    _wire(project, sheet, groups[0], "2", pe, "2", ["PE"])   # PE svorka skupiny → PE lišta
    _wire(project, sheet, spd, "PE", pe, "1", ["PE"])
    outs: list[Element] = []
    for i in range(1, n_out + 1):
        x = x0 + i * GROUP_PITCH
        f = _el(project, sheet, "fve.breaker_mcb", x, y - 60, "F", rot=270, in_=i_out, char="B", poles="3", modules="3")
        out = _el(project, sheet, "sb.feed_out", x, y - 95, "X", desc=f"vývod {i}")
        _wire(project, sheet, groups[i], "2", f, "1", AC_CONDUCTORS)
        _wire(project, sheet, f, "2", out, "1", AC_CONDUCTORS)
        outs.append(f)
    _auto_link_feed(project, sheet, feed, "1")
    _place_sequential(sheet, [q, spd, *outs])


def build_dc(project: Project, sheet: Sheet, p: dict[str, str]) -> None:
    """DC rozvaděč: stringy → pojistky → svorky X s můstky → SPD DC → odpínač DC → vývod ke střídači."""
    n_str = max(1, min(int(p.get("n_strings", "4")), 9))
    i_fuse = p.get("i_fuse", "15")
    y = 200.0
    x0 = 60.0
    nc = len(DC_CONDUCTORS)
    strip = project.next_ref("X")
    firsts: list[int] = []
    groups: list[Element] = []
    fuses: list[Element] = []
    for i in range(n_str + 2):  # stringy, SPD, odpínač
        first = 1 + i * nc
        firsts.append(first)
        desc = f"string {i + 1}" if i < n_str else ("SPD" if i == n_str else "ke střídači")
        groups.append(_terminal_group(project, sheet, x0 + i * GROUP_PITCH, y - 40, strip, first, nc, desc))
    project.set_bridges(strip, _bridge_groups(firsts, nc), sheet)
    for i in range(n_str):
        x = x0 + i * GROUP_PITCH
        feed = _el(project, sheet, "sb.feed_in", x, y + 10, "X", desc=f"string {i + 1}")
        f = _el(project, sheet, "fve.fuse", x, y - 15, "F", rot=270, in_=i_fuse, char="gPV", poles="2", modules="2")
        _wire(project, sheet, feed, "1", f, "1", DC_CONDUCTORS)
        _wire(project, sheet, f, "2", groups[i], "1", DC_CONDUCTORS)
        fuses.append(f)
    xs = x0 + n_str * GROUP_PITCH
    spd = _el(project, sheet, "fve.spd", xs, y - 70, "F", spd_type="T1+T2 DC", poles="3", modules="3", uc="1000")
    pe = _el(project, sheet, "sb.pe_bar", xs, y - 95, "X", kind="PE")
    xq = x0 + (n_str + 1) * GROUP_PITCH
    q = _el(project, sheet, "fve.dc_disconnect", xq, y - 70, "Q", rot=270, in_=p.get("i_dc", "32"), poles="2", modules="2")
    out = _el(project, sheet, "sb.feed_out", xq, y - 100, "X", desc="ke střídači")
    _wire(project, sheet, groups[n_str], "2", spd, "L", DC_CONDUCTORS)
    _wire(project, sheet, spd, "PE", pe, "1", ["PE"])
    _wire(project, sheet, groups[n_str + 1], "2", q, "1", DC_CONDUCTORS)
    _wire(project, sheet, q, "2", out, "1", DC_CONDUCTORS)
    _place_sequential(sheet, [*fuses, spd, q])


TEMPLATES: list[Template] = [
    Template("ac_fve", "AC rozvaděč FVE", "Přívod od střídače, hlavní vypínač, rozvodné svorky s můstky, SPD, vývody s jističi",
             [TemplateParam("n_out", "Počet vývodů", "3"), TemplateParam("i_main", "In hlavního vypínače [A]", "80"),
              TemplateParam("i_out", "In jističů vývodů [A]", "32"), TemplateParam("feed_desc", "Přívod od", "od střídače")],
             build_ac_fve),
    Template("dc", "DC rozvaděč", "Stringy s pojistkami, svorky s můstky, SPD DC, odpínač DC, vývod ke střídači",
             [TemplateParam("n_strings", "Počet stringů", "4"), TemplateParam("i_fuse", "In pojistek [A]", "15"),
              TemplateParam("i_dc", "In odpínače DC [A]", "32")],
             build_dc),
    Template("empty", "Prázdný list", "Jen přívod a PE můstek", [], lambda pr, sh, p: (
        _el(pr, sh, "sb.feed_in", 40, 220, "X", desc="přívod"), _el(pr, sh, "sb.pe_bar", 40, 120, "X", kind="PE"))),
]


def template(tid: str) -> Template:
    return next(t for t in TEMPLATES if t.id == tid)


def apply_template(project: Project, sheet: Sheet, tid: str, params: dict[str, str] | None = None) -> None:
    t = template(tid)
    p = {tp.key: tp.default for tp in t.params}
    p.update(params or {})
    t.build(project, sheet, p)
