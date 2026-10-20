"""Výpočty z modelu (bez Qt)."""

from dataclasses import replace

from envocad.library.store import LibraryStore
from envocad.model import calc
from envocad.model.checks import WARNING, check_project
from envocad.model.project import Element, Project, Wire, WireEnd


def _fve():
    p = Project(name="Výpočty")
    s = p.sheets[0]
    g = Element("fve.pv_string", 30, 150, attrs={"ref": "G1", "n_modules": "20", "voc": "49.5", "vmp": "41.5",
                                                   "isc": "13.9", "beta_voc": "-0.27"})
    q = Element("fve.dc_disconnect", 80, 150, attrs={"ref": "Q1", "in_": "32"})
    t = Element("fve.inverter", 130, 150, attrs={"ref": "T1", "p_ac": "50", "phases": "3", "u_dc_max": "1100",
                                                   "u_mppt_min": "200", "u_mppt_max": "1000", "i_mppt_max": "30"})
    f = Element("fve.breaker_mcb", 190, 150, attrs={"ref": "F1", "in_": "80", "poles": "3"})
    f2 = Element("fve.breaker_mcb", 240, 150, attrs={"ref": "F2", "in_": "63", "poles": "3"})
    n = Element("fve.grid", 290, 150)
    s.elements += [g, q, t, f, f2, n]
    s.wires += [
        Wire(WireEnd(g.id, "DC"), WireEnd(q.id, "1"), attrs={"ref": "W1", "cable": "H1Z2Z2-K 1x6", "cross": "6", "length": "60"},
             conductors=["DC+", "DC-"]),
        Wire(WireEnd(q.id, "2"), WireEnd(t.id, "DC1"), conductors=["DC+", "DC-"]),
        Wire(WireEnd(t.id, "AC"), WireEnd(f.id, "1"), attrs={"ref": "W2", "cable": "CYKY-J 5x16", "cross": "16",
                                                            "length": "40", "route": "v zemi"},
             conductors=["L1", "L2", "L3", "N", "PE"]),
        Wire(WireEnd(f.id, "2"), WireEnd(f2.id, "1"), attrs={"ref": "W3", "cable": "CYKY-J 5x25", "cross": "25", "length": "10"},
             conductors=["L1", "L2", "L3", "N", "PE"]),
        Wire(WireEnd(f2.id, "2"), WireEnd(n.id, "1"), conductors=["L1", "L2", "L3", "N", "PE"]),
    ]
    return p, s


def test_ampacity_and_drop():
    assert calc.ampacity(16, "C", 3) == 76 and calc.ampacity(16, "D", 3) == 64
    assert calc.ampacity(2.5, "B1", 2) == round(21 * 1.1, 1)
    assert calc.ampacity(16, "C", 3, aluminium=True) < 76
    assert calc.ampacity(16, "C", 3, t_ambient=40) == round(76 * 0.87, 1)
    assert calc.ampacity(300, "C") is None
    du, pct = calc.voltage_drop(72.2, 40, 16, "3f", 400)
    assert 6.5 < du < 7.5 and 1.5 < pct < 2.0   # √3·I·ρ·L/S
    du_dc, pct_dc = calc.voltage_drop(17.4, 60, 6, "dc", 830)
    assert 7 < du_dc < 9 and pct_dc < 1.2   # 2·I·ρ·L/S


def test_string_and_cable_checks():
    p, s = _fve()
    st = calc.check_strings(p)
    assert len(st) == 1 and st[0].inverter == "T1" and st[0].ok, st[0].issues
    assert 1070 < st[0].uoc_cold < 1090           # 20 × 49,5 × (1 + 0,0027·35) ≈ 1083 V
    # zvýšení počtu modulů → Uoc nad Umax
    g = next(e for e in s.elements if e.ref == "G1")
    g.attrs["n_modules"] = "24"
    st = calc.check_strings(p)
    assert any("Umax" in m for m in st[0].issues)
    g.attrs["n_modules"] = "20"
    cc = {c.ref: c for c in calc.check_cables(p)}
    assert cc["W1"].system == "dc" and cc["W1"].i_a == round(1.25 * 13.9, 2) and cc["W1"].iz is not None
    assert cc["W2"].method == "D" and cc["W2"].i_a == 72.2 and cc["W2"].iz == 64   # 16 mm² v zemi: 64 A < 72 A
    assert any("Iz" in m for m in cc["W2"].issues) and any("In jističe F1" in m for m in cc["W2"].issues)
    assert cc["W3"].in_breaker == 80 and cc["W3"].iz == 96 and not cc["W3"].issues
    sel = calc.check_selectivity(p)
    pair = next(x for x in sel if x[0] == "F1")
    assert pair[1] == "F2" and "menší In" in pair[4]           # F2 (63 A) je od sítě nadřazený F1 (80 A)
    codes = {f.code for f in check_project(p, LibraryStore())}
    assert {"calc_cable", "calc_selectivity"} <= codes
    from envocad.export import reports
    _, rows = reports.calculations(p, LibraryStore())
    assert [r[0] for r in rows][:1] == ["String"] and any(r[0] == "Kabel" and r[1] == "W2" for r in rows)


# ---- katalog FV: data modulu/střídače, meze stringu, návrh stringů (docs/design/katalog_fv.md §2) ------------
MOD = calc.ModuleData(voc=49.5, vmp=41.5, isc=13.9, imp=13.2, beta_voc=-0.27)
INV = calc.InverterData(u_dc_max=1100, u_mppt_min=200, u_mppt_max=1000, i_mppt_max=30, mppt=3, strings_per_mppt=2)


