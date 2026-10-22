"""Projekt → listy → elementy a vodiče. Čistá data, bez Qt."""
from __future__ import annotations

import contextlib
import copy
import dataclasses
import json
import logging
import math
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field, fields
from pathlib import Path

from envocad.model.busbar import BUS_SYMBOL, TAPS_ATTR, busbar_symbol
from envocad.model.designation import (
    CABLE_SCOPE,
    FUNC,
    LOC,
    LOCATION_SYMBOLS,
    element_name,
    scope_key,
    sheet_scope,
)
from envocad.model.feed import (
    FEED_SYMBOL,
    FEED_SYMBOLS,
    LEGACY_FEEDS,
    feed_link_key,
    feed_symbol,
    is_feed,
    is_feed_in,
    is_feed_out,
    normalize_legacy_element,
    normalize_legacy_fragment,
    other_link_key,
)
from envocad.model.symbol import Attribute, Port, Symbol, place_point, placeholder_symbol, with_orphan_ports

# Atributy vodiče (vodič nemá symbol, proto jsou definované zde)
WIRE_ATTRIBUTES = [
    Attribute("ref", "Označení", "", True),
    Attribute("cable", "Typ kabelu", "", True),
    Attribute("cross", "Průřez [mm²]", "", True),
    Attribute("length", "Délka [m]"),
    Attribute("route", "Trasa / uložení"),
    Attribute("method", "Uložení dle ČSN (A1/B1/C/D/E)"),
]

# Další atributy vnitřního vodiče rozvaděče (jen list rozvaděče, výrobní zapojovací seznam – `model/wiring.py`);
# prázdná hodnota = automaticky (barva podle žíly, koncovka podle průřezu a typu vodiče, vodič do seznamu patří)
SWITCHBOARD_WIRE_ATTRIBUTES = [
    Attribute("color", "Barva vodiče"),
    Attribute("end_a", "Koncovka A"),
    Attribute("end_b", "Koncovka B"),
    Attribute("prod", "Do výrobního seznamu (0 = ne)"),
]

FORMAT_VERSION = 16

MODULE_WIDTH = 17.5  # mm – šířka jednoho modulu na DIN liště
DEVICE_HEIGHT_MM = 45.0  # mm – výška modulového přístroje na liště (rozložení, délky vodičů)
SHEET_KINDS = ("schematic", "switchboard")
# Symboly, které nejsou přístroje k objednání ani na DIN lištu (propojení, odkazy, vnější prvky, kontakty – patří
# k přístroji své cívky); výkazy (`export/reports.py`) i rozložení (`Layout.devices`)
NON_DEVICE_SYMBOLS = {"fve.terminal", "fve.earth", "fve.grid", "fve.load", "fve.switchboard", FEED_SYMBOL,
                      "fve.interrupt", "ctl.contact_no", "ctl.contact_nc", "ctl.contact_power"}
# Šířka jedné řadové svorky pro rozložení, když skupina svorek nemá zadanou šířku (`modules`): 6,2 mm = běžná
# šroubová/pružinová průchozí svorka 2,5–4 mm² (Weidmüller, Phoenix, Bečov ~5,2–6,2 mm; push-in 1,5 mm² 3,5 mm,
# 10 mm² ~10 mm). Přesnou šířku lze zadat atributem `modules` skupiny (celé skupiny) nebo artiklem.
TERMINAL_WIDTH_MM = 6.2
AUTO_WIDTH_TERMINALS = {"sb.terminal_block"}


def terminal_count(e: Element) -> int:
    """Počet svorek skupiny podle atributu `terminal` („1 2 3 4 5“ → 5); jedno číslo nebo nic = 1 svorka."""
    toks = [t for t in re.split(r"[\s,;]+", str(e.attrs.get("terminal") or "")) if t]
    return max(len(toks), 1)


def terminal_group_modules(n: int, width_mm: float = TERMINAL_WIDTH_MM) -> float:
    """Šířka n svorek v modulech DIN (17,5 mm), na setiny."""
    return round(max(n, 0) * width_mm / MODULE_WIDTH, 2)


log = logging.getLogger("envocad.model")


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# ---- validace při načítání (poškozený soubor → ValueError s českou hláškou místo syrové výjimky) -----------
class CorruptProjectError(ValueError):
    """Soubor projektu je poškozený – zpráva je česky a míří na list / prvek / vodič."""


def _float(v, key: str) -> float:
    if isinstance(v, bool):
        raise ValueError(f"položka „{key}“ není číslo: {v!r}")  # noqa: TRY004 – poškozený soubor = ValueError
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"položka „{key}“ není číslo: {v!r}") from None
    if not math.isfinite(f):
        raise ValueError(f"položka „{key}“ není konečné číslo: {v!r}")
    return f


def _int(v, key: str) -> int:
    f = _float(v, key)
    if f != int(f):
        raise ValueError(f"položka „{key}“ není celé číslo: {v!r}")
    return int(f)


def _dict(v, key: str) -> dict:
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ValueError(f"položka „{key}“ má být objekt, je {type(v).__name__}")  # noqa: TRY004 – poškozený soubor = ValueError
    return v


def _list(v, key: str) -> list:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError(f"položka „{key}“ má být seznam, je {type(v).__name__}")  # noqa: TRY004 – poškozený soubor = ValueError
    return v


def _str_attrs(v, key: str = "attrs") -> dict[str, str]:
    """Atributy jako {str: str}; None → prázdné, čísla → text."""
    return {str(k): ("" if x is None else x if isinstance(x, str) else str(x)) for k, x in _dict(v, key).items()}


