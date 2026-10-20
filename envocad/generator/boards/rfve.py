"""Rozvaděč FVE rodinného domu (RFVE): DC část za AC částí, tvar „U“ (bez Qt). Přesun 1:1 z `generate.py`
(refaktoring F1, krok 4)."""
from __future__ import annotations

import re

from envocad.generator import context
from envocad.generator.boards.base import ChainContext
from envocad.generator.boards.macro_glue import FUSE_SYMBOLS, _dc_box_from_macro
from envocad.generator.boards.rfve_ac import AC_ROW_BOTTOM, AC_ROW_DEVICES
from envocad.generator.context import (
    _s,
)
from envocad.library.templates import (
    _place_sequential,
    build_dc_strings,
)
from envocad.model.busbar import line_end, line_span
from envocad.model.feed import is_feed_in, is_feed_out
from envocad.model.project import Element, Project, Sheet, Wire, element_symbol


def _add_dc_part(p: Project, sheet: Sheet, groups: list[tuple[int, str, list[str], str]], entry, dc: dict,
                 first: int) -> None:
    """DC část rozvaděče FVE rodinného domu (za AC částí): na každý string pojistkový odpínač + SPD (makro
    `dc_tech`, jinak `build_dc_strings`); přívody X{first}…, vývody X{first + n}… přes všechny střídače.
    `groups` = [(č. střídače, střídač, stringy, In pojistek)]. Přístroje se pak rozmístí: DC část, za ní AC."""
    ac_ids = [pl.element_id for pl in sheet.layout.placements]
    dx0 = max((e.x for e in sheet.elements), default=0.0) + 60.0
    n = sum(len(g[2]) for g in groups)
    k0 = first - 1
    done = False
    for inv_no, inv_ref, strings, fuse_in in groups:
        box = {**dc, "fuse_in": fuse_in}
        done = _dc_box_from_macro(p, sheet, strings, entry, box, inv_no, inv_ref, k0=k0, n=n, dx0=dx0)
        if not done:
            break
        k0 += len(strings)
    if not done:   # makro chybí (pak pro žádný střídač): kódem, všechny stringy najednou, číslování jako u makra;
        # In pojistek po skupinách – každý string podle svého střídače (moduly / SolarEdge se mohou lišit)
        # SPD stringů na vývod XPE AC části (k HOP) jako makro; při rozvodu svorkami (bez XPE) vlastní PE lišta
        pe = next((e for e in sheet.elements if is_feed_out(e) and e.ref == "XPE"), None)
        build_dc_strings(p, sheet, [g for grp in groups for g in grp[2]], "tech",
                         [_s(grp[3]) for grp in groups for _g in grp[2]],
                         spd=_s(dc.get("spd") or "T2"), first=first, dx=dx0, pe=pe)
    new = [pl.element_id for pl in sheet.layout.placements if pl.element_id not in ac_ids]
    by_id = {e.id: e for e in sheet.elements}
    _place_sequential(sheet, [by_id[i] for i in [*new, *ac_ids] if i in by_id])


DC_U_PITCH = 70.0     # rozteč stringů DC části RFVE ve tvaru „U“ (dvě svorky ve spodní řadě s popisky vpravo)
DC_U_WIDTH = 35.0     # levá noha (přívod X, pojistkový odpínač) → pravá noha (vývod X)
DC_U_TOP = 155.0      # vodorovný úsek „U“ (nad odpínačem)
DC_SPD_Y = 170.0      # SPD nad ohybem (otočený: L dole z ohybu, PE nahoru)
DC_PE_Y = 192.5       # PE svodičů nad SPD a nad sběrnicí → XPE vlevo (nebo PE lišta DC části vpravo)
DC_U_X0 = 60.0        # levá noha prvního stringu, když na listu nic jiného není
DC_AC_GAP = 42.5      # od posledního prvku AC části (XOUT s popiskem) k levé noze prvního stringu
DC_U_GAP = 35.0       # od SPD posledního stringu (popisek) k PE liště DC části
DC_PE_AROUND = 7.5    # PE svodičů DC kolem levého konce sběrnice, když XPE stojí pod ní (parametrická sběrnice)
DC_PE_JOIN_DY = 5.0   # odbočka PE svodičů DC (zleva) nad odbočkou PE svodiče AC (zprava) na vodiči k XPE
DC_SPD_DX = 12.5      # SPD vpravo od pravé nohy (popisek vpravo nad ohybem dalšího stringu)


