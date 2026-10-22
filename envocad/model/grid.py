"""Mřížka výkresu 2,5 mm (CAD konvence, jednotky mm) – zaokrouhlení na mřížku sdílené modelem, knihovnou, exportem,
generátorem i GUI. Bez Qt."""
from __future__ import annotations

import math

GRID = 2.5  # mm
_EPS = 1e-9  # tolerance zaokrouhlení nahoru/dolů (hodnota o chybu výpočtu nad/pod čárou mřížky zůstane na ní)


def snap(v: float) -> float:
    """Nejbližší bod mřížky."""
    return round(v / GRID) * GRID


def floor_grid(v: float) -> float:
    """Nejbližší bod mřížky ≤ v (s tolerancí `_EPS`)."""
    return math.floor(v / GRID + _EPS) * GRID


def ceil_grid(v: float) -> float:
    """Nejbližší bod mřížky ≥ v (s tolerancí `_EPS`)."""
    return math.ceil(v / GRID - _EPS) * GRID
