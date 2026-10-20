"""Vestavěná makra (sestavy) → envocad/library/builtin/macros/*.json. Spustit po změně šablon."""
from __future__ import annotations

import json
import re
from pathlib import Path

from envocad.library.macros import MACRO_VERSION, validate_macro
from envocad.library.templates import (
    AC_CONDUCTORS,
    DC_CONDUCTORS,
    GROUP_PITCH,
    _el,
    _feed,
    _terminal_group,
    _wire,
)
from envocad.model.project import Project, Sheet, copy_fragment

OUT = Path(__file__).resolve().parent.parent / "envocad" / "library" / "builtin" / "macros"


def ac_outlet() -> dict:
    """AC vývod: skupina rozvodných svorek → jistič → vývod."""
    p, s = Project(), Sheet(kind="switchboard")
    grp = _terminal_group(p, s, 60, 200, "X2", 1, len(AC_CONDUCTORS), "vývod")
    f = _el(p, s, "fve.breaker_mcb", 60, 170, "F", rot=270, in_="16", char="B", poles="3", modules="3")
    out = _feed(p, s, "out", 60, 140, "", desc="vývod")
    out.attrs["ref"] = "X3"
    _wire(p, s, grp, "2", f, "1", AC_CONDUCTORS)
    _wire(p, s, f, "2", out, "1", AC_CONDUCTORS)
    return copy_fragment(s, [e.id for e in s.elements])


def _frag(s: Sheet, pitch: float | None = None) -> dict:
    f = copy_fragment(s, [e.id for e in s.elements])
    if pitch:
        f["pitch"] = pitch
    return f


def dc_string_in() -> dict:
    """DC string v rozvaděči u technologie (parametrické: {k} číslo stringu, {nk} = n + k, {string} označení stringu,
    {fuse_in}, {spd}): přívod X{k} → pojistkový odpínač → vývod X{nk}; SPD na string, PE svodiče → XPE (sdílený vývod k HOP)."""
    p, s = Project(), Sheet(kind="switchboard")
    feed = _feed(p, s, "in", 60, 240, "", rot=180, desc="od {string}")
    feed.attrs["ref"] = "X{k}"
    d = _el(p, s, "fve.fuse_disconnect", 60, 210, "F", rot=270, in_="{fuse_in}", char="gPV", un="1000", poles="2", modules="2")
    d.attrs["ref"] = "FU{i}.{j}"   # číslování ENVO: střídač.string
    out = _feed(p, s, "out", 60, 170, "", desc="{string} dál")
    out.attrs["ref"] = "X{nk}"
    spd = _el(p, s, "fve.spd", 72.5, 180, "F", spd_type="{spd} DC", uc="1000 V DC", poles="3", modules="3", desc="string {string}",
              when="spd")   # prázdný typ svodiče = bez SPD
    spd.attrs["ref"] = "SPD-DC{i}.{j}"
    xpe = _feed(p, s, "out", 40, 130, "", desc="k HOP", shared="1", when="spd")   # vývod jen pro PE svodiče
    xpe.attrs["ref"] = "XPE"
    _wire(p, s, feed, "1", d, "1", DC_CONDUCTORS)
    _wire(p, s, d, "2", out, "1", DC_CONDUCTORS)
    _wire(p, s, d, "2", spd, "L", DC_CONDUCTORS)
    pe = _wire(p, s, spd, "PE", xpe, "1", ["PE"])
    pe.points = [(95.0, 170.0), (95.0, 147.5), (40.0, 147.5)]   # PE vpravo kolem popisků vývodu, ne přes ně
    return _frag(s, 50)   # rozteč 50 mm: popisky přívodu/SPD (typ, Uc, Up, ISCPV) se nepřekrývají se sousedním stringem


