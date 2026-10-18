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
    assert d == before and out["format_version"] == 12
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


def _jps_with_switchboard() -> Project:
    from envocad.library.templates import apply_template
    from envocad.model.project import Layout, sync_feed_links
    p = Project(name="Kopie listu")
    s = p.sheets[0]
    t = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    s.elements += [t, blk]
    s.wires.append(Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "1"), attrs={"ref": "W2"}))
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    sync_feed_links(p)
    if not sb.layout.placements:
        sb.layout = Layout(rows=3)
        sb.layout.set_placement(sb.elements[0].id, 0, 0.0)
    return p


def test_sheet_copied_in_json_keeps_wires_and_links():
    """List zkopírovaný v JSON (stejná id prvků a vodičů na dvou listech) → po načtení žádný visící vodič,
    list rozvaděče patří dál původnímu bloku, přívody vedou na původní vodič, kopie listu rozvaděče má vlastní
    umístění ve skříni; připomínka na kopii ukazuje na přeznačený prvek."""
    from envocad.model.project import FEED_SYMBOLS, dangling_wires, linked_wire
    p = _jps_with_switchboard()
    jps, sb = p.sheets
    feed_wires = {f.ref: f.attrs.get("wire_id") for f in sb.elements if f.symbol_id in FEED_SYMBOLS}
    assert any(feed_wires.values())
    d = p.to_dict()
    for k, src in enumerate((0, 1)):
        c = copy.deepcopy(d["sheets"][src])
        c["id"], c["name"] = f"kopie{k}", f"Kopie {k}"
        d["sheets"].append(c)
    target = d["sheets"][0]["elements"][0]["id"]
    d["notes"] = [{"sheet_id": "kopie0", "x": 0, "y": 0, "text": "a", "no": 1, "target_id": target}]
    q = Project.from_dict(d)
    assert all(not dangling_wires(s) for s in q.sheets)
    ids = [e.id for s in q.sheets for e in s.elements]
    assert len(ids) == len(set(ids))
    wids = [w.id for s in q.sheets for w in s.wires]
    assert len(wids) == len(set(wids))
    qjps, qsb, copy_jps, copy_sb = q.sheets
    assert [e.id for e in qjps.elements] == [e.id for e in jps.elements]            # první výskyt beze změny
    assert qsb.parent_element_id == jps.elements[1].id
    for f in qsb.elements:
        if f.symbol_id in FEED_SYMBOLS and feed_wires.get(f.ref):
            assert linked_wire(q, qsb, f)[0] is qjps                                   # přívod → původní vodič
    copy_ids = {e.id for e in copy_sb.elements}
    assert copy_sb.layout.placements and all(pl.element_id in copy_ids for pl in copy_sb.layout.placements)
    assert q.notes[0].target_id == copy_jps.elements[0].id != target
    assert {e.id for e in copy_jps.elements}.isdisjoint(e.id for e in qjps.elements)


def test_copied_block_takes_its_own_switchboard_sheet_and_feed_links():
    """Kopie listu JPS i listu rozvaděče, blok kopie odkazuje (atribut „sheet“) na kopii listu rozvaděče →
    kopie listu rozvaděče patří přeznačenému bloku a její přívody vedou na přeznačené vodiče kopie JPS."""
    from envocad.model.project import FEED_SYMBOLS, dangling_wires, linked_wire
    p = _jps_with_switchboard()
    d = p.to_dict()
    cj, cs = copy.deepcopy(d["sheets"][0]), copy.deepcopy(d["sheets"][1])
    cj["id"], cs["id"], cs["name"] = "kj", "ks", "R1 kopie"
    cj["elements"][1]["attrs"]["sheet"] = "R1 kopie"
    d["sheets"] += [cj, cs]
    q = Project.from_dict(d)
    qjps, qsb, copy_jps, copy_sb = q.sheets
    assert all(not dangling_wires(s) for s in q.sheets)
    assert qsb.parent_element_id == qjps.elements[1].id
    assert copy_sb.parent_element_id == copy_jps.elements[1].id != qjps.elements[1].id
    linked = [linked_wire(q, copy_sb, f) for f in copy_sb.elements
              if f.symbol_id in FEED_SYMBOLS and f.attrs.get("wire_id")]
    assert linked and all(hit is not None and hit[0] is copy_jps for hit in linked)


