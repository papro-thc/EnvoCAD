"""Generování projektu ze specifikace (bez Qt)."""

import pytest

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
    assert [pt.name for pt in element_symbol(p, blk, lib).ports] == ["X1", "X2", "XOUT", "XPE"]   # XPE = uzemnění na HOP
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
    assert [pt.name for pt in element_symbol(p, boxes[0], lib).ports] == ["X1", "X2", "X3", "X4", "X5", "X6", "XPE"]
    # string → RDC1 → RDC2 → RDC3 (u technologie) → střídač, každý string odděleně
    g1 = next(e for e in s.elements if e.symbol_id == "fve.pv_string")
    chain = [w for w in s.wires if w.touches(g1.id)]
    assert len(chain) == 1 and chain[0].b.port == "X1"
    inv = next(e for e in s.elements if e.symbol_id == "fve.inverter")
    assert sum(1 for w in s.wires if w.touches(inv.id) and w.a.element_id == boxes[2].id) == 3
    route, tech = p.switchboard_sheet(boxes[0].id), p.switchboard_sheet(boxes[2].id)
    # po trase jen SPD (přívod rovně na vývod), odpojovací místo = pojistkové odpínače u střídače
    assert not [e for e in route.elements if e.symbol_id in ("fve.dc_disconnect", "fve.fuse_disconnect")]
    assert sum(1 for e in route.elements if e.symbol_id == "fve.spd") == 3
    x1, x4 = (next(e for e in route.elements if e.ref == r) for r in ("X1", "X4"))
    assert any(w.touches(x1.id) and w.touches(x4.id) for w in route.wires)
    fds = [e for e in tech.elements if e.symbol_id == "fve.fuse_disconnect"]
    assert len(fds) == 3 and fds[0].attrs["in_"] == "20"
    assert sum(1 for e in tech.elements if e.symbol_id == "fve.spd") == 3   # SPD na každý string, stringy se nespojují
    assert sorted(w.b.port for w in s.wires if w.touches(inv.id) and w.a.element_id == boxes[2].id) == ["DC1", "DC2", "DC3"]
    assert all(f.attrs.get("wire_id") for f in tech.elements if f.symbol_id == "sb.feed_in")
    assert s.width > 420   # dva rozvaděče po trase → širší list
    fs = check_project(p, lib)
    assert not [f for f in fs if f.severity in (ERROR, WARNING)], [f.text for f in fs if f.severity != "info"]