def _spec(**inv):
    return {"name": "S", "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000,
                                        "i_mppt_max": 30, "strings": [20, 20, 18], **inv}]}


def test_module_and_inverter_from_attrs():
    m = calc.ModuleData.from_attrs({"voc": "49,5", "isc": "13.9", "imp": "13.2", "u_sys_max": "1500", "p_module": "450"})
    assert m.vmp == 49.5 * 0.82 and m.beta_voc == calc.BETA_VOC_DEFAULT and m.u_sys_max == 1500 and m.p_wp == 450
    assert calc.ModuleData.from_attrs({"isc": "13.9"}) is None and calc.ModuleData.from_attrs({"voc": "0"}) is None
    i = calc.InverterData.from_attrs({"u_dc_max": "1100", "mppt": "3", "strings_per_mppt": "", "isc_mppt_max": "40"})
    # neznámé stringů na MPPT zůstane None (výchozí 2 jen pro počet DC vstupů, ne pro sčítání proudů)
    assert i.u_dc_max == 1100 and i.mppt == 3 and i.strings_per_mppt is None and i.isc_mppt_max == 40 and i.u_mppt_min is None
    assert abs(MOD.uoc(-10) - 49.5 * (1 + 0.0027 * 35)) < 1e-9 and MOD.uoc(25) == 49.5


def test_design_temperatures():
    p = Project(name="T")
    assert calc.design_temperatures(p) == (calc.T_MIN_DEFAULT, calc.T_MAX_DEFAULT) == (-10.0, 70.0)
    p.meta.update({"pv_t_min": "-20", "pv_t_max": "75,5"})
    assert calc.design_temperatures(p) == (-20.0, 75.5)
    p.meta["pv_t_min"] = "x"
    assert calc.design_temperatures(p)[0] == -10.0


def test_string_limits_consistent_with_issues():
    lim = calc.string_limits(MOD, INV, -10, 70)
    assert (lim.n_min, lim.n_max, lim.n_par_max) == (6, 20, 2) and lim.ok   # 1100/54,18 → 20; 200/36,46 → 6
    assert any("nejvýš 20 modulů" in r and "Umax střídače" in r for r in lim.reasons)
    assert not calc.string_issues(MOD, INV, 20, 1, -10, 70) and not calc.string_issues(MOD, INV, 6, 1, -10, 70)
    assert any("Umax" in x for x in calc.string_issues(MOD, INV, 21, 1, -10, 70))
    assert any("Umppt min" in x for x in calc.string_issues(MOD, INV, 5, 1, -10, 70))
    # chladnější návrhová teplota zmenší horní mez
    assert calc.string_limits(MOD, INV, -20, 70).n_max == 19
    # Umax systému modulu
    m = calc.ModuleData(voc=49.5, vmp=41.5, isc=13.9, u_sys_max=1000)
    lim = calc.string_limits(m, INV, -10, 70)
    assert lim.n_max == 18 and any("systému modulu" in r for r in lim.reasons)
    assert any("> Umax systému modulu 1000 V" in x for x in calc.string_issues(m, INV, 19, 1, -10, 70))
    # neslučitelné okno: prázdný rozsah
    narrow = calc.InverterData(u_dc_max=300, u_mppt_min=280, u_mppt_max=290)
    lim = calc.string_limits(MOD, narrow, -10, 70)
    assert not lim.ok and any("prázdný" in r for r in lim.reasons)
    # bez údajů střídače: bez horní meze, s důvodem
    lim = calc.string_limits(MOD, calc.InverterData(), -10, 70)
    assert lim.n_max is None and lim.n_min == 1 and any("nemá zadané" in r for r in lim.reasons)


def test_string_current_rules():
    # bez isc_mppt_max: dosavadní pravidlo 1,25·Isc jednoho stringu, paralelní stringy se nesčítají
    assert not calc.string_issues(MOD, INV, 20, 2, -10, 70)
    low = calc.InverterData(u_dc_max=1100, u_mppt_min=200, u_mppt_max=1000, i_mppt_max=16)
    assert calc.string_issues(MOD, low, 20, 1, -10, 70) == ["1,25·Isc 17.4 A > Imax vstupu 16 A"]
    assert calc.string_limits(MOD, low, -10, 70).n_par_max == 0
    # s isc_mppt_max: součet Isc = chyba, součet Imp nad Imax = varování „omezení výkonu“
    inv = calc.InverterData(u_dc_max=1100, u_mppt_min=200, u_mppt_max=1000, i_mppt_max=20, isc_mppt_max=30,
                            strings_per_mppt=2)
    assert not calc.string_issues(MOD, inv, 20, 1, -10, 70)
    issues = calc.string_issues(MOD, inv, 20, 2, -10, 70)   # 2 × 13,9 = 27,8 ≤ 30; 2 × 13,2 = 26,4 > 20
    assert len(issues) == 1 and "omezení výkonu" in issues[0]
    tight = calc.InverterData(u_dc_max=1100, u_mppt_min=200, u_mppt_max=1000, i_mppt_max=30, isc_mppt_max=20)
    assert any("Isc max MPPT 20 A" in x for x in calc.string_issues(MOD, tight, 20, 2, -10, 70))
    lim = calc.string_limits(MOD, tight, -10, 70)
    assert lim.n_par_max == 1 and any("nejvýš 1 string na MPPT:" in r for r in lim.reasons)


def test_suggest_inverter_count():
    assert calc.suggest_inverter_count(30, 25) == 1
    assert calc.suggest_inverter_count(32.5, 25) == 1             # přesně 1,3
    assert calc.suggest_inverter_count(40, 25) == 2
    assert calc.suggest_inverter_count(100, 25, dc_ac_max=1.0) == 4
    assert calc.suggest_inverter_count(0, 25) == 1 and calc.suggest_inverter_count(10, 0) == 1


