"""Primitivní změny modelu pro příkazový řádek (bez Qt).

Každá funkce mění projekt na místě stejnými funkcemi modelu jako `ui/commands.py` (navázané změny přívodů/vývodů
`feed_*_followups`, `rename_followups`, přejmenování umístění `rename_structure`). Undo tu není: příkazy běží
v transakci runneru (snímek `sheets_state` před a po → `ChangeSet`). Shodu výsledku s QUndoCommandy hlídá
`tests/test_cmd_parity.py`. Pomocné výpočty navázaných změn (`wire_conductor_followups`, `feed_link_followups`,
`feed_dir_followups`, `renames_location`) používá i `ui/commands.py` – jedna implementace.
"""
from __future__ import annotations

from envocad.model.grid import snap
from envocad.model.multipole import branch_conductors, default_conductors
from envocad.model.project import (
    FEED_SYMBOLS,
    WIRE_ATTRIBUTES,
    ConductorChange,
    Element,
    Project,
    Sheet,
    TextChange,
    Wire,
    WireEnd,
    apply_conductor_changes,
    apply_text_changes,
    copy_fragment,
    effective_feed_wire,
    feed_conductor_changes,
    feed_conductor_followups,
    feed_dir_changes,
    feed_link_attrs,
    feed_port_followups,
    paste_fragment,
    rename_followups,
    rename_structure,
)

TERMINAL_SYMBOLS = ("sb.terminal_block", "fve.terminal")   # skupiny svorek sdílejí označení svorkovnice


# ---- navázané změny (sdílí ui/commands.py) ----------------------------------------------------------------------
def wire_conductor_followups(project: Project, wires) -> list[ConductorChange]:
    """Vložené / změněné vodiče JPS předají žíly vodičům rozvaděče u navázaných přívodů (provede a vrátí změny)."""
    out: list[ConductorChange] = []
    for w in wires:
        ch = feed_conductor_followups(project, w)
        apply_conductor_changes(project, ch)
        out += ch
    return out


def feed_link_followups(project: Project, sheet: Sheet, feed: Element, attrs: bool = False
                        ) -> tuple[list[TextChange], list[ConductorChange]]:
    """Přívod/vývod `feed` listu rozvaděče s vazbou na vodič JPS: konec vodiče na bloku se přejmenuje podle
    označení přívodu (`feed_port_followups`) a vodiče u přívodu převezmou jeho žíly (`feed_conductor_changes`).
    S `attrs` navíc odvozené atributy vazby (odkud/kam, kabel) jako navázaná změna (chybějící klíč = `old` None).
    Změny provede a vrátí (porty, žíly)."""
    if feed.symbol_id not in FEED_SYMBOLS or not sheet.is_switchboard:
        return [], []
    ports = feed_port_followups(project, sheet, feed, feed.ref)
    if attrs:
        for k, v in feed_link_attrs(project, sheet, feed, feed.attrs.get("wire_id", "")).items():
            cur = feed.attrs.get(k)
            if k != "wire_id" and cur != v and not (cur is None and v == ""):
                ports.append(TextChange("element", feed.id, k, cur, v))
    apply_text_changes(project, ports)
    conds: list[ConductorChange] = []
    w = effective_feed_wire(project, sheet, feed)
    if w is not None:
        conds = feed_conductor_changes(sheet, feed, w)
        apply_conductor_changes(project, conds)
    return ports, conds


def feed_elements_followups(project: Project, sheet: Sheet, elements
                            ) -> tuple[list[TextChange], list[ConductorChange]]:
    """Vložené přívody/vývody s ruční vazbou (`wire_id`) – follow-upy jako u změny `wire_id`."""
    ports: list[TextChange] = []
    conds: list[ConductorChange] = []
    for e in elements:
        if e.attrs.get("wire_id"):
            p, c = feed_link_followups(project, sheet, e)
            ports += p
            conds += c
    return ports, conds


def feed_dir_followups(project: Project, sheet: Sheet, e: Element) -> list[TextChange]:
    """Směr přívodu/vývodu: odkud ↔ kam (`feed_dir_changes`) jako navázané změny (provede a vrátí)."""
    from envocad.model.feed import is_feed
    if not is_feed(e):
        return []
    ch = [TextChange("element", e.id, k, e.attrs.get(k), v) for k, v in feed_dir_changes(project, sheet, e).items()]
    apply_text_changes(project, ch)
    return ch


