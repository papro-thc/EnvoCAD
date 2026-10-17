"""Revize ve výkresu: značky (trojúhelník s označením revize) u změněných míst, uzavření revize, revize listu.
Bez Qt – geometrii kreslí Qt (`ui/render.py`) i DXF export (vrstva REVIZE) stejně.

Použití z GUI (všechny funkce mění `project.revisions` / `project.meta` – v UI je obal jedním
`ReplaceRevisionsCommand(project, before, after)`, stav před/po dá `revisions_state` – revize a jen meta klíče
`REVISION_META_KEYS`, ostatní metadata undo revize nemění):

Porovnání s revizí (`compare_revision`)::

    changes = diff_projects(old, project, lib)
    before = revisions_state(project)
    rev = open_revision(project, label, date, author)    # poslední otevřená revize, jinak nová
    apply_changes(project, rev, changes)                 # značky z porovnání (idempotentní), meta["revision"]
    after = revisions_state(project)
    restore_revisions_state(project, before)             # model zpět – změnu provede až příkaz v undo
    undo.push(ReplaceRevisionsCommand(project, *before, *after))   # redo = restore_revisions_state(after)

Uzavřít revizi / list: stejně, mezi `before` a `after` je `close_revision(project, rev[, [sheet.id]])`.

Kreslení listu: `revision_geometry(project, sheet, lib, routes)` → `RevisionGeometry` (mm, Y nahoru; `routes`
= trasy vodičů, které scéna/DXF právě kreslí, aby značka vodiče seděla na čáře).
"""
from __future__ import annotations

import copy
import math
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise

from envocad.model.diff import MOVE_DETAIL, Change, sheet_fingerprint
from envocad.model.project import Project, Revision, RevisionMark, Sheet, element_symbol
from envocad.model.symbol import GRID

MARK_MOVES = False        # pouhý posun prvku ve výkresu značku revize nevytváří
TEXT_H = 2.5              # výška písma v trojúhelníku
MIN_SIDE = 6.0            # minimální strana trojúhelníku (mm)
MARK_WHATS = {"prvek", "vodič", "můstky", "skříň", "list"}   # změny, které mají místo na listu


# ---- značky z porovnání ------------------------------------------------------------------------------------
def _is_move_only(c: Change) -> bool:
    return c.kind == "změněno" and c.what in ("prvek", "vodič") and c.detail == MOVE_DETAIL


def marks_from_changes(changes: list[Change]) -> list[RevisionMark]:
    """Značky revize ze změn `diff_projects`. Jedna značka na místo (list, prvek/vodič, resp. poloha odebraného);
    změny listu bez místa (skříň, přejmenování, označení listu, nový list) → jedna značka listu (`target_id=""`,
    bez polohy – projeví se jen v popisovém poli). Bez značky: kabely, struktury, odebrané listy, pouhý posun
    (`MARK_MOVES`) a jednotlivé prvky na zcela novém listu (je označený celý list)."""
    new_sheets = {c.sheet_id for c in changes if c.what == "list" and c.kind == "přidáno" and c.sheet_id}
    out: list[RevisionMark] = []
    index: dict[tuple, RevisionMark] = {}
    for c in changes:
        if not c.sheet_id or c.what not in MARK_WHATS:
            continue
        if _is_move_only(c) and not MARK_MOVES:
            continue
        if c.sheet_id in new_sheets and c.what != "list":
            continue
        removed = c.kind == "odebráno" and c.x is not None and c.y is not None
        if c.what in ("skříň", "list") or not (c.target_id or removed):
            key: tuple = (c.sheet_id, "", False, None, None)
            target, is_wire = "", False
        elif removed:
            key = (c.sheet_id, "", c.is_wire, round(c.x, 3), round(c.y, 3))
            target, is_wire = "", c.is_wire
        else:
            key = (c.sheet_id, c.target_id, c.is_wire, None, None)
            target, is_wire = c.target_id, c.is_wire
        text = " ".join(x for x in (c.what, c.ref, c.kind) if x) + (f": {c.detail}" if c.detail else "")
        m = index.get(key)
        if m is None:
            m = RevisionMark(c.sheet_id, target, is_wire, c.kind, c.x if removed else None, c.y if removed else None, text)
            index[key] = m
            out.append(m)
        else:
            m.text = f"{m.text}; {text}"
            if m.kind != c.kind:
                m.kind = "změněno"
    return out


