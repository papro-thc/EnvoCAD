"""Výpočty z modelu (bez Qt): stringy vs. střídač, proud a úbytek napětí na kabelech, zatížitelnost Iz
dle ČSN 33 2000-5-52 (zjednodušené tabulky), soulad jištění s kabelem (In ≤ Iz) a základní selektivita.

Hodnoty Iz jsou tabulky A.52 pro Cu/PVC 70 °C při 30 °C okolí (B.52.x) – přepsané z normy, označené
„orientační“: pro průkaz použijte normu. Výsledky jdou do kontroly projektu (F7) a do výkazu „Výpočty“.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from envocad.model.project import Element, Project, Sheet, Wire

RHO_CU, RHO_AL = 0.0225, 0.036      # Ω·mm²/m při provozní teplotě ~70 °C (orientační)
T_MIN_DEFAULT, T_MAX_DEFAULT = -10.0, 70.0  # °C: nejnižší okolí (Uoc), teplota článku při plném slunci (Umpp)
BETA_VOC_DEFAULT = -0.27            # %/K (krystalický Si; z datasheetu modulu `beta_voc`)
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


def _source_current(project: Project, s: Sheet, w: Wire, inverter_u_dc: float | None) -> tuple[float | None, str]:
    """Proud vodičem podle zdroje na jeho konci: string (1,25·Isc), střídač AC (P/√3U), jistič (In)."""
    for end in (w.a, w.b):
        e = s.element(end.element_id)
        if e.symbol_id == "fve.pv_string":
            isc = _f(e.attrs.get("isc"))
            if isc:
                return round(SAFETY_ISC * isc, 2), f"1,25·Isc stringu {e.ref}"
        if e.symbol_id in ("fve.inverter", "fve.inverter_hybrid") and end.port == "AC":
            p = _f(e.attrs.get("p_ac"))
            if p:
                ph = _f(e.attrs.get("phases"), 3)
                i = p * 1000 / (3 ** 0.5 * 400) if ph == 3 else p * 1000 / 230
                return round(i, 1), f"P_AC střídače {e.ref}"
    for end in (w.a, w.b):
        e = s.element(end.element_id)
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


def check_strings(project: Project, t_min: float = T_MIN_DEFAULT, t_max: float = T_MAX_DEFAULT) -> list[StringCheck]:
    out = []
    for s in project.sheets:
        for e in s.elements:
            if e.symbol_id != "fve.pv_string":
                continue
            n = int(_f(e.attrs.get("n_modules"), 0) or 0)
            voc = _f(e.attrs.get("voc")) or 0.0
            vmp = _f(e.attrs.get("vmp")) or (voc * 0.82 if voc else 0.0)
            isc = _f(e.attrs.get("isc")) or 0.0
            beta = (_f(e.attrs.get("beta_voc")) or BETA_VOC_DEFAULT) / 100.0
            uoc_cold = round(n * voc * (1 + beta * (t_min - 25)), 1)
            umpp_hot = round(n * vmp * (1 + beta * (t_max - 25)), 1)
            umpp_cold = round(n * vmp * (1 + beta * (t_min - 25)), 1)
            # střídač: po vodičích až k prvnímu střídači (přes odpínač/pojistky/svorky)
            inv = _find_inverter(project, s, e)
            sc = StringCheck(e.ref, n, uoc_cold, umpp_hot, isc, inv.ref if inv else "",
                             _f(inv.attrs.get("u_dc_max")) if inv else None, _f(inv.attrs.get("u_mppt_min")) if inv else None,
                             _f(inv.attrs.get("u_mppt_max")) if inv else None, _f(inv.attrs.get("i_mppt_max")) if inv else None)
            if not n or not voc:
                sc.issues.append("chybí počet modulů nebo Uoc modulu")
            if inv is None:
                sc.issues.append("string není propojen se střídačem")
            else:
                if sc.u_dc_max and uoc_cold > sc.u_dc_max:
                    sc.issues.append(f"Uoc při {t_min:g} °C {uoc_cold} V > Umax střídače {sc.u_dc_max:g} V")
                if sc.u_mppt_min and umpp_hot and umpp_hot < sc.u_mppt_min:
                    sc.issues.append(f"Umpp při {t_max:g} °C {umpp_hot} V < Umppt min {sc.u_mppt_min:g} V")
                if sc.u_mppt_max and umpp_cold and umpp_cold > sc.u_mppt_max:
                    sc.issues.append(f"Umpp při {t_min:g} °C {umpp_cold} V > Umppt max {sc.u_mppt_max:g} V (mimo rozsah sledování)")
                if sc.i_mppt_max and isc and SAFETY_ISC * isc > sc.i_mppt_max:
                    sc.issues.append(f"1,25·Isc {SAFETY_ISC * isc:.1f} A > Imax vstupu {sc.i_mppt_max:g} A")
                if not (sc.u_dc_max or sc.u_mppt_min):
                    sc.issues.append("střídač nemá zadané Umax / rozsah MPPT (doplňte z artiklu)")
            out.append(sc)
    return out


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
                        if o.symbol_id in ("fve.inverter", "fve.inverter_hybrid"):
                            return o
                        if o.symbol_id in ("fve.dc_disconnect", "fve.fuse", "fve.terminal", "sb.terminal_block",
                                           "fve.spd", "fve.switchboard", "sb.feed_in", "sb.feed_out", "fve.interrupt"):
                            seen.add(o.id)
                            nxt.append(o.id)
        frontier = nxt
        if not frontier:
            break
    return None


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
                for end in (w.a, w.b):
                    e = s.element(end.element_id)
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


def check_selectivity(project: Project) -> list[tuple[str, str, float, float, str]]:
    """Dvojice jistič → nadřazený jistič po cestě ke zdroji; vrací (dolní, horní, In_d, In_h, hlášení)."""
    from envocad.model.multipole import SOURCE_SYMBOLS
    out = []
    breakers = {"fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo", "fve.fuse"}
    for s in project.sheets:
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
