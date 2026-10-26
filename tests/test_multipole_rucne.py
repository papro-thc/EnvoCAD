"""Automatické rozmístění vícepólu ručně kresleného listu rozvaděče (RFVE – DC stringy, AC přívod přes uzly,
přepínač sítí, cívky, lišty N/PE). Regrese: přístroje v pásu žil, lišty přes sebe, popisky přes cizí čáry."""
from __future__ import annotations

from pathlib import Path

import pytest

from envocad.library.store import LibraryStore
from envocad.model import multipole as mp
from envocad.model import multipole_geometry as mg
from envocad.model.project import Element, Project, Sheet, Wire, element_symbol
from envocad.model.symbol import rotate_dir

FIXTURE = Path(__file__).parent / "data" / "vicepol_rfve_rucne.ecp"


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "l.db")


def _load(paper: str | None = None, clear: bool = False) -> tuple[Project, Sheet]:
    p = Project.load(FIXTURE)
    sb = p.sheets[1]
    assert sb.name.startswith("RFVE")
    if clear:
        for e in sb.elements:
            e.mp_pos = None
    if paper:
        sb.mp_paper = paper
    return p, sb


def _by_id(sb: Sheet, prefix: str) -> str:
    return next(e.id for e in sb.elements if e.id.startswith(prefix))


# horní meze překryvů textů (před opravou 10/2026: 37, 29, 23, 26, 48, 38); A4 se na výšku nevejde ani zhuštěný –
# použije mělčí rozmístění a přerušení na další strany (formáty stran se řeší zvlášť)
LIMITS = [(None, False, 26), (None, True, 11), ("A3", False, 17), ("A3", True, 4),
          ("A4 na výšku", False, 24), ("A4 na výšku", True, 9)]


@pytest.mark.parametrize(("paper", "clear", "limit"), LIMITS)
def test_fixture_text_overlaps_bounded(lib, paper, clear, limit):
    p, sb = _load(paper, clear)
    hits = mg.multipole_text_overlaps(p, sb, lib, standard_paper="A3")
    assert len(hits) <= limit, hits


@pytest.mark.parametrize(("paper", "clear"), [(None, True), ("A3", True), ("A3", False)])
def test_fixture_pe_bars_not_over_each_other(lib, paper, clear):
    """Lišty N (X6) a PE (X7) napájené ze stejného uzlu leží ve stejné řadě vedle sebe, ne přes sebe."""
    p, sb = _load(paper, clear)
    hits = mg.multipole_text_overlaps(p, sb, lib, standard_paper="A3")
    assert not [h for h in hits if "X6" in h[2] and "X7" in h[2]], hits


def test_fixture_device_labels_off_foreign_wires(lib):
    """Popisky přístrojů mimo hlavní tok (F2.CCA, PSU.24, SPD.AC, Q1, F1, KM.N0%) se odsunou z cizích žil."""
    p, sb = _load("A3", clear=True)
    hits = mg.multipole_text_overlaps(p, sb, lib, standard_paper="A3")
    devices = [h for h in hits if h[2].startswith("popisek ") and not h[2].startswith("popisek žíly")]
    assert len(devices) <= 1, devices
    assert not [h for h in devices if any(r in h[2] for r in ("PSU.24", "SPD.AC", "Q1", "KM.N0%", "popisek F1 "))]


def test_fixture_flow_depth_ignores_coils_and_bars(lib):
    """Uzel za F2 odbočkou (8991) je o řadu níž než uzel za F1.STR (ad13): vazba cívky stykače na kontakty ani lišta
    N nezkrátí silový tok (dřív byl 8991 ve stejné řadě jako ad13 a přístroje za ním na další straně)."""
    p, sb = _load("A3", clear=True)
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A3")
    ad13, n8991 = _by_id(sb, "ad13"), _by_id(sb, "8991")
    assert g.page_of[ad13] == g.page_of[n8991]
    assert g.layout_pos[n8991][1] < g.layout_pos[ad13][1]


