"""Přehled artiklů bez provozního rozsahu teplot (`t_min_c` / `t_max_c`) v CSV knihovny (issue #70).

Spustit: python tools/report_missing_temps.py [adresář]

Výchozí adresář je vestavěná knihovna `envocad/library/builtin/components`. Skript jen čte, nic nezapisuje
a vždy končí kódem 0 (je to přehled, ne kontrola CI).
"""

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from envocad.library.components import read_csv, read_header

TEMP_COLUMNS = ("t_min_c", "t_max_c")
DEFAULT_DIR = ROOT / "envocad" / "library" / "builtin" / "components"


@dataclass
class FileReport:
    name: str
    missing_columns: list[str] = field(default_factory=list)
    total: int = 0
    missing: int = 0
    by_manufacturer: dict[str, tuple[int, int]] = field(default_factory=dict)


def scan(directory: Path) -> list[FileReport]:
    """Projde `*.csv` v adresáři (nerekurzivně, podle jména) a spočítá artikly bez teplot."""
    reports = []
    for path in sorted(Path(directory).glob("*.csv")):
        header = read_header(path)
        report = FileReport(name=path.name, missing_columns=[c for c in TEMP_COLUMNS if c not in header])
        counts: dict[str, list[int]] = {}
        for comp in read_csv(path):
            lacks = any(not str(comp.params.get(c, "")).strip() for c in TEMP_COLUMNS)
            m = counts.setdefault(comp.manufacturer, [0, 0])
            m[1] += 1
            report.total += 1
            if lacks:
                m[0] += 1
                report.missing += 1
        report.by_manufacturer = {k: (v[0], v[1]) for k, v in sorted(counts.items())}
        reports.append(report)
    return reports


def _table(header: tuple[str, ...], rows: list[tuple]) -> list[str]:
    cells = [header] + [tuple(str(x) for x in r) for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(header))]

    right = [all(r[i].isdigit() for r in cells[1:]) for i in range(len(header))]

    def line(r):
        return "  ".join(c.rjust(w) if right[i] else c.ljust(w) for i, (c, w) in enumerate(zip(r, widths))).rstrip()

    return [line(cells[0]), "  ".join("-" * w for w in widths)] + [line(r) for r in cells[1:]]


def format_report(reports: list[FileReport]) -> str:
    out = ["Artikly bez provozního rozsahu teplot (t_min_c / t_max_c)", ""]
    rows = []
    for r in reports:
        if r.missing_columns:
            continue   # soubory bez sloupců mají vlastní sekci
        for man, (miss, tot) in r.by_manufacturer.items():
            if miss:
                rows.append((r.name, man, miss, tot))
    if rows:
        out += _table(("Soubor", "Výrobce", "Chybí", "Celkem"), rows)
    else:
        out.append("Žádný artikl nemá chybějící teploty u souborů se sloupci.")
    nocols = [r for r in reports if r.missing_columns]
    if nocols:
        out += ["", "Soubory bez sloupců s teplotami (chybí hodnoty u všech artiklů)", ""]
        out += _table(("Soubor", "Výrobce", "Chybějící sloupce", "Chybí", "Celkem"),
                      [(r.name, man, ", ".join(r.missing_columns), miss, tot)
                       for r in nocols for man, (miss, tot) in (r.by_manufacturer or {"–": (0, 0)}).items()])
    out += ["", f"Celkem: chybí {sum(r.missing for r in reports)} z {sum(r.total for r in reports)} artiklů"]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Přehled artiklů bez provozního rozsahu teplot.")
    ap.add_argument("directory", nargs="?", type=Path, default=DEFAULT_DIR,
                    help="adresář s CSV artikly (výchozí: vestavěná knihovna)")
    args = ap.parse_args(argv)
    reports = scan(args.directory)
    if not reports:   # překlep v cestě nesmí vypadat jako „nic nechybí“
        print(f"Varování: v adresáři {args.directory} nejsou žádné soubory *.csv.", file=sys.stderr)
    print(format_report(reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
