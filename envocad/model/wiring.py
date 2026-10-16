"""Výrobní data rozvaděče: vnitřní vodiče po žílách s průřezem, barvou, typem, délkou a koncovkami (bez Qt).

Návrh `docs/design/vyrobni_data.md`. Formát projektu se nemění – vstupem jsou nepovinné `Wire.attrs`
(`cross`, `cable`, `color`, `end_a`, `end_b`, `prod`) a klíče `wire_*` v `Layout.params`.

Délka se počítá z rozložení: souřadnice v mm, Y nahoru, počátek v levém horním rohu montážní plochy. Řada r má
osu `y = -(r + 0,5)·P` (P = rozteč řad), vodorovný žlab j leží na `y = -j·P` (žlab r nad řadou r, r+1 pod ní),
svislé žlaby vlevo a vpravo od lišty (`wire_duct_side_mm` od jejího konce). `ProductionWire` je zároveň rozhraní
pro budoucí exporty strojů (Komax, Steinhauer) – typovaná pole, žádné formátování na straně exportu.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from envocad.model.designation import LOCATION_SYMBOLS, designation, full_designation
from envocad.model.multipole import (
    NEVER_SWITCHED,
    TERMINAL_BLOCK_SYMBOLS,
    UNSWITCHED_POLES,
    canon_key,
    device_terminal,
    is_terminal_block,
    port_conductors,
    wire_conductors,
)
from envocad.model.project import (
    CORE_COLORS,
    DEVICE_HEIGHT_MM,
    MODULE_WIDTH,
    Element,
    Layout,
    Placement,
    Project,
    Sheet,
    Wire,
)

# ---- parametry ------------------------------------------------------------------------------------------------
# výchozí hodnoty klíčů `Layout.params` (a `settings.json standard.wiring`) jako text, jak je ukáže dialog skříně
WIRING_DEFAULTS: dict[str, str] = {
    "wire_type": "H07V-K",
    "wire_end_mm": "100",
    "wire_reserve_pct": "10",
    "wire_round_mm": "50",
    "wire_duct_side_mm": "25",
    "wire_cross_min": "1,5",
    "wire_cross_ctl": "1",
    "wire_unplaced": "estimate",
}

_LABELS = {
    "wire_type": "Typ vodiče (není-li u vodiče)",
    "wire_end_mm": "Přídavek na konec [mm]",
    "wire_reserve_pct": "Rezerva délky [%]",
    "wire_round_mm": "Zaokrouhlení délky nahoru [mm]",
    "wire_duct_side_mm": "Svislý žlab od konce lišty [mm]",
    "wire_cross_min": "Min. / výchozí silový průřez [mm²]",
    "wire_cross_ctl": "Výchozí průřez řízení [mm²]",
    "wire_unplaced": "Neumístěné konce (estimate = odhad / none = bez délky)",
}

# (klíč, popisek, výchozí) – pro EnclosurePanel (skupina „Výrobní data (zapojení)“) a list „Parametry“
WIRING_PARAMS: list[tuple[str, str, str]] = [(k, _LABELS[k], v) for k, v in WIRING_DEFAULTS.items()]

# klíč → pole WiringParams
_FIELDS = {
    "wire_type": "wire_type", "wire_end_mm": "end_mm", "wire_reserve_pct": "reserve_pct",
    "wire_round_mm": "round_mm", "wire_duct_side_mm": "duct_side_mm", "wire_cross_min": "cross_min",
    "wire_cross_ctl": "cross_ctl", "wire_unplaced": "unplaced",
}
UNPLACED_MODES = ("estimate", "none")


def _parse_float(v) -> float | None:
    """„1,5“ / 1.5 → 1.5; prázdné nebo nečíselné → None."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


def _fmt(x: float) -> str:
    """1.5 → „1,5“, 4.0 → „4“ (česká desetinná čárka)."""
    return f"{x:g}".replace(".", ",")


def _parse_param(key: str, v):
    """Hodnota parametru z textu; neplatná hodnota → None (použije se hodnota nižší priority)."""
    if key == "wire_type":
        return (str(v).strip() or None) if v is not None else None
    if key == "wire_unplaced":
        t = str(v or "").strip().lower()
        return t if t in UNPLACED_MODES else None
    x = _parse_float(v)
    return x if x is not None and x >= 0 else None