def test_propose_strings():
    lim = calc.StringLimits(6, 20, 2)
    assert calc.propose_strings(58, 1, lim, INV) == ([[20, 19, 19]], 0)
    assert calc.propose_strings(78, 2, lim, INV) == ([[20, 19], [20, 19]], 0)
    # kapacita střídače 3 MPPT × 2 stringy = 6 stringů po 20 modulech
    assert calc.propose_strings(200, 1, lim, INV) == ([[20] * 6], 80)
    # úzký rozsah: 41 modulů do stringů 18–20 → 2 × 20, jeden zbývá
    assert calc.propose_strings(41, 1, calc.StringLimits(18, 20, 2), INV) == ([[20, 20]], 1)
    assert calc.propose_strings(5, 1, lim, INV) == ([[]], 5)            # méně než n_min
    assert calc.propose_strings(50, 2, calc.StringLimits(1, None, 2), INV) == ([[], []], 50)
    assert calc.propose_strings(50, 1, calc.StringLimits(6, 20, 0), INV) == ([[]], 50)
    # neznámý počet MPPT = bez omezení počtu stringů
    assert calc.propose_strings(200, 1, lim, calc.InverterData())[0] == [[20] * 10]
    # návrh projde kontrolou stringů
    for n in calc.propose_strings(58, 1, calc.string_limits(MOD, INV), INV)[0][0]:
        assert not calc.string_issues(MOD, INV, n, 2)


def test_check_strings_groups_by_mppt_through_dc_boxes():
    from envocad.generate import build_project
    p = build_project(_spec(strings_per_mppt=2))   # string → RDC po trase → RDC u technologie → DC1…DC3
    st = {sc.ref: sc for sc in calc.check_strings(p)}
    assert [(st[r].mppt, st[r].n_par) for r in ("G1", "G2", "G3")] == [(0, 2), (0, 2), (1, 1)]
    assert all(sc.ok for sc in st.values()) and st["G1"].t_min == -10.0
    # isc_mppt_max: dva stringy na MPPT 0 překročí 20 A, samotný G3 ne
    p = build_project(_spec(isc_mppt_max=20, strings_per_mppt=2))
    st = {sc.ref: sc for sc in calc.check_strings(p)}
    assert not st["G1"].ok and any("Isc 2× 13.9 A" in x for x in st["G1"].issues) and st["G3"].ok
    assert st["G1"].isc_mppt_max == 20
    # bez DC rozvaděčů, jeden string na MPPT
    p = build_project({**_spec(strings_per_mppt=1), "dc": {"route_boxes": 0, "tech_box": False}})
    assert [(sc.mppt, sc.n_par) for sc in calc.check_strings(p)] == [(0, 1), (1, 1), (2, 1)]


def test_check_strings_design_temperatures_and_warning():
    p, s = _fve()
    p.meta["pv_t_min"] = "-25"
    sc = calc.check_strings(p)[0]
    assert sc.t_min == -25 and sc.uoc_cold == round(20 * 49.5 * (1 + -0.0027 * -50), 1)
    assert calc.check_strings(p, -10, 70)[0].uoc_cold < sc.uoc_cold     # explicitní teploty vyhrávají
    from envocad.export import reports
    _, rows = reports.calculations(p, LibraryStore())
    assert "Uoc(-25 °C)" in rows[0][2]
    # „omezení výkonu“ je v kontrole projektu varování, ne chyba
    g = next(e for e in s.elements if e.ref == "G1")
    t = next(e for e in s.elements if e.ref == "T1")
    g.attrs["imp"] = "13.2"
    t.attrs.update({"isc_mppt_max": "40", "i_mppt_max": "10"})
    p.meta.pop("pv_t_min")
    fs = [f for f in check_project(p, LibraryStore()) if f.code == "calc_string"]
    assert len(fs) == 1 and fs[0].severity == WARNING and "omezení výkonu" in fs[0].text


# ---- review katalogu FV: MPPT jako generátor, neznámé stringů/MPPT, kapacita, Umpp(t), teploty, skloňování ---------
def test_string_ports_and_mppt_assignment():
    inv = calc.InverterData(mppt=3, strings_per_mppt=2)
    # známé mppt: vstupy rovnoměrně po MPPT (MPPT m = DC(2m+1), DC(2m+2)), stringům vzestupně – vodiče se nekříží
    assert calc.string_ports(4, inv) == [1, 2, 3, 5]
    assert calc.assign_mppt(4, inv) == [0, 0, 1, 2] and calc.mppt_groups([0, 0, 1, 2]) == [2, 2, 1, 1]
    # nad kapacitu 3 × 2: další stringy za sebou (DC7, DC8 → „MPPT 3“ – hlásí `capacity_issue`)
    assert calc.string_ports(8, inv) == [1, 2, 3, 4, 5, 6, 7, 8]
    # neznámé mppt: DC1, DC2… za sebou jako dosud
    assert calc.string_ports(3, calc.InverterData(strings_per_mppt=2)) == [1, 2, 3]
    assert calc.assign_mppt(3, calc.InverterData(strings_per_mppt=2)) == [0, 0, 1]
    # neznámé stringů na MPPT: MPPT se nezjišťuje, proudy se nesčítají (výchozí 2 jen pro rozložení vstupů)
    assert calc.string_ports(3, calc.InverterData(mppt=2)) == [1, 2, 3]
    assert calc.assign_mppt(3, calc.InverterData(mppt=2)) == [None, None, None]
    assert calc.mppt_groups([None, None]) == [1, 1] and calc.port_mppt(5, None) is None


