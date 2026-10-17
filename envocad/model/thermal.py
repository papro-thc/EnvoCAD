"""Ověření oteplení rozvaděče výpočtem – ČSN EN 61439-1 čl. 10.10.4.3.1 / IEC TR 60890:2014. Bez Qt.

Postup:
1. Ztrátový výkon přístrojů ΣPv – z atributu `p_loss_w` přístroje (údaj výrobce při In), jinak odhad
   podle typu a In; přepočet na skutečné zatížení faktorem RDF² (RDF = Ib/In, výchozí 0,8).
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

Výsledek je orientační – pro průkaz dle normy lze použít i údaje výrobce skříně (Rittal Therm, Hager…).
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

from envocad.model.project import Element, Sheet

# Odhad ztrátového výkonu na pól při In [W/A] – ORIENTAČNÍ střední hodnoty z katalogů (MCB/MCCB/RCD, odpínače,
# stykače). Pojistkový odpínač = ztráta pojistkové vložky (gG/gPV 10×38 při In ~ 1,5–3 W → ~0,15 W/A), pojistka
# totéž; hlavní (silový) kontakt stykače jako stykač. Řadové svorky (sb.terminal_block) se nepočítají zvlášť –
# zahrnuje je přirážka na vodiče a spoje (`wiring_pct`). Údaj výrobce (`p_loss_w`) má vždy přednost.
LOSS_PER_A_PER_POLE = {
    "fve.breaker_mcb": 0.09, "sb.rcbo": 0.11, "sb.rcd": 0.04, "fve.breaker_mccb": 0.06,
    "sb.main_switch": 0.03, "fve.switch_disconnector": 0.03, "fve.dc_disconnect": 0.03,
    "fve.contactor": 0.08, "ctl.contact_power": 0.08, "fve.fuse": 0.15, "fve.fuse_disconnect": 0.15,
    "fve.meter": 0.0,
}
# Pevná ztráta [W] nezávislá na proudu (cívky, elektronika) – ORIENTAČNÍ. Stykač kreslený jako jeden prvek má cívku
# v sobě; cívka (ctl.coil) kreslená zvlášť nese ztrátu sama (silové kontakty `ctl.contact_power` mají jen ztrátu
# průchodem proudu). Cívka se nezapočítá, když položkou výkazu je stykač (`is_bom_device`) – žádná dvojí cívka.
FIXED_LOSS_W = {"fve.spd": 0.5, "fve.meter": 2.0, "fve.contactor": 2.5, "ctl.coil": 2.5, "fve.transformer": 0.0}

# Hodnocení oteplení podle teploty vzduchu uvnitř skříně (okolí + Δt v horní části), ne jen podle Δt:
# ČSN EN 61439-1 čl. 7.1.1 – normální provozní podmínky: teplota okolí nepřekročí 40 °C, průměr za 24 h 35 °C.
# Přístroje uvnitř (jističe, odpínače, svorky) jsou dimenzované na teplotu vzduchu kolem sebe; běžné katalogové
# maximum pro modulové přístroje bez dalších opatření je 55 °C (`DEVICE_AIR_MAX_C`), nad referenční teplotou
# přístrojů (`DEVICE_REF_C` 40 °C – kalibrace MCCB dle EN 60947-2; MCB dle EN 60898 je 30 °C) se proud
# přístrojů snižuje (derating). ORIENTAČNÍ hodnoty – konkrétní mez podle katalogu použitých přístrojů.
DEVICE_REF_C = 40.0
DEVICE_AIR_MAX_C = 55.0

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

    @property
    def t_top_c(self) -> float:
        return self.t_ambient_c + self.dt_top_k

    def limit_k(self, limit_k: float | None = None) -> float:
        """Přípustné oteplení vzduchu v horní části skříně nad okolím [K]: zadané, jinak tak, aby teplota uvnitř
        nepřekročila `DEVICE_AIR_MAX_C` (55 °C – 35 °C okolí = 20 K)."""
        return limit_k if limit_k is not None else DEVICE_AIR_MAX_C - self.t_ambient_c

    def verdict(self, limit_k: float | None = None) -> str:
        """Orientační hodnocení podle absolutní teploty uvnitř (okolí + Δt v horní části) i oteplení:
        nad `limit_k` (výchozí = do 55 °C uvnitř) nevyhovuje; nad 40 °C (referenční teplota přístrojů) vyhovuje
        jen s odlehčením (derating) přístrojů; jinak vyhovuje. Viz `DEVICE_AIR_MAX_C`, `DEVICE_REF_C`."""
        t_in = self.t_top_c
        lim = self.limit_k(limit_k)
        if self.dt_top_k > lim or t_in > DEVICE_AIR_MAX_C:
            return (f"NEVYHOVUJE (orientačně) – uvnitř ≈ {t_in:.0f} °C, oteplení {self.dt_top_k:.0f} K > {lim:.0f} K; "
                    "zvětšit skříň, snížit zatížení nebo doplnit ventilaci")
        if t_in > DEVICE_REF_C:
            return (f"vyhovuje s podmínkou (orientačně) – uvnitř ≈ {t_in:.0f} °C nad {DEVICE_REF_C:.0f} °C: "
                    "ověřit odlehčení (derating) jističů a přístrojů podle katalogu")
        return f"vyhovuje (orientačně) – uvnitř ≈ {t_in:.0f} °C"


def layout_inputs(layout) -> tuple[float, float]:
    """(RDF, teplota okolí °C) z parametrů skříně; každá hodnota zvlášť – nezadaná nebo neplatná = výchozí
    0,8 / 35 °C (`project.enclosure_number`)."""
    from envocad.model.project import enclosure_number
    return enclosure_number(layout.params, "rdf", 0.8), enclosure_number(layout.params, "t_ambient", 35.0)


def device_power_loss(e: Element, rdf: float = 0.8) -> float:
    """Ztrátový výkon přístroje [W] při zatížení rdf·In."""
    explicit = e.attrs.get("p_loss_w")
    if explicit:
        try:
            return float(str(explicit).replace(",", ".")) * rdf ** 2
        except ValueError:
            pass
    try:
        i_n = float(str(e.attrs.get("in_", "0")).replace(",", ".") or 0)
    except ValueError:
        i_n = 0.0
    per_a = LOSS_PER_A_PER_POLE.get(e.symbol_id, 0.0)
    poles = max(e.poles, 1)
    p = per_a * i_n * poles * rdf ** 2 + FIXED_LOSS_W.get(e.symbol_id, 0.0)
    return round(p, 2)


def cooling_area(width_mm: float, height_mm: float, depth_mm: float, mounting: str) -> float:
    """Účinná chladicí plocha Ae [m²] dle IEC TR 60890 tab. 3 (plochy × činitel b)."""
    w, h, d = width_mm / 1000, height_mm / 1000, max(depth_mm, 150) / 1000
    key = next((k for k in B_FACTORS if k in (mounting or "").lower()), "nástěnná")
    b_top, b_bottom, b_front, b_back, b_side = B_FACTORS[key]
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


def k_factor(ae: float) -> float:
    """Konstanta skříně k (IEC TR 60890 obr. 3 pro Ae > 1,25 m², obr. 4 pro Ae ≤ 1,25 m²; bez ventilace)."""
    return _interp(K_LARGE_NO_VENTS if ae > AE_LIMIT_M2 else K_SMALL, ae)


def d_factor(partitions: int) -> float:
    """Činitel vodorovných přepážek d (skříň bez ventilačních otvorů)."""
    return D_PARTITIONS_NO_VENTS[min(max(int(partitions), 0), 3)]


def c_factor(ae: float, height_mm: float, width_mm: float, depth_mm: float) -> float:
    """Činitel rozložení teploty c (obr. 6: f = h^1,35/Ab pro Ae > 1,25 m²; obr. 7: g = h/š jinak)."""
    h, w, dd = height_mm / 1000, width_mm / 1000, max(depth_mm, 150) / 1000
    if ae > AE_LIMIT_M2:
        f = h ** 1.35 / (w * dd) if w > 0 else 0.0
        return _interp(C_LARGE_NO_VENTS, f)
    g = h / w if w > 0 else 0.0
    return _interp(C_SMALL, g)


def temperature_rise(sheet: Sheet, rdf: float = 0.8, t_ambient_c: float = 35.0, wiring_pct: float = 15.0,
                     partitions: int = 0, vents: bool = False, project=None, layout=None) -> ThermalResult:
    """Oteplení skříně dle IEC TR 60890. Cívka stykače se nezapočítá, když položkou výkazu je stykač na stejném
    listu (`xref.DeviceIndex.is_bom_device`; bez `project` se skupiny hledají jen na listu). `layout` = rozměry
    a parametry skříně místo `sheet.layout` (rozpracovaná kopie v dialogu skříně)."""
    from envocad.model.xref import DeviceIndex
    idx = DeviceIndex.build(project) if project is not None else DeviceIndex.for_sheets([sheet])
    lay = layout if layout is not None else sheet.layout
    notes: list[str] = []
    p_dev = 0.0
    for e in sheet.elements:
        if not idx.is_bom_device(e, sheet):
            continue
        p = device_power_loss(e, rdf)
        if p:
            p_dev += p
    p_total = p_dev * (1 + wiring_pct / 100)
    ae = cooling_area(lay.width_mm, lay.height_mm, lay.depth_mm, lay.params.get("mounting", "nástěnná"))
    notes.append("Ae dle IEC TR 60890 tab. 3")
    if "plast" in (lay.params.get("material", "") or "").lower():
        ae /= K_PLASTIC_PENALTY
        notes.append("plastová skříň – chladicí plocha snížena o 15 %")
    large = ae > AE_LIMIT_M2
    x = X_LARGE if large else X_SMALL
    k = k_factor(ae)
    d = d_factor(partitions)
    c = c_factor(ae, lay.height_mm, lay.width_mm, lay.depth_mm)
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
    dt_mid = k * d * p_total ** x if p_total > 0 else 0.0
    dt_top = c * dt_mid
    if not lay.params.get("depth_mm"):
        notes.append("hloubka skříně nezadána – počítáno 150 mm")
    if not any(e.attrs.get("p_loss_w") for e in sheet.elements):
        notes.append("ztráty přístrojů odhadnuty z In (doplňte p_loss_w z katalogů pro přesnější výsledek)")
    return ThermalResult(round(p_dev, 1), round(p_total, 1), round(ae, 3), round(dt_mid, 1), round(dt_top, 1),
                         rdf, t_ambient_c, notes, k=round(k, 4), c=round(c, 3), d=d, x=x)
