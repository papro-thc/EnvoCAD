"""Nastavení programu a firemní standard (ENVO) – `~/.envocad/settings.json`. Bez Qt.

{
  "shared_library_dir": "\\\\server\\envocad\\knihovna",   // sdílená knihovna (JSON značky + CSV artikly), načítá se navíc
  "standard": {
    "author": "PR", "company": "ENVO s.r.o.",
    "dc_cable": "H1Z2Z2-K 1x6", "dc_cross": 6, "ac_cable": "CYKY-J 5x16", "ac_cross": 16,
    "switchboard_paper": "A4",                             // strany schématu rozvaděče: A4 / A4 na výšku / A3
    "jps_max_paper": "A2",                                 // největší list JPS z generátoru, větší se rozdělí na listy
    "doc_jps_page": "A3",                                  // listy JPS v PDF dokumentace: "A3" = zmenšit, "list" = skutečný formát
    "preferred_manufacturers": ["OEZ", "Eaton", "Weidmüller"],
    "pv_t_min": -20, "pv_t_max": 70,                       // návrhové teploty stringů [°C] pro průvodce
    "project_meta": {"author": "PR"}                      // předvyplní se do nového projektu
  }
}
"""
from __future__ import annotations

import getpass
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
        "jps_max_paper": "A2",       # větší JPS generátor rozdělí na listy tohoto formátu (AC list + listy střídačů)
        "doc_jps_page": "A3",        # listy JPS v PDF dokumentace: „A3“ = zmenšit na A3, „list“ = skutečný formát listu
        "switchboard_paper": "A4",   # strany schématu rozvaděče a plánu svorkovnice: „A4“, „A4 na výšku“, „A3“
        "preferred_manufacturers": ["OEZ", "Eaton", "Weidmüller", "SMA", "Huawei", "SolaX"],
        # návrhové teploty pro stringy [°C] – průvodce je předvyplní do `meta pv_t_min/pv_t_max` (model/calc.py)
        "pv_t_min": -20, "pv_t_max": 70,
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
            data = json.loads(p.read_text(encoding="utf-8-sig"))
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


def current_user() -> str:
    """Autor připomínek a revizí: `standard.author` z nastavení, jinak přihlašovací jméno uživatele OS."""
    author = str(load_settings()["standard"].get("author") or "").strip()
    if author:
        return author
    try:
        return getpass.getuser()
    except (OSError, KeyError, ImportError):   # bez proměnných prostředí a bez záznamu v passwd
        return ""


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
