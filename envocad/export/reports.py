"""Výkazy odvozené z modelu (čistá data, bez Qt a bez formátů souborů).

Každá funkce vrací (hlavička, řádky) – stejné tabulky použije xlsx, docx i GUI.
"""
from __future__ import annotations

from collections import OrderedDict

from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Sheet

# Symboly, které nejsou přístroje k objednání (propojení, odkazy, vnější prvky)
NON_DEVICE_SYMBOLS = {"fve.terminal", "fve.earth", "fve.grid", "fve.load", "fve.switchboard", "sb.feed_in", "sb.feed_out"}
TERMINAL_SYMBOLS = {"sb.feed_in", "sb.feed_out", "sb.terminal_block"}

DEVICE_PARAMS = ["in_", "char", "poles", "idn", "spd_type", "uc", "icu", "ir", "p_ac", "e_kwh", "sn"]


def _sheets(project: Project, sheet: Sheet | None) -> list[Sheet]:
    return [sheet] if sheet else list(project.sheets)


def _param_str(e: Element) -> str:
    parts = []
    for k in DEVICE_PARAMS:
        v = e.attrs.get(k)
        if v:
            unit = {"in_": " A", "idn": " mA", "uc": " V", "icu": " kA", "ir": " A", "p_ac": " kW", "e_kwh": " kWh",
                    "sn": " kVA", "poles": "p"}.get(k, "")
            parts.append(f"{v}{unit}")
    return ", ".join(parts)


def devices(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> list[Element]:
    return [e for s in _sheets(project, sheet) for e in s.elements if e.symbol_id not in NON_DEVICE_SYMBOLS]


def device_list(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Seznam přístrojů (každý zvlášť) – pro štítky a kontrolu."""
    head = ["Označení", "Přístroj", "Typ", "Výrobce", "Parametry", "Moduly", "Řada", "Pozice", "List"]
    rows = []
    for s in _sheets(project, sheet):
        for e in s.elements:
            if e.symbol_id in NON_DEVICE_SYMBOLS:
                continue
            sym = lib.get_symbol(e.symbol_id)
            pl = s.layout.placement(e.id) if s.is_switchboard else None
            rows.append([e.ref, sym.name, e.attrs.get("type", ""), e.attrs.get("manufacturer", ""), _param_str(e),
                         e.modules or "", (pl.row + 1) if pl else "", pl.pos if pl else "", s.name])
    rows.sort(key=lambda r: (r[8], _ref_key(r[0])))
    return head, rows


def bom(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Výkaz materiálu – sloučeno podle přístroje/typu/výrobce/parametrů."""
    head = ["Pol.", "Přístroj", "Typ", "Výrobce", "Parametry", "Ks", "Označení"]
    groups: OrderedDict[tuple, list[str]] = OrderedDict()
    for s in _sheets(project, sheet):
        for e in s.elements:
            if e.symbol_id in NON_DEVICE_SYMBOLS:
                continue
            key = (lib.get_symbol(e.symbol_id).name, e.attrs.get("type", ""), e.attrs.get("manufacturer", ""), _param_str(e))
            groups.setdefault(key, []).append(e.ref)
    rows = []
    for i, (key, refs) in enumerate(sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][3])), start=1):
        rows.append([i, key[0], key[1], key[2], key[3], len(refs), ", ".join(sorted(refs, key=_ref_key))])
    return head, rows


def cables(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Seznam kabelů / vodičů s označením nebo typem kabelu."""
    from envocad.model.project import wire_xref
    head = ["Označení", "Odkud", "Kam", "Typ kabelu", "Průřez [mm²]", "Žíly", "Délka [m]", "Trasa", "Rozvaděč", "List"]
    rows = []
    for s in _sheets(project, sheet):
        for w in s.wires:
            if not (w.attrs.get("ref") or w.attrs.get("cable")):
                continue
            a, b = s.element(w.a.element_id), s.element(w.b.element_id)
            rows.append([w.attrs.get("ref", ""), f"{a.ref or a.symbol_id}:{w.a.port}", f"{b.ref or b.symbol_id}:{w.b.port}",
                         w.attrs.get("cable", ""), w.attrs.get("cross", ""), " ".join(w.conductors) or w.attrs.get("poles", ""),
                         w.attrs.get("length", ""), w.attrs.get("route", ""), wire_xref(project, w.id).lstrip("→ "), s.name])
    rows.sort(key=lambda r: (r[9], _ref_key(r[0])))
    return head, rows


def terminals(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Svorkovnice: každá žíla každého vodiče napojeného na svorku/přívod/vývod + ruční přiřazení z Wire.terminals."""
    from envocad.model.multipole import wire_end_terminal
    head = ["Svorkovnice", "Svorka", "Žíla", "Kabel", "Připojeno na", "Můstek", "Popis", "List"]
    rows = []
    for s in _sheets(project, sheet):
        for w in s.wires:
            a, b = s.element(w.a.element_id), s.element(w.b.element_id)
            for side, end, other, other_port in (("a", a, b, w.b.port), ("b", b, a, w.a.port)):
                if end.symbol_id not in TERMINAL_SYMBOLS:
                    continue
                conds = w.conductors or [""]
                for i, c in enumerate(conds, start=1):
                    desig = wire_end_terminal(s, w, c, side) if c else ""
                    strip, _, num = desig.partition(":")
                    term = num or end.attrs.get("terminal") or (str(i) if c else "")
                    bridge = project.bridge_of(strip or end.ref, term)
                    rows.append([end.ref, term, c, w.attrs.get("ref") or w.attrs.get("cable", ""),
                                 f"{other.ref or other.symbol_id}:{other_port}",
                                 "-".join(bridge) if bridge else "", end.attrs.get("desc", ""), s.name])
    rows.sort(key=lambda r: (r[7], _ref_key(r[0]), _ref_key(str(r[1]))))
    return head, rows


def labels(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Štítky přístrojů a vývodů pro štítkovač: označení + stručný popis."""
    head = ["Štítek", "Popis", "List"]
    rows = []
    for s in _sheets(project, sheet):
        for e in s.elements:
            if not e.ref:
                continue
            sym = lib.get_symbol(e.symbol_id)
            desc = e.attrs.get("desc") or " ".join(x for x in (sym.name, e.attrs.get("in_", "") and e.attrs["in_"] + " A") if x)
            rows.append([e.ref, desc, s.name])
    rows.sort(key=lambda r: (r[2], _ref_key(r[0])))
    return head, rows


def _ref_key(ref: str) -> tuple:
    """Přirozené řazení F1, F2, F10."""
    import re
    m = re.match(r"([A-Za-z]*)(\d*)", ref or "")
    return (m.group(1), int(m.group(2) or 0)) if m else (ref, 0)


ALL_REPORTS = [("Přístroje", device_list), ("Výkaz materiálu", bom), ("Kabely", cables),
               ("Svorkovnice", terminals), ("Štítky", labels)]
