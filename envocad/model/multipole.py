"""Vícepólový pohled odvozený z jednopólového listu (bez Qt).

Nic se nekopíruje: pohled se počítá z `Sheet` – každá žíla vodiče (`Wire.conductors`) je samostatná čára
mezi „póly“ prvků. Pól = port prvku posunutý kolmo na směr portu o násobek `POLE_PITCH`.
Prvek s průchozími porty (dva porty proti sobě, např. jistič 1–2) se v pohledu opakuje pro každou
spínanou žílu; nespínané žíly (N u 3p jističe, PE) jdou kolem prvku jako přímá čára.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from itertools import pairwise

from envocad.model.designation import element_name
from envocad.model.feed import (
    FEED_SYMBOL,
    feed_dir,
    is_feed,
    is_feed_in,
    is_feed_out,
    is_mp_legacy,
    multipole_feed_view,
)
from envocad.model.grid import snap as _snap
from envocad.model.project import FEED_SYMBOLS, Element, Sheet, Wire
from envocad.model.symbol import GRID, Symbol, rotate_dir

POLE_PITCH = 3 * GRID  # 7,5 mm mezi póly
COL_GAP = 30.0          # mezera mezi sloupci automatického rozmístění (ve směru toku)
ROW_GAP = 15.0          # mezera mezi prvky ve sloupci (kolmo na tok)
BAR_GAP = 32.0          # PE lišta pod řadou vývodů: mezera za vývody (štítek kabelu ~13 mm, příčky PE pod ním)
MIN_BAR_GAP = 22.0      # nejmenší mezera k PE liště při zhuštění na stranu A4
SOURCE_SYMBOLS = {FEED_SYMBOL, "fve.pv_string", "fve.battery"}  # zdroje toku (síť je konec; přívod jen `dir=in`)

# Kanonické pořadí žil (shora dolů / zleva doprava)
CANON = ["L1", "L2", "L3", "N", "PE", "PEN", "L+", "L-", "M", "+", "-"]   # DC dle ČSN EN 60445: L+ / L− / M
NEVER_SWITCHED = {"PE", "PEN"}
TERMINAL_SYMBOLS = {FEED_SYMBOL, "sb.terminal_block", "fve.terminal", "sb.pe_bar"}
# řadové svorky: prvek v JPS = skupina svorek (jedna na žílu), čísla v atributu `terminal` ("1 2 3 4 5" nebo "1")
TERMINAL_BLOCK_SYMBOLS = {"sb.terminal_block", "fve.terminal", FEED_SYMBOL}  # přívod/vývod = svorky X1:1…n

OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
# kolmý směr pro řazení pólů (model, Y nahoru): vodorovný tok → póly dolů, svislý tok → póly doprava
PERP = {"E": (0.0, -1.0), "W": (0.0, -1.0), "N": (1.0, 0.0), "S": (1.0, 0.0)}


def canon_key(c: str) -> tuple[int, str]:
    return (CANON.index(c) if c in CANON else len(CANON), c)


def parse_conductors(text: str) -> list[str]:
    """„L1 L2 L3 N PE“ / „L1,L2“ → seznam žil (bez duplicit, pořadí zachováno); „DC+ DC-“ → „L+ L-“ (ČSN EN 60445)."""
    from envocad.model.project import conductor_name
    out: list[str] = []
    for tok in (conductor_name(t) for t in text.replace(",", " ").replace(";", " ").split()):
        if tok not in out:
            out.append(tok)
    return out


def default_conductors(a: Element, pa: str, b: Element, pb: str) -> list[str]:
    """Výchozí žíly nového vodiče podle portů a pólů připojených prvků."""
    for e in (a, b):
        if e.symbol_id.startswith("ctl."):  # ovládací obvod: jedna žíla
            return ["L"]
    from envocad.model.inverter_io import io_conductors
    for e, p in ((a, pa), (b, pb)):       # komunikační svorka střídače (RS485 → A, B; LAN; DI…)
        if e.symbol_id in ("fve.inverter", "fve.inverter_hybrid"):
            cores = io_conductors(p)
            if cores is not None:
                return cores
    for p in (pa, pb):
        up = p.upper()
        if up in ("DC+", "DC-", "+", "-", "L+", "L-"):
            from envocad.model.project import conductor_name
            return [conductor_name(p)]
        if up.startswith("DC") or up == "BAT":  # jednopólová DC čára = pár L+ / L− (ČSN EN 60445)
            return ["L+", "L-"]
        if up == "PE":
            return ["PE"]
    poles = 1
    for e in (a, b):
        poles = max(poles, e.poles)
        try:
            poles = max(poles, int(e.attrs.get("phases") or 0))
        except ValueError:
            pass
    return ["L1", "L2", "L3", "N", "PE"] if poles >= 3 else ["L1", "N", "PE"]


PHASES = ("L1", "L2", "L3", "L")
SINGLE_POLE_KINDS = ("breaker", "mcb", "fuse")     # jistič, pojistka – měřicí přístroje (elektroměr, MTP, MTN) ne


def single_pole_device(e: Element) -> bool:
    """Jistič nebo pojistka s výslovně jedním pólem (`poles` = 1): vede se na něj jen jedna fáze. Elektroměr,
    měřicí transformátory a prvky bez atributu `poles` ne – jejich žíly (napěťové cesty, S1/S2) zůstávají."""
    return str(e.attrs.get("poles") or "").strip() == "1" and any(k in e.symbol_id for k in SINGLE_POLE_KINDS) \
        and e.symbol_id not in TERMINAL_SYMBOLS


def branch_conductors(src: list[str], device: Element) -> list[str]:
    """Žíly nového vodiče z uzlu k přístroji: převezme žíly vodiče uzlu, ale na jednopólový přístroj (atribut
    `poles` = 1: jistič 1p, pojistka) vede jen jedna fáze – první fáze vodiče uzlu (většinou L1)."""
    if not single_pole_device(device):
        return list(src)
    phase = next((c for c in src if c in PHASES), None)
    return [phase] if phase else list(src)


def has_multipole(sheet) -> bool:
    """List rozvaděče má vícepól a plán svorkovnice – ne rozvaděč VN (kobky, `layout.params["voltage_level"] == "vn"`),
    ten se dokumentuje jednopólovým schématem."""
    return sheet.layout.params.get("voltage_level", "") != "vn"


def is_flow_source(e: Element) -> bool:
    """Zdroj toku ve vícepólu a při hledání nadřazeného jištění: přívod (`dir=in`), FV string, baterie."""
    return e.symbol_id in SOURCE_SYMBOLS and (not is_feed(e) or is_feed_in(e))


def is_terminal_block(e: Element) -> bool:
    return e.symbol_id in TERMINAL_BLOCK_SYMBOLS


def terminal_numbers(e: Element, n: int) -> list[str]:
    """Čísla svorek skupiny pro n žil z atributu `terminal`: seznam („1 2 3 N PE“) nebo první číslo („6“ → 6, 7, 8…).
    Bez atributu vrací prázdné řetězce."""
    toks = parse_conductors(e.attrs.get("terminal", ""))
    if not toks:
        # přívod/vývod bez zadaných čísel: svorky 1…n
        return [str(i + 1) for i in range(n)] if e.symbol_id in FEED_SYMBOLS else [""] * n
    if len(toks) == 1 and toks[0].isdigit() and n > 1:
        k = int(toks[0])
        return [str(k + i) for i in range(n)]
    return (toks + [""] * n)[:n]


def terminal_designation(e: Element, slots: list[str], conductor: str) -> str:
    """„X2:7“ pro žílu na svorkovém prvku (prázdné, když číslo chybí)."""
    nums = terminal_numbers(e, len(slots))
    i = slots.index(conductor) if conductor in slots else -1
    num = nums[i] if i >= 0 else ""
    return f"{e.ref}:{num}" if num else ""


def wire_conductors(w: Wire) -> list[str]:
    return list(w.conductors) if w.conductors else ["L1"]


def through_ports(sym: Symbol, rotation: int) -> tuple[str, str] | None:
    """Dvojice průchozích portů (proti sobě), pokud má symbol právě dva porty s opačným směrem – nebo dvojice
    `multipole["through"]` u značky s dalšími porty (MTP: primár 1–2 v sérii, sekundár S zvlášť)."""
    names = (sym.multipole or {}).get("through")
    if names and len(names) == 2:
        by_name = {p.name: p for p in sym.ports}
        if names[0] not in by_name or names[1] not in by_name:
            return None
        p, q = by_name[names[0]], by_name[names[1]]
    elif len(sym.ports) != 2:
        return None
    else:
        p, q = sym.ports
    if OPPOSITE.get(rotate_dir(p.dir, rotation)) == rotate_dir(q.dir, rotation):
        return (p.name, q.name)
    return None


@dataclass
class ElementPoles:
    element: Element
    symbol: Symbol
    slots: list[str]                      # žíly v pořadí slotů (0 = na portu)
    switched: list[str]                   # žíly, které prvek spíná (opakuje se pro ně symbol)
    bypass: list[str]                     # žíly, které jdou kolem prvku
    through: tuple[str, str] | None       # průchozí porty
    per_port: dict[str, set[str]] = field(default_factory=dict)
    origin: tuple[float, float] = (0.0, 0.0)  # pozice prvku ve vícepólu (ruční nebo z automatického rozmístění)
    # žíla připojená na volnou svorku pólu jiné žíly: {žíla: žíla pólu} – např. cívka A1 = L1, A2 = N
    # → {"N": "L1"}: N se napojí na A2 pólu L1 (prvek spíná/napájí jedním pólem dvě různé žíly)
    joined: dict[str, str] = field(default_factory=dict)
    # popisek prvku přesunutý z výchozí polohy mimo cizí čáry (`multipole_geometry._place_element_label`):
    # [(dx, dy, text, výška, zarovnání)] relativně k `origin`; None = výchozí poloha `pole_label_lines`
    label_lines: list[tuple[float, float, str, float, str]] | None = None
    # žíly vodičů listu, které ve vícepólu nikam nevedou (`dead_conductors`): {id vodiče: {žíla}} – společné všem pólům
    dead: dict[str, set[str]] = field(default_factory=dict)
    # žíla → bod svorky relativně k `origin` (elektroměr při nepřímém měření: `meter_terminal_view`)
    terminals: dict[str, tuple[float, float]] = field(default_factory=dict)
    # sekundár MTP po fázích (`multipole.secondary` značky): žíla → (fáze pólu, bod svorky v souřadnicích značky
    # pólu) na portu `secondary_port`
    secondary: dict[str, tuple[str, tuple[float, float]]] = field(default_factory=dict)
    secondary_port: str = ""

    def flow_shift(self, conductor: str | None) -> tuple[float, float]:
        """Posun pólu žíly po směru toku u prvku s `multipole.stagger` (MTP: transformátory fází pod sebou, aby
        sekundáry S1 / S2 vedly každý v jiné výšce): pól k o (k − (n − 1) / 2) · stagger, prvek zůstává na středu."""
        st = self.stagger
        if not st or not self.secondary_used or conductor not in self.switched or not self.through                 or len(self.switched) < 2:
            return (0.0, 0.0)
        vx, vy = DIR_VEC[rotate_dir(self.symbol.port(self.through[0]).dir, self.element.rotation)]
        k = self.switched.index(conductor) - (len(self.switched) - 1) / 2
        return (-vx * k * st, -vy * k * st)

    @property
    def secondary_used(self) -> bool:
        """Na port sekundáru vedou žíly sekundáru po fázích (`multipole.secondary`) – jen pak se póly posouvají po
        toku a kreslí příčka sekundáru; starý projekt (žíly S1 / S2) zůstává jako dřív."""
        return bool(self.secondary_port) and any(c in self.secondary
                                                 for c in self.per_port.get(self.secondary_port, ()))

    @property
    def stagger(self) -> float:
        try:
            return float((self.symbol.multipole or {}).get("stagger") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def slot(self, conductor: str) -> int:
        conductor = self.joined.get(conductor, conductor)
        return self.slots.index(conductor) if conductor in self.slots else 0

    def pole_pos(self, port: str, conductor: str) -> tuple[float, float]:
        """Pozice pólu pro danou žílu na daném portu (model mm, ve škále pohledu)."""
        e = self.element
        if conductor in self.terminals:            # svorka elektroměru (každá žíla na svou)
            tx, ty = self.terminals[conductor]
            return (self.origin[0] + tx, self.origin[1] + ty)
        sec = self.secondary.get(conductor) if port == self.secondary_port else None
        if sec is not None and sec[0] in self.switched:
            # sekundár MTP u pólu své fáze: svorka S1 / S2 na příčce u kroužku (`multipole.secondary.at`)
            from envocad.model.symbol import place_point
            ax, ay = pole_anchor(self, sec[0])
            dx, dy = place_point(*sec[1], e.rotation, e.mirror)
            return (ax + dx, ay + dy)
        # uzel je bod: žíly končí ve středu tečky (ne u portu o 2,5 mm vedle) a odbočky z ní vycházejí
        px, py = (e.x, e.y) if e.symbol_id == "sb.junction" else e.port_pos(self.symbol, port)
        d = rotate_dir(self.symbol.port(port).dir, e.rotation)
        ox, oy = PERP[d]
        k = self.slot(conductor)
        mx, my = self.origin
        if self.through and port in self.through:
            fx, fy = self.flow_shift(self.joined.get(conductor, conductor))
            mx, my = mx + fx, my + fy
        return (mx + (px - e.x) + ox * k * self.pitch, my + (py - e.y) + oy * k * self.pitch)

    @property
    def pitch(self) -> float:
        """Rozteč pólů prvku: `POLE_PITCH`, nebo vlastní ze značky (`multipole.pitch` – přepínač sítí má u každého
        pólu dva vstupy I / II, póly po 12,5 mm, aby se dvojice sousedních pólů neslily)."""
        try:
            return float((self.symbol.multipole or {}).get("pitch") or POLE_PITCH)
        except (TypeError, ValueError):
            return POLE_PITCH

    @property
    def per_pole(self) -> bool:
        """Kreslí se po pólech: průchozí prvek, nebo přívod/vývod (svorka na každou žílu)."""
        return bool(self.switched) and (self.through is not None or self.element.symbol_id in FEED_SYMBOLS)

    def pole_offset(self, conductor: str) -> tuple[float, float]:
        """Posun opakovaného symbolu pro spínanou žílu (podle směru průchozích portů, u přívodu podle jeho portu)."""
        if not self.through and self.element.symbol_id not in FEED_SYMBOLS:
            return (0.0, 0.0)
        port = self.through[0] if self.through else self.symbol.ports[0].name
        d = rotate_dir(self.symbol.port(port).dir, self.element.rotation)
        ox, oy = PERP[d]
        k = self.slot(conductor)
        fx, fy = self.flow_shift(conductor)
        return (ox * k * self.pitch + fx, oy * k * self.pitch + fy)


BUS_SYMBOL = "sb.busbar"


def perp_extent(ep: ElementPoles) -> float:
    """Rozměr prvku kolmo na směr toku včetně všech pólů (mm)."""
    if ep.element.symbol_id == BUS_SYMBOL:
        return POLE_PITCH   # sběrnice se kreslí přes celou stranu, v rozmístění nezabírá místo
    x0, y0, x1, y1 = ep.symbol.bounds()
    if ep.terminals:        # elektroměr se svorkami: žíly končí na svorkách obdélníku, žádné sloty navíc
        return x1 - x0
    horizontal = ep.through is None or rotate_dir(ep.symbol.port(ep.through[0]).dir, ep.element.rotation) in ("E", "W")
    if ep.through is None and ep.symbol.ports:
        horizontal = rotate_dir(ep.symbol.ports[0].dir, ep.element.rotation) in ("E", "W")
    base = (y1 - y0) if horizontal else (x1 - x0)
    if ep.element.rotation in (90, 270):
        base = (x1 - x0) if horizontal else (y1 - y0)
    # buňka na pól má vždy celou rozteč, aby prvky se stejným počtem žil měly stejný rozměr (zarovnání sloupců)
    return max(base, ep.pitch) + max(0, len(ep.slots) - 1) * ep.pitch


def flow_extent(ep: ElementPoles) -> float:
    if ep.element.symbol_id == BUS_SYMBOL:
        return 5.0 * max(len(ep.slots), 1) + 5.0   # čáry potenciálů pod sebou
    x0, y0, x1, y1 = ep.symbol.bounds()
    w, h = (x1 - x0, y1 - y0) if ep.element.rotation in (0, 180) else (y1 - y0, x1 - x0)
    extra = ep.stagger * (len(ep.switched) - 1) if ep.through and ep.secondary_used else 0.0   # MTP po fázích
    return (w if _flow_is_horizontal_for(ep) else h) + extra


def _flow_is_horizontal_for(ep: ElementPoles) -> bool:
    if ep.through:
        return rotate_dir(ep.symbol.port(ep.through[0]).dir, ep.element.rotation) in ("E", "W")
    if ep.symbol.ports:
        return rotate_dir(ep.symbol.ports[0].dir, ep.element.rotation) in ("E", "W")
    return True


COIL_PORTS = {"A1", "A2"}   # svorky cívky (IEC 60445) – vodič na ně je ovládací, ne silový tok


def is_control_wire(w: Wire) -> bool:
    """Vodič na svorku cívky (A1/A2): ovládání, neurčuje hloubku přístroje v silovém toku vícepólu."""
    return w.a.port in COIL_PORTS or w.b.port in COIL_PORTS


def _bfs_depth(sources: set[str], adj: dict[str, set[str]], seed: dict[str, int]) -> dict[str, int]:
    """Hloubka uzlů od zdrojů (BFS po `adj`). `seed` = už známé hloubky (zachovají se a šíří se dál od nich)."""
    depth = dict(seed)
    for s in sources:
        depth.setdefault(s, 0)
    buckets: dict[int, list[str]] = {}
    for n, d in depth.items():
        buckets.setdefault(d, []).append(n)
    d = 0
    top = max(buckets, default=0)
    while d <= top:
        for c in sorted(buckets.get(d, [])):
            if depth[c] != d:
                continue
            for n in sorted(adj.get(c, ())):
                if n not in depth:
                    depth[n] = d + 1
                    buckets.setdefault(d + 1, []).append(n)
                    top = max(top, d + 1)
        d += 1
    return depth


def _power_depth(sheet: Sheet, poles: dict[str, ElementPoles], comp: dict[str, str], sources: set[str],
                 bar_ids: set[str], merge: bool = True) -> dict[str, int]:
    """Hloubka uzlů (`comp`) v silovém toku od zdrojů. Bez vodičů na cívky (A1/A2) a lišt N/PE. Tok prochází
    přístrojem z jedné strany na druhou: do přístroje vstoupí portem jednoho směru a nepokračuje portem stejného
    směru (přepínač sítí I-0-II: z přívodu II se nevrací do přívodu I – stykač na přívodu I by jinak dostal hloubku
    od přepínače a kreslil se pod ním). Soutok (víc přívodů na vstupní straně) je pod nejhlubším z nich – hlavní
    větev zůstane svislá a přístroje za soutokem se posunou s ním. Uzel (`sb.junction`) a můstkem spojené svorky
    jsou bod (bez stran)."""
    def side(eid: str, port: str) -> str | None:
        ep = poles[eid]
        if ep.element.symbol_id == JUNCTION_SYMBOL or sum(1 for v in comp.values() if v == comp[eid]) > 1:
            return None
        try:
            return rotate_dir(ep.symbol.port(port).dir, ep.element.rotation)
        except (KeyError, StopIteration, ValueError, AttributeError):
            return None

    edges: dict[str, list[tuple[str | None, str, str | None]]] = {}   # uzel -> [(strana, soused, strana souseda)]
    for w in sheet.wires:
        a, b = w.a.element_id, w.b.element_id
        if a not in comp or b not in comp or comp[a] == comp[b] or is_control_wire(w) or {a, b} & bar_ids:
            continue
        sa, sb_ = side(a, w.a.port), side(b, w.b.port)
        edges.setdefault(comp[a], []).append((sa, comp[b], sb_))
        edges.setdefault(comp[b], []).append((sb_, comp[a], sa))
    depth = dict.fromkeys(sources, 0)
    entry: dict[str, str | None] = dict.fromkeys(sources)
    frontier = sorted(sources)
    while frontier:
        nxt = []
        for c in frontier:
            for sc, n, sn in edges.get(c, ()):
                if entry.get(c) is not None and sc == entry[c]:
                    continue          # zpět na stranu, kterou tok do přístroje vstoupil
                if n not in depth:
                    depth[n] = depth[c] + 1
                    entry[n] = sn
                    nxt.append(n)
        frontier = sorted(nxt)
    inputs = {n: {m for sn, m, _sm in edges.get(n, ()) if sn == e and m in depth}
              for n, e in entry.items() if e is not None}
    if merge and any(len(v) > 1 for v in inputs.values()):
        for _ in range(len(poles)):
            changed = False
            for n, ins in inputs.items():
                for m in ins:
                    if n in inputs.get(m, ()):
                        continue
                    if depth[m] + 1 > depth[n]:
                        depth[n] = depth[m] + 1
                        changed = True
            if not changed:
                break
    return depth


BAR_CLEAR = 2 * GRID   # nejmenší volno mezi dvěma lištami ve stejné řadě
BAR_LABEL_ROOM = 20.0  # místo pro popisek přístroje vlevo od něj (lišta zvednutá do řady přístrojů)


def _clear_of_bars(ep: ElementPoles, perp: float, spans: list[tuple[float, float]], horizontal: bool) -> float:
    """Poloha lišty kolmo na tok posunutá za lišty už umístěné ve stejné řadě (N a PE lišta napájené ze stejného
    uzlu by jinak ležely přes sebe). Posun jde ve směru řazení prvků (svislý tok doprava, vodorovný dolů).
    Obsazený úsek přidá do `spans`."""
    x0, y0, x1, y1 = _rot_box(ep.symbol, 0.0, 0.0, ep.element.rotation)
    lo, hi = (y0, y1) if horizontal else (x0, x1)
    for _ in range(len(spans) + 1):
        hit = [s for s in spans if perp + lo < s[1] + BAR_CLEAR and s[0] - BAR_CLEAR < perp + hi]
        if not hit:
            break
        if horizontal:
            perp = min(s[0] for s in hit) - BAR_CLEAR - hi
            perp = math.floor(perp / GRID) * GRID
        else:
            perp = max(s[1] for s in hit) + BAR_CLEAR - lo
            perp = math.ceil(perp / GRID) * GRID
    spans.append((perp + lo, perp + hi))
    return perp


def auto_layout(sheet: Sheet, poles: dict[str, ElementPoles], x0: float = 40.0, y_top: float = 250.0,
                bridges: dict[str, list[list[str]]] | None = None, page_w: float | None = None,
                col_gap: float = COL_GAP, info: dict | None = None,
                y_min: float | None = None, merge: bool = True) -> dict[str, tuple[float, float]]:
    """Automatické rozmístění vícepólu po sloupcích („svorkové schéma“): hloubka od zdroje (přívod, síť, FV)
    určuje sloupec ve směru toku, uvnitř sloupce se prvky řadí podle pozice v JPS a rozestupují podle počtu pólů.
    Prvky s ruční pozicí (`mp_pos`) zůstávají, kde jsou. `page_w` (svislý tok): šířka strany – strany jsou
    v souřadnici x za sebou (strana k = [x0 + k·page_w, …)). Logická skupina (podstrom: přívod/vývod se svými
    přístroji, string = svorky X + pojistka FU + SPD), která by přesáhla hranici strany a na stranu se vejde, začne
    celá na další straně – nikdy se nerozdělí; větší podstrom se dělí až mezi svými dětmi (vývody za sběrnicí).
    `col_gap` = mezera mezi sloupci ve směru toku (svislý tok; menší na nízké straně A4). `info` (je-li zadán)
    dostane `gaps` = počet mezer mezi sloupci a `horizontal` = směr toku. `y_min` (svislý tok): nejnižší místo
    kresby na straně (horní hrana popisového pole) – řada lišt pod vývody pod ním neskončí (jinak by na vysokém
    listu ležely lišty pod okrajem strany). `merge`: soutok pod nejhlubším přívodem (`_power_depth`)."""
    if info is not None:
        info.update(gaps=0, horizontal=True)
    if not poles:
        return {}
    horizontal = sum(1 for ep in poles.values() if _flow_is_horizontal_for(ep)) * 2 >= len(poles)
    # skupiny svorek spojené můstkem tvoří jeden uzel (stejný sloupec) – napájení jde přes můstek, ne vodičem
    comp: dict[str, str] = {eid: eid for eid in poles}
    if bridges:
        owner: dict[tuple[str, str], str] = {}
        for eid, ep in poles.items():
            e = ep.element
            if is_terminal_block(e) and e.ref:
                for num in terminal_numbers(e, len(ep.slots)):
                    if num:
                        owner[(e.ref, num)] = eid
        for strip, groups in bridges.items():
            for g in groups:
                ids = [owner[(strip, n)] for n in g if (strip, n) in owner]
                for b in ids[1:]:
                    root = comp[ids[0]]
                    for k, v in comp.items():
                        if v == comp[b]:
                            comp[k] = root
    bar_ids = {i for i in poles if poles[i].element.symbol_id == "sb.pe_bar"}
    adj: dict[str, set[str]] = {c: set() for c in comp.values()}
    power: dict[str, set[str]] = {c: set() for c in comp.values()}   # silové vazby (bez cívek a lišt)
    for w in sheet.wires:
        if w.a.element_id in comp and w.b.element_id in comp:
            ca, cb = comp[w.a.element_id], comp[w.b.element_id]
            if ca != cb:
                adj[ca].add(cb)
                adj[cb].add(ca)
                if not is_control_wire(w) and not {w.a.element_id, w.b.element_id} & bar_ids:
                    power[ca].add(cb)
                    power[cb].add(ca)
    sources = {comp[eid] for eid, ep in poles.items() if is_flow_source(ep.element)}
    if not sources:
        key = (lambda ep: ep.element.x) if horizontal else (lambda ep: -ep.element.y)
        sources = {comp[min(poles.values(), key=key).element.id]}
    cdepth = _power_depth(sheet, poles, comp, sources, bar_ids, merge)
    # hloubku určuje silový tok; cívky (A1/A2) a lišty N/PE dostanou hloubku až od sousedů – vazba cívky na
    # kontakty stykače ani lišta by jinak zkrátily cestu a přístroj v hlavním toku by „předběhl“ svůj přívod
    cdepth = _bfs_depth(sources, adj, cdepth)
    last = max(cdepth.values(), default=0) + 1
    depth = {eid: cdepth.get(comp[eid], last) for eid in poles}
    # vývody vždy v dolní řadě (jako v EPLAN: přívody nahoře, rozvod, přístroje, vývody dole), PE lišta pod nimi
    sinks = [eid for eid, ep in poles.items() if is_feed_out(ep.element)]
    if sinks:
        bottom = max((d for eid, d in depth.items() if eid not in sinks), default=0) + 1
        for eid in sinks:
            depth[eid] = max(depth[eid], bottom)
        bottom = max(depth[eid] for eid in sinks)
        for eid in sinks:
            depth[eid] = bottom
    columns: dict[int, list[str]] = {}
    for eid, d in depth.items():
        columns.setdefault(d, []).append(eid)
    # sousedé přes vodiče (rodič = soused v předchozím sloupci)
    nb: dict[str, set[str]] = {eid: set() for eid in poles}
    for w in sheet.wires:
        if w.a.element_id in nb and w.b.element_id in nb:
            nb[w.a.element_id].add(w.b.element_id)
            nb[w.b.element_id].add(w.a.element_id)
    key = ((lambda i: (-poles[i].element.y, poles[i].element.x)) if horizontal
           else (lambda i: (poles[i].element.x, -poles[i].element.y)))
    # strom: každý prvek má jednoho rodiče (první soused v předchozím sloupci podle JPS); prvky bez rodiče,
    # které patří do uzlu spojeného můstkem, se zavěsí vedle člena uzlu s rodičem; zbytek jsou kořeny
    children: dict[str, list[str]] = {eid: [] for eid in poles}
    parent: dict[str, str] = {}
    bars = [i for i in poles if poles[i].element.symbol_id == "sb.pe_bar"]   # PE lišta: mimo strom, pod svými sousedy
    for d in sorted(columns):
        for i in sorted(columns[d], key=key):
            if i in bars:
                continue
            # rodič = nejbližší soused s menší hloubkou (vývod posunutý do dolní řady má rodiče o víc sloupců výš)
            ps = sorted((p for p in nb[i] if depth.get(p, d) < d and p not in bars), key=lambda p: (-depth[p], key(p)))
            if ps:
                parent[i] = ps[0]
                children[ps[0]].append(i)
    for d in sorted(columns):
        for i in sorted(columns[d], key=key):
            if i in parent or d == 0:
                continue
            mates = [m for m in columns[d] if comp[m] == comp[i] and m in parent]
            if mates:
                anchor = parent[mates[0]]
                parent[i] = anchor
                children[anchor].append(i)
    wires_at: dict[str, list[Wire]] = {}
    for w in sheet.wires:
        wires_at.setdefault(w.a.element_id, []).append(w)
        if w.b.element_id != w.a.element_id:
            wires_at.setdefault(w.b.element_id, []).append(w)

    def continues(p: str, c: str) -> bool:
        """Dítě vede žíly od rodiče dál (vývod, průchozí přístroj, uzel) – na rozdíl od odbočky, která je ukončí
        (přepěťová ochrana: L+/L− dovnitř, ven jen PE)."""
        if is_feed(poles[c].element):
            return True
        inc = [w for w in wires_at.get(c, ()) if p in (w.a.element_id, w.b.element_id)]
        if not inc:
            return True
        conds = {x for w in inc for x in wire_conductors(w)}
        ports = {w.a.port if w.a.element_id == c else w.b.port for w in inc}
        for w in wires_at.get(c, ()):
            if w in inc:
                continue
            port = w.a.port if w.a.element_id == c else w.b.port
            if port not in ports and conds & set(wire_conductors(w)):
                return True
        return False

    along = "E" if horizontal else "S"

    def junction_rank(p: str, c: str) -> int:
        """Dítě uzlu na portu po toku (hlavní větev, `junction_view_symbols`) první – přímo pod uzlem."""
        if poles[p].element.symbol_id != JUNCTION_SYMBOL:
            return 0
        for w in wires_at.get(p, ()):
            if c in (w.a.element_id, w.b.element_id):
                port = w.a.port if w.a.element_id == p else w.b.port
                try:
                    return 0 if rotate_dir(poles[p].symbol.port(port).dir, poles[p].element.rotation) == along else 1
                except KeyError:
                    return 1
        return 1

    # pokračování toku (string → vývod) přímo pod rodičem, odbočky (SPD ze svorek odpínače) bokem za ním
    for i, c in children.items():
        c.sort(key=lambda ch, i=i: (not continues(i, ch), junction_rank(i, ch), key(ch)))
    roots = [i for i in sorted(poles, key=key) if i not in parent and i not in bars]

    def width(i: str) -> float:
        own = perp_extent(poles[i]) + 8.0
        kids = children[i]
        return max(own, sum(width(c) for c in kids) + ROW_GAP * max(len(kids) - 1, 0))

    col_w = {d: max(flow_extent(poles[i]) for i in ids) for d, ids in columns.items()}
    gap = COL_GAP if horizontal else col_gap
    if info is not None:
        info.update(gaps=max(len(columns) - 1, 0), horizontal=horizontal)
    flow_pos: dict[int, float] = {}
    pos = x0 if horizontal else y_top
    dots = {d for d, ids in columns.items()
            if all(poles[i].element.symbol_id == JUNCTION_SYMBOL for i in ids)}
    prev = None
    for d in sorted(columns):
        if prev is not None and (d in dots or prev in dots):
            # řada jen s uzly (tečky na žílách) nepotřebuje celou mezeru – stačí místo na odbočení žil
            pos += (gap - max(gap / 2, JUNCTION_GAP)) * (1 if not horizontal else -1)
        flow_pos[d] = pos
        pos = pos + col_w[d] + gap if horizontal else pos - col_w[d] - gap
        prev = d
    out: dict[str, tuple[float, float]] = {}
    sign = -1.0 if horizontal else 1.0  # vodorovný tok: prvky ve sloupci jdou dolů; svislý: doprava

    def page_fix(start: float, own: float) -> float:
        """Začátek prvku; přesáhl-li by hranici strany, posune se na začátek další strany."""
        if not page_w or horizontal:
            return start
        k0 = int((start - x0) // page_w)
        k1 = int((start + own - x0) // page_w)
        return start if k1 == k0 else x0 + k1 * page_w

    wire_between: dict[tuple[str, str], Wire] = {}
    for w in sheet.wires:
        wire_between.setdefault((w.a.element_id, w.b.element_id), w)
        wire_between.setdefault((w.b.element_id, w.a.element_id), w)

    def link_wish(parent: str, child: str) -> float | None:
        """Kolmá pozice dítěte, při které je jeho pól pod pólem rodiče, ze kterého vede spojovací žíla
        (vývod PE pod PE svodiče, ne pod L1 – jinak vede svisle skrz rodiče)."""
        w = wire_between.get((parent, child))
        if w is None:
            return None
        pp, cp = (w.a.port, w.b.port) if w.a.element_id == parent else (w.b.port, w.a.port)
        c0 = wire_conductors(w)[0]
        ep_p, ep_c = poles[parent], poles[child]
        try:
            px, py = ep_p.pole_pos(pp, c0)
            save = ep_c.origin
            ep_c.origin = (0.0, 0.0)
            cx, cy = ep_c.pole_pos(cp, c0)
            ep_c.origin = save
        except (KeyError, StopIteration, ValueError):
            return None
        return (py - cy) if horizontal else (px - cx)

    paging = bool(page_w) and not horizontal

    def page_at(v: float) -> int:
        return int((v - x0) // page_w)

    def after(end: float) -> float:
        """Začátek dalšího sourozence za koncem `end`: o mezeru dál; padne-li mezera přes hranici strany, začne
        sourozenec hned na začátku nové strany (ne o kus dál)."""
        nxt = end + sign * ROW_GAP
        if paging and page_at(nxt) > page_at(end - 1e-6):
            nxt = x0 + page_at(nxt) * page_w
        return nxt

    def place(i: str, start: float) -> float:
        """Umístí podstrom jako celek: když přesáhne hranici strany a na jednu stranu se vejde, umístí se znovu od
        začátku další strany (skupina se nerozdělí). Vrátí konec podstromu (kolmo na tok)."""
        end = place_tree(i, start)
        if paging and page_at(start) != page_at(end - 1e-6):
            nxt = x0 + (page_at(start) + 1) * page_w
            if end - start <= page_w + 1e-6 and nxt > start:
                end = place_tree(i, nxt)
            elif nxt > start:
                # šířku mohl nafouknout podstrom, který se sám přesunul na další stranu (rodič by zůstal sám na
                # konci strany a jeho přístroje o stranu dál): zkusí celý strom od začátku další strany
                end2 = place_tree(i, nxt)
                if end2 - nxt <= page_w + 1e-6:
                    end = end2
                else:
                    end = place_tree(i, start)
        return end

    def place_tree(i: str, start: float) -> float:
        """Umístí prvek a jeho podstrom; vrátí konec podstromu (kolmo na tok) – kvůli skokům na další stranu."""
        d = depth[i]
        own = perp_extent(poles[i]) + 8.0
        start = page_fix(start, own)
        perp = start + sign * 8.0
        fp = flow_pos[d]
        out[i] = (fp + col_w[d] / 2, perp) if horizontal else (perp, fp - col_w[d] / 2)
        poles[i].origin = out[i]
        cursor = start
        end = start + sign * own
        for c in children[i]:
            wish = link_wish(i, c)
            if wish is not None:
                want = wish - sign * 8.0
                if (want - cursor) * sign > 0:
                    cursor = want
            e = place(c, cursor)
            cursor = after(e)
            end = max(end, e) if sign > 0 else min(end, e)
        return end

    buses = {i for i in poles if poles[i].element.symbol_id == "sb.busbar"}
    on_bus = buses | {n for b in buses for n in nb[b]}       # sběrnice a vše, co na ni vede vodičem

    def subtree(i: str) -> list[str]:
        return [i, *(x for c in children[i] for x in subtree(c))]

    # strom silově napojený na už umístěný (záložní přívod do přepínače sítí) jde hned za něj, ne až za
    # nesouvisející stromy (ovládání, cívky) – spoj mezi nimi je pak krátký, ne přes celou stranu nebo na další
    tree_of = {x: r for r in roots for x in subtree(r)}
    linked: dict[str, set[str]] = {r: set() for r in roots}
    for x, r in tree_of.items():
        for n in power.get(comp[x], ()):
            for y in (m for m in poles if comp[m] == n):
                if y in tree_of and tree_of[y] != r:
                    linked[r].add(tree_of[y])
    ordered: list[str] = []
    for r in roots:
        if r in ordered:
            continue
        chain = [r]
        while chain:
            q = chain.pop(0)
            if q in ordered:
                continue
            ordered.append(q)
            chain += [o for o in roots if o in linked[q] and o not in ordered and o not in chain]
    roots = ordered

    cursor = y_top if horizontal else x0
    rail_pages: set[int] = set()
    holes: list[float] = []   # volné místo na konci strany, kterou předchozí strom přeskočil (začátek místa)
    root_start: dict[str, float] = {}    # strom (kořen) → začátek jeho místa (napojený strom ho může přesunout)
    # stromy spojené fázovým vodičem (záložní přívod → přepínač sítí) – jen ty se stránkují spolu; spoj přes PE / N
    # (PE stringů do XPE) stromy neváže
    phase_linked: set[tuple[str, str]] = set()
    for w in sheet.wires:
        ra, rb = tree_of.get(w.a.element_id), tree_of.get(w.b.element_id)
        if ra and rb and ra != rb and set(wire_conductors(w)) - {"PE", "PEN", "N"}:
            phase_linked |= {(ra, rb), (rb, ra)}
    for r in roots:
        tree = subtree(r)
        bus_free = not on_bus.intersection(tree)
        # podstrom bez vazby na sběrnici (DC string rozvaděče FVE) nezačíná na straně se sběrnými čarami (vedou
        # přes celou stranu) – přístroje by ležely v jejich pásu (popisky SPD přes 1L1…1PE); začne na další straně
        if paging and rail_pages and bus_free and page_at(cursor) <= max(rail_pages):
            cursor = x0 + (max(rail_pages) + 1) * page_w
        # strom, který se vejde do místa na dřívější straně (zbylo za stromem, který skočil na další stranu),
        # jde tam – ovládání (cívky, vypínací spouště) nezabere celou novou stranu
        filled = False
        for k, h in enumerate(holes):
            if rail_pages and bus_free and page_at(h) <= max(rail_pages):
                continue
            if any(o in out and page_at(out[o][0]) > page_at(h) for o in linked[r]):
                continue      # silově napojený strom zůstane u svého souseda (záložní přívod u přepínače)
            e = place(r, h)
            if page_at(out[r][0]) == page_at(h) and page_at(e - 1e-6) == page_at(h):
                holes[k] = after(e)
                filled = True
                break
        if not filled:
            start = cursor
            end = place(r, cursor)
            partner = next((q for q in linked[r] if q in root_start and paging and (r, q) in phase_linked
                            and page_at(out[q][0]) < page_at(out[r][0])), None)
            if partner is not None:
                # napojený strom skočil na další stranu bez svého souseda (záložní přívod bez přepínače sítí):
                # zkusí se přesunout oba na jeho stranu, aby spoj mezi nimi nevedl přes přerušení
                nxt = x0 + page_at(out[r][0]) * page_w
                e1 = place(partner, nxt)
                e2 = place(r, after(e1))
                if page_at(out[partner][0]) == page_at(out[r][0]) == page_at(nxt) == page_at(e2 - 1e-6):
                    holes.append(root_start[partner])
                    start, end = nxt, e2
                else:
                    place(partner, root_start[partner])
                    end = place(r, start)
            root_start[r] = start
            cursor = after(end)
            if paging and page_at(out[r][0]) > page_at(start):
                holes.append(start)
        if paging:
            rail_pages |= {page_at(out[i][0]) for i in tree if i in on_bus and i in out}
    bar_spans: dict[int, list[tuple[float, float]]] = {}   # řada lišt -> obsazené úseky kolmo na tok
    for b in bars:
        ns = [n for n in nb[b] if n in out]
        d = max([depth[n] for n in ns] + [depth[x] for x in sinks], default=depth[b] - 1) + 1   # PE lišta dole pod vývody
        if d not in flow_pos:
            col_w[d] = flow_extent(poles[b])
            ds = depth[sinks[0]] if sinks else None
            if ds is not None and ds in flow_pos and d == ds + 1:
                # těsně pod řadou vývodů (pod jejich štítky kabelů), ne až na okraji strany
                # zhuštěné sloupce (A4) zmenší i mezeru k liště, nejvýš na MIN_BAR_GAP (štítky kabelů vývodů)
                bar_gap = BAR_GAP if horizontal else max(MIN_BAR_GAP, BAR_GAP - (COL_GAP - gap))
                off = col_w[ds] + bar_gap + col_w[d] / 2
                flow_pos[d] = flow_pos[ds] + (off if horizontal else -off) - (col_w[d] / 2 if horizontal else -col_w[d] / 2)
            else:
                flow_pos[d] = pos + (15.0 if horizontal else -15.0)   # o kus dál, ať příčky PE nevedou přes popisky vývodů
            pos = pos + col_w[d] + gap if horizontal else pos - col_w[d] - gap
        fp = flow_pos[d]
        if y_min is not None and not horizontal and fp - col_w[d] < y_min:
            fp = math.ceil((y_min + col_w[d]) / GRID) * GRID   # lišta nad popisovým polem, ne pod okrajem strany
            # zvednutá lišta padne do řady přístrojů – ty jsou pro ni obsazené úseky (i s popiskem vlevo)
            spans = bar_spans.setdefault(d, [])
            for i, (px, py) in out.items():
                if i in bars:
                    continue
                if abs(py - (fp - col_w[d] / 2)) < (flow_extent(poles[i]) + col_w[d]) / 2 + GRID:
                    if poles[i].element.symbol_id == BUS_SYMBOL and page_w:
                        k = int((px - x0) // page_w)       # sběrnice vede přes celou stranu
                        spans.append((x0 + k * page_w - 8.0, x0 + (k + 1) * page_w - 8.0))
                        continue
                    spans.append((px - 8.0 - BAR_LABEL_ROOM, px - 8.0 + perp_extent(poles[i]) + 8.0))
        if ns:
            vals = [(out[n][1] if horizontal else out[n][0]) for n in ns]
            if page_w and not horizontal:
                # sousedé na více stranách: lišta na stranu s nejvíc sousedy (při shodě na dřívější), uprostřed nich
                from collections import Counter
                pages = Counter(int((v - x0) // page_w) for v in vals)
                k = min(pages.items(), key=lambda kv: (-kv[1], kv[0]))[0]
                vals = [v for v in vals if int((v - x0) // page_w) == k]
            perp = (min(vals) + max(vals)) / 2
        else:
            perp = cursor + sign * 8.0
            cursor += sign * (width(b) + ROW_GAP)
        perp = round(perp / GRID) * GRID
        if page_w and not horizontal and ns:
            # lišta zůstává uvnitř své strany (střed by mohl padnout k okraji)
            k = int((vals[0] - x0) // page_w)
            perp = min(max(perp, x0 + k * page_w + 8.0), x0 + (k + 1) * page_w - perp_extent(poles[b]) - 8.0)
        perp = _clear_of_bars(poles[b], perp, bar_spans.setdefault(d, []), horizontal)
        out[b] = (fp + col_w[d] / 2, perp) if horizontal else (perp, fp - col_w[d] / 2)
    for i, ep in poles.items():
        if ep.element.mp_pos:
            out[i] = tuple(ep.element.mp_pos)
    return out


def sheet_poles(sheet: Sheet, symbol_of) -> dict[str, ElementPoles]:
    """Póly všech prvků listu pro vícepól (`symbol_of(e)` = značka prvku). Přívod/vývod v geometrii starých značek
    (`feed.multipole_feed_view` – vícepól se značkou `sb.feed` nemění). Vícepól kreslí tok vždy shora dolů:
    přívodní větev, která v jednopólovém listu rozvaděče teče zespodu nahoru (přívod s portem nahoře → přístroje
    otočené tokem nahoru → sběrnice; RFVE, RFVE.AC), se ve vícepólu kreslí otočená o 180° jako dřív (přívod nahoře,
    kabel shora) – `flow_flipped`. Prvek v pohledu je pak kopie s jinou rotací (stejné id a atributy)."""
    poles = {e.id: element_poles(sheet, *multipole_feed_view(e, symbol_of(e))) for e in sheet.elements}
    for eid in flow_flipped(sheet, poles):
        ep = poles[eid]
        e = ep.element
        flipped = dataclasses.replace(e, rotation=(e.rotation + 180) % 360)
        poles[eid] = element_poles(sheet, flipped, ep.symbol)
    for eid, rot in upright_rotations(poles).items():
        ep = poles[eid]
        poles[eid] = element_poles(sheet, dataclasses.replace(ep.element, rotation=rot, mirror=False), ep.symbol)
    for eid, sym in junction_view_symbols(sheet, poles).items():
        ep = poles[eid]
        poles[eid] = element_poles(sheet, dataclasses.replace(ep.element, rotation=0, mirror=False), sym)
    for eid, ep in list(poles.items()):
        view = meter_terminal_view(ep)
        if view is not None:
            poles[eid] = element_poles(sheet, dataclasses.replace(ep.element, rotation=0, mirror=False), view)
    dead = dead_conductors(sheet, poles)
    if dead:                # póly prvků bez žil, které nikam nevedou (rozestupy a sloty jen pro živé žíly)
        touched = {end.element_id for w in sheet.wires if w.id in dead for end in (w.a, w.b)}
        for eid in touched & poles.keys():
            ep = poles[eid]
            poles[eid] = element_poles(sheet, ep.element, ep.symbol, dead)
    for ep in poles.values():
        ep.dead = dead
    return poles


def dead_conductors(sheet: Sheet, poles: dict[str, ElementPoles]) -> dict[str, set[str]]:
    """Žíly vodičů, které na jednopólovém jističi / pojistce (`single_pole_device`) nemají pól a za ním nepokračují:
    vodič z uzlu s L1 L2 L3 N PE na jistič 1p – přístroj vezme L1, ostatní žíly k němu nevedou. Nekreslí se ve vícepólu
    a nepočítají se do výrobního zapojovacího seznamu. Svorky, přívody, uzly a prvky bez průchozích portů berou
    všechny žíly; vodiči zůstane vždy aspoň jedna žíla. {id vodiče: {žíla}}."""
    out: dict[str, set[str]] = {}
    for w in sheet.wires:
        conds = wire_conductors(w)
        for end in (w.a, w.b):
            ep = poles.get(end.element_id)
            if ep is None or ep.through is None or end.port not in ep.through or not single_pole_device(ep.element):
                continue        # jen jednopólový přístroj (jistič 1p, zdroj): vícepólový zůstává, jak je nakreslený
            for c in conds:
                if c not in ep.switched and c not in ep.bypass and c not in ep.joined:
                    out.setdefault(w.id, set()).add(c)
        if w.id in out and out[w.id] >= set(conds):
            out[w.id].discard(conds[0])
            if not out[w.id]:
                del out[w.id]
    return out


def sheet_dead_conductors(project, sheet: Sheet, lib) -> dict[str, set[str]]:
    """`dead_conductors` listu rozvaděče s vícepólem (jinak prázdné) – pro výkazy (zapojovací seznam, svorkovnice,
    potenciály), aby žíly, které na jističi 1p nikam nevedou, nebyly ani tam."""
    if lib is None or not sheet.is_switchboard or not has_multipole(sheet):
        return {}
    from envocad.model.project import element_symbol
    return dead_conductors(sheet, sheet_poles(sheet, lambda e: element_symbol(project, e, lib)))


def live_conductors(w: Wire, poles: dict[str, ElementPoles]) -> list[str]:
    """Žíly vodiče ve vícepólu – bez žil, které nikam nevedou (`dead_conductors`)."""
    ep = poles.get(w.a.element_id) or poles.get(w.b.element_id)
    dead = ep.dead.get(w.id, ()) if ep is not None else ()
    return [c for c in wire_conductors(w) if c not in dead]


JUNCTION_SYMBOL = "sb.junction"
JUNCTION_GAP = 7.5    # nejmenší mezera k řadě jen s uzly (odbočení žil se zkosením)
_DIR_POS = {"N": (0.0, GRID), "E": (GRID, 0.0), "S": (0.0, -GRID), "W": (-GRID, 0.0)}


def upright_rotations(poles: dict[str, ElementPoles]) -> dict[str, int]:
    """Vícepól se svislým tokem (shora dolů): průchozí přístroj nakreslený v jednopólovém listu vodorovně (stykač
    s porty vlevo / vpravo) se v pohledu otočí tak, aby vstup (první průchozí port) mířil nahoru – jinak se jeho póly
    kreslí bokem a žíly se k nim stáčejí tam a zpět. Svorky, přívody a uzly ne (mají vlastní pravidla). {id: rotace};
    jen pohled – model beze změny."""
    if not poles or sum(1 for ep in poles.values() if _flow_is_horizontal_for(ep)) * 2 >= len(poles):
        return {}
    out: dict[str, int] = {}
    for eid, ep in poles.items():
        e = ep.element
        if ep.through is None or is_terminal_block(e) or e.symbol_id in (JUNCTION_SYMBOL, BUS_SYMBOL, "sb.pe_bar"):
            continue
        port_in = ep.symbol.port(ep.through[0])
        if rotate_dir(port_in.dir, e.rotation) not in ("E", "W"):
            continue
        rot = next((r for r in (0, 90, 180, 270) if rotate_dir(port_in.dir, r) == "N"), None)
        if rot is not None:
            out[eid] = rot
    return out


def junction_view_symbols(sheet: Sheet, poles: dict[str, ElementPoles]) -> dict[str, Symbol]:
    """Směry portů uzlů (`sb.junction`) ve vícepólu. Uzel je bod (všechny porty stejný potenciál), směry jeho portů
    v jednopólovém listu vycházejí z kresby JPS (přístroj vlevo od uzlu → port W), vícepól ale uzel kreslí pod
    jeho přívodem. Ve vícepólu proto: port k přívodu (soused nejblíž zdroji silového toku) míří proti toku
    (svislý tok nahoru), port k hlavní větvi (nejvíc přístrojů za ní) po toku (dolů) a ostatní odbočky bokem
    (doprava – tam je `auto_layout` staví). Vrací {id uzlu: kopie značky s novými směry a polohami portů} (prvek
    v pohledu má rotaci 0); uzly bez přívodu nemění. Jen pohled – model beze změny."""
    junctions = [i for i, ep in poles.items() if ep.element.symbol_id == JUNCTION_SYMBOL]
    if not junctions:
        return {}
    horizontal = sum(1 for ep in poles.values() if _flow_is_horizontal_for(ep)) * 2 >= len(poles)
    d_in, d_main, d_side = ("W", "E", "S") if horizontal else ("N", "S", "E")
    bars = {i for i, ep in poles.items() if ep.element.symbol_id == "sb.pe_bar"}
    power: dict[str, set[str]] = {i: set() for i in poles}
    links: dict[str, list[tuple[str, str]]] = {}      # uzel -> [(port uzlu, soused)]
    for w in sheet.wires:
        a, b = w.a.element_id, w.b.element_id
        if a not in poles or b not in poles or a == b or is_control_wire(w) or {a, b} & bars:
            continue
        power[a].add(b)
        power[b].add(a)
        links.setdefault(a, []).append((w.a.port, b))
        links.setdefault(b, []).append((w.b.port, a))
    sources = {i for i, ep in poles.items() if is_flow_source(ep.element)}
    if not sources:
        return {}
    depth = _bfs_depth(sources, power, {})

    def downstream(j: str, o: str) -> int:
        """Počet prvků za sousedem `o` (hlouběji než uzel, bez cesty přes uzel)."""
        seen, todo = {j, o}, [o]
        while todo:
            n = todo.pop()
            for m in power[n]:
                if m not in seen and depth.get(m, -1) > depth[j]:
                    seen.add(m)
                    todo.append(m)
        return len(seen) - 1

    out: dict[str, Symbol] = {}
    for j in junctions:
        lst = links.get(j)
        if j not in depth or not lst:
            continue
        known = [(depth[o], port) for port, o in lst if o in depth and depth[o] < depth[j]]
        if not known:
            continue
        p_in = min(known)[1]
        size: dict[str, int] = {}          # port -> přístrojů za ním (pořadí vodičů zachováno)
        for port, o in lst:
            if port != p_in:
                size[port] = size.get(port, 0) + downstream(j, o)
        dirs = {p_in: d_in}
        rest = sorted(size, key=lambda pt: -size[pt])     # stabilní: při shodě pořadí vodičů
        for k, port in enumerate(rest):
            dirs[port] = d_main if k == 0 else d_side
        sym = poles[j].symbol
        free = [d for d in ("N", "E", "S", "W") if d not in dirs.values()]
        ports = []
        for p in sym.ports:
            d = dirs.get(p.name) or (free.pop(0) if free else p.dir)
            x, y = _DIR_POS[d]
            ports.append(dataclasses.replace(p, x=x, y=y, dir=d))
        if any(p.dir != q.dir or p.x != q.x or p.y != q.y for p, q in zip(ports, sym.ports, strict=True))                 or poles[j].element.rotation % 360 or poles[j].element.mirror:
            out[j] = dataclasses.replace(sym, ports=ports)
    return out


# schémata svorek přístrojů s očíslovanými svorkami (elektroměr při nepřímém měření): pořadí svorek, žíla → svorka,
# žíly, podle kterých se schéma použije (sekundár MTP) – `multipole.terminals.scheme` značky
TERMINAL_SCHEMES = {
    "DIN 43856": {      # elektroměr 3f 4vodičový na MTP: I1 1–3, U1 2, I2 4–6, U2 5, I3 7–9, U3 8, N 11
        "order": ("1", "2", "3", "4", "5", "6", "7", "8", "9", "11"),
        "conductors": {"1S1": "1", "1S2": "3", "2S1": "4", "2S2": "6", "3S1": "7", "3S2": "9",
                       "L1": "2", "L2": "5", "L3": "8", "N": "11", "1a": "2", "2a": "5", "3a": "8", "n": "11"},
        "require": ("1S1", "2S1", "3S1"),
    },
}
TERMINAL_SCHEME_SYMBOLS = {"fve.meter": "DIN 43856"}   # pro výkazy bez knihovny (`device_terminal`)


def terminal_scheme(conds: set[str], scheme: str | None) -> dict | None:
    """Schéma svorek (`TERMINAL_SCHEMES`), když na přístroj vede žíla z `require` a všechny jeho žíly mají svorku."""
    spec = TERMINAL_SCHEMES.get(scheme or "")
    if spec is None or not conds & set(spec["require"]) or not conds <= spec["conductors"].keys():
        return None
    return spec


METER_TERMINAL_PITCH = 2 * GRID     # rozteč svorek elektroměru ve vícepólu (jiná než rozteč žil přívodu)
METER_BOX_H = 15.0                  # výška obdélníku elektroměru


def meter_terminal_view(ep: ElementPoles) -> Symbol | None:
    """Elektroměr při nepřímém měření (`multipole.terminals` značky): ve vícepólu obdélník se svorkami nahoře
    podle DIN 43856 (1 2 3 | 4 5 6 | 7 8 9 | 11 – proud I1, napětí U1, …, N) a čísly svorek uvnitř; každá žíla
    vede na svou svorku shora (`ElementPoles.terminals`). Jen když na elektroměr vede žíla sekundáru MTP
    (`require`) a všechny jeho žíly mají svorku – přímé měření (průchozí L1–L3 N) zůstává. Jinak None.
    Porty značky zůstávají (stejná jména, směr nahoru) – vodiče listu se nemění; jen pohled."""
    view = (ep.symbol.multipole or {}).get("terminals") or {}
    conds = set().union(*ep.per_port.values()) if ep.per_port else set()
    spec = terminal_scheme(conds, view.get("scheme"))
    if spec is None:
        return None
    cmap, order = spec["conductors"], list(spec["order"])
    p, h = METER_TERMINAL_PITCH, METER_BOX_H
    xs = {num: i * p for i, num in enumerate(order)}
    x0, x1 = -p / 2, (len(order) - 1) * p + p / 2
    prims: list[dict] = [{"type": "rect", "x": x0, "y": -h, "w": x1 - x0, "h": h}]
    for num, x in xs.items():
        prims.append({"type": "line", "x1": x, "y1": 0.0, "x2": x, "y2": -1.5})
        prims.append({"type": "text", "x": x, "y": -4.0, "text": num, "height": 2.0, "align": "center"})
    if view.get("text"):
        prims.append({"type": "text", "x": (x0 + x1) / 2, "y": -h + 3.0, "text": str(view["text"]), "height": 2.5,
                      "align": "center"})
    at = {c: (xs[cmap[c]], 0.0) for c in sorted(conds, key=canon_key) if cmap[c] in xs}
    ports = []
    for port in ep.symbol.ports:      # port v pohledu u první své svorky, směr nahoru (žíly přicházejí shora)
        mine = [at[c][0] for c in ep.per_port.get(port.name, ()) if c in at]
        ports.append(dataclasses.replace(port, x=min(mine) if mine else 0.0, y=0.0, dir="N"))
    return dataclasses.replace(ep.symbol, primitives=prims, ports=ports, label_pos=(x1 + 2.0, -h / 2),
                               multipole={"terminal_at": {c: list(xy) for c, xy in at.items()}})


def flow_flipped(sheet: Sheet, poles: dict[str, ElementPoles]) -> set[str]:
    """Prvky, které vícepól (svislý tok) kreslí pootočené o 180°: vývod (`dir=out`) s portem dole, přívod (`dir=in`)
    s portem nahoře a průchozí
    prvky jeho větve, do kterých tok vstupuje zdola (port ke zdroji míří dolů – jistič otočený tokem nahoru, SPD nad
    ohybem DC stringu), až po sběrnici nebo prvek s tokem shora. Staré listy (přívod nahoře, tok dolů) nic neotáčí;
    přívod/vývod převedený migrací ze starého projektu (`mp_legacy`) se neotáčí ani se od něj neotáčí větev – vícepól
    starého projektu zůstane, jak byl (i ruční přívod zespodu s jističem otočeným o 90°)."""
    if not poles or sum(1 for ep in poles.values() if _flow_is_horizontal_for(ep)) * 2 >= len(poles):
        return set()
    out: set[str] = set()
    ends: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for w in sheet.wires:
        ends.setdefault((w.a.element_id, w.a.port), []).append((w.b.element_id, w.b.port))
        ends.setdefault((w.b.element_id, w.b.port), []).append((w.a.element_id, w.a.port))
    todo: list[tuple[str, str]] = []
    for eid, ep in poles.items():
        e = ep.element
        if not (is_feed(e) and ep.symbol.ports) or is_mp_legacy(e):
            continue
        d = rotate_dir(ep.symbol.ports[0].dir, e.rotation)
        if is_feed_in(e) and d == "N":
            out.add(eid)
            todo.append((eid, ep.symbol.ports[0].name))
        elif is_feed_out(e) and d == "S":
            out.add(eid)       # vývod portem dolů (kabel nahoru, XMI/XMU v HR): ve vícepólu ve spodní řadě portem nahoru
    while todo:
        eid, port = todo.pop()
        for oid, oport in ends.get((eid, port), []):
            op = poles.get(oid)
            if op is None or oid in out or op.element.symbol_id == BUS_SYMBOL or not op.through:
                continue
            if rotate_dir(op.symbol.port(oport).dir, op.element.rotation) != "S":
                continue                   # tok do prvku shora (běžné rozložení) – dál se neotáčí
            out.add(oid)
            todo.append((oid, op.through[1] if oport == op.through[0] else op.through[0]))
    return out


def feed_cable_up(ep: ElementPoles) -> bool:
    """Štítek a kabel přívodu/vývodu ve vícepólu: na straně proti portu podle otočení (port dolů → kabel shora),
    ne podle druhu značky; port do strany → přívod nahoře, vývod dole."""
    e = ep.element
    if ep.symbol.ports:
        d = rotate_dir(ep.symbol.ports[0].dir, e.rotation)
        if d in ("N", "S"):
            return d == "S"
    return is_feed_in(e)


def element_poles(sheet: Sheet, e: Element, sym: Symbol, dead: dict[str, set[str]] | None = None) -> ElementPoles:
    per_port: dict[str, set[str]] = {p.name: set() for p in sym.ports}
    for w in sheet.wires:
        for end in (w.a, w.b):
            if end.element_id == e.id and end.port in per_port:
                per_port[end.port].update(c for c in wire_conductors(w) if c not in (dead or {}).get(w.id, ()))
    all_c: set[str] = set().union(*per_port.values()) if per_port else set()
    slots = sorted(all_c, key=canon_key)
    thr = through_ports(sym, e.rotation)
    switched: list[str] = []
    bypass: list[str] = []
    if is_terminal_block(e) and (thr or e.symbol_id in FEED_SYMBOLS):
        switched = list(slots)  # každá žíla má svou svorku
    elif thr:
        n = e.poles
        for c in slots:
            if c not in NEVER_SWITCHED and len(switched) < n:
                switched.append(c)
            elif c in per_port[thr[0]] and c in per_port[thr[1]]:
                bypass.append(c)
        if not switched and slots:
            switched.append(slots[0])
    joined = _join_single_port(per_port, thr, switched, bypass, slots) if thr else {}
    if joined:
        slots = [c for c in slots if c not in joined]
    mpd = sym.multipole or {}
    terminals = {c: (float(x), float(y)) for c, (x, y) in (mpd.get("terminal_at") or {}).items()}
    sec = mpd.get("secondary") or {}
    at = {int(k): (float(x), float(y)) for k, (x, y) in (sec.get("at") or {}).items()}
    secondary = {c: (str(ph), at[int(k)]) for c, (ph, k) in (sec.get("conductors") or {}).items() if int(k) in at}
    return ElementPoles(e, sym, slots, switched, bypass, thr, per_port, joined=joined, terminals=terminals,
                        secondary=secondary, secondary_port=str(sec.get("port") or "") if secondary else "")


def _join_single_port(per_port: dict[str, set[str]], thr: tuple[str, str], switched: list[str], bypass: list[str],
                      slots: list[str]) -> dict[str, str]:
    """Žíly průchozího prvku, které nejsou spínané ani nevedou kolem (jsou jen na jednom portu – cívka A1 = L1,
    A2 = N), se připojí na volnou svorku pólu na tomtéž portu: pól spínané žíly, která na tom portu není. PE/PEN se
    nepřipojuje (ochranný vodič nevede přes pól)."""
    out: dict[str, str] = {}
    taken: dict[str, set[str]] = {p: {c for c in per_port.get(p, set()) if c in switched} for p in thr}
    for c in slots:
        if c in switched or c in bypass or c in NEVER_SWITCHED:   # PE nikdy nejde přes pól (SPD: svorka PE zvlášť)
            continue
        ports = [p for p in thr if c in per_port.get(p, set())]
        if len(ports) != 1:
            continue
        port = ports[0]
        free = next((s for s in switched if s not in taken[port]), None)
        if free is not None:
            out[c] = free
            taken[port].add(free)
    return out


def terminal_text(w: Wire, conductor: str, side: str) -> str:
    return (w.terminals.get(conductor) or {}).get(side, "")


def wire_end_terminal(sheet: Sheet, w: Wire, conductor: str, side: str) -> str:
    """Svorka na konci žíly: ruční z `Wire.terminals`, jinak odvozená z čísel svorkového prvku."""
    t = terminal_text(w, conductor, side)
    if t:
        return t
    end = w.a if side == "a" else w.b
    try:
        e = sheet.element(end.element_id)
    except KeyError:
        return ""
    if not is_terminal_block(e):
        return ""
    slots = sorted({c for ww in sheet.wires for end2 in (ww.a, ww.b) if end2.element_id == e.id
                    for c in wire_conductors(ww)}, key=canon_key)
    return terminal_designation(e, slots, conductor)


def auto_number_terminal_blocks(sheet: Sheet) -> dict[str, str]:
    """Doplní čísla svorek skupinám (prvky sb.terminal_block / fve.terminal) bez atributu `terminal`:
    v každé svorkovnici (ref) pokračuje za nejvyšším použitým číslem. Vrací {element_id: "1 2 3 4 5"}."""
    highest: dict[str, int] = {}
    groups: list[tuple[Element, list[str]]] = []
    for e in sheet.elements:
        if not is_terminal_block(e) or not e.ref:
            continue
        slots = sorted({c for w in sheet.wires for end in (w.a, w.b) if end.element_id == e.id
                        for c in wire_conductors(w)}, key=canon_key) or ["L1"]
        nums = terminal_numbers(e, len(slots))
        if any(nums):
            for x in nums:
                if x.isdigit():
                    highest[e.ref] = max(highest.get(e.ref, 0), int(x))
        else:
            groups.append((e, slots))
    out: dict[str, str] = {}
    for e, slots in groups:
        start = highest.get(e.ref, 0) + 1
        out[e.id] = " ".join(str(start + i) for i in range(len(slots)))
        highest[e.ref] = start + len(slots) - 1
    return out


def auto_number_terminals(sheet: Sheet) -> dict[str, dict[str, dict[str, str]]]:
    """Navrhne číslování svorek: pro každý svorkový prvek (X…) očísluje žíly napojených vodičů 1, 2, 3…
    v pořadí vodičů na listu. Už vyplněné svorky zůstávají. Vrací {wire_id: nové terminals} jen pro změněné."""
    counters: dict[str, int] = {}
    used: dict[str, set[str]] = {}
    for w in sheet.wires:  # nejdřív posbírat obsazená čísla
        for c, t in w.terminals.items():
            for side in ("a", "b"):
                v = t.get(side, "")
                if ":" in v:
                    used.setdefault(v.split(":")[0], set()).add(v.split(":", 1)[1])
    result: dict[str, dict[str, dict[str, str]]] = {}
    for w in sheet.wires:
        new = {c: dict(t) for c, t in w.terminals.items()}
        changed = False
        for side, end in (("a", w.a), ("b", w.b)):
            try:
                el = sheet.element(end.element_id)
            except KeyError:
                continue
            if el.symbol_id not in TERMINAL_SYMBOLS or is_terminal_block(el) or not el.ref:
                continue
            for c in wire_conductors(w):
                if new.get(c, {}).get(side):
                    continue
                n = counters.get(el.ref, 0)
                while True:
                    n += 1
                    if str(n) not in used.get(el.ref, set()):
                        break
                counters[el.ref] = n
                used.setdefault(el.ref, set()).add(str(n))
                new.setdefault(c, {})[side] = f"{el.ref}:{n}"
                changed = True
        if changed:
            result[w.id] = new
    return result


# průchozí přístroje s pólovým číslováním 1/2, 3/4, 5/6 (jistič, odpínač, stykač…): porty „1“ (vstup) a „2“ (výstup)
POLE_NUMBERED_PORTS = ("1", "2")
# prvky s porty „1“, „2“…, které nejsou průchozí přístroje (odbočky sběrnice, svorky PE lišty, svorkové prvky)
NOT_POLE_NUMBERED = TERMINAL_SYMBOLS | TERMINAL_BLOCK_SYMBOLS | {"sb.busbar", "sb.junction"}
UNSWITCHED_POLES = {"N"} | NEVER_SWITCHED


def port_conductors(sheet: Sheet, element_id: str, port: str) -> list[str]:
    """Žíly všech vodičů listu napojených na port prvku (kanonické pořadí, bez duplicit)."""
    return sorted({c for w in sheet.wires for end in (w.a, w.b)
                   if end.element_id == element_id and end.port == port for c in wire_conductors(w)}, key=canon_key)


def device_terminal(sheet: Sheet, w: Wire, conductor: str, side: str) -> tuple[str, bool]:
    """Svorka konce žíly „F2:3“ a příznak, zda je odvozená pravidlem.

    Pořadí: ruční přiřazení z `Wire.terminals`; svorkový prvek přes `wire_end_terminal` (čísla svorek skupiny);
    průchozí přístroj s porty 1/2 → pól k (pořadí fázové žíly mezi žilami portu) = vstup 2k+1 / výstup 2k+2;
    spínaný N (přístroj má pól navíc – 4p jistič/vypínač, 1p+N) je další pól za fázemi (IEC 60947-1 příl. L,
    číslování hlavních pólů 1/2, 3/4, 5/6, 7/8 → 4p: N = 7/8); nespínaný N a PE/PEN = jméno žíly („F2:N“) –
    odvozeno=True; jinak jméno portu („F1:L“)."""
    t = terminal_text(w, conductor, side)
    if t:
        return t, False
    end = w.a if side == "a" else w.b
    try:
        e = sheet.element(end.element_id)
    except KeyError:
        return end.port, False
    name = element_name(e)
    if is_terminal_block(e):
        t = wire_end_terminal(sheet, w, conductor, side)
        return (t or f"{name}:{end.port}"), False
    if e.symbol_id in TERMINAL_SCHEME_SYMBOLS:       # elektroměr na MTP: svorka podle DIN 43856 („P1:3“)
        conds = {c for x in sheet.wires for p in (x.a, x.b) if p.element_id == e.id for c in wire_conductors(x)}
        spec = terminal_scheme(conds, TERMINAL_SCHEME_SYMBOLS[e.symbol_id])
        if spec is not None:
            return f"{name}:{spec['conductors'][conductor]}", True
    if e.symbol_id not in NOT_POLE_NUMBERED and end.port in POLE_NUMBERED_PORTS:
        phases = [c for c in port_conductors(sheet, e.id, end.port) if c not in UNSWITCHED_POLES]
        if conductor in NEVER_SWITCHED or (conductor == "N" and len(phases) >= e.poles):
            return f"{name}:{conductor}", True
        if conductor == "N":
            k = len(phases)                       # spínaný N = pól za fázemi
        else:
            k = phases.index(conductor) if conductor in phases else 0
        return f"{name}:{2 * k + 1 + POLE_NUMBERED_PORTS.index(end.port)}", True
    return f"{name}:{end.port}", False


# ---- geometrie pohledu (sdílí ji vícepólová scéna v ui/ a kontrola překryvů textů) ------------------------------
MP_X0 = 42.5          # začátek rozmístění – vlevo názvy potenciálů sběrnice a odkazy na sousední strany
MP_X0_NO_BUS = 35.0   # začátek rozmístění listu bez sběrnice (na A4 na šířku se vejdou 3 stringy DC vedle sebe)
MP_Y_TOP = 60.0       # odstup první řady od horního okraje listu (nahoře nadpis rozvaděče)
MP_PAGE_GAP = 20.0    # mezera mezi stranami pod sebou
LABEL_GAP = 1.5       # odstup popisku od značky


MIN_COL_GAP = 10.0    # nejmenší mezera mezi sloupci při zhuštění na nízkou stranu (A4 na šířku)

# ---- formát stran vícepólu a plánu svorkovnice listu rozvaděče ---------------------------------------------------
# volba („A4“ výchozí) ve firemním standardu `standard.switchboard_paper` nebo u listu `Sheet.mp_paper`
SWITCHBOARD_PAPERS = {"A4": (297.0, 210.0), "A4 na výšku": (210.0, 297.0), "A3": (420.0, 297.0),
                      "A2": (594.0, 420.0), "A1": (841.0, 594.0)}
DEFAULT_SWITCHBOARD_PAPER = "A4"
# volný A4: výška 297 mm, šířka podle obsahu v násobcích 210 mm (A4×n) – vícepól na jedné straně bez přerušení
FREE_A4 = "volný A4"
FREE_A4_STEP = 210.0
FREE_A4_HEIGHT = 297.0
FREE_A4_LAYOUT_W = 40 * FREE_A4_STEP     # šířka pro první průchod rozmístění (změří se skutečná šířka kresby)
# nabídka v GUI (vlastnosti listu, firemní standard); „A4 na výšku“ zůstává platná pro starší projekty
PAPER_CHOICES = ("A4", "A3", "A2", "A1", FREE_A4)
SHEET_PAPER = "list"      # strana = rozměr listu (`Sheet.width × height`, chování do 10/2026)
_DEFAULT_SHEET_SIZE = ("A3", 420.0, 297.0)


def normalize_switchboard_paper(value: object) -> str:
    """Platný formát stran schématu rozvaděče (`SWITCHBOARD_PAPERS`), jinak výchozí A4 na šířku. Hodnotu firemního
    standardu (`standard.switchboard_paper`) čte `envocad.settings.switchboard_paper` – model nastavení nečte,
    funkce níže dostávají standard parametrem `standard_paper` od volajícího (GUI, export, generátor)."""
    v = str(value or "").strip()
    return v if v in SWITCHBOARD_PAPERS or v == FREE_A4 else DEFAULT_SWITCHBOARD_PAPER


def free_a4_label(width: float) -> str:
    """Popis volného A4 do popisového pole podle šířky: 420 → „A4×2“."""
    return f"A4×{max(1, round(width / FREE_A4_STEP))}"


def free_a4_width(needed: float) -> float:
    """Nejmenší šířka volného A4 (násobek 210 mm), do které se vejde `needed` mm."""
    return max(1, -(-needed // FREE_A4_STEP)) * FREE_A4_STEP


def paper_choice(sheet: Sheet, standard_paper: str = DEFAULT_SWITCHBOARD_PAPER) -> str:
    """Formát stran vícepólu listu: „A4“, „A4 na výšku“, „A3“ nebo „list“ (rozměr listu).

    Pořadí: volba listu `mp_paper`; list, který není rozvaděč (vícepól JPS), a list rozvaděče s ručně nastaveným
    formátem (jiný než výchozí A3 420 × 297) nebo s ručními polohami ve vícepólu (`mp_pos` jsou v souřadnicích
    stran původního rozměru) bez volby → „list“ (beze změny proti dřívějšku); jinak firemní standard `standard_paper`
    (výchozí A4; neplatná hodnota → A4)."""
    v = getattr(sheet, "mp_paper", "") or ""
    if v in SWITCHBOARD_PAPERS or v in (SHEET_PAPER, FREE_A4):
        return v
    if not sheet.is_switchboard:
        return SHEET_PAPER
    if (sheet.paper, float(sheet.width), float(sheet.height)) != _DEFAULT_SHEET_SIZE \
            or any(e.mp_pos for e in sheet.elements):
        return SHEET_PAPER
    return normalize_switchboard_paper(standard_paper)


def page_size(sheet: Sheet, choice: str | None = None,
              standard_paper: str = DEFAULT_SWITCHBOARD_PAPER) -> tuple[float, float]:
    """Rozměr strany vícepólu / plánu svorkovnice (šířka, výška v mm). Volný A4 = výchozí A4×2 (plán svorkovnice);
    skutečnou šířku strany vícepólu dopočítá `multipole_geometry` podle kresby (`MultipoleGeometry.page_size`)."""
    v = choice or paper_choice(sheet, standard_paper)
    if v == FREE_A4:
        return (2 * FREE_A4_STEP, FREE_A4_HEIGHT)
    return (float(sheet.width), float(sheet.height)) if v == SHEET_PAPER else SWITCHBOARD_PAPERS[v]


def page_paper_label(sheet: Sheet, choice: str | None = None, standard_paper: str = DEFAULT_SWITCHBOARD_PAPER) -> str:
    """Formát strany do popisového pole („A4“; u rozměru listu jeho formát)."""
    v = choice or paper_choice(sheet, standard_paper)
    if v == FREE_A4:
        return free_a4_label(page_size(sheet, v)[0])
    return sheet.paper if v == SHEET_PAPER else v.split()[0]


def layout_x0(sheet: Sheet, choice: str | None = None) -> float:
    """Začátek rozmístění vícepólu (levý okraj strany 0): se sběrnicí místo vlevo pro názvy potenciálů a odkazy,
    bez ní užší okraj; formát „list“ beze změny proti dřívějšku. Na firemním standardu nezávisí (standard nikdy není
    „list“)."""
    v = choice or paper_choice(sheet)
    if v == SHEET_PAPER or any(e.symbol_id == BUS_SYMBOL for e in sheet.elements):
        return MP_X0
    return MP_X0_NO_BUS


def page_width(sheet: Sheet, size: tuple[float, float] | None = None,
               standard_paper: str = DEFAULT_SWITCHBOARD_PAPER) -> float:
    """Použitelná šířka strany vícepólu pro rozmístění (od `layout_x0` po 10 mm před vnitřním rámečkem)."""
    from envocad.model.frame import MARGIN
    w = (size or page_size(sheet, standard_paper=standard_paper))[0]
    return w - layout_x0(sheet) - MARGIN - 10.0


def page_pitch(sheet: Sheet, size: tuple[float, float] | None = None,
               standard_paper: str = DEFAULT_SWITCHBOARD_PAPER) -> float:
    return (size or page_size(sheet, standard_paper=standard_paper))[1] + MP_PAGE_GAP


def page_ref(sheet_no: str, k: int, x: float, y_local: float, size: tuple[float, float]) -> str:
    """Křížový odkaz na místo na straně k vícepólu: „/list.strana.sloupecřádek“ (např. „/2.3.B4“); `y_local` =
    souřadnice y uvnitř strany (jako na straně 0)."""
    from envocad.model.frame import grid_coord
    return f"/{sheet_no}.{k + 1}.{grid_coord(None, x, y_local, size[0], size[1])}"


def paginate(sheet: Sheet, poles: dict[str, ElementPoles], size: tuple[float, float] | None = None,
             standard_paper: str = DEFAULT_SWITCHBOARD_PAPER) -> tuple[dict[str, int], int]:
    """Rozmístění (strany za sebou v x) → strany pod sebou: prvek na straně k se posune o k·šířka doleva a o
    k·(výška + mezera) dolů (mění `origin`). Ruční pozice (`mp_pos`) jsou už stránkované – strana se jim jen určí.
    Vrací (prvek → strana, počet stran)."""
    size = size or page_size(sheet, standard_paper=standard_paper)
    x0, pw, pitch = layout_x0(sheet), page_width(sheet, size), page_pitch(sheet, size)
    page_of: dict[str, int] = {}
    n_pages = 1
    for eid, ep in poles.items():
        x, y = ep.origin
        if ep.element.mp_pos:
            k = max(0, int((size[1] - y) // pitch))
        else:
            k = max(0, int((x - x0) // pw))
            ep.origin = (x - k * pw, y - k * pitch)
        page_of[eid] = k
        n_pages = max(n_pages, k + 1)
    return page_of, n_pages


@dataclass(frozen=True)
class Bridge:
    """Můstek svorkovnice ve vícepólu na jedné straně: čárkovaná čára přes středy svorek posunuté k portu 1."""
    strip: str                                  # označení svorkovnice (X2)
    group: tuple[str, ...]                      # čísla svorek skupiny můstku (celá skupina, i z jiných stran)
    page: int
    pts: tuple[tuple[float, float], ...]        # body na svorkách této strany (souřadnice pohledu), zleva


def bridge_paths(sheet: Sheet, poles: dict[str, ElementPoles], page_of: dict[str, int]) -> list[Bridge]:
    """Můstky svorkovnic listu (`Sheet.bridges`): spojí středy svorek se stejným označením X:n, posunuté ke straně
    portu 1. Každá skupina v jiné vzdálenosti (2 mm + 0,6 mm × pořadí, po šesti dokola), aby se nepřekrývaly;
    přes hranici stran se můstek kreslí po stranách zvlášť (strana s jedinou svorkou skupiny nic). Polohy pólů
    (`ElementPoles.origin`) musí být už po rozmístění a stránkování."""
    pos: dict[tuple[str, str], tuple[float, float, float, float, int]] = {}   # (x, y, směr k portu 1, strana)
    for ep in poles.values():
        e = ep.element
        if not is_terminal_block(e) or not ep.per_pole:
            continue
        nums = terminal_numbers(e, len(ep.slots))
        px, py = e.port_pos(ep.symbol, ep.through[0] if ep.through else ep.symbol.ports[0].name)
        dx, dy = px - e.x, py - e.y
        n = (dx * dx + dy * dy) ** 0.5 or 1.0
        for c, num in zip(ep.slots, nums):
            if num:
                ox, oy = ep.pole_offset(c)
                pos[(e.ref, num)] = (ep.origin[0] + ox, ep.origin[1] + oy, dx / n, dy / n, page_of.get(e.id, 0))
    out: list[Bridge] = []
    for strip, groups in sheet.bridges.items():
        for gi, g in enumerate(groups):
            hits = [pos[(strip, n)] for n in g if (strip, n) in pos]
            if len(hits) < 2:
                continue
            off = 2.0 + 0.6 * (gi % 6)
            for k in sorted({h[4] for h in hits}):
                part = [h for h in hits if h[4] == k]
                if len(part) < 2:
                    continue
                pts = sorted((x + ux * off, y + uy * off) for x, y, ux, uy, _k in part)
                out.append(Bridge(strip, tuple(g), k, tuple(pts)))
    return out


def pe_join_ports(ep: ElementPoles) -> list[tuple[str, list[str]]]:
    """Porty průchozího prvku, na kterých je jen ochranný vodič (PE/PEN), který prvek nespíná ani nevede kolem –
    svodič přepětí (SPD): konce všech pólů na portu PE se spojí příčkou a PE vodič začíná na ní. Vrací
    [(port, [PE…])]."""
    if not (ep.per_pole and ep.through and ep.switched) or ep.element.symbol_id in FEED_SYMBOLS:
        return []
    out = []
    for port in ep.through:
        conds = ep.per_port.get(port, set())
        if conds and all(c in NEVER_SWITCHED and c not in ep.switched and c not in ep.bypass for c in conds):
            out.append((port, sorted(conds, key=canon_key)))
    return out


def pe_join_segments(ep: ElementPoles) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Příčky `pe_join_ports`: od konce prvního do konce posledního pólu včetně místa, kde začíná PE vodič."""
    out = []
    for port, conds in pe_join_ports(ep):
        pts = [ep.pole_pos(port, c) for c in [*ep.switched, *conds]]
        pts.sort()
        if pts[0] != pts[-1]:
            out.append((pts[0], pts[-1]))
    return out


