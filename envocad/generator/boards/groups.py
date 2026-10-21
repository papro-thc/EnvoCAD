"""Skupiny střídačů na jiném místě (`inverters[].ac_group`) – bez Qt. Návrh docs/design/topologie_f1_f2.md, kap. 2
bod 10; rozhodnutí 3 (docs/NAVRH_TOPOLOGIE.md, kap. 8: RFVE.AC vždy společný, pokud střídače nejsou na jiném místě).

Skupina = vlastní AC rozvaděč RFVE.AC{n} (hlavní skupina „“ = RFVE.AC1) se svými střídači (přívody X1…Xk) a vlastní
vývod FVE ve stávajícím HR / RD (`X1` hlavní skupina, `X3`, `X4`… další; `X2` = stávající rozvody). V blokovém
schématu stojí RFVE.AC{n} u svých střídačů (na výšku jejich AC vývodů) s vlastním uzemněním (HOP); kabel
RFVE.AC{n} XOUT → HR / RD X{3…} vede přes pár přerušovacích bodů „AC{n}-<HR>“ (údaje kabelu u RFVE.AC{n}, úsek u HR
je pokračování) – řetězec HR → RE → HDS → DS se skládá jako bez skupin (`chain._choose_chain_layout`)."""
from __future__ import annotations

from envocad.generator.context import _s
from envocad.library.templates import AC_CONDUCTORS
from envocad.model.project import INTERRUPT_SYMBOL, Element, Wire, WireEnd

GROUP_INT_GAP = 30.0          # přerušení u vývodu XOUT RFVE.AC{n} (místo pro popisek kabelu)
GROUP_INT_GAP_HR = 22.5       # přerušení u vývodu X{3…} HR / RD (místo pro odkaz vazby; spotřeba z X2 visí až za ním)


def feeds(n_groups: int) -> list[str]:
    """Vývody FVE v HR / RD pro skupiny: X1, X3, X4… (X2 = stávající rozvody)."""
    return ["X1", *(f"X{k + 3}" for k in range(n_groups - 1))]


def first_board(ctx) -> Element | None:
    """Blok stávajícího HR / RD (první článek za RFVE.AC)."""
    return ctx.blocks.get("hr") or ctx.blocks.get("rd")


def build_links(ctx) -> None:
    """Vodiče skupin 2… k HR / RD přes pár přerušení (po bloku HR / RD, před listy rozvaděčů); uzemnění bloků."""
    from envocad.generator.chain import link_attrs
    s = ctx.sheet
    hr = first_board(ctx)
    node = next((n for n in ctx.topology.nodes if n.role in ("hr", "rd")), None) if ctx.topology else None
    main_node = ctx.topology.node("rfve_ac") if ctx.topology else None
    if hr is None or node is None:
        return
    from envocad.generator.boards.house_board import group_feeder_in
    for n, g in enumerate(ctx.groups[1:], start=2):
        blk = g["block"]
        ref = f"AC{n}-{hr.ref}"
        i_g = Element(INTERRUPT_SYMBOL, blk.x, blk.y, attrs={"ref": ref})
        i_h = Element(INTERRUPT_SYMBOL, hr.x, hr.y, attrs={"ref": ref})
        s.elements += [i_g, i_h]
        keep = dict(ctx.node_in)
        ctx.node_in[node.role] = group_feeder_in(ctx, g)        # průřez kabelu podle vývodu FVE skupiny
        attrs = link_attrs(ctx, main_node, node)
        ctx.node_in = keep
        w_g = Wire(WireEnd(blk.id, "XOUT"), WireEnd(i_g.id, "1"), conductors=list(AC_CONDUCTORS), attrs=attrs)
        w_h = Wire(WireEnd(i_h.id, "1"), WireEnd(hr.id, g["feed"]), conductors=list(AC_CONDUCTORS), attrs={"ref": ""})
        s.wires += [w_g, w_h]
        g.update(int_g=i_g, int_h=i_h, w_g=w_g, w_h=w_h)
        _earth(ctx, g)


def _earth(ctx, g: dict) -> None:
    """Uzemnění (HOP) bloku RFVE.AC{n} – jako `chain._earth_block` u hlavního."""
    ac, p, s, blk = ctx.spec["ac"], ctx.project, ctx.sheet, g["block"]
    if (ac.get("distribution") or "bus") != "bus":
        return
    earth = Element("fve.earth", blk.x + 35.0, blk.y - 40.0, attrs={"ref": "", "desc": "ekvipotenciální svorkovnice (HOP)"})
    s.elements.append(earth)
    w = Wire(WireEnd(blk.id, "XPE"), WireEnd(earth.id, "PE"), conductors=["PE"],
             attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("pe_cable") or "CYA 16"),
                    "cross": _s(ac.get("pe_cross") or 16), "length": _s(ac.get("pe_length") or 5)})
    s.wires.append(w)
    g["earth"] = earth


