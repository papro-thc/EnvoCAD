from pathlib import Path

from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Sheet, Wire, WireEnd
from envocad.model.symbol import rotate_dir, rotate_point


def test_rotate():
    assert rotate_point(10, 0, 90) == (0, 10)
    assert rotate_point(10, 0, 180) == (-10, 0)
    assert rotate_dir("E", 90) == "N"
    assert rotate_dir("N", 90) == "W"
    assert rotate_dir("W", 270) == "N"


def test_builtin_symbols_valid(tmp_path):
    lib = LibraryStore(tmp_path / "lib.db")
    ids = [s[0] for s in lib.list_symbols()]
    assert len(ids) >= 15
    for sid in ids:
        sym = lib.get_symbol(sid)
        assert sym.validate() == [], sid
        assert any(a.key == "ref" for a in sym.attributes)


def test_project_roundtrip(tmp_path):
    lib = LibraryStore(tmp_path / "lib.db")
    p = Project(name="Test FVE")
    s = p.sheets[0]
    g = Element("fve.pv_string", 20, 100, attrs={"ref": "G1"})
    t = Element("fve.inverter", 80, 100, rotation=90, attrs={"ref": "T1", "p_ac": "50"})
    s.elements += [g, t]
    s.wires.append(Wire(WireEnd(g.id, "DC"), WireEnd(t.id, "DC1"), attrs={"ref": "W1"}))
    f = tmp_path / "t.ecp"
    p.save(f)
    q = Project.load(f)
    assert q.name == "Test FVE"
    assert len(q.sheets[0].elements) == 2 and len(q.sheets[0].wires) == 1
    assert q.sheets[0].element(t.id).rotation == 90
    assert q.next_ref("T") == "T2" and q.next_ref("G") == "G2"
    # pozice portu po rotaci
    x, y = t.port_pos(lib.get_symbol("fve.inverter"), "AC")  # port (10,0) → rot 90 → (0,10)
    assert (x, y) == (80, 110)


def test_remove_element_drops_wires():
    s = Sheet()
    a, b = Element("fve.fuse"), Element("fve.fuse")
    s.elements += [a, b]
    s.wires.append(Wire(WireEnd(a.id, "2"), WireEnd(b.id, "1")))
    removed = s.remove_element(a.id)
    assert len(removed) == 1 and s.wires == [] and len(s.elements) == 1


def test_components_csv(tmp_path):
    lib = LibraryStore(tmp_path / "lib.db")
    csv = tmp_path / "c.csv"
    csv.write_text("id;manufacturer;part_number;name;symbol_id;price;p_ac\n"
                   "sma-stp50;SMA;STP 50-40;Sunny Tripower CORE1;fve.inverter;85000;50\n", encoding="utf-8")
    assert lib.import_components_csv(csv) == 1
    c = lib.get_component("sma-stp50")
    assert c["params"]["p_ac"] == "50" and c["price"] == 85000.0
    assert any(c["part_number"] == "STP 50-40" for c in lib.list_components("fve.inverter"))


def test_dxf_import_export(tmp_path):
    import ezdxf

    from envocad.export.dxf_export import export_sheet_dxf
    from envocad.library.dxf_import import import_dxf

    doc = ezdxf.new()
    blk = doc.blocks.new("INV")
    blk.add_line((0, 0), (10, 10))
    blk.add_circle((5, 5), 2)
    doc.modelspace().add_blockref("INV", (100, 100))
    doc.modelspace().add_text("X").set_placement((0, 0))
    src = tmp_path / "in.dxf"
    doc.saveas(src)

    sym = import_dxf(src, "test.inv", "Test", block="INV", snap=True)
    assert {p["type"] for p in sym.primitives} == {"line", "circle"}
    sym2 = import_dxf(src, "test.ms", "Test2")  # modelspace vč. INSERT a TEXT
    assert {p["type"] for p in sym2.primitives} == {"line", "circle", "text"}

    lib = LibraryStore(tmp_path / "lib.db")
    lib.put_symbol(sym)
    p = Project()
    s = p.sheets[0]
    a = Element("fve.pv_string", 20, 100, attrs={"ref": "G1"})
    b = Element("fve.inverter", 80, 120, attrs={"ref": "T1"})
    s.elements += [a, b]
    s.wires.append(Wire(WireEnd(a.id, "DC"), WireEnd(b.id, "DC1"), attrs={"ref": "W1"}))
    out = tmp_path / "out.dxf"
    export_sheet_dxf(p, s, lib, out)
    d = ezdxf.readfile(out)
    types = [e.dxftype() for e in d.modelspace()]
    assert "LWPOLYLINE" in types and "TEXT" in types and "LINE" in types
    assert Path(out).stat().st_size > 1000


