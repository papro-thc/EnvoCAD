"""Odhad oteplení rozvaděče (ČSN EN 61439-1 čl. 10.10.4.3 – ověření výpočtem dle IEC/TR 60890). Bez Qt.

Postup (zjednodušený, konzervativní):
1. Ztrátový výkon přístrojů ΣPv – z atributu `p_loss_w` přístroje (údaj výrobce při In), jinak odhad
   podle typu a In; přepočet na skutečné zatížení faktorem RDF² (RDF = Ib/In, výchozí 0,8).
   K tomu přirážka na vnitřní vodiče a spoje (výchozí 15 %).
2. Účinná chladicí plocha skříně Ae = Σ(A0 · b) dle IEC 60890 tab. 3 (činitel b podle polohy stěny).
3. Oteplení uprostřed výšky Δt = k · d · Pv^x  (IEC 60890 čl. 5):
   x = 0,804 (Ae > 1,25 m²) / 0,715 (Ae ≤ 1,25 m²); k ≈ konstanta skříně z Ae (aproximace křivek
   pro skříně bez ventilace); d = činitel přepážek (1 bez přepážek).
   Oteplení v horní části ≈ 1,35 · Δt0,5 (činitel c pro g = h/š ≈ 1,5–2 bez ventilace).

Výsledek je orientační – pro průkaz dle normy použijte údaje výrobce skříně (Rittal Therm, Hager, Schrack…).
"""
from __future__ import annotations

from dataclasses import dataclass

from envocad.model.project import Element, Sheet

# Odhad ztrátového výkonu na pól při In [W/A] – orientační střední hodnoty z katalogů (MCB/MCCB/RCD)
LOSS_PER_A_PER_POLE = {
    "fve.breaker_mcb": 0.09, "sb.rcbo": 0.11, "sb.rcd": 0.04, "fve.breaker_mccb": 0.06,
    "sb.main_switch": 0.03, "fve.switch_disconnector": 0.03, "fve.dc_disconnect": 0.03,
    "fve.contactor": 0.08, "fve.fuse": 0.12, "fve.meter": 0.0,
}
FIXED_LOSS_W = {"fve.spd": 0.5, "fve.meter": 2.0, "fve.contactor": 2.5, "fve.transformer": 0.0}  # cívky, elektronika

# IEC 60890 tab. 3 – činitel b pro plochy skříně podle montáže
B_FACTORS = {
    # (horní, spodní, přední, zadní, boky)
    "volně stojící": (1.4, 0.0, 0.9, 0.9, 0.9),
    "nástěnná": (1.4, 0.0, 0.9, 0.0, 0.9),
    "zapuštěná": (0.7, 0.0, 0.9, 0.0, 0.0),
    "stojanová": (1.4, 0.0, 0.9, 0.9, 0.9),
}
K_PLASTIC_PENALTY = 1.15  # plastová skříň odvádí teplo hůř než lakovaná ocel


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

    @property
    def t_top_c(self) -> float:
        return self.t_ambient_c + self.dt_top_k

    def verdict(self, limit_k: float = 70.0) -> str:
        """Mez dle ČSN EN 61439-1 tab. 6: svorky pro vnější vodiče 70 K, přístupné kryty 30/40 K…"""
        if self.dt_top_k <= 30:
            return "vyhovuje"
        if self.dt_top_k <= 50:
            return "vyhovuje s rezervou pro přístroje (ověřit odvození tepla u snížených In)"
        return "NEVYHOVUJE – zvětšit skříň, snížit zatížení nebo doplnit ventilaci"


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
    """Účinná chladicí plocha Ae [m²] dle IEC 60890 (plochy × činitel b)."""
    w, h, d = width_mm / 1000, height_mm / 1000, max(depth_mm, 150) / 1000
    key = next((k for k in B_FACTORS if k in (mounting or "").lower()), "nástěnná")
    b_top, b_bottom, b_front, b_back, b_side = B_FACTORS[key]
    return (w * d) * b_top + (w * d) * b_bottom + (w * h) * b_front + (w * h) * b_back + 2 * (h * d) * b_side


def _k_factor(ae: float) -> float:
    """Konstanta skříně k (IEC 60890 obr. 3/5, skříň bez ventilace) – aproximace křivky."""
    if ae <= 0:
        return 10.0
    if ae <= 1.25:
        return max(0.4, 2.2 * ae ** -0.9)
    return max(0.1, 0.9 * ae ** -0.8)


def temperature_rise(sheet: Sheet, rdf: float = 0.8, t_ambient_c: float = 35.0, wiring_pct: float = 15.0,
                     partitions: int = 0) -> ThermalResult:
    lay = sheet.layout
    notes: list[str] = []
    p_dev = 0.0
    for e in sheet.elements:
        p = device_power_loss(e, rdf)
        if p:
            p_dev += p
    p_total = p_dev * (1 + wiring_pct / 100)
    ae = cooling_area(lay.width_mm, lay.height_mm, lay.depth_mm, lay.params.get("mounting", "nástěnná"))
    if "plast" in (lay.params.get("material", "") or "").lower():
        ae /= K_PLASTIC_PENALTY
        notes.append("plastová skříň – chladicí plocha snížena o 15 %")
    x = 0.804 if ae > 1.25 else 0.715
    d = 1.0 + 0.1 * partitions
    k = _k_factor(ae)
    dt_mid = k * d * p_total ** x if p_total > 0 else 0.0
    dt_top = 1.35 * dt_mid
    if not lay.params.get("depth_mm"):
        notes.append("hloubka skříně nezadána – počítáno 150 mm")
    if not any(e.attrs.get("p_loss_w") for e in sheet.elements):
        notes.append("ztráty přístrojů odhadnuty z In (doplňte p_loss_w z katalogů pro přesnější výsledek)")
    return ThermalResult(round(p_dev, 1), round(p_total, 1), round(ae, 3), round(dt_mid, 1), round(dt_top, 1),
                         rdf, t_ambient_c, notes)
