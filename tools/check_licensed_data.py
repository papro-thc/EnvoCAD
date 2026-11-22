"""Pojistka: do gitu nesmí jít licencovaná data výrobců (EPLAN Data Portal, PDF datasheety, katalogy).

Kontroluje soubory sledované gitem (`git ls-files`), tedy i to, co přináší PR. Spouští CI i agenti před odevzdáním:

    python tools/check_licensed_data.py

Pravidla viz CLAUDE.md, kapitola „Licencovaná data“. Výjimku (např. vlastní PDF dokumentace) přidej
do ALLOWED_PATHS i s důvodem – výjimky schvaluje člověk v review.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath

# přípony balíčků EPLAN / dokumentů výrobců
FORBIDDEN_SUFFIXES = {
    ".edz": "balíček EPLAN Data Portal",
    ".ema": "makro EPLAN",
    ".epdz": "projekt EPLAN",
    ".e3d": "3D data EPLAN",
    ".pdf": "PDF (datasheet / katalog výrobce)",
    ".zip": "archiv (typicky stažená data výrobce)",
    ".7z": "archiv",
    ".step": "3D model výrobce",
    ".stp": "3D model výrobce",
    ".ecpz": "archiv projektu EnvoCAD (může obsahovat data výrobců)",
}
# složky s lokálními podklady (jsou i v .gitignore)
FORBIDDEN_DIRS = ("EPLAN/", "katalogy/", "datasheets/", "_sync/")
# značky surového exportu z EPLAN Data Portalu v datech knihovny
DATA_MARKERS = ("P_ARTICLE_", "dataportal.eplan", "ePulse")
DATA_DIR, DATA_SUFFIXES = "envocad/library/builtin/", {".csv", ".json"}
MAX_BYTES = 5 * 1024 * 1024  # větší soubor je skoro jistě stažený podklad, ne náš zdroj

ALLOWED_PATHS: dict[str, str] = {
    # "cesta/k/souboru.pdf": "důvod výjimky",
}


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True, stdin=subprocess.DEVNULL)
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def problems(paths: list[str]) -> list[str]:
    found: list[str] = []
    for path in paths:
        if path in ALLOWED_PATHS:
            continue
        p = PurePosixPath(path)
        reason = FORBIDDEN_SUFFIXES.get(p.suffix.lower())
        if reason:
            found.append(f"{path}: {reason}")
            continue
        if any(path.startswith(d) or f"/{d}" in path for d in FORBIDDEN_DIRS):
            found.append(f"{path}: složka s lokálními podklady výrobců")
            continue
        try:
            with open(path, "rb") as fh:
                data = fh.read(MAX_BYTES + 1)
        except OSError:
            continue  # smazaný soubor v pracovní kopii
        if len(data) > MAX_BYTES:
            found.append(f"{path}: větší než {MAX_BYTES // 1024 // 1024} MB")
            continue
        if path.startswith(DATA_DIR) and p.suffix.lower() in DATA_SUFFIXES:
            text = data.decode("utf-8", errors="ignore")
            for marker in DATA_MARKERS:
                if marker in text:
                    found.append(f"{path}: obsahuje „{marker}“ (surový export EPLAN Data Portalu?)")
                    break
    return found


def main() -> int:
    found = problems(tracked_files())
    if found:
        print("Licencovaná data výrobců v gitu (viz CLAUDE.md → Licencovaná data):")
        for line in found:
            print(f"  - {line}")
        return 1
    print("OK: žádná licencovaná data výrobců")
    return 0


if __name__ == "__main__":
    sys.exit(main())
