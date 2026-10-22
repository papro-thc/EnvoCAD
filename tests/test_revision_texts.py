"""Volné texty listu (`Sheet.texts`) v porovnání revizí, značkách a otisku listu; migrace otisků v15 → v16 (bez Qt).

Data: `data/v15_closed_revision_texts.ecp` uložil EnvoCAD formátu 15 (otisky uzavřené revize A spočtené bez textů):
list „sheet-texts“ se dvěma texty, list „sheet-plain“ bez textů.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from envocad.model.diff import (
    MOVE_DETAIL,
    diff_projects,
    sheet_fingerprint,
    text_mark_pos,
    upgrade_fingerprints,
)
from envocad.model.project import FORMAT_VERSION, Element, Project, Revision, Sheet, SheetText
from envocad.model.revision import (
    apply_changes,
    changed_after_close,
    close_revision,
    marks_from_changes,
    open_revision,
)

DATA = Path(__file__).parent / "data"


def _project() -> Project:
    s = Sheet(name="L1", id="s1")
    s.elements.append(Element("fve.inverter", 100, 100, attrs={"ref": "T1"}, id="e1"))
    s.texts = [SheetText(20, 250, "Poznámka", id="t1"), SheetText(200, 40, "Část A", height=3.5, id="t2")]
    return Project(name="P", sheets=[s])


def _changed(p: Project) -> tuple[Project, Sheet]:
    q = Project.from_dict(copy.deepcopy(p.to_dict()))
    return q, q.sheets[0]


def test_diff_sees_added_changed_removed_text():
    p = _project()
    q, s = _changed(p)
    assert diff_projects(p, q) == []
    s.text("t1").text = "Poznámka – kabely v chráničce"
    s.texts = [t for t in s.texts if t.id != "t2"]
    s.texts.append(SheetText(50, 60, "Nový nadpis", id="t3"))
    ch = {(c.kind, c.what): c for c in diff_projects(p, q)}
    assert set(ch) == {("změněno", "text"), ("odebráno", "text"), ("přidáno", "text")}
    assert ch[("změněno", "text")].detail == "„Poznámka“ → „Poznámka – kabely v chráničce“"
    assert ch[("odebráno", "text")].detail == "„Část A“"
    assert ch[("přidáno", "text")].detail == "„Nový nadpis“"
    # značka u textu: odebraný v původní poloze, ostatní u nové polohy
    assert (ch[("odebráno", "text")].x, ch[("odebráno", "text")].y) == text_mark_pos(p.sheets[0].text("t2"))
    assert (ch[("přidáno", "text")].x, ch[("přidáno", "text")].y) == text_mark_pos(s.text("t3"))
    assert all(c.sheet_id == "s1" and c.target_id == "" for c in ch.values())


def test_text_height_and_move():
    p = _project()
    q, s = _changed(p)
    s.text("t2").height = 5.0
    s.text("t1").x += 10
    ch = diff_projects(p, q)
    assert [c.detail for c in ch if c.what == "text" and c.kind == "změněno"] == [MOVE_DETAIL, "výška: 3.5 → 5"]


def test_long_and_multiline_text_shortened():
    p = _project()
    q, s = _changed(p)
    s.text("t1").text = "řádek 1\n" + "x" * 80
    (c,) = diff_projects(p, q)
    assert "\n" not in c.detail and c.detail.endswith("…“") and len(c.detail.split(" → ")[1]) == 42


def test_texts_on_new_sheet_listed_without_own_marks():
    p = _project()
    q = Project.from_dict(copy.deepcopy(p.to_dict()))
    q.sheets.append(Sheet(name="L2", id="s2", texts=[SheetText(10, 10, "A", id="ta")]))
    ch = diff_projects(p, q)
    assert any(c.what == "text" and c.sheet_id == "s2" for c in ch)
    marks = marks_from_changes(ch)
    assert [(m.sheet_id, m.x) for m in marks] == [("s2", None)]        # jen značka celého nového listu


def test_marks_for_text_changes():
    p = _project()
    q, s = _changed(p)
    s.text("t1").text = "Jiná poznámka"
    s.text("t2").x += 5                                   # jen posun → bez značky (jako u prvku)
    marks = marks_from_changes(diff_projects(p, q))
    assert len(marks) == 1
    m = marks[0]
    assert (m.sheet_id, m.target_id, m.is_wire, m.kind) == ("s1", "", False, "změněno")
    assert (m.x, m.y) == text_mark_pos(s.text("t1")) and m.text.startswith("text změněno: ")


def test_fingerprint_sees_text_but_not_text_position():
    p = _project()
    s = p.sheets[0]
    fp = sheet_fingerprint(s)
    s.text("t1").x += 7.5
    s.text("t1").y -= 2.5
    assert sheet_fingerprint(s) == fp
    s.text("t1").text = "jiný"
    assert sheet_fingerprint(s) != fp
    s.text("t1").text = "Poznámka"
    assert sheet_fingerprint(s) == fp
    s.text("t2").height = 2.5
    assert sheet_fingerprint(s) != fp
    s.text("t2").height = 3.5
    s.texts.reverse()                                     # pořadí textů otisk nemění
    assert sheet_fingerprint(s) == fp
    s.texts.append(SheetText(0, 0, "nový"))
    assert sheet_fingerprint(s) != fp


def test_fingerprint_without_texts_unchanged():
    """List bez textů má stejný otisk jako ve formátu ≤ 15 (stará uzavřená revize sedí bez migrace)."""
    s = _project().sheets[0]
    s.texts = []
    assert sheet_fingerprint(s) == sheet_fingerprint(s, texts=False)


def test_closed_revision_reports_text_change():
    p = _project()
    rev = open_revision(p, "A")
    close_revision(p, rev)
    assert changed_after_close(p) == []
    p.sheets[0].text("t2").text = "Část B"
    assert [s.id for s, _r in changed_after_close(p)] == ["s1"]
    # porovnání do další revize změnu označí → varování zmizí
    old = Project.from_dict(copy.deepcopy(p.to_dict()))
    old.sheets[0].text("t2").text = "Část A"
    rev_b = open_revision(p, "B")
    apply_changes(p, rev_b, diff_projects(old, p))
    assert changed_after_close(p) == []


def test_old_v15_file_closed_revision_no_false_change():
    raw = json.loads((DATA / "v15_closed_revision_texts.ecp").read_text(encoding="utf-8"))
    assert raw["format_version"] == 15 < FORMAT_VERSION and raw["revisions"][0]["closed"]
    s_raw = next(s for s in raw["sheets"] if s["id"] == "sheet-texts")
    assert s_raw["texts"]
    p = Project.from_dict(raw)
    assert changed_after_close(p) == []
    rev = p.revisions[0]
    assert all(rev.fingerprints[s.id] == sheet_fingerprint(s) for s in p.sheets)
    assert rev.fingerprints["sheet-plain"] == raw["revisions"][0]["fingerprints"]["sheet-plain"]  # bez textů beze změny
    # po migraci se změna textu pozná
    p.sheets[0].text("txt-2").text = "Část B"
    assert [s.id for s, _r in changed_after_close(p)] == ["sheet-texts"]
    # uložení v16 a nové načtení: otisky se už nepřevádějí
    q = Project.from_dict(json.loads(json.dumps(Project.from_dict(raw).to_dict())))
    assert q.to_dict()["format_version"] == FORMAT_VERSION and changed_after_close(q) == []


def test_old_v15_file_changed_after_close_still_reported():
    """List změněný po uzavření (ve v15) migrace nepřepíše – změna se dál hlásí."""
    raw = json.loads((DATA / "v15_closed_revision_texts.ecp").read_text(encoding="utf-8"))
    s_raw = next(s for s in raw["sheets"] if s["id"] == "sheet-texts")
    s_raw["elements"][0]["attrs"]["ref"] = "T9"
    p = Project.from_dict(raw)
    assert [s.id for s, _r in changed_after_close(p)] == ["sheet-texts"]
    assert p.revisions[0].fingerprints["sheet-texts"] == raw["revisions"][0]["fingerprints"]["sheet-texts"]


def test_upgrade_fingerprints_only_legacy_match():
    p = _project()
    s = p.sheets[0]
    legacy = sheet_fingerprint(s, texts=False)
    p.revisions = [Revision("A", closed=True, fingerprints={"s1": legacy}),
                   Revision("B", closed=True, fingerprints={"s1": "jiný"}), Revision("C")]
    upgrade_fingerprints(p)
    assert p.revisions[0].fingerprints == {"s1": sheet_fingerprint(s)}
    assert p.revisions[1].fingerprints == {"s1": "jiný"} and p.revisions[2].fingerprints == {}
