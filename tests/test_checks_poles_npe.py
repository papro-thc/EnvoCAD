"""F7: přístroj s menším počtem pólů, než kolik fází do něj vede (chránič 1+N na L1 L2 L3 N), a spojení N s PE
v uzlu (síť TN-S) – na uživatelském projektu RFVE; generované projekty tyto nálezy nemají (test_generate F7)."""
from pathlib import Path

from envocad.model.checks import n_pe_join_findings, pole_count_findings
from envocad.model.project import Element, Project, Sheet, Wire, WireEnd

DATA = Path(__file__).parent / "data" / "vicepol_rfve_rucne.ecp"


def test_user_project_findings():
    p = Project.load(DATA)
    sb = next(s for s in p.sheets if s.is_switchboard)
    assert {f.ref for f in pole_count_findings(sb)} == {"F1", "F2.CCA"}     # 3p jističe s N kolem nehlásí
    assert len(n_pe_join_findings(sb)) == 1


def test_rules_on_small_sheet():
    s = Sheet(name="R", kind="switchboard")
    q = Element("fve.breaker_mcb", 0, 0, attrs={"ref": "Q1", "poles": "3"})
    f = Element("sb.rcbo", 0, 0, attrs={"ref": "F1", "poles": "4"})
    j = Element("sb.junction", 0, 0)
    a = Element("sb.junction", 0, 0)
    s.elements += [q, f, j, a]
    s.wires += [Wire(WireEnd(j.id, "S"), WireEnd(q.id, "1"), conductors=["L1", "L2", "L3", "N", "PE"]),
                Wire(WireEnd(j.id, "E"), WireEnd(f.id, "1"), conductors=["L1", "L2", "L3", "N"])]
    assert pole_count_findings(s) == []                                       # 3p + N kolem, chránič 3+N
    f.attrs["poles"] = "2"
    assert [x.ref for x in pole_count_findings(s)] == ["F1"]
    s.wires += [Wire(WireEnd(a.id, "N"), WireEnd(q.id, "2"), conductors=["N"]),
                Wire(WireEnd(a.id, "S"), WireEnd(f.id, "2"), conductors=["PE"])]
    assert len(n_pe_join_findings(s)) == 1
    s.wires[-1].conductors = ["PEN"]
    assert n_pe_join_findings(s) == []
