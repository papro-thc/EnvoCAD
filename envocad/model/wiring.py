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

from envocad.model.designation import LOCATION_SYMBOLS, designation, element_name, full_designation
from envocad.model.feed import FEED_SYMBOL, feed_dir, is_feed
from envocad.model.multipole import (
    NEVER_SWITCHED,
    TERMINAL_BLOCK_SYMBOLS,
    UNSWITCHED_POLES,
    canon_key,
    device_terminal,
    is_terminal_block,
    port_conductors,
    terminal_text,
    wire_conductors,
    wire_end_terminal,
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
    element_symbol,
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
    "wire_cross_dc": "6",
    "wire_spd_lps": "no",
    "wire_unplaced": "estimate",
    "wire_marking": "address",
}

_LABELS = {
    "wire_type": "Typ vodiče (není-li u vodiče)",
    "wire_end_mm": "Přídavek na konec [mm]",
    "wire_reserve_pct": "Rezerva délky [%]",
    "wire_round_mm": "Zaokrouhlení délky nahoru [mm]",
    "wire_duct_side_mm": "Svislý žlab od konce lišty [mm]",
    "wire_cross_min": "Min. / výchozí silový průřez [mm²]",
    "wire_cross_ctl": "Výchozí průřez řízení [mm²]",
    "wire_cross_dc": "Min. průřez DC žil L+ / L− [mm²]",
    "wire_spd_lps": "Jímací soustava (hromosvod) na objektu",
    "wire_unplaced": "Neumístěné konce",
    "wire_marking": "Značení vodičů (návlečky)",
}

# (klíč, popisek, výchozí) – pro EnclosurePanel (skupina „Výrobní data (zapojení)“) a list „Parametry“
WIRING_PARAMS: list[tuple[str, str, str]] = [(k, _LABELS[k], v) for k, v in WIRING_DEFAULTS.items()]

# klíč → pole WiringParams
_FIELDS = {
    "wire_type": "wire_type", "wire_end_mm": "end_mm", "wire_reserve_pct": "reserve_pct",
    "wire_round_mm": "round_mm", "wire_duct_side_mm": "duct_side_mm", "wire_cross_min": "cross_min",
    "wire_cross_ctl": "cross_ctl", "wire_unplaced": "unplaced", "wire_marking": "marking",
    "wire_cross_dc": "cross_dc", "wire_spd_lps": "lps",
}
UNPLACED_MODES = ("estimate", "none")
# uložená hodnota `wire_unplaced` → český popisek (GUI výběr, list „Parametry“, podnadpis)
UNPLACED_LABELS: dict[str, str] = {"estimate": "odhad", "none": "bez délky"}
# značení konců vodičů návlečkami dle ČSN EN 62491: adresné (na konci adresa protějšího konce), odkud/kam (vlastní
# a protější), nezávislé (číslo vodiče na obou koncích), bez návleček
MARKING_LABELS: dict[str, str] = {"address": "adresné – protější konec", "both": "odkud / kam",
                                  "number": "číslo vodiče", "none": "bez návleček"}
# výběrové parametry: klíč → {uložená hodnota: český popisek}
# jímací soustava: SPD typu I (T1) v objektu s hromosvodem → PE svodiče 16 mm² Cu k ochrannému pospojování
LPS_LABELS: dict[str, str] = {"no": "ne – PE od SPD 6 mm²", "yes": "ano – PE od SPD typu I 16 mm²"}
CHOICE_LABELS: dict[str, dict[str, str]] = {"wire_unplaced": UNPLACED_LABELS, "wire_marking": MARKING_LABELS,
                                            "wire_spd_lps": LPS_LABELS}


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