def _rot_box(sym: Symbol, x: float, y: float, rotation: int) -> tuple[float, float, float, float]:
    from envocad.model.symbol import rotate_point
    x0, y0, x1, y1 = sym.bounds()
    pts = [rotate_point(px, py, rotation) for px, py in ((x0, y0), (x1, y1), (x0, y1), (x1, y0))]
    return (x + min(p[0] for p in pts), y + min(p[1] for p in pts), x + max(p[0] for p in pts), y + max(p[1] for p in pts))


def pole_symbol_for(ep: ElementPoles, conductor: str | None) -> Symbol:
    """Značka pólu (`Symbol.pole_symbol`) – u MTP se sekundárem po fázích s příčkou sekundáru (`secondary.draw`)."""
    if not conductor:
        return ep.symbol
    sym = ep.symbol.pole_symbol()
    draw = ((ep.symbol.multipole or {}).get("secondary") or {}).get("draw")
    if draw and ep.secondary_used:
        sym = dataclasses.replace(sym, primitives=[*sym.primitives, *draw])
    return sym


def pole_anchor(ep: ElementPoles, conductor: str | None) -> tuple[float, float]:
    """Poloha položky pólu ve vícepólu (model mm) – počátek značky pólu."""
    ox, oy = ep.pole_offset(conductor) if conductor else (0.0, 0.0)
    return (ep.origin[0] + ox, ep.origin[1] + oy)


