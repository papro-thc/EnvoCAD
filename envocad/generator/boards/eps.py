"""EPS a přepínač sítí jen u rodinného domu (rozvaděč FVE RFVE) – bez Qt. Návrh docs/design/topologie_f1_f2.md,
kap. 2 bod 9; rozhodnutí 8 a 10 (docs/NAVRH_TOPOLOGIE.md, kap. 8).

Hybridní střídač s baterií má EPS (záložní) vývod – svorku BACKUP (`model.inverter_io`; když ji typ střídače
neuvádí, generátor ji doplní do atributu `io`, protože EPS vývod vede vždy na přepínač). V JPS vede vodič
T{i}.BACKUP → RFVE.XE{i} přes pár přerušovacích bodů „EPS-T{i}“ (kabel u rozvaděče, úsek u střídače je pokračování –
žádné křížení s AC vodiči nad vším ani s vývodem XOUT pod vším). V listu RFVE: přívod XE{i} → přepínač sítí I-0-II
(`fve.changeover_switch`, port 2 záloha), síťová strana z prvního volného vývodu sběrnice za hlavním vypínačem
(4, se síťovou ochranou 5; port 1), výstup (port 3) → vývod XB{i}
→ v JPS značka spotřeby „zálohované okruhy“ (`fve.load`). Firma a bytový dům EPS nekreslí. Role makra `ac_eps`
(mustr Patrika): `spec.macros.ac_eps` – makro s kotvami `XE{i}`, `XB{i}` a sdílenou sběrnicí 1 (vývod 5).
"""
from __future__ import annotations

from itertools import pairwise

from envocad.generator.context import _s
from envocad.library.templates import AC_CONDUCTORS, _el, _feed, _wire
from envocad.model.project import INTERRUPT_SYMBOL, Element, Sheet, Wire, WireEnd

CHANGEOVER_SYMBOL = "fve.changeover_switch"
EPS_LOAD_DESC = "zálohované okruhy"
EPS_FEED_DX = 15.0            # přívod XE{i} vpravo od přepínače (vodič zdola nahoru a shora do portu 2)
EPS_INT_DX = 5.0              # přerušení EPS kousek od svorky (BACKUP vpravo, XE{i} vlevo)
EPS_DROP = 40.0               # přerušení u RFVE pod přívodem XE{i} (svislý úsek nese popisek kabelu)
EPS_LEFT_GAP = 50.0           # RFVE za střídači: přerušení vlevo od přívodu XE{i} (místo pro popisek kabelu)
EPS_LEFT_MIN = 25.0           # … nejméně (popisek kabelu se pak může posunout)
EPS_LANE_GAP = 30.0           # AC vodiče dalších střídačů rodinného domu stoupají dál od značky (místo pro přerušení)
EPS_TOP_Y = 140.0             # vodič od XE{i} nad přepínačem (port 2 v y 132,5, jistič nad ním 142,5–157,5)


def free_out(sb: Sheet, bus: Element) -> str:
    """První volný vývod sběrnice vpravo za hlavním vypínačem (3): 4, se síťovou ochranou 5…"""
    used = {end.port for w in sb.wires for end in (w.a, w.b) if end.element_id == bus.id}
    k = 4
    while str(k) in used:
        k += 1
    return str(k)


def eps_inverters(ctx) -> list[tuple[int, Element]]:
    """(pořadí od 1, střídač) hybridních střídačů u rodinného domu (topologie s článkem `rfve`), ke kterým je
    v blokovém schématu připojená baterie (EPS jen u střídače s baterií – D7)."""
    if not ctx.spec.get("battery") or ctx.topology is None or ctx.topology.node("rfve") is None:
        return []
    by_id = {e.id: e for e in ctx.sheet.elements}

    def has_battery(t: Element) -> bool:
        for w in ctx.sheet.wires:
            if w.touches(t.id):
                o = by_id.get(w.b.element_id if w.a.element_id == t.id else w.a.element_id)
                if o is not None and o.symbol_id == "fve.battery":
                    return True
        return False
    return [(i + 1, t) for i, t in enumerate(ctx.inverters) if t.symbol_id == "fve.inverter_hybrid" and has_battery(t)]


