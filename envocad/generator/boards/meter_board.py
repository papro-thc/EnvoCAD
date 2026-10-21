"""Elektroměrový rozvaděč RE na nn a funkce měření (bez Qt) – docs/design/topologie_f1_f2.md, kap. 2 bod 4;
rozhodnutí 5 (docs/NAVRH_TOPOLOGIE.md, kap. 8): hlavní jistič před elektroměrem (HJ) **vždy**, vypínač instalace za
elektroměrem **vždy**; přímé / nepřímé měření a hranici vlastnictví volí projektant (výchozí z presetu).

List RE (stávající, jen dotčená část): přívod XIN (od HDS) → HJ (`fve.breaker_mcb` do 125 A, jinak `mccb`) → přímé
měření (`fve.meter` v sérii) | nepřímé (`fve.ct` v sérii, elektroměr na sekundáru MTP a napětí za MTP) → vypínač
instalace (`sb.main_switch`) → vývod XOUT (k RD / HR). Stejnou funkci měření (`build_metering`) kreslí HR u topologie
`nn_hr_meter` (měření v HR). Blok RE je zrcadlený (přívod XIN vpravo k DS, vývod XOUT vlevo).

Hranice vlastnictví `chain.<role>.boundary`: `hds` (v HDS), `re_main` (svorky HJ), `re_meter` (za elektroměrem) –
atribut `boundary="1"` na prvku (HDS, HJ, elektroměr) a volný text „hranice vlastnictví DS / odběratel“ v blokovém
schématu (`chain._boundary_text`). Neznámé In stávajícího HJ zůstane prázdné s `in_unresolved` (chyba F7).
"""
from __future__ import annotations

from dataclasses import dataclass

from envocad.generator.boards.base import ChainContext, ChainPorts
from envocad.generator.context import _num, _s
from envocad.generator.spec import chain_options, node_desc, node_ref
from envocad.library.templates import AC_CONDUCTORS, _el, _feed, _place_sequential, _wire
from envocad.model.project import Element, Project, Sheet
from envocad.model.topology import ChainNode

METERING = {"direct": "direct", "přímé": "direct", "primé": "direct", "prime": "direct",
            "indirect": "indirect", "nepřímé": "indirect", "neprime": "indirect", "mtp": "indirect"}
BOUNDARIES = ("hds", "re_main", "re_meter")
BOUNDARY_TEXT = "hranice vlastnictví DS / odběratel"
MCB_MAX_IN = 125.0           # HJ do 125 A jistič MCB, nad výkonový jistič MCCB
CT_CONDUCTORS = ["S1", "S2"]
MEAS_PITCH = 30.0            # svislý rozestup přístrojů funkce měření


def metering_mode(v, where: str) -> str:
    """„direct“ | „indirect“ z volby (i česky „přímé“ / „nepřímé“, „MTP“); prázdné = přímé. Jinak ValueError."""
    t = _s(v).strip().lower()
    if not t:
        return "direct"
    if t not in METERING:
        raise ValueError(f"{where}: neznámé měření „{v}“ – zadejte direct (přímé) nebo indirect (nepřímé, MTP).")
    return METERING[t]


def boundary_mode(v, where: str) -> str:
    """Hranice vlastnictví: „hds“ | „re_main“ | „re_meter“ (prázdné = hds). Jinak ValueError."""
    t = _s(v).strip().lower()
    if not t:
        return "hds"
    if t not in BOUNDARIES:
        raise ValueError(f"{where}: neznámá hranice vlastnictví „{v}“ – zadejte hds, re_main (svorky hlavního "
                         "jističe) nebo re_meter (za elektroměrem).")
    return t


@dataclass
class Metering:
    """Výsledek `build_metering`: vstup a výstup sloupce (prvek, port), HJ, elektroměr, MTP (nepřímé), vypínač."""
    top: tuple[Element, str]
    bottom: tuple[Element, str]
    main: Element
    meter: Element
    ct: Element | None
    switch: Element