@dataclass(frozen=True)
class WiringParams:
    """Parametry výrobního seznamu. Priorita: výchozí kód < `settings.json standard.wiring` (`base`) <
    `Layout.params` rozvaděče (klíče `wire_*`)."""
    wire_type: str = "H07V-K"
    end_mm: float = 100.0
    reserve_pct: float = 10.0
    round_mm: float = 50.0
    duct_side_mm: float = 25.0
    cross_min: float = 1.5
    cross_ctl: float = 1.0
    unplaced: str = "estimate"

    @classmethod
    def resolve(cls, layout: Layout | None, base: dict | None = None) -> WiringParams:
        vals: dict[str, object] = {}
        for src in (base or {}, (layout.params if layout is not None else {}) or {}):
            for key, fname in _FIELDS.items():
                v = _parse_param(key, src.get(key))
                if v is not None:
                    vals[fname] = v
        return cls(**vals)

    def value(self, key: str) -> str:
        """Hodnota parametru jako text („1,5“, „H07V-K“)."""
        v = getattr(self, _FIELDS[key])
        return v if isinstance(v, str) else _fmt(v)

    def describe(self) -> str:
        """Jednořádkový popis použitých parametrů (podnadpis výkazu)."""
        unpl = "odhad" if self.unplaced == "estimate" else "bez délky"
        return (f"typ {self.wire_type}, přídavek na konec {_fmt(self.end_mm)} mm, rezerva {_fmt(self.reserve_pct)} %, "
                f"zaokrouhlení nahoru na {_fmt(self.round_mm)} mm, svislý žlab {_fmt(self.duct_side_mm)} mm od lišty, "
                f"min. průřez {_fmt(self.cross_min)} mm², řízení {_fmt(self.cross_ctl)} mm², neumístěné konce: {unpl}, "
                f"výška přístroje {_fmt(DEVICE_HEIGHT_MM)} mm")


def param_sources(layout: Layout | None, base: dict | None = None) -> list[tuple[str, str, str, str]]:
    """(klíč, popisek, hodnota, zdroj) pro list „Parametry“; zdroj = výchozí / firemní standard / rozvaděč."""
    p = WiringParams.resolve(layout, base)
    out = []
    for key, label, _ in WIRING_PARAMS:
        src = "výchozí"
        if _parse_param(key, (base or {}).get(key)) is not None:
            src = "firemní standard"
        if layout is not None and _parse_param(key, (layout.params or {}).get(key)) is not None:
            src = "rozvaděč"
        out.append((key, label, p.value(key), src))
    return out


TERMINAL_RULE = ("Svorky: ruční přiřazení z vícepólu (Wire.terminals); svorkový prvek podle čísel svorek; "
                 "přístroj s porty 1/2 odvozeně: pól k → vstup 2k+1, výstup 2k+2 (L1 = 1/2, L2 = 3/4, L3 = 5/6), "
                 "N a PE podle žíly; jinak jméno portu. Lichá svorka nahoře, sudá dole.")

# ---- tabulky ----------------------------------------------------------------------------------------------------
# ORIENTAČNÍ – vnitřní vodiče Cu/PVC ve žlabu (ČSN EN 61439-1 příl. H); schválí projektant. (In ≤ A, průřez mm²)
IN_TO_CROSS: list[tuple[float, float]] = [(10, 1.5), (16, 2.5), (25, 4), (32, 6), (50, 10), (63, 16), (80, 25),
                                          (100, 35), (125, 50), (160, 70)]

# Dutinky dle DIN 46228 (barevný kód „DIN“): průřez → (barva, délka dutinky mm)
FERRULE_DIN46228: dict[float, tuple[str, int]] = {
    0.5: ("bílá", 8), 0.75: ("šedá", 8), 1.0: ("červená", 8), 1.5: ("černá", 8), 2.5: ("modrá", 8), 4: ("šedá", 10),
    6: ("žlutá", 12), 10: ("červená", 12), 16: ("modrá", 12), 25: ("žlutá", 16), 35: ("červená", 16),
    50: ("modrá", 20)}

