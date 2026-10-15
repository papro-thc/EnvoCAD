"""Geometrické pomůcky nad lomenými čarami (bez Qt) – sdílí je editor i DXF export."""

from __future__ import annotations

from itertools import pairwise

Point = tuple[float, float]


def longest_segment(pts: list[Point]) -> tuple[Point, Point]:
    """Nejdelší úsek lomené čáry (pro umístění popisku)."""
    best, best_len = (pts[0], pts[-1]), -1.0
    for a, b in pairwise(pts):
        d = abs(b[0] - a[0]) + abs(b[1] - a[1])
        if d > best_len:
            best, best_len = (a, b), d
    return best


def wire_label_anchor(pts: list[Point], gap: float = 1.5) -> tuple[float, float, str, bool]:
    """Kde a jak napsat popisek vodiče (souřadnice modelu, Y nahoru).

    Vrací (x, y, zarovnání, vertical). Vodorovný úsek → text nad středem, zarovnaný na střed.
    Svislý (nebo šikmý) úsek → text vodorovně vpravo od středu, zarovnaný vlevo (styl EPLAN).
    """
    a, b = longest_segment(pts)
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    if abs(b[1] - a[1]) <= abs(b[0] - a[0]):
        return (mx, my + gap, "center", False)
    return (mx + gap, my - 1.0, "left", True)