def ct_ratio_for(in_a: float | None) -> str:
    """Převod MTP pro In hlavního jističe: nejbližší normalizovaný primár ≥ In („200/5 A“); neznámé In → ""."""
    from envocad.generator.boards.mv import CT_PRIMARY_SIZES, _next_size
    return f"{_next_size(in_a, CT_PRIMARY_SIZES):g}/5 A" if in_a else ""


def build_metering(p: Project, sheet: Sheet, x: float, y0: float, opts: dict, where: str,
                   role: str = "re") -> Metering:
    """Funkce měření shora dolů ve sloupci `x` od `y0` (osa HJ): HJ → elektroměr (přímé) | MTP s elektroměrem
    vpravo (nepřímé) → vypínač instalace. `opts` = volby článku (`main_in`, `char`, `metering`, `ct_ratio`,
    `switch_in`, `boundary`); `where` = označení článku pro hlášky („RE“, „HR“), `role` = klíč `chain.<role>`."""
    mode = metering_mode(opts.get("metering"), where)
    boundary = boundary_mode(opts.get("boundary"), where)
    main_in = _s(opts.get("main_in")).strip()
    i_main = _num(main_in)
    big = i_main is not None and i_main > MCB_MAX_IN
    hj_attrs = {"in_": main_in, "poles": "3", "modules": "6" if big else "3"}
    if not big:
        hj_attrs["char"] = _s(opts.get("char") or "B")
    hj = _el(p, sheet, "fve.breaker_mccb" if big else "fve.breaker_mcb", x, y0, "Q", rot=270, **hj_attrs)
    hj.attrs["desc"] = "hlavní jistič před elektroměrem"
    hj.attrs["chain"] = "meter_main"
    if not main_in:
        hj.attrs["in_unresolved"] = (f"{where}: In stávajícího hlavního jističe před elektroměrem není zadané – "
                                     f"doplňte chain.{role}.main_in")
    ct = None
    if mode == "direct":
        meter = _el(p, sheet, "fve.meter", x, y0 - MEAS_PITCH, "P", rot=270, kind="fakturační (DS)", modules="0")
        _wire(p, sheet, hj, "2", meter, "1", AC_CONDUCTORS)
        last, y_q = meter, y0 - 2 * MEAS_PITCH
    else:
        y_ct = y0 - MEAS_PITCH
        ratio = _s(opts.get("ct_ratio")).strip() or ct_ratio_for(i_main)
        ct = _el(p, sheet, "fve.ct", x, y_ct, "TA", rot=270, ratio=ratio, cls="0,5S", burden="5", n="3", poles="3")
        # elektroměr vpravo od MTP: proud ze sekundáru (S vpravo) shora do 1, napětí za MTP zdola do 2
        meter = _el(p, sheet, "fve.meter", x + 35.0, y_ct - 25.0, "P", rot=270, kind="fakturační (DS)",
                    modules="0")
        _wire(p, sheet, hj, "2", ct, "1", AC_CONDUCTORS)
        _wire(p, sheet, ct, "S", meter, "1", CT_CONDUCTORS).points = [(x + 35.0, y_ct)]
        _wire(p, sheet, ct, "2", meter, "2", AC_CONDUCTORS[:4]).points = [
            (x + 20.0, y_ct - 7.5), (x + 20.0, y_ct - 40.0), (x + 35.0, y_ct - 40.0)]
        last, y_q = ct, y_ct - 50.0
    switch_in = _s(opts.get("switch_in")).strip() or main_in
    q = _el(p, sheet, "sb.main_switch", x, y_q, "Q", rot=270, in_=switch_in, poles="4", modules="4")
    q.attrs["desc"] = "vypínač instalace"
    q.attrs["chain"] = "inst_switch"
    _wire(p, sheet, last, "2", q, "1", AC_CONDUCTORS)
    if boundary == "re_main":
        hj.attrs["boundary"] = "1"
    elif boundary == "re_meter":
        meter.attrs["boundary"] = "1"
    return Metering((hj, "1"), (q, "2"), hj, meter, ct, q)


