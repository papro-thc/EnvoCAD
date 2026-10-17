"""Makra: pojmenované sestavy prvků a vodičů (výřez listu) k opakovanému vkládání. Bez Qt.

Makro = JSON {"version", "name", "description", "role", "variables", "value_sets", "repeat", "fragment"}; fragment má
formát schránky `copy_fragment` ({"elements": […], "wires": […], "pitch"}). Formát v2 popisuje `docs/LIBRARY_FORMAT.md`
(sekce „Formát makra“), návrh `docs/design/makra_promenne.md`. Makro v1 (bez `version`) platí beze změny – jeho
proměnné se odvodí ze zástupných symbolů `{x}` ve fragmentu.

Odkud se načítají (v tomto pořadí, stejné jméno přepíše): vestavěná (`builtin/macros/`), sdílená knihovna
(`<shared_library_dir>/macros/`), uživatelská (`~/.envocad/macros/`). Ukládá se do uživatelské nebo sdílené složky.

Vložení makra do listu: `resolve_values` (hodnoty proměnných) → `expand` (nové prvky a vodiče, list se NEMĚNÍ – GUI je
vloží jedním undo příkazem) → případně `insert`. `instantiate` = `expand` + `insert` (generátor).
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("envocad.library")

BUILTIN_DIR = Path(__file__).parent / "builtin" / "macros"

MACRO_VERSION = 2
RESERVED = frozenset({"k", "n", "nk", "i", "j", "string", "inverter"})   # kontext dodává generátor / opakování
MAX_REPEAT = 100
# kontextové názvy, které dosazuje opakování makra v každé iteraci (n = počet – to se zadává, viz `repeat_context_names`)
REPEAT_CONTEXT = frozenset({"k", "n", "nk"})
VAR_TYPES = ("text", "number", "choice", "component")
FALSE_VALUES = frozenset({"", "0", "ne", "no", "false", "off"})

_PH = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WHEN = re.compile(r"^\s*(!?)\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:(!?=)(.*))?$")
# prvky, kterým se při vložení nepřečíslovává označení (svorkovnice, přívody/vývody, sběrnice)
_KEEP_REF = ("sb.terminal_block", "fve.terminal", "sb.feed_in", "sb.feed_out", "sb.busbar")
_TERMINAL_SYMBOLS = ("sb.terminal_block", "fve.terminal")
_FEED_SYMBOLS = ("sb.feed_in", "sb.feed_out")


# ---------------------------------------------------------------------------------------------------------------
# zástupné symboly
def subst(text, values: dict) -> str:
    """Dosadí `{x}` z `values` (hodnoty převede na řetězec). Neznámé `{x}`, `{}`, `{0}`, `{a.b}`, `{x:>3}` nechá beze
    změny – žádné vyhodnocování výrazů ani formátovací specifikace."""
    s = str(text)
    if "{" not in s:
        return s
    return _PH.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), s)


def _placeholders_in(text) -> set[str]:
    return set(_PH.findall(str(text))) if text is not None else set()


def placeholders(fragment: dict) -> set[str]:
    """Názvy všech `{x}` ve fragmentu: atributy a artikl (`component_id`) prvků, atributy a porty vodičů."""
    out: set[str] = set()
    for d in fragment.get("elements", []) or []:
        for v in (d.get("attrs") or {}).values():
            out |= _placeholders_in(v)
        out |= _placeholders_in(d.get("component_id"))
    for d in fragment.get("wires", []) or []:
        for v in (d.get("attrs") or {}).values():
            out |= _placeholders_in(v)
        for end in ("a", "b"):
            out |= _placeholders_in((d.get(end) or {}).get("port"))
    return out


# ---------------------------------------------------------------------------------------------------------------
# datové třídy
@dataclass(frozen=True)
class MacroVar:
    name: str
    label: str = ""
    type: str = "text"            # text | number | choice | component
    default: str = ""
    unit: str = ""
    help: str = ""
    required: bool = False
    choices: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None
    category: str = ""            # u type=component: kategorie artiklu
    source: str = ""              # JSON "from": "<proměnná component>.<parametr artiklu>"
    auto: bool = False            # dodává volající (generátor, opakování); v GUI sbalené pod „Další“
    implicit: bool = False        # odvozená ze zástupného symbolu (makro bez deklarací)

    @property
    def title(self) -> str:
        return self.label or self.name

    def to_dict(self) -> dict:
        d: dict = {"name": self.name}
        if self.label:
            d["label"] = self.label
        if self.type != "text":
            d["type"] = self.type
        for key in ("default", "unit", "help", "category"):
            if getattr(self, key):
                d[key] = getattr(self, key)
        if self.source:
            d["from"] = self.source
        if self.required:
            d["required"] = True
        if self.choices:
            d["choices"] = list(self.choices)
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.auto:
            d["auto"] = True
        return d

    @classmethod
    def from_dict(cls, d: dict) -> MacroVar:
        def num(v):
            try:
                return None if v in (None, "") else float(v)
            except (TypeError, ValueError):
                return None
        return cls(name=str(d.get("name", "")), label=str(d.get("label", "") or ""), type=str(d.get("type") or "text"),
                   default=_str(d.get("default")), unit=str(d.get("unit", "") or ""), help=str(d.get("help", "") or ""),
                   required=bool(d.get("required", False)), choices=tuple(_str(c) for c in d.get("choices") or ()),
                   min=num(d.get("min")), max=num(d.get("max")), category=str(d.get("category", "") or ""),
                   source=str(d.get("from", "") or ""), auto=bool(d.get("auto", False)))


@dataclass(frozen=True)
class ValueSet:
    name: str
    values: dict[str, str]
    description: str = ""

    def to_dict(self) -> dict:
        d = {"name": self.name, "values": dict(self.values)}
        if self.description:
            d["description"] = self.description
        return d


@dataclass(frozen=True)
class Repeat:
    count: str                    # název proměnné s počtem opakování
    pitch: float | None = None    # rozteč v mm (bez ní rozteč makra – `macro_pitch`)


@dataclass
class Macro:
    name: str
    description: str
    fragment: dict
    path: Path
    source: str   # "vestavěné" | "sdílené" | "vlastní"
    version: int = 1
    variables: list[MacroVar] = field(default_factory=list)
    value_sets: list[ValueSet] = field(default_factory=list)
    repeat: Repeat | None = None
    role: str = ""                # dc_tech | dc_route | ac_feed | ac_core | "" – role v generátoru

    @property
    def size(self) -> int:
        return len(self.fragment.get("elements", []))

    @property
    def has_parameters(self) -> bool:
        """Má proměnné nebo opakování → GUI před vložením ukáže dialog hodnot; jinak se vkládá jako výřez."""
        return bool(self.variables or self.repeat)

    def variable(self, name: str) -> MacroVar | None:
        return next((v for v in self.variables if v.name == name), None)

    def value_set(self, name: str) -> ValueSet | None:
        return next((v for v in self.value_sets if v.name == name), None)


def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def implicit_variables(fragment: dict) -> list[MacroVar]:
    """Proměnné makra bez deklarací: textová proměnná za každý `{x}` (rezervované názvy jako `auto`)."""
    return [MacroVar(name=n, auto=n in RESERVED, implicit=True) for n in sorted(placeholders(fragment))]


# ---------------------------------------------------------------------------------------------------------------
# načtení, uložení, kontrola
def parse_macro(data: dict, path: Path | str | None = None, source: str = "vlastní") -> Macro:
    """Makro z JSON dat (v1 i v2). ValueError, pokud data nejsou makro (chybí fragment). Ostatní nesrovnalosti
    snáší (neplatné položky vynechá) – podrobnou kontrolu dělá `validate_macro`."""
    fragment = data.get("fragment") if isinstance(data, dict) else None
    if not isinstance(fragment, dict):
        raise ValueError("Makro musí být objekt JSON s klíčem „fragment“.")  # noqa: TRY004 – neplatná data, ne typ
    path = Path(path) if path else Path()
    try:
        version = int(data.get("version") or 1)
    except (TypeError, ValueError):
        raise ValueError(f"Neplatná verze makra: {data.get('version')!r}") from None
    if isinstance(data.get("variables"), list):
        variables = [MacroVar.from_dict(v) for v in data["variables"] if isinstance(v, dict) and v.get("name")]
    else:
        variables = implicit_variables(fragment)
    value_sets = [ValueSet(str(vs.get("name", "")), {str(k): _str(v) for k, v in (vs.get("values") or {}).items()},
                           str(vs.get("description", "") or ""))
                  for vs in data.get("value_sets") or [] if isinstance(vs, dict) and vs.get("name")]
    rep = data.get("repeat")
    repeat = None
    if isinstance(rep, dict) and rep.get("count"):
        try:
            pitch = float(rep["pitch"]) if rep.get("pitch") not in (None, "") else None
        except (TypeError, ValueError):
            pitch = None
        repeat = Repeat(str(rep["count"]), pitch)
    return Macro(name=str(data.get("name") or path.stem), description=str(data.get("description", "") or ""),
                 fragment=fragment, path=path, source=source, version=version, variables=variables,
                 value_sets=value_sets, repeat=repeat, role=str(data.get("role", "") or ""))


def load_macro(path: Path | str, source: str = "vlastní") -> Macro | None:
    """Načte makro ze souboru. Nečitelné, neplatné nebo vyšší verze (`version` > MACRO_VERSION) → None + záznam v logu."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as ex:
        log.warning("Makro %s nelze načíst: %s", path, ex)
        return None
    if isinstance(data, dict):
        try:
            ver = int(data.get("version") or 1)
        except (TypeError, ValueError):
            ver = 0
        if ver > MACRO_VERSION:
            log.warning("Makro %s má verzi %s, program umí nejvýše %s – přeskočeno", path, ver, MACRO_VERSION)
            return None
    try:
        return parse_macro(data, path, source)
    except ValueError as ex:
        log.warning("Makro %s je neplatné: %s", path, ex)
        return None


