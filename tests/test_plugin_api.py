"""Plugin API (issue #142): verze API (`API_VERSION`, `REQUIRES_API`) a registrace kontroly `ctx.add_check`
včetně `check_project(..., extra_checks=...)`. Domovská složka je izolovaná autouse fixturou v conftest.py."""
import ast
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from envocad import plugins
from envocad.cmd import CommandRunner, Journal
from envocad.library.store import LibraryStore
from envocad.model.checks import ERROR, INFO, WARNING, Finding, check_project
from envocad.model.project import Element, Project

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


@pytest.fixture(autouse=True)
def _clean_checks(monkeypatch):
    """`plugins.CHECKS` je globální – každý test dostane prázdný registr a po testu se obnoví původní."""
    monkeypatch.setattr(plugins, "CHECKS", [], raising=False)


@pytest.fixture
def pdir(tmp_path, monkeypatch):
    pd = tmp_path / "plugins"
    pd.mkdir()
    monkeypatch.setattr(plugins, "plugin_dirs", lambda: [pd])
    return pd


def _finding(text="x", severity=WARNING, code="my_check") -> Finding:
    return Finding(severity, "", "", "", False, "", text, code)


def _project() -> Project:
    p = Project(name="API")
    p.sheets[0].elements += [Element("fve.breaker_mcb", 60, 150, attrs={"ref": "F1"})]
    return Project.from_dict(p.to_dict())


def _run(project, lib, *extra):
    return check_project(project, lib, standard_paper="A3", extra_checks=extra)


# ---- verze API -----------------------------------------------------------------------------------------------------
def test_api_version_constant():
    assert isinstance(plugins.API_VERSION, int) and not isinstance(plugins.API_VERSION, bool)
    assert plugins.API_VERSION >= 1


@pytest.mark.parametrize("header", ["", "REQUIRES_API = 1\n", "REQUIRES_API = 0\n",
                                    "from envocad import plugins\nREQUIRES_API = plugins.API_VERSION\n"])
def test_plugin_loads_when_api_missing_or_not_newer(pdir, header):
    (pdir / "ok.py").write_text(header + "def register(ctx):\n    ctx.add_menu_action('N', 'OK', lambda w: None)\n",
                                encoding="utf-8")
    ctx = plugins.load_plugins(None)
    assert ctx.loaded == ["ok"] and ctx.failed == []
    assert [t for _m, t, _c in ctx.menu_actions] == ["OK"]


def test_plugin_requiring_newer_api_is_rejected(pdir):
    need = plugins.API_VERSION + 41
    (pdir / "a_future.py").write_text(
        f"REQUIRES_API = {need}\n"
        "CALLED = []\n"
        "def register(ctx):\n"
        "    CALLED.append(1)\n"
        "    ctx.add_menu_action('N', 'Budoucnost', lambda w: None)\n"
        "    ctx.add_check(lambda p, l: [])\n", encoding="utf-8")
    (pdir / "b_ok.py").write_text("def register(ctx):\n    ctx.add_menu_action('N', 'OK', lambda w: None)\n",
                                  encoding="utf-8")
    ctx = plugins.load_plugins(None)
    assert ctx.loaded == ["b_ok"]                                       # ostatní pluginy se načtou dál
    assert [n for n, _ in ctx.failed] == ["a_future"]
    msg = ctx.failed[0][1]
    assert "API" in msg and str(need) in msg and str(plugins.API_VERSION) in msg
    assert any(ch in msg for ch in "ěščřžýáíéůú"), msg                  # hláška je česky
    assert [t for _m, t, _c in ctx.menu_actions] == ["OK"]
    assert plugins.plugin_checks() == []


def test_register_not_called_for_newer_api(pdir, tmp_path):
    marker = tmp_path / "called.txt"
    (pdir / "f.py").write_text(
        f"REQUIRES_API = {plugins.API_VERSION + 1}\n"
        f"def register(ctx):\n    open({str(marker)!r}, 'w').write('x')\n", encoding="utf-8")
    ctx = plugins.load_plugins(None)
    assert ctx.loaded == [] and [n for n, _ in ctx.failed] == ["f"]
    assert not marker.exists()


@pytest.mark.parametrize("value", ['"1"', "1.5", "True", "None", "[1]"])
def test_plugin_with_non_int_requires_api_is_rejected(pdir, value):
    (pdir / "bad.py").write_text(f"REQUIRES_API = {value}\ndef register(ctx):\n"
                                 "    ctx.add_menu_action('N', 'X', lambda w: None)\n", encoding="utf-8")
    (pdir / "z_ok.py").write_text("def register(ctx):\n    pass\n", encoding="utf-8")
    ctx = plugins.load_plugins(None)
    assert [n for n, _ in ctx.failed] == ["bad"]
    assert ctx.loaded == ["z_ok"] and ctx.menu_actions == []


