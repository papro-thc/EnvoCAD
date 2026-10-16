# Návrh formátu v8: strukturní označení IEC 81346, kontrola označení vs. funkce, revize ve výkresu

Návrh agenta `architekt` (10/2026), schválil orchestrátor. Úkoly 1, 2 a 5 ze sekce „Z rešerše EPLAN 2026“
v `docs/ROADMAP.md`. Jedno zvednutí `FORMAT_VERSION` 7 → 8. Formát symbolu se mění jen o nepovinný klíč
(bez verze symbolu).

## Výchozí stav (zjištěno v kódu)
- Prostor označení je implicitní: `check_project` počítá duplicity podle `(sheet.id | "", ref)`, stejně
  `used_refs(sheet)`; `next_ref()` je globální.
- Párování přes `ref` po celém projektu: kontakty ↔ cívka (`contacts_of`, `coil_of`), přerušovací body,
  kabely (`cable_by_ref`, `sync_cables` jen JPS), svorky `"X1:3"` v `Wire.terminals` (vázané na list).
- `iec_ref` symbolu = prefix auto-číslování. QET značky ho mají většinou prázdný.
- `fve.switchboard` má `iec_ref "R"`, ale `generate.py` čísluje `next_ref("RDC")` – jeho `ref` je ve skutečnosti
  **umístění**.
- `store.py` drží symbol jako JSON blob → nový klíč symbolu nepotřebuje migraci SQLite.
- `compare_revision` (`ui/main_window.py`) zapisuje `meta` mimo undo a volá `resetClean()` – porušení CLAUDE.md,
  opravuje bod 5.

## 1. Strukturní označení (=funkce, +umístění, -přístroj)

### Rozhodnutí
1. `attrs["ref"]` zůstává **jen přístrojová část** („F3“, bez „-“). Párování se nemění.
2. Aspekty `=` a `+` na třech úrovních:
   - **Projekt:** `Project.structures` – registr kódů s popisy (jen popisy/výkazy/dialog; kód mimo registr je
     platný, kontrola hlásí INFO).
   - **List:** `Sheet.func`, `Sheet.loc` – výchozí pro prvky a vodiče listu.
   - **Prvek:** volitelný override `Element.attrs["func"]` / `attrs["loc"]` (prázdné = dědit z listu).
3. Kódy bez znaménka („RS1“), vždy **jedna úroveň** na aspekt (víceúroveň YAGNI, rozšíření bez migrace).
4. List rozvaděče má `+` explicitně: migrace i `create_switchboard_sheet` zapíšou `sheet.loc = ref bloku`.
   Blok `fve.switchboard` je „prvek umístění“, plné označení `=func+RDC1`.
5. List rozvaděče s prázdným `loc` = anonymní vlastní prostor `("", "#"+sheet.id)` (= dnešní chování);
   kontrola `sb_no_loc`.
6. **Vodiče override nedostanou** (kabely se párují podle `ref` napříč projektem); vodiče na JPS mají globální
   scope `("~cable", "")`.

### Datové struktury (`model/project.py`)
```python
@dataclass
class StructureId:
    aspect: str            # "=" funkce | "+" umístění
    code: str              # "AC", "RS1" – bez znaménka, jedna úroveň
    description: str = ""

# Sheet: func: str = "", loc: str = ""
# Project: structures: list[StructureId]; def structure(aspect, code) -> StructureId | None
```
Rezervované klíče atributů prvku: `func`, `loc` (doplnit do `LIBRARY_FORMAT.md` vedle `wire_id`, `cable_id`, `sheet`).

JSON v8:
```json
{
  "format": "envocad-project", "format_version": 8,
  "structures": [{"aspect": "=", "code": "AC", "description": "Střídavá část"},
                 {"aspect": "+", "code": "RDC1", "description": "DC rozvaděč"}],
  "sheets": [{"kind": "switchboard", "func": "", "loc": "RDC1", "...": "..."},
             {"kind": "schematic", "func": "", "loc": "",
              "elements": [{"symbol_id": "fve.pv_string", "attrs": {"ref": "G1", "loc": "STR"}}]}],
  "revisions": []
}
```

