"""Artikly FV modulů a střídačů: nové sloupce, validace, propsání do prvku (bez Qt)."""

import csv
import json

from envocad.library import components
from envocad.library.components import Component, inverter_error, pv_module_error
from envocad.library.store import BUILTIN_DIR, LibraryStore
from envocad.model.project import Element

CSV_DIR = BUILTIN_DIR / "components"
MODULE_ROW = {"id": "test-mod-450", "manufacturer": "Test", "part_number": "TM-450", "name": "FV modul 450 Wp",
              "category": "pv_module", "symbol_id": "fve.pv_string", "datasheet_url": "https://example.com/tm.pdf",
              "source": "web", "p_wp": "450", "voc_v": "49,5", "vmp_v": "41.5", "isc_a": "13.9", "imp_a": "10.85",
              "beta_voc": "-0.27", "u_sys_max_v": "1500"}
INV_ROW = {"id": "test-inv-25", "manufacturer": "Test", "part_number": "TI-25", "name": "Střídač 25 kW",
           "category": "inverter", "symbol_id": "fve.inverter", "datasheet_url": "https://example.com/ti.pdf",
           "source": "web", "u_dc_max_v": "1100", "u_mppt_min_v": "200", "u_mppt_max_v": "1000", "i_mppt_max_a": "30",
           "strings_per_mppt": "2", "isc_mppt_max_a": "40"}


def _write(path, rows):
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    return path


def test_new_columns_numeric_and_mapped():
    assert {"alpha_isc", "gamma_pmax", "noct_c", "u_sys_max_v", "i_fuse_max_a", "weight_kg", "isc_mppt_max_a",
            "eff_max_pct", "eff_eu_pct"} <= components.NUMERIC
    assert components.PARAM_TO_ATTR["imp_a"] == "imp"
    assert components.PARAM_TO_ATTR["u_sys_max_v"] == "u_sys_max"
    assert components.PARAM_TO_ATTR["isc_mppt_max_a"] == "isc_mppt_max"
    # teplotní součinitele modulu → atributy stringu (Umpp(t) = γ_Pmax − α_Isc, `calc.ModuleData.vmp_coeff`)
    assert components.PARAM_TO_ATTR["gamma_pmax"] == "gamma_pmax" and components.PARAM_TO_ATTR["alpha_isc"] == "alpha_isc"
    for key in ("noct_c", "eff_eu_pct", "technology"):   # jen katalog
        assert key not in components.PARAM_TO_ATTR


def test_attr_values_and_apply_to():
    c = Component.from_row(MODULE_ROW)
    vals = c.attr_values()
    assert vals == {"type": "TM-450", "manufacturer": "Test", "p_module": "450", "voc": "49,5", "isc": "13.9",
                    "vmp": "41.5", "beta_voc": "-0.27", "imp": "10.85", "u_sys_max": "1500"}
    e = Element("fve.pv_string", 0, 0, attrs={"ref": "G1", "voc": "49,5", "n_modules": "20"})
    changed = c.apply_to(e)
    assert "voc" not in changed and changed["imp"] == "10.85" and e.component_id == "test-mod-450"
    assert e.attrs["n_modules"] == "20" and e.attrs["u_sys_max"] == "1500"
    inv = Component.from_row(INV_ROW)
    assert inv.attr_values()["isc_mppt_max"] == "40" and inv.attr_values()["strings_per_mppt"] == "2"


def test_pv_module_error():
    assert pv_module_error(MODULE_ROW) is None
    assert "voc_v" in pv_module_error({**MODULE_ROW, "voc_v": ""})
    assert "isc_a" in pv_module_error({**MODULE_ROW, "isc_a": ""})
    assert "'vmp_v'" in pv_module_error({**MODULE_ROW, "vmp_v": "50"})
    assert "'imp_a'" in pv_module_error({**MODULE_ROW, "imp_a": "14"})
    assert "beta_voc" in pv_module_error({**MODULE_ROW, "beta_voc": "0.27"})
    assert "beta_voc" in pv_module_error({**MODULE_ROW, "beta_voc": "-1.2"})
    assert "p_wp" in pv_module_error({**MODULE_ROW, "p_wp": "500"})          # 41,5·10,85 = 450,3 W ≠ 500 Wp
    assert pv_module_error({**MODULE_ROW, "p_wp": "460"}) is None           # 2,1 % – v toleranci
    many = pv_module_error({**MODULE_ROW, "vmp_v": "60", "beta_voc": "0.3"})
    assert "vmp_v" in many and "beta_voc" in many and ";" in many
    # nepovinné hodnoty prázdné → jen povinné voc/isc
    assert pv_module_error({"voc_v": "49.5", "isc_a": "13.9"}) is None


