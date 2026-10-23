# Příkazový řádek (styl ZWCAD/CADCraft) – návrh

Stav: **fáze 1 hotová** (jádro `envocad/cmd`, skripty, CLI); fáze 2 (dok v GUI) a 3 čekají. Roadmapa v0.1: „každá akce = příkaz, ovladatelné i z agentů“. Formát projektu se
**nemění** (`FORMAT_VERSION` zůstává 16); nové jsou jen soubory skriptů `.ecs` a uživatelské aliasy.

## 1. Vrstvy (rozhodnutí)
```
envocad/cmd/            bez Qt (hlídá test jako model/), headless, pro GUI, CLI, agenty i pluginy
  registry.py  CommandDef, Param, Registry (jména, aliasy, české názvy, doplňování)
  parse.py     tokenizace (shlex), body „x,y“ / „@dx,dy“, key=value, čísla
  runner.py    CommandRunner – vykoná příkaz jako generátor výzev, vrací ChangeSet
  edits.py     primitivní změny modelu (vložit, smazat, posunout, otočit, zrcadlit, atribut, vodič) nad model/
  builtin.py   vestavěné příkazy;  script.py  .ecs;  __main__.py  CLI;  aliases.json  výchozí aliasy
envocad/ui/command_line.py   dok „Příkazový řádek“ (QLineEdit + výstup), napojení na canvas a QUndoStack
```
Název `cmd`, ne `commands` – `ui/commands.py` (QUndoCommand) by se pletl.

```python
@dataclass(frozen=True)
class Param:  name: str; kind: Literal["point","selection","number","text","symbol","choice","kv"]
              prompt: str; optional: bool = False; choices: tuple[str, ...] = ()
@dataclass
class CommandDef:
    name: str                      # kanonické id = id akce v MainWindow.actions („rotate“, „export_pdf“)
    title: str                     # česky pro výstup a paletu („Otočit o 90°“)
    aliases: tuple[str, ...] = ()  # „RO“, „OTOCIT“ (porovnání bez diakritiky a velikosti písmen)
    params: tuple[Param, ...] = ()
    run: Callable[[Ctx], Generator[Prompt, Any, str | None]] | None = None   # None = jen GUI akce
    gui_fallback: str | None = None   # bez argumentů v GUI spustit existující akci/režim (WIRE → Mode.WIRE)
    needs_gui: bool = False           # dialogy, pohledy – headless hlásí „jen v GUI“
@dataclass
class Ctx:  project: Project; library: object; sheet: Sheet | None; selection: list[str]; log: Callable
@dataclass
class ChangeSet:  label: str; before: dict; after: dict      # sheets_state – jen změněné listy
```
Příkaz je **generátor výzev**: `base = yield Point("Základní bod:")`. Ovladač (GUI nebo skript) dodá hodnotu
z argumentů řádku, z klávesnice nebo kliknutím. Změny dělá příkaz na projektu přes `edits.py`; runner zabalí běh do
transakce (`sheets_state` před/po) a vrátí `ChangeSet`. Esc/chyba uprostřed → stav „před“ se vrátí, nic nezůstane.

## 2. Undo – jak sladit headless a QUndoCommand
- `sheets_state` / `restore_sheets_state` se přesunou z `ui/commands.py` do `model/project.py` (jsou čisté).
- **GUI**: `ChangeSet` → `undo.push(SheetsStateCommand(project, before, after, label, on_change=…))` – každá změna z
  řádku je jeden `QUndoCommand` (CLAUDE.md ✓), Ctrl+Z funguje stejně. Runner pracuje na živém projektu, příkaz pak
  stav „po“ jen znovu nastaví (první `redo` beze změny, jako `MoveElementsCommand`). `on_change` přestaví pohledy
  změněných listů; `restore_state` drží identitu nezměněných prvků → později levná inkrementální obnova scény.