def metering_text(opts: dict) -> str:
    """Měření do popisku bloku bez listu: „přímé“ | „nepřímé, MTP 300/5 A“."""
    mode = metering_mode(opts.get("metering"), "")
    if mode == "direct":
        return "přímé"
    ratio = _s(opts.get("ct_ratio")).strip() or ct_ratio_for(_num(_s(opts.get("main_in")).strip()))
    return f"nepřímé, MTP {ratio}" if ratio else "nepřímé (MTP)"


def build_meter_sheet(p: Project, sheet: Sheet, opts: dict, where: str = "RE", role: str = "re") -> Metering:
    """List RE na nn: přívod XIN nahoře (od HDS) → funkce měření → vývod XOUT dole (k RD / HR)."""
    x, y0 = 60.0, 200.0
    m_in = _s(opts.get("main_in")).strip()
    sheet.layout.params.setdefault("network", "3NPE, 50 Hz")
    sheet.layout.params.setdefault("un", "230/400 V")
    if m_in:
        sheet.layout.params.setdefault("in_", m_in)
    feed = _feed(p, sheet, "in", x, y0 + 35.0, "", rot=180, desc="od HDS")
    feed.attrs["ref"] = "XIN"
    m = build_metering(p, sheet, x, y0, opts, where, role)
    _wire(p, sheet, feed, "1", *m.top, AC_CONDUCTORS)
    q, port = m.bottom
    out = _feed(p, sheet, "out", x, q.y - 35.0, "", desc="do objektu")
    out.attrs["ref"] = "XOUT"
    _wire(p, sheet, q, port, out, "1", AC_CONDUCTORS)
    _place_sequential(sheet, [e for e in (m.main, m.ct, m.switch) if e is not None])
    return m


class MeterBoardBuilder:
    """Role `re` při připojení na nn – stávající elektroměrový rozvaděč (u vn obsluhuje RE builder `mv`). Výchozí jen
    blok (přívod XIN, vývod XOUT, v popisku HJ a měření); list vestavěným kódem s volbou `chain.re.builtin` /
    standard `ac_builtin`."""
    name = "re"
    linked = True

    def block(self, ctx: ChainContext, node: ChainNode) -> Element:
        from envocad.generator.spec import builtin_wanted
        o = chain_options(ctx.spec, ctx.topology, node.role)
        el = Element("fve.switchboard", ctx.next_x(board=True), 150.0, mirror=True, attrs={
            "ref": node_ref(ctx.spec, ctx.topology, node.role, default="RE"),
            "desc": node_desc(ctx.spec, ctx.topology, node.role, default="elektroměrový rozvaděč")})
        ctx.sheet.elements.append(el)
        main_in = _s(o.get("main_in")).strip()
        ctx.node_in[node.role] = main_in
        boundary = boundary_mode(o.get("boundary"), el.ref)       # neplatná hranice → ValueError hned
        metering_mode(o.get("metering"), el.ref)
        if not builtin_wanted(ctx.spec, ctx.topology, node.role):
            el.attrs.update({"ports_in": "XIN", "ports_out": "XOUT",
                             "main": "hlavní jistič před elektroměrem" + (f" {main_in} A" if main_in else ""),
                             "metering": metering_text(o)})
            ctx.boundary = (el, boundary)
        return el

    def ports(self, ctx: ChainContext, node: ChainNode) -> ChainPorts:
        return ChainPorts(("XOUT",), "XIN")

    def build(self, ctx: ChainContext, node: ChainNode) -> None:
        from envocad.generator.spec import builtin_wanted
        if not builtin_wanted(ctx.spec, ctx.topology, node.role):
            return                        # jen blok (údaje v atributech)
        blk = ctx.blocks[node.role]
        o = chain_options(ctx.spec, ctx.topology, node.role)
        build_meter_sheet(ctx.project, ctx.project.create_switchboard_sheet(blk), o, blk.ref or "RE", node.role)
        ctx.boundary = (blk, boundary_mode(o.get("boundary"), blk.ref))


BUILDER = MeterBoardBuilder()
