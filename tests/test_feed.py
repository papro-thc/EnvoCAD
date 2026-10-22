"""Jedna značka přívodu/vývodu `sb.feed` (+ `dir`) – model, migrace v12 → v13, makra, knihovna (bez Qt).

Návrh: docs/design/znacka_privod_vyvod.md.
"""
from __future__ import annotations

import copy
import json
import sqlite3
from itertools import pairwise
from pathlib import Path

import pytest

from envocad.library import macros
from envocad.library.macros import MACRO_VERSION, load_macro, parse_macro
from envocad.library.store import LibraryStore
from envocad.model import project as prj
from envocad.model.checks import check_project
from envocad.model.designation import element_name
from envocad.model.feed import (
    FEED_ARROW_IN,
    FEED_ARROW_OUT,
    FEED_SYMBOL,
    LEGACY_FEEDS,
    MP_LEGACY_ATTR,
    feed_dir,
    feed_dir_valid,
    feed_link_key,
    is_feed,
    is_feed_in,
    is_feed_out,
    normalize_legacy_element,
    normalize_legacy_fragment,
)
from envocad.model.project import (
    FORMAT_VERSION,
    Element,
    Project,
    Sheet,
    Wire,
    WireEnd,
    element_symbol,
    migrate,
    paste_fragment,
    sync_feed_links,
)
from envocad.model.symbol import Attribute, place_dir

pytestmark = pytest.mark.usefixtures("ac_builtin")   # AC listy vestavěným kódem (standard `ac_builtin`)

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "lib.db")


# ---- predikáty ---------------------------------------------------------------------------------------------------
def test_predicates_and_default_direction():
    e_in = Element(FEED_SYMBOL, attrs={"dir": "in"})
    e_out = Element(FEED_SYMBOL, attrs={"dir": "out"})
    blank = Element(FEED_SYMBOL)
    bad = Element(FEED_SYMBOL, attrs={"dir": "nahoru"})
    other = Element("sb.terminal_block", attrs={"dir": "out"})
    assert [feed_dir(x) for x in (e_in, e_out, blank, bad)] == ["in", "out", "in", "in"]
    assert is_feed_in(e_in) and is_feed_in(blank) and is_feed_out(e_out) and not is_feed_out(e_in)
    assert not is_feed(other) and not is_feed_out(other) and not is_feed_in(other)
    assert feed_dir(Element(FEED_SYMBOL, attrs={"dir": " OUT "})) == "out"
    assert feed_dir_valid(blank) and feed_dir_valid(e_out) and not feed_dir_valid(bad)
    assert feed_link_key(e_in) == "from" and feed_link_key(e_out) == "to"
    assert element_name(e_in) == "přívod" and element_name(e_out) == "vývod"
    assert is_feed({"symbol_id": FEED_SYMBOL}) and feed_dir({"symbol_id": FEED_SYMBOL, "attrs": {"dir": "out"}}) == "out"


@pytest.mark.parametrize("sid", sorted(LEGACY_FEEDS))
@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_normalize_legacy_keeps_port(lib, sid, rot):
    """sb.feed_in/out × rot 0/90/180/270 → sb.feed: port 1 na stejném místě se stejným směrem (i zrcadlený)."""
    old_port = {"sb.feed_in": (0.0, -5.0, "S"), "sb.feed_out": (0.0, 5.0, "N")}[sid]
    for mirror in (False, True):
        d = {"id": "a", "symbol_id": sid, "x": 50, "y": 100, "rotation": rot, "mirror": mirror, "attrs": {"ref": "X1"}}
        assert normalize_legacy_element(d) and d["symbol_id"] == FEED_SYMBOL
        assert d["attrs"] == {"ref": "X1", "dir": LEGACY_FEEDS[sid][0]}
        e = Element.from_dict(d)
        sym = element_symbol(Project(), e, lib)
        from envocad.model.symbol import place_point
        ox, oy = place_point(old_port[0], old_port[1], rot, mirror)
        assert e.port_pos(sym, "1") == pytest.approx((50 + ox, 100 + oy))
        assert place_dir(sym.port("1").dir, e.rotation, e.mirror) == place_dir(old_port[2], rot, mirror)
    assert not normalize_legacy_element({"symbol_id": "sb.feed", "attrs": {}})
    assert not normalize_legacy_element({"symbol_id": "fve.fuse"})