def _is_number(v) -> bool:
    if isinstance(v, bool):
        return False
    try:
        float(v)
    except (TypeError, ValueError):
        return False
    return True


def validate_macro(data: dict) -> list[str]:
    """Kontrola JSON makra; vrací seznam chyb česky (prázdný = v pořádku)."""
    if not isinstance(data, dict):
        return ["Makro není objekt JSON."]
    errs: list[str] = []
    ver = data.get("version", 1)
    if not isinstance(ver, int) or isinstance(ver, bool) or not 1 <= ver <= MACRO_VERSION:
        errs.append(f"Neplatná verze makra {ver!r} (podporováno 1–{MACRO_VERSION}).")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        errs.append("Chybí název makra („name“).")
    frag = data.get("fragment")
    if not isinstance(frag, dict):
        return errs + ["Chybí fragment makra („fragment“)."]
    els, wires = frag.get("elements", []), frag.get("wires", [])
    if not isinstance(els, list) or not isinstance(wires, list):
        return errs + ["Fragment musí mít seznamy „elements“ a „wires“."]
    if "role" in data and not isinstance(data["role"], str):
        errs.append("Role makra musí být text.")
    # proměnné
    declared: dict[str, dict] = {}
    if "variables" in data:
        if not isinstance(data["variables"], list):
            errs.append("„variables“ musí být seznam.")
        else:
            for v in data["variables"]:
                if not isinstance(v, dict):
                    errs.append("Proměnná musí být objekt.")
                    continue
                name = v.get("name")
                if not isinstance(name, str) or not _NAME.match(name):
                    errs.append(f"Neplatný název proměnné {name!r} (písmena bez diakritiky, číslice, _).")
                    continue
                if name in declared:
                    errs.append(f"Proměnná „{name}“ je deklarovaná dvakrát.")
                declared[name] = v
                typ = v.get("type", "text")
                if typ not in VAR_TYPES:
                    errs.append(f"Proměnná „{name}“: neznámý typ {typ!r} (povolené: {', '.join(VAR_TYPES)}).")
                if "default" in v and not isinstance(v["default"], (str, int, float)):
                    errs.append(f"Proměnná „{name}“: výchozí hodnota musí být text.")
                if typ == "choice":
                    ch = v.get("choices")
                    if not isinstance(ch, list) or not ch or not all(isinstance(c, str) for c in ch):
                        errs.append(f"Proměnná „{name}“ typu choice potřebuje neprázdný seznam „choices“.")
                if typ == "component" and not v.get("category"):
                    errs.append(f"Proměnná „{name}“ typu component potřebuje „category“.")
                for key in ("min", "max"):
                    if v.get(key) is not None and not _is_number(v[key]):
                        errs.append(f"Proměnná „{name}“: „{key}“ musí být číslo.")
            for name, v in declared.items():
                src = v.get("from")
                if not src:
                    continue
                comp, _, param = str(src).partition(".")
                if not param or declared.get(comp, {}).get("type") != "component":
                    errs.append(f"Proměnná „{name}“: „from“ musí mít tvar „<proměnná typu component>.<parametr>“.")
    known = set(declared) | RESERVED
    # sady hodnot
    vs_names: set[str] = set()
    for vs in data.get("value_sets", []) or []:
        if not isinstance(vs, dict) or not isinstance(vs.get("name"), str) or not vs["name"].strip():
            errs.append("Sada hodnot musí mít název.")
            continue
        if vs["name"] in vs_names:
            errs.append(f"Sada hodnot „{vs['name']}“ je dvakrát.")
        vs_names.add(vs["name"])
        vals = vs.get("values")
        if not isinstance(vals, dict):
            errs.append(f"Sada hodnot „{vs['name']}“: „values“ musí být objekt.")
            continue
        if declared:
            for k in vals:
                if k not in declared:
                    errs.append(f"Sada hodnot „{vs['name']}“: neznámá proměnná „{k}“.")
    # opakování
    rep = data.get("repeat")
    if rep is not None:
        if not isinstance(rep, dict) or not isinstance(rep.get("count"), str):
            errs.append("„repeat“ musí být objekt s „count“ (název proměnné).")
        else:
            if declared and rep["count"] not in declared:
                errs.append(f"Opakování: proměnná počtu „{rep['count']}“ není deklarovaná.")
            cmax = declared.get(rep["count"], {}).get("max")
            if cmax is not None and _is_number(cmax) and float(cmax) > MAX_REPEAT:
                errs.append(f"Opakování: „max“ proměnné počtu „{rep['count']}“ ({_str(cmax)}) je větší než {MAX_REPEAT}.")
            if rep.get("pitch") is not None and (not _is_number(rep["pitch"]) or float(rep["pitch"]) <= 0):
                errs.append("Opakování: „pitch“ musí být kladné číslo.")
    # fragment: podmínky, odkazy vodičů, nedeklarované zástupné symboly
    ids = set()
    for d in els:
        if not isinstance(d, dict) or "symbol_id" not in d or "id" not in d:
            errs.append("Prvek fragmentu musí mít „id“ a „symbol_id“.")
            continue
        ids.add(d["id"])
    for kind, items in (("prvek", els), ("vodič", wires)):
        for d in items:
            if not isinstance(d, dict):
                continue
            when = (d.get("attrs") or {}).get("when")
            if when is None:
                continue
            mt = _WHEN.match(str(when))
            if not mt:
                errs.append(f"Podmínka „{when}“ ({kind}) – povolené tvary: NÁZEV, !NÁZEV, NÁZEV=HODNOTA, NÁZEV!=HODNOTA.")
            elif declared and mt.group(2) not in known:
                errs.append(f"Podmínka „{when}“ ({kind}) odkazuje na nedeklarovanou proměnnou „{mt.group(2)}“.")
    for d in wires:
        if not isinstance(d, dict):
            errs.append("Vodič fragmentu musí být objekt.")
            continue
        for end in ("a", "b"):
            if (d.get(end) or {}).get("element_id") not in ids:
                errs.append(f"Vodič {d.get('id', '?')} odkazuje na neexistující prvek.")
                break
    if declared:
        for name in sorted(placeholders(frag) - known):
            errs.append(f"Zástupný symbol {{{name}}} není deklarovaný v „variables“.")
    return errs


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
            m = load_macro(p, source)
            if m is not None:
                found[m.name] = m
    return sorted(found.values(), key=lambda m: (m.source != "vestavěné", m.name.lower()))


