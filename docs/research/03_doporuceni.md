# 03 – Doporučení: backlog, rychlá vítězství a návrhy issues

Stav k 22. 11. 2026, `main` @ `76c0818`, verze `0.11.0`. Agent fáze 3 (syntéza). Vstupy: `01a_inventura.md`,
`01b_issues.md`, `02_A_opensource.md`, `02_B_vyrobci.md`, `02_C_normy.md`, `02_D_distributori.md`, `CLAUDE.md`,
`docs/ROADMAP.md`. Sporná tvrzení jsem ověřil v kódu, `git` a `gh` (jen čtení); testy **nespuštěny** (v prostředí
chybí `pytest`, stejně jako u 1A). Nic se v kódu ani na GitHubu neměnilo.

Odkazy na zdroje: `01a §5.6` = kapitola 5.6 inventury, `02B P5` = návrh P5 v tabulce kap. 9 souboru 02B,
`02C N3` = návrh N3 v kap. 13 souboru 02C, `02D K12` / `G1` = pravidlo / kandidát v kap. 7–8 souboru 02D,
`02A #6` = řádek 6 tabulky kap. 8 souboru 02A.

---

## 0. Ověření sporných bodů a rozpory mezi vstupy

### (a) Ceny: PR #62/#63 mimo `main` vs. „ceny se načítají, ale žádný výkaz je nepoužívá“
**Obě tvrzení platí, každé o něčem jiném; 1A jen nevěděla o větvi.**
- `gh pr view 62`: base `feature/hybrid-baterie-eps`, head `feature/papir-eti-svodice`, MERGED 27. 10. 2026.
  `gh pr view 63`: base `feature/papir-eti-svodice`, head `feature/ceny-vykaz`, MERGED 27. 10. 2026. **Ani jeden nemá base `main`.**
