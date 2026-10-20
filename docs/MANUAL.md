# EnvoCAD – uživatelská příručka

Verze 0.10. EnvoCAD je nástroj pro elektro-dokumentaci fotovoltaických elektráren: blokové schéma celé elektrárny (dříve nazývané jednopólové schéma, JPS; skutečné jednopólové schéma s přístroji rozvaděčů je v plánu),
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
prvky a vodiče, s filtrem – a **Připomínky**, viz sekce 9), uprostřed záložky listů, vpravo **Vlastnosti** vybraného prvku nebo vodiče.
Po `F7` přibude dole panel **Kontrola** (viz sekce 6).

Nahoře jsou lišty s ikonami (tooltip ukáže název a zkratku):

| Lišta | Obsah |
|---|---|
| Soubor | nový, otevřít, uložit, export PDF a DXF |
| Úpravy | zpět, znovu, kopírovat, vložit, smazat, najít označení |
| Pohled | přizpůsobit list, přiblížit, oddálit, Jen výkres; přepínač Jednopól / Vícepól / Rozložení / Svorkovnice (zamáčknutý = zobrazený pohled); tmavý režim |
| Kreslení | výběr, vodič, vložit značku, přerušovací bod, text, připomínka, otočit, zrcadlit, narovnat vodič – jen v blokovém schématu a schématu rozvaděče (přerušovací bod, text, zrcadlit a narovnat jen v editoru listu, ne ve vícepólu), aktivní nástroj je zamáčknutý |
| Dispozice | skříň rozvaděče, výrobní data – jen v rozložení rozvaděče (místo lišty Kreslení) |
| Kontrola a výstupy | kontrola F7, výkazy, celá dokumentace PDF, štítky |

**Vložit značku** vloží značku označenou v Knihovně; když žádná označená není, ukáže Knihovnu. Co v aktuálním
pohledu nejde použít, je zašedlé. Lišty i panely se dají přetáhnout jinam a okno si rozložení i velikost pamatuje;
`Zobrazit → Obnovit rozložení panelů a lišt` vrátí výchozí stav. `F11` (Zobrazit → Jen výkres) schová všechny
panely, druhým stiskem se vrátí.

**Hledat příkaz** (`Ctrl+K`): napiš část názvu příkazu, třeba „export dxf“ nebo „svorkovnice“ – hledá ve všech
položkách menu (i bez diakritiky), šipkami vybereš, Enter spustí.

**Pravé tlačítko** ve výkresu (blokové schéma i schéma rozvaděče) vybere položku pod kurzorem a nabídne Vlastnosti, Otočit,
Kopírovat a Smazat (v blokovém schématu i Uložit výběr jako makro); u vodiče navíc Svorky, Kabel a Narovnat (Narovnat jen v blokovém schématu),
u bloku ROZVADĚČ Otevřít rozvaděč, na prázdném místě Vložit značku, Vodič a Přizpůsobit list (a Vložit, když je
něco zkopírované). V režimu Vodič nebo Vkládání pravé tlačítko jen
ukončí režim. Připomínky mají vlastní menu (sekce 9).

**Stavový řádek** vlevo ukazuje nápovědu k aktuálnímu režimu, vpravo souřadnice kurzoru v mm (Y nahoru jako ve
výkresu), mřížku 2,5 mm, zoom (100 % = skutečná velikost na monitoru), souhrn kontroly („F7: 2 chyby, 5 varování“,
klik otevře panel Kontrola) a „● neuloženo“, když má projekt neuložené změny.

Nový prázdný projekt ukáže **úvodní obrazovku** s průvodcem, otevřením a posledními projekty; zmizí po první změně
nebo křížkem.

Tmavý a světlý režim přepíná `Ctrl+D` (menu Zobrazit). Tisk a export jsou vždy černobílé na bílém.

Druhy záložek (podle názvu):

| Záložka | Co to je |
|---|---|
| `Blokové schéma` | blokové schéma celé elektrárny (stringy → rozvaděče → střídače → síť) – hlavní editační list; starší projekty mají list `Jednopólové schéma` |
| `R1 – schéma` | **vícepólové** schéma rozvaděče (odvozené, přístroje po pólech, svorky, můstky) |
| `R1 – jednopól (editace)` | jednopólová kresba rozvaděče – jen pro vkládání prvků a vodičů |
| `R1 – rozložení` | fyzické rozložení na DIN lištách + parametry skříně a oteplení |
| `R1 – svorkovnice` | kreslený plán svorkovnice |
| `… – vícepól` | vícepólový pohled libovolného listu blokového schématu |

---

## 3. Kreslení blokového schématu

### Vložení prvku
Dvojklik na značku v Knihovně (nebo hledej: „jistič“, „střídač“, „string“) → klik do výkresu → vyplnit dialog
s parametry → OK. Režim vkládání trvá, dokud nezmáčkneš `Esc` nebo pravé tlačítko. Během vkládání `R` otáčí
značku o 90° a `M` ji zrcadlí.

V dialogu lze vybrat **artikl z knihovny** („Vybrat artikl z knihovny…“): typ, výrobce, In, póly,
charakteristika, Icu, moduly, ztrátový výkon atd. se propíší do prvku. Označení (F1, Q2, T1…) se předvyplní
podle písmene IEC 81346 a program hlídá duplicity.

### Vodiče
`W` (nebo tlačítko Vodič) → klik na port prvního prvku → klik na port druhého → dialog: označení (W1…), typ
kabelu, průřez, délka, trasa/uložení a **žíly** (např. `L1 L2 L3 N PE`, `L+ L-` – předvolby v rozbalovacím
seznamu). Žíly se značí podle **ČSN EN 60445**: střídavé L1, L2, L3, N, PE (PEN), stejnosměrné **L+ / L−** (střed M);
napsané `DC+ DC-` se samo převede na `L+ L-`. Výchozí žíly se odvodí z portů a pólů (DC port → `L+ L-`,
3pólový prvek → `L1 L2 L3 N PE`).

V blokovém schématu je každá čára jednopólová – jedna čára = jeden kabel se všemi žílami. FV string má jeden port DC,
střídač vstupy DC1…DCn (jeden na string) a AC.

**Svorky typu střídače**: střídač s výrobcem a typem z artiklu dostane pod značkou pás svorek své řady – záložní
výstup (BACKUP), komunikace s baterií (BMS, CAN), elektroměr (METER), RS485, Ethernet (LAN), řízení výkonu (DI,
DRM, DIDO) a dálkové vypnutí (RSD); hybridní střídač má baterii (BAT) až pod pásem. Profily řad: Huawei SUN2000
KTL-M1/M2/M3 a MAP0, SolaX X3-Ultra a X1/X3-Hybrid G4, GoodWe ET a DT/SDT G2, Growatt MOD, Sigenergy Sigen
Hybrid / SigenStor, SolarEdge Home Hub a třífázové SetApp. Jsou podle datasheetů a návodů výrobce – čísla pinů
a varianty trhu ověř v návodu konkrétního modelu. Atribut **Svorky střídače** (`io`) profil přepíše (např.
„BACKUP BMS METER RS485“), „-“ svorky vypne. Vodič na komunikační svorku dostane žíly A, B (RS485, METER), H, L
(BMS, CAN), LAN nebo DI; nezapojené komunikační svorky kontrola nehlásí.

