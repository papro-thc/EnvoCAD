- **Normové tabulky lokálně mimo git** – Iz, činitele a oteplení skříně (`calc`, `thermal`) lze přepsat souborem
  `~/.envocad/norms/*.json` (formát `envocad-norms`, ověření a konflikty, vadný soubor se odmítne celý a výpočet
  dál běží); vestavěné hodnoty beze změny. Nové referenční sady `tests/data/ref_iz.json`, `ref_thermal.json`
  (prázdné) pro porovnání se Sichrem, návod `docs/NORMY_FORMAT.md`, pojistka `tools/check_licensed_data.py`.
  Testy `test_norm_tables.py`, `test_ref_sets.py`.
