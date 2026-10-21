"""Sestavení projektu FVE ze specifikace (bez Qt) – veřejné `build_project` (re-export v `envocad.generate`).

Postup (`docs/design/topologie_f1_f2.md`, kap. 1.3): specifikace doplněná z artiklů a sloučená s `DEFAULT_SPEC` →
`spec.select_topology` (preset řetězce, na nesloučené specifikaci) → `pv.plan` (pracovní souřadnice) →
`chain.create_main_block` (blok hlavního AC článku **před** stringy – pořadí prvků) → `pv.build` (střídače, stringy,
DC rozvaděče, baterie) → `chain.build` (průchod topologií: bloky a listy článků, rozmístění)."""
from __future__ import annotations

from envocad.generator import chain, context, pv
from envocad.generator.boards.base import ChainContext
from envocad.generator.context import AC_MAX_INVERTERS_BUS, _merge, _s
from envocad.generator.spec import (
    BUILDINGS,
    DEFAULT_SPEC,
    HOUSE_SWITCHBOARD,
    HOUSE_SWITCHBOARD_AC,
    _apply_module_component,
    _apply_optimizer_component,
    building_kind,
    chain_text,
    resolve_chain_refs,
    rfve_dc_per_inverter,
    select_topology,
)
from envocad.model.project import Project


def build_project(spec: dict) -> Project:
    """Sestaví projekt: JPS (stringy → DC rozvaděče → střídač, každý string na vlastní DC vstup → AC rozvaděč → síť) + listy rozvaděčů."""
    if context._BUILD_LIB is not None:          # vnořené volání – knihovna už je otevřená
        return _build_project(spec)
    from envocad.library.store import LibraryStore
    context._BUILD_LIB = LibraryStore()
    try:
        return _build_project(spec)
    finally:
        context._BUILD_LIB = None


def _build_project(spec: dict) -> Project:
    spec = dict(spec or {})
    if isinstance(spec.get("module"), dict) and spec["module"].get("component_id"):
        # artikl modulu doplní jen to, co specifikace nezadala – proto před doplněním výchozích hodnot
        spec["module"] = _apply_module_component(spec["module"])
    opt_comp = None
    if isinstance(spec.get("optimizer"), dict) and spec["optimizer"].get("component_id"):
        spec["optimizer"], opt_comp = _apply_optimizer_component(spec["optimizer"])
    building = building_kind(spec.get("building"))
    raw = dict(spec)                   # nesloučená: `DEFAULT_SPEC` má connection.level "nn" (výběr topologie) a
    #                                    výchozí označení – přepisem jsou jen klíče zadané uživatelem
    if building == "house" and not spec.get("switchboard"):
        tech = _merge(DEFAULT_SPEC["dc"], spec.get("dc") or {}).get("tech_box")
        spec["switchboard"] = dict(HOUSE_SWITCHBOARD if tech else HOUSE_SWITCHBOARD_AC)
    spec = _merge(DEFAULT_SPEC, spec)
    invs = spec.get("inverters") or []
    if not invs:
        raise ValueError("Specifikace musí obsahovat alespoň jeden střídač (`inverters`).")
    if not _s((raw.get("ac") or {}).get("breaker_in")).strip():
        # jistič přívodu střídače nezadaný: podle proudu střídače (`rfve_ac.size_inverter_breakers`)
        spec["ac"] = {**spec["ac"], "breaker_in_auto": "1"}
    if not _s((raw.get("ac") or {}).get("main_in")).strip():
        # hlavní vypínač RFVE.AC / RFVE nezadaný: nejméně výchozí 125 A a nejméně vývod FVE v RD / HR (nejbližší
        # velikost ≥ Σ In střídačů) – jinak by odpínač ležel pod In jištění, které ho chrání (F7 `chain_selectivity`)
        from envocad.generator.boards.mv import LV_FEEDER_SIZES, _next_size, inverters_ac_current
        i_fve = inverters_ac_current(invs)
        if i_fve:
            main = max(float(DEFAULT_SPEC["ac"]["main_in"]), _next_size(i_fve, LV_FEEDER_SIZES))
            spec["ac"] = {**spec["ac"], "main_in": f"{main:g}"}
    if (spec["ac"].get("distribution") or "bus") == "bus" and len(invs) > AC_MAX_INVERTERS_BUS:
        raise ValueError(f"AC rozvaděč: sběrnice má {AC_MAX_INVERTERS_BUS} přívodů – nejvýš {AC_MAX_INVERTERS_BUS} "
                         f"střídačů (zadáno {len(invs)}). Zvolte rozvod svorkami nebo rozdělte FVE na více rozvaděčů.")
    # rodinný dům: DC část (pojistkové odpínače + SPD, místo rozvaděče u technologie) je v rozvaděči FVE s AC částí
    combined = building == "house" and bool(spec["dc"].get("tech_box"))
    if building == "house" and _s((spec.get("connection") or {}).get("level")).strip().lower() == "vn":
        raise ValueError("Rodinný dům: rozvaděč FVE se připojuje do HDS (připojení na nn) – přípojka VN se "
                         "negeneruje. Zvolte druh objektu firma, nebo připojení nn.")
    # topologie před vznikem prvního prvku (pořadí = id, `next_ref`); neplatná volba → ValueError
    topology = select_topology(raw)
    # označení článků z presetu (`node.ref`); `chain.<role>.ref` a dřívější `switchboard` / `connection.*_board`
    # zadané uživatelem jsou přepis
    resolve_chain_refs(spec, raw, topology)
    p = Project(name=spec["name"], meta={k: _s(v) for k, v in spec["meta"].items()})
    p.meta.setdefault("building", BUILDINGS[building])
    # topologie řetězce (meta jsou řetězce – formát projektu beze změny): id presetu a náhled řetězce
    p.meta["topology"] = topology.id
    p.meta["topology_chain"] = chain_text(topology)
    site = spec.get("site") or {}
    for key, meta_key in (("t_min", "pv_t_min"), ("t_max", "pv_t_max")):
        if site.get(key) not in (None, ""):
            p.meta[meta_key] = _s(site[key])
    s = p.sheets[0]
    s.name = "Blokové schéma"
    ctx = ChainContext(spec=spec, project=p, sheet=s, building=building, combined=combined,
                       geo=pv.plan(spec, combined, rfve_dc_per_inverter(raw, topology)), topology=topology, opt_comp=opt_comp)
    chain.create_main_block(ctx)
    pv.build(ctx)
    chain.build(ctx)
    return p
