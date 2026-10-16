# Návrh: makra se zástupnými proměnnými a sadami hodnot

Návrh agenta `architekt` (10/2026), schválil orchestrátor. Roadmapa „Z rešerše EPLAN 2026“, bod Makra se zástupnými
proměnnými (řeší i „Funkční šablony artiklů“). **Formát projektu se nemění (v8).** Mění se jen JSON makra:
nepovinné klíče a `"version": 2`; makra v1 platí beze změny. Zástupný symbol zůstává `{x}`.

## 0. Dnešní stav a chyby
- `library/macros.py` `instantiate()` dosazuje přes `str.format_map(_Safe)` (zbytečně volné: `{x.attr}`, `{x[0]}`,
  formátovací specifikace), `shared` prvky slučuje, výsledek rovnou vkládá do listu. Proměnné nejsou deklarované.
- `generate.py` `_macro_vars()` natvrdo mapuje specifikaci (`fuse_in, disc_in, spd, breaker_in, main_in, ac_spd`);
  smyčky přidávají `k, nk, n, string, i, j, inverter`.
- **Chyba v GUI:** `main_window.insert_macro` → `canvas.insert_fragment` / `multipole_view.insert_fragment` používají
  `paste_fragment` bez dosazení: vloží doslova `in_ = "{fuse_in}"`, `FU{i}.{j}` přečísluje na F1, `shared` XPE zduplikuje.
- `inverter_symbol()` už dělá DC1…DCn z `mppt` × `strings_per_mppt`; chybí přenos z artiklu
  (`build_project` nastaví `component_id`, ale nevolá `Component.apply_to`).

## 1. Proměnné
Syntax `{x}` (zdůvodnění: používají ji všechna makra, `fmt` atributů, dokumentace; jednoznačný konec; EPLAN `#x`
převede případný budoucí importér). Dosazení regexem, bez eval a formátovacích specifikací:
```python
_PH = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
def subst(text: str, values: dict[str, str]) -> str   # neznámé {x}, {}, {0}, {a.b} nechá beze změny
```
Názvy proměnných ASCII snake_case (anglicky), popisky česky.

### JSON makra v2
```json
{
  "version": 2, "name": "DC string v rozvaděči", "description": "…", "role": "dc_tech",
  "variables": [
    {"name": "n", "label": "Počet stringů", "type": "number", "default": "1", "min": 1, "max": 50, "auto": true},
    {"name": "j", "label": "Číslo stringu", "type": "number", "default": "{k}", "auto": true},
    {"name": "fuse_in", "label": "In pojistky", "type": "number", "unit": "A", "default": "15", "required": true},
    {"name": "spd", "label": "Svodič DC", "type": "choice", "choices": ["", "T2", "T1+T2"], "default": "T2"}
  ],
  "value_sets": [{"name": "OEZ OPVP10 15 A, SPD T2", "values": {"fuse_in": "15", "spd": "T2"}}],
  "repeat": {"count": "n", "pitch": 40},
  "fragment": {"elements": [], "wires": [], "pitch": 40}
}
```
| klíč | povinný | význam |
|---|---|---|
| `name` | ano | `^[A-Za-z_][A-Za-z0-9_]*$`, jedinečné v makru |
| `label`, `help`, `unit` | ne | texty dialogu |
| `type` | ne (`text`) | `text`, `number`, `choice`, `component` |
| `default` | ne | řetězec, smí obsahovat `{jiné}` (jen skládání textu, jeden průchod) |
| `required` | ne | prázdná výsledná hodnota = chyba |
| `choices` | u `choice` | seznam řetězců |
| `min`, `max` | ne | u `number` |
| `category` | u `component` | kategorie artiklu |
| `from` | ne | `"<proměnná component>.<parametr artiklu>"` (`part_number`, `manufacturer`, klíč `params`) |
| `auto` | ne | dodává volající (generátor, opakování); v GUI sbalené pod „Další“ |

Bez aritmetiky (`nk = n + k` spočítá opakování/generátor). Rezervované kontextové názvy: `k, n, nk, i, j, string, inverter`.
Zpětná kompatibilita: makro bez `variables` dostane implicitní `text` proměnné ze všech `{x}` ve fragmentu; makro bez
zástupných symbolů a deklarací se v GUI vkládá jako dnes.

```python
MACRO_VERSION = 2
RESERVED = frozenset({"k", "n", "nk", "i", "j", "string", "inverter"})
MAX_REPEAT = 100
@dataclass(frozen=True)
class MacroVar:
    name: str; label: str = ""; type: str = "text"; default: str = ""; unit: str = ""; help: str = ""
    required: bool = False; choices: tuple[str, ...] = (); min: float | None = None; max: float | None = None
    category: str = ""; source: str = ""   # JSON "from"
    auto: bool = False; implicit: bool = False
@dataclass(frozen=True)
class ValueSet:
    name: str; values: dict[str, str]; description: str = ""
@dataclass(frozen=True)
class Repeat:
    count: str; pitch: float | None = None
@dataclass
class Macro:   # stávající pole + version=1, variables, value_sets, repeat=None, role=""
```

## 2. Sady hodnot a artikly (funkční šablony artiklů)
- `value_sets` – pojmenované předvolby v makru (neúplné; zbytek z `default`).
- Proměnná `type: component` + `from` čte parametry artiklu. Prvek ve fragmentu smí mít `"component_id": "{inv}"`;
  po dosazení `Component.apply_to(prvek)` → `mppt`, `strings_per_mppt` → `inverter_symbol()` dá DC1…DCn.
