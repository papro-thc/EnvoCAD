# Soupis údajů z norem potřebných k ověření výpočtů

Stav k 2026-11-22 (issue #79). Dokument říká, **které hodnoty musí člověk s přístupem k normám dodat nebo
potvrdit**, aby šly výpočty EnvoCADu ověřit. Agent normy nemá – nic zde není z norem doplněno ani odhadnuto.

## Jak tabulky číst

- **Kde v kódu** – `soubor:řádek` (cesty od `envocad/`) a jméno konstanty / funkce. Čísla řádků platí k datu
  dokumentu; po úpravách kódu hledejte podle jména.
- **Současná hodnota** – co je dnes v kódu (data repozitáře, ne citace normy).
- **Zdroj podle kódu** – co o původu tvrdí komentář nebo docstring. „neuveden“ = kód zdroj neříká.
- **Označení** – jak je hodnota dnes v kódu označená: ORIENTAČNÍ / z paměti / odhad / „jisté“ (tvrzení
  komentáře, neověřeno) / předpoklad / bez označení. Žádná hodnota v kódu není označená jako ověřená proti normě.
- **Co dodat** – co přesně má člověk vytáhnout z normy a v jakém tvaru. Stačí fakta (čísla, jednotky, číslo
  tabulky / článku, vydání normy) – **texty ani tabulky norem nekopírujte 1:1** (viz `docs/SOURCES.md`).
- **Priorita** – **V** (vysoká) = hodnota vstupuje do protokolu, technické zprávy (TZ), výkazu nebo přímo
  určuje vygenerované jištění / průřez ve schématu; **S** (střední) = jen kontrola F7 v GUI; **N** (nízká) =
  výchozí hodnota / nápověda.

U každé dodané hodnoty prosíme uvést: normu **včetně vydání a roku**, číslo tabulky / obrázku / článku,
jednotky a podmínky platnosti (materiál, izolace, teplota, uložení…).

## Seznam norem podle priority (co hledat)

| Pořadí | Norma (jak ji uvádí kód) | Co z ní je potřeba | Oddíl |
|---|---|---|---|
| 1 | IEC TR 60890:2014 (+ ČSN EN 61439-1 čl. 10.10.4.3.1) | tab. 3 (činitel b), obr. 3 a 4 (konstanta k), obr. 6 a 7 (činitel c), činitel d, exponent x, vzorce, rozložení teploty po výšce, podmínky platnosti metody; případně obr. 5 (skříně s otvory) | 2 |
| 2 | ČSN 33 2000-5-52 | tabulky Iz podle způsobu uložení (kód: „tab. B.52.4/B.52.5“), teplotní činitele (kód: „tab. B.52.14“), činitele seskupení, přiřazení způsobů uložení | 1.1 |
| 3 | ČSN 33 2000-4-43 (čl. 433.1), EN 60898, EN 60947-2, EN 60269-1 (tab. 2), EN 60269-6 | podmínky ochrany proti přetížení, poměr I2/In podle typu přístroje | 1.1 |
| 4 | ČSN 33 2000-7-712, IEC 62548 | činitel 1,25·Isc, dimenzování pojistek gPV (1,5–2,4·Isc), postup výpočtu Uoc(t_min) / Umpp(t_max), návrhové teploty | 1.2 |
| 5 | ČSN EN 61439-1 (ed. 3) – čl. 11, příl. H | položky a limity kusového ověření (čl. 11.2–11.10), průřezy vnitřních vodičů podle proudu | 3.4, 5 |
| 6 | ČSN EN 60909-0 (tab. 1) | součinitel c_max, vzorec Ik transformátoru | 3.1 |
| 7 | ČSN 33 2000-5-534, ČSN EN 62305-4, (EN) 61643-32, EN 61643-31 | Uc svodičů AC, Ucpv svodičů DC, délka přívodů SPD, průřez PE svodiče, SPD typu 1 při LPS | 3.1, 3.2, 3.4 |
| 8 | ČSN EN 60947-1 (čl. 6.1.1), ČSN EN 60898-1, EN 60947-2, EN 60947-7-1 | teploty okolí přístrojů, referenční teploty kalibrace, mezní teploty svorek | 2 |
| 9 | Podmínky provozovatele DS (v kódu **neuvedeny** – jen „rozhodnutí“, „mustr“) | hranice síťové ochrany 30 kWp, její jištění a působení, třídy přesnosti MTP/MTN, hranice 80 A pro jistič vývodu FVE | 3.3, 4 |
| 10 | ČSN EN 50160, řady jmenovitých proudů (normy v kódu neuvedeny) | rozsah vn, řady In jističů nn, pojistek vn, primárů MTP | 4 |
| 11 | ČSN EN 60445, ČSN EN 62491, IEC 60947-1, DIN 46228, DIN 43856, HD 361 | značení vodičů a svorek, dutinky, třídy ohebnosti | 3.4, 4 |

## 1. `model/calc.py` – kabely, stringy, selektivita

Výstupy: technická zpráva (`export/tz_data.py` – stringy ř. 465–480, kabely ř. 526–535, selektivita), výkaz
„Výpočty“ (`export/reports.py` ř. 551–578), kontroly F7 (`calc_string`, `calc_cable`, `calc_selectivity`,
`calc_temp`) a generátor (průřezy kabelů, pojistky stringů).

### 1.1 Zatížitelnost kabelů, přetížení, úbytek napětí

| ID | Kde v kódu | Současná hodnota | Zdroj podle kódu | Označení | Co dodat | Pr. |
|---|---|---|---|---|---|---|
| K1 | `model/calc.py:30` `IZ_3` | Iz [A] pro způsoby A1, B1, C, D, E; 15 průřezů 1,5–240 mm²; Cu, PVC 70 °C, okolí 30 °C, 3 zatížené vodiče (A1 13,5–286 A, B1 15,5–346 A, C 17,5–403 A, D 18–280 A, E 22–514 A) | ř. 29: „ČSN 33 2000-5-52 tab. B.52.4/B.52.5“; docstring ř. 3–5 mluví o „tabulkách A.52 … (B.52.x) – přepsané z normy“ (odkazy si odporují) | ORIENTAČNÍ | Správné číslo tabulky a vydání pro každý způsob uložení; Iz [A] pro 1,5–240 mm² (případně výš), Cu/PVC, 3 zatížené vodiče. Pokud se mají počítat i jiné kabely: zvlášť Al a zvlášť izolace XLPE/EPR (solární kabely). U způsobu D podmínky (teplota a tepelný odpor půdy). Formát: tabulka průřez [mm²] × způsob → Iz [A]. | V |
| K2 | `model/calc.py:42` `IZ_2_FACTOR` | 1,10 (2 zatížené vodiče = hodnota pro 3 × 1,10) | „≈ +10 % (orientační)“ | ORIENTAČNÍ | Tabulkové Iz pro 2 zatížené vodiče (1f, DC) ve stejném rozsahu jako K1 – činitel pak odpadne; nebo potvrzení, že násobení stačí. | V |
| K3 | `model/calc.py:43` `AL_FACTOR` | 0,78 (Al = Cu × 0,78 pro všechny průřezy a způsoby) | neuveden („Al vodiče“) | bez označení | Tabulky Iz pro Al vodiče (stejné způsoby, průřezy podle normy), nebo potvrzení činitele. | V |
| K4 | `model/calc.py:44` `METHOD_HINTS`; výchozí způsob C (`route_method`, ř. 69) | Slovo v popisu trasy → způsob: zem, výkop → D; vzduch, lávka, rošt, žlab → E; trubka, lišta, chránička → B1; zateplení, izolace → A1; stěna, omítka, příchytky → C; neznámé → C | neuveden | bez označení | Potvrdit přiřazení skutečných uložení ke způsobům podle normy a výchozí způsob; říci, zda chybí další způsoby (kód zná jen A1, B1, C, D, E). | V |
| K5 | `model/calc.py:87` (`k_t` v `ampacity`) | Teplotní činitel PVC: 30 °C 1,0; 35 °C 0,94; 40 °C 0,87; 45 °C 0,79; 50 °C 0,71; zaokrouhlení teploty na 5 °C, bez interpolace; pod 30 °C vždy 1,0; nad 50 °C 0,71; stejný činitel i pro uložení v zemi (D) | ř. 86: „tab. B.52.14 pro PVC, orientační“ | ORIENTAČNÍ | Tabulka přepočtových činitelů pro teplotu okolního vzduchu (PVC, případně XLPE) v celém rozsahu teplot včetně teplot pod 30 °C; zvlášť činitele pro teplotu půdy (způsob D). Formát: teplota [°C] → činitel; uvést, zda se interpoluje. Pozn.: kontrola dnes volá výpočet vždy s 30 °C (`check_cables`, ř. 1501). | V |
| K6 | `model/calc.py:73` parametr `grouping` | 1,0 – seskupení kabelů se v žádné kontrole neuplatňuje | neuveden | předpoklad | Rozhodnout, zda seskupení zohlednit; pokud ano, tabulka činitelů (počet obvodů × způsob uložení). | V |
| K7 | `model/calc.py:77`–`81` | Průřez mimo řadu: Iz nejbližšího většího průřezu × poměr průřezů („lineární odhad“); nad 240 mm² bez výsledku | komentář „lineární odhad“ | odhad | Potvrdit, zda je lineární přepočet přípustný, nebo má být nestandardní průřez chybou; případně hodnoty nad 240 mm². | S |
| K8 | `model/calc.py:92` `min_cross`; `:1539`–`1542` | Průřez = nejmenší s Iz ≥ In jisticího přístroje; kontrola hlásí I > Iz a In > Iz; podmínka Ib ≤ In se nekontroluje | docstring: „ČSN 33 2000-4-43: In ≤ Iz“ | bez označení | Potvrdit úplnou sadu podmínek ochrany proti přetížení (článek, vydání) a zda se průřez volí podle In, nebo Ib. | V |
| K9 | `model/calc.py:1040` `I2_LIMIT`; `:1043` `conventional_trip_factor` | I2 ≤ 1,45·Iz; I2/In: jističe MCB/RCBO 1,45; MCCB 1,3; pojistky gPV 1,45; gG/gL ≤ 4 A 2,1, 4–16 A 1,9, ≥ 16 A 1,6; aM a neznámé – bez kontroly | ř. 1036–1039: „ČSN 33 2000-4-43, čl. 433.1“, „EN 60898“, „EN 60947-2“, „EN 60269-6“, „EN 60269-1, tab. 2“ | bez označení (citace neověřena) | Potvrdit mez 1,45 a článek; poměr I2/In pro každý typ přístroje s číslem tabulky / článku a vydáním; u pojistek gG celé rozdělení podle In (kód má tři pásma). Formát: typ přístroje, pásmo In [A] → I2/In. | V |
| K10 | `model/calc.py:1501` `du_limit_pct`; `generator/pv.py:139` `AC1_MAX_DROP_PCT` | Mez úbytku napětí 3 % – stejná pro AC i DC kabely; TZ tiskne „mez 3 % od rozvaděče k výrobně“ (`export/tz_data.py:534`) | neuveden | bez označení | Dovolený úbytek napětí pro AC přívod výrobny a pro DC stranu (norma / požadavek DS / zvyklost ENVO), k jakému napětí se vztahuje. | V |
| K11 | `model/calc.py:106` `voltage_drop` | ΔU = √3·I·R·cos φ (3f) nebo 2·I·R·cos φ (1f, DC); jen činná složka, cos φ = 1, reaktance se neuvažuje | docstring: „jen činná složka – orientační“ | ORIENTAČNÍ | Potvrdit, zda zjednodušení stačí; pokud ne, reaktance vedení [Ω/km] podle průřezu a cos φ. | V |
| K12 | `model/calc.py:18` `RHO_CU`, `RHO_AL` | 0,0225 a 0,036 Ω·mm²/m „při provozní teplotě ~70 °C“ | „(orientační)“ | ORIENTAČNÍ | Rezistivita Cu a Al a teplota vodiče, pro kterou se má úbytek počítat (i pro solární kabely s vyšší dovolenou teplotou). | V |
| K13 | `model/calc.py:974` `_wire_system`; `:1522` | Soustava podle názvů žil: L1–L3 → 3f 400 V; +/−, L+/L− → DC; jinak 1f 230 V. 3f = 3 zatížené vodiče (N se nepočítá), jinak 2 | neuveden | předpoklad | Potvrdit jmenovitá napětí pro úbytek a počet zatížených vodičů u 3f + N. | S |
| K14 | `model/calc.py:1519`; `:141` | DC napětí pro úbytek = počet modulů × Vmp; chybí-li Vmp, bere se 0,82·Voc | docstring ř. 137: „Chybějící Vmp = 0,82·Voc“ | odhad (neoznačeno) | Potvrdit referenční DC napětí pro úbytek; rozhodnout, zda náhradu 0,82·Voc povolit, nebo vyžadovat údaj z datasheetu. | V |
| K15 | `model/calc.py:999` `_source_current` | Proud DC kabelu stringu = 1,25·Isc; AC proud střídače = P/(√3·400 V) nebo P/230 V, cos φ = 1 | ř. 24: „ČSN 33 2000-7-712: dimenzování DC na 1,25·Isc“ | bez označení | Viz S3; pro AC: zda brát jmenovitý / maximální proud střídače z datasheetu a jaký cos φ. | V |
| K16 | `model/calc.py:1512` | Hliníkový kabel se pozná podle „AYKY“ nebo slova „AL“ v typu kabelu; izolace se nerozlišuje (vše jako PVC) | neuveden | předpoklad | Potvrdit, které typy kabelů ENVO používá a jaké tabulky pro ně platí (materiál, izolace). | S |

### 1.2 Stringy – napětí, teploty, proudy, pojistky

| ID | Kde v kódu | Současná hodnota | Zdroj podle kódu | Označení | Co dodat | Pr. |
|---|---|---|---|---|---|---|
| S1 | `model/calc.py:19` `T_MIN_DEFAULT`, `T_MAX_DEFAULT`; `:306` `design_temperatures` | −10 °C (nejnižší okolí pro Uoc), +70 °C (teplota článku pro Umpp) – když projekt nemá vlastní návrhové teploty | komentář: „nejnižší okolí (Uoc), teplota článku při plném slunci (Umpp)“; norma neuvedena | bez označení | Návrhové teploty pro Uoc a Umpp (norma / lokalita / standard ENVO), zda se přičítá rezerva. Formát: dvě teploty [°C] + zdroj. | V |
| S2 | `model/calc.py:156`–`161` `ModuleData.uoc`, `.ump`; `:150` `vmp_coeff` | Lineární přepočet od 25 °C: U(t) = U·(1 + k/100·(t − 25)); pro Uoc k = β_Voc; pro Umpp k = γ_Pmax − α_Isc, jinak β_Voc | neuveden (odvození v docstringu) | předpoklad | Potvrdit postup výpočtu Uoc při nejnižší teplotě a Umpp při nejvyšší teplotě podle normy (článek, vydání), referenční teplotu a zda je náhrada β_Voc pro Umpp přípustná. | V |
| S3 | `model/calc.py:24` `SAFETY_ISC`; `:352` `_current_issues` | 1,25·Isc proti Imax vstupu střídače; je-li zadán Isc max MPPT, porovnává se Isc **bez** činitele | „ČSN 33 2000-7-712: dimenzování DC na 1,25·Isc“ | bez označení | Potvrdit činitel a článek (vydání); kde všude se má použít (kabel, vstup střídače, přístroje) a zda platí i při porovnání s Isc max MPPT. TZ tiskne sloupec „1,25·Isc [A]“ (`export/tz_data.py:473`). | V |
| S4 | `model/calc.py:332` `_voltage_issues` | Uoc(t_min) ≤ Umax střídače a Umax systému modulu; Umpp(t_max) ≥ MPPT min; Umpp(t_min) ≤ MPPT max; žádná další rezerva | neuveden | bez označení | Potvrdit sadu podmínek a zda norma požaduje bezpečnostní činitel na Uoc nad rámec teplotního přepočtu. | V |
| S5 | `model/calc.py:21` `BETA_VOC_DEFAULT` | −0,27 %/K, když modul údaj nemá | „krystalický Si; z datasheetu modulu“ | bez označení | Rozhodnout, zda výchozí hodnotu povolit (údaj výrobce, ne norma), nebo chybějící koeficient hlásit. | S |
| S6 | `model/calc.py:782` `GPV_FUSE_SIZES`; `:786` `string_fuse_in` (ř. 796–798) | Řada In gPV: 10, 12, 13, 15, 16, 20, 25, 30, 32 A; výběr nejmenší In ≥ 1,5·Isc a ≤ 2,4·Isc, ≤ max. jištění modulu, ≤ max. In držáku | „IEC 62548, ETI Green Protect“; řada: „jmenovité proudy vložek gPV 1000 V DC (ETI Green Protect)“ | bez označení | Potvrdit oba činitele (článek, vydání IEC 62548 / odpovídající ČSN) a podmínku vůči max. jištění modulu; řada In je z katalogu výrobce – potvrdit. | V |
| S7 | `model/calc.py:783` `OPTIMIZER_FUSE_IN` | 25 A pro stringy s optimizéry | „standard ENVO 25 A“ | zvyklost | Potvrdit jako standard ENVO (není z normy). | V |
| S8 | `model/calc.py:1399` `DC_PATH_DEVICES` | Výčet přístrojů ve stringové cestě, jejichž Un DC (u svodiče Ucpv) se porovnává s Uoc(t_min) | neuveden | bez označení | Potvrdit, které přístroje a které jmenovité napětí se má s Uoc porovnávat. | S |
| S9 | `model/calc.py:852` `suggest_inverter_count` | Poměr DC/AC nejvýš 1,3 (doporučený počet střídačů v průvodci) | neuveden | bez označení | Potvrdit jako zvyklost ENVO. | N |

### 1.3 Selektivita

| ID | Kde v kódu | Současná hodnota | Zdroj podle kódu | Označení | Co dodat | Pr. |
|---|---|---|---|---|---|---|
| V1 | `model/calc.py:25` `SELECTIVITY_RATIO` | 1,6 – poměr In nadřazeného a podřazeného přístroje; výkaz tiskne „poměr ≥ 1,6“ (`export/reports.py:577`); omezuje vývody v HR (`generator/boards/mv.py`) | „orientační poměr In pro selektivitu MCB–MCB v přetížení“ | ORIENTAČNÍ | Potvrdit poměr a pro které kombinace přístrojů platí (jistič–jistič, pojistka–jistič, pojistka–pojistka, MCCB), nebo říci, že se má použít selektivní tabulka výrobce. | V |
| V2 | `model/calc.py:1558` `SELECTIVITY_DEVICES`; `:1621` `CHAIN_STRICT` | V rámci listu se poměr uplatní na jističe, RCBO, pojistky i pojistky HDS; v řetězci výrobna → HDS musí být nadřazené In ostře větší a poměr ≥ 1,6 se vyžaduje jen mezi dvěma jističi | neuveden (zvyklosti v komentářích) | bez označení | Potvrdit pravidla odstupňování jištění od střídače po HDS (norma / podmínky DS / zvyklost ENVO). | V |

## 2. `model/thermal.py` – oteplení rozvaděče

Výstupy: protokol o kusovém ověření (`export/docx_export.py:229`, řádek „Oteplení (IEC TR 60890, výpočet)“),
technická zpráva (`export/tz_data.py:510`, „Odhad oteplení dle IEC TR 60890“) a kontrola F7 `thermal_device`.
Verdikt se tiskne jako „vyhovuje / NEVYHOVUJE (orientačně)“. Docstring modulu: „ČSN EN 61439-1 čl. 10.10.4.3.1 /
IEC TR 60890:2014“; tabulky k a c jsou podle něj „převzaty z paměti (reprodukce tabulek IEC 60890 v aplikačních
příručkách výrobců)“.

| ID | Kde v kódu | Současná hodnota | Zdroj podle kódu | Označení | Co dodat | Pr. |
|---|---|---|---|---|---|---|
| T1 | `model/thermal.py:141` `K_LARGE_NO_VENTS` | 14 bodů Ae [m²] → k; Ae 1,25–12 m², k 0,524–0,08; lineární interpolace, mimo rozsah krajní hodnota | „IEC TR 60890 obr. 3 – konstanta k, skříň BEZ ventilačních otvorů, Ae > 1,25 m²“ | ORIENTAČNÍ, z paměti | Body křivky z obr. 3: Ae [m²] → k v celém rozsahu obrázku, dost hustě pro lineární interpolaci (uvést, zda jsou osy logaritmické); co platí mimo rozsah. | V |
| T2 | `model/thermal.py:146` `K_SMALL` | 19 bodů Ae → k; Ae 0,08–1,25 m², k 3,973–0,542; lineární interpolace | „IEC TR 60890 obr. 4 / tabulka – konstanta k pro Ae ≤ 1,25 m² (bez ventilace)“ | ORIENTAČNÍ, z paměti | Body z obr. 4 (je-li v normě tabulka, pak její hodnoty): Ae [m²] → k; dolní mez platnosti Ae. Pozn.: na hranici 1,25 m² mají dnešní tabulky skok (0,542 × 0,524) – ověřit. | V |
| T3 | `model/thermal.py:156` `C_LARGE_NO_VENTS` | 13 bodů f → c; f = h^1,35/Ab od 0,6 do 12, c 1,225–1,495; jediná křivka | „IEC TR 60890 obr. 6 … křivka pro samostatnou skříň volnou ze všech stran (nejvyšší c … na straně bezpečnosti)“ | ORIENTAČNÍ | Body všech křivek obr. 6 (podle způsobu instalace skříně): f → c; potvrdit definici f (jednotky h [m], Ab [m²]) a která křivka patří ke kterému způsobu instalace. | V |
| T4 | `model/thermal.py:161` `C_SMALL` | 7 bodů g → c; g = h/š od 0 do 3, c 1,00–1,45 | „IEC TR 60890 obr. 7 – činitel c pro Ae ≤ 1,25 m² podle g = h/š“ | ORIENTAČNÍ | Body z obr. 7: g → c v celém rozsahu; potvrdit definici g a zda obrázek rozlišuje způsob instalace. | V |
| T5 | `model/thermal.py:127` `B_FACTORS` | Činitel b (horní, spodní, přední, zadní, boky): volně stojící 1,4/0/0,9/0,9/0,9; nástěnná 1,4/0/0,9/0,5/0,9; zapuštěná 0,7/0/0,9/0,5/0,5; stojanová jako volně stojící | „IEC TR 60890 tab. 3“ (ř. 124–126) | „jisté“ (neověřeno) | Potvrdit tab. 3: činitel b pro každý druh plochy (volná / zakrytá horní, volné / zakryté boční, dno) a přiřazení čtyř typů montáže k řádkům tabulky; skříně řazené vedle sebe kód neřeší. | V |
| T6 | `model/thermal.py:137`–`138` `X_LARGE`, `X_SMALL`; `:136` `AE_LIMIT_M2` | Exponent x: 0,804 (Ae > 1,25 m²), 0,715 (Ae ≤ 1,25 m²); hranice 1,25 m² | docstring modulu ř. 12 | „jisté“ (neověřeno) | Potvrdit oba exponenty, hranici a na kterou stranu patří rovnost. | V |
| T7 | `model/thermal.py:152` `D_PARTITIONS_NO_VENTS`; `:431` `d_factor` | Počet vodorovných přepážek 0/1/2/3 → d 1,00/1,05/1,15/1,30; víc než 3 → 1,30; d se násobí i u malých skříní, ač komentář mluví jen o Ae > 1,25 m² | „skříně bez ventilačních otvorů, Ae > 1,25 m² (jisté)“ | „jisté“ (neověřeno) | Potvrdit tabulku d, rozsah platnosti (velké / malé skříně) a co platí pro více než 3 přepážky. Pozn.: počet přepážek nelze v GUI zadat – výstupy dnes počítají vždy s d = 1,00. | V |
| T8 | `model/thermal.py:493`–`494` | Δt0,5 = k·d·P^x; Δt1,0 = c·Δt0,5; P = ΣPv × (1 + přirážka) | docstring modulu | bez označení | Potvrdit vzorce a význam P (celkový ztrátový výkon ve skříni). | V |
| T9 | `model/thermal.py:292` `air_temperature` | Dolní polovina skříně: Δt0,5 (konstantně); od středu k hornímu okraji lineárně na Δt1,0; neumístěný přístroj: Δt1,0 | „podle profilu IEC TR 60890“; „norma tam teplotu dál snižuje, my ne“ | předpoklad | Průběh teploty vzduchu po výšce skříně podle normy (charakteristika mezi dnem, polovinou a horní částí) pro malé i velké skříně. | V |
| T10 | `model/thermal.py:446` `wiring_pct` | Přirážka 15 % k ΣPv na vnitřní vodiče a spoje (nelze v GUI změnit) | neuveden („výchozí 15 %“) | bez označení | Potvrdit zvyklost, nebo dodat postup určení ztrát vodičů (norma / tabulka). | V |
| T11 | `model/thermal.py:390` `device_power_loss`; `:361` `layout_inputs`; `model/project.py:499`–`501` | Ztráty × RDF² (RDF = Ib/In), výchozí RDF 0,8; výchozí teplota okolí 35 °C | neuveden | bez označení | Potvrdit přepočet ztrát druhou mocninou zatížení, výchozí RDF (má-li norma tabulku podle počtu obvodů, pak ji) a teplotu okolí pro průkaz. | V |
| T12 | `model/thermal.py:134` `K_PLASTIC_PENALTY` | Chladicí plocha plastové skříně ÷ 1,15 | „předpoklad EnvoCAD, ne norma“ | předpoklad | Rozhodnout, jak počítat plastové skříně (norma / údaj výrobce skříně), nebo předpoklad schválit. | V |
| T13 | `model/thermal.py:408` | Nezadaná hloubka skříně = 150 mm | neuveden | předpoklad | Potvrdit, nebo vyžadovat zadání. | S |
| T14 | `model/thermal.py:44` `LOSS_PER_A_PER_POLE` | Odhad ztrát [W/A na pól]: jistič 0,09; RCBO 0,11; chránič 0,04; MCCB 0,06; vypínače a odpínače 0,03; stykač 0,08; pojistka 0,15 | „ORIENTAČNÍ střední hodnoty z katalogů“ | ORIENTAČNÍ, odhad | Nejde o normu: buď schválit odhady, nebo doplnit `p_loss_w` k artiklům (fakta z datasheetů s odkazem – viz `docs/SOURCES.md`). Má-li norma tabulku nejvyšších ztrát přístrojů, uvést ji. | V |
| T15 | `model/thermal.py:53` `FIXED_LOSS_W` | Pevné ztráty [W]: svodič 0,5; elektroměr 2,0; stykač / cívka 2,5; síťová ochrana 3,0 | „ORIENTAČNÍ“ | ORIENTAČNÍ, odhad | Totéž co T14. | V |
| T16 | `model/thermal.py:66`–`67` `DEFAULT_T_MAX_C`, `DEFAULT_T_MIN_C` | +40 °C a −5 °C – předpokládané meze teploty okolí přístroje bez údaje výrobce | „ČSN EN 60947-1 čl. 6.1.1, ČSN EN 60898-1: okolí do +40 °C, průměr za 24 h 35 °C“; dolní mez „týchž norem“ | bez označení (citace neověřena) | Potvrdit obě meze a články v obou normách (vydání). | V |
| T17 | `model/thermal.py:68` `DEVICE_REF_C` | 40 °C – nad ní verdikt upozorní na odlehčení (derating); jedna hodnota pro všechny přístroje | komentář ř. 64: „referenční teplota kalibrace MCCB dle EN 60947-2 (MCB dle EN 60898 je 30 °C)“ | bez označení | Potvrdit referenční teploty kalibrace pro MCB a MCCB (článek) a rozhodnout, zda je rozlišovat. | V |
| T18 | `model/thermal.py:71` `THERMAL_SKIP_SYMBOLS` | Řadové svorky se bez vlastního údaje nehodnotí | komentář: „EN 60947-7-1, běžně do 100–130 °C“ | bez označení | Potvrdit mezní teploty svorek (článek) a zda je správné je vynechat. | S |
| T19 | `model/thermal.py:489` (`vents`) | Skříň s ventilačními otvory se počítá jako bez otvorů (GUI volbu nemá) | „obr. 5 neimplementován – výsledek na straně bezpečnosti“ | chybí | Jen má-li se podporovat: obr. 5 (k pro skříně s otvory podle plochy otvorů) a odpovídající d, c, x. | S |
| T20 | `model/thermal.py` (celý výpočet) | Skříň = jeden prostor; podmínky použitelnosti metody se nekontrolují | neuveden | chybí | Výčet podmínek platnosti metody IEC TR 60890 (co musí rozvaděč splňovat, aby šla použít) a postup pro skříně s více sekcemi. | V |

## 3. `model/ratings.py`, `dc_system.py`, `checks.py`, `wiring.py`

### 3.1 Zkratové proudy a napětí (`ratings.py`)

| ID | Kde v kódu | Současná hodnota | Zdroj podle kódu | Označení | Co dodat | Pr. |
|---|---|---|---|---|---|---|
| R1 | `model/ratings.py:126` `C_MAX` | 1,05 – napěťový součinitel pro nejvyšší zkratový proud v sítích nn | „ČSN EN 60909-0, tab. 1“ | bez označení (citace neověřena) | Potvrdit hodnotu c_max pro síť 230/400 V, číslo tabulky a vydání. | V |
| R2 | `model/ratings.py:129` `transformer_ik_ka`; `:21` `U_NN` | Ik = c_max·Sn/(√3·U·uk/100), U = 400 V; tvrdá síť vn, bez impedance vedení („horní odhad“); jde do TZ | neuveden (docstring: „horní odhad“) | odhad | Potvrdit vzorec a napětí (jmenovité × naprázdno) podle ČSN EN 60909-0; zda je takový horní odhad v TZ přijatelný. | V |
| R3 | `model/ratings.py:207` `short_circuit_findings` | Icu < Ik → varování; Icw rozvaděče < Ik → chyba; Icu < Icw (bez Ik) → varování; kaskáda / záložní jištění se nehodnotí; `ipk` se nepoužívá | neuveden | bez označení | Potvrdit pravidla (Icu nebo Ics proti Ik; Icw a doba; Ipk) a příslušné články norem pro přístroje a rozvaděče. | S |
| R4 | `model/ratings.py:20` `SPD_UC_FACTOR`; `:249` `spd_uc_required` | Uc ≥ 1,1·Uo (TN, TT); v IT √3·Uo; Uo výchozí 230 V (`:19`) | „ČSN 33 2000-5-534 … zjednodušeně L–PE“ | bez označení (zjednodušení) | Požadované Uc podle uspořádání sítě a způsobu zapojení SPD (číslo tabulky, vydání); kód nerozlišuje zapojení L–N / N–PE. | S |
| R5 | `model/ratings.py:284`–`293` (`spd_findings`) | Svodič DC: Ucpv ≥ Uoc stringu při t_min (chyba jen se zadanou návrhovou t_min, jinak informace); Up ≤ Uw střídače (varování); bez rezervy | neuveden | bez označení | Potvrdit pravidla výběru svodiče DC (norma, článek) a zda se požaduje rezerva nad Uoc. | S |
| R6 | `model/ratings.py:31` `_T1`; kód `spd_lps` | Objekt s jímací soustavou a svodič bez typu 1 → informace | neuveden | bez označení | Potvrdit požadavek a normu. | S |
| R7 | `model/ratings.py:420` (`un_findings`) | Un přístroje ≥ napětí sítě (3f: √3·Uo zaokrouhleno na 10 V) | neuveden | bez označení | Potvrdit pravidlo, případně toleranci. | S |

### 3.2 Napěťová soustava DC (`dc_system.py`)

| ID | Kde v kódu | Současná hodnota | Zdroj podle kódu | Označení | Co dodat | Pr. |
|---|---|---|---|---|---|---|
| D1 | `model/dc_system.py:20`–`21` `SYSTEMS`, `DEFAULT_SYSTEM` | Soustavy 1000 V a 1500 V DC, výchozí 1000 V; TZ tiskne „max. 1000 / 1500 V DC“ | neuveden | bez označení | Potvrdit obě hranice a normu, ze které plynou. | V |
| D2 | `model/dc_system.py:52` `spd_ucpv`; `library/components.py:38` `ucpv_v` | Ucpv se čte z atributu, artiklu nebo poznámky; Uc se za Ucpv nebere | `components.py:37`: „EN 61643-31“ | bez označení | Potvrdit normu a definici Ucpv a že Uc nelze použít jako náhradu (při výběru artiklu generátorem se dnes Uc jako záloha bere). | S |
| D3 | `model/dc_system.py:218` `choose` | Přesáhne-li Uoc stringu 1000 V a střídač i katalog to dovolí, zvolí se automaticky sada 1500 V | neuveden | rozhodnutí | Oborové rozhodnutí – potvrdit. | V |

### 3.3 Kontroly F7 (`checks.py`)

| ID | Kde v kódu | Současná hodnota | Zdroj podle kódu | Označení | Co dodat | Pr. |
|---|---|---|---|---|---|---|
| C1 | `model/checks.py:640` a `generator/spec.py:34` `GRID_PROTECTION_KWP`; `export/tz_data.py:279` | 30 kWp instalovaného výkonu DC – nad hranicí se požaduje síťová ochrana (lze přepsat firemním standardem) | neuveden („F2“) | bez označení | Hranice a její zdroj (podmínky provozovatele DS / norma), zda se vztahuje k výkonu DC, nebo AC, a zda se liší podle napěťové hladiny. | V |
| C2 | `model/checks.py:643` `FVE_FUSE_MAX_BREAKER_IN`; `generator/boards/house_board.py:26` `FVE_FUSE_MIN_IN` | Vývod FVE do 80 A včetně musí být jistič, pojistkový odpínač až nad 80 A | „rozhodnutí 4“ (`docs/NAVRH_TOPOLOGIE.md`) | zvyklost | Potvrdit zdroj (zvyklost ENVO / požadavek DS). | V |
| C3 | `model/checks.py:930` `n_pe_join_findings` | Spojení N a PE v rozvaděči sítě TN-S → varování | text hlášky, norma neuvedena | bez označení | Potvrdit pravidlo a článek normy. | S |

V `checks.py` nejsou žádné tabulky z norem; ostatní prahy přebírá z `calc`, `ratings` a `thermal`.

### 3.4 Vnitřní vodiče rozvaděče (`wiring.py`)

| ID | Kde v kódu | Současná hodnota | Zdroj podle kódu | Označení | Co dodat | Pr. |
|---|---|---|---|---|---|---|
| W1 | `model/wiring.py:198` `IN_TO_CROSS`; tiskne `export/xlsx_export.py:133` | In jištění ≤ 10/16/25/32/50/63/80/100/125/160 A → průřez 1,5/2,5/4/6/10/16/25/35/50/70 mm²; nad 160 A určí projektant | „ORIENTAČNÍ – vnitřní vodiče Cu/PVC ve žlabu (ČSN EN 61439-1 příl. H); schválí projektant“ | ORIENTAČNÍ | Tabulka z příl. H (potvrdit, že je to správný zdroj, a vydání): průřez [mm²] → dovolený proud [A] pro uložení ve žlabu, s podmínkami (teplota uvnitř skříně, počet zatížených vodičů, izolace); zda se má porovnávat s In jištění. | V |
| W2 | `model/wiring.py:304` `spd_pe_cross` | PE od svodiče 6 mm² Cu; SPD typu 1 v objektu s jímací soustavou 16 mm² Cu | docstring, norma neuvedena | bez označení | Nejmenší průřezy vodičů k SPD podle typu svodiče – norma, článek, vydání. | V |
| W3 | `model/wiring.py:881` `SPD_BRANCH_MAX_MM` | Přívod k SPD + PE svodiče dohromady nejvýš 0,5 m | „ČSN EN 62305-4, 61643-32“ | bez označení (citace neověřena) | Potvrdit délku, co se do ní počítá, správnou normu a článek; zda platí i pro svodiče DC. | V |
| W4 | `model/wiring.py:52`–`54` `WIRING_DEFAULTS` | Nejmenší silový průřez 1,5 mm², řízení 1 mm², DC žíly 6 mm² | neuveden | bez označení | Potvrdit nejmenší průřezy (norma / standard ENVO). | V |
| W5 | `model/wiring.py:202` `FERRULE_DIN46228` | Průřez 0,5–50 mm² → barva a délka dutinky | „Dutinky dle DIN 46228 (barevný kód DIN)“ | bez označení | Potvrdit barvy a délky podle zvolené barevné řady. | S |
| W6 | `model/wiring.py:187` `TERMINAL_RULE` | Číslování svorek L1 = 1/2, L2 = 3/4, L3 = 5/6, N = 7/8 | „dle IEC 60947-1“ | bez označení | Potvrdit značení svorek a článek. | S |
| W7 | `model/wiring.py:216` `FLEXIBLE_WIRE_TYPES` | Ohebné vodiče: typy „-K“ (třída 5), „-F“, CYA, LGY, LIY | „třída 5 dle HD 361“ | bez označení | Potvrdit výčet a normu. | N |

## 4. `generator/` – jištění, průřezy, připojení k síti

Generátor výpočty stringů (Uoc při t_min, gPV, Ucpv svodiče DC, Icu/Icw) sám nedělá – volá `model/calc.py`,
`model/dc_system.py` a `model/ratings.py` (oddíly 1 a 3). Vlastní má pravidla dimenzování na straně AC a vn.
Žádná konstanta generátoru není označená jako orientační; většina odkazuje jen na „rozhodnutí“
(`docs/NAVRH_TOPOLOGIE.md`), ne na normu.

| ID | Kde v kódu | Současná hodnota | Zdroj podle kódu | Označení | Co dodat | Pr. |
|---|---|---|---|---|---|---|
| G1 | `generator/currents.py:24` `BREAKER_FACTOR` | Jistič přívodu střídače ≥ 1,25 × max. AC proud střídače | neuveden („review F2, D1“) | bez označení | Zdroj činitele (norma / doporučení výrobců střídačů / zvyklost ENVO). | V |
| G2 | `generator/currents.py:22`–`23` `AC3_BREAKER_SIZES`, `AC1_BREAKER_SIZES` | 3f: 10–250 A (15 hodnot); 1f: 10–63 A (9 hodnot) | neuveden | bez označení | Potvrdit řady jmenovitých proudů (norma / sortiment) a horní meze. | V |
| G3 | `generator/currents.py:25` `U_3F`, `U_1F`; `generator/boards/mv.py:37` `U_LV` | I = P/(√3·400 V), 1f P/230 V; cos φ se neuvažuje (kW = kVA) | neuveden | bez označení | Potvrdit napětí a zda počítat se zdánlivým výkonem / cos φ. | V |
| G4 | `generator/currents.py:26` `MAIN_SWITCH_MIN` | Hlavní vypínač rozvaděče FVE nejméně 125 A | „výchozí“ | bez označení | Potvrdit pravidlo (zvyklost ENVO). | V |
| G5 | `generator/currents.py:96` `fve_out_in` | Vývod FVE = nejbližší In ≥ max(Σ proudů střídačů, největší jistič střídače) | neuveden | bez označení | Potvrdit pravidlo dimenzování vývodu (činitel, soudobost). | V |
| G6 | `generator/pv.py:138` `AC1_MIN_CROSS`; `:162` | Kabel 1f střídače: nejméně 2,5 mm², uložení B1, 2 zatížené žíly | neuveden | bez označení | Potvrdit nejmenší průřez a uložení. | V |
| G7 | `generator/pv.py:305`–`338`; `generator/chain.py:93`, `:96` | Výchozí uložení: DC kabely E, AC kabel střídače B1, kabel k síti D, ostatní C | neuveden | bez označení | Potvrdit výchozí způsoby uložení (určují Iz v kontrole i TZ). | V |
| G8 | `generator/chain.py:135` | Vodič PE k HOP „CYA 16“, 16 mm² | neuveden | bez označení | Potvrdit průřez a normu / článek. | V |
| G9 | `generator/boards/eps.py:123` | Chránič zálohy (EPS): 30 mA, typ A | docstring: „chránič 30 mA“ | bez označení | Typ a IΔn chrániče na zálohovaném výstupu střídače (norma / požadavek výrobce střídače). | V |
| G10 | `generator/boards/rfve_ac.py:210` `GP_FUSE_IN` | Jištění měřicího vstupu síťové ochrany: jistič 4p B6 | „požadavek na mustr, D5“ | zvyklost | Potvrdit zdroj požadavku. | V |
| G11 | `generator/boards/meter_board.py:29` `MCB_MAX_IN` | Hlavní jistič do 125 A jako MCB, výš MCCB | neuveden | bez označení | Potvrdit hranici (sortiment / zvyklost). | S |
| G12 | `generator/boards/mv.py:29`, `:31` `LV_BREAKER_SIZES`, `LV_FEEDER_SIZES` | Řada 100–4000 A (hlavní jistič HR); vývody navíc 16–80 A; hlavní jistič = nejbližší In ≥ In transformátoru, bez činitele (`:117`–`120`) | neuveden | bez označení | Potvrdit řady a pravidlo výběru hlavního jističe. | V |
| G13 | `generator/boards/mv.py:32` `CT_PRIMARY_SIZES`; `:302`, `:398`; `meter_board.py:101` | Primáry MTP 5–4000 A, sekundár 5 A; třídy MTP nn 0,5S, vn 0,2S, MTN 0,2; zátěž 5 VA | „normalizovaný primár“; třídy neuvedeny | bez označení | Normalizovaná řada primárních proudů; třídy přesnosti a zátěž podle podmínek měření provozovatele DS. | V |
| G14 | `generator/boards/mv.py:34`–`35` `VN_FUSE_SIZES`, `VN_FUSE_FACTOR` | Pojistky vn 6,3–100 A; In pojistky ≈ 1,8 × In transformátoru na vn | „tabulky výrobců pojistek – ověřit“ | k ověření | Pravidlo / tabulka výběru pojistek vn podle Sn a Un transformátoru (výrobce, norma). | V |
| G15 | `generator/boards/mv.py:36` `VN_BREAKER_FROM_KVA`; `:420` | Nad 1000 kVA vypínač vn s ochranou „nadproudová 50/51“, jinak odpínač s pojistkami | neuveden | bez označení | Potvrdit hranici a typ ochrany (podmínky DS / zvyklost). | V |
| G16 | `generator/boards/mv.py:49` `U_MV_RANGE` | 1–52 kV, mimo rozsah chyba zadání | „ČSN EN 50160: 1 kV < Un ≤ 35 kV; řada Um do 52 kV“ (komentář a rozsah nesouhlasí) | bez označení | Potvrdit rozsah napětí vn, který má generátor přijmout. | S |
| G17 | `generator/pv.py:137` `AC1_CONDUCTORS`; `library/templates.py:15`–`16` | Označení žil L1, L2, L3, N, PE; DC L+, L− | „ČSN EN 60445“ | bez označení | Potvrdit označení a vydání normy. | S |
| G18 | `generator/boards/rfve_dc.py:93` | Síť DC rozvaděče „DC IT“ | neuveden | bez označení | Potvrdit označení sítě DC strany. | S |
| G19 | `generator/boards/mv.py:324`; `generator/spec.py` (`DEFAULT_SPEC`) | Typ SPD: HR „T1“, rozvaděče FVE „T1+T2“ (AC i DC) | neuveden | bez označení | Pravidlo volby typu SPD na AC a DC straně. | V |
| G20 | `generator/context.py:29` `BATTERY_CABLE`; `DEFAULT_SPEC` v `generator/spec.py` | Výchozí kabely: baterie H1Z2Z2-K 1×25, DC H1Z2Z2-K 1×6, AC CYKY-J 5×16, síť CYKY-J 5×35 | „výchozí“ | bez označení | Výchozí hodnoty ENVO – potvrdit (průřez AC se jinak dopočítává podle K8). | N |

## 5. Texty s odkazem na normu ve výstupech

| ID | Kde v kódu | Současný text / hodnota | Co dodat | Pr. |
|---|---|---|---|---|
| X1 | `export/docx_export.py:21` `ROUTINE_CHECKS`; `:202`, `:253` | Položky kusového ověření „11.2“–„11.10“ s názvy a způsoby ověření, mj. „spojitost PE ≤ 0,1 Ω“, „izolační odpor ≥ 1 000 Ω/V (min. 1 MΩ) nebo zkouška 2 U + 1 000 V“; hlavička „dle ČSN EN 61439-1 ed. 3, čl. 11“ | Potvrdit vydání, čísla článků, výčet zkoušek a všechny tři limity (hodnota + článek). | V |
| X2 | `export/tz_data.py:534` | „Zatížitelnost Iz dle ČSN 33 2000-5-52 (Cu, PVC, 30 °C) – tabulkové hodnoty orientační; úbytek napětí činný, mez 3 % …“ | Po dodání K1–K12 upravit znění (navazující issue). | V |
| X3 | `export/docx_export.py:229`; `export/tz_data.py:510` | „Oteplení (IEC TR 60890, výpočet)“, „Odhad oteplení dle IEC TR 60890“ | Po dodání T1–T20 rozhodnout, zda smí protokol uvádět výpočet jako průkaz. | V |
| X4 | `export/xlsx_export.py:126`; `export/reports.py:683` | „Návlečky (ČSN EN 62491)“ | Potvrdit normu pro značení vodičů a kabelů. | N |
| X5 | `export/docx_export.py:225`–`227` | Výchozí „3×400/230 V, 50 Hz“ a síť „TN-S“, když rozvaděč údaj nemá | Rozhodnout, zda výchozí texty v protokolu ponechat. | S |

## Nesrovnalosti v kódu zjištěné při soupisu

Neopravují se zde (mimo rozsah issue #79) – jen aby je člověk při ověřování měl na očích:

- `model/calc.py`: komentář u `IZ_3` uvádí „tab. B.52.4/B.52.5“, docstring modulu „tabulky A.52 … (B.52.x)“.
- `model/calc.py:352`: činitel 1,25 se použije jen bez zadaného Isc max MPPT; se zadaným se Isc porovnává bez činitele.
- `model/thermal.py`: tabulky k mají na hranici Ae = 1,25 m² skok (0,524 × 0,542); činitel d se používá i u malých
  skříní, ač ho komentář omezuje na Ae > 1,25 m²; komentář uvádí kalibraci MCB při 30 °C, kód má jednu hodnotu 40 °C.
- `model/thermal.py`: počet přepážek, ventilační otvory, přirážku na vodiče ani způsob instalace pro křivku c
  nelze v GUI zadat.
- `generator/boards/mv.py:49`: komentář „Un ≤ 35 kV“, rozsah přijímá až 52 kV.
- `model/dc_system.py`: při výběru artiklu svodiče se jako záloha bere Uc, kontrola F7 Uc za Ucpv nebere.
- `model/wiring.py:881`: u délky přívodů SPD je uvedena „61643-32“ bez předpony normy.
