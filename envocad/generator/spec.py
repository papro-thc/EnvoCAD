"""Specifikace generátoru FVE (bez Qt): výchozí hodnoty, vstupy průvodce, artikly a výběr topologie připojení.
Návrh `docs/design/topologie_f1_f2.md`, kap. 1.1 a 1.3 (krok 2).

Pravidla (`docs/NAVRH_TOPOLOGIE.md`, kap. 8 – rozhodnutí):
- `spec["topology"]` zadané → ten preset (volba projektanta; jediná cesta k `nn_hr_meter` – měření v HR se
  automaticky nevolí, rozhodnutí 6);
- rodinný dům (`house`) → `rd` i nad 30 kWp (rozhodnutí 1); přípojka VN u RD → ValueError (jako `generate.py`);
- `connection.level == "vn"` → `vn` (firma volbou projektanta, rozhodnutí 1);
- jinak `nn` (firma – výchozí i pod 30 kWp; bytový dům, rozhodnutí 2).
Výkon (`installed_kwp`) výběr neovlivňuje – řídí jen síťovou ochranu nad 30 kWp (F2).

Dále výchozí specifikace (`DEFAULT_SPEC`), druh objektu (`BUILDINGS`, `building_kind`), vstupy průvodce (`parse_*`,
`load_spec`) a doplnění specifikace z artiklů (modul, střídač, optimizér, In pojistek stringů). Z `envocad.generate`
nic neimportuje (refaktoring F1, krok 2).
"""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from pathlib import Path

from envocad.generator import context
from envocad.generator.context import AC_SWITCHBOARD_REF, MAIN_LV_BOARD_REF, _num, _s, log
from envocad.model.project import Element
from envocad.model.topology import Topology

# role článků řetězce FVE (model je obor-nezávislý – role mu předává až generátor)
ROLES = ("rfve_dc", "inverter", "rfve_ac", "rfve", "rd", "hr", "re", "hds", "tr", "rvn", "grid")
# popisky článků bez vlastního označení v náhledu řetězce („stringy → RFVE.DC → T → … → DS“)
CHAIN_LABELS = {"inverter": "T", "grid": "DS"}
CHAIN_START = "stringy"
GRID_PROTECTION_KWP = 30.0   # nad tuto hranici instalovaného výkonu DC síťová ochrana (F2; `standard.grid_protection_kwp`)

# automatický výběr presetu
AUTO_TOPOLOGY = {"house": "rd", "vn": "vn", "nn": "nn"}


def connection_level(spec: Mapping) -> str:
    """Úroveň připojení ze specifikace: "vn" jen pro `connection.level` "vn", jinak "nn" (jako `generate.py`)."""
    conn = spec.get("connection") or {}
    return "vn" if _s(conn.get("level")).strip().lower() == "vn" else "nn"


def _num0(v) -> float:
    """Číslo ze specifikace, nečitelné nebo prázdné = 0 (`installed_kwp`)."""
    try:
        return float(_s(v).replace(",", ".").strip() or 0)
    except ValueError:
        return 0.0


def installed_kwp(spec: Mapping) -> float:
    """Instalovaný výkon DC [kWp] = Σ modulů ve stringech × `module.p_wp` / 1000 (rozhodnutí 1). Chybí-li `p_wp`
    nebo počty modulů, počítá se 0 (specifikaci před sloučením s `DEFAULT_SPEC` doplní volající)."""
    p_wp = _num0((spec.get("module") or {}).get("p_wp"))
    modules = sum(_num0(n) for inv in spec.get("inverters") or [] if isinstance(inv, Mapping)
                  for n in inv.get("strings") or [])
    return round(modules * p_wp / 1000, 3)


def chain_text(topology: Topology) -> str:
    """Náhled řetězce FVE („stringy → RFVE.DC → T → RFVE.AC → HR → RE → HDS → DS“) – průvodce, `meta["topology_chain"]`."""
    return topology.chain_text(CHAIN_START, CHAIN_LABELS)