# ---- práce s revizemi --------------------------------------------------------------------------------------
REVISION_META_KEYS = ("revision", "changes")   # meta klíče, které mění revize (porovnání, změnový list)


def revisions_state(project: Project) -> tuple[list[Revision], dict[str, str]]:
    """Hluboká kopie (revize, meta klíče revize `REVISION_META_KEYS`) pro undo příkaz. Ostatní metadata (investor…)
    do stavu nepatří – undo revize je nesmí vrátit."""
    meta = {k: project.meta[k] for k in REVISION_META_KEYS if k in project.meta}
    return copy.deepcopy(project.revisions), meta


def restore_revisions_state(project: Project, state: tuple[list[Revision], dict[str, str]]) -> None:
    """Vrátí stav z `revisions_state` (kopii – stav lze obnovit opakovaně, redo/undo). Z meta mění jen
    `REVISION_META_KEYS` (klíč, který ve stavu chybí, odebere)."""
    revs, meta = state
    project.revisions = copy.deepcopy(revs)
    for k in REVISION_META_KEYS:
        if k in meta:
            project.meta[k] = meta[k]
        else:
            project.meta.pop(k, None)


def closed_labels(project: Project) -> set[str]:
    """Označení uzavřených revizí."""
    return {r.label for r in project.revisions if r.closed}


def open_revision(project: Project, label: str, date: str = "", author: str = "") -> Revision:
    """Poslední otevřená (neuzavřená) revize, jinak nová na konci seznamu. Neprázdné `label`/`date`/`author`
    otevřené revizi přepíšou údaje (dialog porovnání je nabízí k úpravě). Označení, které už má uzavřená revize,
    → ValueError (projekt se nezmění)."""
    if label and label in closed_labels(project):
        raise ValueError(f"Revize {label} je už uzavřená – zadej jiné označení")
    rev = next((r for r in reversed(project.revisions) if not r.closed), None)
    if rev is None:
        base = str(project.meta.get("revision") or "").strip()
        new_label = label or next_revision_label(project)
        if not project.revisions and base and base != new_label:
            # výchozí stav výkresu (revize z vlastností projektu před prvním porovnáním) jako uzavřená revize –
            # nezměněné listy ji dál ukazují v popisovém poli (`sheet_revision`)
            project.revisions.append(Revision(base, date=str(project.meta.get("date") or ""),
                                              author=str(project.meta.get("author") or ""), closed=True,
                                              description="výchozí stav před prvním porovnáním"))
        rev = Revision(new_label, date=date, author=author)
        project.revisions.append(rev)
        return rev
    rev.label = label or rev.label
    rev.date = date or rev.date
    rev.author = author or rev.author
    return rev


def next_revision_label(project: Project) -> str:
    """Označení další revize za poslední: „A“ → „B“, „3“ → „4“, jiné → „…+“ (bez revizí „A“). Nikdy nevrátí
    označení uzavřené revize."""
    if not project.revisions:
        return "A"
    used = closed_labels(project)
    label = _increment_label(project.revisions[-1].label)
    while label in used:
        label = _increment_label(label)
    return label


def _increment_label(last: str) -> str:
    if last.isdigit():
        return str(int(last) + 1)
    if len(last) == 1 and "A" <= last.upper() < "Z":
        return chr(ord(last.upper()) + 1)
    return f"{last}+"


def apply_changes(project: Project, rev: Revision, changes: list[Change]) -> None:
    """Nahradí značky revize `rev` značkami ze `changes` (opakované porovnání = stejný výsledek). Listy, které už
    jsou v `rev` uzavřené (mají otisk), si nechají dosavadní značky. Nastaví `meta["revision"] = rev.label`."""
    if rev.closed:
        raise ValueError(f"Revize {rev.label} je uzavřená")
    frozen = set(rev.fingerprints)
    keep = [m for m in rev.marks if m.sheet_id in frozen]
    rev.marks = keep + [m for m in marks_from_changes(changes) if m.sheet_id not in frozen]
    project.meta["revision"] = rev.label


