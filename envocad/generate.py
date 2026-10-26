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
         "system_v": "",                                              # soustava DC: "" = standard dc_system_v (1000 V, automaticky
                                                                      #  1500 V, když string > Un DC přístrojů a katalog má 2p odpojovač
                                                                      #  a svodič 1500 V); 1500 = DC přístroje 1500 V vždy
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
              "component_id": "solax-t-bat-h-5.8-v3", "modules": 3, "bms_id": "",   # nebo artikl baterie z katalogu
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
Artikl baterie (`battery.component_id`, `batteries.csv`, `library/batteries.py`) + `modules` (počet modulů věže, v mezích
`n_mod_min`/`n_mod_max` artiklu, jinak ValueError) doplní prázdné `type`, `e_kwh`, `p_kw` (jen když je datasheet uvádí),
`manufacturer`, `n_modules`, `slave_type` a `bms` (`bms_id` = řídicí jednotka); prvek baterie dostane `component_id`,
výkaz materiálu master/modul × n, slave a řídicí jednotku. Zadané hodnoty specifikace vyhrávají.
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
`site.ik_ka` [kA] (Ik v místě připojení) se zapíše do `meta["ik_ka"]` a do atributu `ik_ka` bloků HR / RE / RD /
RFVE.AC (jen když je zadáno; kontroly `ratings`).
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

# Tenký re-export: implementace je v balíčku `envocad/generator/` (refaktoring F1, docs/design/topologie_f1_f2.md,
# kap. 1.3; přehled v docs/ARCHITECTURE.md). Knihovnu generátoru drží `envocad.generator.context` (`_lib`, `_BUILD_LIB`)
# – testy ji patchují tam, ne tady (re-export by byl jen kopie). Logger zůstává "envocad.generate".
import sys
import types

from envocad.generator.boards.macro_glue import (
    UNRESOLVED_IN,
    _blank_unresolved,
    _feed_macro_from_below,
    _macro_ref,
    _macro_values,
)
from envocad.generator.boards.mv import (
    connection_currents,
    fve_feeder_in,
    inverters_ac_current,
    parse_voltage,
    voltage_label,
)
from envocad.generator.boards.rfve_ac import BUS_B_X, _ac_core_after_feeds
from envocad.generator.boards.rfve_dc import dc_box_ref
from envocad.generator.build import build_project
from envocad.generator.context import AC_MAX_INVERTERS_BUS, AC_SWITCHBOARD_REF, MAIN_LV_BOARD_REF, log
from envocad.generator.jps import JPS_AC_SHEET_NAME, ref_ranges
from envocad.generator.spec import (
    BUILDINGS,
    DEFAULT_SPEC,
    _apply_optimizer_component,
    _fuse_in,
    building_kind,
    fuse_in_why,
    holder_max_in,
    is_solaredge,
    load_spec,
    parse_number,
    parse_strings,
)

__all__ = [
    "AC_MAX_INVERTERS_BUS", "AC_SWITCHBOARD_REF", "BUILDINGS", "BUS_B_X", "DEFAULT_SPEC", "JPS_AC_SHEET_NAME",
    "MAIN_LV_BOARD_REF", "UNRESOLVED_IN", "_ac_core_after_feeds", "_apply_optimizer_component", "_blank_unresolved",
    "_feed_macro_from_below", "_fuse_in", "_macro_ref", "_macro_values", "build_project", "building_kind",
    "connection_currents", "dc_box_ref", "fuse_in_why", "fve_feeder_in", "holder_max_in", "inverters_ac_current",
    "is_solaredge", "load_spec", "log", "main", "parse_number", "parse_strings", "parse_voltage", "ref_ranges",
    "voltage_label",
]