def _point(v, key: str) -> tuple[float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ValueError(f"položka „{key}“ má být bod [x, y], je {v!r}")
    return (_float(v[0], key), _float(v[1], key))


def _reason(ex: BaseException) -> str:
    if isinstance(ex, KeyError):
        return f"chybí položka „{ex.args[0] if ex.args else '?'}“"
    if isinstance(ex, ValueError) and str(ex):
        return str(ex)
    return f"neplatná data ({type(ex).__name__}: {ex})"


_LOAD_ERRORS = (KeyError, TypeError, ValueError, AttributeError, IndexError)


def _label(d, kind: str, k: int) -> str:
    """„prvek F1“ / „vodič W2“ / „prvek č. 3“ – pro hlášku o poškozeném souboru."""
    if isinstance(d, dict):
        attrs = d.get("attrs") if isinstance(d.get("attrs"), dict) else {}
        name = attrs.get("ref") or d.get("name") or d.get("ref") or d.get("label") or d.get("id")
        if name and isinstance(name, (str, int)):
            return f"{kind} „{name}“"
    return f"{kind} č. {k + 1}" if k >= 0 else kind


def _part(fn, d, where: str):
    if not isinstance(d, dict):
        raise CorruptProjectError(f"Soubor je poškozen: {where} – položka má být objekt")
    try:
        return fn(d)
    except CorruptProjectError:
        raise
    except _LOAD_ERRORS as ex:
        raise CorruptProjectError(f"Soubor je poškozen: {where} – {_reason(ex)}") from ex


@dataclass
class Element:
    """Instance symbolu na listu."""
    symbol_id: str
    x: float = 0.0
    y: float = 0.0
    rotation: int = 0  # 0/90/180/270
    attrs: dict[str, str] = field(default_factory=dict)
    component_id: str | None = None  # přiřazený artikl z knihovny
    mp_pos: tuple[float, float] | None = None  # ruční pozice ve vícepólu (None = automatické rozmístění)
    id: str = field(default_factory=_uid)
    mirror: bool = False  # zrcadleno podle svislé osy značky (před otočením, v10); popisky a texty se nezrcadlí
    sl_pos: tuple[float, float] | None = None  # ruční posun v jednopólovém schématu (dx, dy mm; v12), i podřízených

    @property
    def ref(self) -> str:
        return self.attrs.get("ref", "")

    @property
    def poles(self) -> int:
        try:
            return int(self.attrs.get("poles") or 1)
        except ValueError:
            return 1

    @property
    def modules(self) -> float:
        """Šířka přístroje v modulech (17,5 mm) pro rozložení na DIN liště. Skupina řadových svorek
        (`sb.terminal_block`) bez zadané šířky = počet svorek × `TERMINAL_WIDTH_MM` (`terminal_group_modules`)."""
        raw = str(self.attrs.get("modules") or "").strip()
        if not raw and self.symbol_id in AUTO_WIDTH_TERMINALS:
            return terminal_group_modules(terminal_count(self))
        try:
            return float((raw or "0").replace(",", "."))
        except ValueError:
            return 0.0

    def port_pos(self, symbol: Symbol, port_name: str) -> tuple[float, float]:
        p = symbol.port(port_name)
        rx, ry = place_point(p.x, p.y, self.rotation, self.mirror)
        return (self.x + rx, self.y + ry)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "symbol_id": self.symbol_id, "x": self.x, "y": self.y,
            "rotation": self.rotation, "attrs": self.attrs, "component_id": self.component_id,
            **({"mp_pos": list(self.mp_pos)} if self.mp_pos else {}),
            **({"mirror": True} if self.mirror else {}),
            **({"sl_pos": list(self.sl_pos)} if self.sl_pos else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Element:
        rot = _int(d.get("rotation") or 0, "rotation") % 360
        if rot % 90:
            raise ValueError(f"položka „rotation“ musí být násobek 90°: {d.get('rotation')!r}")
        cid = d.get("component_id")
        return cls(
            symbol_id=str(d["symbol_id"]), x=_float(d["x"], "x"), y=_float(d["y"], "y"), rotation=rot,
            attrs=_str_attrs(d.get("attrs")), component_id=str(cid) if cid else None, id=str(d["id"]),
            mp_pos=_point(d["mp_pos"], "mp_pos") if d.get("mp_pos") else None, mirror=d.get("mirror") is True,
            sl_pos=_point(d["sl_pos"], "sl_pos") if d.get("sl_pos") else None,
        )


# Barvy žil dle ČSN 33 0165 ed. 2 / HD 308 S2 (kabely CYKY, NYY…); DC podle zvyklosti FVE (červená +, černá −)
CORE_COLORS = {"L1": "hnědá", "L2": "černá", "L3": "šedá", "L": "hnědá", "N": "modrá", "PE": "zelenožlutá",
               "PEN": "zelenožlutá", "+": "červená", "-": "černá", "L+": "červená", "L-": "černá", "M": "modrá"}
# Označení žil dle ČSN EN 60445 (v11): stejnosměrné L+ / L− (kladný / záporný), střed M. Starší názvy z projektů
# do v10, maker a ručního zadání se při načtení převedou (`conductor_name`).
CONDUCTOR_ALIASES = {"DC+": "L+", "DC-": "L-", "DC−": "L-", "L−": "L-", "+DC": "L+", "-DC": "L-"}


def conductor_name(c: str) -> str:
    """Název žíly dle ČSN EN 60445: „DC+“ → „L+“, „DC−“/„DC-“ → „L-“; ostatní beze změny."""
    c = str(c).strip()
    return CONDUCTOR_ALIASES.get(c.upper(), c)


@dataclass
class Core:
    """Žíla kabelu."""
    name: str                  # L1, N, PE, DC+ … (shodné s Wire.conductors)
    number: str = ""           # číslo žíly (1…n) u číslovaných kabelů
    color: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "number": self.number, "color": self.color}


@dataclass
class Cable:
    """Kabel jako objekt (jako v EPLAN): typ, průřez, žíly s barvami, stínění, délka, trasa.
    Vodiče (Wire) na něj odkazují přes `cable_id`; jeden kabel může procházet více vodiči (přes svorky)."""
    ref: str
    type: str = ""
    cross: str = ""
    cores: list[Core] = field(default_factory=list)
    shield: bool = False
    length: str = ""
    route: str = ""
    note: str = ""
    component_id: str | None = None   # artikl kabelu z knihovny
    id: str = field(default_factory=_uid)

    def core(self, name: str) -> Core | None:
        return next((c for c in self.cores if c.name == name), None)

    def set_cores(self, names: list[str], keep_colors: bool = True) -> None:
        old = {c.name: c for c in self.cores}
        self.cores = []
        for i, n in enumerate(names, start=1):
            prev = old.get(n) if keep_colors else None
            self.cores.append(Core(n, prev.number if prev and prev.number else str(i),
                                   prev.color if prev and prev.color else CORE_COLORS.get(n, "")))

    def to_dict(self) -> dict:
        return {"id": self.id, "ref": self.ref, "type": self.type, "cross": self.cross,
                "cores": [c.to_dict() for c in self.cores], "shield": self.shield, "length": self.length,
                "route": self.route, "note": self.note, "component_id": self.component_id}

    @classmethod
    def from_dict(cls, d: dict) -> Cable:
        return cls(ref=d.get("ref", ""), type=d.get("type", ""), cross=d.get("cross", ""),
                   cores=[Core(conductor_name(c["name"]), c.get("number", ""), c.get("color", "")) for c in d.get("cores", [])],
                   shield=bool(d.get("shield")), length=d.get("length", ""), route=d.get("route", ""),
                   note=d.get("note", ""), component_id=d.get("component_id"), id=d["id"])


@dataclass
class WireEnd:
    element_id: str
    port: str

    def to_dict(self) -> dict:
        return {"element_id": self.element_id, "port": self.port}


@dataclass
class Wire:
    a: WireEnd
    b: WireEnd
    points: list[tuple[float, float]] = field(default_factory=list)  # mezilehlé body (lomy)
    attrs: dict[str, str] = field(default_factory=dict)  # označení, typ kabelu, průřez…
    conductors: list[str] = field(default_factory=list)  # příprava na vícepól: ["L1","L2","L3","N","PE"]
    # vícepól: přiřazení svorek per žíla, např. {"L1": {"a": "X1:1", "b": "F1:1"}}
    terminals: dict[str, dict[str, str]] = field(default_factory=dict)
    id: str = field(default_factory=_uid)

    @property
    def poles(self) -> int:
        return len(self.conductors) or int(self.attrs.get("poles") or 1)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "a": self.a.to_dict(), "b": self.b.to_dict(),
            "points": [list(p) for p in self.points], "attrs": self.attrs, "conductors": self.conductors,
            "terminals": self.terminals,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Wire:
        def end(key: str) -> WireEnd:
            e = _dict(d[key], key)
            return WireEnd(str(e["element_id"]), str(e["port"]))
        return cls(
            a=end("a"), b=end("b"),
            points=[_point(p, "points") for p in _list(d.get("points"), "points")], attrs=_str_attrs(d.get("attrs")),
            conductors=[conductor_name(c) for c in _list(d.get("conductors"), "conductors")],
            terminals={conductor_name(k): _str_attrs(v, "terminals") for k, v in _dict(d.get("terminals"), "terminals").items()},
            id=str(d["id"]),
        )

    def touches(self, element_id: str) -> bool:
        return self.a.element_id == element_id or self.b.element_id == element_id


@dataclass
class Placement:
    """Umístění přístroje v rozvaděči: řada (DIN lišta) a pozice v modulech od levého okraje."""
    element_id: str
    row: int = 0
    pos: float = 0.0

    def to_dict(self) -> dict:
        return {"element_id": self.element_id, "row": self.row, "pos": self.pos}


@dataclass
class Layout:
    """Fyzické rozložení rozvaděče – skříň s řadami DIN lišt."""
    rows: int = 3
    modules_per_row: int = 24
    enclosure: str = ""  # typ skříně (artikl / popis)
    placements: list[Placement] = field(default_factory=list)
    # parametry skříně (volné textové/číselné hodnoty – klíče viz ENCLOSURE_PARAMS)
    params: dict[str, str] = field(default_factory=dict)

    @property
    def width_mm(self) -> float:
        return _num(self.params.get("width_mm")) or self.modules_per_row * MODULE_WIDTH + 2 * 25

    @property
    def height_mm(self) -> float:
        return _num(self.params.get("height_mm")) or self.rows * 150 + 2 * 25

    @property
    def depth_mm(self) -> float:
        return _num(self.params.get("depth_mm"))

    @property
    def row_pitch_mm(self) -> float:
        """Rozteč řad DIN lišt (mm) – zadaná, nebo odvozená z výšky skříně."""
        return _num(self.params.get("row_pitch_mm")) or max(100.0, (self.height_mm - 50) / max(self.rows, 1))

    @property
    def outline_mm(self) -> tuple[float, float]:
        """Obrys skříně, jak ho kreslí rozložení (š, v): zadané rozměry, nejméně řady DIN lišt + 2 × 10 mm (lišty
        svisle i vodorovně na střed). Sdílí ho pohled rozložení i kontrola rozměrů (`device_size.size_problems`)."""
        inner_w, inner_h = self.modules_per_row * MODULE_WIDTH, self.rows * self.row_pitch_mm
        return max(self.width_mm, inner_w + 20), max(self.height_mm, inner_h + 20)

    @property
    def total_modules(self) -> int:
        return self.rows * self.modules_per_row

    def devices(self, sheet: Sheet, project: Project | None = None, lib=None) -> list[Element]:
        """Přístroje listu pro rozložení: šířka > 0, ne kontakt ani propojovací/vnější prvek (`NON_DEVICE_SYMBOLS`
        – kontakty jsou součástí přístroje své cívky) a položka výkazu (cívka stykače se nepočítá, když skupina má
        stykač na stejném listu – `xref.DeviceIndex.is_bom_device`). Cívka + hlavní kontakt = jeden přístroj
        (cívka). Bez `project` se skupiny hledají jen na listu. S knihovnou `lib` se šířka bere i z artiklu
        (`device_size.device_modules`), bez ní z atributu `modules`."""
        from envocad.model.device_size import device_modules, memo_lib
        from envocad.model.xref import DeviceIndex
        lib = memo_lib(lib)      # artikl se v rámci volání čte jednou
        idx = DeviceIndex.build(project) if project is not None else DeviceIndex.for_sheets([sheet])
        return [e for e in sheet.elements
                if e.symbol_id not in NON_DEVICE_SYMBOLS and device_modules(e, lib) > 0 and idx.is_bom_device(e, sheet)]

    def used_modules(self, sheet: Sheet, project: Project | None = None, lib=None) -> float:
        from envocad.model.device_size import device_modules, memo_lib
        lib = memo_lib(lib)
        devs = {e.id: e for e in self.devices(sheet, project, lib)}
        return sum(device_modules(devs[pl.element_id], lib) for pl in self.placements
                   if pl.element_id in devs and self.in_enclosure(pl))

    def in_enclosure(self, pl: Placement) -> bool:
        """Umístění leží v některé řadě skříně (po zmenšení počtu řad zůstanou umístění z vyšších řad v modelu
        – vrátí se po zvětšení počtu řad – ale do té doby se berou jako nerozmístěná)."""
        return 0 <= pl.row < self.rows

    def placement(self, eid: str) -> Placement | None:
        """Platné umístění přístroje (v řadě skříně), jinak None – přístroj je nerozmístěný."""
        pl = self.stored_placement(eid)
        return pl if pl is not None and self.in_enclosure(pl) else None

    def stored_placement(self, eid: str) -> Placement | None:
        """Uložené umístění včetně umístění mimo skříň (řada ≥ počet řad) – pro undo a kontrolu."""
        return next((p for p in self.placements if p.element_id == eid), None)

    def outside_placements(self) -> list[Placement]:
        """Uložená umístění mimo skříň (řada mimo rozsah 0…rows-1)."""
        return [p for p in self.placements if not self.in_enclosure(p)]

    def set_placement(self, eid: str, row: int | None, pos: float | None) -> None:
        self.placements = [p for p in self.placements if p.element_id != eid]
        if row is not None and pos is not None:
            self.placements.append(Placement(eid, row, pos))

    def to_dict(self) -> dict:
        return {"rows": self.rows, "modules_per_row": self.modules_per_row, "enclosure": self.enclosure,
                "params": self.params, "placements": [p.to_dict() for p in self.placements]}

    @classmethod
    def from_dict(cls, d: dict | None) -> Layout:
        d = _dict(d, "layout")
        pls = []
        for p in _list(d.get("placements"), "placements"):
            p = _dict(p, "placements")
            pls.append(Placement(str(p["element_id"]), _int(p.get("row", 0), "row"), _float(p.get("pos", 0), "pos")))
        return cls(rows=_int(d.get("rows", 3), "rows"), modules_per_row=_int(d.get("modules_per_row", 24), "modules_per_row"),
                   enclosure=str(d.get("enclosure") or ""), params=_str_attrs(d.get("params"), "params"),
                   placements=pls)


def _num(v) -> float:
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0


# Parametry skříně pro dialog a protokol: (klíč, popisek, výchozí)
ENCLOSURE_PARAMS = [
    ("manufacturer", "Výrobce", ""),
    ("type", "Typ / objednací číslo", ""),
    ("width_mm", "Šířka [mm]", ""),
    ("height_mm", "Výška [mm]", ""),
    ("depth_mm", "Hloubka [mm]", ""),
    ("row_pitch_mm", "Rozteč řad [mm]", "150"),
    ("ip", "Krytí IP", "IP 40"),
    ("ik", "Odolnost IK", ""),
    ("mounting", "Montáž", "nástěnná"),
    ("material", "Materiál", "plast"),
    ("door", "Dveře", "plné"),
    ("un", "Jmenovité napětí Un", "3×400/230 V, 50 Hz"),
    ("in_", "Jmenovitý proud In [A]", ""),
    ("icw", "Zkrat. odolnost [kA]", ""),
    ("network", "Síť / uzemnění", "TN-S"),
    ("reserve_pct", "Požadovaná rezerva [%]", "20"),
    ("t_ambient", "Teplota okolí [°C]", "35"),
    ("t_ambient_min", "Nejnižší teplota okolí [°C]", ""),   # nepovinné – kontrola dolních mezí přístrojů (t_min)
    ("rdf", "RDF (Ib/In)", "0,8"),
    ("note", "Poznámka", ""),
]

# Číselné parametry skříně: klíč → (min, max, min vyloučeno, jednotka pro hlášku). Prázdné pole = nezadáno.
ENCLOSURE_NUMERIC: dict[str, tuple[float, float, bool, str]] = {
    "width_mm": (0.0, 5000.0, True, "mm"), "height_mm": (0.0, 5000.0, True, "mm"),
    "depth_mm": (0.0, 2000.0, True, "mm"), "row_pitch_mm": (50.0, 1000.0, False, "mm"),
    "in_": (0.0, 10000.0, True, "A"), "icw": (0.0, 200.0, True, "kA"), "reserve_pct": (0.0, 100.0, False, "%"),
    "t_ambient": (-40.0, 60.0, False, "°C"), "t_ambient_min": (-60.0, 60.0, False, "°C"), "rdf": (0.0, 1.0, True, ""),
}


def enclosure_param_error(key: str, text: str) -> str | None:
    """Česká hláška pro neplatnou hodnotu číselného parametru skříně (není číslo, mimo rozsah – RDF 0–1, teplota
    okolí −40…60 °C…), jinak None. Prázdná hodnota a nečíselné parametry jsou vždy v pořádku."""
    rng = ENCLOSURE_NUMERIC.get(key)
    t = (text or "").strip()
    if rng is None or not t:
        return None
    label = next((lab for k, lab, _d in ENCLOSURE_PARAMS if k == key), key)
    lo, hi, lo_open, unit = rng
    try:
        v = float(t.replace(",", ".").replace(" ", ""))
    except ValueError:
        return f"{label}: „{t}“ není číslo"
    if not math.isfinite(v) or v > hi or v < lo or (lo_open and v == lo):
        u = f" {unit}" if unit and unit != "%" else unit
        span = f"větší než {lo:g} a nejvýše {hi:g}{u}" if lo_open else f"{lo:g} až {hi:g}{u}"
        return f"{label}: hodnota {t} je mimo rozsah ({span})"
    return None


def enclosure_number(params: dict[str, str], key: str, default: float) -> float:
    """Platná číselná hodnota parametru skříně, jinak (nezadaná / neplatná) `default`. Každý parametr zvlášť –
    neplatné RDF neshodí teplotu okolí."""
    t = (params.get(key) or "").strip()
    if not t or enclosure_param_error(key, t):
        return default
    return float(t.replace(",", ".").replace(" ", ""))



@dataclass
class StructureId:
    """Položka registru strukturního označení projektu (IEC 81346): aspekt + kód + popis."""
    aspect: str            # "=" funkce | "+" umístění
    code: str              # "AC", "RS1" – bez znaménka, jedna úroveň
    description: str = ""

    def to_dict(self) -> dict:
        return {"aspect": self.aspect, "code": self.code, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict) -> StructureId:
        return cls(aspect=d.get("aspect", LOC), code=d.get("code", ""), description=d.get("description", ""))


REVISION_KINDS = ("přidáno", "změněno", "odebráno")


@dataclass
class RevisionMark:
    """Značka revize ve výkresu (trojúhelník s písmenem revize)."""
    sheet_id: str
    target_id: str = ""       # "" = změna listu bez místa → jen popisové pole
    is_wire: bool = False
    kind: str = "změněno"     # přidáno | změněno | odebráno
    x: float | None = None    # pevná poloha – jen u odebraných
    y: float | None = None
    text: str = ""

    def to_dict(self) -> dict:
        return {"sheet_id": self.sheet_id, "target_id": self.target_id, "is_wire": self.is_wire, "kind": self.kind,
                "x": self.x, "y": self.y, "text": self.text}

    @classmethod
    def from_dict(cls, d: dict) -> RevisionMark:
        x, y = d.get("x"), d.get("y")
        return cls(sheet_id=d.get("sheet_id", ""), target_id=d.get("target_id", ""), is_wire=bool(d.get("is_wire")),
                   kind=d.get("kind", "změněno"), x=float(x) if x is not None else None,
                   y=float(y) if y is not None else None, text=d.get("text", ""))


@dataclass
class Revision:
    """Revize dokumentace: popis, značky ve výkresu, otisky listů při uzavření (měkký zámek)."""
    label: str
    date: str = ""
    author: str = ""
    description: str = ""
    closed: bool = False
    marks: list[RevisionMark] = field(default_factory=list)
    fingerprints: dict[str, str] = field(default_factory=dict)   # sheet_id → otisk při uzavření listu
    id: str = field(default_factory=_uid)
    # řádky změnového listu (`meta["changes"]`), které do revize zapsalo porovnání (`change_list_text`), v přesném
    # znění – opakované porovnání nahradí jen je, ručně psané řádky zůstanou. None = neznámé (starší soubor).
    # Ukládá se jako nepovinný klíč „auto_lines“ (starší program ho ignoruje, formát se nemění).
    auto_lines: list[str] | None = None

    def to_dict(self) -> dict:
        d = {"id": self.id, "label": self.label, "date": self.date, "author": self.author,
             "description": self.description, "closed": self.closed, "marks": [m.to_dict() for m in self.marks],
             "fingerprints": dict(self.fingerprints)}
        if self.auto_lines is not None:
            d["auto_lines"] = list(self.auto_lines)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Revision:
        return cls(label=str(d.get("label", "")), date=d.get("date", ""), author=d.get("author", ""),
                   description=d.get("description", ""), closed=bool(d.get("closed")),
                   marks=[RevisionMark.from_dict(m) for m in d.get("marks", [])],
                   fingerprints={str(k): str(v) for k, v in (d.get("fingerprints") or {}).items()},
                   id=d.get("id") or _uid(),
                   auto_lines=[str(x) for x in d["auto_lines"]] if isinstance(d.get("auto_lines"), list) else None)


NOTE_STATUSES = ("open", "resolved")          # UI „otevřeno“ / „vyřešeno“


@dataclass
class Note:
    """Připomínka (redline) – interní poznámka, není součástí dokumentace (diff/otisk ji ignorují).
    Bod (w = h = 0) má kotvu v (x, y), obdélník má v (x, y) levý dolní roh; mm, Y nahoru, na mřížce."""
    sheet_id: str
    x: float = 0.0
    y: float = 0.0
    text: str = ""
    no: int = 0                  # pořadové číslo v projektu, nepřečíslovává se
    w: float = 0.0               # 0 = bod; > 0 = obdélník
    h: float = 0.0
    target_id: str = ""          # informativní (skok, popis), poloha je absolutní
    is_wire: bool = False
    author: str = ""
    created: str = ""            # ISO „2026-10-16T14:05“
    status: str = "open"         # open | resolved
    reply: str = ""
    resolved_by: str = ""
    resolved: str = ""
    id: str = field(default_factory=_uid)

    @property
    def is_rect(self) -> bool:
        return self.w > 0 and self.h > 0

    def to_dict(self) -> dict:
        return {"id": self.id, "no": self.no, "sheet_id": self.sheet_id, "x": self.x, "y": self.y, "w": self.w,
                "h": self.h, "text": self.text, "target_id": self.target_id, "is_wire": self.is_wire,
                "author": self.author, "created": self.created, "status": self.status, "reply": self.reply,
                "resolved_by": self.resolved_by, "resolved": self.resolved}

    @classmethod
    def from_dict(cls, d: dict) -> Note:
        status = d.get("status", "open")
        return cls(sheet_id=d.get("sheet_id", ""), x=float(d.get("x") or 0.0), y=float(d.get("y") or 0.0),
                   text=d.get("text", ""), no=int(d.get("no") or 0), w=float(d.get("w") or 0.0),
                   h=float(d.get("h") or 0.0), target_id=d.get("target_id", ""), is_wire=bool(d.get("is_wire")),
                   author=d.get("author", ""), created=d.get("created", ""),
                   status=status if status in NOTE_STATUSES else "open", reply=d.get("reply", ""),
                   resolved_by=d.get("resolved_by", ""), resolved=d.get("resolved", ""), id=d.get("id") or _uid())


TEXT_HEIGHTS = (2.5, 3.5, 5.0, 7.0)   # výšky písma volného textu [mm] (ISO 3098)
TEXT_LINE = 1.4                        # řádkování víceřádkového textu (× výška)


@dataclass
class SheetText:
    """Volný text listu (v10): poznámka, nadpis části výkresu. (x, y) = levý bod základny prvního řádku [mm, Y nahoru];
    další řádky (zalomení v `text`) jsou pod ním po `TEXT_LINE` × výška. Kreslí se ve výkresu, PDF i DXF; nepatří
    k prvku a do výkazů nejde."""
    x: float = 0.0
    y: float = 0.0
    text: str = ""
    height: float = 2.5
    id: str = field(default_factory=_uid)

    def lines(self) -> list[str]:
        return self.text.splitlines() or [""]

    def to_dict(self) -> dict:
        return {"id": self.id, "x": self.x, "y": self.y, "text": self.text, "height": self.height}

    @classmethod
    def from_dict(cls, d: dict) -> SheetText:
        h = _float(d.get("height", 2.5), "height")
        if not 0.5 <= h <= 50:
            raise ValueError(f"položka „height“ textu mimo rozsah 0,5–50 mm: {h}")
        return cls(x=_float(d.get("x", 0), "x"), y=_float(d.get("y", 0), "y"), text=str(d.get("text") or ""),
                   height=h, id=str(d.get("id") or _uid()))


@dataclass
class Sheet:
    name: str = "Blokové schéma"
    paper: str = "A3"
    width: float = 420.0
    height: float = 297.0
    elements: list[Element] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)
    kind: str = "schematic"               # "schematic" | "switchboard"
    parent_element_id: str | None = None  # blok ROZVADĚČ na nadřazeném listu, který tento list reprezentuje
    layout: Layout = field(default_factory=Layout)
    # můstky (propoje) svorkovnic tohoto listu: {"X2": [["1", "6", "11"], ["2", "7", "12"]]} – čísla svorek spojená můstkem
    bridges: dict[str, list[list[str]]] = field(default_factory=dict)
    # strukturní označení listu (IEC 81346) – výchozí aspekty prvků a vodičů listu; kódy bez znaménka
    func: str = ""                        # "=" funkce
    loc: str = ""                         # "+" umístění (list rozvaděče = označení bloku)
    # formát stran vícepólu a plánu svorkovnice listu rozvaděče („A4“, „A4 na výšku“, „A3“, „list“ = rozměr listu);
    # prázdné = podle firemního standardu (`multipole.paper_choice`). Nepovinný klíč – ukládá se, jen když je zadaný.
    mp_paper: str = ""
    id: str = field(default_factory=_uid)
    texts: list[SheetText] = field(default_factory=list)   # volné texty listu (v10)

    @property
    def is_switchboard(self) -> bool:
        return self.kind == "switchboard"

    def element(self, eid: str) -> Element:
        for e in self.elements:
            if e.id == eid:
                return e
        raise KeyError(eid)

    def remove_element(self, eid: str) -> list[Wire]:
        """Odstraní element a všechny jeho vodiče; vrátí odstraněné vodiče (pro undo)."""
        removed = [w for w in self.wires if w.touches(eid)]
        self.wires = [w for w in self.wires if not w.touches(eid)]
        self.elements = [e for e in self.elements if e.id != eid]
        self.layout.set_placement(eid, None, None)
        return removed

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "paper": self.paper, "width": self.width, "height": self.height,
            "kind": self.kind, "parent_element_id": self.parent_element_id, "layout": self.layout.to_dict(),
            "elements": [e.to_dict() for e in self.elements], "wires": [w.to_dict() for w in self.wires],
            "bridges": self.bridges, "func": self.func, "loc": self.loc,
            **({"mp_paper": self.mp_paper} if self.mp_paper else {}),
            **({"texts": [t.to_dict() for t in self.texts]} if self.texts else {}),
        }

    def text(self, tid: str) -> SheetText:
        for t in self.texts:
            if t.id == tid:
                return t
        raise KeyError(tid)

    def restore_state(self, d: dict) -> None:
        """Nastaví list na stav `d` (z `to_dict`) na místě – objekt listu zůstane (drží ho pohledy a příkazy undo).
        Prvky a vodiče, které se nezměnily, zůstanou stejné objekty; ostatní se vytvoří z `d`."""
        new = Sheet.from_dict(d)
        old_el = {e.id: e for e in self.elements}
        old_w = {w.id: w for w in self.wires}
        elements = [old_el[e.id] if e.id in old_el and old_el[e.id].to_dict() == e.to_dict() else e
                    for e in new.elements]
        wires = [old_w[w.id] if w.id in old_w and old_w[w.id].to_dict() == w.to_dict() else w for w in new.wires]
        for f in fields(Sheet):
            setattr(self, f.name, getattr(new, f.name))
        self.elements, self.wires = elements, wires

    @classmethod
    def from_dict(cls, d: dict) -> Sheet:
        where = _label(d, "list", -1)
        def part(fn, kind):
            key = "elements" if kind == "prvek" else "wires"
            return [_part(fn, x, f"{where}, {_label(x, kind, k)}") for k, x in enumerate(_list(d.get(key), key))]
        pid = d.get("parent_element_id")
        sid = str(d["id"])
        raw_texts = _list(d.get("texts"), "texts")
        texts = [_part(SheetText.from_dict, x, f"{where}, text {k + 1}") for k, x in enumerate(raw_texts)]
        for k, (x, t) in enumerate(zip(raw_texts, texts, strict=True)):
            if not x.get("id"):
                # text bez id (ručně psaný soubor): stálé id z listu a pořadí – náhodné by při každém otevření změnilo
                # otisk listu a uzavřená revize by hlásila falešné „změněno po uzavření“
                t.id = f"{sid}.t{k + 1}"
        return cls(
            name=str(d.get("name") or ""), paper=str(d.get("paper") or "A3"), width=_float(d.get("width", 420), "width"),
            height=_float(d.get("height", 297), "height"),
            kind=d.get("kind") if d.get("kind") in SHEET_KINDS else "schematic",
            parent_element_id=str(pid) if pid else None,
            layout=Layout.from_dict(d.get("layout")),
            elements=part(Element.from_dict, "prvek"),
            wires=part(Wire.from_dict, "vodič"), id=sid,
            bridges={str(k): [[str(x) for x in _list(g, "bridges")] for g in _list(v, "bridges")]
                     for k, v in _dict(d.get("bridges"), "bridges").items()},
            func=str(d.get("func") or ""), loc=str(d.get("loc") or ""),
            mp_paper=str(d.get("mp_paper") or ""),
            texts=texts,
        )