def merge_change_lines(current: str, labels: set[str] | list[str], new_text: str,
                       auto_lines: list[str] | None = None) -> str:
    """Změnový list `meta["changes"]` po porovnání do otevřené revize: řádky, které dřív vygenerovalo porovnání
    (`auto_lines` = `Revision.auto_lines`, přesné znění), se nahradí řádky `new_text`; ručně psané řádky (i se
    značkou otevřené revize) zůstanou. Opakované porovnání do téže revize tedy řádky nezdvojí.

    `auto_lines=None` (revize ze staršího souboru, vygenerované řádky neznámé): ze řádků revizí `labels` se odeberou
    jen ty, které `new_text` obsahuje beze změny (nezdvojí se); jiné řádky se nemažou – mohou být psané ručně."""
    from envocad.model.diff import split_change_line
    new = [ln for ln in (new_text or "").splitlines() if ln.strip()]
    old = [ln for ln in (current or "").splitlines() if ln.strip()]
    if auto_lines is not None:
        drop = Counter(ln.strip() for ln in auto_lines if ln.strip())
    else:
        marks = {x for x in labels if x}
        drop = Counter(ln.strip() for ln in new)
        drop = Counter({k: n for k, n in drop.items() if split_change_line(k)[0] in marks})
    kept = []
    for ln in old:
        if drop[ln.strip()] > 0:
            drop[ln.strip()] -= 1
            continue
        kept.append(ln)
    return "\n".join([*kept, *new])


def close_revision(project: Project, rev: Revision, sheet_ids: list[str] | None = None) -> None:
    """Uzavře revizi (měkký zámek): uloží otisky listů. `sheet_ids=None` = celá revize (otisky všech listů
    a `closed=True`; listy uzavřené dřív si nechají dosavadní otisk), jinak jen vybrané listy (revize zůstane
    otevřená, jejich značky se dál nemění; opakované uzavření listu otisk obnoví)."""
    if sheet_ids is None:
        for s in project.sheets:
            # list uzavřený dřív si nechá svůj otisk – jeho pozdější změna se dál hlásí (`changed_after_close`)
            # a zachytí ji porovnání do další revize
            rev.fingerprints.setdefault(s.id, sheet_fingerprint(s))
        rev.closed = True
        return
    ids = set(sheet_ids)
    for s in project.sheets:
        if s.id in ids:
            rev.fingerprints[s.id] = sheet_fingerprint(s)


def _has_mark(rev: Revision, sheet_id: str) -> bool:
    return any(m.sheet_id == sheet_id for m in rev.marks)


def sheet_revision(project: Project, sheet: Sheet) -> Revision | None:
    """Revize listu do popisového pole: poslední revize se značkou na listu. List bez značky (od začátku sledování
    nezměněný) je ve výchozím stavu – revize těsně před první revizí se značkami (výchozí stav z vlastností projektu
    zakládá `open_revision` při prvním porovnání). Není-li před ní žádná revize, vrací None a popisové pole ukáže
    prázdnou revizi (`frame.sheet_revision_label`), ne novou revizi. Projekt bez jakýchkoli značek (starý /
    migrovaný) → None = popisové pole použije `meta["revision"]`."""
    revs = project.revisions
    for r in reversed(revs):
        if _has_mark(r, sheet.id):
            return r
    first = next((i for i, r in enumerate(revs) if r.marks), None)
    if not first:            # bez značek, nebo první revize se značkami nemá předchůdce
        return None
    return revs[first - 1]


def revisions_marked(project: Project) -> bool:
    """Má některá revize značky ve výkresu (revize se sledují po listech)?"""
    return any(r.marks for r in project.revisions)


def changed_after_close(project: Project) -> list[tuple[Sheet, Revision]]:
    """Listy změněné po uzavření: poslední revize s otiskem listu má jiný otisk než list teď a žádná pozdější
    revize na listu nemá značku (změna zatím nebyla porovnána do nové revize)."""
    out = []
    for s in project.sheets:
        idx = next((i for i in range(len(project.revisions) - 1, -1, -1)
                    if s.id in project.revisions[i].fingerprints), None)
        if idx is None:
            continue
        rev = project.revisions[idx]
        if rev.fingerprints[s.id] == sheet_fingerprint(s):
            continue
        if any(_has_mark(r, s.id) for r in project.revisions[idx + 1:]):
            continue
        out.append((s, rev))
    return out


# ---- geometrie --------------------------------------------------------------------------------------------
@dataclass
class RevisionGeometry:
    polylines: list[list[tuple[float, float]]] = field(default_factory=list)          # uzavřené (poslední → první)
    texts: list[tuple[float, float, str, float, str]] = field(default_factory=list)   # jako FrameGeometry.texts


def triangle_side(label: str) -> float:
    return max(MIN_SIDE, 1.6 * len(label) + 3.0)


