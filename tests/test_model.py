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
    assert lib.list_components("fve.inverter")[0]["part_number"] == "STP 50-40"


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