def test_inverter_error():
    assert inverter_error(INV_ROW) is None
    assert inverter_error({}) is None                                        # vestavěné střídače zatím bez hodnot
    assert "u_mppt_min_v" in inverter_error({**INV_ROW, "u_mppt_min_v": "1000"})
    assert "u_dc_max_v" in inverter_error({**INV_ROW, "u_mppt_max_v": "1200"})
    assert "strings_per_mppt" in inverter_error({**INV_ROW, "strings_per_mppt": "0"})
    assert "strings_per_mppt" in inverter_error({**INV_ROW, "strings_per_mppt": "1.5"})


def test_validate_checks_modules_and_inverters(tmp_path):
    ok = _write(tmp_path / "ok.csv", [MODULE_ROW, INV_ROW])
    assert components.validate(ok, {"fve.pv_string", "fve.inverter"}) == []
    bad = _write(tmp_path / "bad.csv", [{**MODULE_ROW, "vmp_v": "55"}, {**INV_ROW, "u_mppt_max_v": "1200"},
                                        {**INV_ROW, "id": "test-hyb", "category": "inverter_hybrid",
                                         "strings_per_mppt": "0"}])
    errs = components.validate(bad)
    assert len(errs) == 3
    assert "test-mod-450" in errs[0] and "vmp_v" in errs[0]
    assert "test-inv-25" in errs[1] and "test-hyb" in errs[2]


def test_builtin_headers_and_empty_pv_modules(tmp_path):
    inv_head = (CSV_DIR / "inverters.csv").read_text(encoding="utf-8-sig").splitlines()[0].split(";")
    for col in ("u_dc_max_v", "u_mppt_min_v", "u_mppt_max_v", "i_mppt_max_a", "strings_per_mppt", "isc_mppt_max_a",
                "eff_max_pct", "eff_eu_pct", "weight_kg"):
        assert col in inv_head
    mod_file = CSV_DIR / "pv_modules.csv"
    mod_head = mod_file.read_text(encoding="utf-8-sig").splitlines()[0].split(";")
    for col in (*components.REQUIRED, "p_wp", "voc_v", "vmp_v", "isc_a", "imp_a", "beta_voc", "alpha_isc",
                "gamma_pmax", "noct_c", "u_sys_max_v", "i_fuse_max_a", "technology", "width_mm", "height_mm",
                "depth_mm", "weight_kg", "t_min_c", "t_max_c"):
        assert col in mod_head
    assert components.validate(mod_file) == []
    assert all(c.category == "pv_module" for c in components.read_csv(mod_file))
    # soubor jen s hlavičkou: přečte se jako prázdný, store ho načte bez chyby
    empty = tmp_path / "pv_modules.csv"
    empty.write_text(mod_file.read_text(encoding="utf-8-sig").splitlines()[0] + "\n", encoding="utf-8")
    assert components.read_csv(empty) == [] and components.validate(empty) == []
    lib = LibraryStore()
    assert lib.import_components_csv_v2(empty) == 0
    assert all(c.category == "pv_module" for c in lib.components(category="pv_module"))


def test_hidden_string_and_inverter_attributes():
    for sid, keys in (("fve.pv_string", ("imp", "u_sys_max")), ("fve.inverter", ("isc_mppt_max",)),
                      ("fve.inverter_hybrid", ("isc_mppt_max",))):
        data = json.loads((BUILTIN_DIR / "fve" / f"{sid}.json").read_text(encoding="utf-8"))
        attrs = {a["key"]: a for a in data["attributes"]}
        for k in keys:
            assert k in attrs and not attrs[k]["show"], (sid, k)


def test_settings_design_temperatures():
    from envocad.settings import load_settings
    st = load_settings()["standard"]
    assert st["pv_t_min"] == -20 and st["pv_t_max"] == 70


