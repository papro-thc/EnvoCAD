- **Kontrola F7: úplnost podkladů pro distributora** – při vyplněném distributoru (`fve.grid.dso`) hlásí varování
  `dso_inverter_data` (střídač bez výrobce, typu, AC výkonu nebo počtu fází), `dso_battery_data` (akumulace bez
  kapacity / výkonu), `dso_main_breaker` (hlavní jistič bez hodnoty / pólů) a `dso_instrument_transformers` (MTP / MTN
  v elektroměrovém nebo hlavním rozvaděči bez převodu, třídy přesnosti, zatížitelnosti) a info `dso_feed_cable`
  (připojovací kabel bez typu, průřezu, délky); jen přítomnost údajů, žádné prahy, export se neblokuje. Symbol
  `fve.vt` má atribut `burden`. Test `test_f7_dso.py`.
