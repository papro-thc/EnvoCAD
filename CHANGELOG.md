# Changelog

## 0.10.1 – 2026-10-15
- **Texty se nepřekrývají** (`model/textlayout.py`): popisky prvků i vodičů se automaticky umístí na volné místo – výchozí poloha značky, když je volná, jinak vpravo/vlevo/nad/pod značkou, popisek vodiče na začátek/střed/konec jiného úseku nebo vlevo od svislého; počítá se s čarami značek, vodiči a ostatními texty; stejně v editoru, PDF i DXF. **Kontrola projektu** hlásí zbylé překryvy (text přes text, přes vodič, přes značku) jako varování se skokem na prvek. Generátor: rozestup DC rozvaděčů 85 mm, stringů 45 mm, větší mezera střídač → RH, lomy vodičů do střídače bez křížení; DC makra s roztečí 40 mm a PE svodičů vedeným kolem popisků vývodů.
- **Vodiče jen svisle a vodorovně**: ruční lomy se doplní o rohy (`orthogonalize`) na obrazovce i v DXF/PDF, poslední úsek vstupuje do portu ve směru portu; generátor srovná lomy na skutečnou výšku portů (`_align_bends`) – žádné šikminy ani u starších projektů. Popisek stringu nad značkou (nepřekrývá popis kabelu), rozteč stringů 40 mm, uzemnění vpravo od rozvaděče.
- **Kreslení přímo ve schématu rozvaděče** (vícepól): vkládání prvků z knihovny (ruční pozice, průchozí přístroje svisle, R otočí, po vložení parametry), žíly klikem na konce pólů (žíla podle pólu), makra; undo, jednopólová editace se přestaví (`MultipoleAddCommand`). Dialog parametrů z vícepólu už nepřepíná záložku.
- **Styl ENVO podle vzorů** (`docs/ENVO_STYL.md`): ve vícepólu štítky kabelů na přívodech/vývodech (rámeček: označení kabelu / název / typ), označení svorek vlevo u svorek, nadpis výkresu rozvaděče vlevo nahoře na každé straně (`switchboard_title`: označení, soustava, Un, In, Ik'', skříň, montáž, krytí); generátor vyplní soustavu DC IT / 3NPE; proměnné maker `{i}`, `{j}` (střídač.string) – vestavěná DC makra číslují `FU{i}.{j}`, `QS{i}.{j}`, `SPD-DC{i}.{j}`; rozmístění vícepólu začíná vpravo od hlavičky.
- **Generátor skládá rozvaděče z maker** (`spec["macros"]`: `dc_tech`, `dc_route`, `ac_feed`, `ac_core`): parametrická makra s proměnnými `{k}`, `{nk}`, `{string}`, `{inverter}`, `{fuse_in}`… v atributech, označeních i portech, prvek `shared=1` se vloží jednou (sběrnice, XPE), `pitch` = rozteč instancí; vlastní makro stejného názvu má přednost před vestavěným – projektant ladí výkres, program opakuje. Porty bloku rozvaděče v přirozeném pořadí (X4, X5…, XOUT, XPE).
- Vícepól: dítě se zarovná pod pól rodiče, ze kterého vede spojovací žíla (vývod PE pod PE svodiče, ne pod L1 – PE už nevede skrz svodič).
- AC rozvaděč se sběrnicí: bez vnitřní PE lišty – PE je potenciál sběrnice (1PE), SPD jde svým PE na vývod `XPE`, stejně jako PE sběrnice; uzemnění je vývod `XPE` na ekvipotenciální svorkovnici (HOP) vně rozvaděče; generátor přidá do JPS uzemnění s kabelem (`ac.pe_cable`, výchozí CYA 16).
- Přívod a vývod se kreslí jen jako svorky (kroužek s číslem a krátký vnější vývod), bez šipek „Y“ a nápisů ve vícepólu; v JPS kroužek s nápisem.
- Vícepól: **vývody vždy v dolní řadě** (přívody nahoře → rozvod → přístroje → vývody dole), PE lišta pod nimi s odstupem; rodič prvku = nejbližší soused výš (ne jen o sloupec); popis sběrnice vpravo nad čarami.
- **Sběrnice potenciálů jako v EPLAN**: prvek `sb.busbar` (porty T1…T10 shora, 1…10 zdola) se ve vícepólu kreslí vodorovnými čarami L1 L2 L3 N PE přes stranu (na každé straně, kde má odbočky) s názvem potenciálu a šipkou na obou koncích (předpona = označení sběrnice: `1L1`), přístroje odbočkou s tečkou; v potenciálech je jeden uzel, názvy sítí `1L1`…; šablona AC rozvaděče, generátor a průvodce mají volbu rozvodu `bus` (výchozí) / `terminals` (svorky s můstky).
- **Rozvaděč na více stran s odkazy**: vícepól se automaticky stránkuje (prvek nepřesáhne okraj strany – `auto_layout(page_w)`), strany pod sebou na obrazovce a každá zvlášť v PDF (`export_scene_pdf` i celá dokumentace, popisové pole `k/n`); žíla přes hranici stran končí přerušovacím bodem s odkazem `/list.strana.sloupecřádek` a na druhé straně pokračuje s odkazem zpět; můstky po stranách, PE lišta na straně s nejvíc sousedy. PDF stran už není otočené na výšku.
- Výkon: vazby přívodů na vodiče JPS se počítají jednou (`feed_link_index`) a drží v cache scény do další změny modelu – výkaz Kabely a DXF u projektu s 800 vodiči z 0,25 s na 3 ms, překreslení JPS ~2× rychlejší; makra se nenačítají jako značky (chybové hlášky při startu).
- **T-odbočka / vodič z vodiče**: klik na vodič v režimu Vodič ho rozdělí uzlem (`sb.junction`, 4 porty = jeden potenciál), odbočka přebere žíly; `SplitWireCommand` s undo.
- **Potenciály** (`model/potential.py`): sítě přes vodiče, uzly, průchozí svorky, můstky, PE lištu a vazby přívod/vývod ↔ JPS; názvy potenciálů (`L1 X1`, `DC+ G1`, `N (W3)`), kontrola zkratů L–N / L–PE / DC+–DC− / fáze (u jednopólových přístrojů i přes jednu svorku), uzel bez odbočky; potenciál žil v panelu Vlastnosti, výkaz **Potenciály**.
- **Makra**: `Úpravy → Uložit výběr jako makro…` (`Ctrl+Shift+S`) do `~/.envocad/macros/` nebo sdílené knihovny (`macros/`), uzel Makra v panelu Knihovna (dvojklik vloží doprostřed pohledu, nová označení), mazání; 3 vestavěná makra (`tools/gen_builtin_macros.py`).
- String: v JPS se zobrazuje počet modulů a **počet a typ optimizérů** (atributy `n_optimizers`, `optimizer`; generátor/průvodce: `optimizer.type`, `per_module`); BOM počítá moduly a optimizéry v kusech, TZ má sloupec Optimizéry. Atribut značky může mít `fmt` („{}× modul“).
- Rámeček s popisovým polem a QR je zatím **vypnutý** (nastavení `frame`, přepínač `Zobrazit → Rámeček a popisové pole`); platí pro výkresy, PDF i DXF. Odkazy `/2.B4` fungují dál.
- **Stringy se v rozvaděči nikdy nespojují**: šablona *DC rozvaděč* i generátor vedou každý string zvlášť (přívod → pojistkový odpínač / odpínač DC → vývod) s vlastním SPD; střídač má DC vstup na každý string (`DC1…DCn` podle `mppt × strings_per_mppt`, značka se roztáhne – `inverter_symbol`), volné DC vstupy nejsou chyba. Paralelní spojení (SolarEdge) = jeden string.
- **Značky kontaktů dle IEC 60617 / EPLAN**: kloub pohyblivého kontaktu na straně výstupu (port 2), volný konec u vstupu – ve svislém vícepólu kloub dole, nůž nahoře; spoušť „x“ jističe na volném konci nože, pevný kontakt odpojovače s příčkou na vstupu; pomocné kontakty NO/NC stejně. Pojistkový odpínač má pojistku správně na noži.
- PE lišta má porty nahoře (vodiče k ní přicházejí shora, nic přes ni nevede); příčky Z-tras ve vícepólu jsou u cíle (80 % délky), ne uprostřed přes prvky v mezilehlém sloupci.
- Vícepól: PE lišta ve vlastním sloupci pod svými sousedy (SPD…), můstky čárkovaně podél řady svorek místo tlusté „sběrnice“, popisek svislých přístrojů vedle prvního pólu, označení skupiny svorek vedle čáry.
- **Přívod a vývod rozvaděče jsou svorkovnice**: ve vícepólu má každá žíla svorku s číslem (bez zadání 1…n, jinak atribut „Svorka č.“), jsou v plánu svorkovnice, ve výkazu svorkovnice a v BOM (řadové svorky); popisek vývodu pod svorkami.
- **Můstky patří listu rozvaděče** (`Sheet.bridges`, formát projektu v7 s migrací) – X1 v RDC1 a X1 v RH jsou různé svorkovnice; `SetBridgesCommand`/`bridge_groups`/`set_bridges`/`bridge_of` berou list.
- **Generátor / průvodce – DC strana jako na stavbě**: ke každému střídači DC rozvaděče **po trase** (`dc.route_boxes`, odpínač DC + SPD na každý string, stringy procházejí odděleně) a **u technologie** (`dc.tech_box`, pojistkové odpínače gPV + SPD DC na každý string); bloky v JPS mají porty X1…Xn (od stringů) a Xn+1… (dál); kabely string → 1. rozvaděč, mezi rozvaděči (`route_length`) a ke střídači (`tech_length`). Starou variantu (jen odpínač v JPS) zapne `dc.disconnect` bez rozvaděčů. Více rozvaděčů po trase rozšíří list JPS.
- Nová značka **pojistkový odpínač** (`fve.fuse_disconnect`, F, gPV, 1000 V DC).
- **Označení jedinečná uvnitř rozvaděče** (jako EPLAN `+RDC1-X1`): kontrola duplicit i varování v dialogu počítají s prostorem označení listu rozvaděče; listy JPS sdílejí jeden.
- Popisky vodičů: křížový odkaz (`→ RDC1:X1 /2.A2`) na druhém řádku pod vodičem (JPS i DXF), průřez se neopakuje, když ho typ kabelu obsahuje (`H1Z2Z2-K 1x6`).
- **Vícepól – rozmístění jako strom**: každá větev (vývod, SPD, PE) dostane místo ve sloupci svého rodiče – odbočky se už nekreslí přes ostatní stringy, žádné dlouhé křížící vodiče.
- JPS: popisek kabelu stringu s počtem jednožilových kabelů (`2× H1Z2Z2-K 1x6`); generátor lomí vodiče string → rozvaděč a rozvaděč → střídač každému zvlášť a popisek dává k začátku vodiče, texty se nekryjí s vodiči.