def parse_param(key: str, v):
    """Hodnota parametru z textu; neplatná hodnota → None (použije se hodnota nižší priority)."""
    if key == "wire_type":
        return (str(v).strip() or None) if v is not None else None
    if key in CHOICE_LABELS:
        labels = CHOICE_LABELS[key]
        t = str(v or "").strip().lower()
        t = {lab: code for code, lab in labels.items()}.get(t, t)   # i český popisek
        return t if t in labels else None
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
    marking: str = "address"
    cross_dc: float = 6.0
    lps: str = "no"

    @classmethod
    def resolve(cls, layout: Layout | None, base: dict | None = None) -> WiringParams:
        vals: dict[str, object] = {}
        for src in (base or {}, (layout.params if layout is not None else {}) or {}):
            for key, fname in _FIELDS.items():
                v = parse_param(key, src.get(key))
                if v is not None:
                    vals[fname] = v
        return cls(**vals)

    def value(self, key: str) -> str:
        """Hodnota parametru jako text („1,5“, „H07V-K“, „estimate“) – tak, jak se ukládá."""
        v = getattr(self, _FIELDS[key])
        return v if isinstance(v, str) else _fmt(v)

    def display(self, key: str) -> str:
        """Hodnota parametru česky pro výstupy („odhad“ místo „estimate“)."""
        v = self.value(key)
        return CHOICE_LABELS[key].get(v, v) if key in CHOICE_LABELS else v

    def describe(self) -> str:
        """Jednořádkový popis použitých parametrů (podnadpis výkazu)."""
        unpl = UNPLACED_LABELS.get(self.unplaced, self.unplaced)
        return (f"typ {self.wire_type}, přídavek na konec {_fmt(self.end_mm)} mm, rezerva {_fmt(self.reserve_pct)} %, "
                f"zaokrouhlení nahoru na {_fmt(self.round_mm)} mm, svislý žlab {_fmt(self.duct_side_mm)} mm od lišty, "
                f"min. průřez {_fmt(self.cross_min)} mm², řízení {_fmt(self.cross_ctl)} mm², neumístěné konce: {unpl}, "
                f"DC žíly min. {_fmt(self.cross_dc)} mm², jímací soustava: {LPS_LABELS.get(self.lps, self.lps)}, "
                f"značení vodičů: {MARKING_LABELS.get(self.marking, self.marking)}, "
                f"výška přístroje z artiklu, jinak {_fmt(DEVICE_HEIGHT_MM)} mm")


def param_sources(layout: Layout | None, base: dict | None = None) -> list[tuple[str, str, str, str]]:
    """(klíč, popisek, hodnota, zdroj) pro list „Parametry“; zdroj = výchozí / firemní standard / rozvaděč."""
    p = WiringParams.resolve(layout, base)
    out = []
    for key, label, _ in WIRING_PARAMS:
        src = "výchozí"
        if parse_param(key, (base or {}).get(key)) is not None:
            src = "firemní standard"
        if layout is not None and parse_param(key, (layout.params or {}).get(key)) is not None:
            src = "rozvaděč"
        out.append((key, label, p.display(key), src))
    return out


TERMINAL_RULE = ("Svorky: ruční přiřazení z vícepólu (Wire.terminals); svorkový prvek podle čísel svorek; "
                 "přístroj s porty 1/2 odvozeně: pól k → vstup 2k+1, výstup 2k+2 (L1 = 1/2, L2 = 3/4, L3 = 5/6, "
                 "spínaný N jako další pól – 4p: 7/8 dle IEC 60947-1; výrobce může značit N – pak přiřadit ručně); "
                 "nespínaný N a PE vedou kolem přístroje (jeden řádek mezi vnějšími konci); sběrnice = potenciál "
                 "(1L1); port s více žilami = port podle žíly (F1:L1, F1:N; číselný port 3/L1); jinak jméno portu. "
                 "Lichá svorka nahoře, sudá dole.")

NUMBER_NOTE = "Č. je pořadí v seznamu, po změně projektu se může změnit."

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
# silové kontakty (prvky `ctl.*`, které nejsou řízení): bez `in_` průřez z In stykače ve skupině, jinak výchozí silový
POWER_CONTACTS = {"ctl.contact_power"}
# přístroje, u kterých je výchozí průřez nebezpečný: bez In na druhém konci průřez None + poznámka (zdroj = klíč)
NO_DEFAULT_CROSS: dict[str, tuple[str, str]] = {
    "fve.spd": ("SPD", "SPD – průřez určí projektant (dle výrobce SPD)"),
}
# ohebné vodiče (třída 5/6) – automatická dutinka; hledá se podřetězec v typu (velká písmena)
FLEXIBLE_WIRE_TYPES: list[tuple[str, str]] = [
    ("-K", "třída 5 dle HD 361: H05V-K, H07V-K, H07V2-K, H05Z1-K…"),
    ("-F", "třída 5/6 – šňůry: H05VV-F, H07RN-F…"),
    ("CYA", "CYA – Cu lanovaný (ČSN)"),
    ("LGY", "LgY – Cu jemně lanovaný"),
    ("LIY", "LiY, LiYY, LiYCY – sdělovací lanované"),
]
BUS = "sb.busbar"
# neumístěné prvky s odhadem polohy: sběrnice nahoře (žlab 0), svorky a PE lišta dole (žlab `rows`), uprostřed
TOP_ESTIMATE = {"sb.busbar"}
BOTTOM_ESTIMATE = {FEED_SYMBOL, "sb.terminal_block", "fve.terminal", "sb.pe_bar"}
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


def _group_in(e: Element, index) -> float | None:
    """In stykače ve skupině silového kontaktu (`xref.DeviceIndex`), jinak None."""
    g = index.group_of(e) if index is not None else None
    if g is None:
        return None
    ins = [x for _s, m in [g.device, *g.secondary, *g.members] if m is not e and (x := _in_of(m)) is not None]
    return min(ins) if ins else None