def test_fixture_junction_in_port_faces_flow(lib):
    """Uzel pod přívodem X1 (vodič do portu S) je ve vícepólu otočený portem S nahoru – žíly do něj vstupují
    shora, ne obloukem zespodu."""
    p, sb = _load("A3", clear=True)
    poles = mp.sheet_poles(sb, lambda e: element_symbol(p, e, lib))
    ep = poles[_by_id(sb, "ca88")]
    assert rotate_dir(ep.symbol.port("S").dir, ep.element.rotation) == "N"
    assert next(e for e in sb.elements if e.id == ep.element.id).rotation == 0   # model beze změny
    # uzel za F1.STR: přívod (W) nahoru, hlavní větev k 8991 (E, víc přístrojů) dolů, odbočka F2.CCA (S) doprava
    ad = poles[_by_id(sb, "ad13")]
    assert [ad.symbol.port(n).dir for n in ("W", "E", "S")] == ["N", "S", "E"]
    # žíly končí ve středu tečky uzlu (ne u portu o 2,5 mm vedle)
    ad.origin = (100.0, 50.0)
    assert {ad.pole_pos(n, "L1") for n in ("W", "E")} == {(100.0, 50.0)}


def test_fixture_ac_branch_top_down(lib):
    """AC větev shora dolů jako DC stringy: X1 → F1.STR → … → KM.N0% → Q1 → F3.FVE → XOUT v jednom sloupci na jedné
    straně (přepínač sítí pod stykačem – soutok pod nejhlubším přívodem), odbočky F2.CCA a SPD.AC vpravo vedle;
    záložní přívod T1 Backup na stejné straně jako přepínač."""
    p, sb = _load("A3", clear=True)
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A3")
    ref = {}
    for e in sb.elements:
        if e.ref and e.symbol_id != "ctl.coil":
            ref[e.ref] = e.id
    col = ["X1", "F1.STR", "KM.N0%", "Q1", "F3.FVE", "XOUT"]
    pages = {g.page_of[ref[r]] for r in col}
    assert len(pages) == 1, pages
    ys = [g.origins[ref[r]][1] for r in col]
    assert ys == sorted(ys, reverse=True), ys
    xs = [g.origins[ref[r]][0] for r in col]
    assert max(xs) - min(xs) <= 20.0, xs
    for side in ("F2.CCA", "SPD.AC"):
        assert g.origins[ref[side]][0] > g.origins[ref["F1.STR"]][0] + 30.0
    assert g.page_of[ref["T1 Backup"]] == g.page_of[ref["Q1"]]


def test_scene_uses_moved_element_labels(lib):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QApplication

    from envocad.ui.multipole_view import MultipoleScene
    QApplication.instance() or QApplication([])
    p, sb = _load("A3", clear=True)
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A3")
    assert g.element_labels
    sc = MultipoleScene(p, sb, lib, QUndoStack())
    assert {eid: ep.label_lines for eid, ep in sc._poles.items() if ep.label_lines is not None} == g.element_labels


# ---- jednotky ---------------------------------------------------------------------------------------------------
def test_is_control_wire():
    w = Wire.__new__(Wire)
    w.a = type("E", (), {"element_id": "a", "port": "A1"})()
    w.b = type("E", (), {"element_id": "b", "port": "1"})()
    assert mp.is_control_wire(w)
    w.a.port = "2"
    assert not mp.is_control_wire(w)


def test_bfs_depth_seed_keeps_known_depths():
    adj = {"s": {"a"}, "a": {"s", "b"}, "b": {"a", "c"}, "c": {"b"}}
    assert mp._bfs_depth({"s"}, adj, {}) == {"s": 0, "a": 1, "b": 2, "c": 3}
    # známé hloubky (silový tok) zůstanou, zbytek se dopočte od nich
    assert mp._bfs_depth({"s"}, adj, {"s": 0, "b": 5}) == {"s": 0, "b": 5, "a": 1, "c": 6}


def test_clear_of_bars_shifts_second_bar(lib):
    sym = lib.get_symbol("sb.pe_bar")
    ep = mp.ElementPoles(Element(symbol_id="sb.pe_bar", x=0, y=0), sym, ["PE"], [], [], None)
    spans: list[tuple[float, float]] = []
    a = mp._clear_of_bars(ep, 100.0, spans, horizontal=False)
    b = mp._clear_of_bars(ep, 100.0, spans, horizontal=False)
    assert a == 100.0 and b > a
    assert spans[0][1] + mp.BAR_CLEAR <= spans[1][0] + 1e-6
    assert b % mp.GRID == 0


