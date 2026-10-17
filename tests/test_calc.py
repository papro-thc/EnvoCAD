"""Výpočty z modelu (bez Qt)."""

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
