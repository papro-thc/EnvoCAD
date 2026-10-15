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

FORMAT_VERSION = 3

MODULE_WIDTH = 17.5  # mm – šířka jednoho modulu na DIN liště
SHEET_KINDS = ("schematic", "switchboard")


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

    @property
    def poles(self) -> int:
        try:
            return int(self.attrs.get("poles") or 1)
        except ValueError:
            return 1

    @property
    def modules(self) -> float:
        """Šířka přístroje v modulech (17,5 mm) pro rozložení na DIN liště."""
        try:
            return float(str(self.attrs.get("modules") or "0").replace(",", "."))
        except ValueError:
            return 0.0

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
        return cls(
            a=WireEnd(**d["a"]), b=WireEnd(**d["b"]),
            points=[tuple(p) for p in d.get("points", [])], attrs=dict(d.get("attrs", {})),
            conductors=list(d.get("conductors", [])), terminals=dict(d.get("terminals", {})), id=d["id"],
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
    def total_modules(self) -> int:
        return self.rows * self.modules_per_row

    def used_modules(self, sheet: Sheet) -> float:
        return sum(sheet.element(pl.element_id).modules for pl in self.placements
                   if any(e.id == pl.element_id for e in sheet.elements))

    def placement(self, eid: str) -> Placement | None:
        return next((p for p in self.placements if p.element_id == eid), None)

    def set_placement(self, eid: str, row: int | None, pos: float | None) -> None:
        self.placements = [p for p in self.placements if p.element_id != eid]
        if row is not None and pos is not None:
            self.placements.append(Placement(eid, row, pos))

    def to_dict(self) -> dict:
        return {"rows": self.rows, "modules_per_row": self.modules_per_row, "enclosure": self.enclosure,
                "params": self.params, "placements": [p.to_dict() for p in self.placements]}

    @classmethod
    def from_dict(cls, d: dict | None) -> Layout:
        d = d or {}
        return cls(rows=int(d.get("rows", 3)), modules_per_row=int(d.get("modules_per_row", 24)),
                   enclosure=d.get("enclosure", ""), params=dict(d.get("params", {})),
                   placements=[Placement(**p) for p in d.get("placements", [])])


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
    ("rdf", "RDF (Ib/In)", "0,8"),
    ("note", "Poznámka", ""),
]



@dataclass
class Sheet:
    name: str = "Jednopólové schéma"
    paper: str = "A3"
    width: float = 420.0
    height: float = 297.0
    elements: list[Element] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)
    kind: str = "schematic"               # "schematic" | "switchboard"
    parent_element_id: str | None = None  # blok ROZVADĚČ na nadřazeném listu, který tento list reprezentuje
    layout: Layout = field(default_factory=Layout)
    id: str = field(default_factory=_uid)

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
        }

    @classmethod
    def from_dict(cls, d: dict) -> Sheet:
        return cls(
            name=d.get("name", ""), paper=d.get("paper", "A3"), width=d.get("width", 420), height=d.get("height", 297),
            kind=d.get("kind", "schematic"), parent_element_id=d.get("parent_element_id"),
            layout=Layout.from_dict(d.get("layout")),
            elements=[Element.from_dict(e) for e in d.get("elements", [])],
            wires=[Wire.from_dict(w) for w in d.get("wires", [])], id=d["id"],
        )


