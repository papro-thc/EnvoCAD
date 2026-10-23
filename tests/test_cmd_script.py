"""Skripty `.ecs` a CLI `python -m envocad.cmd` (subprocess): čísla řádků chyb, proměnné, vnoření, ukládání jen
s `-o` / `--in-place`, `--dry-run`, `--json`, `--keep-going`, kódy návratu; žádné spouštění kódu ze skriptu."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from envocad.cmd import CommandRunner, Journal, run_script, run_script_file
from envocad.cmd.script import MAX_DEPTH, script_lines
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _project() -> Project:
    p = Project(name="Skript")
    p.sheets[0].elements += [Element("fve.breaker_mcb", 50.0, 100.0, attrs={"ref": "F1"}),
                             Element("fve.breaker_mcb", 100.0, 100.0, attrs={"ref": "F2"})]
    return p


def test_script_lines_skip_comments_and_blank():
    text = "# hlavička\n\nINSERT a 1,1\n   # odsazený komentář\n  RO F1  \n"
    assert list(script_lines(text)) == [(3, "INSERT a 1,1"), (5, "RO F1")]


def test_run_script_line_numbers_and_stop(lib):
    p = _project()
    r = CommandRunner(p, lib, journal=Journal())
    rep = run_script(r, "# test\nRO F1\n\nMOVE F1 0,0\nRO F2\n")
    assert not rep.ok and rep.count == 2
    assert rep.first_error == "řádek 4: MOVE – chybí Cílový bod"
    assert p.sheets[0].elements[1].rotation == 0             # za chybou se nepokračuje
    rep = run_script(r, "MOVE F1 0,0\nRO F2\n", stop_on_error=False)
    assert rep.count == 2 and rep.errors == ["řádek 1: MOVE – chybí Cílový bod"]
    assert p.sheets[0].elements[1].rotation == 90


def test_variables(lib):
    p = _project()
    r = CommandRunner(p, lib)
    rep = run_script(r, "SET F1 ref=${R} desc=\"${D}\"\nSET F2 ref=${X}\n", variables={"R": "Q7", "D": "a b"})
    assert p.sheets[0].elements[0].attrs["ref"] == "Q7" and p.sheets[0].elements[0].attrs["desc"] == "a b"
    assert rep.first_error == "řádek 2: neznámá proměnná ${X}"


def test_nested_scripts_relative_and_depth(lib, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "inner.ecs").write_text("RO F1\n", encoding="utf-8")
    (tmp_path / "main.ecs").write_text("SCRIPT sub/inner.ecs\nSCR sub/inner.ecs\n", encoding="utf-8")
    p = _project()
    r = CommandRunner(p, lib, journal=Journal())
    rep = run_script_file(r, tmp_path / "main.ecs")
    assert rep.ok and p.sheets[0].elements[0].rotation == 180
    assert len(r.journal.done) == 2                          # každý vnořený řádek je vlastní krok
    (tmp_path / "loop.ecs").write_text("RO F2\nSCRIPT loop.ecs\n", encoding="utf-8")
    rep = run_script_file(r, tmp_path / "loop.ecs")
    assert not rep.ok and f"nejvýš {MAX_DEPTH}" in rep.first_error
    assert r.script_depth == 0 and r.ctx.base_dir is None
    rep = run_script(r, "SCRIPT neni.ecs\n", base_dir=tmp_path)
    assert "nelze načíst" in rep.first_error
    (tmp_path / "tajne.txt").write_text("HESLO123\n", encoding="utf-8")
    rep = run_script(r, "SCRIPT tajne.txt\n", base_dir=tmp_path)    # jen .ecs – obsah jiného souboru neprosákne
    assert "čekám soubor .ecs" in rep.first_error and "HESLO" not in json.dumps([x.to_json() for x in rep.lines], ensure_ascii=False)


# ---- CLI ---------------------------------------------------------------------------------------------------------
def _cli(*args, stdin: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    env.pop("QT_QPA_PLATFORM", None)
    return subprocess.run([sys.executable, "-m", "envocad.cmd", *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", input=stdin, cwd=ROOT, env=env, timeout=300, check=False)


@pytest.fixture
def files(tmp_path):
    proj = tmp_path / "projekt.ecp"
    _project().save(proj)
    (tmp_path / "ok.ecs").write_text(
        "# vložit jistič a otočit\nINSERT fve.breaker_mcb 150,100 ref=F3\nRO F3\nWIRE F1:2 F2:1\nF7\n",
        encoding="utf-8")
    (tmp_path / "bad.ecs").write_text("RO F1\nMOVE F1 0,0\nRO F2\n", encoding="utf-8")
    return tmp_path, proj


def _load(path: Path) -> Project:
    return Project.load(path)


def test_cli_without_output_saves_nothing(files):
    d, proj = files
    before = proj.read_bytes()
    r = _cli(proj, d / "ok.ecs")
    assert r.returncode == 0, r.stderr
    assert "Vloženo F3" in r.stdout and "Neuloženo" in r.stdout and "Kontrola F7" in r.stdout
    assert proj.read_bytes() == before and not (d / "projekt.ecp.bak").exists()


def test_cli_output_in_place_and_dry_run(files):
    d, proj = files
    before = proj.read_bytes()
    r = _cli(proj, d / "ok.ecs", "-o", d / "out.ecp", "--dry-run")
    assert r.returncode == 0 and not (d / "out.ecp").exists() and "dry-run" in r.stdout
    r = _cli(proj, d / "ok.ecs", "-o", d / "out.ecp")
    assert r.returncode == 0, r.stderr
    out = _load(d / "out.ecp")
    f3 = next(e for e in out.sheets[0].elements if e.ref == "F3")
    assert f3.rotation == 90 and len(out.sheets[0].wires) == 1 and proj.read_bytes() == before
    assert any(c.ref == "W1" for c in out.cables)            # odvozená data před uložením (sync_cables)
    r = _cli(proj, d / "ok.ecs", "--in-place")
    assert r.returncode == 0 and (d / "projekt.ecp.bak").exists()
    assert any(e.ref == "F3" for e in _load(proj).sheets[0].elements)
    assert _cli(proj, d / "ok.ecs", "--in-place", "-o", d / "x.ecp").returncode == 2


def test_cli_error_line_number_no_save_and_keep_going(files):
    d, proj = files
    r = _cli(proj, d / "bad.ecs", "-o", d / "out.ecp")
    assert r.returncode == 1 and "řádek 2: MOVE – chybí Cílový bod" in r.stderr
    assert not (d / "out.ecp").exists()
    r = _cli(proj, d / "bad.ecs", "-o", d / "out.ecp", "--keep-going")
    assert r.returncode == 1 and (d / "out.ecp").exists()
    assert [e.rotation for e in _load(d / "out.ecp").sheets[0].elements] == [90, 90]


def test_cli_json_lines(files):
    d, proj = files
    r = _cli(proj, d / "bad.ecs", "--json", "--keep-going")
    rows = [json.loads(x) for x in r.stdout.splitlines()]
    assert r.returncode == 1 and len(rows) == 4
    for row, line in zip(rows[:3], (1, 2, 3), strict=True):
        assert set(row) == {"line", "cmd", "ok", "messages", "changed_sheets"} and row["line"] == line
    assert [x["ok"] for x in rows[:3]] == [True, False, True] and rows[1]["cmd"] == "move"
    assert rows[0]["changed_sheets"] == [_load(proj).sheets[0].id] and rows[1]["changed_sheets"] == []
    s = rows[3]["summary"]
    assert s["ok"] is False and s["commands"] == 3 and s["saved"] is None and s["errors"]
    r = _cli(proj, "-", "--json", stdin="F7\n")
    rows = [json.loads(x) for x in r.stdout.splitlines()]
    assert r.returncode == 0 and rows[0]["cmd"] == "checks" and isinstance(rows[0]["data"], list)


def test_cli_vars_stdin_and_no_code_execution(files):
    d, proj = files
    marker = d / "hacked"
    script = (f"__import__('os').system('touch {marker}')\n"
              f"SET F1 \"desc=$(touch {marker})\"\nSET F2 ref=${{R}}\n")
    r = _cli(proj, "-", "-o", d / "o.ecp", "--keep-going", "--var", "R=Q5", stdin=script)
    assert r.returncode == 1 and "Neznámý příkaz" in r.stderr and not marker.exists()
    out = _load(d / "o.ecp")
    assert out.sheets[0].elements[0].attrs["desc"] == f"$(touch {marker})"     # jen text
    assert out.sheets[0].elements[1].ref == "Q5"


def test_cli_usage_errors(files, tmp_path):
    d, proj = files
    assert _cli().returncode == 2
    assert _cli(tmp_path / "neni.ecp", d / "ok.ecs").returncode == 2
    assert _cli(proj, tmp_path / "neni.ecs").returncode == 2
    assert _cli(proj, d / "ok.ecs", "--var", "spatne").returncode == 2
    (tmp_path / "rozbity.ecp").write_text("{", encoding="utf-8")
    r = _cli(tmp_path / "rozbity.ecp", d / "ok.ecs")
    assert r.returncode == 2 and "nelze otevřít" in r.stderr


def test_cli_main_in_process(files, capsys):
    """`main()` jde volat i bez podprocesu (agent v Pythonu)."""
    from envocad.cmd.__main__ import main
    d, proj = files
    assert main([str(proj), str(d / "ok.ecs"), "--json"]) == 0
    rows = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert rows[-1]["summary"]["ok"] is True and rows[0]["messages"][0].startswith("Vloženo F3")
