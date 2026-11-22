"""Charakterizační testy `generator/dc_voltage.py` (soustava DC 1000 / 1500 V) – bez Qt, bez sítě.
Popisují současné chování: záložní větve (chyba čtení nastavení, chybějící artikly 1500 V, nečíselný počet DC
rozvaděčů) a pár případů veřejného API."""
import logging

import pytest

from envocad.generator import context, dc_voltage
from envocad.library.components import Component
from envocad.model.project import Project


def _c(cid, category, symbol="", **params):
    return Component(cid, "X", cid.upper(), cid, category, symbol, params={k: str(v) for k, v in params.items()})


class FakeLib:
    """Minimální knihovna artiklů (`component`, `components`) – jako ve `test_dc_system.py`."""

    def __init__(self, *comps):
        self.comps = {c.id: c for c in comps}

    def component(self, cid):
        return self.comps.get(cid)

    def components(self, symbol_id=None, category=None, search=""):
        return [c for c in self.comps.values() if category is None or c.category == category]


H1000 = _c("h1000", "fuse_holder", "fve.fuse_disconnect", un_v=1000, poles=2, in_max_a=25)
S1000 = _c("s1000", "spd", "fve.spd", uc_v=1000, spd_type="T1+T2 DC", note="DC | Ucpv 1100 V")
DC = {"fuse_component": "h1000", "spd_component": "s1000", "spd": "T1+T2", "tech_box": True}


# ---- standard_system_v: chyby čtení nastavení se spolknou -----------------------------------------------------------
@pytest.mark.parametrize("exc", [OSError("disk"), ValueError("špatný JSON"), KeyError("standard"), TypeError("x")])
def test_standard_system_v_swallows_settings_errors(monkeypatch, exc):
    """Řádky 24-25: výjimka při čtení nastavení → None (generátor pak použije 1000 V)."""
    def boom():
        raise exc
    monkeypatch.setattr("envocad.settings.load_settings", boom)
    assert dc_voltage.standard_system_v() is None


def test_standard_system_v_missing_standard_section(monkeypatch):
    """Nastavení bez sekce `standard` → KeyError → None."""
    monkeypatch.setattr("envocad.settings.load_settings", dict)
    assert dc_voltage.standard_system_v() is None


@pytest.mark.parametrize("raw, expected", [("1500", 1500.0), (1000, 1000.0), ("1500 V", 1500.0),
                                           ("1200", None), ("", None), (None, None)])
def test_standard_system_v_parses_standard(monkeypatch, raw, expected):
    monkeypatch.setattr("envocad.settings.load_settings", lambda: {"standard": {"dc_system_v": raw}})
    assert dc_voltage.standard_system_v() == expected


# ---- has_dc_boxes: počet rozvaděčů po trase a příznak technologie ------------------------------------------------------
@pytest.mark.parametrize("dc, expected", [
    ({"route_boxes": "abc"}, False),                    # řádky 69-70: nečíselný počet → 0 rozvaděčů
    ({"route_boxes": "abc", "tech_box": True}, True),   # … ale rozvaděč u technologie stačí
    ({"route_boxes": "2"}, True),
    ({"route_boxes": "1,5"}, True),                     # desetinná čárka → int(1.5) = 1
    ({"route_boxes": "0,9"}, False),                    # int(0.9) = 0
    ({"route_boxes": None}, False),
    ({}, False),
    ({"tech_box": "ne"}, False),
    ({"tech_box": "0"}, False),
    ({"tech_box": "ano"}, True),
    ({"tech_box": False, "route_boxes": 0}, False),
])
def test_has_dc_boxes(dc, expected):
    assert dc_voltage.has_dc_boxes(dc) is expected


# ---- inverters_allow_auto / un_label ----------------------------------------------------------------------------------
@pytest.mark.parametrize("values, expected", [([1100], True), ([1000], False), ([None, 0], False), ([], False),
                                              ([900, 1500], True), ([1000.0000000001], False)])
def test_inverters_allow_auto(values, expected):
    assert dc_voltage.inverters_allow_auto(values) is expected


def test_un_label_default_and_custom():
    assert dc_voltage.un_label({}) == "max. 1000 V DC"
    assert dc_voltage.un_label({"un_label": "  "}) == "max. 1000 V DC"
    assert dc_voltage.un_label({"un_label": " max. 1500 V DC "}) == "max. 1500 V DC"


