"""Rozsah generátoru (docs/NAVRH_TOPOLOGIE.md, kap. 8 bod 12): blokové schéma a DC rozvaděče; AC rozvaděče z mustrů.
Stávající RD / HR / RE (a HDS) jen jako bloky bez listů, RFVE.AC bez mustru blok bez listu, RFVE rodinného domu list
s DC částí a kotvami AC části; vestavěný kód AC listů jako volba `chain.<role>.builtin` / standard `ac_builtin`.
Dále nálezy review F2: párování stringů přes RFVE (B2), jištění a kabely (D1–D3, B3), EPS (D4, D6, D7), síťová ochrana
(D5), formát listů blokového schématu (B1)."""
from __future__ import annotations

import functools
import json
from pathlib import Path

import pytest

from envocad.generate import build_project
from envocad.model.checks import ERROR, INFO, WARNING, check_project
from envocad.model.project import Element, Project, Wire, WireEnd, element_symbol, is_block_only

INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
RD_INV = {"p_ac": 10, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
BAT = {"e_kwh": 10, "p_kw": 5, "type": "BYD"}
MACROS = Path(__file__).resolve().parent.parent / "envocad" / "library" / "builtin" / "macros"


@functools.cache
def _lib():
    from envocad.library.store import LibraryStore
    return LibraryStore()


def _bad(p) -> list:
    return [(f.code, f.ref, f.text) for f in check_project(p, _lib()) if f.severity in (ERROR, WARNING)]


def _codes(p) -> dict[str, list]:
    out: dict[str, list] = {}
    for f in check_project(p, _lib()):
        out.setdefault(f.code, []).append(f)
    return out


def _blocks(p) -> dict:
    return {e.ref: e for s in p.sheets if not s.is_switchboard for e in s.elements if e.symbol_id == "fve.switchboard"}


def _sheet_refs(p) -> set[str]:
    return {s.loc for s in p.sheets if s.is_switchboard}


def _ports(p, e) -> tuple[list[str], list[str]]:
    sym = element_symbol(p, e, _lib())
    return [pt.name for pt in sym.ports if pt.dir == "W"], [pt.name for pt in sym.ports if pt.dir == "E"]


# ---- výchozí rozsah: bloky bez listů ------------------------------------------------------------------------------
def test_company_default_blocks_without_sheets():
    """Firma na nn: listy jen DC rozvaděčů; RFVE.AC, HR a RE jsou bloky bez listu s porty z atributů a údaji
    řetězce v popisku; HDS bez In bez chyby; F7 bez chyb a varování."""
    p = build_project({"inverters": [{"ref": f"T{i}", **INV, "strings": [20, 20]} for i in (1, 2)]})
    assert _sheet_refs(p) == {"RDC1", "RDC2", "RFVE.DC"}
    b = _blocks(p)
    for ref in ("RFVE.AC", "HR", "RE"):
        assert is_block_only(p, b[ref]), ref
    assert _ports(p, b["RFVE.AC"]) == (["X1", "X2"], ["XOUT", "XPE"])
    assert _ports(p, b["HR"]) == (["XIN"], ["X1", "X2"]) and _ports(p, b["RE"]) == (["XIN"], ["XOUT"])
    ac = b["RFVE.AC"].attrs
    # 2 × 25 kW: jistič střídače 1,25 × 36 A → 50 A; vývod FVE max(72 A, 50 A) → 80 A; hlavní vypínač ≥ 125 A
    assert ac["inv_protect"] == "2× 50 A" and ac["main"] == "hlavní vypínač 125 A" and ac["protect"] == "X1=50, X2=50"
    hr = b["HR"].attrs
    assert hr["main"] == "hlavní jistič" and hr["fve_out"] == "jistič 80 A" and hr["protect"] == "X1=80"
    assert b["RE"].attrs["metering"] == "přímé" and b["RE"].attrs["main"] == "hlavní jistič před elektroměrem"
    hds = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.hds")
    assert hds.attrs["in_"] == "" and "in_unresolved" not in hds.attrs
    assert _bad(p) == []
    codes = _codes(p)
    assert {f.severity for f in codes["block_only"]} == {INFO} and {f.severity for f in codes["hds_no_in"]} == {INFO}
    # popisek bloku ukazuje údaje (blokové schéma)
    lines = element_symbol(p, b["HR"], _lib()).label_lines(b["HR"].attrs)
    assert "vývod FVE: jistič 80 A" in lines


def test_company_chain_data_in_block_attrs():
    """Zadané údaje chain.* se propíší do atributů bloků: hlavní přístroj s In, pojistkový odpínač nad 80 A, nepřímé
    měření s MTP, hranice vlastnictví zůstává textem v blokovém schématu."""
    p = build_project({"inverters": [{"ref": f"T{i}", **INV, "strings": [20]} for i in (1, 2, 3, 4)],
                       "chain": {"hr": {"main_in": 400, "fve_device": "fuse_disconnect", "fve_in": 160},
                                 "re": {"main_in": 400, "metering": "indirect", "boundary": "re_meter"},
                                 "hds": {"in_": 500}}})
    b = _blocks(p)
    assert b["HR"].attrs["main"] == "hlavní jistič 400 A" and b["HR"].attrs["fve_out"] == "pojistkový odpínač 160 A"
    assert b["RE"].attrs["metering"] == "nepřímé, MTP 400/5 A"
    assert any(t.text == "hranice vlastnictví DS / odběratel" for s in p.sheets for t in s.texts)
    assert _bad(p) == []


def test_house_default_rfve_sheet_dc_part_and_anchors():
    """RD: list RFVE vždy s DC částí; AC část bez mustru jen přívody / vývody (kotvy) bez přístrojů – blok má porty;
    RD a RE bloky bez listů; EPS (hybrid s baterií) jen kotvy XE1 / XB1, F7 bez chyb a varování (jen INFO)."""
    from envocad.model.feed import is_anchor_feed
    p = build_project({"building": "house", "battery": BAT,
                       "inverters": [{"ref": "T1", **RD_INV, "strings": [16, 16]}]})
    assert _sheet_refs(p) == {"RDC1", "RFVE"}
    sb = next(s for s in p.sheets if s.loc == "RFVE")
    anchors = {e.ref for e in sb.elements if is_anchor_feed(e)}
    assert anchors == {"X1", "XOUT", "XPE", "XE1", "XB1"}
    assert not [e for e in sb.elements if e.symbol_id in ("sb.busbar", "sb.main_switch", "fve.changeover_switch")]
    assert len([e for e in sb.elements if e.symbol_id == "fve.fuse_disconnect"]) == 2     # DC část
    b = _blocks(p)
    ins, outs = _ports(p, b["RFVE"])
    assert {"X1", "XE1"} <= set(ins) and {"XOUT", "XPE", "XB1"} <= set(outs)
    assert is_block_only(p, b["RD"]) and is_block_only(p, b["RE"])
    assert b["RD"].attrs["main"] == "hlavní vypínač" and b["RD"].attrs["fve_out"] == "jistič 20 A"
    assert _bad(p) == []
    codes = _codes(p)
    assert {f.severity for f in codes["eps_open"]} == {INFO} and {f.severity for f in codes["feed_anchor"]} == {INFO}


def test_house_without_dc_part_is_block_only():
    """RD bez DC části v RFVE (`dc.tech_box` false) a bez mustru: RFVE jen blok (porty X1…, XOUT, XPE)."""
    p = build_project({"building": "house", "dc": {"tech_box": False},
                       "inverters": [{"ref": "T1", **RD_INV, "strings": [12]}]})
    b = _blocks(p)
    assert is_block_only(p, b["RFVE"]) and "RFVE" not in _sheet_refs(p)
    assert _bad(p) == []


def test_vn_default_station_blocks_without_sheets():
    """Přípojka VN (rozhodnutí uživatele): HR, RVN, RE trafostanice i RFVE.AC jen bloky – porty z přívodů / vývodů
    vestavěného listu, údaje v popisku; listy jen s `builtin`. Kabel RFVE.AC → HR bez zadaného `ac.grid_*` podle In
    vývodu FVE v HR (D3). F7 bez chyb a varování (i bez známého překryvu vícepólu RE)."""
    p = build_project({"inverters": [{"ref": "T1", **INV, "strings": [20, 20]}], "connection": {"level": "vn"}})
    assert not {"HR", "RVN", "RE", "RFVE.AC"} & _sheet_refs(p)
    b = _blocks(p)
    assert all(is_block_only(p, b[r]) for r in ("HR", "RVN", "RE"))
    ins, outs = _ports(p, b["HR"])
    assert set(ins) == {"XT"} and set(outs) == {"X1", "X2", "XMI", "XMU"}
    hr = b["HR"].attrs
    assert hr["main"] == "hlavní jistič 1000 A" and hr["fve_out"] == "jistič 50 A" and hr["protect"] == "X1=50"
    assert hr["metering"].startswith("na nn, MTP") and b["RVN"].attrs["main"].startswith("pojistky VN")
    assert set(_ports(p, b["RE"])[0]) == {"XMI", "XMU"}
    w = next(w for w in p.sheets[0].wires if w.touches(b["RFVE.AC"].id) and w.touches(b["HR"].id))
    # vývod FVE v HR max(36 A, jistič střídače 50 A) → 50 A (B3, jako na nn), uložení D → 10 mm²
    assert (w.attrs["cable"], w.attrs["cross"]) == ("CYKY-J 5x10", "10")
    assert _bad(p) == []
    # vestavěné listy TS volbou
    p = build_project({"inverters": [{"ref": "T1", **INV, "strings": [20, 20]}], "connection": {"level": "vn"},
                       "chain": {"hr": {"builtin": True}, "rvn": {"builtin": True}, "re": {"builtin": True}}})
    assert {"HR", "RVN", "RE"} <= _sheet_refs(p)


# ---- volba vestavěného kódu --------------------------------------------------------------------------------------
def test_builtin_option_per_role_and_standard(monkeypatch, tmp_path):
    """`chain.<role>.builtin` zapne vestavěný list jen pro svůj článek; standard `ac_builtin` pro všechny AC články."""
    spec = {"inverters": [{"ref": "T1", **INV, "strings": [20, 20]}],
            "chain": {"hr": {"builtin": True, "main_in": 250}}}
    p = build_project(spec)
    assert "HR" in _sheet_refs(p) and not {"RFVE.AC", "RE"} & _sheet_refs(p)
    assert not is_block_only(p, _blocks(p)["HR"])
    p = build_project({**spec, "chain": {"rfve_ac": {"builtin": "1"}}})
    assert "RFVE.AC" in _sheet_refs(p) and "HR" not in _sheet_refs(p)
    # standard `ac_builtin` v nastavení (settings.json v ENVOCAD_HOME)
    from envocad.settings import settings_path
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"standard": {"ac_builtin": True}}), encoding="utf-8")
    p = build_project({"inverters": [{"ref": "T1", **INV, "strings": [20, 20]}]})
    assert {"RFVE.AC", "HR", "RE"} <= _sheet_refs(p)
    # volba článku má přednost před standardem
    p = build_project({"inverters": [{"ref": "T1", **INV, "strings": [20, 20]}], "chain": {"re": {"builtin": "0"}}})
    assert "RE" not in _sheet_refs(p) and "HR" in _sheet_refs(p)


