"""Opravy z review větve optimizéry (docs/design/optimizery.md) – headless, jen fixture hodnoty (ne vestavěná CSV)."""
import logging
from dataclasses import replace

import pytest

from envocad.model import calc

MOD = calc.ModuleData(voc=49.5, vmp=41.5, isc=13.9, imp=13.2, beta_voc=-0.27, p_wp=430)      # Uoc(−10) 54,18 V
OPT = calc.OptimizerData(p_max=440, u_in_max=60, isc_in_max=14.5, u_mppt_min=8, u_out_max=60, name="S440",
                         manufacturer="SolarEdge", compat="SolarEdge", n_min=14, n_max=50, p_string_max=13500)
FIXED = calc.InverterData(u_dc_max=900, string_mode="fixed_voltage", u_string=750, n_opt_min=16, n_opt_max=50,
                          p_string_max=11250, mppt=1, strings_per_mppt=2, manufacturer="SolarEdge")
HW_OPT = calc.OptimizerData(p_max=450, u_in_max=80, isc_in_max=14.5, p_tol_pct=5, u_mppt_min=10, u_out_max=80,
                            name="P2", manufacturer="Huawei", compat="Huawei SUN2000")
HW_INV = calc.InverterData(u_dc_max=1100, u_mppt_min=160, u_mppt_max=1000, i_mppt_max=26, isc_mppt_max=33, mppt=2,
                           strings_per_mppt=2, string_mode="optimizer", n_opt_min=6, n_opt_max=50, manufacturer="Huawei")
CLASSIC = calc.InverterData(u_dc_max=1100, u_mppt_min=200, u_mppt_max=1000, i_mppt_max=30, mppt=3, strings_per_mppt=2)


# ---- 2: návrh stringů – stejné délky na jednom MPPT, kde to jde --------------------------------------------------
def _mixed_mppts(groups: list[int], inv: calc.InverterData, mod=MOD) -> int:
    by: dict[int, list[int]] = {}
    for n, m in zip(groups, calc.assign_mppt(len(groups), inv), strict=True):
        by.setdefault(m, []).append(n)
    return sum(bool(calc.parallel_issues([(n, mod, "") for n in ns])) for ns in by.values())


@pytest.mark.parametrize("mppt, spm, n_max", [(2, 3, 20), (2, 2, 20), (3, 2, 18), (4, 2, 22), (2, 3, 17)])
def test_propose_strings_equal_lengths_per_mppt(mppt, spm, n_max):
    inv = calc.InverterData(mppt=mppt, strings_per_mppt=spm)
    lim = calc.StringLimits(8, n_max, spm)
    for total in range(30, mppt * spm * n_max + 1):
        (g,), left = calc.propose_strings(total, 1, lim, inv)
        assert sum(g) + left == total and all(lim.n_min <= n <= lim.n_max for n in g), (total, g)
        sizes = [calc.assign_mppt(len(g), inv).count(m) for m in set(calc.assign_mppt(len(g), inv))]
        # homogenní rozdělení existuje ⇔ součet jde složit z délek po MPPT v rozmezí 2 jednotek
        feasible = any(sum(s * x for s, x in zip(sizes, xs, strict=True)) == sum(g)
                       for lo in range(lim.n_min, lim.n_max + 1)
                       for xs in _combos(len(sizes), lo, min(lo + 2, lim.n_max)))
        assert _mixed_mppts(g, inv) <= (0 if feasible else 1), (total, g)


def _combos(k: int, lo: int, hi: int):
    if k == 0:
        yield ()
        return
    for x in range(lo, hi + 1):
        for rest in _combos(k - 1, lo, hi):
            yield (x, *rest)