def test_normalize_fragment_counts():
    frag = {"elements": [{"symbol_id": "sb.feed_in"}, {"symbol_id": "sb.feed_out", "rotation": 90}, {"symbol_id": "x"}]}
    assert normalize_legacy_fragment(frag) == 2
    assert [(d["symbol_id"], d.get("rotation"), d.get("attrs")) for d in frag["elements"]] == [
        (FEED_SYMBOL, 180, {"dir": "in"}), (FEED_SYMBOL, 90, {"dir": "out"}), ("x", None, None)]
    assert normalize_legacy_fragment(None) == 0


# ---- značka a odvozený obrázek -----------------------------------------------------------------------------------
def test_symbol_json_and_choices(lib):
    sym = lib.get_symbol(FEED_SYMBOL)
    assert [(p.name, p.x, p.y, p.dir) for p in sym.ports] == [("1", 0, 5, "N")]
    assert not sym.validate()
    dir_attr = next(a for a in sym.attributes if a.key == "dir")
    assert dir_attr.default == "in" and not dir_attr.show
    assert dir_attr.choice_items() == [("in", "přívod"), ("out", "vývod")]
    assert not any(p.get("type") == "text" for p in sym.primitives)      # směr jen šipkou, bez PŘÍVOD/VÝVOD
    assert FEED_ARROW_IN in sym.primitives
    for sid in LEGACY_FEEDS:
        assert not lib.has_symbol(sid)


def test_attribute_choices_roundtrip():
    a = Attribute("dir", "Směr", "in", choices=[["in", "přívod"], "out"])
    assert a.choice_items() == [("in", "přívod"), ("out", "out")]
    assert Attribute(**a.to_dict()) == a
    assert "choices" not in Attribute("x", "X").to_dict()      # bez nabídky se klíč neukládá


def test_feed_symbol_by_direction(lib):
    p = Project()
    e_in = Element(FEED_SYMBOL, attrs={"ref": "X1", "dir": "in", "from": "W1 T1:AC", "to": "staré"})
    e_out = Element(FEED_SYMBOL, attrs={"ref": "X2", "dir": "out", "from": "staré", "to": "W2 DS:1"})
    s_in, s_out = element_symbol(p, e_in, lib), element_symbol(p, e_out, lib)
    assert FEED_ARROW_IN in s_in.primitives and FEED_ARROW_OUT not in s_in.primitives
    assert FEED_ARROW_OUT in s_out.primitives and FEED_ARROW_IN not in s_out.primitives
    assert s_in.label_lines(e_in.attrs) == ["W1 T1:AC"]
    assert s_out.label_lines(e_out.attrs) == ["W2 DS:1"]
    assert s_in.ports == s_out.ports
    # popisek vpravo od svorky: přívod portem nahoru (rot 0) i převedený přívod portem dolů (rot 180)
    from envocad.model.symbol import rotate_point
    for rot in (0, 180):
        e = Element(FEED_SYMBOL, rotation=rot, attrs={"dir": "in"})
        assert rotate_point(*element_symbol(p, e, lib).label_pos, rot)[0] > 0
    assert lib.get_symbol(FEED_SYMBOL).primitives == s_in.primitives      # náhled z palety = přívod


def test_check_reports_invalid_direction(lib):
    p = Project()
    s = p.sheets[0]
    f = Element(FEED_SYMBOL, attrs={"ref": "X1", "dir": "nahoru"})
    s.elements.append(f)
    codes = {x.code for x in check_project(p, lib, standard_paper="A4")}
    assert "feed_dir" in codes
    f.attrs["dir"] = "out"
    assert "feed_dir" not in {x.code for x in check_project(p, lib, standard_paper="A4")}


