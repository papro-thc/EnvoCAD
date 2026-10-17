# EnvoCAD – architektura

Interní nástroj ENVO pro elektro-dokumentaci FVE (a později dalších oborů).
Náhrada EPLAN pro naše potřeby: jednopólová schémata, rozvaděče, výkazy, vlastní knihovna prvků.

## Technologický stack a proč

| Vrstva | Volba | Důvod |
|---|---|---|
| Jazyk | Python 3.11+ | Agenti ho píší nejspolehlivěji, snadná údržba bez profi vývojáře |
| GUI | PySide6 (Qt 6) | Cross-platform Windows/Linux, `QGraphicsScene` je přímo stavěná na 2D editory schémat (zoom, výběr, hit-test, undo) |
| DXF | ezdxf | Zralá knihovna pro čtení/zápis DXF (import symbolů od výrobců, export do ZWCAD) |
| Úložiště knihovny | SQLite (+ JSON soubory symbolů v gitu) | Bez serveru, jeden soubor, později lze přepnout na PostgreSQL pro sdílení v ENVO |
| Formát projektu | JSON (`.ecp`) | Čitelné, diffovatelné v gitu, snadno strojově generovatelné |
| Balení | PyInstaller | Jeden .exe / AppImage |

Zvažované a zamítnuté: Tauri/Electron (slabší DXF ekosystém v JS, složitější build), nadstavba nad ZWCAD (vendor lock-in, nelze provozovat bez licence ZWCAD).

## Vrstvy

```
envocad/
  model/      čistá data, žádné Qt  → testovatelné headless
    symbol.py   Symbol = grafická primitiva + porty + atributy
    project.py  Project → Sheet → Element (instance symbolu) + Wire
  library/    knihovna prvků
    store.py       SQLite úložiště symbolů a komponent (artiklů)
    dxf_import.py  DXF → Symbol
    builtin/       startovní symboly (JSON), verzované v gitu
  ui/         PySide6 GUI (nikdy neobsahuje business logiku)
    canvas.py       QGraphicsView – mřížka, zoom, snap
    items.py        QGraphicsItem obaly nad Element/Wire
    main_window.py  okno, panely, akce
  export/     DXF, PDF, (později výkaz materiálu .xlsx)
```

Zásada: **model nezávisí na UI.** Vše, co lze, se testuje bez spuštění Qt.

## Klíčové pojmy

- **Symbol** – grafická definice (čáry, kružnice, oblouky, texty) v jednotkách mm na mřížce 2,5 mm,
  s pojmenovanými **porty** (připojovací body) a sadou **atributů** (označení, typ, Un, In…).
  Nezávislý na konkrétním výrobku.
- **Komponenta (artikl)** – konkrétní výrobek (např. `SMA STP 50-40`) s parametry a odkazem na symbol.
  Jeden symbol střídače → stovky artiklů.
- **Element** – instance symbolu na listu: pozice, rotace, hodnoty atributů, volitelně přiřazený artikl.
- **Wire** – vodič mezi dvěma porty (element.port → element.port), má atributy (průřez, typ kabelu, označení).
- **Sheet** – list výkresu (formát, rámeček, popisové pole).
- **Project** – zakázka: metadata (název, investor, číslo zakázky), seznam listů.
- **Struktura (IEC 81346)** – `=` funkce, `+` umístění, `-` přístroj. Registr kódů `Project.structures`
  (`StructureId`: aspekt, kód, popis; kód mimo registr je platný, kontrola jen hlásí INFO). `Sheet.func` a
  `Sheet.loc` jsou výchozí aspekty prvků listu; prvek může přepsat `attrs["func"]` / `attrs["loc"]` (prázdné =
  dědit). `attrs["ref"]` je jen přístrojová část („F3“). Plné označení („=AC+RDC1-F3“) skládá
  `model/designation.py` – používají ho výkazy a štítky; list rozvaděče má `+` = označení bloku.
