# Roadmap

## v0.1 – MVP: jednopólové schéma FVE  ← tento repozitář
- [x] Datový model (symbol, element, vodič, list, projekt), JSON projekt
- [x] Startovní knihovna symbolů FVE (~12 symbolů)
- [x] Import symbolů z DXF
- [x] Editor: vkládání z knihovny, posun, rotace, kreslení vodičů port→port, snap na mřížku, undo/redo
- [x] Panel vlastností (atributy elementu/vodiče)
- [x] Uložit/načíst projekt
- [x] Export DXF, PDF
- [x] Tmavý režim
- [x] Dialog parametrů při vložení prvku/vodiče
- [x] Rámeček a popisové pole listu (šablona ENVO) – logo doplnit po dodání
- [ ] Příkazový řádek (styl ZWCAD/CADCraft): každá akce = příkaz, ovladatelné i z agentů
- [x] Automatické číslování označení (T1, F1, Q1…) s kontrolou duplicit – nové prvky a kopie dostanou další volné číslo, F7 hlásí duplicity, Úpravy → Přečíslovat označení (podle polohy, jen chybějící/duplicitní nebo vše, kontakty s cívkou, 10/2026)

## v0.2 – Knihovna a výkazy
- [ ] Editor symbolů (porty, atributy) přímo v GUI
- [x] Artikly: CSV formát, validátor, výběr v dialogu prvku, propsání parametrů, skříně z knihovny
- [x] Data z PDF katalogů: OEZ Minia + 3VA + OPVP + RZA, Eaton xPole/xComfort, Schneider skříně, BMR (460 artiklů)
- [ ] Doplnit: ABB, FV moduly, SolarEdge/Fronius/GoodWe, Pv pro 3VA (OEZ „3VA Parametry“), OPVF10 DC – z dalších PDF (web je v prostředí blokovaný)
- [ ] Knihovna → program (analýza 10/2026): 222 artiklů bez rozměrů/modulů, 138 z 266 jističů/chráničů bez Pv, 0 footprintů
  - [ ] rozměry a Pv z Katalogu Minia a „3VA Parametry“ (PDF od uživatele), rozměry svorek Bečov z technických listů
  - [ ] svorkovnice v rozložení: šířka = `width_mm` artiklu × počet svorek (+ koncové desky), místo ručních modulů
  - [ ] generické footprinty podle kategorie a rozměrů (kompaktní jistič = obdélník š×v, svorka = úzký obdélník), ne jen moduly
  - [ ] kontroly z artiklů: In jističe vs. průřez vodiče (základní tabulka), Icu vs. Icw rozvaděče, Uc svodiče vs. síť
- [x] Značky z QElectroTech (673), importéry EPLAN CSV/XML/DXF, pluginy a uživatelské balíčky
- [ ] BMEcat/ETIM importér (volná data výrobců)
- [ ] Footprinty z DXF výrobců (OEZ, Hager) a editor portů importovaných symbolů
- [ ] Ceny v artiklech + výkaz s cenami
- [x] Výkaz materiálu (.xlsx) a seznam kabelů z modelu – Výkaz materiálu, Kabely, Kabelový plán; nově Kabely a vodiče k objednání (metry kabelů podle typu, vodiče rozvaděče, dutinky; 10/2026)
- [ ] Hromadný import DXF knihoven výrobců (SMA, Huawei, SolarEdge, Eaton, Schneider, OEZ…)

## v0.2 – Rozvaděče  ← hotovo v základu
- [x] List rozvaděče z bloku, šablony AC/DC
- [x] Pohled rozložení: DIN lišty, moduly, přetahování
- [x] Výkazy xlsx (přístroje, BOM, kabely, svorkovnice, štítky), protokol kusového ověření docx
- [ ] Šablona ENVO pro protokol (loga, hlavička) – doplnit po dodání .docx
- [x] Parametry skříně v panelu rozložení, odhad oteplení (IEC 60890)
- [ ] Rozměry a ztrátové výkony přístrojů z artiklu (ne ručně v atributech `modules`, `p_loss_w`)
- [x] Oteplení: tabulky IEC 60890 (k, c, d) – křivky k a c ověřit proti normě; [ ] ventilace (obr. 5), přepážky v GUI

