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


# ---- optimizéry (docs/design/optimizery.md §4) --------------------------------------------------------------------
def _optimizer(**kw):
    params = {"p_max_w": "440", "u_in_max_v": "60", "isc_in_max_a": "14.5", "u_out_max_v": "60",
              "modules_per_optimizer": "1", "compat": "SolarEdge", "n_min_3ph": "14", "n_max_3ph": "50",
              "p_string_max_3ph_w": "11250", "string_mode": "fixed_voltage"}
    params.update(kw.pop("params", {}))
    return Component(id="t-opt", manufacturer="Test", part_number="TO-440", name="Testovací optimizér",
                     category="optimizer", symbol_id="", source="datasheet", params=params, **kw)


def test_picker_optimizer_columns_and_unverified(app):
    web = _optimizer(params={"note": "WebSearch 2026-10-17"})
    web.id, web.part_number = "t-opt-web", "TO-WEB"
    d = ComponentPicker(FakeLibrary([_optimizer(), web, _module(), _inverter()]), categories=("optimizer",))
    heads = [d.table.horizontalHeaderItem(i).text() for i in range(d.table.columnCount())]
    assert heads == ["Výrobce", "Typ", "P [W]", "Uin max [V]", "Isc in [A]", "Moduly/opt.", "Kompatibilita", "Zdroj"]
    assert len(d._rows) == 2 and d.p_unit.text() == "[W]"
    ok = next(r for r, c in enumerate(d._rows) if c.id == "t-opt")
    assert d.table.item(ok, 2).text() == "440" and not d.table.item(ok, 0).toolTip()
    assert "WebSearch" in d.table.item(1 - ok, 0).toolTip()
    d.p_to.setText("400")
    assert [c.id for c in d._rows] == [] or all(c.num("p_max_w") is None for c in d._rows)


def test_wizard_optimizer_component_mode_and_spec(app):
    d = ProjectWizard(library=FakeLibrary([_optimizer()]))
    assert d.spec()["optimizer"] == {"type": "", "per_module": 1}   # bez artiklu beze změny
    assert "string_mode" not in d.spec()["inverters"][0]
    d.set_optimizer_component(_optimizer())
    assert d.opt_type.text() == "TO-440" and d.opt_per.text() == "1" and "Testovací optimizér" in d.opt_label.text()
    assert d.spec()["optimizer"]["component_id"] == "t-opt"
    d.set_optimizer_component(_optimizer(params={"modules_per_optimizer": "2"}))
    assert d.opt_per.text() == "0.5" and d.spec()["optimizer"]["per_module"] == 0.5
    assert [d.string_mode.itemText(i) for i in range(4)] == [
        "Automaticky (z artiklu)", "Klasický", "S optimizéry", "Pevné napětí"]
    d.string_mode.setCurrentIndex(2)
    assert d.spec()["inverters"][0]["string_mode"] == "optimizer"
    d.clear_optimizer()
    assert "component_id" not in d.spec()["optimizer"] and "nevybrán" in d.opt_label.text()


def test_wizard_optimizer_assistant_lines(app):
    d = ProjectWizard(library=FakeLibrary([]))
    d.set_module_component(_module(params={"p_wp": "400", "isc_a": "13.9"}))
    d.set_inverter_component(_inverter(params={"u_string_v": "750", "u_dc_max_v": "900"}))
    d.set_optimizer_component(_optimizer())          # režim z artiklu optimizéru: fixed_voltage
    d.strings.setText("20,13,14")
    txt = d.assistant_text()
    assert "Režim stringů: pevné napětí" in txt and "optimizérů 14–50" in txt and "P stringu ≤ 11250 W" in txt
    assert "Optimizér TO-440:" in txt and "Uin max 60 V" in txt
    assert "13 modulů" in txt and "13 optimizérů ve stringu < min 14" in txt
    d.string_mode.setCurrentIndex(1)                 # Klasický přebije artikl
    assert "Režim stringů: klasický" in d.assistant_text() and "pevné napětí" not in d.assistant_text()


