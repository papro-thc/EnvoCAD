"""Import artiklů z BMEcat (XML, verze 1.2 i 2005) do knihovny EnvoCAD. Bez Qt.

BMEcat je výměnný formát produktových katalogů; výrobci k němu často přidávají klasifikaci ETIM.
Parser (1. krok):
- načte `ARTICLE` (1.2) i `PRODUCT` (2005), jmenné prostory ignoruje,
  čte `T_NEW_CATALOG` i `T_UPDATE_PRODUCTS`,
- vytáhne výrobce, objednací číslo, název, GTIN, odkaz na datasheet a rozměry / hmotnost (v mm a kg),
- ETIM třídu, verzi a vlastnosti uloží jen jako text do `params`
  (`etim_class`, `etim_version`, `etim_features`) –
  mapování ETIM na parametry knihovny (`in_`, `p_loss_w`…) je oborové rozhodnutí a řeší se zvlášť.

XML se čte přes `defusedxml` (bez entit a externích zdrojů; DOCTYPE s odkazem na DTD projde,
DTD se nestahuje).
Všechny artikly dostanou `source=user` a poznámku „import BMEcat – ověřit“. Katalogy se do gitu nedávají.
Rozměry a hmotnost se přijmou jen jako kladné číslo v rozumném rozsahu; nečitelná hodnota → varování.
Záložní hodnoty (výrobce z hlavičky katalogu, číslo dodavatele) hlásí parser souhrnně jedním varováním.

Import do knihovny (`import_bmecat`) nikdy nepřepíše artikl, který nevznikl importem BMEcat (klíč výrobce +
objednací číslo, bez ohledu na id): přeskočí ho. Dřívější import BMEcat aktualizuje pod jeho id a zachová
`symbol_id`, `footprint_id` a cenu; id obsazené jiným artiklem se obejde příponou `-2`, `-3`…

CLI:
    python -m envocad.library.bmecat_import katalog.xml [-o out.csv] [--dump]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, iterparse

from envocad.library.components import REQUIRED, Component
from envocad.library.eplan_import import _norm, guess_category
from envocad.library.store import LibraryStore

NOTE = "import BMEcat – ověřit"
ARTICLE_TAGS = {"ARTICLE", "PRODUCT"}

# rozměry a hmotnost: klíč parametru → (kategorie jednotky, názvy vlastností bez diakritiky, malými písmeny)
_FEATURE_NAMES = {
    "width_mm": ("len", {"sirka", "breite", "width"}),
    "height_mm": ("len", {"vyska", "hohe", "height"}),
    "depth_mm": ("len", {"hloubka", "tiefe", "depth"}),
    "weight_kg": ("mass", {"hmotnost", "gewicht", "weight"}),
}
# jednotka (malými písmeny; zkratky i kódy UN/ECE) → násobek do mm, resp. kg
_UNITS = {
    "len": {"mm": Decimal(1), "mmt": Decimal(1), "cm": Decimal(10), "cmt": Decimal(10),
            "m": Decimal(1000), "mtr": Decimal(1000)},
    "mass": {"kg": Decimal(1), "kgm": Decimal(1), "g": Decimal("0.001"), "grm": Decimal("0.001")},
}
# UDX.EDXF.*: rozměry v metrech, hmotnost v kg
_UDX = {"UDX.EDXF.NETWIDTH": ("width_mm", Decimal(1000)), "UDX.EDXF.NETLENGTH": ("height_mm", Decimal(1000)),
        "UDX.EDXF.NETDEPTH": ("depth_mm", Decimal(1000)), "UDX.EDXF.NETWEIGHT": ("weight_kg", Decimal(1))}


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _kids(el, name: str):
    return [c for c in el if _local(c.tag) == name]


def _text(el, name: str) -> str:
    """Text prvního přímého potomka `name` (ořezaný), jinak prázdný řetězec."""
    for c in _kids(el, name):
        return (c.text or "").strip()
    return ""


def _fmt(d: Decimal) -> str:
    """Decimal → řetězec bez exponentu a bez zbytečných nul („85“, „52.5“, „0.012“)."""
    return format(d.normalize(), "f")


def _to_decimal(text: str) -> Decimal | None:
    try:
        d = Decimal((text or "").strip().replace(",", "."))
    except ArithmeticError:     # InvalidOperation
        return None
    return d if d.is_finite() else None


_MAX_VALUE = Decimal(1_000_000)     # největší věrohodný rozměr (mm) / hmotnost (kg)
_MIN_VALUE = Decimal("1e-6")        # menší hodnota by dala nesmyslně dlouhý řetězec


def _measure(raw: str, factor: Decimal, label: str, warns: list[str], pn: str) -> str | None:
    """Rozměr / hmotnost `raw` × `factor` jako řetězec; prázdná hodnota a 0 se zahodí tiše, nečitelná nebo
    nevěrohodná (záporná, přes 1 000 000, přetečení) se zahodí s varováním."""
    raw = (raw or "").strip()
    if not raw:
        return None
    d = _to_decimal(raw)
    if d is not None and d == 0:
        return None
    value = None
    if d is not None:
        try:
            value = d * factor
        except ArithmeticError:     # Overflow u 1E+999999
            value = None
    if value is None or not _MIN_VALUE <= value <= _MAX_VALUE:
        warns.append(f"Artikl {pn}: hodnota „{raw[:40]}“ u {label} není čitelné kladné číslo"
                     " v rozumném rozsahu – nepoužila se")
        return None
    return _fmt(value)


def _slug(text: str) -> str:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9._+-]+", "-", s).strip("-._+")


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _dimensions(art, warns: list[str], pn: str) -> dict[str, str]:
    out: dict[str, str] = {}
    # a) UDX.EDXF.* (metry / kg) – má přednost
    for ext in (c for c in art if _local(c.tag) == "USER_DEFINED_EXTENSIONS"):
        for c in ext:
            key = _local(c.tag).upper()
            if key not in _UDX or _UDX[key][0] in out:
                continue
            val = _measure(c.text or "", _UDX[key][1], key, warns, pn)
            if val is not None:
                out[_UDX[key][0]] = val
    # b) vlastnosti mimo ETIM
    for grp in (c for c in art if _local(c.tag) in ("ARTICLE_FEATURES", "PRODUCT_FEATURES")):
        if _text(grp, "REFERENCE_FEATURE_SYSTEM_NAME").upper().startswith("ETIM"):
            continue
        for feat in _kids(grp, "FEATURE"):
            n = _norm(_text(feat, "FNAME"))
            hit = next((k for k, (_, names) in _FEATURE_NAMES.items() if n in names), None)
            if hit is None or hit in out:
                continue
            kind = _FEATURE_NAMES[hit][0]
            unit = _text(feat, "FUNIT")
            factor = _UNITS[kind].get(unit.lower())
            if factor is None:
                warns.append(f"Artikl {pn}: neznámá jednotka „{unit}“ u vlastnosti „{_text(feat, 'FNAME')}“"
                             " – hodnota se nepoužila")
                continue
            val = _measure(_text(feat, "FVALUE"), factor, f"vlastnosti „{_text(feat, 'FNAME')}“", warns, pn)
            if val is not None:
                out[hit] = val
    return out


def _etim(art, warns: list[str], pn: str) -> dict[str, str]:
    groups = [g for g in art if _local(g.tag) in ("ARTICLE_FEATURES", "PRODUCT_FEATURES")
              and _text(g, "REFERENCE_FEATURE_SYSTEM_NAME").upper().startswith("ETIM")]
    if len(groups) > 1:
        warns.append(f"Artikl {pn}: více skupin ETIM ({len(groups)}) – použita první, další se ignorují")
    for grp in groups[:1]:
        system = _text(grp, "REFERENCE_FEATURE_SYSTEM_NAME")
        feats = []
        for feat in _kids(grp, "FEATURE"):
            item: dict = {"f": _text(feat, "FNAME"),
                          "v": [(v.text or "").strip() for v in _kids(feat, "FVALUE")]}
            if _text(feat, "FUNIT"):
                item["u"] = _text(feat, "FUNIT")
            feats.append(item)
        out = {"etim_class": _text(grp, "REFERENCE_FEATURE_GROUP_ID"),
               "etim_version": re.sub(r"^ETIM[\s_-]*", "", system, flags=re.IGNORECASE).strip(),
               "etim_features": json.dumps(feats, ensure_ascii=False)}
        return {k: v for k, v in out.items() if v}
    return {}


def _datasheet(art, warns: list[str], pn: str) -> str:
    found = ""
    for el in art.iter():
        tag = _local(el.tag)
        if tag == "MIME":
            if _text(el, "MIME_PURPOSE").lower() != "data_sheet":
                continue
            src = _text(el, "MIME_SOURCE")
        elif tag == "UDX.EDXF.MIME":
            if _text(el, "UDX.EDXF.MIME_CODE").upper() != "MD22":
                continue
            src = _text(el, "UDX.EDXF.MIME_SOURCE")
        else:
            continue
        if not src:
            continue
        if re.fullmatch(r"https?://[^\s\"'<>]+", src, re.IGNORECASE):
            found = found or src
        else:
            warns.append(f"Artikl {pn}: odkaz na datasheet „{src[:80]}“ není platný http(s) odkaz"
                         " – nepoužil se")
    return found


def _gtin(details) -> str:
    if details is None:
        return ""
    if _text(details, "EAN"):
        return _text(details, "EAN")
    for c in _kids(details, "INTERNATIONAL_PID"):
        if (c.get("type") or "").lower() in ("ean", "gtin") and (c.text or "").strip():
            return c.text.strip()
    return ""


def _convert(art, header_supplier: str, warns: list[str],
             fallbacks: dict[str, int]) -> tuple[Component, tuple[str, str]] | None:
    kind = _local(art.tag)
    details = next(iter(_kids(art, "ARTICLE_DETAILS" if kind == "ARTICLE" else "PRODUCT_DETAILS")), None)
    aid, mid = (("SUPPLIER_AID", "MANUFACTURER_AID") if kind == "ARTICLE"
                else ("SUPPLIER_PID", "MANUFACTURER_PID"))
    pn = _text(details, mid) if details is not None else ""
    if not pn:
        pn = _text(art, aid)
        if pn:
            fallbacks["pn"] += 1
    short = _text(details, "DESCRIPTION_SHORT") if details is not None else ""
    gtin = _gtin(details)
    if not pn:
        ident = short or gtin or "bez názvu"
        warns.append(f"Artikl „{ident}“ nemá objednací číslo – přeskočeno")
        return None
    mfr = _text(details, "MANUFACTURER_NAME") if details is not None else ""
    if not mfr:
        mfr = header_supplier
        if not mfr:
            warns.append(f"Artikl {pn}: chybí výrobce (ani v hlavičce katalogu) – přeskočeno")
            return None
        fallbacks["mfr"] += 1
    if not short:
        warns.append(f"Artikl {pn}: chybí název, použito objednací číslo")
    name = short or pn
    params: dict[str, str] = {}
    if gtin:
        params["gtin"] = gtin
    params.update(_dimensions(art, warns, pn))
    params.update(_etim(art, warns, pn))
    params["note"] = NOTE
    cid = _slug(f"{mfr}-{pn}")
    if not re.match(r"[a-z0-9]", cid):     # např. jen ne-latinkové znaky
        cid = "bmecat-" + hashlib.sha1(f"{mfr}|{pn}".encode()).hexdigest()[:10]
    comp = Component(id=cid, manufacturer=mfr, part_number=pn, name=name,
                     category=guess_category(name, _ascii(name), pn), symbol_id="",
                     datasheet_url=_datasheet(art, warns, pn), source="user", params=params)
    return comp, (mfr.strip().casefold(), pn.strip().casefold())


def parse_bmecat(path: Path | str) -> tuple[list[Component], list[str]]:
    """BMEcat 1.2 / 2005 → (artikly, česká varování). Neplatný soubor → `ValueError`."""
    path = Path(path)
    comps: list[Component] = []
    warns: list[str] = []
    seen: set[tuple[str, str]] = set()
    ids: set[str] = set()
    header_supplier = ""
    root_checked = False
    fallbacks = {"mfr": 0, "pn": 0}
    stack: list = []        # otevřené prvky: zpracovaný artikl se z rodiče odebere (paměť u velkých katalogů)
    try:
        for event, el in iterparse(str(path), events=("start", "end")):
            tag = _local(el.tag)
            if event == "start":
                stack.append(el)
                if not root_checked:
                    root_checked = True
                    if tag != "BMECAT":
                        raise ValueError(f"Soubor {path.name} není BMEcat (kořenový prvek je „{tag}“, "
                                         "čekám BMECAT)")
                continue
            stack.pop()
            parent = stack[-1] if stack else None
            if tag == "HEADER":
                for sup in _kids(el, "SUPPLIER"):
                    header_supplier = header_supplier or _text(sup, "SUPPLIER_NAME")
                el.clear()
            elif tag in ARTICLE_TAGS:
                res = _convert(el, header_supplier, warns, fallbacks)
                el.clear()
                if parent is not None:
                    parent.remove(el)
                if res is None:
                    continue
                comp, key = res
                if key in seen:
                    warns.append(f"Artikl {comp.part_number} ({comp.manufacturer}): duplicitní záznam"
                                 " v souboru – použit jen první")
                    continue
                seen.add(key)
                base, n = comp.id, 1
                while comp.id in ids:   # různé artikly se stejným zjednodušeným id
                    n += 1
                    comp.id = f"{base}-{n}"
                ids.add(comp.id)
                comps.append(comp)
    except DefusedXmlException as ex:      # je podtřída ValueError, proto první
        raise ValueError(f"Soubor {path.name} obsahuje nepovolenou konstrukci XML (entity / externí zdroje): "
                         f"{type(ex).__name__}") from ex
    except ValueError:
        raise
    except ParseError as ex:
        raise ValueError(f"Soubor {path.name} není platné XML: {ex}") from ex
    except OSError as ex:
        raise ValueError(f"Soubor {path.name} nejde přečíst: {ex.strerror or ex}") from ex
    if not root_checked:
        raise ValueError(f"Soubor {path.name} je prázdný")
    if fallbacks["mfr"]:
        warns.append(f"U {fallbacks['mfr']} artiklů chybí MANUFACTURER_NAME – výrobce převzat z hlavičky"
                     f" katalogu (dodavatel „{header_supplier}“) – ověřit")
    if fallbacks["pn"]:
        warns.append(f"U {fallbacks['pn']} artiklů chybí objednací číslo výrobce – použito číslo dodavatele "
                     "– ověřit")
    return comps, warns


def write_components_csv(components: list[Component], out: Path | str) -> int:
    """CSV v2 (`docs/COMPONENTS.md`, oddělovač `;`): povinné sloupce, `footprint_id`, `price_czk`
    a sjednocení klíčů `params`."""
    fixed = REQUIRED + ["footprint_id", "price_czk"]
    extra = sorted({k for c in components for k in c.params} - set(fixed))
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(fixed + extra)
        for c in components:
            base = {"id": c.id, "manufacturer": c.manufacturer, "part_number": c.part_number, "name": c.name,
                    "category": c.category, "symbol_id": c.symbol_id, "datasheet_url": c.datasheet_url,
                    "source": c.source, "footprint_id": c.footprint_id,
                    "price_czk": "" if c.price is None else repr(c.price)}
            w.writerow([base[k] for k in fixed] + [c.params.get(k, "") for k in extra])
    return len(components)


@dataclass
class BmecatImport:
    imported: int = 0           # zapsáno do knihovny (nové + aktualizované dřívější import BMEcat)
    skipped: int = 0            # artikly (výrobce, objednací číslo) už v knihovně z jiného zdroje
    warnings: list[str] = field(default_factory=list)
    csv_path: Path | None = None


def _key(c: Component) -> tuple[str, str]:
    return (c.manufacturer.strip().casefold(), c.part_number.strip().casefold())


def import_bmecat(store: LibraryStore, path: Path | str, out_dir: Path | str) -> BmecatImport:
    """Naparsuje BMEcat a zapíše artikly do `out_dir/<stem>.csv` i do knihovny. Artikl, který v knihovně už je
    (stejný výrobce + objednací číslo) a nevznikl importem BMEcat, se přeskočí. Artikl z dřívějšího importu se
    aktualizuje pod svým id (`symbol_id`, `footprint_id` a cena zůstanou). Nový artikl s id obsazeným jiným
    artiklem dostane příponu `-2`, `-3`… Chyba parseru (`ValueError`) knihovnu nezmění."""
    path = Path(path)
    comps, warns = parse_bmecat(path)
    by_key: dict[tuple[str, str], list[Component]] = {}
    used: set[str] = set()
    for ex in store.components():
        by_key.setdefault(_key(ex), []).append(ex)
        used.add(ex.id)
    res = BmecatImport(warnings=list(warns))
    todo: list[Component] = []
    for c in comps:
        rows = by_key.get(_key(c), [])
        foreign = next((r for r in rows if NOTE not in r.params.get("note", "")), None)
        if foreign is not None:
            res.skipped += 1
            res.warnings.append(f"Artikl {c.part_number} ({c.manufacturer}) už v knihovně je"
                                f" (id {foreign.id}) – přeskočeno")
        elif rows:      # dřívější import BMEcat: aktualizace pod jeho id, přiřazení uživatele zůstane
            old = rows[0]
            c.id, c.symbol_id, c.footprint_id, c.price = old.id, old.symbol_id, old.footprint_id, old.price
            todo.append(c)
        else:
            base, n = c.id, 1
            while c.id in used:
                n += 1
                c.id = f"{base}-{n}"
            used.add(c.id)
            todo.append(c)
    if todo:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        res.csv_path = out_dir / f"{path.stem}.csv"
        write_components_csv(todo, res.csv_path)
        res.imported = store.import_components_csv_v2(res.csv_path)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="BMEcat (XML) → CSV artiklů EnvoCAD")
    ap.add_argument("xml", help="soubor BMEcat 1.2 nebo 2005")
    ap.add_argument("-o", "--out", help="výstupní CSV (výchozí <název>.csv v aktuální složce)")
    ap.add_argument("--dump", action="store_true", help="jen vypsat, co se našlo; nic nezapisovat")
    a = ap.parse_args(argv)
    try:
        comps, warns = parse_bmecat(a.xml)
    except ValueError as ex:
        print(f"Chyba: {ex}", file=sys.stderr)
        return 1
    for w in warns:
        print(f"Varování: {w}", file=sys.stderr)
    if a.dump:
        for c in comps:
            print(f"{c.id}\t{c.category}\t{c.manufacturer}\t{c.part_number}\t{c.name}\t"
                  + json.dumps({k: v for k, v in c.params.items() if k not in ("note", "etim_features")},
                               ensure_ascii=False))
        print(f"{len(comps)} artiklů, {len(warns)} varování")
        return 0
    out = Path(a.out) if a.out else Path(Path(a.xml).stem + ".csv")
    print(f"Zapsáno {write_components_csv(comps, out)} artiklů do {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
