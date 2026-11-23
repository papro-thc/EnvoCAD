"""Archiv projektu `.ecpz` (zip): projekt + jeho uživatelské (nevestavěné) značky a artikly. Bez Qt.

Členy archivu (ploché, bez složek): `manifest.json`, `project.ecp` (stejný JSON jako `Project.save`),
`symbols.json` (seznam `Symbol.to_dict()`), `components.json` (seznam tvaru `LibraryStore.get_component`).
Čtení nic nerozbaluje na disk a odmítá nebezpečná jména členů i zip bomby. Import do knihovny nikdy nepřepíše
rozdílnou položku bez `overwrite=True`; vestavěnou značku nepřepíše nikdy.
"""
from __future__ import annotations

import json
import logging
import os
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from envocad import __version__
from envocad.library.store import BUILTIN_DIR, LibraryStore
from envocad.model.project import Project
from envocad.model.symbol import Symbol, SymbolVersionError

log = logging.getLogger("envocad.library")

ARCHIVE_SUFFIX = ".ecpz"
ARCHIVE_FORMAT = 1
MAX_TOTAL_BYTES = 200 * 1024 * 1024          # limit nekomprimované velikosti všech členů (ochrana proti zip bombě)
_KNOWN = ("manifest.json", "project.ecp", "symbols.json", "components.json")


class ArchiveError(ValueError):
    """Poškozený nebo nebezpečný archiv projektu – text je česky pro uživatele."""


@dataclass
class ProjectArchive:
    project: dict
    symbols: list[Symbol] = field(default_factory=list)
    components: list[dict] = field(default_factory=list)


@dataclass
class ImportReport:
    new_symbols: list[str] = field(default_factory=list)
    new_components: list[str] = field(default_factory=list)
    conflict_symbols: list[str] = field(default_factory=list)
    conflict_components: list[str] = field(default_factory=list)

    @property
    def conflicts(self) -> bool:
        return bool(self.conflict_symbols or self.conflict_components)


# ---- balení ----------------------------------------------------------------------------------------------------
def _collect_ids(node, key: str, out: set[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, str) and v:
                out.add(v)
            else:
                _collect_ids(v, key, out)
    elif isinstance(node, list):
        for v in node:
            _collect_ids(v, key, out)


@lru_cache(maxsize=1)
def _builtin_components() -> dict[str, dict]:
    """Vestavěné artikly (CSV pod `BUILTIN_DIR`) ve tvaru, v jakém je do knihovny zapisuje `LibraryStore`."""
    from envocad.library.components import read_csv
    out: dict[str, dict] = {}
    for f in sorted(BUILTIN_DIR.rglob("*.csv")):
        try:
            comps = read_csv(f)
        except Exception as ex:  # noqa: BLE001 – vadný soubor nesmí shodit balení
            log.warning("archiv: vestavěné artikly %s se nenačetly: %s", f, ex)
            continue
        for c in comps:
            out[c.id] = {"id": c.id, "manufacturer": c.manufacturer, "part_number": c.part_number, "name": c.name,
                         "symbol_id": c.symbol_id or None, "params": c.to_db_row()["params"], "price": c.price,
                         "url": c.datasheet_url}
    return out


def _is_builtin_component(comp: dict) -> bool:
    return _builtin_components().get(comp["id"]) == comp


def pack_project(project: Project, store: LibraryStore, path: Path | str) -> ProjectArchive:
    """Zabalí projekt s použitými nevestavěnými značkami a artikly do `path` (atomicky). Id, která knihovna nezná,
    se přeskočí (projekt na ně jen odkazuje)."""
    data = project.to_dict()
    comp_ids: set[str] = set()
    sym_ids: set[str] = set()
    _collect_ids(data, "component_id", comp_ids)
    _collect_ids(data, "symbol_id", sym_ids)
    components: list[dict] = []
    for cid in sorted(comp_ids):
        comp = store.get_component(cid)
        if comp is None or _is_builtin_component(comp):
            continue
        components.append(comp)
        if comp.get("symbol_id"):
            sym_ids.add(comp["symbol_id"])
        fp = (comp.get("params") or {}).get("footprint_id")
        if isinstance(fp, str) and fp:
            sym_ids.add(fp)
    symbols = []
    for sid in sorted(sym_ids):
        if not store.has_symbol(sid) or store.is_builtin(sid):
            continue
        try:
            symbols.append(store.get_symbol(sid))
        except KeyError:   # značka v knihovně je z novější verze programu (varování zapsal store) – nebalí se
            continue

    def dump(obj) -> str:
        return json.dumps(obj, ensure_ascii=False, indent=1)

    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", dump({"format": ARCHIVE_FORMAT, "app": __version__}))
            z.writestr("project.ecp", dump(data))
            z.writestr("symbols.json", dump([s.to_dict() for s in symbols]))
            z.writestr("components.json", dump(components))
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)
    log.info("archiv: %s – %d značek, %d artiklů", p, len(symbols), len(components))
    return ProjectArchive(project=data, symbols=symbols, components=components)


