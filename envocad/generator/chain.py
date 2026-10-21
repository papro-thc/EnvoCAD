"""Průchod topologií řetězce FVE (bez Qt): blok hlavního AC článku, bloky a listy článků přes registr builderů
(`BOARD_BUILDERS`), uzemnění, zarovnání a rozmístění JPS. Návrh `docs/design/topologie_f1_f2.md`, kap. 1.3 (kroky 5–6).

`build` projde `ctx.topology.nodes` dvakrát – nejdřív bloky v JPS (`BoardBuilder.block`), pak listy rozvaděčů
(`BoardBuilder.build`) – v pořadí uzlů, takže pořadí prvků i `next_ref` zůstává jako před refaktoringem. Role bez
builderu se přeskočí (F1: stávající RD, HR a RE na nn, HDS – přijdou v F2); u topologie `vn` obslouží HR, TR, RVN,
DS a odbočku RE jeden složený builder `mv`. Střídače (`inverter`) a vše před nimi staví `pv.build`.
"""
from __future__ import annotations

from envocad.generator.boards import grid, mv, rfve, rfve_ac, rfve_dc
from envocad.generator.boards.base import BoardBuilder, ChainContext
from envocad.generator.context import _s, log
from envocad.generator.jps import _place_jps
from envocad.generator.layout import (
    _align_bends,
    _align_connection,
    _align_outputs,
    _align_route_boxes,
    _grow_switchboards,
    _route_house,
)
from envocad.model.project import Element, Wire, WireEnd, sync_cables, sync_feed_links
from envocad.model.topology import ChainNode

# role → builder článku (F2 doplní rd, hr a re na nn, hds)
BOARD_BUILDERS: dict[str, BoardBuilder] = {
    "rfve_dc": rfve_dc.BUILDER,
    "rfve_ac": rfve_ac.BUILDER,
    "rfve": rfve.BUILDER,
    "grid": grid.BUILDER,
}


def builder_for(ctx: ChainContext, node: ChainNode) -> BoardBuilder | None:
    """Builder článku: u topologie na vn obslouží HR, TR, RVN, DS a RE přípojka VN (`mv`), jinak registr podle role;
    None = role zatím bez builderu (přeskočí se)."""
    if ctx.topology is not None and ctx.topology.level == "vn" and node.role in mv.MV_ROLES:
        return mv.BUILDER
    return BOARD_BUILDERS.get(node.role)


def create_main_block(ctx: ChainContext) -> Element:
    """Blok hlavního AC článku (RFVE.AC, u rodinného domu RFVE) – vzniká **před** stringy (pořadí prvků v listu).
    Označení zatím ze `spec.switchboard` (legacy; označení z presetu je F2)."""
    sw = ctx.spec["switchboard"]
    blk = Element("fve.switchboard", ctx.geo.x_blk, 150.0, attrs={"ref": sw["ref"], "desc": sw["desc"]})
    ctx.sheet.elements.append(blk)
    ctx.blocks["main"] = blk
    return blk


def _earth_block(ctx: ChainContext) -> None:
    """PE rozvaděče je uzemněný na ekvipotenciální svorkovnici (HOP) vně rozvaděče – vývod XPE → uzemnění."""
    p, s, ac, blk = ctx.project, ctx.sheet, ctx.spec["ac"], ctx.main
    if not ((ac.get("distribution") or "bus") == "bus" or ctx.combined):
        return
    earth = Element("fve.earth", ctx.geo.x_blk + (42.5 if ctx.mv is not None else 35.0), 150.0 - 40.0,
                    attrs={"ref": "", "desc": "ekvipotenciální svorkovnice (HOP)"})
    s.elements.append(earth)
    s.wires.append(Wire(WireEnd(blk.id, "XPE"), WireEnd(earth.id, "PE"), conductors=["PE"],
                        attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("pe_cable") or "CYA 16"), "cross": _s(ac.get("pe_cross") or 16),
                               "length": _s(ac.get("pe_length") or 5)}))
    ctx.earth = earth