## 0.10.0 – 2026-10-15 (nad rámec EPLAN)
- **Výpočty z modelu** (`model/calc.py`): kontrola stringů proti střídači (Uoc při −10 °C vs. Umax, Umpp při 70 °C vs. rozsah MPPT, 1,25·Isc vs. Imax vstupu – nové atributy stringu `vmp`, `beta_voc` a střídače `u_dc_max`, `u_mppt_min/max`, `i_mppt_max`), proud kabelem (1,25·Isc, P_AC/√3U, In), zatížitelnost Iz dle ČSN 33 2000-5-52 podle uložení (A1/B1/C/D/E z atributu `method` nebo textu trasy; tabulky orientační), In ≤ Iz, úbytek napětí (mez 3 %), základní selektivita po cestě ke zdroji. Nálezy v kontrole F7 a výkaz **Výpočty**.
- **Průvodce novým projektem** (`Ctrl+Shift+N`) a **generování ze specifikace JSON** (`Soubor → Nový projekt ze specifikace`, CLI `python -m envocad.generate spec.json out.ecp`) – rozhraní pro agenty: stringy → odpínače DC → střídače → AC rozvaděč (přívody po střídačích, jističe, rozvodné svorky s můstky, SPD, hlavní vypínač, vývod do HDS) → síť, kabely jako objekty, vazby, instalovaný výkon.
- **Porovnání s revizí** (`Soubor → Porovnat s revizí`): rozdíl dvou .ecp (prvky, vodiče, kabely, můstky, skříň) → změnový list jedním tlačítkem, skok na změněný prvek.
- **Technická zpráva (docx)** z modelu: základní údaje, FV pole + kontrola stringů, střídače, rozvaděče s oteplením, kabely s Iz/ΔU, selektivita, SPD, výkazy; výkaz **Data pro DS** (žádost o připojení).
- **Provoz**: autosave každé 2 min s nabídkou obnovy po startu, Poslední projekty, export PDF zmenšený na A4, štítky CSV pro tiskárnu (UTF-8 BOM, `;`), QR kód s identifikací výkresu v popisovém poli (knihovna `segno`).
- **Sdílená knihovna a firemní standard**: `Knihovna → Sdílená knihovna` (síťová složka s JSON/CSV načítaná navíc), `Firemní standard` (výchozí kabely, zpracoval) – `~/.envocad/settings.json`; nový projekt a průvodce standard předvyplní.