# ---- migrace v12 → v13 -------------------------------------------------------------------------------------------
def _v12_project_dict() -> dict:
    return json.loads((DATA / "v12_feeds.ecp").read_text(encoding="utf-8"))


def test_v12_project_opens_with_same_port_positions(lib):
    """Starý projekt v12 (vygenerovaný starou verzí, přípojka VN: HR, RVN s přívodem rot 180, RE, RFVE.AC, RFVE.DC
    a ruční přívody/vývody otočené o 90/270°): po otevření leží každý konec vodiče na stejném místě se stejným
    směrem portu jako ve staré verzi (`v12_feeds_ports.json`), nic se nerozpojí."""
    raw = _v12_project_dict()
    assert raw["format_version"] == 12
    assert any(e["symbol_id"] == "sb.feed_in" for s in raw["sheets"] for e in s["elements"])
    expected = json.loads((DATA / "v12_feeds_ports.json").read_text(encoding="utf-8"))
    p = Project.from_dict(raw)
    got = {}
    for s in p.sheets:
        assert not any(e.symbol_id in LEGACY_FEEDS for e in s.elements)
        for w in s.wires:
            for end in (w.a, w.b):
                e = s.element(end.element_id)
                sym = element_symbol(p, e, lib)
                x, y = e.port_pos(sym, end.port)
                got[f"{w.id}:{end.element_id}:{end.port}"] = [round(x, 3), round(y, 3),
                                                              place_dir(sym.port(end.port).dir, e.rotation, e.mirror)]
    assert got == expected
    findings = check_project(p, lib, standard_paper="A4")
    assert not [f for f in findings if f.code in ("bad_port", "dangling", "symbol", "feed_dir")]
    # RVN: přívod z DS byl sb.feed_in rot 180 → sb.feed rot 0 (port nahoře, kabel zespodu)
    rvn = next(s for s in p.sheets if s.loc == "RVN")
    assert {(e.rotation, feed_dir(e)) for e in rvn.elements if is_feed_in(e)} == {(0, "in")}


def test_v12_migration_lossless_roundtrip_and_links():
    raw = _v12_project_dict()
    before = copy.deepcopy(raw)
    p = Project.from_dict(raw)
    assert raw == before                                   # vstup se nemění
    d = p.to_dict()
    assert d["format_version"] == FORMAT_VERSION
    assert Project.from_dict(d).to_dict() == d
    # nic kromě id značky, rotace přívodu a `dir` se nezměnilo (polohy, vodiče s `points`, mp_pos, vazby)
    mig = migrate(raw, 12)
    for so, sn in zip(raw["sheets"], mig["sheets"], strict=True):
        assert so["wires"] == sn["wires"]
        for eo, en in zip(so["elements"], sn["elements"], strict=True):
            if eo["symbol_id"] in LEGACY_FEEDS:
                direction, turn = LEGACY_FEEDS[eo["symbol_id"]]
                assert en["symbol_id"] == FEED_SYMBOL
                assert en["attrs"] == {**eo["attrs"], "dir": direction, MP_LEGACY_ATTR: "1"}
                assert en["rotation"] == (eo.get("rotation", 0) + turn) % 360
                assert {k: v for k, v in en.items() if k not in ("symbol_id", "rotation", "attrs")} == \
                    {k: v for k, v in eo.items() if k not in ("symbol_id", "rotation", "attrs")}
            else:
                assert eo == en
    # vazby přívodů na vodiče JPS: plná synchronizace po načtení nic nemění
    q = Project.from_dict(d)
    sync_feed_links(q)
    assert q.to_dict() == d


def test_v13_rejected_by_older_program(monkeypatch):
    """Soubor v13 starší program (FORMAT_VERSION 12) odmítne – `sb.feed` tak tiše nezmizí při uložení."""
    d = {**Project().to_dict(), "format_version": 13}
    monkeypatch.setattr(prj, "FORMAT_VERSION", 12)
    with pytest.raises(ValueError, match="novější verze"):
        Project.from_dict(d)


