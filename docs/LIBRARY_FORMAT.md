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
(porty IN + 1…10 po 15 mm), přívod `sb.feed_in`, vývod `sb.feed_out`, svorkovnice `sb.terminal_block`, PE/N můstek `sb.pe_bar`.

## Footprinty (pohled do rozložení)

Footprint je obyčejný symbol (JSON) v kategorii `Rozložení/<výrobce>`, kreslený **ve skutečných mm**
s počátkem v levém horním rohu přístroje a Y nahoru (tedy souřadnice dolů jsou záporné). Artikl na něj
odkazuje sloupcem `footprint_id`. Vytvoří se importem DXF od výrobce:

```
python -m envocad.library.dxf_import pohled_LTN.dxf --id fp.oez.ltn-3p --name "LTN 3p čelní pohled" --no-center -o envocad/library/builtin/footprints/fp.oez.ltn-3p.json
```

Bez footprintu se kreslí generický modulový přístroj (páčky podle pólů, svorky) o šířce `modules` × 17,5 mm.
