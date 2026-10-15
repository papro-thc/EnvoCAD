"""Makra: pojmenované sestavy prvků a vodičů (výřez listu) k opakovanému vkládání. Bez Qt.

Makro = JSON {"name", "description", "fragment": {"elements": […], "wires": […]}} (formát jako schránka `copy_fragment`).
Odkud se načítají (v tomto pořadí, stejné jméno přepíše): vestavěná (`builtin/macros/`), sdílená knihovna
(`<shared_library_dir>/macros/`), uživatelská (`~/.envocad/macros/`). Ukládá se do uživatelské nebo sdílené složky.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

BUILTIN_DIR = Path(__file__).parent / "builtin" / "macros"


@dataclass
class Macro:
    name: str
    description: str
    fragment: dict
    path: Path
    source: str   # "vestavěné" | "sdílené" | "vlastní"

    @property
    def size(self) -> int:
        return len(self.fragment.get("elements", []))


def user_dir() -> Path:
    from envocad.settings import settings_path
    return settings_path().parent / "macros"


def shared_dir() -> Path | None:
    try:
        from envocad.settings import shared_library_dir
        d = shared_library_dir()
    except Exception:  # noqa: BLE001
        return None
    return (Path(d) / "macros") if d else None


def macro_dirs() -> list[tuple[Path, str]]:
    out = [(BUILTIN_DIR, "vestavěné")]
    sd = shared_dir()
    if sd:
        out.append((sd, "sdílené"))
    out.append((user_dir(), "vlastní"))
    return out


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", name.strip(), flags=re.UNICODE).strip("_")
    return s or "makro"


def list_macros() -> list[Macro]:
    found: dict[str, Macro] = {}
    for d, source in macro_dirs():
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict) or "fragment" not in data:
                continue
            name = data.get("name") or p.stem
            found[name] = Macro(name, data.get("description", ""), data["fragment"], p, source)
    return sorted(found.values(), key=lambda m: (m.source != "vestavěné", m.name.lower()))


def save_macro(name: str, description: str, fragment: dict, shared: bool = False) -> Path:
    d = (shared_dir() if shared else None) or user_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{_slug(name)}.json"
    p.write_text(json.dumps({"name": name, "description": description, "fragment": fragment}, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return p


def delete_macro(m: Macro) -> bool:
    if m.source == "vestavěné":
        return False
    try:
        m.path.unlink()
    except OSError:
        return False
    return True


def fragment_bounds(fragment: dict) -> tuple[float, float, float, float]:
    xs = [e["x"] for e in fragment.get("elements", [])]
    ys = [e["y"] for e in fragment.get("elements", [])]
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))
