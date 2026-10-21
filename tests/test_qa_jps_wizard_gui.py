"""Regrese z QA auditu JPS / průvodce (skupina D) – GUI části: validace průvodce, dialog makra (navazující číslování,
hvězdička u počtu, skrytá prázdná skupina), přejmenování a smazání bloku rozvaděče jedním krokem undo, popisky žil
a příčka PE ve vícepólu, české hlášky importérů QET/EPLAN."""
import json
import os
from itertools import pairwise

import pytest

pytestmark = pytest.mark.usefixtures("ac_builtin")   # AC listy vestavěným kódem (standard `ac_builtin`)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QLabel, QMessageBox

from envocad.generate import build_project
from envocad.library.store import LibraryStore
from envocad.model.feed import is_feed_in
from envocad.model.project import Project
from envocad.ui.main_window import MainWindow

INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def lib(tmp_path):
    return LibraryStore(tmp_path / "lib.db")


@pytest.fixture
def warned(monkeypatch):
    seen: list[str] = []
    for kind in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda *a, **k: seen.append(a[2]) or QMessageBox.Ok))
    return seen


def spec(n=1, per=4, **kw):
    s = {"inverters": [{"ref": f"T{i + 1}", **INV, "strings": [20] * per} for i in range(n)]}
    s.update(kw)
    return s


def _state(p: Project) -> str:
    return json.dumps(p.to_dict(), sort_keys=True, ensure_ascii=False)


def _win(lib, p):
    w = MainWindow(library=lib, project=p)
    w.show()
    w.undo.setClean()
    return w


def _done(w):
    w.undo.setClean()
    w.close()


# ---- 3. průvodce ----------------------------------------------------------------------------------------------
def test_wizard_invalid_input_keeps_dialog_open(app, warned):
    from envocad.ui.dialogs import ProjectWizard
    d = ProjectWizard()
    d.show()
    d.strings.setText("20, 20 abc")
    d.mod_p.setText("")
    d.dc_route_boxes.setText("2.5")
    d.accept()
    assert d.result() != QDialog.Accepted and d.isVisible()
    msg = warned[-1]
    assert "Stringy" in msg and "P modulu" in msg and "Počet DC rozvaděčů po trase" in msg
    with pytest.raises(ValueError):
        d.spec()
    # mezery i čárky jako oddělovač, desetinná čárka u P modulu → projde
    d.strings.setText("20 20 18; 20,20")
    d.mod_p.setText("450,5")
    d.dc_route_boxes.setText("1")
    assert d.errors() == []
    sp = d.spec()
    assert [i["strings"] for i in sp["inverters"]] == [[20, 20, 18], [20, 20]] and sp["module"]["p_wp"] == 450.5
    d.accept()
    assert d.result() == QDialog.Accepted
    build_project(sp)


# ---- 5., 21. dialog makra -------------------------------------------------------------------------------------
def test_macro_dialog_prefills_next_free_numbers(app, lib):
    from envocad.library.macros import K_START, find_macro
    from envocad.ui.dialogs import MacroValuesDialog
    p = build_project(spec(1, 4))
    rdc = next(s for s in p.sheets if s.name.startswith("RFVE.DC"))
    dc = find_macro("DC string v rozvaděči")
    d = MacroValuesDialog(dc, lib, project=p, sheet=rdc)
    assert d.k_start is not None and d.k_start.text() == "9" and d.extra.isChecked()
    vals = d.values()
    assert not d.errors and vals[K_START] == "9"
    # počet opakování má hvězdičku (povinný)
    labels = [lb.text() for lb in d.findChildren(QLabel)]
    assert "Počet stringů *" in labels
    d.k_start.setText("0")
    d.values()
    assert any("Číslovat od" in e for e in d.errors)
    # AC přívod do RFVE.AC s X1 → k = 2, střídač T2
    ac = find_macro("AC přívod střídače")
    d = MacroValuesDialog(ac, lib, project=p, sheet=next(s for s in p.switchboards() if s.loc == "RFVE.AC"))
    vals = d.values()
    assert not d.errors and vals["k"] == "2" and vals["inverter"] == "T2"
    # bez listu se nic nepředvyplňuje (výchozí k = 1)
    assert MacroValuesDialog(ac, lib).values()["k"] == "1"


