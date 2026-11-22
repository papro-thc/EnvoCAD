"""Přehled artiklů bez provozní teploty (tools/report_missing_temps.py, issue #70)."""
import importlib.util
from pathlib import Path

import pytest

from envocad.library.components import read_csv

ROOT = Path(__file__).resolve().parents[1]
BUILTIN = ROOT / "envocad" / "library" / "builtin" / "components"
_spec = importlib.util.spec_from_file_location("report_missing_temps", ROOT / "tools" / "report_missing_temps.py")
rep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rep)

BASE = ["id", "manufacturer", "part_number", "name", "category", "symbol_id", "datasheet_url", "source"]


def _write(path: Path, header: list[str], rows: list[dict], delim: str = ";") -> Path:
    lines = [delim.join(header)]
    for r in rows:
        lines.append(delim.join(str(r.get(c, "")) for c in header))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _row(i: str, man: str, tmin: str | None = None, tmax: str | None = None) -> dict:
    d = {"id": i, "manufacturer": man, "part_number": i.upper(), "name": i, "category": "x",
         "symbol_id": "s", "datasheet_url": "u", "source": "web"}
    if tmin is not None:
        d["t_min_c"] = tmin
    if tmax is not None:
        d["t_max_c"] = tmax
    return d


def _by_name(reports):
    return {r.name: r for r in reports}


def test_counts_per_manufacturer(tmp_path):
    rows = [
        _row("a1", "ABB", "-25", "60"),        # kompletní
        _row("a2", "ABB", "", ""),             # chybí obojí
        _row("a3", "ABB", "-25", ""),          # chybí jen t_max
        _row("b1", "Siemens", "-40", "70"),    # kompletní
        _row("b2", "Siemens", "  ", "70"),     # jen bílé znaky = chybí
        _row("c1", "OEZ", "-5", "40"),         # kompletní
    ]
    _write(tmp_path / "full.csv", BASE + ["t_min_c", "t_max_c"], rows)
    reports = rep.scan(tmp_path)
    assert len(reports) == 1
    r = reports[0]
    assert r.name == "full.csv"
    assert r.missing_columns == []
    assert r.total == 6
    assert r.missing == 3
    assert r.by_manufacturer == {"ABB": (2, 3), "Siemens": (1, 2), "OEZ": (0, 1)}


def test_only_t_min_column_present(tmp_path):
    _write(tmp_path / "half.csv", BASE + ["t_min_c"], [_row("a", "ABB", "-25"), _row("b", "ABB", "")])
    r = rep.scan(tmp_path)[0]
    assert r.missing_columns == ["t_max_c"]
    assert r.total == 2
    assert r.missing == 2  # bez t_max_c chybí hodnota u všech


def test_file_without_columns(tmp_path):
    _write(tmp_path / "nocols.csv", BASE, [_row("a", "ABB"), _row("b", "ABB"), _row("c", "Eaton")])
    r = rep.scan(tmp_path)[0]
    assert r.missing_columns == ["t_min_c", "t_max_c"]
    assert r.total == 3
    assert r.missing == r.total
    assert r.by_manufacturer == {"ABB": (2, 2), "Eaton": (1, 1)}


def test_complete_file(tmp_path):
    _write(tmp_path / "ok.csv", BASE + ["t_min_c", "t_max_c"],
           [_row("a", "ABB", "-25", "60"), _row("b", "Eaton", "-5", "40")])
    r = rep.scan(tmp_path)[0]
    assert r.missing_columns == []
    assert r.missing == 0
    assert r.total == 2
    assert all(m == 0 for m, _ in r.by_manufacturer.values())


def test_comma_delimiter_and_rows_without_id(tmp_path):
    rows = [_row("a", "ABB", "-25", ""), _row("", "ABB", "", ""), _row("b", "ABB", "-25", "60")]
    _write(tmp_path / "comma.csv", BASE + ["t_min_c", "t_max_c"], rows, delim=",")
    r = rep.scan(tmp_path)[0]
    assert r.total == 2  # řádek bez id se nepočítá
    assert r.missing == 1


def test_scan_sorted_and_not_recursive(tmp_path):
    for n in ("b.csv", "a.csv", "c.csv"):
        _write(tmp_path / n, BASE, [_row("x", "ABB")])
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    _write(sub / "deep.csv", BASE, [_row("x", "ABB")])
    assert [r.name for r in rep.scan(tmp_path)] == ["a.csv", "b.csv", "c.csv"]


def test_scan_empty_directory(tmp_path):
    assert rep.scan(tmp_path) == []


