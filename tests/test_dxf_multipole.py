"""Export vícepólového schématu rozvaděče do DXF (`export_multipole_dxf`) a kreslicí seznam modelu
(`multipole_geometry.Prim`, `MultipoleGeometry.prims`, `multipole.bridge_paths`), ze kterého export kreslí."""
from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

import ezdxf
import pytest

from envocad.export.dxf_export import LINEWEIGHT, MP_LAYERS, MP_PAGE_GAP, export_multipole_dxf
from envocad.generate import build_project
from envocad.library.store import LibraryStore
from envocad.library.templates import apply_template
from envocad.model import multipole as mp
from envocad.model import multipole_geometry as mg
from envocad.model.project import Element, Project

ROOT = Path(__file__).resolve().parents[1]
INV = {"p_ac": 100, "mppt": 6, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "l.db")


def _tpl(tid: str, params: dict):
    p = Project()
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, tid, params, standard_paper="A4")
    return p, sb


def _ac_terminals():
    """AC rozvaděč se svorkami X2 a můstky (5 skupin po 10 svorkách přes 3 strany A4)."""
    return _tpl("ac_fve", {"distribution": "terminals", "n_out": "9"})


def _ac_bus():
    return _tpl("ac_fve", {"distribution": "bus", "n_out": "9"})


def _dc4():
    """DC rozvaděč 4 stringy: 2 strany, přerušení žíly mezi stranami."""
    p = build_project({"name": "DC 4", "inverters": [{"ref": "T1", **INV, "strings": [20] * 4}],
                       "dc": {"route_boxes": 0}})
    return p, p.switchboards()[0]


def _dc9():
    """DC šablona 9 stringů: sběrná čára PE přes 3 strany (tečky odboček, přerušení s odkazy)."""
    return _tpl("dc", {"n_strings": "9"})


CASES = {"ac_svorky": _ac_terminals, "ac_bus": _ac_bus, "dc4": _dc4, "dc9": _dc9}


def _frame(on: bool) -> None:
    from envocad.settings import load_settings, save_settings
    s = load_settings()
    s["frame"] = on
    save_settings(s)


def _placement(e) -> tuple[float, float]:
    return tuple(e.get_placement()[1])[:2]


# ---- model: můstky, šipky, kreslicí seznam --------------------------------------------------------------------
def test_bridge_paths_per_page_and_in_overlap_lines(lib):
    p, sb = _ac_terminals()
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A4")
    assert g.pages >= 2 and g.bridges
    groups = {tuple(gr) for grs in sb.bridges.values() for gr in grs}
    assert {b.group for b in g.bridges} == groups
    assert {b.page for b in g.bridges} == set(range(g.pages))      # můstek přes strany po stranách zvlášť
    for b in g.bridges:
        assert len(b.pts) >= 2 and list(b.pts) == sorted(b.pts)
    # čáry můstků vidí kontrola překryvů (F7)
    bridge_lines = [ln for ln in g.lines if "#bridge" in ln[2]]
    assert len(bridge_lines) == sum(len(b.pts) - 1 for b in g.bridges)
    assert mg.multipole_text_overlaps(p, sb, lib, g, standard_paper="A4") == []


def test_bridge_paths_skips_single_terminal_and_unknown():
    from envocad.model.project import Sheet
    s = Sheet()
    s.bridges = {"X9": [["1", "2"]]}
    assert mp.bridge_paths(s, {}, {}) == []


def test_arrow_helpers():
    assert mg.break_arrow(10, 5, True) == [((10, 5), (7.0, 7.0)), ((10, 5), (7.0, 3.0))]
    assert mg.break_arrow(10, 5, False) == [((10, 5), (13.0, 7.0)), ((10, 5), (13.0, 3.0))]
    arrows = mg.bus_arrows(0.0, 100.0, 50.0)
    assert len(arrows) == 4 and {a for a, _b in arrows} == {(0.0, 50.0), (100.0, 50.0)}
    assert {b[0] for _a, b in arrows} == {2.5, 97.5}
    a, b = mg.title_underline(5.0, 100.0, "R1", 5.0)
    assert a == (5.0, 99.0) and b == pytest.approx((5.0 + 2 * 5.0 * mg.TITLE_UNDERLINE, 99.0))


