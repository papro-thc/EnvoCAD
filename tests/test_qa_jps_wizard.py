"""Regrese z QA auditu JPS / průvodce (skupina D) – headless části: rozmístění JPS na list, baterie hybridu,
vstupy průvodce, uzel odbočky, navazující číslování maker, přejmenování a smazání bloku rozvaděče, překryvy textů
ve vícepólu, SPD + PE, svazek vodičů u střídače, čitelné názvy prvků bez označení, šum kontroly, výkon kontroly."""
import json
import os
import time
from itertools import pairwise

import pytest
from chain_data import with_existing

from envocad.generate import build_project, parse_number, parse_strings
from envocad.library.store import LibraryStore
from envocad.model.checks import INFO, WARNING, check_project
from envocad.model.feed import is_feed, is_feed_in, is_feed_out
from envocad.model.frame import fit_placement, inner_box, title_block_box
from envocad.model.project import Element, Project, Sheet, Wire, WireEnd, element_symbol
from envocad.model.textlayout import (
    boxes_overlap,
    segment_hits_box,
    sheet_content_boxes,
    symbol_box,
    union_box,
)

pytestmark = pytest.mark.usefixtures("ac_builtin")   # AC listy vestavěným kódem (standard `ac_builtin`)

INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
NO_MACROS = {"dc_tech": "", "dc_route": "", "ac_feed": "", "ac_core": ""}


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _ac(p):
    """List AC rozvaděče FVE (RFVE.AC, u rodinného domu RFVE) – za ním jsou od F2 listy stávajících HR / RD a RE."""
    return next(s for s in p.switchboards() if s.loc in ("RFVE.AC", "RFVE"))


def spec(n=1, per=4, **kw):
    s = {"inverters": [{"ref": f"T{i + 1}", **INV, "strings": [20] * per} for i in range(n)]}
    s.update(kw)
    return with_existing(s)


def _inside(b, box) -> bool:
    return b[0] >= box[0] - 1e-6 and b[1] >= box[1] - 1e-6 and b[2] <= box[2] + 1e-6 and b[3] <= box[3] + 1e-6


# ---- 1. JPS uvnitř vnitřního rámečku -------------------------------------------------------------------------
@pytest.mark.parametrize("n", range(1, 7))
def test_jps_content_inside_inner_frame(lib, n):
    """#1: pro 1–6 střídačů × 4/6/12 stringů leží všechny značky, popisky a vodiče JPS uvnitř vnitřního rámečku
    listu (i při zapnutém rámečku – x ≥ 20 mm) a mimo popisové pole; souřadnice zůstávají na mřížce."""
    for per in (4, 6, 12):
        p = build_project(spec(n, per))
        for s in (x for x in p.sheets if not x.is_switchboard):   # velké JPS je rozdělené na listy
            boxes = sheet_content_boxes(p, s, lib)
            assert _inside(union_box(boxes), inner_box(s.width, s.height)), (n, per, s.name, s.width, s.height)
            tb = title_block_box(s.width, s.height)
            assert not [b for b in boxes if boxes_overlap(b, tb, tol=0.0)], (n, per, s.name)
            assert all(abs(e.x / 2.5 - round(e.x / 2.5)) < 1e-9 and abs(e.y / 2.5 - round(e.y / 2.5)) < 1e-9
                       for e in s.elements)
            if n * per <= 24:   # menší projekty: normalizovaný formát A3–A0, ne vlastní nudle
                assert s.paper in ("A3", "A2", "A1", "A0"), (n, per, s.paper)


def test_fit_placement_paper_and_title_block():
    # malý obsah → A3, na středu, v násobcích mřížky
    name, w, h, dx, dy = fit_placement([(0, 0, 100, 50)])
    assert (name, w, h) == ("A3", 420.0, 297.0) and dx % 2.5 == 0 and dy % 2.5 == 0
    # obsah, který by na středu zasáhl do popisového pole vpravo dole, se posune nahoru
    boxes = [(0, 0, 380, 30), (0, 200, 10, 240)]
    name, w, h, dx, dy = fit_placement(boxes)
    tb = title_block_box(w, h)
    assert not any(boxes_overlap((b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy), tb, tol=0.0) for b in boxes)
    # obří obsah → vlastní formát, který se vejde i s popisovým polem
    name, w, h, dx, dy = fit_placement([(0, 0, 500, 3000)])
    assert name == "vlastní" and _inside((dx, dy, 500 + dx, 3000 + dy), inner_box(w, h))


