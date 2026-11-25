# Formát knihovny symbolů

Každý symbol je jeden JSON soubor. Vestavěné symboly jsou v `envocad/library/builtin/<obor>/*.json`
a při startu se nahrají do SQLite (`~/.envocad/library.db`), kde přibývají i uživatelské/importované.

```json
{
  "format_version": 1,                // volitelné; chybí = 1 (viz „Verze formátu“)
  "id": "fve.inverter.3ph",
  "name": "Střídač 3f",
  "category": "Střídače a měniče",   // druh prvku = nadpis v panelu; "Druh/QET" = podsložka cizích značek
  "description": "Síťový střídač DC/AC, třífázový",
  "iec_ref": "T",                     // písmeno označení dle ČSN EN IEC 81346 → T1, T2…
  "function_class": ["T"],            // volitelné – povolené třídy označení (viz níže); bez klíče = [iec_ref]
  "primitives": [
    {"type": "rect",    "x": -10, "y": -10, "w": 20, "h": 20},
    {"type": "line",    "x1": -10, "y1": 10, "x2": 10, "y2": -10},
    {"type": "circle",  "cx": 0, "cy": 0, "r": 2.5},
    {"type": "arc",     "cx": 0, "cy": 0, "r": 5, "start": 0, "end": 180},
    {"type": "polyline","points": [[0,0],[5,5],[10,0]], "closed": false},
    {"type": "text",    "x": 0, "y": 12, "text": "DC", "height": 2.5, "align": "center"}
  ],
  "ports": [
    {"name": "DC1", "x": -10, "y": 5,  "dir": "W"},   // v JPS je čára vždy jednopólová; pár L+/L- jsou žíly vodiče (ČSN EN 60445)
    {"name": "DC2", "x": -10, "y": -5, "dir": "W"},
    {"name": "AC",  "x": 10,  "y": 0,  "dir": "E"}
  ],
  "attributes": [
    {"key": "ref",   "label": "Označení",  "default": "", "show": true},
    {"key": "type",  "label": "Typ",       "default": "", "show": true},
    {"key": "p_ac",  "label": "P_AC [kW]", "default": "", "show": false},
    {"key": "n_modules", "label": "Počet modulů", "show": true, "fmt": "{}× modul"},  // fmt = formát zobrazené hodnoty
    {"key": "dir", "label": "Směr", "default": "in", "choices": [["in", "přívod"], ["out", "vývod"]]}  // nabídka
  ],
  "label_pos": {"x": 12, "y": 8},
  "multipole": {                      // volitelné – podoba ve vícepólovém schématu (průchozí prvky)
    "pole": [ ...primitiva jednoho pólu... ],   // kreslí se pro každou spínanou žílu (rozteč 7,5 mm)
    "common": [ ...kreslí se jednou u 1. pólu... ],  // spoušť, cívka, sumační transformátor…
    "link": true,                     // čárkovaná mechanická vazba pólů
    "link_at": [0, 2],                // bod pólu, kterým vazba prochází
    "through": ["1", "2"],            // nepovinné: průchozí porty u značky s dalšími porty (MTP: primár 1–2, sekundár S)
    "pitch": 12.5,                    // nepovinné: rozteč pólů ve vícepólu [mm], výchozí 7,5 (přepínač sítí: vstupy I / II)
    "stagger": 12.5,                  // nepovinné: posun pólů po toku [mm] – jen se sekundárem po fázích (níže)
    "secondary": {                    // nepovinné: sekundár po fázích (MTP) – žíla na port `port` u pólu své fáze
      "port": "S",
      "at": {"-1": [-5, 4], "1": [5, 4]},             // svorky S1 / S2 v souřadnicích značky pólu
      "draw": [ ...primitiva příčky sekundáru... ],   // kreslí se k pólu, jen když na `port` vedou žíly z `conductors`
      "conductors": {"1S1": ["L1", -1], "1S2": ["L1", 1]}   // žíla → [fáze pólu, svorka z `at`]
    },
    "terminals": {"scheme": "DIN 43856", "text": "kWh"}  // nepovinné: přístroj s očíslovanými svorkami
  }
}
```

Kategorie (`category`) je druh prvku: `Zdroje`, `Střídače a měniče`, `Jištění`, `Spínání`, `Měření`,
`Svorky a propojení`, `Rozvaděče`, `Síť a zátěž`, `Transformátory a napájení`, `Relé a stykače`, `Kabely`,
`Konektory`, `Instalace`, `Elektronika`. Tvar `Druh/QET` zařadí značku do sbalené podsložky cizí knihovny.
Pól se v knihovně nerozlišuje: v JPS je každá značka jednopólová (jedna čára = kabel se všemi žílami) a ve
vícepólu se rozkreslí podle `multipole` (bez něj se opakuje celá značka).

`multipole.terminals` (elektroměr při nepřímém měření): když na přístroj vede žíla sekundáru MTP, kreslí se ve
vícepólu jako obdélník se svorkami nahoře podle schématu `scheme` (`multipole.TERMINAL_SCHEMES`; DIN 43856:
I1 1–3, U1 2, I2 4–6, U2 5, I3 7–9, U3 8, N 11) a každá žíla vede na svou svorku; tatáž čísla svorek uvádí
zapojovací seznam („P1:3“). Žíly sekundáru MTP po fázích jsou `1S1 1S2 2S1 2S2 3S1 3S2`, napětí z MTN
`1a 2a 3a n`. Přímé měření (elektroměr průchozí L1–L3 N) se kreslí jako dřív.

Pravidla:

- Jednotky mm, počátek symbolu = jeho vztažný bod při vkládání.
- Porty na mřížce 2,5 mm. `dir` = směr, kterým z portu vychází vodič (N/E/S/W).
- Atribut `ref` je povinný (označení prvku ve schématu). Program ho při vložení předvyplní
  `iec_ref` + pořadové číslo.
