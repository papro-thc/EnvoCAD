"""Nálezy review jednotné značky `sb.feed` (bez Qt): otisky uzavřených revizí po migraci v12 → v13, vlastní AC makra
ve starém rozložení, AC rozvaděč se 7–12 střídači bez křížení, vícepól starých projektů, úklid knihovny, šablony
pluginů, verze ukládaného makra a prodloužený formát listu rozvaděče.

Data: `data/v12_closed_revision.ecp` uložil EnvoCAD formátu 12 (generátor, 1 střídač, uzavřená revize A – otisky
listů spočtené nad `sb.feed_in` / `sb.feed_out`); `data/macros_v2/` = firemní makra AC přívodu a jádra ve starém
rozložení (verze 2, přívod shora do portu T{k} sběrnice).
"""
from __future__ import annotations

import json
import os
import shutil
from itertools import pairwise
from pathlib import Path

import pytest

from envocad.library import macros
from envocad.library.store import LEGACY_BUILTIN_FILES, LibraryStore
from envocad.model.checks import ERROR, WARNING, check_project
from envocad.model.diff import _canon_element, diff_projects, sheet_fingerprint
from envocad.model.feed import FEED_SYMBOL, LEGACY_FEEDS, MP_LEGACY_ATTR, is_feed, is_feed_in, is_mp_legacy
from envocad.model.project import Element, Project, Sheet, element_symbol, migrate
from envocad.model.revision import changed_after_close

pytestmark = pytest.mark.usefixtures("ac_builtin")   # AC listy vestavěným kódem (standard `ac_builtin`)

DATA = Path(__file__).parent / "data"
INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
HOUSE_INV = {"p_ac": 10, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "lib.db")


def _crossings(project, sheet, lib) -> list[tuple[str, str]]:
    """Dvojice vodičů, jejichž trasy se kříží (vodorovný úsek přes svislý uvnitř obou úseků)."""
    from envocad.model.routing import route_sheet
    segs = {wid: list(pairwise(pts)) for wid, pts in route_sheet(project, sheet, lib).items()}
    out = []
    ids = sorted(segs)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            for p, q in segs[a]:
                for r, t in segs[b]:
                    if p[1] == q[1] and r[0] == t[0]:
                        h, v = (p, q), (r, t)
                    elif r[1] == t[1] and p[0] == q[0]:
                        h, v = (r, t), (p, q)
                    else:
                        continue
                    x0, x1 = sorted((h[0][0], h[1][0]))
                    y0, y1 = sorted((v[0][1], v[1][1]))
                    if x0 + 0.1 < v[0][0] < x1 - 0.1 and y0 + 0.1 < h[0][1] < y1 - 0.1:
                        out.append((a, b))
    return out



def _cross_nodes(project, sheet, lib) -> list[tuple[float, float]]:
    """Body, do kterých vodiče listu vedou ze všech čtyř stran (zleva, zprava, shora, zdola) – vypadají jako křížení
    bez uzlu, i když se vodiče v bodě opravdu spojují (odbočky zleva i zprava v témže bodě svislého vodiče).
    `_crossings` je nevidí (konce úseků leží přesně na druhém vodiči). Uzel `sb.junction` má tečku a porty mimo střed,
    takže sem nepatří."""
    from envocad.model.routing import route_sheet
    segs = [(p, q) for pts in route_sheet(project, sheet, lib).values() for p, q in pairwise(pts) if p != q]
    pts = {pt for seg in segs for pt in seg}
    out = []
    for c in sorted(pts):
        dirs = set()
        for p, q in segs:
            for a, b in ((p, q), (q, p)):
                if a[0] == b[0] == c[0] and min(a[1], b[1]) - 1e-6 <= c[1] <= max(a[1], b[1]) + 1e-6:
                    if b[1] > c[1] + 1e-6:
                        dirs.add("N")
                    if b[1] < c[1] - 1e-6:
                        dirs.add("S")
                elif a[1] == b[1] == c[1] and min(a[0], b[0]) - 1e-6 <= c[0] <= max(a[0], b[0]) + 1e-6:
                    if b[0] > c[0] + 1e-6:
                        dirs.add("E")
                    if b[0] < c[0] - 1e-6:
                        dirs.add("W")
        if len(dirs) == 4:
            out.append(c)
    return out

# ---- 1. uzavřená revize v12 zůstane po migraci uzavřená ----------------------------------------------------------
def _v12_raw() -> dict:
    return json.loads((DATA / "v12_closed_revision.ecp").read_text(encoding="utf-8"))