@pytest.mark.parametrize("case", sorted(CASES))
def test_prims_local_on_their_page(case, lib):
    p, sb = CASES[case]()
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A4")
    w, h = g.page_size
    assert {pr.page for pr in g.prims} == set(range(g.pages))
    assert g.prims and all(0 <= pr.page < g.pages for pr in g.prims)
    for pr in g.prims:
        for x, y in pr.pts:
            assert -1e-6 <= x <= w + 1e-6 and -1e-6 <= y <= h + 1e-6, (case, pr)
    syms = [pr for pr in g.prims if pr.kind == "symbol"]
    assert syms and all(pr.symbol is not None for pr in syms)
    # každý text pro kontrolu překryvů má svůj text v kreslicím seznamu (štítky/značky mají vlastní obálky)
    texts = Counter(pr.text for pr in g.prims if pr.kind == "text")
    for _x, _y, s, _a in g.conductor_labels.values():
        if s:
            assert texts[s] > 0
    assert mg.page_prims(g, 0) == [pr for pr in g.prims if pr.page == 0]


def test_prims_break_and_dots_match_model(lib):
    p, sb = _dc9()
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A4")
    odkazy = {pr.text for pr in g.prims if pr.kind == "text" and pr.layer == "ODKAZY"}
    assert {b[3] for r in g.rails for b in r.breaks} <= odkazy
    dots = [pr for pr in g.prims if pr.kind == "dot" and pr.layer == "SBERNICE"]
    assert len(dots) == sum(len(r.dots) for r in g.rails)


# ---- DXF ------------------------------------------------------------------------------------------------------
def test_dxf_layers_layouts_and_bridges(lib, tmp_path):
    p, sb = _ac_terminals()
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A4")
    out = export_multipole_dxf(p, sb, lib, tmp_path / "mp.dxf")
    assert out == [tmp_path / "mp.dxf"]
    doc = ezdxf.readfile(out[0])
    assert not doc.audit().has_errors
    names = {ly.dxf.name for ly in doc.layers}
    assert {"SYMBOLY", "VODICE", "TEXTY", "RAMECEK", *MP_LAYERS} <= names
    assert doc.layers.get("MUSTKY").dxf.linetype == "DASHED" and doc.layers.get("VAZBY").dxf.linetype == "DASHED"
    paper = [ly for ly in doc.layouts if ly.name != "Model"]
    assert [ly.name for ly in paper] == [f"Strana {k + 1}" for k in range(g.pages)]
    w, h = g.page_size
    for k, ly in enumerate(paper):
        assert (ly.dxf_layout.dxf.paper_width, ly.dxf_layout.dxf.paper_height) == pytest.approx((w, h))
        vp = [e for e in ly if e.dxftype() == "VIEWPORT" and e.dxf.id > 1]
        assert len(vp) == 1
        assert tuple(vp[0].dxf.view_center_point)[:2] == pytest.approx((k * (w + MP_PAGE_GAP) + w / 2, h / 2))
        assert vp[0].dxf.view_height == pytest.approx(h)
    msp = doc.modelspace()
    bridges = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "MUSTKY"]
    assert len(bridges) == sum(len(b.pts) - 1 for b in g.bridges)
    assert all(e.dxf.linetype == "DASHED" for e in bridges)
    dots = [e for e in msp if e.dxftype() == "CIRCLE" and e.dxf.layer == "MUSTKY"]
    assert len(dots) == sum(len(b.pts) for b in g.bridges)
    # vazba pólů čárkovaně, žíly s tloušťkou vodiče
    assert all(e.dxf.linetype == "DASHED" for e in msp if e.dxf.layer == "VAZBY")
    wires = [e for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "VODICE"]
    assert wires and all(e.dxf.lineweight == LINEWEIGHT["wire"] for e in wires)
    texts = {e.dxf.text for e in msp if e.dxftype() == "TEXT"}
    assert {"L1", "L2", "L3", "N", "PE"} <= texts                     # popisky žil
    assert "X2" in texts and {"1", "6", "46"} <= texts                # svorkovnice a čísla svorek
    assert any(t.startswith("R1") and "(1/" in t for t in texts)      # nadpis rozvaděče
    stitky = {e.dxf.text for e in msp if e.dxftype() == "TEXT" and e.dxf.layer == "STITKY"}
    assert {"X1", "od střídače"} <= stitky