- Tloušťka čar se neukládá v symbolu – řeší se vrstvou při exportu.

## Třída označení (`function_class`)

`iec_ref` je jen prefix automatického číslování (F → F1, F2…). `function_class` je seznam **povolených tříd**
označení dle ČSN EN IEC 81346-2 (1–2 velká písmena: třída a podtřída), případně firemní prefix ENVO
(`docs/ENVO_STYL.md`) až o 3 písmenech. Kontrola projektu (`ref_class`, varování) hlásí prvek, jehož
písmenný kód označení žádné třídě neodpovídá. Shoda je prefixem: třída „F“ přijme F3, FA1, FC2.

- Klíč chybí → třídy `[iec_ref]`; prázdný `iec_ref` → kontrola třídy se nedělá.
- `[]` → nekontroluje se (např. blok rozvaděče `fve.switchboard`, jehož označení je umístění).
- `validate()` vyžaduje třídy `^[A-Z]{1,3}$` a aby jim odpovídal i sám `iec_ref` (`iec_ref` + „1“).
- Příklad: jistič `fve.breaker_mcb` má `iec_ref` „F“ a `function_class` `["F", "Q"]` – označení Q1 je také v pořádku.
- Firemní prefix: svodič `fve.spd` má `iec_ref` „F“ a `function_class` `["F", "SPD"]` – firemní číslování
- Svodič DC: artikl `ucpv_v` (Ucpv, docs/COMPONENTS.md) se propíše do atributu `ucpv`; podle něj se omezuje délka stringu (`model/dc_system.py`).
  `SPD-DC1.1` (`docs/ENVO_STYL.md`) neodpovídá třídě F ani podtřídě FC, a třída „S“ by znamenala ruční ovládání
  (tlačítka S1). Proto explicitní třípísmenný prefix místo volnějšího „S“.
- Firemní číslování: tečka (`FU1.1`) je schválený standard ENVO a kontrola ji nehlásí; vnitřní „-“ (`SPD-DC1.1`)
  je jen informace. Třída, délka a znaky (bez oddělovačů) se kontrolují dál.

Nový klíč je nepovinný a starší program ho ignoruje, proto kvůli němu verze formátu symbolu nestoupá (viz „Verze formátu“).

## Verze formátu

Klíč `format_version` je nepovinný; chybí-li (starší soubory), platí 1. Aktuální verzi určuje konstanta
`SYMBOL_FORMAT_VERSION` v `envocad/model/symbol.py`. Značku s vyšší verzí program nenačte: v knihovně ji při
synchronizaci přeskočí s varováním v logu (zbytek knihovny se načte), archiv projektu s takovou značkou odmítne
a zbytek programu ji bere jako chybějící. Verzi zapisuje každý zápis symbolu (import DXF/QET/EPLAN, uložení,
editor symbolů, archiv). Verzi zvedat jen při nekompatibilní změně formátu; nepovinné klíče jako `function_class`
nebo `choices` verzi nezvedají.

## Nabídka hodnot atributu (`choices`)

Nepovinný klíč atributu `choices` = seznam `[hodnota, popisek]` (nebo jen řetězců, pak hodnota = popisek). Panel
Vlastnosti i dialog atributů pak místo textového pole nabídnou výběr (`ui/dialogs.ChoiceEdit`); hodnota mimo nabídku
(ručně upravený soubor) se zobrazí jako další položka. Uloží se hodnota, ne popisek. Starší program klíč ignoruje,
verze formátu symbolu se nemění (jako u `function_class`). Použití: směr přívodu/vývodu `sb.feed` (`dir`: `in` přívod, `out` vývod).

## Rezervované atributy prvku

Některé klíče v `attrs` prvku nastavuje program a značka by je neměla používat k jinému účelu:

| klíč | význam |
|---|---|
| `ref` | přístrojová část označení („F3“, bez „-“) |
| `func` | override aspektu funkce (`=`), prázdné = dědit z listu (`Sheet.func`) |
| `loc` | override aspektu umístění (`+`), prázdné = dědit z listu (`Sheet.loc`) |
| `wire_id` | přívod/vývod rozvaděče: id navázaného vodiče JPS |
| `cable_id` | vodič: id kabelu (`Project.cables`) |
| `sheet` | blok rozvaděče: název listu rozvaděče |
| `contacts` | kontaktní obraz přístroje (cívka, stykač, jistič, relé…): páry svorek oddělené mezerou/čárkou, volitelně s předponou druhu – `1/2 3/4 5/6 13/14 21/22`, `NO:11/14 NC:11/12`, `NO:DO1 NO:DO2` (předpony `NO`, `NC`; `P`, `PWR` a `HL` = silový/hlavní kontakt; velikost písmen nerozhoduje). Bez předpony dle IEC 60947-5-1: jednomístné liché/sudé = silový, dvoumístné s funkční číslicí 3/4 nebo 7/8 = NO, 1/2 nebo 5/6 = NC. Prázdné = nezadán (bez rezerv v zrcadle a bez kontrol `contact_count`/`contact_unknown`). Plní ho i artikl (sloupec `contacts`). |
| `t_min`, `t_max` | rozsah provozní teploty okolí přístroje [°C] dle datasheetu (z artiklu `t_min_c` / `t_max_c`, nebo ručně). Hodnocení oteplení po přístrojích (`model/thermal.py:device_temperatures`): teplota vzduchu v řadě přístroje vs. `t_max`, se zadanou nejnižší teplotou okolí skříně i `t_min`. Prázdné = předpoklad 40 °C (resp. −5 °C). Vestavěné přístroje rozvaděče s šířkou v modulech je mají jako skryté atributy (`show: false`); řadové svorky ne (hodnotí se jen s vlastním údajem) |
| `mirror` | `"0"` potlačí zrcadlo kontaktů pod hostitelem; jinak (prázdné) se kreslí, má-li přístroj kontakty nebo obraz. V GUI zaškrtávátko „Zobrazit zrcadlo kontaktů“ v panelu Vlastnosti |
| `star_source` | přerušovací bod: `"1"` = zdroj hvězdy (ostatní body se stejným označením jsou cíle); bez něj se body řetězí v pořadí list, x, −y |
| `terminals` | kontakt: páry svorek (`13/14`, i víc párů `13/14 23/24`); prázdné = výchozí podle druhu, silový kontakt/stykač pár na každý pól (1/2, 3/4, 5/6) |

