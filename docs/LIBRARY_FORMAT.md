# Formát knihovny symbolů

Každý symbol je jeden JSON soubor. Vestavěné symboly jsou v `envocad/library/builtin/<obor>/*.json`
a při startu se nahrají do SQLite (`~/.envocad/library.db`), kde přibývají i uživatelské/importované.

```json
{
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
    {"name": "DC1", "x": -10, "y": 5,  "dir": "W"},   // v JPS je čára vždy jednopólová; pár DC+/DC- jsou žíly vodiče
    {"name": "DC2", "x": -10, "y": -5, "dir": "W"},
    {"name": "AC",  "x": 10,  "y": 0,  "dir": "E"}
  ],
  "attributes": [
    {"key": "ref",   "label": "Označení",  "default": "", "show": true},
    {"key": "type",  "label": "Typ",       "default": "", "show": true},
    {"key": "p_ac",  "label": "P_AC [kW]", "default": "", "show": false},
    {"key": "n_modules", "label": "Počet modulů", "show": true, "fmt": "{}× modul"}   // fmt = formát zobrazené hodnoty
  ],
  "label_pos": {"x": 12, "y": 8},
  "multipole": {                      // volitelné – podoba ve vícepólovém schématu (průchozí prvky)
    "pole": [ ...primitiva jednoho pólu... ],   // kreslí se pro každou spínanou žílu (rozteč 7,5 mm)
    "common": [ ...kreslí se jednou u 1. pólu... ],  // spoušť, cívka, sumační transformátor…
    "link": true,                     // čárkovaná mechanická vazba pólů
    "link_at": [0, 2]                 // bod pólu, kterým vazba prochází
  }
}
```

Kategorie (`category`) je druh prvku: `Zdroje`, `Střídače a měniče`, `Jištění`, `Spínání`, `Měření`,
`Svorky a propojení`, `Rozvaděče`, `Síť a zátěž`, `Transformátory a napájení`, `Relé a stykače`, `Kabely`,
`Konektory`, `Instalace`, `Elektronika`. Tvar `Druh/QET` zařadí značku do sbalené podsložky cizí knihovny.
Pól se v knihovně nerozlišuje: v JPS je každá značka jednopólová (jedna čára = kabel se všemi žílami) a ve
vícepólu se rozkreslí podle `multipole` (bez něj se opakuje celá značka).

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
  `SPD-DC1.1` (`docs/ENVO_STYL.md`) neodpovídá třídě F ani podtřídě FC, a třída „S“ by znamenala ruční ovládání
  (tlačítka S1). Proto explicitní třípísmenný prefix místo volnějšího „S“.
- Firemní číslování: tečka (`FU1.1`) je schválený standard ENVO a kontrola ji nehlásí; vnitřní „-“ (`SPD-DC1.1`)
  je jen informace. Třída, délka a znaky (bez oddělovačů) se kontrolují dál.

Formát symbolu kvůli tomu nemá verzi – nový klíč je nepovinný a starší program ho ignoruje.

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
| `mirror` | `"0"` potlačí zrcadlo kontaktů pod hostitelem; jinak (prázdné) se kreslí, má-li přístroj kontakty nebo obraz. V GUI zaškrtávátko „Zobrazit zrcadlo kontaktů“ v panelu Vlastnosti |
| `star_source` | přerušovací bod: `"1"` = zdroj hvězdy (ostatní body se stejným označením jsou cíle); bez něj se body řetězí v pořadí list, x, −y |
| `terminals` | kontakt: páry svorek (`13/14`, i víc párů `13/14 23/24`); prázdné = výchozí podle druhu, silový kontakt/stykač pár na každý pól (1/2, 3/4, 5/6) |

Kontakty (`ctl.contact_*`) se k přístroji vážou označením `ref`: přístroj = prvky se stejným `ref` v jednom
prostoru označení (cívka `ctl.coil` + případně stykač `fve.contactor` kreslený v silovém schématu jako silové
kontakty cívky – položkou výkazu, rozložení a tepla je pak stykač). Zrcadlo kontaktů je tabulka pod hostitelem
(cívka, jinak hlavní prvek) – `envocad/model/xref.py`, návrh `docs/design/xref_zrcadleni_kontaktu.md`.

Kódy `func`/`loc` se zadávají bez znaménka („AC“, „RDC1“), jedna úroveň, znaky A–Z, 0–9, _ (max. 10).
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
(porty IN, T1…T10 shora, vývody 1…12 zdola po 15 mm), přívod `sb.feed_in`, vývod `sb.feed_out`, svorkovnice `sb.terminal_block` (šířka skupiny `modules`; prázdná = počet svorek × 6,2 mm), PE/N můstek `sb.pe_bar`.

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
  "version": 2,
  "name": "DC string v rozvaděči",
  "description": "…",
  "role": "dc_tech",                       // role v generátoru: dc_tech | dc_route | ac_feed | ac_core | ""
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
- Makro s `version` vyšší než `MACRO_VERSION` (2) se nenačte (záznam v logu, v seznamu maker chybí).
- Makro bez `variables` dostane implicitní textovou proměnnou za každý zástupný symbol ve fragmentu.
  `save_macro` („Uložit výběr jako makro…“) zapisuje v2 s těmito proměnnými.

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
přívody/vývody `sb.feed_in`/`sb.feed_out` dostanou další volné označení; obojí jen tam, kde ref/terminal neobsahuje
zástupný symbol. Ostatní pravidla (`shared`, přečíslování F1 → další volné) platí stejně. Parametrická makra (a tedy
generátor, který navíc předává `copy=False`) označení svorek a přívodů z makra drží – jinak by se změnil např. vývod
XOUT AC jádra. V API `expand(..., copy=None)`: None = kopie právě u `not m.has_parameters`.

### Rozhraní (`envocad/library/macros.py`)
`load_macro(path)` / `parse_macro(data, path, source)` → `Macro`; `validate_macro(data)` → chyby česky;
`resolve_values(m, given, value_set, components, context, base)` → `(hodnoty, chyby)`;
`resolve_values(..., repeat=True)`; `repeat_context_names(m)`, `repeat_limit(m)`;
`expand(project, sheet, m, values, dx, dy, ref_prefix_of, components, repeat, copy)` → `(nové prvky, nové vodiče)` – list
nemění (GUI je vloží jedním undo příkazem); `instantiate` = `expand` bez opakování + vložení do listu.
