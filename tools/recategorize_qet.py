"""Přepíše kategorie importovaných QET značek na druhy prvků (nadpisy v panelu knihovny).

Spustit: python tools/recategorize_qet.py
"""
from __future__ import annotations

import json
from pathlib import Path

from envocad.library.qet_import import kind_for_path

QET = Path(__file__).resolve().parents[1] / "envocad" / "library" / "builtin" / "qet"


def main() -> None:
    n = 0
    for f in sorted(QET.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        old = d.get("category", "")
        path = old.split("/", 1)[1] if "/" in old else old
        multipole = old.startswith("QET vícepól") or ".ap." in d["id"]
        d["category"] = f"{kind_for_path(path)}/QET"
        if multipole and not d["name"].endswith("[vícepól]"):
            d["name"] = d["name"] + " [vícepól]"
        f.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        n += 1
    print(f"{n} značek přepsáno")


if __name__ == "__main__":
    main()