def _user_macros(monkeypatch, tmp_path, roles: dict[str, str]) -> None:
    """Vlastní knihovna maker s mustry rolí (kopie vestavěných maker pod jiným názvem – „firemní“)."""
    from envocad.library import macros
    d = tmp_path / "macros"
    d.mkdir(exist_ok=True)
    for role, src in roles.items():
        data = json.loads((MACROS / src).read_text(encoding="utf-8"))
        data["name"] = f"{data['name']} firemní"
        assert data["role"] == role
        (d / f"firemni_{src}").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(macros, "user_dir", lambda: d)
    monkeypatch.setattr(macros, "shared_dir", lambda: None)


def test_pattern_macros_build_ac_sheet(monkeypatch, tmp_path):
    """Mustr = makra rolí `ac_feed` + `ac_core` ve vlastní / sdílené knihovně (vestavěná makra se nepočítají): list
    RFVE.AC z mustru; jen jedna role nestačí."""
    from envocad.generator.spec import pattern_macro
    from envocad.library.topologies import load_topologies
    spec = {"inverters": [{"ref": "T1", **INV, "strings": [20, 20]}]}
    topo = load_topologies()["nn"]
    assert pattern_macro(spec, spec, topo, "rfve_ac", "ac_feed") is None      # jen vestavěné makro
    _user_macros(monkeypatch, tmp_path, {"ac_feed": "ac_privod_stridace.json"})
    assert pattern_macro(spec, spec, topo, "rfve_ac", "ac_feed") == "AC přívod střídače firemní"
    assert "RFVE.AC" not in _sheet_refs(build_project(spec))                  # chybí jádro
    _user_macros(monkeypatch, tmp_path, {"ac_core": "ac_jadro_rozvadece.json"})
    p = build_project(spec)
    sb = next(s for s in p.sheets if s.loc == "RFVE.AC")
    assert any(e.symbol_id == "sb.main_switch" for e in sb.elements)
    assert not is_block_only(p, _blocks(p)["RFVE.AC"])
    # zadaný název ve specifikaci (vestavěné makro) mustr není
    assert pattern_macro({**spec, "macros": {"ac_feed": "AC přívod střídače"}},
                         {"macros": {"ac_feed": "AC přívod střídače"}}, topo, "rfve_ac", "ac_feed") \
        == "AC přívod střídače firemní"