# prvky, jejichž `in_` neurčuje průřez vodiče (rozvod, svorky)
NO_CROSS_SYMBOLS = {"sb.busbar", "sb.pe_bar", "sb.junction"} | TERMINAL_BLOCK_SYMBOLS
# neumístěné prvky s odhadem polohy: sběrnice nahoře (žlab 0), svorky a PE lišta dole (žlab `rows`), uprostřed
TOP_ESTIMATE = {"sb.busbar"}
BOTTOM_ESTIMATE = {"sb.feed_in", "sb.feed_out", "sb.terminal_block", "fve.terminal", "sb.pe_bar"}
JUNCTION = "sb.junction"
UNSPLIT_COLOR = {"N", "PE", "PEN"}       # vícežilový vodič: barva z atributu se na ně nepoužije


@dataclass(frozen=True)
class Ferrule:
    cross: float
    length_mm: float
    color: str
    twin: bool = False

    def text(self) -> str:
        """„dutinka 1,5/8 černá“, „dvojitá dutinka 2×1,5/8 černá“."""
        if self.twin:
            return f"dvojitá dutinka 2×{_fmt(self.cross)}/{_fmt(self.length_mm)} {self.color}"
        return f"dutinka {_fmt(self.cross)}/{_fmt(self.length_mm)} {self.color}"


def _in_of(e: Element) -> float | None:
    x = _parse_float(e.attrs.get("in_"))
    return x if x and x > 0 else None


def wire_cross(project: Project, sheet: Sheet, w: Wire, params: WiringParams) -> tuple[float | None, str]:
    """Průřez vodiče a jeho zdroj: `attrs["cross"]` („vodič“) → nejmenší In přístrojů na koncích přes `IN_TO_CROSS`,
    nejméně `cross_min` („jištění“; In nad tabulkou → None) → konec na prvku řízení `ctl.*` („řízení“) →
    `cross_min` („výchozí“)."""
    del project   # rezervováno (např. průřez z objektu kabelu)
    c = _parse_float(w.attrs.get("cross"))
    if c and c > 0:
        return c, "vodič"
    ends = []
    for end in (w.a, w.b):
        try:
            ends.append(sheet.element(end.element_id))
        except KeyError:
            pass
    ins = [x for e in ends if e.symbol_id not in NO_CROSS_SYMBOLS and (x := _in_of(e)) is not None]
    if ins:
        m = min(ins)
        for lim, cross in IN_TO_CROSS:
            if m <= lim:
                return max(float(cross), params.cross_min), "jištění"
        return None, "jištění"
    if any(e.symbol_id.startswith("ctl.") for e in ends):
        return params.cross_ctl, "řízení"
    return params.cross_min, "výchozí"


def conductor_color(w: Wire, conductor: str) -> str:
    """Barva žíly: `attrs["color"]` (jednožilový vodič vždy, vícežilový jen fáze/DC, ne N/PE/PEN), jinak `CORE_COLORS`."""
    col = (w.attrs.get("color") or "").strip()
    if col and (len(wire_conductors(w)) == 1 or conductor not in UNSPLIT_COLOR):
        return col
    return CORE_COLORS.get(conductor, "")


def is_flexible(wire_type: str) -> bool:
    """Ohebný vodič (dutinka): třída 5/6 – „-K“, „-F“, LiY…"""
    t = (wire_type or "").upper()
    return "-K" in t or "-F" in t or "LIY" in t


def ferrule_for(cross: float | None, twin: bool = False) -> Ferrule | None:
    """Dutinka pro průřez podle `FERRULE_DIN46228` (None, když průřez v tabulce není)."""
    if cross is None:
        return None
    for k, (color, length) in FERRULE_DIN46228.items():
        if abs(float(k) - cross) < 1e-9:
            return Ferrule(float(k), float(length), color, twin)
    return None


