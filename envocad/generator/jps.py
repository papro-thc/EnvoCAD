"""Rozmístění blokového schématu (JPS) na list a jeho rozdělení na listy střídačů (bez Qt). Návrh
`docs/design/dluhy_dxf_jps.md`, bod B; přesun 1:1 z `generate.py` (refaktoring F1, krok 3)."""
from __future__ import annotations

import re

from envocad.generator import context
from envocad.generator.context import _s
from envocad.model.project import Element, Project, Sheet, Wire, WireEnd


def jps_max_paper() -> str:
    """Největší formát jednoho listu JPS z firemního standardu (`standard.jps_max_paper`, výchozí „A2“)."""
    from envocad.settings import load_settings
    try:
        return str(load_settings()["standard"].get("jps_max_paper") or "A2")
    except (OSError, ValueError, KeyError, TypeError):
        return "A2"


JPS_AC_SUFFIX = "AC a připojení"
JPS_AC_SHEET_NAME = "Blokové schéma – " + JPS_AC_SUFFIX   # list generátoru se jmenuje „Blokové schéma“
INTERRUPT_GAP_INV = 15.0   # AC port střídače → port přerušovacího bodu na listu střídače (mm)
INTERRUPT_GAP_BLOCK = 30.0  # port bloku rozvaděče v řadě střídače → přerušovací bod (místo pro odkaz vazby vývodu)
INTERRUPT_FAN_PITCH = 10.0  # rozestup přerušení u DC vstupů střídače (vstupy jsou po 5 mm – popisky by se kryly)
INTERRUPT_GAP_AC = 60.0    # port přerušovacího bodu → port bloku AC rozvaděče (místo pro popisek AC kabelu)


def _place_jps(p: Project, s: Sheet, opts: dict, rows: list[list[Element]], ac_wires: list[Wire],
               blk: Element, after_split=None, movable: set[str] | None = None) -> None:
    """Rozmístí JPS na list (`frame.fit_placement`). Přesáhl by jeden list `jps.max_paper` (jinak standard
    `jps_max_paper`, výchozí A2) a `jps.split` není „none“, rozdělí se JPS na listy formátu `jps.paper` (výchozí
    = limit; jen při 2+ střídačích): první list „AC a připojení“ (blok AC rozvaděče, síť, HOP) jako přehled, za ním
    listy střídačů (stringy → DC rozvaděče → střídač, baterie) balené hladově, dokud se vejdou. Řez vede AC kabelem:
    pár `fve.interrupt` „AC-T1“; údaje kabelu nese jen úsek u bloku AC rozvaděče, úsek u střídače je pokračování bez
    označení a kabelu (`xref.is_blank_wire`).

    Výjimka: řada jednoho střídače (DC řetězec se nedělí), která se sama nevejde ani na `jps.paper`, dostane svůj
    list v nejmenším normalizovaném formátu, do kterého se vejde (A1, A0, jinak „vlastní“) – limit tedy platí pro
    balení řad, ne pro jednu přerostlou řadu (např. 3 střídače × 12 stringů: listy střídačů A1, AC list A2).
    `after_split` = volání po rozdělení, před rozmístěním listů (řetězec stávajících článků pod obsah listu AC)."""
    from envocad.model.frame import PAPER_SIZES, apply_placement, fit_placement, paper_exceeds
    from envocad.model.textlayout import sheet_content_boxes
    lib = context._lib()
    boxes = sheet_content_boxes(p, s, lib)
    if not boxes:
        return
    placement = fit_placement(boxes)
    limit = _s(opts.get("max_paper")) or jps_max_paper()
    if (_s(opts.get("split")) or "auto") == "none" or len(rows) < 2 or not paper_exceeds(placement[0], limit):
        apply_placement(s, placement)     # jeden střídač: DC řetězec se nedělí, oddělit jen AC část nemá smysl
        return
    paper = _s(opts.get("paper")) or limit
    sizes = [x for x in PAPER_SIZES if x[0] == paper] or [x for x in PAPER_SIZES if x[0] == "A2"]
    sheets = _split_jps(p, s, rows, ac_wires, blk, sizes)
    if after_split is not None:       # list „AC a připojení“ bez řad střídačů: řetězec znovu pod jeho obsah
        after_split()
    for sh in sheets:                 # společný DC rozvaděč zůstal na listu AC – mezera po něm v řadě se zavře
        close_gaps(p, sh, lib)
    stack_components(p, s, blk, lib, sizes, movable)
    close_gaps(p, s, lib, axis="y")   # list AC: místo po řadách střídačů (RFVE.AC{n} skupin dál od hlavního)
    for sh in [s, *sheets]:
        bx = sheet_content_boxes(p, sh, lib)
        if bx:
            pl = fit_placement(bx, sizes)
            if pl[0] == "vlastní":        # řada střídače sama přesahuje formát listu → nejmenší normalizovaný
                pl = fit_placement(bx)
            apply_placement(sh, pl)


