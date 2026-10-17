"""Robustnost GUI (offscreen): mazání listu rozvaděče, otevření vadného projektu, autosave a obnova, uložení,
import DXF, start s vadným souborem, pluginy."""
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from envocad.library.store import LibraryStore, home_dir
from envocad.model.project import Element, Project, Wire, WireEnd
from envocad.ui.main_window import MainWindow

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "ukazka_fve.ecp"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def lib(tmp_path):
    return LibraryStore(tmp_path / "lib.db")


@pytest.fixture
def dialogs(monkeypatch):
    """Zaznamená modální hlášky; otázky odpoví podle `answers` (výchozí Yes)."""
    seen: list[tuple[str, str]] = []
    answers: list = []

    def question(*a, **k):
        seen.append(("question", a[2]))
        return answers.pop(0) if answers else QMessageBox.Yes
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    for kind in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind,
                            staticmethod(lambda *a, _k=kind, **kw: seen.append((_k, a[2])) or QMessageBox.Ok))
    return type("D", (), {"seen": seen, "answers": answers})


def _project(name="A") -> Project:
    p = Project(name=name)
    s = p.sheets[0]
    g = Element("fve.pv_string", 30, 150, attrs={"ref": "G1"})
    t = Element("fve.inverter", 120, 150, attrs={"ref": "T1"})
    s.elements += [g, t]
    s.wires.append(Wire(WireEnd(g.id, "DC"), WireEnd(t.id, "DC1"), attrs={"ref": "W1"}))
    return p


def _win(lib, p=None) -> MainWindow:
    w = MainWindow(library=lib, project=p or _project())
    w.show()
    QApplication.processEvents()
    return w


def _spec_project():
    from envocad.generate import build_project
    return build_project({"name": "T", "module": {"p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9},
                          "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200,
                                         "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [20, 20]}],
                          "ac": {"breaker_in": 50, "main_in": 125}})


# ---- 1: smazání listu rozvaděče ---------------------------------------------------------------------------------
def test_delete_switchboard_sheet_keeps_block_and_project_openable(app, lib, dialogs, tmp_path):
    from envocad.model.checks import check_project
    from envocad.ui.multipole_view import MultipoleView
    p = _spec_project()
    w = _win(lib, p)
    sb = p.switchboards()[-1]
    block_id = sb.parent_element_id
    jps = p.sheet_of_element(block_id)
    w.open_sheet(sb, "multipole")
    w.open_sheet(sb, "schematic")
    w.delete_sheet()
    q = [t for k, t in dialogs.seen if k == "question"][-1]
    assert "list rozvaděče" in q and "zůstane" in q and "„?“" in q
    assert sb not in p.sheets
    assert all(w._unwrap(w.tabs.widget(i)).scene().sheet is not sb for i in range(w.tabs.count()))
    assert not any(isinstance(w._unwrap(w.tabs.widget(i)), MultipoleView) and
                   w._unwrap(w.tabs.widget(i)).scene().sheet is sb for i in range(w.tabs.count()))
    sc = w._jps_scene(jps)
    used = {end.port for x in jps.wires for end in (x.a, x.b) if end.element_id == block_id}
    assert used and used <= set(sc.element_items[block_id].symbol.orphan_ports)
    assert all(x.id in sc.wire_items for x in jps.wires if x.touches(block_id))
    assert any(f.code == "bad_port" for f in check_project(p, lib))
    p.save(tmp_path / "del.ecp")
    w2 = _win(lib, Project.load(tmp_path / "del.ecp"))
    assert w2.tabs.count() == len(p.sheets)
    w.undo.setClean()
    w2.undo.setClean()


def test_delete_parent_sheet_detaches_switchboards(app, lib, dialogs):
    p = _project()
    blk = Element("fve.switchboard", 200, 150, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    w = _win(lib, p)
    w.tabs.setCurrentIndex(0)
    w.delete_sheet()
    assert "bez nadřazeného bloku" in [t for k, t in dialogs.seen if k == "question"][-1]
    assert p.sheets == [sb] and sb.parent_element_id is None
    w.undo.setClean()


# ---- 3: otevření vadného projektu ---------------------------------------------------------------------------------
def test_failed_open_keeps_original_project(app, lib, dialogs, tmp_path, monkeypatch):
    good = _project("Dobrý")
    gp = tmp_path / "good.ecp"
    good.save(gp)
    w = _win(lib, Project.load(gp))
    before = (w.project, w.tabs.count(), w.windowTitle())
    bad = Project.load(EXAMPLE)
    victim = bad.sheets[0].elements[1]
    bp = tmp_path / "bad.ecp"
    bad.save(bp)
    import envocad.model.project as mp
    orig = mp.element_symbol

    def broken(project, e, lib_):
        if e.id == victim.id:
            raise RuntimeError("rozbitá značka")
        return orig(project, e, lib_)
    monkeypatch.setattr(mp, "element_symbol", broken)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bp), "")))
    w.open_project()
    assert (w.project, w.tabs.count(), w.windowTitle()) == before
    msg = [t for k, t in dialogs.seen if k == "critical"][-1]
    assert f"list „{bad.sheets[0].name}“" in msg and f"prvek {victim.ref}" in msg and "rozbitá značka" in msg
    # scéna padající při stavbě: totéž
    monkeypatch.setattr(mp, "element_symbol", orig)
    monkeypatch.setattr(MainWindow, "_build_tab", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("scéna")))
    w.open_project()
    assert (w.project, w.tabs.count(), w.windowTitle()) == before
    assert "nejde zobrazit" in [t for k, t in dialogs.seen if k == "critical"][-1]


