"""Projekt → listy → elementy a vodiče. Čistá data, bez Qt."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from envocad.model.symbol import Attribute, Symbol, rotate_point

# Atributy vodiče (vodič nemá symbol, proto jsou definované zde)
WIRE_ATTRIBUTES = [
    Attribute("ref", "Označení", "", True),
    Attribute("cable", "Typ kabelu", "", True),
    Attribute("cross", "Průřez [mm²]", "", True),
    Attribute("length", "Délka [m]"),
    Attribute("route", "Trasa / uložení"),
]

FORMAT_VERSION = 1


def _uid() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Element:
    """Instance symbolu na listu."""
    symbol_id: str
    x: float = 0.0
    y: float = 0.0
    rotation: int = 0  # 0/90/180/270
    attrs: dict[str, str] = field(default_factory=dict)
    component_id: str | None = None  # přiřazený artikl z knihovny
    id: str = field(default_factory=_uid)

    @property
    def ref(self) -> str:
        return self.attrs.get("ref", "")

    def port_pos(self, symbol: Symbol, port_name: str) -> tuple[float, float]:
        p = symbol.port(port_name)
        rx, ry = rotate_point(p.x, p.y, self.rotation)
        return (self.x + rx, self.y + ry)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "symbol_id": self.symbol_id, "x": self.x, "y": self.y,
            "rotation": self.rotation, "attrs": self.attrs, "component_id": self.component_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Element:
        return cls(
            symbol_id=d["symbol_id"], x=d["x"], y=d["y"], rotation=d.get("rotation", 0),
            attrs=dict(d.get("attrs", {})), component_id=d.get("component_id"), id=d["id"],
        )


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
    id: str = field(default_factory=_uid)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "a": self.a.to_dict(), "b": self.b.to_dict(),
            "points": [list(p) for p in self.points], "attrs": self.attrs,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Wire:
        return cls(
            a=WireEnd(**d["a"]), b=WireEnd(**d["b"]),
            points=[tuple(p) for p in d.get("points", [])], attrs=dict(d.get("attrs", {})), id=d["id"],
        )

    def touches(self, element_id: str) -> bool:
        return self.a.element_id == element_id or self.b.element_id == element_id


@dataclass
class Sheet:
    name: str = "Jednopólové schéma"
    paper: str = "A3"
    width: float = 420.0
    height: float = 297.0
    elements: list[Element] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)
    id: str = field(default_factory=_uid)

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
        return removed

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "paper": self.paper, "width": self.width, "height": self.height,
            "elements": [e.to_dict() for e in self.elements], "wires": [w.to_dict() for w in self.wires],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Sheet:
        return cls(
            name=d.get("name", ""), paper=d.get("paper", "A3"), width=d.get("width", 420), height=d.get("height", 297),
            elements=[Element.from_dict(e) for e in d.get("elements", [])],
            wires=[Wire.from_dict(w) for w in d.get("wires", [])], id=d["id"],
        )


@dataclass
class Project:
    name: str = "Nový projekt"
    meta: dict[str, str] = field(default_factory=dict)  # investor, číslo zakázky, místo, zpracoval…
    sheets: list[Sheet] = field(default_factory=lambda: [Sheet()])
    path: Path | None = None

    # ---- označení prvků ---------------------------------------------
    def used_refs(self) -> set[str]:
        refs = {e.ref for s in self.sheets for e in s.elements if e.ref}
        refs |= {w.attrs.get("ref", "") for s in self.sheets for w in s.wires if w.attrs.get("ref")}
        return refs

    def next_ref(self, prefix: str) -> str:
        if not prefix:
            return ""
        used = self.used_refs()
        n = 1
        while f"{prefix}{n}" in used:
            n += 1
        return f"{prefix}{n}"

    # ---- serializace -------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "format": "envocad-project", "format_version": FORMAT_VERSION,
            "name": self.name, "meta": self.meta, "sheets": [s.to_dict() for s in self.sheets],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Project:
        if d.get("format") != "envocad-project":
            raise ValueError("Soubor není projekt EnvoCAD")
        ver = d.get("format_version", 1)
        if ver > FORMAT_VERSION:
            raise ValueError(f"Projekt je z novější verze programu (formát {ver})")
        return cls(name=d.get("name", ""), meta=dict(d.get("meta", {})),
                   sheets=[Sheet.from_dict(s) for s in d.get("sheets", [])] or [Sheet()])

    def save(self, path: Path | str | None = None) -> None:
        p = Path(path) if path else self.path
        if p is None:
            raise ValueError("Projekt nemá cestu")
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self.path = p

    @classmethod
    def load(cls, path: Path | str) -> Project:
        p = Path(path)
        proj = cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
        proj.path = p
        return proj
