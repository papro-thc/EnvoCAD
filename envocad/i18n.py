"""Překlady rozhraní (gettext-styl, bez Qt). Zdrojové texty jsou česky a obalují se `tr("…")`; překlady jsou v textových
katalozích `envocad/resources/i18n/<jazyk>.po`, čtených přímo za běhu (bez .mo/.qm). Viz `docs/PREKLADY.md`."""
from __future__ import annotations

from pathlib import Path

DEFAULT_LANGUAGE = "cs"
LANGUAGES = {"cs": "Čeština", "en": "English"}

Catalog = dict[tuple[str | None, str], str]

_language = DEFAULT_LANGUAGE
_catalog: Catalog = {}


def set_language(code) -> str:
    """Nastaví jazyk rozhraní a načte jeho katalog; neplatný kód (i `None`) → čeština. Vrací nastavený kód."""
    global _language, _catalog
    code = code if isinstance(code, str) and code in LANGUAGES else DEFAULT_LANGUAGE
    _catalog = load_catalog(code) if code != DEFAULT_LANGUAGE else {}
    _language = code
    return code


def language() -> str:
    return _language


def tr(text: str, ctx: str | None = None) -> str:
    """Přeložený text; čeština je identita, chybějící nebo prázdný překlad vrátí původní `text`."""
    if _language == DEFAULT_LANGUAGE:
        return text
    return _catalog.get((ctx, text)) or text


def catalog_path(lang: str) -> Path:
    return Path(__file__).resolve().parent / "resources" / "i18n" / f"{lang}.po"


def load_catalog(lang: str) -> Catalog:
    if lang == DEFAULT_LANGUAGE:
        return {}
    try:
        return parse_po(catalog_path(lang).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError):      # chybějící / poškozený katalog nesmí shodit start – zůstane čeština
        return {}


_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) < 2 or s[0] != '"' or s[-1] != '"':
        return ""
    out, i, body = [], 0, s[1:-1]
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            i += 1
            out.append(_ESCAPES.get(body[i], "\\" + body[i]))
        else:
            out.append(c)
        i += 1
    return "".join(out)


def parse_po(text: str) -> Catalog:
    """Zjednodušený parser `.po`: komentáře, víceřádkové řetězce, escape sekvence, `msgctxt`. Vynechá hlavičku
    (prázdný msgid), prázdné překlady a záznamy označené `#, fuzzy`."""
    out: Catalog = {}
    entry: dict[str, str] = {}
    field: str | None = None
    fuzzy = False

    def flush() -> None:
        nonlocal entry, field, fuzzy
        if "msgid" in entry and entry["msgid"] and entry.get("msgstr") and not fuzzy:
            out[(entry.get("msgctxt"), entry["msgid"])] = entry["msgstr"]
        entry, field, fuzzy = {}, None, False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("#"):
            if "msgstr" in entry:                  # komentář za hotovým záznamem (bez prázdného řádku) patří dalšímu
                flush()
            if line.startswith("#,") and "fuzzy" in line:
                fuzzy = True
        elif line.startswith('"'):
            if field:
                entry[field] += _unquote(line)
        else:
            key, _, rest = line.partition(" ")
            if key not in ("msgctxt", "msgid", "msgstr"):
                continue
            # nový záznam bez prázdného řádku
            if (key == "msgctxt" and "msgid" in entry) or (key == "msgid" and "msgstr" in entry):
                flush()
            field = key
            entry[key] = _unquote(rest)
    flush()
    return out
