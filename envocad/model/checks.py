"""Kontroly projektu (obdoba EPLAN „Zprávy/Check“) – čistá data, bez Qt.

Každý nález: závažnost, list, prvek/vodič, text. GUI z nich dělá seznam se skokem do výkresu.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

from envocad.model import multipole as mp
from envocad.model.advisory import ADVISORY_NOTE
from envocad.model.designation import (
    FUNC,
    LOC,
    LOCATION_SYMBOLS,
    MAX_FULL_LEN,
    Designation,
    designation,
    element_name,
    full_designation,
    scope_key,
    validate_code,
    validate_ref,
)
from envocad.model.feed import FEED_SYMBOL, feed_dir_valid, is_anchor_feed, is_feed_in, is_feed_out, raw_dir
from envocad.model.notes import OPEN_NOTE_WORDS, count_label
from envocad.model.project import (
    FEED_SYMBOLS,
    INTERRUPT_SYMBOL,
    INVERTER_SYMBOLS,
    Element,
    Project,
    Sheet,
    Waiver,
    contact_terminals,
    dangling_wires,
    element_symbol,
    is_block_only,
    is_contact,
    linked_wire,
    without_dangling,
)

ERROR, WARNING, INFO = "chyba", "varování", "info"
# prvky, u kterých nevadí nezapojený port (jde o odkazy/bloky/sběrnice s rezervou)
OPTIONAL_PORT_SYMBOLS = {"fve.switchboard", "sb.pe_bar", "sb.busbar", "fve.terminal", "sb.terminal_block",
                         "sb.junction",   # uzel odbočky: počet vodičů hlídá `junction_free`
                         "fve.tigo_cca", "fve.tigo_tap", "fve.tigo_rss"}   # komunikace Tigo: zapojení nepovinné
NO_REF_OK_SYMBOLS = {"fve.earth", "fve.grid", "fve.load", "sb.junction"}   # bez označení je v pořádku
AGGREGATED_INFO = {"no_article": "Bez artiklu / typu", "ref_syntax": "Označení s firemním oddělovačem „.“ / „-“ (přípustné jako firemní číslování)"}
NO_ARTICLE_SYMBOLS = {"fve.grid", "fve.load", "fve.earth", "fve.terminal", "fve.switchboard", FEED_SYMBOL,
                      "sb.pe_bar", "sb.busbar", "fve.pv_string", "fve.interrupt",
                      "ctl.contact_no", "ctl.contact_nc", "ctl.contact_power"}


@dataclass
class Finding:
    severity: str
    sheet_id: str
    sheet_name: str
    target_id: str          # id prvku nebo vodiče ("" = celý list/projekt)
    is_wire: bool
    ref: str
    text: str
    code: str = ""
    waived: bool = False         # potlačeno (`Waiver`) – jen s `check_project(include_waived=True)`
    waiver_reason: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        """Klíč potlačení: (kód, id prvku/vodiče nebo "" pro celý list, id listu)."""
        return (self.code, self.target_id, self.sheet_id)


def _connected_ports(sheet: Sheet, e: Element) -> set[str]:
    return {end.port for w in sheet.wires for end in (w.a, w.b) if end.element_id == e.id}


def check_project(project: Project, lib, *, standard_paper: str, include_waived: bool = False,
                  aggregate: bool = True) -> list[Finding]:
    """Kontrola projektu (F7). `standard_paper` = formát stran vícepólu z firemního standardu
    (`envocad.settings.switchboard_paper`) pro překryvy ve vícepólu – model nastavení nečte.
    Potlačené nálezy (`project.waivers`) se vynechají, s `include_waived` jsou v seznamu s `waived=True`; osiřelé
    potlačení hlásí vždy nález `waiver_orphan`. `aggregate=False` neslučuje informační nálezy po prvcích."""
    from envocad.model.xref import (
        DeviceIndex,
        has_cable_data,
        interrupt_link,
        is_continuation,
        split_cable_partner,
    )
    out: list[Finding] = []
    # vodiče na neexistující prvek: nahlásit a dál počítat bez nich (výpočty a trasy by na nich padaly)
    for s in project.sheets:
        for w in dangling_wires(s):
            out.append(Finding(ERROR, s.id, s.name, w.id, True, w.attrs.get("ref", ""),
                               "Vodič na neexistující prvek", "dangling"))
    full = project
    project = without_dangling(project)
    idx = DeviceIndex.build(project)
    # duplicitní označení: jako v EPLAN je úplné označení „=funkce+umístění-X1“ – v každém prostoru (func, loc)
    # musí být označení jedinečné, mezi umístěními se smí opakovat (X1 v +RDC1 i v +RFVE.AC). Listy se stejným
    # umístěním sdílejí prostor, list rozvaděče bez umístění má vlastní, vodiče JPS (kabely) jeden společný.
    # Prvky se stejným označením v prostoru tvoří přístroj (`xref.DeviceGroup`): smí v něm být cívka a stykač
    # (silové kontakty cívky), jinak jen jeden prvek. Kontakty a svorky se nepočítají. Přerušovací body se stejným
    # označením v prostoru jsou jedna položka (dvojice/řetěz/hvězda – mezi sebou duplicitou nejsou), kolize jejich
    # označení s přístrojem nebo vodičem téhož prostoru je ale duplicita.
    refs: Counter[tuple[str, str, str]] = Counter()      # vodiče
    irefs: set[tuple[str, str, str]] = set()             # přerušovací body
    feeds: Counter[tuple[str, str, str]] = Counter()     # přívody/vývody rozvaděče (svorkovnice X1 – jen jednou)
    for s in project.sheets:
        for w in s.wires:
            if w.attrs.get("ref"):
                refs[(*scope_key(s, w), w.attrs["ref"])] += 1
        for e in s.elements:
            if e.symbol_id == INTERRUPT_SYMBOL and e.ref:
                irefs.add((*scope_key(s, e), e.ref))
            if e.symbol_id in FEED_SYMBOLS and e.ref:
                feeds[(*scope_key(s, e), e.ref)] += 1
    for s in project.sheets:
        sym_of = {}
        for e in s.elements:
            try:
                sym = element_symbol(project, e, lib)
            except Exception:  # noqa: BLE001
                out.append(Finding(ERROR, s.id, s.name, e.id, False, e.ref, f"Neznámá značka {e.symbol_id}", "symbol"))
                continue
            sym_of[e.id] = sym
            if sym.placeholder:   # zástupná značka (symbol není v knihovně) – porty jsou jen podle vodičů
                out.append(Finding(ERROR, s.id, s.name, e.id, False, e.ref, f"Neznámá značka {e.symbol_id}", "symbol"))
                continue
            group = idx.group_of(e)
            if is_contact(e) and e.ref and group is None:
                out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                   f"Kontakt {contact_terminals(e)} bez cívky/přístroje {e.ref}", "contact_alone"))
            key = (*scope_key(s, e), e.ref)
            if group is not None and not is_contact(e) and (group.dup or refs[key] > 0 or key in irefs):
                out.append(Finding(ERROR, s.id, s.name, e.id, False, e.ref, f"Duplicitní označení {e.ref}", "dup_ref"))
            if e.symbol_id in FEED_SYMBOLS and e.ref and (feeds[key] > 1 or key in idx.groups or refs[key] > 0):
                out.append(Finding(ERROR, s.id, s.name, e.id, False, e.ref,
                                   f"Duplicitní označení {e.ref} (přívod/vývod je na listu víckrát)", "dup_ref"))
            if e.symbol_id == INTERRUPT_SYMBOL and e.ref and (key in idx.groups or refs[key] > 0):
                out.append(Finding(ERROR, s.id, s.name, e.id, False, e.ref, f"Duplicitní označení {e.ref}", "dup_ref"))
            if not e.ref and e.symbol_id not in NO_REF_OK_SYMBOLS:
                out.append(Finding(WARNING, s.id, s.name, e.id, False, "", f"Prvek {sym.name} bez označení", "no_ref"))
            conn = _connected_ports(s, e)
            if e.symbol_id in FEED_SYMBOLS and is_anchor_feed(e) and not conn:
                # kotva přívodu/vývodu bez přístrojů (list RFVE bez mustru AC části): doplní mustr / projektant
                out.append(Finding(INFO, s.id, s.name, e.id, False, e.ref,
                                   "Přívod/vývod bez zapojení v listu (kotva – AC část doplní mustr / projektant)",
                                   "feed_anchor"))
            elif e.symbol_id not in OPTIONAL_PORT_SYMBOLS:
                real = [p.name for p in sym.ports if p.name not in sym.orphan_ports]   # osiřelé hlásí bad_port
                free = [p for p in real if p not in conn]
                if e.symbol_id in INVERTER_SYMBOLS and any(p.startswith("DC") for p in conn):
                    free = [p for p in free if not p.startswith("DC")]   # volné DC vstupy střídače jsou rezerva
                if e.symbol_id in INVERTER_SYMBOLS:          # záloha a komunikace střídače jsou nepovinné
                    from envocad.model.inverter_io import inverter_io
                    optional = set(inverter_io(e.attrs, e.symbol_id == "fve.inverter_hybrid"))
                    free = [p for p in free if p not in optional]
                    if not any(p in conn for p in optional):   # zapojená jen komunikace = částečně zapojený
                        real = [p for p in real if p not in optional]
                if free and (free != real):
                    out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                       f"Nezapojené porty: {', '.join(free)}", "free_port"))
                elif free:
                    out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref, "Prvek není zapojen", "unconnected"))
            if mp.is_terminal_block(e):
                slots = sorted({c for w in s.wires for end in (w.a, w.b) if end.element_id == e.id
                                for c in mp.wire_conductors(w)}, key=mp.canon_key)
                if slots and not any(mp.terminal_numbers(e, len(slots))):
                    out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                       "Skupina svorek bez čísel (Úpravy → Očíslovat svorky)", "no_terminal_no"))
            if e.symbol_id in FEED_SYMBOLS and not feed_dir_valid(e):
                out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                   f"Neplatný směr přívodu/vývodu „{raw_dir(e)}“ (in = přívod, out = vývod) – "
                                   "bere se jako přívod", "feed_dir"))
            if (e.symbol_id in FEED_SYMBOLS and s.is_switchboard and linked_wire(project, s, e) is None
                    and not is_earthing_feed(s, e)):
                out.append(Finding(INFO, s.id, s.name, e.id, False, e.ref,
                                   "Přívod/vývod bez vazby na vodič v blokovém schématu", "feed_unlinked"))
            if (e.symbol_id not in NO_ARTICLE_SYMBOLS and not e.component_id and not e.attrs.get("type")
                    and not mp.is_terminal_block(e) and idx.is_bom_device(e)):
                out.append(Finding(INFO, s.id, s.name, e.id, False, e.ref, "Bez artiklu / typu", "no_article"))
            if e.symbol_id == INTERRUPT_SYMBOL and interrupt_link(project, s, e, idx.interrupts).mode == "alone":
                out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                   "Přerušovací bod bez protějšku (stejné označení jinde)", "interrupt_alone"))
            if e.symbol_id == "fve.switchboard" and project.switchboard_sheet(e.id) is None:
                if is_block_only(project, e):     # záměrně jen blok (porty z atributů `ports_in` / `ports_out`)
                    out.append(Finding(INFO, s.id, s.name, e.id, False, e.ref,
                                       "Rozvaděč jen jako blok bez listu (porty z atributů bloku)", "block_only"))
                else:
                    out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref, "Rozvaděč nemá list (dvojklik)",
                                       "no_sheet"))
        for w in s.wires:
            ref = w.attrs.get("ref", "")
            try:
                a, b = s.element(w.a.element_id), s.element(w.b.element_id)
            except KeyError:
                out.append(Finding(ERROR, s.id, s.name, w.id, True, ref, "Vodič na neexistující prvek", "dangling"))
                continue
            for e, end in ((a, w.a), (b, w.b)):
                sym = sym_of.get(e.id)
                if sym is not None and not sym.placeholder and (
                        end.port in sym.orphan_ports or not any(p.name == end.port for p in sym.ports)):
                    out.append(Finding(ERROR, s.id, s.name, w.id, True, ref,
                                       f"Vodič na neexistující port {element_name(e)}:{end.port}", "bad_port"))
            wkey = (*scope_key(s, w), ref)
            if ref and (refs[wkey] > 1 or wkey in idx.groups or wkey in irefs):
                out.append(Finding(ERROR, s.id, s.name, w.id, True, ref, f"Duplicitní označení {ref}", "dup_ref"))
            if not s.is_switchboard and not has_cable_data(w) \
                    and not is_continuation(project, s, w, idx.interrupts):   # pokračování kabelu přes přerušení
                out.append(Finding(INFO, s.id, s.name, w.id, True, ref, "Vodič bez typu kabelu / průřezu", "no_cable"))
            # typ/průřez na obou úsecích přes dvojici přerušení (samotné auto označení „W12“ se nepočítá)
            hit = None if s.is_switchboard else split_cable_partner(project, s, w, idx.interrupts)
            if hit is not None and (project.sheets.index(hit[0]), hit[1].id) > (project.sheets.index(s), w.id):
                # hlásí se jednou za dvojici úseků (u úseku na dřívějším listu)
                out.append(Finding(WARNING, s.id, s.name, w.id, True, ref,
                                   f"Údaje kabelu na obou úsecích přes přerušení (i {hit[1].attrs.get('ref') or 'vodič'}"
                                   f" na listu {hit[0].name}) – kabel se ve výkazech zdvojí; nech je jen na jednom úseku",
                                   "cable_split"))
            if not w.conductors:
                out.append(Finding(INFO, s.id, s.name, w.id, True, ref, "Vodič bez žil (vícepól ho kreslí jako L1)", "no_cond"))
        if s.is_switchboard and (not s.parent_element_id or project.sheet_of_element(s.parent_element_id) is None):
            out.append(Finding(WARNING, s.id, s.name, "", False, s.loc,
                               "List rozvaděče bez bloku ROZVADĚČ v blokovém schématu (blok smazán?) – "
                               "vlož blok a propoj ho s listem, nebo list odstraň", "sb_no_block"))
        # můstky na neexistující svorky
        terms = set()
        for e in s.elements:
            if mp.is_terminal_block(e):
                n_slots = len({c for w in s.wires for end in (w.a, w.b) if end.element_id == e.id
                               for c in mp.wire_conductors(w)}) or 1
                terms |= {(e.ref, n) for n in mp.terminal_numbers(e, n_slots) if n}
        strips = {e.ref for e in s.elements if mp.is_terminal_block(e)}
        for strip in strips:
            for g in project.bridge_groups(strip, s):
                missing = [n for n in g if (strip, n) not in terms]
                if missing:
                    out.append(Finding(WARNING, s.id, s.name, "", False, strip,
                                       f"Můstek {strip}:{'-'.join(g)} odkazuje na neexistující svorky {', '.join(missing)}",
                                       "bridge_missing"))
    out += layout_findings(project, lib)
    out += contact_findings(project, idx)
    out += interrupt_findings(project, idx)
    out += spd_findings(project)
    out += protection_findings(project, lib)
    out += chain_findings(project, lib)
    out += designation_findings(project, lib, idx)
    out += revision_findings(full)
    out += note_findings(full)
    out += cable_findings(full)
    out += calc_findings(project, lib)
    out += rating_findings(project, lib)
    out += battery_findings(project, lib)
    out += thermal_findings(project, lib)
    out += potential_findings(project, lib)
    out += text_findings(project, lib, standard_paper=standard_paper)
    out = apply_waivers(out, full)
    waived = [f for f in out if f.waived]
    out = [f for f in out if not f.waived]
    if aggregate:
        out = aggregate_info(out)
    if include_waived:
        out += waived
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    out.sort(key=lambda f: (order[f.severity], f.sheet_name, f.ref))
    return out


def apply_waivers(findings: list[Finding], project: Project) -> list[Finding]:
    """Označí nálezy potlačené `project.waivers` (`waived=True` + důvod; jedno potlačení kryje všechny nálezy se
    stejným klíčem) a přidá nález `waiver_orphan` za každé potlačení, ke kterému žádný nález nevznikl. Nález
    `waiver_orphan` potlačit nelze."""
    by_key = {w.key: w for w in project.waivers if w.code != "waiver_orphan"}
    out = [replace(f, waived=True, waiver_reason=by_key[f.key].reason)
           if f.code != "waiver_orphan" and f.key in by_key else f for f in findings]
    seen = {f.key for f in findings}
    out += [_orphan_finding(project, w) for w in project.waivers if w.key not in seen]
    return out


def _orphan_finding(project: Project, w: Waiver) -> Finding:
    sheet = next((s for s in project.sheets if s.id == w.sheet_id), None)
    target_id, is_wire, ref = "", False, w.ref
    if sheet is not None and w.target_id:
        e = next((x for x in sheet.elements if x.id == w.target_id), None)
        wire = next((x for x in sheet.wires if x.id == w.target_id), None)
        if e is not None:
            target_id, ref = e.id, e.ref or w.ref
        elif wire is not None:
            target_id, is_wire, ref = wire.id, True, wire.attrs.get("ref") or w.ref
    why = ("nález už nevzniká" if target_id or not w.target_id else "prvek/vodič už neexistuje")
    return Finding(INFO, sheet.id if sheet else "", sheet.name if sheet else "", target_id, is_wire, ref,
                   f"Potlačení nálezu {w.code} je osiřelé – {why} (důvod: {w.reason})", "waiver_orphan")


def is_earthing_feed(sheet: Sheet, e: Element) -> bool:
    """Vývod jen s PE (XPE → ekvipotenciální svorkovnice HOP): uzemnění rozvaděče, ve schématu JPS obvykle bez
    vodiče – chybějící vazbu na JPS kontrola nehlásí."""
    if not is_feed_out(e):
        return False
    conds = [w.conductors for w in sheet.wires if w.touches(e.id)]
    return bool(conds) and all(c and set(c) <= {"PE", "PEN"} for c in conds)


def aggregate_info(findings: list[Finding], max_refs: int = 8) -> list[Finding]:
    """Informační nálezy, kterých bývá hodně (`AGGREGATED_INFO`: bez artiklu, označení mimo konvenci), sloučí do
    jedné položky na list s počtem a výčtem označení („Bez artiklu / typu: 12 prvků (F1, F2, …)“). Skok z položky
    vede na list (první prvek)."""
    out: list[Finding] = []
    groups: dict[tuple[str, str], list[Finding]] = {}
    for f in findings:
        if f.severity == INFO and f.code in AGGREGATED_INFO:
            groups.setdefault((f.code, f.sheet_id), []).append(f)
        else:
            out.append(f)
    for (code, _sid), fs in groups.items():
        if len(fs) == 1:
            out.append(fs[0])
            continue
        refs = sorted({f.ref for f in fs if f.ref}, key=_natural)
        shown = ", ".join(refs[:max_refs]) + (", …" if len(refs) > max_refs else "")
        f0 = fs[0]
        out.append(Finding(INFO, f0.sheet_id, f0.sheet_name, f0.target_id, f0.is_wire, "",
                           f"{AGGREGATED_INFO[code]}: {count_label(len(fs), ('prvek', 'prvky', 'prvků'))}"
                           + (f" ({shown})" if shown else ""), code))
    return out


def _natural(ref: str) -> tuple:
    import re
    return tuple((0, int(t)) if t.isdigit() else (1, t) for t in re.findall(r"\d+|\D+", ref))


LAYOUT_EPS = 1e-6   # tolerance součtu modulů (desetinné šířky svorek)


@dataclass
class LayoutProblem:
    """Problém rozložení řady: `layout_overflow` (součet modulů řady > modulů v řadě, přístroj za koncem řady)
    nebo `layout_overlap` (dva přístroje v řadě se překrývají). `element` = přístroj (u součtu řady None)."""
    code: str
    row: int
    element: Element | None
    text: str


def _m(v: float) -> str:
    return f"{round(v, 2):g}".replace(".", ",")


def layout_problems(sheet: Sheet, project: Project | None = None, layout=None, lib=None) -> list[LayoutProblem]:
    """Přetečení a překryvy v řadách rozložení listu rozvaděče (jen přístroje rozložení – `Layout.devices`, bez
    kontaktů – umístěné v řadách skříně). Zmenšení počtu modulů v řadě umístění nemaže; přístroje za koncem řady
    hlásí tato kontrola. `layout` = rozpracovaná kopie (dialog skříně), jinak `sheet.layout`. S knihovnou `lib`
    šířky i z artiklů (`device_size`); rozměry proti řadě a skříni `device_size.size_problems`."""
    from envocad.model.device_size import device_modules, memo_lib
    lay = layout if layout is not None else sheet.layout
    lib = memo_lib(lib)
    devs = lay.devices(sheet, project, lib)
    rows: dict[int, list[tuple[float, float, Element]]] = {}
    for e in devs:
        pl = lay.placement(e.id)
        if pl is not None:
            rows.setdefault(pl.row, []).append((pl.pos, pl.pos + device_modules(e, lib), e))
    out: list[LayoutProblem] = []
    cap = lay.modules_per_row
    for r in sorted(rows):
        items = sorted(rows[r], key=lambda t: (t[0], t[1]))
        total = sum(b - a for a, b, _ in items)
        if total > cap + LAYOUT_EPS:
            out.append(LayoutProblem("layout_overflow", r, None,
                                     f"Řada {r + 1} je přeplněná: přístroje zabírají {_m(total)} M, řada má {cap} M"))
        for a, b, e in items:
            if b > cap + LAYOUT_EPS:
                out.append(LayoutProblem("layout_overflow", r, e,
                                         f"Přístroj v řadě {r + 1} přesahuje konec řady (pozice {_m(a)}–{_m(b)} M, "
                                         f"řada má {cap} M)"))
        for i, (a1, b1, e1) in enumerate(items):
            for a2, b2, e2 in items[i + 1:]:
                if a2 >= b1 - LAYOUT_EPS:
                    break
                out.append(LayoutProblem("layout_overlap", r, e2,
                                         f"Přístroj v řadě {r + 1} se překrývá s {element_name(e1)} "
                                         f"({_m(a2)}–{_m(b2)} M × {_m(a1)}–{_m(b1)} M)"))
    return out


def layout_findings(project: Project, lib=None) -> list[Finding]:
    """Rozložení rozvaděče: přístroj s uloženým umístěním v řadě mimo skříň (po zmenšení počtu řad) – WARNING
    `outside_enclosure`; rozložení ho kreslí mezi nerozmístěnými, po zvětšení počtu řad se umístění vrátí.
    Přetečení řady a překryvy přístrojů (`layout_problems`) – WARNING `layout_overflow` / `layout_overlap`.
    Rozměry z artiklu / atributů (`device_size.size_problems`) – WARNING `layout_height` / `layout_enclosure` /
    `layout_depth`. Artikl můstku (`bridges.bridge_findings`) – WARNING `bridge_article`."""
    from envocad.model.device_size import memo_lib, size_problems
    lib = memo_lib(lib)
    out: list[Finding] = []
    for s in project.sheets:
        if not s.is_switchboard:
            continue
        lay = s.layout
        by_id = {e.id: e for e in s.elements}
        for pl in lay.outside_placements():
            e = by_id.get(pl.element_id)
            if e is None:
                continue
            out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                               f"Přístroj je umístěn v řadě {pl.row + 1} mimo skříň (skříň má {lay.rows} řad) "
                               "– v rozložení je mezi nerozmístěnými", "outside_enclosure"))
        for pr in layout_problems(s, project, lib=lib):
            e = pr.element
            out.append(Finding(WARNING, s.id, s.name, e.id if e else "", False, e.ref if e else "", pr.text, pr.code))
        for sp in size_problems(s, project, lib):
            out.append(Finding(WARNING, s.id, s.name, sp.element.id, False, sp.element.ref, sp.text, sp.code))
    from envocad.model.bridges import bridge_findings
    out += bridge_findings(project, lib)      # artikl můstku (`bridge_id`): neznámý, není můstek, málo pólů
    return out


def revision_findings(project: Project) -> list[Finding]:
    """Měkký zámek revize: list změněný po uzavření (otisk se liší) a změna ještě není v nové revizi."""
    from envocad.model.revision import changed_after_close
    return [Finding(WARNING, s.id, s.name, "", False, "",
                    f"List změněn po uzavření revize {rev.label} – porovnej s revizí a založ novou", "rev_closed_changed")
            for s, rev in changed_after_close(project)]


def note_findings(project: Project) -> list[Finding]:
    """Připomínky: INFO `note_open` jednou za list s otevřenými připomínkami, INFO `note_orphan` pro připomínky na
    smazaném listu (jinak by v editoru nebyly vidět)."""
    out: list[Finding] = []
    for s in project.sheets:
        n = sum(1 for x in project.notes if x.sheet_id == s.id and x.status == "open")
        if n:
            out.append(Finding(INFO, s.id, s.name, "", False, "", count_label(n, OPEN_NOTE_WORDS), "note_open"))
    sheet_ids = {s.id for s in project.sheets}
    for x in project.notes:
        if x.sheet_id not in sheet_ids:
            out.append(Finding(INFO, "", "", "", False, f"č. {x.no}",
                               f"Připomínka č. {x.no} je na smazaném listu: {x.text[:60]}", "note_orphan"))
    return out


def _sev(issue) -> str:
    return ERROR if issue.error else (INFO if issue.info else WARNING)


def _aspect_word(aspect: str) -> str:
    return "Funkce" if aspect == FUNC else "Umístění"


def designation_findings(project: Project, lib, index=None) -> list[Finding]:
    """Strukturní označení (IEC 81346): syntaxe a třída označení prvků a vodičů, kódy funkce/umístění,
    umístění listů rozvaděčů, kontakty s cívkami ve více umístěních."""
    out: list[Finding] = []
    registered = {(x.aspect, x.code) for x in project.structures}
    # registr struktur
    for x in project.structures:
        for i in validate_code(x.code, x.aspect, "v seznamu struktur"):
            out.append(Finding(_sev(i), "", "", "", False, x.code, i.text, i.code))

    def code_findings(s: Sheet, aspect: str, code: str, target_id: str, ref: str, where: str,
                      reported: set[tuple[str, str]]) -> None:
        if not code:
            return
        for i in validate_code(code, aspect, where):
            out.append(Finding(_sev(i), s.id, s.name, target_id, False, ref, i.text, i.code))
        if (aspect, code) not in registered and (aspect, code) not in reported:
            reported.add((aspect, code))
            out.append(Finding(INFO, s.id, s.name, target_id, False, ref,
                               f"{_aspect_word(aspect)} {aspect}{code} není v seznamu struktur projektu",
                               "struct_undefined"))

    for s in project.sheets:
        reported: set[tuple[str, str]] = set()     # struct_undefined jen jednou za kód a list
        code_findings(s, FUNC, s.func, "", "", f"listu {s.name}", reported)
        code_findings(s, LOC, s.loc, "", "", f"listu {s.name}", reported)
        if s.is_switchboard:
            if not s.loc:
                out.append(Finding(WARNING, s.id, s.name, "", False, "", "List rozvaděče nemá umístění (+)", "sb_no_loc"))
            ps = project.sheet_of_element(s.parent_element_id) if s.parent_element_id else None
            block = ps.element(s.parent_element_id) if ps is not None else None
            if s.loc and block is not None and block.ref and block.ref != s.loc:
                out.append(Finding(INFO, s.id, s.name, "", False, s.loc,
                                   f"Umístění listu +{s.loc} se liší od označení bloku {block.ref}", "loc_mismatch"))
        for e in s.elements:
            code_findings(s, FUNC, e.attrs.get("func", ""), e.id, e.ref, f"prvku {element_name(e)}", reported)
            code_findings(s, LOC, e.attrs.get("loc", ""), e.id, e.ref, f"prvku {element_name(e)}", reported)
            if not e.ref or is_contact(e) or e.symbol_id == INTERRUPT_SYMBOL:
                continue
            try:
                sym = element_symbol(project, e, lib)
            except Exception:  # noqa: BLE001, S112 – neznámou značku hlásí check_project
                continue
            location = e.symbol_id in LOCATION_SYMBOLS
            classes = sym.classes
            if not (location or classes or mp.is_terminal_block(e)):
                continue
            issues = validate_ref(e.ref, None if location else classes, name=sym.name)
            for i in issues:
                out.append(Finding(_sev(i), s.id, s.name, e.id, False, e.ref, i.text, i.code))
            full = full_designation(project, s, e)
            if len(full) > MAX_FULL_LEN and not any(i.error for i in issues):
                out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                   f"Plné označení {full} přesahuje {MAX_FULL_LEN} znaků (štítek)", "ref_length"))
        for w in s.wires:
            ref = w.attrs.get("ref", "")
            issues = validate_ref(ref, None, is_wire=True)
            for i in issues:
                out.append(Finding(_sev(i), s.id, s.name, w.id, True, ref, i.text, i.code))
    out += _contact_findings(project, index)
    return out


def _place_text(project: Project, s: Sheet, e: Element) -> str:
    d = designation(s, e)
    if s.is_switchboard and not d.loc:
        return s.name                     # anonymní rozvaděč – bez kódu, jen název listu
    return Designation(d.func, d.loc).aspects or "(bez umístění)"


def _contact_findings(project: Project, index=None) -> list[Finding]:
    """Kontakt se páruje s přístrojem podle `ref` (napříč projektem, `xref.DeviceIndex`). Má-li stejné označení víc
    přístrojů v různých prostorech (K1 v +RDC1 i v +RFVE.AC), přednost má ten ve stejném prostoru označení (funkce,
    umístění) jako kontakt. Nejednoznačné je to, jen když v prostoru kontaktu žádný z nich není."""
    from envocad.model.xref import DeviceIndex
    idx = index or DeviceIndex.build(project)
    out: list[Finding] = []
    for s in project.sheets:
        for c in s.elements:
            if not (is_contact(c) and c.ref):
                continue
            groups = idx.by_ref.get(c.ref, [])
            if len(groups) < 2 or (*scope_key(s, c), c.ref) in idx.groups:
                continue
            places = sorted({_place_text(project, *g.host) for g in groups})
            out.append(Finding(WARNING, s.id, s.name, c.id, False, c.ref,
                               f"Kontakt {c.ref} odpovídá cívkám ve více umístěních ({', '.join(places)}) – "
                               "nastav kontaktu umístění", "contact_ambiguous"))
    return out


def contact_findings(project: Project, index=None) -> list[Finding]:
    """Kontakty přístroje: stejný pár svorek dvakrát (`contact_dup`), víc kontaktů druhu než v kontaktním obrazu
    (`contact_count`), pár mimo obraz (`contact_unknown`), nečitelný obraz (`contact_image_syntax`)."""
    from envocad.model.xref import KIND_WORD, DeviceIndex, contact_image, count_words, parse_contact_image
    idx = index or DeviceIndex.build(project)
    out: list[Finding] = []
    for s in project.sheets:
        for e in s.elements:
            text = e.attrs.get("contacts", "")
            if text and text.strip():
                _slots, bad = parse_contact_image(text)
                if bad:
                    out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                       f"Kontaktní obraz {e.ref}: nečitelné {', '.join(bad)} (páry 13/14, 21/22, 1/2 "
                                       "nebo s předponou NO:/NC:)", "contact_image_syntax"))
    for g in idx.groups.values():
        items = g.contact_items()
        if not items:
            continue
        seen: dict[str, Element] = {}
        for (s, c), _kind, pairs in items:
            for pair in pairs:
                if pair in seen:
                    out.append(Finding(WARNING, s.id, s.name, c.id, False, c.ref,
                                       f"{g.ref}: svorky {pair} jsou u více kontaktů", "contact_dup"))
                else:
                    seen[pair] = c
        image = contact_image(g)
        if image is None:
            continue
        known = {slot.pair for slot in image}
        for (s, c), _kind, pairs in items:
            for pair in pairs:
                if pair not in known:
                    out.append(Finding(WARNING, s.id, s.name, c.id, False, c.ref,
                                       f"Kontakt {pair} není v kontaktním obrazu {g.ref}", "contact_unknown"))
        hs, h = g.host
        for kind in KIND_WORD:
            used = sum(len(pairs) for _, k, pairs in items if k == kind)
            have = sum(1 for slot in image if slot.kind == kind)
            if used > have:
                out.append(Finding(WARNING, hs.id, hs.name, h.id, False, g.ref,
                                   f"{g.ref}: {count_words(used, kind)}, kontaktní obraz má {have}", "contact_count"))
    return out


SPD_SWITCHES = {"fve.dc_disconnect", "fve.fuse_disconnect", "fve.switch_disconnector", "sb.main_switch"}
SPD_SOURCES = {"fve.pv_string"}   # + přívod (`is_feed_in`)


def spd_findings(project: Project) -> list[Finding]:
    """Svodič připojený na svorky odpínače na straně stringu (tam, kam vede i přívod od stringu): vypnutý odpínač
    by SPD neodpojil – SPD patří na výstupní svorky (strana střídače), dvojitou dutinkou s vývodem."""
    out = []
    for s in project.sheets:
        by_id = {e.id: e for e in s.elements}
        at: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for w in s.wires:
            at.setdefault((w.a.element_id, w.a.port), []).append((w.b.element_id, w.b.port))
            at.setdefault((w.b.element_id, w.b.port), []).append((w.a.element_id, w.a.port))
        for e in s.elements:
            if e.symbol_id != "fve.spd":
                continue
            for oid, oport in at.get((e.id, "L"), []):
                d = by_id.get(oid)
                if d is None or d.symbol_id not in SPD_SWITCHES:
                    continue
                if any(by_id.get(x) is not None and (by_id[x].symbol_id in SPD_SOURCES or is_feed_in(by_id[x]))
                       for x, _p in at.get((oid, oport), [])):
                    out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                       f"SPD na svorkách {d.ref}:{oport} na straně stringu – vypnutý {d.ref} ho "
                                       "neodpojí; připoj na výstupní svorky (strana střídače)", "spd_side"))
    return out


PROTECTION_SYMBOLS = {"fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo", "fve.fuse", "fve.fuse_disconnect"}
FUSE_SYMBOLS = {"fve.fuse", "fve.fuse_disconnect"}
IN_UNRESOLVED = "in_unresolved"   # nepovinný atribut: generátor In nedosadil, protože nic nevyhovělo (hodnota = důvod)


def _num_attr(v) -> float | None:
    try:
        return float(str(v).replace(",", ".").split()[0])
    except (TypeError, ValueError, IndexError):
        return None


def protection_findings(project: Project, lib=None) -> list[Finding]:
    """Jistič / pojistka v rozvaděči bez In → WARNING „… bez In – doplňte“ (`fuse_no_in` / `breaker_no_in`).
    ERROR jen tam, kde In nechal prázdné generátor, protože nic nevyhovělo (atribut `in_unresolved` s důvodem –
    pojistka stringu, na kterou nevyhoví žádná velikost gPV; vývod HR bez selektivního jističe, který unese proud
    FVE) – hláška pak nese důvod. Pojistka s artiklem držáku (kategorie fuse_holder, `lib`) a In vložky nad
    `in_max_a` držáku → ERROR `fuse_over_holder`."""
    out: list[Finding] = []
    for s in project.sheets:
        if not s.is_switchboard:
            # blokové schéma: pojistky HDS (stávající přípojková skříň) bez In – jen informace (údaj stávající
            # skříně projektant často nezná; selektivita s pojistkami HDS se pak nehodnotí)
            for e in s.elements:
                if e.symbol_id == "fve.hds" and not str(e.attrs.get("in_") or "").strip():
                    out.append(Finding(INFO, s.id, s.name, e.id, False, e.ref,
                                       "Pojistky HDS bez In – doplňte, je-li známé (selektivita s HDS se nehodnotí)",
                                       "hds_no_in"))
            continue
        for e in s.elements:
            if e.symbol_id not in PROTECTION_SYMBOLS:
                # jiný přístroj, kterému generátor In nedosadil (stávající hlavní vypínač RD s neznámým In)
                why = str(e.attrs.get(IN_UNRESOLVED) or "").strip()
                if why and not str(e.attrs.get("in_") or "").strip():
                    out.append(Finding(ERROR, s.id, s.name, e.id, False, e.ref,
                                       f"Přístroj bez In – generátor nenašel vyhovující hodnotu: {why}; zvolte ručně",
                                       "breaker_no_in"))
                continue
            fuse = e.symbol_id in FUSE_SYMBOLS
            code = "fuse_no_in" if fuse else "breaker_no_in"
            what = "Pojistka" if fuse else "Jistič"
            in_ = str(e.attrs.get("in_") or "").strip()
            if not in_:
                why = str(e.attrs.get(IN_UNRESOLVED) or "").strip()
                if why:
                    out.append(Finding(ERROR, s.id, s.name, e.id, False, e.ref,
                                       f"{what} bez In – generátor nenašel vyhovující hodnotu: {why}; zvolte ručně",
                                       code))
                else:
                    out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref, f"{what} bez In – doplňte", code))
                continue
            if fuse and lib is not None and e.component_id and hasattr(lib, "component"):
                try:
                    comp = lib.component(e.component_id)
                except Exception:  # noqa: BLE001 – knihovna nedostupná → bez kontroly držáku
                    comp = None
                if comp is None or getattr(comp, "category", "") != "fuse_holder":
                    continue
                max_in, val = comp.num("in_max_a"), _num_attr(in_)
                if max_in and val is not None and val > max_in + 1e-9:
                    out.append(Finding(ERROR, s.id, s.name, e.id, False, e.ref,
                                       f"In vložky {in_} A > max. In držáku {max_in:g} A ({comp.part_number}) – "
                                       "zvolte menší vložku nebo větší držák", "fuse_over_holder"))
    return out


GRID_PROTECTION_KWP = 30.0      # výchozí hranice síťové ochrany (instalovaný výkon DC, kWp)
GRID_PROTECTION_SYMBOL = "fve.grid_protection"
CHANGEOVER_SYMBOL = "fve.changeover_switch"
FVE_FUSE_MAX_BREAKER_IN = 80.0  # vývod FVE do 80 A včetně vždy jistič


def chain_findings(project: Project, lib) -> list[Finding]:
    """Řetězec FVE (F2): selektivita přes listy (`calc.check_selectivity_tree`, `chain_selectivity`), pojistkový
    vývod FVE do 80 A (`fve_out_fuse_le80`), chybějící síťová ochrana nad hranicí kWp (`grid_protection_missing` –
    `meta["p_installed_kwp"]` nad `meta["grid_protection_kwp"]`, výchozí 30; požadavek zapsaný na bloku rozvaděče bez
    listu `grid_protection` stačí – AC rozvaděč dodá mustr), síťová ochrana bez vazebního prvku s vypínací spouští /
    s nejištěným měřicím vstupem U (`grid_protection_trip`, `grid_protection_u`) a EPS vývod hybridního střídače,
    který nevede na přepínač sítí (`eps_unconnected`). Kódy běží jen nad přístroji, které v projektu jsou (blok bez
    listu nic nehlásí). Varování; hodnoty se nepřepisují."""
    from envocad.model import calc
    out: list[Finding] = []
    for c in calc.check_selectivity_tree(project, lib):
        out.append(Finding(WARNING, c.sheet.id, c.sheet.name, c.element.id, False, c.element.ref,
                           f"Selektivita v řetězci: {c.msg}", "chain_selectivity"))
    for s in project.sheets:
        for e in s.elements:
            if str(e.attrs.get("chain") or "") == "fve_out" and e.symbol_id in FUSE_SYMBOLS:
                v = _num_attr(e.attrs.get("in_"))
                if v is not None and v <= FVE_FUSE_MAX_BREAKER_IN:
                    out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                       f"Vývod FVE {v:g} A pojistkou – do {FVE_FUSE_MAX_BREAKER_IN:g} A vždy jistič",
                                       "fve_out_fuse_le80"))
    kwp = _num_attr(project.meta.get("p_installed_kwp"))
    limit = _num_attr(project.meta.get("grid_protection_kwp")) or GRID_PROTECTION_KWP
    if kwp is not None and kwp > limit + 1e-9 and not any(
            e.symbol_id == GRID_PROTECTION_SYMBOL or _protection_required_on_block(project, e)
            for s in project.sheets for e in s.elements):
        out.append(Finding(WARNING, "", "", "", False, "",
                           f"Instalovaný výkon {kwp:g} kWp > {limit:g} kWp a v projektu chybí síťová ochrana "
                           f"({GRID_PROTECTION_SYMBOL})", "grid_protection_missing"))
    out += _grid_protection_findings(project)
    out += _eps_findings(project)
    out += tigo_findings(project)
    return out


def battery_findings(project: Project, lib) -> list[Finding]:
    """Katalogová baterie na svorce BAT střídače z katalogu, která k němu podle datasheetu baterie nepasuje
    (`library.batteries.compatible`: vzory `inv_compat`, bez nich stejný výrobce) – varování `battery_incompatible`."""
    from envocad.library.batteries import compatible
    out: list[Finding] = []
    comp = getattr(lib, "component", None)
    if comp is None:
        return out
    for s in project.sheets:
        by_id = {e.id: e for e in s.elements}
        for w in s.wires:
            for bat_end, inv_end in ((w.a, w.b), (w.b, w.a)):
                bat, inv = by_id.get(bat_end.element_id), by_id.get(inv_end.element_id)
                if bat is None or inv is None or bat.symbol_id != "fve.battery" or inv_end.port != "BAT":
                    continue
                cb = comp(bat.component_id) if bat.component_id else None
                ci = comp(inv.component_id) if inv.component_id else None
                if cb is None or ci is None or cb.category != "battery" or not ci.category.startswith("inverter"):
                    continue
                if not compatible(cb, ci):
                    out.append(Finding(WARNING, s.id, s.name, bat.id, False, bat.ref,
                                       f"Baterie {cb.part_number} nepasuje ke střídači {inv.ref} ({ci.part_number}) "
                                       "podle datasheetu baterie – ověřte kompatibilitu", "battery_incompatible"))
    return out


TIGO_RSS, TIGO_CCA, TIGO_TAP = "fve.tigo_rss", "fve.tigo_cca", "fve.tigo_tap"


def is_tigo_string(e: Element) -> bool:
    """String s optimizéry Tigo: výrobce optimizéru z artiklu (`opt_manufacturer`), jinak typ řady TS4…"""
    if e.symbol_id != "fve.pv_string":
        return False
    mfr = str(e.attrs.get("opt_manufacturer") or "").strip().lower()
    return mfr == "tigo" or (not mfr and str(e.attrs.get("optimizer") or "").strip().upper().startswith("TS4"))


def tigo_findings(project: Project) -> list[Finding]:
    """Optimizéry Tigo potřebují signál: v projektu musí být vysílač RSS (`fve.tigo_rss`) nebo řídicí jednotka CCA
    (`fve.tigo_cca`) – jinak varování `tigo_missing` u prvního stringu s Tigo. CCA bez přístupového bodu TAP
    (`fve.tigo_tap`) nekomunikuje s optimizéry – varování `tigo_tap_missing`."""
    els = [(s, e) for s in project.sheets for e in s.elements]
    tigo = [(s, e) for s, e in els if is_tigo_string(e)]
    syms = {e.symbol_id for _s, e in els}
    out: list[Finding] = []
    if tigo and not syms & {TIGO_RSS, TIGO_CCA}:
        s, e = tigo[0]
        refs = ", ".join(x.ref for _s, x in tigo[:5] if x.ref) + ("…" if len(tigo) > 5 else "")
        out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                           f"Optimizéry Tigo ({refs}) bez vysílače RSS ani CCA – bez signálu optimizéry moduly "
                           "odpojí; vložte blok Tigo RSS vysílač nebo Tigo CCA + TAP", "tigo_missing"))
    if TIGO_CCA in syms and TIGO_TAP not in syms:
        s, e = next((s, e) for s, e in els if e.symbol_id == TIGO_CCA)
        out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                           "Tigo CCA bez přístupového bodu TAP – CCA s optimizéry komunikuje jen přes TAP",
                           "tigo_tap_missing"))
    return out


def _protection_required_on_block(project: Project, e: Element) -> bool:
    """Požadavek síťové ochrany na bloku rozvaděče, jehož AC část není nakreslená (blok bez listu, nebo list jen
    s kotvami AC části – RFVE rodinného domu bez mustru): AC rozvaděč dodá mustr / projektant."""
    if e.symbol_id != "fve.switchboard" or not grid_protection_required(e):
        return False
    sb = project.switchboard_sheet(e.id)
    return is_block_only(project, e) or (sb is not None and any(is_anchor_feed(f) for f in sb.elements))


def grid_protection_required(e: Element) -> bool:
    """Blok rozvaděče nese požadavek síťové ochrany (`grid_protection` neprázdné a ne „0“ / „ne“)."""
    v = str(e.attrs.get("grid_protection") or "").strip().lower()
    return bool(v) and v not in ("0", "ne", "no", "false")


TRIP_ATTR = "trip"   # vypínací spoušť vazebního prvku (síťová ochrana na něj působí) – neprázdné = má


def _grid_protection_findings(project: Project) -> list[Finding]:
    """Síťová ochrana (`fve.grid_protection`) – požadavek na mustr (docs/design/topologie_f1_f2.md, kap. 3): prvek,
    na který působí (`acts_on`, vazební prvek), má vypínací spoušť (atribut `trip`), a měřicí vstup U je jištěný
    (na portu U vodič k jističi / pojistce). Ochrana bez `acts_on` se nehodnotí (ruční výkres)."""
    out: list[Finding] = []
    for s in project.sheets:
        by_id = {e.id: e for e in s.elements}
        for e in s.elements:
            if e.symbol_id != GRID_PROTECTION_SYMBOL:
                continue
            target = str(e.attrs.get("acts_on") or "").strip()
            dev = next((x for x in s.elements if target and x.ref == target and x.id != e.id), None)
            if dev is not None and not str(dev.attrs.get(TRIP_ATTR) or "").strip():
                out.append(Finding(WARNING, s.id, s.name, dev.id, False, dev.ref,
                                   f"Vazební prvek {dev.ref} síťové ochrany {e.ref} bez vypínací spouště "
                                   "(atribut trip)", "grid_protection_trip"))
            u = [by_id.get(w.b.element_id if w.a.element_id == e.id else w.a.element_id) for w in s.wires
                 if any(end.element_id == e.id and end.port == "U" for end in (w.a, w.b))]
            if u and not any(x is not None and x.symbol_id in PROTECTION_SYMBOLS for x in u):
                out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                   f"Měřicí vstup U síťové ochrany {e.ref} není jištěný (jistič / pojistka před "
                                   "vstupem)", "grid_protection_u"))
    return out


def _eps_findings(project: Project) -> list[Finding]:
    """Hybridní střídač s baterií a EPS vývodem, který podle generátoru vede na přepínač sítí (`eps="1"`, rodinný
    dům): vodič z BACKUP musí vést (přes přívod / vývod rozvaděče a svorky) na přepínač sítí – jinak varování
    `eps_unconnected`. Vede-li do listu, kde AC část ještě není (kotva `anchor`, blok bez listu), jen INFO
    `eps_open`. Ruční projekt (bez `eps`): zapojený BACKUP bez přepínače je jen INFO."""
    out: list[Finding] = []
    by_id = {e.id: (s, e) for s in project.sheets for e in s.elements}

    def reaches_changeover(start: tuple[str, str]) -> str:
        """„ok“ (přepínač), „open“ (kotva / blok bez listu – AC část chybí), „no“."""
        seen = {start, (start[0], "*")}          # zpět přes střídač (AC strana) se nehledá
        todo = [start]
        open_ = False
        while todo:
            eid, port = todo.pop()
            s, e = by_id[eid]
            if e.symbol_id == CHANGEOVER_SYMBOL:
                return "ok"
            if is_anchor_feed(e) and not any(w.touches(e.id) for w in s.wires if s.is_switchboard):
                open_ = True
            nxt: list[tuple[str, str]] = []
            for w in s.wires:
                for a, b in ((w.a, w.b), (w.b, w.a)):
                    if a.element_id == eid and (port == "*" or a.port == port) and b.element_id in by_id:
                        # do bloku rozvaděče konkrétním portem (přívod listu), jinak přes všechny porty prvku
                        nxt.append((b.element_id, b.port if by_id[b.element_id][1].symbol_id == "fve.switchboard"
                                    else "*"))
            if e.symbol_id == INTERRUPT_SYMBOL and e.ref:   # pár přerušovacích bodů = jeden vodič
                nxt += [(x.id, "*") for _s2, x in by_id.values() if x.symbol_id == INTERRUPT_SYMBOL
                        and x.ref == e.ref and x.id != e.id]
            if e.symbol_id == "fve.switchboard":       # blok: port bloku → přívod / vývod listu rozvaděče
                sb = project.switchboard_sheet(e.id)
                if sb is None and is_block_only(project, e):
                    open_ = True
                for f in (sb.elements if sb is not None else []):
                    if f.ref == port:
                        nxt.append((f.id, "*"))
            for k in nxt:
                if k not in seen and len(seen) < 200:
                    seen.add(k)
                    todo.append(k)
        return "open" if open_ else "no"

    for s in project.sheets:
        for e in s.elements:
            if e.symbol_id != "fve.inverter_hybrid":
                continue
            battery = any(w.touches(e.id) and any(by_id.get(x, (None, None))[1] is not None
                                                  and by_id[x][1].symbol_id == "fve.battery"
                                                  for x in (w.a.element_id, w.b.element_id)) for w in s.wires)
            wired = [w for w in s.wires if any(end.element_id == e.id and end.port == "BACKUP" for end in (w.a, w.b))]
            expected = str(e.attrs.get("eps") or "") == "1"
            if not battery or not (wired or expected):
                continue
            state = reaches_changeover((e.id, "BACKUP")) if wired else "no"
            if state == "ok":
                continue
            if expected and state == "no":
                out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                   f"EPS vývod (BACKUP) hybridního střídače {e.ref} s baterií nevede na přepínač sítí",
                                   "eps_unconnected"))
            elif expected:
                out.append(Finding(INFO, s.id, s.name, e.id, False, e.ref,
                                   f"EPS vývod (BACKUP) střídače {e.ref} vede do rozvaděče bez AC části – přepínač sítí "
                                   "doplní mustr / projektant", "eps_open"))
            else:
                out.append(Finding(INFO, s.id, s.name, e.id, False, e.ref,
                                   f"EPS vývod (BACKUP) střídače {e.ref} nevede na přepínač sítí", "eps_unconnected"))
    return out


def interrupt_findings(project: Project, index=None) -> list[Finding]:
    """Přerušovací body: víc zdrojů hvězdy ve skupině (`interrupt_star_multi`) – zdrojem je jen první; stejné
    označení ve 3+ bodech bez hvězdy (`interrupt_chain`, INFO u prvního bodu) – řetěz, výkazy přes něj kabel
    nesledují (jen dvojici)."""
    from envocad.model.xref import DeviceIndex, interrupt_chains, is_star_source
    idx = index or DeviceIndex.build(project)
    out: list[Finding] = []
    for ref, members in interrupt_chains(idx.interrupts):
        s, e = members[0]
        out.append(Finding(INFO, s.id, s.name, e.id, False, ref,
                           f"Přerušení {ref} je v {len(members)} bodech (řetěz)", "interrupt_chain"))
    for ref, members in idx.interrupts.items():
        stars = [m for m in members if is_star_source(m[1])]
        for s, e in stars[1:]:
            out.append(Finding(WARNING, s.id, s.name, e.id, False, ref,
                               f"Přerušovací bod {ref}: víc zdrojů hvězdy – zdrojem je jen první "
                               f"(list {stars[0][0].name})", "interrupt_star_multi"))
    return out


def text_findings(project: Project, lib, *, standard_paper: str) -> list[Finding]:
    """Překrývající se vodiče a texty na listech (po automatickém rozmístění popisků) – text přes text, vodič nebo značku."""
    from envocad.model.routing import wire_overlaps
    from envocad.model.textlayout import compute_layout, text_overlaps
    out: list[Finding] = []
    for s in project.sheets:
        try:
            lay = compute_layout(project, s, lib)
            hits = text_overlaps(project, s, lib, lay)
        except (KeyError, ValueError, AttributeError):
            continue
        wires = {w.id: w for w in s.wires}
        for a, b in wire_overlaps(s, lay.routes):
            ra, rb = wires[a].attrs.get("ref") or "vodič", wires[b].attrs.get("ref") or "vodič"
            out.append(Finding(WARNING, s.id, s.name, a, True, wires[a].attrs.get("ref", ""),
                               f"Vodiče {ra} a {rb} vedou přes sebe (souběh blíž než 5 mm) – posuň úsek vodiče "
                               "(chytit a táhnout) nebo prvek", "wire_overlap"))
        for a, _b, text in hits:
            w = wires.get(a)
            ref = (w.attrs.get("ref", "") if w else s.element(a).ref) or ""
            out.append(Finding(WARNING, s.id, s.name, a, w is not None, ref,
                               f"Překryv textu: {text} – posuň prvek / lom vodiče nebo uprav polohu popisku značky",
                               "text_overlap"))
        if s.is_switchboard and mp.has_multipole(s):
            out += multipole_text_findings(project, s, lib, standard_paper=standard_paper)
            out += conductor_end_findings(project, s, lib)
        if s.is_switchboard:
            out += pole_count_findings(s) + n_pe_join_findings(s)
    return out


def pole_count_findings(s: Sheet) -> list[Finding]:
    """Do přístroje s udaným počtem pólů (`poles`) vede na jeden port víc fází než pólů (u proudového chrániče fáze
    + N): chránič 1+N (2 póly) zapojený žilami L1 L2 L3 N, jistič 1p s L1 L2 L3 – buď je přístroj špatně zvolený,
    nebo vodiče nesou žíly navíc. N kolem jističe (nespínaný) je v pořádku."""
    out = []
    for e in s.elements:
        raw = str(e.attrs.get("poles") or "").strip()
        if not raw.isdigit() or mp.is_terminal_block(e) or e.symbol_id in FEED_SYMBOLS                 or e.symbol_id.startswith(("ctl.", "sb.")) and e.symbol_id not in ("sb.rcbo",) or "spd" in e.symbol_id:
            continue
        n = int(raw)
        for port in sorted({end.port for w in s.wires for end in (w.a, w.b) if end.element_id == e.id}):
            conds = sorted({c for w in s.wires if not mp.is_control_wire(w) for end in (w.a, w.b)
                            if end.element_id == e.id and end.port == port for c in mp.wire_conductors(w)}
                           - {"PE", "PEN"}, key=mp.canon_key)
            # fáze na póly; N jde u jističe kolem (nespínaný), u proudového chrániče přes pól (1+N, 3+N)
            rcd = any(k in e.symbol_id for k in ("rcbo", "rcd"))
            need = sum(1 for c in conds if c in ("L1", "L2", "L3", "L")) + (1 if rcd and "N" in conds else 0)
            if need > n:
                out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                   f"{e.ref or 'Přístroj'} má {n} pól(y), na svorku {port} vedou žíly {' '.join(conds)} – "
                                   "zvol přístroj s odpovídajícím počtem pólů nebo oprav žíly vodičů", "pole_count"))
                break
    return out


def n_pe_join_findings(s: Sheet) -> list[Finding]:
    """Uzel, ve kterém se potkávají vodiče jen s N a vodiče jen s PE: v síti TN-S (oddělené N a PE) se N a PE
    v rozvaděči nespojují – PEN se rozděluje jen jednou (hlavní rozvaděč)."""
    from envocad.model.potential import JUNCTION
    out = []
    for e in s.elements:
        if e.symbol_id != JUNCTION:
            continue
        sets = [set(mp.wire_conductors(w)) for w in s.wires if w.touches(e.id)]
        if any("PEN" in c for c in sets):
            continue
        if any("N" in c and "PE" not in c for c in sets) and any("PE" in c and "N" not in c for c in sets):
            out.append(Finding(WARNING, s.id, s.name, e.id, False, "uzel",
                               "V uzlu se spojuje N s PE (vodič jen s N a vodič jen s PE) – v síti TN-S se N a PE "
                               "v rozvaděči nespojují; oprav žíly vodiče", "n_pe_join"))
    return out


def conductor_end_findings(project: Project, s: Sheet, lib) -> list[Finding]:
    """Žíly, které vedou do vícepólového průchozího přístroje jen z jedné strany: na vstupu N a PE, na výstupu jen
    L1–L3 (ve vícepólu pak končí naprázdno u přístroje). Jednopólový přístroj ne – tam se žíly navíc nekreslí
    (`multipole.dead_conductors`). Cívky (A1 / A2 na pólu) a svorky ne."""
    try:
        poles = mp.sheet_poles(s, lambda e: element_symbol(project, e, lib))
    except (KeyError, ValueError, AttributeError, StopIteration):
        return []
    out = []
    for ep in poles.values():
        e = ep.element
        if ep.through is None or len(ep.switched) < 2 or mp.is_terminal_block(e) or e.symbol_id in FEED_SYMBOLS \
                or "PE" in ep.through or "spd" in e.symbol_id:
            continue                    # svodič (L → PE) není průchozí přístroj
        a, b = ({c for w in s.wires if not mp.is_control_wire(w)          # ovládací žíla cívky (A1 → L) se nepočítá
                 for end in (w.a, w.b) if end.element_id == e.id and end.port == p for c in mp.wire_conductors(w)}
                for p in ep.through)
        if not a or not b:
            continue                    # přístroj zapojený jen z jedné strany hlásí jiná kontrola
        loose = sorted((a ^ b) - set(ep.joined) - set(ep.switched), key=mp.canon_key)
        loose = sorted(set(loose) | {c for c in ep.switched if (c in a) != (c in b)}, key=mp.canon_key)
        if loose:
            out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                               f"Žíly {', '.join(loose)} vedou do {e.ref or 'přístroje'} jen z jedné strany – na "
                               "druhé straně chybí (vícepól je kreslí naprázdno); doplň žíly vodiče v jednopólu",
                               "mp_conductor_end"))
    return out


MP_OVERLAP_DETAIL = 5   # víc překryvů ve vícepólu jednoho listu → jedna souhrnná položka


def multipole_text_findings(project: Project, s: Sheet, lib, *, standard_paper: str) -> list[Finding]:
    """Překryvy textů a čar ve vícepólovém schématu listu rozvaděče (`multipole_geometry`)."""
    from envocad.model.multipole_geometry import multipole_text_overlaps
    try:
        hits = multipole_text_overlaps(project, s, lib, standard_paper=standard_paper)
    except (KeyError, ValueError, AttributeError, StopIteration):
        return []
    wires = {w.id: w for w in s.wires}
    els = {e.id: e for e in s.elements}
    out = []
    if len(hits) > MP_OVERLAP_DETAIL:   # velký rozvaděč: jedna položka s počtem, ať F7 nezahltí
        examples = "; ".join(t for _a, _b, t in hits[:3])
        return [Finding(WARNING, s.id, s.name, "", False, s.loc,
                        f"Vícepól: {len(hits)} překryvů textů a čar (např. {examples}) – uprav rozmístění ve vícepólu",
                        "mp_text_overlap")]
    for a, _b, text in hits:
        w, e = wires.get(a), els.get(a)
        ref = (w.attrs.get("ref", "") if w else (e.ref if e else "")) or ""
        out.append(Finding(WARNING, s.id, s.name, a if (w or e) else "", w is not None, ref,
                           f"Vícepól: překryv textu – {text} (posuň prvek ve vícepólu nebo uprav rozmístění)",
                           "mp_text_overlap"))
    return out


def potential_findings(project: Project, lib) -> list[Finding]:
    """Potenciály: nepřípustně spojené potenciály v jedné síti (L–N, L–PE, L+–L−, fáze), uzel odbočky bez odbočky."""
    from envocad.model.potential import JUNCTION, nets
    out: list[Finding] = []
    for net in nets(project, lib):
        issue = net.short_issue()
        if issue:
            s, w, _ = net.wires[0] if net.wires else (net.members[0][0], None, "")
            tid, is_wire = (w.id, True) if w is not None else (net.members[0][1].id, False)
            out.append(Finding(ERROR, s.id, s.name, tid, is_wire, w.attrs.get("ref", "") if w else net.members[0][1].ref,
                               f"Potenciál {net.name}: {issue}", "pot_short"))
    for s in project.sheets:
        for e in s.elements:
            if e.symbol_id == JUNCTION:
                n = sum(1 for w in s.wires for end in (w.a, w.b) if end.element_id == e.id)
                if n < 3:
                    out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref or "uzel",
                                       f"Uzel odbočky má jen {n} vodič(e) – odbočka chybí", "junction_free"))
    return out


def cable_findings(project: Project) -> list[Finding]:
    """Kabely bez vodiče JPS (osiřelé už v načteném souboru – `sync_cables` je ponechá kvůli ručním datům) → INFO."""
    from envocad.model.project import orphan_cables
    return [Finding(INFO, "", "", "", False, c.ref, f"Kabel {c.ref or '(bez označení)'} nemá vodič", "cable_no_wire")
            for c in orphan_cables(project)]


def calc_findings(project: Project, lib=None) -> list[Finding]:
    """Nálezy z výpočtů (model/calc.py): stringy, kabely, selektivita."""
    from envocad.model import calc
    out: list[Finding] = []
    sheet_of = {e.id: s for s in project.sheets for e in s.elements}
    el_by_ref = {e.ref: e for s in project.sheets for e in s.elements if e.ref}
    for msg in calc.design_temperature_issues(project):   # neplatná návrhová teplota ve Vlastnostech projektu
        out.append(Finding(WARNING, "", "", "", False, "", msg, "calc_temp"))
    for sc in calc.check_strings(project, lib=lib):
        e = el_by_ref.get(sc.ref)
        s = sheet_of.get(e.id) if e else None
        for msg in sc.issues:
            sev = WARNING if calc.is_warning(msg) else ERROR   # závažnost hlášek stringu jen v `calc.is_warning`
            out.append(Finding(sev, s.id if s else "", s.name if s else "", e.id if e else "", False, sc.ref,
                               f"String: {msg}", "calc_string"))
    for cc in calc.check_cables(project):
        s = next((x for x in project.sheets if x.name == cc.sheet), None)
        w = next((w for w in (s.wires if s else []) if w.attrs.get("ref") == cc.ref), None)
        for msg in cc.issues:
            sev = INFO if "chybí" in msg else (WARNING if "úbytek" in msg else ERROR)
            out.append(Finding(sev, s.id if s else "", cc.sheet, w.id if w else "", True, cc.ref,
                               f"Kabel: {msg}", "calc_cable"))
    for lo, hi, _il, _ih, msg in calc.check_selectivity(project):
        if msg != "OK":
            e = el_by_ref.get(lo)
            s = sheet_of.get(e.id) if e else None
            out.append(Finding(WARNING if "menší" in msg else INFO, s.id if s else "", s.name if s else "",
                               e.id if e else "", False, lo, f"Selektivita: {msg}", "calc_selectivity"))
    return out


def rating_findings(project: Project, lib=None) -> list[Finding]:
    """Kontroly z údajů artiklů (`model/ratings.py`, docs/design/kontroly_artiklu.md): zkratová odolnost (`sc_*`),
    svodiče (`spd_uc`, `spd_ucpv`, `spd_up`, `spd_lps`), svorky (`terminal_cross`, `terminal_in`) a jmenovité napětí
    (`un_ac`, `un_dc`). Chybějící údaj nic nehlásí."""
    from envocad.model.ratings import rating_findings as _rating
    return _rating(project, lib)


def thermal_findings(project: Project, lib=None) -> list[Finding]:
    """Oteplení rozvaděče po přístrojích (`thermal.temperature_rise` → `ThermalResult.devices`), kód `thermal_device`:
    teplota vzduchu v řadě přístroje nad jeho `t_max` z artiklu / atributu (nebo `t_min` nad nejnižší teplotou okolí
    skříně) – WARNING u přístroje. Přístroje bez rozsahu teplot z datasheetu (předpoklad `DEFAULT_T_MAX_C` /
    `DEFAULT_T_MIN_C`) – jedna INFO na list, včetně počtu těch, které jsou nad předpokladem (bez údaje z datasheetu
    nejde o prokázané překročení, ale o úkol doplnit data; verdikt oteplení je přesto hodnotí konzervativně)."""
    from envocad.model.thermal import SOURCE_ASSUMED, layout_inputs, temperature_rise
    out: list[Finding] = []
    for s in project.sheets:
        if not s.is_switchboard:
            continue
        rdf, t_amb = layout_inputs(s.layout)
        r = temperature_rise(s, rdf=rdf, t_ambient_c=t_amb, project=project, lib=lib)
        over_assumed = 0
        for d in r.hot_devices():
            if d.source == SOURCE_ASSUMED:
                over_assumed += 1
                continue
            out.append(Finding(WARNING, s.id, s.name, d.element_id, False, d.ref,
                               f"Oteplení ({ADVISORY_NOTE}): {d.place} ≈ {d.t_air:.0f} °C > t_max {d.t_max:.0f} °C "
                               f"({d.source})", "thermal_device"))
        for d in r.cold_devices():
            if d.t_min_source == SOURCE_ASSUMED:
                over_assumed += 1
                continue
            t_min = f"{d.t_min:.0f}".replace("-", "−")
            t_lo = f"{r.t_ambient_min_c:.0f}".replace("-", "−")
            out.append(Finding(WARNING, s.id, s.name, d.element_id, False, d.ref,
                               f"Teplota okolí skříně až {t_lo} °C je pod t_min {t_min} °C přístroje ({d.t_min_source})",
                               "thermal_device"))
        missing = r.missing_devices()
        if missing:
            refs = sorted({d.ref for d in missing if d.ref}, key=_natural)
            shown = ", ".join(refs[:8]) + (", …" if len(refs) > 8 else "")
            extra = f"; nad předpokladem: {over_assumed}" if over_assumed else ""
            out.append(Finding(INFO, s.id, s.name, missing[0].element_id, False, "",
                               f"Oteplení: {r.missing_text()}{extra}" + (f" ({shown})" if shown else ""),
                               "thermal_device"))
    return out


def summary(findings: list[Finding]) -> str:
    """Souhrn počtů; potlačené nálezy se nepočítají, jen (když nějaké jsou) se připojí „, N potlačeno“."""
    c = Counter(f.severity for f in findings if not f.waived)
    n_waived = sum(f.waived for f in findings)
    return (f"{c.get(ERROR, 0)} chyb, {c.get(WARNING, 0)} varování, {c.get(INFO, 0)} informací"
            + (f", {n_waived} potlačeno" if n_waived else ""))
