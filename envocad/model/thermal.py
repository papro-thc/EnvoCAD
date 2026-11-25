"""Ověření oteplení rozvaděče výpočtem – ČSN EN 61439-1 čl. 10.10.4.3.1 / IEC TR 60890:2014. Bez Qt.

Postup:
1. Ztrátový výkon přístrojů ΣPv – z atributu `p_loss_w` přístroje (ruční údaj), jinak z artiklu (`p_loss_w`
   z katalogu, `lib`), jinak odhad podle typu a In (zdroj u každého přístroje: `ThermalResult.losses`);
   přepočet na skutečné zatížení faktorem RDF² (RDF = Ib/In, výchozí 0,8).
   K tomu přirážka na vnitřní vodiče a spoje (výchozí 15 %). P = celkový ztrátový výkon [W].
2. Účinná chladicí plocha skříně Ae = Σ(A0 · b) – IEC TR 60890 tab. 3 (činitel b podle polohy stěny;
   podlaha se nezapočítává).
3. Oteplení vzduchu uprostřed výšky skříně  Δt0,5 = k · d · P^x
   - k … konstanta skříně z Ae: Ae > 1,25 m² obr. 3 (bez ventilačních otvorů), Ae ≤ 1,25 m² obr. 4 / tabulka;
   - x … 0,804 (Ae > 1,25 m²), 0,715 (Ae ≤ 1,25 m²);
   - d … činitel vodorovných přepážek (tab. normy pro skříně bez otvorů: 0/1/2/3 → 1,00/1,05/1,15/1,30).
4. Oteplení v horní části  Δt1,0 = c · Δt0,5
   - c … činitel rozložení teploty: Ae > 1,25 m² obr. 6 podle f = h^1,35 / Ab (Ab = půdorysná plocha
     skříně), Ae ≤ 1,25 m² obr. 7 podle g = h / š.

Konstanty k a c jsou tabulky bodů z křivek normy s lineární interpolací. Hodnoty jsou převzaty z paměti
(reprodukce tabulek IEC 60890 v aplikačních příručkách výrobců) a jsou označeny jako ORIENTAČNÍ –
před použitím v průkazu ověřit proti normě. Jisté jsou exponenty x, činitele b (tab. 3) a činitel d.
Implementována je pouze varianta skříně BEZ ventilačních otvorů; pro `vents=True` se počítá stejně
(na straně bezpečnosti) a do poznámek se zapíše upozornění.

5. Hodnocení po přístrojích (`device_temperatures`, `ThermalResult.verdict`): teplota vzduchu v úrovni osy řady
   DIN lišty přístroje (lineárně mezi Δt0,5 ve středu a Δt1,0 nahoře, spodní polovina konzervativně Δt0,5,
   neumístěný přístroj = horní část) se porovná s horní mezí provozní teploty okolí přístroje `t_max` (datasheet,
   artikl `t_max_c`), bez údaje s předpokladem 40 °C; nejhorší přístroj určuje verdikt. Se zadanou nejnižší
   teplotou okolí skříně `t_ambient_min` i dolní mez `t_min`.

Výsledek je orientační – pro průkaz dle normy lze použít i údaje výrobce skříně (Rittal Therm, Hager…).

Tabulky a činitele (k, c, d, b, x, mez Ae) lze lokálně přepsat souborem `~/.envocad/norms/*.json`
(`model/norm_tables.py`, formát v `docs/NORMY_FORMAT.md`); výpočet je bere z `norm_tables.current()`, nebo z
parametru `tables=`. Konstanty níže jsou vestavěné hodnoty (bez souborů se počítá přesně s nimi).
"""
from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass, field

from envocad.model import norm_tables
from envocad.model.advisory import ADVISORY_NOTE
from envocad.model.project import Element, Sheet

