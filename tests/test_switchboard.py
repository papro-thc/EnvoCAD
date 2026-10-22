import json

import pytest

from envocad.library.store import LibraryStore
from envocad.library.templates import TEMPLATES, apply_template
from envocad.model.feed import is_feed_in, is_feed_out
from envocad.model.project import FORMAT_VERSION, Element, Project, Sheet, Wire, WireEnd


def _lib(tmp_path):
    return LibraryStore(tmp_path / "lib.db")


def test_switchboard_sheet_from_block(tmp_path):
    _lib(tmp_path)
    p = Project()
    block = Element("fve.switchboard", 100, 100, attrs={"ref": "R1", "desc": "AC rozvaděč FVE"})
    p.sheets[0].elements.append(block)
    s = p.create_switchboard_sheet(block)
    assert s.is_switchboard and s.parent_element_id == block.id and "R1" in s.name
    assert p.create_switchboard_sheet(block) is s  # idempotentní
    assert block.attrs["sheet"] == s.name
    assert p.switchboards() == [s]


def test_templates_build_and_place(tmp_path):
    lib = _lib(tmp_path)
    for t in TEMPLATES:
        p = Project()
        s = Sheet(kind="switchboard")
        p.sheets.append(s)
        apply_template(p, s, t.id)
        assert s.elements, t.id
        # všechny symboly existují a porty vodičů sedí
        for e in s.elements:
            lib.get_symbol(e.symbol_id)
        for w in s.wires:
            ea, eb = s.element(w.a.element_id), s.element(w.b.element_id)
            lib.get_symbol(ea.symbol_id).port(w.a.port)
            lib.get_symbol(eb.symbol_id).port(w.b.port)
            assert w.poles >= 1
        # označení bez duplicit (skupiny svorek jedné svorkovnice sdílejí ref – ty se liší čísly svorek)
        refs = [e.ref for e in s.elements if e.ref and e.symbol_id != "sb.terminal_block"]
        assert len(refs) == len(set(refs)), t.id
        terms = [(e.ref, n) for e in s.elements if e.symbol_id == "sb.terminal_block"
                 for n in e.attrs["terminal"].split()]
        assert len(terms) == len(set(terms)), t.id
        # můstky odkazují jen na existující svorky
        for strip, groups in s.bridges.items():
            for g in groups:
                assert all((strip, n) in terms for n in g), (t.id, strip, g)
        # přístroje s moduly jsou rozmístěné
        placed = {pl.element_id for pl in s.layout.placements}
        for e in s.elements:
            if e.modules > 0 and e.symbol_id != "sb.terminal_block":
                assert e.id in placed, (t.id, e.ref)


def test_layout_roundtrip_and_migration(tmp_path):
    p = Project()
    s = Sheet(kind="switchboard")
    p.sheets.append(s)
    a = Element("fve.breaker_mcb", 0, 0, attrs={"ref": "F1", "modules": "3", "poles": "3"})
    s.elements.append(a)
    s.layout.set_placement(a.id, 1, 6.0)
    s.wires.append(Wire(WireEnd(a.id, "1"), WireEnd(a.id, "2"), conductors=["L1", "L2", "L3"]))
    f = tmp_path / "p.ecp"
    p.save(f)
    q = Project.load(f)
    s2 = q.sheets[1]
    assert s2.layout.placement(a.id).row == 1 and s2.layout.placement(a.id).pos == 6.0
    assert s2.wires[0].conductors == ["L1", "L2", "L3"] and s2.wires[0].poles == 3
    assert s2.element(a.id).modules == 3.0 and s2.element(a.id).poles == 3
    s2.remove_element(a.id)
    assert s2.layout.placements == []

    # migrace v1 → aktuální
    old = {"format": "envocad-project", "format_version": 1, "name": "old",
           "sheets": [{"id": "s1", "name": "x", "elements": [], "wires": []}]}
    f1 = tmp_path / "old.ecp"
    f1.write_text(json.dumps(old), encoding="utf-8")
    o = Project.load(f1)
    assert o.sheets[0].kind == "schematic" and o.to_dict()["format_version"] == FORMAT_VERSION


def test_layout_params(tmp_path):
    from envocad.model.project import Layout
    lay = Layout(rows=3, modules_per_row=24, params={"width_mm": "600", "height_mm": "1000", "depth_mm": "250,5", "row_pitch_mm": ""})
    assert (lay.width_mm, lay.height_mm, lay.depth_mm) == (600, 1000, 250.5)
    assert lay.row_pitch_mm == (1000 - 50) / 3 and lay.total_modules == 72
    s = Sheet(kind="switchboard")
    s.layout = lay
    e = Element("fve.breaker_mcb", attrs={"ref": "F1", "modules": "3"})
    s.elements.append(e)
    lay.set_placement(e.id, 0, 0)
    assert lay.used_modules(s) == 3
    d = Layout.from_dict(lay.to_dict())
    assert d.params["depth_mm"] == "250,5" and d.placements[0].element_id == e.id
    empty = Layout()
    assert empty.width_mm == 24 * 17.5 + 50 and empty.row_pitch_mm >= 100


