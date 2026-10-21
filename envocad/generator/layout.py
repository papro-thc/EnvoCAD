"""Rozmístění v blokovém schématu (JPS) a zvětšení listů rozvaděčů (bez Qt): zarovnání bloků na výšku vodičů,
lomy vodičů, trasa rodinného domu. Přesun 1:1 z `generate.py` (refaktoring F1, krok 3)."""
from __future__ import annotations

from itertools import pairwise

from envocad.generator import context
from envocad.model.feed import is_feed_out
from envocad.model.project import PORT_PITCH, Element, Project, Sheet, Wire, element_symbol


def _grow_switchboards(p: Project, sheets: list[Sheet]) -> bool:
    """Zvětšení listů rozvaděčů, které přetékají (šířka roste se stringy po `DC_STRING_PITCH` / `DC_U_PITCH`
    a se střídači): přednostně prodloužený formát na šířku se stejnou výškou (`frame.grow_sheet_long` – RFVE
    s 9 stringy je A4×5, ne A0), jinak `frame.grow_sheet_to_content`. True = některý list se změnil."""
    from envocad.model.frame import grow_sheet_long, grow_sheet_to_content
    lib = context._lib()
    changed = False
    for sh in sheets:
        changed = (grow_sheet_long(p, sh, lib) or grow_sheet_to_content(p, sh, lib)) or changed
    return changed


def _align_route_boxes(p: Project, blk: Element, chains: list[list[Element]]) -> None:
    """Rozvaděče po trase rodinného domu na výšku přívodů rozvaděče FVE: vývody posledního rozvaděče trasy leží
    proti DC přívodům RFVE, vodiče vedou rovně (bez lomů, přes které by šly popisky kabelů). Celý řetěz rozvaděčů
    střídače se posune stejně; kdyby se rozvaděče různých střídačů překryly, zůstane lom."""
    lib = context._lib()
    s = p.sheets[0]
    plan: list[tuple[list[Element], float, list[Wire]]] = []
    spans: list[tuple[float, float]] = []
    for chain in chains:
        if not chain:
            continue
        last = chain[-1]
        ws = [w for w in s.wires if w.a.element_id == last.id and w.b.element_id == blk.id]
        if not ws:
            continue
        dys = {round(blk.port_pos(element_symbol(p, blk, lib), w.b.port)[1]
                     - last.port_pos(element_symbol(p, last, lib), w.a.port)[1], 3) for w in ws}
        if len(dys) != 1:
            return
        dy = dys.pop()
        half = max(abs(pt.y) for pt in element_symbol(p, last, lib).ports) + PORT_PITCH
        spans.append((last.y + dy - half, last.y + dy + half))
        plan.append((chain, dy, ws))
    spans.sort()
    if any(a[1] > b[0] for a, b in pairwise(spans)):
        return
    for chain, dy, ws in plan:
        for b in chain:
            b.y += dy
        for w in ws:
            w.points = []


