"""Undo/redo příkazy – jediné místo, kde GUI mění model."""
from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from envocad.model.project import Element, Wire


class AddElementCommand(QUndoCommand):
    def __init__(self, scene, element: Element):
        super().__init__(f"Vložit {element.ref or element.symbol_id}")
        self.scene, self.element = scene, element

    def redo(self):
        self.scene.sheet.elements.append(self.element)
        self.scene.add_element_item(self.element)

    def undo(self):
        self.scene.sheet.remove_element(self.element.id)
        self.scene.remove_element_item(self.element.id)


class RemoveItemsCommand(QUndoCommand):
    def __init__(self, scene, element_ids: list[str], wire_ids: list[str]):
        super().__init__("Smazat")
        self.scene = scene
        sheet = scene.sheet
        self.elements = [sheet.element(e) for e in element_ids]
        wires = {w.id: w for w in sheet.wires if w.id in wire_ids}
        for e in self.elements:  # vodiče napojené na mazané elementy jdou pryč také
            for w in sheet.wires:
                if w.touches(e.id):
                    wires[w.id] = w
        self.wires = list(wires.values())
        # původní pořadí v listu – undo vrací prvky i vodiče na stejné místo (pořadí určuje číslování a rozmístění)
        self.el_idx = sorted((sheet.elements.index(e), e) for e in self.elements)
        self.w_idx = sorted((sheet.wires.index(w), w) for w in self.wires)

    def redo(self):
        s = self.scene.sheet
        wid = {w.id for w in self.wires}
        eid = {e.id for e in self.elements}
        s.wires = [w for w in s.wires if w.id not in wid]
        s.elements = [e for e in s.elements if e.id not in eid]
        for w in self.wires:
            self.scene.remove_wire_item(w.id)
        for e in self.elements:
            self.scene.remove_element_item(e.id)

    def undo(self):
        s = self.scene.sheet
        for i, e in self.el_idx:
            s.elements.insert(i, e)
            self.scene.add_element_item(e)
        for i, w in self.w_idx:
            s.wires.insert(i, w)
            self.scene.add_wire_item(w)


class MoveElementsCommand(QUndoCommand):
    """Posun už proběhl interaktivně; první redo() se přeskočí."""

    def __init__(self, scene, moves: dict[str, tuple[tuple[float, float], tuple[float, float]]],
                 wire_points: dict[str, tuple[list, list]] | None = None):
        super().__init__("Posunout")
        self.scene, self.moves, self._first = scene, moves, True
        self.wire_points = wire_points or {}   # ruční lomy vodičů, které se posunuly s prvky: {id: (před, po)}

    def _apply(self, idx: int):
        sc = self.scene
        sc._dragging = False
        for wid, pair in self.wire_points.items():
            w = next((x for x in sc.sheet.wires if x.id == wid), None)
            if w is not None:
                w.points = [tuple(p) for p in pair[idx]]
        for eid, pair in self.moves.items():
            e = sc.sheet.element(eid)
            e.x, e.y = pair[idx]
            sc.element_items[eid].sync_from_model()
            sc.update_wires_of(eid)

    def redo(self):
        if self._first:
            self._first = False
            return
        self._apply(1)

    def undo(self):
        self._apply(0)


class SetWirePointsCommand(QUndoCommand):
    """Ruční lomy vodičů (posun úseku, narovnání): {id vodiče: (staré body, nové body)}."""

    def __init__(self, scene, changes: dict[str, tuple[list, list]], text: str = "Upravit trasu vodiče"):
        super().__init__(text)
        self.scene, self.changes = scene, changes

    def _apply(self, idx: int):
        for wid, pair in self.changes.items():
            w = next((x for x in self.scene.sheet.wires if x.id == wid), None)
            if w is None:
                continue
            w.points = [tuple(p) for p in pair[idx]]
            it = self.scene.wire_items.get(wid)
            if it is not None:
                self.scene._route(it)

    def redo(self):
        self._apply(1)

    def undo(self):
        self._apply(0)


