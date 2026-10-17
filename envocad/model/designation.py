"""Strukturní označení dle ČSN EN IEC 81346: =funkce +umístění -přístroj. Čistá data, bez Qt.

`attrs["ref"]` prvku je jen přístrojová část („F3“). Aspekty `=` a `+` se dědí z listu (`Sheet.func`, `Sheet.loc`)
a prvek je může přepsat atributy `func` / `loc` (prázdné = dědit). Modul nezávisí na `project.py` (duck typing):
`sheet` má `id`, `func`, `loc`, `is_switchboard`; cíl je prvek (má `symbol_id`) nebo vodič, oba mají `attrs`.
"""
from __future__ import annotations

import re
import string
from dataclasses import dataclass

FUNC, LOC = "=", "+"
ASPECT_NAMES = {FUNC: "Funkce", LOC: "Umístění"}
LOCATION_SYMBOLS = {"fve.switchboard"}          # prvky, jejichž ref je kód umístění
MAX_CODE_LEN = 10

# Čitelný název prvku bez označení do textů (křížové odkazy, výkazy, TZ, kontroly) – místo symbol_id.
# Zkratky: DS = distribuční soustava (síť), HOP = hlavní ochranná přípojnice (ekvipotenciální svorkovnice).
SHORT_NAMES = {
    "fve.grid": "DS", "fve.load": "spotřebič", "sb.junction": "uzel", "sb.busbar": "sběrnice",
    "sb.pe_bar": "PE lišta", "fve.interrupt": "přerušovací bod", "sb.feed_in": "přívod", "sb.feed_out": "vývod",
    "fve.switchboard": "rozvaděč", "fve.pv_string": "string", "fve.battery": "baterie",
    "fve.inverter": "střídač", "fve.inverter_hybrid": "střídač",
}
SHORT_NAME_MAX = 20


def element_name(e, lib=None) -> str:
    """Jak prvek nazvat v textu: označení (`ref`), jinak zkratka druhu (`SHORT_NAMES`: síť → „DS“; uzemnění s popisem
    HOP → „HOP“, jinak „uzemnění“), jinak název značky z knihovny zkrácený na `SHORT_NAME_MAX` znaků, jinak poslední
    část symbol_id. Jedna funkce pro křížové odkazy, výkazy, TZ i kontroly."""
    ref = str(getattr(e, "attrs", {}).get("ref", "") or "")
    if ref:
        return ref
    sid = getattr(e, "symbol_id", "") or ""
    if sid == "fve.earth":
        return "HOP" if "HOP" in str(e.attrs.get("desc", "")).upper() else "uzemnění"
    if sid in SHORT_NAMES:
        return SHORT_NAMES[sid]
    if lib is not None:
        try:
            name = str(lib.get_symbol(sid).name or "").strip()
        except Exception:  # noqa: BLE001 – neznámá značka
            name = ""
        if name:
            return name if len(name) <= SHORT_NAME_MAX else name[:SHORT_NAME_MAX - 1].rstrip() + "…"
    return sid.split(".")[-1] or "?"
MAX_REF_LEN = 10
MAX_FULL_LEN = 32
CODE_RE = re.compile(r"[A-Z][A-Z0-9_]*")
REF_CHARS_RE = re.compile(r"[A-Z0-9_]+")        # vodič smí začínat číslicí
SEPARATORS = set("=+-.:/") | set(string.whitespace)
# Firemní číslování ENVO (docs/ENVO_STYL.md) používá „.“ a vnitřní „-“ v označení: FU1.1, QS1.2, SPD-DC1.1.
# Plné označení se tím nerozbije (aspekty = a + stojí vždy před „-“). Tečka je schválený firemní standard
# (bez nálezu), vnitřní „-“ je jen informace; ostatní oddělovače (=, +, :, /, mezera) a úvodní „-“ jsou chyba –
# kolidují s aspekty a se zápisem svorek „X1:3“.
SOFT_SEPARATORS = set(".-")
INFO_SEPARATORS = set("-")                      # měkké oddělovače, které se hlásí jako INFO
CABLE_SCOPE = ("~cable", "")                    # vodiče JPS (kabely) – jeden prostor pro celý projekt