def _route_house(p: Project, blk: Element, ac_wires: list[Wire], first: tuple[Element, str, Wire],
                 earth: Element | None) -> None:
    """JPS rodinného domu: rozvaděč FVE stojí před střídači. AC vodiče od střídačů vedou nad vším zpět na přívody
    X1…Xn vlevo (vnější lom pro dolní střídač – bez křížení), vývod XOUT pod vším k prvnímu článku za střídači
    (`first` = blok, jeho přívod, vodič – RD, jinak HDS / DS), uzemnění (HOP) hned pod vývod XPE."""
    from envocad.model.textlayout import symbol_box
    grid, grid_port, w_grid = first
    from envocad.model.textlayout import sheet_content_boxes
    lib = context._lib()
    s = p.sheets[0]

    def port(e: Element, name: str) -> tuple[float, float]:
        return e.port_pos(element_symbol(p, e, lib), name)

    def snap(v: float) -> float:
        return round(v / 2.5) * 2.5

    sheet = p.switchboard_sheet(blk.id)
    names = {e.ref for e in (sheet.elements if sheet else []) if is_feed_out(e)}
    w_earth = next((w for w in s.wires if earth is not None and earth.id in (w.a.element_id, w.b.element_id)), None)
    if earth is not None and "XPE" not in names:   # bez svodičů a PE vývodu (rozvod svorkami) – uzemnění nekreslit
        s.elements.remove(earth)
        s.wires.remove(w_earth)
        earth, w_earth = None, None
    bx = blk.x
    if earth is not None:
        xpe = port(blk, "XPE")
        earth.x, earth.y = bx + 22.5, snap(xpe[1] - 15.0)
        w_earth.points = [(bx + 22.5, xpe[1])]
    # obálky obsahu bez AC vodičů a vodiče k síti (ty se teprve trasují)
    routed = {w.id for w in ac_wires} | {w_grid.id}
    keep = s.wires
    s.wires = [w for w in keep if w.id not in routed]
    try:
        boxes = sheet_content_boxes(p, s, lib)
    finally:
        s.wires = keep
    x_lo = bx - 15.0 - 5.0 * len(ac_wires)
    x_hi = max(port(s.element(w.a.element_id), "AC")[0] for w in ac_wires) + 10.0 + 5.0 * len(ac_wires)
    top = max((b[3] for b in boxes if b[2] >= x_lo and b[0] <= x_hi), default=blk.y)
    y_top = snap(top + 7.5)
    for i, w in enumerate(ac_wires):
        ac = port(s.element(w.a.element_id), "AC")
        feed = port(blk, w.b.port)
        x_r, x_l, lane = ac[0] + 10.0 + 5.0 * i, bx - 20.0 - 5.0 * i, y_top + 5.0 * i
        w.points = [(x_r, ac[1]), (x_r, lane), (x_l, lane), (x_l, feed[1])]
    out = port(blk, "XOUT")
    x_out = bx + 30.0
    if w_earth is not None:   # svislý úsek k síti až za popiskem vodiče k uzemnění
        from envocad.model.textlayout import compute_layout
        lp = compute_layout(p, s, lib).wires.get(w_earth.id)
        x_out = max([x_out, *(snap(b[2] + 5.0) for b in (lp.boxes if lp else []))])
    sym = element_symbol(p, grid, lib)
    above = symbol_box(grid, sym)[3] - port(grid, grid_port)[1]      # značka nad přívodem (blok RD: popis, řádky)
    # pod vším vpravo od svislého úseku: za prvním článkem pokračuje řetězec (RE, HDS, DS) ve stejné výšce
    bottom = min((b[1] for b in boxes if b[2] >= x_out - 5.0), default=blk.y)
    y = snap(bottom - 7.5 - max(0.0, above))
    grid.y += y - port(grid, grid_port)[1]
    w_grid.points = [(x_out, out[1]), (x_out, y)]


