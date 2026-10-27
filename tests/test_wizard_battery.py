"""Průvodce novým projektem: volba baterie u hybridního střídače (batteries.csv, `library/batteries.py`)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from envocad.generate import build_project
from envocad.library.components import Component
from envocad.library.store import LibraryStore
from envocad.ui.dialogs import ProjectWizard


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _plain_inverter():
    return Component(id="t-inv", manufacturer="Test", part_number="TI-25", name="Testovací střídač",
                     category="inverter", symbol_id="fve.inverter", source="datasheet",
                     params={"p_ac_kw": "25", "u_dc_max_v": "1100", "u_mppt_min_v": "200", "u_mppt_max_v": "1000",
                             "i_mppt_max_a": "26"})


def _wizard():
    lib = LibraryStore()
    return ProjectWizard(library=lib), lib


def test_battery_hidden_without_hybrid_inverter(app):
    d, lib = _wizard()
    assert d.grp_battery.isHidden() and "battery" not in d.spec()
    d.set_inverter_component(_plain_inverter())                  # nehybridní střídač
    assert d.grp_battery.isHidden() and d.battery_spec() is None and "battery" not in d.spec()
    d.set_inverter_component(lib.component("solax-x3-hyb-10.0-p"))
    assert not d.grp_battery.isHidden()
    assert d.bat_combo.itemText(0) == "bez baterie" and "battery" not in d.spec()     # výchozí = bez baterie
    d.clear_inverter()
    assert d.grp_battery.isHidden() and "battery" not in d.spec()


def test_battery_choice_spec_and_generation(app):
    d, lib = _wizard()
    d.set_inverter_component(lib.component("solax-x3-hyb-10.0-p"))
    assert d.bat_combo.itemText(1).startswith("SolaX")           # výrobce střídače první
    d.bat_combo.setCurrentIndex(d.bat_combo.findData("solax-t-bat-h-5.8-v3"))
    assert (d.bat_modules.minimum(), d.bat_modules.maximum(), d.bat_modules.value()) == (1, 6, 1)
    assert d.bat_bms.isHidden()                                  # master + slave, BMS zvlášť není
    d.bat_modules.setValue(3)
    assert "17.4 kWh" in d.bat_info.text() and "HV11550-A V3" in d.bat_info.text()
    assert d.spec()["battery"] == {"component_id": "solax-t-bat-h-5.8-v3", "modules": 3}
    d.strings.setText("16,16")
    p = build_project(d.spec())
    bat = next(e for s in p.sheets for e in s.elements if e.symbol_id == "fve.battery")
    assert bat.attrs["e_kwh"] == "17.4" and bat.component_id == "solax-t-bat-h-5.8-v3"
    assert any(e.symbol_id == "fve.inverter_hybrid" for s in p.sheets for e in s.elements)
    d.refresh_summary()                                          # souhrn průvodce zmiňuje baterii
    assert "T-BAT H 5.8 V3" in d.summary.text()
    # zpět na „bez baterie“ i výměna za nehybridní střídač: klíč `battery` ve specifikaci chybí
    d.bat_combo.setCurrentIndex(0)
    assert "battery" not in d.spec() and d.bat_info.text() == "" and not d.bat_modules.isEnabled()
    d.bat_combo.setCurrentIndex(d.bat_combo.findData("solax-t-bat-h-5.8-v3"))
    d.set_inverter_component(_plain_inverter())
    assert d.grp_battery.isHidden() and "battery" not in d.spec()


def test_battery_choice_survives_inverter_change_within_hybrids(app):
    d, lib = _wizard()
    d.set_inverter_component(lib.component("solax-x3-hyb-10.0-p"))
    d.bat_combo.setCurrentIndex(d.bat_combo.findData("solax-t-bat-h-5.8-v3"))
    d.bat_modules.setValue(4)
    d.set_inverter_component(lib.component("solax-x3-hyb-12.0-p"))      # jiný hybrid: volba zůstane
    assert d.bat_combo.currentData() == "solax-t-bat-h-5.8-v3" and d.bat_modules.value() == 4
    d.set_inverter_component(lib.component("growatt-sph5000"))          # jiný výrobce: SolaX nepasuje, volba zmizí
    assert d.bat_combo.findData("solax-t-bat-h-5.8-v3") == -1 and d.bat_combo.currentData() == ""
    assert d.bat_combo.findData("growatt-apx-5.0p-b1") == -1            # APX jen k MIN …TL-XH (inv_compat)
    d.bat_all.setChecked(True)                                          # i ostatní: výrobce střídače první
    assert d.bat_combo.itemText(1).startswith("Growatt") and d.bat_combo.findData("solax-t-bat-h-5.8-v3") > 0


def test_battery_only_compatible_with_inverter(app):
    """Nabídka baterií podle střídače: vzory `inv_compat` z datasheetu baterie, jinak stejný výrobce."""
    d, lib = _wizard()
    d.set_inverter_component(lib.component("huawei-sun2000-5ktl-m1"))
    ids = [d.bat_combo.itemData(i) for i in range(1, d.bat_combo.count())]
    assert "huawei-luna2000-5-e0" in ids                                 # LUNA2000 S0 k SUN2000-…KTL-M1
    assert "huawei-luna2000-241-2s1" not in ids                          # úložiště s vlastním PCS („-“)
    assert all(lib.component(i).manufacturer == "Huawei" for i in ids)
    d.set_inverter_component(lib.component("huawei-sun2000-10k-map0"))
    assert d.bat_combo.findData("huawei-luna2000-5-e0") == -1            # MAP0 v seznamu LUNA2000 S0 není
    d.set_inverter_component(lib.component("goodwe-gw10k-et-20"))
    assert d.bat_combo.findData("goodwe-lx-f9.8-h") > 0


def test_battery_bms_selection(app):
    d, lib = _wizard()
    d.set_inverter_component(lib.component("solax-x3-hyb-10.0-p"))
    d.bat_combo.setCurrentIndex(d.bat_combo.findData("solax-tp-hs36"))
    assert (d.bat_modules.minimum(), d.bat_modules.value()) == (2, 2)          # HS36: od 2 modulů
    assert not d.bat_bms.isHidden() and d.bat_bms.currentData() == "solax-tbms-mcs0800"     # jediná BMS = předvolba
    assert d.spec()["battery"] == {"component_id": "solax-tp-hs36", "modules": 2, "bms_id": "solax-tbms-mcs0800"}
    assert d.bat_combo.findData("sigenergy-sigenstack-bat-12.0") == -1     # jiný výrobce ke střídači nepasuje
    d.bat_all.setChecked(True)                                              # „i ostatní baterie“
    d.bat_combo.setCurrentIndex(d.bat_combo.findData("sigenergy-sigenstack-bat-12.0"))
    assert d.bat_bms.count() == 6 and d.bat_bms.currentData() == ""            # 5 variant BC: volí uživatel
    assert "bms_id" not in d.spec()["battery"]
    d.bat_bms.setCurrentIndex(d.bat_bms.findData("sigenergy-sigenstack-bc-m2-1c-bst"))
    assert d.spec()["battery"]["bms_id"] == "sigenergy-sigenstack-bc-m2-1c-bst"
    d.bat_combo.setCurrentIndex(d.bat_combo.findData("huawei-luna2000-241-2s1"))
    assert (d.bat_modules.minimum(), d.bat_modules.maximum()) == (1, 1) and d.bat_bms.isHidden()


def test_battery_screenshot(app, tmp_path):
    d, lib = _wizard()
    d.set_inverter_component(lib.component("solax-x3-hyb-10.0-p"))
    d.bat_combo.setCurrentIndex(d.bat_combo.findData("solax-tp-hs36"))
    d.bat_modules.setValue(4)
    d.goto(2)
    d.resize(900, 760)
    d.show()
    app.processEvents()
    out = tmp_path / "wizard_baterie.png"
    assert d.grab().save(str(out)) and out.stat().st_size > 5000
