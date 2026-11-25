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


# ---- review: souběh, atomicita, ochrana transakce volajícího --------------------------------------------------------

def _add_column_step(conn):
    conn.execute("ALTER TABLE symbols ADD COLUMN x TEXT")      # neidempotentní krok


def test_second_migrate_after_first_does_not_rerun_step(db, monkeypatch):
    calls: list[int] = []

    def step(conn):
        calls.append(1)
        _add_column_step(conn)

    monkeypatch.setitem(store.MIGRATIONS, 1, step)
    _make_legacy_db(db)
    c1, c2 = sqlite3.connect(str(db)), sqlite3.connect(str(db))
    try:
        store.migrate(c1, 1, 2)
        store.migrate(c2, 1, 2)           # druhý proces četl starou verzi před zámkem – po zámku vidí 2
    finally:
        c1.close()
        c2.close()
    assert calls == [1]
    assert _user_version(db) == 2


def test_second_store_after_first_does_not_rerun_step(db, monkeypatch):
    calls: list[int] = []

    def step(conn):
        calls.append(1)
        _add_column_step(conn)

    monkeypatch.setattr(store, "LIBRARY_SCHEMA_VERSION", 2)
    monkeypatch.setitem(store.MIGRATIONS, 1, step)
    _make_legacy_db(db)
    for _ in range(2):
        s = LibraryStore(db, load_builtin=False)
        s.close()
    assert calls == [1]
    assert _user_version(db) == 2


def test_stale_version_read_before_lock_is_rechecked(db, monkeypatch):
    """Druhý otevírač přečetl 0, než první převedl; `_upgrade` po zámku vidí 2 a krok nespustí."""
    calls: list[int] = []
    monkeypatch.setattr(store, "LIBRARY_SCHEMA_VERSION", 2)
    monkeypatch.setitem(store.MIGRATIONS, 1, lambda conn: (calls.append(1), _add_column_step(conn)))
    _make_legacy_db(db)
    other = sqlite3.connect(str(db))
    try:
        store.migrate(other, 1)           # první proces
    finally:
        other.close()
    conn = sqlite3.connect(str(db))
    try:
        store._upgrade(conn, 1, 2, db, create_empty=True)   # starý údaj `found == 0` už neplatí
    finally:
        conn.close()
    assert calls == [1]


def test_migrate_refuses_open_transaction(db):
    _make_legacy_db(db)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("INSERT INTO symbols(id,name,category,builtin,data) VALUES('t','T','',0,'{}')")
        assert conn.in_transaction
        with pytest.raises(RuntimeError):
            store.migrate(conn, 1, 2)
        assert conn.in_transaction            # transakce volajícího zůstala otevřená a necommitnutá
        conn.rollback()
    finally:
        conn.close()
    assert _user_version(db) == 0
    c = sqlite3.connect(str(db))
    try:
        assert c.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 1
    finally:
        c.close()


def test_migrate_refuses_downgrade(db):
    _make_legacy_db(db)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA user_version = 3")
        with pytest.raises(ValueError):
            store.migrate(conn, 3, 2)
    finally:
        conn.close()
    assert _user_version(db) == 3


def test_isolation_level_restored_after_failed_step(db, monkeypatch):
    def bad(conn):
        raise ValueError("selhalo")

    monkeypatch.setitem(store.MIGRATIONS, 1, bad)
    _make_legacy_db(db)
    conn = sqlite3.connect(str(db))
    try:
        before = conn.isolation_level
        with pytest.raises(ValueError):
            store.migrate(conn, 1, 2)
        assert conn.isolation_level == before
        assert not conn.in_transaction
    finally:
        conn.close()


def test_new_db_has_all_tables_and_version_together(db):
    s = LibraryStore(db, load_builtin=False)
    s.close()
    assert {"symbols", "components", "builtin_files"} <= _tables(db)
    assert _user_version(db) == store.LIBRARY_SCHEMA_VERSION


def test_migration_step_write_is_persisted(db, monkeypatch):
    monkeypatch.setattr(store, "LIBRARY_SCHEMA_VERSION", 2)
    monkeypatch.setitem(store.MIGRATIONS, 1, lambda conn: conn.execute("UPDATE symbols SET name='po1'"))
    _make_legacy_db(db)
    LibraryStore(db, load_builtin=False).close()
    c = sqlite3.connect(str(db))
    try:
        assert c.execute("SELECT name FROM symbols WHERE id='user.sym'").fetchone()[0] == "po1"
    finally:
        c.close()


def test_store_closes_connection_when_sync_builtin_fails(db, monkeypatch):
    closed: list[bool] = []
    real_connect = sqlite3.connect

    class Spy:
        def __init__(self, c):
            self._c = c

        def __getattr__(self, name):
            return getattr(self._c, name)

        def __setattr__(self, name, value):
            if name == "_c":
                object.__setattr__(self, name, value)
            else:
                setattr(self._c, name, value)

        def close(self):
            closed.append(True)
            self._c.close()

    monkeypatch.setattr(store.sqlite3, "connect", lambda *a, **k: Spy(real_connect(*a, **k)))
    monkeypatch.setattr(LibraryStore, "sync_builtin", lambda self: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError, match="boom"):
        LibraryStore(db)
    assert closed == [True]


def test_cli_refuses_newer_library(tmp_path, monkeypatch, capsys):
    from envocad.cmd.__main__ import main
    from envocad.model.project import Project

    home = tmp_path / "home"
    home.mkdir()
    c = sqlite3.connect(str(home / "library.db"))
    c.execute(f"PRAGMA user_version = {store.LIBRARY_SCHEMA_VERSION + 1}")
    c.close()
    monkeypatch.setenv("ENVOCAD_HOME", str(home))
    proj = tmp_path / "p.ecp"
    Project(name="X").save(proj)
    script = tmp_path / "s.ecs"
    script.write_text("# nic\n", encoding="utf-8")
    assert main([str(proj), str(script)]) == 1
    assert "Knihovnu nelze otevřít" in capsys.readouterr().err