def pole_label_texts(ep: ElementPoles) -> list[tuple[str, float]]:
    """Řádky popisku prvku ve vícepólu: označení (2,5 mm) a zobrazené atributy (2 mm); u skupiny svorek bez čísel."""
    e = ep.element
    lines = [(e.ref, 2.5)] if e.ref else []
    skip = {"ref", "terminal"} if is_terminal_block(e) else {"ref"}   # čísla svorek jsou u pólů
    lines += [(a.display(e.attrs[a.key]), 2.0) for a in ep.symbol.label_attributes(e.attrs, skip)]
    return lines


def pole_label_lines(ep: ElementPoles) -> list[tuple[float, float, str, float, str]]:
    """Popisek prvku ve vícepólu: [(x, y, text, výška, zarovnání)] v souřadnicích pohledu (mm, Y nahoru), texty
    vždy vodorovně. Přívod/vývod: označení svorkovnice vlevo u svorek. Vícepólový přístroj se svislým tokem
    (póly vedle sebe): vlevo od prvního pólu zarovnaný doprava, horní řádek u horního okraje pólů – nepřeškrtne
    žílu prvního pólu ani nevede přes přívodní žíly nad prvkem. Skupina svorek: nad můstky. Jednopólový prvek:
    poloha popisku značky. Přesunutý popisek (`ep.label_lines`) má přednost."""
    if ep.label_lines is not None:
        ox, oy = ep.origin
        return [(ox + dx, oy + dy, text, h, align) for dx, dy, text, h, align in ep.label_lines]
    return default_label_lines(ep)


