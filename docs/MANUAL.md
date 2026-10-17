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

Skripty vytvoří virtuální prostředí `.venv`, nainstalují závislosti (PySide6, ezdxf, openpyxl, python-docx, segno, pypdf)
a spustí program. Ručně: `python -m venv .venv`, aktivovat, `pip install -e .`, `python -m envocad` (na Windows
`py -m envocad`, pokud `python` otevírá Microsoft Store).

Samostatná aplikace bez Pythonu pro kolegy: `scripts\build.ps1` / `scripts/build.sh` sestaví složku
`dist/EnvoCAD` přes PyInstaller.

Uživatelská data jsou v `~/.envocad/` (Windows `C:\Users\<jméno>\.envocad\`): knihovna (`library.db`, vlastní
balíčky v `library/`), pluginy, nastavení (`settings.json`), logy (`log/`) a automatické zálohy (`autosave/`).

---

## 2. Okno programu

Vlevo jsou doky **Knihovna** (značky podle druhu prvku, s hledáním) a **Navigátor** (záložky **Prvky** – listy →
prvky a vodiče, s filtrem – a **Připomínky**, viz sekce 9), uprostřed záložky listů, vpravo **Vlastnosti** vybraného prvku nebo vodiče. Nahoře je nástrojová
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
střídač vstupy DC1…DCn (jeden na string) a AC.

**T-odbočka (vodič z vodiče)**: v režimu Vodič klikni místo na port rovnou **na vodič** – vodič se v tom místě
rozdělí uzlem (tečka, značka *Odbočka*) a z volného portu uzlu kreslíš dál; odbočka přebere žíly původního
vodiče. Stejně jde vodič na jiném vodiči i ukončit. Uzel má čtyři porty, všechny jsou jeden potenciál.

### Úpravy
Dvojklik na prvek nebo vodič otevře dialog s parametry, panel Vlastnosti upravuje jednotlivé atributy přímo.
Tažení myší posouvá (snap 2,5 mm), `R` otáčí, `Delete` maže, `Ctrl+Z`/`Ctrl+Y` vrací. `Ctrl+C`/`Ctrl+V`
kopíruje vybrané prvky včetně vodičů mezi nimi – kopie dostanou nová označení a posun 10 mm. Výběr více prvků
tažením rámečku v prázdné ploše. Kolečko zoomuje, střední tlačítko posouvá pohled, `Home` přizpůsobí list.

### Makra (sestavy)
Vyber prvky (vodiče mezi nimi se přiberou) a `Úpravy → Uložit výběr jako makro…` (`Ctrl+Shift+S`): makro se
uloží do `~/.envocad/macros/` nebo – když je nastavená sdílená knihovna – na dotaz do `<sdílená>/macros/`
pro všechny. V panelu Knihovna je dole uzel **Makra**; dvojklik vloží sestavu doprostřed pohledu s novými
označeními (makro bez proměnných se vloží jako kopie výřezu: čísla svorek se vymažou a doplní automatické
číslování, přívody/vývody dostanou další volné X). `Úpravy → Smazat makro…` maže vlastní a sdílená.

**Generátor skládá rozvaděče z maker** – výkres ladí projektant, program ho jen opakuje. Specifikace (`macros`)
říká, které makro se použije: `dc_tech` (string v DC rozvaděči u technologie), `dc_route` (po trase),
`ac_feed` (přívod od střídače), `ac_core` (jádro AC rozvaděče). Výchozí jsou vestavěná makra stejných jmen;
**vlastní makro se stejným názvem** (uložené do `~/.envocad/macros/` nebo do sdílené knihovny) má přednost –
stačí tedy nakreslit svou verzi, uložit ji pod tím jménem a generátor ji začne používat.

Parametrické makro používá v atributech, označeních a názvech portů **proměnné** `{k}` (pořadí instance),
`{nk}` (n + k – pro vývod X{nk}), `{n}`, `{i}` / `{j}` (číslo střídače / stringu u něj – číslování ENVO
`FU{i}.{j}`, `SPD-DC{i}.{j}`), `{string}` / `{inverter}` (označení z JPS), `{fuse_in}`, `{disc_in}`,
`{breaker_in}`, `{main_in}`, `{spd}`. Označení s proměnnou se dosadí a nepřečísluje (`X{k}` → X3), ostatní
(F1, W1) dostanou další volné číslo. Prvek s atributem **`shared` = 1** (sběrnice, vývod XPE k HOP) se vloží
jen jednou a další instance se na něj napojí; do portu sběrnice se dá psát `T{k}`. Rozteč instancí určuje
klíč `pitch` v JSON makra (jinak šířka + 10 mm). Nejjednodušší cesta: otevři vestavěné makro
(`envocad/library/builtin/macros/*.json`), uprav podle sebe a ulož pod stejným názvem do vlastní složky.

### Makra s proměnnými: dialog, sady hodnot, opakování
Makro, které deklaruje proměnné nebo opakování, se při vložení (dvojklik v panelu Knihovna) nejdřív zeptá na
hodnoty v dialogu **Makro – název**. Makro bez proměnných se vloží hned jako dřív.

- **Sada hodnot** – nahoře rozbalovací seznam předvoleb (např. „Pojistka 20 A gPV, SPD T1+T2“). Vybraná sada
  vyplní pole; „— vlastní —“ nechá ruční hodnoty. Hodnoty zadané ručně po výběru sady sadu přebíjejí.
- **Pole** podle typu: text, číslo (jednotka je v popisku, čárka i tečka se berou), nabídka a **artikl**.
  Povinná pole jsou označená hvězdičkou a tučně; nápověda je v tooltipu. Při **OK** se hodnoty zkontrolují
  (povinné, číslo, rozsah min/max, nabídka) a chyby se vypíšou v dialogu – dialog se nezavře.
- **Vazba na artikl** – pole typu artikl otevře výběr artiklů dané kategorie. Po výběru se přepočítají pole,
  která si berou hodnotu z parametrů artiklu (např. In pojistky z artiklu), a prvek, který artikl odkazuje,
  dostane jeho parametry.
- **Další (číslování)** – sbalená skupina s proměnnými, které jinak dodává generátor nebo opakování
  (čísla střídače a stringu, označení). Obvykle se nechávají být; pošlou se jen pole, která změníš. U makra
  s opakováním jsou pole pořadí `k` a vývodu `nk` zakázaná – „doplní se automaticky“ v každé instanci.
- **Opakování** – makro s klíčem `repeat` se vloží N× (počet je jedna z proměnných, např. „Počet stringů“),
  instance jsou posunuté o rozteč a očíslované `{k}` = 1…N (FU1.1, FU1.2…, popisy G1, G2…). Sdílené prvky
  (sběrnice, XPE) se vloží jen jednou, i kdyby už na listu byly – vodiče se napojí na existující. Počet musí být
  celé číslo do maxima proměnné (vestavěné DC makro 50, nejvíc 100); prázdný nebo desetinný dialog nepustí.
  Počet 0 nevloží nic (stavový řádek: „Makro nevložilo žádné prvky (počet 0)“).
- **Typ svodiče** (`spd`) je text – doporučené T1, T2, T1+T2, prázdné = bez svodiče; projde i T1+T2+T3.
- **Podmínky `when`** – prvek nebo vodič s atributem `when` se vloží jen při splnění podmínky: `spd` (hodnota
  není prázdná, 0, ne, no, false, off), `!spd`, `spd=T2`, `spd!=T2`. Vestavěné DC makro tak vynechá svodič
  (i jeho vodiče), když zvolíš „bez SPD“. Atribut `when` se do vložených prvků nepřenáší.
- **Zpět** – celé vložení (všechna opakování) je jeden krok `Ctrl+Z`; zpět smaže jen nové prvky a vodiče,
  už existující sdílené prvky zůstanou.

### Přerušovací body
Prvek **Přerušovací bod** (Svorky a propojení) přenese potenciál jinam – dva body se stejným označením se
spárují a každý ukazuje polohu protějšku (`→ /2.C3` = list 2, sloupec C, řádek 3 v síti rámečku). Rámeček
s popisovým polem je zatím vypnutý – zapne ho `Zobrazit → Rámeček a popisové pole` (platí i pro PDF a DXF).

Body se stejným označením (`ref`) v projektu tvoří skupinu. Zapojení podle stavu skupiny:

| Stav skupiny | Zapojení | Zobrazení |
|---|---|---|
| 2 body | dvojice | `→ /2.C3` u obou |
| 3 a více bodů | řetěz, pořadí list, x, shora dolů | střední bod `← /1.A2` a `→ /4.C1` na samostatných řádcích; první bod jen `→`, poslední jen `←` |
| zdroj hvězdy (2 a více bodů) | hvězda: zdroj → ostatní body | u zdroje `→ /2.A2, /3.B1, /4.C5` (max. 3 na řádek), u cíle `← /1.F3` |

Zdroj hvězdy označíš zaškrtávátkem **Zdroj hvězdy** v panelu Vlastnosti přerušovacího bodu (atribut
`star_source` = `1`). Zdroj má být jeden: další zaškrtnutý bod kontrola hlásí jako `interrupt_star_multi`
a zdrojem zůstane první podle pořadí. Bod bez protějšku ukazuje `→ ?`.

### Ovládací obvody
Značky **Cívka** (K, A1/A2), **Kontakt NO** (13/14), **Kontakt NC** (21/22) a **Hlavní kontakt**. Kontakt
dostane označení své cívky (K1); pod cívkou se automaticky kreslí zrcadlo kontaktů (svorky + poloha) a u
kontaktu odkaz na cívku. Kontakty nejsou samostatné položky ve výkazu materiálu, patří k cívce.

**Zrcadlo kontaktů** je tabulka pod hostitelem – cívkou, jističem, relé nebo RTU s kontakty. Sloupce:
- vlevo od osy silové kontakty (1/2, 3/4, 5/6…),
- u osy vlevo NO (13/14, 33/34…), vpravo NC (21/22…); prázdný sloupec se nekreslí,
- hlavička s piktogramem druhu.

Řádek = pár svorek a odkaz na kontakt: `13/14 /3.B4` = svorky 13/14, kontakt na listu 3, pozice B4. Odkaz
na jiné umístění předřadí aspekt (`+RDC1/3.B4`). Silový kontakt s `poles` = 3 dá tři řádky (1/2, 3/4, 5/6).
Rezerva je pár z kontaktního obrazu, ke kterému zatím není kontakt; řádek má jen pár, bez odkazu. Zrcadlo
potlačíš v panelu Vlastnosti zrušením zaškrtávátka **Zobrazit zrcadlo kontaktů** (je jen u přístroje, který zrcadlo má –
hostitel s kontakty nebo kontaktním obrazem; jde přes undo). Zaškrtávátko zapisuje atribut `mirror` = `0`
(prázdné = zobrazit; viz `docs/LIBRARY_FORMAT.md`).

**Kontaktní obraz** (atribut `contacts`) je seznam párů svorek přístroje: `1/2 3/4 5/6 13/14 21/22`. Zadáš ho
v panelu Vlastnosti nebo sloupcem `contacts` v CSV artiklů; výchozí značky `ctl.coil` a `fve.contactor` mají
pole prázdné. Druh kontaktu se pozná z předpony nebo z čísel svorek:
- bez předpony podle IEC 60947-5-1: jednomístné liché/sudé (1/2, 3/4) = silový; dvoumístné s funkční číslicí
  3/4 nebo 7/8 = NO, 1/2 nebo 5/6 = NC; ostatní jsou chyba (`contact_image_syntax`);
- s předponou `NO:`, `NC:` nebo `P:` / `PWR:` / `HL:` (silový, hlavní kontakt), např. `NO:11/14 NC:11/12`, `NO:DO1 NO:DO2`.

Obraz je nepovinný. Bez něj se nekreslí rezervy a nedělají se kontroly `contact_count` a `contact_unknown`.

**Stykač v JPS a cívka** se stejným označením (např. K1) tvoří jeden přístroj. Výkaz materiálu a rozložení
mají stykač, cívka se do nich nedává. Výjimka: je-li stykač nakreslen na jiném listu (silové schéma se stejným
umístěním), zůstává cívka položkou svého listu rozvaděče (rozložení, oteplení, výkaz a štítky toho listu);
v celoprojektovém výkazu je jen stykač. Silové kontakty stykače jsou v zrcadle cívky jako silový sloupec.
Stykač bez cívky je sám hostitelem zrcadla. Kontakty (`ctl.contact_*`) patří přístroji se stejným označením
ve stejném prostoru označení (funkce a umístění).

---

## 4. Rozvaděče

### Založení
V JPS vlož **Rozvaděč (blok)** (R1), zapoj do něj kabely a dvakrát na něj klikni. Poprvé program nabídne
**šablonu**: *AC rozvaděč FVE* (přívod, hlavní vypínač, rozvod, SPD, vývody s jističi), *DC rozvaděč* (každý
string zvlášť: pojistkový odpínač / odpínač DC, SPD, vývod), nebo prázdný list. Otevře se záložka
`R1 – schéma` – vícepólové schéma rozvaděče.

**Rozvod** v rozvaděči jde dvěma způsoby (parametr šablony i průvodce): **sběrnice potenciálů** – prvek
*Sběrnice (rozvodný vodič)*; ve vícepólu se kreslí jako v EPLAN vodorovnými čarami L1 L2 L3 N PE přes
celou stranu (i přes více stran) s názvem potenciálu a šipkou na obou koncích (`1L1`… – označení sběrnice je
předpona), přístroje se na ni napojují odbočkou s tečkou; porty `T1…T10` shora, `1…10` zdola. PE je potenciál sběrnice (1PE),
PE sběrnice i PE svodiče přepětí jdou na vývod `XPE` – ekvipotenciální svorkovnici (HOP) vně rozvaděče. Nebo
**rozvodné svorky s můstky** (skupiny svorek X2, můstky mezi nimi).

Blok v JPS dostane **porty podle přívodů a vývodů** listu (X1 vlevo, X4, X5… vpravo). Kabel zakreslený na port
X4 se sám naváže na vývod X4: vývod převezme kabel, žíly a text „kam“, u kabelu v JPS se objeví křížový odkaz
`→ R1:X4 /2.B4`. Když vývod přejmenuješ nebo přidáš, blok se přestaví sám; na smazaný vývod s kabelem
zůstane port označený `?`.

### Vícepólové schéma
Je odvozené z jednopólové kresby rozvaděče – nic se nekopíruje. Průchozí přístroje (jistič, odpínač,
chránič, stykač) se kreslí po pólech s čárkovanou mechanickou vazbou a společnou spouští, N a PE jdou kolem;
pojistky, SPD a svorky po pólech bez vazby. Automatické rozmístění je po sloupcích podle toku od přívodu
(svorkové schéma) – přívody nahoře, rozvod, přístroje, **vývody vždy v dolní řadě**, PE lišta pod nimi;
prvky jdou chytit a posunout myší, `Zobrazit → Vícepól: rozmístit automaticky` vrátí
automatiku. Dvojklik na prvek = parametry, dvojklik na žílu = svorky, `Delete` maže.

**Více stran s odkazy**: když se rozvaděč nevejde na jednu stranu, rozmístění pokračuje na dalších stranách
(na obrazovce pod sebou, v PDF každá zvlášť, v popisovém poli `2/3`). Prvek nikdy nepřesahuje okraj strany.
Žíla, která pokračuje jinde, končí na okraji **přerušovacím bodem** se šipkou a odkazem `/3.2.B4` = list 3,
strana 2, sloupec B, řádek 4 – na druhé straně vstupuje stejně s odkazem zpět. Svorkovnice s můstky
pokračuje přes strany, PE lišta je na straně, kde má nejvíc sousedů. Ručně posunuté prvky zůstávají tam,
kam je dáš (i na jiné straně).

**Kreslit jde přímo ve schématu rozvaděče**: dvojklik na značku v knihovně → klik umístí prvek (průchozí přístroje
se otočí svisle, `R` otočí, Esc / pravé tlačítko ukončí) a hned se otevřou jeho parametry; `W` (nebo Vodič) →
klik na konec pólu jednoho prvku a na konec pólu druhého nakreslí žílu (převezme označení žíly L1/N/PE/DC+…
z pólu, na který klikneš). Makra z knihovny se vkládají taky. Totéž jde v záložce `R1 – jednopól (editace)`
(`Ctrl+J`), obě záložky drží stejný model; `Ctrl+M` vrátí do schématu.

### Svorky a můstky
Prvek **Svorkovnice** (`sb.terminal_block`) je v JPS *skupina svorek* jedné svorkovnice: označení X2 a
v atributu „Svorka č.“ čísla (`1 2 3 4 5`, nebo jen první číslo – zbytek se dopočítá). Ve vícepólu má každá
žíla vlastní svorku s číslem. **Přívod a vývod** (`sb.feed_in`, `sb.feed_out`) jsou také svorkovnice: ve
vícepólu dostane každá žíla svorku s číslem (bez zadání 1…n, jinak „Svorka č.“ stejně jako u skupiny),
jsou v plánu svorkovnice i v BOM. `Úpravy → Očíslovat svorky automaticky` doplní chybějící čísla (skupiny,
PE lišta), ruční čísla nechá.

`Úpravy → Svorkovnice a můstky…` (`Ctrl+Shift+T`): tabulka svorek vybrané svorkovnice (vnitřní/vnější strana,
můstek) a editace **můstků** – jedna skupina na řádek, čísla svorek pomlčkou (`1-6-11-16`). Můstky se kreslí
ve vícepólu, v JPS čárkovaně mezi skupinami, a jsou ve výkazech a BOM. Můstky patří listu rozvaděče –
svorkovnice X1 v RDC1 a X1 v RH jsou dvě různé. Přepnutí svorkovnice v dialogu rozpracované můstky nezahodí;
OK uloží změny všech svorkovnic jedním krokem undo a odmítne číslo svorky, které na svorkovnici není.
Šířka skupiny svorek v rozložení = počet svorek × 6,2 mm, pokud atribut „Šířka skupiny“ nevyplníš.

`Ctrl+T` (Svorky vybraného vodiče) přiřadí svorky ručně po žílách (`X1:3`, `F2:1`) – pro PE lištu a
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
  svorky, přerušovací bod nebo kontakt bez protějšku, úbytek napětí přes mez, uzel odbočky bez odbočky;
- **potenciály**: program sleduje, co je vodivě spojené přes vodiče, uzly, svorky, můstky, PE lištu i přes
  přívody/vývody rozvaděčů. Spojení L–N, L–PE, DC+–DC− nebo dvou fází v jedné síti je chyba. Panel Vlastnosti
  ukazuje u vodiče potenciál každé žíly (`L1 X1`, `DC+ G1`, `N (W3)`), výkaz **Potenciály** vypíše všechny sítě;
- informace: přívod bez vazby na JPS, prvek bez artiklu, vodič bez kabelu/žil, selektivita nejistá.

Kontakty a přerušovací body:

| Kód | Závažnost | Význam |
|---|---|---|
| `contact_dup` | varování | dva kontakty nebo póly téhož přístroje mají stejné svorky |
| `contact_count` | varování | použito víc kontaktů druhu (NO, NC, silové), než kontaktní obraz má |
| `contact_unknown` | varování | pár svorek kontaktu není v kontaktním obrazu přístroje |
| `contact_image_syntax` | varování | v atributu `contacts` je nečitelný token |
| `interrupt_star_multi` | varování | ve skupině přerušovacích bodů jsou dva a více zdrojů hvězdy |

Připomínky (sekce 9):

| Kód | Závažnost | Význam |
|---|---|---|
| `note_open` | informace | list má otevřené připomínky (jedna hláška na list) |
| `note_orphan` | informace | připomínka je na smazaném listu, v editoru ji nevidět |

Výpočty (`model/calc.py`, výkaz **Výpočty**): kontrola stringu proti střídači (Uoc při −10 °C vs. Umax,
Umpp při 70 °C vs. rozsah MPPT, 1,25·Isc vs. Imax vstupu – atributy stringu Uoc/Umpp/Isc modulu a teplotní
součinitel, atributy střídače Umax, MPPT min/max, Imax), proud kabelem (1,25·Isc, P_AC/√3·U, In),
zatížitelnost Iz podle ČSN 33 2000-5-52 pro uložení A1/B1/C/D/E (atribut vodiče „Uložení dle ČSN“, nebo se
pozná z textu trasy: „v zemi“, „trubka“, „na vzduchu“, „ve stěně“), In ≤ Iz, úbytek napětí (mez 3 %) a
základní selektivita (poměr In po cestě ke zdroji ≥ 1,6). Tabulky Iz jsou orientační přepis normy.

`Ctrl+F` najde prvek nebo vodič podle označení kdekoli v projektu; Navigátor umí totéž s filtrem.

### Strukturní označení (IEC 81346)

Označení má tři části: `=` funkce, `+` umístění, `-` přístroj, plné označení např. `=AC+RDC1-F3`.
Přístroj nesou značky jako `F3` (bez `-`); funkci a umístění dostávají z listu a na listu rozvaděče je
umístěním jeho blok.

| Kde | Co nastavíš |
|---|---|
| `Projekt → Strukturní označení…` | seznam kódů funkce (`=`) a umístění (`+`) s popisem, např. `AC`, `DC`, `RDC1`; ve výkazech a štítcích se pak píše plné označení |
| `List → Vlastnosti listu (název, =funkce, +umístění)…` | funkce a umístění listu – výchozí pro všechny prvky a vodiče listu |
| Panel Vlastnosti prvku, pole `Funkce (=)` a `Umístění (+)` | přepis pro jeden prvek; prázdné pole = převzít z listu |

Kódy se píšou bez znaménka, jedna úroveň (`RS1`, ne `=RS1.2`), jen A–Z, 0–9 a `_`, nejvýš 10 znaků. Přejmenování
bloku rozvaděče (`ref` v panelu Vlastnosti) přejmenuje i jeho umístění v registru, na listech a v overridech prvků.

Kontrola (`F7`) hlásí označení a strukturní údaje:

| Kód | Závažnost | Význam |
|---|---|---|
| `ref_syntax` | chyba | v označení je oddělovač aspektů (`=`, `+`, `:`, `/`, mezera) nebo úvodní `-`, např. `=F3` nebo `X1:3` |
| `ref_chars` | varování | malá písmena, diakritika nebo jiný znak než A–Z, 0–9, `_` |
| `ref_length` | varování | označení delší než 10 znaků nebo plné označení delší než 32 znaků (štítek) |
| `ref_class` | varování | písmeno označení neodpovídá třídě značky (značka `function_class`, např. jistič `F` nebo `Q`) |
| `struct_syntax` | chyba | neplatný kód funkce nebo umístění listu či prvku |
| `struct_undefined` | info | kód není v `Projekt → Strukturní označení` |
| `sb_no_loc` | varování | list rozvaděče nemá umístění (`+`) |
| `loc_mismatch` | info | umístění listu se liší od označení bloku rozvaděče |
| `contact_ambiguous` | varování | kontakt odpovídá cívkám ve více umístěních – nastav kontaktu umístění v panelu Vlastnosti |

Kontrola `ref_class` se nedělá u kontaktů, přerušovacích bodů a vodičů. Tečka v označení (např. `FU1.1`)
je firemní číslování ENVO a kontrola ji nehlásí; pomlčka uvnitř označení (`SPD-DC1.1`) se hlásí jen jako info.

---

## 7. Nový projekt z průvodce (a pro agenty)

`Ctrl+Shift+N` (Soubor → Nový projekt z průvodce): zadej projekt a investora, modul (typ, Wp, Uoc, Umpp, Isc),
optimizéry (typ a kusy na modul – prázdné = bez optimizérů), střídač (typ, P AC, Umax, rozsah MPPT, Imax), stringy po střídačích (`20,20,18; 20,20`), kabely a jištění.
Vygeneruje se JPS (stringy → DC rozvaděče → střídače → AC rozvaděč → síť) a listy všech rozvaděčů včetně
kabelů a vazeb. Hned potom spusť `F7`.

DC strana se dělá jako na stavbě: ke každému střídači vznikne **DC rozvaděč po trase** (počet zadáš, i 0 –
odpínač DC a SPD na každý string, stringy jím procházejí odděleně) a **DC rozvaděč u technologie**
(pojistkové odpínače gPV a SPD DC na každý string). **Stringy se v rozvaděči nikdy nespojují** – každý jde
zvlášť až na vlastní DC vstup střídače (DC1…DCn podle počtu MPPT × stringů na MPPT; paralelní spojení dělá
jen SolarEdge a kreslí se jako jeden string). Blok DC rozvaděče v JPS má porty podle přívodů
(X1…Xn od stringů) a vývodů (Xn+1… dál). Když obojí vypneš, vloží se jen samostatný odpínač DC v JPS.
AC rozvaděč má přívody po střídačích, jističe, rozvodné svorky s můstky, SPD, hlavní vypínač a vývod do HDS.
Označení jsou jedinečná uvnitř každého rozvaděče (jako v EPLAN `+RDC1-X1`), takže X1 smí být v každém
rozvaděči; listy JPS sdílejí jeden prostor označení.

Jištění ve specifikaci i v průvodci se zadává **číslem v ampérech**: `dc.fuse_in`, `dc.disconnect_in`,
`ac.breaker_in` (např. `40`, ne „C40“ ani „B40“ – charakteristiku nese prvek jističe) a `ac.main_in`; „40,0“
i `40.0` se berou jako 40. Typ svodiče `dc.spd` / `ac.spd` je text (T1, T2, T1+T2, i T1+T2+T3).

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
| Otevřené připomínky jako anotace PDF nebo vrstva `PRIPOMINKY` v DXF | Výstupy → Přidávat připomínky do exportu (sekce 9) |

Rámeček listu má popisové pole (projekt, zakázka, investor, místo, list, číslo listu, zpracoval, datum,
revize, formát), souřadnicovou síť A–H × 1–6 a QR kód s identifikací výkresu. Údaje se zadávají v
Soubor → Vlastnosti projektu, název firmy v popisovém poli v nastavení (`standard.company`).

### Revize
Soubor → Vlastnosti projektu: revize, datum, změnový list (řádek = `revize | datum | popis | zpracoval`).
**Porovnat s revizí (.ecp)** porovná aktuální projekt se starší uloženou verzí (prvky, vodiče, kabely, můstky,
skříň) a jedním tlačítkem zapíše změny do změnového listu; dvojklik skočí na změněný prvek.

Výkres ukazuje změny trojúhelníky s číslem revize (červeně, také v DXF ve vrstvě `REVIZE`); revize listu se
objeví v popisovém poli toho listu (když je zapnutý rámeček). Revizi uzavřeš v menu **Soubor**:

| Položka | Co dělá |
|---|---|
| `Uzavřít revizi` | uzavře otevřenou revizi pro celý projekt |
| `Uzavřít revizi listu` | uzavře revizi jen aktuálního listu |

Uzavření je měkký zámek: program si zapamatuje stav listů. Když pak list změníš, kontrola `F7` hlásí
`rev_closed_changed` (list změněn po uzavření revize). Úpravu neblokuje – porovnej projekt s revizí
(`Porovnat s revizí (.ecp)…`) a založ novou revizi. Má-li uzavírané místo otevřené připomínky, program se
před uzavřením zeptá (sekce 9).

---

## 9. Připomínky (redlining)

Připomínka je interní poznámka k listu: bod nebo oblast (obdélník) s textem, autorem a stavem **otevřeno** /
**vyřešeno**. Je uložená v projektu (`.ecp`, formát v9), ale **není součástí dokumentace** – nevypaluje se do
obsahu PDF ani DXF a revize ji neberou jako změnu. Starší verze programu (formát v8) projekt v9 neotevře.

### Vložení a úpravy

Kreslit → Připomínka (`Ctrl+Shift+P`) zapne zobrazení připomínek a nástroj. Klik = bod, tah přes alespoň
1 mřížku (2,5 mm) v obou směrech = oblast. Je-li pod kotvou prvek nebo vodič, připomínka se na něj naváže
(jen pro popis a skok). `Esc` nebo pravé tlačítko nástroj ukončí. Po nakreslení se otevře dialog.

| Akce | Jak |
|---|---|
| Nová připomínka | `Ctrl+Shift+P`, klik nebo tah |
| Upravit | dvojklik na připomínku, nebo kontextové menu → Upravit… |
| Posun | tažení (přichycení na mřížku) |
| Vyřešit / Znovu otevřít | kontextové menu |
| Smazat | `Delete`, nebo kontextové menu → Smazat |

Dialog **Připomínka**:

| Pole | Význam |
|---|---|
| Text | popis připomínky (více řádků) |
| Stav | otevřeno / vyřešeno; přepnutí na vyřešeno doplní, kdo a kdy |
| Vyřízení | jak byla připomínka vyřízena (volitelné) |
| Autor, Vytvořeno, Vyřešeno | jen ke čtení; autor = `standard.author` z firemního standardu, jinak přihlašovací jméno |

Číslo připomínky (`Č.`) je pořadové v projektu a při smazání se nepřečíslovává.

### Navigátor → Připomínky

- Filtr **Otevřené** / **Vyřešené** / **Vše**, zaškrtávátko **jen aktuální list**.
- Hledání v textu, autorovi, prvku a názvu listu.
- Sloupce: Č., List, Prvek, Text, Autor, Datum, Stav.
- Tlačítko **Vyřešit** a **Smazat** pracují s vybranými řádky; **Vyřešit** se změní na **Otevřít**, když jsou
  vybrané jen vyřešené. Každá akce jde do undo.
- **Dvojklik** na řádek přepne list, zapne zobrazení připomínek, připomínku vybere a vycentruje.

### Zobrazení a export

| Přepínač | Kde | Výchozí | Co dělá |
|---|---|---|---|
| Připomínky | Zobrazit → Připomínky | vypnuto | zobrazí nebo skryje připomínky v editoru |
| Přidávat připomínky do exportu | Výstupy → Přidávat připomínky do exportu | vypnuto | přidá **otevřené** připomínky do exportů níže |

Při zapnutém přepínači:
- **PDF listu** (JPS) a **Celá dokumentace** – připomínky jsou anotace PDF (komentáře v Adobe Acrobat a
  Readeru: bod jako poznámka, oblast jako obdélník; autor, text a číslo). Vícepól a plán svorkovnice připomínky
  nemají.
- **DXF listu** – připomínky ve vrstvě `PRIPOMINKY` (purpurová), s textem zalomeným na 40 znaků.

### Revize a kontroly

- Uzavření revize (Soubor → `Uzavřít revizi` / `Uzavřít revizi listu`) se při otevřených připomínkách zeptá
  „N otevřených připomínek – přesto uzavřít?“ (výchozí odpověď Ne). Nezablokuje ho.
- Kontrola `F7` hlásí otevřené připomínky (kódy v sekci 6).

---

## 10. Knihovna

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

## 11. Klávesové zkratky

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
| `Ctrl+Shift+S` | uložit výběr jako makro |
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
| `Ctrl+Shift+P` | připomínka (Kreslit → Připomínka) |
| `Ctrl+D` | tmavý režim |
| `Home` | přizpůsobit list |
| kolečko / střední tlačítko | zoom / posun |

---

## 12. Když se něco pokazí

- Program ukládá rozpracovaný projekt každé 2 minuty do `~/.envocad/autosave/`; po spuštění nabídne obnovu.
- Log každého běhu: `~/.envocad/log/envocad.log` (Nápověda → Otevřít složku s logy); neošetřená chyba se
  zobrazí v dialogu a program většinou běží dál – ulož práci.
- Starší projekty (`.ecp`) se při otevření převedou na aktuální formát automaticky.
- `python` na Windows spouští Store? Použij `py -m envocad`.
- Linux Wayland potíže: `QT_QPA_PLATFORM=xcb scripts/run.sh`.

Soubor projektu je čitelný JSON (`.ecp`) – hodí se do gitu, porovnání revizí s ním počítá.
