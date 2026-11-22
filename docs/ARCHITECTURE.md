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
    topology.py Topologie připojení (řetězec článků, obor-nezávislé role) – docs/design/topologie_f1_f2.md
  library/    knihovna prvků
    store.py       SQLite úložiště symbolů a komponent (artiklů)
    dxf_import.py  DXF → Symbol
    topologies.py  presety topologií (builtin/topologies, sdílená, ~/.envocad/topologies) – jako makra
    builtin/       startovní symboly (JSON), verzované v gitu
  generate.py   tenký re-export generátoru (build_project, DEFAULT_SPEC…) + CLI `python -m envocad.generate`
  generator/  generátor FVE podle topologie (bez Qt; docs/design/topologie_f1_f2.md, kap. 1.3)
    context.py   knihovna sestavení (`_lib`, `_BUILD_LIB` – patch v testech jen zde), převody, konstanty, logger
                 "envocad.generate"
    spec.py      DEFAULT_SPEC, BUILDINGS/building_kind, parse_*, load_spec, artikly, select_topology, chain_text
    build.py     build_project: specifikace → select_topology → pv.plan → chain.create_main_block → pv.build →
                 chain.build
    pv.py        plan (pracovní souřadnice řad) a build (střídače, stringy, DC rozvaděče, DC/AC vodiče, baterie)
    chain.py     průchod topology.nodes přes registr BOARD_BUILDERS: 1. bloky (`block`) a vodiče mezi články
                 (`link` – kabel `chain.<role>.*`, stávající úsek bez údajů a HDS → DS bez kabelu, nový bez průřezu
                 `calc.min_cross`), 2. listy (`build`); HOP, zarovnání – řetězec stávajících článků svisle (firma pod
                 RFVE.AC `layout._chain_column`, RD vpravo `layout._house_column`) nebo v řadě; volba podle hodnocení
                 (`_choose_chain_layout`: křížení, překryvy, formát), hranice vlastnictví, rozmístění JPS, vazby přívodů
    layout.py    zarovnání bloků a lomů JPS, trasa RD, svislý řetězec (`_stack_column`), zvětšení listů rozvaděčů
    jps.py       rozmístění JPS na list a dělení na listy střídačů (`close_gaps` svisle i vodorovně,
                 `stack_components` jen se společným RFVE.DC)
    currents.py  proudy střídačů a jištění AC strany: jistič přívodu střídače (1,25 × max. AC proud – artikl `i_ac_max_a`, jinak z P AC,
                 řada do 250 A), vývod FVE v RD / HR i HR na vn (≥ max(Σ I, jistič střídače)), hlavní vypínač RFVE.AC
    boards/      jeden modul na roli: base (ChainContext, ChainPorts, BoardBuilder), rfve_dc (i společný RFVE.DC),
                 rfve_ac, rfve (rozvaděč FVE RD), house_board (stávající RD / HR: hlavní přístroj, vývod FVE, stávající
                 rozvody), meter_board (RE na nn a funkce měření – i měření v HR), hds (`fve.hds`), grid (DS na nn),
                 mv (přípojka VN: HR+TR+RVN+RE jako jeden builder), macro_glue (makra), eps (EPS a přepínač sítí
                 RD), groups (skupiny střídačů `ac_group` – RFVE.AC{n}). Rozsah (rozhodnutí 12): RD / HR / RE jen
                 bloky bez listu (porty a údaje v atributech), RFVE.AC / AC část RFVE z mustru (`rfve_ac.ac_mode`,
                 `spec.pattern_macro`), jinak blok / kotvy; vestavěný kód volbou `chain.<role>.builtin` / standard
                 `ac_builtin`. Zkoušení rozložení s mezipamětí značek (`project.symbol_cache`) a rozložení textů
                 (`textlayout.layout_cache`, klíč = úplný stav listů; benchmark `tools/bench_generate.py`); přístroje řetězce nesou atribut `chain`
                 (inv, rfve_main, fve_out, main, meter_main, inst_switch) pro `calc.check_selectivity_tree` (F7
                 `checks.chain_findings`)
  i18n.py     překlady rozhraní (gettext-styl bez Qt: `tr("česky")` + katalogy `resources/i18n/<jazyk>.po`, `docs/PREKLADY.md`)
  updater.py  aktualizace na vydané verze (klon: git tagy `vX.Y.Z`; samostatná aplikace: `latest.json` ve sdílené složce,
              ZIP + SHA-256, `current.txt`); bez Qt – dotaz a hlášení v `ui/update_prompt.py` (`docs/RELEASE.md`)
  cmd/        příkazový řádek ve stylu ZWCAD (bez Qt – hlídá `test_model_pure.py`), pro GUI, CLI, skripty a agenty;
              návrh docs/design/prikazovy_radek.md
    registry.py  CommandDef (jméno = id akce MainWindow), Param (výzva: point, port, selection, number, text, symbol,
                 choice, kv), Registry (aliasy bez diakritiky z aliases.json + ~/.envocad/aliases.json, `complete`)
    parse.py     tokeny (shlex), body „x,y“ (desetinná tečka) / „@dx,dy“ / „ref:port“, klíč=hodnota, `space_submits`
    runner.py    CommandRunner → Session (příkaz = generátor výzev, hodnoty z řádku nebo z GUI `send`/`send_value`),
                 transakce `sheets_state` před/po → ChangeSet (jen změněné listy), chyba / Esc vrátí stav; Journal =
                 headless UNDO/REDO; `sync_derived` = odvozená data po změně (CLI)
    edits.py     změny modelu (vložit, smazat, posunout, otočit, zrcadlit, kopie, vodič, atribut) stejnými funkcemi
                 modelu jako ui/commands.py; navázané změny přívodů (`feed_link_followups`, `wire_conductor_followups`,
                 `feed_dir_followups`, `renames_location`) volá i ui/commands.py – jedna implementace
    builtin.py   vestavěné příkazy, `default_registry()`;  script.py  skripty .ecs;  __main__.py  CLI
  ui/         PySide6 GUI (nikdy neobsahuje business logiku)
    canvas.py       QGraphicsView – mřížka, zoom, snap
    items.py        QGraphicsItem obaly nad Element/Wire
    main_window.py  okno, panely, akce
    update_prompt.py  aktualizace při startu: dotaz Aktualizovat / Teď ne, průběh kopie, hlášení výsledku
                    (`app.startup_update`, `app.report_update`)
  export/     DXF, PDF, výkazy .xlsx, docx (protokol kusového ověření, TZ a DSPS ze šablony: doc_template.py engine
              polí {{…}} / {% if/for %} / bloků, tz_data.py kontext a tabulky z modelu – docs/design/tz_dsps.md)
