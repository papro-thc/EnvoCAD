"""Charakterizační testy `generator/boards/eps.py` (EPS a přepínač sítí u rodinného domu) – bez Qt, bez sítě.
Část přes `build_project` (RD s baterií, vlastní topologie bez RD / HR), pomocné funkce volané přímo."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from envocad.generate import build_project
from envocad.generator.boards import eps
from envocad.library import topologies
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Sheet, Wire, WireEnd, element_symbol

_BAT = {"e_kwh": 10, "p_kw": 5, "type": "BYD"}
_INV = {"p_ac": 10, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
_NO_DC = {"tech_box": False, "route_boxes": 0}      # RFVE za střídači (bez DC části) → `ctx.combined` False


def _house(n_inv=1, **kw):
    return {"building": "house", "battery": dict(_BAT),
            "inverters": [{"ref": f"T{i + 1}", **_INV, "strings": [16]} for i in range(n_inv)], **kw}


def _rfve_only_topology():
    """Vlastní topologie rodinného domu s RFVE a bez stávajícího RD / HR (záloha visí přímo na RFVE.XB{i})."""
    d = topologies.user_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "rfve_only.json").write_text(json.dumps({
        "version": 1, "id": "rfve_only", "name": "RFVE bez RD", "buildings": ["house"], "level": "nn",
        "nodes": [{"role": "rfve", "ref": "RFVE", "macros": {},
                   "options": {"grid_protection": "auto", "changeover_switch": "1"}},
                  {"role": "inverter"},
                  {"role": "hds", "ref": "HDS", "desc": "hlavní domovní skříň", "sheet": False,
                   "options": {"char": "gG"}},
                  {"role": "grid", "desc": "distribuční soustava", "sheet": False}]}), encoding="utf-8")


def _load(p):
    """Značka „zálohované okruhy“ a její vodič v JPS."""
    s = p.sheets[0]
    load = next(e for e in s.elements if e.symbol_id == "fve.load" and e.attrs.get("desc") == eps.EPS_LOAD_DESC)
    w = next(w for w in s.wires if w.touches(load.id))
    return s, load, w


# ---- čisté pomocné funkce -------------------------------------------------------------------------------------------
def _bus_sheet(*ports):
    sb = Sheet()
    bus = Element("sb.busbar", 0, 0)
    other = Element("sb.rcd", 0, 0)
    sb.elements += [bus, other]
    sb.wires += [Wire(WireEnd(bus.id, pt), WireEnd(other.id, "1")) for pt in ports]
    sb.wires.append(Wire(WireEnd(other.id, "4"), WireEnd(other.id, "2")))      # cizí vývod „4“ se nepočítá
    return sb, bus


@pytest.mark.parametrize("used, expected", [((), "4"), (("4",), "5"), (("4", "5"), "6"), (("5",), "4"),
                                             (("4", "6"), "5")])
def test_free_out_first_unused_from_four(used, expected):
    """Řádek 41: první volný vývod sběrnice od 4 výše (obsazené 4, 5… se přeskočí)."""
    sb, bus = _bus_sheet(*used)
    assert eps.free_out(sb, bus) == expected


def test_prepare_inverter_adds_backup_once():
    t = Element("fve.inverter_hybrid", 0, 0, attrs={"io": "RS485 BAT"})
    eps.prepare_inverter(t)
    assert t.attrs["io"] == "RS485 BAT BACKUP" and t.attrs["eps"] == "1"
    eps.prepare_inverter(t)                              # podruhé už BACKUP nepřidá
    assert t.attrs["io"] == "RS485 BAT BACKUP"


def test_prepare_inverter_without_io_keeps_only_backup():
    t = Element("fve.inverter_hybrid", 0, 0, attrs={})
    eps.prepare_inverter(t)
    assert t.attrs["io"].split()[-1] == "BACKUP" and t.attrs["eps"] == "1"


def test_house_board_prefers_rd_over_hr():
    rd, hr = Element("fve.switchboard", 0, 0), Element("fve.switchboard", 1, 1)
    assert eps.house_board(SimpleNamespace(blocks={"rd": rd, "hr": hr})) is rd
    assert eps.house_board(SimpleNamespace(blocks={"hr": hr})) is hr
    assert eps.house_board(SimpleNamespace(blocks={})) is None


def test_eps_inverters_empty_without_battery_or_topology():
    assert eps.eps_inverters(SimpleNamespace(spec={}, topology=None)) == []
    assert eps.eps_inverters(SimpleNamespace(spec={"battery": _BAT}, topology=None)) == []


# ---- _wire_clashes (řádek 332 a okolní větve) ------------------------------------------------------------------------
@pytest.mark.parametrize("own, other, expected", [
    ([(0, 0), (20, 0)], [(5, 3), (25, 3)], 1),        # souběh vodorovných úseků do 5 mm (řádek 332)
    ([(0, 0), (20, 0)], [(5, 10), (25, 10)], 0),      # vodorovné dál než 5 mm
    ([(0, 0), (20, 0)], [(30, 3), (40, 3)], 0),       # vodorovné bez překryvu
    ([(0, 0), (20, 0)], [(10, -5), (10, 5)], 1),      # křížení
    ([(0, 0), (20, 0)], [(10, 5), (10, 15)], 0),      # svislý úsek mimo vodorovný
    ([(0, 0), (0, 20)], [(3, 5), (3, 15)], 1),        # souběh svislých úseků
    ([(0, 0), (0, 20)], [(8, 5), (8, 15)], 0),        # svislé dál než 5 mm
    ([(0, 0), (20, 0)], [(5, 0), (5, 0)], 0),         # nulový úsek se ignoruje
])
def test_wire_clashes(monkeypatch, own, other, expected):
    w = Wire(WireEnd("a", "1"), WireEnd("b", "1"))
    other_w = Wire(WireEnd("c", "1"), WireEnd("d", "1"))
    routes = {w.id: own, other_w.id: other}
    monkeypatch.setattr("envocad.model.routing.route_sheet", lambda p, s, lib: routes)
    ctx = SimpleNamespace(project=Project(name="x"), sheet=Sheet())
    assert eps._wire_clashes(ctx, w) == expected


# ---- build_jps / place_jps bez RD / HR (řádky 199, 248-257, 272, 372-382) ---------------------------------------------
def test_eps_without_house_board_load_hangs_on_rfve():
    """Bez RD / HR v řetězci visí „zálohované okruhy“ přímo na RFVE.XB1 (řádek 199) a nevzniká kabel zpět (272);
    `place_jps` ji položí vpravo od vodiče XB (řádky 248-257, `_band_bottom` 372-382)."""
    _rfve_only_topology()
    p = build_project(_house(topology="rfve_only"))
    s, load, w = _load(p)
    blk = next(e for e in s.elements if e.ref == "RFVE")
    assert {w.a.port, w.b.port} == {"XB1", "1"} and blk.id in (w.a.element_id, w.b.element_id)
    assert not [e for e in s.elements if e.symbol_id == "fve.interrupt" and e.ref.startswith("EPS-RD")]
    assert len([e for e in s.elements if e.symbol_id == "fve.interrupt" and e.ref == "EPS-T1"]) == 2
    lib = LibraryStore()
    xb = blk.port_pos(element_symbol(p, blk, lib), "XB1")
    lp = load.port_pos(element_symbol(p, load, lib), "1")
    (x1, y1), (x2, y2) = w.points
    assert x1 == x2 and y1 == xb[1]                   # svisle dolů od vývodu XB
    assert y2 <= xb[1] - 15.0 and y2 % 2.5 == 0       # pod vývodem, na mřížce
    assert lp == (x1 + 10.0, y2)                      # značka vpravo od svislého úseku, port 1 v jeho výšce


def test_eps_without_house_board_f7_clean_of_errors():
    from envocad.model.checks import ERROR, check_project
    _rfve_only_topology()
    p = build_project(_house(topology="rfve_only"))
    assert [f.code for f in check_project(p, LibraryStore(), standard_paper="A4") if f.severity == ERROR] == []


def test_eps_with_rd_returns_to_house_board():
    """Výchozí topologie `rd`: záloha vede RFVE.XB1 → přerušení „EPS-RD“ → RD.XE1; spotřeba visí na RD.XB1."""
    p = build_project(_house())
    s = p.sheets[0]
    rd = next(e for e in s.elements if e.ref == "RD")
    assert len([e for e in s.elements if e.symbol_id == "fve.interrupt" and e.ref == "EPS-RD"]) == 2
    _s, _load_el, w = _load(p)
    assert rd.id in (w.a.element_id, w.b.element_id) and "XB1" in (w.a.port, w.b.port)
    assert "XE1" in rd.attrs["ports_in"].split() and "XB1" in rd.attrs["ports_out"].split()


# ---- _place_interrupts: RFVE za střídači (řádky 354-361) ---------------------------------------------------------
def _eps_int_b(p, lib):
    """(přerušení u přívodu XE1 na RFVE, poloha portu XE1 bloku RFVE)."""
    s = p.sheets[0]
    blk = next(e for e in s.elements if e.ref == "RFVE")
    ex, ey = blk.port_pos(element_symbol(p, blk, lib), "XE1")
    ib = next(e for e in s.elements if e.symbol_id == "fve.interrupt" and e.ref == "EPS-T1"
              and any(w.touches(e.id) and w.touches(blk.id) for w in s.wires))
    return ib, (ex, ey)


def test_place_interrupts_behind_inverters_default_gap():
    """RFVE bez DC části, jediný střídač: přerušení 50 mm (`EPS_LEFT_GAP`) vlevo od přívodu XE1, otočené o 180°."""
    p = build_project(_house(dc=dict(_NO_DC)))
    lib = LibraryStore()
    ib, (ex, ey) = _eps_int_b(p, lib)
    assert ib.rotation == 180
    assert ib.port_pos(element_symbol(p, ib, lib), "1") == (ex - eps.EPS_LEFT_GAP, ey)


def test_place_interrupts_behind_inverters_gap_shrinks_before_ac_bends():
    """Řádek 359: se dvěma střídači stoupá AC vodič druhého těsně před přívodem XE1 → mezera se zkrátí
    (nejméně `EPS_LEFT_MIN`)."""
    p = build_project(_house(n_inv=2, dc=dict(_NO_DC)))
    lib = LibraryStore()
    ib, (ex, ey) = _eps_int_b(p, lib)
    px, py = ib.port_pos(element_symbol(p, ib, lib), "1")
    assert py == ey and ib.rotation == 180
    assert (ex - px) == 30.0 and eps.EPS_LEFT_MIN <= ex - px < eps.EPS_LEFT_GAP


def test_place_interrupts_combined_below_xe():
    """RFVE s DC částí (`combined`): přerušení 5 mm vlevo od XE1 a 40 mm pod ním (svisle, rotace 270°)."""
    p = build_project(_house())
    lib = LibraryStore()
    ib, (ex, ey) = _eps_int_b(p, lib)
    assert ib.rotation == 270
    assert ib.port_pos(element_symbol(p, ib, lib), "1") == (ex - eps.EPS_INT_DX, ey - eps.EPS_DROP)


# ---- anchor_eps / build_sheet_part ----------------------------------------------------------------------------------
def test_house_rfve_sheet_has_changeover_switch_and_feeds():
    """List RFVE s vestavěným kódem: přepínač sítí, přívod XE1 a vývod XB1, jistič z prvního volného vývodu sběrnice."""
    p = build_project(_house(chain={"rfve": {"builtin": True}}))
    sb = next(s for s in p.sheets if s.loc == "RFVE")
    assert len([e for e in sb.elements if e.symbol_id == eps.CHANGEOVER_SYMBOL]) == 1
    assert {e.ref for e in sb.elements if e.ref.startswith(("XE", "XB"))} == {"XE1", "XB1"}
    bus = next(e for e in sb.elements if e.symbol_id == "sb.busbar")
    used = {end.port for w in sb.wires for end in (w.a, w.b) if end.element_id == bus.id}
    assert eps.free_out(sb, bus) not in used
