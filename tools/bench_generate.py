"""Benchmark generátoru projektu (`build_project`) – nespouští se v pytestu.

    python tools/bench_generate.py              # tabulka časů (nejlepší z N opakování), N = 3
    python tools/bench_generate.py -n 5 -k rd   # jen případy obsahující „rd“
    python tools/bench_generate.py --profile firma_8inv   # cProfile jednoho případu (top 30 podle cumtime)

Sada: firma 1/2/4/8 střídačů, RD 1/3 střídače, přípojka VN (kiosk), rozdělené JPS 4×8 stringů. Skript jde spustit i nad
starší verzí repozitáře (spustit z kořene jeho worktree; potřebuje jen `envocad.generate.build_project`) – reference.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


def _invs(n: int, strings: list[int]) -> list[dict]:
    return [{"ref": f"T{i}", **INV, "strings": list(strings)} for i in range(1, n + 1)]


CASES: dict[str, dict] = {
    "firma_1inv": {"inverters": _invs(1, [20, 20, 18])},
    "firma_2inv": {"inverters": _invs(2, [20, 20, 18])},
    "firma_4inv": {"inverters": _invs(4, [20, 20, 18])},
    "firma_8inv": {"inverters": _invs(8, [20, 18])},
    "rd_1inv": {"building": "house", "inverters": _invs(1, [16, 16])},
    "rd_3inv": {"building": "house", "inverters": _invs(3, [12, 12])},
    "vn_kiosk": {"inverters": _invs(1, [20, 20]),
                 "connection": {"level": "vn", "station": "kiosk", "loop": True, "metering": "nn"}},
    "split_4x8": {"inverters": _invs(4, [20] * 8), "jps": {"split": "auto", "max_paper": "A2", "paper": "A2"}},
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-n", type=int, default=3, help="počet opakování (bere se nejlepší čas)")
    ap.add_argument("-k", default="", help="jen případy, jejichž název obsahuje text")
    ap.add_argument("--profile", metavar="CASE", help="cProfile jednoho případu")
    args = ap.parse_args(argv)
    # jako testy: nastavení a knihovna uživatele výsledek neovlivní
    os.environ["ENVOCAD_HOME"] = tempfile.mkdtemp(prefix="envohome-bench-")
    sys.path.insert(0, str(Path.cwd()))               # repozitář = aktuální adresář (i starší worktree)
    from envocad.generate import build_project
    build_project(CASES["firma_1inv"])          # zahřátí (importy, knihovna symbolů)
    if args.profile:
        import cProfile
        import pstats
        pr = cProfile.Profile()
        pr.enable()
        build_project(CASES[args.profile])
        pr.disable()
        pstats.Stats(pr).sort_stats("cumulative").print_stats(30)
        return 0
    total = 0.0
    print(f"{'případ':<14}{'čas [s]':>10}")
    for name, spec in CASES.items():
        if args.k not in name:
            continue
        best = min(_timed(build_project, spec) for _ in range(max(1, args.n)))
        total += best
        print(f"{name:<14}{best:>10.3f}")
    print(f"{'celkem':<14}{total:>10.3f}")
    return 0


def _timed(fn, spec: dict) -> float:
    t = time.perf_counter()
    fn(spec)
    return time.perf_counter() - t


if __name__ == "__main__":
    raise SystemExit(main())
