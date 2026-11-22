# 02B – Návrhové nástroje výrobců (Sichr, SIMARIS, ABB e-Design/DOC, Schneider, hagercad, Eaton, Rittal Therm)

Stav k 22. 11. 2026. Agent 2B, rešerše (jen čtení veřejných zdrojů, nic se neinstalovalo ani nestahovalo do repozitáře).
Vstup: `01a_inventura.md` (kap. 1, 5, 6) a `01b_issues.md` (souhrn). Odkazy na zdroje jsou v závorkách `[Sx]`, seznam v kap. 12.

Značení spolehlivosti: **[ověřeno]** = přečteno přímo v dokumentu výrobce; **[vyhledávač]** = jen z výsledku webového
vyhledávání, stránka se nepodařilo načíst celá; **neověřeno** = nenalezeno / nepotvrzeno. U každého nástroje je licenční
poznámka. Převzít se smí **myšlenky, metodika, struktura a fakta (čísla s odkazem)**, ne kód, databáze přístrojů, tabulky
selektivity ani texty a grafika protokolů (viz `CLAUDE.md`, „Licencovaná data“).

---

## 0. Hlavní zjištění (co z toho plyne pro EnvoCAD)

1. **Výpočet oteplení rozvaděče mají zdarma Siemens (SIMARIS therm), Rittal (Therm/RiTherm), Schneider (ProClima), Eaton
   (Temperature calculator) i ABB (Excel nástroj + modul v DOC).** Všechny stojí na stejném řetězci: ztrátový výkon přístrojů
   (Pv z katalogu výrobce, upravený proudem/RDF) + přípojnice + vodiče → porovnání s vyzářitelným výkonem skříně, případně
   teplota po výšce podle IEC TR 60890. Právě data Pv jsou jejich hlavní hodnota; vlastní vzorce jsou veřejně známé.
   → Pro #79/#80/#82 je k dispozici **zdarma použitelný referenční nástroj (SIMARIS therm, Rittal Therm) pro srovnávací
   příklady**; kód ani jejich databázi ale přebírat nelze.
2. **Žádný z nalezených výrobců veřejně neukazuje „protokol kusové zkoušky“.** Siemens, Rittal i Eaton generují
   *doklad o ověření oteplení* (design verification, 10.10), nikoli kusovou zkoušku (čl. 11). ABB uvádí oteplení výslovně jako
   „návrhové ověření“ [S19]. Struktura protokolu kusové zkoušky tedy z těchto zdrojů **nevyplývá – neověřeno** (kap. 11, otázka O1).
3. **Siemens therm přímo řeší problém z #80:** dokud projekt není uzavřen, vytiskne se do protokolu vodoznak „Project not
   completed“ [S6, kap. 2.9]. Totéž pro EnvoCAD: výstup výpočtu musí nést stav (orientační / ověřeno) a metodu.
4. **IEC TR 60890:2022 (3. vydání) mění oproti 2014** hranici platnosti (3 150 A → 3 200 A), přidává algebraickou rovnici pro
   křivky (podle IEC webstore) a přílohy o nerovnoměrném rozložení výkonu, slunečním záření, materiálu skříně a větrání [S13].
   Pro #82 je klíčové, **zda EnvoCAD křivky k, c čerpá z vydání 2014/1995 nebo 2022** – to musí potvrdit člověk s normou v ruce.
5. **Pro FVE specifika (DC stringy, Isc/Uoc podle teplot, optimizéry, MPPT, Tigo) nebyl nalezen žádný protějšek** v nástrojích
   výrobců nízkého napětí. Siemens uvádí jen obecně „renewable energy sources“ mezi výrobky SIMARIS design [S5]; DOC „cogeneration“
   a ostrovní provoz [S9]. **Výpočty `string_limits`, `optimizer_issues` nelze těmito nástroji ověřit** (neověřeno, že DC strana
   je kterýmkoli z nich pokryta).
6. **Selektivita, kaskádování a zkratové proudy** jsou postaveny na *tabulkách výrobce pro jeho vlastní přístroje* (OEZ „Selektivita
   vybraných jističů“, ABB „Coordination tables“) [S3, S9]. Tato data jsou licenčně i obsahově mimo EnvoCAD – bezpečná cesta je
   jen *ruční potvrzení projektantem s odkazem na výsledek v nástroji výrobce*, nikoli import tabulek.

---

## 1. OEZ Sichr

**Co to je.** Výpočtový program OEZ pro návrh a kontrolu vedení v sítích TN-C, TN-C-S a IT na všech obvyklých napěťových
hladinách nn; obsahuje databázi přístrojů OEZ (jističe, proudové chrániče, svodiče, odpínače) a *otevřenou* databázi
transformátorů a kabelů [S1] **[ověřeno]**. Běží na Windows 10 a novějších; stahuje se jako „portable“ (.exe nebo .zip)
z oez.cz [S1]. Podpora: softwarova.podpora.cz@oez.com [S1]. Verze v ukázce 20.07 (2020), soubor projektu `.oez` [S2].

**Co počítá a podle čeho.** Prezentace OEZ uvádí zkratové proudy, impedanci smyček, selektivitu, úbytky napětí,
dimenzování kabelů, jištění proudovými chrániči a odpínači a kaskádování (back-up) [S3, S2 – vyhledávač + ukázka]. Normové
reference: jištění kabelů podle ČSN 33 2000-5-52, ochrana proti nadproudům ČSN 33 2000-4-43 (čl. 431.4.2) [S3, vyhledávač].
Konkrétní edice norem ani vzorce **nejsou na webu uvedeny** (stránka produktu žádnou normu nejmenuje [S1]).
Pro selektivitu v oblasti zkratů program čerpá z dokumentu výrobce „Selektivita vybraných jističů 3VA2“ (mezní selektivní proud Is) [S2].

