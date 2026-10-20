"""Undo/redo příkazy – jediné místo, kde GUI mění model."""
from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from envocad.model.project import Element, Wire


class _FeedFollowups:
    """Navázané změny u přívodů/vývodů rozvaděče (žíly vodičů rozvaděče `feed_conductor_followups`, port vodiče
    JPS na bloku `feed_port_followups`, u ruční vazby i odvozené odkud/kam a kabel). Vyvolá je vložení vodiče JPS,
    vložení přívodu/vývodu s `wire_id` (`AddElementCommand`, `PasteCommand`, `MultipoleAddCommand`) i změna
    `wire_id` (`SetAttrCommand`). Spočítají se při prvním redo po hlavní změně, další redo je zopakuje beze změny
    a undo je vrátí před hlavní změnou – synchronizace mimo undo je už nedělá."""

    _ports: list | None = None
    _conds: list | None = None

    def _followups_redo(self, compute) -> None:
        from envocad.model.project import apply_conductor_changes, apply_text_changes
        project = getattr(self.scene, "project", None)
        if project is None:
            return
        if self._ports is None:
            self._ports, self._conds = [], []
            compute(project)        # naplní _ports / _conds a rovnou je provede (výpočet závisí na pořadí)
        else:
            apply_text_changes(project, self._ports)
            apply_conductor_changes(project, self._conds)
        self._notify_followups()

    def _followups_undo(self) -> None:
        from envocad.model.project import apply_conductor_changes, apply_text_changes
        project = getattr(self.scene, "project", None)
        if project is None or self._ports is None:
            return
        apply_conductor_changes(project, self._conds, undo=True)
        apply_text_changes(project, self._ports, undo=True)
        self._notify_followups()

    def followup_wire_ids(self) -> list[str]:
        """Vodiče (i na jiných listech), kterým follow-upy změnily port nebo žíly."""
        ids = {c.target_id for c in self._ports or [] if c.kind == "wire_port"}
        ids |= {c.wire_id for c in self._conds or []}
        return sorted(ids)

    def _notify_followups(self) -> None:
        """Položky dotčených vodičů v ostatních pohledech se překreslí (signál scény `followup_wires`, hlavní okno
        přepočítá trasy ve všech scénách JPS – port na bloku má jinou polohu, žíly jiný popisek)."""
        ids = self.followup_wire_ids()
        sig = getattr(self.scene, "followup_wires", None)
        if ids and sig is not None:
            sig.emit(ids)

    def _wire_conductors(self, project, wires) -> None:
        from envocad.model.project import apply_conductor_changes, feed_conductor_followups
        for w in wires:
            ch = feed_conductor_followups(project, w)
            apply_conductor_changes(project, ch)
            self._conds += ch

    def _feed_link_followups(self, project, sheet, feed, attrs: bool = False) -> None:
        """Přívod/vývod `feed` listu rozvaděče s vazbou na vodič JPS: konec vodiče na bloku se přejmenuje podle
        označení přívodu (`feed_port_followups`) a vodiče u přívodu převezmou jeho žíly (`feed_conductor_changes`).
        S `attrs` navíc odvozené atributy vazby (odkud/kam, kabel – `feed_link_attrs`) jako navázaná změna, aby je
        undo vrátilo (chybějící klíč = `old` None, undo ho zase odebere)."""
        from envocad.model.project import (
            FEED_SYMBOLS,
            TextChange,
            apply_conductor_changes,
            apply_text_changes,
            effective_feed_wire,
            feed_conductor_changes,
            feed_link_attrs,
            feed_port_followups,
        )
        if feed.symbol_id not in FEED_SYMBOLS or not sheet.is_switchboard:
            return
        ports = feed_port_followups(project, sheet, feed, feed.ref)
        if attrs:
            for k, v in feed_link_attrs(project, sheet, feed, feed.attrs.get("wire_id", "")).items():
                cur = feed.attrs.get(k)
                if k != "wire_id" and cur != v and not (cur is None and v == ""):
                    ports.append(TextChange("element", feed.id, k, cur, v))
        apply_text_changes(project, ports)
        self._ports += ports
        w = effective_feed_wire(project, sheet, feed)
        if w is not None:
            ch = feed_conductor_changes(sheet, feed, w)
            apply_conductor_changes(project, ch)
            self._conds += ch

    def _feed_elements(self, project, elements) -> None:
        """Vložené přívody/vývody s ruční vazbou (`wire_id`) na listu rozvaděče – follow-upy jako u `SetAttrCommand`
        (port vodiče JPS na bloku, žíly vodičů u přívodu)."""
        sheet = self.scene.sheet
        for e in elements:
            if e.attrs.get("wire_id"):
                self._feed_link_followups(project, sheet, e)


