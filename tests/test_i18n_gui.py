"""Překlady rozhraní (issue #91) v hlavním okně: menu Soubor, volba jazyka, pluginy. Offscreen."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu

from envocad import i18n, settings
from envocad.ui.main_window import MainWindow

FILE_CS = ["&Nový", "Nový projekt z průvodce…", "Nový projekt ze specifikace (JSON)…", "&Otevřít…",
           "Poslední projekty", "&Uložit", "Uložit &jako…", "Archiv projektu…",
           "Otevřít archiv projektu…", "Spustit skript…", "Export &DXF…", "Export &PDF…",
           "Export PDF na A4 (zmenšeno)…", "Vlastnosti projektu…", "Porovnat s revizí (.ecp)…", "Uzavřít revizi",
           "Uzavřít revizi listu", "Konec"]
FILE_EN = ["&New", "New Project from Wizard…", "New Project from Specification (JSON)…", "&Open…",
           "Recent Projects", "&Save", "Save &As…", "Project Archive…",
           "Open Project Archive…", "Run Script…", "Export &DXF…", "Export &PDF…",
           "Export PDF to A4 (scaled down)…", "Project Properties…", "Compare with Revision (.ecp)…",
           "Close Revision", "Close Sheet Revision", "Exit"]


@pytest.fixture(autouse=True)
def _no_plugins(monkeypatch):
    """Pluginy z nainstalované aplikace do menu nic nepřidají (test menu Soubor je přesný výčet)."""
    from envocad import plugins
    monkeypatch.setattr(plugins, "load_plugins", lambda lib: plugins.PluginContext(library=lib))


@pytest.fixture
def made():
    wins = []

    def make():
        w = MainWindow()
        wins.append(w)
        return w
    yield make
    for w in wins:
        w._autosave_timer.stop()


def _top_menu(win, index=0) -> QMenu:
    return win.menuBar().actions()[index].menu()


def _texts(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _menu_titles(win) -> list[str]:
    return [a.text() for a in win.menuBar().actions()]


def test_default_czech_file_menu(made):
    w = made()
    assert _top_menu(w).title() == "&Soubor"
    assert _texts(_top_menu(w)) == FILE_CS
    assert "&Úpravy" in _menu_titles(w)


def test_english_file_menu(made):
    i18n.set_language("en")
    w = made()
    assert _top_menu(w).title() == "&File"
    assert _texts(_top_menu(w)) == FILE_EN
    titles = _menu_titles(w)
    assert "&Úpravy" in titles and "&Soubor" not in titles     # ostatní menu zatím česky


def test_language_menu_actions_default(made):
    w = made()
    assert set(w.language_actions) == set(i18n.LANGUAGES)
    assert {c: a.text() for c, a in w.language_actions.items()} == {"cs": "Čeština", "en": "English"}
    assert all(a.isCheckable() for a in w.language_actions.values())
    assert [c for c, a in w.language_actions.items() if a.isChecked()] == ["cs"]
    sub = [a.menu() for a in w.m_view.actions() if a.menu() and a.text() == "Jazyk rozhraní"]
    assert len(sub) == 1
    assert set(sub[0].actions()) >= set(w.language_actions.values())
    # exkluzivní skupina
    w.language_actions["en"].setChecked(True)
    assert not w.language_actions["cs"].isChecked()


def test_language_menu_english_title_and_checked_from_settings(made):
    s = settings.load_settings()
    s["language"] = "en"
    settings.save_settings(s)
    i18n.set_language("en")
    w = made()
    assert [c for c, a in w.language_actions.items() if a.isChecked()] == ["en"]
    assert any(a.menu() and a.text() == "Interface Language" for a in w.m_view.actions())


def test_set_ui_language_saves_and_announces_restart(made):
    w = made()
    before = _texts(_top_menu(w))
    w.set_ui_language("en")
    assert settings.load_settings()["language"] == "en"
    assert settings.language() == "en"
    assert "po restartu" in w.statusBar().currentMessage()
    QApplication.processEvents()
    assert _texts(_top_menu(w)) == before == FILE_CS            # běžící okno se nepřekládá
    i18n.set_language("en")                                     # restart = nové okno
    w2 = made()
    assert _texts(_top_menu(w2)) == FILE_EN


def test_set_ui_language_triggered_by_action(made):
    w = made()
    w.language_actions["en"].trigger()
    assert settings.language() == "en"


def test_setup_language_applies_saved_language():
    from envocad import app as envo_app
    assert envo_app.setup_language() == "cs" and i18n.language() == "cs"
    s = settings.load_settings()
    s["language"] = "en"
    settings.save_settings(s)
    assert envo_app.setup_language() == "en"
    assert i18n.language() == "en"


def test_install_qt_translations_english_installs_nothing():
    from envocad.app import install_qt_translations
    app = QApplication.instance()
    assert install_qt_translations(app, "en") == []


def test_plugin_menu_action_lands_in_file_menu_in_english(made, monkeypatch):
    from envocad import plugins
    called = []
    ctx = plugins.PluginContext(library=None)
    ctx.add_menu_action("Soubor", "Akce pluginu", lambda w: called.append(w))
    ctx.add_menu_action("Knihovna", "Akce do knihovny", lambda w: None)
    monkeypatch.setattr(plugins, "load_plugins", lambda lib: ctx)
    i18n.set_language("en")
    w = made()
    titles = _menu_titles(w)
    assert "&Soubor" not in titles and "Soubor" not in titles        # žádné nové menu
    assert titles.count("&Knihovna") + titles.count("Knihovna") == 1
    file_menu = _top_menu(w)
    assert file_menu.title() == "&File"
    act = next(a for a in file_menu.actions() if a.text() == "Akce pluginu")
    act.trigger()
    assert called == [w]
    lib = next(a.menu() for a in w.menuBar().actions() if a.text().replace("&", "") == "Knihovna")
    assert "Akce do knihovny" in _texts(lib)


def test_plugin_menu_action_lands_in_file_menu_in_czech(made, monkeypatch):
    from envocad import plugins
    ctx = plugins.PluginContext(library=None)
    ctx.add_menu_action("Soubor", "Akce pluginu", lambda w: None)
    monkeypatch.setattr(plugins, "load_plugins", lambda lib: ctx)
    w = made()
    assert _menu_titles(w).count("&Soubor") == 1
    assert "Akce pluginu" in _texts(_top_menu(w))


def test_all_actions_are_qactions_sanity(made):
    assert all(isinstance(a, QAction) for a in _top_menu(made()).actions())


def test_view_menu_tail_order_unchanged():
    """Nové podmenu jazyka nesmí posunout konec menu Zobrazit: Příkazový řádek, Obnovit rozložení panelů a lišt."""
    from envocad.ui.main_window import MainWindow
    win = MainWindow()
    win._autosave_timer.stop()
    texts = [a.text() for a in win.m_view.actions()]
    assert texts[-2:] == ["Příkazový řádek", "Obnovit rozložení panelů a lišt"]