# ---- makra a schránka --------------------------------------------------------------------------------------------
_LEGACY_FRAG = {"elements": [
    {"id": "a", "symbol_id": "sb.feed_in", "x": 0, "y": 40, "rotation": 0, "attrs": {"ref": "X{k}", "desc": "od G{k}"}},
    {"id": "b", "symbol_id": "sb.feed_out", "x": 0, "y": 0, "rotation": 0, "attrs": {"ref": "X9"}}],
    "wires": [{"id": "w", "a": {"element_id": "a", "port": "1"}, "b": {"element_id": "b", "port": "1"},
               "conductors": ["L+", "L-"]}]}


@pytest.mark.parametrize("version", [None, 2])
def test_legacy_macro_v1_v2_loads_as_sb_feed(tmp_path, lib, version):
    data = {"name": "starý string", "fragment": copy.deepcopy(_LEGACY_FRAG)}
    if version:
        data["version"] = version
    path = tmp_path / "stary.json"
    text = json.dumps(data, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    m = load_macro(path)
    assert m is not None
    assert [(d["symbol_id"], d["rotation"], d["attrs"].get("dir")) for d in m.fragment["elements"]] == [
        (FEED_SYMBOL, 180, "in"), (FEED_SYMBOL, 0, "out")]
    assert path.read_text(encoding="utf-8") == text            # soubor sdílené knihovny se nepřepisuje
    p = Project()
    vals, errs = macros.resolve_values(m, given={"k": "1"})
    assert not errs
    els, wires = macros.expand(p, p.sheets[0], m, vals, ref_prefix_of=lambda sid: lib.get_symbol(sid).iec_ref)
    assert [(e.symbol_id, feed_dir(e), e.ref) for e in els] == [(FEED_SYMBOL, "in", "X1"), (FEED_SYMBOL, "out", "X9")]
    assert len(wires) == 1


def test_macro_version_three_and_newer_rejected(tmp_path):
    assert MACRO_VERSION == 3
    path = tmp_path / "novy.json"
    path.write_text(json.dumps({"version": 4, "name": "x", "fragment": {"elements": [], "wires": []}}), encoding="utf-8")
    assert load_macro(path) is None
    m = parse_macro({"version": 3, "name": "y", "fragment": {"elements": [], "wires": []}})
    assert m.version == 3


def test_saved_macro_is_v3(tmp_path, monkeypatch):
    monkeypatch.setattr(macros, "user_dir", lambda: tmp_path / "m")
    monkeypatch.setattr(macros, "shared_dir", lambda: None)
    path = macros.save_macro("Přívod", "", {"elements": [{"id": "a", "symbol_id": FEED_SYMBOL, "x": 0, "y": 0,
                                                          "attrs": {"ref": "X1", "dir": "in"}}], "wires": []})
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 3


def test_paste_legacy_clipboard_fragment(lib):
    p = Project()
    els, wires = paste_fragment(p, copy.deepcopy(_LEGACY_FRAG), lambda sid: lib.get_symbol(sid).iec_ref, 0, 0)
    assert [(e.symbol_id, e.rotation, feed_dir(e)) for e in els] == [(FEED_SYMBOL, 180, "in"), (FEED_SYMBOL, 0, "out")]
    assert wires[0].a.element_id == els[0].id and wires[0].b.element_id == els[1].id


def test_builtin_macros_use_sb_feed():
    for m in macros.list_macros():
        if m.source != "vestavěné":
            continue
        data = json.loads(m.path.read_text(encoding="utf-8"))
        assert data["version"] == MACRO_VERSION
        assert not [d for d in data["fragment"]["elements"] if d["symbol_id"] in LEGACY_FEEDS], m.name


# ---- knihovna ----------------------------------------------------------------------------------------------------
def test_sync_builtin_removes_legacy_rows(tmp_path):
    db = tmp_path / "lib.db"
    store = LibraryStore(db)
    store.conn.execute("INSERT INTO symbols(id,name,category,builtin,data) VALUES(?,?,?,?,?)",
                       ("sb.feed_in", "Přívod", "Svorky", 1, json.dumps({"id": "sb.feed_in", "name": "Přívod"})))
    store.conn.execute("INSERT INTO symbols(id,name,category,builtin,data) VALUES(?,?,?,?,?)",
                       ("sb.feed_out", "Můj vývod", "Svorky", 0, json.dumps({"id": "sb.feed_out", "name": "Můj vývod"})))
    store.conn.commit()
    store.close()
    store = LibraryStore(db)
    ids = {r[0] for r in store.list_symbols()}
    assert "sb.feed_in" not in ids          # vestavěný řádek staré značky pryč
    assert "sb.feed_out" in ids             # uživatelská značka se stejným id zůstává
    assert FEED_SYMBOL in ids
    store.close()
    # bez starých řádků sync nic nezapisuje (nedrží zámek databáze)
    store = LibraryStore(db)
    other = sqlite3.connect(str(db), timeout=0.1)
    other.execute("BEGIN IMMEDIATE")
    other.rollback()
    other.close()
    store.close()


# ---- vazby a blok ROZVADĚČ ---------------------------------------------------------------------------------------
def _linked_project():
    """Blok ROZVADĚČ s listem: přívod X1 a vývod X2 navázané přes porty bloku na vodiče JPS."""
    p = Project()
    jps = p.sheets[0]
    t = Element("fve.inverter", 0, 100, attrs={"ref": "T1"})
    blk = Element("fve.switchboard", 100, 100, attrs={"ref": "R1"})
    g = Element("fve.grid", 200, 100, attrs={"ref": ""})
    jps.elements += [t, blk, g]
    sb = Sheet(name="R1", kind="switchboard", parent_element_id=blk.id)
    p.sheets.append(sb)
    blk.attrs["sheet"] = sb.name
    x1 = Element(FEED_SYMBOL, 40, 200, attrs={"ref": "X1", "dir": "in"})
    x2 = Element(FEED_SYMBOL, 40, 100, attrs={"ref": "X2", "dir": "out"})
    sb.elements += [x1, x2]
    w1 = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, "X1"), conductors=["L1", "N", "PE"], attrs={"ref": "W1"})
    w2 = Wire(WireEnd(blk.id, "X2"), WireEnd(g.id, "1"), conductors=["L1", "N", "PE"], attrs={"ref": "W2"})
    jps.wires += [w1, w2]
    sync_feed_links(p)
    return p, blk, x1, x2