# ---- 2. baterie u hybridního střídače ------------------------------------------------------------------------
def test_hybrid_battery_below_its_inverter_cable_crosses_nothing(lib):
    p = build_project(spec(3, 4, battery={"e_kwh": 10, "p_kw": 5, "type": "BYD"}))
    # 3 střídače se na A2 nevejdou → JPS na listy; baterie je na listu svého střídače
    s = next(x for x in p.sheets if any(e.ref == "T1" for e in x.elements) and not x.is_switchboard)
    t1 = next(e for e in s.elements if e.ref == "T1")
    bat = next(e for e in s.elements if e.symbol_id == "fve.battery")
    assert t1.symbol_id == "fve.inverter_hybrid" and bat.x == t1.x and bat.y < t1.y
    w = next(w for w in s.wires if w.touches(bat.id))
    from envocad.model.routing import wire_route
    pts = wire_route(p, s, lib, w)
    assert all(abs(a[0] - b[0]) < 1e-6 for a, b in pairwise(pts))   # svisle rovně dolů
    for e in s.elements:
        if e.id in (bat.id, t1.id):
            continue
        box = symbol_box(e, element_symbol(p, e, lib))
        assert not any(segment_hits_box(a, b, box) for a, b in pairwise(pts)), e.ref
    # text BAT hybridního střídače neleží přes kabel baterie
    from envocad.model.textlayout import symbol_text_boxes
    sym = element_symbol(p, t1, lib)
    assert not any(segment_hits_box(a, b, tb) for tb in symbol_text_boxes(t1, sym) for a, b in pairwise(pts))


# ---- 3. vstupy průvodce ---------------------------------------------------------------------------------------
def test_parse_strings_separators_and_errors():
    assert parse_strings("20,20,18; 20 20") == [[20, 20, 18], [20, 20]]
    assert parse_strings("20, 20 ;") == [[20, 20]]
    assert parse_strings("20;;18") == [[20], [18]]
    for bad in ("abc", "20.5,18", "0", "-5,10", "", " ; "):
        with pytest.raises(ValueError) as ex:
            parse_strings(bad)
        assert "Stringy" in str(ex.value)


def test_parse_number_rules():
    assert parse_number("450", "P") == 450 and parse_number("450,5", "P") == 450.5
    assert parse_number("0", "Počet", integer=True, strict=False) == 0
    assert parse_number("", "Délka", strict=False, allow_empty=True) == ""
    for text, kw, word in (("abc", {}, "není číslo"), ("", {}, "zadejte"), ("2.5", {"integer": True}, "celé"),
                           ("-1", {"integer": True, "strict": False}, "alespoň"), ("0", {}, "větší"),
                           ("inf", {}, "není číslo")):
        with pytest.raises(ValueError) as ex:
            parse_number(text, "Pole", **kw)
        assert str(ex.value).startswith("Pole:") and word in str(ex.value)


# ---- 4. uzel odbočky ------------------------------------------------------------------------------------------
def test_junction_has_no_ref_and_free_port_findings(lib):
    p = Project()
    s = p.sheets[0]
    a = Element("fve.breaker_mcb", 50, 100, attrs={"ref": "F1", "type": "x"})
    b = Element("fve.breaker_mcb", 150, 100, attrs={"ref": "F2", "type": "x"})
    j = Element("sb.junction", 100, 100, attrs={"ref": ""})
    s.elements += [a, b, j]
    jsym = element_symbol(p, j, lib)
    s.wires += [Wire(WireEnd(a.id, "2"), WireEnd(j.id, jsym.ports[0].name), conductors=["L1"]),
                Wire(WireEnd(j.id, jsym.ports[1].name), WireEnd(b.id, "1"), conductors=["L1"])]
    fs = [f for f in check_project(p, lib, standard_paper="A4") if f.target_id == j.id]
    codes = {f.code for f in fs}
    assert "no_ref" not in codes and "free_port" not in codes and "unconnected" not in codes
    assert "junction_free" in codes   # odbočka chybí – to hlásí vlastní kontrola uzlu


