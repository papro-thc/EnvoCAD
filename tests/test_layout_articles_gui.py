"""Rozložení rozvaděče s artikly (offscreen): 3VA jako obdélník š × v, MCB z artiklu, svorkovnice podle šířky svorky;
projekt bez artiklů se kreslí jako dřív. Volitelně uloží snímek (`ENVOCAD_LAYOUT_SNAPSHOT=<složka>`)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QUndoStack

from envocad.library.store import LibraryStore
from envocad.model.project import (
    DEVICE_HEIGHT_MM,
    MODULE_WIDTH,
    Element,
    Layout,
    Project,
    Sheet,
)

VA, MCB, RCD, TERM = "oez-3va1163-3ef36-0aa0", "hager-mbn116", "hager-cda440d", "weidmuller-1552790000"


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "lib.db")


def board(lib, with_articles: bool = True) -> tuple[Project, Sheet]:
    s = Sheet(name="RFVE.AC", kind="switchboard")
    s.layout = Layout(rows=3, modules_per_row=24,
                      params={"width_mm": "550", "height_mm": "700", "depth_mm": "150", "row_pitch_mm": "200"})
    q1 = Element("fve.breaker_mccb", attrs={"ref": "Q1", "modules": "6", "in_": "63", "poles": "3"})
    fs = [Element("fve.breaker_mcb", attrs={"ref": f"F{i}", "modules": "1", "in_": "16", "char": "B", "poles": "1"})
          for i in (1, 2, 3)]
    x1 = Element("sb.terminal_block", attrs={"ref": "X1", "terminal": "1 2 3 4 5 6 7 8"})
    if with_articles:
        for e, cid in ((q1, VA), (fs[0], MCB), (fs[1], MCB), (fs[2], MCB), (x1, TERM)):
            c = lib.component(cid)
            assert c is not None, cid
            c.apply_to(e)
    s.elements = [q1, *fs, x1]
    s.layout.set_placement(q1.id, 0, 0)
    for i, f in enumerate(fs):
        s.layout.set_placement(f.id, 1, i)
    s.layout.set_placement(x1.id, 2, 0)
    return Project(name="Rozložení z artiklů", sheets=[s]), s


def render(scene, path: Path) -> None:
    r = scene.sceneRect()
    img = QImage(int(r.width() * 4), int(r.height() * 4), QImage.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    scene.render(p, QRectF(0, 0, img.width(), img.height()), r, Qt.KeepAspectRatio)
    p.end()
    assert img.save(str(path))


def test_layout_scene_sizes_from_articles(lib, tmp_path):
    from envocad.ui.layout_view import LayoutScene
    p, s = board(lib)
    sc = LayoutScene(p, s, lib, QUndoStack())
    by_ref = {it.element.ref: it for it in sc.items_by_id.values()}
    q1, f1, x1 = by_ref["Q1"], by_ref["F1"], by_ref["X1"]
    q1.setSelected(True)
    assert q1.isSelected() and q1.flags() & q1.GraphicsItemFlag.ItemIsMovable    # přetahování a výběr fungují
    assert (q1.rect().width(), q1.rect().height()) == (76.2, 130.0)
    assert q1.size_label() == "76,2 × 130 mm"
    assert (f1.rect().width(), f1.rect().height()) == (MODULE_WIDTH, 83.0)
    assert x1.rect().width() == pytest.approx(8 * 3.5) and x1.size_label() == "8 × 3,5 mm"
    # svisle na střed osy řady
    for it, row in ((q1, 0), (f1, 1), (x1, 2)):
        assert it.pos().y() + it.rect().height() / 2 == pytest.approx(sc.axis_y(row))
    # tažení: přístroj vyšší než 45 mm se vrátí na stejné místo (střed podle vlastní výšky)
    assert sc.scene_to_placement(q1.pos(), q1.modules, q1.rect().height()) == (0, 0.0)
    out = Path(os.environ.get("ENVOCAD_LAYOUT_SNAPSHOT") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    render(sc, out / "rozlozeni_artikly.png")
    assert (out / "rozlozeni_artikly.png").stat().st_size > 1000


def test_layout_scene_without_articles_unchanged(lib, tmp_path):
    """Bez artiklů: šířka z modulů (nejméně 1 M), výška 45 mm, horní hrana na `rail_y` jako dřív."""
    from envocad.ui.layout_view import LayoutScene
    p, s = board(lib, with_articles=False)
    sc = LayoutScene(p, s, lib, QUndoStack())
    by_ref = {it.element.ref: it for it in sc.items_by_id.values()}
    assert (by_ref["Q1"].rect().width(), by_ref["Q1"].rect().height()) == (6 * MODULE_WIDTH, DEVICE_HEIGHT_MM)
    x1 = by_ref["X1"]
    assert x1.rect().width() == pytest.approx(max(x1.element.modules, 1.0) * MODULE_WIDTH)
    assert x1.size_label() == f"{x1.element.modules:g} M"
    for ref, row in (("Q1", 0), ("F1", 1), ("X1", 2)):
        assert by_ref[ref].pos().y() == pytest.approx(sc.rail_y(row))
    out = Path(os.environ.get("ENVOCAD_LAYOUT_SNAPSHOT") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    render(sc, out / "rozlozeni_bez_artiklu.png")


def test_layout_pdf_and_enclosure_panel_with_articles(lib, tmp_path):
    """PDF rozložení s artikly se vytvoří; panel skříně ukáže zdroj ztrát a varování rozměrů."""
    from envocad.export.pdf_export import export_layout_pdf
    from envocad.ui.dialogs import EnclosurePanel
    from envocad.ui.layout_view import LayoutScene
    p, s = board(lib)
    s.layout.params["row_pitch_mm"] = "120"      # 3VA 130 mm > rozteč 120 mm
    s.layout.params["depth_mm"] = "80"           # 3VA hloubka 88 mm > 80 mm
    sc = LayoutScene(p, s, lib, QUndoStack())
    export_layout_pdf(sc, tmp_path / "r.pdf")
    assert (tmp_path / "r.pdf").stat().st_size > 1000
    panel = EnclosurePanel(s, library=lib, project=p)
    panel.refresh()
    assert "vyšší než rozteč řad" in panel.warning.text() and "hlubší než skříň" in panel.warning.text()
    assert "artikl" in panel.thermal.text() and "odhad" in panel.thermal.text()


def _window(lib):
    from envocad.ui.main_window import MainWindow
    p, s = board(lib)
    win = MainWindow(lib, p)
    win.open_sheet(s, "schematic")
    win.show()
    return win, p, s


def _pump(n=6):
    from PySide6.QtWidgets import QApplication
    for _ in range(n):
        QApplication.processEvents()


def test_panel_size_fields_and_bridge_choice(lib):
    """Panel Vlastnosti na listu rozvaděče: pole rozměrů zapisují přes undo, nabídka můstků z katalogu."""
    from PySide6.QtWidgets import QLineEdit

    from envocad.ui.dialogs import ChoiceEdit
    win, _p, s = _window(lib)
    q1 = next(e for e in s.elements if e.ref == "Q1")
    win.scene.clearSelection()
    win.scene.element_items[q1.id].setSelected(True)
    _pump()
    width = next(f for f in win.props_panel.findChildren(QLineEdit) if f.placeholderText().startswith("76,2"))
    assert "(artikl)" in width.placeholderText()
    width.setText("90")
    width.editingFinished.emit()
    _pump()
    assert q1.attrs["width_mm"] == "90"
    win.undo.undo()
    assert not q1.attrs.get("width_mm")
    # svorkovnice: výběr můstku z kandidátů (Weidmüller)
    x1 = next(e for e in s.elements if e.ref == "X1")
    win.scene.clearSelection()
    win.scene.element_items[x1.id].setSelected(True)
    _pump()
    combo = next(c for c in win.props_panel.findChildren(ChoiceEdit))
    ids = [combo.itemData(i) for i in range(combo.count())]
    assert ids[0] == "" and "weidmuller-1527540000" in ids
    assert all(lib.component(i).manufacturer == "Weidmüller" for i in ids[1:])
    combo.setCurrentIndex(ids.index("weidmuller-1527540000"))
    _pump()
    assert x1.attrs["bridge_id"] == "weidmuller-1527540000"
    win.undo.setClean()
    win.close()


def test_component_change_clears_manual_sizes(lib, monkeypatch):
    """Změna artiklu v dialogu prvku vymaže ruční rozměry v témže kroku undo."""
    from envocad.model.device_size import size_resets_for_component
    from envocad.ui import dialogs
    win, _p, s = _window(lib)
    f1 = next(e for e in s.elements if e.ref == "F1")
    f1.attrs.update({"width_mm": "20", "depth_mm": "75"})
    assert size_resets_for_component(f1, f1.component_id) == {}

    class FakeDialog:
        Accepted = 1
        wire_combo = None

        def __init__(self, sym, attrs, *a, **k):
            self.attrs, self.component_id = dict(attrs), "hager-mbn110"

        def exec(self):
            return 1

        def values(self):
            return dict(self.attrs)
    monkeypatch.setattr(dialogs, "ElementDialog", FakeDialog)
    n = win.undo.count()
    win.scene.edit_element(f1.id)
    assert f1.component_id == "hager-mbn110" and not f1.attrs.get("width_mm") and not f1.attrs.get("depth_mm")
    assert win.undo.count() == n + 1
    win.undo.undo()
    assert f1.component_id == "hager-mbn116" and f1.attrs["width_mm"] == "20" and f1.attrs["depth_mm"] == "75"
    win.undo.setClean()
    win.close()