**T-odbočka (vodič z vodiče)**: v režimu Vodič klikni místo na port rovnou **na vodič** – vodič se v tom místě
rozdělí uzlem (tečka, značka *Odbočka*) a z volného portu uzlu kreslíš dál; odbočka přebere žíly původního
vodiče. Stejně jde vodič na jiném vodiči i ukončit. Uzel má čtyři porty, všechny jsou jeden potenciál.

### Úpravy
Dvojklik na prvek nebo vodič otevře dialog s parametry, panel Vlastnosti upravuje jednotlivé atributy přímo.
Tažení myší posouvá (snap 2,5 mm), `R` otáčí, `M` zrcadlí, `Delete` maže, `Ctrl+Z`/`Ctrl+Y` vrací. `Ctrl+C`/`Ctrl+V`
kopíruje vybrané prvky včetně vodičů mezi nimi – kopie dostanou nová označení a posun 10 mm. Výběr více prvků
tažením rámečku v prázdné ploše. Kolečko zoomuje, střední tlačítko posouvá pohled, `Home` přizpůsobí list.

**Zrcadlit** (`M`, Úpravy → Zrcadlit, i pravé tlačítko) obrátí vybrané značky podle jejich svislé osy – porty
vpravo jsou pak vlevo a vodiče se k nim přetrasují; popisky a texty ve značce zůstanou čitelné. Platí pro výkres,
PDF i DXF; vícepól si přístroje rozmisťuje sám a zrcadlení nepřebírá.

**Text** (`T`, Kreslit → Text): klik do výkresu otevře dialog s textem (víc řádků) a výškou písma 2,5 / 3,5 / 5 /
7 mm. Text se posouvá myší, dvojklik ho upraví (smazáním celého textu se odstraní), `Delete` maže. Je ve výkresu,
v PDF i DXF (vrstva TEXTY) a popisky prvků se mu vyhnou. Texty se nekopírují se schránkou ani makrem a změnový
list revize je nesleduje.

**Přečíslovat označení** (`Úpravy → Přečíslovat označení…`): nový prvek dostane další volné číslo sám (F1, F2…),
tenhle příkaz srovná označení hromadně. Rozsah je aktuální list nebo celý projekt, režim **Jen doplnit chybějící
a opravit duplicitní** (výchozí – ostatní označení zůstanou, u duplicity si číslo nechá první podle polohy) nebo
**Přečíslovat vše podle polohy** (listy v pořadí projektu, v listu po sloupcích zleva doprava a shora dolů).
Číslovat lze přístroje, vodiče (W) nebo obojí. Dialog ukáže náhled „staré → nové“; provede se jedním krokem
`Ctrl+Z`. Kontakty dostanou číslo spolu se svou cívkou, kabel navázaný na vodič jeho označením se přejmenuje s ním,
automatické popisy („od T1“) se přepíšou. Každý prostor označení (=funkce+umístění) se čísluje zvlášť. Nemění se
svorkovnice, přívody a vývody (čísla svorek viz `Očíslovat svorky`), přerušovací body, bloky ROZVADĚČ a firemní
označení, která nejsou tvaru písmena + číslo (`Q1.2`, `SPD-DC1`) – jejich čísla zůstanou obsazená.

### Makra (sestavy)
Vyber prvky (vodiče mezi nimi se přiberou) a `Úpravy → Uložit výběr jako makro…` (`Ctrl+Alt+M`): makro se
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
`FU{i}.{j}`, `SPD-DC{i}.{j}`), `{string}` / `{inverter}` (označení z blokového schématu), `{fuse_in}`, `{disc_in}`,
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
Prvek **Přerušovací bod** (Svorky a propojení, nebo tlačítko na liště Kreslení) přenese potenciál jinam – dva body se stejným označením se
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

**Stykač v blokovém schématu a cívka** se stejným označením (např. K1) tvoří jeden přístroj. Výkaz materiálu a rozložení
mají stykač, cívka se do nich nedává. Výjimka: je-li stykač nakreslen na jiném listu (silové schéma se stejným
umístěním), zůstává cívka položkou svého listu rozvaděče (rozložení, oteplení, výkaz a štítky toho listu);
v celoprojektovém výkazu je jen stykač. Silové kontakty stykače jsou v zrcadle cívky jako silový sloupec.
Stykač bez cívky je sám hostitelem zrcadla. Kontakty (`ctl.contact_*`) patří přístroji se stejným označením
ve stejném prostoru označení (funkce a umístění).

---

## 4. Rozvaděče

### Založení
V blokovém schématu vlož **Rozvaděč (blok)** (R1), zapoj do něj kabely a dvakrát na něj klikni. Poprvé program nabídne
**šablonu**: *AC rozvaděč FVE* (přívod, hlavní vypínač, rozvod, SPD, vývody s jističi), *DC rozvaděč* (každý
string zvlášť: pojistkový odpínač (u technologie) nebo jen průchozí svorky (po trase), SPD, vývod), nebo prázdný list. Otevře se záložka
`R1 – schéma` – vícepólové schéma rozvaděče.

**Rozvod** v rozvaděči jde dvěma způsoby (parametr šablony i průvodce): **sběrnice potenciálů** – prvek
*Sběrnice (rozvodný vodič)*; ve vícepólu se kreslí jako v EPLAN vodorovnými čarami L1 L2 L3 N PE přes
celou stranu (i přes více stran) s názvem potenciálu a šipkou na obou koncích (`1L1`… – označení sběrnice je
předpona), přístroje se na ni napojují odbočkou s tečkou; porty `T1…T10` shora, `1…10` zdola. PE je potenciál sběrnice (1PE),
PE sběrnice i PE svodiče přepětí jdou na vývod `XPE` – ekvipotenciální svorkovnici (HOP) vně rozvaděče. Nebo
**rozvodné svorky s můstky** (skupiny svorek X2, můstky mezi nimi).

Blok v blokovém schématu dostane **porty podle přívodů a vývodů** listu (X1 vlevo, X4, X5… vpravo). Kabel zakreslený na port
X4 se sám naváže na vývod X4: vývod převezme kabel, žíly a text „kam“, u kabelu v blokovém schématu se objeví křížový odkaz
`→ R1:X4 /2.B4`. Když vývod přejmenuješ nebo přidáš, blok se přestaví sám; na smazaný vývod s kabelem
zůstane port označený `?`.

