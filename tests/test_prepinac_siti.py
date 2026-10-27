"""Přepínač sítí a stykač ve vícepólu (uživatelský projekt RFVE): vlastní rozteč pólů přepínače, stykač nakreslený
vodorovně se v pohledu otočí vstupem nahoru, kontrola F7 žil vedených do přístroje jen z jedné strany."""
from itertools import pairwise
from pathlib import Path

import pytest

from envocad.library.store import LibraryStore
from envocad.model import multipole as mp
from envocad.model.checks import conductor_end_findings
from envocad.model.project import Project, element_symbol
from envocad.model.symbol import rotate_dir

DATA = Path(__file__).parent / "data" / "vicepol_rfve_rucne.ecp"
EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "ukazka_fve.ecp"


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "l.db")


def _poles(lib):
    p = Project.load(DATA)
    sb = next(s for s in p.sheets if s.is_switchboard)
    return p, sb, mp.sheet_poles(sb, lambda e: element_symbol(p, e, lib))


def test_changeover_switch_pole_pitch(lib):
    _p, _sb, poles = _poles(lib)
    q1 = next(ep for ep in poles.values() if ep.element.ref == "Q1")
    assert q1.pitch == 12.5
    xs = sorted(q1.pole_pos(port, c)[0] for port in ("1", "2") for c in q1.switched if c in q1.per_port[port])
    gaps = [b - a for a, b in pairwise(xs)]
    assert min(gaps) >= 5.0 - 1e-6                         # vstupy I / II se nikde neslévají (dřív 2,5 mm)
    f3 = next(ep for ep in poles.values() if ep.element.ref == "F3.FVE")
    assert f3.pitch == mp.POLE_PITCH


def test_horizontal_contactor_upright_in_view(lib):
    _p, sb, poles = _poles(lib)
    km = next(ep for ep in poles.values() if ep.element.ref == "KM.N0%" and ep.element.symbol_id == "fve.contactor")
    src = next(e for e in sb.elements if e.id == km.element.id)
    assert src.rotation == 0                                # v jednopólu vodorovně (porty vlevo / vpravo)
    assert rotate_dir(km.symbol.port(km.through[0]).dir, km.element.rotation) == "N"   # ve vícepólu vstup nahoru


def test_conductor_end_findings(lib):
    p, sb, _ = _poles(lib)
    found = {f.ref: f.text for f in conductor_end_findings(p, sb, lib)}
    assert set(found) == {"Q1", "F3.FVE"}                   # svodiče a ovládání cívky se nehlásí
    assert "N" in found["Q1"] and "PE" in found["Q1"]
    ex = Project.load(EXAMPLE)
    assert not [f for s in ex.sheets if s.is_switchboard for f in conductor_end_findings(ex, s, lib)]
