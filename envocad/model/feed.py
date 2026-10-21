"""Přívod / vývod rozvaděče – jediné místo pravdy o značce `sb.feed` (bez Qt).

Jedna značka `sb.feed` se směrem v atributu `dir` (`in` = přívod, `out` = vývod; prázdné nebo neznámé = přívod).
Při `rot=0` je port `1` nahoře (`(0, 5)`, směr N) a kabelový výběžek dole; směr toku ukazuje jen šipka na výběžku.
Starší projekty, makra a schránka mají dvě značky `sb.feed_in` / `sb.feed_out` – převádí je
`normalize_legacy_element` (migrace formátu v13, `macros.parse_macro`, `paste_fragment`) tak, že port zůstane na
stejném místě se stejným směrem (vodiče se nerozpojí). Návrh `docs/design/znacka_privod_vyvod.md`.
"""
from __future__ import annotations

from typing import Any

FEED_SYMBOL = "sb.feed"
FEED_SYMBOLS = frozenset({FEED_SYMBOL})
FEED_IN, FEED_OUT = "in", "out"
FEED_DIRS = (FEED_IN, FEED_OUT)
DIR_CHOICES = [[FEED_IN, "přívod"], [FEED_OUT, "vývod"]]
# staré id → (směr, o kolik stupňů pootočit, aby port zůstal na místě): `sb.feed_in` měl port dole (S)
LEGACY_FEEDS = {"sb.feed_in": (FEED_IN, 180), "sb.feed_out": (FEED_OUT, 0)}
LINK_KEYS = {FEED_IN: "from", FEED_OUT: "to"}
LEGACY_FEED_IDS = {FEED_IN: "sb.feed_in", FEED_OUT: "sb.feed_out"}   # kanonická podoba v otisku listu (`diff`)
# technická značka prvku převedeného migrací projektu v12 → v13: vícepól ho kreslí přesně jako dřív (neotáčí přívodní
# větev – `multipole.flow_flipped`); do otisku listu ani do porovnání revizí nepatří
MP_LEGACY_ATTR = "mp_legacy"


def _sid(e: Any) -> str:
    return e.get("symbol_id", "") if isinstance(e, dict) else getattr(e, "symbol_id", "")


def _attrs(e: Any) -> dict:
    a = e.get("attrs") if isinstance(e, dict) else getattr(e, "attrs", None)
    return a if isinstance(a, dict) else {}


def raw_dir(e: Any) -> str:
    """Zapsaný směr (ořezaný, malými písmeny) – i neplatný; pro kontrolu `feed_dir`."""
    return str(_attrs(e).get("dir") or "").strip().lower()


def is_feed(e: Any) -> bool:
    """Prvek (nebo slovník prvku) je přívod/vývod rozvaděče."""
    return _sid(e) == FEED_SYMBOL


def feed_dir(e: Any) -> str:
    """Směr přívodu/vývodu: "out" jen pro `dir=out`, jinak (prázdné, neznámé) "in"."""
    return FEED_OUT if raw_dir(e) == FEED_OUT else FEED_IN


def feed_dir_valid(e: Any) -> bool:
    """Směr je prázdný (= přívod) nebo platný."""
    return raw_dir(e) in ("", *FEED_DIRS)


def is_mp_legacy(e: Any) -> bool:
    """Přívod/vývod převedený migrací ze starého projektu (vícepól jako dřív, bez otočení větve)."""
    return str(_attrs(e).get(MP_LEGACY_ATTR) or "") == "1"


def is_feed_in(e: Any) -> bool:
    return is_feed(e) and feed_dir(e) == FEED_IN


def is_feed_out(e: Any) -> bool:
    return is_feed(e) and feed_dir(e) == FEED_OUT


ANCHOR_ATTR = "anchor"   # kotva přívodu/vývodu bez zapojení v listu (AC část doplní mustr / projektant) – „1“


def is_anchor_feed(e: Any) -> bool:
    """Přívod/vývod označený jako kotva (`anchor="1"`): nezapojený v listu není chyba, jen informace (F7 `feed_anchor`)."""
    return is_feed(e) and str((getattr(e, "attrs", None) or {}).get(ANCHOR_ATTR) or "").strip() == "1"


def feed_link_key(e: Any) -> str:
    """Atribut s protějškem vazby: přívod „from“ (odkud), vývod „to“ (kam)."""
    return LINK_KEYS[feed_dir(e)]


