# Návrh: generátor podle topologie připojení (RD / firma nn / firma vn)

Stav: **návrh k implementaci** (2026-10-20). Zadání: Patrik. Navazuje na `envocad/generate.py` (stav `d640b7d`).
Šablony rozvaděčů **RFVE** (rodinný dům) a **RFVE_AC** připraví Patrik jako makra – generátor je jen skládá.

## 1. Zadání – tři řetězce

| Topologie | Řetězec (tok energie od FV k síti) |
|---|---|
| **RD** – rodinný dům | stringy → **RFVE** (DC část) → střídač → **RFVE** (AC část) → **domovní rozvaděč (RD)** → **elektroměrový rozvaděč (RE)** → **HDS** |
| **NN** – firmy a FVE nad 30 kWp, připojení na nn | stringy → **RFVE_DC** → střídač → **RFVE_AC** → **HR** → **RE** → **HDS** (varianta: měření přímo v HR, bez RE) |
| **VN** – firmy a FVE nad 30 kWp, připojení na vn | stringy → **RFVE_DC** → střídač → **RFVE_AC** → **HR** → **trafo** → **rozvaděč VN** |

Volitelně ve všech: DC rozvaděče po trase (jen SPD) mezi stringy a RFVE / RFVE_DC – zůstávají jako dnes.

## 2. Co už je hotové (nepředělávat)

- `building` = `company | house | apartment`, u `house` sloučený rozvaděč RFVE (DC + AC) – `combined`, `_add_dc_part`,
  `_route_house` (AC vodiče se vrací zpět do bloku RFVE).
- Přípojka VN: `_connection_blocks` → RFVE.AC → HR (hlavní rozvaděč nn) → TR → RVN / sloup → DS, RE s měřicími
  obvody (měření nn/vn), `connection_currents` ze Sn.
- Rozvaděče z maker: role `dc_tech`, `dc_route`, `ac_feed`, `ac_core` (`_dc_box_from_macro`, `_ac_box_from_macros`),
  sady hodnot maker, `resolve_values`.
- Hlavní list = **blokové schéma**, jednopólové schéma se odvozuje (`model/single_line.py`) – nové bloky se v JPS
  objeví samy, pokud mají list rozvaděče s přívody/vývody.

**Chybí:** domovní rozvaděč / HR jako článek řetězce u připojení na nn, RE na nn (přímé / nepřímé měření), HDS,
měření v HR, pojmenování RFVE_DC / RFVE_AC, volba topologie podle výkonu, a celé je to dnes větvení v kódu
(`combined`, `chain`), ne data.

## 3. Návrh – topologie jako data

### 3.1 Model (`envocad/model/topology.py`, bez Qt)

```python
@dataclass
class ChainNode:
    role: str            # "rfve_dc" | "inverter" | "rfve_ac" | "rfve" | "rd" | "hr" | "re" | "hds" | "tr" | "rvn" | "grid"
    ref: str             # RFVE_DC, RFVE_AC, RD, HR, RE, HDS…  ({i} = číslo střídače u rozvaděčů na střídač)
    desc: str
    per_inverter: bool = False   # RFVE_DC1…n (jeden na střídač) vs. jeden společný
    sheet: bool = True           # má list rozvaděče (False = jen blok, např. stávající RD bez úprav)
    existing: bool = False       # stávající rozvaděč – kreslí se jen dotčená část (přívod, HJ, vývod FVE, spotřeba)
    macros: dict[str, str] = field(default_factory=dict)   # role maker → název makra (prázdné = vestavěný kód)
    link: dict = field(default_factory=dict)  # kabel k dalšímu článku: cable, cross, length, method

@dataclass
class Topology:
    id: str              # "rd" | "nn" | "nn_hr_meter" | "vn"
    name: str
    nodes: list[ChainNode]
```

Presety jako JSON v `envocad/library/builtin/topologies/*.json` (+ sdílená knihovna `topologies/`, stejně jako makra) –
projektant si může topologii upravit nebo přidat (např. „RD s baterií a záložním rozvaděčem“) bez zásahu do kódu.