def test_block_ports_split_by_direction(lib):
    p, blk, x1, x2 = _linked_project()
    sym = element_symbol(p, blk, lib)
    assert {(q.name, q.dir) for q in sym.ports} == {("X1", "W"), ("X2", "E")}
    assert x1.attrs["from"].startswith("W1 T1:AC") and "to" not in x1.attrs
    assert x2.attrs["to"].startswith("W2 DS:1") and "from" not in x2.attrs
    assert not [f for f in check_project(p, lib, standard_paper="A4") if f.code in ("bad_port", "feed_unlinked")]


def test_feed_dir_followups(lib):
    """Změna směru: odkud ↔ kam se přepočte z vazby; port bloku se přesune na druhou stranu, vodič drží."""
    from envocad.model.project import feed_dir_changes
    p, blk, x1, _x2 = _linked_project()
    sb = p.sheets[1]
    x1.attrs["dir"] = "out"
    ch = feed_dir_changes(p, sb, x1)
    assert ch["to"].startswith("W1 T1:AC") and ch["from"] == ""
    sym = element_symbol(p, blk, lib)
    assert ("X1", "E") in {(q.name, q.dir) for q in sym.ports}
    # bez vazby: ruční text se přesune do klíče nového směru
    q = Project()
    f = Element(FEED_SYMBOL, attrs={"ref": "X5", "dir": "out", "from": "z trafa"})
    q.sheets[0].elements.append(f)
    assert feed_dir_changes(q, q.sheets[0], f) == {"to": "z trafa", "from": ""}
    f.attrs.update({"to": "z trafa", "from": ""})
    assert feed_dir_changes(q, q.sheets[0], f) == {}


