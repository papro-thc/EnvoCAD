# Formát knihovny symbolů

Každý symbol je jeden JSON soubor. Vestavěné symboly jsou v `envocad/library/builtin/<obor>/*.json`
a při startu se nahrají do SQLite (`~/.envocad/library.db`), kde přibývají i uživatelské/importované.

```json
{
  "id": "fve.inverter.3ph",
  "name": "Střídač 3f",
  "category": "FVE/Střídače",
  "description": "Síťový střídač DC/AC, třífázový",
  "iec_ref": "T",                     // písmeno označení dle ČSN EN IEC 81346 → T1, T2…
  "primitives": [
    {"type": "rect",    "x": -10, "y": -10, "w": 20, "h": 20},
    {"type": "line",    "x1": -10, "y1": 10, "x2": 10, "y2": -10},
    {"type": "circle",  "cx": 0, "cy": 0, "r": 2.5},
    {"type": "arc",     "cx": 0, "cy": 0, "r": 5, "start": 0, "end": 180},
    {"type": "polyline","points": [[0,0],[5,5],[10,0]], "closed": false},
    {"type": "text",    "x": 0, "y": 12, "text": "DC", "height": 2.5, "align": "center"}
  ],
  "ports": [
    {"name": "DC+", "x": -10, "y": 5,  "dir": "W"},
    {"name": "DC-", "x": -10, "y": -5, "dir": "W"},
    {"name": "AC",  "x": 10,  "y": 0,  "dir": "E"}
  ],
  "attributes": [
    {"key": "ref",   "label": "Označení",  "default": "", "show": true},
    {"key": "type",  "label": "Typ",       "default": "", "show": true},
    {"key": "p_ac",  "label": "P_AC [kW]", "default": "", "show": false}
  ],
  "label_pos": {"x": 12, "y": 8}
}
```

Pravidla:

- Jednotky mm, počátek symbolu = jeho vztažný bod při vkládání.
- Porty na mřížce 2,5 mm. `dir` = směr, kterým z portu vychází vodič (N/E/S/W).
- Atribut `ref` je povinný (označení prvku ve schématu). Program ho při vložení předvyplní
  `iec_ref` + pořadové číslo.
- Tloušťka čar se neukládá v symbolu – řeší se vrstvou při exportu.

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
