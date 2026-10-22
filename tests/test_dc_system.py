"""Soustava DC 1000 / 1500 V: Un DC přístrojů ve stringové cestě (asistent, F7) a volba artiklů 1500 V generátorem
(model/dc_system.py, generator/dc_voltage.py) – bez Qt. Artikly 1500 V jen jako fixture (data doplní data-entry)."""
import logging

import pytest

from envocad.library.components import Component
from envocad.model import calc, dc_system
from envocad.model.checks import INFO, check_project

_INV25 = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
MOD = calc.ModuleData(voc=49.5, vmp=41.5, isc=13.9, beta_voc=-0.27)
INV = calc.InverterData(u_dc_max=1100, u_mppt_min=200, u_mppt_max=1000, i_mppt_max=30)

def _c(cid, category, symbol="", **params):
    return Component(cid, "X", cid.upper(), cid, category, symbol, params={k: str(v) for k, v in params.items()})


class FakeLib:
    def __init__(self, *comps):
        self.comps = {c.id: c for c in comps}

    def component(self, cid):
        return self.comps.get(cid)

    def components(self, symbol_id=None, category=None, search=""):
        return [c for c in self.comps.values() if category is None or c.category == category]


H1000 = _c("h1000", "fuse_holder", "fve.fuse_disconnect", un_v=1000, poles=2, in_max_a=25)
S1000 = _c("s1000", "spd", "fve.spd", uc_v=1000, spd_type="T1+T2 DC", note="DC | Ucpv 1100 V")
H1500 = _c("h1500", "fuse_holder", "fve.fuse_disconnect", un_v=1500, poles=2, in_max_a=30)
S1500 = _c("s1500", "spd", "fve.spd", uc_v=1500, spd_type="T1+T2 DC")
DC = {"fuse_component": "h1000", "spd_component": "s1000", "spd": "T1+T2"}


# ---- model/dc_system -----------------------------------------------------------------------------------------------
def test_component_un():
    assert dc_system.component_un(H1000) == 1000
    assert dc_system.component_un(S1000) == 1100           # svodič: Ucpv z poznámky, ne Uc
    assert dc_system.component_un(S1500) == 1500           # bez Ucpv → Uc
    assert dc_system.component_un(_c("x", "spd", ucpv_v=1200, uc_v=1000)) == 1200
    assert dc_system.component_un(None) is None


def test_device_limit_takes_lowest_and_matching_spd_type():
    lib = FakeLib(H1000, S1000)
    assert dc_system.device_limit(lib, DC) == (1000, "H1000 1000 V")
    assert dc_system.device_limit(lib, {**DC, "fuse_component": ""}) == (1100, "S1000 1100 V")
    assert dc_system.device_limit(lib, {**DC, "fuse_component": "", "spd": "T2"}) == (None, "")   # typ nesedí


def test_choose_auto_1500_and_missing():
    lib = FakeLib(H1000, S1000, H1500, S1500)
    ch = dc_system.choose(lib, DC, 990.0)                  # pod 1000 V – beze změny
    assert (ch.system_v, ch.overrides, ch.limit) == (1000, {}, 1000)
    ch = dc_system.choose(lib, DC, 1083.6)                 # nad → automaticky 1500 V
    assert ch.system_v == 1500 and ch.auto and ch.overrides == {"fuse_component": "h1500", "spd_component": "s1500"}
    assert ch.limit == 1500 and ch.label == "max. 1500 V DC"
    ch = dc_system.choose(lib, DC, 900.0, 1500)            # zadaná 1500 V i pro krátký string
    assert ch.system_v == 1500 and not ch.auto
    ch = dc_system.choose(FakeLib(H1000, S1000, S1500), DC, 1083.6)   # držák 1500 V chybí
    assert ch.system_v == 1000 and ch.limit == 1000 and ch.missing == ["držák pojistky 1500 V DC 2p"]
    assert dc_system.choose(FakeLib(H1000, S1000, S1500), DC, 900.0).missing == []
    h1p = _c("h1500-1p", "fuse_holder", "fve.fuse_disconnect", un_v=1500, poles=1, in_max_a=63)
    hsym = _c("h1500-fuse", "fuse_holder", "fve.fuse", un_v=1500, poles=2)
    # 1pólový držák (generátor kreslí 2pólový odpojovač na string) ani jiná značka 2p odpojovač nenahradí
    assert dc_system.choose(FakeLib(H1000, S1000, S1500, h1p, hsym), DC, 1083.6).missing == ["držák pojistky 1500 V DC 2p"]
    assert dc_system.catalog_missing(FakeLib(H1000, S1500, h1p)) == ["pojistkový odpojovač 1500 V DC 2p"]
    assert dc_system.catalog_missing(FakeLib(H1500, S1500)) == []


