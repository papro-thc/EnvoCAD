"""Průchod topologií řetězce FVE (bez Qt): blok hlavního AC článku, bloky a listy článků přes registr builderů
(`BOARD_BUILDERS`), uzemnění, zarovnání a rozmístění JPS. Návrh `docs/design/topologie_f1_f2.md`, kap. 1.3 (kroky 5–6).

`build` projde `ctx.topology.nodes` dvakrát – nejdřív bloky v JPS (`BoardBuilder.block`), pak listy rozvaděčů
(`BoardBuilder.build`) – v pořadí uzlů, takže pořadí prvků i `next_ref` zůstává jako před refaktoringem. Role bez
builderu se přeskočí (F1: stávající RD, HR a RE na nn, HDS – přijdou v F2); u topologie `vn` obslouží HR, TR, RVN,
DS a odbočku RE jeden složený builder `mv`. Střídače (`inverter`) a vše před nimi staví `pv.build`.
"""
from __future__ import annotations

from envocad.generator.boards import grid, hds, house_board, meter_board, mv, rfve, rfve_ac, rfve_dc
from envocad.generator.boards.base import BoardBuilder, ChainContext
from envocad.generator.context import _s, log
from envocad.generator.jps import _place_jps
from envocad.generator.layout import (
    _align_bends,
    _align_chain,
    _align_connection,
    _align_outputs,
    _align_route_boxes,
    _chain_below,
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
    "rd": house_board.RD_BUILDER,
    "hr": house_board.HR_BUILDER,
    "re": meter_board.BUILDER,
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
    multi = len(ctx.groups) > 1          # skupiny střídačů: RFVE.AC1, RFVE.AC2… (vlastní vývod FVE v HR / RD)
    blk = Element("fve.switchboard", ctx.geo.x_blk, 150.0,
                  attrs={"ref": sw["ref"] + ("1" if multi else ""), "desc": sw["desc"]})
    ctx.sheet.elements.append(blk)
    ctx.blocks["main"] = blk
    for n, g in enumerate(ctx.groups, start=1):
        if n == 1:
            g["block"] = blk
            continue
        g["block"] = Element("fve.switchboard", ctx.geo.x_blk, 150.0, attrs={
            "ref": f"{sw['ref']}{n}", "desc": f"{sw['desc']} ({g['key']})" if g["key"] else sw["desc"]})
        ctx.sheet.elements.append(g["block"])
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
        # dřívější `ac.grid_*` jen zadané uživatelem (`ctx.raw`, ne výchozí CYKY-J 5x35 z `DEFAULT_SPEC`) a jen když
        # článek kabel nezadal (zadaný typ bez průřezu → průřez se dopočte); délka i z výchozí specifikace
        raw_ac = ctx.raw.get("ac") if isinstance(ctx.raw.get("ac"), dict) else {}
        given = bool(vals["cable"] or vals["cross"])
        for k in ("length",) if given else ("cable", "cross", "length"):
            src = ctx.spec["ac"] if k == "length" else raw_ac
            vals[k] = vals[k] or _s(src.get(f"grid_{k}")).strip()
        vals["method"] = vals["method"] or "D"
    elif prev is not None and prev.existing and not (vals["cable"] or vals["cross"]):
        return {"ref": ""}
    vals["method"] = vals["method"] or "C"
    if not vals["cross"]:
        from envocad.generator.context import _num
        i_n = _num(ctx.node_in.get(node.role))
        if i_n is None and role in MAIN_ROLES:        # RFVE.AC přímo do DS (vlastní topologie): podle proudu FVE
            from envocad.generator.currents import fve_out_in
            i_n = _num(fve_out_in(ctx.spec, ctx.inverters))
        x = min_cross(i_n or 0.0, vals["method"])
        vals["cross"] = f"{x:g}".replace(".", ",") if x else ""
        if x and not vals["cable"] and role in MAIN_ROLES:     # typ jako AC kabel střídačů („CYKY-J 5x50“)
            vals["cable"] = cable_for(ctx.spec, x)
    return {"ref": ctx.project.next_ref("W"), **vals}


def cable_for(spec: dict, cross: float) -> str:
    """Typ pětižilového kabelu s průřezem `cross` v řadě AC kabelu střídačů (`ac.cable`, výchozí CYKY-J)."""
    family = (_s(spec["ac"].get("cable")).split() or ["CYKY-J"])[0]
    return f"{family} 5x{cross:g}".replace(".", ",")


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
    if ctx.groups:                    # skupiny střídačů: RFVE.AC{n} → HR / RD X{3…} přes pár přerušení
        from envocad.generator.boards.groups import build_links
        build_links(ctx)
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
    from envocad.generator.boards.eps import build_jps
    build_jps(ctx)                    # EPS rodinného domu: BACKUP → RFVE.XE{i}, XB{i} → zálohované okruhy
    _layout(ctx)


def _place_loads(ctx: ChainContext) -> None:
    """Spotřeba objektu (`fve.load` na vývodu X2 stávajícího RD / HR) pod blokem – builder ji registruje
    v `ctx.loads` (blok, port, značka, vodič); vodič z X2 vlevo (blok je zrcadlený), svisle dolů pod blok a do značky."""
    from envocad.generator.layout import place_load
    for blk, port, load, w in ctx.loads:
        place_load(ctx.project, blk, port, load, w)


def _boundary_text(ctx: ChainContext) -> None:
    """Hranice vlastnictví DS / odběratel: `hds` → atribut `boundary` na HDS a text nad ním; `re_main` / `re_meter`
    (atribut na HJ / elektroměru v listu) → text nad blokem rozvaděče s měřením. Volný text listu (`Sheet.texts`,
    posouvá se s rozmístěním listu)."""
    from envocad.generator.boards.meter_board import BOUNDARY_TEXT
    from envocad.model.project import SheetText
    from envocad.model.textlayout import symbol_box
    if ctx.boundary is None:
        return
    blk, mode = ctx.boundary
    target = blk
    if mode == "hds":
        target = next((e for e in ctx.sheet.elements if e.symbol_id == hds.HDS_SYMBOL), None)
        if target is None:
            return
        target.attrs["boundary"] = "1"
    from envocad.generator import context
    from envocad.model.project import element_symbol
    x0, _y0, _x1, y1 = symbol_box(target, element_symbol(ctx.project, target, context._lib()))
    x, y = round(x0 / 2.5) * 2.5, round((y1 + 7.5) / 2.5) * 2.5
    old = next((t for t in ctx.sheet.texts if t.text == BOUNDARY_TEXT), None)
    if old is not None:               # znovu po přeskládání řetězce (rozdělené JPS)
        old.x, old.y = x, y
        return
    ctx.sheet.texts.append(SheetText(x=x, y=y, text=BOUNDARY_TEXT, height=2.0))


def _paper(ctx: ChainContext) -> str:
    """Formát, na který by se vešlo blokové schéma (`frame.fit_placement`) – volba rozložení řetězce."""
    from envocad.generator import context
    from envocad.model.frame import fit_placement
    from envocad.model.textlayout import sheet_content_boxes
    boxes = sheet_content_boxes(ctx.project, ctx.sheet, context._lib())
    return fit_placement(boxes)[0] if boxes else "A3"


def _paper_index(name: str) -> int:
    from envocad.model.frame import PAPER_SIZES
    order = [n for n, _w, _h in PAPER_SIZES]
    return order.index(name) if name in order else len(order)


# „column_below“ = jako „column“, DS pod HDS (vedle by ležela na svislých úsecích AC vodičů střídačů)
CHAIN_LAYOUTS = ("column", "column_below", "column_top", "column_top_below", "below", "row")


def _chain_layout_score(ctx: ChainContext, wires: set[str]) -> tuple:
    """Hodnocení rozložení řetězce na listu: (křížení vodičů řetězce, překryvy textů, formát, plocha obsahu) – menší
    je lepší. Křížení = úsek vodiče řetězce přes cizí vodič nebo přes značku."""
    from itertools import pairwise

    from envocad.generator import context
    from envocad.model.frame import fit_placement
    from envocad.model.project import element_symbol
    from envocad.model.textlayout import (
        compute_layout,
        segment_hits_box,
        sheet_content_boxes,
        symbol_box,
        text_overlaps,
    )
    p, s, lib = ctx.project, ctx.sheet, context._lib()
    lay = compute_layout(p, s, lib)
    boxes = sheet_content_boxes(p, s, lib, lay)
    segs = {wid: [(a, b) for a, b in pairwise(pts) if a != b] for wid, pts in lay.routes.items()}
    ends = {w.id: {w.a.element_id, w.b.element_id} for w in s.wires}
    cross = 0
    for wid in wires & set(segs):
        for a, b in segs[wid]:
            for oid, other in segs.items():
                if oid == wid:
                    continue
                for c, d in other:
                    if _segments_cross((a, b), (c, d)):
                        cross += 1
            for e in s.elements:
                if e.id in ends.get(wid, ()):
                    continue
                x1, y1, x2, y2 = symbol_box(e, element_symbol(p, e, lib))
                if segment_hits_box(a, b, (x1 + 0.5, y1 + 0.5, x2 - 0.5, y2 - 0.5)):
                    cross += 1
    # značky řetězce přes cizí značky (např. RFVE.AC dalších skupin střídačů pod hlavním)
    owners = {w.a.element_id for w in s.wires if w.id in wires} | {w.b.element_id for w in s.wires if w.id in wires}
    sym_boxes = {e.id: symbol_box(e, element_symbol(p, e, lib)) for e in s.elements}
    # cizí vodiče přes značky řetězce (DS / HDS uprostřed svislých úseků AC vodičů střídačů)
    for wid, sg in segs.items():
        if wid in wires:
            continue
        for eid in owners & set(sym_boxes):
            if eid in ends.get(wid, ()):
                continue
            x1, y1, x2, y2 = sym_boxes[eid]
            cross += sum(1 for a, b in sg if segment_hits_box(a, b, (x1 + 0.5, y1 + 0.5, x2 - 0.5, y2 - 0.5)))
    for a in owners & set(sym_boxes):
        ax = sym_boxes[a]
        for b, bx in sym_boxes.items():
            if b != a and b not in owners and ax[0] < bx[2] - 0.5 and bx[0] < ax[2] - 0.5 \
                    and ax[1] < bx[3] - 0.5 and bx[1] < ax[3] - 0.5:
                cross += 1
    over = len(text_overlaps(p, s, lib, lay))
    paper = fit_placement(boxes)[0] if boxes else "A3"
    w = max(b[2] for b in boxes) - min(b[0] for b in boxes)
    h = max(b[3] for b in boxes) - min(b[1] for b in boxes)
    return (cross, over, _paper_index(paper), w * h)


def _segments_cross(s1, s2) -> bool:
    """Vodorovný úsek přes svislý uvnitř obou úseků (jako test `_crossings`)."""
    (p, q), (r, t) = s1, s2
    if p[1] == q[1] and r[0] == t[0]:
        h, v = (p, q), (r, t)
    elif r[1] == t[1] and p[0] == q[0]:
        h, v = (r, t), (p, q)
    else:
        return False
    x0, x1 = sorted((h[0][0], h[1][0]))
    y0, y1 = sorted((v[0][1], v[1][1]))
    return x0 + 0.1 < v[0][0] < x1 - 0.1 and y0 + 0.1 < h[0][1] < y1 - 0.1


def _choose_chain_layout(ctx: ChainContext, links: list, in_row) -> str:
    """Zkusí rozložení řetězce stávajících článků (svisle pod RFVE.AC, v řadě pod FV částí, v řadě za RFVE.AC),
    každé ohodnotí (`_chain_layout_score`) a nechá nejlepší; vrací jeho název. Značky prvků se při zkoušení
    nemění (jen polohy) – počítají se jednou (`project.symbol_cache`)."""
    from envocad.model.project import symbol_cache
    with symbol_cache():
        return _choose_chain_layout_cached(ctx, links, in_row)


def _choose_chain_layout_cached(ctx: ChainContext, links: list, in_row) -> str:
    from envocad.generator.layout import _chain_column, chain_snapshot
    p, s, blk = ctx.project, ctx.sheet, ctx.main
    els = [el for _p, _q, el, _r, _w in links] + [ld for _b, _pt, ld, _w in ctx.loads]
    wires = [w for *_x, w in links] + [w for *_x, w in ctx.loads]
    # „column_top“ posouvá i RFVE.AC s uzemněním (AC vodiče střídačů dostanou nové lomy)
    w_earth = [w for w in s.wires if ctx.earth is not None and w.touches(ctx.earth.id)]
    restore = chain_snapshot(s, [*els, blk, *([ctx.earth] if ctx.earth is not None else [])],
                             [*wires, *w_earth, *ctx.ac_wires])
    target = _boundary_target(ctx)

    def apply(mode: str) -> bool:
        ok = _apply(mode)
        if ok and ctx.groups:         # přerušení skupin u HR / RD podle polohy a strany jeho vývodů
            from envocad.generator.boards.groups import place
            place(ctx)
        if ok and ctx.eps:            # EPS rodinného domu (RFVE za střídači) podle polohy RFVE a lomů AC vodičů
            from envocad.generator.boards.eps import place_jps
            from envocad.generator.layout import xout_lane_x
            place_jps(ctx, xout_lane_x(p, s, blk, ctx.earth, links))
        return ok

    def _apply(mode: str) -> bool:
        restore()
        in_row()
        if mode.startswith("column_top") and not _raise_main(ctx):
            return False
        if mode.startswith("column"):
            from envocad.generator.boards.groups import obstacles, place_sources
            place_sources(ctx)
            return _chain_column(p, s, blk, links, ctx.loads, ctx.earth, target, obstacles(ctx),
                                 end_below=mode.endswith("_below"))
        if mode == "below":
            return _chain_below(p, blk, links, ctx.loads, ctx.earth)
        return True

    best, best_score = "row", None
    ids = {w.id for w in wires}
    floor = None                      # nejmenší formát, kam se vejde list bez řetězce (dřívější ukončení)
    for mode in CHAIN_LAYOUTS:
        if not apply(mode):
            continue
        _boundary_text(ctx)
        sc = _chain_layout_score(ctx, ids)
        if best_score is None or sc < best_score:
            best, best_score = mode, sc
        if sc[:2] == (0, 0):
            # bez křížení a překryvů na formátu listu bez řetězce: jiné rozložení formát nezmenší – dál se nezkouší
            if floor is None:
                floor = _paper_without(ctx, {e.id for e in els}, ids)
            if sc[2] <= floor:
                break
    apply(best)
    return best


def _paper_without(ctx: ChainContext, ids: set[str], wire_ids: set[str]) -> int:
    """Index formátu (`_paper_index`), na který by se vešel list bez prvků řetězce (`ids`) a jeho vodičů."""
    from envocad.generator import context
    from envocad.model.frame import fit_placement
    from envocad.model.textlayout import sheet_content_boxes
    s = ctx.sheet
    keep_el, keep_w, keep_t = s.elements, s.wires, s.texts
    s.elements = [e for e in keep_el if e.id not in ids]
    s.wires = [w for w in keep_w if w.id not in wire_ids and w.a.element_id not in ids and w.b.element_id not in ids]
    s.texts = []
    try:
        boxes = sheet_content_boxes(ctx.project, s, context._lib())
    finally:
        s.elements, s.wires, s.texts = keep_el, keep_w, keep_t
    return _paper_index(fit_placement(boxes)[0] if boxes else "A3")


def _choose_house_layout(ctx: ChainContext, first: tuple, links: list, in_row) -> str:
    """Rodinný dům: řetězec za RD v řadě pod vším (`_route_house` + `_align_chain`), nebo svisle vpravo od FV části
    (`_house_column`) – nechá rozložení s lepším hodnocením (`_chain_layout_score`); vrací jeho název."""
    from envocad.model.project import symbol_cache
    with symbol_cache():
        return _choose_house_layout_cached(ctx, first, links, in_row)


def _choose_house_layout_cached(ctx: ChainContext, first: tuple, links: list, in_row) -> str:
    from envocad.generator.layout import _house_column, chain_snapshot
    p, s, blk = ctx.project, ctx.sheet, ctx.main
    el0, _port0, w0 = first
    els = [el0, *(el for _p, _q, el, _r, _w in links), *(ld for _b, _pt, ld, _w in ctx.loads)]
    wires = [w0, *(w for *_x, w in links), *(w for *_x, w in ctx.loads)]
    restore = chain_snapshot(s, els, wires)
    target = _boundary_target(ctx)

    def apply(mode: str) -> bool:
        restore()
        if mode.startswith("column"):     # „column_below“: DS pod HDS (užší sloupec)
            return _house_column(p, s, blk, first, links, ctx.loads, ctx.earth, target,
                                 end_below=mode == "column_below")
        in_row()
        if mode == "row_left":        # řada doleva pod vším (výkres se nerozšíří vpravo)
            from envocad.generator.layout import _house_row_left
            return _house_row_left(p, s, blk, first, links, ctx.loads, ctx.earth)
        return True

    best, best_score = "row", None
    ids = {w.id for w in wires}
    for mode in ("row", "column", "column_below", "row_left"):
        if not apply(mode):
            continue
        _boundary_text(ctx)
        sc = _chain_layout_score(ctx, ids)
        if best_score is None or sc < best_score:
            best, best_score = mode, sc
    apply(best)
    return best


def _raise_main(ctx: ChainContext) -> bool:
    """RFVE.AC (s uzemněním) nahoru: horní přívod na výšku AC vývodu nejvyššího střídače na listu – pod blokem je
    pak místo na svislý řetězec. False = blok už výš nejde (nic se nezměnilo)."""
    from envocad.generator import context
    from envocad.model.project import element_symbol
    p, s, blk, lib = ctx.project, ctx.sheet, ctx.main, context._lib()
    ys = []
    for w in ctx.ac_wires:
        a = s.element(w.a.element_id) if any(e.id == w.a.element_id for e in s.elements) else None
        if a is not None:
            ys.append(a.port_pos(element_symbol(p, a, lib), w.a.port)[1])
    sym = element_symbol(p, blk, lib)
    feeds = [blk.port_pos(sym, pt.name)[1] for pt in sym.ports if pt.dir == "W"]
    if not ys or not feeds:
        return False
    dy = round((max(ys) - max(feeds)) / 2.5) * 2.5
    if dy <= 0:
        return False
    blk.y += dy
    if ctx.earth is not None:
        ctx.earth.y += dy
    for w in s.wires:
        if ctx.earth is not None and w.touches(ctx.earth.id):
            w.points = [(x, y + dy) for x, y in w.points]
    _align_bends(p)
    return True


def _boundary_target(ctx: ChainContext) -> Element | None:
    """Prvek blokového schématu, nad kterým leží text hranice vlastnictví (HDS, nebo blok s měřením)."""
    if ctx.boundary is None:
        return None
    blk, mode = ctx.boundary
    if mode == "hds":
        return next((e for e in ctx.sheet.elements if e.symbol_id == hds.HDS_SYMBOL), None)
    return blk


def _layout(ctx: ChainContext) -> None:
    """Zarovnání bloků a lomů JPS, rozmístění na list(y), zvětšení přetékajících listů rozvaděčů, vazby přívodů.
    Do vazeb přívodů se atributy ani zapojení prvků nemění (jen polohy, přerušení při dělení JPS) – značky se počítají
    jednou (`project.symbol_cache`); vazby přívodů mění texty přívodů / vývodů, proto až za mezipamětí."""
    from envocad.model.project import symbol_cache
    with symbol_cache():
        dc_sheets = _layout_place(ctx)
    p = ctx.project
    sync_feed_links(p)
    if _grow_switchboards(p, dc_sheets):
        sync_feed_links(p)
    sync_cables(p)


def _layout_place(ctx: ChainContext) -> list:
    """`_layout` až po první zvětšení listů rozvaděčů; vrací listy rozvaděčů ke zvětšení."""
    p, s, blk = ctx.project, ctx.sheet, ctx.main
    if ctx.combined or ctx.dc_common is not None:   # rozvaděče po trase na výšku přívodů RFVE / společného RFVE.DC
        target = blk if ctx.combined else ctx.dc_common
        _align_route_boxes(p, target, [[b for b, _g, k, no, _r in ctx.dc_boxes if no == i + 1 and b is not target]
                                       for i in range(len(ctx.inverters))])
    if ctx.groups:                    # RFVE.AC{n} u svých střídačů
        from envocad.generator.boards.groups import align_blocks
        align_blocks(ctx)
    _align_bends(p)
    links = list(ctx.links)
    mode = "row"

    def in_row() -> None:
        _align_chain(p, links)
        _place_loads(ctx)

    choose = not ctx.combined and ctx.mv is None and len(links) > 2
    first = None
    if ctx.combined and links:
        _prev, _pp, el0, port0, w0 = links.pop(0)
        first = (el0, port0, w0)
        from envocad.generator.boards.eps import EPS_LANE_GAP, place_jps
        gap = EPS_LANE_GAP if ctx.eps else 0.0
        _route_house(p, blk, ctx.ac_wires, first, ctx.earth, gap)
        if ctx.eps:                   # EPS u RFVE, pak trasa znovu – řetězec pod značkou zálohovaných okruhů
            place_jps(ctx, w0.points[0][0] if w0.points else None)
            _route_house(p, blk, ctx.ac_wires, first, ctx.earth, gap)
        if links:
            mode = _choose_house_layout(ctx, first, links, in_row)
    else:
        _align_outputs(p, blk, None, ctx.earth)
        if ctx.eps:                   # rodinný dům bez DC části (RFVE za střídači): EPS u RFVE před volbou řetězce
            from envocad.generator.boards.eps import place_jps
            from envocad.generator.layout import xout_lane_x
            place_jps(ctx, xout_lane_x(p, ctx.sheet, blk, ctx.earth, links))   # i pro řetězec v řadě
        # firma na nn s několika články za RFVE.AC: řetězec svisle pod RFVE.AC, v řadě pod FV částí, nebo v řadě
        # za RFVE.AC – podle toho, co dá nejmenší výkres bez křížení a překryvů textů (`_choose_chain_layout`)
        if choose:
            mode = _choose_chain_layout(ctx, links, in_row)
    if mode == "row":
        in_row()
        if ctx.groups:
            from envocad.generator.boards.groups import place
            place(ctx)

    def after_split() -> None:          # list „AC a připojení“ bez řad střídačů: řetězec znovu
        if ctx.groups:                  # RFVE.AC{n} skupin zůstaly na výšce svých (přesunutých) střídačů
            from envocad.generator.boards.groups import stack_after_split
            stack_after_split(ctx)
        if choose:
            _choose_chain_layout(ctx, links, in_row)
        elif first is not None and links:
            _choose_house_layout(ctx, first, links, in_row)
        else:
            return
        _boundary_text(ctx)

    _boundary_text(ctx)
    if ctx.mv is not None:
        _align_connection(p, blk, ctx.mv)
    _place_jps(p, s, ctx.spec.get("jps") or {}, ctx.rows, ctx.ac_wires, blk, after_split,
               {ctx.dc_common.id} if ctx.dc_common is not None else set())
    # až po rozmístění na list: vazby přívodů ukládají texty s polohou v JPS („W3 T1:DC1 /1.F3“); listy DC rozvaděčů,
    # které přetékají formát (DC rozvaděč s mnoha stringy po 50 mm), se zvětší – před vazbami (sloupce listu)
    # i po nich (delší texty vazeb)
    # i AC rozvaděč / rozvaděč FVE rodinného domu (DC část „U“ po `DC_U_PITCH`, mnoho střídačů)
    dc_sheets = [sh for sh in p.sheets if sh.parent_element_id in {b.id for b, *_ in ctx.dc_boxes} | {blk.id}]
    _grow_switchboards(p, dc_sheets)
    return dc_sheets