def prepare_inverter(t: Element) -> None:
    """Hybridní střídač s EPS: svorka BACKUP (doplní se do `io`, když ji typ neuvádí) a `eps="1"` (kontrola F7
    `eps_unconnected` – EPS vývod musí vést na přepínač sítí)."""
    from envocad.model.inverter_io import inverter_io
    io = inverter_io(t.attrs)
    if "BACKUP" not in io:
        t.attrs["io"] = " ".join([*io, "BACKUP"])
    t.attrs["eps"] = "1"


def eps_in(t: Element) -> str:
    """In jističe před přepínačem i přepínače: jako jistič přívodu střídače (`currents.inverter_breaker` – artikl,
    jinak 1,25 × P AC; 1f podle 230 V); neznámý proud → 40 A."""
    from envocad.generator.currents import inverter_breaker
    return inverter_breaker(t)[0] or "40"


EPS_Q_Y = 125.0               # přepínač sítí (porty 1, 2 nahoře v y 132,5, výstup 3 dole)
EPS_BREAKER_Y = 150.0          # jistič před přepínačem (síťová strana, port 1) nad přepínačem


def build_sheet_part(ctx, sb: Sheet, entry="", builtin: bool = True) -> list[Element]:
    """EPS v listu RFVE (po AC části, před DC částí): na každý hybridní střídač s baterií přívod XE{i} → přepínač
    sítí → vývod XB{i}; síťová strana z prvního volného vývodu sběrnice za hlavním vypínačem přes jistič (D4).
    Makro role `ac_eps` (`entry` – mustr, s `builtin` i vestavěné makro `spec.macros.ac_eps`), s `builtin` jinak
    vestavěný kód, bez obojího jen kotvy XE{i} / XB{i} (`anchor_eps`). Vrací přepínače."""
    from envocad.generator.boards.macro_glue import _insert_macro, _macro_ref, _macro_values
    from envocad.generator.boards.rfve_ac import _ac_core_after_feeds
    from envocad.library.macros import find_macro
    p = ctx.project
    bus = next((e for e in sb.elements if e.symbol_id == "sb.busbar"), None)
    out: list[Element] = []
    ref = _macro_ref(entry)
    m = find_macro(ref[0]) if ref[0] else None
    invs = eps_inverters(ctx)
    if m is None and not builtin:
        anchor_eps(ctx, sb, max((e.x for e in sb.elements), default=0.0))
        return out
    x_max = max((e.x for e in sb.elements), default=0.0)
    for j, (i, t) in enumerate(invs):
        x = x_max + 30.0 * (j + 1)
        if m is not None:
            from envocad.generator import context
            lib = context._lib()
            base = {"eps_in": eps_in(t), "main_in": _s(ctx.spec["ac"].get("main_in") or 125)}
            vals = _macro_values(m, ref, base, {"i": i, "inverter": t.ref}, lib.component)
            els = _insert_macro(p, sb, m, vals, x, lib)
            out += [e for e in els if e.symbol_id == CHANGEOVER_SYMBOL]
            continue
        q = _el(p, sb, CHANGEOVER_SYMBOL, x, EPS_Q_Y, "Q", in_=eps_in(t), poles="4", modules="4", kind="ruční")
        q.attrs["desc"] = "přepínač sítí (EPS)"
        fq = _el(p, sb, "fve.breaker_mcb", x, EPS_BREAKER_Y, "F", rot=270, in_=eps_in(t), char="B",
                 poles="4", modules="4")
        fq.attrs["desc"] = "jištění přepínače sítí (síťová strana)"
        fe = _feed(p, sb, "in", x + EPS_FEED_DX, 105.0, "", desc=f"EPS od {t.ref}")
        fe.attrs["ref"] = f"XE{i}"
        fb = _feed(p, sb, "out", x, 105.0, "", desc=EPS_LOAD_DESC)
        fb.attrs["ref"] = f"XB{i}"
        if bus is not None:
            _wire(p, sb, bus, free_out(sb, bus), fq, "1", AC_CONDUCTORS)
        _wire(p, sb, fq, "2", q, "1", AC_CONDUCTORS)
        # záloha shora do portu 2 (vpravo od sítě): od přívodu XE dole nahoru nad přepínač a vlevo dolů
        _wire(p, sb, fe, "1", q, "2", AC_CONDUCTORS).points = [(x + EPS_FEED_DX, EPS_TOP_Y), (x + 5.0, EPS_TOP_Y)]
        _wire(p, sb, q, "3", fb, "1", AC_CONDUCTORS)
        out.append(q)
    if out:
        _ac_core_after_feeds(p, sb)          # přepínač rovně pod svůj vývod sběrnice (za ochranou / vypínačem)
    return out


