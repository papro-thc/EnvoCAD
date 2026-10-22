"""Připomínky (redlining): model, pomocné funkce, geometrie, kontroly, DXF, nezávislost na diffu/otisku. Bez Qt."""
import copy

import ezdxf
import pytest

from envocad.model import notes as nt
from envocad.model.checks import INFO, check_project, note_findings
from envocad.model.diff import diff_projects, sheet_fingerprint
from envocad.model.project import NOTE_STATUSES, Element, Note, Project, Sheet, Wire, WireEnd
from envocad.model.symbol import GRID


def _on_grid(v: float) -> bool:
    return abs(v / GRID - round(v / GRID)) < 1e-9


@pytest.fixture
def proj():
    p = Project()
    s = p.sheets[0]
    s.elements += [Element("fve.breaker_mcb", 100, 100, attrs={"ref": "F1"}, id="f1"),
                   Element("fve.breaker_mcb", 150, 100, attrs={"ref": "F2"}, id="f2")]
    s.wires.append(Wire(WireEnd("f1", "2"), WireEnd("f2", "1"), attrs={"ref": "W1"}, id="w1"))
    return p


# ---- model a pomocné funkce -------------------------------------------------------------------------
def test_note_defaults_and_statuses():
    n = Note("s1", 10.0, 20.0)
    assert n.status == "open" and n.status in NOTE_STATUSES and NOTE_STATUSES == ("open", "resolved")
    assert not n.is_rect and n.no == 0 and len(n.id) == 12
    assert Note("s1", 0, 0, w=10, h=5).is_rect
    assert Note.from_dict(n.to_dict()) == n


def test_put_number_and_replace(proj):
    sid = proj.sheets[0].id
    assert nt.next_note_no(proj) == 1
    a, b = Note(sid, 10, 10, "a"), Note(sid, 20, 20, "b")
    assert nt.put_note(proj, a) == 0 and a.no == 1
    assert nt.put_note(proj, b) == 1 and b.no == 2
    # nahrazení stejného id na místě, číslo zůstává
    a2 = copy.deepcopy(a)
    a2.text = "a upravená"
    assert nt.put_note(proj, a2) == 0 and proj.notes[0].text == "a upravená" and proj.notes[0].no == 1
    assert len(proj.notes) == 2
    assert nt.note(proj, b.id) is b and nt.note(proj, "nic") is None


def test_remove_and_restore_at_index(proj):
    sid = proj.sheets[0].id
    ns = [Note(sid, 0, 0, str(i)) for i in range(3)]
    for n in ns:
        nt.put_note(proj, n)
    got = nt.remove_note(proj, ns[1].id)
    assert got == (ns[1], 1) and [n.text for n in proj.notes] == ["0", "2"]
    assert nt.remove_note(proj, ns[1].id) is None
    nt.put_note(proj, ns[1], index=1)          # undo smazání vrátí na původní místo i číslo
    assert [n.text for n in proj.notes] == ["0", "1", "2"] and ns[1].no == 2
    # čísla se nepřečíslovávají: po smazání nejvyšší + 1
    nt.remove_note(proj, ns[0].id)
    assert nt.next_note_no(proj) == 4
    # ani po smazání nejvyšší: čítač meta["note_seq"] (řetězec) si pamatuje přidělená čísla
    nt.remove_note(proj, ns[2].id)
    assert proj.meta["note_seq"] == "3" and nt.next_note_no(proj) == 4
    n = Note(sid, 0, 0, "nová")
    nt.put_note(proj, n)
    assert n.no == 4 and proj.meta["note_seq"] == "4"
    # explicitní vyšší číslo čítač posune, nižší ne; nečitelný čítač = 0 → next = nejvyšší + 1
    nt.put_note(proj, Note(sid, 0, 0, "x", no=10))
    assert proj.meta["note_seq"] == "10" and nt.next_note_no(proj) == 11
    nt.put_note(proj, Note(sid, 0, 0, "y", no=7))
    assert proj.meta["note_seq"] == "10"
    proj.meta["note_seq"] = "nic"
    assert nt.next_note_no(proj) == 11


def test_note_seq_survives_save_load(proj, tmp_path):
    sid = proj.sheets[0].id
    for i in range(3):
        nt.put_note(proj, Note(sid, 0, 0, str(i)))
    nt.remove_note(proj, proj.notes[-1].id)
    path = tmp_path / "p.ecp"
    proj.save(path)
    back = Project.load(path)
    assert back.meta["note_seq"] == "3" and nt.next_note_no(back) == 4