# Jména, která `envocad.generate` měl před refaktoringem F1 (všechna top-level jména na commitu aaf9040, i soukromá
# a importovaná) a dnes jsou jinde: přístup přes `envocad.generate.<jméno>` je přesměruje na nové umístění
# s DeprecationWarning (`__getattr__`); zápis (`monkeypatch.setattr(generate, "_lib", …)`) jde do nového modulu
# (`_DeprecatedModule.__setattr__`) – kopie v `envocad.generate` by sestavení nijak neovlivnila.
_MOVED_BY_MODULE: dict[str, tuple[str, ...]] = {
    "envocad.generator.boards.macro_glue": ("FUSE_SYMBOLS", "_ac_box_from_macros", "_dc_box_from_macro",
        "_insert_macro", "_macro_vars",),
    "envocad.generator.boards.mv": ("CELL_NAMES", "CT_CONDUCTORS", "CT_PRIMARY_SIZES", "LV_BREAKER_SIZES",
        "LV_FEEDER_SIZES", "STATIONS", "U_LV", "U_MV_DEFAULT", "U_MV_RANGE", "VN_BREAKER_FROM_KVA", "VN_CONDUCTORS",
        "VN_FUSE_FACTOR", "VN_FUSE_SIZES", "VT_CONDUCTORS", "_VOLTAGE_RE", "_build_main_lv_board",
        "_build_meter_board", "_build_mv_board", "_connection_blocks", "_next_size", "station_kind", "station_label",),
    "envocad.generator.boards.rfve": ("DC_AC_GAP", "DC_PE_AROUND", "DC_PE_JOIN_DY", "DC_PE_Y", "DC_SPD_DX",
        "DC_SPD_Y", "DC_U_GAP", "DC_U_PITCH", "DC_U_TOP", "DC_U_WIDTH", "DC_U_X0", "_add_dc_part", "_dc_from_below",),
    "envocad.generator.boards.rfve_ac": ("AC_BUS_POS", "AC_CORE_GAP", "AC_FEED_X0", "AC_ROW_BOTTOM",
        "AC_ROW_DEVICES", "BUS_DROP_STEP", "BUS_OUTPUTS", "_ac_core_parametric", "_build_ac_switchboard",
        "_bus_b_ports_by_x", "_bus_drop_points", "_bus_out_x",),
    "envocad.generator.boards.rfve_dc": ("_apply_component", "_apply_spd_component", "_mark_unresolved",),
    "envocad.generator.build": ("_build_project",),
    "envocad.generator.context": ("BATTERY_CABLE", "BATTERY_ROW_EXTRA", "DC_ROUTE_BOX_PREFIX", "DC_TECH_BOX_REF",
        "INV_LABEL_SPACE", "_BUILD_LIB", "_int_attr", "_lib", "_merge", "_num", "_num_or", "_s",),
    "envocad.generator.jps": ("INTERRUPT_GAP_AC", "INTERRUPT_GAP_BLOCK", "INTERRUPT_GAP_INV", "JPS_AC_SUFFIX",
        "_place_jps", "_split_jps", "jps_max_paper",),
    "envocad.generator.layout": ("_align_bends", "_align_bends_sheet", "_align_connection", "_align_outputs",
        "_align_route_boxes", "_grow_switchboards", "_route_house",),
    "envocad.generator.spec": ("HOUSE_SWITCHBOARD", "HOUSE_SWITCHBOARD_AC", "INVERTER_MODE_KEYS",
        "MODULE_SPEC_FROM_ATTR", "_apply_inverter_component", "_apply_module_component", "_apply_optimizer_rules",
        "_modules_per_optimizer",),
    "envocad.library.templates": ("AC_CONDUCTORS", "DC_CONDUCTORS", "GROUP_PITCH", "_bridge_groups", "_el", "_feed",
        "_place_sequential", "_terminal_group", "_wire", "build_dc_strings",),
    "envocad.model.busbar": ("BusLayout", "OUTS_ATTR", "PITCH_ATTR", "TAPS_ATTR", "layout_of", "line_end",
        "line_span",),
    "envocad.model.calc": ("DC_INPUTS_PER_MPPT_DEFAULT", "InverterData", "string_ports",),
    "envocad.model.feed": ("FEED_SYMBOL", "is_feed_in", "is_feed_out",),
    "envocad.model.project": ("Element", "PORT_PITCH", "Project", "Sheet", "Wire", "WireEnd", "element_symbol",
        "sync_cables", "sync_feed_links",),
}
_MOVED: dict[str, str] = {name: mod for mod, names in _MOVED_BY_MODULE.items() for name in names}


def _moved_module(name: str):
    import importlib
    import warnings
    target = _MOVED[name]
    warnings.warn(f"envocad.generate.{name} je přesunuto do {target}.{name} – importujte ho odtud "
                  "(envocad.generate je jen re-export veřejného API).", DeprecationWarning, stacklevel=3)
    return importlib.import_module(target)


def __getattr__(name: str):
    if name in _MOVED:
        return getattr(_moved_module(name), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *_MOVED})


class _DeprecatedModule(types.ModuleType):
    """Zápis přesunutého jména (`generate._lib = …`, `monkeypatch.setattr`) jde do nového modulu s varováním."""

    def __setattr__(self, name: str, value) -> None:
        if name in _MOVED and name not in self.__dict__:
            setattr(_moved_module(name), name, value)
            return
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _DeprecatedModule


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
