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
