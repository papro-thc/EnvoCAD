"""Nastavení programu a firemní standard (ENVO) – `~/.envocad/settings.json`. Bez Qt.

{
  "shared_library_dir": "\\\\server\\envocad\\knihovna",   // sdílená knihovna (JSON značky + CSV artikly), načítá se navíc
  "standard": {
    "author": "PR", "company": "ENVO s.r.o.",
    "dc_cable": "H1Z2Z2-K 1x6", "dc_cross": 6, "ac_cable": "CYKY-J 5x16", "ac_cross": 16,
    "preferred_manufacturers": ["OEZ", "Eaton", "Weidmüller"],
    "project_meta": {"author": "PR"}                      // předvyplní se do nového projektu
  }
}
"""
from __future__ import annotations

import json
from pathlib import Path

from envocad.library.store import home_dir

DEFAULTS = {
    "shared_library_dir": "",
    "frame": False,   # rámeček s popisovým polem a QR na listech (zatím vypnuto; Zobrazit → Rámeček a popisové pole)
    "standard": {
        "author": "", "company": "ENVO s.r.o.",
        "dc_cable": "H1Z2Z2-K 1x6", "dc_cross": 6, "ac_cable": "CYKY-J 5x16", "ac_cross": 16,
        "grid_cable": "CYKY-J 5x35", "grid_cross": 35,
        "preferred_manufacturers": ["OEZ", "Eaton", "Weidmüller", "SMA", "Huawei", "SolaX"],
        "project_meta": {},
    },
}


def settings_path() -> Path:
    return home_dir() / "settings.json"


def load_settings() -> dict:
    p = settings_path()
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    out = json.loads(json.dumps(DEFAULTS))
    out.update({k: v for k, v in data.items() if k != "standard"})
    out["standard"].update(data.get("standard", {}))
    return out


def save_settings(data: dict) -> None:
    settings_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def shared_library_dir() -> Path | None:
    d = load_settings().get("shared_library_dir") or ""
    if not d:
        return None
    p = Path(d)
    return p if p.is_dir() else None


def apply_standard_to_spec(spec: dict) -> dict:
    """Doplní do specifikace průvodce výchozí hodnoty firemního standardu (kabely, zpracoval)."""
    st = load_settings()["standard"]
    spec = dict(spec)
    meta = dict(st.get("project_meta") or {})
    if st.get("author"):
        meta.setdefault("author", st["author"])
    meta.update(spec.get("meta") or {})
    spec["meta"] = meta
    dc = {"cable": st.get("dc_cable"), "cross": st.get("dc_cross")}
    dc.update(spec.get("dc") or {})
    spec["dc"] = dc
    ac = {"cable": st.get("ac_cable"), "cross": st.get("ac_cross"), "grid_cable": st.get("grid_cable"),
          "grid_cross": st.get("grid_cross")}
    ac.update(spec.get("ac") or {})
    spec["ac"] = ac
    return spec