### Vícepólové schéma
Je odvozené z jednopólové kresby rozvaděče – nic se nekopíruje. Průchozí přístroje (jistič, odpínač,
chránič, stykač) se kreslí po pólech s čárkovanou mechanickou vazbou a společnou spouští, N a PE jdou kolem;
pojistky, SPD a svorky po pólech bez vazby. Automatické rozmístění je po sloupcích podle toku od přívodu
(svorkové schéma) – přívody nahoře, rozvod, přístroje, **vývody vždy v dolní řadě**, PE lišta pod nimi;
prvky jdou chytit a posunout myší, `Zobrazit → Vícepól: rozmístit automaticky` vrátí
automatiku. Dvojklik na prvek = parametry, dvojklik na žílu = svorky, `Delete` maže.

**Strany A4**: schéma rozvaděče a plán svorkovnice jsou na stranách **A4 na šířku** (297 × 210 mm) – vytisknou
se na běžné tiskárně. Formát se volí ve `Firemní standard…` (poslední otázka: `A4`, `A4 na výšku`, `A3`; klíč
`standard.switchboard_paper` v `settings.json`) nebo pro jeden list rozvaděče v `List → Vlastnosti listu` →
**Formát stran schématu** (podle standardu / A4 na šířku / A4 na výšku / A3 na šířku / jako list); změna jde vrátit
`Ctrl+Z`. Na každé straně je rámeček s popisovým polem (číslo listu a strany „2/5, str. 1/3“, formát A4); QR kód
vlevo od popisového pole je na A4 na šířku i A3, na A4 na výšku se nevejde (popisové pole 180 mm vyplní celou
šířku) a vynechá se. Na nízké straně A4 se rozmístění samo zhustí (posune nahoru pod nadpis, zmenší mezery mezi
řadami), aby kresba nezasahovala do popisového pole – na obrazovce, v PDF i v kontrole F7 stejně.

**Více stran s odkazy**: když se rozvaděč nevejde na jednu stranu, rozmístění pokračuje na dalších stranách
(na obrazovce pod sebou, v PDF každá zvlášť, v nadpisu `RDC1 (2/3)`). **Logická skupina se nikdy nerozdělí**:
přívod/vývod se svými přístroji (u DC rozvaděče string = svorky X + pojistka FU + SPD + vývod), který by přesáhl
okraj strany, začne celý na další straně (A4 na šířku: 3 stringy na stranu, 21 stringů = 7 stran). Žíla, která
pokračuje jinde, končí na okraji **přerušovacím bodem** se šipkou a odkazem `/3.2.B4` = list 3, strana 2, sloupec B,
řádek 4 – na druhé straně vstupuje stejně s odkazem zpět; odkaz je nad žílou uvnitř rámečku. **Sběrnice** se kreslí
na každé straně se svými odbočkami a pod názvem potenciálu na konci čáry má odkaz na předchozí / další stranu.
**PE z více stran** (PE svodičů všech stringů do XPE nebo do PE lišty) vede **sběrná čára**: na každé straně
vodorovná čára s odbočkami (tečky) a jedním přerušením na okraji s odkazem na sousední stranu – ne 20 samostatných
přerušení. Svorkovnice s můstky pokračuje přes strany, PE lišta je na straně, kde má nejvíc sousedů. Ručně posunuté
prvky zůstávají tam, kam je dáš (i na jiné straně); první ruční posun zapíše k listu platný formát stran, aby ho
pozdější změna standardu nepřesunula. Starší list rozvaděče s ručními polohami ve vícepólu nebo s jiným rozměrem
listu než výchozí A3 zůstává ve formátu listu (A3), dokud v Vlastnostech listu nezvolíš jiný.

**Kreslit jde přímo ve schématu rozvaděče**: dvojklik na značku v knihovně → klik umístí prvek (průchozí přístroje
se otočí svisle, `R` otočí, Esc / pravé tlačítko ukončí) a hned se otevřou jeho parametry; `W` (nebo Vodič) →
klik na konec pólu jednoho prvku a na konec pólu druhého nakreslí žílu (převezme označení žíly L1/N/PE/L+…
z pólu, na který klikneš). Makra z knihovny se vkládají taky. Totéž jde v záložce `R1 – jednopól (editace)`
(`Ctrl+J`), obě záložky drží stejný model; `Ctrl+M` vrátí do schématu.

### Svorky a můstky
Prvek **Svorkovnice** (`sb.terminal_block`) je v blokovém schématu *skupina svorek* jedné svorkovnice: označení X2 a
v atributu „Svorka č.“ čísla (`1 2 3 4 5`, nebo jen první číslo – zbytek se dopočítá). Ve vícepólu má každá
žíla vlastní svorku s číslem. **Přívod a vývod** (`sb.feed_in`, `sb.feed_out`) jsou také svorkovnice: ve
vícepólu dostane každá žíla svorku s číslem (bez zadání 1…n, jinak „Svorka č.“ stejně jako u skupiny),
jsou v plánu svorkovnice i v BOM. `Úpravy → Očíslovat svorky automaticky` doplní chybějící čísla (skupiny,
PE lišta), ruční čísla nechá.

`Úpravy → Svorkovnice a můstky…` (`Ctrl+Shift+T`): tabulka svorek vybrané svorkovnice (vnitřní/vnější strana,
můstek) a editace **můstků** – jedna skupina na řádek, čísla svorek pomlčkou (`1-6-11-16`). Můstky se kreslí
ve vícepólu, v blokovém schématu čárkovaně mezi skupinami, a jsou ve výkazech a BOM. Můstky patří listu rozvaděče –
svorkovnice X1 v RDC1 a X1 v RH jsou dvě různé. Přepnutí svorkovnice v dialogu rozpracované můstky nezahodí;
OK uloží změny všech svorkovnic jedním krokem undo a odmítne číslo svorky, které na svorkovnici není.
Šířka skupiny svorek v rozložení = počet svorek × 6,2 mm, pokud atribut „Šířka skupiny“ nevyplníš.

`Ctrl+T` (Svorky vybraného vodiče) přiřadí svorky ručně po žílách (`X1:3`, `F2:1`) – pro PE lištu a
prvky bez skupin svorek.

### Plán svorkovnice
`Zobrazit → Plán svorkovnice` (`Ctrl+Shift+M`): svorky v řadě, nahoře vnější připojení (kabel z blokového schématu),
dole vnitřní (přístroj), můstky. Krátké svorkovnice jsou vedle sebe, další pod nimi; dlouhá svorkovnice se
zalomí do dalšího pásu („(pokračování)“) a co se nevejde na stranu, pokračuje na další straně (v editoru pod
sebou, v PDF listu i v dokumentaci každá strana zvlášť, popisové pole „2/5, str. 1/3“). Žádná svorka se nevynechá.
Strany mají formát schématu rozvaděče (výchozí A4 na šířku); výška pásů se řídí délkou textů připojení, takže
krátké texty (DC rozvaděč) dají dva pásy na stranu A4. Export do PDF, stejná data jsou i jako list ve výkazech.

