# Lokální normové tabulky (`~/.envocad/norms/`) a referenční sady

Tento dokument je návod pro projektanta, který má přístup k normám a chce do EnvoCADu doplnit **svoje ověřené
hodnoty** místo vestavěných orientačních (viz `docs/NORMY_POTREBA.md`). Hodnoty z norem **nepatří do gitu** – leží
jen na vašem počítači, kód je jen čte. Vestavěné konstanty v `model/calc.py` a `model/thermal.py` se tím nemění;
bez souborů se počítá přesně jako dřív.

## Kam soubor uložit

Složka `norms` v domovské složce EnvoCADu:

| Systém | Cesta |
|---|---|
| Linux, macOS | `~/.envocad/norms/` |
| Windows | `C:\Users\<jméno>\.envocad\norms\` (`%USERPROFILE%\.envocad\norms\`) |
| vlastní umístění | `ENVOCAD_HOME=<složka>` → `<složka>/norms/` |

Složka se sama nevytváří – založte ji ručně. Čtou se všechny soubory `*.json`, seřazené podle jména. **Jeden soubor
= jeden normový dokument** (např. jeden soubor pro ČSN 33 2000-5-52, jiný pro IEC TR 60890). Soubor se načte při
prvním výpočtu; po úpravě je nutné program restartovat (změny za běhu se nesledují).

Soubory norem do gitu nepatří: složka `norms/` je v `.gitignore` a `python tools/check_licensed_data.py` (i CI)
selže, když git sleduje `*.json` se značkou `envocad-norms`.

## Částečné přepsání

Soubor smí obsahovat jen některé položky. Co v něm není, zůstane vestavěné. Přepisuje se po celých položkách:
celá tabulka, celý skalár, u Iz jeden způsob uložení (nová řada **nahrazuje celou** vestavěnou řadu daného
způsobu, včetně průřezů – průřezy si soubor definuje sám). Prázdné `"tables": {}` je platný soubor bez účinku.

## Klíče souboru ↔ konstanty v kódu ↔ soupis `NORMY_POTREBA.md`

| Klíč v `tables` | Konstanta v kódu | Řádek soupisu | Jednotky |
|---|---|---|---|
| `iz` (`cu`, `pvc70`, `loaded` 3, `t_ref_c` 30, `method` A1/B1/C/D/E) | `calc.IZ_3[způsob]` | K1 | průřez [mm²] → Iz [A] |
| `iz_2_factor` | `calc.IZ_2_FACTOR` | K2 | činitel (bezrozměrný) |
| `al_factor` | `calc.AL_FACTOR` | K3 | činitel |
| `k_temp_air` (`pvc70`) | `calc.K_T_PVC_AIR` | K5 | teplota okolí [°C] → činitel |
| `k_large_no_vents` | `thermal.K_LARGE_NO_VENTS` | T1 | Ae [m²] → k |
| `k_small` | `thermal.K_SMALL` | T2 | Ae [m²] → k |
| `c_large_no_vents` | `thermal.C_LARGE_NO_VENTS` | T3 | f = h^1,35/Ab → c |
| `c_small` | `thermal.C_SMALL` | T4 | g = h/š → c |
| `b_factors` | `thermal.B_FACTORS` | T5 | činitel b podle montáže a plochy |
| `x_large`, `x_small`, `ae_limit_m2` | `thermal.X_LARGE`, `X_SMALL`, `AE_LIMIT_M2` | T6 | exponent; plocha [m²] |
| `d_partitions_no_vents` | `thermal.D_PARTITIONS_NO_VENTS` | T7 | počet přepážek (0–3) → d |

Teplotní činitel se počítá beze změny: teplota se zaokrouhlí na 5 °C, **bez interpolace**; chybí-li klíč, platí 1,0
pro t ≤ 30 °C, jinak hodnota u nejvyšší teploty tabulky.

Metody uložení mimo A1, B1, C, D, E, jiný vodič než `cu`, jiná izolace než `pvc70`, `loaded` ≠ 3 a `t_ref_c` ≠ 30
se zatím nepoužívají (jen varování, položka se přeskočí) – nové způsoby uložení, izolace a tabulky pro Al jsou
mimo rozsah.

## Formát souboru

Každá položka musí mít `ref` – místo v normě (tabulka, sloupec, článek, obrázek). Bez něj se celý soubor odmítne.

```json
{
  "format": "envocad-norms", "format_version": 1,
  "source": {"standard": "PŘÍKLAD 0000-0", "edition": "ed. 9", "year": 2099, "amendments": ["Z1"],
             "transcribed_by": "PR", "transcribed_on": "2099-01-01", "checked_by": "", "note": ""},
  "tables": {
    "iz": [{"conductor": "cu", "insulation": "pvc70", "loaded": 3, "t_ref_c": 30, "method": "B1",
            "ref": "tab. X.1 sl. 3", "unit": "A", "points": [[1.5, 1], [2.5, 2], [4, 3]]}],
    "iz_2_factor": {"ref": "čl. 1.2", "value": 2},
    "al_factor": {"ref": "čl. 1.3", "value": 3},
    "k_temp_air": [{"insulation": "pvc70", "ref": "tab. X.2", "points": [[30, 1], [35, 2]]}],
    "k_small": {"ref": "obr. 4", "points": [[1, 3], [2, 2]]},
    "d_partitions_no_vents": {"ref": "tab. 2", "points": [[0, 1], [1, 2], [2, 3], [3, 3]]},
    "x_small": {"ref": "čl. 1", "value": 1}
  }
}
```

**Čísla v příkladu (1, 2, 3 …) jsou vymyšlená, nejde o normové hodnoty.** Nikdy je nepoužívejte pro skutečný projekt.
Příklad záměrně ukazuje jen část položek (částečné přepsání); `b_factors` má tvar
`{"ref": "…", "value": {"nástěnná": {"top": …, "bottom": …, "front": …, "back": …, "side": …}, …}}` pro všechny
čtyři montáže (volně stojící, nástěnná, zapuštěná, stojanová) a všech pět ploch.

`source`: povinné jsou `standard`, `edition`, `year` (celé číslo), `transcribed_by`, `transcribed_on`; volitelné
`amendments`, `checked_by`, `note`. Údaje se uchovávají u každé přepsané položky (`norm_tables.provenance()`).

## Pravidla ověření a co se stane při chybě

Výpočet **nikdy nespadne** kvůli vadnému souboru.

**Soubor se odmítne celý** (platí tabulky z dosavadního stavu, nejhůř vestavěné), když: není platný JSON v UTF-8
nebo kořen není objekt; `format` není `envocad-norms`; `format_version` chybí, není celé číslo nebo je vyšší než
podporovaná (1); chybí `source.standard|edition|year|transcribed_by|transcribed_on`; chybí `source`, `tables` nebo
`ref` u kterékoli položky; v `tables` je neznámý klíč; hodnota není konečné číslo (text, `true`, NaN, nekonečno) nebo
je ≤ 0 (výjimky: `bottom` v činiteli b a x-ové souřadnice křivek / počet přepážek mohou být 0; x křivek nesmí být
záporné); křivka nebo Iz má méně než 2 body nebo x neroste ostře vzestupně; průřez v `iz` není > 0; Iz s průřezem
klesá; `d_partitions_no_vents` nemá x = 0, 1, 2, 3; `b_factors` nemá všechny 4 montáže a 5 ploch.

**Jen varování** (soubor se použije, položka se přeskočí): nepodporovaná kombinace v `iz` / `k_temp_air` (viz výše);
neznámé pole v `source` nebo v položce.

**Konflikt:** definují-li stejnou položku (způsob uložení Iz, skalár, křivku) dva soubory, položka zůstane
**vestavěná** a zapíše se varování s klíčem položky; oba soubory jinak platí pro své ostatní položky.

Důvody odmítnutí a varování jsou v logu `envocad.norms` (běžný log aplikace; ve spuštěném programu také
`norm_tables.load_report()` – použité soubory, odmítnuté soubory s chybami, varování).

## Referenční sady – kontrola proti Sichru a jiným nástrojům

`tests/data/ref_iz.json` (Iz a průřez) a `tests/data/ref_thermal.json` (oteplení skříně) jsou sady případů, v nichž
je výsledek externího nástroje (např. Sichr) porovnán s výpočtem EnvoCADu. V gitu jsou **prázdné** (`"cases": []`) a
tolerance mají `null` – tu určí vlastník; žádná výchozí tolerance v kódu není.

```json
{"format": "envocad-refset", "format_version": 1, "kind": "iz",
 "tolerance": {"iz_a": {"abs": null, "rel": null}},
 "cases": [
  {"id": "iz-001", "description": "", "tables": "norms",
   "inputs": {"function": "ampacity", "cross": 1, "method": "B1", "loaded": 3, "aluminium": false,
              "t_ambient": 30, "grouping": 1},
   "expected": {"iz_a": 2},
   "tolerance": {"iz_a": {"abs": 1, "rel": null}},
   "origin": {"tool": "Sichr", "tool_version": "0.0", "date": "2099-01-01", "url": "", "supplied_by": "PR", "note": ""}}
 ]}