def test_thermal(tmp_path):
    from envocad.library.templates import apply_template
    from envocad.model.thermal import cooling_area, device_power_loss, temperature_rise
    p = Project()
    s = Sheet(kind="switchboard")
    p.sheets.append(s)
    apply_template(p, s, "ac_fve", {"n_out": "6", "i_out": "32", "i_main": "100"})
    f = next(e for e in s.elements if e.symbol_id == "fve.breaker_mcb")
    assert device_power_loss(f, rdf=1.0) == round(0.09 * 32 * 3, 2)
    f.attrs["p_loss_w"] = "9"
    assert device_power_loss(f, rdf=0.5) == 2.25
    a_wall = cooling_area(600, 1000, 250, "nástěnná")
    a_free = cooling_area(600, 1000, 250, "volně stojící")
    assert 0 < a_wall < a_free
    s.layout.params = {"width_mm": "550", "height_mm": "800", "depth_mm": "160", "mounting": "nástěnná", "material": "plast"}
    r = temperature_rise(s)
    assert r.p_total_w > r.p_devices_w > 0 and r.dt_top_k > r.dt_mid_k > 0 and r.verdict()
    big = Sheet(kind="switchboard")
    big.layout.params = {"width_mm": "1200", "height_mm": "2000", "depth_mm": "400"}
    big.elements = list(s.elements)
    assert temperature_rise(big).dt_top_k < r.dt_top_k  # větší skříň → menší oteplení


def test_switchboard_header():
    from envocad.model.project import switchboard_header
    p = Project(name="FVE Test", meta={"order": "Z-1"})
    s = Sheet(name="R1 – AC", kind="switchboard")
    s.layout.params = {"manufacturer": "Hager", "type": "VU36", "ip": "IP 44", "ik": "IK 08", "network": "TN-S",
                       "in_": "80", "width_mm": "550", "height_mm": "650"}
    rows = dict(switchboard_header(p, s))
    assert rows["Skříň"] == "Hager VU36" and rows["Krytí"] == "IP 44 / IK 08" and rows["In"] == "80 A"
    assert rows["Síť"] == "TN-S" and rows["Rozměry"].startswith("550 × 650")
    assert "Icw / Ipk" not in rows  # nevyplněné se vynechá


def test_feed_link_to_jps_wire():
    from envocad.library.templates import apply_template
    from envocad.model.project import feed_link_attrs, linked_wire, wire_choices, wire_xref
    p = Project(name="Link")
    s = p.sheets[0]
    t = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    s.elements += [t, blk]
    w = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "1"), attrs={"ref": "W2", "cable": "CYKY-J 5x16", "cross": "16"},
             conductors=["L1", "L2", "L3", "N", "PE"])
    s.wires.append(w)
    sb = p.create_switchboard_sheet(blk)
    assert [c[0] for c in wire_choices(p, sb)] == [w.id]
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    feed = next(e for e in sb.elements if is_feed_in(e))
    assert feed.attrs["wire_id"] == w.id and feed.attrs["from"].startswith("W2 T1:AC /1.") and feed.attrs["cable"] == "CYKY-J 5x16 16"
    assert linked_wire(p, sb, feed)[1] is w
    assert wire_xref(p, w.id) .startswith("→ R1:X1 /2.")
    assert feed_link_attrs(p, sb, feed, "") == {"wire_id": "", "from": "", "cable": ""}
    out = next(e for e in sb.elements if is_feed_out(e))
    assert feed_link_attrs(p, sb, out, "") == {"wire_id": "", "to": "", "cable": ""}
    # seznam kabelů celého projektu: kabel je jen jednou (W2 v JPS) a má odkaz na rozvaděč
    from envocad.export import reports
    _, rows = reports.cables(p, LibraryStore())
    assert [r[0] for r in rows] == ["W2"] and rows[0][8].startswith("R1:X1 /2.")


