"""Stávající domovní rozvaděč RD / hlavní rozvaděč HR jako článek řetězce na nn (bez Qt) – jedna implementace pro
role `rd` a `hr`. Návrh docs/design/topologie_f1_f2.md, kap. 2 bod 5; rozhodnutí 4 a 6 (docs/NAVRH_TOPOLOGIE.md, kap. 8).

Kreslí se jen dotčená část: přívod XIN (od RE / HDS) → hlavní přístroj (`main_device` `switch` = vypínač, výchozí RD |
`breaker` = jistič, výchozí HR; In `main_in`) → přípojnice → vývod FVE X1 (`fve_device` `breaker` | `fuse_disconnect`,
In `fve_in`) a vývod „stávající rozvody“ X2 (v blokovém schématu `fve.load`). **Do 80 A vždy jistič:** pojistkový
odpínač s In ≤ 80 A → ValueError. `fve_in` prázdné → nejbližší jistič ≥ Σ In střídačů; stávající `main_in` neznámé →
prázdné + `in_unresolved` (chyba F7). Měření v HR (`metering` – topologie `nn_hr_meter`) = stejná funkce jako v RE
(`meter_board.build_metering`: HJ → elektroměr / MTP → vypínač instalace) místo hlavního přístroje.
"""
from __future__ import annotations

from envocad.generator.boards.base import ChainContext, ChainPorts
from envocad.generator.boards.meter_board import MCB_MAX_IN, boundary_mode, build_metering, metering_mode
from envocad.generator.context import _num, _s
from envocad.generator.spec import chain_options, node_desc, node_ref
from envocad.library.templates import AC_CONDUCTORS, _el, _feed, _place_sequential, _wire
from envocad.model.project import Element, Wire, WireEnd
from envocad.model.topology import ChainNode

MAIN_DEVICES = {"switch": "switch", "vypínač": "switch", "vypinac": "switch",
                "breaker": "breaker", "jistič": "breaker", "jistic": "breaker"}
FVE_DEVICES = {"breaker": "breaker", "jistič": "breaker", "jistic": "breaker",
               "fuse_disconnect": "fuse_disconnect", "fuse": "fuse_disconnect", "pojistka": "fuse_disconnect",
               "pojistkový odpínač": "fuse_disconnect"}
FVE_FUSE_MIN_IN = 80.0       # do 80 A včetně vždy jistič (rozhodnutí 4)
DEFAULT_DESC = {"rd": "domovní rozvaděč", "hr": "hlavní rozvaděč"}
DEFAULT_MAIN = {"rd": "switch", "hr": "breaker"}
LOAD_DESC = "stávající rozvody objektu"


def _choice(table: dict, v, default: str, where: str, what: str, allowed: str) -> str:
    t = _s(v).strip().lower()
    if not t:
        return default
    if t not in table:
        raise ValueError(f"{where}: neznámý {what} „{v}“ – zadejte {allowed}.")
    return table[t]


def fve_feeder_in(ctx: ChainContext, o: dict, where: str) -> str:
    """In vývodu FVE: zadané `fve_in`, jinak nejbližší jistič ≥ Σ In střídačů (`mv.inverters_ac_current`)."""
    from envocad.generator.boards.mv import LV_FEEDER_SIZES, _next_size, inverters_ac_current
    given = _s(o.get("fve_in")).strip()
    if given:
        return given
    i_fve = inverters_ac_current(ctx.inverters)
    return f"{_next_size(i_fve, LV_FEEDER_SIZES):g}" if i_fve else ""


def resolve_options(ctx: ChainContext, node: ChainNode, where: str) -> dict:
    """Volby článku RD / HR ověřené a doplněné: `main_device`, `fve_device`, `fve_in` (ValueError česky)."""
    o = chain_options(ctx.spec, ctx.topology, node.role)
    o["main_device"] = _choice(MAIN_DEVICES, o.get("main_device"), DEFAULT_MAIN.get(node.role, "breaker"), where,
                               "hlavní přístroj", "switch (vypínač) nebo breaker (jistič)")
    o["fve_device"] = _choice(FVE_DEVICES, o.get("fve_device"), "breaker", where, "přístroj vývodu FVE",
                              "breaker (jistič) nebo fuse_disconnect (pojistkový odpínač)")
    o["fve_in"] = fve_feeder_in(ctx, o, where)
    fin = _num(o["fve_in"])
    if o["fve_device"] == "fuse_disconnect" and (fin is None or fin <= FVE_FUSE_MIN_IN):
        shown = f"{fin:g} A" if fin is not None else "neurčené In"
        raise ValueError(f"{where}: vývod FVE do {FVE_FUSE_MIN_IN:g} A musí být jistič – pojistkový odpínač jen nad "
                         f"{FVE_FUSE_MIN_IN:g} A (zadáno {shown}). Zvolte fve_device breaker, nebo fve_in nad "
                         f"{FVE_FUSE_MIN_IN:g} A.")
    o["metering"] = _s(o.get("metering")).strip()
    if o["metering"]:
        o["metering"] = metering_mode(o["metering"], where)
        boundary_mode(o.get("boundary"), where)
    return o


