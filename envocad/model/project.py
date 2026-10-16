"""Projekt → listy → elementy a vodiče. Čistá data, bez Qt."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from envocad.model.designation import CABLE_SCOPE, FUNC, LOC, scope_key, sheet_scope
from envocad.model.symbol import Attribute, Port, Symbol, rotate_point

# Atributy vodiče (vodič nemá symbol, proto jsou definované zde)
WIRE_ATTRIBUTES = [
    Attribute("ref", "Označení", "", True),
    Attribute("cable", "Typ kabelu", "", True),
    Attribute("cross", "Průřez [mm²]", "", True),
    Attribute("length", "Délka [m]"),
    Attribute("route", "Trasa / uložení"),
    Attribute("method", "Uložení dle ČSN (A1/B1/C/D/E)"),
]

FORMAT_VERSION = 9

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
    mp_pos: tuple[float, float] | None = None  # ruční pozice ve vícepólu (None = automatické rozmístění)
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
            **({"mp_pos": list(self.mp_pos)} if self.mp_pos else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Element:
        return cls(
            symbol_id=d["symbol_id"], x=d["x"], y=d["y"], rotation=d.get("rotation", 0),
            attrs=dict(d.get("attrs", {})), component_id=d.get("component_id"), id=d["id"],
            mp_pos=tuple(d["mp_pos"]) if d.get("mp_pos") else None,
        )


# Barvy žil dle ČSN 33 0165 ed. 2 / HD 308 S2 (kabely CYKY, NYY…); DC podle zvyklosti FVE (červená +, černá −)
CORE_COLORS = {"L1": "hnědá", "L2": "černá", "L3": "šedá", "L": "hnědá", "N": "modrá", "PE": "zelenožlutá",
               "PEN": "zelenožlutá", "DC+": "červená", "DC-": "černá", "+": "červená", "-": "černá",
               "L+": "červená", "L-": "černá"}


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
                   cores=[Core(c["name"], c.get("number", ""), c.get("color", "")) for c in d.get("cores", [])],
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

    def devices(self, sheet: Sheet, project: Project | None = None) -> list[Element]:
        """Přístroje listu pro rozložení: šířka > 0 a položka výkazu (cívka stykače se nepočítá, když skupina má
        stykač na stejném listu – `xref.DeviceIndex.is_bom_device`). Bez `project` se skupiny hledají jen na listu."""
        from envocad.model.xref import DeviceIndex
        idx = DeviceIndex.build(project) if project is not None else DeviceIndex.for_sheets([sheet])
        return [e for e in sheet.elements if e.modules > 0 and idx.is_bom_device(e, sheet)]

    def used_modules(self, sheet: Sheet, project: Project | None = None) -> float:
        devs = {e.id: e for e in self.devices(sheet, project)}
        return sum(devs[pl.element_id].modules for pl in self.placements if pl.element_id in devs)

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

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "date": self.date, "author": self.author,
                "description": self.description, "closed": self.closed, "marks": [m.to_dict() for m in self.marks],
                "fingerprints": dict(self.fingerprints)}

    @classmethod
    def from_dict(cls, d: dict) -> Revision:
        return cls(label=str(d.get("label", "")), date=d.get("date", ""), author=d.get("author", ""),
                   description=d.get("description", ""), closed=bool(d.get("closed")),
                   marks=[RevisionMark.from_dict(m) for m in d.get("marks", [])],
                   fingerprints={str(k): str(v) for k, v in (d.get("fingerprints") or {}).items()},
                   id=d.get("id") or _uid())


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
    # můstky (propoje) svorkovnic tohoto listu: {"X2": [["1", "6", "11"], ["2", "7", "12"]]} – čísla svorek spojená můstkem
    bridges: dict[str, list[list[str]]] = field(default_factory=dict)
    # strukturní označení listu (IEC 81346) – výchozí aspekty prvků a vodičů listu; kódy bez znaménka
    func: str = ""                        # "=" funkce
    loc: str = ""                         # "+" umístění (list rozvaděče = označení bloku)
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
            "bridges": self.bridges, "func": self.func, "loc": self.loc,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Sheet:
        return cls(
            name=d.get("name", ""), paper=d.get("paper", "A3"), width=d.get("width", 420), height=d.get("height", 297),
            kind=d.get("kind", "schematic"), parent_element_id=d.get("parent_element_id"),
            layout=Layout.from_dict(d.get("layout")),
            elements=[Element.from_dict(e) for e in d.get("elements", [])],
            wires=[Wire.from_dict(w) for w in d.get("wires", [])], id=d["id"],
            bridges={k: [[str(x) for x in g] for g in v] for k, v in d.get("bridges", {}).items()},
            func=d.get("func", ""), loc=d.get("loc", ""),
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
        sheet = Sheet(name=f"{name} – {desc}" if desc else name, kind="switchboard", parent_element_id=block.id,
                      loc=block.ref)
        self.sheets.append(sheet)
        block.attrs["sheet"] = sheet.name
        if block.ref and self.structure(LOC, block.ref) is None:
            self.structures.append(StructureId(LOC, block.ref, desc))
        return sheet

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
        if d.get("format") != "envocad-project":
            raise ValueError("Soubor není projekt EnvoCAD")
        ver = d.get("format_version", 1)
        if ver > FORMAT_VERSION:
            raise ValueError(f"Projekt je z novější verze programu (formát {ver})")
        d = migrate(d, ver)
        return cls(name=d.get("name", ""), meta=dict(d.get("meta", {})),
                   sheets=[Sheet.from_dict(s) for s in d.get("sheets", [])] or [Sheet()],
                   cables=[Cable.from_dict(c) for c in d.get("cables", [])],
                   structures=[StructureId.from_dict(x) for x in d.get("structures", [])],
                   revisions=[Revision.from_dict(r) for r in d.get("revisions", [])],
                   notes=[Note.from_dict(n) for n in d.get("notes", [])])

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
    # v4: volitelné `mp_pos` prvku (ruční pozice ve vícepólu) – bez migrace
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
                    w["conductors"] = ["DC+", "DC-"]
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
    d["format_version"] = FORMAT_VERSION
    return d


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


FEED_SYMBOLS = {"sb.feed_in", "sb.feed_out"}


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
        label = f"{w.attrs.get('ref') or '(bez označení)'}: {a.ref or a.symbol_id}:{w.a.port} → {b.ref or b.symbol_id}:{w.b.port}"
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
    """Atributy přívodu/vývodu odvozené z navázaného vodiče JPS (odkud/kam, kabel)."""
    e2 = Element(symbol_id=e.symbol_id, attrs={"wire_id": wire_id})
    hit = linked_wire(project, sheet, e2)
    if hit is None:
        return {"wire_id": "", "from": "", "to": "", "cable": ""} if not wire_id else {}
    s, w = hit
    block = sheet.parent_element_id
    far_end = w.b if w.a.element_id == block else w.a
    far = s.element(far_end.element_id)
    from envocad.model.frame import position_ref
    text = f"{w.attrs.get('ref', '')} {far.ref or far.symbol_id}:{far_end.port} {position_ref(project, s, far.x, far.y)}".strip()
    cable = " ".join(x for x in (w.attrs.get("cable", ""), w.attrs.get("cross", "")) if x)
    key = "from" if e.symbol_id == "sb.feed_in" else "to"
    return {"wire_id": wire_id, key: text, "cable": cable}


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
    (výkazy a překreslení s 800 vodiči by jinak procházely všechny přívody × vodiče pokaždé)."""
    out: dict[str, list[tuple[Sheet, Element]]] = {}
    for s in project.sheets:
        for e in s.elements:
            if e.symbol_id not in FEED_SYMBOLS:
                continue
            hit = linked_wire(project, s, e)
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