**Vstupy / průvodce.** Síť se kreslí a parametrizuje (zdroj/transformátor, vedení, rozvaděče, přístroje); detailní kroky
průvodce nebyly v dostupných dokumentech popsány – **neověřeno**. Ukázkový příklad (průmyslový podnik, 2 × 1 000 kVA, Ik″ = 46,5 kA)
slouží jako postup: přístroje + nastavení spouští → ověření úplné selektivity, jištění kabelů a odpínačů, ochrany automatickým odpojením [S2].

**Výstupy.** Příklad aplikace obsahuje **25 stran výstupů „tak, jak je program generuje“** (stránkové zápatí „n / 25 SICHR 20.07“)
[S2]; obsah stran je v PDF vložen jako obrázky, takže **struktura protokolu se z textu nedá přečíst – neověřeno**. K příkladu je
ke stažení soubor `.oez` [S2]. Export DXF/XLS **neověřeno**.

**Dostupnost / licence.** Veřejný download bez viditelné registrace; cena a licenční podmínky na stránce neuvedeny [S1] (neověřeno).
Databáze přístrojů je data OEZ – k opětovnému použití mimo Sichr **není licence známa**; v EnvoCAD ji nepřebírat.
Nezávislé údaje o chování (např. výsledek pro konkrétní obvod) jsou fakta uživatele a lze je ukládat jako referenční hodnoty.

**Co převzít:** (a) *typy kontrol* (smyčka, Ik min, úbytek, Iz vs. In, selektivita jako ano/ne s odkazem) jako seznam kontrol F7
a výkaz „ověření jištění“; (b) *ukázkové obvody* jako zdroj srovnávacích příkladů, které si projektant spočítá v Sichru a uloží
výsledky (viz kap. 9, položka P4). Detaily viz kap. 9.

---

## 2. Siemens SIMARIS (design, curves, project, therm, toolbox)

**Souhrn sady.** SIMARIS Suite (zdarma ke stažení po jednorázové registraci) sdružuje: *project* (prostorové nároky a rozpočet,
výběrová řízení, IFC/BIM), *design* (výpočet sítě a dimenzování s výběrem skutečných přístrojů), *curves* (vypínací charakteristiky,
let-through), *toolbox* (online kalkulátory), a samostatný *therm* [S4] **[ověřeno]**.

### 2.1 SIMARIS design
- **Počítá:** zkratové proudy, toky výkonů, úbytky napětí a energetické bilance v radiálních sítích; v „professional“ licenci
  i okružní/smyčkové sítě, paralelní provoz, **automatické vyhodnocení selektivity**; zohlednění ochrany osob, zkratové a přetížení,
  funkční vydrž, bleskové/přepěťové ochrany, přípojnicové systémy [S4]. Normy: „IEC, VDE“ [S4]; 2019 přehled uvádí zkrat podle IEC 60909
  a nastavení teploty pro úbytek napětí na kabelech/přípojnicích [S5 – vyhledávač].
- **Výstupy:** soupis přístrojů, schéma sítě v PDF/DXF/DWG, **seznam nastavení ochran a zkratových proudů** (pro přenos do přístrojů při
  montáži), export do SIMARIS project a Powerconfig [S4].
- **Dostupnost:** základní verze a „professional“ (multiuser licence) [S4]; technologické balíčky pro ~100 zemí v 20 jazycích [S4].
  Přesné ceny **neověřeno**. Data jsou omezena na výrobky Siemens (reálné přístroje).

### 2.2 SIMARIS curves
Vizualizace vypínacích charakteristik jističů a pojistek (IEC) včetně tolerančních pásem, let-through proudu a energie; výběr přístroje
zadáním objednacího čísla nebo filtrem; úprava nastavení posuvníky s okamžitým vlivem na selektivitu; **tisk (PDF) charakteristik
a nastavení**; mobilní aplikace Android/iOS [S4] **[ověřeno]**. Dostupné zdarma v rámci Suite (neověřeno výslovně).

### 2.3 SIMARIS therm (nejdůležitější pro #79/#80/#82)
Zdarma stahovaný nástroj pro **ověření oteplení rozvaděčů** podle IEC 61439-1 Beiblatt/Supplement 2 (a IEC 60204-1); Windows 7–10, .NET 4.6
[S7, S6] **[ověřeno]**. Z manuálu V 2.1 (11/2016) [S6]:

- **Dvě metody.** (1) *Jednoduchý odhad* – skutečný Pv skříně se porovná s *vyzářitelným výkonem skříně* zadaným výrobcem
  (preferováno, protože je ověřitelný zkouškou), nebo s koeficientem prostupu tepla k [W/m²K] (výslovně uvedeno jako „není definován
  v EN 61439-1“). (2) *Výpočet podle IEC 60890* – teplota uvnitř ve výškách 50 / 75 / 100 % skříně podle efektivní chladicí plochy;
  výsledek se porovnává s max. provozní teplotou přístrojů. Pokud je efektivní plocha příliš velká, skříň se rozdělí na fiktivní menší skříně.
  Pro některé velikosti skříní IEC 60890 není použitelná – SW to hlásí. Je i **křivka teploty po výšce** (4 body výšky, °C a ΔK) a lze zadat
  požadovanou teplotu → vrátí výšku a naopak [S6, příloha B].
- **Vstupy po krocích (průvodce):** 1 Definice projektu → 2 Návrh soustavy (skříň, **RDF** výchozí 80 %, **koeficient kabeláže**
  „wiring factor“ [doporučeno 30 % pro rozvody, u řídicích skříní víc], typ řady: solitér / střed / levý konec / pravý konec, vnitřní
  teplota, k nebo vyzářitelný výkon, rozměry) → přístroje (počet, počet pólů, jmenovitý a skutečný proud, využití, Pv) → přípojnice (průřez,
  měrný odpor, délka ≤ 2 400 mm, počet pólů; N se zadává jako samostatná 1-pólová přípojnice) → 3 Výpočet → 4 Výstupy [S6, S7].