# ---- 5. navazující číslování maker, duplicitní přívody --------------------------------------------------------
def test_suggest_numbering_dc_and_ac_macros(lib):
    from envocad.library.macros import K_START, expand, find_macro, resolve_values, suggest_numbering
    p = build_project(spec(1, 4))
    rdc = next(s for s in p.sheets if s.name.startswith("RFVE.DC"))
    rh = _ac(p)
    dc = find_macro("DC string v rozvaděči")
    sug = suggest_numbering(p, rdc, dc)
    assert sug == {K_START: "9"}    # X1–X4 přívody, X5–X8 vývody → další volné X9
    vals, errs = resolve_values(dc, given={"n": "2", **sug}, components=lib.component)
    assert not errs
    els, _ = expand(p, rdc, dc, vals, components=lib.component)
    refs = sorted(e.ref for e in els if is_feed(e))
    used = {e.ref for e in rdc.elements}
    assert {"X9", "X10", "X11", "X12"} <= set(refs) and not ({r for r in refs if r != "XPE"} & used)
    ac = find_macro("AC přívod střídače")
    assert suggest_numbering(p, rh, ac) == {"k": "2"}     # X1 obsazen → X2 „od T2“
    # prázdný list → výchozí číslování (nic se nemění)
    empty = Sheet(name="R", kind="switchboard")
    p.sheets.append(empty)
    assert suggest_numbering(p, empty, ac) == {} and suggest_numbering(p, empty, dc) == {}


def test_dup_ref_reports_duplicate_feeds(lib):
    p = build_project(spec(1, 4))
    rh = _ac(p)
    x1 = next(e for e in rh.elements if is_feed_in(e) and e.ref == "X1")
    dup = Element("sb.feed", x1.x + 60, x1.y, rotation=180, attrs={"dir": "in", "ref": "X1", "desc": "od T9"})
    rh.elements.append(dup)
    fs = [f for f in check_project(p, lib, standard_paper="A4") if f.code == "dup_ref"]
    assert {f.target_id for f in fs} >= {x1.id, dup.id}
    assert all("X1" in f.text for f in fs)


# ---- 6. přejmenování: navázané texty --------------------------------------------------------------------------
def test_rename_followups_auto_texts_only():
    from envocad.model.project import apply_text_changes, rename_followups
    p = build_project(spec(2, 2))
    s = p.sheets[0]
    t1 = next(e for e in s.elements if e.ref == "T1")
    rdc1 = next(e for e in s.elements if e.ref == "RDC1")
    rh = next(e for e in s.elements if e.ref == "RFVE.AC")
    rh_sheet = p.switchboard_sheet(rh.id)
    manual = next(e for e in rh_sheet.elements if is_feed_in(e) and e.ref == "X2")
    manual.attrs["desc"] = "od T1 přes jistič"   # ručně psaný text se nemění
    before = p.to_dict()
    ch = rename_followups(p, t1, "T1", "T9")
    apply_text_changes(p, ch)
    descs = [e.attrs.get("desc") for e in rh_sheet.elements if is_feed_in(e)]
    assert "od T9" in descs and "od T1 přes jistič" in descs
    assert rdc1.attrs["desc"] == "DC rozvaděč po trase T9"
    assert p.switchboard_sheet(rdc1.id).name == "RDC1 – DC rozvaděč po trase T9"
    assert rdc1.attrs["sheet"] == p.switchboard_sheet(rdc1.id).name
    apply_text_changes(p, ch, undo=True)
    assert p.to_dict() == before
    # blok rozvaděče: název listu začínající starým označením
    ch = rename_followups(p, rdc1, "RDC1", "RDC7")
    apply_text_changes(p, ch)
    assert p.switchboard_sheet(rdc1.id).name.startswith("RDC7 – ")
    # G1 → „od G1“ / „G1 dál“ / „string G1“ v DC rozvaděčích
    g1 = next(e for e in s.elements if e.ref == "G1")
    texts = {c.new for c in rename_followups(p, g1, "G1", "G99")}
    assert {"od G99", "G99 dál"} <= texts