Kontakty (`ctl.contact_*`) se k přístroji vážou označením `ref`: přístroj = prvky se stejným `ref` v jednom
prostoru označení (cívka `ctl.coil` + případně stykač `fve.contactor` kreslený v silovém schématu jako silové
kontakty cívky – položkou výkazu, rozložení a tepla je pak stykač). Zrcadlo kontaktů je tabulka pod hostitelem
(cívka, jinak hlavní prvek) – `envocad/model/xref.py`, návrh `docs/design/xref_zrcadleni_kontaktu.md`.

Kódy `func`/`loc` se zadávají bez znaménka („AC“, „RDC1“), jedna úroveň, znaky A–Z, 0–9, _ a tečka uvnitř – firemní `RFVE.AC`, `RFVE.DC` (max. 10).
Plné označení prvku je pak `=AC+RDC1-F3` (viz `envocad/model/designation.py`).

## Atributy vnitřního vodiče rozvaděče (výrobní data)

Na listu rozvaděče má vodič kromě běžných atributů (`WIRE_ATTRIBUTES`: `ref`, `cable`, `cross`…) nepovinné klíče
`SWITCHBOARD_WIRE_ATTRIBUTES` (`model/project.py`) pro výrobní zapojovací seznam (`model/wiring.py`, návrh
`docs/design/vyrobni_data.md`). **Formát projektu se nemění (v9)** – prázdná hodnota = automaticky.

| klíč | popisek | význam |
|---|---|---|
| `cross` | Průřez [mm²] | průřez vodiče; prázdné = z nejmenšího In přístrojů na koncích (`IN_TO_CROSS`, orientační), u `ctl.*` průřez řízení, jinak min. průřez |
| `cable` | Typ kabelu | typ vodiče; prázdné = `wire_type` rozvaděče (H07V-K) |
| `color` | Barva vodiče | jednožilový vodič vždy; vícežilový jen fáze/DC (N, PE, PEN si nechají barvu podle žíly); prázdné = barva žíly (`CORE_COLORS`) |
| `end_a`, `end_b` | Koncovka A/B | koncovka konce `a`/`b`; prázdné = automaticky dutinka DIN 46228 u ohebného vodiče (`-K`, `-F`, `LiY`), dvojitá při dvou žilách v jedné svorce; `-` = bez koncovky; jiný text se vypíše doslova |
| `prod` | Do výrobního seznamu | `0` = vodič se do výrobního seznamu nevypisuje; prázdné = ano |

### Parametry výrobních dat v `Layout.params`

Klíče `wire_*` v parametrech skříně (`WIRING_PARAMS`, výchozí `WIRING_DEFAULTS`). Priorita: výchozí v kódu <
`settings.json` → `standard.wiring` (stejné klíče; čte jen export) < `Layout.params` rozvaděče. Prázdná nebo
neplatná hodnota se přeskočí.

| klíč | výchozí | význam |
|---|---|---|
| `wire_type` | `H07V-K` | typ vodiče, pokud vodič nemá `cable` |
| `wire_end_mm` | 100 | přídavek na každý konec [mm] |
| `wire_reserve_pct` | 10 | rezerva délky [%] |
| `wire_round_mm` | 50 | zaokrouhlení délky nahoru [mm] |
| `wire_duct_side_mm` | 25 | osa svislého žlabu od konce DIN lišty [mm] |
| `wire_cross_min` | 1,5 | min. a výchozí silový průřez [mm²] |
| `wire_cross_ctl` | 1 | výchozí průřez řízení (`ctl.*`) [mm²] |
| `wire_unplaced` | `estimate` | neumístěné svorky/přívody/vývody/PE lišta/sběrnice: `estimate` = poloha odhadem, `none` = bez délky |

## Import z DXF výrobců

`envocad/library/dxf_import.py` načte DXF (modelspace nebo konkrétní blok), převede entity
LINE / CIRCLE / ARC / LWPOLYLINE / TEXT / MTEXT na primitiva, volitelně přeškáluje a vycentruje.
Porty DXF neobsahuje – doplní se ručně v editoru symbolů (TODO) nebo v JSON.

```
python -m envocad.library.dxf_import vyrobce.dxf --id fve.xyz --name "XYZ" --scale 1.0 -o out.json
```

## Komponenty (artikly)

Tabulka `components` v SQLite: `id, manufacturer, part_number, name, symbol_id, params (JSON), price, url`.
Zatím bez UI – plní se CSV importem (`store.import_components_csv`).

## Atributy přístrojů pro rozvaděče

Aby se přístroj objevil v rozložení a ve výkazech správně, má mít atributy `manufacturer`, `poles`
a `modules` (šířka na DIN liště v modulech 17,5 mm; `0` = nemodulový, nerozmisťuje se).
Symboly pro list rozvaděče mají prefix `sb.` (`envocad/library/builtin/switchboard/`): sběrnice `sb.busbar`
(porty IN, T1…T12 shora, vývody 1…13 zdola po 15 mm), přívod/vývod `sb.feed` (viz níže), svorkovnice `sb.terminal_block` (šířka skupiny `modules`; prázdná = počet svorek × 6,2 mm), PE/N můstek `sb.pe_bar`.

### Blok rozvaděče bez listu `fve.switchboard` (formát projektu v15)