def test_house_pattern_macros_without_eps_pattern(monkeypatch, tmp_path):
    """RD s mustrem AC části (ac_feed + ac_core) bez mustru EPS: AC část z mustru, EPS jen kotvy XE1 / XB1."""
    from envocad.model.feed import is_anchor_feed
    _user_macros(monkeypatch, tmp_path, {"ac_feed": "ac_privod_stridace.json", "ac_core": "ac_jadro_rozvadece.json"})
    p = build_project({"building": "house", "battery": BAT,
                       "inverters": [{"ref": "T1", **RD_INV, "strings": [16, 16]}]})
    sb = next(s for s in p.sheets if s.loc == "RFVE")
    assert any(e.symbol_id == "sb.main_switch" for e in sb.elements)
    assert {e.ref for e in sb.elements if is_anchor_feed(e)} == {"XE1", "XB1"}
    _user_macros(monkeypatch, tmp_path, {"ac_eps": "eps_prepinac_siti.json"})
    p = build_project({"building": "house", "battery": BAT,
                       "inverters": [{"ref": "T1", **RD_INV, "strings": [16, 16]}]})
    sb = next(s for s in p.sheets if s.loc == "RFVE")
    assert any(e.symbol_id == "fve.changeover_switch" for e in sb.elements)


# ---- síťová ochrana jako požadavek na bloku ------------------------------------------------------------------------
def test_grid_protection_requirement_on_block():
    """Nad 30 kWp bez listu RFVE.AC: požadavek síťové ochrany v atributu bloku – `grid_protection_missing` se
    nehlásí; bez požadavku (smazaný atribut) varování."""
    p = build_project({"inverters": [{"ref": "T1", **INV, "strings": [20, 20, 20, 20]}]})     # 36 kWp
    blk = _blocks(p)["RFVE.AC"]
    assert blk.attrs["grid_protection"] == "požadována"
    assert "grid_protection_missing" not in _codes(p)
    del blk.attrs["grid_protection"]
    assert [f.severity for f in _codes(p)["grid_protection_missing"]] == [WARNING]