```

Zásada: **model nezávisí na UI.** Vše, co lze, se testuje bez spuštění Qt.
Model nečte ani uživatelská nastavení (`~/.envocad/settings.json`): firemní standard (formát stran vícepólu
`standard_paper`, název firmy `company`) předává volající (GUI, export, generátor) parametrem a čte ho přes
`envocad/settings.py` (`switchboard_paper`, `company`, `frame_enabled`); hlídá `tests/test_model_pure.py`. Knihovna
čte z nastavení jen umístění dat (uživatelská a sdílená složka knihovny, maker a topologií).

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
  `model/designation.py` – používají ho výkazy a štítky; list rozvaděče má `+` = označení bloku. Kód je jedna
  úroveň; tečka uvnitř kódu (firemní `RFVE.AC`, `RFVE.DC1`) úrovně nedělí (`CODE_RE`, `parse_designation`). Generátor
  označuje rozvaděče podle presetu topologie (`node.ref`; přepis `chain.<role>.ref`, dřívější `switchboard.ref`,
  `connection.*_board.ref` – `generator/spec.resolve_chain_refs`): RFVE.AC, společný RFVE.DC (na střídač RFVE.DC1…n
  s `chain.rfve_dc.per_inverter`), RDCn, HR, RD, RE, HDS, u rodinného domu RFVE (`generator/boards/rfve_dc.dc_box_ref`).
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
  Čistá data bez Qt; návrh v `docs/design/xref_zrcadleni_kontaktu.md`. Kabel přes dvojici přerušovacích bodů:
  „data kabelu“ = typ nebo průřez (`has_cable_data`, podle nich `no_cable` a `cable_split`); úsek pokračování =
  vodič úplně prázdný – ani označení (`is_blank_wire`; vodič s označením je pro `sync_cables` samostatný kabel), oba
  body mají jediný vodič a protější úsek prázdný není (`continuation_main`). `through_interrupt` sleduje jen od
  hlavního úseku k pokračování a vrací `ThroughEnd` (list, prvek, port, vodič pokračování, strana – svorka se počítá
  z vodiče pokračování). Výkazy (Odkud/Kam, zapojovací seznam), výpočet kabelů, vazba přívodu a potenciály tak vidí
  jeden kabel; ruční projekt s auto označením na obou úsecích se chová jako dřív („P:1“). `groups`
  (`interrupt_groups`) se předávají jednou za výkaz. Generátor dělí velké JPS na listy (nad `standard.jps_max_paper`
  = A2): AC list první, listy střídačů za ním („T1–T3“), AC kabel přes pár přerušení „AC-T1“ s daty jen u bloku AC
  rozvaděče, úsek u střídače s `ref=""` (`generator/jps._split_jps` přeruší každý vodič mezi řadou a listem AC – u rodinného
  domu i DC vodiče přes RFVE; přípojka VN zůstává na listu AC); přerostlá řada jednoho střídače dostane větší formát.
  Odvozené jednopólové schéma (`single_line._graph`, i kabel přes pár přerušení končící na bloku rozvaděče – společný
  RFVE.DC zůstává na listu AC) a kontrola stringů (`calc._wire_steps`, blok DC rozvaděče párem portů) jdou přes pár
  přerušení. Elektroměr v sérii (přímé měření v RE na nn – fáze na portu 1 i 2) je v JPS obyčejný uzel stromu, elektroměr
  na MTP měřicí obvod. PDF dokumentace: listy JPS zmenšit na A3 / skutečný formát (`DocBuilder(jps_page=…)`, standard
  `doc_jps_page`).
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
změnit atribut). Model sám o undo neví. Příkazový řádek (`envocad/cmd`) mění model přímo přes `cmd/edits.py` v transakci runneru
a vrací `ChangeSet` (`before`/`after` ve tvaru `model.project.sheets_state`); GUI ho pushne jako jeden
`SheetsStateCommand` (první redo nic nemění; dok `ui/command_line.py`, výzvy bodu klikem přes `Mode.PICK` scény,
psaní ve výkresu filtr `CanvasTyping`), headless CLI drží historii v `Journal`. Shodu s QUndoCommandy GUI hlídá
`tests/test_cmd_parity.py` (stejné `to_dict` po INSERT, MOVE, ROTATE, MIRROR, COPY, ERASE, SET ref). Operace nad projektem mají vlastní příkazy (`ui/commands.py`): přidání a
smazání listu (`AddSheetCommand`, `DeleteSheetCommand` – vrací i odpojené listy rozvaděčů a atribut „sheet“ bloku,
záložky listu se zavřou / obnoví), šablona rozvaděče (`SheetsStateCommand` – snímek změněných listů, `sheets_state` / `restore_sheets_state` jsou čistý
model v `model/project.py`, `ui/commands.py` je re-exportuje), vlastnosti
projektu (`SetProjectMetaCommand`), skříň (`SetLayoutCommand` – snímek `Layout.to_dict`, po sobě jdoucí změny
téhož pole panelu se slučují; dialog skříně pracuje na kopii). `undo.clear()` / `undo.resetClean()` smí GUI volat
jen při načtení projektu, po založení nového projektu z průvodce / specifikace a po obnově autosave (hlídá test
`test_no_undo_reset_outside_allowed_places` – všechna volání v `ui/` včetně lambd a aliasů undo stacku). Zmenšení počtu řad skříně umístění nemaže: umístění v řadě mimo skříň
zůstane v modelu (`Layout.stored_placement`), `Layout.placement` ho nevrací (přístroj je nerozmístěný) a kontrola
hlásí `outside_enclosure`. Zmenšení počtu modulů v řadě také nic nemaže – přístroje za koncem řady a překryvy hlásí
kontrola `layout_overflow` / `layout_overlap` (`checks.layout_problems`, varování i v panelu skříně). Rozměry
přístroje v rozložení určuje `model/device_size.py` (ruční rozměr > artikl > `modules`; tvar modulový / obdélník /
svorkovnice; kontroly `layout_height` / `layout_enclosure` / `layout_depth`); knihovna se předává volitelně (`lib`),
bez ní platí jen atributy – návrh `docs/design/rozlozeni_z_artiklu.md`. Kabely
(`Cable`) jsou odvozené z vodičů JPS (`sync_cables`): kabel bez vodiče se odebere do `Project.removed_cables`
(neukládá se) a vrácený vodič (undo/redo) dostane týž kabel zpět – undo vložení/smazání vodiče vrátí `to_dict` přesně. Kabel osiřelý už v načteném souboru (`Project.loaded_orphan_cables`) se při otevření neodebere (ruční barvy žil, artikl); kontrola ho hlásí jako INFO `cable_no_wire`.
Vazby přívodů/vývodů rozvaděče na vodiče JPS: GUI po každé změně modelu volá jen odvozenou `sync_feed_link_attrs`
(`wire_id`, odkud/kam, kabel přívodu). Primární data mění příkazy jako navázané změny (`commands._FeedFollowups`:
spočítají se při prvním redo, undo je vrátí): žíly vodičů u přívodu převezmou žíly navázaného vodiče JPS
(`feed_conductor_followups` v `AddWireCommand`, `SplitWireCommand`, `SetConductorsCommand`, `SetAttrCommand` s
`wire_id`), přejmenování přívodu přejmenuje port vodiče JPS na bloku (`rename_followups` → `TextChange` „wire_port“).
Plná `sync_feed_links` (i s primárními změnami) jen při načtení projektu a v generátoru. Parametrická sběrnice (`taps`) má porty i podle
vodičů: scéna po každém vložení / odebrání položky vodiče (`add_wire_item` / `remove_wire_item` – vodič, schránka, makro,
smazání, undo / redo) přestaví značku dotčené sběrnice (`SchematicScene.refresh_bus_symbols`), jako `SetAttrCommand`
po změně `taps`; vícepól (`MultipoleAddCommand`) přestaví sousední jednopólovou scénu celou. Zápisy do modelu v `ui/`
mimo `commands.py` hlídá `tests/test_no_model_writes_in_ui.py`; výjimky mají komentář `# model-write-ok: <důvod>`.

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
- Přívod/vývod rozvaděče je jedna značka `sb.feed` (`dir` in/out); predikáty jen v `model/feed.py` (bez Qt). Vícepól
  ho kreslí jako dřívější `sb.feed_in` / `sb.feed_out` (`feed.multipole_feed_view`) a přívodní větev, kterou list
  rozvaděče kreslí tokem zespodu nahoru (RFVE, RFVE.AC – přívod portem nahoru, jistič rot 90), otočí zpět shora dolů
  (`multipole.sheet_poles` / `flow_flipped`: prvek v pohledu je kopie se stejným id a atributy a jinou rotací).
  Přívod/vývod převedený migrací v12 → v13 má technický atribut `mp_legacy="1"` – od něj se větev neotáčí (vícepól
  starého projektu beze změny); otisk listu (`diff._canon_element`) kreslí `sb.feed` jako `sb.feed_in`/`sb.feed_out`
  bez `dir` a `mp_legacy`, takže uzavřené revize starých projektů zůstanou uzavřené.
  Štítek kabelu přívodu/vývodu je na straně proti portu (`feed_cable_up`). Změna směru v GUI = jeden `SetAttrCommand`
  s navázanými změnami odkud ↔ kam (`project.feed_dir_changes`) a přestavbou položky značky.
