"""LibraryStore jako context manager (issue #124).

Po výstupu z bloku `with` musí být spojení zavřené, aby šel soubor
databáze smazat (jinak na Windows WinError 32). Výjimky se nepotlačují.
"""

import sqlite3

import pytest

from envocad.library.store import LibraryStore


def test_enter_returns_store_and_connection_works(tmp_path):
    with LibraryStore(tmp_path / "lib.db", load_builtin=False) as lib:
        assert isinstance(lib, LibraryStore)
        assert lib.conn.execute("SELECT 1").fetchone()[0] == 1


def test_exit_closes_connection(tmp_path):
    with LibraryStore(tmp_path / "lib.db", load_builtin=False) as lib:
        pass
    with pytest.raises(sqlite3.ProgrammingError):
        lib.conn.execute("SELECT 1")


def test_file_can_be_deleted_after_exit(tmp_path):
    path = tmp_path / "lib.db"
    with LibraryStore(path, load_builtin=False):
        pass
    path.unlink()
    assert not path.exists()


def test_exit_does_not_swallow_exception(tmp_path):
    path = tmp_path / "lib.db"
    holder = {}
    with (
        pytest.raises(ValueError, match="boom"),
        LibraryStore(path, load_builtin=False) as lib,
    ):
        holder["lib"] = lib
        raise ValueError("boom")
    with pytest.raises(sqlite3.ProgrammingError):
        holder["lib"].conn.execute("SELECT 1")
    path.unlink()
    assert not path.exists()
