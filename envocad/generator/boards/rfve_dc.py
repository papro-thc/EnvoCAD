"""DC rozvaděče (u technologie RFVE.DC, po trase RDCn): označení, artikly a neurčené In (bez Qt). Přesun 1:1 z `generate.py`
(refaktoring F1, krok 4)."""
from __future__ import annotations

from envocad.generator import context
from envocad.generator.context import (
    DC_ROUTE_BOX_PREFIX,
    DC_TECH_BOX_REF,
    _s,
)
from envocad.model.project import Project, Sheet


def dc_box_ref(kind: str, inv_index: int, n_tech: int, p: Project) -> str:
    """Označení DC rozvaděče generátoru: u technologie (`kind` "tech") RFVE.DC, je-li jediný, jinak RFVE.DC1, RFVE.DC2…
    podle pořadí střídače (`inv_index` od 0; `n_tech` = počet rozvaděčů u technologie); po trase další volné RDCn
    (rozvaděče u technologie číslo RDC neberou, takže po trase jdou RDC1…n souvisle)."""
    if kind == "tech":
        return DC_TECH_BOX_REF if n_tech <= 1 else f"{DC_TECH_BOX_REF}{inv_index + 1}"
    return p.next_ref(DC_ROUTE_BOX_PREFIX)


def _mark_unresolved(elements, symbols, why: str) -> None:
    """Prvkům `symbols` bez In zapíše `in_unresolved` = důvod (generátor In neurčil, protože nic nevyhovělo) –
    kontrola F7 pak hlásí chybu s důvodem; nepovinný atribut, formát projektu beze změny."""
    for e in elements:
        if e.symbol_id in symbols and not _s(e.attrs.get("in_")).strip():
            e.attrs["in_unresolved"] = why or "nic nevyhovělo"


def _apply_component(sheet: Sheet, cid, symbol_id: str) -> None:
    """Artikl (`dc.fuse_component`) na všechny prvky `symbol_id` listu – typ, výrobce, póly, šířka. In vložky
    zůstává: artikl držáku (kategorie fuse_holder) In vložky nepřepisuje (`Component.attr_values` ho u držáku
    vynechá). Neznámý nebo prázdný artikl → beze změny."""
    comp = context._lib().component(cid) if cid else None
    if comp is None:
        return
    for e in sheet.elements:
        if e.symbol_id == symbol_id:
            comp.apply_to(e)


def _apply_spd_component(sheet: Sheet, cid) -> None:
    """Artikl svodiče DC (`dc.spd_component`) na SPD listu DC rozvaděče, jejichž typ SPD artiklu odpovídá („T1+T2“ =
    „T1+T2 DC“) – typ, výrobce, Uc, Up, ISCPV ve výkresu. Jiný zadaný typ (`dc.spd` „T2“) artikl nepřepíše;
    neznámý nebo prázdný artikl → beze změny."""
    comp = context._lib().component(cid) if cid else None
    if comp is None:
        return

    def norm(t: str) -> str:
        return "".join(t.upper().replace("DC", "").split())

    for e in sheet.elements:   # jen svodiče DC (rozvaděč FVE rodinného domu má i svodič AC)
        if e.symbol_id == "fve.spd" and "DC" in e.attrs.get("spd_type", "").upper() \
                and norm(e.attrs.get("spd_type", "")) == norm(comp.params.get("spd_type", "")):
            comp.apply_to(e)
