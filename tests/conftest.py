"""Společné nastavení testů."""
import os
import sys
from pathlib import Path

import pytest

# skutečné nastavení uživatele (QSettings("ENVO", "EnvoCAD") na Linuxu) – testy na něj nesmí sáhnout
USER_QSETTINGS = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "ENVO" / "EnvoCAD.conf"


def _snapshot(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


@pytest.fixture(autouse=True, scope="session")
def _user_qsettings_untouched():
    """Pojistka k `_isolated_qsettings`: po běhu testů musí být `~/.config/ENVO/EnvoCAD.conf` beze změny."""
    before = _snapshot(USER_QSETTINGS)
    yield
    assert _snapshot(USER_QSETTINGS) == before, f"testy změnily nastavení uživatele {USER_QSETTINGS}"


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    """Každý test má vlastní ENVOCAD_HOME – autosave, nastavení ani knihovna uživatele testy neovlivní
    (jinak by např. autosave kopie z běžné práce zablokovala GUI testy dialogem obnovy)."""
    monkeypatch.setenv("ENVOCAD_HOME", str(tmp_path_factory.mktemp("envohome")))
    # cache topologií (klíč podle mtime souborů) – test, který v rychlém sledu přepíše soubor stejné délky, nesmí
    # dostat výsledek z předchozího testu
    from envocad.library import topologies
    topologies.clear_cache()
    # lokální normové tabulky (#82): cache podle ENVOCAD_HOME, další test nesmí dostat tabulky z jiného domova
    from envocad.model import norm_tables
    norm_tables.clear_cache()


@pytest.fixture(autouse=True)
def _reset_ui_language():
    """Jazyk rozhraní je globální stav procesu – test, který přepne na angličtinu, nesmí ovlivnit zbytek sady."""
    yield
    try:
        from envocad import i18n
        i18n.set_language("cs")
    except (ImportError, AttributeError):    # modul i18n ještě neexistuje
        pass


@pytest.fixture(autouse=True)
def _stop_leftover_autosave():
    """Po testu zastaví autosave časovač (120 s) oken `MainWindow`, která test nezavřel. Jinak na pomalém stroji
    (CI) okno z dřívějšího testu zapíše kopii do `ENVOCAD_HOME` pozdějšího testu, nové okno ji nabídne modálním
    dialogem obnovy a sada se zasekne. Okna se nezavírají – zavření okna se změnami by se ptalo na uložení."""
    yield
    import sys
    mw = sys.modules.get("envocad.ui.main_window")
    if mw is None:               # test GUI nepoužil
        return
    from PySide6.QtWidgets import QApplication
    for w in QApplication.topLevelWidgets():
        if isinstance(w, mw.MainWindow):
            w._autosave_timer.stop()


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path_factory, monkeypatch):
    """Každý test má vlastní úložiště QSettings – `QSettings("ENVO", "EnvoCAD")` (poslední projekty, zobrazení
    a export připomínek, tmavý motiv) nepíše do `~/.config/ENVO/EnvoCAD.conf` uživatele a testy se navzájem
    neovlivňují. `QSettings(org, app)` používá NativeFormat (na Linuxu = IniFormat), proto se přesměrují obě;
    `XDG_CONFIG_HOME` pokryje případné podprocesy."""
    cfg = tmp_path_factory.mktemp("qsettings")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    try:
        from PySide6.QtCore import QSettings
    except ImportError:          # headless prostředí bez PySide6 – modelové testy Qt nepotřebují
        yield cfg
        return
    for fmt in (QSettings.NativeFormat, QSettings.IniFormat):
        for scope in (QSettings.UserScope, QSettings.SystemScope):
            QSettings.setPath(fmt, scope, str(cfg))
    yield cfg


@pytest.fixture(autouse=True, scope="session")
def _qt_czech():
    """Jedna QApplication pro celou sadu (offscreen) s českými překlady Qt jako v `envocad.app.main` – testy GUI
    vidí stejná tlačítka (Ano/Ne/Storno) jako uživatel. Bez PySide6 (headless modelové testy) se přeskočí."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if sys.platform == "win32" and os.environ["QT_QPA_PLATFORM"] == "offscreen":
        # offscreen na Windows hledá písma (FreeType) ve složce Qt, kterou kola PySide6 nemají → text se do PDF
        # vůbec nevykreslí; systémová písma (Arial) jako v běžném okně
        os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        yield None
        return
    from envocad.app import install_qt_translations
    app = QApplication.instance() or QApplication([])
    install_qt_translations(app)
    yield app



@pytest.fixture(scope="module")
def ac_builtin():
    """AC listy (RFVE.AC, AC část RFVE, stávající RD / HR / RE) vestavěným kódem, když mustr chybí – jako před
    rozhodnutím 12 (docs/NAVRH_TOPOLOGIE.md, kap. 8), tj. firemní standard `ac_builtin` = true. Testy obsahu AC listů
    se na tuto volbu přepnou (`pytestmark = pytest.mark.usefixtures("ac_builtin")`); výchozí chování (jen bloky)
    testuje `test_generator_scope.py`. Rozsah modulu – platí i pro projekty z fixtures modulu (`usefixtures` se
    vytvoří před nimi); standard v `settings.json` testuje `test_generator_scope.py`."""
    from envocad.generator import spec
    mp = pytest.MonkeyPatch()
    mp.setattr(spec, "ac_builtin_default", lambda: True)
    yield
    mp.undo()


@pytest.fixture
def ac_builtin_fn(monkeypatch):
    """Jako `ac_builtin`, ale jen pro jeden test – v modulech, kde ostatní testy jedou ve výchozím rozsahu (modulový
    fixture by po prvním použití zůstal zapnutý pro zbytek modulu)."""
    from envocad.generator import spec
    monkeypatch.setattr(spec, "ac_builtin_default", lambda: True)
