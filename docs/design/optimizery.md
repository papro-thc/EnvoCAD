# Návrh: optimizéry a režimy stringů FV

Návrh agenta `architekt` (10/2026), schválil orchestrátor. Navazuje na `katalog_fv.md`.
Podnět uživatele: „hlídá to i napětí stringu na MPPT? U SolarEdge a Huawei to je jinak.“
**Formát projektu se nemění (v9)** – nová kategorie artiklů, nové sloupce CSV, nepovinné atributy a klíče specifikace.

## 0. Výchozí stav
- `spec["optimizer"] = {"type", "per_module"}` → string dostane `optimizer` (text) a `n_optimizers = round(n·per)`;
  BOM a TZ je počítají, `calc` je ignoruje. Optimizéry nejsou v katalogu, střídač nemá režim stringu.
- `calc.string_issues` vždy klasicky: Uoc·n proti Umax, okno MPPT, proud na MPPT. U SolarEdge (pevné napětí) proto
  hlásí nesmysly, u Huawei/Tigo s optimizéry chybí kontrola vstupu optimizéru. Paralelní stringy na MPPT se
  na stejnou délku/modul nekontrolují (v katalog_fv.md YAGNI, teď na žádost).

## 1. Režim stringu
`string_mode` ∈ `classic` (prázdné = classic) | `optimizer` | `fixed_voltage`; jediný zdroj pro výpočet je atribut
**střídače** `string_mode`. Kdo ho nastaví (generátor, v tomto pořadí): `inverters[i].string_mode` ve spec (průvodce:
volba „Režim stringů“) > sloupec artiklu střídače > sloupec `string_mode` artiklu optimizéru (SolarEdge →
`fixed_voltage`, Huawei P2 → `optimizer`, Tigo → `classic`) > `classic`. Ručně v GUI = úprava atributu.
Neznámá hodnota → počítá se `classic` + varování „neznámý režim stringu“ (atributy značky nemají `choice`).
- **classic** – dnešní výpočet beze změny + paralelní stringy na MPPT (§3) + kontrola vstupu optimizéru, má-li string
  data optimizéru (Tigo TS4-A-O na libovolném střídači – napětí stringu dávají moduly).
- **optimizer** (Huawei SUN2000 + SUN2000-450W-P2/600W-P) – jako classic, navíc počet optimizérů ve stringu, P stringu
  ≤ max, smíšení s neoptimalizovanými moduly jen při `opt_partial = 1`; příspěvek optimalizované jednotky k Uoc
  stringu = min(mpo·Uoc_mod(t_min), `opt_u_out_max`), je-li `u_out_max` známé (jinak Uoc modulů – konzervativně).
- **fixed_voltage** (SolarEdge) – Uoc·n, okno MPPT ani proudy na MPPT se nekontrolují (nahrazeno): optimizér na každém
  modulu (n_mod = n_opt·mpo), n_opt ∈ ⟨n_opt_min, n_opt_max⟩, P stringu = n_mod·p_wp ≤ p_string_max,
  `u_string ≤ u_dc_max` (věrohodnost), vstup optimizéru (§3). Stejná délka stringů se nevyžaduje.
Zamítnuto: režim jen u optimizéru (Huawei střídač funguje i bez optimizérů → rozhoduje střídač + volba projektanta);
režim u stringu (stringy jednoho střídače musí mít stejný režim; zbytečná redundance).

