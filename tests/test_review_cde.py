"""Regrese nálezů review C–E: přednost zdrojů knihovny při mezipaměti podle mtime, ruční řádky změnového listu,
přejmenování jen souvisejících textů, osiřelé kabely ze souboru, čísla v xlsx, obnova motivu po chybě PDF,
svorkovnice podle prostoru označení, PE přes čísla svorek ve vícepólu, sběrnice pro 12 střídačů."""
import json
import os
import shutil

import pytest

from envocad.export import reports
from envocad.generate import build_project
from envocad.library import store as st
from envocad.library.store import LibraryStore
from envocad.model.feed import is_feed_in
from envocad.model.project import Element, Project, Sheet

pytestmark = pytest.mark.usefixtures("ac_builtin")   # AC listy vestavěným kódem (standard `ac_builtin`)

INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "l.db")


# ---- 1. přednost builtin → user → shared i po změně vestavěného souboru ---------------------------------------
@pytest.fixture
def small_builtin(tmp_path, monkeypatch):
    """Malá vestavěná knihovna (jedno CSV, jedna značka) a firemní přepis téhož artiklu a téže značky."""
    src = st.BUILTIN_DIR
    b = tmp_path / "builtin"
    (b / "components").mkdir(parents=True)
    (b / "switchboard").mkdir()
    lines = (src / "components" / "becov_terminals.csv").read_text(encoding="utf-8").splitlines()
    (b / "components" / "becov_terminals.csv").write_text("\n".join(lines[:3]) + "\n", encoding="utf-8")
    shutil.copy(src / "switchboard" / "sb.busbar.json", b / "switchboard" / "sb.busbar.json")
    monkeypatch.setattr(st, "BUILTIN_DIR", b)
    user = st.user_library_dir() / "firma"
    user.mkdir(parents=True)
    head, row = lines[0], lines[1]
    cols = row.split(";")
    cid = cols[0]
    cols[3] = "FIREMNÍ NÁZEV"
    (user / "prepis.csv").write_text(head + "\n" + ";".join(cols) + "\n", encoding="utf-8")
    sym = json.loads((b / "switchboard" / "sb.busbar.json").read_text(encoding="utf-8"))
    sym["name"] = "Firemní sběrnice"
    (user / "sb.busbar.json").write_text(json.dumps(sym, ensure_ascii=False), encoding="utf-8")
    return b, cid


def _touch(path, dt=10.0):
    s = path.stat()
    os.utime(path, (s.st_atime + dt, s.st_mtime + dt))


def test_user_override_wins_after_builtin_csv_touched(small_builtin):
    b, cid = small_builtin
    lib1 = LibraryStore()
    assert lib1.get_component(cid)["name"] == "FIREMNÍ NÁZEV"
    lib1.conn.close()
    _touch(b / "components" / "becov_terminals.csv")      # jen vestavěné CSV změněno (aktualizace programu)
    lib2 = LibraryStore()
    assert lib2.get_component(cid)["name"] == "FIREMNÍ NÁZEV"
    lib2.conn.close()


def test_user_symbol_wins_after_builtin_json_touched(small_builtin):
    b, _cid = small_builtin
    lib1 = LibraryStore()
    assert lib1.get_symbol("sb.busbar").name == "Firemní sběrnice"
    lib1.conn.close()
    _touch(b / "switchboard" / "sb.busbar.json")
    lib2 = LibraryStore()
    assert lib2.get_symbol("sb.busbar").name == "Firemní sběrnice"
    lib2.conn.close()


# ---- 2. změnový list: ruční řádky otevřené revize zůstanou -----------------------------------------------------
MANUAL = "B | 1.1.2026 | doplněn popis kabelové trasy (ručně) | JR"


