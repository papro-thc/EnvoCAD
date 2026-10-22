"""Průvodce novým projektem po krocích: navigace (seznam kroků, Zpět / Další), vyznačení kroku s chybou, Souhrn
s chybou generátoru a nálezy F7, zakázané „Vytvořit“ při chybě."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from envocad.ui.dialogs import STEPS, ProjectWizard
from envocad.ui.wizard_topology import FUSE_MIN_IN


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def warned(monkeypatch):
    seen: list[str] = []
    for kind in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda *a, **k: seen.append(a[2]) or QMessageBox.Ok))
    return seen


def _pick(combo, data):
    i = combo.findData(data)
    assert i >= 0
    combo.setCurrentIndex(i)


def _flagged(d) -> list[int]:
    """Indexy kroků označených jako chybné (červený text a tooltip s hláškami)."""
    return [i for i in range(len(STEPS)) if d.steps.item(i).toolTip()]


def test_wizard_has_seven_steps_and_starts_on_first(app):
    d = ProjectWizard()
    assert len(STEPS) == 7 and d.steps.count() == 7 and d.stack.count() == 7
    assert d.steps.item(0).text() == "1. Projekt" and STEPS[-1] == "Souhrn"
    assert d.step() == 0 and d.stack.currentIndex() == 0
    assert not d.btn_back.isEnabled() and d.btn_next.isEnabled()


def test_wizard_navigation_back_next_and_free_jump(app):
    d = ProjectWizard()
    d.btn_next.click()
    assert d.step() == 1 and d.stack.currentIndex() == 1 and d.btn_back.isEnabled()
    d.steps.setCurrentRow(4)                     # volná navigace: skok bez průchodu kroky 3 a 4
    assert d.step() == 4 and d.stack.currentIndex() == 4
    d.btn_back.click()
    assert d.step() == 3
    d.goto(6)
    assert d.step() == 6 and not d.btn_next.isEnabled() and d.btn_back.isEnabled()
    d.goto(99)                                    # mimo rozsah se ignoruje
    assert d.step() == 6
    d.btn_back.click()
    assert d.step() == 5 and d.btn_next.isEnabled()


def test_wizard_default_has_no_flagged_step_and_create_enabled(app):
    d = ProjectWizard()
    assert _flagged(d) == [] and d.btn_ok.isEnabled() and d.btn_ok.text() == "Vytvořit"
    assert d.step_errors() == [[] for _ in STEPS]


@pytest.mark.parametrize("field,value,step", [
    ("inv_p", "", 2), ("mod_voc", "abc", 2), ("t_max", "-30", 2),
    ("strings", "20, 20 abc", 3), ("mod_total", "1.5", 3),
    ("dc_len", "abc", 4), ("ac_main", "", 4), ("grid_cross", "0", 4),
    ("tr_sn", "x", 1),
])
def test_wizard_error_marks_its_step_and_disables_create(app, field, value, step):
    d = ProjectWizard()
    getattr(d, field).setText(value)
    assert d.errors(), field
    flagged = _flagged(d)
    assert step in flagged and 6 in flagged          # krok s polem a Souhrn
    assert all(i in (step, 6) for i in flagged)
    assert d.steps.item(step).toolTip() and d.steps.item(step).foreground().color().name() == "#d32f2f"
    assert not d.steps.item(step).icon().isNull()
    assert not d.btn_ok.isEnabled() and d.btn_ok.toolTip()
    getattr(d, field).setText(ProjectWizard().__dict__[field].text())   # výchozí hodnota pole
    assert d.errors() == [] and _flagged(d) == [] and d.btn_ok.isEnabled()


def test_wizard_existing_boards_error_is_on_its_step(app):
    d = ProjectWizard()
    d.topo.main_in.setText("abc")
    assert d.errors() and 5 in _flagged(d) and 1 not in _flagged(d)
    assert not d.btn_ok.isEnabled()
    d.topo.main_in.setText("")
    assert _flagged(d) == [] and d.btn_ok.isEnabled()
    # pojistkový odpínač do 80 A: chyba je v kroku Stávající rozvaděče, jde opravit i skupinami (dynamická pole)
    _pick(d.topo.fve_device, "fuse_disconnect")
    d.topo.fve_in.setText(str(FUSE_MIN_IN - 17))
    assert 5 in _flagged(d) and not d.btn_ok.isEnabled()
    d.topo.fve_in.setText("100")
    assert _flagged(d) == [] and d.btn_ok.isEnabled()


def test_wizard_group_edit_triggers_state_refresh(app):
    """Pole skupin střídačů vzniká dynamicky (i po změně počtu střídačů); změna v něm přepočítá stav kroků."""
    d = ProjectWizard()
    d.strings.setText("18; 18; 18")                   # počet střídačů se změní → pole skupin se postaví znovu
    assert len(d.topo._group_edits) == 3
    called = []
    d.refresh_state = lambda: called.append(1)
    d.topo._group_edits[2].setText("Hala B")
    assert called


def test_wizard_summary_lists_input_errors_with_links(app):
    d = ProjectWizard()
    d.name.setText("FVE Test")
    d.dc_len.setText("abc")
    d.goto(6)
    txt = d.summary.text()
    assert "FVE Test" in txt and "Chyby zadání" in txt and "step:5" in txt and "Kabely a rozvaděče" in txt
    assert not d.btn_ok.isEnabled()
    d._summary_link("step:5")                         # odkaz v souhrnu skočí na krok s chybou
    assert d.step() == 4


def test_wizard_summary_shows_counts_and_f7_without_errors(app):
    d = ProjectWizard()
    d.goto(6)
    txt = d.summary.text()
    assert "2 střídače" in txt and "6 stringů" in txt and "108 modulů" in txt and "DC / AC" in txt
    assert "stringy → RFVE.DC" in txt.replace("&gt;", ">") or "RFVE.DC" in txt
    assert "Kontrola projektu (F7)" in txt and "Chyba generátoru" not in txt
    assert d.btn_ok.isEnabled() and _flagged(d) == [] and d._gen_errors == []


def test_wizard_summary_shows_generator_error_and_blocks_create(app, warned):
    """Chyba, kterou ohlásí až generátor (pojistka s dopočteným In ≤ 80 A), je v Souhrnu červeně a vytvoření je
    zakázané; po opravě se povolí."""
    d = ProjectWizard()
    d.strings.setText("18")
    _pick(d.topo.fve_device, "fuse_disconnect")
    assert d.errors() == [] and d.generator_errors()
    assert d.btn_ok.isEnabled()                       # generátor se spouští až v Souhrnu (a při Vytvořit)
    d.goto(6)
    txt = d.summary.text()
    assert "Chyba generátoru" in txt and "musí být jistič" in txt and "#d32f2f" in txt
    assert not d.btn_ok.isEnabled() and 6 in _flagged(d)
    d.accept()                                        # i přímé accept() chybu odmítne
    assert d.result() != ProjectWizard.Accepted and "musí být jistič" in warned[-1]
    d.goto(0)
    _pick(d.topo.fve_device, "breaker")               # oprava pole smaže starou chybu generátoru
    assert d._gen_errors is None and d.btn_ok.isEnabled() and _flagged(d) == []
    d.goto(6)
    assert "Chyba generátoru" not in d.summary.text() and d.btn_ok.isEnabled()


def test_wizard_ok_button_accepts_when_valid(app):
    d = ProjectWizard()
    d.show()
    d.goto(6)
    assert d.btn_ok.isEnabled()
    d.btn_ok.click()
    assert d.result() == ProjectWizard.Accepted


def test_wizard_fits_small_screen(app):
    """Okno průvodce se vejde na 1366×768 a každý krok má posuvník jen uvnitř (tlačítka zůstávají vidět)."""
    d = ProjectWizard()
    assert d.width() <= 1366 and d.height() <= 700
    d.show()
    app.processEvents()
    assert d.btn_ok.isVisible() and d.btn_next.isVisible() and d.btn_back.isVisible()
    for i in range(len(STEPS)):
        d.goto(i)
        app.processEvents()
        assert d.btn_ok.geometry().bottom() <= d.height()