## 0.9.0 – 2026-10-15 (srovnání s EPLAN)
- **Kontrola projektu** (`F7`): duplicitní označení, vodiče na neexistující porty, nezapojené porty/prvky, skupiny svorek bez čísel, přívody bez vazby, prvky bez artiklu, vodiče bez kabelu/žil, můstky na neexistující svorky, přerušovací body a kontakty bez protějšku; dvojklik skočí na prvek.
- **Navigátor** (dok vlevo): listy → prvky a vodiče s filtrem; `Ctrl+F` najde označení kdekoli v projektu a vybere ho.
- **Kabel jako objekt**: `Project.cables` se žílami (číslo, barva dle ČSN 33 0165: L1 hnědá, L2 černá, L3 šedá, N modrá, PE zelenožlutá, DC+ červená, DC− černá), stíněním, délkou, trasou a artiklem; vzniká z vodiče JPS (označení/typ) a drží s ním krok. `Úpravy → Kabel vybraného vodiče…` (`Ctrl+Shift+K`). Nové výkazy **Kabelový plán** (po žílách odkud–kam) a **Zapojovací seznam** (všechna propojení vč. rozvaděčů, barva, průřez). Katalog kabelů (CYKY, AYKY, H1Z2Z2-K, JYTY, UTP – seed, ověřit).
- **Souřadnicová síť** A–H × 1–6 v rámečku; odkazy ve tvaru `/list.sloupec` (`/2.B4`) u vodičů na rozvaděč, u přívodů/vývodů; **přerušovací bod** (Svorky a propojení) párovaný podle označení s odkazem na protějšek.
- **Celá dokumentace do PDF** (`Výstupy → Celá dokumentace`, `Ctrl+Shift+E`): titulní list, obsah, listy JPS, schéma a plán svorkovnice každého rozvaděče, všechny výkazy stránkované, změnový list (`Vlastnosti projektu → Změnový list`).
- **Ovládací obvody**: cívka (K, A1/A2), kontakty NO 13/14, NC 21/22 a silový kontakt stykače; kontakty nesou označení cívky, pod cívkou se kreslí **zrcadlo kontaktů** (svorky + odkaz), u kontaktu odkaz na cívku; kontakty ve výkazu přístrojů ve sloupci Kontakty, ne jako samostatné položky BOM. Ovládací vodiče mají výchozí jednu žílu.
- Formát projektu v6 (kabely); starší projekty se načtou a kabely se dopočítají.

