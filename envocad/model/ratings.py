"""Kontroly z údajů artiklů (F7) – bez Qt. Návrh: docs/design/kontroly_artiklu.md.

Zkratová odolnost (Icu přístroje, Icw rozvaděče vs. Ik), svodiče (Uc vs. síť, Ucpv vs. Uoc stringu, Up vs. Uw,
typ 1 při jímací soustavě), svorky (průřez vodiče vs. max. průřez svorky, In svorky vs. In jištění) a jmenovité
napětí přístrojů (AC síť, DC Uoc stringů). Údaj se bere z atributu prvku, jinak z přiřazeného artiklu; chybějící
údaj = žádná chyba (nejvýš jedna informace na list). In jištění vs. Iz kabelu (i I2 ≤ 1,45·Iz) je v `calc.check_cables`.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from envocad.model import calc
from envocad.model.checks import ERROR, INFO, WARNING, Finding
from envocad.model.feed import is_feed
from envocad.model.project import Element, Project, Sheet, conductor_name, linked_wire

UO_DEFAULT = 230.0           # V – napětí fáze proti zemi sítě nn, když rozvaděč neuvádí jinak (`un` „230/400 V“)
SPD_UC_FACTOR = 1.1          # ČSN 33 2000-5-534: Uc ≥ 1,1·Uo (TN, TT); IT: Uc ≥ √3·Uo
U_NN = 400.0                 # V – sdružené napětí pro výpočet Ik transformátoru na straně nn
BREAKERS = frozenset({"fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo"})          # přístroje s Icu / Icn
PROTECTION = frozenset(calc._PROTECTION)
TERMINAL_SYMBOLS = frozenset({"fve.terminal", "sb.terminal_block"})
# přístroje, u nichž `un` / artikl `un_v` je jmenovité napětí obvodu (ne napětí střídače, baterie, elektroměru)
UN_SYMBOLS = frozenset({"fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo", "sb.rcd", "fve.fuse", "fve.fuse_disconnect",
                        "fve.dc_disconnect", "fve.switch_disconnector", "sb.main_switch", "fve.contactor",
                        "fve.changeover_switch", *TERMINAL_SYMBOLS})
UN_CATEGORIES = frozenset({"mcb", "mccb", "rcd", "rcbo", "switch", "contactor", "fuse", "fuse_holder", "terminal"})
_NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
_UCPV_NOTE = re.compile(r"U\s*C\s*PV\s*(\d+(?:[.,]\d+)?)\s*V", re.IGNORECASE)
_T1 = re.compile(r"\bT1\b|\bI\s*\+\s*II\b|\bTYP\s*1\b", re.IGNORECASE)


def _nums(v) -> list[float]:
    return [float(x.replace(",", ".")) for x in _NUM.findall(str(v or ""))]


def first_num(v) -> float | None:
    """První číslo v textu („6 kA“ → 6, „3,8“ → 3,8, „1000 V DC“ → 1000), jinak None."""
    n = _nums(v)
    return n[0] if n else None


def max_num(v) -> float | None:
    """Největší číslo v textu („230/400 V“ → 400), jinak None."""
    n = _nums(v)
    return max(n) if n else None


def _g(x: float) -> str:
    return f"{x:g}".replace(".", ",")


class Data:
    """Údaje prvku: neprázdný atribut prvku, jinak parametr přiřazeného artiklu (`lib.component`)."""

    def __init__(self, lib=None):
        self.lib = lib
        self._cache: dict[str, object] = {}

    def comp(self, e: Element):
        cid = e.component_id
        if not cid or self.lib is None or not hasattr(self.lib, "component"):
            return None
        if cid not in self._cache:
            try:
                self._cache[cid] = self.lib.component(cid)
            except Exception:  # noqa: BLE001 – knihovna nedostupná → jen atributy
                self._cache[cid] = None
        return self._cache[cid]

    def text(self, e: Element, attr: str, param: str = "") -> str:
        v = str(e.attrs.get(attr) or "").strip()
        if v or not param:
            return v
        c = self.comp(e)
        return str((c.params.get(param) if c is not None else "") or "").strip()

    def num(self, e: Element, attr: str, param: str = "") -> float | None:
        return first_num(self.text(e, attr, param))

    def note(self, e: Element) -> str:
        c = self.comp(e)
        return str(c.params.get("note") or "") if c is not None else ""

    def category(self, e: Element) -> str:
        c = self.comp(e)
        return getattr(c, "category", "") if c is not None else ""


# ---- prostředí: síť, napětí, zkratový proud --------------------------------------------------------------------
@dataclass
class Board:
    """Údaje rozvaděče (list rozvaděče a jeho blok) pro kontroly; list mimo rozvaděč = výchozí síť TN 230/400 V."""
    network: str = "TN"          # TN / TT / IT (AC část)
    uo: float = UO_DEFAULT
    ik: float | None = None      # Ik v rozvaděči [kA] (atribut `ik_ka` bloku nebo parametr skříně)
    icw: float | None = None     # zkratová odolnost rozvaděče [kA] (parametr skříně `icw`, atribut bloku `icw`)
    lps: bool = False            # objekt s jímací soustavou (parametr skříně `wire_spd_lps` = yes)


def _ac_part(text: str) -> str:
    """AC část popisu sítě („3NPE, 50 Hz / DC IT“ → „3NPE, 50 Hz“)."""
    return " / ".join(p for p in str(text or "").split("/") if "DC" not in p.upper())


def board_of(project: Project, s: Sheet) -> Board:
    if not s.is_switchboard:
        return Board()
    p = s.layout.params or {}
    block = None
    if s.parent_element_id:
        bs = project.sheet_of_element(s.parent_element_id)
        block = bs.element(s.parent_element_id) if bs is not None else None
    battrs = block.attrs if block is not None else {}
    net = _ac_part(p.get("network", "")).upper()
    network = "IT" if re.search(r"\bIT\b", net) else ("TT" if re.search(r"\bTT\b", net) else "TN")
    un = [x for x in _nums(_ac_part(p.get("un", ""))) if 100 <= x <= 1000]
    uo = min(un) if un and min(un) < 300 else (min(un) / math.sqrt(3) if un else UO_DEFAULT)
    ik = first_num(battrs.get("ik_ka")) or first_num(p.get("ik_ka"))
    icw = first_num(p.get("icw")) or first_num(battrs.get("icw")) or first_num(battrs.get("icw_ka"))
    lps = str(p.get("wire_spd_lps") or "").strip().lower() in ("yes", "ano", "1", "true")
    return Board(network, round(uo, 1), ik, icw, lps)


def transformer_ik_ka(sn_kva: float, uk_pct: float, u_v: float = U_NN) -> float:
    """Počáteční souměrný zkratový proud na svorkách nn transformátoru při tvrdé síti vn: Sn / (√3 · U · uk)."""
    return round(sn_kva * 1000 / (math.sqrt(3) * u_v * uk_pct / 100) / 1000, 1)


def upstream_ik(project: Project) -> tuple[float, str] | None:
    """Horní odhad Ik pro celý projekt: `meta["ik_ka"]` (zkratový proud v místě připojení – Vlastnosti projektu),
    jinak největší Ik na svorkách nn transformátorů projektu (atributy `sn` [kVA] a `uk` [%]). Neznámé → None."""
    v = first_num((project.meta or {}).get("ik_ka"))
    if v:
        return v, "v místě připojení (Vlastnosti projektu)"
    best = None
    for s in project.sheets:
        for e in s.elements:
            if e.symbol_id != "fve.transformer":
                continue
            sn, uk = first_num(e.attrs.get("sn")), first_num(e.attrs.get("uk"))
            if sn and uk and uk > 0:
                ik = transformer_ik_ka(sn, uk)
                if best is None or ik > best[0]:
                    best = (ik, f"na svorkách nn {e.ref or 'TR'} (Sn {_g(sn)} kVA, uk {_g(uk)} %)")
    return best


def design_t_min_given(project: Project) -> bool:
    """Návrhová nejnižší teplota stringů je zadaná v projektu (`meta["pv_t_min"]`); jinak se počítá s předpokladem
    `calc.T_MIN_DEFAULT` a nálezy z Uoc při t_min jsou jen informace (jako oteplení s předpokládanými mezemi)."""
    return calc.parse_temperature((project.meta or {}).get("pv_t_min")) is not None


def _assumed_text(what: str) -> str:
    return (f"{what} při předpokládané t_min {_g(calc.T_MIN_DEFAULT).replace('-', '−')} °C (návrhová teplota "
            "v projektu není zadaná – zadejte ji ve Vlastnostech projektu)")


def _touching(s: Sheet, e: Element):
    return [w for w in s.wires if w.touches(e.id)]


def is_dc(s: Sheet, e: Element, data: Data) -> bool:
    """Prvek na straně DC: vodič s žilami +/− (L+/L−), jinak údaj artiklu / atributu („DC“ v typu SPD, v Uc,
    poznámka artiklu začíná „DC“)."""
    systems = {calc._wire_system(w)[0] for w in _touching(s, e) if not set(w.conductors) <= {"PE"}}
    if systems:
        return "dc" in systems
    marks = f"{data.text(e, 'spd_type', 'spd_type')} {e.attrs.get('uc', '')}".upper()
    return bool(re.search(r"\bDC\b", marks)) or data.note(e).strip().upper().startswith("DC")


def _three_phase(s: Sheet, e: Element, data: Data) -> bool:
    poles = data.num(e, "poles", "poles")
    if poles is not None and poles >= 3:
        return True
    return any({"L1", "L2", "L3"} <= {conductor_name(c) for c in w.conductors} for w in _touching(s, e))


class _Infos:
    """Informace sloučené po listu a kódu (jedna položka se seznamem označení)."""

    def __init__(self):
        self.items: dict[tuple[str, str], list] = {}

    def add(self, s: Sheet, code: str, e: Element | None, detail: str) -> None:
        self.items.setdefault((s.id, code), [s, e, []])[2].append(detail)

    def findings(self, texts: dict[str, str]) -> list[Finding]:
        out = []
        for (_sid, key), (s, e, details) in self.items.items():
            code = key.removesuffix("_t")      # „…_t“ = totéž s předpokládanou návrhovou teplotou
            shown = "; ".join(details[:6]) + ("; …" if len(details) > 6 else "")
            out.append(Finding(INFO, s.id, s.name, e.id if e is not None else "", False, "", f"{texts[key]}: {shown}",
                               code))
        return out


# ---- 2. zkratová odolnost -------------------------------------------------------------------------------------
def short_circuit_findings(project: Project, data: Data) -> list[Finding]:
    """Icu/Icn jističů ≥ Ik rozvaděče (`sc_icu`, varování – kaskádu / záložní jištění nehodnotíme), Icw rozvaděče ≥ Ik
    (`sc_icw`, chyba), Icu ≥ Icw rozvaděče bez zadaného Ik (`sc_icu_icw`, varování). Bez Ik rozvaděče: horní odhad
    Ik projektu (`upstream_ik`) nad Icu / Icw → jedna informace na list (`sc_upstream`). Jen AC přístroje."""
    out: list[Finding] = []
    up = upstream_ik(project)
    infos = _Infos()
    for s in project.sheets:
        if not s.is_switchboard:
            continue
        b = board_of(project, s)
        if b.ik and b.icw and b.icw < b.ik - 1e-9:
            out.append(Finding(ERROR, s.id, s.name, "", False, s.loc,
                               f"Zkratová odolnost rozvaděče Icw {_g(b.icw)} kA < Ik {_g(b.ik)} kA v rozvaděči", "sc_icw"))
        if not b.ik and up and b.icw and b.icw < up[0] - 1e-9:
            infos.add(s, "sc_upstream", None, f"rozvaděč Icw {_g(b.icw)} kA")
        for e in s.elements:
            if e.symbol_id not in BREAKERS or is_dc(s, e, data):
                continue
            icu = data.num(e, "icu", "icu_ka")
            if not icu:
                continue
            name = e.ref or e.symbol_id
            if b.ik:
                if icu < b.ik - 1e-9:
                    out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                       f"Vypínací schopnost {name} Icu {_g(icu)} kA < Ik {_g(b.ik)} kA v rozvaděči – "
                                       "zvolte přístroj s vyšší Icu, nebo doložte záložní jištění (kaskádu)", "sc_icu"))
            elif b.icw and icu < b.icw - 1e-9:
                out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                   f"Vypínací schopnost {name} Icu {_g(icu)} kA < zkratová odolnost rozvaděče Icw "
                                   f"{_g(b.icw)} kA – zadejte Ik v rozvaděči (ik_ka) nebo zvolte přístroj s vyšší Icu",
                                   "sc_icu_icw"))
            elif up and icu < up[0] - 1e-9:
                infos.add(s, "sc_upstream", e, f"{name} Icu {_g(icu)} kA")
    if up:
        out += infos.findings({"sc_upstream": f"Ik {up[1]} až {_g(up[0])} kA (horní odhad) – ověřte Ik v rozvaděči "
                                              "(atribut ik_ka bloku / parametr skříně)"})
    return out


# ---- 3. svodiče přepětí -----------------------------------------------------------------------------------------
def spd_uc_required(network: str, uo: float) -> float:
    """Nejmenší Uc svodiče AC: TN a TT 1,1·Uo, IT √3·Uo (ČSN 33 2000-5-534, zjednodušeně L–PE)."""
    return round(math.sqrt(3) * uo if network == "IT" else SPD_UC_FACTOR * uo, 1)


def spd_ucpv(e: Element, data: Data) -> float | None:
    """Ucpv DC svodiče: atribut `ucpv`, parametr artiklu `ucpv_v`, jinak „Ucpv 1100 V“ z poznámky artiklu."""
    v = data.num(e, "ucpv", "ucpv_v")
    if v:
        return v
    m = _UCPV_NOTE.search(data.note(e))
    return float(m.group(1).replace(",", ".")) if m else None


def spd_findings(project: Project, data: Data, dcv: dict | None = None) -> list[Finding]:
    """AC svodič: Uc ≥ 1,1·Uo (TN/TT) / √3·Uo (IT) podle sítě listu (`spd_uc`, chyba). DC svodič: Ucpv ≥ Uoc
    stringu při t_min (`spd_ucpv`, varování – bez návrhové teploty v projektu informace; jen Uc známé a pod Uoc → informace „ověřte Ucpv“), Up ≤ Uw střídače
    (`uw` / artikl `uw_kv`, `spd_up`). Jímací soustava rozvaděče a svodič bez typu 1 → informace (`spd_lps`)."""
    dcv = calc.dc_voltages(project) if dcv is None else dcv
    given = design_t_min_given(project)
    out: list[Finding] = []
    infos = _Infos()
    for s in project.sheets:
        b = board_of(project, s)
        for e in s.elements:
            if e.symbol_id != "fve.spd":
                continue
            name = e.ref or "SPD"
            uc = data.num(e, "uc", "uc_v")
            if is_dc(s, e, data):
                v = dcv.get(e.id)
                if v is None:
                    continue
                ucpv = spd_ucpv(e, data)
                if ucpv and ucpv < v.u - 1e-9 and not given:
                    infos.add(s, "spd_ucpv_t", e, f"{name} Ucpv {_g(ucpv)} V < Uoc {_g(v.u)} V ({v.string_ref})")
                elif ucpv and ucpv < v.u - 1e-9:
                    out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                       f"Svodič {name}: Ucpv {_g(ucpv)} V < Uoc stringu {v.string_ref} {_g(v.u)} V "
                                       "při nejnižší teplotě – zvolte svodič na vyšší napětí", "spd_ucpv"))
                elif not ucpv and uc and uc < v.u - 1e-9:
                    infos.add(s, "spd_ucpv", e, f"{name} Uc {_g(uc)} V < Uoc {_g(v.u)} V ({v.string_ref})")
                up, uw = data.num(e, "up", "up_kv"), (data.num(v.inverter, "uw", "uw_kv") if v.inverter else None)
                if up and uw and up > uw + 1e-9:
                    out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                       f"Svodič {name}: Up {_g(up)} kV > výdržné napětí Uw {_g(uw)} kV střídače "
                                       f"{v.inverter.ref} – zvolte svodič s nižší ochrannou úrovní", "spd_up"))
            elif uc:
                req = spd_uc_required(b.network, b.uo)
                if uc < req - 1e-9:
                    rule = "√3·Uo" if b.network == "IT" else "1,1·Uo"
                    out.append(Finding(ERROR, s.id, s.name, e.id, False, e.ref,
                                       f"Svodič {name}: Uc {_g(uc)} V < {rule} = {_g(req)} V (síť {b.network}, "
                                       f"Uo {_g(b.uo)} V) – zvolte svodič s vyšším Uc", "spd_uc"))
            kind = data.text(e, "spd_type", "spd_type")
            if b.lps and kind and not _T1.search(kind.replace("T1+", "T1 ")):
                infos.add(s, "spd_lps", e, f"{name} ({kind})")
    out += infos.findings({"spd_ucpv": "Svodič DC: Uc pod Uoc stringu, Ucpv neznámé – ověřte Ucpv v datasheetu "
                                       "(atribut ucpv)",
                           "spd_ucpv_t": _assumed_text("Svodič DC: Ucpv pod Uoc stringu"),
                           "spd_lps": "Objekt s jímací soustavou: svodič bez typu 1 – na vstupu vedení do objektu "
                                      "patří SPD typu 1 (ověřte umístění)"})
    return out


# ---- 4. svorky ----------------------------------------------------------------------------------------------------
def _is_terminal(e: Element, data: Data) -> bool:
    return e.symbol_id in TERMINAL_SYMBOLS or data.category(e) == "terminal"


def _adjacent_protection(s: Sheet, e: Element, depth: int = 4) -> list[Element]:
    """Jisticí přístroje s In vodivě nejblíž u svorky (přes vodiče a další svorky / uzly, bez PE vodičů)."""
    by_id = {x.id: x for x in s.elements}
    seen, frontier, found = {e.id}, [e], []
    for _ in range(depth):
        nxt = []
        for cur in frontier:
            for w in s.wires:
                if not w.touches(cur.id) or set(w.conductors) <= {"PE"}:
                    continue
                o = by_id.get(w.b.element_id if w.a.element_id == cur.id else w.a.element_id)
                if o is None or o.id in seen:
                    continue
                seen.add(o.id)
                if o.symbol_id in PROTECTION and calc._f(o.attrs.get("in_")):
                    found.append(o)
                elif o.symbol_id in calc._TERMINALS:
                    nxt.append(o)
        frontier = nxt
    return found


def terminal_findings(project: Project, data: Data) -> list[Finding]:
    """Průřez vodiče (atribut `cross`) nad max. průřezem svorky / přístroje (`cross_max`, artikl `cross_max_mm2`) –
    vodiče u prvku a u přívodu / vývodu listu rozvaděče i navázaný kabel JPS (`terminal_cross`, chyba). In svorky
    (atribut / artikl `in_`) pod In nejbližšího jištění (`terminal_in`, varování)."""
    out: list[Finding] = []
    for s in project.sheets:
        for e in s.elements:
            cmax = data.num(e, "cross_max", "cross_max_mm2")
            if cmax:
                wires = [(s, w) for w in _touching(s, e)]
                if is_feed(e) and s.is_switchboard:
                    hit = linked_wire(project, s, e)
                    if hit is not None:
                        wires.append(hit)
                for ws, w in wires:
                    cross = calc._f(w.attrs.get("cross"))
                    if cross and cross > cmax + 1e-9:
                        out.append(Finding(ERROR, s.id, s.name, e.id, False, e.ref,
                                           f"Vodič {w.attrs.get('ref') or ''} {_g(cross)} mm² ({ws.name}) > max. "
                                           f"průřez {e.ref or e.symbol_id} {_g(cmax)} mm² – zvolte větší svorku",
                                           "terminal_cross"))
            if not _is_terminal(e, data):
                continue
            in_t = data.num(e, "in_", "in_")
            if not in_t:
                continue
            prot = _adjacent_protection(s, e)
            if not prot:
                continue
            p = min(prot, key=lambda x: calc._f(x.attrs.get("in_")) or 0)
            in_p = calc._f(p.attrs.get("in_")) or 0
            if in_t < in_p - 1e-9:
                out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                   f"Svorka {e.ref or ''}: In {_g(in_t)} A < In jištění {p.ref} {_g(in_p)} A – "
                                   "zvolte svorku s vyšším In", "terminal_in"))
    return out


# ---- 5. jmenovité napětí -----------------------------------------------------------------------------------------
def un_findings(project: Project, data: Data, dcv: dict | None = None) -> list[Finding]:
    """Un přístroje (atribut `un`, artikl `un_v`) pod napětím obvodu: AC – 3f přístroj sdružené napětí, jinak Uo sítě
    listu (`un_ac`, chyba; artikl jen pro DC se v AC obvodu nehodnotí); DC – Uoc stringů při t_min, které prvkem
    vedou (`un_dc`, varování; bez návrhové teploty v projektu jedna informace na list)."""
    dcv = calc.dc_voltages(project) if dcv is None else dcv
    given = design_t_min_given(project)
    out: list[Finding] = []
    infos = _Infos()
    for s in project.sheets:
        b = None
        for e in s.elements:
            if e.symbol_id not in UN_SYMBOLS and data.category(e) not in UN_CATEGORIES:
                continue
            un = max_num(data.text(e, "un", "un_v"))
            if not un:
                continue
            name = e.ref or e.symbol_id
            if is_dc(s, e, data):
                v = dcv.get(e.id)
                if v is not None and un < v.u - 1e-9 and not given:
                    infos.add(s, "un_dc_t", e, f"{name} Un {_g(un)} V < Uoc {_g(v.u)} V ({v.string_ref})")
                elif v is not None and un < v.u - 1e-9:
                    out.append(Finding(WARNING, s.id, s.name, e.id, False, e.ref,
                                       f"Un {name} {_g(un)} V DC < Uoc stringu {v.string_ref} {_g(v.u)} V při "
                                       "nejnižší teplotě – přístroj na vyšší napětí, nebo kratší string", "un_dc"))
                continue
            if data.note(e).strip().upper().startswith("DC") or not _touching(s, e):
                continue           # artikl pro DC (AC údaj neznáme) / nezapojený prvek
            b = b or board_of(project, s)
            three = _three_phase(s, e, data)
            req = round(b.uo * math.sqrt(3) / 10) * 10 if three else b.uo
            if un < req - 1e-9:
                out.append(Finding(ERROR, s.id, s.name, e.id, False, e.ref,
                                   f"Un {name} {_g(un)} V < {'sdružené' if three else 'fázové'} napětí sítě "
                                   f"{_g(req)} V", "un_ac"))
    return out + infos.findings({"un_dc_t": _assumed_text("Un přístroje DC pod Uoc stringu")})


def rating_findings(project: Project, lib=None) -> list[Finding]:
    """Všechny kontroly z údajů artiklů (pro `checks.check_project`)."""
    data = Data(lib)
    dcv = calc.dc_voltages(project)
    return (short_circuit_findings(project, data) + spd_findings(project, data, dcv) + terminal_findings(project, data)
            + un_findings(project, data, dcv))
