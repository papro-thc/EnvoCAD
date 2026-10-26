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
| `category` | `mcb`, `mccb`, `rcd`, `rcbo`, `spd`, `switch`, `contactor`, `fuse`, `fuse_holder`, `meter`, `inverter`, `inverter_hybrid`, `battery`, `pv_module`, `enclosure`, `terminal`, `relay`, `accessory`, `connector`, `cable`, `other` | |
| `symbol_id` | schematická značka z knihovny (viz `LibraryStore().list_symbols()`) | např. `fve.breaker_mcb`, `sb.rcd`, `fve.inverter`, `fve.spd`; skříň: prázdné |
| `footprint_id` | symbol pro rozložení (prázdné = generický tvar: modulový podle `modules`, obdélník `width_mm` × `height_mm` u MCCB / 3VA a artiklů bez `modules` vyšších než 100 mm, svorky po `width_mm` – `model/device_size.py`) | |
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
| `t_min_c`, `t_max_c` | rozsah provozní teploty okolí přístroje dle datasheetu (ne skladovací); −60 až 150, `t_min_c` < `t_max_c`. Hodnocení oteplení po přístrojích – bez údaje se počítá s 40 °C. Jen ověřené hodnoty z datasheetu, vestavěné CSV mají sloupce zatím prázdné | °C |
| `p_ac_kw`, `p_dc_max_kwp`, `mppt`, `phases`, `i_ac_max_a` | střídače | kW, kWp, počet, 1/3, A |
| `u_dc_max_v`, `u_mppt_min_v`, `u_mppt_max_v`, `i_mppt_max_a`, `strings_per_mppt` | střídače – pro kontrolu stringů (výpočty): max. vstupní napětí DC, okno MPPT, max. (provozní) vstupní proud na MPPT, počet stringů na MPPT. Platí u_mppt_min < u_mppt_max ≤ u_dc_max, strings_per_mppt ≥ 1 | V, V, V, A, ks |
| `isc_mppt_max_a` | střídače – max. zkratový proud na MPPT (datasheet „Max. short-circuit current per MPPT“). S ním se kontroluje součet Isc paralelních stringů na MPPT (chyba) a součet Impp proti `i_mppt_max_a` (varování „omezení výkonu“); bez něj platí 1,25·Isc jednoho stringu proti `i_mppt_max_a` | A |
| `string_mode`, `u_string_v`, `n_opt_min`, `n_opt_max`, `p_string_max_w` | střídače – režim stringů a pravidla pro optimizéry (`docs/design/optimizery.md`). `string_mode`: prázdné = `classic`, `optimizer` (klasické meze Uoc/MPPT + počet optimizérů a P stringu), `fixed_voltage` (SolarEdge: pevné napětí stringu `u_string_v`, délku určuje počet optimizérů; Uoc·n a okno MPPT se nekontrolují; platí `u_string_v` ≤ `u_dc_max_v`, `n_opt_min` ≤ `n_opt_max`). `n_opt_min`/`n_opt_max` = počet optimizérů ve stringu, `p_string_max_w` = max. výkon stringu. Jen hodnoty z listu střídače; neznámé nech prázdné (kontrola pak hlásí „chybí údaj“) | –, V, ks, ks, W |
| `eff_max_pct`, `eff_eu_pct`, `weight_kg` | střídače – max. a evropská účinnost, hmotnost (jen katalog) | %, %, kg |
| `p_wp`, `voc_v`, `vmp_v`, `isc_a`, `imp_a`, `beta_voc` | FV moduly (`pv_modules.csv`, STC) + tepl. součinitel Uoc. Povinné `voc_v`, `isc_a`; vmp < voc, imp < isc, −1 < β < 0, \|p_wp − vmp·imp\| ≤ 3 % p_wp | Wp, V, V, A, A, %/K |
| `alpha_isc`, `gamma_pmax`, `noct_c` | FV moduly – tepl. součinitel Isc a Pmax, NOCT (jen katalog) | %/K, %/K, °C |
| `u_sys_max_v`, `i_fuse_max_a` | FV moduly – max. napětí systému (kontrola Uoc stringu), max. jištění řady (rezerva) | V, A |
| `technology`, `weight_kg` | FV moduly – technologie (text, např. „N-type TOPCon bifacial“), hmotnost; rozměry v `width_mm`, `height_mm`, `depth_mm`, provozní teploty v `t_min_c`, `t_max_c` | –, kg |
| `p_max_w`, `p_tol_pct`, `u_in_max_v`, `isc_in_max_a`, `modules_per_optimizer` | optimizéry (`optimizers.csv`, `category=optimizer`, vstup od modulu). **Povinné** `p_max_w`, `u_in_max_v`, `isc_in_max_a` a `modules_per_optimizer` (1 nebo 2) – řádek bez nich se neukládá. `p_tol_pct` = tolerance P max dle výrobce (jen když ji výrobce uvádí, jinak prázdné = 0). Isc se porovnává s Isc STC modulu (bez 1,25) | W, %, V, A, ks |
| `u_mppt_min_v`, `u_mppt_max_v`, `i_out_max_a`, `u_out_max_v` | optimizéry – okno MPPT vstupu (min < max ≤ `u_in_max_v`), max. výstupní proud a napětí. `u_out_max_v` omezí příspěvek optimizované jednotky k Uoc stringu v režimu `optimizer` | V, V, A, V |
| `string_mode`, `partial_ok`, `compat` | optimizéry – doporučený režim stringů střídače (použije se, když ho nezadá spec ani artikl střídače), smíšení optimalizovaných a neoptimalizovaných modulů dovoleno (0/1), kompatibilní střídače podle výrobce (`SolarEdge`, `Huawei SUN2000`, `*`; položky oddělené `,` `;` `/`) | –, 0/1, text |
| `n_min_1ph`, `n_max_1ph`, `p_string_max_1ph_w`, `n_min_3ph`, `n_max_3ph`, `p_string_max_3ph_w` | optimizéry – pravidla stringu z listu optimizéru podle fáze střídače: počet optimizérů ve stringu a max. výkon stringu. Z nich vznikají atributy stringu `opt_n_min`, `opt_n_max`, `opt_p_string_max`; ve výpočtu platí nejpřísnější z pravidel střídače a optimizéru. Výjimky („vyšší P stringu při ≥ N optimizérech“) patří do `note` | ks, ks, W |
| `e_kwh`, `p_kw`, `u_dc_v` | baterie (`batteries.csv`): kapacita, jmenovitý výkon a jmenovité napětí **jednoho modulu / kusu** (výkon jen když ho datasheet uvádí na modul, jinak prázdné; věž se skládá z modulů, viz `bat_role`) | kWh, kW, V |
| `bat_role`, `bat_link`, `n_mod_min`, `n_mod_max` | baterie: role v systému – `master` (BMS + modul), `slave` (přídavný modul k masteru), `module` (modul bez BMS), `bms` (řídicí jednotka, bez kapacity), `system` (hotové úložiště, jeden kus), `accessory` (příslušenství). `bat_link` = id artiklů (oddělená `,`), které věž doplňují: u `master` jeho `slave` (n − 1 ks), u `module` řídicí jednotka `bms` (1 ks; víc id = uživatel vybere). `n_mod_min` / `n_mod_max` = počet modulů věže (u masteru včetně něj) podle datasheetu; u `system` 1. Průvodce nabízí jen role `master`, `module`, `system`. Kompatibilita se střídačem se zapisuje do `note` (datasheet ji často neuvádí – pak se nedomýšlí) | text, id, ks, ks |
| `spd_type`, `uc_v`, `up_kv`, `iimp_ka`, `in_ka` | svodiče | T1 / T2 / T1+T2 / T1+T2 DC; V; kV; kA; kA |
| `ucpv_v` | svodič DC: max. trvalé napětí Ucpv (EN 61643-31, datasheet „UCPV“) – mez délky stringu a kontrola F7 (atribut prvku `ucpv`; bez sloupce se jako záloha čte „Ucpv … V“ z `note`). U DC svodiče je `uc_v` jmenovitá třída (např. 1000), Ucpv může být vyšší (VPU PV I+II 3 1000: 1100 V) | V |
| `rows`, `modules_per_row`, `ip`, `ik`, `material`, `mounting`, `door` | skříně | |
| `terminal_kind`, `connection`, `cross_mm2`, `cross_max_mm2`, `width_mm`, `in_`, `un_v`, `color`, `levels` | řadové svorky: druh (`prochozi`, `pe`, `n-odpojovaci`, `dvoupatrova`, `pojistkova`, `rozbocovaci`, `distribucni`, `mustek`), připojení (`sroub`, `push-in`, `pruzina`), jmenovitý / max. průřez, rozteč (šířka), In, Un, barva, počet pater | mm², mm, A, V |
| `in_max_a` | držák pojistky (`fuse_holder`): max. In vložky (EFH 10 DC = 25 A, OEZ OPVP10/14/22 = 32/63/125 A, Eaton CHPV1U = 30 A). Mez se bere **jen** z `in_max_a` (ne z `in_`). Generátor podle něj omezí In pojistky gPV stringu (i SolarEdge 25 A); když žádná velikost nevyhoví, nechá In prázdné a kontrola (F7) hlásí chybu; In vložky nad `in_max_a` přiřazeného držáku = chyba F7 `fuse_over_holder`. `in_` u držáku = jmenovitý proud odpínače (OPVP: Ie) – do prvku se **nepropisuje** (In je vlastnost vložky) | A |
| `cores_n`, `cross_mm2`, `od_mm`, `un_v`, `shield` | kabely: počet žil, průřez, vnější průměr, Un, stínění (`ano`) | ks, mm², mm, V |
| `contacts` | kontaktní obraz (stykače, relé, jističe s pomocnými kontakty): páry svorek oddělené mezerou, volitelně `NO:`/`NC:`/`P:` – viz `docs/LIBRARY_FORMAT.md` | např. `1/2 3/4 5/6 13/14`, `NO:11/14 NC:11/12` |
| `macro` | **rezervováno** pro funkční šablonu artiklu: název makra (`docs/LIBRARY_FORMAT.md`, „Formát makra“), které artikl vkládá. Zatím se nevyhodnocuje – sloupec se jen uloží do `params` | |
| `note` | cokoliv dalšího (např. „DC 1000 V“, „s pomocným kontaktem“) | |

