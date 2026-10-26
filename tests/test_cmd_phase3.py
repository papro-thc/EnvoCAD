"""Příkazový řádek – fáze 3: export DXF / PDF / dokumentace z řádku a skriptu, příkazy pluginů (`ctx.add_command`,
CLI `--plugins`) a Soubor → Spustit skript… v okně (jeden krok undo, chyba vrátí vše)."""
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from envocad.cmd import CommandRunner, Journal, default_registry
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = '''
from envocad.cmd import CommandDef, Param


def register(ctx):
    def cmd_tag(c):
        kv = yield Param("attrs", "kv", "klíč=hodnota:", optional=True, default={})
        for e in c.require_sheet().elements:
            e.attrs["desc"] = kv.get("desc", "OK")
        return "Označeno"
    ctx.add_command(CommandDef("tag_all", "Popsat vše", aliases=("TAGALL",), run=cmd_tag))
'''


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _project() -> Project:
    p = Project(name="Fáze 3")
    p.sheets[0].elements += [Element("fve.breaker_mcb", 60, 150, attrs={"ref": "F1"}),
                             Element("fve.breaker_mcb", 140, 150, attrs={"ref": "F2"})]
    return Project.from_dict(p.to_dict())


# ---- export --------------------------------------------------------------------------------------------------------
def test_export_dxf_pdf_and_documentation_headless(lib, tmp_path):
    import ezdxf
    r = CommandRunner(_project(), lib, journal=Journal())
    res = r.execute(f'EXPORT_DXF "{tmp_path / "list.dxf"}"')
    assert res.ok, res.messages
    assert ezdxf.readfile(tmp_path / "list.dxf").modelspace() is not None
    assert res.data["files"] == [str(tmp_path / "list.dxf")]
    res = r.execute(f'PDF "{tmp_path / "list.pdf"}" A3')
    assert res.ok, res.messages
    assert (tmp_path / "list.pdf").read_bytes()[:4] == b"%PDF"
    res = r.execute(f'DOC_PDF "{tmp_path / "dok.pdf"}" A3')
    assert res.ok, res.messages
    assert (tmp_path / "dok.pdf").read_bytes()[:4] == b"%PDF" and res.data["pages"] >= 1
    assert res.changeset is None and r.journal.done == []                 # export model nemění
    assert "čekám soubor .pdf" in r.execute(f'PDF "{tmp_path / "x.txt"}"').error


