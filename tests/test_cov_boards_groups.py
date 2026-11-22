"""Charakterizační testy `generator/boards/groups.py` (skupiny střídačů `ac_group` – RFVE.AC{n}) – bez Qt, bez sítě.
Část přes `build_project` (veřejné chování), okrajové větve voláním modulových funkcí s minimálním kontextem."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from envocad.generate import build_project
from envocad.generator import jps
from envocad.generator.boards import groups
from envocad.model.project import Element, Project, Wire, WireEnd

_INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
_EXIST_NN = {"hr": {"main_in": 250}, "re": {"main_in": 250}, "hds": {"in_": 315}}


def _spec(**kw):
    """Tři střídače, T2 a T3 ve vlastních skupinách (RFVE.AC2, RFVE.AC3)."""
    return {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]},
                          {"ref": "T2", **_INV, "strings": [20], "ac_group": "hala B"},
                          {"ref": "T3", **_INV, "strings": [20], "ac_group": "hala C"}],
            "chain": dict(_EXIST_NN), "jps": {"split": "none"}, **kw}


def _ctx(**kw):
    """Minimální kontext: jen to, co funkce modulu čtou."""
    p = Project(name="skupiny")
    base = {"project": p, "sheet": p.sheets[0], "blocks": {}, "groups": [], "topology": None, "node_in": {},
            "spec": {"ac": {}}}
    return SimpleNamespace(**{**base, **kw})


# ---- čisté funkce ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("n, expected", [(1, ["X1"]), (2, ["X1", "X3"]), (4, ["X1", "X3", "X4", "X5"]), (0, ["X1"])])
def test_feeds(n, expected):
    """Vývody FVE v HR / RD: X1, pak X3, X4… (X2 = stávající rozvody); pro 0 skupin zbyde X1."""
    assert groups.feeds(n) == expected


def test_first_board_prefers_hr_over_rd():
    hr, rd = Element("sb.feed", 0, 0), Element("sb.feed", 1, 1)
    assert groups.first_board(SimpleNamespace(blocks={"hr": hr, "rd": rd})) is hr
    assert groups.first_board(SimpleNamespace(blocks={"rd": rd})) is rd
    assert groups.first_board(SimpleNamespace(blocks={})) is None


def test_obstacles_skips_main_group_and_missing_parts():
    blk1, blk2, blk3 = (Element("fve.switchboard", 0, 0) for _ in range(3))
    earth, i_g = Element("fve.earth", 0, 0), Element("fve.interrupt", 0, 0)
    ctx = SimpleNamespace(groups=[{"block": blk1, "earth": Element("fve.earth", 0, 0)},
                                  {"block": blk2, "earth": earth, "int_g": i_g}, {"block": blk3}])
    assert groups.obstacles(ctx) == [blk2, earth, i_g, blk3]


# ---- build_links ----------------------------------------------------------------------------------------------------
def test_build_links_returns_without_house_board():
    """Řádek 37: bez bloku HR / RD (nebo bez topologie) se nic nepřidá."""
    ctx = _ctx(groups=[{"block": Element("fve.switchboard", 0, 0)}, {"block": Element("fve.switchboard", 0, 0)}])
    groups.build_links(ctx)
    assert ctx.sheet.elements == [] and ctx.sheet.wires == []
    assert all("int_g" not in g for g in ctx.groups)


# ---- _earth ---------------------------------------------------------------------------------------------------------
def test_earth_non_bus_distribution_adds_nothing():
    """Řádek 60: rozvod „terminals“ → bloky skupin nemají uzemnění (HOP) ani PE vodič."""
    blk = Element("fve.switchboard", 100, 200)
    ctx = _ctx(spec={"ac": {"distribution": "terminals"}})
    g = {"block": blk}
    groups._earth(ctx, g)
    assert ctx.sheet.elements == [] and ctx.sheet.wires == [] and "earth" not in g


def test_earth_bus_distribution_defaults():
    """Rozvod „bus“ (výchozí): HOP 35 mm vpravo a 40 mm pod blokem, PE vodič s výchozími údaji kabelu."""
    blk = Element("fve.switchboard", 100, 200)
    ctx = _ctx()
    g = {"block": blk}
    groups._earth(ctx, g)
    earth = g["earth"]
    assert (earth.symbol_id, earth.x, earth.y) == ("fve.earth", 135.0, 160.0)
    w = ctx.sheet.wires[0]
    assert (w.a.port, w.b.port, w.conductors) == ("XPE", "PE", ["PE"])
    assert (w.attrs["cable"], w.attrs["cross"], w.attrs["length"]) == ("CYA 16", "16", "5")


def test_earth_uses_spec_pe_cable():
    ctx = _ctx(spec={"ac": {"pe_cable": "CYA 25", "pe_cross": 25, "pe_length": 8}})
    g = {"block": Element("fve.switchboard", 0, 0)}
    groups._earth(ctx, g)
    w = ctx.sheet.wires[0]
    assert (w.attrs["cable"], w.attrs["cross"], w.attrs["length"]) == ("CYA 25", "25", "8")


# ---- place_sources / place ------------------------------------------------------------------------------------------
def test_place_sources_skips_groups_without_interrupt():
    """Řádek 97: skupina bez přerušení u XOUT (`int_g`) se přeskočí – nic se nepočítá ani nemění."""
    ctx = _ctx(groups=[{"block": Element("fve.switchboard", 0, 0)}, {"block": Element("fve.switchboard", 5, 5)}])
    groups.place_sources(ctx)
    assert "int_g" not in ctx.groups[1]


def test_place_without_house_board_does_nothing():
    """Řádek 117: bez HR / RD `place` skončí hned (ani `place_sources` neběží)."""
    w = Wire(WireEnd("a", "XOUT"), WireEnd("b", "1"), points=[(1.0, 2.0)])
    i_g = Element("fve.interrupt", 7, 8)
    ctx = _ctx(groups=[{"block": Element("fve.switchboard", 0, 0)},
                       {"block": Element("fve.switchboard", 0, 0), "int_g": i_g, "w_g": w}])
    groups.place(ctx)
    assert w.points == [(1.0, 2.0)] and (i_g.x, i_g.y) == (7, 8)


def test_place_skips_groups_without_house_interrupt():
    """Řádek 122: skupina bez přerušení u HR / RD (`int_h`) se přeskočí."""
    hr = Element("sb.feed", 0, 0)
    ctx = _ctx(blocks={"hr": hr}, groups=[{"block": Element("fve.switchboard", 0, 0)},
                                          {"block": Element("fve.switchboard", 0, 0), "feed": "X3"}])
    groups.place(ctx)
    assert "int_h" not in ctx.groups[1]


# ---- stack_after_split ----------------------------------------------------------------------------------------------
def _stack_ctx():
    """List: RFVE.AC1 (main) a blok skupiny pod ním bez vodičové vazby; zbytek přidají testy."""
    p = Project(name="stack")
    s = p.sheets[0]
    main = Element("fve.load", 0, 0, attrs={"ref": "M"})
    blk = Element("fve.load", 0, -100, attrs={"ref": "G"})
    s.elements += [main, blk]
    ctx = SimpleNamespace(project=p, sheet=s, main=main, links=[], groups=[{"block": main}, {"block": blk}])
    return ctx, main, blk


def test_stack_after_split_without_main_boxes_returns(monkeypatch):
    """Řádek 147: RFVE.AC1 bez obsahu (žádné obálky) → nic se nepřesouvá."""
    ctx, _main, blk = _stack_ctx()
    ctx.sheet.elements = [blk]            # main na listu není → `component_boxes` je prázdné
    y = blk.y
    groups.stack_after_split(ctx)
    assert blk.y == y


def test_stack_after_split_block_not_on_sheet_is_skipped():
    """Řádek 152: blok skupiny, který na listu není, se přeskočí."""
    ctx, main, blk = _stack_ctx()
    ctx.sheet.elements = [main]
    groups.stack_after_split(ctx)
    assert main.y == 0 and blk.y == -100


def test_stack_after_split_group_without_boxes_is_skipped(monkeypatch):
    """Řádek 155: skupina bez obálek obsahu (`own` prázdné) se nepřesouvá."""
    ctx, main, blk = _stack_ctx()
    monkeypatch.setattr(jps, "component_boxes", lambda p, s, ids, lib: [(0.0, 0.0, 10.0, 10.0)] if main.id in ids else [])
    groups.stack_after_split(ctx)
    assert blk.y == -100


def test_stack_after_split_moves_group_below_main():
    """Skupina bez vazby na RFVE.AC1 se přesune pod obsah s RFVE.AC1 (mezera `GROUP_STACK_GAP`, krok 2,5 mm);
    body vodiče uvnitř skupiny se posunou o stejné dy."""
    ctx, main, blk = _stack_ctx()
    other = Element("fve.load", 0, -100, attrs={"ref": "H"})
    ctx.sheet.elements.append(other)
    w = Wire(WireEnd(blk.id, "1"), WireEnd(other.id, "1"), points=[(10.0, -100.0), (10.0, -110.0)])
    ctx.sheet.wires.append(w)
    y0 = blk.y
    groups.stack_after_split(ctx)
    dy = blk.y - y0
    assert dy != 0 and dy % 2.5 == 0 and other.y == y0 + dy
    assert w.points == [(10.0, -100.0 + dy), (10.0, -110.0 + dy)]
    assert main.y == 0


# ---- celé sestavení ---------------------------------------------------------------------------------------------------
def _blocks(p):
    return {e.ref: e for e in p.sheets[0].elements if e.symbol_id == "fve.switchboard"}


def test_build_three_groups_have_own_feeds_and_earth():
    """Tři skupiny: RFVE.AC1-3, HR má vývody X1, X2, X3, X4 a každý blok skupiny má uzemnění (HOP)."""
    p = build_project(_spec())
    s = p.sheets[0]
    b = _blocks(p)
    assert {"RFVE.AC1", "RFVE.AC2", "RFVE.AC3", "HR"} <= set(b)
    assert (b["HR"].attrs["ports_in"], b["HR"].attrs["ports_out"]) == ("XIN", "X1 X2 X3 X4")
    assert len([e for e in s.elements if e.symbol_id == "fve.earth"]) == 3
    ints = sorted(e.ref for e in s.elements if e.symbol_id == "fve.interrupt" and e.ref.startswith("AC"))
    assert ints == ["AC2-HR", "AC2-HR", "AC3-HR", "AC3-HR"]


def test_build_groups_terminals_distribution_has_no_earth():
    """Rozvod „terminals“: žádný blok (ani skupiny) nemá uzemnění HOP – větev řádku 60."""
    p = build_project(_spec(ac={"distribution": "terminals"}))
    assert [e for e in p.sheets[0].elements if e.symbol_id == "fve.earth"] == []
    assert {"RFVE.AC2", "RFVE.AC3"} <= set(_blocks(p))


def test_build_groups_interrupt_placed_right_of_xout():
    """`place_sources`: přerušení kabelu skupiny leží `GROUP_INT_GAP` vpravo od XOUT bloku skupiny."""
    from envocad.library.store import LibraryStore
    from envocad.model.project import element_symbol
    lib = LibraryStore()
    p = build_project(_spec())
    s = p.sheets[0]
    blk = _blocks(p)["RFVE.AC2"]
    ox, oy = blk.port_pos(element_symbol(p, blk, lib), "XOUT")
    i_g = next(e for e in s.elements if e.symbol_id == "fve.interrupt" and e.ref == "AC2-HR"
               and any(w.touches(e.id) and w.touches(blk.id) for w in s.wires))
    px, py = i_g.port_pos(element_symbol(p, i_g, lib), "1")
    assert (px, py) == (ox + groups.GROUP_INT_GAP, oy)