@pytest.mark.parametrize("case", sorted(CASES))
def test_dxf_entities_inside_their_page(case, lib, tmp_path):
    p, sb = CASES[case]()
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A4")
    w, h = g.page_size
    doc = ezdxf.readfile(export_multipole_dxf(p, sb, lib, tmp_path / "mp.dxf")[0])
    pitch = w + MP_PAGE_GAP
    seen = set()
    for e in doc.modelspace():
        t = e.dxftype()
        if t == "LINE":
            pts = [tuple(e.dxf.start)[:2], tuple(e.dxf.end)[:2]]
        elif t == "LWPOLYLINE":
            pts = [tuple(q)[:2] for q in e.get_points("xy")]
        elif t == "CIRCLE":
            pts = [tuple(e.dxf.center)[:2]]
        elif t == "TEXT":
            pts = [_placement(e)]
        else:
            continue
        k = int(pts[0][0] // pitch)
        seen.add(k)
        for x, y in pts:
            assert k * pitch - 1e-6 <= x <= k * pitch + w + 1e-6 and -1e-6 <= y <= h + 1e-6, (case, t, x, y)
    assert seen == set(range(g.pages))


def test_dxf_break_refs_and_conductor_labels(lib, tmp_path):
    p, sb = _dc4()
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A4")
    assert g.page_breaks
    doc = ezdxf.readfile(export_multipole_dxf(p, sb, lib, tmp_path / "dc.dxf")[0])
    msp = doc.modelspace()
    odkazy = {e.dxf.text for e in msp if e.dxftype() == "TEXT" and e.dxf.layer == "ODKAZY"}
    refs = {b[3] for v in g.page_breaks.values() for b in v} | {b[3] for r in g.rails for b in r.breaks}
    assert refs and refs <= odkazy and all(r.startswith("/2.") for r in refs)
    # šipka = 2 čáry u každého přerušení
    arrows = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "ODKAZY"]
    n_breaks = sum(len(v) for v in g.page_breaks.values()) + sum(len(r.breaks) for r in g.rails)
    assert len(arrows) == 2 * n_breaks
    texts = {e.dxf.text for e in msp if e.dxftype() == "TEXT"}
    labels = {s for (_x, _y, s, _a) in g.conductor_labels.values() if s}
    assert labels and labels <= texts


def test_dxf_bus_taps_and_refs(lib, tmp_path):
    p, sb = _ac_bus()
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A4")
    doc = ezdxf.readfile(export_multipole_dxf(p, sb, lib, tmp_path / "bus.dxf")[0])
    msp = doc.modelspace()
    dots = [e for e in msp if e.dxftype() == "CIRCLE" and e.dxf.layer == "SBERNICE"]
    assert len(dots) == sum(len(v) for v in g.bus_taps.values()) > 0
    bus = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "SBERNICE"
           and e.dxf.lineweight == LINEWEIGHT["bus"]]
    assert bus
    odkazy = {e.dxf.text for e in msp if e.dxftype() == "TEXT" and e.dxf.layer == "ODKAZY"}
    assert {r[3] for refs in g.bus_refs.values() for r in refs} <= odkazy


def test_dxf_split_pages(lib, tmp_path):
    p, sb = _ac_terminals()
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A4")
    out = export_multipole_dxf(p, sb, lib, tmp_path / "rozvadec.dxf", split_pages=True)
    assert out == [tmp_path / f"rozvadec_s{k + 1}.dxf" for k in range(g.pages)]
    assert not (tmp_path / "rozvadec.dxf").exists()
    w, h = g.page_size
    for k, f in enumerate(out):
        doc = ezdxf.readfile(f)
        msp = doc.modelspace()
        n_prims = len([pr for pr in mg.page_prims(g, k) if pr.kind == "line" and pr.layer == "MUSTKY"])
        assert len([e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "MUSTKY"]) == n_prims
        for e in msp:
            if e.dxftype() == "TEXT":
                x, y = _placement(e)
                assert 0 <= x <= w and 0 <= y <= h