### Rozložení a skříň
`Ctrl+L` otevře rozložení: DIN lišty podle řad, přístroje se přetahují na lišty (snap 0,5 modulu), vpravo
panel **skříně**: označení, řady, moduly na řadu, rozměry, rozteč řad, IP/IK, montáž, materiál, dveře, Un/In/Icw,
síť, rezerva, teplota okolí, nejnižší teplota okolí (nepovinné), RDF (`Ctrl+Alt+K` otevře totéž jako dialog; skříň lze
vybrat z artiklů).
Panel ukazuje obsazenost a **odhad oteplení** podle IEC TR 60890 (ΣPv z atributů `p_loss_w` nebo odhad
z In a pólů, chladicí plocha podle montáže, Δt uprostřed a v horní části, kritický přístroj, hodnocení). Parametry
skříně se kreslí v informačním bloku listu rozvaděče a jdou do protokolu kusového ověření.

**Hodnocení oteplení po přístrojích.** Rozhoduje teplota vzduchu u každého přístroje proti rozsahu provozní teploty
z jeho datasheetu, ne pevný práh skříně:

- *Teplota v řadě*: oteplení roste s výškou – uprostřed výšky skříně Δt0,5, nahoře Δt1,0. Přístroj dostane teplotu
  v úrovni osy své řady DIN lišty (řady jsou ve skříni na střed s roztečí řad): nad středem lineárně mezi Δt0,5
  a Δt1,0, ve spodní polovině konzervativně Δt0,5 (norma tam teplotu ještě snižuje). Nerozmístěný přístroj
  = horní část skříně.
- *Meze přístroje*: atributy `t_max` / `t_min` (°C, teplota okolí přístroje dle datasheetu) – vyplní je artikl
  (sloupce `t_max_c` / `t_min_c`), nebo je zadej ručně ve Vlastnostech prvku (u vestavěných přístrojů jsou to
  skryté atributy). Přístroj bez `t_max` se hodnotí s předpokladem **40 °C** – horní mez normálních provozních
  podmínek výrobkových norem (ČSN EN 60947-1, ČSN EN 60898-1); výrobci obvykle uvádějí víc (55–70 °C), takže
  předpoklad je na straně bezpečnosti a hodnocení připíše „u N přístrojů chybí rozsah teplot – ověřit“.
- *Dolní mez*: jen když skříň má **nejnižší teplotu okolí** (`t_ambient_min`); vzduch uvnitř se pak bere rovný
  okolí (bez zatížení se skříň neohřívá). Přístroj bez `t_min` předpokládá −5 °C.
- *Verdikt*: nejhorší přístroj (prokázané překročení z artiklu/atributu má přednost před překročením předpokladu):
  „NEVYHOVUJE (orientačně) – F3 v řadě 1: ≈ 58 °C > t_max 55 °C; …“, jinak „vyhovuje (orientačně) – nejteplejší
  F3 ≈ 48 °C (t_max 55 °C, rezerva 7 K)“; nad 40 °C připomene odlehčení (derating) jističů. Stejný text je v TZ
  a v protokolu kusového ověření. Řadové svorky se hodnotí jen s vlastním `t_max`.

Pozor: hodnoty křivek k a c v tabulkách jsou orientační – pro průkaz ověř proti normě.

---

## 5. Kabely

Kabel je objekt: vzniká automaticky z vodiče blokového schématu, který má označení nebo typ kabelu, a drží s ním krok
(typ, průřez, délka, trasa se editují ve vodiči). `Úpravy → Kabel vybraného vodiče…` (`Ctrl+Shift+K`) otevře
žíly s čísly a **barvami** (ČSN 33 0165: L1 hnědá, L2 černá, L3 šedá, N modrá, PE zelenožlutá, L+ červená,
L− černá – jdou přepsat), stínění, poznámku a artikl kabelu z knihovny (CYKY, AYKY, H1Z2Z2-K…).

Výkazy **Kabely** (přehled), **Kabelový plán** (po žílách odkud–kam, i na svorky) a **Zapojovací seznam**
(všechna propojení včetně vnitřku rozvaděčů s barvou a průřezem).

**Značení vodičů a kabelů (ČSN EN 62491)** – výkaz **Značení vodičů a kabelů** (xlsx, pro tisk; do PDF dokumentace
nejde), jeden řádek = jeden štítek:
- **štítek kabelu** na obou koncích kabelu blokového schématu: označení kabelu dle IEC 81346 (`W3`, se strukturou `=DC-W3`) a ve
  druhém řádku adresa protějšího konce (`→ +RDC1-X1`);
- **návlečka** na obou koncích každé žíly vnitřního vodiče rozvaděče. Druh značení je parametr výrobních dat
  **Značení vodičů (návlečky)** – v panelu skříně rozvaděče (skupina Výrobní data) nebo pro celou firmu
  v `settings.json` → `standard.wiring.wire_marking`: **adresné – protější konec** (výchozí; na konci u F2:3 je
  „X1:1“, kam vodič vede), **odkud / kam** („F2:3 / X1:1“), **číslo vodiče** (označení vodiče, jinak pořadové
  číslo – stejné na obou koncích) nebo **bez návleček**. Vlastní umístění rozvaděče se na návlečce neopakuje
  (`F2:3`, ne `+RDC1-F2:3`), konec v jiném rozvaděči zůstane celý.

Návlečky jsou i ve **Výrobním zapojovacím seznamu** (sloupce Návlečka odkud / kam) a ve Výrobních datech
rozvaděče (xlsx) na listu **Návlečky**.

Výkaz **Kabely a vodiče k objednání** (jen v xlsx, do PDF dokumentace nejde) sečte materiál pro nákup: kabely
blokového schématu podle typu a průřezu (počet a metry z délky kabelu, kabel přes svorky jen jednou), vnitřní vodiče rozvaděčů
podle typu, průřezu a barvy (metry z výrobního zapojovacího seznamu – s rezervou na konce) a dutinky podle druhu.
Sloupec „Bez délky“ ukáže, kolika položkám délka chybí – součet metrů je pak neúplný.

---

## 6. Kontrola projektu a výpočty

`F7` (Úpravy → Kontrola projektu) projde celý projekt a vypíše nálezy do panelu **Kontrola** pod výkresem – dvojklik
skočí na prvek, filtr nahoře ukáže jen chyby, chyby a varování nebo informace. Panel neblokuje práci: dokud je
otevřený, nálezy se po každé změně projektu obnoví samy (tlačítko „Zkontrolovat znovu“ hned). Souhrn je i ve
stavovém řádku. Co kontrola hlásí:

- chyby: duplicitní označení, vodič na neexistující port, vodič na smazaný prvek, string mimo rozsah střídače,
  kabel přetížený (I > Iz) nebo nechráněný (In jističe > Iz);
- varování: nezapojené porty/prvky, skupiny svorek bez čísel, rozvaděč bez listu, můstky na neexistující
  svorky, přerušovací bod nebo kontakt bez protějšku, úbytek napětí přes mez, uzel odbočky bez odbočky;
- **potenciály**: program sleduje, co je vodivě spojené přes vodiče, uzly, svorky, můstky, PE lištu i přes
  přívody/vývody rozvaděčů. Spojení L–N, L–PE, L+–L− nebo dvou fází v jedné síti je chyba. Panel Vlastnosti
  ukazuje u vodiče potenciál každé žíly (`L1 X1`, `L+ G1`, `N (W3)`), výkaz **Potenciály** vypíše všechny sítě;
- informace: přívod bez vazby na blokové schéma, prvek bez artiklu, vodič bez kabelu/žil, selektivita nejistá.

Kontakty a přerušovací body:

| Kód | Závažnost | Význam |
|---|---|---|
| `contact_dup` | varování | dva kontakty nebo póly téhož přístroje mají stejné svorky |
| `contact_count` | varování | použito víc kontaktů druhu (NO, NC, silové), než kontaktní obraz má |
| `contact_unknown` | varování | pár svorek kontaktu není v kontaktním obrazu přístroje |
| `contact_image_syntax` | varování | v atributu `contacts` je nečitelný token |
| `interrupt_star_multi` | varování | ve skupině přerušovacích bodů jsou dva a více zdrojů hvězdy |

Oteplení rozvaděče (sekce 4, Rozložení a skříň):

| Kód | Závažnost | Význam |
|---|---|---|
| `thermal_device` | varování | teplota vzduchu v řadě přístroje překračuje jeho `t_max` z artiklu/atributu (nebo nejnižší teplota okolí skříně je pod jeho `t_min`) |
| `thermal_device` | info | jedna položka na list: u N přístrojů chybí rozsah teplot z datasheetu (předpoklad 40 °C), kolik z nich je nad předpokladem |

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

Podrobnosti kontroly stringů (sdílí ji `F7`, výkaz Výpočty i asistent průvodce):
- **Teploty** – návrhové teploty z Vlastností projektu (`pv_t_min` / `pv_t_max`, jinak −10 / 70 °C). Pole přijme
  i typografické minus a jednotku („−20 °C“) a uloží číslo; neplatný text dialog nezavře. Neplatná hodnota v už
  uloženém projektu → varování `calc_temp` „Návrhová teplota … není číslo – počítá se s …“.
- **Umpp(t)** – má-li modul (artikl nebo atributy stringu) teplotní součinitele **γ_Pmax i α_Isc**, počítá se
  Umpp(t) = Umpp·(1 + (γ_Pmax − α_Isc)/100·(t − 25)) (výkon = U·I, proud v MPP roste zhruba jako Isc). Jinak se
  použije β_Voc jako u Uoc – zjednodušení (Umpp za tepla vyjde o něco vyšší); asistent to uvádí důvodem
  „Umpp z β_Voc – zjednodušení“. Starší projekty bez γ/α počítají beze změny.
- **MPPT** – stringy se sčítají na MPPT podle vstupu střídače: DCk → MPPT (k − 1) div „stringů na MPPT“. Když
  střídač počet stringů na MPPT nemá, MPPT se nezjišťuje a proudy paralelních stringů se nesčítají (výchozí 2 na
  MPPT platí jen pro počet DC vstupů značky).
- **Režim stringů a optimizéry** – atribut střídače `string_mode` (prázdné = klasický). *S optimizéry*: navíc počet
  optimizérů ve stringu a výkon stringu proti pravidlům střídače a optimizéru (nejpřísnější platí), smíšení
  s neoptimalizovanými moduly (chyba, nemá-li optimizér `opt_partial`) a Uoc stringu s omezením napětí výstupu optimizéru.
  *Pevné napětí*: místo Uoc·n a okna MPPT se kontroluje počet optimizérů, optimizér na každém modulu, výkon stringu a
  věrohodnost pevného napětí vůči střídači a modulu; stringy na jednom MPPT se neporovnávají. Vstup optimizéru
  (Uoc při t min × moduly na optimizér ≤ Uin max, Isc STC modulu ≤ Isc max vstupu, P modulu ≤ P max, kompatibilita
  s výrobcem střídače) se kontroluje ve všech režimech. V režimech klasický a s optimizéry se paralelní stringy na MPPT
  porovnávají: nestejná délka, různé moduly a různá orientace (nepovinný atribut `orientation`) jsou varování.
  Texty hlášek jsou jen v `calc.string_issues`, závažnost určuje `calc.is_warning`.
- **Počet vstupů** – zná-li střídač počet MPPT i stringů na MPPT a je na něm zapojeno víc stringů, je to chyba
  „Střídač T1 má jen N vstupů (MPPT × stringů), zapojeno M stringů“ u stringů nad kapacitu.

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
optimizéry (typ a kusy na modul – prázdné = bez optimizérů; nebo **Z katalogu…**), střídač (typ, P AC, Umax, rozsah MPPT, Imax), stringy po střídačích (`20,20,18; 20,20`), kabely a jištění.

**Modul a střídač z katalogu:** tlačítko **Z katalogu…** u modulu a střídače otevře výběr artiklu (tabulka s Voc, Isc,
Imp, β, Usys resp. P AC, MPPT, okno MPPT, I/MPPT…, filtr „Výkon od–do“ a u střídačů „Fáze“). Vybraný artikl vyplní
pole průvodce a uloží se k projektu (štítek „Artikl: …“); **ruční úprava pole má přednost** před artiklem, **×** vazbu
na artikl zruší (pole zůstanou). Šedě kurzívou jsou neúplné nebo neověřené řádky (zdroj `web`/`seed` nebo poznámka
„doplněno WebSearch“, chybí Voc/Isc resp. U DC max/okno MPPT) – důvod je v tooltipu; před použitím je zkontroluj
podle datasheetu. Filtry „Výkon“ a „Fáze“ neskrývají artikly, které údaj nemají – zobrazí se šedě s poznámkou. Nepovinná pole: Impp,
β Uoc, Isc max na MPPT, stringů na MPPT, návrhové teploty min/max (předvyplněné z firemního standardu, uloží se do
projektu pro kontrolu `F7`) a „Celkem modulů“.