def build_house_sheet(ctx: ChainContext, sheet, o: dict, where: str, role: str, fve_ref: str) -> None:
    """List RD / HR (dotčená část): přívod XIN → hlavní přístroj (nebo funkce měření) → přípojnice → vývod FVE X1,
    vývod stávajících rozvodů X2."""
    p = ctx.project
    x0 = 60.0
    main_in = _s(o.get("main_in")).strip()
    sheet.layout.params.setdefault("network", "3NPE, 50 Hz")
    sheet.layout.params.setdefault("un", "230/400 V")
    if main_in:
        sheet.layout.params.setdefault("in_", main_in)
    feed = _feed(p, sheet, "in", x0, 235.0, "", rot=180, desc="od RE / HDS")
    feed.attrs["ref"] = "XIN"
    devices = []
    if o["metering"]:
        m = build_metering(p, sheet, x0, 200.0, {**o, "metering": o["metering"]}, where, role)
        _wire(p, sheet, feed, "1", *m.top, AC_CONDUCTORS)
        last, last_port = m.bottom
        devices += [e for e in (m.main, m.ct, m.switch) if e is not None]
    else:
        i_main = _num(main_in)
        if o["main_device"] == "switch":
            q = _el(p, sheet, "sb.main_switch", x0, 200.0, "Q", rot=270, in_=main_in, poles="4", modules="4")
            q.attrs["desc"] = "hlavní vypínač"
        else:
            big = i_main is not None and i_main > MCB_MAX_IN
            q = _el(p, sheet, "fve.breaker_mccb" if big else "fve.breaker_mcb", x0, 200.0, "Q", rot=270, in_=main_in,
                    poles="3", modules="6" if big else "3", **({} if big else {"char": "B"}))
            q.attrs["desc"] = "hlavní jistič"
        if not main_in:
            q.attrs["in_unresolved"] = (f"{where}: In stávajícího hlavního přístroje není zadané – doplňte "
                                        f"chain.{role}.main_in")
        _wire(p, sheet, feed, "1", q, "1", AC_CONDUCTORS)
        last, last_port = q, "2"
        devices.append(q)
    y_bus = last.y - 35.0
    bus = _el(p, sheet, "sb.busbar", x0 + 75.0, y_bus, "", desc="přípojnice", in_=main_in,
              conductors=" ".join(AC_CONDUCTORS))
    bus.attrs["ref"] = "1"
    _wire(p, sheet, last, last_port, bus, "IN", AC_CONDUCTORS)
    fve_in = o["fve_in"]
    if o["fve_device"] == "fuse_disconnect":
        qf = _el(p, sheet, "fve.fuse_disconnect", x0 + 7.5, y_bus - 35.0, "F", rot=270, in_=fve_in, char="gG",
                 un="400", poles="3", modules="6")
    else:
        big = (_num(fve_in) or 0) > MCB_MAX_IN
        qf = _el(p, sheet, "fve.breaker_mccb" if big else "fve.breaker_mcb", x0 + 7.5, y_bus - 35.0, "Q", rot=270,
                 in_=fve_in, poles="3", modules="6" if big else "3", **({} if big else {"char": "B"}))
    qf.attrs["desc"] = "vývod FVE"
    if not fve_in:
        qf.attrs["in_unresolved"] = f"{where}: proud FVE neznámý (střídače bez P AC) – doplňte chain.{role}.fve_in"
    out_f = _feed(p, sheet, "out", x0 + 7.5, y_bus - 70.0, "", desc=f"k {fve_ref} (FVE)" if fve_ref else "k FVE")
    out_f.attrs["ref"] = "X1"
    out_s = _feed(p, sheet, "out", x0 + 67.5, y_bus - 70.0, "", desc=_s(o.get("load") or LOAD_DESC))
    out_s.attrs["ref"] = "X2"
    _wire(p, sheet, bus, "1", qf, "1", AC_CONDUCTORS)
    _wire(p, sheet, qf, "2", out_f, "1", AC_CONDUCTORS)
    _wire(p, sheet, bus, "5", out_s, "1", AC_CONDUCTORS)
    _place_sequential(sheet, [*devices, qf])


class HouseBoardBuilder:
    """Role `rd` (domovní rozvaděč) a `hr` (hlavní rozvaděč) na nn – stávající rozvaděč, dotčená část."""
    linked = True

    def __init__(self, role: str):
        self.name = role

    def block(self, ctx: ChainContext, node: ChainNode) -> Element:
        ref = node_ref(ctx.spec, ctx.topology, node.role, default=node.role.upper())
        o = resolve_options(ctx, node, ref)
        el = Element("fve.switchboard", ctx.next_x(board=True), 150.0, mirror=True, attrs={
            "ref": ref, "desc": node_desc(ctx.spec, ctx.topology, node.role, default=DEFAULT_DESC.get(node.role, ""))})
        ctx.sheet.elements.append(el)
        ctx.node_in[node.role] = o["fve_in"]
        # stávající rozvody objektu (vývod X2) – značka spotřeby pod blokem, vodič bez kabelu
        load = Element("fve.load", el.x, 110.0, attrs={"ref": "", "desc": _s(o.get("load") or LOAD_DESC)})
        ctx.sheet.elements.append(load)
        w = Wire(WireEnd(el.id, "X2"), WireEnd(load.id, "1"), conductors=list(AC_CONDUCTORS), attrs={"ref": ""})
        ctx.sheet.wires.append(w)
        ctx.loads.append((el, "X2", load, w))
        return el

    def ports(self, ctx: ChainContext, node: ChainNode) -> ChainPorts:
        return ChainPorts(("X1",), "XIN")

    def build(self, ctx: ChainContext, node: ChainNode) -> None:
        blk = ctx.blocks[node.role]
        o = resolve_options(ctx, node, blk.ref)
        build_house_sheet(ctx, ctx.project.create_switchboard_sheet(blk), o, blk.ref, node.role, ctx.main.ref)
        if o["metering"]:
            ctx.boundary = (blk, boundary_mode(o.get("boundary"), blk.ref))


RD_BUILDER = HouseBoardBuilder("rd")
HR_BUILDER = HouseBoardBuilder("hr")