def test_v12_closed_revision_stays_closed_after_migration(lib):
    raw = _v12_raw()
    assert raw["format_version"] == 12 and raw["revisions"][0]["closed"]
    assert any(e["symbol_id"] in LEGACY_FEEDS for s in raw["sheets"] for e in s["elements"])
    p = Project.from_dict(raw)
    assert changed_after_close(p) == []
    assert not [f for f in check_project(p, lib, standard_paper="A4") if f.code == "rev_closed_changed"]
    # otisky uložené starou verzí = otisky převedených listů
    rev = p.revisions[0]
    assert all(rev.fingerprints[s.id] == sheet_fingerprint(s) for s in p.sheets if s.id in rev.fingerprints)


def test_canonical_feed_matches_legacy_element_and_rotation():
    """Kanonická forma převedeného přívodu/vývodu = forma starého prvku (id značky, atributy bez `dir`); rotace
    (přívod +180°) vrácená zpět je stará rotace, poloha portu se nemění."""
    raw = _v12_raw()
    p = Project.from_dict(raw)
    by_id = {e["id"]: e for s in raw["sheets"] for e in s["elements"]}
    n = 0
    for s in p.sheets:
        for e in s.elements:
            if not is_feed(e):
                continue
            old = by_id[e.id]
            legacy = Element.from_dict(old)            # prvek tak, jak ho viděla verze 12 (bez migrace)
            assert legacy.symbol_id in LEGACY_FEEDS
            assert _canon_element(e) == _canon_element(legacy)
            turn = LEGACY_FEEDS[old["symbol_id"]][1]
            assert (e.rotation - turn) % 360 == int(old.get("rotation") or 0) % 360
            n += 1
    assert n >= 5


def test_fingerprint_still_sees_real_feed_changes():
    p = Project.from_dict(_v12_raw())
    s, e = next((s, e) for s in p.sheets for e in s.elements if is_feed_in(e))
    fp = sheet_fingerprint(s)
    e.attrs["dir"] = ""                       # prázdný směr = přívod: beze změny
    assert sheet_fingerprint(s) == fp
    e.attrs["dir"] = "out"                    # přívod → vývod: změna listu
    assert sheet_fingerprint(s) != fp
    e.attrs["dir"] = "in"
    e.attrs[MP_LEGACY_ATTR] = ""              # technická značka migrace se do otisku ani porovnání nepočítá
    assert sheet_fingerprint(s) == fp
    assert diff_projects(Project.from_dict(_v12_raw()), p) == []


# ---- 2. vlastní makra AC přívodu a jádra ve starém rozložení (v2, port T{k}) -------------------------------------
@pytest.fixture
def legacy_macros(tmp_path, monkeypatch):
    d = tmp_path / "macros"
    d.mkdir()
    for f in (DATA / "macros_v2").glob("*.json"):
        shutil.copy(f, d / f.name)
    monkeypatch.setattr(macros, "user_dir", lambda: d)
    monkeypatch.setattr(macros, "shared_dir", lambda: None)
    return {"ac_feed": "AC přívod střídače firemní", "ac_core": "AC jádro rozvaděče firemní"}


def test_feed_macro_layout_detection(legacy_macros):
    from envocad.generate import _feed_macro_from_below
    old = macros.find_macro(legacy_macros["ac_feed"])
    assert old.version == 2 and not _feed_macro_from_below(old)
    assert _feed_macro_from_below(macros.find_macro("AC přívod střídače"))      # vestavěné v3: B{k}
    v3_top = macros.parse_macro({**json.loads((DATA / "macros_v2" / "ac_privod_stridace_v2.json").read_text("utf-8")),
                                 "version": 3})
    assert not _feed_macro_from_below(v3_top)                                  # v3, ale vodič do T{k}


@pytest.mark.parametrize("n", [1, 3])
def test_legacy_ac_macros_generate_clean(lib, legacy_macros, n):
    from chain_data import build_project  # F2: In stávajících článků zadané
    p = build_project({"inverters": [{"ref": f"T{i + 1}", **INV, "strings": [20]} for i in range(n)],
                       "macros": legacy_macros})
    ac = next(s for s in p.sheets if s.loc == "RFVE.AC")
    feeds = [e for e in ac.elements if is_feed_in(e)]
    q = next(e for e in ac.elements if e.symbol_id == "sb.main_switch")
    assert len(feeds) == n and q.x > max(e.x for e in feeds)      # jádro za přívody jako dřív
    bad = [(f.code, f.sheet_name, f.text) for f in check_project(p, lib, standard_paper="A4") if f.severity in (ERROR, WARNING)]
    assert bad == []