def test_grid_protection_trip_and_u_findings():
    """D5: síťová ochrana působí na vazební prvek bez vypínací spouště → `grid_protection_trip`; měřicí vstup U
    přímo ze sběrnice (bez jištění) → `grid_protection_u`."""
    p = Project(name="Ochrana")
    s = p.sheets[0]
    bus = Element("sb.busbar", 100, 150, attrs={"ref": "1"})
    q = Element("sb.main_switch", 100, 120, rotation=270, attrs={"ref": "Q1", "in_": "125"})
    gp = Element("fve.grid_protection", 140, 120, attrs={"ref": "F1", "acts_on": "Q1"})
    s.elements += [bus, q, gp]
    s.wires += [Wire(WireEnd(bus.id, "3"), WireEnd(q.id, "1"), conductors=["L1"]),
                Wire(WireEnd(bus.id, "4"), WireEnd(gp.id, "U"), conductors=["L1"])]
    codes = _codes(p)
    assert codes["grid_protection_trip"][0].severity == WARNING and codes["grid_protection_u"][0].severity == WARNING
    q.attrs["trip"] = "vypínací spoušť"
    fu = Element("fve.breaker_mcb", 140, 140, rotation=270, attrs={"ref": "F2", "in_": "6"})
    s.elements.append(fu)
    s.wires[1] = Wire(WireEnd(bus.id, "4"), WireEnd(fu.id, "1"), conductors=["L1"])
    s.wires.append(Wire(WireEnd(fu.id, "2"), WireEnd(gp.id, "U"), conductors=["L1"]))
    codes = _codes(p)
    assert "grid_protection_trip" not in codes and "grid_protection_u" not in codes


# ---- B2: string u svého střídače přes RFVE se 2 střídači ----------------------------------------------------------
@pytest.mark.parametrize("builtin", [False, True])
@pytest.mark.parametrize("strings", [([16], [16]), ([16, 16], [16])])
def test_house_two_inverters_strings_on_own_inverter(strings, builtin):
    """RFVE rodinného domu se 2 střídači (AC přívody X1, X2 před DC částí): každý string patří svému střídači
    (párování jen DC portů bloku / přes list RFVE) – kontrola stringů i MPPT."""
    from envocad.model.calc import check_strings
    spec = {"building": "house", "inverters": [{"ref": f"T{i + 1}", **RD_INV, "strings": list(st)}
                                               for i, st in enumerate(strings)]}
    if builtin:
        spec["chain"] = {"rfve": {"builtin": True}}
    p = build_project(spec)
    got = {sc.ref: sc.inverter for sc in check_strings(p)}
    n1 = len(strings[0])
    want = {f"G{k + 1}": ("T1" if k < n1 else "T2") for k in range(n1 + len(strings[1]))}
    assert got == want


