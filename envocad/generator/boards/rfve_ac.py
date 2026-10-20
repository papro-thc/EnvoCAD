"""AC rozvaděč FVE (RFVE.AC; AC část RFVE rodinného domu) vestavěným kódem – vše přichází zespodu (bez Qt). Přesun 1:1 z `generate.py`
(refaktoring F1, krok 4)."""
from __future__ import annotations

import re

from envocad.generator import context
from envocad.generator.boards.base import ChainContext, ChainPorts
from envocad.generator.context import (
    _s,
)
from envocad.library.templates import (
    AC_CONDUCTORS,
    GROUP_PITCH,
    _bridge_groups,
    _el,
    _feed,
    _place_sequential,
    _terminal_group,
    _wire,
)
from envocad.model.busbar import OUTS_ATTR, PITCH_ATTR, TAPS_ATTR, BusLayout, layout_of
from envocad.model.project import Element, Project, Sheet, element_symbol
from envocad.model.topology import ChainNode

# ---- AC rozvaděč FVE: vše přichází zespodu ----------------------------------------------------------------------
# Rozhodnutí 3 (docs/design/znacka_privod_vyvod.md): na listu RFVE.AC a RFVE rodinného domu jsou přívody i vývody ve
# spodní řadě (svorka `sb.feed` portem nahoru, kabel zespodu), sběrnice nahoře, přívodní větev teče nahoru do
# sběrnice (svorka X → jistič otočený tokem nahoru → přívod zdola B{k}), jádro visí ze sběrnice dolů. Zleva: XPE
# a SPD, přívody po 30 mm, hlavní vypínač s XOUT za posledním přívodem. Stejně vestavěná makra
# (`tools/gen_builtin_macros.py`). Vícepól se nemění (`multipole.flow_flipped`).
AC_BUS_POS = (165.0, 175.0)     # sběrnice: B1 v x 105 (= přívod X1); parametrická (`model/busbar.py`): vývod 1 (PE)
                                # v x 60 (XPE), 2 v x 82,5 (SPD), přívody B{k} po 30 mm, 3 za posledním přívodem


                                # v x 60 (XPE), 2 v x 82,5 (SPD), přívody B{k} po 30 mm, 3 za posledním přívodem
# pevná sběrnice (bez atributu `taps` – vlastní makra se sběrnicí bez atributu): čára x 90…270, vývody i:
# x − 67,5 + 15·(i − 1), přívody zdola `BUS_B_X`
BUS_B_X = [-60, -30, 0, 30, 60, 90, -45, -15, 15, 45, 75, 105]   # = tools/gen_builtin_fve.BUSBAR_B_X
AC_ROW_BOTTOM = 105.0           # spodní řada: přívody a vývody (port nahoře y + 5)
AC_ROW_DEVICES = 140.0          # přístroje (jističe přívodů, SPD, hlavní vypínač)
AC_FEED_X0 = 105.0              # sloupec přívodu X1 (pod přívodem zdola B1)
AC_CORE_GAP = 37.5              # hlavní vypínač nejméně tolik za posledním přívodem (popisky svorek ve spodní řadě)
BUS_OUTPUTS = 13                # vývody 1…13 zdola (13 = za posledním přívodem zdola B12, pro hlavní vypínač)
BUS_DROP_STEP = 5.0             # rozestup vodorovných úseků lomených odboček ze sběrnice (kontrola souběhu: 5 mm)


def _bus_out_x(bus: Element, i: int) -> float:
    return bus.x - 67.5 + 15.0 * (i - 1)