# ---- 3. AC rozvaděč se 7–12 střídači bez křížení vodičů ----------------------------------------------------------
@pytest.mark.parametrize("use_macros", [True, False], ids=["makra", "kod"])
@pytest.mark.parametrize("n", [7, 9, 12])
def test_many_inverters_no_crossings(lib, n, use_macros):
    from chain_data import build_project  # F2: In stávajících článků zadané
    spec = {"inverters": [{"ref": f"T{i + 1}", **INV, "strings": [20]} for i in range(n)]}
    if not use_macros:
        spec["macros"] = {"ac_feed": "", "ac_core": ""}
    p = build_project(spec)
    s = next(s for s in p.sheets if s.loc == "RFVE.AC")
    assert _crossings(p, s, lib) == []
    bus = next(e for e in s.elements if e.symbol_id == "sb.busbar")
    ports = [w.a.port if w.a.element_id == bus.id else w.b.port for w in s.wires if w.touches(bus.id)]
    assert len({x for x in ports if x.startswith("B")}) == n
    bad = [(f.code, f.text) for f in check_project(p, lib, standard_paper="A4")
           if f.severity in (ERROR, WARNING) and f.sheet_id == s.id]
    assert bad == []


def test_busbar_has_output_behind_last_bottom_feed(lib):
    sym = lib.get_symbol("sb.busbar")
    b12, o13 = sym.port("B12"), sym.port("13")
    assert o13.x > b12.x and o13.dir == "S"
    xs = [x for pr in sym.primitives for x, _y in pr["points"]]
    assert max(xs) > o13.x


# ---- 4. vícepól starých projektů beze změny ----------------------------------------------------------------------
def _v12_manual_bottom_feed() -> dict:
    return {"format": "envocad-project", "format_version": 12, "sheets": [
        {"id": "s1", "name": "R1", "kind": "switchboard", "elements": [
            {"id": "f", "symbol_id": "sb.feed_in", "x": 60, "y": 100, "rotation": 180, "attrs": {"ref": "X1"}},
            {"id": "q", "symbol_id": "fve.breaker_mcb", "x": 60, "y": 140, "rotation": 90,
             "attrs": {"ref": "F1", "poles": "3"}},
            {"id": "o", "symbol_id": "sb.feed_out", "x": 90, "y": 100, "rotation": 0, "attrs": {"ref": "X2"}}],
         "wires": [
             {"id": "w1", "a": {"element_id": "f", "port": "1"}, "b": {"element_id": "q", "port": "1"},
              "conductors": ["L1", "L2", "L3", "N", "PE"]},
             {"id": "w2", "a": {"element_id": "q", "port": "2"}, "b": {"element_id": "o", "port": "1"},
              "conductors": ["L1", "L2", "L3", "N", "PE"]}]}]}


def test_legacy_multipole_not_flipped(lib):
    from envocad.model import multipole as mp
    p = Project.from_dict(_v12_manual_bottom_feed())
    s = p.sheets[0]
    assert all(is_mp_legacy(e) for e in s.elements if is_feed(e))
    poles = mp.sheet_poles(s, lambda e: element_symbol(p, e, lib))
    # jako verze 12: přívod v souřadnicích starého sb.feed_in s rotací 180, jistič 90
    assert poles["f"].element.rotation == 180 and poles["q"].element.rotation == 90
    assert mp.flow_flipped(s, poles) == set()
    # tentýž list nakreslený novou značkou (bez značky migrace) se otáčí – vícepól shora dolů
    for e in s.elements:
        e.attrs.pop(MP_LEGACY_ATTR, None)
    poles = mp.sheet_poles(s, lambda e: element_symbol(p, e, lib))
    assert poles["f"].element.rotation == 0 and poles["q"].element.rotation == 270


def test_migration_marks_only_project_elements():
    raw = _v12_manual_bottom_feed()
    mig = migrate(raw, 12)
    assert all(e["attrs"].get(MP_LEGACY_ATTR) == "1" for e in mig["sheets"][0]["elements"] if "feed" in e["symbol_id"])
    frag = {"elements": [dict(raw["sheets"][0]["elements"][0], attrs={"ref": "X1"})], "wires": []}
    from envocad.model.feed import normalize_legacy_fragment
    normalize_legacy_fragment(frag)                       # schránka / makro: bez značky (nový obsah)
    assert MP_LEGACY_ATTR not in frag["elements"][0]["attrs"]


# ---- 5. knihovna: záznamy souborů starých vestavěných značek -----------------------------------------------------
def test_sync_builtin_removes_legacy_builtin_files(tmp_path):
    db = tmp_path / "lib.db"
    store = LibraryStore(db)
    keys = sorted(LEGACY_BUILTIN_FILES) + ["builtin:switchboard/jiny.json"]
    store.conn.executemany("INSERT OR REPLACE INTO builtin_files(path, mtime) VALUES(?, ?)", [(k, 1.0) for k in keys])
    store.conn.commit()
    store.close()
    store = LibraryStore(db)
    left = {r[0] for r in store.conn.execute("SELECT path FROM builtin_files")}
    assert not left & LEGACY_BUILTIN_FILES
    # skutečné klíče knihovny mají oddělovač systému (`_rel`), na Windows „\\“
    assert "builtin:switchboard/jiny.json" in left and f"builtin:switchboard{os.sep}sb.feed.json" in left
    store.close()


