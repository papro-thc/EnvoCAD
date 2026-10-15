# Knihovna artiklů (komponent)

Artikl = konkrétní výrobek (např. `OEZ LTN-16B-3`) s parametry z katalogu. Je napojený na:

- **schematickou značku** `symbol_id` (symbol z knihovny, např. `fve.breaker_mcb`), volitelně přesnější
  vlastní značku výrobce;
- **footprint** `footprint_id` – pohled do rozložení (symbol v mm ve skutečné velikosti; z DXF výrobce,
  nebo generický modulový podle `modules`);
- parametry, které se po přiřazení k prvku **propíší do atributů prvku** (In, póly, charakteristika,
  Icu, moduly, ztrátový výkon…), takže výkazy, rozložení a oteplení pracují s katalogovými daty.

Data jsou v CSV souborech `envocad/library/builtin/components/<vyrobce>.csv` (verzované v gitu, při
startu se nahrají do SQLite `~/.envocad/library.db`). Uživatelské artikly lze přidat přes
`Knihovna → Importovat artikly z CSV…`.

## Formát CSV (oddělovač `;`, UTF‑8, desetinná čárka i tečka OK)

Povinné sloupce: `id;manufacturer;part_number;name;category;symbol_id;datasheet_url;source`
Volitelné (podle kategorie): viz tabulka. Neznámou hodnotu nechte **prázdnou** – nikdy neodhadujte.

| Sloupec | Význam | Jednotka / hodnoty |
|---|---|---|
| `id` | jedinečné, `<vyrobce>-<objednaci-cislo>` malými písmeny, bez mezer | |
| `manufacturer` | Výrobce | OEZ, Eaton, Hager, Schneider, ABB, Siemens, SMA, Huawei, SolarEdge, Fronius, SolaX, GoodWe, BMR… |
| `part_number` | Objednací číslo / typové označení přesně dle katalogu | |
| `name` | Lidský název | např. „Jistič LTN 16B 3p“ |
| `category` | `mcb`, `mccb`, `rcd`, `rcbo`, `spd`, `switch`, `contactor`, `fuse`, `fuse_holder`, `meter`, `inverter`, `inverter_hybrid`, `battery`, `pv_module`, `enclosure`, `terminal`, `relay`, `accessory`, `connector`, `other` | |
| `symbol_id` | schematická značka z knihovny (viz `LibraryStore().list_symbols()`) | např. `fve.breaker_mcb`, `sb.rcd`, `fve.inverter`, `fve.spd`; skříň: prázdné |
| `footprint_id` | symbol pro rozložení (prázdné = generický modulový podle `modules`) | |
| `datasheet_url` | odkaz na katalogový list / stránku výrobce, ze které hodnoty pocházejí | **povinné pro data od agentů** |
| `source` | `catalog`, `datasheet`, `web`, `seed` (ručně, ověřit), `user` | |
| `price_czk` | cena bez DPH, pokud veřejná | Kč |
| `in_` | jmenovitý proud In | A |
| `poles` | počet pólů (1, 2, 3, 4; 1+N → 2; 3+N → 4) | |
| `char` | vypínací charakteristika B/C/D (jističe), gPV/gG/aM (pojistky), A/AC/B/F (chrániče) | |
| `icu_ka` | zkratová schopnost Icu/Icn | kA |
| `idn_ma` | jmenovitý reziduální proud IΔn | mA |
| `un_v` | jmenovité napětí | V (AC), u DC prvků uveďte `DC` v `note` |
| `modules` | šířka na DIN liště | moduly 17,5 mm (0,5 = 9 mm) |
| `width_mm`, `height_mm`, `depth_mm` | rozměry | mm (u modulových: šířka, výška čela, hloubka) |
| `p_loss_w` | ztrátový výkon při In (celý přístroj, všechny póly) | W |
| `p_ac_kw`, `p_dc_max_kwp`, `mppt`, `phases`, `i_ac_max_a` | střídače | kW, kWp, počet, 1/3, A |
| `e_kwh`, `p_kw`, `u_dc_v` | baterie | kWh, kW, V |
| `p_wp`, `voc_v`, `isc_a`, `vmp_v`, `imp_a` | FV moduly (STC) | Wp, V, A |
| `spd_type`, `uc_v`, `up_kv`, `iimp_ka`, `in_ka` | svodiče | T1 / T2 / T1+T2 / T1+T2 DC; V; kV; kA; kA |
| `rows`, `modules_per_row`, `ip`, `ik`, `material`, `mounting`, `door` | skříně | |
| `note` | cokoliv dalšího (např. „DC 1000 V“, „s pomocným kontaktem“) | |

## Propsání do prvku

Při výběru artiklu v dialogu prvku se naplní atributy prvku: `type` ← `part_number`, `manufacturer`,
`in_`, `poles`, `char`, `icu`, `idn`, `modules`, `p_loss_w`, `spd_type`, `uc`, `p_ac`, `p_dc_max`,
`mppt`, `phases`, `e_kwh`, `p_kw`, `p_string`… (mapování v `envocad/library/components.py`).
Atributy, které artikl nezná, zůstanou, jak byly.

## Checklist pro agenty `data-entry`

1. Vyber **jen** výrobky, které výrobce aktuálně nabízí; každý řádek má `datasheet_url` na stránku,
   kde jsou hodnoty vidět.
2. Hodnoty opisuj v jednotkách tabulky; neznámé nech prázdné; v `note` stručně, co je nejisté.
3. `symbol_id` jen z existujících symbolů (`fve.*`, `sb.*`) – seznam v `docs/LIBRARY_FORMAT.md`.
4. Ověř: `python -m envocad.library.components validate soubor.csv` → žádné chyby.
5. Vrať tabulku: soubor, počet řádků, které sloupce jsou vyplněné u kolika % řádků, co chybí.
