import json

from envocad.library.store import LibraryStore
from envocad.library.templates import TEMPLATES, apply_template
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
        # označení bez duplicit
        refs = [e.ref for e in s.elements if e.ref]
        assert len(refs) == len(set(refs)), t.id
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