# ---- calc: asistent / kontrola stringu ---------------------------------------------------------------------------
def test_string_limits_capped_by_dc_devices():
    free = calc.string_limits(MOD, INV, -20)
    assert free.n_max == 19                                # Umax střídače 1100 V: 19 × 55,5 V = 1055 V
    lim = calc.string_limits(MOD, INV, -20, u_dc_devices=1000, u_dc_label="EFH 10 DC 2p 1000 V")
    assert lim.n_max == 18
    assert any("nejvýš 18 modulů" in r and "Un DC přístrojů 1000 V (EFH 10 DC 2p 1000 V)" in r for r in lim.reasons)
    assert calc.string_limits(MOD, INV, -20, u_dc_devices=1500).n_max == 19     # 1500 V přístroje: mez střídač


def test_string_issues_dc_devices():
    msgs = calc.string_issues(MOD, INV, 19, t_min=-20, u_dc_devices=1000, u_dc_label="EFH 1000 V")
    assert "Uoc 1054,8 V při -20 °C > Un DC přístrojů 1000 V (EFH 1000 V)" in msgs
    assert not calc.is_warning(msgs[-1])
    assert not calc.string_issues(MOD, INV, 18, t_min=-20, u_dc_devices=1000)
    assert not calc.string_issues(MOD, INV, 19, t_min=-20)   # bez meze přístrojů jako dřív


# ---- generátor -----------------------------------------------------------------------------------------------------
FIX_H = _c("fix-holder-1500", "fuse_holder", "fve.fuse_disconnect", un_v=1500, poles=2, in_max_a=30, note="DC")
FIX_S = _c("fix-spd-1500", "spd", "fve.spd", uc_v=1500, spd_type="T1+T2 DC", note="DC | Ucpv 1500 V")


class CatalogView:
    """Vestavěná knihovna bez artiklů DC ≥ 1500 V (nezávisle na stavu katalogu) + volitelně fixture 1500 V."""

    def __init__(self, extra=()):
        from envocad.library.store import LibraryStore
        self.lib = LibraryStore()
        self.extra = {c.id: c for c in extra}

    def _hidden(self, c) -> bool:
        return c is not None and c.id not in self.extra and c.category in ("fuse_holder", "spd") \
            and (dc_system.component_un(c) or 0) >= 1500

    def component(self, cid):
        c = self.extra.get(cid) or self.lib.component(cid)
        return None if self._hidden(c) else c

    def components(self, symbol_id=None, category=None, search=""):
        out = [c for c in self.lib.components(symbol_id, category, search) if not self._hidden(c)]
        return out + [c for c in self.extra.values() if category in (None, c.category)]

    def __getattr__(self, name):
        return getattr(self.lib, name)


@pytest.fixture
def catalog(monkeypatch):
    """catalog(with_1500) → knihovna generátoru i kontroly (`context._lib`)."""
    from envocad.generator import context

    def make(with_1500: bool):
        view = CatalogView((FIX_H, FIX_S) if with_1500 else ())
        monkeypatch.setattr(context, "_lib", lambda: view)
        return view
    return make


def _boards(p):
    return {s.loc: s for s in p.sheets if s.is_switchboard}


