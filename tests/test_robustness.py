"""Robustnost modelu a knihoven (bez Qt): poškozené soubory, neznámé značky, osiřelé porty, atomické uložení,
pluginy, importéry."""
import copy
import json
import logging
import os
from pathlib import Path

import pytest

from envocad.library.store import LibraryStore
from envocad.model.checks import check_project
from envocad.model.project import (
    CorruptProjectError,
    Element,
    Project,
    Wire,
    WireEnd,
    element_symbol,
    migrate,
    without_dangling,
)
from envocad.model.symbol import Symbol, placeholder_symbol, with_orphan_ports

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "ukazka_fve.ecp"


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "lib.db")


def _codes(findings):
    return {f.code for f in findings}


def _base() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _dxf(p: Project, lib, tmp_path) -> None:
    from envocad.export.dxf_export import export_sheet_dxf
    for s in p.sheets:
        export_sheet_dxf(p, s, lib, tmp_path / f"{s.id}.dxf")


# ---- osiřelé porty a zástupné značky ------------------------------------------------------------------------------
def test_with_orphan_ports_adds_marked_ports_on_grid():
    base = Symbol(id="t", name="T", primitives=[{"type": "rect", "x": -5, "y": -3, "w": 10, "h": 6}])
    sym = with_orphan_ports(base, ["B", "A"])
    assert [p.name for p in sym.ports] == ["A", "B"] and sym.orphan_ports == ("A", "B")
    assert all(p.y < -3 and p.y % 2.5 == 0 and p.x % 2.5 == 0 for p in sym.ports)
    assert any(pr.get("text") == "A?" for pr in sym.primitives)
    assert with_orphan_ports(base, []) is base
    assert not base.ports        # původní značka (cache knihovny) se nemění


def test_placeholder_symbol_ports_from_wires():
    sym = placeholder_symbol("x.unknown", ["3", "1", "2"])
    assert sym.placeholder and sym.id == "x.unknown"
    assert sorted(p.name for p in sym.ports) == ["1", "2", "3"]
    assert not sym.validate()                     # porty na mřížce, bez duplicit
    assert any(pr.get("text") == "?" for pr in sym.primitives)
    assert "placeholder" not in sym.to_dict()     # jen za běhu, formát značky se nemění


def test_wire_to_missing_port_is_orphan_and_reported(lib, tmp_path):
    p = Project()
    s = p.sheets[0]
    g = Element("fve.pv_string", 30, 150, attrs={"ref": "G1"})
    t = Element("fve.inverter", 120, 150, attrs={"ref": "T1"})
    s.elements += [g, t]
    s.wires.append(Wire(WireEnd(g.id, "ZZ"), WireEnd(t.id, "DC1"), attrs={"ref": "W1"}))
    sym = element_symbol(p, g, lib)
    assert "ZZ" in sym.orphan_ports and g.port_pos(sym, "ZZ")       # žádný KeyError
    fs = check_project(p, lib)
    assert any(f.code == "bad_port" and f.ref == "W1" for f in fs)
    _dxf(p, lib, tmp_path)
    from envocad.model.routing import route_sheet
    assert route_sheet(p, s, lib)                                    # trasa vede na osiřelý port


def test_unknown_symbol_gets_placeholder_and_check(lib, tmp_path):
    d = _base()
    d["sheets"][0]["elements"][0]["symbol_id"] = "x.unknown"
    p = Project.from_dict(d)
    e = p.sheets[0].elements[0]
    sym = element_symbol(p, e, lib)
    assert sym.placeholder
    used = {end.port for w in p.sheets[0].wires for end in (w.a, w.b) if end.element_id == e.id}
    assert used and used <= {pt.name for pt in sym.ports}
    fs = check_project(p, lib)
    assert any(f.code == "symbol" and "Neznámá značka x.unknown" in f.text for f in fs)
    assert not any(f.code == "bad_port" and f.target_id in {w.id for w in p.sheets[0].wires if w.touches(e.id)}
                   for f in fs)
    _dxf(p, lib, tmp_path)