def end_for(w: Wire, side: str, cross: float | None, wire_type: str, twin: bool = False) -> tuple[str, Ferrule | None]:
    """Koncovka konce `side` („a“/„b“): `attrs["end_a"/"end_b"]` – prázdné = automaticky, „-“ = bez koncovky,
    jiný text doslova; automaticky dutinka jen u ohebného vodiče (dvojitá, když do svorky jdou dvě žíly)."""
    v = (w.attrs.get(f"end_{side}") or "").strip()
    if v == "-":
        return "", None
    if v:
        return v, None
    if not is_flexible(wire_type):
        return "", None
    f = ferrule_for(cross, twin)
    return (f.text() if f else ""), f


# ---- poloha svorek a délka ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TerminalPoint:
    x: float
    y: float
    duct: int          # vodorovný žlab, do kterého konec vede (0 = nad první řadou)
    estimated: bool    # poloha odhadem (neumístěný prvek)


def duct_y(layout: Layout, j: int) -> float:
    return -j * layout.row_pitch_mm


def placed_device(sheet: Sheet, e: Element, index=None) -> tuple[Element, Placement] | None:
    """Umístěný přístroj, ke kterému konec patří: prvek sám, jinak člen jeho skupiny na stejném listu (cívka a
    kontakty přes stykač – `xref.DeviceIndex`)."""
    lay = sheet.layout
    pl = lay.placement(e.id)
    if pl is not None:
        return e, pl
    g = index.group_of(e) if index is not None else None
    if g is None:
        return None
    for s, m in [g.device, *g.members, *g.secondary]:
        if s is sheet and m is not e and (pl := lay.placement(m.id)) is not None:
            return m, pl
    return None


def _terminal_number(terminal: str) -> str:
    return terminal.rpartition(":")[2] if ":" in terminal else terminal


def _port_on_top(e: Element, port: str, lib=None) -> bool:
    """Svorka bez čísla: nahoře/dole podle směru portu v symbolu (N/W = vstup nahoře), bez knihovny podle jména."""
    if lib is not None:
        try:
            return lib.get_symbol(e.symbol_id).port(port).dir in ("N", "W")
        except (KeyError, StopIteration, ValueError, AttributeError):
            pass
    if port.upper() in ("PE", "PEN"):
        return False
    m = re.search(r"(\d+)$", port)
    return int(m.group(1)) % 2 == 1 if m else True


def terminal_point(project: Project, sheet: Sheet, e: Element, port: str, conductor: str, terminal: str,
                   params: WiringParams, index=None, lib=None) -> TerminalPoint | None:
    """Poloha svorky konce žíly na montážní ploše (mm) nebo None (neumístěno, uzel odbočky).

    x = pos·17,5 + (k + 0,5)·W/póly, k = (n − 1)//2 z čísla svorky (N/nečíselné → pořadí žíly na portu);
    svorkový prvek rovnoměrně po šířce podle pořadí žíly. Lichá svorka nahoře (žlab r), sudá dole (žlab r+1),
    bez čísla podle směru portu; svorkový prvek nahoře. `lib` (nepovinně) upřesní směr portu."""
    del project
    lay = sheet.layout
    width = lay.modules_per_row * MODULE_WIDTH
    found = placed_device(sheet, e, index)
    if found is None:
        if e.symbol_id == JUNCTION or params.unplaced != "estimate":
            return None
        if e.symbol_id in TOP_ESTIMATE:
            return TerminalPoint(width / 2, duct_y(lay, 0), 0, True)
        if e.symbol_id in BOTTOM_ESTIMATE:
            return TerminalPoint(width / 2, duct_y(lay, lay.rows), lay.rows, True)
        return None
    dev, pl = found
    w_dev = max(dev.modules, 0.0) * MODULE_WIDTH
    x0 = pl.pos * MODULE_WIDTH
    if is_terminal_block(e):
        slots = sorted({c for w in sheet.wires for end in (w.a, w.b) if end.element_id == e.id
                        for c in wire_conductors(w)}, key=canon_key)
        i = slots.index(conductor) if conductor in slots else 0
        x = x0 + (i + 0.5) * w_dev / max(len(slots), 1)
        top = True
    else:
        poles = max(dev.poles, 1)
        num = _terminal_number(terminal)
        if num.isdigit() and int(num) > 0:
            k = (int(num) - 1) // 2
            top = int(num) % 2 == 1
        else:
            conds = port_conductors(sheet, e.id, port)
            k = conds.index(conductor) if conductor in conds else 0
            top = _port_on_top(e, port, lib)
        k = min(max(k, 0), poles - 1)
        x = x0 + (k + 0.5) * w_dev / poles
    axis = -(pl.row + 0.5) * lay.row_pitch_mm
    y = axis + DEVICE_HEIGHT_MM / 2 if top else axis - DEVICE_HEIGHT_MM / 2
    return TerminalPoint(x, y, pl.row if top else pl.row + 1, False)