def test_switchboard_block_ports_follow_feeds():
    from envocad.library.templates import apply_template
    from envocad.model.project import element_symbol, feeds_linked_to, linked_wire, sync_feed_links, wire_xref
    lib = LibraryStore()
    p = Project(name="Blok")
    s = p.sheets[0]
    t = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    load = Element("fve.load", 200, 150, attrs={"ref": "M1"})
    s.elements += [t, blk, load]
    w_in = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "1"), attrs={"ref": "W2", "cable": "CYKY-J 5x16"},
                conductors=["L1", "L2", "L3", "N", "PE"])
    s.wires.append(w_in)
    assert [pt.name for pt in element_symbol(p, blk, lib).ports] == ["1", "2", "3", "4"]  # bez listu základní
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    sym = element_symbol(p, blk, lib)
    assert [pt.name for pt in sym.ports] == ["X1", "X4", "X5", "X6"]   # přívod vlevo, vývody vpravo
    assert w_in.b.port == "X1"                                           # vodič přejmenovaný na port přívodu
    assert sym.port("X1").dir == "W" and sym.port("X4").dir == "E"
    # nový vodič na port X4 → vývod X4 se naváže sám (podle jména portu)
    w_out = Wire(WireEnd(blk.id, "X4"), WireEnd(load.id, "1"), attrs={"ref": "W3", "cable": "CYKY-J 5x6", "cross": "6"},
                 conductors=["L1", "L2", "L3", "N", "PE"])
    s.wires.append(w_out)
    x4 = next(e for e in sb.elements if e.ref == "X4")
    assert linked_wire(p, sb, x4)[1] is w_out
    assert wire_xref(p, w_out.id).startswith("→ R1:X4 /2.") and [e.ref for _, e in feeds_linked_to(p, w_out.id)] == ["X4"]
    assert sync_feed_links(p) >= 1
    assert x4.attrs["to"].startswith("W3 M1:1 /1.") and x4.attrs["cable"] == "CYKY-J 5x6 6" and x4.attrs["wire_id"] == w_out.id
    assert sync_feed_links(p) == 0
    # starý port zůstane jen dokud na něj něco vede
    w_old = Wire(WireEnd(blk.id, "3"), WireEnd(load.id, "1"))
    s.wires.append(w_old)
    assert "3" in [pt.name for pt in element_symbol(p, blk, lib).ports]
    s.wires.remove(w_old)
    assert "3" not in [pt.name for pt in element_symbol(p, blk, lib).ports]


def test_block_follows_switchboard_edits():
    """Změny v rozvaděči (nový vývod, přejmenování, smazání) se promítnou do portů bloku v JPS."""
    from envocad.library.templates import apply_template
    from envocad.model.project import element_symbol, sync_feed_links
    lib = LibraryStore()
    p = Project(name="Edit")
    s = p.sheets[0]
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    load = Element("fve.load", 200, 150, attrs={"ref": "M1"})
    s.elements += [blk, load]
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    ports = lambda: [pt.name for pt in element_symbol(p, blk, lib).ports]
    assert ports() == ["X1", "X4", "X5", "X6"]
    # nový vývod v rozvaděči → nový port
    sb.elements.append(Element("sb.feed", 300, 100, attrs={"dir": "out", "ref": "X7", "desc": "vývod 4"}))
    assert ports() == ["X1", "X4", "X5", "X6", "X7"]
    # vodič v JPS na X4, pak přejmenování vývodu X4 → X8: konec vodiče se přejmenuje
    w = Wire(WireEnd(blk.id, "X4"), WireEnd(load.id, "1"), attrs={"ref": "W3"})
    s.wires.append(w)
    sync_feed_links(p)
    x4 = next(e for e in sb.elements if e.ref == "X4")
    assert x4.attrs["wire_id"] == w.id
    x4.attrs["ref"] = "X8"
    sync_feed_links(p)
    assert w.a.port == "X8" and "X8" in ports() and "X4" not in ports()
    # smazání vývodu s napojeným vodičem: port zůstane označený otazníkem, nic nespadne
    sb.elements.remove(x4)
    sync_feed_links(p)
    sym = element_symbol(p, blk, lib)
    assert "X8" in [pt.name for pt in sym.ports] and sym.port("X8").dir == "S"
    assert any(pr.get("text") == "X8?" for pr in sym.primitives)


def test_switchboard_sheet_gets_location_and_structure():
    from envocad.model.project import StructureId
    p = Project()
    block = Element("fve.switchboard", 100, 100, attrs={"ref": "RDC1", "desc": "DC rozvaděč"})
    p.sheets[0].elements.append(block)
    s = p.create_switchboard_sheet(block)
    assert s.loc == "RDC1" and s.func == ""
    assert p.structures == [StructureId("+", "RDC1", "DC rozvaděč")]
    assert p.structure("+", "RDC1") is p.structures[0] and p.structure("=", "RDC1") is None
    # druhý blok se stejným označením strukturu nezdvojí
    b2 = Element("fve.switchboard", 200, 100, attrs={"ref": "RDC1"})
    p.sheets[0].elements.append(b2)
    p.create_switchboard_sheet(b2)
    assert len(p.structures) == 1
    # blok bez označení → anonymní list, nic se neregistruje
    b3 = Element("fve.switchboard", 300, 100)
    p.sheets[0].elements.append(b3)
    assert p.create_switchboard_sheet(b3).loc == "" and len(p.structures) == 1