Příklad `rd.json`:

```json
{"id": "rd", "name": "Rodinný dům",
 "nodes": [
  {"role": "rfve", "ref": "RFVE", "desc": "rozvaděč FVE",
   "macros": {"dc_string": "RFVE – DC string", "ac_feed": "RFVE – AC přívod střídače", "core": "RFVE – jádro"}},
  {"role": "inverter"},
  {"role": "rd", "ref": "RD", "desc": "domovní rozvaděč", "existing": true,
   "link": {"cable": "CYKY-J 5x6", "cross": 6, "length": 10, "method": "B1"}},
  {"role": "re", "ref": "RE", "desc": "elektroměrový rozvaděč", "existing": true},
  {"role": "hds", "ref": "HDS", "desc": "hlavní domovní skříň"}]}
```

### 3.2 Specifikace

```jsonc
"topology": "",            // "" = automaticky (3.3), jinak id presetu: "rd" | "nn" | "nn_hr_meter" | "vn"
"chain": {                 // přepisy po článcích (podle role), vše volitelné
  "rd":  {"main_in": 25, "fve_in": 16, "existing": true},
  "hr":  {"ref": "HR", "main_in": 160, "fve_in": 63, "metering": false},
  "re":  {"metering": "direct", "main_in": 63},     // direct (přímé) | indirect (MTP)
  "hds": {"fuse_in": 80, "fuse_type": "gG"}
}
```

`building` a `connection.level` zůstávají – slouží k automatické volbě. `switchboard` (RH) se mapuje na článek
`rfve_ac` (zpětná kompatibilita starých specifikací a testů).

### 3.3 Automatická volba topologie

```
house a P ≤ 30 kWp           → rd
connection.level == "vn"     → vn
jinak                        → nn   (chain.hr.metering == true → nn_hr_meter)
```

Hranice 30 kWp jako konstanta ve standardu (`settings.standard.rd_limit_kwp`), viz otevřené otázky 7.1.
Průvodce ukáže zvolený řetězec jako náhled („stringy → RFVE_DC → T1 → RFVE_AC → HR → RE → HDS“) a dovolí ho změnit.

### 3.4 Sestavení (refaktoring `generate.py`)

`generate.py` má 1 300 řádků a topologii řeší větvením. Navrhuji balíček:

```
envocad/generator/
  __init__.py      build_project(spec) – veřejné API beze změny, CLI python -m envocad.generate zůstává (re-export)
  spec.py          DEFAULT_SPEC, _merge, parse_*, building_kind, výběr topologie
  pv.py            stringy, střídače, baterie, MPPT (dnešní 1. polovina _build_project)
  chain.py         průchod topologií: blok na článek, kabely mezi články, rozmístění zleva doprava
  boards/          jeden modul na roli: rfve_dc.py, rfve_ac.py, rfve.py, house_board.py (RD/HR),
                   meter_board.py (RE nn i vn), hds.py, mv.py (RHN/TR/RVN – přesun dnešního kódu)
  layout.py        _align_* funkce, _align_bends, fit_sheet_to_content
```

Každý `boards/*.py` má stejné rozhraní:

```python
def build(project, sheet, node: ChainNode, ctx: ChainContext) -> None   # ctx: invs, stringy, In předchozího článku, spec
def ports(node, ctx) -> PortsSpec                                        # přívody/vývody pro blok (X1…, XOUT, XPE)
```

`chain.py` projde `topology.nodes`, pro každý článek vytvoří blok `fve.switchboard` (nebo `fve.grid` / HDS),
list přes `boards.<role>.build` (makra, jinak kód) a kabel k dalšímu článku podle `link` / `chain.<role>`.
Topologii zapíše do `project.meta["topology"]`, aby ji šlo zobrazit a zkontrolovat (F7).

### 3.5 Nové / upravené rozvaděče