def test_dxf_frame_per_page(lib, tmp_path):
    from envocad.model.frame import page_label
    _frame(True)
    p, sb = _ac_terminals()
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A4")
    doc = ezdxf.readfile(export_multipole_dxf(p, sb, lib, tmp_path / "r.dxf")[0])
    texts = {e.dxf.text for e in doc.modelspace() if e.dxftype() == "TEXT" and e.dxf.layer == "RAMECEK"}
    for k in range(g.pages):
        assert page_label(p, sb, k, g.pages) in texts
    assert "vícepólové schéma" in " ".join(texts)


def test_dxf_export_without_qt(tmp_path):
    """Export vícepólu nepotřebuje PySide6 (model i export jsou bez Qt)."""
    code = f"""
import sys
sys.modules["PySide6"] = None
sys.path.insert(0, {str(ROOT)!r})
from pathlib import Path
from envocad.export.dxf_export import export_multipole_dxf
from envocad.library.store import LibraryStore
from envocad.library.templates import apply_template
from envocad.model.project import Element, Project
p = Project()
blk = Element("fve.switchboard", 120, 150, attrs={{"ref": "R1"}})
p.sheets[0].elements.append(blk)
sb = p.create_switchboard_sheet(blk)
apply_template(p, sb, "ac_fve", {{"distribution": "terminals", "n_out": "9"}}, standard_paper="A4")
out = export_multipole_dxf(p, sb, LibraryStore(Path({str(tmp_path)!r}) / "l.db"), Path({str(tmp_path)!r}) / "x.dxf")
assert not [m for m in sys.modules if m.startswith("PySide6") and sys.modules[m] is not None]
print(len(out))
"""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(tmp_path), stdin=subprocess.DEVNULL,
                       timeout=120, check=False)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "1" and (tmp_path / "x.dxf").exists()


def test_dxf_dangling_wire_is_skipped(lib, tmp_path):
    from envocad.model.project import Wire, WireEnd
    p, sb = _ac_terminals()
    sb.wires.append(Wire(WireEnd("neni", "1"), WireEnd(sb.elements[0].id, "1"), conductors=["L1"]))
    out = export_multipole_dxf(p, sb, lib, tmp_path / "d.dxf")
    assert out[0].exists()


# ---- scéna = model (offscreen) --------------------------------------------------------------------------------
@pytest.fixture
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _scene(p, sb, lib):
    from PySide6.QtGui import QUndoStack

    from envocad.ui.multipole_view import MultipoleScene
    return MultipoleScene(p, sb, lib, QUndoStack())