def test_wire_label_anchor():
    from envocad.model.geometry import longest_segment, wire_label_anchor
    horiz = [(0, 0), (2.5, 0), (40, 0), (40, 5), (42.5, 5)]
    assert longest_segment(horiz) == ((2.5, 0), (40, 0))
    x, y, align, vert = wire_label_anchor(horiz)
    assert (x, align, vert) == (21.25, "center", False) and y > 0
    vert_pts = [(10, 0), (10, -2.5), (10, -60), (12.5, -60)]
    x, y, align, vert = wire_label_anchor(vert_pts)
    assert align == "left" and vert and x > 10


def test_qet_import(tmp_path):
    from envocad.library.qet_import import parse_elmt
    elmt = tmp_path / "x.elmt"
    elmt.write_text("""<definition version="0.100.0" type="element" width="30" height="60" hotspot_x="15" hotspot_y="30">
<names><name lang="cs">Jistič test</name><name lang="en">Breaker</name></names>
<kindInformations><kindInformation name="type">protection</kindInformation></kindInformations>
<informations>Author: Tester</informations>
<description>
<line x1="0" y1="-30" x2="0" y2="-10" style="" antialias="false"/>
<rect x="-5" y="-10" width="10" height="20" style=""/>
<circle x="-5" y="20" diameter="10" style=""/>
<arc x="-10" y="-10" width="20" height="20" start="0" angle="90" style=""/>
<polygon x1="0" y1="10" x2="5" y2="15" x3="0" y3="20" closed="false" style=""/>
<text text="I&gt;" x="2" y="0" font="Liberation Sans,9,-1,5,50,0,0,0,0,0,Regular"/>
<dynamic_text x="20" y="-10" text_from="ElementInfo"><text></text><info_name>label</info_name></dynamic_text>
<terminal x="0" y="-30" orientation="n" name="1"/>
<terminal x="0" y="30" orientation="s" name="2"/>
</description></definition>""", encoding="utf-8")
    s = parse_elmt(elmt, "qet.test", "QET/Test")
    assert s.name == "Jistič test" and s.iec_ref == "F" and "Tester" in s.description
    assert {p["type"] for p in s.primitives} == {"line", "rect", "circle", "arc", "polyline", "text"}
    assert [(p.name, p.x, p.y, p.dir) for p in s.ports] == [("1", 0.0, 7.5, "N"), ("2", 0.0, -7.5, "S")]
    assert s.validate() == []
    assert s.label_pos[0] > 0


def test_eplan_import_heuristics(tmp_path):
    from envocad.library.components import validate
    from envocad.library.eplan_import import (
        rows_from_commercial_csv,
        rows_from_parts_xml,
        write_components_csv,
    )
    (tmp_path / "c.csv").write_text("Part number;Manufacturer;Description;Width;Rated current;Product group\n"
                                    "LTN-16B-3;OEZ;Jistič LTN 16B 3p;52,5;16 A;Leitungsschutzschalter\n", encoding="utf-8")
    rows, mapping = rows_from_commercial_csv(tmp_path / "c.csv")
    assert mapping["part_number"] == "Part number" and rows[0]["category"] == "mcb"
    assert rows[0]["in_"] == "16" and rows[0]["modules"] == "3"
    (tmp_path / "p.xml").write_text('<Parts><Part P_ARTICLE_PARTNR="MCN116" P_ARTICLE_MANUFACTURER="Hager" '
                                    'P_ARTICLE_DESCR1="Jistič" P_ARTICLE_POWERDISSIPATION="2.32" P_ARTICLE_PRODUCTGROUP="MCB"/></Parts>',
                                    encoding="utf-8")
    rows2, _ = rows_from_parts_xml(tmp_path / "p.xml")
    assert rows2[0]["p_loss_w"] == "2.32" and rows2[0]["id"] == "hager-mcn116"
    write_components_csv(rows + rows2, tmp_path / "o.csv")
    assert validate(tmp_path / "o.csv") == []