# ---- ctx.add_check -------------------------------------------------------------------------------------------------
def test_add_check_rejects_non_callable():
    ctx = plugins.PluginContext(library=None)
    with pytest.raises(TypeError):
        ctx.add_check("nejsem funkce")
    with pytest.raises(TypeError):
        ctx.add_check(None)
    assert plugins.plugin_checks() == []


def test_add_check_pending_until_register_succeeds():
    def fn(project, lib):
        return []
    sub = plugins.PluginContext(library=None, live=False)
    sub.add_check(fn)
    assert sub.checks == [fn]
    assert plugins.plugin_checks() == []                                  # do registru až po úspěšném register


def test_add_check_live_applies_immediately():
    def fn(project, lib):
        return []
    ctx = plugins.PluginContext(library=None, live=True)
    ctx.add_check(fn)
    assert plugins.plugin_checks() == [fn]
    ctx.add_check(fn)                                                     # duplicita se nepřidá
    assert plugins.plugin_checks() == [fn]


def test_plugin_checks_returns_copy():
    def fn(project, lib):
        return []
    plugins.PluginContext(library=None, live=True).add_check(fn)
    got = plugins.plugin_checks()
    got.append(lambda p, l: [])
    got.clear()
    assert plugins.plugin_checks() == [fn] and plugins.CHECKS == [fn]


def test_load_plugins_registers_check_after_success(pdir, lib):
    (pdir / "chk.py").write_text(
        "from envocad.model.checks import Finding, INFO\n"
        "def my_plugin_check(project, lib):\n"
        "    return [Finding(INFO, '', '', '', False, '', 'z pluginu', 'from_plugin')]\n"
        "def register(ctx):\n    ctx.add_check(my_plugin_check)\n", encoding="utf-8")
    ctx = plugins.load_plugins(lib)
    assert ctx.loaded == ["chk"] and ctx.failed == []
    fns = plugins.plugin_checks()
    assert [f.__name__ for f in fns] == ["my_plugin_check"]
    assert ctx.checks == []                                               # čekající fronta se vyprázdnila
    assert any(f.code == "from_plugin" for f in check_project(_project(), lib, standard_paper="A3",
                                                              extra_checks=fns))


def test_load_plugins_does_not_duplicate_same_function(pdir):
    (pdir / "twice.py").write_text(
        "def chk(project, lib):\n    return []\n"
        "def register(ctx):\n    ctx.add_check(chk)\n    ctx.add_check(chk)\n", encoding="utf-8")
    plugins.load_plugins(None)
    assert [f.__name__ for f in plugins.plugin_checks()] == ["chk"]


def test_plugin_crashing_after_add_check_leaves_no_check(pdir):
    (pdir / "half.py").write_text(
        "def chk(project, lib):\n    return []\n"
        "def register(ctx):\n    ctx.add_check(chk)\n    raise ValueError('half')\n", encoding="utf-8")
    (pdir / "ok.py").write_text("def chk_ok(project, lib):\n    return []\n"
                                "def register(ctx):\n    ctx.add_check(chk_ok)\n", encoding="utf-8")
    ctx = plugins.load_plugins(None)
    assert [n for n, _ in ctx.failed] == ["half"] and ctx.loaded == ["ok"]
    assert [f.__name__ for f in plugins.plugin_checks()] == ["chk_ok"]


def test_plugin_with_invalid_check_is_rejected(pdir):
    (pdir / "bad.py").write_text("def register(ctx):\n    ctx.add_check('x')\n", encoding="utf-8")
    ctx = plugins.load_plugins(None)
    assert [n for n, _ in ctx.failed] == ["bad"] and "TypeError" in ctx.failed[0][1]
    assert plugins.plugin_checks() == []


# ---- check_project(extra_checks=...) -------------------------------------------------------------------------------
def test_extra_check_findings_appear_in_result(lib):
    p = _project()
    base = check_project(p, lib, standard_paper="A3")

    def plug_check(project, library):
        return [_finding("nález pluginu", ERROR), _finding("info pluginu", INFO)]
    res = _run(p, lib, plug_check)
    mine = [f for f in res if f.code == "my_check"]
    assert {f.text for f in mine} == {"nález pluginu", "info pluginu"}
    assert [f for f in res if f.code != "my_check"] == base
    order = {ERROR: 0, WARNING: 1, INFO: 2}                               # společné řazení podle závažnosti
    assert [order[f.severity] for f in res] == sorted(order[f.severity] for f in res)


