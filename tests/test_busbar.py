"""Parametrická sběrnice `sb.busbar` (atribut `taps`, `model/busbar.py`): délka a porty podle počtu přívodů, přívodní
větve RFVE.AC / RFVE rovně do sběrnice; sběrnice bez atributu (staré projekty, vlastní makra) beze změny. Bez Qt."""
from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest
from test_feed_review import _cross_nodes, _crossings

from envocad.model.busbar import (
    B1_X,
    DEFAULT_PITCH,
    PARAM_KEYS,
    BusLayout,
    busbar_symbol,
    layout_of,
    line_end,
    line_span,
)
from envocad.model.checks import ERROR, WARNING, check_project
from envocad.model.feed import is_feed, is_feed_in
from envocad.model.project import Element, Project, element_symbol

pytestmark = pytest.mark.usefixtures("ac_builtin")   # AC listy vestavěným kódem (standard `ac_builtin`)

DATA = Path(__file__).parent / "data"
INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
HOUSE_INV = {"p_ac": 10, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    from envocad.library.store import LibraryStore
    return LibraryStore(tmp_path_factory.mktemp("lib") / "lib.db")


def _bus(sheet) -> Element:
    return next(e for e in sheet.elements if e.symbol_id == "sb.busbar")


def _bent(project, sheet, lib, wires) -> list[str]:
    """Vodiče, jejichž trasa není jedna svislá úsečka."""
    from envocad.model.routing import route_sheet
    r = route_sheet(project, sheet, lib)
    return [w.id for w in wires if len({round(x, 6) for x, _y in r[w.id]}) != 1]


def _branch_wires(sheet) -> list:
    """Vodiče přívodních větví (přívod → jistič → sběrnice) a všechny odbočky sběrnice (SPD, PE → XPE, hlavní
    vypínač) a hlavní vypínač → XOUT."""
    bus = _bus(sheet)
    by_id = {e.id: e for e in sheet.elements}
    feeds = {e.id for e in sheet.elements if is_feed_in(e)}
    q = {e.id for e in sheet.elements if e.symbol_id == "sb.main_switch"}
    out = []
    for w in sheet.wires:
        ids = {w.a.element_id, w.b.element_id}
        if bus.id in ids or ids & feeds or (ids & q and any(is_feed(by_id[i]) for i in ids if i in by_id)):
            out.append(w)
    return out


# ---- značka ------------------------------------------------------------------------------------------------------
def test_without_attribute_is_library_symbol(lib):
    base = lib.get_symbol("sb.busbar")
    for attrs in ({}, {"taps": ""}, {"taps": "x"}, {"taps": "0"}, {"taps": "2.5"}):
        e = Element("sb.busbar", 0, 0, attrs=attrs)
        assert layout_of(e) is None
        assert busbar_symbol(e, base) is base
        assert element_symbol(Project(), e, lib).ports == base.ports


def test_symbol_json_has_param_attributes_empty(lib):
    base = lib.get_symbol("sb.busbar")
    attrs = {a.key: a for a in base.attributes}
    assert all(k in attrs and attrs[k].default == "" for k in PARAM_KEYS)   # nová sběrnice z knihovny = pevná


@pytest.mark.parametrize("n", [1, 2, 6, 7, 9, 12, 20])
def test_parametric_geometry(lib, n):
    base = lib.get_symbol("sb.busbar")
    e = Element("sb.busbar", 165, 175, attrs={"taps": str(n)})
    sym = element_symbol(Project(), e, lib)
    ports = {p.name: p for p in sym.ports}
    for k in range(1, n + 1):
        b, t = ports[f"B{k}"], ports[f"T{k}"]
        assert (b.x, b.y, b.dir) == (B1_X + DEFAULT_PITCH * (k - 1), -5, "S")
        assert (t.x, t.y, t.dir) == (b.x, 5, "N")
    assert f"B{n + 1}" not in ports and "4" not in ports
    assert ports["1"].x == ports["B1"].x - 45 and ports["2"].x == ports["B1"].x - 22.5
    assert ports["3"].x == ports[f"B{n}"].x + 37.5 and ports["3"].dir == "S"
    assert all(abs(p.x / 2.5 - round(p.x / 2.5)) < 1e-9 for p in sym.ports)       # porty na mřížce
    lo, hi = line_span(sym)
    assert lo == ports["IN"].x == min(p.x for p in sym.ports) - 0.0
    assert hi == max(p.x for p in sym.ports) + 7.5 and line_end(sym) == hi
    assert sym.label_pos[0] == lo
    assert sym.attributes == base.attributes                                    # vlastnosti jako knihovní značka


def test_layout_attributes_and_used_ports():
    e = Element("sb.busbar", 0, 0, attrs={"taps": "2", "outs": "3", "tap_pitch": "45"})
    lay = layout_of(e)
    assert lay == BusLayout(2, 3, 45.0)
    assert [lay.out_x(n) for n in ("3", "4", "5")] == [-15 + 37.5, -15 + 37.5 + 45, -15 + 37.5 + 90]
    assert lay.right_out_name(lay.out_x("4")) == "4" and lay.right_out_name(0.1) is None
    # neplatná rozteč (mimo mřížku / příliš malá) → výchozí
    for bad in ("31", "5", "abc", "-30"):
        assert layout_of(Element("sb.busbar", 0, 0, attrs={"taps": "2", "tap_pitch": bad})).pitch == DEFAULT_PITCH
    # vodiče na porty za počtem z atributu sběrnici prodlouží (nic se neodpojí)
    lay = layout_of(e, {"B9", "T4", "7", "IN", "1"})
    assert (lay.taps, lay.outs) == (9, 5)
    assert layout_of(Element("fve.spd", 0, 0, attrs={"taps": "3"})) is None


def test_used_port_extends_symbol_no_orphans(lib):
    from envocad.model.project import Wire, WireEnd
    p = Project()
    s = p.sheets[0]
    bus = Element("sb.busbar", 100, 100, attrs={"taps": "1"})
    f = Element("fve.breaker_mcb", 160, 60, rotation=90)
    s.elements += [bus, f]
    s.wires.append(Wire(WireEnd(f.id, "2"), WireEnd(bus.id, "B3")))
    sym = element_symbol(p, bus, lib)
    assert "B3" in {q.name for q in sym.ports} and not any(q.name.endswith("?") for q in sym.ports)
    assert sym.port("3").x == sym.port("B3").x + 37.5


# ---- staré projekty a vlastní makra ------------------------------------------------------------------------------
def test_old_project_busbar_unchanged(lib):
    raw = json.loads((DATA / "v12_feeds.ecp").read_text(encoding="utf-8"))
    p = Project.from_dict(raw)
    buses = [(s, e) for s in p.sheets for e in s.elements if e.symbol_id == "sb.busbar"]
    assert buses
    base = lib.get_symbol("sb.busbar")
    for s, e in buses:
        assert not any(k in e.attrs for k in PARAM_KEYS)
        sym = element_symbol(p, e, lib)
        assert [(q.name, q.x, q.y) for q in sym.ports if not q.name.endswith("?")] == \
               [(q.name, q.x, q.y) for q in base.ports]
        assert sym.primitives == base.primitives
    assert p.to_dict()["sheets"] == Project.from_dict(raw).to_dict()["sheets"]


def test_legacy_custom_macros_keep_fixed_busbar(lib, tmp_path, monkeypatch):
    """Vlastní makra ve starém rozložení (v2, přívod shora T{k}): sběrnice bez atributu = pevná geometrie."""
    import shutil

    from chain_data import build_project  # F2: In stávajících článků zadané

    from envocad.library import macros
    d = tmp_path / "macros"
    d.mkdir()
    for f in (DATA / "macros_v2").glob("*.json"):
        shutil.copy(f, d / f.name)
    monkeypatch.setattr(macros, "user_dir", lambda: d)
    monkeypatch.setattr(macros, "shared_dir", lambda: None)
    p = build_project({"inverters": [{"ref": f"T{i + 1}", **INV, "strings": [20]} for i in range(3)],
                       "macros": {"ac_feed": "AC přívod střídače firemní", "ac_core": "AC jádro rozvaděče firemní"}})
    s = next(s for s in p.sheets if s.loc == "RFVE.AC")
    assert layout_of(_bus(s)) is None


def test_custom_from_below_macro_without_attribute_keeps_old_layout(lib, tmp_path, monkeypatch):
    """Vlastní makra „zespodu“ uložená z dřívějších vestavěných maker (v3, sběrnice bez `taps`, jádro na vývody 1 a 4
    s lomy; `data/macros_v3_fixed_bus/`): generátor sběrnici na parametrickou nemění a rozložení je jako dřív
    (B7…B12 se schody, bez křížení, bez nálezů)."""
    import shutil

    from chain_data import build_project  # F2: In stávajících článků zadané

    from envocad.library import macros
    d = tmp_path / "macros"
    d.mkdir()
    for f in (DATA / "macros_v3_fixed_bus").glob("*.json"):
        shutil.copy(f, d / f.name)
    monkeypatch.setattr(macros, "user_dir", lambda: d)
    monkeypatch.setattr(macros, "shared_dir", lambda: None)
    for n in (2, 9):
        p = build_project({"inverters": [{"ref": f"T{i + 1}", **INV, "strings": [20]} for i in range(n)],
                           "macros": {"ac_feed": "AC přívod střídače firemní", "ac_core": "AC jádro rozvaděče firemní"}})
        s = next(s for s in p.sheets if s.loc == "RFVE.AC")
        bus = _bus(s)
        assert layout_of(bus) is None
        assert element_symbol(p, bus, lib).ports == lib.get_symbol("sb.busbar").ports
        assert _crossings(p, s, lib) == []
        assert not [f for f in check_project(p, lib, standard_paper="A4") if f.sheet_id == s.id and f.severity in (ERROR, WARNING)]


# ---- generátor: RFVE.AC a RFVE rodinného domu ---------------------------------------------------------------------
@pytest.mark.parametrize("use_macros", [True, False], ids=["makra", "kod"])
@pytest.mark.parametrize("n", [1, 2, 6, 7, 9, 12])
def test_rfve_ac_branches_straight(lib, n, use_macros):
    from chain_data import build_project  # F2: In stávajících článků zadané
    spec = {"inverters": [{"ref": f"T{i + 1}", **INV, "strings": [20]} for i in range(n)]}
    if not use_macros:
        spec["macros"] = {"ac_feed": "", "ac_core": ""}
    p = build_project(spec)
    s = next(s for s in p.sheets if s.loc == "RFVE.AC")
    bus = _bus(s)
    # síťová ochrana nad 30 kWp (F2, krok 8): vývod 4 za hlavním vypínačem (n × 9 kWp)
    gp = next((e for e in s.elements if e.symbol_id == "fve.grid_protection"), None)
    assert (gp is not None) == (n * 9 > 30)
    assert layout_of(bus) == BusLayout(n, 2 if gp else 1, 30.0)
    wires = _branch_wires(s)
    assert len(wires) >= 2 * n + 4
    assert _bent(p, s, lib, wires) == []
    assert all(not w.points for w in wires)
    assert _crossings(p, s, lib) == []
    # každý přívod B{k} nad svým jističem, hlavní vypínač pod vývodem 3
    sym = element_symbol(p, bus, lib)
    q = next(e for e in s.elements if e.symbol_id == "sb.main_switch")
    assert q.x == bus.x + sym.port("3").x
    last = gp if gp is not None else q
    if gp is not None:
        assert gp.x == bus.x + sym.port("4").x
    assert line_end(sym) + bus.x == last.x + 7.5           # sběrnice končí za posledním vývodem (vypínač / ochrana)
    bad = [(f.code, f.text) for f in check_project(p, lib, standard_paper="A4") if f.severity in (ERROR, WARNING)]
    assert bad == []


@pytest.mark.parametrize("n", [1, 3])
def test_rfve_house_branches_straight(lib, n):
    from chain_data import build_project  # F2: In stávajících článků zadané
    p = build_project({"building": "house",
                       "inverters": [{"ref": f"T{i + 1}", **HOUSE_INV, "strings": [12, 12] if n == 1 else [12]}
                                     for i in range(n)]})
    s = next(s for s in p.switchboards() if s.loc == "RFVE")
    bus = _bus(s)
    assert layout_of(bus) is not None
    assert _bent(p, s, lib, _branch_wires(s)) == []
    assert _crossings(p, s, lib) == []
    # DC část vpravo za koncem sběrnice, PE svodičů DC vede kolem levého konce sběrnice (neprotne ji)
    lo, hi = line_span(element_symbol(p, bus, lib))
    from envocad.model.routing import route_sheet
    r = route_sheet(p, s, lib)
    for w in s.wires:
        if bus.id in (w.a.element_id, w.b.element_id):
            continue
        for (x0, y0), (x1, y1) in zip(r[w.id], r[w.id][1:], strict=False):
            if x0 == x1 and min(y0, y1) < bus.y < max(y0, y1):
                assert not bus.x + lo <= x0 <= bus.x + hi, w.id
    # 3 střídače: vícepól RFVE měl překryv textů už se sběrnicí pevné délky (nesouvisí se sběrnicí – otevřené)
    known = {"mp_text_overlap"} if n == 3 else set()
    bad = [(f.code, f.text) for f in check_project(p, lib, standard_paper="A4")
           if f.sheet_id == s.id and f.severity in (ERROR, WARNING) and f.code not in known]
    assert bad == []



_NO_MACROS = {"dc_tech": "", "dc_route": "", "ac_feed": "", "ac_core": ""}


def _house_spec(n: int, **extra) -> dict:
    return {"building": "house", **extra,
            "inverters": [{"ref": f"T{i + 1}", **HOUSE_INV, "strings": [12, 12] if n == 1 else [12]} for i in range(n)]}


_ALL_SWITCHBOARD_CASES = {
    "rd1": _house_spec(1),
    "rd3": _house_spec(3),
    "rd1_kod": _house_spec(1, macros=_NO_MACROS),
    "rd3_kod": _house_spec(3, macros=_NO_MACROS),
    "rd1_svorky": _house_spec(1, ac={"distribution": "terminals"}),
    "rd1_svorky_kod": _house_spec(1, ac={"distribution": "terminals"}, macros=_NO_MACROS),
    **{f"firma{n}{suf}": {"inverters": [{"ref": f"T{i + 1}", **INV, "strings": [20]} for i in range(n)], **extra}
       for n in (1, 2, 9, 12) for suf, extra in (("", {}), ("_kod", {"macros": _NO_MACROS}))},
}


@pytest.mark.parametrize("case", sorted(_ALL_SWITCHBOARD_CASES))
def test_switchboards_no_crossing_without_node(lib, case):
    """Na žádném generovaném listu rozvaděče se vodiče nekříží – ani úsekem přes úsek (`_crossings`), ani odbočkami
    ze všech čtyř stran v jednom bodě bez uzlu (`_cross_nodes`; RFVE: PE svodičů DC zleva a PE svodiče AC zprava na
    vodiči vývod 1 → XPE). Kontrola projektu (F7) na listech rozvaděčů bez chyb a varování."""
    from chain_data import build_project  # F2: In stávajících článků zadané
    p = build_project(_ALL_SWITCHBOARD_CASES[case])
    sheets = p.switchboards()
    assert sheets
    for s in sheets:
        assert _crossings(p, s, lib) == [], s.loc
        assert _cross_nodes(p, s, lib) == [], s.loc
    ids = {s.id for s in sheets}
    # rd3: vícepól RFVE má překryv textů nezávisle na trasování (viz test_rfve_house_branches_straight – otevřené)
    known = {"mp_text_overlap"} if case.startswith("rd3") else set()
    bad = [(f.code, f.text) for f in check_project(p, lib, standard_paper="A4")
           if f.sheet_id in ids and f.severity in (ERROR, WARNING) and f.code not in known]
    assert bad == []


def test_house_pe_branches_join_xpe_as_tees(lib):
    """RFVE rodinného domu: PE svodičů DC přichází zleva k vodiči vývod 1 → XPE výš než PE svodiče AC zprava –
    dvě odbočky „T“ místo jednoho bodu se čtyřmi směry."""
    from chain_data import build_project  # F2: In stávajících článků zadané

    from envocad.model.routing import route_sheet
    p = build_project(_house_spec(1))
    s = next(s for s in p.switchboards() if s.loc == "RFVE")
    xpe = next(e for e in s.elements if e.attrs.get("ref") == "XPE")
    r = route_sheet(p, s, lib)
    joins = {}
    for w in s.wires:
        if not w.touches(xpe.id) or len(r[w.id]) < 3:
            continue
        # poslední vodorovný úsek před XPE: y odbočky a strana, ze které přichází
        pts = r[w.id] if w.b.element_id == xpe.id else r[w.id][::-1]
        hz = [(a, b) for a, b in pairwise(pts) if a[1] == b[1] and a[0] != b[0]]
        if hz:
            a, b = hz[-1]
            assert b[0] == xpe.x
            joins.setdefault("W" if a[0] < b[0] else "E", set()).add(a[1])
    assert set(joins) == {"W", "E"}
    assert len(joins["W"]) == len(joins["E"]) == 1
    assert joins["W"] != joins["E"]

# ---- šablona „AC rozvaděč FVE“ -------------------------------------------------------------------------------------
@pytest.mark.parametrize("n_out", ["1", "3", "9"])
def test_ac_template_branches_straight(lib, n_out):
    from envocad.library.templates import apply_template
    p = Project()
    blk = Element("fve.switchboard", 100, 100, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"n_out": n_out}, lib=lib, standard_paper="A4")
    bus = _bus(sb)
    assert layout_of(bus) == BusLayout(1, int(n_out), 30.0)
    bus_wires = [w for w in sb.wires if w.touches(bus.id)]
    assert len(bus_wires) == int(n_out) + 3
    assert _bent(p, sb, lib, bus_wires) == []
    assert _crossings(p, sb, lib) == []
    assert not [f for f in check_project(p, lib, standard_paper="A4") if f.sheet_id == sb.id and f.severity in (ERROR, WARNING)]


