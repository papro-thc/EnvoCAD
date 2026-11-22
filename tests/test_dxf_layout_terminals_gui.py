"""GUI export DXF rozložení rozvaděče a plánu svorkovnice (issue #88): offscreen."""
from __future__ import annotations

import ezdxf
import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from envocad.library.store import LibraryStore
from envocad.library.templates import apply_template
from envocad.model.project import Element, Project
from envocad.ui.main_window import MainWindow


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "l.db")


def _project():
    p = Project()
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals", "n_out": "9"}, standard_paper="A4")
    return p, sb


def _layers(path):
    return {e.dxf.layer for e in ezdxf.readfile(str(path)).modelspace()}


def test_menu_has_dxf_layout_and_terminal_items(qapp, lib):
    w = MainWindow(library=lib, project=_project()[0])
    try:
        assert "export_layout_dxf" in w.actions and "export_terminal_plan_dxf" in w.actions
        titles = [a.text() for a in w.menuBar().actions()[0].menu().actions()]
        i = titles.index("Export &DXF…")
        assert titles[i + 1:i + 3] == ["Export DXF rozložení rozvaděče…", "Export DXF plánu svorkovnice…"]
    finally:
        w.undo.setClean()
        w.close()


@pytest.mark.parametrize(("kind", "expected"), [("layout", "SKRIN"), ("terminals", "SVORKY")])
def test_export_dxf_from_view(qapp, lib, tmp_path, monkeypatch, kind, expected):
    p, sb = _project()
    w = MainWindow(library=lib, project=p)
    try:
        w.open_sheet(sb, kind)
        out = tmp_path / f"{kind}.dxf"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
        w.export_dxf()
        assert out.exists() and expected in _layers(out)
    finally:
        w.undo.setClean()
        w.close()


def test_menu_exports_from_other_view_of_same_sheet(qapp, lib, tmp_path, monkeypatch):
    p, sb = _project()
    w = MainWindow(library=lib, project=p)
    try:
        w.open_sheet(sb, "multipole")
        a, b = tmp_path / "a.dxf", tmp_path / "b.dxf"
        for fn, out, layer in ((w.export_layout_dxf, a, "SKRIN"), (w.export_terminal_plan_dxf, b, "SVORKY")):
            monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, o=out, **k: (str(o), "")))
            fn()
            assert out.exists() and layer in _layers(out)
    finally:
        w.undo.setClean()
        w.close()


def test_menu_export_without_switchboard_sheet_informs(qapp, lib, tmp_path, monkeypatch):
    msgs = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: msgs.append(a[1:3])))
    out = tmp_path / "x.dxf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    w = MainWindow(library=lib, project=Project())
    try:
        w.export_layout_dxf()
        w.export_terminal_plan_dxf()
        assert len(msgs) == 2 and not out.exists()
    finally:
        w.undo.setClean()
        w.close()


def test_layout_scene_matches_model_geometry(qapp, lib):
    """Editor rozložení a `layout_geometry` (zdroj DXF) dávají stejné obrysy – skříň i každý přístroj (rozmístěný
    i nerozmístěný); model má Y nahoru, scéna Y dolů."""
    from PySide6.QtGui import QUndoStack

    from envocad.model.layout_geometry import layout_geometry
    from envocad.ui.layout_view import LayoutScene
    p, sb = _project()
    devs = sb.layout.devices(sb, p, lib)
    for e in devs[:2]:
        sb.layout.set_placement(e.id, None, None)
    scene = LayoutScene(p, sb, lib, QUndoStack())
    g = layout_geometry(p, sb, lib)
    r = scene._encl_rect
    assert g.enclosure == pytest.approx((r.left(), -r.bottom(), r.width(), r.height()))
    assert {d.element_id for d in g.devices} == set(scene.items_by_id)
    for d in g.devices:
        it = scene.items_by_id[d.element_id]
        w, h = it.rect().width(), it.rect().height()
        assert (d.x, d.y, d.w, d.h) == pytest.approx((it.pos().x(), -(it.pos().y() + h), w, h)), d.ref
        assert d.placed == it.placed
