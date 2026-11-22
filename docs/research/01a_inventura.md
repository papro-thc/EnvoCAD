# 01A – Inventura repozitáře EnvoCAD

Stav: větev `main` @ `76c0818` (22. 11. 2026), verze `0.11.0` (`pyproject.toml`). Agent 1A, rešerše.

Metoda: čtení kódu (`envocad/**`), osnovy modulů (grep tříd/funkcí, AST analýza délek funkcí), grep testů
(`tests/**`), čtení dokumentace (`docs/**`, `README.md`, `CLAUDE.md`, `.github/**`).
**Testy se nespustily** – v prostředí agenta chybí `pytest` (`/usr/bin/python: No module named pytest`), nic se
neinstalovalo. Počty testů jsou z grepu `def test_` (viz kap. 4.4). `ruff` se také nespouštěl.

Značení: **H** = hotové (ověřeno v kódu + existuje test), **H*** = hotové v kódu, test nenalezen nebo jen nepřímý,
**R** = rozpracované / částečné, **P** = jen v plánu (bez kódu). „neověřeno“ = tvrzení z dokumentace, které jsem
v kódu nepotvrdil.

Velikost kódu (řádky / soubory): `model` 16 699 / 31, `ui` 12 811 / 26, `generator` 5 934 / 24, `export` 3 408 / 12,
`library` 3 086 / 11 (bez dat), `cmd` 2 070 / 8, kořen `envocad/*.py` 1 402; `tests` 29 269 řádků / 101 souborů.

---

## 1. Funkce

### 1.1 Hotové (ověřené v kódu)

