"""Přípojka VN v generátoru (hlavní rozvaděč nn, transformátor, rozvaděč VN, fakturační měření nn/vn) a jednopólové
schéma odvozené z blokového schématu a listů rozvaděčů – bez Qt (kromě DXF/scény na konci)."""
import pytest

from envocad.generate import build_project, connection_currents
from envocad.library.store import LibraryStore
from envocad.model import multipole as mp
from envocad.model.checks import check_project
from envocad.model.single_line import build_tree, single_line_geometry

INVS = [{"ref": "T1", "strings": [20] * 3}, {"ref": "T2", "strings": [20] * 2}]


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _vn(metering="nn", **conn):
    return build_project({"name": "t", "inverters": INVS,
                          "connection": {"level": "vn", "metering": metering, **conn}})


def _board(p, prefix):
    return next(s for s in p.switchboards() if s.name.startswith(prefix))


def test_connection_currents():
    c = connection_currents({"transformer": {"sn": 630}, "u_vn": "22 kV", "metering": "nn"})
    assert (c["main_in"], c["ct_ratio"], c["fuse_vn"], c["breaker_vn"]) == ("1000", "1000/5 A", "31,5", False)
    c = connection_currents({"transformer": {"sn": 630}, "metering": "vn"})
    assert c["ct_ratio"] == "20/5 A"                       # In VN 16,5 A
    c = connection_currents({"transformer": {"sn": 1600}, "metering": "vn", "ct_ratio": "50/5 A"})
    assert c["breaker_vn"] and c["ct_ratio"] == "50/5 A"   # zadané má přednost


def test_nn_connection_unchanged():
    p = build_project({"name": "t", "inverters": INVS})
    assert [s.name[:3] for s in p.switchboards()][-1] == "RH "
    assert not any(e.symbol_id == "fve.transformer" for e in p.sheets[0].elements)


@pytest.mark.parametrize("metering", ["nn", "vn"])
def test_vn_connection_blocks_and_boards(metering):
    p = _vn(metering)
    rhn, rvn = _board(p, "RHN"), _board(p, "RVN")
    syms = lambda s: [e.symbol_id for e in s.elements]
    assert "fve.transformer" in syms(p.sheets[0])
    meter_board = rhn if metering == "nn" else rvn
    assert "fve.ct" in syms(meter_board) and "fve.meter" in syms(meter_board)
    assert ("fve.vt" in syms(rvn)) == (metering == "vn")
    assert syms(rvn).count("fve.earthing_switch") == 3     # 2 kabelová pole (smyčka) + transformátorové
    assert not mp.has_multipole(rvn) and mp.has_multipole(rhn)
    # hlavní rozvaděč napájený od transformátoru: přívod XT, vývody X1 (FVE) a XS (spotřeba)
    feeds = {e.ref: e.symbol_id for e in rhn.elements if e.symbol_id.startswith("sb.feed")}
    assert feeds == {"XT": "sb.feed_in", "X1": "sb.feed_out", "XS": "sb.feed_out"}


def test_vn_connection_checks_clean(lib):
    noisy = {"wire_overlap", "text_overlap", "free_port", "unconnected", "mp_text_overlap", "calc_cable", "bad_port"}
    for metering in ("nn", "vn"):
        fs = check_project(_vn(metering), lib)
        assert not [f.text for f in fs if f.code in noisy], metering
        assert not [f for f in fs if f.code == "calc_selectivity" and "menší In" in f.text]


def test_big_transformer_gets_vn_breaker():
    rvn = _board(_vn("vn", transformer={"sn": 1600}), "RVN")
    assert any(e.symbol_id == "fve.breaker_mccb" and "vypínač" in e.attrs.get("type", "") for e in rvn.elements)
    assert not any(e.symbol_id == "fve.fuse" for e in rvn.elements)


def test_tree_from_grid_to_inverters(lib):
    p = _vn("vn")
    root, nodes = build_tree(p, lib)
    assert root.element.symbol_id == "fve.grid"
    order = []

    def walk(n):
        order.append(n.element.ref or n.element.symbol_id)
        nxt = n.main if n.kind != "bus" else (n.children[0] if n.children else None)   # přípojnice: 1. vývod
        if nxt is not None:
            walk(nxt)
    walk(root)
    # hlavní větev: DS → RVN (XDS1 … XT) → TR1 → RHN (XT … X1) → RH (XOUT …) → T1
    i = order.index
    assert i("XDS1") < i("TR1") < i("XOUT") < i("T1") and order.count("XT") == 2   # vývod RVN a přívod RHN
    invs = [n for n in nodes.values() if n.element.symbol_id.startswith("fve.inverter")]
    assert len(invs) == 2 and all(not n.children for n in invs)          # DC část se nekreslí
    assert not any(n.element.symbol_id == "fve.pv_string" for n in nodes.values())
    ta = next(n for n in nodes.values() if n.element.symbol_id == "fve.ct")
    assert [m.element.symbol_id for m in ta.meters] == ["fve.meter"]
    assert all(n.element.symbol_id not in ("sb.pe_bar", "fve.earth") for n in nodes.values())


def test_tree_with_dc(lib):
    _root, nodes = build_tree(_vn(), lib, dc=True)
    assert sum(n.element.symbol_id == "fve.pv_string" for n in nodes.values()) == 5


def test_terminal_distribution_is_bus(lib):
    p = build_project({"name": "t", "inverters": INVS, "ac": {"distribution": "terminals"}})
    _root, nodes = build_tree(p, lib)
    buses = [n for n in nodes.values() if n.kind == "bus"]
    assert len(buses) == 1 and len(buses[0].children) >= 3      # 2 jističe + SPD (+ hlavní vypínač z druhé strany)


@pytest.mark.parametrize(("spec", "paper"), [({}, "A3"), ({"connection": {"level": "vn"}}, "A2")])
def test_geometry_fits_page(lib, spec, paper):
    from envocad.model.frame import MARGIN
    from envocad.model.single_line import _boxes
    g = single_line_geometry(build_project({"name": "t", "inverters": INVS, **spec}), lib)
    w, h = g.page_size
    assert g.paper == paper
    for x0, y0, x1, y1 in _boxes(g.prims):
        assert MARGIN <= x0 and x1 <= w - MARGIN and MARGIN <= y0 and y1 <= h - MARGIN
    # rámečky rozvaděčů se nepřekrývají
    frames = list(g.frames.values())
    for k, a in enumerate(frames):
        for b in frames[k + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
    texts = {p.text for p in g.prims if p.kind == "text"}
    assert {"RH", "T1", "DC: 3 stringy"} <= texts
    if spec:
        assert {"RVN", "RHN", "TR1", "630 kVA"} <= texts
        assert any(t.startswith("W") and "22-AXEKVCEY" in t for t in texts)      # kabel mezi částmi


def test_empty_project(lib):
    from envocad.model.project import Project
    g = single_line_geometry(Project(), lib)
    assert g.root is None and g.prims == []


def test_single_line_dxf(tmp_path, lib):
    import ezdxf

    from envocad.export.dxf_export import export_single_line_dxf
    out = export_single_line_dxf(_vn("vn"), lib, tmp_path / "jps")
    doc = ezdxf.readfile(out)
    msp = doc.modelspace()
    texts = {e.dxf.text for e in msp.query("TEXT")}
    assert {"RVN", "TR1", "TA1", "P1"} <= texts
    assert len(msp.query('LWPOLYLINE[layer=="ROZVADECE"]')) == 3