- **Headless**: `Journal` = seznam ChangeSetů; skript umí `UNDO`/`REDO` (agent může krok vrátit).
- Navázané změny (přívody/vývody, `rename_followups` u `SET ref=`) volá `edits.py` stejnými funkcemi modelu jako
  `ui/commands.py`. Shodu hlídá test parity (stejný `to_dict` po příkazu z řádku i po QUndoCommand z myši).
- Odvozená data (`sync_cables`, `sync_feed_link_attrs`) GUI dopočítá po změně jako dnes; CLI před uložením.

Zamítnuto: **(a)** headless přes `ui/commands.py` s falešnou scénou – implicitní kontrakt scény (`element_items`,
`route_wire`…), Qt v cestě agentů, každý nový příkaz ji tiše rozbije. **(b)** vlastní model-level `Edit.apply/revert`
pro každou operaci a přepis 30 QUndoCommandů – správné dlouhodobě, ale velký refaktor bez přínosu pro v0.1.
**(c)** headless mění model a GUI má zvlášť vlastní kód – dvě implementace, rozjedou se. **(d)** snímek celého
projektu – zbytečně drahé, listy stačí (meta/revize mají vlastní dialogy a příkazy, z řádku je v0.1 nemění).
Cena zvolené cesty: kopie změněných listů v undo zásobníku a přestavba scény listu; při ~stovkách prvků přijatelné.

## 3. GUI
- Dok dole (`QDockWidget` „Příkazový řádek“, `objectName` pro `saveState`): 3 řádky výstupu (`QPlainTextEdit`
  jen čtení, F2 rozbalí historii) + výzva vlevo („Příkaz:“, „Základní bod:“) + `QLineEdit`. Výstup i do logu
  `envocad.cmd`. Chyby česky červeně („Neznámý příkaz „XY“ – Tab doplní“).
- Klávesy: **Enter/mezera** potvrdí (mezera ne uvnitř uvozovek a ve výzvě typu text); **Enter na prázdném řádku**
  zopakuje poslední příkaz; **Esc** zruší běžící příkaz (a vrátí canvas do `Mode.SELECT`); **↑/↓** historie (relace,
  posledních 200 i do `~/.envocad/cmd_history.txt`); **Tab** doplní (`Registry.complete(text, ctx)` bez Qt: jména,
  aliasy, české názvy, u INSERT id značek z knihovny, u SET klíče atributů výběru) – víc shod = popup `QCompleter`.
- Psaní z canvasu: tisknutelná klávesa, kterou nezachytí zkratka, jde do řádku (fokus + znak). Jednopísmenné zkratky
  (R, M, N, T, W) dnes vyhrají – volba v nastavení `cmdline_keys`: „envocad“ (dnešní zkratky, výchozí) / „zwcad“
  (všechna písmena do řádku, M = MOVE). Viz otázka 1.
- Výzvy a myš: nový `Mode.PICK` v `canvas.py` – klik pošle bod (snap 2,5 mm, převod Y nahoru) do runneru, gumová
  čára od základního bodu. Výzva `selection`: platí aktuální výběr, jinak se vybírá myší a Enter potvrdí. `point`
  zadaný textem se nekreslí přes režim. `gui_fallback`: WIRE/INSERT bez argumentů spustí dnešní `Mode.WIRE` /
  `start_place` (ghost, dialog atributů) – interaktivní kreslení se nepřepisuje.
- Stavový řádek beze změny; souřadnice kurzoru (`_show_cursor`) jsou ve stejné soustavě jako vstup řádku.

## 4. Syntaxe a vestavěné příkazy
Řádek = `PŘÍKAZ arg arg …` (shlex, uvozovky pro mezery). Chybějící argumenty se doptají výzvou.
- Bod: `x,y` absolutně v mm na listu (počátek levý dolní roh, Y nahoru), `@dx,dy` relativně k poslednímu bodu,
  `ref:port` (`F1:2`) = poloha portu. Desetinná **tečka** (čárka dělí souřadnice), viz otázka 3. Prvky se
  zaokrouhlí na mřížku 2,5 mm (výstup to oznámí), porty tak zůstanou na mřížce.