```

(Čísla opět vymyšlená.) Jak zapsat případ ze Sichru:

1. Zvolte `kind`: `iz` nebo `thermal` (podle souboru sady).
2. `iz`: `inputs.function` je `ampacity` (vstupy `cross`, volitelně `method`, `loaded`, `aluminium`, `t_ambient`,
   `grouping`; výstup `iz_a`) nebo `min_cross` (vstupy `in_a`, `method`, `loaded`, `aluminium`, `t_ambient`; výstup
   `cross_mm2`, porovnává se **přesně**, tolerance se neuplatní).
3. `thermal`: vstupy jsou parametry `thermal.enclosure_rise` (`width_mm`, `height_mm`, `depth_mm`, `mounting`,
   `p_total_w`, volitelně `partitions`, `plastic`); `expected` je neprázdná podmnožina `ae_m2`, `k`, `c`, `dt_mid_k`,
   `dt_top_k` (nezaokrouhlené hodnoty, jednotky m² / K).
4. `expected` = výsledek Sichru; `origin` je povinné: `tool`, `tool_version`, `date` (RRRR-MM-DD), `supplied_by`
   neprázdné, `url` smí být prázdné.
5. Tolerance se zadává zvlášť pro každou veličinu v `tolerance` sady (výchozí) a případně v případu (přepíše výchozí).
   Případ vyhoví, když |vypočteno − očekáváno| ≤ max(`abs`, `rel`·|očekáváno|); aspoň jedno z `abs` / `rel` musí být
   zadané, jinak případ selže s hláškou „tolerance neurčena“.
6. `id` musí být v sadě jedinečné. `tables`: `"norms"` (výchozí) = případ běží proti vašim lokálním tabulkám;
   `"builtin"` = proti vestavěným.

Spuštění (případy s `tables: "norms"` se bez proměnné přeskočí):

```
ENVOCAD_REF_NORMS=<složka s norms/*.json> QT_QPA_PLATFORM=offscreen pytest tests/test_ref_sets.py
```

Např. `ENVOCAD_REF_NORMS=~/.envocad/norms`. Tabulky se načtou ze zadané složky jen pro test, nikam se neukládají.
