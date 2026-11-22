# 01b – Rešerše: issues a pull requesty EnvoCAD

Stav k 2026-11-22, repozitář `papro-thc/EnvoCAD`, větev `main` (HEAD `76c0818`). Zdroj: `gh issue list/view`, `gh pr view/diff/checks`
(jen čtení). Kód ověřen v tomto worktree (= `origin/main`). Soubor `docs/research/01a_inventura.md` v době psaní **neexistoval**,
body 4 a 5 jsou proto ověřené přímo grepem/čtením kódu a `git log` (viz „Co se nepodařilo ověřit“ na konci).

Poznámky k číslování: v repozitáři je 30 issues (65–77, 79–91, 101–104). Čísla 78, 92–95, 99, 100 a nižší jsou **pull requesty**, ne issues
(např. #78 = „Agent: předplatné Claude…“, #99 = PR k #72). Issue #65 a #72 jsou zavřené, zbylých 28 je otevřených. Všechny issues mají štítek
`agent-task`; „noční selhání“ = počet komentářů bota „Noční agent issue nedokončil“.

## 1. Přehledová tabulka issues

Štítky: `A-T` = agent-task, `A-R` = agent-ready, `A-IP` = agent-in-progress. Typ: B bug, F funkce, D data knihovny, UX, Dok, T testy/infrastruktura.

| # | Název | Stav | Štítky | Typ | Oblast | Pozn. |
|---|---|---|---|---|---|---|
| 65 | Testy: úklid po selhání a DeprecationWarning (3.12/3.14) | zavřeno 21.11. (PR #64) | A-T | T/B | infrastruktura (testy) | viz bod 5 |
| 66 | Testy: pokrýt nejméně pokryté moduly jádra | otevřeno | A-T, A-R, A-IP | T | infrastruktura (testy) | 8× noční selhání |
| 67 | Testy: charakterizace výkazů `export/reports.py` | otevřeno | A-T, A-R, A-IP | T | export / BOM | 3× selhání |
| 68 | Výkaz artiklů po výrobcích (xlsx) | otevřeno | A-T, A-R | F | BOM / export | PR #97 |
| 69 | Varování na uživatelské kopie makra „DC string po trase“ | otevřeno | A-T, A-R, A-IP | F/UX | generátor / makra | 3× selhání |
| 70 | Nástroj: přehled artiklů bez `t_min_c`/`t_max_c` | otevřeno | A-T, A-R, A-IP | D (nástroj) | knihovna | 3× selhání |
| 71 | Příkaz „Duplikovat list“ | otevřeno | A-T, A-R, A-IP | F | GUI / JPS / rozvaděč | otázky zodpovězeny, `agent-question` už sundán |
| 72 | PDF: záložky v Celé dokumentaci | zavřeno 22.11. (PR #99) | A-T, A-R | F | export (PDF) | hotovo, dozvuky v #104 |
| 73 | PDF: klikací křížové odkazy | otevřeno | A-T, A-R, A-IP | F | export (PDF) / JPS | navazuje na #72 |
| 74 | Hledat a nahradit text v projektu | otevřeno | A-T, A-R | F/UX | GUI / cmd | PR #98 |
| 75 | Archiv projektu (zabalit s uživ. značkami a artikly) | otevřeno | A-T, A-R | F | knihovna / soubor projektu | PR #96 |
| 76 | Volitelná strana: přehled použitých značek (legenda) | otevřeno | A-T, A-R, A-IP | F | export (PDF) / knihovna | 3× selhání |
| 77 | Hromadná úprava vlastností vybraných prvků | otevřeno | A-T, A-R, A-IP | F/UX | GUI / cmd | rozhodnuto „B“ (nový atribut `note`) |
| 79 | Soupis údajů z norem potřebných k ověření výpočtů | otevřeno | A-T, A-R, A-IP | Dok | výpočty (normy) | |
| 80 | Výpočty označit jako orientační, oteplení pryč z protokolu | otevřeno | A-T, A-R, A-IP | B/Dok (bezpečnost dokumentace) | export docx/xlsx/PDF, výpočty | |
| 81 | Atribuce značek QElectroTech (CC BY 3.0, LICENSE) | otevřeno | A-T, A-R, A-IP | Dok (licence) | knihovna / právní | |
| 82 | Ověřit tabulky Iz a konstanty oteplení proti normě | otevřeno | A-T | D/B | výpočty (`calc.py`, `thermal.py`) | čeká na člověka a #79 |
| 83 | Report úplnosti dat artiklů (rozměry, moduly, Pv) | otevřeno | A-T, A-R, A-IP | D (nástroj) | knihovna / rozvaděč | |
| 84 | Import artiklů z BMEcat – parser | otevřeno | A-T, A-R, A-IP | D | knihovna / import | |
| 85 | Editor symbolů v GUI – fáze 1 | otevřeno | A-T, A-R, A-IP | F | GUI / knihovna symbolů | |
| 86 | Import modulů a střídačů z PVsyst .PAN/.OND | otevřeno | A-T, A-R, A-IP | D | knihovna / import | |
| 87 | Ceny ve výkazech | otevřeno | A-T | F | BOM / export | viz bod 4 (práce existuje mimo main) |
| 88 | DXF export rozložení rozvaděče a plánu svorkovnice | otevřeno | A-T, A-R, A-IP | F | export DXF / rozvaděč / svorkovnice | |
| 89 | Vícepatrové svorky | otevřeno | A-T | F | svorkovnice | čeká na návrh a rozhodnutí |
| 90 | Podepsaný build pro Windows a první vydání | otevřeno | A-T | Dok/infra | infrastruktura (release) | čeká na rozhodnutí o podpisu |
| 91 | Anglické rozhraní – fáze 1 | otevřeno | A-T, A-R, A-IP | F/UX | GUI / i18n | |
| 101 | Archiv: nepřepisovat vestavěné artikly, přepis přežije přenačtení | otevřeno | A-T | B | knihovna / archiv | z review PR #96 |
| 102 | Výkaz po výrobcích: výrobce bez ohledu na velikost písmen | otevřeno | A-T | B | BOM | z review PR #97 |
| 103 | Najít a nahradit: skloňování, test dialogu, changelog | otevřeno | A-T | UX/T | GUI | z review PR #98 |
| 104 | PDF záložky: panel záložek, pojistka nesouladu stran | otevřeno | A-T, A-R | B | export (PDF) | z review PR #99 |

Pozorování k procesu: 15 otevřených issues má zároveň `agent-ready` i `agent-in-progress`, ale jen tři mají otevřený PR (#68, #74, #75). Většina
`agent-in-progress` issues má za sebou 2–8 komentářů „Noční agent issue nedokončil“ (#66: 8×) a štítek `agent-failed` zřejmě nebyl sundán/nastaven
(v seznamu štítků se `agent-failed` nevyskytuje – neověřeno proč). Issues #101–#104 jsou přímo odvozené z review PR (#96, #97, #98, #99).

## 2. Otevřené pull requesty

| PR | Název / větev | Zavírá | Co řeší | Změněné soubory | CI | Stav |
|---|---|---|---|---|---|---|
| #96 | „Agent: issue #75“ (`agent/issue-75-archiv-projektu`) | #75 | Archiv projektu `.ecpz` (zip s `.ecp` + nevestavěné značky a artikly), import chybějících položek do uživatelské knihovny | `.gitignore`, `changelog.d/2026-11-22-archiv-projektu.md`, `docs/ARCHITECTURE.md`, `envocad/library/archive.py`, `envocad/ui/main_window.py`, `tests/test_project_archive.py`, `tests/test_project_archive_gui.py`, `tools/check_licensed_data.py` | všech 7 jobů zelených (Linux/Windows × 3.12/3.14, build, ruff+licence) | MERGEABLE; popis PR prázdný („Agent nezapsal popis PR“). Vlastník zadal agentovi (`@claude`) opravu 2 nálezů review: (1) validace artiklů v `read_archive` (špatný `params`/`manufacturer=null` rozbije knihovnu) + import v jedné transakci, (2) ověřit `project.ecp` před importem. Agent opravy právě dělá (checklist, nic nezapsáno). Zbylé nálezy → #101 |
| #97 | „Agent: issue #68“ (`agent/issue-68-vykaz-po-vyrobcich`) | #68 | `bom_by_manufacturer()` v `reports.py` + list v xlsx | `changelog.d/2026-11-22-vykaz-po-vyrobcich.md`, `docs/MANUAL.md`, `envocad/export/reports.py`, `tests/test_bom_by_manufacturer.py` | **2 jobů padá**: Testy windows 3.12 a 3.14 (`PermissionError WinError 32` při mazání dočasného adresáře – soubor `lib.db` zůstal otevřený, tj. nezavřené SQLite spojení v testu); Linux a lint zelené | MERGEABLE; popis prázdný. Vlastník zadal opravy: slučování artiklů bez `typ` (parametry do klíče i názvu), tautologický test součtů. Rozlišení velikosti písmen → #102. Pozor: Windows chyba nesouvisí s popsanými nálezy – neověřeno, zda se opraví samo |
| #98 | „Agent: issue #74“ (`agent/issue-74-hledat-nahradit`) | #74 | Hledat a nahradit text (`cmd/edits.py`, `ReplaceDialog`, undo) | `changelog.d/2026-11-22-hledat-nahradit.md`, `envocad/cmd/builtin.py`, `envocad/cmd/edits.py`, `envocad/ui/commands.py`, `envocad/ui/main_window.py`, `envocad/ui/replace_dialog.py`, `tests/test_replace_text.py`, `tests/test_replace_text_gui.py` | všech 7 zelených | MERGEABLE; popis prázdný. Vlastník zadal opravy: „Aktuální list“ bez aktivního listu nahradí celý projekt (bug); chráněné atributy (`ports_in/out`, `sheet`, `acts_on`, `busbar.PARAM_KEYS`, `terminal`, `terminals`, `contacts`). Drobnosti → #103 |

Společný nedostatek: všechny tři PR mají místo popisu jen „Closes #N“ – schází „Mimo rozsah“ a výpis pokrytí, které CLAUDE.md požaduje.

**Důležitý nález mimo seznam otevřených PR:** PR #62 (`Velikost papíru z pravého tlačítka, rozvodnice ETI, oprava výběru svodičů`) a PR #63 (`Ceník artiklů a výkaz materiálu s cenami`)
mají stav MERGED, ale byly sloučeny **do pomocné větve `feature/papir-eti-svodice` (resp. `feature/hybrid-baterie-eps`), nikoli do `main`**. Commity `0c5e968`,
`08afd11` a `4a67825` jsou jen v `origin/feature/papir-eti-svodice` (`git rev-list origin/main..origin/feature/papir-eti-svodice` = 3). Na `main` proto chybí
`envocad/library/prices.py`, `reports.priced_bom`, `envocad/library/builtin/components/enclosures_eti.csv` a menu velikosti papíru. Nikdo to zatím nevyřešil (žádné issue, žádný otevřený PR).

## 3. Duplicity a související issues

- **PDF dokumentace (#72 → #73 → #104, #76):** #72 záložky (hotovo, PR #99); #104 jsou opravy po review téhož; #73 klikací odkazy (zadání říká „neber, dokud není #72“ – už může);
  #76 legenda mění `plan()` a obsah v `doc_pdf.py`. Všechny sahají do `export/doc_pdf.py` a `pdf_annots.py`/`pdf_outline.py`, hrozí konflikty a opakované průchody pypdf
  (explicitně „mimo rozsah“ v #104).
- **Výkazy a ceny (#67, #68, #87, #102):** #67 charakterizační testy `reports.py`; #68 výkaz po výrobcích (PR #97); #102 oprava case-insensitive; #87 ceny – závisí na #68. Navíc **#87 se částečně
  překrývá s hotovou, ale nesloučenou prací PR #63** (viz bod 4).
- **Archiv (#75 ↔ #101):** #101 = nálezy z review PR #96; blokováno sloučením #96.
- **Hledat/nahradit (#74 ↔ #103) a hromadná úprava (#77):** #103 drobnosti z PR #98; #77 používá stejnou infrastrukturu (`cmd/edits.py`, undo) a stejné pojetí „chráněných“ klíčů (`ref`, čísla svorek) – #77 má
  rozhodnuté „`ref` ne“, #98 chrání `terminal(s)`, `contacts`; pravidla chráněných atributů je dobré sjednotit.
- **Duplikace listu (#71) ↔ přečíslování / hromadná úprava (#74, #77):** všechny řeší dopad na `ref` a odkazy mezi listy; #71 navíc na logiku značení rozvaděčů v generátoru („volitelná v generátoru“ – vlastník chce nové nastavení).
- **Normy a výpočty (#79 → #82, #80):** #79 soupis, #82 ověření (čeká na #79 + data od člověka), #80 označení „orientační“ (nezávislé, dělá se hned). Společně tvoří „ověřitelnost výpočtů“.
- **Úplnost dat artiklů (#70, #83, #84, #86):** #70 a #83 jsou dva podobné reportovací skripty (#83 výslovně „může sdílet kód s #70“); #84 (BMEcat) a #86 (PVsyst) jsou dva importéry artiklů, oba po vzoru `eplan_import.py`.
- **Licence a data (#81, #75):** #81 atribuce QET; #75 řeší balení EPLAN artiklů do archivu (lokální soubor, `.gitignore`) – oba jsou o licenčních hranicích.
- **Rozvaděč a svorkovnice (#88, #89, #83):** #88 DXF rozložení/plánu svorkovnice, #89 vícepatrové svorky (ovlivní plán svorkovnice i vícepól → i #88), #83 rozměry artiklů pro rozložení.
- **Infrastruktura (#65, #66, #67, #90, #91):** testy/CI, vydání, překlady.
- Skutečné duplicity (dvě issues o totéž): nenalezeny; nejblíž je dvojice #70/#83.

## 4. Otevřené issues, které jsou podle kódu už vyřešené

Ověřeno na `main` (HEAD `76c0818`) grepem a `git log`. **Žádná otevřená issue není na `main` zcela vyřešená.**

| # | Posouzení | Důkaz |
|---|---|---|
| 87 Ceny ve výkazech | **Částečně – hotové, ale mimo `main`** | Commit `08afd11` „Ceník artiklů (`~/.envocad/ceny.csv`) a výkaz materiálu s cenami“ (PR #63, sloučen do `feature/papir-eti-svodice`, ne do `main`): `envocad/library/prices.py`, `export/reports.priced_bom`, položka v menu, `tests/test_prices.py`, ROADMAP „[x] Ceny v artiklech + výkaz s cenami“. Na `main` neexistuje (`ls envocad/library/prices.py` → chybí; `grep priced_bom` bez nálezu). Zadání #87 (list „Rozpočet“, formát Kč, upozornění „N položek bez ceny“, otázky DPH/přirážka) se s hotovou implementací jen částečně kryje (PR #63 počítá bez DPH, xlsx výkaz „s cenami“; zda je tam hláška o chybějících cenách a formát Kč – neověřeno). Nejdřív rozhodnout o sloučení větve do `main` |
| 72 | (zavřená, hotová) | `envocad/export/pdf_outline.py`, `doc_pdf.py:526-527`, `tests/test_pdf_outline.py`, `changelog.d/2026-11-22-pdf-zalozky.md`, PR #99 |
| 66, 67, 69, 70, 71, 73, 76, 77, 79, 80, 81, 83, 84, 85, 86, 88, 89, 90, 91 | **Nevyřešeno** | grep na `bom_by_manufacturer`, `duplicate_sheet`, `replace_text`, `ecpz`, `legend`, `pvsyst`, `/Link`, `report_missing_temps`, `report_library_gaps`, `lupdate/gettext`, `symbol editor` bez výskytu v `envocad/`, `tests/`, `tools/` na `main`; `docs/NORMY_POTREBA.md` neexistuje; `.github/workflows/release.yml` neexistuje (jen `ci.yml`, `agent-*.yml`); `exporty DXF` jen `export_sheet_dxf/single_line/multipole` |
| 68, 74, 75 | Rozpracováno v PR #97 / #98 / #96 | viz bod 2; na `main` nesloučeno |
| 80 | Nevyřešeno, potvrzeno | `envocad/export/docx_export.py:229` stále vypisuje řádek „Oteplení (IEC TR 60890, výpočet)“ přes `_thermal_text`; řetězec „neověřeno proti normě“ není v `envocad/` ani `tests/` |
| 81 | Nevyřešeno, potvrzeno | `envocad/library/builtin/qet/ATTRIBUTION.md` obsahuje starý odkaz `…/wiki/doc/elements_license` (v issue uváděný jako 404; **neověřeno ručně**), chybí oznámení o úpravách; `LICENSE` nezmiňuje QET (jen README ř. 158 a CLAUDE.md bez zmínky licence) |
| 69 | Nevyřešeno | v `envocad/generator/` ani `library/macros.py` není kontrola uživatelských kopií makra; vestavěné `dc_string_po_trase.json` už odpínač nemá (PR #16), `dc_string_v_rozvadeci.json` ho má legitimně |
| 77 | Nevyřešeno; člověk rozhodl „B“ | `Element` nemá `note`; odpověď „B“ = nový atribut `note` u každého prvku + pole v panelu vlastností |
| 91 | Základ existuje | `envocad/app.py: install_qt_translations` načítá jen `qtbase_cs`/`qt_cs` (české standardní texty Qt), není volba jazyka ani vlastní překlady; `settings.py` nemá jazyk |

## 5. Zavřené issues, které se vrátily nebo nejsou dořešené

- **#65 (Testy: úklid po selhání a DeprecationWarning) – podezření „zavřeno, ale nedořešeno“.** Zavřeno přes PR #64 (CI a noční agenti). Podmínka hotovo vyžaduje, aby
  `tests/test_generator_chain.py::test_old_generate_setattr_goes_to_context` vrátil `context._lib` i při selhání (`try/finally` / fixture). V kódu na `main` (ř. 195–204) test dál
  používá `monkeypatch.setattr` + ruční `monkeypatch.undo()` + `assert context._lib is real` **bez `try/finally`**; `git log` souboru ukazuje poslední změnu už u F2 (`ce42302`),
  PR #64 test tedy nezměnil. CI na 3.12 i 3.14 je u PR #96/#98 zelené (varování se tam asi vydává spolehlivě), takže praktický dopad se nemusí projevit; **zda je ostatní část
  (DeprecationWarning u `tests/test_updater.py`) opravena, neověřeno**. Doporučení: dotázat se vlastníka, jestli zavření bylo záměrné (issue-body mluví o lokálním selhání na 3.14).
- **#72 (PDF záložky)** – splněno (`pdf_outline.py`), ale review po sloučení odhalilo dva nedostatky, vedené jako nová #104 (chybí `/PageMode /UseOutlines`, hrozí `IndexError` při nesouladu stran;
  `grep UseOutlines envocad` = bez nálezu). Ne regrese, ale nedořešení.
- Jiné zavřené issues v repozitáři nejsou (30 issues celkem, 2 zavřené).
- Související problém procesu (ne issue): PR #62/#63 „MERGED“ mimo `main` (viz bod 2) – funkční obsah, který vlastník považuje za hotový, v hlavní větvi není.

## 6. Nejasně zadané issues

| # | Co chybí, aby šlo implementovat |
|---|---|
| 66 | Výčet modulů a cílové pokrytí je vágní („3–5 nejméně pokrytých“); 8 selhání nočního agenta napovídá, že je zadání příliš velké / běh trvá dlouho (CI testy trvají 22–38 min). Chybí omezení času a konkrétní seznam modulů |
| 69 | Neřekne, **jak** se pozná „kopie obsahuje odpínač“ (podle `symbol_id`, role, názvu?) a kde přesně v generátoru se hlášení zapisuje; 3 selhání |
| 76 | Chybí formát tabulky (kolik řádků na stranu, které značky – i vestavěné QET?), jak se kreslí značka pro různé orientace; 3 selhání |
| 79 | Agent nemá normy – výstup je jen soupis; chybí šablona řádku a kritérium úplnosti („projde aspoň…“). Stále `agent-in-progress` |
| 80 | „Výpočty Iz / jištění kabelu ve výkazech a technické zprávě“ – chybí seznam všech míst výpisu (xlsx, docx, PDF, F7, TZ) a rozhodnutí, zda se označení vkládá do textu hodnoty, nebo samostatné poznámky; hrozí konflikt s `builtin/doc_templates` (zadání říká „zeptej se“) |
| 82 | Čeká na dodání normových hodnot a rozhodnutí, **jak je ukládat** (výběr bodů v kódu vs. lokální soubor mimo git – otázka na člověka je otevřená) |
| 85 | Chybí návrh GUI (dialog/okno), jak se zobrazí kresba bez editace; „upozornění na projekty“ nespecifikováno; fáze 1 je pravděpodobně na víc než pár hodin |
| 87 | Dvě otevřené oborové otázky (ceny s/bez DPH, přirážka/sleva); navíc se krýve s nesloučenou prací #63 |
| 88 | Chybí, zda geometrie rozložení už existuje v `model/` (v `ui/layout_view.py` je podle zadání Qt kód); zadání sám navrhuje rozdělení. Chybí příklad očekávaného výkresu (měřítko, vrstvy, kóty) |
| 89 | Chybí tři rozhodnutí (číslování pater, kreslení, které artikly) a návrh datového modelu; zadání výslovně „nejdřív návrh v issue“ |
| 90 | Chybí volba způsobu podpisu (Azure Trusted Signing vs. OV/EV cert) a vlastník secrets; bez nich jen kostra |
| 91 | Volba mechanismu (Qt `tr()` vs. gettext) a pravidlo pro překlad hlášek z `model/`/`generator/` (bez Qt) – musí navrhnout agent; velký rozsah, dvou-fázový plán; 2. a další fáze bez issue |
| 84 | Chybí příklad BMEcat (zadání vyžaduje smyšlený), neřeší, které verze (1.2 vs. 2005) mají prioritu a jak mapovat jednotky |
| 86 | Chybí seznam klíčů `.PAN`/`.OND` → sloupce (agent si je má odvodit); jednotky `beta_voc` |
| 71 | Zodpovězeno komentářem vlastníka (1: c + okno na přepsání všech značení; 2: b; 3: přeznačit kopii a zachovat logiku, **volitelná logika značení rozvaděčů v generátoru – název a číslo**). Tento poslední požadavek je nový rozsah (nastavení v generátoru) bez akceptačních kritérií; v issue se zadání neupravilo – neodpovídá původnímu textu |
| 77 | Zodpovězeno („B“), ale zadání v těle issue stále mluví o „poznámce“ bez definice atributu; chybí rozhodnutí o zobrazení poznámky (panel, výkazy) |
| 70, 83 | Jasně zadané; jen překryv (společný kód) |
| 73, 74, 75, 101–104 | Jasné; #73 stále uvádí závislost na #72 (již sloučeno) |

## 7. Návrh priority otevřených issues

Priorita = můj návrh (vysoká / střední / nízká) podle dopadu na uživatele (ENVO) a rizika; rozhodnutí je na vlastníkovi.

| # | Priorita | Zdůvodnění |
|---|---|---|
| 80 | vysoká | Protokol kusového ověření dnes uvádí neověřené oteplení jako průkaz – právní/bezpečnostní riziko dokumentu pro zákazníka |
| 82 | vysoká (blokováno) | Opravuje nespolehlivé normové konstanty, ale nelze bez dat od člověka a #79 |
| 79 | vysoká | Nutná podmínka pro #82; jediná cesta, jak dostat výpočty z „orientační“ do „ověřeno“ |
| 101 | vysoká | Po sloučení #96 přepisuje vestavěné artikly a tiše ztrácí změny – datová integrita knihovny |
| 87 / PR #63 (sloučení mimo main) | vysoká | Funkční práce (ceník, rozpočet, ETI rozvodnice, velikost papíru) je hotová, ale není v `main`; nejdřív rozhodnout o jejím začlenění |
| 68 | vysoká | PR hotový, jen opravit Windows CI a nálezy; výkaz po výrobcích přímo podporuje objednávání |
| 75 | vysoká | PR otevřený a zelený; řeší přenos projektu mezi PC (knihovna chybí) – reálná bolest uživatelů |
| 74 | střední | Pohodlnější úpravy; PR hotový, opravit bug „Aktuální list“ |
| 102 | střední | Drobná oprava korektnosti výkazu po výrobcích |
| 104 | střední | Panel záložek se neotevře a hrozí pád exportu při nesouladu stran |
| 71 | střední | Často používaná funkce (duplikace listu), rozhodnutí hotová, ale rozsah vzrostl (volitelné značení rozvaděčů) |
| 77 | střední | Zrychlí úpravy řady prvků; rozhodnuto B |
| 88 | střední | Výstup pro dodavatele skříní; velká práce, může vyžadovat rozdělení |
| 73 | střední | Přínos PDF navigace (EPLAN standard); závisí na hotových záložkách |
| 83 | střední | Chybějící rozměry/Pv zhoršují rozložení a oteplení (222 artiklů bez rozměrů, 138 jističů bez Pv) |
| 70 | nízká | Jen přehled; sloučit s #83 |
| 81 | střední | Licenční soulad (CC BY 3.0) – malá práce, nenápadné riziko při veřejném repozitáři |
| 69 | nízká | Ochrana před zastaralou uživatelskou kopií makra – okrajový případ |
| 66, 67 | nízká | Charakterizační testy – užitečné, ale nic nepřináší uživateli; #66 opakovaně selhává (příliš široké) |
| 76 | nízká | Volitelná legenda, výchozí vypnutá |
| 84, 86 | střední / nízká | Importy (BMEcat, PVsyst) pomáhají plnit knihovnu, ale nejsou kritické; PVsyst zajímavější pro projektanty FVE |
| 85 | nízká | Editor symbolů, velký rozsah; značky lze zatím upravit JSON |
| 89 | nízká | Čeká na návrh a oborová rozhodnutí |
| 90 | střední | První vydání je podmíněno podpisem; bez rozhodnutí o certifikátu jen kostra |
| 91 | nízká | Anglické UI není pro nynější české uživatele přínosem; jen návrh infrastruktury |
| 103 | nízká | Kosmetika po review #98 |
| 65 (zavřená) | nízká | Doladit test (`try/finally`), pokud vlastník nepovažuje za vyřízené |

## 8. Souhrn pro další agenty

Hlavní témata a mezery (pro rešerši inspirace v jiných nástrojích, normách a požadavcích distributorů):

1. **Důvěryhodnost výpočtů a dokumentů** (#79, #80, #82): Iz, oteplení rozvaděče (IEC TR 60890), jištění kabelu jsou „z paměti / orientační“; protokol kusového
   ověření dnes obsahuje neověřené oteplení. Hledat: co přesně vyžaduje ČSN EN 61439-1 (čl. 10.10 ověření návrhu vs. čl. 11 kusová zkouška), ČSN 33 2000-5-52 / IEC 60364-5-52
   tab. B.52.x, IEC 60890 – a jak nástroje (Rittal Therm, ETI/Hager/ABB konfigurátory, EPLAN Pro Panel, SEE Electrical) tyto výpočty označují a dokládají.
2. **Knihovna artiklů a import dat výrobců** (#70, #83, #84, #86, #75, #101): chybí rozměry (222 artiklů), Pv u jističů (138), teploty; potřeba importu z BMEcat/ETIM, PVsyst
   `.PAN/.OND`, případně dalších formátů (EPLAN Data Portal, ECLASS, ETIM). Zjistit, jaké katalogy poskytují distributoři a výrobci v ČR/SK (např. OEZ, ABB, Schneider,
   Eaton, ETI, Hager, Phoenix Contact, Weidmüller, Elektro-Bečov/Eleman, Fronius, SolarEdge, Huawei) a pod jakou licencí; jak řeší ceny (ceníky distributorů, API) – #87.
3. **Výkazy / BOM a objednávání** (#67, #68, #87, #102): výkaz po výrobcích, ceny, rozpočet; inspirace: EPLAN Pro Panel/Report Generator, KiCad BOM, požadavky velkoobchodů
   (formáty objednávkových košíků, CSV pro e-shopy, ETIM třídy).
4. **PDF/DXF výstupy a navigace** (#72, #73, #76, #88, #104): záložky, klikací odkazy, legenda značek, DXF rozložení pro výrobu skříní – srovnat s EPLAN (PDF export s odkazy a zálož­kami),
   AutoCAD Electrical, QElectroTech, SEE Electrical; požadavky dodavatelů skříní na DXF (vrstvy, jednotky, vrtací plány – mimo rozsah #88).
5. **Editační produktivita** (#71, #74, #77, #85): duplikace listu, najít/nahradit, hromadná úprava, editor symbolů – podívat se na řešení v EPLAN (tabulková úprava, označení),
   KiCad (plugin, annotation), QElectroTech (hromadná editace); návazně na pravidla chráněných atributů (`ref`, čísla svorek, kontakty).
6. **Svorkovnice a rozvaděč** (#89, #88, #83): vícepatrové svorky (číslování pater `X1:1.1` vs. průběžně; kreslení v plánu), můstky, koncové desky; hledat konvence EPLAN/Phoenix/Weidmüller/Wago a normy (ČSN EN 60947-7-x).
7. **Licenční soulad open-source** (#81, #75): atribuce QElectroTech (CC BY 3.0, zákaz použití pro trénink ML, rozpor s MIT), nepatřičná data výrobců v repu; kontrola `tools/check_licensed_data.py`.
8. **Vydání a lokalizace** (#90, #91): podepsané Windows buildy (Azure Trusted Signing vs. EV certifikát), PyInstaller buildy, Qt Linguist `.ts/.qm` vs. gettext, překlad hlášek z modulů bez Qt – srovnat s jinými PySide6 aplikacemi (QElectroTech, FreeCAD, KiCad).
9. **Proces a spolehlivost agentů** (#65, #66, PR #96–#98): nízká úspěšnost nočního běhu (8× u #66; 2–3× u většiny), Windows testy padají na nezavřeném SQLite (`lib.db`, WinError 32 na PR #97),
   prázdné popisy PR, PR sloučené mimo `main` (#62, #63). Doporučit kontrolu cílové větve a povinný popis PR.

Kritická zjištění, která by měla vidět další agenti: (a) PR #62/#63 nejsou v `main` – funkce „ceník/rozpočet“ a „ETI rozvodnice“ existují jen ve větvi `feature/papir-eti-svodice`;
(b) otevřená rizika správnosti: #80 (protokol), #101 (přepis vestavěných artiklů), nález PR #98 (chybná volba „aktuální list“) a PR #96 (vadný archiv rozbije knihovnu); (c) žádná otevřená issue
není na `main` zcela vyřešená – ROADMAP ř. 9 a 10 odpovídají (#88, #89).

## Co se nepodařilo ověřit

- `docs/research/01a_inventura.md` v době psaní neexistoval; body 4 a 5 jsou ověřeny jen grepem/čtením a `git log`, bez spuštění testů a aplikace.
- Zda je odkaz v `ATTRIBUTION.md` (#81) skutečně 404 – nezkoušeno (jen čtení, bez sítě mimo `gh`).
- Zda jsou na `main` pokryty ostatní části #65 (`DeprecationWarning` v `tests/test_updater.py`) – nespouštěl jsem testy.
- Zda by sloučení `feature/papir-eti-svodice` do `main` bylo bez konfliktů a jestli splní všechna kritéria #87 (hláška o chybějících cenách, formát Kč).
- Přesná příčina Windows selhání PR #97 (jen z logu: `PermissionError WinError 32` na `lib.db` v dočasném adresáři).
- Zda se po opravách agentem (PR #96/#97/#98 mají v komentářích rozpracované checklisty) stav PR změnil; data k okamžiku čtení.
- Proč štítek `agent-failed` není v seznamu štítků u issues s opakovanými selháními.
- Texty komentářů #71 (jen zkrácený výpis) – celý komentář a odpověď vlastníka přečteny z JSON, nikoli však všechny případné pozdější úpravy.