def default_label_lines(ep: ElementPoles) -> list[tuple[float, float, str, float, str]]:
    """Výchozí poloha popisku prvku (viz `pole_label_lines`)."""
    from envocad.model.symbol import rotate_point
    e = ep.element
    c0 = ep.switched[0] if ep.per_pole and ep.switched else None
    sym = pole_symbol_for(ep, c0)
    px, py = pole_anchor(ep, c0)

    def at(lx: float, ly: float) -> tuple[float, float]:
        rx, ry = rotate_point(lx, ly, e.rotation)
        return (px + rx, py + ry)

    if is_feed(e):
        if not e.ref:
            return []
        # vlevo u svorky; přívod je ve vícepólu v souřadnicích starého `sb.feed_in` (`feed.multipole_feed_view`)
        cy = -2.5 if feed_dir(e) == "in" else 2.5
        x, y = at(-2.5, cy - 0.8)
        return [(x, y, e.ref, 2.5, "right")]
    lines = pole_label_texts(ep)
    if not lines:
        return []
    multi = len(ep.switched) > 1
    if multi and not is_terminal_block(e) and not _flow_is_horizontal_for(ep):
        boxes = [_rot_box(sym, *pole_anchor(ep, c), e.rotation) for c in ep.switched]
        x = min(b[0] for b in boxes) - LABEL_GAP
        y = max(b[3] for b in boxes) - lines[0][1]
        # dlouhý popisek (SPD: typ, Uc, Up, ISCPV) nesmí sahat pod spodní porty – tam vede PE / vývodní žíly;
        # posune se nahoru, aby poslední řádek ležel nad spodním okrajem pólů
        stack = sum(h + 1.0 for _, h in lines[1:])
        y = max(y, min(b[1] for b in boxes) + 1.5 + stack)
        out = []
        for text, h in lines:
            out.append((x, y, text, h, "right"))
            y -= h + 1.0
        return out
    if multi:
        x0, y0, _x1, y1 = sym.bounds()
        stack = sum(h + 1.0 for _, h in lines[1:])
        if e.rotation == 270 and not is_terminal_block(e):
            lx, ly = x0, y0 - 1.5 - (stack + 2.5)
        else:
            lx, ly = x0, y1 + (7.5 if is_terminal_block(e) else 1.5)   # nad můstky
            if e.symbol_id in ("sb.terminal_block", "fve.terminal"):
                lx -= 3.5   # vedle svislé čáry svorky, ne přes ni
    else:
        lx, ly = sym.label_pos
        stack = 0.0
    x, y = at(lx, ly)
    out = []
    for text, h in lines:
        out.append((x, y + stack, text, h, "left"))
        stack -= h + 1.0
    return out