def test_notes_on_sheet_filter_and_order(proj):
    other = Sheet(name="Druhý")
    proj.sheets.append(other)
    sid = proj.sheets[0].id
    nt.put_note(proj, Note(sid, 0, 0, "x", no=5))
    nt.put_note(proj, Note(other.id, 0, 0, "y"))
    nt.put_note(proj, Note(sid, 0, 0, "z", no=2, status="resolved"))
    assert [n.no for n in nt.notes_on_sheet(proj, sid)] == [2, 5]
    assert [n.text for n in nt.notes_on_sheet(proj, sid, ("open",))] == ["x"]
    assert [n.text for n in nt.notes_on_sheet(proj, other.id)] == ["y"]


def test_resolve_and_reopen():
    n = Note("s", 0, 0, "Opravit")
    assert nt.resolve(n, "JN", "2026-10-17T08:00", "Hotovo") is n
    assert (n.status, n.resolved_by, n.resolved, n.reply) == ("resolved", "JN", "2026-10-17T08:00", "Hotovo")
    nt.reopen(n)
    assert (n.status, n.resolved_by, n.resolved) == ("open", "", "") and n.reply == "Hotovo"
    nt.resolve(n, "PR", "2026-10-18T09:00")
    assert n.reply == "Hotovo"                 # bez nové odpovědi zůstane původní


def test_orphans_and_target_label(proj):
    sid = proj.sheets[0].id
    el = Note(sid, 0, 0, target_id="f1")
    wire = Note(sid, 0, 0, target_id="w1", is_wire=True)
    gone = Note(sid, 0, 0, target_id="smazany")
    none = Note(sid, 0, 0)
    orphan = Note("smazany_list", 0, 0, target_id="f1")
    proj.notes = [el, wire, gone, none, orphan]
    assert nt.note_target_label(proj, el) == "F1"
    assert nt.note_target_label(proj, wire) == "W1"
    assert nt.note_target_label(proj, gone) == "(smazáno)"
    assert nt.note_target_label(proj, none) == ""
    assert nt.note_target_label(proj, orphan) == "(smazáno)"
    assert nt.orphan_notes(proj) == [orphan]


def test_current_user(monkeypatch):
    from envocad import settings
    monkeypatch.setattr(settings.getpass, "getuser", lambda: "osuser")
    assert settings.current_user() == "osuser"
    data = settings.load_settings()
    data["standard"]["author"] = "PR"
    settings.save_settings(data)
    assert settings.current_user() == "PR"

    def boom():
        raise OSError("bez uživatele")
    monkeypatch.setattr(settings.getpass, "getuser", boom)
    data["standard"]["author"] = ""
    settings.save_settings(data)
    assert settings.current_user() == ""


# ---- geometrie -----------------------------------------------------------------------------------------
def test_point_shape_on_grid():
    n = Note("s", 100.0, 50.0, "text", no=7)
    g = nt.note_shape(n)
    assert g.note_id == n.id and g.status == "open"
    # křížek 1 mm v kotvě + odkazová čára do (x + 2,5; y + 2,5)
    assert (99.5, 49.5, 100.5, 50.5) in g.lines and (100.0, 50.0, 102.5, 52.5) in g.lines
    flag = g.polylines[-1]
    assert flag[0] == (102.5, 52.5) and flag[2][1] - flag[0][1] == nt.FLAG_H
    assert all(_on_grid(x) and _on_grid(y) for x, y in flag)
    assert [t[2] for t in g.texts] == ["7"]          # bez with_text jen číslo
    x0, y0, x1, y1 = g.bbox
    assert x0 <= 99.5 and y0 <= 49.5 and x1 == flag[2][0] and y1 == flag[2][1]


def test_flag_width_grows_with_label():
    assert nt.flag_width("7") == 5.0
    assert nt.flag_width("123") == 10.0              # 1,6·3 + 3 = 7,8 → na mřížku 10
    assert all(_on_grid(nt.flag_width(str(10 ** k))) for k in range(6))


def test_rect_shape_and_with_text():
    n = Note("s", 10.0, 20.0, "slovo " * 20, no=3, w=30.0, h=15.0)
    g = nt.note_shape(n)
    assert g.polylines[0] == [(10.0, 20.0), (40.0, 20.0), (40.0, 35.0), (10.0, 35.0)]
    assert g.polylines[1][0] == (40.0, 35.0)          # praporek na pravém horním rohu
    assert not g.lines
    gt = nt.note_shape(n, with_text=True)
    body = [t[2] for t in gt.texts[1:]]
    assert len(body) >= 3 and all(len(t) <= nt.WRAP for t in body)
    assert " ".join(body).split() == n.text.split()
    assert gt.bbox[1] < g.bbox[1] or gt.bbox[2] > g.bbox[2]


