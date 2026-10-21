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
from envocad.model.feed import is_feed
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
        _shift(sheet, [q, *_below(sheet, q, bus)], dx)     # hlavní vypínač a vše pod ním (XOUT) se posune
    # další vývody vpravo (4… – síťová ochrana) rovně pod svůj port za hlavním vypínačem; počet vývodů vpravo
    # (`outs`) podle nejvyššího použitého
    right = [int(e.port) for e, _o in ends if re.fullmatch(r"\d+", e.port) and int(e.port) >= 3]
    if right:
        bus.attrs[OUTS_ATTR] = str(max(int(_s(bus.attrs.get(OUTS_ATTR)) or 1), max(right) - 2))
    lay = layout_of(bus, {e.port for e, _o in ends})
    for end, o in ends:
        el = by_id.get(o.element_id)
        if el is None or el.symbol_id == "sb.main_switch" or not re.fullmatch(r"\d+", end.port) or int(end.port) < 4:
            continue
        dx = bus.x + lay.out_x(end.port) - el.x
        _shift(sheet, [el, *_below(sheet, el, bus)], dx)   # i přístroje pod jističem (ochrana, přepínač, svorky)
    _bus_drop_points(project, sheet, bus)


def _shift(sheet: Sheet, els: list[Element], dx: float) -> None:
    """Posun prvků o `dx` i s lomy vodičů mezi nimi."""
    if abs(dx) < 1e-9:
        return
    ids = {e.id for e in els}
    for e in els:
        e.x += dx
    for w in sheet.wires:
        if w.a.element_id in ids and w.b.element_id in ids and w.points:
            w.points = [(x + dx, y) for x, y in w.points]


def _below(sheet: Sheet, el: Element, bus: Element) -> list[Element]:
    """Prvky zapojené pod `el` (po vodičích směrem dolů, bez sběrnice) – posouvají se s ním."""
    by_id = {e.id: e for e in sheet.elements}
    out: list[Element] = []
    seen, todo = {el.id, bus.id}, [el]
    while todo:
        cur = todo.pop()
        for w in sheet.wires:
            if not w.touches(cur.id):
                continue
            o = by_id.get(w.b.element_id if w.a.element_id == cur.id else w.a.element_id)
            if o is not None and o.id not in seen and o.y < cur.y:
                seen.add(o.id)
                out.append(o)
                todo.append(o)
    return out


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


GRID_PROTECTION_SYMBOL = "fve.grid_protection"


GP_FUSE_IN = "6"           # jištění měřicího vstupu U síťové ochrany (jistič 4p B6 – požadavek na mustr, D5)
GP_Y, GP_FUSE_Y = 125.0, 150.0   # ochrana (port U v y 132,5) a jistič měřicího vstupu nad ní (sběrnice 170)


