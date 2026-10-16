# Návrh: výrobní data rozvaděče (zapojovací seznam pro dílnu)

Návrh agenta `architekt` (10/2026), schválil orchestrátor. Roadmapa „Z rešerše EPLAN 2026“, bod Výrobní data rozvaděče.
**Formát projektu se nemění (v9)** – jen nepovinné klíče `Wire.attrs` a `Layout.params`.

## 0. Zjištění
- `wiring_list` vypisuje vnitřní vodiče rozvaděče s barvou z `CORE_COLORS` a `attrs["cable"]` jako typem.
- `_end_text` bez ručních `Wire.terminals` vypíše jméno portu → 3P jistič s porty 1/2 dá L1/L2/L3 „F2:1“ třikrát.
- Rozložení zná jen modulové přístroje; `sb.feed_in/feed_out/busbar/pe_bar/junction` nejsou umístěné → odhad.
- Cívka stykače není v rozložení – poloha přes skupinu (`xref.DeviceIndex`).
- `DEV_H = 45` je jen v `ui/layout_view.py` → přesunout do modelu.
- **`EnclosurePanel.apply()` skládá `lay.params` jen z vlastních políček → maže jiné klíče** (opravit současně).
- Úpravy skříně jsou mimo undo (stávající dluh, mimo rozsah).
- `doc_pdf` dává do dokumentace všechny výkazy – výrobní seznam tam nepatří.
- Footprinty s polohou svorek neexistují.

## 1. Řádek (nový `envocad/model/wiring.py`, bez Qt)
```python
@dataclass(frozen=True)
class Ferrule:
    cross: float; length_mm: float; color: str; twin: bool = False
    def text(self) -> str   # „dutinka 1,5/8 černá“, „dvojitá dutinka 2×1,5/8 černá“

@dataclass
class ProductionWire:     # zároveň rozhraní pro budoucí exporty strojů (typovaná pole)
    number: int; sheet: str; ref: str; conductor: str
    from_text: str; to_text: str           # „+RDC1-F2:3“
    cross: float | None; cross_source: str # vodič | jištění | řízení | výchozí
    color: str; wire_type: str
    length_mm: int | None
    end_from: str; end_to: str
    ferrule_from: Ferrule | None; ferrule_to: Ferrule | None
    notes: list[str]; wire_id: str
```
Výkaz „Výrobní zapojovací seznam“: `Č. | Označení | Žíla | Odkud | Kam | Průřez [mm²] | Barva | Typ vodiče |
Délka [mm] | Koncovka odkud | Koncovka kam | Poznámka | List` (průřez a délka jako čísla). Jen listy rozvaděčů;
`attrs["prod"] == "0"` vynechá; můstky ne. Řazení: konce srovnat (řada, pozice, ref, svorka; umístěné první),
pak list, odkud, kam, žíla; čísla po seřazení.

## 2. Délka z rozložení
Souřadnice mm, Y nahoru, počátek levý horní roh montážní plochy. `P = row_pitch_mm`, `H = DEVICE_HEIGHT_MM = 45`
(do `model/project.py`, UI importuje). Osa řady r `y_r = -(r+0,5)·P`; žlab j `y_d(j) = -j·P`; svislé žlaby
`x_L = -side`, `x_R = modules_per_row·17,5 + side`.

```python
def device_terminal(sheet, w, conductor, side) -> tuple[str, bool]   # model/multipole.py
    # ručně z Wire.terminals; svorkový prvek přes wire_end_terminal; průchozí přístroj: pól k → vstup 2k+1,
    # výstup 2k+2, N → "N"; jinak jméno portu; odvozeno=True u pravidla (použije se i v textu Odkud/Kam)

@dataclass(frozen=True)
class TerminalPoint:
    x: float; y: float; duct: int; estimated: bool
def terminal_point(project, sheet, e, port, conductor, terminal, params, index) -> TerminalPoint | None
def route_length_mm(a, b, layout, params) -> int
```
- x: `pos·17,5 + (k+0,5)·W/poles`, k = (n−1)//2 (N/nečíselné → slot žíly); svorkový prvek – rovnoměrně po šířce.
- Strana: lichá svorka nahoře (žlab r), sudá dole (žlab r+1); bez čísla podle směru portu; svorkový prvek nahoře.
- Neumístěné (`wire_unplaced = "estimate"`): `sb.busbar` horní žlab 0 uprostřed; feed_in/out, terminal_block,
  fve.terminal, pe_bar spodní žlab `rows` uprostřed (estimated, poznámka „délka odhadem – X1 neumístěn“);
  ostatní → None (poznámka „neumístěno: F5“ / „konec v uzlu odbočky“). `"none"` vypne odhad.
- Trasa: `leg = |y_a − y_d(j_a)| + |y_b − y_d(j_b)|`; stejný žlab `horiz = |x_a − x_b|`, jinak kratší boční žlab
  + `vert = |y_d(j_a) − y_d(j_b)|`; `L = (leg + horiz + vert + 2·end) · (1 + reserve/100)` → nahoru na `round`.