@dataclass
class Project:
    name: str = "Nový projekt"
    meta: dict[str, str] = field(default_factory=dict)  # investor, číslo zakázky, místo, zpracoval…
    sheets: list[Sheet] = field(default_factory=lambda: [Sheet()])
    cables: list[Cable] = field(default_factory=list)
    structures: list[StructureId] = field(default_factory=list)   # registr kódů =funkce / +umístění s popisy
    revisions: list[Revision] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)   # připomínky (redlining), viz model/notes.py
    path: Path | None = None
    # kabely odebrané `sync_cables` (žádný vodič na ně neodkazuje): id → (pořadí, kabel). Vrátí-li se vodič s tímto
    # `cable_id` (undo smazání, redo vložení), kabel se obnoví beze změny i na původním místě. Neukládá se.
    removed_cables: dict[str, tuple[int, Cable]] = field(default_factory=dict, repr=False, compare=False)
    # kabely osiřelé už v načteném souboru (žádný vodič JPS na ně neodkazuje): `sync_cables` je při otevření
    # neodebere (ruční barvy žil, artikl) – odebírá jen kabely osiřelé změnou v této relaci. Kontrola je hlásí
    # jako INFO (`cable_no_wire`). Vodič, který se na takový kabel naváže, ho z množiny vyřadí. Neukládá se.
    loaded_orphan_cables: set[str] = field(default_factory=set, repr=False, compare=False)

    # ---- strukturní označení ------------------------------------------
    def structure(self, aspect: str, code: str) -> StructureId | None:
        return next((x for x in self.structures if x.aspect == aspect and x.code == code), None)

    # ---- kabely ------------------------------------------------------
    def cable(self, cid: str) -> Cable | None:
        return next((c for c in self.cables if c.id == cid), None)

    def cable_by_ref(self, ref: str) -> Cable | None:
        return next((c for c in self.cables if c.ref == ref), None) if ref else None

    def cable_of_wire(self, w: Wire) -> Cable | None:
        """Kabel vodiče: podle `cable_id`, jinak podle označení vodiče (W2 = kabel W2)."""
        cid = w.attrs.get("cable_id", "")
        return (self.cable(cid) if cid else None) or self.cable_by_ref(w.attrs.get("ref", ""))

    # ---- svorkovnice (můstky patří listu – svorkovnice X1 je v každém rozvaděči jiná) ----------
    def bridge_groups(self, strip: str, sheet: Sheet) -> list[list[str]]:
        return [list(g) for g in sheet.bridges.get(strip, [])]

    def set_bridges(self, strip: str, groups: list[list[str]], sheet: Sheet) -> None:
        groups = [[str(x).strip() for x in g if str(x).strip()] for g in groups]
        groups = [g for g in groups if len(g) >= 2]
        if groups:
            sheet.bridges[strip] = groups
        else:
            sheet.bridges.pop(strip, None)

    def bridge_of(self, strip: str, number: str, sheet: Sheet) -> list[str]:
        """Skupina svorek propojených můstkem se svorkou `strip:number` (včetně ní), nebo []."""
        for g in sheet.bridges.get(strip, []):
            if number in g:
                return list(g)
        return []

    # ---- označení prvků ---------------------------------------------
    def used_refs(self, sheet: Sheet | None = None) -> set[str]:
        """Použitá označení. S `sheet` jen ta ve stejném prostoru označení (`scope_key`) jako výchozí hodnoty listu
        (jako EPLAN „+RDC1-X1“: X1 smí být v každém umístění) a k tomu označení vodičů ve stejném prostoru jako
        vodiče listu (vodiče JPS = kabely sdílejí jeden prostor celého projektu)."""
        if sheet is None:
            refs = {e.ref for s in self.sheets for e in s.elements if e.ref and e.symbol_id not in CONTACT_SYMBOLS}
            refs |= {w.attrs.get("ref", "") for s in self.sheets for w in s.wires if w.attrs.get("ref")}
            return refs
        el_scope = sheet_scope(sheet)
        wire_scope = el_scope if sheet.is_switchboard else CABLE_SCOPE
        refs = {e.ref for s in self.sheets for e in s.elements
                if e.ref and e.symbol_id not in CONTACT_SYMBOLS and scope_key(s, e) == el_scope}
        refs |= {w.attrs["ref"] for s in self.sheets for w in s.wires
                 if w.attrs.get("ref") and scope_key(s, w) in (el_scope, wire_scope)}
        return refs

    def next_ref(self, prefix: str) -> str:
        if not prefix:
            return ""
        used = self.used_refs()
        n = 1
        while f"{prefix}{n}" in used:
            n += 1
        return f"{prefix}{n}"

    # ---- listy -------------------------------------------------------
    def sheet(self, sid: str) -> Sheet:
        for s in self.sheets:
            if s.id == sid:
                return s
        raise KeyError(sid)

    def sheet_of_element(self, eid: str) -> Sheet | None:
        for s in self.sheets:                 # první list s prvkem (prostá smyčka – volá se tisíckrát za generování)
            for e in s.elements:
                if e.id == eid:
                    return s
        return None

    def switchboard_sheet(self, block_element_id: str) -> Sheet | None:
        """List rozvaděče reprezentovaný blokem na nadřazeném listu (nebo None)."""
        return next((s for s in self.sheets if s.parent_element_id == block_element_id), None)

    def create_switchboard_sheet(self, block: Element) -> Sheet:
        """Založí list rozvaděče pro blok ROZVADĚČ (pokud už existuje, vrátí ho)."""
        existing = self.switchboard_sheet(block.id)
        if existing:
            return existing
        name = block.ref or "Rozvaděč"
        desc = block.attrs.get("desc", "")
        sheet = Sheet(name=f"{name} – {desc}" if desc else name, kind="switchboard", parent_element_id=block.id,
                      loc=block.ref)
        self.sheets.append(sheet)
        block.attrs["sheet"] = sheet.name
        if block.ref and self.structure(LOC, block.ref) is None:
            self.structures.append(StructureId(LOC, block.ref, desc))
        return sheet

    def remove_sheet(self, sheet: Sheet) -> list[Sheet]:
        """Odstraní list. Blok ROZVADĚČ smazaného listu rozvaděče zůstane (vodiče na jeho porty zůstanou, porty bez
        přívodu se kreslí jako „X1?“ a hlásí je kontrola); listy rozvaděčů, jejichž blok byl na smazaném listu, se
        odpojí (`parent_element_id` = None). Vrací odpojené listy."""
        self.sheets.remove(sheet)
        if sheet.parent_element_id:
            ps = self.sheet_of_element(sheet.parent_element_id)
            if ps is not None and self.switchboard_sheet(sheet.parent_element_id) is None:
                ps.element(sheet.parent_element_id).attrs.pop("sheet", None)
        ids = {e.id for e in sheet.elements}
        orphans = [s for s in self.sheets if s.parent_element_id in ids]
        for s in orphans:
            s.parent_element_id = None
        return orphans

    def switchboards(self) -> list[Sheet]:
        return [s for s in self.sheets if s.is_switchboard]

    # ---- serializace -------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "format": "envocad-project", "format_version": FORMAT_VERSION,
            "name": self.name, "meta": self.meta, "sheets": [s.to_dict() for s in self.sheets],
            "cables": [c.to_dict() for c in self.cables],
            "structures": [x.to_dict() for x in self.structures],
            "revisions": [r.to_dict() for r in self.revisions],
            "notes": [n.to_dict() for n in self.notes],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Project:
        """Projekt ze slovníku (vstup se nemění). Poškozená struktura → `CorruptProjectError` (ValueError) s českou
        hláškou „Soubor je poškozen: list X, prvek Y – …“. Odkazy uvnitř projektu se nevalidují: vodič na
        neexistující prvek se načte (kreslení ho přeskočí, kontrola hlásí `dangling`), duplicitní id prvků a vodičů
        dostanou nová id."""
        if not isinstance(d, dict) or d.get("format") != "envocad-project":
            raise ValueError("Soubor není projekt EnvoCAD")
        ver = d.get("format_version", 1)
        if isinstance(ver, bool) or not isinstance(ver, (int, float)) or ver != int(ver) or ver < 1:
            raise CorruptProjectError(f"Soubor je poškozen: neplatná verze formátu {ver!r}")
        ver = int(ver)
        if ver > FORMAT_VERSION:
            raise ValueError(f"Projekt je z novější verze programu (formát {ver})")
        _check_shape(d)
        try:
            d = migrate(d, ver)
        except _LOAD_ERRORS as ex:
            raise CorruptProjectError(f"Soubor je poškozen: převod ze starší verze formátu – {_reason(ex)}") from ex
        sheets = [_part(Sheet.from_dict, sd, _label(sd, "list", k)) for k, sd in enumerate(_top(d, "sheets"))]
        proj = cls(name=str(d.get("name") or ""), meta=_part(lambda x: _str_attrs(x, "meta"), d.get("meta") or {}, "meta"),
                   sheets=sheets or [Sheet()],
                   cables=[_part(Cable.from_dict, c, _label(c, "kabel", k)) for k, c in enumerate(_top(d, "cables"))],
                   structures=[_part(StructureId.from_dict, x, f"struktura č. {k + 1}")
                               for k, x in enumerate(_top(d, "structures"))],
                   revisions=[_part(Revision.from_dict, r, _label(r, "revize", k)) for k, r in enumerate(_top(d, "revisions"))],
                   notes=[_part(Note.from_dict, n, f"připomínka č. {k + 1}") for k, n in enumerate(_top(d, "notes"))])
        _repair_duplicate_ids(proj)
        if ver < 16:
            from envocad.model.diff import upgrade_fingerprints  # diff importuje project – až tady
            upgrade_fingerprints(proj)
        proj.loaded_orphan_cables = {c.id for c in orphan_cables(proj)}
        return proj

    def save(self, path: Path | str | None = None) -> None:
        """Uloží projekt atomicky (zápis do dočasného souboru + přejmenování) a ponechá zálohu předchozí verze
        „<název>.ecp.bak“. Při chybě zůstane původní soubor beze změny a `path` se nemění."""
        p = Path(path) if path else self.path
        if p is None:
            raise ValueError("Projekt nemá cestu")
        write_json_atomic(self.to_dict(), p, backup=True)
        self.path = p

    @classmethod
    def load(cls, path: Path | str) -> Project:
        p = Path(path)
        proj = cls.from_dict(read_project_json(p))
        proj.path = p
        return proj