def _ac_core_after_feeds(project: Project, sheet: Sheet) -> None:
    """Hlavní vypínač a XOUT za poslední přívod zdola (vývod sběrnice, pod kterým stojí, vede svisle bez lomu);
    pak lomy odboček ze sběrnice (`_bus_drop_points`). List bez sběrnice nebo bez hlavního vypínače nemění.
    Parametrická sběrnice (`taps`): počet přívodů podle použitých portů B, hlavní vypínač pod vývod 3 – vše rovně."""
    bus = next((e for e in sheet.elements if e.symbol_id == "sb.busbar"), None)
    if bus is None:
        return
    if layout_of(bus) is not None:
        _ac_core_parametric(project, sheet, bus)
        return
    by_id = {e.id: e for e in sheet.elements}
    feeds_x = [by_id[o].x for w in sheet.wires for end, o in ((w.a, w.b.element_id), (w.b, w.a.element_id))
               if end.element_id == bus.id and end.port.startswith("B") and o in by_id]
    q_wire = next((w for w in sheet.wires if bus.id in (w.a.element_id, w.b.element_id)
                   and by_id.get(w.b.element_id if w.a.element_id == bus.id else w.a.element_id) is not None
                   and by_id[w.b.element_id if w.a.element_id == bus.id else w.a.element_id].symbol_id == "sb.main_switch"),
                  None)
    b_x = _bus_b_ports_by_x(project, sheet, bus)
    if q_wire is not None and feeds_x:
        q = by_id[q_wire.b.element_id if q_wire.a.element_id == bus.id else q_wire.a.element_id]
        want = max(feeds_x) + AC_CORE_GAP
        # vývod hlavního vypínače vpravo od všech použitých přívodů zdola (jinak by jeho odbočka křížila přívod)
        right = [i for i in range(1, BUS_OUTPUTS + 1) if _bus_out_x(bus, i) > b_x + 1e-6] or [BUS_OUTPUTS]
        i = next((i for i in right if _bus_out_x(bus, i) >= want - 1e-6), right[0])
        # víc než 6 přívodů: za koncem sběrnice, odbočka z vývodu za posledním přívodem s lomem
        x = max(_bus_out_x(bus, i), round(want / 2.5) * 2.5)
        dx = x - q.x
        for w in sheet.wires:          # hlavní vypínač a vše pod ním (XOUT) se posune
            if w.touches(q.id):
                o = by_id[w.b.element_id if w.a.element_id == q.id else w.a.element_id]
                if o is not bus and o.y < q.y:
                    o.x += dx
        q.x = x
        end = q_wire.a if q_wire.a.element_id == bus.id else q_wire.b
        end.port = str(i)
    _bus_drop_points(project, sheet, bus)


def _ac_core_parametric(project: Project, sheet: Sheet, bus: Element) -> None:
    """Parametrická sběrnice: `taps` = nejvyšší použitý přívod B{k} (žádný navíc), hlavní vypínač (a XOUT pod ním)
    rovně pod vývod 3 za posledním přívodem. Odbočky, které přesto nejsou svisle, dostanou lomy (`_bus_drop_points`)."""
    by_id = {e.id: e for e in sheet.elements}
    ends = [(end, other) for w in sheet.wires for end, other in ((w.a, w.b), (w.b, w.a)) if end.element_id == bus.id]
    ks = [int(end.port[1:]) for end, _o in ends if re.fullmatch(r"B\d+", end.port)]
    if ks:
        bus.attrs[TAPS_ATTR] = str(max(ks))
    q_end = next(((end, by_id[o.element_id]) for end, o in ends
                  if o.element_id in by_id and by_id[o.element_id].symbol_id == "sb.main_switch"), None)
    if q_end is not None:
        end, q = q_end
        if not re.fullmatch(r"\d+", end.port) or int(end.port) < 3:
            end.port = "3"
        lay = layout_of(bus, {e.port for e, _o in ends})
        dx = bus.x + lay.out_x(end.port) - q.x
        for w in sheet.wires:          # hlavní vypínač a vše pod ním (XOUT) se posune
            if w.touches(q.id):
                o = by_id.get(w.b.element_id if w.a.element_id == q.id else w.a.element_id)
                if o is not None and o is not bus and o.y < q.y:
                    o.x += dx
        q.x += dx
    _bus_drop_points(project, sheet, bus)