Parametry (výchozí kód < `settings.json standard.wiring` (čte jen export a předá `base`) < `Layout.params`):
| klíč | výchozí | význam |
|---|---|---|
| `wire_type` | `H07V-K` | typ, pokud vodič nemá `cable` |
| `wire_end_mm` | 100 | přídavek na konec |
| `wire_reserve_pct` | 10 | rezerva % |
| `wire_round_mm` | 50 | zaokrouhlení nahoru |
| `wire_duct_side_mm` | 25 | osa svislého žlabu od konce lišty |
| `wire_cross_min` | 1,5 | min./výchozí silový průřez |
| `wire_cross_ctl` | 1 | výchozí průřez řízení (`ctl.*`) |
| `wire_unplaced` | `estimate` | `estimate` / `none` |
```python
@dataclass(frozen=True)
class WiringParams:
    wire_type="H07V-K"; end_mm=100.0; reserve_pct=10.0; round_mm=50.0; duct_side_mm=25.0
    cross_min=1.5; cross_ctl=1.0; unplaced="estimate"
    @classmethod
    def resolve(cls, layout, base=None) -> WiringParams
WIRING_PARAMS: list[tuple[str, str, str]]   # (klíč, popisek, výchozí) pro EnclosurePanel
```
Podnadpis xlsx vypíše použité parametry a pravidlo odvození svorek.

## 3. Průřez, barva, typ, koncovka (tabulky v `model/wiring.py`)
- `wire_cross(project, sheet, w, params) -> (float | None, zdroj)`: `attrs["cross"]` → nejmenší `in_` z konců
  (jen přístroje, ne busbar/pe_bar/junction/svorky) přes tabulku → `ctl.*` → `cross_min` s poznámkou.
```python
# ORIENTAČNÍ – vnitřní vodiče Cu/PVC ve žlabu (ČSN EN 61439-1 příl. H); schválí projektant
IN_TO_CROSS = [(10, 1.5), (16, 2.5), (25, 4), (32, 6), (50, 10), (63, 16), (80, 25), (100, 35), (125, 50), (160, 70)]
```
- `conductor_color(w, conductor)`: `attrs["color"]` (jednožilový vždy; vícežilový jen fáze/DC, ne N/PE/PEN), jinak
  `CORE_COLORS`. `wiring_list` na rozvaděči přejde na `conductor_color`.
- Typ: `attrs["cable"]`, jinak `params.wire_type`.
- Koncovka: `attrs["end_a"/"end_b"]` (prázdné = auto, `-` = bez, text doslova); auto dutinka jen u ohebného
  (`-K`, `-F`, `LiY`); dvě žíly do stejné svorky → `twin`; 3+ → poznámka.
```python
FERRULE_DIN46228 = {0.5: ("bílá", 8), 0.75: ("šedá", 8), 1.0: ("červená", 8), 1.5: ("černá", 8),
                    2.5: ("modrá", 8), 4: ("šedá", 10), 6: ("žlutá", 12), 10: ("červená", 12),
                    16: ("modrá", 12), 25: ("žlutá", 16), 35: ("červená", 16), 50: ("modrá", 20)}
```

## 4. Export
- `reports.production_wiring_list(project, lib, sheet=None)` → `ALL_REPORTS` za „Zapojovací seznam“;
  `NOT_IN_DOC = {"Výrobní zapojovací seznam"}` – `doc_pdf.plan()` přeskočí.
- `wiring.production_wires(project, sheet=None, base=None) -> list[ProductionWire]`.
- Volitelně `xlsx_export.export_production_xlsx(project, lib, path, sheet=None)` (+ list „Parametry“) a položka menu.
- Stroje (Komax, Steinhauer) teď ne – rozhraní `ProductionWire`, budoucí `export/machine_<výrobce>.py`.

## 5. Formát, GUI, undo
Nové nepovinné `Wire.attrs` (list rozvaděče): `color` (Barva vodiče), `end_a`/`end_b` (Koncovka A/B),
`prod` (Do výrobního seznamu, `0` = ne). `Layout.params`: `wire_*`. `SWITCHBOARD_WIRE_ATTRIBUTES` v `model/project.py`.
GUI: WireDialog a panel Vlastnosti na listu rozvaděče s těmito atributy (placeholder s automatickou hodnotou);
`EnclosurePanel` skupina „Výrobní data (zapojení)“ + **oprava `apply()` – zachovat neznámé klíče**. Undo: atributy
vodiče přes `SetAttrCommand`; parametry skříně zůstávají mimo undo (samostatný úkol).

## 6. Pořadí a testy
(1) wiring.py tabulky a funkce; (2) device_terminal, DEVICE_HEIGHT_MM, terminal_point, route_length_mm;
(3) production_wires, výkaz, NOT_IN_DOC, wiring_list barva, SWITCHBOARD_WIRE_ATTRIBUTES; (4) GUI; (5) xlsx pro dílnu;
(6) dokumentace. Testy `tests/test_wiring.py` (trasa, poloha svorky 3P, cívka přes stykač, device_terminal,
průřez min(In) a sběrnice, barvy, koncovky a twin, neumístěné konce, řazení a priorita parametrů), xlsx s čísly,
round-trip atributů, GUI (pole jen na rozvaděči, `EnclosurePanel.apply()` zachová neznámý klíč).

## Známá omezení v1
Konce v uzlu bez délky; neumístěné svorky odhadem; odvozené svorky jen pro pólové číslování 1/2, 3/4, 5/6;
tabulky orientační – schválí projektant.

## Zamítnuto
Nová pole `Wire` (formát v10); barva/koncovka per žíla; footprinty se svorkami (neexistují); skutečné trasování
žlabů; vzdálenost bez žlabů; průřez z `calc.ampacity` či max(In); trvalé číslování vodičů; tabulky v settings;
umístitelné přívody/vývody; výrobní seznam v PDF dokumentaci; stroje a CSV teď; barevné schéma EN 60204-1.