def test_generator_spreads_strings_over_known_mppt():
    from envocad.generate import build_project
    p = build_project({**_spec(mppt=3, strings_per_mppt=2, strings=[20, 20, 18, 18]),
                       "dc": {"route_boxes": 0, "tech_box": False}})
    s = p.sheets[0]
    t = next(e for e in s.elements if e.ref == "T1")
    ports = [w.b.port for w in s.wires if w.b.element_id == t.id and w.b.port.startswith("DC")]
    assert ports == ["DC1", "DC2", "DC3", "DC5"]
    st = calc.check_strings(p)
    assert [(sc.mppt, sc.n_par) for sc in st] == [(0, 2), (0, 2), (1, 1), (2, 1)]
    # mppt jen dopočtené z počtu stringů → za sebou jako dosud
    p = build_project({**_spec(strings_per_mppt=2), "dc": {"route_boxes": 0, "tech_box": False}})
    assert [sc.mppt for sc in calc.check_strings(p)] == [0, 0, 1]


def test_unknown_strings_per_mppt_not_summed():
    from envocad.generate import build_project
    from envocad.model.project import inverter_dc_inputs
    p = build_project(_spec(isc_mppt_max=20))     # 2 × 13,9 A > 20 A by platilo jen při 2 stringech na MPPT
    t = next(e for e in p.sheets[0].elements if e.ref == "T1")
    assert t.attrs["strings_per_mppt"] == "" and t.attrs["mppt"] == "2"
    assert inverter_dc_inputs(p, t) == 4          # DC vstupy dál s výchozími 2 na MPPT
    st = calc.check_strings(p)
    assert [(sc.mppt, sc.n_par) for sc in st] == [(None, 1)] * 3 and all(sc.ok for sc in st)
    # stávající projekt s uloženým strings_per_mppt = 2 sčítá jako dřív
    t.attrs["strings_per_mppt"] = "2"
    st = calc.check_strings(p)
    assert [(sc.mppt, sc.n_par) for sc in st] == [(0, 2), (0, 2), (1, 1)] and not st[0].ok


def test_capacity_issue_more_strings_than_inputs():
    from envocad.generate import build_project
    from envocad.model.checks import ERROR
    assert calc.capacity_issue("T1", calc.InverterData(mppt=3, strings_per_mppt=2), 6) is None
    assert calc.capacity_issue("T1", calc.InverterData(mppt=3), 9) is None            # neznámé stringů/MPPT
    assert calc.capacity_issue("T2", calc.InverterData(mppt=1, strings_per_mppt=1), 3) == \
        "Střídač T2 má jen 1 vstup (MPPT × stringů), zapojeny 3 stringy"
    p = build_project(_spec(mppt=3, strings_per_mppt=2, strings=[12] * 8))
    st = calc.check_strings(p)
    msg = "Střídač T1 má jen 6 vstupů (MPPT × stringů), zapojeno 8 stringů"
    assert [sc.ref for sc in st if msg in sc.issues] == ["G7", "G8"]
    assert [sc.mppt for sc in st] == [0, 0, 1, 1, 2, 2, 3, 3]
    fs = [f for f in check_project(p, LibraryStore()) if f.code == "calc_string" and msg in f.text]
    assert len(fs) == 2 and all(f.severity == ERROR for f in fs)


def test_vmp_coefficient_from_gamma_and_alpha():
    m = calc.ModuleData(voc=49.5, vmp=41.5, isc=13.9, beta_voc=-0.25, gamma_pmax=-0.30, alpha_isc=0.05)
    assert not m.vmp_from_beta and abs(m.vmp_coeff - (-0.35)) < 1e-12
    assert abs(m.ump(70) - 41.5 * (1 - 0.0035 * 45)) < 1e-9 and m.uoc(-10) == 49.5 * (1 - 0.0025 * -35)
    beta_only = calc.ModuleData(voc=49.5, vmp=41.5, isc=13.9, beta_voc=-0.25, gamma_pmax=-0.30)   # jen γ → β
    assert beta_only.vmp_from_beta and beta_only.vmp_coeff == -0.25
    a = calc.ModuleData.from_attrs({"voc": "49.5", "vmp": "41.5", "beta_voc": "-0.25", "gamma_pmax": "-0,30",
                                    "alpha_isc": "0.05"})
    assert a.gamma_pmax == -0.30 and a.alpha_isc == 0.05
    # Umpp za tepla s γ − α je nižší než z β → užší okno (n_min větší); důvod „zjednodušení“ jen u β
    lim_b = calc.string_limits(calc.ModuleData(voc=49.5, vmp=41.5, isc=13.9, beta_voc=-0.25), INV, -10, 70)
    lim_g = calc.string_limits(m, INV, -10, 70)
    assert any("Umpp z β_Voc – zjednodušení" in r for r in lim_b.reasons)
    assert not any("zjednodušení" in r for r in lim_g.reasons)
    inv = calc.InverterData(u_mppt_min=600)
    assert calc.string_limits(m, inv, -10, 70).n_min > calc.string_limits(
        calc.ModuleData(voc=49.5, vmp=41.5, isc=13.9, beta_voc=-0.25), inv, -10, 70).n_min
    # kontrola projektu bere součinitele z atributů stringu; bez nich beze změny
    p, s = _fve()
    before = calc.check_strings(p)[0].umpp_hot
    g = next(e for e in s.elements if e.ref == "G1")
    g.attrs.update({"gamma_pmax": "-0.30", "alpha_isc": "0.05"})
    assert calc.check_strings(p)[0].umpp_hot == round(20 * 41.5 * (1 - 0.0035 * 45), 1) < before


