# Topologie – zpřesnění fází F1 a F2

Stav: návrh (architekt, 2026-10-20), větev `feature/topologie`. Vychází z `docs/NAVRH_TOPOLOGIE.md`, kap. 8 (rozhodnutí
Patrika). Formát projektu se **nemění** (`FORMAT_VERSION` zůstává 12): topologie žije jen ve specifikaci, v presetech
a v `Project.meta` (řetězce); nové značky jsou knihovna, ne formát.

## 1. F1 – topologie jako data + refaktoring beze změny výstupu

### 1.1 `envocad/model/topology.py` (bez Qt, obor-nezávislé – role jsou jen řetězce)
```python
TOPOLOGY_VERSION = 1
@dataclass(frozen=True)
class CableLink: cable: str = ""; cross: str = ""; length: str = ""; method: str = ""   # kabel k dalšímu článku (k síti)
@dataclass(frozen=True)
class ChainNode:
    role: str                   # rfve_dc | inverter | rfve_ac | rfve | rd | hr | re | hds | tr | rvn | grid
    ref: str = ""; desc: str = ""
    per_inverter: bool = False; sheet: bool = True    # jen rfve_dc (výchozí společný); False = jen blok (hds, grid)
    existing: bool = False; branch: bool = False      # stávající = jen dotčená část; odbočka mimo tok (RE u vn)
    macros: Mapping[str, str] = field(default_factory=dict)   # role makra → název makra
    options: Mapping[str, str] = field(default_factory=dict)  # výchozí hodnoty pro spec["chain"][role]
    link: CableLink = CableLink()
@dataclass(frozen=True)
class Topology:
    id: str; name: str; nodes: tuple[ChainNode, ...]; description: str = ""
    buildings: tuple[str, ...] = (); level: str = "nn"; source: str = "vestavěná"; path: Path | None = None
    def node(self, role: str) -> ChainNode | None: ...
    def chain_text(self) -> str: ...   # „stringy → RFVE.DC → T → RFVE.AC → HR → RE → HDS → DS“
def parse_topology(data: dict, source: str = "vlastní", path=None) -> Topology     # ValueError česky
def validate_topology(data: dict, known_roles: Collection[str] | None = None) -> list[str]
```
Načítání je v `envocad/library/topologies.py` (jako `macros.py`): `topology_dirs()` = vestavěné
`library/builtin/topologies/`, sdílené `<shared_library_dir>/topologies/`, vlastní `~/.envocad/topologies/` (stejné `id`
přepíše dřívější); `load_topologies() -> dict[str, Topology]` (neplatné → `log.warning`, vynechá); `find_topology(id)`.
**Nutno:** `library/store.py:109` vyřadit i složku `topologies` (jinak se JSON načte jako značka).

Výběr je doménový (FVE), proto **ne v modelu**, ale v `envocad/generator/spec.py`:
```python
def installed_kwp(spec: dict) -> float                     # Σ modulů × p_wp / 1000 (DC, rozhodnutí 1)
def select_topology(spec: dict, topologies: Mapping[str, Topology]) -> Topology
#  spec["topology"] zadáno → ten preset (neznámé id → ValueError); house + level vn → ValueError (jako dnes)
#  house → rd (i nad 30 kWp) | level == "vn" → vn | chain.hr.metering neprázdné → nn_hr_meter | jinak nn
#  (company i apartment; firma pod 30 kWp nn výchozí, vn volbou connection.level)
```
Zamítnuto `select_topology(spec, project)`: volba na výkonu nezávisí (RD vždy rd) a musí proběhnout před vznikem
prvního prvku (pořadí = id, `next_ref`); kWp řídí jen síťovou ochranu (`standard.grid_protection_kwp` = 30). Zamítnuty
role jako Enum v modelu (jádro by znalo FVE) – známé role předává generátor do `validate_topology`.

