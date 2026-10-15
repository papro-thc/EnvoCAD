"""Vícepólový pohled odvozený z jednopólového listu (bez Qt).

Nic se nekopíruje: pohled se počítá z `Sheet` – každá žíla vodiče (`Wire.conductors`) je samostatná čára
mezi „póly“ prvků. Pól = port prvku posunutý kolmo na směr portu o násobek `POLE_PITCH`.
Prvek s průchozími porty (dva porty proti sobě, např. jistič 1–2) se v pohledu opakuje pro každou
spínanou žílu; nespínané žíly (N u 3p jističe, PE) jdou kolem prvku jako přímá čára.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from envocad.model.project import Element, Sheet, Wire
from envocad.model.symbol import GRID, Symbol, rotate_dir

POLE_PITCH = 3 * GRID  # 7,5 mm mezi póly
COL_GAP = 30.0          # mezera mezi sloupci automatického rozmístění (ve směru toku)
ROW_GAP = 15.0          # mezera mezi prvky ve sloupci (kolmo na tok)
SOURCE_SYMBOLS = {"sb.feed_in", "fve.pv_string", "fve.battery"}  # zdroje toku (síť je konec)

# Kanonické pořadí žil (shora dolů / zleva doprava)
CANON = ["L1", "L2", "L3", "N", "PE", "PEN", "DC+", "DC-", "+", "-", "L+", "L-"]
NEVER_SWITCHED = {"PE", "PEN"}
TERMINAL_SYMBOLS = {"sb.feed_in", "sb.feed_out", "sb.terminal_block", "fve.terminal", "sb.pe_bar"}
# řadové svorky: prvek v JPS = skupina svorek (jedna na žílu), čísla v atributu `terminal` ("1 2 3 4 5" nebo "1")
TERMINAL_BLOCK_SYMBOLS = {"sb.terminal_block", "fve.terminal"}

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
        return [""] * n
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

    def slot(self, conductor: str) -> int:
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

    def pole_offset(self, conductor: str) -> tuple[float, float]:
        """Posun opakovaného symbolu pro spínanou žílu (podle směru průchozích portů)."""
        if not self.through:
            return (0.0, 0.0)
        d = rotate_dir(self.symbol.port(self.through[0]).dir, self.element.rotation)
        ox, oy = PERP[d]
        k = self.slot(conductor)
        return (ox * k * POLE_PITCH, oy * k * POLE_PITCH)


def perp_extent(ep: ElementPoles) -> float:
    """Rozměr prvku kolmo na směr toku včetně všech pólů (mm)."""
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
                bridges: dict[str, list[list[str]]] | None = None) -> dict[str, tuple[float, float]]:
    """Automatické rozmístění vícepólu po sloupcích („svorkové schéma“): hloubka od zdroje (přívod, síť, FV)
    určuje sloupec ve směru toku, uvnitř sloupce se prvky řadí podle pozice v JPS a rozestupují podle počtu pólů.
    Prvky s ruční pozicí (`mp_pos`) zůstávají, kde jsou."""
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
    for d in sorted(columns):
        for i in sorted(columns[d], key=key):
            ps = sorted((p for p in nb[i] if depth.get(p) == d - 1), key=key)
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
    roots = [i for i in sorted(poles, key=key) if i not in parent]

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

    def place(i: str, start: float) -> None:
        d = depth[i]
        perp = start + sign * 8.0
        fp = flow_pos[d]
        out[i] = (fp + col_w[d] / 2, perp) if horizontal else (perp, fp - col_w[d] / 2)
        cursor = start
        for c in children[i]:
            place(c, cursor)
            cursor += sign * (width(c) + ROW_GAP)

    cursor = y_top if horizontal else x0
    for r in roots:
        place(r, cursor)
        cursor += sign * (width(r) + ROW_GAP)
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
    if thr and is_terminal_block(e):
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
    return ElementPoles(e, sym, slots, switched, bypass, thr, per_port)


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
