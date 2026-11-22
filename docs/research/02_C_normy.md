# 02C – Normy a datové standardy pro EnvoCAD

Agent 2C, rešerše. Stav k 22. 11. 2026. Vstupy: `docs/research/01a_inventura.md`, `docs/research/01b_issues.md`.

Pravidla tohoto dokumentu: normy jsou placené a chráněné autorským právem – **nekopíruji tabulky ani text**, popisuji strukturu
a požadavky vlastními slovy. Co jsem nemohl ověřit z veřejných zdrojů (hlavně přesná čísla článků a hodnoty), je označeno
**„neověřeno“** a shrnuto v kap. 13. Webový obsah je brán jako data. Nic se nemění v kódu ani na GitHubu.

Značení: **DM** = datový model, **K** = kontroly (ERC, F7 – `model/checks.py`), **V** = výstupy (dokumenty, protokoly, štítky).
Náročnost: S (hodiny až den), M (dny), L (týden a víc / vyžaduje rozhodnutí).

---

## 0. Zjištění v kostce

1. **IEC 81346**: EnvoCAD už má aspekty `=`/`+`/`-` (`model/designation.py`, `Project.structures`, `Symbol.function_class`).
   Chybí: úplná vazba na písmenné kódy tříd z IEC 81346-2 (číslování podle třídy – ROADMAP ř. 112), aspekt typu (nové ve vydání 81346-1:2022)
   a rozhodnutí, zda použít **ISO 81346-10 / ISO/TS 81346-101 (RDS-PS)** pro FVE. Obor – rozhoduje projektant.
2. **IEC 61439**: protokol „kusové ověření“ (čl. 11) je správně oddělený od „ověření návrhu“ (čl. 10); problém není v protokolu samotném, ale v tom, že
   do něj #80 vkládá **oteplení vypočtené neověřeným modelem**. Ověření návrhu (včetně oteplení) je odpovědnost výrobce rozvaděče a kusová zkouška
   ho nenahrazuje. Navrhuji oteplení v protokolu nahradit odkazem na doklad o ověření návrhu (viz kap. 5, 6).
3. **IEC TR 60890**: metoda je výpočetní pro uzavřené rozvaděče bez nucené ventilace; **vydání 2014 a 2022 se liší** (hranice proudu, max. vnitřní teplota,
   vliv sousedních stěn) a podle DKE se interpretace vůči 61439-1 liší. Před #82 je nutné zjistit, podle kterého vydání je kód psán (neověřeno).