def test_merge_change_lines_keeps_manual_rows():
    from envocad.model.revision import merge_change_lines
    cur = f"A | 1.1. | první vydání | PR\nB | 2.1. | stará změna | PR\n{MANUAL}"
    new = "B | 3.1. | nová | PR"
    out = merge_change_lines(cur, {"B"}, new, ["B | 2.1. | stará změna | PR"])
    assert out.splitlines() == ["A | 1.1. | první vydání | PR", MANUAL, new]
    # revize ze staršího souboru (vygenerované řádky neznámé): ruční řádek se nesmaže
    assert MANUAL in merge_change_lines(cur, {"B"}, new).splitlines()


def test_revision_auto_lines_roundtrip_optional_key():
    from envocad.model.project import Revision
    r = Revision("B")
    assert "auto_lines" not in r.to_dict()            # starší soubory se uloží beze změny
    r.auto_lines = ["B | 1.1. | x | PR"]
    d = r.to_dict()
    assert d["auto_lines"] == ["B | 1.1. | x | PR"]
    assert Revision.from_dict(d).auto_lines == ["B | 1.1. | x | PR"]
    assert Revision.from_dict({"label": "B"}).auto_lines is None


def test_record_revision_keeps_manual_row(lib):
    from envocad.model.diff import change_list_text, diff_projects
    from envocad.ui.main_window import MainWindow
    proj = build_project({"inverters": [{"ref": "T1", **INV, "strings": [20, 20]}]})
    old = Project.from_dict(proj.to_dict())
    proj.sheets[0].elements[0].attrs["type"] = "jiný typ"
    ch = diff_projects(old, proj, lib)
    w = MainWindow(library=lib, project=proj)
    try:
        assert w.record_revision(ch, "B", "1.1.2026", "PR", change_list_text(ch, "B", "1.1.2026", "PR"))
        proj.meta["changes"] += "\n" + MANUAL           # uživatel dopsal řádek do otevřené revize
        assert w.record_revision(ch, "B", "2.1.2026", "PR", change_list_text(ch, "B", "2.1.2026", "PR"))
        lines = proj.meta["changes"].splitlines()
        assert MANUAL in lines
        assert not any("1.1.2026" in ln for ln in lines if ln != MANUAL)   # vygenerované řádky nahrazené
        saved = Project.from_dict(json.loads(json.dumps(proj.to_dict())))
        assert saved.revisions[-1].auto_lines == proj.revisions[-1].auto_lines
    finally:
        w.undo.setClean()
        w.close()


# ---- 3. přejmenování: jen texty souvisejících prvků ------------------------------------------------------------
def test_rename_followups_skips_other_designation_space():
    from envocad.model.project import rename_followups
    p = build_project({"inverters": [{"ref": "T1", **INV, "strings": [20, 20]}]})
    t1 = next(e for e in p.sheets[0].elements if e.ref == "T1")
    s2 = Sheet(name="Druhá FVE", func="B")
    p.sheets.append(s2)
    fed = Element("fve.load", 150, 100, attrs={"ref": "", "desc": "od T1"})
    s2.elements += [Element("fve.inverter", 100, 100, attrs={"ref": "T1"}), fed]
    ch = rename_followups(p, t1, "T1", "T5")
    assert fed.id not in {c.target_id for c in ch}
    rh = next(e for e in p.sheets[0].elements if e.ref == "RFVE.AC")
    rh_sheet = p.switchboard_sheet(rh.id)
    feed = next(e for e in rh_sheet.elements if is_feed_in(e) and e.attrs.get("desc") == "od T1")
    assert feed.id in {c.target_id for c in ch}          # přívod navázaný na vodič od T1 se přepíše
    # ruční text podle šablony ve stejném prostoru (prokázaná vazba) se také přepíše
    same = Element("fve.load", 200, 100, attrs={"ref": "", "desc": "od T1"})
    p.sheets[0].elements.append(same)
    assert same.id in {c.target_id for c in rename_followups(p, t1, "T1", "T5")}