def other_link_key(e: Any) -> str:
    return LINK_KEYS[FEED_OUT if feed_dir(e) == FEED_IN else FEED_IN]


def feed_name(e: Any) -> str:
    """Zkratka druhu do textů (odkud/kam, výkazy): „přívod“ / „vývod“."""
    return "vývod" if feed_dir(e) == FEED_OUT else "přívod"


def normalize_legacy_element(d: dict, mark: bool = False) -> bool:
    """Slovník prvku se starou značkou `sb.feed_in` / `sb.feed_out` převede na `sb.feed` + `attrs.dir` (na místě).
    `sb.feed_in` se pootočí o 180°, aby port `1` zůstal na stejném místě se stejným směrem. `mark` (migrace projektu)
    zapíše `attrs.mp_legacy = "1"` – vícepól starého listu se pak nemění. Vrací True při změně."""
    if not isinstance(d, dict):
        return False
    legacy = LEGACY_FEEDS.get(str(d.get("symbol_id", "")))
    if legacy is None:
        return False
    direction, turn = legacy
    d["symbol_id"] = FEED_SYMBOL
    attrs = d.get("attrs")
    if not isinstance(attrs, dict):
        attrs = d["attrs"] = {}
    attrs["dir"] = direction
    if mark:
        attrs[MP_LEGACY_ATTR] = "1"
    try:
        rot = int(d.get("rotation") or 0)
    except (TypeError, ValueError):
        rot = 0
    d["rotation"] = (rot + turn) % 360
    return True


def normalize_legacy_objects(elements: Any) -> int:
    """Prvky (objekty `Element`) se starou značkou `sb.feed_in` / `sb.feed_out` převede na místě jako
    `normalize_legacy_element` – pro šablony pluginů psané pro starší verzi (`templates.apply_template`). Vrací počet."""
    n = 0
    for e in elements or ():
        legacy = LEGACY_FEEDS.get(str(getattr(e, "symbol_id", "")))
        if legacy is None:
            continue
        direction, turn = legacy
        e.symbol_id = FEED_SYMBOL
        e.attrs["dir"] = direction
        e.rotation = (int(e.rotation or 0) + turn) % 360
        n += 1
    return n


def normalize_legacy_fragment(fragment: Any) -> int:
    """Všechny prvky výřezu (schránka, makro: {"elements": [...]}) se starou značkou převede; vrací počet."""
    if not isinstance(fragment, dict):
        return 0
    els = fragment.get("elements")
    return sum(normalize_legacy_element(d) for d in els) if isinstance(els, list) else 0


# šipka směru toku na kabelovém výběžku (otevřená, šířka 2 mm): přívod = hrot (0, −3,5) k portu, vývod = hrot
# (0, −6,5) od portu. Základní JSON značky (`builtin/switchboard/sb.feed.json`) má šipku přívodu.
FEED_ARROW_IN = {"type": "polyline", "points": [[-1, -5.5], [0, -3.5], [1, -5.5]], "closed": False}
FEED_ARROW_OUT = {"type": "polyline", "points": [[-1, -4.5], [0, -6.5], [1, -4.5]], "closed": False}
LABEL_X = 7.0


def _is_arrow(pr: dict) -> bool:
    return pr.get("type") == "polyline" and pr.get("points") in (FEED_ARROW_IN["points"], FEED_ARROW_OUT["points"])


def feed_label_pos(e: Any) -> tuple[float, float]:
    """Poloha popisku v souřadnicích značky (otáčí se s prvkem). Popisek je ve výkresu vpravo od svorky jak u přívodu
    s portem nahoře (rot 0), tak u převedeného přívodu s portem dole (rot 180) – starý `sb.feed_in` ho měl tam.
    Přívod otočený o 90/270° má popisek tam, kde ho měl starý `sb.feed_in` se stejnou polohou portu."""
    rot = int(getattr(e, "rotation", 0) or 0) % 360
    if feed_dir(e) == FEED_IN and rot != 0:
        return (-LABEL_X, 0.0)
    return (LABEL_X, 0.0)


