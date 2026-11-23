"""F7: potlačení nálezu s důvodem (issue #139, fáze 1) – datový model, kontroly, příkazy WAIVE / UNWAIVE / CHECKS."""
import copy
import json

import pytest

from envocad.cmd import CommandRunner, Journal
from envocad.library.store import LibraryStore
from envocad.model.checks import INFO, Finding, check_project, summary
from envocad.model.project import (
    Element,
    Project,
    Sheet,
    Waiver,
    Wire,
    WireEnd,
    restore_sheets_state,
    sheets_state,
)


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _project() -> Project:
    """Tři nezapojené jističe: F1, F2 a prvek bez označení -> `unconnected` na každém (+ `no_ref`, `no_article`)."""
    p = Project(name="Waive")
    s = p.sheets[0]
    s.elements += [Element("fve.breaker_mcb", 50, 50, attrs={"ref": "F1"}),
                   Element("fve.breaker_mcb", 100, 50, attrs={"ref": "F2"}),
                   Element("fve.breaker_mcb", 150, 50)]
    return p


def _check(p, lib, **kw):
    return check_project(p, lib, standard_paper="A4", **kw)


def _by(fs, code, ref=None):
    return [f for f in fs if f.code == code and (ref is None or f.ref == ref)]


def _el(p, ref):
    return next(e for e in p.sheets[0].elements if e.ref == ref)


def _waiver(p, code, ref, **kw):
    e = _el(p, ref)
    return Waiver(code, e.id, p.sheets[0].id, **{"reason": "záměrně", **kw})


# ---- datový model -------------------------------------------------------------------------------------------------
def test_waiver_dict_roundtrip_and_key():
    w = Waiver("unconnected", "e1", "s1", "rezerva", "PR", "2026-11-23", "TZ 3.2")
    assert w.key == ("unconnected", "e1", "s1")
    d = w.to_dict()
    assert set(d) == {"code", "target_id", "sheet_id", "reason", "author", "date", "ref"}
    assert Waiver.from_dict(d) == w


def test_waiver_from_dict_tolerant():
    w = Waiver.from_dict({"code": "dup_ref", "target_id": None, "sheet_id": "s1"})
    assert (w.code, w.target_id, w.sheet_id) == ("dup_ref", "", "s1")
    assert (w.reason, w.author, w.date, w.ref) == ("", "", "", "")
    assert Waiver.from_dict({}) == Waiver("", "", "")


def test_project_waivers_default_and_roundtrip(tmp_path):
    p = Project()
    assert p.waivers == [] and p.to_dict()["waivers"] == []
    p.waivers = [Waiver("unconnected", "e1", p.sheets[0].id, "rezerva", "PR", "2026-11-23", "TZ"),
                 Waiver("sb_no_block", "", p.sheets[0].id, "dočasně")]
    d = json.loads(json.dumps(p.to_dict()))
    assert len(d["waivers"]) == 2 and d["waivers"][0]["reason"] == "rezerva"
    assert Project.from_dict(copy.deepcopy(d)).waivers == p.waivers
    f = tmp_path / "w.ecp"
    p.save(f)
    assert Project.load(f).waivers == p.waivers


def test_sheets_state_includes_waivers(lib):
    p = _project()
    p.waivers = [_waiver(p, "unconnected", "F1")]
    st = sheets_state(p)
    assert "waivers" in st and len(st["waivers"]) == 1
    p.waivers = []
    restore_sheets_state(p, st)
    assert [w.key for w in p.waivers] == [("unconnected", _el(p, "F1").id, p.sheets[0].id)]


# ---- check_project ------------------------------------------------------------------------------------------------
def test_waived_finding_hidden_by_default(lib):
    p = _project()
    before = _check(p, lib)
    assert len(_by(before, "unconnected")) == 3
    p.waivers = [_waiver(p, "unconnected", "F1")]
    after = _check(p, lib)
    assert _by(after, "unconnected", "F1") == []
    # stejný kód na jiném prvku zůstane
    assert len(_by(after, "unconnected")) == 2 and _by(after, "unconnected", "F2")
    assert not any(f.waived for f in after)
    assert not _by(after, "waiver_orphan")


def test_include_waived_flags_finding(lib):
    p = _project()
    p.waivers = [_waiver(p, "unconnected", "F1", reason="rezerva do etapy 2")]
    fs = _check(p, lib, include_waived=True)
    w = _by(fs, "unconnected", "F1")
    assert len(w) == 1 and w[0].waived is True and w[0].waiver_reason == "rezerva do etapy 2"
    assert w[0].key == ("unconnected", _el(p, "F1").id, p.sheets[0].id)
    assert all(not f.waived for f in _by(fs, "unconnected", "F2"))