# Odhad ztrátového výkonu na pól při In [W/A] – ORIENTAČNÍ střední hodnoty z katalogů (MCB/MCCB/RCD, odpínače,
# stykače). Pojistkový odpínač = ztráta pojistkové vložky (gG/gPV 10×38 při In ~ 1,5–3 W → ~0,15 W/A), pojistka
# totéž; hlavní (silový) kontakt stykače jako stykač. Řadové svorky (sb.terminal_block) se nepočítají zvlášť –
# zahrnuje je přirážka na vodiče a spoje (`wiring_pct`). Údaj výrobce (`p_loss_w`) má vždy přednost.
LOSS_PER_A_PER_POLE = {
    "fve.breaker_mcb": 0.09, "sb.rcbo": 0.11, "sb.rcd": 0.04, "fve.breaker_mccb": 0.06,
    "sb.main_switch": 0.03, "fve.switch_disconnector": 0.03, "fve.dc_disconnect": 0.03,
    "fve.contactor": 0.08, "ctl.contact_power": 0.08, "fve.fuse": 0.15, "fve.fuse_disconnect": 0.15,
    "fve.meter": 0.0, "fve.changeover_switch": 0.03,
}
# Pevná ztráta [W] nezávislá na proudu (cívky, elektronika) – ORIENTAČNÍ. Stykač kreslený jako jeden prvek má cívku
# v sobě; cívka (ctl.coil) kreslená zvlášť nese ztrátu sama (silové kontakty `ctl.contact_power` mají jen ztrátu
# průchodem proudu). Cívka se nezapočítá, když položkou výkazu je stykač (`is_bom_device`) – žádná dvojí cívka.
FIXED_LOSS_W = {"fve.spd": 0.5, "fve.meter": 2.0, "fve.contactor": 2.5, "ctl.coil": 2.5, "fve.transformer": 0.0,
                "fve.grid_protection": 3.0}

# Hodnocení oteplení po přístrojích (`device_temperatures`): teplota vzduchu v úrovni řady DIN lišty přístroje se
# porovná s horní mezí provozní teploty okolí přístroje `t_max` (datasheet; artikl `t_max_c` → atribut `t_max`).
# Přístroj bez údaje: předpoklad `DEFAULT_T_MAX_C` = 40 °C – horní mez normálních provozních podmínek výrobkových
# norem (ČSN EN 60947-1 čl. 6.1.1, ČSN EN 60898-1: okolí do +40 °C, průměr za 24 h 35 °C). Výrobci obvykle uvádějí
# víc (55–70 °C, s odlehčením), takže 40 °C je na straně bezpečnosti; verdikt pak hlásí „chybí rozsah teplot – ověřit“.
# Dolní mez `t_min` se kontroluje jen se zadanou nejnižší teplotou okolí skříně `t_ambient_min` (vzduch uvnitř
# = okolí – bez zatížení, např. FVE v noci, se skříň neohřívá); přístroj bez `t_min` pak předpokládá
# `DEFAULT_T_MIN_C` = −5 °C (dolní mez normálních provozních podmínek týchž norem).
# `DEVICE_REF_C` 40 °C – referenční teplota kalibrace MCCB dle EN 60947-2 (MCB dle EN 60898 je 30 °C): nad ní se
# proud přístrojů snižuje (derating); verdikt to připomene i u vyhovujícího výsledku.
DEFAULT_T_MAX_C = 40.0
DEFAULT_T_MIN_C = -5.0
DEVICE_REF_C = 40.0
# Přístroje rozložení, které se po přístrojích nehodnotí bez vlastního údaje `t_max`: řadové svorky jsou dimenzované
# na vyšší teploty (EN 60947-7-1, běžně do 100–130 °C) – předpoklad 40 °C by je hlásil zbytečně.
THERMAL_SKIP_SYMBOLS = {"sb.terminal_block"}
SOURCE_ARTICLE, SOURCE_ATTR, SOURCE_ASSUMED = "artikl", "atribut", "předpoklad"
# Zdroj ztrátového výkonu přístroje (`rated_loss`, výkaz oteplení): údaj artiklu (i propsaný do atributu `p_loss_w`
# se stejnou hodnotou), ruční atribut (bez artiklu nebo jiná hodnota než artikl), odhad z In (`LOSS_PER_A_PER_POLE`).
LOSS_ARTICLE, LOSS_MANUAL, LOSS_ESTIMATE = "artikl", "ruční", "odhad"


@dataclass
class DeviceLoss:
    """Ztrátový výkon přístroje ve výpočtu oteplení: `p_w` při zatížení RDF·In, `p_rated_w` při In (None = odhad
    bez údaje), `source` „artikl“ / „ruční“ / „odhad“."""
    element_id: str
    ref: str
    p_w: float
    p_rated_w: float | None
    source: str


