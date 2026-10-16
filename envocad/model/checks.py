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
    full_designation,
    scope_key,
    validate_code,
    validate_ref,
)
from envocad.model.project import (
    FEED_SYMBOLS,
    INTERRUPT_SYMBOL,
    INVERTER_SYMBOLS,
    Element,
    Project,
    Sheet,
    coil_of,
    contact_terminals,
    element_symbol,
    interrupt_partner,
    is_contact,
    linked_wire,
)

ERROR, WARNING, INFO = "chyba", "varování", "info"
# prvky, u kterých nevadí nezapojený port (jde o odkazy/bloky/sběrnice s rezervou)
OPTIONAL_PORT_SYMBOLS = {"fve.switchboard", "sb.pe_bar", "sb.busbar", "fve.terminal", "sb.terminal_block"}
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
    out: list[Finding] = []
    # duplicitní označení: jako v EPLAN je úplné označení „=funkce+umístění-X1“ – v každém prostoru (func, loc)
    # musí být označení jedinečné, mezi umístěními se smí opakovat (X1 v +RDC1 i v +RH). Listy se stejným
    # umístěním sdílejí prostor, list rozvaděče bez umístění má vlastní, vodiče JPS (kabely) jeden společný.
    refs: Counter[tuple[str, str, str]] = Counter()
    for s in project.sheets:
        for e in s.elements:
            if e.ref and not mp.is_terminal_block(e) and not is_contact(e):
                refs[(*scope_key(s, e), e.ref)] += 1
        for w in s.wires:
            if w.attrs.get("ref"):
                refs[(*scope_key(s, w), w.attrs["ref"])] += 1
    for s in project.sheets:
        sym_of = {}
        for e in s.elements:
            try:
                sym = element_symbol(project, e, lib)
            except Exception:  # noqa: BLE001
                out.append(Finding(ERROR, s.id, s.name, e.id, False, e.ref, f"Neznámá značka {e.symbol_id}", "symbol"))
                continue
            sym_of[e.id] = sym
            if is_contact(e) and e.ref and coil_of(project, e) is None:
                out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                   f"Kontakt {contact_terminals(e)} bez cívky/přístroje {e.ref}", "contact_alone"))
            if e.ref and refs[(*scope_key(s, e), e.ref)] > 1 and not mp.is_terminal_block(e) and not is_contact(e):
                out.append(Finding(ERROR, s.id, s.name, e.id, False, e.ref, f"Duplicitní označení {e.ref}", "dup_ref"))
            if not e.ref and e.symbol_id not in ("fve.earth", "fve.grid", "fve.load"):
                out.append(Finding(WARNING, s.id, s.name, e.id, False, "", f"Prvek {sym.name} bez označení", "no_ref"))
            conn = _connected_ports(s, e)
            if e.symbol_id not in OPTIONAL_PORT_SYMBOLS:
                free = [p.name for p in sym.ports if p.name not in conn]
                if e.symbol_id in INVERTER_SYMBOLS and any(p.startswith("DC") for p in conn):
                    free = [p for p in free if not p.startswith("DC")]   # volné DC vstupy střídače jsou rezerva
                if free and (free != [p.name for p in sym.ports]):
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
            if e.symbol_id in FEED_SYMBOLS and s.is_switchboard and linked_wire(project, s, e) is None:
                out.append(Finding(INFO, s.id, s.name, e.id, False, e.ref,
                                   "Přívod/vývod bez vazby na vodič v JPS", "feed_unlinked"))
            if (e.symbol_id not in NO_ARTICLE_SYMBOLS and not e.component_id and not e.attrs.get("type")
                    and not mp.is_terminal_block(e)):
                out.append(Finding(INFO, s.id, s.name, e.id, False, e.ref, "Bez artiklu / typu", "no_article"))
            if e.symbol_id == "fve.interrupt" and interrupt_partner(project, e) is None:
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
                if sym is not None and not any(p.name == end.port for p in sym.ports):
                    out.append(Finding(ERROR, s.id, s.name, w.id, True, ref,
                                       f"Vodič na neexistující port {e.ref or e.symbol_id}:{end.port}", "bad_port"))
            if ref and refs[(*scope_key(s, w), ref)] > 1:
                out.append(Finding(ERROR, s.id, s.name, w.id, True, ref, f"Duplicitní označení {ref}", "dup_ref"))
            if not s.is_switchboard and not (w.attrs.get("cable") or w.attrs.get("cross")):
                out.append(Finding(INFO, s.id, s.name, w.id, True, ref, "Vodič bez typu kabelu / průřezu", "no_cable"))
            if not w.conductors:
                out.append(Finding(INFO, s.id, s.name, w.id, True, ref, "Vodič bez žil (vícepól ho kreslí jako L1)", "no_cond"))
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
    out += designation_findings(project, lib)
    out += calc_findings(project)
    out += potential_findings(project, lib)
    out += text_findings(project, lib)
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    out.sort(key=lambda f: (order[f.severity], f.sheet_name, f.ref))
    return out


