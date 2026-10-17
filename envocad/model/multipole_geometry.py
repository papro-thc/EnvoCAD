"""Geometrie vícepólového pohledu bez Qt – texty a čáry tak, jak je kreslí `ui/multipole_view.py`, pro kontrolu
překryvů textů ve vícepólu (`checks.text_findings`).

Rozmístění, stránkování, popisky prvků a trasy žil se počítají sdílenými funkcemi z `model/multipole.py`
(`auto_layout`, `paginate`, `pole_label_lines`, `conductor_route`), které používá i scéna – kontrola tedy vidí
stejný výkres. Obálky textů jsou odhad podle `textlayout.text_box` (průměrná šířka znaku).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

from envocad.model import multipole as mp
from envocad.model.designation import element_name
from envocad.model.project import Project, Sheet, element_symbol, linked_wire, switchboard_title, wire_label
from envocad.model.symbol import rotate_dir, rotate_point
from envocad.model.textlayout import (
    CHAR_W,
    GAP,
    Box,
    _IndexGrid,
    boxes_overlap,
    segment_hits_box,
    symbol_segments,
    symbol_text_boxes,
    text_box,
)

Point = tuple[float, float]
BUS = "sb.busbar"
BUS_PITCH = 5.0       # rozteč čar potenciálů sběrnice (jako `multipole_view.BUS_PITCH`)
TAG_ROW = 3.2         # řádek štítku kabelu (`CableTagItem.ROW`)
END_TEXT_OFFSET = {"E": (1.5, 0.8), "W": (-1.5, 0.8), "N": (0.8, 1.5), "S": (0.8, -3.0)}


@dataclass
class _At:
    """Prvek posunutý na místo pólu ve vícepólu (pro `symbol_segments` / `symbol_text_boxes`)."""
    x: float
    y: float
    rotation: int


@dataclass
class MultipoleGeometry:
    texts: list[tuple[Box, str, str]] = field(default_factory=list)            # obálka, vlastník, popis
    lines: list[tuple[Point, Point, str, str]] = field(default_factory=list)   # úsečka, vlastník, popis
    pages: int = 1
    # popisky žil: (id vodiče, žíla, část) → (x, y, text, zarovnání); část 0 = žíla / úsek k přerušení na straně
    # zdroje, 1 = úsek za přerušením. Scéna je kreslí přesně tady (rozmístěné mimo cizí čáry a texty).
    conductor_labels: dict[tuple[str, str, int], tuple[float, float, str, str]] = field(default_factory=dict)
    origins: dict[str, Point] = field(default_factory=dict)    # prvek → poloha (po stránkování a posunu)
    page_of: dict[str, int] = field(default_factory=dict)      # prvek → strana


TERMINAL_NUMBER = "číslo svorky"   # popis textu čísla svorky (kontrola překryvů ho bere bez tolerance)
TB_PAD = 2.5          # odstup kresby od popisového pole a QR kódu


def multipole_geometry(project: Project, sheet: Sheet, lib) -> MultipoleGeometry:
    """Texty a čáry vícepólu listu rozvaděče (souřadnice pohledu, strany pod sebou).

    Se zapnutým rámečkem se automaticky rozmístěné prvky strany, jejichž kresba by zasahovala do popisového pole
    nebo QR kódu vedle něj, posunou nahoru (o násobek mřížky, nejvýš pod nadpis rozvaděče). Výsledné polohy
    prvků jsou v `origins` – scéna (`ui/multipole_view.py`) je převezme, takže kreslí totéž."""
    poles: dict[str, mp.ElementPoles] = {}
    for e in sheet.elements:
        poles[e.id] = mp.element_poles(sheet, e, element_symbol(project, e, lib))
    layout = mp.auto_layout(sheet, poles, x0=mp.MP_X0, y_top=sheet.height - mp.MP_Y_TOP, bridges=sheet.bridges,
                            page_w=mp.page_width(sheet))
    for eid, ep in poles.items():
        ep.origin = layout.get(eid, (ep.element.x, ep.element.y))
    page_of, n_pages = mp.paginate(sheet, poles)
    g = _build(project, sheet, poles, page_of, n_pages)
    shifts = _title_block_shifts(project, sheet, g, poles, page_of)
    if shifts:
        for eid, ep in poles.items():
            dy = shifts.get(page_of.get(eid, 0), 0.0)
            if dy and not ep.element.mp_pos:
                ep.origin = (ep.origin[0], ep.origin[1] + dy)
        g = _build(project, sheet, poles, page_of, n_pages)
    g.origins = {eid: ep.origin for eid, ep in poles.items()}
    g.page_of = dict(page_of)
    return g


def _title_block_shifts(project: Project, sheet: Sheet, g: MultipoleGeometry, poles, page_of) -> dict[int, float]:
    """Posun nahoru (mm, na mřížce) pro každou stranu, na které kresba automaticky rozmístěných prvků zasahuje do
    popisového pole s QR kódem. Jen se zapnutým rámečkem; nejvýš tolik, aby kresba nezasáhla nadpis rozvaděče."""
    from envocad.model.frame import MARGIN, frame_enabled, title_block_box
    if not frame_enabled():
        return {}
    tb = title_block_box(sheet.width, sheet.height)
    tb = (tb[0] - TB_PAD, tb[1], tb[2], tb[3] + TB_PAD)
    pitch = mp.page_pitch(sheet)
    title = switchboard_title(project, sheet)
    top_limit = sheet.height - MARGIN - 4.0 - (9.0 + 4.2 * max(len(title) - 1, 0) if title else 0.0) - TB_PAD
    auto = {eid for eid, ep in poles.items() if not ep.element.mp_pos}
    low: dict[int, float] = {}      # strana → nejnižší bod kresby v oblasti popisového pole (lokální y strany)
    top: dict[int, float] = {}      # strana → nejvyšší bod kresby automatických prvků
    for box, owner, _w in g.texts:
        eid = owner.split("#")[0]
        if eid not in auto:
            continue
        k = page_of.get(eid, 0)
        x0, y0, x1, y1 = box[0], box[1] + k * pitch, box[2], box[3] + k * pitch
        top[k] = max(top.get(k, y1), y1)
        if x1 > tb[0] and x0 < tb[2] and y0 < tb[3]:
            low[k] = min(low.get(k, y0), y0)
    for a, b, owner, _w in g.lines:
        eid = owner.split("#")[0]
        if eid not in auto:
            continue
        k = page_of.get(eid, 0)
        ys = (a[1] + k * pitch, b[1] + k * pitch)
        top[k] = max(top.get(k, max(ys)), max(ys))
        if max(a[0], b[0]) > tb[0] and min(a[0], b[0]) < tb[2] and min(ys) < tb[3]:
            low[k] = min(low.get(k, min(ys)), min(ys))
    out: dict[int, float] = {}
    for k, y in low.items():
        need = tb[3] - y
        room = top_limit - top.get(k, top_limit)
        dy = min(need, max(room, 0.0))
        dy = -(-dy // mp.GRID) * mp.GRID if dy == need else (dy // mp.GRID) * mp.GRID
        if dy > 0:
            out[k] = dy
    return out


def _build(project: Project, sheet: Sheet, poles: dict[str, mp.ElementPoles], page_of: dict[str, int],
           n_pages: int) -> MultipoleGeometry:
    from envocad.model.frame import MARGIN, MARGIN_LEFT
    g = MultipoleGeometry()
    g.pages = n_pages
    pitch = mp.page_pitch(sheet)

    def text(x: float, y: float, s: str, h: float, align: str, owner: str, what: str) -> None:
        if s:
            g.texts.append((text_box(x, y, s, h, align), owner, what))

    def line(a: Point, b: Point, owner: str, what: str) -> None:
        if a != b:
            g.lines.append((a, b, owner, what))

    # prvky (póly, popisky, vazby, obtoky, příčky PE svodiče)
    for e in sheet.elements:
        ep = poles[e.id]
        if e.symbol_id == BUS:
            continue
        name = element_name(e)
        conds = list(ep.switched) if ep.per_pole else [None]
        for i, c in enumerate(conds):
            sym = mp.pole_symbol_for(ep, c)
            at = _At(*mp.pole_anchor(ep, c), e.rotation)
            for a, b in symbol_segments(at, sym):
                line(a, b, e.id, f"značku {name}")
            for b in symbol_text_boxes(at, sym):
                g.texts.append((b, e.id, f"text značky {name}"))
            if i == 0 and c is not None and ep.symbol.common_symbol() is not None:
                for a, b in symbol_segments(at, ep.symbol.common_symbol()):
                    line(a, b, e.id, f"značku {name}")
            if c is not None and mp.is_terminal_block(e):
                num = mp.terminal_numbers(e, len(ep.slots))[ep.slot(c)] or "?"
                _x0, y0, x1, _y1 = sym.bounds()
                rx, ry = rotate_point(x1 + 1.0, y0 + 1.0, e.rotation)
                text(at.x + rx, at.y + ry, num, 2.0, "left", e.id, f"{TERMINAL_NUMBER} {name}")
        for x, y, s, h, align in mp.pole_label_lines(ep):
            text(x, y, s, h, align, e.id, f"popisek {name}")
        if ep.per_pole:
            if ep.symbol.pole_link and len(ep.switched) > 1:
                lx, ly = rotate_point(*ep.symbol.link_at, e.rotation)
                pts = [(ep.origin[0] + ep.pole_offset(c)[0] + lx, ep.origin[1] + ep.pole_offset(c)[1] + ly)
                       for c in ep.switched]
                line(pts[0], pts[-1], e.id, f"vazbu pólů {name}")
            for c in ep.bypass:
                a, b = ep.through
                line(ep.pole_pos(a, c), ep.pole_pos(b, c), e.id, f"žílu {c} kolem {name}")
            for a, b in mp.pe_join_segments(ep):
                line(a, b, e.id, f"spojení PE {name}")
        else:
            for port, cs in ep.per_port.items():
                if len(cs) >= 2:
                    last = max(cs, key=ep.slot)
                    line(ep.pole_pos(port, ep.slots[0]), ep.pole_pos(port, last), e.id, f"vývod {name}")

    # žíly
    breaks: dict[tuple[int, bool], int] = {}
    break_ys: dict[tuple[int, bool], set[float]] = {}
    bus_taps: dict[tuple[str, int], list[Point]] = {}

    pending: list[tuple[tuple[str, str, int], str, list[Point], str, bool]] = []

    def conductor(w, c: str, idx: int, pa: Point, da: str, pb: Point, db: str, ends: tuple[str, str],
                  staggered: bool = False, part: int = 0) -> None:
        pts = mp.conductor_route(pa, da, pb, db, stagger=idx * mp.GRID, jog=0.8)
        what = f"žílu {c}" + (f" vodiče {w.attrs['ref']}" if w.attrs.get("ref") else "")
        owner = f"{w.id}#{c}"   # každá žíla zvlášť – popisek DC− přes žílu DC+ téhož vodiče je překryv
        for a, b in pairwise(pts):
            line(a, b, owner, what)
        label = c
        if idx == 0:
            lbl = wire_label(w.attrs)
            label = f"{lbl}  {c}" if lbl else c
        pending.append(((w.id, c, part), owner, pts, label, staggered))   # rozmístí se, až budou známé všechny čáry
        for t, (px, py), d in ((ends[0], pts[0], da), (ends[1], pts[-1], db)):
            if t:
                dx, dy = END_TEXT_OFFSET[d]
                text(px + dx, py + dy, t, 1.8, "right" if d == "W" else "left", owner, f"svorku {t}")

    def bus_y(ep: mp.ElementPoles, c: str, page: int) -> float:
        k0 = page_of.get(ep.element.id, 0)
        return ep.origin[1] + k0 * pitch - ep.slot(c) * BUS_PITCH - page * pitch

    for w in sheet.wires:
        ea, eb = poles.get(w.a.element_id), poles.get(w.b.element_id)
        if not ea or not eb:
            continue
        try:
            da = rotate_dir(ea.symbol.port(w.a.port).dir, ea.element.rotation)
            db = rotate_dir(eb.symbol.port(w.b.port).dir, eb.element.rotation)
        except (KeyError, StopIteration):
            continue
        ka, kb = page_of.get(w.a.element_id, 0), page_of.get(w.b.element_id, 0)
        if ea.element.symbol_id == BUS or eb.element.symbol_id == BUS:
            if ea.element.symbol_id == BUS and eb.element.symbol_id == BUS:
                continue
            dev, ddir, kd, bus, dport = (eb, db, kb, ea, w.b.port) if ea.element.symbol_id == BUS else \
                (ea, da, ka, eb, w.a.port)
            side = "b" if dev is eb else "a"
            for c in mp.wire_conductors(w):
                if c not in bus.slots:
                    continue
                px, py = dev.pole_pos(dport, c)
                y = bus_y(bus, c, kd)
                t = "" if mp.is_terminal_block(dev.element) else mp.terminal_text(w, c, side)
                conductor(w, c, 0, (px, py), ddir, (px, y), "S" if y > py else "N", (t, ""))
                bus_taps.setdefault((bus.element.id, kd), []).append((px, y))
            continue
        for i, c in enumerate(mp.wire_conductors(w)):
            pa, pb = ea.pole_pos(w.a.port, c), eb.pole_pos(w.b.port, c)
            ta = "" if mp.is_terminal_block(ea.element) else mp.terminal_text(w, c, "a")
            tb = "" if mp.is_terminal_block(eb.element) else mp.terminal_text(w, c, "b")
            if ka == kb:
                conductor(w, c, i, pa, da, pb, db, (ta, tb), len(mp.wire_conductors(w)) > 1)
                continue
            right = ka < kb
            xa = (sheet.width - MARGIN - 6.0) if right else (MARGIN_LEFT + 6.0)
            xb = (MARGIN_LEFT + 6.0) if right else (sheet.width - MARGIN - 6.0)
            na = breaks.setdefault((ka, right), 0)
            nb = breaks.setdefault((kb, not right), 0)
            breaks[(ka, right)] = na + 1
            breaks[(kb, not right)] = nb + 1
            ya = mp.break_y(pa, da, na, break_ys.setdefault((ka, right), set()))
            yb = mp.break_y(pb, db, nb, break_ys.setdefault((kb, not right), set()))
            conductor(w, c, i, pa, da, (xa, ya), "W" if right else "E", (ta, ""))
            conductor(w, c, i, (xb, yb), "E" if right else "W", pb, db, ("", tb), part=1)
            text(xa + (1.5 if right else -1.5), ya + 1.0, "/0.0.A1", 1.8, "left" if right else "right", w.id,
                 "odkaz přerušení")
            text(xb + (1.5 if not right else -1.5), yb + 1.0, "/0.0.A1", 1.8, "left" if not right else "right", w.id,
                 "odkaz přerušení")

    # sběrnice potenciálů
    x0, x1 = MARGIN_LEFT + 12.0, sheet.width - MARGIN - 14.0
    for e in sheet.elements:
        if e.symbol_id != BUS:
            continue
        ep = poles[e.id]
        conds = list(ep.slots) or mp.parse_conductors(e.attrs.get("conductors", "")) or ["L1"]
        pages = sorted({page_of.get(e.id, 0)} | {k for (bid, k) in bus_taps if bid == e.id})
        for k in pages:
            ys = {c: (bus_y(ep, c, k) if c in ep.slots else ep.origin[1] - i * BUS_PITCH) for i, c in enumerate(conds)}
            for c, y in ys.items():
                line((x0, y), (x1, y), e.id, f"sběrnici {e.ref}{c}")
                text(x0 - 1.5, y - 0.8, f"{e.ref}{c}", 2.0, "right", e.id, f"název potenciálu {e.ref}{c}")
                text(x1 + 1.5, y - 0.8, f"{e.ref}{c}", 2.0, "left", e.id, f"název potenciálu {e.ref}{c}")
            if k == pages[0] and e.attrs.get("desc"):
                text(x1, max(ys.values()) + 4.5, e.attrs["desc"], 2.0, "right", e.id, "popis sběrnice")

    # štítky kabelů u přívodů a vývodů
    for e in sheet.elements:
        if e.symbol_id not in ("sb.feed_in", "sb.feed_out"):
            continue
        ep = poles.get(e.id)
        if ep is None or not ep.switched:
            continue
        xs = [ep.origin[0] + ep.pole_offset(c)[0] for c in ep.switched]
        hit = linked_wire(project, sheet, e)
        w = hit[1] if hit else None
        cable = wire_label({k: v for k, v in w.attrs.items() if k != "ref"}, w.conductors) if w is not None \
            else e.attrs.get("cable", "")
        rows = [r for r in [(w.attrs.get("ref") if w else "") or e.ref, e.attrs.get("desc", ""), cable] if r] or ["?"]
        width = max(max(xs) - min(xs) + 4.0, max(len(r) for r in rows) * 1.25 + 3.0)
        cx = (min(xs) + max(xs)) / 2
        tx0, tx1 = cx - width / 2, cx + width / 2
        up = e.symbol_id == "sb.feed_in"
        h = TAG_ROW * len(rows)
        y_edge = ep.origin[1] + (3.0 if up else -3.0)
        top = y_edge + h if up else y_edge
        for a, b in pairwise([(tx0, top), (tx1, top), (tx1, top - h), (tx0, top - h), (tx0, top)]):
            line(a, b, e.id, f"štítek kabelu {rows[0]}")
        for i, r in enumerate(rows):
            # text štítku je uvnitř rámečku (zmenšený odhad šířky – písmo 1,7–2 mm je užší než průměr)
            y = top - (i + 1) * TAG_ROW
            hh = 2.0 if i == 0 else 1.7
            b = text_box(cx, y + 0.8, r, hh, "center")
            g.texts.append(((max(b[0], tx0 + 0.3), b[1], min(b[2], tx1 - 0.3), min(b[3], top - i * TAG_ROW)), e.id,
                            f"štítek kabelu {rows[0]}"))

    # popisky žil: výchozí poloha, a když vede přes cizí čáru nebo text, první volná z kandidátů
    _place_conductor_labels(g, pending)

    # nadpis rozvaděče
    title = switchboard_title(project, sheet)
    for k in range(g.pages if title else 0):
        ls = list(title)
        if g.pages > 1:
            ls[0] = f"{ls[0]}  ({k + 1}/{g.pages})"
        tx, ty = MARGIN_LEFT + 5.0, sheet.height - MARGIN - 4.0 - k * pitch
        y = 0.0
        for i, s in enumerate(ls):
            h = 5.0 if i == 0 else 3.0
            y -= h
            text(tx, ty + y, s, h, "left", "#title", "nadpis rozvaděče")
            if i == 0:
                y -= 2.8
            y -= 1.2
    return g


def _label_candidates(pts: list[Point], staggered: bool, label: str) -> list[tuple[float, float, str]]:
    """Kandidáti polohy popisku žíly: výchozí (`conductor_label_anchor`), pak na každém úseku (nejdelší první)
    nad vodorovným vlevo/uprostřed/vpravo a vpravo/vlevo od svislého ve třetinách."""
    x, y, align, _v = mp.conductor_label_anchor(pts, staggered)
    out = [(x, y, align)]
    width = len(label) * 1.8 * CHAR_W
    segs = [(a, b) for i, (a, b) in enumerate(pairwise(pts))
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1e-6 and not (staggered and len(pts) == 6 and i == 2)]
    segs.sort(key=lambda s: -(abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1])))
    for a, b in segs:
        if abs(a[1] - b[1]) < 1e-6:
            x1, x2 = sorted((a[0], b[0]))
            if x2 - x1 >= width + 2 * GAP:
                yy = a[1] + GAP
                out += [((x1 + x2) / 2, yy, "center"), (x1 + GAP, yy, "left"), (x2 - GAP, yy, "right"),
                        ((x1 + x2) / 2, a[1] - GAP - 1.8, "center")]
        else:
            y1, y2 = sorted((a[1], b[1]))
            if y2 - y1 >= 6.0:
                for f in (0.5, 0.25, 0.75, 0.1, 0.9):
                    yy = y1 + (y2 - y1) * f - 1.0
                    out += [(a[0] + GAP, yy, "left"), (a[0] - GAP, yy, "right")]
    return out


def _place_conductor_labels(g: MultipoleGeometry, pending) -> None:
    lgrid = _IndexGrid()
    for k, (a, b, _o, _w) in enumerate(g.lines):
        lgrid.add((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])), k)
    tgrid = _IndexGrid()
    for i, (b, _o, _w) in enumerate(g.texts):
        tgrid.add(b, i)

    def score(box: Box, owner: str) -> float:
        s = 0.0
        for k in lgrid.near(box):
            a, b, lo, _w = g.lines[k]
            if lo != owner and segment_hits_box(a, b, box):
                s += 3.0
        for i in tgrid.near(box):
            ob, oo, _w = g.texts[i]
            if oo != owner and boxes_overlap(box, ob):
                s += 10.0
        return s

    placed: list[tuple[str, Point, Point, Point]] = []   # (text, úsek trasy, bod popisku) – už rozmístěné popisky

    def nearest_seg(pts: list[Point], x: float, y: float) -> tuple[Point, Point] | None:
        best_d, best_seg = None, None
        for a, b in pairwise(pts):
            if a == b:
                continue
            cx = min(max(x, min(a[0], b[0])), max(a[0], b[0]))
            cy = min(max(y, min(a[1], b[1])), max(a[1], b[1]))
            d = (cx - x) ** 2 + (cy - y) ** 2
            if best_d is None or d < best_d:
                best_d, best_seg = d, (a, b)
        return best_seg

    def duplicate(pts: list[Point], label: str) -> bool:
        """Stejný popisek už leží u úseku, který tato žíla sdílí (žíly několika vodičů vedené po stejné čáře
        do jedné svorky – např. PE ze svodičů do XPE): druhý popisek by se jen opakoval."""
        for text, a, b, (lx, ly) in placed:
            if text != label:
                continue
            for c, d in pairwise(pts):
                if abs(a[0] - b[0]) < 1e-6 and abs(c[0] - d[0]) < 1e-6 and abs(a[0] - c[0]) < 1e-6:
                    lo, hi = max(min(a[1], b[1]), min(c[1], d[1])), min(max(a[1], b[1]), max(c[1], d[1]))
                    if hi - lo > 1.0 and lo - 2.0 <= ly <= hi + 2.0:
                        return True
                elif abs(a[1] - b[1]) < 1e-6 and abs(c[1] - d[1]) < 1e-6 and abs(a[1] - c[1]) < 1e-6:
                    lo, hi = max(min(a[0], b[0]), min(c[0], d[0])), min(max(a[0], b[0]), max(c[0], d[0]))
                    if hi - lo > 1.0 and lo - 2.0 <= lx <= hi + 2.0:
                        return True
        return False

    for key, owner, pts, label, staggered in pending:
        if duplicate(pts, label):
            x, y, _a, _v = mp.conductor_label_anchor(pts, staggered)
            g.conductor_labels[key] = (x, y, "", "left")    # prázdný = scéna popisek nekreslí
            continue
        best, best_s = None, None
        for i, (x, y, align) in enumerate(_label_candidates(pts, staggered, label)):
            box = text_box(x, y, label, 1.8, align)
            sc = score(box, owner) + 0.01 * i
            if best_s is None or sc < best_s:
                best, best_s = (x, y, align, box), sc
            if sc < 0.5:
                break
        x, y, align, box = best
        g.conductor_labels[key] = (x, y, label, align)
        seg = nearest_seg(pts, x, y)
        if seg is not None:
            placed.append((label, seg[0], seg[1], (x, y)))
        tgrid.add(box, len(g.texts))
        g.texts.append((box, owner, f"popisek žíly {key[1]}"))


def multipole_text_overlaps(project: Project, sheet: Sheet, lib,
                            geometry: MultipoleGeometry | None = None) -> list[tuple[str, str, str]]:
    """Překryvy ve vícepólu: text přes cizí text, text přes cizí čáru (žílu, značku, sběrnici, štítek).
    [(vlastník textu, vlastník druhého, popis)] – vlastník = id prvku nebo vodiče (žíla „id#L1“ se hlásí jako vodič);
    každá dvojice jen jednou."""
    g = geometry or multipole_geometry(project, sheet, lib)
    found: dict[tuple, tuple[str, str, str]] = {}
    tgrid = _IndexGrid()
    for i, (b, _o, _w) in enumerate(g.texts):
        tgrid.add(b, i)
    for i, (a, oa, wa) in enumerate(g.texts):
        for j in tgrid.near(a, after=i):
            b, ob, wb = g.texts[j]
            if oa == ob or not boxes_overlap(a, b):
                continue
            key = frozenset((oa, ob))
            if key not in found:
                found[key] = (oa, ob, f"{wa} přes {wb}")
    lgrid = _IndexGrid()
    for k, (a, b, _o, _w) in enumerate(g.lines):
        lgrid.add((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])), k)
    for box, owner, what in g.texts:
        # čísla svorek (písmo 2 mm těsně pod svorkou): bez tolerance – čára po okraji obálky už číslo přeškrtne
        tol = 0.0 if what.startswith(TERMINAL_NUMBER) else 0.2
        for k in lgrid.near(box):
            a, b, lo, lwhat = g.lines[k]
            if lo == owner:
                continue
            key = (owner, lo, "line")
            if key in found or not segment_hits_box(a, b, box, tol):
                continue
            found[key] = (owner, lo, f"{what} přes {lwhat}")
    out: dict[tuple, tuple[str, str, str]] = {}
    for a, b, what in found.values():
        a, b = a.split("#")[0], b.split("#")[0]
        out.setdefault((a, b, what), (a, b, what))
    return list(out.values())