def test_parse_temperature_and_invalid_meta_warning():
    for txt, val in (("-20", -20.0), ("−20", -20.0), ("-20 °C", -20.0), ("−20 °C", -20.0),
                     ("-20,5", -20.5), ("75°", 75.0), ("70 C", 70.0), (" 5 ", 5.0)):
        assert calc.parse_temperature(txt) == val, txt
    for txt in ("", None, "x", "-", "nan", "°C"):
        assert calc.parse_temperature(txt) is None, txt
    p = Project(name="T")
    p.meta.update({"pv_t_min": "−25 °C", "pv_t_max": "75"})
    assert calc.design_temperatures(p) == (-25.0, 75.0) and calc.design_temperature_issues(p) == []
    p.meta["pv_t_min"] = "mráz"
    assert calc.design_temperatures(p) == (-10.0, 75.0)
    assert calc.design_temperature_issues(p) == ["Návrhová teplota min „mráz“ není číslo – počítá se s -10 °C"]
    fs = [f for f in check_project(p, LibraryStore()) if f.code == "calc_temp"]
    assert len(fs) == 1 and fs[0].severity == WARNING and "není číslo" in fs[0].text


def test_limit_reasons_plural():
    lim = calc.string_limits(MOD, calc.InverterData(u_dc_max=180, u_mppt_min=70), -10, 70)   # 180/54,18 → 3
    assert any(r.startswith("nejvýš 3 moduly:") for r in lim.reasons)
    assert any(r.startswith("nejméně 2 moduly:") for r in lim.reasons)
    lim = calc.string_limits(MOD, calc.InverterData(u_dc_max=60), -10, 70)
    assert any(r.startswith("nejvýš 1 modul:") for r in lim.reasons)


# ---- optimizéry a režimy stringu (docs/design/optimizery.md) – fixture hodnoty, ne vestavěné CSV -----------------
MOD430 = calc.ModuleData(voc=49.5, vmp=41.5, isc=13.9, imp=13.2, beta_voc=-0.27, p_wp=430)   # Uoc(−10) 54,18 V
SE_OPT = calc.OptimizerData(p_max=440, u_in_max=60, isc_in_max=14.5, u_mppt_min=8, u_out_max=60, name="S440",
                            manufacturer="SolarEdge", compat="SolarEdge", n_min=14, n_max=50, p_string_max=13500)
SE_INV = calc.InverterData(u_dc_max=900, string_mode="fixed_voltage", u_string=750, n_opt_min=16, n_opt_max=50,
                           p_string_max=11250, mppt=1, strings_per_mppt=2, manufacturer="SolarEdge")
HW_OPT = calc.OptimizerData(p_max=450, u_in_max=80, isc_in_max=14.5, p_tol_pct=5, u_mppt_min=10, u_out_max=80,
                            name="P2", manufacturer="Huawei", compat="Huawei SUN2000")
HW_INV = calc.InverterData(u_dc_max=1100, u_mppt_min=160, u_mppt_max=1000, i_mppt_max=26, isc_mppt_max=33, mppt=2,
                           strings_per_mppt=2, string_mode="optimizer", n_opt_min=6, n_opt_max=50, manufacturer="Huawei")


def test_string_modes_and_from_attrs():
    assert calc.STRING_MODES == ("classic", "optimizer", "fixed_voltage")
    inv = calc.InverterData.from_attrs({"string_mode": "fixed_voltage", "u_string": "750", "n_opt_min": "16",
                                        "n_opt_max": "50", "p_string_max": "11250", "manufacturer": "SolarEdge"})
    assert (inv.mode, inv.u_string, inv.n_opt_min, inv.n_opt_max, inv.p_string_max) == ("fixed_voltage", 750, 16, 50, 11250)
    assert calc.InverterData.from_attrs({}).mode == "classic" and calc.InverterData.from_attrs({"string_mode": " "}).mode == "classic"
    unknown = calc.InverterData.from_attrs({"string_mode": "foo"})
    assert unknown.mode == "classic" and unknown.string_mode == "foo"
    assert calc.OptimizerData.from_attrs({"opt_p_max": "440"}) is None          # bez U max vstupu
    assert calc.OptimizerData.from_attrs({}) is None
    o = calc.OptimizerData.from_attrs({"opt_p_max": "850", "opt_u_in_max": "125", "opt_isc_in_max": "14,5",
                                       "opt_modules": "2", "opt_partial": "1", "optimizer": "P850", "opt_p_tol": "",
                                       "opt_n_min": "8", "opt_p_string_max": "5700", "opt_compat": "SolarEdge"})
    assert (o.modules, o.isc_in_max, o.partial_ok, o.name, o.p_tol_pct, o.n_min, o.p_string_max) == \
        (2, 14.5, True, "P850", 0.0, 8, 5700)
    assert o.compatible_with("SolarEdge Technologies") is True and o.compatible_with("Huawei") is False
    assert o.compatible_with("") is None and replace(o, compat="*").compatible_with("Fronius") is True
    assert replace(o, compat="").compatible_with("Fronius") is None


def test_classic_unchanged_without_optimizer():
    # bez dat optimizéru a počtu optimizérů je výstup classic stejný jako dřív (i s novými parametry)
    for n in (5, 20, 21):
        assert calc.string_issues(MOD, INV, n, 1, -10, 70) == calc.string_issues(MOD, INV, n, 1, -10, 70, None, None)
    assert calc.string_issues(MOD, INV, 20) == []
    assert calc.string_limits(MOD, INV, -10, 70).step == 1 and calc.string_limits(MOD, INV).mode == "classic"


