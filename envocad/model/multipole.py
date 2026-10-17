"""Vícepólový pohled odvozený z jednopólového listu (bez Qt).

Nic se nekopíruje: pohled se počítá z `Sheet` – každá žíla vodiče (`Wire.conductors`) je samostatná čára
mezi „póly“ prvků. Pól = port prvku posunutý kolmo na směr portu o násobek `POLE_PITCH`.
Prvek s průchozími porty (dva porty proti sobě, např. jistič 1–2) se v pohledu opakuje pro každou
spínanou žílu; nespínané žíly (N u 3p jističe, PE) jdou kolem prvku jako přímá čára.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from envocad.model.designation import element_name
from envocad.model.project import FEED_SYMBOLS, Element, Sheet, Wire
from envocad.model.symbol import GRID, Symbol, rotate_dir

POLE_PITCH = 3 * GRID  # 7,5 mm mezi póly
COL_GAP = 30.0          # mezera mezi sloupci automatického rozmístění (ve směru toku)
ROW_GAP = 15.0          # mezera mezi prvky ve sloupci (kolmo na tok)
BAR_GAP = 32.0          # PE lišta pod řadou vývodů: mezera za vývody (štítek kabelu ~13 mm, příčky PE pod ním)
SOURCE_SYMBOLS = {"sb.feed_in", "fve.pv_string", "fve.battery"}  # zdroje toku (síť je konec)

# Kanonické pořadí žil (shora dolů / zleva doprava)
CANON = ["L1", "L2", "L3", "N", "PE", "PEN", "DC+", "DC-", "+", "-", "L+", "L-"]
NEVER_SWITCHED = {"PE", "PEN"}
TERMINAL_SYMBOLS = {"sb.feed_in", "sb.feed_out", "sb.terminal_block", "fve.terminal", "sb.pe_bar"}
# řadové svorky: prvek v JPS = skupina svorek (jedna na žílu), čísla v atributu `terminal` ("1 2 3 4 5" nebo "1")
TERMINAL_BLOCK_SYMBOLS = {"sb.terminal_block", "fve.terminal", "sb.feed_in", "sb.feed_out"}  # přívod/vývod = svorky X1:1…n

OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
# kolmý směr pro řazení pólů (model, Y nahoru): vodorovný tok → póly dolů, svislý tok → póly doprava
PERP = {"E": (0.0, -1.0), "W": (0.0, -1.0), "N": (1.0, 0.0), "S": (1.0, 0.0)}


def canon_key(c: str) -> tuple[int, str]:
    return (CANON.index(c) if c in CANON else len(CANON), c)


def parse_conductors(text: str) -> list[str]:
    """„L1 L2 L3 N PE“ / „L1,L2“ → seznam žil (bez duplicit, pořadí zachováno)."""
    out: list[str] = []
    for tok in text.replace(",", " ").replace(";", " ").split():
        if tok not in out:
            out.append(tok)
    return out


def default_conductors(a: Element, pa: str, b: Element, pb: str) -> list[str]:
    """Výchozí žíly nového vodiče podle portů a pólů připojených prvků."""
    for e in (a, b):
        if e.symbol_id.startswith("ctl."):  # ovládací obvod: jedna žíla
            return ["L"]
    for p in (pa, pb):
        up = p.upper()
        if up in ("DC+", "DC-", "+", "-"):
            return [p]
        if up.startswith("DC") or up == "BAT":  # jednopólová DC čára = pár DC+ / DC-
            return ["DC+", "DC-"]
        if up == "PE":
            return ["PE"]
    poles = 1
    for e in (a, b):
        poles = max(poles, e.poles)
        try:
            poles = max(poles, int(e.attrs.get("phases") or 0))
        except ValueError:
            pass
    return ["L1", "L2", "L3", "N", "PE"] if poles >= 3 else ["L1", "N", "PE"]


def is_terminal_block(e: Element) -> bool:
    return e.symbol_id in TERMINAL_BLOCK_SYMBOLS


def terminal_numbers(e: Element, n: int) -> list[str]:
    """Čísla svorek skupiny pro n žil z atributu `terminal`: seznam („1 2 3 N PE“) nebo první číslo („6“ → 6, 7, 8…).
    Bez atributu vrací prázdné řetězce."""
    toks = parse_conductors(e.attrs.get("terminal", ""))
    if not toks:
        # přívod/vývod bez zadaných čísel: svorky 1…n
        return [str(i + 1) for i in range(n)] if e.symbol_id in FEED_SYMBOLS else [""] * n
    if len(toks) == 1 and toks[0].isdigit() and n > 1:
        k = int(toks[0])
        return [str(k + i) for i in range(n)]
    return (toks + [""] * n)[:n]


def terminal_designation(e: Element, slots: list[str], conductor: str) -> str:
    """„X2:7“ pro žílu na svorkovém prvku (prázdné, když číslo chybí)."""
    nums = terminal_numbers(e, len(slots))
    i = slots.index(conductor) if conductor in slots else -1
    num = nums[i] if i >= 0 else ""
    return f"{e.ref}:{num}" if num else ""


def wire_conductors(w: Wire) -> list[str]:
    return list(w.conductors) if w.conductors else ["L1"]


def through_ports(sym: Symbol, rotation: int) -> tuple[str, str] | None:
    """Dvojice průchozích portů (proti sobě), pokud má symbol právě dva porty s opačným směrem."""
    if len(sym.ports) != 2:
        return None
    p, q = sym.ports
    if OPPOSITE.get(rotate_dir(p.dir, rotation)) == rotate_dir(q.dir, rotation):
        return (p.name, q.name)
    return None


@dataclass
class ElementPoles:
    element: Element
    symbol: Symbol
    slots: list[str]                      # žíly v pořadí slotů (0 = na portu)
    switched: list[str]                   # žíly, které prvek spíná (opakuje se pro ně symbol)
    bypass: list[str]                     # žíly, které jdou kolem prvku
    through: tuple[str, str] | None       # průchozí porty
    per_port: dict[str, set[str]] = field(default_factory=dict)
    origin: tuple[float, float] = (0.0, 0.0)  # pozice prvku ve vícepólu (ruční nebo z automatického rozmístění)
    # žíla připojená na volnou svorku pólu jiné žíly: {žíla: žíla pólu} – např. cívka A1 = L1, A2 = N
    # → {"N": "L1"}: N se napojí na A2 pólu L1 (prvek spíná/napájí jedním pólem dvě různé žíly)
    joined: dict[str, str] = field(default_factory=dict)

    def slot(self, conductor: str) -> int:
        conductor = self.joined.get(conductor, conductor)
        return self.slots.index(conductor) if conductor in self.slots else 0

    def pole_pos(self, port: str, conductor: str) -> tuple[float, float]:
        """Pozice pólu pro danou žílu na daném portu (model mm, ve škále pohledu)."""
        e = self.element
        px, py = e.port_pos(self.symbol, port)
        d = rotate_dir(self.symbol.port(port).dir, e.rotation)
        ox, oy = PERP[d]
        k = self.slot(conductor)
        mx, my = self.origin
        return (mx + (px - e.x) + ox * k * POLE_PITCH, my + (py - e.y) + oy * k * POLE_PITCH)

    @property
    def per_pole(self) -> bool:
        """Kreslí se po pólech: průchozí prvek, nebo přívod/vývod (svorka na každou žílu)."""
        return bool(self.switched) and (self.through is not None or self.element.symbol_id in FEED_SYMBOLS)

    def pole_offset(self, conductor: str) -> tuple[float, float]:
        """Posun opakovaného symbolu pro spínanou žílu (podle směru průchozích portů, u přívodu podle jeho portu)."""
        if not self.through and self.element.symbol_id not in FEED_SYMBOLS:
            return (0.0, 0.0)
        port = self.through[0] if self.through else self.symbol.ports[0].name
        d = rotate_dir(self.symbol.port(port).dir, self.element.rotation)
        ox, oy = PERP[d]
        k = self.slot(conductor)
        return (ox * k * POLE_PITCH, oy * k * POLE_PITCH)


BUS_SYMBOL = "sb.busbar"


def perp_extent(ep: ElementPoles) -> float:
    """Rozměr prvku kolmo na směr toku včetně všech pólů (mm)."""
    if ep.element.symbol_id == BUS_SYMBOL:
        return POLE_PITCH   # sběrnice se kreslí přes celou stranu, v rozmístění nezabírá místo
    x0, y0, x1, y1 = ep.symbol.bounds()
    horizontal = ep.through is None or rotate_dir(ep.symbol.port(ep.through[0]).dir, ep.element.rotation) in ("E", "W")
    if ep.through is None and ep.symbol.ports:
        horizontal = rotate_dir(ep.symbol.ports[0].dir, ep.element.rotation) in ("E", "W")
    base = (y1 - y0) if horizontal else (x1 - x0)
    if ep.element.rotation in (90, 270):
        base = (x1 - x0) if horizontal else (y1 - y0)
    # buňka na pól má vždy celou rozteč, aby prvky se stejným počtem žil měly stejný rozměr (zarovnání sloupců)
    return max(base, POLE_PITCH) + max(0, len(ep.slots) - 1) * POLE_PITCH


def flow_extent(ep: ElementPoles) -> float:
    if ep.element.symbol_id == BUS_SYMBOL:
        return 5.0 * max(len(ep.slots), 1) + 5.0   # čáry potenciálů pod sebou
    x0, y0, x1, y1 = ep.symbol.bounds()
    w, h = (x1 - x0, y1 - y0) if ep.element.rotation in (0, 180) else (y1 - y0, x1 - x0)
    return w if _flow_is_horizontal_for(ep) else h


def _flow_is_horizontal_for(ep: ElementPoles) -> bool:
    if ep.through:
        return rotate_dir(ep.symbol.port(ep.through[0]).dir, ep.element.rotation) in ("E", "W")
    if ep.symbol.ports:
        return rotate_dir(ep.symbol.ports[0].dir, ep.element.rotation) in ("E", "W")
    return True


def auto_layout(sheet: Sheet, poles: dict[str, ElementPoles], x0: float = 40.0, y_top: float = 250.0,
                bridges: dict[str, list[list[str]]] | None = None, page_w: float | None = None) -> dict[str, tuple[float, float]]:
    """Automatické rozmístění vícepólu po sloupcích („svorkové schéma“): hloubka od zdroje (přívod, síť, FV)
    určuje sloupec ve směru toku, uvnitř sloupce se prvky řadí podle pozice v JPS a rozestupují podle počtu pólů.
    Prvky s ruční pozicí (`mp_pos`) zůstávají, kde jsou. `page_w` (svislý tok): šířka strany – prvek, který by
    přesáhl hranici strany, začne na další straně (strany jsou v souřadnici x za sebou: strana k = [x0 + k·page_w, …)."""
    if not poles:
        return {}
    horizontal = sum(1 for ep in poles.values() if _flow_is_horizontal_for(ep)) * 2 >= len(poles)
    # skupiny svorek spojené můstkem tvoří jeden uzel (stejný sloupec) – napájení jde přes můstek, ne vodičem
    comp: dict[str, str] = {eid: eid for eid in poles}
    if bridges:
        owner: dict[tuple[str, str], str] = {}
        for eid, ep in poles.items():
            e = ep.element
            if is_terminal_block(e) and e.ref:
                for num in terminal_numbers(e, len(ep.slots)):
                    if num:
                        owner[(e.ref, num)] = eid
        for strip, groups in bridges.items():
            for g in groups:
                ids = [owner[(strip, n)] for n in g if (strip, n) in owner]
                for b in ids[1:]:
                    root = comp[ids[0]]
                    for k, v in comp.items():
                        if v == comp[b]:
                            comp[k] = root
    adj: dict[str, set[str]] = {c: set() for c in comp.values()}
    for w in sheet.wires:
        if w.a.element_id in comp and w.b.element_id in comp:
            ca, cb = comp[w.a.element_id], comp[w.b.element_id]
            if ca != cb:
                adj[ca].add(cb)
                adj[cb].add(ca)
    sources = {comp[eid] for eid, ep in poles.items() if ep.element.symbol_id in SOURCE_SYMBOLS}
    if not sources:
        key = (lambda ep: ep.element.x) if horizontal else (lambda ep: -ep.element.y)
        sources = {comp[min(poles.values(), key=key).element.id]}
    cdepth: dict[str, int] = dict.fromkeys(sources, 0)
    frontier = list(sources)
    while frontier:
        nxt = []
        for c in frontier:
            for n in adj[c]:
                if n not in cdepth:
                    cdepth[n] = cdepth[c] + 1
                    nxt.append(n)
        frontier = nxt
    last = max(cdepth.values(), default=0) + 1
    depth = {eid: cdepth.get(comp[eid], last) for eid in poles}
    # vývody vždy v dolní řadě (jako v EPLAN: přívody nahoře, rozvod, přístroje, vývody dole), PE lišta pod nimi
    sinks = [eid for eid, ep in poles.items() if ep.element.symbol_id == "sb.feed_out"]
    if sinks:
        bottom = max((d for eid, d in depth.items() if eid not in sinks), default=0) + 1
        for eid in sinks:
            depth[eid] = max(depth[eid], bottom)
        bottom = max(depth[eid] for eid in sinks)
        for eid in sinks:
            depth[eid] = bottom
    columns: dict[int, list[str]] = {}
    for eid, d in depth.items():
        columns.setdefault(d, []).append(eid)
    # sousedé přes vodiče (rodič = soused v předchozím sloupci)
    nb: dict[str, set[str]] = {eid: set() for eid in poles}
    for w in sheet.wires:
        if w.a.element_id in nb and w.b.element_id in nb:
            nb[w.a.element_id].add(w.b.element_id)
            nb[w.b.element_id].add(w.a.element_id)
    key = ((lambda i: (-poles[i].element.y, poles[i].element.x)) if horizontal
           else (lambda i: (poles[i].element.x, -poles[i].element.y)))
    # strom: každý prvek má jednoho rodiče (první soused v předchozím sloupci podle JPS); prvky bez rodiče,
    # které patří do uzlu spojeného můstkem, se zavěsí vedle člena uzlu s rodičem; zbytek jsou kořeny
    children: dict[str, list[str]] = {eid: [] for eid in poles}
    parent: dict[str, str] = {}
    bars = [i for i in poles if poles[i].element.symbol_id == "sb.pe_bar"]   # PE lišta: mimo strom, pod svými sousedy
    for d in sorted(columns):
        for i in sorted(columns[d], key=key):
            if i in bars:
                continue
            # rodič = nejbližší soused s menší hloubkou (vývod posunutý do dolní řady má rodiče o víc sloupců výš)
            ps = sorted((p for p in nb[i] if depth.get(p, d) < d and p not in bars), key=lambda p: (-depth[p], key(p)))
            if ps:
                parent[i] = ps[0]
                children[ps[0]].append(i)
    for d in sorted(columns):
        for i in sorted(columns[d], key=key):
            if i in parent or d == 0:
                continue
            mates = [m for m in columns[d] if comp[m] == comp[i] and m in parent]
            if mates:
                anchor = parent[mates[0]]
                parent[i] = anchor
                children[anchor].append(i)
    for c in children.values():
        c.sort(key=key)
    roots = [i for i in sorted(poles, key=key) if i not in parent and i not in bars]

    def width(i: str) -> float:
        own = perp_extent(poles[i]) + 8.0
        kids = children[i]
        return max(own, sum(width(c) for c in kids) + ROW_GAP * max(len(kids) - 1, 0))

    col_w = {d: max(flow_extent(poles[i]) for i in ids) for d, ids in columns.items()}
    flow_pos: dict[int, float] = {}
    pos = x0 if horizontal else y_top
    for d in sorted(columns):
        flow_pos[d] = pos
        pos = pos + col_w[d] + COL_GAP if horizontal else pos - col_w[d] - COL_GAP
    out: dict[str, tuple[float, float]] = {}
    sign = -1.0 if horizontal else 1.0  # vodorovný tok: prvky ve sloupci jdou dolů; svislý: doprava

    def page_fix(start: float, own: float) -> float:
        """Začátek prvku; přesáhl-li by hranici strany, posune se na začátek další strany."""
        if not page_w or horizontal:
            return start
        k0 = int((start - x0) // page_w)
        k1 = int((start + own - x0) // page_w)
        return start if k1 == k0 else x0 + k1 * page_w

    wire_between: dict[tuple[str, str], Wire] = {}
    for w in sheet.wires:
        wire_between.setdefault((w.a.element_id, w.b.element_id), w)
        wire_between.setdefault((w.b.element_id, w.a.element_id), w)

    def link_wish(parent: str, child: str) -> float | None:
        """Kolmá pozice dítěte, při které je jeho pól pod pólem rodiče, ze kterého vede spojovací žíla
        (vývod PE pod PE svodiče, ne pod L1 – jinak vede svisle skrz rodiče)."""
        w = wire_between.get((parent, child))
        if w is None:
            return None
        pp, cp = (w.a.port, w.b.port) if w.a.element_id == parent else (w.b.port, w.a.port)
        c0 = wire_conductors(w)[0]
        ep_p, ep_c = poles[parent], poles[child]
        try:
            px, py = ep_p.pole_pos(pp, c0)
            save = ep_c.origin
            ep_c.origin = (0.0, 0.0)
            cx, cy = ep_c.pole_pos(cp, c0)
            ep_c.origin = save
        except (KeyError, StopIteration, ValueError):
            return None
        return (py - cy) if horizontal else (px - cx)

    def place(i: str, start: float) -> float:
        """Umístí prvek a jeho podstrom; vrátí konec podstromu (kolmo na tok) – kvůli skokům na další stranu."""
        d = depth[i]
        own = perp_extent(poles[i]) + 8.0
        start = page_fix(start, own)
        perp = start + sign * 8.0
        fp = flow_pos[d]
        out[i] = (fp + col_w[d] / 2, perp) if horizontal else (perp, fp - col_w[d] / 2)
        poles[i].origin = out[i]
        cursor = start
        end = start + sign * own
        for c in children[i]:
            wish = link_wish(i, c)
            if wish is not None:
                want = wish - sign * 8.0
                if (want - cursor) * sign > 0:
                    cursor = want
            e = place(c, cursor)
            cursor = e + sign * ROW_GAP
            end = max(end, e) if sign > 0 else min(end, e)
        return end

    cursor = y_top if horizontal else x0
    for r in roots:
        cursor = place(r, cursor) + sign * ROW_GAP
    for b in bars:
        ns = [n for n in nb[b] if n in out]
        d = max([depth[n] for n in ns] + [depth[x] for x in sinks], default=depth[b] - 1) + 1   # PE lišta dole pod vývody
        if d not in flow_pos:
            col_w[d] = flow_extent(poles[b])
            ds = depth[sinks[0]] if sinks else None
            if ds is not None and ds in flow_pos and d == ds + 1:
                # těsně pod řadou vývodů (pod jejich štítky kabelů), ne až na okraji strany
                gap = col_w[ds] + BAR_GAP + col_w[d] / 2
                flow_pos[d] = flow_pos[ds] + (gap if horizontal else -gap) - (col_w[d] / 2 if horizontal else -col_w[d] / 2)
            else:
                flow_pos[d] = pos + (15.0 if horizontal else -15.0)   # o kus dál, ať příčky PE nevedou přes popisky vývodů
            pos = pos + col_w[d] + COL_GAP if horizontal else pos - col_w[d] - COL_GAP
        fp = flow_pos[d]
        if ns:
            vals = [(out[n][1] if horizontal else out[n][0]) for n in ns]
            if page_w and not horizontal:
                # sousedé na více stranách: lišta na stranu s nejvíc sousedy (při shodě na dřívější), uprostřed nich
                from collections import Counter
                pages = Counter(int((v - x0) // page_w) for v in vals)
                k = min(pages.items(), key=lambda kv: (-kv[1], kv[0]))[0]
                vals = [v for v in vals if int((v - x0) // page_w) == k]
            perp = (min(vals) + max(vals)) / 2
        else:
            perp = cursor + sign * 8.0
            cursor += sign * (width(b) + ROW_GAP)
        perp = round(perp / GRID) * GRID
        if page_w and not horizontal and ns:
            # lišta zůstává uvnitř své strany (střed by mohl padnout k okraji)
            k = int((vals[0] - x0) // page_w)
            perp = min(max(perp, x0 + k * page_w + 8.0), x0 + (k + 1) * page_w - perp_extent(poles[b]) - 8.0)
        out[b] = (fp + col_w[d] / 2, perp) if horizontal else (perp, fp - col_w[d] / 2)
    for i, ep in poles.items():
        if ep.element.mp_pos:
            out[i] = tuple(ep.element.mp_pos)
    return out


def element_poles(sheet: Sheet, e: Element, sym: Symbol) -> ElementPoles:
    per_port: dict[str, set[str]] = {p.name: set() for p in sym.ports}
    for w in sheet.wires:
        for end in (w.a, w.b):
            if end.element_id == e.id and end.port in per_port:
                per_port[end.port].update(wire_conductors(w))
    all_c: set[str] = set().union(*per_port.values()) if per_port else set()
    slots = sorted(all_c, key=canon_key)
    thr = through_ports(sym, e.rotation)
    switched: list[str] = []
    bypass: list[str] = []
    if is_terminal_block(e) and (thr or e.symbol_id in FEED_SYMBOLS):
        switched = list(slots)  # každá žíla má svou svorku
    elif thr:
        n = e.poles
        for c in slots:
            if c not in NEVER_SWITCHED and len(switched) < n:
                switched.append(c)
            elif c in per_port[thr[0]] and c in per_port[thr[1]]:
                bypass.append(c)
        if not switched and slots:
            switched.append(slots[0])
    joined = _join_single_port(per_port, thr, switched, bypass, slots) if thr else {}
    if joined:
        slots = [c for c in slots if c not in joined]
    return ElementPoles(e, sym, slots, switched, bypass, thr, per_port, joined=joined)


def _join_single_port(per_port: dict[str, set[str]], thr: tuple[str, str], switched: list[str], bypass: list[str],
                      slots: list[str]) -> dict[str, str]:
    """Žíly průchozího prvku, které nejsou spínané ani nevedou kolem (jsou jen na jednom portu – cívka A1 = L1,
    A2 = N), se připojí na volnou svorku pólu na tomtéž portu: pól spínané žíly, která na tom portu není. PE/PEN se
    nepřipojuje (ochranný vodič nevede přes pól)."""
    out: dict[str, str] = {}
    taken: dict[str, set[str]] = {p: {c for c in per_port.get(p, set()) if c in switched} for p in thr}
    for c in slots:
        if c in switched or c in bypass or c in NEVER_SWITCHED:   # PE nikdy nejde přes pól (SPD: svorka PE zvlášť)
            continue
        ports = [p for p in thr if c in per_port.get(p, set())]
        if len(ports) != 1:
            continue
        port = ports[0]
        free = next((s for s in switched if s not in taken[port]), None)
        if free is not None:
            out[c] = free
            taken[port].add(free)
    return out


def terminal_text(w: Wire, conductor: str, side: str) -> str:
    return (w.terminals.get(conductor) or {}).get(side, "")


def wire_end_terminal(sheet: Sheet, w: Wire, conductor: str, side: str) -> str:
    """Svorka na konci žíly: ruční z `Wire.terminals`, jinak odvozená z čísel svorkového prvku."""
    t = terminal_text(w, conductor, side)
    if t:
        return t
    end = w.a if side == "a" else w.b
    try:
        e = sheet.element(end.element_id)
    except KeyError:
        return ""
    if not is_terminal_block(e):
        return ""
    slots = sorted({c for ww in sheet.wires for end2 in (ww.a, ww.b) if end2.element_id == e.id
                    for c in wire_conductors(ww)}, key=canon_key)
    return terminal_designation(e, slots, conductor)


def auto_number_terminal_blocks(sheet: Sheet) -> dict[str, str]:
    """Doplní čísla svorek skupinám (prvky sb.terminal_block / fve.terminal) bez atributu `terminal`:
    v každé svorkovnici (ref) pokračuje za nejvyšším použitým číslem. Vrací {element_id: "1 2 3 4 5"}."""
    highest: dict[str, int] = {}
    groups: list[tuple[Element, list[str]]] = []
    for e in sheet.elements:
        if not is_terminal_block(e) or not e.ref:
            continue
        slots = sorted({c for w in sheet.wires for end in (w.a, w.b) if end.element_id == e.id
                        for c in wire_conductors(w)}, key=canon_key) or ["L1"]
        nums = terminal_numbers(e, len(slots))
        if any(nums):
            for x in nums:
                if x.isdigit():
                    highest[e.ref] = max(highest.get(e.ref, 0), int(x))
        else:
            groups.append((e, slots))
    out: dict[str, str] = {}
    for e, slots in groups:
        start = highest.get(e.ref, 0) + 1
        out[e.id] = " ".join(str(start + i) for i in range(len(slots)))
        highest[e.ref] = start + len(slots) - 1
    return out


def auto_number_terminals(sheet: Sheet) -> dict[str, dict[str, dict[str, str]]]:
    """Navrhne číslování svorek: pro každý svorkový prvek (X…) očísluje žíly napojených vodičů 1, 2, 3…
    v pořadí vodičů na listu. Už vyplněné svorky zůstávají. Vrací {wire_id: nové terminals} jen pro změněné."""
    counters: dict[str, int] = {}
    used: dict[str, set[str]] = {}
    for w in sheet.wires:  # nejdřív posbírat obsazená čísla
        for c, t in w.terminals.items():
            for side in ("a", "b"):
                v = t.get(side, "")
                if ":" in v:
                    used.setdefault(v.split(":")[0], set()).add(v.split(":", 1)[1])
    result: dict[str, dict[str, dict[str, str]]] = {}
    for w in sheet.wires:
        new = {c: dict(t) for c, t in w.terminals.items()}
        changed = False
        for side, end in (("a", w.a), ("b", w.b)):
            try:
                el = sheet.element(end.element_id)
            except KeyError:
                continue
            if el.symbol_id not in TERMINAL_SYMBOLS or is_terminal_block(el) or not el.ref:
                continue
            for c in wire_conductors(w):
                if new.get(c, {}).get(side):
                    continue
                n = counters.get(el.ref, 0)
                while True:
                    n += 1
                    if str(n) not in used.get(el.ref, set()):
                        break
                counters[el.ref] = n
                used.setdefault(el.ref, set()).add(str(n))
                new.setdefault(c, {})[side] = f"{el.ref}:{n}"
                changed = True
        if changed:
            result[w.id] = new
    return result


# průchozí přístroje s pólovým číslováním 1/2, 3/4, 5/6 (jistič, odpínač, stykač…): porty „1“ (vstup) a „2“ (výstup)
POLE_NUMBERED_PORTS = ("1", "2")
# prvky s porty „1“, „2“…, které nejsou průchozí přístroje (odbočky sběrnice, svorky PE lišty, svorkové prvky)
NOT_POLE_NUMBERED = TERMINAL_SYMBOLS | TERMINAL_BLOCK_SYMBOLS | {"sb.busbar", "sb.junction"}
UNSWITCHED_POLES = {"N"} | NEVER_SWITCHED


def port_conductors(sheet: Sheet, element_id: str, port: str) -> list[str]:
    """Žíly všech vodičů listu napojených na port prvku (kanonické pořadí, bez duplicit)."""
    return sorted({c for w in sheet.wires for end in (w.a, w.b)
                   if end.element_id == element_id and end.port == port for c in wire_conductors(w)}, key=canon_key)


def device_terminal(sheet: Sheet, w: Wire, conductor: str, side: str) -> tuple[str, bool]:
    """Svorka konce žíly „F2:3“ a příznak, zda je odvozená pravidlem.

    Pořadí: ruční přiřazení z `Wire.terminals`; svorkový prvek přes `wire_end_terminal` (čísla svorek skupiny);
    průchozí přístroj s porty 1/2 → pól k (pořadí fázové žíly mezi žilami portu) = vstup 2k+1 / výstup 2k+2;
    spínaný N (přístroj má pól navíc – 4p jistič/vypínač, 1p+N) je další pól za fázemi (IEC 60947-1 příl. L,
    číslování hlavních pólů 1/2, 3/4, 5/6, 7/8 → 4p: N = 7/8); nespínaný N a PE/PEN = jméno žíly („F2:N“) –
    odvozeno=True; jinak jméno portu („F1:L“)."""
    t = terminal_text(w, conductor, side)
    if t:
        return t, False
    end = w.a if side == "a" else w.b
    try:
        e = sheet.element(end.element_id)
    except KeyError:
        return end.port, False
    name = element_name(e)
    if is_terminal_block(e):
        t = wire_end_terminal(sheet, w, conductor, side)
        return (t or f"{name}:{end.port}"), False
    if e.symbol_id not in NOT_POLE_NUMBERED and end.port in POLE_NUMBERED_PORTS:
        phases = [c for c in port_conductors(sheet, e.id, end.port) if c not in UNSWITCHED_POLES]
        if conductor in NEVER_SWITCHED or (conductor == "N" and len(phases) >= e.poles):
            return f"{name}:{conductor}", True
        if conductor == "N":
            k = len(phases)                       # spínaný N = pól za fázemi
        else:
            k = phases.index(conductor) if conductor in phases else 0
        return f"{name}:{2 * k + 1 + POLE_NUMBERED_PORTS.index(end.port)}", True
    return f"{name}:{end.port}", False


# ---- geometrie pohledu (sdílí ji vícepólová scéna v ui/ a kontrola překryvů textů) ------------------------------
MP_X0 = 42.5          # začátek rozmístění – vlevo názvy potenciálů sběrnice
MP_Y_TOP = 60.0       # odstup první řady od horního okraje listu (nahoře nadpis rozvaděče)
MP_PAGE_GAP = 20.0    # mezera mezi stranami pod sebou
LABEL_GAP = 1.5       # odstup popisku od značky


def page_width(sheet: Sheet) -> float:
    """Použitelná šířka strany vícepólu pro rozmístění (bez okrajů rámečku)."""
    from envocad.model.frame import MARGIN
    return sheet.width - MP_X0 - MARGIN - 10.0


def page_pitch(sheet: Sheet) -> float:
    return sheet.height + MP_PAGE_GAP


def paginate(sheet: Sheet, poles: dict[str, ElementPoles]) -> tuple[dict[str, int], int]:
    """Rozmístění (strany za sebou v x) → strany pod sebou: prvek na straně k se posune o k·šířka doleva a o
    k·(výška + mezera) dolů (mění `origin`). Ruční pozice (`mp_pos`) jsou už stránkované – strana se jim jen určí.
    Vrací (prvek → strana, počet stran)."""
    x0, pw, pitch = MP_X0, page_width(sheet), page_pitch(sheet)
    page_of: dict[str, int] = {}
    n_pages = 1
    for eid, ep in poles.items():
        x, y = ep.origin
        if ep.element.mp_pos:
            k = max(0, int((sheet.height - y) // pitch))
        else:
            k = max(0, int((x - x0) // pw))
            ep.origin = (x - k * pw, y - k * pitch)
        page_of[eid] = k
        n_pages = max(n_pages, k + 1)
    return page_of, n_pages


def pe_join_ports(ep: ElementPoles) -> list[tuple[str, list[str]]]:
    """Porty průchozího prvku, na kterých je jen ochranný vodič (PE/PEN), který prvek nespíná ani nevede kolem –
    svodič přepětí (SPD): konce všech pólů na portu PE se spojí příčkou a PE vodič začíná na ní. Vrací
    [(port, [PE…])]."""
    if not (ep.per_pole and ep.through and ep.switched) or ep.element.symbol_id in FEED_SYMBOLS:
        return []
    out = []
    for port in ep.through:
        conds = ep.per_port.get(port, set())
        if conds and all(c in NEVER_SWITCHED and c not in ep.switched and c not in ep.bypass for c in conds):
            out.append((port, sorted(conds, key=canon_key)))
    return out


def pe_join_segments(ep: ElementPoles) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Příčky `pe_join_ports`: od konce prvního do konce posledního pólu včetně místa, kde začíná PE vodič."""
    out = []
    for port, conds in pe_join_ports(ep):
        pts = [ep.pole_pos(port, c) for c in [*ep.switched, *conds]]
        pts.sort()
        if pts[0] != pts[-1]:
            out.append((pts[0], pts[-1]))
    return out


def _rot_box(sym: Symbol, x: float, y: float, rotation: int) -> tuple[float, float, float, float]:
    from envocad.model.symbol import rotate_point
    x0, y0, x1, y1 = sym.bounds()
    pts = [rotate_point(px, py, rotation) for px, py in ((x0, y0), (x1, y1), (x0, y1), (x1, y0))]
    return (x + min(p[0] for p in pts), y + min(p[1] for p in pts), x + max(p[0] for p in pts), y + max(p[1] for p in pts))


def pole_symbol_for(ep: ElementPoles, conductor: str | None) -> Symbol:
    return ep.symbol.pole_symbol() if conductor else ep.symbol


def pole_anchor(ep: ElementPoles, conductor: str | None) -> tuple[float, float]:
    """Poloha položky pólu ve vícepólu (model mm) – počátek značky pólu."""
    ox, oy = ep.pole_offset(conductor) if conductor else (0.0, 0.0)
    return (ep.origin[0] + ox, ep.origin[1] + oy)


def pole_label_texts(ep: ElementPoles) -> list[tuple[str, float]]:
    """Řádky popisku prvku ve vícepólu: označení (2,5 mm) a zobrazené atributy (2 mm); u skupiny svorek bez čísel."""
    e = ep.element
    lines = [(e.ref, 2.5)] if e.ref else []
    skip = {"ref", "terminal"} if is_terminal_block(e) else {"ref"}   # čísla svorek jsou u pólů
    lines += [(a.display(e.attrs[a.key]), 2.0) for a in ep.symbol.attributes
              if a.show and a.key not in skip and e.attrs.get(a.key)]
    return lines


def pole_label_lines(ep: ElementPoles) -> list[tuple[float, float, str, float, str]]:
    """Popisek prvku ve vícepólu: [(x, y, text, výška, zarovnání)] v souřadnicích pohledu (mm, Y nahoru), texty
    vždy vodorovně. Přívod/vývod: označení svorkovnice vlevo u svorek. Vícepólový přístroj se svislým tokem
    (póly vedle sebe): vlevo od prvního pólu zarovnaný doprava, horní řádek u horního okraje pólů – nepřeškrtne
    žílu prvního pólu ani nevede přes přívodní žíly nad prvkem. Skupina svorek: nad můstky. Jednopólový prvek:
    poloha popisku značky."""
    from envocad.model.symbol import rotate_point
    e = ep.element
    c0 = ep.switched[0] if ep.per_pole and ep.switched else None
    sym = pole_symbol_for(ep, c0)
    px, py = pole_anchor(ep, c0)

    def at(lx: float, ly: float) -> tuple[float, float]:
        rx, ry = rotate_point(lx, ly, e.rotation)
        return (px + rx, py + ry)

    if e.symbol_id in ("sb.feed_in", "sb.feed_out"):
        if not e.ref:
            return []
        cy = -2.5 if e.symbol_id == "sb.feed_in" else 2.5
        x, y = at(-2.5, cy - 0.8)
        return [(x, y, e.ref, 2.5, "right")]
    lines = pole_label_texts(ep)
    if not lines:
        return []
    multi = len(ep.switched) > 1
    if multi and not is_terminal_block(e) and not _flow_is_horizontal_for(ep):
        boxes = [_rot_box(sym, *pole_anchor(ep, c), e.rotation) for c in ep.switched]
        x = min(b[0] for b in boxes) - LABEL_GAP
        y = max(b[3] for b in boxes) - lines[0][1]
        out = []
        for text, h in lines:
            out.append((x, y, text, h, "right"))
            y -= h + 1.0
        return out
    if multi:
        x0, y0, _x1, y1 = sym.bounds()
        stack = sum(h + 1.0 for _, h in lines[1:])
        if e.rotation == 270 and not is_terminal_block(e):
            lx, ly = x0, y0 - 1.5 - (stack + 2.5)
        else:
            lx, ly = x0, y1 + (7.5 if is_terminal_block(e) else 1.5)   # nad můstky
            if e.symbol_id in ("sb.terminal_block", "fve.terminal"):
                lx -= 3.5   # vedle svislé čáry svorky, ne přes ni
    else:
        lx, ly = sym.label_pos
        stack = 0.0
    x, y = at(lx, ly)
    out = []
    for text, h in lines:
        out.append((x, y + stack, text, h, "left"))
        stack -= h + 1.0
    return out


DIR_VEC = {"N": (0, 1), "E": (1, 0), "S": (0, -1), "W": (-1, 0)}


def _snap(v: float) -> float:
    return round(v / GRID) * GRID


def conductor_route(pa: tuple[float, float], da: str, pb: tuple[float, float], db: str, stagger: float = 0.0,
                    jog: float = 0.8) -> list[tuple[float, float]]:
    """Trasa žíly ve vícepólu (model mm, Y nahoru): vývod GRID z každého portu, L/Z vedení, příčka Z-trasy v `jog`
    délky (blízko cíle) posunutá o `stagger` (rovnoběžné žíly se nepřekrývají). Stejně kreslí scéna i kontrola."""
    stub = GRID
    va, vb = DIR_VEC[da], DIR_VEC[db]
    sa = (pa[0] + va[0] * stub, pa[1] + va[1] * stub)
    sb = (pb[0] + vb[0] * stub, pb[1] + vb[1] * stub)
    pts = [pa, sa]
    horizontal_first = da in ("E", "W")
    if horizontal_first and db in ("E", "W") and abs(sa[1] - sb[1]) > 1e-6:
        mx = _snap(sa[0] + (sb[0] - sa[0]) * jog) + stagger
        pts += [(mx, sa[1]), (mx, sb[1])]
    elif not horizontal_first and db in ("N", "S") and abs(sa[0] - sb[0]) > 1e-6:
        my = _snap(sa[1] + (sb[1] - sa[1]) * jog) - stagger   # scéna má Y dolů: posun +stagger tam = −stagger tady
        pts += [(sa[0], my), (sb[0], my)]
    elif horizontal_first:
        pts.append((sb[0], sa[1]))
    else:
        pts.append((sa[0], sb[1]))
    pts += [sb, pb]
    return pts


def conductor_label_anchor(pts: list[tuple[float, float]], staggered: bool) -> tuple[float, float, str, bool]:
    """Poloha popisku žíly (jako `geometry.wire_label_anchor`). U vodiče s více žilami vedenými Z-trasou
    (`staggered`) se příčka Z (rovnoběžné žíly jsou od sebe jen 2,5 mm) přeskočí a popisek jde na nejdelší jiný
    úsek – jinak by popisek jedné žíly ležel přes sousední žílu. Krátké úseky (< 6 mm) → výchozí poloha."""
    from envocad.model.geometry import wire_label_anchor
    if staggered and len(pts) == 6:
        segs = [(pts[i], pts[i + 1]) for i in (1, 3)]   # úseky mezi vývodem a příčkou (příčka = pts[2]–pts[3])
        a, b = max(segs, key=lambda s: abs(s[1][0] - s[0][0]) + abs(s[1][1] - s[0][1]))
        if abs(b[0] - a[0]) + abs(b[1] - a[1]) >= 6.0:
            return wire_label_anchor([a, b])
    return wire_label_anchor(pts)
