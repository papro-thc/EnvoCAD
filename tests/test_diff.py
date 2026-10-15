"""Porovnání revizí (bez Qt)."""

from envocad.generate import build_project
from envocad.model.diff import change_list_text, diff_projects, summary
from envocad.model.project import Element, Project


def test_diff_projects(tmp_path):
    spec = {"name": "Diff", "inverters": [{"ref": "T1", "p_ac": 25, "strings": [20, 20]}],
            "dc": {"route_boxes": 0, "tech_box": False, "disconnect": True}, "ac": {"distribution": "terminals"}}
    p1 = build_project(spec)
    p1.save(tmp_path / "r0.ecp")
    p2 = Project.load(tmp_path / "r0.ecp")
    assert diff_projects(p1, p2) == []
    s = p2.sheets[0]
    f1 = next(e for e in s.elements if e.symbol_id == "fve.dc_disconnect")
    f1.attrs["in_"] = "40"
    s.elements.append(Element("fve.meter", 200, 100, attrs={"ref": "P1"}))
    w = s.wires[0]
    w.attrs["cross"] = "10"
    w.conductors = ["DC+", "DC-"]
    removed = s.wires.pop()  # kabel do HDS
    p2.set_bridges("X2", [["1", "6"]], p2.sheets[1])
    from envocad.model.project import sync_cables
    sync_cables(p2)
    ch = diff_projects(p1, p2)
    kinds = {(c.kind, c.what, c.ref) for c in ch}
    assert ("změněno", "prvek", f1.ref) in kinds
    assert ("přidáno", "prvek", "P1") in kinds
    assert ("změněno", "vodič", w.attrs["ref"]) in kinds
    assert ("odebráno", "vodič", removed.attrs["ref"]) in kinds
    assert ("změněno", "můstky", "X2") in kinds
    assert any(c.what == "kabel" and c.kind == "odebráno" for c in ch) or any(c.what == "kabel" for c in ch)
    assert "in_: 32 → 40" in next(c.detail for c in ch if c.ref == f1.ref and c.what == "prvek")
    txt = change_list_text(ch, "1", "16.10.2026", "PR")
    assert txt.startswith("1 | 16.10.2026 | ") and txt.count("\n") == len(ch) - 1
    assert "přidáno" in summary(ch)
