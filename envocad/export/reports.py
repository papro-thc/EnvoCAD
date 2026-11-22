"""Výkazy odvozené z modelu (čistá data, bez Qt a bez formátů souborů).

Každá funkce vrací (hlavička, řádky) – stejné tabulky použije xlsx, docx i GUI.
"""
from __future__ import annotations

import functools
from collections import OrderedDict

from envocad.library.store import LibraryStore
from envocad.model.advisory import ADVISORY_NOTE
from envocad.model.designation import LOCATION_SYMBOLS, designation, element_name, full_designation, scope_key
from envocad.model.feed import FEED_SYMBOL
from envocad.model.notes import plural
from envocad.model.project import INTERRUPT_SYMBOL, NON_DEVICE_SYMBOLS, Element, Project, Sheet, clean_view
from envocad.model.xref import natural_key

TERMINAL_SYMBOLS = {FEED_SYMBOL, "sb.terminal_block"}

DEVICE_PARAMS = ["in_", "char", "poles", "idn", "spd_type", "uc", "icu", "ir", "p_ac", "e_kwh", "sn"]


def over_clean(fn):
    """Výkaz počítá nad `without_dangling` (vodiče na neexistující prvek vynechá) – i když ho volá přímo plugin
    nebo GUI bez předchozího `clean_view`. List `sheet` se nahradí odpovídajícím listem čistého pohledu.
    Bez visících vodičů je to jen průchod (`clean_view` vrátí projekt i list beze změny)."""
    @functools.wraps(fn)
    def wrapper(project: Project, lib: LibraryStore, sheet: Sheet | None = None, *args, **kwargs):
        project, sheet = clean_view(project, sheet)
        return fn(project, lib, sheet, *args, **kwargs)
    return wrapper


def _sheets(project: Project, sheet: Sheet | None) -> list[Sheet]:
    return [sheet] if sheet else list(project.sheets)


def _int(v) -> int:
    try:
        return int(float(str(v or 0).replace(",", ".")))
    except ValueError:
        return 0


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


def _port_text(project: Project, s: Sheet, e: Element, port: str, terminal: str = "", base: str = "",
               groups: dict | None = None) -> str:
    """Konec vodiče: „+RDC1-X1:3“ (svorka), „+RDC1-F2:1“ (prvek:port), u bloku rozvaděče „+RDC1-X1“ (port bloku =
    přívod/vývod uvnitř). Aspekty shodné s `base` (kontext řádku, např. svorkovnice) se vynechají. Přerušovací bod
    hlavního úseku kabelu, jehož protějšek má úsek pokračování → skutečný konec za protějškem
    (`xref.through_interrupt`: kabel přes listy JPS „Odkud T1:AC“); jinak zůstává „P:1“. `groups` =
    `xref.interrupt_groups` (výkaz je spočítá jednou)."""
    if e.symbol_id == INTERRUPT_SYMBOL and not terminal:
        from envocad.model.xref import through_interrupt
        hit = through_interrupt(project, s, e, port, groups)
        if hit is not None:
            s, e, port = hit.sheet, hit.element, hit.port   # jen jeden krok – řetěz se nesleduje (nezacyklí se)
    return _plain_port_text(project, s, e, port, terminal, base)


def _plain_port_text(project: Project, s: Sheet, e: Element, port: str, terminal: str = "", base: str = "") -> str:
    if e.symbol_id in LOCATION_SYMBOLS and e.ref:
        return f"{full_designation(project, s, e)}-{terminal or port}"
    text = terminal or f"{element_name(e)}:{port}"
    a = _aspects(s, e) if (terminal or e.ref) else ""
    return f"{a}-{text}" if a and a != base else text


def _interrupts(project: Project) -> dict:
    """Skupiny přerušovacích bodů jednou za výkaz (`xref.interrupt_groups`) – předávají se do `_port_text`."""
    from envocad.model.xref import interrupt_groups
    return interrupt_groups(project)


def _index(project: Project):
    from envocad.model.xref import DeviceIndex
    return DeviceIndex.build(project)


