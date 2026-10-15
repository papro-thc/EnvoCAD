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
SCALE = 2.0  # roztažení pozic z JPS, aby se vedle sebe vešly póly

# Kanonické pořadí žil (shora dolů / zleva doprava)
CANON = ["L1", "L2", "L3", "N", "PE", "PEN", "DC+", "DC-", "+", "-", "L+", "L-"]
NEVER_SWITCHED = {"PE", "PEN"}
TERMINAL_SYMBOLS = {"sb.feed_in", "sb.feed_out", "sb.terminal_block", "fve.terminal", "sb.pe_bar"}

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
    for p in (pa, pb):
        up = p.upper()
        if up.startswith("DC") or up in ("+", "-", "BAT"):
            return [p if up != "BAT" else "DC+"]
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

    def slot(self, conductor: str) -> int:
        return self.slots.index(conductor) if conductor in self.slots else 0

    def pole_pos(self, port: str, conductor: str) -> tuple[float, float]:
        """Pozice pólu pro danou žílu na daném portu (model mm, ve škále pohledu)."""
        e = self.element
        px, py = e.port_pos(self.symbol, port)
        d = rotate_dir(self.symbol.port(port).dir, e.rotation)
        ox, oy = PERP[d]
        k = self.slot(conductor)
        # pozice prvku se roztahují (SCALE), symbol zůstává ve skutečné velikosti
        return (e.x * SCALE + (px - e.x) + ox * k * POLE_PITCH, e.y * SCALE + (py - e.y) + oy * k * POLE_PITCH)

    def pole_offset(self, conductor: str) -> tuple[float, float]:
        """Posun opakovaného symbolu pro spínanou žílu (podle směru průchozích portů)."""
        if not self.through:
            return (0.0, 0.0)
        d = rotate_dir(self.symbol.port(self.through[0]).dir, self.element.rotation)
        ox, oy = PERP[d]
        k = self.slot(conductor)
        return (ox * k * POLE_PITCH, oy * k * POLE_PITCH)


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
    if thr:
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
            if el.symbol_id not in TERMINAL_SYMBOLS or not el.ref:
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