# ---- resolve ---------------------------------------------------------------------------------------------------------
def test_resolve_without_dc_boxes_keeps_default(monkeypatch):
    """Bez DC rozvaděčů se artikly nemění, jen se doplní `system_v` a popis 1000 V."""
    spec = {"dc": {"tech_box": False, "route_boxes": 0, "fuse_component": "h1000"}}
    ch = dc_voltage.resolve(spec, Project(name="x"))
    assert ch.system_v == 1000
    assert spec["dc"] == {"tech_box": False, "route_boxes": 0, "fuse_component": "h1000",
                          "system_v": "1000", "un_label": "max. 1000 V DC"}


def test_resolve_requested_1500_without_catalog_records_missing(monkeypatch, caplog):
    """Řádky 53-54: zadaná 1500 V, katalog sadu 1500 V nemá → zůstane 1000 V, `meta["dc_system_missing"]`
    a varování v logu."""
    monkeypatch.setattr(dc_voltage.calc, "string_paths", lambda project: [])
    monkeypatch.setattr(context, "_lib", lambda: FakeLib(H1000, S1000))
    p = Project(name="x")
    spec = {"dc": {**DC, "system_v": "1500"}}
    with caplog.at_level(logging.WARNING, logger="envocad.generate"):
        ch = dc_voltage.resolve(spec, p)
    assert ch.system_v == 1000 and not ch.auto
    assert p.meta["dc_system_missing"] == "držák pojistky 1500 V DC 2p, svodič DC T1+T2 1500 V"
    assert spec["dc"]["system_v"] == "1000" and spec["dc"]["un_label"] == "max. 1000 V DC"
    assert any("Zadaná soustava DC 1500 V nepoužita" in r.getMessage() for r in caplog.records)


def test_resolve_requested_1500_with_catalog_overrides_components(monkeypatch):
    """Katalog má sadu 1500 V → artikly se přepíšou a nic se nezapíše do `meta`."""
    h1500 = _c("h1500", "fuse_holder", "fve.fuse_disconnect", un_v=1500, poles=2, in_max_a=30)
    s1500 = _c("s1500", "spd", "fve.spd", uc_v=1500, spd_type="T1+T2 DC")
    monkeypatch.setattr(dc_voltage.calc, "string_paths", lambda project: [])
    monkeypatch.setattr(context, "_lib", lambda: FakeLib(H1000, S1000, h1500, s1500))
    p = Project(name="x")
    spec = {"dc": {**DC, "system_v": 1500}}
    ch = dc_voltage.resolve(spec, p)
    assert ch.system_v == 1500
    assert spec["dc"]["fuse_component"] == "h1500" and spec["dc"]["spd_component"] == "s1500"
    assert spec["dc"]["system_v"] == "1500" and spec["dc"]["un_label"] == "max. 1500 V DC"
    assert "dc_system_missing" not in p.meta


def test_resolve_uses_standard_when_spec_has_no_system(monkeypatch):
    """Bez `dc.system_v` ve specifikaci rozhoduje firemní standard (`standard.dc_system_v`)."""
    monkeypatch.setattr("envocad.settings.load_settings", lambda: {"standard": {"dc_system_v": "1500"}})
    monkeypatch.setattr(dc_voltage.calc, "string_paths", lambda project: [])
    monkeypatch.setattr(context, "_lib", lambda: FakeLib(H1000, S1000))
    p = Project(name="x")
    dc_voltage.resolve({"dc": dict(DC)}, p)
    assert "dc_system_missing" in p.meta


# ---- assistant_devices / assistant_limit ------------------------------------------------------------------------------
def test_assistant_devices_with_fake_lib():
    """Průvodce: výchozí `DEFAULT_SPEC["dc"]` se sloučí s `dc`; přístroje podle artiklů z dodané knihovny."""
    lib = FakeLib(H1000, S1000)
    dc = {"fuse_component": "h1000", "spd_component": "s1000", "spd": "T1+T2", "tech_box": True}
    assert dc_voltage.assistant_devices(dc, lib) == [(1000.0, "H1000 1000 V"), (1100.0, "S1000 1100 V")]
    assert dc_voltage.assistant_limit(dc, lib) == (1000.0, "H1000 1000 V")


def test_assistant_devices_without_boxes_is_empty():
    dc = {"tech_box": False, "route_boxes": 0}
    assert dc_voltage.assistant_devices(dc, FakeLib(H1000)) == []
    assert dc_voltage.assistant_limit(dc, FakeLib(H1000)) == (None, "")