# ---- výkazy a exporty s visícím vodičem ---------------------------------------------------------------------------
def _dangling_generated() -> Project:
    from envocad.generate import build_project
    spec = {"name": "T", "module": {"p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9},
            "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000,
                           "i_mppt_max": 30, "strings": [20, 20]}], "ac": {"breaker_in": 50, "main_in": 125}}
    d = build_project(spec).to_dict()
    for sd in d["sheets"]:
        if sd["wires"]:
            sd["wires"][0]["a"]["element_id"] = "nonexistent"
    next(sd for sd in d["sheets"] if sd.get("kind") == "switchboard")["elements"][0]["symbol_id"] = "x.unknown"
    p = Project.from_dict(d)
    assert without_dangling(p) is not p
    return p


def test_all_reports_called_directly_ignore_dangling_wires(lib, tmp_path):
    """Každý výkaz z ALL_REPORTS (i volaný přímo, např. pluginem) a technická zpráva snesou visící vodič –
    na celém projektu i na každém listu; model se nemění."""
    from envocad.export import reports
    from envocad.export.tz_export import export_tz_docx
    p = _dangling_generated()
    before = json.dumps(p.to_dict(), sort_keys=True)
    assert len(reports.ALL_REPORTS) >= 12
    for name, fn in reports.ALL_REPORTS:
        for sheet in (None, *p.sheets):
            head, rows = fn(p, lib, sheet)
            assert isinstance(head, list) and isinstance(rows, list), name
    assert reports.devices(p, lib, p.sheets[1])
    export_tz_docx(p, lib, tmp_path / "tz.docx")
    assert (tmp_path / "tz.docx").stat().st_size > 0
    assert json.dumps(p.to_dict(), sort_keys=True) == before


def test_plugin_report_gets_project_without_dangling(tmp_path, monkeypatch, lib):
    from envocad import plugins
    from envocad.export import reports
    pd = tmp_path / "plugins"
    pd.mkdir()
    monkeypatch.setattr(plugins, "plugin_dirs", lambda: [pd])
    (pd / "r.py").write_text(
        "def register(ctx):\n"
        "    def rep(p, lib, sheet):\n"
        "        for s in ([sheet] if sheet else p.sheets):\n"
        "            for w in s.wires:\n"
        "                s.element(w.a.element_id); s.element(w.b.element_id)\n"
        "        return ['n'], [[1]]\n"
        "    ctx.add_report('Plugin výkaz', rep)\n", encoding="utf-8")
    ctx = plugins.load_plugins(None)
    try:
        assert ctx.loaded == ["r"]
        fn = dict(reports.ALL_REPORTS)["Plugin výkaz"]
        p = _dangling_generated()
        assert fn(p, lib, None) == (["n"], [[1]]) and fn(p, lib, p.sheets[0]) == (["n"], [[1]])
    finally:
        reports.ALL_REPORTS[:] = [r for r in reports.ALL_REPORTS if r[0] != "Plugin výkaz"]


def test_plugin_library_writes_are_logged_when_plugin_fails(tmp_path, monkeypatch, caplog):
    from envocad import plugins
    lib = LibraryStore(tmp_path / "lib.db")
    pd = tmp_path / "plugins"
    pd.mkdir()
    monkeypatch.setattr(plugins, "plugin_dirs", lambda: [pd])
    (pd / "w.py").write_text(
        "from envocad.model.symbol import Symbol\n"
        "def register(ctx):\n"
        "    ctx.library.put_symbol(Symbol(id='plugin.x', name='X'))\n"
        "    raise RuntimeError('pád po zápisu')\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="envocad.plugins"):
        ctx = plugins.load_plugins(lib)
    assert [n for n, _ in ctx.failed] == ["w"]
    assert any("plugin.x" in r.getMessage() and "nevracejí" in r.getMessage() for r in caplog.records)
    assert lib.get_symbol("plugin.x") is not None          # transakce knihovnu nepokrývá (docstring)
    assert "put_symbol" not in vars(lib)                     # záznam zápisů po registraci zmizí
    assert "nepokrývá" in plugins.__doc__


@pytest.mark.skipif(os.name != "posix", reason="oprávnění a symlinky POSIX")
def test_save_keeps_file_mode_and_symlink(tmp_path):
    import stat
    f = tmp_path / "a.ecp"
    Project().save(f)
    os.chmod(f, 0o664)
    old = os.umask(0o022)
    try:
        Project(name="B").save(f)
    finally:
        os.umask(old)
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o664
    real = tmp_path / "real.ecp"
    Project().save(real)
    link = tmp_path / "link.ecp"
    link.symlink_to(real)
    p = Project(name="Přes odkaz")
    p.save(link)
    assert link.is_symlink() and json.loads(real.read_text(encoding="utf-8"))["name"] == "Přes odkaz"
    assert p.path == link and (tmp_path / "real.ecp.bak").exists() and not (tmp_path / "link.ecp.tmp").exists()