# ---- 4. kabely osiřelé už v souboru se při otevření nemažou ---------------------------------------------------
def test_sync_cables_keeps_orphans_from_file(lib):
    from envocad.model.checks import INFO, check_project
    from envocad.model.project import sync_cables, sync_feed_links
    p = build_project({"inverters": [{"ref": "T1", **INV, "strings": [20, 20]}]})
    s = p.sheets[0]
    w = next(w for w in s.wires if w.attrs.get("ref") and w.attrs.get("cable_id"))
    cid = w.attrs["cable_id"]
    s.wires.remove(w)
    p.cable(cid).cores[0].color = "fialová"          # ruční data kabelu
    q = Project.from_dict(json.loads(json.dumps(p.to_dict())))
    sync_feed_links(q)
    sync_cables(q)
    assert q.cable(cid) is not None and q.cable(cid).cores[0].color == "fialová"
    fs = [f for f in check_project(q, lib, standard_paper="A4") if f.code == "cable_no_wire"]
    assert len(fs) == 1 and fs[0].severity == INFO and "nemá vodič" in fs[0].text
    # kabel osiřelý změnou v této relaci se dál odebírá (undo vrátí týž kabel)
    w2 = next(w for w in q.sheets[0].wires if w.attrs.get("cable_id"))
    cid2 = w2.attrs["cable_id"]
    q.sheets[0].wires.remove(w2)
    sync_cables(q)
    assert q.cable(cid2) is None and cid2 in q.removed_cables


# ---- 5. xlsx: Svorka / Č. číslem jen čisté celé číslo ---------------------------------------------------------
def test_xlsx_terminal_numbers_only_plain_integers():
    from openpyxl import Workbook

    from envocad.export.xlsx_export import _integer, _write_table
    assert _integer("12") == 12 and _integer("1.10") == "1.10" and _integer("01") == "01"
    assert _integer("1,5") == "1,5" and _integer("PE") == "PE"
    ws = Workbook().active
    _write_table(ws, "T", "", ["Svorka", "Č.", "Průřez [mm²]"], [["1.10", "3", "1,5"], ["7", "01", "6"]])
    vals = [[c.value for c in r] for r in ws.iter_rows(min_row=ws.max_row - 1)]
    assert vals == [["1.10", 3, 1.5], [7, "01", 6]]


# ---- 6. PDF: motiv a scéna se vrátí i po chybě ----------------------------------------------------------------
class _FailingScene:
    def __init__(self, fail_in):
        self.fail_in = fail_in
        self.printing = False
        self.project = type("P", (), {"name": "P"})()
        self.sheet = type("S", (), {"name": "S", "width": 420.0, "height": 297.0})()
        self.draw_grid = True

    def clearSelection(self):
        pass

    def rebuild(self):
        if self.fail_in == "rebuild" and self.printing:
            raise RuntimeError("rebuild")

    def sceneRect(self):
        from PySide6.QtCore import QRectF
        return QRectF(0, 0, 10, 10)

    def render(self, *a):
        raise RuntimeError("render")

    def update(self):
        pass


@pytest.mark.parametrize("fail_in", ["rebuild", "render"])
def test_export_layout_pdf_restores_theme_on_error(tmp_path, fail_in):
    from envocad.export.pdf_export import export_layout_pdf
    from envocad.ui import theme
    before = theme._current
    sc = _FailingScene(fail_in)
    with pytest.raises(RuntimeError):
        export_layout_pdf(sc, tmp_path / "x.pdf")
    assert theme._current is before and sc.printing is False


def test_export_scene_pdf_restores_theme_on_error(tmp_path):
    from envocad.export.pdf_export import export_scene_pdf
    from envocad.ui import theme
    before = theme._current
    sc = _FailingScene("render")
    with pytest.raises(RuntimeError):
        export_scene_pdf(sc, tmp_path / "x.pdf")
    assert theme._current is before and sc.draw_grid is True


