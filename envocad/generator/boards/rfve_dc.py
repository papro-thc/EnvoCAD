"""DC rozvaděče (u technologie RFVE.DC, po trase RDCn): označení, artikly a neurčené In (bez Qt). Přesun 1:1 z `generate.py`
(refaktoring F1, krok 4)."""
from __future__ import annotations

from envocad.generator import context
from envocad.generator.boards.base import ChainContext, ChainPorts
from envocad.generator.boards.macro_glue import FUSE_SYMBOLS, _dc_box_from_macro
from envocad.generator.context import (
    DC_ROUTE_BOX_PREFIX,
    DC_TECH_BOX_REF,
    _s,
    log,
)
from envocad.generator.spec import fuse_in_why
from envocad.library.templates import _place_sequential, build_dc_strings
from envocad.model.project import Element, Project, Sheet
from envocad.model.topology import ChainNode


def dc_box_ref(kind: str, inv_index: int, n_tech: int, p: Project, base: str = DC_TECH_BOX_REF) -> str:
    """Označení DC rozvaděče generátoru: u technologie (`kind` "tech") `base` (z presetu, výchozí RFVE.DC), je-li
    jediný, jinak RFVE.DC1, RFVE.DC2… podle pořadí střídače (`inv_index` od 0; `n_tech` = počet rozvaděčů u
    technologie); po trase další volné RDCn (rozvaděče u technologie číslo RDC neberou, takže po trase jdou RDC1…n
    souvisle)."""
    if kind == "tech":
        base = base or DC_TECH_BOX_REF
        return base if n_tech <= 1 else f"{base}{inv_index + 1}"
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


def fuse_of(ctx: ChainContext, t: Element | None) -> tuple[str, str]:
    """In pojistek stringů střídače a důvod prázdného In – spočte a případně zaloguje jednou za střídač (ne pro
    každý jeho rozvaděč po trase); mezipaměť `ctx.fuse_cache`."""
    spec = ctx.spec
    key = t.ref if t is not None else ""
    if key not in ctx.fuse_cache:
        ctx.fuse_cache[key] = fuse_in_why(spec["dc"], spec["module"], spec.get("optimizer") or {}, t)
        if not ctx.fuse_cache[key][0]:
            log.warning("Pojistka stringu %s: %s – In zůstává prázdné", key, ctx.fuse_cache[key][1])
    return ctx.fuse_cache[key]


def build_dc_sheets(ctx: ChainContext) -> None:
    """Listy DC rozvaděčů z `ctx.dc_boxes` (po trase i u technologie, v pořadí vzniku bloků): makro na string
    (`dc_route` / `dc_tech`), jinak `build_dc_strings`; artikly SPD a držáku pojistky, neurčené In → `in_unresolved`.
    Jednou za sestavení (volá ho první článek, který DC rozvaděče potřebuje – listy musí vzniknout před hlavním)."""
    if "dc_sheets" in ctx.done:
        return
    ctx.done.add("dc_sheets")
    p, dc = ctx.project, ctx.spec["dc"]
    macros = ctx.spec.get("macros") or {}
    inv_by_ref = {t.ref: t for t in ctx.inverters}
    for b, gens, kind, inv_no, inv_ref in ctx.dc_boxes:
        sheet = p.create_switchboard_sheet(b)
        sheet.layout.params.setdefault("network", "DC IT")
        sheet.layout.params.setdefault("un", "max. 1000 V DC")
        if b is ctx.dc_common:
            build_common_sheet(ctx, sheet, macros.get("dc_tech", ""))
            continue
        entry = macros.get("dc_tech" if kind == "tech" else "dc_route", "")
        fin, why = fuse_of(ctx, inv_by_ref.get(inv_ref))
        dc_box = {**dc, "fuse_in": fin}
        if not _dc_box_from_macro(p, sheet, [g.ref for g in gens], entry, dc_box, inv_no, inv_ref):
            build_dc_strings(p, sheet, [g.ref for g in gens], kind, _s(dc_box["fuse_in"]),
                             _s(dc.get("disconnect_in") or 32), _s(dc.get("spd") or "T2"))
        _apply_spd_component(sheet, dc.get("spd_component"))
        _apply_component(sheet, dc.get("fuse_component"), "fve.fuse_disconnect")
        if not fin:
            _mark_unresolved(sheet.elements, FUSE_SYMBOLS, why)


def build_common_sheet(ctx: ChainContext, sheet: Sheet, entry) -> None:
    """List společného DC rozvaděče u technologie (RFVE.DC pro 2+ střídače): stringy všech střídačů za sebou, přívody
    X1…Xn, vývody X(n+1)…X(2n) – makro `dc_tech` po střídačích (k0, ENVO číslování i.j jako DC část RFVE), jinak
    `build_dc_strings` s In pojistek po stringu podle jeho střídače; artikly, neurčené In."""
    p, dc = ctx.project, ctx.spec["dc"]
    groups = [(i + 1, t.ref, [g.ref for g in gens], fuse_of(ctx, t))
              for i, (t, gens) in enumerate(zip(ctx.inverters, ctx.strings))]
    n = sum(len(g[2]) for g in groups)
    k0, done = 0, False
    for inv_no, inv_ref, strings, (fin, _why) in groups:
        done = _dc_box_from_macro(p, sheet, strings, entry, {**dc, "fuse_in": fin}, inv_no, inv_ref, k0=k0, n=n)
        if not done:
            break
        k0 += len(strings)
    if done:       # makro rozmístí přístroje jen svého střídače – znovu všechny za sebou
        sheet.layout.placements.clear()
        _place_sequential(sheet, list(sheet.elements))
    if not done:   # makro chybí (pak pro žádný střídač): kódem, všechny stringy najednou (In po stringu podle střídače)
        build_dc_strings(p, sheet, [g for grp in groups for g in grp[2]], "tech",
                         [_s(grp[3][0]) for grp in groups for _g in grp[2]],
                         _s(dc.get("disconnect_in") or 32), _s(dc.get("spd") or "T2"))
    _apply_spd_component(sheet, dc.get("spd_component"))
    _apply_component(sheet, dc.get("fuse_component"), "fve.fuse_disconnect")
    whys = [why for _n, _r, _s2, (fin, why) in groups if not fin]
    if whys:
        _mark_unresolved(sheet.elements, FUSE_SYMBOLS, "; ".join(dict.fromkeys(whys)))


class RfveDcBuilder:
    """Role `rfve_dc` – DC rozvaděče: bloky vznikají ve FV části (v řadě střídače, `pv.build`; F1 = jeden RFVE.DC na
    střídač, společný RFVE.DC až F2), builder vytvoří jejich listy (i listy rozvaděčů po trase)."""
    name = "rfve_dc"

    def block(self, ctx: ChainContext, node: ChainNode) -> Element | None:
        return None

    def ports(self, ctx: ChainContext, node: ChainNode) -> ChainPorts:
        return ChainPorts((), "")

    def build(self, ctx: ChainContext, node: ChainNode) -> None:
        build_dc_sheets(ctx)


BUILDER = RfveDcBuilder()
