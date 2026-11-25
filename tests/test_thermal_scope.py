"""Oteplení mimo rozsah metody IEC TR 60890:2022 – nález F7 `thermal_out_of_scope` a neplatný výsledek (#127)."""
from envocad.export import reports
from envocad.library.store import LibraryStore
from envocad.model import thermal
from envocad.model.checks import WARNING, thermal_findings
from envocad.model.project import Element, Project, Sheet
from envocad.model.thermal import temperature_rise


def _sheet(w=600, h=800, dpt=250, params=None):
    s = Sheet(kind="switchboard", name="RH")
    s.layout.params = {"width_mm": str(w), "height_mm": str(h), "depth_mm": str(dpt), "mounting": "volně stojící",
                       **(params or {})}
    s.elements = [Element(symbol_id="fve.breaker_mcb", attrs={"p_loss_w": "100"})]
    return s


def _project(s):
    p = Project()
    p.sheets = [s]
    return p


def test_in_scope_unchanged():
    r = temperature_rise(_sheet(), rdf=1.0, t_ambient_c=35)
    assert r.valid and r.out_of_scope == []
    assert "vyhovuje" in r.verdict()
    assert not [f for f in thermal_findings(_project(_sheet())) if f.code == "thermal_out_of_scope"]


def test_limits_are_inclusive():
    r = temperature_rise(_sheet(w=1500, h=2000, dpt=300), t_ambient_c=50, partitions=5)
    assert not [x for x in r.out_of_scope if "šířka" in x or "přepážek" in x or "okolí" in x]
    assert temperature_rise(_sheet(), t_ambient_c=10).valid


def test_area_over_limit():
    assert thermal.cooling_area(1400, 2400, 1200, "volně stojící") > thermal.AE_MAX_M2
    r = temperature_rise(_sheet(w=1400, h=2400, dpt=1200))
    assert not r.valid and any("Ae" in x for x in r.out_of_scope)
    assert "mimo rozsah metody IEC TR 60890" in r.verdict() and "vyhovuje" not in r.verdict()


def test_width_over_limit():
    r = temperature_rise(_sheet(w=1600, h=800, dpt=300))
    assert not r.valid and any("šířka" in x for x in r.out_of_scope)


def test_partitions_over_limit():
    r = temperature_rise(_sheet(), partitions=6)
    assert not r.valid and any("přepážek" in x for x in r.out_of_scope)


def test_ambient_out_of_range():
    for t in (9.0, 51.0):
        r = temperature_rise(_sheet(), t_ambient_c=t)
        assert not r.valid and any("okolí" in x for x in r.out_of_scope)


def test_finding_and_report():
    s = _sheet(params={"t_ambient": "55"})
    p = _project(s)
    fs = [f for f in thermal_findings(p) if f.code == "thermal_out_of_scope"]
    assert len(fs) == 1 and fs[0].severity == WARNING and fs[0].sheet_id == s.id
    assert "mimo rozsah metody IEC TR 60890 – doložit jinak" in fs[0].text and "55" in fs[0].text
    assert not [f for f in thermal_findings(p) if f.code == "thermal_device"]
    (row,) = reports._thermal_rows(p, LibraryStore(), s)
    assert "mimo rozsah" in row[4] and "vyhovuje" not in row[4].lower() and "°C" not in row[3]
