"""Rozbor příkazového řádku (bez Qt): tokeny, body „x,y“ / „@dx,dy“ / „ref:port“, čísla, „klíč=hodnota“.

Souřadnice jsou v mm listu (počátek levý dolní roh, Y nahoru), desetinná **tečka** (čárka dělí souřadnice). Nic se
nevyhodnocuje jako kód: hodnoty jsou řetězce a čísla parsovaná explicitně (`float` jen nad ověřeným vzorem).
"""
from __future__ import annotations

import math
import re
import shlex

NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")
POINT_RE = re.compile(rf"(@)?({NUMBER_RE.pattern}),({NUMBER_RE.pattern})")
PORT_RE = re.compile(r"([^\s:,@=]+):([^\s:,=]+)")
KV_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.\-]*)=(.*)", re.DOTALL)
VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ParseError(ValueError):
    """Chybný zápis na řádku (česká hláška pro uživatele)."""


def tokenize(line: str) -> list[str]:
    """Řádek → tokeny (shlex, uvozovky pro mezery v hodnotě: `SET desc="Hlavní jistič"`). Neuzavřené uvozovky →
    ParseError. Komentáře `#` řeší až skript (celý řádek), uvnitř řádku je `#` obyčejný znak."""
    lex = shlex.shlex(line, posix=True)
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        return list(lex)
    except ValueError as ex:
        raise ParseError("neuzavřené uvozovky") from ex


def is_number(text: str) -> bool:
    return NUMBER_RE.fullmatch(text.strip()) is not None


def parse_number(text: str) -> float:
    """Číslo s desetinnou tečkou („2.5“, „-90“). Čárka → hláška s nápovědou (čárka dělí souřadnice)."""
    t = text.strip()
    if NUMBER_RE.fullmatch(t):
        v = float(t)
        if math.isfinite(v):
            return v
    if re.fullmatch(r"[+-]?\d+,\d+", t):
        raise ParseError(f"„{text}“: desetinná čárka – použijte tečku ({t.replace(',', '.')})")
    raise ParseError(f"„{text}“ není číslo")


def is_point(text: str) -> bool:
    return POINT_RE.fullmatch(text.strip()) is not None


def parse_xy(text: str, last: tuple[float, float] | None = None) -> tuple[float, float]:
    """„x,y“ absolutně nebo „@dx,dy“ relativně k poslednímu bodu `last`. Bez posledního bodu je „@“ chyba."""
    t = text.strip()
    m = POINT_RE.fullmatch(t)
    if m is None:
        if t.count(",") > 1 and re.fullmatch(r"@?[\d+\-.,]+", t):
            raise ParseError(f"„{text}“: bod je „x,y“ s desetinnou tečkou (např. 12.5,40)")
        raise ParseError(f"„{text}“ není bod (x,y, @dx,dy nebo ref:port)")
    x, y = float(m.group(2)), float(m.group(3))
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ParseError(f"„{text}“ není bod")
    if m.group(1):
        if last is None:
            raise ParseError(f"„{text}“: relativní bod bez předchozího bodu")
        return (last[0] + x, last[1] + y)
    return (x, y)


def parse_port_ref(text: str) -> tuple[str, str] | None:
    """„F1:2“ → ("F1", "2"); jiný zápis → None."""
    m = PORT_RE.fullmatch(text.strip())
    return (m.group(1), m.group(2)) if m else None


def is_kv(text: str) -> bool:
    return KV_RE.fullmatch(text) is not None


def parse_kv(text: str) -> tuple[str, str]:
    m = KV_RE.fullmatch(text)
    if m is None:
        raise ParseError(f"„{text}“ není ve tvaru klíč=hodnota")
    return m.group(1), m.group(2)


def is_selector(text: str) -> bool:
    """Token, který se dá číst jako označení / glob výběru (F1, Q*, RFVE.AC) – ne bod, číslo ani klíč=hodnota."""
    t = text.strip()
    return bool(t) and not is_number(t) and not is_point(t) and "=" not in t and ":" not in t \
        and not t.startswith("@") and "," not in t


def substitute_vars(line: str, variables: dict[str, str]) -> str:
    """Textové dosazení `${name}` (jen z `variables`; neznámá proměnná → ParseError)."""
    def rep(m: re.Match) -> str:
        name = m.group(1)
        if name not in variables:
            raise ParseError(f"neznámá proměnná ${{{name}}}")
        return variables[name]
    return VAR_RE.sub(rep, line)


def space_submits(buffer: str, prompt_kind: str | None = None) -> bool:
    """GUI: má mezerník potvrdit řádek jako Enter? Ne uvnitř neuzavřených uvozovek a ne ve výzvě typu text
    (rozhodnutí 3); jinak ano."""
    if prompt_kind == "text":
        return False
    quote = None
    esc = False
    for c in buffer:
        if esc:
            esc = False
        elif c == "\\" and quote != "'":
            esc = True
        elif quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
    return quote is None