# ---- optimizéry a režim stringu střídače (docs/design/optimizery.md) -------------------------------------------
OPT_ROW = {"id": "test-opt-850", "manufacturer": "TestEdge", "part_number": "TP850", "name": "Optimizér 850 W",
           "category": "optimizer", "symbol_id": "", "datasheet_url": "https://example.com/o.pdf", "source": "web",
           "p_max_w": "850", "p_tol_pct": "", "u_in_max_v": "125", "u_mppt_min_v": "12,5", "u_mppt_max_v": "105",
           "isc_in_max_a": "14.5", "i_out_max_a": "15", "u_out_max_v": "85", "modules_per_optimizer": "2",
           "string_mode": "fixed_voltage", "partial_ok": "0", "compat": "TestEdge", "n_min_1ph": "6",
           "n_max_1ph": "12", "p_string_max_1ph_w": "5700", "n_min_3ph": "8", "n_max_3ph": "25",
           "p_string_max_3ph_w": "11250"}


def test_optimizer_category_and_columns():
    assert "optimizer" in components.CATEGORIES and "optimizer" not in components.DEFAULT_SYMBOL
    for col in ("p_max_w", "p_tol_pct", "u_in_max_v", "isc_in_max_a", "i_out_max_a", "u_out_max_v",
                "modules_per_optimizer", "partial_ok", "n_min_1ph", "n_max_3ph", "p_string_max_1ph_w",
                "p_string_max_3ph_w", "u_string_v", "n_opt_min", "n_opt_max", "p_string_max_w"):
        assert col in components.NUMERIC, col
    assert {components.PARAM_TO_ATTR[k] for k in ("string_mode", "u_string_v", "n_opt_min", "n_opt_max",
                                                  "p_string_max_w")} == {"string_mode", "u_string", "n_opt_min",
                                                                         "n_opt_max", "p_string_max"}
    from envocad.model import calc
    assert components.STRING_MODES == calc.STRING_MODES


def test_optimizer_values_by_phase():
    c = Component.from_row(OPT_ROW)
    assert c.symbol_id == "" and c.category == "optimizer"
    v3 = c.optimizer_values(3)
    assert v3 == {"optimizer": "TP850", "opt_manufacturer": "TestEdge", "opt_p_max": "850", "opt_u_in_max": "125",
                  "opt_u_mppt_min": "12,5", "opt_u_mppt_max": "105", "opt_isc_in_max": "14.5", "opt_i_out_max": "15", "opt_u_out_max": "85",
                  "opt_modules": "2", "opt_partial": "0", "opt_compat": "TestEdge", "optimizer_id": "test-opt-850",
                  "opt_n_min": "8", "opt_n_max": "25", "opt_p_string_max": "11250"}
    v1 = c.optimizer_values("1")
    assert (v1["opt_n_min"], v1["opt_n_max"], v1["opt_p_string_max"]) == ("6", "12", "5700")
    assert c.optimizer_values("?")["opt_n_min"] == "8"                       # neznámá fáze = 3f
    # nekoliduje s atributy modulu (type / manufacturer)
    assert not {"type", "manufacturer"} & set(v3)
    from envocad.model import calc
    o = calc.OptimizerData.from_attrs(v3)
    assert (o.modules, o.u_mppt_min, o.n_min, o.p_string_max, o.compat) == (2, 12.5, 8, 11250, "TestEdge")


def test_optimizer_error():
    assert components.optimizer_error(OPT_ROW) is None
    errs = components.optimizer_error({})
    assert "p_max_w" in errs and "u_in_max_v" in errs and "isc_in_max_a" in errs and "modules_per_optimizer" in errs
    assert "u_mppt_max_v" in components.optimizer_error({**OPT_ROW, "u_mppt_max_v": "130"})
    assert "u_mppt_min_v" in components.optimizer_error({**OPT_ROW, "u_mppt_min_v": "110"})
    assert "modules_per_optimizer" in components.optimizer_error({**OPT_ROW, "modules_per_optimizer": "3"})
    assert "string_mode" in components.optimizer_error({**OPT_ROW, "string_mode": "pevne"})
    assert components.optimizer_error({**OPT_ROW, "string_mode": ""}) is None
    assert "partial_ok" in components.optimizer_error({**OPT_ROW, "partial_ok": "2"})
    assert "n_min_3ph" in components.optimizer_error({**OPT_ROW, "n_min_3ph": "30"})
    assert "n_max_1ph" in components.optimizer_error({**OPT_ROW, "n_max_1ph": "1.5"})
    assert "p_tol_pct" in components.optimizer_error({**OPT_ROW, "p_tol_pct": "150"})