### 1.2 Presety `library/builtin/topologies/*.json` (+ sdílená/vlastní složka)
```jsonc
{"version": 1, "id": "rd", "name": "Rodinný dům", "buildings": ["house"], "level": "nn", "nodes": [
 {"role": "rfve", "ref": "RFVE", "desc": "rozvaděč FVE", "macros": {}},     // F4: názvy mustrů podle rolí (kap. 3)
 {"role": "inverter"},
 {"role": "rd", "ref": "RD", "desc": "domovní rozvaděč", "existing": true, "options": {"main_device": "switch"}},
 {"role": "re", "ref": "RE", "existing": true, "options": {"metering": "direct", "boundary": "hds"}},
 {"role": "hds", "ref": "HDS", "sheet": false, "options": {"char": "gG"}}, {"role": "grid", "sheet": false}]}
```
`nn` (company, apartment): rfve_dc RFVE.DC → inverter → rfve_ac RFVE.AC → hr HR (existing, `main_device` breaker) → re →
hds → grid. `nn_hr_meter`: jako nn bez re, `hr.options.metering = "direct"`. `vn`: rfve_dc → inverter → rfve_ac → hr
(přívod XT od trafa) → tr → rvn → grid + `{"role": "re", "branch": true}` (měřicí obvody, dnešní `_build_meter_board`).
Uzly před `inverter` jsou DC strana, za ním AC; `rfve` stojí před střídači (jako dnes) a je i prvním AC článkem.
Makra: `spec.macros[role]` zadané uživatelem > `node.macros[role]` (jen když makro existuje, jinak warning v logu) >
`DEFAULT_SPEC.macros` > vestavěný kód. V F1 mají presety `macros` prázdné → výstup beze změny.
`Project.meta["topology"] = "rd"` a `meta["topology_chain"] = chain_text()` (meta jsou řetězce – bez změny formátu).

### 1.3 Refaktoring `generate.py` → `envocad/generator/` (každý krok = commit, snímek beze změny)
Harness existuje: `tests/generate_snapshot.py` (`canon` = `to_dict` s normalizovanými id, vidí pořadí, polohy i
`Sheet.texts`; `model/diff.py` jen jako čitelný výpis při selhání – `diff_projects` texty listu nevidí). Rozšířit `CASES` ze 4 na 10: stávající `default_1inv`, `two_inv`, `route2_terminals`, `with_component` +
`house_2inv` (makra, rozvaděč po trase), `house_code_battery` (`macros` "", hybrid + baterie), `apartment_optimizer`
(artikl SolarEdge, 2 střídače), `vn_kiosk_nn` (smyčka, měření nn), `vn_kobky_vn_1250` (měření vn, vypínač VN) a
`split_4x8` (dělení JPS). Sloupová TS a `dc.disconnect` jsou volitelné 11. a 12. případ.

| krok | obsah | pozn. |
|---|---|---|
| 0 | **až po merge F0**: rozšířit CASES, přegenerovat snímek, test porovná všechny případy (zrušit výjimku `with_component`) | F0 i F1 mění `generate.py` – souběh = konflikty |
| 1 | `generator/context.py`: `_BUILD_LIB`, `_lib`, `_s`, `_merge`, `_num`, `_num_or`, `_int_attr`, konstanty | všechny moduly volají `context._lib()` (jedno místo pro monkeypatch) |
| 2 | `spec.py`: `DEFAULT_SPEC`, `BUILDINGS`, `HOUSE_SWITCHBOARD`, `building_kind`, `parse_*`, `load_spec`, `_apply_*_component`, `_apply_optimizer_rules`, `_fuse_in` | logger dál `"envocad.generate"` (caplog v testech) |
| 3 | `layout.py` (`_align_*`, `_route_house`), `jps.py` (`_place_jps`, `_split_jps`, `ref_ranges`, `jps_max_paper`, `JPS_*`) | přesun 1:1 |
| 4 | `boards/macro_glue.py` (`_macro_*`, `_insert_macro`, `_dc_box_from_macro`, `_ac_box_from_macros`), `boards/rfve_dc.py`, `boards/rfve_ac.py` (`_build_ac_switchboard`), `boards/rfve.py` (`_add_dc_part`), `boards/mv.py` (`connection_currents`, `station_*`, `_connection_blocks`, `_build_main_lv_board`, `_build_mv_board`, `_build_meter_board`) | přesun 1:1 |
| 5 | rozdělit `_build_project`: `pv.plan(spec) -> PvGeometry` (x/y řad), `chain.create_main_block` (blok RH/RFVE **před** stringy – pořadí!), `pv.build` (střídače, stringy, DC rozvaděče, DC/AC vodiče, baterie), `chain.build` (zbytek) | nejrizikovější: pořadí `s.elements` a `next_ref("W")` |
| 6 | `select_topology` + presety; `chain.build` iteruje `topology.nodes` přes registr `BOARD_BUILDERS`; role bez builderu (rd, hr nn, re nn, hds) se v F1 přeskočí, vn = jeden složený builder `mv` (hr+tr+rvn+re) | výstup stejný |
| 7 | `meta["topology"]`, `meta["topology_chain"]` | jediná vědomá změna snímku (jen 2 klíče meta – test to ověří) |

