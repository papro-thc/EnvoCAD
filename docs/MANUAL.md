# EnvoCAD – uživatelská příručka

Verze 0.10. EnvoCAD je nástroj pro elektro-dokumentaci fotovoltaických elektráren: jednopólové schéma (JPS),
rozvaděče (vícepólové schéma, svorkovnice, rozložení, oteplení), kabely, výpočty, výkazy a kompletní
dokumentace v jednom PDF. Všechno vychází z jednoho datového modelu – co nakreslíš, to se propíše do
všech výstupů.

---

## 1. Instalace a spuštění

Potřebuješ Python 3.11–3.13 (Windows i Linux).

```
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
scripts\run.ps1

# Linux
bash scripts/install.sh
scripts/run.sh
```

Skripty vytvoří virtuální prostředí `.venv`, nainstalují závislosti (PySide6, ezdxf, openpyxl, python-docx, segno)
a spustí program. Ručně: `python -m venv .venv`, aktivovat, `pip install -e .`, `python -m envocad` (na Windows
`py -m envocad`, pokud `python` otevírá Microsoft Store).

Samostatná aplikace bez Pythonu pro kolegy: `scripts\build.ps1` / `scripts/build.sh` sestaví složku
`dist/EnvoCAD` přes PyInstaller.

Uživatelská data jsou v `~/.envocad/` (Windows `C:\Users\<jméno>\.envocad\`): knihovna (`library.db`, vlastní
balíčky v `library/`), pluginy, nastavení (`settings.json`), logy (`log/`) a automatické zálohy (`autosave/`).

---

## 2. Okno programu

Vlevo jsou doky **Knihovna** (značky podle druhu prvku, s hledáním) a **Navigátor** (listy → prvky a vodiče,
s filtrem), uprostřed záložky listů, vpravo **Vlastnosti** vybraného prvku nebo vodiče. Nahoře je nástrojová
lišta s nejčastějšími akcemi, dole stavový řádek s nápovědou k aktuálnímu režimu.

Tmavý a světlý režim přepíná `Ctrl+D` (menu Zobrazit). Tisk a export jsou vždy černobílé na bílém.

Druhy záložek (podle názvu):

| Záložka | Co to je |
|---|---|
| `Jednopólové schéma` | JPS celé elektrárny – hlavní editační list |
| `R1 – schéma` | **vícepólové** schéma rozvaděče (odvozené, přístroje po pólech, svorky, můstky) |
| `R1 – jednopól (editace)` | jednopólová kresba rozvaděče – jen pro vkládání prvků a vodičů |
| `R1 – rozložení` | fyzické rozložení na DIN lištách + parametry skříně a oteplení |
| `R1 – svorkovnice` | kreslený plán svorkovnice |
| `… – vícepól` | vícepólový pohled libovolného listu JPS |

---

## 3. Kreslení jednopólového schématu

### Vložení prvku
Dvojklik na značku v Knihovně (nebo hledej: „jistič“, „střídač“, „string“) → klik do výkresu → vyplnit dialog
s parametry → OK. Režim vkládání trvá, dokud nezmáčkneš `Esc` nebo pravé tlačítko. Během vkládání `R` otáčí
značku o 90°.

V dialogu lze vybrat **artikl z knihovny** („Vybrat artikl z knihovny…“): typ, výrobce, In, póly,
charakteristika, Icu, moduly, ztrátový výkon atd. se propíší do prvku. Označení (F1, Q2, T1…) se předvyplní
podle písmene IEC 81346 a program hlídá duplicity.

### Vodiče
`W` (nebo tlačítko Vodič) → klik na port prvního prvku → klik na port druhého → dialog: označení (W1…), typ
kabelu, průřez, délka, trasa/uložení a **žíly** (např. `L1 L2 L3 N PE`, `DC+ DC-` – předvolby v rozbalovacím
seznamu). Výchozí žíly se odvodí z portů a pólů (DC port → `DC+ DC-`, 3pólový prvek → `L1 L2 L3 N PE`).

V JPS je každá čára jednopólová – jedna čára = jeden kabel se všemi žílami. FV string má jeden port DC,
střídač vstupy DC1/DC2 (MPPT) a AC.

### Úpravy
Dvojklik na prvek nebo vodič otevře dialog s parametry, panel Vlastnosti upravuje jednotlivé atributy přímo.
Tažení myší posouvá (snap 2,5 mm), `R` otáčí, `Delete` maže, `Ctrl+Z`/`Ctrl+Y` vrací. `Ctrl+C`/`Ctrl+V`
kopíruje vybrané prvky včetně vodičů mezi nimi – kopie dostanou nová označení a posun 10 mm. Výběr více prvků
tažením rámečku v prázdné ploše. Kolečko zoomuje, střední tlačítko posouvá pohled, `Home` přizpůsobí list.

### Přerušovací body
Prvek **Přerušovací bod** (Svorky a propojení) přenese potenciál jinam – dva body se stejným označením se
spárují a každý ukazuje polohu protějšku (`→ /2.C3` = list 2, sloupec C, řádek 3 v síti rámečku).

### Ovládací obvody
Značky **Cívka** (K, A1/A2), **Kontakt NO** (13/14), **Kontakt NC** (21/22) a **Hlavní kontakt**. Kontakt
dostane označení své cívky (K1); pod cívkou se automaticky kreslí zrcadlo kontaktů (svorky + poloha) a u
kontaktu odkaz na cívku. Kontakty nejsou samostatné položky ve výkazu materiálu, patří k cívce.

---

## 4. Rozvaděče

### Založení
V JPS vlož **Rozvaděč (blok)** (R1), zapoj do něj kabely a dvakrát na něj klikni. Poprvé program nabídne
**šablonu**: *AC rozvaděč FVE* (přívod, hlavní vypínač, rozvodné svorky s můstky, SPD, vývody s jističi),
*DC rozvaděč* (stringy s pojistkami, svorky, SPD DC, odpínač DC), nebo prázdný list. Otevře se záložka
`R1 – schéma` – vícepólové schéma rozvaděče.

Blok v JPS dostane **porty podle přívodů a vývodů** listu (X1 vlevo, X4, X5… vpravo). Kabel zakreslený na port
X4 se sám naváže na vývod X4: vývod převezme kabel, žíly a text „kam“, u kabelu v JPS se objeví křížový odkaz
`→ R1:X4 /2.B4`. Když vývod přejmenuješ nebo přidáš, blok se přestaví sám; na smazaný vývod s kabelem
zůstane port označený `?`.

### Vícepólové schéma
Je odvozené z jednopólové kresby rozvaděče – nic se nekopíruje. Průchozí přístroje (jistič, odpínač,
chránič, stykač) se kreslí po pólech s čárkovanou mechanickou vazbou a společnou spouští, N a PE jdou kolem;
pojistky, SPD a svorky po pólech bez vazby. Automatické rozmístění je po sloupcích podle toku od přívodu
(svorkové schéma); prvky jdou chytit a posunout myší, `Zobrazit → Vícepól: rozmístit automaticky` vrátí
automatiku. Dvojklik na prvek = parametry, dvojklik na žílu = svorky, `Delete` maže.

Vkládání nových prvků a vodičů do rozvaděče se dělá v záložce `R1 – jednopól (editace)` (`Ctrl+J`, menu
List → Rozvaděč – jednopólová editace); `Ctrl+M` tě vrátí do vícepólu.

### Svorky a můstky
Prvek **Svorkovnice** (`sb.terminal_block`) je v JPS *skupina svorek* jedné svorkovnice: označení X2 a
v atributu „Svorka č.“ čísla (`1 2 3 4 5`, nebo jen první číslo – zbytek se dopočítá). Ve vícepólu má každá
žíla vlastní svorku s číslem. `Úpravy → Očíslovat svorky automaticky` doplní chybějící čísla (skupiny i
přívody/vývody/PE lišta), ruční čísla nechá.

`Úpravy → Svorkovnice a můstky…` (`Ctrl+Shift+T`): tabulka svorek vybrané svorkovnice (vnitřní/vnější strana,
můstek) a editace **můstků** – jedna skupina na řádek, čísla svorek pomlčkou (`1-6-11-16`). Můstky se kreslí
ve vícepólu, v JPS čárkovaně mezi skupinami, a jsou ve výkazech a BOM.

`Ctrl+T` (Svorky vybraného vodiče) přiřadí svorky ručně po žílách (`X1:3`, `F2:1`) – pro přívody, vývody a
prvky bez skupin svorek.

### Plán svorkovnice
`Zobrazit → Plán svorkovnice` (`Ctrl+Shift+M`): svorky v řadě, nahoře vnější připojení (kabel z JPS),
dole vnitřní (přístroj), můstky. Export do PDF, stejná data jsou i jako list ve výkazech.

### Rozložení a skříň
`Ctrl+L` otevře rozložení: DIN lišty podle řad, přístroje se přetahují na lišty (snap 0,5 modulu), vpravo
panel **skříně**: označení, řady, moduly na řadu, rozměry, rozteč řad, IP/IK, montáž, materiál, dveře, Un/In/Icw,
síť, rezerva, teplota okolí, RDF (`Ctrl+K` otevře totéž jako dialog; skříň lze vybrat z artiklů).
Panel ukazuje obsazenost a **odhad oteplení** podle IEC TR 60890 (ΣPv z atributů `p_loss_w` nebo odhad
z In a pólů, chladicí plocha podle montáže, Δt uprostřed a v horní části, hodnocení). Parametry skříně se
kreslí v informačním bloku listu rozvaděče a jdou do protokolu kusového ověření.

Pozor: hodnoty křivek k a c v tabulkách jsou orientační – pro průkaz ověř proti normě.

---

## 5. Kabely

Kabel je objekt: vzniká automaticky z vodiče JPS, který má označení nebo typ kabelu, a drží s ním krok
(typ, průřez, délka, trasa se editují ve vodiči). `Úpravy → Kabel vybraného vodiče…` (`Ctrl+Shift+K`) otevře
žíly s čísly a **barvami** (ČSN 33 0165: L1 hnědá, L2 černá, L3 šedá, N modrá, PE zelenožlutá, DC+ červená,
DC− černá – jdou přepsat), stínění, poznámku a artikl kabelu z knihovny (CYKY, AYKY, H1Z2Z2-K…).

Výkazy **Kabely** (přehled), **Kabelový plán** (po žílách odkud–kam, i na svorky) a **Zapojovací seznam**
(všechna propojení včetně vnitřku rozvaděčů s barvou a průřezem).

---

## 6. Kontrola projektu a výpočty

`F7` (Úpravy → Kontrola projektu) projde celý projekt a vypíše nálezy – dvojklik skočí na prvek:

- chyby: duplicitní označení, vodič na neexistující port, vodič na smazaný prvek, string mimo rozsah střídače,
  kabel přetížený (I > Iz) nebo nechráněný (In jističe > Iz);
- varování: nezapojené porty/prvky, skupiny svorek bez čísel, rozvaděč bez listu, můstky na neexistující
  svorky, přerušovací bod nebo kontakt bez protějšku, úbytek napětí přes mez;
- informace: přívod bez vazby na JPS, prvek bez artiklu, vodič bez kabelu/žil, selektivita nejistá.

Výpočty (`model/calc.py`, výkaz **Výpočty**): kontrola stringu proti střídači (Uoc při −10 °C vs. Umax,
Umpp při 70 °C vs. rozsah MPPT, 1,25·Isc vs. Imax vstupu – atributy stringu Uoc/Umpp/Isc modulu a teplotní
součinitel, atributy střídače Umax, MPPT min/max, Imax), proud kabelem (1,25·Isc, P_AC/√3·U, In),
zatížitelnost Iz podle ČSN 33 2000-5-52 pro uložení A1/B1/C/D/E (atribut vodiče „Uložení dle ČSN“, nebo se
pozná z textu trasy: „v zemi“, „trubka“, „na vzduchu“, „ve stěně“), In ≤ Iz, úbytek napětí (mez 3 %) a
základní selektivita (poměr In po cestě ke zdroji ≥ 1,6). Tabulky Iz jsou orientační přepis normy.

`Ctrl+F` najde prvek nebo vodič podle označení kdekoli v projektu; Navigátor umí totéž s filtrem.

---

## 7. Nový projekt z průvodce (a pro agenty)

`Ctrl+Shift+N` (Soubor → Nový projekt z průvodce): zadej projekt a investora, modul (typ, Wp, Uoc, Umpp, Isc),
střídač (typ, P AC, Umax, rozsah MPPT, Imax), stringy po střídačích (`20,20,18; 20,20`), kabely a jištění.
Vygeneruje se JPS (stringy → DC rozvaděče → střídače → AC rozvaděč → síť) a listy všech rozvaděčů včetně
kabelů a vazeb. Hned potom spusť `F7`.

DC strana se dělá jako na stavbě: ke každému střídači vznikne **DC rozvaděč po trase** (počet zadáš, i 0 –
odpínač DC a SPD na každý string, stringy jím procházejí odděleně) a **DC rozvaděč u technologie**
(pojistkové odpínače gPV a SPD DC na každý MPPT). Blok DC rozvaděče v JPS má porty podle přívodů
(X1…Xn od stringů) a vývodů (Xn+1… dál). Když obojí vypneš, vloží se jen samostatný odpínač DC v JPS.
AC rozvaděč má přívody po střídačích, jističe, rozvodné svorky s můstky, SPD, hlavní vypínač a vývod do HDS.
Označení jsou jedinečná uvnitř každého rozvaděče (jako v EPLAN `+RDC1-X1`), takže X1 smí být v každém
rozvaděči; listy JPS sdílejí jeden prostor označení.

Totéž umí příkaz `python -m envocad.generate spec.json vystup.ecp` – specifikace je JSON popsaný
v `envocad/generate.py`. To je cesta pro AI agenty: z poptávky a datasheetů připraví specifikaci, program
vygeneruje projekt, ty ho upravíš.

Výchozí hodnoty (kabely, zpracoval) bere průvodce z **firemního standardu** (menu Knihovna).

---

## 8. Výstupy

| Výstup | Kde |
|---|---|
| PDF listu (skutečný formát / zmenšený na A4) | Soubor → Export PDF / Export PDF na A4 |
| DXF listu | Soubor → Export DXF |
| **Celá dokumentace do jednoho PDF**: titulní list, obsah, listy JPS, schéma + plán svorkovnice každého rozvaděče, výkazy, změnový list | Výstupy → Celá dokumentace (`Ctrl+Shift+E`) |
| Výkazy xlsx (Data pro DS, Výpočty, Přístroje, Výkaz materiálu, Kabely, Kabelový plán, Zapojovací seznam, Svorkovnice, Plán svorkovnice, Štítky) | Výstupy → Výkazy listu / projektu |
| Protokol kusového ověření rozvaděče (docx) | Výstupy → Protokol kusového ověření |
| Technická zpráva (docx) – kostra s tabulkami z modelu a výpočty | Výstupy → Technická zpráva |
| Štítky pro tiskárnu (CSV, `;`, UTF-8 BOM) | Výstupy → Štítky pro tiskárnu |

Rámeček listu má popisové pole (projekt, zakázka, investor, místo, list, číslo listu, zpracoval, datum,
revize, formát), souřadnicovou síť A–H × 1–6 a QR kód s identifikací výkresu. Údaje se zadávají v
Soubor → Vlastnosti projektu, název firmy v popisovém poli v nastavení (`standard.company`).

### Revize
Soubor → Vlastnosti projektu: revize, datum, změnový list (řádek = `revize | datum | popis | zpracoval`).
**Porovnat s revizí (.ecp)** porovná aktuální projekt se starší uloženou verzí (prvky, vodiče, kabely, můstky,
skříň) a jedním tlačítkem zapíše změny do změnového listu; dvojklik skočí na změněný prvek.

---

## 9. Knihovna

Knihovna má **značky** (JSON, vlastní FVE/rozvaděčové/ovládací + 673 značek QElectroTech ve složkách „QET“)
a **artikly** (CSV, přes 700 položek: OEZ Minia a 3VA, Eaton xPole, Schneider, Hager, Weidmüller, Elektro
Bečov a ELEMAN svorky, SMA, SolaX, Huawei, BMR, skříně, kabely). Artikl nese parametry, které se propíší do
prvku, rozměry pro rozložení a ztrátový výkon pro oteplení.

- **Prohlížet artikly…** – přehled s filtrem výrobce / In / póly.
- **Importovat artikly z CSV…** – vlastní artikly (formát `docs/COMPONENTS.md`, validátor
  `python -m envocad.library.components validate soubor.csv --symbols`).
- **Importovat symbol z DXF…** – značka z DXF výrobce; vlastní značky také jako JSON do `~/.envocad/library/`
  (formát `docs/LIBRARY_FORMAT.md`, včetně vícepólové podoby `multipole`).
- **Sdílená knihovna (síťová složka)…** – složka s JSON/CSV, kterou sdílí celá firma; načítá se navíc
  k vestavěné a stejná id přebíjí.
- **Firemní standard…** – výchozí kabely, zpracoval, název firmy (`~/.envocad/settings.json`).
- Pluginy: `~/.envocad/plugins/*.py` s funkcí `register(ctx)` přidají menu, šablony, importéry nebo výkazy.

Data artiklů jsou opsaná z veřejných katalogů (zdroj a strana je u každého řádku) – před použitím
v projektu je ověř u výrobce.

---

## 10. Klávesové zkratky

| Zkratka | Akce |
|---|---|
| `Ctrl+N` / `Ctrl+Shift+N` | nový projekt / z průvodce |
| `Ctrl+O`, `Ctrl+S`, `Ctrl+Shift+S` | otevřít, uložit, uložit jako |
| `W` | kreslit vodič |
| `Esc` | zpět do výběru |
| `R` | otočit o 90° |
| `Delete` | smazat |
| `Ctrl+Z` / `Ctrl+Y` | zpět / znovu |
| `Ctrl+C` / `Ctrl+V` | kopírovat / vložit kopii |
| `Ctrl+F` | najít označení |
| `F7` | kontrola projektu |
| `Ctrl+M` / `Ctrl+J` | vícepól / jednopól |
| `Ctrl+Shift+M` | plán svorkovnice |
| `Ctrl+L` | rozložení rozvaděče |
| `Ctrl+K` | skříň rozvaděče |
| `Ctrl+T` | svorky vodiče |
| `Ctrl+Shift+T` | svorkovnice a můstky |
| `Ctrl+Shift+K` | kabel vodiče |
| `Ctrl+Shift+E` | celá dokumentace PDF |
| `Ctrl+D` | tmavý režim |
| `Home` | přizpůsobit list |
| kolečko / střední tlačítko | zoom / posun |

---

## 11. Když se něco pokazí

- Program ukládá rozpracovaný projekt každé 2 minuty do `~/.envocad/autosave/`; po spuštění nabídne obnovu.
- Log každého běhu: `~/.envocad/log/envocad.log` (Nápověda → Otevřít složku s logy); neošetřená chyba se
  zobrazí v dialogu a program většinou běží dál – ulož práci.
- Starší projekty (`.ecp`) se při otevření převedou na aktuální formát (verze 6) automaticky.
- `python` na Windows spouští Store? Použij `py -m envocad`.
- Linux Wayland potíže: `QT_QPA_PLATFORM=xcb scripts/run.sh`.

Soubor projektu je čitelný JSON (`.ecp`) – hodí se do gitu, porovnání revizí s ním počítá.