def check_topology(topology: Topology, building: str | None = None) -> list[str]:
    """Chyby topologie z pohledu generátoru FVE (česky): neznámé role a druhy objektu, chybějící střídač, rozvaděč FVE
    rodinného domu, přípojka VN bez článku přípojky. `building` = druh objektu specifikace ("company" | "house" |
    "apartment"); None = podle `topology.buildings`.

    - Rodinný dům potřebuje článek `rfve` (rozvaděč FVE s DC i AC částí): builder `rfve_ac` DC část nestaví, DC
      vodiče do RFVE by vedly na neexistující přívody (`bad_port`). Chyba místo tichého mapování `rfve_ac` → `rfve`:
      projektant uvidí, že preset neodpovídá druhu objektu (označení a popis článku z presetu převezme F2).
    - `rfve` a `rfve_ac` zároveň ne – oba builderu staví list hlavního AC rozvaděče (vznikly by dva listy).
    - Úroveň vn potřebuje aspoň jeden článek přípojky VN (`boards.mv.MV_ROLES`), jinak by vznikla tichá přípojka nn.
    """
    from envocad.generator.boards.mv import MV_ROLES
    tid = topology.id
    errs = [f"Topologie „{tid}“: neznámá role „{n.role}“ – známé: {', '.join(ROLES)}."
            for n in topology.nodes if n.role not in ROLES]
    errs += [f"Topologie „{tid}“: neznámý druh objektu „{b}“ – známé: {', '.join(BUILDINGS)}."
             for b in topology.buildings if b not in BUILDINGS]
    if topology.node("inverter") is None:
        errs.append(f"Topologie „{tid}“ nemá článek „inverter“ (střídače).")
    house = building == "house" if building is not None else "house" in topology.buildings
    if house and topology.node("rfve") is None:
        errs.append(f"Topologie „{tid}“ pro rodinný dům nemá článek „rfve“ (rozvaděč FVE s DC i AC částí) – "
                    f"„rfve_ac“ je AC rozvaděč pro firmu a bytový dům.")
    if topology.node("rfve") is not None and topology.node("rfve_ac") is not None:
        errs.append(f"Topologie „{tid}“ má článek „rfve“ i „rfve_ac“ – hlavní AC rozvaděč smí být jen jeden "
                    f"(„rfve“ pro rodinný dům, „rfve_ac“ pro firmu a bytový dům).")
    if topology.level == "vn" and not any(topology.node(r) is not None for r in MV_ROLES):
        errs.append(f"Topologie „{tid}“ je pro připojení na vn, ale nemá žádný článek přípojky VN "
                    f"({', '.join(MV_ROLES)}).")
    return errs


def select_topology(spec: Mapping, topologies: Mapping[str, Topology] | None = None) -> Topology:
    """Topologie pro specifikaci (pravidla v docstringu modulu). `topologies` = výsledek
    `library.topologies.load_topologies(ROLES)` (None = načte se s rolemi generátoru – soubor s neznámou rolí se
    vynechá i s přepisem vestavěného presetu; knihovna drží cache podle změn souborů). Neplatná volba → ValueError (česky):
    neznámé `topology`, preset pro jiný druh objektu nebo jinou úroveň připojení než zadané `connection.level`,
    přípojka VN u rodinného domu, topologie s rolí, kterou generátor nezná."""
    if topologies is None:
        # s rolemi generátoru: neplatný vlastní / sdílený soubor (neznámá role) se vynechá a platí vestavěný preset
        from envocad.library.topologies import load_topologies
        topologies = load_topologies(known_roles=ROLES)
    building = building_kind(spec.get("building"))
    conn = spec.get("connection") or {}
    level_given = _s(conn.get("level")).strip().lower()
    level = connection_level(spec)
    wanted = _s(spec.get("topology")).strip()
    if wanted:
        topo = topologies.get(wanted)
        if topo is None:
            known = ", ".join(sorted(topologies)) or "žádná"
            raise ValueError(f"Neznámá topologie „{wanted}“ – k dispozici: {known}.")
        if not level_given:
            level = topo.level   # úroveň připojení nezadaná → podle zvoleného presetu
    else:
        key = "house" if building == "house" else level
        topo = topologies.get(AUTO_TOPOLOGY[key])
        if topo is None:
            raise ValueError(f"Chybí topologie „{AUTO_TOPOLOGY[key]}“ (knihovna topologií).")
    # neznámý druh objektu v presetu ohlásí `check_topology` (srozumitelněji než „je pro druh objektu …“)
    if topo.buildings and building not in topo.buildings and all(b in BUILDINGS for b in topo.buildings):
        allowed = ", ".join(BUILDINGS.get(b, b) for b in topo.buildings)
        raise ValueError(f"Topologie „{topo.name}“ je pro druh objektu {allowed}, ne pro {BUILDINGS[building]}.")
    if building == "house" and level == "vn":
        raise ValueError("Rodinný dům: rozvaděč FVE se připojuje do HDS (připojení na nn) – přípojka VN se "
                         "negeneruje. Zvolte druh objektu firma, nebo připojení nn.")
    if level != topo.level:
        raise ValueError(f"Topologie „{topo.name}“ je pro připojení na {topo.level}, ale specifikace má "
                         f"připojení na {level} (`connection.level`).")
    errs = check_topology(topo, building)
    if errs:
        raise ValueError(" ".join(errs))
    return topo