def switchboard_symbol(project: Project, e: Element, base: Symbol) -> Symbol:
    """Značka bloku ROZVADĚČ odvozená z jeho listu: port za každý přívod (vlevo) a vývod (vpravo),
    pojmenovaný označením svorky (X1, X4…). Bez listu zůstává základní značka. Porty, na které ještě vedou
    vodiče se starými názvy (1–4), se zachovají, aby se nic nerozpojilo."""
    sheet = project.switchboard_sheet(e.id)
    if sheet is None:
        return base
    def nat(f: Element) -> tuple:
        m = re.match(r"([A-Za-z]*)(\d*)(.*)", f.ref)
        return (m.group(1), int(m.group(2)) if m.group(2) else 10**9, m.group(3))
    feeds_in = sorted((f for f in sheet.elements if f.symbol_id == "sb.feed_in" and f.ref), key=nat)
    feeds_out = sorted((f for f in sheet.elements if f.symbol_id == "sb.feed_out" and f.ref), key=nat)
    if not feeds_in and not feeds_out:
        return base
    n = max(len(feeds_in), len(feeds_out), 1)
    h = max(20.0, n * PORT_PITCH + PORT_PITCH)
    half = h / 2
    prims: list = [{"type": "rect", "x": -15, "y": -half, "w": 30, "h": h},
                   {"type": "text", "x": 0, "y": half + 1.5, "text": "ROZVADĚČ", "height": 2, "align": "center"}]
    ports: list[Port] = []
    for i, f in enumerate(feeds_in):
        y = half - PORT_PITCH / 2 - i * PORT_PITCH
        y = round(y / 2.5) * 2.5
        ports.append(Port(f.ref, -15, y, "W"))
        prims.append({"type": "text", "x": -13.5, "y": y - 0.8, "text": f.ref, "height": 1.8, "align": "left"})
    for i, f in enumerate(feeds_out):
        y = half - PORT_PITCH / 2 - i * PORT_PITCH
        y = round(y / 2.5) * 2.5
        ports.append(Port(f.ref, 15, y, "E"))
        prims.append({"type": "text", "x": 13.5, "y": y - 0.8, "text": f.ref, "height": 1.8, "align": "right"})
    names = {p.name for p in ports}
    parent = project.sheet_of_element(e.id)
    used = {end.port for w in (parent.wires if parent else []) for end in (w.a, w.b) if end.element_id == e.id}
    for p in base.ports:  # staré porty, dokud na ně něco vede
        if p.name in used and p.name not in names:
            ports.append(Port(p.name, p.x, p.y if abs(p.y) < half else (half if p.y > 0 else -half), p.dir))
            names.add(p.name)
    # vodiče na smazaný/přejmenovaný přívod či vývod: port zůstane dole (nic se nerozpojí), označený „?“
    for k, name in enumerate(sorted(used - names)):
        x = round((-10 + k * 10) / 2.5) * 2.5
        ports.append(Port(name, x, -half, "S"))
        prims.append({"type": "text", "x": x, "y": -half + 1.0, "text": f"{name}?", "height": 1.8, "align": "center"})
    return Symbol(id=base.id, name=base.name, category=base.category, description=base.description,
                  iec_ref=base.iec_ref, function_class=base.function_class, primitives=prims, ports=ports, attributes=base.attributes,
                  label_pos=(-15, -half - 3))


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