def anchor_eps(ctx, sb: Sheet, x0: float) -> None:
    """EPS bez mustru: přívod XE{i} a vývod XB{i} jako kotvy (`anchor="1"`) vpravo od `x0` – blok RFVE má porty
    pro vodiče EPS v blokovém schématu, přepínač sítí doplní mustr / projektant (F7 jen INFO `eps_open`)."""
    p = ctx.project
    x = x0
    for i, t in eps_inverters(ctx):
        x += 30.0
        fe = _feed(p, sb, "in", x, 105.0, "", desc=f"EPS od {t.ref}")
        fe.attrs.update({"ref": f"XE{i}", "anchor": "1"})
        x += 30.0
        fb = _feed(p, sb, "out", x, 105.0, "", desc=EPS_LOAD_DESC)
        fb.attrs.update({"ref": f"XB{i}", "anchor": "1"})


def build_jps(ctx) -> None:
    """Vodiče EPS v blokovém schématu: T{i}.BACKUP → přerušení „EPS-T{i}“ … „EPS-T{i}“ → RFVE.XE{i} (kabel jako AC
    kabel střídače u rozvaděče, úsek u střídače bez údajů) a RFVE.XB{i} → spotřeba „zálohované okruhy“. Polohy
    doplní `place_jps` po trase rodinného domu (`ctx.eps`)."""
    from envocad.generator.pv import ac_cable_of
    p, s, blk = ctx.project, ctx.sheet, ctx.main
    ac = ctx.spec["ac"]
    for i, t in eps_inverters(ctx):
        conductors, cable, cross = ac_cable_of(t, ac)
        cab = {"ref": p.next_ref("W"), "cable": cable, "cross": cross, "length": _s(ac.get("length")), "method": "B1"}
        load = Element("fve.load", blk.x, blk.y, attrs={"ref": "", "desc": EPS_LOAD_DESC})
        s.elements.append(load)
        w_l = Wire(WireEnd(blk.id, f"XB{i}"), WireEnd(load.id, "1"), conductors=list(conductors), attrs={"ref": ""})
        ep = {"inverter": t, "i": i, "load": load, "w_l": w_l}
        ref = f"EPS-{t.ref}"
        i_t = Element(INTERRUPT_SYMBOL, t.x, t.y, attrs={"ref": ref})
        i_b = Element(INTERRUPT_SYMBOL, blk.x, blk.y, rotation=0, attrs={"ref": ref})
        s.elements += [i_t, i_b]
        w_t = Wire(WireEnd(t.id, "BACKUP"), WireEnd(i_t.id, "1"), conductors=list(conductors), attrs={"ref": ""})
        w_b = Wire(WireEnd(i_b.id, "1"), WireEnd(blk.id, f"XE{i}"), conductors=list(conductors), attrs=cab)
        s.wires += [w_t, w_b, w_l]
        ctx.eps.append({**ep, "int_t": i_t, "int_b": i_b, "w_t": w_t, "w_b": w_b})
        for row in ctx.rows:                 # přerušení u střídače patří do jeho řady (dělení JPS na listy)
            if t in row:
                row.append(i_t)


