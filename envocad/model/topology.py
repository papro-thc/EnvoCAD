"""Topologie připojení – řetězec článků od zdroje k síti jako data (bez Qt, obor-nezávislé).

Topologie je seznam článků (`ChainNode`) v pořadí toku energie; role článku je jen řetězec (význam rolí zná až
generátor oboru – FVE: `envocad/generator/spec.py`). Presety jsou JSON soubory knihovny (`library/topologies.py`,
formát `docs/LIBRARY_FORMAT.md`, „Formát topologie“). Návrh `docs/design/topologie_f1_f2.md`, kap. 1.1.
**Formát projektu se nemění** – topologie žije ve specifikaci, v presetech a v `Project.meta` (řetězce).
"""
from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

TOPOLOGY_VERSION = 1
LEVELS = ("nn", "vn")

_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")
_ROLE = re.compile(r"^[a-z][a-z0-9_]*$")
_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TOP_KEYS = frozenset({"version", "id", "name", "description", "buildings", "level", "nodes"})
NODE_KEYS = frozenset({"role", "ref", "desc", "per_inverter", "sheet", "existing", "branch", "macros", "options",
                       "link"})
NODE_FLAGS = ("per_inverter", "sheet", "existing", "branch")
LINK_KEYS = ("cable", "cross", "length", "method")