def _cross_for_in(m: float, params: WiringParams) -> float | None:
    for lim, cross in IN_TO_CROSS:
        if m <= lim:
            return max(float(cross), params.cross_min)
    return None


def wire_cross(project: Project, sheet: Sheet, w: Wire, params: WiringParams, index=None) -> tuple[float | None, str]:
    """Průřez vodiče a jeho zdroj: `attrs["cross"]` („vodič“) → nejmenší In přístrojů na koncích přes `IN_TO_CROSS`,
    nejméně `cross_min` („jištění“; In nad tabulkou → None) → silový kontakt bez In: In stykače ve skupině
    (`index`, „stykač“) → přístroj z `NO_DEFAULT_CROSS` (SPD: None, zdroj „SPD“) → konec na prvku řízení `ctl.*`
    mimo silové kontakty („řízení“) → `cross_min` („výchozí“). PE od svodiče (port PE prvku `fve.spd`) má vlastní
    pravidlo (`spd_pe_cross`, zdroj „PE SPD“); DC žíly (L+ / L− / M) mají nejméně `cross_dc` a přívod DC svodiče
    bez In na druhém konci dostane `cross_dc` (zdroj „DC“) – stejný průřez jako DC vedení stringu."""
    del project   # rezervováno (např. průřez z objektu kabelu)
    c = _parse_float(w.attrs.get("cross"))
    if c and c > 0:
        return c, "vodič"
    ends = []
    for end in (w.a, w.b):
        try:
            e = sheet.element(end.element_id)
        except KeyError:
            continue
        ends.append(e)
        if e.symbol_id == "fve.spd" and end.port == "PE":
            return spd_pe_cross(e, params), SPD_PE
    cross, source = _wire_cross(ends, params, index)
    if cross is not None and set(wire_conductors(w)) <= DC_CORES:   # DC string: L+ / L− nejméně `cross_dc`
        return max(cross, params.cross_dc), source
    if cross is None and source == "SPD" and set(wire_conductors(w)) <= DC_CORES:
        return params.cross_dc, "DC"        # přívod DC svodiče = průřez DC vedení stringu
    return cross, source


SPD_PE = "PE SPD"
DC_CORES = {"L+", "L-", "M"}


def is_spd_type1(e: Element) -> bool:
    """SPD typu I (T1, „I+II“): podle typu SPD nebo objednacího typu."""
    t = f"{e.attrs.get('spd_type', '')} {e.attrs.get('type', '')}".upper()
    return bool(re.search(r"\bT1\b|\bI\+II\b|\bTYP\s*1\b", t.replace("T1+", "T1 ")))


def spd_pe_cross(e: Element, params: WiringParams) -> float:
    """PE od svodiče: nejméně 6 mm² Cu; SPD typu I v objektu s jímací soustavou (`wire_spd_lps`) 16 mm² Cu
    k ochrannému pospojování."""
    return 16.0 if params.lps == "yes" and is_spd_type1(e) else 6.0


def _wire_cross(ends: list[Element], params: WiringParams, index) -> tuple[float | None, str]:
    ins = [x for e in ends if e.symbol_id not in NO_CROSS_SYMBOLS and (x := _in_of(e)) is not None]
    if ins:
        return _cross_for_in(min(ins), params), "jištění"
    kins = [x for e in ends if e.symbol_id in POWER_CONTACTS and (x := _group_in(e, index)) is not None]
    if kins:
        return _cross_for_in(min(kins), params), "stykač"
    for e in ends:
        if e.symbol_id in NO_DEFAULT_CROSS:
            return None, NO_DEFAULT_CROSS[e.symbol_id][0]
    if any(e.symbol_id.startswith("ctl.") and e.symbol_id not in POWER_CONTACTS for e in ends):
        return params.cross_ctl, "řízení"
    return params.cross_min, "výchozí"


def cross_note(cross: float | None, source: str) -> str:
    """Poznámka k průřezu podle zdroje (prázdné = bez poznámky)."""
    for src, note in NO_DEFAULT_CROSS.values():
        if source == src:
            return note
    if source == SPD_PE:
        return f"PE od SPD {_fmt(cross)} mm² Cu" + (" (SPD typu I, jímací soustava)" if cross and cross >= 16 else "")
    if cross is None:
        return "In nad tabulkou – průřez určí projektant"
    if source == "výchozí":
        return "průřez výchozí – ověřit"
    return ""


def conductor_color(w: Wire, conductor: str) -> str:
    """Barva žíly: `attrs["color"]` (jednožilový vodič vždy, vícežilový jen fáze/DC, ne N/PE/PEN), jinak `CORE_COLORS`."""
    col = (w.attrs.get("color") or "").strip()
    if col and (len(wire_conductors(w)) == 1 or conductor not in UNSPLIT_COLOR):
        return col
    return CORE_COLORS.get(conductor, "")