## v0.6 – Vícepól  ← hotovo v základu
- [x] Vícepólový pohled nad stejným listem (Ctrl+M / Ctrl+J), žíly z `Wire.conductors`, přiřazení svorek per žíla (`Wire.terminals`, Ctrl+T)
- [x] Automatické číslování svorek na svorkovnicích (Úpravy → Očíslovat svorky)
- [x] Svorkovnice jako v EPLAN: skupiny svorek s čísly, můstky (dialog, vícepól, JPS, výkaz); šablony bez sběrnice
- [ ] Artikl svorky → šířka v rozložení (svorkovnice na DIN liště podle `width_mm`), můstky jako artikl (ZQV…) do BOM
- [x] Vlastní rozmístění ve vícepólu: automatické svorkové schéma + posun myší
- [ ] Ruční lomy žil ve vícepólu, zalomení dlouhých řad svorek na další list
- [ ] Vícepólové značky z knihovny (QET `qet.ap.*`) místo opakování jednopólové značky; společná spoušť/vazba pólů
- [ ] Export DXF vícepólu (PDF už funguje)

## v0.4 – Vícelistové projekty a dokumentace
- [x] Vazba přívod/vývod rozvaděče ↔ vodič JPS (křížový odkaz, kabel jen jednou)
- [x] Křížové odkazy potenciálů mezi listy JPS – hotovo 10/2026: přerušovací body se stejným označením jsou v `potential.nets` jeden potenciál (dvojice, řetěz, hvězda)
- [ ] Generování částí TZ/DSPS z modelu (šablony)
- [ ] Sdílená knihovna pro celé ENVO (PostgreSQL nebo sdílený soubor)

## Nad rámec EPLAN – hotovo 10/2026
- [x] Výpočty z modelu (stringy, Iz, In ≤ Iz, úbytky, selektivita) v kontrole a výkazu
- [x] Průvodce / specifikace JSON → projekt (rozhraní pro agenty), porovnání revizí → změnový list, TZ docx, data pro DS
- [x] Autosave, poslední projekty, PDF A4, štítky CSV, QR v popisovém poli, sdílená knihovna, firemní standard
- [ ] Slovenská mutace výstupů (odloženo na přání)
- [ ] Výpočty: tabulky Iz ověřit proti normě, seskupení kabelů, teplota půdy; selektivita podle křivek výrobců
- [ ] Průvodce: DC rozvaděč, baterie, více AC rozvaděčů, výběr modulu/střídače z knihovny (dnes ručně)

## Proti EPLAN (analýza 10/2026) – zbývá
- [x] Potenciály: T-odbočka vodiče do vodiče, sledování potenciálu přes svorky a můstky, kontrola N/PE (10/2026)
- [ ] Funkční šablony artiklů (střídač → porty podle MPPT, jistič → příslušenství), přiřazení příslušenství k rámu – částečně: střídač → porty podle MPPT z artiklu (makra v2 / průvodce), jistič → příslušenství makrem
- [x] **Bloky typů střídačů** (10/2026: pás svorek záloha/BMS/METER/RS485/LAN/DI/DRM/RSD podle profilu řady – Huawei, SolaX, GoodWe, Growatt, Sigenergy, SolarEdge; `model/inverter_io.py`, atribut `io`; zbývá: piny ověřit z návodů, katalog Sigenergy/Growatt/SolarEdge, měřicí smyčka/NA ochrana jako makra): každý typ střídače jako blok s vlastními svorkami – DC vstupy, AC, baterie, komunikace (RS485, Ethernet, CAN), DRMS / řízení výkonu (RTU, NS ochrana), měřicí smyčka – z katalogu `inverters.csv`; dnes má střídač jen DC1…DCn, AC (a BAT)
- [ ] Rozložení jako výkres: montážní deska, žlaby a lišty podle artiklu s délkami, vrtací plán, výkaz montážního materiálu
- [ ] Vícepatrové svorky, N-odpojovací svorky jako druh (svorkovnice přes více stran – hotovo 10/2026 stránkováním vícepólu)
- [x] Makra (oblíbené sestavy) – hotovo 10/2026; zbývá: kopírování celého listu, hromadné přečíslování, editor značek v GUI
- [ ] Štítky ve formátu tiskáren (Brady/Partex), výkaz artiklů po dodavatelích s objednacími čísly
- [ ] Číslování stran celé dokumentace i v rámečku listů (dnes list x/y projektu), logo ENVO v popisovém poli
- [ ] Přerušovací body v zapojovacím seznamu jako průchod (potenciál pokračuje), vodič z vodiče