def dangling_wires(sheet: Sheet) -> list[Wire]:
    """Vodiče listu, jejichž konec vede na prvek, který na listu není (ručně upravený / poškozený soubor)."""
    ids = {e.id for e in sheet.elements}
    return [w for w in sheet.wires if w.a.element_id not in ids or w.b.element_id not in ids]


def without_dangling(project: Project) -> Project:
    """Pohled na projekt bez vodičů na neexistující prvky – pro kontroly, výkazy a export, které s takovým vodičem
    neumí počítat. Bez visících vodičů vrací `project` samotný, jinak mělkou kopii (listy jsou kopie se stejným id,
    prvky a ostatní vodiče sdílené; model se nemění). Visící vodiče hlásí kontrola (`dangling`)."""
    import dataclasses
    if not any(dangling_wires(s) for s in project.sheets):
        return project
    sheets = []
    for s in project.sheets:
        bad = {w.id for w in dangling_wires(s)}
        sheets.append(dataclasses.replace(s, wires=[w for w in s.wires if w.id not in bad]) if bad else s)
    # vlastní seznam kabelů: `sync_cables` nad pohledem (výkazy) by jinak odebral z modelu kabel visícího vodiče
    return dataclasses.replace(project, sheets=sheets, cables=list(project.cables), removed_cables={})


def _check_shape(d: dict) -> None:
    """Tvar dat před migrací (migrace starších verzí sahá do listů, prvků a vodičů): seznamy a objekty tam, kde
    mají být – jinak hláška s listem a prvkem / vodičem."""
    for k, sd in enumerate(_top(d, "sheets")):
        where = _label(sd, "list", k)
        if not isinstance(sd, dict):
            raise CorruptProjectError(f"Soubor je poškozen: {where} – položka má být objekt")
        for key, kind in (("elements", "prvek"), ("wires", "vodič")):
            try:
                items = _list(sd.get(key), key)
            except ValueError as ex:
                raise CorruptProjectError(f"Soubor je poškozen: {where} – {ex}") from None
            for i, x in enumerate(items):
                if not isinstance(x, dict):
                    raise CorruptProjectError(f"Soubor je poškozen: {where}, {_label(x, kind, i)} – položka má být objekt")
                if kind == "vodič":
                    for end in ("a", "b"):
                        if end not in x:
                            raise CorruptProjectError(f"Soubor je poškozen: {where}, {_label(x, kind, i)} – "
                                                      f"chybí položka „{end}“")
                        if not isinstance(x[end], dict) or "element_id" not in x[end] or "port" not in x[end]:
                            raise CorruptProjectError(f"Soubor je poškozen: {where}, {_label(x, kind, i)} – konec "
                                                      f"„{end}“ musí mít element_id a port")


def clean_view(project: Project, sheet: Sheet | None = None) -> tuple[Project, Sheet | None]:
    """`without_dangling` + odpovídající list v čistém pohledu (pro export / výkaz jednoho listu)."""
    clean = without_dangling(project)
    if clean is project or sheet is None:
        return clean, sheet
    return clean, next((s for s in clean.sheets if s.id == sheet.id), sheet)


def _top(d: dict, key: str) -> list:
    try:
        return _list(d.get(key), key)
    except ValueError as ex:
        raise CorruptProjectError(f"Soubor je poškozen: {ex}") from None


def _repair_duplicate_ids(proj: Project) -> None:
    """Duplicitní id listů / prvků / vodičů (ručně upravený soubor, např. list zkopírovaný v JSON) → nové id pro
    druhý a další výskyt, a to tak, aby se nic nerozbilo: po přeznačení prvku na listu se přepíší konce vodičů,
    umístění ve skříni, značky revizí a připomínky téhož listu, `parent_element_id` listu rozvaděče, který blok
    podle atributu „sheet“ reprezentuje, a vazby přívodů/vývodů (`wire_id`) listů rozvaděčů pod tímto listem.
    Duplicita uvnitř jednoho listu je nejednoznačná: vodiče dál vedou na první prvek s daným id (`Sheet.element`).
    Volné texty listu (`Sheet.texts`) mají id jedinečná v projektu; duplicita dostane stálé id „<id>.<n>“ (na id
    textu nic neodkazuje, ale náhodné id by měnilo otisk listu při každém otevření)."""
    seen_s: set[str] = set()
    seen_e: dict[str, Element] = {}   # id → první prvek s tímto id (předchozí listy)
    seen_w: set[str] = set()
    marks = [m for r in proj.revisions for m in r.marks]
    for s in proj.sheets:
        if s.id in seen_s:
            log.warning("duplicitní id listu %s – nové id", s.id)
            s.id = _uid()
        seen_s.add(s.id)
        emap: dict[str, str] = {}
        local: dict[str, Element] = {}
        for e in s.elements:
            old = e.id
            if old in local or old in seen_e:
                e.id = _uid()
                log.warning("duplicitní id prvku %s (%s) – nové id %s", old, e.ref, e.id)
                if old not in local:
                    # první výskyt na listu, id už má prvek jiného listu → odkazy listu patří tomuto prvku
                    emap[old] = e.id
                    _repoint_switchboard(proj, seen_e[old], e, old)
                local.setdefault(old, e)
            local.setdefault(e.id, e)
        for e in s.elements:
            seen_e.setdefault(e.id, e)
        wmap: dict[str, str] = {}
        local_w: set[str] = set()
        for w in s.wires:
            old = w.id
            if old in local_w or old in seen_w:
                w.id = _uid()
                log.warning("duplicitní id vodiče %s – nové id %s", old, w.id)
                if old not in local_w:
                    wmap[old] = w.id
                local_w.add(old)
            local_w.add(w.id)
        seen_w |= {w.id for w in s.wires}
        _remap_sheet_refs(proj, s, emap, wmap, marks)
    _repair_text_ids(proj)


def _repair_text_ids(proj: Project) -> None:
    used = {t.id for s in proj.sheets for t in s.texts}
    seen: set[str] = set()
    for s in proj.sheets:
        for t in s.texts:
            if t.id in seen:
                old, n = t.id, 2
                while f"{old}.{n}" in used:
                    n += 1
                t.id = f"{old}.{n}"
                used.add(t.id)
                log.warning("duplicitní id textu %s (list %s) – nové id %s", old, s.name, t.id)
            seen.add(t.id)


def _repoint_switchboard(proj: Project, first: Element | None, renamed: Element, old: str) -> None:
    """Blok ROZVADĚČ dostal nové id: list rozvaděče s `parent_element_id` = staré id převezme, jen když ho podle
    atributu „sheet“ (jméno listu) reprezentuje právě přeznačený blok, a ne první blok se stejným id."""
    name = renamed.attrs.get("sheet", "")
    if not name or (first is not None and first.attrs.get("sheet", "") == name):
        return
    for sb in proj.sheets:
        if sb.parent_element_id == old and sb.name == name:
            sb.parent_element_id = renamed.id
            return


def _remap_sheet_refs(proj: Project, s: Sheet, emap: dict[str, str], wmap: dict[str, str],
                      marks: list[RevisionMark]) -> None:
    """Po přeznačení prvků / vodičů listu `s` přepíše odkazy, které na ně z listu (a z listů pod ním) vedou."""
    if not emap and not wmap:
        return
    for w in s.wires:
        for end in (w.a, w.b):
            end.element_id = emap.get(end.element_id, end.element_id)
    for pl in s.layout.placements:
        pl.element_id = emap.get(pl.element_id, pl.element_id)
    for x in [*marks, *proj.notes]:
        if x.sheet_id == s.id and x.target_id:
            x.target_id = (wmap if x.is_wire else emap).get(x.target_id, x.target_id)
    if not wmap:
        return
    blocks = {e.id for e in s.elements}
    for sb in proj.sheets:
        if sb.parent_element_id in blocks:
            for f in sb.elements:
                if f.symbol_id in FEED_SYMBOLS and f.attrs.get("wire_id") in wmap:
                    f.attrs["wire_id"] = wmap[f.attrs["wire_id"]]


def read_project_json(path: Path | str) -> dict:
    """Načte JSON projektu (UTF-8, i s BOM). Nečitelný obsah → `CorruptProjectError` s českou hláškou."""
    p = Path(path)
    data = p.read_bytes()
    if not data.strip():
        raise CorruptProjectError("Soubor je poškozen: soubor je prázdný")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CorruptProjectError("Soubor je poškozen: není to textový soubor UTF-8 (projekt EnvoCAD je JSON)") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as ex:
        raise CorruptProjectError(f"Soubor je poškozen: neplatný JSON (řádek {ex.lineno}, sloupec {ex.colno}) – "
                                  "soubor je asi useknutý nebo ručně upravený") from None
    except RecursionError:
        raise CorruptProjectError("Soubor je poškozen: příliš hluboce vnořený JSON") from None


