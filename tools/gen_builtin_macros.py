"""Vestavěná makra (sestavy) → envocad/library/builtin/macros/*.json. Spustit po změně šablon."""
from __future__ import annotations

import json
from pathlib import Path

from envocad.library.templates import AC_CONDUCTORS, DC_CONDUCTORS, GROUP_PITCH, _el, _terminal_group, _wire
from envocad.model.project import Project, Sheet, copy_fragment

OUT = Path(__file__).resolve().parent.parent / "envocad" / "library" / "builtin" / "macros"


def ac_outlet() -> dict:
    """AC vývod: skupina rozvodných svorek → jistič → vývod."""
    p, s = Project(), Sheet(kind="switchboard")
    grp = _terminal_group(p, s, 60, 200, "X2", 1, len(AC_CONDUCTORS), "vývod")
    f = _el(p, s, "fve.breaker_mcb", 60, 170, "F", rot=270, in_="16", char="B", poles="3", modules="3")
    out = _el(p, s, "sb.feed_out", 60, 140, "", desc="vývod")
    out.attrs["ref"] = "X3"
    _wire(p, s, grp, "2", f, "1", AC_CONDUCTORS)
    _wire(p, s, f, "2", out, "1", AC_CONDUCTORS)
    return copy_fragment(s, [e.id for e in s.elements])


def dc_string_in() -> dict:
    """DC string v rozvaděči: přívod → pojistkový odpínač → vývod + SPD na string."""
    p, s = Project(), Sheet(kind="switchboard")
    feed = _el(p, s, "sb.feed_in", 60, 240, "", desc="od stringu")
    feed.attrs["ref"] = "X1"
    d = _el(p, s, "fve.fuse_disconnect", 60, 210, "F", rot=270, in_="15", char="gPV", un="1000", poles="2", modules="2")
    out = _el(p, s, "sb.feed_out", 60, 170, "", desc="dál")
    out.attrs["ref"] = "X2"
    spd = _el(p, s, "fve.spd", 72.5, 180, "F", spd_type="T2 DC", uc="1000", poles="3", modules="3")
    _wire(p, s, feed, "1", d, "1", DC_CONDUCTORS)
    _wire(p, s, d, "2", out, "1", DC_CONDUCTORS)
    _wire(p, s, d, "2", spd, "L", DC_CONDUCTORS)
    return copy_fragment(s, [e.id for e in s.elements])


def jps_string_chain() -> dict:
    """JPS: FV string → DC rozvaděč (blok) → střídač, s kabely."""
    p, s = Project(), Sheet()
    g = _el(p, s, "fve.pv_string", 40, 200, "G", n_modules="20", p_module="450", p_string="9 kWp")
    t = _el(p, s, "fve.inverter", 40 + 2 * GROUP_PITCH + 60, 200, "T", p_ac="25", phases="3", mppt="2", strings_per_mppt="2")
    _wire(p, s, g, "DC", t, "DC1", DC_CONDUCTORS, ref="W1", cable="H1Z2Z2-K 1x6", cross="6", length="30", method="E")
    return copy_fragment(s, [e.id for e in s.elements])


MACROS = [
    ("AC vývod s jističem", "Skupina rozvodných svorek X2 → jistič 3p → vývod X3 (rozvaděč)", ac_outlet),
    ("DC string v rozvaděči", "Přívod X1 → pojistkový odpínač gPV → vývod X2, SPD T2 DC na string (rozvaděč)", dc_string_in),
    ("String → střídač", "FV string s kabelem H1Z2Z2-K na DC vstup střídače (JPS)", jps_string_chain),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, desc, fn in MACROS:
        slug = name.lower().replace(" → ", "_").replace(" ", "_").replace("í", "i").replace("č", "c").replace("ř", "r").replace("ě", "e").replace("ý", "y")
        (OUT / f"{slug}.json").write_text(json.dumps({"name": name, "description": desc, "fragment": fn()}, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    print(f"{len(MACROS)} maker → {OUT}")


if __name__ == "__main__":
    main()
