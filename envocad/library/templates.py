"""Šablony listů rozvaděčů – vygenerují přístroje a vodiče do listu. Bez Qt.

Šablona je funkce (project, sheet, params) → None. Souřadnice v mm, Y nahoru, mřížka 2,5 mm.
Přístroje se zároveň rozmístí na DIN lišty (layout), aby pohled rozložení nebyl prázdný.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from envocad.model.project import Element, Project, Sheet, Wire, WireEnd

AC_CONDUCTORS = ["L1", "L2", "L3", "N", "PE"]
BUS_X0, BUS_PITCH, BUS_IN_X = -67.5, 15.0, -75.0  # porty sběrnice sb.busbar (relativně k jejímu počátku)


def bus_port_x(bus_x: float, port_index: int) -> float:
    return bus_x + BUS_X0 + BUS_PITCH * (port_index - 1)
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
def build_ac_fve(project: Project, sheet: Sheet, p: dict[str, str]) -> None:
    """AC rozvaděč FVE: přívod od střídače → hlavní vypínač → SPD → sběrnice → vývody."""
    n_out = max(1, int(p.get("n_out", "3")))
    i_main = p.get("i_main", "80")
    i_out = p.get("i_out", "32")
    y = 200.0
    bx = 120.0
    fx = bx + BUS_IN_X  # x vstupu sběrnice
    feed = _el(project, sheet, "sb.feed_in", fx, y + 20, "X", desc=p.get("feed_desc", "od střídače"))
    q = _el(project, sheet, "sb.main_switch", fx, y, "Q", rot=270, in_=i_main, poles="4", modules="4")
    bus = _el(project, sheet, "sb.busbar", bx, y - 30, "X", desc="hlavní sběrnice", in_=i_main)
    spd = _el(project, sheet, "fve.spd", bus_port_x(bx, 1), y - 55, "F", spd_type="T1+T2", poles="4", modules="4")
    pe = _el(project, sheet, "sb.pe_bar", bus_port_x(bx, 1), y - 80, "X", kind="PE")
    _wire(project, sheet, feed, "1", q, "1", AC_CONDUCTORS)
    _wire(project, sheet, q, "2", bus, "IN", AC_CONDUCTORS)
    _wire(project, sheet, bus, "1", spd, "L", AC_CONDUCTORS[:4])
    _wire(project, sheet, spd, "PE", pe, "1", ["PE"])
    outs: list[Element] = []
    for i in range(min(n_out, 9)):
        port = str(i + 2)
        x = bus_port_x(bx, i + 2)
        f = _el(project, sheet, "fve.breaker_mcb", x, y - 60, "F", rot=270, in_=i_out, char="B", poles="3", modules="3")
        out = _el(project, sheet, "sb.feed_out", x, y - 95, "X", desc=f"vývod {i + 1}")
        _wire(project, sheet, bus, port, f, "1", AC_CONDUCTORS[:3])
        _wire(project, sheet, f, "2", out, "1", AC_CONDUCTORS[:3])
        outs.append(f)
    _place_sequential(sheet, [q, spd, *outs])


def build_dc(project: Project, sheet: Sheet, p: dict[str, str]) -> None:
    """DC rozvaděč: stringy → pojistky → sběrnice → SPD DC → odpínač DC → vývod ke střídači."""
    n_str = max(1, int(p.get("n_strings", "4")))
    i_fuse = p.get("i_fuse", "15")
    y = 200.0
    bx = 120.0
    bus = _el(project, sheet, "sb.busbar", bx, y - 40, "X", desc="sběrnice DC", conductors="DC+ DC-")
    fuses: list[Element] = []
    for i in range(min(n_str, 9)):
        x = bus_port_x(bx, i + 1)
        feed = _el(project, sheet, "sb.feed_in", x, y + 10, "X", desc=f"string {i + 1}")
        f = _el(project, sheet, "fve.fuse", x, y - 15, "F", rot=270, in_=i_fuse, char="gPV", poles="2", modules="2")
        _wire(project, sheet, feed, "1", f, "1", DC_CONDUCTORS)
        _wire(project, sheet, f, "2", bus, str(i + 1), DC_CONDUCTORS)
        fuses.append(f)
    spd = _el(project, sheet, "fve.spd", bx + BUS_IN_X, y - 70, "F", spd_type="T1+T2 DC", poles="3", modules="3", uc="1000")
    pe = _el(project, sheet, "sb.pe_bar", bx + BUS_IN_X, y - 95, "X", kind="PE")
    q = _el(project, sheet, "fve.dc_disconnect", bus_port_x(bx, 10), y - 80, "Q", rot=270, in_=p.get("i_dc", "32"), poles="2", modules="2")
    out = _el(project, sheet, "sb.feed_out", bus_port_x(bx, 10), y - 110, "X", desc="ke střídači")
    _wire(project, sheet, bus, "IN", spd, "L", DC_CONDUCTORS)
    _wire(project, sheet, spd, "PE", pe, "1", ["PE"])
    _wire(project, sheet, bus, "10", q, "1", DC_CONDUCTORS)
    _wire(project, sheet, q, "2", out, "1", DC_CONDUCTORS)
    _place_sequential(sheet, [*fuses, spd, q])


TEMPLATES: list[Template] = [
    Template("ac_fve", "AC rozvaděč FVE", "Přívod od střídače, hlavní vypínač, SPD, sběrnice, vývody s jističi",
             [TemplateParam("n_out", "Počet vývodů", "3"), TemplateParam("i_main", "In hlavního vypínače [A]", "80"),
              TemplateParam("i_out", "In jističů vývodů [A]", "32"), TemplateParam("feed_desc", "Přívod od", "od střídače")],
             build_ac_fve),
    Template("dc", "DC rozvaděč", "Stringy s pojistkami, sběrnice, SPD DC, odpínač DC, vývod ke střídači",
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
