"""Balíček `envocad/generator/` (refaktoring F1): průchod topologií, registr builderů, re-export `envocad.generate`."""
from __future__ import annotations

import pytest
from generate_snapshot import CASES, canon

from envocad import generate
from envocad.generator import build, chain, context
from envocad.generator.boards import grid, hds, mv, rfve, rfve_ac, rfve_dc
from envocad.generator.boards.base import ChainContext, PvGeometry
from envocad.library.topologies import load_topologies
from envocad.model.project import Project

_INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


def _ctx(topology) -> ChainContext:
    p = Project()
    geo = PvGeometry([], [], 0, 0, 0, 0, 0, 0, 0, [], 0, 0, 0, 0)
    return ChainContext(spec={}, project=p, sheet=p.sheets[0], building="company", combined=False, geo=geo,
                        topology=topology)


def test_generate_is_thin_reexport():
    """`envocad.generate` jen re-exportuje balíček (veřejné API, CLI, logger beze změny)."""
    assert generate.build_project is build.build_project
    assert generate.DEFAULT_SPEC is build.DEFAULT_SPEC
    assert generate.log.name == "envocad.generate" == context.log.name
    assert "_BUILD_LIB" not in vars(generate)       # knihovna jen v `generator.context` (patch na jednom místě)
    assert generate.main([]) == 2


def test_builders_per_role():
    topos = load_topologies()
    ctx = _ctx(topos["nn"])
    got = {n.role: chain.builder_for(ctx, n) for n in topos["nn"].nodes}
    assert got == {"rfve_dc": rfve_dc.BUILDER, "inverter": None, "rfve_ac": rfve_ac.BUILDER, "hr": None, "re": None,
                   "hds": hds.BUILDER, "grid": grid.BUILDER}
    ctx = _ctx(topos["rd"])
    assert [chain.builder_for(ctx, n) for n in topos["rd"].nodes] == [rfve.BUILDER, None, None, None, hds.BUILDER,
                                                                       grid.BUILDER]
    ctx = _ctx(topos["vn"])
    got = {n.role: chain.builder_for(ctx, n) for n in topos["vn"].nodes}
    assert {r: got[r] for r in ("hr", "tr", "rvn", "grid", "re")} == dict.fromkeys(("hr", "tr", "rvn", "grid", "re"),
                                                                                   mv.BUILDER)
    # průchod přeskočí střídače a role bez builderu
    assert [n.role for n, _b in chain._chain_nodes(_ctx(topos["nn"]))] == ["rfve_dc", "rfve_ac", "hds", "grid"]


def test_topology_selected_from_unmerged_spec():
    """Výběr topologie na nesloučené specifikaci: zvolený preset `vn` bez `connection.level` = přípojka VN
    (sloučená by měla level „nn“ z `DEFAULT_SPEC` a výběr by selhal)."""
    spec = {"topology": "vn", "inverters": [{"ref": "T1", **_INV, "strings": [20]}]}
    p = generate.build_project(spec)
    refs = {e.attrs.get("ref") for e in p.sheets[0].elements}
    assert {"HR", "RVN", "RE"} <= refs
    vn = generate.build_project({**spec, "topology": "", "connection": {"level": "vn"}})
    assert canon(p)["sheets"] == canon(vn)["sheets"]
    assert p.meta == vn.meta and p.meta["topology"] == "vn"          # i id presetu a náhled řetězce
    assert p.meta["topology_chain"] == "stringy → RFVE.DC → T → RFVE.AC → HR → TR → RVN → DS (+ RE)"


def test_nn_hr_meter_same_drawing_as_nn():
    """V F1 mají presety nn a nn_hr_meter stejný výkres (HR, RE a HDS ještě nemají builder)."""
    spec = CASES["two_inv"]
    a = canon(generate.build_project(spec))
    b = canon(generate.build_project({**spec, "topology": "nn_hr_meter"}))
    assert a["sheets"] == b["sheets"]


@pytest.mark.parametrize("spec, msg", [
    ({"topology": "neznama"}, "Neznámá topologie"),
    ({"topology": "rd"}, "je pro druh objektu"),                         # firma s presetem RD
    ({"building": "house", "topology": "nn"}, "je pro druh objektu"),
])
def test_invalid_topology_raises(spec, msg):
    with pytest.raises(ValueError, match=msg):
        generate.build_project({**spec, "inverters": [{"ref": "T1", **_INV, "strings": [20]}]})


