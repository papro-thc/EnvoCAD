"""Definice symbolu – čistá data, bez Qt.

Jednotky mm, Y nahoru. Primitiva jsou slovníky (viz docs/LIBRARY_FORMAT.md), aby šly
1:1 ukládat do JSON a snadno rozšiřovat o nové typy.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from envocad.model.designation import class_matches
from envocad.model.grid import GRID
from envocad.model.grid import snap as _snap

Primitive = dict[str, Any]

DIRS = ("N", "E", "S", "W")

# Verze formátu JSON symbolu; zvedat jen při nekompatibilní změně (viz docs/LIBRARY_FORMAT.md)
SYMBOL_FORMAT_VERSION = 1


class SymbolVersionError(ValueError):
    """Symbol byl uložen novějším formátem, než tento program umí číst."""


@dataclass
class Port:
    name: str
    x: float
    y: float
    dir: str = "E"

    def to_dict(self) -> dict:
        return asdict(self)


# atribut → atribut, který ho v popisku ve výkresu nahradí, když je zadaný: typ SPD (T1+T2) je obsažený
# v objednacím typu svodiče („VPU PV I+II 3 1000“) – ve výkresu typ, Uc, Up, ISCPV
LABEL_SUPERSEDED = {"spd_type": "type"}


@dataclass
class Attribute:
    key: str
    label: str
    default: str = ""
    show: bool = False
    fmt: str = ""        # formát zobrazené hodnoty ve výkresu, např. "{} modulů" (prázdné = hodnota sama)
    # nepovinná nabídka hodnot [[hodnota, popisek], …] – ve Vlastnostech výběr místo textu (starší program ignoruje)
    choices: list | None = None

    def choice_items(self) -> list[tuple[str, str]]:
        """Nabídka (hodnota, popisek); položka jako řetězec = hodnota i popisek. Bez nabídky prázdný seznam."""
        out = []
        for c in self.choices or []:
            if isinstance(c, (list, tuple)) and c:
                out.append((str(c[0]), str(c[1]) if len(c) > 1 else str(c[0])))
            elif isinstance(c, str):
                out.append((c, c))
        return out

    def display(self, value: str) -> str:
        """Hodnota pro výkres podle `fmt`; hodnota, která už jednotku z formátu nese („25 kW“, „1000 V DC“ u
        „Uc {} V“), se nezdvojí – dostane jen předponu formátu („Uc 1000 V DC“)."""
        if not (self.fmt and value):
            return value
        prefix, suffix = (self.fmt.split("{}", 1) + [""])[:2] if "{}" in self.fmt else ("", "")
        suffix = suffix.strip()
        if suffix and suffix.lower() in str(value).lower().split():
            return prefix + str(value).strip()
        if suffix and str(value).strip().lower().endswith(suffix.lower()):
            return prefix + str(value).strip()
        return self.fmt.format(value)

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.choices is None:
            d.pop("choices")
        return d


@dataclass
class Symbol:
    id: str
    name: str
    category: str = ""
    description: str = ""
    iec_ref: str = ""
    primitives: list[Primitive] = field(default_factory=list)
    ports: list[Port] = field(default_factory=list)
    attributes: list[Attribute] = field(default_factory=list)
    label_pos: tuple[float, float] = (0.0, 0.0)
    # vícepólová podoba: {"pole": [primitiva jednoho pólu], "common": [primitiva kreslená jednou u 1. pólu],
    #                     "link": True (čárkovaná mechanická vazba pólů), "link_at": [x, y] bod vazby v pólu}
    multipole: dict = field(default_factory=dict)
    # povolené třídy označení dle IEC 81346-2 (1–2 písmena) nebo firemní prefix ENVO (3 písmena, např. SPD);
    # shoda prefixem; None = odvodit z iec_ref, [] = nekontrolovat
    function_class: list[str] | None = None
    # jen za běhu, neukládá se: zástupná značka za neznámé symbol_id / porty, které značka nemá (vedou na ně vodiče)
    placeholder: bool = field(default=False, compare=False, repr=False)
    orphan_ports: tuple[str, ...] = field(default=(), compare=False, repr=False)

    @property
    def classes(self) -> list[str]:
        """Povolené třídy označení: explicitní `function_class`, jinak [iec_ref] (prázdný iec_ref = bez kontroly)."""
        if self.function_class is not None:
            return list(self.function_class)
        return [self.iec_ref] if self.iec_ref else []

    def label_attributes(self, attrs: dict, skip: set[str] | frozenset = frozenset({"ref"})) -> list[Attribute]:
        """Zobrazované atributy s hodnotou (bez `skip`); atribut, který nahrazuje jiný zadaný (`LABEL_SUPERSEDED`:
        typ SPD vedle objednacího typu svodiče), se vynechá – popisek SPD se pak vejde vedle pólů."""
        return [a for a in self.attributes if a.show and a.key not in skip and attrs.get(a.key)
                and not (a.key in LABEL_SUPERSEDED and attrs.get(LABEL_SUPERSEDED[a.key]))]

    def label_lines(self, attrs: dict) -> list[str]:
        """Řádky popisku prvku ve výkresu (bez označení): zobrazované atributy s formátem."""
        return [a.display(attrs[a.key]) for a in self.label_attributes(attrs)]

    def pole_symbol(self) -> Symbol:
        """Značka jednoho pólu pro vícepól (bez vlastní – celá značka)."""
        pole = self.multipole.get("pole")
        if not pole:
            return self
        return Symbol(id=self.id + "#pole", name=self.name, primitives=list(pole), ports=list(self.ports),
                      attributes=self.attributes, label_pos=self.label_pos)

    def common_symbol(self, texts: bool = False) -> Symbol | None:
        """Společná část vícepólové značky: tvary (`texts=False`, kreslí se u prvního pólu) nebo texty
        (`texts=True`, např. „DC“ – kreslí se u posledního pólu, aby neležely přes další póly)."""
        common = [p for p in self.multipole.get("common") or [] if (p.get("type") == "text") == texts]
        if not common:
            return None
        return Symbol(id=self.id + ("#common_text" if texts else "#common"), name=self.name,
                      primitives=common, ports=[])

    @property
    def pole_link(self) -> bool:
        return bool(self.multipole.get("link"))

    @property
    def link_at(self) -> tuple[float, float]:
        la = self.multipole.get("link_at") or [0.0, 2.0]
        return (float(la[0]), float(la[1]))

    # ---- serializace -------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "format_version": SYMBOL_FORMAT_VERSION,
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "iec_ref": self.iec_ref,
            **({"function_class": list(self.function_class)} if self.function_class is not None else {}),
            "primitives": self.primitives,
            "ports": [p.to_dict() for p in self.ports],
            "attributes": [a.to_dict() for a in self.attributes],
            "label_pos": {"x": self.label_pos[0], "y": self.label_pos[1]},
            **({"multipole": self.multipole} if self.multipole else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Symbol:
        ver = d.get("format_version", 1)
        if isinstance(ver, bool) or not isinstance(ver, int) or ver < 1:
            raise ValueError(f"Symbol „{d.get('id', '?')}“: neplatná verze formátu {ver!r}")
        if ver > SYMBOL_FORMAT_VERSION:
            raise SymbolVersionError(
                f"Symbol „{d.get('id', '?')}“ byl vytvořen novější verzí EnvoCAD (formát {ver}) – aktualizujte EnvoCAD")
        lp = d.get("label_pos") or {"x": 0, "y": 0}
        sym = cls(
            id=d["id"],
            name=d["name"],
            category=d.get("category", ""),
            description=d.get("description", ""),
            iec_ref=d.get("iec_ref", ""),
            primitives=list(d.get("primitives", [])),
            ports=[Port(**p) for p in d.get("ports", [])],
            attributes=[Attribute(**a) for a in d.get("attributes", [])],
            label_pos=(float(lp["x"]), float(lp["y"])),
            multipole=dict(d.get("multipole") or {}),
            function_class=[str(c) for c in d["function_class"]] if d.get("function_class") is not None else None,
        )
        if not any(a.key == "ref" for a in sym.attributes):
            sym.attributes.insert(0, Attribute("ref", "Označení", "", True))
        return sym

    def to_json(self, path: Path | str) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path | str) -> Symbol:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))

    # ---- geometrie ---------------------------------------------------
    def port(self, name: str) -> Port:
        for p in self.ports:
            if p.name == name:
                return p
        raise KeyError(f"Symbol {self.id} nemá port {name!r}")

    def bounds(self) -> tuple[float, float, float, float]:
        """(xmin, ymin, xmax, ymax) přes primitiva i porty. Prázdný symbol → malý čtverec."""
        xs: list[float] = []
        ys: list[float] = []
        for p in self.primitives:
            t = p["type"]
            if t == "line":
                xs += [p["x1"], p["x2"]]
                ys += [p["y1"], p["y2"]]
            elif t == "rect":
                xs += [p["x"], p["x"] + p["w"]]
                ys += [p["y"], p["y"] + p["h"]]
            elif t in ("circle", "arc"):
                xs += [p["cx"] - p["r"], p["cx"] + p["r"]]
                ys += [p["cy"] - p["r"], p["cy"] + p["r"]]
            elif t == "polyline":
                for x, y in p["points"]:
                    xs.append(x)
                    ys.append(y)
            elif t == "text":
                xs.append(p["x"])
                ys.append(p["y"])
        for pt in self.ports:
            xs.append(pt.x)
            ys.append(pt.y)
        if not xs:
            return (-GRID, -GRID, GRID, GRID)
        return (min(xs), min(ys), max(xs), max(ys))

    def validate(self) -> list[str]:
        """Vrátí seznam problémů (prázdný = OK)."""
        issues = []
        for p in self.ports:
            if abs(p.x / GRID - round(p.x / GRID)) > 1e-6 or abs(p.y / GRID - round(p.y / GRID)) > 1e-6:
                issues.append(f"port {p.name} není na mřížce {GRID} mm")
            if p.dir not in DIRS:
                issues.append(f"port {p.name}: neplatný směr {p.dir!r}")
        names = [p.name for p in self.ports]
        if len(names) != len(set(names)):
            issues.append("duplicitní názvy portů")
        for c in self.function_class or []:
            if not re.fullmatch(r"[A-Z]{1,3}", c):
                issues.append(f"neplatná třída označení {c!r} (1–3 velká písmena A–Z)")
        if self.iec_ref and self.classes and not class_matches(self.iec_ref + "1", self.classes):
            issues.append(f"prefix označení {self.iec_ref!r} neodpovídá třídám {', '.join(self.classes)}")
        return issues


ORPHAN_PITCH = 5.0   # mm – rozestup osiřelých portů pod značkou



def with_orphan_ports(sym: Symbol, names) -> Symbol:
    """Kopie značky doplněná o „osiřelé“ porty `names`, na které vedou vodiče, ale značka je nemá (přejmenovaný
    port, smazaný přívod rozvaděče…). Porty leží na mřížce pod značkou a jsou označené „název?“; nic se
    nerozpojí a kontrola je hlásí jako vodič na neexistující port (`Symbol.orphan_ports`)."""
    have = {p.name for p in sym.ports}
    missing = sorted({str(n) for n in names} - have)
    if not missing:
        return sym
    x0, y0, _x1, _y1 = sym.bounds()
    y = math.floor(y0 / GRID + 1e-9) * GRID - GRID     # na mřížce, pod spodním okrajem značky
    xs = math.ceil(x0 / GRID - 1e-9) * GRID
    ports = list(sym.ports)
    prims = list(sym.primitives)
    for k, name in enumerate(missing):
        x = xs + k * ORPHAN_PITCH
        ports.append(Port(name, x, y, "S"))
        prims.append({"type": "circle", "cx": x, "cy": y, "r": 0.6})
        prims.append({"type": "text", "x": x, "y": y + 1.0, "text": f"{name}?", "height": 1.8, "align": "center"})
    return Symbol(id=sym.id, name=sym.name, category=sym.category, description=sym.description, iec_ref=sym.iec_ref,
                  primitives=prims, ports=ports, attributes=sym.attributes, label_pos=sym.label_pos,
                  multipole=sym.multipole, function_class=sym.function_class, placeholder=sym.placeholder,
                  orphan_ports=tuple(sym.orphan_ports) + tuple(missing))


def placeholder_symbol(symbol_id: str, port_names=()) -> Symbol:
    """Zástupná značka za symbol, který v knihovně není: obdélník s „?“ a porty podle vodičů (střídavě vlevo
    a vpravo, na mřížce). Projekt jde otevřít, kreslit i exportovat; kontrola hlásí „Neznámá značka“."""
    names = sorted({str(n) for n in port_names})
    rows = max(1, (len(names) + 1) // 2)
    h = max(10.0, rows * 5.0 + 5.0)
    half = _snap(h / 2)
    ports = []
    for k, name in enumerate(names):
        y = half - 5.0 - (k // 2) * 5.0
        ports.append(Port(name, -10.0 if k % 2 == 0 else 10.0, y, "W" if k % 2 == 0 else "E"))
    prims: list[Primitive] = [
        {"type": "rect", "x": -10.0, "y": -half, "w": 20.0, "h": 2 * half},
        {"type": "text", "x": 0.0, "y": -1.5, "text": "?", "height": 5.0, "align": "center"},
        {"type": "text", "x": 0.0, "y": -half - 3.0, "text": symbol_id, "height": 1.8, "align": "center"},
    ]
    for p in ports:
        prims.append({"type": "text", "x": p.x + (1.0 if p.x < 0 else -1.0), "y": p.y + 0.5, "text": p.name,
                      "height": 1.8, "align": "left" if p.x < 0 else "right"})
    return Symbol(id=symbol_id, name=f"Neznámá značka {symbol_id}", category="?", primitives=prims, ports=ports,
                  label_pos=(0.0, half + 3.0), function_class=[], placeholder=True)


def rotate_point(x: float, y: float, rot: int) -> tuple[float, float]:
    """Otočí bod kolem počátku o rot ∈ {0,90,180,270} stupňů (proti směru hod. ručiček, Y nahoru)."""
    a = math.radians(rot)
    c, s = round(math.cos(a)), round(math.sin(a))
    return (x * c - y * s, x * s + y * c)


def rotate_dir(d: str, rot: int) -> str:
    i = DIRS.index(d)
    steps = (rot // 90) % 4
    # DIRS = N,E,S,W (po směru hod. ručiček); rotace proti směru → index klesá
    return DIRS[(i - steps) % 4]


def place_point(x: float, y: float, rot: int, mirror: bool = False) -> tuple[float, float]:
    """Bod značky do souřadnic prvku: nejdřív zrcadlení podle svislé osy značky (x → −x), pak otočení."""
    return rotate_point(-x if mirror else x, y, rot)


def place_dir(d: str, rot: int, mirror: bool = False) -> str:
    """Směr portu prvku: zrcadlení prohodí E/W, pak otočení (jako `place_point`)."""
    if mirror and d in ("E", "W"):
        d = "W" if d == "E" else "E"
    return rotate_dir(d, rot)


MIRROR_ALIGN = {"left": "right", "right": "left", "center": "center"}