def test_scene_bridges_and_breaks_from_model(qapp, lib):
    from envocad.ui.multipole_view import BridgeItem, PageBreakItem
    for make in (_ac_terminals, _dc4, _dc9):
        p, sb = make()
        g = mg.multipole_geometry(p, sb, lib, standard_paper="A4")
        sc = _scene(p, sb, lib)
        items = sc.items()
        got = sorted((it.strip, tuple(it.group), tuple(it.points)) for it in items if isinstance(it, BridgeItem))
        assert got == sorted((b.strip, b.group, b.pts) for b in g.bridges)
        breaks = sorted((it.x_, it.y_, it.outgoing, it.text) for it in items if isinstance(it, PageBreakItem))
        expect = sorted([tuple(b) for v in g.page_breaks.values() for b in v] + [tuple(b) for r in g.rails
                                                                                 for b in r.breaks])
        assert breaks == expect
        # šipky ve scéně = šipky v kreslicím seznamu modelu (lokální souřadnice stran)
        pitch = g.page_pitch
        arrows = {(pr.page, pr.pts) for pr in g.prims if pr.kind == "line" and pr.layer == "ODKAZY"}
        for it in items:
            if isinstance(it, PageBreakItem):
                k = max(0, int((g.page_size[1] - it.y_) // pitch))
                for a, b in it.arrow():
                    seg = ((it.x_ + a[0], it.y_ + a[1] + k * pitch), (it.x_ + b[0], it.y_ + b[1] + k * pitch))
                    assert (k, seg) in arrows


def test_gui_export_dxf_from_multipole_tab(qapp, lib, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from envocad.ui.main_window import MainWindow
    p, sb = _ac_terminals()
    w = MainWindow(library=lib, project=p)
    try:
        w.open_sheet(sb, "multipole")
        out = tmp_path / "gui.dxf"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
        monkeypatch.setattr(w, "_ask_multipole_dxf_split", lambda: True)
        w.export_dxf()
        g = mg.multipole_geometry(p, sb, lib, standard_paper="A4")
        assert sorted(tmp_path.glob("gui_s*.dxf")) == [tmp_path / f"gui_s{k + 1}.dxf" for k in range(g.pages)]
        monkeypatch.setattr(w, "_ask_multipole_dxf_split", lambda: None)     # zrušeno: nic se nezapíše
        out.unlink(missing_ok=True)
        w.export_dxf()
        assert not out.exists()
        monkeypatch.setattr(w, "_ask_multipole_dxf_split", lambda: False)
        w.export_dxf()
        assert out.exists() and len([ly for ly in ezdxf.readfile(out).layouts if ly.name != "Model"]) == g.pages
    finally:
        w.undo.setClean()
        w.close()


def _r(pt) -> tuple[float, float]:
    return (round(pt[0], 3), round(pt[1], 3))


def _dedup(pts) -> tuple:
    """Bez opakovaných po sobě jdoucích bodů (QPainterPath nulový úsek vynechá)."""
    out: list = []
    for q in pts:
        if not out or out[-1] != q:
            out.append(q)
    return tuple(out)


def _view_pts(g, pr) -> tuple[tuple[float, float], ...]:
    """Body primitiva v souřadnicích pohledu (strany pod sebou, jako scéna)."""
    return tuple(_r((x, y - pr.page * g.page_pitch)) for x, y in pr.pts)


@pytest.mark.parametrize("case", sorted(CASES))
def test_scene_matches_model_prims(case, qapp, lib):
    """Parita scéna × kreslicí seznam modelu (z něj kreslí DXF): trasy žil, počátky pólů, štítky kabelů, tečky
    sběrnic a sběrných čar a nadpis rozvaděče."""
    from envocad.ui.items import path_points
    from envocad.ui.multipole_view import BusItem, CableTagItem, ConductorItem, PoleItem, RailItem, TitleItem
    p, sb = CASES[case]()
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A4")
    sc = _scene(p, sb, lib)
    items = sc.items()
    # trasy žil: ConductorItem ↔ prims „poly“
    scene_routes = Counter(_dedup(_r(pt) for pt in path_points(it.path()))   # path_points: už mm, Y nahoru
                           for it in items if isinstance(it, ConductorItem))
    model_routes = Counter(_dedup(_view_pts(g, pr)) for pr in g.prims if pr.kind == "poly")
    assert scene_routes and scene_routes == model_routes
    # počátky pólů: PoleItem ↔ prims „symbol“ (společná část značky leží ve stejném počátku)
    poles = {(it.element.id, _r((it.pos().x(), -it.pos().y()))) for it in items if isinstance(it, PoleItem)}
    model_poles = {_view_pts(g, pr)[0] for pr in g.prims if pr.kind == "symbol"}
    assert poles and {pt for _eid, pt in poles} == model_poles
    # štítky kabelů: texty a polohy řádků CableTagItem ↔ prims „text“ ve vrstvě STITKY
    tags = set()
    for it in items:
        if isinstance(it, CableTagItem):
            top = it.y_edge + it.h if it.up else it.y_edge
            for i, t in enumerate(it.rows):
                tags.add((t, _r(((it.x0 + it.x1) / 2, top - (i + 1) * it.ROW + 0.8))))
    model_tags = {(pr.text, _view_pts(g, pr)[0]) for pr in g.prims if pr.kind == "text" and pr.layer == "STITKY"}
    assert tags == model_tags
    # tečky: odbočky sběrnic (BusItem) a sběrných čar (RailItem) ↔ prims „dot“ ve vrstvě SBERNICE
    dots = Counter(_r(pt) for it in items if isinstance(it, BusItem) for pt in it.taps)
    dots += Counter(_r(pt) for it in items if isinstance(it, RailItem) for pt in it.rail.dots)
    model_dots = Counter(_view_pts(g, pr)[0] for pr in g.prims if pr.kind == "dot" and pr.layer == "SBERNICE")
    assert dots == model_dots
    # nadpis: řádky a polohy TitleItem (stejný výpočet jako `TitleItem.paint`) ↔ prims s vlastníkem nadpisu
    titles = set()
    for it in items:
        if isinstance(it, TitleItem):
            y = 0.0
            for i, t in enumerate(it.lines):
                h = 5.0 if i == 0 else 3.0
                y -= h
                titles.add((t, _r((it.pos().x(), -it.pos().y() + y))))
                y -= (2.8 if i == 0 else 0.0) + 1.2
    assert titles
    texts = {(pr.text, _view_pts(g, pr)[0]) for pr in g.prims if pr.kind == "text"}
    assert titles <= texts


def test_prims_of_element_above_top_edge_stay_on_its_page(lib):
    """Prvek s ruční polohou na straně k ≥ 1, jehož port (a začátek žíly) leží nad horní hranou strany: žíla, svorky
    i popisek žíly patří na stranu prvku (`page_of`), ne na stranu k − 1 podle výšky bodu."""
    from envocad.model.project import Wire, WireEnd
    p = Project()
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    q1 = Element("fve.breaker_mcb", 100, 100, rotation=270, attrs={"ref": "Q1"})   # port 1 nahoru
    q2 = Element("fve.breaker_mcb", 160, 100, attrs={"ref": "Q2"})
    q1.mp_pos = q2.mp_pos = (0.0, 0.0)           # ruční polohy určují formát stran (`paper_choice`)
    sb.elements += [q1, q2]
    size = mp.page_size(sb, mp.paper_choice(sb))
    pitch = mp.page_pitch(sb, size)
    top1 = size[1] - pitch                       # horní hrana strany 2 v souřadnicích pohledu
    q1.mp_pos = (100.0, top1 - 1.0)              # počátek těsně pod horní hranou, port 1 nad ní
    q2.mp_pos = (160.0, top1 - 80.0)
    sb.wires.append(Wire(WireEnd(q1.id, "1"), WireEnd(q2.id, "1"), attrs={"ref": "W1"}, conductors=["L1"],
                         terminals={"L1": {"a": "1", "b": "1"}}))
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A4")
    assert g.page_of[q1.id] == g.page_of[q2.id] == 1
    polys = [pr for pr in g.prims if pr.kind == "poly"]
    assert all(pr.page == 1 for pr in polys)
    # předpoklad testu: část žíly je nad horní hranou strany 2 (souřadnice pohledu = lokální − strana × rozteč)
    assert max(y - pitch for pr in polys for _x, y in pr.pts) > top1
    terms = [pr for pr in g.prims if pr.kind == "text" and pr.text == "1"]
    assert terms and all(pr.page == 1 for pr in terms)
    # popisek žíly (vnitřní vodič rozvaděče je bez označení W – `internal_wires`)
    labels = [pr for pr in g.prims if pr.kind == "text" and pr.text and pr.text.strip() == "L1"]
    assert labels and all(pr.page == 1 for pr in labels)


def test_dxf_bridge_dots_continuous_and_suffix(lib, tmp_path):
    """Tečky můstků na čárkované vrstvě MUSTKY mají plný obrys (linetype CONTINUOUS); chybějící přípona „.dxf“ se
    doplní stejně pro jeden soubor i pro soubor na stranu."""
    p, sb = _ac_terminals()
    out = export_multipole_dxf(p, sb, lib, tmp_path / "bez")
    assert out == [tmp_path / "bez.dxf"] and out[0].exists()
    circles = [e for e in ezdxf.readfile(out[0]).modelspace().query("CIRCLE") if e.dxf.layer == "MUSTKY"]
    assert circles and all(e.dxf.linetype == "CONTINUOUS" for e in circles)
    split = export_multipole_dxf(p, sb, lib, tmp_path / "strany", split_pages=True)
    assert split[0] == tmp_path / "strany_s1.dxf" and all(f.exists() for f in split)
    assert export_multipole_dxf(p, sb, lib, tmp_path / "x.DXF") == [tmp_path / "x.DXF"]


def test_export_files_message_plural(qapp):
    from envocad.ui.main_window import export_files_message
    assert export_files_message(["a.dxf"]) == "Exportováno: a.dxf"
    assert export_files_message(["a_s1.dxf", "a_s2.dxf"]) == "Exportováno 2 soubory: a_s1.dxf …"
    assert export_files_message([f"{i}" for i in range(5)]).startswith("Exportováno 5 souborů: ")