def test_custom_topology_without_grid_and_ac_node(tmp_path, monkeypatch):
    """Vlastní topologie bez článku RFVE.AC a DS: hlavní AC rozvaděč a DS vzniknou i tak (výkres jako u topologie
    RFVE.DC → T → RFVE.AC → DS)."""
    import json
    home = tmp_path / "home"
    (home / "topologies").mkdir(parents=True)
    (home / "topologies" / "jen_dc.json").write_text(json.dumps({
        "version": 1, "id": "jen_dc", "name": "Jen DC", "level": "nn",
        "nodes": [{"role": "rfve_dc"}, {"role": "inverter"}]}), encoding="utf-8")
    (home / "topologies" / "primo.json").write_text(json.dumps({
        "version": 1, "id": "primo", "name": "Přímo do DS", "level": "nn",
        "nodes": [{"role": "rfve_dc", "ref": "RFVE.DC"}, {"role": "inverter"}, {"role": "rfve_ac", "ref": "RFVE.AC"},
                  {"role": "grid"}]}), encoding="utf-8")
    monkeypatch.setenv("ENVOCAD_HOME", str(home))
    assert "jen_dc" in load_topologies()
    spec = CASES["two_inv"]
    a = canon(generate.build_project({**spec, "topology": "primo"}))
    b = canon(generate.build_project({**spec, "topology": "jen_dc"}))
    assert a["sheets"] == b["sheets"]


EXPECTED_TOPOLOGY = {"house": "rd", "vn": "vn"}


@pytest.mark.parametrize("name", list(CASES))
def test_meta_topology(name, tmp_path):
    """Krok 7: generátor zapíše `meta["topology"]` (id presetu) a `meta["topology_chain"]` (náhled řetězce);
    meta jsou řetězce – uložení a načtení projektu beze změny formátu."""
    from envocad.generator.spec import building_kind, chain_text, select_topology
    spec = CASES[name]
    p = generate.build_project(spec)
    level = (spec.get("connection") or {}).get("level", "nn")
    want = EXPECTED_TOPOLOGY.get("house" if building_kind(spec.get("building")) == "house" else level, "nn")
    assert p.meta["topology"] == want
    assert p.meta["topology_chain"] == chain_text(select_topology(spec))
    assert p.meta["topology_chain"].startswith("stringy → ") and p.meta["topology_chain"].endswith(("DS", "(+ RE)"))
    path = tmp_path / "p.ecp"
    p.save(path)
    q = Project.load(path)
    assert q.meta["topology"] == want and q.meta["topology_chain"] == p.meta["topology_chain"]


def test_meta_topology_explicit_preset():
    p = generate.build_project({**CASES["two_inv"], "topology": "nn_hr_meter"})
    assert p.meta["topology"] == "nn_hr_meter"
    assert p.meta["topology_chain"] == "stringy → RFVE.DC → T → RFVE.AC → HR → HDS → DS"


# ---- dřívější jména `envocad.generate` (review F1) --------------------------------------------------------------------
# všechna top-level jména `envocad/generate.py` na commitu aaf9040 (před refaktoringem; definice i importy z envocad)
OLD_GENERATE_NAMES = """
    AC_BUS_POS AC_CONDUCTORS AC_CORE_GAP AC_FEED_X0 AC_MAX_INVERTERS_BUS AC_ROW_BOTTOM AC_ROW_DEVICES
    AC_SWITCHBOARD_REF BATTERY_CABLE BATTERY_ROW_EXTRA BUILDINGS BUS_B_X BUS_DROP_STEP BUS_OUTPUTS BusLayout
    CELL_NAMES CT_CONDUCTORS CT_PRIMARY_SIZES DC_AC_GAP DC_CONDUCTORS DC_INPUTS_PER_MPPT_DEFAULT DC_PE_AROUND
    DC_PE_JOIN_DY DC_PE_Y DC_ROUTE_BOX_PREFIX DC_SPD_DX DC_SPD_Y DC_TECH_BOX_REF DC_U_GAP DC_U_PITCH DC_U_TOP
    DC_U_WIDTH DC_U_X0 DEFAULT_SPEC Element FEED_SYMBOL FUSE_SYMBOLS GROUP_PITCH HOUSE_SWITCHBOARD
    HOUSE_SWITCHBOARD_AC INTERRUPT_GAP_AC INTERRUPT_GAP_BLOCK INTERRUPT_GAP_INV INVERTER_MODE_KEYS INV_LABEL_SPACE
    InverterData JPS_AC_SHEET_NAME JPS_AC_SUFFIX LV_BREAKER_SIZES LV_FEEDER_SIZES MAIN_LV_BOARD_REF
    MODULE_SPEC_FROM_ATTR OUTS_ATTR PITCH_ATTR PORT_PITCH Project STATIONS Sheet TAPS_ATTR UNRESOLVED_IN U_LV
    U_MV_DEFAULT U_MV_RANGE VN_BREAKER_FROM_KVA VN_CONDUCTORS VN_FUSE_FACTOR VN_FUSE_SIZES VT_CONDUCTORS Wire
    WireEnd _BUILD_LIB _VOLTAGE_RE _ac_box_from_macros _ac_core_after_feeds _ac_core_parametric _add_dc_part
    _align_bends _align_bends_sheet _align_connection _align_outputs _align_route_boxes _apply_component
    _apply_inverter_component _apply_module_component _apply_optimizer_component _apply_optimizer_rules
    _apply_spd_component _blank_unresolved _bridge_groups _build_ac_switchboard _build_main_lv_board
    _build_meter_board _build_mv_board _build_project _bus_b_ports_by_x _bus_drop_points _bus_out_x
    _connection_blocks _dc_box_from_macro _dc_from_below _el _feed _feed_macro_from_below _fuse_in
    _grow_switchboards _insert_macro _int_attr _lib _macro_ref _macro_values _macro_vars _mark_unresolved _merge
    _modules_per_optimizer _next_size _num _num_or _place_jps _place_sequential _route_house _s _split_jps
    _terminal_group _wire build_dc_strings build_project building_kind connection_currents dc_box_ref
    element_symbol fuse_in_why fve_feeder_in holder_max_in inverters_ac_current is_feed_in is_feed_out
    is_solaredge jps_max_paper layout_of line_end line_span load_spec log main parse_number parse_strings
    parse_voltage ref_ranges station_kind station_label string_ports sync_cables sync_feed_links voltage_label
""".split()  # noqa: SIM905 – čitelnější než seznam 154 řetězců