def _chain_nodes(ctx: ChainContext) -> list[tuple[ChainNode, BoardBuilder]]:
    """Uzly topologie s builderem (bez střídačů – ty staví `pv.build`); role bez builderu se zalogují a přeskočí."""
    out = []
    for node in ctx.topology.nodes if ctx.topology is not None else ():
        if node.role == "inverter":
            continue
        b = builder_for(ctx, node)
        if b is None:
            log.debug("Topologie %s: článek „%s“ zatím nemá builder – přeskočen", ctx.topology.id, node.role)
            continue
        out.append((node, b))
    return out


def build(ctx: ChainContext) -> None:
    """Zbytek projektu po FV části (`pv.build`) průchodem topologií: bloky článků za hlavním AC článkem (síť /
    přípojka VN), uzemnění, listy rozvaděčů (DC, hlavní AC, přípojka VN), zarovnání, rozmístění JPS a vazby přívodů."""
    p = ctx.project
    nodes = _chain_nodes(ctx)
    # 1. průchod: bloky v JPS (kabel k síti vede z vývodu posledního bloku – `ctx.tail`)
    for node, b in nodes:
        if f"block:{b.name}" in ctx.done:
            continue
        ctx.done.add(f"block:{b.name}")
        el = b.block(ctx, node)
        if el is not None:
            ctx.blocks.setdefault(node.role, el)
            grid_side = b.ports(ctx, node).grid_side
            if grid_side:
                ctx.tail = (el, grid_side)
    if ctx.grid is None:              # vlastní topologie bez článku „grid“: DS za koncem řetězce jako dřív
        grid.build_grid(ctx)
    _earth_block(ctx)
    p.meta.setdefault("p_installed_kwp", f"{ctx.kwp:g}")
    # 2. průchod: listy rozvaděčů (DC rozvaděče před hlavním AC rozvaděčem – zajistí `build_main_sheet`)
    for node, b in nodes:
        if f"build:{b.name}" in ctx.done:
            continue
        ctx.done.add(f"build:{b.name}")
        b.build(ctx, node)
    if "main" not in ctx.done:        # vlastní topologie bez RFVE.AC / RFVE: hlavní AC rozvaděč je vždy
        sb = rfve_ac.build_main_sheet(ctx)
        if ctx.combined:
            rfve.build_dc_part(ctx, sb)
    _layout(ctx)


def _layout(ctx: ChainContext) -> None:
    """Zarovnání bloků a lomů JPS, rozmístění na list(y), zvětšení přetékajících listů rozvaděčů, vazby přívodů."""
    p, s, blk = ctx.project, ctx.sheet, ctx.main
    if ctx.combined:
        _align_route_boxes(p, blk, [[b for b, _g, _k, no, _r in ctx.dc_boxes if no == i + 1]
                                    for i in range(len(ctx.inverters))])
    _align_bends(p)
    if ctx.combined:
        _route_house(p, blk, ctx.ac_wires, ctx.grid, ctx.earth)
    else:
        _align_outputs(p, blk, None if ctx.mv else ctx.grid, ctx.earth)
    if ctx.mv is not None:
        _align_connection(p, blk, ctx.mv)
    _place_jps(p, s, ctx.spec.get("jps") or {}, ctx.rows, ctx.ac_wires, blk)
    # až po rozmístění na list: vazby přívodů ukládají texty s polohou v JPS („W3 T1:DC1 /1.F3“); listy DC rozvaděčů,
    # které přetékají formát (DC rozvaděč s mnoha stringy po 50 mm), se zvětší – před vazbami (sloupce listu)
    # i po nich (delší texty vazeb)
    # i AC rozvaděč / rozvaděč FVE rodinného domu (DC část „U“ po `DC_U_PITCH`, mnoho střídačů)
    dc_sheets = [sh for sh in p.sheets if sh.parent_element_id in {b.id for b, *_ in ctx.dc_boxes} | {blk.id}]
    _grow_switchboards(p, dc_sheets)
    sync_feed_links(p)
    if _grow_switchboards(p, dc_sheets):
        sync_feed_links(p)
    sync_cables(p)