Blok ROZVADĚČ má porty podle přívodů / vývodů svého listu (`project.switchboard_symbol`). Bez listu (stávající RD /
HR / RE, RFVE.AC bez mustru) je nese **v atributech**: `ports_in` (přívody vlevo, „XIN“ / „X1 X2 XE1“) a `ports_out`
(vývody vpravo, „XOUT XPE“), označení oddělená mezerou / čárkou; s listem se přidají porty, které list nemá.
`protect` = jištění portů („X1=63, X3=40“, A) pro kontrolu kabelu (`calc.check_cables` – In jištění vývodu vs Iz).
Údaje článku v popisku (zobrazené atributy): `main` (hlavní přístroj), `fve_out` (vývod FVE), `metering` (měření),
`inv_protect` (jištění střídačů), `grid_protection` (požadavek síťové ochrany – F7 `grid_protection_missing` ho
uzná). Kontrola: blok s porty z atributů = INFO `block_only` (ne `no_sheet`). Přívod / vývod listu s `anchor="1"` je
kotva bez zapojení (AC část RFVE bez mustru) – nezapojená = INFO `feed_anchor`. Hlavní vypínač `sb.main_switch` má
atribut `trip` (vypínací spoušť vazebního prvku síťové ochrany).

### Přívod / vývod `sb.feed` (formát projektu v13)

Jedna značka pro přívod i vývod rozvaděče (`docs/design/znacka_privod_vyvod.md`); jediné místo s predikáty je
`envocad/model/feed.py` (`is_feed`, `feed_dir`, `is_feed_in/out`, `feed_link_key`).
- Při `rot 0` je port `1` **nahoře** (`(0, 5)`, směr N), kroužek svorky v `(0, 0)`, kabelový výběžek dolů do `(0, −7,5)`.
- Směr toku **jen šipkou** na výběžku (otevřená, 2 mm): přívod hrot `(0, −3,5)` k portu, vývod hrot `(0, −6,5)` od
  portu. Text „PŘÍVOD“ / „VÝVOD“ se nekreslí.
- Atributy: `ref`, **`dir`** (`in` | `out`, výchozí `in`, skrytý, `choices`), `desc`, `from` (Odkud), `to` (Kam), `cable`,
  `terminal`. Ve výkresu se zobrazí jen `from` (přívod) nebo `to` (vývod). Prázdný `dir` = přívod; neplatný hlásí
  kontrola jako varování `feed_dir`.
- Základní JSON je přívod (náhled při vkládání z palety); obrázek vývodu skládá `feed.feed_symbol` přes
  `element_symbol` (jiná šipka, zobrazené „Kam“). Popisek je vpravo od svorky i u přívodu otočeného portem dolů.
- Ve vícepólu se kreslí jako dřívější `sb.feed_in` / `sb.feed_out` (`feed.multipole_feed_view`); štítek kabelu je na
  straně proti portu podle otočení.
- Staré `sb.feed_in` / `sb.feed_out`: projekt v12 → v13 migrace (`sb.feed_in` rot r → `sb.feed` `dir=in` rot r+180 –
  port na stejném místě), makra v1/v2 a schránka se převádějí při načtení (`normalize_legacy_element`), vestavěné
  řádky starých značek `sync_builtin` z SQLite smaže (uživatelská značka se stejným id zůstává).
- Sběrnice `sb.busbar` má navíc **přívody zdola `B1…B12`** (B1…B6 na x −60, −30, 0, 30, 60, 90; B7…B12 mezi nimi,
  vždy mimo polohy vývodů 1…12) – přívodní větev, která teče nahoru do sběrnice (RFVE, RFVE.AC). Při 7–12 přívodech
  generátor přiřadí porty B podle x zleva (odbočky schodovitě bez křížení); vývod 13 (x 112,5, za B12) je pro hlavní
  vypínač za posledním přívodem.
- **Parametrická sběrnice** (`envocad/model/busbar.py`, skládá ji `project.element_symbol` jako značku střídače):
  sběrnice s atributem **`taps`** (počet přívodů zdola) má délku a porty podle počtu přívodů a rozteče – přívody
  `B1…Bn` (a `T1…Tn` přímo nad nimi) od x −60 po **`tap_pitch`** (výchozí 30 mm, násobek 2,5 ≥ 7,5), vývody `1`
  (x B1 − 45, PE → XPE) a `2` (x B1 − 22,5, SPD) vlevo, vývody `3…` za posledním přívodem (`3` v x Bn + 37,5, další
  po rozteči; počet vpravo **`outs`**, výchozí 1), `IN` vlevo nahoře na začátku čáry, čára 7,5 mm za krajními porty.
  Počty se zvětší podle portů, na které vedou vodiče (nic se neodpojí). Prázdný / neplatný `taps` = pevná sběrnice
  výše (staré projekty, vlastní makra, nově vložená sběrnice). Generátor (RFVE.AC, AC část RFVE), vestavěná makra
  „AC přívod střídače“ / „AC jádro rozvaděče“ a šablona „AC rozvaděč FVE“ kreslí sběrnici parametrickou: každá
  odbočka svisle. Formát symbolu se nemění (atributy prvku); **formát projektu v14** – migrace v13 → v14 nic
  nemění, verze je vyšší jen proto, aby starší program (v13) soubor odmítl místo kreslení pevné sběrnice s přívody
  jinde (B13 a další by byly osiřelé porty). Makra a schránka se sběrnicí s `taps` vlastní verzi nemají.

## Footprinty (pohled do rozložení)

Footprint je obyčejný symbol (JSON) v kategorii `Rozložení/<výrobce>`, kreslený **ve skutečných mm**
s počátkem v levém horním rohu přístroje a Y nahoru (tedy souřadnice dolů jsou záporné). Artikl na něj
odkazuje sloupcem `footprint_id`. Vytvoří se importem DXF od výrobce:

```
python -m envocad.library.dxf_import pohled_LTN.dxf --id fp.oez.ltn-3p --name "LTN 3p čelní pohled" --no-center -o envocad/library/builtin/footprints/fp.oez.ltn-3p.json
```

Bez footprintu se kreslí generický modulový přístroj (páčky podle pólů, svorky) o šířce `modules` × 17,5 mm.

## Formát makra

Makro = pojmenovaná sestava prvků a vodičů (výřez listu) k opakovanému vkládání – `envocad/library/macros.py`
(bez Qt), návrh `docs/design/makra_promenne.md`. Soubory `*.json` ve `builtin/macros/` (vestavěná, generuje je
`tools/gen_builtin_macros.py`), `<sdílená knihovna>/macros/` a `~/.envocad/macros/` (stejné jméno přepíše dřívější).
**Formát projektu se kvůli makrům nemění** – makro se při vložení rozvine na obyčejné prvky a vodiče.

```json
{
  "version": 3,
  "name": "DC string v rozvaděči",
  "description": "…",
  "role": "dc_tech",                       // role v generátoru: dc_tech | dc_route | ac_feed | ac_core | ac_eps | ""
  "variables": [
    {"name": "n", "label": "Počet stringů", "type": "number", "default": "1", "min": 1, "max": 50, "auto": true},
    {"name": "j", "label": "Číslo stringu u střídače", "type": "number", "default": "{k}", "auto": true},
    {"name": "fuse_in", "label": "In pojistky", "type": "number", "unit": "A", "default": "15", "required": true},
    {"name": "spd", "label": "Svodič přepětí DC (typ)", "default": "T2",
     "help": "Doporučené hodnoty: T1, T2, T1+T2 (smí být i jiný text, např. T1+T2+T3). Prázdné = bez svodiče."}
  ],
  "value_sets": [{"name": "Pojistka 20 A gPV, SPD T1+T2", "values": {"fuse_in": "20", "spd": "T1+T2"}}],
  "repeat": {"count": "n", "pitch": 40},
  "fragment": {"elements": [ … ], "wires": [ … ], "pitch": 40}   // formát schránky (copy_fragment)
}
```

### Verze
- Bez `version` = v1 (`name`, `description`, `fragment`); v1 je podmnožina v2, migrace není potřeba.
- Makro s `version` vyšší než `MACRO_VERSION` (3) se nenačte (záznam v logu, v seznamu maker chybí).
- v3 (značka `sb.feed`): `save_macro` a vestavěná makra píší v3, aby starší EnvoCAD makro se `sb.feed` odmítl
  místo vložení zástupných „?“. Makra v1/v2 se `sb.feed_in` / `sb.feed_out` se převedou při načtení
  (`parse_macro`, soubor ve sdílené složce se nepřepisuje).
- Makro bez `variables` dostane implicitní textovou proměnnou za každý zástupný symbol ve fragmentu.
  `save_macro` („Uložit výběr jako makro…“) zapisuje v3 s těmito proměnnými.

### Proměnné a zástupné symboly
Zástupný symbol `{název}` smí být v hodnotách atributů prvků a vodičů, v `component_id` prvku a v portech vodičů.
Dosazuje se regulárním výrazem `\{[A-Za-z_][A-Za-z0-9_]*\}` – bez výrazů a formátovacích specifikací; neznámé `{x}`,
`{}`, `{0}`, `{a.b}` zůstanou beze změny. Bez aritmetiky (`nk = n + k` dodá opakování nebo generátor).
**`{{` se v makrech v2 neescapuje** – zůstává doslova (`{{a}}` s `a = X` dá `{X}`), na rozdíl od dřívějšího
`str.format_map`, kde `{{` znamenalo jednu složenou závorku. Doslovné `{název}` v makru tedy zapsat nejde.

| klíč | povinný | význam |
|---|---|---|
| `name` | ano | `^[A-Za-z_][A-Za-z0-9_]*$` (anglicky, snake_case), jedinečné v makru |
| `label`, `help`, `unit` | ne | texty dialogu (česky) |
| `type` | ne (`text`) | `text`, `number`, `choice`, `component` |
| `default` | ne | řetězec; smí skládat text z jiných proměnných (`"T{i}"`, jeden průchod) |
| `required` | ne | prázdná výsledná hodnota = chyba |
| `choices` | u `choice` | seznam řetězců (porovnává se bez mezer a velikosti písmen, uloží se tvar z nabídky) |
| `min`, `max` | ne | u `number`; čísla se normalizují („15,0“ → „15“) |
| `category` | u `component` | kategorie artiklu (`inverter`, `mcb`…) |
| `from` | ne | `"<proměnná component>.<parametr artiklu>"` – `part_number`, `manufacturer`, `name` nebo klíč `params` (`p_ac_kw`…) |
| `auto` | ne | hodnotu dodává volající (generátor, opakování); GUI ji sbalí pod „Další“ |

Rezervované kontextové názvy (dodává generátor / opakování): `k` (pořadí), `n` (počet), `nk` (n + k), `i` (číslo
střídače), `j` (string u střídače), `string` (označení stringu), `inverter` (označení střídače).
U makra s `repeat` dosazuje `k` a `nk` (a `n`, pokud počet není proměnná `n`) až `expand` v každém opakování –
`resolve_values` je ze zadaných hodnot do výchozích nedosazuje (`j = "{k}"` zůstane `{k}`); dialog tato pole zakáže.

Typ svodiče (`spd`) je ve vestavěných makrech volný text (doporučené T1, T2, T1+T2; projde i „T1+T2+T3“, „Typ 2“);
In přístrojů (`fuse_in`, `disc_in`, `breaker_in`, `main_in`) jsou čísla v A – „C40“ je chyba (charakteristika
jističe je samostatný atribut prvku).