### Nový modul `model/designation.py` (bez Qt, bez importu `project` – duck typing)
```python
FUNC, LOC = "=", "+"
LOCATION_SYMBOLS = {"fve.switchboard"}          # prvky, jejichž ref je kód umístění
MAX_CODE_LEN = 10; MAX_REF_LEN = 10; MAX_FULL_LEN = 32
CODE_RE = re.compile(r"[A-Z][A-Z0-9_]*")
REF_CHARS_RE = re.compile(r"[A-Z0-9_]+")        # vodič smí začínat číslicí
SEPARATORS = set("=+-.:/") | whitespace

@dataclass(frozen=True)
class Designation:
    func: str = ""; loc: str = ""; ref: str = ""
    def __str__(self) -> str: ...   # "=AC+RS1-F3", prázdné části vynechá; jen ref → "-F3"

@dataclass(frozen=True)
class DesignationIssue:
    code: str      # ref_syntax | ref_chars | ref_length | ref_class | struct_syntax
    error: bool
    text: str      # česky

def parse_designation(text: str) -> Designation      # "=AC+RS1-F3", "+RS1-F3", "F3"; ValueError při víceúrovni
def letter_code(ref: str) -> str                     # "F3"→"F", "QA12"→"QA", "101"→""
def class_matches(ref: str, classes: list[str]) -> bool   # letter_code(ref).startswith(c) pro některé c
def validate_code(code: str, aspect: str) -> list[DesignationIssue]
def validate_ref(ref: str, classes: list[str] | None, *, is_wire: bool = False) -> list[DesignationIssue]
def designation(sheet, target) -> Designation        # efektivní func/loc (override → list), ref
def scope_key(sheet, target) -> tuple[str, str]      # (func, loc); anonymní rozvaděč ("", "#"+id); vodič JPS ("~cable", "")
def full_designation(project, sheet, target) -> str  # LOCATION_SYMBOLS → "=f+REF"
def display_designation(sheet, target) -> str        # do výkresu: jen části odlišné od listu + ref
```
`validate_ref`: oddělovač v ref („Q1-2“, „X1:3“, mezera) → ERROR `ref_syntax` (úvodní „-“: „Označení zadej bez „-““);
malá písmena / diakritika / jiný znak než `A–Z 0–9 _` → WARNING `ref_chars`; ref > `MAX_REF_LEN` nebo plné
označení > `MAX_FULL_LEN` → WARNING `ref_length`.

### Funkce v `project.py`
- `used_refs(sheet)`: ref ve stejném `scope_key` jako výchozí hodnoty listu.
- `next_ref(prefix)`: beze změny (globálně unikátní číslo je platné v každém scope).
- `create_switchboard_sheet(block)`: navíc `sheet.loc = block.ref` a registrace `StructureId("+", ref, desc)`.
- `rename_structure(project, aspect, old, new) -> int`: přejmenuje v `structures`, `Sheet.func/loc`, `attrs func/loc`;
  `ValueError`, když `new` existuje (→ přesně invertovatelné).
- Přejmenování bloku rozvaděče v UI = makro `SetAttrCommand(ref)` + `RenameStructureCommand("+", old, new)`.

### Unikátnost (`checks.py`)
- `dup_ref` klíč `(*scope_key(s, x), ref)`; výjimky jako dnes (kontakty, skupiny svorek).
- Dva listy se stejným `loc` sdílejí prostor (nové).
- `contacts_of` / `coil_of` zůstávají podle ref; nová kontrola `contact_ambiguous` (WARNING).

### Exporty (`export/reports.py`)
- `device_list`, `labels`: „Označení“ = `full_designation`, řazení `(func, loc, přirozené ref)`.
- `cables`, `terminals`, `wiring_list`: konce `+RDC1-X1:3`.
- Výkres: `display_designation` – bez overridu se popisky nemění.

## 2. Kontrola označení vs. funkce (EPLAN P017003)
- `iec_ref` zůstává prefixem auto-číslování; `function_class` = seznam povolených tříd (1–2 písmena).
- Výchozí: `[iec_ref]` je-li neprázdný, jinak `[]` (= nekontroluje se). Shoda prefixem: „F“ přijme F/FA/FC.
```python
# Symbol
    function_class: list[str] | None = None     # None = odvodit z iec_ref
    @property
    def classes(self) -> list[str]: ...
```
- `to_dict` zapíše klíč jen když není `None`. `validate`: třídy `^[A-Z]{1,2}$` a `class_matches(iec_ref + "1", classes)`.
- Explicitní `function_class` jen v 7 souborech:

| soubor | `iec_ref` | `function_class` |
|---|---|---|
| `fve/fve.breaker_mcb.json` | F | `["F","Q"]` |
| `fve/fve.breaker_mccb.json` | Q | `["Q","F"]` |
| `fve/fve.fuse_disconnect.json` | F | `["F","Q"]` |
| `fve/fve.contactor.json` | K | `["K","Q"]` |
| `switchboard/sb.rcd.json` | F | `["F","Q"]` |
| `switchboard/sb.rcbo.json` | F | `["F","Q"]` |
| `fve/fve.switchboard.json` | R | `[]` (umístění) |

(Pokud JSON generuje `tools/gen_builtin_fve.py`, upravit i generátor.)

Nová `designation_findings(project, lib)` volaná z `check_project`:

| kód | závažnost | příklad textu | na co |
|---|---|---|---|
| `ref_syntax` | ERROR | Označení „Q1-2“ obsahuje nepovolený znak „-“ (oddělovač aspektů) | prvky s neprázdnými třídami nebo blok, vodiče, skupiny svorek |
| `ref_chars` | WARNING | Označení „f3“: povolena jen velká písmena A–Z, číslice a _ | totéž |
| `ref_length` | WARNING | Označení „…“ je delší než 10 znaků / Plné označení … přesahuje 32 znaků (štítek) | totéž |
| `ref_class` | WARNING | Označení T1 neodpovídá funkci značky Jistič (povolené třídy: F, Q) | prvky s neprázdnými třídami; ne kontakty, ne vodiče |
| `struct_syntax` | ERROR | Umístění „RS 1“ listu X není platný kód (A–Z, 0–9, _, max. 10) | `structures`, `Sheet.func/loc`, `attrs func/loc` |
| `struct_undefined` | INFO | Umístění +STR není v seznamu struktur projektu | totéž |
| `sb_no_loc` | WARNING | List rozvaděče nemá umístění (+) | listy rozvaděčů s prázdným `loc` |
| `loc_mismatch` | INFO | Umístění listu +RS1 se liší od označení bloku RDC1 | listy rozvaděčů |
| `contact_ambiguous` | WARNING | Kontakt K1 odpovídá cívkám ve více umístěních (+RDC1, +RH) – nastav kontaktu umístění | kontakty |

Přerušovací body, kontakty a symboly s prázdnými třídami se na znaky nekontrolují. Vodiče jen syntaxe a délka.

## 5. Revize ve výkresu

### Data (`project.py`), logika v novém `model/revision.py`
```python
@dataclass
class RevisionMark:
    sheet_id: str
    target_id: str = ""       # "" = změna listu bez místa → jen popisové pole
    is_wire: bool = False
    kind: str = "změněno"     # přidáno | změněno | odebráno
    x: float | None = None    # pevná poloha – jen u odebraných
    y: float | None = None
    text: str = ""

@dataclass
class Revision:
    label: str
    date: str = ""; author: str = ""; description: str = ""
    closed: bool = False
    marks: list[RevisionMark]
    fingerprints: dict[str, str]   # sheet_id → otisk při uzavření listu
    id: str = field(default_factory=_uid)

# Project: revisions: list[Revision]
```
`diff.Change` + `sheet_id: str = ""`, `x/y: float | None = None`. Odebraný prvek → poloha starého prvku; odebraný
vodič → střed (lomy, jinak střed konců); odebraný list / kabel → bez značky; `můstky` → `target_id` svorkovnice se
stejným ref; `skříň`, nový/přejmenovaný list → značka listu (`target_id=""`). Pouhý „posun ve výkresu“ značku
nevytváří (`MARK_MOVES = False`). `diff_projects` porovnává i `Sheet.func/loc`.

### `model/revision.py`
```python
def marks_from_changes(changes) -> list[RevisionMark]      # dedup (sheet, target)
def open_revision(project, label, date, author) -> Revision # poslední otevřená, jinak nová
def apply_changes(project, rev, changes) -> None            # nahradí značky (idempotentní), kromě listů s otiskem;
                                                            # meta["revision"] = rev.label
def close_revision(project, rev, sheet_ids=None) -> None    # None = celá (otisky + closed=True)
def sheet_revision(project, sheet) -> Revision | None       # poslední se značkou na listu, jinak první
def changed_after_close(project) -> list[tuple[Sheet, Revision]]
def revision_geometry(project, sheet, lib, routes=None, revision=None) -> RevisionGeometry
```
`diff.sheet_fingerprint(sheet) -> str`: sha1 kanonického JSON ze stejných údajů, jaké porovnává `diff_projects`.