def triangle(x: float, y: float, label: str) -> tuple[list[tuple[float, float]], tuple[float, float, str, float, str]]:
    """Rovnostranný trojúhelník vrcholem nahoru s těžištěm v (x, y) a označením revize uvnitř.
    Vrací (3 vrcholy – uzavřený obrys, text (x, účaří y, text, výška, „center“))."""
    a = triangle_side(label)
    h = a * math.sqrt(3) / 2
    base = y - h / 3
    pts = [(x - a / 2, base), (x + a / 2, base), (x, base + h)]
    return pts, (x, base + 0.8, label, TEXT_H, "center")


def _ceil_grid(v: float) -> float:
    return math.ceil(round(v / GRID, 6)) * GRID


def _element_anchor(project: Project, sheet: Sheet, lib, eid: str) -> tuple[float, float] | None:
    from envocad.model.textlayout import symbol_box
    try:
        e = sheet.element(eid)
        _x1, _y1, x2, y2 = symbol_box(e, element_symbol(project, e, lib))
    except Exception:  # noqa: BLE001 – smazaný prvek / neznámá značka
        return None
    return (_ceil_grid(x2 + GRID), _ceil_grid(y2 + GRID))


def _wire_anchor(route: list[tuple[float, float]], side: float) -> tuple[float, float] | None:
    """Těžiště značky u středu nejdelšího úseku trasy – nad vodorovným, vpravo od svislého úseku (nepřekryje čáru)."""
    if not route:
        return None
    if len(route) == 1:
        return route[0]
    best = max(pairwise(route), key=lambda s: math.dist(s[0], s[1]))
    (ax, ay), (bx, by) = best
    mx, my = (ax + bx) / 2, (ay + by) / 2
    h = side * math.sqrt(3) / 2
    if abs(by - ay) > abs(bx - ax):           # svislý úsek → vpravo
        return (mx + side / 2 + 1.0, my)
    return (mx, my + h / 3 + 1.0)            # vodorovný (i šikmý) → nad


def revision_geometry(project: Project, sheet: Sheet, lib, routes: dict[str, list[tuple[float, float]]] | None = None,
                      revision: Revision | None = None) -> RevisionGeometry:
    """Značky revize na listu (mm, Y nahoru). `revision=None` = revize listu (`sheet_revision`).
    Prvek – pravý horní roh obálky otočené značky + 2,5 mm (na mřížce); vodič – u středu nejdelšího úseku trasy
    (`routes` z `compute_layout`/scény, jinak se trasy spočítají); odebrané – uložená poloha. Značky listu bez místa
    a značky na prvky/vodiče, které už neexistují, se nekreslí."""
    g = RevisionGeometry()
    rev = revision or sheet_revision(project, sheet)
    if rev is None:
        return g
    marks = [m for m in rev.marks if m.sheet_id == sheet.id]
    if not marks:
        return g
    label = rev.label
    side = triangle_side(label)
    wire_ids = {w.id for w in sheet.wires}
    if routes is None and any(m.is_wire and m.target_id in wire_ids for m in marks):
        from envocad.model.routing import route_sheet
        try:
            routes = route_sheet(project, sheet, lib)
        except Exception:  # noqa: BLE001
            routes = {}
    routes = routes or {}
    seen: set[tuple[float, float]] = set()
    for m in marks:
        if m.x is not None and m.y is not None:
            pos: tuple[float, float] | None = (m.x, m.y)
        elif not m.target_id:
            continue
        elif m.is_wire:
            if m.target_id not in wire_ids:
                continue
            w = next(w for w in sheet.wires if w.id == m.target_id)
            route = routes.get(w.id)
            if not route:
                from envocad.model.routing import wire_route
                try:
                    route = wire_route(project, sheet, lib, w)
                except Exception:  # noqa: BLE001 – vodič na neexistující prvek/port → aspoň ruční lomy
                    route = [tuple(p) for p in w.points]
            pos = _wire_anchor(route, side)
        else:
            pos = _element_anchor(project, sheet, lib, m.target_id)
        if pos is None:
            continue
        key = (round(pos[0], 2), round(pos[1], 2))
        if key in seen:                       # dvě značky na stejném místě kreslit jednou
            continue
        seen.add(key)
        pts, text = triangle(pos[0], pos[1], label)
        g.polylines.append(pts)
        g.texts.append(text)
    return g
