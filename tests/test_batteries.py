"""Baterie z katalogu (`batteries.csv`): validace, výběr, věž (master/slave/BMS), generátor, výkaz a EPS (bez Qt)."""
from __future__ import annotations

import csv

import pytest

from envocad.generate import build_project
from envocad.library import batteries, components
from envocad.library.store import BUILTIN_DIR, LibraryStore
from envocad.model.checks import ERROR, WARNING, check_project

CSV = BUILTIN_DIR / "components" / "batteries.csv"
RD_INV = {"p_ac": 10, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


@pytest.fixture
def lib():
    return LibraryStore()


def _rows():
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def _write(path, rows):
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    return path


def test_builtin_csv_validates_and_is_battery_only(lib):
    assert components.validate(CSV, {s[0] for s in lib.list_symbols()}) == []
    comps = components.read_csv(CSV)
    assert comps and all(c.category == "battery" and c.symbol_id == "fve.battery" and c.source == "datasheet"
                         or c.id == "huawei-luna2000-241-2s1" for c in comps)
    assert all(c.params.get("bat_role") in components.BAT_ROLES for c in comps)
    # Huawei úložiště se přestěhovalo z inverters.csv, id zůstalo
    assert lib.component("huawei-luna2000-241-2s1").category == "battery"
    assert "huawei-luna2000-241-2s1" not in (CSV.parent / "inverters.csv").read_text(encoding="utf-8-sig")
    # každý odkaz bat_link míří na existující artikl správné role
    by_id = {c.id: c for c in comps}
    for c in comps:
        for cid in batteries.link_ids(c):
            assert by_id[cid].params["bat_role"] in ("slave", "bms"), (c.id, cid)


def test_validator_battery_rules(tmp_path):
    base = {"id": "t-bat", "manufacturer": "T", "part_number": "B1", "name": "B", "category": "battery",
            "symbol_id": "fve.battery", "datasheet_url": "https://example.com", "source": "datasheet",
            "e_kwh": "5", "bat_role": "module"}
    assert components.validate(_write(tmp_path / "ok.csv", [base])) == []
    for patch, word in (({"bat_role": "veza"}, "bat_role"), ({"n_mod_min": "5", "n_mod_max": "2"}, "n_mod_min"),
                        ({"e_kwh": ""}, "e_kwh"), ({"bat_link": "nezname-id"}, "neznámé id"),
                        ({"bat_role": "slave", "bat_link": "t-bat"}, "bat_link"), ({"n_mod_max": "x"}, "n_mod_max")):
        errs = components.validate(_write(tmp_path / "bad.csv", [{**base, **patch}]))
        assert errs and any(word in e for e in errs), (patch, errs)


def test_datasheet_values_spot_check(lib):
    """Hodnoty doslova z datasheetů (kontrola přepisu): kapacita, rozměry, hmotnost, napětí."""
    v3 = lib.component("solax-t-bat-h-5.8-v3")
    assert (v3.num("e_kwh"), v3.num("u_dc_v"), v3.num("weight_kg"), v3.num("width_mm"), v3.num("height_mm"),
            v3.num("depth_mm")) == (5.8, 115.2, 61.5, 474, 715, 150)
    v2s = lib.component("solax-hv11550-v2")
    assert (v2s.num("weight_kg"), v2s.num("height_mm"), v2s.num("depth_mm")) == (68.5, 647, 193)
    assert lib.component("solax-tp-hs36").num("e_kwh") == 3.6
    assert lib.component("sigenergy-sigenstor-bat-5.0").num("e_kwh") == 5.38
    assert lib.component("sigenergy-sigenstack-bat-12.0").num("e_kwh") == 12.06
    assert lib.component("growatt-ark-2.5h-a2").num("u_dc_v") == 51.2


def test_choices_only_compatible(lib):
    bats = lib.components(category="battery")
    ch = batteries.choices(bats, lib.component("solax-x3-hyb-10.0-p"))
    assert ch and all(c.manufacturer == "SolaX" for c in ch)
    assert "solax-t-bat-h-5.8-v2" not in {c.id for c in ch}          # V2 jen k X1/X3-Hybrid (inv_compat)
    assert "solax-t-bat-h-5.8-v2" in {c.id for c in batteries.choices(bats, lib.component("solax-x3-hybrid-10.0-d"))}
    assert {c.id for c in batteries.choices(bats, lib.component("growatt-min5000tl-xh"))} >= {"growatt-apx-5.0p-b1"}
    assert "growatt-apx-5.0p-b1" not in {c.id for c in batteries.choices(bats, lib.component("growatt-sph5000"))}
    luna = lib.component("huawei-luna2000-5-e0")
    assert batteries.compatible(luna, lib.component("huawei-sun2000-3ktl-l1"))
    assert not batteries.compatible(luna, lib.component("huawei-sun2000-12k-mb0"))
    assert not batteries.compatible(lib.component("huawei-luna2000-241-2s1"), lib.component("huawei-sun2000-12k-mb0"))
    assert batteries.compat_patterns(luna)[0] == "SUN2000-*KTL-L1"


def test_choices_same_manufacturer_first_and_only_bases(lib):
    inv = lib.component("solax-x3-hyb-10.0-p")
    ch = batteries.choices(lib.components(category="battery"), inv, only_compatible=False)
    assert ch and ch[0].manufacturer == "SolaX"
    roles = {c.params["bat_role"] for c in ch}
    assert roles <= set(batteries.BASE_ROLES) and "slave" not in roles and "bms" not in roles
    first_other = next(i for i, c in enumerate(ch) if c.manufacturer != "SolaX")
    assert all(c.manufacturer == "SolaX" for c in ch[:first_other])
    assert not [c for c in ch[first_other:] if c.manufacturer == "SolaX"]
    gw = batteries.choices(lib.components(category="battery"), lib.component("growatt-sph5000"), only_compatible=False)
    assert gw[0].manufacturer == "Growatt"


def test_tower_totals_and_range(lib):
    v3 = lib.component("solax-t-bat-h-5.8-v3")
    slave, bms = batteries.parts(lib, v3)
    assert slave.id == "solax-hv11550-a-v3" and bms == []
    assert batteries.module_range(v3) == (1, 6)
    tot = batteries.totals(v3, 3, slave)
    assert tot["e_kwh"] == pytest.approx(17.4) and tot["p_kw"] == pytest.approx(8.7)
    hs = lib.component("solax-tp-hs36")
    _s, bms = batteries.parts(lib, hs)
    assert [b.id for b in bms] == ["solax-tbms-mcs0800"] and batteries.module_range(hs) == (2, 13)
    t = batteries.totals(hs, 10, None)
    assert t["e_kwh"] == pytest.approx(36.0) and t["p_kw"] is None      # výkon na modul datasheet neuvádí
    assert len(batteries.parts(lib, lib.component("sigenergy-sigenstack-bat-12.0"))[1]) == 5
    assert batteries.module_range(lib.component("huawei-luna2000-241-2s1")) == (1, 1)


def test_apply_battery_component(lib):
    b = batteries.apply_battery_component(lib, {"component_id": "solax-t-bat-h-5.8-v3", "modules": 3})
    assert (b["type"], b["manufacturer"], b["e_kwh"], b["p_kw"], b["n_modules"], b["slave_type"]) == (
        "T-BAT H 5.8 V3", "SolaX", "17.4", "8.7", "3", "HV11550-A V3")
    one = batteries.apply_battery_component(lib, {"component_id": "solax-t-bat-h-5.8-v3", "modules": 1})
    assert one["e_kwh"] == "5.8" and "slave_type" not in one
    hs = batteries.apply_battery_component(lib, {"component_id": "solax-tp-hs36", "modules": 4,
                                                 "bms_id": "solax-tbms-mcs0800"})
    assert hs["e_kwh"] == "14.4" and hs["bms"] == "TBMS-MCS0800" and "p_kw" not in hs
    # zadané hodnoty specifikace mají přednost
    given = batteries.apply_battery_component(lib, {"component_id": "solax-tp-hs36", "modules": 2, "e_kwh": 7,
                                                    "type": "vlastní"})
    assert given["e_kwh"] == 7 and given["type"] == "vlastní"
    # neznámý artikl / jiná kategorie: beze změny
    assert batteries.apply_battery_component(lib, {"component_id": "neni", "e_kwh": 5}) == {"component_id": "neni", "e_kwh": 5}
    assert "n_modules" not in batteries.apply_battery_component(lib, {"component_id": "solax-x3-hyb-10.0-p", "modules": 2})
    with pytest.raises(ValueError, match="mimo rozsah 1–6"):
        batteries.apply_battery_component(lib, {"component_id": "solax-t-bat-h-5.8-v3", "modules": 7})
    with pytest.raises(ValueError, match="není celé číslo"):
        batteries.apply_battery_component(lib, {"component_id": "solax-t-bat-h-5.8-v3", "modules": "x"})


def _house(battery):
    spec = {"building": "house", "chain": {"rfve": {"builtin": True}},
            "inverters": [{"ref": "T1", **RD_INV, "component_id": "solax-x3-hyb-10.0-p", "strings": [16, 16]}]}
    if battery is not None:
        spec["battery"] = battery
    return build_project(spec)


def test_generator_battery_from_catalog_block_scheme_bom_and_eps(lib):
    p = _house({"component_id": "solax-t-bat-h-5.8-v3", "modules": 3})
    s = p.sheets[0]
    bat = next(e for e in s.elements if e.symbol_id == "fve.battery")
    assert bat.component_id == "solax-t-bat-h-5.8-v3"
    assert bat.attrs["type"] == "T-BAT H 5.8 V3" and bat.attrs["e_kwh"] == "17.4" and bat.attrs["p_kw"] == "8.7"
    assert bat.attrs["n_modules"] == "3" and bat.attrs["manufacturer"] == "SolaX"
    assert any(e.symbol_id == "fve.inverter_hybrid" for e in s.elements)
    # baterie je připojená ke střídači (blokové schéma) a EPS se kreslí
    inv = next(e for e in s.elements if e.symbol_id == "fve.inverter_hybrid")
    assert any(w.touches(inv.id) and w.touches(bat.id) for w in s.wires)
    sb = next(x for x in p.sheets if x.loc == "RFVE")
    assert any(e.symbol_id == "fve.changeover_switch" for e in sb.elements)
    bad = [(f.code, f.ref, f.text) for f in check_project(p, lib, standard_paper="A4")
           if f.severity in (ERROR, WARNING)]
    assert bad == []
    # výkaz: master ×1 + slave ×2, jedna položka baterie
    from envocad.export.reports import bom
    rows = {(r[2], r[3]): r[5] for r in bom(p, lib)[1] if r[1] == "Bateriové úložiště"}
    assert rows == {("T-BAT H 5.8 V3", "SolaX"): 1, ("HV11550-A V3", "SolaX"): 2}


def test_generator_battery_bms_in_bom(lib):
    p = _house({"component_id": "solax-tp-hs36", "modules": 4, "bms_id": "solax-tbms-mcs0800"})
    from envocad.export.reports import bom
    rows = [(r[1], r[2], r[5]) for r in bom(p, lib)[1] if r[1] in ("Bateriové úložiště", "Řídicí jednotka baterie")]
    assert sorted(rows) == [("Bateriové úložiště", "TP-HS36", 4), ("Řídicí jednotka baterie", "TBMS-MCS0800", 1)]
    bat = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.battery")
    assert bat.attrs["e_kwh"] == "14.4" and bat.attrs["bms"] == "TBMS-MCS0800"


def test_generator_without_battery_and_manual_spec_unchanged(lib):
    p = _house(None)
    s = p.sheets[0]
    assert not [e for e in s.elements if e.symbol_id == "fve.battery"]
    assert not [e for e in s.elements if e.symbol_id == "fve.inverter_hybrid"]
    # ruční specifikace bez artiklu (původní chování)
    p = _house({"e_kwh": 10, "p_kw": 5, "type": "BYD"})
    bat = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.battery")
    assert bat.component_id is None and bat.attrs["e_kwh"] == "10" and "n_modules" not in bat.attrs


def test_generator_battery_out_of_range_is_valueerror():
    with pytest.raises(ValueError, match="mimo rozsah"):
        _house({"component_id": "solax-t-bat-h-5.8-v3", "modules": 9})