class RotateElementCommand(QUndoCommand):
    def __init__(self, scene, element_id: str, delta: int = 90):
        super().__init__("Otočit")
        self.scene, self.eid, self.delta = scene, element_id, delta

    def _rot(self, d: int):
        e = self.scene.sheet.element(self.eid)
        e.rotation = (e.rotation + d) % 360
        self.scene.element_items[self.eid].sync_from_model()
        self.scene.update_wires_of(self.eid)

    def redo(self):
        self._rot(self.delta)

    def undo(self):
        self._rot(-self.delta)


class AddWireCommand(QUndoCommand):
    def __init__(self, scene, wire: Wire):
        super().__init__("Vodič")
        self.scene, self.wire = scene, wire

    def redo(self):
        self.scene.sheet.wires.append(self.wire)
        self.scene.add_wire_item(self.wire)

    def undo(self):
        self.scene.sheet.wires = [w for w in self.scene.sheet.wires if w.id != self.wire.id]
        self.scene.remove_wire_item(self.wire.id)


class SplitWireCommand(QUndoCommand):
    """T-odbočka: vodič se rozdělí uzlem (sb.junction) na dva díly; z volného portu uzlu pak vede odbočka."""

    def __init__(self, scene, wire_id: str, junction: Element, w1: Wire, w2: Wire):
        super().__init__("Odbočka na vodiči")
        self.scene = scene
        self.old = next(w for w in scene.sheet.wires if w.id == wire_id)
        self.old_idx = scene.sheet.wires.index(self.old)
        self.junction, self.w1, self.w2 = junction, w1, w2

    def redo(self):
        s = self.scene.sheet
        s.wires = [w for w in s.wires if w.id != self.old.id]
        self.scene.remove_wire_item(self.old.id)
        s.elements.append(self.junction)
        self.scene.add_element_item(self.junction)
        for w in (self.w1, self.w2):
            s.wires.append(w)
            self.scene.add_wire_item(w)

    def undo(self):
        s = self.scene.sheet
        s.wires = [w for w in s.wires if w.id not in (self.w1.id, self.w2.id)]
        for w in (self.w1, self.w2):
            self.scene.remove_wire_item(w.id)
        s.elements = [e for e in s.elements if e.id != self.junction.id]
        self.scene.remove_element_item(self.junction.id)
        s.wires.insert(self.old_idx, self.old)
        self.scene.add_wire_item(self.old)


class SetAttrCommand(QUndoCommand):
    def __init__(self, scene, target_id: str, is_wire: bool, key: str, old: str, new: str):
        super().__init__(f"Změnit {key}")
        self.scene, self.tid, self.is_wire, self.key, self.old, self.new = scene, target_id, is_wire, key, old, new
        self.had_key = key in self._target().attrs   # undo nového atributu ho zase odebere

    def _target(self):
        if self.is_wire:
            return next(w for w in self.scene.sheet.wires if w.id == self.tid)
        return self.scene.sheet.element(self.tid)

    def _set(self, v: str, remove: bool = False):
        t = self._target()
        if remove:
            t.attrs.pop(self.key, None)
        else:
            t.attrs[self.key] = v
        (self.scene.wire_items if self.is_wire else self.scene.element_items)[self.tid].update()
        if hasattr(self.scene, "invalidate_text_layout"):
            self.scene.invalidate_text_layout()   # popisek (ref / aspekty) se přepočítá
        self.scene.attrs_changed.emit(self.tid)

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old, remove=not self.had_key)


class SetComponentCommand(QUndoCommand):
    def __init__(self, scene, element_id: str, old: str | None, new: str | None):
        super().__init__("Přiřadit artikl")
        self.scene, self.eid, self.old, self.new = scene, element_id, old, new

    def _set(self, v):
        e = self.scene.sheet.element(self.eid)
        e.component_id = v
        self.scene.element_items[self.eid].update()
        self.scene.attrs_changed.emit(self.eid)

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old)


def _refresh_wire(scene, wid: str) -> None:
    """JPS scéna má položky vodičů; odvozené scény (vícepól) se celé přestaví."""
    items = getattr(scene, "wire_items", None)
    if items is not None:
        if wid in items:
            items[wid].update()
        scene.attrs_changed.emit(wid)
    else:
        scene.rebuild()


