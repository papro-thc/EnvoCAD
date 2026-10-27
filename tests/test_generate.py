"""Generování projektu ze specifikace (bez Qt)."""

import pytest
from chain_data import build_project  # F2: In stávajících článků (RD/HR, RE, HDS) zadané – F7 bez chyb

from envocad.generate import DEFAULT_SPEC
from envocad.library.store import LibraryStore
from envocad.model.checks import ERROR, WARNING, check_project
from envocad.model.feed import is_feed_in
from envocad.model.project import element_symbol

pytestmark = pytest.mark.usefixtures("ac_builtin")   # AC listy vestavěným kódem (standard `ac_builtin`)


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
    # 2 střídače × po trase + společný u technologie (F2) + AC; za nimi stávající články řetězce
    assert all(sh.is_switchboard for sh in p.sheets[1:])
    assert [sh.loc for sh in p.sheets[1:5]] == ["RDC1", "RDC2", "RFVE.DC", "RFVE.AC"]
    assert len([e for e in s.elements if e.symbol_id == "fve.pv_string"]) == 5
    assert p.meta["p_installed_kwp"] == "44.1"
    lib = LibraryStore()
    blk = next(e for e in s.elements if e.symbol_id == "fve.switchboard")
    assert [pt.name for pt in element_symbol(p, blk, lib).ports] == ["X1", "X2", "XOUT", "XPE"]   # XPE = uzemnění na HOP
    # přívody rozvaděče jsou navázané na AC vodiče střídačů, kabely jako objekty
    sb = p.sheets[1]
    feeds = [e for e in sb.elements if is_feed_in(e)]
    assert all(f.attrs.get("wire_id") for f in feeds) and len(p.cables) >= 8
    fs = check_project(p, lib, standard_paper="A4")
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
    boxes = [e for e in s.elements if e.symbol_id == "fve.switchboard" and e.ref.startswith(("RDC", "RFVE.DC"))]
    assert [b.ref for b in boxes] == ["RDC1", "RDC2", "RFVE.DC"]   # po trase RDCn, u technologie RFVE.DC
    assert [pt.name for pt in element_symbol(p, boxes[0], lib).ports] == ["X1", "X2", "X3", "X4", "X5", "X6", "XPE"]
    # string → RDC1 → RDC2 → RFVE.DC (u technologie) → střídač, každý string odděleně
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
    assert all(f.attrs.get("wire_id") for f in tech.elements if is_feed_in(f))
    assert s.width > 420   # dva rozvaděče po trase → širší list
    fs = check_project(p, lib, standard_paper="A4")
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
_HOUSE_INV = {"p_ac": 10, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


@pytest.mark.parametrize("dc", [{"route_boxes": 0}, {"route_boxes": 1}])
def test_house_combined_switchboard(dc):
    """Rodinný dům: DC i AC v jednom rozvaděči RFVE – pojistkové odpínače a SPD stringů vedle AC části."""
    spec = {"building": "rodinný dům", "inverters": [{"ref": "T1", **_HOUSE_INV, "strings": [12, 12]}], "dc": dc}
    p = build_project(spec)
    lib = LibraryStore()
    assert p.meta["building"] == "rodinný dům"
    boards = [sh for sh in p.sheets if sh.is_switchboard]
    # za RFVE stávající RD a RE (F2)
    assert [sh.loc for sh in boards] == (["RDC1"] if dc["route_boxes"] else []) + ["RFVE", "RD", "RE"]
    rf = next(sh for sh in boards if sh.loc == "RFVE")
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
    fs = check_project(p, lib, standard_paper="A4")
    assert not [f for f in fs if f.severity in (ERROR, WARNING)], [f.text for f in fs if f.severity != "info"]


def test_house_rejects_mv_and_unknown_building():
    base = {"inverters": [{"ref": "T1", **_HOUSE_INV, "strings": [12]}]}
    with pytest.raises(ValueError, match="Rodinný dům"):
        build_project({**base, "building": "house", "connection": {"level": "vn"}})
    with pytest.raises(ValueError, match="druh objektu"):
        build_project({**base, "building": "garáž"})
    p = build_project({**base, "building": "apartment"})
    assert p.meta["building"] == "bytový dům"
    assert [sh.loc for sh in p.sheets if sh.is_switchboard] == ["RDC1", "RFVE.DC", "RFVE.AC", "HR", "RE"]


def test_datasheet_solaredge_se25k_p1100_runergy():
    """Artikly z datasheetů (katalogy/datasheet): SE25K + P1100 + modul 420 Wp bez chyb; Runergy 450 Wp má Isc 16,07 A
    nad vstupem P1100 (14,1 A) → chyba stringu."""
    lib = LibraryStore()
    spec = {"name": "SE", "module": {"component_id": "longi-lr5-54hth-420m"},
            "optimizer": {"component_id": "solaredge-p1100-4rm4mbt"},
            "inverters": [{"ref": "T1", "component_id": "solaredge-se25k", "strings": [30, 32]}]}
    p = build_project(spec)
    assert not [f for f in check_project(p, lib, standard_paper="A4") if f.severity in (ERROR, WARNING)]
    spec["module"] = {"component_id": "runergy-hy-dh96n11b-450"}
    p = build_project(spec)
    assert any("Isc max vstupu optimizéru" in f.text for f in check_project(p, lib, standard_paper="A4") if f.severity == ERROR)


# ---- F0: opravy z review generátoru (docs/NAVRH_TOPOLOGIE.md, kap. 6) ------------------------------------------
_INV25 = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
_NO_MACROS = {"dc_tech": "", "dc_route": "", "ac_feed": "", "ac_core": ""}


def _fuses(p, loc=None):
    return [e for sh in p.sheets if sh.is_switchboard and (loc is None or sh.loc == loc)
            for e in sh.elements if e.symbol_id == "fve.fuse_disconnect"]


def _codes(p, lib, *codes):
    return [f for f in check_project(p, lib, standard_paper="A4") if f.code in codes]


def test_string_fuse_series_and_holder_limit():
    """Bod 1: řada gPV doplněná o 30/32 A, mez držáku (EFH 10 DC max 25 A)."""
    from envocad.model.calc import GPV_FUSE_SIZES, string_fuse_in
    assert {30.0, 32.0} <= set(GPV_FUSE_SIZES)
    assert string_fuse_in(18.5) == 30.0                       # 1,5 × 18,5 = 27,75 → 30 A
    assert string_fuse_in(18.5, max_in=25) is None            # EFH 10 DC: max 25 A → nevyhoví
    assert string_fuse_in(13.9, max_in=25) == 25.0
    assert string_fuse_in(13.9, i_fuse_max=10) is None        # max. jištění modulu 10 A
    lib = LibraryStore()
    assert lib.component("eti-efh-10-dc-2p").num("in_max_a") == 25


@pytest.mark.parametrize("macros", [None, _NO_MACROS])
@pytest.mark.parametrize("module", [{"isc": 18.5}, {"isc": 13.9, "i_fuse_max": 10}])
def test_no_fitting_string_fuse_leaves_in_empty_with_f7_error(macros, module):
    """Bod 1: žádná pojistka gPV nevyhoví → prázdné In (makro i kód) a chyba F7, žádné tiché 15 A."""
    spec = {"module": module, "inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}]}
    if macros is not None:
        spec["macros"] = macros
    p = build_project(spec)
    fuses = _fuses(p)
    assert fuses and all(f.attrs["in_"] == "" for f in fuses)
    assert not any("987654321" in v for sh in p.sheets for e in sh.elements for v in e.attrs.values())
    errs = _codes(p, LibraryStore(), "fuse_no_in")
    assert len(errs) == len(fuses) and all(f.severity == ERROR for f in errs)


def test_string_fuse_30a_without_holder_limit():
    spec = {"module": {"isc": 18.5}, "dc": {"fuse_component": ""},
            "inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}]}
    assert {f.attrs["in_"] for f in _fuses(build_project(spec))} == {"30"}


@pytest.mark.parametrize("mppt", ["2.0", "2,0", 2.0, "2"])
def test_mppt_decimal_text(mppt):
    """Bod 2: „2.0“ / „2,0“ v mppt nespadne a zapíše se jako celé číslo."""
    p = build_project({"inverters": [{"ref": "T1", **_INV25, "mppt": mppt, "strings_per_mppt": "2,0",
                                      "strings": [20, 20, 18]}]})
    t = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.inverter")
    assert t.attrs["mppt"] == "2" and t.attrs["strings_per_mppt"] == "2"


@pytest.mark.parametrize("macros", [None, _NO_MACROS])
def test_house_fuse_in_per_inverter_group(macros):
    """Bod 3 (+7): RFVE s více střídači – In pojistek po skupinách (SolarEdge 25 A, klasický string podle Isc)."""
    spec = {"building": "house", "module": {"isc": 9.0},
            "inverters": [{"ref": "T1", **_HOUSE_INV, "type": "SolarEdge SE10K", "strings": [12]},
                          {"ref": "T2", **_HOUSE_INV, "type": "Fronius Symo 10", "strings": [12, 12]}]}
    if macros is not None:
        spec["macros"] = macros
    p = build_project(spec)
    assert sorted(f.attrs["in_"] for f in _fuses(p, "RFVE")) == ["15", "15", "25"]
    fs = check_project(p, LibraryStore(), standard_paper="A4")
    assert not [f for f in fs if f.severity in (ERROR, WARNING)], [f.text for f in fs if f.severity != "info"]


def test_vn_fve_feeder_limited_by_main_breaker():
    """Bod 4: vývod FVE v hlavním rozvaděči nn omezený selektivitou s hlavním jističem ze Sn (50 kVA → HJ 100 A)."""
    from envocad.generate import fve_feeder_in
    lib = LibraryStore()
    spec = {"inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}],
            "connection": {"level": "vn", "transformer": {"sn": 50}}}
    p = build_project(spec)
    rhn = next(sh for sh in p.sheets if sh.loc == "HR")
    x1 = next(e for e in rhn.elements if e.ref == "X1")
    w = next(w for w in rhn.wires if w.touches(x1.id))
    feeder = rhn.element(w.a.element_id if w.b.element_id == x1.id else w.b.element_id)
    ins = sorted((e.attrs["in_"] for e in rhn.elements if e.symbol_id == "fve.breaker_mccb"), key=float)
    assert feeder.attrs["in_"] == "50" and ins == ["50", "50", "100"]   # vývod FVE, spotřeba, hlavní jistič
    assert not [f for f in check_project(p, lib, standard_paper="A4") if f.code in ("calc_selectivity", "breaker_no_in")]
    # 630 kVA (HJ 1000 A): beze změny – In hlavního vypínače RFVE.AC
    assert fve_feeder_in({"transformer": {"sn": 630}}, {"main_in": 125}, [])[0] == "125"
    # FVE 60 kW na 50 kVA: žádný selektivní vývod neunese proud → prázdné In + chyba F7, nic se nedosazuje
    big = {**spec, "inverters": [{"ref": "T1", **_INV25, "p_ac": 60, "strings": [20, 20]}]}
    p = build_project(big)
    rhn = next(sh for sh in p.sheets if sh.loc == "HR")
    assert [e.attrs["in_"] for e in rhn.elements if e.symbol_id == "fve.breaker_mccb"].count("") == 1
    assert [f.severity for f in _codes(p, lib, "breaker_no_in")] == [ERROR]
    assert fve_feeder_in({"transformer": {"sn": 50}}, {"main_in": 125, "breaker_in": 40},
                         [{"p_ac": 60}])[1].startswith("vývod FVE")
    # zadané main_board.fve_in platí beze změny (selektivitu hlásí F7)
    over = {**spec, "connection": {**spec["connection"], "main_board": {"fve_in": 125}}}
    p = build_project(over)
    assert any(f.code == "calc_selectivity" and f.severity == WARNING for f in check_project(p, lib, standard_paper="A4"))


@pytest.mark.parametrize("text, volts", [("22 kV", 22000), ("22kV", 22000), ("22000 V", 22000), ("22 000 V", 22000),
                                         ("22000", 22000), ("22", 22000), ("35 kV", 35000), ("22,5 kV", 22500),
                                         ("22.5 kV", 22500), ("35 kV, 50 Hz", 35000), ("22.000 V", 22000),
                                         ("22\u00a0000 V", 22000), ("10 kV", 10000), ("", 22000)])
def test_parse_voltage(text, volts):
    """Bod 5 (+ review F0 bod 2): u_vn s jednotkou, číslo na začátku textu, tečka jako oddělovač tisíců."""
    from envocad.generate import parse_voltage
    assert parse_voltage(text) == volts


@pytest.mark.parametrize("text", ["nesmysl", "kV 22", "400 V", "0", "110 kV", "60000 V"])
def test_parse_voltage_invalid_raises_czech(text):
    """Review F0 bod 2: nečitelné / mimo rozsah vn (1–52 kV) → ValueError s českou hláškou, žádné tiché 22 kV."""
    from envocad.generate import parse_voltage
    with pytest.raises(ValueError, match="Napětí vn"):
        parse_voltage(text)
    spec = {"inverters": [{"ref": "T1", **_INV25, "strings": [20]}], "connection": {"level": "vn", "u_vn": text}}
    with pytest.raises(ValueError, match="Napětí vn"):
        build_project(spec)


def test_voltage_label_not_written_when_u_vn_missing():
    """Review F0 bod 2: nezadané u_vn – výpočet z 22 kV, ale do výkresu se dosazená hodnota nepíše."""
    from envocad.generate import connection_currents, voltage_label
    c = connection_currents({"u_vn": ""})
    assert c["u_mv"] == 22000 and c["u_label"] == "" and voltage_label(None) == ""
    assert connection_currents({"u_vn": "35 kV, 50 Hz"})["u_label"] == "35 kV"
    p = build_project({"inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}],
                       "connection": {"level": "vn", "metering": "vn", "u_vn": ""}})
    assert {e.attrs["voltage"] for e in p.sheets[0].elements if e.symbol_id == "fve.grid"} == {"3~ 50 Hz"}
    assert not any("22" in e.attrs.get("ratio", "") for sh in p.sheets for e in sh.elements if e.symbol_id == "fve.vt")


def test_u_vn_in_volts_gives_same_project_values():
    from envocad.generate import connection_currents
    a, b = connection_currents({"u_vn": "22 kV"}), connection_currents({"u_vn": "22000 V"})
    assert a["i_mv"] == pytest.approx(b["i_mv"]) and a["fuse_vn"] == b["fuse_vn"] and b["u_label"] == "22 kV"
    p = build_project({"inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}],
                       "connection": {"level": "vn", "metering": "vn", "u_vn": "22000 V"}})
    tv = next(e for sh in p.sheets for e in sh.elements if e.symbol_id == "fve.vt")
    assert tv.attrs["ratio"].startswith("22/√3")
    assert {e.attrs["voltage"] for e in p.sheets[0].elements if e.symbol_id == "fve.grid"} == {"3~ 22 kV, 50 Hz"}


def test_house_without_tech_box():
    """Bod 6: RD bez DC části v RFVE – název „rozvaděč FVE (AC)“, přípojka VN odmítnutá česky."""
    base = {"building": "house", "dc": {"tech_box": False}, "inverters": [{"ref": "T1", **_HOUSE_INV, "strings": [12]}]}
    p = build_project(base)
    blk = next(e for e in p.sheets[0].elements if e.ref == "RFVE")
    assert blk.attrs["desc"] == "rozvaděč FVE (AC)"
    assert not _fuses(p, "RFVE")
    with pytest.raises(ValueError, match="Rodinný dům.*přípojka VN"):
        build_project({**base, "connection": {"level": "vn"}})


@pytest.mark.parametrize("inv, opt", [
    ({"type": "SolarEdge SE10K"}, {}),
    ({"manufacturer": "SolarEdge"}, {}),
    ({"type": "SE17K", "string_mode": "fixed_voltage"}, {}),
    ({"component_id": "solaredge-se17k"}, {}),
    ({"type": "X"}, {"type": "Solar-Edge S440"}),
])
def test_solaredge_string_fuse_25a(inv, opt):
    """Bod 7: SolarEdge podle typu / výrobce / artiklu střídače, režimu fixed_voltage nebo optimizéru → 25 A."""
    from envocad.generate import _fuse_in, is_solaredge
    from envocad.model.project import Element
    t = Element("fve.inverter", 0, 0, attrs={k: v for k, v in inv.items() if k != "component_id"},
                component_id=inv.get("component_id"))
    assert is_solaredge(t, opt)
    assert _fuse_in({"fuse_in": "", "fuse_component": "eti-efh-10-dc-2p"}, {"isc": 9.0}, opt, t) == "25"
    assert not is_solaredge(Element("fve.inverter", 0, 0, attrs={"type": "Fronius Symo"}), {})
    assert _fuse_in({"fuse_in": ""}, {"isc": 9.0}, {}, Element("fve.inverter", 0, 0, attrs={"type": "Fronius"})) == "15"


def test_battery_cable_from_battery_spec():
    """Bod 8: kabel baterie z `battery.cable/cross/length` (výchozí H1Z2Z2-K 1x25, 25 mm², 5 m), ne z `dc.cable`."""
    def bat_wire(battery):
        p = build_project({"inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}], "battery": battery})
        bat = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.battery")
        return next(w for sh in p.sheets for w in sh.wires if w.touches(bat.id)).attrs
    w = bat_wire({"e_kwh": 10, "p_kw": 5})
    assert (w["cable"], w["cross"], w["length"]) == ("H1Z2Z2-K 1x25", "25", "5")
    w = bat_wire({"e_kwh": 10, "cable": "H1Z2Z2-K 1x35", "cross": 35, "length": 8})
    assert (w["cable"], w["cross"], w["length"]) == ("H1Z2Z2-K 1x35", "35", "8")


def test_build_dc_strings_fuse_list_and_pitch():
    """Bod 9 / 3: DC rozvaděč bez makra – rozteč stringů jako makra (texty SPD se nepřekrývají), In po stringech."""
    from envocad.library.templates import DC_STRING_PITCH, build_dc_strings
    from envocad.model.project import Project
    p = Project()
    sh = p.sheets[0]
    build_dc_strings(p, sh, ["G1", "G2"], "tech", ["25", "15"])
    fuses = sorted((e for e in sh.elements if e.symbol_id == "fve.fuse_disconnect"), key=lambda e: e.x)
    assert [f.attrs["in_"] for f in fuses] == ["25", "15"] and fuses[1].x - fuses[0].x == DC_STRING_PITCH
    with pytest.raises(ValueError):
        build_dc_strings(p, sh, ["G1", "G2"], "tech", ["25"])


def test_protection_without_in_is_f7_error():
    from envocad.model.checks import protection_findings
    from envocad.model.project import Element
    p = build_project({"inverters": [{"ref": "T1", **_INV25, "strings": [20]}]})
    rh = next(sh for sh in p.sheets if sh.loc == "RFVE.AC")
    br = next(e for e in rh.elements if e.symbol_id == "fve.breaker_mcb")
    assert not protection_findings(p)
    br.attrs["in_"] = " "      # ruční list bez In: neutrální varování
    fs = protection_findings(p)
    assert [(f.code, f.severity, f.target_id) for f in fs] == [("breaker_no_in", WARNING, br.id)]
    assert fs[0].text == "Jistič bez In – doplňte"
    br.attrs["in_unresolved"] = "nic nevyhovělo (test)"    # generátor In nedosadil → chyba s důvodem
    fs = protection_findings(p)
    assert [(f.code, f.severity) for f in fs] == [("breaker_no_in", ERROR)] and "nic nevyhovělo (test)" in fs[0].text
    fu = Element("fve.fuse", attrs={"ref": "F9", "in_": ""})
    rh.elements.append(fu)
    assert ("fuse_no_in", WARNING, "Pojistka bez In – doplňte") in [(f.code, f.severity, f.text)
                                                                   for f in protection_findings(p)]


# výstup generátoru bez chyb a varování F7 – topologie z docs/NAVRH_TOPOLOGIE.md (kap. 5) a cesta bez maker
# stávající články řetězce (F2): In stávajících přístrojů projektant zadá (průvodce je vyžaduje) – neznámé = chyba F7
_EXIST_NN = {"hr": {"main_in": 250}, "re": {"main_in": 250}, "hds": {"in_": 315}}
# RD: HJ před elektroměrem ≥ 1,6 × vývod FVE (2 střídače 10 kW → 32 A) – selektivita v řetězci (F7 `chain_selectivity`)
_EXIST_RD = {"rd": {"main_in": 63}, "re": {"main_in": 63}, "hds": {"in_": 80}}
F7_CASES = {
    "firma": {"inverters": [{"ref": "T1", **_INV25, "strings": [20, 20, 18]}, {"ref": "T2", **_INV25, "strings": [20, 20]}],
              "chain": _EXIST_NN},
    "rd": {"building": "house", "inverters": [{"ref": "T1", **_HOUSE_INV, "strings": [12, 12]}],
           "battery": {"e_kwh": 10, "p_kw": 5}, "chain": _EXIST_RD},
    "rd_2inv": {"building": "house", "inverters": [{"ref": "T1", **_HOUSE_INV, "strings": [12, 12]},
                                                   {"ref": "T2", **_HOUSE_INV, "strings": [12]}], "chain": _EXIST_RD},
    "nn_hr_meter": {"topology": "nn_hr_meter", "chain": _EXIST_NN,
                    "inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}, {"ref": "T2", **_INV25, "strings": [20]}]},
    "bytovy_dum": {"building": "apartment", "inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}],
                   "chain": _EXIST_NN},
    "vn_kiosk": {"inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}], "connection": {"level": "vn"}},
    "vn_kobky_mereni_vn": {"inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}],
                           "connection": {"level": "vn", "station": "kobky", "metering": "vn"}},
    "vn_sloup_50kva": {"inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}],
                       "connection": {"level": "vn", "station": "sloup", "transformer": {"sn": 50}}},
    "bez_maker": {"inverters": [{"ref": "T1", **_INV25, "strings": [20, 20, 18]}, {"ref": "T2", **_INV25, "strings": [20, 20]}],
                  "macros": _NO_MACROS, "chain": _EXIST_NN},
    "bez_maker_svorky": {"inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}], "macros": _NO_MACROS,
                         "ac": {"distribution": "terminals"}, "chain": _EXIST_NN},
    "rd_bez_maker": {"building": "house", "inverters": [{"ref": "T1", **_HOUSE_INV, "strings": [12, 12]}],
                     "macros": _NO_MACROS, "chain": _EXIST_RD},
    "nn_hranice_re_main": {"inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}],
                           "chain": {**_EXIST_NN, "re": {"main_in": 250, "boundary": "re_main"}}},
    "rd_2inv_bez_maker_svorky": {"building": "house", "macros": _NO_MACROS, "ac": {"distribution": "terminals"},
                                 "dc": {"route_boxes": 2}, "chain": _EXIST_RD,
                                 "inverters": [{"ref": "T1", **_HOUSE_INV, "strings": [12, 12, 12]},
                                               {"ref": "T2", **_HOUSE_INV, "strings": [12]}]},
}
@pytest.mark.parametrize("name", list(F7_CASES))
def test_generated_project_f7_clean(name):
    p = build_project(F7_CASES[name])
    fs = [f for f in check_project(p, LibraryStore(), standard_paper="A4") if f.severity in (ERROR, WARNING)]
    assert not fs, [(f.sheet_name, f.ref, f.text) for f in fs]


_F7_RE_INDIRECT = {"inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}],
                   "chain": {**_EXIST_NN, "re": {"main_in": 250, "metering": "indirect"}}}


def test_generated_indirect_metering_re_f7_clean():
    """Nepřímé měření v RE na nn (MTP v RE, elektroměr na sekundáru): ve vícepólu elektroměr se svorkami (DIN 43856)
    a MTP po fázích pod sebou – bez chyb a varování F7 (dřív text elektroměru přes žílu napěťových obvodů)."""
    p = build_project(_F7_RE_INDIRECT)
    fs = [f for f in check_project(p, LibraryStore(), standard_paper="A4") if f.severity in (ERROR, WARNING)]
    assert not fs, [(f.sheet_name, f.ref, f.text) for f in fs]


# ---- označení rozvaděčů (docs/NAVRH_TOPOLOGIE.md, kap. 8 bod 9) -------------------------------------------------
def test_switchboard_designations_company_two_inverters():
    """Firma, 2 střídače s `chain.rfve_dc.per_inverter`: rozvaděč u technologie na střídač RFVE.DC1/RFVE.DC2 (pořadí
    střídačů), po trase RDC1, RDC2 souvisle, AC rozvaděč RFVE.AC; kódy jsou platné umístění (tečka uvnitř) a listy
    dědí +RFVE.DCn. Bez volby (výchozí od F2) jeden společný RFVE.DC za rozvaděči po trase."""
    from envocad.model.designation import LOC, validate_code
    spec = {"inverters": [{"ref": "T1", **_INV25, "strings": [20]}, {"ref": "T2", **_INV25, "strings": [20]}],
            "dc": {"route_boxes": 1}}
    common = build_project(spec)
    assert [sh.loc for sh in common.sheets if sh.is_switchboard][:4] == ["RDC1", "RDC2", "RFVE.DC", "RFVE.AC"]
    p = build_project({**spec, "chain": {"rfve_dc": {"per_inverter": True}}})
    assert [sh.loc for sh in p.sheets if sh.is_switchboard][:5] == ["RDC1", "RFVE.DC1", "RDC2", "RFVE.DC2",
                                                                     "RFVE.AC"]
    assert all(not validate_code(sh.loc, LOC) for sh in p.switchboards())
    tech = {b.attrs["desc"]: b.ref for b in p.sheets[0].elements if b.ref.startswith("RFVE.DC")}
    assert tech == {"DC rozvaděč u T1": "RFVE.DC1", "DC rozvaděč u T2": "RFVE.DC2"}
    assert {s.code for s in p.structures} >= {"RFVE.DC1", "RFVE.DC2", "RFVE.AC", "RDC1", "RDC2"}
    assert not [f for f in check_project(p, LibraryStore(), standard_paper="A4") if f.code in ("struct_syntax", "dup_ref")]


def test_dc_box_ref_helper():
    from envocad.generate import dc_box_ref
    from envocad.model.project import Project
    p = Project()
    assert dc_box_ref("tech", 0, 1, p) == "RFVE.DC"
    assert dc_box_ref("tech", 2, 3, p) == "RFVE.DC3"
    assert dc_box_ref("route", 0, 1, p) == "RDC1"


def test_switchboard_designations_vn_house_and_override():
    """Přípojka VN: hlavní rozvaděč nn HR, vývod FVE „k RFVE.AC (FVE)“; rodinný dům jeden RFVE; zadané ref platí."""
    p = build_project({"inverters": [{"ref": "T1", **_INV25, "strings": [20]}], "connection": {"level": "vn"}})
    locs = [sh.loc for sh in p.switchboards()]
    assert "HR" in locs and "RFVE.AC" in locs and "RHN" not in locs and "RH" not in locs
    hr = next(sh for sh in p.switchboards() if sh.loc == "HR")
    assert next(e for e in hr.elements if e.ref == "X1").attrs["desc"] == "k RFVE.AC (FVE)"
    house = build_project({"building": "house", "inverters": [{"ref": "T1", **_HOUSE_INV, "strings": [12]}],
                           "dc": {"route_boxes": 0}})
    assert [sh.loc for sh in house.switchboards()] == ["RFVE", "RD", "RE"]
    own = build_project({"inverters": [{"ref": "T1", **_INV25, "strings": [20]}], "switchboard": {"ref": "RH1"},
                         "connection": {"level": "vn", "main_board": {"ref": "RHN"}}})
    assert {"RH1", "RHN"} <= {sh.loc for sh in own.switchboards()}
    hr = next(sh for sh in own.switchboards() if sh.loc == "RHN")
    assert next(e for e in hr.elements if e.ref == "X1").attrs["desc"] == "k RH1 (FVE)"


# ---- review F0 (2. kolo): vývod FVE z prvků střídačů, držáky pojistek, In bez řešení ---------------------------
def _hr_feeder(p):
    hr = next(sh for sh in p.sheets if sh.loc == "HR")
    x1 = next(e for e in hr.elements if e.ref == "X1")
    w = next(w for w in hr.wires if w.touches(x1.id))
    return hr.element(w.a.element_id if w.b.element_id == x1.id else w.b.element_id)


def test_vn_fve_feeder_current_from_inverter_components():
    """Bod 1: 3× SolarEdge SE27.6K jen s component_id (bez p_ac ve spec) na trafu 50 kVA – proud FVE z p_ac
    artiklu (≈ 120 A) → žádný selektivní vývod: prázdné In + chyba F7 s důvodem (dřív 50 A z jističe střídače)."""
    from envocad.generate import inverters_ac_current
    from envocad.model.project import Element
    invs = [{"ref": f"T{i}", "component_id": "solaredge-se27.6k", "strings": [20]} for i in (1, 2, 3)]
    p = build_project({"inverters": invs, "connection": {"level": "vn", "transformer": {"sn": 50}}})
    ts = [e for sh in p.sheets for e in sh.elements if e.symbol_id == "fve.inverter"]
    assert len(ts) == 3
    assert inverters_ac_current(ts) == pytest.approx(3 * 27600 / (3 ** 0.5 * 400))
    qf = _hr_feeder(p)
    assert qf.attrs["in_"] == "" and "proud FVE" in qf.attrs["in_unresolved"]
    errs = _codes(p, LibraryStore(), "breaker_no_in")
    assert [(f.severity, f.target_id) for f in errs] == [(ERROR, qf.id)] and "proud FVE" in errs[0].text
    # i 1f střídač z prvku (230 V)
    assert inverters_ac_current([Element("fve.inverter", attrs={"p_ac": "4,6", "phases": "1"})]) == pytest.approx(20)


def test_vn_fve_feeder_given_main_in_checked_against_fve_current():
    """Bod 1: zadané ac.main_in (selektivní s HJ) menší než proud FVE → prázdné In + chyba F7, ne tiché 40 A."""
    from envocad.generate import fve_feeder_in
    conn = {"transformer": {"sn": 50}}
    assert fve_feeder_in(conn, {"main_in": 40, "breaker_in": 40}, [{"p_ac": 25}]) == ("40", "")
    fin, why = fve_feeder_in(conn, {"main_in": 40, "breaker_in": 32}, [{"p_ac": 30}])
    assert fin == "" and "< proud FVE" in why
    p = build_project({"inverters": [{"ref": "T1", **_INV25, "p_ac": 30, "strings": [20]}], "ac": {"main_in": 40},
                       "connection": {"level": "vn", "transformer": {"sn": 50}}})
    qf = _hr_feeder(p)
    assert qf.attrs["in_"] == "" and [f.severity for f in _codes(p, LibraryStore(), "breaker_no_in")] == [ERROR]


def test_fuse_holder_limit_from_in_max_a_only():
    """Bod 3: mez držáku jen z in_max_a artiklu fuse_holder; In držáku (OPVP Ie) se do pojistky nepropisuje."""
    from envocad.generate import holder_max_in
    from envocad.model.project import Element
    lib = LibraryStore()
    assert {cid: holder_max_in(lib.component(cid)) for cid in
            ("oez-opvp10-2", "oez-opvp14-3-s", "oez-opvp22-1", "eaton-chpv1u", "eaton-chpv2u", "eti-efh-10-dc-2p")} \
        == {"oez-opvp10-2": 32, "oez-opvp14-3-s": 63, "oez-opvp22-1": 125, "eaton-chpv1u": 30, "eaton-chpv2u": None,
            "eti-efh-10-dc-2p": 25}
    assert holder_max_in(lib.component("eaton-pv-2a10f")) is None and holder_max_in(None) is None   # vložka, ne držák
    opvp = lib.component("oez-opvp10-2")
    assert opvp.params["in_"] == "32" and "in_" not in opvp.attr_values()
    e = Element("fve.fuse_disconnect", attrs={"ref": "F1", "in_": "16"})
    opvp.apply_to(e)
    assert e.attrs["in_"] == "16" and e.component_id == "oez-opvp10-2"


def test_fuse_component_keeps_fuse_in_and_f7_over_holder():
    """Bod 3: artikl držáku nepřepíše In pojistky; In vložky > max. In držáku → chyba F7 `fuse_over_holder`."""
    lib = LibraryStore()
    spec = {"module": {"isc": 9.0}, "dc": {"fuse_component": "oez-opvp10-2"},
            "inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}]}
    p = build_project(spec)
    assert {f.attrs["in_"] for f in _fuses(p)} == {"15"} and {f.component_id for f in _fuses(p)} == {"oez-opvp10-2"}
    assert not _codes(p, lib, "fuse_over_holder")
    p = build_project({**spec, "dc": {"fuse_component": "eti-efh-10-dc-2p", "fuse_in": 32}})
    over = _codes(p, lib, "fuse_over_holder")
    assert len(over) == len(_fuses(p)) == 2 and all(f.severity == ERROR and "25 A" in f.text for f in over)


def test_solaredge_fuse_respects_holder_limit():
    """Bod 3: OPTIMIZER_FUSE_IN (25 A) jen do max. In držáku."""
    from envocad.generate import fuse_in_why
    from envocad.model.calc import string_fuse_in
    from envocad.model.project import Element
    assert string_fuse_in(None, optimizer=True, max_in=25) == 25.0
    assert string_fuse_in(None, optimizer=True, max_in=20) is None
    se = Element("fve.inverter", attrs={"type": "SolarEdge SE10K"})
    assert fuse_in_why({"fuse_in": "", "fuse_component": "oez-opvp10-2"}, {"isc": 9}, {}, se) == ("25", "")


def test_unresolved_fuse_marked_and_logged_once(caplog):
    """Bod 4 + 8: pojistka bez řešení nese in_unresolved (chyba F7 s důvodem); varování jednou za střídač, i když
    má střídač rozvaděče po trase."""
    import logging
    spec = {"module": {"isc": 18.5}, "dc": {"route_boxes": 2},
            "inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}]}
    with caplog.at_level(logging.WARNING, logger="envocad.generate"):
        p = build_project(spec)
    assert len([r for r in caplog.records if "Pojistka stringu" in r.getMessage()]) == 1
    fuses = _fuses(p)
    assert fuses and all("gPV nevyhoví" in f.attrs["in_unresolved"] for f in fuses)
    errs = _codes(p, LibraryStore(), "fuse_no_in")
    assert len(errs) == len(fuses) and all(f.severity == ERROR and "Isc 18.5" in f.text for f in errs)


def test_module_without_isc_gives_empty_in_with_reason():
    """Bod 7 (záměrný dopad): modul bez Isc → prázdné In + chyba F7 „modul nemá Isc“ (dřív tiché 15 A)."""
    p = build_project({"module": {"isc": ""}, "inverters": [{"ref": "T1", **_INV25, "strings": [20]}]})
    assert [f.attrs["in_unresolved"] for f in _fuses(p)] == ["modul nemá Isc"]
    assert [f.severity for f in _codes(p, LibraryStore(), "fuse_no_in")] == [ERROR]


def test_resolve_values_skips_unresolved_variable():
    """Bod 5: proměnná se zástupnou hodnotou (In neurčené generátorem) se nevaliduje (max, nabídka, povinnost);
    přebitá sadou / zadáním se validuje normálně."""
    from envocad.generate import UNRESOLVED_IN
    from envocad.library.macros import Macro, MacroVar, resolve_values
    m = Macro(name="T", description="", fragment={"elements": [], "wires": []}, path=None, source="",
              variables=[MacroVar(name="fuse_in", label="In", type="number", required=True, max=63),
                         MacroVar(name="c", label="Char", type="choice", choices=("gPV",), default="gPV")])
    base = {"fuse_in": UNRESOLVED_IN}
    _vals, errs = resolve_values(m, base=base, repeat=False)
    assert errs                                                          # bez příznaku: 987654321 > 63
    vals, errs = resolve_values(m, base=base, repeat=False, unresolved={"fuse_in"})
    assert not errs and vals["fuse_in"] == UNRESOLVED_IN
    _vals, errs = resolve_values(m, base=base, given={"fuse_in": "80"}, repeat=False, unresolved={"fuse_in"})
    assert errs and "80" in errs[0]


def test_blank_unresolved_cleans_wires_and_double_spaces():
    """Bod 5: zástupné In se vymaže z prvků i vodičů (texty) bez zdvojené mezery."""
    from envocad.generate import UNRESOLVED_IN, _blank_unresolved
    from envocad.model.project import Element, Wire, WireEnd
    e = Element("fve.fuse_disconnect", attrs={"in_": UNRESOLVED_IN, "desc": f"gPV {UNRESOLVED_IN} A 1000 V"})
    w = Wire(WireEnd("a", "1"), WireEnd("b", "1"), attrs={"note": f"pojistka {UNRESOLVED_IN} A"})
    _blank_unresolved([e], [w])
    assert (e.attrs["in_"], e.attrs["desc"], w.attrs["note"]) == ("", "gPV A 1000 V", "pojistka A")


def _inside(p, sh, lib):
    from envocad.model.frame import inner_box
    from envocad.model.textlayout import sheet_content_boxes
    x0, y0, x1, y1 = inner_box(sh.width, sh.height)
    return all(b[0] >= x0 and b[1] >= y0 and b[2] <= x1 and b[3] <= y1 for b in sheet_content_boxes(p, sh, lib))


def test_dc_template_9_strings_fits_sheet():
    """Bod 6: šablona DC rozvaděče s 9 stringy po 50 mm přetékala A3 (420 mm) – list se zvětší, obsah uvnitř."""
    from envocad.library.templates import apply_template
    from envocad.model import multipole as mp
    from envocad.model.project import Element, Project
    lib = LibraryStore()
    for n, paper in ((4, "A3"), (9, "A2")):
        p = Project()
        blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
        p.sheets[0].elements.append(blk)
        sh = p.create_switchboard_sheet(blk)
        apply_template(p, sh, "dc", {"n_strings": str(n)}, lib=lib, standard_paper="A4")
        assert sh.paper == paper and _inside(p, sh, lib)
        # vícepól a plán svorkovnice zůstávají na stranách firemního standardu (ne na rozměru zvětšeného listu)
        assert mp.paper_choice(sh) == mp.DEFAULT_SWITCHBOARD_PAPER
    p = build_project({"inverters": [{"ref": "T1", **_INV25, "strings": [20] * 9}]})
    dcs = [sh for sh in p.sheets if sh.loc.startswith(("RDC", "RFVE.DC"))]
    # generátor: prodloužený formát na šířku se stejnou výškou (`frame.grow_sheet_long`), ne vyšší list
    assert dcs and all(sh.paper == "A4×3" and sh.height == 297.0 and _inside(p, sh, lib) for sh in dcs)


def test_grow_sheet_to_content_keeps_fitting_sheet():
    from envocad.library.templates import apply_template
    from envocad.model.frame import grow_sheet_to_content
    from envocad.model.project import Project
    lib = LibraryStore()
    p = Project()
    sh = p.sheets[0]
    apply_template(p, sh, "dc", {"n_strings": "2"}, standard_paper="A4")
    pos = [(e.x, e.y) for e in sh.elements]
    assert not grow_sheet_to_content(p, sh, lib, standard_paper="A4") and sh.paper == "A3" and pos == [(e.x, e.y) for e in sh.elements]


@pytest.mark.parametrize("level", [" VN ", "vn", "Vn\t"])
def test_connection_level_strip_lower(level):
    """Bod 10: `connection.level` sjednoceně .strip().lower() (i RD odmítne „ VN “)."""
    p = build_project({"inverters": [{"ref": "T1", **_INV25, "strings": [20]}], "connection": {"level": level}})
    assert any(sh.loc == "HR" for sh in p.sheets)
    with pytest.raises(ValueError, match="Rodinný dům"):
        build_project({"building": "house", "inverters": [{"ref": "T1", **_HOUSE_INV, "strings": [12]}],
                       "connection": {"level": level}})
