"""Nezávislé ověření účinné chladicí plochy Ae (`envocad.model.thermal.cooling_area`) – issue #128.

Vzorce jsou zde zapsané samostatně jako výrazy v W, H, D [m] (ne kopie kódu); `cooling_area` bere rozměry v mm
a vrací m². Zdroj: tabulka Rittal [S21] (IEC 890 / DIN 57 660-500), https://www.rittal.com/imf/none/5_263
(viz docs/research/02_B_vyrobci.md). Přiřazení vzorec ↔ způsob instalace potvrdil: projektant, 2026-11-25 (#128).
"""
from __future__ import annotations

import pytest

from envocad.model.thermal import cooling_area


# Zdroj: Rittal [S21], řádek 1 (solitér, volně stojící ze všech stran). Potvrdil: projektant, 2026-11-25 (#128).
def free_standing(w, h, d):
    return 1.8 * h * (w + d) + 1.4 * w * d


# Zdroj: Rittal [S21], řádek 2 (solitér na stěnu). Potvrdil: projektant, 2026-11-25 (#128).
def wall_mounted(w, h, d):
    return 1.4 * w * (h + d) + 1.8 * d * h


# Zdroj: Rittal [S21], řádek 7 (prostřední skříň na stěnu, zakrytá střecha) = zapuštěná skříň.
# Potvrdil: projektant, 2026-11-25 (#128).
def recessed(w, h, d):
    return 1.4 * w * h + 0.7 * w * d + d * h


FORMULAS = {"volně stojící": free_standing, "stojanová": free_standing,
            "nástěnná": wall_mounted, "zapuštěná": recessed}

# (W, H, D) v metrech; všechny hloubky >= 0,15 m (kód bere nejméně 150 mm)
DIMS = [(0.8, 2.0, 0.6), (0.6, 0.8, 0.25), (1.2, 1.8, 0.4)]


def _ae(w, h, d, mounting):
    return cooling_area(w * 1000, h * 1000, d * 1000, mounting)


@pytest.mark.parametrize("mounting", list(FORMULAS))
@pytest.mark.parametrize("w,h,d", DIMS)
def test_cooling_area_matches_formula(w, h, d, mounting):
    assert _ae(w, h, d, mounting) == pytest.approx(FORMULAS[mounting](w, h, d), rel=1e-9)


@pytest.mark.parametrize("mounting,expected", [
    ("volně stojící", 5.712), ("nástěnná", 5.072), ("zapuštěná", 3.776), ("stojanová", 5.712),
])
def test_cooling_area_fixed_values(mounting, expected):
    """W = 0,8 m, H = 2,0 m, D = 0,6 m – pevné hodnoty potvrzené projektantem (#128)."""
    assert _ae(0.8, 2.0, 0.6, mounting) == pytest.approx(expected, abs=1e-9)


def test_stojanova_equals_free_standing():
    for w, h, d in DIMS:
        assert _ae(w, h, d, "stojanová") == pytest.approx(_ae(w, h, d, "volně stojící"), rel=1e-12)


@pytest.mark.parametrize("mounting", list(FORMULAS))
def test_depth_minimum_150_mm(mounting):
    """Hloubka pod 150 mm se bere jako 150 mm; přesně 150 mm je beze změny."""
    f = FORMULAS[mounting]
    for depth_mm in (150, 100, 0):
        assert cooling_area(800, 2000, depth_mm, mounting) == pytest.approx(f(0.8, 2.0, 0.15), rel=1e-9)


# Způsoby instalace z tabulky Rittal [S21], které kód nepodporuje (neznámý způsob padá na „nástěnná“).
# Čeká na issue – zatím neexistuje.
def first_in_row_free(w, h, d):
    return 1.4 * d * (h + w) + 1.8 * w * h


def middle_in_row_free(w, h, d):
    return 1.4 * h * (w + d) + 1.4 * w * d


def first_in_row_wall(w, h, d):
    return 1.8 * w * h + 1.4 * w * d + d * h


def middle_in_row_wall(w, h, d):
    return 1.4 * w * (h + d) + d * h


@pytest.mark.xfail(strict=True, reason="čeká na issue: první/prostřední skříň v řadě není v B_FACTORS (#128)")
@pytest.mark.parametrize("mounting,f", [
    ("první skříň v řadě, volně stojící", first_in_row_free),
    ("prostřední skříň v řadě, volně stojící", middle_in_row_free),
    ("první skříň v řadě na stěnu", first_in_row_wall),
    ("prostřední skříň v řadě na stěnu", middle_in_row_wall),
])
def test_row_mountings_not_supported(mounting, f):
    assert _ae(0.8, 2.0, 0.6, mounting) == pytest.approx(f(0.8, 2.0, 0.6), rel=1e-9)