| Oblast | Stav | Kde (kód) | Testy |
|---|---|---|---|
| **Blokové schéma / JPS editor** – vkládání značek, vodiče port→port, lomy, posun, rotace, zrcadlení, texty, snap 2,5 mm | H | `ui/canvas.py`, `ui/items.py`, `ui/main_window.py`, `model/routing.py` (`route_points`, `best_route`, `drag_segment`), `model/grid.py` | `test_gui_smoke.py` (52), `test_gui_mouse.py` (18), `test_mirror_text.py` |
| **Odvozené jednopólové schéma** (strom od DS přes rozvaděče ke střídačům, VN přípojka) | H | `model/single_line.py` (`build_tree`, `single_line_geometry`), `ui/single_line_view.py`, DXF `export/dxf_export.py:export_single_line_dxf` | `test_single_line.py` (17) |
| **Generátor projektu ze specifikace / topologie** (firma nn, firma vn, RD, bytový dům) | H | `generator/build.py:build_project`, `generator/spec.py` (`DEFAULT_SPEC`, `select_topology`), `generator/chain.py`, `generator/pv.py`, `generator/boards/*`, presety `library/builtin/topologies/{nn,nn_hr_meter,rd,vn}.json`, CLI `envocad/generate.py:main` | `test_generate.py` (46), `test_generator_f2.py` (47), `test_generator_scope.py`, `test_generator_chain.py`, `test_topology.py`, `test_perf_generator.py`, snapshot `tests/data/generate_snapshot.json` |
| Průvodce nového projektu (GUI) vč. katalogu modulů/střídačů, baterií, optimizérů | H | `ui/wizard_topology.py`, `ui/dialogs.py` (třída průvodce, `__init__` 306 řádků od ř. 526) | `test_wizard_*.py`, `test_qa_jps_wizard*.py` |
| **Rozvaděč – schéma** (list rozvaděče z bloku, vícepól nad stejnými daty, stránkování, sběrnice, přerušení s odkazy) | H | `model/project.py:Project.create_switchboard_sheet`, `model/multipole.py` (`auto_layout`, `sheet_poles`), `model/multipole_geometry.py`, `ui/multipole_view.py`, `model/busbar.py` | `test_multipole*.py`, `test_switchboard*.py`, `test_busbar*.py`, `test_qa_switchboard*.py` |
| **Rozvaděč – fyzické rozložení** (DIN lišty, moduly, rozměry z artiklu, kontrola přetečení) | H | `model/project.py:Layout/Placement`, `model/device_size.py`, `ui/layout_view.py`, `checks.layout_problems` | `test_device_size.py` (20), `test_layout_articles_gui.py` |
| Šablony rozvaděčů (AC/DC/prázdný – Python) | H | `library/templates.py` (`build_ac_fve`, `build_dc`, `apply_template`) | `test_switchboard.py`, `test_model_pure.py` |
| **Svorkovnice, můstky, plán svorkovnice** | H | svorka = prvek `sb.terminal_block` / `fve.terminal` (atribut `terminal`), přiřazení žil `Wire.terminals`, můstky `Sheet.bridges`, `model/terminal_plan.py`, `model/bridges.py` (artikl můstku), `ui/terminal_plan_view.py` | `test_feed*.py`, `test_wiring.py`, `test_exports_audit3.py` |
| Automatické číslování svorek | H* | menu „Očíslovat svorky automaticky“ (`ui/main_window.py`) | nepřímo (GUI testy, neověřeno konkrétně) |
| **Vodiče a kabely** – žíly dle ČSN EN 60445, kabel odvozený z vodičů (`sync_cables`), žíly/barvy/stínění | H | `model/project.py:Wire, Cable, Core, conductor_name, CORE_COLORS`; `ui/commands.py:SetCableCommand` | `test_model.py`, `test_undo*.py` |
| **Potenciály** (sítě přes vodiče, uzly, svorky, můstky; T-odbočka) | H | `model/potential.py` (`nets`, `split_wire`) | `test_checks.py`, `test_checks_poles_npe.py` |
| **Výrobní data rozvaděče** (délky po žlabech, průřez, barva, dutinky) | H | `model/wiring.py` (`production_wires`, `ProductionWire`), `reports.production_wiring_list`, `xlsx_export.export_production_xlsx` | `test_wiring.py` (36) |
| **Výkazy / BOM** (přístroje, BOM, kabely, svorky, štítky, kabelový plán, zapojovací seznam, výpočty, DS, potenciály, kabely k objednání, značení) | H | `export/reports.py` (14 funkcí výkazů), `export/xlsx_export.py:export_reports_xlsx` | `test_reports.py`, `test_export_content.py`, `test_exports_audit3.py` |
| **Štítky** – výkaz `reports.labels`, `reports.marking`; CSV pro tiskárnu | H* (CSV) | `export/reports.py:labels` (testováno `test_qa_switchboard.py:315`); CSV zápis je přímo v GUI `ui/main_window.py:2033 export_labels_csv` | CSV export bez testu |
| **Protokol kusového ověření (docx)** dle ČSN EN 61439-1 čl. 11 | H | `export/docx_export.py:export_routine_test_docx`, `ROUTINE_CHECKS` | 4 testy soubory ji volají |
| **Oteplení rozvaděče** (IEC TR 60890: Ae, k, c, d, teploty po přístrojích, Pv z artiklu) | H (orientační) | `model/thermal.py` (`temperature_rise`, `k_factor`, `c_factor`, `device_temperatures`); kontrola `checks.thermal_findings` | `test_thermal.py`, `test_thermal_devices.py` (19) |
| Výpočty (stringy Uoc/Isc za teploty, Iz, In ≤ Iz, úbytky, selektivita, optimizéry, MPPT) | H (tabulky orientační) | `model/calc.py` (`ampacity`, `min_cross`, `voltage_drop`, `string_issues`, `string_limits`, `optimizer_issues`), `model/ratings.py`, `model/dc_system.py`, `generator/currents.py` | `test_calc.py` (27), `test_ratings.py` (32), `test_spd_dc.py`, `test_optimizer_review.py`, `test_dc_system.py` |
| **Knihovna symbolů** – 48 vlastních (`fve` 36, `switchboard` 8, `control` 4) + 673 QET | H | `library/builtin/**`, `model/symbol.py:Symbol/Port/Attribute`, `library/store.py:LibraryStore` | `test_components_builtin.py`, `test_model.py` |
| **Knihovna artiklů** – 32 CSV, cca 1 392 řádků (OEZ, Eaton, Hager, Weidmüller, Bečov, ELEMAN, střídače, moduly, baterie, optimizéry, skříně, kabely) | H | `library/components.py` (`Component`, `validate`, `CATEGORIES`, `apply_to`), `library/builtin/components/*.csv`, `library/batteries.py` | `test_components.py`, `test_batteries.py` |
| Sdílená a uživatelská knihovna (síťová složka, přebíjení id) | H | `store.py:sync_builtin` (zdroje builtin → user → shared) | `test_settings*.py`, neověřeno přesně |
| **Makra** (v3: proměnné, sady hodnot, `when`, `repeat`, vazba na artikl) – 8 vestavěných | H | `library/macros.py` (`Macro`, `MacroVar`, `parse_macro`, `validate_macro`, `MACRO_VERSION = 3`), `library/builtin/macros/*.json`, `generator/boards/macro_glue.py` | `test_macros.py` (35) |
| **Příkazový řádek / CLI / skripty `.ecs`** – 20 příkazů, aliasy ZWCAD + české | H | `cmd/builtin.py` (`CommandDef` ř. 595–628), `cmd/registry.py`, `cmd/parse.py`, `cmd/runner.py` (`Session`, `Journal`), `cmd/script.py`, `cmd/__main__.py`, `cmd/aliases.json`, dok `ui/command_line.py`, paleta `ui/command_palette.py` | `test_cmd_*.py` (6 souborů, ~96 testů), parita GUI↔CLI `test_cmd_parity.py` |
| **Undo/redo** – 30 tříd `QUndoCommand` v GUI, headless `Journal` v CLI | H | `ui/commands.py` (`AddElementCommand` … `SetSingleLineOffsetCommand`), `cmd/runner.py:Journal` | `test_undo.py`, `test_undo_feed_links.py`, `test_undo_project_ops.py`, hlídač `test_no_model_writes_in_ui.py` |
| **PDF** – list, rozložení, celá dokumentace (titul, obsah, listy, výkazy, změnový list), záložky, anotace připomínek | H | `export/pdf_export.py` (QPdfWriter), `export/doc_pdf.py:DocBuilder`, `export/pdf_outline.py:add_bookmarks`, `export/pdf_annots.py` | `test_doc_pages.py`, `test_pdf_outline.py`, `test_pdf_annots.py`, `test_export_content.py` |
| **Kontroly (ERC, F7)** – cca 80 kódů nálezů (duplicity, osiřelé porty, potenciály/zkraty, N/PE, póly, kabely, výpočty, SPD, Icu/Icw, kontakty, přerušení, revize, připomínky, rozložení, texty, baterie, Tigo, síťová ochrana) | H | `model/checks.py:check_project` (181 řádků) + `*_findings`, `model/ratings.py`, `Finding(severity, sheet_id, …, code)` | `test_checks*.py`, `test_ratings.py`, `test_review_cde.py` |
| **Značení IEC 81346** (`=` funkce, `+` umístění, `-` přístroj), registr struktur, `function_class` v symbolu, kontrola syntaxe/třídy | H | `model/designation.py` (`parse_designation`, `full_designation`, `validate_ref`), `Project.structures`, `Sheet.func/loc` | `test_designation.py` |
| Automatické číslování / přečíslování označení (nové prvky další volné číslo, dialog Přečíslovat) | H | `Project.next_ref`, `model/renumber.py:plan`, `ui/renumber_dialog.py` | `test_renumber.py` |
| **Křížové odkazy** – přerušovací body (dvojice, řetěz, hvězda), zrcadlo kontaktů pod cívkou, vazba přívod/vývod ↔ vodič JPS, odkaz polohy `/list.sloupec` | H | `model/xref.py` (`DeviceIndex`, `contact_table`, `interrupt_xref`, `through_interrupt`), `model/project.py:wire_xref`, `feed_link_index`, `model/frame.py:position_ref` | `test_xref.py` (26), `test_feed*.py` |
| **Vícelistové projekty** (listy schématu, listy rozvaděčů, dělení velkých JPS na listy střídačů) | H | `Project.sheets`, `AddSheetCommand`/`DeleteSheetCommand`, `generator/jps.py` (`_split_jps`) | `test_jps_split*.py`, `test_undo_project_ops.py` |
| **Rohové razítko / rámeček** (razítko ENVO 180 × 32 mm, logo, mřížka sloupců, číslo listu „n/N, str. k/m“, formáty A4–A0, na výšku, volný A4, vlastní) | H | `model/frame.py` (`stamp_fields`, `frame_geometry`, `sheet_format_placement`), `resources/envo_logo.json`, `ui/render.py` | `test_formaty_stran.py`, `test_doc_pages.py`, `test_switchboard_a4.py` |
| Revize (diff, značky trojúhelníky, měkké uzavření, změnový list) | H | `model/diff.py`, `model/revision.py` | `test_diff.py`, `test_revision*.py` |
| Připomínky / redlining | H | `model/notes.py`, `Project.notes`, `ui/notes_panel.py`, `ui/notes_view.py` | `test_notes.py` (16) |
| TZ / DSPS z šablony (.md / .docx, pole `{{…}}`, `{% if/for %}`) | H | `export/doc_template.py`, `export/tz_data.py`, `export/tz_export.py`, `library/doc_templates.py` | `test_tz_dsps.py` (22), `test_tz_dsps_gui.py` |
| Bloky typů střídačů (pás svorek BACKUP/BMS/METER/RS485…) | H (piny neověřené dle ROADMAP) | `model/inverter_io.py` (`profile_for`, `inverter_io`) | `test_inverter_io.py` |
| Tigo CCA/TAP/RSS | H | `generator/tigo.py`, značky `fve.tigo_*`, `checks.tigo_findings` | `test_tigo.py` |
| Pluginy (`~/.envocad/plugins/*.py`, `register(ctx)`) | H | `envocad/plugins.py:PluginContext` (`add_menu_action`, `add_template`, `add_importer`, `add_report`, `add_command`), vzor `plugins_builtin/example_counts.py` | `load_plugins` ve 2 testech |
| Autosave, poslední projekty, atomický zápis + `.bak`, oprava duplicitních id | H | `ui/main_window.py`, `model/project.py:write_json_atomic`, `_repair_duplicate_ids` | `test_robustness.py`, `test_gui_robustness.py` |
| Aktualizace (git tagy / sdílená složka, ZIP + SHA-256) | H | `envocad/updater.py`, `ui/update_prompt.py`, `tools/release.py` | `test_updater.py` (28) |