def dc_string_route() -> dict:
    """DC string v rozvaděči po trase: průchozí svorky přívod X{k} → vývod X{nk} (bez odpínače – pojistkové odpínače
    jen v rozvaděči u střídače); SPD na string z přívodní svorky → XPE (sdílený vývod k HOP)."""
    p, s = Project(), Sheet(kind="switchboard")
    feed = _feed(p, s, "in", 60, 240, "", rot=180, desc="od {string}")
    feed.attrs["ref"] = "X{k}"
    out = _feed(p, s, "out", 60, 170, "", desc="{string} dál")
    out.attrs["ref"] = "X{nk}"
    spd = _el(p, s, "fve.spd", 72.5, 180, "F", spd_type="{spd} DC", uc="1000 V DC", poles="3", modules="3", desc="string {string}",
              when="spd")   # prázdný typ svodiče = bez SPD
    spd.attrs["ref"] = "SPD-DC{i}.{j}"
    xpe = _feed(p, s, "out", 40, 130, "", desc="k HOP", shared="1", when="spd")   # vývod jen pro PE svodiče
    xpe.attrs["ref"] = "XPE"
    _wire(p, s, feed, "1", out, "1", DC_CONDUCTORS)
    _wire(p, s, feed, "1", spd, "L", DC_CONDUCTORS)
    pe = _wire(p, s, spd, "PE", xpe, "1", ["PE"])
    pe.points = [(95.0, 170.0), (95.0, 147.5), (40.0, 147.5)]   # PE vpravo kolem popisků vývodu, ne přes ně
    return _frag(s, 50)


# AC rozvaděč FVE (RFVE.AC, AC část RFVE rodinného domu): sběrnice nahoře, vše přichází zespodu – přívody i vývody
# jsou ve spodní řadě (y 105, port nahoře), přívodní větev teče nahoru do sběrnice (svorka X → jistič otočený tokem
# nahoru → přívod zdola B{k}), jádro visí ze sběrnice dolů. Zleva: XPE, SPD, přívody po 30 mm, hlavní vypínač + XOUT.
# Generátor (`generate._ac_core_after_feeds`) posune hlavní vypínač a XOUT za poslední přívod. docs/design/
# znacka_privod_vyvod.md
AC_BUS = (165, 175)          # sběrnice: čára x 90…270, vývody 1…12 x 97,5 + 15·(i−1), přívody zdola B1…B6 x 105 + 30·(k−1)


def ac_feed() -> dict:
    """AC přívod od střídače ({k}, {inverter}, {breaker_in}): X{k} dole → jistič nahoru → sběrnice 1 (sdílená) port B{k}."""
    p, s = Project(), Sheet(kind="switchboard")
    feed = _feed(p, s, "in", 105, 105, "", desc="od {inverter}")
    feed.attrs["ref"] = "X{k}"
    f = _el(p, s, "fve.breaker_mcb", 105, 140, "F", rot=90, in_="{breaker_in}", char="B", poles="3", modules="3")
    bus = _el(p, s, "sb.busbar", *AC_BUS, "", desc="rozvod AC", in_="{main_in}", conductors=" ".join(AC_CONDUCTORS), shared="1")
    bus.attrs["ref"] = "1"
    _wire(p, s, feed, "1", f, "1", AC_CONDUCTORS)
    _wire(p, s, f, "2", bus, "B{k}", AC_CONDUCTORS)   # zdola
    return _frag(s, 30)


def ac_core() -> dict:
    """AC jádro rozvaděče ({spd}, {main_in}): sběrnice 1 (sdílená) → SPD a PE → XPE (k HOP, sdílený) vlevo, sběrnice →
    hlavní vypínač → XOUT vpravo za přívody (jeden přívod; generátor posune za poslední)."""
    p, s = Project(), Sheet(kind="switchboard")
    bus = _el(p, s, "sb.busbar", *AC_BUS, "", desc="rozvod AC", in_="{main_in}", conductors=" ".join(AC_CONDUCTORS), shared="1")
    bus.attrs["ref"] = "1"
    spd = _el(p, s, "fve.spd", 82.5, 140, "F", spd_type="{spd}", poles="4", modules="4", when="spd")
    xpe = _feed(p, s, "out", 60, 105, "", desc="k HOP", shared="1")
    xpe.attrs["ref"] = "XPE"
    q = _el(p, s, "sb.main_switch", 142.5, 140, "Q", rot=270, in_="{main_in}", poles="4", modules="4")
    out = _feed(p, s, "out", 142.5, 105, "", desc="do HDS / DS")
    out.attrs["ref"] = "XOUT"
    _wire(p, s, bus, "1", spd, "L", AC_CONDUCTORS[:4]).points = [(97.5, 160.0), (82.5, 160.0)]
    pe = _wire(p, s, spd, "PE", xpe, "1", ["PE"])
    pe.points = [(82.5, 120.0), (60.0, 120.0)]
    pe = _wire(p, s, bus, "1", xpe, "1", ["PE"])        # PE sběrnice odbočuje z téhož vývodu jako SPD, nad ním
    pe.points = [(97.5, 165.0), (60.0, 165.0)]
    _wire(p, s, bus, "4", q, "1", AC_CONDUCTORS)
    _wire(p, s, q, "2", out, "1", AC_CONDUCTORS)
    return _frag(s)