DIR_VEC = {"N": (0, 1), "E": (1, 0), "S": (0, -1), "W": (-1, 0)}



BREAK_PITCH = 2.5      # rozteč přerušení žil na okraji strany


def break_y(p: tuple[float, float], d: str, n: int, used: set[float], lo: float | None = None) -> float:
    """Výška (mm, Y nahoru) vodorovného úseku k přerušovacímu bodu na okraji strany; `used` = výšky přerušení, která
    už na okraji jsou (doplní se o vrácenou výšku); `n` (pořadí přerušení na okraji) se už nepoužívá.
    Port E/W: v úrovni portu, je-li volná (žíly v různých výškách – sekundár MTP), jinak první volná níž.
    Port N/S: úsek vede za vývodem portu ven od přístroje (nad / pod něj) – ne v úrovni portu, kde by šel přes
    sousední svorky, jejich čísla a vlastní značku; další přerušení dál ven po dvou roztečích (souběžné úseky
    k pólům – mezi ně se vejde popisek žíly), u portu S po jedné, kdyby dvojí rozteč sjela pod `lo`.
    `lo` = nejnižší povolená výška (spodní okraj kresby strany): port E/W pak pokračuje nad úrovní portu."""
    if d in ("N", "S"):
        out = 1.0 if d == "N" else -1.0
        for k in (2, 1):
            step = k * BREAK_PITCH
            y = p[1] + out * GRID
            while any(abs(y - u) < step - 1e-6 for u in used):
                y += out * step
            if d == "N" or lo is None or y >= lo:
                break
    else:
        y = p[1]
        while any(abs(y - u) < BREAK_PITCH - 1e-6 for u in used):
            y -= BREAK_PITCH
        if lo is not None and y < lo:
            # pod spodní okraj strany ne – další přerušení nad úrovní portu (první volná výška)
            y = p[1] + BREAK_PITCH
            while any(abs(y - u) < BREAK_PITCH - 1e-6 for u in used):
                y += BREAK_PITCH
    used.add(y)
    return y


