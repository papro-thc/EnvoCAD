"""Průchod topologií řetězce FVE (bez Qt): blok hlavního AC článku, bloky a listy článků přes registr builderů
(`BOARD_BUILDERS`), uzemnění, zarovnání a rozmístění JPS. Návrh `docs/design/topologie_f1_f2.md`, kap. 1.3 (kroky 5–6).

`build` projde `ctx.topology.nodes` dvakrát – nejdřív bloky v JPS (`BoardBuilder.block`), pak listy rozvaděčů
(`BoardBuilder.build`) – v pořadí uzlů, takže pořadí prvků i `next_ref` zůstává jako před refaktoringem. Role bez
builderu se přeskočí (F1: stávající RD, HR a RE na nn, HDS – přijdou v F2); u topologie `vn` obslouží HR, TR, RVN,
DS a odbočku RE jeden složený builder `mv`. Střídače (`inverter`) a vše před nimi staví `pv.build`.
"""
from __future__ import annotations

from envocad.generator.boards import grid, hds, mv, rfve, rfve_ac, rfve_dc
from envocad.generator.boards.base import BoardBuilder, ChainContext
from envocad.generator.context import _s, log
from envocad.generator.jps import _place_jps
from envocad.generator.layout import (
    _align_bends,
    _align_chain,
    _align_connection,
    _align_outputs,
    _align_route_boxes,
    _grow_switchboards,
    _route_house,
)
from envocad.library.templates import AC_CONDUCTORS
from envocad.model.project import Element, Wire, WireEnd, sync_cables, sync_feed_links
from envocad.model.topology import ChainNode

# role → builder článku
BOARD_BUILDERS: dict[str, BoardBuilder] = {
    "rfve_dc": rfve_dc.BUILDER,
    "rfve_ac": rfve_ac.BUILDER,
    "rfve": rfve.BUILDER,
    "hds": hds.BUILDER,
    "grid": grid.BUILDER,
}
MAIN_ROLES = ("rfve", "rfve_ac")
CABLE_KEYS = ("cable", "cross", "length", "method")


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


def link_attrs(ctx: ChainContext, prev: ChainNode | None, node: ChainNode) -> dict:
    """Atributy vodiče od článku `prev` k článku `node` (kabel článku směrem k síti, kap. 2 bod 6): `chain.<role>`
    (cable / cross / length / method) > `link` článku presetu > u hlavního AC článku dřívější `ac.grid_*`.
    Od HDS k DS vodič bez kabelu; stávající úsek (`existing`) bez údajů = vodič bez označení. Nový úsek bez průřezu
    → nejmenší průřez pro In přístroje, který kabel jistí (`ctx.node_in[node.role]`, `calc.min_cross`)."""
    from envocad.generator.spec import chain_options
    from envocad.model.calc import min_cross
    role = prev.role if prev is not None else "rfve_ac"
    if role == "hds":
        return {"ref": ""}
    o = chain_options(ctx.spec, ctx.topology, role)
    link_ = prev.link if prev is not None else None
    vals = {k: _s(o.get(k)).strip() or (_s(getattr(link_, k, "")).strip() if link_ is not None else "")
            for k in CABLE_KEYS}
    if role in MAIN_ROLES:
        ac = ctx.spec["ac"]
        for k in ("cable", "cross", "length"):
            vals[k] = vals[k] or _s(ac.get(f"grid_{k}")).strip()
        vals["method"] = vals["method"] or "D"
    elif prev is not None and prev.existing and not (vals["cable"] or vals["cross"]):
        return {"ref": ""}
    vals["method"] = vals["method"] or "C"
    if not vals["cross"]:
        from envocad.generator.context import _num
        x = min_cross(_num(ctx.node_in.get(node.role)) or 0.0, vals["method"])
        vals["cross"] = f"{x:g}" if x else ""
    return {"ref": ctx.project.next_ref("W"), **vals}


def link(ctx: ChainContext, el: Element, port: str, node: ChainNode) -> Wire:
    """Vodič od vývodu předchozího článku (`ctx.tail`) k přívodu `port` bloku `el` článku `node` (`ctx.links`)."""
    prev, pport = ctx.tail
    w = Wire(WireEnd(prev.id, pport), WireEnd(el.id, port), conductors=list(AC_CONDUCTORS),
             attrs=link_attrs(ctx, ctx.tail_node, node))
    ctx.sheet.wires.append(w)
    ctx.links.append((prev, pport, el, port, w))
    return w


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
            ports = b.ports(ctx, node)
            if getattr(b, "linked", False) and ctx.tail is not None and ports.pv_side:
                link(ctx, el, ports.pv_side[0], node)
            if ports.grid_side:
                ctx.tail = (el, ports.grid_side)
                ctx.tail_node = node
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


def _place_loads(ctx: ChainContext) -> None:
    """Spotřeba objektu (`fve.load` na vývodu X2 stávajícího RD / HR) pod blokem – builder ji registruje
    v `ctx.loads` (blok, port, značka, vodič); vodič z X2 vlevo (blok je zrcadlený), svisle dolů pod blok a do značky."""
    from envocad.generator.layout import place_load
    for blk, port, load, w in ctx.loads:
        place_load(ctx.project, blk, port, load, w)


def _layout(ctx: ChainContext) -> None:
    """Zarovnání bloků a lomů JPS, rozmístění na list(y), zvětšení přetékajících listů rozvaděčů, vazby přívodů."""
    p, s, blk = ctx.project, ctx.sheet, ctx.main
    if ctx.combined or ctx.dc_common is not None:   # rozvaděče po trase na výšku přívodů RFVE / společného RFVE.DC
        target = blk if ctx.combined else ctx.dc_common
        _align_route_boxes(p, target, [[b for b, _g, k, no, _r in ctx.dc_boxes if no == i + 1 and b is not target]
                                       for i in range(len(ctx.inverters))])
    _align_bends(p)
    links = list(ctx.links)
    if ctx.combined and links:
        _prev, _pp, first, port, w = links.pop(0)
        _route_house(p, blk, ctx.ac_wires, (first, port, w), ctx.earth)
    else:
        _align_outputs(p, blk, None, ctx.earth)
    _align_chain(p, links)
    _place_loads(ctx)
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
