"""Přehled úplnosti dat artiklů: které artikly nemají údaje, které program čte (rozměry, ztráty, obrys v rozložení).

Spuštění z kořene repa (nic nezapisuje, kromě volitelného --csv souboru):

    python tools/report_library_gaps.py                        # celá vestavěná knihovna
    python tools/report_library_gaps.py cesta/a.csv složka/    # jen vybrané soubory / složky (*.csv, nerekurzivně)
    python tools/report_library_gaps.py --csv mezery.csv       # navíc seznam artiklů s mezerou (utf-8, ';')

Na stdout jdou jen souhrny (po kategoriích, výrobcích a souborech); seznam jednotlivých artiklů je v --csv.
Hodnoty se nedoplňují ani neodhadují. Pravidla (pole × kategorie) jsou v `FIELD_RULES`.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    from envocad.library.components import read_csv
except ImportError:   # spuštěno bez `pip install -e`
    sys.path.insert(0, str(ROOT))
    from envocad.library.components import read_csv

DIN = frozenset({"mcb", "rcd", "rcbo", "spd", "switch", "contactor", "fuse_holder", "meter", "relay"})
LAYOUT = DIN | {"mccb", "terminal", "enclosure"}

# pole → (kategorie, u kterých se vyžaduje; kde ho program čte)
FIELD_RULES: dict[str, tuple[frozenset[str], str]] = {
    "modules": (DIN, "model/device_size.py (šířka přístroje v rozložení: moduly artiklu, jinak width_mm)"),
    "width_mm": (LAYOUT, ("model/device_size.py (device_size, is_box, šířka svorky); skříň ui/dialogs.py "
                          "(rozměry skříně z artiklu do rozložení)")),
    "height_mm": (LAYOUT, ("model/device_size.py (size_problems – výška vs. rozteč řad); skříň → parametry "
                           "rozložení / oteplení")),
    "depth_mm": (LAYOUT, ("model/device_size.py (size_problems – hloubka vs. skříň); skříň → parametry "
                          "rozložení / oteplení")),
    "p_loss_w": (frozenset({"mcb", "mccb", "rcd", "rcbo", "fuse", "fuse_holder", "spd"}),
                 "model/thermal.py (ΣPv; bez údaje odhad z In)"),
    "footprint_id": (DIN | {"mccb"}, "ui/layout_view.py (kresba přístroje v rozložení; bez něj generický tvar)"),
}
DEFAULT_DIR = ROOT / "envocad" / "library" / "builtin" / "components"
CSV_HEADER = ["file", "id", "manufacturer", "part_number", "category", "missing"]
TABLES = (("category", "Po kategoriích"), ("manufacturer", "Po výrobcích"), ("file", "Po souborech"))


@dataclass(frozen=True)
class Gap:
    file: str
    id: str
    manufacturer: str
    part_number: str
    category: str
    missing: tuple[str, ...]


@dataclass
class Report:
    total: int
    gaps: list[Gap] = field(default_factory=list)


def _is_empty(comp, name: str) -> bool:
    if name == "footprint_id":
        return not (comp.footprint_id or "").strip()
    return comp.num(name) is None


def missing_fields(comp) -> list[str]:
    """Sledovaná pole, která artikl dané kategorie nemá vyplněná (v pořadí `FIELD_RULES`)."""
    out = []
    for name, (categories, _where) in FIELD_RULES.items():
        if comp.category not in categories or not _is_empty(comp, name):
            continue
        # výjimka: u DIN přístroje stačí `modules` nebo `width_mm`; hlásí se jen, když chybí obojí
        if comp.category in DIN and name in ("modules", "width_mm"):
            other = "width_mm" if name == "modules" else "modules"
            if not _is_empty(comp, other):
                continue
        out.append(name)
    return out


def _csv_files(paths: Iterable[Path | str]) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        files.extend(sorted(p.glob("*.csv"), key=lambda f: f.name) if p.is_dir() else [p])
    return files


def scan(paths: Iterable[Path | str]) -> Report:
    """Načte artikly ze souborů .csv / složek a vrátí počet všech a seznam těch s mezerou."""
    paths = list(paths)
    files = sorted(_csv_files(paths), key=lambda f: f.name)
    report = Report(total=0)
    for f in files:
        for comp in read_csv(f):
            report.total += 1
            missing = missing_fields(comp)
            if missing:
                report.gaps.append(Gap(f.name, comp.id, comp.manufacturer, comp.part_number, comp.category,
                                       tuple(missing)))
    return report


def _table(title: str, gaps: list[Gap], key: str) -> list[str]:
    rows: dict[str, list[Gap]] = {}
    for g in gaps:
        rows.setdefault(getattr(g, key), []).append(g)
    fields = list(FIELD_RULES)
    data = []
    for name, items in rows.items():
        counts = Counter(m for g in items for m in g.missing)
        data.append((name or "(prázdné)", len(items), [counts[f] for f in fields]))
    data.sort(key=lambda r: (-r[1], r[0]))
    width = max([len(r[0]) for r in data] + [len(title)])
    head = [title.ljust(width), "artiklů".rjust(7)] + [f.rjust(max(len(f), 3)) for f in fields]
    lines = ["  ".join(head), "  ".join("-" * len(h) for h in head)]
    for name, n, cnts in data:
        cells = [name.ljust(width), str(n).rjust(7)] + [str(c).rjust(max(len(f), 3)) for c, f in zip(cnts, fields)]
        lines.append("  ".join(cells))
    return lines


def format_report(report: Report) -> str:
    lines = ["Sledovaná pole artiklů (kategorie → kde je program čte):"]
    for name, (categories, where) in FIELD_RULES.items():
        lines.append(f"  {name}: {', '.join(sorted(categories))}")
        lines.append(f"      čte: {where}")
    lines.append("  Poznámka: u DIN přístrojů stačí `modules` nebo `width_mm`; hlásí se jen, když chybí obojí.")
    lines += ["", f"Artiklů celkem: {report.total}, s chybějícím údajem: {len(report.gaps)}"]
    if not report.gaps:
        lines += ["", "Žádné mezery."]
        return "\n".join(lines)
    for key, title in TABLES:
        lines += ["", *_table(title, report.gaps, key)]
    return "\n".join(lines)


def write_csv(gaps: Iterable[Gap], path: Path | str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(CSV_HEADER)
        for g in gaps:
            w.writerow([g.file, g.id, g.manufacturer, g.part_number, g.category, ",".join(g.missing)])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Přehled úplnosti dat artiklů (rozměry, ztráty, obrys).")
    ap.add_argument("paths", nargs="*", help=f"soubory .csv / složky (výchozí {DEFAULT_DIR})")
    ap.add_argument("--csv", metavar="OUT", help="zapíše seznam artiklů s mezerou do CSV (utf-8, ';')")
    args = ap.parse_args(argv)
    paths = [Path(p) for p in args.paths] or [DEFAULT_DIR]
    for p in paths:
        if not p.exists():
            print(f"Cesta neexistuje: {p}", file=sys.stderr)
            return 2
    report = scan(paths)
    print(format_report(report))
    print()
    if args.csv:
        write_csv(report.gaps, args.csv)
        print(f"Seznam zapsán do {args.csv} ({len(report.gaps)} řádků)")
    else:
        print("Tip: seznam jednotlivých artiklů zapíše volba --csv OUT.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