## Propsání do prvku

Při výběru artiklu v dialogu prvku se naplní atributy prvku: `type` ← `part_number`, `manufacturer`,
`in_`, `poles`, `char`, `icu`, `idn`, `modules`, `p_loss_w`, `t_min`, `t_max`, `spd_type`, `uc`, `p_ac`, `p_dc_max`,
`mppt`, `phases`, `e_kwh`, `p_kw`, `p_string`, `contacts`, u střídače `u_dc_max`, `u_mppt_min`, `u_mppt_max`,
`i_mppt_max`, `isc_mppt_max`, `strings_per_mppt`, u svodiče DC `ucpv`, u FV modulu (`fve.pv_string`) `p_module`, `voc`, `vmp`, `isc`,
`imp`, `beta_voc`, `u_sys_max`… (mapování `PARAM_TO_ATTR` v `envocad/library/components.py`, hodnoty bez prvku
vrací `Component.attr_values()`). Atributy, které artikl nezná, zůstanou, jak byly.
Rozměry (`width_mm`, `height_mm`, `depth_mm`) a `p_loss_w` se pro rozložení a oteplení čtou z artiklu i bez propsání
(`model/device_size.py`, `thermal.rated_loss`); atributy prvku `width_mm` / `height_mm` / `depth_mm` jsou ruční
přepis. Skupina svorek: `end_mm` (koncové desky / zarážky) a `bridge_id` (artikl můstku, `terminal_kind=mustek`).