def test_format_report_sections(tmp_path):
    _write(tmp_path / "with_cols.csv", BASE + ["t_min_c", "t_max_c"],
           [_row("a", "Mfr_Alpha", "", ""), _row("b", "Mfr_Alpha", "-5", "40"), _row("c", "Mfr_Beta", "-5", "40")])
    _write(tmp_path / "no_cols.csv", BASE, [_row("x", "Mfr_Gamma"), _row("y", "Mfr_Gamma")])
    text = rep.format_report(rep.scan(tmp_path))
    assert isinstance(text, str)
    assert "with_cols.csv" in text
    assert "Mfr_Alpha" in text
    assert "Mfr_Gamma" in text
    marker = text.lower().find("bez sloupc")
    assert marker != -1, "chybí sekce souborů bez sloupců"
    before, after = text[:marker], text[marker:]
    # soubor bez sloupců je jen ve zvláštní sekci, soubor se sloupci jen před ní
    assert "no_cols.csv" in after
    assert "no_cols.csv" not in before
    assert "with_cols.csv" in before
    assert "with_cols.csv" not in after
    assert "Mfr_Alpha" in before
    # řádek s výrobcem a čísly (chybí 1 z 2)
    alpha_line = next(ln for ln in before.splitlines() if "Mfr_Alpha" in ln)
    assert "1" in alpha_line and "2" in alpha_line


def test_format_report_complete_file_has_no_missing_manufacturer_row(tmp_path):
    _write(tmp_path / "ok.csv", BASE + ["t_min_c", "t_max_c"], [_row("a", "Mfr_Done", "-5", "40")])
    text = rep.format_report(rep.scan(tmp_path))
    assert "Mfr_Done" not in text


def test_format_report_total_line(tmp_path):
    _write(tmp_path / "a.csv", BASE, [_row("x", "ABB"), _row("y", "ABB"), _row("z", "ABB")])
    _write(tmp_path / "b.csv", BASE + ["t_min_c", "t_max_c"], [_row("q", "ABB", "", ""), _row("r", "ABB", "1", "2")])
    text = rep.format_report(rep.scan(tmp_path))
    assert "celkem" in text.lower()
    total_line = next(ln for ln in text.splitlines() if "celkem" in ln.lower() and "4" in ln and "5" in ln)
    assert total_line


def test_main_returns_zero_prints_and_does_not_modify(tmp_path, capsys):
    p1 = _write(tmp_path / "a.csv", BASE + ["t_min_c", "t_max_c"], [_row("a", "Mfr_Alpha", "", "")])
    p2 = _write(tmp_path / "b.csv", BASE, [_row("b", "Mfr_Gamma")])
    before = {p: p.read_bytes() for p in (p1, p2)}
    names_before = sorted(x.name for x in tmp_path.iterdir())
    assert rep.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "a.csv" in out and "b.csv" in out and "Mfr_Alpha" in out
    assert {p: p.read_bytes() for p in before} == before
    assert sorted(x.name for x in tmp_path.iterdir()) == names_before


def test_main_empty_directory_returns_zero(tmp_path, capsys):
    assert rep.main([str(tmp_path)]) == 0
    capsys.readouterr()


def test_main_default_builtin_library(capsys):
    assert rep.main([]) == 0
    assert capsys.readouterr().out.strip()


@pytest.mark.skipif(not BUILTIN.is_dir(), reason="vestavěná knihovna chybí")
def test_scan_builtin_totals_match_read_csv():
    reports = rep.scan(BUILTIN)
    paths = sorted(BUILTIN.glob("*.csv"))
    assert [r.name for r in reports] == [p.name for p in paths]
    assert sum(r.total for r in reports) == sum(len(read_csv(p)) for p in paths)
    for r in reports:
        assert 0 <= r.missing <= r.total
        assert sum(t for _, t in r.by_manufacturer.values()) == r.total
        assert sum(m for m, _ in r.by_manufacturer.values()) == r.missing


def test_missing_directory_warns_on_stderr(tmp_path, capsys):
    assert rep.main([str(tmp_path / "neexistuje")]) == 0
    captured = capsys.readouterr()
    assert "Celkem: chybí 0 z 0" in captured.out
    assert "*.csv" in captured.err


def test_header_only_file_without_columns_is_listed(tmp_path):
    (tmp_path / "prazdny.csv").write_text("id;manufacturer;part_number;name\n", encoding="utf-8")
    out = rep.format_report(rep.scan(tmp_path))
    assert "prazdny.csv" in out.split("bez sloupc", 1)[1]