def test_block_exit_pairs_only_dc_ports():
    """Bez listu rozvaděče se párují jen porty zapojené DC vodičem (AC přívody X1…Xn se nepočítají)."""
    from envocad.model.calc import _block_exit
    p = Project(name="Blok")
    s = p.sheets[0]
    blk = Element("fve.switchboard", 100, 150, attrs={"ref": "RFVE"})
    others = [Element("fve.terminal", 0, 0, attrs={"ref": f"X{k}"}) for k in range(6)]
    s.elements += [blk, *others]
    ac = ["L1", "L2", "L3", "N", "PE"]
    for k, port in enumerate(("X1", "X2")):
        s.wires.append(Wire(WireEnd(others[k].id, "1"), WireEnd(blk.id, port), conductors=list(ac)))
    for k, port in enumerate(("X3", "X4", "X5", "X6")):
        s.wires.append(Wire(WireEnd(others[2 + k].id, "1"), WireEnd(blk.id, port), conductors=["L+", "L-"]))
    assert _block_exit(s, blk, "X3") == "X5" and _block_exit(s, blk, "X4") == "X6"


# ---- D1 / D2 / B3 / D3: jištění a kabely --------------------------------------------------------------------------
def test_inverter_breaker_rules():
    """D1: jistič přívodu střídače ≥ 1,25 × max. AC proud (z P AC i z artiklu `i_ac_max_a`); řada do 250 A, nad ní
    prázdné s důvodem; 1f do 63 A."""
    from envocad.generator.currents import inverter_breaker
    assert inverter_breaker(Element("fve.inverter", 0, 0, attrs={"p_ac": "25"}))[0] == "50"
    assert inverter_breaker(Element("fve.inverter", 0, 0, attrs={"p_ac": "100"}))[0] == "200"
    assert inverter_breaker(Element("fve.inverter", 0, 0, attrs={"p_ac": "120"}))[0] == "250"
    big = inverter_breaker(Element("fve.inverter", 0, 0, attrs={"p_ac": "150", "ref": "T9"}))
    assert big[0] == "" and "T9" in big[1] and "250" in big[1]
    assert inverter_breaker(Element("fve.inverter", 0, 0, attrs={"p_ac": "5", "phases": "1"}))[0] == "32"
    art = Element("fve.inverter", 0, 0, attrs={}, component_id="huawei-sun2000-100ktl-m2")    # i_ac_max 160,4 A
    assert inverter_breaker(art)[0] == "250"                                                  # 1,25 × 160,4 = 200,5
    assert inverter_breaker(Element("fve.inverter", 0, 0, attrs={})) == ("", "")


def test_inverter_breaker_over_series_is_unresolved():
    """Automatický jistič nad řadou: prázdné In + `in_unresolved` (chyba F7) – nic se nedosazuje."""
    p = build_project({"inverters": [{"ref": "T1", **INV, "p_ac": 150, "strings": [20]}],
                       "chain": {"rfve_ac": {"builtin": True}}})
    sb = next(s for s in p.sheets if s.loc == "RFVE.AC")
    f = next(e for e in sb.elements if e.attrs.get("chain") == "inv")
    assert f.attrs["in_"] == "" and "nad řadou" in f.attrs["in_unresolved"]
    assert any(x.code == "breaker_no_in" and x.severity == ERROR for x in check_project(p, _lib()))


def test_main_switch_from_inverter_articles():
    """D2: hlavní vypínač RFVE.AC z prvků střídačů – artikl bez `p_ac` ve specifikaci: 2 × Huawei 100 kW
    (i_ac_max 160,4 A, jistič 1,25 × → 250 A) → vývod FVE ≥ 320,8 A → 400 A, hlavní vypínač 400 A (ne 125 A)."""
    inv = {"component_id": "huawei-sun2000-100ktl-m2", "strings": [20]}
    p = build_project({"inverters": [{"ref": "T1", **inv}, {"ref": "T2", **inv}]})
    b = _blocks(p)
    assert b["RFVE.AC"].attrs["main"] == "hlavní vypínač 400 A"
    assert b["RFVE.AC"].attrs["inv_protect"] == "2× 250 A"
    assert b["HR"].attrs["fve_out"] == "jistič 400 A"


