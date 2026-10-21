"""Regresní snímek výstupu `build_project` (pomocný modul testů, bez Qt).

Snímek = `Project.to_dict()` s náhodnými id (12 hex znaků) nahrazenými pořadovými značkami `#1`, `#2`… podle prvního
výskytu, takže se porovnávají označení, atributy, polohy, vodiče, kabely i pořadí vzniku prvků.

Přegenerování (jen po vědomé změně generátoru):
    python -m tests.generate_snapshot
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SNAPSHOT = Path(__file__).parent / "data" / "generate_snapshot.json"

_NO_MACROS = {"dc_tech": "", "dc_route": "", "ac_feed": "", "ac_core": ""}   # rozvaděče vestavěným kódem
_INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}

CASES: dict[str, dict] = {
    # výchozí specifikace + jeden střídač (1 rozvaděč po trase + u technologie, AC rozvaděč z maker)
    "default_1inv": {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20, 18]}]},
    # dva střídače, jiný jistič
    "two_inv": {"name": "FVE Test", "meta": {"investor": "Test s.r.o."},
                "inverters": [{"ref": "T1", **_INV, "strings": [20, 20, 18]}, {"ref": "T2", **_INV, "strings": [20, 20]}],
                "ac": {"breaker_in": 50, "main_in": 125}},
    # dva rozvaděče po trase, jiné In pojistky a SPD, AC rozvod svorkami (kód místo maker)
    "route2_terminals": {"inverters": [{"ref": "T1", **_INV, "strings": [20, 18]}],
                         "dc": {"route_boxes": 2, "fuse_in": 20, "disconnect_in": 25, "spd": "T1+T2"},
                         "ac": {"distribution": "terminals", "spd": "T2"}},
    # střídač s artiklem: mppt/strings_per_mppt zadané, typ a p_dc_max nezadané (doplní artikl – viz test)
    "with_component": {"inverters": [{"ref": "T1", **_INV, "mppt": 3, "strings_per_mppt": 2, "strings": [20, 20, 18, 18],
                                      "component_id": "sma-stp-25-50"}]},
    # --- rozšíření pro refaktoring F1 (docs/design/topologie_f1_f2.md, kap. 1.3, krok 0) ---
    # firma, 9 střídačů z maker a kódem (parametrická sběrnice, víc než 6 přívodů)
    "company_9inv": {"inverters": [{"ref": f"T{i}", **_INV, "strings": [20, 18]} for i in range(1, 10)],
                     "jps": {"split": "none"}},
    "company_9inv_code": {"inverters": [{"ref": f"T{i}", **_INV, "strings": [20, 18]} for i in range(1, 10)],
                          "macros": _NO_MACROS, "jps": {"split": "none"}},
    # rodinný dům, 1 střídač kódem, hybrid + baterie
    "house_code_battery": {"building": "house", "macros": _NO_MACROS,
                           "inverters": [{"ref": "T1", **_INV, "strings": [16, 16]}],
                           "battery": {"e_kwh": 10, "p_kw": 5, "type": "BYD HVS 10.2"}},
    # rodinný dům, 2 a 3 střídače z maker, rozvaděč po trase
    "house_2inv": {"building": "house", "inverters": [{"ref": "T1", **_INV, "strings": [16, 16]},
                                                      {"ref": "T2", **_INV, "strings": [14]}]},
    "house_3inv": {"building": "rodinný dům", "dc": {"route_boxes": 1},
                   "inverters": [{"ref": f"T{i}", **_INV, "strings": [12, 12]} for i in range(1, 4)]},
    # bytový dům, optimizéry SolarEdge (artikl), 2 střídače
    "apartment_optimizer": {"building": "apartment", "optimizer": {"component_id": "solaredge-s440-1gm4mrm"},
                            "inverters": [{"ref": "T1", **_INV, "strings": [20, 20]},
                                          {"ref": "T2", **_INV, "strings": [18]}]},
    # přípojka VN: kiosk se smyčkou a měřením na nn, kobky s měřením na vn a vypínačem VN (1250 kVA), sloup
    "vn_kiosk_nn": {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}],
                    "connection": {"level": "vn", "station": "kiosk", "loop": True, "metering": "nn"}},
    "vn_kobky_vn_1250": {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]},
                                       {"ref": "T2", **_INV, "strings": [20]}],
                         "connection": {"level": "vn", "station": "kobky", "loop": False, "metering": "vn",
                                        "u_vn": "35 kV", "transformer": {"sn": 1250}}},
    "vn_sloup": {"inverters": [{"ref": "T1", **_INV, "strings": [20]}],
                 "connection": {"level": "vn", "station": "sloup", "transformer": {"sn": 250}}},
    # rozdělení JPS na listy (4 střídače × 8 stringů nad A2)
    "split_4x8": {"inverters": [{"ref": f"T{i}", **_INV, "strings": [20] * 8} for i in range(1, 5)],
                  "jps": {"split": "auto", "max_paper": "A2", "paper": "A2"}},
    # samostatný odpínač DC bez rozvaděčů (stará varianta)
    "dc_disconnect": {"inverters": [{"ref": "T1", **_INV, "strings": [20, 18]}],
                      "dc": {"route_boxes": 0, "tech_box": False, "disconnect": True}},
    # --- doplněno po review F1 (snímek rozšířen jen o tyto případy; dřívější beze změny) ---
    # rodinný dům jen AC (`dc.tech_box` false → RFVE „rozvaděč FVE (AC)“), rodinný dům s rozvodem svorkami
    "house_ac_only": {"building": "house", "dc": {"tech_box": False},
                      "inverters": [{"ref": "T1", **_INV, "strings": [16, 16]}]},
    "house_terminals": {"building": "house", "ac": {"distribution": "terminals"},
                        "inverters": [{"ref": "T1", **_INV, "strings": [16, 14]}]},
    # firma s baterií u hybridního střídače (kabel baterie z `BATTERY_CABLE`)
    "company_battery": {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}],
                        "battery": {"e_kwh": 15, "p_kw": 10, "type": "BYD HVS 15.4"}},
    # tři rozvaděče po trase
    "route_boxes3": {"inverters": [{"ref": "T1", **_INV, "strings": [20, 18]}], "dc": {"route_boxes": 3}},
    # neurčené In pojistek stringů (Isc modulu tak velký, že žádná gPV v držáku nevyhoví → `in_unresolved`)
    "fuse_in_unresolved": {"module": {"isc": 30, "i_fuse_max": 35},
                           "inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}]},
    # makra se sadou hodnot a hodnotami proměnných (`spec.macros` jako objekt)
    "macro_values": {"inverters": [{"ref": "T1", **_INV, "strings": [20, 18]},
                                   {"ref": "T2", **_INV, "strings": [20]}],
                     "macros": {"dc_tech": {"name": "DC string v rozvaděči", "value_set": "Pojistka 15 A gPV, SPD T2",
                                            "values": {"fuse_in": 12}},
                                "ac_feed": {"name": "AC přívod střídače", "values": {"breaker_in": 32}}}},
    # --- F2 (docs/design/topologie_f1_f2.md, kap. 2) ---
    # DC rozvaděč u technologie na střídač (`chain.rfve_dc.per_inverter`) – stav před F2 (výchozí je společný RFVE.DC)
    "two_inv_per_inverter": {"name": "FVE Test", "meta": {"investor": "Test s.r.o."}, "inverters": [{"ref": "T1", **_INV, "strings": [20, 20, 18]},
                                           {"ref": "T2", **_INV, "strings": [20, 20]}],
                             "ac": {"breaker_in": 50, "main_in": 125}, "chain": {"rfve_dc": {"per_inverter": True}}},
    # stávající články se zadanými In: nn s pojistkovým vývodem FVE nad 80 A a kabelem HR → RE, měření v HR,
    # rodinný dům s nepřímým měřením a hranicí za elektroměrem
    "nn_existing_fuse": {"inverters": [{"ref": f"T{i}", **_INV, "strings": [20, 20]} for i in (1, 2, 3, 4)],
                         "chain": {"hr": {"main_in": 400, "fve_device": "fuse_disconnect", "fve_in": 160,
                                          "cable": "AYKY-J 4x150", "length": 15},
                                   "re": {"main_in": 400, "metering": "indirect"}, "hds": {"in_": 500}}},
    "nn_hr_meter": {"topology": "nn_hr_meter", "inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}],
                    "chain": {"hr": {"main_in": 160, "boundary": "re_main"}, "hds": {"in_": 200}}},
    "house_existing": {"building": "house", "inverters": [{"ref": "T1", **_INV, "strings": [16, 16]}],
                       "chain": {"rd": {"main_in": 63}, "re": {"main_in": 63, "boundary": "re_meter"},
                                 "hds": {"in_": 80}}},
    # jednofázový střídač
    "inverter_1phase": {"inverters": [{"ref": "T1", "p_ac": 5, "phases": 1, "u_dc_max": 600, "u_mppt_min": 90,
                                       "u_mppt_max": 550, "i_mppt_max": 16, "strings": [12, 10]}]},
}

_ID = re.compile(r"\b[0-9a-f]{12}\b")


def canon(project) -> dict:
    text = json.dumps(project.to_dict(), ensure_ascii=False, sort_keys=False)
    ids: dict[str, str] = {}

    def rep(m: re.Match) -> str:
        return ids.setdefault(m.group(0), f"#{len(ids) + 1}")
    return json.loads(_ID.sub(rep, text))


def snapshot_all() -> dict:
    from envocad.generate import build_project
    return {name: canon(build_project(spec)) for name, spec in CASES.items()}


if __name__ == "__main__":
    import os
    import tempfile
    # jako testy (conftest `_isolated_home`): nastavení a knihovna uživatele snímek neovlivní
    os.environ["ENVOCAD_HOME"] = tempfile.mkdtemp(prefix="envohome-")
    SNAPSHOT.write_text(json.dumps(snapshot_all(), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(CASES)} případů → {SNAPSHOT}")