BRANCH_CHAMFER = GRID / 2   # zkosení odbočky ze svorky (45°), jako uzel „T“ se směrem v EPLAN


def branch_ends(sheet: Sheet, poles: dict[str, ElementPoles]) -> set[tuple[str, str]]:
    """Konce vodičů, které jsou na svorce přístroje druhým vodičem (dvojitá dutinka): (id vodiče, „a“/„b“).

    Ze stejného portu prvku vede víc vodičů (odpínač → vývod a → SPD): hlavní je ten, jehož protější pól leží
    nejvíc v ose portu (pokračuje rovně), ostatní jsou odbočky – kreslí se ze svorky hned za vývodem se zkoseným
    rohem, aby bylo vidět, že začínají na svorce, a ne v uzlu na čáře. Svorkovnice a sběrnice se nepočítají."""
    groups: dict[tuple[str, str], list[tuple[float, str, str]]] = {}
    for w in sheet.wires:
        ea, eb = poles.get(w.a.element_id), poles.get(w.b.element_id)
        if not ea or not eb or BUS_SYMBOL in (ea.element.symbol_id, eb.element.symbol_id):
            continue
        c = wire_conductors(w)[0]
        for side, me, end, other, oend in (("a", ea, w.a, eb, w.b), ("b", eb, w.b, ea, w.a)):
            if is_terminal_block(me.element) or me.element.symbol_id == "sb.pe_bar":
                continue
            try:
                d = rotate_dir(me.symbol.port(end.port).dir, me.element.rotation)
                px, py = me.pole_pos(end.port, c)
                qx, qy = other.pole_pos(oend.port, c)
            except (KeyError, StopIteration):
                continue
            off = abs(qx - px) if d in ("N", "S") else abs(qy - py)
            groups.setdefault((me.element.id, end.port), []).append((off, w.id, side))
    out: set[tuple[str, str]] = set()
    for ends in groups.values():
        if len(ends) < 2:
            continue
        ends.sort()
        out |= {(wid, side) for _off, wid, side in ends[1:]}
    return out