def test_string_modules_and_optimizers_in_label_and_bom():
    from envocad.export.reports import bom
    spec = {"name": "Opt", "module": {"type": "JA 450", "p_wp": 450}, "optimizer": {"type": "SE S500", "per_module": 1},
            "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "strings": [20, 18]}]}
    p = build_project(spec)
    lib = LibraryStore()
    g = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.pv_string")
    assert g.attrs["n_optimizers"] == "20" and g.attrs["optimizer"] == "SE S500"
    lines = lib.get_symbol("fve.pv_string").label_lines(g.attrs)
    assert "20× modul" in lines and "20× optimizér" in lines and "SE S500" in lines
    rows = bom(p, lib, p.sheets[0])[1]
    mods = next(r for r in rows if r[1] == "FV modul")
    opts = next(r for r in rows if r[1] == "Optimizér")
    assert mods[5] == 38 and mods[2] == "JA 450" and opts[5] == 38 and opts[2] == "SE S500"


# ---- katalog FV: artikl modulu, návrhové teploty, artikl střídače před dopočtem MPPT ---------------------------
_CATALOG = """id;manufacturer;part_number;name;category;symbol_id;datasheet_url;source;p_wp;voc_v;vmp_v;isc_a;imp_a;beta_voc;u_sys_max_v;mppt;strings_per_mppt;isc_mppt_max_a;u_dc_max_v;u_mppt_min_v;u_mppt_max_v;i_mppt_max_a
test-mod-450;TestSolar;TS-450;FV modul 450 Wp;pv_module;fve.pv_string;https://example.com/m.pdf;web;450;49,5;41,5;13,9;10,85;-0,26;1500;;;;;;;
test-inv-1spm;TestInv;TI-25;Střídač 25 kW;inverter;fve.inverter;https://example.com/i.pdf;web;;;;;;;;;1;40;1100;200;1000;16
"""


def _catalog(tmp_path):
    f = tmp_path / "katalog.csv"
    f.write_text(_CATALOG, encoding="utf-8")
    assert LibraryStore().import_components_csv_v2(f) == 2


def _inv(**kw):
    return {"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30,
            "strings": [20, 20, 18], **kw}


def test_module_component_fills_missing_values(tmp_path):
    _catalog(tmp_path)
    p = build_project({"module": {"component_id": "test-mod-450", "vmp": 41.0}, "inverters": [_inv()],
                       "site": {"t_min": -20, "t_max": 70}})
    gs = [e for e in p.sheets[0].elements if e.symbol_id == "fve.pv_string"]
    g = gs[0]
    assert all(x.component_id == "test-mod-450" for x in gs)
    assert g.attrs["voc"] == "49.5" and g.attrs["vmp"] == "41.0"          # spec vyhrává, čárka → tečka
    assert g.attrs["imp"] == "10.85" and g.attrs["u_sys_max"] == "1500" and g.attrs["beta_voc"] == "-0.26"
    assert g.attrs["type"] == "TS-450" and g.attrs["manufacturer"] == "TestSolar" and g.attrs["p_module"] == "450"
    assert p.meta["pv_t_min"] == "-20" and p.meta["pv_t_max"] == "70"
    from envocad.model import calc
    assert calc.check_strings(p)[0].t_min == -20
    from envocad.export.reports import bom
    _, rows = bom(p, LibraryStore())
    mod = next(r for r in rows if r[1] == "FV modul")
    assert mod[2] == "TS-450" and mod[3] == "TestSolar" and mod[5] == 58
    # neznámý artikl: hodnoty ze specifikace / výchozí, component_id zůstane (kontrola ho nahlásí)
    p = build_project({"module": {"component_id": "neni-v-knihovne"}, "inverters": [_inv()]})
    g = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.pv_string")
    assert g.component_id == "neni-v-knihovne" and g.attrs["voc"] == "49.5" and "imp" not in g.attrs
    assert "pv_t_min" not in p.meta


def test_inverter_component_before_mppt(tmp_path):
    _catalog(tmp_path)
    # artikl: 1 string na MPPT → 3 stringy = 3 MPPT (dřív 2 podle výchozích 2 stringů na MPPT)
    p = build_project({"inverters": [_inv(component_id="test-inv-1spm")]})
    t = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.inverter")
    assert t.attrs["strings_per_mppt"] == "1" and t.attrs["mppt"] == "3" and t.attrs["isc_mppt_max"] == "40"
    assert t.attrs["i_mppt_max"] == "30"                                    # spec vyhrává nad artiklem (16)
    # spec strings_per_mppt vyhrává nad artiklem
    p = build_project({"inverters": [_inv(component_id="test-inv-1spm", strings_per_mppt=2)]})
    t = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.inverter")
    assert t.attrs["strings_per_mppt"] == "2" and t.attrs["mppt"] == "2"
    # isc_mppt_max ze specifikace
    p = build_project({"inverters": [_inv(isc_mppt_max=25)]})
    t = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.inverter")
    assert t.attrs["isc_mppt_max"] == "25" and t.attrs["mppt"] == "2"


def test_tz_uses_design_temperatures(tmp_path):
    from docx import Document

    from envocad.export.tz_export import export_tz_docx
    p = build_project({"inverters": [_inv()], "site": {"t_min": -20, "t_max": 75}})
    out = tmp_path / "tz.docx"
    export_tz_docx(p, LibraryStore(), out)
    heads = [c.text for t in Document(str(out)).tables for c in t.rows[0].cells]
    assert "Uoc při -20 °C [V]" in heads and "Umpp při 75 °C [V]" in heads


_HOUSE_INV = {"p_ac": 10, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


@pytest.mark.parametrize("dc", [{"route_boxes": 0}, {"route_boxes": 1}])
def test_house_combined_switchboard(dc):
    """Rodinný dům: DC i AC v jednom rozvaděči RFVE – pojistkové odpínače a SPD stringů vedle AC části."""
    spec = {"building": "rodinný dům", "inverters": [{"ref": "T1", **_HOUSE_INV, "strings": [12, 12]}], "dc": dc}
    p = build_project(spec)
    lib = LibraryStore()
    assert p.meta["building"] == "rodinný dům"
    boards = [sh for sh in p.sheets if sh.is_switchboard]
    assert [sh.loc for sh in boards] == (["RDC1"] if dc["route_boxes"] else []) + ["RFVE"]
    rf = boards[-1]
    sym = {e.symbol_id for e in rf.elements}
    assert {"fve.fuse_disconnect", "fve.breaker_mcb", "sb.main_switch"} <= sym
    assert sum(1 for e in rf.elements if e.symbol_id == "fve.fuse_disconnect") == 2
    spds = [e.attrs["spd_type"] for e in rf.elements if e.symbol_id == "fve.spd"]
    assert sorted(spds) == ["T1+T2", "T1+T2 DC", "T1+T2 DC"]
    # artikly DC (pojistkový odpojovač, svodič DC) jen na DC přístroje, ne na svodič AC
    assert {e.component_id for e in rf.elements if e.symbol_id == "fve.fuse_disconnect"} == {"eti-efh-10-dc-2p"}
    assert {(e.attrs["spd_type"], e.component_id) for e in rf.elements if e.symbol_id == "fve.spd"} == \
        {("T1+T2", None), ("T1+T2 DC", "weidmuller-vpu-pv-i-ii-3-1000")}
    blk = next(e for e in p.sheets[0].elements if e.ref == "RFVE")
    ports = [pt.name for pt in element_symbol(p, blk, lib).ports]
    assert ports == ["X1", "X2", "X3", "X4", "X5", "XOUT", "XPE"]   # AC od T1, DC přívody, DC vývody, HDS, HOP
    inv = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.inverter")
    assert sorted(w.b.port for w in p.sheets[0].wires if w.a.element_id == blk.id and w.b.element_id == inv.id) == ["DC1", "DC2"]
    # vše na listu bez překryvů a chyb
    fs = check_project(p, lib)
    assert not [f for f in fs if f.severity in (ERROR, WARNING)], [f.text for f in fs if f.severity != "info"]


def test_house_rejects_mv_and_unknown_building():
    base = {"inverters": [{"ref": "T1", **_HOUSE_INV, "strings": [12]}]}
    with pytest.raises(ValueError, match="Rodinný dům"):
        build_project({**base, "building": "house", "connection": {"level": "vn"}})
    with pytest.raises(ValueError, match="druh objektu"):
        build_project({**base, "building": "garáž"})
    p = build_project({**base, "building": "apartment"})
    assert p.meta["building"] == "bytový dům"
    assert [sh.loc for sh in p.sheets if sh.is_switchboard] == ["RDC1", "RDC2", "RH"]
