"""Jednopólové schéma odvozené z blokového schématu a listů rozvaděčů – bez Qt.

Nic se nekreslí znovu: strom vede od distribuční soustavy (první `fve.grid` blokového schématu) po vodičích
blokového schématu a přes bloky ROZVADĚČ do jejich listů (port bloku = přívod/vývod listu se stejným označením).
Každý přístroj se kreslí jednou značkou svislé „jednočárové“ podoby, rozvaděč je čárkovaný rámeček s označením,
přípojnice vodorovná čára. Vodiče jen s PE, PE lišty a uzemnění se vynechají; elektroměr (vodiče k MTP/MTN) visí
čárkovaně vpravo vedle měřicího transformátoru. Strom končí u střídačů (DC část má vlastní listy rozvaděčů a blokové
schéma), s `dc=True` pokračuje až ke stringům.

Výstup `single_line_geometry` je kreslicí seznam (`multipole_geometry.Prim`, souřadnice strany v mm, Y nahoru) a
formát strany – stejný zdroj pro scénu (náhled, PDF dokumentace) i DXF.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from envocad.model import multipole as mp
from envocad.model.multipole_geometry import Prim
from envocad.model.project import Element, Project, Sheet, Wire, element_symbol, wire_label
from envocad.model.symbol import Symbol, place_point, rotate_dir
from envocad.model.textlayout import CHAR_W

Key = tuple[str, str]   # (id listu, id prvku)
Point = tuple[float, float]

TITLE = "Jednopólové schéma"
PASS_SYMBOLS = {"sb.feed_in", "sb.feed_out", "sb.terminal_block", "fve.terminal", "sb.junction", "fve.interrupt"}
SKIP_SYMBOLS = {"sb.pe_bar", "fve.earth"}
BUS_SYMBOLS = {"sb.busbar"}
METER_SYMBOLS = {"fve.meter"}
BRANCH_SYMBOLS = {"fve.earthing_switch", "fve.spd", "fve.vt"}   # odbočka vedle vedení, nikdy jeho pokračování
LEAF_PREFIXES = ("fve.inverter",)      # bez `dc` strom končí u střídače
# značky, které se neotáčí (text by byl svisle, vodič vede do portu i z boku): DS, spotřeba, elektroměr, střídač…
NO_ROTATE_PREFIXES = ("fve.grid", "fve.load", "fve.meter", "fve.inverter", "fve.switchboard", "fve.pv_string",
                      "fve.battery")

GAP = 4.0           # mezera mezi značkami ve sloupci (mm)
BUS_GAP = 7.5       # přípojnice → začátek vývodů
CABLE_GAP = 10.0    # mezi částmi (rozvaděče, transformátor, střídače) – popisek kabelu v mezeře (+ rámečky)
FRAME_PAD = 4.0     # odstup rámečku rozvaděče od kresby
TITLE_H = 9.0       # řádek označení rozvaděče nahoře v rámečku
METER_GAP = 4.0     # elektroměr za popiskem měřicího transformátoru
COL_GAP = 5.0       # mezi sloupci (za popiskem)
REF_H, LABEL_H, LINE_H = 2.5, 2.0, 3.0
MAX_LABEL_LINES = 6
PAGE_PAD = 5.0      # od vnitřního rámečku strany
PAPERS = (("A3", 420.0, 297.0), ("A2", 594.0, 420.0), ("A1", 841.0, 594.0), ("A0", 1189.0, 841.0))


@dataclass(eq=False)
class Node:
    key: Key
    sheet: Sheet
    element: Element
    symbol: Symbol
    entry: str | None = None             # port od nadřazeného prvku
    exit: str | None = None              # port nadřazeného prvku, ze kterého vede vodič sem
    wire: Wire | None = None             # vodič od nadřazeného prvku
    children: list[Node] = field(default_factory=list)
    meters: list[Node] = field(default_factory=list)   # elektroměry vpravo (čárkovaně)
    kind: str = "symbol"                 # symbol | pass | bus
    main: Node | None = None             # pokračování sloupce (ostatní potomci odbočují vlevo)
    # rozmístění
    rot: int = 0
    col: int = 0
    x: float = 0.0
    y: float = 0.0                       # bod vstupu (nahoře)
    origin: Point = (0.0, 0.0)
    left: float = 0.0                    # značka vlevo od osy sloupce
    right: float = 0.0                   # značka + popisek vpravo od osy
    bottom: float = 0.0                  # spodek značky (absolutně)
    down: float = 0.0                    # spodek značky i popisku (absolutně)
    labels: list[str] = field(default_factory=list)

    @property
    def segment(self) -> str:
        """Část schématu: list rozvaděče, jinak samostatný prvek blokového schématu (transformátor, střídač, DS)."""
        return self.sheet.id if self.sheet.is_switchboard else "el:" + self.element.id

    @property
    def side(self) -> list[Node]:
        return [c for c in self.children if c is not self.main] if self.kind != "bus" else []


@dataclass
class SingleLineGeometry:
    prims: list[Prim] = field(default_factory=list)
    page_size: tuple[float, float] = (420.0, 297.0)
    paper: str = "A3"
    nodes: dict[Key, Node] = field(default_factory=dict)
    frames: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)   # list rozvaděče → x0,y0,x1,y1
    root: Node | None = None


def page_label(project: Project) -> str:
    """„Číslo listu“ jednopólového schématu (popisové pole, obsah dokumentace): číslo blokového schématu + „JPS“."""
    from envocad.model.frame import sheet_number
    block = next((s for s in project.sheets if not s.is_switchboard), None)
    return f"{sheet_number(project, block)} JPS" if block is not None else "JPS"


# ---- graf ------------------------------------------------------------------------------------------------------
@dataclass
class _Edge:
    port: str
    other: Key
    other_port: str
    wire: Wire
    sheet: Sheet


def _graph(project: Project):
    """Sousedství prvků přes vodiče všech listů; vodič na port bloku ROZVADĚČ vede na přívod/vývod jeho listu se
    stejným označením. Skupiny řadových svorek jedné svorkovnice propojené můstky = jeden uzel (rozvod svorkami).
    Vrací (sousedství, prvky, uzly-přípojnice, vodiče elektroměrů)."""
    els: dict[Key, tuple[Sheet, Element]] = {}
    for s in project.sheets:
        for e in s.elements:
            els[(s.id, e.id)] = (s, e)
    feeds: dict[str, dict[str, Element]] = {}
    rep: dict[Key, Key] = {}
    buses: set[Key] = set()
    for s in project.switchboards():
        feeds[s.id] = {e.ref: e for e in s.elements if e.symbol_id in ("sb.feed_in", "sb.feed_out") and e.ref}
        for strip, groups in s.bridges.items():
            if not groups:
                continue
            members = [e for e in s.elements if e.symbol_id == "sb.terminal_block" and e.ref == strip]
            if len(members) > 1:
                head = (s.id, members[0].id)
                buses.add(head)
                for e in members:
                    rep[(s.id, e.id)] = head

    def resolve(s: Sheet, end) -> tuple[Key, str] | None:
        e = s.element(end.element_id)
        if e is None or e.symbol_id in SKIP_SYMBOLS:
            return None
        if e.symbol_id == "fve.switchboard":
            sb = project.switchboard_sheet(e.id)
            f = feeds.get(sb.id, {}).get(end.port) if sb is not None else None
            if f is not None:
                return (sb.id, f.id), "1"
        key = (s.id, e.id)
        return rep.get(key, key), end.port

    adj: dict[Key, list[_Edge]] = {}
    meas: list[tuple[Key, Key, str, Wire]] = []
    for s in project.sheets:
        for w in s.wires:
            if set(mp.wire_conductors(w)) <= {"PE"}:
                continue
            a, b = resolve(s, w.a), resolve(s, w.b)
            if a is None or b is None or a[0] == b[0]:
                continue
            ea, eb = els[a[0]][1], els[b[0]][1]
            if ea.symbol_id in METER_SYMBOLS or eb.symbol_id in METER_SYMBOLS:
                m, o = (a, b) if ea.symbol_id in METER_SYMBOLS else (b, a)
                meas.append((m[0], o[0], o[1], w))
                continue
            adj.setdefault(a[0], []).append(_Edge(a[1], b[0], b[1], w, s))
            adj.setdefault(b[0], []).append(_Edge(b[1], a[0], a[1], w, s))
    return adj, els, buses, meas


def _root(project: Project, adj, els) -> Key | None:
    for s in project.sheets:
        if s.is_switchboard:
            continue
        for e in s.elements:
            if e.symbol_id == "fve.grid" and (s.id, e.id) in adj:
                return (s.id, e.id)
    return next(iter(adj), None)


def _leaf_count(n: Node) -> int:
    return sum(_leaf_count(c) for c in n.children) if n.children else 1


def _depth(n: Node) -> int:
    return 1 + max((_depth(c) for c in n.children), default=0)


def build_tree(project: Project, lib, dc: bool = False) -> tuple[Node | None, dict[Key, Node]]:
    """Strom jednopólového schématu od DS (bez rozmístění)."""
    adj, els, buses, meas = _graph(project)
    root_key = _root(project, adj, els)
    if root_key is None:
        return None, {}
    nodes: dict[Key, Node] = {}
    sym_cache: dict[Key, Symbol] = {}

    def symbol(key: Key) -> Symbol:
        if key not in sym_cache:
            sym_cache[key] = element_symbol(project, els[key][1], lib)
        return sym_cache[key]

    def port_x(key: Key, port: str) -> float:
        _s, e = els[key]
        try:
            return e.port_pos(symbol(key), port)[0]
        except (KeyError, StopIteration, ValueError):
            return e.x

    def make(key: Key, entry, exit_port, wire) -> Node:
        s, e = els[key]
        n = Node(key, s, e, symbol(key), entry, exit_port, wire)
        n.kind = "bus" if (e.symbol_id in BUS_SYMBOLS or key in buses) else (
            "pass" if e.symbol_id in PASS_SYMBOLS else "symbol")
        nodes[key] = n
        return n

    root = make(root_key, None, None, None)
    stack = [root]
    while stack:
        n = stack.pop()
        if n is not root and not dc and n.element.symbol_id.startswith(LEAF_PREFIXES):
            continue
        if not dc and n.element.symbol_id == "fve.pv_string":
            continue
        edges = [ed for ed in adj.get(n.key, []) if ed.other not in nodes]
        edges.sort(key=lambda ed: port_x(ed.other, ed.other_port))
        for ed in edges:
            if ed.other in nodes:        # dva vodiče na tentýž prvek
                continue
            c = make(ed.other, ed.other_port, ed.port, ed.wire)
            n.children.append(c)
        stack.extend(reversed(n.children))
    for n in nodes.values():
        if n.kind != "bus" and n.children:
            n.main = max(n.children, key=lambda c: (c.element.symbol_id not in BRANCH_SYMBOLS, _leaf_count(c), _depth(c)))
    # elektroměry: vpravo u prvního měřicího transformátoru (v pořadí stromu), čárkované vodiče ke všem
    order = {k: i for i, k in enumerate(nodes)}
    by_meter: dict[Key, list[tuple[Key, str, Wire]]] = {}
    for m, o, port, w in meas:
        if o in nodes:
            by_meter.setdefault(m, []).append((o, port, w))
    for m, links in by_meter.items():
        links.sort(key=lambda t: order[t[0]])
        host = nodes[links[0][0]]
        s, e = els[m]
        mn = Node(m, s, e, symbol(m), "1", links[0][1], links[0][2], kind="symbol")
        mn.links = links          # type: ignore[attr-defined]
        nodes[m] = mn
        host.meters.append(mn)
    return root, nodes


# ---- rozmístění --------------------------------------------------------------------------------------------------
def _has_text(sym: Symbol) -> bool:
    return any(p.get("type") == "text" for p in sym.primitives)


def _orient(n: Node) -> int:
    """Otočení značky: vstup nahoru (N), výstupy dolů (S). DS, spotřeba, elektroměr a střídač se neotáčí."""
    sym = n.symbol
    if n.kind != "symbol" or n.element.symbol_id.startswith(NO_ROTATE_PREFIXES):
        return 0
    ports = {p.name: p for p in sym.ports}
    exits = {c.exit for c in n.children if c.exit in ports}

    def score(r: int) -> tuple[int, int]:
        s = 0
        if n.entry in ports:
            d = rotate_dir(ports[n.entry].dir, r)
            s += 4 if d == "N" else (-4 if d == "S" else 0)
        for name in exits:
            d = rotate_dir(ports[name].dir, r)
            s += 2 if d == "S" else (-2 if d == "N" else 0)
        return (s, -r)
    return max((0, 90, 180, 270), key=score)


def _sym_box(sym: Symbol, rot: int) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = sym.bounds()
    # `bounds` bere u textu jen bod základny – výška písma nad ní (nápis „DS“ nad značkou sítě)
    y1 = max([y1] + [p["y"] + p.get("height", 2.5) for p in sym.primitives if p.get("type") == "text"])
    pts = [place_point(x, y, rot) for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


def _port_rel(sym: Symbol, name: str | None, rot: int) -> Point | None:
    p = next((q for q in sym.ports if q.name == name), None) if name else None
    return place_point(p.x, p.y, rot) if p is not None else None


def _plural_strings(n: int) -> str:
    return f"{n} string" if n == 1 else (f"{n} stringy" if 2 <= n <= 4 else f"{n} stringů")


def _labels(project: Project, n: Node, adj_count: dict[str, int]) -> list[str]:
    e = n.element
    if n.kind == "pass":
        return [e.ref] if e.ref else []
    if n.kind == "bus":
        return []
    lines = [e.ref] if e.ref else []
    try:
        lines += n.symbol.label_lines(e.attrs)
    except (KeyError, ValueError, IndexError):
        pass
    if e.symbol_id.startswith(LEAF_PREFIXES) and adj_count.get(e.id):
        lines.append("DC: " + _plural_strings(adj_count[e.id]))
    return [x for x in lines if x][:MAX_LABEL_LINES]


def _string_counts(project: Project) -> dict[str, int]:
    """Počet stringů na střídač (blokové schéma: string → … → vstup DC střídače) – popisek střídače bez DC části."""
    out: dict[str, int] = {}
    for s in project.sheets:
        if s.is_switchboard:
            continue
        inv = {e.id for e in s.elements if e.symbol_id.startswith(LEAF_PREFIXES)}
        for w in s.wires:
            for end in (w.a, w.b):
                if end.element_id in inv and end.port.startswith("DC"):
                    out[end.element_id] = out.get(end.element_id, 0) + 1
    return out


def _measure(n: Node) -> None:
    """Otočení a rozměry uzlu vůči bodu vstupu (0, 0): značka vlevo/vpravo, výška."""
    if n.kind != "symbol":
        n.left = 0.0
        n.right = (len(n.labels[0]) * LABEL_H * CHAR_W + 2.0) if n.labels else 0.0
        return
    n.rot = _orient(n)
    bx0, by0, bx1, by1 = _sym_box(n.symbol, n.rot)
    anchor = _port_rel(n.symbol, n.entry, n.rot)
    if anchor is None:   # kořen (DS): osa = port ke kořenovému potomku, vstup = horní hrana značky
        first = n.main or (n.children[0] if n.children else None)
        p = _port_rel(n.symbol, first.exit if first else None, n.rot)
        anchor = (p[0] if p else (bx0 + bx1) / 2, by1)
    ax, _ay = anchor
    text_w = max((len(t) * (REF_H if i == 0 else LABEL_H) * CHAR_W for i, t in enumerate(n.labels)), default=0.0)
    n.left = max(0.0, ax - bx0)
    n.right = max(0.0, bx1 - ax)
    if n.labels and n.meters:      # vpravo vede čárkovaný vodič k elektroměru – popisek vlevo
        n.left += 1.5 + text_w
    elif n.labels:
        n.right += 1.5 + text_w
    n._anchor = anchor            # type: ignore[attr-defined]
    n._box = (bx0, by0, bx1, by1)  # type: ignore[attr-defined]


def _assign_columns(root: Node) -> int:
    col = 0

    def walk(n: Node) -> None:
        nonlocal col
        if n.kind == "bus":
            for c in n.children:
                walk(c)
            n.col = n.children[0].col if n.children else _new()
        else:
            for c in n.side:
                walk(c)
            if n.main is not None:
                walk(n.main)
                n.col = n.main.col
            else:
                n.col = _new()

    def _new() -> int:
        nonlocal col
        col += 1
        return col - 1

    walk(root)
    return col


def cable_gap(parent: Node, child: Node) -> float:
    """Mezera mezi spodkem nadřazené části a vstupem podřízené: popisek kabelu + rámečky rozvaděčů."""
    return CABLE_GAP + (FRAME_PAD if parent.sheet.is_switchboard else 0.0) + (
        FRAME_PAD + TITLE_H if child.sheet.is_switchboard else 0.0)


def _place_y(root: Node, nodes: dict[Key, Node]) -> dict[str, float]:
    """Svislé rozmístění po částech: v části (rozvaděč, samostatný prvek) shora dolů, potomci v jiné části až pod
    spodkem celé nadřazené části (mezera na popisek kabelu, rámečky se nepřekrývají). Vrací spodek každé části."""
    lows: dict[str, float] = {}
    def place(n: Node, y: float) -> None:
        n.y = y
        if n.kind == "symbol":
            ax, ay = n._anchor     # type: ignore[attr-defined]
            _bx0, by0, _bx1, by1 = n._box   # type: ignore[attr-defined]
            # značka, která přesahuje nad vstupní port (DS, spotřeba s portem z boku), začíná horní hranou v y
            top = ay if n.element.symbol_id in METER_SYMBOLS else max(ay, by1)   # elektroměr: port na výšce MTP
            n.origin = (n.x - ax, y - top)
            n.bottom = n.origin[1] + by0
            label_bottom = y - REF_H - LINE_H * (len(n.labels) - 1) - 0.8 if n.labels else n.bottom
            n.down = min(n.bottom, label_bottom)
        else:
            n.origin = (n.x, y)
            n.bottom = y
            n.down = y - (LABEL_H + 1.0 if n.kind == "pass" and n.labels else 0.0)

    def segment(start: Node, y: float) -> None:
        seg = start.segment
        members: list[Node] = []
        pending: list[Node] = []

        def walk(n: Node, y: float) -> None:
            place(n, y)
            members.append(n)
            for m in n.meters:   # port 1 elektroměru ve výšce sekundáru měřicího transformátoru
                links = getattr(m, "links", [])
                pr = (_port_abs(n, links[0][1]) if links else None) or (n.x, n.y)
                place(m, pr[1])
                members.append(m)
            y_next = (n.y - BUS_GAP) if n.kind == "bus" else (n.bottom - GAP)
            for c in n.children:
                if c.segment == seg:
                    walk(c, y_next)
                else:
                    pending.append(c)

        walk(start, y)
        low = min(n.down for n in members)
        lows[seg] = low
        for c in pending:
            parent = next(n for n in members if c in n.children)
            segment(c, low - cable_gap(parent, c))

    segment(root, 0.0)
    return lows


def _port_abs(n: Node, port: str | None) -> Point | None:
    if n.kind != "symbol":
        return (n.x, n.y)
    rel = _port_rel(n.symbol, port, n.rot)
    return (n.origin[0] + rel[0], n.origin[1] + rel[1]) if rel else None


def single_line_geometry(project: Project, lib, dc: bool = False) -> SingleLineGeometry:
    """Kreslicí seznam jednopólového schématu a formát strany (nejmenší z A3–A0, do kterého se vejde 1 : 1)."""
    g = SingleLineGeometry()
    root, nodes = build_tree(project, lib, dc)
    g.root, g.nodes = root, nodes
    if root is None:
        return g
    counts = _string_counts(project)
    for n in nodes.values():
        n.labels = _labels(project, n, counts)
        _measure(n)
    for n in nodes.values():
        for m in n.meters:
            m._dx = n.right + METER_GAP + m.left      # type: ignore[attr-defined]
            n.right = m._dx + m.right                  # type: ignore[attr-defined]
    n_cols = _assign_columns(root)
    left = [0.0] * n_cols
    right = [0.0] * n_cols
    meters = {id(m) for n in nodes.values() for m in n.meters}
    for n in nodes.values():
        if id(n) in meters:
            continue
        left[n.col] = max(left[n.col], n.left)
        right[n.col] = max(right[n.col], n.right)
    xs, x = [], 0.0
    for c in range(n_cols):
        x += left[c] if c == 0 else max(right[c - 1] + left[c] + COL_GAP, 15.0)
        xs.append(x)
    for n in nodes.values():
        n.x = xs[n.col]
    for n in nodes.values():
        for m in n.meters:
            m.x = n.x + m._dx                          # type: ignore[attr-defined]
    seg_low = _place_y(root, nodes)
    prims = _draw(project, root, nodes, g, seg_low)
    _fit_page(g, prims)
    return g


# ---- kresba ------------------------------------------------------------------------------------------------------
def _line(pts, weight="wire", style="solid", layer="VODICE") -> Prim:
    pts = tuple(pts)
    return Prim("line" if len(pts) == 2 else "poly", 0, pts, layer=layer, style=style, weight=weight)


def _text(x, y, text, h=LABEL_H, align="left", layer="TEXTY") -> Prim:
    return Prim("text", 0, ((x, y),), text=text, h=h, align=align, layer=layer)


def _entry_point(n: Node) -> Point:
    """Kam vede vodič od nadřazeného prvku: vstupní port značky (u značky přesahující nad port níž než `n.y`)."""
    p = _port_abs(n, n.entry) if n.kind == "symbol" else None
    return p if p is not None else (n.x, n.y)


def _route(a: Point, b: Point, jy: float) -> list[Point]:
    """Svisle – vodorovně (ve výšce jy) – svisle z bodu a do bodu b."""
    if abs(a[0] - b[0]) < 1e-6:
        return [a, b]
    return [a, (a[0], jy), (b[0], jy), b]


def _draw(project: Project, root: Node, nodes: dict[Key, Node], g: SingleLineGeometry,
          seg_low: dict[str, float]) -> list[Prim]:
    out: list[Prim] = []
    for n in nodes.values():
        if n.kind == "symbol":
            out.append(Prim("symbol", 0, (n.origin,), rot=n.rot, symbol=n.symbol, symbol_id=n.symbol.id, layer="SYMBOLY"))
            if n.labels:
                if n.meters:
                    lx, align = min(n.origin[0] + n._box[0], n.x) - 1.5, "right"   # type: ignore[attr-defined]
                else:
                    lx, align = max(n.origin[0] + n._box[2], n.x) + 1.5, "left"    # type: ignore[attr-defined]
                for i, t in enumerate(n.labels):
                    out.append(_text(lx, n.y - REF_H - i * LINE_H, t, REF_H if i == 0 else LABEL_H, align))
        elif n.kind == "pass" and n.labels:
            out.append(_text(n.x + 1.5, n.y - LABEL_H - 0.5, n.labels[0], LABEL_H))
        # vodiče k potomkům
        if n.kind == "bus":
            if n.children:
                xs = [c.x for c in n.children] + [n.x]
                out.append(_line([(min(xs) - 2.5, n.y), (max(xs) + 2.5, n.y)], weight="bus", layer="SBERNICE"))
                if n.element.attrs.get("desc"):
                    out.append(_text(max(xs) + 3.5, n.y - 0.8, n.element.attrs["desc"], LABEL_H))
            for c in n.children:
                out.append(_line([(c.x, n.y), _entry_point(c)]))
        else:
            jy = n.bottom - GAP / 2
            for c in n.children:
                a = _port_abs(n, c.exit) or (n.x, n.bottom)
                pts = _route(a, _entry_point(c), jy if c.segment == n.segment else (c.y + n.down) / 2)
                out.append(_line(pts))
            if len(n.children) > 1:
                out.append(Prim("dot", 0, ((n.x, jy),), r=0.6, layer="SBERNICE"))
        # elektroměr: čárkovaně ke všem měřicím transformátorům
        for m in n.meters:
            for o, port, _w in getattr(m, "links", []):
                on = nodes.get(o)
                a = _port_abs(on, port) if on is not None else None
                b = _port_abs(m, "1" if on is n else "2")
                if a is None or b is None:
                    continue
                pts = [a, (b[0], a[1]), b] if abs(a[1] - b[1]) > 1e-6 else [a, b]
                out.append(_line(pts, weight="thin", style="dashed", layer="ODKAZY"))
    # kabely mezi částmi
    for n in nodes.values():
        for c in n.children:
            if c.segment == n.segment or c.wire is None or not c.wire.attrs.get("ref"):
                continue
            text = wire_label(c.wire.attrs, mp.wire_conductors(c.wire))
            length = c.wire.attrs.get("length", "")
            lines = [text] + ([f"l = {length} m"] if length else [])
            upper = seg_low.get(n.segment, n.down) - (FRAME_PAD if n.sheet.is_switchboard else 0.0)
            lower = c.y + (TITLE_H if c.sheet.is_switchboard else 0.0)
            mid = (upper + lower) / 2 + (len(lines) - 1) * LINE_H / 2
            for i, t in enumerate(lines):
                out.append(_text(c.x + 1.5, mid - i * LINE_H - 0.8, t, LABEL_H))
    # rámečky rozvaděčů
    by_seg: dict[str, list[Node]] = {}
    for n in nodes.values():
        if n.sheet.is_switchboard:
            by_seg.setdefault(n.sheet.id, []).append(n)
    for sid, members in by_seg.items():
        sheet = members[0].sheet
        x0 = min(n.x - n.left for n in members) - FRAME_PAD
        x1 = max(n.x + n.right for n in members) + FRAME_PAD
        y1 = max(n.y for n in members) + TITLE_H
        y0 = min(n.down for n in members) - FRAME_PAD
        block = project.sheet_of_element(sheet.parent_element_id) if sheet.parent_element_id else None
        be = block.element(sheet.parent_element_id) if block is not None else None
        ref = be.ref if be is not None else sheet.loc or sheet.name
        desc = be.attrs.get("desc", "") if be is not None else ""
        top = max(n.y for n in members)
        tx = min(n.x for n in members if n.y == top) + 3.0      # vpravo od přívodu (čára vede shora)
        title_w = len(ref) * 3.0 * CHAR_W + 3.0 + len(desc) * LABEL_H * CHAR_W
        x1 = max(x1, tx + title_w + 2.0)
        out.append(_text(tx, y1 - 5.0, ref, 3.0))
        if desc:
            out.append(_text(tx + len(ref) * 3.0 * CHAR_W + 3.0, y1 - 5.0, desc, LABEL_H))
        out.append(_line([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], weight="thin", style="dashed",
                         layer="ROZVADECE"))
        g.frames[sid] = (x0, y0, x1, y1)
    return out


def _bbox(prims: list[Prim]) -> tuple[float, float, float, float]:
    boxes = _boxes(prims)
    if not boxes:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _boxes(prims: list[Prim]) -> list[tuple[float, float, float, float]]:
    """Obálka každého primitiva (x0, y0, x1, y1)."""
    out = []
    for p in prims:
        xs: list[float] = []
        ys: list[float] = []
        if p.kind == "symbol" and p.symbol is not None:
            x0, y0, x1, y1 = _sym_box(p.symbol, int(p.rot))
            ox, oy = p.pts[0]
            xs += [ox + x0, ox + x1]
            ys += [oy + y0, oy + y1]
        elif p.kind == "text":
            (x, y), = p.pts
            w = len(p.text) * p.h * CHAR_W
            x0 = {"left": x, "center": x - w / 2, "right": x - w}.get(p.align, x)
            xs += [x0, x0 + w]
            ys += [y - 0.3 * p.h, y + p.h]
        else:
            xs += [q[0] for q in p.pts]
            ys += [q[1] for q in p.pts]
        if xs:
            out.append((min(xs), min(ys), max(xs), max(ys)))
    return out


def _shift(p: Prim, dx: float, dy: float) -> Prim:
    from dataclasses import replace
    return replace(p, pts=tuple((x + dx, y + dy) for x, y in p.pts))


def _fit_page(g: SingleLineGeometry, prims: list[Prim]) -> None:
    """Nejmenší formát na šířku (A3–A0), do kterého se kresba vejde 1 : 1 nad popisové pole; kresba vlevo nahoře."""
    from envocad.model.frame import MARGIN, MARGIN_LEFT, TB_H, TB_W
    x0, y0, x1, y1 = _bbox(prims)
    w, h = x1 - x0, y1 - y0
    paper, pw, ph = PAPERS[-1]
    for name, fw, fh in PAPERS:
        if w > fw - MARGIN_LEFT - MARGIN - 2 * PAGE_PAD or h > fh - 2 * MARGIN - 2 * PAGE_PAD:
            continue
        # kresba vlevo nahoře: do pásu popisového pole (dole vpravo) nesmí zasahovat
        dy = fh - MARGIN - PAGE_PAD - y1
        band = MARGIN + TB_H + PAGE_PAD - dy
        x_tb = fw - MARGIN - TB_W - PAGE_PAD - (MARGIN_LEFT + PAGE_PAD - x0)
        if all(b[2] <= x_tb for b in _boxes(prims) if b[1] < band):
            paper, pw, ph = name, fw, fh
            break
    dx = MARGIN_LEFT + PAGE_PAD - x0
    dy = ph - MARGIN - PAGE_PAD - y1
    g.prims = [_shift(p, dx, dy) for p in prims]
    for n in g.nodes.values():
        n.x, n.y = n.x + dx, n.y + dy
        n.origin = (n.origin[0] + dx, n.origin[1] + dy)
        n.bottom += dy
        n.down += dy
    g.frames = {k: (a + dx, b + dy, c + dx, d + dy) for k, (a, b, c, d) in g.frames.items()}
    g.page_size, g.paper = (pw, ph), paper
