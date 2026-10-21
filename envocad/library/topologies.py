"""Knihovna topologií připojení (presety řetězců) – bez Qt.

Soubory `*.json` (formát `docs/LIBRARY_FORMAT.md`, „Formát topologie“) ze tří složek, stejně jako makra:
vestavěné `library/builtin/topologies/`, sdílené `<shared_library_dir>/topologies/`, vlastní `~/.envocad/topologies/`.
Pozdější složka přebíjí stejné `id` (vlastní > sdílená > vestavěná). Neplatný soubor se vynechá (záznam v logu).
Načtené topologie drží cache podle mtime složek a souborů (`load_topologies`, `clear_cache`).
Model topologie: `envocad/model/topology.py`; výběr podle specifikace FVE: `envocad/generator/spec.py`.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Collection
from pathlib import Path

from envocad.model.topology import TOPOLOGY_VERSION, Topology, parse_topology

log = logging.getLogger("envocad.library")

BUILTIN_DIR = Path(__file__).parent / "builtin" / "topologies"
DIR_NAME = "topologies"   # název podsložky ve sdílené knihovně a v ~/.envocad (store.py ji nenačítá jako značky)
SOURCES = ("vestavěná", "sdílená", "vlastní")


def user_dir() -> Path:
    from envocad.settings import settings_path
    return settings_path().parent / DIR_NAME


def shared_dir() -> Path | None:
    try:
        from envocad.settings import shared_library_dir
        d = shared_library_dir()
    except Exception:  # noqa: BLE001 – vadné nastavení nesmí shodit načtení vestavěných
        return None
    return (Path(d) / DIR_NAME) if d else None


def topology_dirs() -> list[tuple[Path, str]]:
    """Složky topologií v pořadí přednosti (pozdější přebíjí): vestavěná, sdílená (je-li nastavená), vlastní."""
    out = [(BUILTIN_DIR, "vestavěná")]
    sd = shared_dir()
    if sd:
        out.append((sd, "sdílená"))
    out.append((user_dir(), "vlastní"))
    return out


def load_topology(path: Path | str, source: str = "vlastní",
                  known_roles: Collection[str] | None = None) -> Topology | None:
    """Topologie ze souboru; nečitelná, neplatná nebo vyšší verze → None + varování v logu."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as ex:
        log.warning("Topologie %s nelze načíst: %s", path, ex)
        return None
    try:
        return parse_topology(data, source, path, known_roles)
    except ValueError as ex:
        ver = data.get("version") if isinstance(data, dict) else None
        if isinstance(ver, int) and not isinstance(ver, bool) and ver > TOPOLOGY_VERSION:
            log.warning("Topologie %s má verzi %s, program umí nejvýše %s – přeskočeno", path, ver,
                        TOPOLOGY_VERSION)
        else:
            log.warning("Topologie %s je neplatná: %s", path, ex)
        return None


# cache `load_topologies`: klíč = role + stav složek (cesta, zdroj, mtime složky a jméno / mtime / velikost souborů);
# `build_project` tak sdílenou složku (síťový disk) při každém sestavení jen vylistuje, soubory znovu nečte
_CACHE: dict[tuple, dict[str, Topology]] = {}


def _dir_state(d: Path, source: str) -> tuple:
    try:
        files = tuple((p.name, st.st_mtime_ns, st.st_size) for p in sorted(d.glob("*.json"))
                      for st in (p.stat(),))
        return (str(d), source, d.stat().st_mtime_ns, files)
    except OSError:
        return (str(d), source, None, ())   # neexistující / nepřístupná složka


def clear_cache() -> None:
    """Zahodí cache topologií (další `load_topologies` soubory znovu načte)."""
    _CACHE.clear()


def load_topologies(known_roles: Collection[str] | None = None) -> dict[str, Topology]:
    """Všechny topologie podle `id` (vlastní > sdílená > vestavěná). Neplatné se vynechají (log – jednou, dokud se
    složka nezmění). Výsledek se drží v cache podle změn složek a souborů (`_dir_state`); vrací vždy nový slovník."""
    dirs = topology_dirs()
    key = (tuple(sorted(known_roles)) if known_roles is not None else None,
           tuple(_dir_state(d, source) for d, source in dirs))
    hit = _CACHE.get(key)
    if hit is not None:
        return dict(hit)
    found: dict[str, Topology] = {}
    for d, source in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            t = load_topology(p, source, known_roles)
            if t is not None:
                found[t.id] = t
    if len(_CACHE) > 16:      # jiné složky (testy, změna nastavení) – staré klíče nejsou potřeba
        _CACHE.clear()
    _CACHE[key] = found
    return dict(found)


def list_topologies(known_roles: Collection[str] | None = None) -> list[Topology]:
    """Výpis pro GUI: vestavěné první (rd, nn, nn_hr_meter, vn), pak sdílené a vlastní podle názvu."""
    order = {"rd": 0, "nn": 1, "nn_hr_meter": 2, "vn": 3}
    return sorted(load_topologies(known_roles).values(),
                  key=lambda t: (t.source != "vestavěná", order.get(t.id, 99), t.name.lower()))


def find_topology(topology_id: str, known_roles: Collection[str] | None = None) -> Topology | None:
    return load_topologies(known_roles).get(topology_id)