def test_old_generate_names_redirected():
    """Každé dřívější jméno je v `envocad.generate` dál dostupné: re-export beze změny, nebo přesměrování na nové
    umístění s DeprecationWarning (stejný objekt, ne kopie)."""
    import importlib
    import warnings
    assert len(OLD_GENERATE_NAMES) == 154
    missing = [n for n in OLD_GENERATE_NAMES if n not in vars(generate) and n not in generate._MOVED]
    assert missing == []
    assert set(generate._MOVED) <= set(OLD_GENERATE_NAMES)
    assert not set(generate._MOVED) & set(vars(generate))
    for name, target in generate._MOVED.items():
        with pytest.warns(DeprecationWarning, match=f"envocad.generate.{name} je přesunuto do {target}.{name}"):
            got = getattr(generate, name)
        assert got is getattr(importlib.import_module(target), name), name
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert generate.build_project is build.build_project          # veřejné API bez varování
    with pytest.raises(AttributeError):
        generate.neexistuje  # noqa: B018
    assert {"station_kind", "_lib", "_BUILD_LIB", "build_project"} <= set(dir(generate))


def test_old_generate_private_names_examples():
    from envocad.generator import jps
    from envocad.generator.boards import mv as bmv
    with pytest.warns(DeprecationWarning):
        assert generate.station_kind is bmv.station_kind and generate.STATIONS is bmv.STATIONS
    with pytest.warns(DeprecationWarning):
        assert generate._split_jps is jps._split_jps
    with pytest.warns(DeprecationWarning):
        from envocad.generate import _BUILD_LIB  # noqa: F401 – i import jménem projde (s varováním)


def test_old_generate_setattr_goes_to_context(monkeypatch):
    """Starý patch `monkeypatch.setattr(generate, "_lib", …)` zapíše do `generator.context` (jinak by se tiše
    neuplatnil) a po testu se vrátí."""
    real = context._lib
    sentinel = object()
    with pytest.warns(DeprecationWarning):
        monkeypatch.setattr(generate, "_lib", lambda: sentinel)
    assert context._lib() is sentinel and "_lib" not in vars(generate)
    with pytest.warns(DeprecationWarning):
        monkeypatch.undo()
    assert context._lib is real


def test_nobody_imports_build_lib_by_name():
    """`_lib` a `_BUILD_LIB` se berou jen jako atribut modulu `generator.context` (`context._lib()`); import jménem
    (`from … import _lib`) by byl kopie, kterou patch v testech ani `build_project` nezmění."""
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    bad = []
    for path in [*root.joinpath("envocad").rglob("*.py"), *root.joinpath("tests").rglob("*.py"),
                 *root.joinpath("tools").rglob("*.py")]:
        if path.resolve() == Path(__file__).resolve():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported = isinstance(node, ast.ImportFrom) and any(a.name in ("_lib", "_BUILD_LIB") for a in node.names)
            other_attr = (isinstance(node, ast.Attribute) and node.attr in ("_lib", "_BUILD_LIB")
                          and not (isinstance(node.value, ast.Name) and node.value.id == "context"))
            if imported or other_attr:
                bad.append(f"{path.relative_to(root)}:{node.lineno}")
    assert bad == []


def test_generator_package_all_and_dir():
    import envocad.generator as pkg
    assert pkg.__all__ == ["build_project"] and "build_project" in dir(pkg)
    assert all(getattr(pkg, n) is build.build_project for n in pkg.__all__)   # jako `from envocad.generator import *`
    with pytest.raises(AttributeError):
        pkg.neexistuje  # noqa: B018