def test_optimizer_input_issues():
    assert calc.optimizer_issues(MOD430, SE_OPT, -10, 70, "SolarEdge") == []
    hot = calc.optimizer_issues(MOD430, replace(SE_OPT, u_in_max=50), -10, 70)
    assert hot == ["Uoc modulu při -10 °C 54.2 V > Uin max optimizéru 50 V"] and not calc.is_warning(hot[0])
    isc = calc.optimizer_issues(MOD430, replace(SE_OPT, isc_in_max=13.5), -10, 70)   # Isc STC bez 1,25
    assert isc == ["Isc modulu 13.9 A > Isc max vstupu optimizéru 13.5 A"]
    assert calc.optimizer_issues(MOD430, replace(SE_OPT, isc_in_max=14.0), -10, 70) == []   # 1,25·Isc by neprošlo
    # výkon: nad P max v toleranci výrobce = varování, nad tolerancí = chyba
    tol = calc.optimizer_issues(replace(MOD430, p_wp=460), HW_OPT, -10, 70, "Huawei")
    assert tol == ["P modulu 460 W > P max optimizéru 450 W – v toleranci výrobce 5 %"] and calc.is_warning(tol[0])
    over = calc.optimizer_issues(replace(MOD430, p_wp=480), HW_OPT, -10, 70, "Huawei")
    assert over == ["P modulu 480 W > P max optimizéru 450 W + 5 %"] and not calc.is_warning(over[0])
    assert not calc.is_warning(calc.optimizer_issues(replace(MOD430, p_wp=450.5), SE_OPT, -10, 70)[0])   # tol. 0
    low = calc.optimizer_issues(MOD430, replace(SE_OPT, u_mppt_min=40), -10, 70)
    assert low == ["Umpp modulu při 70 °C 36.5 V < Umppt min optimizéru 40 V – omezení výkonu"] and calc.is_warning(low[0])
    comp = calc.optimizer_issues(MOD430, SE_OPT, -10, 70, "Huawei")
    assert len(comp) == 1 and "kompatibilní" in comp[0] and calc.is_warning(comp[0])
    miss = calc.optimizer_issues(MOD430, replace(SE_OPT, isc_in_max=None), -10, 70)
    assert miss == ["chybí údaj Isc max vstupu optimizéru"] and calc.is_warning(miss[0])
    # 2 moduly na optimizér: Uoc a P dvou modulů
    two = calc.optimizer_issues(MOD430, replace(SE_OPT, modules=2, u_in_max=100, p_max=850), -10, 70)
    assert two == ["Uoc 2 modulů při -10 °C 108.4 V > Uin max optimizéru 100 V",
                   "P 2 modulů 860 W > P max optimizéru 850 W"]


def test_fixed_voltage_mode():
    lim = calc.string_limits(MOD430, SE_INV, -10, 70, SE_OPT)
    # nejpřísnější pravidla: min 16 (střídač) ⊃ 14 (optimizér), P ≤ 11 250 W → ⌊11250 / 430⌋ = 26
    assert (lim.n_min, lim.n_max, lim.step, lim.n_opt, lim.mode, lim.n_par_max) == (16, 26, 1, (16, 50), "fixed_voltage", 2)
    assert lim.reasons[0] == "pevné napětí 750 V – Uoc·n se nekontroluje"
    assert any("P stringu ≤ 11250 W → nejvýš 26 modulů" in r for r in lim.reasons)
    for n in range(lim.n_min, lim.n_max + 1):                     # meze = string_issues
        assert calc.string_issues(MOD430, SE_INV, n, 2, -10, 70, SE_OPT) == [], n
    assert calc.string_issues(MOD430, SE_INV, 27, 1, -10, 70, SE_OPT) == ["P stringu 11610 W > max 11250 W"]
    assert calc.string_issues(MOD430, SE_INV, 15, 1, -10, 70, SE_OPT) == ["15 optimizérů ve stringu < min 16"]
    # Uoc·n, okno MPPT ani proudy se nekontrolují (40 modulů = 2167 V Uoc, ale P stringu je jediná chyba)
    assert calc.string_issues(replace(MOD430, p_wp=200), SE_INV, 40, 2, -10, 70, SE_OPT) == []
    # optimizér na každém modulu
    msg = calc.string_issues(MOD430, SE_INV, 20, 1, -10, 70, SE_OPT, n_opt=18)
    assert msg == ["20 modulů, 18 optimizérů × 1 – optimizér musí být na každém modulu"] and not calc.is_warning(msg[0])
    # věrohodnost pevného napětí, chybějící údaje, string bez optimizérů
    bad = calc.string_issues(MOD430, replace(SE_INV, u_dc_max=600), 20, 1, -10, 70, SE_OPT)
    assert bad == ["pevné napětí stringu 750 V > Umax střídače 600 V – nevěrohodné údaje střídače"]
    bare = calc.InverterData(string_mode="fixed_voltage")
    msgs = calc.string_issues(MOD430, bare, 20, 1, -10, 70, replace(SE_OPT, n_min=None, n_max=None, p_string_max=None))
    assert msgs == ["chybí údaj pevné napětí stringu střídače",
                    "chybí údaj rozmezí počtu optimizérů ve stringu (doplňte z artiklu)",
                    "chybí údaj max. výkon stringu (doplňte z artiklu)"] and all(map(calc.is_warning, msgs))
    none = calc.string_issues(MOD430, SE_INV, 20, 1, -10, 70)
    assert none == ["pevné napětí: string bez optimizérů – optimizér musí být na každém modulu"]
    assert not calc.is_warning(none[0])


