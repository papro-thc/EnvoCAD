"""Přípojka VN v generátoru (trafostanice kiosková / zděná / sloupová: rozvaděč VN po polích, transformátor, hlavní
rozvaděč nn, elektroměrový rozvaděč, fakturační měření nn/vn) a jednopólové schéma odvozené z blokového schématu
a listů rozvaděčů (rámečky polí a trafostanice, ruční posun) – bez Qt (kromě DXF na konci)."""
import pytest

from envocad.generate import build_project, connection_currents
from envocad.library.store import LibraryStore
from envocad.model import multipole as mp
from envocad.model.checks import check_project
from envocad.model.single_line import build_tree, single_line_geometry

INVS = [{"ref": "T1", "strings": [20] * 3}, {"ref": "T2", "strings": [20] * 2}]
VN_SYMBOLS = ("fve.switch_disconnector_vn", "fve.disconnector", "fve.breaker_vn", "fve.fuse_vn", "fve.cable_end",
              "fve.voltage_indicator", "fve.surge_arrester")


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _vn(metering="nn", **conn):
    return build_project({"name": "t", "inverters": INVS,
                          "connection": {"level": "vn", "metering": metering, **conn}})


def _board(p, prefix):
    return next(s for s in p.switchboards() if s.name.split()[0] == prefix)


def _syms(s):
    return [e.symbol_id for e in s.elements]


def test_vn_symbols(lib):
    for sid in VN_SYMBOLS:
        sym = lib.get_symbol(sid)
        assert sym.category == "VN" and any(a.key == "ref" for a in sym.attributes)
        assert all(p.x % 2.5 == 0 and p.y % 2.5 == 0 for p in sym.ports)


def test_connection_currents():
    c = connection_currents({"transformer": {"sn": 630}, "u_vn": "22 kV", "metering": "nn"})
    assert (c["main_in"], c["ct_ratio"], c["fuse_vn"], c["breaker_vn"]) == ("1000", "1000/5 A", "31,5", False)
    c = connection_currents({"transformer": {"sn": 630}, "metering": "vn"})
    assert c["ct_ratio"] == "20/5 A"                       # In VN 16,5 A
    c = connection_currents({"transformer": {"sn": 1600}, "metering": "vn", "ct_ratio": "50/5 A"})
    assert c["breaker_vn"] and c["ct_ratio"] == "50/5 A"   # zadané má přednost
    assert connection_currents({"metering": "vn", "station": "sloup"})["metering"] == "nn"   # sloup: jen nn


def test_nn_connection_unchanged():
    p = build_project({"name": "t", "inverters": INVS})
    assert [s.name.split(" – ")[0] for s in p.switchboards()][-1] == "RFVE.AC"
    assert not any(e.symbol_id == "fve.transformer" for e in p.sheets[0].elements)


@pytest.mark.parametrize("metering", ["nn", "vn"])
def test_vn_connection_blocks_and_boards(metering):
    p = _vn(metering)
    rhn, rvn, re_ = _board(p, "HR"), _board(p, "RVN"), _board(p, "RE")
    assert "fve.transformer" in _syms(p.sheets[0])
    assert "fve.ct" in _syms(rhn if metering == "nn" else rvn)
    assert _syms(re_).count("fve.meter") == 1 and "fve.meter" not in _syms(rhn) + _syms(rvn)
    assert ("fve.vt" in _syms(rvn)) == (metering == "vn")
    assert _syms(rvn).count("fve.earthing_switch") == 3     # 2 kabelová pole (smyčka) + transformátorové
    assert _syms(rvn).count("fve.cable_end") == 3 and _syms(rvn).count("fve.voltage_indicator") == 2
    assert _syms(rvn).count("fve.fuse_vn") == 1 and "fve.switch_disconnector" not in _syms(rvn)
    assert not mp.has_multipole(rvn) and mp.has_multipole(rhn) and mp.has_multipole(re_)
    # hlavní rozvaděč napájený od transformátoru: přívod XT, vývody X1 (FVE), XS (spotřeba) a měřicí obvody k RE
    feeds = {e.ref: e.symbol_id for e in rhn.elements if e.symbol_id.startswith("sb.feed")}
    meas = {"XMI": "sb.feed_out", "XMU": "sb.feed_out"} if metering == "nn" else {}
    assert feeds == {"XT": "sb.feed_in", "X1": "sb.feed_out", "X2": "sb.feed_out", **meas}
    # každý přístroj rozvaděče VN patří do pole (kromě přípojnic)
    cells = {e.attrs.get("cell") for e in rvn.elements if e.symbol_id != "sb.busbar"}
    names = {"P1 kabelové pole", "P2 kabelové pole", "P3 transformátorové pole"} if metering == "nn" else {
        "P1 kabelové pole", "P2 kabelové pole", "P3 měřicí pole", "P4 transformátorové pole"}
    assert cells == names
    # všechny části trafostanice nesou její označení
    st = {e.ref: e.attrs.get("station") for e in p.sheets[0].elements if e.attrs.get("station")}
    assert set(st) == {"HR", "TR1", "RVN", "RE"} and set(st.values()) == {"TS1 kiosková trafostanice"}


