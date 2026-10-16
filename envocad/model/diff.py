"""Porovnání dvou verzí projektu (revize) → změnový list. Bez Qt.

Porovnává prvky a vodiče podle id (přežívají uložení), svorkovnice/můstky a kabely podle označení,
označení listů (`Sheet.func/loc`) a registr struktur projektu (`Project.structures`).
Výstup: seznam změn (list, prvek, druh změny, co se změnilo) pro změnový list, navigátor a značky revize
ve výkresu (`model/revision.py`): `Change.sheet_id` + `target_id` = kde, `x/y` = pevná poloha odebraných.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from itertools import pairwise

from envocad.model import multipole as mp
from envocad.model.project import Element, Project, Sheet, Wire

IGNORED_ATTRS = {"wire_id", "cable_id", "sheet"}   # odvozené/technické atributy
MOVE_DETAIL = "posun ve výkresu"                   # detail změny, která je jen posunem prvku (bez značky revize)


@dataclass
class Change:
    kind: str        # "přidáno" | "odebráno" | "změněno"
    sheet: str
    ref: str
    what: str        # prvek | vodič | kabel | můstky | skříň | list | struktura
    detail: str
    target_id: str = ""      # id prvku/vodiče v novém projektu ("" = změna listu, odebraná věc, kabel…)
    is_wire: bool = False
    sheet_id: str = ""       # id listu v novém projektu ("" = mimo list: kabel, struktura, odebraný list)
    x: float | None = None   # poloha odebraného prvku/vodiče (mm, souřadnice listu); jinak None
    y: float | None = None


def _attrs_diff(old: dict, new: dict) -> list[str]:
    out = []
    for k in sorted(set(old) | set(new)):
        if k in IGNORED_ATTRS:
            continue
        a, b = old.get(k, ""), new.get(k, "")
        if a != b:
            out.append(f"{k}: {a or '–'} → {b or '–'}")
    return out


def _midpoint(pts: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Bod v polovině délky lomené čáry (jeden bod → on sám, nic → None)."""
    if not pts:
        return None
    total = sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in pairwise(pts))
    if total <= 0:
        return (float(pts[0][0]), float(pts[0][1]))
    half = total / 2
    for a, b in pairwise(pts):
        seg = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        if seg >= half:
            t = half / seg if seg else 0.0
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        half -= seg
    return (float(pts[-1][0]), float(pts[-1][1]))


def _end_pos(project: Project, sheet: Sheet, end, lib) -> tuple[float, float] | None:
    try:
        e = sheet.element(end.element_id)
    except KeyError:
        return None
    if lib is not None:
        from envocad.model.project import element_symbol
        try:
            return e.port_pos(element_symbol(project, e, lib), end.port)
        except Exception:  # noqa: BLE001 – neznámá značka/port → aspoň vložný bod prvku
            return (e.x, e.y)
    return (e.x, e.y)


def removed_wire_pos(project: Project, sheet: Sheet, w: Wire, lib=None) -> tuple[float, float] | None:
    """Poloha značky odebraného vodiče: střed ručních lomů, jinak střed mezi konci (porty, bez `lib` vložné body
    prvků). `project`/`sheet` = stará verze, ve které vodič ještě je."""
    if w.points:
        return _midpoint([tuple(p) for p in w.points])
    a, b = _end_pos(project, sheet, w.a, lib), _end_pos(project, sheet, w.b, lib)
    if a and b:
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return a or b


def _strip_id(sheet: Sheet, strip: str) -> str:
    """id (první) skupiny svorek s označením `strip` na listu – kam patří značka změny můstků."""
    return next((e.id for e in sheet.elements if mp.is_terminal_block(e) and e.ref == strip), "")


def _designation_diff(o: Sheet, n: Sheet) -> list[str]:
    d = []
    if o.func != n.func:
        d.append(f"funkce: {'=' + o.func if o.func else '–'} → {'=' + n.func if n.func else '–'}")
    if o.loc != n.loc:
        d.append(f"umístění: {'+' + o.loc if o.loc else '–'} → {'+' + n.loc if n.loc else '–'}")
    return d


def _structures_diff(old: Project, new: Project) -> list[Change]:
    out = []
    oa = {(x.aspect, x.code): x for x in old.structures}
    na = {(x.aspect, x.code): x for x in new.structures}
    for key in sorted(set(oa) | set(na)):
        a, b = oa.get(key), na.get(key)
        code = key[0] + key[1]
        if a is None:
            out.append(Change("přidáno", "", code, "struktura", b.description or code))
        elif b is None:
            out.append(Change("odebráno", "", code, "struktura", a.description or code))
        elif a.description != b.description:
            out.append(Change("změněno", "", code, "struktura", f"popis: {a.description or '–'} → {b.description or '–'}"))
    return out


