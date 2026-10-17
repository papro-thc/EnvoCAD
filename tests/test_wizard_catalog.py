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


# ---- review katalogu FV ------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def builtin_lib():
    from envocad.library.store import LibraryStore
    return LibraryStore()


@pytest.mark.parametrize("mod_id, inv_id, strings, fields", [
    ("canadian-solar-cs6.1-60tb-505", "sma-stp-25-50", "16,16,16", {}),            # rovnoměrně po MPPT
    (None, None, "20,20", {"inv_isc_mppt": "25", "mod_isc": "14", "mod_imp": "13"}),  # stringů/MPPT neznámé
    (None, None, "20,20,18", {"inv_isc_mppt": "25", "inv_spm": "2"}),               # mppt neznámé → za sebou
    ("canadian-solar-cs6.1-60tb-505", "sma-stp-25-50", "12,12,12,12,12,12,12,12", {}),   # víc stringů než vstupů
    (None, "huawei-sun2000-100ktl-m2", "18,18,18,18; 18,18", {"mod_isc": "18", "mod_voc": "60"}),
    ("ja-solar-jam54d40-445-mb", "sma-stp-25-50", "22,22,10", {"t_min": "−25 °C"}),
])
def test_assistant_matches_check_strings(app, builtin_lib, mod_id, inv_id, strings, fields):
    from envocad.model import calc
    d = ProjectWizard(library=builtin_lib)
    if mod_id:
        d.set_module_component(builtin_lib.component(mod_id))
    if inv_id:
        d.set_inverter_component(builtin_lib.component(inv_id))
    for name, text in fields.items():
        getattr(d, name).setText(text)
    d.strings.setText(strings)
    assistant = [issues for group in d.string_results() for _n, issues in group]
    f7 = [sc.issues for sc in calc.check_strings(build_project(d.spec()))]
    assert assistant == f7
    for issues in assistant:   # text asistenta ukazuje stejné hlášky
        for msg in issues:
            assert msg in d.assistant_text()


def test_assistant_capacity_and_missing_p_ac(app):
    d = ProjectWizard()
    d.set_inverter_component(_inverter())        # 3 MPPT × 2 stringy
    d.strings.setText("12," * 7 + "12")
    assert "Střídač T1 má jen 6 vstupů (MPPT × stringů), zapojeno 8 stringů" in d.assistant_text()
    assert [bool(i) for _n, i in d.string_results()[0]] == [False] * 6 + [True] * 2
    d.inv_p.setText("")
    d.clear_inverter()
    assert "P AC střídače není zadán" in d.assistant_text() and "DC/AC =" not in d.assistant_text()


def test_assistant_umpp_beta_reason(app):
    d = ProjectWizard()
    d.set_module_component(_module())
    assert "Umpp z β_Voc – zjednodušení" in d.assistant_text()
    d.set_module_component(_module(params={"gamma_pmax": "-0.29", "alpha_isc": "0.046"}))
    assert "zjednodušení" not in d.assistant_text()


def test_propose_left_plural(app, warned):
    d = ProjectWizard()
    d.set_module_component(_module())
    d.set_inverter_component(_inverter(params={"p_ac_kw": "100"}))   # jeden střídač: 6 stringů × 19 = 114 modulů
    d.t_min.setText("-20")
    d.strings.setText("19")
    d.mod_total.setText("115")
    d.propose_strings()
    assert warned and warned[-1].startswith("Nevešel se 1 modul ")
    d.mod_total.setText("117")
    d.propose_strings()
    assert warned[-1].startswith("Nevešly se 3 moduly ")


def test_wizard_temperatures_typographic_minus(app):
    d = ProjectWizard()
    d.t_min.setText("−25 °C")
    d.t_max.setText("75 °C")
    assert d.errors() == [] and d.spec()["site"] == {"t_min": -25, "t_max": 75}
    assert "Uoc při -25 °C" in d.assistant_text()
    d.t_min.setText("zima")
    assert any("Návrhová teplota min" in e and "není číslo" in e for e in d.errors())


def test_project_meta_dialog_validates_temperatures(app, warned):
    from envocad.model.project import Project
    from envocad.ui.dialogs import ProjectMetaDialog
    p = Project(name="T")
    dlg = ProjectMetaDialog(p)
    dlg.edits["pv_t_min"].setText("−20 °C")
    dlg.edits["pv_t_max"].setText("70,5")
    assert dlg.errors() == []
    assert dlg.values()[1]["pv_t_min"] == "-20" and dlg.values()[1]["pv_t_max"] == "70.5"
    dlg.edits["pv_t_min"].setText("abc")
    assert dlg.errors() and "není číslo" in dlg.errors()[0]
    dlg.accept()                                    # chyba → dialog se nezavře
    assert warned and dlg.result() != ProjectMetaDialog.Accepted
    dlg.edits["pv_t_min"].setText("80")
    assert any("menší než max" in e for e in dlg.errors())
    dlg.edits["pv_t_min"].setText("")               # prázdné = výchozí, smí se uložit
    assert dlg.errors() == [] and "pv_t_min" not in dlg.values()[1]


def test_picker_websearch_note_unverified(app):
    web = _inverter(params={"note": "max DC 1000 V; doplněno WebSearch 2026-10-17: u_mppt_max_v dle e-shopu"})
    d = ComponentPicker(FakeLibrary([web]), categories=("inverter",))
    it = d.table.item(0, 0)
    assert it.font().italic() and "neověřeno" in it.toolTip() and "WebSearch" in it.toolTip()


def test_builtin_web_sourced_inverters_marked_web(builtin_lib):
    for cid in ("sma-stp-25-50", "sma-stp-110-60", "huawei-sun2000-100ktl-m2"):
        assert builtin_lib.component(cid).source == "web"


def test_picker_filters_keep_unknown_values(app):
    unknown = Component(id="i3", manufacturer="Test", part_number="TI-?", name="Bez výkonu", category="inverter",
                        symbol_id="fve.inverter", source="datasheet",
                        params={"u_dc_max_v": "1000", "u_mppt_min_v": "200", "u_mppt_max_v": "800"})
    d = ComponentPicker(FakeLibrary([_inverter(), unknown]), categories=("inverter",))
    assert d.table.item([c.id for c in d._rows].index("i3"), 0).toolTip() == ""   # bez filtru v pořádku
    d.p_from.setText("20")
    assert {c.id for c in d._rows} == {"t-inv", "i3"}
    it = d.table.item([c.id for c in d._rows].index("i3"), 0)
    assert it.font().italic() and "filtr Výkon" in it.toolTip()
    d.p_from.setText("30")                           # známý výkon mimo filtr zmizí, neznámý zůstane
    assert [c.id for c in d._rows] == ["i3"]
    d.p_from.setText("")
    d.phases.setCurrentText("1")
    assert [c.id for c in d._rows] == ["i3"] and "filtr Fáze" in d.table.item(0, 0).toolTip()