def _same_as_f7(d):
    from envocad.model import calc
    assistant = [issues for group in d.string_results() for _n, issues in group]
    f7 = [sc.issues for sc in calc.check_strings(build_project(d.spec()))]
    assert assistant == f7
    for issues in assistant:
        for msg in issues:
            assert msg in d.assistant_text()
    return assistant


@pytest.mark.parametrize("opt_id, inv_id, mode, strings, fields", [
    ("solaredge-s440-1gm4mrm", "solaredge-se5k-rw0teben4", 0, "10,14,20,30", {}),
    ("solaredge-s440-1gm4mrm", "solaredge-se5k-rw0teben4", 1, "14,20", {}),          # classic + vstup optimizéru
    ("huawei-sun2000-450w-p2", "huawei-sun2000-50ktl-m3", 0, "20,20,18; 22", {}),
    ("huawei-sun2000-450w-p2", "huawei-sun2000-50ktl-m3", 3, "20,14", {}),
    (None, "sma-stp-25-50", 0, "20,18,22,22,20,16,20", {"mod_isc": "10"}),           # classic, různé délky na MPPT
    (None, "huawei-sun2000-50ktl-m3", 0, "20,18,22,24,20,16,20", {}),
])
def test_assistant_optimizer_matches_f7(app, builtin_lib, opt_id, inv_id, mode, strings, fields):
    d = ProjectWizard(library=builtin_lib)
    d.set_module_component(builtin_lib.component("ja-solar-jam54d40-445-mb"))
    d.set_inverter_component(builtin_lib.component(inv_id))
    if opt_id:
        d.set_optimizer_component(builtin_lib.component(opt_id))
    d.string_mode.setCurrentIndex(mode)
    for name, text in fields.items():
        getattr(d, name).setText(text)
    d.strings.setText(strings)
    _same_as_f7(d)
    if opt_id:
        assert "Optimizér " in d.assistant_text()


def test_assistant_parallel_strings_warning(app, builtin_lib):
    d = ProjectWizard(library=builtin_lib)
    d.set_module_component(builtin_lib.component("ja-solar-jam54d40-445-mb"))
    d.set_inverter_component(builtin_lib.component("sma-stp-25-50"))   # 3 MPPT × 2 stringy
    d.strings.setText("20,16,20,20")                  # 1. a 2. string sdílejí MPPT 1
    res = _same_as_f7(d)
    assert any("nestejná délka" in m for issues in res for m in issues)
    assert "#b26a00" in d.assistant_text()           # jen varování → oranžově


def test_propose_strings_with_optimizer_step(app, builtin_lib, warned):
    d = ProjectWizard(library=builtin_lib)
    d.set_module_component(builtin_lib.component("ja-solar-jam54d40-445-mb"))
    d.set_inverter_component(builtin_lib.component("huawei-sun2000-50ktl-m3"))
    d.set_optimizer_component(builtin_lib.component("huawei-sun2000-450w-p2"))
    d.mod_total.setText("60")
    d.strings.setText("20")
    d.propose_strings()
    assert d.strings.text()
    res = _same_as_f7(d)
    assert all(not any("není dovoleno" in m for m in issues) for issues in res)


# ---- review optimizérů: vymazaný typ, ruční ks/modul, 1f pravidla (fixture artikly, ne vestavěná CSV) -------------
def test_clearing_optimizer_type_drops_component(app):
    d = ProjectWizard(library=FakeLibrary([_optimizer()]))
    d.set_optimizer_component(_optimizer())
    assert d.spec()["optimizer"]["component_id"] == "t-opt"
    d.opt_type.setText("")                         # vymazaný typ = bez optimizérů
    assert d._opt_comp is None and "nevybrán" in d.opt_label.text()
    assert "component_id" not in d.spec()["optimizer"]
    p = build_project(d.spec())
    assert all(not e.attrs.get("n_optimizers") and not e.attrs.get("optimizer_id")
               for e in p.sheets[0].elements if e.symbol_id == "fve.pv_string")


