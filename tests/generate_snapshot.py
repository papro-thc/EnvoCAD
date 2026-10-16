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
    SNAPSHOT.write_text(json.dumps(snapshot_all(), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(CASES)} případů → {SNAPSHOT}")