def test_open_unknown_symbol_uses_placeholder(app, lib, dialogs, tmp_path, monkeypatch):
    d = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    d["sheets"][0]["elements"][0]["symbol_id"] = "x.unknown"
    bp = tmp_path / "unk.ecp"
    bp.write_text(json.dumps(d), encoding="utf-8")
    w = _win(lib)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bp), "")))
    w.open_project()
    assert w.project.path == bp and not [k for k, _ in dialogs.seen if k == "critical"]
    eid = w.project.sheets[0].elements[0].id
    assert w.scene.element_items[eid].symbol.placeholder
    assert "neznámé značky" in w.statusBar().currentMessage()


def test_open_corrupt_file_message(app, lib, dialogs, tmp_path, monkeypatch):
    bp = tmp_path / "c.ecp"
    bp.write_text('{"format": "envocad-project", "sheets": [ {', encoding="utf-8")
    w = _win(lib)
    p0 = w.project
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bp), "")))
    w.open_project()
    assert w.project is p0 and "Soubor je poškozen" in [t for k, t in dialogs.seen if k == "critical"][-1]


# ---- 4, 5, 16: autosave a obnova ------------------------------------------------------------------------------------
def _dirty(w):
    f = w.project.sheets[0].elements[0]
    w.scene.set_attr(f.id, False, "desc", "změna")
    assert not w.undo.isClean()


def test_autosave_does_not_touch_project_path(app, lib, dialogs, tmp_path, monkeypatch):
    w = _win(lib)
    w.project.path = tmp_path / "real.ecp"
    _dirty(w)
    import envocad.model.project as mp

    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(mp, "write_json_atomic", boom)
    w.autosave()
    assert w.project.path == tmp_path / "real.ecp"
    monkeypatch.undo()
    w.autosave()
    assert w.project.path == tmp_path / "real.ecp" and w._autosave_path().exists()
    data = json.loads(w._autosave_path().read_text(encoding="utf-8"))
    assert data["format"] == "envocad-project"
    assert w._autosave_path().with_suffix(".orig").read_text(encoding="utf-8") == str(tmp_path / "real.ecp")
    w.undo.setClean()