@over_clean
def devices(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> list[Element]:
    """Přístroje k objednání; cívka stykače se vynechá, když položkou výkazu je stykač (`is_bom_device`). U výkazu
    jednoho listu (`sheet`) jen tehdy, když stykač leží na stejném listu."""
    idx = _index(project)
    return [e for s in _sheets(project, sheet) for e in s.elements
            if e.symbol_id not in NON_DEVICE_SYMBOLS and idx.is_bom_device(e, sheet)]


def _contacts_text(idx, e: Element) -> str:
    """Sloupec Kontakty: páry kontaktů a pólů stykače (secondary) přístroje, jen u položky výkazu skupiny."""
    g = idx.group_of(e)
    if g is None or g.device[1] is not e:
        return ""
    return ", ".join(sorted(g.used_pairs(), key=natural_key))


def _symbol(lib, symbol_id: str):
    """Značka z knihovny; neznámé symbol_id → zástupná značka (výkaz nespadne, kontrola hlásí „Neznámá značka“)."""
    try:
        return lib.get_symbol(symbol_id)
    except KeyError:
        from envocad.model.symbol import placeholder_symbol
        return placeholder_symbol(symbol_id)


@over_clean
def device_list(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Seznam přístrojů (každý zvlášť) – pro štítky a kontrolu. Moduly z artiklu (`device_size`), jinak z atributu."""
    from envocad.model.device_size import device_modules
    from envocad.model.multipole import is_terminal_block
    idx = _index(project)
    head = ["Označení", "Přístroj", "Typ", "Výrobce", "Parametry", "Kontakty", "Moduly", "Řada", "Pozice", "List"]
    keyed: list[tuple[tuple, list]] = []
    for s in _sheets(project, sheet):
        strips: dict[tuple[str, str, str], list[Element]] = {}
        for e in s.elements:
            if e.symbol_id in NON_DEVICE_SYMBOLS or not idx.is_bom_device(e, sheet):
                continue
            if is_terminal_block(e) and e.ref:
                # svorkovnice = jeden řádek za všechny skupiny svorek; klíč jako u štítků (`labels`): prostor
                # označení + ref – skupina X1 s vlastním umístěním (override +loc) je jiná svorkovnice
                strips.setdefault((*scope_key(s, e), e.ref), []).append(e)
                continue
            sym = _symbol(lib, e.symbol_id)
            pl = s.layout.placement(e.id) if s.is_switchboard else None
            conts = _contacts_text(idx, e)
            d = designation(s, e)
            keyed.append(((natural_key(d.func), natural_key(d.loc), _ref_key(e.ref), natural_key(s.name)),
                          [_tag(project, s, e), sym.name, e.attrs.get("type", ""), e.attrs.get("manufacturer", ""),
                           _param_str(e), conts, device_modules(e, lib) or "", (pl.row + 1) if pl else "",
                           pl.pos if pl else "",
                           s.name]))
        for (_f, _l, ref), grp in strips.items():
            e = grp[0]
            n = sum(_terminal_qty(s, g) for g in grp)
            pls = sorted((pl.row, pl.pos) for g in grp if s.is_switchboard and (pl := s.layout.placement(g.id)))
            mods = round(sum(device_modules(g, lib) for g in grp), 2)
            types = ", ".join(dict.fromkeys(t for g in grp if (t := g.attrs.get("type", ""))))
            mfrs = ", ".join(dict.fromkeys(m for g in grp if (m := g.attrs.get("manufacturer", ""))))
            params = f"{n} {_terminal_word(n)}" + (f", {len(grp)} {'skupiny' if len(grp) < 5 else 'skupin'}" if len(grp) > 1 else "")
            d = designation(s, e)
            keyed.append(((natural_key(d.func), natural_key(d.loc), _ref_key(ref), natural_key(s.name)),
                          [_tag(project, s, e), _symbol(lib, e.symbol_id).name, types, mfrs, params, "", mods or "",
                           (pls[0][0] + 1) if pls else "", pls[0][1] if pls else "", s.name]))
    keyed.sort(key=lambda kr: kr[0])
    return head, [r for _, r in keyed]


def _terminal_word(n: int) -> str:
    return "svorka" if n == 1 else ("svorky" if 2 <= n <= 4 else "svorek")


def _terminal_qty(s: Sheet, e: Element) -> int:
    """Počet svorek skupiny: žíly napojených vodičů, jinak čísla svorek z atributu, jinak 1."""
    from envocad.model.multipole import terminal_numbers, wire_conductors
    n = len({c for w in s.wires for end in (w.a, w.b) if end.element_id == e.id for c in wire_conductors(w)})
    return n or len([x for x in terminal_numbers(e, 1) if x]) or 1


@over_clean
def bom(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Výkaz materiálu – sloučeno podle přístroje/typu/výrobce/parametrů."""
    head = ["Pol.", "Přístroj", "Typ", "Výrobce", "Parametry", "Ks", "Označení"]
    groups: OrderedDict[tuple, list[str]] = OrderedDict()
    from envocad.model.multipole import is_terminal_block
    qty: dict[tuple, int] = {}
    idx = _index(project)
    for s in _sheets(project, sheet):
        strip_qty: OrderedDict[tuple, int] = OrderedDict()   # (klíč položky, plné označení svorkovnice) → kusy
        for e in s.elements:
            if (e.symbol_id in NON_DEVICE_SYMBOLS and not is_terminal_block(e)) or not idx.is_bom_device(e, sheet):
                continue
            if is_terminal_block(e):
                # skupina svorek (i přívod/vývod) = tolik kusů svorky, kolik má žil; parametr = průřez/druh z artiklu;
                # označení plné (+RDC1-X1 – X1 je v každém rozvaděči jiná), skupiny jedné svorkovnice sečtené
                n = _terminal_qty(s, e)
                params = ", ".join(x for x in (e.attrs.get("cross", "") and f"{e.attrs['cross']} mm²",
                                               e.attrs.get("kind", "")) if x)
                key = ("Řadová svorka", e.attrs.get("type", ""), e.attrs.get("manufacturer", ""), params)
                sk = (key, _tag(project, s, e) or element_name(e, lib))
                strip_qty[sk] = strip_qty.get(sk, 0) + n
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
                    # výrobce modulu z atributu (artikl modulu ho propíše), optimizéru z `opt_manufacturer` (artikl)
                    mfr = e.attrs.get("manufacturer" if akey == "type" else "opt_manufacturer", "")
                    key = (name, e.attrs.get(akey, ""), mfr, params)
                    groups.setdefault(key, []).append(f"{_tag(project, s, e)} ({n})")
                    qty[key] = qty.get(key, 0) + n
                continue
            if e.symbol_id == "fve.battery" and _int(e.attrs.get("n_modules")) > 1:
                # věž z katalogu: n modulů (master/modul + slave) a řídicí jednotka BMS – ne jeden kus
                n, mfr, tag = _int(e.attrs.get("n_modules")), e.attrs.get("manufacturer", ""), _tag(project, s, e)
                name, slave = _symbol(lib, e.symbol_id).name, e.attrs.get("slave_type", "")
                parts = [((name, e.attrs.get("type", ""), mfr, ""), 1 if slave else n)]
                if slave:
                    parts.append(((name, slave, mfr, "přídavný modul"), n - 1))
                if e.attrs.get("bms"):
                    parts.append((("Řídicí jednotka baterie", e.attrs["bms"], mfr, ""), 1))
                for key, k in parts:
                    groups.setdefault(key, []).append(f"{tag} ({k})")
                    qty[key] = qty.get(key, 0) + k
                continue
            key = (_symbol(lib, e.symbol_id).name, e.attrs.get("type", ""), e.attrs.get("manufacturer", ""), _param_str(e))
            groups.setdefault(key, []).append(_tag(project, s, e))
            qty[key] = qty.get(key, 0) + 1
            if e.symbol_id == "fve.battery" and e.attrs.get("bms"):   # jeden modul + BMS
                bkey = ("Řídicí jednotka baterie", e.attrs["bms"], e.attrs.get("manufacturer", ""), "")
                groups.setdefault(bkey, []).append(_tag(project, s, e))
                qty[bkey] = qty.get(bkey, 0) + 1
        for (key, tag), n in strip_qty.items():
            groups.setdefault(key, []).append(f"{tag} ({n})")
        # můstky: za každou skupinu můstků jeden (vícepólový) můstek dané svorkovnice; počítají se jen svorky, které
        # na svorkovnici existují (můstek na smazanou svorku se nepočítá, skupina pod 2 svorky odpadá)
        if s.is_switchboard or sheet is not None:
            from envocad.model.bridges import resolve_bridge
            from envocad.model.terminal_plan import strip_numbers
            first = {}
            for e in s.elements:
                if is_terminal_block(e) and e.ref:
                    first.setdefault(e.ref, e)
            for strip in sorted(first, key=natural_key):
                existing = strip_numbers(project, s, strip)
                tag = _tag(project, s, first[strip]) or strip
                for g in project.bridge_groups(strip, s):
                    g = [x for x in g if x in existing]
                    if len(g) < 2:
                        continue
                    # artikl můstku z `bridge_id` skupiny svorek, na které můstek leží (`model/bridges.py`)
                    br = resolve_bridge(s, strip, g, lib)
                    params = f"{len(g)} pólů" + (f", {br.note}" if br.note else "")
                    key = ("Můstek svorek", br.type, br.manufacturer, params)
                    groups.setdefault(key, []).append(f"{tag}:{'-'.join(g)}")
                    qty[key] = qty.get(key, 0) + 1
    rows = []
    order = sorted(groups.items(), key=lambda kv: (kv[0][0], natural_key(kv[0][3]), kv[0][1], kv[0][2]))
    for i, (key, refs) in enumerate(order, start=1):
        rows.append([i, key[0], key[1], key[2], key[3], qty[key], ", ".join(sorted(refs, key=_ref_key))])
    return head, rows


@over_clean
def cables(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Seznam kabelů / vodičů s označením nebo typem kabelu."""
    from envocad.model.project import feed_link_index, wire_xref
    head = ["Označení", "Odkud", "Kam", "Typ kabelu", "Průřez [mm²]", "Žíly", "Délka [m]", "Trasa", "Rozvaděč", "List"]
    rows = []
    idx = feed_link_index(project)
    groups = _interrupts(project)
    for s in _sheets(project, sheet):
        for w in s.wires:
            if not (w.attrs.get("ref") or w.attrs.get("cable")):
                continue
            a, b = s.element(w.a.element_id), s.element(w.b.element_id)
            rows.append([w.attrs.get("ref", ""), _port_text(project, s, a, w.a.port, groups=groups),
                         _port_text(project, s, b, w.b.port, groups=groups),
                         w.attrs.get("cable", ""), w.attrs.get("cross", ""), " ".join(w.conductors) or w.attrs.get("poles", ""),
                         w.attrs.get("length", ""), w.attrs.get("route", ""), wire_xref(project, w.id, idx).lstrip("→ "), s.name])
    rows.sort(key=lambda r: (natural_key(r[9]), _ref_key(r[0])))
    return head, rows


@over_clean
def terminals(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Svorkovnice: každá žíla každého vodiče napojeného na svorku/přívod/vývod + ruční přiřazení z Wire.terminals."""
    from envocad.model.multipole import sheet_dead_conductors, wire_end_terminal
    head = ["Svorkovnice", "Svorka", "Žíla", "Kabel", "Připojeno na", "Můstek", "Popis", "List"]
    rows = []
    groups = _interrupts(project)
    for s in _sheets(project, sheet):
        dead = sheet_dead_conductors(project, s, lib)       # žíly, které na jističi 1p nikam nevedou
        for w in s.wires:
            a, b = s.element(w.a.element_id), s.element(w.b.element_id)
            for side, end, other, other_port in (("a", a, b, w.b.port), ("b", b, a, w.a.port)):
                if end.symbol_id not in TERMINAL_SYMBOLS:
                    continue
                conds = [c for c in w.conductors if c not in dead.get(w.id, ())] or [""]
                base = _aspects(s, end)
                for i, c in enumerate(conds, start=1):
                    desig = wire_end_terminal(s, w, c, side) if c else ""
                    strip, _, num = desig.partition(":")
                    term = num or end.attrs.get("terminal") or (str(i) if c else "")
                    bridge = project.bridge_of(strip or end.ref, term, s)
                    rows.append([end.ref, term, c, w.attrs.get("ref") or w.attrs.get("cable", ""),
                                 _other_end_text(project, s, w, c, "b" if side == "a" else "a", other, other_port, base,
                                                 groups),
                                 "-".join(bridge) if bridge else "", end.attrs.get("desc", ""), s.name])
    rows.sort(key=lambda r: (natural_key(r[7]), _ref_key(r[0]), natural_key(str(r[1])), r[2]))
    return head, rows


def _other_end_text(project: Project, s: Sheet, w, conductor: str, side: str, other: Element, other_port: str,
                    base: str, groups: dict | None = None) -> str:
    """Druhý konec žíly pro výkaz svorkovnice – stejně jako zapojovací/výrobní seznam (`wiring.conductor_end`:
    pól přístroje „Q1:3“, svorka, potenciál sběrnice); aspekty shodné se svorkovnicí (`base`) se vynechají."""
    if not conductor:
        return _port_text(project, s, other, other_port, base=base, groups=groups)
    from envocad.model.wiring import conductor_end
    text = conductor_end(project, s, w, conductor, side).text
    if base and text.startswith(base + "-"):
        text = text[len(base) + 1:]
    return text


@over_clean
def labels(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Štítky přístrojů a vývodů pro štítkovač: označení + stručný popis."""
    from envocad.model.multipole import is_terminal_block
    from envocad.model.project import CONTACT_SYMBOLS
    head = ["Štítek", "Popis", "List"]
    keyed: list[tuple[tuple, list]] = []
    idx = _index(project)
    for s in _sheets(project, sheet):
        strips: set[tuple] = set()
        for e in s.elements:
            # cívka stykače = jeden štítek se stykačem; kontakty patří k přístroji (vlastní štítek nemají),
            # přerušovací bod není fyzický prvek
            if not e.ref or not idx.is_bom_device(e, sheet) or e.symbol_id in CONTACT_SYMBOLS \
                    or e.symbol_id == INTERRUPT_SYMBOL:
                continue
            sym = _symbol(lib, e.symbol_id)
            if is_terminal_block(e):
                key = (*scope_key(s, e), e.ref)
                if key in strips:      # skupiny svorek jedné svorkovnice = jeden štítek
                    continue
                strips.add(key)
                desc = sym.name
            else:
                desc = e.attrs.get("desc") or " ".join(x for x in (sym.name, e.attrs.get("in_", "") and e.attrs["in_"] + " A") if x)
            d = designation(s, e)
            keyed.append(((natural_key(d.func), natural_key(d.loc), _ref_key(e.ref), natural_key(s.name)),
                          [_tag(project, s, e), desc, s.name]))
    keyed.sort(key=lambda kr: kr[0])
    return head, [r for _, r in keyed]


def _ref_key(ref: str) -> tuple:
    """Přirozené řazení F1, F2, F10, F10.2; plné označení „+RDC1-X1“ nejdřív podle aspektů (přirozeně: +R2 < +R10),
    pak podle přístroje."""
    ref = ref or ""
    prefix = ""
    if ref[:1] in ("=", "+") and "-" in ref:
        prefix, _, ref = ref.partition("-")
    return (natural_key(prefix), natural_key(ref))


@over_clean
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


def _end_text(project: Project, s: Sheet, w, side: str, conductor: str, groups: dict | None = None) -> str:
    """Konec žíly: svorka (+RDC1-X1:3), jinak prvek:port; u bloku rozvaděče cíl uvnitř rozvaděče. Přes přerušení
    (`xref.through_interrupt`) se svorka počítá z vodiče pokračování na protějším listu (X1:5, ne X1:1)."""
    from envocad.model.multipole import wire_end_terminal
    t = wire_end_terminal(s, w, conductor, side)
    end = w.a if side == "a" else w.b
    e = s.element(end.element_id)
    if not t and e.symbol_id == INTERRUPT_SYMBOL:
        from envocad.model.xref import through_interrupt
        hit = through_interrupt(project, s, e, end.port, groups)
        if hit is not None:
            t = wire_end_terminal(hit.sheet, hit.wire, conductor, hit.side)
            return _plain_port_text(project, hit.sheet, hit.element, hit.port, terminal=t)
    return _port_text(project, s, e, end.port, terminal=t, groups=groups)


@over_clean
def cable_plan(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Kabelový plán: každá žíla každého kabelu – číslo, barva, odkud, kam (jako v EPLAN)."""
    from envocad.model.project import CORE_COLORS, sync_cables
    sync_cables(project)   # úsek pokračování přes přerušení kabel nemá (`cable_of_wire` → None), řádky nedostane
    head = ["Kabel", "Typ", "Průřez [mm²]", "Žíla", "Č.", "Barva", "Odkud", "Kam", "Stínění", "Délka [m]", "List"]
    rows = []
    groups = _interrupts(project)
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
                             _end_text(project, s, w, "a", name, groups), _end_text(project, s, w, "b", name, groups),
                             "ano" if c.shield else "", c.length, s.name])
    rows.sort(key=lambda r: (natural_key(r[10]), _ref_key(r[0]), int(r[4]) if str(r[4]).isdigit() else 99))
    return head, rows


@over_clean
def wiring_list(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Zapojovací seznam: každé propojení po žílách – odkud, kam, kabel/vodič, barva, průřez (pro zapojování)."""
    from envocad.model.project import CORE_COLORS, sync_cables
    from envocad.model.wiring import conductor_color, merged_conductors
    from envocad.model.xref import is_continuation
    sync_cables(project)
    groups = _interrupts(project)
    head = ["List", "Kabel / vodič", "Žíla", "Barva", "Průřez [mm²]", "Odkud", "Kam", "Poznámka"]
    rows = []
    for s in _sheets(project, sheet):
        if s.is_switchboard:
            # vnitřní vodiče: konce i sloučení nespínaných N/PE vedených v JPS přes přístroj stejně jako výrobní
            # seznam (`wiring.merged_conductors`) – „vede kolem Q1“ místo neexistující svorky „Q1:PE“
            for mc in merged_conductors(project, s):
                w = mc.wires[0]
                label = "/".join(dict.fromkeys(r for x in mc.wires if (r := (x.attrs.get("ref") or "").strip()))) \
                    or "vodič"
                cross = next((x.attrs["cross"] for x in mc.wires if x.attrs.get("cross")), "")
                kinds = list(dict.fromkeys(k for x in mc.wires if (k := x.attrs.get("cable", ""))))
                note = "; ".join([*kinds, *mc.notes])
                rows.append([s.name, label, mc.conductor, conductor_color(w, mc.conductor), cross,
                             mc.end_a.text, mc.end_b.text, note])
            continue
        for w in s.wires:
            if is_continuation(project, s, w, groups):   # pokračování kabelu přes přerušení – řádky má úsek s kabelem
                continue
            c = project.cable_of_wire(w)
            label = c.ref if c else (w.attrs.get("ref") or "vodič")
            cross = (c.cross if c else "") or w.attrs.get("cross", "")
            for name in (w.conductors or ["L1"]):
                core = c.core(name) if c else None
                color = core.color if core and core.color else CORE_COLORS.get(name, "")
                ends = [_end_text(project, s, w, side, name, groups) for side in ("a", "b")]
                rows.append([s.name, label, name, color, cross, *ends, c.type if c else w.attrs.get("cable", "")])
    rows.sort(key=lambda r: (natural_key(r[0]), _ref_key(r[1])))
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


@over_clean
def production_wiring_list(project: Project, lib: LibraryStore, sheet: Sheet | None = None,
                           base: dict | None = None) -> tuple[list[str], list[list]]:
    """Výrobní zapojovací seznam pro dílnu (jen listy rozvaděčů): průřez, barva, typ, délka z rozložení, koncovky.
    Průřez a délka jsou čísla. Sloupec Označení se vynechá, když je v celém výstupu prázdný. Výpočet
    `model/wiring.py`; do PDF dokumentace nepatří (`NOT_IN_DOC`)."""
    from envocad.model.wiring import production_wires
    head = ["Č.", "Označení", "Žíla", "Odkud", "Kam", "Průřez [mm²]", "Barva", "Typ vodiče", "Délka [mm]",
            "Koncovka odkud", "Koncovka kam", "Návlečka odkud", "Návlečka kam", "Poznámka", "List"]
    rows = []
    for pw in production_wires(project, sheet, wiring_base() if base is None else base, lib):
        rows.append([pw.number, pw.ref, pw.conductor, pw.from_text, pw.to_text, _number(pw.cross), pw.color,
                     pw.wire_type, _number(pw.length_mm), pw.end_from, pw.end_to, pw.marker_from, pw.marker_to,
                     "; ".join(pw.notes), pw.sheet])
    drop = {i for i in (1, 11, 12) if not any(r[i] for r in rows)}   # prázdné všude (bez označení / bez návleček)
    if drop:
        head = [h for i, h in enumerate(head) if i not in drop]
        rows = [[x for i, x in enumerate(r) if i not in drop] for r in rows]
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


def _g(v) -> str:
    return "–" if v is None else f"{v:g}"


def _modules(n: int) -> str:
    return f"{n} {plural(n, 'modul', 'moduly', 'modulů')}"


def fixed_voltage_parts(sc) -> tuple[str, str]:
    """(„pevné U 750 V“, „P stringu 6160 / 11250 W“) stringu s pevným napětím (`calc.StringCheck`, neznámé „–“)."""
    return f"pevné U {_g(sc.u_string)} V", f"P stringu {_g(sc.p_string)} / {_g(sc.p_string_max)} W"


def fixed_voltage_text(sc) -> str:
    """Hodnoty stringu s pevným napětím pro výkaz Výpočty: „14 optimizérů, pevné U 750 V, P stringu 6160 / 11250 W“."""
    n_opt = f"{sc.n_opt} {plural(sc.n_opt, 'optimizér', 'optimizéry', 'optimizérů')}, " if sc.n_opt else ""
    return n_opt + ", ".join(fixed_voltage_parts(sc))


@over_clean
def calculations(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Výkaz výpočtů: stringy vs. střídač, kabely (I, Iz, In, ΔU), selektivita."""
    from envocad.model import calc
    head = ["Část", "Prvek", "Hodnoty", "Mez / porovnání", "Výsledek"]
    rows = []
    for sc in calc.check_strings(project, lib=lib):
        if sheet is not None and sc.sheet != sheet.name:
            continue
        if sc.mode == "fixed_voltage":   # pevné napětí (SolarEdge): Uoc·n ani okno MPPT se nekontrolují
            vals = f"{_modules(sc.n)}, {fixed_voltage_text(sc)}"
            lim = f"{sc.inverter}: optimizérů {sc.n_opt_min or '–'}–{sc.n_opt_max or '–'}, " \
                  f"P stringu ≤ {_g(sc.p_string_max)} W"
        else:
            vals = f"{_modules(sc.n)}, Uoc({sc.t_min:g} °C) = {sc.uoc_cold} V, Umpp({sc.t_max:g} °C) = {sc.umpp_hot} V, 1,25·Isc = {calc.SAFETY_ISC * sc.isc:.1f} A"
            lim = f"{sc.inverter}: Umax {sc.u_dc_max or '–'} V, MPPT {sc.u_mppt_min or '–'}–{sc.u_mppt_max or '–'} V, Imax {sc.i_mppt_max or '–'} A"
            if sc.isc_mppt_max:   # nové pravidlo: součet Isc paralelních stringů na MPPT
                lim += f", Isc max MPPT {sc.isc_mppt_max:g} A ({sc.n_par} str. na MPPT)"
        rows.append(["String", sc.ref, vals, lim, "OK" if sc.ok else "; ".join(sc.issues)])
    for cc in calc.check_cables(project):
        if sheet is not None and cc.sheet != sheet.name:
            continue
        vals = f"I = {cc.i_a or '–'} A, S = {cc.cross or '–'} mm², L = {cc.length or '–'} m, uložení {cc.method}, {cc.system}"
        lim = f"Iz = {cc.iz or '–'} A ({ADVISORY_NOTE})" + \
              (f", In {cc.breaker_ref} = {cc.in_breaker:g} A" if cc.in_breaker else "") + \
              (f", ΔU = {cc.du_v} V ({cc.du_pct} %)" if cc.du_pct is not None else "")
        rows.append(["Kabel", cc.ref, vals, lim, "OK" if not cc.issues else "; ".join(cc.issues)])
    for lo, hi, il, ih, msg in calc.check_selectivity(project, sheet):
        rows.append(["Selektivita", f"{lo} → {hi}", f"In {il:g} A → {ih:g} A", f"poměr ≥ {calc.SELECTIVITY_RATIO}", msg])
    rows += _thermal_rows(project, lib, sheet)
    return head, rows


def _thermal_rows(project: Project, lib: LibraryStore, sheet: Sheet | None) -> list[list]:
    """Řádky „Oteplení“ výkazu Výpočty: jeden na list rozvaděče (IEC TR 60890, výsledek `ThermalResult.verdict`)."""
    from envocad.model.thermal import layout_inputs, temperature_rise
    rows = []
    for sb in project.switchboards():
        if sheet is not None and sb.id != sheet.id:
            continue
        try:
            rdf, t_amb = layout_inputs(sb.layout)
            r = temperature_rise(sb, rdf=rdf, t_ambient_c=t_amb, project=project, lib=lib)
        except Exception:  # noqa: BLE001 – výkaz se vytvoří i bez výpočtu oteplení
            r = None
        if r is None:
            continue
        src = r.loss_summary()     # zdroj ztrát přístrojů: artikl / ruční / odhad
        rows.append(["Oteplení", sb.name, f"ΣPv {r.p_total_w:.0f} W" + (f" ({src})" if src else "")
                     + f", okolí {r.t_ambient_c:.0f} °C", f"horní část ≈ {r.t_top_c:.0f} °C", r.verdict()])
    return rows


@over_clean
def dso_report(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Data pro žádost o připojení výrobny k DS."""
    from envocad.export.tz_export import dso_data
    has_plant = any(e.symbol_id in ("fve.pv_string", "fve.inverter", "fve.inverter_hybrid")
                    for s in project.sheets for e in s.elements)
    return ["Údaj", "Hodnota"], ([list(r) for r in dso_data(project, lib)] if has_plant else [])


@over_clean
def potentials(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Potenciály (sítě): název, žíly, počet spojů, vodiče, prvky:porty, stav (zkrat)."""
    from envocad.model.potential import nets
    head = ["Potenciál", "Žíly", "Spojů", "Vodiče", "Prvky", "Stav", "List"]
    rows = []
    for n in nets(project, lib):
        if sheet is not None and not any(s.id == sheet.id for s, _, _, _ in n.members):
            continue
        wires = sorted({w.attrs.get("ref") or w.attrs.get("cable", "") for _, w, _ in n.wires if w.attrs.get("ref") or w.attrs.get("cable")},
                       key=_ref_key)
        # prvky plným označením s aspekty (+RDC1-F1:1) – X1 v různých rozvaděčích jsou různé svorkovnice
        members = sorted({f"{_tag(project, s, e) or element_name(e, lib)}:{p}" for s, e, p, _ in n.members
                          if e.symbol_id != "sb.junction"}, key=_ref_key)
        sheets_ = sorted({s.name for s, _, _, _ in n.members}, key=natural_key)
        rows.append([n.name, " ".join(sorted(n.conductors, key=lambda c: c)), len(n.members), ", ".join(wires), ", ".join(members),
                     n.short_issue() or "OK", ", ".join(sheets_)])
    rows.sort(key=lambda r: _ref_key(r[0]))
    return head, rows


def _metres(v) -> float | None:
    """„25“, „12,5“, „25 m“ → metry; prázdné / nečíselné → None."""
    t = str(v or "").strip().lower().removesuffix("m").strip().replace(",", ".")
    try:
        x = float(t)
    except ValueError:
        return None
    return x if x > 0 else None


@over_clean
def cable_material(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Kabely a vodiče k objednání: kabely JPS sečtené podle typu a průřezu (metry z délky kabelu/vodiče), vnitřní
    vodiče rozvaděčů podle typu, průřezu a barvy (délky z výrobního zapojovacího seznamu – už s rezervou na konce)
    a dutinky podle druhu. Sloupec „Bez délky“ = kolik položek délku nemá (součet je pak neúplný)."""
    from envocad.model.wiring import production_wires
    head = ["Pol.", "Druh", "Typ", "Průřez [mm²]", "Barva", "Ks", "Délka [m]", "Bez délky", "Označení"]
    groups: OrderedDict[tuple, dict] = OrderedDict()

    def add(key: tuple, length: float | None, ref: str = "", n: int = 1) -> None:
        g = groups.setdefault(key, {"n": 0, "m": 0.0, "missing": 0, "refs": []})
        g["n"] += n
        if length is None:
            g["missing"] += n
        else:
            g["m"] += length
        if ref and ref not in g["refs"]:
            g["refs"].append(ref)

    seen: set[str] = set()                 # kabel přes více vodičů (svorky) se počítá jednou
    for s in _sheets(project, sheet):
        if s.is_switchboard:
            continue
        for w in s.wires:
            c = project.cable_of_wire(w)
            if c is not None:
                if c.id in seen:
                    continue
                seen.add(c.id)
                ctype, cross, length, ref = c.type, c.cross, c.length or w.attrs.get("length", ""), c.ref
            else:
                ctype, cross, length, ref = (w.attrs.get("cable", ""), w.attrs.get("cross", ""),
                                             w.attrs.get("length", ""), w.attrs.get("ref", ""))
            if not (ctype or cross):
                continue
            add(("Kabel", ctype, str(cross), ""), _metres(length), ref)
    base = wiring_base()
    for pw in production_wires(project, sheet, base, lib):
        add(("Vodič rozvaděče", pw.wire_type, str(_number(pw.cross)), pw.color),
            pw.length_mm / 1000 if pw.length_mm else None)
        for fe in (pw.ferrule_from, pw.ferrule_to):
            if fe is not None:
                add(("Dutinka", fe.text(), "", ""), 0.0)
    order = sorted(groups.items(), key=lambda kv: (["Kabel", "Vodič rozvaděče", "Dutinka"].index(kv[0][0]),
                                                   kv[0][1], natural_key(kv[0][2]), kv[0][3]))
    rows = []
    for i, ((kind, typ, cross, color), g) in enumerate(order, start=1):
        metres = "" if kind == "Dutinka" or g["missing"] == g["n"] else round(g["m"], 1)
        rows.append([i, kind, typ, cross, color, g["n"], metres, g["missing"] if kind != "Dutinka" else "",
                     ", ".join(sorted(g["refs"], key=_ref_key))])
    return head, rows


def _cable_tag(project: Project, s: Sheet, w) -> str:
    """Označení kabelu na štítek: plné „=DC-W3“, bez aspektů „W3“."""
    from envocad.model.designation import full_designation
    t = full_designation(project, s, w) if w.attrs.get("ref") else ""
    return t.removeprefix("-")


@over_clean
def marking(project: Project, lib: LibraryStore, sheet: Sheet | None = None) -> tuple[list[str], list[list]]:
    """Značení vodičů a kabelů pro tisk (ČSN EN 62491): štítek kabelu JPS na obou koncích (označení kabelu
    a adresa protějšího konce) a návlečky vnitřních vodičů rozvaděčů na obou koncích podle druhu značení
    (`wire_marking`: adresné / odkud-kam / číslo). Každý řádek = jeden štítek / návlečka."""
    from envocad.model.wiring import production_wires
    head = ["Druh", "Text", "Druhý řádek", "Umístění", "Vodič / kabel", "Žíla", "List"]
    rows = []
    for s in _sheets(project, sheet):
        if s.is_switchboard:
            continue
        for w in s.wires:
            tag = _cable_tag(project, s, w)
            if not tag:
                continue
            a, b = s.element(w.a.element_id), s.element(w.b.element_id)
            ea, eb = _port_text(project, s, a, w.a.port), _port_text(project, s, b, w.b.port)
            rows.append(["Štítek kabelu", tag, f"→ {eb}", ea, tag, "", s.name])
            rows.append(["Štítek kabelu", tag, f"→ {ea}", eb, tag, "", s.name])
    for pw in production_wires(project, sheet, wiring_base(), lib):
        name = pw.ref or str(pw.number)
        if pw.marker_from:
            rows.append(["Návlečka", pw.marker_from, "", pw.local_from or pw.from_text, name, pw.conductor, pw.sheet])
        if pw.marker_to:
            rows.append(["Návlečka", pw.marker_to, "", pw.local_to or pw.to_text, name, pw.conductor, pw.sheet])
    return head, rows


ALL_REPORTS = [("Data pro DS", dso_report), ("Výpočty", calculations), ("Přístroje", device_list), ("Výkaz materiálu", bom), ("Kabely", cables),
               ("Kabelový plán", cable_plan), ("Kabely a vodiče k objednání", cable_material),
               ("Zapojovací seznam", wiring_list),
               ("Výrobní zapojovací seznam", production_wiring_list), ("Značení vodičů a kabelů", marking),
               ("Svorkovnice", terminals), ("Plán svorkovnice", terminal_plan_report), ("Potenciály", potentials), ("Štítky", labels)]

# výkazy, které nejsou součástí PDF dokumentace (výrobní podklad pro dílnu) – `doc_pdf.DocBuilder.plan` je přeskočí
NOT_IN_DOC = {"Výrobní zapojovací seznam", "Kabely a vodiče k objednání", "Značení vodičů a kabelů"}

# doplňkové řádky podnadpisu výkazu v xlsx: název → fn(project, sheet) -> list[str]
REPORT_SUBTITLES = {"Výrobní zapojovací seznam": production_subtitle}