def _cli(*args, stdin=None):
    env = {**os.environ, "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    for k in ("QT_QPA_PLATFORM", "PYTHONIOENCODING", "PYTHONUTF8"):
        env.pop(k, None)
    return subprocess.run([sys.executable, "-m", "envocad.cmd", *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", input=stdin, cwd=ROOT, env=env, timeout=300, check=False)


def test_cli_exports_only_into_script_folder_and_respect_dry_run(tmp_path):
    proj = tmp_path / "p.ecp"
    _project().save(proj)
    (tmp_path / "out").mkdir()
    (tmp_path / "ok.ecs").write_text("EXPORT_DXF out/a.dxf\nEXPORT_PDF out/a.pdf\n", encoding="utf-8")
    r = _cli(proj, tmp_path / "ok.ecs")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "out" / "a.dxf").exists() and (tmp_path / "out" / "a.pdf").read_bytes()[:4] == b"%PDF"
    (tmp_path / "bad.ecs").write_text("EXPORT_DXF ../jinam.dxf\n", encoding="utf-8")
    r = _cli(proj, tmp_path / "bad.ecs")
    assert r.returncode == 1 and "jen do složky skriptu" in r.stderr and not (tmp_path.parent / "jinam.dxf").exists()
    (tmp_path / "dry.ecs").write_text("EXPORT_DXF out/b.dxf\n", encoding="utf-8")
    r = _cli(proj, tmp_path / "dry.ecs", "--dry-run")
    assert r.returncode == 0 and not (tmp_path / "out" / "b.dxf").exists() and "dry-run" in r.stdout


# ---- příkazy pluginů ---------------------------------------------------------------------------------------------
def _write_plugin(name: str, body: str) -> None:
    from envocad.library.store import home_dir
    d = home_dir() / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.py").write_text(body, encoding="utf-8")


def test_plugin_command_registers_and_runs(lib):
    from envocad.plugins import load_plugins, register_plugin_commands
    _write_plugin("tagger", PLUGIN)
    ctx = load_plugins(lib)
    assert "tagger" in ctx.loaded and [c.name for c in ctx.commands] == ["tag_all"]
    reg = default_registry(user_aliases=False)
    assert register_plugin_commands(ctx, reg) == []
    p = _project()
    r = CommandRunner(p, lib, reg, journal=Journal())
    res = r.execute("TAGALL desc=hotovo")
    assert res.ok and {e.attrs["desc"] for e in p.sheets[0].elements} == {"hotovo"} and res.changeset is not None
    r.undo()
    assert all("desc" not in e.attrs for e in p.sheets[0].elements)


def test_plugin_command_clash_fails_plugin(lib):
    from envocad.plugins import PluginContext, load_plugins
    _write_plugin("zly", "from envocad.cmd import CommandDef\n\ndef register(ctx):\n"
                         "    ctx.add_menu_action('Nástroje', 'Zlý', lambda w: None)\n"
                         "    ctx.add_command(CommandDef('move', 'Posunout jinak', run=lambda c: None))\n")
    _write_plugin("tagger", PLUGIN)
    _write_plugin("tagger2", PLUGIN)                                   # stejné jméno jako tagger
    ctx = load_plugins(lib)
    failed = dict(ctx.failed)
    assert "už existuje" in failed["zly"] and "jiný plugin" in failed["tagger2"]
    assert [c.name for c in ctx.commands] == ["tag_all"] and all(t != "Zlý" for _m, t, _cb in ctx.menu_actions)
    with pytest.raises(TypeError):
        PluginContext(library=lib).add_command("není CommandDef")


def test_cli_plugin_commands_only_with_flag(tmp_path):
    _write_plugin("tagger", PLUGIN)                                    # do ENVOCAD_HOME testu – podproces ho dědí
    proj = tmp_path / "p.ecp"
    _project().save(proj)
    r = _cli(proj, "-", "-o", tmp_path / "o.ecp", stdin="TAG_ALL desc=x\n")
    assert r.returncode == 1 and "Neznámý příkaz" in r.stderr
    r = _cli(proj, "-", "-o", tmp_path / "o.ecp", "--plugins", stdin="TAG_ALL desc=x\n")
    assert r.returncode == 0, r.stderr
    assert {e.attrs["desc"] for e in Project.load(tmp_path / "o.ecp").sheets[0].elements} == {"x"}


# ---- Soubor → Spustit skript… --------------------------------------------------------------------------------------
@pytest.fixture
def win():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from envocad.ui.main_window import MainWindow
    made = []

    def make():
        w = MainWindow(LibraryStore(), _project())
        w.show()
        made.append(w)
        return w
    yield make
    for w in made:
        w.undo.setClean()
        w.close()


def _el(w, ref):
    return next(e for e in w.project.sheets[0].elements if e.ref == ref)


def test_run_script_menu_is_one_undo_step_and_error_reverts(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    w = win()
    ok = tmp_path / "ok.ecs"
    ok.write_text("RO F1\nRO F2 0,0 180\nUNDO\nMI F1\n", encoding="utf-8")     # UNDO uvnitř vrátí RO F2
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(ok), ""))
    w.actions["run_script"].trigger()
    assert (_el(w, "F1").rotation, _el(w, "F1").mirror, _el(w, "F2").rotation) == (90, True, 0)
    assert w.undo.count() == 1 and "Skript ok.ecs: 4 příkazy" in w.cmdline.output.toPlainText()
    w.undo.undo()
    assert (_el(w, "F1").rotation, _el(w, "F1").mirror) == (0, False)
    bad = tmp_path / "bad.ecs"
    bad.write_text("RO F1\nRO NENI\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(bad), ""))
    before = json.dumps(w.project.to_dict(), sort_keys=True)
    w.actions["run_script"].trigger()
    assert json.dumps(w.project.to_dict(), sort_keys=True) == before and "řádek 2" in w.cmdline.output.toPlainText()


def test_export_from_dock_with_and_without_path(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    w = win()
    w.cmdline.run_line(f'EXPORT_DXF "{tmp_path / "z_doku.dxf"}"')
    assert (tmp_path / "z_doku.dxf").exists()
    asked = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: asked.append(1) or ("", ""))
    w.cmdline.run_line("DXFOUT")                                       # bez cesty = dialog jako v menu
    assert asked == [1]


def test_cmd_package_still_imports_without_qt():
    code = ("import sys, envocad.cmd, envocad.cmd.builtin, envocad.plugins; "
            "bad = [m for m in sys.modules if m.startswith(('PySide6', 'envocad.ui'))]; assert not bad, bad")
    subprocess.run([sys.executable, "-c", code], check=True, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)})