def is_flexible(wire_type: str) -> bool:
    """Ohebný vodič (dutinka): typ obsahuje některý vzor z `FLEXIBLE_WIRE_TYPES` (-K, -F, CYA, LgY, LiY)."""
    t = (wire_type or "").upper()
    return any(pat in t for pat, _ in FLEXIBLE_WIRE_TYPES)


def ferrule_for(cross: float | None, twin: bool = False) -> Ferrule | None:
    """Dutinka pro průřez podle `FERRULE_DIN46228` (None, když průřez v tabulce není)."""
    if cross is None:
        return None
    for k, (color, length) in FERRULE_DIN46228.items():
        if abs(float(k) - cross) < 1e-9:
            return Ferrule(float(k), float(length), color, twin)
    return None


def end_for(w: Wire, side: str, cross: float | None, wire_type: str, twin: bool = False,
            auto: bool = True) -> tuple[str, Ferrule | None]:
    """Koncovka konce `side` („a“/„b“): `attrs["end_a"/"end_b"]` – prázdné = automaticky, „-“ = bez koncovky,
    jiný text doslova; automaticky dutinka jen u ohebného vodiče (dvojitá, když do svorky jdou dvě žíly stejného
    průřezu); `auto=False` automatickou dutinku vypne (např. dva různé průřezy v jedné svorce)."""
    v = (w.attrs.get(f"end_{side}") or "").strip()
    if v == "-":
        return "", None
    if v:
        return v, None
    if not auto or not is_flexible(wire_type):
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


def _port_on_top(project: Project, e: Element, port: str, lib=None) -> bool:
    """Svorka bez čísla: nahoře/dole podle směru portu ve značce prvku (`element_symbol` – i parametrická sběrnice,
    střídač, blok ROZVADĚČ; N/W = vstup nahoře), bez knihovny nebo u osiřelého portu podle jména."""
    if is_feed(e):     # starý `sb.feed_in` měl port dole (S), `sb.feed_out` nahoře (N) – beze změny výstupu
        return feed_dir(e) == "out"
    if lib is not None:
        try:
            sym = element_symbol(project, e, lib)
            if port not in sym.orphan_ports:     # osiřelý port („X1?“ pod značkou) směr nemá – podle jména
                return sym.port(port).dir in ("N", "W")
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
    from envocad.model.device_size import device_size
    size = device_size(dev, lib)        # šířka a výška z artiklu (s `lib`), jinak z atributů jako dřív (45 mm)
    w_dev = max(size.width_mm, 0.0)
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
            top = _port_on_top(project, e, port, lib)
        k = min(max(k, 0), poles - 1)
        x = x0 + (k + 0.5) * w_dev / poles
    axis = -(pl.row + 0.5) * lay.row_pitch_mm
    y = axis + size.height_mm / 2 if top else axis - size.height_mm / 2
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
    wire_id: str = ""                                    # vodič konce „odkud“
    wire_ids: list[str] = field(default_factory=list)    # všechny vodiče řádku (sloučený úsek kolem přístroje)
    marking: str = "address"                             # druh značení (`WiringParams.marking`)
    marker_from: str = ""                                # text návlečky na konci „odkud“ (ČSN EN 62491)
    marker_to: str = ""                                  # text návlečky na konci „kam“
    local_from: str = ""                                 # konce bez vlastního umístění rozvaděče („F2:3“)
    local_to: str = ""


def end_text(project: Project, sheet: Sheet, e: Element, terminal: str) -> str:
    """Text konce „+RDC1-F2:3“ (aspekty prvku před svorkou; bez aspektů „F2:3“) – jako `reports._port_text`."""
    if e.symbol_id in LOCATION_SYMBOLS and e.ref:
        return f"{full_designation(project, sheet, e)}-{_terminal_number(terminal)}"
    a = designation(sheet, e).aspects if e.ref else ""
    return f"{a}-{terminal}" if a else terminal


def local_end_text(sheet: Sheet, text: str) -> str:
    """Konec uvnitř rozvaděče bez jeho vlastních aspektů: „=AC+RDC1-F2:3“ na listu =AC+RDC1 → „F2:3“; konec
    v jiném umístění (+RFVE.AC-X1:2) zůstane celý – návlečka musí říct, kam vodič vede."""
    t = text
    if sheet.func and t.startswith(f"={sheet.func}") and t[len(sheet.func) + 1:len(sheet.func) + 2] in ("+", "-"):
        t = t[len(sheet.func) + 1:]
    if sheet.loc and t.startswith(f"+{sheet.loc}-"):
        t = t[len(sheet.loc) + 1:]
    return t.removeprefix("-")