def _grid_protection(project: Project, sheet: Sheet, x: float, y: float, source: Element,
                     port: str) -> list[Element]:
    """Síťová ochrana (U<, U>, f<, f>): měření z rozvodu (`source` / `port`) přes jistič měřicího vstupu (port U
    nahoře), působí na hlavní (vazební) vypínač s vypínací spouští – `acts_on` a `trip` doplní `mark_chain_devices`
    (označení vypínače je známé až po vložení). Vrací [ochrana, jistič měřicího vstupu]."""
    gp = _el(project, sheet, GRID_PROTECTION_SYMBOL, x, y - (AC_ROW_DEVICES - GP_Y), "F", modules="4")
    fu = _el(project, sheet, "fve.breaker_mcb", x, y + (GP_FUSE_Y - AC_ROW_DEVICES), "F", rot=270, in_=GP_FUSE_IN,
             char="B",
             poles="4", modules="4")
    fu.attrs["desc"] = "jištění měřicího vstupu"
    _wire(project, sheet, source, port, fu, "1", AC_CONDUCTORS[:4])
    _wire(project, sheet, fu, "2", gp, "U", AC_CONDUCTORS[:4])
    return [gp, fu]


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
        extra = []
        if ac.get("grid_protection"):      # síťová ochrana: měří z přípojnice (vývod 4 za hlavním vypínačem)
            extra += _grid_protection(project, sheet, x_q + GROUP_PITCH, AC_ROW_DEVICES, bus, "4")
        _place_sequential(sheet, [q, *extra, spd, *breakers])
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
        g_gp = None
        if ac.get("grid_protection"):      # síťová ochrana: vlastní skupina rozvodných svorek (svisle do jističe U)
            first = 1 + (n + 2) * nc
            firsts.append(first)
            g_gp = _terminal_group(project, sheet, x_out + GROUP_PITCH, y - 30, strip, first, nc, "síťová ochrana")
        project.set_bridges(strip, _bridge_groups(firsts, nc), sheet)
        _wire(project, sheet, g_spd, "2", spd, "L", AC_CONDUCTORS[:4])
        _wire(project, sheet, g_spd, "2", pe, "1", ["PE"]).points = [(x_spd, 160.0), (x_spd - 5.0, 160.0)]   # PE skupiny
        _wire(project, sheet, g_out, "2", q, "1", AC_CONDUCTORS)
        _wire(project, sheet, spd, "PE", pe, "2", ["PE"])
        _wire(project, sheet, q, "2", out, "1", AC_CONDUCTORS)
        extra = []
        if g_gp is not None:               # síťová ochrana: měří z rozvodu (vlastní skupina svorek za vývodem)
            extra += _grid_protection(project, sheet, x_out + GROUP_PITCH, y - 60, g_gp, "2")
        # skupiny rozvodných svorek zabírají na liště počet svorek × šířka svorky (`Element.modules`)
        _place_sequential(sheet, [q, *extra, spd, *breakers, *groups, g_spd, g_out, *([g_gp] if g_gp else [])])
    if ac.get("enclosure"):
        sheet.layout.params["type"] = _s(ac["enclosure"])


def main_role(ctx: ChainContext) -> str:
    """Role hlavního AC článku: `rfve` (rodinný dům, rozvaděč FVE), jinak `rfve_ac`."""
    return "rfve" if ctx.topology is not None and ctx.topology.node("rfve") is not None else "rfve_ac"


def ac_mode(ctx: ChainContext) -> tuple[str, dict]:
    """Jak vznikne AC část hlavního AC článku (docs/NAVRH_TOPOLOGIE.md, kap. 8 bod 12): „builtin“ (volba
    `chain.<role>.builtin` / standard `ac_builtin` – makra `spec.macros` včetně vestavěných, jinak vestavěný kód, jako
    před F2), „macro“ (mustr: makra rolí `ac_feed` + `ac_core` ze sdílené / vlastní knihovny, `ac_eps` volitelně),
    „none“ (mustr chybí: RFVE.AC jen blok bez listu, RFVE rodinného domu list jen s DC částí a kotvami přívodů /
    vývodů). Vrací (režim, makra pro `_ac_box_from_macros`)."""
    if "ac_mode" in ctx.cache:
        return ctx.cache["ac_mode"]
    from envocad.generator.spec import builtin_wanted, pattern_macro
    role = main_role(ctx)
    out: tuple[str, dict] = ("none", {})
    if builtin_wanted(ctx.spec, ctx.topology, role):
        out = ("builtin", dict(ctx.spec.get("macros") or {}))
    elif (ctx.spec["ac"].get("distribution") or "bus") == "bus":
        feed = pattern_macro(ctx.spec, ctx.raw, ctx.topology, role, "ac_feed")
        core = pattern_macro(ctx.spec, ctx.raw, ctx.topology, role, "ac_core")
        if feed and core:
            eps = pattern_macro(ctx.spec, ctx.raw, ctx.topology, role, "ac_eps")
            out = ("macro", {"ac_feed": feed, "ac_core": core, "ac_eps": eps or ""})
    ctx.cache["ac_mode"] = out
    return out


