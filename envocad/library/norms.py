"""Načtení lokálních normových tabulek ze složky `~/.envocad/norms/` (`ENVOCAD_HOME/norms`). Bez Qt.

Jeden soubor `*.json` = jeden normový dokument (formát `envocad-norms`, viz `docs/NORMY_FORMAT.md`). Soubory se čtou
seřazené podle jména; vadný soubor se odmítne celý (důvody v `LoadReport` a v logu `envocad.norms`) a výpočty
dál používají tabulky z dosavadního stavu. Definují-li stejnou položku dva soubory, položka zůstane vestavěná
a zapíše se varování. Ověření dokumentu dělá čistá `model.norm_tables.apply_document`."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from envocad.model import norm_tables
from envocad.model.norm_tables import LoadReport, NormTables

log = logging.getLogger("envocad.norms")


def norms_dir() -> Path:
    """Složka s normovými tabulkami (`ENVOCAD_HOME`, jinak `~/.envocad`, + `norms`). Nic nezakládá na disku:
    `store.home_dir()` by dělalo `mkdir`, čistý výpočet nesmí vytvářet složky."""
    base = Path(os.environ.get("ENVOCAD_HOME") or os.path.join(os.path.expanduser("~"), ".envocad"))
    return base / "norms"


MAX_FILE_BYTES = 1024 * 1024        # větší soubor norem se nečte (technická ochrana, ne normová hodnota)


def _read_document(path: Path) -> tuple[object, str, list[str]]:
    """(dokument, sha256 bajtů, chyby čtení)."""
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            return None, "", [f"soubor je větší než {MAX_FILE_BYTES // 1024} kB ({size} B) – nečte se"]
        data = path.read_bytes()
    except OSError as ex:
        return None, "", [f"soubor nelze přečíst: {ex}"]
    sha = hashlib.sha256(data).hexdigest()
    try:
        return json.loads(data.decode("utf-8-sig")), sha, []
    except (UnicodeDecodeError, ValueError, RecursionError) as ex:
        return None, sha, [f"soubor není platný JSON v UTF-8: {ex}"]


def load_dir(path: Path, base: NormTables | None = None) -> tuple[NormTables, LoadReport]:
    """Načte všechny `*.json` ze složky `path` nad tabulkami `base` (výchozí vestavěné). Nikdy nevyhazuje
    výjimku; bez použitelného souboru vrací přímo `base`."""
    base = base if base is not None else norm_tables.BUILTIN
    report = LoadReport()
    try:
        files = sorted((p for p in Path(path).iterdir() if p.suffix.lower() == ".json" and p.is_file()),
                       key=lambda p: p.name) if Path(path).is_dir() else []
    except OSError as ex:
        msg = f"složku norem {str(path)!r} nelze číst: {ex!r}"
        log.warning(msg)
        report.warnings.append(msg)
        return base, report
    tables = base
    conflicted: set[str] = set()
    for f in files:
        doc, sha, errors = _read_document(f)
        warnings: list[str] = []
        new = None
        if not errors:
            new, errors, warnings = norm_tables.apply_document(doc, tables, str(f), sha)
        for w in warnings:
            report.warnings.append(f"{f.name}: {w}")
            log.warning("normy %s: %s", f.name, w)
        if new is None:
            report.files_rejected.append((str(f), errors))
            for e in errors:
                log.warning("normy %s odmítnuty: %s", f.name, e)
            continue
        report.files_used.append(str(f))
        mine = [k for k, s in new.sources.items() if s is not None and s.path == str(f)]
        clash = [k for k in mine if k in conflicted or tables.sources.get(k) is not None]
        if clash:
            conflicted.update(clash)
            new = norm_tables.reset_keys(new, clash, base)
            for k in clash:
                msg = (f"{f.name}: položka {k} je definovaná ve více souborech – použita vestavěná hodnota "
                       f"(ponechte ji jen v jednom souboru)")
                report.warnings.append(msg)
                log.warning("normy %s", msg)
        tables = new
    if report.files_used:
        log.info("normy: použito %d souborů z %s", len(report.files_used), path)
    return tables, report