def test_propose_strings_review_case_and_assistant_flow():
    inv = calc.InverterData(mppt=2, strings_per_mppt=3)
    # 98 modulů do stringů ≤ 20: 5 stringů (3 + 2 na MPPT) → 20,20,20 | 19,19 – žádné varování
    (g,), left = calc.propose_strings(98, 1, calc.StringLimits(8, 20, 3), inv)
    assert (g, left) == ([20, 20, 20, 19, 19], 0)
    assert _mixed_mppts(g, inv) == 0
    # 96: dřív 20,19,19 | 19,19 (MPPT 1 smíšený), teď délky různých MPPT o 2 → bez varování
    (g,), _ = calc.propose_strings(96, 1, calc.StringLimits(8, 20, 3), inv)
    assert g == [20, 20, 20, 18, 18] and _mixed_mppts(g, inv) == 0
    # 98 do stringů ≤ 17 = 6 stringů 3 + 3: 98 není dělitelné 3 → smíšený nejvýš jeden MPPT (dřív i teď)
    (g,), _ = calc.propose_strings(98, 1, calc.StringLimits(8, 17, 3), inv)
    assert sorted(g) == [16, 16, 16, 16, 17, 17] and _mixed_mppts(g, inv) == 1
    # průchod jako asistent: string_limits → propose → assign_mppt → string_issues + parallel_issues
    m = calc.ModuleData(voc=49.5, vmp=41.5, isc=10, imp=9.5, beta_voc=-0.27)
    inv2 = replace(CLASSIC, mppt=2, strings_per_mppt=3, isc_mppt_max=40)
    lim = calc.string_limits(m, inv2, -10, 70)
    (g,), left = calc.propose_strings(98, 1, lim, inv2)
    assert left == 0 and _mixed_mppts(g, inv2, m) == 0, g
    n_par = calc.mppt_groups(calc.assign_mppt(len(g), inv2))
    assert all(calc.string_issues(m, inv2, n, k, -10, 70) == [] for n, k in zip(g, n_par, strict=True))


def test_propose_strings_keeps_port_order_and_fixed_voltage():
    # pořadí vstupů (a tedy vodičů) se nemění – mění se jen délky; pevné napětí beze změny
    inv = calc.InverterData(mppt=2, strings_per_mppt=2)
    assert calc.string_ports(4, inv) == [1, 2, 3, 4]
    assert calc.propose_strings(70, 1, calc.StringLimits(8, 20, 2), inv) == ([[18, 18, 17, 17]], 0)
    lim = calc.string_limits(MOD, FIXED, -10, 70, OPT)
    assert calc.propose_strings(41, 1, lim, FIXED) == ([[21, 20]], 0)


