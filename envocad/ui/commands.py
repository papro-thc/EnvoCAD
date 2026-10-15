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
        for e in self.elements:
            s.elements.append(e)
            self.scene.add_element_item(e)
        for w in self.wires:
            s.wires.append(w)
            self.scene.add_wire_item(w)


class MoveElementsCommand(QUndoCommand):
    """Posun už proběhl interaktivně; první redo() se přeskočí."""

    def __init__(self, scene, moves: dict[str, tuple[tuple[float, float], tuple[float, float]]]):
        super().__init__("Posunout")
        self.scene, self.moves, self._first = scene, moves, True

    def _apply(self, idx: int):
        for eid, pair in self.moves.items():
            e = self.scene.sheet.element(eid)
            e.x, e.y = pair[idx]
            self.scene.element_items[eid].sync_from_model()
            self.scene.update_wires_of(eid)

    def redo(self):
        if self._first:
            self._first = False
            return
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


class SetAttrCommand(QUndoCommand):
    def __init__(self, scene, target_id: str, is_wire: bool, key: str, old: str, new: str):
        super().__init__(f"Změnit {key}")
        self.scene, self.tid, self.is_wire, self.key, self.old, self.new = scene, target_id, is_wire, key, old, new

    def _set(self, v: str):
        if self.is_wire:
            w = next(w for w in self.scene.sheet.wires if w.id == self.tid)
            w.attrs[self.key] = v
            self.scene.wire_items[self.tid].update()
        else:
            e = self.scene.sheet.element(self.tid)
            e.attrs[self.key] = v
            self.scene.element_items[self.tid].update()
        self.scene.attrs_changed.emit(self.tid)

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old)


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
    """Můstky jedné svorkovnice (`Project.bridges[strip]`)."""

    def __init__(self, project, strip: str, old: list[list[str]], new: list[list[str]], on_change=None):
        super().__init__(f"Můstky {strip}")
        self.project, self.strip = project, strip
        self.old, self.new, self.on_change = [list(g) for g in old], [list(g) for g in new], on_change

    def _set(self, v):
        self.project.set_bridges(self.strip, v)
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