def test_manual_per_module_against_component_is_reported(app):
    d = ProjectWizard(library=FakeLibrary([]))
    d.set_module_component(_module())
    d.set_inverter_component(_inverter())
    d.set_optimizer_component(_optimizer(params={"modules_per_optimizer": "2", "string_mode": ""}))
    assert "neodpovídá artiklu" not in d.assistant_text()
    d.opt_per.setText("1")                         # ručně přepsáno – nesmí se tiše přebít
    txt = d.assistant_text()
    assert "Ručně zadané 1 ks/modul neodpovídá artiklu (2 moduly na optimizér)" in txt and "0.5 ks/modul" in txt
    d.clear_optimizer()                            # bez artiklu se ruční hodnota použije
    assert "neodpovídá artiklu" not in d.assistant_text()


def test_fixed_voltage_manual_half_per_module_even_lengths(app, warned):
    d = ProjectWizard(library=FakeLibrary([]))
    d.set_module_component(_module(params={"p_wp": "400"}))
    d.set_inverter_component(_inverter(params={"mppt": "1", "u_string_v": "750", "u_dc_max_v": "900",
                                               "string_mode": "fixed_voltage", "n_opt_min": "8", "n_opt_max": "25",
                                               "p_string_max_w": "11250"}))
    d.opt_type.setText("Ruční 2:1")
    d.opt_per.setText("0.5")                       # bez artiklu: 2 moduly na optimizér → délky po 2
    assert "po 2 modulech" in d.assistant_text()
    d.mod_total.setText("51")
    d.propose_strings()
    groups = d._string_groups()
    assert groups and all(n % 2 == 0 for g in groups for n in g)
    assert not any("optimizér musí být na každém modulu" in m for row in d.string_results() for _n, i in row
                   for m in i)


class _CatalogOverLibrary:
    """Skutečná knihovna (symboly, makra) + testovací artikly – pro `build_project` z průvodce."""

    def __init__(self, real, comps):
        self._real, self._c = real, comps

    def component(self, cid):
        return next((c for c in self._c if c.id == cid), None) or self._real.component(cid)

    def components(self, *a, **k):
        return list(self._c)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_assistant_single_phase_rules_match_f7(app, monkeypatch):
    """1f střídač: pravidla optimizéru `*_1ph` (přes `phases`) v asistentu i v generátoru / F7."""
    from envocad.generator import context
    from envocad.library.store import LibraryStore
    from envocad.model import calc
    opt = _optimizer(params={"n_min_1ph": "8", "n_max_1ph": "25", "p_string_max_1ph_w": "6200", "compat": "Test",
                             "n_min_3ph": "16", "n_max_3ph": "50", "p_string_max_3ph_w": "11250"})
    inv1 = _inverter(params={"phases": "1", "p_ac_kw": "5", "mppt": "1", "u_string_v": "380", "u_dc_max_v": "480"})
    mod = _module(params={"p_wp": "400", "u_sys_max_v": "1000"})
    lib = _CatalogOverLibrary(LibraryStore(), [opt, inv1, mod])
    # knihovna generátoru je jen v `generator.context` (re-export v `generate` by byl kopie, patch by nepůsobil)
    monkeypatch.setattr(context, "_lib", lambda: lib)
    d = ProjectWizard(library=lib)
    d.set_module_component(mod)
    d.set_inverter_component(inv1)
    d.set_optimizer_component(opt)
    d.strings.setText("7,15,16")                   # 7 < min 8 (1f); 15 ok; 16·400 W = 6400 > 6200 W (1f)
    txt = d.assistant_text()
    assert "optimizérů 8–25" in txt and "P stringu ≤ 6200 W" in txt and "16–50" not in txt
    res = [issues for row in d.string_results() for _n, issues in row]
    assert "7 optimizérů ve stringu < min 8" in res[0] and res[1] == []
    assert "P stringu 6400 W > max 6200 W" in res[2]
    f7 = [sc.issues for sc in calc.check_strings(build_project(d.spec()))]
    assert res == f7
    # stejný optimizér na 3f střídači → pravidla *_3ph
    d.set_inverter_component(_inverter(params={"phases": "3", "u_string_v": "750", "u_dc_max_v": "900"}))
    assert "optimizérů 16–50" in d.assistant_text() and "P stringu ≤ 11250 W" in d.assistant_text()
