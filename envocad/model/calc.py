"""Výpočty z modelu (bez Qt): stringy vs. střídač, proud a úbytek napětí na kabelech, zatížitelnost Iz
dle ČSN 33 2000-5-52 (zjednodušené tabulky), soulad jištění s kabelem (In ≤ Iz) a základní selektivita.

Hodnoty Iz jsou tabulky A.52 pro Cu/PVC 70 °C při 30 °C okolí (B.52.x) – přepsané z normy, označené
„orientační“: pro průkaz použijte normu. Výsledky jdou do kontroly projektu (F7) a do výkazu „Výpočty“.

Tabulky Iz, činitele a teplotní činitel lze lokálně přepsat souborem `~/.envocad/norms/*.json`
(`model/norm_tables.py`, formát v `docs/NORMY_FORMAT.md`); funkce je berou z `norm_tables.current()`, nebo z
parametru `tables=`. Konstanty níže jsou vestavěné hodnoty (bez souborů se počítá přesně s nimi).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field, replace

from envocad.model import norm_tables
from envocad.model.feed import FEED_SYMBOL, is_feed
from envocad.model.notes import plural
from envocad.model.project import INTERRUPT_SYMBOL, Element, Project, Sheet, Wire

RHO_CU, RHO_AL = 0.0225, 0.036      # Ω·mm²/m při provozní teplotě ~70 °C (orientační)
T_MIN_DEFAULT, T_MAX_DEFAULT = -10.0, 70.0  # °C: nejnižší okolí (Uoc), teplota článku při plném slunci (Umpp)
# – výchozí, když projekt nemá návrhové teploty v `meta["pv_t_min"]` / `meta["pv_t_max"]` (`design_temperatures`)
BETA_VOC_DEFAULT = -0.27            # %/K (krystalický Si; z datasheetu modulu `beta_voc`)
DC_INPUTS_PER_MPPT_DEFAULT = 2      # vstupů na MPPT, když střídač `strings_per_mppt` nemá – jen pro počet DC vstupů
#                                     (generátor, `inverter_dc_inputs`), ne pro sčítání proudů stringů na MPPT
SAFETY_ISC = 1.25                   # ČSN 33 2000-7-712: dimenzování DC na 1,25·Isc
SELECTIVITY_RATIO = 1.6             # orientační poměr In pro selektivitu MCB–MCB v přetížení
# režim stringu (atribut střídače `string_mode`, prázdné = classic) – docs/design/optimizery.md
STRING_MODES = ("classic", "optimizer", "fixed_voltage")

# Iz [A] Cu, PVC 70 °C, 30 °C okolí, 3 zatížené vodiče – ČSN 33 2000-5-52 tab. B.52.4/B.52.5 (ORIENTAČNÍ)
IZ_3 = {
    "A1": {1.5: 13.5, 2.5: 18, 4: 24, 6: 31, 10: 42, 16: 56, 25: 73, 35: 89, 50: 108, 70: 136, 95: 164, 120: 188,
           150: 216, 185: 245, 240: 286},
    "B1": {1.5: 15.5, 2.5: 21, 4: 28, 6: 36, 10: 50, 16: 68, 25: 89, 35: 110, 50: 134, 70: 171, 95: 207, 120: 239,
           150: 262, 185: 296, 240: 346},
    "C": {1.5: 17.5, 2.5: 24, 4: 32, 6: 41, 10: 57, 16: 76, 25: 96, 35: 119, 50: 144, 70: 184, 95: 223, 120: 259,
          150: 299, 185: 341, 240: 403},
    "D": {1.5: 18, 2.5: 24, 4: 30, 6: 38, 10: 50, 16: 64, 25: 82, 35: 98, 50: 116, 70: 143, 95: 169, 120: 192,
          150: 217, 185: 243, 240: 280},
    "E": {1.5: 22, 2.5: 30, 4: 40, 6: 51, 10: 70, 16: 94, 25: 119, 35: 148, 50: 180, 70: 232, 95: 282, 120: 328,
          150: 379, 185: 434, 240: 514},
}
IZ_2_FACTOR = 1.10   # 2 zatížené vodiče (1f, DC) ≈ +10 % (orientační)
AL_FACTOR = 0.78     # Al vodiče
# teplotní činitel (tab. B.52.14 pro PVC, orientační): 30 °C 1,0; 35 °C 0,94; 40 °C 0,87; 45 °C 0,79; 50 °C 0,71
K_T_PVC_AIR = {30: 1.0, 35: 0.94, 40: 0.87, 45: 0.79, 50: 0.71}
METHOD_HINTS = [("zem", "D"), ("výkop", "D"), ("vzduch", "E"), ("lávk", "E"), ("rošt", "E"), ("žlab", "E"),
                ("trubk", "B1"), ("lišt", "B1"), ("chránič", "B1"), ("zatepl", "A1"), ("izolac", "A1"),
                ("stěn", "C"), ("omítk", "C"), ("příchytk", "C")]


def _f(v, default: float | None = None) -> float | None:
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return default


def _num_cz(x: float) -> str:
    """1.6 → „1,6“ (česká desetinná čárka v hláškách)."""
    return f"{x:g}".replace(".", ",")


def route_method(w: Wire, tables: norm_tables.NormTables | None = None) -> str:
    t = tables if tables is not None else norm_tables.current()
    m = (w.attrs.get("method") or "").strip().upper()
    if m in t.iz3:
        return m
    text = (w.attrs.get("route") or "").lower()
    for key, meth in METHOD_HINTS:
        if key in text:
            return meth
    return "C"


def ampacity(cross: float, method: str = "C", loaded: int = 3, aluminium: bool = False, t_ambient: float = 30.0,
             grouping: float = 1.0, tables: norm_tables.NormTables | None = None) -> float | None:
    """Zatížitelnost Iz [A]; `tables` = normové tabulky (None = `norm_tables.current()`)."""
    t = tables if tables is not None else norm_tables.current()
    table = t.iz3.get(method, t.iz3["C"])
    sizes = sorted(table)
    size = next((s for s in sizes if s >= cross - 1e-6), None)
    if size is None:
        return None
    iz = table[size]
    if size != cross:  # průřez mimo řadu: lineární odhad
        iz = iz * cross / size
    if loaded <= 2:
        iz *= t.iz2_factor
    if aluminium:
        iz *= t.al_factor
    # teplotní činitel: zaokrouhleno na 5 °C, bez interpolace; chybí-li klíč: 1,0 pro t ≤ 30 °C, jinak hodnota
    # u nejvyšší teploty tabulky
    k_t = t.k_t_pvc_air
    kt = k_t.get(int(round(t_ambient / 5) * 5), 1.0 if t_ambient <= 30 else k_t[max(k_t)])
    return round(iz * kt * grouping, 1)


def min_cross(in_a: float, method: str = "C", loaded: int = 3, aluminium: bool = False,
              t_ambient: float = 30.0, tables: norm_tables.NormTables | None = None) -> float | None:
    """Nejmenší průřez z tabulky Iz (`IZ_3`, způsob uložení `method`), jehož zatížitelnost (`ampacity`) je ≥ `in_a`
    (In jisticího přístroje kabelu, ČSN 33 2000-4-43: In ≤ Iz). Nic nevyhoví (nad 240 mm²) nebo neplatné In → None –
    průřez se pak nedosazuje (prázdný = nález F7)."""
    if not in_a or in_a <= 0:
        return None
    t = tables if tables is not None else norm_tables.current()
    for cross in sorted(t.iz3.get(method, t.iz3["C"])):
        iz = ampacity(cross, method, loaded, aluminium, t_ambient, tables=t)
        if iz is not None and iz >= in_a - 1e-9:
            return float(cross)
    return None


def voltage_drop(i_a: float, length_m: float, cross: float, system: str, u_v: float, aluminium: bool = False,
                 cos_phi: float = 1.0) -> tuple[float, float]:
    """ΔU [V] a [%]; system = '3f' | '1f' | 'dc' (jen činná složka – orientační)."""
    rho = RHO_AL if aluminium else RHO_CU
    r = rho * length_m / cross
    if system == "3f":
        du = 3 ** 0.5 * i_a * r * cos_phi
    else:
        du = 2 * i_a * r * cos_phi
    return round(du, 2), round(100 * du / u_v, 2) if u_v else 0.0


# ---- stringy: data modulu a střídače, meze, hlášky (sdílí průvodce i kontrola F7) -----------------------------
@dataclass(frozen=True)
class ModuleData:
    """FV modul pro výpočet stringů (STC): Voc, Vmp, Isc [V, A], Imp, β_Voc [%/K], max. napětí systému, Pmax [Wp],
    α_Isc a γ_Pmax [%/K] (z artiklu; oba zadané → teplotní součinitel Umpp = γ_Pmax − α_Isc, jinak β_Voc)."""
    voc: float
    vmp: float
    isc: float
    imp: float | None = None
    beta_voc: float = BETA_VOC_DEFAULT
    u_sys_max: float | None = None
    p_wp: float | None = None
    alpha_isc: float | None = None
    gamma_pmax: float | None = None
    component_id: str = ""   # artikl modulu (jen pro porovnání paralelních stringů, `parallel_issues`)

    @classmethod
    def from_attrs(cls, a: dict) -> ModuleData | None:
        """Z atributů prvku `fve.pv_string` (nebo `Component.attr_values()` artiklu modulu); bez Uoc → None.
        Chybějící Vmp = 0,82·Voc, Isc = 0, β = `BETA_VOC_DEFAULT` (jako dosud v kontrole stringů)."""
        voc = _f(a.get("voc"))
        if not voc or voc <= 0:
            return None
        return cls(voc=voc, vmp=_f(a.get("vmp")) or voc * 0.82, isc=_f(a.get("isc")) or 0.0, imp=_f(a.get("imp")),
                   beta_voc=_f(a.get("beta_voc")) or BETA_VOC_DEFAULT, u_sys_max=_f(a.get("u_sys_max")),
                   p_wp=_f(a.get("p_module")), alpha_isc=_f(a.get("alpha_isc")), gamma_pmax=_f(a.get("gamma_pmax")))

    @property
    def vmp_from_beta(self) -> bool:
        """Umpp(t) se počítá z β_Voc (zjednodušení) – modul nemá zadané γ_Pmax i α_Isc."""
        return self.gamma_pmax is None or self.alpha_isc is None

    @property
    def vmp_coeff(self) -> float:
        """Teplotní součinitel Umpp [%/K]: γ_Pmax − α_Isc (Pmpp = Umpp·Impp, Impp roste zhruba jako Isc), jinak β_Voc."""
        return self.beta_voc if self.vmp_from_beta else self.gamma_pmax - self.alpha_isc

    def uoc(self, t: float) -> float:
        """Uoc jednoho modulu při teplotě t [°C]: Voc·(1 + β/100·(t − 25))."""
        return self.voc * (1 + self.beta_voc / 100.0 * (t - 25))

    def ump(self, t: float) -> float:
        """Umpp jednoho modulu při teplotě t [°C]: Vmp·(1 + k/100·(t − 25)), k = `vmp_coeff`."""
        return self.vmp * (1 + self.vmp_coeff / 100.0 * (t - 25))


@dataclass(frozen=True)
class InverterData:
    """Střídač pro výpočet stringů: Umax DC, okno MPPT [V], Imax a Isc max na MPPT [A], počet MPPT, stringů na MPPT,
    P AC [kW], P DC max [kWp]. Neznámé = None (příslušná kontrola se přeskočí; neznámé stringů na MPPT = MPPT
    stringu se nezjišťuje a proudy paralelních stringů se nesčítají)."""
    u_dc_max: float | None = None
    u_mppt_min: float | None = None
    u_mppt_max: float | None = None
    i_mppt_max: float | None = None
    isc_mppt_max: float | None = None
    mppt: int | None = None
    strings_per_mppt: int | None = None
    p_ac: float | None = None
    p_dc_max: float | None = None
    string_mode: str = "classic"      # atribut `string_mode` tak, jak je (prázdné = classic); platný režim = `mode`
    u_string: float | None = None     # pevné napětí stringu [V] (fixed_voltage, jen informativně / věrohodnost)
    n_opt_min: int | None = None      # optimizérů ve stringu min / max (optimizer, fixed_voltage)
    n_opt_max: int | None = None
    p_string_max: float | None = None  # max. výkon stringu [W] (optimizer, fixed_voltage)
    manufacturer: str = ""            # výrobce (kompatibilita optimizéru)

    @classmethod
    def from_attrs(cls, a: dict) -> InverterData:
        """Z atributů prvku `fve.inverter*` (nebo `Component.attr_values()` artiklu střídače)."""
        mppt = _f(a.get("mppt"))
        spm = _f(a.get("strings_per_mppt"))
        return cls(u_dc_max=_f(a.get("u_dc_max")), u_mppt_min=_f(a.get("u_mppt_min")),
                   u_mppt_max=_f(a.get("u_mppt_max")), i_mppt_max=_f(a.get("i_mppt_max")),
                   isc_mppt_max=_f(a.get("isc_mppt_max")), mppt=int(mppt) if mppt and mppt >= 1 else None,
                   strings_per_mppt=int(spm) if spm and spm >= 1 else None, p_ac=_f(a.get("p_ac")),
                   p_dc_max=_f(a.get("p_dc_max")),
                   string_mode=str(a.get("string_mode") or "").strip() or "classic", u_string=_f(a.get("u_string")),
                   n_opt_min=_int(a.get("n_opt_min")), n_opt_max=_int(a.get("n_opt_max")),
                   p_string_max=_f(a.get("p_string_max")), manufacturer=str(a.get("manufacturer") or "").strip())

    @property
    def mode(self) -> str:
        """Platný režim stringu: `string_mode` z `STRING_MODES`, neznámá hodnota → classic (`string_issues` varuje)."""
        return self.string_mode if self.string_mode in STRING_MODES else "classic"


def _int(v) -> int | None:
    """Kladné celé číslo z atributu („14“, „14.0“), jinak None."""
    x = _f(v)
    return int(x) if x is not None and x >= 1 and float(x).is_integer() else None


@dataclass(frozen=True)
class OptimizerData:
    """Optimizér stringu (z atributů `opt_*` stringu, viz `Component.optimizer_values`): P max vstupu [W], U max vstupu
    [V], Isc max vstupu [A], modulů na optimizér (1 | 2), tolerance P dle výrobce [%], U MPPT min [V], I max a U max
    výstupu, smíšení s neoptimalizovanými moduly dovoleno, typ, výrobce, kompatibilita („SolarEdge“, „*“) a pravidla
    stringu z listu optimizéru pro fázi střídače (n_min, n_max optimizérů, P stringu max [W]), U MPPT max vstupu [V].

    Předpoklad při 2 modulech na optimizér: oba moduly jsou na vstupu optimizéru zapojené **sériově** (dvojitý vstup
    sériově, např. SolarEdge P850/P1100) – napětí vstupu = 2 · napětí modulu, proud = proud jednoho modulu (Isc se
    nesčítá), výkon = 2 · P modulu. Paralelní dvojvstup by vyžadoval jiný výpočet (zatím nepodporováno)."""
    p_max: float
    u_in_max: float
    isc_in_max: float | None
    modules: int = 1
    p_tol_pct: float = 0.0
    u_mppt_min: float | None = None
    i_out_max: float | None = None
    u_out_max: float | None = None
    partial_ok: bool = False
    name: str = ""
    manufacturer: str = ""
    compat: str = ""
    n_min: int | None = None
    n_max: int | None = None
    p_string_max: float | None = None
    u_mppt_max: float | None = None
    bad_modules: str = ""    # neplatná hodnota `opt_modules` (ne 1 ani 2) – počítá se s 1, `optimizer_issues` varuje

    @classmethod
    def from_attrs(cls, a: dict) -> OptimizerData | None:
        """Z atributů stringu; bez `opt_p_max` nebo `opt_u_in_max` → None (optimizér bez parametrů). Neplatný počet
        modulů na optimizér (`opt_modules` vyplněné, ale ne 1 ani 2) → počítá se s 1 a `bad_modules` = zadaná hodnota."""
        p_max, u_in = _f(a.get("opt_p_max")), _f(a.get("opt_u_in_max"))
        if not p_max or not u_in or p_max <= 0 or u_in <= 0:
            return None
        raw = str(a.get("opt_modules") or "").strip()
        mpo = _int(raw)
        bad = raw if raw and mpo not in (1, 2) else ""
        return cls(p_max=p_max, u_in_max=u_in, isc_in_max=_f(a.get("opt_isc_in_max")),
                   modules=mpo if mpo in (1, 2) else 1, bad_modules=bad, u_mppt_max=_f(a.get("opt_u_mppt_max")),
                   p_tol_pct=_f(a.get("opt_p_tol")) or 0.0, u_mppt_min=_f(a.get("opt_u_mppt_min")),
                   i_out_max=_f(a.get("opt_i_out_max")), u_out_max=_f(a.get("opt_u_out_max")),
                   partial_ok=str(a.get("opt_partial") or "").strip() in ("1", "1.0", "true", "ano"),
                   name=str(a.get("optimizer") or "").strip(), manufacturer=str(a.get("opt_manufacturer") or "").strip(),
                   compat=str(a.get("opt_compat") or "").strip(), n_min=_int(a.get("opt_n_min")),
                   n_max=_int(a.get("opt_n_max")), p_string_max=_f(a.get("opt_p_string_max")))

    def compatible_with(self, manufacturer: str) -> bool | None:
        """Kompatibilita se střídačem výrobce `manufacturer` podle `compat` (položky oddělené , ; /; „*“ = libovolný;
        shoda prvního slova bez ohledu na velikost písmen). Neznámý výrobce nebo prázdné `compat` → None."""
        man = (manufacturer or "").strip().lower().split()
        entries = [x.strip().lower() for x in re.split(r"[,;/|]", self.compat) if x.strip()]
        if not man or not entries:
            return None
        return any(x == "*" or x.split()[0] == man[0] for x in entries)


@dataclass
class StringLimits:
    """Meze stringu pro dvojici modul + střídač: počet modulů ve stringu n_min…n_max (None = bez horní meze – chybí
    Umax i MPPT max), nejvýš n_par_max paralelních stringů na jeden MPPT; `reasons` = české důvody pro průvodce."""
    n_min: int
    n_max: int | None
    n_par_max: int
    reasons: list[str] = field(default_factory=list)
    step: int = 1                              # délky stringu po násobcích step (modulů na optimizér; `propose_strings`)
    n_opt: tuple[int | None, int | None] | None = None   # rozmezí počtu optimizérů (optimizer, fixed_voltage)
    mode: str = "classic"                      # platný režim stringu (`InverterData.mode`)

    @property
    def ok(self) -> bool:
        """Existuje aspoň jeden přípustný počet modulů a aspoň jeden string na MPPT."""
        return self.n_par_max >= 1 and (self.n_max is None or self.n_min <= self.n_max)


def parse_temperature(v) -> float | None:
    """Teplota [°C] z textu: desetinná čárka i tečka, typografické minus „−“ (i pomlčka „–“), přípona „°C“ / „°“ / „C“
    a mezery se tolerují („−20 °C“ → −20.0). Prázdné nebo neplatné → None."""
    if v is None:
        return None
    t = str(v).strip().replace("\u2212", "-").replace("\u2013", "-").replace("\u00a0", " ")
    t = re.sub(r"\s*(°\s*C?|C)\s*$", "", t, flags=re.IGNORECASE)
    t = t.replace(" ", "").replace(",", ".")
    if not t:
        return None
    try:
        x = float(t)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


DESIGN_TEMPERATURE_KEYS = (("pv_t_min", "min", T_MIN_DEFAULT), ("pv_t_max", "max", T_MAX_DEFAULT))


def design_temperatures(project: Project) -> tuple[float, float]:
    """Návrhové teploty pro stringy (t_min pro Uoc, t_max pro Umpp) z `meta["pv_t_min"]` / `meta["pv_t_max"]`
    (Vlastnosti projektu, průvodce; text se normalizuje `parse_temperature`), jinak `T_MIN_DEFAULT` / `T_MAX_DEFAULT`."""
    meta = getattr(project, "meta", None) or {}
    t_min, t_max = (parse_temperature(meta.get(key)) for key, _lab, _d in DESIGN_TEMPERATURE_KEYS)
    return (T_MIN_DEFAULT if t_min is None else t_min, T_MAX_DEFAULT if t_max is None else t_max)


def design_temperature_issues(project: Project) -> list[str]:
    """Hlášky k neplatným návrhovým teplotám v meta (vyplněné, ale ne číslo) – počítá se pak s výchozí hodnotou."""
    meta = getattr(project, "meta", None) or {}
    out = []
    for key, lab, default in DESIGN_TEMPERATURE_KEYS:
        raw = str(meta.get(key) or "").strip()
        if raw and parse_temperature(raw) is None:
            out.append(f"Návrhová teplota {lab} „{raw}“ není číslo – počítá se s {default:g} °C")
    return out


def _u_strings(m: ModuleData, n: int, t_min: float, t_max: float) -> tuple[float, float, float]:
    """(Uoc za studena, Umpp za tepla, Umpp za studena) stringu n modulů, zaokrouhleno na 0,1 V jako ve výkazech."""
    beta, kv = m.beta_voc / 100.0, m.vmp_coeff / 100.0
    return (round(n * m.voc * (1 + beta * (t_min - 25)), 1), round(n * m.vmp * (1 + kv * (t_max - 25)), 1),
            round(n * m.vmp * (1 + kv * (t_min - 25)), 1))


def _voltage_issues(m: ModuleData, inv: InverterData | None, n: int, t_min: float, t_max: float,
                    uoc: float | None = None) -> list[str]:
    """Napětí stringu proti střídači a modulu; `uoc` = Uoc stringu za studena, je-li jiné než n·Uoc(t_min) (režim
    optimizer s U max výstupu optimizéru, `_uoc_capped`)."""
    uoc_cold, umpp_hot, umpp_cold = _u_strings(m, n, t_min, t_max)
    if uoc is not None:
        uoc_cold = uoc
    out = []
    if inv is not None and inv.u_dc_max and uoc_cold > inv.u_dc_max:
        out.append(f"Uoc při {t_min:g} °C {uoc_cold} V > Umax střídače {inv.u_dc_max:g} V")
    if m.u_sys_max and uoc_cold > m.u_sys_max:
        out.append(f"Uoc při {t_min:g} °C {uoc_cold} V > Umax systému modulu {m.u_sys_max:g} V")
    if inv is not None:
        if inv.u_mppt_min and umpp_hot and umpp_hot < inv.u_mppt_min:
            out.append(f"Umpp při {t_max:g} °C {umpp_hot} V < Umppt min {inv.u_mppt_min:g} V")
        if inv.u_mppt_max and umpp_cold and umpp_cold > inv.u_mppt_max:
            out.append(f"Umpp při {t_min:g} °C {umpp_cold} V > Umppt max {inv.u_mppt_max:g} V (mimo rozsah sledování)")
    return out


def _current_issues(m: ModuleData, inv: InverterData, n_par: int) -> list[str]:
    """Proud na MPPT. Se `isc_mppt_max`: n_par·Isc > Isc max = chyba, n_par·Imp > Imax = varování (omezení výkonu).
    Bez něj dosavadní pravidlo: 1,25·Isc jednoho stringu proti Imax vstupu (staré projekty beze změny)."""
    out = []
    isc = m.isc
    if inv.isc_mppt_max:
        n_par = max(1, n_par)
        if isc and n_par * isc > inv.isc_mppt_max:
            out.append(f"Isc {n_par}× {isc:g} A = {n_par * isc:.1f} A > Isc max MPPT {inv.isc_mppt_max:g} A")
        if m.imp and inv.i_mppt_max and n_par * m.imp > inv.i_mppt_max:
            out.append(f"Impp {n_par}× {m.imp:g} A = {n_par * m.imp:.1f} A > Imax MPPT {inv.i_mppt_max:g} A "
                       "– omezení výkonu")
    elif inv.i_mppt_max and isc and SAFETY_ISC * isc > inv.i_mppt_max:
        out.append(f"1,25·Isc {SAFETY_ISC * isc:.1f} A > Imax vstupu {inv.i_mppt_max:g} A")
    return out


# ---- optimizéry a režimy stringu (docs/design/optimizery.md) ---------------------------------------------------
# Závažnost hlášek stringu: jediné místo pro F7 (`checks.calc_findings`) i barvu v asistentu průvodce. Varování jsou
# vyjmenovaná šablonami (celé znění, `re.fullmatch`) – každá šablona odpovídá jedné varovné hlášce níže; cokoli jiného
# (i nová, dosud nezařazená hláška) je chyba. Pevné texty jsou konstanty, aby se šablona a hláška nerozešly.
MSG_NO_MODULES = "chybí počet modulů nebo Uoc modulu"
MSG_NO_INVERTER = "string není propojen se střídačem"
MSG_INV_NO_LIMITS = "střídač nemá zadané Umax / rozsah MPPT (doplňte z artiklu)"
MSG_OPT_NO_PARAMS = "optimizér bez parametrů (doplňte z katalogu)"
MSG_NO_OPTIMIZERS = "string nemá optimizéry (režim stringů s optimizéry)"
MSG_PARALLEL_MODULES = "různé moduly stringů na MPPT"
MSG_DC_DEVICES = "Uoc {u} V při {t} °C > Un DC přístrojů {devices}"   # devices: „EFH 10 DC 2p 1000 V, …“
POWER_LIMIT_SUFFIX = " – omezení výkonu"     # přípona varování „omezení výkonu“ (proud MPPT, okno MPPT optimizéru)
_WARNING_TEMPLATES = (
    re.escape(MSG_NO_MODULES),
    re.escape(MSG_NO_INVERTER),
    re.escape(MSG_INV_NO_LIMITS),
    re.escape(MSG_OPT_NO_PARAMS),
    re.escape(MSG_NO_OPTIMIZERS),
    re.escape(MSG_PARALLEL_MODULES),
    r"neznámý režim stringu „.*“ – počítá se klasicky",
    r".+" + re.escape(POWER_LIMIT_SUFFIX),
    r"chybí údaj .+",
    r"P .+ > P max optimizéru .+ – v toleranci výrobce .+",
    r"optimizér .* není uveden jako kompatibilní se střídačem .*",
    r"neplatný počet modulů na optimizér „.*“ .*",
    r"nestejná délka stringů na MPPT \(.+\)",
    r"různá orientace stringů na MPPT \(.+\)",
)
WARNING_PATTERNS = tuple(re.compile(p, re.DOTALL) for p in _WARNING_TEMPLATES)


def is_warning(msg: str) -> bool:
    """Hláška stringu (`string_issues`, `parallel_issues`, `capacity_issue`) je jen varování (chybějící údaj, omezení
    výkonu, tolerance výrobce, nestejné paralelní stringy, neznámý režim…) – celé znění odpovídá šabloně
    z `WARNING_PATTERNS`; jinak chyba."""
    return any(p.fullmatch(msg) for p in WARNING_PATTERNS)


def _unit_label(mpo: int) -> str:
    return "modulu" if mpo == 1 else f"{mpo} modulů"


def _optimizers(n: int) -> str:
    return f"{n} {plural(n, 'optimizér', 'optimizéry', 'optimizérů')}"


def optimizer_issues(m: ModuleData, opt: OptimizerData, t_min: float = T_MIN_DEFAULT, t_max: float = T_MAX_DEFAULT,
                     inverter_manufacturer: str = "") -> list[str]:
    """Vstup optimizéru (všechny režimy): mpo·Uoc(t_min) > U max vstupu → chyba; Isc STC modulu (bez 1,25 –
    limit výrobce je vztažen k Isc modulu) > Isc max vstupu → chyba; mpo·P modulu > P max·(1 + tolerance) → chyba,
    nad P max v toleranci výrobce → varování; mpo·Umpp(t_max) < U MPPT min → varování (omezení výkonu); `compat`
    neodpovídá výrobci střídače → varování. Chybějící Isc max vstupu → varování „chybí údaj“. mpo·Umpp(t_min) > U MPPT
    max optimizéru → varování (omezení výkonu). Neplatný počet modulů na optimizér (`bad_modules`) → varování, počítá
    se s 1. Při mpo = 2 se předpokládá sériové zapojení modulů na vstupu (viz `OptimizerData`)."""
    out = []
    if opt.bad_modules:
        out.append(f"neplatný počet modulů na optimizér „{opt.bad_modules}“ (povoleno 1 nebo 2) – počítá se s 1")
    mpo = opt.modules
    unit = _unit_label(mpo)
    if m.voc:
        u = round(mpo * m.uoc(t_min), 1)
        if u > opt.u_in_max:
            out.append(f"Uoc {unit} při {t_min:g} °C {u} V > Uin max optimizéru {opt.u_in_max:g} V")
        if opt.u_mppt_min and m.vmp:
            ump = round(mpo * m.ump(t_max), 1)
            if ump < opt.u_mppt_min:
                out.append(f"Umpp {unit} při {t_max:g} °C {ump} V < Umppt min optimizéru {opt.u_mppt_min:g} V"
                           + POWER_LIMIT_SUFFIX)
        if opt.u_mppt_max and m.vmp:
            ump = round(mpo * m.ump(t_min), 1)
            if ump > opt.u_mppt_max:
                out.append(f"Umpp {unit} při {t_min:g} °C {ump} V > Umppt max optimizéru {opt.u_mppt_max:g} V"
                           + POWER_LIMIT_SUFFIX)
    if opt.isc_in_max is None:
        out.append("chybí údaj Isc max vstupu optimizéru")
    elif m.isc and m.isc > opt.isc_in_max:
        out.append(f"Isc modulu {m.isc:g} A > Isc max vstupu optimizéru {opt.isc_in_max:g} A")
    if m.p_wp:
        p = mpo * m.p_wp
        if p > opt.p_max * (1 + opt.p_tol_pct / 100.0) + 1e-9:
            tol = f" + {opt.p_tol_pct:g} %" if opt.p_tol_pct else ""
            out.append(f"P {unit} {p:g} W > P max optimizéru {opt.p_max:g} W{tol}")
        elif p > opt.p_max:
            out.append(f"P {unit} {p:g} W > P max optimizéru {opt.p_max:g} W – v toleranci výrobce {opt.p_tol_pct:g} %")
    if opt.compatible_with(inverter_manufacturer) is False:
        out.append(f"optimizér {opt.name or '?'} není uveden jako kompatibilní se střídačem {inverter_manufacturer} "
                   f"(kompatibilita: {opt.compat})")
    return out


def optimizer_rules(inv: InverterData | None, opt: OptimizerData | None) -> tuple[int | None, int | None, float | None]:
    """Nejpřísnější známá pravidla stringu ze střídače a optimizéru: (n_opt min = max, n_opt max = min, P stringu max
    [W] = min); neznámé = None."""
    lo = [x for x in (inv.n_opt_min if inv else None, opt.n_min if opt else None) if x]
    hi = [x for x in (inv.n_opt_max if inv else None, opt.n_max if opt else None) if x]
    pm = [x for x in (inv.p_string_max if inv else None, opt.p_string_max if opt else None) if x]
    return (max(lo) if lo else None, min(hi) if hi else None, min(pm) if pm else None)


def _uoc_capped(m: ModuleData, n: int, t_min: float, opt: OptimizerData | None, n_opt: int | None) -> float | None:
    """Uoc stringu za studena v režimu optimizer, má-li optimizér U max výstupu: optimalizovaná jednotka přispívá
    min(mpo·Uoc(t_min), U max výstupu), moduly bez optimizéru Uoc(t_min). Jinak None (počítá se n·Uoc)."""
    if opt is None or not opt.u_out_max or not n:
        return None
    mpo, u1 = opt.modules, m.uoc(t_min)
    optimized = min(n, (n_opt if n_opt is not None else math.ceil(n / mpo)) * mpo)
    full, rest = divmod(optimized, mpo)
    u = full * min(mpo * u1, opt.u_out_max) + min(rest * u1, opt.u_out_max) + (n - optimized) * u1
    return round(u, 1)


def _assumed_mpo(n: int, n_opt: int | None) -> int:
    """Modulů na optimizér bez dat optimizéru (starý spec): z poměru modulů a optimizérů, 1 nebo 2."""
    if not n_opt or not n:
        return 1
    return 2 if n >= 2 * n_opt else 1


def _mode_issues(m: ModuleData, inv: InverterData, n: int, opt: OptimizerData | None, n_opt: int | None) -> list[str]:
    """Počet optimizérů a výkon stringu (režimy optimizer a fixed_voltage) + pevné napětí (fixed_voltage)."""
    out = []
    mode = inv.mode
    fixed = mode == "fixed_voltage"
    if fixed:
        if inv.u_string:
            if inv.u_dc_max and inv.u_string > inv.u_dc_max:
                out.append(f"pevné napětí stringu {inv.u_string:g} V > Umax střídače {inv.u_dc_max:g} V "
                           "– nevěrohodné údaje střídače")
        else:
            out.append("chybí údaj pevné napětí stringu střídače")
        # napětí stringu může dosáhnout až Umax střídače (regulace optimizérů) – Umax systému modulu proti
        # max(pevné napětí, Umax střídače) ze známých hodnot
        if m.u_sys_max:
            u_top = max((x for x in (inv.u_string, inv.u_dc_max) if x), default=None)
            if u_top and u_top > m.u_sys_max:
                what = ("pevné napětí stringu" if u_top == inv.u_string and not (inv.u_dc_max or 0) > inv.u_string
                        else "Umax střídače")
                out.append(f"{what} {u_top:g} V > Umax systému modulu {m.u_sys_max:g} V")
    mpo = opt.modules if opt is not None else _assumed_mpo(n, n_opt)
    if n_opt is None and opt is not None and n:
        n_opt = math.ceil(n / mpo)
    if opt is None:
        if n_opt:
            out.append(MSG_OPT_NO_PARAMS)
        elif fixed:
            out.append("pevné napětí: string bez optimizérů – optimizér musí být na každém modulu")
        else:
            out.append(MSG_NO_OPTIMIZERS)
    n_lo, n_hi, p_max = optimizer_rules(inv, opt)
    if n_opt:
        if n_lo and n_opt < n_lo:
            out.append(f"{_optimizers(n_opt)} ve stringu < min {n_lo}")
        if n_hi and n_opt > n_hi:
            out.append(f"{_optimizers(n_opt)} ve stringu > max {n_hi}")
    if fixed and (n_lo is None or n_hi is None):
        out.append("chybí údaj rozmezí počtu optimizérů ve stringu (doplňte z artiklu)")
    if p_max and m.p_wp and n and n * m.p_wp > p_max + 1e-9:
        out.append(f"P stringu {n * m.p_wp:g} W > max {p_max:g} W")
    if fixed and p_max is None:
        out.append("chybí údaj max. výkon stringu (doplňte z artiklu)")
    if fixed and n_opt and n != n_opt * mpo:
        out.append(f"{_modules(n)}, {_optimizers(n_opt)} × {mpo} – optimizér musí být na každém modulu")
    if mode == "optimizer" and opt is not None and n_opt is not None and n_opt * mpo < n and not opt.partial_ok:
        out.append(f"smíšení optimalizovaných a neoptimalizovaných modulů ({n_opt * mpo} z {n}) není dovoleno")
    return out


def string_issues(m: ModuleData, inv: InverterData | None, n: int, n_par: int = 1, t_min: float = T_MIN_DEFAULT,
                  t_max: float = T_MAX_DEFAULT, opt: OptimizerData | None = None,
                  n_opt: int | None = None, dc_devices=None) -> list[str]:
    """České hlášky ke stringu n modulů, n_par paralelních stringů na stejném MPPT (prázdný seznam = vyhovuje).
    Texty sdílí kontrola projektu (F7), výkaz Výpočty i asistent průvodce; závažnost určuje `is_warning`.
    Režim podle střídače (`InverterData.mode`): classic – napětí, okno MPPT, proudy; optimizer – navíc počet
    optimizérů, P stringu, smíšení a Uoc s U max výstupu optimizéru; fixed_voltage – místo Uoc·n, okna MPPT a proudů
    počet optimizérů, optimizér na každém modulu, P stringu a pevné napětí. `opt` (data optimizéru stringu) → kontrola
    vstupu optimizéru ve všech režimech; `n_opt` = počet optimizérů ve stringu (atribut `n_optimizers`).
    `dc_devices` = [(Un DC [V], popis)] přístrojů ve stringové cestě (`dc_system.path_devices` v průvodci,
    `string_device_limits` v projektu) – Uoc stringu nad Un kteréhokoli z nich je chyba (`MSG_DC_DEVICES`, všechny
    takové přístroje v jedné hlášce)."""
    out = []
    if not n or not m.voc:
        out.append(MSG_NO_MODULES)
    if inv is None:
        out.append(MSG_NO_INVERTER)
    mode = inv.mode if inv is not None else "classic"
    if inv is not None and inv.string_mode != mode:
        out.append(f"neznámý režim stringu „{inv.string_mode}“ – počítá se klasicky")
    if mode != "fixed_voltage":
        uoc = _uoc_capped(m, n, t_min, opt, n_opt) if mode == "optimizer" else None
        out += _voltage_issues(m, inv, n, t_min, t_max, uoc)
        if dc_devices and n and m.voc:
            u = uoc if uoc is not None else _u_strings(m, n, t_min, t_max)[0]
            under = sorted((d for d in dc_devices if u > d[0] + 1e-9), key=lambda d: d[0])
            if under:
                out.append(MSG_DC_DEVICES.format(u=_num_cz(u), t=_num_cz(t_min).replace("-", "−"),
                                                 devices=", ".join(dict.fromkeys(lab for _u, lab in under))))
        if inv is not None:
            out += _current_issues(m, inv, n_par)
            if not (inv.u_dc_max or inv.u_mppt_min):
                out.append(MSG_INV_NO_LIMITS)
    if opt is not None:
        out += optimizer_issues(m, opt, t_min, t_max, inv.manufacturer if inv is not None else "")
    if mode in ("optimizer", "fixed_voltage"):
        out += _mode_issues(m, inv, n, opt, n_opt)
    elif opt is None and n_opt:
        out.append(MSG_OPT_NO_PARAMS)
    return out


def _join_and(items: list) -> str:
    items = [str(x) for x in items]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " a " + items[-1]


def parallel_issues(members: list[tuple[int, ModuleData | None, str]]) -> list[str]:
    """Varování ke stringům na jednom MPPT (n modulů, modul, orientace): nestejná délka (s rozdílem Umpp STC), různé
    moduly (`component_id`, jinak Voc/Vmp/Isc), různá orientace (jen vyplněné). Jeden string → []."""
    out: list[str] = []
    if len(members) < 2:
        return out
    ns = sorted({n for n, _m, _o in members if n}, reverse=True)
    mods = [m for _n, m, _o in members if m is not None]
    if len(ns) > 1:
        umpp = [n * m.vmp for n, m, _o in members if n and m is not None and m.vmp]
        if len(umpp) == len(members) and max(umpp) > 0:
            d = 100 * (max(umpp) - min(umpp)) / max(umpp)
        else:
            d = 100 * (ns[0] - ns[-1]) / ns[0]
        out.append(f"nestejná délka stringů na MPPT ({_join_and(ns)} modulů, ΔUmpp {d:.0f} %)")
    by_id = all(m.component_id for m in mods)
    if len({m.component_id if by_id else (m.voc, m.vmp, m.isc) for m in mods}) > 1:
        out.append(MSG_PARALLEL_MODULES)
    ors = sorted({o.strip() for _n, _m, o in members if o and o.strip()})
    if len(ors) > 1:
        out.append(f"různá orientace stringů na MPPT ({', '.join(ors)})")
    return out


N_MODULES_LIMIT = 200   # strop hledání horní meze počtu modulů ve stringu (bez Umax / MPPT max → None)


def modules_per_optimizer(per_module) -> int | None:
    """Modulů na optimizér z „ks optimizérů na modul“ (1 → 1, 0,5 → 2); jiná nebo neplatná hodnota → None."""
    per = _f(per_module)
    if not per or per <= 0:
        return None
    mpo = 1 / per
    return round(mpo) if abs(mpo - round(mpo)) < 1e-6 and round(mpo) in (1, 2) else None


def string_limits(m: ModuleData, inv: InverterData, t_min: float = T_MIN_DEFAULT,
                  t_max: float = T_MAX_DEFAULT, opt: OptimizerData | None = None,
                  mpo: int | None = None, u_dc_devices: float | None = None, u_dc_label: str = "") -> StringLimits:
    """Rozsah počtu modulů ve stringu a paralelních stringů na MPPT – konzistentní se `string_issues`:
    classic: n_max = ⌊min(Umax, Umax systému modulu) / Uoc(t_min)⌋ a ⌊Umppt max / Umpp(t_min)⌋,
    n_min = ⌈Umppt min / Umpp(t_max)⌉; optimizer: totéž s U max výstupu optimizéru ∩ meze z počtu optimizérů
    a P stringu, délky po násobcích modulů na optimizér; fixed_voltage: jen z počtu optimizérů a P stringu.
    `mpo` = modulů na optimizér, když chybí data optimizéru (ruční „ks na modul“, `modules_per_optimizer`);
    s `opt` platí `opt.modules`. `u_dc_devices` = nejnižší Un DC přístrojů ve stringové cestě (`dc_system`):
    n_max = ⌊min(Umax, Umax systému modulu, Un DC přístrojů) / Uoc(t_min)⌋ (classic, optimizer)."""
    if opt is not None or mpo not in (1, 2):
        mpo = opt.modules if opt is not None else 1
    if inv.mode == "fixed_voltage":
        return _fixed_voltage_limits(m, inv, opt, mpo)
    lim = _classic_limits(m, inv, t_min, t_max, opt if inv.mode == "optimizer" else None, u_dc_devices, u_dc_label)
    if inv.string_mode != inv.mode:
        lim.reasons.insert(0, f"neznámý režim stringu „{inv.string_mode}“ – počítá se klasicky")
    if inv.mode != "optimizer":
        return lim
    lim.mode = "optimizer"
    n_lo, n_hi, p_max = optimizer_rules(inv, opt)
    caps = [] if lim.n_max is None else [lim.n_max]
    if n_hi:
        caps.append(n_hi * mpo)
        lim.reasons.append(f"nejvýš {_modules(n_hi * mpo)}: nejvýš {_optimizers(n_hi)} ve stringu")
    if p_max and m.p_wp:
        k = math.floor(p_max / m.p_wp / mpo + 1e-9) * mpo
        caps.append(k)
        lim.reasons.append(f"nejvýš {_modules(k)}: P stringu ≤ {p_max:g} W")
    if n_lo and n_lo * mpo > lim.n_min:
        lim.n_min = n_lo * mpo
        lim.reasons.append(f"nejméně {_modules(lim.n_min)}: nejméně {_optimizers(n_lo)} ve stringu")
    lim.n_max = min(caps) if caps else None
    lim.step = mpo
    lim.n_opt = (n_lo, n_hi) if (n_lo or n_hi) else None
    _apply_step(lim)
    return lim


def _apply_step(lim: StringLimits) -> None:
    """Meze na násobky `step` (n_min nahoru, n_max dolů) + důvod při prázdném rozsahu."""
    if lim.step > 1:
        lim.n_min = math.ceil(lim.n_min / lim.step) * lim.step
        if lim.n_max is not None:
            lim.n_max = lim.n_max // lim.step * lim.step
        lim.reasons.append(f"{lim.step} moduly na optimizér – délka stringu po {lim.step}")
    if lim.n_max is not None and lim.n_min > lim.n_max and not any("rozsah je prázdný" in r for r in lim.reasons):
        lim.reasons.append(f"rozsah je prázdný (nejméně {lim.n_min}, nejvýš {lim.n_max} modulů) – modul a střídač "
                           "k sobě nepasují")


def _fixed_voltage_limits(m: ModuleData, inv: InverterData, opt: OptimizerData | None, mpo: int = 1) -> StringLimits:
    """Meze stringu s pevným napětím (SolarEdge): n_min = n_opt_min·mpo, n_max = min(n_opt_max·mpo,
    ⌊P stringu max / P modulu / mpo⌋·mpo), krok mpo, stringů na MPPT = strings_per_mppt (bez proudové meze)."""
    n_lo, n_hi, p_max = optimizer_rules(inv, opt)
    u = f" {inv.u_string:g} V" if inv.u_string else ""
    reasons = [f"pevné napětí{u} – Uoc·n se nekontroluje"]
    if n_lo or n_hi:
        reasons.append(f"optimizérů {n_lo or '?'}–{n_hi or '?'}")
    if n_lo is None or n_hi is None:
        reasons.append("chybí údaj rozmezí počtu optimizérů ve stringu (doplňte z artiklu)")
    caps = []
    if n_hi:
        caps.append(n_hi * mpo)
    if p_max and m.p_wp:
        k = math.floor(p_max / m.p_wp / mpo + 1e-9) * mpo
        caps.append(k)
        reasons.append(f"P stringu ≤ {p_max:g} W → nejvýš {_modules(k)}")
    elif p_max is None:
        reasons.append("chybí údaj max. výkon stringu (doplňte z artiklu)")
    lim = StringLimits((n_lo or 1) * mpo, min(caps) if caps else None,
                       max(1, inv.strings_per_mppt or DC_INPUTS_PER_MPPT_DEFAULT), reasons, step=mpo,
                       n_opt=(n_lo, n_hi), mode="fixed_voltage")
    _apply_step(lim)
    return lim


def _classic_limits(m: ModuleData, inv: InverterData, t_min: float, t_max: float,
                    opt: OptimizerData | None = None, u_dc_devices: float | None = None,
                    u_dc_label: str = "") -> StringLimits:
    """Klasické meze (napětí, okno MPPT, proudy); `opt` s U max výstupu = Uoc stringu s capem (režim optimizer)."""
    reasons: list[str] = []
    uoc1, ump_hot1, ump_cold1 = m.uoc(t_min), m.ump(t_max), m.ump(t_min)
    # cap U max výstupu optimizéru jen když skutečně omezuje (mpo·Uoc(t_min) > U max výstupu)
    capped = opt is not None and bool(opt.u_out_max) and opt.modules * uoc1 > opt.u_out_max
    uoc_unit = opt.u_out_max / opt.modules if capped else uoc1
    cap_note = f" (U výstupu optimizéru ≤ {opt.u_out_max:g} V)" if capped else ""

    def issues(n: int) -> list[str]:
        uoc = _uoc_capped(m, n, t_min, opt, None) if capped else None
        out = _voltage_issues(m, inv, n, t_min, t_max, uoc)
        if u_dc_devices and (uoc if uoc is not None else _u_strings(m, n, t_min, t_max)[0]) > u_dc_devices + 1e-9:
            out.append("Un DC přístrojů")
        return out

    def fits_high(n: int, which: str) -> bool:
        return not any(which in x for x in issues(n))

    def upper(which: str, limit: float | None, per_module: float, label: str) -> int | None:
        if not limit or per_module <= 0:
            return None
        n = max(0, math.floor(limit / per_module))
        while n < N_MODULES_LIMIT and fits_high(n + 1, which):   # zaokrouhlení jako ve výkazu
            n += 1
        while n > 0 and not fits_high(n, which):
            n -= 1
        reasons.append(f"nejvýš {_modules(n)}: {label}")
        return n

    caps = [
        upper("Umax střídače", inv.u_dc_max, uoc_unit,
              f"Uoc při {t_min:g} °C {uoc_unit:.1f} V/modul{cap_note}, Umax střídače {inv.u_dc_max or 0:g} V"),
        upper("Umax systému modulu", m.u_sys_max, uoc_unit,
              f"Uoc při {t_min:g} °C {uoc_unit:.1f} V/modul{cap_note}, Umax systému modulu {m.u_sys_max or 0:g} V"),
        upper("Umppt max", inv.u_mppt_max, ump_cold1,
              f"Umpp při {t_min:g} °C {ump_cold1:.1f} V/modul, Umppt max {inv.u_mppt_max or 0:g} V"),
        upper("Un DC přístrojů", u_dc_devices, uoc_unit,
              f"Uoc při {t_min:g} °C {uoc_unit:.1f} V/modul{cap_note}, Un DC přístrojů {u_dc_devices or 0:g} V"
              + (f" ({u_dc_label})" if u_dc_label else "")),
    ]
    known = [c for c in caps if c is not None]
    n_max = min(known) if known else None
    n_min = 1
    if inv.u_mppt_min and ump_hot1 > 0:
        n_min = max(1, math.ceil(inv.u_mppt_min / ump_hot1))
        while n_min > 1 and not any("Umppt min" in x for x in issues(n_min - 1)):
            n_min -= 1
        while n_min < N_MODULES_LIMIT and any("Umppt min" in x for x in issues(n_min)):
            n_min += 1
        reasons.append(f"nejméně {_modules(n_min)}: Umpp při {t_max:g} °C {ump_hot1:.1f} V/modul, "
                       f"Umppt min {inv.u_mppt_min:g} V")
    if m.vmp_from_beta and (inv.u_mppt_min or inv.u_mppt_max):
        reasons.append("Umpp z β_Voc – zjednodušení (modul nemá γ_Pmax a α_Isc)")
    if not (inv.u_dc_max or inv.u_mppt_min):
        reasons.append(MSG_INV_NO_LIMITS)
    n_par_max = max(1, inv.strings_per_mppt or DC_INPUTS_PER_MPPT_DEFAULT)
    if inv.isc_mppt_max:
        if m.isc:
            by_isc = math.floor(inv.isc_mppt_max / m.isc + 1e-9)
            if by_isc < n_par_max:
                reasons.append(f"nejvýš {_strings(by_isc)} na MPPT: Isc {m.isc:g} A, Isc max MPPT {inv.isc_mppt_max:g} A")
            n_par_max = min(n_par_max, by_isc)
        if m.imp and inv.i_mppt_max and n_par_max * m.imp > inv.i_mppt_max:
            reasons.append(f"{_strings(n_par_max)} na MPPT: Impp {n_par_max * m.imp:.1f} A > Imax MPPT "
                           f"{inv.i_mppt_max:g} A – omezení výkonu")
    elif inv.i_mppt_max and m.isc and SAFETY_ISC * m.isc > inv.i_mppt_max:
        reasons.append(f"1,25·Isc {SAFETY_ISC * m.isc:.1f} A > Imax vstupu {inv.i_mppt_max:g} A – modul na střídač nelze")
        n_par_max = 0
    if n_max is not None and n_min > n_max:
        reasons.append(f"rozsah je prázdný (nejméně {n_min}, nejvýš {n_max} modulů) – modul a střídač k sobě nepasují")
    return StringLimits(n_min, n_max, n_par_max, reasons)


def _modules(n: int) -> str:
    return f"{n} {plural(n, 'modul', 'moduly', 'modulů')}"


def _strings(n: int) -> str:
    return f"{n} {plural(n, 'string', 'stringy', 'stringů')}"


# jmenovité proudy vložek gPV 1000 V DC (ETI Green Protect): CH10x38 10 až 25 A (EFH 10 DC max 25 A – mez držáku
# `in_max_a` artiklu), 30 / 32 A ve větších velikostech (10x85, 14x51)
GPV_FUSE_SIZES = (10.0, 12.0, 13.0, 15.0, 16.0, 20.0, 25.0, 30.0, 32.0)
OPTIMIZER_FUSE_IN = 25.0     # SolarEdge (optimizéry): string má pevný proud, standard ENVO 25 A


def string_fuse_in(isc: float | None, i_fuse_max: float | None = None, optimizer: bool = False,
                   sizes: tuple[float, ...] = GPV_FUSE_SIZES, max_in: float | None = None) -> float | None:
    """Jmenovitý proud pojistky gPV stringu (IEC 62548, ETI Green Protect): nejmenší řada In ≥ 1,5·Isc modulu
    (STC), nejvýš 2,4·Isc, max. jištění modulu (`i_fuse_max`, IMOD_MAX_OCPR) a max. In držáku (`max_in`, např.
    EFH 10 DC 25 A). String s optimizéry (SolarEdge) 25 A – i ten jen do max. In držáku. Bez Isc nebo bez
    vyhovující velikosti → None – nic se nedosazuje, generátor nechá In prázdné a kontrola (F7) to hlásí jako chybu."""
    if optimizer:
        return OPTIMIZER_FUSE_IN if not max_in or OPTIMIZER_FUSE_IN <= max_in + 1e-9 else None
    if not isc or isc <= 0:
        return None
    hi = min(x for x in (2.4 * isc, i_fuse_max, max_in) if x)
    for s in sizes:
        if s >= 1.5 * isc - 1e-9 and s <= hi + 1e-9:
            return s
    return None


def string_ports(n_strings: int, inv: InverterData | None) -> list[int]:
    """Čísla DC vstupů střídače (k v „DCk“, od 1) pro stringy v pořadí – tak je zapojí generátor. Se známým počtem
    MPPT rovnoměrně: vstupy {m·s + j + 1} pro k-tý string (m = k mod mppt, j = k div mppt, s = stringů na MPPT,
    neznámé = `DC_INPUTS_PER_MPPT_DEFAULT`), přiřazené stringům vzestupně, aby se vodiče nekřížily; stringy nad
    kapacitu mppt·s a při neznámém mppt za sebou DCk+1."""
    if inv is None or not inv.mppt:
        return list(range(1, n_strings + 1))
    s = inv.strings_per_mppt or DC_INPUTS_PER_MPPT_DEFAULT
    cap = inv.mppt * s
    spread = sorted((k % inv.mppt) * s + k // inv.mppt + 1 for k in range(min(n_strings, cap)))
    # vstupy se vyberou rovnoměrně po MPPT, stringy se k nim přiřadí vzestupně (shora dolů) – vodiče se nekříží
    return spread + [k + 1 for k in range(cap, n_strings)]


def port_mppt(port: int | None, inv: InverterData | None) -> int | None:
    """MPPT (od 0) vstupu DC`port`: (port − 1) div stringů na MPPT; neznámé stringů na MPPT nebo port → None."""
    if inv is None or not inv.strings_per_mppt or not port or port < 1:
        return None
    return (port - 1) // inv.strings_per_mppt


def assign_mppt(n_strings: int, inv: InverterData | None) -> list[int | None]:
    """MPPT (od 0, None = nezjištěno) každého z n_strings stringů střídače zapojených generátorem (`string_ports`)."""
    return [port_mppt(p, inv) for p in string_ports(n_strings, inv)]


def mppt_groups(assignment: list[int | None]) -> list[int]:
    """Počet stringů na stejném MPPT (n_par) pro každý string; nezjištěný MPPT → 1 (proudy se nesčítají)."""
    counts = Counter(m for m in assignment if m is not None)
    return [1 if m is None else counts[m] for m in assignment]


def inverter_capacity(inv: InverterData | None) -> int | None:
    """Počet stringových vstupů střídače mppt · stringů na MPPT; None, když jedno z nich není známé."""
    if inv is None or not inv.mppt or not inv.strings_per_mppt:
        return None
    return inv.mppt * inv.strings_per_mppt


def capacity_issue(ref: str, inv: InverterData | None, n_strings: int) -> str | None:
    """Hláška, když je na střídač zapojeno víc stringů, než má vstupů (MPPT × stringů na MPPT); jinak None.
    Přidává se stringům nad kapacitu (v pořadí vstupů DCk)."""
    cap = inverter_capacity(inv)
    if cap is None or n_strings <= cap:
        return None
    return (f"Střídač {ref or '?'} má jen {cap} {plural(cap, 'vstup', 'vstupy', 'vstupů')} (MPPT × stringů), "
            f"{plural(n_strings, 'zapojen', 'zapojeny', 'zapojeno')} {_strings(n_strings)}")


def suggest_inverter_count(p_dc_kwp: float, p_ac_kw: float, dc_ac_max: float = 1.3) -> int:
    """Doporučený počet střídačů: nejmenší počet, při kterém poměr DC/AC nepřekročí `dc_ac_max` (aspoň 1)."""
    if not p_dc_kwp or p_dc_kwp <= 0 or not p_ac_kw or p_ac_kw <= 0 or dc_ac_max <= 0:
        return 1
    return max(1, math.ceil(p_dc_kwp / (p_ac_kw * dc_ac_max) - 1e-9))


def _group_lengths(units: list[int], inv: InverterData, u_min: int, u_max: int) -> list[int]:
    """Délky stringů jednoho střídače (v jednotkách step, sestupně) přeskládané tak, aby stringy na stejném MPPT
    (`assign_mppt` – pořadí stringů = pořadí vstupů DCk vzestupně, vodiče se nekříží) měly stejnou délku, kde to jde.
    Součet modulů se nemění; délky různých MPPT se smí lišit víc než o 1 (nejvýš o 2 jednotky, v mezích u_min…u_max).
    Nejde-li to (nebo MPPT nezjištěn), vrací původní pořadí – smíšený je nejvýš jeden MPPT."""
    mppts = assign_mppt(len(units), inv)
    if len(units) < 2 or any(m is None for m in mppts) or len(set(mppts)) == len(units):
        return units
    sizes = [mppts.count(m) for m in dict.fromkeys(mppts)]   # stringů na MPPT v pořadí vstupů
    total, n_groups = sum(units), len(sizes)
    for spread in range(3):
        for lo in range(total // len(units), total // len(units) - spread - 1, -1):
            top = min(spread, u_max - lo)           # x_j ∈ 0…top (délka MPPT lo + x_j ≤ u_max)
            if lo < u_min or top < 0:
                continue
            rest = total - lo * len(units)          # rozdělit jako Σ sizes[j] · x_j
            if rest < 0:
                continue
            # reach[j] = součty dosažitelné skupinami j… (pro rekonstrukci zleva: delší stringy dřív)
            reach = [set() for _ in range(n_groups + 1)]
            reach[n_groups] = {0}
            for j in range(n_groups - 1, -1, -1):
                reach[j] = {r + sizes[j] * x for r in reach[j + 1] for x in range(top + 1) if r + sizes[j] * x <= rest}
            if rest not in reach[0]:
                continue
            out: list[int] = []
            for j in range(n_groups):
                x = next(x for x in range(top, -1, -1) if rest - sizes[j] * x in reach[j + 1])
                rest -= sizes[j] * x
                out += [lo + x] * sizes[j]
            return out
    return units


def propose_strings(n_total: int, n_inverters: int, lim: StringLimits,
                    inv: InverterData) -> tuple[list[list[int]], int]:
    """Návrh stringů: n_total modulů do co nejmenšího počtu stringů v mezích `lim`, rovnoměrně délky (liší se nejvýš
    o 1 modul, resp. o `lim.step` – délky jsou násobky step) i počtem na střídač; kapacita střídače = mppt ·
    min(strings_per_mppt, n_par_max) stringů (neznámé mppt = bez omezení). Mimo pevné napětí se pak délky na střídači
    přeskládají (`_group_lengths`), aby stringy na jednom MPPT měly stejnou délku, kde to jde – mezi MPPT se pak smí
    lišit až o 2·step. Vrací (stringy po střídačích v pořadí vstupů DCk, počet modulů, které se nevešly)."""
    n_inv = max(1, int(n_inverters or 1))
    empty: list[list[int]] = [[] for _ in range(n_inv)]
    n_total = max(0, int(n_total or 0))
    step = max(1, int(lim.step or 1))
    if not n_total or lim.n_max is None or lim.n_max < step or not lim.ok:
        return empty, n_total
    u_total, u_max, u_min = n_total // step, lim.n_max // step, max(1, math.ceil(lim.n_min / step))
    spm = inv.strings_per_mppt or DC_INPUTS_PER_MPPT_DEFAULT
    per_inv = inv.mppt * min(spm, lim.n_par_max) if inv.mppt else None
    n_str = math.ceil(u_total / u_max) if u_total else 0
    if per_inv is not None:
        n_str = min(n_str, per_inv * n_inv)
    n_str = min(n_str, u_total // u_min)
    if n_str <= 0:
        return empty, n_total
    placed = min(u_total, n_str * u_max)
    base, rem = divmod(placed, n_str)
    lengths = [(base + 1) * step] * rem + [base * step] * (n_str - rem)
    out = [lengths[i::n_inv] for i in range(n_inv)]   # střídavě: počty i délky na střídačích vyrovnané
    if lim.mode != "fixed_voltage":   # pevné napětí: paralelní stringy se neporovnávají (`check_strings`)
        out = [[u * step for u in _group_lengths([n // step for n in g], inv, u_min, u_max)] for g in out]
    return out, n_total - placed * step

@dataclass
class StringCheck:
    ref: str
    n: int
    uoc_cold: float
    umpp_hot: float
    isc: float
    inverter: str
    u_dc_max: float | None
    u_mppt_min: float | None
    u_mppt_max: float | None
    i_mppt_max: float | None
    issues: list[str] = field(default_factory=list)
    sheet: str = ""          # název listu se stringem (filtr výkazu Výpočty pro jeden list)
    mppt: int | None = None  # index MPPT střídače (od 0; DCk → (k−1)//strings_per_mppt), None = nezjištěno
    #                          (port nejednoznačný nebo střídač nemá `strings_per_mppt`)
    n_par: int = 1           # počet stringů na stejném MPPT (včetně tohoto)
    isc_mppt_max: float | None = None
    t_min: float = T_MIN_DEFAULT
    t_max: float = T_MAX_DEFAULT
    mode: str = "classic"               # platný režim stringu střídače (`InverterData.mode`)
    n_opt: int | None = None            # optimizérů ve stringu (atribut, jinak ⌈n / mpo⌉ s daty optimizéru)
    p_string: float | None = None       # P stringu [W] = n · P modulu
    u_string: float | None = None       # pevné napětí stringu [V] (jen fixed_voltage)
    p_string_max: float | None = None   # nejpřísnější P stringu max [W] (optimizer, fixed_voltage)
    n_opt_min: int | None = None        # nejpřísnější rozmezí počtu optimizérů (optimizer, fixed_voltage)
    n_opt_max: int | None = None

    @property
    def ok(self) -> bool:
        return not self.issues


@dataclass
class CableCheck:
    ref: str
    sheet: str
    i_a: float | None
    cross: float | None
    length: float | None
    method: str
    system: str
    u_v: float
    iz: float | None
    in_breaker: float | None
    breaker_ref: str
    du_v: float | None
    du_pct: float | None
    issues: list[str] = field(default_factory=list)


def _wire_system(w: Wire) -> tuple[str, float]:
    from envocad.model.project import conductor_name
    conds = {conductor_name(c) for c in w.conductors}
    if conds & {"+", "-", "L+", "L-"}:
        return "dc", 0.0
    if {"L1", "L2", "L3"} <= conds:
        return "3f", 400.0
    return "1f", 230.0


def _far_ends(project: Project, s: Sheet, w: Wire, groups: dict | None = None) -> list[tuple[Element, str]]:
    """Konce vodiče (prvek, port); přerušovací bod hlavního úseku s pokračováním za protějškem se nahradí skutečným
    koncem (`xref.through_interrupt` – AC kabel přes listy JPS vede ze střídače). `groups` = `interrupt_groups`."""
    out = []
    for end in (w.a, w.b):
        e, port = s.element(end.element_id), end.port
        if e.symbol_id == INTERRUPT_SYMBOL:
            from envocad.model.xref import through_interrupt
            hit = through_interrupt(project, s, e, port, groups)
            if hit is not None:
                e, port = hit.element, hit.port
        out.append((e, port))
    return out


def _source_current(project: Project, s: Sheet, w: Wire, inverter_u_dc: float | None,
                    groups: dict | None = None) -> tuple[float | None, str]:
    """Proud vodičem podle zdroje na jeho konci: string (1,25·Isc), střídač AC (P/√3U), jistič (In). Konec na
    přerušovacím bodu ve dvojici se sleduje za protějšek (`_far_ends`)."""
    ends = _far_ends(project, s, w, groups)
    for e, port in ends:
        if e.symbol_id == "fve.pv_string":
            isc = _f(e.attrs.get("isc"))
            if isc:
                return round(SAFETY_ISC * isc, 2), f"1,25·Isc stringu {e.ref}"
        if e.symbol_id in ("fve.inverter", "fve.inverter_hybrid") and port == "AC":
            p = _f(e.attrs.get("p_ac"))
            if p:
                ph = _f(e.attrs.get("phases"), 3)
                i = p * 1000 / (3 ** 0.5 * 400) if ph == 3 else p * 1000 / 230
                return round(i, 1), f"P_AC střídače {e.ref}"
    for e, _port in ends:
        i_n = _f(e.attrs.get("in_"))
        if i_n and e.symbol_id in ("fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo", "sb.main_switch",
                                   "fve.switch_disconnector", "fve.fuse", "fve.dc_disconnect"):
            return i_n, f"In {e.ref}"
    return None, ""


def _breaker_el_on_wire(s: Sheet, w: Wire) -> Element | None:
    for end in (w.a, w.b):
        e = s.element(end.element_id)
        if e.symbol_id in ("fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo", "fve.fuse"):
            return e
    return None


def _breaker_on_wire(s: Sheet, w: Wire) -> tuple[float | None, str]:
    e = _breaker_el_on_wire(s, w)
    return (_f(e.attrs.get("in_")), e.ref) if e is not None else (None, "")


# I2 / In – smluvený vypínací proud jisticího přístroje (ČSN 33 2000-4-43, čl. 433.1: I2 ≤ 1,45·Iz). Jističe
# EN 60898 (B/C/D) 1,45, jističe EN 60947-2 (kompaktní, MCCB) 1,3, pojistky gPV (EN 60269-6) 1,45, pojistky gG / gL
# (EN 60269-1, tab. 2) podle In: ≤ 4 A 2,1; nad 4 A pod 16 A 1,9; ≥ 16 A 1,6. aM a neznámá charakteristika pojistky → None
# (bez kontroly přetížení – aM nechrání proti přetížení, neznámou nehádáme).
I2_LIMIT = 1.45


def conventional_trip_factor(e: Element) -> float | None:
    """I2/In jisticího přístroje podle značky a charakteristiky (`char`), None = neznámé (kontrola I2 se přeskočí)."""
    if e.symbol_id in ("fve.breaker_mcb", "sb.rcbo"):
        return 1.45
    if e.symbol_id == "fve.breaker_mccb":
        return 1.3
    if e.symbol_id in ("fve.fuse", "fve.fuse_disconnect"):
        ch = str(e.attrs.get("char") or "").strip().lower()
        if ch == "gpv":
            return 1.45
        if ch in ("gg", "gl", "gl/gg", "gg/gl"):
            i_n = _f(e.attrs.get("in_"))
            if not i_n:
                return None
            return 2.1 if i_n <= 4 else (1.9 if i_n < 16 else 1.6)
    return None


def check_strings(project: Project, t_min: float | None = None, t_max: float | None = None,
                  lib=None) -> list[StringCheck]:
    """Kontrola každého stringu proti střídači, na který vede (přes odpínače, pojistky, svorky, DC rozvaděče).
    Teploty: zadané, jinak `design_temperatures(project)`. Stringy na stejném MPPT (střídač + DCk → MPPT, jen se
    známým `strings_per_mppt`) se počítají spolu (`n_par`) – uplatní se jen u střídače s `isc_mppt_max` – a v režimech
    classic / optimizer se porovnají (`parallel_issues`). Víc stringů na střídači než mppt · stringů na MPPT →
    `capacity_issue` u stringů nad kapacitu (v pořadí vstupů DCk). Režim stringu = atribut střídače `string_mode`,
    data optimizéru = atributy `opt_*` stringu (`OptimizerData.from_attrs`), počet optimizérů = `n_optimizers`.
    Uoc nad nejnižším Un DC přístrojů ve stringové cestě (`string_device_limits`, s `lib` i z artiklů) je chyba
    `MSG_DC_DEVICES` – stejně jako v asistentu průvodce; jen se zadanou návrhovou teplotou t_min v projektu
    (`meta["pv_t_min"]`, i když volající teploty předá – TZ i výkaz Výpočty tak hlásí totéž co F7); bez ní F7 `un_dc`
    jako informace."""
    d_min, d_max = design_temperatures(project)
    t_min = d_min if t_min is None else t_min
    t_max = d_max if t_max is None else t_max
    found = []
    from envocad.model.xref import interrupt_groups
    igroups = interrupt_groups(project)      # jednou – string přes přerušení (rozdělené blokové schéma)
    for s in project.sheets:
        for e in s.elements:
            if e.symbol_id != "fve.pv_string":
                continue
            inv_el, port = _trace_inverter(project, s, e, groups=igroups)
            inv = InverterData.from_attrs(inv_el.attrs) if inv_el is not None else None
            mt = re.fullmatch(r"DC(\d+)", port or "")
            pnum = int(mt.group(1)) if mt else None
            found.append((s, e, inv_el, inv, port_mppt(pnum, inv), pnum))
    groups: dict[tuple[str, int], list[int]] = {}
    per_inv: dict[str, list[int]] = {}
    for i, (_s, _e, inv_el, _inv, mppt, _p) in enumerate(found):
        if inv_el is not None:
            per_inv.setdefault(inv_el.id, []).append(i)
            if mppt is not None:
                groups.setdefault((inv_el.id, mppt), []).append(i)
    over: dict[int, str] = {}
    for idx in per_inv.values():
        inv_el, inv = found[idx[0]][2], found[idx[0]][3]
        msg = capacity_issue(inv_el.ref, inv, len(idx))
        if msg:
            ordered = sorted(idx, key=lambda i: (found[i][5] is None, found[i][5] or 0, i))
            over.update(dict.fromkeys(ordered[inverter_capacity(inv):], msg))
    out = []
    # Un DC přístrojů ve stringové cestě (jako asistent průvodce) – jen se zadanou návrhovou teplotou v projektu;
    # s předpokladem T_MIN_DEFAULT hlásí podkročení Un jen informace F7 `un_dc` (`model/ratings.py`)
    t_given = parse_temperature((getattr(project, "meta", None) or {}).get("pv_t_min")) is not None
    dev_limits = string_device_limits(project, lib) if t_given else {}
    modules: list[tuple[int, ModuleData | None]] = []
    for i, (s, e, inv_el, inv, mppt, _p) in enumerate(found):
        n = int(_f(e.attrs.get("n_modules"), 0) or 0)
        m0 = ModuleData.from_attrs(e.attrs)
        m = m0 or ModuleData(voc=0.0, vmp=0.0, isc=_f(e.attrs.get("isc")) or 0.0, imp=_f(e.attrs.get("imp")),
                             beta_voc=_f(e.attrs.get("beta_voc")) or BETA_VOC_DEFAULT,
                             u_sys_max=_f(e.attrs.get("u_sys_max")), alpha_isc=_f(e.attrs.get("alpha_isc")),
                             gamma_pmax=_f(e.attrs.get("gamma_pmax")), p_wp=_f(e.attrs.get("p_module")))
        if e.component_id:
            m = replace(m, component_id=e.component_id)
        modules.append((n, m if m0 is not None else None))
        opt = OptimizerData.from_attrs(e.attrs)
        n_opt = _int(e.attrs.get("n_optimizers"))
        group = groups.get((inv_el.id, mppt), []) if inv_el is not None and mppt is not None else []
        n_par = len(group) or 1
        uoc_cold, umpp_hot, _umpp_cold = _u_strings(m, n, t_min, t_max)
        mode = inv.mode if inv is not None else "classic"
        n_lo, n_hi, p_max = optimizer_rules(inv, opt) if mode != "classic" else (None, None, None)
        sc = StringCheck(e.ref, n, uoc_cold, umpp_hot, m.isc, inv_el.ref if inv_el else "",
                         inv.u_dc_max if inv else None, inv.u_mppt_min if inv else None,
                         inv.u_mppt_max if inv else None, inv.i_mppt_max if inv else None,
                         sheet=s.name, mppt=mppt, n_par=n_par, isc_mppt_max=inv.isc_mppt_max if inv else None,
                         t_min=t_min, t_max=t_max, mode=mode,
                         n_opt=n_opt if n_opt is not None or opt is None or not n else math.ceil(n / opt.modules),
                         p_string=round(n * m.p_wp, 1) if m.p_wp and n else None,
                         u_string=inv.u_string if inv is not None and mode == "fixed_voltage" else None,
                         p_string_max=p_max, n_opt_min=n_lo, n_opt_max=n_hi)
        sc.issues = string_issues(m, inv, n, n_par, t_min, t_max, opt, n_opt, dev_limits.get(e.id)) \
            + ([over[i]] if i in over else [])
        out.append(sc)
    for idx in groups.values():
        inv = found[idx[0]][3]
        if len(idx) < 2 or inv is None or inv.mode == "fixed_voltage":
            continue
        msgs = parallel_issues([(modules[i][0], modules[i][1], str(found[i][1].attrs.get("orientation") or ""))
                                for i in idx])
        for i in idx:
            out[i].issues += msgs
    return out


_PASS_THROUGH = ("fve.dc_disconnect", "fve.fuse", "fve.terminal", "sb.terminal_block", "fve.spd", "fve.switchboard",
                 FEED_SYMBOL, "fve.interrupt")
_INVERTERS = ("fve.inverter", "fve.inverter_hybrid")


def _wire_steps(project: Project, s: Sheet, e: Element, groups: dict | None):
    """Vodiče u prvku: (list, konec u prvku, druhý konec, přes protějšek). Přerušovací bod dvojice, kde jeden úsek
    je prázdné pokračování (rozdělené blokové schéma, `xref.is_blank_wire`), pokračuje vodičem u protějšku na jeho
    listu – string najde svůj střídač i přes rozvaděč FVE na jiném listu. Jiná přerušení se nepřeskakují."""
    out = [(s, end, other, False) for w in s.wires for end, other in ((w.a, w.b), (w.b, w.a))
           if end.element_id == e.id]
    if e.symbol_id == INTERRUPT_SYMBOL and groups:
        from envocad.model.xref import _pair_segments, is_blank_wire
        hit = _pair_segments(project, s, e, groups)
        if hit is not None and is_blank_wire(hit[0]) != is_blank_wire(hit[3]):
            _own, ps, pe, _w = hit
            out += [(ps, end, other, True) for w in ps.wires for end, other in ((w.a, w.b), (w.b, w.a))
                    if end.element_id == pe.id]
    return out


def _find_inverter(project: Project, s: Sheet, start: Element, max_depth: int = 12,
                   groups: dict | None = None, trail: list | None = None) -> Element | None:
    # blok DC rozvaděče se prochází párem portů (`_block_exit`): společný rozvaděč u technologie (RFVE.DC pro víc
    # střídačů) vede každý string jen na jeho střídač; nejednoznačné zapojení bloku = všechny vodiče jako dřív.
    # `trail` (seznam) = sem se zapíšou prošlé průchozí prvky (list, prvek, port vstupu) – napětí DC prvků (`dc_voltages`)
    seen = {start.id}
    frontier: list[tuple[Sheet, Element, str | None]] = [(s, start, None)]
    for _ in range(max_depth):
        nxt = []
        for fs, fe, entered in frontier:
            exit_port = _block_exit(fs, fe, entered, project) if fe.symbol_id == "fve.switchboard" and entered else None
            for ps, end, other, via in _wire_steps(project, fs, fe, groups):
                if exit_port is not None and not via and end.port != exit_port:
                    continue
                o = ps.element(other.element_id)
                key = f"{o.id}:{other.port}" if o.symbol_id == "fve.switchboard" else o.id
                if key in seen or other.element_id == start.id:
                    continue
                if o.symbol_id in _INVERTERS:
                    return o
                if o.symbol_id in _PASS_THROUGH:
                    seen.add(key)
                    nxt.append((ps, o, other.port))
                    if trail is not None:
                        trail.append((ps, o, other.port))
        frontier = nxt
        if not frontier:
            break
    return None


def _block_exit(s: Sheet, block: Element, port: str, project: Project | None = None) -> str | None:
    """Průchod blokem DC rozvaděče: přívod `port` → vývod. S listem rozvaděče podle zapojení listu (`_sheet_exit` –
    přívod → pojistka → vývod); jinak (nebo nejednoznačně) párem DC portů bloku: vstup X{k} ↔ výstup X{k + N/2}
    (N = počet portů X… zapojených DC vodičem, jako u generátoru – AC přívody RFVE rodinného domu X1…Xn se
    nepočítají, string by jinak skončil u cizího střídače). Jiné zapojení → None (nejednoznačné)."""
    if project is not None:
        hit = _sheet_exit(project, block, port)
        if hit is not None:
            return hit
    nums = sorted({int(mm.group(1)) for w in s.wires for end in (w.a, w.b) if end.element_id == block.id
                   and _wire_system(w)[0] == "dc" and (mm := re.fullmatch(r"X(\d+)", end.port or ""))})
    mk = re.fullmatch(r"X(\d+)", port or "")
    if not mk or len(nums) % 2 or int(mk.group(1)) not in nums:
        return None
    i = nums.index(int(mk.group(1)))
    half = len(nums) // 2
    return f"X{nums[i + half]}" if i < half else None


_SHEET_STOP = ("sb.busbar", "sb.pe_bar", "fve.busbar")


def _sheet_exit(project: Project, block: Element, port: str) -> str | None:
    """Vývod listu rozvaděče, kam vede přívod `port` (přes přístroje a svorky listu, bez PE vodičů a bez průchodu
    sběrnicí); jediný jiný přívod / vývod → jeho označení, jinak None."""
    sb = project.switchboard_sheet(block.id)
    if sb is None:
        return None
    start = next((e for e in sb.elements if is_feed(e) and e.ref == port), None)
    if start is None:
        return None
    by_id = {e.id: e for e in sb.elements}
    seen, todo, found = {start.id}, [start], set()
    while todo:
        cur = todo.pop()
        for w in sb.wires:
            if not w.touches(cur.id) or set(w.conductors) <= {"PE"}:
                continue
            o = by_id.get(w.b.element_id if w.a.element_id == cur.id else w.a.element_id)
            if o is None or o.id in seen:
                continue
            seen.add(o.id)
            if is_feed(o):
                if o.ref:
                    found.add(o.ref)
                continue
            if o.symbol_id in _SHEET_STOP:
                continue
            todo.append(o)
    return next(iter(found)) if len(found) == 1 else None


def _trace_inverter(project: Project, s: Sheet, start: Element, max_depth: int = 12,
                    groups: dict | None = None) -> tuple[Element | None, str]:
    """(střídač, port střídače) pro string: střídač jako `_find_inverter`; port jen při jednoznačném řetězci
    vodičů (přes průchozí prvky, bloky DC rozvaděčů párem portů, dvojice přerušení s pokračováním), jinak ""
    (MPPT nezjištěn → bez sčítání proudů)."""
    inv = _find_inverter(project, s, start, max_depth, groups)
    if inv is None:
        return None, ""
    cs, cur, entered = s, start, None
    visited = {start.id}
    for _ in range(max_depth + 1):
        exit_port = _block_exit(cs, cur, entered, project) if cur.symbol_id == "fve.switchboard" else None
        if cur.symbol_id == "fve.switchboard" and exit_port is None:
            return inv, ""
        nxt = []
        for ps, end, other, via in _wire_steps(project, cs, cur, groups):
            if other.element_id in visited:
                continue
            if not via and exit_port is not None and end.port != exit_port:
                continue
            if not via and exit_port is None and entered is not None and end.port == entered:
                continue
            nxt.append((ps, other))
        if len({(o.element_id, o.port) for _ps, o in nxt}) != 1:
            return inv, ""
        ps, o = nxt[0]
        el = ps.element(o.element_id)
        if el.symbol_id in _INVERTERS:
            return (inv, o.port) if el.id == inv.id else (inv, "")
        if el.symbol_id not in _PASS_THROUGH:
            return inv, ""
        visited.add(el.id)
        cs, cur, entered = ps, el, o.port
    return inv, ""


@dataclass
class DcVoltage:
    """Nejvyšší napětí DC v místě prvku: Uoc stringu při t_min (režim fixed_voltage: pevné napětí stringu střídače,
    režim optimizer s U max výstupu optimizéru: `_uoc_capped`), string, který ho dává, a jeho střídač."""
    u: float
    string_ref: str
    inverter: Element | None = None


def _string_dc_voltage(m: ModuleData, n: int, t_min: float, inv: InverterData | None, attrs: dict) -> float | None:
    mode = inv.mode if inv is not None else "classic"
    if mode == "fixed_voltage":
        return inv.u_string if inv is not None else None
    uoc = _u_strings(m, n, t_min, T_MAX_DEFAULT)[0]
    if mode == "optimizer":
        capped = _uoc_capped(m, n, t_min, OptimizerData.from_attrs(attrs), _int(attrs.get("n_optimizers")))
        if capped is not None:
            return capped
    return uoc


def _board_reach(project: Project, block: Element, port: str | None) -> list[Element] | None:
    """Prvky listu rozvaděče bloku `block`, kam vede přívod `port` (přes přístroje a svorky listu, bez PE vodičů,
    zastaví se na přívodech / vývodech a sběrnicích). Blok bez listu → []; přívod `port` v listu nenalezen → None
    (napětí se neurčuje – `StringPath.unresolved`, F7 informace `dc_path_unknown`)."""
    sb = project.switchboard_sheet(block.id)
    if sb is None:
        return []
    start = next((e for e in sb.elements if is_feed(e) and port and e.ref == port), None)
    if start is None:
        return None
    by_id = {e.id: e for e in sb.elements}
    seen, todo, out = {start.id}, [start], [start]
    while todo:
        cur = todo.pop()
        for w in sb.wires:
            if not w.touches(cur.id) or set(w.conductors) <= {"PE"}:
                continue
            o = by_id.get(w.b.element_id if w.a.element_id == cur.id else w.a.element_id)
            if o is None or o.id in seen:
                continue
            seen.add(o.id)
            out.append(o)
            if is_feed(o) or o.symbol_id in _SHEET_STOP:
                continue
            todo.append(o)
    return out


@dataclass
class StringPath:
    """String a jeho cesta ke střídači: průchozí prvky blokového schématu a prvky listů DC rozvaděčů od přívodu
    stringu (`_board_reach`); `unresolved` = (blok, port) rozvaděčů, kde přívod v listu chybí; `voltage` = napětí
    stringu při t_min (`DcVoltage`, None bez údajů modulu)."""
    sheet: Sheet
    string: Element
    inverter: Element | None
    elements: list[Element] = field(default_factory=list)
    unresolved: list[tuple[Element, str]] = field(default_factory=list)
    voltage: DcVoltage | None = None


def string_paths(project: Project, t_min: float | None = None) -> list[StringPath]:
    """Cesty všech stringů projektu (`StringPath`) s napětím při t_min (`design_temperatures`, je-li None)."""
    from envocad.model.xref import interrupt_groups
    t_min = design_temperatures(project)[0] if t_min is None else t_min
    groups = interrupt_groups(project)
    out: list[StringPath] = []
    for s in project.sheets:
        for e in s.elements:
            if e.symbol_id != "fve.pv_string":
                continue
            trail: list = []
            inv_el = _find_inverter(project, s, e, groups=groups, trail=trail)
            sp = StringPath(s, e, inv_el)
            for _ps, o, entered in trail:
                sp.elements.append(o)
                if o.symbol_id == "fve.switchboard":
                    reach = _board_reach(project, o, entered)
                    if reach is None:
                        sp.unresolved.append((o, entered or ""))
                    else:
                        sp.elements += reach
            m, n = ModuleData.from_attrs(e.attrs), int(_f(e.attrs.get("n_modules"), 0) or 0)
            if m is not None and n:
                inv = InverterData.from_attrs(inv_el.attrs) if inv_el is not None else None
                u = _string_dc_voltage(m, n, t_min, inv, e.attrs)
                if u:
                    sp.voltage = DcVoltage(round(u, 1), e.ref, inv_el)
            out.append(sp)
    return out


def dc_voltages(project: Project, t_min: float | None = None,
                paths: list[StringPath] | None = None) -> dict[str, DcVoltage]:
    """Id prvku → nejvyšší napětí DC v jeho místě (`DcVoltage`) ze stringů, které jím vedou (`string_paths`):
    průchozí prvky blokového schématu a prvky listů DC rozvaděčů od přívodu stringu. Rozvaděč, kde přívod stringu
    v listu chybí, se neurčuje. Pro kontroly Un a Ucpv prvků DC strany z údajů artiklů (`model/ratings.py`)."""
    out: dict[str, DcVoltage] = {}
    for sp in string_paths(project, t_min) if paths is None else paths:
        v = sp.voltage
        if v is None:
            continue
        for x in sp.elements:
            if x.id not in out or out[x.id].u < v.u:
                out[x.id] = v
    return out


# přístroje stringové cesty s Un DC (svodič: Ucpv) – mez délky stringu (`string_device_limits`, `dc_system`); stejné
# druhy hodnotí F7 `un_dc` / `spd_ucpv` (`model/ratings.py`), v cestě stringu je ale pokryje `calc_string`
DC_PATH_DEVICES = frozenset({"fve.fuse", "fve.fuse_disconnect", "fve.dc_disconnect", "fve.switch_disconnector",
                             "fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo", "sb.rcd", "sb.main_switch",
                             "fve.contactor", "fve.changeover_switch", "fve.terminal", "sb.terminal_block",
                             "fve.spd"})


def _cached_component(lib, cid: str | None, cache: dict | None = None):
    if lib is None or not cid:
        return None
    if cache is not None and cid in cache:
        return cache[cid]
    try:
        comp = lib.component(cid)
    except Exception:  # noqa: BLE001 – knihovna nedostupná
        comp = None
    if cache is not None:
        cache[cid] = comp
    return comp


def device_dc_un(e: Element, lib=None, cache: dict | None = None) -> float | None:
    """Un DC přístroje ve stringové cestě (pořadí atribut > artikl jako F7): svodič – Ucpv (`dc_system.spd_ucpv`,
    Uc se za Ucpv nebere); ostatní – atribut `un`, artikl `un_v` (`dc_system.un_value`). Neznámé → None."""
    from envocad.model import dc_system
    if e.symbol_id not in DC_PATH_DEVICES:
        return None
    comp = _cached_component(lib, e.component_id, cache)
    if e.symbol_id == "fve.spd":
        return dc_system.spd_ucpv(e.attrs, comp)
    return dc_system.un_value(e.attrs.get("un")) or dc_system.component_un(comp)


def path_devices(sp: StringPath, lib=None, cache: dict | None = None) -> list[tuple[float, str, Element]]:
    """(Un DC [V], popis „EFH 10 DC 2p 1000 V“, prvek) přístrojů v cestě stringu se známým Un (bez opakování)."""
    out, seen = [], set()
    for x in sp.elements:
        u = device_dc_un(x, lib, cache) if x.id not in seen else None
        seen.add(x.id)
        if u:
            out.append((u, f"{x.attrs.get('type') or x.ref or x.symbol_id} {u:g} V", x))
    return out


def string_device_limits(project: Project, lib=None,
                         paths: list[StringPath] | None = None) -> dict[str, list[tuple[float, str]]]:
    """Id stringu → [(Un DC, popis)] přístrojů v jeho cestě – stejná data jako asistent průvodce
    (`dc_system.path_devices`); string bez přístrojů se známým Un chybí."""
    cache: dict = {}
    out: dict[str, list[tuple[float, str]]] = {}
    for sp in string_paths(project) if paths is None else paths:
        devs = [(u, label) for u, label, _x in path_devices(sp, lib, cache)]
        if devs:
            out[sp.string.id] = devs
    return out


_PROTECTION = ("fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo", "fve.fuse", "fve.fuse_disconnect")


_TERMINALS = ("fve.terminal", "sb.terminal_block", "sb.junction")


def _port_protection(project: Project, block: Element, port: str) -> tuple[float | None, str]:
    """Jištění kabelu na vývodu bloku rozvaděče (vazba vývodu – vývod jistí svůj kabel): jistič / pojistka hned za
    vývodem `port` v listu rozvaděče (přes svorky); blok bez listu → atribut `protect` („X1=63“). Přívod listu (kabel
    jistí druhý konec) a vývod bez jištění → (None, "")."""
    i_n, label, _e = _port_protection_el(project, block, port)
    return i_n, label


def _port_protection_el(project: Project, block: Element, port: str) -> tuple[float | None, str, Element | None]:
    """Jako `_port_protection` + prvek jištění v listu rozvaděče (blok bez listu – jen In z `protect`, prvek None)."""
    from envocad.model.feed import is_feed_out
    from envocad.model.project import block_protect
    sb = project.switchboard_sheet(block.id)
    if sb is None:
        v = block_protect(block).get(port)
        return (v, f"{block.ref}:{port}", None) if v else (None, "", None)
    start = next((e for e in sb.elements if is_feed(e) and e.ref == port), None)
    if start is None or not is_feed_out(start):
        return None, "", None
    by_id = {e.id: e for e in sb.elements}
    seen, frontier = {start.id}, [start]
    for _ in range(4):
        nxt = []
        for cur in frontier:
            for w in sb.wires:
                if not w.touches(cur.id) or set(w.conductors) <= {"PE"}:
                    continue
                o = by_id.get(w.b.element_id if w.a.element_id == cur.id else w.a.element_id)
                if o is None or o.id in seen:
                    continue
                seen.add(o.id)
                if o.symbol_id in _PROTECTION:
                    i_n = _f(o.attrs.get("in_"))
                    return (i_n, f"{block.ref}:{o.ref}", o) if i_n else (None, "", None)
                if o.symbol_id in _TERMINALS:
                    nxt.append(o)
        frontier = nxt
    return None, "", None


def check_cables(project: Project, t_ambient: float = 30.0, du_limit_pct: float = 3.0) -> list[CableCheck]:
    from envocad.model.xref import interrupt_groups
    out = []
    groups = interrupt_groups(project)     # jednou – konce přes přerušení (`_far_ends`)
    for s in project.sheets:
        for w in s.wires:
            if not (w.attrs.get("ref") or w.attrs.get("cable") or w.attrs.get("cross")):
                continue
            cross = _f(w.attrs.get("cross"))
            length = _f(w.attrs.get("length"))
            system, u = _wire_system(w)
            alu = "AYKY" in (w.attrs.get("cable") or "").upper() or "AL" in (w.attrs.get("cable") or "").upper().split()
            i_a, _src = _source_current(project, s, w, None, groups)
            if system == "dc":
                # napětí stringu pro úbytek: Umpp ≈ n·vmp z připojeného stringu
                for e, _port in _far_ends(project, s, w, groups):
                    if e.symbol_id == "fve.pv_string":
                        n = _f(e.attrs.get("n_modules"), 0) or 0
                        vmp = _f(e.attrs.get("vmp")) or (_f(e.attrs.get("voc")) or 0) * 0.82
                        u = n * vmp
            method = route_method(w)
            loaded = 3 if system == "3f" else 2
            iz = ampacity(cross, method, loaded, alu, t_ambient) if cross else None
            prot = _breaker_el_on_wire(s, w)
            in_b, bref = (_f(prot.attrs.get("in_")), prot.ref) if prot is not None else (None, "")
            if in_b is None:          # jištění za přívodem / vývodem bloku rozvaděče (list, jinak atribut `protect`)
                for e, port in _far_ends(project, s, w, groups):
                    if e.symbol_id == "fve.switchboard":
                        in_b, bref, prot = _port_protection_el(project, e, port)
                        if in_b is not None:
                            break
            du_v = du_pct = None
            if i_a and length and cross and u:
                du_v, du_pct = voltage_drop(i_a, length, cross, system, u, alu)
            cc = CableCheck(w.attrs.get("ref", ""), s.name, i_a, cross, length, method, system, u, iz, in_b, bref,
                            du_v, du_pct)
            if cross is None:
                cc.issues.append("chybí průřez")
            if iz and i_a and i_a > iz:
                cc.issues.append(f"proud {i_a} A > Iz {iz} A ({method})")
            if iz and in_b and in_b > iz:
                cc.issues.append(f"In jističe {bref} {in_b:g} A > Iz kabelu {iz} A")
            elif iz and in_b and prot is not None:   # In ≤ Iz splněno – smluvený vypínací proud I2 ≤ 1,45·Iz
                k2 = conventional_trip_factor(prot)
                if k2 is not None and k2 * in_b > I2_LIMIT * iz + 1e-9:
                    cc.issues.append(f"I2 jištění {bref} = {_num_cz(k2)}·In = {_num_cz(round(k2 * in_b, 1))} A > "
                                     f"1,45·Iz = {_num_cz(round(I2_LIMIT * iz, 1))} A (pojistka "
                                     f"{prot.attrs.get('char') or ''} – zvolte menší In nebo větší průřez)")
            if du_pct is not None and du_pct > du_limit_pct:
                cc.issues.append(f"úbytek {du_pct} % > {du_limit_pct:g} %")
            if length is None and not s.is_switchboard:
                cc.issues.append("chybí délka (úbytek nespočítán)")
            out.append(cc)
    return out


# jisticí přístroje v selektivitě: jističe, pojistky (i pojistkový odpínač – vývod FVE nad 80 A) a pojistky HDS
SELECTIVITY_DEVICES = frozenset({"fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo", "fve.fuse", "fve.fuse_disconnect",
                                 "fve.hds"})


def check_selectivity(project: Project, sheet: Sheet | None = None) -> list[tuple[str, str, float, float, str]]:
    """Dvojice jistič → nadřazený jistič po cestě ke zdroji; vrací (dolní, horní, In_d, In_h, hlášení).
    `sheet` = jen dvojice na tomto listu (výkaz pro jeden list), jinak všechny listy."""
    from envocad.model.multipole import is_flow_source
    out = []
    breakers = SELECTIVITY_DEVICES
    for s in project.sheets:
        if sheet is not None and s.id != sheet.id:
            continue
        adj: dict[str, set[str]] = {e.id: set() for e in s.elements}
        for w in s.wires:
            if w.a.element_id in adj and w.b.element_id in adj:
                adj[w.a.element_id].add(w.b.element_id)
                adj[w.b.element_id].add(w.a.element_id)
        sources = [e.id for e in s.elements if is_flow_source(e) or e.symbol_id == "fve.grid"]
        if not sources:
            continue
        # BFS od zdrojů: rodič každého uzlu
        parent: dict[str, str | None] = dict.fromkeys(sources)
        frontier = list(sources)
        while frontier:
            nxt = []
            for eid in frontier:
                for n in adj[eid]:
                    if n not in parent:
                        parent[n] = eid
                        nxt.append(n)
            frontier = nxt
        by_id = {e.id: e for e in s.elements}
        for e in s.elements:
            if e.symbol_id not in breakers or e.id not in parent:
                continue
            p = parent[e.id]
            while p is not None and by_id[p].symbol_id not in breakers:
                p = parent.get(p)
            if p is None:
                continue
            up = by_id[p]
            i_lo, i_hi = _f(e.attrs.get("in_")), _f(up.attrs.get("in_"))
            if not (i_lo and i_hi):
                continue
            if i_hi < i_lo:
                msg = f"nadřazený {up.ref} ({i_hi:g} A) má menší In než {e.ref} ({i_lo:g} A)"
            elif i_hi / i_lo < SELECTIVITY_RATIO:
                msg = f"poměr In {i_hi:g}/{i_lo:g} = {i_hi / i_lo:.2f} < {SELECTIVITY_RATIO} – selektivita nejistá (ověřit křivky)"
            else:
                msg = "OK"
            out.append((e.ref, up.ref, i_lo, i_hi, msg))
    return out


# ---- selektivita podél řetězce přes listy (F2, krok 7) --------------------------------------------------------------
# role přístroje v řetězci FVE – atribut `chain` (zapisuje generátor; ruční projekt ho mít nemusí)
CHAIN_ROLES = ("inv", "rfve_main", "fve_out", "main", "meter_main", "inst_switch", "hds")
# odpínače (i přepínač sítí EPS): In nesmí být pod In jištění, které je chrání
SWITCH_DEVICES = frozenset({"sb.main_switch", "fve.changeover_switch"})
# ostatní dvojice přes list stačí In nadřazeného ≥ In přístroje (jištění střídače ≤ vývod FVE v RD/HR, hlavní
# přístroj RD/HR ≤ HJ před elektroměrem); dvojice, kde nadřazené jištění musí být větší (vývod FVE < hlavní jistič RD/HR, HJ / hlavní přístroj < pojistky HDS);
# dva jističe pod sebou navíc s poměrem In ≥ `SELECTIVITY_RATIO`
CHAIN_STRICT = frozenset({("fve_out", "main"), ("fve_out", "meter_main"), ("meter_main", "hds"), ("main", "hds"),
                          ("fve_out", "hds")})
_BREAKERS = frozenset({"fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo"})


@dataclass
class ChainSelectivity:
    """Nález selektivity v řetězci: přístroj (list, prvek), nadřazené jištění a hlášení."""
    sheet: Sheet
    element: Element
    upper: Element
    upper_sheet: Sheet
    msg: str


def _chain_role(e: Element) -> str:
    if e.symbol_id == "fve.hds":
        return "hds"
    return str(e.attrs.get("chain") or "").strip()


def check_selectivity_tree(project: Project, lib) -> list[ChainSelectivity]:
    """Selektivita podél řetězce přes listy nad stromem jednopólového schématu (`single_line.build_tree`, od DS):
    ke každému jisticímu přístroji (`SELECTIVITY_DEVICES`) nejbližší nadřazené jištění směrem ke zdroji. Hodnotí se
    jen dvojice přes hranici listu (uvnitř listu je `check_selectivity`) – nadřazený s menším In vždy; s rolemi
    `chain` (generátor) rovnost u `CHAIN_STRICT` (a poměr dvou jističů < `SELECTIVITY_RATIO`). Odpínač
    (`SWITCH_DEVICES`) s In pod In nejbližšího nadřazeného jištění – i na témže listu. Přístroje bez In se
    přeskočí (hlásí je `checks.protection_findings`); cesta přes rozvaděč jen jako blok bez listu
    (`project.is_block_only` – stávající RD / HR / RE, RFVE.AC bez mustru) se nehodnotí (jeho přístroje nejsou
    nakreslené); nic se nepřepisuje."""
    from envocad.model.project import is_block_only
    from envocad.model.single_line import build_tree
    try:
        _root, nodes = build_tree(project, lib)
    except (KeyError, ValueError, AttributeError):
        return []
    out: list[ChainSelectivity] = []
    for n in nodes.values():
        e = n.element
        switch = e.symbol_id in SWITCH_DEVICES
        if e.symbol_id not in SELECTIVITY_DEVICES and not switch:
            continue
        u = n.parent
        while u is not None and u.element.symbol_id not in SELECTIVITY_DEVICES:
            if u.element.symbol_id == "fve.switchboard" and is_block_only(project, u.element):
                u = None              # rozvaděč jen jako blok (bez listu): jeho přístroje neznáme – nehodnotí se
                break
            u = u.parent
        if u is None:
            continue
        up = u.element
        i_lo, i_hi = _f(e.attrs.get("in_")), _f(up.attrs.get("in_"))
        if not (i_lo and i_hi):
            continue
        name, uname = e.ref or e.symbol_id, up.ref or up.symbol_id
        where = f"{name} ({n.sheet.name}) → {uname} ({u.sheet.name})"
        if switch:
            if i_lo < i_hi:
                out.append(ChainSelectivity(n.sheet, e, up, u.sheet,
                                            f"odpínač {where}: In {i_lo:g} A je pod In jištění {i_hi:g} A, které ho "
                                            "chrání – zvolte odpínač s In ≥ jištění"))
            continue
        if u.sheet.id == n.sheet.id:
            continue
        pair = (_chain_role(e), _chain_role(up))
        if i_hi < i_lo:
            out.append(ChainSelectivity(n.sheet, e, up, u.sheet,
                                        f"{where}: nadřazené jištění má menší In ({i_hi:g} A < {i_lo:g} A)"))
        elif pair in CHAIN_STRICT and i_hi <= i_lo:
            out.append(ChainSelectivity(n.sheet, e, up, u.sheet,
                                        f"{where}: stejné In {i_lo:g} A – nadřazené jištění musí být větší"))
        elif pair in CHAIN_STRICT and e.symbol_id in _BREAKERS and up.symbol_id in _BREAKERS \
                and i_hi / i_lo < SELECTIVITY_RATIO:
            out.append(ChainSelectivity(n.sheet, e, up, u.sheet,
                                        f"{where}: poměr In {i_hi:g}/{i_lo:g} = {i_hi / i_lo:.2f} < "
                                        f"{SELECTIVITY_RATIO} – selektivita nejistá"))
    return out
