"""Role `hds` – hlavní domovní skříň (přípojková skříň DS): jen blok `fve.hds` s pojistkami, bez listu (bez Qt).
Návrh `docs/design/topologie_f1_f2.md`, kap. 2 bod 3: port `1` k odběrateli (RE / RD / HR), `2` k DS; vodič HDS → DS
bez kabelu (`chain.link`). Pojistky HDS jsou jisticí přístroj selektivity (`calc.SELECTIVITY_DEVICES`)."""
from __future__ import annotations

from envocad.generator.boards.base import ChainContext, ChainPorts
from envocad.generator.context import _s
from envocad.generator.spec import chain_options, node_desc, node_ref
from envocad.model.project import Element
from envocad.model.topology import ChainNode

HDS_SYMBOL = "fve.hds"


class HdsBuilder:
    name = "hds"
    linked = True        # vodič od předchozího článku vytvoří `chain.link`

    def block(self, ctx: ChainContext, node: ChainNode) -> Element:
        o = chain_options(ctx.spec, ctx.topology, node.role)
        in_ = _s(o.get("in_") or o.get("fuse_in")).strip()
        el = Element(HDS_SYMBOL, ctx.next_x(), 150.0, attrs={
            "ref": node_ref(ctx.spec, ctx.topology, node.role, default="HDS"),
            "desc": node_desc(ctx.spec, ctx.topology, node.role, default="hlavní domovní skříň"),
            "in_": in_, "char": _s(o.get("char") or o.get("fuse_type") or "gG"), "poles": _s(o.get("poles") or 3)})
        # stávající pojistky HDS neznámé: In zůstane prázdné (F7 jen INFO `hds_no_in`, nic se nedosazuje)
        ctx.sheet.elements.append(el)
        return el

    def ports(self, ctx: ChainContext, node: ChainNode) -> ChainPorts:
        return ChainPorts(("1",), "2")

    def build(self, ctx: ChainContext, node: ChainNode) -> None:
        return None


BUILDER = HdsBuilder()