## Z rešerše EPLAN 2026 (10/2026)
Pořadí = priorita. Body 1, 2 a 5 jsou nejlevnější start.
- [x] **Strukturní označení IEC 81346** (`=` funkce, `+` umístění, `-` přístroj): centrální správa jako v EPLAN, plné označení `+RS1-F3` ve výkazech a štítcích – změna formátu (návrh `architekt`, `FORMAT_VERSION` + migrace) – hotovo 10/2026: formát v8, `Project.structures`, `Sheet.func/loc`, override `func/loc` u prvku, dialog Projekt → Strukturní označení, plné označení ve výkazech a štítcích (`model/designation.py`)
- [x] **Kontrola označení vs. funkce** (EPLAN P017003): `function_class` (F, Q, T…) v JSON symbolu, pravidlo v `model/checks.py`, kontrola délky a povolených znaků; podklad pro automatické číslování – hotovo 10/2026: `function_class` (nepovinný klíč, bez verze symbolu), kódy `ref_syntax`, `ref_chars`, `ref_length`, `ref_class` v kontrole F7; automatické číslování podle tříd zatím ne
- [x] **Zrcadlení kontaktů** cívka ↔ kontakty (tabulka pod cívkou s odkazem list/sloupec), křížové odkazy přerušovacích bodů hvězda/řetěz – NS ochrana, stykače řízení výkonu, RTU – hotovo 10/2026: zrcadlo jako tabulka pod hostitelem (`model/xref.py`), kontaktní obraz `contacts`, přerušovací body řetěz a hvězda (`star_source`), kontroly `contact_dup`, `contact_count`, `contact_unknown`, `contact_image_syntax`, `interrupt_star_multi`. Záměrně vynechány (YAGNI): vícepól, skok kliknutím z řádku zrcadla, přepínací kontakt
- [x] **Makra se zástupnými proměnnými** (`#In`, `#typ_stridace`, `#pocet_MPPT`) a sadami hodnot; průvodce skládá schéma z maker (EPLAN eBuild) – řeší i „Funkční šablony artiklů“ – hotovo 10/2026: makra v2 (`docs/design/makra_promenne.md`) s deklarovanými proměnnými `{x}`, sadami hodnot, podmínkou `when`, opakováním `repeat` a vazbou na artikl (`type: component` + `from`, `component_id` → `apply_to`); dialog proměnných při vložení, jedno undo; průvodce bere makro a sadu ze specifikace a doplní atributy střídače z artiklu. Záměrně vynechány: aritmetika ve výrazech, vnořená makra, skládání JPS z maker, výběr makra/sady v dialogu průvodce, sloupec `macro` u artiklu (jen rezervován)
- [x] **Revize ve výkresu**: označení změn z `model/diff.py` přímo v listu (obláček/trojúhelník s číslem revize), revize v popisovém poli, uzavření revize listu – hotovo 10/2026: trojúhelníky se značkou revize v editoru, PDF a DXF (vrstva `REVIZE`), revize listu v popisovém poli, uzavření revize = měkký zámek (kontrola `rev_closed_changed`). Záměrně vynechány: obláček a značky ve vícepólu (YAGNI)
- [x] **Připomínkování (redlining)**: vrstva poznámek v projektu se stavem otevřeno/vyřešeno, export jako anotace do PDF (EPLAN eVIEW) – hotovo 10/2026: `Project.notes` (formát v9 + migrace), nástroj Kreslit → Připomínka (bod / oblast), dialog, Navigátor → Připomínky (filtr, hledání, skok), Zobrazit → Připomínky, export PDF jako anotace (pypdf) a DXF vrstva `PRIPOMINKY`, dotaz při uzavření revize, kontroly `note_open`, `note_orphan`. Záměrně vynechány (YAGNI): vlákna odpovědí, import komentářů z PDF, vícepól, obláček
- [x] **Výrobní data rozvaděče**: zapojovací seznam s délkami z rozložení, barvou, průřezem, koncovkou/dutinkou (xlsx) – hotovo 10/2026: `model/wiring.py` (návrh `docs/design/vyrobni_data.md`), výkaz „Výrobní zapojovací seznam“ (mimo PDF dokumentaci), `export_production_xlsx` s listem Parametry, odvozené svorky přístrojů 1/2 → 1…6, délky po žlabech z rozložení, dutinky DIN 46228; formát v9 beze změny. GUI (atributy vodiče, parametry skříně, položka menu) dodělává gui-dev
- [x] **Generovat skutečné jednopólové schéma** po vytvoření blokového schématu a rozvaděčů (požadavek 17. 10. 2026) – hotovo 10/2026: `model/single_line.py` odvozuje strom od DS přes bloky rozvaděčů do jejich listů (rámečky rozvaděčů, přípojnice, kabely, elektroměr u MTP, konec u střídačů), kreslicí seznam `Prim` pro scénu (`ui/single_line_view.py`, Zobrazit → Jednopólové schéma), PDF dokumentaci a DXF; generátor umí **přípojku VN** (`connection.level = "vn"`: hlavní rozvaděč nn, transformátor, rozvaděč VN s kobkami, fakturační měření nn/vn; nové značky MTP, MTN, uzemňovač). Doplněno 18. 10. 2026: pole / kobky VN v samostatných rámečcích, rámeček trafostanice (RVN, TR, RHN, elektroměrový rozvaděč RE), druh TS kiosková / zděná / sloupová, značky VN (ČSN EN 60617), ruční posun tažením (formát 12, `Element.sl_pos`). Dál: vícepól elektroměru (proud a napětí odděleně), DC část zkráceně (n × string), rozvaděč telemetrie AXY jako makro (dodá ENVO); ochrany VN a motorové pohony se v praxi ENVO nekreslí
- [ ] **Formáty strojů pro výrobu vodičů** (Komax, Steinhauer…) – až při sériové výrobě; vstupem `wiring.ProductionWire`, výstup `export/machine_<výrobce>.py`
- [ ] **Parametry artiklů pojmenovat podle ETIM/eCl@ss** – BMEcat importér pak jen mapuje sloupce
- [x] Databáze FV modulů a střídačů pro výběr v průvodci (jako SurgePV/PVcase) – hotovo 10/2026: katalog `pv_modules.csv` + rozšířený `inverters.csv` (zdroje v poznámkách), výběr z katalogu v průvodci, asistent stringů (`model/calc.py`, sdílený s F7), návrhové teploty v projektu (`docs/design/katalog_fv.md`). Data zatím neúplná (WebSearch bez stahování datasheetů) – doplnit z PDF výrobců; importér PVsyst .PAN/.OND odložen
- [x] **Optimizéry a režimy stringů** (SolarEdge, Huawei, Tigo) – hotovo 10/2026 (`docs/design/optimizery.md`): kategorie `optimizer` (`optimizers.csv`), sloupce střídače `string_mode`/`u_string_v`/`n_opt_*`/`p_string_max_w`, výpočty `model/calc.py` (režimy classic / optimizer / fixed_voltage, vstup optimizéru, paralelní stringy), generátor `optimizer.component_id`, výběr z katalogu, režim stringů a asistent v průvodci shodný s F7. Zbývá (YAGNI zatím): značka optimizéru v JPS, různé optimizéry v jednom stringu, US 277/480 V, import SolarEdge Designer, rapid shutdown, výnosy, „Přiřadit optimizér z katalogu“ u existujícího stringu
- [ ] **K doplnění dat (nutné oficiální PDF výrobce, WebSearch nestačí)**: pravidla stringů **SolarEdge** (počet optimizérů, max. P stringu podle fáze střídače – tabulka „PV system design“) a **Huawei** (`n_opt_min/max`, `p_string_max_w` k SUN2000 M1/M3, zda s optimizéry platí cap `u_out_max`, pravidla smíšené instalace); optimizéry **SolarEdge S500, S650B** (modulů na optimizér), **P850, P1100** (ověřit 2:1) a **Tigo TS4-A-O**; tolerance výkonu modulu `p_tol_pct`
- Nedělat: předprojekt / P&ID (Preplanning), cloud (eVIEW/eManage) – stačí JPS, průvodce a sdílená knihovna

