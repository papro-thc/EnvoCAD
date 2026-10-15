"""Vícepólový pohled – výpočty nad modelem (bez Qt)."""

from envocad.library.store import LibraryStore
from envocad.model import multipole as mp
from envocad.model.project import Element, Sheet, Wire, WireEnd


def _lib():
    return LibraryStore()


def test_default_conductors():
    a = Element("fve.breaker_mcb", attrs={"poles": "3"})
    b = Element("fve.inverter", attrs={"phases": "3"})
    assert mp.default_conductors(a, "2", b, "AC") == ["L1", "L2", "L3", "N", "PE"]
    assert mp.default_conductors(Element("fve.breaker_mcb", attrs={"poles": "1"}), "2", Element("fve.load"), "1") \
        == ["L1", "N", "PE"]
    assert mp.default_conductors(Element("fve.pv_string"), "DC+", Element("fve.inverter"), "DC+") == ["DC+"]
    assert mp.parse_conductors("L1, L2;L3 N N") == ["L1", "L2", "L3", "N"]


def test_element_poles_switched_and_bypass():
    lib = _lib()
    s = Sheet()
    f = Element("fve.breaker_mcb", x=50, y=100, attrs={"ref": "F1", "poles": "3"})
    g = Element("fve.grid", x=0, y=100, attrs={"ref": "G"})
    t = Element("fve.inverter", x=100, y=100, attrs={"ref": "T1"})
    s.elements += [g, f, t]
    s.wires.append(Wire(WireEnd(g.id, "1"), WireEnd(f.id, "1"), conductors=["L1", "L2", "L3", "N", "PE"]))
    s.wires.append(Wire(WireEnd(f.id, "2"), WireEnd(t.id, "AC"), conductors=["L1", "L2", "L3", "N", "PE"]))
    ep = mp.element_poles(s, f, lib.get_symbol("fve.breaker_mcb"))
    assert ep.through == ("1", "2")
    assert ep.slots == ["L1", "L2", "L3", "N", "PE"]
    assert ep.switched == ["L1", "L2", "L3"] and ep.bypass == ["N", "PE"]
    # póly jističe (porty W/E) se řadí dolů
    x0, y0 = ep.pole_pos("1", "L1")
    x1, y1 = ep.pole_pos("1", "L2")
    assert x0 == x1 and y1 == y0 - mp.POLE_PITCH
    assert ep.pole_offset("L3") == (0.0, -2 * mp.POLE_PITCH)
    # střídač není průchozí – jen jeden symbol
    et = mp.element_poles(s, t, lib.get_symbol("fve.inverter"))
    assert et.through is None and et.switched == [] and et.slots == ["L1", "L2", "L3", "N", "PE"]


def test_rotated_element_poles_go_right():
    lib = _lib()
    s = Sheet()
    f = Element("fve.breaker_mcb", x=50, y=100, rotation=90, attrs={"ref": "F1", "poles": "1"})
    g = Element("fve.grid", x=0, y=100)
    s.elements += [g, f]
    s.wires.append(Wire(WireEnd(g.id, "1"), WireEnd(f.id, "1"), conductors=["L1", "N"]))
    ep = mp.element_poles(s, f, lib.get_symbol("fve.breaker_mcb"))
    (x0, y0), (x1, y1) = ep.pole_pos("1", "L1"), ep.pole_pos("1", "N")
    assert y0 == y1 and x1 == x0 + mp.POLE_PITCH
    assert ep.switched == ["L1"] and ep.bypass == []  # N jen na jedné straně → žádný obtok


def test_auto_number_terminals():
    s = Sheet(kind="switchboard")
    x1 = Element("sb.terminal_block", attrs={"ref": "X1"})
    x1b = Element("sb.terminal_block", attrs={"ref": "X1", "terminal": "7"})  # explicitní start
    f = Element("sb.rcbo", attrs={"ref": "F1", "poles": "1"})
    out = Element("sb.feed_out", attrs={"ref": "X2"})
    s.elements += [x1, x1b, f, out]
    w1 = Wire(WireEnd(x1.id, "2"), WireEnd(f.id, "1"), conductors=["L1", "N", "PE"])
    w2 = Wire(WireEnd(f.id, "2"), WireEnd(out.id, "1"), conductors=["L1", "N", "PE"])
    w3 = Wire(WireEnd(x1b.id, "2"), WireEnd(f.id, "1"), conductors=["L1", "N"])
    s.wires += [w1, w2, w3]
    # skupiny svorek: X1b má 7, 8 → X1 bez čísel pokračuje od 9
    assert mp.terminal_numbers(x1b, 2) == ["7", "8"]
    blocks = mp.auto_number_terminal_blocks(s)
    assert blocks == {x1.id: "9 10 11"}
    x1.attrs["terminal"] = blocks[x1.id]
    assert mp.terminal_designation(x1, ["L1", "N", "PE"], "N") == "X1:10"
    assert mp.wire_end_terminal(s, w1, "PE", "a") == "X1:11"
    assert mp.wire_end_terminal(s, w1, "PE", "b") == ""  # F1 není svorka
    assert mp.auto_number_terminal_blocks(s) == {}
    # přívody/vývody: číslování per žíla přes Wire.terminals
    res = mp.auto_number_terminals(s)
    assert w1.id not in res                              # svorkový prvek má čísla sám
    assert res[w2.id]["L1"]["b"] == "X2:1" and res[w2.id]["PE"]["b"] == "X2:3"
    for wid, t in res.items():
        next(w for w in s.wires if w.id == wid).terminals = t
    assert mp.auto_number_terminals(s) == {}


def test_bridges_roundtrip(tmp_path):
    from envocad.model.project import Project
    p = Project()
    p.set_bridges("X2", [["1", "6", "11"], ["2", "7"], ["3"]])
    assert p.bridge_groups("X2") == [["1", "6", "11"], ["2", "7"]]
    assert p.bridge_of("X2", "7") == ["2", "7"] and p.bridge_of("X2", "3") == []
    p.save(tmp_path / "b.ecp")
    p2 = Project.load(tmp_path / "b.ecp")
    assert p2.bridges == {"X2": [["1", "6", "11"], ["2", "7"]]}
    p2.set_bridges("X2", [])
    assert "X2" not in p2.bridges