def test_waiver_covers_all_findings_with_same_key(lib):
    p = _project()
    e = _el(p, "F1")
    raw = [f for f in _check(p, lib, include_waived=True, aggregate=False) if f.target_id == e.id]
    assert len({f.code for f in raw}) >= 2                      # F1 má víc různých nálezů
    # dva nálezy se stejným klíčem: jedno potlačení kryje oba (klíč = kód + cíl + list)
    p.waivers = [_waiver(p, "unconnected", "F1")]
    fs = _check(p, lib, include_waived=True, aggregate=False)
    assert all(f.waived for f in fs if f.key == ("unconnected", e.id, p.sheets[0].id))
    assert any(f.target_id == e.id and not f.waived for f in fs)    # jiný kód téhož prvku zůstává


def test_summary_skips_waived(lib):
    p = _project()
    plain = summary(_check(p, lib))
    assert "potlačeno" not in plain
    p.waivers = [_waiver(p, "unconnected", "F1")]
    fs = _check(p, lib, include_waived=True)
    s = summary(fs)
    assert "potlačeno" in s
    # počty chyb/varování jsou bez potlačeného: shodné s výpisem bez include_waived
    assert s.split(",")[:3] == summary(_check(p, lib)).split(",")[:3]
    assert summary([Finding("varování", "s", "S", "e", False, "F1", "x", "unconnected", waived=True)]).startswith("0 chyb, 0 varování")


def test_waived_element_not_counted_in_aggregated_info(lib):
    p = _project()
    agg = _by(_check(p, lib), "no_article")
    assert len(agg) == 1 and "F1" in agg[0].text and "F2" in agg[0].text
    p.waivers = [_waiver(p, "no_article", "F1")]
    agg = _by(_check(p, lib), "no_article")
    assert len(agg) == 1 and "F1" not in agg[0].text and "F2" in agg[0].text
    # bez agregace jsou nálezy po jednom prvku
    raw = _by(_check(p, lib, include_waived=True, aggregate=False), "no_article")
    assert len(raw) == 3 and sum(f.waived for f in raw) == 1


def test_orphan_waiver_when_element_deleted(lib):
    p = _project()
    e = _el(p, "F1")
    sid = p.sheets[0].id
    p.waivers = [Waiver("unconnected", e.id, sid, "rezerva")]
    p.sheets[0].elements.remove(e)
    fs = _check(p, lib)
    orph = _by(fs, "waiver_orphan")
    assert len(orph) == 1
    o = orph[0]
    assert o.severity == INFO and "osiřelé" in o.text and "unconnected" in o.text
    assert o.target_id == "" and o.sheet_id == sid           # prvek zmizel, list existuje
    assert _by(_check(p, lib, include_waived=True), "waiver_orphan")


def test_orphan_waiver_when_sheet_and_element_gone(lib):
    p = _project()
    p.waivers = [Waiver("unconnected", "nic", "nic", "x")]
    o = _by(_check(p, lib), "waiver_orphan")
    assert len(o) == 1 and o[0].target_id == "" and o[0].sheet_id == ""


def test_orphan_waiver_when_problem_fixed(lib):
    p = _project()
    f1 = _el(p, "F1")
    p.waivers = [_waiver(p, "unconnected", "F1")]
    assert not _by(_check(p, lib), "waiver_orphan")
    p.sheets[0].elements.append(Element("fve.breaker_mcb", 200, 50, attrs={"ref": "F9"}))
    p.sheets[0].wires.append(Wire(WireEnd(f1.id, "1"), WireEnd(p.sheets[0].elements[-1].id, "1")))
    fs = _check(p, lib)
    o = _by(fs, "waiver_orphan")
    assert len(o) == 1 and o[0].target_id == f1.id and "osiřelé" in o[0].text


def test_waiver_orphan_cannot_be_waived(lib):
    p = _project()
    p.waivers = [Waiver("unconnected", "nic", p.sheets[0].id, "x")]
    p.waivers.append(Waiver("waiver_orphan", "", p.sheets[0].id, "ignoruj"))
    fs = _check(p, lib)
    assert [f for f in fs if f.code == "waiver_orphan" and not f.waived]


def test_sheet_level_waiver(lib):
    p = Project()
    sh = Sheet(name="Rozv", kind="switchboard", loc="RH")
    p.sheets.append(sh)
    assert _by(_check(p, lib), "sb_no_block")
    p.waivers = [Waiver("sb_no_block", "", sh.id, "dočasně")]
    assert not _by(_check(p, lib), "sb_no_block")
    assert _by(_check(p, lib, include_waived=True), "sb_no_block")[0].waived


# ---- příkazy ------------------------------------------------------------------------------------------------------
@pytest.fixture
def run(lib):
    p = _project()
    r = CommandRunner(p, lib, journal=Journal())

    def do(line: str, ok: bool = True):
        res = r.execute(line)
        assert res.ok == ok, (line, res.messages, res.error)
        return res
    do.p, do.r = p, r
    return do