def test_autosave_path_unique_and_cleared(app, lib, dialogs, tmp_path):
    w1, w2 = _win(lib), _win(lib)
    w1.project.path = tmp_path / "a" / "proj.ecp"
    w2.project.path = tmp_path / "b" / "proj.ecp"
    assert w1._autosave_path() != w2._autosave_path()
    w3, w4 = _win(lib), _win(lib)
    assert w3._autosave_path() != w4._autosave_path()        # nepojmenované projekty dvou oken
    # po uložení autosave pryč
    (tmp_path / "a").mkdir()
    _dirty(w1)
    w1.autosave()
    assert w1._autosave_path().exists()
    assert w1.save_project()
    assert not list((home_dir() / "autosave").glob("proj-*.autosave.ecp"))
    # zavření s Discard → autosave pryč
    _dirty(w3)
    w3.autosave()
    auto = w3._autosave_path()
    assert auto.exists()
    dialogs.answers.append(QMessageBox.Discard)
    assert w3.close()
    assert not auto.exists() and not auto.with_suffix(".orig").exists()
    for w in (w2, w4):
        w.undo.setClean()


def test_recovery_keeps_autosave_on_failure_and_offers_newest(app, lib, dialogs, tmp_path):
    d = home_dir() / "autosave"
    d.mkdir(parents=True, exist_ok=True)
    bad = d / "x.autosave.ecp"
    bad.write_text("{nejde", encoding="utf-8")
    w = _win(lib)
    QApplication.processEvents()
    w.offer_recovery()
    assert bad.exists()                                     # nepovedlo se načíst → kopie zůstává
    assert "zůstává" in [t for k, t in dialogs.seen if k == "warning"][-1]
    bad.unlink()
    older, newer = d / "a.autosave.ecp", d / "b.autosave.ecp"
    older.write_text(json.dumps(_project("Starší").to_dict()), encoding="utf-8")
    newer.write_text(json.dumps(_project("Novější").to_dict()), encoding="utf-8")
    (d / "b.autosave.orig").write_text(str(tmp_path / "novejsi.ecp"), encoding="utf-8")
    os.utime(older, (1_000_000, 1_000_000))
    dialogs.seen.clear()
    w.offer_recovery()
    q = [t for k, t in dialogs.seen if k == "question"]
    assert len(q) == 1 and "Další automaticky uložené kopie (1)" in q[0]
    assert w.project.name == "Novější" and w.project.path == tmp_path / "novejsi.ecp"
    assert not newer.exists() and older.exists()
    assert not w.undo.isClean() and w.windowTitle().startswith("novejsi.ecp*")
    w.undo.setClean()
    older.unlink()


# ---- 8: uložení ---------------------------------------------------------------------------------------------------
def test_save_as_failure_keeps_path_and_title(app, lib, dialogs, tmp_path, monkeypatch):
    w = _win(lib)
    _dirty(w)
    title = w.windowTitle()
    bad = tmp_path / "nodir" / "sub" / "x.ecp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(bad), "")))
    assert w.save_project_as() is False
    assert w.project.path is None and w.windowTitle() == title and not w.undo.isClean()
    msg = [t for k, t in dialogs.seen if k == "critical"][-1]
    assert "nepodařilo uložit" in msg and "neexistuje" in msg
    ok = tmp_path / "ok.ecp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(ok), "")))
    assert w.save_project_as() and w.project.path == ok and w.windowTitle() == "ok.ecp – EnvoCAD"