- **Model Pv přístroje:** typ závislosti na proudu *lineární / kvadratická / konstantní*; Pv na pól vs. celé zařízení; typ „měnič“
  (Pv závisí na pracovním bodu). Kabely a vodiče lze přidat jako vlastní přístroj (kvadratická, 1 m, příklad v manuálu: 10 mm², 25 A, žlab,
  55 °C → 1,37 W/m jedné žíly; zdrojem uvedena IEC 61439-1 příloha H nebo katalog) [S6]. Bilance: Pv celkem = Pv přístrojů (s RDF) + kabeláž
  (koeficient) + přípojnice − výkon přidaného chlazení [S6, kap. 2.6].
- **Doplňky:** výběr ventilátoru/klimatizace (vyzářitelný Pv ventilátoru z průtoku V [m³/h], konstanta vzduchu f = 3,5 m³K/Wh do 1 000 m n. m.,
  ΔT; klimatizace přímo ve W) a **topení proti kondenzaci** P = A·k·ΔT (venku dvojnásobek) [S6, kap. 2.7–2.8].
- **Výstupy:** *protokol výpočtu (PDF)* dokládající dodržení teplotních mezí; *kusovník* CSV a XLSX; **vodoznak „Project not completed“**,
  dokud se projekt tlačítkem neuzavře; uzavřený projekt se při aktualizaci databáze nemění [S6, kap. 2.9]. Dodatečně lze přiložit
  graf teploty po výšce k protokolu [S6].
- **Data a licence:** zabudovaná databáze Pv přístrojů a skříní Siemens (letáček 2016: >20 000 hodnot [S7]; novější web: ~30 000 [S8, vyhledávač]),
  cizí přístroje se doplňují ručně nebo **importem z CSV/XLSX** (šablona „XLS Template“, volitelné sloupce, chybějící údaje se doplní z databází,
  chybový log do Excelu, zástupný znak `_`) [S6]. Odpovědnost za data třetích stran nese uživatel [S6]. Databáze Siemens je licencovaná data
  výrobce – **do EnvoCAD nepřebírat**; formát importu a strukturu lze převzít jako myšlenku.
- **Limity (manuál):** „SIMARIS therm neprovádí kontrolu, zda vybrané přístroje do skříně vůbec padnou“; kontrolu zástavby ventilátorů
  musí udělat uživatel [S6].

### 2.4 SIMARIS project / Toolbox
Prostorové nároky, rozpočet (cenu doplňuje regionální expert), výběrové texty (GAEB XML, RTF), IFC export, jednopólová schémata s tabulkou
technických dat [S4]. Pro EnvoCAD jen jako inspirace k #87 (rozpočet) a TZ/DSPS – převzít nic konkrétního.

**Dostupnost celkem:** Windows; Suite zdarma po registraci; professional licence placená (cena neověřeno). Podpora v ČR přes regionální experty [S4].

---

## 3. ABB e-Design, DOC a nástroje pro oteplení

**e-Design** je zdarma stahovaná „jednotná brána“ k návrhovému SW ABB: po registraci (přístupový kód e-mailem, EULA) stáhne a spravuje
jednotlivé programy, kontroluje aktualizace denně, jazyk a země se volí při prvním spuštění [S10 – manuál e-Design 2015]. Obsah sady:
DOC, CAT, EDS PowerCon, StriePlan atd. [vyhledávač] – **úplný aktuální seznam neověřen**. Ekip Connect je samostatný nástroj k nastavení
digitálních spouští [vyhledávač]. **„OPTISIZER“ jsem v ABB zdrojích nenašel – neověřeno, pravděpodobně jde o jiný produkt / jiný název.**

### 3.1 DOC (jednopólové schéma + výpočet) [S9 – manuál DOC, ověřeno]
- **Funkce:** kreslení jednopólových schémat a pomocných obvodů, výpočet proudů a úbytků, zkratové proudy, dimenzování kabelů nn/vn,
  dimenzování a výběr jisticích/spínacích přístrojů, **výpočet oteplení v modulárních rozváděčích ABB**, nastavení a koordinace ochran,
  ověření ochrany kabelů, tisk dokumentace. Sítě nn do 1 kV, TT/TN-S/TN-C/IT, generátory, kogenerace, ostrovní provoz; neomezený počet úrovní [S9].
- **Normy volené v průvodci „Plant Wizard“:** zkrat IEC 60909 (nebo NF C 15-100); dimenzování kabelů IEC 60364, CEI 64-8, UNE 20460, VDE 0298,
  NF C 15-100. **ČSN není samostatná volba** (ČR = IEC 60364) [S9]. Ověření ochran podle IEC 60364-4-43 (přetížení čl. 433, zkrat 434,
  nepřímý dotyk 413) [S9].
- **Výsledky dimenzování:** minimální průřez z kritéria *tepelného (dle zvolené normy)* a *úbytku napětí v jednom vedení < 4 % (uživatelsky
  měnitelné)*; nejlevnější přístroje z technicky vyhovujících; ruční změna produktu/průřezu se **zamkne „zámkem“** a při dalším výpočtu se
  jen kontroluje; změna průřezu mění impedance a může zneplatnit výběr jištění → nutný přepočet celého schématu [S9, kap. 4].
- **Ověření:** modul křivek ukazuje přetížení, zkrat, nepřímý dotyk a **selektivitu** (podmínky: omezení selektivity přiřazené při výběru
  jističů + křivky; vyšrafovaná oblast = maximální dosažitelná selektivita podle ABB „Coordination tables“); back-up z tabulek výrobce [S9, kap. 5].
- **Výstupy – „Print manager“:** 3 hlavičkové a 17 technických sekcí, které se zapínají zaškrtnutím: hlavička, *kritéria dimenzování a ověření*
  (normy + hlavní parametry, spolu s ověřením kabelů „odůvodňuje kladný výsledek“), *hypotézy zkratového výpočtu*, schéma, rozvaděče/zdroje,
  zkraty, **tabulka kabelů** (průřez, izolace, materiál, počet uložení dle normy, **Iz, provozní teplota, ztrátový výkon, úbytek %, R, X**),
  seznamy přístrojů s objednacími kódy, tabulka jističů s **nastavením spouští**, **tabulka ověření OK/–** (SC, CC, CI-TN, CI-TT), back-up,
  selektivita, zátěže. Export: **DWG/DXF, XLS, PDF**, makra `.blk`, projekt `.e-Design` [S9, kap. 7–8].