# ---- 7. list rozvaděče bez bloku ------------------------------------------------------------------------------
def test_switchboard_sheet_without_block_is_warning(lib):
    p = build_project(spec(1, 2))
    s = p.sheets[0]
    rdc1 = next(e for e in s.elements if e.ref == "RDC1")
    sb = p.switchboard_sheet(rdc1.id)
    s.remove_element(rdc1.id)
    fs = [f for f in check_project(p, lib, standard_paper="A4") if f.code == "sb_no_block"]
    assert len(fs) == 1 and fs[0].severity == WARNING and fs[0].sheet_id == sb.id


# ---- 8., 9., 22. vícepól: překryvy textů, SPD + PE, PE lišta --------------------------------------------------
@pytest.mark.parametrize("kw", [{}, {"ac": {"distribution": "terminals"}}, {"macros": NO_MACROS}])
def test_generated_multipole_has_no_text_overlaps(lib, kw):
    from envocad.model.multipole_geometry import multipole_text_overlaps
    p = build_project(spec(2, 4, **kw))
    for s in p.switchboards():
        assert multipole_text_overlaps(p, s, lib, standard_paper="A4") == [], s.name


def test_multipole_device_label_left_of_poles(lib):
    """FU1.1 (svislý tok) je vlevo od prvního pólu, zarovnaný doprava – nepřeškrtne žílu DC+; SPD také."""
    from envocad.model import multipole as mp
    p = build_project(spec(1, 2))
    s = next(x for x in p.sheets if x.name.startswith("RFVE.DC"))
    poles = {e.id: mp.element_poles(s, e, element_symbol(p, e, lib)) for e in s.elements}
    layout = mp.auto_layout(s, poles, x0=mp.MP_X0, y_top=s.height - mp.MP_Y_TOP, page_w=mp.page_width(s))
    for eid, ep in poles.items():
        ep.origin = layout[eid]
    for ref in ("FU1.1", "SPD-DC1.1"):
        ep = next(ep for ep in poles.values() if ep.element.ref == ref)
        lines = mp.pole_label_lines(ep)
        first_x = min(ep.pole_pos(ep.through[0], c)[0] for c in ep.switched)
        assert lines and lines[0][2] == ref and all(a == "right" and x < first_x for x, _y, _t, _h, a in lines)


def test_multipole_overlap_detected():
    """Kontrola překryvů vícepólu najde popisek prvku přes cizí žílu (syntetický případ)."""
    from envocad.model.multipole_geometry import MultipoleGeometry, multipole_text_overlaps
    g = MultipoleGeometry(texts=[((0, 0, 10, 3), "e1", "popisek F1"), ((20, 0, 30, 3), "e2", "popisek F2")],
                          lines=[((5, -5), (5, 10), "w1#L1", "žílu L1"), ((25, -5), (25, 10), "e2", "značku F2")])
    hits = multipole_text_overlaps(None, None, None, geometry=g, standard_paper="A4")
    assert hits == [("e1", "w1", "popisek F1 přes žílu L1")]


def test_spd_pole_ends_joined_to_pe(lib):
    from envocad.model import multipole as mp
    for kw, sheet_idx in (({}, None), ({}, 2)):
        p = build_project(spec(1, 2, **kw))
        s = _ac(p) if sheet_idx is None else p.sheets[sheet_idx]
        spd = next(e for e in s.elements if e.symbol_id == "fve.spd")
        ep = mp.element_poles(s, spd, element_symbol(p, spd, lib))
        segs = mp.pe_join_segments(ep)
        assert len(segs) == 1
        (x1, y1), (x2, y2) = segs[0]
        assert y1 == y2
        ends = [ep.pole_pos("PE", c) for c in [*ep.switched, "PE"]]   # konce pólů i začátek PE vodiče
        assert all(abs(y - y1) < 1e-9 and x1 - 1e-9 <= x <= x2 + 1e-9 for x, y in ends)
    # jistič (PE jde kolem, ne přes pól) příčku nemá
    br = next(e for e in _ac(p).elements if e.symbol_id == "fve.breaker_mcb")
    assert mp.pe_join_segments(mp.element_poles(_ac(p), br, element_symbol(p, br, lib))) == []