class AddElementCommand(_FeedFollowups, QUndoCommand):
    """Vložení prvku; přívod/vývod s vazbou na vodič JPS (`wire_id` z dialogu) na listu rozvaděče přejmenuje konec
    vodiče na bloku a předá žíly (follow-upy `_feed_elements`, undo je vrátí)."""

    def __init__(self, scene, element: Element):
        super().__init__(f"Vložit {element.ref or element.symbol_id}")
        self.scene, self.element = scene, element

    def redo(self):
        self.scene.sheet.elements.append(self.element)
        self._followups_redo(lambda p: self._feed_elements(p, [self.element]))
        self.scene.add_element_item(self.element)

    def undo(self):
        self._followups_undo()
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
                self.scene.route_wire(it)

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


class SheetTextsCommand(QUndoCommand):
    """Volné texty listu (přidat, upravit, posunout, smazat): stav `Sheet.texts` před a po jako seznamy slovníků."""

    def __init__(self, scene, before: list[dict], after: list[dict], text: str = "Text"):
        super().__init__(text)
        self.scene, self.before, self.after = scene, before, after

    def _set(self, state: list[dict]):
        from envocad.model.project import SheetText
        self.scene.sheet.texts = [SheetText.from_dict(d) for d in state]
        self.scene.rebuild_texts()

    def redo(self):
        self._set(self.after)

    def undo(self):
        self._set(self.before)


class MirrorElementsCommand(QUndoCommand):
    """Zrcadlit prvky podle svislé osy značky (přepne `Element.mirror`); vodiče se přetrasují na nové porty."""

    def __init__(self, scene, element_ids: list[str]):
        super().__init__("Zrcadlit")
        self.scene, self.eids = scene, list(element_ids)

    def _flip(self):
        for eid in self.eids:
            e = self.scene.sheet.element(eid)
            e.mirror = not e.mirror
            self.scene.element_items[eid].sync_from_model()
            self.scene.update_wires_of(eid)

    def redo(self):
        self._flip()

    def undo(self):
        self._flip()


class AddWireCommand(_FeedFollowups, QUndoCommand):
    """Vložení vodiče; vodič JPS na port bloku ROZVADĚČ předá žíly vodičům u přívodu (follow-up, undo ho vrátí)."""

    def __init__(self, scene, wire: Wire):
        super().__init__("Vodič")
        self.scene, self.wire = scene, wire

    def redo(self):
        self.scene.sheet.wires.append(self.wire)
        self._followups_redo(lambda p: self._wire_conductors(p, [self.wire]))
        self.scene.add_wire_item(self.wire)

    def undo(self):
        self._followups_undo()
        self.scene.sheet.wires = [w for w in self.scene.sheet.wires if w.id != self.wire.id]
        self.scene.remove_wire_item(self.wire.id)


