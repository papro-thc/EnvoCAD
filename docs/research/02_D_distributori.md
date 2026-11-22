# 02D – Požadavky distributorů na dokumentaci připojení FVE

Stav k 22. 11. 2026. Agent 2D, rešerše (jen veřejné zdroje, nic nestaženo do repozitáře; PDF se četla z dočasných kopií
mimo repo). Kód ani GitHub se neměnily.

Značení: **[P]** = ověřeno v primárním dokumentu (text přečten), **[S]** = jen shrnutí webové stránky distributora
(stránka přečtena, ale PDF/obsah pod ní ne), **[N]** = neověřeno (jen výsledek vyhledávání nebo odvození).
Data modelu EnvoCAD vycházejí z `01a_inventura.md` a `01b_issues.md`; konkrétní klíče atributů jsem v kódu neověřoval
(„data v modelu“ = podle inventury).

Důležité upozornění: **požadavky se mění téměř každý rok** (ČEZ: připojovací podmínky nn od 1. 9. 2025, nové formuláře
A1/A2 od 1. 1. 2025; EG.D: nové formuláře 09/2025 a 10/2025, novinky UTP 4. 9. 2026; vyhláška 16/2016 Sb. v aktuálním
znění 1. 4. 2026; revize kodexu RfG „2.0“ se připravuje). Před nasazením kontroly do EnvoCAD vždy znovu otevřít
aktuální verzi dokumentu.

---

## 1. Společný právní a technický rámec (ČR)

| Zdroj | Co z něj plyne | Verze / datum | Stav |
|---|---|---|---|
| Vyhláška č. 16/2016 Sb., o podmínkách připojení k ES – příloha č. 1 (náležitosti žádosti o připojení) | Žádost obsahuje: údaje o žadateli; umístění (katastr, parcely, **katastrální mapa**, souhlas vlastníka nemovitosti); u výrobny/ZUE nad 0,5 MW harmonogram přípravy výstavby; **jednopólové schéma připojovaného zařízení umožňující posouzení žádosti** (bod B 6.4); možnost ostrovního provozu, **řízení přetoku v předávacím místě**, účiník a kompenzace; rezervovaný příkon/výkon, instalovaný výkon, 1f/3f; část C: druh výrobny, počet modulů, charakter (synchronní/nesynchronní), **typ modulu A/B/C/D**, instalovaný výkon, schopnost ostrovního provozu; ZUE: druh, výkon MW, **kapacita MWh** | aktuální znění k 1. 4. 2026 (e-Sbírka, kopie ČEZ) | [P] |
| Táž vyhláška – příloha č. 4 (zjednodušené připojení mikrozdroje / ZUE do **10,8 kW**, §16) | Povinné přílohy: **technická zpráva** (druh zařízení; u FVE typ, počet a výkon panelů; typ, počet, štítkové parametry měniče, činný/zdánlivý výkon, účiník, fáze, výrobce; možnost ostrovního provozu; **typy, parametry a hodnoty nastavení ochran**; zapojení ZUE), **výkresová dokumentace = jednopólové schéma včetně zapojení do odběrného místa s vyznačením rozpadového bodu**, **zpráva o výchozí revizi** s naměřenou impedancí smyčky v místě připojení, pokud součet výkonů > 800 W | totéž | [P] |
| Vyhláška 16/2016 §16 | Zjednodušené připojení jen NN, součet mikrozdrojů a ZUE v OM ≤ 10,8 kW, limit impedance smyčky (0,47 Ω u zdrojů do 16 A/fázi, 0,75 Ω do 10 A – udávají EG.D a PRE, v PPDS P4 čl. 4.6.1 také) | totéž | [P] (hodnoty impedance [P] z PPDS P4) |
| PPDS **příloha 4** (pravidla pro paralelní provoz výroben a akumulace) – kopie hostovaná ČEZ „Příloha 4 PPDS 2025“ | Definice JPS výrobny („do podrobnosti, aby z ní byla jednoznačně patrná funkce výrobny a souvisejících zařízení“); čl. 4.8 obsah projektové dokumentace; čl. 7 spínací zařízení (vazební spínač, galvanické oddělení všech fází, na AC straně střídače); čl. 8 ochrany (Tab. 7 pro ≤ 16 A / A1: U>> 1,2 Un/0,1 s, U> 1,15 Un/5 s, 10min průměr 1,11 Un, U< 0,7 Un/2,7 s, U<< 0,45 Un/0,2 s, f> 51,5 Hz/0,1 s, f< 47,5 Hz/0,1 s; Tab. 8 pro A2/B/C); čl. 12 UPOS/UTP; čl. 16 formuláře (dotazník, provozní oznámení o PPP, výsledky zkoušek) | označeno „2025“; na titulu **placeholder „datum a číslo rozhodnutí ERÚ“** → mohlo jít o nepodepsaný/pracovní text; verzi schválenou ERÚ je třeba ověřit | [P] (text), [N] (platnost) |
| Nařízení Komise (EU) 2016/631 (RfG) + Metodika ověřování souladu (MPO 2023) | Kategorie modulů A1/A2/B/C/D; u A1/A2 se UPOS nahrazuje **instalačním dokumentem** (čl. 30) s certifikátem zařízení / protokolem laboratoře / výjimkou ERÚ | – | [P] (odkazy v ČEZ dokumentech) |

**Kategorie výrobních modulů v ČR (ČEZ Tab. 1, platí i pro akumulaci):** A1 ≥ 800 W až ≤ 11 kW; A2 > 11 kW až < 100 kW;
B1 ≥ 100 kW až < 1 MW; B2 ≥ 1 MW až < 30 MW; C ≥ 30 až < 75 MW; D ≥ 75 MW [P] (ČEZ dodatek č. 2 k PP nn, od 1. 9. 2025;
u PREdistribuce a EG.D hranice [N], ale vycházejí z téhož RfG a PPDS P4).

---

## 2. ČEZ Distribuce

