"""Potenciály: sledování, co je s čím vodivě spojené, přes listy. Bez Qt.

Uzel sítě = (list, prvek, port, žíla). Spojuje: vodič (obě strany, každá žíla), uzel odbočky (`sb.junction` – všechny
porty), průchozí svorka (port 1 ↔ 2 téže žíly), můstek svorkovnice (svorky stejné žíly… resp. stejného čísla),
PE lišta (všechny porty), přívod/vývod rozvaděče ↔ vodič nadřazeného JPS (vazba), blok ROZVADĚČ ↔ jeho přívody.
Výstup: seznam sítí s názvem potenciálu (žíla + zdroj) a kontrola zkratů (L–N, L–PE, DC+–DC−).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from envocad.model import multipole as mp
from envocad.model.project import (
    FEED_SYMBOLS,
    Element,
    Project,
    Sheet,
    Wire,
    WireEnd,
    element_symbol,
    linked_wire,
)

JUNCTION = "sb.junction"
BUS = "sb.busbar"
SOURCE_ORDER = ("fve.grid", "fve.pv_string", "fve.battery", "fve.inverter", "fve.inverter_hybrid")
LIVE = {"L1", "L2", "L3", "L", "DC+", "DC-", "DC−", "BAT+", "BAT-"}


@dataclass
class Net:
    id: int
    name: str = ""
    conductors: set[str] = field(default_factory=set)
    members: list[tuple[Sheet, Element, str, str]] = field(default_factory=list)   # list, prvek, port, žíla
    wires: list[tuple[Sheet, Wire, str]] = field(default_factory=list)              # list, vodič, žíla

    def short_issue(self) -> str:
        """Popis nepřípustného spojení potenciálů v jedné síti (prázdné = v pořádku)."""
        c = {x.replace("−", "-") for x in self.conductors}
        live = sorted(c & LIVE)
        if "PE" in c and (live or "N" in c):
            return f"PE spojeno s {', '.join(live or ['N'])}"
        if "N" in c and live:
            return f"N spojeno s {', '.join(live)}"
        if "DC+" in c and "DC-" in c:
            return "DC+ spojeno s DC−"
        phases = sorted(x for x in live if x in ("L1", "L2", "L3"))
        if len(phases) > 1:
            return "spojené fáze " + ", ".join(phases)
        return ""


class _UF:
    def __init__(self) -> None:
        self.p: dict[tuple, tuple] = {}

    def find(self, x: tuple) -> tuple:
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: tuple, b: tuple) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _slots(sheet: Sheet, e: Element) -> list[str]:
    return sorted({c for w in sheet.wires for end in (w.a, w.b) if end.element_id == e.id
                   for c in mp.wire_conductors(w)}, key=mp.canon_key)


def _first_port(project: Project, e: Element, lib) -> str:
    if lib is None:
        return "1"
    sym = element_symbol(project, e, lib)
    return sym.ports[0].name if sym.ports else "1"


def nets(project: Project, lib) -> list[Net]:
    uf = _UF()
    wire_nodes: list[tuple[Sheet, Wire, str, tuple]] = []
    for s in project.sheets:
        for w in s.wires:
            for c in mp.wire_conductors(w):
                a, b = (s.id, w.a.element_id, w.a.port, c), (s.id, w.b.element_id, w.b.port, c)
                uf.union(a, b)
                wire_nodes.append((s, w, c, a))
        # na jednom portu (svorce) jsou všechny žíly vodičů s disjunktními sadami fyzicky spojené – vodič „L1“ a vodič
        # „N“ na téže svorce je zkrat (podmnožina, např. L1 N PE + L1, je odbočka jedné žíly)
        # – platí jen pro jednopólové přístroje (atribut Póly = 1); port vícepólového přístroje nebo skupiny svorek je svazek
        single = {e.id for e in s.elements if str(e.attrs.get("poles", "")).strip() == "1"}
        at_port: dict[tuple[str, str], list[list[str]]] = {}
        for w in s.wires:
            for end in (w.a, w.b):
                if end.element_id in single:
                    at_port.setdefault((end.element_id, end.port), []).append(mp.wire_conductors(w))
        for (eid, port), sets in at_port.items():
            for i, a in enumerate(sets):
                for b in sets[i + 1:]:
                    if not set(a) & set(b):
                        uf.union((s.id, eid, port, a[0]), (s.id, eid, port, b[0]))
        for e in s.elements:
            sym = element_symbol(project, e, lib) if lib else None
            slots = _slots(s, e)
            if e.symbol_id in (JUNCTION, BUS, "sb.pe_bar"):
                ports = [p.name for p in (sym.ports if sym else [])] or ["N", "E", "S", "W"]
                for c in slots:
                    for p in ports[1:]:
                        uf.union((s.id, e.id, ports[0], c), (s.id, e.id, p, c))
            elif mp.is_terminal_block(e) and sym is not None and len(sym.ports) == 2:
                p1, p2 = sym.ports[0].name, sym.ports[1].name
                for c in slots:
                    uf.union((s.id, e.id, p1, c), (s.id, e.id, p2, c))
            elif e.symbol_id in FEED_SYMBOLS:
                hit = linked_wire(project, s, e)
                if hit is not None:
                    ps, pw = hit
                    port = sym.ports[0].name if sym and sym.ports else "1"
                    block = s.parent_element_id
                    for c in mp.wire_conductors(pw):
                        for end in (pw.a, pw.b):
                            if end.element_id == block:
                                uf.union((s.id, e.id, port, c), (ps.id, block, end.port, c))
        # můstky: svorky stejného čísla jsou jeden uzel (přes skupiny) – svorka = (ref, číslo) → (prvek, žíla)
        owner: dict[tuple[str, str], tuple[str, str]] = {}
        for e in s.elements:
            if mp.is_terminal_block(e) and e.ref:
                slots = _slots(s, e)
                for c, num in zip(slots, mp.terminal_numbers(e, len(slots))):
                    if num:
                        owner[(e.ref, num)] = (e.id, c)
        sym_port = {}
        for strip, groups in s.bridges.items():
            for g in groups:
                hits = [owner[(strip, n)] for n in g if (strip, n) in owner]
                for (eid, c) in hits[1:]:
                    e0, c0 = hits[0]
                    p0 = sym_port.setdefault(e0, _first_port(project, s.element(e0), lib))
                    p1 = sym_port.setdefault(eid, _first_port(project, s.element(eid), lib))
                    uf.union((s.id, e0, p0, c0), (s.id, eid, p1, c))
    groups: dict[tuple, Net] = {}
    sheets = {s.id: s for s in project.sheets}
    for key in list(uf.p):
        root = uf.find(key)
        net = groups.setdefault(root, Net(len(groups) + 1))
        sid, eid, port, c = key
        s = sheets[sid]
        try:
            e = s.element(eid)
        except KeyError:
            continue
        net.members.append((s, e, port, c))
        net.conductors.add(c)
    for s, w, c, node in wire_nodes:
        groups[uf.find(node)].wires.append((s, w, c))
    out = sorted(groups.values(), key=lambda n: n.id)
    for i, net in enumerate(out, start=1):
        net.id = i
        net.name = _net_name(net)
    return out


def _net_name(net: Net) -> str:
    conds = sorted(net.conductors, key=mp.canon_key)
    bus = next((e for _, e, _, _ in net.members if e.symbol_id == BUS), None)
    if bus is not None and len(conds) == 1:
        return f"{bus.ref}{conds[0]}"   # potenciál sběrnice: předpona + žíla (1L1)
    src = None
    for kind in SOURCE_ORDER:
        src = next((e for _, e, _, _ in net.members if e.symbol_id == kind and e.ref), None)
        if src:
            break
    base = "/".join(conds) if len(conds) <= 2 else conds[0]
    if src:
        return f"{base} {src.ref}"
    # bez zdroje v síti (za přístrojem): podle prvního označeného vodiče (kabelu), jinak podle svorky
    wref = next((w.attrs.get("ref") for _, w, _ in net.wires if w.attrs.get("ref")), "")
    if wref:
        return f"{base} ({wref})"
    feed = next((e for _, e, _, _ in net.members if e.symbol_id in FEED_SYMBOLS and e.ref), None)
    return f"{base} {feed.ref}" if feed else base


def net_of_wire(project: Project, lib, wire_id: str) -> dict[str, Net]:
    """{žíla: síť} pro vodič – pro vlastnosti vodiče (název potenciálu každé žíly)."""
    out = {}
    for n in nets(project, lib):
        for _, w, c in n.wires:
            if w.id == wire_id:
                out[c] = n
    return out


def split_wire(sheet: Sheet, w: Wire, x: float, y: float) -> tuple[Element, Wire, Wire]:
    """Rozdělí vodič v bodě (x, y) uzlem odbočky: vrátí (uzel, vodič a→uzel, vodič uzel→b). Nic nevkládá do listu.
    Oba díly nesou kabel a žíly původního vodiče; označení (W3) zůstává prvnímu dílu."""
    j = Element(symbol_id=JUNCTION, x=x, y=y, attrs={"ref": ""})
    a = sheet.element(w.a.element_id)
    b = sheet.element(w.b.element_id)

    def side(e: Element) -> str:
        dx, dy = e.x - x, e.y - y
        return ("E" if dx > 0 else "W") if abs(dx) >= abs(dy) else ("N" if dy > 0 else "S")
    pa, pb = side(a), side(b)
    if pb == pa:
        pb = next(p for p in ("N", "E", "S", "W") if p != pa)
    attrs2 = dict(w.attrs)
    attrs2["ref"] = ""
    w1 = Wire(WireEnd(w.a.element_id, w.a.port), WireEnd(j.id, pa), points=[], attrs=dict(w.attrs), conductors=list(w.conductors))
    w2 = Wire(WireEnd(j.id, pb), WireEnd(w.b.element_id, w.b.port), points=[], attrs=attrs2, conductors=list(w.conductors))
    return j, w1, w2


def junction_free_port(sheet: Sheet, j: Element, towards: tuple[float, float] | None = None) -> str:
    """Volný port uzlu (nejlépe směrem k cílovému bodu)."""
    used = {end.port for w in sheet.wires for end in (w.a, w.b) if end.element_id == j.id}
    order = ["N", "E", "S", "W"]
    if towards is not None:
        dx, dy = towards[0] - j.x, towards[1] - j.y
        pref = ("E" if dx > 0 else "W") if abs(dx) >= abs(dy) else ("N" if dy > 0 else "S")
        order.remove(pref)
        order.insert(0, pref)
    return next((p for p in order if p not in used), "")
