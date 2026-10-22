"""Sdílené zaokrouhlení na mřížku (`model/grid.py`)."""
import pytest

from envocad.model import grid
from envocad.model.symbol import GRID


def test_grid_constant_shared():
    assert grid.GRID == GRID == 2.5


@pytest.mark.parametrize(("v", "snap", "floor", "ceil"), [
    (0.0, 0.0, 0.0, 0.0), (1.2, 0.0, 0.0, 2.5), (1.3, 2.5, 0.0, 2.5), (2.5, 2.5, 2.5, 2.5),
    (-1.3, -2.5, -2.5, 0.0), (7.5 + 1e-12, 7.5, 7.5, 7.5), (7.5 - 1e-12, 7.5, 7.5, 7.5), (10.1, 10.0, 10.0, 12.5),
])
def test_snap_floor_ceil(v, snap, floor, ceil):
    assert grid.snap(v) == pytest.approx(snap)
    assert grid.floor_grid(v) == pytest.approx(floor)
    assert grid.ceil_grid(v) == pytest.approx(ceil)


def test_ceil_floor_tolerance_just_above_and_below_line():
    """Dokumentace chování: hodnota o chybu výpočtu (< 1e-9 kroku mřížky) nad / pod čárou mřížky zůstane na čáře;
    větší odchylka (např. 1e-6 mm) už je „za čárou“ – `ceil_grid` jde na další bod, `floor_grid` na předchozí."""
    assert grid.ceil_grid(7.5 + 1e-10) == 7.5          # 0.1 + 0.2 apod. – šum výpočtu
    assert grid.ceil_grid(0.1 + 0.2 + 7.2) == 7.5
    assert grid.ceil_grid(7.5 + 1e-6) == 10.0
    assert grid.ceil_grid(7.5 + 1e-3) == 10.0
    assert grid.floor_grid(7.5 - 1e-10) == 7.5
    assert grid.floor_grid(7.5 - 1e-6) == 5.0
    assert grid.ceil_grid(-2.5 + 1e-10) == -2.5 and grid.ceil_grid(-2.5 + 1e-6) == 0.0


def test_no_duplicate_grid_helpers():
    """Zaokrouhlení na mřížku je jen v `model/grid.py` (dřív kopie v routing, symbol, frame, xref, multipole,
    revision, notes, exportu, importu QET, generátoru a GUI)."""
    import re
    from pathlib import Path
    root = Path(grid.__file__).resolve().parent.parent
    pat = re.compile(r"def _?(snap|ceil_grid|floor_grid)\(v: float\)")
    bad = [str(p.relative_to(root)) for p in root.rglob("*.py") if p.name != "grid.py"
           and pat.search(p.read_text(encoding="utf-8"))]
    assert bad == []
