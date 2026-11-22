"""Oteplení po přístrojích: teplota vzduchu v řadě přístroje × rozsah provozní teploty z datasheetu (t_min/t_max)."""
import json
import os
from pathlib import Path

import pytest

from envocad.library.components import PARAM_TO_ATTR, Component, temperature_range_error, validate
from envocad.model.checks import INFO, WARNING, thermal_findings
from envocad.model.project import Element, Project, Sheet, enclosure_param_error
from envocad.model.thermal import (
    DEFAULT_T_MAX_C,
    DEFAULT_T_MIN_C,
    DeviceTemp,
    ThermalResult,
    air_temperature,
    ambient_min,
    device_temperatures,
    row_height_ratio,
    temperature_rise,
)

BUILTIN = Path(__file__).resolve().parents[1] / "envocad" / "library" / "builtin"


class FakeLib:
    """Knihovna jen s artikly (`component(cid)`)."""

    def __init__(self, *comps: Component):
        self._c = {c.id: c for c in comps}

    def component(self, cid):
        return self._c.get(cid)


def _art(cid, **params) -> Component:
    return Component(cid, "Výrobce", cid.upper(), "Jistič", "mcb", "fve.breaker_mcb", params=params)


def _board(*devs, rows=3, height=500, params=None):
    """List rozvaděče: `devs` = (ref, řada nebo None, atributy)."""
    p = Project()
    blk = Element("fve.switchboard", 0, 0, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    sb.layout.rows = rows
    sb.layout.params = {"width_mm": "500", "height_mm": str(height), "depth_mm": "200", "row_pitch_mm": "150",
                        **(params or {})}
    for i, (ref, row, attrs) in enumerate(devs):
        e = Element("fve.breaker_mcb", 0, 0, attrs={"ref": ref, "modules": "1", "p_loss_w": "15", **attrs})
        sb.elements.append(e)
        if row is not None:
            sb.layout.set_placement(e.id, row, float(i))
    return p, sb


def _el(sb, ref):
    return next(e for e in sb.elements if e.attrs.get("ref") == ref)


# ---- profil teploty ----------------------------------------------------------------------------------------------
def test_air_temperature_profile():
    assert air_temperature(35, 10, 14, 1.0) == pytest.approx(49)
    assert air_temperature(35, 10, 14, 0.75) == pytest.approx(47)           # lineárně mezi středem a horní částí
    assert air_temperature(35, 10, 14, 0.5) == pytest.approx(45)
    assert air_temperature(35, 10, 14, 0.1) == pytest.approx(45)            # spodní polovina konzervativně = střed
    assert air_temperature(35, 10, 14, None) == pytest.approx(49)           # neumístěný = horní část
    assert air_temperature(35, 10, 14, 2.0) == pytest.approx(49)            # mimo rozsah oříznuto


def test_row_height_ratio_rows_centered():
    _p, sb = _board()
    lay = sb.layout                                    # 3 řady × 150 mm ve skříni 500 mm: osy 400 / 250 / 100 mm
    assert [round(row_height_ratio(lay, r), 3) for r in range(3)] == [0.8, 0.5, 0.2]
    lay.params["height_mm"] = "300"                    # řady vyšší než skříň → výška = řady, ořez 0…1
    assert 0.0 <= row_height_ratio(lay, 2) < row_height_ratio(lay, 0) <= 1.0


def test_device_temperature_by_row_and_unplaced():
    p, sb = _board(("F1", 0, {}), ("F2", 1, {}), ("F3", 2, {}), ("F4", None, {}))
    r = temperature_rise(sb, project=p)
    by = {d.ref: d for d in r.devices}
    assert by["F1"].t_air == pytest.approx(r.air_at(0.8), abs=0.05)
    assert by["F2"].t_air == pytest.approx(r.t_ambient_c + r.dt_mid_k, abs=0.05)
    assert by["F3"].t_air == pytest.approx(by["F2"].t_air)                  # spodní řada jako střed
    assert by["F4"].row is None and by["F4"].t_air == pytest.approx(r.t_top_c, abs=0.05)
    assert by["F1"].t_air > by["F2"].t_air
    assert "neumístěný" in by["F4"].place and by["F1"].place == "v řadě 1"


# ---- zdroje mezí ------------------------------------------------------------------------------------------------
def test_t_max_sources_article_attribute_assumed():
    lib = FakeLib(_art("a1", t_max_c="70"), _art("a2", t_max_c="60"))
    p, sb = _board(("F1", 0, {"t_max": "70"}), ("F2", 0, {}), ("F3", 0, {"t_max": "55"}), ("F4", 0, {}))
    _el(sb, "F1").component_id = "a1"                 # F1: atribut = artikl → „artikl“
    _el(sb, "F2").component_id = "a2"                 # F2: atribut prázdný, artikl má údaj → „artikl“
    r = temperature_rise(sb, project=p, lib=lib)
    by = {d.ref: d for d in r.devices}
    assert (by["F1"].t_max, by["F1"].source) == (70, "artikl")
    assert (by["F2"].t_max, by["F2"].source) == (60, "artikl")
    assert (by["F3"].t_max, by["F3"].source) == (55, "atribut")
    assert (by["F4"].t_max, by["F4"].source) == (DEFAULT_T_MAX_C, "předpoklad")
    _el(sb, "F1").attrs["t_max"] = "65"               # ručně přepsaná hodnota artiklu → „atribut“
    assert {d.ref: d.source for d in temperature_rise(sb, project=p, lib=lib).devices}["F1"] == "atribut"
    # bez knihovny jen atributy
    assert {d.ref: d.source for d in temperature_rise(sb, project=p).devices}["F2"] == "předpoklad"


def test_verdict_ok_names_hottest_with_margin():
    p, sb = _board(("F1", 0, {"t_max": "70"}), ("F2", 2, {"t_max": "70"}))
    r = temperature_rise(sb, project=p)
    v = r.verdict()
    hot = max(r.devices, key=lambda d: d.t_air)
    assert v.startswith("vyhovuje (orientační – neověřeno proti normě) – nejteplejší F1 ≈")
    assert f"(t_max 70 °C, rezerva {70 - hot.t_air:.0f} K)" in v
    assert "chybí rozsah" not in v
    assert "F1 v řadě 1" in r.critical_text() and "(atribut)" in r.critical_text()


def test_verdict_one_device_exceeds():
    p, sb = _board(("F1", 2, {"t_max": "70"}), ("F3", 0, {"t_max": "42"}), ("F5", 1, {"t_max": "70"}))
    r = temperature_rise(sb, project=p, t_ambient_c=35)
    f3 = next(d for d in r.devices if d.ref == "F3")
    assert f3.t_air > 42 and f3.margin < 0
    v = r.verdict()
    assert v.startswith(f"NEVYHOVUJE (orientační – neověřeno proti normě) – F3 v řadě 1: ≈ {f3.t_air:.0f} °C > t_max 42 °C;"), v
    assert "a další" not in v and "(předpoklad)" not in v
    assert r.critical().ref == "F3" and "překročeno o" in r.critical_text()
    fs = thermal_findings(p)
    assert [(f.severity, f.ref) for f in fs] == [(WARNING, "F3")] and fs[0].code == "thermal_device"
    assert "> t_max 42 °C (atribut)" in fs[0].text


def test_verdict_with_assumed_limit_and_missing_data():
    p, sb = _board(("F1", 2, {"t_max": "70"}), ("F2", 2, {}), ("F3", 2, {}))
    r = temperature_rise(sb, project=p, t_ambient_c=20)                      # chladno → i 40 °C vyhovuje
    v = r.verdict()
    assert v.startswith("vyhovuje (orientační – neověřeno proti normě)")
    assert "u 2 přístrojů chybí rozsah teplot – ověřit (předpoklad 40 °C)" in v
    assert v.endswith("(předpoklad 40 °C)")
    r = temperature_rise(sb, project=p, t_ambient_c=38)                      # nad 40 °C jen podle předpokladu
    v = r.verdict()
    assert v.startswith("NEVYHOVUJE (orientační – neověřeno proti normě) – F2") and "t_max 40 °C (předpoklad), a další 1" in v
    assert "u 2 přístrojů chybí rozsah teplot" in v


def test_missing_data_aggregated_info_per_sheet():
    p, sb = _board(("F1", 0, {}), ("F2", 0, {}), ("F3", 1, {"t_max": "70"}), ("F4", None, {}))
    sb.layout.params["t_ambient"] = "35"
    fs = thermal_findings(p)
    assert len(fs) == 1 and fs[0].severity == INFO and fs[0].code == "thermal_device"
    assert "u 3 přístrojů chybí rozsah teplot" in fs[0].text and "(F1, F2, F4)" in fs[0].text
    assert "nad předpokladem: 3" in fs[0].text                                # 35 °C + Δt > 40 °C, ale bez dat → INFO
    for e in sb.elements:
        if e.symbol_id == "fve.breaker_mcb":
            e.attrs["t_max"] = "70"
    assert thermal_findings(p) == []


def test_one_missing_device_wording():
    r = ThermalResult(10, 10, 1, 5, 6, 0.8, 25, [])
    r.devices = [DeviceTemp("a", "F1", 0, 31, 55, "artikl"), DeviceTemp("b", "F2", 0, 31, 40, "předpoklad")]
    assert "u 1 přístroje chybí rozsah teplot" in r.verdict()


def test_t_min_checked_only_with_ambient_min():
    p, sb = _board(("F1", 0, {"t_max": "70", "t_min": "-5"}), ("F2", 0, {"t_max": "70", "t_min": "-40"}))
    r = temperature_rise(sb, project=p)
    assert r.t_ambient_min_c is None and all(d.t_min is None and d.t_min_source == "" for d in r.devices)
    assert r.verdict().startswith("vyhovuje")
    sb.layout.params["t_ambient_min"] = "-25"
    r = temperature_rise(sb, project=p)
    assert r.t_ambient_min_c == -25
    assert [d.ref for d in r.cold_devices()] == ["F1"]
    v = r.verdict()
    assert v.startswith("NEVYHOVUJE (orientační – neověřeno proti normě) – F1: t_min −5 °C > nejnižší okolí −25 °C") and "vytápění" in v
    fs = thermal_findings(p)
    assert [(f.severity, f.ref) for f in fs] == [(WARNING, "F1")] and "pod t_min −5 °C" in fs[0].text
    # přístroj bez t_min při zadaném minimu okolí → předpoklad −5 °C, počítá se mezi chybějící údaje
    del _el(sb, "F2").attrs["t_min"]
    r = temperature_rise(sb, project=p)
    f2 = next(d for d in r.devices if d.ref == "F2")
    assert (f2.t_min, f2.t_min_source) == (DEFAULT_T_MIN_C, "předpoklad") and f2.missing
    assert "t_min −5 °C" in r.missing_text()
    info = [f for f in thermal_findings(p) if f.severity == INFO]
    assert len(info) == 1 and "nad předpokladem: 1" in info[0].text


def test_ambient_min_param_parsing_and_validation():
    _p, sb = _board()
    assert ambient_min(sb.layout) is None
    sb.layout.params["t_ambient_min"] = "-20,5"
    assert ambient_min(sb.layout) == -20.5
    sb.layout.params["t_ambient_min"] = "abc"
    assert ambient_min(sb.layout) is None
    assert enclosure_param_error("t_ambient_min", "abc") and enclosure_param_error("t_ambient_min", "-80")
    assert enclosure_param_error("t_ambient_min", "-25") is None and enclosure_param_error("t_ambient_min", "") is None


def test_terminal_block_skipped_without_own_limit():
    p, sb = _board(("F1", 0, {"t_max": "70"}))
    x = Element("sb.terminal_block", 0, 0, attrs={"ref": "X1", "modules": "2"})
    sb.elements.append(x)
    sb.layout.set_placement(x.id, 1, 0.0)
    assert [d.ref for d in temperature_rise(sb, project=p).devices] == ["F1"]
    x.attrs["t_max"] = "100"
    assert [d.ref for d in temperature_rise(sb, project=p).devices] == ["F1", "X1"]


def test_device_temperatures_direct_call_and_layout_copy():
    p, sb = _board(("F1", 0, {"t_max": "60"}))
    r = temperature_rise(sb, project=p)
    other = type(sb.layout).from_dict(sb.layout.to_dict())
    other.set_placement(_el(sb, "F1").id, None, None)                       # rozpracovaná kopie: neumístěný
    d = device_temperatures(sb, r, other, p)[0]
    assert d.row is None and d.t_air == pytest.approx(r.t_top_c, abs=0.05)


# ---- artikly a knihovna -----------------------------------------------------------------------------------------
def test_article_temperature_columns(tmp_path):
    assert PARAM_TO_ATTR["t_min_c"] == "t_min" and PARAM_TO_ATTR["t_max_c"] == "t_max"
    e = Element("fve.breaker_mcb", 0, 0, attrs={"ref": "F1"})
    _art("x", t_min_c="-25", t_max_c="55").apply_to(e)
    assert e.attrs["t_min"] == "-25" and e.attrs["t_max"] == "55"
    head = "id;manufacturer;part_number;name;category;symbol_id;datasheet_url;source;t_min_c;t_max_c\n"
    rows = ["ok;A;1;n;mcb;fve.breaker_mcb;;user;-25;55", "ok2;A;2;n;mcb;fve.breaker_mcb;;user;;",
            "bad1;A;3;n;mcb;fve.breaker_mcb;;user;x;55", "bad2;A;4;n;mcb;fve.breaker_mcb;;user;60;55",
            "bad3;A;5;n;mcb;fve.breaker_mcb;;user;-25;300"]
    f = tmp_path / "t.csv"
    f.write_text(head + "\n".join(rows) + "\n", encoding="utf-8")
    errs = validate(f)
    assert len(errs) == 3, errs
    assert "bad1" in errs[0] and "'t_min_c' musí být číslo" in errs[0]
    assert "bad2" in errs[1] and "menší než 't_max_c'" in errs[1]
    assert "bad3" in errs[2] and "mimo věrohodný rozsah" in errs[2]
    assert temperature_range_error("", "") is None and temperature_range_error("-5", "") is None


def test_builtin_device_symbols_have_hidden_temperature_attrs():
    with_temp = set()
    for f in BUILTIN.glob("*/*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        if "attributes" not in d:
            continue
        keys = {a["key"]: a for a in d["attributes"]}
        mods = keys.get("modules", {}).get("default", "")
        if "t_max" in keys:
            assert "t_min" in keys and not keys["t_max"]["show"] and not keys["t_min"]["show"]
            assert keys["t_max"]["default"] == "" and keys["t_min"]["default"] == ""
            with_temp.add(d["id"])
        elif mods not in ("", "0") and d["id"] not in ("ctl.contact_power",):
            pytest.fail(f"{d['id']}: přístroj s moduly bez t_min/t_max")
    assert {"fve.breaker_mcb", "sb.rcd", "sb.main_switch", "fve.spd", "ctl.coil"} <= with_temp
    assert "sb.terminal_block" not in with_temp


def test_builtin_csv_temperature_values_have_source():
    """Vestavěné artikly: rozsah teplot je vyplněný jen s citovaným zdrojem (poznámka „t: … dle <URL>“), nic odhadnutého."""
    from envocad.library.components import read_csv
    found = False
    for f in (BUILTIN / "components").glob("*.csv"):
        for c in read_csv(f):
            tmin, tmax = c.params.get("t_min_c"), c.params.get("t_max_c")
            if tmin or tmax:
                assert tmin and tmax, c.id
                assert float(tmin) < float(tmax), c.id
                note = str(c.params.get("note", ""))
                assert "t: " in note and "http" in note, c.id
        found = found or "t_max_c" in f.read_text(encoding="utf-8").splitlines()[0]
    assert found


# ---- výstupy -----------------------------------------------------------------------------------------------------
def _docx_text(path) -> str:
    from docx import Document
    d = Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    return "\n".join(parts)


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    from envocad.library.store import LibraryStore
    return LibraryStore(tmp_path_factory.mktemp("lib") / "l.db")


def test_tz_and_protocol_show_device_verdict(lib, tmp_path):
    from envocad.export.docx_export import export_routine_test_docx
    from envocad.export.tz_export import export_tz_docx
    p, sb = _board(("F1", 2, {"t_max": "70"}), ("F3", 0, {"t_max": "42"}), ("F7", 1, {}))
    sb.name = "RH"
    export_tz_docx(p, lib, tmp_path / "tz.docx")
    tz = _docx_text(tmp_path / "tz.docx")
    assert "NEVYHOVUJE (orientační – neověřeno proti normě) – F3 v řadě 1:" in tz and "> t_max 42 °C" in tz
    assert "u 1 přístroje chybí rozsah teplot" in tz
    export_routine_test_docx(p, lib, sb, tmp_path / "p.docx")
    prot = _docx_text(tmp_path / "p.docx")
    assert "Oteplení" not in prot and "60890" not in prot and "F3 v řadě 1" not in prot   # #80: oteplení není v protokolu


def test_enclosure_panel_shows_critical_device():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from envocad.ui.dialogs import EnclosurePanel
    _app = QApplication.instance() or QApplication([])
    p, sb = _board(("F1", 2, {"t_max": "70"}), ("F3", 0, {"t_max": "42"}))
    panel = EnclosurePanel(sb, project=p)
    txt = panel.thermal.text()
    assert "Kritický přístroj: F3 v řadě 1:" in txt and "t_max 42 °C (atribut)" in txt
    assert "Hodnocení: NEVYHOVUJE (orientační – neověřeno proti normě) – F3" in txt
    assert "t_ambient_min" in panel._edits
    panel._edits["t_ambient_min"].setText("-30")
    panel._edits["t_ambient_min"].editingFinished.emit()
    assert sb.layout.params["t_ambient_min"] == "-30"
    _el(sb, "F3").attrs["t_max"] = "70"
    panel.refresh()                                     # bez t_min přístrojů platí předpoklad −5 °C > −30 °C
    assert "Hodnocení: NEVYHOVUJE (orientační – neověřeno proti normě) – F1: t_min −5 °C (předpoklad)" not in panel.thermal.text()
    assert "t_min −5 °C > nejnižší okolí −30 °C (předpoklad)" in panel.thermal.text()
    for ref in ("F1", "F3"):
        _el(sb, ref).attrs["t_min"] = "-40"
    panel.refresh()
    assert "Hodnocení: vyhovuje (orientační – neověřeno proti normě)" in panel.thermal.text()
    panel.deleteLater()


def test_unused_sheet_without_devices():
    s = Sheet(kind="switchboard")
    r = temperature_rise(s)
    assert r.devices == [] and r.critical() is None and r.critical_text() == ""
    assert r.verdict().startswith("vyhovuje (orientační – neověřeno proti normě) – bez přístrojů")
