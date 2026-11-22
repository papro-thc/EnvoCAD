# 02A – Rešerše: open-source projekty jako inspirace pro EnvoCAD

Stav k 22. 11. 2026. Agent 2A. Vstup: `docs/research/01a_inventura.md` (kap. 5, 6), `docs/research/01b_issues.md`.
Zdroje jsou webové stránky načtené přes WebFetch/WebSearch; co se z webu nepodařilo potvrdit, je označeno **neověřeno**.
Obsah stránek jsem bral jako data. Nic v kódu ani na GitHubu se neměnilo. Čísla `#NN` jsou issues EnvoCAD z 01b.

**Pravidlo pro licence (zkratka):** EnvoCAD je MIT. Kód pod GPL/LGPL nelze kopírovat do MIT repozitáře (ani po částech);
z GPL projektů lze brát **myšlenky, formáty a postupy** (autorské právo chrání výraz, ne nápad), ne zdrojový text.
Kód pod MIT/BSD lze převzít s uvedením licence. Datové sady (knihovny symbolů) mají licenci zvlášť od kódu.
Nejsem právník – licenční závěry níže jsou technické doporučení k ověření vlastníkem.

---

## 1. KiCad (EDA, C++/Python, schématický editor Eeschema)

### 1.1 Licence
- Kód: „GNU General Public License (GPL) version 3 or greater“, drobné třetí strany jinak (např. MIT) – https://www.kicad.org/about/licenses/
- Oficiální knihovny symbolů/footprintů/3D: **CC-BY-SA 4.0 s výjimkou** – výjimka se vzdává čl. 3 licence pro *návrhy a z nich generované soubory* (návrh nemusí být CC-BY-SA, ani nemusí nést atribuci), ale **redistribuce knihoven jako sbírky** musí zůstat CC-BY-SA se zachováním licenčních dokumentů – https://www.kicad.org/libraries/license/
- Závěr pro EnvoCAD: kód nekopírovat (GPL-3 ⊄ MIT). Knihovní symboly KiCadu (jsou to elektronické značky, pro FVE téměř nepoužitelné) do repozitáře nedávat – CC-BY-SA je share-alike a s MIT se míchat nemá. Formáty a postupy jako myšlenka: bez omezení.

### 1.2 Co převzít (myšlenky)

**a) Verze formátu souboru a UUID instance (řeší #85, #89, #91, mezeru „symbol nemá pole verze“, „spec bez verze“).**
- `.kicad_sch` nese `version` (datum YYYYMMDD) a `generator`; třetí strany mají mít vlastní identifikátor generátoru; objekty mají UUID; instance listů se identifikují řetězcem UUID (`/root-uuid/sheet-uuid`), takže jeden podlist může být použit vícekrát – https://dev-docs.kicad.org/en/file-formats/sexpr-schematic/
- Pravidlo kompatibility: novější KiCad načte starší soubory, starší novější odmítne s hláškou „vytvořeno novější verzí“ – https://docs.kicad.org/8.0/en/eeschema/eeschema_symbols_and_libraries.html (+ forum, viz níže); dokumentace formátu popisuje změny jen po tokenech („od verze 7“), forward kompatibilitu neřeší – https://dev-docs.kicad.org/en/file-formats/sexpr-intro/
- EnvoCAD už to dělá u `.ecp` (`FORMAT_VERSION`, `migrate`). Chybí u symbolů (JSON), CSV artiklů, spec generátoru a SQLite knihovny. Návrh: pole `format_version`/`generator` do symbolu a spec JSON; „novější → odmítnout s českou hláškou“ jako u `.ecp`.
- Instanční UUID podlistů: relevantní pro #71 (Duplikovat list) – duplikovaný list = nové id, vazby (`parent_element_id`, xref) se přemapují; KiCad to řeší cestou UUID místo jména.

**b) ERC – matice konfliktů pinů, závažnosti, výjimky (řeší hlavně rozšiřitelnost kontrol, #80 označování nálezů, návaznost na `checks.py`).**
- KiCad drží výchozí tabulku „úroveň chyby pro dvojici typů pinů“ (Pin Conflicts Map, uživatelsky měnitelná), závažnost *každého pravidla* (`rule_severities`: error/warning/ignore) a **seznam výjimek** (`m_ErcExclusions`) – vše uloženo v projektu. Zdroje: https://docs.kicad.org/9.0/en/eeschema/eeschema.html (typy pinů, ERC text-proměnné), https://docs.kicad.org/doxygen/erc__settings_8h_source.html, https://hub.allspice.io/AllSpiceMirrors/kicad/src/branch/master/eeschema/erc/erc_settings.cpp (zrcadlo zdrojáku).
- Přenositelná myšlenka: `Finding` v EnvoCAD má `severity` a `code` (cca 80 kódů). Doplnit **per-kód závažnost v projektu** (vypnout/povolit/chyba) a **seznam „waived“ nálezů s důvodem** (stabilní klíč = kód + id prvku). Dnes kontrola je pevná a nelze ji potlačit – u 80 kódů to vede k „únavě z varování“.
- Typy pinů s ERC (input, output, power in/out, passive, unspecified…) – EnvoCAD má `Port(name,x,y,dir)` bez elektrického typu. U FVE by byl použitelný zjednodušený typ (zdroj DC, zátěž, PE, N) → kontrola „zdroj proti zdroji“. Oborové rozhodnutí je na člověku (CLAUDE.md) – jen námět.
- Výstup ERC v CI: `kicad-cli sch erc --format json --severity-* --exit-code-violations` (návratový kód 5 při nálezu) – https://docs.kicad.org/9.0/en/cli/cli.html. Pro EnvoCAD: příkaz `checks` v CLI s `--json` už existuje (inventura 4.3); doplnit návratový kód podle závažnosti.

**c) Headless CLI nad schématem (řeší bod 11/9 inventury: CLI bez PDF/BOM/generátoru, PDF jen přes Qt).**
- `kicad-cli sch export pdf|svg|dxf|bom|netlist|python-bom`, `sch erc`; PDF „jedna stránka na list“, volby `--exclude-pdf-hierarchical-links`, `--exclude-pdf-property-popups`, `--exclude-pdf-metadata` – https://docs.kicad.org/9.0/en/cli/cli.html. Důležité pro #73: KiCad exportuje PDF **s hierarchickými odkazy** a popup vlastnostmi, a volí se vypnutím – tj. je to výchozí. Jak přesně je technicky vyřešeno (vlastní PDF plotter), jsem neověřoval.
- BOM: preset uložený ve schématu (`--preset`), pole/popisky (`--fields`, `--labels`), `--group-by`, `--sort-field`, filtr, vyloučení DNP – tentýž model pro #68/#87/#102: výkaz jako *pojmenovaný preset* (pole, seskupení, řazení, filtr), ne pevná funkce `reports.*`.

