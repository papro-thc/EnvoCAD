# Návrh: katalog FV modulů a střídačů v průvodci

Návrh agenta `architekt` (10/2026), schválil orchestrátor. Roadmapa „Databáze FV modulů a střídačů pro výběr v průvodci“.
**Formát projektu se nemění (v9)** – nové sloupce CSV artiklů a klíče specifikace/meta jsou nepovinné.

## 0. Výchozí stav
- FV moduly v katalogu nejsou (kategorie `pv_module` existuje, žádný řádek). `inverters.csv`: 7 střídačů, 6 hybridů,
  1 baterie; sloupce `u_dc_max_v`, `u_mppt_min_v`, `u_mppt_max_v`, `i_mppt_max_a`, `strings_per_mppt` jsou v NUMERIC
  a PARAM_TO_ATTR, ale chybí v hlavičce – hodnoty jen v `note` → F7 u katalogových střídačů hlásí „nemá Umax / MPPT“.
- `calc.check_strings`: modul `voc, vmp, isc, beta_voc`, střídač `u_dc_max, u_mppt_min, u_mppt_max, i_mppt_max`;
  pevné `T_MIN_DEFAULT=-10`, `T_MAX_DEFAULT=70`; proud `1,25·Isc` jednoho stringu proti `i_mppt_max` (paralelní
  stringy nesčítá, maximální napětí systému modulu nekontroluje).
- `generate._apply_inverter_component` doplní atributy z artiklu; pro modul nic. Průvodce bez β_Voc a Imp,
  `ComponentPicker` s pevnými sloupci a jednou kategorií.

## 1. Data artiklu
**FV modul** – nový `components/pv_modules.csv`, `category=pv_module`, `symbol_id=fve.pv_string`:
`p_wp`→`p_module`, `voc_v`→`voc`, `vmp_v`→`vmp`, `isc_a`→`isc`, `imp_a`→**`imp`** (nově), `beta_voc`→`beta_voc`,
nové `alpha_isc`, `gamma_pmax`, `noct_c` (jen katalog), `u_sys_max_v`→**`u_sys_max`**, `i_fuse_max_a` (rezerva),
`technology` (text), `width_mm`, `height_mm`, `depth_mm`, `weight_kg`, `t_min_c`, `t_max_c`.
**Střídač** – `inverters.csv` doplnit do hlavičky `u_dc_max_v`, `u_mppt_min_v`, `u_mppt_max_v`, `i_mppt_max_a`,
`strings_per_mppt`, nové `isc_mppt_max_a`→**`isc_mppt_max`**, `eff_max_pct`, `eff_eu_pct`, `weight_kg`.
`components.py`: NUMERIC + nové sloupce; PARAM_TO_ATTR jen `imp_a`, `u_sys_max_v`, `isc_mppt_max_a`;
`Component.attr_values() -> dict[str, str]` (apply_to přes ni); `pv_module_error(row)` (vmp<voc, imp<isc,
−1<β<0, |p_wp − vmp·imp|/p_wp ≤ 3 %), `inverter_error(row)` (u_mppt_min < u_mppt_max ≤ u_dc_max,
strings_per_mppt ≥ 1) ve `validate`. Skryté atributy `imp`, `u_sys_max`, `isc_mppt_max` u `fve.pv_string`
a `fve.inverter*` (přes tools/gen_builtin_fve.py).