class SplitWireCommand(_FeedFollowups, QUndoCommand):
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
        self._followups_redo(lambda p: self._wire_conductors(p, [self.w1, self.w2]))
        for w in (self.w1, self.w2):
            self.scene.add_wire_item(w)

    def undo(self):
        self._followups_undo()
        s = self.scene.sheet
        s.wires = [w for w in s.wires if w.id not in (self.w1.id, self.w2.id)]
        for w in (self.w1, self.w2):
            self.scene.remove_wire_item(w.id)
        s.elements = [e for e in s.elements if e.id != self.junction.id]
        self.scene.remove_element_item(self.junction.id)
        s.wires.insert(self.old_idx, self.old)
        self.scene.add_wire_item(self.old)


class SetAttrCommand(_FeedFollowups, QUndoCommand):
    """Změna atributu. Ruční vazba přívodu/vývodu (`wire_id`) navíc přejmenuje konec vodiče JPS na bloku a předá
    žíly vodičům u přívodu (follow-upy, undo je vrátí)."""

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

    def _changed(self) -> None:
        """Překreslení a signál `attrs_changed` až po navázaných změnách – panel vlastností a pohledy tak vidí
        výsledný stav (i odkud/kam a kabel z vazby)."""
        self._refresh_symbol()
        (self.scene.wire_items if self.is_wire else self.scene.element_items)[self.tid].update()
        if self._conds:
            _refresh_wires(self.scene, [c.wire_id for c in self._conds])
        if hasattr(self.scene, "invalidate_text_layout"):
            self.scene.invalidate_text_layout()   # popisek (ref / aspekty) se přepočítá
        self.scene.attrs_changed.emit(self.tid)

    def _feed_link(self, project) -> None:
        if self.is_wire:
            return
        if self.key == "dir":
            self._feed_dir_followups(project)
        elif self.key == "wire_id":
            self._feed_link_followups(project, self.scene.sheet, self._target(), attrs=True)

    def _feed_dir_followups(self, project) -> None:
        """Směr přívodu/vývodu: odkud ↔ kam (z vazby na vodič JPS, jinak přesun ručního textu) jako navázané změny
        téhož kroku undo (`feed_dir_changes`). Port bloku ROZVADĚČ se přesune sám (porty z listu), vodič drží."""
        from envocad.model.feed import is_feed
        from envocad.model.project import TextChange, apply_text_changes, feed_dir_changes
        e = self._target()
        if not is_feed(e):
            return
        ch = [TextChange("element", e.id, k, e.attrs.get(k), v)
              for k, v in feed_dir_changes(project, self.scene.sheet, e).items()]
        apply_text_changes(project, ch)
        self._ports += ch

    def _refresh_symbol(self) -> None:
        """Obrázek prvku závisí na atributu (směr přívodu/vývodu – šipka, zobrazené odkud/kam): položka dostane novou
        značku, jako blok ROZVADĚČ po změně listu."""
        from envocad.model.feed import is_feed
        it = getattr(self.scene, "element_items", {}).get(self.tid)
        project = getattr(self.scene, "project", None)
        if it is None or project is None or self.is_wire or self.key != "dir" or not is_feed(it.element):
            return
        from envocad.model.project import element_symbol
        from envocad.ui.render import symbol_path
        it.prepareGeometryChange()
        it.symbol = element_symbol(project, it.element, self.scene.library)
        it._path = symbol_path(it.symbol)
        it.sync_from_model()

    def redo(self):
        self._set(self.new)
        self._followups_redo(self._feed_link)
        self._changed()

    def undo(self):
        self._followups_undo()
        self._set(self.old, remove=not self.had_key)
        self._changed()


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


def _refresh_wires(scene, wids) -> None:
    for wid in wids:
        if any(w.id == wid for w in scene.sheet.wires):
            _refresh_wire(scene, wid)


def _refresh_wire(scene, wid: str) -> None:
    """JPS scéna má položky vodičů; odvozené scény (vícepól) se celé přestaví."""
    items = getattr(scene, "wire_items", None)
    if items is not None:
        if wid in items:
            items[wid].update()
        scene.attrs_changed.emit(wid)
    else:
        scene.rebuild()