## 0.8.0 – 2026-10-15
- Blok ROZVADĚČ v JPS má porty podle přívodů a vývodů svého listu (X1 vlevo, X4/X5/X6 vpravo, s popisky) – vodič zakreslený na port X4 se sám naváže na vývod X4 (odkud/kam, kabel, žíly, křížový odkaz). Staré porty 1–4 zůstávají jen dokud na ně něco vede; šablona přejmenuje konec přívodního vodiče na X1.
- Schéma rozvaděče je vícepólové: dvojklik na blok / „Otevřít rozvaděč (schéma)“ otevře záložku „R – schéma“ jako vícepól (značky po pólech, svorky, můstky); jednopólová podoba je jen editační („R – jednopól (editace)“, `Ctrl+J`, menu List). Delete ve vícepólu maže přes undo.
- Vícepólové značky: značka má volitelnou část `multipole` (pól, společná část, mechanická vazba) – ve vícepólu se jistič/odpínač/stykač/chránič rozkreslí po pólech s čárkovanou vazbou a společnou spouští, pojistky a svorky po pólech bez vazby. Vlastní značky mají `multipole` vygenerované (`tools/gen_builtin_fve.py`), QET značky se opakují celé.
- Panel knihovny: nadpisy jsou druhy prvků (Zdroje, Střídače a měniče, Jištění, Spínání, Měření, Svorky a propojení, Rozvaděče, …), vlastní značky přímo pod nadpisem, cizí (QET, 673 ks) ve sbalené podsložce „QET (n)“ s příznakem „[vícepól]“ v názvu; rozlišení jednopól/vícepól z cest zmizelo (`tools/recategorize_qet.py`).
- FV string má v JPS jeden port DC (pár DC+/DC- jsou žíly vodiče), střídač má DC vstupy DC1/DC2 (MPPT); staré projekty se zmigrují (formát v5). Rozložení už nekreslí rámeček listu.
- **Vícepól jako svorkové schéma s vlastním rozmístěním**: automatické rozmístění po sloupcích podle hloubky od zdroje (přívod/FV/baterie), skupiny svorek spojené můstky v jedné řadě, vývody zarovnané pod svými svorkami; prvky jdou ve vícepólu posouvat myší (undo, `Element.mp_pos`, formát projektu v4), `Zobrazit → Vícepól: rozmístit automaticky` vrátí automatiku. List vícepólu se podle potřeby zvětší.
- **Plán svorkovnice** (`Zobrazit → Plán svorkovnice`, `Ctrl+Shift+M`): kreslený list jako v EPLAN – svorky v řadě, vnější připojení nahoře (navázaný kabel JPS), vnitřní dole, můstky; export PDF. Stejná data jako list xlsx „Plán svorkovnice“. Výkaz materiálu počítá svorky po kusech (skupina = počet žil) a můstky po skupinách.
- **Rámeček s popisovým polem ENVO** na všech listech (JPS, rozvaděč, vícepól, rozložení, plán svorkovnice) i v DXF/PDF: projekt, zakázka, investor, místo, list x/y, zpracoval, datum, revize, formát (`Soubor → Vlastnosti projektu`).
- **Vazba rozvaděč ↔ JPS**: přívod/vývod má v dialogu výběr „Vodič v JPS“; převezme kabel, průřez a žíly, zobrazí „W2 T1:AC“, u vodiče v JPS se vykreslí křížový odkaz „→ R1:X1“, seznam kabelů má sloupec Rozvaděč. Šablony vážou přívod automaticky na vodič k bloku.
- Kopírování prvků `Ctrl+C` / `Ctrl+V` (včetně vodičů mezi nimi, nová označení, posun 10 mm), varování na duplicitní označení v dialogu, panel vlastností ukazuje žíly a svorky vodiče.
- Oteplení dle IEC TR 60890: k, c, d a x z tabulek/křivek normy (hodnoty křivek k a c jsou přepsané z paměti – označené „orientační“, ověřit proti normě), parametry `partitions` a `vents`; činitelé b podle tab. 3 (nástěnná zadní stěna 0,5).
- Odvozené pohledy se přestavují jen když jsou vidět (ostatní při přepnutí záložky).
- Testy: 54 (nově `tests/test_gui_mouse.py` – vkládání, vodiče, tažení, dvojklik a výběr skutečnými událostmi myši; `tests/test_thermal.py`).