- **Dostupnost:** zdarma v e-Design s registrací (Windows 7 SP1+, ~3 GB) [vyhledávač]; nově i webová „DOCweb“ (podmínky neověřeny). EULA – data
  přístrojů ABB jsou chráněna; DOC omezuje výběr na přístroje ABB.

### 3.2 ABB výpočet oteplení rozvaděče
- **Excelový nástroj** s databází vybraných modulárních přístrojů a rozvodnic: z nabídky se vybere rozvodnice s dostatečným vyzářitelným
  ztrátovým výkonem → prokáže se vyhovující oteplení (ČSN EN IEC 61439-1 a -3); k dispozici webinář [S19 – česká stránka ABB, vyhledávač;
  celá stránka se nenačetla]. Verze a odkaz ke stažení **neověřeno**.
- Starší „ABB SACE overtemperature calculation tool (OTC)“: promo SW, „not for sale“, modul chlazení [vyhledávač, Scribd – neověřeno, dokument zastaralý].
- ABB technické dokumenty (workbook k IEC 61439, 1SDC007103G0202; TR 60890 postup, příklady) – **stránku se nepodařilo načíst (403)**,
  doporučeno otevřít ručně jako zdroj ověřených příkladů (kap. 11, O5).

**Co převzít z DOC:** strukturu „Print manageru“ (volitelné sekce, sekce *kritéria a normy* jako povinná příloha důkazu), „zámek“ ručního výběru
vs. automatický návrh, tabulku kabelů se sloupci Iz/ztráta/úbytek/R/X, tabulku ověření s OK/–, seznam nastavení spouští.

---

## 4. Schneider Electric: Ecodial / Power Design, Power Build Rapsody, ProClima

### 4.1 EcoStruxure Power Design – Ecodial (dříve Ecodial Advance Calculation)
Software pro návrh a dimenzování instalace podle **IEC 60364** a výpočet podle **CENELEC TR 50480**; zkraty podle TR 50480, volba a nastavení
jističů s ohledem na kaskádování a selektivitu, kabely dle IEC 60364-5-52, limity úbytku podle zvolené normy (hodnoty IEC 60364 vs. NF C 15-100),
tepelné namáhání: vyhovuje, když práh Isd < min. zkratový proud obvodu (IEC 60364 čl. 533.3.2) [vyhledávač – neoficiální kopie nápovědy ~2012–14].
Česká lokalizovaná verze V4.9 existuje [vyhledávač, FAQ se.com/cz]. Doporučeno primárně pro budovy [vyhledávač]. Dostupnost a ceny: **neověřeno**.

### 4.2 EcoStruxure Power Build – Rapsody
Konfigurační a nabídkový nástroj pro rozvaděče PrismaSeT (rozvaděčové firmy, instalatéři); nastavení obecných parametrů → automatické/ruční
rozmístění přístrojů; import projektů z Ecodialu; „plně IEC 61439“; Windows 10, vyžaduje internet a přihlášení k serverům Schneider; **ceny nezveřejněny** [S11,
vyhledávač]. Výpočet oteplení v něm **neověřeno** (nalezena jen vazba na ProClima přes Schneider – nepotvrzeno).

### 4.3 ProClima
Tepelné projektování rozvaděčů: odvod tepla stěnami skříně (IEC 60890 a „61.439 – heat exchange walls“), výběr chlazení/topení, vestavěná databáze
klimatu (sluneční záření, teploty), **databáze ztrátových výkonů „všech běžných přístrojů na trhu“** (v5.0) [S11, vyhledávač]. Je zdarma;
integrován do WSCAD ELECTRIX: Pv a rozměry skříně se berou z výrobcově nezávislé databáze článků, **chybějící hodnoty se vyžádají a uloží zpět do databáze**,
po výběru chlazení se komponenty přenesou do projektu jako „nový materiál“ [S12 – ověřeno]. Schneider výslovně uvádí, že Pv je u řady komponent
těžké najít [vyhledávač].