# ---- 7. seznam přístrojů: svorkovnice podle prostoru označení jako štítky --------------------------------------
def test_device_list_groups_strips_by_scope(lib):
    p = build_project({"inverters": [{"ref": f"T{i + 1}", **INV, "strings": [18]} for i in range(2)],
                       "ac": {"distribution": "terminals"}})
    rh = next(s for s in p.sheets if s.is_switchboard and s.loc == "RFVE.AC")
    grp = next(e for e in rh.elements if e.symbol_id == "sb.terminal_block")
    grp.attrs["loc"] = "RX"                              # skupina svorek X3 jiného umístění = jiná svorkovnice
    _h, rows = reports.device_list(p, lib, rh)
    _h, labs = reports.labels(p, lib, rh)
    strips = sorted(r[0] for r in rows if r[0].endswith("-X3"))
    assert strips == sorted(r[0] for r in labs if r[0].endswith("-X3")) == ["+RFVE.AC-X3", "+RX-X3"]


# ---- 8. vícepól: PE k přerušení nevede přes čísla svorek -------------------------------------------------------
def test_multipole_pe_break_avoids_terminal_numbers(lib, monkeypatch):
    from envocad.model import multipole as mp
    from envocad.model.multipole_geometry import multipole_text_overlaps
    p = build_project({"inverters": [{"ref": "T1", **INV, "strings": [20] * 6}], "dc": {"route_boxes": 1}})
    s = next(x for x in p.sheets if x.is_switchboard and x.loc == "RDC1")
    assert not [o for o in multipole_text_overlaps(p, s, lib, standard_paper="A4") if "číslo svorky" in o[2]]
    # kontrola čísla svorek hlídá: dřívější vedení v úrovni portu (přes řadu svorek) se ohlásí – PE z více stran
    # do XPE vede sběrná čára (za portem XPE), ostatní přerušení `break_y`
    from envocad.model import multipole_geometry as mg
    monkeypatch.setattr(mp, "break_y", lambda pt, d, n, used: pt[1] - 2.5 * n)
    monkeypatch.setattr(mg, "RAIL_OFFSET", -5.0)     # čára pod portem = přes řadu čísel svorek
    hits = [o for o in multipole_text_overlaps(p, s, lib, standard_paper="A4") if "číslo svorky" in o[2]]
    assert hits


def test_break_y_outward_and_spaced():
    from envocad.model.multipole import GRID, break_y
    used: set[float] = set()
    assert break_y((0.0, 100.0), "N", 0, used) == 100.0 + GRID
    assert break_y((0.0, 100.0), "N", 1, used) == 100.0 + GRID + 5.0      # souběžné úseky po 2 roztečích (popisek)
    assert break_y((0.0, 100.0), "S", 2, set()) == 100.0 - GRID
    assert break_y((0.0, 100.0), "E", 2, set()) == 100.0               # v úrovni portu, je-li volná
    assert break_y((0.0, 100.0), "E", 3, {100.0}) == 97.5
    # port S u spodního okraje: dvojí rozteč by sjela pod `lo` → po jedné rozteči
    low = {100.0 - GRID}
    assert break_y((0.0, 100.0), "S", 1, low, lo=95.0) == 100.0 - GRID - 2.5


# ---- 9. sběrnice: 12 střídačů, nad limit česká hláška ----------------------------------------------------------
def test_busbar_takes_twelve_inverters(lib):
    from envocad.model.checks import check_project
    sym = lib.get_symbol("sb.busbar")
    assert {f"T{i}" for i in range(1, 13)} <= {pt.name for pt in sym.ports}
    assert all(pt.x % 2.5 == 0 and pt.y % 2.5 == 0 for pt in sym.ports)
    p = build_project({"inverters": [{"ref": f"T{i + 1}", "p_ac": 10, "strings": [18]} for i in range(12)]})
    assert not [f for f in check_project(p, lib, standard_paper="A4") if f.code == "bad_port"]
    with pytest.raises(ValueError, match="nejvýš 12 střídačů"):
        build_project({"inverters": [{"ref": f"T{i + 1}", "p_ac": 10, "strings": [18]} for i in range(13)]})