## 0.7.0 – 2026-10-15
- Svorky jako v EPLAN místo sběrnice: prvek `sb.terminal_block` je skupina svorek jedné svorkovnice (atribut `terminal` = čísla „1 2 3 4 5“ nebo první číslo), ve vícepólu má každá žíla vlastní svorku s číslem. Šablony AC/DC už sběrnici nepoužívají – napájení vývodů jde přes rozvodné svorky X2 a můstky.
- Můstky (propoje) svorkovnic: `Úpravy → Svorkovnice a můstky…` (`Ctrl+Shift+T`) – tabulka svorek svorkovnice (vnitřní/vnější strana, můstek) a editace můstků „1-6-11“; uloženo v projektu (`bridges`, formát v3 s migrací). Ve vícepólu se kreslí jako čáry s tečkami, v JPS čárkovaně mezi skupinami, ve výkazu svorkovnice sloupec „Můstek“.
- `Očíslovat svorky automaticky` čísluje i skupiny svorek (pokračuje za nejvyšším číslem svorkovnice).
- Knihovna: 254 artiklů řadových svorek z PDF katalogů – Weidmüller Klippon Connect (A2C/A2T push-in, WDU/WPE šroubové, ZDU/ZPE pružinové, můstky ZQV/WQV), Elektro Bečov (RSA, RSA PE, EB, RSP, PYK, PS, UTB, DTS/DTB distribuční bloky, EPS), ELEMAN (RKA, UK, HLAK, PVB/PDB). Nové sloupce `terminal_kind`, `connection`, `cross_mm2`, `cross_max_mm2`, `color`, `levels` (`docs/COMPONENTS.md`).