@dataclass
class DeviceTemp:
    """Teplota vzduchu u přístroje a jeho meze. `row` = řada rozložení od 0 (shora), None = neumístěný (počítá se
    s teplotou v horní části skříně). `source` / `t_min_source`: „artikl“, „atribut“ nebo „předpoklad“
    (`t_min_source` = "" když se dolní mez nekontroluje)."""
    element_id: str
    ref: str
    row: int | None
    t_air: float
    t_max: float
    source: str
    t_min: float | None = None
    t_min_source: str = ""

    @property
    def margin(self) -> float:
        """Rezerva k horní mezi [K] (záporná = překročeno)."""
        return self.t_max - self.t_air

    @property
    def place(self) -> str:
        return f"v řadě {self.row + 1}" if self.row is not None else "neumístěný (horní část skříně)"

    @property
    def missing(self) -> bool:
        """Chybí údaj z datasheetu (počítá se s předpokladem)."""
        return self.source == SOURCE_ASSUMED or self.t_min_source == SOURCE_ASSUMED

    def too_hot(self) -> bool:
        return self.t_air > self.t_max + 1e-9

    def too_cold(self, t_ambient_min: float | None) -> bool:
        return t_ambient_min is not None and self.t_min is not None and t_ambient_min < self.t_min - 1e-9


# IEC TR 60890 tab. 3 – činitel b: volná horní plocha 1,4; zakrytá horní plocha (vestavěná skříň) 0,7;
# volné boční plochy (přední, zadní, boky) 0,9; zakryté boční plochy (např. zadní stěna nástěnné skříně) 0,5;
# podlaha se nezapočítává (0).  (jisté)
B_FACTORS = {
    # (horní, spodní, přední, zadní, boky)
    "volně stojící": (1.4, 0.0, 0.9, 0.9, 0.9),
    "nástěnná": (1.4, 0.0, 0.9, 0.5, 0.9),
    "zapuštěná": (0.7, 0.0, 0.9, 0.5, 0.5),
    "stojanová": (1.4, 0.0, 0.9, 0.9, 0.9),
}
K_PLASTIC_PENALTY = 1.15  # plastová skříň odvádí teplo hůř než lakovaná ocel (předpoklad EnvoCAD, ne norma)

AE_LIMIT_M2 = 1.25
X_LARGE = 0.804  # Ae > 1,25 m² (jisté)
X_SMALL = 0.715  # Ae ≤ 1,25 m² (jisté)

# IEC TR 60890 obr. 3 – konstanta k, skříň BEZ ventilačních otvorů, Ae > 1,25 m².  ORIENTAČNÍ hodnoty.
K_LARGE_NO_VENTS: tuple[tuple[float, float], ...] = (
    (1.25, 0.524), (1.5, 0.45), (2.0, 0.35), (2.5, 0.275), (3.0, 0.225), (3.5, 0.20), (4.0, 0.185),
    (5.0, 0.16), (6.0, 0.14), (7.0, 0.13), (8.0, 0.12), (9.0, 0.11), (10.0, 0.10), (12.0, 0.08),
)
# IEC TR 60890 obr. 4 / tabulka – konstanta k pro Ae ≤ 1,25 m² (bez ventilace).  ORIENTAČNÍ hodnoty.
K_SMALL: tuple[tuple[float, float], ...] = (
    (0.08, 3.973), (0.09, 3.643), (0.10, 3.371), (0.15, 2.5), (0.20, 2.022), (0.25, 1.716), (0.30, 1.5),
    (0.35, 1.339), (0.40, 1.215), (0.45, 1.116), (0.50, 1.035), (0.60, 0.907), (0.70, 0.817), (0.80, 0.743),
    (0.90, 0.682), (1.00, 0.632), (1.10, 0.592), (1.20, 0.558), (1.25, 0.542),
)
# Činitel přepážek d – skříně bez ventilačních otvorů, Ae > 1,25 m² (jisté). Více než 3 přepážky → 1,30.
D_PARTITIONS_NO_VENTS = {0: 1.00, 1: 1.05, 2: 1.15, 3: 1.30}
# IEC TR 60890 obr. 6 – činitel c (bez ventilace, Ae > 1,25 m²) podle f = h^1,35/Ab; křivka pro
# samostatnou skříň volnou ze všech stran (nejvyšší c ze všech způsobů instalace → na straně bezpečnosti).
# ORIENTAČNÍ hodnoty.
C_LARGE_NO_VENTS: tuple[tuple[float, float], ...] = (
    (0.6, 1.225), (1.0, 1.24), (1.5, 1.265), (2.0, 1.285), (3.0, 1.32), (4.0, 1.35), (5.0, 1.375),
    (6.0, 1.395), (7.0, 1.415), (8.0, 1.435), (9.0, 1.45), (10.0, 1.465), (12.0, 1.495),
)
# IEC TR 60890 obr. 7 – činitel c pro Ae ≤ 1,25 m² podle g = h/š.  ORIENTAČNÍ hodnoty.
C_SMALL: tuple[tuple[float, float], ...] = (
    (0.0, 1.00), (0.5, 1.10), (1.0, 1.21), (1.5, 1.29), (2.0, 1.36), (2.5, 1.41), (3.0, 1.45),
)