def test_pole_label_lines_uses_override(lib):
    sym = lib.get_symbol("fve.breaker_mcb")
    ep = mp.ElementPoles(Element(symbol_id="fve.breaker_mcb", x=0, y=0, attrs={"ref": "F9"}), sym, ["L1"], [], [], None)
    ep.origin = (50.0, 60.0)
    assert ep.label_lines is None and mp.pole_label_lines(ep) == mp.default_label_lines(ep)
    ep.label_lines = [(2.0, -3.0, "F9", 2.5, "left")]
    assert mp.pole_label_lines(ep) == [(52.0, 57.0, "F9", 2.5, "left")]


def test_fixture_dc_string_straight_down_spd_beside(lib):
    """DC string X2 → FU1.1 → X4 je jedna svislá linie (vývod přímo pod odpínačem), přepěťová ochrana SPD-DC
    (odbočka ze svorek odpínače) stojí bokem vpravo, ne v cestě stringu."""
    p, sb = _load("A3", clear=True)
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A3")
    ref = {e.ref: e.id for e in sb.elements if e.ref}
    for src, fu, out, spd in (("X2", "FU1.1", "X4", "SPD-DC1.1"), ("X3", "FU1.2", "X5", "SPD-DC1.2")):
        xs = {r: g.origins[ref[r]][0] for r in (src, fu, out, spd)}
        assert xs[src] == xs[fu] == xs[out], xs
        assert xs[spd] > xs[fu] + 15.0, xs


def test_scene_pages_are_separate_papers(lib):
    """Strany vícepólu ve scéně jako samostatné papíry: mezera mezi stranami bez mřížky (jiná barva než papír)
    a obrys strany i bez rámečku."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter, QUndoStack
    from PySide6.QtWidgets import QApplication

    from envocad.ui.multipole_view import MultipoleScene
    QApplication.instance() or QApplication([])
    p, sb = _load("A3", clear=True)
    sc = MultipoleScene(p, sb, lib, QUndoStack())
    assert len(sc.pages) == 2
    gap_y = (sc.pages[0].bottom() + sc.pages[1].top()) / 2
    r = QRectF(0, sc.pages[0].top(), sc.paper_size[0], sc.pages[1].bottom() - sc.pages[0].top())
    img = QImage(int(r.width()), int(r.height()), QImage.Format_RGB32)
    pa = QPainter(img)
    sc.render(pa, QRectF(img.rect()), r, Qt.IgnoreAspectRatio)
    pa.end()
    sy = img.height() / r.height()
    desk = img.pixelColor(int(r.width() / 2), int((gap_y - r.top()) * sy))
    paper = img.pixelColor(int(r.width() / 2) + 1, int((sc.pages[0].top() + 150.7 - r.top()) * sy))
    assert desk != paper
    # tisk (export): jen bílá, bez obrysů a mřížky
    sc.draw_grid = False
    img.fill(0)
    pa = QPainter(img)
    sc.render(pa, QRectF(img.rect()), r, Qt.IgnoreAspectRatio)
    pa.end()
    assert img.pixelColor(int(r.width() / 2), int((gap_y - r.top()) * sy)).lightness() == 255


@pytest.mark.parametrize(("paper", "clear"), [(None, False), (None, True), ("A3", True)])
def test_fixture_bars_stay_on_page(lib, paper, clear):
    """Řada lišt pod vývody na nízké straně (A4, kresba se nevejde ani po zhuštění) neskončí pod okrajem strany –
    zvedne se nad popisové pole a vyhne se přístrojům své řady."""
    from envocad.model.frame import MARGIN, TB_H
    p, sb = _load(paper, clear)
    g = mg.multipole_geometry(p, sb, lib, standard_paper="A3")
    for e in sb.elements:
        if e.symbol_id == "sb.pe_bar":
            local = g.origins[e.id][1] + g.page_of[e.id] * g.page_pitch
            assert MARGIN + TB_H < local < g.page_size[1], (e.ref, local)
    hits = mg.multipole_text_overlaps(p, sb, lib, standard_paper="A3")
    assert not [h for h in hits if ("X6" in h[2] or "X7" in h[2]) and "značk" in h[2]], hits
