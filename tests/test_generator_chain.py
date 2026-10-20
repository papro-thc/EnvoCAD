"""Balíček `envocad/generator/` (refaktoring F1): průchod topologií, registr builderů, re-export `envocad.generate`."""
from __future__ import annotations

import pytest
from generate_snapshot import CASES, canon

from envocad import generate
from envocad.generator import build, chain, context
from envocad.generator.boards import grid, mv, rfve, rfve_ac, rfve_dc
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
    assert not hasattr(generate, "_BUILD_LIB")      # knihovna jen v `generator.context` (patch na jednom místě)
    assert generate.main([]) == 2


def test_builders_per_role():
    topos = load_topologies()
    ctx = _ctx(topos["nn"])
    got = {n.role: chain.builder_for(ctx, n) for n in topos["nn"].nodes}
    assert got == {"rfve_dc": rfve_dc.BUILDER, "inverter": None, "rfve_ac": rfve_ac.BUILDER, "hr": None, "re": None,
                   "hds": None, "grid": grid.BUILDER}       # F1: stávající HR, RE a HDS ještě bez builderu
    ctx = _ctx(topos["rd"])
    assert [chain.builder_for(ctx, n) for n in topos["rd"].nodes] == [rfve.BUILDER, None, None, None, None,
                                                                       grid.BUILDER]
    ctx = _ctx(topos["vn"])
    got = {n.role: chain.builder_for(ctx, n) for n in topos["vn"].nodes}
    assert {r: got[r] for r in ("hr", "tr", "rvn", "grid", "re")} == dict.fromkeys(("hr", "tr", "rvn", "grid", "re"),
                                                                                   mv.BUILDER)
    # průchod přeskočí střídače a role bez builderu
    assert [n.role for n, _b in chain._chain_nodes(_ctx(topos["nn"]))] == ["rfve_dc", "rfve_ac", "grid"]


def test_topology_selected_from_unmerged_spec():
    """Výběr topologie na nesloučené specifikaci: zvolený preset `vn` bez `connection.level` = přípojka VN
    (sloučená by měla level „nn“ z `DEFAULT_SPEC` a výběr by selhal)."""
    spec = {"topology": "vn", "inverters": [{"ref": "T1", **_INV, "strings": [20]}]}
    p = generate.build_project(spec)
    refs = {e.attrs.get("ref") for e in p.sheets[0].elements}
    assert {"HR", "RVN", "RE"} <= refs
    vn = generate.build_project({**spec, "topology": "", "connection": {"level": "vn"}})
    assert canon(p)["sheets"] == canon(vn)["sheets"]


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
    """Vlastní topologie bez článku RFVE.AC a DS: hlavní AC rozvaděč a DS vzniknou i tak (výkres jako u nn)."""
    import json
    home = tmp_path / "home"
    (home / "topologies").mkdir(parents=True)
    (home / "topologies" / "jen_dc.json").write_text(json.dumps({
        "version": 1, "id": "jen_dc", "name": "Jen DC", "level": "nn",
        "nodes": [{"role": "rfve_dc"}, {"role": "inverter"}]}), encoding="utf-8")
    monkeypatch.setenv("ENVOCAD_HOME", str(home))
    assert "jen_dc" in load_topologies()
    spec = CASES["two_inv"]
    a = canon(generate.build_project(spec))
    b = canon(generate.build_project({**spec, "topology": "jen_dc"}))
    assert a["sheets"] == b["sheets"]
