- **Baterie u víc střídačů a kontrola kompatibility** – specifikace `battery.inverters` („all“ nebo seznam označení
  T1, T2…; výchozí jen první) dá baterii stejného typu pod každý zvolený střídač (hybridní značka, vlastní kabel
  na svorku BAT); v průvodci volba **ke každému střídači**. Rodinný dům zatím jen jeden hybrid s baterií (EPS
  a návrat do RD). Nová kontrola F7 `battery_incompatible`: katalogová baterie na svorce BAT střídače z katalogu,
  ke kterému podle `inv_compat` nepasuje. `library/batteries.py` (`battery_targets`), `generator/pv.py`,
  `model/checks.py`, `ui/dialogs.py`; testy v `test_batteries.py`, `test_wizard_battery.py`.