def wire_markers(pw: ProductionWire) -> tuple[str, str]:
    """Texty návleček (odkud, kam) podle druhu značení `pw.marking` (ČSN EN 62491): adresné = na každém konci
    adresa protějšího konce, odkud/kam = „vlastní / protější“, číslo = označení vodiče (jinak pořadové číslo)
    na obou koncích, bez návleček = prázdné."""
    a, b = pw.local_from or pw.from_text, pw.local_to or pw.to_text
    if pw.marking == "none":
        return "", ""
    if pw.marking == "number":
        n = pw.ref or str(pw.number)
        return n, n
    if pw.marking == "both":
        return f"{a} / {b}", f"{b} / {a}"
    return b, a


def end_name(e: Element) -> str:
    """Jméno konce do poznámek: „F2“, u sběrnice „sběrnice 1“."""
    if e.symbol_id == BUS:
        return f"sběrnice {e.ref}".strip()
    return element_name(e)


# původ svorky konce žíly (`ConductorEnd.origin`)
ORIGIN_MANUAL = "ruční"            # Wire.terminals z vícepólu
ORIGIN_BLOCK = "svorkový prvek"    # čísla svorek svorkového prvku
ORIGIN_RULE = "pravidlo"           # průchozí přístroj s porty 1/2 (pól k → 2k+1 / 2k+2)
ORIGIN_BUS = "sběrnice"            # potenciál sběrnice „1L1“
ORIGIN_PORT = "port"               # jen jméno portu (případně s žílou)
SPECIFIC_ORIGINS = {ORIGIN_MANUAL, ORIGIN_BLOCK, ORIGIN_RULE}


@dataclass(frozen=True)
class ConductorEnd:
    """Konec žíly vodiče: svorka bez aspektů („F2:3“, „1L1“), její původ a text s aspekty („+RDC1-F2:3“)."""
    terminal: str
    origin: str
    text: str

    @property
    def specific(self) -> bool:
        """Svorka je konkrétní (ruční / svorkový prvek / pravidlo) – klíč svorky je její označení."""
        return self.origin in SPECIFIC_ORIGINS

    @property
    def derived(self) -> bool:
        return self.origin == ORIGIN_RULE


def conductor_end(project: Project, sheet: Sheet, w: Wire, conductor: str, side: str) -> ConductorEnd:
    """Svorka a text konce žíly – společné pro výrobní i zapojovací seznam listu rozvaděče.

    Pořadí: ruční `Wire.terminals` → sběrnice = potenciál `{ref}{žíla}` („+RDC1-1L1“) → `device_terminal`
    (svorkový prvek, pravidlo 1/2) → jméno portu; nese-li port víc žil, doplní se žíla: nečíselný port → žíla
    místo portu („F1:L1“, „F1:N“ – SPD s portem L), číselný port → „port/žíla“ („X:3/L1“)."""
    end = w.a if side == "a" else w.b
    e = sheet.element(end.element_id)
    manual = terminal_text(w, conductor, side)
    if manual:
        t, origin = manual, ORIGIN_MANUAL
    elif e.symbol_id == BUS:
        t, origin = (f"{e.ref}{conductor}" if e.ref else f"sběrnice {conductor}"), ORIGIN_BUS
    else:
        t, derived = device_terminal(sheet, w, conductor, side)
        if derived:
            origin = ORIGIN_RULE
        elif is_terminal_block(e) and wire_end_terminal(sheet, w, conductor, side):
            origin = ORIGIN_BLOCK
        else:
            origin = ORIGIN_PORT
            if len(port_conductors(sheet, e.id, end.port)) > 1:
                name = element_name(e)
                t = f"{name}:{end.port}/{conductor}" if end.port[:1].isdigit() else f"{name}:{conductor}"
    return ConductorEnd(t, origin, end_text(project, sheet, e, t))


def wire_end_labels(sheet: Sheet, w: Wire) -> dict[str, str]:
    """Popisky koncovek vodiče s koncem: {"end_a": "Koncovka A (F2:2)", "end_b": "Koncovka B (X1:1)"}."""
    out = {}
    for side, end in (("a", w.a), ("b", w.b)):
        try:
            e = sheet.element(end.element_id)
            where = f"{end_name(e)}:{end.port}" if e.symbol_id != BUS else end_name(e)
        except KeyError:
            where = end.port
        out[f"end_{side}"] = f"Koncovka {side.upper()} ({where})"
    return out


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
    wire: Wire
    element: Element
    port: str
    info: ConductorEnd
    point: TerminalPoint | None
    key: tuple                     # řazení konců

    @property
    def text(self) -> str:
        return self.info.text


def _end_key(e: Element, terminal: str, point: TerminalPoint | None, found) -> tuple:
    from envocad.model.xref import natural_key
    placed = point is not None and not point.estimated
    row, pos = (found[1].row, found[1].pos) if found else (math.inf, math.inf)
    return (0 if placed else 1, row, pos, natural_key(e.ref or e.symbol_id), natural_key(_terminal_number(terminal)))


