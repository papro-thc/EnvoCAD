"""Sestavení projektu FVE ze specifikace (bez Qt) – veřejné `build_project` (re-export v `envocad.generate`).

Postup (`docs/design/topologie_f1_f2.md`, kap. 1.3): specifikace doplněná z artiklů a sloučená s `DEFAULT_SPEC` →
`spec.select_topology` (preset řetězce, na nesloučené specifikaci) → `pv.plan` (pracovní souřadnice) →
`chain.create_main_block` (blok hlavního AC článku **před** stringy – pořadí prvků) → `pv.build` (střídače, stringy,
DC rozvaděče, baterie) → `chain.build` (průchod topologií: bloky a listy článků, rozmístění)."""
from __future__ import annotations

from envocad.generator import chain, context, pv
from envocad.generator.boards.base import ChainContext
from envocad.generator.context import AC_MAX_INVERTERS_BUS, _merge, _s
from envocad.generator.currents import main_switch_in
from envocad.generator.spec import (
    BUILDINGS,
    DEFAULT_SPEC,
    HOUSE_SWITCHBOARD,
    HOUSE_SWITCHBOARD_AC,
    _apply_module_component,
    _apply_optimizer_component,
    ac_groups,
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
    """Sestavení; společný RFVE.DC (výchozí pro 2+ střídače), se kterým by list blokového schématu přerostl
    `jps_max_paper` (list „AC a připojení“ s RFVE.DC pro desítky stringů), se nahradí RFVE.DC na střídač – jen když
    projektant `chain.rfve_dc.per_inverter` nezadal (review F2, B1)."""
    p, common = _build_once(spec)
    if common is not None and _jps_over_limit(p, spec, common) and not _per_inverter_given(spec):
        from envocad.generator.context import log
        log.info("Společný RFVE.DC by blokové schéma zvětšil nad limit listu – RFVE.DC na střídač")
        chain_spec = dict((spec or {}).get("chain") or {})
        chain_spec["rfve_dc"] = {**(chain_spec.get("rfve_dc") or {}), "per_inverter": True}
        p, _common = _build_once({**spec, "chain": chain_spec})
    return p


def _per_inverter_given(spec: dict) -> bool:
    given = ((spec or {}).get("chain") or {}).get("rfve_dc") if isinstance((spec or {}).get("chain"), dict) else None
    return isinstance(given, dict) and _s(given.get("per_inverter")).strip() != ""


def _jps_over_limit(p: Project, spec: dict, block_id: str) -> bool:
    """List blokového schématu se společným RFVE.DC (`block_id`) je větší než limit (`jps.max_paper`, jinak standard
    `jps_max_paper`); přerostlý list řady jednoho střídače se nepočítá (DC řetězec se nedělí – jako dřív), při
    `jps.split` „none“ se nehodnotí (jeden list záměrně)."""
    from envocad.generator.jps import jps_max_paper
    from envocad.model.frame import paper_exceeds
    opts = (spec or {}).get("jps") or {}
    if (_s(opts.get("split")) or "auto") == "none":
        return False
    limit = _s(opts.get("max_paper")) or jps_max_paper()
    return any(paper_exceeds(s.paper, limit) for s in p.sheets
               if not s.is_switchboard and any(e.id == block_id for e in s.elements))


def _build_once(spec: dict) -> tuple[Project, str | None]:
    """Jedno sestavení: (projekt, id bloku společného RFVE.DC nebo None)."""
    spec = dict(spec or {})
    if isinstance(spec.get("module"), dict) and spec["module"].get("component_id"):
        # artikl modulu doplní jen to, co specifikace nezadala – proto před doplněním výchozích hodnot
        spec["module"] = _apply_module_component(spec["module"])
    if isinstance(spec.get("battery"), dict) and spec["battery"].get("component_id"):
        # artikl baterie (batteries.csv) + počet modulů → typ, kapacita a výkon věže, BMS (`library/batteries.py`)
        from envocad.library.batteries import apply_battery_component
        spec["battery"] = apply_battery_component(context._lib(), spec["battery"])
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
        # jistič přívodu střídače nezadaný: podle proudu střídače (`currents.inverter_breaker`, dosadí
        # `rfve_ac.mark_chain_devices` / blok bez listu `rfve_ac.block_attrs`)
        spec["ac"] = {**spec["ac"], "breaker_in_auto": "1"}
    if not _s((raw.get("ac") or {}).get("main_in")).strip():
        # hlavní vypínač RFVE.AC / RFVE nezadaný: nejméně výchozí 125 A a nejméně vývod FVE v RD / HR
        # (`currents.main_switch_in`) – jinak by odpínač ležel pod In jištění, které ho chrání (F7 `chain_selectivity`).
        # Tady odhad ze specifikace; po `pv.build` znovu z prvků střídačů (proud i z artiklu bez `p_ac`), u skupin
        # střídačů (`ac_group`) podle střídačů skupiny (`rfve_ac._build_main`)
        spec["ac"] = {**spec["ac"], "main_in": main_switch_in(spec, invs), "main_in_auto": "1"}
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
    groups = ac_groups(spec)
    if len(groups) > 1:
        # řady střídačů po skupinách (hlavní první): AC vodiče skupin k RFVE.AC{n} se nekříží; označení beze změny
        order = {k: n for n, k in enumerate(groups)}
        invs = spec["inverters"] = [
            {**inv, "ref": _s(inv.get("ref")) or f"T{i + 1}"} for i, inv in sorted(
                enumerate(invs), key=lambda t: (order[_s(t[1].get("ac_group")).strip()], t[0]))]
    if len(groups) > 1 and (topology.node("rfve_ac") is None or topology.level != "nn"
                            or not any(topology.node(r) is not None for r in ("hr", "rd"))):
        raise ValueError("Skupiny střídačů na jiném místě (`inverters[].ac_group`) zatím jen pro připojení na nn "
                         "s AC rozvaděčem RFVE.AC a stávajícím HR / RD (firma, bytový dům) – zadejte jednu skupinu.")
    p = Project(name=spec["name"], meta={k: _s(v) for k, v in spec["meta"].items()})
    p.meta.setdefault("building", BUILDINGS[building])
    # topologie řetězce (meta jsou řetězce – formát projektu beze změny): id presetu a náhled řetězce
    p.meta["topology"] = topology.id
    p.meta["topology_chain"] = chain_text(topology)
    site = spec.get("site") or {}
    for key, meta_key in (("t_min", "pv_t_min"), ("t_max", "pv_t_max")):
        if site.get(key) not in (None, ""):
            p.meta[meta_key] = _s(site[key])
    ik = _s(site.get("ik_ka")).strip()
    if ik:   # Ik v místě připojení [kA] (vyjádření DS / výpočet) – kontroly Icu / Icw (`ratings`)
        from envocad.model.project import ik_ka_error
        if (msg := ik_ka_error(ik, "site.ik_ka")):
            raise ValueError(msg + ".")
        p.meta["ik_ka"] = ik
    s = p.sheets[0]
    s.name = "Blokové schéma"
    ctx = ChainContext(spec=spec, raw=raw, project=p, sheet=s, building=building, combined=combined,
                       geo=pv.plan(spec, combined, rfve_dc_per_inverter(raw, topology)), topology=topology, opt_comp=opt_comp)
    from envocad.generator.boards.groups import feeds
    ctx.groups = [{"key": k, "feed": f, "idx": [i for i, inv in enumerate(invs) if _s(inv.get("ac_group")).strip() == k]}
                  for k, f in zip(groups, feeds(len(groups)), strict=True)] if len(groups) > 1 else []
    chain.create_main_block(ctx)
    pv.build(ctx)
    from envocad.generator.dc_voltage import resolve as resolve_dc_system
    resolve_dc_system(spec, p)      # soustava DC 1000 / 1500 V podle Uoc stringů – před listy DC rozvaděčů
    if _s(spec["ac"].get("main_in_auto")):     # z prvků střídačů (artikl bez `p_ac` ve specifikaci)
        spec["ac"]["main_in"] = main_switch_in(spec, ctx.inverters)
    chain.build(ctx)
    if ik:   # jen zadané: bloky přípojných rozvaděčů dostanou Ik (blok má přednost před odhadem z trafa)
        for blk in (*(g.get("block") for g in ctx.groups), *(ctx.blocks.get(r) for r in ("main", "hr", "re", "rd"))):
            if blk is not None:
                blk.attrs["ik_ka"] = ik
    return p, (ctx.dc_common.id if ctx.dc_common is not None else None)