- Geometrie vícepólu (rozmístění `auto_layout`, stránkování `paginate`, popisky přístrojů `pole_label_lines`, trasy
  žil `conductor_route`, příčka PE svodiče `pe_join_segments`) je v `model/multipole.py`; `model/multipole_geometry.py`
  z ní bez Qt skládá texty a čáry celého pohledu a rozmisťuje popisky žil a prvků (`element_labels`) mimo cizí čáry
  – stejné polohy kreslí scéna
  (`ui/multipole_view.py`) a kontroluje F7 (`mp_text_overlap`). Scéna přebírá z modelu vše: polohy
  (`MultipoleGeometry.origins`), strany, přerušení s odkazy (`page_breaks`), sběrné čáry (`rails`, `rail_taps`),
  odkazy sběrnice (`bus_refs`), popis sběrnice (`bus_desc`) a můstky svorkovnic (`bridges` = `multipole.bridge_paths`).
  Kreslicí seznam `MultipoleGeometry.prims` (`Prim`, lokální souřadnice strany) je zdroj pro export DXF vícepólu
  (`export/dxf_export.export_multipole_dxf`: jeden soubor se stranami vedle sebe a layoutem na stranu, nebo soubor
  na stranu).
- Formát stran vícepólu a plánu svorkovnice: `multipole.paper_choice` – `Sheet.mp_paper` (nepovinný klíč), jinak
  firemní standard `standard.switchboard_paper` (výchozí „A4“ = 297 × 210); list, který není rozvaděč, a starší list
  rozvaděče s jiným rozměrem než A3 nebo s `mp_pos` → „list“ (rozměr listu jako dřív). `page_size`, `page_width`,
  `page_pitch`, `layout_x0` (bez sběrnice užší levý okraj). Ruční poloha ve vícepólu (`MoveMultipoleCommand`,
  `MultipoleAddCommand`) zapíše platný formát do `Sheet.mp_paper`.
