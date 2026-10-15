"""Výkazy odvozené z modelu (čistá data, bez Qt a bez formátů souborů).

Každá funkce vrací (hlavička, řádky) – stejné tabulky použije xlsx, docx i GUI.
"""
from __future__ import annotations

from collections import OrderedDict

from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Sheet

# Symboly, které nejsou přístroje k objednání (propojení, odkazy, vnější prvky)
NON_DEVICE_SYMBOLS = {"fve.terminal", "fve.earth", "fve.grid", "fve.load", "fve.switchboard", "sb.feed_in", "sb.feed_out",
                      "fve.interrupt", "ctl.contact_no", "ctl.contact_nc", "ctl.contact_power"}
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
    from envocad.model.project import contact_terminals, contacts_of
    head = ["Označení", "Přístroj", "Typ", "Výrobce", "Parametry", "Kontakty", "Moduly", "Řada", "Pozice", "List"]
    rows = []
    for s in _sheets(project, sheet):
        for e in s.elements:
            if e.symbol_id in NON_DEVICE_SYMBOLS:
                continue
            sym = lib.get_symbol(e.symbol_id)
            pl = s.layout.placement(e.id) if s.is_switchboard else None
            conts = ", ".join(sorted(contact_terminals(c) for _, c in contacts_of(project, e.ref))) if e.ref else ""
            rows.append([e.ref, sym.name, e.attrs.get("type", ""), e.attrs.get("manufacturer", ""), _param_str(e),
                         conts, e.modules or "", (pl.row + 1) if pl else "", pl.pos if pl else "", s.name])
    rows.sort(key=lambda r: (r[9], _ref_key(r[0])))
    return head, rows


