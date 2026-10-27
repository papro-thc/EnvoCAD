"""Elektroměr při nepřímém měření ve vícepólu jako v EPLAN: obdélník se svorkami podle DIN 43856 (každá žíla na svou
svorku, čísla svorek i v zapojovacím seznamu), MTP po fázích pod sebou se sekundáry S1 / S2 v různých výškách;
žíly jednoho vodiče se společnou příčkou bez překrývání (`multipole.wire_jog`)."""
from itertools import combinations, pairwise

import pytest
from test_generate import _F7_RE_INDIRECT, F7_CASES, build_project

from envocad.library.store import LibraryStore
from envocad.model import multipole as mp
from envocad.model.multipole_geometry import multipole_geometry
from envocad.model.project import element_symbol

pytestmark = pytest.mark.usefixtures("ac_builtin")

CT_SECONDARY = ["1S1", "1S2", "2S1", "2S2", "3S1", "3S2"]


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _re(spec):
    p = build_project(spec)
    return p, next(s for s in p.sheets if s.is_switchboard and s.name.startswith("RE"))


def _meter(s):
    return next(e for e in s.elements if e.symbol_id == "fve.meter")


@pytest.mark.parametrize("name", ["vn_sloup_50kva", "vn_kobky_mereni_vn", "nn"])
def test_meter_terminals_din_43856(lib, name):
    """Každá žíla elektroměru má svou svorku nahoře na obdélníku (DIN 43856: I1 1–3, U1 2, …, N 11), bez sběrné
    čárky portu; svorky v pořadí 1 2 3 4 5 6 7 8 9 11 zleva doprava."""
    p, s = _re(F7_CASES.get(name) or _F7_RE_INDIRECT)
    poles = mp.sheet_poles(s, lambda e: element_symbol(p, e, lib))
    ep = poles[_meter(s).id]
    conds = set().union(*ep.per_port.values())
    assert set(ep.terminals) == conds and set(CT_SECONDARY) <= conds
    xs = {c: ep.pole_pos("1", c)[0] for c in conds}
    order = mp.TERMINAL_SCHEMES["DIN 43856"]["conductors"]
    by_terminal = sorted(conds, key=lambda c: mp.TERMINAL_SCHEMES["DIN 43856"]["order"].index(order[c]))
    assert [xs[c] for c in by_terminal] == sorted(xs.values())
    assert len({round(x, 3) for x in xs.values()}) == len(conds)          # žádné dvě žíly na jedné svorce
    assert all(ep.symbol.port(port).dir == "N" for port in ep.per_port)    # žíly přicházejí shora


def test_direct_meter_stays_through_device(lib):
    """Přímé měření (elektroměr průchozí L1–L3 N) zůstává jako dřív – schéma svorek jen se sekundárem MTP."""
    spec = {**_F7_RE_INDIRECT, "chain": {**_F7_RE_INDIRECT["chain"], "re": {"main_in": 63, "metering": "direct"}}}
    p, s = _re(spec)
    poles = mp.sheet_poles(s, lambda e: element_symbol(p, e, lib))
    ep = poles[_meter(s).id]
    assert not ep.terminals and ep.through


def test_wiring_list_uses_meter_terminals():
    """Zapojovací seznam: konec žíly na elektroměru = svorka DIN 43856 („P1:3“), ne port značky."""
    from envocad.model.wiring import conductor_end
    p, s = _re(_F7_RE_INDIRECT)
    meter = _meter(s)
    got = {}
    for w in s.wires:
        if w.touches(meter.id):
            side = "a" if w.a.element_id == meter.id else "b"
            got.update({c: conductor_end(p, s, w, c, side).text.rsplit(":", 1)[1] for c in w.conductors})
    assert got == {"1S1": "1", "1S2": "3", "2S1": "4", "2S2": "6", "3S1": "7", "3S2": "9",
                   "L1": "2", "L2": "5", "L3": "8", "N": "11"}


def test_ct_secondaries_at_own_heights(lib):
    """MTP po fázích pod sebou (`multipole.stagger`): sekundáry S1 / S2 všech fází v různých výškách a mimo kroužky
    ostatních fází – vodorovné žíly sekundáru se nepřekrývají ani nevedou přes cizí transformátor."""
    p, s = _re(_F7_RE_INDIRECT)
    poles = mp.sheet_poles(s, lambda e: element_symbol(p, e, lib))
    ct = next(ep for ep in poles.values() if ep.element.symbol_id == "fve.ct")
    ends = {c: ct.pole_pos("S", c) for c in CT_SECONDARY}
    flow_vertical = not mp._flow_is_horizontal_for(ct)
    across = 1 if flow_vertical else 0          # výška sekundáru = souřadnice po toku
    assert len({round(v[across], 3) for v in ends.values()}) == 6
    centers = {ph: mp.pole_anchor(ct, ph) for ph in ("L1", "L2", "L3")}
    assert len({round(v[across], 3) for v in centers.values()}) == 3          # póly posunuté po toku
    for c, pt in ends.items():
        own = c[0]                                # fáze sekundáru (1S1 → L1)
        for ph, cen in centers.items():
            if ph[1] != own:
                assert abs(pt[across] - cen[across]) > 3.0, (c, ph)          # kroužek r = 3 mm