Rozhraní builderu (`boards/<role>.py`):
```python
@dataclass
class ChainContext: spec: dict; project: Project; sheet: Sheet; topology: Topology; kwp: float; inverters: list[Element]
                    strings: list[list[Element]]; rows: list[list[Element]]; ac_wires: list[Wire]; blocks: dict[str, Element]
@dataclass(frozen=True)
class ChainPorts: pv_side: tuple[str, ...]; grid_side: str        # např. ("X1",), "XIN"
class BoardBuilder(Protocol):   # boards/<role>.py, registr BOARD_BUILDERS: role → builder
    def block(self, ctx, node) -> Element | None; def ports(self, ctx, node) -> ChainPorts
    def build(self, ctx, node, sheet: Sheet | None) -> None
```
`envocad/generate.py` zůstane tenký: docstring specifikace, `main()` (CLI `python -m envocad.generate`) a re-export
`build_project, DEFAULT_SPEC, AC_MAX_INVERTERS_BUS, connection_currents, parse_number, parse_strings, load_spec,
JPS_AC_SHEET_NAME, ref_ranges, building_kind, _macro_ref, _macro_values, _apply_optimizer_component` (importují je
testy, `ui/main_window.py`, `ui/dialogs.py`). **Upravit testy**: `test_wizard_catalog.py:463` a
`test_optimizer_review.py:271` patchují `generate._lib` → patchovat `envocad.generator.context._lib`;
`test_exports_audit3.py:550` čte `generate._BUILD_LIB` (re-export globálu je kopie, test by nic neověřil) →
`envocad.generator.context._BUILD_LIB`.

## 2. F2 – nové články (pořadí = pořadí implementace)
Bloky za prvním AC článkem zleva doprava, zrcadlené (přívod vpravo, k DS) jako dnes RHN; zarovnání zobecní
`_align_connection` (`align(next, pv_port, port(prev, grid_side))`). U RD vede XOUT RFVE (`_route_house`) na RD.

1. **Označení z presetů** (RFVE.DC/RFVE.AC/HR místo RDCn/RH/RHN; v F1 se brala legacy označení). `switchboard` a
   `connection.main_board/meter_board` zůstávají jako přepis `chain.<role>.ref`. Vědomá změna snímku, ~45 testů s „RH“.
   Nemergnutý `537cdd8` (RH → RFVE.AC) převzít, ne duplikovat.
2. **RFVE_DC společný** (výchozí; `chain.rfve_dc.per_inverter: true` = dnešní stav): DC část jako u RFVE (`k0`, `i.j`),
   rozvaděče po trase dál na střídač, při dělení JPS zůstává na listu AC.
3. **HDS** – nová značka `fve.hds` (symbol-author): obdélník s pojistkou, porty `1` W (k odběrateli), `2` E (k DS),
   atributy `ref` („HDS“), `desc`, `in_`, `char` („gG“), `poles`; do `NO_ROTATE_PREFIXES` a mezi jisticí přístroje
   selektivity. Vodič HDS → DS bez kabelu. Zamítnuto: `fve.grid` s `kind=HDS` (rozbije kořen DS, pojistky nemají kam),
   `fve.switchboard` bez listu (nález `no_sheet`).