## 2. Výpočty – jen `model/calc.py`, sdílené průvodcem i F7
```python
@dataclass(frozen=True)
class ModuleData: voc; vmp; isc; imp=None; beta_voc=BETA_VOC_DEFAULT; u_sys_max=None; p_wp=None
    @classmethod
    def from_attrs(cls, a) -> ModuleData | None
@dataclass(frozen=True)
class InverterData: u_dc_max=None; u_mppt_min=None; u_mppt_max=None; i_mppt_max=None; isc_mppt_max=None
                    mppt=None; strings_per_mppt=2; p_ac=None; p_dc_max=None
    @classmethod
    def from_attrs(cls, a) -> InverterData
@dataclass
class StringLimits: n_min; n_max; n_par_max; reasons: list[str]
def design_temperatures(project) -> tuple[float, float]      # meta pv_t_min/pv_t_max, jinak výchozí
def string_limits(m, inv, t_min, t_max) -> StringLimits
def string_issues(m, inv, n, n_par, t_min, t_max) -> list[str]
def suggest_inverter_count(p_dc_kwp, p_ac_kw, dc_ac_max=1.3) -> int
def propose_strings(n_total, n_inverters, lim, inv) -> tuple[list[list[int]], int]
```
Pravidla: `n_max = floor(min(u_dc_max, u_sys_max) / Uoc(t_min))`, `Uoc(t) = Voc·(1 + β/100·(t − 25))`;
`n_max_mppt = floor(u_mppt_max / Vmp(t_min))`; `n_min = ceil(u_mppt_min / Vmp(t_max))`. Proud na MPPT pro `n_par`
stringů (`DCk → (k−1)//strings_per_mppt`): se `isc_mppt_max` → `n_par·Isc > isc_mppt_max` chyba,
`n_par·Imp > i_mppt_max` varování „omezení výkonu“; **bez `isc_mppt_max` zůstává dnešní pravidlo** (1,25·Isc
jednoho stringu proti `i_mppt_max`) – starým projektům nepřibydou chyby. Stávající texty hlášek zachovat
(testy hledají „Umax“), nově „… > Umax systému modulu …“.
`check_strings(project, t_min=None, t_max=None)` přes tyto funkce, seskupení podle (střídač, MPPT), `StringCheck`
+ `mppt`, `n_par`; API pro F7 beze změny. `tz_export` a `reports` tisknou teploty z `design_temperatures`;
BOM u modulů výrobce z `attrs["manufacturer"]`.
Teploty v projektu: `meta["pv_t_min"]`, `meta["pv_t_max"]` (pole ve Vlastnostech projektu); výchozí v kódu −10/70
(beze změny výsledků); průvodce předvyplní z `standard.pv_t_min` (−20) / `pv_t_max` (70).

## 3. Generátor
`spec["module"]["component_id"]` → `_apply_module_component` (doplní prázdné atributy, spec vyhrává, stringy
dostanou `component_id`); `spec["site"] = {"t_min", "t_max"}` → meta; `_apply_inverter_component` dřív, než se
dopočítá `mppt` (strings_per_mppt z artiklu ovlivní DC vstupy). Zpětně kompatibilní.

## 4. GUI
`ComponentPicker(categories=…)`, sloupce podle kategorie (modul: výrobce, typ, Wp, Voc, Isc, Vmp, Imp, β, Usys,
technologie, rozměry, zdroj; střídač: P AC, P DC max, fáze, MPPT, str./MPPT, U DC max, MPPT okno, I/MPPT, Isc/MPPT,
hybrid, zdroj), filtr výkon od–do a fáze; neúplné/neověřené řádky šedě s tooltipem.
`ProjectWizard`: „Z katalogu…“ u modulu a střídače (pole se vyplní, ruční úprava vyhrává, „×“ zruší), nová pole
Imp, β_Voc, Isc/MPPT, stringů/MPPT, návrhové teploty, nepovinně celkem modulů; **asistent** (štítek, přepočet při
změně): rozsah modulů ve stringu s důvody, stav každého stringu, DC/AC a doporučený počet střídačů; tlačítko
„Navrhnout stringy“. Chyby stringů v průvodci jen varují. `spec()` s `component_id` a `site`.

## 5. Data (data-entry)
Nejdřív doplnit sloupce 13 střídačů z textu `note` (doslovné hodnoty se zdrojem). Pak `pv_modules.csv` (~12 řádků:
JA Solar JAM54D40, LONGi Hi-MO 6/X6, Jinko Tiger Neo 54HL4R, Trina Vertex S+, Canadian TOPBiHiKu6, AIKO ABC,
jedna 72článková třída) a střídače (~20–25: Huawei SUN2000 M1/MB0/M3, Fronius Symo GEN24 Plus, Tauro, GoodWe ET/SDT,
SolaX X3-Hybrid G4, Deye SG04LP3). Pravidla: jen WebSearch, každé číslo doslovně ve výsledku, `datasheet_url`,
`source=web` (`datasheet` jen PDF výrobce), nic neodhadovat/nedopočítávat, `note` „WebSearch <datum>; nejistoty“,
`id` `<výrobce>-<typ>`, řádek bez voc/isc (modul) či u_dc_max + MPPT okna (střídač) neukládat, musí projít validate.

## Pořadí a YAGNI
(1) core: sloupce, validace, attr_values; (2) data-entry souběžně s (3) core calc + exporty; (4) core generate;
(5) GUI picker + průvodce; (6) docs. YAGNI: kontrola gPV proti i_fuse_max_a, stejná délka stringů na MPPT,
bateriová okna, importér PVsyst .PAN/.OND (fáze 3: `library/pvsyst.py`), výnosové simulace.
