"""Šablona dokumentu .docx s poli a bloky (TZ, DSPS) – malý engine nad python-docx, bez Qt a bez jinja.

Návrh `docs/design/tz_dsps.md`. Šablona je dokument Word (nebo zdroj `.md`, který se převede `doc_from_markdown`):

- pole `{{cesta.k.hodnote}}` kdekoli v textu (odstavce, buňky tabulek, záhlaví, zápatí); chybí-li → „neuvedeno“
  (jednotka hned za polem – „ kWp“, „ V“… – se pak vynechá), `{{cesta|náhrada}}` vlastní náhrada, `{{cesta|}}` nic;
- řídicí odstavce `{% if cesta %}`, `{% if not cesta %}`, `{% if cesta == "text" %}` (`!=`), `{% else %}`,
  `{% endif %}`, `{% for x in seznam %}` … `{% endfor %}` – celý odstavec je značka, obsah mezi nimi se vynechá /
  opakuje (odstavce i tabulky), vnořování povoleno;
- vložený blok: odstavec, jehož celý text je `{{tabulka.jméno}}` nebo `{{blok.jméno}}`, nahradí obsah, který vytvoří
  funkce z `blocks` (připisuje do dokumentu – engine ho přesune na místo značky);
- `{{§}}` v nadpisu = číslo kapitoly podle úrovně nadpisu (1, 1.1, …), počítá se až po vynechání sekcí.

Vyhodnocení nikdy nespadne kvůli šabloně: neznámá cesta, neznámý blok i neuzavřená značka dají text, ne výjimku.
"""
from __future__ import annotations

import copy
import logging
import re
from collections.abc import Callable, Mapping
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

log = logging.getLogger("envocad.export")

MISSING = "neuvedeno"
NUMBER_TOKEN = "{{§}}"
_FIELD = re.compile(r"\{\{\s*([^{}|]*?)\s*(?:\|([^{}]*))?\}\}")
# jednotka hned za polem – u chybějícího údaje se vynechá („neuvedeno“, ne „neuvedeno kWp“)
_UNIT = re.compile(r"[ \u00a0](?:kWp|kWh|kVA|kW|Wp|kA|ks|°C|mA|mm²|V|A|W|K|%|m)(?![\w²])")
_CTRL = re.compile(r"^\{%\s*(.*?)\s*%\}$")
_IF = re.compile(r"^if\s+(not\s+)?([\w.]+)\s*(?:(==|!=)\s*\"([^\"]*)\")?$")
_FOR = re.compile(r"^for\s+(\w+)\s+in\s+([\w.]+)$")
_BLOCK = re.compile(r"^\{\{\s*((?:tabulka|blok)\.\w+)\s*\}\}$")
_HEADING = re.compile(r"^(?:Heading|Nadpis)\s*(\d)$", re.IGNORECASE)

BlockFn = Callable[[object, Mapping], None]   # (dokument, kontext) → připíše obsah na konec dokumentu


# ---- hodnoty -------------------------------------------------------------------------------------------------
def lookup(ctx: Mapping, path: str):
    """Hodnota podle tečkové cesty (slovníky i atributy objektů); chybí-li cokoli po cestě → None."""
    cur: object = ctx
    for part in path.split("."):
        if not part:
            return None
        if isinstance(cur, Mapping):
            cur = cur.get(part)
        elif isinstance(cur, (list, tuple)) and part.isdigit():
            i = int(part)
            cur = cur[i] if i < len(cur) else None
        else:
            cur = getattr(cur, part, None)
        if cur is None:
            return None
    return cur


def is_empty(v) -> bool:
    return v is None or v is False or (isinstance(v, (str, list, tuple, dict)) and not (v.strip() if isinstance(v, str) else v))


def fmt_value(v) -> str:
    """Hodnota do textu: číslo s desetinnou čárkou, seznam čárkami, bool ano/ne."""
    if v is True:
        return "ano"
    if isinstance(v, float):
        return f"{v:g}".replace(".", ",")
    if isinstance(v, (list, tuple)):
        return ", ".join(fmt_value(x) for x in v if not is_empty(x))
    return str(v)