def save_macro(name: str, description: str, fragment: dict, shared: bool = False) -> Path:
    """Uloží makro ve formátu v2; proměnné odvodí ze zástupných symbolů `{x}` ve fragmentu (typ text)."""
    d = (shared_dir() if shared else None) or user_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{_slug(name)}.json"
    data = {"version": MACRO_VERSION, "name": name, "description": description,
            "variables": [v.to_dict() for v in implicit_variables(fragment)], "fragment": fragment}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
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


def find_macro(name: str) -> Macro | None:
    return next((m for m in list_macros() if m.name == name), None)


def macro_pitch(m: Macro) -> float:
    """Rozteč opakovaných instancí: atribut `pitch` makra, jinak šířka + 10 mm."""
    try:
        return float(m.fragment.get("pitch") or 0) or (fragment_bounds(m.fragment)[2] - fragment_bounds(m.fragment)[0] + 10.0)
    except (TypeError, ValueError):
        return fragment_bounds(m.fragment)[2] - fragment_bounds(m.fragment)[0] + 10.0


# ---------------------------------------------------------------------------------------------------------------
# hodnoty proměnných
ComponentLookup = Callable[[str], object]   # id artiklu → Component | None (např. LibraryStore().component)


def _norm_number(v: str) -> str | None:
    """„15,0“ → „15“, „2,5“ → „2.5“; None = není číslo."""
    t = v.strip().replace(",", ".")
    try:
        f = float(t)
    except ValueError:
        return None
    if not math.isfinite(f):
        return None
    if f.is_integer():
        return str(int(f))
    return f"{f:.6f}".rstrip("0").rstrip(".")