GAP_KEEP = 30.0     # šířka svislého pruhu, na kterou se zúží prázdný pruh listu střídače (mm)


def gap_shift(boxes: list, keep: float = GAP_KEEP, axis: str = "x"):
    """Funkce x → x po zúžení prázdných svislých pruhů mezi obálkami `boxes` na `keep` (None = žádný pruh);
    `axis` „y“ = vodorovné pruhy, funkce y → y (obsah nad pruhem dolů)."""
    lo, hi = (0, 2) if axis == "x" else (1, 3)
    boxes = sorted(boxes, key=lambda b: b[lo])
    if not boxes:
        return None
    cuts: list[tuple[float, float]] = []          # (začátek pruhu, posun obsahu za ním)
    right = boxes[0][hi]
    for b in boxes[1:]:
        if b[lo] - right > keep + 2.5:
            cuts.append((right, round((b[lo] - right - keep) / 2.5) * 2.5))
        right = max(right, b[hi])
    if not cuts:
        return None
    return lambda x: x - sum(d for x0, d in cuts if x > x0)


def close_gaps(p: Project, sh: Sheet, lib, keep: float = GAP_KEEP, axis: str = "x") -> bool:
    """Zúží prázdné svislé pruhy listu (bez značek, textů i vodičů) na `keep`: obsah vpravo od pruhu se posune vlevo
    (`axis` „y“: vodorovné pruhy, obsah nad pruhem se posune dolů). Na listu střídače po rozdělení JPS zůstane místo
    po společném RFVE.DC (ten je na listu AC), na listu AC místo po řadách střídačů (RFVE.AC{n} skupin u svých
    střídačů) – list by byl zbytečně velký. True = něco se posunulo."""
    from envocad.model.textlayout import sheet_content_boxes
    shift = gap_shift(sheet_content_boxes(p, sh, lib), keep, axis)
    if shift is None:
        return False
    if axis == "x":
        for e in sh.elements:
            e.x = shift(e.x)
        for w in sh.wires:
            w.points = [(shift(x), y) for x, y in w.points]
        for t in sh.texts:
            t.x = shift(t.x)
        return True
    for e in sh.elements:
        e.y = shift(e.y)
    for w in sh.wires:
        w.points = [(x, shift(y)) for x, y in w.points]
    for t in sh.texts:
        t.y = shift(t.y)
    return True


def _components(sh: Sheet) -> list[set[str]]:
    """Souvislé skupiny prvků listu (spojené vodiči)."""
    parent = {e.id: e.id for e in sh.elements}

    def find(a: str) -> str:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for w in sh.wires:
        if w.a.element_id in parent and w.b.element_id in parent:
            parent[find(w.a.element_id)] = find(w.b.element_id)
    groups: dict[str, set[str]] = {}
    for e in sh.elements:
        groups.setdefault(find(e.id), set()).add(e.id)
    return list(groups.values())


def component_boxes(p: Project, sh: Sheet, ids: set[str], lib) -> list:
    """Obálky obsahu (značky, texty, vodiče) jen prvků `ids` listu a vodičů mezi nimi (bez volných textů listu)."""
    from envocad.model.textlayout import sheet_content_boxes
    keep_el, keep_w, keep_t = sh.elements, sh.wires, sh.texts
    sh.elements = [e for e in keep_el if e.id in ids]
    sh.wires = [w for w in keep_w if w.a.element_id in ids and w.b.element_id in ids]
    sh.texts = []
    try:
        return sheet_content_boxes(p, sh, lib)
    finally:
        sh.elements, sh.wires, sh.texts = keep_el, keep_w, keep_t


