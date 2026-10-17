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


# ---- optimizéry: artikl optimizéru, režim stringů a nejpřísnější pravidla (docs/design/optimizery.md) -----------
_OPT_CATALOG = """id;manufacturer;part_number;name;category;symbol_id;datasheet_url;source;p_max_w;u_in_max_v;isc_in_max_a;u_out_max_v;modules_per_optimizer;string_mode;partial_ok;compat;n_min_1ph;n_max_1ph;p_string_max_1ph_w;n_min_3ph;n_max_3ph;p_string_max_3ph_w;mppt;strings_per_mppt;u_dc_max_v;u_string_v;n_opt_min;n_opt_max;p_string_max_w
test-opt-2;TestEdge;TP850;Optimizér 2:1;optimizer;;https://example.com/o.pdf;web;850;125;14,5;85;2;fixed_voltage;0;TestEdge;8;40;6800;14;50;11250;;;;;;;
test-opt-1;TestWay;TW450;Optimizér 1:1;optimizer;;https://example.com/o1.pdf;web;450;80;14,5;80;1;optimizer;0;TestWay;;;;;;;;;;;;;
test-inv-se;TestEdge;TE5K;Střídač 5 kW;inverter;fve.inverter;https://example.com/i.pdf;web;;;;;;;;;;;;;;;1;2;480;380;6;30;8000
"""


def _opt_catalog(tmp_path):
    f = tmp_path / "opt.csv"
    f.write_text(_OPT_CATALOG, encoding="utf-8")
    assert LibraryStore().import_components_csv_v2(f) == 3


def _opt_spec(strings, opt_id="test-opt-2", **inv):
    return {"module": {"p_wp": 400, "voc": 49.5, "vmp": 41.5, "isc": 13.9, "type": "M400"},
            "optimizer": {"type": "", "per_module": 1, "component_id": opt_id},
            "inverters": [{"ref": "T1", "p_ac": 5, "phases": 1, "strings": strings, "component_id": "test-inv-se",
                           **inv}]}


def test_optimizer_component_to_strings_and_inverter(tmp_path):
    _opt_catalog(tmp_path)
    p = build_project(_opt_spec([18, 15]))
    s = p.sheets[0]
    g1, g2 = (e for e in s.elements if e.symbol_id == "fve.pv_string")
    t = next(e for e in s.elements if e.symbol_id == "fve.inverter")
    # artikl optimizéru: typ, ⌈n / 2⌉ optimizérů, parametry pro kontrolu (pravidla 1f), výrobce optimizéru
    assert g1.attrs["optimizer"] == "TP850" and g1.attrs["n_optimizers"] == "9" and g2.attrs["n_optimizers"] == "8"
    assert g1.attrs["opt_manufacturer"] == "TestEdge" and g1.attrs["optimizer_id"] == "test-opt-2"
    assert (g1.attrs["opt_modules"], g1.attrs["opt_p_max"], g1.attrs["opt_n_min"], g1.attrs["opt_p_string_max"]) == \
        ("2", "850", "8", "6800")
    assert "manufacturer" not in g1.attrs and g1.attrs["type"] == "M400"     # modul beze změny
    # střídač: režim z artiklu střídače, pravidla nejpřísnější pro 1f: min max(6, 8), max min(30, 40), P min(8000, 6800)
    assert (t.attrs["string_mode"], t.attrs["u_string"]) == ("fixed_voltage", "380")
    assert (t.attrs["n_opt_min"], t.attrs["n_opt_max"], t.attrs["p_string_max"]) == ("8", "30", "6800")
    from envocad.model import calc
    st = {sc.ref: sc for sc in calc.check_strings(p)}
    assert st["G1"].mode == "fixed_voltage" and st["G1"].issues == ["P stringu 7200 W > max 6800 W"]
    assert "15 modulů, 8 optimizérů × 2 – optimizér musí být na každém modulu" in st["G2"].issues
    # 3f: pravidla optimizéru pro 3 fáze (min 14 > 6, P 8000 < 11250)
    t3 = next(e for e in build_project(_opt_spec([16], phases=3)).sheets[0].elements if e.symbol_id == "fve.inverter")
    assert (t3.attrs["n_opt_min"], t3.attrs["n_opt_max"], t3.attrs["p_string_max"]) == ("14", "30", "8000")
    # specifikace vyhrává: režim i pravidla
    p = build_project(_opt_spec([16], string_mode="classic", n_opt_max=12, p_string_max=9000))
    t = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.inverter")
    assert (t.attrs["string_mode"], t.attrs["n_opt_max"], t.attrs["p_string_max"], t.attrs["n_opt_min"]) == \
        ("classic", "12", "9000", "8")
    # BOM: optimizér s výrobcem z artiklu
    from envocad.export.reports import bom
    rows = bom(p, LibraryStore(), p.sheets[0])[1]
    opt = next(r for r in rows if r[1] == "Optimizér")
    assert opt[2] == "TP850" and opt[3] == "TestEdge" and opt[5] == 8


def test_optimizer_mode_from_optimizer_component(tmp_path):
    _opt_catalog(tmp_path)
    # střídač bez režimu (bez artiklu): režim z artiklu optimizéru, 1:1 → n_optimizers = n
    spec = _opt_spec([20, 20], opt_id="test-opt-1", component_id=None, u_dc_max=1100, u_mppt_min=160,
                     u_mppt_max=1000, i_mppt_max=26, phases=3)
    spec["optimizer"]["type"] = "Vlastní typ"
    p = build_project(spec)
    g = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.pv_string")
    t = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.inverter")
    assert t.attrs["string_mode"] == "optimizer" and "n_opt_min" not in t.attrs
    assert g.attrs["optimizer"] == "Vlastní typ" and g.attrs["n_optimizers"] == "20"   # zadaný typ vyhrává
    from envocad.model import calc
    assert all(sc.ok and sc.mode == "optimizer" for sc in calc.check_strings(p))
    # neznámý artikl optimizéru: jako dřív (typ ze specifikace, round, bez atributů opt_*)
    spec = _opt_spec([20], opt_id="neni", component_id=None)
    spec["optimizer"]["type"] = "X"
    g = next(e for e in build_project(spec).sheets[0].elements if e.symbol_id == "fve.pv_string")
    assert g.attrs["n_optimizers"] == "20" and "optimizer_id" not in g.attrs


def test_fixed_voltage_in_reports_and_tz(tmp_path):
    from docx import Document

    from envocad.export.reports import calculations
    from envocad.export.tz_export import export_tz_docx
    _opt_catalog(tmp_path)
    p = build_project(_opt_spec([16]))
    _, rows = calculations(p, LibraryStore())
    assert rows[0][2] == "16 modulů, 8 optimizérů, pevné U 380 V, P stringu 6400 / 6800 W" and rows[0][4] == "OK"
    assert rows[0][3] == "T1: optimizérů 8–30, P stringu ≤ 6800 W"
    out = tmp_path / "tz.docx"
    export_tz_docx(p, LibraryStore(), out)
    text = "\n".join(c.text for t in Document(out).tables for r in t.rows for c in r.cells)
    assert "pevné U 380 V" in text and "P stringu 6400 / 6800 W" in text