## 0.6.0 – 2026-10-15
- Vícepólový pohled (`Zobrazit → Vícepólový pohled`, `Ctrl+M`): odvozená scéna nad stejným listem – každá žíla vodiče (`Wire.conductors`) je samostatná čára, průchozí prvky (jistič, odpínač, chránič, SPD…) se opakují pro spínané póly, N/PE jdou kolem; neprůchozí prvky (střídač, svorky, sběrnice) mají sběrnou čárku přes žíly. Pozice z JPS roztažené 2×, symboly ve skutečné velikosti. Žádná data se nekopírují – změna v JPS se hned promítne (`Ctrl+J` zpět na JPS).
- Dialog vodiče má pole „Žíly“ s předvolbami (L1 L2 L3 N PE, DC+ DC-, …); nové vodiče dostanou výchozí žíly podle portů a pólů připojených prvků.
- Svorky: dvojklik na žílu ve vícepólu nebo `Ctrl+T` otevře tabulku svorek vodiče (X1:3 / F2:1 per žíla a konec), `Úpravy → Očíslovat svorky automaticky` doplní chybějící čísla na svorkovnicích, přívodech, vývodech a PE liště. Vše přes undo.
- Výkaz svorkovnice a export PDF berou vícepól v úvahu; `tests/test_multipole.py` + GUI smoke test.