4. **ETIM** je **otevřeně licencován (ODC-BY 1.0)** a xChange je Apache 2.0 – ideální cesta pro strukturovaná data artiklů (#84, #83, #70). ECLASS je pro
   formáty BASIC/ADVANCED placený. BMEcat je volně použitelný formát, ETIM BMEcat guideline končí verzí 5.0 (nástupce xChange).
5. Pro FVE je důležitá **IEC 60364-7-712** (třetí vydání 2025 – přidává akumulaci/baterie a DC sběrnici) a **IEC 62548-1:2023** (návrh FV polí, DC jištění).
   Většinu požadavků lze převést na **kontroly** a na **pole stringu v datech artiklu** (Isc, Voc, Imax OCPR, Ib…), ne na nový obsah modelu.

---

## 1. IEC 81346 (-1, -2) a ISO 81346-10 / -12, ISO/TS 81346-101

**Rozsah.** Strukturní principy a referenční označení objektů (zařízení, systémů). Díl 1 (IEC 81346-1:2022) = základní pravidla (nově i aspekt „typ“ a informační
model RDS); díl 2 (IEC 81346-2:2019) = klasifikace objektů a **písmenné kódy tříd** (třístupňové schéma, samostatné schéma pro prostory). Díl 10 (ISO 81346-10:2022)
= RDS-PS, **energetické systémy** (výroba vč. FV); díl 12 (ISO 81346-12:2018) = RDS-CW, **stavby** (ne FVE). ISO/TS 81346-101:2025 = návod k použití RDS-PS
(cílová odvětví výslovně zahrnují fotovoltaiku).
Zdroje: <https://en.wikipedia.org/wiki/IEC_81346>, <https://webstore.iec.ch/en/publication/64021>, <https://webstore.iec.ch/en/publication/29181>,
<https://knowledge.bsigroup.com/products/industrial-systems-installations-and-equipment-and-industrial-products-structuring-principles-and-reference-designations-part-101-modelling-concepts-guidelines-and-requirements-for-power-supply-systems>.
(Pozn.: zadání zmiňovalo „81346-12 / RDS-PS“; RDS-PS je díl **10**, díl 12 je stavebnictví.)

**Pojmy použitelné v modelu (vlastními slovy).** Objekt se může označit podle několika **aspektů**: funkce (prefix `=`), produkt/přístroj (`-`), umístění (`+`);
vydání 2022 doplňuje aspekt typu. Označení se skládá z řetězu aspektů a podřízených úrovní. Třída objektu se vyjadřuje **písmenným kódem** (příklady z Wikipedie:
Q řídicí objekt/spínač, F ochranný objekt/pojistka/jistič, K zpracování informací, W vodicí objekt/kabel, X propojovací objekt/svorka, G generující objekt).
Přesný aktuální seznam kódů a jejich podtříd je v normě – **neověřeno**, nekopírovat.

**Co je v EnvoCAD (inventura kap. 1, 2):** `model/designation.py` (`parse_designation`, `full_designation`, `validate_ref`), `Project.structures: StructureId(aspect, code, description)`,
`Sheet.func/loc`, `Element.attrs["ref"/"func"/"loc"]`, `Symbol.function_class`, `model/renumber.py`, `Project.next_ref`, test `tests/test_designation.py`. Kontrola syntaxe
a třídy existuje. Chybí číslování podle `function_class` (ROADMAP ř. 112), kontrola, že třída symbolu odpovídá písmenu v `ref` je „částečná“ (neověřeno do detailu), aspekt typu, a
**datový odkaz na zdrojovou revizi tabulky tříd** (která edice 81346-2 se používá).

| Co | DM | K | V |
|---|---|---|---|
| Aspekty `=` `+` `-` jako struktury, registr kódů (`StructureId`) | ano (už je) | kontrola neznámého kódu (je) | popisové pole, výkazy |
| Písmenný kód třídy v symbolu (`function_class`) + tabulka kódů v datech (ne text normy) | ano (už je, sjednotit zdroj tabulky) | shoda `ref` ↔ třída (je) | značení v `reports.marking` |
| Číslování podle třídy (Q1, Q2, F1…) | ano – pravidlo v `Symbol` nebo nastavení | – | – |
| Aspekt typu (2022), případně vazba na ETIM třídu artiklu | volitelně `Component.etim_class` | – | – |
| RDS-PS pro celý FVE systém (např. úroveň elektrárna → pole → string) | rozhodnutí projektanta | – | titulní list, štítky |

**Otázky pro projektanta (Q-1):** Kterou edici 81346-2 a které kódy tříd mají v ENVO stanovené (interní směrnice)? Používat RDS-PS (díl 10) i pro DC stranu a
stringy? Mají zákazníci/provozovatelé předepsané značení (KKS/RDS-PP u velkých elektráren)? Má se aspekt typu zavést?

---

## 2. IEC 60617 a IEC 61082

**IEC 60617.** Databáze grafických značek pro schémata; oficiálním zdrojem je placená databáze (v nabídce IEC předplatné; formáty GIF/DWG/EPS), IEC se vyhrazuje autorské
právo na strukturu a obsah a **zakazuje kopírování podstatných částí pro komerční použití nebo volné sdílení bez písemného souhlasu**. Značky mají referenční číslo a
anglicko-francouzské názvy. Zdroje: <https://webstore.iec.ch/en/publication/2723>, <https://library.iec.ch/iec60617>.

**IEC 61082-1.** Pravidla pro tvorbu dokumentů v elektrotechnice (druhy dokumentů, členění); datové listy značek v 60617 odkazují na druhy dokumentů z 61082-1.
Aktuální vydání a obsah článků – **neověřeno** (nenalezl jsem veřejně obsah).

**EnvoCAD dnes:** `Symbol.iec_ref` (pole existuje), 48 vlastních značek (`library/builtin/{fve,switchboard,control}`), 673 QET značek (CC BY 3.0; #81). Vlastní značky
**nemají být kopií grafiky IEC DB** – CLAUDE.md to už vylučuje (licencovaná data). `iec_ref` smí obsahovat jen identifikátor.

| Co | DM | K | V |
|---|---|---|---|
| `iec_ref` – číslo značky v 60617 (jen ID, ne kresba) | ano, už je; doplnit pro všech 48 | kontrola formátu ID | legenda značek (#76) |
| Legenda použitých značek | – | – | ano (název + `iec_ref` + vlastní kresba) |
| Druhy dokumentů dle 61082-1 (schéma, plán svorkovnice, seznam…) | volitelně `Sheet.kind` → typ dokumentu | – | titulní list / obsah (`doc_pdf`) |

**Otázka (Q-2):** Má být v legendě (#76) uvedeno číslo IEC 60617 u každé značky? Je ENVO předplatitel IEC 60617 DB (jinak nesmí ID zkopírovat z DB hromadně)?

---

## 3. IEC 61439-1 a -2 (rozvaděče nn)

**Rozsah.** -1 = všeobecná pravidla pro rozváděče nn, -2 = výkonové rozváděče. Klíč pro EnvoCAD: **dvě oddělené roviny**:
- **Ověření návrhu** (čl. 10) – prokazuje, že konstrukce splňuje normu: vlastnosti konstrukce (materiály, krytí), elektrické vlastnosti (oteplení, odolnost
  vůči zkratu, izolace atd.). Metody: zkouška, výpočet (srovnání), pravidla konstrukce. Provádí **původní výrobce** (typ.) – ověření jednou pro typ.
- **Kusové (rutinní) ověření** (čl. 11) – každý vyrobený kus; typicky vizuální kontrola, mechanická funkce, izolační odolnost / dielektrické zkoušky, ochranná
  opatření a spojitost PE, kontrola zapojení. Provádí **výrobce konkrétní sestavy** a protokoluje.
Zdroje: <https://webstore.iec.ch/en/publication/5457> (IEC 61439-1; 2011 zrušeno, platné vydání 2020 – pozn.: aktuální vydání ověřit), přehled Schneider
<https://blog.se.com/infrastructure-and-grid/power-management-metering-monitoring-power-quality/2013/03/29/iec-61439-more-than-just-an-upgrade-a-whole-new-approach/>.
Vydání 2020 podle IEC doplnilo informativní přílohu o ověřování oteplení a změnilo kusové ověření vzdušných/povrchových vzdáleností (čl. 11.3) – **neověřeno** do detailu.
Přesná čísla podčlánků 10.x a 11.x a požadavky na obsah protokolu: **neověřeno**.

**Co je v EnvoCAD:** `export/docx_export.py:export_routine_test_docx`, `ROUTINE_CHECKS` (seznam kusových kontrol); řádek „Oteplení (IEC TR 60890, výpočet)“ z `_thermal_text`
(`docx_export.py:229`); `model/thermal.py`; `Layout.params` (IP, Icw, rozměry). Připravenost na výrobce: štítek rozvaděče (jmenovité hodnoty – Ue, In, Icw, Icc, IP, IK, forma
vnitřního rozdělení) – je v `Layout.params`, strukturu a úplnost nelze z inventury posoudit (neověřeno).

| Co | DM | K | V |
|---|---|---|---|
| Jmenovité hodnoty sestavy (Un, Inc, Icw/Icc, IP, IK, forma, třída ochrany, ambient) | ano – strukturované pole v `Layout.params` (verzované) | úplnost vyplnění; Icw ≥ prospektivní zkrat | štítek rozvaděče, protokol |
| Způsob ověření návrhu (typ. zkouška / výpočet / pravidla) a odkaz na doklad | ano – textové pole + URL/č. dokladu | upozornění „ověření návrhu není vyplněno“ | protokol, TZ |
| Kusová zkouška: seznam kontrol, výsledek, datum, zkoušející, přístroje | ano, strukturovaně (dnes jen generace docx) | – | protokol (čl. 11) |
| Oteplení vypočtené EnvoCAD | **ne jako výsledek ověření**; jen orientační pomůcka | označit „orientační“ (#80) | **vypustit z protokolu** nebo označit |
| Ověřovací výpočet oteplení výrobcem skříně (Rittal Therm ap.) | pole pro odkaz/hodnotu z cizího nástroje | – | protokol |

**Otázky (Q-3):** Je ENVO „původní výrobce“ nebo „výrobce rozvaděče“ (stavba z typově ověřené skříně např. Hager/ETI/Rittal)? Jakou metodou se dnes ověřuje oteplení
(výrobcův doklad, výpočet 60890, zkouška)? Má protokol obsahovat shodu s konkrétním vydáním (2011/2020/ČSN EN 61439)? Kdo podepisuje? Je potřeba šablona „po dodání“ (ROADMAP)?

---

## 4. IEC TR 60890 (oteplení rozvaděče – výpočet)

**Rozsah.** Technická zpráva s výpočetní metodou ověření oteplení pro uzavřené rozvaděče (nebo oddělené oddíly) **bez nucené ventilace**. Vydání 2014 uvádí omezení:
nepoužít, kde produktová norma IEC 61439 uvádí vlastní ověření; **3. vydání 2022** má podle AFNOR změny (hranice 3 150 → 3 200 A, mez vnitřní teploty okolí, vliv sousedních
stěn). Německá verze DKE 2022 (jako doplněk k 61439-1) uvádí, že omezení rozsahu nemá – **protichůdné čtení, před implementací zjistit, které vydání platí v ČR/pro ENVO**.
Zdroje: <https://www.scc.ca/en/standardsdb/iec/23175>, <https://webstore.iec.ch/publication/66007>,
<https://www.boutique.afnor.org/en-gb/standard/iec-tr-608902022/a-method-of-temperaturerise-verification-of-lowvoltage-switchgear-and-contr/xs142134/335135>,
<https://www.din.de/en/getting-involved/standards-committees/dke/publications/wdc-beuth:din21:385014480>. Přesné křivky a konstanty k, c, d, a limity použití: **neověřeno**.

**EnvoCAD:** `model/thermal.py` (`temperature_rise`, `k_factor`, `c_factor`, `device_temperatures`, Ae, Pv z artiklu), kontrola `checks.thermal_findings`; křivky „ORIENTAČNÍ“
(`thermal.py:19`); ventilace a přepážky chybí (#82, #80, #79).

| Co | DM | K | V |
|---|---|---|---|
| Pv artiklu (ztrátový výkon při In) | ano (`params`), doplnit u 138 jističů (#83) | kontrola „Pv chybí“ | – |
| Konstanty a křivky k, c, d | ne v repu jako text normy; datový soubor mimo git nebo vlastní fit s odkazem na vydání (#82) | – | – |
| Podmínky platnosti metody (bez ventilace, ≤ 3 150/3 200 A, rovnoměrná dělba atd.) | – | **ano** – kontrola „mimo rozsah metody“ | upozornění |
| Označení „orientační / neověřeno“ ve výsledku | atribut výsledku (`verified: false`) | – | **ano** – všude (#80) |
| Prokazatelný výsledek | externí doklad (Rittal Therm, výrobce skříně) – pole | – | protokol |

**Otevřené nástroje:** nenalezl jsem otevřenou referenční implementaci TR 60890 (**neověřeno** – vyhledávání neprovedeno nad GitHubem). Výrobcovské konfigurátory
(Rittal Therm aj.) jsou uzavřené.

**Otázky (Q-4):** Má EnvoCAD oteplení vůbec počítat „ověřitelně“, nebo jen jako předvýpočet s odkazem na doklad výrobce skříně? Které vydání TR 60890 má ENVO k dispozici?

---

## 5. IEC 60364-7-712 / ČSN 33 2000-7-712 (FV napájecí systémy)

**Rozsah.** Požadavky na elektrickou instalaci FV napájecích systémů připojených k instalaci (vč. AC modulů); zařízení řeší jen z hlediska výběru a použití. **Třetí vydání
(říjen 2025) nahrazuje 2. vydání 2017** a přidává požadavky na akumulaci (baterie) a DC sběrnici / DC jednotky. Ostrovní provoz je v IEC 60364-8-82. Obsahuje ochranu před
úrazem, zařízení pro odpojení a spínání (712.53), nadproudová ochrana (712.533) apod.
Zdroje: <https://webstore.iec.ch/publication/28213>, <https://webstore.ansi.org/standards/iec/iec60364712eden2025>, <https://www.evs.ee/en/iec-60364-7-712-2025>.
České znění ČSN 33 2000-7-712 a platná edice v ČR: **neověřeno**. Přesná znění článků (DC odpojení, uzemnění, ochrana stringů): **neověřeno**.

**EnvoCAD:** `model/calc.py` (stringy, Iz, úbytky), `model/dc_system.py`, `checks.*` (SPD, Icu/Icw, přerušení, N/PE, baterie), generátor `generator/pv.py`. Bytový dům/RD s EPS jen částečně.

| Co | DM | K | V |
|---|---|---|---|
| DC strana: Uoc max (za nejnižší teploty), Isc, počet stringů paralelně | ano (artikl modulu: Voc, Isc, teplotní koef.) | ano – Uoc ≤ Umax střídače/svorky/kabelu (už je v `string_issues`) | TZ, výkaz výpočtů |
| Ochrana DC proti nadproudu (je-li potřeba) a přepětí; požadavek na DC odpojovač | ano – atribut ochranného prvku | ano – „chybí DC odpojovač / SPD“ | schéma, TZ |
| Uzemnění/vyrovnání potenciálů FV | atribut vodiče (PE/ekvipotenciál) | ano – chybějící PE u kostry pole | TZ |
| Označení DC kabelů/rozvaděčů výstražným štítkem | – | – | štítky (CSV → vzor) |
| Baterie / DC sběrnice (nové vydání) | atributy `battery`, DC bus | rozšíření `battery_findings` | TZ |

**Otázky (Q-5):** Podle kterého vydání 712 projektuje ENVO (2017 vs. 2025)? Jaké interní požadavky navíc (např. typ SPD, přerušení DC, požární odpojení)? Zahrnout i
návaznost na 60364-8-82 (ostrovní, EPS)?

---

## 6. IEC 62548 (FV pole – požadavky na návrh)

**Rozsah.** IEC 62548-1:2023 (předchůdce IEC TS 62548:2013): požadavky na návrh FV polí – kabeláž DC, ochranná zařízení, spínání, uzemnění. Obsahuje kapitolu nadproudové
ochrany DC (kdy je potřeba, požadavky na úrovni obvodu, baterie, umístění; pojistky a jističe).
Zdroje: <https://webstore.ansi.org/preview-pages/IEC/preview_iec62548-1%7Bed1.0%7Den.pdf>, <https://cdn.standards.iteh.ai/samples/102730/49931c968ef142498bc4475eb9858050/IEC-62548-1-2023.pdf>,
<https://standards.iteh.ai/catalog/standards/iec/4f9e80a5-fc15-49f4-8eec-88df1c3c1663/iec-ts-62548-2013>. **Konkrétní vzorce** (např. faktor k Isc pro jmenovitý proud
jištění, maximální zpětný proud) jsem **neověřil** – za paywallem, použít až po ověření (#79).

| Co | DM | K | V |
|---|---|---|---|
| Isc modulu, Imax OCPR (max. jmenovitý nadproudový chránič z datasheetu), Voc, koeficient Voc | ano – povinná pole artiklu modulu (dnes částečně `params`) | ano – počet paralelních stringů vs. Imax OCPR; jištění stringu | výkaz výpočtů |
| Isc střídače (max. DC proud na MPPT), Umax | ano (`ratings.py`) | ano (`string_limits`) | – |
| Jmenovitý proud DC jištění, charakteristika gPV | ano – `params` artiklu | ano – In ≥ k·Isc, In ≤ Imax OCPR (konstanty ověřit!) | schéma |
| Vazba na parametry zařízení v PVsyst PAN/OND (#86) | – | – | – |

**Otázka (Q-6):** Jaké interní zásady má ENVO pro jištění stringů (kdy se pojistky používají, koeficient, typ gPV)? EnvoCAD je „nedomýšlí“.

---

## 7. IEC 60364-5-52 (zatížitelnost kabelů, Iz)

**Rozsah.** Výběr a provedení kabelových systémů. Tabulky proudové zatížitelnosti v příloze (v vydání 3.1 2024: instalační metody v normativní příloze A, zatížitelnosti
v informativní příloze B – číslování tabulek se mezi vydáními mění, např. starší A.52-x/B.52-x). Referenční metody A–G; Iz = tabulková hodnota × korekce (teplota okolí
30 °C ve vzduchu / 20 °C v zemi; seskupení; hloubka/tepelný odpor půdy 2,5 K·m/W – pozn. z sekundárního zdroje). Čísla a samotné tabulky **nepřepisovat**.
Zdroje: <https://www.vde-verlag.de/iec-normen/preview-pdf/info_iec60364-5-52{ed3.1}en.pdf>, <https://www.electrical-installation.org/enwiki/General_method_for_cable_sizing>
(sekundární, nelze považovat za normativní). České znění ČSN 33 2000-5-52 – **neověřeno**.

**EnvoCAD:** `model/calc.py` (`ampacity`, `min_cross`, Iz tabulky „orientační přepisy“), `Wire.attrs` (průřez, uložení), `Cable.cross/type`, `checks` (In ≤ Iz).

| Co | DM | K | V |
|---|---|---|---|
| Referenční metoda uložení (A1…G), teplota okolí, seskupení, materiál vodiče, izolace (PVC/XLPE) | ano – atributy vodiče/kabelu (část už je) | ano – In ≤ Iz·k | kabelový plán, výkaz |
| Tabulky Iz | **soubor dat mimo repo** (licence) nebo vlastní fit s odkazem na vydání a stavem „neověřeno“ | – | označit |
| Úbytek napětí | ano (už je) | – | – |
| Specifické FV kabely (H1Z2Z2-K) – zatížitelnost podle výrobce kabelu | pole v artiklu kabelu | – | – |

**Otázky (Q-7):** Které instalační metody ENVO reálně používá (žlab, trubka, v zemi…)? Zdroj tabulek: ČSN originál, nebo hodnoty výrobců kabelů (Prysmian, Nexans)?
Lze hodnoty od výrobců použít jako „fakta“ do knihovny s `url` (CLAUDE.md to dovoluje)?

---

## 8. ETIM (třídy, vlastnosti, xChange)

**Co to je.** Mezinárodní klasifikační model technických produktů (třídy EC…, skupiny EG…, vlastnosti EF…, hodnoty EV…). **Licence: Open Data Commons Attribution License 1.0
(ODC-BY)** – model i rozšíření MC je zdarma pro každého, podmínka: uvedení zdroje a ponechání licenčních oznámení. **Jazykové verze**: otevřené jsou angličtina (master),
belgická nizozemština/francouzština, italština, finština, norština; **německá (DE) pro Německo/Rakousko a polská aj. jsou za členstvím národní organizace** – **českou/slovenskou verzi
jsem neověřil**. ETIM **xChange** (formát JSON s JSON Schema; verze 1.0/1.1/2.0) má podle licenční stránky **Apache 2.0**, copyright 2024 ETIM International; online validační nástroj
je zdarma, ale jen pro členy.
Zdroje: <https://www.etim-international.com/?p=1811>, <https://etim-international.com/>, <https://www.2ba.nl/en/documentation/file-exchange/file-formats/etimxchange/>,
<https://www.productsup.com/blog/etim-xchange-product-data-exchange-for-global-industrial-manufacturing/>, <https://en.wikipedia.org/wiki/ETIM_(standard)>.

**Ověřené příklady tříd (viewer ETIM):** EC000042 jistič (MCB), EC002694 MCB s příslušenstvím, EC001747 DC/AC síťový střídač (FV; vlastnosti např. max. vstupní výkon DC,
max. vstupní napětí DC), EC004891 výkonová elektronika na úrovni modulu (optimizéry/mikroměniče). Třída pro FV modul: **neověřeno**. Zdroje:
<https://viewer.etim-international.com/class/EC000042>, <https://viewer.etim-international.com/class/EC001747>, <https://viewer.etim-international.com/class/EC004891>.
Aktuální vydání modelu (7.0/8.0/9.0…) a seznam tříd pro svorky, SPD, DC odpojovače, kabely: **neověřeno**.

**EnvoCAD:** v `library/eplan_import.py:52` jen sloupec ETIM; `Component.params` je volný JSON bez ETIM klíčů; neexistuje `bmecat_import.py` (#84). `Component.category ∈ CATEGORIES`.

**Návrh datové reprezentace.** Do `Component` přidat volitelně `etim_class` (EC…), `etim_version` a `etim_features: dict[EF… → hodnota+jednotka]`; mapování EF → naše
`params` klíče (`PARAM_TO_ATTR`) v datovém souboru `library/etim_map.json`. Verzovat knihovní SQLite (dnes bez verze – inventura kap. 2).

| Co | DM | K | V |
|---|---|---|---|
| `etim_class`, `etim_features`, `gtin`, `manufacturer_part_number` v artiklu | ano | kontrola úplnosti dle třídy (Pv, Icu, In…) = #83 | výkaz (sloupec ETIM, GTIN pro objednání) |
| Import ETIM xChange / BMEcat | importér `library/…` | validace schématem | – |
| Mapování ETIM jednotky ↔ naše jednotky (A, V, W, mm) | tabulka v datech | – | – |

**Otázky (Q-8):** Mají dodavatelé ENVO (OEZ, Eaton, Hager, ETI…) data v ETIM a v jaké verzi/jazyce? Máte přístup k české verzi? Má smysl ETIM i jako **jediný** zdroj parametrů (místo ručního CSV)?

---

## 9. eCl@ss (ECLASS)

**Co to je.** Německý klasifikační a popisný standard (třídy 8místné, vlastnosti, hodnoty). **Licence:** použití vyžaduje licenci nebo členství v ECLASS e.V.; v e-shopu
např. ECLASS 14.0 za 700 €, cena podle počtu zaměstnanců, licence i pro >50 % dceřiné firmy; **formát „Asset“ (např. ECLASS 16.0 Asset) je zdarma**; zdarma i pro výzkum/vzdělání
(podle ceníku V10.1 z r. 2020 – **ověřit aktuální stav**). Online hledání je zdarma, **aplikace standardu** vyžaduje licenci.
Zdroje: <https://eclass.eu/en/eclass-standard/prices>, <https://eclass.eu/en/eclass-standard/licenses>, <https://eclass.eu/shop/en/product/eclass-16-0>, <https://eclass.eu/en/eclass-standard/search-content/search>.

**Relevantní pro EnvoCAD:** hlavně jako **import**: pokud výrobce dodá data v ECLASS (BMEcat s ECLASS), je to zdroj parametrů. Do repo ale **nesmí** jít obsah ECLASS (licence, podobně jako EPLAN).
Doporučení: ukládat jen **číslo třídy/vlastnosti** v poli artiklu (`eclass_class`) jako identifikátor a nesdílet tabulky. Prakticky nižší priorita než ETIM (ČR/SK distributoři v elektru
používají hlavně ETIM – **neověřeno** pro konkrétní firmy).

| Co | DM | K | V |
|---|---|---|---|
| `eclass_class` (ID) v artiklu | volitelně | – | výkaz |
| Import ECLASS dat | jen pokud poskytne výrobce v BMEcat/XML | – | – |

**Otázka (Q-9):** Posílají některí zákazníci/dodavatelé data v ECLASS? Je ENVO členem / má licenci?

---

## 10. BMEcat (2005, ETIM BMEcat guideline)

**Co to je.** XML katalogový formát (BME), verze 1.2 a 2005; ETIM má vlastní **guideline pro BMEcat** (tvary s ETIM třídami a vlastnostmi; verze 5.0 z 30. 6. 2021 je „poslední“, nástupcem je
xChange). Formát je volně použitelný; validace proti XSD; oficiální certifikační nástroj ETIM vyžaduje účet.
Zdroje: <https://www.etim-international.com/?p=1664>, <https://www.itek.de/en/knowledge/industry-standards-directory/etim-bmecat>, <https://github.com/naugrimm/bmecat>,
<https://packages.nuget.org/packages/BMECat.net/4.5.0>, <https://www.productsup.com/blog/unlock-efficient-product-data-exchange-exploring-with-bmecat/>.
Nenalezl jsem zavedený **Python parser** BMEcat (nalezeno: .NET `BMECat.net`; `naugrimm/bmecat` je PHP – **licenci a jazyk neověřeno**). Realistická cesta pro #84: `lxml`/`xml.etree`
+ XSD validace, vlastní lehký parser, bez nové závislosti (`lxml` by bylo nutné zapsat do `pyproject.toml`).

| Co | DM | K | V |
|---|---|---|---|
| Parser BMEcat 1.2/2005 → `Component` (supplier PID, popis, ETIM/ECLASS třída, vlastnosti, jednotky, GTIN/EAN, cena) | importér | validace XSD + hlášení nevalidních řádků | – |
| Ceny z BMEcat (price list) | `Component.price` (už je) | – | výkaz cen (#87) |

**Otázky (Q-10):** Které dodavatelské BMEcat soubory má ENVO k dispozici (ukázkový **reálný** soubor – zadání #84 žádá smyšlený)? Verze 1.2 vs. 2005? Smí se ceny/popisy z katalogů ukládat do sdíleného repa (licence dodavatele)?

---

## 11. AutomationML (IEC 62714)

**Co to je.** Otevřený XML formát výměny inženýrských dat (CAEX, IEC 62424) pro výrobní systémy; standardizováno jako IEC 62714 (texty norem placené), whitepapery a doporučení volně
na automationml.org. Vazba na eCl@ss existuje (atributy/třídy). Python knihovna: **PyAutomationML** (CIIRC-ISI, na PyPI `pyautomationml`, práce s lxml) – licenci **neověřeno**.
Zdroje: <https://en.wikipedia.org/wiki/AutomationML>, <https://pypi.org/project/pyautomationml/>, <https://github.com/CIIRC-ISI/PyAutomationML>, <https://automationml.org/>.

**Relevantní pro EnvoCAD:** nízká priorita. EPLAN exportuje AML pro výměnu s PLC/mechanikou, pro FVE rozvaděče není poptávka v zadání. Možné použití jen jako budoucí **export topologie**
(strom objektů z `Project`) pro spolupráci s jinými CAD. Nedoporučuji do roadmapy bez konkrétní poptávky zákazníka.

---

## 12. Souhrnná tabulka „datový model / kontroly / výstupy“

| Norma / standard | Datový model | Kontroly (ERC / F7) | Výstupy |
|---|---|---|---|
| IEC/ISO 81346 | aspekty `=` `+` `-` (je), písmenný kód třídy v symbolu (je), aspekt typu (chybí), číslování podle třídy | shoda třídy a `ref` (je), duplicity (je) | značení, štítky, titulní list, výkaz `marking` |
| IEC 60617 / 61082 | `Symbol.iec_ref` (ID, ne kresba) | formát ID | legenda značek (#76), obsah dokumentace |
| IEC 61439-1/-2 | jmenovité hodnoty sestavy, způsob ověření návrhu, doklad (odkaz) | úplnost údajů, Icw vs. zkrat | štítek rozvaděče, **protokol kusového ověření (čl. 11)** |
| IEC TR 60890 | Pv artiklu, geometrie skříně, ventilace/přepážky (zatím chybí) | rozsah platnosti metody, Pv chybí | označení „orientační“, poznámka v TZ; **ne** do protokolu |
| IEC 60364-7-712 | DC parametry stringu, SPD/odpojovač atributy, baterie | DC odpojení, SPD, PE FV pole, Uoc max | TZ, schéma, výstražné štítky |
| IEC 62548 | Isc/Voc/Imax OCPR artiklu, jištění stringu | jištění stringu, paralelní stringy | výkaz výpočtů |
| IEC 60364-5-52 | metoda uložení, teplota, seskupení, materiál | In ≤ Iz, úbytek | kabelový plán, výpočty |
| ETIM | `etim_class`, `etim_features`, GTIN | úplnost dle třídy (#83) | výkaz s ETIM/GTIN, objednávka |
| ECLASS | `eclass_class` (ID) | – | výkaz |
| BMEcat | – (importér) | XSD validace | – |
| AutomationML | – | – | případně export topologie (nízká priorita) |

---

## 13. Návrhy (návrh → mezera/issue → norma → náročnost)

| # | Návrh | Mezera / issue EnvoCAD | Norma | Náročnost |
|---|---|---|---|---|
| N1 | Oteplení z protokolu kusového ověření odstranit; nahradit polem „Ověření návrhu: způsob + doklad“ | #80 (`docx_export.py:229`) | 61439-1 čl. 10 vs. 11 | S |
| N2 | Atribut `verified: false` + text „orientační, neověřeno proti normě“ u všech výsledků Iz/oteplení (xlsx, docx, PDF, TZ, F7) | #80, #82 | 60364-5-52, TR 60890 | S–M |
| N3 | Kontrola „mimo rozsah metody TR 60890“ (ventilace, proud, rozměry) | #82 | TR 60890 | M |
| N4 | Strukturovaná jmenovitá data sestavy (`Layout.params` verzovaně) a kontrola úplnosti | – | 61439-1/-2 | M |
| N5 | Kusové ověření jako **data** (výsledky kontrol, datum, zkoušející), ne jen generovaný docx | šablona „po dodání“ v ROADMAP | 61439-1 čl. 11 | M |
| N6 | `Component.etim_class`, `etim_features`, `gtin` + `etim_map.json`; verze schématu knihovny a migrace | #83, #84, #70, inventura kap. 2 | ETIM | M |
| N7 | Importér BMEcat 1.2/2005 (stdlib XML + XSD), mapování ETIM → `params` | #84 | BMEcat, ETIM | M–L |
| N8 | Importér ETIM xChange JSON (JSON Schema validace) – otevřená licence (Apache 2.0) | #84 | ETIM xChange | M |
| N9 | Report úplnosti artiklů podle ETIM třídy (které EF chybí: Pv, Icu, rozměry) | #83, #70 | ETIM | S–M |
| N10 | Číslování `ref` podle písmenného kódu třídy (tabulka kódů jako data, bez textu normy) | ROADMAP ř. 112; `designation.py` | IEC 81346-2 | M |
| N11 | Rozhodnout RDS-PS (ISO 81346-10 / TS 81346-101) pro FVE; případně aspekt typu | – | ISO 81346-10, -101 | L (rozhodnutí) |
| N12 | Povinná DC pole stringu v artiklu modulu: Voc, Isc, teplotní koef., Imax OCPR; kontrola jištění stringu | `string_issues`, #79 | IEC 62548, 60364-7-712 | M |
| N13 | Kontroly 712: DC odpojení, SPD, PE FV pole, výstražné štítky | `checks.*` | IEC 60364-7-712 | M |
| N14 | Legenda značek s `iec_ref` a odkazem na zdroj (jen ID) | #76 | IEC 60617 | S |
| N15 | Atribuce QET a oddělení od IEC 60617 (ne kopie IEC DB) | #81 | IEC 60617 (copyright) | S |
| N16 | Volitelné `eclass_class` (jen ID), bez ECLASS dat v gitu | – | ECLASS | S |
| N17 | Export AutomationML | – | IEC 62714 | L (nedoporučeno) |
| N18 | Soubor mimo git pro normové tabulky (Iz, k/c) + načítání, test s fixture | #82 (otevřená otázka „jak ukládat“) | 5-52, 60890 | M |

---

## 14. Co se nepodařilo ověřit

- Přesné číslování a znění článků: IEC 61439-1 čl. 10.10 / 11.x (obsah kusových zkoušek a protokolu), IEC 60364-7-712 (DC odpojení, uzemnění, ochrana stringů), IEC 62548 (faktor k Isc),
  IEC 60364-5-52 (čísla tabulek v současném vydání) – za paywallem.
- Aktuální vydání a ČSN znění: ČSN EN 61439-1/-2, ČSN 33 2000-5-52, ČSN 33 2000-7-712, IEC 61082-1 (obsah).
- Který text TR 60890 (2014/2022) je v kódu `thermal.py`; interpretace omezení vůči 61439-1 (rozpor IEC/AFNOR vs. DKE).
- Úplný seznam písmenných kódů 81346-2 a jejich podtříd; přesný popis aspektu typu a konfigurace RDS-PS pro FVE.
- Existence **české/slovenské** jazykové verze ETIM a podmínky přístupu; ETIM třída pro FV modul; aktuální verze modelu.
- Licence PyAutomationML a PHP/.NET BMEcat knihoven; existence zralého Python parseru BMEcat/ETIM (hledal jsem jen jednou).
- Zda je ECLASS u cílových distributorů v ČR/SK používán; aktuální cena a podmínky (stránky ukazují 700 € pro 14.0 – ceník 2020 zastaralý).
- Zda ENVO je „původní výrobce“ rozvaděče ve smyslu 61439.

## 15. Otázky pro projektanta (shrnutí)

Q-1 značení: edice 81346-2, interní kódy, RDS-PS ano/ne, aspekt typu. Q-2 legenda: číslo IEC 60617, předplatné IEC DB. Q-3 61439: role výrobce, metoda ověření oteplení,
podpis, vydání. Q-4 oteplení: počítat ověřitelně, nebo jen předvýpočet + doklad; které vydání TR 60890. Q-5 712: které vydání, interní požadavky, vazba na 8-82.
Q-6 jištění stringů: interní zásady. Q-7 Iz: metody uložení, zdroj tabulek (ČSN vs. výrobci kabelů). Q-8 ETIM: dodavatelé s ETIM, česká verze, jediný zdroj parametrů?
Q-9 ECLASS: licence/zákazníci. Q-10 BMEcat: reálné vzorové soubory a smlouvy s dodavateli o použití dat.