@dataclass
class ThermalResult:
    """Výsledek výpočtu oteplení; `devices` = teploty po přístrojích (`device_temperatures`), `t_ambient_min_c` =
    nejnižší teplota okolí skříně (parametr `t_ambient_min`, None = dolní meze se nekontrolují)."""
    p_devices_w: float
    p_total_w: float
    ae_m2: float
    dt_mid_k: float
    dt_top_k: float
    rdf: float
    t_ambient_c: float
    notes: list[str]
    k: float = 0.0
    c: float = 1.0
    d: float = 1.0
    x: float = X_LARGE
    devices: list[DeviceTemp] = field(default_factory=list)
    t_ambient_min_c: float | None = None
    losses: list[DeviceLoss] = field(default_factory=list)

    def loss_counts(self) -> dict[str, int]:
        """Počet přístrojů s nenulovou ztrátou podle zdroje (`LOSS_ARTICLE`, `LOSS_MANUAL`, `LOSS_ESTIMATE`)."""
        out: dict[str, int] = {}
        for x in self.losses:
            if x.p_w > 0:
                out[x.source] = out.get(x.source, 0) + 1
        return out

    def loss_summary(self) -> str:
        """„Pv: 3× artikl, 1× ruční, 2× odhad“ (jen nenulové ztráty), prázdné bez ztrát."""
        c = self.loss_counts()
        parts = [f"{c[k]}× {k}" for k in (LOSS_ARTICLE, LOSS_MANUAL, LOSS_ESTIMATE) if c.get(k)]
        return f"Pv: {', '.join(parts)}" if parts else ""

    @property
    def t_top_c(self) -> float:
        return self.t_ambient_c + self.dt_top_k

    def air_at(self, height_ratio: float | None) -> float:
        """Teplota vzduchu [°C] ve výšce `height_ratio` (0 = dno, 1 = strop skříně; None = horní část) –
        `air_temperature`."""
        return air_temperature(self.t_ambient_c, self.dt_mid_k, self.dt_top_k, height_ratio)

    def critical(self) -> DeviceTemp | None:
        """Kritický přístroj: první z `hot_devices` (prokázané překročení má přednost před překročením předpokladu),
        jinak s nejmenší rezervou k horní mezi (při shodě přednost údaji z datasheetu, pak pořadí prvků listu);
        None bez přístrojů."""
        hot = self.hot_devices()
        if hot:
            return hot[0]
        return min(self.devices, key=_severity) if self.devices else None

    def hot_devices(self) -> list[DeviceTemp]:
        """Přístroje nad `t_max`: nejdřív prokázaná překročení (mez z artiklu / atributu), pak podle předpokladu;
        uvnitř skupiny podle rezervy."""
        return sorted((d for d in self.devices if d.too_hot()), key=lambda d: (d.source == SOURCE_ASSUMED, d.margin))

    def cold_devices(self) -> list[DeviceTemp]:
        return [d for d in self.devices if d.too_cold(self.t_ambient_min_c)]

    def missing_devices(self) -> list[DeviceTemp]:
        return [d for d in self.devices if d.missing]

    def missing_text(self) -> str:
        """„u 3 přístrojů chybí rozsah teplot – ověřit (předpoklad 40 °C)“, prázdné když údaje jsou."""
        n = len(self.missing_devices())
        if not n:
            return ""
        word = "přístroje" if n == 1 else "přístrojů"
        assumed = f"{DEFAULT_T_MAX_C:.0f} °C"
        if self.t_ambient_min_c is not None:
            assumed = f"t_max {DEFAULT_T_MAX_C:.0f} °C, t_min {_c(DEFAULT_T_MIN_C)} °C"
        return f"u {n} {word} chybí rozsah teplot – ověřit (předpoklad {assumed})"

    def critical_text(self) -> str:
        """Krátký popis kritického přístroje pro panel skříně („F3 v řadě 1: ≈ 48 °C, t_max 55 °C (artikl),
        rezerva 7 K“), prázdné bez přístrojů."""
        d = self.critical()
        if d is None:
            return ""
        tail = f"rezerva {d.margin:.0f} K" if d.margin >= 0 else f"překročeno o {-d.margin:.0f} K"
        return f"{d.ref or '?'} {d.place}: ≈ {d.t_air:.0f} °C, t_max {d.t_max:.0f} °C ({d.source}), {tail}"

    def verdict(self) -> str:
        """Orientační hodnocení po přístrojích: nejhorší přístroj (nejmenší rezerva k `t_max`, teplota vzduchu
        v jeho řadě – `device_temperatures`) určuje verdikt; při zadané `t_ambient_min` i dolní meze `t_min`.
        Chybějící údaje se doplní předpokladem (`DEFAULT_T_MAX_C`) a verdikt na ně upozorní."""
        hot, cold = self.hot_devices(), self.cold_devices()
        tail = self.missing_text()
        tail = f"; {tail}" if tail else ""
        if hot or cold:
            parts = []
            if hot:
                d = hot[0]
                more = f", a další {len(hot) - 1}" if len(hot) > 1 else ""
                parts.append(f"{d.ref or '?'} {d.place}: ≈ {d.t_air:.0f} °C > t_max {d.t_max:.0f} °C"
                             + (" (předpoklad)" if d.source == SOURCE_ASSUMED else "") + more)
            if cold:
                d = min(cold, key=lambda x: -(x.t_min or 0.0))
                more = f", a další {len(cold) - 1}" if len(cold) > 1 else ""
                parts.append(f"{d.ref or '?'}: t_min {_c(d.t_min)} °C > nejnižší okolí {_c(self.t_ambient_min_c)} °C"
                             + (" (předpoklad)" if d.t_min_source == SOURCE_ASSUMED else "") + more)
            fix = ("zvětšit skříň, snížit zatížení, doplnit ventilaci nebo zvolit přístroje s vyšší t_max" if hot
                   else "doplnit vytápění skříně nebo zvolit přístroje s nižší t_min")
            return f"NEVYHOVUJE ({ADVISORY_NOTE}) – {'; '.join(parts)}; {fix}{tail}"
        d = self.critical()
        if d is None:
            return f"vyhovuje ({ADVISORY_NOTE}) – bez přístrojů, uvnitř ≈ {self.t_top_c:.0f} °C"
        hottest = max(x.t_air for x in self.devices)
        label = "nejteplejší" if d.t_air >= hottest - 1e-9 else "nejmenší rezerva"
        txt = (f"vyhovuje ({ADVISORY_NOTE}) – {label} {d.ref or '?'} ≈ {d.t_air:.0f} °C "
               f"(t_max {d.t_max:.0f} °C, rezerva {d.margin:.0f} K)")
        if hottest > DEVICE_REF_C:
            txt += (f"; nad {DEVICE_REF_C:.0f} °C ověřit odlehčení (derating) jističů a přístrojů podle katalogu")
        return txt + tail