## Chyby k řešení
- [x] Generovaný projekt se 4 a více střídači: JPS přetékal list – opraveno 10/2026 (formát A3–A0 podle obsahu); rozdělení velkých JPS na víc listů hotovo 10/2026 (`docs/design/dluhy_dxf_jps.md` bod B): nad A2 generátor dělí na listy A2 – AC list (AC rozvaděč, síť, HOP) první, za ním listy střídačů; AC kabel přes pár přerušení „AC-T1“ jako jeden kabel (`xref.through_interrupt`), F7 `cable_split`. Záměrně vynecháno (YAGNI): ruční příkaz „Rozdělit list“, párování prvků přesunutých mezi listy v `diff_projects`
- [ ] Rozvaděčové artikly: doplnit `t_min_c`/`t_max_c` z datasheetů. Stav: ověřeno z PDF/stránek výrobce – OEZ 3VA1/3VA2 (−25…70 °C, katalog MO1-2020), OEZ SVBC-DC (−40…80 °C), Hager MCB/RCD (−25…70 °C, resp. −25…40 °C). Zbývá: Eaton (eaton.com z agentního prostředí nedostupný, ~250 řádků bez nového ověření), OEZ MCB/RCD/SPD AC (minikatalog teploty neuvádí), BMR PLA33 (bez údaje), skříně (se.com 403, soubor bez sloupců `t_min_c`/`t_max_c`)

## Odloženo (analýza 10/2026 – nebrzdí práci)
- Příkazový řádek (styl ZWCAD/CADCraft) – až bude potřeba ovládat program z agentů
- BMEcat/ETIM importér – až budou soubory od výrobců
- Vlastní vícepólové značky z QET (`qet.ap.*`) – opakovaná jednopólová značka je čitelná a EPLAN to kreslí podobně
- Rust – ne

## Později
- Další obory (HVAC, MaR, silnoproud budov)
- Kontroly (dimenzování kabelů, selektivita) – propojení s výpočty