**Optimizéry a režim stringů:** **Z katalogu…** u optimizéru otevře výběr (výrobce, typ, P, Uin max, Isc in, moduly na
optimizér, kompatibilita, zdroj; neúplné a neověřené řádky šedě) a vyplní typ a kusy na modul (1 nebo 0,5 při dvou
modulech na optimizér); **×** vazbu zruší. Artikl se uloží do specifikace (`optimizer.component_id`) a generátor z něj
doplní stringům parametry optimizéru a pravidla stringu pro fáze střídače. Volba **Režim stringů** má hodnoty
*Automaticky (z artiklu)* (režim z artiklu střídače, jinak z artiklu optimizéru, jinak klasický), *Klasický*,
*S optimizéry* (klasické meze Uoc a MPPT, navíc počet optimizérů, výkon stringu a vstup optimizéru) a *Pevné napětí*
(SolarEdge – délku stringu určuje počet optimizérů, Uoc·n a okno MPPT se nekontrolují). Údaje, které artikl nezná,
kontrola hlásí jako „chybí údaj“ (varování) – nic se neodhaduje.

**Asistent stringů** pod polem Stringy se přepočítá při každé změně a ukazuje: rozsah počtu modulů ve stringu
(n min–n max) s důvody (Uoc za studena, Umppt, Umax systému modulu, „Umpp z β_Voc – zjednodušení“), nejvýš stringů na
MPPT, **řádek režimu stringů** (např. „pevné napětí 750 V – Uoc·n se nekontroluje; optimizérů 14–50, P stringu ≤ … W“;
jen při optimizérech nebo neklasickém režimu) a **řádek vstupu optimizéru** (Uoc modulu při t min, Isc a P modulu vůči
limitům optimizéru), stav každého zadaného stringu (OK, nebo hláška; **oranžově** jsou jen varování – chybějící údaj,
omezení výkonu, tolerance výrobce, nestejné paralelní stringy –, **červeně** chyby), poměr DC/AC (bez P AC
„P AC střídače není zadán“) a doporučený počet střídačů. Stav stringů je **stejný jako v `F7`** po vygenerování:
asistent přiřazuje stringy na MPPT stejně jako generátor, počítá stejnými funkcemi (viz Výpočty v kapitole 6) a hlásí i
nestejné paralelní stringy na jednom MPPT. Tlačítko **Navrhnout stringy** rozdělí „Celkem modulů“ (jinak součet
zadaných stringů) do co nejméně vyrovnaných stringů v mezích střídače (u optimizérů po násobcích modulů na optimizér) a vyplní pole Stringy. Chyby stringů v průvodci jen varují – projekt jde vygenerovat i tak; blokují
jen chyby zadání (např. text místo čísla).

Vygeneruje se blokové schéma (stringy → DC rozvaděče → střídače → AC rozvaděč → síť) a listy všech rozvaděčů včetně
kabelů a vazeb. Hned potom spusť `F7`.

**Připojení k DS** (pole pod Distributorem): **nn** = AC rozvaděč FVE jde vývodem XOUT přímo do HDS (jako dřív).
**VN** = trafostanice. AC rozvaděč FVE → **hlavní rozvaděč nn** RHN (přívod XT od transformátoru, hlavní jistič,
přípojnice nn, vývod X1 k FVE, SPD T1, vývod X2 spotřeba objektu) → **transformátor** TR1 → podle pole **Trafostanice**:
- **kiosková TS** (výchozí, nové stanice) – **rozvaděč VN** RVN po **polích**: kabelová pole (odpínač VN, uzemňovač,
  kapacitní indikátor napětí, kabelová koncovka, přívod XDS1/XDS2 z DS – u smyčky dvě), přípojnice VN, při měření na VN
  **měřicí pole** (odpínač, MTP, MTN) a za ním přípojnice odběratele, **transformátorové pole** (odpínač VN + pojistky
  VN s úderníkem, nad 1000 kVA vypínač VN s ochranou; uzemňovač, koncovka, vývod X1 k transformátoru);
- **zděná TS** – totéž, pole se jmenují **kobky** (K1 kabelová kobka…);
- **sloupová TS** – bez rozvaděče VN: na sloupu úsekový odpínač VN, pojistky VN a svodiče přepětí VN (v blokovém
  schématu jako samostatné prvky), měření jen na nn, bez smyčky.

**Elektroměrový rozvaděč** RE s fakturačním elektroměrem je samostatný: měřicí obvody k němu vedou kabely z vývodů
XMI (proud ze sekundáru MTP) a XMU (napětí z přípojnice nn, při měření na VN ze sekundáru MTN) rozvaděče s měřením.
Všechny části trafostanice (RVN, TR1, RHN, RE, prvky na sloupu) mají atribut **Trafostanice** („TS1 kiosková
trafostanice“) a přístroje rozvaděče VN atribut **Pole / kobka** („P1 kabelové pole“) – oba jdou změnit v panelu
vlastností a určují rámečky v jednopólovém schématu. Ze Sn transformátoru se dopočte hlavní jistič (In nn → nejbližší
vyšší řada), převod MTP (x/5 A), pojistky VN (≈ 1,8 × In VN – ověř podle tabulky výrobce) a jistič spotřeby (≤ hlavní
/ 1,6 kvůli selektivitě); ve specifikaci je mění `connection.main_board.main_in`, `ct_ratio`, `fuse_vn`,
`main_board.load_in`, označení TS `connection.ts.ref`/`desc`. Rozvaděč VN nemá vícepól ani plán svorkovnice
(dokumentuje se jednopólovým schématem), přístroje VN se na DIN lištu nerozmísťují.

**Značky VN** (kategorie VN v knihovně, ČSN EN 60617): odpínač VN (kroužek + odpojovací čárka), odpojovač, vypínač VN
(křížek), pojistka VN s úderníkem, kabelová koncovka, kapacitní indikátor napětí (VDS), svodič přepětí VN;
uzemňovač, MTP a MTN. Motorové pohony a ochrany VN se nekreslí; rozvaděč telemetrie (AXY) se vloží makrem.

**Jednopólové schéma** (Zobrazit → Jednopólové schéma, `Ctrl+Shift+J`) se **odvozuje** z blokového schématu a listů
rozvaděčů – nic se nekreslí znovu, po změně rozvaděče se samo přepočítá. U trafostanice s rozvaděčem VN začíná jeho
přípojnicí: **pole visí pod ní**, každé ve vlastním čárkovaném rámečku s názvem (pole / kobka), DS je pod kabelovými
poli; bez rozvaděče VN (přípojka nn, sloupová TS) vede od DS dolů. Každý rozvaděč je čárkovaný rámeček s označením,
přístroj jedna značka s popiskem (označení, In, typ…), přípojnice vodorovná čára, kabely mezi částmi s označením, typem
a délkou. Rozvaděč VN, transformátor, rozvaděč nn za ním a elektroměrový rozvaděč jsou v **rámečku trafostanice**;
elektroměr leží v rámečku elektroměrového rozvaděče vpravo od rozvaděče s měřením, čárkovaně spojený s MTP a MTN /
přípojnicí. Vodiče jen s PE, PE lišty a uzemnění se vynechají. Končí u střídačů (popisek „DC: 3 stringy“ – DC část mají
listy DC rozvaděčů). Formát A3–A0 podle velikosti (1 : 1). Je v PDF dokumentaci hned za blokovým schématem (číslo listu
„1/8 JPS“) a jde exportovat do DXF (Soubor → Export DXF na záložce jednopólového schématu).

