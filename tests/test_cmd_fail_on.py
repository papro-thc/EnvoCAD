"""CLI `python -m envocad.cmd --fail-on {chyba,varování}` (issue #125): návratový kód podle závažnosti nálezů
kontroly F7 (`CHECKS_FAILED`). Bez přepínače se kód nemění; chyba skriptu má přednost; špatná hodnota = USAGE_ERROR."""
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from envocad.cmd.__main__ import COMMAND_ERROR, USAGE_ERROR, main
from envocad.library.store import LibraryStore
from envocad.model.checks import ERROR, INFO, WARNING, check_project
from envocad.model.project import Element, Note, Project
from envocad.settings import switchboard_paper

ROOT = Path(__file__).resolve().parent.parent


def _checks_failed() -> int:
    from envocad.cmd import __main__ as m
    return m.CHECKS_FAILED


def _breaker(ref: str, x: float) -> Element:
    return Element("fve.breaker_mcb", x, 100.0, attrs={"ref": ref} if ref else {})


def _clean() -> Project:
    return Project(name="Čistý")                         # bez prvků – žádné nálezy


def _info_only() -> Project:
    p = Project(name="Info")                             # jen otevřená připomínka = INFO `note_open`
    p.notes.append(Note(sheet_id=p.sheets[0].id, text="zkontrolovat", no=1))
    return p


def _warning_only() -> Project:
    p = Project(name="Varování")                         # nezapojený jistič = varování (+ info bez artiklu)
    p.sheets[0].elements.append(_breaker("F1", 50.0))
    return p


def _with_error() -> Project:
    p = Project(name="Chyba")                            # duplicitní označení = chyba
    p.sheets[0].elements += [_breaker("F1", 50.0), _breaker("F1", 100.0)]
    return p


BUILDERS = {"clean": _clean, "info": _info_only, "warning": _warning_only, "error": _with_error}


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _severities(project: Project, lib) -> set[str]:
    return set(Counter(f.severity for f in check_project(project, lib, standard_paper=switchboard_paper())))


@pytest.fixture
def make(tmp_path):
    """make(stav, script_text) -> (cesta projektu, cesta skriptu)."""
    def _make(state: str, script: str = "# jen kontrola\nF7\n"):
        proj = tmp_path / f"{state}.ecp"
        BUILDERS[state]().save(proj)
        scr = tmp_path / "s.ecs"
        scr.write_text(script, encoding="utf-8")
        return proj, scr
    return _make


@pytest.mark.parametrize("state, has_error, has_warning, has_info", [
    ("clean", False, False, False), ("info", False, False, True),
    ("warning", False, True, True), ("error", True, True, True)])
def test_premise_project_severities(state, has_error, has_warning, has_info, lib):
    """Předpoklad testů: závažnosti nálezů testovacích projektů (ať nic neprojde omylem)."""
    got = _severities(BUILDERS[state](), lib)
    assert (ERROR in got, WARNING in got, INFO in got) == (has_error, has_warning, has_info)


def test_constant_checks_failed():
    assert _checks_failed() == 3 and len({_checks_failed(), USAGE_ERROR, COMMAND_ERROR}) == 3


@pytest.mark.parametrize("state", list(BUILDERS))
def test_without_switch_exit_code_unchanged(make, state):
    proj, scr = make(state)
    assert main([str(proj), str(scr)]) == 0


@pytest.mark.parametrize("state, fails", [("clean", False), ("info", False), ("warning", False), ("error", True)])
def test_fail_on_error(make, state, fails):
    proj, scr = make(state)
    assert main([str(proj), str(scr), "--fail-on", ERROR]) == (_checks_failed() if fails else 0)


@pytest.mark.parametrize("state, fails", [("clean", False), ("info", False), ("warning", True), ("error", True)])
def test_fail_on_warning(make, state, fails):
    proj, scr = make(state)
    assert main([str(proj), str(scr), "--fail-on", WARNING]) == (_checks_failed() if fails else 0)


def test_fail_on_equals_form(make):
    proj, scr = make("error")
    assert main([str(proj), str(scr), f"--fail-on={ERROR}"]) == _checks_failed()


@pytest.mark.parametrize("level", [ERROR, WARNING])
def test_script_error_has_priority(make, level):
    proj, scr = make("error", "MOVE F1 0,0\n")           # chybí cílový bod -> skript selže
    assert main([str(proj), str(scr), "--fail-on", level]) == COMMAND_ERROR


@pytest.mark.parametrize("level", [ERROR, WARNING])
def test_keep_going_failed_line_stays_command_error(make, level):
    proj, scr = make("error", "MOVE F1 0,0\nF7\n")
    assert main([str(proj), str(scr), "--keep-going", "--fail-on", level]) == COMMAND_ERROR


@pytest.mark.parametrize("extra", [["--fail-on", INFO], ["--fail-on", "nesmysl"], ["--fail-on", "ERROR"], ["--fail-on"]])
def test_bad_value_is_usage_error(make, extra):
    proj, scr = make("error")
    assert main([str(proj), str(scr), *extra]) == USAGE_ERROR


def test_help_mentions_fail_on(capsys):
    assert main(["-h"]) == 0
    assert "--fail-on" in capsys.readouterr().out


@pytest.mark.parametrize("level, state, code", [
    (ERROR, "error", 3), (ERROR, "warning", 0), (WARNING, "warning", 3), (WARNING, "info", 0)])
def test_json_summary_kept_and_code_follows(make, capsys, level, state, code):
    proj, scr = make(state)
    assert main([str(proj), str(scr), "--json", "--fail-on", level]) == code
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])["summary"]
    assert summary["ok"] is True
    assert (ERROR in summary["checks"]) == (state == "error")


def test_text_summary_still_printed(make, capsys):
    proj, scr = make("error")
    assert main([str(proj), str(scr), "--fail-on", ERROR]) == _checks_failed()
    assert "Kontrola F7" in capsys.readouterr().out


def test_fail_on_does_not_block_saving(make, tmp_path):
    proj, scr = make("error")
    out = tmp_path / "out.ecp"
    assert main([str(proj), str(scr), "-o", str(out), "--fail-on", ERROR]) == _checks_failed()
    assert out.exists()


# ---- subprocess (skutečný `python -m envocad.cmd`) ---------------------------------------------------------------
def _cli(*args) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    return subprocess.run([sys.executable, "-m", "envocad.cmd", *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", cwd=ROOT, env=env, timeout=300, check=False, stdin=subprocess.DEVNULL)


def test_subprocess_exit_codes(make):
    proj, scr = make("error")
    assert _cli(proj, scr).returncode == 0
    assert _cli(proj, scr, "--fail-on", ERROR).returncode == _checks_failed()
    assert _cli(proj, scr, "--fail-on", INFO).returncode == USAGE_ERROR