**Co převzít:** *chybějící Pv doplnit v místě použití a uložit do uživatelské knihovny* (vazba na #83); přenos výsledku výběru chlazení jako položky BOM.

---

## 5. hagercad / Hagercad Calc

- **Hagercad 6** (zdarma ke stažení, Windows 10/11, účet myHager): plánování a dokumentace instalací až 4 000 A, edice Basic/Expert/Premium, seznam materiálu,
  nabídky podle rozvaděče/seznamu/umístění [S14 – ověřeno]. Výpočty stránka *neuvádí* (zkrat, úbytek, selektivita, IEC 61439 – neověřeno).
- **Hagercad Calc**: podle výsledku vyhledávače nástroj pro dimenzování rozvaděče „podle směrnic VDI“, zkraty, úbytek napětí, toky výkonů,
  dimenzování kabelů, bilance výkonů, **selektivita** [S15 – vyhledávač, stránka se přesměrovala]. Oteplení rozvaděče **nenalezeno**.
- Dostupnost: stažení po bezplatném účtu myHager, nabídka se liší podle země [S15]. Konkrétní protokoly/formáty exportu **neověřeno**.
- V ČR je s Hagerem spojena i ETI-podobná nabídka rozvodnic (viz `01b` – větev `feature/papir-eti-svodice`); pro tuto rešerši bez významu.

---

## 6. Eaton: xSpider a Temperature calculator

### 6.1 xSpider (verze 3 / 3.5)
Grafický návrhový nástroj pro dimenzování sítí nn s přístroji Eaton; výpočty **vždy podle IEC**: zkratové proudy (1f/3f), úbytky napětí, rozdělení zátěže pro radiální
i smyčkové sítě; kontrola kabelů a ochran; **selektivita a back-up včetně otestovaných hodnot kombinací**; TN/IT/TT do 1 000 V; modul ArcRisk
(energie oblouku podle IEEE 1584:2002) [S16 – vyhledávač + Eaton stránky; stránku se nepodařilo načíst celou]. Registrace pro stažení, aktualizace ze souboru, podpora xspider@eaton.com.
Export DXF **neověřeno**. Licence: data Eaton jen pro přístroje Eaton.

### 6.2 Eaton Temperature Calculator
Zdarma (neověřeno výslovně) nástroj pro výpočet tepelných ztrát a **design verification oteplení podle IEC/EN 61439**; celkový proud se omezí na
jmenovitý proud sestavy; zahrnuje ztráty vodičů; **kusovník (BOM) z konfigurátoru xEnergy lze přímo nahrát** [S17 – vyhledávač].
Obsah protokolu a předpoklady o okolní teplotě **neověřeno**.

---

## 7. Rittal Therm / RiTherm

- **Therm (desktop 2008–) / Therm app / RiTherm (online)** – výpočet potřeby klimatizace rozvaděče. Rittal uvádí, že hodnocení *„se těsně opírají“*
  o IEC/TR 60890 AMD1/02.95 a DIN 3168 pro chladicí přístroje; verze Express a Expert; **kalkulátor ztrátového výkonu**; konfigurátor zpětného chlazení; dokumentace
  výsledků; aktualizace přes internet; letáček (dříve 30denní zkušební verze) [S18 – letáček, ověřeno]. Novější web: nástroj je online a zdarma, zahrnuje
  nadmořskou výšku, sestavy skříní s vlastními zónami ztrát, venkovní skříně, energetickou účinnost podle klimatické zóny, uhlíkovou stopu, F-plyny,
  **„normou vyhovující potvrzení o odvodu tepla“ (heat dissipation certificate)**, výběr jazyka dokumentace, integrace do EPLAN Pro Panel [S20, ověřeno z webu výrobce].
  Konkrétní normy novější web nejmenuje (neověřeno, zda přešel na IEC TR 60890:2022).
- **Efektivní chladicí plocha Ae podle způsobu instalace** (tabulka z katalogu Rittal, odkaz na IEC 890 / DIN 57 660-500) [S21 – ověřeno z PDF Rittal]:
  | Způsob instalace | A [m²] (B šířka, H výška, T hloubka) |
  |---|---|
  | solitér, volně stojící ze všech stran | 1,8·H·(B+T) + 1,4·B·T |
  | solitér na stěnu | 1,4·B·(H+T) + 1,8·T·H |
  | první/koncová skříň v řadě, volně stojící | 1,4·T·(H+B) + 1,8·B·H |
  | prostřední skříň, volně stojící | 1,4·H·(B+T) + 1,4·B·T |
  | první/koncová skříň na stěnu | 1,8·B·H + 1,4·B·T + T·H |
  | prostřední skříň na stěnu | 1,4·B·(H+T) + T·H |
  | prostřední skříň na stěnu, zakrytá střecha | 1,4·B·H + 0,7·B·T + T·H |
  Pořadí řádků odpovídá obrázkům v katalogu; **přiřazení vzorec ↔ obrázek jsem z textu PDF nepotvrdil jednoznačně – ověřit v normě** (O4).
  Jde o fakta/vzorce, vhodná jako **nezávislý test funkce `Ae`** v `model/thermal.py` (ne kopie kódu).
- Dostupnost: online zdarma, desktop dříve s časově omezenou zkušební verzí (údaje se rozcházejí podle stáří zdroje – neověřeno aktuální podmínky).
  Licence na data Rittal (skříně, chlazení) je proprietární.

---

## 8. Srovnávací tabulka

| Nástroj | Počítá | Normy (dle zdroje) | Výstupy | Dostupnost | Veřejná data Pv / charakteristik |
|---|---|---|---|---|---|
| OEZ Sichr | Ik, smyčka, selektivita, ΔU, kabely, RCD, kaskádování | ČSN 33 2000-5-52, -4-43 [S3]; edice neuvedeny | 25str. protokol (struktura neověřena), `.oez` | Win 10+, portable, bez viditelné registrace; cena neověřena | databáze přístrojů OEZ + otevřená kabelů/trafa – licence neznámá |
| SIMARIS design | Ik, ΔU, toky, selektivita (prof.), energ. bilance | IEC/VDE; IEC 60909 | seznam přístrojů, schéma PDF/DXF/DWG, seznam nastavení | Suite zdarma po registraci; prof. licence placená | jen přístroje Siemens; neveřejné |
| SIMARIS curves | charakteristiky, let-through | IEC | PDF křivky + nastavení | zdarma (Suite), mobilní app | Siemens |
| **SIMARIS therm** | **oteplení: 2 metody (vyzářitelný Pv / IEC 60890 po výšce), chlazení, topení** | IEC 61439-1 Suppl. 2, IEC 60204-1 | **PDF protokol (vodoznak „nedokončeno“), BOM CSV/XLSX** | **zdarma**, Win 7–10 | >20 000–30 000 Pv Siemens; import vlastních CSV/XLSX |
| ABB DOC (e-Design) | ΔU, Ik, kabely, přístroje, selektivita, back-up, oteplení modulárních rozvaděčů ABB | IEC 60909, IEC 60364 (+CEI, VDE…), IEC 60364-4-43 | Print manager 17 sekcí, DWG/DXF/XLS/PDF | zdarma po registraci | jen přístroje ABB; Coordination tables ABB |
| ABB Excel oteplení | oteplení rozvodnic (vyzářitelný Pv) | ČSN EN IEC 61439-1/-3 | Excel (neověřeno) | zdarma (neověřeno), webinář | databáze vybraných modulárních přístrojů |
| Schneider Ecodial / Power Design | kabely, Ik, jištění, selektivita | IEC 60364, CENELEC TR 50480 | tištěné protokoly (neověřeno) | česká lokalizace V4.9; podmínky neověřeny | databáze přístrojů Schneider |
| Schneider Rapsody | konfigurace PrismaSeT, nabídky | IEC 61439 | BOM/nabídka | Win 10, přihlášení; ceny nezveřejněny | Schneider |
| **Schneider ProClima** | **oteplení, klima, chlazení** | IEC 60890, 61439 (přes výsledky) | dokumentace; přenos do WSCAD | zdarma | databáze Pv „všech běžných přístrojů“ |
| hagercad 6 / Calc | plánování; Calc: Ik, ΔU, kabely, selektivita | VDI směrnice (Calc) | seznam materiálu, nabídky | zdarma, účet myHager | neověřeno |
| Eaton xSpider | Ik, ΔU, kabely, selektivita, arc flash | IEC; IEEE 1584 (ArcRisk) | neověřeno | registrace | Eaton |
| Eaton Temp. calculator | oteplení, ztráty vodičů | IEC/EN 61439 | design verification, BOM z xEnergy | neověřeno (pravděp. zdarma) | Eaton |
| **Rittal Therm / RiTherm** | **klima/chlazení, vyzářitelný Pv, Ae podle instalace** | IEC/TR 60890 AMD1, DIN 3168 (letáček) | **Potvrzení odvodu tepla (PDF/Word)**, EPLAN | online zdarma | Pv kalkulátor; Rittal skříně |

---

## 9. Co převzít do EnvoCAD (návrhy)

Náročnost: S = hodiny, M = 1–3 dny, L = týden a víc. Všechna oborová rozhodnutí jsou formulována jako otázka (kap. 11).

| # | Návrh | Mezera / issue EnvoCAD | Zdroj | Náročnost |
|---|---|---|---|---|
| P1 | **Stav a metoda ve výstupu výpočtu**: protokol/výkaz nese „NÁVRH / ORIENTAČNÍ / OVĚŘENO“ a seznam použitých norem + edice; neověřené hodnoty vodoznakem; uzavřený projekt se neupravuje při aktualizaci dat | #80, #82, #79 (důvěryhodnost); oteplení v `docx_export.py:229` | SIMARIS therm vodoznak [S6 §2.9]; DOC „kritéria dimenzování“ [S9 §7.2.2] | S |
| P2 | **Dvoustupňový model oteplení**: (A) bilance Pv celkem vs. vyzářitelný výkon skříně (zadaný výrobcem, jinak k) a (B) IEC 60890 teploty po výšce 50/75/100 %; porovnání s `t_max_c` přístrojů; výstup jako tabulka + graf | `thermal.py` (jen bez ventilace, orientační), #82 | SIMARIS therm [S6 §1.1, §2.6.2, příl. B] | M |
| P3 | **Model Pv přístroje**: typ závislosti na proudu (lineární/kvadratická/konstantní), pólově závislé vs. celkové Pv, RDF, koeficient kabeláže, typ „měnič“; ztráty kabelů a přípojnic jako zdroj tepla (RI²l) | 138 jističů bez Pv (#83), `thermal.device_temperatures` | SIMARIS therm [S6 §2.3, §2.5.9] | M |
| P4 | **Srovnávací příklady (regresní sada)**: 6–10 případů skříň + Pv + ambient + způsob instalace, výsledek spočten v SIMARIS therm i Rittal Therm; uloženo `tests/data/ref_thermal.json` jen jako čísla + odkaz + datum + verze nástroje; test s tolerancí | #82 (ověření konstant), #79 | SIMARIS therm, Rittal Therm (zdarma) [S6, S20] | M |
| P5 | **Nezávislý test efektivní plochy Ae** – 7 vzorců podle způsobu instalace (tabulka výše) proti `model/thermal.py` | #82 | Rittal katalog [S21] | S |
| P6 | **Mezní platnost IEC TR 60890**: hlásit „mimo rozsah“ (nucené větrání, příliš velká Ae → rozdělit na fiktivní skříně, proud > mez 3 150 / 3 200 A) místo tichého výsledku | #80, #82 | SIMARIS therm hláška [S6]; IEC TR 60890:2022 [S13] | S |
| P7 | **Algebraické křivky k, c z vydání 2022** místo čtení z grafů, pokud je projektant doloží z normy | #82 (konstanty „orientační“) | IEC webstore – změny 2022 [S13] | M (data od člověka) |
| P8 | **Průvodce „Oteplení rozvaděče“** v GUI: Skříň (rozměry, instalace, řada) → Přístroje (Pv z artiklu, doplnění chybějících) → Přípojnice/vodiče → Výsledek → Chlazení/topení → Výstup | `ui/` – chybí ventilace a přepážky; mezera Top10 | SIMARIS therm kroky 1–4 [S6, S7]; Rittal Therm tabs [S18] | M–L |
| P9 | **Doplnění chybějícího Pv v místě použití** a uložení do uživatelské knihovny (+ log chyb při importu CSV/XLSX, šablona „XLS Template“) | #83, #84, #70 | ProClima/WSCAD [S12]; SIMARIS import [S6 §3] | S–M |
| P10 | **Výkaz „Výpočty kabelů“** sloupce Iz, provozní teplota, ztráta [W/m], ΔU %, R, X, způsob uložení + stav ověření OK/– | `model/calc.py`, #79 | DOC tabulka kabelů a ověření [S9 §7.2.4, §7.2.9] | S–M |
| P11 | **Volitelné sekce dokumentace (Print manager)** – zahrnout/vypnout výkazy a „Kritéria a normy“ do PDF a protokolu | `doc_pdf.py`, #76 | DOC [S9 §7.1] | S |
| P12 | **Zámek ručního výběru** (průřez/artikl) vs. automatický návrh; po změně průřezu označit závislé kontroly za neaktuální | výběr jištění, `calc.min_cross` | DOC [S9 §4.5] | M |
| P13 | **Uživatelský limit úbytku napětí** (výchozí hodnota + přepis na projektu), zobrazený v protokolu | `calc.voltage_drop` | DOC (4 %, měnitelné) [S9] | S – hodnota = otázka O3 |
| P14 | **Seznam nastavení ochran** jako výkaz (vstup `Ir`, `Isd`, `tsd`, `Ii` zadá projektant) | selektivita, výkazy | SIMARIS design, DOC [S4, S9] | S |
| P15 | **Selektivita jen jako ruční potvrzení s odkazem** („ověřeno v Sichr/SIMARIS curves/DOC, soubor X, datum“), s kontrolou F7 „neověřeno“ | #79, jištění | Sichr, DOC, curves [S2, S9, S4] | S |
| P16 | **Topení proti kondenzaci a ventilátor** (P = A·k·ΔT, ventilátor Pv = V·ΔT/f s f = 3,5 m³K/Wh do 1 000 m n. m.) – vzorce odvozeny z popisu v manuálu, před použitím ověřit | oteplení – doplňky | SIMARIS therm [S6 §2.7–2.8] | S–M |
| P17 | **Potvrzení odvodu tepla** jako výstup (jedna strana: vstupy, Pv, plocha, výsledek, norma, edice, stav) | #80, protokol | Rittal „heat dissipation certificate“ [S20] | S–M |

---

## 10. Postup ověření vlastních výpočtů (návrh)

1. **Úroveň 1 – vnitřní invarianty (bez cizích nástrojů):** oteplení roste s Pv, klesá s Ae; Ae podle 7 vzorců pro známé rozměry; rozdělení na
   dvě skříně dá nižší ΔT; kvadratické Pv při poloviční proudu = 25 % (příklad uvádí manuál [S6]). Součet bilance v protokolu = součet řádků.
2. **Úroveň 2 – křížové srovnání s bezplatnými nástroji:** stejné vstupy (skříň, způsob instalace, Pv přístrojů, ambient) zadat do SIMARIS therm
   (režim IEC 60890: ΔT při 50/75/100 % výšky) a Rittal Therm; uložit výsledek + verzi nástroje + datum + odkaz do `tests/data`; toleranci a použití
   „vzorových“ hodnot potvrdí projektant (O2). Pozor na rozdíly: SIMARIS rozděluje velké skříně na fiktivní; Rittal počítá chlazení (cíl ΔT), ne teplotu
   po výšce (ověřit v praxi).
3. **Úroveň 3 – zkrat/smyčka/úbytek/Iz:** projektant spočítá 5–8 typických obvodů FVE (přívod AC střídače, páteřní kabel, přívod do RH, DC string –
   jen AC část) v **Sichr** a **DOC** a zapíše Iz, ΔU, Ik min, vypínací čas jako fakta s verzí nástroje; EnvoCAD je porovná (`calc.ampacity`, `voltage_drop`).
   DC strana tímto způsobem **neověřitelná** (viz 0.5).
4. **Úroveň 4 – norma:** hodnoty tabulek Iz a křivek k, c musí být nakonec ověřeny proti vydání normy (#79/#82); nástroje výrobců slouží jen
   jako *kontrola rozumnosti*, nikoli jako zdroj pravdy (každý má jiná zjednodušení a vlastní databáze).

---

## 11. Neověřené body a otázky pro projektanta

**Neověřeno (nepodařilo se potvrdit z veřejných zdrojů):**
- Struktura protokolu o kusové zkoušce (čl. 11 IEC 61439-1) u kteréhokoli z nástrojů; zda vůbec nějaký nástroj protokol kusové zkoušky generuje.
- Obsah 25stránkového výstupu Sichru (strany jsou obrázky); cena/licence Sichru; zda umí export DXF/XLS/PDF; zda má databáze kabelů licenci k dalšímu použití.
- Aktuální stav a ceny SIMARIS design professional; aktuální verze SIMARIS therm (nejnovější nalezený manuál 2016–2017, 11/2016).
- Seznam modulů e-Design a existence „OPTISIZER“; verze/odkaz Excelového nástroje ABB na oteplení; formát jeho výstupu.
- Zda Rapsody počítá oteplení; zda ProClima je zdarma pro všechny země; které vydání IEC TR 60890 používá Rittal Therm / ProClima.
- Hagercad Calc – skutečné funkce a výstupy (stránka přesměrována, popis jen z vyhledávače); xSpider – export DXF a formát protokolů; Eaton Temp. calculator – obsah výstupu.
- Přiřazení vzorec ↔ obrázek u 7 způsobů instalace podle IEC 60890 (ověřit v normě).
- Čísla ze SIMARIS manuálu použitá jako vzor (1,37 W/m pro 10 mm² 25 A; wiring factor 30 %; RDF 80 %; f = 3,5) – jde o údaje výrobce, ne o normu.
- Zda je legální ukládat výstupy z cizích nástrojů do repozitáře jako referenční fakta (EULA Rittal/Siemens/OEZ jsem nečetl).
- Webové stránky ABB, Rittal, Eaton, Schneider se místy nenačetly (timeout/403), údaje označené [vyhledávač] vycházejí jen z výsledku hledání.

**Otázky pro projektanta (oborová rozhodnutí – nedomýšlím):**
- **O1.** Co přesně má být v protokolu kusového ověření ENVO a co patří do návrhového ověření (oteplení čl. 10.10)? Má se oteplení z protokolu kusové zkoušky
  vyřadit (jak navrhuje #80) a nahradit samostatným dokladem o ověření oteplení s uvedením metody a stavu? (Podle ABB je oteplení „návrhové ověření“ [S19]; kusová zkouška je čl. 11 – k potvrzení.)
- **O2.** Jaké odchylky mezi EnvoCAD a SIMARIS therm / Rittal Therm jsou přijatelné (např. ±1 K nebo ±5 %)? Který nástroj je pro ENVO „referenční“?
- **O3.** Limit úbytku napětí (ČR/FVE): jaké hodnoty používáte pro DC stringy, AC přívod střídače a hlavní přívod (DOC používá 4 % jako výchozí, měnitelné)?
- **O4.** Máte k dispozici IEC TR 60890 (které vydání: 2014 nebo 2022) a IEC 61439-1 Beiblatt 2 pro ověření křivek k, c, tabulky Ae a rozsahu platnosti?
- **O5.** Můžete otevřít ruční zdroje (ABB workbook 1SDC007103G0202, 2CPC000339L0201) a vybrat příklady vhodné jako test?
- **O6.** Který způsob ověření oteplení ENVO skutečně používá: výpočet (60890), srovnání s referenčním návrhem, nebo zkoušku? Pro které proudy/skříně?
- **O7.** Jaký koeficient kabeláže (wiring factor) a RDF jsou pro rozvaděče FVE ENVO obvyklé? (SIMARIS uvádí 30 % / 80 %; je to vhodné pro AC/DC rozvaděče FVE?)
- **O8.** Chcete u selektivity jen „ruční potvrzení s odkazem na Sichr/SIMARIS curves“ (P15), nebo plánujete cokoli s tabulkami výrobců (právně rizikové)?
- **O9.** Jaké nástroje (Sichr, DOC, SIMARIS, Rittal Therm, ProClima) skutečně používáte v praxi? Podle toho zvolíme, proti kterým srovnávat.
- **O10.** Je pro vás důležitý import/export projektu do těchto nástrojů (např. seznam přístrojů s Pv do CSV pro SIMARIS therm), nebo stačí výstup PDF?

---

## 12. Zdroje (URL)

- **[S1]** OEZ – Sichr: https://www.oez.com/technical-support-software-support/computational-program-sichr
- **[S2]** OEZ – Příklad aplikace jističů 3VA2 v Sichru (Sichr 20.07, 25 stran výstupů): https://www.oez.cz/files/editor_source/Dokumenty/Katalogy/3va/Priklad_aplikace_jisticu_3VA2_v_Sichru.pdf
- **[S3]** OEZ přednášky / normy: https://www.oez.cz/files/editor_source/PDF-ke-stazeni/Aktuality-clanky/Prednaska_OEZ_1.pdf , https://www.oez.cz/files/editor_source/PDF-ke-stazeni/Aktuality-clanky/Norma%20%C4%8CSN%20332000_final.pdf (jen vyhledávač)
- **[S4]** Siemens – SIMARIS Planning Tools (brožura 2020): https://assets.new.siemens.com/siemens/assets/api/uuid:c8a7c3bd-32cd-4178-88d9-14c481c12c8f/2020-simaris-brochure-en.pdf
- **[S5]** Siemens – SIMARIS design tutorial / help: https://assets.new.siemens.com/siemens/assets/api/uuid:1b583352-e436-435a-9979-5003058133f2/tutorial-simaris-design-10-2-en.pdf (jen vyhledávač)
- **[S6]** Siemens – SIMARIS therm Operating Manual V2.1: https://www.stercontrol.pl/attachments/data/import/109744553_operating_manual_SIMARIS_therm_V2_1_en.pdf
- **[S7]** Siemens – SIMARIS therm flyer 2016: https://assets.new.siemens.com/siemens/assets/api/uuid:1c8e88ffd1c9c22eeae032099b2515d1f1f58cb5/version:1537342606/dfcp-b10055-01-7600-sb-berechnungstool-simaris-therm-en.pdf
- **[S8]** Siemens – SIMARIS therm (web): https://www.siemens.com/us/en/products/automation/industrial-controls/control-cabinet/tools-data1/tools/simaris-therm.html , https://siemens.com/us/en/industries/panel-building/temperature-rise-calculation.html (jen vyhledávač)
- **[S9]** ABB – DOC User Manual: https://library.e.abb.com/public/a7a540898e0685bdc1257e1a0048b3ef/DOC_UserManual_EN_SLD.pdf ; stránka DOC: https://new.abb.com/low-voltage/solutions/selectivity/tools-support/doc
- **[S10]** ABB – e-Design User manual: https://library.e.abb.com/public/40636f30b69349608218a538514c7ae5/e-Design_UserManual_EN.pdf ; přehled: https://new.abb.com/low-voltage/support/software/e-design/overview
- **[S11]** Schneider – Rapsody: https://www.se.com/nl/en/product-range/2309-ecostruxure-power-build-rapsody ; ProClima: https://www.se.com/be/nl/product-range/2560-proclima ; Ecodial FAQ: https://www.se.com/cz/cs/faqs/FA307441
- **[S12]** WSCAD – ELECTRIX + ProClima: https://blog.wscad.com/en/control-cabinet-planning-with-electrix-and-proclima/
- **[S13]** IEC TR 60890:2022: https://webstore.iec.ch/publication/66007 (rozsah a změny; text normy nečten)
- **[S14]** Hager – hagercad 6: https://hager.com/uk/digital-tools/hagercad
- **[S15]** Hager – Hagercad Calc: https://hagergroup.com/en/technologies-and-innovations/digital-tools/hagercad-calc (jen vyhledávač)
- **[S16]** Eaton – xSpider: https://www.eaton.com/ma/en-gb/catalog/low-voltage-power-distribution-controls-systems/xspider.html (jen vyhledávač)
- **[S17]** Eaton – Temperature calculator: https://www.eaton.com/dk/da-dk/support/tools/temperaturberegner.html ; https://www.eaton.com/lv/lv-lv/catalog/low-voltage-power-distribution-controls-systems/tc-tool.html (jen vyhledávač)
- **[S18]** Rittal – Therm software flyer: https://www.rittal.com/imf/none/5_326/Rittal_Software-Flyer_5_326 (tentýž obsah použit z https://de.slideshare.net/eeusc/khlung-mit-system-intelligent-cooling)
- **[S19]** ABB ČR – Nástroje pro výpočet oteplení rozváděče: https://new.abb.com/low-voltage/cs/vypocet-otepleni/ (jen vyhledávač)
- **[S20]** Rittal – RiTherm: https://www.rittal.com/RiTherm , http://www.rittal.com/therm
- **[S21]** Rittal – Systemklimatisierung, výpočet efektivní plochy (IEC 890 / DIN 57 660-500): https://www.rittal.com/imf/none/5_263