def place_jps(ctx, x_out: float | None) -> None:
    """Polohy EPS v JPS (po `_route_house`; RFVE za střídači před volbou rozložení řetězce): přerušení u svorky
    BACKUP a u přívodu XE{i} rozvaděče FVE (`_place_interrupts`); spotřeba „zálohované okruhy“ vpravo od vývodu XB{i} za svislým úsekem
    vodiče od XOUT (`x_out`) – vodič XB{i} vede vpravo a dolů do značky nad vodorovným úsekem k síti."""
    from envocad.generator import context
    from envocad.model.project import element_symbol
    from envocad.model.symbol import rotate_dir
    lib = context._lib()
    p, blk = ctx.project, ctx.main

    def port(e: Element, name: str) -> tuple[float, float]:
        return e.port_pos(element_symbol(p, e, lib), name)

    dx_port = lib.get_symbol(INTERRUPT_SYMBOL).port("1").x
    for k, ep in enumerate(ctx.eps):
        t = ep["inverter"]
        bx, by = port(t, "BACKUP")
        d = rotate_dir(element_symbol(p, t, lib).port("BACKUP").dir, t.rotation)
        sgn = -1 if d == "W" else 1
        _place_interrupts(ctx, ep, (bx, by), sgn, port(blk, f"XE{ep['i']}"), port, dx_port)
        xb, yb = port(blk, f"XB{ep['i']}")
        load = ep["load"]
        x_v = (x_out if x_out is not None else xb + 15.0) + 10.0 + 5.0 * k
        lp = port(load, "1")
        # pod vším v pásu značky (baterie pod hybridním střídačem, popisky) – vodič XB svisle dolů a vpravo do ní
        y_l = min(yb - 15.0, _band_bottom(ctx, (x_v - 2.5, x_v + 45.0), {load.id}, {ep["w_l"].id}) - 10.0)
        y_l = round(y_l / 2.5) * 2.5
        load.x += x_v + 10.0 - lp[0]
        load.y += y_l - lp[1]
        ep["w_l"].points = [(x_v, yb), (x_v, y_l)]


def _place_interrupts(ctx, ep: dict, b: tuple[float, float], sgn: int, e: tuple[float, float], port,
                      dx_port: float) -> None:
    """Pár přerušení EPS: u svorky BACKUP kousek vpravo (AC vodiče dalších střídačů stoupají až za ním –
    `EPS_LANE_GAP`); u rozvaděče FVE z přívodu XE{i} (vlevo dole) kousek vlevo a šipkou dolů pod blok – vodorovně
    vlevo by křížil svislé úseky DC vodičů od rozvaděčů po trase; RFVE za střídači (bez DC části) vlevo od přívodu
    (pod blokem je řetězec RD)."""
    (bx, by), (ex, ey) = b, e
    it = ep["int_t"]
    it.rotation = 0 if sgn > 0 else 180
    it.x, it.y = bx + sgn * (EPS_INT_DX - dx_port), by
    ep["w_t"].points = []
    ib = ep["int_b"]
    if not ctx.combined:              # RFVE za střídači (bez DC části): vlevo od přívodu, pod ním je řetězec RD
        # před svislými úseky AC vodičů dalších střídačů (lomy mezi střídači a RFVE), jinak dál – popisky
        from envocad.generator import context
        from envocad.model.textlayout import wire_route
        lib = context._lib()
        bends = []                    # svislé úseky přes výšku přívodu XE{i} (vodič vlevo by je křížil)
        for w in ctx.ac_wires:
            pts = wire_route(ctx.project, ctx.sheet, lib, w) if w in ctx.sheet.wires else []
            for (x1, y1), (x2, y2) in pairwise(pts):
                if abs(x1 - x2) < 1e-6 and min(y1, y2) - 2.5 <= ey <= max(y1, y2) + 2.5 \
                        and ex - EPS_LEFT_GAP - 12.5 < x1 < ex:
                    bends.append(x1)
        gap = max(EPS_LEFT_MIN, min(EPS_LEFT_GAP, ex - max(bends) - 12.5)) if bends else EPS_LEFT_GAP
        ib.rotation, ib.x, ib.y = 180, ex - (gap - dx_port), ey
        ep["w_b"].points = []
        return
    ib.rotation, ib.x, ib.y = 270, 0.0, 0.0
    ix, iy = port(ib, "1")
    ib.x, ib.y = ex - EPS_INT_DX - ix, ey - EPS_DROP - iy
    ep["w_b"].points = [(ex - EPS_INT_DX, ey)]


def _band_bottom(ctx, band: tuple[float, float], skip_el: set[str], skip_w: set[str]) -> float:
    """Spodní okraj obsahu JPS ve svislém pásu `band` (bez prvků / vodičů `skip_*`)."""
    from envocad.generator import context
    from envocad.model.textlayout import sheet_content_boxes
    s = ctx.sheet
    keep_el, keep_w = s.elements, s.wires
    s.elements = [e for e in keep_el if e.id not in skip_el]
    s.wires = [w for w in keep_w if w.id not in skip_w]
    try:
        boxes = sheet_content_boxes(ctx.project, s, context._lib())
    finally:
        s.elements, s.wires = keep_el, keep_w
    return min((b[1] for b in boxes if b[2] >= band[0] and b[0] <= band[1]), default=0.0)