def _chain_below(p: Project, blk: Element, links: list, loads: list, earth: Element | None,
                 x0: dict[str, float] | None = None) -> bool:
    """Firma / bytový dům na nn: řetězec stávajících článků (HR → RE → HDS → DS) v řadě pod FV částí – vodič
    z vývodu XOUT hlavního AC rozvaděče vede vpravo, svisle dolů pod řetězec, vlevo a zespodu do přívodu X1 prvního
    článku; řetězec končí vlevo od svislého úseku. Výkres zůstane úzký (řetězec v jedné řadě za RFVE.AC by
    vícestřídačovou FVE přenesl přes A2 a rozdělil na listy). Nevejde-li se řetězec pod FV část, vrací False (pak
    zůstane v řadě za RFVE.AC)."""
    from envocad.model.textlayout import compute_layout, sheet_content_boxes, symbol_box
    lib = context._lib()
    s = p.sheets[0]
    if not links:
        return False

    def port(e: Element, name: str) -> tuple[float, float]:
        return e.port_pos(element_symbol(p, e, lib), name)

    def snap(v: float) -> float:
        return round(v / 2.5) * 2.5

    _prev, _pp, first, fport, w0 = links[0]
    chain_els = [first, *(el for _p, _q, el, _r, _w in links[1:]), *(ld for _b, _pt, ld, _w in loads)]
    chain_ids = {e.id for e in chain_els}
    if x0 is not None:                # opakované volání (po rozdělení JPS): od původních x řetězce
        for e in chain_els:
            e.x = x0.setdefault(e.id, e.x)
    chain_wires = {w.id for *_x, w in links} | {w.id for *_x, w in loads}
    keep_el, keep_w = s.elements, s.wires
    s.elements = [e for e in keep_el if e.id not in chain_ids]
    s.wires = [w for w in keep_w if w.id not in chain_wires]
    try:
        boxes = sheet_content_boxes(p, s, lib)
        lay = compute_layout(p, s, lib)
    finally:
        s.elements, s.wires = keep_el, keep_w
    if not boxes:
        return False
    out = port(blk, "XOUT")
    x_out = out[0] + 15.0
    w_earth = next((w for w in s.wires if earth is not None and w.touches(earth.id)), None)
    if w_earth is not None and w_earth.id in lay.wires:
        x_out = max([x_out, *(snap(b[2] + 5.0) for b in lay.wires[w_earth.id].boxes)])
    x_left = min(b[0] for b in boxes)
    bottom = min(b[1] for b in boxes)
    # řetězec v řadě: první blok na výšku pod obsah, další zarovnané (`_align_chain`), spotřeba pod HR / RD
    above = symbol_box(first, element_symbol(p, first, lib))[3] - port(first, fport)[1]
    first.y += snap(bottom - 15.0 - above) - port(first, fport)[1]
    _align_chain(p, links[1:])
    for b, pt, ld, w in loads:
        place_load(p, b, pt, ld, w)
    lo = min(symbol_box(e, element_symbol(p, e, lib))[0] for e in chain_els)
    hi = max(symbol_box(e, element_symbol(p, e, lib))[2] for e in chain_els)
    x_l_need = 40.0                                    # zespodu do X1: svislý úsek vlevo od řetězce (popisek)
    dx = snap(x_out - 25.0 - hi)
    if lo + dx - x_l_need < x_left:
        dx = snap(x_left + x_l_need - lo)
    if hi + dx > x_out - 15.0:
        return False
    for e in chain_els:
        e.x += dx
    for _b, _pt, _ld, w in loads:
        w.points = [(x + dx, y) for x, y in w.points]
    s.elements, s.wires = [e for e in keep_el], keep_w
    rows = [b for e in chain_els for b in [symbol_box(e, element_symbol(p, e, lib))]]
    y_low = snap(min(b[1] for b in rows) - 20.0)
    x1 = port(first, fport)
    x_l = snap(x1[0] - 30.0)
    w0.points = [(x_out, out[1]), (x_out, y_low), (x_l, y_low), (x_l, x1[1])]
    return True


def _align_chain(project: Project, links: list[tuple[Element, str, Element, str, Wire]]) -> None:
    """Bloky řetězce za prvním článkem k síti na výšku vývodu předchozího (vodiče vedou rovně): RE na přívod RD/HR,
    HDS na přívod RE, DS na HDS. `links` v pořadí řetězce (`ChainContext.links`)."""
    lib = context._lib()
    for prev, pport, el, port, w in links:
        y_prev = prev.port_pos(element_symbol(project, prev, lib), pport)[1]
        el.y += y_prev - el.port_pos(element_symbol(project, el, lib), port)[1]
        w.points = []


