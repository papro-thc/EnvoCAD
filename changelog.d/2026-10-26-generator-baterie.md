- **Průvodce: baterie u hybridního střídače + katalog baterií z datasheetů** – nový `batteries.csv` (18 artiklů,
  `category=battery`, `source=datasheet`, jen hodnoty z PDF, nejasné prázdné): SolaX T-BAT H 5.8 V3 (master + slave
  HV11550-A V3) a V2 (master + slave HV11550 V2), SolaX TP-HS36 (modul 3,6 kWh) + BMS TBMS-MCS0800 + Series Box,
  Sigenergy SigenStor BAT 5.0 / 8.0, SigenStack BAT 12.0 + 5 řídicích jednotek BC, Growatt ARK 2.5H-A2 + BMS HVC 60050-C2;
  Huawei LUNA2000-241-2S1 se přesunulo z `inverters.csv` (id stejné). Nové sloupce `bat_role` (master / slave / module /
  bms / system / accessory), `bat_link` (slave / BMS věže), `n_mod_min`, `n_mod_max` – validátor je hlídá
  (`docs/COMPONENTS.md`). V kroku „Moduly a střídače“ se u artiklu střídače `inverter_hybrid` ukáže skupina **Baterie**
  (artikl – stejný výrobce první –, počet modulů v mezích datasheetu, řídicí jednotka, souhrn kWh/kW); u nehybridního
  střídače je skrytá a `battery` ve specifikaci chybí. Generátor (`battery.component_id` + `modules` + `bms_id`,
  `library/batteries.py`) doplní typ, kapacitu a výkon věže, prvek baterie nese artikl a výkaz materiálu rozepíše
  master/modul × n, slave a BMS; EPS u rodinného domu funguje s katalogovou baterií. `pyproject.toml` do balíčku
  přidává i `library/builtin/**/*.csv`. Testy `test_batteries.py`, `test_wizard_battery.py`.