class SetConductorsCommand(_FeedFollowups, QUndoCommand):
    """Změna seznamu žil vodiče (vícepól). Vodič JPS navázaný na přívod/vývod rozvaděče předá nové žíly vodičům
    u přívodu (follow-up, undo ho vrátí)."""

    def __init__(self, scene, wire_id: str, old: list[str], new: list[str]):
        super().__init__("Změnit žíly vodiče")
        self.scene, self.wid, self.old, self.new = scene, wire_id, list(old), list(new)

    _old_terminals: dict | None = None

    def _set(self, v: list[str], terminals: dict | None = None):
        w = next(w for w in self.scene.sheet.wires if w.id == self.wid)
        if self._old_terminals is None:
            self._old_terminals = {c: dict(t) for c, t in w.terminals.items()}
        w.conductors = list(v)
        if terminals is not None:     # undo vrátí i svorky žil, které redo zahodilo
            w.terminals = {c: dict(t) for c, t in terminals.items()}
        else:
            w.terminals = {c: t for c, t in w.terminals.items() if c in w.conductors}
        return w

    def redo(self):
        w = self._set(self.new)
        self._followups_redo(lambda p: self._wire_conductors(p, [w]))
        _refresh_wire(self.scene, self.wid)

    def undo(self):
        self._followups_undo()
        self._set(self.old, self._old_terminals)
        _refresh_wire(self.scene, self.wid)


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


class PasteCommand(_FeedFollowups, QUndoCommand):
    """Vložení kopie prvků a vodičů ze schránky; vložený vodič JPS na port bloku ROZVADĚČ předá žíly vodičům
    u přívodu (follow-up jako `AddWireCommand`, undo ho vrátí)."""

    def __init__(self, scene, elements: list[Element], wires: list[Wire], text: str | None = None):
        super().__init__(text or f"Vložit kopii ({len(elements)})")
        self.scene, self.elements, self.wires = scene, elements, wires

    def redo(self):
        for e in self.elements:
            self.scene.sheet.elements.append(e)
            self.scene.add_element_item(e)
        for w in self.wires:
            self.scene.sheet.wires.append(w)
        self._followups_redo(lambda p: (self._feed_elements(p, self.elements), self._wire_conductors(p, self.wires)))
        for w in self.wires:
            self.scene.add_wire_item(w)
        self.scene.clearSelection()
        for e in self.elements:
            self.scene.element_items[e.id].setSelected(True)

    def undo(self):
        self._followups_undo()
        wid = {w.id for w in self.wires}
        eid = {e.id for e in self.elements}
        s = self.scene.sheet
        s.wires = [w for w in s.wires if w.id not in wid]
        s.elements = [e for e in s.elements if e.id not in eid]
        for w in self.wires:
            self.scene.remove_wire_item(w.id)
        for e in self.elements:
            self.scene.remove_element_item(e.id)


def _pinned_paper(sheet) -> tuple[str, str]:
    """(dosavadní, nová) volba formátu stran vícepólu listu při zápisu ručních poloh (`mp_pos`): ruční polohy jsou
    v souřadnicích stran, proto se dosud platný formát (firemní standard) zapíše k listu (`Sheet.mp_paper`) –
    pozdější změna standardu je neposune na jiné místo."""
    from envocad.model.multipole import paper_choice
    old = getattr(sheet, "mp_paper", "")
    if not sheet.is_switchboard:     # vícepól listu JPS má vždy formát listu
        return old, old
    return old, old or paper_choice(sheet)