# ---- vícepól -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("case", ["ac9", "house"])
def test_multipole_with_parametric_bus(lib, case):
    from chain_data import build_project  # F2: In stávajících článků zadané

    from envocad.model import multipole as mp
    from envocad.model.multipole_geometry import multipole_geometry
    if case == "ac9":
        p = build_project({"inverters": [{"ref": f"T{i + 1}", **INV, "strings": [20]} for i in range(9)]})
        s = next(s for s in p.sheets if s.loc == "RFVE.AC")
    else:
        p = build_project({"building": "house", "inverters": [{"ref": "T1", **HOUSE_INV, "strings": [12, 12]}]})
        s = next(s for s in p.sheets if s.loc == "RFVE")
    poles = mp.sheet_poles(s, lambda e: element_symbol(p, e, lib))
    bus = _bus(s)
    assert poles[bus.id].symbol.ports == element_symbol(p, bus, lib).ports
    geo = multipole_geometry(p, s, lib, standard_paper="A4")
    # každá žíla odbočky sběrnice ve vícepólu (L1 L2 L3 N PE přívodů, L1…N SPD, PE XPE, hlavní vypínač)
    assert geo.prims
    assert not [f for f in check_project(p, lib, standard_paper="A4") if f.sheet_id == s.id and f.code.startswith("mp_")]


