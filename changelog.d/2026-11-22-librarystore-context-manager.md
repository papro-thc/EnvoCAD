- **Oprava: zavírání knihovny v testech** – `LibraryStore` lze používat v `with` (zavře spojení na konci bloku);
  testy výkazu po výrobcích tak nenechávají otevřený `lib.db` (na Windows chyba při mazání souboru).
  `library/store.py`, testy `test_library_store_close.py`, `test_bom_by_manufacturer.py`.
