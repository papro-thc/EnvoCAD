"""Export rozložení rozvaděče (`export_layout_dxf`, `layout_geometry`) a plánu svorkovnice (`export_terminal_plan_dxf`)
do DXF (issue #88)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import ezdxf
import pytest

from envocad.export.dxf_export import (
    LAYERS,
    LAYOUT_LAYERS,
    MP_PAGE_GAP,
    TERMINAL_LAYERS,
    export_layout_dxf,
    export_terminal_plan_dxf,
)
from envocad.library.store import LibraryStore
from envocad.library.templates import apply_template
from envocad.model.device_size import device_size
from envocad.model.layout_geometry import layout_geometry
from envocad.model.project import MODULE_WIDTH, Element, Project
from envocad.model.terminal_plan import T_H, T_W, sheet_plan_pages, terminal_plan

# názvy vrstev = klíče slovníků vrstev (hodnoty jsou barva / typ čáry jako u LAYERS a MP_LAYERS)
L_LISTY = "LISTY"
L_MUSTKY = "MUSTKY"
L_NEROZMISTENE = "NEROZMISTENE"
L_PRIPOJENI = "PRIPOJENI"
L_PRISTROJE = "PRISTROJE"
L_RAMECEK = "RAMECEK"
L_SKRIN = "SKRIN"
L_SVORKY = "SVORKY"
L_TEXTY = "TEXTY"

ROOT = Path(__file__).resolve().parents[1]
TOL = 1e-6


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "l.db")


def _ac_terminals():
    p = Project()
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals", "n_out": "9"}, standard_paper="A4")
    return p, sb


def _bbox(poly) -> tuple[float, float, float, float]:
    """(x, y, w, h) LWPOLYLINE."""
    pts = [(p[0], p[1]) for p in poly.get_points()]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _closed(msp, layer):
    return [e for e in msp.query(f'LWPOLYLINE[layer=="{layer}"]') if e.closed]


def _texts(msp, layer):
    return [e.dxf.text for e in msp.query(f'TEXT[layer=="{layer}"]')]


def _close(a, b) -> bool:
    return all(abs(x - y) < TOL for x, y in zip(a, b, strict=True))


# ---- model: layout_geometry -----------------------------------------------------------------------------------
def test_geometry_enclosure_rails_and_ticks(lib):
    p, sb = _ac_terminals()
    lay = sb.layout
    g = layout_geometry(p, sb, lib)
    assert g.enclosure[2:] == pytest.approx(lay.outline_mm)
    assert len(g.rails) == lay.rows
    for _x, _y, w, h in g.rails:
        assert w == pytest.approx(lay.modules_per_row * MODULE_WIDTH)
        assert h == pytest.approx(35)
    assert len(g.ticks) == lay.rows * (lay.modules_per_row + 1)


def test_geometry_device_sizes_follow_device_size_rule(lib):
    p, sb = _ac_terminals()
    g = layout_geometry(p, sb, lib)
    devs = {e.id: e for e in sb.layout.devices(sb, p, lib)}
    assert {d.element_id for d in g.devices} == set(devs)
    for d in g.devices:
        size = device_size(devs[d.element_id], lib)
        w = max(size.width_mm, 1.0) if size.real else max(size.modules, 1.0) * MODULE_WIDTH
        assert d.w == pytest.approx(w)
        assert d.h == pytest.approx(size.height_mm)
        assert d.ref == devs[d.element_id].ref


def test_geometry_placed_positions_and_row_order(lib):
    p, sb = _ac_terminals()
    g = layout_geometry(p, sb, lib)
    ex = g.enclosure[0]
    rails_by_y = sorted(g.rails, key=lambda r: -r[1])      # řada 0 nahoře = nejvyšší y
    placed = [d for d in g.devices if d.placed]
    assert placed
    for d in placed:
        pl = sb.layout.placement(d.element_id)
        rail = rails_by_y[pl.row]
        assert d.x == pytest.approx(rail[0] + pl.pos * MODULE_WIDTH)
        assert d.y + d.h / 2 == pytest.approx(rail[1] + rail[3] / 2)     # svisle na středu lišty
        assert d.x >= ex - TOL
    assert rails_by_y[0][1] > rails_by_y[1][1]


def test_geometry_unplaced_device_is_marked_and_outside(lib):
    p, sb = _ac_terminals()
    eid = sb.layout.devices(sb, p, lib)[0].id
    sb.layout.set_placement(eid, None, None)
    g = layout_geometry(p, sb, lib)
    d = next(d for d in g.devices if d.element_id == eid)
    assert not d.placed
    ex, _ey, ew, _eh = g.enclosure
    assert d.x >= ex + ew - TOL                          # vedle skříně
    assert all(x.placed for x in g.devices if x.element_id != eid)


def test_layout_geometry_is_qt_free(tmp_path):
    code = ("import sys\nimport envocad.model.layout_geometry\n"
            "assert not [m for m in sys.modules if m.startswith('PySide6') and sys.modules[m] is not None]\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT),
                       stdin=subprocess.DEVNULL, timeout=120, check=False)
    assert r.returncode == 0, r.stderr


# ---- export rozložení -----------------------------------------------------------------------------------------
def test_layout_export_appends_extension_and_returns_path(lib, tmp_path):
    p, sb = _ac_terminals()
    out = export_layout_dxf(p, sb, lib, tmp_path / "rozlozeni")
    assert out == tmp_path / "rozlozeni.dxf" and out.exists()


def test_layout_layers_defined():
    for k in ("SKRIN", "LISTY", "PRISTROJE", "NEROZMISTENE", "TEXTY"):
        assert k in LAYOUT_LAYERS


def test_layout_enclosure_polyline(lib, tmp_path):
    p, sb = _ac_terminals()
    msp = ezdxf.readfile(str(export_layout_dxf(p, sb, lib, tmp_path / "l.dxf"))).modelspace()
    polys = list(msp.query(f'LWPOLYLINE[layer=="{L_SKRIN}"]'))
    assert len(polys) == 1 and polys[0].closed
    _x, _y, w, h = _bbox(polys[0])
    assert (w, h) == pytest.approx(sb.layout.outline_mm)


def test_layout_rails_and_ticks(lib, tmp_path):
    p, sb = _ac_terminals()
    lay = sb.layout
    msp = ezdxf.readfile(str(export_layout_dxf(p, sb, lib, tmp_path / "l.dxf"))).modelspace()
    layer = L_LISTY
    rails = _closed(msp, layer)
    assert len(rails) == lay.rows
    for r in rails:
        _x, _y, w, h = _bbox(r)
        assert w == pytest.approx(lay.modules_per_row * MODULE_WIDTH) and h == pytest.approx(35)
    assert len(msp.query(f'LINE[layer=="{layer}"]')) == lay.rows * (lay.modules_per_row + 1)


def _device_rects(msp, layer):
    return [_bbox(e) for e in _closed(msp, layer)]


def test_layout_placed_devices_match_model(lib, tmp_path):
    p, sb = _ac_terminals()
    g = layout_geometry(p, sb, lib)
    msp = ezdxf.readfile(str(export_layout_dxf(p, sb, lib, tmp_path / "l.dxf"))).modelspace()
    rects = _device_rects(msp, L_PRISTROJE)
    placed = [d for d in g.devices if d.placed]
    assert placed
    for d in placed:
        assert any(_close(r, (d.x, d.y, d.w, d.h)) for r in rects), d.ref


def test_layout_placed_devices_inside_enclosure_width(lib, tmp_path):
    p, sb = _ac_terminals()
    g = layout_geometry(p, sb, lib)
    msp = ezdxf.readfile(str(export_layout_dxf(p, sb, lib, tmp_path / "l.dxf"))).modelspace()
    ex, _ey, ew, _eh = g.enclosure
    for x, _y, w, _h in _device_rects(msp, L_PRISTROJE):
        assert x >= ex - TOL and x + w <= ex + ew + TOL


def test_layout_unplaced_device_on_own_layer_dashed(lib, tmp_path):
    p, sb = _ac_terminals()
    eid = sb.layout.devices(sb, p, lib)[0].id
    sb.layout.set_placement(eid, None, None)
    g = layout_geometry(p, sb, lib)
    d = next(d for d in g.devices if d.element_id == eid)
    doc = ezdxf.readfile(str(export_layout_dxf(p, sb, lib, tmp_path / "l.dxf")))
    layer = L_NEROZMISTENE
    rects = _device_rects(doc.modelspace(), layer)
    assert any(_close(r, (d.x, d.y, d.w, d.h)) for r in rects)
    placed_rects = _device_rects(doc.modelspace(), L_PRISTROJE)
    assert not any(_close(r, (d.x, d.y, d.w, d.h)) for r in placed_rects)
    assert doc.layers.get(layer).dxf.linetype.upper() != "CONTINUOUS"      # čárkovaně


def test_layout_texts_have_refs_and_sheet_name(lib, tmp_path):
    p, sb = _ac_terminals()
    msp = ezdxf.readfile(str(export_layout_dxf(p, sb, lib, tmp_path / "l.dxf"))).modelspace()
    texts = _texts(msp, L_TEXTY)
    for e in sb.layout.devices(sb, p, lib):
        assert any(e.ref in t for t in texts), e.ref
    assert any(sb.name in t for t in texts)


# ---- export plánu svorkovnice ---------------------------------------------------------------------------------
def _terminal_setup(lib):
    from envocad.model.project import clean_view
    from envocad.settings import switchboard_paper
    p, sb = _ac_terminals()
    cp, cs = clean_view(p, sb)
    plans = terminal_plan(cp, cs)
    size, pages = sheet_plan_pages(p, sb, plans, standard_paper=switchboard_paper())
    return p, sb, size, pages


@pytest.fixture
def tp(lib, tmp_path):
    p, sb, size, pages = _terminal_setup(lib)
    out = export_terminal_plan_dxf(p, sb, lib, tmp_path / "svorky")
    return ezdxf.readfile(str(out)), size, pages, out


def test_terminal_export_path_and_layers(tp):
    _doc, _size, _pages, out = tp
    assert out.suffix == ".dxf" and out.exists()
    for k in ("SVORKY", "PRIPOJENI", "MUSTKY", "TEXTY"):
        assert k in TERMINAL_LAYERS
    assert "RAMECEK" in LAYERS


def test_terminal_pages_side_by_side_with_layouts(tp):
    doc, size, pages, _out = tp
    assert len(pages) >= 2
    names = [n for n in doc.layouts.names() if n != "Model"]
    assert names == [f"Strana {k + 1}" for k in range(len(pages))]
    assert "Layout1" not in doc.layouts.names()
    xs = sorted({round(_bbox(e)[0] // (size[0] + MP_PAGE_GAP)) for e in
                 _closed(doc.modelspace(), L_SVORKY)})
    assert xs == list(range(len(pages)))


def test_terminal_one_rect_per_terminal(tp):
    doc, _size, pages, _out = tp
    rects = _closed(doc.modelspace(), L_SVORKY)
    assert len(rects) == sum(len(c.rows) for page in pages for c in page)
    for r in rects:
        _x, _y, w, h = _bbox(r)
        assert (w, h) == pytest.approx((T_W, T_H))


def test_terminal_texts_numbers_titles_connections(tp):
    doc, _size, pages, _out = tp
    msp = doc.modelspace()
    texts = _texts(msp, L_TEXTY)
    chunks = [c for page in pages for c in page]
    for c in chunks:
        assert c.title in texts
        for r in c.rows:
            assert r.number in texts
            for t in (r.external, r.internal):
                if t:
                    assert t in texts
    vertical = [e for e in msp.query(f'TEXT[layer=="{L_TEXTY}"]') if abs(e.dxf.rotation - 90) < TOL]
    assert vertical


def test_terminal_connection_lines_per_nonempty_side(tp):
    doc, _size, pages, _out = tp
    expected = sum(bool(r.external or r.ext_cable) + bool(r.internal or r.int_cable)
                   for page in pages for c in page for r in c.rows)
    assert expected > 0
    assert len(doc.modelspace().query(f'LINE[layer=="{L_PRIPOJENI}"]')) == expected


def test_terminal_bridges_and_frame(tp):
    doc, _size, pages, _out = tp
    msp = doc.modelspace()
    groups = 0
    for page in pages:
        for c in page:
            nums = {r.number for r in c.rows}
            groups += sum(len(nums & set(g)) >= 2 for g in c.bridges)
    assert groups > 0
    assert len(msp.query(f'*[layer=="{L_MUSTKY}"]')) >= groups
    assert len(msp.query(f'*[layer=="{L_RAMECEK}"]')) > 0


def test_terminal_bridge_lines_are_continuous(lib, tmp_path):
    """Můstek je plná čára jako v editoru (vrstva MUSTKY je ve vícepólu čárkovaná) – jedna LINE na skupinu."""
    p, sb = _ac_terminals()
    plans = terminal_plan(p, sb)
    from envocad.settings import switchboard_paper
    _size, pages = sheet_plan_pages(p, sb, plans, standard_paper=switchboard_paper())
    groups = sum(1 for page in pages for ch in page for grp in ch.bridges
                 if len({r.number for r in ch.rows} & set(grp)) >= 2)
    msp = ezdxf.readfile(str(export_terminal_plan_dxf(p, sb, lib, tmp_path / "t.dxf"))).modelspace()
    lines = list(msp.query(f'LINE[layer=="{L_MUSTKY}"]'))
    assert groups > 0 and len(lines) == groups
    assert all(ln.dxf.linetype.upper() == "CONTINUOUS" for ln in lines)


def test_layout_unplaced_inner_drawing_is_continuous(lib, tmp_path):
    """Čárkovaný je jen obrys nerozmístěného přístroje; vnitřní kresba (páčky, svorky) je plná jako v editoru."""
    p, sb = _ac_terminals()
    eid = sb.layout.devices(sb, p, lib)[0].id
    sb.layout.set_placement(eid, None, None)
    msp = ezdxf.readfile(str(export_layout_dxf(p, sb, lib, tmp_path / "l.dxf"))).modelspace()
    ents = list(msp.query(f'*[layer=="{L_NEROZMISTENE}"]'))
    assert len(ents) > 1
    assert sum(1 for e in ents if e.dxf.linetype.upper() != "CONTINUOUS") == 1   # jen obrys (BYLAYER = DASHED)
