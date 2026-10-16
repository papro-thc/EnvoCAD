"""Společné nastavení testů."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    """Každý test má vlastní ENVOCAD_HOME – autosave, nastavení ani knihovna uživatele testy neovlivní
    (jinak by např. autosave kopie z běžné práce zablokovala GUI testy dialogem obnovy)."""
    monkeypatch.setenv("ENVOCAD_HOME", str(tmp_path_factory.mktemp("envohome")))
