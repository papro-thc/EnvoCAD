"""Průvodce a výběr artiklu s katalogem FV (docs/design/katalog_fv.md §4) – vlastní testovací artikly, ne vestavěná CSV."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from envocad.generate import build_project
from envocad.library.components import Component
from envocad.ui.component_picker import ComponentPicker
from envocad.ui.dialogs import ProjectWizard


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _module(**kw):
    params = {"p_wp": "550", "voc_v": "49.9", "vmp_v": "41.8", "isc_a": "13.9", "imp_a": "13.16", "beta_voc": "-0.27",
              "u_sys_max_v": "1500", "technology": "TOPCon", "width_mm": "2278", "height_mm": "1134"}
    params.update(kw.pop("params", {}))
    return Component(id="t-mod", manufacturer="Test", part_number="TM-550", name="Testovací modul",
                     category="pv_module", symbol_id="fve.pv_string", source="datasheet", params=params, **kw)


def _inverter(**kw):
    params = {"p_ac_kw": "25", "p_dc_max_kwp": "37.5", "phases": "3", "mppt": "3", "strings_per_mppt": "2",
              "u_dc_max_v": "1100", "u_mppt_min_v": "200", "u_mppt_max_v": "1000", "i_mppt_max_a": "26",
              "isc_mppt_max_a": "40"}
    params.update(kw.pop("params", {}))
    return Component(id="t-inv", manufacturer="Test", part_number="TI-25", name="Testovací střídač",
                     category="inverter", symbol_id="fve.inverter", source="datasheet", params=params, **kw)


class FakeLibrary:
    def __init__(self, comps):
        self._c = comps

    def components(self, *a, **k):
        return list(self._c)

    def component(self, cid):
        return next((c for c in self._c if c.id == cid), None)


@pytest.fixture
def warned(monkeypatch):
    seen: list[str] = []
    for kind in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda *a, **k: seen.append(a[2]) or QMessageBox.Ok))
    return seen


def test_set_components_fill_fields(app):
    d = ProjectWizard(library=FakeLibrary([_module(), _inverter()]))
    d.set_module_component(_module())
    d.set_inverter_component(_inverter())
    assert d.mod_type.text() == "TM-550" and d.mod_p.text() == "550" and d.mod_voc.text() == "49.9"
    assert d.mod_imp.text() == "13.16" and d.mod_beta.text() == "-0.27"
    assert d.inv_p.text() == "25" and d.inv_udc.text() == "1100" and d.inv_isc_mppt.text() == "40"
    assert d.inv_spm.text() == "2" and "Testovací modul" in d.mod_label.text()
    d.clear_module()
    assert "nevybrán" in d.mod_label.text() and d.mod_voc.text() == "49.9"   # pole zůstanou
    assert "component_id" not in d.spec()["module"]


def test_assistant_range_and_manual_edit_wins(app):
    d = ProjectWizard()
    d.set_module_component(_module())
    d.set_inverter_component(_inverter())
    d.t_min.setText("-20")
    txt = d.assist.text()
    assert "Modulů ve stringu:" in txt and "Stringů na MPPT ≤ 2" in txt and "DC/AC" in txt
    d.inv_udc.setText("600")      # ruční úprava přebije artikl
    assert d.assist.text() != txt and "Umax střídače 600" in d.assist.text()
    d.strings.setText("30")       # 30 modulů překročí 600 V
    assert "Uoc" in d.assist.text() and "30 modulů" in d.assist.text()


def test_propose_strings_fills_field_and_spec(app, warned):
    d = ProjectWizard()
    d.set_module_component(_module())
    d.set_inverter_component(_inverter())
    d.mod_total.setText("120")
    d.propose_strings()
    assert not warned
    groups = d._string_groups()
    assert groups and sum(sum(g) for g in groups) == 120
    assert d.errors() == []
    spec = d.spec()
    assert spec["module"]["component_id"] == "t-mod" and spec["module"]["u_sys_max"] == 1500.0
    assert spec["module"]["imp"] == 13.16 and spec["module"]["beta_voc"] == -0.27
    assert spec["site"] == {"t_min": -20, "t_max": 70}
    assert all(i["component_id"] == "t-inv" and i["isc_mppt_max"] == 40 for i in spec["inverters"])


def test_string_errors_only_warn(app):
    d = ProjectWizard()
    d.set_module_component(_module())
    d.set_inverter_component(_inverter())
    d.strings.setText("40")      # Uoc 40·49.9 V >> 1100 V
    assert "Uoc" in d.assist.text()
    assert d.errors() == []      # chyba stringu neblokuje
    d.mod_beta.setText("0.3")
    assert any("β" in e for e in d.errors())


def test_generate_from_wizard_spec(app):
    d = ProjectWizard(library=FakeLibrary([]))
    d.set_module_component(_module())
    d.set_inverter_component(_inverter())
    d.strings.setText("20,20,18")
    p = build_project(d.spec())
    assert p.meta["pv_t_min"] == "-20"


def test_picker_inverter_columns_and_power_filter(app):
    lib = FakeLibrary([
        _inverter(),
        Component(id="i2", manufacturer="Test", part_number="TI-10", name="Malý", category="inverter_hybrid",
                  symbol_id="fve.inverter_hybrid", source="web",
                  params={"p_ac_kw": "10", "phases": "1", "u_dc_max_v": "600"}),
        _module(),
    ])
    d = ComponentPicker(lib, categories=("inverter", "inverter_hybrid"))
    heads = [d.table.horizontalHeaderItem(i).text() for i in range(d.table.columnCount())]
    assert "Str./MPPT" in heads and "Isc/MPPT [A]" in heads and "Hybrid" in heads and "Voc [V]" not in heads
    assert not d.p_from.isHidden() and d.in_.isHidden() and d.poles.isHidden()
    assert len(d._rows) == 2          # modul se nezobrazí
    d.p_from.setText("20")
    assert [c.id for c in d._rows] == ["t-inv"]
    d.p_from.setText("")
    d.phases.setCurrentText("1")
    assert [c.id for c in d._rows] == ["i2"]
    # neúplný / neověřený řádek: kurzíva a tooltip
    d.phases.setCurrentIndex(0)
    row = [c.id for c in d._rows].index("i2")
    it = d.table.item(row, 0)
    assert it.font().italic() and "okno MPPT" in it.toolTip() and "neověřeno" in it.toolTip()
    ok = d.table.item([c.id for c in d._rows].index("t-inv"), 0)
    assert not ok.font().italic() and ok.toolTip() == ""


def test_picker_module_columns(app):
    d = ComponentPicker(FakeLibrary([_module(), _inverter()]), categories=("pv_module",))
    heads = [d.table.horizontalHeaderItem(i).text() for i in range(d.table.columnCount())]
    assert "Voc [V]" in heads and "β Voc [%/K]" in heads and "Š×V [mm]" in heads and "Str./MPPT" not in heads
    assert len(d._rows) == 1
    size = heads.index("Š×V [mm]")
    assert d.table.item(0, size).text() == "2278 × 1134"
    d.p_to.setText("500")
    assert d._rows == []
