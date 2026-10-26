# EnvoCAD – uživatelská příručka

Verze 0.10. EnvoCAD je nástroj pro elektro-dokumentaci fotovoltaických elektráren: blokové schéma celé elektrárny (dříve nazývané jednopólové schéma, JPS; skutečné jednopólové schéma s přístroji rozvaděčů je v plánu),
rozvaděče (vícepólové schéma, svorkovnice, rozložení, oteplení), kabely, výpočty, výkazy a kompletní
dokumentace v jednom PDF. Všechno vychází z jednoho datového modelu – co nakreslíš, to se propíše do
všech výstupů.

---

## 1. Instalace a spuštění

Potřebuješ Python 3.11–3.14 (Windows i Linux).

```
# Windows (cmd i PowerShell; obejde zákaz spouštění skriptů .ps1)
scripts\install.cmd
scripts\run.cmd           # nebo dvojklik na scripts\run.cmd

# Linux
bash scripts/install.sh
scripts/run.sh
```

Skripty vytvoří virtuální prostředí `.venv`, nainstalují závislosti (PySide6, ezdxf, openpyxl, python-docx, segno, pypdf)
a spustí program. Ručně: `python -m venv .venv`, aktivovat, `pip install -e .`, `python -m envocad` (na Windows
`py -m envocad`, pokud `python` otevírá Microsoft Store).

Samostatná aplikace bez Pythonu pro kolegy: `scripts\build.ps1` / `scripts/build.sh` sestaví složku
`dist/EnvoCAD` přes PyInstaller.

**Aktualizace:** při spuštění přes `scripts\run.cmd` (nebo samostatnou aplikaci nainstalovanou ze sdílené složky) se
EnvoCAD zeptá, když vyjde nová verze – **Aktualizovat** ji nainstaluje a spustí, **Teď ne** se zeptá zase za den.
Nová verze se objeví při druhém spuštění po vydání (první na pozadí zjistí, že existuje). Rozpracované změny ve
vlastním klonu repozitáře se nikdy nepřepíšou. Vypnutí: `"auto_update": false` v `settings.json`; návrat na
předchozí verzi: `.venv\Scripts\python.exe -m envocad.updater rollback`. Podrobnosti v `docs/RELEASE.md`.

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
Zrcadlit (jen v blokovém schématu), Kopírovat a Smazat (v blokovém schématu i Uložit výběr jako makro); u vodiče navíc Svorky, Kabel a Narovnat (Narovnat jen v blokovém schématu),
u bloku ROZVADĚČ Otevřít rozvaděč, na prázdném místě Vložit značku, Vodič a Přizpůsobit list; Vložit kopii je na prázdném místě vždy,
zašedlé, dokud není co vložit. Všechny položky jsou stejné příkazy jako v menu a na lištách (stejné zkratky, `Ctrl+Z` vrací). V režimu Vodič nebo Vkládání pravé tlačítko jen
ukončí režim. Připomínky mají vlastní menu (sekce 9).