# ---- rozložení generátoru: RFVE.AC a RFVE vše zespodu, DC rozvaděče beze změny -----------------------------------
_INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
_HOUSE_INV = {"p_ac": 10, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 16}
_CASES = {
    "firma": {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}, {"ref": "T2", **_INV, "strings": [20]}]},
    "rd": {"building": "house", "inverters": [{"ref": "T1", **_HOUSE_INV, "strings": [12, 12]}]},
    "rd_bez_maker_svorky": {"building": "house", "ac": {"distribution": "terminals"},
                            "macros": {"dc_tech": "", "dc_route": "", "ac_feed": "", "ac_core": ""},
                            "inverters": [{"ref": "T1", **_HOUSE_INV, "strings": [12, 12]}]},
    "bez_maker": {"macros": {"dc_tech": "", "dc_route": "", "ac_feed": "", "ac_core": ""},
                  "inverters": [{"ref": "T1", **_INV, "strings": [20]}, {"ref": "T2", **_INV, "strings": [20]}]},
}


def _crossings(project, sheet, lib) -> list[tuple[str, str]]:
    """Dvojice vodičů, jejichž trasy se kříží (vodorovný přes svislý uvnitř obou úseků)."""
    from envocad.model.routing import route_sheet
    routes = route_sheet(project, sheet, lib)
    segs = {wid: list(pairwise(pts)) for wid, pts in routes.items()}
    out = []
    ids = sorted(segs)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            for (p, q) in segs[a]:
                for (r, t) in segs[b]:
                    h, v = ((p, q), (r, t)) if p[1] == q[1] and r[0] == t[0] else (((r, t), (p, q))
                                                                                if r[1] == t[1] and p[0] == q[0] else (None, None))
                    if h is None:
                        continue
                    x0, x1 = sorted((h[0][0], h[1][0]))
                    y0, y1 = sorted((v[0][1], v[1][1]))
                    if x0 + 0.1 < v[0][0] < x1 - 0.1 and y0 + 0.1 < h[0][1] < y1 - 0.1:
                        out.append((a, b))
    return out


@pytest.mark.parametrize("case", sorted(_CASES))
def test_rfve_everything_from_below(lib, case):
    from envocad.generate import build_project
    p = build_project(_CASES[case])
    for s in p.switchboards():
        feeds = [e for e in s.elements if is_feed(e)]
        if s.loc in ("RFVE.AC", "RFVE"):
            # přívody i vývody ve spodní řadě, port nahoře (kabel zespodu)
            assert {e.rotation for e in feeds} == {0}, s.loc
            assert len({e.y for e in feeds}) == 1, s.loc
            assert {feed_dir(e) for e in feeds} == {"in", "out"}
            assert not _crossings(p, s, lib), s.loc
        elif s.loc.startswith(("RFVE.DC", "RDC")):
            # DC rozvaděče rozložením beze změny: přívod nahoře portem dolů (rot 180), vývody dole
            assert {e.rotation for e in feeds if is_feed_in(e)} == {180}
            assert max(e.y for e in feeds if is_feed_in(e)) > max(e.y for e in feeds if is_feed_out(e))


def test_rfve_multipole_keeps_feeds_on_top(lib):
    """Vícepól se nemění: přívodní větev otočená v listu tokem nahoru se ve vícepólu kreslí shora (otočená zpět)."""
    from envocad.generate import build_project
    from envocad.model import multipole as mp
    p = build_project(_CASES["rd"])
    s = next(s for s in p.switchboards() if s.loc == "RFVE")
    poles = mp.sheet_poles(s, lambda e: element_symbol(p, e, lib))
    for e in s.elements:
        ep = poles[e.id]
        if is_feed_in(e):
            # v souřadnicích starého sb.feed_in (port dole) s rotací 0 – jako dřív
            assert ep.element.rotation == 0 and ep.symbol.ports[0].dir == "S" and mp.feed_cable_up(ep)
        if e.symbol_id in ("fve.breaker_mcb", "fve.fuse_disconnect"):
            assert e.rotation == 90 and ep.element.rotation == 270
        if e.symbol_id == "fve.spd" and "DC" in e.ref:
            assert e.rotation == 180 and ep.element.rotation == 0
        assert ep.element.id == e.id and ep.element.attrs is e.attrs
    flipped = mp.flow_flipped(s, {e.id: mp.element_poles(s, *mp.multipole_feed_view(e, element_symbol(p, e, lib)))
                                  for e in s.elements})
    assert {s.element(i).symbol_id for i in flipped} >= {FEED_SYMBOL, "fve.breaker_mcb", "fve.fuse_disconnect", "fve.spd"}