4. **RE nn** (`boards/meter_board.py`): XIN → HJ vždy (`fve.breaker_mcb` ≤ 125 A, jinak `mccb`) → `direct` (`fve.meter`
   v sérii) | `indirect` (`fve.ct`, převod `ct_ratio` / z In, elektroměr přes XMI/XMU v RE) → vypínač instalace vždy
   (`sb.main_switch`) → XOUT. Volí projektant, výchozí z presetu. **Hranice vlastnictví** `chain.re.boundary` = `hds` |
   `re_main` (svorky HJ) | `re_meter` (za elektroměrem): atribut `boundary="1"` na prvku + volný text listu
   (`Sheet.texts`) „hranice vlastnictví DS / odběratel“ v blokovém schématu. Zamítnuto: čerchovaná značka (primitiva
   neumí typ čáry, JPS ji nepřevezme). **Riziko:** `single_line._graph` vyjme vodiče elektroměru jako měřicí obvody →
   elektroměr v sérii přeruší strom; `fve.meter` s výkonovými žílami na obou portech = sériový uzel.
5. **RD / HR stávající** (`boards/house_board.py`, jedna implementace): `XIN` (u vn `XT`) → `main_device` `switch` (RD) |
   `breaker` (HR) s `main_in` → přípojnice → vývod FVE `X1` (`fve_device` `breaker` | `fuse_disconnect`, `fve_in`) a
   „stávající rozvody“ `X2` → `fve.load`. **Do 80 A vždy jistič:** pojistka s `fve_in` ≤ 80 → `ValueError` (průvodce
   nedovolí). `fve_in` prázdné → nejbližší jistič ≥ Σ In střídačů; stávající `main_in` neznámé → prázdné + `breaker_no_in` (průvodce ho vyžaduje).
   Měření v HR (nn_hr_meter) = stejná funkce jako v RE.
6. **Kabely mezi články** z `chain.<role>.cable/cross/length/method` (kabel článku směrem k síti; RFVE.AC → RD/HR = dnešní
   `ac.grid_*`). Prázdný `cross` u nového úseku → nový `calc.min_cross(in_a, method)` nad `calc.ampacity`; stávající
   úsek bez údajů = vodič bez označení (`no_cable` je jen INFO).
7. **F7 a selektivita v řetězci** (hned po 3–6). Obecně, bez znalosti topologie: `calc.check_selectivity_tree(project,
   lib)` nad `single_line.build_tree` (od DS přes listy), jen dvojice přes hranici listu (uvnitř listu dál
   `calc_selectivity`). Generátor přístroje řetězce označí atributem `chain` (`inv`, `rfve_main`, `fve_out`, `main`,
   `meter_main`, `inst_switch`). Kódy: `chain_selectivity` (W: nadřazený In menší / poměr < 1,6 / odpínač pod In
   jištění), chybějící In = kód F0 `breaker_no_in` (ERROR, `protection_findings` – rozšířit o `fve.hds` v JPS), `fve_out_fuse_le80` (W),
   `grid_protection_missing` (W: `p_installed_kwp` > limit bez `fve.grid_protection`), `eps_unconnected` (W: hybrid
   s baterií, BACKUP nevede na přepínač). Nesplnitelné hodnoty se nenahrazují – zůstanou a vznikne nález.
8. **Síťová ochrana nad 30 kWp** (RFVE.AC, u RD RFVE): nová značka `fve.grid_protection` (port `U`, atribut `acts_on`);
   v jádru podmíněné prvky `when: grid_protection` (auto: „1“ když `kwp` > `standard.grid_protection_kwp`; přepis
   `chain.rfve_ac.grid_protection` `auto|1|0`). Vestavěný kód: relé měří z přípojnice (port 6), `acts_on` = hlavní
   vypínač. Zamítnuta samostatná role makra – vazební spínač leží v hlavní cestě jádra (bus → Q → vazba → XOUT).
9. **EPS a přepínač sítí** (RFVE): nová značka `fve.changeover_switch` (I-0-II, porty `1` síť, `2` záloha, `3` výstup;
   `ref` Q, `in_`, `poles`, `kind` ruční/ATS) – **ano, hned**, mustr ji potřebuje. Role makra `ac_eps` na hybridní
   střídač; vodič JPS `T{i}.BACKUP` (jen má-li svorku, `inverter_io`) → `RFVE.XE{i}`, výstup `XB{i}` → `fve.load`
   „zálohované okruhy“. Baterie zůstává pod střídačem.
