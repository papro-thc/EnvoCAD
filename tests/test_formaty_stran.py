"""Formáty stran: A4…A1 a volný A4 (výška 297, šířka n × 210 podle obsahu) u listu rozvaděče (vícepól) i u ostatních
listů; jednopólový přístroj ve vícepólu jen s jednou fází (žíly, které nikam nevedou, se nekreslí ani nepočítají)."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from envocad.library.store import LibraryStore
from envocad.model import multipole as mp
from envocad.model.frame import (
    MARGIN,
    _fits_unmoved,
    apply_placement,
    sheet_format,
    sheet_format_placement,
    sheet_format_size,
)
from envocad.model.multipole_geometry import multipole_geometry
from envocad.model.project import Element, Project, element_symbol

DATA = Path(__file__).parent / "data" / "vicepol_rfve_rucne.ecp"
EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "ukazka_fve.ecp"


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "l.db")


def _rfve(paper: str, clear: bool = True):
    p = Project.load(DATA)
    sb = next(s for s in p.sheets if s.is_switchboard)
    sb.mp_paper = paper
    if clear:
        for e in sb.elements:
            e.mp_pos = None
    return p, sb


def test_paper_choices():
    assert mp.PAPER_CHOICES == ("A4", "A3", "A2", "A1", mp.FREE_A4)
    for v in ("A2", "A1", mp.FREE_A4, "A4 na výšku"):
        assert mp.normalize_switchboard_paper(v) == v
    assert mp.normalize_switchboard_paper("A0") == "A4"
    assert mp.free_a4_width(1) == 210 and mp.free_a4_width(420) == 420 and mp.free_a4_width(421) == 630
    assert mp.free_a4_label(630) == "A4×3"


def test_free_a4_multipole_one_page_width_by_content(lib):
    p, sb = _rfve(mp.FREE_A4)
    g = multipole_geometry(p, sb, lib, standard_paper="A4")
    w, h = g.page_size
    assert g.pages == 1 and h == 297 and w % 210 == 0 and g.paper == mp.free_a4_label(w)
    assert not g.page_breaks                                       # jedna strana, žádné přerušení
    right = max([b[2] for b, _o, _w in g.texts] + [max(a[0], b[0]) for a, b, _o, _w in g.lines])
    assert right <= w - MARGIN                                     # kresba uvnitř strany
    assert right > w - 210 - MARGIN                                # a strana není zbytečně široká
    assert len(mp_overlaps(p, sb, lib, g)) <= 4


def mp_overlaps(p, sb, lib, g):
    from envocad.model.multipole_geometry import multipole_text_overlaps
    return multipole_text_overlaps(p, sb, lib, g, standard_paper="A4")


@pytest.mark.parametrize("paper,size", [("A2", (594.0, 420.0)), ("A1", (841.0, 594.0))])
def test_large_papers(lib, paper, size):
    p, sb = _rfve(paper)
    g = multipole_geometry(p, sb, lib, standard_paper="A4")
    assert tuple(g.page_size) == size and g.paper == paper
    assert g.pages <= 2


def test_sheet_format_size_fixed_and_free(lib):
    p = Project.load(EXAMPLE)
    s = p.sheets[0]
    assert sheet_format_size(p, s, lib, "A2") == ("A2", 594.0, 420.0)
    name, w, h, dx, dy = sheet_format_placement(p, s, lib, mp.FREE_A4)
    assert h == 297 and w % 210 == 0 and name == mp.free_a4_label(w)
    from envocad.model.textlayout import sheet_content_boxes
    apply_placement(s, (name, w, h, dx, dy))
    boxes = sheet_content_boxes(p, s, lib)
    assert _fits_unmoved(boxes, w, h)                              # po posunu obsah uvnitř rámečku mimo popisové pole
    assert sheet_format_placement(p, s, lib, mp.FREE_A4)[:3] == (name, w, h)   # opakovaná volba stejná
    assert sheet_format(s) == mp.FREE_A4
    s.paper, s.width, s.height = "A3", 420.0, 297.0
    assert sheet_format(s) == "A3"
    s.paper, s.width, s.height = "A0", 1189.0, 841.0
    assert sheet_format(s) == ""
    with pytest.raises(ValueError):
        sheet_format_size(p, s, lib, "A7")


def test_single_pole_device_gets_one_phase(lib):
    p, sb = _rfve("A3")
    poles = mp.sheet_poles(sb, lambda e: element_symbol(p, e, lib))
    by_ref = {e.ref: e for e in sb.elements}
    dead = next(iter(poles.values())).dead
    f2 = by_ref["F2.CCA"].id
    to_f2 = next(w for w in sb.wires if f2 in (w.a.element_id, w.b.element_id) and len(w.conductors) == 5)
    assert dead[to_f2.id] == {"L2", "L3", "N", "PE"}
    assert mp.live_conductors(to_f2, poles) == ["L1"]
    xout = by_ref["XOUT"].id
    to_xout = next(w for w in sb.wires if xout in (w.a.element_id, w.b.element_id))
    assert mp.live_conductors(to_xout, poles) == to_xout.conductors   # vícepólový přístroj beze změny
    assert set(dead) == {to_f2.id}
    # výrobní zapojovací seznam: žíly, které nikam nevedou, se nepočítají
    from envocad.model.wiring import WiringParams, _segments
    from envocad.model.xref import DeviceIndex
    segs = _segments(p, sb, DeviceIndex.build(p), WiringParams.resolve(sb.layout, {}), lib)
    assert sorted(sg.c for sg in segs if sg.w is to_f2) == ["L1"]


def test_branch_conductors_from_junction():
    src = ["L1", "L2", "L3", "N", "PE"]
    assert mp.branch_conductors(src, Element("fve.breaker_mcb", 0, 0, attrs={"poles": "1"})) == ["L1"]
    assert mp.branch_conductors(src, Element("fve.breaker_mcb", 0, 0, attrs={"poles": "3"})) == src
    assert mp.branch_conductors(src, Element("fve.breaker_mcb", 0, 0)) == src            # bez pólů beze změny
    assert mp.branch_conductors(src, Element("sb.terminal_block", 0, 0, attrs={"poles": "1"})) == src
    assert mp.branch_conductors(["L2", "N"], Element("fve.breaker_mcb", 0, 0, attrs={"poles": "1"})) == ["L2"]


def test_sheet_props_dialog_and_undo(lib):
    from PySide6.QtWidgets import QApplication

    from envocad.ui.dialogs import SheetPropsDialog
    from envocad.ui.main_window import MainWindow
    QApplication.instance() or QApplication([])
    p = Project.load(EXAMPLE)
    w = MainWindow(lib, p)
    s = p.sheets[0]
    dlg = SheetPropsDialog(s)
    assert dlg.size is not None and dlg.paper is None
    assert [dlg.size.itemData(i) for i in range(5)] == list(mp.PAPER_CHOICES)
    dlg.size.setCurrentIndex(dlg.size.findData(mp.FREE_A4))
    assert dlg.sheet_format() == mp.FREE_A4
    old = (s.paper, s.width, s.height, [(e.x, e.y) for e in s.elements])
    assert w.set_sheet_props(s, s.name, s.func, s.loc, sheet_format=mp.FREE_A4)
    assert s.height == 297 and s.width % 210 == 0 and s.paper.startswith("A4×")
    w.undo.undo()
    assert (s.paper, s.width, s.height, [(e.x, e.y) for e in s.elements]) == old
    p2 = Project.load(DATA)
    sb = next(x for x in p2.sheets if x.is_switchboard)
    d2 = SheetPropsDialog(sb)
    assert d2.size is None and d2.paper.findData(mp.FREE_A4) >= 0 and d2.paper.findData("A1") >= 0
    w.undo.setClean()
    w.close()
