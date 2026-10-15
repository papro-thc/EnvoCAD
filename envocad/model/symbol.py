"""Definice symbolu – čistá data, bez Qt.

Jednotky mm, Y nahoru. Primitiva jsou slovníky (viz docs/LIBRARY_FORMAT.md), aby šly
1:1 ukládat do JSON a snadno rozšiřovat o nové typy.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

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
