"""Generování projektu ze specifikace (bez Qt)."""

from envocad.generate import DEFAULT_SPEC, build_project
from envocad.library.store import LibraryStore
from envocad.model.checks import ERROR, WARNING, check_project
from envocad.model.project import element_symbol


def test_build_project_from_spec(tmp_path):
    spec = {"name": "FVE Test", "meta": {"investor": "Test s.r.o."},
            "module": {"p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9},
            "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000,
                           "i_mppt_max": 30, "strings": [20, 20, 18]},
                          {"ref": "T2", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000,
                           "i_mppt_max": 30, "strings": [20, 20]}],
            "ac": {"breaker_in": 50, "main_in": 125}}
    p = build_project(spec)
    s = p.sheets[0]
    assert len(p.sheets) == 6 and all(sh.is_switchboard for sh in p.sheets[1:])  # 2 střídače × (po trase + u technologie) + AC
    assert len([e for e in s.elements if e.symbol_id == "fve.pv_string"]) == 5
    assert p.meta["p_installed_kwp"] == "44.1"
    lib = LibraryStore()
    blk = next(e for e in s.elements if e.symbol_id == "fve.switchboard")
    assert [pt.name for pt in element_symbol(p, blk, lib).ports] == ["X1", "X2", "XOUT"]
    # přívody rozvaděče jsou navázané na AC vodiče střídačů, kabely jako objekty
    sb = p.sheets[1]
    feeds = [e for e in sb.elements if e.symbol_id == "sb.feed_in"]
    assert all(f.attrs.get("wire_id") for f in feeds) and len(p.cables) >= 8
    fs = check_project(p, lib)
    assert not [f for f in fs if f.severity in (ERROR, WARNING)], [f.text for f in fs if f.severity != "info"]
    p.save(tmp_path / "g.ecp")
    assert (tmp_path / "g.ecp").stat().st_size > 1000


def test_build_requires_inverters():
    import pytest
    with pytest.raises(ValueError):
        build_project(dict(DEFAULT_SPEC))


def test_tz_and_dso(tmp_path):
    from docx import Document

    from envocad.export.reports import dso_report
    from envocad.export.tz_export import dso_data, export_tz_docx
    spec = {"name": "FVE TZ", "meta": {"investor": "Inv", "place": "Brno"},
            "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "strings": [20, 20]}],
            "grid": {"dso": "EG.D"}}
    p = build_project(spec)
    d = dict(dso_data(p, LibraryStore()))
    assert d["Distributor"] == "EG.D" and d["Instalovaný výkon FV (DC)"].startswith("18 kWp") and "25 kW" in d["Instalovaný výkon střídačů (AC)"]
    assert dso_report(p, LibraryStore())[1]
    out = tmp_path / "tz.docx"
    export_tz_docx(p, LibraryStore(), out)
    doc = Document(str(out))
    text = "\n".join(par.text for par in doc.paragraphs)
    assert "Technická zpráva" in text and "Kontrola stringů" in text and len(doc.tables) >= 6


def test_dc_boxes_along_route():
    spec = {"name": "DC", "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000,
                                         "i_mppt_max": 30, "strings": [20, 20, 18]}],
            "dc": {"route_boxes": 2, "tech_box": True, "fuse_in": 20, "spd": "T1+T2"}}
    p = build_project(spec)
    lib = LibraryStore()
    s = p.sheets[0]
    boxes = [e for e in s.elements if e.symbol_id == "fve.switchboard" and e.ref.startswith("RDC")]
    assert [b.ref for b in boxes] == ["RDC1", "RDC2", "RDC3"]
    assert [pt.name for pt in element_symbol(p, boxes[0], lib).ports] == ["X1", "X2", "X3", "X4", "X5", "X6"]
    # string → RDC1 → RDC2 → RDC3 (u technologie) → střídač, každý string odděleně
    g1 = next(e for e in s.elements if e.symbol_id == "fve.pv_string")
    chain = [w for w in s.wires if w.touches(g1.id)]
    assert len(chain) == 1 and chain[0].b.port == "X1"
    inv = next(e for e in s.elements if e.symbol_id == "fve.inverter")
    assert sum(1 for w in s.wires if w.touches(inv.id) and w.a.element_id == boxes[2].id) == 3
    route, tech = p.switchboard_sheet(boxes[0].id), p.switchboard_sheet(boxes[2].id)
    assert sum(1 for e in route.elements if e.symbol_id == "fve.dc_disconnect") == 3
    assert not [e for e in route.elements if e.symbol_id == "fve.fuse_disconnect"]
    fds = [e for e in tech.elements if e.symbol_id == "fve.fuse_disconnect"]
    assert len(fds) == 3 and fds[0].attrs["in_"] == "20"
    assert sum(1 for e in tech.elements if e.symbol_id == "fve.spd") == 3   # SPD na každý string, stringy se nespojují
    assert sorted(w.b.port for w in s.wires if w.touches(inv.id) and w.a.element_id == boxes[2].id) == ["DC1", "DC2", "DC3"]
    assert all(f.attrs.get("wire_id") for f in tech.elements if f.symbol_id == "sb.feed_in")
    assert s.width > 420   # dva rozvaděče po trase → širší list
    fs = check_project(p, lib)
    assert not [f for f in fs if f.severity in (ERROR, WARNING)], [f.text for f in fs if f.severity != "info"]