def test_fixed_voltage_step_two():
    p850 = calc.OptimizerData(p_max=850, u_in_max=125, isc_in_max=14.5, modules=2, compat="SolarEdge")
    inv = replace(SE_INV, n_opt_min=8, n_opt_max=25)
    m425 = replace(MOD430, p_wp=425)
    lim = calc.string_limits(m425, inv, -10, 70, p850)
    # n_min = 8·2, n_max = min(25·2, ⌊11250 / 425 / 2⌋·2 = 26), délky po 2
    assert (lim.n_min, lim.n_max, lim.step, lim.n_opt) == (16, 26, 2, (8, 25))
    for n in range(16, 27, 2):
        assert calc.string_issues(m425, inv, n, 1, -10, 70, p850) == [], n
    # 2:1 a lichý počet modulů → chyba (⌈21/2⌉ = 11 optimizérů = 22 míst)
    assert calc.string_issues(m425, inv, 21, 1, -10, 70, p850) == [
        "21 modulů, 11 optimizérů × 2 – optimizér musí být na každém modulu"]
    assert calc.string_issues(m425, inv, 21, 1, -10, 70, p850, n_opt=10) == [
        "21 modulů, 10 optimizérů × 2 – optimizér musí být na každém modulu"]
    # návrh stringů po násobcích 2: kapacita střídače 1 MPPT × 2 stringy
    assert calc.propose_strings(60, 1, lim, inv) == ([[26, 26]], 8)
    assert calc.propose_strings(61, 1, lim, replace(inv, mppt=None)) == ([[20, 20, 20]], 1)   # lichý zbytek
    assert calc.propose_strings(64, 1, lim, replace(inv, mppt=None)) == ([[22, 22, 20]], 0)
    assert calc.propose_strings(10, 1, lim, inv) == ([[]], 10)    # méně než n_min
    # step 1 beze změny (stávající chování)
    assert calc.propose_strings(41, 1, calc.StringLimits(18, 20, 2, step=1), INV) == ([[20, 20]], 1)


def test_optimizer_mode():
    m = MOD430
    assert calc.string_issues(m, HW_INV, 20, 1, -10, 70, HW_OPT) == []
    # počet optimizérů pod minimem střídače
    assert calc.string_issues(m, HW_INV, 5, 1, -10, 70, HW_OPT) == ["5 optimizérů ve stringu < min 6"]
    # smíšení bez opt_partial → chyba; s ním OK
    mixed = calc.string_issues(m, HW_INV, 20, 1, -10, 70, HW_OPT, n_opt=18)
    assert mixed == ["smíšení optimalizovaných a neoptimalizovaných modulů (18 z 20) není dovoleno"]
    assert not calc.is_warning(mixed[0])
    assert calc.string_issues(m, HW_INV, 20, 1, -10, 70, replace(HW_OPT, partial_ok=True), n_opt=18) == []
    # klasické kontroly platí dál (Uoc proti Umax střídače, Umppt min – rozhodnutí orchestrátora 1)
    assert any("Umax střídače" in x for x in calc.string_issues(m, HW_INV, 21, 1, -10, 70, HW_OPT))
    assert calc.string_issues(m, HW_INV, 4, 1, -10, 70, replace(HW_OPT, n_min=None),
                              ) == ["Umpp při 70 °C 145.8 V < Umppt min 160 V", "4 optimizéry ve stringu < min 6"]
    # P stringu ze střídače
    assert calc.string_issues(m, replace(HW_INV, p_string_max=8000), 20, 1, -10, 70, HW_OPT) == [
        "P stringu 8600 W > max 8000 W"]
    # starý string bez dat optimizéru: jen varování, počet se zkontroluje
    old = calc.string_issues(m, HW_INV, 20, 1, -10, 70, None, n_opt=20)
    assert old == ["optimizér bez parametrů (doplňte z katalogu)"] and calc.is_warning(old[0])
    assert calc.string_issues(m, HW_INV, 5, 1, -10, 70, None, n_opt=5)[-1] == "5 optimizérů ve stringu < min 6"
    no_opt = calc.string_issues(m, HW_INV, 20, 1, -10, 70)
    assert no_opt == ["string nemá optimizéry (režim stringů s optimizéry)"] and calc.is_warning(no_opt[0])


def test_optimizer_mode_limits_with_output_cap():
    inv = replace(HW_INV, n_opt_min=None, n_opt_max=None, u_mppt_max=1000)
    classic = calc.string_limits(MOD430, replace(inv, string_mode=""), -10, 70)
    assert classic.n_max == 20                                    # 1100 / 54,18
    capped = calc.OptimizerData(p_max=450, u_in_max=80, isc_in_max=14.5, u_out_max=50)
    lim = calc.string_limits(MOD430, inv, -10, 70, capped)
    assert lim.mode == "optimizer" and lim.n_max == 22            # 1100 / 50 (U výstupu optimizéru)
    for n in (21, 22):
        assert calc.string_issues(MOD430, inv, n, 1, -10, 70, capped) == [], n
    assert any("Umax střídače" in x for x in calc.string_issues(MOD430, inv, 23, 1, -10, 70, capped))
    assert any("Umax střídače" in x for x in calc.string_issues(MOD430, replace(inv, string_mode=""), 21, 1, -10, 70,
                                                                 capped))   # classic: cap neplatí
    # meze z počtu optimizérů a výkonu
    lim = calc.string_limits(MOD430, replace(HW_INV, n_opt_min=8, n_opt_max=15, p_string_max=6000), -10, 70, HW_OPT)
    assert (lim.n_min, lim.n_max, lim.n_opt) == (8, 13, (8, 15))  # ⌊6000 / 430⌋ = 13
    for n in range(lim.n_min, lim.n_max + 1):
        assert calc.string_issues(MOD430, replace(HW_INV, n_opt_min=8, n_opt_max=15, p_string_max=6000), n, 1,
                                  -10, 70, HW_OPT) == [], n