- **Revize** – `Project.revisions` (`Revision`: označení, datum, zpracoval, otisky listů při uzavření, značky
  `RevisionMark` na listu, prvku nebo vodiči). Značky vznikají z porovnání `model/diff.py` přes `model/revision.py`;
  kreslí se v editoru, PDF a DXF (vrstva `REVIZE`) a revizi listu ukazuje popisové pole. **Uzavření revize je měkký
  zámek**: uloží otisky listů; další změna listu jen hlásí kontrola (`rev_closed_changed`), model ji neblokuje.
- **Připomínky (redlining)** – `Project.notes` (`Note`: list, bod nebo obdélník v mm, text, autor, stav
  otevřeno/vyřešeno, odpověď). Interní poznámky, nejsou součástí dokumentace: `diff_projects` ani
  `sheet_fingerprint` je nevidí, do obsahu PDF se nevypalují. Pomocné funkce a geometrie `model/notes.py`, kontrola
  `note_findings`, DXF vrstva `PRIPOMINKY` (volitelně), PDF anotace `export/pdf_annots.py` (pypdf). Návrh
  `docs/design/pripominky.md`.
- **Přístroj a křížové odkazy** (`model/xref.py`) – přístroj = skupina prvků se stejným `ref` v jednom prostoru
  označení (`DeviceIndex.build(project)`, O(N), hostitel = cívka, jinak první prvek). Přes skupinu se počítají
  kontakty (`contacts`, zrcadlo pod hostitelem), stykač s cívkou a přerušovací body (dvojice, řetěz, hvězda).
  Čistá data bez Qt; návrh v `docs/design/xref_zrcadleni_kontaktu.md`.
- **Výrobní data rozvaděče** (`model/wiring.py`) – výrobní zapojovací seznam pro dílnu: každá žíla vnitřního vodiče
  listu rozvaděče s průřezem (`wire_cross`: atribut, nejmenší In přístrojů přes `IN_TO_CROSS`, řízení, minimum),
  barvou (`conductor_color`), typem, koncovkou (`end_for`, dutinky `FERRULE_DIN46228`, dvojitá při dvou žilách ve
  svorce stejného průřezu) a délkou z rozložení. Svorky a texty konců `conductor_end` (sdílí i zapojovací seznam
  listu rozvaděče): ruční `Wire.terminals`, sběrnice jako potenciál („+RDC1-1L1“), svorkový prvek, pravidlo pro
  přístroje s porty 1/2 (`multipole.device_terminal`: pól k → 2k+1 / 2k+2, spínaný N 4p = 7/8), jinak port (s více
  žilami „F1:L1“). Nespínané N/PE vedené v JPS přes přístroj se slučují do jednoho řádku („vede kolem Q1“). Poloha svorky `terminal_point` (mm, Y nahoru, počátek levý
  horní roh montážní plochy, osa řady `-(r+0,5)·P`, žlab j na `-j·P`, výška přístroje `DEVICE_HEIGHT_MM`; cívka a
  kontakty přes umístěný stykač `xref.DeviceIndex`; neumístěné svorky/sběrnice odhadem), délka `route_length_mm` po
  žlabech (+ konce, rezerva, zaokrouhlení). Parametry `WiringParams.resolve` (kód < `standard.wiring` < `Layout.params`
  `wire_*`). `production_wires` vrací typované `ProductionWire` – rozhraní i pro budoucí exporty strojů
  (`export/machine_<výrobce>.py`). Výkaz `reports.production_wiring_list` (není v PDF dokumentaci – `NOT_IN_DOC`),
  xlsx pro dílnu `xlsx_export.export_production_xlsx`. Formát projektu se nemění; návrh `docs/design/vyrobni_data.md`.

Z tohoto modelu se generuje vše ostatní (výkaz materiálu, seznam kabelů, svorkovnice) – to je hlavní
přidaná hodnota oproti ručnímu kreslení v ZWCAD.

## Souřadnice a jednotky