**Ruční rozmístění:** levým tlačítkem chyť přístroj, pole, rozvaděč nebo trafostanici (pod myší se zvýrazní) a táhni –
posune se i vše, co je pod ním (mřížka 2,5 mm, `Ctrl+Z` vrátí). Pravé tlačítko → **Vrátit automatickou polohu**
(jedné části) nebo **Vrátit automatické rozmístění celého schématu**. Posuny se ukládají do projektu (formát 12) a platí
i pro PDF a DXF; strana drží automatické rozmístění, takže posun jedné části nehýbe ostatními.

DC strana se dělá jako na stavbě: ke každému střídači vznikne **DC rozvaděč po trase** (počet zadáš, i 0 –
jen SPD na každý string, **bez odpínače**: přívod jde rovně na vývod a SPD odbočuje z přívodní svorky, stringy jím
procházejí odděleně) a **DC rozvaděč u technologie** (pojistkové odpojovače gPV a SPD DC na každý string – jediné
odpojovací místo stringů). Výchozí přístroje podle praxe ENVO: **pojistkový odpojovač
ETI EFH 10 DC 2p** (vložky CH10x38 gPV 1000 V, max 25 A; kategorie DC-20B – **nespínat pod zátěží**, vypíná se
odpínačem střídače), **svodič Weidmüller VPU PV I+II 3 1000** (ve výkresu typ, Uc 1000 V DC,
Up ≤ 3,8 kV, ISCPV 11 kA – proto bez vlastní pojistky) připojený z výstupních svorek odpojovače (strana
střídače) dvojitou dutinkou. **In pojistek** se při prázdném poli určí podle stringu (IEC 62548): nejmenší vložka
≥ 1,5 × Isc modulu, nejvýš 2,4 × Isc a max. jištění modulu z katalogu; SolarEdge (střídač nebo optimizéry) 25 A.
Artikly mění `dc.fuse_component` a `dc.spd_component` ve specifikaci. **Stringy se v rozvaděči nikdy nespojují** – každý jde
zvlášť až na vlastní DC vstup střídače (DC1…DCn podle počtu MPPT × stringů na MPPT; zná-li střídač počet MPPT
(zadáním nebo z artiklu), stringy se rozdělí na MPPT rovnoměrně – 1. string na MPPT 1, 2. na MPPT 2… –, jinak jdou
na DC1, DC2… za sebou; paralelní spojení dělá
jen SolarEdge a kreslí se jako jeden string). Blok DC rozvaděče v blokovém schématu má porty podle přívodů
(X1…Xn od stringů) a vývodů (Xn+1… dál). Když obojí vypneš, vloží se jen samostatný odpínač DC v blokovém schématu.
Průvodce se ptá i na **objekt** (`building` ve specifikaci): **firma** a **bytový dům** mají DC rozvaděče a AC
rozvaděč zvlášť; u **rodinného domu** je DC i AC v jednom **rozvaděči FVE (RFVE)** – místo DC rozvaděče u technologie
má RFVE na každý string pojistkový odpojovač a SPD DC (přívody za AC přívody od střídačů, vývody ke střídači) a k tomu
AC část s vývodem do HDS. V blokovém schématu stojí RFVE před střídačem, AC kabel od střídače se vrací shora;
rozvaděče po trase zůstávají. Přípojka VN se u rodinného domu negeneruje.
AC rozvaděč má přívody po střídačích, jističe, rozvodné svorky s můstky, SPD, hlavní vypínač a vývod do HDS.
Označení jsou jedinečná uvnitř každého rozvaděče (jako v EPLAN `+RDC1-X1`), takže X1 smí být v každém
rozvaděči; listy blokového schématu sdílejí jeden prostor označení.

Jištění ve specifikaci i v průvodci se zadává **číslem v ampérech**: `dc.fuse_in`, `dc.disconnect_in`,
`ac.breaker_in` (např. `40`, ne „C40“ ani „B40“ – charakteristiku nese prvek jističe) a `ac.main_in`; „40,0“
i `40.0` se berou jako 40. Typ svodiče `dc.spd` / `ac.spd` je text (T1, T2, T1+T2, i T1+T2+T3).

Totéž umí příkaz `python -m envocad.generate spec.json vystup.ecp` – specifikace je JSON popsaný
v `envocad/generate.py`. To je cesta pro AI agenty: z poptávky a datasheetů připraví specifikaci, program
vygeneruje projekt, ty ho upravíš.

**Velké JPS na víc listů**: když by se JPS nevešlo na největší povolený list (firemní standard
`jps_max_paper`, výchozí A2 – Knihovna → Firemní standard…), průvodce i příkaz `python -m envocad.generate` ho
rozdělí blokové schéma: první list „Blokové schéma – AC a připojení“ (AC rozvaděč, síť, HOP; u přípojky VN celá
trafostanice a elektroměrový rozvaděč, u rodinného domu rozvaděč FVE), za ním listy střídačů („Blokové schéma –
T1–T3“). AC kabel vede přes pár přerušovacích bodů „AC-T1“ (u rodinného domu i DC vodiče do rozvaděče FVE a z něj,
„RFVE-X5“), údaje kabelu nese jen úsek na listu AC. Odvozené jednopólové schéma se nemění. Ve specifikaci lze limit přebít:
`"jps": {"split": "auto" | "none", "max_paper": "A1", "paper": "A2"}`. Řada jednoho střídače, která se sama na
limit nevejde (např. 12 stringů), dostane větší formát (A1, A0) – DC řetězec se nedělí.

Výchozí hodnoty (kabely, zpracoval) bere průvodce z **firemního standardu** (menu Knihovna).

---

## 8. Výstupy