def _severity(d: DeviceTemp) -> tuple[float, bool]:
    return (round(d.margin, 6), d.source == SOURCE_ASSUMED)


def _c(v: float | None) -> str:
    """Teplota pro text: celé číslo se znaménkem minus (−5)."""
    return f"{v:.0f}".replace("-", "−") if v is not None else "?"


def air_temperature(t_ambient_c: float, dt_mid_k: float, dt_top_k: float, height_ratio: float | None) -> float:
    """Teplota vzduchu ve skříni [°C] ve výšce `height_ratio` (0 = dno, 1 = strop) podle profilu IEC TR 60890:
    od středu výšky (Δt0,5) k horní části (Δt1,0) lineárně. Spodní polovina konzervativně Δt0,5 (norma tam
    teplotu dál snižuje, my ne – na straně bezpečnosti). None (neumístěný přístroj) = horní část."""
    if height_ratio is None:
        return t_ambient_c + dt_top_k
    h = min(max(height_ratio, 0.0), 1.0)
    if h <= 0.5:
        return t_ambient_c + dt_mid_k
    return t_ambient_c + dt_mid_k + (dt_top_k - dt_mid_k) * (h - 0.5) / 0.5


def row_height_ratio(layout, row: int) -> float:
    """Výška osy řady `row` (0 = horní) nad dnem skříně jako podíl výšky skříně. Řady jsou ve skříni svisle na střed
    s roztečí `row_pitch_mm` (jako kreslí rozložení), osa řady uprostřed pásu řady."""
    pitch = layout.row_pitch_mm
    h = max(layout.height_mm, layout.rows * pitch)
    axis = h / 2 + (layout.rows / 2 - row - 0.5) * pitch
    return min(max(axis / h, 0.0), 1.0) if h > 0 else 1.0