10. **RFVE_AC jinde**: `inverters[].ac_group` ("" = hlavní); skupina = vlastní RFVE.AC{n} a vlastní vývod FVE v RD/HR
    (`X1`, `X3`…; `X2` = spotřeba). Bez skupin jeden společný.

**`chain.*`** (volitelné; spec > `node.options` > kód): `rfve_dc {per_inverter, ref, desc}`, `rfve_ac|rfve {ref, desc,
grid_protection, cable…}`, `rd|hr {ref, main_device, main_in, fve_device, fve_in, metering, ct_ratio, cable, cross,
length, method}`, `re {ref, main_in, metering, ct_ratio, switch_in, boundary, cable…}`, `hds {ref, in_, char}`.
**Průvodce (F5):** „Objekt a připojení“ – druh objektu, nn/vn (u RD zakázáno), preset (filtr `buildings`), měření RE/HR,
náhled `chain_text()`, RFVE_DC na střídač (2+ střídače), skupiny střídačů. „Stávající rozvaděče“ – hlavní přístroj a In
RD/HR, vývod FVE (pojistka ≤ 80 A nedostupná), HJ RE, přímé/nepřímé + MTP, hranice vlastnictví, In HDS.

## 3. Specifikace pro autora mustru (Patrik)
Makro = JSON v2 (`LIBRARY_FORMAT.md`, „Formát makra“), klíč `role`, uložit do sdílené knihovny `macros/`. Generátor
napojuje **jen přes označení přívodů/vývodů a sdílené prvky** – ty musí sedět přesně, zbytek je volný.

| role | kolikrát | povinné kotvy | proměnné (auto = dodá generátor) |
|---|---|---|---|
| `dc_tech` | na string | `sb.feed_in` `X{k}`, `sb.feed_out` `X{nk}`, `XPE` (`shared: "1"`) | auto `k, n, nk, i, j, string, inverter`; `fuse_in`, `spd` (`disc_in`) |
| `ac_feed` | na střídač | `sb.feed_in` `X{k}`; vodič na sdílenou `sb.busbar` ref `1` port `T{k}` | auto `k, i, inverter`; `breaker_in`, `main_in` |
| `ac_core` | 1× | sdílená `sb.busbar` `1` (porty 1 SPD, 3 hlavní vypínač, 4 PE, 6 síťová ochrana), `sb.feed_out` `XOUT`, `XPE` (`shared`) | `main_in`, `spd`; auto `grid_protection` (podmínky `when`) |
| `ac_eps` | na hybridní střídač | `sb.feed_in` `XE{i}`, `sb.feed_out` `XB{i}`, sběrnice `1` port 5 (síťová strana přepínače) | auto `i, inverter`; `eps_in` |

RFVE (RD) = `dc_tech` + `ac_feed` + `ac_core` (+ `ac_eps`) s vlastními názvy („RFVE – DC string“…), RFVE.AC =
`ac_feed` + `ac_core`, RFVE.DC = `dc_tech`. V RFVE platí číslování: AC přívody X1…Xn, DC přívody od X{k0+1}
(k0 = za AC částí), vývody X{nk}. Porty na mřížce 2,5 mm, `ref` u všech přístrojů, In jako čísla.

## 4. Testy, rizika, YAGNI
**Testy F1:** presety platné, neznámá role / vyšší verze, přepis id ze sdílené/vlastní složky, store nenačte
`topologies/`, tabulka `select_topology`, snímek, meta klíče. **F2:** na topologii (rd, nn, nn_hr_meter, vn ×3) řetězec
bloků od DS, listy, `sync_feed_links`, **F7 bez chyb a varování**, JPS; RE direct/indirect, hranice, pojistka ≤ 80 A →
`ValueError`, nesplnitelná selektivita → nález, 30,0 / 30,1 kWp, EPS, `per_inverter`, `ac_group`, staré specifikace.
**Rizika:** souběh s F0; pořadí vzniku prvků (krok 5); monkeypatch/globály; `537cdd8`; elektroměr v sérii v
`single_line`; vícepól třívývodového přepínače; společný RFVE_DC mění rozložení a dělení JPS firem.
**YAGNI:** editor topologií v GUI, stromové topologie mimo `ac_group`, makra pro RD/HR/RE (jen kód), F3, automatická
volba měření, limity DS, značka hranice vlastnictví, migrace verzí presetů.
