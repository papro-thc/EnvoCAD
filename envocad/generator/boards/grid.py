"""Role `grid` – distribuční soustava (DS) při připojení na nn: jen blok, bez listu (bez Qt). Vodič k ní vede
z vývodu předchozího článku řetězce (`chain.link`; z HDS bez kabelu, z hlavního AC článku s kabelem `ac.grid_*`)."""
from __future__ import annotations

from envocad.generator.boards.base import ChainContext, ChainPorts
from envocad.generator.context import _s
from envocad.library.templates import AC_CONDUCTORS
from envocad.model.project import Element, Wire, WireEnd
from envocad.model.topology import ChainNode


def grid_element(ctx: ChainContext, x: float) -> Element:
    grid = Element("fve.grid", x, 150.0, attrs={"ref": "", "voltage": _s(ctx.spec["grid"].get("voltage")),
                                                "dso": _s(ctx.spec["grid"].get("dso"))})
    ctx.sheet.elements.append(grid)
    ctx.grid = grid
    return grid


def build_grid(ctx: ChainContext) -> Element:
    """DS za koncem řetězce (`ctx.tail`, jinak hlavní AC článek, vývod XOUT) – vlastní topologie bez článku „grid“;
    kabel jako u článku „grid“ (`chain.link_attrs`)."""
    from envocad.generator.chain import link_attrs
    prev, port = ctx.tail or (ctx.main, "XOUT")
    grid = grid_element(ctx, ctx.next_x())
    w = Wire(WireEnd(prev.id, port), WireEnd(grid.id, "1"), conductors=list(AC_CONDUCTORS),
             attrs=link_attrs(ctx, ctx.tail_node, ChainNode(role="grid")))
    ctx.sheet.wires.append(w)
    ctx.links.append((prev, port, grid, "1", w))
    return grid


class GridBuilder:
    name = "grid"
    linked = True

    def block(self, ctx: ChainContext, node: ChainNode) -> Element | None:
        return grid_element(ctx, ctx.next_x(small=True))

    def ports(self, ctx: ChainContext, node: ChainNode) -> ChainPorts:
        return ChainPorts(("1",), "")

    def build(self, ctx: ChainContext, node: ChainNode) -> None:
        return None


BUILDER = GridBuilder()
