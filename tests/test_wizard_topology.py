"""Průvodce novým projektem – topologie připojení a stávající rozvaděče (F5, docs/design/topologie_f1_f2.md, kap. 2):
objekt a připojení, náhled řetězce, stávající rozvaděče v popisku bloků, skupiny střídačů, výchozí specifikace beze
změny, kontrola projektu (F7) bez chyb."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from envocad.generate import build_project
from envocad.ui.dialogs import ProjectWizard


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def warned(monkeypatch):
    seen: list[str] = []
    for kind in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda *a, **k: seen.append(a[2]) or QMessageBox.Ok))
    return seen


def _pick(combo, data):
    i = combo.findData(data)
    assert i >= 0, f"v nabídce chybí {data!r}: {[combo.itemData(k) for k in range(combo.count())]}"
    combo.setCurrentIndex(i)


def _blocks(p) -> dict:
    return {e.ref: e for s in p.sheets if not s.is_switchboard for e in s.elements if e.symbol_id == "fve.switchboard"}


def _wizard(building="company", level="nn") -> ProjectWizard:
    d = ProjectWizard()
    _pick(d.building, building)
    _pick(d.conn_level, level)
    d.strings.setText("18,18; 18,18")     # 2 střídače, 72 modulů
    return d


def _f7(p) -> list:
    from envocad.library.store import LibraryStore
    from envocad.model.checks import ERROR, WARNING, check_project
    return [(f.code, f.ref, f.text) for f in check_project(p, LibraryStore()) if f.severity in (ERROR, WARNING)]


# ---- výchozí průvodce = dnešní specifikace --------------------------------------------------------------------
@pytest.mark.parametrize("building,level", [("company", "nn"), ("house", "nn"), ("apartment", "nn"), ("company", "vn")])
def test_wizard_default_spec_has_no_topology_keys(app, building, level):
    d = ProjectWizard()
    base = d.spec()                        # výchozí průvodce (firma, nn)
    assert "topology" not in base and "chain" not in base
    d = _wizard(building, level)
    spec = d.spec()
    assert "topology" not in spec and "chain" not in spec
    assert all("ac_group" not in inv for inv in spec["inverters"])
    # projdou generátorem a F7 bez chyb a varování
    assert _f7(build_project(spec)) == []


def test_wizard_default_spec_equals_previous_keys(app):
    """Klíče výchozí specifikace jsou beze změny (topologie a chain se zapisují jen při změně)."""
    spec = ProjectWizard().spec()
    assert sorted(spec) == ["ac", "building", "connection", "dc", "grid", "inverters", "meta", "module", "name",
                            "optimizer", "site"]


def test_wizard_explicit_auto_preset_is_not_written(app):
    d = _wizard("house")
    _pick(d.topo.preset, "rd")             # totéž co automaticky
    assert "topology" not in d.spec()


# ---- objekt a připojení ---------------------------------------------------------------------------------------
def test_wizard_house_vn_disabled(app):
    d = _wizard("company", "vn")
    assert d.conn_level.isEnabled() and d.topo.chain_label.text().endswith("DS (+ RE)") or "RVN" in d.topo.chain_label.text()
    _pick(d.building, "house")
    assert d.conn_level.currentData() == "nn" and not d.conn_level.isEnabled()
    assert "přípojka VN" in d.topo.level_note.text() and not d.topo.level_note.isHidden()
    assert d.spec()["connection"]["level"] == "nn"
    _pick(d.building, "company")
    assert d.conn_level.isEnabled()


def test_wizard_preset_list_filtered_by_building_and_level(app):
    d = _wizard("company", "nn")
    ids = [d.topo.preset.itemData(i) for i in range(d.topo.preset.count())]
    assert ids == ["", "nn", "nn_hr_meter"]
    _pick(d.building, "house")
    assert [d.topo.preset.itemData(i) for i in range(d.topo.preset.count())] == ["", "rd"]
    _pick(d.building, "apartment")
    _pick(d.conn_level, "vn")
    assert [d.topo.preset.itemData(i) for i in range(d.topo.preset.count())] == ["", "vn"]
    assert d.topo.preset.itemText(0).startswith("Automaticky")


def test_wizard_chain_preview_follows_choices(app):
    d = _wizard("company", "nn")
    assert d.topo.chain_label.text() == "stringy → RFVE.DC → T → RFVE.AC → HR → RE → HDS → DS"
    _pick(d.topo.metering_at, "hr")
    assert d.topo.selected_id() == "nn_hr_meter"
    assert d.topo.chain_label.text() == "stringy → RFVE.DC → T → RFVE.AC → HR → HDS → DS"
    assert d.spec()["topology"] == "nn_hr_meter"
    _pick(d.topo.metering_at, "re")
    assert d.topo.selected_id() == "" and "RE" in d.topo.chain_label.text() and "topology" not in d.spec()
    _pick(d.building, "house")
    assert d.topo.chain_label.text() == "stringy → RFVE → T → RD → RE → HDS → DS"
    assert not d.topo.metering_at.isEnabled()
    _pick(d.building, "company")
    _pick(d.conn_level, "vn")
    assert "RVN" in d.topo.chain_label.text() and "TR" in d.topo.chain_label.text()
    _pick(d.conn_level, "nn")
    assert "HR → RE → HDS" in d.topo.chain_label.text()


def test_wizard_shared_and_custom_topologies_in_list(app, tmp_path, monkeypatch):
    import json

    from envocad.library import topologies
    monkeypatch.setenv("ENVOCAD_HOME", str(tmp_path))
    own = tmp_path / "topologies"
    own.mkdir()
    src = topologies.BUILTIN_DIR / "nn.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    data.update(id="muj_nn", name="Moje nn")
    (own / "muj_nn.json").write_text(json.dumps(data), encoding="utf-8")
    topologies.clear_cache()
    d = _wizard("company", "nn")
    texts = [d.topo.preset.itemText(i) for i in range(d.topo.preset.count())]
    assert "Moje nn (vlastní)" in texts
    _pick(d.topo.preset, "muj_nn")
    assert d.spec()["topology"] == "muj_nn"
    assert _f7(build_project(d.spec())) == []
    topologies.clear_cache()


def test_wizard_rfve_dc_per_inverter_only_with_two_inverters(app):
    d = _wizard("company", "nn")
    assert d.topo.dc_per_inv.isEnabled() and not d.topo.dc_per_inv.isChecked()
    assert "chain" not in d.spec()
    d.topo.dc_per_inv.setChecked(True)
    assert d.spec()["chain"]["rfve_dc"] == {"per_inverter": "1"}
    d.strings.setText("18,18")
    assert not d.topo.dc_per_inv.isEnabled() and "chain" not in d.spec()
    _pick(d.building, "house")
    d.strings.setText("18; 18")
    assert not d.topo.dc_per_inv.isEnabled()      # RD nemá RFVE.DC


def test_wizard_grid_protection_info_and_choice(app, ac_builtin_fn):
    d = _wizard("company", "nn")
    d.mod_p.setText("450")                          # 72 × 450 Wp = 32,4 kWp
    assert "32,4" in d.topo.gp_info.text().replace(".", ",") and "se vloží" in d.topo.gp_info.text()
    assert "30" in d.topo.gp_info.text()
    d.strings.setText("18; 18")                     # 16,2 kWp
    assert "se nevloží" in d.topo.gp_info.text()
    _pick(d.topo.gp, "1")
    assert d.spec()["chain"]["rfve_ac"] == {"grid_protection": "1"}
    p = build_project(d.spec())
    assert any(e.symbol_id == "fve.grid_protection" for s in p.sheets for e in s.elements)
    d2 = _wizard("house", "nn")
    _pick(d2.topo.gp, "0")
    assert d2.spec()["chain"]["rfve"] == {"grid_protection": "0"}


# ---- stávající rozvaděče -------------------------------------------------------------------------------------
def test_wizard_existing_boards_into_block_labels(app):
    d = _wizard("company", "nn")
    t = d.topo
    _pick(t.main_device, "switch")
    t.main_in.setText("250")
    _pick(t.fve_device, "fuse_disconnect")
    t.fve_in.setText("90")
    t.re_in.setText("200")
    _pick(t.meter_mode, "indirect")
    t.ct_ratio.setText("200/5 A")
    _pick(t.boundary, "re_meter")
    t.hds_in.setText("315")
    t.hds_char.setText("gL")
    spec = d.spec()
    assert spec["chain"] == {
        "hr": {"main_device": "switch", "main_in": 250, "fve_device": "fuse_disconnect", "fve_in": 90},
        "re": {"main_in": 200, "metering": "indirect", "ct_ratio": "200/5 A", "boundary": "re_meter"},
        "hds": {"in_": 315, "char": "gL"}}
    assert d.errors() == []
    p = build_project(spec)
    b = _blocks(p)
    assert b["HR"].attrs["main"] == "hlavní vypínač 250 A"
    assert b["HR"].attrs["fve_out"] == "pojistkový odpínač 90 A"
    assert "HJ" in b["RE"].attrs.get("main", "") or "200" in str(b["RE"].attrs)
    assert "nepřímé" in str(b["RE"].attrs) and "200/5" in str(b["RE"].attrs)
    hds = next(e for s in p.sheets for e in s.elements if e.symbol_id == "fve.hds")
    assert hds.attrs["in_"] == "315" and hds.attrs["char"] == "gL"
    assert _f7(p) == []


def test_wizard_existing_boards_empty_means_unspecified(app):
    d = _wizard("company", "nn")
    p = build_project(d.spec())
    hr = _blocks(p)["HR"]
    assert hr.attrs["main"] == "hlavní jistič" and "A" not in hr.attrs["main"]
    assert _f7(p) == []


def test_wizard_metering_in_hr(app):
    d = _wizard("company", "nn")
    _pick(d.topo.metering_at, "hr")
    assert not d.topo.re_in.isEnabled() and not d.topo.main_device.isEnabled()
    d.topo.main_in.setText("125")                  # HJ v HR
    _pick(d.topo.meter_mode, "indirect")
    spec = d.spec()
    assert spec["topology"] == "nn_hr_meter"
    assert spec["chain"]["hr"] == {"main_in": 125, "metering": "indirect"}
    p = build_project(spec)
    assert "RE" not in _blocks(p)
    hr = _blocks(p)["HR"]
    assert "125" in hr.attrs["main"] and "nepřímé" in hr.attrs["metering"]
    assert _f7(p) == []


def test_wizard_house_existing_rd(app):
    d = _wizard("house", "nn")
    d.strings.setText("12,12")
    assert d.topo.main_label.text() == "Hlavní přístroj RD"
    d.topo.main_in.setText("40")
    _pick(d.topo.main_device, "breaker")
    d.topo.re_in.setText("40")
    d.topo.hds_in.setText("63")
    spec = d.spec()
    assert spec["chain"]["rd"] == {"main_device": "breaker", "main_in": 40}
    p = build_project(spec)
    assert _blocks(p)["RD"].attrs["main"] == "hlavní jistič 40 A"
    assert _f7(p) == []
    assert "EPS" in d.topo.eps_note.text() and not d.topo.eps_note.isHidden()


def test_wizard_fuse_up_to_80a_unavailable(app, warned):
    d = _wizard("company", "nn")
    t = d.topo
    item = t.fve_device.model().item(1)
    assert item.isEnabled()
    t.fve_in.setText("63")
    assert not item.isEnabled()                    # pojistkový odpínač do 80 A nedostupný
    assert "80" in t.fve_note.text()
    t.fve_in.setText("80")
    assert not item.isEnabled()
    t.fve_in.setText("100")
    assert item.isEnabled()
    _pick(t.fve_device, "fuse_disconnect")
    t.fve_in.setText("63")                         # vybraná pojistka a In ≤ 80 A: chyba, dialog se nezavře
    assert any("musí být jistič" in e for e in d.errors())
    with pytest.raises(ValueError, match="musí být jistič"):
        d.spec()
    d.accept()
    assert d.result() != ProjectWizard.Accepted and warned and "musí být jistič" in warned[-1]
    _pick(t.fve_device, "breaker")
    assert d.errors() == []


def test_wizard_generator_error_shown_in_wizard(app, warned):
    """Chyba, kterou ohlásí až generátor (pojistka s dopočteným In ≤ 80 A), se zobrazí v průvodci."""
    d = _wizard("company", "nn")
    d.strings.setText("18")
    _pick(d.topo.fve_device, "fuse_disconnect")    # In prázdné → dopočte se (malý výkon, ≤ 80 A)
    assert d.errors() == []
    errs = d.generator_errors()
    assert errs and "musí být jistič" in errs[0]
    d.accept()
    assert d.result() != ProjectWizard.Accepted and "musí být jistič" in warned[-1]


def test_wizard_invalid_numbers_report_czech_errors(app):
    d = _wizard("company", "nn")
    d.topo.main_in.setText("abc")
    d.topo.hds_in.setText("-5")
    errs = d.errors()
    assert any("In hlavního přístroje" in e for e in errs) and any("In HDS" in e for e in errs)
    with pytest.raises(ValueError, match="In HDS"):
        d.spec()


def test_wizard_vn_keeps_connection_fields_and_disables_existing(app):
    d = _wizard("company", "vn")
    assert not d.topo.main_in.isEnabled() and not d.topo.re_in.isEnabled()
    assert "vn" in d.topo.existing_note.text()
    d.tr_sn.setText("1000")
    _pick(d.conn_station, "kobky")
    spec = d.spec()
    assert spec["connection"]["level"] == "vn" and spec["connection"]["station"] == "kobky"
    assert spec["connection"]["transformer"] == {"sn": 1000}
    assert "chain" not in spec and "topology" not in spec
    assert _f7(build_project(spec)) == []


@pytest.mark.parametrize("case", ["firma", "bd", "hr_meter", "rd"])
def test_wizard_filled_boards_f7_clean_with_sheets(app, ac_builtin_fn, case):
    """Vyplněné stávající rozvaděče i s listy vestavěným kódem: F7 bez chyb a varování."""
    d = _wizard("house" if case == "rd" else "apartment" if case == "bd" else "company", "nn")
    t = d.topo
    d.strings.setText("18,18")
    if case == "hr_meter":
        _pick(t.metering_at, "hr")
        t.main_in.setText("250")
    elif case == "rd":
        d.strings.setText("12,12")
        d.strings.setText("16,16")
        t.main_in.setText("80")
        t.re_in.setText("80")
        t.hds_in.setText("100")
    else:
        t.main_in.setText("250")
        t.re_in.setText("250")
        t.hds_in.setText("315")      # nepřímé měření: list RE vestavěným kódem má překryv textu vícepólu (F2), viz výše
        if case == "bd":
            _pick(t.boundary, "re_main")
    p = build_project(d.spec())
    assert _f7(p) == []


# ---- skupiny střídačů ---------------------------------------------------------------------------------------
def test_wizard_ac_groups(app):
    d = _wizard("company", "nn")
    d.strings.setText("18,18; 18,18")
    edits = d.topo._group_edits
    assert len(edits) == 2 and all(e.isEnabled() for e in edits)
    edits[1].setText("Hala B")
    spec = d.spec()
    assert "ac_group" not in spec["inverters"][0] and spec["inverters"][1]["ac_group"] == "Hala B"
    p = build_project(spec)
    assert {"RFVE.AC", "RFVE.AC2"} <= set(_blocks(p)) or len([r for r in _blocks(p) if r.startswith("RFVE.AC")]) == 2
    assert _f7(p) == []
    d.strings.setText("18,18; 18,18; 18")       # počet střídačů se změní, text zůstane u T2
    assert d.topo._group_edits[1].text() == "Hala B" and len(d.topo._group_edits) == 3
    _pick(d.building, "house")                    # u RD skupiny nejdou – pole zakázaná a nezapisují se
    assert not any(e.isEnabled() for e in d.topo._group_edits)
    assert all("ac_group" not in inv for inv in d.spec()["inverters"])
    _pick(d.building, "company")
    _pick(d.conn_level, "vn")
    assert all("ac_group" not in inv for inv in d.spec()["inverters"])


def test_wizard_topology_error_blocks_nothing_for_defaults(app):
    d = _wizard("company", "nn")
    assert d.topo.topo_error.isHidden() and d.errors() == [] and d.generator_errors() == []


# ---- screenshoty (ruční kontrola rozvržení) -------------------------------------------------------------------
@pytest.mark.skipif(not os.environ.get("WIZARD_SHOTS"), reason="jen na vyžádání (WIZARD_SHOTS=adresář)")
def test_wizard_screenshots(app):
    from pathlib import Path
    out = Path(os.environ["WIZARD_SHOTS"])
    out.mkdir(parents=True, exist_ok=True)

    def shot(d, name):
        d.resize(980, 1500)
        d.show()
        app.processEvents()
        body = d.findChildren(__import__("PySide6.QtWidgets", fromlist=["QScrollArea"]).QScrollArea)[0]
        body.widget().adjustSize()
        d.resize(980, body.widget().sizeHint().height() + 80)
        app.processEvents()
        d.grab().save(str(out / f"{name}.png"))

    d = _wizard("company", "nn")
    d.topo.main_in.setText("250")
    _pick(d.topo.fve_device, "fuse_disconnect")
    d.topo.fve_in.setText("63")
    _pick(d.topo.meter_mode, "indirect")
    d.topo._group_edits[1].setText("Hala B")
    shot(d, "firma_nn")
    shot(_wizard("house", "nn"), "rd")
    shot(_wizard("company", "vn"), "vn")
