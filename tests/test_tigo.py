"""Optimizéry Tigo: kontrola vysílače RSS / CCA + TAP (`checks.tigo_findings`), bloky Tigo v generátoru
(`generator/tigo.py`) a makro „Tigo CCA + TAP“."""
import pytest

from envocad.generate import build_project
from envocad.library.macros import find_macro
from envocad.library.store import LibraryStore
from envocad.model.checks import WARNING, check_project, tigo_findings
from envocad.model.project import Element, Project, Sheet, element_symbol

_INV = {"ref": "T1", "p_ac": 10, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30,
        "strings": [16, 16]}


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _codes(p):
    return {f.code for f in tigo_findings(p)}


def _project(*extra):
    p = Project()
    s = Sheet(name="JPS")
    p.sheets[:] = [s]
    s.elements.append(Element("fve.pv_string", 0, 0, attrs={"ref": "G1", "optimizer": "TS4-A-O",
                                                            "opt_manufacturer": "Tigo"}))
    s.elements += [Element(sid, 50 * k, 50, attrs={"ref": f"A{k}"}) for k, sid in enumerate(extra, start=1)]
    return p


def test_tigo_needs_rss_or_cca():
    assert _codes(_project()) == {"tigo_missing"}
    assert _codes(_project("fve.tigo_rss")) == set()
    assert _codes(_project("fve.tigo_cca", "fve.tigo_tap")) == set()
    assert _codes(_project("fve.tigo_cca")) == {"tigo_tap_missing"}      # CCA bez TAP s optimizéry nemluví
    p = _project()
    p.sheets[0].elements[0].attrs = {"ref": "G1", "optimizer": "S440", "opt_manufacturer": "SolarEdge"}
    assert _codes(p) == set()                                              # jiný výrobce
    p.sheets[0].elements[0].attrs = {"ref": "G1", "optimizer": "TS4-X-O"}  # bez artiklu: řada TS4
    assert _codes(p) == {"tigo_missing"}


def test_tigo_symbols(lib):
    p = _project("fve.tigo_cca", "fve.tigo_tap", "fve.tigo_rss")
    names = {e.symbol_id: {pt.name for pt in element_symbol(p, e, lib).ports} for e in p.sheets[0].elements}
    assert names["fve.tigo_cca"] == {"GW", "LAN", "PWR"} and names["fve.tigo_tap"] == {"GW"}
    assert names["fve.tigo_rss"] == {"PWR"}
    # komunikace Tigo bez zapojení není „nezapojený prvek“
    bad = {f.code for f in check_project(p, lib, standard_paper="A4") if f.severity == WARNING
           and f.target_id in {e.id for e in p.sheets[0].elements[1:]}}
    assert not bad & {"free_port", "unconnected"}


@pytest.mark.parametrize("building", ["house", "company"])
def test_generator_adds_cca_and_tap(lib, building):
    spec = {"building": building, "inverters": [_INV], "optimizer": {"component_id": "tigo-ts4-a-o"}}
    p = build_project(spec)
    s = p.sheets[0]
    tap = next(e for e in s.elements if e.symbol_id == "fve.tigo_tap")
    cca = next(e for e in s.elements if e.symbol_id == "fve.tigo_cca")
    assert any(w.touches(tap.id) and w.touches(cca.id) for w in s.wires)
    top = max((e for e in s.elements if e.symbol_id == "fve.pv_string"), key=lambda e: e.y)
    assert tap.y > top.y and cca.x > tap.x
    found = check_project(p, lib, standard_paper="A4")
    assert not {f.code for f in found} & {"tigo_missing", "tigo_tap_missing"}
    assert not [f for f in found if f.code == "text_overlap" and f.sheet_id == s.id]


def test_generator_rss_and_none():
    spec = {"building": "house", "inverters": [_INV], "optimizer": {"component_id": "tigo-ts4-a-o", "tigo": "rss"}}
    p = build_project(spec)
    rss = [e for e in p.sheets[0].elements if e.symbol_id == "fve.tigo_rss"]
    assert len(rss) == 1 and rss[0].attrs["strings"] == "G1, G2"
    assert not any(e.symbol_id in ("fve.tigo_cca", "fve.tigo_tap") for e in p.sheets[0].elements)
    spec["optimizer"]["tigo"] = "none"
    p = build_project(spec)
    assert not any(e.symbol_id.startswith("fve.tigo") for s in p.sheets for e in s.elements)
    assert "tigo_missing" in _codes(p)
    spec["optimizer"]["tigo"] = "vysílač"
    with pytest.raises(ValueError, match="optimizer.tigo"):
        build_project(spec)
    # bez Tigo optimizérů se nic nepřidá
    p = build_project({"building": "house", "inverters": [_INV]})
    assert not any(e.symbol_id.startswith("fve.tigo") for s in p.sheets for e in s.elements)


def test_tigo_macro():
    m = find_macro("Tigo CCA + TAP")
    assert m is not None
    syms = {e["symbol_id"] for e in m.fragment["elements"]}
    assert syms == {"fve.tigo_cca", "fve.tigo_tap"} and len(m.fragment["wires"]) == 1