def place_load(project: Project, blk: Element, port: str, load: Element, w: Wire) -> None:
    """Spotřeba objektu pod zrcadleným blokem (stávající RD / HR, vývod X2 vlevo): z vývodu kousek vlevo, svisle
    dolů pod blok a vpravo do značky (jako `_align_connection` u přípojky VN)."""
    lib = context._lib()
    sym = element_symbol(project, blk, lib)
    if not any(pt.name == port for pt in sym.ports):
        return
    xs = blk.port_pos(sym, port)
    low = blk.y - max(abs(pt.y) for pt in sym.ports) - 25.0
    lp = load.port_pos(element_symbol(project, load, lib), "1")
    load.x += xs[0] + 7.5 - lp[0]
    load.y += low - lp[1]
    w.points = [(xs[0] - 20.0, xs[1]), (xs[0] - 20.0, low)]


def _align_outputs(project: Project, blk: Element, grid: Element | None, earth: Element | None) -> None:
    """Síť (DS) na výšku vývodu XOUT bloku AC rozvaděče (vodič vede rovně) a uzemnění (HOP) pod vývod XPE –
    porty bloku jsou známé až po vytvoření listu rozvaděče."""
    from envocad.model.project import element_symbol
    sym = element_symbol(project, blk, context._lib())
    names = {pt.name for pt in sym.ports}
    if "XOUT" in names and grid is not None:
        grid.y = blk.port_pos(sym, "XOUT")[1]
    if earth is not None and "XPE" in names:
        earth.y = blk.port_pos(sym, "XPE")[1] - 20.0


def _align_connection(project: Project, blk: Element, chain: dict) -> None:
    """Bloky přípojky na výšku vodičů (vodiče vedou rovně): hlavní rozvaděč nn HR na XOUT bloku RFVE.AC, transformátor na
    přívod XT, rozvaděč VN vývodem X1 na transformátor (u sloupové TS přístroje na sloupu na port transformátoru),
    sítě na přívody XDS; spotřeba pod vývod X2, elektroměrový rozvaděč pod rozvaděč s měřením."""
    lib = context._lib()
    sheet = project.sheets[0]

    def port_pos(e: Element, port: str) -> tuple[float, float] | None:
        sym = element_symbol(project, e, lib)
        return e.port_pos(sym, port) if any(pt.name == port for pt in sym.ports) else None

    def align(e: Element, port: str, target) -> None:
        pos = port_pos(e, port)
        if pos is not None and target is not None:
            e.y += target[1] - pos[1]

    def bottom_of(e: Element) -> float:
        sym = element_symbol(project, e, lib)
        return e.y - max(abs(pt.y) for pt in sym.ports)

    def wire_to(eid: str, port: str | None = None):
        return [w for w in sheet.wires if w.touches(eid) and (port is None or port in (w.a.port, w.b.port))]

    align(chain["hr"], "X1", port_pos(blk, "XOUT"))
    align(chain["tr"], "2", port_pos(chain["hr"], "XT"))
    t1 = port_pos(chain["tr"], "1")
    if chain["rvn"] is not None:
        align(chain["rvn"], "X1", t1)
        feeds = [port_pos(chain["rvn"], f"XDS{k + 1}") for k in range(len(chain["grids"]))]
    else:
        qs, fu, fv = chain["pole"]
        align(fu, "2", t1)
        align(qs, "2", t1)
        fv.x += t1[0] + 12.5 - port_pos(fv, "1")[0]
        fv.y += t1[1] - 12.5 - port_pos(fv, "1")[1]
        for w in wire_to(fv.id):
            w.points = [(t1[0] + 12.5, t1[1])]
        feeds = [port_pos(qs, "1")]
    for k, g in enumerate(chain["grids"]):
        pos = feeds[k]
        if pos is None:
            continue
        align(g, "1", (pos[0], pos[1] - 15.0 * k))
        if k:
            x_bend = port_pos(g, "1")[0] - 20.0
            for w in sheet.wires:
                if w.touches(g.id):
                    w.points = [(x_bend, pos[1]), (x_bend, pos[1] - 15.0 * k)]
    xs = port_pos(chain["hr"], "X2")
    low = bottom_of(chain["hr"]) - 25.0
    if xs is not None:
        # spotřeba pod blokem: z X2 (vlevo, blok je zrcadlený) kousek vlevo, svisle dolů pod blok a vpravo do značky
        load = chain["load"]
        x_bend = xs[0] - 20.0          # za svislými měřicími obvody (ty vedou těsně u bloku)
        lp = port_pos(load, "1")
        load.x += xs[0] + 7.5 - lp[0]
        load.y += low - lp[1]
        for w in wire_to(load.id):
            w.points = [(x_bend, xs[1]), (x_bend, low)]
    # elektroměrový rozvaděč pod rozvaděčem s měřením (pod spotřebou) a vpravo: měřicí obvody vedou z bloku vlevo,
    # svisle dolů (XMI blíž bloku) a vodorovně do přívodů RE – vodorovný úsek je nejdelší, popisky kabelů leží nad
    # ním a nepřekrývají se (svislý úsek by popisek nesl vpravo přes druhý vodič)
    src, re_ = chain["src"], chain["re"]
    top = min(low - 20.0, bottom_of(src) - 25.0) if src is chain["hr"] else bottom_of(src) - 25.0
    a, ps0 = port_pos(re_, "XMI"), port_pos(src, "XMI")
    if a is not None and ps0 is not None:
        re_.y += top - a[1]
        x_bend = ps0[0] - 3.0
        re_.x += x_bend + (ps0[1] - top) + 15.0 - port_pos(re_, "XMI")[0]
        for n, name in enumerate(("XMI", "XMU")):
            ps, pr = port_pos(src, name), port_pos(re_, name)
            if ps is None or pr is None:
                continue
            xb = x_bend - 5.0 * n
            for w in wire_to(re_.id, name):
                w.points = [(xb, ps[1]), (xb, pr[1])]


