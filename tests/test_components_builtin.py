"""Konzistence vestavěných CSV artiklů (bez Qt)."""

from collections import Counter

from envocad.library import components
from envocad.library.store import BUILTIN_DIR

CSV_DIR = BUILTIN_DIR / "components"


def _all_rows():
    rows = []
    for f in sorted(CSV_DIR.glob("*.csv")):
        rows += [(f.name, c) for c in components.read_csv(f)]
    return rows


def test_builtin_csvs_validate():
    symbols = {p.stem for p in BUILTIN_DIR.rglob("*.json")}
    for f in sorted(CSV_DIR.glob("*.csv")):
        errs = components.validate(f, symbols)
        assert not errs, f"{f.name}: {errs[:3]}"


def test_no_duplicate_ids_across_builtin_files():
    counts = Counter(c.id for _, c in _all_rows())
    dups = sorted(i for i, n in counts.items() if n > 1)
    assert not dups, f"duplicitní id (pozdější soubor by přepsal dřívější): {dups}"


def test_library_size():
    assert len(_all_rows()) >= 450
