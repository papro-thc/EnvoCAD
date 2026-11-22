- **Import artiklů z BMEcat** – menu Knihovna → Importovat artikly z BMEcat (XML) načte katalog BMEcat 1.2 i 2005
  (výrobce, objednací číslo, název, GTIN, datasheet, rozměry a hmotnost, ETIM třída a vlastnosti jako text) do
  uživatelské knihovny; artikl už v knihovně z jiného zdroje se přeskočí (nikdy se nepřepíše), opakovaný import zachová přiřazený symbol a cenu. XML se čte přes `defusedxml`. Testy
  `test_bmecat_import.py`, `test_bmecat_import_gui.py`.
