"""Výkazy odvozené z modelu (čistá data, bez Qt a bez formátů souborů).

Každá funkce vrací (hlavička, řádky) – stejné tabulky použije xlsx, docx i GUI.
"""
from __future__ import annotations

from collections import OrderedDict

from envocad.library.store import LibraryStore
from envocad.model.designation import LOCATION_SYMBOLS, designation, full_designation
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


def _aspects(s: Sheet, e: Element) -> str:
    """Aspekty prvku „=AC+RDC1“ (bez přístroje); prázdné, když list ani prvek žádné nemají."""
    return designation(s, e).aspects


def _tag(project: Project, s: Sheet, e: Element) -> str:
    """Označení prvku do výkazů: plné „=AC+RDC1-F3“; bez aspektů zůstává dnešní „F3“ (ne „-F3“), aby projekty bez
    strukturního označení vypadaly stejně jako dřív. Blok rozvaděče = jeho umístění „+RDC1“."""
    if e.symbol_id in LOCATION_SYMBOLS:
        return full_designation(project, s, e)
    a = _aspects(s, e)
    return f"{a}-{e.ref}" if a and e.ref else e.ref


def _port_text(project: Project, s: Sheet, e: Element, port: str, terminal: str = "", base: str = "") -> str:
    """Konec vodiče: „+RDC1-X1:3“ (svorka), „+RDC1-F2:1“ (prvek:port), u bloku rozvaděče „+RDC1-X1“ (port bloku =
    přívod/vývod uvnitř). Aspekty shodné s `base` (kontext řádku, např. svorkovnice) se vynechají."""
    if e.symbol_id in LOCATION_SYMBOLS and e.ref:
        return f"{full_designation(project, s, e)}-{terminal or port}"
    text = terminal or f"{e.ref or e.symbol_id}:{port}"
    a = _aspects(s, e) if (terminal or e.ref) else ""
    return f"{a}-{text}" if a and a != base else text


def _index(project: Project):
    from envocad.model.xref import DeviceIndex
    return DeviceIndex.build(project)


def devices(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> list[Element]:
    """Přístroje k objednání; cívka stykače se vynechá, když položkou výkazu je stykač (`is_bom_device`). U výkazu
    jednoho listu (`sheet`) jen tehdy, když stykač leží na stejném listu."""
    idx = _index(project)
    return [e for s in _sheets(project, sheet) for e in s.elements
            if e.symbol_id not in NON_DEVICE_SYMBOLS and idx.is_bom_device(e, sheet)]


def _contacts_text(idx, e: Element) -> str:
    """Sloupec Kontakty: páry kontaktů a pólů stykače (secondary) přístroje, jen u položky výkazu skupiny."""
    from envocad.model.xref import natural_key
    g = idx.group_of(e)
    if g is None or g.device[1] is not e:
        return ""
    return ", ".join(sorted(g.used_pairs(), key=natural_key))


def device_list(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Seznam přístrojů (každý zvlášť) – pro štítky a kontrolu."""
    idx = _index(project)
    head = ["Označení", "Přístroj", "Typ", "Výrobce", "Parametry", "Kontakty", "Moduly", "Řada", "Pozice", "List"]
    keyed: list[tuple[tuple, list]] = []
    for s in _sheets(project, sheet):
        for e in s.elements:
            if e.symbol_id in NON_DEVICE_SYMBOLS or not idx.is_bom_device(e, sheet):
                continue
            sym = lib.get_symbol(e.symbol_id)
            pl = s.layout.placement(e.id) if s.is_switchboard else None
            conts = _contacts_text(idx, e)
            d = designation(s, e)
            keyed.append(((d.func, d.loc, _ref_key(e.ref), s.name),
                          [_tag(project, s, e), sym.name, e.attrs.get("type", ""), e.attrs.get("manufacturer", ""),
                           _param_str(e), conts, e.modules or "", (pl.row + 1) if pl else "", pl.pos if pl else "",
                           s.name]))
    keyed.sort(key=lambda kr: kr[0])
    return head, [r for _, r in keyed]


def bom(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Výkaz materiálu – sloučeno podle přístroje/typu/výrobce/parametrů."""
    head = ["Pol.", "Přístroj", "Typ", "Výrobce", "Parametry", "Ks", "Označení"]
    groups: OrderedDict[tuple, list[str]] = OrderedDict()
    from envocad.model.multipole import is_terminal_block, terminal_numbers, wire_conductors
    qty: dict[tuple, int] = {}
    idx = _index(project)
    for s in _sheets(project, sheet):
        for e in s.elements:
            if (e.symbol_id in NON_DEVICE_SYMBOLS and not is_terminal_block(e)) or not idx.is_bom_device(e, sheet):
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
    from envocad.model.project import feed_link_index, wire_xref
    head = ["Označení", "Odkud", "Kam", "Typ kabelu", "Průřez [mm²]", "Žíly", "Délka [m]", "Trasa", "Rozvaděč", "List"]
    rows = []
    idx = feed_link_index(project)
    for s in _sheets(project, sheet):
        for w in s.wires:
            if not (w.attrs.get("ref") or w.attrs.get("cable")):
                continue
            a, b = s.element(w.a.element_id), s.element(w.b.element_id)
            rows.append([w.attrs.get("ref", ""), _port_text(project, s, a, w.a.port), _port_text(project, s, b, w.b.port),
                         w.attrs.get("cable", ""), w.attrs.get("cross", ""), " ".join(w.conductors) or w.attrs.get("poles", ""),
                         w.attrs.get("length", ""), w.attrs.get("route", ""), wire_xref(project, w.id, idx).lstrip("→ "), s.name])
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
                                 _port_text(project, s, other, other_port, base=_aspects(s, end)),
                                 "-".join(bridge) if bridge else "", end.attrs.get("desc", ""), s.name])
    rows.sort(key=lambda r: (r[7], _ref_key(r[0]), _ref_key(str(r[1]))))
    return head, rows