# ---- volby článků řetězce (`spec["chain"][role]`) -----------------------------------------------------------
def chain_options(spec: Mapping, topology: Topology | None, role: str) -> dict:
    """Volby článku `role`: `spec["chain"][role]` > `node.options` presetu (docs/design/topologie_f1_f2.md, kap. 2
    „chain.*“). Kopie – volající ji smí měnit."""
    node = topology.node(role) if topology is not None else None
    out: dict = dict(node.options) if node is not None else {}
    given = (spec.get("chain") or {}).get(role) if isinstance(spec.get("chain"), Mapping) else None
    if isinstance(given, Mapping):
        out.update(given)
    return out


def chain_flag(v, default: bool = False) -> bool:
    """Pravdivostní volba článku („1“, „true“, „ano“, True; prázdné = `default`)."""
    t = _s(v).strip().lower()
    if not t:
        return default
    return t in ("1", "true", "ano", "yes", "a", "y")


def node_ref(spec: Mapping, topology: Topology | None, role: str, legacy: str = "", default: str = "") -> str:
    """Označení článku: `chain.<role>.ref` > dřívější klíč specifikace (`legacy` – `switchboard.ref`,
    `connection.main_board.ref`…, jen zadaný uživatelem) > `ref` článku presetu > `default` (konstanta generátoru)."""
    given = (spec.get("chain") or {}).get(role) if isinstance(spec.get("chain"), Mapping) else None
    ref = _s((given or {}).get("ref") if isinstance(given, Mapping) else "").strip()
    node = topology.node(role) if topology is not None else None
    return ref or _s(legacy).strip() or (node.ref if node is not None else "") or default


def node_desc(spec: Mapping, topology: Topology | None, role: str, legacy: str = "", default: str = "") -> str:
    """Popis článku: `chain.<role>.desc` > zadaný dřívější klíč > `default` (popis generátoru) > `desc` presetu."""
    given = (spec.get("chain") or {}).get(role) if isinstance(spec.get("chain"), Mapping) else None
    desc = _s((given or {}).get("desc") if isinstance(given, Mapping) else "").strip()
    node = topology.node(role) if topology is not None else None
    return desc or _s(legacy).strip() or default or (node.desc if node is not None else "")


def rfve_dc_per_inverter(spec: Mapping, topology: Topology | None) -> bool:
    """DC rozvaděč u technologie na každý střídač (RFVE.DC1, RFVE.DC2…) místo jednoho společného RFVE.DC:
    `chain.rfve_dc.per_inverter` > `per_inverter` článku presetu > False (rozhodnutí 3 – výchozí společný)."""
    given = (spec.get("chain") or {}).get("rfve_dc") if isinstance(spec.get("chain"), Mapping) else None
    if isinstance(given, Mapping) and _s(given.get("per_inverter")).strip():
        return chain_flag(given.get("per_inverter"))
    node = topology.node("rfve_dc") if topology is not None else None
    return bool(node.per_inverter) if node is not None else False