def _component_param(comp, param: str) -> str:
    if param in ("id", "part_number", "manufacturer", "name", "category", "symbol_id", "footprint_id"):
        return _str(getattr(comp, param, ""))
    return _str((getattr(comp, "params", None) or {}).get(param, ""))


def repeat_context_names(m: Macro) -> frozenset[str]:
    """Názvy, které při opakování makra dosazuje `expand` v každé iteraci (k, nk; n, pokud počet není proměnná `n`).
    Bez `repeat` prázdná množina."""
    if m.repeat is None:
        return frozenset()
    return REPEAT_CONTEXT - {m.repeat.count}


def repeat_limit(m: Macro) -> int:
    """Nejvyšší povolený počet opakování: menší z `max` proměnné počtu a MAX_REPEAT."""
    cv = m.variable(m.repeat.count) if m.repeat else None
    if cv is not None and cv.max is not None:
        return max(0, min(math.floor(cv.max), MAX_REPEAT))
    return MAX_REPEAT


def _count_errors(m: Macro, vals: dict, where: str) -> list[str]:
    """Kontrola počtu opakování: celé číslo v rozsahu max(0, min)…`repeat_limit`; prázdné = chyba. Normalizuje vals."""
    name = m.repeat.count
    cv = m.variable(name)
    title = cv.title if cv else name
    raw = str(vals.get(name, "")).strip()
    if not raw:
        return [f"{where}{title}: počet opakování je povinný."]
    num = _norm_number(raw)
    if num is None or not float(num).is_integer():
        return [f"{where}{title}: „{raw}“ není celé číslo (počet opakování)."]
    vals[name] = num
    n = int(float(num))
    lo = max(0, math.ceil(cv.min)) if cv is not None and cv.min is not None else 0
    hi = repeat_limit(m)
    if n < lo:
        return [f"{where}{title}: {n} je menší než {lo}."]
    if n > hi:
        return [f"{where}{title}: {n} je větší než {hi}."]
    return []