- Model i symboly v **mm**, Y nahoru jako v CADu (ve scéně Qt se jen převrátí osa).
- Mřížka 2,5 mm (jako EPLAN), snap na mřížku standardně zapnutý.
- Porty symbolů musí ležet na mřížce.

## Formát symbolu (JSON)

Viz `docs/LIBRARY_FORMAT.md`.

## Undo/redo

`QUndoStack` v UI; každá změna modelu je `QUndoCommand` (přidat/smazat/posunout element, přidat vodič,
změnit atribut). Model sám o undo neví. Operace nad projektem mají vlastní příkazy (`ui/commands.py`): přidání a
smazání listu (`AddSheetCommand`, `DeleteSheetCommand` – vrací i odpojené listy rozvaděčů a atribut „sheet“ bloku,
záložky listu se zavřou / obnoví), šablona rozvaděče (`SheetsStateCommand` – snímek změněných listů), vlastnosti
projektu (`SetProjectMetaCommand`), skříň (`SetLayoutCommand` – snímek `Layout.to_dict`, po sobě jdoucí změny
téhož pole panelu se slučují; dialog skříně pracuje na kopii). `undo.clear()` / `undo.resetClean()` smí GUI volat
jen při načtení projektu, po založení nového projektu z průvodce / specifikace a po obnově autosave (hlídá test
`test_no_undo_reset_outside_allowed_places` – všechna volání v `ui/` včetně lambd a aliasů undo stacku). Zmenšení počtu řad skříně umístění nemaže: umístění v řadě mimo skříň
zůstane v modelu (`Layout.stored_placement`), `Layout.placement` ho nevrací (přístroj je nerozmístěný) a kontrola
hlásí `outside_enclosure`. Zmenšení počtu modulů v řadě také nic nemaže – přístroje za koncem řady a překryvy hlásí
kontrola `layout_overflow` / `layout_overlap` (`checks.layout_problems`, varování i v panelu skříně). Kabely
(`Cable`) jsou odvozené z vodičů JPS (`sync_cables`): kabel bez vodiče se odebere do `Project.removed_cables`
(neukládá se) a vrácený vodič (undo/redo) dostane týž kabel zpět – undo vložení/smazání vodiče vrátí `to_dict` přesně. Kabel osiřelý už v načteném souboru (`Project.loaded_orphan_cables`) se při otevření neodebere (ruční barvy žil, artikl); kontrola ho hlásí jako INFO `cable_no_wire`.

## Rozšiřitelnost na další obory

Nic v modelu není specifické pro FVE – „FVE“ je jen sada symbolů, šablon listů a generátorů výstupů.
Další obor = další složka v `library/builtin/` + případně vlastní exportní šablony.

## Jednopól ↔ vícepól (implementováno v `model/multipole.py` + `ui/multipole_view.py`)

Jeden model, dva pohledy nad stejnými daty:

- **Jednopólové schéma (JPS)** – kreslí se první. `Wire` je jedna čára, ale nese `conductors`
  (např. `["L1","L2","L3","N","PE"]`) a `Element` má `poles`.
- **Vícepólové schéma** – odvozený pohled: každá žíla z `conductors` se rozkreslí jako samostatná čára
  mezi póly přístrojů (pól = port + index žíly). Uživatel zde přiřazuje svorky: `Wire.terminals[žíla] =
  {"a": "X1:3", "b": "F2:1"}`. Nic se nekopíruje – změna typu kabelu v JPS se projeví i ve vícepólu a naopak.
- Přepínání pohledu = jiný `QGraphicsScene` nad stejným `Sheet`; symboly pro vícepól se generují z jednopólových
  (N× opakovaný pólový symbol + společná spoušť), vlastní vícepólové symboly v knihovně jsou volitelné.