def inverter_symbol(project: Project, e: Element, base: Symbol) -> Symbol:
    """Značka střídače s DC vstupem na každý string (DC1…DCn vlevo); základní značka má DC1/DC2."""
    n = inverter_dc_inputs(project, e)
    if n <= 2:
        return base
    h = max(20.0, 5.0 * n + 5.0)
    half = h / 2
    prims = []
    for pr in base.primitives:
        if pr.get("type") == "rect" and pr.get("w") == 20:
            prims.append({**pr, "y": -half, "h": h})
        elif pr.get("type") == "line" and pr.get("x1") == -10 and pr.get("y1") == -10 and pr.get("x2") == 10 and pr.get("y2") == 10:
            prims.append({**pr, "y1": -half, "y2": half})
        else:
            prims.append(pr)
    ports = [Port(f"DC{k + 1}", -10, 2.5 * (n - 1) - 5 * k, "W") for k in range(n)]
    ports += [p for p in base.ports if not p.name.startswith("DC")]
    ports = [Port(p.name, p.x, (-half if p.y == -10 else (half if p.y == 10 else p.y)), p.dir) for p in ports]
    return Symbol(id=base.id, name=base.name, category=base.category, description=base.description, iec_ref=base.iec_ref, function_class=base.function_class,
                  primitives=prims, ports=ports, attributes=base.attributes, multipole=base.multipole,
                  label_pos=(base.label_pos[0], half + 10.0))


def element_symbol(project: Project, e: Element, lib) -> Symbol:
    """Značka prvku – blok ROZVADĚČ podle jeho listu, střídač podle počtu DC vstupů, jinak z knihovny."""
    base = lib.get_symbol(e.symbol_id)
    if e.symbol_id == "fve.switchboard":
        return switchboard_symbol(project, e, base)
    if e.symbol_id in INVERTER_SYMBOLS:
        return inverter_symbol(project, e, base)
    return base


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


def sync_feed_links(project: Project) -> int:
    """Přívody/vývody rozvaděčů se navážou na vodiče JPS podle portu bloku (X1 → port X1); vrací počet změn.
    Ruční vazba (`wire_id` na jiný vodič) má přednost, pokud ten vodič ještě existuje."""
    changed = 0
    for s in project.sheets:
        if not s.is_switchboard:
            continue
        for f in s.elements:
            if f.symbol_id not in FEED_SYMBOLS:
                continue
            cur = f.attrs.get("wire_id", "")
            if cur and linked_wire(project, s, f) is not None and feed_wire_by_port(project, s, f) is None:
                # ruční vazba (nebo přejmenovaný přívod/vývod): konec vodiče na bloku se přejmenuje na nové označení
                _, lw = linked_wire(project, s, f)
                block = s.parent_element_id
                for end in (lw.a, lw.b):
                    if end.element_id == block and end.port != f.ref and f.ref:
                        end.port = f.ref
                        changed += 1
                continue
            w = feed_wire_by_port(project, s, f)
            new_id = w.id if w else ""
            if new_id != cur or (new_id and not f.attrs.get("cable") and w.attrs.get("cable")):
                f.attrs.update(feed_link_attrs(project, s, f, new_id))
                if w and w.conductors:
                    for sw in s.wires:
                        if sw.touches(f.id) and sw.conductors != list(w.conductors):
                            sw.conductors = list(w.conductors)
                changed += 1
    return changed


# ---- kabely ↔ vodiče -------------------------------------------------------------------------------------
def sync_cables(project: Project) -> int:
    """Z vodičů JPS (s označením nebo typem kabelu) udržuje objekty Cable: typ/průřez/délka/trasa se berou
    z atributů vodiče (ten je editační místo), žíly z `Wire.conductors` (barvy se dopočítají a ručně upravené
    zůstanou). Vodiče uvnitř rozvaděčů kabel nedostanou. Vrací počet změn."""
    changed = 0
    for s in project.sheets:
        if s.is_switchboard:
            continue
        for w in s.wires:
            ref = w.attrs.get("ref", "")
            if not ref and not w.attrs.get("cable"):
                continue
            c = project.cable_of_wire(w)
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