def test_kobky_and_pole_station():
    p = _vn("nn", station="kobky", ts={"ref": "TS 2", "desc": ""})
    assert any(e.attrs.get("cell") == "K1 kabelová kobka" for e in _board(p, "RVN").elements)
    p = _vn("vn", station="sloup", loop=True)
    assert not any(s.name.startswith("RVN") for s in p.switchboards())      # bez rozvaděče VN
    blk = _syms(p.sheets[0])
    assert {"fve.switch_disconnector_vn", "fve.fuse_vn", "fve.surge_arrester"} <= set(blk)
    assert blk.count("fve.grid") == 1                                       # bez smyčky
    assert "fve.ct" in _syms(_board(p, "HR"))                              # měření na nn


def test_vn_connection_checks_clean(lib):
    noisy = {"wire_overlap", "text_overlap", "free_port", "unconnected", "mp_text_overlap", "calc_cable", "bad_port",
             "dup_ref", "no_ref"}
    for kw in ({"metering": "nn"}, {"metering": "vn"}, {"station": "sloup"}, {"station": "kobky"}):
        p = _vn(**kw)
        re_id = _board(p, "RE").id
        fs = check_project(p, lib)
        # vícepól elektroměru (proud S1/S2 a napětí L1–N do dvou portů jedné značky) zatím popisek kříží žílou
        assert not [f.text for f in fs if f.code in noisy and not (f.code == "mp_text_overlap" and f.sheet_id == re_id)], kw
        assert not [f for f in fs if f.code == "calc_selectivity" and "menší In" in f.text], kw


def test_big_transformer_gets_vn_breaker():
    rvn = _board(_vn("vn", transformer={"sn": 1600}), "RVN")
    qt = [e for e in rvn.elements if e.symbol_id == "fve.breaker_vn"]
    assert len(qt) == 1 and qt[0].attrs["cell"].endswith("transformátorové pole")
    assert "fve.fuse_vn" not in _syms(rvn)


def test_tree_from_vn_bus_to_inverters(lib):
    p = _vn("vn")
    root, nodes = build_tree(p, lib)
    assert root.element.symbol_id == "sb.busbar" and root.sheet.name.startswith("RVN")
    grids = [n for n in nodes.values() if n.element.symbol_id == "fve.grid"]
    assert len(grids) == 2 and all(not g.children and g.parent.element.ref.startswith("XDS") for g in grids)
    path = []
    n = next(k for k in nodes.values() if k.element.ref == "T1")
    while n is not None:
        path.append(n.element.ref or n.element.symbol_id)
        n = n.parent
    path.reverse()
    i = path.index
    assert path[0] == "1" and i("TA1") < i("TR1") < i("XOUT") < i("T1")       # přípojnice VN → měření → TR → RH
    invs = [n for n in nodes.values() if n.element.symbol_id.startswith("fve.inverter")]
    assert len(invs) == 2 and all(not n.children for n in invs)          # DC část se nekreslí
    ta = next(n for n in nodes.values() if n.element.symbol_id == "fve.ct")
    (meter,) = ta.meters
    assert meter.sheet.name.startswith("RE") and meter.station == "TS1 kiosková trafostanice"
    assert {nodes[k].element.symbol_id for k, *_ in meter.links} == {"fve.ct", "fve.vt"}
    # měřicí obvody (vývody XMI/XMU, přívody RE) nejsou ve stromu
    assert not any(n.element.ref in ("XMI", "XMU") for n in nodes.values())
    assert all(n.element.symbol_id not in ("sb.pe_bar", "fve.earth") for n in nodes.values())


def test_meter_on_lv_side_measures_bus(lib):
    _root, nodes = build_tree(_vn("nn"), lib)
    ta = next(n for n in nodes.values() if n.element.symbol_id == "fve.ct")
    (meter,) = ta.meters
    assert {nodes[k].element.symbol_id for k, *_ in meter.links} == {"fve.ct", "sb.busbar"}


def test_tree_with_dc(lib):
    _root, nodes = build_tree(_vn(), lib, dc=True)
    assert sum(n.element.symbol_id == "fve.pv_string" for n in nodes.values()) == 5


def test_terminal_distribution_is_bus(lib):
    p = build_project({"name": "t", "inverters": INVS, "ac": {"distribution": "terminals"}})
    _root, nodes = build_tree(p, lib)
    buses = [n for n in nodes.values() if n.kind == "bus"]
    assert len(buses) == 1 and len(buses[0].children) >= 3      # 2 jističe + SPD (+ hlavní vypínač z druhé strany)