def test_unknown_mode_and_classic_with_optimizer_data():
    inv = replace(INV, string_mode="foo")
    msgs = calc.string_issues(MOD, inv, 20, 1, -10, 70)
    assert msgs == ["neznámý režim stringu „foo“ – počítá se klasicky"] and calc.is_warning(msgs[0])
    assert calc.string_limits(MOD, inv, -10, 70).reasons[0] == "neznámý režim stringu „foo“ – počítá se klasicky"
    # classic + optimizér (Tigo): kontrola vstupu optimizéru, napětí stringu dávají moduly
    tigo = calc.OptimizerData(p_max=475, u_in_max=50, isc_in_max=15, compat="*")
    assert calc.string_issues(MOD430, INV, 20, 1, -10, 70, tigo) == [
        "Uoc modulu při -10 °C 54.2 V > Uin max optimizéru 50 V"]
    old = calc.string_issues(MOD, INV, 20, 1, -10, 70, None, n_opt=20)
    assert old == ["optimizér bez parametrů (doplňte z katalogu)"]


def test_parallel_issues():
    assert calc.parallel_issues([(20, MOD, "")]) == []
    assert calc.parallel_issues([(20, MOD, "J"), (20, MOD, "J")]) == []
    assert calc.parallel_issues([(20, MOD, ""), (18, MOD, "")]) == [
        "nestejná délka stringů na MPPT (20 a 18 modulů, ΔUmpp 10 %)"]
    assert calc.parallel_issues([(20, MOD, ""), (20, replace(MOD, voc=50.1), "")]) == ["různé moduly stringů na MPPT"]
    # artikl rozhoduje před parametry
    a, b = replace(MOD, component_id="a"), replace(MOD, component_id="b")
    assert calc.parallel_issues([(20, a, ""), (20, b, "")]) == ["různé moduly stringů na MPPT"]
    assert calc.parallel_issues([(20, a, ""), (20, replace(a, voc=50), "")]) == []
    assert calc.parallel_issues([(20, MOD, "J"), (20, MOD, "JV"), (20, MOD, "")]) == [
        "různá orientace stringů na MPPT (J, JV)"]
    assert calc.parallel_issues([(20, MOD, "J"), (20, MOD, "")]) == []     # orientace jen u vyplněných
    assert calc.parallel_issues([(20, None, ""), (18, None, ""), (19, None, "")]) == [
        "nestejná délka stringů na MPPT (20, 19 a 18 modulů, ΔUmpp 10 %)"]
    assert all(calc.is_warning(x) for x in calc.parallel_issues([(20, a, "J"), (18, b, "Z")]))


def test_check_strings_parallel_and_modes():
    from envocad.generate import build_project
    p = build_project({**_spec(strings_per_mppt=2), "inverters": [{**_spec()["inverters"][0], "strings_per_mppt": 2,
                                                                    "strings": [20, 18, 18]}]})
    st = {sc.ref: sc for sc in calc.check_strings(p)}
    assert st["G1"].mppt == st["G2"].mppt == 0 and st["G3"].mppt == 1
    assert st["G1"].issues == st["G2"].issues == ["nestejná délka stringů na MPPT (20 a 18 modulů, ΔUmpp 10 %)"]
    assert st["G3"].ok and st["G1"].mode == "classic"
    fs = [f for f in check_project(p, LibraryStore()) if f.code == "calc_string"]
    assert len(fs) == 2 and all(f.severity == WARNING for f in fs)
    # orientace ze stringu
    g = {e.ref: e for e in p.sheets[0].elements if e.symbol_id == "fve.pv_string"}
    g["G2"].attrs["n_modules"] = "20"
    g["G1"].attrs["orientation"], g["G2"].attrs["orientation"] = "J", "Z"
    assert calc.check_strings(p)[0].issues == ["různá orientace stringů na MPPT (J, Z)"]
    # pevné napětí: paralelní stringy se neporovnávají, Uoc·n se nekontroluje; data optimizéru ze stringu
    t = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.inverter")
    t.attrs.update({"string_mode": "fixed_voltage", "u_string": "750", "n_opt_min": "16", "n_opt_max": "50",
                    "p_string_max": "11250", "u_dc_max": "900"})
    for e in g.values():
        e.attrs.update({"p_module": "430", "opt_p_max": "440", "opt_u_in_max": "60", "opt_isc_in_max": "14.5",
                        "n_optimizers": e.attrs["n_modules"]})
    st = {sc.ref: sc for sc in calc.check_strings(p)}
    assert all(sc.ok for sc in st.values()), [sc.issues for sc in st.values()]
    assert (st["G1"].mode, st["G1"].n_opt, st["G1"].p_string, st["G1"].u_string, st["G1"].p_string_max,
            st["G1"].n_opt_min, st["G1"].n_opt_max) == ("fixed_voltage", 20, 8600, 750, 11250, 16, 50)
    from envocad.export import reports
    _, rows = reports.calculations(p, LibraryStore())
    assert rows[0][2] == "20 modulů, 20 optimizérů, pevné U 750 V, P stringu 8600 / 11250 W"
    assert rows[0][3] == "T1: optimizérů 16–50, P stringu ≤ 11250 W" and rows[0][4] == "OK"
