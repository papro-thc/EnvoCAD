"""Ceník artiklů (bez Qt): vlastní ceny firmy v `~/.envocad/ceny.csv`, nezávisle na katalogu (vestavěné CSV ceny
nemají a při aktualizaci by je přepsaly). Výkaz materiálu s cenami (`export/reports.priced_bom`) bere cenu
z ceníku, jinak z artiklu (`Component.price`, sloupec `price_czk`).

Formát ceníku (CSV, oddělovač `;` nebo `,`, UTF-8): sloupec `price_czk` (cena za kus / metr bez DPH v Kč) a buď
`id` (artikl katalogu), nebo `manufacturer` + `part_number` (výrobce a typ jako ve výkazu). Řádek bez ceny se
přeskočí; desetinná čárka i mezery v čísle jsou povolené.
"""
from __future__ import annotations

import csv
from pathlib import Path

PRICES_FILE = "ceny.csv"


def _num(v: str) -> float | None:
    try:
        return float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def price_key(manufacturer: str, part_number: str) -> str:
    return f"{(manufacturer or '').strip().lower()}|{(part_number or '').strip().lower()}"


def read_prices(path: Path | str) -> tuple[dict[str, float], list[str]]:
    """Ceník → ({klíč: cena}, chyby česky). Klíč = id artiklu malými písmeny, nebo `price_key(výrobce, typ)`."""
    path = Path(path)
    errors: list[str] = []
    out: dict[str, float] = {}
    if not path.exists():
        return out, errors
    with open(path, encoding="utf-8-sig", newline="") as f:
        head = f.readline()
        f.seek(0)
        reader = csv.DictReader(f, delimiter=";" if head.count(";") >= head.count(",") else ",")
        cols = reader.fieldnames or []
        if "price_czk" not in cols or not ("id" in cols or {"manufacturer", "part_number"} <= set(cols)):
            return out, ["ceník musí mít sloupec price_czk a buď id, nebo manufacturer + part_number"]
        for n, row in enumerate(reader, start=2):
            raw = (row.get("price_czk") or "").strip()
            if not raw:
                continue
            price = _num(raw)
            if price is None or price < 0:
                errors.append(f"řádek {n}: cena „{raw}“ není nezáporné číslo")
                continue
            cid = (row.get("id") or "").strip().lower()
            if cid:
                out[cid] = price
            elif (row.get("part_number") or "").strip():
                out[price_key(row.get("manufacturer", ""), row["part_number"])] = price
            else:
                errors.append(f"řádek {n}: chybí id nebo typ (part_number)")
    return out, errors


class PriceBook:
    """Cena položky výkazu: ceník (id artiklu → výrobce + typ), jinak cena artiklu z katalogu (výrobce + typ)."""

    def __init__(self, lib, prices: dict[str, float] | None = None):
        self.prices = prices or {}
        self.catalog: dict[str, float] = {}
        self.ids: dict[str, str] = {}
        for c in (lib.components() if lib is not None else []):
            k = price_key(c.manufacturer, c.part_number)
            self.ids.setdefault(k, c.id.lower())
            if c.price is not None:
                self.catalog.setdefault(k, c.price)

    def price(self, manufacturer: str, part_number: str) -> float | None:
        if not (part_number or "").strip():
            return None
        k = price_key(manufacturer, part_number)
        cid = self.ids.get(k)
        if cid and cid in self.prices:
            return self.prices[cid]
        if k in self.prices:
            return self.prices[k]
        return self.catalog.get(k)