def _overlapping_lines(g):
    """Dvojice úseků různých žil, které leží na sobě (vypadaly by jako spojení). Stejná žíla dvou vodičů z jedné
    svorky (odbočka L1 k elektroměru a L1 dál) je týž potenciál – ta se nepočítá."""
    segs = [(a, b, o) for a, b, o, what in g.lines if "#" in o]
    out = []
    for (a, b, oa), (c, d, ob) in combinations(segs, 2):
        if oa.split("#")[1] != ob.split("#")[1] and mp._overlaps([a, b], [(c, d)]):
            out.append((oa, ob))
    return out


@pytest.mark.parametrize("name", ["vn_sloup_50kva", "vn_kobky_mereni_vn", "nn"])
def test_metering_conductors_do_not_overlap(lib, name):
    """Žíly různých vodičů k elektroměru (proud z MTP, napětí) se na listu RE nikde nepřekrývají."""
    p, s = _re(F7_CASES.get(name) or _F7_RE_INDIRECT)
    g = multipole_geometry(p, s, lib, standard_paper="A4")
    assert not _overlapping_lines(g)


def test_wire_jog_avoids_turn_back_and_overlap():
    """Společná příčka vodiče: krátký úsek s mnoha žilami → jiná výška, aby se žádná žíla nevracela po sobě;
    úsek už nakreslené žíly → výška bez překrytí."""
    ends = [((10.0 + 7.5 * i, 40.0), "S", (10.0 + 5.0 * i + (i > 2) * 20, 20.0), "N") for i in range(6)]
    jog, rev = mp.wire_jog(ends)
    routes = [mp.wire_route(*e, stagger=((5 - i) if rev else i) * mp.GRID, jog=jog) for i, e in enumerate(ends)]
    assert all(mp._clean_path(r) for r in routes)
    assert not any(mp._overlaps(r, list(pairwise(q))) for r, q in combinations(routes, 2))
    blocker = [((0.0, 26.0), (100.0, 26.0))]
    jog2, rev2 = mp.wire_jog(ends, segs=blocker)
    routes2 = [mp.wire_route(*e, stagger=((5 - i) if rev2 else i) * mp.GRID, jog=jog2) for i, e in enumerate(ends)]
    assert not any(mp._overlaps(r, blocker) for r in routes2)


def test_break_at_own_height_when_free():
    """Přerušení na okraji strany od portu E/W ve výšce žíly, je-li volná (sekundáry MTP v různých výškách)."""
    used: set[float] = set()
    assert mp.break_y((50.0, 100.0), "E", 0, used) == 100.0
    assert mp.break_y((50.0, 90.0), "E", 1, used) == 90.0
    assert mp.break_y((50.0, 100.0), "E", 2, used) == 97.5     # obsazená výška → o rozteč níž


def test_old_project_s1_s2_unchanged(lib):
    """Starý projekt (sekundár jako jedna dvojice S1 / S2, napětí a n): elektroměr bez svorek a MTP bez posunu pólů
    po toku a bez příčky sekundáru – vícepól jako dřív."""
    p, s = _re(_F7_RE_INDIRECT)
    old = {"1S1": "S1", "1S2": "S2"}
    for w in s.wires:
        if any(c in w.conductors for c in CT_SECONDARY):
            w.conductors = [old[c] for c in w.conductors if c in old]
    poles = mp.sheet_poles(s, lambda e: element_symbol(p, e, lib))
    assert not poles[_meter(s).id].terminals
    ct = next(ep for ep in poles.values() if ep.element.symbol_id == "fve.ct")
    assert not ct.secondary_used
    assert {mp.pole_anchor(ct, ph)[1] for ph in ct.switched} == {ct.origin[1]} or \
        {mp.pole_anchor(ct, ph)[0] for ph in ct.switched} == {ct.origin[0]}
    assert len(mp.pole_symbol_for(ct, "L1").primitives) == len(ct.symbol.pole_symbol().primitives)


def test_meter_layout_width_is_box(lib):
    """Elektroměr se svorkami zabírá v rozmístění jen šířku obdélníku (ne rezervu na každou žílu)."""
    p, s = _re(_F7_RE_INDIRECT)
    poles = mp.sheet_poles(s, lambda e: element_symbol(p, e, lib))
    ep = poles[_meter(s).id]
    x0, _y0, x1, _y1 = ep.symbol.bounds()
    assert mp.perp_extent(ep) == pytest.approx(x1 - x0)