## 0.5.1 – 2026-10-15
- Knihovna artiklů z PDF katalogů dodaných uživatelem (celkem 460 artiklů): Eaton 253 (xPole PL/PLHT/AZ, PF/PFIM/FRCmM/dRCM, SPD, xComfort skříně), OEZ 143 (Minia LTN/LFN/LFE/OLI/SVBC, 3VA10–3VA24 vč. odpínačů, motorových pohonů MO310/MO320/SEO520 a spínačů do dutin, pojistkové odpínače OPVP/OPVF, rozvodnice RZA), Schneider 35 (skříně S1868), Hager 11, SMA 5, SolaX 6, Huawei 3, BMR 4 (PLA33RXE…). Každý řádek má odkaz na zdroj a stranu katalogu v poznámce.
- Úklid: staré řádky 3VA v `oez.csv` nahrazeny `oez_3va.csv`, duplicity ze `seed.csv` odstraněny (dřívější chyba: `seed.csv` se načítal jako poslední a přepisoval katalogová data), přiřazení motorových pohonů a spínače EAS k rámům ověřeno proti tabulkám B12/B19 katalogu MO01-2022.
- Test `tests/test_components_builtin.py`: validace všech vestavěných CSV, zákaz duplicitních id napříč soubory.
- Známé mezery: ztrátové výkony 3VA (potřeba OEZ „3VA Parametry“), OPVF10 DC (chybějící strany B12–B14 v OPVP PDF), význam přípon BMR C/D/R, montážní desky Schneider.

## 0.5.0 – 2026-10-15
- Instalační skripty `scripts/install.ps1|sh`, `run.*`, balení `scripts/build.*` + `envocad.spec` (PyInstaller, ověřeno na Linuxu). Python omezen na 3.11–3.13.
- Import značek QElectroTech (`library/qet_import.py`): 673 značek IEC 60617 (jednopól + vícepólové jištění, spínání, transformátory, střídače, zdroje, svorky, relé, kabely) v kategoriích „QET …“, s uvedením autorství (CC BY 3.0, `builtin/qet/ATTRIBUTION.md`).
- Import z EPLAN exportů (`library/eplan_import.py`): obchodní CSV z Data Portalu, XML artiklů z P8, DXF ZIP → footprinty; heuristické mapování sloupců s `--dump`.
- Modularita: uživatelské balíčky knihovny v `~/.envocad/library/` (JSON + CSV, bez kódu), pluginy `~/.envocad/plugins/*.py` s `register(ctx)` (menu, šablony, importéry, výkazy); menu Knihovna → Otevřít složku knihovny a pluginů.
- Knihovna se načítá jen při změně souborů (start 0,02 s místo 1,3 s); panel Knihovna má QET kategorie sbalené.
- `docs/SOURCES.md`: přehled zdrojů dat a komunitních nástrojů (EPLAN Data Portal API, .epdz/E3D, QET).

## 0.4.0 – 2026-10-15
- Knihovna artiklů: formát CSV v2 (`docs/COMPONENTS.md`), validátor (`python -m envocad.library.components validate …`), vestavěné CSV v `library/builtin/components/` načítané při startu, import vlastních CSV z menu Knihovna.
- Výběr artiklu v dialogu prvku (filtr výrobce / In / póly / charakteristika, odkaz na datasheet) – parametry se propíší do prvku; prohlížeč artiklů v menu Knihovna; výběr skříně z knihovny v panelu rozložení.
- Rozložení: generický footprint modulového přístroje (páčky podle pólů, svorky), footprint z DXF přes `footprint_id`.
- Startovní data: 77 artiklů (OEZ Minia LTN/LFN/OLI/SVBC + 3VA, Hager MBN/MCN/CDA/Volta, SMA STP X, Huawei, SolaX X3-ULTRA, BMR PLA33) – každý s odkazem na zdroj.

## 0.3.1 – 2026-10-15
- List rozvaděče má vlevo nahoře informační blok s parametry skříně (skříň, rozměry, moduly, Un, In, Icw, síť, IP/IK, montáž, materiál) – živě z panelu skříně, stejně v PDF i DXF.