Pořadí hodnot (pozdější vyhrává): `default` < základ volajícího (generátor: hodnoty ze specifikace `dc`/`ac`) <
artikl (`from`) < sada hodnot < zadané (uživatel / `values` ve specifikaci) < kontext.

### Sady hodnot (`value_sets`)
Pojmenované předvolby (`name`, `values`, volitelně `description`); smí být neúplné – zbytek z `default`. V generátoru
se vybírají položkou `"macros": {"dc_tech": {"name": "…", "value_set": "…", "values": {…}}}`.

### Artikl v makru
Proměnná `type: component` nese id artiklu; prvek fragmentu smí mít `"component_id": "{inv}"`. Po dosazení se zavolá
`Component.apply_to` – parametry artiklu se propíší do atributů (u střídače `mppt`, `strings_per_mppt` → DC1…DCn).

### Podmínky (`when`)
Atribut `when` prvku nebo vodiče: `NÁZEV`, `!NÁZEV`, `NÁZEV=HODNOTA`, `NÁZEV!=HODNOTA` (porovnání přesné, po oříznutí
mezer). Nepravda je `""`, `0`, `ne`, `no`, `false`, `off` (bez ohledu na velikost písmen). Vynechaný prvek vyřadí i
své vodiče; `when` se z atributů po rozvinutí odstraní. Vestavěná DC makra mají `"when": "spd"` u svodiče a vývodu XPE,
AC jádro u svodiče.

### Opakování (`repeat`)
Jen na úrovni makra: `count` = název proměnné s počtem, `pitch` = rozteč v mm (bez ní `fragment.pitch`, jinak šířka
+ 10 mm). Makro se vloží N× s `k = 1…N`, `n = N`, `nk = N + k`, posun `(k − 1) · pitch` zaokrouhlený na mřížku 2,5 mm.
Prvky s `"shared": "1"` (sběrnice, vývod XPE) se vloží jen jednou a další instance se na ně napojí (hledá se na listu
i mezi nově vytvořenými prvky). Počet musí být celé číslo 0…min(`max` proměnné počtu, 100 = `MAX_REPEAT`); prázdný,
desetinný nebo větší počet je chyba už v `resolve_values` (a `expand` ho odmítne `ValueError`). `max` proměnné počtu
nad `MAX_REPEAT` hlásí `validate_macro`. Generátor u DC rozvaděčů drží vlastní smyčku (`resolve_values(...,
repeat=False)`, `expand(..., repeat=False)`), `repeat` ani `max` počtu ho neomezují; slouží vkládání z GUI.

**Navazující číslování** při vložení do listu, kde už instance makra jsou: hodnota `k_start` (`macros.K_START`, není to
proměnná makra) posune opakování na `k = k_start … k_start + N − 1`, `nk = N + k`. Dialog makra ji předvyplní
(„Číslovat od (k)“ ve skupině Další) přes `suggest_numbering(project, sheet, m)` – nejmenší `k_start`, při kterém
žádné označení se zástupným symbolem (`X{k}`, `X{nk}`, `FU{i}.{j}`…) nekoliduje s prostorem označení listu (DC rozvaděč
se 4 stringy: X1–X8 obsazené → `k_start = 9`). U makra bez opakování se stejně předvyplní automatická proměnná `k`
(AC přívod do rozvaděče s X1 → `k = 2`, „od T2“). Duplicitní přívod/vývod (X1 dvakrát) hlásí kontrola jako `dup_ref`.

### Makro bez proměnných (kopie výřezu)
Makro bez proměnných a bez `repeat` (typicky „Uložit výběr jako makro…“ bez `{x}`) se vkládá jako kopie výřezu, jako
dřív `paste_fragment`: nesdíleným skupinám svorek se vymaže číslo svorky (`terminal`, doplní automatické číslování),
přívody/vývody `sb.feed` dostanou další volné označení; obojí jen tam, kde ref/terminal neobsahuje
zástupný symbol. Ostatní pravidla (`shared`, přečíslování F1 → další volné) platí stejně. Parametrická makra (a tedy
generátor, který navíc předává `copy=False`) označení svorek a přívodů z makra drží – jinak by se změnil např. vývod
XOUT AC jádra. V API `expand(..., copy=None)`: None = kopie právě u `not m.has_parameters`.

### Rozhraní (`envocad/library/macros.py`)
`load_macro(path)` / `parse_macro(data, path, source)` → `Macro`; `validate_macro(data)` → chyby česky;
`resolve_values(m, given, value_set, components, context, base)` → `(hodnoty, chyby)`;
`resolve_values(..., repeat=True)`; `repeat_context_names(m)`, `repeat_limit(m)`;
`expand(project, sheet, m, values, dx, dy, ref_prefix_of, components, repeat, copy)` → `(nové prvky, nové vodiče)` – list
nemění (GUI je vloží jedním undo příkazem); `instantiate` = `expand` bez opakování + vložení do listu.

## Formát topologie

Topologie = řetězec článků připojení od zdroje k síti (návrh `docs/design/topologie_f1_f2.md`, rozhodnutí
`docs/NAVRH_TOPOLOGIE.md`, kap. 8). Soubory `*.json` ve `builtin/topologies/` (vestavěné presety `rd`, `nn`,
`nn_hr_meter`, `vn`), `<sdílená knihovna>/topologies/` a `~/.envocad/topologies/` – stejné `id` přepíše dřívější
(vlastní > sdílená > vestavěná), neplatný soubor nebo vyšší `version` se vynechá (záznam v logu). Složky `topologies/`
(i `macros/`) knihovna značek nenačítá (`store.NON_SYMBOL_DIRS`). **Formát projektu se kvůli topologiím nemění.**

