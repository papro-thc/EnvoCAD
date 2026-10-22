"""Napěťová soustava DC strany FVE (1000 / 1500 V) a Un DC přístrojů ve stringové cestě – bez Qt.

Návrh: docs/design/kontroly_artiklu.md (kap. „Soustava DC 1000 / 1500 V“). Knihovna (`lib`) se předává zvenku
(`LibraryStore` nebo cokoli s `component(id)` a `components(category=…)`); artikl je `library.components.Component`.

- `component_un`: Un DC přístroje z artiklu – svodič Ucpv (`ucpv_v`, „Ucpv NNN V“ v poznámce), jinak Uc; ostatní `un_v`.
- `device_limit`: nejnižší Un DC přístrojů, které generátor do stringové cesty dá (`dc.fuse_component`,
  `dc.spd_component`, je-li typ SPD shodný se `dc.spd`).
- `find_set`: artikly pro soustavu `system_v` (držák pojistky a svodič DC daného typu s Un ≥ soustava).
- `choose`: volba soustavy pro generátor a asistent stringů (zadaná 1500, jinak 1000 s automatikou na 1500, když
  string přesáhne Un DC přístrojů a katalog artikly 1500 V má).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SYSTEMS = (1000.0, 1500.0)
DEFAULT_SYSTEM = 1000.0
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_UCPV_NOTE = re.compile(r"U\s*C\s*PV\s*(\d+(?:[.,]\d+)?)\s*V", re.IGNORECASE)


def _num(v) -> float | None:
    m = _NUM.search(str(v or ""))
    return float(m.group(0).replace(",", ".")) if m else None


def note_ucpv(note: str) -> float | None:
    """Ucpv svodiče z poznámky artiklu („Ucpv 1100 V“, „UCPV 1170 V DC“), jinak None."""
    m = _UCPV_NOTE.search(note or "")
    return float(m.group(1).replace(",", ".")) if m else None


def _spd_kind(t: str) -> str:
    return "".join(str(t or "").upper().replace("DC", "").split())


def is_dc_spd(comp) -> bool:
    return getattr(comp, "category", "") == "spd" and "DC" in str(comp.params.get("spd_type") or "").upper()


def component_un(comp) -> float | None:
    """Un DC přístroje z artiklu: svodič Ucpv (parametr `ucpv_v`, poznámka), jinak Uc (`uc_v`); jiné `un_v`."""
    if comp is None:
        return None
    if getattr(comp, "category", "") == "spd":
        return _num(comp.params.get("ucpv_v")) or note_ucpv(comp.params.get("note", "")) or _num(comp.params.get("uc_v"))
    return _num(comp.params.get("un_v"))


def _comp(lib, cid):
    if not cid or lib is None:
        return None
    try:
        return lib.component(cid)
    except Exception:  # noqa: BLE001 – knihovna nedostupná
        return None


def _flag(v) -> bool:
    return v if isinstance(v, bool) else str(v or "").strip().lower() not in ("", "0", "false", "ne", "no")


def path_components(lib, dc: dict) -> list:
    """Artikly, které generátor dá do stringové cesty: držák pojistky (`dc.fuse_component`, jen s DC rozvaděčem
    u technologie `dc.tech_box`) a svodič DC
    (`dc.spd_component`, jen když jeho typ odpovídá `dc.spd` – jako `rfve_dc._apply_spd_component`)."""
    out = []
    fuse = _comp(lib, dc.get("fuse_component")) if _flag(dc.get("tech_box", True)) else None
    if fuse is not None:      # pojistkové odpojovače jen v DC rozvaděči u technologie (po trase jen SPD)
        out.append(fuse)
    spd = _comp(lib, dc.get("spd_component"))
    if spd is not None and _spd_kind(dc.get("spd") or "T2") == _spd_kind(spd.params.get("spd_type", "")):
        out.append(spd)
    return out


def device_limit(lib, dc: dict) -> tuple[float | None, str]:
    """(nejnižší Un DC přístrojů ve stringové cestě [V], popis „EFH 10 DC 2p 1000 V“), bez údaje (None, "")."""
    best: tuple[float | None, str] = (None, "")
    for c in path_components(lib, dc):
        u = component_un(c)
        if u and (best[0] is None or u < best[0]):
            best = (u, f"{c.part_number} {u:g} V")
    return best


def _candidates(lib, category: str) -> list:
    if lib is None or not hasattr(lib, "components"):
        return []
    try:
        return list(lib.components(category=category))
    except Exception:  # noqa: BLE001
        return []


def find_set(lib, dc: dict, system_v: float) -> tuple[dict[str, str], list[str]]:
    """Artikly pro soustavu `system_v`: ({"fuse_component": id, "spd_component": id}, chybějící role česky). Role se
    hledá jen tehdy, když ji `dc` používá. Držák: kategorie fuse_holder, Un ≥ soustava, stejná značka a stejný
    (známý) počet pólů jako dosavadní držák (generátor kreslí jeden 2pólový odpojovač na string – 1pólový artikl by
    ve výkazu chyběl), přednost výrobce, pak větší `in_max_a`; svodič: DC, stejný typ jako `dc.spd`, Ucpv/Uc ≥
    soustava, přednost výrobce dosavadního svodiče."""
    out: dict[str, str] = {}
    missing: list[str] = []
    cur = _comp(lib, dc.get("fuse_component"))
    if dc.get("fuse_component"):
        hs = [c for c in _candidates(lib, "fuse_holder") if (component_un(c) or 0) >= system_v - 1e-9
              and _holder_fits(c, cur)]
        if cur is not None and (component_un(cur) or 0) >= system_v - 1e-9:
            hs = [cur]
        if hs:
            maker = cur.manufacturer if cur is not None else ""
            out["fuse_component"] = min(hs, key=lambda c: (c.manufacturer != maker, -(c.num("in_max_a") or 0),
                                                           c.id)).id
        else:
            missing.append(f"držák pojistky {system_v:g} V DC{_poles_text(cur)}")
    if dc.get("spd_component"):
        kind = _spd_kind(dc.get("spd") or "T2")
        ss = [c for c in _candidates(lib, "spd") if is_dc_spd(c) and _spd_kind(c.params.get("spd_type", "")) == kind
              and (component_un(c) or 0) >= system_v - 1e-9]
        cur_spd = _comp(lib, dc.get("spd_component"))
        if cur_spd is not None and cur_spd in ss:
            ss = [cur_spd]
        if ss:
            maker = cur_spd.manufacturer if cur_spd is not None else ""
            out["spd_component"] = min(ss, key=lambda c: (c.manufacturer != maker, component_un(c) or 0, c.id)).id
        else:
            missing.append(f"svodič DC {dc.get('spd') or 'T2'} {system_v:g} V")
    return out, missing


def catalog_missing(lib, system_v: float = 1500.0, poles: str = "2") -> list[str]:
    """Chybějící druhy DC přístrojů soustavy v katalogu (pojistkový odpojovač `fve.fuse_disconnect` s `poles` póly
    jako u generátoru, svodič DC) – bez ohledu na typ SPD; knihovna bez seznamu artiklů → [] (nehodnotí se)."""
    if lib is None or not hasattr(lib, "components"):
        return []
    out = []
    if not any((component_un(c) or 0) >= system_v - 1e-9 and c.symbol_id == "fve.fuse_disconnect"
               and str(c.params.get("poles") or "") == poles for c in _candidates(lib, "fuse_holder")):
        out.append(f"pojistkový odpojovač {system_v:g} V DC {poles}p")
    if not any(is_dc_spd(c) and (component_un(c) or 0) >= system_v - 1e-9 for c in _candidates(lib, "spd")):
        out.append(f"svodič DC {system_v:g} V")
    return out


def _holder_fits(c, cur) -> bool:
    """Držák nahradí dosavadní: stejná značka a stejný počet pólů (neznámé póly kandidáta → ne)."""
    if cur is None:
        return True
    return c.symbol_id == cur.symbol_id and (not cur.params.get("poles")
                                             or str(c.params.get("poles") or "") == str(cur.params["poles"]))


def _poles_text(cur) -> str:
    return f" {cur.params['poles']}p" if cur is not None and cur.params.get("poles") else ""


def parse_system(v) -> float | None:
    """1000 / 1500 z textu („1500“, „1500 V“); jiné / prázdné → None."""
    x = _num(v)
    return x if x in SYSTEMS else None


@dataclass
class DcChoice:
    """Volba soustavy DC: napětí soustavy, přepis artiklů v `dc`, mez Un DC přístrojů pro stringy a důvod."""
    system_v: float = DEFAULT_SYSTEM
    overrides: dict[str, str] = field(default_factory=dict)
    limit: float | None = None          # nejnižší Un DC přístrojů zvolené sady [V]
    limit_label: str = ""               # „EFH 10 DC 2p 1000 V“
    missing: list[str] = field(default_factory=list)   # chybějící artikly 1500 V (když je string potřebuje)
    auto: bool = False                  # 1500 V zvoleno automaticky podle stringu

    @property
    def label(self) -> str:
        return f"max. {self.system_v:g} V DC"


def choose(lib, dc: dict, u_string_max: float | None = None, system_v=None) -> DcChoice:
    """Soustava DC pro generátor / asistent. `system_v` = zadání (spec `dc.system_v`, standard `dc_system_v`):
    1500 → artikly 1500 V (chybí-li, zůstane 1000 V a `missing`); 1000 (výchozí) → artikly z `dc`, a když Uoc
    stringu `u_string_max` přesáhne jejich Un a katalog má sadu 1500 V, automaticky 1500 V. Bez `u_string_max`
    (asistent před zadáním stringů) se automatika uplatní, kdykoli je sada 1500 V k dispozici – mez pro stringy je
    pak Un sady 1500 V."""
    want = parse_system(system_v) or DEFAULT_SYSTEM
    base_u, base_label = device_limit(lib, dc)
    base = DcChoice(DEFAULT_SYSTEM, {}, base_u, base_label)
    need = u_string_max is None or (base_u is not None and u_string_max > base_u + 1e-9)
    if want < 1500 and not need:
        return base
    over, missing = find_set(lib, dc, 1500.0)
    if missing:
        base.missing = missing if (want >= 1500 or (u_string_max is not None and need)) else []
        return base
    u, label = device_limit(lib, {**dc, **over})
    return DcChoice(1500.0, over, u, label, [], auto=want < 1500)