### Geometrie
```python
@dataclass
class RevisionGeometry:
    polylines: list[list[tuple[float, float]]]          # uzavřené trojúhelníky
    texts: list[tuple[float, float, str, float, str]]   # jako FrameGeometry.texts
def triangle(x, y, label)   # rovnostranný, vrchol nahoru, strana max(6, 1,6·len(label)+3) mm, text 2,5 mm center
```
Poloha: prvek – pravý horní roh obálky otočené značky + 2,5 mm, na mřížce 2,5 mm; vodič – střed nejdelšího úseku
trasy (`routes` z `compute_layout`, jinak `points`/porty); odebrané – uložené x, y.
Kreslení: Qt `ui/render.draw_revision_marks`; DXF vrstva `REVIZE` (červená). Vícepól ne. Obláček ne (YAGNI).

### Popisové pole (`frame.py`)
`title_rows` a `qr_text`: revize = `sheet_revision(project, sheet).label`, jinak `meta["revision"]`.
`meta["revision"]` (celá dokumentace) a `meta["changes"]` zůstávají.

### Uzavření = měkký zámek
Uloží otisky, zmrazí značky; další porovnání založí novou revizi. Kontrola `rev_closed_changed` (WARNING):
„List změněn po uzavření revize B – porovnej s revizí a založ novou“. Editaci model neblokuje.

## Migrace v7 → v8
```python
if ver < 8:
    sheets = d.get("sheets", [])
    el_by_id = {e["id"]: e for s in sheets for e in s.get("elements", [])}
    structs = d.setdefault("structures", [])
    for s in sheets:
        s.setdefault("func", "")
        loc = ""
        if s.get("kind") == "switchboard":
            blk = el_by_id.get(s.get("parent_element_id") or "")
            loc = ((blk or {}).get("attrs") or {}).get("ref", "")   # beze změny textu, nevalidní ohlásí kontrola
            if loc and not any(x["aspect"] == "+" and x["code"] == loc for x in structs):
                structs.append({"aspect": "+", "code": loc, "description": (blk.get("attrs") or {}).get("desc", "")})
        s.setdefault("loc", loc)
    if not d.get("revisions"):
        # meta["changes"] řádky "rev | datum | popis | zpracoval" → jedna uzavřená Revision na label (pořadí výskytu),
        # bez značek a otisků; meta["revision"] mimo seznam → poslední, otevřená
        d["revisions"] = _revisions_from_meta(d.get("meta", {}))
```
Dva bloky se stejným ref sloučí prostory – zamýšlené (dup_ref je hlásí už dnes).

## Undo (`ui/commands.py`)
- `SetSheetDesignationCommand(sheet, old, new)` – `(func, loc)` listu.
- `RenameStructureCommand(project, aspect, old, new)` – redo/undo přes `rename_structure`.
- `SetStructuresCommand(project, old_list, new_list)` – dialog „Projekt → Strukturní označení“.
- Override prvku: stávající `SetAttrCommand` (`func`/`loc`).
- `ReplaceRevisionsCommand(project, old_revs, new_revs, old_meta, new_meta)` – `compare_revision` (místo
  `resetClean`) a „Uzavřít revizi / list“.

## Pořadí implementace
1. `designation.py` + testy. 2. `Symbol.function_class` + 7 JSON + `LIBRARY_FORMAT.md`.
3. `project.py` (třídy, serializace, v8, migrace, `create_switchboard_sheet`, `used_refs`, `rename_structure`).
4. `checks.py` (scope, `designation_findings`). 5. `reports.py`. 6. `diff.py`. 7. `revision.py`, `frame.py`, DXF,
`rev_closed_changed`. 8. UI. 9. Dokumentace.

## YAGNI (nedělat)
Víceúrovňové aspekty; override na vodičích; `next_ref` per scope; párování kontaktů podle plného označení;
verze formátu symbolu; obláček, značky ve vícepólu, tvrdý zámek, generování `meta["changes"]` z `revisions`.