def test_cable_to_hr_from_raw_grid_or_fve_in():
    """D3: kabel RFVE.AC → HR – zadané `ac.grid_*` platí, jinak nejmenší průřez pro In vývodu FVE; zadaný malý
    průřez proti In vývodu (atribut `protect` bloku HR bez listu) → chyba F7 `calc_cable`."""
    base = {"inverters": [{"ref": "T1", **INV, "strings": [20, 20]}]}
    p = build_project(base)
    b = _blocks(p)
    w = next(w for w in p.sheets[0].wires if w.touches(b["RFVE.AC"].id) and w.touches(b["HR"].id))
    assert (w.attrs["cable"], w.attrs["cross"]) == ("CYKY-J 5x10", "10")      # vývod FVE 50 A, uložení D
    p = build_project({**base, "ac": {"grid_cable": "CYKY-J 5x6", "grid_cross": 6}})
    b = _blocks(p)
    w = next(w for w in p.sheets[0].wires if w.touches(b["RFVE.AC"].id) and w.touches(b["HR"].id))
    assert w.attrs["cable"] == "CYKY-J 5x6"
    bad = [f.text for f in check_project(p, _lib()) if f.code == "calc_cable" and f.severity == ERROR]
    assert any("HR:X1" in t and "Iz" in t for t in bad), bad


# ---- D6 / D7: EPS -------------------------------------------------------------------------------------------------
def test_eps_unconnected_manual_is_info():
    """D6: ruční projekt (střídač bez `eps`) se zapojeným BACKUP, který nevede na přepínač sítí → jen INFO."""
    p = Project(name="Ruční EPS")
    s = p.sheets[0]
    t = Element("fve.inverter_hybrid", 100, 150, attrs={"ref": "T1", "io": "BACKUP"})
    bat = Element("fve.battery", 100, 100, attrs={"ref": "G1"})
    load = Element("fve.load", 150, 150, attrs={"ref": "", "desc": "okruhy"})
    s.elements += [t, bat, load]
    s.wires += [Wire(WireEnd(t.id, "BAT"), WireEnd(bat.id, "DC"), conductors=["L+", "L-"]),
                Wire(WireEnd(t.id, "BACKUP"), WireEnd(load.id, "1"), conductors=["L1", "N", "PE"])]
    f = _codes(p)["eps_unconnected"]
    assert [x.severity for x in f] == [INFO]
    t.attrs["eps"] = "1"
    assert [x.severity for x in _codes(p)["eps_unconnected"]] == [WARNING]


def test_eps_only_for_inverter_with_battery():
    """D7: EPS (přepínač, XE / XB) jen u střídače, ke kterému je připojená baterie."""
    from envocad.generator.boards.base import ChainContext
    from envocad.generator.boards.eps import eps_inverters
    p = build_project({"building": "house", "battery": BAT, "chain": {"rfve": {"builtin": True}},
                       "inverters": [{"ref": "T1", **RD_INV, "strings": [16]}, {"ref": "T2", **RD_INV, "strings": [16]}]})
    sb = next(s for s in p.sheets if s.loc == "RFVE")
    assert {e.ref for e in sb.elements if e.ref.startswith(("XE", "XB"))} == {"XE1", "XB1"}
    s = p.sheets[0]
    invs = [e for e in s.elements if e.symbol_id.startswith("fve.inverter")]
    ctx = ChainContext(spec={"battery": BAT}, project=p, sheet=s, building="house", combined=True, geo=None,
                       inverters=invs)
    from envocad.library.topologies import load_topologies
    ctx.topology = load_topologies()["rd"]
    assert [t.ref for _i, t in eps_inverters(ctx)] == ["T1"]
    s.wires = [w for w in s.wires if not any(e.symbol_id == "fve.battery" for e in s.elements
                                             if w.touches(e.id))]
    assert eps_inverters(ctx) == []


# ---- popis článku: pořadí přednosti jako označení ------------------------------------------------------------------
def test_node_desc_precedence_like_ref():
    from envocad.generator.spec import node_desc
    from envocad.library.topologies import load_topologies
    topo = load_topologies()["nn"]
    assert node_desc({}, topo, "hr", default="kód") == "hlavní rozvaděč"                # preset > výchozí kód
    assert node_desc({}, topo, "hr", legacy="dřívější", default="kód") == "dřívější"
    assert node_desc({"chain": {"hr": {"desc": "HR objektu"}}}, topo, "hr", legacy="x") == "HR objektu"
    assert node_desc({}, topo, "tr", default="kód") == "kód"                           # role mimo preset