def stack_components(p: Project, sh: Sheet, blk: Element, lib, sizes=None, movable: set[str] | None = None) -> bool:
    """List „AC a připojení“ po rozdělení JPS: samostatné skupiny bez vazby vodičem na blok AC rozvaděče (společný
    RFVE.DC s přerušeními) zkusí přesunout pod nebo nad zbytek listu, pokud tím list vyjde menší (přípojka VN v řadě
    za RFVE.AC by se společným RFVE.DC vlevo přerostla formát). True = něco se přesunulo."""
    from envocad.model.frame import PAPER_SIZES, fit_placement
    from envocad.model.textlayout import sheet_content_boxes
    comps = _components(sh)
    # jen skupiny s prvkem `movable` (společný RFVE.DC) – RFVE.AC{n} skupin střídačů zůstává u svých přerušení
    others = [c for c in comps if blk.id not in c and len(c) > 1 and (movable is None or c & movable)]
    if not others:
        return False
    order = [n for n, _w, _h in PAPER_SIZES]

    def rank(boxes) -> tuple:
        name = fit_placement(boxes, sizes)[0] if boxes else "A3"
        w = max(b[2] for b in boxes) - min(b[0] for b in boxes)
        h = max(b[3] for b in boxes) - min(b[1] for b in boxes)
        return (order.index(name) if name in order else len(order), w * h)

    def boxes_of(ids: set[str] | None):
        keep_el, keep_w = sh.elements, sh.wires
        if ids is not None:
            sh.elements = [e for e in keep_el if e.id in ids]
            sh.wires = [w for w in keep_w if w.a.element_id in ids and w.b.element_id in ids]
        try:
            return sheet_content_boxes(p, sh, lib)
        finally:
            sh.elements, sh.wires = keep_el, keep_w

    def move(ids: set[str], dx: float, dy: float) -> None:
        for e in sh.elements:
            if e.id in ids:
                e.x, e.y = e.x + dx, e.y + dy
        for w in sh.wires:
            if w.a.element_id in ids and w.b.element_id in ids:
                w.points = [(x + dx, y + dy) for x, y in w.points]

    moved = False
    for comp in others:
        own = boxes_of(comp)
        rest_ids = {e.id for e in sh.elements} - comp
        rest = boxes_of(rest_ids)
        if not own or not rest:
            continue
        ox0, oy0, _ox1, oy1 = (min(b[0] for b in own), min(b[1] for b in own), max(b[2] for b in own),
                              max(b[3] for b in own))
        rx0, ry0, _rx1, ry1 = (min(b[0] for b in rest), min(b[1] for b in rest), max(b[2] for b in rest),
                               max(b[3] for b in rest))
        best, best_r = (0.0, 0.0), rank(own + rest)
        for dx, dy in ((rx0 - ox0, ry0 - 15.0 - oy1), (rx0 - ox0, ry1 + 15.0 - oy0)):     # pod, nad zbytkem
            dx, dy = round(dx / 2.5) * 2.5, round(dy / 2.5) * 2.5
            r = rank([(b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy) for b in own] + rest)
            if r < best_r:
                best, best_r = (dx, dy), r
        if best != (0.0, 0.0):
            move(comp, *best)
            moved = True
    return moved


