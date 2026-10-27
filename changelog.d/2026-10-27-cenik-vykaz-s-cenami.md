- **Ceník artiklů a výkaz materiálu s cenami** – `Knihovna → Načíst ceník artiklů (CSV)…` uloží ceník firmy do
  `~/.envocad/ceny.csv` (sloupce `price_czk` a `id`, nebo `manufacturer` + `part_number`; katalog ho při
  aktualizaci nepřepíše). Nový výkaz „Výkaz materiálu s cenami“ (ve výkazech xlsx, ne v PDF dokumentaci): položky
  výkazu materiálu s cenou za kus z ceníku, jinak z artiklu (`price_czk`), cenou celkem a součtem bez DPH s počtem
  položek bez ceny. `library/prices.py`, `export/reports.py` (`priced_bom`), `ui/main_window.py`; test
  `test_prices.py`.