def test_generator_switches_to_1500_with_catalog(catalog):
    from chain_data import build_project
    lib = catalog(True)
    p = build_project({"inverters": [{"ref": "T1", **_INV25, "strings": [20, 20]}], "site": {"t_min": -20}})
    sb = _boards(p)["RFVE.DC"]
    holders = [e for e in sb.elements if e.symbol_id == "fve.fuse_disconnect"]
    spds = [e for e in sb.elements if e.symbol_id == "fve.spd"]
    assert {e.component_id for e in holders} == {"fix-holder-1500"} and {e.attrs["un"] for e in holders} == {"1500"}
    assert {e.component_id for e in spds} == {"fix-spd-1500"}
    assert sb.layout.params["un"] == "max. 1500 V DC" and _boards(p)["RDC1"].layout.params["un"] == "max. 1500 V DC"
    assert not [f for f in check_project(p, lib) if f.code in ("un_dc", "spd_ucpv", "dc_1500_missing")]


def test_generator_keeps_1000_for_short_strings_and_forced_1500(catalog):
    from chain_data import build_project
    catalog(True)
    spec = {"inverters": [{"ref": "T1", **_INV25, "strings": [18, 18]}], "site": {"t_min": -20}}
    sb = _boards(build_project(spec))["RFVE.DC"]
    assert {e.component_id for e in sb.elements if e.symbol_id == "fve.fuse_disconnect"} == {"eti-efh-10-dc-2p"}
    assert sb.layout.params["un"] == "max. 1000 V DC"
    sb = _boards(build_project({**spec, "dc": {"system_v": 1500}}))["RFVE.DC"]
    assert {e.component_id for e in sb.elements if e.symbol_id == "fve.fuse_disconnect"} == {"fix-holder-1500"}


def test_generator_house_label_1500(catalog):
    from chain_data import build_project
    catalog(True)
    p = build_project({"building": "house", "dc": {"system_v": "1500"},
                       "inverters": [{"ref": "T1", "p_ac": 10, "u_dc_max": 1000, "u_mppt_min": 160,
                                      "u_mppt_max": 950, "i_mppt_max": 16, "strings": [12]}]})
    assert _boards(p)["RFVE"].layout.params["un"] == "230/400 V AC / max. 1500 V DC"


def test_generator_without_1500_catalog_logs_and_f7_info(catalog, caplog):
    """Bez artiklů 1500 V zůstane 1000 V: string ze specifikace se nemění, generátor zaloguje varování a F7 hlásí
    `un_dc` a `dc_1500_missing`."""
    from chain_data import build_project
    lib = catalog(False)
    with caplog.at_level(logging.WARNING, logger="envocad.generate"):
        p = build_project({"inverters": [{"ref": "T1", **_INV25, "strings": [20]}], "site": {"t_min": -20}})
    assert any("Un DC přístrojů EFH 10 DC 2p 1000 V" in r.getMessage() and "chybí v katalogu" in r.getMessage()
               for r in caplog.records)
    assert _boards(p)["RFVE.DC"].layout.params["un"] == "max. 1000 V DC"
    fs = check_project(p, lib)
    assert {f.code for f in fs} >= {"un_dc", "dc_1500_missing"}
    assert [f.severity for f in fs if f.code == "dc_1500_missing"] == [INFO]


def test_assistant_limit(catalog):
    from envocad.generator.dc_voltage import assistant_limit, has_dc_boxes
    catalog(False)
    assert not has_dc_boxes({"tech_box": False, "route_boxes": 0})
    assert assistant_limit({"tech_box": False, "route_boxes": 0}) == (None, "")
    u, label = assistant_limit({})
    assert u == 1000 and "EFH 10 DC 2p" in label     # výchozí: držák ETI EFH 10 DC 1000 V (svodič Ucpv 1100 V)
    catalog(True)
    assert assistant_limit({})[0] == 1500            # s artikly 1500 V počítá asistent jako generátor (automatika)


def test_builtin_catalog_1500_choice_if_present():
    """Skutečný katalog (data-entry): když má sadu 1500 V, volba vezme držák a svodič ≥ 1500 V se stejným typem."""
    from envocad.generator.spec import DEFAULT_SPEC
    from envocad.library.store import LibraryStore
    lib = LibraryStore()
    if dc_system.catalog_missing(lib):
        pytest.skip("katalog zatím artikly 1500 V nemá")
    ch = dc_system.choose(lib, DEFAULT_SPEC["dc"], 1110.0)
    if ch.missing:
        pytest.skip(f"chybí {ch.missing}")
    assert ch.system_v == 1500 and all(dc_system.component_un(lib.component(c)) >= 1500 for c in ch.overrides.values())
