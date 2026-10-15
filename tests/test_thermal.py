"""IEC TR 60890 – výpočet oteplení rozvaděče."""
from itertools import pairwise

from envocad.model.project import Element, Sheet
from envocad.model.thermal import (
    C_LARGE_NO_VENTS,
    C_SMALL,
    K_LARGE_NO_VENTS,
    K_SMALL,
    c_factor,
    cooling_area,
    d_factor,
    k_factor,
    temperature_rise,
)


def _sheet(w, h, dpt, mounting, p_w):
    s = Sheet(kind="switchboard")
    s.layout.params = {"width_mm": str(w), "height_mm": str(h), "depth_mm": str(dpt), "mounting": mounting}
    s.elements = [Element(symbol_id="fve.breaker_mcb", attrs={"p_loss_w": str(p_w)})]
    return s


def test_tables_monotonic():
    for t in (K_LARGE_NO_VENTS, K_SMALL):
        assert all(a[0] < b[0] and a[1] > b[1] for a, b in pairwise(t))
    for t in (C_LARGE_NO_VENTS, C_SMALL):
        assert all(a[0] < b[0] and a[1] <= b[1] for a, b in pairwise(t))
    assert k_factor(0.5) > k_factor(1.0) > k_factor(2.0) > k_factor(8.0)
    assert abs(k_factor(1.75) - (0.45 + 0.35) / 2) < 1e-9  # interpolace


def test_b_factors():
    # nástěnná 600×800×250: horní 1,4; přední 0,9; zadní (u stěny) 0,5; boky 0,9; spodní 0
    ae = cooling_area(600, 800, 250, "nástěnná")
    exp = 0.6 * 0.25 * 1.4 + 0.6 * 0.8 * 0.9 + 0.6 * 0.8 * 0.5 + 2 * 0.8 * 0.25 * 0.9
    assert abs(ae - exp) < 1e-9


def test_factors():
    assert d_factor(0) == 1.0 and d_factor(2) > d_factor(0) and d_factor(5) == d_factor(3) == 1.3
    for ae, h, w in ((0.5, 600, 400), (0.9, 800, 600), (2.0, 2000, 800), (6.0, 2000, 1200)):
        assert c_factor(ae, h, w, 400) >= 1.0


def test_monotonic_rise():
    small = temperature_rise(_sheet(600, 800, 250, "nástěnná", 150), rdf=1.0, wiring_pct=0)
    big = temperature_rise(_sheet(1000, 1400, 300, "nástěnná", 150), rdf=1.0, wiring_pct=0)
    assert big.ae_m2 > small.ae_m2 and big.dt_mid_k < small.dt_mid_k
    hot = temperature_rise(_sheet(600, 800, 250, "nástěnná", 300), rdf=1.0, wiring_pct=0)
    assert hot.dt_mid_k > small.dt_mid_k
    s = _sheet(800, 2000, 600, "volně stojící", 600)
    r0 = temperature_rise(s, rdf=1.0, partitions=0)
    r2 = temperature_rise(s, rdf=1.0, partitions=2)
    assert r0.ae_m2 > 1.25 and r0.x == 0.804 and r2.d > r0.d and r2.dt_mid_k > r0.dt_mid_k
    assert r0.dt_top_k >= r0.dt_mid_k and r0.c >= 1.0


def test_reference_example():
    # nástěnná skříň 600×800×250, 150 W → Ae ≈ 1,24 m² (malá skříň, x = 0,715)
    r = temperature_rise(_sheet(600, 800, 250, "nástěnná", 150), rdf=1.0, wiring_pct=0)
    assert r.x == 0.715 and r.p_total_w == 150
    assert abs(r.dt_mid_k - r.k * r.d * 150 ** 0.715) < 0.1
    assert 10 <= r.dt_mid_k <= 40 and 10 <= r.dt_top_k <= 40
    assert any("obr. 4" in n for n in r.notes) and any("tab. 3" in n for n in r.notes)
    rv = temperature_rise(_sheet(600, 800, 250, "nástěnná", 150), rdf=1.0, wiring_pct=0, vents=True)
    assert any("ventilační" in n for n in rv.notes)