def conductor_route(pa: tuple[float, float], da: str, pb: tuple[float, float], db: str, stagger: float = 0.0,
                    jog: float = 0.8, branch: bool = False) -> list[tuple[float, float]]:
    """Trasa žíly ve vícepólu (model mm, Y nahoru): vývod GRID z každého portu, L/Z vedení, příčka Z-trasy v `jog`
    délky (blízko cíle) posunutá o `stagger` (rovnoběžné žíly se nepřekrývají). Stejně kreslí scéna i kontrola.
    `branch` = odbočka ze svorky v `pa` (`branch_ends`): příčka hned za vývodem, roh zkosený pod 45°."""
    stub = GRID
    va, vb = DIR_VEC[da], DIR_VEC[db]
    sa = (pa[0] + va[0] * stub, pa[1] + va[1] * stub)
    sb = (pb[0] + vb[0] * stub, pb[1] + vb[1] * stub)
    pts = [pa, sa]
    horizontal_first = da in ("E", "W")
    if branch and not horizontal_first and db in ("N", "S") and abs(sa[0] - sb[0]) > 1e-6:
        # odbočky žil jednoho vodiče po 2 × `stagger` – mezi příčky se vejde popisek žíly
        my = sa[1] - 2 * stagger if da == "S" else sa[1] + 2 * stagger
        ch = BRANCH_CHAMFER
        sx = 1.0 if sb[0] > sa[0] else -1.0
        return [pa, (sa[0], my - va[1] * ch), (sa[0] + sx * ch, my), (sb[0], my), sb, pb]
    if branch and horizontal_first and db in ("E", "W") and abs(sa[1] - sb[1]) > 1e-6:
        mx = sa[0] + 2 * stagger if da == "E" else sa[0] - 2 * stagger
        ch = BRANCH_CHAMFER
        sy = 1.0 if sb[1] > sa[1] else -1.0
        return [pa, (mx - va[0] * ch, sa[1]), (mx, sa[1] + sy * ch), (mx, sb[1]), sb, pb]
    if horizontal_first and db in ("E", "W") and abs(sa[1] - sb[1]) > 1e-6:
        mx = _snap(sa[0] + (sb[0] - sa[0]) * jog) + stagger
        pts += [(mx, sa[1]), (mx, sb[1])]
    elif not horizontal_first and db in ("N", "S") and abs(sa[0] - sb[0]) > 1e-6:
        my = _snap(sa[1] + (sb[1] - sa[1]) * jog) - stagger   # scéna má Y dolů: posun +stagger tam = −stagger tady
        pts += [(sa[0], my), (sb[0], my)]
    elif horizontal_first:
        pts.append((sb[0], sa[1]))
    else:
        pts.append((sa[0], sb[1]))
    pts += [sb, pb]
    return pts