```jsonc
{
  "version": 1,                          // TOPOLOGY_VERSION; vyšší se nenačte
  "id": "nn",                            // jedinečné, písmena/číslice/_ . -; spec["topology"] = id
  "name": "Připojení na nn",             // povinné, text pro průvodce
  "description": "…",
  "buildings": ["company", "apartment"], // pro které druhy objektu (company | house | apartment); [] = všechny
  "level": "nn",                         // úroveň připojení: nn | vn
  "nodes": [                             // články v pořadí toku energie (od FV k síti), role jedinečné
    {"role": "rfve_dc", "ref": "RFVE.DC", "desc": "DC rozvaděč FVE", "per_inverter": false, "macros": {}},
    {"role": "inverter"},
    {"role": "rfve_ac", "ref": "RFVE.AC", "desc": "AC rozvaděč FVE", "options": {"grid_protection": "auto"}},
    {"role": "hr", "ref": "HR", "desc": "hlavní rozvaděč", "existing": true,
     "options": {"main_device": "breaker", "fve_device": "breaker"},
     "link": {"cable": "CYKY-J 5x35", "cross": 35, "length": 20, "method": "D"}},
    {"role": "re", "ref": "RE", "existing": true, "options": {"metering": "direct", "boundary": "hds"}},
    {"role": "hds", "ref": "HDS", "sheet": false, "options": {"char": "gG"}},
    {"role": "grid", "sheet": false}
  ]
}
```

| klíč článku | výchozí | význam |
|---|---|---|
| `role` | povinné | `rfve_dc` \| `inverter` \| `rfve_ac` \| `rfve` \| `rd` \| `hr` \| `re` \| `hds` \| `tr` \| `rvn` \| `grid` (zná generátor FVE, `generator/spec.ROLES`) |
| `ref`, `desc` | `""` | označení a popis rozvaděče (bloku) |
| `per_inverter` | `false` | jen `rfve_dc`: jeden rozvaděč na střídač (RFVE.DC1…n), jinak společný |
| `sheet` | `true` | `false` = jen blok bez listu rozvaděče (HDS, TR, DS) |
| `existing` | `false` | stávající rozvaděč – kreslí se jen dotčená část (RD, HR, RE) |
| `branch` | `false` | odbočka mimo hlavní tok (RE s měřicími obvody u `vn`) |
| `macros` | `{}` | role makra → název makra (F4; prázdné = vestavěný kód) |
| `options` | `{}` | výchozí hodnoty článku pro `spec["chain"][role]` (specifikace je přebíjí); hodnoty se převedou na text (`true` → „1“) |
| `link` | `{}` | kabel k dalšímu článku směrem k síti: `cable`, `cross`, `length`, `method` |

Uzly před `inverter` jsou DC strana, za ním AC; `rfve` (rodinný dům) stojí před střídači a je i prvním AC článkem.
### Volby článků (`spec["chain"]`, F2)
Volby článku: `spec["chain"][role]` > `options` článku presetu > výchozí hodnota generátoru; kabel k dalšímu článku
`spec["chain"][role]` > `link` presetu (> `ac.grid_*` u hlavního AC článku, jen zadané ve specifikaci – jinak průřez
pro In vývodu FVE). Logika `envocad/generator/boards/`, pravidla jištění `envocad/generator/currents.py`.

| role | klíč | výchozí | význam |
|---|---|---|---|
| všechny | `ref`, `desc` | z presetu | označení a popis bloku (přepis; dřívější `switchboard.ref`, `connection.*_board.ref` také) |
| všechny | `cable`, `cross`, `length`, `method` | `""` | kabel od článku k dalšímu směrem k síti; nový úsek bez `cross` → `calc.min_cross(In, method)`; stávající (`existing`) bez `cable`/`cross` = vodič bez označení; od `hds` k DS vždy bez kabelu |
| `rfve_ac`, `rfve`, `rd`, `hr`, `re`, `rvn` | `builtin` | standard `ac_builtin` (`false`) | list článku vestavěným kódem (jako před rozhodnutím 12); `false` = RFVE.AC / AC část RFVE z mustru (jinak blok bez listu / kotvy), RD / HR / RE (i HR, RVN, RE trafostanice na vn) jen blok bez listu s údaji v atributech |
| `rfve_dc` | `per_inverter` | `false` | DC rozvaděč u technologie na střídač (RFVE.DC1…n, stav před F2); jinak jeden společný RFVE.DC (přerostl-li by s ním list „AC a připojení“ limit, generátor vezme RFVE.DC na střídač, když klíč nezadáš) |
| `rd`, `hr` | `main_device` | `switch` (RD), `breaker` (HR) | hlavní přístroj stávajícího rozvaděče |
| `rd`, `hr` | `main_in` | `""` | In stávajícího hlavního přístroje; v listu (`builtin`) prázdné → `in_unresolved`, chyba F7 `breaker_no_in`; v bloku bez listu jen údaj v popisku |
| `rd`, `hr` | `fve_device` | `breaker` | vývod FVE: `breaker` \| `fuse_disconnect`; pojistka s `fve_in` ≤ 80 A → ValueError |
| `rd`, `hr` | `fve_in` | nejbližší velikost ≥ max(Σ proudů střídačů, největší jistič střídače) | In vývodu FVE (blok bez listu: i `protect` „X1=…“ pro kontrolu kabelu) |
| `rd`, `hr` | `load` | „stávající rozvody objektu“ | popis vývodu X2 a značky spotřeby |
| `hr` | `metering`, `ct_ratio`, `switch_in`, `boundary` | `""` | měření v HR (topologie `nn_hr_meter`) – jako `re` |
| `re` | `main_in`, `char` | `""`, `B` | hlavní jistič před elektroměrem (do 125 A MCB, jinak MCCB); prázdné In v listu → chyba F7 |
| `re` | `metering` | `direct` | `direct` (elektroměr v sérii) \| `indirect` (MTP, elektroměr na sekundáru) |
| `re` | `ct_ratio` | z `main_in` | převod MTP („200/5 A“) |
| `re` | `switch_in` | `main_in` | In vypínače instalace |
| `re` | `boundary` | `hds` | hranice vlastnictví `hds` \| `re_main` \| `re_meter` (atribut `boundary="1"` na HDS / HJ / elektroměru + text v blokovém schématu) |
| `hds` | `in_`, `char`, `poles` | `""`, `gG`, `3` | pojistky HDS (`fve.hds`); prázdné In = jen INFO `hds_no_in` |
| `rfve`, `rfve_ac` | `grid_protection` | `auto` | síťová ochrana `fve.grid_protection`: `auto` = instalovaný výkon DC nad `standard.grid_protection_kwp` (30 kWp), `1` vždy, `0` nikdy (F7 `grid_protection_missing`); jinak ValueError |