def build_main_sheet(ctx: ChainContext) -> Sheet | None:
    """List hlavního AC článku (`ctx.main` – RFVE.AC, u rodinného domu AC část RFVE) podle `ac_mode`: z mustru
    (`ac_feed` + `ac_core`), vestavěně (makra / `_build_ac_switchboard`), nebo bez AC části – RFVE.AC jen jako blok
    bez listu (porty a údaje v atributech, `main_block_attrs`), RFVE rodinného domu s DC částí list s kotvami přívodů
    a vývodů (`anchor_ac_part`). Listy DC rozvaděčů vzniknou před ním. Skupiny střídačů na jiném místě
    (`ctx.groups`, krok 10): RFVE.AC{n} na skupinu, každý se svými střídači. Vrací list hlavního (prvního) AC
    rozvaděče, nebo None (blok bez listu)."""
    from envocad.generator.boards.rfve_dc import build_dc_sheets
    build_dc_sheets(ctx)
    if not ctx.groups:
        sb = _build_main(ctx, ctx.spec.get("inverters") or [])
    else:
        sb = None
        invs = ctx.spec.get("inverters") or []
        keep = ctx.blocks["main"], ctx.inverters, ctx.ac_wires
        try:
            for n, g in enumerate(ctx.groups):
                ctx.blocks["main"] = g["block"]
                ctx.inverters = [keep[1][i] for i in g["idx"]]
                ctx.ac_wires = [keep[2][i] for i in g["idx"]]
                one = _build_main(ctx, [invs[i] for i in g["idx"]])
                if n == 0:
                    sb = one
        finally:
            ctx.blocks["main"], ctx.inverters, ctx.ac_wires = keep
    ctx.done.add("main")
    return sb


def _build_main(ctx: ChainContext, invs: list[dict]) -> Sheet | None:
    """List jednoho AC rozvaděče FVE (`ctx.main`) pro střídače `invs` (slovníky specifikace; `ctx.inverters` /
    `ctx.ac_wires` odpovídají); bez mustru (`ac_mode` „none“) blok bez listu (None) nebo list s kotvami (RFVE)."""
    from envocad.generator.boards.eps import build_sheet_part
    from envocad.generator.boards.macro_glue import _ac_box_from_macros
    from envocad.generator.currents import main_switch_in
    from envocad.generator.spec import grid_protection_limit, grid_protection_wanted
    p, spec = ctx.project, ctx.spec
    # síťová ochrana nad hranicí kWp (u rodinného domu v RFVE) – podmíněné prvky `when: grid_protection`
    limit = grid_protection_limit()
    gp = grid_protection_wanted(spec, ctx.topology, main_role(ctx), ctx.kwp, limit)
    p.meta["grid_protection_kwp"] = f"{limit:g}"
    ac = {**spec["ac"], "grid_protection": "1" if gp else ""}
    if ctx.groups and _s(ac.get("main_in_auto")):        # hlavní vypínač podle střídačů skupiny
        ac["main_in"] = main_switch_in(spec, ctx.inverters)
    mode, macros = ac_mode(ctx)
    if mode == "none" and not ctx.combined:
        main_block_attrs(ctx, ac)
        return None
    sb = p.create_switchboard_sheet(ctx.main)
    sb.layout.params.setdefault("network", "3NPE, 50 Hz")
    sb.layout.params.setdefault("un", "230/400 V")
    sb.layout.params.setdefault("in_", _s(ac.get("main_in") or 125))
    if mode == "none":                 # RFVE rodinného domu bez mustru: jen kotvy AC části (DC část dostaví builder)
        anchor_ac_part(ctx, sb, invs)
        main_block_attrs(ctx, ac, ports=False)
        return sb
    if not _ac_box_from_macros(p, sb, invs, ac, macros):
        _build_ac_switchboard(p, sb, invs, ac, spec)
    single_phase_feeds(ctx, sb)
    # EPS a přepínač sítí (jen rodinný dům s hybridním střídačem a baterií): mustr / vestavěně, jinak kotvy
    build_sheet_part(ctx, sb, macros.get("ac_eps", ""), builtin=mode == "builtin")
    mark_chain_devices(ctx, sb)
    return sb


def anchor_ac_part(ctx: ChainContext, sb: Sheet, invs: list[dict]) -> None:
    """AC část listu RFVE bez mustru: jen přívody od střídačů X1…Xn, vývod XOUT (do RD), XPE (k HOP – na něj vedou
    PE svodičů DC části) a EPS (XE{i}, XB{i}, `eps.anchor_eps`) jako kotvy (`anchor="1"`) bez přístrojů – blok má
    porty, vazby přívodů fungují a mustr / projektant AC část doplní. Rozložení jako vestavěná AC část (spodní
    řada)."""
    from envocad.generator.boards.eps import anchor_eps
    p = ctx.project
    x = AC_FEED_X0
    for i, inv in enumerate(invs):
        f = _feed(p, sb, "in", AC_FEED_X0 + i * GROUP_PITCH, AC_ROW_BOTTOM, "",
                  desc=f"od {inv.get('ref') or f'T{i + 1}'}")
        f.attrs.update({"ref": f"X{i + 1}", "anchor": "1"})
        x = f.x
    xpe = _feed(p, sb, "out", 60.0, AC_ROW_BOTTOM, "", desc="k HOP")
    xpe.attrs.update({"ref": "XPE", "anchor": "1"})
    out = _feed(p, sb, "out", x + AC_CORE_GAP, AC_ROW_BOTTOM, "", desc="do RD")
    out.attrs.update({"ref": "XOUT", "anchor": "1"})
    anchor_eps(ctx, sb, out.x)


