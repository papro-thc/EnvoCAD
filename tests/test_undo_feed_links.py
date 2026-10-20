"""Vazby přívodů/vývodů rozvaděče na vodiče JPS a undo (návrh docs/design/dluhy_dxf_jps.md, bod C).

Synchronizace po kroku undo/redo smí zapisovat jen odvozené atributy přívodu (`wire_id`, odkud/kam, kabel).
Primární data – žíly vodičů rozvaděče a port vodiče JPS na bloku – mění jen příkazy, takže je undo vrátí."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from envocad.library.store import LibraryStore
from envocad.model.project import (
    ConductorChange,
    Element,
    Project,
    Wire,
    WireEnd,
    apply_conductor_changes,
    apply_text_changes,
    feed_conductor_followups,
    rename_followups,
    sync_feed_link_attrs,
    sync_feed_links,
)
from envocad.ui import commands
from envocad.ui.main_window import MainWindow

FULL = ["L1", "L2", "L3", "N", "PE"]
SHORT = ["L1", "N", "PE"]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def lib(tmp_path):
    return LibraryStore(tmp_path / "lib.db")


def _state(x) -> str:
    return json.dumps(x.to_dict(), sort_keys=True, ensure_ascii=False)


def _project(linked: bool = False):
    """JPS: střídač T1 a blok R1; list rozvaděče: přívod X1 → jistič Q1 vodičem se žilami [L1, N, PE].
    `linked` = vodič JPS T1:AC → R1:X1 (5 žil) už existuje."""
    p = Project(name="Vazby")
    s = p.sheets[0]
    t = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    s.elements += [t, blk]
    sb = p.create_switchboard_sheet(blk)
    feed = Element("sb.feed", 40, 200, rotation=180, attrs={"dir": "in", "ref": "X1"})
    q = Element("fve.breaker_mcb", 40, 150, attrs={"ref": "Q1"})
    sb.elements += [feed, q]
    sb.wires.append(Wire(WireEnd(feed.id, "1"), WireEnd(q.id, "1"), conductors=list(SHORT)))
    jw = None
    if linked:
        jw = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X1"), attrs={"ref": "W1"}, conductors=list(FULL))
        s.wires.append(jw)
    return p, s, sb, t, blk, feed, jw


def _win(lib, p: Project) -> MainWindow:
    w = MainWindow(library=lib, project=p)
    w.show()
    w.undo.setClean()
    return w


def _done(w: MainWindow) -> None:
    w.undo.setClean()
    w.close()


# ---- ověřená chyba ----------------------------------------------------------------------------------------------
def test_undo_add_jps_wire_restores_feed_conductors(app, lib):
    """Žíly přívodu [L1, N, PE] → vložení vodiče JPS (5 žil) na blok:X1 → undo: žíly zase [L1, N, PE]
    (dřív zůstalo L1…PE, protože je kopírovala synchronizace po kroku undo mimo příkaz)."""
    p, s, sb, t, blk, feed, _ = _project()
    w = _win(lib, p)
    jps = w._jps_scene(s)
    sb_before, jps_before = _state(sb.wires[0]), _state(s)
    wire = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X1"), attrs={"ref": "W1"}, conductors=list(FULL))
    w.undo.push(commands.AddWireCommand(jps, wire))
    assert sb.wires[0].conductors == FULL
    assert feed.attrs["wire_id"] == wire.id               # odvozená vazba (synchronizace)
    after = _state(p)
    w.undo.undo()
    assert sb.wires[0].conductors == SHORT
    assert _state(sb.wires[0]) == sb_before and _state(s) == jps_before
    assert feed.attrs.get("wire_id", "") == ""
    w.undo.redo()
    assert sb.wires[0].conductors == FULL and _state(p) == after
    _done(w)


def test_undo_sync_does_not_touch_primary_data(app, lib):
    """Po kroku undo/redo běží jen odvozená synchronizace: žíly vodičů rozvaděče ani porty JPS nemění."""
    p, s, sb, t, _blk, _feed, _jw = _project(linked=True)
    w = _win(lib, p)               # načtení projektu: plná synchronizace (vazba vznikla už v souboru)
    assert sb.wires[0].conductors == FULL
    sb.wires[0].conductors = list(SHORT)    # ruční odchylka v souboru – krok undo ji nesmí přepsat
    jps = w._jps_scene(s)
    w.undo.push(commands.SetAttrCommand(jps, t.id, False, "desc", "", "střídač"))
    w.undo.undo()
    w.undo.redo()
    assert sb.wires[0].conductors == SHORT
    _done(w)


# ---- model: rozdělení sync_feed_links ---------------------------------------------------------------------------
def test_sync_feed_link_attrs_is_derived_only():
    p, _s, sb, _t, _blk, feed, jw = _project(linked=True)
    sb_wires = _state(sb.wires[0])
    assert sync_feed_link_attrs(p) == 1
    assert feed.attrs["wire_id"] == jw.id and feed.attrs["from"].startswith("W1 T1:AC")
    assert _state(sb.wires[0]) == sb_wires             # žíly se nekopírují
    assert sync_feed_link_attrs(p) == 0                 # idempotentní
    feed.attrs["ref"] = "X5"                            # přejmenovaný přívod s vazbou: port vodiče se nemění
    sync_feed_link_attrs(p)
    assert jw.b.port == "X1"


def test_sync_feed_links_full_keeps_old_behaviour():
    """Plná synchronizace (načtení projektu, generátor) dál kopíruje žíly a přejmenuje port."""
    p, _s, sb, _t, _blk, feed, jw = _project(linked=True)
    assert sync_feed_links(p) >= 1
    assert sb.wires[0].conductors == FULL
    feed.attrs["ref"] = "X5"
    sync_feed_links(p)
    assert jw.b.port == "X5"
    assert sync_feed_links(p) == 0


def test_feed_conductor_followups_and_apply():
    p, _s, sb, _t, _blk, _feed, jw = _project(linked=True)
    sb.wires[0].terminals = {"N": {"a": "X1:2"}, "L1": {"a": "X1:1"}}
    ch = feed_conductor_followups(p, jw)
    assert ch == [ConductorChange(sb.wires[0].id, SHORT, FULL, {"N": {"a": "X1:2"}, "L1": {"a": "X1:1"}},
                                  {"N": {"a": "X1:2"}, "L1": {"a": "X1:1"}})]
    before = _state(p)
    apply_conductor_changes(p, ch)
    assert sb.wires[0].conductors == FULL
    assert feed_conductor_followups(p, jw) == []
    apply_conductor_changes(p, ch, undo=True)
    assert _state(p) == before
    # vodič rozvaděče ani vodič bez žil nic nevyvolá
    assert feed_conductor_followups(p, sb.wires[0]) == []
    jw.conductors = []
    assert feed_conductor_followups(p, jw) == []


def test_feed_conductor_followups_drops_terminals_of_removed_conductors():
    p, _s, sb, _t, _blk, _feed, jw = _project(linked=True)
    jw.conductors = ["L1", "PE"]
    sb.wires[0].terminals = {"N": {"a": "X1:2"}, "L1": {"a": "X1:1"}}
    (c,) = feed_conductor_followups(p, jw)
    assert c.new_terminals == {"L1": {"a": "X1:1"}}
    apply_conductor_changes(p, [c])
    assert sb.wires[0].terminals == {"L1": {"a": "X1:1"}}
    apply_conductor_changes(p, [c], undo=True)
    assert sb.wires[0].terminals == {"N": {"a": "X1:2"}, "L1": {"a": "X1:1"}}


def test_feed_conductor_followups_respects_port_over_manual_link():
    """Vazba jako v odvozené synchronizaci: vodič na portu bloku má přednost před ruční vazbou `wire_id`."""
    p, s, _sb, t, blk, feed, jw = _project(linked=True)
    other = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X9"), conductors=["L1", "PE"])
    s.wires.append(other)
    feed.attrs["wire_id"] = other.id
    assert feed_conductor_followups(p, other) == []
    assert len(feed_conductor_followups(p, jw)) == 1


def test_rename_followups_renames_block_port_of_linked_wire():
    p, _s, _sb, _t, _blk, feed, jw = _project(linked=True)
    sync_feed_link_attrs(p)
    ch = rename_followups(p, feed, "X1", "X5")
    ports = [c for c in ch if c.kind == "wire_port"]
    assert len(ports) == 1 and (ports[0].target_id, ports[0].key, ports[0].old, ports[0].new) == (jw.id, "b", "X1", "X5")
    before = _state(p)
    apply_text_changes(p, ch)
    assert jw.b.port == "X5"
    apply_text_changes(p, ch, undo=True)
    assert _state(p) == before


def test_rename_followups_port_without_wire_id_and_when_new_port_taken():
    p, s, sb, t, blk, feed, _jw = _project(linked=True)
    assert "wire_id" not in feed.attrs                  # vazba jen podle portu
    assert [c.new for c in rename_followups(p, feed, "X1", "X2") if c.kind == "wire_port"] == ["X2"]
    s.wires.append(Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X2")))
    assert [c for c in rename_followups(p, feed, "X1", "X2") if c.kind == "wire_port"] == []
    other = Element("fve.breaker_mcb", 0, 0, attrs={"ref": "Q1"})   # jen přívody/vývody
    sb.elements.append(other)
    assert [c for c in rename_followups(p, other, "Q1", "Q2") if c.kind == "wire_port"] == []


# ---- příkazy -----------------------------------------------------------------------------------------------------
def test_rename_feed_in_gui_renames_port_in_one_undo_step(app, lib):
    p, _s, sb, _t, _blk, feed, jw = _project(linked=True)
    w = _win(lib, p)
    w.open_sheet(sb)
    sc = w.scene
    assert sc.sheet is sb
    before = _state(p)
    sc.set_attr(feed.id, False, "ref", "X5")
    assert feed.ref == "X5" and jw.b.port == "X5"
    after = _state(p)
    w.undo.undo()
    assert feed.ref == "X1" and jw.b.port == "X1"
    assert _state(p) == before
    w.undo.redo()
    assert _state(p) == after
    _done(w)


def test_set_conductors_on_jps_wire_propagates_and_undoes(app, lib):
    p, s, sb, _t, _blk, _feed, jw = _project(linked=True)
    w = _win(lib, p)
    jps = w._jps_scene(s)
    before = _state(p)
    w.undo.push(commands.SetConductorsCommand(jps, jw.id, jw.conductors, ["L1", "N", "PE"]))
    assert sb.wires[0].conductors == ["L1", "N", "PE"]
    after = _state(p)
    w.undo.undo()
    assert _state(p) == before and sb.wires[0].conductors == FULL
    w.undo.redo()
    assert _state(p) == after
    _done(w)


def test_set_attr_wire_id_copies_conductors_and_undoes(app, lib):
    """Ruční vazba (`wire_id`) na vodič JPS: žíly, port bloku i odvozené odkud/kam a kabel se změní příkazem a undo
    vrátí celý stav projektu."""
    p, s, sb, t, blk, feed, _ = _project()
    other = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X7"), attrs={"ref": "W7", "cable": "CYKY"},
                 conductors=list(FULL))
    s.wires.append(other)
    w = _win(lib, p)
    w.open_sheet(sb)
    sc = w.scene
    assert sc.sheet is sb
    before = _state(p)
    sc.set_attr(feed.id, False, "wire_id", other.id)
    assert sb.wires[0].conductors == FULL and other.b.port == "X1"
    w.undo.undo()
    assert sb.wires[0].conductors == SHORT and other.b.port == "X7"
    w.undo.redo()
    assert sb.wires[0].conductors == FULL and other.b.port == "X1"
    assert feed.attrs["from"].startswith("W7 ") and feed.attrs["cable"] == "CYKY"
    w.undo.undo()
    assert _state(p) == before          # i odkud/kam a kabel ruční vazby vrátí undo (klíče zase chybí)
    _done(w)


def test_attrs_changed_emitted_after_followups(app, lib):
    """Signál `attrs_changed` přijde až po navázaných změnách – panel vlastností vidí výsledný stav (port vodiče
    JPS, odkud/kam) při redo i undo."""
    p, s, sb, t, blk, feed, _ = _project()
    other = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X7"), attrs={"ref": "W7"}, conductors=list(FULL))
    s.wires.append(other)
    w = _win(lib, p)
    w.open_sheet(sb)
    seen = []
    w.scene.attrs_changed.connect(lambda _id: seen.append((other.b.port, feed.attrs.get("from", ""),
                                                          list(sb.wires[0].conductors))))
    w.scene.set_attr(feed.id, False, "wire_id", other.id)
    assert seen[-1][0] == "X1" and seen[-1][1].startswith("W7 ") and seen[-1][2] == FULL
    w.undo.undo()
    assert seen[-1] == ("X7", "", SHORT)
    _done(w)


def test_add_feed_with_wire_id_renames_jps_port_and_undoes(app, lib):
    """Nový přívod s vazbou z dialogu (`AddElementCommand`): konec vodiče JPS na bloku se přejmenuje podle
    označení přívodu, undo ho vrátí, redo zopakuje."""
    from envocad.model.project import feed_link_attrs
    p, s, sb, _t, blk, _feed, _ = _project()
    t2 = Element("fve.inverter", 50, 100, attrs={"ref": "T2"})
    other = Wire(WireEnd(t2.id, "AC"), WireEnd(blk.id, "X7"), attrs={"ref": "W7"}, conductors=list(FULL))
    s.elements.append(t2)
    s.wires.append(other)
    w = _win(lib, p)
    w.open_sheet(sb)
    sc = w.scene
    before = _state(p)
    e = Element("sb.feed", 80, 200, rotation=180, attrs={"dir": "in", "ref": "X2"})
    e.attrs.update(feed_link_attrs(p, sb, e, other.id))
    w.undo.push(commands.AddElementCommand(sc, e))
    assert other.b.port == "X2" and e.attrs["wire_id"] == other.id
    after = _state(p)
    w.undo.undo()
    assert other.b.port == "X7" and _state(p) == before
    w.undo.redo()
    assert other.b.port == "X2" and _state(p) == after
    _done(w)


def test_paste_feed_with_wire_id_renames_jps_port(app, lib):
    """Totéž pro přívod s vazbou vložený přes `PasteCommand` (makro s vazbou)."""
    p, s, sb, t, blk, _feed, _ = _project()
    other = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X7"), attrs={"ref": "W7"}, conductors=list(FULL))
    s.wires.append(other)
    w = _win(lib, p)
    w.open_sheet(sb)
    before = _state(p)
    e = Element("sb.feed", 80, 200, rotation=180, attrs={"dir": "in", "ref": "X3", "wire_id": other.id})
    w.undo.push(commands.PasteCommand(w.scene, [e], []))
    assert other.b.port == "X3"
    w.undo.undo()
    assert other.b.port == "X7" and _state(p) == before
    _done(w)


def test_multipole_add_feed_with_wire_id_renames_jps_port(app, lib):
    """Totéž pro přívod s vazbou vložený ve vícepólu listu rozvaděče (`MultipoleAddCommand`)."""
    p, s, sb, t, blk, _feed, _ = _project()
    other = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X7"), attrs={"ref": "W7"}, conductors=list(FULL))
    s.wires.append(other)
    w = _win(lib, p)
    w.open_sheet(sb, "multipole")
    mps = w.view.scene()
    assert mps.sheet is sb
    before = _state(p)
    e = Element("sb.feed", 80, 200, rotation=180, attrs={"dir": "in", "ref": "X4", "wire_id": other.id})
    w.undo.push(commands.MultipoleAddCommand(mps, element=e))
    assert other.b.port == "X4"
    w.undo.undo()
    assert other.b.port == "X7" and _state(p) == before
    _done(w)


def test_edit_feed_ref_and_wire_id_together_keeps_new_link(app, lib):
    """Úprava přívodu se změnou označení i vazby v jednom dialogu: nová vazba se neztratí – port dostane nově
    navázaný vodič, dosavadní vodič zůstane na svém portu a vodiče u přívodu převezmou žíly nového vodiče."""
    p, s, sb, _t, blk, feed, jw = _project(linked=True)
    t2 = Element("fve.inverter", 50, 100, attrs={"ref": "T2"})
    other = Wire(WireEnd(t2.id, "AC"), WireEnd(blk.id, "X7"), attrs={"ref": "W7"}, conductors=["L1", "PE"])
    s.elements.append(t2)
    s.wires.append(other)
    w = _win(lib, p)
    w.open_sheet(sb)
    sc = w.scene
    before = _state(p)
    sc.undo.beginMacro("Upravit X1")            # stejné kroky jako `edit_element`
    sc._apply_attr_changes(feed.id, False, dict(feed.attrs), {**feed.attrs, "ref": "X5", "wire_id": other.id}, "x")
    sc._take_conductors_from_link(feed.id, other.id)
    sc.undo.endMacro()
    assert feed.attrs["ref"] == "X5" and feed.attrs["wire_id"] == other.id
    assert other.b.port == "X5" and jw.b.port == "X1"
    assert sb.wires[0].conductors == ["L1", "PE"]
    w.undo.undo()
    assert _state(p) == before
    _done(w)


def test_split_wire_on_block_keeps_undo_exact(app, lib):
    p, s, sb, _t, _blk, _feed, jw = _project(linked=True)
    w = _win(lib, p)
    sb.wires[0].conductors = list(SHORT)
    w.undo.setClean()
    jps = w._jps_scene(s)
    j = Element("sb.junction", 80, 150)
    w1 = Wire(jw.a, WireEnd(j.id, "W"), attrs=dict(jw.attrs), conductors=list(FULL))
    w2 = Wire(WireEnd(j.id, "E"), jw.b, conductors=list(FULL))
    before = _state(sb.wires[0])
    w.undo.push(commands.SplitWireCommand(jps, jw.id, j, w1, w2))
    assert sb.wires[0].conductors == FULL               # nová vazba přívodu převzala žíly
    w.undo.undo()
    assert _state(sb.wires[0]) == before
    _done(w)


# ---- schránka, vícepól, překreslení, revize ---------------------------------------------------------------------
def test_paste_wire_on_block_port_copies_conductors_and_undoes(app, lib):
    """Vložení ze schránky / makra (PasteCommand) s vodičem JPS na port bloku: žíly přebere přívod příkazem,
    undo je vrátí, redo zopakuje (dřív to dělala jen synchronizace mimo undo)."""
    p, s, sb, _t, blk, feed, _ = _project()
    w = _win(lib, p)
    jps = w._jps_scene(s)
    before = _state(p)
    t2 = Element("fve.inverter", 50, 100, attrs={"ref": "T2"})
    wire = Wire(WireEnd(t2.id, "AC"), WireEnd(blk.id, "X1"), attrs={"ref": "W2"}, conductors=list(FULL))
    w.undo.push(commands.PasteCommand(jps, [t2], [wire]))
    assert sb.wires[0].conductors == FULL and feed.attrs["wire_id"] == wire.id
    after = _state(p)
    w.undo.undo()
    assert sb.wires[0].conductors == SHORT
    assert json.loads(_state(p))["sheets"][1]["wires"] == json.loads(before)["sheets"][1]["wires"]
    w.undo.redo()
    assert sb.wires[0].conductors == FULL and _state(p) == after
    _done(w)


def test_multipole_add_wire_on_block_port_copies_conductors_and_undoes(app, lib):
    """Totéž pro vodič vložený ve vícepólu listu JPS (MultipoleAddCommand)."""
    p, s, sb, t, blk, _feed, _ = _project()
    w = _win(lib, p)
    w.open_sheet(s, "multipole")
    mps = w.view.scene()
    assert mps.sheet is s and not hasattr(mps, "wire_items")
    wire = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X1"), conductors=list(FULL))
    w.undo.push(commands.MultipoleAddCommand(mps, wire=wire))
    assert sb.wires[0].conductors == FULL
    w.undo.undo()
    assert sb.wires[0].conductors == SHORT and wire not in s.wires
    w.undo.redo()
    assert sb.wires[0].conductors == FULL
    _done(w)


def _ends(item):
    path = item.path()
    first, last = path.elementAt(0), path.elementAt(path.elementCount() - 1)
    return {(round(first.x, 3), round(first.y, 3)), (round(last.x, 3), round(last.y, 3))}


def test_set_attr_wire_id_reroutes_jps_wire_item(app, lib):
    """Ruční vazba přívodu X1 na vodič JPS vedoucí na port X2 bloku: port vodiče se přejmenuje na X1 a položka
    vodiče v otevřeném JPS se hned přetrasuje (bez přestavby scény); undo ji vrátí na X2. Porty bloku se nemění
    (přívod X2 existuje), takže obnovu nezajistí ani přestavba bloku."""
    p, s, sb, t, blk, feed, _ = _project()
    sb.elements.append(Element("sb.feed", 40, 120, rotation=180, attrs={"dir": "in", "ref": "X2"}))
    other = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X2"), attrs={"ref": "W7"}, conductors=list(FULL))
    s.wires.append(other)
    w = _win(lib, p)
    jps = w._jps_scene(s)
    item, blk_item = jps.wire_items[other.id], jps.element_items[blk.id]
    pos = {n: (round(blk_item.port_scene_pos(n).x(), 3), round(blk_item.port_scene_pos(n).y(), 3))
           for n in ("X1", "X2")}
    assert pos["X1"] != pos["X2"] and pos["X2"] in _ends(item)
    w.open_sheet(sb)
    sc = w.scene
    assert sc.sheet is sb
    sc.set_attr(feed.id, False, "wire_id", other.id)
    assert other.b.port == "X1"
    assert jps.wire_items[other.id] is item            # stejná položka, scéna se nepřestavěla
    assert pos["X1"] in _ends(item) and pos["X2"] not in _ends(item)
    w.undo.undo()
    assert other.b.port == "X2" and pos["X2"] in _ends(item) and pos["X1"] not in _ends(item)
    w.undo.redo()
    assert pos["X1"] in _ends(item)
    _done(w)


def test_derived_empty_attrs_after_undo_do_not_affect_revision(app, lib):
    """Po vložení a undo vodiče JPS má přívod místo chybějících klíčů `wire_id`/`from`/`cable` prázdné hodnoty
    (odvozená synchronizace). Porovnání revizí ani otisk listu je nevidí – prázdná hodnota = chybějící klíč."""
    from envocad.model.diff import diff_projects, sheet_fingerprint
    p, s, _sb, t, blk, feed, _ = _project()
    w = _win(lib, p)
    old = Project.from_dict(p.to_dict())
    fps = {x.id: sheet_fingerprint(x) for x in p.sheets}
    wire = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X1"), attrs={"ref": "W1", "cable": "CYKY"},
                conductors=list(FULL))
    w.undo.push(commands.AddWireCommand(w._jps_scene(s), wire))
    assert feed.attrs["cable"] == "CYKY" and diff_projects(old, p)
    w.undo.undo()
    assert {k: feed.attrs.get(k) for k in ("wire_id", "from", "cable")} == {"wire_id": "", "from": "", "cable": ""}
    assert diff_projects(old, p) == []
    assert {x.id: sheet_fingerprint(x) for x in p.sheets} == fps
    _done(w)