def test_macro_dialog_hides_group_without_editable_fields(app, lib, tmp_path):
    from envocad.library.macros import load_macro
    from envocad.ui.dialogs import MacroValuesDialog
    path = tmp_path / "m.json"
    path.write_text(json.dumps({
        "version": 2, "name": "Bez čísel",
        "variables": [{"name": "in_", "type": "number", "default": "16", "required": True},
                      {"name": "nk", "type": "number", "auto": True}],
        "repeat": None,
        "fragment": {"elements": [{"id": "a", "symbol_id": "fve.breaker_mcb", "x": 0, "y": 0,
                                   "attrs": {"ref": "F1", "in_": "{in_}"}}], "wires": []}}), encoding="utf-8")
    m = load_macro(path)
    d = MacroValuesDialog(m, lib)
    assert d.extra is not None   # nk je bez opakování editovatelné
    path.write_text(json.dumps({
        "version": 2, "name": "Opakování", "repeat": {"count": "n"},
        "variables": [{"name": "n", "type": "number", "default": "2"}, {"name": "k", "type": "number", "auto": True}],
        "fragment": {"elements": [{"id": "a", "symbol_id": "fve.breaker_mcb", "x": 0, "y": 0,
                                   "attrs": {"ref": "F{k}"}}], "wires": []}}), encoding="utf-8")
    d = MacroValuesDialog(load_macro(path), lib)
    assert d.extra is not None and d.k_start is not None   # jediné editovatelné pole: Číslovat od (k)
    path.write_text(json.dumps({
        "version": 2, "name": "Jen povinné",
        "variables": [{"name": "in_", "type": "number", "default": "16", "required": True}],
        "fragment": {"elements": [{"id": "a", "symbol_id": "fve.breaker_mcb", "x": 0, "y": 0,
                                   "attrs": {"ref": "F1"}}], "wires": []}}), encoding="utf-8")
    assert MacroValuesDialog(load_macro(path), lib).extra is None   # prázdná skupina se neukazuje


def test_insert_macro_continues_numbering_in_switchboard(app, lib, monkeypatch):
    """Vložení makra „DC string v rozvaděči“ z knihovny do existujícího DC rozvaděče: X9… bez duplicit."""
    from envocad.library.macros import find_macro
    from envocad.model.checks import check_project
    from envocad.ui import dialogs
    p = build_project(spec(1, 4))
    w = _win(lib, p)
    rdc = next(s for s in p.sheets if s.name.startswith("RFVE.DC"))
    w.open_sheet(rdc, "schematic")
    real = dialogs.MacroValuesDialog

    class Auto(real):
        def exec(self):
            self.accept()
            return self.result()
    monkeypatch.setattr(dialogs, "MacroValuesDialog", Auto)
    n0 = len(rdc.elements)
    w.insert_macro(str(find_macro("DC string v rozvaděči").path))
    assert len(rdc.elements) > n0
    assert not [f for f in check_project(p, LibraryStore()) if f.code == "dup_ref"]
    assert "X9" in {e.ref for e in rdc.elements}
    _done(w)


# ---- 6., 7. přejmenování a smazání bloku ----------------------------------------------------------------------
def test_rename_inverter_updates_auto_texts_in_one_undo_step(app, lib):
    p = build_project(spec(2, 2))
    w = _win(lib, p)
    sc = w.scene
    t1 = next(e for e in p.sheets[0].elements if e.ref == "T1")
    before = _state(p)
    n0 = w.undo.count()
    sc.set_attr(t1.id, False, "ref", "T9")
    assert w.undo.count() == n0 + 1
    rh = next(s for s in p.switchboards() if s.loc == "RFVE.AC")
    assert "od T9" in [e.attrs.get("desc") for e in rh.elements if is_feed_in(e)]
    rdc1 = next(e for e in p.sheets[0].elements if e.ref == "RDC1")
    assert p.switchboard_sheet(rdc1.id).name == "RDC1 – DC rozvaděč po trase T9"
    w.undo.undo()
    assert _state(p) == before
    # přejmenování bloku: název listu (i v záložce) + umístění, jedním krokem
    sheet = p.switchboard_sheet(rdc1.id)
    w.open_sheet(sheet, "multipole")
    w.tabs.setCurrentIndex(0)
    sc.set_attr(rdc1.id, False, "ref", "RDC5")
    assert sheet.name.startswith("RDC5 – ") and sheet.loc == "RDC5" and w.undo.count() == n0 + 1
    assert any(w.tabs.tabText(i).startswith("RDC5 – ") for i in range(w.tabs.count()))
    w.undo.undo()
    assert _state(p) == before
    assert not any(w.tabs.tabText(i).startswith("RDC5") for i in range(w.tabs.count()))
    _done(w)