def jps_string_chain() -> dict:
    """JPS: FV string → DC rozvaděč (blok) → střídač, s kabely."""
    p, s = Project(), Sheet()
    g = _el(p, s, "fve.pv_string", 40, 200, "G", n_modules="20", p_module="450", p_string="9 kWp")
    t = _el(p, s, "fve.inverter", 40 + 2 * GROUP_PITCH + 60, 200, "T", p_ac="25", phases="3", mppt="2", strings_per_mppt="2")
    _wire(p, s, g, "DC", t, "DC1", DC_CONDUCTORS, ref="W1", cable="H1Z2Z2-K 1x6", cross="6", length="30", method="E")
    return copy_fragment(s, [e.id for e in s.elements])


# ---- proměnné a sady hodnot (formát makra v2, docs/LIBRARY_FORMAT.md „Formát makra“) ----------------------------
def _num(name: str, label: str, default: str, unit: str = "", **kw) -> dict:
    d = {"name": name, "label": label, "type": "number", "default": default}
    if unit:
        d["unit"] = unit
    d.update(kw)
    return d


def _auto(name: str, label: str, default: str = "", typ: str = "number") -> dict:
    d = {"name": name, "label": label}
    if typ != "text":
        d["type"] = typ
    if default:
        d["default"] = default
    d["auto"] = True
    return d


# číslování stringů – dodává generátor nebo opakování makra
_DC_AUTO = [
    _num("n", "Počet stringů", "1", min=1, max=50, auto=True),
    _auto("k", "Pořadí stringu v rozvaděči", "1"),
    _auto("nk", "Číslo vývodu (n + k)"),
    _auto("i", "Číslo střídače", "1"),
    _auto("j", "Číslo stringu u střídače", "{k}"),
    _auto("string", "Označení stringu", "G{k}", typ="text"),
    _auto("inverter", "Střídač", "T{i}", typ="text"),
]
# typ svodiče je volný text (specifikace a starší projekty mají i „T1+T2+T3“, „Typ 2“); doporučené hodnoty v nápovědě
_SPD_HELP = "Doporučené hodnoty: T1, T2, T1+T2 (smí být i jiný text, např. T1+T2+T3). Prázdné = bez svodiče."
_DC_SPD = {"name": "spd", "label": "Svodič přepětí DC (typ)", "default": "T2", "help": _SPD_HELP}

META = {
    "DC string v rozvaděči": {
        "role": "dc_tech",
        "variables": [*_DC_AUTO, _num("fuse_in", "In pojistky", "15", "A", required=True, min=1), _DC_SPD],
        "value_sets": [
            {"name": "Pojistka 10 A gPV, SPD T2", "values": {"fuse_in": "10", "spd": "T2"}},
            {"name": "Pojistka 15 A gPV, SPD T2", "values": {"fuse_in": "15", "spd": "T2"}},
            {"name": "Pojistka 20 A gPV, SPD T1+T2", "values": {"fuse_in": "20", "spd": "T1+T2"}},
            {"name": "Pojistka 15 A gPV bez SPD", "values": {"fuse_in": "15", "spd": ""}},
        ],
        "repeat": {"count": "n", "pitch": 50},
    },
    "DC string po trase": {
        "role": "dc_route",
        "variables": [*_DC_AUTO, _DC_SPD],
        "value_sets": [
            {"name": "SPD T2", "values": {"spd": "T2"}},
            {"name": "SPD T1+T2", "values": {"spd": "T1+T2"}},
        ],
        "repeat": {"count": "n", "pitch": 50},
    },
    "AC přívod střídače": {
        "role": "ac_feed",
        "variables": [
            _auto("k", "Číslo přívodu", "1"),
            _auto("inverter", "Střídač", "T{k}", typ="text"),
            _num("breaker_in", "In jističe", "40", "A", required=True, min=1),
            _num("main_in", "In sběrnice / hlavního vypínače", "125", "A", required=True, min=1),
        ],
        "value_sets": [
            {"name": "Jistič B25", "values": {"breaker_in": "25"}},
            {"name": "Jistič B32", "values": {"breaker_in": "32"}},
            {"name": "Jistič B40", "values": {"breaker_in": "40"}},
            {"name": "Jistič B63", "values": {"breaker_in": "63"}},
        ],
    },
    "AC jádro rozvaděče": {
        "role": "ac_core",
        "variables": [
            {"name": "spd", "label": "Svodič přepětí AC (typ)", "default": "T1+T2", "help": _SPD_HELP},
            _num("main_in", "In hlavního vypínače", "125", "A", required=True, min=1),
        ],
        "value_sets": [
            {"name": "SPD T1+T2, hlavní vypínač 125 A", "values": {"spd": "T1+T2", "main_in": "125"}},
            {"name": "SPD T2, hlavní vypínač 63 A", "values": {"spd": "T2", "main_in": "63"}},
        ],
    },
}