| Role | Obsah listu (výchozí kód; projektant může přebít makrem) |
|---|---|
| `rfve_dc` | dnešní „DC rozvaděč u technologie“ přejmenovaný: na string pojistkový odpínač + SPD, vývody ke střídači; `per_inverter` → RFVE_DC1…n |
| `rfve_ac` | dnešní AC rozvaděč (RH): přívody od střídačů, jističe, sběrnice/svorky, SPD, hlavní vypínač, vývod XOUT, XPE → HOP. **Mustr RFVE_AC od Patrika** → makra `ac_feed` + `ac_core` |
| `rfve` (RD) | sloučený rozvaděč: DC část + AC část na jednom listu (dnešní `combined`). **Mustr RFVE od Patrika** → makra `dc_string`, `ac_feed`, `core` |
| `rd` / `hr` | stávající rozvaděč objektu, kreslí se jen dotčená část: přívod (od RE/HDS nebo z trafa), hlavní jistič / vypínač, **vývod FVE** (jistič `fve_in`, případně SPD), vývod „stávající rozvody objektu“ (`fve.load`). Varianta `metering: true` = fakturační elektroměr v HR (přímé / MTP podle In) |
| `re` (nn) | elektroměrový rozvaděč: hlavní jistič před elektroměrem (`main_in`), elektroměr přímý (do In ≤ limit DS) nebo nepřímý (MTP + svorkovnice), vývod do objektu. Dnešní `_build_meter_board` (měřicí obvody pro vn) zůstává jako varianta `re` u topologie vn |
| `hds` | blok HDS (přípojková skříň) s pojistkami `fuse_in` – jen blok, bez listu; nová značka `fve.hds` nebo `fve.grid` s atributem `kind=HDS` |
| `tr`, `rvn` | beze změny (přesun `_connection_blocks`, `_build_main_lv_board`→`hr` s přívodem z trafa, `_build_mv_board`) |

Pozn. k VN: dnešní RHN = HR v nové terminologii; ref se vezme z topologie (`HR`), `connection.main_board.ref`
zůstane jako přepis.

### 3.6 Rozvaděč RFVE u rodinného domu – dvě podoby jednoho rozvaděče

Zadání RD kreslí RFVE dvakrát (před a za střídačem). Dnes je to jeden blok a AC vodiče se do něj vracejí
(`_route_house`) – na velkém počtu střídačů je to nepřehledné. Dvě možnosti:

- **A (doporučuji):** v blokovém schématu dva bloky se stejným označením RFVE – „RFVE (DC část)“ a „RFVE (AC část)“,
  oba ukazují na **jeden list** rozvaděče; blok ukáže jen porty své části (atribut přívodu/vývodu `part = dc|ac`).
  Vodiče vedou zleva doprava bez návratu, jako u firmy. Vyžaduje: `Sheet` s více bloky (`Element.attrs["sheet_of"]`
  = id hlavního bloku), filtr portů v `switchboard_symbol`, kontrola duplicitního označení výjimku pro tyto dvojice,
  jednopólové schéma (`single_line.py`) obě části spojí přes list. **Zvýšit `FORMAT_VERSION` + migrace** (staré
  projekty: jeden blok bez `sheet_of`).
- **B:** ponechat jeden blok a dnešní `_route_house`. Bez změny formátu, ale přetrvá zpětné vedení AC vodičů.

### 3.7 Kabely a jištění v řetězci (návaznost)

Generátor dopočítá a F7 zkontroluje selektivitu podél řetězce:
`jistič střídače (RFVE_AC) ≤ hlavní vypínač RFVE_AC ≤ vývod FVE v RD/HR < hlavní jistič RD/HR ≤ HJ před elektroměrem (RE)
< pojistky HDS` (u vn: `… < hlavní jistič HR` podle Sn – dnešní `connection_currents`). Průřezy kabelů mezi články
podle In a uložení (`calc` už umí Iz a úbytky). Hodnoty, které nejdou splnit, se **nesmí tiše nahradit** – prázdná
hodnota + nález F7 (viz review, bod 1 a 5).

### 3.8 Průvodce (GUI)