def test_pe_bar_inside_frame_below_outputs(lib):
    from envocad.model import multipole as mp
    from envocad.model.frame import MARGIN
    for kw in ({"macros": NO_MACROS}, {"ac": {"distribution": "terminals"}}):
        p = build_project(spec(1, 4, **kw))
        for s in p.sheets[1:]:
            bars = [e for e in s.elements if e.symbol_id == "sb.pe_bar"]
            if not bars:
                continue
            poles = {e.id: mp.element_poles(s, e, element_symbol(p, e, lib)) for e in s.elements}
            lay = mp.auto_layout(s, poles, x0=mp.MP_X0, y_top=s.height - mp.MP_Y_TOP, page_w=mp.page_width(s))
            outs = [lay[e.id][1] for e in s.elements if is_feed_out(e)]
            for b in bars:
                y = lay[b.id][1]
                assert y < min(outs) and y >= MARGIN + 5.0, (s.name, y)   # pod vývody, ne u okraje


# ---- 10. svazek u vstupů střídače, XOUT a DS ------------------------------------------------------------------
@pytest.mark.parametrize("per", [6, 12])
def test_inverter_input_bundle_fans_without_overlap(lib, per):
    from envocad.model.routing import route_sheet, wire_overlaps
    p = build_project(spec(1, per))
    s = p.sheets[0]
    t1 = next(e for e in s.elements if e.ref == "T1")
    port_x = t1.port_pos(element_symbol(p, t1, lib), "DC1")[0]
    ws = [w for w in s.wires if w.b.element_id == t1.id and w.b.port.startswith("DC")]
    xs = [w.points[0][0] for w in ws]
    assert len(set(xs)) == per and all(x < port_x - 2.0 for x in xs)   # každý lom jinde, před značkou střídače
    rdc = s.element(ws[0].a.element_id)
    box_right = symbol_box(rdc, element_symbol(p, rdc, lib))[2]
    assert min(xs) - box_right >= 40.0   # za popiskem kabelu
    routes = route_sheet(p, s, lib)
    assert not [(a, b) for a, b in wire_overlaps(s, routes) if a in {w.id for w in ws} or b in {w.id for w in ws}]


@pytest.mark.parametrize("dist", ["bus", "terminals"])
def test_grid_at_xout_height(lib, dist):
    """DS stojí na výšce portu, ze kterého k ní vede vodič (rovně) – od F2 na konci řetězce (HDS), ne u XOUT."""
    p = build_project(spec(2, 6, ac={"distribution": dist}))
    s = next(sh for sh in p.sheets if any(e.symbol_id == "fve.grid" for e in sh.elements))
    grid = next(e for e in s.elements if e.symbol_id == "fve.grid")
    w = next(w for w in s.wires if w.touches(grid.id))
    other, port = (w.a.element_id, w.a.port) if w.b.element_id == grid.id else (w.b.element_id, w.b.port)
    src = s.element(other)
    assert src.port_pos(element_symbol(p, src, lib), port)[1] == grid.port_pos(element_symbol(p, grid, lib), "1")[1]
    assert not w.points