def feed_symbol(e: Any, base):
    """Značka přívodu/vývodu podle směru (`dir`): vývod má obrácenou šipku a ve výkresu „Kam“ místo „Odkud“.
    Základní značka z knihovny (přívod) zůstává beze změny (náhled při vkládání)."""
    import dataclasses
    out = feed_dir(e) == FEED_OUT
    prims = []
    for pr in base.primitives:
        if _is_arrow(pr):
            prims.append(dict(FEED_ARROW_OUT if out else FEED_ARROW_IN))
        else:
            prims.append(pr)
    shown = LINK_KEYS[FEED_OUT if out else FEED_IN]
    attributes = [dataclasses.replace(a, show=(a.key == shown)) if a.key in LINK_KEYS.values() else a
                  for a in base.attributes]
    return dataclasses.replace(base, primitives=prims, attributes=attributes, label_pos=feed_label_pos(e))


# ---- vícepól: beze změny proti značkám sb.feed_in / sb.feed_out --------------------------------------------------
# Vícepól (rozhodnutí 4 v návrhu) kreslí přívody a vývody přesně jako dřív: přívod v souřadnicích starého
# `sb.feed_in` (port dole, kroužek pólu v (0, −2,5)) s rotací o 180° menší, vývod jako `sb.feed_out`. Obálka značky
# (rozměry ve vícepólu: `flow_extent`, `perp_extent`) je obálka starých značek včetně nápisu PŘÍVOD / VÝVOD.
_MP_LEGACY = {
    FEED_IN: {"prims": [{"type": "circle", "cx": 0, "cy": 0, "r": 1.5},
                        {"type": "line", "x1": 0, "y1": -1.5, "x2": 0, "y2": -5},
                        {"type": "line", "x1": 0, "y1": 1.5, "x2": 0, "y2": 5}],
              "pole": [{"type": "circle", "cx": 0, "cy": -2.5, "r": 1.5},
                       {"type": "line", "x1": 0, "y1": -4, "x2": 0, "y2": -5},
                       {"type": "line", "x1": 0, "y1": -1, "x2": 0, "y2": 3}],
              "port": (0.0, -5.0, "S"), "bounds": (-1.5, -5.0, 1.5, 7.0)},
    FEED_OUT: {"prims": [{"type": "circle", "cx": 0, "cy": 0, "r": 1.5},
                         {"type": "line", "x1": 0, "y1": 1.5, "x2": 0, "y2": 5},
                         {"type": "line", "x1": 0, "y1": -1.5, "x2": 0, "y2": -5}],
               "pole": [{"type": "circle", "cx": 0, "cy": 2.5, "r": 1.5},
                        {"type": "line", "x1": 0, "y1": 4, "x2": 0, "y2": 5},
                        {"type": "line", "x1": 0, "y1": 1, "x2": 0, "y2": -3}],
               "port": (0.0, 5.0, "N"), "bounds": (-1.5, -9.0, 1.5, 5.0)},
}


def multipole_feed_view(e: Any, sym):
    """(prvek, značka) přívodu/vývodu pro vícepól: kopie prvku (stejné id, atributy, `mp_pos`) s rotací starého
    `sb.feed_in` (o 180° méně) a značka s geometrií starých značek. Prvek, který není přívod/vývod, beze změny."""
    import dataclasses

    from envocad.model.symbol import Port, Symbol
    if not is_feed(e):
        return e, sym
    d = feed_dir(e)
    leg = _MP_LEGACY[d]
    port = sym.ports[0].name if sym.ports else "1"
    px, py, pd = leg["port"]
    bounds = leg["bounds"]

    class _FeedMpSymbol(Symbol):
        def bounds(self):   # obálka staré značky (s nápisem), aby se rozmístění vícepólu nezměnilo
            return bounds

    mp_sym = _FeedMpSymbol(id=sym.id, name=sym.name, category=sym.category, description=sym.description,
                           iec_ref=sym.iec_ref, primitives=[dict(p) for p in leg["prims"]],
                           ports=[Port(port, px, py, pd)] + [p for p in sym.ports[1:]],
                           attributes=sym.attributes, label_pos=(LABEL_X, 0.0),
                           multipole={**sym.multipole, "pole": [dict(p) for p in leg["pole"]]},
                           function_class=sym.function_class, orphan_ports=sym.orphan_ports)
    if d == FEED_IN:
        e = dataclasses.replace(e, rotation=(int(e.rotation or 0) + 180) % 360)
    return e, mp_sym