def diff_projects(old: Project, new: Project, lib=None) -> list[Change]:
    """Změny z `old` na `new`. `lib` (volitelná knihovna) zpřesní polohu odebraných vodičů na porty prvků."""
    changes: list[Change] = []
    old_sheets = {s.id: s for s in old.sheets}
    new_sheets = {s.id: s for s in new.sheets}
    for sid, s in new_sheets.items():
        if sid not in old_sheets:
            changes.append(Change("přidáno", s.name, "", "list", f"nový list {s.name}", sheet_id=sid))
    for sid, s in old_sheets.items():
        if sid not in new_sheets:
            changes.append(Change("odebráno", s.name, "", "list", f"list {s.name} odstraněn"))
    for sid, ns in new_sheets.items():
        os_ = old_sheets.get(sid)
        if os_ is None:
            for e in ns.elements:
                changes.append(Change("přidáno", ns.name, e.ref, "prvek", e.symbol_id, e.id, sheet_id=sid))
            continue
        d = [f"přejmenován {os_.name} → {ns.name}"] if os_.name != ns.name else []
        d += _designation_diff(os_, ns)
        if d:
            changes.append(Change("změněno", ns.name, "", "list", "; ".join(d), sheet_id=sid))
        oe = {e.id: e for e in os_.elements}
        ne = {e.id: e for e in ns.elements}
        for eid, e in ne.items():
            if eid not in oe:
                changes.append(Change("přidáno", ns.name, e.ref, "prvek", e.symbol_id, eid, sheet_id=sid))
                continue
            o = oe[eid]
            d = _attrs_diff(o.attrs, e.attrs)
            if o.symbol_id != e.symbol_id:
                d.append(f"značka: {o.symbol_id} → {e.symbol_id}")
            if (o.component_id or "") != (e.component_id or ""):
                d.append(f"artikl: {o.component_id or '–'} → {e.component_id or '–'}")
            if (o.x, o.y, o.rotation) != (e.x, e.y, e.rotation):
                d.append(MOVE_DETAIL)
            if d:
                changes.append(Change("změněno", ns.name, e.ref, "prvek", "; ".join(d), eid, sheet_id=sid))
        for eid, o in oe.items():
            if eid not in ne:
                changes.append(Change("odebráno", ns.name, o.ref, "prvek", o.symbol_id, sheet_id=sid, x=o.x, y=o.y))
        ow = {w.id: w for w in os_.wires}
        nw = {w.id: w for w in ns.wires}
        for wid, w in nw.items():
            if wid not in ow:
                changes.append(Change("přidáno", ns.name, w.attrs.get("ref", ""), "vodič",
                                      f"{w.attrs.get('cable', '')} {' '.join(w.conductors)}".strip(), wid, True, sheet_id=sid))
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
                changes.append(Change("změněno", ns.name, w.attrs.get("ref", ""), "vodič", "; ".join(d), wid, True,
                                      sheet_id=sid))
        for wid, o in ow.items():
            if wid not in nw:
                pos = removed_wire_pos(old, os_, o, lib) or (None, None)
                changes.append(Change("odebráno", ns.name, o.attrs.get("ref", ""), "vodič", o.attrs.get("cable", ""),
                                      is_wire=True, sheet_id=sid, x=pos[0], y=pos[1]))
        if os_.is_switchboard or ns.is_switchboard:
            op, np_ = os_.layout.params, ns.layout.params
            d = _attrs_diff(op, np_)
            if (os_.layout.rows, os_.layout.modules_per_row) != (ns.layout.rows, ns.layout.modules_per_row):
                d.append(f"řady/moduly: {os_.layout.rows}×{os_.layout.modules_per_row} → {ns.layout.rows}×{ns.layout.modules_per_row}")
            if d:
                changes.append(Change("změněno", ns.name, "", "skříň", "; ".join(d), sheet_id=sid))
    for sid, ns in new_sheets.items():
        os_ = old_sheets.get(sid)
        for strip in sorted(set(os_.bridges if os_ else {}) | set(ns.bridges)):
            a = old.bridge_groups(strip, os_) if os_ else []
            b = new.bridge_groups(strip, ns)
            if a != b:
                kind = "přidáno" if not a else ("odebráno" if not b else "změněno")
                changes.append(Change(kind, ns.name, strip, "můstky",
                                      f"{', '.join('-'.join(g) for g in a) or '–'} → {', '.join('-'.join(g) for g in b) or '–'}",
                                      _strip_id(ns, strip), sheet_id=sid))
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
    changes += _structures_diff(old, new)
    return changes


def _canon_element(e: Element) -> dict:
    return {"id": e.id, "symbol_id": e.symbol_id, "component_id": e.component_id or "",
            "attrs": {k: v for k, v in sorted(e.attrs.items()) if k not in IGNORED_ATTRS and v not in ("", None)}}


def _canon_wire(w: Wire) -> dict:
    return {"id": w.id, "attrs": {k: v for k, v in sorted(w.attrs.items()) if k not in IGNORED_ATTRS and v not in ("", None)},
            "conductors": list(w.conductors), "terminals": w.terminals,
            "ends": [w.a.element_id, w.a.port, w.b.element_id, w.b.port]}


def sheet_fingerprint(sheet: Sheet) -> str:
    """Otisk listu (sha1 kanonického JSON) ze stejných údajů, jaké porovnává `diff_projects` (název, označení listu,
    prvky, vodiče, můstky, skříň). Stejný otisk ⇔ porovnání listu nenajde změnu se značkou (kabely a struktury
    jsou projektové, do otisku listu nepatří). Pořadí prvků/vodičů v seznamu otisk nemění. Poloha prvků (x, y, rotace) ani ruční
    lomy vodičů v otisku nejsou – pouhý posun nedostane značku revize (`revision.MARK_MOVES = False`), takže by
    po uzavření vyvolal varování `rev_closed_changed`, které další porovnání nemůže odstranit."""
    data = {
        "name": sheet.name, "func": sheet.func, "loc": sheet.loc,
        "elements": sorted((_canon_element(e) for e in sheet.elements), key=lambda x: x["id"]),
        "wires": sorted((_canon_wire(w) for w in sheet.wires), key=lambda x: x["id"]),
        "bridges": {k: v for k, v in sorted(sheet.bridges.items()) if v},
    }
    if sheet.is_switchboard:
        data["layout"] = {"params": {k: v for k, v in sorted(sheet.layout.params.items()) if v not in ("", None)},
                          "rows": sheet.layout.rows, "modules_per_row": sheet.layout.modules_per_row}
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


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