def renames_location(project: Project, sheet: Sheet, element_id: str, old: str, new: str) -> bool:
    """Přejmenování bloku = umístění (`LOCATION_SYMBOLS`) přejmenuje i kód „+“ v projektu, když starý kód je známý
    (registr nebo použitý) a nový ne."""
    from envocad.model.designation import LOCATION_SYMBOLS
    if not old or not new or sheet.element(element_id).symbol_id not in LOCATION_SYMBOLS:
        return False
    used = {s.loc for s in project.sheets} | {e.attrs.get("loc", "") for s in project.sheets for e in s.elements}

    def known(code: str) -> bool:
        return project.structure("+", code) is not None or code in used
    return known(old) and not known(new)


# ---- prvky -------------------------------------------------------------------------------------------------------
def new_element(project: Project, lib, symbol_id: str, x: float, y: float, rotation: int = 0,
                mirror: bool = False) -> Element:
    """Nový prvek jako při vložení myší (`canvas` režim PLACE): poloha na mřížce, výchozí atributy značky,
    další volné označení podle `iec_ref`. Do listu ho vloží `insert_element`."""
    sym = lib.get_symbol(symbol_id)
    e = Element(symbol_id=sym.id, x=snap(x), y=snap(y), rotation=int(rotation) % 360, mirror=bool(mirror))
    e.attrs = {a.key: a.default for a in sym.attributes}
    e.attrs["ref"] = project.next_ref(sym.iec_ref)
    return e


def insert_element(project: Project, sheet: Sheet, element: Element) -> None:
    """Vloží prvek do listu (jako `AddElementCommand`): přívod/vývod s `wire_id` předá vazbu (follow-upy)."""
    sheet.elements.append(element)
    feed_elements_followups(project, sheet, [element])


def remove_items(sheet: Sheet, element_ids, wire_ids=()) -> tuple[list[Element], list[Wire]]:
    """Smaže prvky a vodiče (i vodiče napojené na mazané prvky) – jako `RemoveItemsCommand`."""
    eids = set(element_ids)
    elements = [e for e in sheet.elements if e.id in eids]
    wids = set(wire_ids) | {w.id for w in sheet.wires if any(w.touches(e) for e in eids)}
    wires = [w for w in sheet.wires if w.id in wids]
    sheet.wires = [w for w in sheet.wires if w.id not in wids]
    sheet.elements = [e for e in sheet.elements if e.id not in eids]
    return elements, wires


def move_elements(project: Project, sheet: Sheet, lib, element_ids, dx: float, dy: float) -> int:
    """Posune prvky o (dx, dy); ruční lomy jejich vodičů jdou s nimi (`follow_points` jako tažení myší v GUI)."""
    from envocad.model.routing import follow_points, port_geometry
    ids = [e.id for e in sheet.elements if e.id in set(element_ids)]
    if not ids or (dx == 0 and dy == 0):
        return 0
    start = {eid: (sheet.element(eid).x, sheet.element(eid).y) for eid in ids}
    orig = {w.id: [tuple(p) for p in w.points] for w in sheet.wires
            if w.points and (w.a.element_id in start or w.b.element_id in start)}
    for eid in ids:
        e = sheet.element(eid)
        e.x, e.y = e.x + dx, e.y + dy
    for w in sheet.wires:
        if w.id not in orig:
            continue
        ends = []
        for end in (w.a, w.b):
            e = sheet.element(end.element_id)
            _, d = port_geometry(project, sheet, lib, e, end.port)
            st = start.get(end.element_id)
            ends.append((d, (e.x - st[0], e.y - st[1]) if st else (0.0, 0.0)))
        w.points = follow_points(orig[w.id], ends[0][0], ends[0][1], ends[1][0], ends[1][1])
    return len(ids)