- Stránkování po logických skupinách: `auto_layout` umisťuje podstrom jako celek – přesáhne-li hranici strany a vejde se
  na stranu, začne celý na další (string = X + FU + SPD + vývod; za sběrnicí každý vývod zvlášť). Nízká strana A4:
  `multipole_geometry` posune rozmístění nahoru pod nadpis a zmenší `col_gap` (≥ `MIN_COL_GAP`), dokud kresba nesahá
  pod horní hranu popisového pole (nezávisle na zapnutí rámečku). Žíly z více stran do jednoho pólu (PE svodičů do
  XPE / PE lišty) vede sběrná čára (`Rail`) s jedním přerušením a odkazem na každém okraji strany.
- Plán svorkovnice: data `model/terminal_plan.py:terminal_plan`, rozmístění na strany `layout_plan_pages` (pásy,
  svorkovnice vedle sebe, zalomení dlouhé, další strana, výška pásu podle textů `band_heights`), formát strany
  `sheet_plan_pages` – scéna `ui/terminal_plan_view.py` má `pages` jako vícepól.
- Formát listu (`frame.sheet_format_placement`): pevné A4…A1 na šířku, nebo volný A4 (výška 297 mm, šířka A4×n podle
  obsahu); volí se v `Vlastnosti listu`, změna jde vrátit undo. Obsah se posune jen tehdy, když se mimo popisové pole
  nevejde.
