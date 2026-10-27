- **Hybridní střídač: svorky baterie a zálohy, baterie podle střídače** – blok hybridního střídače má vždy dvě
  výkonové svorky navíc: BAT (baterie) a BACKUP (záložní výstup), BACKUP i u řady bez profilu (`inverter_io(…,
  hybrid=True)`); nezapojená záloha se v kontrole nehlásí. V průvodci se u hybridního střídače nabízejí jen baterie,
  které k němu pasují – nový sloupec baterií `inv_compat` (vzory typů střídačů z datasheetu: LUNA2000 S0 →
  SUN2000 KTL-L1/M1/M0, Lynx Home F → GoodWe ET/EH, APX → MIN …TL-XH, T-BAT H V2 → X1/X3-Hybrid, LUNA2000-241 „-“),
  bez vzorů stejný výrobce; zaškrtnutím „i ostatní baterie“ celý katalog. `library/batteries.py` (`compatible`,
  `choices(only_compatible=…)`), testy `test_inverter_io.py`, `test_batteries.py`, `test_wizard_battery.py`.
