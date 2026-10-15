"""Artikly (komponenty): formát CSV v2, validace, propsání parametrů do prvku. Bez Qt.

CLI:
    python -m envocad.library.components validate soubor.csv [--symbols]
    python -m envocad.library.components stats soubor.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from envocad.model.project import Element

REQUIRED = ["id", "manufacturer", "part_number", "name", "category", "symbol_id", "datasheet_url", "source"]
CATEGORIES = {"mcb", "mccb", "rcd", "rcbo", "spd", "switch", "contactor", "fuse", "fuse_holder", "meter", "inverter",
              "inverter_hybrid", "battery", "pv_module", "enclosure", "terminal", "relay", "accessory", "connector",
              "cable", "other"}
NUMERIC = {"price_czk", "in_", "poles", "icu_ka", "idn_ma", "un_v", "modules", "width_mm", "height_mm", "depth_mm",
           "p_loss_w", "p_ac_kw", "p_dc_max_kwp", "mppt", "phases", "i_ac_max_a", "e_kwh", "p_kw", "u_dc_v", "p_wp",
           "voc_v", "isc_a", "vmp_v", "imp_a", "uc_v", "up_kv", "iimp_ka", "in_ka", "rows", "modules_per_row",
           "cross_mm2", "cross_max_mm2", "levels", "cores_n", "od_mm"}
SOURCES = {"catalog", "datasheet", "web", "seed", "user"}

# výchozí schematická značka podle kategorie (když symbol_id chybí)
DEFAULT_SYMBOL = {
    "mcb": "fve.breaker_mcb", "mccb": "fve.breaker_mccb", "rcd": "sb.rcd", "rcbo": "sb.rcbo", "spd": "fve.spd",
    "switch": "fve.switch_disconnector", "contactor": "fve.contactor", "fuse": "fve.fuse", "fuse_holder": "fve.fuse",
    "meter": "fve.meter", "inverter": "fve.inverter", "inverter_hybrid": "fve.inverter_hybrid",
    "battery": "fve.battery", "pv_module": "fve.pv_string", "terminal": "sb.terminal_block",
}

# artikl.param → atribut prvku
PARAM_TO_ATTR = {
    "part_number": "type", "manufacturer": "manufacturer", "in_": "in_", "poles": "poles", "char": "char",
    "icu_ka": "icu", "idn_ma": "idn", "modules": "modules", "p_loss_w": "p_loss_w", "spd_type": "spd_type",
    "uc_v": "uc", "p_ac_kw": "p_ac", "p_dc_max_kwp": "p_dc_max", "mppt": "mppt", "phases": "phases",
    "e_kwh": "e_kwh", "p_kw": "p_kw", "un_v": "un", "p_wp": "p_module", "voc_v": "voc", "isc_a": "isc",
    "cross_mm2": "cross", "terminal_kind": "kind",
}


@dataclass
class Component:
    id: str
    manufacturer: str
    part_number: str
    name: str
    category: str
    symbol_id: str
    datasheet_url: str = ""
    source: str = "user"
    footprint_id: str = ""
    params: dict[str, str] = field(default_factory=dict)
    price: float | None = None

    @property
    def label(self) -> str:
        return f"{self.manufacturer} {self.part_number} – {self.name}"

    def num(self, key: str) -> float | None:
        v = self.params.get(key)
        if v in (None, ""):
            return None
        try:
            return float(str(v).replace(",", "."))
        except ValueError:
            return None

    def apply_to(self, e: Element) -> dict[str, str]:
        """Propíše parametry do atributů prvku; vrátí změněné atributy (klíč → nová hodnota)."""
        changed: dict[str, str] = {}
        src = {"part_number": self.part_number, "manufacturer": self.manufacturer, **self.params}
        for pkey, akey in PARAM_TO_ATTR.items():
            v = src.get(pkey)
            if v in (None, ""):
                continue
            v = str(v)
            if e.attrs.get(akey) != v:
                changed[akey] = v
        e.attrs.update(changed)
        e.component_id = self.id
        return changed

    @classmethod
    def from_row(cls, row: dict[str, str]) -> Component:
        fixed = {"id", "manufacturer", "part_number", "name", "category", "symbol_id", "datasheet_url", "source",
                 "footprint_id", "price_czk"}
        params = {k: v.strip() for k, v in row.items() if k and k not in fixed and v and v.strip()}
        price = None
        if row.get("price_czk"):
            try:
                price = float(row["price_czk"].replace(",", ".").replace(" ", ""))
            except ValueError:
                price = None
        cat = (row.get("category") or "other").strip()
        return cls(
            id=row["id"].strip(), manufacturer=row.get("manufacturer", "").strip(),
            part_number=row.get("part_number", "").strip(), name=row.get("name", "").strip(), category=cat,
            symbol_id=(row.get("symbol_id") or DEFAULT_SYMBOL.get(cat, "")).strip(),
            datasheet_url=row.get("datasheet_url", "").strip(), source=(row.get("source") or "user").strip(),
            footprint_id=(row.get("footprint_id") or "").strip(), params=params, price=price,
        )

    def to_db_row(self) -> dict:
        return {"id": self.id, "manufacturer": self.manufacturer, "part_number": self.part_number, "name": self.name,
                "symbol_id": self.symbol_id or None, "params": {**self.params, "category": self.category,
                                                                "datasheet_url": self.datasheet_url, "source": self.source,
                                                                "footprint_id": self.footprint_id},
                "price": self.price, "url": self.datasheet_url}

    @classmethod
    def from_db_row(cls, d: dict) -> Component:
        params = dict(d.get("params") or {})
        return cls(id=d["id"], manufacturer=d.get("manufacturer", ""), part_number=d.get("part_number", ""),
                   name=d.get("name", ""), category=params.pop("category", "other"), symbol_id=d.get("symbol_id") or "",
                   datasheet_url=params.pop("datasheet_url", "") or (d.get("url") or ""),
                   source=params.pop("source", "user"), footprint_id=params.pop("footprint_id", ""),
                   params=params, price=d.get("price"))


def read_csv(path: Path | str) -> list[Component]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        head = f.readline()
        delim = ";" if head.count(";") >= head.count(",") else ","
        f.seek(0)
        return [Component.from_row(r) for r in csv.DictReader(f, delimiter=delim) if r.get("id", "").strip()]


def validate(path: Path | str, known_symbols: set[str] | None = None) -> list[str]:
    """Vrátí seznam chyb (prázdný = OK)."""
    errors: list[str] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        head = f.readline()
        delim = ";" if head.count(";") >= head.count(",") else ","
        f.seek(0)
        reader = csv.DictReader(f, delimiter=delim)
        cols = reader.fieldnames or []
        missing = [c for c in REQUIRED if c not in cols]
        if missing:
            errors.append(f"chybí sloupce: {', '.join(missing)}")
            return errors
        ids: set[str] = set()
        for n, row in enumerate(reader, start=2):
            rid = (row.get("id") or "").strip()
            if not rid:
                continue
            if not re.fullmatch(r"[a-z0-9][a-z0-9._+-]*", rid):
                errors.append(f"řádek {n}: id '{rid}' – jen malá písmena, čísla, . _ + -")
            if rid in ids:
                errors.append(f"řádek {n}: duplicitní id '{rid}'")
            ids.add(rid)
            for c in ("manufacturer", "part_number", "name"):
                if not (row.get(c) or "").strip():
                    errors.append(f"řádek {n} ({rid}): prázdné '{c}'")
            cat = (row.get("category") or "").strip()
            if cat not in CATEGORIES:
                errors.append(f"řádek {n} ({rid}): neznámá kategorie '{cat}'")
            src = (row.get("source") or "").strip()
            if src not in SOURCES:
                errors.append(f"řádek {n} ({rid}): source musí být jedno z {sorted(SOURCES)}")
            if src in ("catalog", "datasheet", "web") and not (row.get("datasheet_url") or "").startswith("http"):
                errors.append(f"řádek {n} ({rid}): datasheet_url musí být http(s) odkaz")
            sym = (row.get("symbol_id") or "").strip()
            if known_symbols is not None and sym and sym not in known_symbols:
                errors.append(f"řádek {n} ({rid}): neznámý symbol_id '{sym}'")
            for c in NUMERIC:
                v = (row.get(c) or "").strip()
                if v and not re.fullmatch(r"-?\d+([.,]\d+)?", v):
                    errors.append(f"řádek {n} ({rid}): '{c}' musí být číslo, je '{v}'")
    return errors


def stats(path: Path | str) -> dict[str, float]:
    comps = read_csv(path)
    if not comps:
        return {"count": 0}
    keys = sorted({k for c in comps for k in c.params})
    out = {"count": len(comps)}
    for k in keys:
        out[k] = round(100 * sum(1 for c in comps if c.params.get(k)) / len(comps))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["validate", "stats"])
    ap.add_argument("csv")
    ap.add_argument("--symbols", action="store_true", help="ověřit symbol_id proti knihovně")
    a = ap.parse_args(argv)
    if a.cmd == "validate":
        known = None
        if a.symbols:
            from envocad.library.store import LibraryStore
            known = {s[0] for s in LibraryStore(load_builtin=True).list_symbols()}
        errs = validate(a.csv, known)
        print("\n".join(errs) if errs else "OK")
        return 1 if errs else 0
    for k, v in stats(a.csv).items():
        unit = "" if k == "count" else " %"
        print(f"{k}: {v}{unit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