@dataclass(frozen=True)
class Designation:
    func: str = ""
    loc: str = ""
    ref: str = ""

    def __str__(self) -> str:
        return "".join(f"{sign}{part}" for sign, part in ((FUNC, self.func), (LOC, self.loc), ("-", self.ref))
                       if part)

    @property
    def aspects(self) -> str:
        """Jen část funkce a umístění („=AC+RS1“), bez přístroje."""
        return str(Designation(self.func, self.loc))


@dataclass(frozen=True)
class DesignationIssue:
    code: str      # ref_syntax | ref_chars | ref_length | ref_class | struct_syntax
    error: bool
    text: str      # česky
    info: bool = False   # jen informace (firemní číslování s „.“ / „-“), ne varování


def parse_designation(text: str) -> Designation:
    """„=AC+RS1-F3“, „+RS1-F3“, „F3“ → Designation. Opakovaný aspekt nebo víceúrovňový kód („=AC.1“, „+A+B“)
    → ValueError. Přístrojová část je vše za prvním „-“ (firemní „SPD-DC1.1“ zůstane celé)."""
    text = (text or "").strip()
    if not text:
        return Designation()
    if text[0] not in "=+-":
        text = "-" + text
    head, dash, ref = text.partition("-")
    if dash and ("=" in ref or "+" in ref):
        raise ValueError(f"Označení {text!r}: aspekty = a + musí předcházet přístroji")
    parts: dict[str, str] = {"-": ref.strip()} if dash else {}
    for sign, code in re.findall(r"([=+])([^=+]*)", head):
        code = code.strip()
        if sign in parts:
            raise ValueError(f"Označení {text!r}: aspekt {sign!r} je uvedený víckrát (víceúrovňové označení)")
        if sign != "-" and "." in code:
            raise ValueError(f"Označení {text!r}: víceúrovňový kód {code!r} není podporován")
        parts[sign] = code
    return Designation(parts.get(FUNC, ""), parts.get(LOC, ""), parts.get("-", ""))


def letter_code(ref: str) -> str:
    """Písmenný kód třídy z označení: „F3“ → „F“, „QA12“ → „QA“, „101“ → „“."""
    m = re.match(r"[A-Za-z]*", ref or "")
    return m.group(0).upper() if m else ""


def class_matches(ref: str, classes: list[str]) -> bool:
    """Odpovídá označení některé z povolených tříd? Shoda prefixem („F“ přijme F, FA, FC). Prázdné třídy = bez kontroly."""
    if not classes:
        return True
    code = letter_code(ref)
    return bool(code) and any(code.startswith(c) for c in classes)


def validate_code(code: str, aspect: str, where: str = "") -> list[DesignationIssue]:
    """Kód funkce/umístění: A–Z, 0–9, _, začíná písmenem, nejvýš MAX_CODE_LEN znaků. `where` doplní text („listu X“)."""
    if not code:
        return []
    if CODE_RE.fullmatch(code) and len(code) <= MAX_CODE_LEN:
        return []
    name = ASPECT_NAMES.get(aspect, "Kód")
    place = f" {where}" if where else ""
    return [DesignationIssue("struct_syntax", True,
                             f"{name} „{code}“{place} není platný kód (A–Z, 0–9, _, max. {MAX_CODE_LEN})")]


def _separator_name(ch: str) -> str:
    return "mezeru" if ch == " " else ("bílý znak" if ch.isspace() else f"„{ch}“")


