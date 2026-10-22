"""Regrese z QA auditu rozvaděčů a JPS – GUI části: šablona s neplatným parametrem, panel skříně (neplatná čísla,
varování přeplnění), dialog Svorkovnice a můstky, vložení kopie a undo s kabely."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from envocad.library.store import LibraryStore
from envocad.library.templates import apply_template
from envocad.model.project import Element, Project, Wire, WireEnd
from envocad.ui.main_window import MainWindow


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
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    return seen


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


def _sb_project(params=None):
    p = Project(name="Q")
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    if params is not None:
        apply_template(p, sb, "ac_fve", params, standard_paper="A4")
    return p, sb


def test_gui_template_invalid_param_shows_message_and_inserts_nothing(app, lib, warned):
    """#24: GUI ukáže českou hlášku šablony a nic nevloží (žádný krok undo)."""
    p, sb = _sb_project()
    w = _win(lib, p)
    before = _state(p)
    assert w.apply_template(sb, "ac_fve", {"n_out": "0"}) is False
    assert _state(p) == before and w.undo.count() == 0
    assert warned and "Počet vývodů" in warned[-1]
    assert w.apply_template(sb, "ac_fve", {"n_out": "2"}) is True and w.undo.count() == 1
    _done(w)


def test_enclosure_panel_invalid_number_highlights_and_keeps_model(app, lib, warned):
    """#25: neplatné číslo → pole zvýrazněné + hláška, model ani undo se nemění; rdf a t_ambient nezávislé."""
    p, sb = _sb_project({"distribution": "terminals", "n_out": "2"})
    w = _win(lib, p)
    w.open_sheet(sb, "layout")
    panel = w.view.side_panel
    before = _state(p)
    panel._edits["rdf"].setText("1,5")
    panel._edits["rdf"].editingFinished.emit()
    assert _state(p) == before and w.undo.count() == 0
    assert panel._edits["rdf"].styleSheet() and "RDF" in panel._edits["rdf"].toolTip()
    assert not panel.errors.isHidden() and "mimo rozsah" in panel.errors.text()
    panel._edits["t_ambient"].setText("40")                     # platná teplota se propíše i při neplatném RDF
    panel._edits["t_ambient"].editingFinished.emit()
    assert sb.layout.params["t_ambient"] == "40" and "rdf" not in sb.layout.params and w.undo.count() == 1
    assert "40 °C" in panel.thermal.text()
    panel._edits["rdf"].setText("0,6")
    panel._edits["rdf"].editingFinished.emit()
    assert sb.layout.params["rdf"] == "0,6" and not panel._edits["rdf"].styleSheet() and panel.errors.isHidden()
    _done(w)


def test_enclosure_panel_warns_on_overflow_and_keeps_placements(app, lib, warned):
    """#9: zmenšení modulů v řadě nic nemaže; panel ukáže varování (záporná rezerva, přístroje za koncem řady)."""
    p, sb = _sb_project({"distribution": "terminals", "n_out": "9"})
    w = _win(lib, p)
    w.open_sheet(sb, "layout")
    panel = w.view.side_panel
    n = len(sb.layout.placements)
    assert panel.warning.isHidden()
    panel.rows.setValue(1)
    panel.mods.setValue(8)
    assert len(sb.layout.placements) == n
    assert not panel.warning.isHidden()
    assert "přeplněná" in panel.warning.text() and "za koncem řady" in panel.warning.text()
    assert "rezerva -" in panel.info.text()
    _done(w)


def test_strip_dialog_keeps_drafts_and_validates(app, lib, warned):
    """#20: úpravy můstků se při přepnutí svorkovnice zachovají; neexistující svorka → hláška, dialog se nezavře."""
    from envocad.ui.dialogs import StripDialog
    p, sb = _sb_project({"distribution": "terminals", "n_out": "2"})
    d = StripDialog(p, sb, None, "X2")
    d.bridges.setPlainText("1-6\n2-7")
    d.strip.setCurrentText("X1")
    d.strip.setCurrentText("X2")
    assert d.bridges.toPlainText() == "1-6\n2-7"
    assert d.all_values() == {"X2": [["1", "6"], ["2", "7"]]}
    d.bridges.setPlainText("1-6-99")
    d.accept()
    assert d.result() != QDialog.Accepted and warned and "99" in warned[-1]
    d.bridges.setPlainText("1-6-11")
    d.accept()
    assert d.result() == QDialog.Accepted


def test_edit_strip_applies_all_strips_as_one_undo_step(app, lib, warned, monkeypatch):
    from envocad.ui import dialogs
    p, sb = _sb_project({"distribution": "terminals", "n_out": "2"})
    p.set_bridges("X1", [["1", "2"]], sb)
    w = _win(lib, p)
    w.open_sheet(sb, "schematic")
    before = _state(p)

    def fake_exec(self):
        self.strip.setCurrentText("X2")
        self.bridges.setPlainText("1-6")
        self.strip.setCurrentText("X1")
        self.bridges.setPlainText("")
        return QDialog.Accepted
    monkeypatch.setattr(dialogs.StripDialog, "exec", fake_exec)
    w.edit_strip()
    assert p.bridge_groups("X2", sb) == [["1", "6"]] and p.bridge_groups("X1", sb) == []
    assert w.undo.count() == 1
    w.undo.undo()
    assert _state(p) == before
    _done(w)


def _jps():
    p = Project(name="J")
    s = p.sheets[0]
    g = Element("fve.pv_string", 40, 150, attrs={"ref": "G1"})
    t = Element("fve.inverter", 100, 150, attrs={"ref": "T1"})
    s.elements += [g, t]
    s.wires.append(Wire(WireEnd(g.id, "+"), WireEnd(t.id, "DC1"), attrs={"ref": "W1", "cable": "H1Z2Z2-K 1x6"},
                        conductors=["DC+", "DC-"]))
    return p, s


def test_paste_gets_own_cable_and_undo_redo_is_exact(app, lib, warned):
    """Audit 1 #3 a #15: vložená kopie má vlastní kabel; undo vložení kabel odebere, redo ho vrátí – to_dict přesně;
    smazání vodiče + undo totéž."""
    p, s = _jps()
    w = _win(lib, p)
    sc = w.scene
    sc.ask_attributes = False
    before = _state(p)
    for it in sc.element_items.values():
        it.setSelected(True)
    assert sc.copy_selected() == 2 and sc.paste() == 2
    after = _state(p)
    new = s.wires[-1]
    assert new.attrs["cable_id"] != s.wires[0].attrs["cable_id"] and len(p.cables) == 2
    assert p.cable_of_wire(s.wires[0]).ref == "W1"
    w.undo.undo()
    assert _state(p) == before and len(p.cables) == 1
    w.undo.redo()
    assert _state(p) == after
    sc.clearSelection()
    sc.wire_items[new.id].setSelected(True)
    sc.delete_selected()
    assert len(p.cables) == 1
    w.undo.undo()
    assert _state(p) == after
    _done(w)