def substitute(text: str, ctx: Mapping) -> str:
    """Dosadí pole `{{…}}` (kromě čísla kapitoly `{{§}}`)."""
    out, pos = [], 0
    for m in _FIELD.finditer(text):
        out.append(text[pos:m.start()])
        pos = m.end()
        path, default = m.group(1), m.group(2)
        if path == "§":
            out.append(m.group(0))
            continue
        v = lookup(ctx, path)
        if not is_empty(v):
            out.append(fmt_value(v))
            continue
        out.append(MISSING if default is None else default)
        unit = _UNIT.match(text, pos) if default is None else None
        if unit:
            pos = unit.end()
    out.append(text[pos:])
    return "".join(out)


def condition(expr: str, ctx: Mapping) -> bool | None:
    """Podmínka `if` (bez „if“); neplatný zápis → None."""
    m = _IF.match(f"if {expr}")
    if not m:
        return None
    neg, path, op, lit = m.groups()
    v = lookup(ctx, path)
    if op:
        res = (fmt_value(v) if not is_empty(v) else "") == lit
        res = res if op == "==" else not res
    else:
        res = not is_empty(v)
    return not res if neg else res


# ---- odstavce ------------------------------------------------------------------------------------------------
def _p_text(p) -> str:
    return "".join(t.text or "" for t in p.iter(qn("w:t")))


def _substitute_paragraph(p_el, ctx: Mapping) -> None:
    par = Paragraph(p_el, None)
    runs = par.runs
    for r in runs:      # pole celé v jednom runu – formát runu zůstane
        if "{{" in r.text:
            r.text = substitute(r.text, ctx)
    full = "".join(r.text for r in runs)
    if "{{" in full and "}}" in full and _FIELD.search(full) and \
            _FIELD.sub(lambda m: m.group(0) if m.group(1) == "§" else "", full) != full:
        runs[0].text = substitute(full, ctx)    # pole přes více runů (Word je rozdělil) → do prvního runu
        for r in runs[1:]:
            r.text = ""


def _ctrl(el) -> str | None:
    if el.tag != qn("w:p"):
        return None
    m = _CTRL.match(_p_text(el).strip())
    return m.group(1) if m else None


def _find_end(elems: list, start: int, opener: str, closer: str) -> tuple[int | None, int | None]:
    """(index `else`, index ukončení) ke značce na `start`; vnořené stejné značky se přeskočí."""
    depth, els = 0, None
    for i in range(start + 1, len(elems)):
        c = _ctrl(elems[i])
        if c is None:
            continue
        word = c.split()[0] if c.split() else ""
        if word == opener:
            depth += 1
        elif word == closer:
            if depth == 0:
                return els, i
            depth -= 1
        elif word == "else" and depth == 0 and opener == "if":
            els = i
    return els, None


def _remove(el) -> None:
    parent = el.getparent()
    if parent is not None:
        parent.remove(el)


def _warn_paragraph(el, text: str) -> None:
    """Chybná značka – odstavec zůstane s vysvětlením (šablona se dá opravit, export nespadne)."""
    par = Paragraph(el, None)
    for r in par.runs[1:]:
        r.text = ""
    if par.runs:
        par.runs[0].text = text
    else:
        par.add_run(text)


