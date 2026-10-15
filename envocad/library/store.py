"""SQLite úložiště knihovny: symboly + komponenty (artikly). Bez Qt."""
from __future__ import annotations

import csv
import json
import os
import sqlite3
from pathlib import Path

from envocad.model.symbol import Symbol

BUILTIN_DIR = Path(__file__).parent / "builtin"

SCHEMA = """
CREATE TABLE IF NOT EXISTS symbols (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    builtin INTEGER NOT NULL DEFAULT 0,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS components (
    id TEXT PRIMARY KEY,
    manufacturer TEXT NOT NULL DEFAULT '',
    part_number TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    symbol_id TEXT,
    params TEXT NOT NULL DEFAULT '{}',
    price REAL,
    url TEXT
);
CREATE INDEX IF NOT EXISTS ix_symbols_cat ON symbols(category);
CREATE TABLE IF NOT EXISTS builtin_files (path TEXT PRIMARY KEY, mtime REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_components_symbol ON components(symbol_id);
"""


def home_dir() -> Path:
    base = Path(os.environ.get("ENVOCAD_HOME") or os.path.join(os.path.expanduser("~"), ".envocad"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def user_library_dir() -> Path:
    """Uživatelské/firemní balíčky knihovny: libovolná podsložka se symboly (*.json) a artikly (*.csv)."""
    d = home_dir() / "library"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_db_path() -> Path:
    return home_dir() / "library.db"


class LibraryStore:
    def __init__(self, path: Path | str | None = None, load_builtin: bool = True):
        self.path = Path(path) if path else default_db_path()
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._cache: dict[str, Symbol] = {}
        if load_builtin:
            self.sync_builtin()

    # ---- symboly ---------------------------------------------------------
    def sync_builtin(self) -> int:
        """Nahraje/aktualizuje vestavěné symboly (JSON) a artikly (CSV). Vrátí počet symbolů."""
        n = 0
        seen = {r["path"]: r["mtime"] for r in self.conn.execute("SELECT path, mtime FROM builtin_files")}
        rows = []
        sources = [(BUILTIN_DIR, "builtin")]
        if self.path == default_db_path():
            sources.append((user_library_dir(), "user"))
        for root, tag in sources:
            self._sync_symbols(root, tag, seen, rows)
            self._sync_components(root)
        n = len(rows)
        if rows:
            self.conn.executemany(
                "INSERT INTO symbols(id,name,category,builtin,data) VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, category=excluded.category, "
                "builtin=excluded.builtin, data=excluded.data", rows)
            self.conn.commit()
        return n

    def _sync_symbols(self, root: Path, tag: str, seen: dict, rows: list) -> None:
        for f in sorted(root.rglob("*.json")):
            key = f"{tag}:{f.relative_to(root)}"
            mtime = f.stat().st_mtime
            if seen.get(key) == mtime:
                continue  # beze změny – přeskočit (start s ~700 symboly by jinak trval sekundy)
            try:
                sym = Symbol.from_json(f)
            except Exception as ex:  # noqa: BLE001 – vadný uživatelský soubor nesmí shodit start
                print(f"[knihovna] {f}: {ex}")
                continue
            rows.append((sym.id, sym.name, sym.category, 1 if tag == "builtin" else 0,
                         json.dumps(sym.to_dict(), ensure_ascii=False)))
            self.conn.execute("INSERT OR REPLACE INTO builtin_files(path, mtime) VALUES(?, ?)", (key, mtime))

    def _sync_components(self, root: Path) -> None:
        csvs = sorted(root.rglob("*.csv"))
        if csvs:
            from envocad.library.components import read_csv
            for f in csvs:
                try:
                    comps = read_csv(f)
                except Exception as ex:  # noqa: BLE001 – vadný soubor nesmí shodit start
                    print(f"[knihovna] {f.name}: {ex}")
                    continue
                self.conn.executemany(
                    "INSERT INTO components(id,manufacturer,part_number,name,symbol_id,params,price,url) "
                    "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET manufacturer=excluded.manufacturer,"
                    "part_number=excluded.part_number,name=excluded.name,symbol_id=excluded.symbol_id,"
                    "params=excluded.params,price=excluded.price,url=excluded.url",
                    [(c.id, c.manufacturer, c.part_number, c.name, c.symbol_id or None,
                      json.dumps(c.to_db_row()["params"], ensure_ascii=False), c.price, c.datasheet_url) for c in comps],
                )
            self.conn.commit()

    # ---- artikly (typované API) -----------------------------------------
    def component(self, cid: str):
        from envocad.library.components import Component
        d = self.get_component(cid)
        return Component.from_db_row(d) if d else None

    def components(self, symbol_id: str | None = None, category: str | None = None, search: str = ""):
        """Seznam Component; filtr podle značky, kategorie a textu (výrobce / typ / název)."""
        from envocad.library.components import Component
        out = [Component.from_db_row(d) for d in self.list_components(symbol_id)]
        if category:
            out = [c for c in out if c.category == category]
        if search:
            q = search.lower()
            out = [c for c in out if q in f"{c.manufacturer} {c.part_number} {c.name}".lower()]
        return out

    def import_components_csv_v2(self, path: Path | str) -> int:
        """CSV dle docs/COMPONENTS.md (strukturované sloupce)."""
        from envocad.library.components import read_csv
        comps = read_csv(path)
        for c in comps:
            r = c.to_db_row()
            self.put_component(c.id, c.manufacturer, c.part_number, c.name, c.symbol_id or None, r["params"],
                               c.price, c.datasheet_url)
        return len(comps)

    def put_symbol(self, sym: Symbol, builtin: bool = False) -> None:
        self.conn.execute(
            "INSERT INTO symbols(id,name,category,builtin,data) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, category=excluded.category, "
            "builtin=excluded.builtin, data=excluded.data",
            (sym.id, sym.name, sym.category, int(builtin), json.dumps(sym.to_dict(), ensure_ascii=False)),
        )
        self.conn.commit()
        self._cache[sym.id] = sym

    def get_symbol(self, sid: str) -> Symbol:
        if sid in self._cache:
            return self._cache[sid]
        row = self.conn.execute("SELECT data FROM symbols WHERE id=?", (sid,)).fetchone()
        if row is None:
            raise KeyError(f"Symbol {sid!r} není v knihovně")
        sym = Symbol.from_dict(json.loads(row["data"]))
        self._cache[sid] = sym
        return sym

    def delete_symbol(self, sid: str) -> None:
        self.conn.execute("DELETE FROM symbols WHERE id=? AND builtin=0", (sid,))
        self.conn.commit()
        self._cache.pop(sid, None)

    def list_symbols(self, search: str = "") -> list[tuple[str, str, str]]:
        """[(id, name, category)] seřazené podle kategorie a názvu."""
        q = "SELECT id,name,category FROM symbols"
        args: tuple = ()
        if search:
            q += " WHERE name LIKE ? OR id LIKE ? OR category LIKE ?"
            s = f"%{search}%"
            args = (s, s, s)
        q += " ORDER BY category, name"
        return [(r["id"], r["name"], r["category"]) for r in self.conn.execute(q, args)]

    def categories(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT category FROM symbols ORDER BY category")]

    # ---- komponenty ------------------------------------------------------
    def put_component(self, cid: str, manufacturer: str, part_number: str, name: str,
                      symbol_id: str | None, params: dict | None = None,
                      price: float | None = None, url: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO components(id,manufacturer,part_number,name,symbol_id,params,price,url) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET manufacturer=excluded.manufacturer,"
            "part_number=excluded.part_number,name=excluded.name,symbol_id=excluded.symbol_id,"
            "params=excluded.params,price=excluded.price,url=excluded.url",
            (cid, manufacturer, part_number, name, symbol_id, json.dumps(params or {}, ensure_ascii=False),
             price, url),
        )
        self.conn.commit()

    def get_component(self, cid: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM components WHERE id=?", (cid,)).fetchone()
        if r is None:
            return None
        d = dict(r)
        d["params"] = json.loads(d["params"])
        return d

    def list_components(self, symbol_id: str | None = None) -> list[dict]:
        if symbol_id:
            rows = self.conn.execute("SELECT * FROM components WHERE symbol_id=? ORDER BY manufacturer,part_number",
                                     (symbol_id,))
        else:
            rows = self.conn.execute("SELECT * FROM components ORDER BY manufacturer,part_number")
        out = []
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d["params"])
            out.append(d)
        return out

    def import_components_csv(self, path: Path | str) -> int:
        """CSV se sloupci: id,manufacturer,part_number,name,symbol_id,price,url + libovolné další → params."""
        fixed = {"id", "manufacturer", "part_number", "name", "symbol_id", "price", "url"}
        n = 0
        with open(path, encoding="utf-8-sig", newline="") as f:
            delim = ";" if ";" in f.readline() else ","
            f.seek(0)
            for row in csv.DictReader(f, delimiter=delim):
                params = {k: v for k, v in row.items() if k not in fixed and v}
                price = float(row["price"].replace(",", ".")) if row.get("price") else None
                self.put_component(row["id"], row.get("manufacturer", ""), row.get("part_number", ""),
                                   row.get("name", ""), row.get("symbol_id") or None, params, price, row.get("url"))
                n += 1
        return n

    def close(self) -> None:
        self.conn.close()
