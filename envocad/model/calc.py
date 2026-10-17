"""Výpočty z modelu (bez Qt): stringy vs. střídač, proud a úbytek napětí na kabelech, zatížitelnost Iz
dle ČSN 33 2000-5-52 (zjednodušené tabulky), soulad jištění s kabelem (In ≤ Iz) a základní selektivita.

Hodnoty Iz jsou tabulky A.52 pro Cu/PVC 70 °C při 30 °C okolí (B.52.x) – přepsané z normy, označené
„orientační“: pro průkaz použijte normu. Výsledky jdou do kontroly projektu (F7) a do výkazu „Výpočty“.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

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
METHOD_HINTS = [("zem", "D"), ("výkop", "D"), ("vzduch", "E"), ("lávk", "E"), ("rošt", "E"), ("žlab", "E"),
                ("trubk", "B1"), ("lišt", "B1"), ("chránič", "B1"), ("zatepl", "A1"), ("izolac", "A1"),
                ("stěn", "C"), ("omítk", "C"), ("příchytk", "C")]


def _f(v, default: float | None = None) -> float | None:
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return default


def route_method(w: Wire) -> str:
    m = (w.attrs.get("method") or "").strip().upper()
    if m in IZ_3:
        return m
    text = (w.attrs.get("route") or "").lower()
    for key, meth in METHOD_HINTS:
        if key in text:
            return meth
    return "C"


def ampacity(cross: float, method: str = "C", loaded: int = 3, aluminium: bool = False, t_ambient: float = 30.0,
             grouping: float = 1.0) -> float | None:
    table = IZ_3.get(method, IZ_3["C"])
    sizes = sorted(table)
    size = next((s for s in sizes if s >= cross - 1e-6), None)
    if size is None:
        return None
    iz = table[size]
    if size != cross:  # průřez mimo řadu: lineární odhad
        iz = iz * cross / size
    if loaded <= 2:
        iz *= IZ_2_FACTOR
    if aluminium:
        iz *= AL_FACTOR
    # teplotní činitel (tab. B.52.14 pro PVC, orientační): 30 °C 1,0; 35 °C 0,94; 40 °C 0,87; 45 °C 0,79; 50 °C 0,71
    k_t = {30: 1.0, 35: 0.94, 40: 0.87, 45: 0.79, 50: 0.71}
    kt = k_t.get(int(round(t_ambient / 5) * 5), 1.0 if t_ambient <= 30 else 0.71)
    return round(iz * kt * grouping, 1)


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

    @classmethod
    def from_attrs(cls, a: dict) -> InverterData:
        """Z atributů prvku `fve.inverter*` (nebo `Component.attr_values()` artiklu střídače)."""
        mppt = _f(a.get("mppt"))
        spm = _f(a.get("strings_per_mppt"))
        return cls(u_dc_max=_f(a.get("u_dc_max")), u_mppt_min=_f(a.get("u_mppt_min")),
                   u_mppt_max=_f(a.get("u_mppt_max")), i_mppt_max=_f(a.get("i_mppt_max")),
                   isc_mppt_max=_f(a.get("isc_mppt_max")), mppt=int(mppt) if mppt and mppt >= 1 else None,
                   strings_per_mppt=int(spm) if spm and spm >= 1 else None, p_ac=_f(a.get("p_ac")),
                   p_dc_max=_f(a.get("p_dc_max")))


@dataclass
class StringLimits:
    """Meze stringu pro dvojici modul + střídač: počet modulů ve stringu n_min…n_max (None = bez horní meze – chybí
    Umax i MPPT max), nejvýš n_par_max paralelních stringů na jeden MPPT; `reasons` = české důvody pro průvodce."""
    n_min: int
    n_max: int | None
    n_par_max: int
    reasons: list[str] = field(default_factory=list)

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


def _voltage_issues(m: ModuleData, inv: InverterData | None, n: int, t_min: float, t_max: float) -> list[str]:
    uoc_cold, umpp_hot, umpp_cold = _u_strings(m, n, t_min, t_max)
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


def string_issues(m: ModuleData, inv: InverterData | None, n: int, n_par: int = 1, t_min: float = T_MIN_DEFAULT,
                  t_max: float = T_MAX_DEFAULT) -> list[str]:
    """České hlášky ke stringu n modulů, n_par paralelních stringů na stejném MPPT (prázdný seznam = vyhovuje).
    Texty sdílí kontrola projektu (F7), výkaz Výpočty i asistent průvodce; „– omezení výkonu“ je jen varování."""
    out = []
    if not n or not m.voc:
        out.append("chybí počet modulů nebo Uoc modulu")
    if inv is None:
        out.append("string není propojen se střídačem")
    out += _voltage_issues(m, inv, n, t_min, t_max)
    if inv is not None:
        out += _current_issues(m, inv, n_par)
        if not (inv.u_dc_max or inv.u_mppt_min):
            out.append("střídač nemá zadané Umax / rozsah MPPT (doplňte z artiklu)")
    return out


N_MODULES_LIMIT = 200   # strop hledání horní meze počtu modulů ve stringu (bez Umax / MPPT max → None)


def string_limits(m: ModuleData, inv: InverterData, t_min: float = T_MIN_DEFAULT,
                  t_max: float = T_MAX_DEFAULT) -> StringLimits:
    """Rozsah počtu modulů ve stringu a paralelních stringů na MPPT – konzistentní se `string_issues`:
    n_max = ⌊min(Umax, Umax systému modulu) / Uoc(t_min)⌋ a ⌊Umppt max / Umpp(t_min)⌋, n_min = ⌈Umppt min / Umpp(t_max)⌉."""
    reasons: list[str] = []
    uoc1, ump_hot1, ump_cold1 = m.uoc(t_min), m.ump(t_max), m.ump(t_min)

    def fits_high(n: int, which: str) -> bool:
        return not any(which in x for x in _voltage_issues(m, inv, n, t_min, t_max))

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
        upper("Umax střídače", inv.u_dc_max, uoc1,
              f"Uoc při {t_min:g} °C {uoc1:.1f} V/modul, Umax střídače {inv.u_dc_max or 0:g} V"),
        upper("Umax systému modulu", m.u_sys_max, uoc1,
              f"Uoc při {t_min:g} °C {uoc1:.1f} V/modul, Umax systému modulu {m.u_sys_max or 0:g} V"),
        upper("Umppt max", inv.u_mppt_max, ump_cold1,
              f"Umpp při {t_min:g} °C {ump_cold1:.1f} V/modul, Umppt max {inv.u_mppt_max or 0:g} V"),
    ]
    known = [c for c in caps if c is not None]
    n_max = min(known) if known else None
    n_min = 1
    if inv.u_mppt_min and ump_hot1 > 0:
        n_min = max(1, math.ceil(inv.u_mppt_min / ump_hot1))
        while n_min > 1 and not any("Umppt min" in x for x in _voltage_issues(m, inv, n_min - 1, t_min, t_max)):
            n_min -= 1
        while n_min < N_MODULES_LIMIT and any("Umppt min" in x for x in _voltage_issues(m, inv, n_min, t_min, t_max)):
            n_min += 1
        reasons.append(f"nejméně {_modules(n_min)}: Umpp při {t_max:g} °C {ump_hot1:.1f} V/modul, "
                       f"Umppt min {inv.u_mppt_min:g} V")
    if m.vmp_from_beta and (inv.u_mppt_min or inv.u_mppt_max):
        reasons.append("Umpp z β_Voc – zjednodušení (modul nemá γ_Pmax a α_Isc)")
    if not (inv.u_dc_max or inv.u_mppt_min):
        reasons.append("střídač nemá zadané Umax / rozsah MPPT (doplňte z artiklu)")
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


def propose_strings(n_total: int, n_inverters: int, lim: StringLimits,
                    inv: InverterData) -> tuple[list[list[int]], int]:
    """Návrh stringů: n_total modulů do co nejmenšího počtu stringů v mezích `lim`, rovnoměrně délky (liší se nejvýš
    o 1 modul) i počtem na střídač; kapacita střídače = mppt · min(strings_per_mppt, n_par_max) stringů (neznámé mppt =
    bez omezení). Vrací (stringy po střídačích – délky sestupně, počet modulů, které se nevešly)."""
    n_inv = max(1, int(n_inverters or 1))
    empty: list[list[int]] = [[] for _ in range(n_inv)]
    n_total = max(0, int(n_total or 0))
    if not n_total or lim.n_max is None or lim.n_max < 1 or not lim.ok:
        return empty, n_total
    spm = inv.strings_per_mppt or DC_INPUTS_PER_MPPT_DEFAULT
    per_inv = inv.mppt * min(spm, lim.n_par_max) if inv.mppt else None
    n_str = math.ceil(n_total / lim.n_max)
    if per_inv is not None:
        n_str = min(n_str, per_inv * n_inv)
    n_str = min(n_str, n_total // max(1, lim.n_min))
    if n_str <= 0:
        return empty, n_total
    placed = min(n_total, n_str * lim.n_max)
    base, rem = divmod(placed, n_str)
    lengths = [base + 1] * rem + [base] * (n_str - rem)
    out = [lengths[i::n_inv] for i in range(n_inv)]   # střídavě: počty i délky na střídačích vyrovnané
    return out, n_total - placed


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
    conds = set(w.conductors)
    if conds & {"DC+", "DC-", "+", "-", "L+", "L-"}:
        return "dc", 0.0
    if {"L1", "L2", "L3"} <= conds:
        return "3f", 400.0
    return "1f", 230.0


def _far_ends(project: Project, s: Sheet, w: Wire) -> list[tuple[Element, str]]:
    """Konce vodiče (prvek, port); přerušovací bod ve dvojici se nahradí skutečným koncem za protějškem
    (`xref.through_interrupt` – AC kabel přes listy JPS vede ze střídače)."""
    out = []
    for end in (w.a, w.b):
        e, port = s.element(end.element_id), end.port
        if e.symbol_id == INTERRUPT_SYMBOL:
            from envocad.model.xref import through_interrupt
            hit = through_interrupt(project, s, e, port)
            if hit is not None:
                e, port = hit[1], hit[2]
        out.append((e, port))
    return out


def _source_current(project: Project, s: Sheet, w: Wire, inverter_u_dc: float | None) -> tuple[float | None, str]:
    """Proud vodičem podle zdroje na jeho konci: string (1,25·Isc), střídač AC (P/√3U), jistič (In). Konec na
    přerušovacím bodu ve dvojici se sleduje za protějšek (`_far_ends`)."""
    ends = _far_ends(project, s, w)
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


def _breaker_on_wire(s: Sheet, w: Wire) -> tuple[float | None, str]:
    for end in (w.a, w.b):
        e = s.element(end.element_id)
        if e.symbol_id in ("fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo", "fve.fuse"):
            return _f(e.attrs.get("in_")), e.ref
    return None, ""


def check_strings(project: Project, t_min: float | None = None, t_max: float | None = None) -> list[StringCheck]:
    """Kontrola každého stringu proti střídači, na který vede (přes odpínače, pojistky, svorky, DC rozvaděče).
    Teploty: zadané, jinak `design_temperatures(project)`. Stringy na stejném MPPT (střídač + DCk → MPPT, jen se
    známým `strings_per_mppt`) se počítají spolu (`n_par`) – uplatní se jen u střídače s `isc_mppt_max`. Víc stringů
    na střídači než mppt · stringů na MPPT → `capacity_issue` u stringů nad kapacitu (v pořadí vstupů DCk)."""
    d_min, d_max = design_temperatures(project)
    t_min = d_min if t_min is None else t_min
    t_max = d_max if t_max is None else t_max
    found = []
    for s in project.sheets:
        for e in s.elements:
            if e.symbol_id != "fve.pv_string":
                continue
            inv_el, port = _trace_inverter(project, s, e)
            inv = InverterData.from_attrs(inv_el.attrs) if inv_el is not None else None
            mt = re.fullmatch(r"DC(\d+)", port or "")
            pnum = int(mt.group(1)) if mt else None
            found.append((s, e, inv_el, inv, port_mppt(pnum, inv), pnum))
    groups: dict[tuple[str, int], int] = {}
    per_inv: dict[str, list[int]] = {}
    for i, (_s, _e, inv_el, _inv, mppt, _p) in enumerate(found):
        if inv_el is not None:
            per_inv.setdefault(inv_el.id, []).append(i)
            if mppt is not None:
                groups[(inv_el.id, mppt)] = groups.get((inv_el.id, mppt), 0) + 1
    over: dict[int, str] = {}
    for idx in per_inv.values():
        inv_el, inv = found[idx[0]][2], found[idx[0]][3]
        msg = capacity_issue(inv_el.ref, inv, len(idx))
        if msg:
            ordered = sorted(idx, key=lambda i: (found[i][5] is None, found[i][5] or 0, i))
            over.update(dict.fromkeys(ordered[inverter_capacity(inv):], msg))
    out = []
    for i, (s, e, inv_el, inv, mppt, _p) in enumerate(found):
        n = int(_f(e.attrs.get("n_modules"), 0) or 0)
        m = ModuleData.from_attrs(e.attrs) or ModuleData(voc=0.0, vmp=0.0, isc=_f(e.attrs.get("isc")) or 0.0,
                                                         imp=_f(e.attrs.get("imp")),
                                                         beta_voc=_f(e.attrs.get("beta_voc")) or BETA_VOC_DEFAULT,
                                                         u_sys_max=_f(e.attrs.get("u_sys_max")),
                                                         alpha_isc=_f(e.attrs.get("alpha_isc")),
                                                         gamma_pmax=_f(e.attrs.get("gamma_pmax")))
        n_par = groups.get((inv_el.id, mppt), 1) if inv_el is not None and mppt is not None else 1
        uoc_cold, umpp_hot, _umpp_cold = _u_strings(m, n, t_min, t_max)
        sc = StringCheck(e.ref, n, uoc_cold, umpp_hot, m.isc, inv_el.ref if inv_el else "",
                         inv.u_dc_max if inv else None, inv.u_mppt_min if inv else None,
                         inv.u_mppt_max if inv else None, inv.i_mppt_max if inv else None,
                         sheet=s.name, mppt=mppt, n_par=n_par, isc_mppt_max=inv.isc_mppt_max if inv else None,
                         t_min=t_min, t_max=t_max)
        sc.issues = string_issues(m, inv, n, n_par, t_min, t_max) + ([over[i]] if i in over else [])
        out.append(sc)
    return out


_PASS_THROUGH = ("fve.dc_disconnect", "fve.fuse", "fve.terminal", "sb.terminal_block", "fve.spd", "fve.switchboard",
                 "sb.feed_in", "sb.feed_out", "fve.interrupt")
_INVERTERS = ("fve.inverter", "fve.inverter_hybrid")


def _find_inverter(project: Project, s: Sheet, start: Element, max_depth: int = 8) -> Element | None:
    seen = {start.id}
    frontier = [start.id]
    for _ in range(max_depth):
        nxt = []
        for eid in frontier:
            for w in s.wires:
                for end, other in ((w.a, w.b), (w.b, w.a)):
                    if end.element_id == eid and other.element_id not in seen:
                        o = s.element(other.element_id)
                        if o.symbol_id in _INVERTERS:
                            return o
                        if o.symbol_id in _PASS_THROUGH:
                            seen.add(o.id)
                            nxt.append(o.id)
        frontier = nxt
        if not frontier:
            break
    return None


def _block_exit(s: Sheet, block: Element, port: str) -> str | None:
    """Průchod blokem DC rozvaděče: vstup X{k} ↔ výstup X{k + N/2} (N = počet zapojených portů X…, jako u generátoru).
    Jiné zapojení → None (nejednoznačné)."""
    nums = sorted({int(mm.group(1)) for w in s.wires for end in (w.a, w.b) if end.element_id == block.id
                   and (mm := re.fullmatch(r"X(\d+)", end.port or ""))})
    mk = re.fullmatch(r"X(\d+)", port or "")
    if not mk or len(nums) % 2 or int(mk.group(1)) not in nums:
        return None
    i = nums.index(int(mk.group(1)))
    half = len(nums) // 2
    return f"X{nums[i + half]}" if i < half else None


def _trace_inverter(project: Project, s: Sheet, start: Element, max_depth: int = 8) -> tuple[Element | None, str]:
    """(střídač, port střídače) pro string: střídač jako `_find_inverter`; port jen při jednoznačném řetězci
    vodičů (přes průchozí prvky, bloky DC rozvaděčů párem portů), jinak "" (MPPT nezjištěn → bez sčítání proudů)."""
    inv = _find_inverter(project, s, start, max_depth)
    if inv is None:
        return None, ""
    cur, entered = start, None
    visited = {start.id}
    for _ in range(max_depth + 1):
        exit_port = _block_exit(s, cur, entered) if cur.symbol_id == "fve.switchboard" else None
        if cur.symbol_id == "fve.switchboard" and exit_port is None:
            return inv, ""
        nxt = []
        for w in s.wires:
            for end, other in ((w.a, w.b), (w.b, w.a)):
                if end.element_id != cur.id or other.element_id in visited:
                    continue
                if exit_port is not None and end.port != exit_port:
                    continue
                if exit_port is None and entered is not None and end.port == entered:
                    continue
                nxt.append(other)
        if len({(o.element_id, o.port) for o in nxt}) != 1:
            return inv, ""
        o = nxt[0]
        el = s.element(o.element_id)
        if el.symbol_id in _INVERTERS:
            return (inv, o.port) if el.id == inv.id else (inv, "")
        if el.symbol_id not in _PASS_THROUGH:
            return inv, ""
        visited.add(el.id)
        cur, entered = el, o.port
    return inv, ""


def check_cables(project: Project, t_ambient: float = 30.0, du_limit_pct: float = 3.0) -> list[CableCheck]:
    out = []
    for s in project.sheets:
        for w in s.wires:
            if not (w.attrs.get("ref") or w.attrs.get("cable") or w.attrs.get("cross")):
                continue
            cross = _f(w.attrs.get("cross"))
            length = _f(w.attrs.get("length"))
            system, u = _wire_system(w)
            alu = "AYKY" in (w.attrs.get("cable") or "").upper() or "AL" in (w.attrs.get("cable") or "").upper().split()
            i_a, _src = _source_current(project, s, w, None)
            if system == "dc":
                # napětí stringu pro úbytek: Umpp ≈ n·vmp z připojeného stringu
                for e, _port in _far_ends(project, s, w):
                    if e.symbol_id == "fve.pv_string":
                        n = _f(e.attrs.get("n_modules"), 0) or 0
                        vmp = _f(e.attrs.get("vmp")) or (_f(e.attrs.get("voc")) or 0) * 0.82
                        u = n * vmp
            method = route_method(w)
            loaded = 3 if system == "3f" else 2
            iz = ampacity(cross, method, loaded, alu, t_ambient) if cross else None
            in_b, bref = _breaker_on_wire(s, w)
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
            if du_pct is not None and du_pct > du_limit_pct:
                cc.issues.append(f"úbytek {du_pct} % > {du_limit_pct:g} %")
            if length is None and not s.is_switchboard:
                cc.issues.append("chybí délka (úbytek nespočítán)")
            out.append(cc)
    return out


def check_selectivity(project: Project, sheet: Sheet | None = None) -> list[tuple[str, str, float, float, str]]:
    """Dvojice jistič → nadřazený jistič po cestě ke zdroji; vrací (dolní, horní, In_d, In_h, hlášení).
    `sheet` = jen dvojice na tomto listu (výkaz pro jeden list), jinak všechny listy."""
    from envocad.model.multipole import SOURCE_SYMBOLS
    out = []
    breakers = {"fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo", "fve.fuse"}
    for s in project.sheets:
        if sheet is not None and s.id != sheet.id:
            continue
        adj: dict[str, set[str]] = {e.id: set() for e in s.elements}
        for w in s.wires:
            if w.a.element_id in adj and w.b.element_id in adj:
                adj[w.a.element_id].add(w.b.element_id)
                adj[w.b.element_id].add(w.a.element_id)
        sources = [e.id for e in s.elements if e.symbol_id in SOURCE_SYMBOLS | {"fve.grid"}]
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
