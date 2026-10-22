"""Soustava DC (1000 / 1500 V) pro generátor: volba artiklů DC přístrojů podle napětí stringů (bez Qt).

Po `pv.build` (stringy a střídače jsou v projektu) a před listy DC rozvaděčů: Uoc stringů při t_min
(`calc.string_paths`) → `model.dc_system.choose` (spec `dc.system_v` > standard `dc_system_v` > 1000; automatika
na 1500 V, když string přesáhne Un DC přístrojů a katalog má artikly 1500 V) → přepis `dc.fuse_component`,
`dc.spd_component`, popis rozvaděče `dc.un_label` („max. 1500 V DC“). Bez artiklů 1500 V zůstane 1000 V,
string ze specifikace se nemění (zadání projektanta) – generátor zaloguje varování a kontrola F7 hlásí `un_dc`
a `dc_1500_missing`. Návrh: docs/design/kontroly_artiklu.md.
"""
from __future__ import annotations

from envocad.generator import context
from envocad.generator.context import _s, log
from envocad.model import calc, dc_system

DC_LABEL_DEFAULT = "max. 1000 V DC"


def standard_system_v() -> float | None:
    """Soustava DC z firemního standardu (`standard.dc_system_v`, 1000 / 1500), jinak None."""
    from envocad.settings import load_settings
    try:
        return dc_system.parse_system(load_settings()["standard"].get("dc_system_v"))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _cz(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def inverters_allow_auto(u_dc_max_values) -> bool:
    """Automatika 1500 V jen u střídače, který připouští víc než 1000 V DC (známé Umax > 1000 V); jinak by string nad
    1000 V byl chybou střídače a 1500 V přístroje by ho jen zakryly."""
    vals = [v for v in u_dc_max_values if v]
    return bool(vals) and max(vals) > dc_system.DEFAULT_SYSTEM + 1e-9


def resolve(spec: dict, project) -> dc_system.DcChoice:
    """Zvolí soustavu DC a přepíše `spec["dc"]` (artikly, `system_v`, `un_label`); zadaná 1500 V, kterou katalog
    nepokryje, se zapíše do `project.meta["dc_system_missing"]` (F7 informace `dc_1500_missing`). Vrací volbu."""
    dc = spec["dc"]
    if not has_dc_boxes(dc):      # bez DC rozvaděčů nejsou v cestě stringu přístroje z artiklů `dc`
        spec["dc"] = {**dc, "system_v": f"{dc_system.DEFAULT_SYSTEM:g}", "un_label": DC_LABEL_DEFAULT}
        return dc_system.DcChoice()
    paths = calc.string_paths(project)
    worst = max((sp.voltage for sp in paths if sp.voltage is not None), key=lambda v: v.u, default=None)
    want = dc_system.parse_system(dc.get("system_v")) or standard_system_v()
    auto = inverters_allow_auto(calc._f(sp.inverter.attrs.get("u_dc_max")) for sp in paths if sp.inverter is not None)
    ch = dc_system.choose(context._lib(), dc, worst.u if worst else 0.0, want, allow_auto=auto)
    spec["dc"] = {**dc, **ch.overrides, "system_v": f"{ch.system_v:g}", "un_label": ch.label}
    if want and want >= 1500 and ch.system_v < 1500:
        project.meta["dc_system_missing"] = ", ".join(ch.missing) or "artikly 1500 V"
        log.warning("Zadaná soustava DC 1500 V nepoužita – v katalogu chybí %s", project.meta["dc_system_missing"])
    if ch.auto and worst is not None:
        log.info("Soustava DC 1500 V: string %s Uoc %s V > Un DC přístrojů 1000 V – artikly %s", worst.string_ref,
                 _cz(worst.u), ", ".join(ch.overrides.values()))
    if worst is not None and ch.limit and worst.u > ch.limit + 1e-9:
        log.warning("String %s: Uoc %s V při t_min > Un DC přístrojů %s%s", worst.string_ref, _cz(worst.u),
                    ch.limit_label or f"{_cz(ch.limit)} V",
                    f" – pro 1500 V chybí v katalogu {', '.join(ch.missing)}" if ch.missing else "")
    return ch


def has_dc_boxes(dc: dict) -> bool:
    """Generátor kreslí DC rozvaděče (u technologie nebo po trase) – jen do nich dává artikly `dc.*_component`."""
    try:
        boxes = int(float(_s(dc.get("route_boxes") or 0).replace(",", ".")))
    except ValueError:
        boxes = 0
    tech = dc.get("tech_box")
    tech = tech if isinstance(tech, bool) else _s(tech).strip().lower() not in ("", "0", "false", "ne", "no")
    return bool(tech) or boxes > 0


def assistant_devices(dc: dict, lib=None, u_dc_max: float | None = None) -> list[tuple[float, str]]:
    """Přístroje stringové cesty [(Un DC, popis)] pro asistent stringů v průvodci: artikly, které generátor použije
    (`dc` sloučené s `DEFAULT_SPEC["dc"]`), se soustavou jako generátor (zadaná 1500 V; automatika 1500 V, je-li sada
    v katalogu a Umax střídače `u_dc_max` > 1000 V); bez DC rozvaděčů []."""
    from envocad.generator.spec import DEFAULT_SPEC
    full = {**DEFAULT_SPEC["dc"], **{k: v for k, v in dc.items() if v not in (None, "")}}
    if not has_dc_boxes(full):
        return []
    lib = lib if lib is not None else context._lib()
    want = dc_system.parse_system(full.get("system_v")) or standard_system_v()
    ch = dc_system.choose(lib, full, None, want, allow_auto=inverters_allow_auto([u_dc_max]))
    return dc_system.path_devices(lib, {**full, **ch.overrides})


def assistant_limit(dc: dict, lib=None, u_dc_max: float | None = None) -> tuple[float | None, str]:
    """(nejnižší Un DC přístrojů, popis) z `assistant_devices`; bez přístrojů (None, "")."""
    devs = assistant_devices(dc, lib, u_dc_max)
    return min(devs, key=lambda d: d[0]) if devs else (None, "")


def un_label(dc: dict) -> str:
    """Popis napětí DC rozvaděče („max. 1000 V DC“ / „max. 1500 V DC“) ze sloučené specifikace."""
    return _s(dc.get("un_label")).strip() or DC_LABEL_DEFAULT
