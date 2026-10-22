"""Napěťová soustava DC strany FVE (1000 / 1500 V) a Un DC přístrojů ve stringové cestě – bez Qt.

Návrh: docs/design/kontroly_artiklu.md (kap. „Soustava DC 1000 / 1500 V“). Knihovna (`lib`) se předává zvenku
(`LibraryStore` nebo cokoli s `component(id)` a `components(category=…)`); artikl je `library.components.Component`.

- `spd_ucpv` / `component_un`: Un DC přístroje – svodič Ucpv (atribut `ucpv` > artikl `ucpv_v` > „Ucpv …“ v poznámce;
  Uc jen pro výběr artiklu soustavy), ostatní `un_v` (`un_value`, největší číslo).
- `path_devices` / `device_limit`: přístroje, které generátor dá do stringové cesty (`dc.fuse_component` jen s RFVE.DC,
  `dc.spd_component`, je-li typ SPD shodný se `dc.spd`).
- `find_set`: artikly pro soustavu `system_v` (2pólový držák se stejnou značkou – jen s RFVE.DC – a svodič DC daného
  typu s Un ≥ soustava).
- `choose`: volba soustavy pro generátor a asistent stringů (zadaná 1500, jinak 1000 s automatikou na 1500, když
  string přesáhne Un DC přístrojů, střídač připouští víc než 1000 V a katalog sadu 1500 V má).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SYSTEMS = (1000.0, 1500.0)
DEFAULT_SYSTEM = 1000.0
GENERATOR_HOLDER_POLES = "2"   # generátor kreslí jeden 2pólový pojistkový odpojovač na string (L+ i L−)
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
# „Ucpv 1100 V“, „UCPV = 1170 V DC“, „Ucpv: 1 100 V“, „Ucpv 1,1 kV“
_UCPV_NOTE = re.compile(r"U\s*C\s*PV\s*(?:[=:≤]\s*)?(\d{1,3}(?:[ \u00a0]\d{3})+|\d+(?:[.,]\d+)?)\s*(kV|V)\b",
                        re.IGNORECASE)


def _num(v) -> float | None:
    """První číslo v textu („1000 V DC“ → 1000, „3,8“ → 3,8), jinak None."""
    m = _NUM.search(str(v or ""))
    return float(m.group(0).replace(",", ".")) if m else None


def un_value(v) -> float | None:
    """Jmenovité napětí z textu – největší číslo („230/400 V“ → 400, „1000 V DC“ → 1000); jediné čtení Un pro
    kontroly F7 (`ratings`), mez stringu (`calc.device_dc_un`) i volbu artiklů."""
    n = [float(x.replace(",", ".")) for x in _NUM.findall(str(v or ""))]
    return max(n) if n else None


def note_ucpv(note: str) -> float | None:
    """Ucpv svodiče z poznámky artiklu (záloha, když chybí sloupec `ucpv_v`): „Ucpv 1100 V“, „UCPV = 1170 V DC“,
    „Ucpv 1 100 V“, „Ucpv 1,1 kV“; jinak None."""
    m = _UCPV_NOTE.search(note or "")
    if not m:
        return None
    x = float(re.sub(r"[ \u00a0]", "", m.group(1)).replace(",", "."))
    return round(x * 1000, 1) if m.group(2).lower() == "kv" else x


def spd_ucpv(attrs: dict | None, comp=None) -> float | None:
    """Ucpv DC svodiče – jedno pořadí pro F7 i mez stringu: atribut prvku `ucpv` > artikl `ucpv_v` > „Ucpv …“
    z poznámky artiklu. Uc se za Ucpv nebere."""
    v = _num((attrs or {}).get("ucpv"))
    if v:
        return v
    if comp is None:
        return None
    return _num(comp.params.get("ucpv_v")) or note_ucpv(comp.params.get("note", ""))


def _spd_kind(t: str) -> str:
    return "".join(str(t or "").upper().replace("DC", "").split())


def is_dc_spd(comp) -> bool:
    return getattr(comp, "category", "") == "spd" and "DC" in str(comp.params.get("spd_type") or "").upper()


def component_un(comp, uc_fallback: bool = False) -> float | None:
    """Un DC přístroje z artiklu: svodič Ucpv (`spd_ucpv`; s `uc_fallback` jinak Uc `uc_v` – jen pro výběr artiklu
    soustavy), jiné `un_v` (`un_value`)."""
    if comp is None:
        return None
    if getattr(comp, "category", "") == "spd":
        return spd_ucpv(None, comp) or (un_value(comp.params.get("uc_v")) if uc_fallback else None)
    return un_value(comp.params.get("un_v"))


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


def path_devices(lib, dc: dict) -> list[tuple[float, str]]:
    """(Un DC [V], popis „EFH 10 DC 2p 1000 V“) artiklů ve stringové cestě (`path_components`) se známým Un."""
    out = []
    for c in path_components(lib, dc):
        u = component_un(c)
        if u:
            out.append((u, f"{c.part_number} {u:g} V"))
    return out


def device_limit(lib, dc: dict) -> tuple[float | None, str]:
    """(nejnižší Un DC přístrojů ve stringové cestě [V], popis), bez údaje (None, ""); při shodě první (držák)."""
    devs = path_devices(lib, dc)
    return min(devs, key=lambda d: d[0]) if devs else (None, "")


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
    if dc.get("fuse_component") and _flag(dc.get("tech_box", True)):   # držák jen v RFVE.DC (cesta stringu)
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
              and (component_un(c, uc_fallback=True) or 0) >= system_v - 1e-9]
        cur_spd = _comp(lib, dc.get("spd_component"))
        if cur_spd is not None and cur_spd in ss:
            ss = [cur_spd]
        if ss:
            maker = cur_spd.manufacturer if cur_spd is not None else ""
            out["spd_component"] = min(ss, key=lambda c: (c.manufacturer != maker, component_un(c, True) or 0,
                                                           c.id)).id
        else:
            missing.append(f"svodič DC {dc.get('spd') or 'T2'} {system_v:g} V")
    return out, missing


def catalog_missing(lib, system_v: float = 1500.0, need_holder: bool = True) -> list[str]:
    """Chybějící druhy DC přístrojů soustavy v katalogu: 2pólový pojistkový odpojovač `fve.fuse_disconnect` (jen
    `need_holder` – cesta stringu vede přes RFVE.DC s pojistkami) a svodič DC (typ SPD se nehodnotí); knihovna bez
    seznamu artiklů → [] (nehodnotí se)."""
    if lib is None or not hasattr(lib, "components"):
        return []
    out = []
    if need_holder and not any((component_un(c) or 0) >= system_v - 1e-9 and _holder_fits(c, None)
                               for c in _candidates(lib, "fuse_holder")):
        out.append(f"pojistkový odpojovač {system_v:g} V DC {GENERATOR_HOLDER_POLES}p")
    if not any(is_dc_spd(c) and (component_un(c, uc_fallback=True) or 0) >= system_v - 1e-9
               for c in _candidates(lib, "spd")):
        out.append(f"svodič DC {system_v:g} V")
    return out


def _holder_fits(c, cur) -> bool:
    """Držák nahradí dosavadní: stejná značka (bez dosavadního `fve.fuse_disconnect`) a známý počet pólů rovný
    pólům dosavadního držáku (bez údaje 2 – generátor kreslí 2pólový odpojovač); prázdné / 1 póly jako 2p ne."""
    sym = cur.symbol_id if cur is not None else "fve.fuse_disconnect"
    poles = str((cur.params.get("poles") if cur is not None else "") or GENERATOR_HOLDER_POLES)
    return c.symbol_id == sym and str(c.params.get("poles") or "").strip() == poles


def _poles_text(cur) -> str:
    return f" {(cur.params.get('poles') if cur is not None else '') or GENERATOR_HOLDER_POLES}p"


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


def choose(lib, dc: dict, u_string_max: float | None = None, system_v=None, allow_auto: bool = True) -> DcChoice:
    """Soustava DC pro generátor / asistent. `system_v` = zadání (spec `dc.system_v`, standard `dc_system_v`):
    1500 → artikly 1500 V (chybí-li, zůstane 1000 V a `missing`); 1000 (výchozí) → artikly z `dc`, a když Uoc
    stringu `u_string_max` přesáhne jejich Un, katalog má sadu 1500 V a `allow_auto` (střídač připouští víc než
    1000 V), automaticky 1500 V. Bez `u_string_max` (asistent) se automatika uplatní, kdykoli je sada k dispozici."""
    want = parse_system(system_v) or DEFAULT_SYSTEM
    base_u, base_label = device_limit(lib, dc)
    base = DcChoice(DEFAULT_SYSTEM, {}, base_u, base_label)
    need = allow_auto and (u_string_max is None or (base_u is not None and u_string_max > base_u + 1e-9))
    if want < 1500 and not need:
        return base
    over, missing = find_set(lib, dc, 1500.0)
    if missing:
        base.missing = missing if (want >= 1500 or (u_string_max is not None and need)) else []
        return base
    u, label = device_limit(lib, {**dc, **over})
    return DcChoice(1500.0, over, u, label, [], auto=want < 1500)