# ---- 9. literál, šablony pluginů ---------------------------------------------------------------------------------
def test_no_feed_literal_outside_feed_module():
    root = Path(__file__).parent.parent / "envocad"
    hits = [str(f.relative_to(root)) for f in root.rglob("*.py")
            if f.name != "feed.py" and ('"sb.feed"' in f.read_text("utf-8") or "'sb.feed'" in f.read_text("utf-8"))]
    assert hits == []


def test_plugin_template_with_legacy_feeds_is_normalized(monkeypatch):
    from envocad.library import templates as T

    def build(project, sheet, _params):
        sheet.elements += [Element("sb.feed_in", 0, 100, attrs={"ref": "X1"}),
                           Element("sb.feed_out", 0, 50, rotation=90, attrs={"ref": "X2"})]

    monkeypatch.setattr(T, "TEMPLATES", [*T.TEMPLATES, T.Template("stara", "Stará", "", [], build)])
    p = Project()
    sh = Sheet(name="R", kind="switchboard")
    p.sheets.append(sh)
    T.apply_template(p, sh, "stara", standard_paper="A4")
    x1, x2 = sh.elements
    assert (x1.symbol_id, x1.attrs["dir"], x1.rotation) == (FEED_SYMBOL, "in", 180)
    assert (x2.symbol_id, x2.attrs["dir"], x2.rotation) == (FEED_SYMBOL, "out", 90)


# ---- 11. verze ukládaného makra ----------------------------------------------------------------------------------
def test_saved_macro_version_by_content(tmp_path, monkeypatch):
    monkeypatch.setattr(macros, "user_dir", lambda: tmp_path / "m")
    monkeypatch.setattr(macros, "shared_dir", lambda: None)
    feed = {"id": "a", "symbol_id": FEED_SYMBOL, "x": 0, "y": 0, "attrs": {"ref": "X1", "dir": "in"}}
    brk = {"id": "b", "symbol_id": "fve.breaker_mcb", "x": 0, "y": 30, "attrs": {"ref": "F1"}}
    with_feed = macros.save_macro("S přívodem", "", {"elements": [feed, brk], "wires": []})
    without = macros.save_macro("Bez přívodu", "", {"elements": [brk], "wires": []})
    assert json.loads(with_feed.read_text("utf-8"))["version"] == 3
    assert json.loads(without.read_text("utf-8"))["version"] == 2


# ---- 12. široký list rozvaděče: prodloužený formát na šířku ------------------------------------------------------
def test_wide_house_switchboard_gets_long_landscape_paper(lib):
    from chain_data import build_project  # F2: In stávajících článků zadané

    from envocad.model.frame import LONG_PAPERS
    p = build_project({"building": "house",
                       "inverters": [{"ref": f"T{i + 1}", **HOUSE_INV, "strings": [12, 12, 12]} for i in range(3)]})
    s = next(s for s in p.switchboards() if s.loc == "RFVE")
    assert s.height == 297.0 and (s.paper, s.width) in LONG_PAPERS[297.0]
    assert _crossings(p, s, lib) == []
    assert not [f for f in check_project(p, lib, standard_paper="A4")
                if f.severity in (ERROR, WARNING) and f.sheet_id == s.id and f.code in ("outside_frame", "text_overlap")]


def test_grow_sheet_long_unit(lib):
    from envocad.model.frame import grow_sheet_long
    p = Project()
    sh = Sheet(name="R", kind="switchboard")
    p.sheets.append(sh)
    sh.elements.append(Element("fve.breaker_mcb", 60, 150, rotation=90, attrs={"ref": "F1"}))
    assert not grow_sheet_long(p, sh, lib, standard_paper="A4") and sh.paper == "A3"      # vejde se – beze změny
    sh.elements.append(Element("fve.breaker_mcb", 500, 150, rotation=90, attrs={"ref": "F2"}))
    assert grow_sheet_long(p, sh, lib, standard_paper="A4")
    assert (sh.paper, sh.width, sh.height) == ("A4×3", 630.0, 297.0)
    sh.elements.append(Element("fve.breaker_mcb", 300, 280, rotation=90, attrs={"ref": "F3"}))   # přetéká nahoru
    assert not grow_sheet_long(p, sh, lib, standard_paper="A4")