def test_extra_check_receives_project_and_library(lib):
    p = _project()
    seen = []

    def spy(project, library):
        seen.append((project, library))
    _run(p, lib, spy)
    assert len(seen) == 1 and seen[0][1] is lib and seen[0][0].name == p.name


def test_no_extra_checks_is_same_as_before(lib):
    p = _project()
    base = check_project(p, lib, standard_paper="A3")
    assert _run(p, lib) == base
    assert check_project(p, lib, standard_paper="A3", extra_checks=[]) == base
    assert all(f.code != "plugin_check" for f in base)


def test_extra_check_returning_none_is_ok(lib):
    def nothing(project, library):
        return None
    p = _project()
    assert _run(p, lib, nothing) == check_project(p, lib, standard_paper="A3")


def test_extra_check_generator_is_accepted(lib):
    def gen(project, library):
        yield _finding("z generátoru")
    assert any(f.text == "z generátoru" for f in _run(_project(), lib, gen))


def test_failing_extra_check_becomes_error_and_others_still_run(lib):
    def explode(project, library):
        raise RuntimeError("kaboom")

    def after(project, library):
        return [_finding("po výjimce")]
    p = _project()
    res = _run(p, lib, explode, after)
    errs = [f for f in res if f.code == "plugin_check"]
    assert len(errs) == 1 and errs[0].severity == ERROR
    assert "explode" in errs[0].text and "RuntimeError" in errs[0].text and "kaboom" in errs[0].text
    assert any(f.text == "po výjimce" for f in res)                       # další kontrola proběhla
    base = check_project(p, lib, standard_paper="A3")
    assert all(f in res for f in base)                                    # ostatní nálezy zůstaly


@pytest.mark.parametrize("bad", ['text', 42, object()], ids=["str", "int", "object"])
def test_extra_check_returning_non_iterable_is_error(lib, bad):
    def broken(project, library):
        return bad
    res = _run(_project(), lib, broken)
    errs = [f for f in res if f.code == "plugin_check"]
    assert errs and all(f.severity == ERROR for f in errs)


def test_extra_check_with_invalid_items_keeps_valid_findings(lib):
    def mixed(project, library):
        return ["text", _finding("platný"), 42, _finding("špatná závažnost", severity="xx")]
    res = _run(_project(), lib, mixed)
    assert any(f.text == "platný" and f.code == "my_check" for f in res)
    assert not any(f.severity == "xx" for f in res)
    errs = [f for f in res if f.code == "plugin_check"]
    assert errs and all(f.severity == ERROR for f in errs)
    assert all("mixed" in f.text for f in errs)


def test_model_checks_does_not_import_plugins():
    src = (ROOT / "envocad" / "model" / "checks.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            assert not any(a.name.startswith("envocad.plugins") for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not mod.startswith("envocad.plugins")
            assert not (mod == "envocad" and any(a.name == "plugins" for a in node.names))


# ---- end-to-end: příkaz CHECKS -------------------------------------------------------------------------------------
def test_registered_check_shows_up_in_checks_command(lib):
    def e2e_check(project, library):
        return [_finding("viditelné v CHECKS", ERROR, "e2e_code")]
    plugins.PluginContext(library=lib, live=True).add_check(e2e_check)
    r = CommandRunner(_project(), lib, journal=Journal())
    res = r.execute("CHECKS")
    assert res.ok, res.error
    assert any(d["code"] == "e2e_code" and d["text"] == "viditelné v CHECKS" for d in res.data)


# ---- vzorový plugin ------------------------------------------------------------------------------------------------
def test_example_check_plugin_loads_and_runs(lib, monkeypatch, tmp_path):
    home = tmp_path / "plugins_home"
    home.mkdir()
    builtin = ROOT / "envocad" / "plugins_builtin"
    monkeypatch.setattr(plugins, "plugin_dirs", lambda: [builtin, home])
    ctx = plugins.load_plugins(lib)
    assert "example_check" in ctx.loaded, ctx.failed
    fns = plugins.plugin_checks()
    assert fns
    import importlib.util
    spec = importlib.util.spec_from_file_location("example_check_probe", builtin / "example_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.REQUIRES_API == 1
    for fn in fns:
        assert isinstance(fn(Project(name="prázdný"), lib), list)
    assert isinstance(check_project(Project(name="prázdný"), lib, standard_paper="A3", extra_checks=fns), list)