# ---- 6: import DXF ------------------------------------------------------------------------------------------------
def test_import_dxf_refuses_existing_id(app, lib, dialogs, tmp_path, monkeypatch):
    import ezdxf
    doc = ezdxf.new()
    doc.modelspace().add_line((0, 0), (10, 0))
    f = tmp_path / "s.dxf"
    doc.saveas(f)
    w = _win(lib)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(f), "")))
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("(modelspace)", True)))
    ids = ["fve.inverter", "moje.znacka"]
    prompts = []
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: (prompts.append(k.get("text", "")) or
                                                      (ids.pop(0) if ids else "Název"), True)))
    monkeypatch.setattr(QInputDialog, "getDouble", staticmethod(lambda *a, **k: (1.0, True)))
    w.import_dxf_symbol()
    warn = [t for k, t in dialogs.seen if k == "warning"]
    assert warn and "vestavěná" in warn[0] and "fve.inverter_2" in warn[0]
    assert prompts[1] == "fve.inverter_2"                              # návrh volného ID
    assert [p.name for p in lib.get_symbol("fve.inverter").ports] == ["DC1", "DC2", "AC"]
    assert lib.get_symbol("moje.znacka").primitives
    # poškozený DXF → hláška, žádná výjimka
    f.write_text("hello", encoding="utf-8")
    dialogs.seen.clear()
    w.import_dxf_symbol()
    assert "nejde načíst" in [t for k, t in dialogs.seen if k == "warning"][-1]


# ---- 14: start s vadným souborem ------------------------------------------------------------------------------------
def test_start_with_bad_file_gives_message(tmp_path):
    from envocad.app import load_start_project
    f = tmp_path / "bad.ecp"
    f.write_text("[1]", encoding="utf-8")
    project, err = load_start_project([str(f)])
    assert project is None and "Projekt nelze otevřít" in err and "prázdným projektem" in err
    assert load_start_project([]) == (None, None)
    project, err = load_start_project([str(EXAMPLE)])
    assert project is not None and err is None


def test_window_with_unrenderable_project_starts_empty(app, lib, dialogs, monkeypatch):
    calls = []
    orig = MainWindow._build_tab

    def flaky(self, project, sheet, kind):
        if project.name == "Rozbitý":
            calls.append(sheet)
            raise RuntimeError("nejde")
        return orig(self, project, sheet, kind)
    monkeypatch.setattr(MainWindow, "_build_tab", flaky)
    w = _win(lib, _project("Rozbitý"))
    assert calls and w.project.name != "Rozbitý" and w.tabs.count() == 1
    assert "prázdným projektem" in [t for k, t in dialogs.seen if k == "critical"][-1]


# ---- 15: pluginy --------------------------------------------------------------------------------------------------
def test_failed_plugin_status_message(app, lib, dialogs, tmp_path, monkeypatch):
    from envocad import plugins
    pd = tmp_path / "plugins"
    pd.mkdir()
    (pd / "rozbity.py").write_text("raise RuntimeError('x')\n", encoding="utf-8")
    monkeypatch.setattr(plugins, "plugin_dirs", lambda: [pd])
    w = _win(lib)
    QApplication.processEvents()
    assert w.plugins.failed and w.statusBar().currentMessage() == "Plugin rozbity se nenačetl (viz log)"


# ---- 13: poškozený projekt neshodí pohledy ani exporty ---------------------------------------------------------------
def test_views_and_exports_survive_unknown_symbol_and_dangling_wire(app, lib, dialogs, tmp_path):
    from envocad.export.doc_pdf import export_documentation_pdf
    from envocad.export.xlsx_export import export_reports_xlsx
    d = _spec_project().to_dict()
    d["sheets"][0]["elements"][0]["symbol_id"] = "x.unknown"
    d["sheets"][0]["wires"][0]["a"]["element_id"] = "nonexistent"
    p = Project.from_dict(d)
    w = _win(lib, p)
    for s in p.sheets:
        for kind in ("schematic", "multipole", "terminals") + (("layout",) if s.is_switchboard else ()):
            w.open_sheet(s, kind)
            QApplication.processEvents()
            w.view.viewport().repaint()
    assert d["sheets"][0]["wires"][0]["id"] not in w._jps_scene(p.sheets[0]).wire_items
    export_reports_xlsx(p, lib, tmp_path / "r.xlsx")
    assert export_documentation_pdf(p, lib, tmp_path / "d.pdf") > 0
    assert len(p.sheets[0].wires) == len(d["sheets"][0]["wires"])     # model beze změny
    w.undo.setClean()