# ---- F7 výchozích projektů z průvodce --------------------------------------------------------------------------------
def _wizard_spec(building: str, level: str = "nn", battery: bool = False) -> dict:
    """Specifikace jako `ui/dialogs.ProjectWizard.spec` s výchozími poli průvodce (2 střídače 25 kW, stringy
    „18,18,18,18; 18,18“, 1 rozvaděč po trase, jistič 40 A, hlavní vypínač 125 A, kabel do HDS 35 mm²); s baterií
    navíc (průvodce ji zatím nenabízí). Skutečný dialog testuje `test_gui_smoke.py`."""
    from envocad.settings import load_settings
    std = load_settings()["standard"]
    spec = {
        "name": "Nový projekt FVE", "meta": {"investor": "", "place": "", "order": "", "author": ""},
        "building": building,
        "module": {"type": "", "p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9},
        "site": {"t_min": std["pv_t_min"], "t_max": std["pv_t_max"]},
        "optimizer": {"type": "", "per_module": 1},
        "inverters": [{"ref": f"T{i + 1}", "type": "", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200,
                       "u_mppt_max": 1000, "i_mppt_max": 30, "strings": st}
                      for i, st in enumerate(([18, 18, 18, 18], [18, 18]))],
        "dc": {"cable": std["dc_cable"], "cross": std["dc_cross"], "length": 30, "route_boxes": 1,
               "route_length": 20, "tech_box": True, "tech_length": 5, "fuse_in": "", "spd": "T1+T2",
               "disconnect": False},
        "ac": {"cable": std["ac_cable"], "cross": std["ac_cross"], "length": 30, "breaker_in": 40, "main_in": 125,
               "grid_cable": std["grid_cable"], "grid_cross": std["grid_cross"], "grid_length": 20,
               "distribution": "bus"},
        "grid": {"dso": ""},
        "connection": {"level": level, "metering": "nn", "station": "kiosk", "loop": True,
                       "transformer": {"sn": 630}},
    }
    if battery:
        spec["battery"] = BAT
    return spec


@pytest.mark.parametrize("building,level,battery", [("company", "nn", False), ("house", "nn", False),
                                                    ("house", "nn", True), ("apartment", "nn", False),
                                                    ("company", "vn", False)],
                         ids=["firma", "RD", "RD-baterie", "BD", "vn"])
def test_wizard_default_projects_f7_clean(building, level, battery):
    """Výchozí projekty z průvodce (firma, RD, BD, vn): F7 bez chyb a varování, žádný list nad `jps_max_paper`."""
    from envocad.generator.jps import jps_max_paper
    from envocad.model.frame import paper_exceeds
    p = build_project(_wizard_spec(building, level, battery))
    assert _bad(p) == []
    assert not [s.paper for s in p.sheets if not s.is_switchboard and paper_exceeds(s.paper, jps_max_paper())]


# ---- B1: formát blokového schématu jako na main ---------------------------------------------------------------------
# firma na nn, n střídačů × k stringů × r rozvaděčů po trase – na main (před F2) jeden list A2
MAIN_ONE_A2 = [(4, 2, 0), (5, 2, 0), (3, 3, 0), (2, 3, 2), (2, 4, 2), (3, 2, 2), (5, 1, 2), (6, 1, 0), (6, 1, 1),
               (6, 1, 2)]


@pytest.mark.parametrize("n,k,r", MAIN_ONE_A2)
def test_company_fits_one_a2_like_main(n, k, r):
    p = build_project({"inverters": [{"ref": f"T{i}", **INV, "strings": [20] * k} for i in range(1, n + 1)],
                       "dc": {"route_boxes": r}})
    assert [s.paper for s in p.sheets if not s.is_switchboard] == ["A2"]


@pytest.mark.parametrize("n,k,r", [(5, 8, 0), (6, 6, 1), (6, 8, 2)])
def test_company_no_sheet_over_limit(n, k, r):
    """Velké firmy: žádný list blokového schématu nad `jps_max_paper` (A2) – společný RFVE.DC, který by list
    „AC a připojení“ zvětšil nad limit, se nahradí RFVE.DC na střídač."""
    p = build_project({"inverters": [{"ref": f"T{i}", **INV, "strings": [20] * k} for i in range(1, n + 1)],
                       "dc": {"route_boxes": r}})
    assert {s.paper for s in p.sheets if not s.is_switchboard} == {"A2"}


def test_stack_components_keeps_group_blocks():
    """Rozdělené JPS se skupinou střídačů (`ac_group`): RFVE.AC2 zůstává u svého přerušení (stack_components
    přesouvá jen samostatný společný RFVE.DC)."""
    inv = [{"ref": f"T{i}", **INV, "strings": [20] * 4, **({"ac_group": "hala B"} if i > 3 else {})}
           for i in range(1, 6)]
    p = build_project({"inverters": inv, "jps": {"split": "auto", "max_paper": "A2", "paper": "A2"}})
    ac = next(s for s in p.sheets if not s.is_switchboard)
    blk2 = next(e for e in ac.elements if e.ref == "RFVE.AC2")
    i_g = next(e for e in ac.elements if e.symbol_id == "fve.interrupt" and e.ref.startswith("AC2-"))
    assert abs(blk2.y - i_g.y) < 40.0
    assert {s.paper for s in p.sheets if not s.is_switchboard} == {"A2"}


def test_builtin_macros_not_a_pattern(monkeypatch, tmp_path):
    """Vestavěná makra (zdroj „vestavěné“) se za mustr nepovažují ani nalezená podle role."""
    from envocad.library import macros
    monkeypatch.setattr(macros, "user_dir", lambda: tmp_path / "nic")
    monkeypatch.setattr(macros, "shared_dir", lambda: None)
    p = build_project({"inverters": [{"ref": "T1", **INV, "strings": [20]}]})
    assert "RFVE.AC" not in _sheet_refs(p)


# ---- RD: formát blokového schématu jako na main (sweep 1–4 střídače × 1–8 stringů × 0–2 rozvaděče po trase) ------
# origin/main (před F2): "nkr" → (počet listů JPS, největší formát)
MAIN_RD = {
    "110": (1, "A3"), "111": (1, "A3"), "112": (1, "A2"), "120": (1, "A3"), "121": (1, "A3"), "122": (1, "A2"),
    "130": (1, "A3"), "131": (1, "A3"), "132": (1, "A2"), "140": (1, "A3"), "141": (1, "A3"), "142": (1, "A2"),
    "150": (1, "A3"), "151": (1, "A2"), "152": (1, "A2"), "160": (1, "A2"), "161": (1, "A2"), "162": (1, "A2"),
    "170": (1, "A2"), "171": (1, "A2"), "172": (1, "A2"), "180": (1, "A2"), "181": (1, "A2"), "182": (1, "A2"),
    "210": (1, "A3"), "211": (1, "A3"), "212": (1, "A2"), "220": (1, "A3"), "221": (1, "A3"), "222": (1, "A2"),
    "230": (1, "A2"), "231": (1, "A2"), "232": (1, "A2"), "240": (1, "A2"), "241": (1, "A2"), "242": (1, "A2"),
    "250": (1, "A2"), "251": (3, "A2"), "252": (3, "A2"), "260": (1, "A2"), "261": (3, "A2"), "262": (3, "A2"),
    "270": (3, "A2"), "271": (3, "A2"), "272": (3, "A2"), "280": (3, "A2"), "281": (3, "A2"), "282": (3, "A1"),
    "310": (1, "A3"), "311": (1, "A3"), "312": (1, "A2"), "320": (1, "A2"), "321": (1, "A2"), "322": (1, "A2"),
    "330": (1, "A2"), "331": (3, "A2"), "332": (3, "A2"), "340": (3, "A2"), "341": (3, "A2"), "342": (3, "A2"),
    "350": (3, "A2"), "351": (4, "A2"), "352": (4, "A2"), "360": (3, "A2"), "361": (4, "A2"), "362": (4, "A1"),
    "370": (4, "A2"), "371": (4, "A2"), "372": (4, "A1"), "380": (4, "A1"), "381": (4, "A1"), "382": (4, "A1"),
    "410": (1, "A2"), "411": (1, "A2"), "412": (1, "A2"), "420": (1, "A2"), "421": (3, "A2"), "422": (3, "A2"),
    "430": (3, "A2"), "431": (3, "A2"), "432": (3, "A2"), "440": (3, "A2"), "441": (3, "A2"), "442": (5, "A1"),
    "450": (3, "A2"), "451": (5, "A2"), "452": (5, "A1"), "460": (3, "A1"), "461": (5, "A1"), "462": (5, "A1"),
    "470": (5, "A1"), "471": (5, "A1"), "472": (5, "A1"), "480": (5, "A0"), "481": (5, "A0"), "482": (5, "A0")
}
_PAPERS = ("A3", "A2", "A1", "A0")


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_house_sheets_like_main(n):
    """Rodinný dům (řetězec RD → RE → HDS → DS): žádný projekt nemá víc listů blokového schématu než na main a žádný
    list není větší než na main ani než A2 (kromě přerostlé řady jednoho střídače, která byla větší i na main)."""
    for k in range(1, 9):
        for r in range(3):
            p = build_project({"building": "house", "dc": {"route_boxes": r},
                               "inverters": [{"ref": f"T{i}", **INV, "strings": [20] * k} for i in range(1, n + 1)]})
            papers = [s.paper for s in p.sheets if not s.is_switchboard]
            count, biggest = MAIN_RD[f"{n}{k}{r}"]
            limit = max(_PAPERS.index(biggest), _PAPERS.index("A2"))
            assert len(papers) <= count and max(_PAPERS.index(x) for x in papers) <= limit, (n, k, r, papers)