def validate_ref(ref: str, classes: list[str] | None, *, is_wire: bool = False,
                 name: str = "") -> list[DesignationIssue]:
    """Přístrojová část označení (bez „-“). `classes` = povolené třídy značky (None/[] = nekontrolovat třídu),
    `name` = název značky do textu nálezu. Tečka (firemní číslování) projde bez nálezu, vnitřní „-“ je INFO; kontrola pokračuje:
    znaky se kontrolují bez měkkých oddělovačů, délka a třída z celého označení („SPD-DC1.1“ → třída SPD)."""
    if not ref:
        return []
    out: list[DesignationIssue] = []
    if ref.startswith("-"):
        return [DesignationIssue("ref_syntax", True, f"Označení „{ref}“: označení zadej bez „-“")]
    bad = next((ch for ch in ref if ch in SEPARATORS - SOFT_SEPARATORS), "")
    if bad:
        return [DesignationIssue("ref_syntax", True, f"Označení „{ref}“ obsahuje nepovolený znak "
                                                    f"{_separator_name(bad)} (oddělovač aspektů)")]
    soft = next((ch for ch in ref if ch in INFO_SEPARATORS), "")
    if soft:
        out.append(DesignationIssue("ref_syntax", False, f"Označení „{ref}“ obsahuje znak „{soft}“ (oddělovač dle "
                                                        "IEC 81346) – přípustné jen jako firemní číslování", info=True))
    bare = "".join(ch for ch in ref if ch not in SOFT_SEPARATORS)    # znaky bez firemních oddělovačů
    if not REF_CHARS_RE.fullmatch(bare):
        out.append(DesignationIssue("ref_chars", False,
                                    f"Označení „{ref}“: povolena jen velká písmena A–Z, číslice a _"))
    if len(ref) > MAX_REF_LEN:
        out.append(DesignationIssue("ref_length", False, f"Označení „{ref}“ je delší než {MAX_REF_LEN} znaků"))
    if classes and not is_wire and not class_matches(ref, classes):
        what = f"funkci značky {name}" if name else "funkci značky"
        out.append(DesignationIssue("ref_class", False, f"Označení {ref} neodpovídá {what} "
                                                        f"(povolené třídy: {', '.join(classes)})"))
    return out


def _is_element(target) -> bool:
    return hasattr(target, "symbol_id")


def designation(sheet, target) -> Designation:
    """Efektivní označení prvku/vodiče: func/loc z overridu prvku (`attrs func/loc`), jinak z listu; ref."""
    attrs = getattr(target, "attrs", {}) or {}
    func, loc = sheet.func, sheet.loc
    if _is_element(target):
        func = attrs.get("func") or func
        loc = attrs.get("loc") or loc
    return Designation(func, loc, attrs.get("ref", ""))


def sheet_scope(sheet) -> tuple[str, str]:
    """Prostor označení prvků listu bez overridu: (func, loc); list rozvaděče bez umístění má vlastní anonymní."""
    if sheet.is_switchboard and not sheet.loc:
        return (sheet.func, "#" + sheet.id)
    return (sheet.func, sheet.loc)


def scope_key(sheet, target) -> tuple[str, str]:
    """Prostor, ve kterém musí být `ref` jedinečný: (func, loc). Anonymní rozvaděč ("", "#"+id), vodič JPS
    (kabel) ("~cable", "")."""
    if not _is_element(target):
        return CABLE_SCOPE if not sheet.is_switchboard else sheet_scope(sheet)
    d = designation(sheet, target)
    if sheet.is_switchboard and not d.loc:
        return (d.func, "#" + sheet.id)
    return (d.func, d.loc)


def full_designation(project, sheet, target) -> str:
    """Plné označení „=AC+RS1-F3“ (bez aspektů „-F3“). Prvek umístění (blok rozvaděče) → „=func+REF“."""
    del project  # rezervováno (např. víceúrovňová struktura) – výsledek dnes závisí jen na listu a prvku
    d = designation(sheet, target)
    if _is_element(target) and target.symbol_id in LOCATION_SYMBOLS:
        return str(Designation(d.func, d.ref)) if d.ref else ""
    return str(d)


def display_designation(sheet, target) -> str:
    """Popisek do výkresu: jen aspekty odlišné od listu + ref; bez overridu je to samotný ref („F3“)."""
    d = designation(sheet, target)
    if not _is_element(target) or target.symbol_id in LOCATION_SYMBOLS:
        return d.ref
    func = d.func if d.func != sheet.func else ""
    loc = d.loc if d.loc != sheet.loc else ""
    if not func and not loc:
        return d.ref
    return str(Designation(func, loc, d.ref))