def _split_jps(p: Project, s: Sheet, rows: list[list[Element]], ac_wires: list[Wire], blk: Element,
               sizes) -> list[Sheet]:
    """Přesune řady střídačů z `s` na nové listy (hned za `s`) a vodiče mezi řadou a zbytkem listu (AC kabel; u
    rodinného domu i DC vodiče přes rozvaděč FVE, který zůstává na listu „AC a připojení“) přeruší párem
    přerušovacích bodů; `s` zůstane listem „AC a připojení“. Vrací listy střídačů v pořadí."""
    from envocad.model.frame import fit_placement
    from envocad.model.project import INTERRUPT_SYMBOL, element_symbol
    from envocad.model.symbol import rotate_dir
    from envocad.model.textlayout import sheet_content_boxes
    lib = context._lib()
    base = s.name or "Blokové schéma"
    s.name = f"{base} – {JPS_AC_SUFFIX}"
    sym_int = lib.get_symbol(INTERRUPT_SYMBOL)
    port_dx = sym_int.port("1").x            # port přerušovacího bodu vlevo od jeho středu (rotace 0)
    ac_ids = {w.id for w in ac_wires}

    def side(e: Element, port: str) -> tuple[float, float, int]:
        """Poloha portu a směr ven (+1 vpravo, −1 vlevo) – přerušovací bod stojí ve směru vodiče od portu."""
        sym = element_symbol(p, e, lib)
        x, y = e.port_pos(sym, port)
        d = rotate_dir(sym.port(port).dir, e.rotation)
        if e.mirror and d in ("E", "W"):
            d = "W" if d == "E" else "E"
        return x, y, (-1 if d == "W" else 1)

    def interrupt(e: Element, port: str, ref: str, gap: float) -> Element:
        x, y, sgn = side(e, port)
        # rotace 0: port vlevo, šipka vpravo (bod vpravo od portu); 180: port vpravo, šipka vlevo
        i = Element(INTERRUPT_SYMBOL, x + sgn * (gap - port_dx), y, rotation=0 if sgn > 0 else 180,
                    attrs={"ref": ref})
        return i

    fans: dict[str, list] = {}       # střídač → přerušení u jeho DC vstupů (vstupy po 5 mm, body se rozestoupí)
    moves: list[tuple[set[str], list[Wire]]] = []       # (id prvků řady, vodiče řady) pro každý střídač
    for row in rows:
        t = row[0]
        row_ids = {e.id for e in row}
        new_ids: set[str] = set()
        # každý vodič mezi řadou a zbytkem listu (AC kabel k bloku AC rozvaděče; u rodinného domu i DC vodiče
        # stringů do rozvaděče FVE a z něj do střídače) se přeruší párem přerušovacích bodů; údaje kabelu zůstávají
        # u úseku mimo řadu (list „AC a připojení“), úsek u řady je prázdné pokračování
        for w in [w for w in s.wires if (w.a.element_id in row_ids) != (w.b.element_id in row_ids)]:
            inside, outside = (w.a, w.b) if w.a.element_id in row_ids else (w.b, w.a)
            e_in, e_out = s.element(inside.element_id), s.element(outside.element_id)
            ref = f"AC-{t.ref}" if w.id in ac_ids else f"{e_out.ref or 'P'}-{outside.port}"
            # u bloku rozvaděče (DC rozvaděč po trase) má úsek odkaz vazby na vývod („/5.A1“) – delší úsek
            i_in = interrupt(e_in, inside.port, ref,
                             INTERRUPT_GAP_BLOCK if e_in.symbol_id == "fve.switchboard" else INTERRUPT_GAP_INV)
            i_out = interrupt(e_out, outside.port, ref, INTERRUPT_GAP_AC)
            s.elements += [i_in, i_out]
            w_in = Wire(WireEnd(e_in.id, inside.port), WireEnd(i_in.id, "1"), conductors=list(w.conductors),
                        attrs={"ref": ""})
            s.wires.append(w_in)
            if w.id not in ac_ids and e_in.symbol_id != "fve.switchboard":
                fans.setdefault(e_in.id, []).append((i_in, w_in, e_in, inside.port))
            if inside is w.a:
                w.a = WireEnd(i_out.id, "1")
            else:
                w.b = WireEnd(i_out.id, "1")
            w.points = []                    # přerušovací bod stojí na výšce portu – vodič vede rovně
            new_ids.add(i_in.id)
        for items in fans.values():
            _fan_interrupts(items, side)
        fans.clear()
        ids = row_ids | new_ids
        moves.append((ids, [w for w in s.wires if w.a.element_id in ids and w.b.element_id in ids]))

    def move(src: Sheet, dst: Sheet, ids: set[str], wires: list[Wire]) -> None:
        dst.elements += [e for e in src.elements if e.id in ids]
        src.elements = [e for e in src.elements if e.id not in ids]
        wset = {w.id for w in wires}
        dst.wires += [w for w in src.wires if w.id in wset]
        src.wires = [w for w in src.wires if w.id not in wset]

    def new_sheet(after: Sheet) -> Sheet:
        sh = Sheet(name=base, func=s.func, loc=s.loc)
        p.sheets.insert(p.sheets.index(after) + 1, sh)
        return sh

    def fits(sh: Sheet) -> bool:
        bx = sheet_content_boxes(p, sh, lib)
        shift = gap_shift(bx)               # jako po `close_gaps` (mezera po společném RFVE.DC se zavře)
        if shift is not None:
            bx = [(shift(b[0]), b[1], shift(b[0]) + b[2] - b[0], b[3]) for b in bx]
        return not bx or fit_placement(bx, sizes)[0] != "vlastní"

    sheets: list[Sheet] = []
    groups: list[list[int]] = []
    for i, (ids, wires) in enumerate(moves):
        if not sheets:
            sheets.append(new_sheet(s))
            groups.append([])
        cur = sheets[-1]
        move(s, cur, ids, wires)
        groups[-1].append(i)
        if len(groups[-1]) > 1 and not fits(cur):     # řada se nevešla – začne nový list
            nxt = new_sheet(cur)
            move(cur, nxt, ids, wires)
            groups[-1].pop()
            sheets.append(nxt)
            groups.append([i])
    for sh, grp in zip(sheets, groups):
        sh.name = f"{base} – " + ref_ranges([rows[i][0].ref for i in grp])
    return sheets