def test_waive_by_ref(run):
    p = run.p
    run('WAIVE unconnected F1 "Rezerva pro 2. etapu"')
    assert len(p.waivers) == 1
    w = p.waivers[0]
    assert w.code == "unconnected" and w.target_id == _el(p, "F1").id and w.sheet_id == p.sheets[0].id
    assert w.reason == "Rezerva pro 2. etapu"
    import datetime
    assert w.date == datetime.date.today().isoformat()
    assert isinstance(w.author, str)


def test_waive_by_element_id(run):
    p = run.p
    run(f'WAIVE unconnected {_el(p, "F2").id} "důvod"')
    assert p.waivers[0].target_id == _el(p, "F2").id


def test_waive_author_from_settings(run, monkeypatch):
    monkeypatch.setattr("envocad.settings.current_user", lambda: "Tester")
    run('WAIVE unconnected F1 "důvod"')
    assert run.p.waivers[0].author == "Tester"


def test_waive_sheet_level_with_dash(lib):
    p = Project()
    sh = Sheet(name="Rozv", kind="switchboard", loc="RH")
    p.sheets.append(sh)
    r = CommandRunner(p, lib, journal=Journal())
    assert r.execute("SHEET Rozv").ok
    res = r.execute('WAIVE sb_no_block - "dočasně"')
    assert res.ok, (res.messages, res.error)
    assert p.waivers[0].target_id == "" and p.waivers[0].sheet_id == sh.id


@pytest.mark.parametrize("line", [
    'WAIVE unconnected F1',                  # chybí důvod
    'WAIVE unconnected F1 ""',               # prázdný důvod
    'WAIVE unconnected F1 "   "',            # důvod jen z mezer
    'WAIVE no_such_code F1 "důvod"',         # takový nález nevzniká
    'WAIVE unconnected NENI "důvod"',        # neznámý cíl
    'WAIVE dup_ref F1 "důvod"',              # nález pro F1 nevzniká
    'WAIVE unconnected - "důvod"',           # celolistový cíl, ale nález je na prvku
])
def test_waive_errors(run, line):
    before = json.dumps(run.p.to_dict(), sort_keys=True)
    res = run(line, ok=False)
    assert res.error
    assert json.dumps(run.p.to_dict(), sort_keys=True) == before and run.p.waivers == []


def test_waive_already_waived_is_error(run):
    run('WAIVE unconnected F1 "a"')
    res = run('WAIVE unconnected F1 "b"', ok=False)
    assert res.error and len(run.p.waivers) == 1 and run.p.waivers[0].reason == "a"


def test_unwaive(run):
    run('WAIVE unconnected F1 "a"')
    run("UNWAIVE unconnected F1")
    assert run.p.waivers == []
    assert run("UNWAIVE unconnected F1", ok=False).error     # už neexistuje
    assert run("UNWAIVE unconnected F2", ok=False).error


def test_waive_unwaive_undo_redo(run):
    p = run.p
    run('WAIVE unconnected F1 "a"')
    run('WAIVE unconnected F2 "b"')
    run("UNWAIVE unconnected F1")
    assert [w.reason for w in p.waivers] == ["b"]
    run("UNDO")
    assert sorted(w.reason for w in p.waivers) == ["a", "b"]
    run("UNDO 2")
    assert p.waivers == []
    run("REDO")
    assert [w.reason for w in p.waivers] == ["a"]
    run("REDO 2")
    assert [w.reason for w in p.waivers] == ["b"]


def test_checks_command_lists_waived_section(run):
    res = run("CHECKS")
    n_active = len([d for d in res.data if d["code"] == "unconnected"])
    assert n_active == 3
    assert all({"target_id", "sheet_id", "waived", "reason"} <= set(d) for d in res.data)
    assert not any(d["waived"] for d in res.data)
    assert not any(m.startswith("Potlačeno") for m in res.messages)
    run('WAIVE unconnected F1 "Rezerva etapa 2"')
    res = run("CHECKS")
    waived = [d for d in res.data if d["waived"]]
    assert len(waived) == 1 and waived[0]["code"] == "unconnected" and waived[0]["reason"] == "Rezerva etapa 2"
    assert waived[0]["ref"] == "F1" and waived[0]["target_id"] == _el(run.p, "F1").id
    assert len([d for d in res.data if d["code"] == "unconnected" and not d["waived"]]) == 2
    idx = next(i for i, m in enumerate(res.messages) if m.startswith("Potlačeno (1):"))
    tail = "\n".join(res.messages[idx:])
    assert "Rezerva etapa 2" in tail
    # souhrn počítá jen aktivní nálezy: potlačený `unconnected` F1 není mezi aktivními řádky před sekcí
    assert not any("F1" in m and "unconnected" in m for m in res.messages[:idx])


def test_edits_waive_unwaive_helpers():
    from envocad.cmd import edits
    p = Project()
    w = Waiver("unconnected", "e1", p.sheets[0].id, "x")
    edits.waive(p, w)
    assert p.waivers == [w]
    assert edits.unwaive(p, ("nic", "e1", "s")) is None
    assert edits.unwaive(p, w.key) == w
    assert p.waivers == []
