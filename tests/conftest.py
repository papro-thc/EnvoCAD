"""Společné nastavení testů."""
import os
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
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        yield None
        return
    from envocad.app import install_qt_translations
    app = QApplication.instance() or QApplication([])
    install_qt_translations(app)
    yield app