MACROS = [
    ("AC vývod s jističem", "Skupina rozvodných svorek X2 → jistič 3p → vývod X3 (rozvaděč)", ac_outlet),
    ("DC string v rozvaděči", "Generátor (u technologie): X{k} → pojistkový odpínač FU{i}.{j} {fuse_in} → X{nk}, SPD-DC{i}.{j} {spd} DC, PE → XPE; proměnné k, nk, i, j, string, inverter, fuse_in, spd", dc_string_in),
    ("DC string po trase", "Generátor (po trase): X{k} → X{nk} (průchozí svorky, bez odpínače), SPD-DC{i}.{j} {spd} DC z přívodní svorky, PE → XPE; pojistkové odpínače jen v rozvaděči u střídače; proměnné k, nk, i, j, string, inverter, spd", dc_string_route),
    ("AC přívod střídače", "Generátor: X{k} od {inverter} (zespodu) → jistič {breaker_in} → sběrnice 1 port B{k}; proměnné k, inverter, breaker_in, main_in", ac_feed),
    ("AC jádro rozvaděče", "Generátor: sběrnice 1 → SPD {spd} → XPE (k HOP), sběrnice → hlavní vypínač {main_in} → XOUT", ac_core),
    ("String → střídač", "FV string s kabelem H1Z2Z2-K na DC vstup střídače (JPS)", jps_string_chain),
]


def macro_data(name: str, desc: str, fragment: dict) -> dict:
    meta = META.get(name, {})
    data = {"version": MACRO_VERSION, "name": name, "description": desc, "role": meta.get("role", ""),
            "variables": meta.get("variables", [])}
    if meta.get("value_sets"):
        data["value_sets"] = meta["value_sets"]
    if meta.get("repeat"):
        data["repeat"] = meta["repeat"]
    data["fragment"] = fragment
    return data


_ID = re.compile(r"\b[0-9a-f]{12}\b")


def _canon_ids(fragment: dict) -> str:
    """Fragment jako text s náhodnými id nahrazenými pořadovými značkami (porovnání bez ohledu na id)."""
    ids: dict[str, str] = {}
    return _ID.sub(lambda m: ids.setdefault(m.group(0), f"#{len(ids) + 1}"), json.dumps(fragment, sort_keys=False))


def _keep_ids(path: Path, fragment: dict) -> dict:
    """Beze změny obsahu ponechá fragment s id z existujícího souboru – přegenerování nemění diff kvůli náhodným id."""
    try:
        old = json.loads(path.read_text(encoding="utf-8")).get("fragment")
    except (OSError, ValueError, AttributeError):
        return fragment
    if not isinstance(old, dict):
        return fragment
    if _canon_ids(old) == _canon_ids(fragment):
        return old
    # změněný obsah se stejnými prvky a vodiči (pořadí): id převzít podle pořadí, ať diff ukazuje jen změnu obsahu
    def ids(f: dict) -> list[str]:
        return [str(x.get("id")) for key in ("elements", "wires") for x in f.get(key) or []]
    a, b = ids(fragment), ids(old)
    if len(a) != len(b):
        return fragment
    m = dict(zip(a, b, strict=True))
    return json.loads(_ID.sub(lambda g: m.get(g.group(0), g.group(0)), json.dumps(fragment)))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, desc, fn in MACROS:
        slug = name.lower().replace(" → ", "_").replace(" ", "_").replace("í", "i").replace("č", "c").replace("ř", "r").replace("ě", "e").replace("ý", "y").replace("á", "a")
        data = macro_data(name, desc, _keep_ids(OUT / f"{slug}.json", fn()))
        errs = validate_macro(data)
        if errs:
            raise SystemExit(f"{name}: " + "; ".join(errs))
        (OUT / f"{slug}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(MACROS)} maker → {OUT}")


if __name__ == "__main__":
    main()