def _text(v) -> str:
    """Skalár z JSON → řetězec (čísla bez zbytečné nuly, pravda/nepravda → „1“/„0“)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _scalar(v) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


@dataclass(frozen=True)
class CableLink:
    """Kabel od článku k dalšímu článku směrem k síti (prázdné = podle specifikace / generátoru)."""
    cable: str = ""
    cross: str = ""
    length: str = ""
    method: str = ""


@dataclass(frozen=True)
class ChainNode:
    """Článek řetězce. `per_inverter` = jeden na střídač (jinak společný), `sheet` = má list rozvaděče (False = jen
    blok), `existing` = stávající (kreslí se jen dotčená část), `branch` = odbočka mimo hlavní tok (např. měření).
    `macros`: role makra → název makra; `options`: výchozí hodnoty článku (specifikace je přebíjí)."""
    role: str
    ref: str = ""
    desc: str = ""
    per_inverter: bool = False
    sheet: bool = True
    existing: bool = False
    branch: bool = False
    macros: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}), hash=False)
    options: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}), hash=False)
    link: CableLink = CableLink()


@dataclass(frozen=True)
class Topology:
    id: str
    name: str
    nodes: tuple[ChainNode, ...]
    description: str = ""
    buildings: tuple[str, ...] = ()
    level: str = "nn"
    source: str = "vestavěná"
    path: Path | None = field(default=None, compare=False)

    def node(self, role: str) -> ChainNode | None:
        """Článek s rolí `role` (role jsou v topologii jedinečné), jinak None."""
        return next((n for n in self.nodes if n.role == role), None)

    def roles(self) -> tuple[str, ...]:
        return tuple(n.role for n in self.nodes)

    def flow(self) -> tuple[ChainNode, ...]:
        """Články hlavního toku (bez odboček `branch`) v pořadí od zdroje k síti."""
        return tuple(n for n in self.nodes if not n.branch)

    def chain_text(self, start: str = "", labels: Mapping[str, str] | None = None) -> str:
        """Náhled řetězce „start → A → B …“ (odbočky v závorce na konci „(+ RE)“). Popisek článku: `labels[role]`
        > `ref` > `role`. Obor dodá `start` a popisky rolí bez označení (FVE: `generator.spec.chain_text`)."""
        labels = labels or {}

        def label(n: ChainNode) -> str:
            return labels.get(n.role) or n.ref or n.role

        parts = ([start] if start else []) + [label(n) for n in self.flow()]
        text = " → ".join(parts)
        branches = [label(n) for n in self.nodes if n.branch]
        if branches:
            text += " (" + ", ".join("+ " + b for b in branches) + ")"
        return text


def _check_str(errs: list[str], where: str, key: str, v, *, required: bool = False) -> None:
    if v is None or v == "":
        if required:
            errs.append(f"{where}: chybí „{key}“.")
        return
    if not isinstance(v, str):
        errs.append(f"{where}: „{key}“ musí být text.")


def _check_map(errs: list[str], where: str, key: str, v) -> None:
    if v is None:
        return
    if not isinstance(v, dict):
        errs.append(f"{where}: „{key}“ musí být objekt (klíč → hodnota).")
        return
    for k, val in v.items():
        if not _KEY.match(str(k)):
            errs.append(f"{where}: neplatný klíč „{k}“ v „{key}“ (písmena, číslice, podtržítko).")
        if not _scalar(val):
            errs.append(f"{where}: hodnota „{key}.{k}“ musí být text, číslo nebo ano/ne.")


def validate_topology(data, known_roles: Collection[str] | None = None) -> list[str]:
    """Chyby topologie (česky); prázdný seznam = platná. `known_roles` = role, které zná volající (generátor oboru);
    None = role se proti seznamu nekontrolují (jen tvar)."""
    if not isinstance(data, dict):
        return ["Topologie musí být objekt JSON."]
    errs: list[str] = []
    for k in sorted(set(data) - TOP_KEYS):
        errs.append(f"Neznámý klíč topologie „{k}“.")
    ver = data.get("version", 1)
    if isinstance(ver, bool) or not isinstance(ver, int) or ver < 1:
        errs.append(f"Neplatná verze topologie: {ver!r} (celé číslo od 1).")
    elif ver > TOPOLOGY_VERSION:
        errs.append(f"Topologie má verzi {ver}, program umí nejvýše {TOPOLOGY_VERSION}.")
    tid = data.get("id")
    if not isinstance(tid, str) or not tid.strip():
        errs.append("Chybí „id“ topologie.")
    elif not _ID.match(tid):
        errs.append(f"Neplatné „id“ topologie „{tid}“ (písmena, číslice, podtržítko, tečka, pomlčka).")
    _check_str(errs, "Topologie", "name", data.get("name"), required=True)
    _check_str(errs, "Topologie", "description", data.get("description"))
    level = data.get("level", "nn")
    if level not in LEVELS:
        errs.append(f"Neplatná úroveň připojení „{level}“ – zadejte nn nebo vn.")
    buildings = data.get("buildings", [])
    if not isinstance(buildings, list) or not all(isinstance(b, str) and b.strip() for b in buildings):
        errs.append("„buildings“ musí být seznam textů (druhy objektů).")
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errs.append("Topologie musí mít neprázdný seznam článků „nodes“.")
        return errs
    seen: set[str] = set()
    for i, n in enumerate(nodes, 1):
        where = f"Článek {i}"
        if not isinstance(n, dict):
            errs.append(f"{where}: musí být objekt JSON.")
            continue
        role = n.get("role")
        if not isinstance(role, str) or not role.strip():
            errs.append(f"{where}: chybí „role“.")
        elif not _ROLE.match(role):
            errs.append(f"{where}: neplatná role „{role}“ (malá písmena, číslice, podtržítko).")
        else:
            where = f"Článek {i} ({role})"
            if known_roles is not None and role not in known_roles:
                errs.append(f"{where}: neznámá role „{role}“ – známé: {', '.join(sorted(known_roles))}.")
            if role in seen:
                errs.append(f"{where}: role „{role}“ je v topologii dvakrát.")
            seen.add(role)
        for k in sorted(set(n) - NODE_KEYS):
            errs.append(f"{where}: neznámý klíč „{k}“.")
        for k in ("ref", "desc"):
            _check_str(errs, where, k, n.get(k))
        for k in NODE_FLAGS:
            if k in n and not isinstance(n[k], bool):
                errs.append(f"{where}: „{k}“ musí být true nebo false.")
        _check_map(errs, where, "macros", n.get("macros"))
        _check_map(errs, where, "options", n.get("options"))
        link = n.get("link")
        if link is not None:
            if not isinstance(link, dict):
                errs.append(f"{where}: „link“ musí být objekt (cable, cross, length, method).")
            else:
                for k in sorted(set(link) - set(LINK_KEYS)):
                    errs.append(f"{where}: neznámý klíč „link.{k}“ (cable, cross, length, method).")
                for k, val in link.items():
                    if not _scalar(val) or isinstance(val, bool):
                        errs.append(f"{where}: „link.{k}“ musí být text nebo číslo.")
    if nodes and all(isinstance(n, dict) and n.get("branch") is True for n in nodes):
        errs.append("Topologie nemá žádný článek hlavního toku (všechny jsou odbočky).")
    return errs


def parse_topology(data, source: str = "vlastní", path: Path | str | None = None,
                   known_roles: Collection[str] | None = None) -> Topology:
    """Topologie z JSON dat. Neplatná data → ValueError se všemi chybami (česky, `validate_topology`)."""
    errs = validate_topology(data, known_roles)
    if errs:
        raise ValueError("Neplatná topologie: " + " ".join(errs))
    nodes = []
    for n in data["nodes"]:
        link = n.get("link") or {}
        nodes.append(ChainNode(
            role=n["role"], ref=_text(n.get("ref")).strip(), desc=_text(n.get("desc")).strip(),
            per_inverter=bool(n.get("per_inverter", False)), sheet=bool(n.get("sheet", True)),
            existing=bool(n.get("existing", False)), branch=bool(n.get("branch", False)),
            macros=MappingProxyType({str(k): _text(v) for k, v in (n.get("macros") or {}).items()}),
            options=MappingProxyType({str(k): _text(v) for k, v in (n.get("options") or {}).items()}),
            link=CableLink(**{k: _text(link.get(k)) for k in LINK_KEYS})))
    return Topology(id=data["id"].strip(), name=data["name"].strip(), nodes=tuple(nodes),
                    description=_text(data.get("description")).strip(),
                    buildings=tuple(b.strip() for b in data.get("buildings") or ()),
                    level=data.get("level", "nn"), source=source, path=Path(path) if path else None)