def _clamp_key(sheet: Sheet, end: _End, conductor: str) -> tuple:
    """Klíč fyzické svorky (počet žil → dvojitá dutinka): konkrétní svorka podle původu (ruční / svorkový prvek /
    pravidlo) = její označení s aspekty; sběrnice a jméno portu = prvek, port a žíla."""
    if end.info.specific:
        a = designation(sheet, end.element).aspects if end.element.ref else ""
        return ("t", a, end.info.terminal)
    return ("p", end.element.id, end.port, conductor)


@dataclass
class _Seg:
    """Jedna žíla jednoho vodiče se dvěma konci (a, b)."""
    w: Wire
    c: str
    ends: list[_End]


def _bypass_links(sheet: Sheet, segs: list[_Seg]) -> dict[tuple[int, int], tuple[int, int, str]]:
    """Propojení úseků nespínané žíly přes průchozí přístroj: (úsek, konec) → (úsek, konec, přístroj).

    Spojí se jen jednoznačné případy: na vstupu (port 1) i výstupu (port 2) přístroje právě jeden úsek žíly,
    oba konce odvozené pravidlem a žíla na obou portech nespínaná (`is_bypassed`)."""
    at: dict[tuple[str, str, str], list[tuple[int, int]]] = {}
    for i, sg in enumerate(segs):
        for j, end in enumerate(sg.ends):
            if end.info.derived and sg.c in UNSWITCHED_POLES:
                at.setdefault((end.element.id, end.port, sg.c), []).append((i, j))
    links: dict[tuple[int, int], tuple[int, int, str]] = {}
    for (eid, port, c), ins in at.items():
        if port != "1":
            continue
        outs = at.get((eid, "2", c), [])
        if len(ins) != 1 or len(outs) != 1:
            continue
        (i, j), (k, m) = ins[0], outs[0]
        e = segs[i].ends[j].element
        if i == k or not (is_bypassed(sheet, e, "1", c) and is_bypassed(sheet, e, "2", c)):
            continue
        links[(i, j)] = (k, m, end_name(e))
        links[(k, m)] = (i, j, end_name(e))
    return links


def _chains(segs: list[_Seg], links) -> list[tuple[list[int], _End, _End, list[str]]]:
    """Řetězy úseků spojených přes přístroje: (úseky, vnější konec, vnější konec, přístroje po cestě)."""
    out = []
    done: set[int] = set()
    for start in range(len(segs)):
        if start in done:
            continue
        si, se, seen = start, 0, {start}          # najít vnější konec: jít přes odkazy z konce a
        while (si, se) in links:
            k, m, _ = links[(si, se)]
            if k in seen:
                break
            seen.add(k)
            si, se = k, 1 - m
        chain, devs = [si], []
        done.add(si)
        cur, cur_in = si, se
        while (cur, 1 - cur_in) in links:
            k, m, name = links[(cur, 1 - cur_in)]
            if k in done:
                break
            devs.append(name)
            done.add(k)
            chain.append(k)
            cur, cur_in = k, m
        out.append((chain, segs[si].ends[se], segs[cur].ends[1 - cur_in], devs))
    return out


def _segments(project: Project, s: Sheet, index, params: WiringParams | None, lib=None,
              prod_only: bool = True) -> list[_Seg]:
    """Úseky žil vodičů listu (žíla × vodič) s konci. `params` None = bez poloh svorek (zapojovací seznam);
    `prod_only` vynechá vodiče s `attrs["prod"] == "0"` (výrobní seznam)."""
    segs: list[_Seg] = []
    from envocad.model.multipole import sheet_dead_conductors
    dead = sheet_dead_conductors(project, s, lib)      # žíly, které na jističi 1p nikam nevedou
    for w in s.wires:
        if prod_only and (w.attrs.get("prod") or "").strip() == "0":
            continue
        try:
            ea, eb = s.element(w.a.element_id), s.element(w.b.element_id)
        except KeyError:
            continue
        for c in wire_conductors(w):
            if c in dead.get(w.id, ()):
                continue
            ends = []
            for side, e, port in (("a", ea, w.a.port), ("b", eb, w.b.port)):
                info = conductor_end(project, s, w, c, side)
                pt = terminal_point(project, s, e, port, c, info.terminal, params, index, lib) if params else None
                found = placed_device(s, e, index)
                ends.append(_End(side, w, e, port, info, pt, _end_key(e, info.terminal, pt, found)))
            segs.append(_Seg(w, c, ends))
    return segs


@dataclass
class MergedConductor:
    """Žíla zapojení listu rozvaděče po sloučení nespínaných úseků kolem přístrojů (stejně jako výrobní seznam):
    vodiče úseků, vnější konce (`ConductorEnd`) a poznámky („vede kolem Q1“, „N nespínaný – … kolem Q1“)."""
    conductor: str
    wires: list[Wire]
    end_a: ConductorEnd
    end_b: ConductorEnd
    notes: list[str]