def test_frame_geometry_and_copy_paste():
    from envocad.model.frame import frame_geometry, sheet_number
    from envocad.model.project import Element, Project, Wire, WireEnd, copy_fragment, paste_fragment
    p = Project(name="Test")
    p.meta.update(order="2026-001", author="PR")
    s = p.sheets[0]
    g = frame_geometry(p, s)
    assert g.inner == (20.0, 10.0, s.width - 10.0, s.height - 10.0)
    texts = {t[2] for t in g.texts}
    assert {"Test", "2026-001", "PR", "ENVO", "1/1", "A3"} <= texts
    assert sheet_number(p, s) == "1/1"
    a = Element("fve.breaker_mcb", 50, 100, attrs={"ref": "F1", "in_": "16"})
    b = Element("fve.load", 100, 100, attrs={"ref": "M1"})
    x = Element("sb.terminal_block", 75, 120, attrs={"ref": "X1", "terminal": "1 2 3"})
    s.elements += [a, b, x]
    s.wires.append(Wire(WireEnd(a.id, "2"), WireEnd(b.id, "1"), attrs={"ref": "W1"}, conductors=["L1", "N", "PE"],
                        terminals={"L1": {"a": "F1:2"}}))
    frag = copy_fragment(s, [a.id, b.id, x.id])
    assert len(frag["elements"]) == 3 and len(frag["wires"]) == 1
    prefix = {"fve.breaker_mcb": "F", "fve.load": "", "sb.terminal_block": "X"}
    els, wires = paste_fragment(p, frag, lambda sid: prefix[sid], 10, -10)
    refs = {e.ref for e in els}
    assert "F2" in refs and "X1" in refs and "M1" in refs   # M1 bez prefixu zůstává
    xe = next(e for e in els if e.symbol_id == "sb.terminal_block")
    assert xe.attrs["terminal"] == ""
    assert els[0].x == 60 and els[0].y == 90 and els[0].id != a.id
    assert wires[0].attrs["ref"] == "W2" and wires[0].conductors == ["L1", "N", "PE"] and wires[0].terminals == {}
    assert wires[0].a.element_id == els[0].id


def test_grid_coords_and_interrupt_points():
    from envocad.library.store import LibraryStore
    from envocad.model.checks import check_project
    from envocad.model.frame import frame_geometry, grid_coord, position_ref
    from envocad.model.project import (
        Element,
        Project,
        Sheet,
        Wire,
        WireEnd,
        element_xref,
        interrupt_partner,
        wire_xref,
    )
    p = Project(name="Síť")
    s1 = p.sheets[0]
    s2 = Sheet(name="List 2")
    p.sheets.append(s2)
    assert grid_coord(s1, 25, 280) == "A1" and grid_coord(s1, 400, 20) == "H6"
    assert position_ref(p, s2, 210, 150) == "/2.D3"
    g = frame_geometry(p, s1)
    assert {t[2] for t in g.texts} >= set("ABCDEFGH") | {"1", "6"}
    a = Element("fve.interrupt", 300, 150, attrs={"ref": "L1-A"})
    b = Element("fve.interrupt", 60, 200, rotation=180, attrs={"ref": "L1-A"})
    lone = Element("fve.interrupt", 60, 100, attrs={"ref": "N-X"})
    s1.elements.append(a)
    s2.elements += [b, lone]
    assert interrupt_partner(p, a)[1] is b
    assert element_xref(p, s1, a) == "→ /2.A2" and element_xref(p, s2, b) == "→ /1.F3"
    assert element_xref(p, s2, lone) == "→ ?"
    assert any(f.code == "interrupt_alone" and f.ref == "N-X" for f in check_project(p, LibraryStore()))
    # křížový odkaz vodiče na vývod má i souřadnici
    t = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    s1.elements += [t, blk]
    sb = p.create_switchboard_sheet(blk)
    sb.elements.append(Element("sb.feed_in", 40, 250, attrs={"ref": "X1"}))
    w = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X1"), attrs={"ref": "W2"})
    s1.wires.append(w)
    assert wire_xref(p, w.id).startswith("→ R1:X1 /3.")