def inverter_protection(ctx: ChainContext) -> list[str]:
    """In jištění přívodu každého střídače `ctx.inverters` (automaticky podle proudu, jinak `ac.breaker_in`); nad
    řadou ""."""
    from envocad.generator.currents import inverter_breaker
    ac = ctx.spec["ac"]
    auto = bool(_s(ac.get("breaker_in_auto")))
    out = []
    for t in ctx.inverters:
        v, why = inverter_breaker(t) if auto else ("", "")
        out.append(v if v or why else _s(ac.get("breaker_in") or 40))
    return out


def main_block_attrs(ctx: ChainContext, ac: dict, ports: bool = True) -> None:
    """Údaje hlavního AC článku bez AC listu do atributů bloku (blokové schéma je ukáže): hlavní vypínač, jištění
    střídačů, požadavek síťové ochrany; s `ports` i porty bloku bez listu (přívody X1…Xn a EPS XE{i}, vývody XOUT,
    XPE, XB{i}) a jištění přívodů `protect` (kontrola kabelů od střídačů, `calc.check_cables`)."""
    from envocad.generator.boards.eps import eps_inverters
    blk = ctx.main
    ins = inverter_protection(ctx)
    blk.attrs["main"] = f"hlavní vypínač {_s(ac.get('main_in') or 125)} A"
    known = [v for v in ins if v]
    if known and len(set(known)) == 1 and len(known) == len(ins):
        blk.attrs["inv_protect"] = f"{len(ins)}× {known[0]} A" if len(ins) > 1 else f"{known[0]} A"
    elif known:
        blk.attrs["inv_protect"] = ", ".join(f"X{k + 1} {v or '?'} A" for k, v in enumerate(ins))
    if ac.get("grid_protection"):
        blk.attrs["grid_protection"] = "požadována"
    if not ports:
        return
    eps = eps_inverters(ctx)
    blk.attrs["ports_in"] = " ".join([*(f"X{k + 1}" for k in range(len(ctx.inverters))),
                                      *(f"XE{i}" for i, _t in eps)])
    used = {end.port for w in ctx.sheet.wires for end in (w.a, w.b) if end.element_id == blk.id}
    blk.attrs["ports_out"] = " ".join(["XOUT", *(["XPE"] if "XPE" in used else []), *(f"XB{i}" for i, _t in eps)])
    prot = [f"X{k + 1}={v}" for k, v in enumerate(ins) if v]
    if prot:
        blk.attrs["protect"] = ", ".join(prot)


def inverter_breaker_in(t: Element) -> str:
    """In automatického jističe přívodu střídače (`currents.inverter_breaker`); neznámý proud / nad řadou → ""."""
    from envocad.generator.currents import inverter_breaker
    return inverter_breaker(t)[0]


CHAIN_DEVICE_SYMBOLS = ("fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo", "fve.fuse", "fve.fuse_disconnect",
                        "sb.main_switch")


def first_device(sheet: Sheet, start: Element, symbols=CHAIN_DEVICE_SYMBOLS, depth: int = 4) -> Element | None:
    """První přístroj (`symbols`) od prvku `start` (přívod / vývod listu) po vodičích listu – přes svorky a uzly."""
    by_id = {e.id: e for e in sheet.elements}
    seen, frontier = {start.id}, [start]
    for _ in range(depth):
        nxt = []
        for cur in frontier:
            for w in sheet.wires:
                if not w.touches(cur.id):
                    continue
                o = by_id.get(w.b.element_id if w.a.element_id == cur.id else w.a.element_id)
                if o is None or o.id in seen:
                    continue
                if o.symbol_id in symbols:
                    return o
                if o.symbol_id.startswith(("sb.busbar", "fve.busbar")):
                    continue                 # za rozvodem už jiná větev
                seen.add(o.id)
                nxt.append(o)
        frontier = nxt
    return None