def _sev(issue) -> str:
    return ERROR if issue.error else (INFO if issue.info else WARNING)


def _aspect_word(aspect: str) -> str:
    return "Funkce" if aspect == FUNC else "Umístění"


def designation_findings(project: Project, lib) -> list[Finding]:
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
            code_findings(s, FUNC, e.attrs.get("func", ""), e.id, e.ref, f"prvku {e.ref or e.symbol_id}", reported)
            code_findings(s, LOC, e.attrs.get("loc", ""), e.id, e.ref, f"prvku {e.ref or e.symbol_id}", reported)
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
    out += _contact_findings(project)
    return out


def _place_text(project: Project, s: Sheet, e: Element) -> str:
    d = designation(s, e)
    if s.is_switchboard and not d.loc:
        return s.name                     # anonymní rozvaděč – bez kódu, jen název listu
    return Designation(d.func, d.loc).aspects or "(bez umístění)"


def _contact_findings(project: Project) -> list[Finding]:
    """Kontakt se páruje s cívkou jen podle `ref` (napříč projektem). Má-li stejné označení víc cívek/přístrojů
    v různých prostorech (K1 v +RDC1 i v +RH), je párování nejednoznačné – pokud kontakt umístěním nevybere právě
    jeden z nich."""
    out: list[Finding] = []
    owners: dict[str, list[tuple[Sheet, Element]]] = {}
    for s in project.sheets:
        for e in s.elements:
            if e.ref and not is_contact(e) and not mp.is_terminal_block(e) and e.symbol_id != INTERRUPT_SYMBOL:
                owners.setdefault(e.ref, []).append((s, e))
    for s in project.sheets:
        for c in s.elements:
            if not (is_contact(c) and c.ref):
                continue
            cands = owners.get(c.ref, [])
            scopes = {scope_key(os_, o) for os_, o in cands}
            if len(scopes) < 2:
                continue
            if (c.attrs.get("func") or c.attrs.get("loc")) and \
                    sum(1 for os_, o in cands if scope_key(os_, o) == scope_key(s, c)) == 1:
                continue
            places = sorted({_place_text(project, os_, o) for os_, o in cands})
            out.append(Finding(WARNING, s.id, s.name, c.id, False, c.ref,
                               f"Kontakt {c.ref} odpovídá cívkám ve více umístěních ({', '.join(places)}) – "
                               "nastav kontaktu umístění", "contact_ambiguous"))
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
            sev = WARNING if ("chybí" in msg or "nemá" in msg or "není" in msg) else ERROR
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


def summary(findings: list[Finding]) -> str:
    c = Counter(f.severity for f in findings)
    return f"{c.get(ERROR, 0)} chyb, {c.get(WARNING, 0)} varování, {c.get(INFO, 0)} informací"
