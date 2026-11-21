"""Pojistka proti licencovaným datům výrobců v gitu (tools/check_licensed_data.py)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_licensed_data", ROOT / "tools" / "check_licensed_data.py")
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def test_repo_is_clean(monkeypatch):
    monkeypatch.chdir(ROOT)
    assert check.problems(check.tracked_files()) == []


def test_forbidden_suffix_and_dirs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    found = check.problems(["a/OEZ-katalog.pdf", "x.EDZ", "EPLAN/parts.csv", "lib/datasheets/x.txt", "ok.py"])
    assert len(found) == 4
    assert not any(f.startswith("ok.py") for f in found)


def test_eplan_marker_in_library_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "envocad" / "library" / "builtin" / "components" / "deep"
    data.mkdir(parents=True)
    (data / "x.csv").write_text("P_ARTICLE_PARTNR;P_ARTICLE_MANUFACTURER\n1;OEZ\n", encoding="utf-8")
    (data / "ok.csv").write_text("id;manufacturer\noez-1;OEZ\n", encoding="utf-8")
    found = check.problems(["envocad/library/builtin/components/deep/x.csv",
                            "envocad/library/builtin/components/deep/ok.csv"])
    assert len(found) == 1 and "x.csv" in found[0]


def test_oversized_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "big.bin").write_bytes(b"0" * (check.MAX_BYTES + 1))
    assert check.problems(["big.bin"])
