"""F7: úplnost podkladů pro distributora (issue #132) – kontroly běží jen při vyplněném `fve.grid.dso`, hlídají
jen přítomnost údajů (žádné prahy). Malý projekt z generátoru; údaje, které generátor nevyplňuje (výrobce a typ
střídače, připojovací kabel), doplní test, pak se vždy jeden smaže a hledá se nález."""
import json

import pytest
from chain_data import build_project

from envocad.library.store import LibraryStore
from envocad.model.checks import INFO, WARNING, check_project
from envocad.model.project import INVERTER_SYMBOLS, Element

INV = {"p_ac": 10, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
CODES = ("dso_inverter_data", "dso_battery_data", "dso_main_breaker", "dso_instrument_transformers", "dso_feed_cable")


def _spec(dso="ČEZ Distribuce", **extra):
    return {"building": "house", "inverters": [{"ref": "T1", **INV, "strings": [12, 12]}],
            "battery": {"e_kwh": 10, "p_kw": 5}, "grid": {"dso": dso},
            "chain": {"rd": {"main_in": 63}, "re": {"main_in": 63, "metering": "indirect", "builtin": True},
                      "hds": {"in_": 80}}, **extra}


def _complete(p):
    """Doplní údaje, které generátor nevyplňuje (výrobce, typ střídače; připojovací kabel)."""
    for s in p.sheets:
        for e in s.elements:
            if e.symbol_id in INVERTER_SYMBOLS:
                e.attrs.update({"manufacturer": "Výrobce", "type": "Typ"})
        for w in s.wires:
            if any(s.element(x.element_id).symbol_id == "fve.grid" for x in (w.a, w.b)):
                w.attrs.update({"cable": "CYKY-J 5x16", "cross": "16", "length": "20"})
    return p


def _codes(p, severity=None):
    return [f.code for f in check_project(p, LibraryStore(), standard_paper="A4")
            if f.code in CODES and (severity is None or f.severity == severity)]


def _find(p, symbols):
    return next((s, e) for s in p.sheets for e in s.elements if e.symbol_id in symbols)


@pytest.fixture
def proj():
    return _complete(build_project(_spec()))


def test_complete_project_no_dso_findings(proj):
    assert _codes(proj) == []


def test_no_distributor_no_findings():
    p = build_project(_spec(dso=""))                  # chybí výrobce, typ, kabel – ale distributor není zadán
    assert _codes(p) == []
    grid = _find(p, {"fve.grid"})[1]
    grid.attrs["dso"] = "  "
    assert _codes(p) == []


@pytest.mark.parametrize("key", ["manufacturer", "type", "p_ac", "phases"])
def test_inverter_missing_attr(proj, key):
    inv = _find(proj, INVERTER_SYMBOLS)[1]
    inv.attrs[key] = ""
    fs = [f for f in check_project(proj, LibraryStore(), standard_paper="A4") if f.code == "dso_inverter_data"]
    assert [(f.severity, f.target_id) for f in fs] == [(WARNING, inv.id)]
    assert fs[0].ref == inv.ref


def test_inverter_attr_deleted(proj):
    del _find(proj, INVERTER_SYMBOLS)[1].attrs["phases"]
    assert _codes(proj, WARNING) == ["dso_inverter_data"]


@pytest.mark.parametrize("key", ["e_kwh", "p_kw"])
def test_battery_missing_attr(proj, key):
    bat = _find(proj, {"fve.battery"})[1]
    bat.attrs.pop(key)
    assert _codes(proj, WARNING) == ["dso_battery_data"]


@pytest.mark.parametrize("key", ["in_", "poles"])
def test_main_breaker_missing_attr(proj, key):
    q = next(e for s in proj.sheets for e in s.elements if e.attrs.get("chain") == "meter_main")
    q.attrs[key] = ""
    assert _codes(proj, WARNING) == ["dso_main_breaker"]


def test_main_switch_missing_poles(proj):
    s = next(s for s in proj.sheets if s.is_switchboard)
    sw = Element("sb.main_switch", 0, 0, attrs={"ref": "QM", "in_": "40", "poles": ""})
    s.elements.append(sw)
    assert _codes(proj, WARNING) == ["dso_main_breaker"]
    sw.attrs["poles"] = "3"
    assert _codes(proj) == []


@pytest.mark.parametrize("sym", ["fve.ct", "fve.vt"])
@pytest.mark.parametrize("key", ["ratio", "cls", "burden"])
def test_billing_transformer_missing_attr(proj, sym, key):
    re_sheet = next(s for s in proj.sheets if s.is_switchboard and s.loc == "RE")
    t = next((e for e in re_sheet.elements if e.symbol_id == sym), None)
    if t is None:                                      # generátor kreslí v RE jen MTP; MTN doplní test
        t = Element("fve.vt", 0, 0, attrs={"ref": "TV1", "ratio": "400/100 V", "cls": "0,5", "burden": "10"})
        re_sheet.elements.append(t)
    assert _codes(proj) == []
    t.attrs[key] = ""
    fs = [f for f in check_project(proj, LibraryStore(), standard_paper="A4") if f.code in CODES]
    assert [(f.code, f.severity, f.target_id, f.sheet_id) for f in fs] == [
        ("dso_instrument_transformers", WARNING, t.id, re_sheet.id)]


def test_transformer_elsewhere_not_checked(proj):
    """MTP / MTN mimo elektroměrový a hlavní rozvaděč (ochrany) se nekontrolují – ani na bloku, ani v jiném rozvaděči."""
    other = next(s for s in proj.sheets if not s.is_switchboard)
    other.elements.append(Element("fve.ct", 0, 0, attrs={"ref": "TA9"}))
    other.elements.append(Element("fve.vt", 0, 0, attrs={"ref": "TV9"}))
    blk = Element("fve.switchboard", 0, 0, attrs={"ref": "RFVE", "desc": "rozvaděč FVE"})
    other.elements.append(blk)
    sheet = proj.create_switchboard_sheet(blk)
    sheet.elements.append(Element("fve.ct", 0, 0, attrs={"ref": "TA8"}))
    assert _codes(proj) == []


@pytest.mark.parametrize("key", ["cable", "cross", "length"])
def test_feed_cable_missing_is_info(proj, key):
    _s, w = next((s, w) for s in proj.sheets for w in s.wires
                if any(s.element(x.element_id).symbol_id == "fve.grid" for x in (w.a, w.b)))
    del w.attrs[key]
    assert _codes(proj, INFO) == ["dso_feed_cable"]
    assert _codes(proj, WARNING) == []


def test_no_thresholds(proj):
    """Jen přítomnost: nulový / malý výkon a velký jistič nejsou nález."""
    inv = _find(proj, INVERTER_SYMBOLS)[1]
    inv.attrs["p_ac"] = "0,5"
    assert _codes(proj) == []


def test_vt_symbol_declares_attributes():
    from pathlib import Path

    import envocad
    f = Path(envocad.__file__).parent / "library" / "builtin" / "fve" / "fve.vt.json"
    keys = [a["key"] for a in json.loads(f.read_text(encoding="utf-8"))["attributes"]]
    assert {"ref", "ratio", "cls", "burden"} <= set(keys)
