- **Knihovna: verze schématu a migrace** – databáze knihovny nese verzi v `PRAGMA user_version`; novější knihovnu
  (z novější verze EnvoCADu) program odmítne s hláškou a nezmění ji, starší převede krok za krokem v transakci.
  Soubory `envocad/library/store.py`, `app.py`, `cmd/__main__.py`, test `test_library_schema_version.py`.