def _bus_b_ports_by_x(project: Project, sheet: Sheet, bus: Element) -> float:
    """Víc než 6 přívodů zdola (B7…B12 leží mezi B1…B6): k-tý přívod zleva dostane k-tý port B zleva, odbočky
    (`_bus_drop_points`) jsou pak schody bez křížení (vlevo nejníž). Do 6 přívodů beze změny (B1…B6 svisle pod
    přívody po 30 mm). Vrací x nejpravějšího použitého portu B (bez přívodů zdola −∞)."""
    sym = element_symbol(project, bus, context._lib())
    bx = {p.name: bus.x + p.x for p in sym.ports if p.name.startswith("B")}
    by_id = {e.id: e for e in sheet.elements}
    ends = []
    for w in sheet.wires:
        for end, other in ((w.a, w.b), (w.b, w.a)):
            if end.element_id == bus.id and end.port in bx and other.element_id in by_id:
                ends.append((by_id[other.element_id].x, end))
    if len(ends) > 6:
        ports = sorted(bx, key=lambda n: bx[n])
        for (_x, end), name in zip(sorted(ends, key=lambda t: t[0]), ports):
            end.port = name
    return max((bx[end.port] for _x, end in ends), default=float("-inf"))


def _bus_drop_points(project: Project, sheet: Sheet, bus: Element) -> None:
    """Odbočky ze spodních portů sběrnice k přístroji pod ní, které nejsou svisle pod portem (a nemají ruční lomy):
    lom svisle–vodorovně–svisle. Vodorovné úseky po `BUS_DROP_STEP` pod sebou tak, aby se odbočky nekřížily:
    lomené doprava – nejpravější nejvýš, doleva – nejlevější nejvýš."""
    lib = context._lib()
    sym_bus = element_symbol(project, bus, lib)
    right, left = [], []
    for w in sheet.wires:
        if w.points or bus.id not in (w.a.element_id, w.b.element_id) or w.a.element_id == w.b.element_id:
            continue
        be, oe = (w.a, w.b) if w.a.element_id == bus.id else (w.b, w.a)
        o = sheet.element(oe.element_id)
        try:
            px, py = bus.port_pos(sym_bus, be.port)
            ox, oy = o.port_pos(element_symbol(project, o, lib), oe.port)
        except (KeyError, StopIteration, AttributeError):
            continue
        if oy >= py or abs(ox - px) < 1e-6:
            continue
        (right if ox > px else left).append((px, ox, oy, w, be is w.a))
    # schody odboček se musí vejít nad přístroje (víc než 6 přívodů zdola): jinak se sběrnice zvedne
    lift = 0.0
    for group in (right, left):
        if group:
            lowest = bus.y - 5.0 - BUS_DROP_STEP * len(group)
            lift = max(lift, max(oy for _px, _ox, oy, _w, _b in group) + 2.5 - lowest)
    if lift > 1e-6:
        bus.y += -(-lift // 2.5) * 2.5
    top = bus.y - 5.0 - BUS_DROP_STEP
    for group, rising in ((sorted(right, key=lambda t: t[0]), True), (sorted(left, key=lambda t: t[0]), False)):
        n = len(group)
        for k, (px, ox, oy, w, bus_first) in enumerate(group):
            level = (n - 1 - k) if rising else k
            y = max(top - level * BUS_DROP_STEP, oy + 2.5)
            pts = [(px, y), (ox, y)]
            w.points = pts if bus_first else pts[::-1]


def _build_ac_switchboard(project: Project, sheet: Sheet, invs: list[dict], ac: dict, spec: dict) -> None:
    """AC rozvaděč FVE (bez maker): přívody od střídačů (X1…Xn) zespodu → jističe → rozvod → hlavní vypínač → vývod do
    HDS; SPD, PE (XPE nebo PE lišta). Rozvod podle `ac.distribution`: "bus" = sběrnice potenciálů (vodič, jako
    v EPLAN; geometrie jako vestavěná makra), "terminals" = rozvodné svorky s můstky (skupiny nahoře místo sběrnice)."""
    nc = len(AC_CONDUCTORS)
    n = len(invs)
    use_bus = (ac.get("distribution") or "bus") == "bus"
    feeds: list[Element] = []
    breakers: list[Element] = []
    groups: list[Element] = []
    firsts: list[int] = []
    strip = "X" + str(n + 1)
    y = 200.0
    x0 = AC_FEED_X0 if use_bus else 60.0
    bus = None
    if use_bus:
        bus = _el(project, sheet, "sb.busbar", *AC_BUS_POS, "", desc="rozvod AC", in_=str(ac.get("main_in") or 125),
                  conductors=" ".join(AC_CONDUCTORS))
        bus.attrs["ref"] = "1"   # předpona potenciálů: 1L1, 1L2, 1L3, 1N, 1PE
        # parametrická sběrnice: přívod B{k} rovně nad jističem k, vývody 1 (PE) a 2 (SPD) vlevo, 3 (hlavní vypínač)
        bus.attrs.update({TAPS_ATTR: str(n), OUTS_ATTR: "1", PITCH_ATTR: f"{GROUP_PITCH:g}"})
    for i, inv in enumerate(invs):
        x = x0 + i * GROUP_PITCH
        feed = _feed(project, sheet, "in", x, AC_ROW_BOTTOM, "", desc=f"od {inv.get('ref') or f'T{i + 1}'}")
        feed.attrs["ref"] = f"X{i + 1}"
        f = _el(project, sheet, "fve.breaker_mcb", x, AC_ROW_DEVICES, "F", rot=90, in_=str(ac.get("breaker_in") or 40),
                char="B", poles="3", modules="3")
        _wire(project, sheet, feed, "1", f, "1", AC_CONDUCTORS)
        if use_bus:
            _wire(project, sheet, f, "2", bus, f"B{i + 1}", AC_CONDUCTORS)   # zdola
        else:
            first = 1 + i * nc
            firsts.append(first)
            grp = _terminal_group(project, sheet, x, y - 30, strip, first, nc, f"střídač {i + 1}")
            grp.rotation = 180    # vstup skupiny (port 1) dole: větev přívodu teče nahoru (vícepól: jako dřív shora)
            _wire(project, sheet, f, "2", grp, "1", AC_CONDUCTORS)
            groups.append(grp)
        feeds.append(feed)
        breakers.append(f)
    if use_bus:
        lay = BusLayout(n, 1, GROUP_PITCH)
        x_spd, x_pe, x_q = (bus.x + lay.out_x(o) for o in ("2", "1", "3"))
        spd = _el(project, sheet, "fve.spd", x_spd, AC_ROW_DEVICES, "F", spd_type=_s(ac.get("spd") or "T1+T2"), poles="4",
                  modules="4")
        xpe = _feed(project, sheet, "out", x_pe, AC_ROW_BOTTOM, "", desc="k HOP")
        xpe.attrs["ref"] = "XPE"
        q = _el(project, sheet, "sb.main_switch", x_q, AC_ROW_DEVICES, "Q", rot=270, in_=str(ac.get("main_in") or 125),
                poles="4", modules="4")
        out = _feed(project, sheet, "out", x_q, AC_ROW_BOTTOM, "", desc="do HDS / DS")
        out.attrs["ref"] = "XOUT"
        # PE je potenciál sběrnice; SPD i PE rozvaděče jdou na ekvipotenciální svorkovnici (HOP) vně – vývod XPE.
        # Odbočky ze sběrnice svisle (vývod 2 nad SPD, 1 nad XPE, 3 nad hlavním vypínačem), jen PE svodiče s lomem
        _wire(project, sheet, bus, "2", spd, "L", AC_CONDUCTORS[:4])
        _wire(project, sheet, spd, "PE", xpe, "1", ["PE"]).points = [(x_spd, 120.0), (x_pe, 120.0)]
        _wire(project, sheet, bus, "1", xpe, "1", ["PE"])
        _wire(project, sheet, bus, "3", q, "1", AC_CONDUCTORS)
        _wire(project, sheet, q, "2", out, "1", AC_CONDUCTORS)
        _place_sequential(sheet, [q, spd, *breakers])
        _ac_core_after_feeds(project, sheet)
    else:
        x_spd = x0 + n * GROUP_PITCH
        x_out = x0 + (n + 1) * GROUP_PITCH
        spd = _el(project, sheet, "fve.spd", x_spd, y - 60, "F", spd_type=_s(ac.get("spd") or "T1+T2"), poles="4", modules="4")
        q = _el(project, sheet, "sb.main_switch", x_out, y - 60, "Q", rot=270, in_=str(ac.get("main_in") or 125), poles="4", modules="4")
        out = _feed(project, sheet, "out", x_out, y - 95, "", desc="do HDS / DS")
        out.attrs["ref"] = "XOUT"
        pe = _el(project, sheet, "sb.pe_bar", x_spd + 7.5, y - 90, "X", kind="PE")   # port 2 pod SPD, port 1 vlevo
        # skupina pro SPD a skupina pro hlavní vypínač / vývod
        first = 1 + n * nc
        firsts.append(first)
        g_spd = _terminal_group(project, sheet, x_spd, y - 30, strip, first, nc, "SPD")
        first = 1 + (n + 1) * nc
        firsts.append(first)
        g_out = _terminal_group(project, sheet, x_out, y - 30, strip, first, nc, "vývod")
        project.set_bridges(strip, _bridge_groups(firsts, nc), sheet)
        _wire(project, sheet, g_spd, "2", spd, "L", AC_CONDUCTORS[:4])
        _wire(project, sheet, g_spd, "2", pe, "1", ["PE"]).points = [(x_spd, 160.0), (x_spd - 5.0, 160.0)]   # PE skupiny
        _wire(project, sheet, g_out, "2", q, "1", AC_CONDUCTORS)
        _wire(project, sheet, spd, "PE", pe, "2", ["PE"])
        _wire(project, sheet, q, "2", out, "1", AC_CONDUCTORS)
        # skupiny rozvodných svorek zabírají na liště počet svorek × šířka svorky (`Element.modules`)
        _place_sequential(sheet, [q, spd, *breakers, *groups, g_spd, g_out])
    if ac.get("enclosure"):
        sheet.layout.params["type"] = _s(ac["enclosure"])


def build_main_sheet(ctx: ChainContext) -> Sheet:
    """List hlavního AC článku (`ctx.main` – RFVE.AC, u rodinného domu AC část RFVE): přívody od střídačů z maker
    `ac_feed` + `ac_core` (jen rozvod sběrnicí), jinak `_build_ac_switchboard`. Listy DC rozvaděčů vzniknou před ním."""
    from envocad.generator.boards.macro_glue import _ac_box_from_macros
    from envocad.generator.boards.rfve_dc import build_dc_sheets
    build_dc_sheets(ctx)
    p, spec = ctx.project, ctx.spec
    invs, ac = spec.get("inverters") or [], spec["ac"]
    sb = p.create_switchboard_sheet(ctx.main)
    sb.layout.params.setdefault("network", "3NPE, 50 Hz")
    sb.layout.params.setdefault("un", "230/400 V")
    sb.layout.params.setdefault("in_", _s(ac.get("main_in") or 125))
    if not _ac_box_from_macros(p, sb, invs, ac, spec.get("macros") or {}):
        _build_ac_switchboard(p, sb, invs, ac, spec)
    ctx.done.add("main")
    return sb


class RfveAcBuilder:
    """Role `rfve_ac` – AC rozvaděč FVE: blok vzniká před stringy (`chain.create_main_block`), přívody X1…Xn od
    střídačů, vývod XOUT k síti; list z maker nebo kódem (před ním listy DC rozvaděčů)."""
    name = "rfve_ac"

    def block(self, ctx: ChainContext, node: ChainNode) -> Element | None:
        return ctx.main

    def ports(self, ctx: ChainContext, node: ChainNode) -> ChainPorts:
        return ChainPorts(tuple(f"X{i + 1}" for i in range(len(ctx.inverters))), "XOUT")

    def build(self, ctx: ChainContext, node: ChainNode) -> None:
        build_main_sheet(ctx)


BUILDER = RfveAcBuilder()
