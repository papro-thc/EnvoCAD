"""DC svodič přepětí v rozvaděči stringů: odbočka ze svorky odpínače (dvojitá dutinka), průřezy, údaje SPD ve
výkresu, kontrola strany odpínače a délky odbočky – bez Qt."""
import pytest

from envocad.generate import build_project
from envocad.library.store import LibraryStore
from envocad.model import multipole as mp
from envocad.model.checks import spd_findings
from envocad.model.project import Element, Project, Wire, WireEnd, element_symbol
from envocad.model.symbol import Attribute
from envocad.model.wiring import SPD_BRANCH_MAX_MM, production_wires, twin_clamp_note


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


@pytest.fixture(scope="module")
def route_box():
    p = build_project({"name": "t", "inverters": [{"ref": "T1", "strings": [24] * 2}], "dc": {"route_boxes": 1}})
    sb = next(s for s in p.switchboards() if "po trase" in s.name)
    return p, sb


def test_attribute_display_keeps_unit_in_value():
    a = Attribute("uc", "Uc [V]", fmt="Uc {} V")
    assert a.display("1000") == "Uc 1000 V"
    assert a.display("1000 V DC") == "Uc 1000 V DC"
    assert Attribute("p", "P", fmt="{} kW").display("25 kW") == "25 kW"


def test_generator_applies_spd_article(route_box, lib):
    p, sb = route_box
    spds = [e for e in sb.elements if e.symbol_id == "fve.spd"]
    assert spds and all(e.component_id == "weidmuller-vpu-pv-i-ii-3-1000" for e in spds)
    e = spds[0]
    assert (e.attrs["type"], e.attrs["uc"], e.attrs["up"], e.attrs["iscpv"]) == \
        ("VPU PV I+II 3 1000", "1000 V DC", "3,8", "11")
    sym = element_symbol(p, e, lib)
    shown = [a.display(e.attrs.get(a.key, "")) for a in sym.attributes if a.show and e.attrs.get(a.key)]
    assert {"Uc 1000 V DC", "Up ≤ 3,8 kV", "ISCPV 11 kA"} <= set(shown)


def test_spd_branch_leaves_from_disconnector_terminal(route_box, lib):
    """Odbočka k SPD je druhý vodič ze svorky odpínače (vývod rovně je hlavní): trasa začíná hned za vývodem
    portu se zkosením 45°; konec „b“ se trasuje od svého portu a obrátí."""
    p, sb = route_box
    from envocad.model.multipole_geometry import multipole_geometry
    g = multipole_geometry(p, sb, lib)
    poles = {e.id: mp.element_poles(sb, e, element_symbol(p, e, lib)) for e in sb.elements}
    for eid, ep in poles.items():
        ep.origin = g.origins.get(eid, ep.origin)
    branches = mp.branch_ends(sb, poles)
    spd_ids = {e.id for e in sb.elements if e.symbol_id == "fve.spd"}
    by_id = {w.id: w for w in sb.wires}
    assert branches and all({by_id[wid].a.element_id, by_id[wid].b.element_id} & spd_ids for wid, _s in branches)
    pts = mp.wire_route((0.0, 0.0), "S", (20.0, -40.0), "N", branch="a")
    assert pts[1] == (0.0, -mp.GRID + mp.BRANCH_CHAMFER) and pts[2] == (mp.BRANCH_CHAMFER, -mp.GRID)
    assert mp.wire_route((20.0, -40.0), "N", (0.0, 0.0), "S", branch="b") == pts[::-1]


def test_production_twin_ferrule_and_cross(route_box):
    p, sb = route_box
    rows = production_wires(p, sb)
    qs = next(e for e in sb.elements if e.symbol_id == "fve.dc_disconnect")
    at_qs2 = [r for r in rows if f"{qs.ref}:2" in (r.local_from, r.local_to) and r.conductor == "L+"]
    assert len(at_qs2) == 2
    for r in at_qs2:
        assert r.cross == 6.0
        f = r.ferrule_from if r.local_from == f"{qs.ref}:2" else r.ferrule_to
        assert f is not None and f.twin and f.cross == 6.0
        assert any("dvojitá dutinka 2×6" in n and "ověřit rozsah svorky" in n for n in r.notes)
    pe = [r for r in rows if r.conductor == "PE" and "SPD" in r.local_from + r.local_to]
    assert pe and all(r.cross == 6.0 and r.cross_source == "PE SPD" for r in pe)


def test_twin_clamp_note_with_catalog_range():
    e = Element("fve.dc_disconnect", 0, 0, attrs={"ref": "QS1", "cross_max": "10"})
    assert "nevejde" in twin_clamp_note(e, "QS1:2", 6.0)
    e.attrs["cross_max"] = "16"
    assert twin_clamp_note(e, "QS1:2", 6.0) == ""


def test_spd_branch_length_note(route_box):
    """Přívod k SPD + PE nad 0,5 m → poznámka u řádků odbočky; počítají se jen umístěné konce (ne odhad)."""
    p, sb = route_box
    rows = production_wires(p, sb)
    spd_rows = [r for r in rows if "SPD" in r.local_from + r.local_to]
    placed = [r for r in spd_rows if not any(n.startswith("délka odhadem") for n in r.notes)]
    pe_len = max((r.length_mm or 0 for r in placed if r.conductor == "PE"), default=0)
    for r in placed:
        if r.conductor == "PE" or r.length_mm is None:
            continue
        long = any(n.startswith("odbočka SPD") and n.endswith("vést nejkratší cestou") for n in r.notes)
        assert long == (r.length_mm + pe_len > SPD_BRANCH_MAX_MM)
    assert any(any(n.startswith("odbočka SPD") for n in r.notes) for r in placed)


def test_spd_on_string_side_is_reported():
    p = Project()
    s = p.sheets[0]
    x1 = Element("sb.feed_in", 0, 100, attrs={"ref": "X1"})
    qs = Element("fve.dc_disconnect", 0, 80, 270, attrs={"ref": "QS1"})
    x2 = Element("sb.feed_out", 0, 40, attrs={"ref": "X2"})
    f = Element("fve.spd", 20, 60, attrs={"ref": "F1"})
    s.elements += [x1, qs, x2, f]
    s.wires += [Wire(WireEnd(x1.id, "1"), WireEnd(qs.id, "1"), conductors=["L+", "L-"]),
                Wire(WireEnd(qs.id, "2"), WireEnd(x2.id, "1"), conductors=["L+", "L-"])]
    s.wires.append(Wire(WireEnd(qs.id, "2"), WireEnd(f.id, "L"), conductors=["L+", "L-"]))
    assert spd_findings(p) == []
    s.wires[-1] = Wire(WireEnd(qs.id, "1"), WireEnd(f.id, "L"), conductors=["L+", "L-"])
    fs = spd_findings(p)
    assert [x.code for x in fs] == ["spd_side"] and "QS1:1" in fs[0].text