- Svorkovnice a seznam kabelů se generují z `Wire.conductors` + `Wire.terminals`.
- Geometrie vícepólu (rozmístění `auto_layout`, stránkování `paginate`, popisky přístrojů `pole_label_lines`, trasy
  žil `conductor_route`, příčka PE svodiče `pe_join_segments`) je v `model/multipole.py`; `model/multipole_geometry.py`
  z ní bez Qt skládá texty a čáry celého pohledu a rozmisťuje popisky žil mimo cizí čáry – stejné polohy kreslí scéna
  (`ui/multipole_view.py`) a kontroluje F7 (`mp_text_overlap`). Se zapnutým rámečkem posune automaticky rozmístěné
  prvky strany nahoru mimo popisové pole s QR kódem; výsledné polohy (`MultipoleGeometry.origins`) přebírá scéna.
- Plán svorkovnice: data `model/terminal_plan.py:terminal_plan`, rozmístění na strany `layout_plan_pages` (pásy,
  svorkovnice vedle sebe, zalomení dlouhé, další strana) – scéna `ui/terminal_plan_view.py` má `pages` jako vícepól.

## Modularita a rozšiřování

Tři vrstvy rozšíření, od nejjednodušší:

1. **Data bez kódu** – knihovna je jen soubory. `~/.envocad/library/<balíček>/` (Windows
   `C:\Users\<jméno>\.envocad\library\`) může obsahovat libovolné podsložky se značkami `*.json`
   (formát `docs/LIBRARY_FORMAT.md`) a artikly `*.csv` (`docs/COMPONENTS.md`). Načtou se při startu, změny
   podle data souboru. Firemní sdílená knihovna = tato složka na síťovém disku (nebo git repozitář).
2. **Importéry** – `library/dxf_import.py`, `qet_import.py`, `eplan_import.py` převádějí cizí formáty na (1).
   Nový formát = nový modul se stejným rozhraním (vstup → `Symbol` / řádky CSV).
3. **Pluginy** – `~/.envocad/plugins/*.py` s `register(ctx)` (`envocad/plugins.py`): položky menu, šablony
   rozvaděčů, importéry v menu, vlastní výkazy. Vzor: `envocad/plugins_builtin/example_counts.py`.
   Budoucí obory (HVAC, MaR, silnoproud budov) = balíček knihovny + plugin se šablonami a výkazy, jádro se nemění.

Formát projektu (`.ecp`) je verzovaný (`FORMAT_VERSION` + migrace, aktuálně **9** – připomínky `Project.notes`;
v8 přidala strukturní označení a revize v `Project`, `Sheet.func/loc`; migrace v `model/project.py:migrate`), takže
rozšíření modelu nerozbije staré soubory. Načítání validuje strukturu (`Project.from_dict` → `CorruptProjectError`, česky „Soubor je poškozen: list X,
prvek Y – …“; vstupní slovník se nemění), odkazy uvnitř projektu ale nevaliduje: vodič na neexistující prvek se načte,
editor ho nekreslí, kontroly/výkazy/exporty pracují nad `without_dangling(project)` a kontrola ho hlásí (`dangling`).
`element_symbol` nikdy nepadá: neznámé `symbol_id` → zástupná značka „?“ (`Symbol.placeholder`, kontrola `symbol`),
port, na který vede vodič a značka ho nemá → osiřelý port „X1?“ (`Symbol.orphan_ports`, kontrola `bad_port`).
`Project.save` je atomický (`.tmp` + `os.replace`) a nechává zálohu `<název>.ecp.bak`; nový soubor převezme oprávnění
původního a symbolický odkaz zůstane odkazem (zapisuje se do jeho cíle). Ručně zkopírovaný list (duplicitní id)
dostane při načtení nová id i s přepsáním odkazů (konce vodičů, umístění, list rozvaděče, vazby přívodů).

Autosave (`ui/main_window.py`): okno maže jen kopie, které samo zapsalo nebo obnovilo (`_last_autosave`,
`_recovered_autosave`), a to až po uložení, po zahození změn a úspěšném otevření jiného projektu nebo po zavření.
Obnovená kopie zůstává na disku do prvního nového autosave okna; „Ne“ v nabídce obnovy kopii přesune do
`autosave/odmitnute/` (nenabízí se znovu, maže se po 30 dnech).