def branch_side(branches: set[tuple[str, str]], wire_id: str) -> str:
    """„a“/„b“, když je konec vodiče odbočkou ze svorky (`branch_ends`), jinak „“ (oba konce → „a“)."""
    return "a" if (wire_id, "a") in branches else "b" if (wire_id, "b") in branches else ""


def wire_route(pa: tuple[float, float], da: str, pb: tuple[float, float], db: str, stagger: float = 0.0,
               branch: str = "", jog: float = 0.8) -> list[tuple[float, float]]:
    """Trasa žíly mezi póly (`conductor_route`, příčka Z v `jog` délky, výchozí 0,8 – blízko cíle); `branch` „a“/„b“
    = ten konec je odbočka ze svorky (`branch_ends`) – trasa se spočítá od něj a obrátí, aby body šly vždy od `pa`
    k `pb`."""
    if branch == "b":
        return conductor_route(pb, db, pa, da, stagger=stagger, jog=jog, branch=True)[::-1]
    return conductor_route(pa, da, pb, db, stagger=stagger, jog=jog, branch=branch == "a")


ROUTE_JOGS = (0.8, 0.5, 0.2, 0.65, 0.35, 0.9, 0.1)   # výšky příčky Z-trasy, které se zkoušejí (první = výchozí)
# výšky pro společnou příčku žil vodiče (`wire_jog`): nejdřív `ROUTE_JOGS`, pak jemněji po 5 %
WIRE_JOGS = ROUTE_JOGS + tuple(j / 20 for j in range(1, 20) if j / 20 not in ROUTE_JOGS)
# trasy se dvěma lomy (`clear_route`) se zkoušejí jen u žil přes cizí značku


def _segment_hits_box(a, b, box, pad: float = 0.6) -> bool:
    """Vede vodorovný / svislý úsek žíly přes vnitřek obálky značky (okraj `pad` – vývod k portu se nepočítá)?"""
    x0, y0, x1, y1 = box[0] + pad, box[1] + pad, box[2] - pad, box[3] - pad
    if x1 <= x0 or y1 <= y0:
        return False
    (ax, ay), (bx, by) = a, b
    if abs(ay - by) < 1e-6:
        return y0 < ay < y1 and max(ax, bx) > x0 and min(ax, bx) < x1
    if abs(ax - bx) < 1e-6:
        return x0 < ax < x1 and max(ay, by) > y0 and min(ay, by) < y1
    return False


def route_hits(pts: list[tuple[float, float]], boxes) -> int:
    """Počet úseků trasy vedených přes obálky značek `boxes`."""
    return sum(1 for a, b in pairwise(pts) for box in boxes if _segment_hits_box(a, b, box))


def _route_len(pts) -> float:
    return sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in pairwise(pts))


def _clean_path(pts) -> bool:
    """Trasa bez otočky o 180° a bez úseku vedeného po jiném úseku téže trasy (žíla se nevrací po sobě)."""
    q = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    dirs = []
    for a, b in pairwise(q):
        dx, dy = b[0] - a[0], b[1] - a[1]
        dirs.append(((dx > 0) - (dx < 0), (dy > 0) - (dy < 0)))
    for d1, d2 in pairwise(dirs):
        if d1[0] == -d2[0] and d1[1] == -d2[1]:
            return False
    segs = list(pairwise(q))
    for i, (a, b) in enumerate(segs):
        for c, d in segs[i + 2:]:
            vert = abs(a[0] - b[0]) < 1e-6 and abs(c[0] - d[0]) < 1e-6 and abs(a[0] - c[0]) < 1e-6
            horz = abs(a[1] - b[1]) < 1e-6 and abs(c[1] - d[1]) < 1e-6 and abs(a[1] - c[1]) < 1e-6
            k = 1 if vert else 0
            if (vert or horz) and min(max(a[k], b[k]), max(c[k], d[k])) - max(min(a[k], b[k]), min(c[k], d[k])) > 1e-6:
                return False
    return True


def _crossings(pts, segs) -> int:
    """Počet křížení úseků trasy (vodorovný × svislý, uvnitř obou) s úseky jiných žil `segs`."""
    n = 0
    for a, b in pairwise(pts):
        for c, d in segs:
            if abs(a[1] - b[1]) < 1e-6 and abs(c[0] - d[0]) < 1e-6:
                h, v = (a, b), (c, d)
            elif abs(a[0] - b[0]) < 1e-6 and abs(c[1] - d[1]) < 1e-6:
                h, v = (c, d), (a, b)
            else:
                continue
            x, y = v[0][0], h[0][1]
            if min(h[0][0], h[1][0]) + 1e-6 < x < max(h[0][0], h[1][0]) - 1e-6 \
                    and min(v[0][1], v[1][1]) + 1e-6 < y < max(v[0][1], v[1][1]) - 1e-6:
                n += 1
    return n


def _overlaps(pts, segs) -> int:
    """Počet úseků trasy, které leží na úseku jiné žíly `segs` (stejná přímka, společná délka > 0) – vypadalo by
    to jako spojení žil."""
    n = 0
    for a, b in pairwise(pts):
        for c, d in segs:
            if abs(a[1] - b[1]) < 1e-6 and abs(c[1] - d[1]) < 1e-6 and abs(a[1] - c[1]) < 1e-6:
                lo, hi = max(min(a[0], b[0]), min(c[0], d[0])), min(max(a[0], b[0]), max(c[0], d[0]))
            elif abs(a[0] - b[0]) < 1e-6 and abs(c[0] - d[0]) < 1e-6 and abs(a[0] - c[0]) < 1e-6:
                lo, hi = max(min(a[1], b[1]), min(c[1], d[1])), min(max(a[1], b[1]), max(c[1], d[1]))
            else:
                continue
            if hi - lo > 1e-6:
                n += 1
    return n


def wire_jog(ends, branch: str = "", segs=()) -> tuple[float, bool]:
    """Společná výška příčky Z-trasy žil jednoho vodiče a pořadí posunu příček: `ends` = [(pa, da, pb, db)] po
    žilách. Výchozí `ROUTE_JOGS[0]` (blízko cíle), posun `i · GRID`. Když by příčka posledních žil přejela za cíl
    a žíla se vracela po svorkách (krátký úsek, mnoho žil – elektroměr se svorkami), nebo se žíly vodiče navzájem
    kříží (žíly se rozbíhají na svorky v jiném rozestupu), nebo by ležely na úsecích už nakreslených žil `segs`
    (dva vodiče na svorky jednoho přístroje), vybere výšku a obrácené pořadí posunu (`(n − 1 − i) · GRID`), kde
    jsou všechny žíly čisté, nic se nepřekrývá a křížení mezi nimi je nejméně. (jog, obráceně)"""
    if branch or len(ends) < 2:
        return ROUTE_JOGS[0], False
    n = len(ends)
    best = None
    for k, jog in enumerate(WIRE_JOGS):
        for rev in (False, True):
            routes = [wire_route(pa, da, pb, db, stagger=((n - 1 - i) if rev else i) * GRID, jog=jog)
                      for i, (pa, da, pb, db) in enumerate(ends)]
            if not all(_clean_path(r) for r in routes):
                continue
            own = [list(pairwise(r)) for r in routes]
            cross = sum(_crossings(r, s) for i, r in enumerate(routes) for s in own[i + 1:])
            over = sum(_overlaps(r, segs) for r in routes)
            key = (over, cross + sum(_crossings(r, segs) for r in routes), k, rev)
            if best is None or key < best[0]:
                best = (key, jog, rev)
            if over == 0 and cross == 0 and k == 0 and not rev:
                return jog, rev          # výchozí trasa je v pořádku
    return (best[1], best[2]) if best else (ROUTE_JOGS[0], False)


def clear_route(pa, da, pb, db, stagger: float = 0.0, branch: str = "", boxes=(),
                segs=(), labels=(), jog: float = ROUTE_JOGS[0]) -> list[tuple[float, float]]:
    """Trasa žíly, která co nejméně vede přes cizí značky (`boxes`). Výchozí trasa (`wire_route`), když nic nekříží;
    jinak jiné výšky příčky Z (`ROUTE_JOGS`) a trasy se dvěma lomy přes volný pruh (svisle – vodorovně – svisle
    v různých výškách, vodorovně – svisle – vodorovně v různých odstupech) – nejkratší bez přechodu, jinak s nejméně
    přechody (při shodě výchozí). Odbočka ze svorky (`branch`) zůstává, pokud nevede přes cizí značku."""
    base = wire_route(pa, da, pb, db, stagger=stagger, branch=branch, jog=jog)
    if not boxes or route_hits(base, boxes) == 0:
        return base                     # odbočka ze svorky jen když výchozí trasa vede přes značku
    cands = [wire_route(pa, da, pb, db, stagger=stagger, jog=j) for j in ROUTE_JOGS if j != jog]
    va, vb = DIR_VEC[da], DIR_VEC[db]
    sa = (pa[0] + va[0] * GRID, pa[1] + va[1] * GRID)
    sb = (pb[0] + vb[0] * GRID, pb[1] + vb[1] * GRID)
    lo_y, hi_y = min(sa[1], sb[1]), max(sa[1], sb[1])
    lo_x, hi_x = min(sa[0], sb[0]), max(sa[0], sb[0])
    ys = {_snap(lo_y + (hi_y - lo_y) * f) for f in (0.1, 0.3, 0.5, 0.7, 0.9)}
    ys |= {_snap(lo_y - k * GRID) for k in (2, 4, 8, 12)} | {_snap(hi_y + k * GRID) for k in (2, 4, 8, 12)}
    xs = {_snap(lo_x + (hi_x - lo_x) * f) for f in (0.1, 0.3, 0.5, 0.7, 0.9)}
    xs |= {_snap(lo_x - k * GRID) for k in (2, 4, 8, 12)} | {_snap(hi_x + k * GRID) for k in (2, 4, 8, 12)}
    off = stagger
    for y in ys:            # svisle – vodorovně – svisle
        cands.append([pa, sa, (sa[0], y - off), (sb[0], y - off), sb, pb])
    for x in xs:            # vodorovně – svisle – vodorovně
        cands.append([pa, sa, (x + off, sa[1]), (x + off, sb[1]), sb, pb])
    base_x = _crossings(base, segs)
    best = None
    for pts in cands:
        # objízdná trasa jen čistá: bez značky i popisku, bez otočky, nejvýš o 2 křížení víc než výchozí
        if not _clean_path(pts) or route_hits(pts, boxes) or route_hits(pts, labels):
            continue
        c = (_crossings(pts, segs), _route_len(pts))
        if c[0] <= base_x + 2 and (best is None or c < best[0]):
            best = (c, pts)
    if best is None:
        return base
    pts = best[1]
    return [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]


def label_boxes(poles: dict[str, ElementPoles]) -> dict[str, list[tuple[float, float, float, float]]]:
    """Obálky popisků prvků (`pole_label_lines`, odhad šířky textu) – objízdná trasa žíly je nesmí přeškrtnout."""
    out: dict[str, list[tuple[float, float, float, float]]] = {}
    for eid, ep in poles.items():
        if ep.element.symbol_id in (BUS_SYMBOL, JUNCTION_SYMBOL):
            continue
        for x, y, text, h, align in pole_label_lines(ep):
            w = len(text) * h * 0.62
            x0 = x - w if align == "right" else x - w / 2 if align == "center" else x
            out.setdefault(eid, []).append((x0 - 0.6, y - 0.4, x0 + w + 0.6, y + h + 0.4))
    return out


def obstacle_boxes(poles: dict[str, ElementPoles]) -> dict[str, list[tuple[float, float, float, float]]]:
    """Obálky značek prvků ve vícepólu (po pólech, souřadnice pohledu) pro vedení žil mimo cizí značky. Uzly
    a sběrnice nejsou překážka (žíly do nich vedou)."""
    out: dict[str, list[tuple[float, float, float, float]]] = {}
    for eid, ep in poles.items():
        if ep.element.symbol_id in (BUS_SYMBOL, JUNCTION_SYMBOL):
            continue
        for c in (list(ep.switched) if ep.per_pole else [None]):
            x, y = pole_anchor(ep, c)
            out.setdefault(eid, []).append(_rot_box(pole_symbol_for(ep, c), x, y, ep.element.rotation))
    return out


def conductor_label_anchor(pts: list[tuple[float, float]], staggered: bool) -> tuple[float, float, str, bool]:
    """Poloha popisku žíly (jako `geometry.wire_label_anchor`). U vodiče s více žilami vedenými Z-trasou
    (`staggered`) se příčka Z (rovnoběžné žíly jsou od sebe jen 2,5 mm) přeskočí a popisek jde na nejdelší jiný
    úsek – jinak by popisek jedné žíly ležel přes sousední žílu. Krátké úseky (< 6 mm) → výchozí poloha."""
    from envocad.model.geometry import wire_label_anchor
    if staggered and len(pts) == 6:
        segs = [(pts[i], pts[i + 1]) for i in (1, 3)]   # úseky mezi vývodem a příčkou (příčka = pts[2]–pts[3])
        a, b = max(segs, key=lambda s: abs(s[1][0] - s[0][0]) + abs(s[1][1] - s[0][1]))
        if abs(b[0] - a[0]) + abs(b[1] - a[1]) >= 6.0:
            return wire_label_anchor([a, b])
    return wire_label_anchor(pts)