def _dc_from_below(project: Project, sheet: Sheet) -> None:
    """DC část rozvaděče FVE rodinného domu (rozhodnutí 3: vše zespodu) vpravo od AC části: každý string jako „U“ –
    levá noha nahoru (přívod X{k} ve spodní řadě → pojistkový odpínač otočený tokem nahoru), ohyb nahoře, pravá noha
    dolů na vývod X{nk} ve spodní řadě; SPD visí vpravo nad ohybem (za odpínačem, za koncem sběrnice), jeho PE vede nad
    sběrnicí doleva k XPE AC části (s rozvodem svorkami k PE liště DC části vpravo). Nic se nekříží: PE je nad ohyby,
    SPD i sběrnicí a XPE stojí vlevo před sběrnicí. Stringy se rozpoznají podle zapojení (přívod → pojistka → vývod +
    SPD), ať vznikly z makra nebo kódem."""
    by_id = {e.id: e for e in sheet.elements}
    at: dict[tuple[str, str], list[tuple[Wire, Element, str]]] = {}
    for w in sheet.wires:
        for end, other in ((w.a, w.b), (w.b, w.a)):
            if other.element_id in by_id:
                at.setdefault((end.element_id, end.port), []).append((w, by_id[other.element_id], other.port))
    strings = []
    for f in sheet.elements:
        if not is_feed_in(f):
            continue
        fus = [o for _w, o, op in at.get((f.id, "1"), []) if o.symbol_id in FUSE_SYMBOLS and op == "1"]
        if len(fus) != 1:
            continue
        nxt = at.get((fus[0].id, "2"), [])
        out = next(((w, o) for w, o, _p in nxt if is_feed_out(o)), None)
        spd = next(((w, o) for w, o, op in nxt if o.symbol_id == "fve.spd" and op == "L"), None)
        if out is not None:
            strings.append((f, fus[0], out, spd))
    if not strings:
        return
    strings.sort(key=lambda st: (st[0].x, -st[0].y))
    dc_ids = {e.id for f, fu, (_w, o), spd in strings for e in (f, fu, o, *((spd[1],) if spd else ()))}
    pe_wires: list[tuple[Wire, Element, float]] = []     # (vodič PE svodiče, cíl, x svodiče)
    # DC část vpravo od AC části (vícepól řadí podle polohy: AC, pak DC – jako dřív); SPD a PE nad ohybem až za koncem
    # sběrnice, ohyb „U“ smí být pod ní
    ac = [e for e in sheet.elements if e.id not in dc_ids and e.symbol_id not in ("sb.pe_bar", "sb.busbar")]
    bus = next((e for e in sheet.elements if e.symbol_id == "sb.busbar"), None)
    x0 = max(e.x for e in ac) + DC_AC_GAP if ac else DC_U_X0
    if bus is not None:
        x0 = max(x0, bus.x + line_end(element_symbol(project, bus, context._lib())) + 7.5 - DC_U_WIDTH - DC_SPD_DX)
    x0 = round(x0 / 2.5 + 0.49) * 2.5
    for j, (f, fu, (w_out, out), spd) in enumerate(strings):
        left = x0 + j * DC_U_PITCH
        right = left + DC_U_WIDTH
        mid = right + DC_SPD_DX        # SPD vpravo za pravou nohou (vícepól: vývod, pak SPD – jako dřív)
        f.x, f.y, f.rotation = left, AC_ROW_BOTTOM, 0
        fu.x, fu.y, fu.rotation = left, AC_ROW_DEVICES, 90
        out.x, out.y, out.rotation = right, AC_ROW_BOTTOM, 0
        for w in sheet.wires:
            if w.touches(f.id) and w.touches(fu.id):
                w.points = []
        pts = [(left, DC_U_TOP), (right, DC_U_TOP)]
        w_out.points = pts if w_out.a.element_id == fu.id else pts[::-1]
        if spd is None:
            continue
        w_spd, sp = spd
        sp.x, sp.y, sp.rotation = mid, DC_SPD_Y, 180
        pts = [(left, DC_U_TOP), (mid, DC_U_TOP)]
        w_spd.points = pts if w_spd.a.element_id == fu.id else pts[::-1]
        for w in sheet.wires:
            if w.touches(sp.id) and (w.a.port if w.a.element_id == sp.id else w.b.port) == "PE":
                tgt = by_id.get(w.b.element_id if w.a.element_id == sp.id else w.a.element_id)
                if tgt is not None:
                    pe_wires.append((w, tgt, mid))
    # PE lišta DC části (rozvod svorkami, bez XPE): vpravo za DC částí nahoře, porty nahoře
    bars = {t.id: t for _w, t, _x in pe_wires if t.symbol_id == "sb.pe_bar"}
    edge = x0 + (len(strings) - 1) * DC_U_PITCH + DC_U_WIDTH + DC_SPD_DX + DC_U_GAP
    for bar in bars.values():
        bar.x, bar.y, bar.rotation = edge + 12.5, DC_PE_Y - 7.5, 0
        edge += 40.0
    bus_span = None
    if bus is not None and bus.rotation % 360 == 0 and not bus.mirror:
        lo, hi = line_span(element_symbol(project, bus, context._lib()))
        bus_span = (bus.x + lo, bus.x + hi)
    for w, tgt, mid in pe_wires:
        if tgt.symbol_id == "sb.pe_bar":
            end = w.b if w.b.element_id == tgt.id else w.a
            end.port = "1"           # všechny PE do jednoho portu: souběh vodičů do téhož konce je odbočka
            tx = tgt.x - 12.5
        else:
            tx = tgt.x
        pts = [(mid, DC_PE_Y), (tx, DC_PE_Y)]
        if bus_span is not None and bus_span[0] - 1e-6 <= tx <= bus_span[1] + 1e-6 and tgt.y < bus.y:
            # XPE pod parametrickou sběrnicí (vývod 1 nad ním): PE svodičů ji neprotne – vlevo kolem jejího začátku
            # a zleva k vodiči vývod 1 → XPE (souběh do téhož konce = odbočka „T“). Výš než PE svodiče AC, který
            # přichází zprava v y = AC_ROW_BOTTOM + 15 – obě odbočky v jednom bodě by vypadaly jako křížení bez uzlu
            xb, yb = bus_span[0] - DC_PE_AROUND, AC_ROW_BOTTOM + 15.0 + DC_PE_JOIN_DY
            pts = [(mid, DC_PE_Y), (xb, DC_PE_Y), (xb, yb), (tx, yb)]
        w.points = pts if w.b.element_id == tgt.id else pts[::-1]


