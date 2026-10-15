"""Porovnání dvou verzí projektu (revize) → změnový list. Bez Qt.

Porovnává prvky a vodiče podle id (přežívají uložení), svorkovnice/můstky a kabely podle označení.
Výstup: seznam změn (list, prvek, druh změny, co se změnilo) pro změnový list a navigátor.
"""
from __future__ import annotations

from dataclasses import dataclass

from envocad.model.project import Project

IGNORED_ATTRS = {"wire_id", "cable_id", "sheet"}   # odvozené/technické atributy


@dataclass
class Change:
    kind: str        # "přidáno" | "odebráno" | "změněno"
    sheet: str
    ref: str
    what: str        # prvek | vodič | kabel | můstky | skříň | list
    detail: str
    target_id: str = ""
    is_wire: bool = False


def _attrs_diff(old: dict, new: dict) -> list[str]:
    out = []
    for k in sorted(set(old) | set(new)):
        if k in IGNORED_ATTRS:
            continue
        a, b = old.get(k, ""), new.get(k, "")
        if a != b:
            out.append(f"{k}: {a or '–'} → {b or '–'}")
    return out


def diff_projects(old: Project, new: Project) -> list[Change]:
    changes: list[Change] = []
    old_sheets = {s.id: s for s in old.sheets}
    new_sheets = {s.id: s for s in new.sheets}
    for sid, s in new_sheets.items():
        if sid not in old_sheets:
            changes.append(Change("přidáno", s.name, "", "list", f"nový list {s.name}"))
    for sid, s in old_sheets.items():
        if sid not in new_sheets:
            changes.append(Change("odebráno", s.name, "", "list", f"list {s.name} odstraněn"))
    for sid, ns in new_sheets.items():
        os_ = old_sheets.get(sid)
        if os_ is None:
            for e in ns.elements:
                changes.append(Change("přidáno", ns.name, e.ref, "prvek", e.symbol_id, e.id))
            continue
        if os_.name != ns.name:
            changes.append(Change("změněno", ns.name, "", "list", f"přejmenován {os_.name} → {ns.name}"))
        oe = {e.id: e for e in os_.elements}
        ne = {e.id: e for e in ns.elements}
        for eid, e in ne.items():
            if eid not in oe:
                changes.append(Change("přidáno", ns.name, e.ref, "prvek", e.symbol_id, eid))
                continue
            o = oe[eid]
            d = _attrs_diff(o.attrs, e.attrs)
            if o.symbol_id != e.symbol_id:
                d.append(f"značka: {o.symbol_id} → {e.symbol_id}")
            if (o.component_id or "") != (e.component_id or ""):
                d.append(f"artikl: {o.component_id or '–'} → {e.component_id or '–'}")
            if (o.x, o.y, o.rotation) != (e.x, e.y, e.rotation):
                d.append("posun ve výkresu")
            if d:
                changes.append(Change("změněno", ns.name, e.ref, "prvek", "; ".join(d), eid))
        for eid, o in oe.items():
            if eid not in ne:
                changes.append(Change("odebráno", ns.name, o.ref, "prvek", o.symbol_id))
        ow = {w.id: w for w in os_.wires}
        nw = {w.id: w for w in ns.wires}
        for wid, w in nw.items():
            if wid not in ow:
                changes.append(Change("přidáno", ns.name, w.attrs.get("ref", ""), "vodič",
                                      f"{w.attrs.get('cable', '')} {' '.join(w.conductors)}".strip(), wid, True))
                continue
            o = ow[wid]
            d = _attrs_diff(o.attrs, w.attrs)
            if o.conductors != w.conductors:
                d.append(f"žíly: {' '.join(o.conductors) or '–'} → {' '.join(w.conductors) or '–'}")
            if o.terminals != w.terminals:
                d.append("svorky žil")
            if (o.a.element_id, o.a.port, o.b.element_id, o.b.port) != (w.a.element_id, w.a.port, w.b.element_id, w.b.port):
                d.append("přepojen")
            if d:
                changes.append(Change("změněno", ns.name, w.attrs.get("ref", ""), "vodič", "; ".join(d), wid, True))
        for wid, o in ow.items():
            if wid not in nw:
                changes.append(Change("odebráno", ns.name, o.attrs.get("ref", ""), "vodič", o.attrs.get("cable", "")))
        if os_.is_switchboard or ns.is_switchboard:
            op, np_ = os_.layout.params, ns.layout.params
            d = _attrs_diff(op, np_)
            if (os_.layout.rows, os_.layout.modules_per_row) != (ns.layout.rows, ns.layout.modules_per_row):
                d.append(f"řady/moduly: {os_.layout.rows}×{os_.layout.modules_per_row} → {ns.layout.rows}×{ns.layout.modules_per_row}")
            if d:
                changes.append(Change("změněno", ns.name, "", "skříň", "; ".join(d)))
    for strip in sorted(set(old.bridges) | set(new.bridges)):
        a, b = old.bridge_groups(strip), new.bridge_groups(strip)
        if a != b:
            kind = "přidáno" if not a else ("odebráno" if not b else "změněno")
            changes.append(Change(kind, "", strip, "můstky",
                                  f"{', '.join('-'.join(g) for g in a) or '–'} → {', '.join('-'.join(g) for g in b) or '–'}"))
    oc = {c.ref: c for c in old.cables}
    nc = {c.ref: c for c in new.cables}
    for ref in sorted(set(oc) | set(nc)):
        a, b = oc.get(ref), nc.get(ref)
        if a is None:
            changes.append(Change("přidáno", "", ref, "kabel", f"{b.type} {b.cross}".strip()))
        elif b is None:
            changes.append(Change("odebráno", "", ref, "kabel", f"{a.type} {a.cross}".strip()))
        else:
            da = {k: v for k, v in a.to_dict().items() if k not in ("id", "component_id")}
            db = {k: v for k, v in b.to_dict().items() if k not in ("id", "component_id")}
            if da != db:
                d = [f"{k}: {da[k]} → {db[k]}" for k in da if da[k] != db.get(k) and k != "cores"]
                if da.get("cores") != db.get("cores"):
                    d.append("žíly/barvy")
                changes.append(Change("změněno", "", ref, "kabel", "; ".join(d)))
    return changes


def change_list_text(changes: list[Change], revision: str, date: str, author: str) -> str:
    """Řádky pro `meta['changes']` (revize | datum | popis | zpracoval) – jeden řádek na změnu."""
    lines = []
    for c in changes:
        where = f"{c.sheet}: " if c.sheet else ""
        lines.append(f"{revision} | {date} | {where}{c.what} {c.ref} {c.kind} – {c.detail}".rstrip(" –") + f" | {author}")
    return "\n".join(lines)


def summary(changes: list[Change]) -> str:
    from collections import Counter
    c = Counter(ch.kind for ch in changes)
    return f"{c.get('přidáno', 0)} přidáno, {c.get('změněno', 0)} změněno, {c.get('odebráno', 0)} odebráno"
