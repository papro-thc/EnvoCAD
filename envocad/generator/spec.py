"""Specifikace generátoru FVE – výběr topologie připojení (bez Qt). Návrh `docs/design/topologie_f1_f2.md`, kap. 1.1.

Pravidla (`docs/NAVRH_TOPOLOGIE.md`, kap. 8 – rozhodnutí):
- `spec["topology"]` zadané → ten preset (volba projektanta; jediná cesta k `nn_hr_meter` – měření v HR se
  automaticky nevolí, rozhodnutí 6);
- rodinný dům (`house`) → `rd` i nad 30 kWp (rozhodnutí 1); přípojka VN u RD → ValueError (jako `generate.py`);
- `connection.level == "vn"` → `vn` (firma volbou projektanta, rozhodnutí 1);
- jinak `nn` (firma – výchozí i pod 30 kWp; bytový dům, rozhodnutí 2).
Výkon (`installed_kwp`) výběr neovlivňuje – řídí jen síťovou ochranu nad 30 kWp (F2).

Pozn.: `BUILDINGS` a `building_kind` jsou zatím kopie z `envocad/generate.py` (sem je přesune refaktoring F1, krok 2);
tento modul z `generate.py` nic neimportuje.
"""
from __future__ import annotations

from collections.abc import Mapping

from envocad.model.topology import Topology

# role článků řetězce FVE (model je obor-nezávislý – role mu předává až generátor)
ROLES = ("rfve_dc", "inverter", "rfve_ac", "rfve", "rd", "hr", "re", "hds", "tr", "rvn", "grid")
# popisky článků bez vlastního označení v náhledu řetězce („stringy → RFVE.DC → T → … → DS“)
CHAIN_LABELS = {"inverter": "T", "grid": "DS"}
CHAIN_START = "stringy"
GRID_PROTECTION_KWP = 30.0   # nad tuto hranici instalovaného výkonu DC síťová ochrana (F2; `standard.grid_protection_kwp`)

# druh objektu (`spec["building"]`) → text v projektu (kopie `generate.BUILDINGS`)
BUILDINGS = {"company": "firma", "house": "rodinný dům", "apartment": "bytový dům"}
# automatický výběr presetu
AUTO_TOPOLOGY = {"house": "rd", "vn": "vn", "nn": "nn"}


def _s(v) -> str:
    return "" if v is None else str(v)


def building_kind(v) -> str:
    """Druh objektu ze specifikace: "company" | "house" | "apartment" (přijme i české „firma“, „rodinný dům“, „RD“,
    „bytový dům“, „BD“); prázdné = firma. Neznámá hodnota → ValueError. (Kopie `generate.building_kind`.)"""
    t = _s(v).strip().lower()
    if not t:
        return "company"
    aliases = {**{k: k for k in BUILDINGS}, **{c: k for k, c in BUILDINGS.items()},
               "rd": "house", "bd": "apartment", "rodinny dum": "house", "bytovy dum": "apartment"}
    if t not in aliases:
        raise ValueError(f"Neznámý druh objektu „{v}“ – zadejte firma, rodinný dům nebo bytový dům.")
    return aliases[t]


def connection_level(spec: Mapping) -> str:
    """Úroveň připojení ze specifikace: "vn" jen pro `connection.level` "vn", jinak "nn" (jako `generate.py`)."""
    conn = spec.get("connection") or {}
    return "vn" if _s(conn.get("level")).strip().lower() == "vn" else "nn"


def _num(v) -> float:
    try:
        return float(_s(v).replace(",", ".").strip() or 0)
    except ValueError:
        return 0.0


def installed_kwp(spec: Mapping) -> float:
    """Instalovaný výkon DC [kWp] = Σ modulů ve stringech × `module.p_wp` / 1000 (rozhodnutí 1). Chybí-li `p_wp`
    nebo počty modulů, počítá se 0 (specifikaci před sloučením s `DEFAULT_SPEC` doplní volající)."""
    p_wp = _num((spec.get("module") or {}).get("p_wp"))
    modules = sum(_num(n) for inv in spec.get("inverters") or [] if isinstance(inv, Mapping)
                  for n in inv.get("strings") or [])
    return round(modules * p_wp / 1000, 3)


def chain_text(topology: Topology) -> str:
    """Náhled řetězce FVE („stringy → RFVE.DC → T → RFVE.AC → HR → RE → HDS → DS“) – průvodce, `meta["topology_chain"]`."""
    return topology.chain_text(CHAIN_START, CHAIN_LABELS)


def check_topology(topology: Topology) -> list[str]:
    """Chyby topologie z pohledu generátoru FVE (česky): neznámé role, chybějící střídač."""
    errs = [f"Topologie „{topology.id}“: neznámá role „{n.role}“ – známé: {', '.join(ROLES)}."
            for n in topology.nodes if n.role not in ROLES]
    if topology.node("inverter") is None:
        errs.append(f"Topologie „{topology.id}“ nemá článek „inverter“ (střídače).")
    return errs


def select_topology(spec: Mapping, topologies: Mapping[str, Topology] | None = None) -> Topology:
    """Topologie pro specifikaci (pravidla v docstringu modulu). `topologies` = výsledek
    `library.topologies.load_topologies()` (None = načte se). Neplatná volba → ValueError (česky):
    neznámé `topology`, preset pro jiný druh objektu nebo jinou úroveň připojení než zadané `connection.level`,
    přípojka VN u rodinného domu, topologie s rolí, kterou generátor nezná."""
    if topologies is None:
        from envocad.library.topologies import load_topologies
        topologies = load_topologies()
    building = building_kind(spec.get("building"))
    conn = spec.get("connection") or {}
    level_given = _s(conn.get("level")).strip().lower()
    level = connection_level(spec)
    wanted = _s(spec.get("topology")).strip()
    if wanted:
        topo = topologies.get(wanted)
        if topo is None:
            known = ", ".join(sorted(topologies)) or "žádná"
            raise ValueError(f"Neznámá topologie „{wanted}“ – k dispozici: {known}.")
        if not level_given:
            level = topo.level   # úroveň připojení nezadaná → podle zvoleného presetu
    else:
        key = "house" if building == "house" else level
        topo = topologies.get(AUTO_TOPOLOGY[key])
        if topo is None:
            raise ValueError(f"Chybí topologie „{AUTO_TOPOLOGY[key]}“ (knihovna topologií).")
    if topo.buildings and building not in topo.buildings:
        allowed = ", ".join(BUILDINGS.get(b, b) for b in topo.buildings)
        raise ValueError(f"Topologie „{topo.name}“ je pro druh objektu {allowed}, ne pro {BUILDINGS[building]}.")
    if building == "house" and level == "vn":
        raise ValueError("Rodinný dům: rozvaděč FVE se připojuje do HDS (připojení na nn) – přípojka VN se "
                         "negeneruje. Zvolte druh objektu firma, nebo připojení nn.")
    if level != topo.level:
        raise ValueError(f"Topologie „{topo.name}“ je pro připojení na {topo.level}, ale specifikace má "
                         f"připojení na {level} (`connection.level`).")
    errs = check_topology(topo)
    if errs:
        raise ValueError(" ".join(errs))
    return topo