## 2. Data artiklu
**Optimizér** – nový `components/optimizers.csv`, `category=optimizer` (do `CATEGORIES`), `symbol_id` **prázdné**
(optimizér nemá značku; `fve.pv_string` by ho ukázal mezi moduly a `apply_to` by přepsal typ modulu). Sloupce:
`p_max_w` (jmen. vstupní výkon), `p_tol_pct` (povolené překročení dle výrobce, prázdné = 0), `u_in_max_v`,
`u_mppt_min_v`, `u_mppt_max_v`, `isc_in_max_a`, `i_out_max_a`, `u_out_max_v`, `modules_per_optimizer` (1 | 2),
`string_mode`, `partial_ok` (0/1), `compat` (text: „SolarEdge“, „Huawei SUN2000“, „*“), pravidla stringu dle tabulky
v datasheetu optimizéru: `n_min_1ph`, `n_max_1ph`, `p_string_max_1ph_w`, `n_min_3ph`, `n_max_3ph`, `p_string_max_3ph_w`,
dál `eff_max_pct`, `weight_kg`, `t_min_c`, `t_max_c`, `datasheet_url`, `note`. (Název `isc_in_max_a` místo
`i_sc_in_max_a` – souhlasí s `isc_mppt_max_a`.)
**Střídač** – `inverters.csv` nové sloupce `string_mode`, `u_string_v` (pevné napětí), `n_opt_min`, `n_opt_max`,
`p_string_max_w` (vyplnit jen, uvádí-li je datasheet/manuál střídače; Huawei typicky v manuálu střídače).
**Kde pravidla:** kombinace – SolarEdge je publikuje v tabulce optimizéru po typu střídače (1f/3f), Huawei u střídače.
Generátor vezme **nejpřísnější** ze známých: n_min = max, n_max = min, p_max = min (fáze z atributu `phases`)
a zapíše je do atributů střídače. Zamítnuto: jen u střídače (min. délka závisí na optimizéru, P850 ≠ S440);
jen u optimizéru (Huawei pravidla nejsou v listu optimizéru); matice optimizér × střídač (YAGNI).
`components.py`: NUMERIC + číselné sloupce; PARAM_TO_ATTR jen střídač (`string_mode`, `u_string_v`→`u_string`,
`n_opt_min`, `n_opt_max`, `p_string_max_w`→`p_string_max`); optimizér **vlastní** mapa `OPTIMIZER_ATTRS`
a `Component.optimizer_values(phases) -> dict` (`part_number`→`optimizer`, `manufacturer`→`opt_manufacturer`,
`opt_p_max`, `opt_p_tol`, `opt_u_in_max`, `opt_u_mppt_min`, `opt_u_mppt_max`, `opt_isc_in_max`, `opt_i_out_max`, `opt_u_out_max`,
`opt_modules`, `opt_partial`, `optimizer_id` + pravidla dané fáze) – nekoliduje s `type`/`manufacturer` modulu.
`optimizer_error(row)`: povinné `p_max_w`, `u_in_max_v`, `isc_in_max_a` (bez nich neukládat), u_mppt_min < u_mppt_max
≤ u_in_max, mpo ∈ {1, 2}, `string_mode` z množiny, n_min ≤ n_max; `inverter_error` + `string_mode` z množiny,
`fixed_voltage` ⇒ `u_string_v`, u_string ≤ u_dc_max, n_opt_min ≤ n_opt_max. Skryté atributy přes
`tools/gen_builtin_fve.py`: string `opt_*`, `optimizer_id`, `opt_manufacturer`, nepovinně `orientation` (text);
střídač `string_mode`, `u_string`, `n_opt_min`, `n_opt_max`, `p_string_max`.