# ---- 6: závažnost – šablony celého znění ------------------------------------------------------------------------
WARNINGS = [
    "chybí počet modulů nebo Uoc modulu",
    "string není propojen se střídačem",
    "neznámý režim stringu „foo“ – počítá se klasicky",
    "Impp 2× 13.2 A = 26.4 A > Imax MPPT 26 A – omezení výkonu",
    "střídač nemá zadané Umax / rozsah MPPT (doplňte z artiklu)",
    "Umpp modulu při 70 °C 36.5 V < Umppt min optimizéru 40 V – omezení výkonu",
    "Umpp 2 modulů při -10 °C 92.5 V > Umppt max optimizéru 80 V – omezení výkonu",
    "chybí údaj Isc max vstupu optimizéru",
    "P modulu 460 W > P max optimizéru 450 W – v toleranci výrobce 5 %",
    "optimizér S440 není uveden jako kompatibilní se střídačem Huawei (kompatibilita: SolarEdge)",
    "chybí údaj pevné napětí stringu střídače",
    "optimizér bez parametrů (doplňte z katalogu)",
    "string nemá optimizéry (režim stringů s optimizéry)",
    "chybí údaj rozmezí počtu optimizérů ve stringu (doplňte z artiklu)",
    "chybí údaj max. výkon stringu (doplňte z artiklu)",
    "neplatný počet modulů na optimizér „3“ (povoleno 1 nebo 2) – počítá se s 1",
    "nestejná délka stringů na MPPT (20 a 18 modulů, ΔUmpp 10 %)",
    "různé moduly stringů na MPPT",
    "různá orientace stringů na MPPT (J, Z)",
]
ERRORS = [
    "Uoc při -10 °C 1192.0 V > Umax střídače 1100 V",
    "Uoc při -10 °C 1192.0 V > Umax systému modulu 1000 V",
    "Umpp při 70 °C 145.8 V < Umppt min 160 V",
    "Umpp při -10 °C 1050.1 V > Umppt max 1000 V (mimo rozsah sledování)",
    "Isc 3× 13.9 A = 41.7 A > Isc max MPPT 40 A",
    "1,25·Isc 17.4 A > Imax vstupu 12 A",
    "Uoc modulu při -10 °C 54.2 V > Uin max optimizéru 50 V",
    "Isc modulu 15 A > Isc max vstupu optimizéru 14.5 A",
    "P modulu 480 W > P max optimizéru 450 W + 5 %",
    "pevné napětí stringu 750 V > Umax střídače 600 V – nevěrohodné údaje střídače",
    "pevné napětí stringu 750 V > Umax systému modulu 600 V",
    "Umax střídače 900 V > Umax systému modulu 800 V",
    "15 optimizérů ve stringu < min 16",
    "51 optimizérů ve stringu > max 50",
    "P stringu 11610 W > max 11250 W",
    "20 modulů, 18 optimizérů × 1 – optimizér musí být na každém modulu",
    "pevné napětí: string bez optimizérů – optimizér musí být na každém modulu",
    "smíšení optimalizovaných a neoptimalizovaných modulů (18 z 20) není dovoleno",
    "Střídač T1 má jen 6 vstupů (MPPT × stringů), zapojeno 8 stringů",
    # dřív by podřetězec „není“ / „chybí“ / „nemá“ udělal z chyby varování
    "modul není pro tento střídač – nemá certifikát, chybí schválení",
]


@pytest.mark.parametrize("msg", WARNINGS)
def test_is_warning_templates(msg):
    assert calc.is_warning(msg)


@pytest.mark.parametrize("msg", ERRORS)
def test_is_error_templates(msg):
    assert not calc.is_warning(msg)


def test_generated_messages_classified():
    """Hlášky skutečně vygenerované výpočty mají závažnost podle seznamů výše (šablona a text se nerozešly)."""
    got = set()
    got |= set(calc.string_issues(calc.ModuleData(voc=0, vmp=0, isc=0), None, 0))
    got |= set(calc.string_issues(MOD, calc.InverterData(string_mode="foo"), 20))
    got |= set(calc.string_issues(MOD, HW_INV, 20, 1, -10, 70))
    got |= set(calc.string_issues(MOD, HW_INV, 20, 1, -10, 70, None, n_opt=20))
    got |= set(calc.string_issues(MOD, calc.InverterData(string_mode="fixed_voltage"), 20, 1, -10, 70,
                                  replace(OPT, isc_in_max=None, n_min=None, n_max=None, p_string_max=None)))
    got |= set(calc.optimizer_issues(replace(MOD, p_wp=460), replace(HW_OPT, u_mppt_min=40, u_mppt_max=30,
                                                                     bad_modules="3"), -10, 70, "SolarEdge"))
    got |= set(calc.parallel_issues([(20, MOD, "J"), (18, replace(MOD, voc=50), "Z")]))
    for msg in got:
        assert msg in WARNINGS or any(p.fullmatch(msg) for p in calc.WARNING_PATTERNS), msg
        assert calc.is_warning(msg), msg
    errors = set()
    errors |= set(calc.string_issues(MOD, HW_INV, 21, 1, -10, 70, HW_OPT))
    errors |= set(calc.string_issues(MOD, HW_INV, 20, 1, -10, 70, HW_OPT, n_opt=18))
    errors |= set(calc.string_issues(MOD, FIXED, 15, 1, -10, 70, OPT))
    errors |= set(calc.string_issues(MOD, FIXED, 20, 1, -10, 70))
    errors |= set(calc.optimizer_issues(replace(MOD, isc=15, p_wp=480), replace(HW_OPT, u_in_max=50), -10, 70))
    errors.add(calc.capacity_issue("T1", CLASSIC, 8))
    assert len(errors) >= 7
    for msg in errors:
        assert not calc.is_warning(msg), msg


