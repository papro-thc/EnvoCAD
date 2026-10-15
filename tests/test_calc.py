"""Výpočty z modelu (bez Qt)."""

from envocad.library.store import LibraryStore
from envocad.model import calc
from envocad.model.checks import check_project
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