@pytest.mark.parametrize("answer", [QMessageBox.Yes, QMessageBox.No])
def test_delete_switchboard_block_offers_sheet_delete(app, lib, monkeypatch, answer):
    from envocad.model.checks import check_project
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or answer))
    p = build_project(spec(1, 2))
    w = _win(lib, p)
    sc = w.scene
    rdc1 = next(e for e in p.sheets[0].elements if e.ref == "RDC1")
    sheet = p.switchboard_sheet(rdc1.id)
    w.open_sheet(sheet, "multipole")
    w.tabs.setCurrentIndex(0)
    before = _state(p)
    n_sheets, n0 = len(p.sheets), w.undo.count()
    sc.clearSelection()
    sc.element_items[rdc1.id].setSelected(True)
    sc.delete_selected()
    assert asked and sheet.name in asked[-1]
    assert w.undo.count() == n0 + 1
    if answer == QMessageBox.Yes:
        assert sheet not in p.sheets and len(p.sheets) == n_sheets - 1
        assert all(w._unwrap(w.tabs.widget(i)).scene().sheet is not sheet for i in range(w.tabs.count()))
    else:
        assert sheet in p.sheets
        assert any(f.code == "sb_no_block" for f in check_project(p, LibraryStore()))
    w.undo.undo()
    assert _state(p) == before
    _done(w)


# ---- 8., 9. vícepól -------------------------------------------------------------------------------------------
def test_multipole_scene_uses_model_labels_and_pe_join(app, lib):
    from envocad.model.multipole_geometry import multipole_geometry
    from envocad.ui.multipole_view import ConductorItem, PeJoinItem
    p = build_project(spec(1, 2))
    w = _win(lib, p)
    sheet = next(s for s in p.sheets if s.name.startswith("RFVE.DC"))
    w.open_sheet(sheet, "multipole")
    sc = w.view.scene()
    geo = multipole_geometry(p, sheet, lib)
    items = [it for it in sc.items() if isinstance(it, ConductorItem)]
    assert items and all(it.label is not None for it in items)
    labels = {(it.wire.id, it.conductor): it.label for it in items}
    assert all(geo.conductor_labels[(wid, c, 0)] == lab for (wid, c), lab in labels.items())
    # trasy žil ve scéně = model (kontrola překryvů vidí stejný výkres)
    seg_model = {(round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3)) for a, b, o, _w in geo.lines
                 if "#" in o}
    from envocad.ui.items import path_points
    for it in items:
        pts = path_points(it.path())
        for a, b in pairwise(pts):
            if a != b:
                assert (round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3)) in seg_model
    assert len([it for it in sc.items() if isinstance(it, PeJoinItem)]) == 2   # 2 SPD
    _done(w)


# ---- 17. importéry ----------------------------------------------------------------------------------------------
def test_error_text_parse_and_zip_errors_in_czech():
    import xml.etree.ElementTree as ET
    import zipfile

    from envocad.ui.main_window import error_text
    try:
        ET.fromstring("<a><b></a>")
    except ET.ParseError as ex:
        assert "není platné XML" in error_text(ex) and "řádku 1" in error_text(ex)
    assert "není platný archiv" in error_text(zipfile.BadZipFile("x"))
    assert "kódování" in error_text(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"))


def test_gui_importers_show_czech_message(app, lib, warned, tmp_path, monkeypatch):
    bad_xml = tmp_path / "vadny.elmt"
    bad_xml.write_text("<definition><description></definition>", encoding="utf-8")
    bad_zip = tmp_path / "vadny.zip"
    bad_zip.write_bytes(b"neni zip")
    bad_parts = tmp_path / "parts.xml"
    bad_parts.write_text("<parts><part P_ARTICLE_PARTNR='1'></parts>", encoding="utf-8")
    p = Project()
    w = _win(lib, p)
    n_sym = len(lib.list_symbols())
    for path, fn in ((bad_xml, w.import_qet_symbol), (bad_zip, w.import_eplan), (bad_parts, w.import_eplan)):
        monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, path=path, **k: (str(path), "")))
        fn()
        assert str(path) in warned[-1]
    assert "není platné XML" in warned[0] and "není platný archiv" in warned[1] and "není platné XML" in warned[2]
    assert len(lib.list_symbols()) == n_sym
    _done(w)