def _inside(a, b):
    return b[0] <= a[0] and a[2] <= b[2] and b[1] <= a[1] and a[3] <= b[3]


def _apart(a, b):
    return a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


@pytest.mark.parametrize(("conn", "paper"), [({}, "A3"), ({"connection": {"level": "vn"}}, "A2"),
                                             ({"connection": {"level": "vn", "station": "sloup"}}, "A2")])
def test_geometry_fits_page(lib, conn, paper):
    from envocad.model.frame import MARGIN
    from envocad.model.single_line import _boxes
    g = single_line_geometry(build_project({"name": "t", "inverters": INVS, **conn}), lib)
    w, h = g.page_size
    assert g.paper == paper
    for x0, y0, x1, y1 in _boxes(g.prims):
        assert MARGIN <= x0 and x1 <= w - MARGIN and MARGIN <= y0 and y1 <= h - MARGIN
    # rámečky rozvaděčů se nepřekrývají, pole leží v rámečku svého rozvaděče a nepřekrývají se
    frames = list(g.frames.values())
    for k, a in enumerate(frames):
        for b in frames[k + 1:]:
            assert _apart(a, b)
    cells = list(g.cells.items())
    for k, ((sid, _n), a) in enumerate(cells):
        assert _inside(a, g.frames[sid])
        for _key, b in cells[k + 1:]:
            assert _apart(a, b)
    texts = {p.text for p in g.prims if p.kind == "text"}
    assert {"RFVE.AC", "T1", "DC: 3 stringy"} <= texts
    if conn:
        assert {"HR", "TR1", "630 kVA", "TS1", "RE"} <= texts
        (box,) = g.stations.values()
        # rozvaděče TS v rámečku TS, rozvaděč FVE mimo
        sheets = {n.sheet.id: n.sheet.name.split()[0] for n in g.nodes.values() if n.sheet.is_switchboard}
        for sid, f in g.frames.items():
            assert _inside(f, box) == (sheets[sid] != "RFVE.AC"), sheets[sid]
        grids = [n for n in g.nodes.values() if n.element.symbol_id == "fve.grid"]
        assert grids and all(_apart((n.x - 1, n.down, n.x + 1, n.y), box) for n in grids)   # DS mimo TS
        assert any(t.startswith("W") and "22-AXEKVCEY" in t for t in texts) == (conn["connection"].get("station")
                                                                                != "sloup")


def test_cells_have_titles_under_bus(lib):
    g = single_line_geometry(_vn("vn"), lib)
    assert [n for (_s, n) in g.cells] == ["P1 kabelové pole", "P2 kabelové pole", "P3 měřicí pole",
                                          "P4 transformátorové pole"]
    texts = {p.text for p in g.prims if p.kind == "text"}
    assert {n for (_s, n) in g.cells} <= texts
    root = g.root
    assert all(box[3] < root.y for (sid, _n), box in g.cells.items() if sid == root.sheet.id
               and _n.startswith(("P1", "P2", "P3")))


def test_manual_offset_moves_subtree_and_keeps_page(lib):
    p = _vn("nn")
    g0 = single_line_geometry(p, lib)
    tr = next(n for n in g0.nodes.values() if n.element.symbol_id == "fve.transformer")
    below = {k: (n.x, n.y) for k, n in g0.nodes.items()}
    tr.element.sl_pos = (25.0, -10.0)
    g1 = single_line_geometry(p, lib)
    sub = set()
    stack = [g1.nodes[tr.key]]
    while stack:
        n = stack.pop()
        sub.add(n.key)
        stack.extend(n.children)
        stack.extend(n.meters)
    for k, n in g1.nodes.items():
        dx, dy = n.x - below[k][0], n.y - below[k][1]
        if k in sub:
            assert (dx, dy) == pytest.approx((25.0, -10.0)), n.element.ref
        else:
            assert (dx, dy) == pytest.approx((0.0, 0.0)), n.element.ref    # strana drží automatické rozmístění
    # náhled tažení: `offsets` nahradí uložené posuny
    g2 = single_line_geometry(p, lib, offsets={})
    assert g2.nodes[tr.key].x == pytest.approx(below[tr.key][0])
    # cíl pro myš: transformátor, jeho rámeček rozvaděče/TS jsou větší
    t = g1.target_at(g1.nodes[tr.key].x, g1.nodes[tr.key].y - 2)
    assert t is not None and t.key == tr.key and t.kind == "node"


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
    assert {"RVN", "TR1", "TA1", "TS1", "P3 měřicí pole"} <= texts
    # rozvaděče RVN, HR, RE, RFVE.AC + 4 pole + trafostanice
    assert len(msp.query('LWPOLYLINE[layer=="ROZVADECE"]')) == 9