class _Renderer:
    def __init__(self, doc, blocks: Mapping[str, BlockFn]):
        self.doc = doc
        self.blocks = blocks
        self.body = doc.element.body

    def elements(self, elems: list, ctx: Mapping) -> None:
        i = 0
        while i < len(elems):
            el = elems[i]
            c = _ctrl(el)
            if c is not None:
                i = self._control(elems, i, c, ctx)
                continue
            if el.tag == qn("w:p"):
                self._paragraph(el, ctx)
            elif el.tag == qn("w:tbl"):
                self._table(el, ctx)
            i += 1

    def _control(self, elems: list, i: int, c: str, ctx: Mapping) -> int:
        word = c.split()[0] if c.split() else ""
        if word in ("if", "for"):
            closer = "endif" if word == "if" else "endfor"
            els, end = _find_end(elems, i, word, closer)
            if end is None:
                _warn_paragraph(elems[i], f"[chyba šablony: chybí {{% {closer} %}} k {{% {c} %}}]")
                return i + 1
            if word == "if":
                ok = condition(c[2:].strip(), ctx)
                if ok is None:
                    _warn_paragraph(elems[i], f"[chyba šablony: neplatná podmínka {{% {c} %}}]")
                    ok = False
                else:
                    _remove(elems[i])
                stop = els if els is not None else end
                keep = elems[i + 1:stop] if ok else (elems[els + 1:end] if els is not None else [])
                drop = elems[els + 1:end] if ok and els is not None else ([] if ok else elems[i + 1:stop])
                for el in drop:
                    _remove(el)
                if els is not None:
                    _remove(elems[els])
                _remove(elems[end])
                self.elements(keep, ctx)
                return end + 1
            m = _FOR.match(c)
            body = elems[i + 1:end]
            items = lookup(ctx, m.group(2)) if m else None
            if m is None:
                _warn_paragraph(elems[i], f"[chyba šablony: neplatné opakování {{% {c} %}}]")
            else:
                _remove(elems[i])
            anchor = elems[end]
            for item in (items if isinstance(items, (list, tuple)) else []):
                copies = [copy.deepcopy(el) for el in body]
                for cp in copies:
                    anchor.addprevious(cp)
                self.elements(copies, {**ctx, m.group(1): item})
            for el in body:
                _remove(el)
            _remove(anchor)
            return end + 1
        # osamocené else / endif / endfor nebo neznámá značka
        _warn_paragraph(elems[i], f"[chyba šablony: nečekaná značka {{% {c} %}}]")
        return i + 1

    def _paragraph(self, el, ctx: Mapping) -> None:
        text = _p_text(el).strip()
        m = _BLOCK.match(text)
        if m and el.getparent() is self.body:
            self._block(el, m.group(1), ctx)
            return
        _substitute_paragraph(el, ctx)

    def _block(self, el, name: str, ctx: Mapping) -> None:
        fn = self.blocks.get(name)
        if fn is None:
            _warn_paragraph(el, MISSING)
            return
        sect = self.body.find(qn("w:sectPr"))
        before = len(self.body)
        try:
            fn(self.doc, ctx)
        except Exception:
            log.exception("Blok šablony %s selhal", name)
            for extra in list(self.body)[before - (1 if sect is not None else 0):]:
                if extra.tag != qn("w:sectPr"):
                    self.body.remove(extra)
            _warn_paragraph(el, f"{MISSING} (výpočet „{name}“ selhal)")
            return
        new = [x for x in list(self.body)[before - (1 if sect is not None else 0):] if x.tag != qn("w:sectPr")]
        for x in new:
            el.addprevious(x)
        _remove(el)

    def _table(self, tbl, ctx: Mapping) -> None:
        for tc in tbl.iter(qn("w:tc")):
            self.elements([x for x in tc if x.tag in (qn("w:p"), qn("w:tbl"))], ctx)


def _number_headings(doc) -> None:
    counters = [0] * 9
    for p in doc.paragraphs:
        m = _HEADING.match(p.style.name if p.style is not None else "")
        if not m:
            continue
        level = max(1, int(m.group(1)))
        counters[level - 1] += 1
        for k in range(level, 9):
            counters[k] = 0
        if NUMBER_TOKEN in p.text:
            num = ".".join(str(c) for c in counters[:level]) + "."
            for r in p.runs:
                if NUMBER_TOKEN in r.text:
                    r.text = r.text.replace(NUMBER_TOKEN, num)
                    break
            else:
                full = p.text.replace(NUMBER_TOKEN, num)
                for r in p.runs[1:]:
                    r.text = ""
                p.runs[0].text = full
    for p in doc.paragraphs:   # číslo v ne-nadpisu nemá význam
        if NUMBER_TOKEN in p.text:
            for r in p.runs:
                r.text = r.text.replace(NUMBER_TOKEN, "")