**d) Tabulka polí symbolů – hromadná úprava (řeší #77, #74, #103).**
- *Symbol Fields Table*: tabulka všech symbolů, sloupce = pole, rozsah (list / podlisty / projekt), filtr referencí se zástupnými znaky, skupiny podle polí, copy/paste rozsahů s **automatickým inkrementem**, přidání/přejmenování/smazání pole pro všechny symboly; pole začínající `ki_` jsou rezervovaná (= chráněné klíče) – https://docs.kicad.org/9.0/en/eeschema/eeschema.html
- Pro EnvoCAD: `attrs: dict[str,str]` je ideální pro tabulkový editor (prvky v řádcích, klíče ve sloupcích). Konvence „rezervovaný prefix“ vyřeší dnes rozptýlený seznam chráněných atributů (#77 vs #98: `ref`, `terminal(s)`, `contacts`, `ports_in/out`…) – jedna konstanta `PROTECTED_ATTRS`/prefix.
- Find & Replace: v dokumentaci je v obsahu uvedeno „Find tool“ a „Search panel“, jejich obsah jsem **nepřečetl** (neověřeno).

**e) Anotace (číslování) s volbami (řeší #71, přečíslování `renumber.py`).**
- Nástroj Annotation: rozsah celý projekt / list / výběr, volitelně včetně podlistů; „přečíslovat vše / jen nenaznačené“; řazení podle X nebo Y; start od 0 nebo od čísla listu; zpráva a „Clear annotation“ – https://docs.kicad.org/9.0/en/eeschema/eeschema.html
- EnvoCAD `renumber.plan` + dialog jsou funkčně podobné; z KiCadu lze vzít volbu *„start od čísla listu“* (číslování začíná podle čísla listu) jako námět pro rozvaděče v #71. Konkrétní schéma značení rozvaděčů je oborové rozhodnutí.

**f) Knihovny z databáze – `.kicad_dbl` (řeší #84, #83, #86, model artiklů).**
- Databázová knihovna: konfigurační JSON mapuje *tabulku SQL* (ODBC/SQLite) na symboly: `table`, `key`, sloupec `symbols` (`Knihovna:Symbol`), `footprints`, seznam `fields` (sloupec → jméno pole, viditelnost, zobrazení ve výběru). Zdroj: https://docs.kicad.org/9.0/en/eeschema/eeschema_advanced.html (přes výsledek hledání), hlavička `database_lib_settings.h` (enum `DATABASE_SOURCE_TYPE`: ODBC, SQLITE, ACCESS) – https://docs.kicad.org/doxygen/database__lib__settings_8h.html
- Odkaz na komunitní příklady se SQLite a CSV: https://github.com/git-plm/parts, https://codeberg.org/HallMonitorTurtleTown/kicad_lib, diskuze CSV bez databáze https://forum.kicad.info/t/kicad-dbl-using-csv-without-external-binary-database/71506
- Přenositelné: **deklarativní mapování sloupec → atribut prvku** jako data (dnes `PARAM_TO_ATTR` v kódu `library/components.py`). Dovolilo by přidat mapování pro nový zdroj (BMEcat, PVsyst) bez kódu. Dále: jeden „klíč“ (`part_number` + výrobce) a symbol odkazovaný jménem, ne vložený.

**g) Pluginy – verze API a metadata kompatibility (řeší „plugin API bez verze a bez bodů pro kontroly/exporty“).**
- Plugin and Content Manager (PCM): balíček má `versions[]` s `kicad_version` (min., povinné), `kicad_version_max` (nepovinné), `status` (stable/testing/development/deprecated), `runtime` (`ipc`/`swig`, od 9.0.1), `download_sha256`, schéma balíčku `v1`/`v2` (v2 pro KiCad 10.0+ přidává typy `fab`, `datasource`) – https://dev-docs.kicad.org/en/addons/
- IPC API: pluginy jako samostatné procesy, zprávy v Protocol Buffers přes NNG na socketu; „po stabilizaci nové verze mohou přidávat zprávy a pole, ale nemění význam stávajících; deprecated položky zůstanou aspoň jednu hlavní verzi“ – https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/ (stabilizace plánována pro 9.0; zda je skutečně stabilní, **neověřeno**).
- Pro EnvoCAD: do `register(ctx)` přidat `API_VERSION` (např. `"1"`) a plugin deklaruje `requires_api >= 1`; zastaralé metody ponechat 1 minor. Nové body (`add_check`, `add_export`, `add_board_builder`) nejdřív jako „experimentální“. Proces-izolaci (IPC) pro MIT desktopový nástroj s Python pluginy nepřebírat – zbytečně těžké (L).

**h) Lokalizace bez Qt v modelu (řeší #91).**
- KiCad: gettext `.po` v `translation/pofiles/*.po`, skript `update-po-files.sh`, překlady přes hostovaný **Weblate** (https://hosted.weblate.org/projects/kicad/, 38 jazyků, ~18,7 tis. řetězců k okamžiku snímku – údaj z cache vyhledávače, může být zastaralý) – https://dev-docs.kicad.org/en/translation . 
- Význam: gettext je **nezávislý na Qt**, dá se použít v `model/`, `generator/`, `cmd/` (hlášky `Finding`), kdežto Qt `tr()` jen v `ui/`. QElectroTech používá Qt Linguist (viz kap. 3). Pro #91: stdlib `gettext` + `.po` (bez nové závislosti) pro hlášky z jádra; `tr()` v `ui/`. Rozhodnutí je na vlastníkovi.

**i) Tři úrovně kompatibility knihovny.** Starší `.lib` KiCadu zůstalo jen pro čtení a migruje se (docs 7.0 přes výsledek hledání) – vzor pro „starou verzi uživatelských maker/symbolů nahradit až po varování“ (#69).

### 1.3 Issue tracker KiCadu (GitLab) – co jsem našel
- Odkaz na slajdy FOSDEM 2026 „KiCad ERC love letter“ (https://fosdem.org/2026/events/attachments/3999GS-kicad-erc-love-letter/slides/267701/presentat_lyne5sk.pdf) – zmiňuje, že matice konfliktů je hůře konfigurovatelná než ostatní kontroly; slajdy jsem **nečetl**.
- Merge request „Database Libraries infrastructure“ https://gitlab.com/kicad/code/kicad/-/merge_requests/1282 – jen jako odkaz z výsledků, obsah **neověřen**.
- K ERC „override pin type“ existuje starý požadavek https://bugs.launchpad.net/bugs/1526213 (jen z výsledků, obsah neověřen).
- Do GitLab trackeru jsem se systematicky neprokopal (WebSearch ho nevrací); hloubkovou rešerši issue trackeru označuji jako **nedokončenou**.

---

## 2. Horizon EDA (C++/GTK, pool knihoven, JSON)

### 2.1 Licence
- Kód: GPL-3.0 (repozitář), přibalené komponenty MIT/Boost/GPLv2/GPLv3 – https://github.com/horizon-eda/horizon
- Pool (knihovna): licence **neověřena** (dokumentace pool-why ji nezmiňuje; oficiální pool `horizon-pool` je samostatný repozitář).
- Závěr: kód nekopírovat; architektura „pool“ je volně použitelná jako myšlenka.

### 2.2 Co převzít
**a) Pool = JSON soubory jako zdroj pravdy + SQLite jako generovaný index** (řeší: knihovna SQLite bez verze/mazání/filtrace v Pythonu, #101, #75).
- Každý prvek (unit, entity, symbol, part, package…) je **jeden JSON soubor** kdekoli pod odpovídajícím adresářem; metadata všech souborů se agregují do SQLite databáze, kterou lze znovu sestavit tlačítkem „Update pool“; identita = typ + UUID, při shodě vyhrává pool výše v seznamu zahrnutých poolů; organizace štítky místo složek – https://docs.horizon-eda.org/en/latest/pool-why.html, https://docs.horizon-eda.org/en/latest/pool-mgr.html
- EnvoCAD už má stejný princip (builtin JSON/CSV → SQLite, přebíjení builtin < user < shared). Z Horizonu přijmout: (1) **SQLite je jen index (smazatelný, znovu sestavitelný)** – vyřeší chybějící verzi schématu a „artikl odebraný z CSV zůstane v DB“ (jednoduše přestavět DB při změně `schema_version` nebo `sync` vždy `DELETE` zdrojů, které zmizely); (2) stabilní **UUID** artiklu/symbolu místo `id` odvozeného z názvu (pomáhá archivu #75/#101); (3) štítky (`tags`) jako ploché filtrování.
- Důležité rozlišení: Horizon index je *odvozená cache*, EnvoCAD má v SQLite i uživatelská data (`~/.envocad/library.db`) – nejdřív oddělit.

**b) Verze po typu souboru** (řeší #85, #75, spec generátoru).
- „Každý typ souboru má vlastní číslo verze místo verze aplikace; zvýší se jen při změně, kterou starší verze nezvládne; novější verze vždy otevře starší; varování při otevření ve starší verzi“ – https://docs.horizon-eda.org/en/latest/version.html
- Odpovídá EnvoCADu: `FORMAT_VERSION` (projekt), `MACRO_VERSION`, `TOPOLOGY_VERSION`; doplnit `SYMBOL_FORMAT_VERSION`, `SPEC_VERSION`, `ARCHIVE_VERSION` (pro `.ecpz` z #75) – drobné (S). Pozn.: Horizonu zdroj o migraci `pool.db` **jsem nenašel** (vyhledávání nevrátilo nic z repozitáře Horizon).

**c) Datový model Part / Entity / Unit / Symbol** (řeší #85 editor symbolů, #84, model artiklů).
- Part → jeden Entity (logická netlist) + Package (footprint) s mapou pinů → pad; Entity z jednoho/více Unit; Unit definuje piny (jméno, **směr pro ERC**, alternativní jména); Symbol je *vzhled* Unitu a piny nedefinuje; **Part může dědit** z base partu (rodina lišící se jednou vlastností); parametrická data zatím jen pro rezistory a kondenzátory – https://docs.horizon-eda.org/en/latest/pool-elements.html
- EnvoCAD: `Component` (artikl) ukazuje na `symbol_id` a `footprint_id`; atributy a porty jsou v symbolu. Z Horizonu: **dědění artiklu od „základního artiklu“** (řada jističů B/C 6–63 A sdílí rozměry, Pv, symbol; liší se `In`/charakteristika) by snížilo duplicity v 32 CSV (1 392 řádků) a pomohlo s neúplnými daty (#83: 222 bez rozměrů) – ale pozor: oborově „co je společné“ rozhoduje člověk. Odhad M.
- Pracovní postup tvorby partu: 1) z existujícího partu s „inherit“ checkboxy, 2) z existující entity, 3) čistý wizard (piny z CSV/JSON, `Link Pads`) – vzor pro dialog „Nový artikl z artiklu“.

**d) Python modul** (řeší headless exporty): umí otevřít projekt, schéma/desku a exportovat **PDF a BOM ze schématu**, spouštět DRC; úpravy návrhu nepopisuje – https://docs.horizon-eda.org/en/latest/python.html, CLI https://docs.horizon-eda.org/en/latest/cli-usage.html (obsah CLI nečten). Potvrzuje cíl „headless PDF/BOM“ v EnvoCADu.

**e) Hierarchické schéma** – sekce „Hierarchy“ ve Schematic Editoru (https://docs.horizon-eda.org/en/latest/imp-sch.html); obsah nečten (**neověřeno**). Zda a jak Horizon používá bloky s UUID, jsem neověřil.

---

## 3. QElectroTech (Qt/C++, nejbližší funkčně: elektro-dokumentace, svorkovnice, BOM)

### 3.1 Licence
- **Kód:** GNU GPL (repozitář uvádí GPL-2.0) – https://github.com/qelectrotech/qelectrotech-source-mirror, manuál http://download.qelectrotech.org/qet/manual_0.7/ (výsledek hledání: „Free Software released under the GNU / GPL“).
- **Sbírka prvků (elements) – zvlášť:** `ELEMENTS.LICENSE`: **CC BY 3.0**; platí při redistribuci sbírky (celé nebo její části, upravené i ne) **mimo elektrické schéma**; použití, úprava a vložení prvků **do schémat je bez podmínek**, bez ohledu na licenci schématu; **zákaz použití software nebo souvisejících souborů jako vzorových dat pro trénink modelů strojového učení** – https://raw.githubusercontent.com/qelectrotech/qelectrotech-source-mirror/master/ELEMENTS.LICENSE
- Závěr pro EnvoCAD (#81): EnvoCAD **redistribuuje** 673 QET prvků jako knihovnu → CC BY 3.0 s atribucí platí; „zákaz ML“ je omezení nad rámec čistého CC BY (kolize s deklarovanou svobodou MIT / použitelností agenty? – k posouzení vlastníkem). Doporučuji: oddělený `LICENSE-DATA`/`ATTRIBUTION`, zmínit CC BY 3.0 a oznámit změny (viz `01b` – starý odkaz `elements_license` – neověřeno); QET kód (GPL-2.0) **nikdy** nekopírovat. Vlastní práce odvozená z cizích prvků (DXF → prvek) je „modified version“ pod CC BY 3.0.

### 3.2 Co převzít (myšlenky)
**a) Svorkovnice – Terminal strip manager** (řeší #89 vícepatrové svorky, #88).
- ChangeLog 0.100: nový typ `TerminalStripItem`, **editor svorkovnice s náhledem rozložení**, ukládání do `.qet`, undo, **můstky a propoje kreslené v editoru**; v 0.8 svorky dostaly UUID – https://raw.githubusercontent.com/qelectrotech/qelectrotech-source-mirror/0.100/ChangeLog. Vývoj byl „v pozdním stavu, něco se neukládalo“, větev pozastavena při přechodu Qt5→Qt6 (fórum, výsledek hledání: https://qelectrotech.org/forum/viewtopic.php?pid=22883 a související; **neověřeno**).
- Fórové problémy (užitečné jako seznam případů, které EnvoCAD musí pokrýt): vícepatrové svorky (https://qelectrotech.org/forum/viewtopic.php?pid=21920 – „qet_tb_terminal plugin… zvláštní zacházení pro vícepatrové“), svorky bez vodiče plugin nevidí (https://qelectrotech.org/forum/viewtopic.php?id=2387), dvoupatrová svorka nejasná (https://qelectrotech.org/forum/viewtopic.php?id=1961), centrální GND / +24 V (jedna svorka, mnoho zařízení).
- Starší externí plugin `qet-tb-generator` (Python; generuje svorkovnice z projektu) – licence **neověřena** (stránka PyPI se nenačetla). Použít jako zdroj *zadání případů*, ne kódu.
- Doporučení: model svorky jako entity s `level`/`row` (EPLAN i Autodesk: `X1:1` + patro), nikoliv číselný atribut; tabulka „vícepatrové svorky“ pro AutoCAD Electrical i SOLIDWORKS Electrical (https://help.solidworks.com/2023/English/swelec/c_swelec_EwUiDialogTerminalDeckManager.htm, https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-Electrical/files/GUID-BB0969FC-E649-42CA-BF11-240C26E2C078.htm) – jen jako odkaz z výsledků, **nečteno**.

**b) Nomenklatura/BOM jako SQL dotaz nad projektem** (řeší #68, #87, #102, #67).
- v0.4 CSV export; **v0.8 přepsaná CSV nomenklatura**: uživatel volí pole a pořadí, filtruje podle typu prvku (vše / svorky / spínače), záhlaví zapnout/vypnout, **ukládá/načítá konfigurace, vlastní SQL dotaz**; sumární tabulka; **BOM tabulky vložené do projektu**, pojmenované, umístěné na libovolný list, propojené napříč listy, automaticky se přizpůsobí (ChangeLog výše). Stránka o nomenklatuře: nastavení tabulky lze importovat/exportovat zvlášť, obsah je SQL dotaz z dialogu; velké tabulky se dělí na více propojených listů (https://github.com/qelectrotech/qelectrotech-source-mirror, README).
- Pro EnvoCAD: výkaz jako **uložená konfigurace** (pole, pořadí, filtr, seskupení, řazení) v projektu – sjednotí #68 (po výrobcích), #87 (ceny), #102 (case-insensitive: normalizace v dotazu) a #76 (legenda): „výkaz = konfigurace + datový zdroj“. Tabulka v SQLite *nad projektem* (in-memory view) je techniku lze převzít jako myšlenku (S–M), nic z jejich kódu.

**c) Editor prvků** (řeší #85 – hlavní vzor).
- Vestavěný editor, uložení do uživatelské kolekce; sbírka QET je **jen pro čtení**, po vložení do schématu se kopie uloží do kolekce „imported“ (projektová/vložená) – http://download.qelectrotech.org/qet/manual_0.7/build/element/collection/what_is.html (zjištěno ze snippetu hledání). Vývoj: v0.5 UUID tag v XML prvku; v0.7 informace prvku v editoru, zarovnání textů, bod vkládání/odebírání polygonu; v0.8 **multi-edit**; v0.3 automatický hotspot (ChangeLog výše).
- Pro EnvoCAD fázi 1: (1) read-only builtin vs. uživatelská kolekce (už je), (2) **kopie do projektu** (embedded) – řeší přenositelnost, souvisí s archivem `.ecpz` (#75, #101), (3) editor jen na **porty a atributy** (fáze 1) + náhled, kreslení primitiv až později (matchuje zadání #85).
- Poznámka k dnešnímu stavu: kolekce QET jsou typu Common / Company / Custom / Embedded (doxygen `qet.h`: https://download.qelectrotech.org/qet/doxygen/html/de/d87/qet_8h.html – z výsledku hledání), což je přesně trojice builtin / sdílená / uživatelská + vložená v projektu.

**d) Formát souboru:** projekty `*.qet` a prvky `*.elmt` jsou XML (man page https://mankier.com/1/qelectrotech, výsledek hledání). Detailní schéma **neověřeno** (není dokumentované v hledaných zdrojích). Importér EnvoCADu (`qet_import.py`) už `.elmt` čte.

**e) Lokalizace:** Qt Linguist `.ts/.qm`, `lupdate`/`lrelease`, překlad se oficiálně integruje při **> 90 %** pokrytí aplikace; překlady prvků (jména v `.elmt` a `qet_directory`), menu zkratek, manuálu a README; změna jazyka v menu od v0.4; v0.100 velké aktualizace DE, FR, NL, SV, IT, PL, PT-BR, SR, zh-CN a oprava i18n v CMake – https://qelectrotech.org/wiki_new/en/doc/translation, ChangeLog 0.100. (Popis workflow je z části zastaralý – Qt4 nástroje.)
- Pro #91: prahová hodnota úplnosti překladu a **překlad i dat knihovny (jména prvků/symbolů)** – EnvoCAD ho dnes nemá vůbec; navrhuji pole `name` jako slovník `{ "cs": ..., "en": ... }` v JSON symbolu s `cs` jako povinným.

**f) DXF:** export celého projektu (0.4), import DXF v editoru prvků přes externí `dxf2elmt` (0.9), problémy s ořezáním metadat při importu (0.100) – ChangeLog. EnvoCAD má vlastní `dxf_import` na ezdxf; nic nepřebírat.

**g) Pluginy (qet-tb-generator):** externí Python skript volaný z aplikace, detekce chybějícího pluginu s návodem (ChangeLog 0.7). Poučení: externí proces bez API = křehké (nevidí neprodrátované svorky). Kontrast s vnitřním `register(ctx)` v EnvoCADu – ten je lepší.

---

## 4. FreeCAD (a workbench pro elektro)

### 4.1 Licence
- Jádro: většinou **LGPL-2.1-or-later** (Addon Academy, Wikipedie); některé zdroje uvádějí LGPL-2.0+ – https://freecad.github.io/Addon-Academy/Topics/Licensing, https://wiki.freecad.org/License . FreeCAD do jádra přijímá jen LGPL, MIT nebo BSD (stejná stránka).
- Addon **Cables** (sargo-devel): kód LGPLv3, modely v presetech CC BY 4.0 – https://github.com/sargo-devel/Cables

### 4.2 Relevance
- V hledání se neobjevil žádný „elektro-schematický“ workbench FreeCADu; **Cables Workbench** (https://wiki.freecad.org/Cables_Workbench/en) je 3D trasování kabelů/přístrojů v architektuře (konektory, krabice, svítidla, kabelové žlaby, „Cables ElectricalDevice“). Odkaz z fóra QET (https://qelectrotech.org/forum/viewtopic.php?id=3093): domácí schéma v QET → import do FreeCADu → trasování kabelů; autor píše, že to nezkoušel (experimentální).
- Co je užitečné pro EnvoCAD: (1) **pluginový model „workbench“** – FreeCAD má Addon Manager s metadaty (`package.xml`, SPDX licence, verze FreeCADu) – obdoba PCM KiCadu; jako myšlenka pro verzi API pluginů (viz KiCad 1.2g); (2) 3D rozložení rozvaděče (STEP) – **mimo rozsah** EnvoCADu (2D DIN lišty), ale „kabelová délka po trase“ (EnvoCAD `wiring.py`) odpovídá WireFlex v Cables – jen myšlenka; (3) licenčně: kód FreeCADu/Cables (LGPL) do MIT nekopírovat; jako závislost by LGPL knihovna byla použitelná (dynamické linkování), ale FreeCAD je velká aplikace – **ne**.
- Závěr: pro cílový problém (schéma + rozvaděč + výkazy) je FreeCAD **málo relevantní**; hlavní hodnota je u workflow pluginů. Další komerční „harness“ (SEE Harness Engineering) jen jako reference (ne open-source).

---

## 5. ezdxf (Python, **MIT**) – přímá závislost EnvoCADu

### 5.1 Licence
- MIT – https://ezdxf.readthedocs.io/en/stable/ (lze převzít kód i používat jako závislost; EnvoCAD už závislost má).

### 5.2 Co využít (řeší #88 DXF rozložení, headless renderer, PDF bez Qt)
- Layouty a bloky (modelspace / paperspace, `Page.from_dxf_layout`) – https://ezdxf.mozman.at/docs/addons/drawing.html. Pro #88: rozložení rozvaděče/plán svorkovnice zapsat jako **bloky** (přístroj = blok s ATTRIB: `ref`, artikl), DIN lišty a žlaby jako vrstvy, rozměrování přes dimension entities (tutoriál: https://ezdxf.readthedocs.io/en/stable/) – bez nových závislostí.
- **Drawing add-on** (`ezdxf.addons.drawing`): backendy Matplotlib (PDF/SVG/PNG), **PyMuPdfBackend (PDF/PNG; vyžaduje `pymupdf`)**, SVGBackend (bez dalších balíčků), PlotterBackend (HPGL/2), DXFBackend, PyQtBackend (PySide6 viewer), JSON backendy; `Layout/Page/Settings` (`fit_page`, `scale`, `crop_at_margins`, ořez u SVG/PyMuPDF/PLT) – https://ezdxf.mozman.at/docs/addons/drawing.html
  - **Licenční pozor:** dokumentace výslovně uvádí, že **PyMuPDF je AGPL**. Použít ho jako závislost v MIT aplikaci distribuované jako binárka je rizikové (AGPL se šíří) – **nedoporučuji**; neplatí totéž pro SVGBackend ani Matplotlib (BSD-style, těžká závislost). 
  - Omezení: vykreslování je jen pohled shora, 3D se promítá, `VISUALSTYLE` nepodporováno (tamtéž).
- Návrh „headless PDF“: DXF už EnvoCAD generuje → SVGBackend (bez závislosti) → SVG→PDF přes `pypdf`? (pypdf SVG neumí – **neověřeno**, nutná další knihovna např. cairosvg/svglib/reportlab; ověřit licence). Alternativa: vlastní renderer z `Prim` geometrie (už existuje pro DXF) do `reportlab` (BSD). Tato rešerše patří spíš do agenta 2x pro PDF.
- Další prvky ezdxf pro EnvoCAD: `TablePainter` add-on (tabulky z textových/blokových buněk, styly ohraničení) – vhodné pro **legendu značek (#76)** a rohové tabulky na listu v DXF; `ezdxf.audit`, `ezdxf.addons.importer` (import entit mezi dokumenty – kopie listů, vkládání maker do DXF) – nad rámec fetchnutých stránek, **neověřeno** podrobně.

---

## 6. pandapower (Python, **BSD-3-Clause**) a pvlib (BSD-3-Clause)

### 6.1 pandapower
- Licence BSD 3-Clause (badge v repozitáři) – https://github.com/e2nIEE/pandapower (verifikováno z README; text LICENSE jsem nečetl). Závislosti: pandas, numpy, scipy (+ volitelné solvery) – **těžké pro desktopový nástroj**, ne jako závislost.
- Datový model **std_types** (řeší oblast výpočtů #79/#82): řádek tabulky vedení: `r_ohm_per_km`, `x_ohm_per_km`, `c_nf_per_km`, **`max_i_ka`**, `type` (`cs` kabel / `ol` venkovní), **`q_mm2`**, `alpha` (teplotní koeficient, doplňuje se `add_temperature_coefficient()`), `voltage_rating` (LV/MV/HV); jména konstrukce typu „NAYY 4x50 SE“; DC tabulka bez reaktance a kapacity; hodnoty kompatibilní jen s 50 Hz – https://pandapower.readthedocs.io/en/latest/std_types/basic.html. **Zdroj hodnot v dokumentaci nenalezen** (neověřeno) – nelze je považovat za validační referenci k normě (CLAUDE.md: normativní data rozhoduje člověk).
- Zkratové proudy: modul `shortcircuit` „podle DIN/IEC EN 60909“ – https://pandapower.readthedocs.io/en/latest/shortcircuit.html. Použití: **referenční validace** vlastního výpočtu `Ik` (selektivita, Icu) **v testech** (dev-závislost, ne runtime), aby se výpočty EnvoCADu ověřily na malých sítích (#80, #82 – „ověřitelnost výpočtů“). Kód pandapower do EnvoCADu nekopírovat (zbytečně velký); BSD by to ale i s citací dovolila.
- Pro oteplení rozvaděče (IEC TR 60890) a Iz podle ČSN 33 2000-5-52 pandapower **nic nenabízí** (tvrzení z toho, co jsem našel – úplnost modulů neověřena).

### 6.2 pvlib (jen PAN/OND parser)
- `pvlib.iotools.read_panond(filename, encoding=None)` – čte PVsyst `.pan` a `.ond` do vnořeného `dict`; zdroj https://github.com/pvlib/pvlib-python/blob/main/pvlib/iotools/__init__.py (export `read_panond`), https://raw.githubusercontent.com/pvlib/pvlib-python/main/pvlib/iotools/panond.py, https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.iotools.read_panond.html
  - Parser je **odvozený z inferované logiky** (PVsyst formát nepublikoval); jen stdlib (`open`, řetězce), žádné další balíčky; vnoření = **dvoumezerové odsazení**, řádek s `=` je položka, řádky bez `=` se vynechají; typy odvozené z textu (čárka → seznam, tečka → float, jinak int, jinak řetězec), **jednotky nepřevádí** (PVsyst výchozí), typy mohou být špatně; někdy potřebuje `encoding='utf-8-sig'`.
  - Licence pvlib: **BSD-3-Clause** (PyPI metadata https://pypi.org/pypi/pvlib/json); závislosti jádra numpy, pandas, scipy, h5py, pytz, requests, tzdata → **jako závislost nepřijatelné**.
  - Doporučení (řeší #86): napsat vlastní parser ~100 řádků po vzoru logiky (BSD-3 dovoluje přepsání s atribucí, nebo čistě z myšlenky), do `library/pvsyst_import.py` podle vzoru `eplan_import.py`, **explicitní mapa klíč → sloupec + jednotky** a test na vlastních smyšlených vzorcích (bez datových souborů výrobců – CLAUDE.md zakazuje licencovaná data v gitu). Konkrétní klíče `.PAN` (např. Voc, Isc, Vmpp, Impp, `muVocSpec`, `muISC`) a `.OND` (`PNomAC`, `VAbsMax`, `VMppMin/Max`, `IMaxDC`…) **jsem nepotvrdil** z veřejného zdroje – musí je ověřit agent nad skutečným souborem.
  - Pvlib má pro PV výpočty i jiné prvky (modely modulů, teplotní koeficienty), ale pro EnvoCAD (Uoc/Isc při teplotách) stačí vlastní vzorce.

---

## 7. Srovnání licencí a kompatibility s MIT

| Projekt | Kód | Data / knihovny | Lze kopírovat kód? | Závislost? | Myšlenka? |
|---|---|---|---|---|---|
| KiCad | GPL-3.0+ | CC-BY-SA 4.0 s výjimkou pro návrhy | ne | ne (jiný jazyk) | ano |
| Horizon EDA | GPL-3.0 | pool: neověřeno | ne | ne | ano |
| QElectroTech | GPL(-2.0) | prvky CC BY 3.0 (+ zákaz ML tréninku) | ne | ne | ano |
| FreeCAD | LGPL-2.1+ | addon Cables: kód LGPLv3, modely CC BY 4.0 | ne | ne | ano |
| ezdxf | **MIT** | – | ano | už je | ano |
| pandapower | BSD-3 | std_types neověřeno | ano s atribucí (ale zbytečně) | jen dev/test | ano |
| pvlib | BSD-3 | – | ano s atribucí (jen parser) | ne (těžké deps) | ano |

---

## 8. Tabulka „Co převzít“

Náročnost: S = hodiny až den, M = několik dní, L = týdny. Odkazy v „zdroj“ viz sekce výše.

| # | Návrh | Řeší mezeru / issue EnvoCAD | Zdroj | Způsob | Licence zdroje | Odhad |
|---|---|---|---|---|---|---|
| 1 | Verze formátu pro symboly, spec generátoru, archiv (`format_version` + `generator`; novější → odmítnout) | symbol bez verze, spec bez verze, #75, #85 | KiCad sexpr-schematic, Horizon `version.html` | myšlenka | GPL / GPL | S |
| 2 | Per-kód závažnost nálezů + seznam „waived“ nálezů s důvodem v projektu | ERC (F7) bez potlačení, #80 | KiCad `rule_severities`, `m_ErcExclusions` | myšlenka | GPL-3 | M |
| 3 | Návratový kód CLI `checks` podle závažnosti (CI/agenti) | CLI/agenti, bod 11 inventury | `kicad-cli sch erc --exit-code-violations` | myšlenka | GPL-3 | S |
| 4 | Výkaz jako uložený preset (pole, pořadí, filtr, seskupení, řazení) | #68, #87, #102, #67, #76 | KiCad `sch export bom`, QET nomenklatura v0.8 | myšlenka | GPL / GPL | M |
| 5 | Tabulkový editor atributů prvků (list/projekt, filtr, inkrement, rezervované klíče) | #77, #74, #103 | KiCad Symbol Fields Table | myšlenka | GPL-3 | M |
| 6 | Jedna konstanta chráněných atributů (prefix/seznam) | #77 vs #98 | KiCad pole `ki_*` | myšlenka | GPL-3 | S |
| 7 | SQLite = přestavitelný index nad JSON/CSV; verze schématu; úklid zmizelých zdrojů; UUID artiklu | knihovna SQLite bez verze/mazání, #101, #75 | Horizon pool (`pool-why`, `pool-mgr`) | myšlenka | GPL-3 | M |
| 8 | Deklarativní mapování sloupec → atribut (místo `PARAM_TO_ATTR` v kódu) | #84, #86, #83 | KiCad `.kicad_dbl` | myšlenka | GPL-3 | M |
| 9 | Dědění artiklu od základního artiklu (rodina jističů) | #83 (chybějící rozměry/Pv), duplicity CSV | Horizon Part inheritance | myšlenka | GPL-3 | M |
| 10 | Editor symbolů fáze 1: read-only builtin, uživatelská kolekce, vložená kopie v projektu, editace portů/atributů | #85, #75, #101 | QET editor prvků a kolekce (Common/Company/Custom/Embedded), Horizon wizard | myšlenka | GPL / GPL | L |
| 11 | Svorka jako entita s úrovní (`level`) a UUID; kontrola neprodrátovaných svorek | #89, #88 | QET terminal strip (0.100), fórum | myšlenka | GPL-2 | M |
| 12 | Verze plugin API + `requires_api`; metadata kompatibility; experimentální nové body (`add_check`, `add_export`, `add_board_builder`) | plugin API bez verze a bodů | KiCad PCM `kicad_version(_max)`, IPC API pravidla deprecations, FreeCAD Addon Academy | myšlenka | GPL / LGPL | S–M |
| 13 | Lokalizace: gettext (stdlib) pro hlášky z `model/`/`generator/`/`cmd/`, `tr()` jen v `ui/`; jména v knihovně jako slovník jazyků; prahová úplnost | #91 | KiCad translation (gettext + Weblate), QET translation (Linguist, 90 %) | myšlenka | GPL / GPL | M |
| 14 | Výstup DXF rozložení: bloky s ATTRIB, vrstvy, paperspace layout, dimension | #88 | ezdxf dokumentace (layouts, blocks, dimensions) | kód (závislost, už je) | MIT | M |
| 15 | Legenda a tabulky v DXF přes `TablePainter` | #76, #88 | ezdxf `TablePainter` | kód (závislost) | MIT | S |
| 16 | Headless PDF přes SVGBackend/vlastní renderer; **nepoužít PyMuPDF (AGPL)** | PDF jen přes Qt scény, bod 9 inventury | ezdxf drawing add-on | kód (závislost) + vlastní | MIT (PyMuPDF AGPL – ne) | L |
| 17 | Parser PVsyst .PAN/.OND, mapa klíč → sloupec + jednotky, testy na vlastních vzorcích | #86 | pvlib `read_panond` | myšlenka (případně přepsání s atribucí) | BSD-3 | S–M |
| 18 | Referenční zkoušky zkratových proudů v testech (dev-závislost, volitelně) | #79, #80, #82 | pandapower `shortcircuit` (IEC 60909) | závislost (jen dev/test) / myšlenka | BSD-3 | M |
| 19 | Atribuce QET prvků: `LICENSE-DATA`, CC BY 3.0, oznámení změn, posouzení „zákazu ML“ | #81 | QET `ELEMENTS.LICENSE` | právní doplnění | CC BY 3.0 | S |
| 20 | Rozsah/volba „start od čísla listu“ při přečíslování | #71, `renumber.py` | KiCad Annotation tool | myšlenka | GPL-3 | S |
| 21 | Přenositelné PDF odkazy a vlastnosti: sledovat chování `kicad-cli … export pdf` (hierarchické odkazy) jako akceptační vzor | #73, #104 | KiCad CLI docs | myšlenka | GPL-3 | S |
| 22 | pandapower `std_types` jako vzor *struktury* tabulky kabelů (`q_mm2`, `alpha`, `max_i_ka`) – hodnoty NEpřebírat | #79, #82 | pandapower std_types | myšlenka | BSD-3 | S |

---

## 9. Neověřené body a mezery rešerše

1. **GitLab issue tracker KiCadu a GitHub trackery Horizon/QET/FreeCAD** jsem systematicky neprošel (WebSearch je nevrací, ruční fetch nebyl proveden). Odkazy na issues jsou jen ty, které se objevily ve výsledcích (Launchpad bug 1526213, MR !1282) a nebyly otevřeny.
2. KiCad: obsah „Find tool“/„Search panel“; plné znění ERC sekce 9.0; jak se přesně vyrábí PDF s odkazy; stabilita IPC API ve verzi 9; zda `kicad-cli … --format json` ERC obsahuje stabilní klíče výjimek.
3. Horizon EDA: licence poolu; popis „Hierarchy“; zda existuje migrace schématu `pool.db`; obsah `cli-usage` a `parameter-programs`.
4. QElectroTech: detailní formát `.qet`/`.elmt`; stav editoru svorkovnice po 0.100 (z fóra jen útržky); licence a chování `qet-tb-generator` (stránka PyPI se nenačetla); přesný text zákazu ML v `ELEMENTS.LICENSE` (parafrázováno z fetch souhrnu, ne doslovně).
5. FreeCAD: neexistence „Electrical“ workbenche jsem neprokázal – jen jsem ho při hledání nenašel.
6. ezdxf: `ezdxf.addons.importer` a `audit` nečteny; nevím, zda SVG → PDF bez další závislosti existuje (pypdf SVG neumí – domněnka).
7. pandapower: licenční text, zdroj hodnot `std_types`, rozsah modulu `shortcircuit` (podstránky nečteny).
8. pvlib: seznam klíčů a jednotek `.PAN/.OND`, testované verze PVsyst – nepotvrzeno; potřebná kontrola nad skutečným souborem.
9. Právní výklad (CC BY 3.0 + zákaz ML ve sbírce QET vs. MIT, použití CC-BY-SA knihoven KiCadu) není právní rada – vlastník by měl ověřit.
10. Čísla z cache vyhledávače (počet řetězců/jazyků KiCad Weblate) mohou být zastaralá.
11. Žádný z projektů jsem nespouštěl; závěry o funkcích vycházejí z dokumentace a ChangeLogu.