Krok „Objekt a připojení“: druh objektu, úroveň připojení (nn / vn), měření (RE / v HR) → náhled řetězce,
volba presetu. Krok „Stávající rozvaděče“: hlavní jistič RD/HR, In vývodu FVE, In HDS, přímé/nepřímé měření.
Zbytek beze změny.

## 4. Fáze (pro předání agentům)

| Fáze | Obsah | Agent | Ověření |
|---|---|---|---|
| **F0** | Opravy z review generátoru (kap. 6) + test „výstup generátoru bez varování F7“ pro firma / RD / vn / bez maker | core-dev | `pytest tests/test_generate.py` |
| **F1** | `model/topology.py`, presety JSON, výběr topologie, `meta["topology"]`; refaktoring do `envocad/generator/` **beze změny výstupu** (stávající testy zelené, porovnání výstupu před/po na 5 specifikacích – `model/diff.py`) | architekt → core-dev | testy + diff = prázdný |
| **F2** | Nové články `rd`/`hr` (stávající rozvaděč, vývod FVE, měření v HR), `re` nn (přímé/nepřímé), `hds`; kabely mezi články; selektivita v řetězci + F7 | core-dev, symbol-author (HDS) | nové testy na každou topologii, F7 čisté |
| **F3** | RFVE dvě podoby (varianta A, změna formátu) – nebo ponechat B | architekt → core-dev → reviewer | migrace, test otevření starého projektu |
| **F4** | Makra z mustrů RFVE a RFVE_AC (Patrik) napojit na role, sady hodnot | Patrik + core-dev | vygenerovaný projekt = mustr |
| **F5** | Průvodce (krok Objekt a připojení, náhled řetězce), dokumentace `MANUAL.md`, `LIBRARY_FORMAT.md` (formát topologie) | gui-dev, docs | GUI smoke test |

F1 a F0 jdou paralelně. F2 až po F1. F4 může začít hned, jak budou mustry (role maker jsou dané v 3.5).

## 5. Testy

- Na každou topologii (rd, nn, nn_hr_meter, vn kiosk / kobky / sloup): očekávaný řetězec bloků v blokovém schématu,
  listy rozvaděčů, vazby přívodů (`sync_feed_links`), **F7 bez chyb a varování**, JPS odvozené bez výjimky.
- Zpětná kompatibilita: staré specifikace (`building`, `connection.level`, `switchboard`) dávají platný projekt.
- Makra: vlastní makro role přebije vestavěné (už existuje – rozšířit na nové role).

## 6. Opravy z review generátoru (F0)

Z revize `75c228f..d640b7d` (testy 821/821 zelené, ruff čistý, pravidla architektury dodržena). Týká se generátoru:

**Stav: body 1–9 opraveny (F0, 2026-10-20)** – viz CHANGELOG; test `tests/test_generate.py::test_generated_project_f7_clean`
(firma, RD, bytový dům, vn kiosk / kobky / sloup, bez maker). Známé varování F7 mimo F0: vícepól RE u přípojky VN
(`xfail`, ROADMAP „Chyby k řešení“).

1. `generate.py:583` + `calc.py:356–369` – když žádná pojistka gPV nevyhoví (Isc 18,5 A, nebo max. jištění modulu
   10 A), zapíše se tiše 15 A. → prázdné In + chyba F7; doplnit řadu 30/32 A, EFH 10 max. 25 A.
2. `generate.py:300` – `int(t.attrs["mppt"])` spadne na „2.0“ / „2,0“. → `_int_attr`.
3. `generate.py:470–472` – RD bez makra: všechny stringy dostanou In pojistek prvního střídače. → In po skupinách.
4. `generate.py:810, 817` – vývod FVE v hlavním rozvaděči nn podle `ac.main_in`, ne podle Sn (50 kVA → vývod 125 A
   nad hlavním jističem 100 A). → omezit a hlásit nesplnitelnou selektivitu.
