"""Generování celého projektu ze specifikace (průvodce v GUI i rozhraní pro agenty). Bez Qt.

    python -m envocad.generate spec.json vystup.ecp

Specifikace (JSON, vše kromě `inverters` volitelné – viz `DEFAULT_SPEC`):
{
  "name": "FVE Firma s.r.o.", "meta": {"investor": "…", "place": "…", "order": "…", "author": "…"},
  "building": "company",                                              # company (firma) | house (rodinný dům) | apartment (bytový dům)
  "module": {"p_wp": 450, "voc": 49.5, "vmp": 41.5, "isc": 13.9, "beta_voc": -0.27, "type": "JA Solar …",
             "imp": 13.2, "u_sys_max": 1500,                          # nepovinné: Impp, max. napětí systému modulu
             "alpha_isc": 0.045, "gamma_pmax": -0.29,                 # nepovinné [%/K]: oba → součinitel Umpp = γ − α
             "component_id": "ja-solar-jam54d40-450"},                # nepovinné: artikl modulu (pv_modules.csv)
  "site": {"t_min": -20, "t_max": 70},                                # návrhové teploty stringů → meta pv_t_min/pv_t_max
  "optimizer": {"type": "", "per_module": 1,                         # optimizéry (prázdný typ = bez optimizérů)
                "component_id": "solaredge-s440-1gm4mrm"},            # nepovinné: artikl optimizéru (optimizers.csv)
  "inverters": [{"ref": "T1", "type": "SMA STP 25-50", "p_ac": 25, "phases": 3, "u_dc_max": 1100,
                 "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [20, 20, 18, 18],
                 "isc_mppt_max": 40, "strings_per_mppt": 2, "mppt": 2,       # nepovinné (jinak z artiklu, mppt dopočet)
                 "string_mode": "", "u_string": 750, "n_opt_min": 14,        # nepovinné: režim stringů a pravidla
                 "n_opt_max": 50, "p_string_max": 11250,                     # (jinak z artiklů střídače a optimizéru)
                 "component_id": "sma-stp-25-50"}],
  "dc": {"cable": "H1Z2Z2-K 1x6", "cross": 6, "length": 40,          # string → první DC rozvaděč
         "route_boxes": 1, "route_length": 20,                        # DC rozvaděče po trase (jen SPD, bez odpínače), kabel mezi nimi
         "tech_box": true, "tech_length": 5,                          # DC rozvaděč u technologie (pojistkové odpínače + SPD), kabel ke střídači
         "spd": "T1+T2", "fuse_in": "",                              # "" = podle stringu (gPV ≥ 1,5·Isc; SolarEdge 25 A;
                                                                      #  nevyhoví-li žádná, In prázdné + chyba F7)
         "disconnect_in": 32, "fuse_component": "eti-efh-10-dc-2p",   # pojistkový odpojovač ETI EFH 10 DC 2p
         "spd_component": "weidmuller-vpu-pv-i-ii-3-1000",            # artikl SPD (typ, Uc, Up, ISCPV), když typ odpovídá
         "disconnect": false},                                        # jen samostatný odpínač v JPS bez DC rozvaděčů (stará varianta)
  "ac": {"cable": "CYKY-J 5x16", "cross": 16, "length": 30, "breaker_in": 40, "main_in": 125,
         "grid_cable": "CYKY-J 5x35", "grid_cross": 35, "grid_length": 20, "spd": "T1+T2", "enclosure": "",
         "distribution": "bus"},                                      # rozvod v AC rozvaděči: "bus" (sběrnice potenciálů) | "terminals" (svorky s můstky)
  "switchboard": {"ref": "RFVE.AC", "desc": "AC rozvaděč FVE"},
  "grid": {"dso": "ČEZ Distribuce", "voltage": "3×400 V"},
  "connection": {"level": "vn", "metering": "nn",                     # "nn" = do HDS (výchozí), "vn" = trafostanice
                 "station": "kiosk", "ts": {"ref": "TS1", "desc": ""}, # kiosk | kobky (zděná) | sloup (sloupová)
                 "u_vn": "22 kV", "loop": true,                       # „22 kV“ / „22000 V“ / „22“; smyčka = 2 kabelová pole
                 "transformer": {"sn": 630, "ratio": "22/0,42 kV", "group": "Dyn1", "uk": 6},
                 "main_board": {"ref": "HR", "main_in": "", "load_in": "",    # "" = ze Sn transformátoru
                                "fve_in": ""},                        # "" = ac.main_in omezené selektivitou (F7)
                 "ct_ratio": "", "fuse_vn": "", "vn_cable": "22-AXEKVCEY 3×1×70", "tr_cable": "4× 1-AYKY 3×240+120"},
  "battery": {"e_kwh": 10, "p_kw": 5, "type": "…",        # volitelné, jen u hybridního střídače
              "cable": "H1Z2Z2-K 1x25", "cross": 25, "length": 5},   # kabel k baterii (výchozí `BATTERY_CABLE`)
  "macros": {"dc_tech": "DC string v rozvaděči", "dc_route": "DC string po trase",   # rozvaděče se skládají z maker
             "ac_feed": "AC přívod střídače", "ac_core": "AC jádro rozvaděče"},      # (knihovna → Makra); "" = kód
  "jps": {"split": "auto", "max_paper": "A2", "paper": "A2"}   # rozdělení velkého JPS na listy (viz níže)
}
Položka `macros` smí být i objekt {"name": "DC string v rozvaděči", "value_set": "Pojistka 20 A gPV, SPD T1+T2",
"values": {"fuse_in": 25}} – sada hodnot a hodnoty proměnných makra přebijí základ ze `dc`/`ac` (docs/LIBRARY_FORMAT.md,
„Formát makra“). Neplatná hodnota → ValueError s názvem makra. In (`fuse_in`, `disconnect_in`, `breaker_in`, `main_in`)
jsou čísla v A (ne „C40“), `spd` je text (T1, T2, T1+T2, T1+T2+T3…). Artikl střídače (`component_id`) doplní atributy,
které specifikace nezadala (typ, výrobce, mppt, strings_per_mppt…) – ještě před dopočtem `mppt` z počtu stringů.
Se známým `mppt` (specifikace nebo artikl) se stringy zapojí na MPPT rovnoměrně (string k → MPPT k mod mppt), jinak
za sebou DC1, DC2… (`calc.string_ports`). Neznámé `strings_per_mppt` zůstane v atributu prázdné (kontrola pak proudy
paralelních stringů nesčítá); pro počet DC vstupů se počítá se 2 na MPPT.
Artikl modulu (`module.component_id`) stejně doplní prázdné údaje modulu (p_wp, voc, vmp, isc, imp, beta_voc,
u_sys_max, alpha_isc, gamma_pmax, typ, výrobce); zadané hodnoty specifikace vyhrávají a stringy dostanou `component_id` artiklu.
Artikl optimizéru (`optimizer.component_id`, docs/design/optimizery.md) doplní prázdný typ (part_number) a
`per_module` = 1 / modulů na optimizér; stringy dostanou atributy `opt_*` (`Component.optimizer_values(phases)`)
a `n_optimizers` = ⌈n / modulů na optimizér⌉. Režim stringů střídače (`string_mode`): specifikace > artikl střídače >
artikl optimizéru > classic (prázdné); pravidla `n_opt_min` / `n_opt_max` / `p_string_max` nejpřísnější ze známých
(artikl střídače, artikl optimizéru pro fázi střídače), zadaná ve specifikaci vyhrávají. Bez `component_id` beze změny.
`building` = druh objektu: u rodinného domu (`house`) je DC i AC rozvaděč v jednom – rozvaděč FVE (RFVE) má přívody
od střídačů X1…Xn, DC přívody stringů a vývody ke střídači (pojistkové odpínače + SPD) a vývod do HDS; samostatný DC
rozvaděč u technologie se netvoří (rozvaděče po trase zůstávají); s `dc.tech_box` false je RFVE jen AC („rozvaděč FVE
(AC)“). Rodinný dům se připojuje do HDS – `connection.level` "vn" → ValueError. Firma a bytový dům: DC rozvaděče a AC
rozvaděč zvlášť.
Označení rozvaděčů (docs/NAVRH_TOPOLOGIE.md, kap. 8 bod 9): AC rozvaděč FVE RFVE.AC (`switchboard.ref`), DC rozvaděč
u technologie RFVE.DC – při více střídačích (jeden rozvaděč u technologie na střídač) RFVE.DC1, RFVE.DC2… v pořadí
střídačů; rozvaděče po trase RDC1…n (číslované souvisle jen mezi sebou), hlavní rozvaděč nn u přípojky VN HR
(`connection.main_board.ref`), rodinný dům jeden rozvaděč RFVE. Zadané `ref` ve specifikaci platí.
Rozvaděče po trase mají jen SPD (přívod vede rovně na vývod) – odpojovací místo stringů jsou pojistkové odpínače
v rozvaděči u střídače.
`site.t_min` / `site.t_max` [°C] se zapíšou do `meta["pv_t_min"]` / `meta["pv_t_max"]` (kontrola stringů,
`calc.design_temperatures`); bez nich platí výchozí −10 / 70 °C.
`jps.split` "auto" (výchozí) rozdělí JPS, které by se nevešlo na `jps.max_paper` (výchozí firemní standard
`jps_max_paper` = A2), na listy formátu `jps.paper` (výchozí = limit): první „Blokové schéma – AC a připojení“
(AC rozvaděč, síť, HOP; u přípojky VN celá přípojka – hlavní rozvaděč nn, transformátor, rozvaděč VN, elektroměrový
rozvaděč, rámeček TS; u rodinného domu rozvaděč FVE s DC i AC částí) jako přehled, za ním listy střídačů („Blokové
schéma – T1–T3“). Vodiče mezi řadou střídače a listem AC (AC kabel „AC-T1“, u rodinného domu i DC vodiče do RFVE a
z něj „RFVE-X5“) vedou přes páry přerušovacích bodů, údaje kabelu nese jen úsek na listu AC. "none" = vždy jeden
list (zvětší se formát). Odvozené jednopólové schéma je stejné jako bez rozdělení. Návrh
`docs/design/dluhy_dxf_jps.md`, bod B.
"""
from __future__ import annotations