# ---- 8: neplatný počet modulů na optimizér ----------------------------------------------------------------------
def test_invalid_modules_per_optimizer_warns():
    a = {"opt_p_max": "440", "opt_u_in_max": "60", "opt_isc_in_max": "14.5", "opt_modules": "3"}
    opt = calc.OptimizerData.from_attrs(a)
    assert opt.modules == 1 and opt.bad_modules == "3"
    msgs = calc.optimizer_issues(MOD, opt, -10, 70)
    assert msgs[0] == "neplatný počet modulů na optimizér „3“ (povoleno 1 nebo 2) – počítá se s 1"
    assert calc.is_warning(msgs[0])
    for good, mpo in (("2", 2), ("1", 1), ("", 1), ("2.0", 2)):
        o = calc.OptimizerData.from_attrs({**a, "opt_modules": good})
        assert (o.modules, o.bad_modules) == (mpo, ""), good
    assert calc.OptimizerData.from_attrs({**a, "opt_modules": "0,5"}).bad_modules == "0,5"


# ---- 9: poznámka o U max výstupu jen když omezuje ---------------------------------------------------------------
def test_output_cap_note_only_when_capping():
    inv = replace(HW_INV, n_opt_min=None, n_opt_max=None)
    capping = calc.string_limits(MOD, inv, -10, 70, replace(HW_OPT, u_out_max=50))   # 54,2 V > 50 V
    assert any("U výstupu optimizéru ≤ 50 V" in r for r in capping.reasons)
    free = calc.string_limits(MOD, inv, -10, 70, HW_OPT)                             # 54,2 V ≤ 80 V
    assert not any("U výstupu optimizéru" in r for r in free.reasons)
    assert free.n_max == calc.string_limits(MOD, inv, -10, 70, replace(HW_OPT, u_out_max=None)).n_max


# ---- 10: krok z ručního „ks na modul“ ---------------------------------------------------------------------------
def test_step_from_manual_per_module():
    assert [calc.modules_per_optimizer(x) for x in ("1", "0.5", "0,5", 0.5, "0.3", "", None, "x", "2")] == [
        1, 2, 2, 2, None, None, None, None, None]
    bare = replace(FIXED, n_opt_min=8, n_opt_max=25)
    lim = calc.string_limits(MOD, bare, -10, 70, None, mpo=2)
    assert lim.step == 2 and lim.n_min == 16 and lim.n_max % 2 == 0
    (g,), _left = calc.propose_strings(61, 1, lim, bare)
    assert g and all(n % 2 == 0 for n in g)
    assert calc.string_limits(MOD, bare, -10, 70, None).step == 1                 # bez mpo beze změny
    # data optimizéru mají přednost před ručním mpo
    assert calc.string_limits(MOD, bare, -10, 70, OPT, mpo=2).step == 1


# ---- 13: mpo · Umpp(t_min) nad Umppt max optimizéru ------------------------------------------------------------
def test_optimizer_mppt_max_power_limit():
    p850 = calc.OptimizerData(p_max=850, u_in_max=125, isc_in_max=14.5, modules=2, u_mppt_max=80)
    msgs = calc.optimizer_issues(replace(MOD, p_wp=425), p850, -10, 70)
    assert msgs == ["Umpp 2 modulů při -10 °C 90.8 V > Umppt max optimizéru 80 V – omezení výkonu"]
    assert calc.is_warning(msgs[0])
    assert calc.optimizer_issues(replace(MOD, p_wp=425), replace(p850, u_mppt_max=105), -10, 70) == []
    assert calc.OptimizerData.from_attrs({"opt_p_max": "850", "opt_u_in_max": "125",
                                          "opt_u_mppt_max": "105"}).u_mppt_max == 105