def render(doc, ctx: Mapping, blocks: Mapping[str, BlockFn] | None = None) -> None:
    """Vyplní šablonu `doc` (python-docx Document) na místě."""
    r = _Renderer(doc, blocks or {})
    r.elements([x for x in doc.element.body if x.tag in (qn("w:p"), qn("w:tbl"))], ctx)
    for sec in doc.sections:
        for part in (sec.header, sec.footer, sec.first_page_header, sec.first_page_footer,
                     sec.even_page_header, sec.even_page_footer):
            if part.is_linked_to_previous:
                continue
            r.elements([x for x in part._element if x.tag in (qn("w:p"), qn("w:tbl"))], ctx)
    _number_headings(doc)


def has_markers(doc) -> bool:
    """Šablona obsahuje pole nebo značky (jinak je to jen podkladový dokument se styly)."""
    texts = [p.text for p in doc.paragraphs]
    texts += [c.text for t in doc.tables for row in t.rows for c in row.cells]
    for sec in doc.sections:
        texts += [p.text for p in sec.header.paragraphs] + [p.text for p in sec.footer.paragraphs]
    return any("{{" in t or "{%" in t for t in texts)


# ---- zdroj .md --------------------------------------------------------------------------------------------------
INCLUDE = "@include "
MAX_INCLUDE_DEPTH = 5


def expand_includes(source: str, base: Path | None, depth: int = 0) -> str:
    """Řádek `@include soubor.md` → obsah souboru (relativně k `base`); chybějící soubor → odstavec s chybou."""
    out = []
    for line in source.splitlines():
        if line.strip().startswith(INCLUDE):
            name = line.strip()[len(INCLUDE):].strip()
            path = (base / name) if base is not None else Path(name)
            if depth >= MAX_INCLUDE_DEPTH or not path.is_file():
                out.append(f"[chyba šablony: nelze vložit {name}]")
                continue
            out.append(expand_includes(path.read_text(encoding="utf-8"), path.parent, depth + 1))
        else:
            out.append(line)
    return "\n".join(out)


def markdown_into(doc, source: str, base: Path | None = None) -> None:
    """Připíše do `doc` osnovu ze zjednodušeného Markdownu: `#`…`####` nadpis (`#!` = titul), `- ` odrážka,
    prázdný řádek = konec odstavce, řádek `{% … %}` / `{{tabulka.x}}` = samostatný odstavec, `<!-- … -->` komentář,
    `@include soubor.md` = vložení dalšího zdroje (relativně k `base`)."""
    source = re.sub(r"<!--.*?-->", "", expand_includes(source, base), flags=re.DOTALL)
    buf: list[str] = []

    def flush() -> None:
        if buf:
            doc.add_paragraph(" ".join(buf))
            buf.clear()

    for raw in source.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("#!"):
            flush()
            doc.add_heading(line[2:].strip(), 0)
        elif line.startswith("#"):
            flush()
            level = len(line) - len(line.lstrip("#"))
            doc.add_heading(line[level:].strip(), min(level, 4))
        elif line.startswith("- "):
            flush()
            doc.add_paragraph(line[2:].strip(), style="List Bullet")
        elif _CTRL.match(line) or _BLOCK.match(line):
            flush()
            doc.add_paragraph(line)
        else:
            buf.append(line)
    flush()


def load_template(path: Path | str | None, fallback: Path | str | None = None):
    """Dokument šablony: `.docx` se značkami; `.docx` bez značek = podklad (styly, záhlaví) + osnova ze zdroje
    `fallback` (.md); `.md` = osnova do prázdného dokumentu; None = `fallback`."""
    if path is not None and Path(path).suffix.lower() == ".md":
        doc = Document()
        markdown_into(doc, Path(path).read_text(encoding="utf-8"), Path(path).parent)
        return doc
    doc = Document(str(path)) if path is not None else Document()
    if (path is None or not has_markers(doc)) and fallback is not None:
        markdown_into(doc, Path(fallback).read_text(encoding="utf-8"), Path(fallback).parent)
    return doc