# ---- čtení -----------------------------------------------------------------------------------------------------
def _json_member(z: zipfile.ZipFile, name: str, budget: list[int], required: bool):
    try:
        info = z.getinfo(name)
    except KeyError:
        if required:
            raise ArchiveError(f"Archiv je poškozen: chybí „{name}“") from None
        return []
    if info.file_size > budget[0]:
        raise ArchiveError("Archiv je příliš velký (nekomprimovaná data překračují limit) – soubor se nenačte")
    with z.open(info) as fh:
        raw = fh.read(budget[0] + 1)
    if len(raw) > budget[0]:
        raise ArchiveError("Archiv je příliš velký (nekomprimovaná data překračují limit) – soubor se nenačte")
    budget[0] -= len(raw)
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ArchiveError(f"Archiv je poškozen: „{name}“ není platný JSON") from None


def read_archive(path: Path | str) -> ProjectArchive:
    """Přečte archiv bez rozbalení na disk. Cokoli neplatného nebo nebezpečného → `ArchiveError`."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as ex:
        raise ArchiveError(f"Soubor není platný archiv projektu EnvoCAD: {ex}") from None
    with z:
        names = z.namelist()
        for n in names:
            if any(c in n for c in "/\\:"):
                raise ArchiveError(f"Archiv obsahuje nebezpečné jméno souboru {n!r} – nebude se načítat")
        budget = [MAX_TOTAL_BYTES]
        try:
            manifest = _json_member(z, "manifest.json", budget, True)
            if not isinstance(manifest, dict):
                raise ArchiveError("Archiv je poškozen: „manifest.json“ má špatný tvar")
            ver = manifest.get("format")
            if isinstance(ver, bool) or not isinstance(ver, int) or ver < 1:
                raise ArchiveError("Archiv je poškozen: neplatná verze formátu archivu")
            if ver > ARCHIVE_FORMAT:
                raise ArchiveError(f"Archiv je z novější verze programu (formát {ver}) – aktualizujte EnvoCAD")
            project = _json_member(z, "project.ecp", budget, True)
            if not isinstance(project, dict):
                raise ArchiveError("Archiv je poškozen: „project.ecp“ má špatný tvar")
            raw_syms = _json_member(z, "symbols.json", budget, False)
            raw_comps = _json_member(z, "components.json", budget, False)
        except (zipfile.BadZipFile, OSError, RuntimeError, EOFError) as ex:
            raise ArchiveError(f"Archiv je poškozen: {ex}") from None
    if not isinstance(raw_syms, list) or not all(isinstance(s, dict) for s in raw_syms):
        raise ArchiveError("Archiv je poškozen: „symbols.json“ má špatný tvar")
    if not isinstance(raw_comps, list) or not all(isinstance(c, dict) and isinstance(c.get("id"), str)
                                                  for c in raw_comps):
        raise ArchiveError("Archiv je poškozen: „components.json“ má špatný tvar")
    symbols = []
    for k, sd in enumerate(raw_syms):
        try:
            symbols.append(Symbol.from_dict(sd))
        except SymbolVersionError as ex:
            raise ArchiveError(f"Archiv obsahuje značku „{sd.get('id', '?')}“ z novější verze programu – {ex}") from None
        except Exception as ex:  # noqa: BLE001 – cokoli ve vadné značce = poškozený archiv
            raise ArchiveError(f"Archiv je poškozen: značka č. {k + 1} je neplatná ({ex})") from None
    return ProjectArchive(project=project, symbols=symbols, components=raw_comps)


def load_project(archive: ProjectArchive) -> Project:
    """Projekt z archivu (stejná cesta včetně migrace jako `Project.load`); `path` zůstává `None`."""
    return Project.from_dict(archive.project)


# ---- porovnání a import ------------------------------------------------------------------------------------------
def _sym_data(s: Symbol) -> dict:
    """Kanonický tvar značky pro porovnání: `from_dict` doplní povinný atribut `ref` a JSON sjednotí n-tice se
    seznamy, takže značka z archivu a značka uložená v knihovně se porovnají věcně."""
    return json.loads(json.dumps(Symbol.from_dict(s.to_dict()).to_dict()))


def _plan(archive: ProjectArchive, store: LibraryStore) -> tuple[ImportReport, list[Symbol], list[dict]]:
    """Rozdělí položky na nové a konfliktní; vrací i položky, které se smí zapsat (nové + přepsatelné konflikty).
    Přepsatelné konflikty jsou jen uživatelské – vestavěná značka ne."""
    rep = ImportReport()
    syms: list[Symbol] = []
    comps: list[dict] = []
    for s in archive.symbols:
        if not store.has_symbol(s.id):
            rep.new_symbols.append(s.id)
            syms.append(s)
        else:
            try:
                differs = _sym_data(store.get_symbol(s.id)) != _sym_data(s)
            except KeyError:
                # značka v knihovně je z novější verze programu – je to konflikt a nikdy se nepřepíše
                rep.conflict_symbols.append(s.id)
                continue
            if differs:
                rep.conflict_symbols.append(s.id)
                if not store.is_builtin(s.id):
                    syms.append(s)
    for c in archive.components:
        have = store.get_component(c["id"])
        if have is None:
            rep.new_components.append(c["id"])
            comps.append(c)
        elif have != c:
            rep.conflict_components.append(c["id"])
            comps.append(c)
    return rep, syms, comps


def compare_with_library(archive: ProjectArchive, store: LibraryStore) -> ImportReport:
    """Co by import přinesl; nic nezapisuje."""
    return _plan(archive, store)[0]


def import_missing(archive: ProjectArchive, store: LibraryStore, overwrite: bool = False) -> ImportReport:
    """Doplní chybějící značky a artikly. Konflikt (jiný obsah pod stejným id) se bez `overwrite` nepřepíše;
    s ním se přepíšou uživatelské položky, vestavěná značka nikdy (zůstane v `conflict_symbols`)."""
    rep, syms, comps = _plan(archive, store)
    new_s, new_c = set(rep.new_symbols), set(rep.new_components)
    for s in syms:
        if s.id in new_s or overwrite:
            store.put_symbol(s, builtin=False)
    for c in comps:
        if c["id"] in new_c or overwrite:
            store.put_component(c["id"], c.get("manufacturer", ""), c.get("part_number", ""), c.get("name", ""),
                                c.get("symbol_id"), c.get("params") or {}, c.get("price"), c.get("url"))
    if overwrite:
        done_s = {s.id for s in syms}
        rep.conflict_symbols = [i for i in rep.conflict_symbols if i not in done_s]
        rep.conflict_components = []
    log.info("archiv: import – nové značky %s, nové artikly %s, konflikty značek %s, konflikty artiklů %s "
             "(přepis %s)", rep.new_symbols, rep.new_components, rep.conflict_symbols, rep.conflict_components,
             "ano" if overwrite else "ne")
    return rep