## 3. Výpočty – jen `model/calc.py`, sdílené F7, výkazem i asistentem
```python
STRING_MODES = ("classic", "optimizer", "fixed_voltage")
@dataclass(frozen=True)
class OptimizerData: p_max; u_in_max; isc_in_max; modules=1; p_tol_pct=0.0; u_mppt_min=None
                     i_out_max=None; u_out_max=None; partial_ok=False; name=""
    @classmethod
    def from_attrs(cls, a) -> OptimizerData | None      # z atributů stringu; bez opt_p_max/u_in_max → None
# InverterData + string_mode="classic", u_string=None, n_opt_min=None, n_opt_max=None, p_string_max=None [W]
# StringLimits + step: int = 1 (mpo; propose_strings dělá délky po násobcích step), n_opt: tuple | None
def optimizer_issues(m, opt, t_min, t_max) -> list[str]
def string_issues(m, inv, n, n_par=1, t_min=…, t_max=…, opt=None, n_opt=None) -> list[str]   # rozšířené, zpětně kompat.
def string_limits(m, inv, t_min=…, t_max=…, opt=None) -> StringLimits
def parallel_issues(members: list[tuple[int, ModuleData, str]]) -> list[str]   # (n, modul, orientace) na jednom MPPT
def is_warning(msg) -> bool         # jediné místo: F7 (checks.calc_findings) i barva v asistentu (dnes klíčová slova)
```
**Vstup optimizéru** (všechny režimy, je-li `opt`): mpo·Uoc_mod(t_min) > u_in_max → chyba; Isc_mod > isc_in_max →
chyba (**Isc STC bez 1,25** – limit vstupu výrobce je vztažen k Isc modulu; 1,25 je dimenzování vedení, zůstává
v `check_cables`); mpo·p_wp > p_max·(1 + p_tol/100) → chyba, > p_max a ≤ tolerance → varování; mpo·Umpp(t_max) <
u_mppt_min → varování „omezení výkonu“; `compat` ≠ výrobce střídače → varování.
**Počet a výkon** (optimizer, fixed_voltage): n_opt mimo rozmezí → chyba; n_mod·p_wp > p_string_max → chyba;
fixed_voltage a n_mod ≠ n_opt·mpo → chyba „optimizér na každém modulu“ (2:1 a lichý počet modulů → chyba);
optimizer a n_opt·mpo < n_mod bez `opt_partial` → chyba „smíšení … není dovoleno“; string s `n_optimizers`, ale bez
dat optimizéru (starý spec) → jen varování „optimizér bez parametrů (doplňte z katalogu)“, počet/výkon se zkontroluje.
**Paralelní stringy** (classic, optimizer; jen se známým MPPT): různý počet modulů → varování „nestejná délka stringů
na MPPT (20 a 18 modulů, ΔUmpp 10 %)“; různý modul (`component_id`, jinak Voc/Vmp/Isc) → varování; různá
`orientation` (obě vyplněné) → varování. Chybu nedáváme (bezpečnost hlídá napětí/proud; výrobci píší „should“).
**Meze** fixed_voltage: n_min = n_opt_min·mpo, n_max = min(n_opt_max·mpo, ⌊p_string_max / p_wp / mpo⌋·mpo), step = mpo,
n_par_max = strings_per_mppt (bez proudové meze). optimizer: klasické meze s capem u_out_max ∩ meze z počtu a výkonu.
`check_strings`: OptimizerData ze stringu, `StringCheck` + `mode`, `n_opt`, `p_string`, `u_string`; API F7 beze změny.

## 4. Generátor, průvodce, exporty
Spec: `"optimizer": {"type", "per_module", "component_id"}` – s artiklem `_apply_optimizer_component` **před**
`_merge` (jako modul): prázdný typ ← part_number, `per_module` ← 1/mpo; string dostane `optimizer_values(phases)`,
`n_optimizers = ceil(n_mod / mpo)`; pravidla do střídače (§2), spec `inverters[i].string_mode/u_string/n_opt_min/
n_opt_max/p_string_max` vyhrává. **Starý spec bez `component_id` beze změny** (round, snapshot test zelený).
Průvodce: u optimizéru „Z katalogu…“ (`ComponentPicker(categories=("optimizer",))`, sloupce: výrobce, typ, P, Uin max,
Isc in, moduly/opt., kompatibilita, zdroj) vyplní typ a ks/modul; volba „Režim stringů: Automaticky (z artiklu) /
Klasický / S optimizéry / Pevné napětí“. Asistent: řádek režimu („pevné napětí 750 V – Uoc·n se nekontroluje;
optimizérů 14–50, P stringu ≤ … W → modulů 14–25“), řádek vstupu optimizéru (Uoc(t_min), Isc, P vůči limitům),
stav stringů a „Navrhnout stringy“ přes stejné `string_limits`. Exporty: BOM optimizér s `opt_manufacturer`;
výkaz Výpočty a TZ u fixed_voltage místo Uoc/Umpp „pevné U … V, P stringu … / … W“. Undo/redo: generátor tvoří nový
projekt; ruční změny = stávající `SetAttrCommand`; „Přiřadit optimizér z katalogu“ u existujícího stringu (makro
`SetAttrCommand`) až v další fázi.