def resolve_values(m: Macro, given: dict | None = None, value_set=None, components: ComponentLookup | None = None,
                   context: dict | None = None, base: dict | None = None,
                   repeat: bool = True) -> tuple[dict[str, str], list[str]]:
    """Hodnoty proměnných makra a chyby (česky; prázdný seznam = OK).

    Pořadí (pozdější vyhrává): `default` < `base` (základ volajícího, např. specifikace generátoru) < artikl (`from`)
    < sada hodnot `value_set` (název nebo ValueSet) < `given` (zadané uživatelem / specifikací) < `context`
    (k, n, i, string… od volajícího). Výchozí hodnoty smí skládat text z jiných proměnných (`"T{i}"`, jeden průchod;
    rezervované názvy jen z `given`/`context`, jinak je dosadí až `expand`). Čísla se normalizují („15,0“ → „15“).
    Výsledek obsahuje i nedeklarované klíče z `base`/`given`/`context`.

    Má-li makro `repeat` a volající nepředá `repeat=False` (generátor si opakování drží sám), názvy opakování
    (`repeat_context_names`: k, nk) se z `given` do výchozích hodnot nedosazují – dosadí je `expand` v každé iteraci
    (jinak by `j = "{k}"` dostalo u všech opakování stejné číslo). Počet opakování musí být celé číslo
    0…min(max proměnné, MAX_REPEAT); prázdný = chyba. Hodnoty z `context` se kontrolují jen jako čísla (bez min/max)."""
    given = {k: _str(v) for k, v in (given or {}).items()}
    context = {k: _str(v) for k, v in (context or {}).items()}
    base = {k: _str(v) for k, v in (base or {}).items()}
    errs: list[str] = []
    where = f"Makro „{m.name}“: " if m.name else ""
    vs_vals: dict[str, str] = {}
    if value_set:
        vs = value_set if isinstance(value_set, ValueSet) else m.value_set(str(value_set))
        if vs is None:
            errs.append(f"{where}neznámá sada hodnot „{value_set}“.")
        else:
            vs_vals = dict(vs.values)
    defaults = {v.name: v.default for v in m.variables}
    upper = {**vs_vals, **given, **context}
    pre = {**defaults, **base, **upper}
    # artikl → proměnné s „from“ (nepřebíjí sadu, zadané ani kontext)
    from_vals: dict[str, str] = {}
    comps: dict[str, object] = {}
    for v in m.variables:
        if v.type != "component":
            continue
        cid = pre.get(v.name, "").strip()
        if not cid:
            continue
        comp = components(cid) if components else None
        if comp is None:
            if components is not None:
                errs.append(f"{where}{v.title}: artikl „{cid}“ nenalezen.")
            continue
        if v.category and getattr(comp, "category", v.category) != v.category:
            errs.append(f"{where}{v.title}: artikl „{cid}“ není kategorie „{v.category}“.")
        comps[v.name] = comp
    for v in m.variables:
        if not v.source:
            continue
        cvar, _, param = v.source.partition(".")
        if cvar in comps:
            val = _component_param(comps[cvar], param)
            if val:
                from_vals[v.name] = val
    vals = {**defaults, **base, **from_vals, **upper}
    # skládání textu z jiných proměnných (jeden průchod); k, n, nk… až od opakování / kontextu
    repeating = repeat and m.repeat is not None
    per_run = repeat_context_names(m) if repeating else frozenset()
    src = {k: v for k, v in vals.items()
           if (k not in RESERVED or k in given or k in context) and (k not in per_run or k in context)}
    vals = {k: subst(v, src) for k, v in vals.items()}
    if repeating:
        errs += _count_errors(m, vals, where)
    for v in m.variables:
        if repeating and v.name == m.repeat.count:
            continue   # zkontroloval _count_errors
        val = vals.get(v.name, "")
        if not val.strip():
            if v.required:
                errs.append(f"{where}{v.title}: hodnota je povinná.")
            continue
        if _PH.search(val):
            continue   # doplní se až při rozvinutí (např. „{k}“)
        if v.type == "number":
            num = _norm_number(val)
            if num is None:
                errs.append(f"{where}{v.title}: „{val}“ není číslo.")
                continue
            vals[v.name] = num
            if v.name in context:
                continue   # kontext volajícího (generátor: n = počet stringů v rozvaděči) – min/max platí pro zadání
            f = float(num)
            if v.min is not None and f < v.min:
                errs.append(f"{where}{v.title}: {num} je menší než {_str(v.min)}.")
            if v.max is not None and f > v.max:
                errs.append(f"{where}{v.title}: {num} je větší než {_str(v.max)}.")
        elif v.type == "choice" and v.choices:
            key = val.replace(" ", "").lower()
            hit = next((c for c in v.choices if c.replace(" ", "").lower() == key), None)
            if hit is None:
                errs.append(f"{where}{v.title}: „{val}“ není z nabídky ({', '.join(c or '(prázdné)' for c in v.choices)}).")
            else:
                vals[v.name] = hit
    return vals, errs