def labels(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Štítky přístrojů a vývodů pro štítkovač: označení + stručný popis."""
    head = ["Štítek", "Popis", "List"]
    keyed: list[tuple[tuple, list]] = []
    idx = _index(project)
    for s in _sheets(project, sheet):
        for e in s.elements:
            if not e.ref or not idx.is_bom_device(e, sheet):   # cívka stykače = jeden štítek se stykačem
                continue
            sym = lib.get_symbol(e.symbol_id)
            desc = e.attrs.get("desc") or " ".join(x for x in (sym.name, e.attrs.get("in_", "") and e.attrs["in_"] + " A") if x)
            d = designation(s, e)
            keyed.append(((d.func, d.loc, _ref_key(e.ref), s.name), [_tag(project, s, e), desc, s.name]))
    keyed.sort(key=lambda kr: kr[0])
    return head, [r for _, r in keyed]


def _ref_key(ref: str) -> tuple:
    """Přirozené řazení F1, F2, F10; plné označení „+RDC1-X1“ nejdřív podle aspektů, pak podle přístroje."""
    import re
    ref = ref or ""
    prefix = ""
    if ref[:1] in ("=", "+") and "-" in ref:
        prefix, _, ref = ref.partition("-")
    m = re.match(r"([A-Za-z]*)(\d*)", ref)
    return (prefix, m.group(1), int(m.group(2) or 0)) if m else (prefix, ref, 0)


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
    """Konec žíly: svorka (+RDC1-X1:3), jinak prvek:port; u bloku rozvaděče cíl uvnitř rozvaděče."""
    from envocad.model.multipole import wire_end_terminal
    t = wire_end_terminal(s, w, conductor, side)
    end = w.a if side == "a" else w.b
    return _port_text(project, s, s.element(end.element_id), end.port, terminal=t)


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
    from envocad.model.wiring import conductor_color, conductor_end
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
                if s.is_switchboard:
                    color = conductor_color(w, name)   # vnitřní vodič: barva z atributu `color`, jinak podle žíly
                    # konce stejně jako výrobní seznam (odvozené svorky, sběrnice jako potenciál „+RDC1-1L1“)
                    ends = [conductor_end(project, s, w, name, side).text for side in ("a", "b")]
                else:
                    color = core.color if core and core.color else CORE_COLORS.get(name, "")
                    ends = [_end_text(project, s, w, side, name) for side in ("a", "b")]
                rows.append([s.name, label, name, color, cross, *ends, c.type if c else w.attrs.get("cable", "")])
    rows.sort(key=lambda r: (r[0], _ref_key(r[1])))
    return head, rows


def wiring_base() -> dict:
    """Parametry výrobního seznamu z firemního standardu (`settings.json standard.wiring`); čte jen export."""
    from envocad.settings import load_settings
    try:
        base = load_settings()["standard"].get("wiring") or {}
    except (OSError, ValueError, KeyError, TypeError):
        base = {}
    return base if isinstance(base, dict) else {}


def _number(x):
    """Číslo do buňky: 25.0 → 25, 1.5 → 1.5, None → ""."""
    if x is None:
        return ""
    return int(x) if float(x).is_integer() else x


def production_wiring_list(project: Project, lib: LibraryStore, sheet: Sheet | None = None,
                           base: dict | None = None) -> tuple[list[str], list[list]]:
    """Výrobní zapojovací seznam pro dílnu (jen listy rozvaděčů): průřez, barva, typ, délka z rozložení, koncovky.
    Průřez a délka jsou čísla. Sloupec Označení se vynechá, když je v celém výstupu prázdný. Výpočet
    `model/wiring.py`; do PDF dokumentace nepatří (`NOT_IN_DOC`)."""
    from envocad.model.wiring import production_wires
    head = ["Č.", "Označení", "Žíla", "Odkud", "Kam", "Průřez [mm²]", "Barva", "Typ vodiče", "Délka [mm]",
            "Koncovka odkud", "Koncovka kam", "Poznámka", "List"]
    rows = []
    for pw in production_wires(project, sheet, wiring_base() if base is None else base, lib):
        rows.append([pw.number, pw.ref, pw.conductor, pw.from_text, pw.to_text, _number(pw.cross), pw.color,
                     pw.wire_type, _number(pw.length_mm), pw.end_from, pw.end_to, "; ".join(pw.notes), pw.sheet])
    if not any(r[1] for r in rows):     # Označení prázdné všude → sloupec vynechat
        head = [h for i, h in enumerate(head) if i != 1]
        rows = [[x for i, x in enumerate(r) if i != 1] for r in rows]
    return head, rows


def production_subtitle(project: Project, sheet: Sheet | None = None, base: dict | None = None) -> list[str]:
    """Podnadpis výrobního seznamu: použité parametry (po rozvaděčích, liší-li se) a pravidlo odvození svorek."""
    from envocad.model.wiring import NUMBER_NOTE, TERMINAL_RULE, WiringParams
    base = wiring_base() if base is None else base
    sheets = [s for s in _sheets(project, sheet) if s.is_switchboard]
    texts: OrderedDict[str, list[str]] = OrderedDict()
    for s in sheets:
        texts.setdefault(WiringParams.resolve(s.layout, base).describe(), []).append(s.name)
    if not texts:
        texts[WiringParams.resolve(None, base).describe()] = []
    lines = []
    for text, names in texts.items():
        prefix = f"Parametry ({', '.join(names)}): " if len(texts) > 1 else "Parametry: "
        lines.append(prefix + text)
    lines.append(TERMINAL_RULE)
    lines.append(NUMBER_NOTE)
    return lines


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


def potentials(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Potenciály (sítě): název, žíly, počet spojů, vodiče, prvky:porty, stav (zkrat)."""
    from envocad.model.potential import nets
    head = ["Potenciál", "Žíly", "Spojů", "Vodiče", "Prvky", "Stav"]
    rows = []
    for n in nets(project, lib):
        if sheet is not None and not any(s.id == sheet.id for s, _, _, _ in n.members):
            continue
        wires = sorted({w.attrs.get("ref") or w.attrs.get("cable", "") for _, w, _ in n.wires if w.attrs.get("ref") or w.attrs.get("cable")},
                       key=_ref_key)
        members = sorted({f"{e.ref or e.symbol_id}:{p}" for _, e, p, _ in n.members if e.symbol_id != "sb.junction"}, key=_ref_key)
        rows.append([n.name, " ".join(sorted(n.conductors, key=lambda c: c)), len(n.members), ", ".join(wires), ", ".join(members),
                     n.short_issue() or "OK"])
    rows.sort(key=lambda r: _ref_key(r[0]))
    return head, rows


ALL_REPORTS = [("Data pro DS", dso_report), ("Výpočty", calculations), ("Přístroje", device_list), ("Výkaz materiálu", bom), ("Kabely", cables),
               ("Kabelový plán", cable_plan), ("Zapojovací seznam", wiring_list),
               ("Výrobní zapojovací seznam", production_wiring_list),
               ("Svorkovnice", terminals), ("Plán svorkovnice", terminal_plan_report), ("Potenciály", potentials), ("Štítky", labels)]

# výkazy, které nejsou součástí PDF dokumentace (výrobní podklad pro dílnu) – `doc_pdf.DocBuilder.plan` je přeskočí
NOT_IN_DOC = {"Výrobní zapojovací seznam"}

# doplňkové řádky podnadpisu výkazu v xlsx: název → fn(project, sheet) -> list[str]
REPORT_SUBTITLES = {"Výrobní zapojovací seznam": production_subtitle}