def test_switchboard_block_without_sheet_keeps_wires(lib, tmp_path):
    from envocad.generate import build_project
    spec = {"name": "T", "module": {"p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9},
            "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000,
                           "i_mppt_max": 30, "strings": [20, 20]}], "ac": {"breaker_in": 50, "main_in": 125}}
    p = build_project(spec)
    sb = p.switchboards()[-1]
    block_id = sb.parent_element_id
    jps = p.sheet_of_element(block_id)
    n_wires = sum(1 for w in jps.wires if w.touches(block_id))
    assert n_wires
    assert p.remove_sheet(sb) == []
    block = jps.element(block_id)
    assert "sheet" not in block.attrs
    assert sum(1 for w in jps.wires if w.touches(block_id)) == n_wires      # vodiče zůstaly
    sym = element_symbol(p, block, lib)
    used = {end.port for w in jps.wires for end in (w.a, w.b) if end.element_id == block_id}
    assert used <= set(sym.orphan_ports)
    bad = [f for f in check_project(p, lib) if f.code == "bad_port"]
    assert len(bad) >= n_wires
    p.save(tmp_path / "x.ecp")
    p2 = Project.load(tmp_path / "x.ecp")
    _dxf(p2, lib, tmp_path)


def test_remove_parent_sheet_detaches_switchboards():
    p = Project()
    blk = Element("fve.switchboard", 100, 100, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    from envocad.model.project import Sheet
    p.sheets.append(Sheet(name="Druhý"))
    jps = p.sheets[0]
    assert p.remove_sheet(jps) == [sb]
    assert sb.parent_element_id is None and jps not in p.sheets
    Project.from_dict(p.to_dict())


# ---- načtení poškozeného souboru ------------------------------------------------------------------------------------
@pytest.mark.parametrize("label,mutate,needle", [
    ("missing x", lambda d: d["sheets"][0]["elements"][0].pop("x"), "chybí položka „x“"),
    ("x string", lambda d: d["sheets"][0]["elements"][0].__setitem__("x", "abc"), "„x“ není číslo"),
    ("x nan", lambda d: d["sheets"][0]["elements"][0].__setitem__("x", float("nan")), "není konečné číslo"),
    ("bad points", lambda d: d["sheets"][0]["wires"][0].__setitem__("points", [[1]]), "points"),
    ("layout rows", lambda d: d["sheets"][0].__setitem__("layout", {"rows": "x"}), "rows"),
    ("version str", lambda d: d.__setitem__("format_version", "abc"), "neplatná verze formátu"),
    ("sheets dict", lambda d: d.__setitem__("sheets", {"a": 1}), "sheets"),
    ("element list", lambda d: d["sheets"][0]["elements"].__setitem__(0, [1, 2]), "položka má být objekt"),
    ("wire end str", lambda d: d["sheets"][0]["wires"][0].__setitem__("a", "x"), "vodič"),
    ("rotation", lambda d: d["sheets"][0]["elements"][0].__setitem__("rotation", 45), "rotation"),
    ("cable", lambda d: d.__setitem__("cables", [{}]), "kabel č. 1"),
])
def test_corrupt_structures_give_czech_value_error(label, mutate, needle):
    d = _base()
    mutate(d)
    with pytest.raises(ValueError) as ei:
        Project.from_dict(d)
    msg = str(ei.value)
    assert isinstance(ei.value, CorruptProjectError) and msg.startswith("Soubor je poškozen") and needle in msg, msg


def test_corrupt_message_names_sheet_and_element():
    d = _base()
    el = d["sheets"][0]["elements"][0]
    el.pop("y")
    with pytest.raises(CorruptProjectError) as ei:
        Project.from_dict(d)
    assert f"list „{d['sheets'][0]['name']}“" in str(ei.value) and f"prvek „{el['attrs']['ref']}“" in str(ei.value)


@pytest.mark.parametrize("data,needle", [
    (b"", "prázdný"), (b"   \n", "prázdný"), (b"\xff\xfe\x00bad", "UTF-8"),
    (b'{"format": "envocad-project", "sheets": [ {', "neplatný JSON"), (b"[1, 2]", "není projekt"),
])
def test_unreadable_files(tmp_path, data, needle):
    f = tmp_path / "x.ecp"
    f.write_bytes(data)
    with pytest.raises(ValueError, match=needle):
        Project.load(f)


def test_load_utf8_bom(tmp_path):
    f = tmp_path / "bom.ecp"
    f.write_bytes(b"\xef\xbb\xbf" + EXAMPLE.read_bytes())
    assert Project.load(f).name == Project.load(EXAMPLE).name


def test_symbol_from_json_utf8_bom(tmp_path):
    f = tmp_path / "s.json"
    f.write_bytes(b"\xef\xbb\xbf" + json.dumps({"id": "a.b", "name": "Č"}, ensure_ascii=False).encode("utf-8"))
    assert Symbol.from_json(f).name == "Č"


def test_settings_utf8_bom():
    from envocad import settings
    path = settings.settings_path()       # ENVOCAD_HOME testu (conftest)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(b"\xef\xbb\xbf" + json.dumps({"standard": {"author": "Ž"}}).encode("utf-8"))
    assert settings.load_settings()["standard"]["author"] == "Ž"


def test_dangling_wire_and_duplicate_ids_load_and_check(lib, tmp_path):
    d = _base()
    d["sheets"][0]["wires"][0]["a"]["element_id"] = "nonexistent"
    els = d["sheets"][0]["elements"]
    els[1]["id"] = els[0]["id"]
    d["sheets"][0]["wires"][1]["id"] = d["sheets"][0]["wires"][2]["id"]
    p = Project.from_dict(d)
    s = p.sheets[0]
    assert len({e.id for e in s.elements}) == len(s.elements)        # duplicity dostaly nová id
    assert len({w.id for w in s.wires}) == len(s.wires)
    fs = check_project(p, lib)
    assert "dangling" in _codes(fs)
    clean = without_dangling(p)
    assert clean is not p and len(clean.sheets[0].wires) < len(s.wires) and len(p.sheets[0].wires) == len(s.wires)
    assert without_dangling(Project.from_dict(_base())) is not None
    _dxf(p, lib, tmp_path)


def test_migrate_does_not_mutate_input():
    d = {"format": "envocad-project", "format_version": 4, "name": "M", "bridges": {"X1": [["1", "2"]]},
         "sheets": [{"id": "a", "name": "a", "elements": [
             {"id": "1", "symbol_id": "fve.pv_string", "x": 0, "y": 0, "attrs": {"ref": "X1"}},
             {"id": "2", "symbol_id": "fve.inverter", "x": 0, "y": 0, "attrs": {}}],
             "wires": [{"id": "w", "a": {"element_id": "1", "port": "DC+"}, "b": {"element_id": "2", "port": "DC+"}}]}]}
    before = copy.deepcopy(d)
    out = migrate(d, 4)
    assert d == before and out["format_version"] == 9
    Project.from_dict(d)
    assert d == before


# ---- atomické uložení -----------------------------------------------------------------------------------------------
def test_save_is_atomic_and_keeps_backup(tmp_path, monkeypatch):
    p = Project.load(EXAMPLE)
    f = tmp_path / "x.ecp"
    p.save(f)
    good = f.read_bytes()
    p.name = "Druhá verze"
    p.save(f)
    assert json.loads((tmp_path / "x.ecp.bak").read_text(encoding="utf-8"))["name"] == Project.load(EXAMPLE).name
    second = f.read_bytes()
    assert second != good

    def boom(_fd):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(os, "fsync", boom)
    p.name = "Třetí"
    other = tmp_path / "y.ecp"
    with pytest.raises(OSError):
        p.save(other)
    with pytest.raises(OSError):
        p.save(f)
    assert f.read_bytes() == second                      # předchozí verze netknutá
    assert p.path == f                                   # cesta z posledního úspěšného uložení
    assert not other.exists()
    assert sorted(x.name for x in tmp_path.iterdir()) == ["x.ecp", "x.ecp.bak"]   # žádný .tmp


# ---- knihovna, importéry ----------------------------------------------------------------------------------------------
def test_builtin_symbol_cannot_be_overwritten(tmp_path):
    lib = LibraryStore(tmp_path / "l.db")
    assert lib.is_builtin("fve.inverter") and lib.has_symbol("fve.inverter")
    with pytest.raises(ValueError, match="vestavěná"):
        lib.put_symbol(Symbol(id="fve.inverter", name="Import"))
    assert [p.name for p in LibraryStore(tmp_path / "l.db").get_symbol("fve.inverter").ports] == ["DC1", "DC2", "AC"]
    lib.put_symbol(Symbol(id="moje.x", name="X"))
    lib.put_symbol(Symbol(id="moje.x", name="X2"))       # uživatelskou smí přepsat (knihovna), GUI ale nabídne jiné ID
    assert not lib.is_builtin("moje.x")


def test_library_logs_instead_of_print(tmp_path, caplog, capsys):
    lib = LibraryStore(tmp_path / "l.db", load_builtin=False)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "bad.json").write_text("{", encoding="utf-8")
    (tmp_path / "pkg" / "bad.csv").write_bytes(b"\xff\xfe\x00")
    with caplog.at_level(logging.WARNING, logger="envocad.library"):
        lib._sync_symbols(tmp_path / "pkg", "user", {}, [])
        lib._sync_components(tmp_path / "pkg")
    assert "bad.json" in caplog.text
    assert capsys.readouterr().out == ""