def test_coil_contacts_mirror():
    from envocad.export import reports
    from envocad.library.store import LibraryStore
    from envocad.model.checks import check_project
    from envocad.model.multipole import default_conductors
    from envocad.model.project import Element, Project, Sheet, coil_of, contact_mirror, element_xref
    p = Project(name="Ovládání")
    s1 = p.sheets[0]
    s2 = Sheet(name="Ovládací obvody")
    p.sheets.append(s2)
    k1 = Element("ctl.coil", 100, 100, attrs={"ref": "K1", "desc": "NS ochrana"})
    c_no = Element("ctl.contact_no", 200, 150, attrs={"ref": "K1"})
    c_pw = Element("ctl.contact_power", 150, 150, attrs={"ref": "K1", "poles": "3"})
    lone = Element("ctl.contact_nc", 250, 150, attrs={"ref": "K9"})
    s2.elements.append(k1)
    s1.elements += [c_no, c_pw, lone]
    assert coil_of(p, c_no)[1] is k1 and coil_of(p, lone) is None
    assert contact_mirror(p, k1) == [("1/2", "/1.C3"), ("13/14", "/1.D3")]
    assert element_xref(p, s2, k1) == "1/2 /1.C3\n13/14 /1.D3"
    assert element_xref(p, s1, c_no) == "→ /2.B5" and element_xref(p, s1, lone) == "→ ?"
    assert "K1" in p.used_refs() and p.next_ref("K") == "K2"   # kontakty označení neblokují ani nezdvojují
    assert default_conductors(k1, "A1", c_no, "14") == ["L"]
    codes = {(f.code, f.ref) for f in check_project(p, LibraryStore())}
    assert ("contact_alone", "K9") in codes and not any(c == "dup_ref" for c, _ in codes)
    _, rows = reports.device_list(p, LibraryStore())
    k = next(r for r in rows if r[0] == "K1")
    assert k[5] == "1/2, 13/14"
    _, bom = reports.bom(p, LibraryStore())
    assert not any("Kontakt" in r[1] for r in bom)


def test_potentials_and_branch():
    from envocad.library.store import LibraryStore
    from envocad.model.checks import ERROR, check_project
    from envocad.model.potential import junction_free_port, net_of_wire, nets, split_wire
    from envocad.model.project import Element, Project, Wire, WireEnd
    p = Project()
    s = p.sheets[0]
    lib = LibraryStore()
    feed = Element("sb.feed_in", 50, 200, attrs={"ref": "X1"})
    f1 = Element("fve.breaker_mcb", 100, 200, attrs={"ref": "F1", "poles": "1"})
    f2 = Element("fve.breaker_mcb", 100, 150, attrs={"ref": "F2", "poles": "1"})
    s.elements += [feed, f1, f2]
    w = Wire(WireEnd(feed.id, "1"), WireEnd(f1.id, "1"), conductors=["L1", "N", "PE"], attrs={"ref": "W1", "cable": "CYKY-J 3x2.5"})
    s.wires.append(w)
    # T-odbočka: vodič se rozdělí uzlem, z uzlu vede druhý vodič k F2
    j, w1, w2 = split_wire(s, w, 75, 200)
    s.wires.remove(w)
    s.elements.append(j)
    s.wires += [w1, w2]
    assert w1.attrs["ref"] == "W1" and w2.attrs["ref"] == "" and w1.conductors == w2.conductors == ["L1", "N", "PE"]
    port = junction_free_port(s, j, (100, 150))
    assert port and port not in (w1.b.port, w2.a.port)
    wb = Wire(WireEnd(j.id, port), WireEnd(f2.id, "1"), conductors=["L1", "N", "PE"], attrs={"ref": "W2"})
    s.wires.append(wb)
    ns = nets(p, lib)
    l1 = next(n for n in ns if "L1" in n.conductors)
    assert {e.ref for _, e, _, _ in l1.members} >= {"X1", "F1", "F2"} and l1.name == "L1 (W1)"
    assert net_of_wire(p, lib, wb.id)["N"].name == next(n for n in ns if "N" in n.conductors).name == "N (W1)"
    assert not [f for f in check_project(p, lib) if f.code in ("pot_short", "junction_free")]
    # zkrat potenciálů: N spojené s L1 přes další uzel
    bad = Wire(WireEnd(f1.id, "2"), WireEnd(f2.id, "2"), conductors=["L1"], attrs={"ref": "W3"})
    s.wires.append(bad)
    bad2 = Wire(WireEnd(f1.id, "2"), WireEnd(f2.id, "2"), conductors=["N"], attrs={"ref": "W4"})
    s.wires.append(bad2)
    fs = [f for f in check_project(p, lib) if f.code == "pot_short"]
    assert fs and fs[0].severity == ERROR and "N spojeno s L1" in fs[0].text