- Funkční šablona artiklu = nepovinný sloupec CSV `macro` (název makra) v `params` – fáze 5, volitelně.
- Pořadí hodnot (pozdější vyhrává): default < artikl (`from`) < sada < zadané (uživatel/specifikace) < kontext.
  V generátoru je „základ ze specifikace“ (`_macro_vars`) hned za default.

## 3. Podmínky a opakování (bez eval)
- Atribut `when` prvku/vodiče: `NAME | !NAME | NAME=VALUE | NAME!=VALUE`; nepravda = `""`, `0`, `ne`, `no`, `false`,
  `off` (case-insensitive). Vynechaný prvek vyřadí i své vodiče. `when` se z attrs po rozvinutí odstraní.
  SPD ve vestavěných DC makrech dostane `"when": "spd"`.
- `repeat` jen na úrovni makra: `count`× s `k = 1..N`, `n = N`, `nk = N + k`, `dx = (k-1)·pitch` (na mřížce);
  `shared` slučuje; `N > MAX_REPEAT` = chyba. Jedna úroveň, počet = jedna proměnná.
- Generátor si u DC rozvaděčů drží vlastní smyčku (`repeat=False`); `repeat` ve vestavěném makru slouží GUI.

## 4. API, generátor, GUI
```python
def subst(text, values) -> str
def placeholders(fragment: dict) -> set[str]
def load_macro(path, source="vlastní") -> Macro | None    # v1 i v2; version > MACRO_VERSION → None + log
def parse_macro(data, path, source) -> Macro
def validate_macro(data: dict) -> list[str]               # česky, prázdné = OK
def resolve_values(m, given=None, value_set=None, components=None, context=None) -> tuple[dict[str, str], list[str]]
    # čísla normalizuje "15,0" → "15"; chyby: required, number/min/max, choice, neznámá sada/artikl
def expand(project, sheet, m, values, dx=0.0, dy=0.0, ref_prefix_of=None, components=None, repeat=True)
        -> tuple[list, list]   # NEVKLÁDÁ do listu (undo); shared hledá v listu i v nově vytvořených
def instantiate(project, sheet, fragment, vars_, dx=0.0, dy=0.0, ref_prefix_of=None)   # signatura beze změny, přes expand + vložení
def save_macro(name, description, fragment, shared=False) -> Path   # zapíše version 2 + implicitní variables
```
`components` = callable (`LibraryStore().component`), `macros.py` neimportuje store. `list_macros()` přes `load_macro`.

Generátor: `spec["macros"][role]` = řetězec nebo `{"name", "value_set", "values"}`; `_macro_ref(entry)`;
`resolve_values(m, given={**_macro_vars(dc, ac), **entry_values}, value_set, components=lib.component, context={…})`;
chyby → `ValueError` s názvem makra. Volitelně `apply_to` artiklu střídače pro nezadané atributy. JPS dál kódem.

GUI: `MacroValuesDialog(macro, library, context=None)` (`.values()`, `.value_set()`): sada hodnot, pole podle typu
(`component` přes `ComponentPicker`, přepočet `from`), `auto` ve sbalené skupině „Další (číslování)“, OK volá
`resolve_values` a chyby nechá v dialogu. `main_window.insert_macro` → `load_macro` → dialog (má-li proměnné/repeat)
→ `scene.insert_macro(m, values, at)` v `canvas.py` i `multipole_view.py` → `expand(repeat=True)` → jeden
`undo.push` (`PasteCommand(text=…)`, ve vícepólu `MultipoleAddCommand`). Sloučené `shared` prvky nejsou nové.

## 5. Formát
Projekt beze změny (v8). Makro: `version` (bez = 1; v1 ⊂ v2, migrace není). `load_macro` odmítne vyšší verzi.
Vestavěná makra doplnit o `version`, `variables`, `value_sets`, `role`, `repeat`, `when` u SPD – generátor musí dát
stejný výstup (regresní snímek před refaktorem). Symbol beze změny. Artikl: volitelný sloupec `macro`.

## 6. Testy a pořadí
`tests/test_macros.py`: subst; v1 implicitní proměnné, version 99 → None; resolve_values pořadí a chyby; component +
from + apply_to → inverter_dc_inputs; when; repeat (shared, mřížka, MAX_REPEAT); expand nemění list, instantiate
ano; validate_macro pro vestavěná makra; regrese generátoru; objektová položka `macros`. GUI smoke: vložení „DC string
v rozvaděči“ s podstrčeným dialogem (n=2, fuse_in=20) → žádné `{`, jeden XPE, jedno undo vrátí list.

Pořadí: (1) subst, dataclassy, parse/load/validate, resolve_values; (2) expand, when, repeat, apply_to, instantiate;
(3) data vestavěných maker v2, generate.py, dokumentace formátu; (4) GUI; (5) volitelně apply_to v build_project,
výběr makra a sady v průvodci, sloupec `macro` u artiklu.

## YAGNI
Aritmetika; opakování na úrovni prvku a vnořené; vnořená makra; skládání JPS z maker; vazba prvku na instanci makra
v projektu; editor proměnných v GUI; pamatování posledních hodnot; příslušenství k rámu; import maker z EPLANu.