def mark_chain_devices(ctx: ChainContext, sb: Sheet) -> None:
    """Role přístrojů v řetězci (atribut `chain`, kontrola selektivity přes listy `calc.check_selectivity_tree`):
    jištění přívodu střídače `inv`, hlavní vypínač rozvaděče FVE `rfve_main` (z maker i kódem)."""
    from envocad.generator.currents import inverter_breaker
    feeds = {e.ref: e for e in sb.elements if is_feed(e)}
    auto = bool(_s(ctx.spec["ac"].get("breaker_in_auto")))
    for w, t in zip(ctx.ac_wires, ctx.inverters):
        port = w.b.port if w.b.element_id == ctx.main.id else w.a.port
        f = feeds.get(port)
        d = first_device(sb, f) if f is not None else None
        if d is not None and d.symbol_id != "sb.main_switch":
            d.attrs["chain"] = "inv"
            if auto and _s(d.attrs.get("poles")) != "2":     # jednofázový už podle proudu (`single_phase_feeds`)
                set_breaker_in(d, *inverter_breaker(t))
    out = feeds.get("XOUT")
    q = first_device(sb, out) if out is not None else None
    if q is not None:
        q.attrs["chain"] = "rfve_main"
    for e in sb.elements:             # síťová ochrana působí na vazební (hlavní) vypínač s vypínací spouští
        if e.symbol_id == GRID_PROTECTION_SYMBOL and not _s(e.attrs.get("acts_on")).strip() and q is not None:
            e.attrs["acts_on"] = q.ref
            q.attrs.setdefault("trip", "vypínací spoušť")


def set_breaker_in(d: Element, in_: str, why: str) -> None:
    """In automatického jističe přívodu střídače: hodnota, nad řadou prázdné + `in_unresolved` (chyba F7), neznámý
    proud (bez P AC i artiklu) → zadaná / výchozí hodnota zůstane."""
    if in_:
        d.attrs["in_"] = in_
        d.attrs.pop("in_unresolved", None)
    elif why:
        d.attrs["in_"] = ""
        d.attrs["in_unresolved"] = why


def single_phase_feeds(ctx: ChainContext, sb: Sheet) -> None:
    """Přívodní větev jednofázového střídače (AC kabel L N PE, `pv.ac_cable_of`): vodiče přívod → jistič → rozvod
    se žilami L1 N PE a jistič 1+N (2 póly, In vždy podle proudu střídače `currents.inverter_breaker` – i když je
    `ac.breaker_in` zadané, to platí pro třífázové) – vícepól pak kreslí fázi a N přes jistič, PE kolem (z makra
    i kódem)."""
    from envocad.generator.currents import inverter_breaker
    from envocad.generator.pv import AC1_CONDUCTORS
    by_id = {e.id: e for e in sb.elements}
    inv_of = {w.id: t for w, t in zip(ctx.ac_wires, ctx.inverters)}
    for w_jps in ctx.ac_wires:
        if list(w_jps.conductors) != AC1_CONDUCTORS:
            continue
        port = w_jps.b.port if w_jps.b.element_id == ctx.main.id else w_jps.a.port
        feed = next((e for e in sb.elements if e.ref == port and is_feed(e)), None)
        if feed is None:
            continue
        cur, seen = feed, {feed.id}
        for _ in range(3):                # přívod → jistič → rozvod (sběrnice / svorky)
            nxt = [w for w in sb.wires if w.touches(cur.id)
                   and (w.b.element_id if w.a.element_id == cur.id else w.a.element_id) not in seen]
            if len(nxt) != 1:
                break
            w = nxt[0]
            w.conductors = list(AC1_CONDUCTORS)
            cur = by_id[w.b.element_id if w.a.element_id == cur.id else w.a.element_id]
            seen.add(cur.id)
            if cur.symbol_id in ("fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo"):
                cur.attrs["poles"] = "2"
                cur.attrs["modules"] = "2"
                set_breaker_in(cur, *inverter_breaker(inv_of[w_jps.id]))
            else:
                break


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