def route_length_mm(a: TerminalPoint, b: TerminalPoint, layout: Layout, params: WiringParams) -> int:
    """Délka vodiče po žlabech: svisle ze svorky do žlabu na obou koncích, ve stejném žlabu vodorovně, jinak přes
    kratší boční svislý žlab; + 2× přídavek na konec, + rezerva %, zaokrouhleno nahoru na `round_mm`."""
    yda, ydb = duct_y(layout, a.duct), duct_y(layout, b.duct)
    leg = abs(a.y - yda) + abs(b.y - ydb)
    if a.duct == b.duct:
        horiz, vert = abs(a.x - b.x), 0.0
    else:
        x_l = -params.duct_side_mm
        x_r = layout.modules_per_row * MODULE_WIDTH + params.duct_side_mm
        horiz = min(abs(a.x - x_l) + abs(b.x - x_l), abs(a.x - x_r) + abs(b.x - x_r))
        vert = abs(yda - ydb)
    raw = (leg + horiz + vert + 2 * params.end_mm) * (1 + params.reserve_pct / 100)
    step = params.round_mm if params.round_mm > 0 else 1.0
    return round(math.ceil(raw / step - 1e-9) * step)


# ---- výrobní seznam ---------------------------------------------------------------------------------------------
@dataclass
class ProductionWire:
    """Řádek výrobního zapojovacího seznamu (jedna žíla vnitřního vodiče rozvaděče)."""
    number: int
    sheet: str
    ref: str
    conductor: str
    from_text: str                 # „+RDC1-F2:3“
    to_text: str
    cross: float | None
    cross_source: str              # vodič | jištění | řízení | výchozí
    color: str
    wire_type: str
    length_mm: int | None
    end_from: str
    end_to: str
    ferrule_from: Ferrule | None
    ferrule_to: Ferrule | None
    notes: list[str] = field(default_factory=list)
    wire_id: str = ""


def end_text(project: Project, sheet: Sheet, e: Element, terminal: str) -> str:
    """Text konce „+RDC1-F2:3“ (aspekty prvku před svorkou; bez aspektů „F2:3“) – jako `reports._port_text`."""
    if e.symbol_id in LOCATION_SYMBOLS and e.ref:
        return f"{full_designation(project, sheet, e)}-{_terminal_number(terminal)}"
    a = designation(sheet, e).aspects if e.ref else ""
    return f"{a}-{terminal}" if a else terminal


def is_bypassed(sheet: Sheet, e: Element, port: str, conductor: str) -> bool:
    """Nespínaná žíla průchozího přístroje (PE/PEN vždy, N když přístroj nemá pól navíc pro N – 3p jistič):
    v JPS vede přes přístroj, ve skutečnosti jde kolem něj."""
    if conductor in NEVER_SWITCHED:
        return True
    if conductor != "N":
        return False
    phases = [c for c in port_conductors(sheet, e.id, port) if c not in UNSWITCHED_POLES]
    return len(phases) >= e.poles


@dataclass
class _End:
    side: str
    element: Element
    port: str
    terminal: str
    specific: bool                 # svorka je konkrétní (ruční / svorkový prvek / odvozená), ne jen jméno portu
    derived: bool                  # svorka odvozená pravidlem (průchozí přístroj s porty 1/2)
    point: TerminalPoint | None
    key: tuple
    text: str


def _end_key(e: Element, terminal: str, point: TerminalPoint | None, found) -> tuple:
    from envocad.model.xref import natural_key
    placed = point is not None and not point.estimated
    row, pos = (found[1].row, found[1].pos) if found else (math.inf, math.inf)
    return (0 if placed else 1, row, pos, natural_key(e.ref or e.symbol_id), natural_key(_terminal_number(terminal)))