def test_macros_roundtrip(tmp_path, monkeypatch):
    from envocad.library import macros
    from envocad.library.store import LibraryStore
    from envocad.model.project import Element, Project, Wire, WireEnd, copy_fragment, paste_fragment
    monkeypatch.setattr(macros, "user_dir", lambda: tmp_path / "m")
    monkeypatch.setattr(macros, "shared_dir", lambda: None)
    builtin = macros.list_macros()
    assert len(builtin) >= 3 and all(m.source == "vestavěné" for m in builtin)
    p = Project()
    s = p.sheets[0]
    a = Element("fve.breaker_mcb", 100, 100, attrs={"ref": "F1", "in_": "16"})
    b = Element("sb.terminal_block", 100, 70, attrs={"ref": "X2", "terminal": "1 2 3"})
    s.elements += [a, b]
    s.wires.append(Wire(WireEnd(a.id, "2"), WireEnd(b.id, "1"), conductors=["L1", "N", "PE"]))
    path = macros.save_macro("Můj vývod", "test", copy_fragment(s, [a.id, b.id]))
    assert path.exists() and path.parent == tmp_path / "m"
    mine = next(m for m in macros.list_macros() if m.name == "Můj vývod")
    assert mine.source == "vlastní" and mine.size == 2
    lib = LibraryStore()
    els, wires = paste_fragment(p, mine.fragment, lambda sid: lib.get_symbol(sid).iec_ref, 50, 0)
    assert [e.ref for e in els] == ["F2", "X2"] and len(wires) == 1 and els[0].x == 150
    assert macros.delete_macro(mine) and not path.exists()
    assert not macros.delete_macro(builtin[0]) and builtin[0].path.exists()


def test_text_layout_avoids_and_reports_overlaps():
    from envocad.library.store import LibraryStore
    from envocad.model.project import Element, Project, Sheet, Wire, WireEnd
    from envocad.model.textlayout import boxes_overlap, compute_layout, text_overlaps
    lib = LibraryStore()
    p, s = Project(), Sheet()
    p.sheets.append(s)
    a = Element("fve.dc_disconnect", 60, 100, attrs={"ref": "Q1", "in_": "32"})
    b = Element("fve.dc_disconnect", 62.5, 100, attrs={"ref": "Q2", "in_": "32"})   # výchozí popisky přes sebe
    g = Element("fve.pv_string", 20, 60, attrs={"ref": "G1", "n_modules": "18"})
    t = Element("fve.dc_disconnect", 90, 60, attrs={"ref": "Q3"})
    s.elements += [a, b, g, t]
    s.wires.append(Wire(WireEnd(g.id, "DC"), WireEnd(t.id, "1"), conductors=["DC+", "DC-"],
                        attrs={"ref": "W1", "cable": "H1Z2Z2-K 1x6", "cross": "6"}))
    lay = compute_layout(p, s, lib)
    assert not any(boxes_overlap(x, y) for x in lay.elements[a.id].boxes for y in lay.elements[b.id].boxes)
    # bez automatiky se překryv nahlásí
    assert any("Q1" in m and "Q2" in m for _, _, m in text_overlaps(p, s, lib, compute_layout(p, s, lib, auto=False)))
    assert not [m for _, _, m in text_overlaps(p, s, lib) if "Q1" in m and "Q2" in m]


def test_symbol_function_class(tmp_path):
    from envocad.model.symbol import Symbol
    s = Symbol("x", "X", iec_ref="F")
    assert s.function_class is None and s.classes == ["F"]
    assert "function_class" not in s.to_dict()                   # bez klíče = odvodit z iec_ref
    assert Symbol("y", "Y").classes == []                         # prázdný iec_ref = nekontrolovat
    s.function_class = ["F", "Q"]
    d = s.to_dict()
    assert d["function_class"] == ["F", "Q"] and Symbol.from_dict(d).classes == ["F", "Q"]
    assert Symbol.from_dict({**d, "function_class": []}).classes == []
    assert s.validate() == []
    bad = Symbol("z", "Z", iec_ref="F", function_class=["Q", "fx"])
    issues = bad.validate()
    assert any("fx" in i for i in issues) and any("prefix" in i for i in issues)
    assert Symbol("r", "R", iec_ref="R", function_class=[]).validate() == []
    # vestavěné značky dle návrhu v8
    lib = LibraryStore(tmp_path / "lib.db")
    expected = {"fve.breaker_mcb": ["F", "Q"], "fve.breaker_mccb": ["Q", "F"], "fve.fuse_disconnect": ["F", "Q"],
                "fve.contactor": ["K", "Q"], "sb.rcd": ["F", "Q"], "sb.rcbo": ["F", "Q"], "fve.switchboard": []}
    for sid, cls in expected.items():
        assert lib.get_symbol(sid).function_class == cls, sid
    assert lib.get_symbol("fve.inverter").function_class is None and lib.get_symbol("fve.inverter").classes == ["T"]


def test_derived_symbols_keep_function_class(tmp_path):
    from envocad.model.project import element_symbol
    lib = LibraryStore(tmp_path / "lib.db")
    p = Project()
    blk = Element("fve.switchboard", attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    sb.elements.append(Element("sb.feed_in", attrs={"ref": "X1"}))
    assert element_symbol(p, blk, lib).classes == []              # odvozená značka bloku nezačne kontrolovat „R“
