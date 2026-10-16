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


def orthogonalize(pts: list[Point], end_horizontal: bool | None = None) -> list[Point]:
    """Lomená čára jen ze svislých a vodorovných úseků: kde by úsek šel šikmo, vloží se roh.
    Roh se volí tak, aby se směr střídal (po vodorovném úseku svisle a naopak); poslední úsek k portu jde ve směru
    portu (`end_horizontal`). Body v jedné přímce za sebou se sloučí."""
    if len(pts) < 2:
        return list(pts)
    out: list[Point] = [pts[0]]
    last_h: bool | None = None
    for i, q in enumerate(pts[1:], start=1):
        p = out[-1]
        dx, dy = abs(q[0] - p[0]) > 1e-6, abs(q[1] - p[1]) > 1e-6
        if dx and dy:
            is_last = i == len(pts) - 1
            if is_last and end_horizontal is not None:
                horiz_first = not end_horizontal   # do portu dojít ve směru portu
            else:
                horiz_first = last_h is not True if last_h is not None else True
            corner = (q[0], p[1]) if horiz_first else (p[0], q[1])
            out.append(corner)
            last_h = not horiz_first
        elif dx or dy:
            last_h = dx
        out.append(q)
    # sloučit body v přímce a duplicity
    res: list[Point] = [out[0]]
    for q in out[1:]:
        if abs(q[0] - res[-1][0]) < 1e-6 and abs(q[1] - res[-1][1]) < 1e-6:
            continue
        if len(res) >= 2:
            a, b = res[-2], res[-1]
            if (abs(a[0] - b[0]) < 1e-6 and abs(b[0] - q[0]) < 1e-6) or (abs(a[1] - b[1]) < 1e-6 and abs(b[1] - q[1]) < 1e-6):
                res[-1] = q
                continue
        res.append(q)
    return res