5. `generate.py:675` – `u_vn` „22000 V“ se bere jako 22 MV. → parsovat jednotku.
6. `generate.py:182, 192–194` – RD bez `tech_box` projde s přípojkou VN a má název „RFVE (DC + AC)“ bez DC části.
7. `generate.py:580–581` – SolarEdge se pozná jen podle artiklu/optimizéru, ne podle `type` střídače
   (standard ENVO: pojistka stringu SolarEdge 25 A); katalog nemá žádný střídač SolarEdge.
8. `generate.py:359` – kabel baterie: typ z `dc.cable` (1x6), průřez 25. → `battery.cable/cross/length`.
9. Cesta bez maker (`macros=""`) dává varování F7 (překryvy textů v DC rozvaděčích, SPD na `x+12.5`
   v `templates.py:249`).

Mimo generátor (zařadit do `ROADMAP.md`): revize nevidí `Sheet.texts` (`diff.py:230`); hlídací test zápisů mimo undo
nezná nová pole (`tests/test_no_model_writes_in_ui.py`); model čte uživatelská nastavení (`multipole.py:648`);
duplicitní `_snap`/`_ceil_grid`, nepoužitý `elide_text`, dynamické atributy `Node` v `single_line.py`.

## 7. Otevřené otázky (rozhodne Patrik)

1. **Hranice 30 kWp** – instalovaný výkon DC (kWp), nebo AC výkon střídačů? Co RD nad 30 kWp a firma pod 30 kWp –
   RD řetězec, nebo NN řetězec?
2. **Bytový dům** (`apartment`) – který řetězec? (RD / NN, nebo vlastní: RFVE → společný rozvaděč → RE…)
3. **RFVE_DC u více střídačů** – jeden společný, nebo jeden na střídač (RFVE_DC1, RFVE_DC2)? Totéž RFVE_AC u více
   střídačů na různých místech.
4. **Domovní rozvaděč / HR** – kreslit jako stávající (jen dotčená část), nebo celý nový? Kde je vývod FVE –
   jistič, nebo pojistkový odpínač?
5. **RE na nn** – hranice přímého měření (podle DS: ČEZ / EG.D / PRE)? Hlavní jistič před elektroměrem kreslit vždy?
6. **Měření v HR** – kdy (výkon, požadavek DS) a jaké (přímé / nepřímé)?
7. **RFVE u RD** – varianta A (dva bloky jednoho rozvaděče, změna formátu), nebo B (jako dnes)?
8. **Baterie / záložní okruhy (backup)** – patří do řetězce (záložní rozvaděč za hybridním střídačem)? Ve 1. verzi
   navrhuji mimo řetězec jako dnes.

## 8. Rozhodnutí (Patrik, 2026-10-20)

1. **Hranice 30 kWp** = instalovaný výkon DC (kWp). RD nad 30 kWp má stejný řetězec (rd). Firma pod 30 kWp výchozí
   NN řetězec, ale volba NN / VN zůstává projektantovi. Nad 30 kWp přibývá požadavek na **síťovou ochranu** – je
   v RFVE_AC (u RD v RFVE).
2. **Bytový dům** → NN řetězec.
3. **RFVE_AC** vždy společný, pokud střídače nejsou na jiném místě. **RFVE_DC** většinou společný, může být vlastní
   na střídač (volba ve specifikaci / průvodci; výchozí společný).
4. **RD / HR** kreslit jako stávající (jen dotčená část). Vývod FVE jistič nebo pojistkový odpínač – určí projektant;
   **do 80 A vždy jistič**.
5. **RE na nn**: přímé / nepřímé měření a hranici vlastnictví určí projektant (podle stávající situace). **Hlavní
   jistič před elektroměrem kreslit vždy, vypínač instalace za elektroměrem také.**
6. **Měření v HR** určí projektant podle stávající situace (volba, žádná automatika).
7. **RFVE u RD = jeden blok** (varianta B, bez změny formátu – F3 odpadá).
8. **Baterie a záloha**: baterie je vždy součástí schématu. V RFVE je **přepínač sítí** (mustr dodá Patrik), **EPS
   vývod střídače vede vždy na něj**; zálohované okruhy za přepínačem zakreslí projektant.

