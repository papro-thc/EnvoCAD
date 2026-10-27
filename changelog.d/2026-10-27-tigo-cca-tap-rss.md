- **Optimizéry Tigo: CCA + TAP nebo vysílač RSS** – nové bloky **Tigo CCA** (`fve.tigo_cca`: GW, LAN, PWR),
  **Tigo TAP** (`fve.tigo_tap`: GW) a **Tigo RSS vysílač** (`fve.tigo_rss`: PWR, jádro na stringy) v kategorii
  Komunikace a makro **Tigo CCA + TAP** (RS485 Gateway A/B/+/GND). Kontrola F7: string s optimizérem Tigo bez RSS
  i CCA → `tigo_missing`, CCA bez TAP → `tigo_tap_missing`. Generátor u optimizérů Tigo doplní nad horní string
  TAP → CCA (`optimizer.tigo` = `cca`, výchozí), vysílač RSS (`rss`) nebo nic (`none`). `generator/tigo.py`,
  `model/checks.py`, `tools/gen_builtin_fve.py`, `tools/gen_builtin_macros.py`, test `test_tigo.py`.
