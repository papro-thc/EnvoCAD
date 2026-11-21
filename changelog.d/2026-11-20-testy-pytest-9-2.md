- **Oprava: testy s pytest ≥ 9.2, na Linuxu a v čistém prostředí** – `monkeypatch` na zastaralých jménech
  `envocad.generate` (`_lib`, …) po testu vrátí původní hodnotu (nový `__delattr__`); dřív hodnota prosákla do
  dalších testů a sada padala ve stovkách testů. `read_manifest` odmítá jméno ZIPu s `/`, `\` nebo diskem `C:`
  na všech systémech. Snímek generátoru `tests/data/generate_snapshot.json` přegenerován (síť rámečku podle
  formátu listu, sekundár MTP `1S1…3S2`), `pillow` v dev závislostech pro test vykreslení PDF. Pytest vypíše
  zásobník testu zaseknutého přes 5 min. Okna, která test nezavřel, po testu zastaví autosave – jejich kopie
  zablokovala pozdější test dialogem obnovy. Testy na Windows: písma pro `offscreen` z `C:\Windows\Fonts` (jinak
  PDF bez textu), oddělovač v klíčích knihovny podle systému, volnější časová mez testu rychlosti na CI. Testy `test_generator_chain.py`, `test_updater.py`, `test_macros.py`.