# ---- 11. čitelné názvy prvků bez označení ---------------------------------------------------------------------
def test_element_name_and_reports_use_it(lib):
    from envocad.export.reports import cables
    from envocad.model.designation import element_name
    assert element_name(Element("fve.grid", 0, 0, attrs={"ref": ""})) == "DS"
    assert element_name(Element("fve.earth", 0, 0, attrs={"desc": "ekvipotenciální svorkovnice (HOP)"})) == "HOP"
    assert element_name(Element("fve.earth", 0, 0, attrs={})) == "uzemnění"
    assert element_name(Element("fve.grid", 0, 0, attrs={"ref": "Q9"})) == "Q9"
    assert element_name(Element("fve.spd", 0, 0, attrs={}), lib).startswith("Svodič")
    assert len(element_name(Element("fve.spd", 0, 0, attrs={}), lib)) <= 20
    assert element_name(Element("x.neznama", 0, 0, attrs={}), lib) == "neznama"
    p = build_project(spec(1, 2))
    _head, rows = cables(p, lib)
    text = json.dumps(rows, ensure_ascii=False)
    # F2: kabel RFVE.AC vede do stávajícího HR (+HR-X1), vodič HDS → DS je bez kabelu
    assert "+HR-X1" in text and "HOP:PE" in text and "fve." not in text
    from envocad.model.project import feed_link_index, wire_xref
    w_grid = next(w for w in p.sheets[0].wires if p.sheets[0].element(w.b.element_id).symbol_id == "fve.grid")
    blk_sheet = _ac(p)
    xout = next(e for e in blk_sheet.elements if e.ref == "XOUT")
    assert "HR:X1" in xout.attrs.get("to", "") and "fve.grid" not in wire_xref(p, w_grid.id, feed_link_index(p))


# ---- 12. šum kontroly -----------------------------------------------------------------------------------------
def test_info_aggregated_and_xpe_not_unlinked(lib):
    p = build_project(spec(1, 4, macros=NO_MACROS))
    fs = check_project(p, lib, standard_paper="A4")
    per_sheet = {}
    for f in fs:
        if f.code in ("no_article", "ref_syntax"):
            per_sheet.setdefault((f.code, f.sheet_id), []).append(f)
    assert per_sheet and all(len(v) == 1 for v in per_sheet.values())
    agg = [v[0] for v in per_sheet.values() if "prvk" in v[0].text]
    assert agg and all(f.severity == INFO and ":" in f.text for f in agg)
    # vývod XPE (jen PE, k HOP) bez vodiče v JPS se nehlásí; jiný nenavázaný vývod ano
    p = build_project(spec(1, 2))
    p.sheets[0].wires = [w for w in p.sheets[0].wires if w.conductors != ["PE"]]   # smaž XPE → HOP v JPS
    rh = _ac(p)
    fs = [f for f in check_project(p, lib, standard_paper="A4") if f.code == "feed_unlinked"]
    xpe = next(e for e in rh.elements if e.ref == "XPE")
    assert xpe.id not in {f.target_id for f in fs}
    p.sheets[0].wires = [w for w in p.sheets[0].wires if "XOUT" not in (w.a.port, w.b.port)]
    xout = next(e for e in rh.elements if e.ref == "XOUT")
    assert xout.id in {f.target_id for f in check_project(p, lib, standard_paper="A4") if f.code == "feed_unlinked"}


def test_aggregate_info_unit():
    from envocad.model.checks import Finding, aggregate_info
    fs = [Finding(INFO, "s1", "List", f"e{i}", False, f"F{i}", "Bez artiklu / typu", "no_article") for i in (10, 2, 1)]
    fs.append(Finding(INFO, "s2", "Jiný", "e9", False, "Q1", "Bez artiklu / typu", "no_article"))
    fs.append(Finding(WARNING, "s1", "List", "e5", False, "X", "něco", "free_port"))
    out = aggregate_info(fs)
    agg = [f for f in out if f.code == "no_article"]
    assert len(agg) == 2
    s1 = next(f for f in agg if f.sheet_id == "s1")
    assert "3 prvky" in s1.text and "(F1, F2, F10)" in s1.text
    assert next(f for f in agg if f.sheet_id == "s2").text == "Bez artiklu / typu"   # jediný se neslučuje
    assert any(f.code == "free_port" for f in out)