## 5. Data (data-entry)
Pravidla jako katalog_fv.md §5 (jen WebSearch, doslovně se zdrojem, nic neodhadovat, `note` „WebSearch <datum>;
nejistoty“, musí projít validate). Optimizéry: SolarEdge S440, S500, S650B, P850, P1100 (u P850/P1100 ověřit 2:1,
u S650B mpo), Huawei SUN2000-450W-P2, SUN2000-600W-P, Tigo TS4-A-O. Pravidla SolarEdge z tabulky „PV system design“
v datasheetu optimizéru (1f HD-Wave / 3f 230/400); výjimky typu „vyšší P stringu při ≥ N optimizérech“ do `note`.
Střídače SolarEdge: 1f HD-Wave SE3000H–SE6000H (u_string 380), 3f SE5K–SE10K-RW0TEBEN4 a SE12.5K–SE27.6K (750),
Home Hub 3f SE5K–SE10K (hybrid) – ověřit označení; sloupce `string_mode`, `u_string_v`, `u_dc_max_v`, `p_dc_max_kwp`,
`strings_per_mppt` (= počet stringových vstupů, `mppt` = 1), `p_string_max_w`/`n_opt_*` jen je-li ve listu střídače.
Huawei: doplnit `n_opt_min/max`, `p_string_max_w` k SUN2000 M1/M3 jen z manuálu/listu Huawei, `string_mode` prázdné.
**K ověření daty (nevím jistě):** zda Huawei s optimizéry dovoluje delší string než Uoc·n (tj. zda platí cap
u_out_max), zda pak platí Umppt min; pravidla smíšené instalace Huawei (min. podíl / počet optimizérů); Tigo TS4-A-O
jen snižuje napětí (classic platí) a smí částečně; zda SolarEdge/Huawei uvádějí tolerance výkonu modulu (`p_tol_pct`).

## Pořadí a YAGNI
(1) core: kategorie, sloupce, `optimizer_error`, `optimizer_values`, skryté atributy; (2) data-entry souběžně s
(3) calc (+ `is_warning`, F7 bez změny API); (4) generate; (5) exporty; (6) GUI picker, režim, asistent; (7) docs
(COMPONENTS.md, MANUAL, CHANGELOG). Testy: `test_components` (validace optimizéru a střídače, builtin CSV), `test_calc`
(každý režim: meze, hlášky, step 2, smíšení, starý string bez dat, classic beze změny – stávající testy zelené,
paralelní stringy), `test_generate` (artikl → atributy, ceil, nejpřísnější pravidla podle fáze, snapshot beze změny),
`test_checks` (závažnosti), `test_wizard_catalog` (picker, režim, asistent = F7). YAGNI: značka optimizéru v JPS,
různé optimizéry v jednom stringu, US 277/480 V, import SolarEdge Designer, rapid shutdown, výnosy.

## Rozhodnutí orchestrátora (10/2026)
1. Huawei s optimizéry: konzervativně – cap `u_out_max` jen je-li v artiklu; Umppt min se kontroluje dál.
2. Smíšená instalace Huawei: bez `opt_partial = 1` chyba; min. podíl neznáme → neřešíme.
3. Isc na vstupu optimizéru: Isc STC modulu bez 1,25 (listy uvádějí „Isc of connected PV module“).
4. `p_tol_pct`: jen podle výrobce – Huawei P2/600W-P 5 % (solar.huawei.com specs), jinak prázdné = 0.
5. Nestejná délka paralelních stringů: jen varování.
6. `orientation` u stringu nepovinná, bez ní se orientace nekontroluje.
7. Výjimky SolarEdge („vyšší P stringu při ≥ N optimizérech“, rozdíl délek) jen do `note`.
8. `modules_per_optimizer` jen se zdrojem; bez zdroje řádek neukládat. Nejisté hodnoty prázdné – kontrola pak hlásí
   „chybí údaj“ (varování), nic se neodhaduje.
