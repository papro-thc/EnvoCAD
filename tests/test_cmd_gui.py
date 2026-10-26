"""Příkazový řádek v okně (fáze 2): dok, undo jedním krokem, opakování Enterem, Esc, klik ve výzvě bodu (Mode.PICK),
historie, Tab, psaní ve výkresu (klávesy „zwcad“), akce menu jako příkazy a paleta s aliasy. Offscreen Qt."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDockWidget

from envocad.cmd.registry import norm
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project
from envocad.ui.canvas import Mode
from envocad.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app):
    made = []

    def make(project=None):
        if project is None:
            project = Project(name="Řádek")
            project.sheets[0].elements += [Element("fve.breaker_mcb", 60, 150, attrs={"ref": "F1"}),
                                           Element("fve.breaker_mcb", 140, 150, attrs={"ref": "F2"})]
        w = MainWindow(LibraryStore(), project)
        w.resize(1400, 900)
        w.show()
        app.processEvents()
        w.view.zoom_fit()
        app.processEvents()
        made.append(w)
        return w

    yield make
    for w in made:
        w.undo.setClean()
        w.close()


def _el(w, ref):
    return next(e for e in w.project.sheets[0].elements if e.ref == ref)


def _type(w, text):
    w.cmdline.input.setText(text)
    QTest.keyClick(w.cmdline.input, Qt.Key_Return)


def _out(w) -> str:
    return w.cmdline.output.toPlainText()


def test_dock_exists_with_object_name(win):
    w = win()
    dock = w.findChild(QDockWidget, "Příkazový řádek")
    assert dock is not None and dock.widget() is w.cmdline and dock.isVisible()


def test_rotate_is_one_undo_step_and_enter_repeats(win):
    w = win()
    n0 = w.undo.count()
    _type(w, "RO F1 90")
    assert _el(w, "F1").rotation == 90 and w.undo.count() == n0 + 1 and w.undo.undoText() == "Otočit"
    assert w.scene.element_items[_el(w, "F1").id].isSelected()       # výběr z příkazu přenesený do scény
    w.undo.undo()
    assert _el(w, "F1").rotation == 0
    w.scene.element_items[_el(w, "F1").id].setSelected(True)          # undo přestaví scénu – vybrat znovu
    QTest.keyClick(w.cmdline.input, Qt.Key_Return)                     # prázdný Enter = znovu RO (na výběr F1)
    assert w.cmdline.prompt.text().startswith("Základní bod")
    _type(w, "")                                                       # výzva bodu: Enter = počátek prvku
    _type(w, "")                                                       # úhel: Enter = 90
    assert _el(w, "F1").rotation == 90 and w.cmdline.session is None


def test_undo_redo_from_line_use_window_stack(win):
    w = win()
    _type(w, "RO F1 90")
    _type(w, "RO F2 180")
    _type(w, "UNDO 2")
    assert _el(w, "F1").rotation == 0 and _el(w, "F2").rotation == 0
    _type(w, "REDO")
    assert _el(w, "F1").rotation == 90 and "Znovu: 1" in _out(w)


def test_pick_point_by_click_and_esc_cancels(win):
    w = win()
    sc, port = w.scene, w.view.viewport()
    _type(w, "MOVE F1")
    assert w.cmdline.session is not None and sc.mode == Mode.PICK and w.cmdline.prompt.text() == "Základní bod:"
    QTest.mouseClick(port, Qt.LeftButton, Qt.NoModifier, w.view.mapFromScene(QPointF(60, -150)))
    assert w.cmdline.prompt.text() == "Cílový bod:" and sc._pick_base == (60.0, 150.0)
    _type(w, "@10,0")
    assert (_el(w, "F1").x, _el(w, "F1").y) == (70.0, 150.0) and sc.mode == Mode.SELECT
    _type(w, "MOVE F2")
    QTest.keyClick(port, Qt.Key_Escape)                                # Esc ve výkresu = zrušit příkaz
    assert w.cmdline.session is None and sc.mode == Mode.SELECT and "zrušen" in _out(w)
    assert _el(w, "F2").x == 140.0


def test_error_message_and_unknown_command(win):
    w = win()
    _type(w, "XYZ")
    assert "Neznámý příkaz „XYZ“" in _out(w)
    _type(w, "RO NENI")
    assert "není" in _out(w).splitlines()[-1] and w.undo.count() == 0


def test_canvas_typing_goes_to_command_line(win):
    w = win()
    port = w.view.viewport()
    w.scene.element_items[_el(w, "F1").id].setSelected(True)
    for k in (Qt.Key_M, Qt.Key_I):                                     # MI = zrcadlit, ne klávesa M scény
        QTest.keyClick(port, k)
    assert w.cmdline.input.text() == "mi" and not _el(w, "F1").mirror
    QTest.keyClick(port, Qt.Key_Space)                                 # mezera = Enter
    assert _el(w, "F1").mirror and w.undo.count() == 1
    assert w.actions["rotate"].shortcut().isEmpty()                    # jednopísmenné zkratky vypnuté


def test_envocad_keys_keep_letter_shortcuts(win, monkeypatch):
    import envocad.settings as st
    monkeypatch.setattr(st, "cmdline_keys", lambda: "envocad")
    w = win()
    assert w.actions["rotate"].shortcut().toString() == "R"
    QTest.keyClick(w.view.viewport(), Qt.Key_W)
    assert w.scene.mode == Mode.WIRE and w.cmdline.input.text() == ""


def test_history_and_tab_completion(win):
    w = win()
    _type(w, "RO F1 90")
    _type(w, "MI F2")
    inp = w.cmdline.input
    QTest.keyClick(inp, Qt.Key_Up)
    assert inp.text() == "MI F2"
    QTest.keyClick(inp, Qt.Key_Up)
    assert inp.text() == "RO F1 90"
    assert w.cmdline._history_path().read_text(encoding="utf-8").splitlines()[-2:] == ["RO F1 90", "MI F2"]
    inp.clear()
    inp.setText("ROTA")
    QTest.keyClick(inp, Qt.Key_Tab)
    assert inp.text() == "ROTATE "                     # Tab doplnil (nepřeskočil na další widget)


def test_suggestions_while_typing_like_zwcad(win):
    w = win()
    inp, sp = w.cmdline.input, w.cmdline._suggest
    inp.setFocus()
    QTest.keyClicks(inp, "ro")
    assert sp.isVisible()
    words = [sp.item(i).data(Qt.UserRole) for i in range(sp.count())]
    assert words[0] == "RO"                                            # přesná shoda aliasu první
    assert "ROTATE" in sp.item(0).text() and "Otočit" in sp.item(0).text()   # alias, jméno a český název
    assert sp.geometry().bottom() <= inp.mapTo(w, inp.rect().topLeft()).y()   # nad řádkem
    QTest.keyClick(inp, Qt.Key_Escape)
    assert not sp.isVisible() and inp.text() == "ro"                   # Esc jen zavře našeptávač
    inp.clear()
    QTest.keyClicks(inp, "otoc")                                       # bez diakritiky, i alias
    assert sp.isVisible() and sp.first_word() == "OTOCIT"
    inp.clear()
    QTest.keyClicks(inp, "zrcad")
    QTest.keyClick(inp, Qt.Key_Down)                                   # šipka vybírá v návrzích, ne historii
    assert sp.current_word() == sp.first_word()
    QTest.keyClick(inp, Qt.Key_Tab)
    assert inp.text() == sp.first_word() + " " and not sp.isVisible()  # Tab doplní vybraný
    inp.clear()
    QTest.keyClicks(inp, "qqq")
    assert not sp.isVisible()                                          # nic neodpovídá
    inp.clear()
    QTest.keyClicks(inp, "RO F1")
    assert not sp.isVisible()                                          # argumenty: našeptávač jen u příkazu


def test_suggestion_enter_runs_command_and_history_stays_quiet(win):
    w = win()
    inp, sp = w.cmdline.input, w.cmdline._suggest
    inp.setFocus()
    QTest.keyClicks(inp, "rotat")                                      # nedopsané slovo → Enter spustí první návrh
    QTest.keyClick(inp, Qt.Key_Return)
    assert w.cmdline.session is not None and "ROTATE" in _out(w)
    assert not sp.isVisible()
    QTest.keyClicks(inp, "ro")                                         # ve výzvě příkazu se nenašeptává
    assert not sp.isVisible()
    QTest.keyClick(inp, Qt.Key_Escape)
    assert w.cmdline.session is None
    inp.clear()
    QTest.keyClick(inp, Qt.Key_Up)                                     # historie nenašeptává
    assert inp.text() and not sp.isVisible()


def test_every_action_id_is_a_command_and_palette_shows_aliases(win):
    w = win()
    assert [k for k in w.actions if norm(k) not in w.cmd_registry.commands] == []
    w.command_palette()
    labels = [label for label, _a in w._palette.entries]
    assert any("Otočit o 90°" in x and "ROTATE" in x and "RO" in x for x in labels)
    w._palette.close()


def test_gui_only_command_triggers_action(win):
    w = win()
    _type(w, "F7")                                                     # CHECKS bez argumentů = panel Kontrola
    assert w.checks_dock.isVisible()
    fired = []
    w.actions["copy_clipboard"].triggered.connect(lambda *_: fired.append(1))
    _type(w, "copy_clipboard")                                         # akce menu jako příkaz
    assert fired == [1]


# ---- nálezy review fáze 2 ----------------------------------------------------------------------------------------
def test_open_other_project_cancels_pending_command(win):
    w = win()
    old = w.project
    _type(w, "MOVE F1")
    assert w.cmdline.session is not None
    other = Project(name="Jiný")
    w._load_project(other)
    assert w.cmdline.session is None and w.cmdline.runner is None and w.undo.count() == 0
    _type(w, "60,150")                                                 # už to není hodnota výzvy, ale příkaz
    assert _el_in(old, "F1").x == 60 and w.project is other and w.undo.count() == 0


def _el_in(p, ref):
    return next(e for e in p.sheets[0].elements if e.ref == ref)


def test_selection_outside_drawing_scene_is_empty(win):
    w = win()
    w.scene.element_items[_el(w, "F1").id].setSelected(True)
    w.cmdline._sync_selection()
    w.open_sheet(w.project.sheets[0], "layout")                        # pohled bez kreslicí scény
    assert w.draw_scene is None
    _type(w, "DELETE")                                                 # starý výběr z JPS neplatí – výzva výběru
    assert w.cmdline.session is not None and w.cmdline.input.prompt_kind == "selection"
    w.cmdline.cancel()
    assert _el(w, "F1").id in {e.id for e in w.project.sheets[0].elements}


def test_place_ghost_keeps_r_and_m(win):
    w = win()
    w.scene.ask_attributes = False
    w.scene.start_place("fve.breaker_mcb")
    QTest.keyClick(w.view.viewport(), Qt.Key_R)
    assert w.scene._ghost.element.rotation == 90 and w.cmdline.input.text() == ""


def test_click_in_pick_keeps_selection_and_esc_cancels_selection_prompt(win, app):
    w = win()
    port = w.view.viewport()
    w.scene.element_items[_el(w, "F1").id].setSelected(True)
    _type(w, "MOVE")
    QTest.mouseClick(port, Qt.LeftButton, Qt.NoModifier, w.view.mapFromScene(QPointF(60, -150)))
    QTest.mouseClick(port, Qt.LeftButton, Qt.NoModifier, w.view.mapFromScene(QPointF(70, -150)))
    app.processEvents()
    assert _el(w, "F1").x == 70 and w.scene.element_items[_el(w, "F1").id].isSelected()
    w.scene.clearSelection()
    _type(w, "E")                                                      # výzva výběru (nic vybrané)
    assert w.cmdline.session is not None and w.cmdline.input.prompt_kind == "selection"
    QTest.keyClick(port, Qt.Key_Escape)
    assert w.cmdline.session is None


def test_hidden_dock_reappears_when_typing_and_menu_toggle(win):
    w = win()
    w.cmdline_dock.hide()
    assert w.cmdline_dock.toggleViewAction() in w.m_view.actions()
    QTest.keyClick(w.view.viewport(), Qt.Key_M)
    assert w.cmdline_dock.isVisible() and w.cmdline.input.text() == "m"


def test_altgr_at_sign_goes_to_command_line(win):
    w = win()
    QTest.keyClick(w.view.viewport(), "@", Qt.ControlModifier | Qt.AltModifier)
    assert w.cmdline.input.text() == "@"


def test_failed_command_after_change_rebuilds_views(win):
    w = win()
    seen = []
    w.sheets_changed = lambda ids: seen.append(ids)
    w.cmdline._runner()
    w.cmdline._identity = {}                                           # simulace: listy obnovené ze snímku po chybě
    from envocad.cmd.runner import Result
    w.cmdline._finish(Result(False, "x", ["chyba"], None, "chyba"))
    assert seen and seen[0] == [w.project.sheets[0].id]