class MoveMultipoleCommand(QUndoCommand):
    """Ruční pozice prvků ve vícepólu (`Element.mp_pos`; None = automatické rozmístění). Zapíše k listu i formát
    stran (`_pinned_paper`), undo ho vrátí."""

    def __init__(self, scene, moves: dict):
        super().__init__("Posun ve vícepólu")
        self.scene, self.moves = scene, moves
        self.paper = _pinned_paper(scene.sheet)

    def _apply(self, idx: int):
        for eid, pair in self.moves.items():
            e = self.scene.sheet.element(eid)
            e.mp_pos = tuple(pair[idx]) if pair[idx] else None
        self.scene.sheet.mp_paper = self.paper[idx]
        self.scene.rebuild()

    def redo(self):
        self._apply(1)

    def undo(self):
        self._apply(0)


class MultipoleAddCommand(_FeedFollowups, QUndoCommand):
    """Vložení prvku nebo žíly přímo ve vícepólu (schématu rozvaděče): zapíše se do modelu listu, pohled se přestaví.
    Vodič vícepólu listu JPS na port bloku ROZVADĚČ předá žíly vodičům u přívodu (follow-up, undo ho vrátí)."""

    def __init__(self, scene, element: Element | None = None, wire: Wire | None = None,
                 elements: list[Element] | None = None, wires: list[Wire] | None = None, text: str | None = None):
        self.elements = ([element] if element is not None else []) + list(elements or [])
        self.wires = ([wire] if wire is not None else []) + list(wires or [])
        super().__init__(text or ("Vložit prvek" if self.elements and len(self.elements) == 1 and not self.wires
                                  else ("Vodič" if not self.elements else f"Vložit ({len(self.elements)})")))
        self.scene = scene
        # prvky vložené ve vícepólu mají ruční polohu → formát stran se zapíše k listu (viz MoveMultipoleCommand)
        self.paper = _pinned_paper(scene.sheet) if any(e.mp_pos for e in self.elements) else None

    def redo(self):
        s = self.scene.sheet
        s.elements.extend(self.elements)
        s.wires.extend(self.wires)
        if self.paper:
            s.mp_paper = self.paper[1]
        self._followups_redo(lambda p: (self._feed_elements(p, self.elements), self._wire_conductors(p, self.wires)))
        self.scene.rebuild()
        if getattr(self.scene, "after_edit", None):
            self.scene.after_edit()   # jednopólová editace téhož listu se přestaví

    def undo(self):
        self._followups_undo()
        s = self.scene.sheet
        wid = {w.id for w in self.wires}
        eid = {e.id for e in self.elements}
        s.wires = [w for w in s.wires if w.id not in wid]
        s.elements = [e for e in s.elements if e.id not in eid]
        if self.paper:
            s.mp_paper = self.paper[0]
        self.scene.rebuild()
        if getattr(self.scene, "after_edit", None):
            self.scene.after_edit()


class SetSheetPaperCommand(QUndoCommand):
    """Formát stran vícepólu a plánu svorkovnice listu rozvaděče (`Sheet.mp_paper`; "" = firemní standard).
    `on_change` přestaví pohledy listu."""

    def __init__(self, sheet, old: str, new: str, on_change=None):
        super().__init__("Formát stran schématu rozvaděče")
        self.sheet, self.old, self.new, self.on_change = sheet, old, new, on_change

    def _set(self, v: str):
        self.sheet.mp_paper = v
        if self.on_change:
            self.on_change()

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old)


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


class RenameSheetCommand(QUndoCommand):
    """Název listu (`Sheet.name`) – Vlastnosti listu. `on_change` obnoví titulky záložek."""

    def __init__(self, sheet, old: str, new: str, on_change=None):
        super().__init__("Přejmenovat list")
        self.sheet, self.old, self.new, self.on_change = sheet, old, new, on_change

    def _set(self, v: str):
        self.sheet.name = v
        if self.on_change:
            self.on_change()

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old)


