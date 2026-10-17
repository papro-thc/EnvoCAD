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