## Checklist pro agenty `data-entry`

1. Vyber **jen** výrobky, které výrobce aktuálně nabízí; každý řádek má `datasheet_url` na stránku,
   kde jsou hodnoty vidět.
2. Hodnoty opisuj v jednotkách tabulky; neznámé nech prázdné; v `note` stručně, co je nejisté.
3. `symbol_id` jen z existujících symbolů (`fve.*`, `sb.*`) – seznam v `docs/LIBRARY_FORMAT.md`.
4. Ověř: `python -m envocad.library.components validate soubor.csv` → žádné chyby.
5. Vrať tabulku: soubor, počet řádků, které sloupce jsou vyplněné u kolika % řádků, co chybí.

### Optimizéry (`optimizers.csv`, `docs/design/optimizery.md` §5)

Pravidla jako u modulů a střídačů (jen WebSearch, doslovně se zdrojem, nic neodhaduj, `note` „WebSearch <datum>; nejistoty“).
Povinné `p_max_w`, `u_in_max_v`, `isc_in_max_a`, `modules_per_optimizer` (jen se zdrojem), řádek musí projít `validate`.
Pravidla stringu (`n_min_*`, `n_max_*`, `p_string_max_*_w`) z tabulky „PV system design“ v listu optimizéru.
Atributy stringu z artiklu: `Component.optimizer_values(phases)` (ne `attr_values`/`apply_to`).