class TextChangesCommand(QUndoCommand):
    """Navázané změny textů po přejmenování prvku (`model.project.rename_followups`): popisy jiných prvků a názvy
    listů. `on_change` obnoví pohledy (titulky záložek, popisky)."""

    def __init__(self, project, changes: list, on_change=None, text: str = "Upravit navázané texty"):
        super().__init__(text)
        self.project, self.changes, self.on_change = project, list(changes), on_change

    def _apply(self, undo: bool):
        from envocad.model.project import apply_text_changes
        apply_text_changes(self.project, self.changes, undo=undo)
        if self.on_change:
            self.on_change()

    def redo(self):
        self._apply(False)

    def undo(self):
        self._apply(True)


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
    """Nahrazení revizí (`project.revisions`) a meta klíčů revize („revision“, „changes“) – porovnání s revizí,
    uzavření revize. `old_state`/`new_state` = `(revize, meta)` z `revision.revisions_state`; ostatní `project.meta`
    (investor, datum…) příkaz nemění, takže undo nevrátí jejich úpravy provedené mimo něj."""

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


class ReplaceNoteCommand(QUndoCommand):
    """Přidání (`old=None`), úprava (obě) nebo smazání (`new=None`) připomínky v `project.notes` jedním příkazem.
    Drží hluboké kopie, takže pozdější změny předaných objektů příkaz neovlivní. Undo smazání vrátí připomínku na
    původní index, číslo nové připomínky se přidělí při prvním redo a pak se zachovává; undo vrátí i čítač čísel
    `meta["note_seq"]`. `on_change` překreslí GUI."""

    def __init__(self, project, old, new, text: str = "Připomínka", on_change=None, index: int | None = None):
        super().__init__(text)
        import copy
        self.project, self.on_change = project, on_change
        self.old = copy.deepcopy(old)
        self.new = copy.deepcopy(new)
        nid = (old or new).id
        self.index = index
        if self.index is None:
            self.index = next((i for i, n in enumerate(project.notes) if n.id == nid), None)

    def _changed(self):
        if self.on_change:
            self.on_change()

    def redo(self):
        import copy

        from envocad.model.notes import NOTE_SEQ_KEY, put_note, remove_note
        self._seq_before = self.project.meta.get(NOTE_SEQ_KEY)   # čítač čísel připomínek; undo ho vrátí
        if self.new is None:
            remove_note(self.project, self.old.id)
        else:
            n = copy.deepcopy(self.new)
            put_note(self.project, n, self.index)
            self.new.no = n.no          # číslo přidělené při prvním redo zůstává i po undo/redo
        self._changed()

    def undo(self):
        import copy

        from envocad.model.notes import NOTE_SEQ_KEY, put_note, remove_note
        if self.old is None:
            remove_note(self.project, self.new.id)
        else:
            put_note(self.project, copy.deepcopy(self.old), self.index)
        if self._seq_before is None:
            self.project.meta.pop(NOTE_SEQ_KEY, None)
        else:
            self.project.meta[NOTE_SEQ_KEY] = self._seq_before
        self._changed()


class DeleteSheetCommand(QUndoCommand):
    """Smazání listu (`Project.remove_sheet`). Uloží list, jeho index, odpojené listy rozvaděčů (jejich
    `parent_element_id`) a atribut „sheet“ bloku ROZVADĚČ, který `remove_sheet` odebere; undo vše vrátí.
    `on_change(sheet, present)` zavře / obnoví záložky listu."""

    def __init__(self, project, sheet, on_change=None):
        super().__init__(f"Odstranit list {sheet.name}")
        self.project, self.sheet, self.on_change = project, sheet, on_change
        self.index = project.sheets.index(sheet)
        self.orphans: list = []          # [(list, původní parent_element_id)]
        self.block_attr = None           # (blok, hodnota atributu „sheet“) – odebraná při redo

    def redo(self):
        p, sh = self.project, self.sheet
        self.index = p.sheets.index(sh)
        block = None
        if sh.parent_element_id:
            ps = p.sheet_of_element(sh.parent_element_id)
            block = ps.element(sh.parent_element_id) if ps is not None else None
        had = block is not None and "sheet" in block.attrs
        old_val = block.attrs.get("sheet") if block is not None else None
        self.orphans = [(s, s.parent_element_id) for s in p.sheets if s is not sh]   # odpojené se vyberou níže
        detached = p.remove_sheet(sh)
        self.orphans = [(s, pid) for s, pid in self.orphans if s in detached]
        self.block_attr = (block, old_val) if had and "sheet" not in block.attrs else None
        if self.on_change:
            self.on_change(sh, False)

    def undo(self):
        p, sh = self.project, self.sheet
        p.sheets.insert(self.index, sh)
        for s, pid in self.orphans:
            s.parent_element_id = pid
        if self.block_attr is not None:
            block, val = self.block_attr
            block.attrs["sheet"] = val
        if self.on_change:
            self.on_change(sh, True)