# ---- 13. výkon kontroly ---------------------------------------------------------------------------------------
def test_text_overlaps_index_matches_bruteforce(lib):
    """Prostorový index v `text_overlaps` dává stejný výsledek jako porovnání každý s každým."""
    from envocad.model import textlayout as tl
    p = build_project(spec(2, 6))
    s = p.sheets[0]
    lay = tl.compute_layout(p, s, lib)
    # posuň pár popisků do kolize, ať je co hlásit
    labs = list(lay.wires.values())
    for a, b in zip(labs[::2], labs[1::2]):
        b.boxes = list(a.boxes)
    fast = tl.text_overlaps(p, s, lib, lay)

    class Dense(tl._IndexGrid):
        def near(self, b, after=-1):
            return sorted({i for v in self.cells.values() for i in v if i > after})
    orig = tl._IndexGrid
    tl._IndexGrid = Dense
    try:
        slow = tl.text_overlaps(p, s, lib, lay)
    finally:
        tl._IndexGrid = orig
    assert fast == slow and fast


def test_check_project_speed_sanity(lib):
    """~800 prvků: kontrola dřív 3 s (75 % překryvy textů) – teď s prostorovým indexem pod 1 s (zde volná mez)."""
    sp = spec(4, 21)
    p = build_project(sp)
    assert sum(len(s.elements) for s in p.sheets) > 700
    check_project(p, lib, standard_paper="A4")
    t = time.perf_counter()
    check_project(p, lib, standard_paper="A4")
    # sdílené stroje CI (hlavně Windows) jsou 3–4× pomalejší než pracovní stanice (Linux CI ~12 s)
    assert time.perf_counter() - t < (25.0 if os.environ.get("CI") else 6.0)


# ---- 14. p_ac s jednotkou ---------------------------------------------------------------------------------------
def test_inverter_power_displayed_with_unit(lib):
    sym = lib.get_symbol("fve.inverter")
    assert sym.label_lines({"ref": "T1", "p_ac": "25"}) == ["25 kW"]
    assert sym.label_lines({"ref": "T1", "p_ac": "25 kW"}) == ["25 kW"]   # jednotka se nezdvojí
    assert lib.get_symbol("fve.battery").label_lines({"e_kwh": "10"}) == ["10 kWh"]


# ---- 15. makra v ENVOCAD_HOME -----------------------------------------------------------------------------------
def test_save_macro_writes_under_envocad_home(tmp_path, monkeypatch):
    from envocad.library.macros import find_macro, save_macro
    home = tmp_path / "home"
    monkeypatch.setenv("ENVOCAD_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path / "jinde"))
    p = Project()
    e = Element("fve.breaker_mcb", 0, 0, attrs={"ref": "F1"})
    p.sheets[0].elements.append(e)
    from envocad.model.project import copy_fragment
    path = save_macro("Moje", "", copy_fragment(p.sheets[0], [e.id]))
    assert path.parent == home / "macros" and path.exists()
    assert not (tmp_path / "jinde").exists()
    assert find_macro("Moje") is not None


# ---- 16. rozvod svorkami: skupiny na liště ----------------------------------------------------------------------
def test_terminal_distribution_groups_placed(lib):
    from envocad.model.checks import layout_problems
    p = build_project(spec(2, 2, ac={"distribution": "terminals"}))
    rh = _ac(p)
    groups = [e for e in rh.elements if e.symbol_id == "sb.terminal_block"]
    # 2 přívody, SPD, vývod a nad 30 kWp (2 × 2 × 9 kWp) síťová ochrana – vlastní skupina svorek
    assert len(groups) == 5 and all(e.modules > 0 for e in groups)
    assert any(e.attrs.get("desc") == "síťová ochrana" for e in groups)
    assert all(rh.layout.placement(e.id) is not None for e in groups)
    assert not layout_problems(rh, p)


def test_generated_feed_texts_match_final_positions():
    """Texty vazeb přívodů („W3 T1:DC1 /1.F3“) se ukládají až po rozmístění JPS na list – nové propočítání vazeb
    (po smazání a vrácení listu) je nezmění."""
    from envocad.model.project import feed_link_attrs, sync_feed_links
    p = build_project(spec(2, 4))
    before = p.to_dict()
    for s in p.sheets[1:]:
        for f in s.elements:
            if f.attrs.get("wire_id"):
                for k, v in feed_link_attrs(p, s, f, f.attrs["wire_id"]).items():
                    assert f.attrs.get(k, "") == v, (s.name, f.ref, k)
    sync_feed_links(p)
    assert p.to_dict() == before
