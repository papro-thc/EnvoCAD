"""Primitivní změny modelu pro příkazový řádek (bez Qt).

Každá funkce mění projekt na místě stejnými funkcemi modelu jako `ui/commands.py` (navázané změny přívodů/vývodů
`feed_*_followups`, `rename_followups`, přejmenování umístění `rename_structure`). Undo tu není: příkazy běží
v transakci runneru (snímek `sheets_state` před a po → `ChangeSet`). Shodu výsledku s QUndoCommandy hlídá
`tests/test_cmd_parity.py`. Pomocné výpočty navázaných změn (`wire_conductor_followups`, `feed_link_followups`,
`feed_dir_followups`, `renames_location`) používá i `ui/commands.py` – jedna implementace.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from envocad.model.grid import snap
from envocad.model.multipole import branch_conductors, default_conductors
from envocad.model.project import (
    FEED_SYMBOLS,
    INTERRUPT_SYMBOL,
    LOC,
    WIRE_ATTRIBUTES,
    ConductorChange,
    Element,
    Layout,
    Project,
    Sheet,
    SheetText,
    StructureId,
    TextChange,
    Wire,
    WireEnd,
    _uid,
    apply_conductor_changes,
    apply_text_changes,
    copy_fragment,
    detach_element_attrs,
    detach_wire_attrs,
    effective_feed_wire,
    feed_conductor_changes,
    feed_conductor_followups,
    feed_dir_changes,
    feed_link_attrs,
    feed_port_followups,
    internal_wires,
    is_contact,
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
    els, wires = paste_fragment(project, copy_fragment(sheet, ids), lambda sid: lib.get_symbol(sid).iec_ref, dx, dy,
                                target=sheet)
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
    w.attrs["ref"] = "" if internal_wires(sheet) else project.next_ref("W")   # vnitřní vodič rozvaděče bez W
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


# ---- listy -------------------------------------------------------------------------------------------------------
@dataclass
class SheetCopy:
    """Výsledek `duplicate_sheet`: nový list (už vložený do `project.sheets`), u listu rozvaděče s blokem nový blok
    ROZVADĚČ (vložený do nadřazeného listu `parent`) a zobrazení id originálu → kopie."""
    sheet: Sheet
    block: Element | None = None
    parent: Sheet | None = None
    element_ids: dict[str, str] = field(default_factory=dict)
    wire_ids: dict[str, str] = field(default_factory=dict)


def _ref_prefix_of(lib):
    """Předpona označení značky pro `paste_fragment`; značka, kterou knihovna nezná, je bez předpony (označení
    kopie zůstane) – duplikace listu kvůli ní nesmí spadnout."""
    def prefix(symbol_id: str) -> str:
        try:
            return lib.get_symbol(symbol_id).iec_ref
        except KeyError:
            return ""
    return prefix


def _copy_name(project: Project, name: str) -> str:
    """„<název> – kopie“, při kolizi „– kopie 2“…"""
    taken = {s.name for s in project.sheets}
    cand, n = f"{name} – kopie", 1
    while cand in taken:
        n += 1
        cand = f"{name} – kopie {n}"
    return cand


def _free_designation(project: Project, ref: str) -> str:
    """Nejbližší volné označení tvaru předpona + číslo od `ref` výš (vůči označením prvků, `loc` listů a kódům „+“
    v registru); `ref` jiného tvaru → "". Volné `ref` zůstane."""
    m = re.fullmatch(r"([^\d\s]+)(\d+)", ref or "")
    if not m:
        return ""
    taken = (project.used_refs() | {s.loc for s in project.sheets}
             | {x.code for x in project.structures if x.aspect == LOC})
    n = int(m.group(2))
    while f"{m.group(1)}{n}" in taken:
        n += 1
    return f"{m.group(1)}{n}"


def _duplicate_schematic(project: Project, sheet: Sheet, lib, new: Sheet) -> tuple[dict[str, str], dict[str, str]]:
    """Prvky a vodiče schématu přečíslované jako kopie přes schránku (`copy_fragment` + `paste_fragment`)."""
    ids = [e.id for e in sheet.elements]
    els, wires = paste_fragment(project, copy_fragment(sheet, ids), _ref_prefix_of(lib), 0.0, 0.0,
                                target=new)
    idmap = {e.id: ne.id for e, ne in zip(sheet.elements, els)}
    kept = [w for w in sheet.wires if w.a.element_id in idmap and w.b.element_id in idmap]
    for e, ne in zip(sheet.elements, els):
        ne.mp_pos, ne.sl_pos = e.mp_pos, e.sl_pos          # ruční polohy jsou geometrie, ne číslování
    # přerušovací body párují protějšky označením – kopie ho nemá; kontakt jde s cívkou / přístrojem, který se
    # přečísloval (K1 → K2), kontakt bez přístroje na listu si nechá své označení
    device_ref: dict[str, str] = {}
    for e, ne in zip(sheet.elements, els):
        if e.ref and not is_contact(e) and e.symbol_id != INTERRUPT_SYMBOL:
            device_ref.setdefault(e.ref, ne.ref)
    for e, ne in zip(sheet.elements, els):
        if e.symbol_id == INTERRUPT_SYMBOL:
            ne.attrs["ref"] = ""
        elif is_contact(e) and e.ref in device_ref:
            ne.attrs["ref"] = device_ref[e.ref]
    new.elements, new.wires = els, wires
    return idmap, {w.id: nw.id for w, nw in zip(kept, wires)}


def _duplicate_switchboard(sheet: Sheet, new: Sheet) -> tuple[dict[str, str], dict[str, str]]:
    """List rozvaděče: označení prvků (i `terminal`) a vodičů zůstanou, vazby na originál se odpojí (přívod bez
    `wire_id`, vodič bez `cable_id`); můstky a rozložení se zkopírují s přemapovanými id prvků."""
    idmap: dict[str, str] = {}
    for e in sheet.elements:
        ne = copy.deepcopy(e)
        ne.id = _uid()
        ne.attrs = detach_element_attrs(e.symbol_id, e.attrs)
        if "sheet" in ne.attrs:
            ne.attrs["sheet"] = ""            # vnořený blok ROZVADĚČ: kopie nemá list (jako `paste_fragment`)
        idmap[e.id] = ne.id
        new.elements.append(ne)
    wire_ids: dict[str, str] = {}
    for w in sheet.wires:
        nw = copy.deepcopy(w)
        nw.id = _uid()
        nw.a, nw.b = WireEnd(idmap.get(w.a.element_id, w.a.element_id), w.a.port), \
            WireEnd(idmap.get(w.b.element_id, w.b.element_id), w.b.port)
        nw.attrs = detach_wire_attrs(w.attrs)
        wire_ids[w.id] = nw.id
        new.wires.append(nw)
    new.bridges = copy.deepcopy(sheet.bridges)
    d = sheet.layout.to_dict()
    for pl in d["placements"]:
        pl["element_id"] = idmap.get(pl["element_id"], pl["element_id"])
    new.layout = Layout.from_dict(d)
    return idmap, wire_ids


def duplicate_sheet(project: Project, sheet: Sheet, lib) -> SheetCopy:
    """Zduplikuje list a vloží kopii hned za originál (`Project.sheets`); originál se nemění, revizní značky a
    připomínky se nekopírují.

    Schéma: prvky a vodiče se přečíslují jako při kopii (`paste_fragment`), přerušovací body v kopii nemají
    označení, kontakty sledují přečíslovanou cívku. List rozvaděče: označení prvků zůstanou a kopie se přeznačí –
    blok ROZVADĚČ na nadřazeném listu se zkopíruje (nové označení = umístění kopie, záznam „+“ v registru, název
    listu); bez bloku dostane kopie další volné umístění. Při vložení do listu mění jen `project.sheets`,
    `project.structures` a nadřazený list (undo: `ui.commands.DuplicateSheetCommand`)."""
    new = Sheet(name=_copy_name(project, sheet.name), paper=sheet.paper, width=sheet.width, height=sheet.height,
                kind=sheet.kind, func=sheet.func, loc=sheet.loc, mp_paper=sheet.mp_paper)
    new.texts = [SheetText(t.x, t.y, t.text, t.height) for t in sheet.texts]
    if not sheet.is_switchboard:
        idmap, wire_ids = _duplicate_schematic(project, sheet, lib, new)
        project.sheets.insert(project.sheets.index(sheet) + 1, new)
        return SheetCopy(new, element_ids=idmap, wire_ids=wire_ids)
    idmap, wire_ids = _duplicate_switchboard(sheet, new)
    parent = project.sheet_of_element(sheet.parent_element_id) if sheet.parent_element_id else None
    block = parent.element(sheet.parent_element_id) if parent is not None else None
    if block is None:
        new.parent_element_id, new.loc = None, _free_designation(project, sheet.loc)
        project.sheets.insert(project.sheets.index(sheet) + 1, new)
        return SheetCopy(new, element_ids=idmap, wire_ids=wire_ids)
    # blok existující logikou kopie prvků (označení RDC1 → RDC2); kolize s `loc` listů a kódy „+“ → další volné číslo
    els, _ = paste_fragment(project, copy_fragment(parent, [block.id]), _ref_prefix_of(lib),
                            target=parent)
    nb = els[0]
    free = _free_designation(project, nb.ref)
    if free:
        nb.attrs["ref"] = free
    old = block.ref
    if old and (sheet.name == old or sheet.name.startswith(old + " ")) and nb.ref:
        new.name = nb.ref + sheet.name[len(old):]
        if new.name in {s.name for s in project.sheets}:
            new.name = _copy_name(project, sheet.name)
    new.parent_element_id, new.loc = nb.id, nb.ref
    nb.attrs["sheet"] = new.name
    parent.elements.append(nb)
    if nb.ref and project.structure(LOC, nb.ref) is None:
        project.structures.append(StructureId(LOC, nb.ref, nb.attrs.get("desc", "")))
    project.sheets.insert(project.sheets.index(sheet) + 1, new)
    return SheetCopy(new, nb, parent, idmap, wire_ids)
