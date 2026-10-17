"""Kontroly projektu (obdoba EPLAN „Zprávy/Check“) – čistá data, bez Qt.

Každý nález: závažnost, list, prvek/vodič, text. GUI z nich dělá seznam se skokem do výkresu.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from envocad.model import multipole as mp
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
from envocad.model.notes import OPEN_NOTE_WORDS, count_label
from envocad.model.project import (
    FEED_SYMBOLS,
    INTERRUPT_SYMBOL,
    INVERTER_SYMBOLS,
    Element,
    Project,
    Sheet,
    contact_terminals,
    dangling_wires,
    element_symbol,
    is_contact,
    linked_wire,
    without_dangling,
)

ERROR, WARNING, INFO = "chyba", "varování", "info"
# prvky, u kterých nevadí nezapojený port (jde o odkazy/bloky/sběrnice s rezervou)
OPTIONAL_PORT_SYMBOLS = {"fve.switchboard", "sb.pe_bar", "sb.busbar", "fve.terminal", "sb.terminal_block",
                         "sb.junction"}   # uzel odbočky: počet vodičů hlídá `junction_free`
NO_REF_OK_SYMBOLS = {"fve.earth", "fve.grid", "fve.load", "sb.junction"}   # bez označení je v pořádku
AGGREGATED_INFO = {"no_article": "Bez artiklu / typu", "ref_syntax": "Označení s firemním oddělovačem „.“ / „-“ (přípustné jako firemní číslování)"}
NO_ARTICLE_SYMBOLS = {"fve.grid", "fve.load", "fve.earth", "fve.terminal", "fve.switchboard", "sb.feed_in",
                      "sb.feed_out", "sb.pe_bar", "sb.busbar", "fve.pv_string", "fve.interrupt",
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


def _connected_ports(sheet: Sheet, e: Element) -> set[str]:
    return {end.port for w in sheet.wires for end in (w.a, w.b) if end.element_id == e.id}


def check_project(project: Project, lib) -> list[Finding]:
    from envocad.model.xref import DeviceIndex, interrupt_link
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
    # musí být označení jedinečné, mezi umístěními se smí opakovat (X1 v +RDC1 i v +RH). Listy se stejným
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
            if e.symbol_id not in OPTIONAL_PORT_SYMBOLS:
                real = [p.name for p in sym.ports if p.name not in sym.orphan_ports]   # osiřelé hlásí bad_port
                free = [p for p in real if p not in conn]
                if e.symbol_id in INVERTER_SYMBOLS and any(p.startswith("DC") for p in conn):
                    free = [p for p in free if not p.startswith("DC")]   # volné DC vstupy střídače jsou rezerva
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
            if (e.symbol_id in FEED_SYMBOLS and s.is_switchboard and linked_wire(project, s, e) is None
                    and not is_earthing_feed(s, e)):
                out.append(Finding(INFO, s.id, s.name, e.id, False, e.ref,
                                   "Přívod/vývod bez vazby na vodič v JPS", "feed_unlinked"))
            if (e.symbol_id not in NO_ARTICLE_SYMBOLS and not e.component_id and not e.attrs.get("type")
                    and not mp.is_terminal_block(e) and idx.is_bom_device(e)):
                out.append(Finding(INFO, s.id, s.name, e.id, False, e.ref, "Bez artiklu / typu", "no_article"))
            if e.symbol_id == INTERRUPT_SYMBOL and interrupt_link(project, s, e, idx.interrupts).mode == "alone":
                out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                   "Přerušovací bod bez protějšku (stejné označení jinde)", "interrupt_alone"))
            if e.symbol_id == "fve.switchboard" and project.switchboard_sheet(e.id) is None:
                out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref, "Rozvaděč nemá list (dvojklik)", "no_sheet"))
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
            if not s.is_switchboard and not (w.attrs.get("cable") or w.attrs.get("cross")):
                out.append(Finding(INFO, s.id, s.name, w.id, True, ref, "Vodič bez typu kabelu / průřezu", "no_cable"))
            if not w.conductors:
                out.append(Finding(INFO, s.id, s.name, w.id, True, ref, "Vodič bez žil (vícepól ho kreslí jako L1)", "no_cond"))
        if s.is_switchboard and (not s.parent_element_id or project.sheet_of_element(s.parent_element_id) is None):
            out.append(Finding(WARNING, s.id, s.name, "", False, s.loc,
                               "List rozvaděče bez bloku ROZVADĚČ v jednopólovém schématu (blok smazán?) – "
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
    out += layout_findings(project)
    out += contact_findings(project, idx)
    out += interrupt_findings(project, idx)
    out += designation_findings(project, lib, idx)
    out += revision_findings(full)
    out += note_findings(full)
    out += cable_findings(full)
    out += calc_findings(project)
    out += thermal_findings(project, lib)
    out += potential_findings(project, lib)
    out += text_findings(project, lib)
    out = aggregate_info(out)
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    out.sort(key=lambda f: (order[f.severity], f.sheet_name, f.ref))
    return out


def is_earthing_feed(sheet: Sheet, e: Element) -> bool:
    """Vývod jen s PE (XPE → ekvipotenciální svorkovnice HOP): uzemnění rozvaděče, ve schématu JPS obvykle bez
    vodiče – chybějící vazbu na JPS kontrola nehlásí."""
    if e.symbol_id != "sb.feed_out":
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


def layout_problems(sheet: Sheet, project: Project | None = None, layout=None) -> list[LayoutProblem]:
    """Přetečení a překryvy v řadách rozložení listu rozvaděče (jen přístroje rozložení – `Layout.devices`, bez
    kontaktů – umístěné v řadách skříně). Zmenšení počtu modulů v řadě umístění nemaže; přístroje za koncem řady
    hlásí tato kontrola. `layout` = rozpracovaná kopie (dialog skříně), jinak `sheet.layout`."""
    lay = layout if layout is not None else sheet.layout
    devs = lay.devices(sheet, project)
    rows: dict[int, list[tuple[float, float, Element]]] = {}
    for e in devs:
        pl = lay.placement(e.id)
        if pl is not None:
            rows.setdefault(pl.row, []).append((pl.pos, pl.pos + e.modules, e))
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


def layout_findings(project: Project) -> list[Finding]:
    """Rozložení rozvaděče: přístroj s uloženým umístěním v řadě mimo skříň (po zmenšení počtu řad) – WARNING
    `outside_enclosure`; rozložení ho kreslí mezi nerozmístěnými, po zvětšení počtu řad se umístění vrátí.
    Přetečení řady a překryvy přístrojů (`layout_problems`) – WARNING `layout_overflow` / `layout_overlap`."""
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
        for pr in layout_problems(s, project):
            e = pr.element
            out.append(Finding(WARNING, s.id, s.name, e.id if e else "", False, e.ref if e else "", pr.text, pr.code))
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
    přístrojů v různých prostorech (K1 v +RDC1 i v +RH), přednost má ten ve stejném prostoru označení (funkce,
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


def interrupt_findings(project: Project, index=None) -> list[Finding]:
    """Přerušovací body: víc zdrojů hvězdy ve skupině (`interrupt_star_multi`) – zdrojem je jen první."""
    from envocad.model.xref import DeviceIndex, is_star_source
    idx = index or DeviceIndex.build(project)
    out: list[Finding] = []
    for ref, members in idx.interrupts.items():
        stars = [m for m in members if is_star_source(m[1])]
        for s, e in stars[1:]:
            out.append(Finding(WARNING, s.id, s.name, e.id, False, ref,
                               f"Přerušovací bod {ref}: víc zdrojů hvězdy – zdrojem je jen první "
                               f"(list {stars[0][0].name})", "interrupt_star_multi"))
    return out


def text_findings(project: Project, lib) -> list[Finding]:
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
        if s.is_switchboard:
            out += multipole_text_findings(project, s, lib)
    return out


MP_OVERLAP_DETAIL = 5   # víc překryvů ve vícepólu jednoho listu → jedna souhrnná položka


def multipole_text_findings(project: Project, s: Sheet, lib) -> list[Finding]:
    """Překryvy textů a čar ve vícepólovém schématu listu rozvaděče (`multipole_geometry`)."""
    from envocad.model.multipole_geometry import multipole_text_overlaps
    try:
        hits = multipole_text_overlaps(project, s, lib)
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
    """Potenciály: nepřípustně spojené potenciály v jedné síti (L–N, L–PE, DC+–DC−, fáze), uzel odbočky bez odbočky."""
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


def calc_findings(project: Project) -> list[Finding]:
    """Nálezy z výpočtů (model/calc.py): stringy, kabely, selektivita."""
    from envocad.model import calc
    out: list[Finding] = []
    sheet_of = {e.id: s for s in project.sheets for e in s.elements}
    el_by_ref = {e.ref: e for s in project.sheets for e in s.elements if e.ref}
    for sc in calc.check_strings(project):
        e = el_by_ref.get(sc.ref)
        s = sheet_of.get(e.id) if e else None
        for msg in sc.issues:
            sev = WARNING if ("chybí" in msg or "nemá" in msg or "není" in msg or "omezení výkonu" in msg) else ERROR
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
                               f"Oteplení (orientačně): {d.place} ≈ {d.t_air:.0f} °C > t_max {d.t_max:.0f} °C "
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
    c = Counter(f.severity for f in findings)
    return f"{c.get(ERROR, 0)} chyb, {c.get(WARNING, 0)} varování, {c.get(INFO, 0)} informací"
