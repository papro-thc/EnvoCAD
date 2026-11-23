"""Verze schématu knihovny (SQLite `PRAGMA user_version`), migrace a ochrana před novější DB (issue #136)."""
from __future__ import annotations

import sqlite3

import pytest

from envocad.library import store
from envocad.library.store import LibraryStore


def _user_version(path) -> int:
    c = sqlite3.connect(str(path))
    try:
        return c.execute("PRAGMA user_version").fetchone()[0]
    finally:
        c.close()


def _tables(path) -> set[str]:
    c = sqlite3.connect(str(path))
    try:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        c.close()


def _make_legacy_db(path) -> None:
    """DB v dnešním stavu: schéma + uživatelská data, `user_version` = 0."""
    c = sqlite3.connect(str(path))
    c.executescript(store.SCHEMA)
    c.execute("INSERT INTO symbols(id,name,category,builtin,data) VALUES('user.sym','Moje','x',0,'{}')")
    c.execute("INSERT INTO components(id,manufacturer,part_number,name,symbol_id) "
              "VALUES('user.art','ACME','P1','Artikl','user.sym')")
    c.commit()
    assert c.execute("PRAGMA user_version").fetchone()[0] == 0
    c.close()


@pytest.fixture
def db(tmp_path):
    return tmp_path / "lib.db"


def test_new_db_gets_current_version(db):
    s = LibraryStore(db, load_builtin=False)
    try:
        assert s.schema_version == store.LIBRARY_SCHEMA_VERSION
    finally:
        s.close()
    assert _user_version(db) == store.LIBRARY_SCHEMA_VERSION


def test_legacy_db_without_version_is_stamped_and_keeps_data(db):
    _make_legacy_db(db)
    s = LibraryStore(db, load_builtin=False)
    try:
        assert s.schema_version == store.LIBRARY_SCHEMA_VERSION
        assert s.has_symbol("user.sym")
        comp = s.get_component("user.art")
        assert comp is not None and comp["manufacturer"] == "ACME"
    finally:
        s.close()
    assert _user_version(db) == store.LIBRARY_SCHEMA_VERSION


def test_newer_db_is_refused_and_untouched(db):
    newer = store.LIBRARY_SCHEMA_VERSION + 1
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE moje (a TEXT)")
    c.execute("INSERT INTO moje VALUES('x')")
    c.execute(f"PRAGMA user_version = {newer}")
    c.commit()
    c.close()

    with pytest.raises(store.LibrarySchemaError) as ei:
        LibraryStore(db, load_builtin=False)
    msg = str(ei.value)
    assert str(newer) in msg
    assert str(store.LIBRARY_SCHEMA_VERSION) in msg
    assert str(db) in msg
    assert isinstance(ei.value, RuntimeError)

    assert _user_version(db) == newer
    assert _tables(db) == {"moje"}
    c = sqlite3.connect(str(db))
    try:
        assert c.execute("SELECT a FROM moje").fetchall() == [("x",)]
    finally:
        c.close()


def test_older_db_is_migrated_in_order(db, monkeypatch):
    calls: list[int] = []

    def step1(conn):
        calls.append(1)
        conn.execute("UPDATE symbols SET name='po1'")

    def step2(conn):
        calls.append(2)

    monkeypatch.setattr(store, "LIBRARY_SCHEMA_VERSION", 3)
    monkeypatch.setitem(store.MIGRATIONS, 1, step1)
    monkeypatch.setitem(store.MIGRATIONS, 2, step2)
    _make_legacy_db(db)

    s = LibraryStore(db, load_builtin=False)
    try:
        assert calls == [1, 2]
        assert s.schema_version == 3
        assert s.has_symbol("user.sym")
        assert s.get_component("user.art") is not None
    finally:
        s.close()
    assert _user_version(db) == 3


def test_migrate_direct_missing_step_only_bumps_version(db, monkeypatch):
    calls: list[int] = []
    monkeypatch.setitem(store.MIGRATIONS, 1, lambda conn: calls.append(1))
    _make_legacy_db(db)
    conn = sqlite3.connect(str(db))
    try:
        store.migrate(conn, 1, 3)  # krok 2 chybí = jen zvýšení čísla
    finally:
        conn.close()
    assert calls == [1]
    assert _user_version(db) == 3


def test_failing_migration_step_rolls_back(db, monkeypatch):
    _make_legacy_db(db)

    def bad(conn):
        conn.execute("INSERT INTO symbols(id,name,category,builtin,data) VALUES('tmp','T','',0,'{}')")
        raise ValueError("selhalo")

    monkeypatch.setitem(store.MIGRATIONS, 1, bad)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(ValueError, match="selhalo"):
            store.migrate(conn, 1, 2)
    finally:
        conn.close()

    assert _user_version(db) == 0
    c = sqlite3.connect(str(db))
    try:
        ids = {r[0] for r in c.execute("SELECT id FROM symbols")}
    finally:
        c.close()
    assert ids == {"user.sym"}


def test_failing_migration_via_store_propagates_and_keeps_db(db, monkeypatch):
    _make_legacy_db(db)

    def bad(conn):
        conn.execute("DELETE FROM symbols")
        raise ValueError("selhalo")

    monkeypatch.setattr(store, "LIBRARY_SCHEMA_VERSION", 2)
    monkeypatch.setitem(store.MIGRATIONS, 1, bad)
    with pytest.raises(ValueError, match="selhalo"):
        LibraryStore(db, load_builtin=False)
    assert _user_version(db) == 0
    c = sqlite3.connect(str(db))
    try:
        assert c.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 1
    finally:
        c.close()


def test_reopen_current_version_is_idempotent(db):
    s = LibraryStore(db, load_builtin=False)
    s.put_component("c1", "M", "PN", "Název", None)
    s.close()
    for _ in range(2):
        s = LibraryStore(db, load_builtin=False)
        try:
            assert s.schema_version == store.LIBRARY_SCHEMA_VERSION
            assert s.get_component("c1") is not None
        finally:
            s.close()
        assert _user_version(db) == store.LIBRARY_SCHEMA_VERSION


def test_builtin_load_stamps_version(db):
    s = LibraryStore(db, load_builtin=True)
    try:
        assert s.schema_version == store.LIBRARY_SCHEMA_VERSION
        assert s.list_symbols()
    finally:
        s.close()
    assert _user_version(db) == store.LIBRARY_SCHEMA_VERSION