def _align_bends(project: Project) -> None:
    """Lomy vodičů JPS podle skutečných poloh portů (porty bloků rozvaděčů a střídačů se dopočítají až z listů):
    vodič s jediným svislým úsekem [(x, y1), (x, y2)] dostane y1 = y portu A, y2 = y portu B – je pak jen
    vodorovný–svislý–vodorovný. Svislé úseky víc vodičů do jednoho prvku (konec B) se přeskládají na svých x tak,
    aby se nekřížily (shora dolů: nejvyšší nejdál, zdola nahoru: nejnižší nejdál). Volá se před rozdělením JPS na
    listy (`_place_jps` – rozmístění posouvá prvky i lomy celého listu stejně), projde všechny listy, které nejsou
    rozvaděč."""
    lib = context._lib()
    for s in project.sheets:
        if not s.is_switchboard:
            _align_bends_sheet(project, s, lib)


def _align_bends_sheet(project: Project, s: Sheet, lib) -> None:
    from envocad.model.project import element_symbol
    groups: dict[str, list] = {}
    for w in s.wires:
        if len(w.points) != 2 or abs(w.points[0][0] - w.points[1][0]) > 1e-6:
            continue
        ea, eb = s.element(w.a.element_id), s.element(w.b.element_id)
        try:
            ya = ea.port_pos(element_symbol(project, ea, lib), w.a.port)[1]
            yb = eb.port_pos(element_symbol(project, eb, lib), w.b.port)[1]
        except (KeyError, StopIteration, AttributeError):
            continue
        x = w.points[0][0]
        w.points = [(x, ya), (x, yb)]
        groups.setdefault(w.b.element_id, []).append((w, ya, yb))
    # svislé úseky vodičů do jednoho prvku bez křížení: vodiče shora dolů – nejvyšší nejdál, zdola nahoru – nejnižší nejdál
    for items in groups.values():
        if len(items) < 2:
            continue
        xs = sorted({w.points[0][0] for w, _, _ in items}, reverse=True)
        if len(xs) != len(items):
            continue
        down = sorted((it for it in items if it[2] <= it[1]), key=lambda it: -it[1])
        up = sorted((it for it in items if it[2] > it[1]), key=lambda it: it[1])
        for (w, ya, yb), x in zip(down + up, xs):
            w.points = [(x, ya), (x, yb)]
