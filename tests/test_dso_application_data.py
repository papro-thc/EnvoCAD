"""Údaje žádosti o připojení k distributorovi v `Project.meta` (issue #131): výkaz „Data pro DS“ a dialog vlastností."""
from __future__ import annotations

import pytest

from envocad.export.reports import dso_report
from envocad.export.tz_data import dso_data
from envocad.generator.build import build_project
from envocad.library.store import LibraryStore
from envocad.model.project import DSO_META_FIELDS, Project

SPEC = {"name": "FVE DS", "inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200,
                                         "u_mppt_max": 1000, "strings": [20, 20]}], "grid": {"dso": "EG.D"}}
KEYS = ["ean_consumption", "ean_supply", "metering_point_no", "cadastral_area", "parcels", "island_capable",
        "p_installed_total_kw", "p_reserved_kw"]


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_field_keys_and_labels():
    assert [k for k, _ in DSO_META_FIELDS] == KEYS
    assert dict(DSO_META_FIELDS)["ean_supply"] == "EAN odběrného místa – dodávka"


def test_empty_fields_are_neuvedeno():
    p = build_project(SPEC)
    rows = dict(dso_data(p, LibraryStore()))
    for _, label in DSO_META_FIELDS:
        assert rows[label] == "neuvedeno"
    assert len(dso_report(p, LibraryStore())[1]) == 13 + len(DSO_META_FIELDS)


def test_filled_fields_in_report():
    p = build_project(SPEC)
    p.meta.update({"ean_consumption": "859182400000000001", "ean_supply": "859182400000000002",
                   "metering_point_no": "123", "cadastral_area": "Brno", "parcels": "12/3, 14",
                   "island_capable": "ano", "p_installed_total_kw": "30", "p_reserved_kw": "20"})
    rows = dict(dso_report(p, LibraryStore())[1])
    assert rows["EAN odběrného místa – spotřeba"] == "859182400000000001"
    assert rows["Číslo odběrného místa"] == "123"
    assert rows["Parcelní čísla"] == "12/3, 14"
    assert rows["Schopnost ostrovního provozu"] == "ano"
    assert rows["Požadovaný rezervovaný výkon"] == "20 kW"
    assert rows["Celkový instalovaný výkon (zadaný)"] == "30 kW"


def test_no_plant_no_rows():
    assert dso_report(Project(name="x"), LibraryStore())[1] == []


def test_dialog_edits_and_undo(app, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from envocad.ui.dialogs import ProjectMetaDialog
    from envocad.ui.main_window import MainWindow
    p = build_project(SPEC)
    d = ProjectMetaDialog(p)
    assert d.island.currentData() == ""
    assert all(k in d.edits for k in KEYS if k != "island_capable")
    d.edits["parcels"].setText("12/3")
    d.island.setCurrentIndex(d.island.findData("ano"))
    meta = d.values()[1]
    assert meta["parcels"] == "12/3" and meta["island_capable"] == "ano" and "ean_supply" not in meta
    w = MainWindow(library=LibraryStore(), project=p)

    def ok(dlg):
        dlg.edits["ean_supply"].setText("859")
        dlg.island.setCurrentIndex(dlg.island.findData("ne"))
        return QDialog.Accepted
    monkeypatch.setattr(ProjectMetaDialog, "exec", ok)
    w.edit_project_meta()
    assert p.meta["ean_supply"] == "859" and p.meta["island_capable"] == "ne" and w.undo.count() == 1
    w.undo.undo()
    assert "ean_supply" not in p.meta and "island_capable" not in p.meta
    w.undo.setClean()
    w.close()


def test_meta_roundtrip_no_format_change():
    p = build_project(SPEC)
    p.meta["ean_supply"] = "1"
    assert Project.from_dict(p.to_dict()).meta["ean_supply"] == "1"