- Jednopólové přístroje: `multipole.dead_conductors` / `live_conductors` – na jistič nebo pojistku s `poles` = 1
  (`single_pole_device`; elektroměr, MTP a svorky ne) vede jen první fáze; mrtvé žíly vyřadí `sheet_dead_conductors`
  i z výkazů (svorkovnice, potenciály, zapojovací seznam).
- Elektroměr při nepřímém měření: pohled `multipole.meter_terminal_view` se svorkami podle `TERMINAL_SCHEMES`
  (DIN 43856), stejná čísla svorek v `device_terminal`; MTP po fázích (`multipole.stagger`, `secondary`).
- Rámeček (`model/frame.py`): razítko ENVO v popisovém poli (`stamp_fields`, logo `resources/envo_logo.json`), bez QR kódu,
  „Číslo listu“ stran odvozených pohledů `page_label` („2/5, str. 1/3“), formát strany v popisovém poli (`paper`).
  PDF dokumentace (`export/doc_pdf.py`) má smíšené formáty stran: `QPdfWriter.setPageLayout` před každou novou
  stranou (`DocBuilder.page_sizes`).

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
   Přívod/vývod rozvaděče je v API jedna značka `sb.feed` + `attrs.dir` (`feed.FEED_SYMBOL`); šablona pluginu se
   starými `sb.feed_in` / `sb.feed_out` se po `build` převede (`feed.normalize_legacy_objects` v `apply_template`),
   callback menu, který vkládá prvky sám, musí použít `sb.feed`.

Formát projektu (`.ecp`) je verzovaný (`FORMAT_VERSION` + migrace, aktuálně **17** – formát stran schématu rozvaděče `mp_paper` navíc A2, A1 a volný A4 (výška 297, šířka podle kresby, `multipole.FREE_A4`) a formát listu volný A4 (`frame.sheet_format_size`), data se nemění; v16 otisk listu uzavřené revize zahrnuje volné texty listu, migrace v15 → v16 přepočítá
otisky listů s texty, které sedí na starý výpočet (`diff.upgrade_fingerprints`), data se nemění; v15 blok rozvaděče bez listu
s porty z atributů `ports_in` / `ports_out` a jištěním portů `protect` (`project.block_port_names`, `is_block_only`,
`block_protect`; generátor tak kreslí stávající RD / HR / RE a RFVE.AC bez mustru jen jako blok), migrace v14 → v15
nic nemění, verze zvednutá, aby program v14 soubor odmítl místo osiřelých portů „X1?“; v14 parametrická sběrnice `sb.busbar`
(atributy `taps` / `outs` / `tap_pitch`, `model/busbar.py`), migrace v13 → v14 nic nemění, verze zvednutá jen proto, aby
program v13 soubor odmítl místo kreslení pevné sběrnice; v13 jedna značka přívodu/vývodu
`sb.feed` se směrem `attrs.dir` místo `sb.feed_in` / `sb.feed_out`, migrace bez přeskládání: přívod se pootočí o 180°,
port zůstane na místě, vodiče se nerozpojí (`model/feed.py:normalize_legacy_element`, makra a schránka se převádějí
při načtení); v12 ruční posun prvku v jednopólovém schématu `Element.sl_pos`, bez migrace; v11 žíly dle ČSN EN 60445 (DC+/DC− → L+/L−,
`conductor_name`); v10 zrcadlení prvku `Element.mirror` a volné texty listu `Sheet.texts`; v9 přidala připomínky `Project.notes`;
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