# ---- 15: pevné napětí – Umax systému modulu proti max(pevné U, Umax střídače) ----------------------------------
def test_fixed_voltage_module_u_sys_max_vs_inverter_umax():
    m = replace(MOD, u_sys_max=800)
    assert calc.string_issues(m, FIXED, 20, 1, -10, 70, OPT) == ["Umax střídače 900 V > Umax systému modulu 800 V"]
    assert calc.string_issues(replace(m, u_sys_max=1000), FIXED, 20, 1, -10, 70, OPT) == []
    # Umax střídače neznámé → pevné napětí
    assert calc.string_issues(replace(m, u_sys_max=700), replace(FIXED, u_dc_max=None), 20, 1, -10, 70, OPT) == [
        "pevné napětí stringu 750 V > Umax systému modulu 700 V"]
    # pevné napětí neznámé → Umax střídače (a chybějící údaj)
    assert calc.string_issues(m, replace(FIXED, u_string=None), 20, 1, -10, 70, OPT) == [
        "chybí údaj pevné napětí stringu střídače", "Umax střídače 900 V > Umax systému modulu 800 V"]


# ---- 11, 12: výkaz Výpočty a TZ ---------------------------------------------------------------------------------
def _fixed_project(strings):
    from envocad.generate import build_project
    return build_project({"optimizer": {"type": "S440", "per_module": 1},
                          "inverters": [{"ref": "T1", "type": "SE", "p_ac": 5, "u_dc_max": 900, "strings": strings,
                                         "string_mode": "fixed_voltage", "u_string": 380, "n_opt_min": 1,
                                         "n_opt_max": 30, "p_string_max": 6800}]})


def test_reports_plural_optimizers():
    from envocad.export import reports
    from envocad.library.store import LibraryStore
    _, rows = reports.calculations(_fixed_project([1, 3]), LibraryStore())
    assert rows[0][2].startswith("1 modul, 1 optimizér, pevné U 380 V")
    assert rows[1][2].startswith("3 moduly, 3 optimizéry, pevné U 380 V")


def test_tz_fixed_voltage_separate_table(tmp_path):
    from docx import Document

    from envocad.export.tz_export import export_tz_docx
    from envocad.library.store import LibraryStore
    out = tmp_path / "tz.docx"
    export_tz_docx(_fixed_project([10]), LibraryStore(), out)
    heads = [[c.text for c in t.rows[0].cells] for t in Document(out).tables]
    fixed = next(h for h in heads if "Pevné napětí" in h)
    assert "1,25·Isc [A]" not in fixed and "Optimizérů min–max" in fixed
    assert not any("1,25·Isc [A]" in h for h in heads)          # jen pevné napětí → klasická tabulka chybí


def test_generator_logs_per_module_mismatch(tmp_path, caplog, monkeypatch):
    from envocad import generate
    from envocad.library.components import Component

    comp = Component(id="t-opt2", manufacturer="Test", part_number="TO-850", name="T", category="optimizer",
                     symbol_id="", params={"p_max_w": "850", "u_in_max_v": "125", "modules_per_optimizer": "2"})

    class Lib:
        def component(self, cid):
            return comp if cid == comp.id else None

    monkeypatch.setattr(generate, "_lib", lambda: Lib())
    with caplog.at_level(logging.WARNING, logger="envocad.generate"):
        out, c = generate._apply_optimizer_component({"type": "", "per_module": 1, "component_id": "t-opt2"})
    assert c is comp and out["per_module"] == 0.5 and out["type"] == "TO-850"
    assert any("per_module 1" in r.getMessage() for r in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="envocad.generate"):
        generate._apply_optimizer_component({"type": "", "per_module": 0.5, "component_id": "t-opt2"})
    assert not caplog.records