class SetConductorsCommand(QUndoCommand):
    """Změna seznamu žil vodiče (vícepól)."""

    def __init__(self, scene, wire_id: str, old: list[str], new: list[str]):
        super().__init__("Změnit žíly vodiče")
        self.scene, self.wid, self.old, self.new = scene, wire_id, list(old), list(new)

    def _set(self, v: list[str]):
        w = next(w for w in self.scene.sheet.wires if w.id == self.wid)
        w.conductors = list(v)
        w.terminals = {c: t for c, t in w.terminals.items() if c in w.conductors}
        _refresh_wire(self.scene, self.wid)

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old)


class SetTerminalsCommand(QUndoCommand):
    """Přiřazení svorek žilám vodiče (`Wire.terminals`)."""

    def __init__(self, scene, wire_id: str, old: dict, new: dict):
        super().__init__("Přiřadit svorky")
        self.scene, self.wid = scene, wire_id
        self.old = {c: dict(t) for c, t in old.items()}
        self.new = {c: dict(t) for c, t in new.items()}

    def _set(self, v: dict):
        w = next(w for w in self.scene.sheet.wires if w.id == self.wid)
        w.terminals = {c: dict(t) for c, t in v.items()}
        _refresh_wire(self.scene, self.wid)

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old)


class SetBridgesCommand(QUndoCommand):
    """Můstky jedné svorkovnice na listu (`Sheet.bridges[strip]`)."""

    def __init__(self, project, sheet, strip: str, old: list[list[str]], new: list[list[str]], on_change=None):
        super().__init__(f"Můstky {strip}")
        self.project, self.sheet, self.strip = project, sheet, strip
        self.old, self.new, self.on_change = [list(g) for g in old], [list(g) for g in new], on_change

    def _set(self, v):
        self.project.set_bridges(self.strip, v, self.sheet)
        if self.on_change:
            self.on_change()

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old)


class PasteCommand(QUndoCommand):
    """Vložení kopie prvků a vodičů ze schránky."""

    def __init__(self, scene, elements: list[Element], wires: list[Wire]):
        super().__init__(f"Vložit kopii ({len(elements)})")
        self.scene, self.elements, self.wires = scene, elements, wires

    def redo(self):
        for e in self.elements:
            self.scene.sheet.elements.append(e)
            self.scene.add_element_item(e)
        for w in self.wires:
            self.scene.sheet.wires.append(w)
            self.scene.add_wire_item(w)
        self.scene.clearSelection()
        for e in self.elements:
            self.scene.element_items[e.id].setSelected(True)

    def undo(self):
        wid = {w.id for w in self.wires}
        eid = {e.id for e in self.elements}
        s = self.scene.sheet
        s.wires = [w for w in s.wires if w.id not in wid]
        s.elements = [e for e in s.elements if e.id not in eid]
        for w in self.wires:
            self.scene.remove_wire_item(w.id)
        for e in self.elements:
            self.scene.remove_element_item(e.id)


class MoveMultipoleCommand(QUndoCommand):
    """Ruční pozice prvků ve vícepólu (`Element.mp_pos`; None = automatické rozmístění)."""

    def __init__(self, scene, moves: dict):
        super().__init__("Posun ve vícepólu")
        self.scene, self.moves = scene, moves

    def _apply(self, idx: int):
        for eid, pair in self.moves.items():
            e = self.scene.sheet.element(eid)
            e.mp_pos = tuple(pair[idx]) if pair[idx] else None
        self.scene.rebuild()

    def redo(self):
        self._apply(1)

    def undo(self):
        self._apply(0)


