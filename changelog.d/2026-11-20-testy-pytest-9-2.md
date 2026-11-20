- **Oprava: testy s pytest ≥ 9.2, na Linuxu a v čistém prostředí** – `monkeypatch` na zastaralých jménech
  `envocad.generate` (`_lib`, …) po testu vrátí původní hodnotu (nový `__delattr__`); dřív hodnota prosákla do
  dalších testů a sada padala ve stovkách testů. `read_manifest` odmítá jméno ZIPu s `/`, `\` nebo diskem `C:`
  na všech systémech. Snímek generátoru `tests/data/generate_snapshot.json` přegenerován (síť rámečku podle
  formátu listu, sekundár MTP `1S1…3S2`), `pillow` v dev závislostech pro test vykreslení PDF. Pytest vypíše
  zásobník testu zaseknutého přes 5 min. Testy `test_generator_chain.py`, `test_updater.py`, `test_macros.py`.