def build_dc_part(ctx: ChainContext, sb: Sheet) -> None:
    """DC část rozvaděče FVE rodinného domu na listu `sb` (AC část už je hotová): pojistkové odpínače + SPD stringů
    všech střídačů za AC přívody (DC přívody za vším, co AC část označila X<číslo>; porty JPS se posunou), tvar „U“,
    artikly a neurčené In."""
    from envocad.generator.boards.rfve_dc import (
        _apply_component,
        _apply_spd_component,
        _mark_unresolved,
        fuse_of,
    )
    p, s, blk, dc = ctx.project, ctx.sheet, ctx.main, ctx.spec["dc"]
    dc_first = ctx.geo.dc_first
    macros = ctx.spec.get("macros") or {}
    sb.layout.params["network"] = "3NPE, 50 Hz / DC IT"
    sb.layout.params["un"] = "230/400 V AC / max. 1000 V DC"
    groups = [(i + 1, t.ref, [g.ref for g in gens], fuse_of(ctx, t)[0])
              for i, (t, gens) in enumerate(zip(ctx.inverters, ctx.strings))]
    # DC přívody za vším, co AC část označila X<číslo> (PE lišta, svorkovnice); porty JPS se posunou s nimi
    used = [int(m.group(1)) for e in sb.elements if (m := re.fullmatch(r"X(\d+)", e.ref or ""))]
    first = max([dc_first - 1, *used]) + 1
    if first != dc_first:
        for w in s.wires:
            for end in (w.a, w.b):
                m = re.fullmatch(r"X(\d+)", end.port) if end.element_id == blk.id else None
                if m and int(m.group(1)) >= dc_first:
                    end.port = f"X{int(m.group(1)) + first - dc_first}"
    _add_dc_part(p, sb, groups, macros.get("dc_tech", ""), dc, first)
    _dc_from_below(p, sb)
    _apply_spd_component(sb, dc.get("spd_component"))
    _apply_component(sb, dc.get("fuse_component"), "fve.fuse_disconnect")
    whys = [why for fin, why in ctx.fuse_cache.values() if not fin]
    if whys:   # pojistky bez In jsou jen ze skupin, kde nic nevyhovělo
        _mark_unresolved(sb.elements, FUSE_SYMBOLS, "; ".join(dict.fromkeys(whys)))