# ---------------------------------------------------------------------------------------------------------------
# rozvinutí do listu
def condition(expr, values: dict) -> bool:
    """Podmínka `when`: NAME | !NAME | NAME=VALUE | NAME!=VALUE. Nepravda: "", 0, ne, no, false, off (bez ohledu
    na velikost písmen). Neplatný zápis = pravda (prvek se nevynechá; hlásí ho `validate_macro`)."""
    mt = _WHEN.match(str(expr))
    if not mt:
        return True
    neg, name, op, rhs = mt.groups()
    val = str(values.get(name, "")).strip()
    if op:
        res = val == (rhs or "").strip()
        return (not res) if op == "!=" else res
    res = val.lower() not in FALSE_VALUES
    return (not res) if neg else res


def _expand_once(project, sheet, fragment: dict, values: dict, dx: float, dy: float, ref_prefix_of,
                 components: ComponentLookup | None, used: set[str], created: list,
                 copy: bool = False) -> tuple[list, list]:
    from envocad.model.project import Element, Wire, WireEnd
    idmap: dict[str, str] = {}
    els: list[Element] = []
    for d in fragment.get("elements", []):
        src = Element.from_dict(d)
        when = src.attrs.get("when")
        if when is not None and not condition(when, values):
            continue
        attrs = {k: subst(v, values) for k, v in src.attrs.items() if k != "when"}
        shared = str(src.attrs.get("shared", "")).strip() in ("1", "true", "ano")
        if shared:
            ref = attrs.get("ref", "")
            existing = next((e for e in [*sheet.elements, *created]
                             if e.symbol_id == src.symbol_id and e.ref == ref and ref), None)
            if existing is not None:
                idmap[src.id] = existing.id
                continue
        cid = subst(src.component_id, values) if src.component_id else None
        if cid and _PH.search(cid):
            cid = None   # nedosazený artikl („{inv}“ bez hodnoty)
        new = Element(symbol_id=src.symbol_id, x=src.x + dx, y=src.y + dy, rotation=src.rotation, attrs=attrs,
                      component_id=cid or None)
        if cid and components is not None and src.component_id != cid:
            comp = components(cid)
            if comp is not None:
                comp.apply_to(new)   # parametry artiklu → atributy (mppt, strings_per_mppt → DC vstupy střídače)
        prefix = ref_prefix_of(src.symbol_id) if ref_prefix_of else ""
        keep = _KEEP_REF
        if copy and not shared:
            # kopie jako `paste_fragment`: čísla svorek se vymažou, přívody/vývody se přečíslují (bez zástupných symbolů)
            keep = tuple(s for s in _KEEP_REF if s not in _FEED_SYMBOLS)
            if src.symbol_id in _TERMINAL_SYMBOLS and not _placeholders_in(src.attrs.get("terminal")):
                new.attrs["terminal"] = ""
        if "{" not in str(src.attrs.get("ref", "")) and src.attrs.get("ref") and prefix and not shared \
                and src.symbol_id not in keep:
            n = 1
            while f"{prefix}{n}" in used:
                n += 1
            new.attrs["ref"] = f"{prefix}{n}"
        used.add(new.attrs.get("ref", ""))
        new.attrs.pop("sheet", None)
        idmap[src.id] = new.id
        els.append(new)
        created.append(new)
    wires: list[Wire] = []
    for d in fragment.get("wires", []):
        w = Wire.from_dict(d)
        if w.a.element_id not in idmap or w.b.element_id not in idmap:
            continue
        when = w.attrs.get("when")
        if when is not None and not condition(when, values):
            continue
        nw = Wire(WireEnd(idmap[w.a.element_id], subst(w.a.port, values)),
                  WireEnd(idmap[w.b.element_id], subst(w.b.port, values)),
                  points=[(x + dx, y + dy) for x, y in w.points],
                  attrs={k: subst(v, values) for k, v in w.attrs.items() if k != "when"},
                  conductors=list(w.conductors))
        if nw.attrs.get("ref") and "{" not in str(w.attrs.get("ref", "")):
            n = 1
            while f"W{n}" in used:
                n += 1
            nw.attrs["ref"] = f"W{n}"
            used.add(nw.attrs["ref"])
        wires.append(nw)
    return els, wires