### Baterie (`batteries.csv`)

`category=battery`, `symbol_id=fve.battery`, `source=datasheet` + stránka výrobce v `datasheet_url` a název PDF
v `note`. Hodnoty jen z datasheetu, nejasné prázdné s důvodem v `note`. Rozlišuj roli (`bat_role`): master / slave /
modul / BMS (viz tabulka sloupců) – věž = základ + (n − 1) slave, nebo n modulů + BMS. `validate` hlídá roli, `bat_link`
(existující id, jen u master / module), `n_mod_min` ≤ `n_mod_max`, kladné `e_kwh` a povinné `e_kwh` u master / module /
system. Čte se každé `*.csv` v `components/` (`LibraryStore` načítá rekurzivně), do balíčku i PyInstalleru jdou
(`pyproject.toml` package-data, `envocad.spec`). Logika výběru a věže: `envocad/library/batteries.py`.

### FV moduly a střídače (katalog pro průvodce, `docs/design/katalog_fv.md` §5)

1. Nejdřív doplň nové sloupce 13 střídačů v `inverters.csv` z textu jejich `note` (jen doslovné hodnoty se zdrojem);
   ostatní buňky neměň.
2. Pak `pv_modules.csv` (`category=pv_module`, `symbol_id=fve.pv_string`) a další střídače (`inverters.csv`).
3. Zdroj **jen WebSearch**; každé číslo musí být doslovně ve výsledku hledání (datasheet / stránka výrobce).
4. `datasheet_url` vždy; `source=web`, `source=datasheet` jen pro PDF výrobce.
5. Nic neodhaduj ani nedopočítávej (ani Pmax = Vmp·Imp, ani počet MPPT z počtu vstupů) – neznámé nech prázdné.
6. `note`: „WebSearch <datum>; nejistoty“ (např. které hodnoty platí pro celou řadu).
7. `id` = `<výrobce>-<typ>` malými písmeny (např. `ja-solar-jam54d40-450-lb`, `huawei-sun2000-10ktl-m1`).
8. Řádek modulu bez `voc_v` / `isc_a` a řádek střídače bez `u_dc_max_v` a okna MPPT (`u_mppt_min_v`,
   `u_mppt_max_v`) **neukládej**.
9. Řádek musí projít `python -m envocad.library.components validate soubor.csv --symbols` (kontroluje i vmp < voc,
   imp < isc, −1 < β < 0, |p_wp − vmp·imp| ≤ 3 %, u_mppt_min < u_mppt_max ≤ u_dc_max, strings_per_mppt ≥ 1).
