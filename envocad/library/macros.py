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


# ---------------------------------------------------------------------------------------------------------------
# Parametrická makra pro generátor: `{proměnná}` v atributech, označeních a portech se dosadí při vložení;
# prvek s atributem `shared` = "1" (sběrnice, vývod XPE…) se vloží jen jednou – další instance se na něj napojí.
class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _subst(text: str, vars_: dict) -> str:
    try:
        return str(text).format_map(_Safe(vars_))
    except (ValueError, IndexError):
        return str(text)


def instantiate(project, sheet, fragment: dict, vars_: dict, dx: float = 0.0, dy: float = 0.0,
                ref_prefix_of=None) -> tuple[list, list]:
    """Vloží parametrické makro do listu: dosadí `{proměnné}` (atributy, označení, porty vodičů), prvky s `shared`
    sloučí s už existujícím prvkem stejného označení na listu, ostatní označení bez proměnných přečísluje
    (F1 → další volné). Vrací (nové prvky, nové vodiče) – už vložené do listu."""
    from envocad.model.project import Element, Wire, WireEnd
    used = project.used_refs(sheet)
    idmap: dict[str, str] = {}
    els: list[Element] = []
    for d in fragment.get("elements", []):
        src = Element.from_dict(d)
        attrs = {k: _subst(v, vars_) for k, v in src.attrs.items()}
        shared = str(src.attrs.get("shared", "")).strip() in ("1", "true", "ano")
        if shared:
            ref = attrs.get("ref", "")
            existing = next((e for e in sheet.elements if e.symbol_id == src.symbol_id and e.ref == ref and ref), None)
            if existing is not None:
                idmap[src.id] = existing.id
                continue
        new = Element(symbol_id=src.symbol_id, x=src.x + dx, y=src.y + dy, rotation=src.rotation, attrs=attrs,
                      component_id=src.component_id)
        prefix = ref_prefix_of(src.symbol_id) if ref_prefix_of else ""
        if "{" not in str(src.attrs.get("ref", "")) and src.attrs.get("ref") and prefix and not shared \
                and src.symbol_id not in ("sb.terminal_block", "fve.terminal", "sb.feed_in", "sb.feed_out", "sb.busbar"):
            n = 1
            while f"{prefix}{n}" in used:
                n += 1
            new.attrs["ref"] = f"{prefix}{n}"
        used.add(new.attrs.get("ref", ""))
        new.attrs.pop("sheet", None)
        idmap[src.id] = new.id
        sheet.elements.append(new)
        els.append(new)
    wires: list[Wire] = []
    for d in fragment.get("wires", []):
        w = Wire.from_dict(d)
        if w.a.element_id not in idmap or w.b.element_id not in idmap:
            continue
        nw = Wire(WireEnd(idmap[w.a.element_id], _subst(w.a.port, vars_)), WireEnd(idmap[w.b.element_id], _subst(w.b.port, vars_)),
                  points=[(x + dx, y + dy) for x, y in w.points], attrs={k: _subst(v, vars_) for k, v in w.attrs.items()},
                  conductors=list(w.conductors))
        if nw.attrs.get("ref") and "{" not in str(w.attrs.get("ref", "")):
            n = 1
            while f"W{n}" in used:
                n += 1
            nw.attrs["ref"] = f"W{n}"
            used.add(nw.attrs["ref"])
        sheet.wires.append(nw)
        wires.append(nw)
    return els, wires


def find_macro(name: str) -> Macro | None:
    return next((m for m in list_macros() if m.name == name), None)


def macro_pitch(m: Macro) -> float:
    """Rozteč opakovaných instancí: atribut `pitch` makra, jinak šířka + 10 mm."""
    try:
        return float(m.fragment.get("pitch") or 0) or (fragment_bounds(m.fragment)[2] - fragment_bounds(m.fragment)[0] + 10.0)
    except (TypeError, ValueError):
        return fragment_bounds(m.fragment)[2] - fragment_bounds(m.fragment)[0] + 10.0