- Výběr (headless i GUI): `SELECT F1 F2 Q*` (ref, glob), `SELECT all`, `SELECT W x1,y1 x2,y2` (okno), `SELECT none`.

| Příkaz | Aliasy (CZ) | Výzvy / argumenty |
|---|---|---|
| `insert` | I, VLOZIT | id značky → bod (`INSERT fve.breaker_mcb 50,100`), volitelně `ref=F1 rot=90` |
| `wire` | W, VODIC | port A → port B (`WIRE F1:2 Q1:1`; bod = nejbližší port do 2,5 mm) |
| `move` | M*, POSUN | výběr → základní bod → cílový bod |
| `copy` | CO, CP, KOPIE | výběr → základní → cílový (kopie přes `copy_fragment`, nová `ref`) |
| `rotate` | RO, OTOCIT | výběr → úhel (násobek 90, výchozí 90) |
| `mirror` | MI, ZRCADLIT | výběr |
| `delete` | E, DEL, SMAZAT | výběr |
| `set` | ATTR, ATR, NASTAVIT | `key=value …` na výběr (`SET ref=F1`, `ATTR in_a=16` – klíče podle značky) |
| `sheet` | LIST | název nebo pořadí listu (aktivní list) |
| `zoom` | Z (+ ZE = rozsah, ZA = vše → `fit`) | GUI-only |
| `checks` | F7, KONTROLA | headless vypíše nálezy `checks.check_project` |
| `undo`/`redo`, `save`, `export_dxf`/`export_pdf` | U, ULOZ | cesta jako argument; PDF headless s offscreen Qt |
| `script` | SCR, SKRIPT | soubor `.ecs` (vnoření max. 4) |
\*M = MOVE jen v řádku (ZWCAD); klávesa M na canvasu zůstává Zrcadlit (otázka 1).

## 5. QAction a pluginy
- Po `_build_actions` + načtení pluginů projde `MainWindow` `self.actions`: chybí-li `CommandDef` se jménem id akce,
  zaregistruje se GUI-only příkaz (`title` = text akce bez „&“ a „…“, spuštění = `action.trigger()`; zašedlá akce →
  „Příkaz teď není dostupný“). Existuje-li headless `run`, má přednost; akce zůstane jako `gui_fallback`.
  Menu položky bez id příkaz nedostanou – doplnit id (`act(..., key=…)`) postupně; test hlídá, že každé id je příkaz.
- Paleta Ctrl+K zůstane; nově zobrazí i jméno/alias příkazu („Otočit o 90° · RO“), `_norm` se přesune do `cmd/`.
- Plugin: `ctx.add_command(CommandDef)` v `PluginContext` – transakčně jako `add_menu_action`; kolize jména
  s vestavěným → chyba registrace pluginu. Aliasy: `envocad/cmd/aliases.json` + uživatelské
  `~/.envocad/aliases.json` (obdoba `acad.pgp`; přepisují, nemažou kanonická jména).

## 6. Skripty a agenti
- `.ecs` = UTF-8 text, řádek = příkaz, `#` komentář, prázdné řádky se přeskočí. Argumenty musí pokrýt všechny výzvy
  (jinak chyba „řádek 7: MOVE – chybí Cílový bod“). Volitelné `--var name=value` → `${name}` (jen textové dosazení).
- CLI: `python -m envocad.cmd projekt.ecp skript.ecs [-o vystup.ecp | --in-place] [--dry-run] [--json] [--keep-going]`;
  `-` = skript ze stdin. Bez `-o`/`--in-place` se nic neuloží (bezpečný výchozí stav pro agenty). `--json` = řádek
  na příkaz `{"line", "cmd", "ok", "messages", "changed_sheets"}`. Kód návratu 0 / 1 chyba příkazu / 2 použití.
  Před uložením `sync_cables` a kontrola F7 do výstupu. Konec při první chybě (bez uložení), `--keep-going` pokračuje.
