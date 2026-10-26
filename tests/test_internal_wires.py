"""Vnitřní vodiče rozvaděče: bez označení W a bez popisku kabelu / průřezu ve výkresu (list rozvaděče), JPS beze změny."""
from envocad.cmd.edits import new_wire
from envocad.library.store import LibraryStore
from envocad.model.multipole_geometry import multipole_geometry
from envocad.model.project import (
    Element,
    Project,
    Sheet,
    Wire,
    WireEnd,
    copy_fragment,
    internal_wires,
    paste_fragment,
    wire_label_on,
)


def _project():
    p = Project(name="Vodiče")
    jps = p.sheets[0]
    sb = Sheet(name="R1", kind="switchboard")
    p.sheets.append(sb)
    a = Element("fve.breaker_mcb", 60, 150, attrs={"ref": "F1"})
    b = Element("fve.breaker_mcb", 100, 150, attrs={"ref": "F2"})
    sb.elements += [a, b]
    w = Wire(WireEnd(a.id, "2"), WireEnd(b.id, "1"), conductors=["L1", "N", "PE"],
             attrs={"ref": "W12", "cable": "H07V-K", "cross": "4"})      # starší projekt: označení a průřez v datech
    sb.wires.append(w)
    j1 = Element("fve.breaker_mcb", 60, 150, attrs={"ref": "Q1"})
    j2 = Element("fve.breaker_mcb", 100, 150, attrs={"ref": "Q2"})
    jps.elements += [j1, j2]
    jw = Wire(WireEnd(j1.id, "2"), WireEnd(j2.id, "1"), attrs={"ref": "W1", "cable": "CYKY-J 5x16", "cross": "16"})
    jps.wires.append(jw)
    return p, jps, sb, w, jw


def test_label_hidden_only_on_switchboard():
    _p, jps, sb, w, jw = _project()
    assert internal_wires(sb) and not internal_wires(jps) and not internal_wires(None)
    assert wire_label_on(sb, w) == ""
    assert "W1" in wire_label_on(jps, jw) and "16" in wire_label_on(jps, jw)
    assert w.attrs["ref"] == "W12" and w.attrs["cross"] == "4"           # data se nemění (průřez pro výkazy)


def test_new_and_pasted_wires_on_switchboard_get_no_ref():
    p, jps, sb, _w, _jw = _project()
    a, b = sb.elements
    assert new_wire(p, sb, a, "1", b, "2").attrs["ref"] == ""
    ja, jb = jps.elements
    assert new_wire(p, jps, ja, "1", jb, "2").attrs["ref"].startswith("W")
    frag = copy_fragment(sb, [a.id, b.id])
    _els, wires = paste_fragment(p, frag, lambda sid: "F", target=sb)
    assert wires and all(not x.attrs.get("ref") for x in wires)
    _els, wires = paste_fragment(p, copy_fragment(jps, [ja.id, jb.id]), lambda sid: "Q", target=jps)
    assert wires and all(x.attrs.get("ref", "").startswith("W") for x in wires)


def test_multipole_has_no_wire_name_or_cross(tmp_path):
    p, _jps, sb, _w, _jw = _project()
    g = multipole_geometry(p, sb, LibraryStore(tmp_path / "l.db"), standard_paper="A3")
    texts = [pr.text for pr in g.prims if pr.kind == "text"] + [t for _x, _y, t, _a in g.conductor_labels.values()]
    assert not any("W12" in t or "mm²" in t or "H07V" in t for t in texts)
    assert any(t.strip() == "L1" for t in texts)                            # žíly zůstávají
