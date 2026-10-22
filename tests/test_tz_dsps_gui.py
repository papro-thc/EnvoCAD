"""GUI exportu TZ / DSPS (Výstupy → Technická zpráva… / DSPS…): dialog šablony, údaje DSPS přes undo, .docx."""
from __future__ import annotations

import copy
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docx import Document
from PySide6.QtWidgets import QApplication, QFileDialog

from envocad.generate import build_project
from envocad.library import doc_templates
from envocad.library.store import LibraryStore
from envocad.ui.doc_template_dialog import OTHER, DocExportDialog
from envocad.ui.main_window import MainWindow

INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, tmp_path):
    p = build_project({"name": "FVE GUI", "inverters": [{"ref": "T1", **INV, "strings": [20, 20]}]})
    w = MainWindow(library=LibraryStore(tmp_path / "lib.db"), project=p)
    yield w, p
    w.undo.setClean()
    w.close()


def _text(path) -> str:
    d = Document(str(path))
    return "\n".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells])


def test_dialog_lists_templates_and_defaults(app, win):
    _w, p = win
    dlg = DocExportDialog(p, "tz")
    items = [dlg.template.itemData(i) for i in range(dlg.template.count())]
    assert str(doc_templates.builtin_template("tz")) in items and items[-1] == OTHER
    assert str(doc_templates.builtin_template("dsps")) not in items
    assert dlg.template_path() is None                   # vestavěná → export ji vezme sám
    assert dlg.meta_edits == {} and dlg.meta_updates() == {}
    d2 = DocExportDialog(p, "dsps")
    assert set(d2.meta_edits) == {"dsps_date", "dsps_inspection_report", "dsps_contractor"}
    d2.meta_edits["dsps_date"].setText("1.11.2026")
    assert d2.meta_updates() == {"dsps_date": "1.11.2026"} and d2.fields()["dsps_date"] == "1.11.2026"


def test_export_tz_from_menu(win, tmp_path, monkeypatch):
    w, _p = win
    out = tmp_path / "tz.docx"
    monkeypatch.setattr(DocExportDialog, "exec", lambda self: DocExportDialog.Accepted)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    labels = [a.text() for m in w.menuBar().findChildren(type(w.menuBar().actions()[0].menu())) for a in m.actions()]
    assert "Technická zpráva (docx)…" in labels and "Dokumentace skutečného provedení – DSPS (docx)…" in labels
    w.export_tz()
    assert "Technická zpráva – FVE GUI" in _text(out)
    assert not w.undo.count()                            # TZ projekt nemění


def test_export_dsps_records_meta_with_undo(win, tmp_path, monkeypatch):
    w, p = win
    design = copy.deepcopy(p)
    design.save(tmp_path / "pd.ecp")
    spd = next(e for s in p.sheets for e in s.elements if e.symbol_id == "fve.spd")
    spd.attrs["type"] = "DEHNcube YPV 1000"
    out = tmp_path / "dsps.docx"

    def accept(self):
        self.old_path.setText(str(tmp_path / "pd.ecp"))
        self.meta_edits["dsps_date"].setText("2.11.2026")
        return DocExportDialog.Accepted

    monkeypatch.setattr(DocExportDialog, "exec", accept)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    w.export_dsps()
    text = _text(out)
    assert "Datum provedení: 2.11.2026" in text and "DEHNcube YPV 1000" in text and "1 změněno" in text
    assert p.meta["dsps_date"] == "2.11.2026" and w.undo.count() == 1
    w.undo.undo()
    assert "dsps_date" not in p.meta


def test_export_dsps_bad_old_project_warns(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    w, _p = win
    (tmp_path / "zly.ecp").write_text("není json", encoding="utf-8")
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))

    def accept(self):
        self.old_path.setText(str(tmp_path / "zly.ecp"))
        return DocExportDialog.Accepted

    monkeypatch.setattr(DocExportDialog, "exec", accept)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: pytest.fail("nemá se ptát")))
    w.export_dsps()
    assert warned and "nejde načíst" in warned[0] and not w.undo.count()
