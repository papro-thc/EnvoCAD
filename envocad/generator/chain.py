"""Řetězec FVE za střídači (bez Qt): blok hlavního AC článku, síť / přípojka VN, uzemnění, listy rozvaděčů,
zarovnání a rozmístění JPS. 2. polovina `generate._build_project` (refaktoring F1, krok 5)."""
from __future__ import annotations

from envocad.generator.boards import mv, rfve, rfve_ac, rfve_dc
from envocad.generator.boards.base import ChainContext
from envocad.generator.context import _s
from envocad.generator.jps import _place_jps
from envocad.generator.layout import (
    _align_bends,
    _align_connection,
    _align_outputs,
    _align_route_boxes,
    _grow_switchboards,
    _route_house,
)
from envocad.library.templates import AC_CONDUCTORS
from envocad.model.project import Element, Wire, WireEnd, sync_cables, sync_feed_links


def create_main_block(ctx: ChainContext) -> Element:
    """Blok hlavního AC článku (RFVE.AC, u rodinného domu RFVE) – vzniká **před** stringy (pořadí prvků v listu)."""
    sw = ctx.spec["switchboard"]
    blk = Element("fve.switchboard", ctx.geo.x_blk, 150.0, attrs={"ref": sw["ref"], "desc": sw["desc"]})
    ctx.sheet.elements.append(blk)
    ctx.blocks["main"] = blk
    return blk


def _grid_block(ctx: ChainContext) -> None:
    """DS za hlavním AC článkem (připojení na nn): vodič XOUT → DS s kabelem `ac.grid_*`."""
    p, s, ac, blk = ctx.project, ctx.sheet, ctx.spec["ac"], ctx.main
    grid = Element("fve.grid", ctx.geo.x_grid, 150.0, attrs={"ref": "", "voltage": _s(ctx.spec["grid"].get("voltage")),
                                                             "dso": _s(ctx.spec["grid"].get("dso"))})
    s.elements.append(grid)
    s.wires.append(Wire(WireEnd(blk.id, "XOUT"), WireEnd(grid.id, "1"), conductors=list(AC_CONDUCTORS),
                        attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("grid_cable")),
                               "cross": _s(ac.get("grid_cross")), "length": _s(ac.get("grid_length")), "method": "D"}))
    ctx.grid = grid


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


def build(ctx: ChainContext) -> None:
    """Zbytek projektu po FV části (`pv.build`): bloky za hlavním AC článkem, uzemnění, listy rozvaděčů (DC, hlavní
    AC, přípojka VN), zarovnání, rozmístění JPS na listy a vazby přívodů."""
    p, spec = ctx.project, ctx.spec
    conn = spec.get("connection") or {}
    if _s(conn.get("level")).strip().lower() == "vn":
        # přípojka VN: RFVE.AC → hlavní rozvaděč nn HR → transformátor → rozvaděč VN → DS (listy rozvaděčů níže)
        mv.build_blocks(ctx)
    else:
        _grid_block(ctx)
    _earth_block(ctx)
    p.meta.setdefault("p_installed_kwp", f"{ctx.kwp:g}")
    # listy DC rozvaděčů a AC rozvaděče
    rfve_dc.build_dc_sheets(ctx)
    sb = rfve_ac.build_main_sheet(ctx)
    if ctx.combined:
        rfve.build_dc_part(ctx, sb)
    if ctx.mv is not None:
        mv.build_sheets(ctx)
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