def resolve_chain_refs(spec: dict, raw: Mapping, topology: Topology) -> None:
    """Označení a popisy článků do sloučené specifikace (`spec`, na místě): hlavní AC článek (`switchboard`),
    HR / RVN / RE přípojky VN (`connection.*_board`) – podle `node_ref` / `node_desc`. `raw` = specifikace před
    sloučením s `DEFAULT_SPEC` (jen tam jsou dřívější klíče zadané uživatelem, ne výchozí hodnoty)."""
    main_role = "rfve" if topology.node("rfve") is not None else "rfve_ac"
    sb_raw = raw.get("switchboard") if isinstance(raw.get("switchboard"), Mapping) else {}
    sb = spec["switchboard"] = dict(spec.get("switchboard") or {})
    sb["ref"] = node_ref(spec, topology, main_role, sb_raw.get("ref"), AC_SWITCHBOARD_REF)
    sb["desc"] = node_desc(spec, topology, main_role, sb_raw.get("desc"), _s(sb.get("desc")))
    conn_raw = raw.get("connection") if isinstance(raw.get("connection"), Mapping) else {}
    conn = spec["connection"] = dict(spec.get("connection") or {})
    for key, role, default in (("main_board", "hr", MAIN_LV_BOARD_REF), ("mv_board", "rvn", "RVN"),
                               ("meter_board", "re", "RE")):
        given = conn_raw.get(key) if isinstance(conn_raw.get(key), Mapping) else {}
        board = conn[key] = dict(conn.get(key) or {})
        board["ref"] = node_ref(spec, topology, role, given.get("ref"), default)
        board["desc"] = node_desc(spec, topology, role, given.get("desc"), _s(board.get("desc")))


# druh objektu (`spec["building"]`) → text v projektu (meta „building“)
BUILDINGS = {"company": "firma", "house": "rodinný dům", "apartment": "bytový dům"}
HOUSE_SWITCHBOARD = {"ref": "RFVE", "desc": "rozvaděč FVE (DC + AC)"}
HOUSE_SWITCHBOARD_AC = {"ref": "RFVE", "desc": "rozvaděč FVE (AC)"}   # bez DC části (`dc.tech_box` = false)