| Výstup | Kde |
|---|---|
| PDF listu (skutečný formát / zmenšený na A4) – z blokového schématu, schématu (vícepólu) i plánu svorkovnice rozvaděče (strany A4); z rozložení celý pohled zmenšený na A3 (A4) | Soubor → Export PDF / Export PDF na A4 |
| DXF listu – z blokového schématu, listu rozvaděče v editoru, vícepólu a jednopólového schématu (z plánu svorkovnice a rozložení program upozorní, ať se použije PDF) | Soubor → Export DXF |
| **Celá dokumentace do jednoho PDF**: titulní list, obsah, listy blokového schématu, jednopólové schéma, schéma + plán svorkovnice každého rozvaděče (kromě rozvaděče VN), výkazy, změnový list – strany schématu a plánu svorkovnice A4, ostatní A3 (smíšené formáty v jednom PDF, obsah i „n/N“ počítají skutečné strany) | Výstupy → Celá dokumentace (`Ctrl+Shift+E`) |
| Výkazy xlsx (Data pro DS, Výpočty, Přístroje, Výkaz materiálu, Kabely, Kabelový plán, Kabely a vodiče k objednání, Zapojovací seznam, Svorkovnice, Plán svorkovnice, Štítky) | Výstupy → Výkazy listu / projektu |
| Protokol kusového ověření rozvaděče (docx) | Výstupy → Protokol kusového ověření |
| Technická zpráva (docx) – kostra s tabulkami z modelu a výpočty | Výstupy → Technická zpráva |
| Štítky pro tiskárnu (CSV, `;`, UTF-8 BOM) | Výstupy → Štítky pro tiskárnu |
| Otevřené připomínky jako anotace PDF nebo vrstva `PRIPOMINKY` v DXF | Výstupy → Přidávat připomínky do exportu (sekce 9) |

Rámeček listu má popisové pole (projekt, zakázka, investor, místo, list, číslo listu, zpracoval, datum,
revize, formát), souřadnicovou síť A–H × 1–6 a QR kód s identifikací výkresu. Údaje se zadávají v
Soubor → Vlastnosti projektu, název firmy v popisovém poli v nastavení (`standard.company`) – stejný název je na
titulní straně dokumentace a v protokolu kusového ověření. Dlouhý text se v buňce popisového pole zmenší, a když
se nevejde ani tak, zkrátí se s „…“. Kresba vícepólu se automaticky posune nahoru, aby nezasahovala do popisového
pole a QR kódu (ručně přesunuté přístroje zůstanou, kde jsou).

**Celá dokumentace (PDF)**: obsah má sloupce *Strana* (fyzická strana PDF, u víc stran rozsah „19–20“), *Název*
a *List výkresu* (číslo listu projektu, které ukazuje popisové pole listu – např. „2/6“). Strany obsahu, výkazů
a změnového listu nesou v popisovém poli číslo strany dokumentace („15/33“), strany listů číslo listu výkresu.
Obsah, výkazy i změnový list jsou tabulky stránkované na víc stran; šířky sloupců se řídí obsahem a šířkou strany,
dlouhý text se v buňce zalomí. **Bez rámečku** (výchozí) má každá strana malé „strana n/N“ v pravém dolním rohu –
dokumentace se vždy dá očíslovat a seřadit, rámeček ale zůstává volbou uživatele (např. pro vložení do rámečku
zákazníka). Otevřené připomínky listu rozvaděče se v dokumentaci (s volbou „Přidávat připomínky do exportu“)
ukážou na straně jeho vícepólu u přístroje, ke kterému patří (vodič → jeho první konec); připomínka bez vazby na
přístroj je vlevo nahoře na první straně vícepólu s poznámkou, že patří k listu rozvaděče.
Při exportu se program zeptá, jak dát do PDF **listy JPS**: *Zmenšit na A3* (výchozí, jako dřív) nebo *Skutečný
formát listu* (strana PDF má rozměr listu – A2, A1…, PDF pak má smíšené formáty stran). Výchozí volbu nastavíš ve
Firemním standardu (`standard.doc_jps_page`: „A3“ / „list“). PDF jednoho listu (Soubor → Export PDF…) má vždy
skutečný formát listu, zmenšení nabízí jen „Export PDF na A4 (zmenšeno)“.

**docx** (technická zpráva, protokol kusového ověření): A4, jazyk čeština, vlastnosti dokumentu (název, autor =
Zpracoval projektu nebo `standard.author`, datum); výkazy v technické zprávě na šířku, šířky sloupců podle obsahu.
**xlsx**: označení začínající „=“ (=AC+RDC1-F1) jsou text, ne vzorec; průřez, délka, číslo žíly a číslo svorky
jsou čísla.

### Revize
Soubor → Vlastnosti projektu: revize, datum, změnový list (řádek = `revize | datum | popis | zpracoval`).
**Porovnat s revizí (.ecp)** porovná aktuální projekt se starší uloženou verzí (prvky, vodiče, kabely, můstky,
skříň) a jedním tlačítkem zapíše změny do změnového listu; dvojklik skočí na změněný prvek.

Výkres ukazuje změny trojúhelníky s číslem revize (červeně, také v DXF ve vrstvě `REVIZE`); revize listu se
objeví v popisovém poli toho listu (když je zapnutý rámeček). List, který se od začátku sledování revizí
nezměnil, ukazuje výchozí stav – revizi z vlastností projektu před prvním porovnáním (při prvním porovnání se
uloží jako uzavřená revize), a když tam žádná nebyla, prázdnou revizi; novou revizi ukazují jen změněné listy.
Opakované porovnání do téže otevřené revize řádky změnového listu té revize nahradí (nezdvojí). Znak „|“ v popisu
změny se zapíše jako „¦“, aby se sloupce změnového listu nerozpadly. Revizi uzavřeš v menu **Soubor**:

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
- **PDF listu** (blokové schéma) a **Celá dokumentace** – připomínky jsou anotace PDF (komentáře v Adobe Acrobat a
  Readeru: bod jako poznámka, oblast jako obdélník; autor, text a číslo). PDF vícepólu a plánu svorkovnice
  připomínky nemají; v celé dokumentaci jsou připomínky listu rozvaděče na straně jeho vícepólu (bod u přístroje,
  viz sekce 8).
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
- **Firemní standard…** – výchozí kabely, zpracoval, název firmy, formát stran schématu rozvaděče a plánu
  svorkovnice (výchozí A4 na šířku), největší list JPS z průvodce (`jps_max_paper`, výchozí A2) a výchozí volba
  listů JPS v PDF dokumentace (`doc_jps_page`, výchozí „Zmenšit na A3“) (`~/.envocad/settings.json`).
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
| `M` | zrcadlit |
| `T` | text |
| `Delete` | smazat |
| `Ctrl+Z` / `Ctrl+Y` | zpět / znovu |
| `Ctrl+C` / `Ctrl+V` | kopírovat / vložit kopii |
| `Ctrl+Alt+M` | uložit výběr jako makro |
| `Ctrl+F` | najít označení |
| `F7` | kontrola projektu (panel Kontrola) |
| `Ctrl+K` | hledat příkaz |
| `F11` | jen výkres (skrýt panely) |
| `Ctrl++` / `Ctrl+-` | přiblížit / oddálit |
| `N` | narovnat vybrané vodiče |
| `Ctrl+M` / `Ctrl+J` | vícepól / jednopól |
| `Ctrl+Shift+J` | jednopólové schéma (odvozené z rozvaděčů) |
| `Ctrl+Shift+M` | plán svorkovnice |
| `Ctrl+L` | rozložení rozvaděče |
| `Ctrl+Alt+K` | skříň rozvaděče |
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