- GUI: Soubor → „Spustit skript…“ = celý skript jako jedno makro undo (`beginMacro`), výstup do doku, Esc přeruší
  (vrátí se i hotové řádky).
- Bezpečnost: žádný `eval`/`exec`/shell; jen registrované příkazy, hodnoty jsou řetězce/čísla parsované explicitně.
  Cesty (SAVE, EXPORT, SCRIPT) relativně ke složce skriptu; přepis existujícího souboru jen s `--in-place`/`-o`.
  Kód spouští jen pluginy (už dnes důvěryhodné), skript ne.

## 7. Testy
- `test_cmd_parse`: body (`@`, `ref:port`, mřížka), uvozovky, aliasy bez diakritiky, Tab doplňování.
- `test_cmd_exec` (headless): INSERT/MOVE/COPY/ROTATE/MIRROR/DELETE/SET/WIRE; Esc uprostřed nic nemění;
  `UNDO` vrátí `to_dict` přesně; `SET ref=` přejmenuje navázané texty.
- `test_cmd_parity` (offscreen): příkaz z řádku = stejný výsledek jako QUndoCommand z myši/akce.
- `test_cmd_script`: CLI subprocess, `--json`, čísla řádků chyb, `__import__('os')` je jen neznámý příkaz.
- `test_cmd_gui`: „RO 90“+Enter otočí výběr, Ctrl+Z jedním krokem vrátí; Enter opakuje; Esc ruší; klik v `Mode.PICK`.
- Čistota: `envocad/cmd` bez importu Qt (rozšířit AST test); každé id z `self.actions` je registrovaný příkaz.

## 8. Fáze
1. `cmd/` jádro: registry, parse, runner, edits, SELECT/INSERT/MOVE/ROTATE/MIRROR/DELETE/SET/WIRE/SHEET/UNDO/SAVE +
   CLI `.ecs` (hodnota pro agenty hned, bez GUI). ~2 d.
2. Dok v GUI, ChangeSet → `SheetsStateCommand`, `Mode.PICK`, historie, Enter/mezera/Esc, Tab, akce → příkazy. ~2 d.
3. Pluginy `add_command`, uživatelské aliasy, „Spustit skript…“, COPY, CHECKS, EXPORT. ~1 d.
4. Až bude třeba: inkrementální obnova scény místo přestavby, režim kláves „zwcad“.

YAGNI (záměrně ne): polární souřadnice `@d<úhel`, objektový snap mimo porty, LISP/proměnné/podmínky ve skriptu,
dynamický vstup u kurzoru, vícepól/rozložení z řádku (v0.1 jen JPS a schéma rozvaděče), makra záznamem.

## Rozhodnutí (Patrik, 2026-10-22)
1. Klávesy: volba v nastavení (`cmdline_keys`), **výchozí „zwcad“** – psaní ve výkresu jde do řádku, aliasy jako ZWCAD;
   dnešní jednoklávesové zkratky (M zrcadlit, R otočit, W vodič…) jde zapnout volbou „envocad“.
2. Aliasy: standardní ZWCAD/AutoCAD (acad.pgp: L, M, CO, RO, MI, E, Z, TR…), uživatelské v `~/.envocad/aliases.json`.
3. Mezerník = Enter (mimo textové výzvy a uvozovky).
4. CLI bez `-o` / `--in-place` neukládá.
5. (výchozí orchestrátora) Desetinná tečka v souřadnicích „x,y“; počátek = počátek souřadnic listu (levý dolní roh,
   jako model); české názvy příkazů jako aliasy (VLOZIT, POSUN, OTOCIT…), výzvy česky, klíče atributů beze změny;
   rozsah v0.1: list JPS / blokové schéma a list rozvaděče (vícepól a rozložení později).
6. (Patrik, 2026-10-23) **L = WIRE** (EnvoCAD nemá volné úsečky). **ROTATE jako v ZWCAD**: s výběrem a základním
   bodem otáčí kolem bodu; jeden prvek bez bodu kolem svého počátku.