DEFAULT_SPEC = {
    "name": "Nový projekt FVE",
    "meta": {},
    "building": "company",   # company | house (DC i AC rozvaděč v jednom) | apartment
    "module": {"p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9, "beta_voc": -0.27, "type": ""},
    "site": {},   # {"t_min": -20, "t_max": 70} – návrhové teploty stringů (průvodce předvyplní ze standardu)
    "optimizer": {"type": "", "per_module": 1},
    "dc": {"cable": "H1Z2Z2-K 1x6", "cross": 6, "length": 30, "route_boxes": 1, "route_length": 20,
           "tech_box": True, "tech_length": 5, "spd": "T1+T2", "fuse_in": "", "disconnect_in": 32, "disconnect": False,
           # pojistkový odpojovač stringu (DC-20B – nespínat pod zátěží); "" = bez artiklu
           "fuse_component": "eti-efh-10-dc-2p",
           # artikl svodiče DC (typ, Uc, Up, ISCPV do výkresu) – použije se, když typ `spd` odpovídá artiklu; "" = bez
           "spd_component": "weidmuller-vpu-pv-i-ii-3-1000"},
    "ac": {"cable": "CYKY-J 5x16", "cross": 16, "length": 30, "breaker_in": 40, "main_in": 125,
           "grid_cable": "CYKY-J 5x35", "grid_cross": 35, "grid_length": 20, "spd": "T1+T2", "enclosure": "",
           "distribution": "bus"},
    "switchboard": {"ref": AC_SWITCHBOARD_REF, "desc": "AC rozvaděč FVE"},
    "grid": {"dso": "", "voltage": "3×400 V"},
    # připojení k DS: "nn" = AC rozvaděč FVE přímo do DS (HDS); "vn" = trafostanice: hlavní rozvaděč nn,
    # transformátor, rozvaděč VN (pole kioskové TS / kobky zděné TS; sloupová TS bez rozvaděče VN – odpínač, pojistky
    # a svodiče na sloupu) a elektroměrový rozvaděč. Fakturační měření na straně nn (MTP v hlavním rozvaděči) nebo vn
    # (MTP + MTN v měřicím poli VN; ne u sloupové TS). Prázdné hodnoty (main_in, ct_ratio, fuse_vn) se dopočtou ze Sn.
    "connection": {"level": "nn", "metering": "nn", "station": "kiosk", "u_vn": "22 kV", "loop": True,
                   "ts": {"ref": "TS1", "desc": ""},
                   "transformer": {"sn": 630, "type": "", "ratio": "22/0,42 kV", "group": "Dyn1", "uk": 6},
                   "mv_board": {"ref": "RVN", "desc": "rozvaděč VN"},
                   "main_board": {"ref": MAIN_LV_BOARD_REF, "desc": "hlavní rozvaděč nn", "main_in": "", "load_in": "",
                                  "fve_in": ""},
                   "meter_board": {"ref": "RE", "desc": "elektroměrový rozvaděč"},
                   "ct_ratio": "", "fuse_vn": "",
                   "vn_cable": "22-AXEKVCEY 3×1×70", "vn_cross": 70, "vn_length": 10,
                   "tr_cable": "4× 1-AYKY 3×240+120", "tr_cross": 240, "tr_length": 10,
                   "meas_i_cable": "CYKY-O 7×4", "meas_i_cross": 4, "meas_u_cable": "CYKY-J 5×2,5", "meas_u_cross": "2,5",
                   "meas_length": 5, "load": "spotřeba objektu"},
    # makra, ze kterých se rozvaděče skládají (název makra z knihovny; "" = vestavěný kód); výkresy ladí projektant
    "macros": {"dc_tech": "DC string v rozvaděči", "dc_route": "DC string po trase",
               "ac_feed": "AC přívod střídače", "ac_core": "AC jádro rozvaděče"},
}


def building_kind(v) -> str:
    """Druh objektu ze specifikace: "company" | "house" | "apartment" (přijme i české „firma“, „rodinný dům“, „RD“,
    „bytový dům“, „BD“); prázdné = firma. Neznámá hodnota → ValueError."""
    t = _s(v).strip().lower()
    if not t:
        return "company"
    aliases = {**{k: k for k in BUILDINGS}, **{c: k for k, c in BUILDINGS.items()},
               "rd": "house", "bd": "apartment", "rodinny dum": "house", "bytovy dum": "apartment"}
    if t not in aliases:
        raise ValueError(f"Neznámý druh objektu „{v}“ – zadejte firma, rodinný dům nebo bytový dům.")
    return aliases[t]


def is_solaredge(inv: Element | None, opt: dict) -> bool:
    """String SolarEdge (standard ENVO: pojistka stringu 25 A): výrobce, typ nebo artikl střídače, typ / artikl
    optimizéru obsahuje „SolarEdge“, nebo střídač pracuje s pevným napětím stringu (`string_mode` fixed_voltage –
    SE5K, SE12.5K–SE27.6K)."""
    texts = [opt.get("type"), opt.get("component_id")]
    if inv is not None:
        texts += [inv.attrs.get("manufacturer"), inv.attrs.get("type"), inv.component_id]
        if _s(inv.attrs.get("string_mode")).strip().lower() == "fixed_voltage":
            return True
    return any("solaredge" in re.sub(r"[\s_-]", "", _s(x).lower()) for x in texts)


def fuse_in_why(dc: dict, mod: dict, opt: dict, inv: Element | None) -> tuple[str, str]:
    """In pojistek stringů DC rozvaděče a důvod, proč zůstalo prázdné (jinak ""): zadané `dc.fuse_in`, jinak podle
    stringu (`calc.string_fuse_in`) – SolarEdge (`is_solaredge`) 25 A, jinak gPV ≥ 1,5·Isc modulu do 2,4·Isc, max.
    jištění modulu a max. In držáku (`in_max_a` artiklu `dc.fuse_component` kategorie fuse_holder, EFH 10 DC 25 A;
    i SolarEdge 25 A musí být ≤ max. In držáku). Když žádná velikost nevyhoví (nebo chybí Isc), vrací ("", důvod) –
    In zůstane prázdné, prvek dostane `in_unresolved` a kontrola (F7) hlásí chybu `fuse_no_in`; nic se tiše
    nedosazuje. Nic neloguje (varování jednou za střídač píše `build_project`)."""
    if _s(dc.get("fuse_in")).strip() not in ("", "auto"):
        return _s(dc["fuse_in"]), ""
    from envocad.model.calc import string_fuse_in
    holder = context._lib().component(dc.get("fuse_component")) if dc.get("fuse_component") else None
    max_in = holder_max_in(holder)
    solaredge = is_solaredge(inv, opt)
    fin = string_fuse_in(_num(mod.get("isc")), _num(mod.get("i_fuse_max")), optimizer=solaredge, max_in=max_in)
    if fin:
        return f"{fin:g}", ""
    lim = f"max. In držáku {max_in:g} A" if max_in else "max. In držáku –"
    if solaredge:
        return "", f"SolarEdge 25 A > {lim}"
    if not _num(mod.get("isc")):
        return "", "modul nemá Isc"
    return "", (f"žádná velikost gPV nevyhoví (Isc {_s(mod.get('isc'))} A, max. jištění modulu "
                f"{_s(mod.get('i_fuse_max')) or '–'} A, {lim})")


def _fuse_in(dc: dict, mod: dict, opt: dict, inv: Element | None) -> str:
    """In pojistek stringů (`fuse_in_why` bez důvodu); "" = neurčeno."""
    return fuse_in_why(dc, mod, opt, inv)[0]


def holder_max_in(comp) -> float | None:
    """Max. In vložky držáku pojistky: jen `in_max_a` artiklu kategorie fuse_holder (ne `in_` – to je jmenovitý
    proud držáku / odpínače, u OPVP katalogové Ie). Jiný nebo žádný artikl → None (bez meze)."""
    if comp is None or getattr(comp, "category", "") != "fuse_holder":
        return None
    return comp.num("in_max_a")


# údaje modulu ve specifikaci ← atribut prvku `fve.pv_string` (`Component.attr_values()`)
MODULE_SPEC_FROM_ATTR = {"p_module": "p_wp", "voc": "voc", "vmp": "vmp", "isc": "isc", "imp": "imp",
                         "beta_voc": "beta_voc", "u_sys_max": "u_sys_max", "type": "type", "manufacturer": "manufacturer",
                         "alpha_isc": "alpha_isc", "gamma_pmax": "gamma_pmax", "i_fuse_max": "i_fuse_max"}


def _apply_module_component(mod: dict) -> dict:
    """Artikl modulu (`module.component_id`) doplní údaje modulu, které specifikace nezadala (chybí nebo prázdné);
    zadané hodnoty mají přednost. Vrací novou specifikaci modulu; neznámý artikl → beze změny (stringy si
    `component_id` ponechají, kontrola projektu ho nahlásí). Desetinná čárka z CSV se převede na tečku."""
    out = dict(mod)
    comp = context._lib().component(mod.get("component_id"))
    if comp is None:
        return out
    for akey, val in comp.attr_values().items():
        skey = MODULE_SPEC_FROM_ATTR.get(akey)
        if skey and out.get(skey) in (None, ""):
            out[skey] = val if skey in ("type", "manufacturer") else val.replace(",", ".")
    out["component_id"] = comp.id
    return out


def _apply_inverter_component(t: Element, inv: dict) -> None:
    """Artikl střídače (`component_id`) doplní atributy, které specifikace nezadala (chybí nebo jsou prázdné) –
    např. typ, výrobce, `mppt` (→ počet DC vstupů), p_dc_max. Zadané hodnoty specifikace mají přednost.
    Neznámý artikl se ignoruje (prvek si `component_id` ponechá, kontrola projektu ho nahlásí)."""
    cid = inv.get("component_id")
    if not cid:
        return
    comp = context._lib().component(cid)
    if comp is None:
        return
    probe = Element(t.symbol_id, t.x, t.y, attrs=dict(t.attrs))
    for key, val in comp.apply_to(probe).items():
        if inv.get(key) in (None, ""):
            t.attrs[key] = val
    t.component_id = comp.id


INVERTER_MODE_KEYS = ("string_mode", "u_string", "n_opt_min", "n_opt_max", "p_string_max")


def _modules_per_optimizer(comp) -> int:
    mpo = comp.num("modules_per_optimizer")
    return 2 if mpo == 2 else 1


def _apply_optimizer_component(opt: dict) -> tuple[dict, object | None]:
    """Artikl optimizéru (`optimizer.component_id`): prázdný typ ← part_number, `per_module` ← 1 / modulů na
    optimizér (zadané jiné `per_module` se nepoužije – počet optimizérů musí odpovídat `opt_*` atributům; zaloguje
    se varování, průvodce to hlásí v asistentu). Vrací (nová specifikace optimizéru, artikl | None); neznámý artikl →
    beze změny a None. Průvodce při vymazaném typu `component_id` neposílá (= bez optimizérů)."""
    out = dict(opt)
    comp = context._lib().component(opt.get("component_id"))
    if comp is None or comp.category != "optimizer":
        return out, None
    if not str(out.get("type") or "").strip():
        out["type"] = comp.part_number
    per = 1 / _modules_per_optimizer(comp)
    given = _num(opt.get("per_module"))
    if given is not None and abs(given - per) > 1e-9:
        log.warning("optimizer.per_module %g neodpovídá artiklu %s (%g ks/modul) – použije se hodnota z artiklu",
                    given, comp.id, per)
    out["per_module"] = per
    out["component_id"] = comp.id
    return out, comp


def _apply_optimizer_rules(t: Element, inv: dict, comp) -> None:
    """Režim stringů a pravidla z artiklu optimizéru do střídače: `string_mode` jen když ho nezadala specifikace ani
    artikl střídače; `n_opt_min` = max, `n_opt_max` = min, `p_string_max` = min ze známých (artikl střídače, artikl
    optimizéru pro fázi střídače); hodnoty ze specifikace vyhrávají."""
    vals = comp.optimizer_values(t.attrs.get("phases") or 3)
    mode = (comp.params.get("string_mode") or "").strip()
    if not str(t.attrs.get("string_mode") or "").strip() and mode:
        t.attrs["string_mode"] = mode
    for key, okey, pick in (("n_opt_min", "opt_n_min", max), ("n_opt_max", "opt_n_max", min),
                            ("p_string_max", "opt_p_string_max", min)):
        if inv.get(key) not in (None, ""):
            continue
        known = [x for x in (_num(t.attrs.get(key)), _num(vals.get(okey))) if x is not None]
        if known:
            t.attrs[key] = f"{pick(known):g}"


# ---- vstupy průvodce (bez Qt, testovatelné) -------------------------------------------------------------------
def parse_strings(text: str) -> list[list[int]]:
    """„20,20,18; 20 20“ → [[20, 20, 18], [20, 20]]: střídače oddělené středníkem, stringy čárkou nebo mezerou.
    Počet modulů musí být celé kladné číslo; prázdné úseky (koncový středník) se přeskočí. Chyba → ValueError
    s českou hláškou."""
    out: list[list[int]] = []
    for i, part in enumerate(str(text or "").split(";"), start=1):
        tokens = [t for t in part.replace(",", " ").split() if t]
        if not tokens:
            continue
        nums = []
        for t in tokens:
            if not t.isdigit() or int(t) <= 0:
                raise ValueError(f"Stringy (střídač {i}): „{t}“ není celé kladné číslo (počet modulů ve stringu).")
            nums.append(int(t))
        out.append(nums)
    if not out:
        raise ValueError("Stringy: zadejte alespoň jeden string (počty modulů oddělené čárkou nebo mezerou, "
                         "střídače středníkem).")
    return out


def parse_number(text: str, label: str, *, integer: bool = False, minimum: float = 0.0, strict: bool = True,
                 allow_empty: bool = False) -> int | float | str:
    """Číslo z pole průvodce (desetinná čárka i tečka). `strict` = musí být > minimum, jinak ≥ minimum.
    Prázdné pole s `allow_empty` → "". Chyba → ValueError s českou hláškou s názvem pole."""
    t = str(text or "").strip().replace(",", ".")
    if not t:
        if allow_empty:
            return ""
        raise ValueError(f"{label}: zadejte hodnotu.")
    try:
        v = float(t)
    except ValueError:
        raise ValueError(f"{label}: „{text.strip()}“ není číslo.") from None
    if not math.isfinite(v):
        raise ValueError(f"{label}: „{text.strip()}“ není číslo.")
    if integer and not v.is_integer():
        raise ValueError(f"{label}: zadejte celé číslo (ne „{text.strip()}“).")
    if (strict and v <= minimum) or (not strict and v < minimum):
        cmp = "větší než" if strict else "alespoň"
        raise ValueError(f"{label}: hodnota musí být {cmp} {minimum:g}.")
    if integer or v.is_integer() and "." not in t:
        return int(v)
    return v


def load_spec(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))