- `git rev-list origin/main..origin/feature/papir-eti-svodice` = 3 commity (`0c5e968`, `08afd11`, `4a67825`);
  `origin/feature/hybrid-baterie-eps` je před `main` o 2 commity (merge #62 + `0c5e968`).
- `git diff --stat origin/main...origin/feature/papir-eti-svodice`: 12 souborů, +365/−4 – mj. `envocad/library/prices.py`
  (82 ř.), `export/reports.py` (+41, `priced_bom`), `library/builtin/components/enclosures_eti.csv`, `ui/main_window.py` (+93),
  `tests/test_prices.py`, `tests/test_formaty_stran.py`, `tests/test_gui_smoke.py`.
- Na `main`: `envocad/library/prices.py` **neexistuje**; `price` se čte jen v knihovně (`library/components.py:103,160–167`,
  `store.py:184,216,276,305–312`, `eplan_import.py:47,139,156`), v `export/` ani `ui/` se nepoužívá → 1A má pravdu pro `main`.
- Navíc: **žádný z 25 vestavěných CSV se sloupcem `price_czk` nemá vyplněnou cenu** (spočteno skriptem nad
  `library/builtin/components/*.csv`: 0 řádků s cenou). Proto větev PR #63 bere ceny z vlastního ceníku `~/.envocad/ceny.csv`
  (docstring `prices.py`: „vestavěné CSV ceny nemají a při aktualizaci by je přepsaly“).
- `git merge-tree --write-tree origin/main origin/feature/papir-eti-svodice` skončil bez konfliktů (exit 0). **Sémantické
  konflikty a testy neověřeny**; zda `enclosures_eti.csv` projde `tools/check_licensed_data.py`, neověřeno.

### (b) FORMAT_VERSION
- Kód: `envocad/model/project.py:70` → `FORMAT_VERSION = 18`.
- `docs/ARCHITECTURE.md:279` „aktuálně **17**“, `docs/LIBRARY_FORMAT.md:464` „(`FORMAT_VERSION` 16)“. **Potvrzen nesoulad z 01a §5.6.**
- `examples/ukazka_fve.ecp` má `"format_version": 1` (projde migrací, ale neukazuje současné funkce).

### (c) Zavřená issue #65 – „nedořešena“?
**Rozhoduji podle kódu: věcně vyřešena PR #64, doslovně jedna podmínka nesplněna; nespouštěno.**
- 1B má pravdu, že `tests/test_generator_chain.py:195–204` stále nemá `try/finally` a poslední změna souboru je `ce42302`.
- 1B ale přehlédla, že PR #64 (`gh pr view 64`, base `main`) změnil **`envocad/generate.py`**: `_DeprecatedModule` dostal
  `__delattr__`, který vrátí původní hodnotu přesunutého jména (`_ORIGINALS`). To je skutečná příčina úniku podvrženého
  `_lib` do dalších testů (pytest ≥ 9.2 uklízí `monkeypatch` přes `delattr`). Úklid tedy zajišťuje teardown fixture
  `monkeypatch` i při selhání testu – `try/finally` v testu je zbytečný. Stejný PR opravil `updater.read_manifest`
  (odmítá `/`, `\`, `:` v názvu ZIPu) → část „`test_manifest_validation[patch1]`“. Doloženo `changelog.d/2026-11-20-testy-pytest-9-2.md`.
- Co zůstává neověřené: zda na 3.14 opravdu chodí `DeprecationWarning` spolehlivě (testy nespuštěny). CI zelené u PR #96/#98 to naznačuje.
- Doporučení: issue nechat zavřenou (viz kap. 3).

### Další rozpory mezi vstupy (rozhodnuto podle kódu)
| # | Vstup A | Vstup B / kód | Rozhodnutí |
|---|---|---|---|
| R1 | 02D kap. 9: v modelu „chybí pole … distributor“; G1 „Tabulka údajů zdroje“ jako nový kandidát (M) | Kód: značka `fve.grid` má atribut `dso`; `export/tz_data.py:66 dso_data()` a výkaz `reports.py:582 dso_report` („Data pro DS“, je v `ALL_REPORTS`) už vypisují investora, místo, distributora, kWp, počet modulů a stringů, AC výkon a typy střídačů, fáze, akumulaci kWh/kW, hlavní jištění, připojovací kabel | **G1 je z velké části hotové.** Chybí jen EAN, katastr/parcela, ostrovní provoz, kategorie modulu A1/A2/B… a pravidlo Pi u hybridu → navrženy jako rozšíření (NEW-15, NEW-17), ne nový výkaz |
| R2 | 02B (zjištění 4) a 02C (zjištění 3): „zjistit, podle kterého vydání TR 60890 je kód psán (neověřeno)“ | `model/thermal.py:1`: „ČSN EN 61439-1 čl. 10.10.4.3.1 / **IEC TR 60890:2014**“; ř. 19 a 140–160: hodnoty k, c „ORIENTAČNÍ“ (reprodukce z příruček výrobců) | Kód **cílí na vydání 2014**, ale hodnoty nejsou z normy. Otázka pro projektanta se zužuje na: platí pro ENVO 2014, nebo 2022 (Q2) |
| R3 | 02B O7 (SIMARIS: wiring factor 30 %, RDF 80 %) | `thermal.temperature_rise(…, rdf=0.8, wiring_pct=15.0)` | Kód používá kabeláž 15 %, SIMARIS doporučuje 30 % – oborové rozhodnutí (Q9), agent neměnit |
| R4 | 02B P5: 7 vzorců Ae podle Rittal, „přiřazení neověřeno“ | `thermal.py:127 B_FACTORS` + `cooling_area` (ř. 406): mé ruční dosazení (nespouštěno) dává pro „volně stojící“, „nástěnná“ a „zapuštěná“ přesně Rittal řádky 1, 2 a 7; polohy v řadě (první/prostřední skříň) kód nemá | Test je proveditelný a levný (NEW-14), ale přiřazení musí potvrdit člověk s normou |
| R5 | 1B kap. 1: #67, #70, #81, #83 „agent-in-progress“ bez PR | `gh pr list` 22. 11.: nové PR **#105 (#83), #106 (#70), #107 (#67), #108 (#81)**; štítky `agent-in-progress` u nich už nejsou | 1B je zastaralá o několik hodin; backlog níže počítá s PR #105–#108 |
| R6 | 1B kap. 7: #84 (BMEcat) priorita střední, `agent-ready` + `agent-in-progress` | `docs/ROADMAP.md:149` „Odloženo – BMEcat/ETIM importér – až budou soubory od výrobců“ | Rozpor issue vs. ROADMAP – rozhodne člověk (kap. 3) |
| R7 | 02A #3: „příkaz `checks` v CLI s `--json` už existuje, doplnit návratový kód“ | `cmd/__main__.py`: návratový kód je `COMMAND_ERROR` (1) jen při chybě skriptu, nálezy F7 se jen sečtou do souhrnu (`counts`) | Potvrzeno, návrh NEW-2 |
| R8 | 02B O1 / 02C Q-3: „má se oteplení z protokolu vyřadit?“ | Tělo issue #80: „Rozhodnuto (člověk): oteplení z protokolu kusového ověření **odstranit**“, text „orientační – neověřeno proti normě“ | Otázka je zodpovězená; otevřené zůstává, **čím** oteplení v protokolu nahradit (Q1) |
| R9 | `docs/ROADMAP.md:3` odkazuje na `docs/research/03_srovnani.md` | soubor neexistuje (ani v `docs/research/`) | Tento soubor se jmenuje `03_doporuceni.md`; odkaz v ROADMAP opravit (NEW-4) |

---

## 1. Stav projektu v jednom odstavci

EnvoCAD (v0.11.0, `main` @ `76c0818`) je funkčně bohatý a dobře hlídaný: JPS editor, generátor FVE ze specifikace
(firma nn/vn, RD), rozvaděče (schéma, vícepól, rozložení), svorkovnice a můstky, výkazy xlsx, PDF dokumentace se
záložkami, DXF listů, TZ/DSPS, revize, připomínky, ~80 kontrol F7 a CLI se skripty; 101 testovacích souborů (~1 424
testů dle grepu), hlídače architektury a CI Linux/Windows × 3.12/3.14 (01a §1, §4.4). Hlavní slabiny nejsou v rozsahu,
ale v **důvěryhodnosti a toku práce**: výpočty Iz a oteplení jsou orientační a v protokolu kusového ověření vystupují jako
průkaz (#80), data knihovny jsou neúplná (222 artiklů bez rozměrů, 138 jističů bez Pv, 0 cen ve vestavěných CSV),
hotová práce na cenách a ETI rozvodnicích leží ve větvi mimo `main` (PR #62/#63), noční agenti mají nízkou úspěšnost
(#66 8× selhání, 12 issues se zastaralým `agent-in-progress` bez PR) a sedm agentních PR (#96–#98, #105–#108) čeká
na review člověka. Rešerše norem a distributorů ukazuje, že další přírůstek hodnoty je v **ověřitelnosti výpočtů**
(rozsah platnosti metody, doklad o ověření návrhu) a v **podkladech pro distributora** (údaje žádosti, kontroly
úplnosti), přičemž obojí blokují oborová rozhodnutí projektanta.

---

## 2. Seřazený backlog

Priorita: V / S / N (vysoká / střední / nízká). Náročnost: S (hodiny), M (dny), L (týden+). Sloupec **Agent**:
`ready` = lze dát štítek `agent-ready` hned; `po rozh.` = nejdřív rozhodnutí projektanta (otázka Q v kap. 7);
`člověk` = práce/merge jen pro člověka; `review` = PR existuje, čeká na člověka. `NEW-n` = nová issue, text v kap. 6.

| # | Položka | Prio | Nár. | Agent | Závislosti | Zdroj inspirace / důkaz |
|---|---|---|---|---|---|---|
| 1 | **Začlenit větev `feature/papir-eti-svodice` (PR #62/#63) do `main`** – PR z větve do `main`, CI, merge | V | S | člověk | rozhodnutí o obsahu (ETI CSV, ceník) | kap. 0(a); 01b §2 |
| 2 | **Review a merge agentních PR** #96 (#75), #97 (#68), #98 (#74), #105 (#83), #106 (#70), #107 (#67), #108 (#81) | V | S | review | #97 nejdřív NEW-1 (Windows CI) | 01b §2; `gh pr list` |
| 3 | **NEW-1** Testy: `LibraryStore` jako context manager, zavírat spojení (Windows WinError 32) | V | S | ready | – | 01b §2 (PR #97 log); `store.py:318 close()` bez `__enter__` |
| 4 | **#80** Výpočty orientační, oteplení pryč z protokolu | V | S–M | ready (rozhodnuto) | – | 02B P1 (SIMARIS vodoznak), 02C N1/N2, ROADMAP Top10 #1 |
| 5 | **#81** Atribuce QET (PR #108) | V | S | review | Q16 (zákaz ML) | 02A §3.1, #19; 02C N15 |
| 6 | **NEW-2** CLI: návratový kód podle závažnosti F7 (`--fail-on`) | V | S | ready | – | 02A #3 (`kicad-cli … --exit-code-violations`) |
| 7 | **#79** Soupis údajů z norem | V | S–M | ready | – | 02C kap. 3–7, 02B kap. 10 |
| 8 | **NEW-13** Protokol kusového ověření: odkaz na ověření návrhu místo oteplení | V | S–M | po rozh. (Q1) | #80 | 02C N1, kap. 3; 02B P17 (Rittal certifikát) |
| 9 | **NEW-12** Oteplení: hlásit „mimo rozsah metody IEC TR 60890“ | V | S–M | po rozh. (Q2) | #80 | 02B P6, 02C N3; SIMARIS therm hláška |
| 10 | **NEW-14** Oteplení: nezávislý test účinné chladicí plochy Ae | S | S | po rozh. (Q2 – potvrdit přiřazení) | – | 02B P5 (Rittal katalog [S21]); kap. 0 R4 |
| 11 | **#82** Ověřit tabulky Iz a k/c (přeformulovat – kap. 3) | V | M | po rozh. (Q2, Q3, Q8) | #79, data od člověka | 02B P4/P7, kap. 10; 02C N18 |
| 12 | **NEW-3** Hlídač čistoty: `generator` v `QT_FREE` | S | S | ready | – | 01a §4.1 (`test_model_pure.py:92`) |
| 13 | **NEW-4** Dokumentace: FORMAT_VERSION 18 a nesoulady ROADMAP | S | S | ready | – | 01a §5.6; kap. 0(b), R9 |
| 14 | **#104**, **#102**, **#103**, **#101** – opravy z review | S (#101 V) | S | #104 ready; ostatní po merge PR | #99/#97/#98/#96 sloučené | 01b §1, §7 |
| 15 | **#87** Ceny ve výkazech (přeformulovat po bodu 1) | S | S | po rozh. (Q15 DPH) | bod 1 | 01b §4; kap. 0(a) |
| 16 | **NEW-15** Data pro DS: údaje žádosti (EAN, katastr, parcela, ostrovní provoz) | S | S–M | po rozh. (Q4) | – | 02D G1, K18; kap. 0 R1 |
| 17 | **NEW-16** F7: úplnost podkladů pro distributora – fáze 1 (údaje, které model má) | S | S–M | po rozh. (Q4, Q6) | – | 02D K3, K7, K12, K14 |
| 18 | **NEW-17** Data pro DS: kategorie výrobního modulu A1/A2/B1… a Pi podle distributora | S | S | po rozh. (Q5) | NEW-15 | 02D K5, K4, kap. 1 (ČEZ Tab. 1) |
| 19 | **NEW-5** Štítky CSV: logika z GUI do `export/` + test | S | S | ready | – | 01a §1.2, §5.4, §5.5 |
| 20 | **NEW-6** Symbol JSON: `format_version`, novější se odmítne | S | S | ready | – | 02A #1 (KiCad, Horizon `version.html`) |
| 21 | **NEW-7** Knihovna SQLite: verze schématu (`PRAGMA user_version`) | S | S | ready | – | 02A #7 (Horizon pool); 01a §2 |
| 22 | **NEW-8** Knihovna: artikly odebrané z vestavěných CSV zmizí z `library.db` | S | S | ready | NEW-7 vhodně dřív | 01a §5.3; 02A #7; souvisí #101 |
| 23 | **NEW-9** Chráněné atributy: jedna konstanta | S | S | ready po merge #98 | #98 | 02A #6 (KiCad `ki_*`); 01b §3 |
| 24 | **#77** Hromadná úprava (přeformulovat – rozhodnutí B do těla) | S | M | ready po úpravě | NEW-9 | 02A #5 (Symbol Fields Table) |
| 25 | **#71** Duplikovat list (rozdělit – kap. 3) | S | M | ready po rozdělení | – | 02A §1.2a (UUID instance), #20 |
| 26 | **NEW-10** F7: potlačení nálezu s důvodem – model a CLI | S | M | ready (návrh `architekt`) | – | 02A #2 (KiCad `rule_severities`, `m_ErcExclusions`) |
| 27 | **NEW-11** F7: potlačené nálezy v GUI | S | S–M | ready | NEW-10 | totéž |
| 28 | **#73** Klikací křížové odkazy PDF | S | M | ready (po #104) | #104 (stejné soubory) | 02A #21 (KiCad PDF s odkazy) |
| 29 | **#88** DXF rozložení a plánu svorkovnice (rozdělit 88a/88b) | S | M | ready po rozdělení | – | 02A #14 (ezdxf bloky/ATTRIB/vrstvy) |
| 30 | **#86** Import PVsyst .PAN/.OND | S | S–M | ready | – | 02A #17 (pvlib `read_panond`, BSD-3 – jen myšlenka) |
| 31 | **NEW-18** CI: měřit pokrytí (report bez prahu) + přeformulovat #66 | S | S | ready | – | 01a §4.4 (`--cov` chybí) |
| 32 | **#66**, **#67** charakterizační testy (#67 má PR #107) | N | S | #66 po přeformulování | NEW-18 | 01b §6 |
| 33 | **NEW-19** Plugin API: `API_VERSION` a `add_check` | N | S–M | ready | – | 02A #12 (KiCad PCM, IPC pravidla) |
| 34 | **NEW-20** Úklid: zbytky QR v rámečku | N | S | ready | – | 01a §5.3 (`frame.py:70`, `render.py:160,188`) |
| 35 | **#85** Editor symbolů (rozdělit na fáze) | N | L | ready po rozdělení | NEW-6 | 02A #10 (QET editor, kolekce) |
| 36 | **#84** BMEcat parser | N | M | po rozh. (Q12, rozpor s ROADMAP) | vzorový soubor | 02C N7, kap. 10 |
| 37 | **#76** Legenda značek (doplnit zadání) | N | M | po rozh. (Q14) | – | 02C N14; 02A #15 (ezdxf `TablePainter`) |
| 38 | **#69** Varování na kopie makra (doplnit zadání) | N | S | po doplnění | – | 01b §6 |
| 39 | **#89** Vícepatrové svorky | N | M | po rozh. (otázky v issue) | – | 02A #11 (QET terminal strip, `level`) |
| 40 | **#90** Podepsaný build | S | M | po rozh. (způsob podpisu) | – | 01b §6 |
| 41 | **#91** Anglické UI | N | L | ready (návrh) | – | 02A #13 (gettext pro jádro, `tr()` v UI) |
| – | *Později, bez issue:* výkaz jako uložený preset (02A #4), model Pv přístroje a průvodce oteplení (02B P2/P3/P8), JPS „pro distributora“ s rolemi (02D G2, K2, K8–K10, K13), protokol nastavení ochran (02D G6, K17), ETIM pole a xChange (02C N6/N8), číslování podle třídy 81346 (02C N10), headless PDF (02A #16), stroje na vodiče, Brady/Partex | N | M–L | po rozh. | Q4–Q13 | viz zdroje |

**Zdůvodnění pořadí.**
1. **Nejdřív uvolnit hotovou práci** (body 1–3): větev s ceníkem a sedm PR jsou hotový kód, který jen čeká; NEW-1 odblokuje
   Windows CI u PR #97 a zabrání opakování u dalších testů s knihovnou.
2. **Pak důvěryhodnost dokumentů** (4–11): je to ROADMAP Top10 #1–#3 a jediné místo, kde EnvoCAD může vydat zavádějící průkaz
   zákazníkovi. #80 je rozhodnutá a malá; NEW-12/13/14 navazují a potřebují jen krátké odpovědi projektanta.
3. **Levné hygienické úkoly pro agenty** (12–13, 19–23) – jasné, bez oborových rozhodnutí, snižují riziko (licenční hlídač,
   formáty, knihovna) a zvyšují úspěšnost nočních běhů.
4. **Podklady pro distributora** (16–18) mají velký přínos pro každou zakázku, ale závisí na tom, které kategorie a
   distributory ENVO podává (Q4) – proto až po odpovědi.
5. **Editace a výstupy** (24–30) jsou užitečné, ale ne kritické; některé je nutné před předáním agentům rozdělit.
6. **Velké nebo blokované** (35–41) až po rozhodnutích; #85 a #91 mají malý přínos vůči rozsahu.

Pro agenty hned (`agent-ready` bez dalšího rozhodnutí): NEW-1, NEW-2, NEW-3, NEW-4, NEW-5, NEW-6, NEW-7, NEW-8, NEW-10,
NEW-11, NEW-18, NEW-19, NEW-20, #80, #79, #104, #86; po merge #98 NEW-9. **Rozhodnutí projektanta předem:** NEW-12,
NEW-13, NEW-14, NEW-15, NEW-16, NEW-17, #82, #87, #84, #76, #89, #90.

---

## 3. Issues doporučené k zavření, sloučení nebo přeformulování (jen návrh)

| Issue / PR / větev | Návrh | Důvod a důkaz |
|---|---|---|
| **#65** (zavřená) | **Nechat zavřenou** | Příčina opravena v PR #64 (`envocad/generate.py` `_DeprecatedModule.__delattr__`, `updater.read_manifest`); úklid zajišťuje teardown `monkeypatch`. Doslovná podmínka „try/finally“ nesplněna, ale je bezpředmětná. Kap. 0(c). Ověřit jen během `pytest` na 3.14 |
| **Větev `feature/papir-eti-svodice`** (PR #62, #63) | **Otevřít PR → `main`** (člověk), po zelené CI sloučit | 3 commity mimo `main`, bez textových konfliktů (`git merge-tree`); obsah viz kap. 0(a). Zároveň zvážit pravidlo v `agent-*.yml`/šabloně PR „base musí být `main`“ |
| `feature/hybrid-baterie-eps` | Po sloučení bodu výše smazat (člověk) | Před `main` jen o merge #62 a `0c5e968`, které obsahuje i `feature/papir-eti-svodice` |
| **#87** Ceny ve výkazech | **Přeformulovat** po sloučení větve: ponechat jen to, co `priced_bom` nedělá (list „Rozpočet“ v `export_reports_xlsx`, formát Kč, hláška „N položek bez ceny“, DPH) | Ceník `~/.envocad/ceny.csv` + `priced_bom` + `tests/test_prices.py` existují ve větvi; které části zadání #87 kryjí, neověřeno |
| **#66** Testy nejméně pokrytých modulů | **Přeformulovat** na 1 modul = 1 issue s konkrétním souborem (`generator/pv.py`, `generator/tigo.py`, `generator/boards/groups.py`, `generator/boards/macro_glue.py`) a odebrat `agent-in-progress` | 8× „Noční agent issue nedokončil“ (01b §1); vágní „3–5 modulů“, pokrytí se neměří (NEW-18) |
| **#69**, **#76** | Odebrat `agent-ready`, dokud se nedoplní zadání | 3× selhání; #69 neříká, jak poznat kopii s odpínačem; #76 nemá formát tabulky a rozsah značek (01b §6); #76 navíc mění `doc_pdf.py` jako #73/#104 |
| **#71** Duplikovat list | **Rozdělit**: (a) duplikace listu s přeznačením kopie (rozhodnuto v komentáři: 1c, 2b, 3); (b) nová issue „Generátor: volitelné značení rozvaděčů (název a číslo)“ s vlastními kritérii | Komentář vlastníka přidal nový rozsah bez akceptačních kritérií (01b §6) |
| **#77** Hromadná úprava | **Přeformulovat** tělo: rozhodnutí „B“ (nový atribut `note` u prvku + pole v panelu) a kde se poznámka zobrazuje; navázat na NEW-9 | Tělo issue stále mluví o „poznámce“ bez definice (01b §6) |
| **#82** | **Přeformulovat**: přidat formát referenční sady `tests/data/ref_thermal.json` (čísla + nástroj + verze + datum + odkaz, bez textu norem) a test s tolerancí; hodnoty dodá člověk | 02B P4, kap. 10; 02C N18; otázka „jak ukládat“ je otevřená (01b §6) |
| **#85** Editor symbolů | **Rozdělit** na: 85a náhled symbolu + seznam portů (jen čtení), 85b úprava portů s mřížkou 2,5 mm, 85c úprava atributů a uložení do uživatelské knihovny | Fáze 1 je podle 01b §6 na víc než pár hodin; vzor QET (02A §3.2c) |
| **#88** DXF rozložení | **Rozdělit** 88a rozložení rozvaděče (bloky přístrojů s ATTRIB `ref`, vrstvy lišt/žlabů), 88b plán svorkovnice | Zadání samo navrhuje rozdělení (01b §6); geometrie je zčásti v `ui/layout_view.py` (Qt) – nejdřív zjistit, co je v `model/` |
| **#73** | Smazat z těla závislost na #72 (hotovo); řadit **po #104** | Stejné soubory `doc_pdf.py`, `pdf_outline.py` (01b §3) |
| **#84** BMEcat | Rozhodnout: buď odebrat `agent-ready`/`agent-in-progress` v souladu s ROADMAP „Odloženo – až budou soubory“, nebo upravit ROADMAP | Rozpor R6; bez reálného vzorového souboru (Q12) je parser na smyšleném vzoru |
| **#70** a **#83** | Nesloučovat (oba mají PR #106/#105); po merge zvážit sdílení kódu | 01b §3 – jediná blízká dvojice |
| Štítky `agent-in-progress` bez PR | Odebrat u #66, #69, #71, #73, #76, #77, #80, #84, #85, #86, #88, #91 (člověk / workflow) | `gh issue list` 22. 11.; agent podle CLAUDE.md nebere issue s `agent-in-progress`, takže zastaralý štítek issue blokuje |
| PR #96, #97, #98 | Doplnit popis (Shrnutí, Mimo rozsah) – vyžaduje šablona PR | Popis „Closes #N“ (01b §2); novější PR #105–#108 už shrnutí mají |

---

## 4. Rychlá vítězství (do 1–2 týdnů, velký přínos)

1. **Sloučit ceník a ETI rozvodnice do `main`** (bod 1) – hotový kód (`envocad/library/prices.py`, `export/reports.py:priced_bom`,
   `library/builtin/components/enclosures_eti.csv`, menu velikosti papíru) se dostane uživatelům; #87 se zmenší na zbytek.
2. **#80** – odstranit řádek „Oteplení (IEC TR 60890, výpočet)“ z protokolu (`export/docx_export.py:229`) a označit výsledky
   „orientační – neověřeno proti normě“ (rozhodnuto). Největší snížení rizika za nejmenší práci.
3. **Merge PR #108 (#81)** – licenční soulad atribuce QET při veřejném repozitáři.
4. **NEW-1** – `LibraryStore.__enter__/__exit__` (`library/store.py:78, 318`) + použití v testech → konec `WinError 32` na Windows CI.
5. **NEW-2** – `python -m envocad.cmd … --fail-on chyba` (`cmd/__main__.py`): agenti a CI poznají projekt s chybami F7 bez parsování textu.
6. **NEW-3** – přidat `"generator"` do `QT_FREE` (`tests/test_model_pure.py:92`): pravidlo z `CLAUDE.md` začne hlídat test.
7. **NEW-4** – opravit `docs/ARCHITECTURE.md:279`, `docs/LIBRARY_FORMAT.md:464` (18), `docs/ROADMAP.md:3, 36, 86, 104–105`.
8. **NEW-5** – přesun `export_labels_csv` z `ui/main_window.py:2033` do `export/` s testem: odstraní business logiku z GUI a připraví Brady/Partex.
9. **NEW-14** (po potvrzení Q2) – test `thermal.cooling_area` proti 3 vzorcům Rittal, které kód už pokrývá (kap. 0 R4).
10. **NEW-18** – `pytest --cov` v CI jako artefakt: podklad pro přeformulované #66.

---

## 5. Převzatelné části z open-source projektů a standardů s ohledem na licence

EnvoCAD je MIT. „Myšlenka“ = převzít postup/strukturu vlastními slovy a vlastním kódem; „nelze“ = do repozitáře nepatří.
Licenční závěry jsou technické doporučení ze vstupů, ne právní rada (02A úvod, §9 bod 9).

| Co | Odkud | Licence | Způsob | Poznámka k MIT |
|---|---|---|---|---|
| Verze formátu po typu souboru, odmítnutí novějšího | KiCad `.kicad_sch`, Horizon `version.html` (02A §1.2a, §2.2b) | GPL-3 | myšlenka | Bez kopírování kódu OK → NEW-6, NEW-7 |
| ERC: závažnost per pravidlo, seznam výjimek, návratový kód CLI | KiCad `erc_settings`, `kicad-cli sch erc` (02A §1.2b) | GPL-3 | myšlenka | → NEW-2, NEW-10, NEW-11 |
| Tabulka polí symbolů, rezervovaný prefix klíčů | KiCad Symbol Fields Table (02A §1.2d) | GPL-3 | myšlenka | → NEW-9, #77 |
| SQLite jako přestavitelný index nad JSON/CSV, UUID, verze | Horizon pool (02A §2.2a) | GPL-3 (pool licence neověřena) | myšlenka | → NEW-7, NEW-8 |
| Deklarativní mapování sloupec → atribut | KiCad `.kicad_dbl` (02A §1.2f) | GPL-3 | myšlenka | Později k #84/#86 |
| Editor prvků, kolekce builtin/firemní/uživatelská/vložená | QElectroTech (02A §3.2c) | GPL-2 | myšlenka | → #85; kód QET nikdy nekopírovat |
| Nomenklatura/BOM jako uložená konfigurace | QET v0.8, KiCad BOM preset (02A §3.2b) | GPL | myšlenka | Později (výkaz preset) |
| Značky QET (673 prvků) | QET `ELEMENTS.LICENSE` (02A §3.1) | **CC BY 3.0 + zákaz použití pro trénink ML** | data (už v repu) | Atribuce + oznámení úprav (#81, PR #108); slučitelnost klauzule ML s MIT a s prací agentů – Q16 |
| Knihovny symbolů KiCadu | KiCad (02A §1.1) | CC-BY-SA 4.0 s výjimkou | **nelze** do repa | Share-alike se s MIT nemíchat; pro FVE i nepoužitelné |
| DXF bloky, ATTRIB, vrstvy, `TablePainter` | ezdxf (02A §5) | **MIT** | kód / závislost (už je) | → #88, #76 bez nové závislosti |
| Headless vykreslení DXF → SVG/PDF | ezdxf drawing add-on (02A §5.2) | MIT; **PyMuPDF AGPL** | závislost jen SVGBackend / Matplotlib | **PyMuPdfBackend nepoužívat** (AGPL) |
| Parser PVsyst `.PAN/.OND` | pvlib `read_panond` (02A §6.2) | BSD-3 | myšlenka / přepis s atribucí | pvlib jako závislost ne (numpy, pandas, scipy…) → #86 |
| Zkratové výpočty IEC 60909 jako reference v testech | pandapower (02A §6.1) | BSD-3 | jen dev/test závislost, nebo nic | Hodnoty `std_types` nepřebírat (zdroj neznámý) |
| Pluginy: metadata kompatibility, verze API | KiCad PCM/IPC, FreeCAD Addon Manager (02A §1.2g, §4.2) | GPL / LGPL | myšlenka | → NEW-19 |
| Lokalizace gettext pro jádro, Weblate | KiCad (02A §1.2h) | GPL | myšlenka | stdlib `gettext` bez nové závislosti → #91 |
| Metodika oteplení (2 metody, vodoznak „nedokončeno“, mez platnosti, chlazení) | SIMARIS therm, Rittal Therm, ProClima (02B §2.3, §7, §4.3) | proprietární | myšlenka + fakta s odkazem | Databáze Pv a texty protokolů **nelze** |
| Vzorce účinné plochy Ae (7 způsobů instalace) | Rittal katalog [S21] (02B §7) | proprietární dokument, vzorce = fakta | fakta do testu s `url` | → NEW-14; přiřazení ověřit v normě |
| Struktura výstupu (volitelné sekce, tabulka kabelů s OK/–, „zámek“) | ABB DOC (02B §3.1) | proprietární | myšlenka | Později (02B P10–P12) |
| Tabulky selektivity / koordinace výrobců | OEZ, ABB, Eaton (02B §0 bod 6) | proprietární | **nelze** | Jen ruční potvrzení s odkazem (02B P15) |
| ETIM model a třídy | ETIM International (02C §8) | **ODC-BY 1.0** | data s atribucí | Jazykové verze DE/PL placené; CZ/SK neověřeno |
| ETIM xChange (JSON + schéma) | ETIM (02C §8) | **Apache 2.0** | formát / schéma | Slučitelné s MIT (zachovat NOTICE) |
| BMEcat | BME (02C §10) | volně použitelný formát | formát | Python parser nenalezen; stdlib `xml.etree` (`lxml` = nová závislost) |
| ECLASS | ECLASS e.V. (02C §9) | placená licence (formát Asset zdarma) | jen ID třídy | Obsah do repa **nelze** |
| IEC 60617 grafika značek | IEC (02C §2) | © IEC, zákaz kopírování podstatných částí | **nelze** | Jen identifikátor v `Symbol.iec_ref` |
| Formuláře, typová schémata, vzory distributorů | ČEZ, EG.D, PRE, ZSD, SSD (02D §7 pozn.) | © distributor | **nelze** kopírovat | Vlastní tabulky se stejnými údaji + odkaz na zdroj |

---

## 6. Návrhy nových issues (hotové texty)

Styl podle šablony `.github/ISSUE_TEMPLATE/agent-task.yml` a issues #65, #80, #83 (oddíly Cíl / Podmínka hotovo /
Kde v kódu / Oborová rozhodnutí / Mimo rozsah / Hlavní oblast). Všechny mají štítek `agent-task`; `agent-ready` jen tam,
kde je uvedeno. Každá je dimenzována na pár hodin.

---

### NEW-1 Testy: `LibraryStore` jako context manager, zavírat spojení (Windows WinError 32)
**Štítky:** `agent-task`, `agent-ready` · **Oborové rozhodnutí:** ne

```markdown
### Cíl
Testy, které otevírají knihovnu v dočasném adresáři, na Windows neselhávají na `PermissionError [WinError 32]`
při mazání `lib.db`. Knihovnu lze bezpečně otevřít přes `with LibraryStore(...) as lib:`.

### Podmínka hotovo
- nejdřív test: `tests/test_library_store_close.py` – `with LibraryStore(tmp / "lib.db", load_builtin=False) as lib:`
  po výstupu z bloku je spojení zavřené (další dotaz vyhodí výjimku) a soubor jde smazat (`unlink`)
- `LibraryStore.__enter__` / `__exit__` (volá existující `close()`, výjimky nepotlačuje)
- testy, které vytvářejí `LibraryStore` nad `tmp_path`, spojení zavírají (fixture nebo `with`); minimálně nový test
  z PR #97 (`tests/test_bom_by_manufacturer.py`) – pokud ještě není sloučen, uveď v PR, kde se má změna použít
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené (CI i na Windows); záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/library/store.py:78` (`__init__`), `:318` (`close`)
- log PR #97: Testy windows 3.12/3.14 – `PermissionError WinError 32` na `lib.db` v dočasném adresáři

### Oborová rozhodnutí
Žádná.

### Mimo rozsah
Změny schématu knihovny, chování `sync_builtin`, úpravy jiných testů než těch, které knihovnu nezavírají.

### Hlavní oblast
testy (pokrytí existujícího kódu)
```

---

### NEW-2 CLI: návratový kód podle závažnosti nálezů F7 (`--fail-on`)
**Štítky:** `agent-task`, `agent-ready` · **Oborové rozhodnutí:** ne

```markdown
### Cíl
Skript nebo agent pozná z návratového kódu `python -m envocad.cmd`, že projekt má nálezy F7 dané závažnosti,
bez parsování textu. Výchozí chování se nemění.

### Podmínka hotovo
- nejdřív testy v `tests/test_cmd_script.py` (nebo novém souboru):
  - bez přepínače se návratový kód nemění (0 při úspěchu skriptu i s nálezy)
  - `--fail-on chyba` vrátí nový kód (např. `CHECKS_FAILED = 3`) právě když existuje nález `chyba`
  - `--fail-on varování` vrátí tentýž kód při nálezu `varování` nebo `chyba`; `info` nikdy
  - chyba skriptu má dál přednost (`COMMAND_ERROR = 1`), špatná hodnota přepínače = `USAGE_ERROR = 2`
- hodnoty přepínače = konstanty `ERROR, WARNING` z `envocad/model/checks.py:42` (ne kopírované řetězce)
- nápověda `-h` a `docs/` (kde je CLI popsané) doplněny česky
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/cmd/__main__.py` (konstanty ř. 19, souhrn `counts` a `return` na konci `main`)
- `envocad/model/checks.py:42` (`ERROR, WARNING, INFO`)
- inspirace: `kicad-cli sch erc --exit-code-violations` (docs/research/02_A_opensource.md §1.2b)

### Oborová rozhodnutí
Žádná (závažnosti nálezů se nemění).

### Mimo rozsah
Změna závažností nebo textů nálezů, potlačení nálezů (samostatná issue).

### Hlavní oblast
jádro (model, knihovna, generátor, export)
```

---

### NEW-3 Hlídač čistoty: `generator/` bez Qt v `test_model_pure`
**Štítky:** `agent-task`, `agent-ready` · **Oborové rozhodnutí:** ne

```markdown
### Cíl
Pravidlo z CLAUDE.md „`generator/` – BEZ Qt“ hlídá test stejně jako u `model`, `library` a `cmd`.

### Podmínka hotovo
- `tests/test_model_pure.py`: `QT_FREE` obsahuje `"generator"`; test projde (dnes generator Qt neimportuje – ověřit)
- pokud test odhalí import Qt, **neopravuj** kód tichým obejitím – popiš nález v PR jako „Mimo rozsah“ a zeptej se v issue
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `tests/test_model_pure.py:92` (`QT_FREE = ("model", "library", "cmd")`), `:106`
- docs/research/01a_inventura.md §4.1

### Oborová rozhodnutí
Žádná.

### Mimo rozsah
Úpravy `export/` (PDF na Qt závisí záměrně).

### Hlavní oblast
testy (pokrytí existujícího kódu)
```

---

### NEW-4 Dokumentace: FORMAT_VERSION 18 a nesoulady v ROADMAP
**Štítky:** `agent-task`, `agent-ready` · **Oborové rozhodnutí:** ne

```markdown
### Cíl
Dokumentace odpovídá kódu – agent ani člověk se nespletou o verzi formátu a stavu funkcí.

### Podmínka hotovo
- `docs/ARCHITECTURE.md:279` a `docs/LIBRARY_FORMAT.md:464`: aktuální `FORMAT_VERSION` = 18 (podle
  `envocad/model/project.py:70`), u v18 stručně co přinesla (podle `migrate` a `changelog.d/`)
- `docs/ROADMAP.md`: ř. 3 odkaz na neexistující `docs/research/03_srovnani.md` opravit (existující soubor v `docs/research/`
  nebo odkaz odstranit); ř. 86 „QR v popisovém poli“ (QR odstraněn – `changelog.d/2026-10-27-bez-qr-kodu.md`);
  ř. 36 a 105 „logo doplnit“ (logo je v `envocad/resources/envo_logo.json`); ř. 104 nesoulad `[ ]` vs. „hotovo“
- `docs/design/ux_lista.md`: stav „návrh“ → podle skutečnosti
- volitelně test, který porovná číslo v `ARCHITECTURE.md` s `FORMAT_VERSION` (aby se nesoulad neopakoval)
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
docs/research/01a_inventura.md §5.6 (tabulka nesouladů)

### Oborová rozhodnutí
Žádná – měnit jen popis stavu, ne priority v ROADMAP.

### Mimo rozsah
Přepis priorit a obsahu ROADMAP, `examples/ukazka_fve.ecp` (format_version 1).

### Hlavní oblast
dokumentace
```

---

### NEW-5 Štítky CSV: export z GUI do `export/` a test
**Štítky:** `agent-task`, `agent-ready` · **Oborové rozhodnutí:** ne

```markdown
### Cíl
Export štítků do CSV je funkce exportu (bez Qt), otestovaná a volatelná z CLI/pluginu; GUI jen volá funkci.
Připraví půdu pro formáty tiskáren (Brady/Partex).

### Podmínka hotovo
- nejdřív test charakterizující dnešní výstup (oddělovač `;`, kódování, sloupce) na malém projektu
- nová funkce v `envocad/export/` (např. `labels_csv.py:write_labels_csv(project, lib, path)`), bez Qt
- `ui/main_window.py:export_labels_csv` volá novou funkci, výstup bajtově shodný s dneškem
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/ui/main_window.py:2033` (`export_labels_csv`)
- `envocad/export/reports.py` (`labels`, `marking`)
- docs/research/01a_inventura.md §1.2, §5.4, §5.5

### Oborová rozhodnutí
Žádná (formát se nemění).

### Mimo rozsah
Formáty Brady/Partex/M-Print, nové sloupce, příkaz CLI.

### Hlavní oblast
jádro (model, knihovna, generátor, export)
```

---

### NEW-6 Symbol JSON: `format_version`, novější verzi odmítnout
**Štítky:** `agent-task`, `agent-ready` · **Oborové rozhodnutí:** ne (formát navrhne `architekt`)

```markdown
### Cíl
Symbol JSON nese číslo verze formátu. Starší EnvoCAD symbol z novější verze nenačte potichu špatně, ale ohlásí
česky „symbol vytvořen novější verzí EnvoCAD“ – stejně jako u projektu `.ecp`.

### Podmínka hotovo
- `SYMBOL_FORMAT_VERSION = 1` v `envocad/model/symbol.py`; chybějící pole = verze 1 (všechny dnešní JSON platí beze změny)
- načtení symbolu s vyšší verzí → výjimka / přeskočení s českou hláškou (v knihovně se zbytek načte)
- zápis symbolu (import DXF/QET, uložení) pole zapisuje
- testy: starý JSON bez pole, aktuální, novější
- `docs/LIBRARY_FORMAT.md` doplněn; `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/model/symbol.py` (`Symbol`), `envocad/library/store.py`, `envocad/library/dxf_import.py`, `qet_import.py`
- docs/research/02_A_opensource.md §1.2a, §2.2b (KiCad, Horizon – verze po typu souboru); 01a §2 („symbol nemá pole verze“)

### Oborová rozhodnutí
Žádná.

### Mimo rozsah
Hromadné přepsání 48 + 673 JSON souborů (pole je nepovinné), verze CSV artiklů a specifikace generátoru.

### Hlavní oblast
jádro (model, knihovna, generátor, export)
```

---

### NEW-7 Knihovna SQLite: verze schématu a přestavba
**Štítky:** `agent-task`, `agent-ready` · **Oborové rozhodnutí:** ne

```markdown
### Cíl
`~/.envocad/library.db` má číslo verze schématu. Při změně schématu se databáze vestavěných dat bezpečně přestaví
a uživatelská data se nepřijdou.

### Podmínka hotovo
- `LIBRARY_SCHEMA_VERSION` v `envocad/library/store.py`, uloženo přes `PRAGMA user_version`
- databáze bez verze (dnešní) = verze 1; novější verze → česká hláška, knihovna se neotevře pro zápis
- při nižší verzi migrace (zatím jen zápis čísla); připravená funkce pro budoucí převody
- testy nad dočasnou DB: nová, stará bez verze, novější
- `docs/ARCHITECTURE.md` doplněn; `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/library/store.py:21` (schéma), `:78` (`__init__`)
- docs/research/02_A_opensource.md §2.2a (Horizon: SQLite jako přestavitelný index); 01a §2

### Oborová rozhodnutí
Žádná.

### Mimo rozsah
Změna sloupců (kategorie do sloupce), PostgreSQL, mazání artiklů (samostatná issue).

### Hlavní oblast
jádro (model, knihovna, generátor, export)
```

---

### NEW-8 Knihovna: artikly odebrané z vestavěných CSV zmizí z `library.db`
**Štítky:** `agent-task`, `agent-ready` · **Oborové rozhodnutí:** ne

```markdown
### Cíl
Když se artikl odstraní z vestavěného CSV (oprava dat, přejmenování id), po synchronizaci knihovny už ho uživatel
nevidí. Dnes se mažou jen zastaralé vestavěné **symboly**, artikly zůstávají.

### Podmínka hotovo
- nejdřív test: vestavěný CSV se 2 artikly → sync → z CSV jeden odebrat → sync → v DB zůstane jen jeden
- uživatelské a sdílené artikly (ne-vestavěné) se nemažou (test)
- artikl použitý v otevřeném projektu se nemaže potichu ze souboru projektu (projekt nese `component_id`; F7 má hlásit
  neznámý artikl – ověř, že takový nález existuje, jinak popiš v PR jako „Mimo rozsah“)
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/library/store.py:119–120` (mazání vestavěných symbolů – vzor), `:158–190` (sync artiklů, `DELETE` chybí)
- souvisí s #101 (archiv nesmí přepsat vestavěné artikly)
- docs/research/01a_inventura.md §5.3

### Oborová rozhodnutí
Žádná.

### Mimo rozsah
Mazání artiklů z uživatelské/sdílené knihovny v GUI, oprava #101.

### Hlavní oblast
jádro (model, knihovna, generátor, export)
```

---

### NEW-9 Chráněné atributy: jedna konstanta pro hledat/nahradit a hromadnou úpravu
**Štítky:** `agent-task` (`agent-ready` až po sloučení #98) · **Oborové rozhodnutí:** ne (seznam je převzatý z rozhodnutí v #77 a review #98)

```markdown
### Cíl
Které atributy prvku se nesmí měnit hromadně (hledat/nahradit, hromadná úprava), je definováno na jednom místě
v `model/`, ne rozptýleně v GUI a `cmd/`.

### Podmínka hotovo
- konstanta (např. `PROTECTED_ATTRS`) v `envocad/model/` – obsahuje dnes chráněné klíče z `cmd/edits.py` (PR #98:
  `ports_in/out`, `sheet`, `acts_on`, `busbar.PARAM_KEYS`, `terminal`, `terminals`, `contacts`) a `ref` z rozhodnutí #77
- `cmd/edits.py` (hledat/nahradit) ji používá; test, že chráněný klíč se nezmění
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/cmd/edits.py` (po sloučení PR #98), #77, #103
- docs/research/02_A_opensource.md §1.2d (KiCad – rezervovaný prefix `ki_`)

### Oborová rozhodnutí
Žádná nová – seznam jen sjednocuje existující rozhodnutí. Přidání dalšího klíče = otázka v issue.

### Mimo rozsah
Implementace hromadné úpravy (#77).

### Hlavní oblast
jádro (model, knihovna, generátor, export)
```

---

### NEW-10 F7: potlačení nálezu s důvodem – datový model a CLI (fáze 1)
**Štítky:** `agent-task`, `agent-ready` (s návrhem agenta `architekt`) · **Oborové rozhodnutí:** ne (co potlačit, rozhoduje uživatel v projektu)

```markdown
### Cíl
Projektant může konkrétní nález F7, který posoudil, označit jako „posouzeno“ s důvodem. Nález se pak nepočítá do
souhrnu, ale nezmizí – je vidět v seznamu potlačených a v protokolu změn. Dnes ~80 kódů nálezů nelze nijak potlačit.

### Podmínka hotovo
- nejdřív testy (`tests/test_checks_waivers.py`):
  - `Project.waivers` (seznam: `code`, `target_id`, `sheet_id`, `reason`, `author`, `date`) se uloží a načte
  - `check_project` vrátí nález s příznakem potlačení (nebo zvlášť), souhrn je bez něj
  - nález, jehož prvek zmizel, nechá potlačení „osiřelé“ a F7 to hlásí jako `info`
- `FORMAT_VERSION` + 1 a migrace (prázdný seznam), test v `tests/test_migration.py`
- příkaz CLI `waive <kód> <id> <důvod>` nebo rozšíření `checks` – podle návrhu `architekt`; parita GUI↔CLI zatím ne
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/model/checks.py:55` (`Finding` – `code`, `target_id`, `sheet_id` tvoří stabilní klíč), `:70` (`check_project`)
- `envocad/model/project.py` (`FORMAT_VERSION`, `migrate`)
- docs/research/02_A_opensource.md §1.2b (KiCad `rule_severities`, `m_ErcExclusions`)

### Oborová rozhodnutí
Žádná – potlačuje uživatel v konkrétním projektu. Hromadné vypnutí kódu nálezu v celém projektu **není** součástí.

### Mimo rozsah
GUI (fáze 2), změny závažností a textů nálezů, potlačení v PDF/protokolech.

### Hlavní oblast
jádro (model, knihovna, generátor, export)
```

---

### NEW-11 F7: potlačené nálezy v GUI (fáze 2)
**Štítky:** `agent-task` (`agent-ready` po NEW-10) · **Oborové rozhodnutí:** ne

```markdown
### Cíl
V okně kontroly F7 lze nález označit „Posouzeno…“ (dialog s důvodem), zobrazit/skrýt posouzené a zrušit posouzení.

### Podmínka hotovo
- akce v kontextovém menu nálezu → dialog s povinným důvodem → změna jde přes `QUndoCommand` (jedno undo)
- přepínač „Zobrazit posouzené“; posouzené řádky odlišené (šedé + důvod v tooltipu)
- offscreen GUI test: posoudit, undo, redo
- texty česky; `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/ui/` (okno nálezů F7), `envocad/ui/commands.py`; navazuje na NEW-10

### Oborová rozhodnutí
Žádná.

### Mimo rozsah
Změny datového modelu (NEW-10).

### Hlavní oblast
GUI
```

---

### NEW-12 Oteplení: hlásit „mimo rozsah metody IEC TR 60890“
**Štítky:** `agent-task` (+ `agent-question`, dokud projektant nedoplní meze) · **Oborové rozhodnutí:** **ano**

```markdown
### Cíl
Výpočet oteplení nevrací tiché číslo tam, kde metoda IEC TR 60890 neplatí; F7 a výkaz místo toho ukážou
„mimo rozsah metody – doložit jinak“.

### Podmínka hotovo
- nejdřív testy: skříň s ventilací (pokud ji model zná), proud nad mezí, rozměry/plocha mimo rozsah tabulek → nález
  F7 s kódem `thermal_out_of_scope` (varování) a výsledek označený jako neplatný
- meze jako pojmenované konstanty s komentářem „zdroj: <vydání normy>, potvrdil <kdo>, <datum>“ – **bez opisu textu normy**
- výsledek v rozsahu se nemění (stávající testy `tests/test_thermal*.py` zelené)
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/model/thermal.py` (`temperature_rise` ř. 446, `k_factor`, `c_factor` – dnes interpolace bez hlášení mezí)
- `envocad/model/checks.py` (`thermal_findings`)
- docs/research/02_B_vyrobci.md P6 (SIMARIS therm hlásí nepoužitelnost), 02_C_normy.md N3 a §4 (vydání 2014 vs. 2022)

### Oborová rozhodnutí
**Ano – musí rozhodnout člověk před převzetím:** které vydání IEC TR 60890 platí pro ENVO (kód uvádí 2014); proudová mez
(3 150 A v 2014 / 3 200 A v 2022 podle 02B/02C – neověřeno z textu normy); co dělat při ventilaci a při ploše mimo
rozsah tabulek (hlásit, nebo dělit na fiktivní skříně jako SIMARIS).

### Mimo rozsah
Změna konstant k, c (#82), výpočet s ventilací.

### Hlavní oblast
jádro (model, knihovna, generátor, export)
```

---

### NEW-13 Protokol kusového ověření: odkaz na ověření návrhu místo oteplení
**Štítky:** `agent-task` (+ `agent-question`, dokud projektant neurčí pole) · **Oborové rozhodnutí:** **ano**

```markdown
### Cíl
Po odstranění oteplení z protokolu (#80) protokol uvádí, jak bylo ověřeno navržení rozvaděče (ČSN EN 61439-1 čl. 10)
– způsob a číslo/odkaz dokladu – místo vypočtené hodnoty. Chybí-li údaj, F7 upozorní.

### Podmínka hotovo
- parametry rozvaděče (`Layout.params`) mají pole „Ověření návrhu – způsob“ (volba podle rozhodnutí) a „Doklad“ (text/odkaz)
- protokol (`export_routine_test_docx`) vypíše řádek s těmito údaji; prázdné pole → text „neuvedeno“ a nález F7 `design_verification_missing` (varování)
- pole v panelu parametrů skříně (GUI přes `QUndoCommand`)
- testy na text docx a nález F7; `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/export/docx_export.py:187` (`export_routine_test_docx`), `ROUTINE_CHECKS`
- `envocad/model/project.py` (`Layout.params`), panel parametrů skříně v `envocad/ui/layout_view.py`
- docs/research/02_C_normy.md §3 a N1; 02_B_vyrobci.md P17 (Rittal „potvrzení odvodu tepla“), zjištění 2
- závisí na #80

### Oborová rozhodnutí
**Ano:** seznam možností „způsobu“ (zkouška / výpočet / pravidla konstrukce / doklad výrobce skříně?), zda je ENVO
„původní výrobce“ nebo „výrobce rozvaděče“ ve smyslu 61439, přesný text řádku v protokolu, zda nález má být varování.

### Mimo rozsah
Šablona ENVO protokolu (čeká na dodání .docx), kusová zkouška jako strukturovaná data (02C N5).

### Hlavní oblast
jádro (model, knihovna, generátor, export)
```

---

### NEW-14 Oteplení: nezávislý test účinné chladicí plochy Ae
**Štítky:** `agent-task` (`agent-ready` po potvrzení přiřazení člověkem) · **Oborové rozhodnutí:** **ano (jen potvrzení)**

```markdown
### Cíl
`thermal.cooling_area` je ověřena testem proti nezávisle zapsaným vzorcům Ae (fakta z veřejného katalogu výrobce skříní
s odkazem), ne proti vlastnímu kódu.

### Podmínka hotovo
- `tests/test_thermal_area.py`: pro 2–3 rozměry skříně a způsoby montáže „volně stojící“, „nástěnná“, „zapuštěná“
  se `cooling_area(...)` shoduje (tolerance 1e-9) se vzorcem zapsaným v testu jako výraz v B, H, T
- u každého vzorce komentář se zdrojem (`url` katalogu Rittal [S21] z docs/research/02_B_vyrobci.md) a „potvrdil: <kdo>“
- způsoby, které kód nepodporuje (první/prostřední skříň v řadě), jsou v testu jako `xfail` s odkazem na nové issue, ne implementace
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/model/thermal.py:127` (`B_FACTORS`), `:406` (`cooling_area`)
- docs/research/02_B_vyrobci.md §7 (tabulka 7 vzorců), P5; 03_doporuceni.md kap. 0 R4 (ruční dosazení: 3 vzorce sedí)

### Oborová rozhodnutí
**Ano, malé:** potvrdit, že přiřazení vzorec ↔ způsob instalace odpovídá IEC TR 60890 (02B ho z PDF nepotvrdil jednoznačně).

### Mimo rozsah
Přidání řazení skříní v řadě, změny `B_FACTORS`.

### Hlavní oblast
testy (pokrytí existujícího kódu)
```

---

### NEW-15 Data pro DS: údaje žádosti o připojení v projektu
**Štítky:** `agent-task` (+ `agent-question` do potvrzení seznamu polí) · **Oborové rozhodnutí:** **ano (seznam polí)**

```markdown
### Cíl
Výkaz „Data pro DS“ a TZ obsahují údaje, které distributoři chtějí v žádosti a které dnes projektant dopisuje ručně:
EAN odběrného místa, katastrální území, parcelní čísla, schopnost ostrovního provozu, požadovaný rezervovaný výkon.

### Podmínka hotovo
- pole v `Project.meta` (bez změny formátu, pokud `meta` je volný slovník – ověřit; jinak `FORMAT_VERSION` + migrace)
- dialog vlastností projektu je zobrazuje (GUI přes `QUndoCommand`)
- `export/tz_data.py:dso_data` je vypisuje (prázdné = vynechat nebo „neuvedeno“ dle rozhodnutí); test na řádky výkazu
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/export/tz_data.py:66` (`dso_data` – dnes investor, místo, distributor z `fve.grid.dso`, kWp, střídače, fáze, akumulace, hlavní jištění, kabel)
- `envocad/export/reports.py:582` (`dso_report`, výkaz „Data pro DS“)
- docs/research/02_D_distributori.md §1 (vyhl. 16/2016 příl. 1 a 4), §3 (EG.D D26/D58), G1, K18

### Oborová rozhodnutí
**Ano:** potvrdit seznam polí a názvy (podle distributorů, kterým ENVO podává), zda je „ostrovní provoz“ údaj projektu,
nebo se odvozuje z topologie (EPS). Texty formulářů distributorů se do repa nekopírují.

### Mimo rozsah
Kontroly úplnosti (samostatná issue), kategorie modulu A1/A2/B, šablony formulářů distributorů.

### Hlavní oblast
jádro (model, knihovna, generátor, export)
```

---

### NEW-16 F7: úplnost podkladů pro distributora – fáze 1
**Štítky:** `agent-task` (+ `agent-question` do potvrzení) · **Oborové rozhodnutí:** **ano (závažnost, výběr pravidel)**

```markdown
### Cíl
Kontrola F7 upozorní, když v projektu chybí údaje, které všichni distributoři v ČR chtějí u JPS/žádosti a které už
model umí nést: u každého střídače výrobce, typ, AC výkon a počet fází; u akumulace kapacita a výkon; hodnota
a počet pólů hlavního jističe; u připojovacího kabelu typ, průřez a délka.

### Podmínka hotovo
- nejdřív testy (malý projekt z generátoru, pak smazaný atribut → nález): kódy `dso_inverter_data`, `dso_battery_data`,
  `dso_main_breaker`, `dso_feed_cable` (závažnost podle rozhodnutí, výchozí návrh `info`)
- žádné prahové hodnoty (10,8 kW, 11 kW…) – jen přítomnost údajů
- vygenerovaný projekt `test_generated_project_f7_clean` zůstane bez varování (nebo se test upraví jen po souhlasu v issue)
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/model/checks.py` (`check_project`, vzor `battery_findings`), `envocad/export/tz_data.py:66` (které atributy se čtou)
- docs/research/02_D_distributori.md §8 – pravidla K3, K7, K12, K14 (zdroj: vyhl. 16/2016, ČEZ PP nn, EG.D D26/D58)

### Oborová rozhodnutí
**Ano:** závažnost (info/varování), zda kontroly běží vždy, nebo jen když je vyplněn distributor (`fve.grid.dso`),
a potvrzení, že tyto 4 skupiny údajů jsou pro ENVO povinné.

### Mimo rozsah
Pravidla vyžadující nové role symbolů (rozpadové místo, vazební spínač, HDO – K2, K8–K10, K13), limity mikrozdroje (K6), seznam schválených střídačů (K16).

### Hlavní oblast
jádro (model, knihovna, generátor, export)
```

---

### NEW-17 Data pro DS: kategorie výrobního modulu A1/A2/B1… a instalovaný výkon podle distributora
**Štítky:** `agent-task` (+ `agent-question`) · **Oborové rozhodnutí:** **ano (pravidlo Pi u hybridu, hranice)**

```markdown
### Cíl
Výkaz „Data pro DS“ uvádí kategorii výrobního modulu (A1/A2/B1/B2/C/D) a instalovaný výkon spočtený podle pravidla
zvoleného distributora, aby se pro hybridní systémy nemíchaly různé definice.

### Podmínka hotovo
- čistá funkce v `envocad/model/` (bez Qt): vstup Σ kWp panelů, Σ AC výkonů střídačů, pravidlo; výstup Pi a kategorie
- hranice kategorií a pravidla jako data (např. `envocad/library/builtin/distributors/*.json` s `source_url` a `verified_on`), ne v kódu
- řádky v `dso_data`; testy na hranicích (800 W, 11 kW, 100 kW, 1 MW) a pro hybrid
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/export/tz_data.py:66` (`p_dc`, `p_ac` už počítá)
- docs/research/02_D_distributori.md §1 (ČEZ Tab. 1 kategorie), §2.2 (ČEZ: hybrid = vyšší z Σ panelů a Pi střídače), §5 (ZSD: Σ AC měničů), K4, K5, otázky 9 a 10

### Oborová rozhodnutí
**Ano:** potvrdit hranice kategorií a pravidlo Pi pro ČEZ / EG.D / PRE / ZSD, kde se databáze pravidel udržuje a kdo ji
ověřuje (`verified_on`).

### Mimo rozsah
Kontroly limitů mikrozdroje, formuláře distributorů.

### Hlavní oblast
jádro (model, knihovna, generátor, export)
```

---

### NEW-18 CI: měřit pokrytí testy (report bez prahu)
**Štítky:** `agent-task`, `agent-ready` · **Oborové rozhodnutí:** ne

```markdown
### Cíl
Z každého běhu CI je vidět pokrytí kódu po modulech, aby šlo zadávat konkrétní testovací issue (místo vágního #66).

### Podmínka hotovo
- jeden job CI (Linux, 3.12) spouští `pytest --cov=envocad --cov-report=xml --cov-report=term` (`pytest-cov` už je v dev závislostech)
- report jako artefakt; **žádný práh**, CI kvůli pokrytí nepadá
- doba běhu jobu nevzroste o víc než ~20 % (uvést v PR čísla)
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `.github/workflows/ci.yml` (dnes `pytest -q --junitxml` bez `--cov`), `pyproject.toml:15`
- docs/research/01a_inventura.md §4.4

### Oborová rozhodnutí
Žádná.

### Mimo rozsah
Nové testy, služby typu Codecov, změny agentních workflow.

### Hlavní oblast
testy (pokrytí existujícího kódu)
```

---

### NEW-19 Plugin API: verze API a registrace kontroly `add_check`
**Štítky:** `agent-task`, `agent-ready` · **Oborové rozhodnutí:** ne

```markdown
### Cíl
Plugin pozná, se kterou verzí API běží, a může přidat vlastní kontrolu F7 (dnes jen menu, šablony, importéry, výkazy, příkazy).

### Podmínka hotovo
- `envocad/plugins.py`: `API_VERSION = 1`; plugin může deklarovat `REQUIRES_API = 1`, vyšší → plugin se nenačte s českou hláškou
- `PluginContext.add_check(fn)`: `fn(project, lib) -> list[Finding]`, nálezy se přidají do `check_project` (s výjimkou v pluginu
  zachycenou a nahlášenou, ne pádem); registrace transakční jako ostatní body
- vzor v `plugins_builtin/` a test; `docs/` (popis pluginů) doplněn
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
- `envocad/plugins.py` (`PluginContext`: `add_menu_action`, `add_importer`, `add_template`, `add_command`, `add_report`)
- `envocad/model/checks.py:70` (`check_project`) – model nesmí importovat pluginy; předat seznam funkcí parametrem
- docs/research/02_A_opensource.md §1.2g (KiCad PCM `kicad_version`, pravidla deprecations)

### Oborová rozhodnutí
Žádná.

### Mimo rozsah
Sandbox, buildery generátoru a exportní formáty pluginem, verzování starších metod.

### Hlavní oblast
jádro (model, knihovna, generátor, export)
```

---

### NEW-20 Úklid: zbytky QR kódu v rámečku
**Štítky:** `agent-task`, `agent-ready` · **Oborové rozhodnutí:** ne

```markdown
### Cíl
Po odstranění QR kódu (changelog 2026-10-27) nezůstává v kódu nepoužívané pole a kreslení.

### Podmínka hotovo
- `FrameGeometry.rects` (`envocad/model/frame.py:70`) a jeho kreslení v `envocad/ui/render.py:160–165, 188–193` odstraněny,
  pokud je opravdu nikdo neplní (ověřit grepem i v `export/`)
- komentáře o QR v `settings.py`, `ui/main_window.py`, `model/multipole_geometry.py` upraveny
- výstup PDF/DXF rámečku beze změny (stávající testy `test_formaty_stran.py`, `test_doc_pages.py` zelené)
- `pytest`, `ruff check .`, `python tools/check_licensed_data.py` zelené; záznam v `changelog.d/`

### Kde v kódu / podklady
docs/research/01a_inventura.md §5.3

### Oborová rozhodnutí
Žádná (vzhled výkresu se nemění).

### Mimo rozsah
Jakékoli jiné změny rámečku a razítka.

### Hlavní oblast
jádro (model, knihovna, generátor, export)
```

---

## 7. Otázky pro projektanta (sloučené, deduplikované)

Seřazeno podle toho, kolik položek backlogu blokují. V závorce původní čísla otázek ve vstupech.

| # | Otázka | Blokuje | Zdroj |
|---|---|---|---|
| Q1 | **Čím nahradit oteplení v protokolu kusového ověření** (po #80): pole „ověření návrhu – způsob + doklad“? Jaké způsoby? Je ENVO „původní výrobce“, nebo „výrobce rozvaděče“ z typově ověřené skříně? Kdo podepisuje, které vydání 61439 uvádět? Jak dnes ENVO oteplení skutečně ověřuje (výpočet / doklad výrobce skříně / zkouška)? | NEW-13, NEW-12, #82, „později“ P2/P8/P17 | 02B O1, O6; 02C Q-3, Q-4 |
| Q2 | **Které vydání IEC TR 60890 platí** (kód uvádí 2014, rešerše zmiňuje změny 2022: mez 3 150 → 3 200 A, algebraické křivky)? Má ENVO normu a IEC 61439-1 Suppl. 2 k dispozici? Potvrdit přiřazení vzorců Ae ↔ způsob instalace | NEW-12, NEW-14, #82, P7 | 02B O4, zjištění 4; 02C §4, Q-4 |
| Q3 | **Referenční nástroje a tolerance**: které nástroje ENVO používá (Sichr, DOC, SIMARIS therm, Rittal Therm, ProClima), jaká odchylka je přijatelná (±1 K / ±5 %)? Lze uložit jejich výsledky do `tests/data` jako fakta (EULA)? Můžete otevřít ABB workbook a vybrat příklady? | #82 (referenční sada), P4 | 02B O2, O5, O9, neověřené body |
| Q4 | **Které kategorie připojení a kterým distributorům ENVO podává** (mikrozdroj / do 100 kW / ≥ 100 kW / VN; ČEZ, EG.D, PRE, ZSD)? Chcete JPS „ve formě distributora“, nebo vlastní JPS s doplněnými údaji? | NEW-15, NEW-16, NEW-17, G2–G10 | 02D otázky 1, 2, 6, 8 |
| Q5 | **Instalovaný výkon u hybridu** (ČEZ: vyšší z Σ panelů a Pi střídače; ZSD: Σ AC měničů) a hranice kategorií A1…D – potvrdit a určit, kde a kdo udržuje databázi pravidel distributorů (`verified_on`, `source_url`) | NEW-17, K4–K6 | 02D otázky 9, 10 |
| Q6 | **Kontroly pro distributora**: jen informativní, nebo blokovat export „sady pro distributora“? Jak označovat verzi pravidla (dokument + datum)? | NEW-16, K1–K22 | 02D otázka 7 |
| Q7 | **Značení prvků pro distributora**: jak ENVO značí rozpadové místo, hranici vlastnictví, vazební spínač, přijímač HDO, elektroměr / dispečerské měření? Jako role symbolů (`function_class`, atribut `role`)? Souvisí: kterou edici IEC 81346-2 a kódy tříd ENVO používá, RDS-PS (ISO 81346-10) pro FVE ano/ne, číslování podle třídy | K2, K8–K10, K13, G2; 02C N10, N11 | 02D otázka 3; 02C Q-1 |
| Q8 | **Iz**: které způsoby uložení ENVO reálně používá; zdroj tabulek (ČSN originál, nebo hodnoty výrobců kabelů s `url`); jak ukládat normové hodnoty (soubor mimo git vs. vlastní body v kódu) | #82, N18 | 02C Q-7; 01b §6 (#82) |
| Q9 | **Koeficient kabeláže a RDF** pro rozvaděče FVE ENVO (kód: kabeláž 15 %, RDF 0,8; SIMARIS doporučuje 30 % / 80 %) | výpočet oteplení, P3 | 02B O7; kap. 0 R3 |
| Q10 | **Ochrany a střídače**: zdroj hodnot nastavení ochran (PPDS P4 Tab. 7/8 jako výchozí, nebo dokument modulu)? Kdo hodnoty schvaluje? Evidovat schválené střídače a číslo certifikátu (jen odkaz)? | G6, G9, K16, K17 | 02D otázky 4, 5 |
| Q11 | **FV specifika norem**: podle kterého vydání IEC 60364-7-712 (2017 / 2025) ENVO projektuje, interní zásady jištění stringů (kdy pojistky, koeficient, gPV), vazba na 60364-8-82 (ostrov, EPS) | 02C N12, N13 | 02C Q-5, Q-6 |
| Q12 | **Data artiklů**: mají dodavatelé (OEZ, Eaton, Hager, ETI…) data v ETIM/BMEcat/ECLASS, v jaké verzi a jazyce? Je k dispozici **reálný** vzorový BMEcat? Smí se ceny a popisy z katalogů ukládat do repa? Je ENVO členem ECLASS? | #84, N6–N8, N16 | 02C Q-8, Q-9, Q-10 |
| Q13 | **Úbytek napětí**: limity pro DC stringy, AC přívod střídače, hlavní přívod | P13 (později) | 02B O3 |
| Q14 | **Legenda značek (#76)**: uvádět číslo IEC 60617? Má ENVO předplatné IEC 60617 DB? Které značky (i QET)? | #76 | 02C Q-2; 01b §6 |
| Q15 | **Ceny (#87)**: s DPH, nebo bez? Přirážka/sleva? Stačí ceník `~/.envocad/ceny.csv` z PR #63? | #87 | 01b §4, §6 |
| Q16 | **Licence QET**: je pro ENVO přijatelná klauzule „zákaz použití pro trénink ML“ ve sbírce prvků CC BY 3.0 (MIT repozitář, práce AI agentů)? | #81 (PR #108) | 02A §3.1 |
| Q17 | **Selektivita**: stačí ruční potvrzení s odkazem na výsledek v Sichr/SIMARIS curves/DOC? | P15 (později) | 02B O8 |
| Q18 | **Výměna s nástroji výrobců**: je potřeba export seznamu přístrojů s Pv (CSV pro SIMARIS therm), nebo stačí PDF? | P9 (později) | 02B O10 |

Otázky z existujících issues, které rešerše neřešila a dál platí: #89 (číslování pater, kresba, artikly), #90 (způsob podpisu),
#71 (logika značení rozvaděčů v generátoru), #77 (zobrazení poznámky), bytový dům v generátoru (ROADMAP „Odloženo“).

---

## 8. Neověřené body a mezery rešerše

| Bod | Dopad na doporučení |
|---|---|
| **Testy ani `ruff` nebyly spuštěny** (chybí `pytest`); počty testů jen z grepu | Střední: kap. 0(c) (#65) a předpoklad „NEW-3 projde“ jsou odvozené z kódu; ověřit během prvního běhu CI |
| Sloučení `feature/papir-eti-svodice` do `main`: jen textově bez konfliktů (`git merge-tree`); testy, licenční kontrola `enclosures_eti.csv` a pokrytí zadání #87 neověřeny | Střední: bod 1 backlogu musí projít CI před merge |
| Stav PR a štítků je k 22. 11. 2026 odpoledne; PR #105–#108 jsem neprocházel do detailu (jen shrnutí) | Nízký: pořadí review se může změnit |
| Přesné články a hodnoty norem (61439-1 čl. 10/11, TR 60890 meze, 60364-5-52 tabulky, 62548 faktor k Isc, 712) jsou za paywallem (02C §14) | Vysoký pro NEW-12, NEW-13, #82 – proto jsou označeny „oborové rozhodnutí: ano“ a hodnoty dodá člověk |
| Rozpor IEC/AFNOR vs. DKE o rozsahu TR 60890:2022 (02C §4) | Vysoký pro NEW-12 (Q2) |
| Struktura protokolu kusové zkoušky u nástrojů výrobců nenalezena (02B §0 bod 2) | Střední: NEW-13 se opírá jen o normu a #80 |
| Přiřazení 7 vzorců Ae ↔ obrázek (02B §7); mé ruční dosazení `B_FACTORS` je výpočet z kódu, ne běh testu | Nízký: NEW-14 vyžaduje potvrzení (Q2) |
| PPDS příloha 4 – kopie ČEZ s placeholderem rozhodnutí ERÚ; obsah VP_01/02/05 ČEZ, PN KA 502/508 PRE, formuláře EG.D D6/D36/D50, TP ZSD nečteny (02D §10) | Střední pro NEW-16/17 a „později“ G2–G7: pravidla držet jako data s `verified_on` |
| Požadavky distributorů se mění každý rok (02D úvod) | Vysoký pro udržitelnost – proto pravidla jako data, ne kód (NEW-17) |
| Licence: QET klauzule ML, pool Horizon, `qet-tb-generator`, PyAutomationML, BMEcat knihovny; EULA Rittal/Siemens/OEZ pro ukládání výsledků (02A §9, 02B §11, 02C §14) | Střední: převzetí jen jako myšlenka; ukládání referenčních výsledků (Q3) až po souhlasu |
| ETIM CZ/SK jazyková verze a třída pro FV modul neověřeny; existence Python parseru BMEcat (hledáno jednou) | Nízký: #84 a ETIM pole jsou nízká priorita |
| Issue trackery KiCad/QET/Horizon neprocházeny systematicky (02A §9 bod 1) | Nízký: návrhy stojí na dokumentaci, ne na trackerech |
| Proč chybí štítek `agent-failed` u issues s opakovaným selháním; přesná příčina selhání nočních běhů (#66 8×) | Střední pro proces: doporučení „přeformulovat #66“ je odhad z vágnosti zadání, ne z logů |
| Zda `Project.meta` je volný slovník bez validace (rozhoduje o změně formátu u NEW-15) | Nízký: issue to ukládá ověřit |
| Zda existuje nález F7 pro neznámý `component_id` (předpoklad v NEW-8) | Nízký: issue to ukládá ověřit |
| Vliv `examples/ukazka_fve.ecp` (format v1) – zda je záměrně starý kvůli testu migrace | Nízký: proto vyřazeno z NEW-4 |
