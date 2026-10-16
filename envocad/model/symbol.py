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

GRID = 2.5  # mm

Primitive = dict[str, Any]

DIRS = ("N", "E", "S", "W")


@dataclass
class Port:
    name: str
    x: float
    y: float
    dir: str = "E"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Attribute:
    key: str
    label: str
    default: str = ""
    show: bool = False
    fmt: str = ""        # formát zobrazené hodnoty ve výkresu, např. "{} modulů" (prázdné = hodnota sama)

    def display(self, value: str) -> str:
        return self.fmt.format(value) if self.fmt and value else value

    def to_dict(self) -> dict:
        return asdict(self)


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

    @property
    def classes(self) -> list[str]:
        """Povolené třídy označení: explicitní `function_class`, jinak [iec_ref] (prázdný iec_ref = bez kontroly)."""
        if self.function_class is not None:
            return list(self.function_class)
        return [self.iec_ref] if self.iec_ref else []

    def label_lines(self, attrs: dict) -> list[str]:
        """Řádky popisku prvku ve výkresu (bez označení): zobrazované atributy s formátem."""
        return [a.display(attrs[a.key]) for a in self.attributes if a.show and a.key != "ref" and attrs.get(a.key)]

    def pole_symbol(self) -> Symbol:
        """Značka jednoho pólu pro vícepól (bez vlastní – celá značka)."""
        pole = self.multipole.get("pole")
        if not pole:
            return self
        return Symbol(id=self.id + "#pole", name=self.name, primitives=list(pole), ports=list(self.ports),
                      attributes=self.attributes, label_pos=self.label_pos)

    def common_symbol(self) -> Symbol | None:
        common = self.multipole.get("common")
        if not common:
            return None
        return Symbol(id=self.id + "#common", name=self.name, primitives=list(common), ports=[])

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
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

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