Nepovinné klíče střídače: `inverters[].ac_group` – skupina střídačů na jiném místě (krok 10): každá skupina má vlastní
AC rozvaděč RFVE.AC{n} (hlavní „“ = RFVE.AC1) a vlastní vývod FVE ve stávajícím HR (X1, X3, X4…; X2 = stávající
rozvody); jen nn s RFVE.AC a HR (firma, bytový dům, měření v HR), jinak ValueError. Řady střídačů se v blokovém
schématu seřadí po skupinách.

**Role maker v generátoru** (`spec.macros.<role>`): `dc_tech`, `dc_route` (DC rozvaděče – výchozí vestavěná),
`ac_feed`, `ac_core`, `ac_eps` (AC část). **AC část je mustr** (rozhodnutí 12): list RFVE.AC / AC část RFVE vznikne jen
z maker rolí `ac_feed` + `ac_core` ze **sdílené nebo vlastní** knihovny (zdroj makra není „vestavěné“) – název
zadaný ve specifikaci (`spec.macros`, jen zadaný uživatelem) > `node.macros` presetu > první makro s klíčem `role`;
`ac_eps` volitelně (bez něj u RD jen kotvy XE{i} / XB{i}). Vestavěná makra a kód AC části platí jen s volbou
`builtin` / standardem `ac_builtin` (pak i `spec.macros` s vestavěnými názvy, prázdný název = kód). Jádro `ac_core` má
auto proměnnou `grid_protection` („1“ / „“) – prvky s `"when": "grid_protection"` (vestavěné: síťová ochrana z vývodu
4 sběrnice přes jistič měřicího vstupu; `acts_on` a vypínací spoušť `trip` vazebního prvku doplní generátor = hlavní
vypínač, nemá-li ochrana `acts_on` z mustru). `ac_eps` na hybridní střídač s baterií: auto `i`, `inverter`, `eps_in`
(In jističe před přepínačem i přepínače), `main_in`; kotvy `sb.feed` `dir=in` `XE{i}` (EPS od střídače), `sb.feed`
`dir=out` `XB{i}` (zálohované okruhy), sdílená sběrnice `1` vývod 5 → **jistič** → port 1 přepínače (síťová strana).
Požadavky na mustr (síťová ochrana, EPS) v `docs/design/topologie_f1_f2.md`, kap. 3.

**Výběr topologie** (`envocad/generator/spec.select_topology(spec, topologies)`): `spec["topology"]` zadané → ten preset
(jediná cesta k `nn_hr_meter`); jinak rodinný dům → `rd` (i nad 30 kWp), `connection.level` "vn" → `vn`, jinak `nn`
(firma i bytový dům). Preset jiného druhu objektu nebo jiné úrovně připojení než zadané, neznámé `id`, přípojka VN u
rodinného domu nebo neznámá role → ValueError.

### Rozhraní
`envocad/model/topology.py` (bez Qt, obor-nezávislé): `CableLink`, `ChainNode`, `Topology` (`node(role)`, `roles()`,
`flow()`, `chain_text(start, labels)`), `parse_topology(data, source, path, known_roles)` → `Topology` (ValueError
česky), `validate_topology(data, known_roles)` → chyby česky. `envocad/library/topologies.py`: `topology_dirs()`,
`load_topology(path, source)`, `load_topologies()` → `{id: Topology}`, `list_topologies()`, `find_topology(id)`.
`envocad/generator/spec.py`: `select_topology`, `installed_kwp`, `chain_text(topology)` („stringy → RFVE.DC → T →
RFVE.AC → HR → RE → HDS → DS“), `check_topology`, `ROLES`.

## Aliasy příkazového řádku (`aliases.json`)

Výchozí aliasy příkazů jsou v `envocad/cmd/aliases.json`, uživatelské (obdoba `acad.pgp` v ZWCAD/AutoCAD)
v `~/.envocad/aliases.json` (Windows `C:\Users\<jméno>\.envocad\aliases.json`) ve stejném tvaru:

```json
{"format": "envocad-aliases", "aliases": {"M": "move", "PR": "move", "OT": "rotate"}}
```

Klíč = alias, hodnota = kanonické jméno příkazu (`insert`, `wire`, `move`, `copy`, `rotate`, `mirror`, `delete`, `set`,
`select`, `sheet`, `undo`, `redo`, `checks`, `save`, `script`, `help`, `zoom`, `fit`; seznam vypíše `HELP`). Velikost
písmen a diakritika se neporovnávají. Uživatelský alias přepíše výchozí alias se stejným zápisem, kanonické jméno
příkazu ne; alias na neznámý příkaz se ignoruje (varování do logu). Klíč `format` je nepovinný. Návrh a syntaxe
příkazů: `docs/design/prikazovy_radek.md`, `docs/MANUAL.md` sekce 12.

Skripty příkazového řádku (`.ecs`) nejsou součástí knihovny ani projektu – formát projektu se nemění
(aktuální `FORMAT_VERSION` je 18, viz `docs/ARCHITECTURE.md`).
