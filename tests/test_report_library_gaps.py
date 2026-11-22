"""Přehled úplnosti dat artiklů (tools/report_library_gaps.py) – testy na malých vymyšlených CSV."""
import csv
import importlib.util
import re
import sys
from pathlib import Path

import pytest

from envocad.library.components import read_csv

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("report_library_gaps", ROOT / "tools" / "report_library_gaps.py")
rep = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rep   # modul obsahuje dataclass
_spec.loader.exec_module(rep)

COLUMNS = ["id", "manufacturer", "part_number", "name", "category", "symbol_id", "datasheet_url", "source",
           "footprint_id", "modules", "width_mm", "height_mm", "depth_mm", "p_loss_w"]
FIELDS = ["modules", "width_mm", "height_mm", "depth_mm", "p_loss_w", "footprint_id"]
FULL = {"modules": "1", "width_mm": "17.5", "height_mm": "90", "depth_mm": "60", "p_loss_w": "2",
        "footprint_id": "din.1"}


def write_components(path: Path, manufacturer: str, rows: list[tuple[str, str, dict]]) -> Path:
    """Zapíše CSV: řádek = (id, kategorie, hodnoty sledovaných polí; chybějící klíče = prázdné)."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
        w.writeheader()
        for cid, category, values in rows:
            row = dict.fromkeys(COLUMNS, "")
            row.update(id=cid, manufacturer=manufacturer, part_number=cid.upper(), name=f"{manufacturer} {cid}",
                       category=category, symbol_id="x.sym", datasheet_url="https://example.invalid", source="user")
            row.update(values)
            w.writerow(row)
    return path


def without(**drop) -> dict:
    """FULL bez uvedených polí."""
    return {k: v for k, v in FULL.items() if k not in drop}


@pytest.fixture
def lib(tmp_path):
    """Dvě CSV (a_first = ACME, b_second = BETA); celkem 12 artiklů, 8 s mezerou."""
    d = tmp_path / "lib"
    d.mkdir()
    write_components(d / "b_second.csv", "BETA", [
        ("b-mccb", "mccb", without(width_mm=None)),                       # má modules, ale mccb chce width_mm
        ("b-term", "terminal", {"width_mm": "5", "depth_mm": "40", "p_loss_w": ""}),   # chybí height_mm
        ("b-encl", "enclosure", {"width_mm": "300", "height_mm": "400"}),   # chybí depth_mm
        ("b-fuse", "fuse", {}),                                           # jen p_loss_w
        ("b-pv", "pv_module", {}),                                        # nehlášeno
        ("b-abc", "mcb", {**FULL, "p_loss_w": "abc"}),                    # nečíselné = chybí
        ("b-zero", "mcb", {**FULL, "p_loss_w": "0"}),                     # 0 = vyplněno
    ])
    write_components(d / "a_first.csv", "ACME", [
        ("a-ok", "mcb", FULL),
        ("a-mcb", "mcb", without(depth_mm=None, p_loss_w=None)),
        ("a-rcd", "rcd", without(modules=None, width_mm=None)),
        ("a-sw", "switch", {**without(modules=None, footprint_id=None)}),
        ("a-inv", "inverter", {}),
    ])
    return d


def by_id(report):
    return {g.id: g for g in report.gaps}


def test_field_rules_order_and_default_dir():
    assert list(rep.FIELD_RULES) == FIELDS
    for categories, where in rep.FIELD_RULES.values():
        assert categories and isinstance(where, str) and where
    assert rep.DEFAULT_DIR.is_dir()


def test_scan_counts_and_order(lib):
    report = rep.scan([lib])
    assert report.total == 12
    assert [g.id for g in report.gaps] == ["a-mcb", "a-rcd", "a-sw", "b-mccb", "b-term", "b-encl", "b-fuse", "b-abc"]
    assert {g.file for g in report.gaps[:3]} == {"a_first.csv"}
    assert {g.file for g in report.gaps[3:]} == {"b_second.csv"}


def test_scan_gap_fields_and_missing_order(lib):
    gaps = by_id(rep.scan([lib]))
    assert gaps["a-mcb"].missing == ("depth_mm", "p_loss_w")
    assert gaps["a-mcb"].manufacturer == "ACME" and gaps["a-mcb"].category == "mcb"
    assert gaps["a-mcb"].part_number == "A-MCB"
    assert gaps["a-rcd"].missing == ("modules", "width_mm")            # DIN bez obojího: hlášeno obojí
    assert gaps["a-sw"].missing == ("footprint_id",)                    # jen width_mm: modules se nehlásí
    assert gaps["b-mccb"].missing == ("width_mm",)                      # mccb: modules width_mm nenahradí
    assert gaps["b-term"].missing == ("height_mm",)
    assert gaps["b-encl"].missing == ("depth_mm",)
    assert gaps["b-fuse"].missing == ("p_loss_w",)
    assert gaps["b-abc"].missing == ("p_loss_w",)


def test_scan_unreported(lib):
    ids = set(by_id(rep.scan([lib])))
    assert not ids & {"a-ok", "a-inv", "b-pv", "b-zero"}                # úplné, jiné kategorie, nula = vyplněno


def test_din_with_only_modules_not_reported(tmp_path):
    f = write_components(tmp_path / "x.csv", "ACME", [("x-1", "mcb", without(width_mm=None))])
    assert rep.scan([f]).gaps == []


def test_missing_fields_on_components(lib):
    comps = {c.id: c for c in read_csv(lib / "a_first.csv")}
    assert rep.missing_fields(comps["a-ok"]) == []
    assert rep.missing_fields(comps["a-rcd"]) == ["modules", "width_mm"]
    assert rep.missing_fields(comps["a-inv"]) == []


def test_scan_files_list_and_directory_equivalent(lib):
    from_dir = rep.scan([lib])
    from_files = rep.scan([lib / "b_second.csv", lib / "a_first.csv"])
    assert from_files.total == from_dir.total == 12
    assert {g.id for g in from_files.gaps} == {g.id for g in from_dir.gaps}
    assert rep.scan([lib / "b_second.csv"]).total == 7
    assert {g.file for g in rep.scan([lib / "b_second.csv"]).gaps} == {"b_second.csv"}


def test_scan_directory_not_recursive(lib):
    sub = lib / "deep"
    sub.mkdir()
    write_components(sub / "c.csv", "GAMMA", [("c-1", "mcb", {})])
    assert rep.scan([lib]).total == 12


def line_with(text: str, needle: str) -> list[str]:
    return [ln for ln in text.splitlines() if needle in ln]


def has_number(lines: list[str], n: int) -> bool:
    return any(re.search(rf"(?<!\d){n}(?!\d)", ln) for ln in lines)


def test_format_report_content(lib):
    text = rep.format_report(rep.scan([lib]))
    for field in rep.FIELD_RULES:
        assert field in text
    assert re.search(r"(?<!\d)12(?!\d)", text) and re.search(r"(?<!\d)8(?!\d)", text)
    assert has_number(line_with(text, "ACME"), 3)         # výrobce
    assert has_number(line_with(text, "BETA"), 5)
    assert has_number(line_with(text, "a_first.csv"), 3)  # soubor
    assert has_number(line_with(text, "b_second.csv"), 5)
    for category, n in (("mcb", 2), ("rcd", 1), ("terminal", 1), ("enclosure", 1), ("fuse", 1)):
        assert has_number(line_with(text, category), n), category


def test_format_report_empty(tmp_path):
    f = write_components(tmp_path / "ok.csv", "ACME", [("ok", "mcb", FULL)])
    report = rep.scan([f])
    assert report.total == 1 and report.gaps == []
    assert isinstance(rep.format_report(report), str)
    assert isinstance(rep.format_report(rep.Report(total=0, gaps=[])), str)


def test_write_csv(lib, tmp_path):
    report = rep.scan([lib])
    out = tmp_path / "out.csv"
    rep.write_csv(report.gaps, out)
    with open(out, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    assert rows[0] == ["file", "id", "manufacturer", "part_number", "category", "missing"]
    assert len(rows) == 1 + len(report.gaps)
    for row, g in zip(rows[1:], report.gaps, strict=True):
        assert row == [g.file, g.id, g.manufacturer, g.part_number, g.category, ",".join(g.missing)]
    assert ["a_first.csv", "a-rcd", "ACME", "A-RCD", "rcd", "modules,width_mm"] in rows


def test_main_csv_and_stdout(lib, tmp_path, capsys):
    out = tmp_path / "gaps.csv"
    assert rep.main([str(lib), "--csv", str(out)]) == 0
    assert out.is_file()
    assert "ACME" in capsys.readouterr().out
    with open(out, encoding="utf-8", newline="") as f:
        assert len(list(csv.reader(f, delimiter=";"))) == 1 + 8


def test_main_without_csv_creates_nothing(lib, capsys):
    before = sorted(p.name for p in lib.parent.iterdir())
    assert rep.main([str(lib)]) == 0
    assert capsys.readouterr().out.strip()
    assert sorted(p.name for p in lib.parent.iterdir()) == before


def test_main_missing_path(tmp_path, capsys):
    assert rep.main([str(tmp_path / "neni.csv")]) == 2
    assert capsys.readouterr().err.strip()


def test_main_does_not_modify_inputs(lib, tmp_path):
    snapshot = {p.name: p.read_bytes() for p in lib.iterdir()}
    rep.main([str(lib), "--csv", str(tmp_path / "out.csv")])
    assert {p.name: p.read_bytes() for p in lib.iterdir()} == snapshot


def test_builtin_library_smoke(capsys):
    assert rep.main([]) == 0
    assert capsys.readouterr().out.strip()
    assert rep.scan([rep.DEFAULT_DIR]).total > 0