Mustry RFVE a RFVE_AC (makra) připraví Patrik; do té doby generátor používá vestavěný kód a role maker jsou
připravené (F4 po dodání mustrů).
9. **Označení rozvaděčů** (doplněno): všude **RFVE.DC** (DC rozvaděč u technologie, dřív RDC u střídače) a
   **RFVE.AC** (AC rozvaděč FVE, dřív RH); u rodinného domu jeden rozvaděč **RFVE**. Dnešní „RH“ je chyba. Rozvaděče
   po trase zůstávají RDCn. Hlavní rozvaděč nn u vn = HR (dřív RHN). Základ: commit 537cdd8 (RH → RFVE.AC).
   **Hotovo v generátoru** (10/2026): `generator.context.AC_SWITCHBOARD_REF`, `DC_TECH_BOX_REF`,
   `MAIN_LV_BOARD_REF`, `generator.boards.rfve_dc.dc_box_ref`; od F2 z presetu (`node.ref`). DC rozvaděč u technologie
   je od F2 společný `RFVE.DC`; s `chain.rfve_dc.per_inverter` na střídač: jediný = `RFVE.DC`, víc = `RFVE.DC1`, `RFVE.DC2`…
   podle pořadí střídače ve specifikaci (ne podle čísla v `ref` střídače); rozvaděče po trase `RDC1…n` souvisle (číslo
   RDC rozvaděče u technologie neberou). Návrh výše píše `RFVE_DC` / `RFVE_AC` – platí `RFVE.DC` / `RFVE.AC`
   (kód umístění s tečkou uvnitř, `designation.CODE_RE`). Společný RFVE.DC (bod 3) je hotový (F2, krok 2).
10. **Přepínač sítí a EPS vývod** jen u rodinného domu (RFVE); u firmy a bytového domu se nekreslí. **Hotovo** (F2,
    krok 9: `generator/boards/eps.py`, značka `fve.changeover_switch`). Síťová ochrana nad 30 kWp (bod 1) – F2 krok 8,
    skupiny RFVE.AC na jiném místě (bod 3) – F2 krok 10.
11. **Skupiny střídačů (`ac_group`)** (2026-10-21): síťová ochrana v každém RFVE.AC zvlášť. Rodinné domy se na vn
    nepřipojují (beze změny – chyba). Skupiny zatím jen u nn s HR; RD a vn hlásí srozumitelnou chybu (rozšíření podle
    potřeby).
12. **Rozsah generátoru** (2026-10-21, Patrik): generátor dělá hlavně **blokové schéma a DC rozvaděče**. AC rozvaděče
    připraví Patrik (mustry). Proto: RD / HR / RE / HDS jen jako **bloky bez listů** (žádné chyby F7 o chybějícím In
    stávajících přístrojů); list RFVE.AC (a AC část RFVE u RD) jen když existuje mustr (makra rolí `ac_feed`/`ac_core`/
    `ac_eps` ve sdílené / vlastní knihovně), jinak blok bez listu (u RD list RFVE jen s DC částí + přívody/vývody).
    Vestavěný kód AC listů zůstává jako volba (`chain.<role>.builtin: true` / standard) pro testy a nouzi.
    **Hotovo** (2026-10-21): bloky bez listu nesou porty v atributech `ports_in` / `ports_out` (formát projektu v15,
    migrace v14 → v15 bez změny dat) a údaje článku v popisku (`main`, `fve_out`, `metering`, `inv_protect`,
    `grid_protection`, jištění portů `protect` pro kontrolu kabelů); mustr = makra rolí `ac_feed` + `ac_core` ve
    sdílené / vlastní knihovně (`generator/spec.pattern_macro`); RD: list RFVE s DC částí a kotvami AC části
    (`anchor="1"`); standard `ac_builtin`. F7 jen nad nakreslenými přístroji (selektivita přes blok bez listu se
    nehodnotí, HDS bez In jen INFO, síťová ochrana jako požadavek bloku, EPS do RFVE bez AC části INFO). Přípojka VN:
    listy HR / RVN / RE trafostanice zůstávají (otevřená otázka).