class AddSheetCommand(QUndoCommand):
    """Přidání listu (nový list schématu, list rozvaděče). U listu rozvaděče i atribut „sheet“ bloku ROZVADĚČ
    (`block_attr` = (blok, před, po); „před“ None = atribut nebyl) a registr struktur (`structures` = (před, po)).
    `on_change(sheet, present)` otevře / zavře záložky listu."""

    def __init__(self, project, sheet, on_change=None, index: int | None = None, block_attr=None,
                 structures=None, text: str | None = None):
        super().__init__(text or f"Nový list {sheet.name}")
        self.project, self.sheet, self.on_change = project, sheet, on_change
        self.index = len(project.sheets) if index is None else index
        self.block_attr = block_attr
        self.structures = (list(structures[0]), list(structures[1])) if structures else None

    def _attr(self, value):
        block = self.block_attr[0]
        if value is None:
            block.attrs.pop("sheet", None)
        else:
            block.attrs["sheet"] = value

    def redo(self):
        self.project.sheets.insert(self.index, self.sheet)
        if self.block_attr is not None:
            self._attr(self.block_attr[2])
        if self.structures is not None:
            self.project.structures = list(self.structures[1])
        if self.on_change:
            self.on_change(self.sheet, True)

    def undo(self):
        self.project.sheets.remove(self.sheet)
        if self.block_attr is not None:
            self._attr(self.block_attr[1])
        if self.structures is not None:
            self.project.structures = list(self.structures[0])
        if self.on_change:
            self.on_change(self.sheet, False)


def sheets_state(project) -> dict:
    """Stav listů a registru struktur pro `SheetsStateCommand`: {"sheets": {id: to_dict}, "structures": [...]}.
    Hluboká kopie – `to_dict` sdílí slovníky atributů s modelem."""
    import copy
    return copy.deepcopy({"sheets": {s.id: s.to_dict() for s in project.sheets},
                          "structures": [x.to_dict() for x in project.structures]})


def restore_sheets_state(project, state: dict) -> None:
    """Vrátí listy (na místě, `Sheet.restore_state`) a registr struktur ze `sheets_state`."""
    from envocad.model.project import StructureId
    for s in project.sheets:
        d = state["sheets"].get(s.id)
        if d is not None and s.to_dict() != d:   # nezměněné listy zůstanou beze změny i objektově
            s.restore_state(d)
    project.structures = [StructureId.from_dict(x) for x in state["structures"]]


class SheetsStateCommand(QUndoCommand):
    """Obecný makro-příkaz nad obsahem listů (prvky, vodiče, rozložení, můstky…) a registrem struktur – např.
    vložení šablony rozvaděče, která mění list rozvaděče i vodiče nadřazeného listu. `before`/`after` ze
    `sheets_state`; ukládají se jen změněné listy. Listy se mění na místě (objekty listů drží pohledy).
    `on_change(sheet_ids)` přestaví pohledy."""

    def __init__(self, project, before: dict, after: dict, text: str = "Změna listu", on_change=None):
        super().__init__(text)
        import copy
        changed = {sid for sid, d in after["sheets"].items() if before["sheets"].get(sid) != d}
        self.project, self.on_change = project, on_change
        self.before = {"sheets": {sid: copy.deepcopy(before["sheets"][sid]) for sid in changed if sid in before["sheets"]},
                       "structures": copy.deepcopy(before["structures"])}
        self.after = {"sheets": {sid: copy.deepcopy(after["sheets"][sid]) for sid in changed},
                      "structures": copy.deepcopy(after["structures"])}

    def _set(self, state):
        restore_sheets_state(self.project, state)
        if self.on_change:
            self.on_change(list(state["sheets"]))

    def redo(self):
        self._set(self.after)

    def undo(self):
        self._set(self.before)