## 0.3.0 – 2026-10-15
- Oprava chybového dialogu při zavírání programu (signál výběru na likvidované scéně rozložení).
- Panel skříně přímo v záložce rozložení: označení, řady, moduly, rozměry (š/v/h), rozteč řad, IP/IK, montáž, materiál, dveře, Un/In/Icw, síť, rezerva, teplota okolí, RDF. Změny se projeví hned; dvojklik do prázdné plochy skočí do panelu; `Ctrl+K` otevře totéž jako dialog.
- Rozložení kreslí skříň ve skutečných rozměrech a ukazuje obsazenost/rezervu modulů.
- Odhad oteplení dle IEC 60890 (ČSN EN 61439-1 čl. 10.10.4.3): ΣPv přístrojů (atribut `p_loss_w`, jinak odhad z In a pólů) × RDF², chladicí plocha Ae podle montáže, Δt střed/horní část, hodnocení. Orientační – viz `envocad/model/thermal.py`.
- Protokol kusového ověření přebírá parametry skříně.

## 0.2.4 – 2026-10-15
- Oprava pádu (access violation): panel Vlastnosti mazal editační pole uvnitř jeho vlastního signálu `editingFinished` (při ztrátě fokusu – klik jinam, přepnutí záložky). Mazání i zápis do modelu jsou odložené.
- Popisky vodičů ve stylu EPLAN: vodorovný úsek → nad čarou, svislý → vodorovně vedle čáry se šikmou značkou. Stejně v DXF.

## 0.2.2 – 2026-10-15
- Dialogy parametrů (vložení prvku, vodiče, dvojklik) se otevírají až po doběhnutí události myši – oprava pádu na Windows.
- Do logu se zapisují akce (režim, dialogy, záložky), aby šel pád dohledat.

## 0.2.1 – 2026-10-15
- Logování do `~/.envocad/log/` (rotace 5 běhů), dialog při chybě, `crash.log` pro nativní pády (faulthandler).
- Oprava pravděpodobného pádu v pohledu rozložení (přestavba scény během obsluhy myši); otevření rozvaděče z dvojkliku je odložené mimo obsluhu události.

## 0.2.0 – 2026-10-15
- Rozvaděče: dvojklik na blok ROZVADĚČ založí/otevře jeho list (schéma) – šablony AC rozvaděč FVE, DC rozvaděč, prázdný.
- Pohled rozložení (Ctrl+L): řady DIN lišt, přístroje v modulech (17,5 mm), přetahování se snapem 0,5 modulu, undo.
- Záložky listů, menu List (nový/přejmenovat/odstranit, nastavení skříně, vložit šablonu).
- Nové symboly: hlavní vypínač, proudový chránič, jistič s chráničem, sběrnice, přívod, vývod, svorkovnice, PE/N můstek.
- Přístroje mají atributy výrobce, póly, šířka v modulech.
- Model: příprava na vícepól – `Wire.conductors` (žíly) a `Wire.terminals` (svorky per žíla), `Sheet.kind`, `Layout`; formát projektu v2 s migrací.
- Výstupy (menu Výstupy): výkaz přístrojů, výkaz materiálu, kabely, svorkovnice, štítky do xlsx; protokol kusového ověření (ČSN EN 61439-1) do docx.
- Nové závislosti: openpyxl, python-docx → `pip install -e .[dev]`.

## 0.1.2 – 2026-10-15
- Tmavý režim (výchozí), přepínání Zobrazit → Tmavý režim / Ctrl+D, volba se pamatuje. PDF export vždy černá na bílé.

## 0.1.1 – 2026-10-15
- Dialog s parametry při vložení prvku i vodiče; dvojklik = úprava parametrů (undo jako jeden krok).
- Vodiče: automatické označení W1, W2…; ve výkresu se zobrazuje označení + typ kabelu + průřez.

## 0.1.0 – 2026-10-15
- První kostra: model, knihovna 18 symbolů FVE, editor jednopólového schématu, undo/redo, export DXF/PDF, import DXF.