def _temp_value(v) -> float | None:
    try:
        x = float(str(v).replace(",", ".").replace("−", "-").strip())
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _limit(e: Element, attr: str, param: str, default: float | None, lib) -> tuple[float | None, str]:
    """Mez přístroje: atribut prvku (z artiklu `apply_to`, nebo ručně), jinak parametr artiklu v knihovně, jinak
    předpoklad. Zdroj „artikl“, když hodnota odpovídá přiřazenému artiklu."""
    comp = None
    if lib is not None and e.component_id and hasattr(lib, "component"):
        try:
            comp = lib.component(e.component_id)
        except Exception:  # noqa: BLE001 – knihovna nedostupná → jen atributy
            comp = None
    c_val = _temp_value(comp.params.get(param)) if comp is not None else None
    a_val = _temp_value(e.attrs.get(attr))
    if a_val is not None:
        return a_val, SOURCE_ARTICLE if c_val is not None and abs(c_val - a_val) < 1e-9 else SOURCE_ATTR
    if c_val is not None:
        return c_val, SOURCE_ARTICLE
    return default, SOURCE_ASSUMED if default is not None else ""


def device_temperatures(sheet: Sheet, result: ThermalResult, layout=None, project=None, lib=None,
                        t_ambient_min: float | None = None) -> list[DeviceTemp]:
    """Teplota vzduchu u každého přístroje rozložení (`Layout.devices`) a jeho meze. Teplota v úrovni osy řady
    (`row_height_ratio` → `air_temperature`); neumístěný přístroj = horní část skříně. `t_max` / `t_min` z atributu
    nebo artiklu (`lib`), jinak předpoklad `DEFAULT_T_MAX_C` / `DEFAULT_T_MIN_C` (dolní mez jen se zadanou
    `t_ambient_min`). Řadové svorky (`THERMAL_SKIP_SYMBOLS`) jen s vlastním údajem."""
    lay = layout if layout is not None else sheet.layout
    out: list[DeviceTemp] = []
    for e in lay.devices(sheet, project, lib):
        t_max, src = _limit(e, "t_max", "t_max_c", DEFAULT_T_MAX_C, lib)
        if e.symbol_id in THERMAL_SKIP_SYMBOLS and src == SOURCE_ASSUMED:
            continue
        t_min, src_min = (None, "")
        if t_ambient_min is not None:
            t_min, src_min = _limit(e, "t_min", "t_min_c", DEFAULT_T_MIN_C, lib)
        pl = lay.placement(e.id)
        row = pl.row if pl is not None else None
        t_air = result.air_at(row_height_ratio(lay, row) if row is not None else None)
        out.append(DeviceTemp(e.id, e.ref, row, round(t_air, 1), float(t_max), src, t_min, src_min))
    return out


def layout_inputs(layout) -> tuple[float, float]:
    """(RDF, teplota okolí °C) z parametrů skříně; každá hodnota zvlášť – nezadaná nebo neplatná = výchozí
    0,8 / 35 °C (`project.enclosure_number`)."""
    from envocad.model.project import enclosure_number
    return enclosure_number(layout.params, "rdf", 0.8), enclosure_number(layout.params, "t_ambient", 35.0)


def ambient_min(layout) -> float | None:
    """Nejnižší teplota okolí skříně [°C] (parametr `t_ambient_min`), None = nezadána / neplatná – dolní meze
    přístrojů se pak nekontrolují."""
    from envocad.model.project import enclosure_param_error
    raw = str(layout.params.get("t_ambient_min") or "").strip()
    if not raw or enclosure_param_error("t_ambient_min", raw):
        return None
    return _temp_value(raw.replace(" ", ""))


def rated_loss(e: Element, comp=None) -> tuple[float | None, str]:
    """Ztrátový výkon přístroje při In [W] a jeho zdroj: atribut `p_loss_w` (shodný s artiklem = „artikl“, jinak
    „ruční“), jinak `p_loss_w` artiklu `comp` („artikl“), jinak (None, „odhad“)."""
    a_val = _temp_value(e.attrs.get("p_loss_w")) if e.attrs.get("p_loss_w") else None
    c_val = _temp_value(comp.params.get("p_loss_w")) if comp is not None and comp.params.get("p_loss_w") else None
    if a_val is not None:
        return a_val, LOSS_ARTICLE if c_val is not None and abs(a_val - c_val) < 1e-9 else LOSS_MANUAL
    if c_val is not None:
        return c_val, LOSS_ARTICLE
    return None, LOSS_ESTIMATE


def device_power_loss(e: Element, rdf: float = 0.8, comp=None) -> float:
    """Ztrátový výkon přístroje [W] při zatížení rdf·In: údaj z atributu / artiklu `comp` (`rated_loss`), jinak
    odhad z In a počtu pólů."""
    rated, _src = rated_loss(e, comp)
    if rated is not None:
        return rated * rdf ** 2
    try:
        i_n = float(str(e.attrs.get("in_", "0")).replace(",", ".") or 0)
    except ValueError:
        i_n = 0.0
    per_a = LOSS_PER_A_PER_POLE.get(e.symbol_id, 0.0)
    poles = max(e.poles, 1)
    p = per_a * i_n * poles * rdf ** 2 + FIXED_LOSS_W.get(e.symbol_id, 0.0)
    return round(p, 2)