def test_flow_flipped_nothing_on_classic_sheet(lib):
    """Staré rozložení (přívod nahoře portem dolů, tok dolů): nic se neotáčí."""
    from envocad.generate import build_project
    from envocad.model import multipole as mp
    p = build_project(_CASES["firma"])
    for s in p.switchboards():
        if s.loc.startswith("RFVE.DC"):
            poles = {e.id: mp.element_poles(s, *mp.multipole_feed_view(e, element_symbol(p, e, lib))) for e in s.elements}
            assert mp.flow_flipped(s, poles) == set()


def test_cable_tag_side_follows_rotation(lib):
    """Štítek kabelu ve vícepólu podle otočení (port dolů → kabel a štítek nahoře), ne podle druhu značky."""
    from envocad.model import multipole as mp
    s = Sheet(kind="switchboard")
    up_in = Element(FEED_SYMBOL, rotation=180, attrs={"dir": "in"})       # port dole → kabel shora
    down_in = Element(FEED_SYMBOL, rotation=0, attrs={"dir": "in"})       # port nahoře → kabel zespodu
    out = Element(FEED_SYMBOL, rotation=0, attrs={"dir": "out"})
    out_turned = Element(FEED_SYMBOL, rotation=180, attrs={"dir": "out"})
    res = {}
    for e in (up_in, down_in, out, out_turned):
        ep = mp.element_poles(s, *mp.multipole_feed_view(e, element_symbol(Project(), e, lib)))
        res[e.id] = mp.feed_cable_up(ep)
    assert res[up_in.id] and not res[down_in.id] and not res[out.id] and res[out_turned.id]


def test_ac_template_from_below(lib):
    """Šablona „AC rozvaděč FVE“: přívod X1 dole (port nahoře), hlavní vypínač tokem nahoru do sběrnice / skupiny
    napájení; bez křížení a bez varování."""
    from envocad.library.templates import apply_template
    for dist in ("bus", "terminals"):
        p = Project()
        blk = Element("fve.switchboard", 100, 100, attrs={"ref": "R1"})
        p.sheets[0].elements.append(blk)
        sb = p.create_switchboard_sheet(blk)
        apply_template(p, sb, "ac_fve", {"n_out": "2", "distribution": dist}, lib=lib, standard_paper="A4")
        feeds = [e for e in sb.elements if is_feed(e)]
        assert {e.rotation for e in feeds} == {0} and len({e.y for e in feeds}) == 1
        assert next(e for e in sb.elements if e.symbol_id == "sb.main_switch").rotation == 90
        assert not _crossings(p, sb, lib)
        assert not [f for f in check_project(p, lib, standard_paper="A4") if f.sheet_id == sb.id and f.severity in ("chyba", "varování")]


def test_no_wire_crossings_on_generated_switchboards(lib):
    """Žádný list rozvaděče z generátoru (F7 případy: RFVE.AC, RFVE, RFVE.DC, RDC, HR, RE, RVN) nemá křížení vodičů;
    v HR přichází vodič měřicích obvodů XMI/XMU do svorky zespodu (svorka otočená portem dolů), ne přes kroužek."""
    from test_generate import F7_CASES

    from envocad.generate import build_project
    for name, spec in F7_CASES.items():
        p = build_project(spec)
        for s in p.switchboards():
            assert not _crossings(p, s, lib), (name, s.loc)
            if s.loc == "HR":
                meas = [e for e in s.elements if e.ref in ("XMI", "XMU")]
                assert all(e.rotation == 180 and is_feed_out(e) for e in meas)
