"""Směr přívodu/vývodu `sb.feed` v GUI: jeden `SetAttrCommand` vč. navázaných změn (odkud ↔ kam, port bloku,
obrázek značky) a nabídka ve Vlastnostech."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from envocad.library.store import LibraryStore
from envocad.model.feed import FEED_ARROW_IN, FEED_ARROW_OUT, FEED_SYMBOL
from envocad.model.project import Element, Project, Wire, WireEnd, element_symbol, sync_feed_links
from envocad.ui.dialogs import ChoiceEdit, ElementDialog
from envocad.ui.items import ElementItem
from envocad.ui.main_window import MainWindow

FULL = ["L1", "L2", "L3", "N", "PE"]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def lib(tmp_path):
    return LibraryStore(tmp_path / "lib.db")


def _state(p) -> str:
    return json.dumps(p.to_dict(), sort_keys=True, ensure_ascii=False)


def _project():
    p = Project(name="Směr")
    s = p.sheets[0]
    t = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    s.elements += [t, blk]
    sb = p.create_switchboard_sheet(blk)
    feed = Element(FEED_SYMBOL, 40, 100, attrs={"ref": "X1", "dir": "in"})
    q = Element("fve.breaker_mcb", 40, 150, rotation=90, attrs={"ref": "Q1"})
    sb.elements += [feed, q]
    sb.wires.append(Wire(WireEnd(feed.id, "1"), WireEnd(q.id, "1"), conductors=list(FULL)))
    jw = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X1"), attrs={"ref": "W1", "cable": "CYKY-J 5x16"},
              conductors=list(FULL))
    s.wires.append(jw)
    sync_feed_links(p)
    return p, s, sb, blk, feed, jw


def _win(lib, p):
    w = MainWindow(library=lib, project=p)
    w.show()
    w.undo.setClean()
    return w


def test_dir_change_is_one_undo_step_with_followups(app, lib):
    p, _s, sb, blk, feed, jw = _project()
    assert feed.attrs["from"].startswith("W1 T1:AC") and "to" not in feed.attrs
    w = _win(lib, p)
    w.open_sheet(sb)
    sc = w.scene
    item = sc.element_items[feed.id]
    assert FEED_ARROW_IN in item.symbol.primitives
    before = _state(p)
    n0 = w.undo.count()
    sc.set_attr(feed.id, False, "dir", "out")
    assert w.undo.count() == n0 + 1
    assert feed.attrs["dir"] == "out" and feed.attrs["to"].startswith("W1 T1:AC") and feed.attrs["from"] == ""
    assert FEED_ARROW_OUT in sc.element_items[feed.id].symbol.primitives       # obrázek se přestavěl
    assert ("X1", "E") in {(q.name, q.dir) for q in element_symbol(p, blk, lib).ports}   # port bloku vpravo
    assert jw.b.port == "X1"                                                     # vodič JPS drží
    after = _state(p)
    w.undo.undo()
    assert _state(p) == before
    assert FEED_ARROW_IN in sc.element_items[feed.id].symbol.primitives
    w.undo.redo()
    assert _state(p) == after
    w.undo.setClean()
    w.close()


def test_properties_panel_offers_direction_choice(app, lib):
    p, _s, sb, _blk, feed, _jw = _project()
    w = _win(lib, p)
    w.open_sheet(sb)
    sc = w.scene
    item = sc.element_items[feed.id]
    w.props_panel.show_item(item)
    combos = w.props_panel.findChildren(ChoiceEdit)
    assert len(combos) == 1 and combos[0].text() == "in"
    assert [combos[0].itemText(i) for i in range(combos[0].count())] == ["přívod", "vývod"]
    combos[0].setCurrentIndex(1)
    for _ in range(5):
        app.processEvents()
    assert feed.attrs["dir"] == "out" and feed.attrs["to"].startswith("W1")
    w.undo.undo()
    assert feed.attrs["dir"] == "in" and feed.attrs["from"].startswith("W1") and "to" not in feed.attrs
    w.undo.setClean()
    w.close()


def test_element_dialog_direction_choice(app, lib):
    sym = lib.get_symbol(FEED_SYMBOL)
    dlg = ElementDialog(sym, {"ref": "X1"})
    ed = dlg._edits["dir"]
    assert isinstance(ed, ChoiceEdit) and ed.text() == "in"          # výchozí směr nové značky z palety: přívod
    ed.setText("out")
    assert dlg.values()["dir"] == "out"
    dlg.close()


def test_palette_preview_is_feed_in(app, lib):
    item = ElementItem(Element(FEED_SYMBOL), lib.get_symbol(FEED_SYMBOL))
    assert FEED_ARROW_IN in item.symbol.primitives