def cooling_area(width_mm: float, height_mm: float, depth_mm: float, mounting: str,
                 tables: norm_tables.NormTables | None = None) -> float:
    """Účinná chladicí plocha Ae [m²] dle IEC TR 60890 tab. 3 (plochy × činitel b)."""
    t = tables if tables is not None else norm_tables.current()
    w, h, d = width_mm / 1000, height_mm / 1000, max(depth_mm, 150) / 1000
    key = next((k for k in t.b_factors if k in (mounting or "").lower()), "nástěnná")
    b_top, b_bottom, b_front, b_back, b_side = t.b_factors[key]
    return (w * d) * b_top + (w * d) * b_bottom + (w * h) * b_front + (w * h) * b_back + 2 * (h * d) * b_side


def _interp(table: tuple[tuple[float, float], ...], xv: float) -> float:
    """Lineární interpolace v tabulce bodů; mimo rozsah se drží krajní hodnota."""
    xs = [p[0] for p in table]
    if xv <= xs[0]:
        return table[0][1]
    if xv >= xs[-1]:
        return table[-1][1]
    i = bisect_left(xs, xv)
    (x0, y0), (x1, y1) = table[i - 1], table[i]
    return y0 + (y1 - y0) * (xv - x0) / (x1 - x0)


def k_factor(ae: float, tables: norm_tables.NormTables | None = None) -> float:
    """Konstanta skříně k (IEC TR 60890 obr. 3 pro Ae > 1,25 m², obr. 4 pro Ae ≤ 1,25 m²; bez ventilace)."""
    t = tables if tables is not None else norm_tables.current()
    return _interp(t.k_large_no_vents if ae > t.ae_limit_m2 else t.k_small, ae)


def d_factor(partitions: int, tables: norm_tables.NormTables | None = None) -> float:
    """Činitel vodorovných přepážek d (skříň bez ventilačních otvorů)."""
    t = tables if tables is not None else norm_tables.current()
    return t.d_partitions_no_vents[min(max(int(partitions), 0), 3)]


def c_factor(ae: float, height_mm: float, width_mm: float, depth_mm: float,
             tables: norm_tables.NormTables | None = None) -> float:
    """Činitel rozložení teploty c (obr. 6: f = h^1,35/Ab pro Ae > 1,25 m²; obr. 7: g = h/š jinak)."""
    t = tables if tables is not None else norm_tables.current()
    h, w, dd = height_mm / 1000, width_mm / 1000, max(depth_mm, 150) / 1000
    if ae > t.ae_limit_m2:
        f = h ** 1.35 / (w * dd) if w > 0 else 0.0
        return _interp(t.c_large_no_vents, f)
    g = h / w if w > 0 else 0.0
    return _interp(t.c_small, g)


@dataclass(frozen=True)
class EnclosureRise:
    """Oteplení skříně bez zaokrouhlení: chladicí plocha Ae [m²] (u plastu už snížená), k, c, d, exponent x,
    oteplení uprostřed výšky `dt_mid_k` a v horní části `dt_top_k` [K]."""
    ae_m2: float
    k: float
    c: float
    d: float
    x: float
    dt_mid_k: float
    dt_top_k: float


def enclosure_rise(width_mm: float, height_mm: float, depth_mm: float, mounting: str, p_total_w: float,
                   partitions: int = 0, plastic: bool = False,
                   tables: norm_tables.NormTables | None = None) -> EnclosureRise:
    """Δt0,5 = k·d·P^x a Δt1,0 = c·Δt0,5 pro skříň daných rozměrů a celkový ztrátový výkon `p_total_w` [W]
    (`temperature_rise` ji volá po sečtení ztrát přístrojů). `plastic`: Ae se dělí `K_PLASTIC_PENALTY`."""
    t = tables if tables is not None else norm_tables.current()
    ae = cooling_area(width_mm, height_mm, depth_mm, mounting, t)
    if plastic:
        ae /= K_PLASTIC_PENALTY
    x = t.x_large if ae > t.ae_limit_m2 else t.x_small
    k = k_factor(ae, t)
    d = d_factor(partitions, t)
    c = c_factor(ae, height_mm, width_mm, depth_mm, t)
    try:
        dt_mid = k * d * p_total_w ** x if p_total_w > 0 else 0.0
    except OverflowError:       # nesmyslná tabulka (obří exponent) nesmí shodit kontrolu; výsledek = nekonečno
        return EnclosureRise(ae, k, c, d, x, math.inf, math.inf)
    return EnclosureRise(ae, k, c, d, x, dt_mid, c * dt_mid)