def _fan_interrupts(items: list, side) -> None:
    """Přerušení u DC vstupů jednoho střídače (společný RFVE.DC / RFVE zůstává na listu „AC a připojení“): body po
    `INTERRUPT_FAN_PITCH` kolem středu vstupů, dál od střídače; úsek k vstupu s lomem. Vodič blíž středu má lom víc
    vlevo, krajní nejblíž střídači – úseky nahoru i dolů se nekříží."""
    if len(items) < 2:
        return
    ports = [(it, *side(it[2], it[3])) for it in items]          # (položka, x, y, směr)
    ports.sort(key=lambda t: -t[2])
    m = len(ports)
    yc = sum(t[2] for t in ports) / m
    sgn = ports[0][3]
    x_port = ports[0][1]
    ys = [round((yc + ((m - 1) / 2 - r) * INTERRUPT_FAN_PITCH) / 2.5) * 2.5 for r in range(m)]
    order = sorted(range(m), key=lambda r: abs(ys[r] - ports[r][2]))   # nejmenší odchylka → lom nejdál od střídače
    x_pt = x_port + sgn * (10.0 + 5.0 * m + INTERRUPT_GAP_INV)
    for j, r in enumerate(order):
        (i_el, w_in, _e, _port), px, py, _d = ports[r]
        i_el.x += x_pt - (px + sgn * INTERRUPT_GAP_INV)
        i_el.y += ys[r] - py
        xl = x_port + sgn * (10.0 + 5.0 * (m - 1 - j))
        w_in.points = [(xl, py), (xl, ys[r])]


def ref_ranges(refs: list[str]) -> str:
    """Označení do názvu listu: souvislé řady 3+ stejné předpony jako rozsah („T1–T9“), jinak výčet
    („T1, T2“, „T1–T3, T5“). Pořadí se zachová."""
    out: list[str] = []
    run: list[tuple[str, int, str]] = []          # (předpona, číslo, označení)

    def flush() -> None:
        if len(run) >= 3:
            out.append(f"{run[0][2]}–{run[-1][2]}")
        else:
            out.extend(r[2] for r in run)
        run.clear()

    for ref in refs:
        m = re.fullmatch(r"(.*?)(\d+)", ref)
        if m and run and run[-1][0] == m.group(1) and run[-1][1] + 1 == int(m.group(2)):
            run.append((m.group(1), int(m.group(2)), ref))
            continue
        flush()
        if m:
            run.append((m.group(1), int(m.group(2)), ref))
        else:
            out.append(ref)
    flush()
    return ", ".join(out)