def bom(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Výkaz materiálu – sloučeno podle přístroje/typu/výrobce/parametrů."""
    head = ["Pol.", "Přístroj", "Typ", "Výrobce", "Parametry", "Ks", "Označení"]
    groups: OrderedDict[tuple, list[str]] = OrderedDict()
    from envocad.model.multipole import is_terminal_block, terminal_numbers, wire_conductors
    qty: dict[tuple, int] = {}
    for s in _sheets(project, sheet):
        for e in s.elements:
            if e.symbol_id in NON_DEVICE_SYMBOLS and not is_terminal_block(e):
                continue
            if is_terminal_block(e):
                # skupina svorek (i přívod/vývod) = tolik kusů svorky, kolik má žil; parametr = průřez/druh z artiklu
                n = len({c for w in s.wires for end in (w.a, w.b) if end.element_id == e.id for c in wire_conductors(w)})
                n = n or len([x for x in terminal_numbers(e, 1) if x]) or 1
                params = ", ".join(x for x in (e.attrs.get("cross", "") and f"{e.attrs['cross']} mm²",
                                               e.attrs.get("kind", "")) if x)
                key = ("Řadová svorka", e.attrs.get("type", ""), e.attrs.get("manufacturer", ""), params)
                groups.setdefault(key, []).append(f"{e.ref} ({n})")
                qty[key] = qty.get(key, 0) + n
                continue
            if e.symbol_id == "fve.pv_string":
                # string = moduly (ks) + optimizéry (ks), ne jeden kus
                for akey, name, cnt_key in (("type", "FV modul", "n_modules"), ("optimizer", "Optimizér", "n_optimizers")):
                    try:
                        n = int(float(str(e.attrs.get(cnt_key) or 0).replace(",", ".")))
                    except ValueError:
                        n = 0
                    if n <= 0:
                        continue
                    params = f"{e.attrs['p_module']} Wp" if akey == "type" and e.attrs.get("p_module") else ""
                    key = (name, e.attrs.get(akey, ""), "", params)
                    groups.setdefault(key, []).append(f"{e.ref} ({n})")
                    qty[key] = qty.get(key, 0) + n
                continue
            key = (lib.get_symbol(e.symbol_id).name, e.attrs.get("type", ""), e.attrs.get("manufacturer", ""), _param_str(e))
            groups.setdefault(key, []).append(e.ref)
            qty[key] = qty.get(key, 0) + 1
        # můstky: za každou skupinu můstků jeden (vícepólový) můstek dané svorkovnice
        if s.is_switchboard or sheet is not None:
            strips = {e.ref for e in s.elements if is_terminal_block(e) and e.ref}
            for strip in sorted(strips):
                for g in project.bridge_groups(strip, s):
                    key = ("Můstek svorek", "", "", f"{len(g)} pólů")
                    groups.setdefault(key, []).append(f"{strip}:{'-'.join(g)}")
                    qty[key] = qty.get(key, 0) + 1
    rows = []
    for i, (key, refs) in enumerate(sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][3])), start=1):
        rows.append([i, key[0], key[1], key[2], key[3], qty[key], ", ".join(sorted(refs, key=_ref_key))])
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
                    bridge = project.bridge_of(strip or end.ref, term, s)
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


def terminal_plan_report(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Plán svorkovnice: vnější strana | svorka | můstek | vnitřní strana (jako v EPLAN)."""
    from envocad.model.terminal_plan import terminal_plan
    head = ["Svorkovnice", "Svorka", "Žíla", "Vnější připojení", "Vnější kabel", "Můstek", "Vnitřní připojení",
            "Vnitřní kabel", "List"]
    rows = []
    for s in _sheets(project, sheet):
        for plan in terminal_plan(project, s):
            for r in plan.rows:
                rows.append([r.strip, r.number, r.conductor, r.external, r.ext_cable, r.bridge, r.internal, r.int_cable,
                             s.name])
    return head, rows


def _end_text(project: Project, s: Sheet, w, side: str, conductor: str) -> str:
    """Konec žíly: svorka (X1:3), jinak prvek:port; u bloku rozvaděče cíl uvnitř rozvaděče."""
    from envocad.model.multipole import wire_end_terminal
    t = wire_end_terminal(s, w, conductor, side)
    if t:
        return t
    end = w.a if side == "a" else w.b
    e = s.element(end.element_id)
    return f"{e.ref or e.symbol_id}:{end.port}"


def cable_plan(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Kabelový plán: každá žíla každého kabelu – číslo, barva, odkud, kam (jako v EPLAN)."""
    from envocad.model.project import CORE_COLORS, sync_cables
    sync_cables(project)
    head = ["Kabel", "Typ", "Průřez [mm²]", "Žíla", "Č.", "Barva", "Odkud", "Kam", "Stínění", "Délka [m]", "List"]
    rows = []
    for s in _sheets(project, sheet):
        if s.is_switchboard:
            continue
        for w in s.wires:
            c = project.cable_of_wire(w)
            if c is None:
                continue
            for i, name in enumerate(w.conductors or ["L1"], start=1):
                core = c.core(name)
                rows.append([c.ref, c.type, c.cross, name, core.number if core else str(i),
                             core.color if core else CORE_COLORS.get(name, ""),
                             _end_text(project, s, w, "a", name), _end_text(project, s, w, "b", name),
                             "ano" if c.shield else "", c.length, s.name])
    rows.sort(key=lambda r: (r[10], _ref_key(r[0]), int(r[4]) if str(r[4]).isdigit() else 99))
    return head, rows


def wiring_list(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Zapojovací seznam: každé propojení po žílách – odkud, kam, kabel/vodič, barva, průřez (pro zapojování)."""
    from envocad.model.project import CORE_COLORS, sync_cables
    sync_cables(project)
    head = ["List", "Kabel / vodič", "Žíla", "Barva", "Průřez [mm²]", "Odkud", "Kam", "Poznámka"]
    rows = []
    for s in _sheets(project, sheet):
        for w in s.wires:
            c = project.cable_of_wire(w) if not s.is_switchboard else None
            label = c.ref if c else (w.attrs.get("ref") or "vodič")
            cross = (c.cross if c else "") or w.attrs.get("cross", "")
            for name in (w.conductors or ["L1"]):
                core = c.core(name) if c else None
                color = core.color if core and core.color else CORE_COLORS.get(name, "")
                rows.append([s.name, label, name, color, cross, _end_text(project, s, w, "a", name),
                             _end_text(project, s, w, "b", name), c.type if c else w.attrs.get("cable", "")])
    rows.sort(key=lambda r: (r[0], _ref_key(r[1])))
    return head, rows


def calculations(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Výkaz výpočtů: stringy vs. střídač, kabely (I, Iz, In, ΔU), selektivita."""
    from envocad.model import calc
    head = ["Část", "Prvek", "Hodnoty", "Mez / porovnání", "Výsledek"]
    rows = []
    for sc in calc.check_strings(project):
        vals = f"{sc.n} modulů, Uoc({calc.T_MIN_DEFAULT:g} °C) = {sc.uoc_cold} V, Umpp({calc.T_MAX_DEFAULT:g} °C) = {sc.umpp_hot} V, 1,25·Isc = {calc.SAFETY_ISC * sc.isc:.1f} A"
        lim = f"{sc.inverter}: Umax {sc.u_dc_max or '–'} V, MPPT {sc.u_mppt_min or '–'}–{sc.u_mppt_max or '–'} V, Imax {sc.i_mppt_max or '–'} A"
        rows.append(["String", sc.ref, vals, lim, "OK" if sc.ok else "; ".join(sc.issues)])
    for cc in calc.check_cables(project):
        if sheet is not None and cc.sheet != sheet.name:
            continue
        vals = f"I = {cc.i_a or '–'} A, S = {cc.cross or '–'} mm², L = {cc.length or '–'} m, uložení {cc.method}, {cc.system}"
        lim = f"Iz = {cc.iz or '–'} A" + (f", In {cc.breaker_ref} = {cc.in_breaker:g} A" if cc.in_breaker else "") + \
              (f", ΔU = {cc.du_v} V ({cc.du_pct} %)" if cc.du_pct is not None else "")
        rows.append(["Kabel", cc.ref, vals, lim, "OK" if not cc.issues else "; ".join(cc.issues)])
    for lo, hi, il, ih, msg in calc.check_selectivity(project):
        rows.append(["Selektivita", f"{lo} → {hi}", f"In {il:g} A → {ih:g} A", f"poměr ≥ {calc.SELECTIVITY_RATIO}", msg])
    return head, rows


def dso_report(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Data pro žádost o připojení výrobny k DS."""
    from envocad.export.tz_export import dso_data
    has_plant = any(e.symbol_id in ("fve.pv_string", "fve.inverter", "fve.inverter_hybrid")
                    for s in project.sheets for e in s.elements)
    return ["Údaj", "Hodnota"], ([list(r) for r in dso_data(project, lib)] if has_plant else [])


ALL_REPORTS = [("Data pro DS", dso_report), ("Výpočty", calculations), ("Přístroje", device_list), ("Výkaz materiálu", bom), ("Kabely", cables),
               ("Kabelový plán", cable_plan), ("Zapojovací seznam", wiring_list),
               ("Svorkovnice", terminals), ("Plán svorkovnice", terminal_plan_report), ("Štítky", labels)]
