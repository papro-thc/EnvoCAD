"""Role `grid` – distribuční soustava (DS) při připojení na nn: jen blok, bez listu (bez Qt). Vodič vede z vývodu
posledního článku řetězce, který má blok (`ctx.tail` – v F1 RFVE.AC / RFVE: stávající RD, HR, RE a HDS ještě nemají
builder), s kabelem `ac.grid_*`."""
from __future__ import annotations

from envocad.generator.boards.base import ChainContext, ChainPorts
from envocad.generator.context import _s
from envocad.library.templates import AC_CONDUCTORS
from envocad.model.project import Element, Wire, WireEnd
from envocad.model.topology import ChainNode


def build_grid(ctx: ChainContext) -> Element:
    """DS za koncem řetězce (`ctx.tail`, jinak hlavní AC článek, vývod XOUT)."""
    p, s, ac = ctx.project, ctx.sheet, ctx.spec["ac"]
    prev, port = ctx.tail or (ctx.main, "XOUT")
    grid = Element("fve.grid", ctx.geo.x_grid, 150.0, attrs={"ref": "", "voltage": _s(ctx.spec["grid"].get("voltage")),
                                                             "dso": _s(ctx.spec["grid"].get("dso"))})
    s.elements.append(grid)
    s.wires.append(Wire(WireEnd(prev.id, port), WireEnd(grid.id, "1"), conductors=list(AC_CONDUCTORS),
                        attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("grid_cable")),
                               "cross": _s(ac.get("grid_cross")), "length": _s(ac.get("grid_length")), "method": "D"}))
    ctx.grid = grid
    return grid


class GridBuilder:
    name = "grid"

    def block(self, ctx: ChainContext, node: ChainNode) -> Element | None:
        return build_grid(ctx)

    def ports(self, ctx: ChainContext, node: ChainNode) -> ChainPorts:
        return ChainPorts(("1",), "")

    def build(self, ctx: ChainContext, node: ChainNode) -> None:
        return None


BUILDER = GridBuilder()