def production_wires(project: Project, sheet: Sheet | None = None, base: dict | None = None,
                     lib=None) -> list[ProductionWire]:
    """Výrobní zapojovací seznam: každá žíla každého vodiče listů rozvaděčů (`attrs["prod"] == "0"` vynechá;
    můstky svorek nejsou vodiče). Konce se srovnají (umístěné první, řada, pozice, označení, svorka), řádky podle
    listu, odkud, kam a žíly; čísla se přidělí po seřazení. `base` = `settings.json standard.wiring`."""
    from envocad.model.xref import DeviceIndex
    index = DeviceIndex.build(project)
    sheets = [sheet] if sheet is not None else list(project.sheets)
    keyed: list[tuple[tuple, ProductionWire]] = []
    for s in sheets:
        if not s.is_switchboard:
            continue
        params = WiringParams.resolve(s.layout, base)
        raw: list[tuple[Wire, str, _End, _End]] = []
        clamps: dict[tuple, int] = {}
        for w in s.wires:
            if (w.attrs.get("prod") or "").strip() == "0":
                continue
            try:
                ea, eb = s.element(w.a.element_id), s.element(w.b.element_id)
            except KeyError:
                continue
            for c in wire_conductors(w):
                ends = []
                for side, e, port in (("a", ea, w.a.port), ("b", eb, w.b.port)):
                    t, derived = device_terminal(s, w, c, side)
                    specific = derived or t != f"{e.ref or e.symbol_id}:{port}"
                    pt = terminal_point(project, s, e, port, c, t, params, index, lib)
                    found = placed_device(s, e, index)
                    ends.append(_End(side, e, port, t, specific, derived, pt, _end_key(e, t, pt, found),
                                     end_text(project, s, e, t)))
                    ck = (e.id, port, t) if specific else (e.id, port, t, c)
                    clamps[ck] = clamps.get(ck, 0) + 1
                a, b = ends
                if b.key < a.key:
                    a, b = b, a
                raw.append((w, c, a, b))
        for w, c, a, b in raw:
            cross, source = wire_cross(project, s, w, params)
            wire_type = (w.attrs.get("cable") or "").strip() or params.wire_type
            notes: list[str] = []
            if cross is None:
                notes.append("In nad tabulkou – průřez určí projektant")
            elif source == "výchozí":
                notes.append("průřez výchozí – ověřit")
            ferr: list[tuple[str, Ferrule | None]] = []
            for end in (a, b):
                ck = (end.element.id, end.port, end.terminal) if end.specific else \
                    (end.element.id, end.port, end.terminal, c)
                n = clamps.get(ck, 1)
                if n >= 3:
                    notes.append(f"{n} {'žíly' if n < 5 else 'žil'} ve svorce {end.text} – ověřit")
                ferr.append(end_for(w, end.side, cross, wire_type, twin=n == 2))
                name = end.element.ref or end.element.symbol_id
                if end.derived and c in UNSWITCHED_POLES and is_bypassed(s, end.element, end.port, c):
                    notes.append(f"{c} nespínaný – ve skutečnosti vede kolem {name}")
                if end.point is None:
                    notes.append("konec v uzlu odbočky" if end.element.symbol_id == JUNCTION else f"neumístěno: {name}")
                elif end.point.estimated:
                    notes.append(f"délka odhadem – {name} neumístěn")
            length = route_length_mm(a.point, b.point, s.layout, params) if a.point and b.point else None
            pw = ProductionWire(0, s.name, w.attrs.get("ref", ""), c, a.text, b.text, cross, source,
                                conductor_color(w, c), wire_type, length, ferr[0][0], ferr[1][0], ferr[0][1],
                                ferr[1][1], list(dict.fromkeys(notes)), w.id)
            keyed.append(((s.name, a.key, b.key, canon_key(c)), pw))
    keyed.sort(key=lambda kp: kp[0])
    out = [pw for _, pw in keyed]
    for i, pw in enumerate(out, start=1):
        pw.number = i
    return out