def align_blocks(ctx) -> None:
    """Bloky RFVE.AC{n} na výšku AC vývodů svých střídačů (přívody na střed), uzemnění pod XPE."""
    from envocad.generator import context
    from envocad.generator.layout import _align_outputs
    from envocad.model.project import element_symbol
    lib = context._lib()
    p = ctx.project
    for g in ctx.groups:
        blk = g["block"]
        sym = element_symbol(p, blk, lib)
        ys = [ctx.inverters[i].port_pos(element_symbol(p, ctx.inverters[i], lib), "AC")[1] for i in g["idx"]]
        ins = [blk.port_pos(sym, f"X{k + 1}")[1] for k in range(len(g["idx"]))
               if any(pt.name == f"X{k + 1}" for pt in sym.ports)]
        if ys and ins:
            blk.y += round((sum(ys) / len(ys) - sum(ins) / len(ins)) / 2.5) * 2.5
        if g.get("earth") is not None:
            _align_outputs(p, blk, None, g["earth"])


def place_sources(ctx) -> None:
    """Přerušení u vývodu XOUT RFVE.AC{n} vpravo (před volbou rozložení řetězce – sloupec se mu vyhne)."""
    from envocad.generator import context
    from envocad.generator.layout import _port
    lib = context._lib()
    dx_port = lib.get_symbol(INTERRUPT_SYMBOL).port("1").x
    for g in ctx.groups[1:]:
        if "int_g" not in g:
            continue
        ox, oy = _port(ctx.project, g["block"], "XOUT", lib)
        ig = g["int_g"]
        ig.rotation, ig.x, ig.y = 0, ox + GROUP_INT_GAP - dx_port, oy
        g["w_g"].points = []


def obstacles(ctx) -> list[Element]:
    """Prvky skupin 2… (blok, uzemnění, přerušení u XOUT) – svislý řetězec pod RFVE.AC1 je musí obejít."""
    return [e for g in ctx.groups[1:] for e in (g.get("block"), g.get("earth"), g.get("int_g")) if e is not None]


def place(ctx) -> None:
    """Přerušení skupin: u XOUT RFVE.AC{n} vpravo, u vývodu X{3…} HR / RD krátce ven (podle strany portu)."""
    from envocad.generator import context
    from envocad.generator.layout import _port, _side
    lib = context._lib()
    p = ctx.project
    hr = first_board(ctx)
    if hr is None:
        return
    place_sources(ctx)
    dx_port = lib.get_symbol(INTERRUPT_SYMBOL).port("1").x
    for g in ctx.groups[1:]:
        if "int_h" not in g:
            continue
        hx, hy = _port(p, hr, g["feed"], lib)
        sg = _side(p, hr, g["feed"], lib)
        ih = g["int_h"]
        ih.rotation = 0 if sg > 0 else 180
        ih.x, ih.y = hx + sg * (GROUP_INT_GAP_HR - dx_port), hy
        g["w_h"].points = []


GROUP_STACK_GAP = 20.0        # svislá mezera mezi skupinami na listu „AC a připojení“ po rozdělení JPS


def stack_after_split(ctx) -> None:
    """Rozdělené JPS: RFVE.AC{n} skupin (s uzemněním a přerušeními AC kabelů a vývodu) pod obsah s RFVE.AC1 –
    jinak by zůstaly na výšce svých střídačů (ty jsou na listech střídačů) a list „AC a připojení“ by přerostl."""
    from envocad.generator import context
    from envocad.generator.jps import _components, component_boxes
    s, lib = ctx.sheet, context._lib()
    comps = _components(s)
    # RFVE.AC1 s uzemněním a přerušeními AC kabelů (bez řetězce za ním – ten se pak skládá znovu)
    chain_wires = {w.id for *_x, w in ctx.links}
    main = {ctx.main.id} | {(w.b.element_id if w.a.element_id == ctx.main.id else w.a.element_id)
                            for w in s.wires if w.touches(ctx.main.id) and w.id not in chain_wires}
    boxes = component_boxes(ctx.project, s, main, lib)
    if not boxes:
        return
    bottom = min(b[1] for b in boxes)
    for g in ctx.groups[1:]:
        comp = next((c for c in comps if g["block"].id in c), None)
        if comp is None or ctx.main.id in comp and len(comp & main) > 1 and g["block"].id in main:
            continue
        own = component_boxes(ctx.project, s, comp, lib)
        if not own:
            continue
        dy = round((bottom - GROUP_STACK_GAP - max(b[3] for b in own)) / 2.5) * 2.5
        for e in s.elements:
            if e.id in comp:
                e.y += dy
        for w in s.wires:
            if w.a.element_id in comp and w.b.element_id in comp:
                w.points = [(x, y + dy) for x, y in w.points]
        bottom = min(b[1] for b in own) + dy
