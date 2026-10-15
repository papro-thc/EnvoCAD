"""Generování projektu ze specifikace (bez Qt)."""

from envocad.generate import DEFAULT_SPEC, build_project
from envocad.library.store import LibraryStore
from envocad.model.checks import ERROR, WARNING, check_project
from envocad.model.project import element_symbol


def test_build_project_from_spec(tmp_path):
    spec = {"name": "FVE Test", "meta": {"investor": "Test s.r.o."},
            "module": {"p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9},
            "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000,
                           "i_mppt_max": 30, "strings": [20, 20, 18]},
                          {"ref": "T2", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000,
                           "i_mppt_max": 30, "strings": [20, 20]}],
            "ac": {"breaker_in": 50, "main_in": 125}}
    p = build_project(spec)
    s = p.sheets[0]
    assert len(p.sheets) == 2 and p.sheets[1].is_switchboard
    assert len([e for e in s.elements if e.symbol_id == "fve.pv_string"]) == 5
    assert p.meta["p_installed_kwp"] == "44.1"
    lib = LibraryStore()
    blk = next(e for e in s.elements if e.symbol_id == "fve.switchboard")
    assert [pt.name for pt in element_symbol(p, blk, lib).ports] == ["X1", "X2", "XOUT"]
    # přívody rozvaděče jsou navázané na AC vodiče střídačů, kabely jako objekty
    sb = p.sheets[1]
    feeds = [e for e in sb.elements if e.symbol_id == "sb.feed_in"]
    assert all(f.attrs.get("wire_id") for f in feeds) and len(p.cables) >= 8
    fs = check_project(p, lib)
    assert not [f for f in fs if f.severity in (ERROR, WARNING)], [f.text for f in fs if f.severity != "info"]
    p.save(tmp_path / "g.ecp")
    assert (tmp_path / "g.ecp").stat().st_size > 1000


def test_build_requires_inverters():
    import pytest
    with pytest.raises(ValueError):
        build_project(dict(DEFAULT_SPEC))


def test_tz_and_dso(tmp_path):
    from docx import Document

    from envocad.export.reports import dso_report
    from envocad.export.tz_export import dso_data, export_tz_docx
    spec = {"name": "FVE TZ", "meta": {"investor": "Inv", "place": "Brno"},
            "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "strings": [20, 20]}],
            "grid": {"dso": "EG.D"}}
    p = build_project(spec)
    d = dict(dso_data(p, LibraryStore()))
    assert d["Distributor"] == "EG.D" and d["Instalovaný výkon FV (DC)"].startswith("18 kWp") and "25 kW" in d["Instalovaný výkon střídačů (AC)"]
    assert dso_report(p, LibraryStore())[1]
    out = tmp_path / "tz.docx"
    export_tz_docx(p, LibraryStore(), out)
    doc = Document(str(out))
    text = "\n".join(par.text for par in doc.paragraphs)
    assert "Technická zpráva" in text and "Kontrola stringů" in text and len(doc.tables) >= 6
