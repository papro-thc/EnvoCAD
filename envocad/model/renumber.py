"""Přečíslování označení přístrojů a vodičů (jako „Číslování přístrojů“ v EPLAN).

Prvky se číslují podle pořadí listů a v listu po sloupcích (zleva doprava, shora dolů), v každém prostoru označení
(`designation.scope_key`) zvlášť – X1 v +RDC1 i v +RH je v pořádku. Jednotka číslování je přístroj
(`xref.DeviceGroup`): cívka, stykač i kontakty stejného označení dostanou nové číslo společně. Vodiče (`W`) se
číslují stejně podle středu mezi konci; kabel navázaný jen označením (bez `cable_id`) se přejmenuje s vodičem.

Nečíslují se: svorkovnice a přívody/vývody (vlastní číslování svorek), přerušovací body (protějšky se párují
označením), bloky ROZVADĚČ (označení = umístění listu), prvky bez písmenného kódu ve značce a ručně psaná firemní
označení, která nejsou tvaru písmena + číslo („Q1.2“, „SPD-DC1“) – ta zůstanou a jejich čísla se nepoužijí.

Výsledek je seznam `project.TextChange` (kind "element" / "wire" / "cable") pro `apply_text_changes` – v GUI
jeden krok undo. Model se tu nemění."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from envocad.model.designation import letter_code, scope_key
from envocad.model.multipole import TERMINAL_SYMBOLS, is_terminal_block
from envocad.model.project import (
    INTERRUPT_SYMBOL,
    Element,
    Project,
    Sheet,
    TextChange,
    Wire,
    is_contact,
)

ALL = "all"          # přečíslovat vše (číselná označení tvaru písmena + číslo a prázdná)
FIX = "fix"          # jen prázdná a duplicitní označení – ostatní zůstanou
MODES = {ALL: "Přečíslovat vše podle polohy", FIX: "Jen doplnit chybějící a opravit duplicitní"}

SKIP_SYMBOLS = TERMINAL_SYMBOLS | {INTERRUPT_SYMBOL, "fve.switchboard", "fve.earth", "fve.grid", "fve.load",
                                   "sb.junction", "sb.busbar"}
PLAIN_REF = re.compile(r"([A-Za-z]+)(\d+)")
COLUMN_MM = 5.0      # prvky s rozdílem x do 5 mm leží v jednom sloupci (čte se shora dolů)


@dataclass
class _Unit:
    """Co dostane jedno číslo: prvky přístroje (s kontakty), nebo vodič."""
    scope: tuple[str, str]
    prefix: str
    ref: str
    order: tuple
    elements: list[Element] = field(default_factory=list)
    wire: Wire | None = None
    primary: bool = True       # při duplicitě si označení nechá primární jednotka (přístroj s kontakty)


def _number(ref: str) -> int | None:
    m = PLAIN_REF.fullmatch(ref or "")
    return int(m.group(2)) if m else None


def _pos_key(sheet_no: int, x: float, y: float) -> tuple:
    return (sheet_no, round(x / COLUMN_MM), -y)


def _prefix_of(lib, e: Element) -> str:
    if e.ref:
        return letter_code(e.ref)
    try:
        return lib.get_symbol(e.symbol_id).iec_ref or ""
    except Exception:  # noqa: BLE001 – neznámá značka: bez písmenného kódu se nečísluje
        return ""


def _device_units(project: Project, lib, sheet_no: dict[str, int]) -> list[_Unit]:
    """Přístroje projektu jako jednotky číslování. Skupina s duplicitním označením (`DeviceGroup.dup`) se rozdělí:
    hlavní přístroj (cívka + stykač, jinak první podle polohy) si nechá kontakty, ostatní jsou samostatné."""
    from envocad.model.project import COIL_SYMBOLS, DUAL_ROLE
    from envocad.model.xref import DeviceIndex
    idx = DeviceIndex.build(project)
    units: list[_Unit] = []
    seen: set[str] = set()

    def key(placed) -> tuple:
        s, e = placed
        return _pos_key(sheet_no[s.id], e.x, e.y)

    for g in idx.groups.values():
        members = sorted(g.members, key=key)
        if g.dup:
            coils = [m for m in members if m[1].symbol_id in COIL_SYMBOLS]
            duals = [m for m in members if m[1].symbol_id in DUAL_ROLE]
            main = [coils[0], *duals[:1]] if coils else [members[0]]
        else:
            main = members
        rest = [m for m in members if all(m[1] is not k[1] for k in main)]
        head = min(main, key=key)
        els = [e for _, e in main] + [e for _, e in g.contacts]
        units.append(_Unit(g.scope, letter_code(g.ref), g.ref, key(head), els))
        for s, e in rest:
            units.append(_Unit(g.scope, letter_code(e.ref), e.ref, key((s, e)), [e], primary=False))
        seen.update(e.id for e in els)
        seen.update(e.id for _, e in rest)
    for s in project.sheets:
        for e in s.elements:
            if e.ref or e.id in seen or is_contact(e):
                continue
            prefix = _prefix_of(lib, e)
            if prefix:
                units.append(_Unit(scope_key(s, e), prefix, "", _pos_key(sheet_no[s.id], e.x, e.y), [e]))
    return [u for u in units if not any(_skipped(e) for e in u.elements)]


def _skipped(e: Element) -> bool:
    return e.symbol_id in SKIP_SYMBOLS or is_terminal_block(e)


def _wire_units(project: Project, sheet_no: dict[str, int]) -> list[_Unit]:
    out = []
    for s in project.sheets:
        els = {e.id: e for e in s.elements}
        for w in s.wires:
            a, b = els.get(w.a.element_id), els.get(w.b.element_id)
            if a is None or b is None:
                continue
            ref = w.attrs.get("ref", "")
            out.append(_Unit(scope_key(s, w), letter_code(ref) if ref else "W", ref,
                             _pos_key(sheet_no[s.id], (a.x + b.x) / 2, (a.y + b.y) / 2), wire=w))
    return out


def plan(project: Project, lib, mode: str = FIX, sheets: Iterable[Sheet] | None = None,
         wires: bool = True, devices: bool = True) -> list[TextChange]:
    """Změny označení pro `mode` (ALL / FIX) na listech `sheets` (None = celý projekt). Označení mimo zvolené listy
    a nečíslovaná (firemní) označení se nemění a jejich čísla zůstanou obsazená."""
    if mode not in MODES:
        raise ValueError(f"neznámý režim přečíslování: {mode}")
    sheet_no = {s.id: i for i, s in enumerate(project.sheets)}
    chosen = {s.id for s in (sheets if sheets is not None else project.sheets)}
    units = (_device_units(project, lib, sheet_no) if devices else []) + (_wire_units(project, sheet_no) if wires else [])
    units.sort(key=lambda u: u.order)
    home = {id(x): s.id for s in project.sheets for x in (*s.elements, *s.wires)}
    in_scope = [u for u in units if home[id(u.wire if u.wire is not None else u.elements[0])] in chosen]
    movable_ids = {id(u) for u in in_scope if not u.ref or (mode == ALL and _number(u.ref) is not None)}
    if mode == FIX:                       # duplicita: první podle polohy si číslo nechá, další dostanou nové
        taken: set[tuple] = {(u.scope, u.ref) for u in units if u.ref and id(u) not in {id(x) for x in in_scope}}
        for u in sorted(in_scope, key=lambda u: (not u.primary, u.order)):
            if not u.ref:
                continue
            k = (u.scope, u.ref)
            if k in taken:
                movable_ids.add(id(u))
            else:
                taken.add(k)
    # obsazené: všechna označení, která zůstávají (v prostoru podle prefixu)
    used: dict[tuple, set[int]] = {}
    fixed_refs: set[tuple] = set()
    for u in units:
        if id(u) in movable_ids or not u.ref:
            continue
        fixed_refs.add((u.scope, u.ref))
        n = _number(u.ref)
        if n is not None:
            used.setdefault((u.scope, letter_code(u.ref)), set()).add(n)
    out: list[TextChange] = []
    for u in in_scope:
        if id(u) not in movable_ids or not u.prefix:
            continue
        nums = used.setdefault((u.scope, u.prefix), set())
        n = 1
        while n in nums or (u.scope, f"{u.prefix}{n}") in fixed_refs:
            n += 1
        nums.add(n)
        new = f"{u.prefix}{n}"
        if new == u.ref:
            continue
        if u.wire is not None:
            out.append(TextChange("wire", u.wire.id, "ref", u.wire.attrs.get("ref", ""), new))
            cable = project.cable_of_wire(u.wire) if u.ref and not u.wire.attrs.get("cable_id") else None
            if cable is not None and cable.ref == u.ref:
                # kabel navázaný jen označením: jediný vodič → přejmenovat i kabel, jinak vazbu zachovat přes cable_id
                users = [w for s in project.sheets for w in s.wires
                         if w.attrs.get("cable_id") == cable.id or (not w.attrs.get("cable_id")
                                                                     and w.attrs.get("ref") == cable.ref)]
                if len(users) == 1:
                    out.append(TextChange("cable", cable.id, "ref", cable.ref, new))
                else:
                    out.append(TextChange("wire", u.wire.id, "cable_id", None, cable.id))
        else:
            for e in u.elements:
                out.append(TextChange("element", e.id, "ref", e.ref, new))
    return out


def summary(changes: list[TextChange]) -> str:
    """„12 přístrojů, 5 vodičů“ pro náhled v dialogu."""
    from envocad.model.notes import plural
    els = sum(1 for c in changes if c.kind == "element")
    wires = sum(1 for c in changes if c.kind == "wire" and c.key == "ref")
    return f"{els} {plural(els, 'prvek', 'prvky', 'prvků')}, {wires} {plural(wires, 'vodič', 'vodiče', 'vodičů')}"