def merged_conductors(project: Project, sheet: Sheet) -> list[MergedConductor]:
    """Žíly vodičů listu rozvaděče sloučené přes přístroje jako ve výrobním seznamu (`production_wires`), ale se
    všemi vodiči (i `prod = 0`) – pro zapojovací seznam listu, aby počet a obsah řádků odpovídal výrobnímu.
    Pořadí podle vodičů listu; konce v pořadí vodiče (a → b)."""
    from envocad.model.xref import DeviceIndex
    index = DeviceIndex.build(project)
    segs = _segments(project, sheet, index, None, prod_only=False)
    out: list[MergedConductor] = []
    for chain, a, b, devs in _chains(segs, _bypass_links(sheet, segs)):
        c = segs[chain[0]].c
        notes = [f"vede kolem {', '.join(devs)}"] if devs else []
        if not devs:
            for end in (a, b):
                if end.info.derived and c in UNSWITCHED_POLES and is_bypassed(sheet, end.element, end.port, c):
                    notes.append(f"{c} nespínaný – ve skutečnosti vede kolem {end_name(end.element)}")
        out.append(MergedConductor(c, [segs[i].w for i in chain], a.info, b.info, notes))
    return out


def production_wires(project: Project, sheet: Sheet | None = None, base: dict | None = None,
                     lib=None) -> list[ProductionWire]:
    """Výrobní zapojovací seznam: každá žíla každého vodiče listů rozvaděčů (`attrs["prod"] == "0"` vynechá;
    můstky svorek nejsou vodiče). Nespínaná žíla vedená v JPS přes přístroj (PE vždy, N u přístroje bez pólu pro N)
    se sloučí do jednoho řádku mezi vnějšími konci („vede kolem Q1“; délka mezi vnějšími konci, koncovky jen na
    nich). Konce se srovnají (umístěné první, řada, pozice, označení, svorka), řádky podle listu (přirozeně), odkud,
    kam a žíly; čísla se přidělí po seřazení. `base` = `settings.json standard.wiring`."""
    from envocad.model.device_size import memo_lib
    from envocad.model.xref import DeviceIndex, natural_key
    lib = memo_lib(lib)        # artikly přístrojů (rozměry pro `terminal_point`) se čtou jednou
    index = DeviceIndex.build(project)
    sheets = [sheet] if sheet is not None else list(project.sheets)
    keyed: list[tuple[tuple, ProductionWire]] = []
    for s in sheets:
        if not s.is_switchboard:
            continue
        params = WiringParams.resolve(s.layout, base)
        segs = _segments(project, s, index, params, lib)
        rows = []
        for chain, a, b, devs in _chains(segs, _bypass_links(s, segs)):
            if b.key < a.key:
                a, b = b, a
            c = segs[chain[0]].c
            wires = [segs[i].w for i in chain]
            crosses = [wire_cross(project, s, w, params, index) for w in wires]
            cross, source = next((x for x in crosses if x[0] is None), None) or max(crosses, key=lambda x: x[0])
            types = list(dict.fromkeys((w.attrs.get("cable") or "").strip() or params.wire_type for w in wires))
            rows.append((chain, a, b, devs, c, wires, cross, source, types))
        spd_rows: list[tuple[ProductionWire, _End, _End]] = []
        clamps: dict[tuple, list[tuple[float | None, str]]] = {}
        for _chain, a, b, _devs, c, _wires, cross, _src, _types in rows:
            for end in (a, b):
                clamps.setdefault(_clamp_key(s, end, c), []).append((cross, _end_type(end, params)))
        for chain, a, b, devs, c, wires, cross, source, types in rows:
            wire_type = types[0]
            notes: list[str] = []
            if note := cross_note(cross, source):
                notes.append(note)
            if len(types) > 1:
                notes.append("úseky různého typu vodiče – ověřit")
            if devs:
                notes.append(f"vede kolem {', '.join(devs)}")
            ferr: list[tuple[str, Ferrule | None]] = []
            for end in (a, b):
                members = clamps.get(_clamp_key(s, end, c), [])
                n = len(members)
                twin, auto = False, True
                if n >= 3:
                    notes.append(f"{n} {'žíly' if n < 5 else 'žil'} ve svorce {end.text} – ověřit")
                elif n == 2:
                    (c1, t1), (c2, t2) = members
                    if c1 is None or c2 is None:
                        auto = False
                        notes.append("2 vodiče ve svorce, průřez neurčen – ověřit")
                    elif abs(c1 - c2) > 1e-9:
                        auto = False
                        notes.append("2 vodiče různého průřezu ve svorce – ověřit")
                    elif is_flexible(t1) and is_flexible(t2):
                        twin = True
                        if note := twin_clamp_note(end.element, end.text, c1):
                            notes.append(note)
                    else:
                        notes.append("2 vodiče ve svorce, jeden tuhý – ověřit")
                ferr.append(end_for(end.wire, end.side, cross, _end_type(end, params), twin=twin, auto=auto))
                name = end_name(end.element)
                if not devs and end.info.derived and c in UNSWITCHED_POLES and \
                        is_bypassed(s, end.element, end.port, c):
                    notes.append(f"{c} nespínaný – ve skutečnosti vede kolem {name}")
                if end.point is None:
                    notes.append("konec v uzlu odbočky" if end.element.symbol_id == JUNCTION else f"neumístěno: {name}")
                elif end.point.estimated:
                    notes.append(f"délka odhadem – {name}" if end.element.symbol_id == BUS
                                 else f"délka odhadem – {name} neumístěn")
            length = route_length_mm(a.point, b.point, s.layout, params) if a.point and b.point else None
            ref = "/".join(dict.fromkeys(r for w in wires if (r := (w.attrs.get("ref") or "").strip())))
            pw = ProductionWire(0, s.name, ref, c, a.text, b.text, cross, source, conductor_color(wires[0], c),
                                wire_type, length, ferr[0][0], ferr[1][0], ferr[0][1], ferr[1][1],
                                list(dict.fromkeys(notes)), a.wire.id, list(dict.fromkeys(w.id for w in wires)),
                                params.marking, local_from=local_end_text(s, a.text), local_to=local_end_text(s, b.text))
            keyed.append(((natural_key(s.name), a.key, b.key, canon_key(c)), pw))
            spd_rows.append((pw, a, b))
        _spd_branch_notes(spd_rows)
    keyed.sort(key=lambda kp: kp[0])
    out = [pw for _, pw in keyed]
    for i, pw in enumerate(out, start=1):
        pw.number = i
        pw.marker_from, pw.marker_to = wire_markers(pw)
    return out