Zdroje: [PP nn 2026 (platnost od 1. 9. 2025)](https://www.cezdistribuce.cz/file/edee/distribuce/ppnn/2026/pripojovaci_podminky_nn.pdf) [P],
[Dodatek č. 2 – akumulace (od 1. 9. 2025)](https://www.cezdistribuce.cz/file/edee/distribuce/ppnn/20250901/ppnn_dodatek-c.-2-proces-pripojovani-akumulace.pdf) [P],
[Změny u modulů A1/A2 od 1. 1. 2025](https://www.cezdistribuce.cz/file/edee/distribuce/formulare/zmeny_vyrobni_modul_a1_a2.pdf) [P],
[PPDS příloha 4 2025 (kopie ČEZ)](https://www.cezdistribuce.cz/file/edee/distribuce/ppds/ppds-2025_priloha-4.pdf) [P],
[Formulář žádosti o připojení mikrozdroje (s přetoky), úprava 11/2024](https://www.cezdistribuce.cz/file/edee/distribuce/formulare/zadostopripojenimikrozdrojekdsnn_web.pdf) [P],
[Stránka Pro mikrozdroje](https://www.cezdistribuce.cz/cs/formulare/pro-mikrozdroje) [S].

### 2.1 Mikrozdroj do 10,8 kW (zjednodušené připojení, bez dodávky do sítě; rezervovaný výkon 0 kW)
- Povinné přílohy [S]: **zpráva o výchozí revizi OM** s naměřenou impedancí smyčky; **dokumentace skutečného provedení** =
  typy a nastavení ochran + **jednopólové schéma mikrozdroje v OM včetně akumulace**.
- Žádost obsahuje volbu **typového schématu** (samostatná FVE / FVE + akumulace na společném střídači / FVE + akumulace
  na samostatném střídači), nebo „vlastní schéma“ jako příloha (jednopólové schéma včetně akumulace) [P, formulář].
  ČEZ publikuje vzorová schémata ve dvou variantách (bez / s ostrovním provozem) [S].
- Formulář (standardní připojení, s přetoky) vyžaduje: instalovaný výkon pro výrobu, rezervovaný výkon, druh mikrozdroje, **schopnost
  ostrovního provozu ano/ne, baterie ano/ne a kapacitu kWh**, typ generátoru (se střídačem, 1F/3F), hlavní jistič před
  elektroměrem (A, 1f/3f), součtový příkon spotřebičů [P].
- Od 1. 1. 2025 smí být připojen jen **schválený typ střídače** (certifikát akreditované laboratoře – v ČR SZÚ 1045.1; nebo protokol odborné
  laboratoře ČEZ/EG.D; nebo výjimka ERÚ), prokazuje se **instalačním dokumentem výrobního modulu A1/A2**; více střídačů →
  každý musí být testován pro celkový instalovaný výkon modulu [P]. Seznam schválených střídačů je na webu ČEZ [P, odkaz].

### 2.2 Výrobna / akumulace do 100 kW na NN (PP nn čl. 4.1) [P]
- **Žádost o trvalý provoz (UTP/PPP)** obsahuje minimálně: PDS odsouhlasenou projektovou dokumentaci podle skutečného provedení (lze nahradit **předepsaným typovým
  jednopólovým schématem** z webu ČEZ); jednopólové silové schéma (pokud není v PD); potvrzení odborné firmy; **výchozí revize přípojky** (jen při změně)
  a **výchozí revize výrobny/akumulace**; **protokol o nastavení ochran rozpadových míst**; protokoly o úředním ověření MTP (je-li);
  **instalační dokument**. U A1/A2 se UPOS nahrazuje instalačním dokumentem; trvalý provoz až po vydání **Konečného provozního oznámení** (= protokol o PPP).
- Technické prvky, které mají být ve schématu/dokumentaci: **přijímač HDO** pro omezování činného výkonu (0/100 % Pi) osazuje PDS u Pi < 100 kW (příprava v elektroměrovém
  rozvaděči, napájení z přívodu před elektroměrem přes samostatný 1p jistič 2–6 A, výstražná tabulka „Pozor zpětný proud“, typové schéma č. 2 a 5 ve VP_01);
  **Q(U) a P(U)** autonomní charakteristiky; u 1f výroben Pi střídače max. 3,7 kVA/fázi; **ostrovní provoz → vazební spínač se schopností vypínat zátěž,
  předřazená ochrana**, náhradní zdroj nesmí být v trvalém paralelu; v elektroměrovém rozvaděči trvale přístupné **jednopólové schéma s vyznačeným MTP**.
- Instalovaný výkon FVE = součet jmen. výkonů panelů; u hybridu (společný střídač FVE + ZUE) vyšší z (Σ panelů, Pi střídače) [P] – pozor, na Slovensku se počítá
  jinak (viz 5).

### 2.3 Výrobna / akumulace ≥ 100 kW (PP nn čl. 4.2, 4.1 „dispečerské řízení“) [P]
- **Jednopólové silové schéma v PD musí mj. obsahovat**: hranici vlastnictví PDS/uživatel; spínací prvky pro odpojení míst připojení; **rozpadová místa**; celkový Pi (kW);
  celkovou kapacitu akumulace (kWh); u každé akumulace typ, druh (synchronní / asynchronní / se střídačem), Pi (kW), kapacitu (kWh), jmenovitý příkon; u každého VM typ zdroje, druh, Pi;
  odběrná zařízení pro PpS SVR; **umístění dispečerského měření a fakturačního měření**.
- **Technická zpráva PD**: typ regulace Q(U), omezování činného výkonu P (příp. příkonu P u akumulace), požadované nastavení ochran rozpadových míst (VP_05).
- **Tabulka telemetrie** (VP_02, XLSX; značení prvků dle PDS) je součástí PD; strukturální data dle přílohy 1 PPDS; řídicí jednotka (ŘJ) uživatele, omezování P ve stupních 0–30–60–100 % Pi;
  místní provozní předpisy (MPP); harmonogram zkoušek.
- Proces: **UPOS** (do 12 měsíců dočasné oznámení; předkládá se PD, JPS, potvrzení firmy, revize, protokol ochran, MTP, MPP, harmonogram) → **UTP** (strukturální data, dokument výrobního modulu, dokument ověření souladu akumulace, protokol z fyzického testu omezování P, kontakty pro periodickou zkoušku) → Konečné provozní oznámení. PDS vyjádření k PD do 30 dnů.
- Obsah PD podle PPDS P4 čl. 4.8 [P]: realizace požadavků z vyjádření PDS; délky, typy, průřezy vedení výrobna–místo připojení a parametry transformátorů; situační řešení;
  **typy, parametry a navržené hodnoty nastavení ochran**; řízení P a Q; zařízení pro snížení útlumu HDO (pokud nad limitem); návrh fakturačního měření a jeho umístění; rozhraní pro dálkové ovládání/měření/signalizaci;
  zařazení vyhrazeného technického zařízení (NV 190/2022 Sb.); popis funkcí ochran a automatik majících vazbu na DS. Neúplná PD se neposuzuje.
- Akumulace samostatně: JPS akumulace je povinná v žádosti o UPOS i UTP (dodatek č. 2) a obsahuje generátory, akumulátory, střídače, regulaci, informační vazby a vyvedení výkonu [P].

### 2.4 Oznámení o připojení výrobny v OM zákazníka (PPDS P4 čl. 4.6) [P]
Bez změny místa/způsobu připojení a rezervovaného příkonu (hlavní jistič), impedance pod limitem, ZUE jen na společném střídači s výrobnou, při ztrátě napětí odpojení celého OM,
logické rozhraní pro přerušení dodávky do 5 s, výchozí revize včetně **technických údajů výrobny jako nedílné součásti revizní zprávy** (typ a počet panelů, výkon panelu, typ/výrobce/počet střídačů, AC výkon střídače; kapacita akumulace). Pro > 800 W doložit soulad s RfG/PPDS P4 (instalační dokument).
Obsah oznámení dle čl. 16.6: souhlas vlastníka, místo připojení, napěťová hladina, **katastrální mapa**, **JPS včetně rozpadového místa**, Pi, rezervovaný výkon/příkon, kapacita akumulace, naměřená impedance, instalační dokument.

---

## 3. EG.D

Zdroje: [Připojení výrobny do 100 kW](https://www.egd.cz/zadost/pripojeni-vyrobny-do-100-kw) [S],
[Mikrozdroj NN](https://www.egd.cz/zadost/pripojeni-mikrozdroje-elektriny-nn) [S],
[Výrobna nad 100 kW / VN](https://www.egd.cz/zadost/pripojeni-noveho-odberneho-mista-s-vyrobnou-nad-100-kw) [S],
[Formulář D26 – zjednodušené JPS (0925)](https://www.egd.cz/sites/default/files/2025-09/0925_d26.pdf) [P],
[Formulář D58 – Oznámení o připojení výrobny/zařízení NN (1025)](https://www.egd.cz/sites/default/files/2025-10/1025_d58_0.pdf) [P],
[Článek o online formulářích, 21. 3. 2022](https://www.egd.cz/clanek/nove-online-formulare-pro-pripojeni-vyrobny) [S].

- **Online žádost NN (do 100 kW):** jednopólové schéma se **vybírá přímo ve formuláři** (typová varianta), souhlas vlastníka D34 / D40; podle okolností územně plánovací informace a harmonogram. Článek z 2022 uvádí, že JPS ani koordinační schéma
  se už nepřikládají jako samostatné přílohy [S, stáří 4 roky].
- **D26 (zjednodušené JPS, 09/2025)** [P]: druh výrobny, ZUE ano/ne + **celková kapacita ZUE**, **schopnost ostrovního provozu**, rezervovaný výkon (stávající/požadovaný) a pět typových zapojení:
  samostatná ZUE; samostatná FVE; FVE + ZUE na společném střídači; FVE + ZUE na samostatných střídačích; vlastní schéma. Pro každé: **jmenovitý výkon střídače (AC)**, **počet fází střídače**, **celkový instalovaný výkon panelů FVE**, kapacita ZUE, uspořádání elektroměr EG.D – spotřeba.
- **D58 (10/2025, oznámení o připojení NN)** [P]: důvod (nový paralelní zdroj / změna typu nebo výkonu / změna výrobce / změna rezervovaného příkonu), EAN a výrobní číslo elektroměru, adresa OM, katastr a parcela, **hodnota hlavního jističe (A, fáze)**, rezervovaný výkon, druh výrobny, ostrovní provoz,
  náhradní zdroj (typ, kW), údaje FVE (jako v D26), u jiných zdrojů „vlastní JPS jako příloha“ + generátor (asynchronní/synchronní, rozběhový proud), souhlas vlastníka (D40 pro více). **Povinná příloha: doklady o technickém řešení, z nichž je zřejmé splnění PPDS a předpisu EU.**
- **Mikrozdroj ≤ 10,8 kW** [S]: podmínky: bez dodávky (jen krátké přetoky omezovacího zařízení), impedance ≤ 0,47 Ω (16 A) / 0,47–0,75 Ω (do 10 A), **střídač max. 11 kW, výkonové omezení se nepovoluje**;
  přílohy: technická zpráva (typ/počet/výkon panelů, štítkové údaje střídače, ochrany, baterie) + JPS; revize s impedancí; **instalační dokument A1**; protokol o souladu střídače s PPDS P4; ŽÁDOST o UTP ani KPO se u tohoto typu nepodává.
- **UTP (výrobny nad mikrozdroj)** [S]: do 12 měsíců od termínu připojení ve smlouvě přes ppp.distribuce24.cz nebo D50; EAN, číslo smlouvy, adresa, technické parametry a dokumentace; KPO + výměna elektroměru. Novinky 4. 9. 2026: nový online formulář, výběr výrobních modulů, **číselník schválených střídačů** [S].
- **≥ 100 kW / VN** [S]: formulář D6, situační plánek, souhlas vlastníka, případně JPS a harmonogram; **PD dle PPDS P4 čl. 4.5 do termínu uvedeného ve smlouvě** (poznámka: v kopii P4 ČEZ je PD v čl. 4.8 – číslování se mezi verzemi liší); UPOS formulář D36 (B1, B2, C → souhlas s dočasným provozem; D → dočasné provozní oznámení), poté UTP.

---

## 4. PREdistribuce

Zdroje: [Mikrozdroj – zjednodušené](https://www.predistribuce.cz/cs/potrebuji-zaridit/vyrobci/pripojeni-vyrobny-k-distribucni-soustave/mikrozdroj-do-10-kw-zjednoduseny-zpusob-pripojeni-bez-moznosti-pretoku-s-rezervovanym-vykonem-0-kw/) [S],
[Mikrozdroj – standardní](https://www.predistribuce.cz/cs/potrebuji-zaridit/vyrobci/pripojeni-vyrobny-k-distribucni-soustave/mikrozdroj-do-10-kw-standardni-zpusob-pripojeni-s-moznosti-pretoku/) [S],
[Výrobna do 100 kW](https://www.predistribuce.cz/cs/potrebuji-zaridit/vyrobci/pripojeni-vyrobny-k-distribucni-soustave/vyrobna-do-100-kw/) [S],
[Výrobna nad 100 kW](https://www.predistribuce.cz/cs/potrebuji-zaridit/vyrobci/pripojeni-vyrobny-k-distribucni-soustave/vyrobna-nad-100-kw/) [S],
[Dokumenty ke stažení](https://www.predistribuce.cz/cs/potrebuji-zaridit/vyrobci/dokumenty-ke-stazeni/) [S] (stránky **nemají datum ani verzi**, jen rok 2026 v patičce).

- Žádost e-mailem/poštou, **zvlášť za každé OM**; NN (SP č. 1a) a VN/VVN (SP č. 1b). Doporučená předkonzultace s revizním technikem dle PN MM 501.
- **Dokumenty po realizaci** (zasílají se s podepsanou SOP) [S]: **JPS výrobny**; **dokument výrobního modulu** (A1 / A2 / B1 / B2 / C-D, vždy v synchronní a nesynchronní variantě – FVE = nesynchronní); **protokol nastavení parametrů ochran** (vlastní formulář „Nastavení ochran“);
  **provozní oznámení o provedení prvního paralelního připojení**; u NN **zpráva o výchozí revizi** a **„Podklad pro uzavření smlouvy na hladině NN“ potvrzený revizním technikem**. Připojení je dokončeno potvrzeným provozním oznámením.
- Zjednodušené připojení mikrozdroje: rezervovaný výkon 0 kW, bez dodávky (jen krátké přetoky), impedance před podáním žádosti; JPS je vyžadováno, ale **stránka neuvádí obsah** [S]. Dokument A1 neplatí pro ≤ 800 W.
- **Nad 100 kW** [S]: studie připojitelnosti → smlouva o smlouvě budoucí; **PD** dle P4, **PN KA 508** a dokumentu „Náležitosti k PD“ (včetně dispečerského řízení), vyjádření do 30 dnů; místní provozní předpis (příloha 8/9 PN KA 502); k uvedení do provozu: revize od střídače po rozvaděč, **JPS**, protokol ochran, schválený provozní předpis, provozní oznámení.
- Technické požadavky rozděluje PRE do **příloh PN KA 502** (SP 2–7 podle kategorie, synchronní/nesynchronní; **SP 8 = přehled základních způsobů zapojení a umístění silových prvků**; **SP 9 = podmínky připojení akumulace**) a PN KA 508 – **jejich obsah jsem nečetl** [N]. Typová schémata PRE jsou tedy pravděpodobně v SP 8.
- Příloha č. 1 ke smlouvě o připojení výrobny (podmínky připojení FVS) uvádí platnou výchozí revizi a JPS [S].

---

## 5. Slovensko – Západoslovenská distribučná (ZSD / ZSDIS)

Zdroje: [Žiadosť o pripojenie zariadenia na výrobu a/alebo uskladňovanie (formulár 12/2022)](https://www.zsdis.sk/documents/233/ZSD_Ziadost-o-pripojenie-zariadenia-na-vyrobu-EE-do-DS) [P],
[Malé zdroje do 10,8 kW – uzavretie zmluvy](https://www.zsdis.sk/Uvod/Vyrobcovia/Uzatvorenie-zmluvneho-vztahu/Male-zdroje-do-10-kW) [S],
[Malé zdroje – uvedenie do prevádzky](https://www.zsdis.sk/Uvod/Vyrobcovia/Uvedenie-do-prevadzky/Male-zdroje-do-10-kW) [S],
[Fotovoltická poradňa](https://www.zsdis.sk/Uvod/Online-sluzby/Fotovolticka-poradna) [S],
[Posúdenie možnosti pripojenia](https://www.zsdis.sk/Uvod/Vyrobcovia/Pred-pripojenim/Posudenie-moznosti-pripojenia) [S],
[Proces pripojenia (dokument, 1. 4. 2021, 114 s.)](https://www.zsdis.sk/documents/239/ZSD_Proces-pripojenia-zariadenia-na) [N – > 10 MB, nepřečten; číslování příloh jen ze snippetu].

- **Větší zdroj / formulář pro výrobu a ukládání:** povinné přílohy [P]: **kopie typových listů** (generátor, transformátor, střídač, kompenzace); **situační plán / ortofoto / katastrální mapa** s okolními objekty; **jednopólové schéma vyvedení výkonu od zdroje k dělicímu místu** s **uvedením typů zařízení a délek vedení**; osvědčení o výstavbě energetického zařízení (§ 12 zákona 251/2012) + studie realizovatelnosti, pokud je vyžadována.
  Formulář dále chce: výrobce, typ a počet panelů a **střídačů** (kW, kVA), **hybridní systém ano/ne**, baterie (výrobce, typ, počet, kW), **celkový instalovaný výkon**, EIC, požadovanou **maximální rezervovanou kapacitu** (MRK).
- **Malý zdroj do 10,8 kW** [S]: žádost přes e-Žiadosti; návrh smlouvy do 10 pracovních dnů; **stránka neuvádí povinné JPS ani revizi**. Uvedení do provozu: **čestné prohlášení o splnění technických podmínek (FVE)**, doklad o montáži odpínacího prvku zpětného napětí (u přímého měření do 80 A), smlouva o odpovědnosti za odchylku,
  oznámení o připojení od ZSD, teprve poté zapnout hlavní rozpojovací místo. Technické podmínky se určují pro každou žádost zvlášť. Hybridní systémy jen **certifikované** (seznam na stránce). Instalovaný výkon u FVE = **součet jmenovitých výkonů měničů na AC straně** (od 1. 12. 2022) – jiné než v ČR.
- **Hranice 10,8 kW** na webu ZSD [S]; dříve 10 kW. SK právní rámec (zákon 251/2012 Z. z., vyhláška MH SR 271/2012 Z. z. o rozsahu technických podmínek, technické podmienky PDS schvaľované ÚRSO) jsem **neověřil z primárního textu** [N].
- **Technické podmínky ZSD** (ochrany U/f, rozpojovací místo, síťová ochrana, seznam schválených síťových ochran) jsem nenašel/nečetl [N]; z cizích TP PDS jen orientačně: síťová ochrana jako samostatné zařízení s certifikátem, kontaktní (ne polovodičový) spínač, blokování opětovného zapnutí aspoň 30 s [N, jiný PDS].
- **SSD (východ, doplňkově):** [Vzorová JPS malého zdroje](https://www.ssd.sk/buxus/docs/dokumenty/vyrobcovia_elektriny/Schema%20jednopolova%20MP_A4_reader%20(1).pdf) [P, 27. 3. 2023] – RD, istenie max. 16 A, počet fází, hlavný istič, elektromer, **plombovaná časť RE**, **spínací prvok zdroja (QS1) za elektroměrem**, PEN mostík, menič (přesný typ, počet fází, menovitý výkon), FVS stringy, baterie (kWh). Nevyhovuje-li, žadatel přiloží vlastní JPS „opisujúcu skutočné pripojenie“.
- **VSD:** nezjišťováno [N].

---

## 6. Srovnávací tabulka

| Požadavek | ČEZ | EG.D | PRE | ZSD (SK) |
|---|---|---|---|---|
| Mikrozdroj – limit | ≤ 10,8 kW, 16 A/fázi, NN [P] | totéž, střídač ≤ 11 kW, bez výkonového omezení [S] | „do 10 kW“ v názvu stránek, vyhláška 10,8 kW [S] | ≤ 10,8 kW (dříve 10) [S] |
| JPS pro mikrozdroj | typové (3 varianty) nebo vlastní vč. akumulace; vzor s/bez ostrova [P/S] | typová D26 (5 variant) nebo vlastní; výkon střídače, počet fází, kWp, kWh [P] | vyžadováno, obsah neuveden [S] | ve webu neuvedeno [S]; SSD má vzor [P] |
| Rozpadové místo ve JPS | ano (vyhl. př. 4; PPDS; PP nn pro ≥ 100 kW) [P] | v PPDS; D26 jej nekreslí [P] | v PPDS [P], na webu neuvedeno | SK: „deliace miesto“, „hlavné rozpojovacie miesto“ [P/S] |
| Revize | výchozí revize OM s impedancí (mikro); výchozí revize výrobny/akumulace (UTP) [P/S] | revize s impedancí (mikro) [S] | výchozí revize + podklad potvrzený RT (NN) [S] | neuvedena pro malý zdroj [S] |
| Protokol nastavení ochran | ano (UTP, UPOS) [P] | formálně v P4; na webu neuveden [N] | ano (vlastní formulář) [S] | neověřeno [N] |
| Dokument modulu | **Instalační dokument A1/A2** + certifikát/protokol, schválený střídač [P] | instalační dokument A1 + protokol o souladu; číselník schválených střídačů [S] | **Dokument výrobního modulu** A1…C-D synchr./nesynchr. [S] | certifikované hybridy [S]; typový list [P] |
| PPP / KPO | UTP → KPO (= protokol o PPP) [P] | UTP (PPP portál/D50) → KPO; mikro bez UTP [S] | provozní oznámení o prvním paralelním připojení [S] | oznámení o pripojení / o prevádzke [S] |
| Situace / katastr | katastrální mapa (P4 čl. 16.6) [P] | situační plánek (> 100 kW), parcela v D58 [S/P] | neuvedeno [S] | situační plán + ortofoto/katastr [P] |
| HDO / omezení výkonu | přijímač HDO (< 100 kW), ŘJ (≥ 100 kW), 0-30-60-100 % [P] | neověřeno [N] | neověřeno [N] | MRK (rezervovaná kapacita), poplatek za překročení od 1. 1. 2026 [S] |
| Akumulace | v JPS vždy; ZUE na společném střídači pro oznámení [P] | v D26/D58 (kapacita, střídač) [P] | SP 9 PN KA 502 [N] | hybrid ano/ne, kapacita v kW střídače [P] |
| Výkon FVE pro „Pi“ | Σ panelů; hybrid: max(Σ panelů, Pi střídače) [P] | z D26/D58: výkon panelů + výkon střídače [P] | neověřeno [N] | **Σ AC výkonů měničů** [S] |
| Technická zpráva | popis zařízení, parametry regulace Q(U)/P, ochrany [P] | technická zpráva (mikro) [S] | nad 100 kW: PD dle KA 508 [S] | neuvedeno |

---

## 7. Kandidáti na automatické generování

Značení náročnosti: S = do cca 1 dne agenta, M = několik dní / dotčený model, L = velký rozsah nebo chybí podklady.

| ID | Kandidát | Distributor / kategorie | Data v modelu | Chybí | Nár. |
|---|---|---|---|---|---|
| G1 | **„Tabulka údajů zdroje“** (xlsx/docx/PDF) z topologie: Σ panelů kWp, počet a typ panelů, typy/počty/AC výkony střídačů, fáze, baterie kWh a kW, hybrid ano/ne, ostrov ano/ne, hlavní jistič, Pi dle pravidla distributora | všichni; podklad pro D26/D58, formulář ČEZ, ZSD | stringy, střídače, baterie, panely z artiklů (`Component.params`), hlavní jistič z rozvaděče (částečně) | EAN, požadovaný rezervovaný výkon, ostrov, pole `distributor`, výrobce/typ štítkových údajů (účiník, Smax) | M |
| G2 | **JPS „pro distributora“** = zjednodušený pohled na odvozené JPS (`model/single_line.py`): DS → hlavní jistič → elektroměr → rozpadové místo → střídač(e) → panely, baterie; s vyplněnými poli podle vzoru distributora (ČEZ 3 typová schémata, EG.D D26, SSD vzor) | ČEZ, EG.D, SSD; ZSD (přiložené JPS) | odvozené JPS existuje, střídače a baterie jsou prvky | symboly/role „elektroměr“, „rozpadové místo“, „HDO přijímač“, „hranice vlastnictví“, měření (fakt./disp.), popisky distributora | L |
| G3 | **Volba typového schématu** (samostatná FVE / FVE+ZUE společný střídač / samostatné střídače) automaticky z topologie + výpis polí k ručnímu přepsání do formuláře | ČEZ, EG.D | topologie hybrid/DC-coupled (hybridní střídač v generátoru) | mapování rolí → typ schématu | S |
| G4 | **Osnova technické zprávy** (docx přes `export/tz_export.py`, `doc_templates`): popis zařízení, panely, střídače, ochrany a jejich nastavení, regulace Q(U)/P, ostrovní provoz, akumulace, měření, situace | ČEZ (P4 čl. 4.8), PRE (PD pro KA 508), EG.D (PD ≥ 100 kW), vyhl. př. 4 | TZ/DSPS šablona existuje (`{{…}}`, `if/for`), data z projektu | nové šablony per distributor, kapitola o ochranách | M |
| G5 | **Seznam příloh / checklist k podání** (per distributor × kategorie × fáze: žádost, PPP/UTP, UPOS) s odškrtnutím, co je v projektu dohledatelné | všichni | – (čistě šablona) | databáze pravidel (JSON), vazba na kontroly | S |
| G6 | **Protokol nastavení ochran** – předvyplněný formulář (hodnoty Tab. 7 / Tab. 8 PPDS P4, typ ochrany, výrobce, firmware) k ručnímu doplnění naměřených hodnot | ČEZ, PRE, (EG.D) | existuje kontrola „síťová ochrana“ (inventura), `check_project`; hodnoty U/f v modelu zřejmě ne | atributy ochran (U>, U>>, U<, U<<, f>, f<, časy), druh ochrany (vestavěná ve střídači × externí NS) | M |
| G7 | **Tabulka telemetrie** (VP_02 XLSX, značení prvků PDS) | ČEZ ≥ 100 kW | – | vzor VP_02 (nečten) | L |
| G8 | **Podklad „Technické údaje o výrobně“ do revizní zprávy** (typ/počet panelů, výkon panelu, typ/výrobce/počet střídačů, AC výkon, kapacita akumulace) – ČEZ jej označuje za nedílnou součást výchozí revize | ČEZ (P4 čl. 4.6.1) | jako G1 | – | S |
| G9 | **Instalační dokument / dokument výrobního modulu – předvyplnění** (údaje o modulu, výrobce, typ, výkon, firmware, odkaz na certifikát) | ČEZ, EG.D, PRE | střídače z knihovny; `Component.datasheet_url`, `source` | formuláře nečteny (PDF od distributora, nesmí se kopírovat do repa); číselník schválených střídačů, číslo certifikátu | M |
| G10 | **Výstup do PDF/DXF s razítkem distributora**/popis „Jednopólové schéma připojení … dle PPDS P4“ (titulní strana, měřítko, čísla stran) | všichni | rámeček/razítko ENVO, PDF export | verze razítka pro distributora (dohoda s ENVO) | S |

Pozn.: Texty formulářů distributorů a jejich grafiku **nekopírovat** (CLAUDE.md: licencovaná data); generovat vlastní tabulku
se stejnými údaji a odkazem na zdroj.

---

## 8. Kontroly úplnosti (návrh pravidel pro F7)

„Data v modelu“: **J** = podle inventury už je, **Č** = částečně, **N** = chybí. Nové kódy nálezů by šly do `model/checks.py`
(plugin kontrolu přidat zatím nemůže – inventura 4.2/5.4).

| # | Pravidlo (JPS / projekt obsahuje …) | Distributor | Zdroj | Data | Nár. |
|---|---|---|---|---|---|
| K1 | JPS obsahuje **spínací prvek (vazební spínač) s galvanickým oddělením všech fází na AC straně střídače** mezi zdrojem a sítí | všichni (CZ) | PPDS P4 čl. 7 [P]; SSD vzor (QS1) [P] | Č (jistič/odpínač je prvek; funkce „vazební spínač“ ne) | M |
| K2 | **Rozpadové místo** je ve JPS označeno (atribut role) | ČEZ, EG.D, PRE | vyhl. 16/2016 př. 4 §1.2.1 [P]; P4 čl. 16.6 [P]; PP nn čl. 4 [P] | N | M |
| K3 | U každého střídače jsou uvedeny: **výrobce, typ, jmenovitý AC výkon (kW/kVA), počet fází** | ČEZ, EG.D, ZSD | D26/D58 [P]; vyhl. př. 4 [P]; ZSD formulář [P] | J/Č (artikl střídače, `ratings`) | S |
| K4 | **Σ výkon panelů (kWp)** a počet/typ panelů dohledatelné z modelu; u hybridu rozlišit Pi dle pravidla distributora | ČEZ (max), ZSD (Σ AC), EG.D | PP nn čl. 4 [P]; ZSD [S]; D26 [P] | J | S |
| K5 | **Typ modulu A1/A2/B/C/D** určený z instalovaného výkonu odpovídá hranicím (800 W, 11 kW, 100 kW, 1 MW …) a je uveden | ČEZ (EG.D, PRE obdobně) | ČEZ dodatek č. 2 Tab. 1 [P]; vyhl. př. 1 část C [P] | N (výpočet jednoduchý, pole `module_type` ne) | S |
| K6 | **Mikrozdroj:** Σ instalovaných výkonů zdrojů a ZUE v OM ≤ 10,8 kW; **střídač ≤ 11 kW** (EG.D); 1f ≤ 3,7 kVA/fázi (ČEZ) | ČEZ, EG.D, PRE | vyhl. §16 [P]; EG.D [S]; PP nn 4.1.7 [P] | J (součty) | S |
| K7 | U akumulace je uvedena **kapacita (kWh), výkon střídače (kW), zda je na společném / samostatném střídači** | ČEZ, EG.D, ZSD | D26 [P]; ČEZ formulář [P]; ZSD [P] | J (baterie v modelu), společný/samostatný = Č | S |
| K8 | **Ostrovní provoz:** je-li schopen, existuje vazební spínač se schopností vypínat zátěž s předřazenou ochranou a ve JPS je vyznačen; náhradní zdroj bez trvalého paralelu | ČEZ (PP nn 4.1.8), EG.D (D26/D58 pole), ZSD (hybrid) | [P] | N (příznak ostrova není v modelu) | M |
| K9 | **Měření:** ve JPS jsou elektroměr/fakturační měření a (≥ 100 kW) **dispečerské měření**; u nepřímého měření MTP | ČEZ, PRE | PP nn 4 [P]; PPDS P4 čl. 6 [P] | N/Č | M |
| K10 | **Přijímač HDO / příprava pro omezení P** (< 100 kW) nebo ŘJ (≥ 100 kW) vyznačen; logické rozhraní pro přerušení dodávky do 5 s | ČEZ | PP nn 4.1.5, P4 čl. 4.6.1 [P] | N | M |
| K11 | Je uvedena **regulace Q(U), P(U)** a omezování P (typ regulace) v TZ | ČEZ | PP nn 4.1.4, 4.2.3 [P] | N | S |
| K12 | **Hlavní jistič** v předávacím místě: hodnota (A) a počet fází uvedeny a odpovídají rezervovanému příkonu | ČEZ, EG.D | ČEZ formulář [P]; D58 [P] | J | S |
| K13 | **Hranice vlastnictví / dělicí místo** označeno (≥ 100 kW u ČEZ; SK vždy „deliace miesto“) | ČEZ ≥ 100 kW, ZSD | PP nn čl. 4 [P]; ZSD formulář [P] | N | M |
| K14 | U vedení mezi výrobnou a místem připojení jsou uvedeny **typ, průřez, délka** | ČEZ (PD), ZSD (JPS s délkami vedení) | P4 čl. 4.8 [P]; ZSD formulář [P] | J (kabely, `Cable.length`/`cross`) | S |
| K15 | V rozváděči (elektroměrovém) bude **trvale přístupné JPS** (a MTP) – kontrola, že existuje výstup JPS pro rozváděč | ČEZ | PP nn 2.4, 2.5, 2.6 [P] | Č | S |
| K16 | **Střídač je na seznamu schválených** (certifikát/protokol/výjimka) | ČEZ (od 1. 1. 2025), EG.D (číselník) | ČEZ zmeny A1/A2 [P]; EG.D [S] | N (artikl nemá příznak ani číslo certifikátu) | M |
| K17 | **Hodnoty ochran** v protokolu odpovídají PPDS Tab. 7/8 (U>>, U>, U<, U<<, f>, f<, časy) | ČEZ, PRE | P4 čl. 8.1, 8.2 [P] (výchozí doporučení; hodnoty vždy odsouhlasit s PDS) | N | M |
| K18 | **Katastrální údaje** (KÚ, parcelní čísla), **EAN**, **souhlas vlastníka** jsou vyplněny v projektu (`meta`) | všichni | vyhl. př. 1 [P]; D58 [P]; ZSD [P] | N/Č (investor ano) | S |
| K19 | Pro ZSD: výpis typových listů (generátor, střídač, transformátor); instalovaný výkon dle **AC výkonu měničů**; MRK | ZSD | formulář ZSD [P]; web [S] | Č | S |
| K20 | **Impedance smyčky** v místě připojení (≤ 0,47 Ω) zaznamenána (jen mikrozdroj) | ČEZ, EG.D, PRE | vyhl. př. 4; P4 čl. 4.6.1 [P] | N | S |
| K21 | **Seznam příloh** pro zvolenou kategorii a distributora je úplný (viz G5) | všichni | – | N | S |
| K22 | **Zdroj ≥ 100 kW:** existuje tabulka telemetrie a údaje o ŘJ; kapacita akumulace a Pi v kW ve JPS | ČEZ | PP nn 4.2 [P] | N | L |

Pravidla K2, K8, K9, K10, K13 vyžadují nové **atributy/role** (viz otázky) – bez nich je lze kontrolovat jen heuristicky.

---

## 9. Co už v modelu je a co chybí (shrnutí)

**Je (podle inventury):** topologie (`nn`/`vn`, `building`), strom DS → rozvaděče → střídače (`build_tree`), odvozené JPS a DXF, střídače/moduly/baterie/optimizéry
v knihovně artiklů, tabulky stringů a kabelů (`calc`, `Cable.length/cross`), kontrola „síťová ochrana“, TZ/DSPS šablony (`{{…}}`, docx), protokol kusové zkoušky (docx),
razítko ENVO, revize/změnový list, kontroly ERC (cca 80 kódů).

**Chybí:** pole žádosti (EAN, katastr, parcela, souhlas vlastníka, distributor, požadovaný rezervovaný výkon/příkon), typ modulu A/B/C/D, příznak ostrovního provozu,
role symbolů „elektroměr / rozpadové místo / hranice vlastnictví / přijímač HDO / měření dispečerské“, nastavení a typ síťových ochran (U/f, časy), příznak „schválený střídač“
a číslo certifikátu, impedance smyčky, výpočet Pi dle pravidla distributora, šablony per distributor, tabulka telemetrie.

---

## 10. Neověřené body a zastaralé zdroje

1. **PPDS příloha 4:** hostovaná kopie na webu ČEZ nese „2025“, ale titulní strana má placeholder pro rozhodnutí ERÚ – neověřeno, že jde o schválené znění; čísla kapitol (4.5 vs 4.8) se u EG.D a ČEZ liší. Příloha 4 pro EG.D a PRE se mohla od ČEZ lišit v detailech (společný text je jen předpoklad).
2. **EG.D:** obsah formulářů D6, D22, D34, D35, D36, D40, D50 jsem nečetl; „formulář D35 pro mikrozdroj“ je z vyhledávání, web jej nepotvrdil. Tvrzení „JPS není třeba přikládat“ je z článku z 3/2022 – může být zastaralé. Obsah JPS u ≥ 100 kW (jaké prvky) jsem u EG.D nezjistil.
3. **PREdistribuce:** neověřen obsah PN KA 502 (SP 2–9) a PN KA 508 („Náležitosti k PD“), tj. přesný obsah JPS; nepodařilo se nalézt vzorové schéma. Stránky bez data.
4. **ČEZ:** nečetl jsem VP_01 Schémata nn (typová schémata), VP_02 Tabulku telemetrie, VP_05 Nastavení ochran, formuláře instalačního dokumentu A1/A2 (jen odkazy). Dokument „dodatek_2_pripojovaci_podminky.pdf“ pod URL `ppnn/2026/` je shodný s dodatkem č. 2 z 1. 9. 2025 (akumulace), nikoli samostatný dokument.
5. **Slovensko:** primární technické podmínky ZSD a vyhlášku 271/2012 Z. z. jsem nečetl; SK požadavky na JPS u malého zdroje v ZSD z webu nevyplývají (stránky JPS nezmiňují) – nelze tvrdit, že není vyžadováno. Dokument „Proces pripojenia“ (1. 4. 2021) je velký a nepřečten; formulář žádosti je z 12/2022. Hranice 10 vs 10,8 kW – dle webu ZSD 10,8 kW.
6. **VSD a SSD:** nezjišťováno (kromě vzoru SSD). **ČEZ Distribuce, EG.D, PRE – VN:** zde jen letmo (≥ 100 kW), vyžaduje samostatnou rešerši (studie připojitelnosti, vyhl. př. 1 část C pro VN, MPP).
7. **Revize RfG 2.0 a změny PPDS** – možné další změny; zákon o podporovaných zdrojích a nová vyhláška o dispečerském řízení (242/2025 Sb.) mají vliv na ≥ 100 kW.
8. Část zdrojů je ze **shrnutí webových stránek** (označeno [S]); podle něj nelze považovat seznam příloh za kompletní.

## 11. Otázky pro projektanta (oborová rozhodnutí)

1. Jaké kategorie připojení ENVO reálně podává (mikrozdroj / do 100 kW NN / ≥ 100 kW / VN) a u kterého distributora nejčastěji? Podle toho seřadit G1–G10.
2. Chce ENVO JPS **ve formě distributora** (typová schémata ČEZ/EG.D) nebo vlastní JPS s doplněnými údaji? (Typová schémata distributorů jsou jejich grafika – kopírovat do repa nelze; vlastní výkres ve stejné logice ano.)
3. Jak se v ENVO značí **rozpadové místo**, hranice vlastnictví, vazební spínač, HDO přijímač a elektroměr? Mají se přidat jako role symbolů (`function_class`, atribut `role`) a v jakém označení (IEC 81346)?
4. Zdroj hodnot nastavení ochran (Tab. 7/8 PPDS P4) – brát jako výchozí z tabulky, nebo z dokumentu modulu (certifikovaný střídač)? Kdo schvaluje hodnoty?
5. Má EnvoCAD evidovat **seznam schválených střídačů** (ČEZ, EG.D) a číslo certifikátu? Odkud (jen odkaz `url`, bez kopie seznamu)?
6. Slovensko: je v plánu podávat žádosti do ZSD (resp. SSD/VSD)? Pokud ano, potřebujeme podklady (TP ZSD, vzory) od ENVO – web je neposkytuje.
7. Mají kontroly být **jen varování** (informativní), nebo blokovat export „sady pro distributora“? Jak označovat, že pravidlo pochází z dokumentu s datem (verze pravidel)?
8. Pro ≥ 100 kW: generovat také tabulku telemetrie a dispečerské podklady, nebo to dělá jiná profese?
9. Instalovaný výkon: potvrdit pravidlo pro hybridy (ČEZ: vyšší z Σ panelů a Pi střídače; ZSD: Σ AC výkonů měničů) a jak ho prezentovat, aby se nemíchaly.
10. Kdo/kde se bude udržovat **databáze pravidel** (JSON per distributor, verze, datum ověření)? Návrh: `envocad/library/builtin/distributors/*.json` s polem `verified_on` a `source_url` (agent nerozhoduje).