def temperature_rise(sheet: Sheet, rdf: float = 0.8, t_ambient_c: float = 35.0, wiring_pct: float = 15.0,
                     partitions: int = 0, vents: bool = False, project=None, layout=None, lib=None) -> ThermalResult:
    """Oteplení skříně dle IEC TR 60890. Cívka stykače se nezapočítá, když položkou výkazu je stykač na stejném
    listu (`xref.DeviceIndex.is_bom_device`; bez `project` se skupiny hledají jen na listu). `layout` = rozměry
    a parametry skříně místo `sheet.layout` (rozpracovaná kopie v dialogu skříně). Výsledek nese i teploty po
    přístrojích (`device_temperatures`; `lib` = knihovna pro meze z artiklů, nejnižší okolí z `t_ambient_min`)."""
    from envocad.model.device_size import component_of, memo_lib
    from envocad.model.xref import DeviceIndex
    lib = memo_lib(lib)
    idx = DeviceIndex.build(project) if project is not None else DeviceIndex.for_sheets([sheet])
    lay = layout if layout is not None else sheet.layout
    notes: list[str] = []
    p_dev = 0.0
    losses: list[DeviceLoss] = []
    for e in sheet.elements:
        if not idx.is_bom_device(e, sheet):
            continue
        comp = component_of(e, lib)
        p = device_power_loss(e, rdf, comp)
        rated, src = rated_loss(e, comp)
        if p or rated is not None:
            losses.append(DeviceLoss(e.id, e.ref, round(p, 2), rated, src))
        if p:
            p_dev += p
    p_total = p_dev * (1 + wiring_pct / 100)
    t = norm_tables.current()
    plastic = "plast" in (lay.params.get("material", "") or "").lower()
    notes.append("Ae dle IEC TR 60890 tab. 3")
    if plastic:
        notes.append("plastová skříň – chladicí plocha snížena o 15 %")
    r = enclosure_rise(lay.width_mm, lay.height_mm, lay.depth_mm, lay.params.get("mounting", "nástěnná"), p_total,
                       partitions, plastic, t)
    ae, k, d, c, x, dt_mid, dt_top = r.ae_m2, r.k, r.d, r.c, r.x, r.dt_mid_k, r.dt_top_k
    large = ae > t.ae_limit_m2
    if large:
        notes.append(f"k dle IEC TR 60890 obr. 3 (Ae > 1,25 m², bez ventilace), x = {x}")
        notes.append("c dle obr. 6 (f = h^1,35/Ab, samostatná skříň – konzervativně)")
    else:
        notes.append(f"k dle IEC TR 60890 obr. 4 (Ae ≤ 1,25 m²), x = {x}")
        notes.append("c dle obr. 7 (g = h/š)")
    if partitions:
        notes.append(f"d = {d:g} pro {partitions} vodorovné přepážky (tab. činitele d, bez ventilace)")
    if vents:
        notes.append("skříň s ventilačními otvory: výpočet proveden jako bez otvorů (obr. 5 neimplementován) "
                     "– výsledek na straně bezpečnosti")
    notes.append("tabulky k a c jsou orientační – ověřit proti IEC TR 60890")
    if not lay.params.get("depth_mm"):
        notes.append("hloubka skříně nezadána – počítáno 150 mm")
    if not any(x.source != LOSS_ESTIMATE for x in losses):
        notes.append("ztráty přístrojů odhadnuty z In (doplňte p_loss_w z katalogů pro přesnější výsledek)")
    res = ThermalResult(round(p_dev, 1), round(p_total, 1), round(ae, 3), round(dt_mid, 1), round(dt_top, 1),
                        rdf, t_ambient_c, notes, k=round(k, 4), c=round(c, 3), d=d, x=x,
                        t_ambient_min_c=ambient_min(lay), losses=losses)
    if any(x.source != LOSS_ESTIMATE for x in losses) and res.loss_counts().get(LOSS_ESTIMATE):
        notes.append(f"{res.loss_summary()} – odhad z In u přístrojů bez údaje výrobce")
    res.devices = device_temperatures(sheet, res, lay, project, lib, res.t_ambient_min_c)
    if res.devices:
        notes.append("teplota u přístroje v úrovni osy jeho řady (střed → horní část lineárně, spodní polovina "
                     "jako střed); neumístěný přístroj = horní část")
    return res
