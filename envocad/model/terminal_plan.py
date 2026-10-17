"""Plán svorkovnice (terminal diagram) – data pro výkaz i kreslený list. Bez Qt.

Pro každou svorkovnici (X…) na listu: svorky v pořadí čísel, u každé vnější připojení (kabel odcházející
z rozvaděče – přívod/vývod, resp. vodič JPS navázaný na přívod/vývod), vnitřní připojení (přístroj v rozvaděči)
a můstek. Strana se neurčuje podle portu, ale podle toho, co je na druhém konci vodiče.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from envocad.model import multipole as mp
from envocad.model.project import FEED_SYMBOLS, Element, Project, Sheet, Wire, linked_wire
from envocad.model.xref import natural_key


@dataclass
class TerminalRow:
    strip: str
    number: str
    conductor: str
    element_id: str
    external: str = ""      # odkud/kam vně rozvaděče (W2 T1:AC)
    ext_cable: str = ""
    internal: str = ""      # přístroj v rozvaděči (F2:1)
    int_cable: str = ""
    bridge: str = ""

    @property
    def sort_key(self) -> tuple:
        return (not self.number.isdigit(), int(self.number) if self.number.isdigit() else 0, self.number, self.conductor)


@dataclass
class StripPlan:
    strip: str
    rows: list[TerminalRow] = field(default_factory=list)
    bridges: list[list[str]] = field(default_factory=list)


def _wire_text(project: Project, sheet: Sheet, w: Wire, side: str, conductor: str) -> tuple[str, str]:
    """Druhý konec žíly (strana `side`) a kabel: svorka jako zapojovací/výrobní seznam (`wiring.conductor_end` –
    pól přístroje „Q1:3“, svorka, potenciál sběrnice), bez aspektů (plán je po listech)."""
    from envocad.model.wiring import conductor_end
    end = w.a if side == "a" else w.b
    try:
        sheet.element(end.element_id)
    except KeyError:
        return "", ""
    cable = " ".join(x for x in (w.attrs.get("cable", ""), w.attrs.get("cross", "")) if x)
    return conductor_end(project, sheet, w, conductor, side).terminal, w.attrs.get("ref", "") + (f" {cable}" if cable else "")


def _external_of_feed(project: Project, sheet: Sheet, e: Element) -> tuple[str, str]:
    """Vnější připojení přívodu/vývodu: navázaný vodič JPS, jinak text z atributů."""
    hit = linked_wire(project, sheet, e)
    if hit is not None:
        s, w = hit
        far_end = w.b if w.a.element_id == sheet.parent_element_id else w.a
        far = s.element(far_end.element_id)
        cable = " ".join(x for x in (w.attrs.get("cable", ""), w.attrs.get("cross", "")) if x)
        return f"{far.ref or far.symbol_id}:{far_end.port}", (w.attrs.get("ref", "") + " " + cable).strip()
    return e.attrs.get("from") or e.attrs.get("to") or e.attrs.get("desc", ""), e.attrs.get("cable", "")


def terminal_plan(project: Project, sheet: Sheet) -> list[StripPlan]:
    strips: dict[str, StripPlan] = {}
    for e in sheet.elements:
        if e.symbol_id not in mp.TERMINAL_SYMBOLS or not e.ref:
            continue
        plan = strips.setdefault(e.ref, StripPlan(e.ref, bridges=project.bridge_groups(e.ref, sheet)))
        ends = [(w, side, end) for w in sheet.wires for side, end in (("a", w.a), ("b", w.b)) if end.element_id == e.id]
        slots = sorted({c for w, _, _ in ends for c in mp.wire_conductors(w)}, key=mp.canon_key)
        nums = mp.terminal_numbers(e, len(slots)) if mp.is_terminal_block(e) else [""] * len(slots)
        for c, num in zip(slots, nums):
            row = TerminalRow(e.ref, num, c, e.id)
            if e.symbol_id in FEED_SYMBOLS:
                row.external, row.ext_cable = _external_of_feed(project, sheet, e)
            for w, side, end in ends:
                if c not in mp.wire_conductors(w):
                    continue
                if not row.number:
                    t = mp.terminal_text(w, c, side)
                    row.number = t.partition(":")[2] or t
                other = w.b if side == "a" else w.a
                try:
                    oe = sheet.element(other.element_id)
                except KeyError:
                    continue
                text, cable = _wire_text(project, sheet, w, "b" if side == "a" else "a", c)
                if oe.symbol_id in FEED_SYMBOLS:
                    # vodič k přívodu/vývodu = vnější strana (kabel ven z rozvaděče)
                    ext, ext_cable = _external_of_feed(project, sheet, oe)
                    row.external = row.external or ext or text
                    row.ext_cable = row.ext_cable or ext_cable or cable
                elif row.internal:
                    row.internal += ", " + text
                else:
                    row.internal, row.int_cable = text, cable
            if not row.number:
                row.number = str(len(plan.rows) + 1)
            b = project.bridge_of(e.ref, row.number, sheet)
            row.bridge = "-".join(b) if b else ""
            plan.rows.append(row)
    for plan in strips.values():
        plan.rows.sort(key=lambda r: r.sort_key)
    return sorted(strips.values(), key=lambda p: natural_key(p.strip))


def strip_numbers(project: Project, sheet: Sheet, strip: str) -> set[str]:
    """Čísla svorek, která na svorkovnici `strip` listu existují (podle plánu svorkovnice)."""
    return {r.number for p in terminal_plan(project, sheet) if p.strip == strip for r in p.rows if r.number}


def parse_bridges(text: str) -> list[list[str]]:
    """Text můstků (jedna skupina na řádek, čísla oddělená pomlčkou / čárkou / mezerou) → skupiny (≥ 2 svorky)."""
    groups = []
    for line in (text or "").splitlines():
        toks = [t.strip() for t in line.replace(",", "-").replace(" ", "-").split("-") if t.strip()]
        if len(toks) >= 2:
            groups.append(toks)
    return groups


def bridge_errors(strip: str, text: str, existing: set[str]) -> list[str]:
    """Chyby zadání můstků svorkovnice: řádek s jedinou svorkou, svorka, která na svorkovnici není, svorka ve dvou
    můstcích. Česky, prázdné = v pořádku."""
    errs: list[str] = []
    seen: dict[str, int] = {}
    for i, line in enumerate((text or "").splitlines(), start=1):
        toks = [t.strip() for t in line.replace(",", "-").replace(" ", "-").split("-") if t.strip()]
        if not toks:
            continue
        if len(toks) < 2:
            errs.append(f"{strip}, řádek {i}: můstek musí spojovat aspoň 2 svorky („{line.strip()}“)")
            continue
        missing = [t for t in toks if t not in existing]
        if missing:
            errs.append(f"{strip}, řádek {i}: svorka {', '.join(missing)} na svorkovnici {strip} není")
        for t in toks:
            if t in seen and seen[t] != i:
                errs.append(f"{strip}, řádek {i}: svorka {t} je už v můstku na řádku {seen[t]}")
            seen.setdefault(t, i)
    return errs
