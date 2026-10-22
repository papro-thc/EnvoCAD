"""Můstky svorkovnic jako artikl (bez Qt): každá skupina můstku (`Sheet.bridges`) bere artikl z atributu `bridge_id`
skupiny svorek, na které leží (`bridge_owner`). Výkaz materiálu (`reports.bom`) a kontrola F7 (`bridge_findings`).

Počet pólů artiklu (`poles`) se porovná s velikostí skupiny: shoda = artikl; artikl s více póly = artikl
s poznámkou „zkrátit“ (ZQV/WQV n-pólové se zkracují); méně pólů nebo bez údaje = typ se nevyplní, jen poznámka.
Katalog nemá vazbu svorka → můstek, proto se artikl nevybírá automaticky (kandidáti `components.bridge_candidates`).
"""
from __future__ import annotations

from dataclasses import dataclass

from envocad.model.project import AUTO_WIDTH_TERMINALS, Element, Project, Sheet, terminal_count

BRIDGE_ATTR = "bridge_id"
OK, CUT, UNKNOWN, NOT_BRIDGE, POLES = "ok", "zkrátit", "unknown", "not_bridge", "poles"


def is_bridge_component(comp) -> bool:
    """Artikl můstku svorek (propojka, ZQV/WQV): `terminal_kind` = `mustek`."""
    return comp is not None and (comp.params.get("terminal_kind") or "").strip().lower() == "mustek"


def _group_numbers(sheet: Sheet, e: Element) -> set[str]:
    """Čísla svorek skupiny svorek (jako výkazy: podle počtu žil napojených vodičů, jinak atributu `terminal`)."""
    from envocad.model.multipole import terminal_numbers, wire_conductors
    n = len({c for w in sheet.wires for end in (w.a, w.b) if end.element_id == e.id for c in wire_conductors(w)})
    return {x for x in terminal_numbers(e, max(n, terminal_count(e))) if x}


def bridge_owner(sheet: Sheet, strip: str, group: list[str]) -> Element | None:
    """Skupina svorek svorkovnice `strip`, jejíž `bridge_id` platí pro můstek `group`: první (v pořadí čísel můstku)
    skupina, na které můstek leží a která má `bridge_id`; None = obecný můstek."""
    els = [e for e in sheet.elements if e.symbol_id in AUTO_WIDTH_TERMINALS and e.ref == strip
           and str(e.attrs.get(BRIDGE_ATTR) or "").strip()]
    nums = {e.id: _group_numbers(sheet, e) for e in els}
    for x in group:
        for e in els:
            if x in nums[e.id]:
                return e
    return None


@dataclass
class BridgeArticle:
    """Artikl můstku pro jednu skupinu: `status` „“ (obecný), `ok`, `zkrátit`, `unknown` (id mimo knihovnu),
    `not_bridge` (artikl není můstek), `poles` (málo pólů / bez údaje). `type` a `manufacturer` jsou pro výkaz
    (prázdné, když artikl nevyhovuje), `note` doplní sloupec Parametry."""
    bridge_id: str = ""
    status: str = ""
    type: str = ""
    manufacturer: str = ""
    note: str = ""
    element: Element | None = None


def resolve_bridge(sheet: Sheet, strip: str, group: list[str], lib) -> BridgeArticle:
    owner = bridge_owner(sheet, strip, group)
    if owner is None:
        return BridgeArticle()
    bid = str(owner.attrs.get(BRIDGE_ATTR) or "").strip()
    comp = None
    if lib is not None and hasattr(lib, "component"):
        try:
            comp = lib.component(bid)
        except Exception:  # noqa: BLE001 – výkaz se vytvoří i bez knihovny
            comp = None
    if comp is None:
        return BridgeArticle(bid, UNKNOWN, bid, "", "artikl není v knihovně", owner)
    if not is_bridge_component(comp):
        return BridgeArticle(bid, NOT_BRIDGE, "", "", f"artikl {comp.part_number} není můstek", owner)
    n = len(group)
    poles = comp.num("poles") if hasattr(comp, "num") else None
    if poles is not None and int(poles) == n:
        return BridgeArticle(bid, OK, comp.part_number, comp.manufacturer, "", owner)
    if poles is not None and poles > n:
        return BridgeArticle(bid, CUT, comp.part_number, comp.manufacturer, f"zkrátit z {int(poles)} pólů", owner)
    have = f"má {int(poles)} pólů" if poles is not None else "nemá počet pólů"
    return BridgeArticle(bid, POLES, "", "", f"artikl {comp.part_number} {have}", owner)


def bridge_findings(project: Project, lib) -> list:
    """F7 (jen s knihovnou): WARNING `bridge_article` – `bridge_id` skupiny svorek, který není v knihovně, artikl,
    který není můstek, a artikl s menším (nebo neuvedeným) počtem pólů než skupina můstku."""
    from envocad.model.checks import WARNING, Finding
    from envocad.model.terminal_plan import strip_numbers
    if lib is None:
        return []
    out = []
    for s in project.sheets:
        for strip, groups in s.bridges.items():
            existing = None
            for g in groups:
                if existing is None:
                    existing = strip_numbers(project, s, strip)
                g = [x for x in g if x in existing]
                if len(g) < 2:
                    continue
                r = resolve_bridge(s, strip, g, lib)
                if r.status in (UNKNOWN, NOT_BRIDGE, POLES):
                    e = r.element
                    out.append(Finding(WARNING, s.id, s.name, e.id if e else "", False, e.ref if e else strip,
                                       f"Můstek {strip}:{'-'.join(g)} ({len(g)} pólů): {r.note} – ve výkazu bez typu"
                                       if r.status != UNKNOWN else
                                       f"Můstek {strip}:{'-'.join(g)}: artikl „{r.bridge_id}“ není v knihovně",
                                       "bridge_article"))
    return out