### 1.2 Rozpracované / částečné

| Oblast | Co chybí | Kde |
|---|---|---|
| Štítky pro tiskárny | jen obecné CSV se středníkem; žádný formát Brady/Partex; logika zápisu v GUI, bez testu | `ui/main_window.py:2033` |
| Ceny | `Component.price` / sloupec `price_czk` se načítá, ale **žádný výkaz ceny nepoužívá** (grep `price` v `export/` a `ui/` = 0) | `library/components.py:103,160` |
| Oteplení | jen bez ventilace; ventilace (obr. 5) a přepážky v GUI chybí; křivky k, c označeny jako ORIENTAČNÍ (`thermal.py:19`) | `model/thermal.py` |
| Tabulky Iz, konstanty | orientační přepisy, neověřeno proti normě (ROADMAP Top10 #2, issue #79/#82) | `model/calc.py`, `model/thermal.py` |
| Protokol kusového ověření | generický `Document()` nebo volitelná šablona; firemní šablona ENVO „po dodání“ (ROADMAP v0.2) | `docx_export.py:187` |
| Vícepól | ruční lomy žil, vlastní vícepólové značky (`qet.ap.*`) místo opakování jednopólové | ROADMAP v0.6 |
| DXF export | jen list, vícepól, jednopólové schéma; **rozložení rozvaděče a plán svorkovnice do DXF chybí** (jen PDF `pdf_export.export_layout_pdf`) | `export/dxf_export.py` (3 funkce) |
| Automatické číslování podle `function_class` | kontrola tříd ano, číslování podle tříd ne (ROADMAP ř. 112) | `model/designation.py` |
| Data knihovny | 222 artiklů bez rozměrů, 138 jističů bez Pv (dle ROADMAP, nepřepočítáno), `t_min_c`/`t_max_c` chybí u Eaton/OEZ MCB…; 1500 V DC artikly chybí (`tests/test_dc_system.py:216` → `pytest.skip`) | `library/builtin/components/*.csv` |
| Footprinty z EPLAN ZIP | `eplan_import.footprints_from_zip` existuje, test nenalezen | `library/eplan_import.py:166` |
| Bytový dům v generátoru | generuje se jako firma (liší se jen `meta["building"]`) | ROADMAP „Odloženo“ |
| EPS u více hybridních střídačů RD | baterie jen u jednoho | ROADMAP ř. 89–94 |
| Tisk | **přímý tisk (QPrinter) nenalezen** – jen export do PDF | grep `QPrinter` = 0 |
| Kopírování celého listu | akce v menu nenalezena (ROADMAP „zbývá“) | `ui/main_window.py:_build_actions` |

### 1.3 Jen v plánu (bez kódu)

| Položka | Zdroj | Ověření nepřítomnosti |
|---|---|---|
| Editor symbolů v GUI (porty, atributy) | ROADMAP Top10 #5, v0.2, issue #85 | grep `SymbolEditor`/„editor značek“ v `envocad/` = 0 |
| Import BMEcat / ETIM | Top10 #4, issue #84, `docs/SOURCES.md` („Plán: `library/bmecat_import.py`“) | soubor neexistuje; ETIM jen jako sloupec v `eplan_import.py:52` |
| Import PVsyst .PAN/.OND | Top10 #7, issue #86 | grep `pvsyst` = 0 |
| Ceny ve výkazech | Top10 #8, issue #87 | viz 1.2 |
| DXF rozložení rozvaděče a plánu svorkovnice | Top10 #9, issue #88 | viz 1.2 |
| Vícepatrové svorky, N-odpojovací svorky | Top10 #10, issue #89 | `model/terminal_plan.py` nemá úrovně |
| Podepsaný build Windows | Top10 #6, issue #90 | jen `envocad.spec`, `scripts/build.*` |
| Anglické rozhraní | issue #91 | žádný `QTranslator`, texty natvrdo česky |
| Sdílená knihovna v PostgreSQL | ROADMAP v0.4 | jen SQLite + síťová složka |
| Formáty strojů na vodiče (Komax…) | ROADMAP | rozhraní `wiring.ProductionWire` připraveno, `export/machine_*.py` neexistuje |
| Hromadný import DXF knihoven výrobců, footprinty z DXF výrobců | ROADMAP v0.2 | importér existuje (`dxf_import.py`), data ne |
| Import projektů EPLAN (.epdz) | `docs/SOURCES.md` („pro budoucí import“) | nenalezeno |
| Slovenská mutace výstupů, další obory (HVAC, MaR) | ROADMAP „Později“ | nenalezeno |

---

## 2. Datový model

Vše v `envocad/model/project.py`, pokud není uvedeno jinak. Čisté dataclassy bez Qt (hlídá
`tests/test_model_pure.py:92 QT_FREE = ("model", "library", "cmd")`).

| Pojem | Třída / umístění | Klíčová pole | Vazby |
|---|---|---|---|
| **Projekt** | `Project` (ř. 811) | `name`, `meta` (investor, zakázka, `doc_pages`, `building`…), `sheets`, `cables`, `structures`, `revisions`, `notes`; neukládané `path`, `removed_cables`, `loaded_orphan_cables` | kořen; `to_dict`/`from_dict`/`save`/`load` |
| **List** | `Sheet` (ř. 710) | `name`, `paper`, `width`, `height`, `elements`, `wires`, `kind` (`schematic`/`switchboard`), `parent_element_id`, `layout`, `bridges`, `func`, `loc`, `mp_paper`, `texts`, `id` | list rozvaděče ↔ blok `fve.switchboard` přes `parent_element_id` |
| **Prvek (element)** | `Element` (ř. 188) | `symbol_id`, `x`, `y`, `rotation`, `mirror`, `attrs: dict[str,str]` (vč. `ref`, `func`, `loc`, `in_`, `poles`…), `component_id`, `mp_pos`, `sl_pos`, `id` | → `Symbol` (knihovna), → artikl `Component` |
| **Přístroj** | odvozený: `model/xref.py:DeviceGroup`, `DeviceIndex.build` | skupina prvků se stejným `ref` v prostoru označení (cívka + kontakty) | žádná uložená entita „přístroj“ |
| **Symbol** | `model/symbol.py:Symbol` (ř. 81) | `id`, `name`, `category`, `iec_ref`, `function_class`, `primitives`, `ports: Port(name,x,y,dir)`, `attributes: Attribute(key,label,default,show,fmt,choices)`, `label_pos`, `multipole` | JSON soubor (`docs/LIBRARY_FORMAT.md`) → SQLite `symbols.data`; **symbol nemá pole verze** |
| **Artikl** | `library/components.py:Component` (ř. 92) | `id`, `manufacturer`, `part_number`, `name`, `category` (∈ `CATEGORIES`), `symbol_id`, `datasheet_url`, `source`, `footprint_id`, `params`, `price` | CSV (`docs/COMPONENTS.md`) → SQLite `components` (kategorie uložená v `params` JSON); `apply_to` propisuje parametry do atributů prvku (`PARAM_TO_ATTR`) |
| **Svorka** | bez vlastní třídy: prvek `sb.terminal_block` (skupina, `terminal_count`) / `fve.terminal`; `Wire.terminals[žíla] = {"a": "X1:3", "b": "F2:1"}` | čísla v atributu `terminal`, šířka `TERMINAL_WIDTH_MM = 6.2` | plán `model/terminal_plan.py:StripPlan/TerminalRow` (odvozený) |
| **Propoj / můstek** | `Sheet.bridges: dict[strip, list[list[str]]]` | skupiny čísel svorek | artikl můstku `model/bridges.py:resolve_bridge` (atribut `bridge_id`) |
| **Vodič** | `Wire` (ř. 326) + `WireEnd(element_id, port)` | `a`, `b`, `points` (lomy), `attrs` (ref, typ, průřez, uložení…), `conductors` (["L1",…,"PE"]), `terminals`, `id` | jednopólová čára nese všechny žíly; vícepól je odvozený pohled |
| **Kabel** | `Cable` (ř. 278) + `Core(name, number, color)` | `ref`, `type`, `cross`, `cores`, `shield`, `length`, `route`, `note`, `component_id` | odvozený z vodičů JPS `sync_cables` (vodič → kabel přes `attrs.cable_id`) |
| **Rozložení** | `Layout` (ř. 376), `Placement(element_id,row,pos)` | `rows`, `modules_per_row`, `enclosure`, `placements`, `params` (rozměry, IP, Icw, `wire_*`) | patří listu rozvaděče |
| **Struktura** | `StructureId(aspect, code, description)` | registr `=`/`+` kódů | `model/designation.py` |
| **Revize** | `Revision`, `RevisionMark` | `label`, `date`, `author`, `closed`, `marks`, `fingerprints` | `model/diff.py`, `model/revision.py` |
| **Připomínka** | `Note` | `sheet_id`, `x`, `y`, `w`, `h`, `text`, `status`, `reply`… | nepatří do dokumentace ani otisku |
| **Volný text** | `SheetText` | `x`, `y`, `text`, `height` | `Sheet.texts` |
| **Makro** | `library/macros.py:Macro` | `name`, `fragment` (prvky + vodiče), `version` (≤ `MACRO_VERSION = 3`), `variables: MacroVar`, `value_sets: ValueSet`, `repeat: Repeat`, `role` | JSON v `builtin/macros`, sdílené, `~/.envocad/macros`; vložení = fragment do listu |
| **Topologie** | `model/topology.py:Topology`, `ChainNode`, `CableLink` | `id`, `name`, `buildings`, `level` (`nn`/`vn`), `nodes` (role, ref, `per_inverter`, `sheet`, `existing`, `branch`, `macros`, `options`, `link`) | `TOPOLOGY_VERSION = 1`; JSON v `builtin/topologies`; role ∈ `generator/spec.py:ROLES` |
| **Specifikace generátoru** | `dict` – `generator/spec.py:DEFAULT_SPEC` (ř. 301), `load_spec` | stringy, střídače, DC/AC rozvaděče, kabely, `building`, `connection.level`, `chain.<role>.*`, baterie, optimizér | nemá dataclass ani verzi (neověřeno, zda existuje validace schématu nad rámec `parse_*`) |
| **Šablona rozvaděče** | `library/templates.py:Template` | `id`, `name`, `params`, `build` (Python callable) | rozšiřitelné pluginem |

**Formát uložení:** projekt `.ecp` = JSON `{"format": "envocad-project", "format_version": N, …}`
(`Project.to_dict`, ř. ~941). Zápis atomicky přes `.tmp` + `os.replace` se zálohou `.ecp.bak`
(`write_json_atomic`, ř. 1199). Načtení validuje strukturu → `CorruptProjectError` s českou zprávou; novější
verze → `ValueError` „aktualizujte EnvoCAD“.

**FORMAT_VERSION = 18** (`model/project.py:70`). Migrace `migrate(d, ver)` (ř. 1231–1321): datové převody
v2 (kind), v3 (bridges), v5 (porty stringu/střídače), v7 (můstky k listu), v8 (struktury, revize), v9 (notes),
v11 (DC+/DC− → L+/L−), v13 (`sb.feed_in/out` → `sb.feed`); ostatní verze (v4, v6, v10, v12, v14–v18) jen zvedají
verzi, aby starší program soubor odmítl. v16 převádí otisky revizí v `diff.upgrade_fingerprints`. Testy:
`test_migration.py` (20), soubory `tests/data/v12_*.ecp`, `v15_*.ecp`, `vicepol_rfve_rucne.ecp` (v16).
Knihovní SQLite (`~/.envocad/library.db`, schéma `library/store.py:21`) **nemá verzi schématu ani migrace**.
Makra mají `version` (1–3), topologie `version` (1), symboly a CSV artiklů verzi nemají.

---

## 3. Importy a exporty

| Formát | Směr | Stav | Soubor / funkce | Test |
|---|---|---|---|---|
| `.ecp` (JSON projekt) | čtení/zápis | H | `model/project.py:Project.save/load` | mnoho |
| Specifikace JSON → projekt | import | H | `generator/spec.py:load_spec`, `envocad/generate.py` (CLI `python -m envocad.generate spec.json out.ecp`), GUI „Nový projekt ze specifikace“ | `test_generate.py` |
| Skript `.ecs` | import (příkazy) | H | `cmd/script.py`, CLI `python -m envocad.cmd projekt.ecp skript.ecs [-o] [--json]` | `test_cmd_script.py` |
| DXF → symbol | import | H | `library/dxf_import.py:import_dxf`, `list_blocks`, GUI „Importovat symbol z DXF“ | `test_importers.py` |
| QElectroTech `.elmt` → symbol | import | H | `library/qet_import.py:parse_elmt`, `import_dir`; GUI | `test_importers.py` |
| EPLAN obchodní data CSV | import artiklů | H | `library/eplan_import.py:rows_from_commercial_csv`, `write_components_csv` | `test_importers.py` |
| EPLAN parts XML | import artiklů | H | `eplan_import.rows_from_parts_xml` | `test_importers.py` |
| EPLAN ZIP/EDZ s DXF → footprinty | import | H* | `eplan_import.footprints_from_zip` | test nenalezen |
| CSV artiklů (vlastní formát) | import | H | `store.import_components_csv_v2` (GUI), starší `store.import_components_csv` (jen test) | `test_components.py`, `test_model.py:63` |
| Šablona TZ/DSPS `.md` / `.docx` | import šablony | H | `export/doc_template.py:load_template`, `library/doc_templates.py` | `test_tz_dsps.py` |
| DXF listu (JPS / rozvaděč v jednopólové editaci), vrstvy `REVIZE`, `PRIPOMINKY` | export | H | `export/dxf_export.py:export_sheet_dxf` | 8 souborů |
| DXF vícepólu (strany vedle sebe nebo soubor na stranu) | export | H | `dxf_export.export_multipole_dxf` | `test_dxf_multipole.py` |
| DXF jednopólového schématu | export | H | `dxf_export.export_single_line_dxf` | 1 soubor |
| PDF listu / rozložení / A4 zmenšené | export | H (vyžaduje Qt) | `export/pdf_export.py` (`export_sheet_pdf`, `export_scene_pdf`, `export_layout_pdf`) | ano |
| PDF celé dokumentace (smíšené formáty, záložky, anotace) | export | H (Qt) | `export/doc_pdf.py:export_documentation_pdf`, `pdf_outline.py`, `pdf_annots.py` (pypdf) | ano |
| xlsx výkazy (všechny výkazy, listy) + pluginové výkazy | export | H | `export/xlsx_export.py:export_reports_xlsx` | ano |
| xlsx výrobní data | export | H | `xlsx_export.export_production_xlsx` | ano |
| docx protokol kusového ověření | export | H | `docx_export.export_routine_test_docx` | ano |
| docx TZ, DSPS | export | H | `export/tz_export.py:export_tz_docx`, `export_dsps_docx`, `export_report_docx` | ano |
| CSV štítků | export | H* | `ui/main_window.py:export_labels_csv` | ne |
| Export topologie / makra (uložení výběru jako makro) | export | H | `library/macros.py`, GUI „Uložit výběr jako makro“ | `test_macros.py` |
| BMEcat/ETIM, PVsyst PAN/OND, `.epdz`, DXF rozložení/plánu svorkovnice, formáty strojů na vodiče, Brady/Partex | – | P | nenalezeno | – |

---

## 4. Architektura, modularita, rozšiřitelnost

### 4.1 Vrstvy a závislosti

```
ui (PySide6) ──► cmd ──► model ◄── library
   │              │        ▲          ▲
   └──► export ◄──┘        └ generator┘
```
- `model/` – čistá data a geometrie (vč. výpočtů, kontrol, rozmisťování textů – `multipole_geometry`,
  `textlayout`, `single_line`), bez Qt a bez čtení nastavení (`test_model_pure.py:28`).
- `library/` – bez Qt, z nastavení čte jen umístění složek (`test_model_pure.py:33`).
- `cmd/` – bez Qt, import ověřen v podprocesu (`test_cmd_imports_without_qt`). Exporty PDF uvnitř `cmd/builtin.py:552–568`
  importují Qt líně (`ensure_qt_app`) – CLI tedy pro PDF potřebuje PySide6.
- `generator/` – dnes bez Qt (grep potvrzen), ale **test čistoty ho nehlídá** (`QT_FREE` neobsahuje `generator`).
- `export/` – smíšené: DXF/xlsx/docx bez Qt, **PDF (`pdf_export.py`, `doc_pdf.py`) závisí na PySide6** (QPdfWriter,
  `QUndoStack`, scény z `ui/`) – PDF nelze vyrobit čistě headless bez Qt.
- `ui/` – PySide6; zápisy do modelu mimo `ui/commands.py` hlídá `test_no_model_writes_in_ui.py` (45 výjimek
  `# model-write-ok`).
- Závislosti (`pyproject.toml`): PySide6, ezdxf, openpyxl, python-docx, pypdf; dev: pytest, pytest-cov, hypothesis,
  ruff, pyinstaller, pypdfium2, pillow. Python 3.11–3.14.

### 4.2 Rozšiřovací body

1. **Data bez kódu**: `~/.envocad/library/**` (`*.json` značky, `*.csv` artikly), sdílená síťová složka
   (`settings.shared_library_dir`), `~/.envocad/macros`, `topologies`, `doc_templates`, `aliases.json`.
   Přebíjení: vestavěné < uživatelské < sdílené (`store.sync_builtin`), u maker/topologií vlastní > sdílená > vestavěná.
2. **Importéry**: modul s rozhraním vstup → `Symbol` / řádky CSV (`dxf_import`, `qet_import`, `eplan_import`);
   formální rozhraní (ABC/Protocol) neexistuje – konvence.
3. **Pluginy existují**: `envocad/plugins.py` – `register(ctx)`, transakční registrace (kromě zápisů do knihovny),
   body: menu, šablony rozvaděče, importéry, výkazy, příkazy příkazového řádku (CLI `--plugins`). Pluginy běží
   s plnými právy, bez sandboxu a bez verzování API.
4. **Generátor**: registr `BOARD_BUILDERS` podle role (`generator/chain.py:builder_for`, `generator/boards/base.py:BoardBuilder`),
   topologie jako data, makra s rolí (`dc_tech`, `dc_route`, `ac_feed`, `ac_core`, `ac_eps`).
   Nová role ale vyžaduje kód v `generator/boards/` (pluginem ji registrovat nelze – neověřeno, v `PluginContext`
   metoda pro builder není).
5. **Kontroly**: pevný seznam v `checks.check_project`; plugin nemůže přidat kontrolu (v `PluginContext` chybí `add_check`).
6. **Výstupy**: `reports.*` (hlavička, řádky) + `ctx.add_report`; export formáty pluginem jen přes `add_menu_action`.

### 4.3 Příkazový řádek
`cmd/registry.py:CommandDef` (jméno = id akce MainWindow, `Param` typy point/port/selection/number/text/symbol/
choice/kv), příkaz = generátor výzev (`cmd/runner.py:Session`), transakce nad `sheets_state` → `ChangeSet`, GUI ho
pushne jako jeden `SheetsStateCommand`, CLI drží `Journal` (undo/redo). 20 příkazů (`insert`, `wire`, `move`, `copy`,
`rotate`, `mirror`, `delete`, `set`, `select`, `sheet`, `undo`, `redo`, `checks`, `save`, `script`, `export_dxf`,
`export_pdf`, `doc_pdf`, `help`, `zoom`/`fit` jen GUI). **Chybí** příkazy pro generátor, makra, rozložení, výkazy xlsx,
kabely, revize, přečíslování – tyto funkce jsou jen v GUI nebo v Python API.

### 4.4 Testy a CI
- 101 testovacích souborů, **1 424 funkcí `test_*`** (grep), 100 použití `parametrize` → skutečný počet sebraných
  testů je vyšší (nespuštěno). Největší: `test_gui_smoke.py` 52, `test_generator_f2.py` 47, `test_generate.py` 46,
  `test_wiring.py` 36, `test_macros.py` 35, `test_ratings.py` 32. GUI testy offscreen (`conftest.py`).
- Skipy: `test_dc_system.py:216,219` (chybí 1500 V artikly), `test_robustness.py:510` (jen POSIX),
  `test_wizard_topology.py:355` (snímky na vyžádání), `importorskip("PySide6"/"docx")`.
- Hlídací testy architektury: `test_model_pure.py`, `test_no_model_writes_in_ui.py`, `test_cmd_parity.py`,
  `test_changelog_d.py`, `test_check_licensed_data.py`, `test_scripts_encoding.py`, `test_settings_isolation.py`.
- Moduly, které **žádný test přímo neimportuje** (testují se jen nepřímo přes `build_project` / MainWindow):
  `generator/pv.py`, `generator/tigo.py`, `generator/boards/groups.py`, `generator/boards/macro_glue.py`,
  `ui/command_line.py`, `ui/notes_panel.py`, `ui/welcome.py`, `plugins_builtin/example_counts.py`.
- Pokrytí (`pytest-cov`) se v CI neměří (`ci.yml` volá `pytest -q --junitxml` bez `--cov`).
- CI `.github/workflows/ci.yml`: guard (`tools/check_licensed_data.py`, `ruff`) → testy Ubuntu + Windows × Python
  3.12 / 3.14 → PyInstaller build (smoke = existence binárky). Agentní workflowy: `agent-nightly.yml` (cron 01:00 UTC,
  orchestrátor nad issue `agent-ready`), `agent-mention.yml` (`@claude` od vlastníka), `agent-fix-ci.yml` (oprava
  červeného CI na větvích `agent/*`). Šablony issue/PR v `.github/`.
- Nástroje: `tools/check_licensed_data.py`, `tools/release.py`, `tools/gen_builtin_fve.py`, `tools/gen_builtin_macros.py`,
  `tools/bench_generate.py`, `tools/recategorize_qet.py`, `tools/setup_agent_labels.sh`.

---

## 5. Technický dluh

### 5.1 TODO / FIXME / XXX / HACK
`grep -rnE '\b(TODO|FIXME|XXX|HACK)\b'` přes `*.py`, `*.json`, `*.toml`, `*.yml` (bez `builtin/qet`): **0 výskytů**.
Dluh je evidovaný jen v `docs/ROADMAP.md`, `docs/NAVRH_TOPOLOGIE.md` kap. 6–7 a v GitHub issues (#79–#91), ne v kódu.

### 5.2 Velké soubory a funkce
- Soubory > 2 000 řádků: `ui/dialogs.py` 2 634 (145 funkcí, 15 tříd), `ui/main_window.py` 2 603 (169 funkcí),
  `model/project.py` 2 406 (kromě dataclass i odvozené symboly bloků/střídačů, vazby přívodů, kopírování, přejmenování).
  Dále `model/multipole.py` 1 913, `model/calc.py` 1 697, `ui/canvas.py` 1 241, `model/checks.py` 1 114.
- Funkce ≥ 120 řádků (AST): `model/multipole_geometry.py:348 _build` 399, `model/multipole.py:421 auto_layout` 393,
  `ui/dialogs.py:526 __init__` 306 (průvodce), `generator/pv.py:171 build` 192, `model/checks.py:70 check_project` 181,
  `ui/main_window.py:204 _build_actions` 156, `model/single_line.py:759 _draw` 145, `ui/dialogs.py:1734 __init__` 125,
  `model/single_line.py:165 _graph` 123.

### 5.3 Duplicity a nekonzistence
- Tři cesty ke stavbě obsahu rozvaděče: Python šablony `library/templates.py` (`build_ac_fve`, `build_dc_strings`),
  JSON makra `builtin/macros/*.json` a kód builderů `generator/boards/*` (`builtin` volba vs. makro). Stejné rozteče
  udržované ručně (`templates.DC_STRING_PITCH = 50` „jako makra“).
- Dva importy CSV artiklů: `store.import_components_csv` (starý, volný tvar, používá jen `tests/test_model.py:63`) a
  `import_components_csv_v2` (GUI).
- Zbytek po odebraném QR kódu: `FrameGeometry.rects` (`model/frame.py:70`, komentář „QR“) se nikde neplní, ale
  `ui/render.py:160,188` ho stále kreslí; komentáře o QR v `settings.py:29`, `ui/main_window.py:1044`,
  `multipole_geometry.py:133`.
- Komponenty v SQLite se nikdy nemažou (`DELETE FROM components` neexistuje) – artikl odebraný z CSV zůstane
  v `library.db` (u symbolů se maže jen seznam `LEGACY_FEEDS`). Neověřeno za běhu, plyne z kódu `store.py:158–190`.
- `LibraryStore.components()` načte všechny řádky a filtruje kategorii v Pythonu (kategorie je v JSON `params`,
  ne ve sloupci) – škáluje lineárně s knihovnou.

### 5.4 Slabá místa
- PDF export je navázán na Qt scény (`export/doc_pdf.py` importuje `QUndoStack`, scény GUI) – headless CI to řeší
  offscreen, ale API pro agenty bez Qt PDF neumí.
- Business logika v GUI: zápis CSV štítků (`main_window.py:2033`), import EPLAN orchestruje `main_window.py:2144–2170`.
- 83× `except Exception` v `envocad/` (většinou s `noqa: BLE001` a logem; 3× bez těla/pass – např. `store.py:101`).
- Generátor: výchozí spec dává 2 střídače, bytový dům = firma, uživatelské kopie starého makra „DC string po trase“
  se nemigrují (ROADMAP „Odloženo“).
- Výpočty (Iz, IEC 60890 k/c) jsou orientační, ve výstupech dosud neoznačené (ROADMAP Top10 #1, issue #80).
- Licence QET: `LICENSE` nezmiňuje výjimku pro CC BY 3.0 data (grep „QElectroTech|CC BY“ v `LICENSE` = 0),
  atribuce jen v `builtin/qet/ATTRIBUTION.md` a README (issue #81).
- Plugin API bez verze a bez sandboxu; kontroly a buildery generátoru pluginem rozšířit nelze.
- Specifikace generátoru je volný `dict` bez verze/schématu.

### 5.5 Netestované nebo slabě testované oblasti
- CSV štítků (`export_labels_csv`) – bez testu.
- `eplan_import.footprints_from_zip` – bez testu.
- `export_dsps_docx` – přímo nevolán (DSPS testováno přes `export_report_docx`, `test_tz_dsps*.py`).
- `export_multipole_dxf`, `export_single_line_dxf`, `add_bookmarks`, `add_note_annotations`, `validate_topology` –
  každý jen v 1 testovém souboru.
- Generátorové moduly bez přímého testu (viz 4.4); chování je kryto end-to-end testy generátoru a snapshotem.
- Pokrytí kódu se neměří.

### 5.6 Nesoulad dokumentace a kódu
| Dokument | Tvrzení | Skutečnost v kódu |
|---|---|---|
| `docs/ARCHITECTURE.md:279` | `FORMAT_VERSION` „aktuálně **17**“ | `model/project.py:70` = **18** (v18: A0, na výšku, vlastní formát – `migrate` ř. 1318) |
| `docs/LIBRARY_FORMAT.md:464` | „(`FORMAT_VERSION` 16)“ | 18 |
| `docs/ROADMAP.md:3` | odkaz na `docs/research/03_srovnani.md` | složka `docs/research/` v `main` neexistovala, soubor nenalezen |
| `docs/ROADMAP.md:86` | „QR v popisovém poli“ jako hotové | QR odstraněn (`changelog.d/2026-10-27-bez-qr-kodu.md`) |
| `docs/ROADMAP.md:104` | „Číslování stran“ `[ ]` s textem „hotovo 10/2026“ | stav checkboxu nesedí s textem |
| `docs/ROADMAP.md:36` | rámeček „logo doplnit po dodání“; ř. 105 „zbývá logo ENVO“ | logo je v `resources/envo_logo.json`, kreslí `frame.envo_logo` |
| `docs/design/ux_lista.md` | „Stav: **návrh** (kód se nemění)“ | lišty s ikonami jsou v GUI (README, `ui/icons.py`, `addToolBar`) – status neaktualizován |
| `docs/design/dluhy_dxf_jps.md:3` | „Formát projektu zůstává v9“ | historický údaj, dnes 18 |
| `CLAUDE.md` | `generator/` „BEZ Qt“ | pravda, ale nehlídá test (`QT_FREE` bez `generator`) |
| `docs/ARCHITECTURE.md:85` | „model nezávisí na UI“, export jako vrstva | PDF export závisí na `ui/` scénách (`doc_pdf.py`) |
| `examples/ukazka_fve.ecp` | ukázkový projekt | `format_version: 1` – projde migrací, ale neukazuje současné funkce |

---

## 6. Přehled pro další agenty (mezery pro rešerši zdrojů inspirace)

1. **Editor symbolů v GUI chybí** (Top10 #5). Jediná cesta k nové značce je ruční JSON nebo import DXF/QET.
   Inspirace: QElectroTech editor prvků, KiCad Symbol Editor, ProfiCAD.
2. **Data artiklů jsou neúplná** (rozměry, Pv, teploty, 1500 V DC) a **chybí strukturovaný import** BMEcat/ETIM.
   Hledat: otevřené parsery BMEcat/ETIM (Python), ETIM třídy pro MCB/SPD/svorky, mapování na `PARAM_TO_ATTR`.
3. **Výpočty nejsou ověřené proti normám** (Iz ČSN 33 2000-5-52, IEC TR 60890 k/c, ventilace obr. 5).
   Hledat otevřené referenční implementace / validační sady (pandapower, open-source kalkulačky kabelů, výstupy
   Rittal Therm, Hager hagercad) – jen fakta, ne text norem.
4. **PV výměna dat**: PVsyst .PAN/.OND (Top10 #7), SolarEdge Designer, EPLAN .epdz – chybí. Hledat open-source parsery
   PAN/OND (pvlib má `pvlib.iotools` – ověřit), dokumentaci `.epdz` (covagashi/ecad-view už v `docs/SOURCES.md`).
5. **Svorkovnice**: vícepatrové a N-odpojovací svorky (Top10 #10) – model nemá úroveň svorky; inspirace EPLAN
   „Terminal strip navigator“, WSCAD, QElectroTech terminal strip editor.
6. **DXF rozložení rozvaděče a plánu svorkovnice** (Top10 #9), výkres montážní desky, žlaby, vrtací plán –
   inspirace EPLAN Pro Panel, Rittal RiPanel, QElectroTech; knihovna ezdxf (bloky, layouty).
7. **Štítky a výroba**: jen CSV; chybí formáty Brady/Partex/Weidmüller M-Print a stroje na vodiče (Komax, Steinhauer)
   – hledat veřejné specifikace importních formátů.
8. **Ceny a objednávky** – pole existuje, výkaz ne (Top10 #8).
9. **Tisk** – jen PDF přes QPdfWriter; PDF vyžaduje Qt scény (žádný headless renderer). Zvážit renderer nad
   `Prim` geometrií (už existuje pro DXF) – inspirace: reportlab / pypdf / cairo backendy jiných CAD.
10. **Rozšiřitelnost**: plugin API nemá body pro kontroly F7, buildery generátoru ani exportní formáty; bez verze API.
    Inspirace: pluginy KiCad (pcbnew action plugins), QGIS, FreeCAD workbenches.
11. **Příkazový řádek** pokrývá jen editaci listu; generátor, makra, výkazy, revize a kabely nejsou příkazy –
    pro agenty důležité. Inspirace: CADCraft (už v SOURCES), AutoCAD/ZWCAD LISP/script.
12. **Knihovna SQLite** bez verze schématu, bez mazání zrušených artiklů, filtrace v Pythonu; plánovaný PostgreSQL
    pro sdílení – hledat vzory sdílených elektro knihoven (EPLAN Data Portal API, QET collections).
13. **Vícepól**: chybí ruční lomy žil a skutečné vícepólové značky – QET `qet.ap.*` jsou v knihovně, ale nevyužité.
14. **Lokalizace** – vše natvrdo česky (issue #91); chybí Qt i18n infrastruktura.
15. **Podepsaný Windows build** a distribuce (Top10 #6) – hledat postupy pro PyInstaller + code signing (signtool,
    Azure Trusted Signing).
16. Dokumentace má drobné nesoulady (FORMAT_VERSION 16/17 vs. 18, QR, neexistující `docs/research/03_srovnani.md`).