class SetProjectMetaCommand(QUndoCommand):
    """Vlastnosti projektu: název (`Project.name`) a metadata (`Project.meta`) jedním krokem."""

    def __init__(self, project, old: tuple[str, dict], new: tuple[str, dict], on_change=None):
        super().__init__("Vlastnosti projektu")
        self.project, self.on_change = project, on_change
        self.old = (old[0], dict(old[1]))
        self.new = (new[0], dict(new[1]))

    def _set(self, v):
        self.project.name = v[0]
        self.project.meta = dict(v[1])
        if self.on_change:
            self.on_change()

    def redo(self):
        self._set(self.new)

    def undo(self):
        self._set(self.old)


SET_LAYOUT_ID = 0x4C41   # id pro slučování po sobě jdoucích změn téhož pole skříně (mergeWith)


class SetLayoutCommand(QUndoCommand):
    """Rozložení / skříň rozvaděče: snímek `Layout.to_dict()` před a po. Po sobě jdoucí změny téhož pole
    (`merge_key`, např. počet řad šipkami nebo psaním) se slučují do jednoho kroku. `on_change(sheet)` přestaví
    pohledy a panel skříně."""

    def __init__(self, sheet, before: dict, after: dict, text: str = "Skříň rozvaděče", on_change=None,
                 merge_key: str | None = None):
        super().__init__(text)
        import copy
        self.sheet, self.on_change, self.merge_key = sheet, on_change, merge_key
        self.before, self.after = copy.deepcopy(before), copy.deepcopy(after)

    def id(self) -> int:
        return SET_LAYOUT_ID if self.merge_key else -1

    def mergeWith(self, other) -> bool:
        if not isinstance(other, SetLayoutCommand) or other.sheet is not self.sheet or not self.merge_key \
                or other.merge_key != self.merge_key:
            return False
        import copy
        self.after = copy.deepcopy(other.after)
        if self.after == self.before:
            self.setObsolete(True)    # změna se vrátila na původní hodnotu → krok zmizí
        return True

    def _set(self, d: dict):
        from envocad.model.project import Layout
        new = Layout.from_dict(d)
        lay = self.sheet.layout
        lay.rows, lay.modules_per_row, lay.enclosure = new.rows, new.modules_per_row, new.enclosure
        lay.params, lay.placements = new.params, new.placements
        if self.on_change:
            self.on_change(self.sheet)

    def redo(self):
        self._set(self.after)

    def undo(self):
        self._set(self.before)


class SetSingleLineOffsetCommand(QUndoCommand):
    """Ruční posun v jednopólovém schématu (`Element.sl_pos`; None = automatické rozmístění). `changes` =
    {(id listu, id prvku): (dosavadní, nový)}; `refresh` přestaví scénu."""

    def __init__(self, project, changes: dict, refresh, text: str = "Posun v jednopólovém schématu"):
        super().__init__(text)
        self.project, self.changes, self.refresh = project, changes, refresh

    def _apply(self, idx: int):
        for (sid, eid), pair in self.changes.items():
            e = self.project.sheet(sid).element(eid)
            if e is not None:
                e.sl_pos = tuple(pair[idx]) if pair[idx] else None
        self.refresh()

    def redo(self):
        self._apply(1)

    def undo(self):
        self._apply(0)