import math
import re
import sys

from envocad.generator import context
from envocad.generator.boards.macro_glue import (  # noqa: F401 – re-export (testy)
    FUSE_SYMBOLS,
    UNRESOLVED_IN,
    _ac_box_from_macros,
    _blank_unresolved,
    _dc_box_from_macro,
    _feed_macro_from_below,
    _macro_ref,
    _macro_values,
)
from envocad.generator.boards.mv import (  # noqa: F401 – re-export (testy)
    _build_main_lv_board,
    _build_meter_board,
    _build_mv_board,
    _connection_blocks,
    connection_currents,
    fve_feeder_in,
    inverters_ac_current,
    parse_voltage,
    voltage_label,
)
from envocad.generator.boards.rfve import _add_dc_part, _dc_from_below
from envocad.generator.boards.rfve_ac import (  # noqa: F401 – re-export (testy, tools)
    BUS_B_X,
    _ac_core_after_feeds,
    _build_ac_switchboard,
)
from envocad.generator.boards.rfve_dc import (
    _apply_component,
    _apply_spd_component,
    _mark_unresolved,
    dc_box_ref,
)
from envocad.generator.context import (
    AC_MAX_INVERTERS_BUS,
    BATTERY_CABLE,
    BATTERY_ROW_EXTRA,
    INV_LABEL_SPACE,
    _int_attr,
    _merge,
    _s,
    log,
)
from envocad.generator.jps import (  # noqa: F401 – re-export (testy)
    JPS_AC_SHEET_NAME,
    JPS_AC_SUFFIX,
    _place_jps,
    jps_max_paper,
    ref_ranges,
)
from envocad.generator.layout import (
    _align_bends,
    _align_connection,
    _align_outputs,
    _align_route_boxes,
    _grow_switchboards,
    _route_house,
)
from envocad.generator.spec import (  # noqa: F401 – re-export veřejného API (testy, ui/dialogs.py)
    BUILDINGS,
    DEFAULT_SPEC,
    HOUSE_SWITCHBOARD,
    HOUSE_SWITCHBOARD_AC,
    INVERTER_MODE_KEYS,
    _apply_inverter_component,
    _apply_module_component,
    _apply_optimizer_component,
    _apply_optimizer_rules,
    _fuse_in,
    _modules_per_optimizer,
    building_kind,
    fuse_in_why,
    holder_max_in,
    is_solaredge,
    load_spec,
    parse_number,
    parse_strings,
)
from envocad.library.templates import (
    AC_CONDUCTORS,
    DC_CONDUCTORS,
    build_dc_strings,
)
from envocad.model.calc import DC_INPUTS_PER_MPPT_DEFAULT, InverterData, string_ports
from envocad.model.project import (
    PORT_PITCH,
    Element,
    Project,
    Wire,
    WireEnd,
    element_symbol,
    sync_cables,
    sync_feed_links,
)


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
    if building == "house" and not spec.get("switchboard"):
        tech = _merge(DEFAULT_SPEC["dc"], spec.get("dc") or {}).get("tech_box")
        spec["switchboard"] = dict(HOUSE_SWITCHBOARD if tech else HOUSE_SWITCHBOARD_AC)
    spec = _merge(DEFAULT_SPEC, spec)
    invs = spec.get("inverters") or []
    if not invs:
        raise ValueError("Specifikace musí obsahovat alespoň jeden střídač (`inverters`).")
    if (spec["ac"].get("distribution") or "bus") == "bus" and len(invs) > AC_MAX_INVERTERS_BUS:
        raise ValueError(f"AC rozvaděč: sběrnice má {AC_MAX_INVERTERS_BUS} přívodů – nejvýš {AC_MAX_INVERTERS_BUS} "
                         f"střídačů (zadáno {len(invs)}). Zvolte rozvod svorkami nebo rozdělte FVE na více rozvaděčů.")
    # rodinný dům: DC část (pojistkové odpínače + SPD, místo rozvaděče u technologie) je v rozvaděči FVE s AC částí
    combined = building == "house" and bool(spec["dc"].get("tech_box"))
    if building == "house" and _s((spec.get("connection") or {}).get("level")).strip().lower() == "vn":
        raise ValueError("Rodinný dům: rozvaděč FVE se připojuje do HDS (připojení na nn) – přípojka VN se "
                         "negeneruje. Zvolte druh objektu firma, nebo připojení nn.")
    p = Project(name=spec["name"], meta={k: _s(v) for k, v in spec["meta"].items()})
    p.meta.setdefault("building", BUILDINGS[building])
    site = spec.get("site") or {}
    for key, meta_key in (("t_min", "pv_t_min"), ("t_max", "pv_t_max")):
        if site.get(key) not in (None, ""):
            p.meta[meta_key] = _s(site[key])
    s = p.sheets[0]
    s.name = "Blokové schéma"
    mod, dc, ac = spec["module"], spec["dc"], spec["ac"]
    opt = spec.get("optimizer") or {}
    opt_per = float(opt.get("per_module") or 1) if opt.get("type") else 0.0
    # svislé rozestupy řad střídačů podle počtu stringů; souřadnice jsou zatím pracovní – na list (formát, střed,
    # vnitřní rámeček, popisové pole) se obsah rozmístí až na konci (`frame.fit_sheet_to_content`)
    row_h = [max(60.0, 45.0 * max(len(inv.get("strings") or [1]), 1) + 15.0) for inv in invs]   # 45 mm na string (popisek nad ním)
    # hybridní střídač: baterie pod ním, v řadě se pro ni přidá místo (kabel jde krátce dolů, přes nic jiného)
    row_extra = [BATTERY_ROW_EXTRA if spec.get("battery") and i == 0 else 0.0 for i in range(len(invs))]
    total_h = sum(row_h) + sum(row_extra)
    y_top = 150.0 + total_h / 2
    n_route = max(0, int(dc.get("route_boxes") or 0))
    n_boxes = n_route + (1 if dc.get("tech_box") else 0)   # u rodinného domu je posledním „rozvaděčem“ rozvaděč FVE
    box_pitch = 85.0            # mezi rozvaděči se vejde popisek kabelu i dvojitý křížový odkaz
    x_str = 35.0
    n_max = max(len(inv.get("strings") or [1]) for inv in invs)
    n_all = sum(len(inv.get("strings") or [1]) for inv in invs)
    # rozvaděč FVE: lomy všech stringů do jednoho bloku a vlevo od něj svislé úseky AC vodičů od střídačů
    n_lanes = n_all + len(invs) if combined else n_max
    dc_first = len(invs) + (1 if (spec["ac"].get("distribution") or "bus") == "bus" else 2)   # za AC přívody (a svorkami X(n+1))
    x_box0 = x_str + 60.0 + 5.0 * n_lanes   # lomy stringů až za popisky kabelů u stringů
    x_boxes = [x_box0 + j * box_pitch for j in range(n_boxes)]
    if combined and n_boxes > 1:
        # rozvaděč FVE za rozvaděči po trase: popisek kabelu od rozvaděče po trase (~40 mm) se musí vejít před lomy
        # všech DC vodičů do RFVE (5 mm na string a na AC vodič střídače) – jinak popisek přetéká přes svůj lom
        x_boxes[-1] = x_boxes[-2] + max(box_pitch, 70.0 + 5.0 * n_lanes)
    x_dc = 130.0                                                   # samostatný odpínač DC (bez rozvaděčů)
    # před střídačem: popisek kabelu za blokem rozvaděče + vějíř lomů (5 mm na string) před DC vstupy střídače
    x_inv = (x_boxes[-1] + max(80.0, 15.0 + INV_LABEL_SPACE + 5.0 * n_max + 10.0)) if n_boxes else 200.0
    x_blk, x_grid = x_inv + 110.0, x_inv + 185.0   # mezi střídačem a rozvaděčem se vejde popisek AC kabelu
    if combined:   # rozvaděč FVE na místě DC rozvaděče u technologie (před střídači), síť za střídači
        x_blk, x_grid = x_boxes[-1], x_inv + 75.0
    p_total = 0.0
    blk = Element("fve.switchboard", x_blk, 150.0, attrs={"ref": spec["switchboard"]["ref"], "desc": spec["switchboard"]["desc"]})
    s.elements.append(blk)
    ac_wires: list[Wire] = []
    k_all = 0                   # pořadí stringu v rozvaděči FVE (přes všechny střídače)
    y = y_top
    inverter_elements: list[Element] = []
    rows: list[list[Element]] = []      # prvky řady střídače (střídač, stringy, DC rozvaděče…) – rozdělení JPS na listy
    inverter_strings: list[list[Element]] = []
    dc_boxes: list[tuple[Element, list[Element], str, int, str]] = []   # (blok, stringy, druh, č. střídače, střídač)
    n_tech = len(invs) if dc.get("tech_box") and not combined else 0   # DC rozvaděče u technologie (jeden na střídač)
    for i, inv in enumerate(invs):
        strings = inv.get("strings") or [1]
        y_mid = y - row_h[i] / 2
        ref_t = inv.get("ref") or f"T{i + 1}"
        t = Element("fve.inverter_hybrid" if spec.get("battery") and i == 0 else "fve.inverter", x_inv, y_mid, attrs={
            "ref": ref_t, "type": _s(inv.get("type")), "p_ac": _s(inv.get("p_ac")), "phases": _s(inv.get("phases", 3)),
            "mppt": _s(inv.get("mppt")), "strings_per_mppt": _s(inv.get("strings_per_mppt")),
            "u_dc_max": _s(inv.get("u_dc_max")), "u_mppt_min": _s(inv.get("u_mppt_min")),
            "u_mppt_max": _s(inv.get("u_mppt_max")), "i_mppt_max": _s(inv.get("i_mppt_max")),
            "p_dc_max": _s(inv.get("p_dc_max"))}, component_id=inv.get("component_id"))
        for key in ("isc_mppt_max", *INVERTER_MODE_KEYS):   # jen zadané – starší specifikace beze změny výstupu
            if inv.get(key) not in (None, ""):
                t.attrs[key] = _s(inv[key])
        # artikl dřív než dopočet MPPT: jeho strings_per_mppt / mppt určí počet DC vstupů
        _apply_inverter_component(t, inv)
        if opt_comp is not None:
            _apply_optimizer_rules(t, inv, opt_comp)
        # pás svorek typu střídače (záloha, komunikace – `inverter_io`) visí pod značkou: místo v řadě
        from envocad.model.inverter_io import inverter_io
        row_extra[i] += 5.0 * len(inverter_io(t.attrs))
        # neznámé stringů na MPPT zůstane prázdné (kontrola pak proudy na MPPT nesčítá); výchozí 2 jen pro DC vstupy
        spm_known, mppt_known = _int_attr(t.attrs.get("strings_per_mppt")), _int_attr(t.attrs.get("mppt"))
        t.attrs["strings_per_mppt"] = str(spm_known) if spm_known else ""
        spm = spm_known or DC_INPUTS_PER_MPPT_DEFAULT
        # známé mppt: stringy rovnoměrně po MPPT (string k → MPPT k mod mppt), jinak DC1, DC2… za sebou (`calc.string_ports`)
        ports = string_ports(len(strings), InverterData(mppt=mppt_known, strings_per_mppt=spm_known))
        n_mppt = mppt_known or max(1, -(-len(strings) // spm))
        t.attrs["mppt"] = str(n_mppt)          # i „2.0“ / „2,0“ ze specifikace nebo artiklu → „2“
        s.elements.append(t)
        inverter_elements.append(t)
        row = [t]
        rows.append(row)
        gens: list[Element] = []
        inverter_strings.append(gens)
        for k, n_mod in enumerate(strings):
            ys = y - 35.0 - k * 45.0
            p_str = round(n_mod * float(str(mod.get("p_wp") or 0).replace(",", ".")) / 1000, 2)
            p_total += p_str
            g = Element("fve.pv_string", x_str, ys, attrs={
                "ref": p.next_ref("G"), "type": _s(mod.get("type")), "n_modules": _s(n_mod), "p_module": _s(mod.get("p_wp")),
                "p_string": f"{p_str:g} kWp", "voc": _s(mod.get("voc")), "vmp": _s(mod.get("vmp")),
                "isc": _s(mod.get("isc")), "beta_voc": _s(mod.get("beta_voc")),
                "n_optimizers": _s(round(n_mod * opt_per)) if opt_per else "", "optimizer": _s(opt.get("type")) if opt_per else ""},
                component_id=mod.get("component_id") or None)
            if opt_comp is not None and opt_per:
                # artikl optimizéru: parametry pro kontrolu stringů, počet zaokrouhlený nahoru (2:1 a lichý počet)
                g.attrs.update(opt_comp.optimizer_values(t.attrs.get("phases") or 3))
                g.attrs["optimizer"] = _s(opt.get("type"))
                g.attrs["n_optimizers"] = _s(math.ceil(n_mod / _modules_per_optimizer(opt_comp)))
            for key in ("imp", "u_sys_max", "manufacturer", "alpha_isc", "gamma_pmax"):   # jen zadané – starší specifikace beze změny výstupu
                if mod.get(key) not in (None, ""):
                    g.attrs[key] = _s(mod[key])
            s.elements.append(g)
            gens.append(g)
            row.append(g)
        # DC rozvaděče: po trase (jen SPD) a u technologie (pojistkové odpínače + SPD); stringy jimi procházejí odděleně
        boxes: list[Element] = []
        for j in range(n_boxes):
            kind = "tech" if (dc.get("tech_box") and j == n_boxes - 1) else "route"
            if kind == "tech" and combined:
                boxes.append(blk)
                break
            desc = f"DC rozvaděč u {ref_t}" if kind == "tech" else (f"DC rozvaděč po trase {ref_t}" + (f" ({j + 1})" if n_route > 1 else ""))
            b = Element("fve.switchboard", x_boxes[j], y_mid, attrs={"ref": dc_box_ref(kind, i, n_tech, p), "desc": desc})
            s.elements.append(b)
            boxes.append(b)
            row.append(b)
            dc_boxes.append((b, gens, kind, i + 1, ref_t))
        n_str = len(gens)
        # porty bloku DC rozvaděče (viz switchboard_symbol): rozteč PORT_PITCH, shora dolů
        half = max(20.0, n_str * PORT_PITCH + PORT_PITCH) / 2
        port_y = [y_mid + round((half - PORT_PITCH / 2 - k * PORT_PITCH) / 2.5) * 2.5 for k in range(n_str)]
        n_in = max(2, n_mppt * spm, n_str)   # DC vstupy střídače (viz inverter_symbol)
        for k, g in enumerate(gens):
            port_inv = f"DC{ports[k]}"   # každý string má na střídači vlastní vstup – stringy se nespojují
            j_in = ports[k] - 1          # pořadí vstupu shora (DC1 nahoře)
            if boxes:
                prev, prev_port = g, "DC"
                for j, b in enumerate(boxes):
                    length = dc.get("length") if j == 0 else dc.get("route_length")
                    # string → 1. rozvaděč: lom každého stringu na vlastním x, aby se svislé úseky nekryly
                    pts = [] if j else [(b.x - 15.0 - 5.0 * (n_str - k), g.y), (b.x - 15.0 - 5.0 * (n_str - k), port_y[k])]
                    port_in, port_out = f"X{k + 1}", f"X{n_str + k + 1}"
                    if b is blk:   # rozvaděč FVE: stringy všech střídačů za AC přívody, lomy (doladí `_align_bends`)
                        port_in, port_out = f"X{dc_first + k_all}", f"X{dc_first + n_all + k_all}"
                        xj = b.x - 15.0 - 5.0 * len(invs) - 5.0 * (n_all - k_all)
                        pts = [(xj, prev.y if j == 0 else port_y[k]), (xj, port_y[k])]
                    s.wires.append(Wire(WireEnd(prev.id, prev_port), WireEnd(b.id, port_in), conductors=list(DC_CONDUCTORS),
                                        points=pts,
                                        attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                               "length": _s(length), "method": "E"}))
                    prev, prev_port = b, port_out
                # vějíř lomů těsně před DC vstupy střídače (5 mm rozestup) – za popiskem kabelu, mimo značku střídače;
                # pořadí lomů bez křížení doladí `_align_bends`
                xb = t.x - 10.0 - 5.0 * (n_str - k)
                y_inv = t.y + (2.5 * (n_in - 1) - 5.0 * j_in if n_in > 2 else (5.0 if j_in == 0 else -5.0))
                s.wires.append(Wire(WireEnd(prev.id, prev_port), WireEnd(t.id, port_inv), conductors=list(DC_CONDUCTORS),
                                    points=[(xb, port_y[k]), (xb, y_inv)],
                                    attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                           "length": _s(dc.get("tech_length")), "method": "E"}))
            elif dc.get("disconnect"):
                q = Element("fve.dc_disconnect", x_dc, g.y, attrs={"ref": p.next_ref("Q"), "in_": _s(dc.get("disconnect_in") or 32),
                                                                  "poles": "2", "modules": "2"})
                s.elements.append(q)
                row.append(q)
                s.wires.append(Wire(WireEnd(g.id, "DC"), WireEnd(q.id, "1"), conductors=list(DC_CONDUCTORS),
                                    attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                           "length": _s(dc.get("length")), "method": "E"}))
                s.wires.append(Wire(WireEnd(q.id, "2"), WireEnd(t.id, port_inv), conductors=list(DC_CONDUCTORS), attrs={"ref": ""}))
            else:
                s.wires.append(Wire(WireEnd(g.id, "DC"), WireEnd(t.id, port_inv), conductors=list(DC_CONDUCTORS),
                                    attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                           "length": _s(dc.get("length")), "method": "E"}))
            k_all += 1
        # AC vodič ke bloku rozvaděče – port podle přívodu (X1, X2…), doplní se po vytvoření listu
        w_ac = Wire(WireEnd(t.id, "AC"), WireEnd(blk.id, f"X{i + 1}"), conductors=list(AC_CONDUCTORS),
                    attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("cable")), "cross": _s(ac.get("cross")),
                           "length": _s(ac.get("length")), "method": "B1"})
        s.wires.append(w_ac)
        ac_wires.append(w_ac)
        y -= row_h[i] + row_extra[i]
    if spec.get("battery"):
        b = spec["battery"]
        t0 = inverter_elements[0]
        # baterie přímo pod svým (hybridním) střídačem: port BAT dole (pod pásem svorek, je-li) → port DC baterie
        # nahoře, svisle 15 mm
        bat_y = element_symbol(p, t0, context._lib()).port("BAT").y
        bat = Element("fve.battery", t0.x, t0.y + bat_y - 25.0, attrs={
            "ref": "G" + str(len([e for e in s.elements if e.symbol_id == "fve.pv_string"]) + 1),
            "type": _s(b.get("type")), "e_kwh": _s(b.get("e_kwh")), "p_kw": _s(b.get("p_kw"))})
        s.elements.append(bat)
        rows[0].append(bat)
        bc = {k: b.get(k) if b.get(k) not in (None, "") else v for k, v in BATTERY_CABLE.items()}
        s.wires.append(Wire(WireEnd(t0.id, "BAT"), WireEnd(bat.id, "DC"), conductors=list(DC_CONDUCTORS),
                            attrs={"ref": p.next_ref("W"), "cable": _s(bc["cable"]), "cross": _s(bc["cross"]),
                                   "length": _s(bc["length"])}))
    conn = spec.get("connection") or {}
    chain = None
    if _s(conn.get("level")).strip().lower() == "vn":
        # přípojka VN: RFVE.AC → hlavní rozvaděč nn HR → transformátor → rozvaděč VN → DS (listy rozvaděčů níže)
        chain = _connection_blocks(p, s, spec, blk, x_blk)
        grid = chain["grids"][0]
    else:
        grid = Element("fve.grid", x_grid, 150.0, attrs={"ref": "", "voltage": _s(spec["grid"].get("voltage")),
                                                         "dso": _s(spec["grid"].get("dso"))})
        s.elements.append(grid)
        s.wires.append(Wire(WireEnd(blk.id, "XOUT"), WireEnd(grid.id, "1"), conductors=list(AC_CONDUCTORS),
                            attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("grid_cable")),
                                   "cross": _s(ac.get("grid_cross")), "length": _s(ac.get("grid_length")), "method": "D"}))
    earth = None
    if (ac.get("distribution") or "bus") == "bus" or combined:
        # PE rozvaděče je uzemněný na ekvipotenciální svorkovnici (HOP) vně rozvaděče – vývod XPE → uzemnění
        earth = Element("fve.earth", x_blk + (42.5 if chain is not None else 35.0), 150.0 - 40.0, attrs={"ref": "", "desc": "ekvipotenciální svorkovnice (HOP)"})
        s.elements.append(earth)
        s.wires.append(Wire(WireEnd(blk.id, "XPE"), WireEnd(earth.id, "PE"), conductors=["PE"],
                            attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("pe_cable") or "CYA 16"), "cross": _s(ac.get("pe_cross") or 16),
                                   "length": _s(ac.get("pe_length") or 5)}))
    p.meta.setdefault("p_installed_kwp", f"{p_total:g}")
    # listy DC rozvaděčů a AC rozvaděče
    macros = spec.get("macros") or {}
    inv_by_ref = {t.ref: t for t in inverter_elements}
    fuse_cache: dict[str, tuple[str, str]] = {}

    def fuse_of(t: Element | None) -> tuple[str, str]:
        """In pojistek stringů střídače a důvod prázdného In – spočte a případně zaloguje jednou za střídač (ne pro
        každý jeho rozvaděč po trase)."""
        key = t.ref if t is not None else ""
        if key not in fuse_cache:
            fuse_cache[key] = fuse_in_why(dc, mod, opt, t)
            if not fuse_cache[key][0]:
                log.warning("Pojistka stringu %s: %s – In zůstává prázdné", key, fuse_cache[key][1])
        return fuse_cache[key]

    for b, gens, kind, inv_no, inv_ref in dc_boxes:
        sheet = p.create_switchboard_sheet(b)
        sheet.layout.params.setdefault("network", "DC IT")
        sheet.layout.params.setdefault("un", "max. 1000 V DC")
        entry = macros.get("dc_tech" if kind == "tech" else "dc_route", "")
        fin, why = fuse_of(inv_by_ref.get(inv_ref))
        dc_box = {**dc, "fuse_in": fin}
        if not _dc_box_from_macro(p, sheet, [g.ref for g in gens], entry, dc_box, inv_no, inv_ref):
            build_dc_strings(p, sheet, [g.ref for g in gens], kind, _s(dc_box["fuse_in"]),
                             _s(dc.get("disconnect_in") or 32), _s(dc.get("spd") or "T2"))
        _apply_spd_component(sheet, dc.get("spd_component"))
        _apply_component(sheet, dc.get("fuse_component"), "fve.fuse_disconnect")
        if not fin:
            _mark_unresolved(sheet.elements, FUSE_SYMBOLS, why)
    sb = p.create_switchboard_sheet(blk)
    sb.layout.params.setdefault("network", "3NPE, 50 Hz")
    sb.layout.params.setdefault("un", "230/400 V")
    sb.layout.params.setdefault("in_", _s(ac.get("main_in") or 125))
    if not _ac_box_from_macros(p, sb, invs, ac, macros):
        _build_ac_switchboard(p, sb, invs, ac, spec)
    if combined:
        sb.layout.params["network"] = "3NPE, 50 Hz / DC IT"
        sb.layout.params["un"] = "230/400 V AC / max. 1000 V DC"
        groups = [(i + 1, t.ref, [g.ref for g in gens], fuse_of(t)[0])
                  for i, (t, gens) in enumerate(zip(inverter_elements, inverter_strings))]
        # DC přívody za vším, co AC část označila X<číslo> (PE lišta, svorkovnice); porty JPS se posunou s nimi
        used = [int(m.group(1)) for e in sb.elements if (m := re.fullmatch(r"X(\d+)", e.ref or ""))]
        first = max([dc_first - 1, *used]) + 1
        if first != dc_first:
            for w in s.wires:
                for end in (w.a, w.b):
                    m = re.fullmatch(r"X(\d+)", end.port) if end.element_id == blk.id else None
                    if m and int(m.group(1)) >= dc_first:
                        end.port = f"X{int(m.group(1)) + first - dc_first}"
        _add_dc_part(p, sb, groups, macros.get("dc_tech", ""), dc, first)
        _dc_from_below(p, sb)
        _apply_spd_component(sb, dc.get("spd_component"))
        _apply_component(sb, dc.get("fuse_component"), "fve.fuse_disconnect")
        whys = [why for fin, why in fuse_cache.values() if not fin]
        if whys:   # pojistky bez In jsou jen ze skupin, kde nic nevyhovělo
            _mark_unresolved(sb.elements, FUSE_SYMBOLS, "; ".join(dict.fromkeys(whys)))
    if chain is not None:
        _build_main_lv_board(p, p.create_switchboard_sheet(chain["hr"]), conn, ac, inverter_elements, blk.ref)
        if chain["rvn"] is not None:
            _build_mv_board(p, p.create_switchboard_sheet(chain["rvn"]), conn)
        _build_meter_board(p, p.create_switchboard_sheet(chain["re"]), conn)
    if combined:
        _align_route_boxes(p, blk, [[b for b, _g, _k, no, _r in dc_boxes if no == i + 1] for i in range(len(invs))])
    _align_bends(p)
    if combined:
        _route_house(p, blk, ac_wires, grid, earth)
    else:
        _align_outputs(p, blk, None if chain else grid, earth)
    if chain is not None:
        _align_connection(p, blk, chain)
    _place_jps(p, s, spec.get("jps") or {}, rows, ac_wires, blk)
    # až po rozmístění na list: vazby přívodů ukládají texty s polohou v JPS („W3 T1:DC1 /1.F3“); listy DC rozvaděčů,
    # které přetékají formát (DC rozvaděč s mnoha stringy po 50 mm), se zvětší – před vazbami (sloupce listu)
    # i po nich (delší texty vazeb)
    # i AC rozvaděč / rozvaděč FVE rodinného domu (DC část „U“ po `DC_U_PITCH`, mnoho střídačů)
    dc_sheets = [sh for sh in p.sheets if sh.parent_element_id in {b.id for b, *_ in dc_boxes} | {blk.id}]
    _grow_switchboards(p, dc_sheets)
    sync_feed_links(p)
    if _grow_switchboards(p, dc_sheets):
        sync_feed_links(p)
    sync_cables(p)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__)
        return 2
    spec = load_spec(argv[0])
    p = build_project(spec)
    p.save(argv[1])
    n_el = sum(len(s.elements) for s in p.sheets)
    print(f"{argv[1]}: {len(p.sheets)} listů, {n_el} prvků, {p.meta.get('p_installed_kwp')} kWp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