def test_qet_nan_inf_entities_skipped(tmp_path):
    from envocad.library import qet_import
    f = tmp_path / "bn.elmt"
    f.write_text('<definition><description>'
                 '<line x1="0" y1="0" x2="10" y2="0"/>'
                 '<line x1="a" y1="" x2="nan" y2="inf"/>'
                 '<rect x="1" y="1" width="1e999" height="2"/>'
                 '<arc x="0" y="0" width="10" height="20" start="0" angle="1e300"/>'
                 '<terminal x="1e999" y="0" orientation="n"/>'
                 '<terminal x="10" y="0" orientation="e"/>'
                 '</description></definition>', encoding="utf-8")
    sym = qet_import.parse_elmt(f, "q.x")
    import math
    assert len(sym.ports) == 1
    for pr in sym.primitives:
        vals = [v for v in pr.values() if isinstance(v, float)] + [v for pt in pr.get("points", []) for v in pt]
        assert all(math.isfinite(v) for v in vals)
    assert any(pr["type"] == "line" for pr in sym.primitives)


def test_eplan_empty_csv_value_error(tmp_path):
    from envocad.library import eplan_import
    f = tmp_path / "e.csv"
    f.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="prázdný"):
        eplan_import.rows_from_commercial_csv(f)
    f.write_text("\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="prázdný"):
        eplan_import.rows_from_commercial_csv(f)


# ---- pluginy ------------------------------------------------------------------------------------------------------
def test_plugins_transactional_and_failures_reported(tmp_path, monkeypatch):
    from envocad import plugins
    from envocad.export import reports
    from envocad.library.templates import TEMPLATES
    pd = tmp_path / "plugins"
    pd.mkdir()
    monkeypatch.setattr(plugins, "plugin_dirs", lambda: [pd])
    (pd / "a_half.py").write_text(
        "def register(ctx):\n"
        "    ctx.add_menu_action('Nástroje', 'Napůl', lambda w: None)\n"
        "    ctx.add_report('Napůl výkaz', lambda p, l, s: ([], []))\n"
        "    raise ValueError('half')\n", encoding="utf-8")
    (pd / "b_exit.py").write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    (pd / "c_syntax.py").write_text("def register(ctx:\n", encoding="utf-8")
    (pd / "d_badreport.py").write_text("def register(ctx):\n    ctx.add_report('R', 'x')\n", encoding="utf-8")
    (pd / "e_badtemplate.py").write_text("def register(ctx):\n    ctx.add_template(object())\n", encoding="utf-8")
    (pd / "f_ok.py").write_text(
        "def register(ctx):\n    ctx.add_menu_action('Nástroje', 'OK', lambda w: None)\n"
        "    ctx.add_report('OK výkaz', lambda p, l, s: ([], []))\n", encoding="utf-8")
    n_templates = len(TEMPLATES)
    ctx = plugins.load_plugins(None)
    try:
        assert ctx.loaded == ["f_ok"]
        assert [n for n, _ in ctx.failed] == ["a_half", "b_exit", "c_syntax", "d_badreport", "e_badtemplate"]
        assert [t for _m, t, _c in ctx.menu_actions] == ["OK"]
        names = [r[0] for r in reports.ALL_REPORTS]
        assert "OK výkaz" in names and "Napůl výkaz" not in names
        assert len(TEMPLATES) == n_templates
        assert plugins.failed_message(ctx).startswith("Pluginy a_half, b_exit")
        ctx.failed[:] = [("x", "e")]
        assert plugins.failed_message(ctx) == "Plugin x se nenačetl (viz log)"
    finally:
        reports.ALL_REPORTS[:] = [r for r in reports.ALL_REPORTS if r[0] != "OK výkaz"]


def test_plugin_keyboard_interrupt_propagates(tmp_path, monkeypatch):
    from envocad import plugins
    pd = tmp_path / "plugins"
    pd.mkdir()
    monkeypatch.setattr(plugins, "plugin_dirs", lambda: [pd])
    (pd / "k.py").write_text("raise KeyboardInterrupt\n", encoding="utf-8")
    with pytest.raises(KeyboardInterrupt):
        plugins.load_plugins(None)