def rotate_elements(sheet: Sheet, element_ids, delta: int = 90, base: tuple[float, float] | None = None) -> int:
    """Otočí prvky o `delta` (násobek 90°, proti směru hod. ručiček). Bez `base` každý kolem svého počátku – jako
    `RotateElementCommand` (klávesa R). Se základním bodem `base` (na mřížce) se kolem něj otočí i polohy prvků
    a ruční lomy vodičů, jejichž oba konce se otáčejí; ostatní lomy drží jako v GUI."""
    from envocad.model.symbol import rotate_point
    if delta % 90:
        raise ValueError("úhel musí být násobek 90°")
    ids = {e.id for e in sheet.elements if e.id in set(element_ids)}

    def turn(x: float, y: float) -> tuple[float, float]:
        dx, dy = rotate_point(x - base[0], y - base[1], delta % 360)
        return (base[0] + dx, base[1] + dy)
    for e in sheet.elements:
        if e.id in ids:
            e.rotation = (e.rotation + delta) % 360
            if base is not None:
                e.x, e.y = turn(e.x, e.y)
    if base is not None:
        for w in sheet.wires:
            if w.points and w.a.element_id in ids and w.b.element_id in ids:
                w.points = [turn(x, y) for x, y in w.points]
    return len(ids)


def mirror_elements(sheet: Sheet, element_ids) -> int:
    """Přepne zrcadlení prvků (`MirrorElementsCommand`)."""
    n = 0
    for e in sheet.elements:
        if e.id in set(element_ids):
            e.mirror = not e.mirror
            n += 1
    return n


def copy_elements(project: Project, sheet: Sheet, lib, element_ids, dx: float, dy: float
                  ) -> tuple[list[Element], list[Wire]]:
    """Kopie prvků a vodičů mezi nimi posunutá o (dx, dy) s novými označeními (`copy_fragment` + `paste_fragment`,
    vložení jako `PasteCommand` i s follow-upy vodičů JPS)."""
    ids = [e.id for e in sheet.elements if e.id in set(element_ids)]
    if not ids:
        return [], []
    els, wires = paste_fragment(project, copy_fragment(sheet, ids), lambda sid: lib.get_symbol(sid).iec_ref, dx, dy)
    sheet.elements.extend(els)
    sheet.wires.extend(wires)
    feed_elements_followups(project, sheet, els)
    wire_conductor_followups(project, wires)
    return els, wires


# ---- vodiče ------------------------------------------------------------------------------------------------------
def new_wire(project: Project, sheet: Sheet, a: Element, pa: str, b: Element, pb: str) -> Wire:
    """Nový vodič jako při kreslení myší: výchozí žíly podle portů (odbočka z uzlu převezme žíly vodiče uzlu),
    výchozí atributy a další volné označení „W“."""
    w = Wire(WireEnd(a.id, pa), WireEnd(b.id, pb))
    w.conductors = default_conductors(a, pa, b, pb)
    for j in (a, b):
        if j.symbol_id == "sb.junction":
            src = next((x for x in sheet.wires if x.touches(j.id)), None)
            if src is not None:                 # na jednopólový přístroj jen jedna fáze
                w.conductors = branch_conductors(list(src.conductors), b if j is a else a)
            break
    w.attrs = {at.key: at.default for at in WIRE_ATTRIBUTES}
    w.attrs["ref"] = project.next_ref("W")
    return w


def add_wire(project: Project, sheet: Sheet, wire: Wire) -> None:
    """Vloží vodič (`AddWireCommand`): vodič JPS na port bloku ROZVADĚČ předá žíly vodičům u přívodu."""
    sheet.wires.append(wire)
    wire_conductor_followups(project, [wire])


# ---- atributy ----------------------------------------------------------------------------------------------------
def set_attr(project: Project, sheet: Sheet, target_id: str, is_wire: bool, key: str, value: str) -> bool:
    """Změna atributu se stejnými navázanými změnami jako GUI (`SchematicScene.set_attr` + `SetAttrCommand`):
    `ref` prvku → `rename_followups` (popisy „od T1“, názvy listů, port vodiče JPS u přívodu) a u bloku-umístění
    přejmenování kódu „+“ (`rename_structure`); `dir` přívodu → odkud ↔ kam; `wire_id` → vazba přívodu (port, žíly,
    odvozené atributy). Vrací False, když se hodnota nemění."""
    target = next(w for w in sheet.wires if w.id == target_id) if is_wire else sheet.element(target_id)
    old = target.attrs.get(key, "")
    if old == value:
        return False
    location = texts = None
    if key == "ref" and not is_wire:
        location = renames_location(project, sheet, target_id, old, value)
        texts = rename_followups(project, target, old, value)
    target.attrs[key] = value
    if not is_wire:
        if key == "dir":
            feed_dir_followups(project, sheet, target)
        elif key == "wire_id":
            feed_link_followups(project, sheet, target, attrs=True)
    if location:
        rename_structure(project, "+", old, value)
    if texts:
        apply_text_changes(project, texts)
    return True