def write_json_atomic(data: dict, path: Path | str, backup: bool = False) -> None:
    """Zapíše JSON do `<cesta>.tmp` ve stejné složce a přejmenuje ho na cíl (`os.replace` – atomické). S `backup`
    nejdřív zkopíruje dosavadní soubor na `<cesta>.bak` (jedna záloha předchozí verze). Při chybě zůstane cíl
    beze změny a dočasný soubor se smaže. Symbolický odkaz zůstane odkazem (zapisuje se do cíle odkazu, `.tmp`
    i `.bak` vedle cíle) a nový soubor převezme oprávnění dosavadního (`shutil.copymode`)."""
    p = Path(os.path.realpath(path))
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = p.with_name(p.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if p.is_file():
            try:
                shutil.copymode(p, tmp)
            except OSError as ex:   # oprávnění jsou jen pojistka – uložení kvůli nim neselže
                log.warning("oprávnění %s nejde převzít: %s", p, ex)
        if backup and p.is_file():
            try:
                shutil.copy2(p, p.with_name(p.name + ".bak"))
            except OSError as ex:   # záloha je jen pojistka – uložení kvůli ní neselže
                log.warning("záloha %s se nevytvořila: %s", p, ex)
        os.replace(tmp, p)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def migrate(d: dict, ver: int) -> dict:
    """Převede slovník projektu ze starší verze formátu na aktuální. Vstupní slovník se nemění (pracuje na kopii)."""
    d = copy.deepcopy(d)
    if ver < 2:
        # v1: listy bez kind/layout, vodiče bez conductors – doplní se výchozí hodnoty při from_dict
        for s in d.get("sheets", []):
            s.setdefault("kind", "schematic")
    if ver < 3:
        d.setdefault("bridges", {})  # v3: můstky svorkovnic
    # v4: volitelné `mp_pos` prvku (ruční pozice ve vícepólu) – bez migrace
    # v12: volitelné `sl_pos` prvku (ruční posun v jednopólovém schématu) – bez migrace
    # v6: `cables` – kabely jako objekty; vytvoří se z vodičů při načtení (sync_cables)
    if ver < 5:
        # v5: FV string má jeden port DC (pár DC+/DC- jsou žíly), střídač porty DC1/DC2 místo DC+/DC-
        port_map = {"fve.pv_string": {"DC+": "DC", "DC-": "DC"},
                    "fve.inverter": {"DC+": "DC1", "DC-": "DC2"}, "fve.inverter_hybrid": {"DC+": "DC1", "DC-": "DC2"}}
        for s in d.get("sheets", []):
            sym_of = {e["id"]: e["symbol_id"] for e in s.get("elements", [])}
            for w in s.get("wires", []):
                for end in (w["a"], w["b"]):
                    m = port_map.get(sym_of.get(end["element_id"], ""))
                    if m and end["port"] in m:
                        end["port"] = m[end["port"]]
                if not w.get("conductors") and any(
                        sym_of.get(end["element_id"]) in port_map for end in (w["a"], w["b"])):
                    w["conductors"] = ["L+", "L-"]
    if ver < 7 and d.get("bridges"):
        # v7: můstky patří listu (svorkovnice X1 je v každém rozvaděči jiná) – přesun k listu, kde svorkovnice je
        sheets = d.get("sheets", [])
        for strip, groups in d["bridges"].items():
            target = next((s for s in sheets if any(e.get("attrs", {}).get("ref") == strip for e in s.get("elements", []))),
                          None) or next((s for s in sheets if s.get("kind") == "switchboard"), None) or (sheets[0] if sheets else None)
            if target is not None:
                target.setdefault("bridges", {})[strip] = groups
        d.pop("bridges", None)
    if ver < 8:
        # v8: strukturní označení (Sheet.func/loc, Project.structures) a revize (Project.revisions).
        # List rozvaděče dostane umístění = označení svého bloku (dosud implicitní vlastní prostor označení).
        sheets = d.get("sheets", [])
        el_by_id = {e["id"]: e for s in sheets for e in s.get("elements", []) if "id" in e}
        structs = d.setdefault("structures", [])
        for s in sheets:
            s.setdefault("func", "")
            loc = ""
            if s.get("kind") == "switchboard":
                blk = el_by_id.get(s.get("parent_element_id") or "")
                attrs = (blk or {}).get("attrs") or {}
                loc = attrs.get("ref", "")      # beze změny textu – nevalidní kód ohlásí kontrola
                if loc and not any(x.get("aspect") == LOC and x.get("code") == loc for x in structs):
                    structs.append({"aspect": LOC, "code": loc, "description": attrs.get("desc", "")})
            s.setdefault("loc", loc)
        if not d.get("revisions"):
            d["revisions"] = _revisions_from_meta(d.get("meta") or {})
    if ver < 9:
        # v9: připomínky (Project.notes). Starší program v9 odmítne místo tichého zahození připomínek při uložení.
        d.setdefault("notes", [])
    # v10: zrcadlení prvku (`Element.mirror`, jen když je True) a volné texty listu (`Sheet.texts`) – nepovinné,
    # bez migrace dat. Starší program v10 odmítne místo tichého zahození zrcadlení a textů při uložení.
    if ver < 11:
        # v11: žíly dle ČSN EN 60445 – DC+ / DC− → L+ / L− (vodiče, svorky žil a kabely převádí už `from_dict`
        # přes `conductor_name`); tady atribut `conductors` prvků (svorky, póly ve vícepólu)
        for s in d.get("sheets", []):
            for e in s.get("elements", []):
                attrs = e.get("attrs") or {}
                if isinstance(attrs.get("conductors"), str) and attrs["conductors"]:
                    toks = attrs["conductors"].replace(",", " ").replace(";", " ").split()
                    attrs["conductors"] = " ".join(conductor_name(t) for t in toks)
    if ver < 13:
        # v13: jedna značka přívodu/vývodu `sb.feed` se směrem `attrs.dir` místo `sb.feed_in` / `sb.feed_out`.
        # Bezztrátově: port `1` zůstane na stejném místě se stejným směrem (přívod se pootočí o 180°), vodiče,
        # `mp_pos`, `sl_pos` i vazby se nemění a nic se nepřeskládá. Starší program v13 odmítne (`sb.feed` nezná).
        # Značka `mp_legacy` drží vícepól starého listu beze změny (`multipole.flow_flipped` ho neotáčí).
        for s in d.get("sheets", []):
            for e in s.get("elements", []):
                normalize_legacy_element(e, mark=True)
    # v14: parametrická sběrnice `sb.busbar` (atributy `taps` / `outs` / `tap_pitch`, `model/busbar.py`) – bez migrace
    # dat (sběrnice bez `taps` kreslí pevnou geometrii jako dřív). Verze se zvedla jen proto, aby program v13 soubor
    # odmítl: atributy by sice zachoval, ale kreslil by pevnou sběrnici (přívody B{k} jinde, B13+ osiřelé porty).
    # v15: blok rozvaděče bez listu s porty z atributů `ports_in` / `ports_out` (a jištěním portů `protect`) – bez
    # migrace dat (blok bez atributů se kreslí jako dřív). Verze se zvedla jen proto, aby program v14 soubor odmítl:
    # blok bez listu by kreslil se základní značkou a vodiče na jeho porty jako osiřelé „X1?“ (chyba `bad_port`).
    # v16: otisk listu (`diff.sheet_fingerprint`) zahrnuje volné texty listu. Data se nemění; otisky uzavřených revizí
    # převádí `Project.from_dict` nad hotovými listy (`diff.upgrade_fingerprints`). Verze se zvedla, aby program v15
    # u listu s texty nehlásil falešné „změněno po uzavření revize“.
    d["format_version"] = FORMAT_VERSION
    return d


# Texty, které generátor / šablony / makra skládají z označení jiného prvku – při přejmenování se přepíší
# (ručně psané texty zůstávají). „{}“ = označení jako samostatné slovo.
AUTO_TEXT_TEMPLATES = ("od {}", "{} dál", "string {}", "DC rozvaděč u {}", "DC rozvaděč po trase {}")


@dataclass(frozen=True)
class TextChange:
    """Změna textu navázaná na přejmenování: `kind` = "element" (atribut `key` prvku `target_id`), "wire"
    (atribut vodiče), "cable" (označení kabelu, `key` = "ref", `model.renumber`), "sheet"
    (název listu `target_id`) nebo "wire_port" (port konce `key` = "a"/"b" vodiče `target_id` – konec vodiče JPS
    na bloku ROZVADĚČ po přejmenování přívodu/vývodu, `feed_port_followups`). U „element“ znamená `old` None
    chybějící klíč – undo ho odebere (odvozené atributy nové vazby přívodu, `SetAttrCommand`)."""
    kind: str
    target_id: str
    key: str
    old: str | None
    new: str


def _auto_text_rename(text: str, old: str, new: str) -> str | None:
    """Automaticky vygenerovaný text s označením `old` (podle `AUTO_TEXT_TEMPLATES`, volitelně s „ (2)“ na konci)
    → text s `new`; jiný text → None."""
    m = re.fullmatch(r"(.*?)( \(\d+\))?", text or "")
    body, tail = m.group(1), m.group(2) or ""
    for tpl in AUTO_TEXT_TEMPLATES:
        if body == tpl.format(old):
            return tpl.format(new) + tail
    return None


def _rename_related(project: Project, element: Element):
    """Predikát (list, prvek) → souvisí prvek s přejmenovaným `element` natolik, že jeho text podle šablony
    odkazuje právě na něj? Ano, když je ve stejném prostoru označení (`scope_key`), nebo leží na listu rozvaděče,
    jehož přívod/vývod je navázaný (`linked_wire`, `wire_id` / port bloku) na vodič vedoucí k `element`. Prvky
    jiného prostoru označení (jiné func/loc s vlastním T1) bez takové vazby → ne."""
    from envocad.model.designation import scope_key
    home = project.sheet_of_element(element.id)
    target = scope_key(home, element) if home is not None else None
    touching = {w.id for s in project.sheets for w in s.wires if w.touches(element.id)}
    linked: set[str] = set()     # listy rozvaděčů s přívodem/vývodem navázaným na vodič k `element`
    if touching:
        for s in project.sheets:
            if not s.is_switchboard:
                continue
            for f in s.elements:
                if f.symbol_id in FEED_SYMBOLS:
                    hit = linked_wire(project, s, f)
                    if hit is not None and hit[1].id in touching:
                        linked.add(s.id)
                        break

    def related(s: Sheet, e: Element) -> bool:
        return s.id in linked or (target is not None and scope_key(s, e) == target)
    return related


def rename_followups(project: Project, element: Element, old: str, new: str) -> list[TextChange]:
    """Co se má změnit spolu s přejmenováním prvku `old` → `new` (jeden krok undo v GUI):
    - blok ROZVADĚČ: název jeho listu začínající starým označením („RDC1 – …“ → „RDC5 – …“) a atribut `sheet` bloku;
    - automaticky vygenerované popisy (`AUTO_TEXT_TEMPLATES`: „od T1“, „G1 dál“, „string G1“, „DC rozvaděč u T1“)
      ostatních prvků, kde je staré označení samostatným slovem, a názvy listů rozvaděčů, které takový popis nesou –
      jen u prvků, které s přejmenovaným prokazatelně souvisejí (`_rename_related`: stejný prostor označení, nebo
      list rozvaděče s přívodem/vývodem navázaným na vodič k němu). Stejný text v jiném prostoru označení (=B s
      vlastním T1) se nemění. Ručně psané texty se nemění;
    - přívod/vývod rozvaděče: port navázaného vodiče JPS na bloku („X1“ → „X5“, `feed_port_followups`)."""
    if not old or not new or old == new:
        return []
    out: list[TextChange] = []
    sheet_names: dict[str, str] = {}

    def rename_sheet(s: Sheet, name: str) -> None:
        if name != sheet_names.get(s.id, s.name):
            sheet_names[s.id] = name

    if element.symbol_id == "fve.switchboard":
        s = project.switchboard_sheet(element.id)
        if s is not None and (s.name == old or s.name.startswith(old + " ")):
            rename_sheet(s, new + s.name[len(old):])
    related = _rename_related(project, element)
    for s in project.sheets:
        for e in s.elements:
            if e is element:
                continue
            desc = e.attrs.get("desc", "")
            nd = _auto_text_rename(desc, old, new)
            if nd is None or not related(s, e):
                continue
            out.append(TextChange("element", e.id, "desc", desc, nd))
            if e.symbol_id == "fve.switchboard":
                bs = project.switchboard_sheet(e.id)
                cur = sheet_names.get(bs.id, bs.name) if bs is not None else ""
                if bs is not None and cur.endswith(" – " + desc):
                    rename_sheet(bs, cur[: -len(desc)] + nd)
    if element.symbol_id in FEED_SYMBOLS:
        home = project.sheet_of_element(element.id)
        if home is not None:
            out += feed_port_followups(project, home, element, new)
    for sid, name in sheet_names.items():
        s = project.sheet(sid)
        out.append(TextChange("sheet", sid, "name", s.name, name))
        block = None
        if s.parent_element_id:
            ps = project.sheet_of_element(s.parent_element_id)
            block = ps.element(s.parent_element_id) if ps is not None else None
        if block is not None and block.attrs.get("sheet") == s.name:
            out.append(TextChange("element", block.id, "sheet", s.name, name))
    return out


def apply_text_changes(project: Project, changes: list[TextChange], undo: bool = False) -> None:
    """Provede (nebo s `undo` vrátí) změny z `rename_followups`."""
    els = {e.id: e for s in project.sheets for e in s.elements}
    wires = {w.id: w for s in project.sheets for w in s.wires}
    for c in (reversed(changes) if undo else changes):
        val = c.old if undo else c.new
        if c.kind == "wire_port":
            w = wires.get(c.target_id)
            if w is not None and c.key in ("a", "b"):
                getattr(w, c.key).port = val
        elif c.kind == "sheet":
            try:
                project.sheet(c.target_id).name = val
            except KeyError:
                continue
        elif c.kind == "wire":
            w = wires.get(c.target_id)
            if w is not None:
                if val is None:
                    w.attrs.pop(c.key, None)
                else:
                    w.attrs[c.key] = val
        elif c.kind == "cable":
            cab = next((k for k in project.cables if k.id == c.target_id), None)
            if cab is not None and c.key == "ref":
                cab.ref = val or ""
        elif c.target_id in els:
            if val is None:
                els[c.target_id].attrs.pop(c.key, None)
            else:
                els[c.target_id].attrs[c.key] = val


def rename_structure(project: Project, aspect: str, old: str, new: str) -> int:
    """Přejmenuje kód struktury `aspect` („=“/„+“) ze `old` na `new` v registru, na listech (`func`/`loc`)
    i v overridech prvků (`attrs func/loc`). Vrací počet změněných míst. Kód `new`, který už v projektu existuje
    (v registru nebo použitý), → ValueError – sloučení by nešlo vrátit (undo = přejmenování zpět)."""
    if aspect not in (FUNC, LOC):
        raise ValueError(f"Neznámý aspekt {aspect!r}")
    if not old or not new or old == new:
        return 0
    key = "func" if aspect == FUNC else "loc"
    used = {getattr(s, key) for s in project.sheets} | {e.attrs.get(key, "") for s in project.sheets for e in s.elements}
    if project.structure(aspect, new) is not None or new in used:
        what = "Funkce" if aspect == FUNC else "Umístění"
        raise ValueError(f"{what} {aspect}{new} už v projektu existuje")
    n = 0
    for x in project.structures:
        if x.aspect == aspect and x.code == old:
            x.code = new
            n += 1
    for s in project.sheets:
        if getattr(s, key) == old:
            setattr(s, key, new)
            n += 1
        for e in s.elements:
            if e.attrs.get(key) == old:
                e.attrs[key] = new
                n += 1
    return n


REVISION_HEADER_LABELS = {"rev", "rev.", "revize", "revision", "index"}
MAX_REVISION_LABEL = 8


def _is_revision_label(label: str) -> bool:
    """Krátké označení revize z řádku změnového listu („A“, „B1“, „03“) – ne hlavička („Rev“, „Revize“) ani věta."""
    return (bool(label) and len(label) <= MAX_REVISION_LABEL and not any(ch.isspace() for ch in label)
            and label.lower() not in REVISION_HEADER_LABELS)


def _revisions_from_meta(meta: dict) -> list[dict]:
    """Revize z textového změnového listu `meta["changes"]` (řádky „rev | datum | popis | zpracoval“): jedna uzavřená
    revize na označení v pořadí výskytu, datum a autor z prvního vyplněného řádku, popis = popisy řádků pod sebou.
    Bez značek a otisků. Bere jen řádky s aspoň dvěma částmi a krátkým označením bez mezer (`_is_revision_label`) –
    hlavička tabulky a volný text se přeskočí. `meta["revision"]`, které v seznamu není, se přidá jako poslední
    otevřená revize."""
    revs: dict[str, dict] = {}
    for line in str(meta.get("changes") or "").splitlines():
        parts = [x.strip() for x in line.split("|")]
        label = parts[0]
        if len(parts) < 2 or not _is_revision_label(label):
            continue                             # volný text, nadpis, hlavička tabulky
        date, desc, author = (parts + ["", "", ""])[1:4]
        if len(parts) > 4:                       # „|“ v popisu – autor je poslední část
            desc, author = " | ".join(parts[2:-1]), parts[-1]
        r = revs.setdefault(label, Revision(label, closed=True).to_dict())
        r["date"] = r["date"] or date
        r["author"] = r["author"] or author
        if desc:
            r["description"] = f"{r['description']}\n{desc}" if r["description"] else desc
    out = list(revs.values())
    cur = str(meta.get("revision") or "").strip()
    if cur and cur not in revs:
        out.append(Revision(cur, author=str(meta.get("author") or "")).to_dict())
    return out


def switchboard_header(project: Project, sheet: Sheet) -> list[tuple[str, str]]:
    """Dvojice (popisek, hodnota) pro informační blok na listu rozvaděče – jen vyplněné položky."""
    lay = sheet.layout
    p = lay.params
    enclosure = " ".join(x for x in (p.get("manufacturer", ""), p.get("type", "")) if x) or lay.enclosure
    dims = f"{lay.width_mm:g} × {lay.height_mm:g}" + (f" × {lay.depth_mm:g}" if lay.depth_mm else "") + " mm"
    rows = [
        ("Rozvaděč", sheet.name),
        ("Zakázka", " ".join(x for x in (project.name, project.meta.get("order", "")) if x)),
        ("Skříň", enclosure),
        ("Rozměry", dims if p.get("width_mm") or p.get("height_mm") else ""),
        ("Moduly", f"{lay.rows} × {lay.modules_per_row} = {lay.total_modules} M"),
        ("Un", p.get("un", "")),
        ("In", f"{p['in_']} A" if p.get("in_") else ""),
        ("Icw / Ipk", f"{p['icw']} kA" if p.get("icw") else ""),
        ("Síť", p.get("network", "")),
        ("Krytí", " / ".join(x for x in (p.get("ip", ""), p.get("ik", "")) if x)),
        ("Montáž", p.get("mounting", "")),
        ("Materiál / dveře", " / ".join(x for x in (p.get("material", ""), p.get("door", "")) if x)),
    ]
    return [(k, v) for k, v in rows if v]


def switchboard_title(project: Project, sheet: Sheet) -> list[str]:
    """Hlavička rozvaděče na schématu (styl ENVO): označení, soustava/napětí/proud/zkrat, skříň a krytí."""
    p = sheet.layout.params
    block = project.sheet_of_element(sheet.parent_element_id) if sheet.parent_element_id else None
    ref = block.element(sheet.parent_element_id).ref if block is not None else ""
    lines = [ref or sheet.name]
    sysline = ", ".join(x for x in (p.get("network", ""), p.get("un", ""),
                                    f"In = {p['in_']} A" if p.get("in_") else "",
                                    f"Ik'' = {p['icw']} kA" if p.get("icw") else "") if x)
    if sysline:
        lines.append(sysline)
    enc = ", ".join(x for x in (p.get("material", "") or " ".join(x for x in (p.get("manufacturer", ""), p.get("type", "")) if x),
                                p.get("mounting", ""), "/".join(x for x in (p.get("ip", ""), p.get("ik", "")) if x)) if x)
    if enc:
        lines.append(enc)
    return lines


# Atributy vazeb, které kopie nesmí převzít: vodič odkazuje na objekt kabelu originálu (`cable_id`), přívod/vývod
# rozvaděče na vodič JPS originálu (`wire_id`) a texty z té vazby odvozené (odkud/kam, kabel)
WIRE_LINK_ATTRS = ("cable_id",)
FEED_LINK_ATTRS = ("wire_id", "from", "to", "cable")


def detach_wire_attrs(attrs: dict[str, str]) -> dict[str, str]:
    """Atributy vodiče pro kopii / makro: bez `cable_id` – kopie dostane vlastní kabel podle nového označení."""
    return {k: v for k, v in attrs.items() if k not in WIRE_LINK_ATTRS}


def detach_element_attrs(symbol_id: str, attrs: dict[str, str]) -> dict[str, str]:
    """Atributy prvku pro kopii / makro: přívod/vývod navázaný na vodič JPS (`wire_id`) vazbu ani z ní odvozené texty
    (odkud/kam, kabel) nepřevezme – naváže se znovu podle portu bloku. Nenavázaný si ruční texty nechá."""
    if symbol_id not in FEED_SYMBOLS or not attrs.get("wire_id"):
        return dict(attrs)
    return {k: ("" if k in FEED_LINK_ATTRS else v) for k, v in attrs.items()}


def detach_fragment(fragment: dict) -> dict:
    """Výřez bez vazeb na originál (`detach_wire_attrs`, `detach_element_attrs`); vstup se nemění."""
    out = copy.deepcopy(fragment)
    for d in out.get("elements", []):
        if isinstance(d, dict) and isinstance(d.get("attrs"), dict):
            d["attrs"] = detach_element_attrs(str(d.get("symbol_id", "")), d["attrs"])
    for d in out.get("wires", []):
        if isinstance(d, dict) and isinstance(d.get("attrs"), dict):
            d["attrs"] = detach_wire_attrs(d["attrs"])
    return out


def copy_prefix(e: Element, iec_prefix: str) -> str:
    """Předpona označení kopie: blok rozvaděče podle svého označení („RDC1“ → „RDC“, jako ostatní bloky projektu),
    ostatní prvky podle značky (iec_ref)."""
    if e.symbol_id in LOCATION_SYMBOLS:
        m = re.match(r"([^\d\s]+)\d+$", e.ref or "")
        if m:
            return m.group(1)
    return iec_prefix


def copy_fragment(sheet: Sheet, element_ids: list[str]) -> dict:
    """Výřez listu pro schránku a uložení makra: vybrané prvky + vodiče mezi nimi (čistá data, přenositelná mezi
    listy), bez vazeb na originál (`detach_fragment` – kabel vodiče, vazba přívodu na vodič JPS)."""
    ids = set(element_ids)
    els = [e.to_dict() for e in sheet.elements if e.id in ids]
    wires = [w.to_dict() for w in sheet.wires if w.a.element_id in ids and w.b.element_id in ids]
    return detach_fragment({"elements": els, "wires": wires})


def paste_fragment(project: Project, fragment: dict, ref_prefix_of, dx: float = 10.0, dy: float = -10.0
                   ) -> tuple[list[Element], list[Wire]]:
    """Vytvoří kopie s novými id a označeními (F1 → další volné; blok rozvaděče RDC1 → RDC2, `copy_prefix`),
    posunuté o (dx, dy). Skupiny svorek si nechají označení svorkovnice, čísla svorek se vymažou (doplní automatické
    číslování). Vodiče nepřevezmou kabel originálu (`cable_id`), přívody vazbu na vodič JPS. Nic nevkládá do listu."""
    used = project.used_refs()
    idmap: dict[str, str] = {}
    els: list[Element] = []
    if any(isinstance(d, dict) and d.get("symbol_id") in LEGACY_FEEDS for d in fragment.get("elements", [])):
        fragment = copy.deepcopy(fragment)      # schránka ze starší verze: sb.feed_in/out → sb.feed + dir
        normalize_legacy_fragment(fragment)
    for d in fragment.get("elements", []):
        e = Element.from_dict(d)
        new = Element(symbol_id=e.symbol_id, x=e.x + dx, y=e.y + dy, rotation=e.rotation, mirror=e.mirror,
                      attrs=detach_element_attrs(e.symbol_id, e.attrs), component_id=e.component_id)
        prefix = copy_prefix(e, ref_prefix_of(e.symbol_id))
        if e.symbol_id in ("sb.terminal_block", "fve.terminal"):
            new.attrs["terminal"] = ""
        elif e.ref and prefix:
            n = 1
            while f"{prefix}{n}" in used:
                n += 1
            new.attrs["ref"] = f"{prefix}{n}"
            used.add(new.attrs["ref"])
        if "sheet" in new.attrs:
            new.attrs["sheet"] = ""
        idmap[e.id] = new.id
        els.append(new)
    wires: list[Wire] = []
    for d in fragment.get("wires", []):
        w = Wire.from_dict(d)
        nw = Wire(WireEnd(idmap[w.a.element_id], w.a.port), WireEnd(idmap[w.b.element_id], w.b.port),
                  points=[(x + dx, y + dy) for x, y in w.points], attrs=detach_wire_attrs(w.attrs),
                  conductors=list(w.conductors))
        if nw.attrs.get("ref"):
            n = 1
            while f"W{n}" in used:
                n += 1
            nw.attrs["ref"] = f"W{n}"
            used.add(nw.attrs["ref"])
        wires.append(nw)
    return els, wires




def parent_sheet(project: Project, sheet: Sheet) -> Sheet | None:
    """Nadřazený list (JPS), na kterém je blok ROZVADĚČ tohoto listu."""
    if not sheet.parent_element_id:
        return None
    return project.sheet_of_element(sheet.parent_element_id)


def wire_choices(project: Project, sheet: Sheet) -> list[tuple[str, str]]:
    """Vodiče nadřazeného listu nabízené přívodu/vývodu rozvaděče: (wire_id, popis)."""
    ps = parent_sheet(project, sheet)
    if ps is None:
        return []
    out = []
    for w in ps.wires:
        a, b = ps.element(w.a.element_id), ps.element(w.b.element_id)
        label = f"{w.attrs.get('ref') or '(bez označení)'}: {element_name(a)}:{w.a.port} → {element_name(b)}:{w.b.port}"
        cable = " ".join(x for x in (w.attrs.get("cable", ""), w.attrs.get("cross", "")) if x)
        if cable:
            label += f"  [{cable}]"
        out.append((w.id, label))
    return out


def linked_wire(project: Project, sheet: Sheet, e: Element) -> tuple[Sheet, Wire] | None:
    """Vodič JPS navázaný na přívod/vývod (atribut `wire_id`)."""
    wid = e.attrs.get("wire_id", "")
    if wid:
        for s in project.sheets:
            for w in s.wires:
                if w.id == wid:
                    return s, w
    w = feed_wire_by_port(project, sheet, e)  # bez ruční vazby: podle portu bloku se jménem svorky
    ps = parent_sheet(project, sheet)
    return (ps, w) if (w is not None and ps is not None) else None


def feed_link_attrs(project: Project, sheet: Sheet, e: Element, wire_id: str) -> dict[str, str]:
    """Atributy přívodu/vývodu odvozené z navázaného vodiče JPS (odkud/kam, kabel). Jen klíče, které k prvku
    patří: přívod „from“, vývod „to“ (zrušení vazby nepřidá prázdný klíč, který prvek neměl)."""
    key = feed_link_key(e)
    e2 = Element(symbol_id=e.symbol_id, attrs={"wire_id": wire_id})
    hit = linked_wire(project, sheet, e2)
    if hit is None:
        return {"wire_id": "", key: "", "cable": ""} if not wire_id else {}
    s, w = hit
    block = sheet.parent_element_id
    far_end = w.b if w.a.element_id == block else w.a
    far, far_port, far_sheet = s.element(far_end.element_id), far_end.port, s
    if far.symbol_id == INTERRUPT_SYMBOL:   # kabel přes listy JPS: skutečný konec za přerušením („W3 T1:AC /2.C4“)
        from envocad.model.xref import through_interrupt
        thru = through_interrupt(project, s, far, far_port)   # jen hlavní úsek s pokračováním za protějškem
        if thru is not None:
            far_sheet, far, far_port = thru.sheet, thru.element, thru.port
    from envocad.model.frame import position_ref
    text = (f"{w.attrs.get('ref', '')} {element_name(far)}:{far_port} "
            f"{position_ref(project, far_sheet, far.x, far.y)}").strip()
    cable = " ".join(x for x in (w.attrs.get("cable", ""), w.attrs.get("cross", "")) if x)
    return {"wire_id": wire_id, key: text, "cable": cable}


def feed_dir_changes(project: Project, sheet: Sheet, e: Element) -> dict[str, str]:
    """Navázané změny atributů po změně směru přívodu/vývodu (`dir` už je nový): navázaný přívod (list rozvaděče,
    vazba na vodič JPS) dostane odkud/kam a kabel znovu z vazby a klíč starého směru se vyprázdní; bez vazby se
    ručně psaný text přesune z „Odkud“ do „Kam“ (nebo naopak). Vrací {klíč: nová hodnota} jen se skutečnými změnami."""
    if not is_feed(e):
        return {}
    key, other = feed_link_key(e), other_link_key(e)
    out: dict[str, str] = {}
    hit = linked_wire(project, sheet, e) if sheet.is_switchboard else None
    if hit is not None:
        for k, v in feed_link_attrs(project, sheet, e, hit[1].id).items():
            if k != "wire_id" and e.attrs.get(k, "") != v:
                out[k] = v
        if e.attrs.get(other):
            out[other] = ""
    elif e.attrs.get(other) and not e.attrs.get(key):
        out[key], out[other] = e.attrs[other], ""
    return out


def feeds_linked_to(project: Project, wire_id: str) -> list[tuple[Sheet, Element]]:
    """Přívody/vývody rozvaděčů navázané na vodič JPS (pro křížový odkaz u vodiče)."""
    out = []
    for s in project.sheets:
        for e in s.elements:
            if e.symbol_id not in FEED_SYMBOLS:
                continue
            hit = linked_wire(project, s, e)
            if hit is not None and hit[1].id == wire_id:
                out.append((s, e))
    return out


def wire_label(attrs: dict, conductors: list[str] | None = None) -> str:
    """Popisek vodiče ve výkresu: označení + typ kabelu + průřez. Průřez se vynechá, když ho typ kabelu už
    obsahuje („1x6“); u jednožilového kabelu s více žílami (string DC+/DC−) se doplní počet: „2× H1Z2Z2-K 1x6“."""
    parts = [attrs.get("ref", "")]
    cable, cross = attrs.get("cable", ""), attrs.get("cross", "")
    if cross and re.search(rf"([x×]\s*|\s){re.escape(cross)}(\b|$)", cable):
        cross = ""          # průřez už je v typu („1x6“) – jen se doplní jednotka
    if cable and conductors and len(conductors) > 1 and re.search(r"(^|\s)1\s*[x×]\s*\d", cable):
        cable = f"{len(conductors)}× {cable}"
    text = " ".join(x for x in (cable, cross) if x)
    if text:
        parts.append(text + ("" if "mm" in text or not (cross or attrs.get("cross")) else " mm²"))
    return "  ".join(x for x in parts if x)


def feed_link_index(project: Project) -> dict[str, list[tuple[Sheet, Element]]]:
    """{id vodiče JPS: [(list rozvaděče, přívod/vývod)…]} – spočítat jednou, pak se ptát za každý vodič
    (výkazy a překreslení s 800 vodiči by jinak procházely všechny přívody × vodiče pokaždé). Vazba jako
    `linked_wire` (ruční `wire_id`, jinak vodič na portu bloku se jménem přívodu), jen přes mapy postavené jednou
    – vodiče podle id, list prvku a konce vodičů nadřazeného listu (vždy první výskyt, jako lineární hledání)."""
    out: dict[str, list[tuple[Sheet, Element]]] = {}
    wires: dict[str, tuple[Sheet, Wire]] | None = None
    owner: dict[str, Sheet] | None = None
    ends: dict[int, dict[tuple[str, str], Wire]] = {}       # nadřazený list → {(prvek, port): první vodič}
    for s in project.sheets:
        for e in s.elements:
            if e.symbol_id not in FEED_SYMBOLS:
                continue
            if wires is None:
                wires, owner = {}, {}
                for s2 in project.sheets:
                    for w in s2.wires:
                        wires.setdefault(w.id, (s2, w))
                    for e2 in s2.elements:
                        owner.setdefault(e2.id, s2)
            wid = e.attrs.get("wire_id", "")
            hit = wires.get(wid) if wid else None
            if hit is None and s.parent_element_id and e.ref:       # `feed_wire_by_port`
                ps = owner.get(s.parent_element_id)
                if ps is not None:
                    by_end = ends.get(id(ps))
                    if by_end is None:
                        by_end = ends[id(ps)] = {}
                        for w in ps.wires:
                            for end in (w.a, w.b):
                                by_end.setdefault((end.element_id, end.port), w)
                    w = by_end.get((s.parent_element_id, e.ref))
                    if w is not None:
                        hit = (ps, w)
            if hit is not None:
                out.setdefault(hit[1].id, []).append((s, e))
    return out


def wire_xref(project: Project, wire_id: str, index: dict[str, list[tuple[Sheet, Element]]] | None = None) -> str:
    """Text křížového odkazu k vodiči JPS: „→ R1:X1“. `index` = `feed_link_index()` pro hromadné volání."""
    parts = []
    links = index.get(wire_id, []) if index is not None else feeds_linked_to(project, wire_id)
    for s, e in links:
        block = project.sheet_of_element(s.parent_element_id) if s.parent_element_id else None
        bname = ""
        if block is not None:
            bname = block.element(s.parent_element_id).ref
        from envocad.model.frame import position_ref
        pos = position_ref(project, s, e.x, e.y)
        parts.append((f"{bname or s.name}:{e.ref}" if e.ref else (bname or s.name)) + f" {pos}")
    return ("→ " + ", ".join(parts)) if parts else ""


# ---- blok ROZVADĚČ s porty podle přívodů/vývodů listu rozvaděče -------------------------------------------
PORT_PITCH = 10.0
# Blok rozvaděče bez listu (formát v15): porty z atributů bloku – přívody vlevo `ports_in`, vývody vpravo `ports_out`
# (označení oddělená mezerou / čárkou: „XIN“, „X1 X2“). Nepovinné; s listem se přidají za přívody / vývody listu
# (porty, které list nemá). Generátor tak kreslí stávající RD / HR / RE a RFVE.AC bez mustru jen jako blok v blokovém
# schématu (docs/NAVRH_TOPOLOGIE.md, kap. 8 bod 12). `protect` = jištění portů bloku bez listu („X1=63, X3=40“, A) –
# kontrola kabelů (`calc.check_cables`) porovná In s Iz kabelu na portu, když za ním není list s přístrojem.
BLOCK_PORTS_IN = "ports_in"
BLOCK_PORTS_OUT = "ports_out"
BLOCK_PROTECT = "protect"


def _split_names(v) -> list[str]:
    out: list[str] = []
    for t in re.split(r"[\s,;]+", str(v or "")):
        if t and t not in out:
            out.append(t)
    return out


def block_port_names(e: Element) -> tuple[list[str], list[str]]:
    """Porty bloku rozvaděče z atributů (`ports_in`, `ports_out`) – (přívody, vývody); jméno jen jednou."""
    ins = _split_names(e.attrs.get(BLOCK_PORTS_IN))
    outs = [n for n in _split_names(e.attrs.get(BLOCK_PORTS_OUT)) if n not in ins]
    return ins, outs


def is_block_only(project: Project, e: Element) -> bool:
    """Blok rozvaděče bez listu s porty z atributů (`ports_in` / `ports_out`) – záměrně jen blok."""
    return (e.symbol_id == "fve.switchboard" and project.switchboard_sheet(e.id) is None
            and any(block_port_names(e)))


def block_protect(e: Element) -> dict[str, float]:
    """Jištění portů bloku bez listu z atributu `protect` („X1=63, X3=40“) → {port: In [A]}; nečitelné se vynechá."""
    out: dict[str, float] = {}
    # oddělovač „,“ / „;“ jen před označením portu (desetinná čárka „40,5“ zůstane)
    for part in re.split(r"[,;]+(?=\s*[^\d\s,;])", str(e.attrs.get(BLOCK_PROTECT) or "")):
        name, _sep, val = part.partition("=")
        try:
            v = float(val.strip().replace(",", ".").split()[0])
        except (ValueError, IndexError):
            continue
        if name.strip() and v > 0:
            out[name.strip()] = v
    return out


def switchboard_symbol(project: Project, e: Element, base: Symbol) -> Symbol:
    """Značka bloku ROZVADĚČ odvozená z jeho listu: port za každý přívod (vlevo) a vývod (vpravo),
    pojmenovaný označením svorky (X1, X4…). Porty z atributů `ports_in` / `ports_out` (blok bez listu, nebo
    porty, které list nemá) se přidají za ně. Bez listu a bez atributů zůstává základní značka. Porty, na které ještě
    vedou vodiče se starými názvy (1–4), se zachovají, aby se nic nerozpojilo."""
    sheet = project.switchboard_sheet(e.id)
    extra_in, extra_out = block_port_names(e)
    if sheet is None and not (extra_in or extra_out):
        # list smazán / ještě nezaložen: vodiče na porty přívodů zůstanou na „?“ portech
        return with_orphan_ports(base, _used_ports(project, e))

    def nat(f: Element) -> tuple:
        m = re.match(r"([A-Za-z]*)(\d*)(.*)", f.ref)
        return (m.group(1), int(m.group(2)) if m.group(2) else 10**9, m.group(3))
    elements = sheet.elements if sheet is not None else []
    names_in = [f.ref for f in sorted((f for f in elements if is_feed_in(f) and f.ref), key=nat)]
    names_out = [f.ref for f in sorted((f for f in elements if is_feed_out(f) and f.ref), key=nat)]
    seen = set(names_in) | set(names_out)
    names_in += [n for n in extra_in if n not in seen]
    names_out += [n for n in extra_out if n not in seen and n not in extra_in]
    if not names_in and not names_out:
        return with_orphan_ports(base, _used_ports(project, e))
    n = max(len(names_in), len(names_out), 1)
    h = max(20.0, n * PORT_PITCH + PORT_PITCH)
    half = h / 2
    prims: list = [{"type": "rect", "x": -15, "y": -half, "w": 30, "h": h},
                   {"type": "text", "x": 0, "y": half + 1.5, "text": "ROZVADĚČ", "height": 2, "align": "center"}]
    ports: list[Port] = []
    for i, name in enumerate(names_in):
        y = half - PORT_PITCH / 2 - i * PORT_PITCH
        y = round(y / 2.5) * 2.5
        ports.append(Port(name, -15, y, "W"))
        prims.append({"type": "text", "x": -13.5, "y": y - 0.8, "text": name, "height": 1.8, "align": "left"})
    for i, name in enumerate(names_out):
        y = half - PORT_PITCH / 2 - i * PORT_PITCH
        y = round(y / 2.5) * 2.5
        ports.append(Port(name, 15, y, "E"))
        prims.append({"type": "text", "x": 13.5, "y": y - 0.8, "text": name, "height": 1.8, "align": "right"})
    names = {p.name for p in ports}
    parent = project.sheet_of_element(e.id)
    used = {end.port for w in (parent.wires if parent else []) for end in (w.a, w.b) if end.element_id == e.id}
    for p in base.ports:  # staré porty, dokud na ně něco vede
        if p.name in used and p.name not in names:
            ports.append(Port(p.name, p.x, p.y if abs(p.y) < half else (half if p.y > 0 else -half), p.dir))
            names.add(p.name)
    # vodiče na smazaný/přejmenovaný přívod či vývod: port zůstane dole (nic se nerozpojí), označený „?“
    orphans = sorted(used - names)
    for k, name in enumerate(orphans):
        x = round((-10 + k * 10) / 2.5) * 2.5
        ports.append(Port(name, x, -half, "S"))
        prims.append({"type": "text", "x": x, "y": -half + 1.0, "text": f"{name}?", "height": 1.8, "align": "center"})
    return Symbol(id=base.id, name=base.name, category=base.category, description=base.description,
                  iec_ref=base.iec_ref, function_class=base.function_class, primitives=prims, ports=ports, attributes=base.attributes,
                  label_pos=(-15, -half - 3), orphan_ports=tuple(orphans))


INVERTER_SYMBOLS = {"fve.inverter", "fve.inverter_hybrid"}


def inverter_dc_inputs(project: Project, e: Element) -> int:
    """Počet DC vstupů střídače: MPPT × stringů na MPPT (výchozí 2), nejméně tolik, kolik je zapojeno (DC1…DCn).
    Stringy se v rozvaděči nikdy nespojují – každý má na střídači vlastní vstup."""
    try:
        mppt = int(float(str(e.attrs.get("mppt") or 0).replace(",", ".")))
    except ValueError:
        mppt = 0
    try:
        spm = int(float(str(e.attrs.get("strings_per_mppt") or 2).replace(",", "."))) or 2
    except ValueError:
        spm = 2
    n = mppt * spm if mppt else 2
    sheet = project.sheet_of_element(e.id)
    used = {end.port for w in (sheet.wires if sheet else []) for end in (w.a, w.b) if end.element_id == e.id}
    for p in used:
        if re.fullmatch(r"DC(\d+)", p):
            n = max(n, int(p[2:]))
    return max(n, 2)


IO_ATTRIBUTE = Attribute("io", "Svorky střídače (záloha, komunikace) – prázdné = podle typu, „-“ = žádné", "", False)


def inverter_symbol(project: Project, e: Element, base: Symbol) -> Symbol:
    """Značka střídače s DC vstupem na každý string (DC1…DCn vlevo); základní značka má DC1/DC2. Svorky typu
    střídače (`inverter_io`: záložní výstup, generátor, komunikace, řízení výkonu) jsou v pásu pod značkou s porty
    vpravo a popisem; baterie (BAT) je pak pod pásem. Atribut `io` je u střídače vždy (i bez svorek)."""
    from envocad.model.inverter_io import inverter_io
    attributes = list(base.attributes)
    if not any(a.key == "io" for a in attributes):
        attributes.append(IO_ATTRIBUTE)
    n = inverter_dc_inputs(project, e)
    io = [p for p in inverter_io(e.attrs) if p not in {q.name for q in base.ports}]
    if n <= 2 and not io:
        return dataclasses.replace(base, attributes=attributes)
    h = max(20.0, 5.0 * n + 5.0) if n > 2 else 20.0
    half = h / 2
    prims = []
    for pr in base.primitives:
        if pr.get("type") == "rect" and pr.get("w") == 20:
            prims.append({**pr, "y": -half, "h": h})
        elif pr.get("type") == "line" and pr.get("x1") == -10 and pr.get("y1") == -10 and pr.get("x2") == 10 and pr.get("y2") == 10:
            prims.append({**pr, "y1": -half, "y2": half})
        elif pr.get("type") == "text" and pr.get("text") == "BAT":
            prims.append({**pr, "y": -half + 1.0})   # u spodní hrany uvnitř (port BAT je dole uprostřed)
        else:
            prims.append(pr)
    if n > 2:
        ports = [Port(f"DC{k + 1}", -10, 2.5 * (n - 1) - 5 * k, "W") for k in range(n)]
        ports += [p for p in base.ports if not p.name.startswith("DC")]
    else:
        ports = list(base.ports)
    bottom = -half - 5.0 * len(io)            # spodní hrana pásu svorek (bez svorek = spodní hrana značky)
    ports = [Port(p.name, p.x, (bottom if p.y == -10 else (half if p.y == 10 else p.y)), p.dir) for p in ports]
    if io:
        prims.append({"type": "rect", "x": -10, "y": bottom, "w": 20, "h": -bottom - half})
        for k, name in enumerate(io):
            y = -half - 5.0 * k - 2.5
            ports.append(Port(name, 10, y, "E"))
            prims.append({"type": "text", "x": -8.5, "y": y - 0.7, "text": name, "height": 2.0, "align": "left"})
    return Symbol(id=base.id, name=base.name, category=base.category, description=base.description, iec_ref=base.iec_ref, function_class=base.function_class,
                  primitives=prims, ports=ports, attributes=attributes, multipole=base.multipole,
                  label_pos=(base.label_pos[0], half + 10.0))


def _used_ports(project: Project, e: Element) -> set[str]:
    """Porty prvku, na které vedou vodiče jeho listu."""
    sheet = project.sheet_of_element(e.id)
    return {end.port for w in (sheet.wires if sheet else []) for end in (w.a, w.b) if end.element_id == e.id}


_SYMBOL_CACHE: dict | None = None


@contextlib.contextmanager
def symbol_cache():
    """Mezipaměť `element_symbol` po dobu bloku (generátor: zkoušení rozložení blokového schématu počítá značky
    tisíckrát). Platí jen, když se v bloku nemění listy rozvaděčů, atributy ani zapojení prvků – polohy ano (značka
    na poloze nezávisí). Jen jedno vlákno (GUI ji nepoužívá); vnořený blok sdílí vnější mezipaměť."""
    global _SYMBOL_CACHE
    outer = _SYMBOL_CACHE
    if outer is None:
        _SYMBOL_CACHE = {}
    try:
        yield
    finally:
        if outer is None:
            _SYMBOL_CACHE = None


def element_symbol(project: Project, e: Element, lib) -> Symbol:
    """Značka prvku (`_element_symbol`); v bloku `symbol_cache` z mezipaměti."""
    if _SYMBOL_CACHE is not None:
        key = (id(project), e.id, e.symbol_id)
        hit = _SYMBOL_CACHE.get(key)
        if hit is None:
            hit = _SYMBOL_CACHE[key] = _element_symbol(project, e, lib)
        return hit
    return _element_symbol(project, e, lib)


def _element_symbol(project: Project, e: Element, lib) -> Symbol:
    """Značka prvku – blok ROZVADĚČ podle jeho listu, střídač podle počtu DC vstupů, sběrnice s atributem `taps`
    podle počtu přívodů (`busbar.busbar_symbol`), jinak z knihovny.
    Nikdy nepadá na stavu projektu: symbol, který v knihovně není, nahradí zástupná značka (`placeholder`)
    s porty podle vodičů a port, na který vede vodič, ale značka ho nemá, se doplní jako osiřelý („X1?“,
    `orphan_ports`). Obojí hlásí kontrola projektu (`symbol`, `bad_port`)."""
    used = _used_ports(project, e)      # jednou – hledá list prvku a prochází jeho vodiče
    try:
        base = lib.get_symbol(e.symbol_id)
    except KeyError:
        return placeholder_symbol(e.symbol_id, used)
    if e.symbol_id == "fve.switchboard":
        sym = switchboard_symbol(project, e, base)
    elif e.symbol_id in INVERTER_SYMBOLS:
        sym = inverter_symbol(project, e, base)
    elif is_feed(e):
        sym = feed_symbol(e, base)
    elif e.symbol_id == BUS_SYMBOL and str(e.attrs.get(TAPS_ATTR, "")).strip():
        sym = busbar_symbol(e, base, used)     # jen parametrická sběrnice (pevná = značka z knihovny)
    else:
        sym = base
    if used and not used <= {p.name for p in sym.ports}:
        sym = with_orphan_ports(sym, used)
    return sym


def feed_wire_by_port(project: Project, sheet: Sheet, feed: Element) -> Wire | None:
    """Vodič JPS napojený na port bloku ROZVADĚČ se jménem přívodu/vývodu (X1, X4…)."""
    block = sheet.parent_element_id
    parent = parent_sheet(project, sheet)
    if parent is None or not feed.ref:
        return None
    for w in parent.wires:
        for end in (w.a, w.b):
            if end.element_id == block and end.port == feed.ref:
                return w
    return None


def effective_feed_wire(project: Project, sheet: Sheet, feed: Element) -> Wire | None:
    """Vodič JPS, na který je přívod/vývod skutečně navázaný – stejné pravidlo jako `sync_feed_link_attrs`:
    vodič na portu bloku se jménem přívodu má přednost, jinak ruční vazba (`wire_id` na existující vodič)."""
    w = feed_wire_by_port(project, sheet, feed)
    if w is not None:
        return w
    if not feed.attrs.get("wire_id"):
        return None
    hit = linked_wire(project, sheet, feed)
    return hit[1] if hit is not None else None


def _feeds(project: Project):
    for s in project.sheets:
        if s.is_switchboard:
            for f in s.elements:
                if f.symbol_id in FEED_SYMBOLS:
                    yield s, f


def _sync_feed_attrs(project: Project, s: Sheet, f: Element) -> tuple[bool, Wire | None]:
    """Odvozené atributy jednoho přívodu/vývodu (`wire_id`, odkud/kam, kabel). (změněno, nově navázaný vodič)."""
    cur = f.attrs.get("wire_id", "")
    w = feed_wire_by_port(project, s, f)
    if cur and w is None and linked_wire(project, s, f) is not None:
        return False, None            # ruční vazba (nebo přejmenovaný přívod/vývod před přejmenováním portu)
    new_id = w.id if w else ""
    if new_id != cur or (new_id and not f.attrs.get("cable") and w.attrs.get("cable")):
        for k, v in feed_link_attrs(project, s, f, new_id).items():
            if f.attrs.get(k, "") != v:   # nezměněnou hodnotu ani chybějící prázdný klíč nepřepisovat
                f.attrs[k] = v
        return True, w
    return False, None


def sync_feed_link_attrs(project: Project) -> int:
    """Jen odvozená část vazeb přívodů/vývodů na vodiče JPS: `wire_id`, odkud/kam a kabel přívodu podle portu
    bloku (X1 → port X1); ruční vazba (`wire_id` na jiný existující vodič) má přednost, když na portu žádný vodič
    není. Idempotentní, primární data (žíly, porty vodičů) nemění – GUI ji volá po každé změně modelu mimo undo.
    Doplňuje jen vazbu podle portu (vodič vložený na port bloku, přejmenovaný port); její zápisy undo nevrací –
    po undo zůstanou místo chybějících klíčů prázdné hodnoty, které porovnání revizí nevidí. Ruční vazbu
    (`wire_id` z dialogu / panelu) i s odkud/kam a kabelem zapisuje příkaz (`SetAttrCommand`), takže ji undo vrátí
    celou; ruční vazbu (bez vodiče na portu) tato funkce nepřepisuje. Vrací počet změněných přívodů/vývodů."""
    return sum(_sync_feed_attrs(project, s, f)[0] for s, f in _feeds(project))


def sync_feed_links(project: Project) -> int:
    """Plná synchronizace vazeb (načtení projektu, generátor – mimo undo): odvozené atributy
    (`sync_feed_link_attrs`) a navíc primární follow-upy, které v GUI dělají příkazy: přejmenování konce vodiče
    JPS na bloku podle označení přívodu s ruční vazbou (`feed_port_followups`) a převzetí žil nově navázaného
    vodiče JPS vodiči rozvaděče u přívodu (`feed_conductor_changes`). Vrací počet změn."""
    changed = 0
    for s, f in _feeds(project):
        ports = feed_port_followups(project, s, f, f.ref)
        if ports:
            apply_text_changes(project, ports)
            changed += len(ports)
            continue
        hit, w = _sync_feed_attrs(project, s, f)
        if hit:
            changed += 1
            if w is not None:
                apply_conductor_changes(project, feed_conductor_changes(s, f, w))
    return changed


def feed_port_followups(project: Project, sheet: Sheet, feed: Element, new_ref: str) -> list[TextChange]:
    """Přívod/vývod `feed` dostane označení `new_ref`: konec jeho navázaného vodiče JPS na bloku ROZVADĚČ se
    přejmenuje na `new_ref` (`TextChange` „wire_port“). Nic, když na portu `new_ref` už nějaký vodič je (vazba
    pak vede podle portu), když přívod žádný vodič nemá, nebo když vodič na blok nevede."""
    block = sheet.parent_element_id
    if feed.symbol_id not in FEED_SYMBOLS or not new_ref or not block:
        return []
    probe = Element(symbol_id=feed.symbol_id, attrs={**feed.attrs, "ref": new_ref}, id=feed.id)
    if feed_wire_by_port(project, sheet, probe) is not None:
        return []
    hit = linked_wire(project, sheet, feed)     # ruční vazba, jinak port podle dosavadního označení
    if hit is None:
        return []
    w = hit[1]
    return [TextChange("wire_port", w.id, k, end.port, new_ref)
            for k, end in (("a", w.a), ("b", w.b)) if end.element_id == block and end.port != new_ref]


@dataclass(frozen=True)
class ConductorChange:
    """Změna žil vodiče `wire_id` navázaná na jinou změnu (převzetí žil vodiče JPS u přívodu rozvaděče);
    svorky žil, které zmizely, se zahodí (jako `SetConductorsCommand`)."""
    wire_id: str
    old: list[str]
    new: list[str]
    old_terminals: dict
    new_terminals: dict


def feed_conductor_changes(sheet: Sheet, feed: Element, wire: Wire) -> list[ConductorChange]:
    """Vodiče listu rozvaděče `sheet` napojené na přívod/vývod `feed` převezmou žíly vodiče JPS `wire`."""
    conds = list(wire.conductors)
    if not conds:
        return []
    out = []
    for sw in sheet.wires:
        if sw.touches(feed.id) and sw.conductors != conds:
            old_t = {c: dict(t) for c, t in sw.terminals.items()}
            new_t = {c: dict(t) for c, t in sw.terminals.items() if c in conds}
            out.append(ConductorChange(sw.id, list(sw.conductors), conds, old_t, new_t))
    return out


def feed_conductor_followups(project: Project, wire: Wire) -> list[ConductorChange]:
    """Žíly, které po vložení / změně vodiče JPS `wire` převezmou vodiče rozvaděčů u přívodů/vývodů navázaných
    na `wire` (`effective_feed_wire`). Volají je příkazy (`AddWireCommand`, `SetConductorsCommand`,
    `SetAttrCommand` s `wire_id`), aby undo změnu vrátilo; vodič uvnitř rozvaděče nic nevyvolá."""
    home = next((s for s in project.sheets if any(w.id == wire.id for w in s.wires)), None)
    if home is None or home.is_switchboard or not wire.conductors:
        return []
    out: list[ConductorChange] = []
    for s, f in _feeds(project):
        lw = effective_feed_wire(project, s, f)
        if lw is not None and lw.id == wire.id:
            out += feed_conductor_changes(s, f, wire)
    return out


def apply_conductor_changes(project: Project, changes: list[ConductorChange], undo: bool = False) -> None:
    """Provede (nebo s `undo` vrátí) změny žil z `feed_conductor_followups`."""
    wires = {w.id: w for s in project.sheets for w in s.wires}
    for c in (reversed(changes) if undo else changes):
        w = wires.get(c.wire_id)
        if w is None:
            continue
        w.conductors = list(c.old if undo else c.new)
        w.terminals = {k: dict(t) for k, t in (c.old_terminals if undo else c.new_terminals).items()}


# ---- kabely ↔ vodiče -------------------------------------------------------------------------------------
def _cable_wires(project: Project):
    """Vodiče JPS, které mají kabel (označení nebo typ kabelu) – stejný výběr jako v `sync_cables`."""
    for s in project.sheets:
        if s.is_switchboard:
            continue
        for w in s.wires:
            if w.attrs.get("ref") or w.attrs.get("cable"):
                yield w


def orphan_cables(project: Project) -> list[Cable]:
    """Kabely, na které neodkazuje žádný vodič JPS (ani `cable_id`, ani označením – `Project.cable_of_wire`)."""
    used = set()
    for w in _cable_wires(project):
        c = project.cable_of_wire(w)
        if c is not None:
            used.add(c.id)
    return [c for c in project.cables if c.id not in used]


def sync_cables(project: Project) -> int:
    """Z vodičů JPS (s označením nebo typem kabelu) udržuje objekty Cable: typ/průřez/délka/trasa se berou
    z atributů vodiče (ten je editační místo), žíly z `Wire.conductors` (barvy se dopočítají a ručně upravené
    zůstanou). Vodiče uvnitř rozvaděčů kabel nedostanou. Kabel, na který žádný vodič JPS neodkazuje (smazaný nebo
    vrácený vodič – undo vložení), se odebere do `Project.removed_cables`; vrátí-li se vodič s jeho `cable_id`
    (undo/redo), obnoví se týž kabel (id, barvy žil, artikl) na původním místě. Kabel osiřelý už v načteném souboru
    (`Project.loaded_orphan_cables`) se neodebere – ruční data se otevřením projektu neztratí. Vrací počet změn."""
    changed = 0
    for s in project.sheets:
        if s.is_switchboard:
            continue
        for w in s.wires:
            ref = w.attrs.get("ref", "")
            if not ref and not w.attrs.get("cable"):
                continue
            c = project.cable_of_wire(w)
            cid = w.attrs.get("cable_id", "")
            if cid and (c is None or c.id != cid) and cid in project.removed_cables:
                pos, c = project.removed_cables.pop(cid)       # vodič se vrátil (undo/redo) – týž kabel zpět
                project.cables.insert(min(pos, len(project.cables)), c)
                changed += 1
            if c is None:
                c = Cable(ref=ref or f"W{len(project.cables) + 1}")
                project.cables.append(c)
                changed += 1
            for key, attr in (("type", "cable"), ("cross", "cross"), ("length", "length"), ("route", "route")):
                v = w.attrs.get(attr, "")
                if v and getattr(c, key) != v:
                    setattr(c, key, v)
                    changed += 1
            if ref and c.ref != ref:
                c.ref = ref
                changed += 1
            names = list(w.conductors) or ["L1"]
            if [x.name for x in c.cores] != names:
                c.set_cores(names)
                changed += 1
            if w.attrs.get("cable_id") != c.id:
                w.attrs["cable_id"] = c.id
                changed += 1
    used = {w.attrs.get("cable_id") for w in _cable_wires(project)}
    project.loaded_orphan_cables -= used            # kabel už má vodič – další osiření je změna v této relaci
    for i in range(len(project.cables) - 1, -1, -1):
        c = project.cables[i]
        if c.id not in used and c.id not in project.loaded_orphan_cables:   # osiřelý změnou (vodič smazán / undo)
            project.removed_cables[c.id] = (i, project.cables.pop(i))
            changed += 1
    return changed


# ---- přerušovací body (potenciál pokračuje jinde) --------------------------------------------------------
INTERRUPT_SYMBOL = "fve.interrupt"


def interrupt_partner(project: Project, e: Element) -> tuple[Sheet, Element] | None:
    """Protějšek přerušovacího bodu (stejné označení kdekoli v projektu): v řetězu další, jinak předchozí bod,
    v hvězdě zdroj, u zdroje první cíl (`xref.interrupt_link`)."""
    if e.symbol_id != INTERRUPT_SYMBOL or not e.ref:
        return None
    from envocad.model.xref import interrupt_link, interrupt_partner_of
    sheet = project.sheet_of_element(e.id)
    return interrupt_partner_of(interrupt_link(project, sheet, e))


def element_xref(project: Project, sheet: Sheet, e: Element, index=None) -> str:
    """Text křížového odkazu kreslený u prvku: přerušovací bod → poloha protějšku/ů („→ /2.C3“, řetěz, hvězda),
    kontakt (i stykač kreslený jako silové kontakty cívky) → poloha hostitele („→ /2.B5“). Hostitel zrcadla
    (cívka, přístroj s kontakty) vrací "" – zrcadlo je samostatná tabulka (`xref.mirror_geometry`).
    `index` = `xref.DeviceIndex` (jinak se postaví)."""
    from envocad.model import xref
    if e.symbol_id == INTERRUPT_SYMBOL:
        groups = index.interrupts if index is not None and index.project is project else None
        return xref.interrupt_xref(project, sheet, e, groups)
    if not (is_contact(e) or e.symbol_id in DUAL_ROLE):
        return ""
    idx = index or xref.DeviceIndex.build(project)
    g = idx.group_of(e)
    if g is None and is_contact(e):
        g = idx.resolve(sheet, e)          # kontakt mimo projekt (náhled)
    if g is None or (not is_contact(e) and not idx.is_secondary(e)):
        return "→ ?" if is_contact(e) else ""
    hs, h = g.host
    return "→ " + xref.place_ref(project, sheet, e, hs, h)


# ---- cívky a kontakty (ovládací obvody) ---------------------------------------------------------------------
CONTACT_KIND = {"ctl.contact_no": "no", "ctl.contact_nc": "nc", "ctl.contact_power": "power"}
CONTACT_SYMBOLS = set(CONTACT_KIND)
COIL_SYMBOLS = {"ctl.coil"}
# bez cívky hlavní přístroj; s cívkou stejného označení = silové kontakty cívky (položka výkazu zůstává stykač)
DUAL_ROLE = {"fve.contactor": "power"}


def is_contact(e: Element) -> bool:
    return e.symbol_id in CONTACT_SYMBOLS


def contact_terminals(e: Element) -> str:
    """Svorky kontaktu jako text („13/14“, silový 3pól „1/2 3/4 5/6“) – `xref.contact_pairs`."""
    from envocad.model.xref import contact_pairs
    return " ".join(contact_pairs(e))


def contacts_of(project: Project, ref: str, coil: Element | None = None, index=None) -> list[tuple[Sheet, Element]]:
    """Kontakty (pomocné i silové) s označením `ref`, kdekoli v projektu. Se `coil` jen kontakty přístroje (skupiny
    `xref.DeviceIndex`), do kterého `coil` patří – stejné ref ve více umístěních se rozliší prostorem označení."""
    if coil is None:
        return [(s, e) for s in project.sheets for e in s.elements if is_contact(e) and e.ref == ref]
    from envocad.model.xref import DeviceIndex
    idx = index or DeviceIndex.build(project)
    g = idx.group_of(coil)
    return list(g.contacts) if g is not None and g.ref == ref else []


def contact_mirror(project: Project, coil: Element, index=None) -> list[tuple[str, str]]:
    """Zrcadlo kontaktů hostitele jako [(svorky, odkaz /list.sloupec)…] bez rezerv, přirozeně podle svorek."""
    from envocad.model.xref import DeviceIndex, contact_table, natural_key
    idx = index or DeviceIndex.build(project)
    sheet = project.sheet_of_element(coil.id)
    if sheet is None:
        return []
    rows = [(r.pair, r.ref) for r in contact_table(project, sheet, coil, idx).rows() if r.ref]
    rows.sort(key=lambda r: (natural_key(r[0]), natural_key(r[1])))
    return rows


def coil_candidates(project: Project, contact: Element, index=None) -> list[tuple[Sheet, Element]]:
    """Hostitelé (cívka, jinak první ne-kontakt) přístrojů se stejným označením jako kontakt, v pořadí projektu."""
    from envocad.model.xref import DeviceIndex
    idx = index or DeviceIndex.build(project)
    return [g.host for g in idx.by_ref.get(contact.ref, []) if g.host[1] is not contact] if contact.ref else []


def coil_of(project: Project, contact: Element, sheet: Sheet | None = None, index=None) -> tuple[Sheet, Element] | None:
    """Hostitel přístroje, ke kterému kontakt patří (stejné označení): cívka, jinak první ne-kontakt. Více přístrojů
    se stejným ref → přednost má ten ve stejném prostoru označení (`designation.scope_key`) jako kontakt, jinak první.
    `sheet` = list kontaktu (jen pro kontakt, který v projektu není)."""
    from envocad.model.xref import DeviceIndex
    idx = index or DeviceIndex.build(project)
    g = idx.group_of(contact)
    if g is None and contact.id not in idx.by_element:
        g = idx.resolve(sheet or project.sheet_of_element(contact.id), contact)
    return g.host if g is not None else None