**Stavový řádek** vlevo ukazuje nápovědu k aktuálnímu režimu, vpravo souřadnice kurzoru v mm (Y nahoru jako ve
výkresu, zaokrouhlené na mřížku 2,5 mm – tam se bod skutečně umístí), mřížku 2,5 mm, zoom (100 % = skutečná velikost na monitoru), souhrn kontroly („F7: 2 chyby, 5 varování“,
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

**Jeden kabel přes dvojici přerušení:** údaje kabelu (označení W, typ, průřez) dej jen jednomu úseku a u druhého
úseku smaž i automatické označení W – úplně prázdný úsek je pokračování téhož kabelu. Seznam kabelů, kabelový
plán i kusovník pak kabel uvedou jednou s konci za přerušením. Mají-li označení oba úseky, jsou to dva kabely;
nesou-li typ nebo průřez oba, kontrola hlásí `cable_split`.

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

### Přívod a vývod
Svorky přívodu i vývodu rozvaděče jsou **jedna značka *Přívod / vývod*** (`sb.feed`). Port je nahoře, kabel jde
zespodu; jestli jde o přívod, nebo vývod, ukazuje **šipka** na kabelu (k svorce = přívod, od svorky = vývod) a volba
**Směr** (přívod / vývod) v panelu Vlastnosti nebo v dialogu parametrů. Nová značka z knihovny je přívod. Přepnutí
směru je jeden krok `Ctrl+Z`: s ním se přepočte „Odkud“ ↔ „Kam“ z vazby na blokové schéma a port bloku ROZVADĚČ se
přesune na druhou stranu (přívody vlevo, vývody vpravo) – kabel zůstane připojený. Svorku shora (kabel přichází
shora) uděláš otočením `R` o 180°. Na listech **RFVE** (rodinný dům) a **RFVE.AC** generátor kreslí **vše
zespodu**: přívody i vývody ve spodní řadě, sběrnice nahoře a přívodní větev teče nahoru (svorka → jistič →
sběrnice); DC stringy rozvaděče FVE jako „U“ (přívod, pojistkový odpojovač nahoru, ohyb, dolů na vývod; SPD nad
ohybem, jeho PE nad sběrnicí do XPE). DC rozvaděče (RFVE.DC, RDCn), HR, RE a RVN mají rozložení jako dřív. Vícepól
se tím nemění (přívody v něm zůstávají nahoře). **Starší projekty** (do formátu 12) se při otevření převedou beze
ztráty: přívody i vývody dostanou novou značku, porty zůstanou na místě, nic se nepřeskládá (přibude jen šipka);
převedený přívod je pootočený o 180°, **popisek** (označení, popis, Odkud) ale zůstane tam, kde byl – vpravo od svorky
(přívod otočený o 90°/270° má popisek na stejné straně jako dřív). Vícepól starého listu zůstane, jak byl (ani ruční
přívod zespodu se v něm neotáčí), uzavřené revize zůstanou uzavřené (převod nehlásí změnu listu).
Přeskládat je můžeš přegenerováním nebo ručně (otočení `R` – vodič na port drží). Starší EnvoCAD projekt formátu 13
a makra verze 3 neotevře.

### Založení
V blokovém schématu vlož **Rozvaděč (blok)** (R1), zapoj do něj kabely a dvakrát na něj klikni. Poprvé program nabídne
**šablonu**: *AC rozvaděč FVE* (přívod, hlavní vypínač, rozvod, SPD, vývody s jističi), *DC rozvaděč* (každý
string zvlášť: pojistkový odpínač (u technologie) nebo jen průchozí svorky (po trase), SPD, vývod), nebo prázdný list. Otevře se záložka
`R1 – schéma` – vícepólové schéma rozvaděče.

**Rozvod** v rozvaděči jde dvěma způsoby (parametr šablony i průvodce): **sběrnice potenciálů** – prvek
*Sběrnice (rozvodný vodič)*; ve vícepólu se kreslí jako v EPLAN vodorovnými čarami L1 L2 L3 N PE přes
celou stranu (i přes více stran) s názvem potenciálu a šipkou na obou koncích (`1L1`… – označení sběrnice je
předpona), přístroje se na ni napojují odbočkou s tečkou; porty `T1…T12` shora (přívody), `1…13` zdola (vývody)
a `B1…B12` zdola (přívody, které do sběrnice tečou zespodu). Sběrnice z generátoru, vestavěných maker a šablony
„AC rozvaděč FVE“ je **parametrická**: vlastnost *Přívody zdola* (`taps`) určuje počet přívodů, *Rozteč přívodů*
(výchozí 30 mm) jejich vzdálenost a *Vývody vpravo* počet vývodů za posledním přívodem; délka sběrnice a poloha portů
se podle nich přepočítají, takže každý přívod `Bk` je přímo nad svým jističem a vývody `1` (PE → XPE), `2` (SPD) vlevo
a `3` (hlavní vypínač → XOUT) vedou také rovně – bez schodů pro libovolný počet střídačů. Vodič na port za počtem
(např. `B9` při 7 přívodech) sběrnici sám prodlouží. Sběrnice bez této vlastnosti (starší projekty, vlastní makra,
nově vložená z knihovny) má pevnou délku jako dřív (do 6 přívodů svisle, při 7–12 schodovitě bez křížení, hlavní
vypínač z vývodu 13). PE je potenciál sběrnice (1PE),
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
žíla vlastní svorku s číslem. **Přívod a vývod** (jedna značka *Přívod / vývod* `sb.feed`) jsou také svorkovnice: ve
vícepólu dostane každá žíla svorku s číslem (bez zadání 1…n, jinak „Svorka č.“ stejně jako u skupiny),
jsou v plánu svorkovnice i v BOM. `Úpravy → Očíslovat svorky automaticky` doplní chybějící čísla (skupiny,
PE lišta), ruční čísla nechá.

`Úpravy → Svorkovnice a můstky…` (`Ctrl+Shift+T`): tabulka svorek vybrané svorkovnice (vnitřní/vnější strana,
můstek) a editace **můstků** – jedna skupina na řádek, čísla svorek pomlčkou (`1-6-11-16`). Můstky se kreslí
ve vícepólu, v blokovém schématu čárkovaně mezi skupinami, a jsou ve výkazech a BOM. Můstky patří listu rozvaděče –
svorkovnice X1 v RDC1 a X1 v RFVE.AC jsou dvě různé. Přepnutí svorkovnice v dialogu rozpracované můstky nezahodí;
OK uloží změny všech svorkovnic jedním krokem undo a odmítne číslo svorky, které na svorkovnici není.
Šířka skupiny svorek v rozložení = počet svorek × šířka svorky z artiklu (`width_mm`, např. Weidmüller A2C 1.5 =
3,5 mm), bez artiklu (nebo když artikl šířku nemá – Bečov, ELEMAN) počet svorek × 6,2 mm; ruční „Šířka skupiny“
(moduly) má přednost. Koncové desky a zarážky přidá pole „Koncové desky / zarážky [mm]“ v panelu Vlastnosti (katalog
jejich šířku nemá, výchozí 0). **Můstek jako artikl**: v poli „Artikl můstku“ skupiny svorek vyber můstek z nabídky
(můstky z knihovny, s artiklem svorky jen téhož výrobce – např. Weidmüller ZQV 2.5N/2). Výkaz materiálu pak u můstků,
které leží na této skupině, uvede typ a výrobce; n-pólový můstek delší než skupina dostane poznámku „zkrátit z n
pólů“, kratší (nebo bez počtu pólů) se vypíše bez typu s poznámkou a F7 varuje (`bridge_article`). Bez výběru zůstane
obecný řádek „Můstek svorek“ (můstek se nevybírá automaticky – katalog nemá vazbu svorka → můstek).

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
panel **skříně**: označení, řady, moduly na řadu, rozměry, rozteč řad, IP, IK (mechanická odolnost krytu, ne zkrat), montáž, materiál, dveře, Un/In, Icw [kA] (1 s), Ipk [kA] a Ik v rozvaděči [kA],
síť, rezerva, teplota okolí, nejnižší teplota okolí (nepovinné), RDF (`Ctrl+Alt+K` otevře totéž jako dialog; skříň lze
vybrat z artiklů).
**Rozměry přístrojů z artiklů.** Přístroj s artiklem má v rozložení skutečnou šířku a výšku z katalogu (Hager MBN
1 M × 83 mm); kompaktní jistič / odpínač 3VA a jiné nemodulové přístroje (MCCB, artikl bez modulů vyšší než 100 mm)
se kreslí jako obdélník š × v (3VA11 76,2 × 130 mm) s popiskem rozměru, svorkovnice z artiklu jako řada úzkých
svorek („8 × 3,5 mm“). Přístroje jsou svisle na střed lišty. Priorita: ruční rozměr prvku (panel Vlastnosti na listu
rozvaděče: „Šířka / Výška v rozložení [mm]“, „Hloubka přístroje [mm]“ – prázdné pole ukáže použitou hodnotu a zdroj)
> ruční moduly (liší-li se od artiklu) > artikl > moduly z atributu; moduly „0“ = přístroj mimo rozložení. Změna
artiklu v dialogu prvku ruční rozměry vymaže (jeden krok undo). Projekt bez artiklů vypadá jako dřív. Délky vodičů
výrobního seznamu počítají se skutečnou výškou přístroje z artiklu (svorky na horní / dolní hraně).

Panel ukazuje obsazenost a **odhad oteplení** podle IEC TR 60890 (ΣPv z atributu `p_loss_w`, jinak z artiklu,
jinak odhad z In a pólů – zdroj „Pv: 5× artikl, 1× ruční, 2× odhad“ je u ΣPv v panelu, v TZ (tabulka ztrát po
přístrojích) i v protokolu kusového ověření; chladicí plocha podle montáže, Δt uprostřed a v horní části, kritický přístroj, hodnocení). Parametry
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

Rozložení rozvaděče (rozměry z artiklu nebo ručních rozměrů prvku; přístroj bez nich se nekontroluje):

| Kód | Závažnost | Význam |
|---|---|---|
| `layout_overflow` / `layout_overlap` | varování | přeplněná řada, přístroj za koncem řady, překryv přístrojů (šířky z artiklů) |
| `outside_enclosure` | varování | přístroj umístěný v řadě mimo skříň (po zmenšení počtu řad) |
| `layout_height` | varování | přístroj je vyšší než rozteč řad – zasahuje do sousední řady (3VA13 248 mm při rozteči 150 mm) |
| `layout_enclosure` | varování | přístroj je širší než užitná šířka řady |
| `layout_depth` | varování | hloubka přístroje je větší než hloubka skříně (jen se zadanou hloubkou skříně) |
| `bridge_article` | varování | artikl můstku skupiny svorek není v knihovně, není můstek nebo má méně pólů než skupina můstku |

Jištění v rozvaděčích (`protection_findings`):

| Kód | Závažnost | Význam |
|---|---|---|
| `fuse_no_in` / `breaker_no_in` | varování | „Pojistka bez In – doplňte“ / „Jistič bez In – doplňte“ (In prázdné, např. ručně kreslený list) |
| `fuse_no_in` / `breaker_no_in` | chyba | In nechal prázdné generátor, protože nic nevyhovělo (atribut prvku `in_unresolved` = důvod, je v hlášce): pojistka stringu, na kterou nevyhoví žádná vložka gPV (Isc, max. jištění modulu, max. In držáku) nebo modul nemá Isc; vývod HR, na který není selektivní jistič, jenž unese proud FVE |
| `fuse_over_holder` | chyba | In vložky je nad max. In přiřazeného držáku (artikl `fuse_holder`, sloupec `in_max_a`) |

Kontroly z údajů artiklů (`model/ratings.py`, návrh `docs/design/kontroly_artiklu.md`). Údaj se bere z atributu
prvku, jinak z přiřazeného artiklu; když chybí, kontrola nic nehlásí. Napětí DC = Uoc stringů, které prvkem vedou,
při nejnižší návrhové teplotě (Vlastnosti projektu). **Jedna příčina = jeden nález:** se zadanou návrhovou t_min
hlásí podkročení Un / Ucpv přístrojů v cestě stringu jen `calc_string` (chyba, všechny takové přístroje v jedné
hlášce; totéž ukáže TZ i výkaz Výpočty), `un_dc` / `spd_ucpv` je znovu nehlásí. Když projekt návrhovou teplotu nemá,
počítá se s −10 °C a `un_dc` / `spd_ucpv` jsou jen jedna informace na list.

**Kde zadat zkratové údaje** (kontroly `sc_*` bez nich nic nehlásí, jen `sc_upstream` počítá z trafa):

| Údaj | Kde | Klíč |
|---|---|---|
| Ik v místě připojení [kA] (vyjádření DS / výpočet; prázdné = odhad z transformátoru Sn, uk) | Soubor → Vlastnosti projektu; v průvodci krok „Objekt a připojení“ (zapíše se i do bloků HR, RE, RFVE.AC) | `meta["ik_ka"]` |
| Ik v rozvaděči [kA] | panel / dialog skříně („Ik v rozvaděči“), nebo Vlastnosti bloku rozvaděče (atribut „Ik v rozvaděči“) | parametr skříně `ik_ka`, atribut bloku `ik_ka` (blok má přednost) |
| Icw [kA] (1 s), Ipk [kA] | panel / dialog skříně | parametr skříně `icw`, `ipk` |

Pozor: pole „IK“ u skříně je mechanická odolnost krytu (IK07…), se zkratovým proudem nesouvisí.

| Kód | Závažnost | Význam |
|---|---|---|
| `calc_cable` (I2) | chyba | smluvený vypínací proud I2 > 1,45·Iz kabelu (pojistka gG: I2 = 1,6·In od 16 A, 1,9·In nad 4 A pod 16 A, 2,1·In do 4 A včetně), i když In ≤ Iz |
| `sc_icu` | varování | Icu jističe < Ik v rozvaděči (atribut bloku `ik_ka` nebo parametr skříně `ik_ka`); kaskádu se záložním jištěním program nehodnotí |
| `sc_icw` | chyba | zkratová odolnost rozvaděče (parametr skříně `icw`) < Ik v rozvaděči |
| `sc_icu_icw` | varování | Icu jističe < Icw rozvaděče a Ik v rozvaděči není zadané |
| `sc_upstream` | info | jedna položka na list: Ik v místě připojení (`ik_ka` ve vlastnostech projektu) nebo na svorkách nn transformátoru (c_max · Sn / (√3 · 400 V · uk), c = 1,05) je nad Icu / Icw – horní odhad, ověřte Ik v rozvaděči |
| `spd_uc` | chyba | AC svodič: Uc < 1,1·Uo (síť TN, TT) / √3·Uo (IT) podle parametrů skříně „Síť“ a „Un“ |
| `spd_ucpv` | chyba / info | DC svodič: Ucpv (atribut `ucpv` > artikl `ucpv_v` > „Ucpv …“ z poznámky) < Uoc stringu – v cestě stringu se zadanou t_min hlásí `calc_string`; **info** bez návrhové teploty nebo když je známé jen Uc a je pod Uoc (ověřte Ucpv v datasheetu) |
| `spd_up` | varování | DC svodič: Up > výdržné napětí Uw střídače (atribut střídače `uw` v kV) |
| `spd_lps` | info | rozvaděč v objektu s jímací soustavou (parametr skříně „Jímací soustava“ = ano) a svodič bez typu 1 |
| `terminal_cross` | chyba | průřez vodiče / navázaného kabelu > max. průřez svorky nebo přístroje (`cross_max`) |
| `terminal_in` | varování | In svorky < In nejbližšího jištění |
| `un_ac` | chyba | Un přístroje < napětí sítě (3f přístroj sdružené, jinak fázové) |
| `un_dc` | chyba / info | Un přístroje DC < Uoc stringu při nejnižší teplotě (např. odpojovač 1000 V DC a string 20 × 49,5 V při −10 °C = 1083,6 V) – v cestě stringu se zadanou t_min hlásí `calc_string`; bez návrhové teploty info na list |
| `dc_path_unknown` | info | přívod stringu v listu DC rozvaděče chybí (jiné označení než port bloku) – napětí DC prvků listu se neurčuje, Un / Ucpv se nehodnotí |
| `dc_1500_missing` | info | stringy nad 1000 V DC a v katalogu chybí DC přístroje pro soustavu 1500 V (2p pojistkový odpojovač – jen když cesta stringu vede přes RFVE.DC, svodič DC) – generátor zůstal u 1000 V; nebo zadaná soustava 1500 V nepoužita |
| `calc_string` (Un DC) | chyba | Uoc stringu při zadané návrhové t_min > Un DC přístrojů v jeho cestě (pojistkový odpojovač, odpínač, svorka, svodič – Ucpv); hláška vyjmenuje všechny takové přístroje, stejně jako asistent průvodce, TZ a výkaz Výpočty |

**Soustava DC 1000 / 1500 V.** Asistent stringů v průvodci počítá největší počet modulů i z Un DC přístrojů, které
generátor do cesty stringu dá (pojistkový odpojovač v RFVE.DC, svodič DC; důvod „Un DC přístrojů 1000 V (EFH 10 DC
2p 1000 V)“), a „Navrhnout stringy“ tuto mez dodrží. Generátor vybere DC přístroje 1500 V (popis rozvaděče „max.
1500 V DC“), když je zadaná soustava 1500 V (`dc.system_v`, firemní standard `dc_system_v`), nebo automaticky, když
Uoc stringu přesáhne Un DC přístrojů, střídač připouští víc než 1000 V DC a katalog má 2pólový pojistkový odpojovač
(2× 1pólový se nepoužije) a svodič DC stejného typu na 1500 V (bez RFVE.DC stačí svodič). Soustavu nastavíte i ve
Firemním standardu (Soustava DC).

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

Kódy se píšou bez znaménka, jedna úroveň (`RS1`; tečka nedělí úrovně), jen A–Z, 0–9, `_` a tečka uvnitř (firemní `RFVE.AC`), nejvýš 10 znaků. Přejmenování
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

**Kroky průvodce.** Průvodce má vlevo seznam sedmi kroků a vpravo obsah vybraného kroku (v kroku je případný posuvník,
tlačítka dole zůstávají vidět; okno se vejde na 1366×768):
1. **Projekt** – název, investor, místo, číslo zakázky, zpracoval, distributor;
2. **Objekt a připojení** – druh objektu, nn / vn a trafostanice, topologie, náhled řetězce, fakturační měření, síťová ochrana, RFVE.DC na střídač;
3. **Moduly a střídače** – modul, optimizér a střídač (i **Z katalogu…**), režim stringů, návrhové teploty;
4. **Stringy** – celkem modulů, rozpis stringů, asistent stringů, **Navrhnout stringy**, skupiny střídačů;
5. **Kabely a rozvaděče** – DC kabely a rozvaděče po trase, RFVE.DC, AC kabely, jistič střídače, hlavní vypínač, rozvod sběrnicí / svorky, kabel do HDS;
6. **Stávající rozvaděče** – údaje do popisků bloků;
7. **Souhrn** – zadání, náhled řetězce, počty střídačů, stringů a modulů, DC/AC, výsledek asistenta stringů a kontrola
   `F7` projektu, který by vznikl (chyby červeně, varování oranžově; nález `F7` vytvoření nebrání).

Mezi kroky se přechází **libovolně** – klepnutím na krok v seznamu, nebo tlačítky **‹ Zpět** a **Další ›**; pořadí
vyplňování není vynucené. **Krok s chybou zadání** (např. text místo čísla, záporná β, pojistkový odpínač do 80 A) je
v seznamu **červený s vykřičníkem** a tooltip ukáže hlášku; **Souhrn** je při jakékoli chybě označen také a vypíše
chyby po krocích s odkazy, které na krok skočí. Tlačítko **Vytvořit** je zakázané, dokud je chyba zadání nebo chyba
generátoru (Souhrn průvodcem projekt předem sestaví a chybu ukáže červeně); po opravě se povolí samo.

**Modul a střídač z katalogu:** tlačítko **Z katalogu…** u modulu a střídače otevře výběr artiklu (tabulka s Voc, Isc,
Imp, β, Usys resp. P AC, MPPT, okno MPPT, I/MPPT…, filtr „Výkon od–do“ a u střídačů „Fáze“). Vybraný artikl vyplní
pole průvodce a uloží se k projektu (štítek „Artikl: …“); **ruční úprava pole má přednost** před artiklem, **×** vazbu
na artikl zruší (pole zůstanou). Šedě kurzívou jsou neúplné nebo neověřené řádky (zdroj `web`/`seed` nebo poznámka
„doplněno WebSearch“, chybí Voc/Isc resp. U DC max/okno MPPT) – důvod je v tooltipu; před použitím je zkontroluj
podle datasheetu. Filtry „Výkon“ a „Fáze“ neskrývají artikly, které údaj nemají – zobrazí se šedě s poznámkou. Nepovinná pole: Impp,
β Uoc, Isc max na MPPT, stringů na MPPT, návrhové teploty min/max (předvyplněné z firemního standardu, uloží se do
projektu pro kontrolu `F7`) a „Celkem modulů“.

**Baterie u hybridního střídače:** po výběru artiklu střídače s kategorií `inverter_hybrid` (**Z katalogu…**) se v kroku
„Moduly a střídače“ objeví skupina **Baterie (hybridní střídač)**; u jiného střídače (nebo bez artiklu) je skrytá a ve
specifikaci klíč `battery` chybí. Seznam **Baterie** nabízí artikly kategorie `battery` (stejný výrobce jako střídač jako
první, pak ostatní; slave moduly a řídicí jednotky samostatně nejsou v nabídce) a „bez baterie“ (výchozí). **Počet modulů**
věže je omezen podle datasheetu artiklu (např. SolaX T-BAT H 5.8 V3: 1–6, master se počítá). Je-li k věži řídicí jednotka
(BMS), ukáže se její výběr – jediná možná je předvolená, u více variant (SigenStack BC) se volí. Pod výběrem je souhrn:
celková kapacita (a výkon, jen když ho datasheet uvádí), složení věže a BMS. Baterie se kreslí u prvního střídače (T1),
u rodinného domu se k ní doplní EPS (přepínač sítí a zálohovaný vývod) a ve výkazu materiálu jsou master / modul × n,
přídavné moduly (slave) a řídicí jednotka. Kompatibilitu baterie s konkrétním střídačem průvodce nehlídá – ověřte ji
v datasheetu (poznámka artiklu). Do specifikace: `"battery": {"component_id": "solax-t-bat-h-5.8-v3", "modules": 3}`
(volitelně `bms_id`); `type`, `e_kwh`, `p_kw` z artiklu doplní generátor, zadané hodnoty mají přednost.

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
**VN** = trafostanice. AC rozvaděč FVE → **hlavní rozvaděč nn** HR (přívod XT od transformátoru, hlavní jistič,
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
Všechny části trafostanice (RVN, TR1, HR, RE, prvky na sloupu) mají atribut **Trafostanice** („TS1 kiosková
trafostanice“) a přístroje rozvaděče VN atribut **Pole / kobka** („P1 kabelové pole“) – oba jdou změnit v panelu
vlastností a určují rámečky v jednopólovém schématu. Ze Sn transformátoru se dopočte hlavní jistič (In nn → nejbližší
vyšší řada), převod MTP (x/5 A), pojistky VN (≈ 1,8 × In VN – ověř podle tabulky výrobce) a jistič spotřeby (≤ hlavní
/ 1,6 kvůli selektivitě); ve specifikaci je mění `connection.main_board.main_in`, `ct_ratio`, `fuse_vn`,
`main_board.load_in`, označení TS `connection.ts.ref`/`desc`. **Vývod FVE v HR** je nejbližší velikost ≥ max(**proud
FVE**, největší jistič střídače) – proud FVE = součet AC proudů střídačů (z artiklu `i_ac_max_a`, jinak z P AC a počtu
fází) –, nejvýš největší jistič selektivní s hlavním jističem (poměr 1,6); bez střídačů In hlavního vypínače RFVE.AC.
Rozhodnutí: vývod FVE ≥ jistič střídače, **ne 1,6 × jistič střídače** – selektivitu vůči jističům střídačů drží
hlavní vypínač RFVE.AC a 1,6× by u malých trafostanic vývod zbytečně vyhnalo nad selektivní mez s hlavním jističem HR.
Když takový jistič není (nebo je zadaný hlavní vypínač `ac.main_in` pod proudem FVE), In zůstane prázdné
a F7 hlásí chybu s důvodem; `connection.main_board.fve_in` platí vždy beze změny. **Napětí vn** (`u_vn`) se čte
z čísla na začátku textu („22 kV“, „35 kV, 50 Hz“, „22 000 V“, „22.000 V“); nečitelné nebo mimo 1–52 kV je chyba
zadání, nezadané se počítá jako 22 kV, ale do výkresu se nepíše. Rozvaděč VN nemá vícepól ani plán svorkovnice
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
≥ 1,5 × Isc modulu, nejvýš 2,4 × Isc, max. jištění modulu z katalogu a max. In držáku (`in_max_a` artiklu
`dc.fuse_component`, EFH 10 DC 25 A); SolarEdge (střídač nebo optimizéry) 25 A, pokud to držák snese. Když nic
nevyhoví (nebo modul nemá Isc), In zůstane prázdné a F7 hlásí chybu s důvodem. Artikl držáku In vložky nemění.
Artikly mění `dc.fuse_component` a `dc.spd_component` ve specifikaci. **Stringy se v rozvaděči nikdy nespojují** – každý jde
zvlášť až na vlastní DC vstup střídače (DC1…DCn podle počtu MPPT × stringů na MPPT; zná-li střídač počet MPPT
(zadáním nebo z artiklu), stringy se rozdělí na MPPT rovnoměrně – 1. string na MPPT 1, 2. na MPPT 2… –, jinak jdou
na DC1, DC2… za sebou; paralelní spojení dělá
jen SolarEdge a kreslí se jako jeden string). Blok DC rozvaděče v blokovém schématu má porty podle přívodů
(X1…Xn od stringů) a vývodů (Xn+1… dál). Když obojí vypneš, vloží se jen samostatný odpínač DC v blokovém schématu.
Průvodce se ptá i na **objekt** (`building` ve specifikaci): **firma** a **bytový dům** mají DC rozvaděče a AC
rozvaděč **RFVE.AC** zvlášť; u **rodinného domu** je DC i AC v jednom **rozvaděči FVE (RFVE)** – místo DC rozvaděče u technologie
má RFVE na každý string pojistkový odpojovač a SPD DC (přívody za AC přívody od střídačů, vývody ke střídači) a k tomu
AC část s vývodem do HDS. V blokovém schématu stojí RFVE před střídačem, AC kabel od střídače se vrací shora;
rozvaděče po trase zůstávají. Přípojka VN se u rodinného domu negeneruje.
**Označení rozvaděčů** z generátoru (firemní styl ENVO, bere se z presetu topologie): AC rozvaděč FVE **RFVE.AC**, DC
rozvaděč u technologie **RFVE.DC** – jeden **společný** pro všechny střídače (přívody X1…Xn všech stringů, pojistky
FU{střídač}.{string}); s volbou `"chain": {"rfve_dc": {"per_inverter": true}}` má každý střídač svůj (**RFVE.DC1**,
**RFVE.DC2**… v pořadí střídačů, jako před F2). Rozvaděče po trase **RDC1…n** (číslované souvisle jen mezi sebou),
hlavní rozvaděč **HR**, domovní rozvaděč **RD**, elektroměrový rozvaděč **RE**, hlavní domovní skříň **HDS**, u
rodinného domu jeden **RFVE**. Tečka je uvnitř jednoho kódu umístění (`+RFVE.AC-X1`), nedělí úrovně. Jiné označení
lze zadat ve specifikaci: `"chain": {"<role>": {"ref": "…"}}` (role `rfve_dc`, `rfve_ac`, `rfve`, `rd`, `hr`, `re`,
`hds`, `rvn`), dřívější `switchboard.ref` a `connection.main_board.ref` / `meter_board.ref` platí dál jako přepis.
Starší projekty se nepřejmenovávají.
AC rozvaděč má přívody po střídačích, jističe, rozvodné svorky s můstky, SPD, hlavní vypínač a vývod do HDS; přívody
i vývody jsou ve spodní řadě (vše zespodu), přívodní větev teče nahoru do sběrnice / rozvodných svorek.
Označení jsou jedinečná uvnitř každého rozvaděče (jako v EPLAN `+RDC1-X1`), takže X1 smí být v každém
rozvaděči; listy blokového schématu sdílejí jeden prostor označení.

Jištění ve specifikaci i v průvodci se zadává **číslem v ampérech**: `dc.fuse_in`, `dc.disconnect_in`,
`ac.breaker_in` (např. `40`, ne „C40“ ani „B40“ – charakteristiku nese prvek jističe) a `ac.main_in`; „40,0“
i `40.0` se berou jako 40. Typ svodiče `dc.spd` / `ac.spd` je text (T1, T2, T1+T2, i T1+T2+T3).

Totéž umí příkaz `python -m envocad.generate spec.json vystup.ecp` – specifikace je JSON popsaný
v `envocad/generate.py`. To je cesta pro AI agenty: z poptávky a datasheetů připraví specifikaci, program
vygeneruje projekt, ty ho upravíš.

**Topologie připojení**: generátor vybere preset řetězce (rodinný dům → `rd`, připojení na vn → `vn`, jinak `nn`;
`nn_hr_meter` s měřením v HR jen volbou `"topology": "nn_hr_meter"` ve specifikaci). Do vlastností projektu zapíše
`topology` (id presetu) a `topology_chain` (náhled řetězce, např. „stringy → RFVE.DC → T → RFVE.AC → HR → RE → HDS →
DS“).

**Co generátor kreslí (rozsah):** hlavně **blokové schéma** (celý řetězec od stringů po DS) a **DC rozvaděče**
(RFVE.DC, RDCn, DC část RFVE). **AC rozvaděče připraví projektant z mustrů** (firemní makra):

- **RFVE.AC** má list jen tehdy, když v knihovně je **mustr** – makra rolí `ac_feed` (přívod střídače) a `ac_core`
  (jádro) ve **sdílené nebo vlastní** knihovně (vestavěná makra se nepočítají; název lze vybrat i ve specifikaci
  `"macros": {"ac_feed": "…", "ac_core": "…"}`, jinak se vezme makro s danou rolí). Jinak je RFVE.AC **blok bez
  listu**: porty X1…Xn (přívody od střídačů), XOUT, XPE a v popisku hlavní vypínač, jištění střídačů a požadavek
  síťové ochrany.
- **RFVE (rodinný dům)** má list vždy s **DC částí**; AC část (přívody, jádro, EPS – makro `ac_eps`) jen z mustru,
  jinak jen **kotvy** přívodů a vývodů (X1…, XOUT, XPE, XE1/XB1) bez přístrojů – blok má porty, vazby fungují a AC
  část doplní projektant nebo mustr (kontrola: INFO „kotva“).
- **Stávající RD / HR / RE a HDS** jsou jen **bloky v blokovém schématu** bez listů. Údaje z `chain.*` se propíší do
  popisku bloku: hlavní přístroj s In (`main_in`), vývod FVE (`fve_device`, `fve_in`), měření (přímé / nepřímé s MTP);
  hranice vlastnictví zůstává textem v blokovém schématu. Neznámé In stávajících přístrojů není chyba (HDS bez In jen
  INFO). Porty bloku bez listu jsou v jeho atributech (`ports_in`, `ports_out`, formát projektu 15).
- Na přípojce VN (`vn`) jsou i **HR, RVN a RE trafostanice jen bloky** (porty z přívodů / vývodů vestavěného listu,
  v popisku hlavní jistič, vývod FVE, měření, pojistky / vypínač VN); listy TS s volbou `builtin` (role `hr`, `rvn`,
  `re`) nebo standardem `ac_builtin`. RFVE.AC bez mustru je blok.
- **Vestavěný kód AC listů** (jako před tímto rozhodnutím – RFVE.AC, AC část RFVE včetně EPS, listy RD / HR / RE)
  zapne volba `"chain": {"<role>": {"builtin": true}}` (role `rfve_ac`, `rfve`, `rd`, `hr`, `re`, na vn i `rvn`) nebo firemní
  standard **`ac_builtin`** (Knihovna → Firemní standard; `settings.json`). Pak platí i vestavěná makra
  (`spec.macros`, prázdný název = kód). Volba článku má přednost před standardem.

Údaje stávajících článků (`"chain": {…}`, ve vestavěném kódu i v popisku bloku):

- **RD / HR**: přívod XIN → hlavní přístroj (RD vypínač, HR jistič; In `main_in`) → **vývod FVE X1** (jistič, nebo
  pojistkový odpínač – volba `fve_device`; **do 80 A vždy jistič**, pojistka do 80 A = chyba zadání) a vývod
  „stávající rozvody objektu“ X2 (v blokovém schématu značka Spotřeba). In vývodu FVE bez zadání = nejbližší velikost
  ≥ max(součet proudů střídačů, největší jistič střídače) – stejně jako vývod FVE v HR na vn.
- **RE**: hlavní jistič před elektroměrem → elektroměr přímý (v sérii) nebo nepřímý (MTP, převod z In nebo `ct_ratio`)
  → vypínač instalace. U topologie `nn_hr_meter` je stejné měření v HR (bez RE).
- **HDS**: blok s pojistkami (`in_`, charakteristika gG), vodič HDS → DS bez kabelu.
- **Hranice vlastnictví** DS / odběratel (`boundary`): `hds` (výchozí), `re_main` (svorky hlavního jističe), `re_meter`
  (za elektroměrem) – text „hranice vlastnictví DS / odběratel“ v blokovém schématu (ve vestavěném listu i atribut
  `boundary` na přístroji).
- **Kabely mezi články**: kabel článku směrem k síti `chain.<role>.cable / cross / length / method`. RFVE.AC → HR / RD:
  zadané `ac.grid_*` (jen když je zadáš – výchozí hodnota se nebere), jinak nejmenší průřez pro In vývodu FVE (tabulka
  Iz, uložení D, typ v řadě AC kabelu střídačů – „CYKY-J 5x10“); nad 240 mm² zůstane průřez prázdný (paralelní kabely
  zvolí projektant). Stávající úsek bez údajů je vodič bez označení a kabelu. Kontrola kabelů porovná In jištění
  vývodu s Iz kabelu i přes vazbu přívodu – u bloku bez listu podle atributu `protect` („X1=63“, vývod FVE v HR / RD,
  jištění střídačů u RFVE.AC).

**Jištění střídačů a hlavní vypínač:** nezadaný jistič přívodu střídače = nejbližší velikost řady (10…125, 160, 200,
250 A) ≥ 1,25 × max. AC proud střídače (z artiklu `i_ac_max_a`, jinak z P AC); nad řadou zůstane In prázdné a F7 hlásí
chybu s důvodem. **Jednofázový střídač** má jistič vždy podle proudu (1,25 × P / 230 V, řada do 63 A) – i když je
zadané `ac.breaker_in` (to platí pro třífázové). Nezadaný hlavní vypínač AC rozvaděče je nejméně 125 A a nejméně
vývod FVE, počítá se z prvků střídačů (i z artiklu bez `p_ac` ve specifikaci).

Stávající články se skládají **svisle** („had“, každý další pod předchozím): u firmy pod RFVE.AC (vývod XOUT vede
krátce vpravo za uzemnění a dolů do HR; DS pod HDS), u rodinného domu ve sloupci vpravo od FV části (vývod RFVE pod
střídači a nahoru do RD; DS vedle nebo pod HDS) nebo v řadě pod vším doleva (RD pod RFVE, RE, HDS a DS pod stringy). Generátor zkusí i řadu pod FV částí / za RFVE.AC a nechá rozložení s nejmenším
výkresem bez křížení a překryvů textů (i bez cizího vodiče přes značku řetězce). Společný RFVE.DC sdílí svislé dráhy
vodičů shora a zdola; kdyby list „AC a připojení“ s ním přerostl limit listu, vezme se RFVE.DC na střídač (jen když
`chain.rfve_dc.per_inverter` nezadáš).

**Kontrola řetězce (F7)** – běží jen nad přístroji, které v projektu jsou (blok bez listu nic nehlásí): selektivita
přes listy (vývod FVE v RD / HR < hlavní jistič před elektroměrem < pojistky HDS, jistič střídače ≤ vývod FVE,
odpínač i přepínač sítí nesmí mít In pod jištěním, které ho chrání) – `chain_selectivity`; pojistkový vývod FVE do
80 A (`fve_out_fuse_le80`); chybějící síťová ochrana nad hranicí (`grid_protection_missing` – požadavek v atributu
bloku RFVE.AC / RFVE bez AC části stačí); vazební prvek síťové ochrany bez vypínací spouště (`grid_protection_trip`,
atribut `trip` hlavního vypínače) a nejištěný měřicí vstup U (`grid_protection_u`); EPS vývod, který nevede na
přepínač sítí (`eps_unconnected` – varování jen u střídače, kde ho generátor čeká, `eps="1"`; v ručním projektu INFO;
vede-li do RFVE bez AC části, INFO `eps_open`); HDS bez In (INFO `hds_no_in`); rozvaděč jen jako blok (INFO
`block_only`). Zadané hodnoty generátor nepřepisuje – nevyhovující nahlásí.

**Síťová ochrana** nad 30 kWp instalovaného výkonu DC (hranice ve firemním standardu `grid_protection_kwp`): relé
U<> f<> v RFVE.AC (u rodinného domu v RFVE) měří přes **jistič měřicího vstupu** z přípojnice za hlavním vypínačem
a působí na hlavní (vazební) vypínač s **vypínací spouští**; přepis `"chain": {"rfve_ac": {"grid_protection": "1" |
"0" | "auto"}}` (u RD `rfve`). Bez AC listu je ochrana požadavkem v popisku bloku.

**EPS a přepínač sítí** jen u rodinného domu, u střídače s připojenou baterií: EPS vývod (BACKUP) vede přes pár
přerušení „EPS-T1“ na přívod XE1 RFVE → přepínač sítí I-0-II (síť z přípojnice **přes jistič**) → vývod XB1
„zálohované okruhy“. U firmy a bytového domu se nekreslí.

**Střídače na jiném místě**: `"inverters": [{…, "ac_group": "hala B"}]` – skupina má vlastní RFVE.AC2 (hlavní
RFVE.AC1) a vlastní vývod FVE v HR (X3…; kabel přes pár přerušení „AC2-HR“). Jen nn s HR (firma, bytový dům). Volby se
zadávají ve specifikaci, např. `"chain": {"hr": {"main_in": 250}, "re": {"main_in": 250, "metering": "indirect",
"boundary": "re_main"}, "hds": {"in_": 315}}` (přehled v `docs/LIBRARY_FORMAT.md`, „Volby článků“). Totéž nabízí průvodce
(viz níže).

**Průvodce – topologie připojení.** Krok **Objekt a připojení**: druh objektu, nn / vn (u rodinného domu je vn
zakázané – RD se připojuje do HDS), **Topologie** (Automaticky, nebo preset filtrovaný podle druhu objektu a úrovně,
včetně sdílených a vlastních), živý náhled řetězce („stringy → RFVE.DC → T → RFVE.AC → HR → RE → HDS → DS“),
fakturační měření v RE / v HR, samostatný RFVE.DC na střídač (jen při 2 a více střídačích) a síťová ochrana
(automaticky / ano / ne; průvodce ukáže instalované kWp proti hranici 30 kWp). Krok **Stávající rozvaděče**: hlavní
přístroj a In RD / HR, vývod FVE (jistič, nebo pojistkový odpínač – do 80 A včetně je nedostupný, vždy jistič) a jeho In,
HJ v RE, měření přímé / nepřímé s převodem MTP, hranice vlastnictví, In a charakteristika HDS. Údaje se propíšou do
popisku bloků; **prázdné pole = neuvedeno** (nic se nepíše, žádná chyba). U vn se tyto údaje zadávají v poli Připojení
k DS. Skupina **Skupiny střídačů** (v kroku Stringy): u každého střídače volitelné umístění (jen nn, firma a bytový dům). Do specifikace
se `topology` a `chain.*` zapíšou jen při změně od výchozího. Chybu, kterou ohlásí až generátor, průvodce ukáže hned.
Jednofázový střídač (`phases` 1) má AC kabel třížilový (L N PE) s průřezem podle proudu. Vlastní nebo firemní presety
(`~/.envocad/topologies/`, sdílená knihovna `topologies/`) s neznámou rolí se nenačtou (záznam v logu) a platí
vestavěný preset; preset pro rodinný dům musí mít rozvaděč FVE `rfve`, preset na vn aspoň jeden článek přípojky VN.

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
| Technická zpráva (docx) ze šablony – údaje, tabulky a výpočty z modelu | Výstupy → Technická zpráva |
| Dokumentace skutečného provedení – DSPS (docx): jádro TZ + změny proti projektu dle PD | Výstupy → DSPS |
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

### Technická zpráva a DSPS ze šablony
**Výstupy → Technická zpráva (docx)…** a **Výstupy → Dokumentace skutečného provedení – DSPS (docx)…** otevřou
dialog s výběrem **šablony** (vestavěná, sdílená, vlastní nebo *Jiný soubor šablony…*), pak se zeptají na soubor.
Zpráva obsahuje jen údaje, které projekt má: identifikaci stavby, základní údaje FVE (kWp DC, kW AC, moduly,
střídače, optimizéry, baterie), řetězec rozvaděčů, DC část (stringy, Uoc / Umpp při návrhových teplotách, jištění
stringů, svodiče, kabely), AC část (jištění, kabely, selektivita), připojení k DS (nn / vn, měření, hranice
vlastnictví, HDS, transformátor), ochranu před úrazem a přepětím, síťovou ochranu (nad hranicí kWp), uzemnění,
výpočty (kabely, úbytky, Ik''), rozvaděče s oteplením, seznam výkresů, revize a v příloze výkaz materiálu a kabely.
**Chybějící údaj se vypíše jako „neuvedeno“** (nebo se celá sekce vynechá) – nic se nedomýšlí; doplň ho
v projektu (Vlastnosti projektu, atributy prvků, hlavička rozvaděče) a zprávu vygeneruj znovu.

**DSPS** má stejné jádro a navíc kapitoly *Údaje o provedení* (datum provedení, zhotovitel, výchozí revize – číslo
revizní zprávy; zadávají se v dialogu a uloží do vlastností projektu, krok jde vrátit Zpět) a *Změny proti projektové
dokumentaci*: v dialogu vyber **Porovnat s** = uložený projekt dle PD (.ecp) – tabulka změn je stejná jako
u Porovnat s revizí (posuny ve výkresu se nevypisují); bez souboru se uvede jen změnový list projektu.

**Firemní šablona:** v dialogu *Uložit šablonu jako .docx…* uloží vestavěnou šablonu jako dokument Word s poli.
Ve Wordu uprav styly, záhlaví, logo a texty a ulož ji do složky `doc_templates` uživatelské (`~/.envocad/doc_templates/`)
nebo sdílené knihovny; název začni `tz` nebo `dsps` (soubor `tz.docx` / `dsps.docx` nahradí vestavěnou šablonu
jako výchozí). Pravidla šablony:

| Zápis | Význam |
|---|---|
| `{{fve.p_dc_kwp}}` | pole z projektu; chybí-li → „neuvedeno“ (jednotka hned za polem se pak vynechá) |
| `{{projekt.zakazka|–}}` | vlastní náhrada chybějícího údaje (`{{x|}}` = nic) |
| `{{meta.muj_klic}}`, `{{pole.klic}}` | libovolné metadato projektu / hodnota z dialogu exportu |
| `{% if ds.uroven == "vn" %}` … `{% else %}` … `{% endif %}` | sekce jen když platí (také `if x`, `if not x`, `!=`) |
| `{% for s in stridace %}` … `{{s.oznaceni}}` … `{% endfor %}` | opakování odstavců a tabulek |
| `{{tabulka.stringy}}`, `{{blok.rozvadece}}` | odstavec nahradí tabulka / kapitola z modelu |
| `{{§}}` v nadpisu | číslo kapitoly (1, 1.1 …) – vynechaná sekce mezeru nenechá |

Řídicí značky `{% … %}` a bloky musí být **samostatný odstavec**. Úplný seznam polí a bloků je v
`docs/design/tz_dsps.md`. Dokument Word bez polí se použije jako podklad (styly, záhlaví) a doplní se vestavěnou
osnovou. Chybná značka export nezastaví – v dokumentu zůstane text „[chyba šablony: …]“.

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
  k vestavěné a stejná id přebíjí. Podsložka `doc_templates` = firemní šablony technické zprávy a DSPS (sekce 8).
- **Firemní standard…** – výchozí kabely, zpracoval, název firmy, formát stran schématu rozvaděče a plánu
  svorkovnice (výchozí A4 na šířku), největší list JPS z průvodce (`jps_max_paper`, výchozí A2) a výchozí volba
  listů JPS v PDF dokumentace (`doc_jps_page`, výchozí „Zmenšit na A3“) (`~/.envocad/settings.json`).
- Pluginy: `~/.envocad/plugins/*.py` s funkcí `register(ctx)` přidají menu, šablony, importéry, výkazy nebo
  příkazy příkazového řádku (`ctx.add_command`, viz `envocad/plugins.py`).

Data artiklů jsou opsaná z veřejných katalogů (zdroj a strana je u každého řádku) – před použitím
v projektu je ověř u výrobce.

---

## 11. Klávesové zkratky

| Zkratka | Akce |
|---|---|
| `Ctrl+N` / `Ctrl+Shift+N` | nový projekt / z průvodce |
| `Ctrl+O`, `Ctrl+S`, `Ctrl+Shift+S` | otevřít, uložit, uložit jako |
| `W` `Enter` (`L`) | kreslit vodič – v režimu kláves „envocad“ jen `W` |
| `Esc` | zpět do výběru (a zrušit rozpracovaný příkaz řádku) |
| `RO` `Enter` | otočit o 90° – v režimu „envocad“ `R`; při vkládání značky `R` otočí náhled vždy |
| `MI` `Enter` | zrcadlit – v režimu „envocad“ `M`; při vkládání `M` zrcadlí náhled vždy |
| `TEXT` `Enter` | text – v režimu „envocad“ `T` |
| `Delete` | smazat |
| `Ctrl+Z` / `Ctrl+Y` | zpět / znovu |
| `Ctrl+C` / `Ctrl+V` | kopírovat / vložit kopii |
| `Ctrl+Alt+M` | uložit výběr jako makro |
| `Ctrl+F` | najít označení |
| `F7` | kontrola projektu (panel Kontrola) |
| `Ctrl+K` | hledat příkaz |
| `F11` | jen výkres (skrýt panely) |
| `Ctrl++` / `Ctrl+-` | přiblížit / oddálit |
| `straighten` `Enter` | narovnat vybrané vodiče – v režimu „envocad“ `N` |
| `F2` | delší výstup příkazového řádku |
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

## 12. Příkazový řádek a skripty

Každou úpravu výkresu jde zapsat jako příkaz ve stylu ZWCAD/AutoCAD (`MOVE`, `RO`, `E`…) – v okně programu
(dok „Příkazový řádek“ dole) i ve **skriptu `.ecs`** přes příkazovou řádku systému (hromadné úpravy, agenti).
Příkazy, aliasy i chování jsou v obou stejné.

### Příkazový řádek v okně

| Klávesa | Co udělá |
|---|---|
| psaní ve výkresu | jde rovnou do řádku (režim kláves „zwcad“, výchozí) – `M` `Enter` = posunout, `RO` = otočit, `L` / `W` = vodič |
| Enter / mezera | potvrdí příkaz nebo hodnotu výzvy (mezera ne uvnitř uvozovek a v textové výzvě) |
| Enter na prázdném řádku | zopakuje poslední příkaz |
| Esc | zruší rozpracovaný příkaz – model zůstane, jak byl (i ve výkresu, i pravým tlačítkem) |
| ↑ / ↓ | historie, když není otevřený seznam příkazů (posledních 200, i po restartu – `~/.envocad/cmd_history.txt`) |
| psaní příkazu | nad řádkem se ukážou odpovídající příkazy (jako ZWCAD): alias, jméno a česky co dělá; od 3 znaků hledá i uvnitř jmen a v českých názvech (`otoč` → ROTATE). ↑ / ↓ vybírá, Tab doplní, Enter nebo klik spustí, Esc seznam zavře; nedopsané slovo (`rotat`) Enter spustí podle prvního návrhu |
| Tab | doplní příkaz, alias, id značky u `INSERT`, klíč atributu u `SET`, název listu u `SHEET` |
| F2 | delší výstup (historie hlášek) |

- Chybějící argumenty se doptají výzvou vlevo od řádku („Základní bod:“). **Bod** jde napsat (`120,150`, `@10,0`,
  `F1:2`) nebo **kliknout do výkresu** – od základního bodu se kreslí gumová čára. Výzvu **výběru** splní aktuální
  výběr; když nic vybrané není, vyberte myší a potvrďte Enter.
- Každý příkaz je jeden krok **Ctrl+Z**. `UNDO` / `REDO` z řádku jdou přes stejnou historii jako Ctrl+Z.
- Bez argumentů spustí `L` / `W` (vodič) a `I` (vložit značku) dnešní kreslení myší, `F7` panel Kontrola.
- Každá položka menu s vlastním id je i příkaz (napište ji nebo najděte Tabem); hledání příkazů Ctrl+K ukazuje
  u položky i jméno příkazu a aliasy („Otočit o 90° · ROTATE, RO“).
- `SAVE` v okně = Soubor → Uložit (bez cesty).
- Režim kláves: v `~/.envocad/settings.json` `"cmdline_keys": "envocad"` vrátí jednoklávesové zkratky ve výkresu
  (R otočit, M zrcadlit, W vodič, N narovnat, T text); psaní pak do řádku nejde, řádek zůstává v doku.

### Spuštění skriptu (CLI)

```
python -m envocad.cmd projekt.ecp skript.ecs                 # jen vypíše, co by se stalo – nic neuloží
python -m envocad.cmd projekt.ecp skript.ecs -o novy.ecp     # výsledek do nového souboru
python -m envocad.cmd projekt.ecp skript.ecs --in-place      # zpět do projektu (záloha projekt.ecp.bak)
python -m envocad.cmd projekt.ecp - < skript.ecs             # skript ze vstupu
```

| Volba | Význam |
|---|---|
| `-o soubor` / `--in-place` | uložit výsledek; **bez nich se nic neukládá** (bezpečný výchozí stav) |
| `--force` | s `-o` přepsat existující soubor (jinak chyba) |
| `--dry-run` | vykonat a vypsat, neuložit ani s `-o` |
| `--keep-going` | po chybném řádku pokračovat (a uložit); jinak konec při první chybě bez uložení |
| `--json` | na každý příkaz řádek JSON `{"line", "cmd", "ok", "messages", "changed_sheets"}` (u `CHECKS` navíc `data` s nálezy), nakonec `{"summary": …}` |
| `--var jmeno=hodnota` | dosadí `${jmeno}` ve skriptu (jen text, dosazuje se před rozdělením řádku – mezera nebo uvozovka v hodnotě přidá argument) |
| `--no-user-aliases` | bez uživatelských aliasů `~/.envocad/aliases.json` – skript se chová stejně na každém stroji (doporučeno pro agenty) |
| `--plugins` | načíst pluginy `~/.envocad/plugins` a jejich příkazy (plugin je kód s právy uživatele – bez volby se nenačtou) |

Kód návratu: 0 = vše proběhlo, 1 = chyba příkazu (hláška s číslem řádku, např. `řádek 7: MOVE – chybí Cílový bod`),
2 = chybné použití (argumenty, projekt nebo skript nejde načíst). Před uložením se dopočtou kabely a vazby přívodů
(jako v GUI) a výstup dostane souhrn kontroly F7. Vstup i výstup je vždy UTF-8, i v rouře na Windows.

Bezpečnost skriptů (skript může napsat agent nebo přijít s cizím projektem): žádný kód se nespouští, `SAVE` ve skriptu
zapíše jen do cíle `-o` / `--in-place` a teprve po úspěšném konci, `SCRIPT` načte jen `.ecs` ze složky hlavního
skriptu (ne síťové cesty), celý běh i s vnořenými skripty má nejvýš 10 000 příkazů a skript nejvýš 1 MB.

### Skript `.ecs`

Text v UTF-8, jeden příkaz na řádek, `#` na začátku řádku = komentář, prázdné řádky se přeskočí. Hodnoty s mezerou
do uvozovek. Každý řádek je jeden krok (`UNDO` ho vrátí); chyba uprostřed příkazu nenechá v projektu nic napůl.

```
# jistič za střídač a propojení
SHEET 1
INSERT fve.breaker_mcb 200,150 ref=F5 in_=32
WIRE T1:AC F5:1
SET F5 desc="Vývod FVE"
SELECT Q*
MOVE 0,0 @0,-10
CHECKS
```

**Souřadnice** jsou v mm na listu, počátek v levém dolním rohu listu, Y nahoru (stejně jako ve stavovém řádku).
`x,y` absolutně s desetinnou **tečkou** (`12.5,40`; čárka odděluje souřadnice), `@dx,dy` relativně k poslednímu bodu,
`F1:2` = poloha portu 2 prvku F1. Prvky a posuny se zaokrouhlí na mřížku 2,5 mm (výstup to oznámí).

**Výběr.** Příkazy, které pracují s výběrem, berou označení hned za příkazem (`RO F1 F2`, `E Q*`) – jinak platí
poslední výběr (`SELECT`). `SELECT F1 F2 Q*` (označení prvků i vodičů, `*` / `?` jako maska), `SELECT all`,
`SELECT none`, `SELECT W x1,y1 x2,y2` (okno – prvky celé uvnitř a vodiče mezi nimi), filtr `klíč=maska`
(`SELECT symbol=fve.breaker* in_=16*`, s označením se kombinuje: `SELECT F* in_=80*`).

| Příkaz | Aliasy | Zápis |
|---|---|---|
| `INSERT` | I, VLOZIT | `INSERT id_značky x,y [ref=F1 rot=90 mirror=ano klíč=hodnota …]` – nové označení podle značky, nebo zadané; přívod/vývod listu rozvaděče `wire_id=W1` (id nebo označení vodiče JPS) doplní kam/odkud a kabel jako dialog |
| `WIRE` | W, L, VODIC | `WIRE F1:2 Q1:1 [ref=W5 cross=10 …]`; místo `ref:port` jde bod (port do 2,5 mm), body mezi začátkem a portem = ruční lomy: `WIRE F1:2 190,150 190,100 Q1:1` |
| `MOVE` | M, POSUN | `MOVE [výběr] základní_bod cílový_bod` (`MOVE F1 0,0 @10,0`); ruční lomy vodičů jdou s prvky |
| `COPY` | CO, CP, KOPIE | `COPY [výběr] základní cílový` – kopie dostanou nová označení, výběr = kopie |
| `ROTATE` | RO, OTOCIT | `ROTATE [výběr] [základní_bod] [úhel]` – násobek 90°, výchozí 90; se základním bodem (`RO F1 F2 120,150 90`, `RO T1 T1:AC`) se kolem něj otočí i polohy a ruční lomy mezi otáčenými prvky, bez bodu (`RO F1 180`) každý prvek kolem svého počátku jako klávesa R |
| `MIRROR` | MI, ZRCADLIT | `MIRROR [výběr]` |
| `DELETE` | E, ERASE, DEL, SMAZAT | `DELETE [výběr]` – i vodiče mazaných prvků |
| `SET` | ATTR, ATR, ATE, NASTAVIT | `SET [výběr] klíč=hodnota …` – klíče podle značky (Vlastnosti), u vodiče `cable`, `cross`, `length`…; `SET T1 ref=T7` přejmenuje i navázané texty („od T1“), port vodiče u přívodu a umístění bloku rozvaděče jako v GUI. Označení se kontroluje jako F7: chyba zápisu příkaz odmítne, nesoulad s třídou značky (`F1 ref=K5`) jen vypíše upozornění |
| `SELECT` | VYBER | viz výše |
| `SHEET` | LIST | `SHEET 2` nebo `SHEET "RFVE.AC"` (aktivní list; bez argumentu vypíše listy) |
| `UNDO` / `REDO` | U, ZPET / ZNOVU | `UNDO [počet]` |
| `CHECKS` | F7, KONTROLA | vypíše nálezy kontroly projektu |
| `SAVE` | ULOZ, QSAVE | `SAVE [soubor.ecp]` – v CLI jen potvrdí cíl `-o` / `--in-place` (uloží se po úspěšném konci skriptu), jiná cesta je chyba |
| `SCRIPT` | SCR, SKRIPT | `SCRIPT jiny.ecs` – vnoření nejvýš 4×, cesta relativně ke skriptu a jen pod složkou hlavního skriptu; celý vnořený skript je jeden krok (chyba v něm nezmění nic). V okně Soubor → Spustit skript… (jeden krok Ctrl+Z) |
| `EXPORT_DXF` | DXFOUT, EXPORTDXF | `EXPORT_DXF soubor.dxf` – aktivní list (list rozvaděče jako vícepól po stranách); bez cesty v okně dialog |
| `EXPORT_PDF` | PDF, EXPORTPDF | `EXPORT_PDF soubor.pdf [A4 \| A3]` – aktivní list (skutečný formát, nebo zmenšit/zvětšit na A4/A3) |
| `DOC_PDF` | DOKUMENTACE | `DOC_PDF soubor.pdf [A3 \| list]` – celá dokumentace; listy JPS zmenšit na A3 / skutečný formát (výchozí podle firemního standardu) |

Exporty ze skriptu (CLI i Soubor → Spustit skript…) jdou jen do složky hlavního skriptu (a podsložek), existující
soubor přepíšou jen tehdy, když ho vytvořil tentýž běh (v CLI jinak `--force`), nejvýš 50 exportů za běh;
`--dry-run` nic nezapíše. Export model nemění a chyba později ve skriptu už zapsané soubory nesmaže. Řádek napsaný
ručně v doku tato omezení nemá.
| `HELP` | ?, NAPOVEDA | `HELP [příkaz]` – seznam příkazů a aliasů / syntaxe |
| `ZOOM`, `FIT` | Z, ZE, ZA | jen v GUI |

Velikost písmen a diakritika se u příkazů neřeší (`otočit` = `OTOCIT` = `RO`). Vlastní aliasy (obdoba `acad.pgp`):
`~/.envocad/aliases.json` ve tvaru `{"aliases": {"PR": "move"}}` – přepíší výchozí aliasy, kanonická jména ne.

Skript nespouští žádný kód: zná jen registrované příkazy a hodnoty jsou text nebo čísla. Neznámé slovo je chyba
„Neznámý příkaz“.

---

## 13. Když se něco pokazí

- Program ukládá rozpracovaný projekt každé 2 minuty do `~/.envocad/autosave/`; po spuštění nabídne obnovu.
- Log každého běhu: `~/.envocad/log/envocad.log` (Nápověda → Otevřít složku s logy); neošetřená chyba se
  zobrazí v dialogu a program většinou běží dál – ulož práci.
- Starší projekty (`.ecp`) se při otevření převedou na aktuální formát automaticky.
- `python` na Windows spouští Store? Použij `py -m envocad`.
- Linux Wayland potíže: `QT_QPA_PLATFORM=xcb scripts/run.sh`.

Soubor projektu je čitelný JSON (`.ecp`) – hodí se do gitu, porovnání revizí s ním počítá.