def test_used_refs_by_scope():
    p = Project()
    jps = p.sheets[0]
    b1 = Element("fve.switchboard", attrs={"ref": "RDC1"})
    b2 = Element("fve.switchboard", attrs={"ref": "RH"})
    f_jps = Element("fve.breaker_mcb", attrs={"ref": "F1"})
    jps.elements += [b1, b2, f_jps]
    s1, s2 = p.create_switchboard_sheet(b1), p.create_switchboard_sheet(b2)
    s1.elements.append(Element("sb.terminal_block", attrs={"ref": "X1"}))
    s2.elements.append(Element("fve.breaker_mcb", attrs={"ref": "F7"}))
    s2.elements.append(Element("fve.breaker_mcb", attrs={"ref": "F8", "loc": "RDC1"}))   # override do RDC1
    jps.wires.append(Wire(WireEnd(b1.id, "1"), WireEnd(f_jps.id, "1"), attrs={"ref": "W1"}))
    s1.wires.append(Wire(WireEnd("a", "1"), WireEnd("b", "1"), attrs={"ref": "W9"}))
    assert p.used_refs(s1) == {"X1", "F8", "W9"}
    assert p.used_refs(s2) == {"F7"}
    assert p.used_refs(jps) == {"RDC1", "RH", "F1", "W1"}
    assert {"X1", "F7", "F8", "W1", "W9", "F1"} <= p.used_refs()
    # list se stejným umístěním sdílí prostor
    extra = Sheet(name="RDC1 – pokračování", kind="switchboard", loc="RDC1")
    p.sheets.append(extra)
    assert p.used_refs(extra) == {"X1", "F8", "W9"}


def test_rename_structure_is_invertible():
    from envocad.model.project import StructureId, rename_structure
    p = Project()
    blk = Element("fve.switchboard", attrs={"ref": "RDC1"})
    p.sheets[0].elements.append(blk)
    p.sheets[0].func = "AC"
    sb = p.create_switchboard_sheet(blk)
    g = Element("fve.pv_string", attrs={"ref": "G1", "loc": "RDC1"})
    p.sheets[0].elements.append(g)
    p.structures.append(StructureId("=", "AC", "Střídavá část"))
    before = p.to_dict()
    assert rename_structure(p, "+", "RDC1", "RS1") == 3      # registr, list, override prvku
    assert sb.loc == "RS1" and g.attrs["loc"] == "RS1" and p.structure("+", "RS1") is not None
    assert blk.ref == "RDC1"                                   # ref bloku mění UI zvlášť (SetAttrCommand)
    assert rename_structure(p, "=", "AC", "DC") == 2 and p.sheets[0].func == "DC"
    assert rename_structure(p, "=", "DC", "DC") == 0
    g.attrs["func"] = "XX"                                     # použitý kód mimo registr také blokuje
    with pytest.raises(ValueError):
        rename_structure(p, "=", "DC", "XX")
    del g.attrs["func"]
    p.structures.append(StructureId("+", "RH"))
    with pytest.raises(ValueError, match="už v projektu existuje"):
        rename_structure(p, "+", "RS1", "RH")
    with pytest.raises(ValueError):
        rename_structure(p, "?", "RS1", "X")
    p.structures.pop()
    rename_structure(p, "=", "DC", "AC")
    rename_structure(p, "+", "RS1", "RDC1")
    assert p.to_dict() == before


def test_structures_and_revisions_roundtrip():
    from envocad.model.project import Revision, RevisionMark, StructureId
    p = Project()
    p.sheets[0].func, p.sheets[0].loc = "AC", "STR"
    p.structures = [StructureId("=", "AC", "Střídavá část"), StructureId("+", "STR")]
    rev = Revision("B", date="2026-10-01", author="PR", description="Změna jističe",
                   marks=[RevisionMark(p.sheets[0].id, "e1", kind="přidáno"),
                          RevisionMark(p.sheets[0].id, kind="odebráno", x=12.5, y=-5.0, text="F9")],
                   fingerprints={p.sheets[0].id: "abc"})
    p.revisions = [Revision("A", closed=True), rev]
    d = p.to_dict()
    assert d["format_version"] == FORMAT_VERSION == 16
    q = Project.from_dict(json.loads(json.dumps(d)))
    assert q.to_dict() == d
    assert q.sheets[0].func == "AC" and q.sheets[0].loc == "STR"
    assert q.structures == p.structures
    assert q.revisions[1].marks[1].x == 12.5 and q.revisions[1].marks[0].x is None
    assert q.revisions[1].fingerprints == {p.sheets[0].id: "abc"} and q.revisions[0].closed
