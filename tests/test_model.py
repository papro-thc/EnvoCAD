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
    s.wires.append(Wire(WireEnd(g.id, "DC+"), WireEnd(t.id, "DC+"), attrs={"ref": "W1"}))
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
    s.wires.append(Wire(WireEnd(a.id, "DC+"), WireEnd(b.id, "DC+"), attrs={"ref": "W1"}))
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