def test_inverter_error_string_mode():
    se = {**INV_ROW, "string_mode": "fixed_voltage", "u_string_v": "750", "n_opt_min": "16", "n_opt_max": "50",
          "p_string_max_w": "11250"}
    assert inverter_error(se) is None
    assert "string_mode" in inverter_error({**INV_ROW, "string_mode": "solaredge"})
    assert "u_string_v" in inverter_error({**se, "u_string_v": ""})               # fixed_voltage ⇒ u_string
    assert "u_string_v" in inverter_error({**se, "u_string_v": "1200"})           # > u_dc_max
    assert "n_opt_min" in inverter_error({**se, "n_opt_min": "60"})
    assert inverter_error({**INV_ROW, "string_mode": "optimizer"}) is None


def test_validate_optimizer_rows(tmp_path):
    ok = _write(tmp_path / "opt.csv", [OPT_ROW])
    assert components.validate(ok, {"fve.pv_string"}) == []                   # prázdné symbol_id je v pořádku
    bad = _write(tmp_path / "bad.csv", [{**OPT_ROW, "isc_in_max_a": ""}, {**OPT_ROW, "id": "x2", "p_max_w": "abc"}])
    errs = components.validate(bad)
    assert any("test-opt-850" in e and "isc_in_max_a" in e for e in errs)
    assert any("x2" in e and "'p_max_w' musí být číslo" in e for e in errs)
    lib = LibraryStore()
    assert lib.import_components_csv_v2(ok) == 1
    c = lib.component("test-opt-850")
    assert c.category == "optimizer" and c.optimizer_values(1)["opt_n_max"] == "12"
    assert "test-opt-850" in [x.id for x in lib.components(category="optimizer")]


def test_builtin_optimizer_and_inverter_headers():
    head = (CSV_DIR / "optimizers.csv").read_text(encoding="utf-8-sig").splitlines()[0].split(";")
    for col in (*components.REQUIRED, "p_max_w", "p_tol_pct", "u_in_max_v", "u_mppt_min_v", "u_mppt_max_v",
                "isc_in_max_a", "i_out_max_a", "u_out_max_v", "modules_per_optimizer", "string_mode", "partial_ok",
                "compat", "n_min_1ph", "n_max_1ph", "p_string_max_1ph_w", "n_min_3ph", "n_max_3ph",
                "p_string_max_3ph_w", "eff_max_pct", "weight_kg", "t_min_c", "t_max_c", "note"):
        assert col in head, col
    assert components.validate(CSV_DIR / "optimizers.csv") == []
    assert all(c.category == "optimizer" for c in components.read_csv(CSV_DIR / "optimizers.csv"))
    inv_head = (CSV_DIR / "inverters.csv").read_text(encoding="utf-8-sig").splitlines()[0].split(";")
    for col in ("string_mode", "u_string_v", "n_opt_min", "n_opt_max", "p_string_max_w"):
        assert col in inv_head, col


def test_hidden_optimizer_and_mode_attributes():
    for sid, keys in (("fve.pv_string", ("optimizer_id", "opt_manufacturer", "opt_p_max", "opt_p_tol", "opt_u_in_max",
                                         "opt_u_mppt_min", "opt_u_mppt_max", "opt_isc_in_max", "opt_i_out_max", "opt_u_out_max",
                                         "opt_modules", "opt_partial", "opt_compat", "opt_n_min", "opt_n_max",
                                         "opt_p_string_max", "orientation")),
                      ("fve.inverter", ("string_mode", "u_string", "n_opt_min", "n_opt_max", "p_string_max")),
                      ("fve.inverter_hybrid", ("string_mode", "u_string", "n_opt_min", "n_opt_max", "p_string_max"))):
        data = json.loads((BUILTIN_DIR / "fve" / f"{sid}.json").read_text(encoding="utf-8"))
        attrs = {a["key"]: a for a in data["attributes"]}
        for k in keys:
            assert k in attrs and not attrs[k]["show"] and attrs[k]["default"] == "", (sid, k)
    # optimizer_values plní jen atributy, které značka stringu zná
    data = json.loads((BUILTIN_DIR / "fve" / "fve.pv_string.json").read_text(encoding="utf-8"))
    assert set(Component.from_row(OPT_ROW).optimizer_values()) <= {a["key"] for a in data["attributes"]}