SPD_BRANCH_MAX_MM = 500   # přívody k SPD a PE svodiče dohromady co nejkratší, nejvýš 0,5 m (ČSN EN 62305-4, 61643-32)


def twin_clamp_note(e: Element, text: str, cross: float | None) -> str:
    """Dvojitá dutinka ve svorce přístroje: vejde se? Podle atributu `cross_max` (max. průřez svorky z katalogu,
    `cross_max_mm2`) – dvojitá dutinka 2× S potřebuje svorku aspoň 2·S; bez údaje připomínka ověřit katalog.
    Svorkovnice a lišty se neřeší (svorky dimenzuje projektant podle průřezu)."""
    if cross is None or e.symbol_id in TERMINAL_BLOCK_SYMBOLS or e.symbol_id in NO_CROSS_SYMBOLS:
        return ""
    cmax = _parse_float(e.attrs.get("cross_max"))
    if cmax is None:
        return f"dvojitá dutinka 2×{_fmt(cross)} ve svorce {text} – ověřit rozsah svorky v katalogu"
    if 2 * cross > cmax + 1e-9:
        return f"dvojitá dutinka 2×{_fmt(cross)} se do svorky {text} (max {_fmt(cmax)} mm²) nevejde"
    return ""


def _spd_branch_notes(rows: list[tuple[ProductionWire, _End, _End]]) -> None:
    """Odbočka ke svodiči: přívod každé žíly k SPD + PE svodiče > 0,5 m → poznámka k řádkům odbočky (zkrátit).
    Počítají se jen délky mezi umístěnými konci (odhad u neumístěného prvku by jen šuměl)."""
    by_spd: dict[str, tuple[Element, list[ProductionWire], list[ProductionWire]]] = {}
    for pw, a, b in rows:
        for end in (a, b):
            if end.element.symbol_id != "fve.spd":
                continue
            _e, lines, pes = by_spd.setdefault(end.element.id, (end.element, [], []))
            (pes if end.port == "PE" else lines).append(pw)
    for e, lines, pes in by_spd.values():
        pe_len = max((pw.length_mm or 0 for pw in pes if not _estimated(pw)), default=0)
        for pw in lines:
            if pw.length_mm is None or _estimated(pw):
                continue
            total = pw.length_mm + pe_len
            if total > SPD_BRANCH_MAX_MM:
                note = (f"odbočka {element_name(e)}: {pw.conductor} + PE = {_fmt(total / 1000)} m > "
                        f"{_fmt(SPD_BRANCH_MAX_MM / 1000)} m – vést nejkratší cestou")
                for row in (pw, *pes):
                    if note not in row.notes:
                        row.notes.append(note)


def _estimated(pw: ProductionWire) -> bool:
    return any(n.startswith(("délka odhadem", "neumístěno")) for n in pw.notes)


def _end_type(end: _End, params: WiringParams) -> str:
    """Typ vodiče na konci (úsek, ke kterému konec patří)."""
    return (end.wire.attrs.get("cable") or "").strip() or params.wire_type