# ---- vestavěná makra a značka: přegenerování beze změny --------------------------------------------------------------
def _tool(name: str):
    import importlib.util
    path = Path(__file__).parent.parent / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_tool_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_builtin_macros_regenerate_without_diff():
    g = _tool("gen_builtin_macros")
    for name, desc, fn in g.MACROS:
        slug = name.lower().replace(" → ", "_").replace(" ", "_")
        for a, b in (("í", "i"), ("č", "c"), ("ř", "r"), ("ě", "e"), ("ý", "y"), ("á", "a")):
            slug = slug.replace(a, b)
        path = g.OUT / f"{slug}.json"
        assert g.macro_data(name, desc, g._keep_ids(path, fn())) == json.loads(path.read_text("utf-8")), name
    core = json.loads((g.OUT / "ac_jadro_rozvadece.json").read_text("utf-8"))["fragment"]
    bus = next(e for e in core["elements"] if e["symbol_id"] == "sb.busbar")
    assert bus["attrs"]["taps"] == "1"
    assert all(not w["points"] for w in core["wires"] if bus["id"] in (w["a"]["element_id"], w["b"]["element_id"]))


def test_busbar_symbol_json_matches_generator():
    g = _tool("gen_builtin_fve")
    src = next(d for d in g.SYMBOLS if d["id"] == "sb.busbar")
    data = json.loads((Path(__file__).parent.parent / "envocad" / "library" / "builtin" / "switchboard"
                       / "sb.busbar.json").read_text("utf-8"))
    assert json.loads(json.dumps(src)) == data
    assert {a["key"] for a in data["attributes"]} >= set(PARAM_KEYS)


def test_element_symbol_busbar_only_with_taps(lib, monkeypatch):
    """`element_symbol`: sběrnice bez (nebo s prázdným) `taps` = značka z knihovny bez volání `busbar_symbol`;
    použité porty se počítají jednou."""
    from envocad.model import project as prj
    calls = {"bus": 0, "used": 0}
    real_bus, real_used = prj.busbar_symbol, prj._used_ports
    monkeypatch.setattr(prj, "busbar_symbol", lambda *a: calls.__setitem__("bus", calls["bus"] + 1) or real_bus(*a))
    monkeypatch.setattr(prj, "_used_ports", lambda *a: calls.__setitem__("used", calls["used"] + 1) or real_used(*a))
    p = Project()
    s = p.sheets[0]
    fixed = Element("sb.busbar", attrs={"ref": "", "taps": " "})
    para = Element("sb.busbar", attrs={"ref": "", "taps": "3"})
    s.elements += [fixed, para]
    assert element_symbol(p, fixed, lib) is lib.get_symbol("sb.busbar")
    assert calls == {"bus": 0, "used": 1}
    assert element_symbol(p, para, lib).port("B3").x == B1_X + 2 * DEFAULT_PITCH
    assert calls == {"bus": 1, "used": 2}