class MultipoleAddCommand(QUndoCommand):
    """Vložení prvku nebo žíly přímo ve vícepólu (schématu rozvaděče): zapíše se do modelu listu, pohled se přestaví."""

    def __init__(self, scene, element: Element | None = None, wire: Wire | None = None,
                 elements: list[Element] | None = None, wires: list[Wire] | None = None):
        self.elements = ([element] if element is not None else []) + list(elements or [])
        self.wires = ([wire] if wire is not None else []) + list(wires or [])
        super().__init__("Vložit prvek" if self.elements and len(self.elements) == 1 and not self.wires
                         else ("Vodič" if not self.elements else f"Vložit ({len(self.elements)})"))
        self.scene = scene

    def redo(self):
        s = self.scene.sheet
        s.elements.extend(self.elements)
        s.wires.extend(self.wires)
        self.scene.rebuild()
        if getattr(self.scene, "after_edit", None):
            self.scene.after_edit()   # jednopólová editace téhož listu se přestaví

    def undo(self):
        s = self.scene.sheet
        wid = {w.id for w in self.wires}
        eid = {e.id for e in self.elements}
        s.wires = [w for w in s.wires if w.id not in wid]
        s.elements = [e for e in s.elements if e.id not in eid]
        self.scene.rebuild()
        if getattr(self.scene, "after_edit", None):
            self.scene.after_edit()


class SetCableCommand(QUndoCommand):
    """Změna kabelu (žíly, barvy, stínění, poznámka, artikl)."""

    def __init__(self, project, cable_id: str, old: dict, new: dict):
        super().__init__(f"Kabel {new.get('ref', '')}")
        self.project, self.cid, self.old, self.new = project, cable_id, old, new

    def _set(self, d: dict):
        from envocad.model.project import Cable
        for i, c in enumerate(self.project.cables):
            if c.id == self.cid:
                self.project.cables[i] = Cable.from_dict(d)
                return

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old)


class SetSheetDesignationCommand(QUndoCommand):
    """Strukturní označení listu: dvojice (func, loc) – `Sheet.func` (=) a `Sheet.loc` (+)."""

    def __init__(self, sheet, old: tuple[str, str], new: tuple[str, str], on_change=None):
        super().__init__("Změnit označení listu")
        self.sheet, self.old, self.new, self.on_change = sheet, tuple(old), tuple(new), on_change

    def _set(self, v: tuple[str, str]):
        self.sheet.func, self.sheet.loc = v
        if self.on_change:
            self.on_change()

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old)


class RenameStructureCommand(QUndoCommand):
    """Přejmenování kódu funkce/umístění v celém projektu (registr, listy, override prvků) přes `rename_structure`."""

    def __init__(self, project, aspect: str, old: str, new: str, on_change=None):
        super().__init__(f"Přejmenovat {aspect}{old} na {aspect}{new}")
        self.project, self.aspect, self.old, self.new, self.on_change = project, aspect, old, new, on_change

    def _rename(self, a: str, b: str):
        from envocad.model.project import rename_structure
        rename_structure(self.project, self.aspect, a, b)
        if self.on_change:
            self.on_change()

    def redo(self):
        self._rename(self.old, self.new)

    def undo(self):
        self._rename(self.new, self.old)


class SetStructuresCommand(QUndoCommand):
    """Registr strukturního označení projektu (dialog Projekt → Strukturní označení)."""

    def __init__(self, project, old_list: list, new_list: list, on_change=None):
        super().__init__("Strukturní označení")
        from envocad.model.project import StructureId
        self.project, self.on_change = project, on_change
        self.old = [StructureId(x.aspect, x.code, x.description) for x in old_list]
        self.new = [StructureId(x.aspect, x.code, x.description) for x in new_list]

    def _set(self, v: list):
        from envocad.model.project import StructureId
        self.project.structures = [StructureId(x.aspect, x.code, x.description) for x in v]
        if self.on_change:
            self.on_change()

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old)


class ReplaceRevisionsCommand(QUndoCommand):
    """Nahrazení revizí a metadat (`project.revisions`, `project.meta`) – porovnání s revizí, uzavření revize.
    `old_state`/`new_state` = `(revize, meta)` z `revision.revisions_state`."""

    def __init__(self, project, old_state, new_state, text: str = "Revize", on_change=None):
        super().__init__(text)
        import copy
        self.project, self.on_change = project, on_change
        self.old = (copy.deepcopy(old_state[0]), dict(old_state[1]))
        self.new = (copy.deepcopy(new_state[0]), dict(new_state[1]))

    def _set(self, state):
        from envocad.model.revision import restore_revisions_state
        restore_revisions_state(self.project, state)
        if self.on_change:
            self.on_change()

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old)