@dataclass
class Project:
    name: str = "Nový projekt"
    meta: dict[str, str] = field(default_factory=dict)  # investor, číslo zakázky, místo, zpracoval…
    sheets: list[Sheet] = field(default_factory=lambda: [Sheet()])
    # můstky (propoje) svorkovnic: {"X2": [["1", "6", "11"], ["2", "7", "12"]]} – čísla svorek spojená můstkem
    bridges: dict[str, list[list[str]]] = field(default_factory=dict)
    path: Path | None = None

    # ---- svorkovnice -------------------------------------------------
    def bridge_groups(self, strip: str) -> list[list[str]]:
        return [list(g) for g in self.bridges.get(strip, [])]

    def set_bridges(self, strip: str, groups: list[list[str]]) -> None:
        groups = [[str(x).strip() for x in g if str(x).strip()] for g in groups]
        groups = [g for g in groups if len(g) >= 2]
        if groups:
            self.bridges[strip] = groups
        else:
            self.bridges.pop(strip, None)

    def bridge_of(self, strip: str, number: str) -> list[str]:
        """Skupina svorek propojených můstkem se svorkou `strip:number` (včetně ní), nebo []."""
        for g in self.bridges.get(strip, []):
            if number in g:
                return list(g)
        return []

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

    # ---- listy -------------------------------------------------------
    def sheet(self, sid: str) -> Sheet:
        for s in self.sheets:
            if s.id == sid:
                return s
        raise KeyError(sid)

    def sheet_of_element(self, eid: str) -> Sheet | None:
        return next((s for s in self.sheets if any(e.id == eid for e in s.elements)), None)

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
        sheet = Sheet(name=f"{name} – {desc}" if desc else name, kind="switchboard", parent_element_id=block.id)
        self.sheets.append(sheet)
        block.attrs["sheet"] = sheet.name
        return sheet

    def switchboards(self) -> list[Sheet]:
        return [s for s in self.sheets if s.is_switchboard]

    # ---- serializace -------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "format": "envocad-project", "format_version": FORMAT_VERSION,
            "name": self.name, "meta": self.meta, "sheets": [s.to_dict() for s in self.sheets],
            "bridges": self.bridges,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Project:
        if d.get("format") != "envocad-project":
            raise ValueError("Soubor není projekt EnvoCAD")
        ver = d.get("format_version", 1)
        if ver > FORMAT_VERSION:
            raise ValueError(f"Projekt je z novější verze programu (formát {ver})")
        d = migrate(d, ver)
        return cls(name=d.get("name", ""), meta=dict(d.get("meta", {})),
                   sheets=[Sheet.from_dict(s) for s in d.get("sheets", [])] or [Sheet()],
                   bridges={k: [[str(x) for x in g] for g in v] for k, v in d.get("bridges", {}).items()})

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


def migrate(d: dict, ver: int) -> dict:
    """Převede slovník projektu ze starší verze formátu na aktuální."""
    if ver < 2:
        # v1: listy bez kind/layout, vodiče bez conductors – doplní se výchozí hodnoty při from_dict
        for s in d.get("sheets", []):
            s.setdefault("kind", "schematic")
    if ver < 3:
        d.setdefault("bridges", {})  # v3: můstky svorkovnic
    d["format_version"] = FORMAT_VERSION
    return d


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


def copy_fragment(sheet: Sheet, element_ids: list[str]) -> dict:
    """Výřez listu pro schránku: vybrané prvky + vodiče mezi nimi (čistá data, přenositelná mezi listy)."""
    ids = set(element_ids)
    els = [e.to_dict() for e in sheet.elements if e.id in ids]
    wires = [w.to_dict() for w in sheet.wires if w.a.element_id in ids and w.b.element_id in ids]
    return {"elements": els, "wires": wires}


def paste_fragment(project: Project, fragment: dict, ref_prefix_of, dx: float = 10.0, dy: float = -10.0
                   ) -> tuple[list[Element], list[Wire]]:
    """Vytvoří kopie s novými id a označeními (F1 → další volné), posunuté o (dx, dy). Skupiny svorek si nechají
    označení svorkovnice, čísla svorek se vymažou (doplní automatické číslování). Nic nevkládá do listu."""
    used = project.used_refs()
    idmap: dict[str, str] = {}
    els: list[Element] = []
    for d in fragment.get("elements", []):
        e = Element.from_dict(d)
        new = Element(symbol_id=e.symbol_id, x=e.x + dx, y=e.y + dy, rotation=e.rotation,
                      attrs=dict(e.attrs), component_id=e.component_id)
        prefix = ref_prefix_of(e.symbol_id)
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
                  points=[(x + dx, y + dy) for x, y in w.points], attrs=dict(w.attrs), conductors=list(w.conductors))
        if nw.attrs.get("ref"):
            n = 1
            while f"W{n}" in used:
                n += 1
            nw.attrs["ref"] = f"W{n}"
            used.add(nw.attrs["ref"])
        wires.append(nw)
    return els, wires