def test_notes_geometry_filters_status(proj):
    sid = proj.sheets[0].id
    proj.notes = [Note(sid, 0, 0, no=1), Note(sid, 0, 0, no=2, status="resolved"), Note("jiny", 0, 0, no=3)]
    s = proj.sheets[0]
    assert [g.status for g in nt.notes_geometry(proj, s)] == ["open"]
    assert len(nt.notes_geometry(proj, s, statuses=None)) == 2


# ---- kontroly ------------------------------------------------------------------------------------------
def test_note_findings(proj, monkeypatch):
    s = proj.sheets[0]
    assert note_findings(proj) == []
    proj.notes = [Note(s.id, 0, 0, no=1), Note(s.id, 0, 0, no=2), Note(s.id, 0, 0, no=3, status="resolved"),
                  Note("smazany", 0, 0, "Na smazaném listu", no=4)]
    f = note_findings(proj)
    opened = [x for x in f if x.code == "note_open"]
    assert len(opened) == 1 and opened[0].sheet_id == s.id and opened[0].severity == INFO
    assert opened[0].text == "2 otevřené připomínky"
    orphan = [x for x in f if x.code == "note_orphan"]
    assert len(orphan) == 1 and orphan[0].severity == INFO and "č. 4" in orphan[0].text
    # check_project je volá
    from envocad.library.store import LibraryStore
    codes = {x.code for x in check_project(proj, LibraryStore(), standard_paper="A4")}
    assert {"note_open", "note_orphan"} <= codes


# ---- diff a otisk připomínky ignorují ----------------------------------------------------------------
def test_diff_and_fingerprint_ignore_notes(proj):
    old = copy.deepcopy(proj)
    s = proj.sheets[0]
    fp = sheet_fingerprint(s)
    nt.put_note(proj, Note(s.id, 10, 10, "Změnit jistič", target_id="f1"))
    assert diff_projects(old, proj) == []
    assert sheet_fingerprint(s) == fp
    nt.resolve(proj.notes[0], "PR", "2026-10-16T14:05")
    assert diff_projects(old, proj) == [] and sheet_fingerprint(s) == fp


# ---- DXF -----------------------------------------------------------------------------------------------
def test_dxf_notes_layer_only_with_notes(tmp_path):
    from envocad.export.dxf_export import NOTES_COLOR, NOTES_LAYER, export_sheet_dxf
    from envocad.library.store import LibraryStore
    lib = LibraryStore()
    p = Project()
    s = p.sheets[0]
    s.elements.append(Element("fve.breaker_mcb", 100, 100, attrs={"ref": "F1"}))
    p.notes = [Note(s.id, 50, 50, "Bod", no=1), Note(s.id, 100, 150, "Obdélník " * 8, no=2, w=20, h=10),
               Note(s.id, 10, 10, "Vyřešená", no=3, status="resolved")]
    export_sheet_dxf(p, s, lib, tmp_path / "bez.dxf")
    doc = ezdxf.readfile(tmp_path / "bez.dxf")
    assert NOTES_LAYER not in doc.layers
    export_sheet_dxf(p, s, lib, tmp_path / "s.dxf", notes=True)
    doc = ezdxf.readfile(tmp_path / "s.dxf")
    assert NOTES_LAYER in doc.layers and doc.layers.get(NOTES_LAYER).color == NOTES_COLOR == 6
    ents = doc.modelspace().query(f'*[layer=="{NOTES_LAYER}"]')
    texts = [e.dxf.text for e in ents if e.dxftype() == "TEXT"]
    assert "1" in texts and "2" in texts and "3" not in texts and "Bod" in texts   # jen otevřené, s textem
    assert not any("Vyřešená" in t for t in texts)
    polys = [e for e in ents if e.dxftype() == "LWPOLYLINE"]
    assert len(polys) == 3 and all(pl.closed for pl in polys)   # 2 praporky + obrys obdélníku


def test_czech_plural_and_count_label():
    assert [nt.plural(n, "a", "b", "c") for n in (0, 1, 2, 4, 5, 11, 22)] == ["c", "a", "b", "b", "c", "c", "c"]
    assert nt.count_label(1) == "1 připomínka" and nt.count_label(3) == "3 připomínky"
    assert nt.count_label(5) == "5 připomínek" and nt.count_label(0) == "0 připomínek"
    assert nt.count_label(1, nt.OPEN_NOTE_WORDS) == "1 otevřená připomínka"
    assert nt.count_label(4, nt.OPEN_NOTE_WORDS) == "4 otevřené připomínky"
    assert nt.count_label(12, nt.OPEN_NOTE_WORDS) == "12 otevřených připomínek"