def _grid(v: float, step: float = 2.5) -> float:
    return round(v / step) * step


def repeat_count(m: Macro, values: dict) -> int:
    """Počet opakování makra (1 bez `repeat`). ValueError, je-li počet neplatný nebo větší než `repeat_limit`
    (menší z `max` proměnné počtu a MAX_REPEAT)."""
    if m.repeat is None:
        return 1
    raw = _str(values.get(m.repeat.count, "")).strip()
    num = _norm_number(raw) if raw else None
    if num is None or not float(num).is_integer():
        raise ValueError(f"Makro „{m.name}“: počet opakování „{raw}“ ({m.repeat.count}) není celé číslo.")
    n = int(float(num))
    hi = repeat_limit(m)
    if n < 0 or n > hi:
        raise ValueError(f"Makro „{m.name}“: počet opakování {n} je mimo rozsah 0–{hi}.")
    return n


def expand(project, sheet, m: Macro | dict, values: dict, dx: float = 0.0, dy: float = 0.0, ref_prefix_of=None,
           components: ComponentLookup | None = None, repeat: bool = True,
           copy: bool | None = None) -> tuple[list, list]:
    """Rozvine makro: dosadí `{proměnné}` (atributy, označení, artikl, porty a atributy vodičů), vynechá prvky/vodiče
    s nesplněnou podmínkou `when` (i vodiče vynechaných prvků), prvky s `shared` sloučí s existujícím prvkem stejné
    značky a označení (na listu nebo z dřívějšího opakování), ostatní označení bez proměnných přečísluje (F1 → další
    volné). Prvek s `component_id` ze zástupného symbolu dostane parametry artiklu (`Component.apply_to`, potřebuje
    `components`). S `repeat` a `m.repeat` se makro vloží N× (k = 1…N, n = N, nk = N + k, posun (k−1)·rozteč na mřížce).

    List se NEMĚNÍ: vrací (nové prvky, nové vodiče) k vložení jedním undo příkazem (vodiče smí odkazovat na sloučené
    `shared` prvky, které už v listu jsou). `values` = výsledek `resolve_values`. `m` smí být i holý fragment (dict).

    `copy` = vložit jako kopii výřezu (jako dřívější `paste_fragment`): nesdíleným skupinám svorek se vymaže číslo
    svorky (`terminal`), přívody/vývody (`sb.feed_in`/`sb.feed_out`) se přečíslují – obojí jen bez zástupného symbolu.
    Výchozí None = kopie u makra bez proměnných a opakování (`not m.has_parameters`, uživatelské výřezy); parametrická
    makra (vestavěná, generátor) si označení svorek a přívodů drží. Holý fragment (`instantiate`) = bez kopie."""
    if copy is None:
        copy = isinstance(m, Macro) and not m.has_parameters
    if isinstance(m, dict):
        m = Macro(name="", description="", fragment=m, path=Path(), source="")
    used = project.used_refs(sheet)
    created: list = []
    all_els: list = []
    all_wires: list = []
    base = {k: _str(v) for k, v in values.items()}
    if repeat and m.repeat is not None:
        n = repeat_count(m, base)
        pitch = m.repeat.pitch or macro_pitch(m)
        runs = [({"k": str(k), "n": str(n), "nk": str(n + k)}, _grid((k - 1) * pitch)) for k in range(1, n + 1)]
    else:
        runs = [({}, 0.0)]
    for ctx, off in runs:
        vals = {**base, **ctx}
        vals = {k: subst(v, vals) for k, v in vals.items()}   # např. j = „{k}“, string = „G{k}“
        els, wires = _expand_once(project, sheet, m.fragment, vals, dx + off, dy, ref_prefix_of, components, used, created,
                                  copy)
        all_els += els
        all_wires += wires
    return all_els, all_wires


def insert(sheet, elements: list, wires: list) -> None:
    """Vloží výsledek `expand` do listu (bez undo – generátor, testy)."""
    sheet.elements.extend(elements)
    sheet.wires.extend(wires)


def instantiate(project, sheet, fragment: dict, vars_: dict, dx: float = 0.0, dy: float = 0.0,
                ref_prefix_of=None) -> tuple[list, list]:
    """Vloží parametrický fragment do listu (`expand` bez opakování + `insert`). Vrací (nové prvky, nové vodiče) –
    už vložené do listu."""
    els, wires = expand(project, sheet, fragment, vars_, dx, dy, ref_prefix_of, repeat=False)
    insert(sheet, els, wires)
    return els, wires
