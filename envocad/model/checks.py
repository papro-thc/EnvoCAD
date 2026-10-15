"""Kontroly projektu (obdoba EPLAN „Zprávy/Check“) – čistá data, bez Qt.

Každý nález: závažnost, list, prvek/vodič, text. GUI z nich dělá seznam se skokem do výkresu.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from envocad.model import multipole as mp
from envocad.model.project import (
    FEED_SYMBOLS,
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
    # duplicitní označení: jako v EPLAN je úplné označení „+rozvaděč-X1“ – uvnitř každého rozvaděče (listu) musí být
    # označení jedinečné, mezi rozvaděči se smí opakovat (X1 v RDC1 i v RH); listy JPS tvoří jeden společný prostor
    refs: Counter[tuple[str, str]] = Counter()

    def scope(sh) -> str:
        return sh.id if sh.is_switchboard else ""
    for s in project.sheets:
        for e in s.elements:
            if e.ref and not mp.is_terminal_block(e) and not is_contact(e):
                refs[(scope(s), e.ref)] += 1
        for w in s.wires:
            if w.attrs.get("ref"):
                refs[(scope(s), w.attrs["ref"])] += 1
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
            if e.ref and refs[(scope(s), e.ref)] > 1 and not mp.is_terminal_block(e) and not is_contact(e):
                out.append(Finding(ERROR, s.id, s.name, e.id, False, e.ref, f"Duplicitní označení {e.ref}", "dup_ref"))
            if not e.ref and e.symbol_id not in ("fve.earth", "fve.grid", "fve.load"):
                out.append(Finding(WARNING, s.id, s.name, e.id, False, "", f"Prvek {sym.name} bez označení", "no_ref"))
            conn = _connected_ports(s, e)
            if e.symbol_id not in OPTIONAL_PORT_SYMBOLS:
                free = [p.name for p in sym.ports if p.name not in conn]
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
            if ref and refs[(scope(s), ref)] > 1:
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
    out += calc_findings(project)
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    out.sort(key=lambda f: (order[f.severity], f.sheet_name, f.ref))
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
