"""Průvodce: asistent stringů a „Navrhnout stringy“ s mezí Un DC přístrojů (soustava DC 1000 / 1500 V)."""
import pytest
from test_dc_system import catalog  # noqa: F401 – fixture knihovny generátoru (bez / s artikly 1500 V)


@pytest.fixture(scope="module")
def app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def wizard(app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from envocad.ui.dialogs import ProjectWizard
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    return ProjectWizard


def test_assistant_caps_strings_by_dc_devices(wizard, catalog):  # noqa: F811
    catalog(False)
    d = wizard()
    d.t_min.setText("-20")
    d.inv_udc.setText("1100")
    text = d.assistant_text()
    assert "nejvýš 18 modulů" in text and "Un DC přístrojů 1000 V (EFH 10 DC 2p 1000 V)" in text
    d.strings.setText("20,20")
    assert "Un DC přístrojů 1000 V" in d.assistant_text().split("T1:")[1]
    d.mod_total.setText("40")
    d.propose_strings()
    assert max(int(x) for g in d.strings.text().split(";") for x in g.split(",")) <= 18
    d.dc_tech_box.setChecked(False)               # bez DC rozvaděčů žádné přístroje z artiklů v cestě
    d.dc_route_boxes.setText("0")
    assert "Un DC přístrojů" not in d.assistant_text()


def test_assistant_with_1500_catalog_uses_inverter_limit(wizard, catalog):  # noqa: F811
    catalog(True)
    d = wizard()
    d.t_min.setText("-20")
    d.inv_udc.setText("1100")
    text = d.assistant_text()
    assert "nejvýš 19 modulů" in text and "Un DC přístrojů 1500 V" in text
