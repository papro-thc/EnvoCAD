"""Import dat z EPLAN exportů do knihovny EnvoCAD. Bez Qt.

Podporované vstupy (vše jsou soubory, které si uživatel stáhne sám svým účtem – program nic nestahuje):

1. **Obchodní data z EPLAN Data Portal** – CSV („Download commercial data“). Sloupce se liší podle verze
   portálu, proto se mapují heuristicky podle názvů (viz COLUMN_HINTS) a `--dump` ukáže, co se našlo.
2. **Export artiklů z EPLAN P8** – XML (Správa artiklů → Export), elementy s atributy `P_ARTICLE_*`.
3. **DXF balíček z Data Portalu** – ZIP s DXF pohledy přístrojů → footprinty (symboly v mm pro rozložení).
4. **EDZ** – ZIP; obsahuje XML artiklů (jako 2) a makra; projde se jako (2) + (3).

Výstup: CSV ve formátu `docs/COMPONENTS.md` (+ JSON footprinty). Vždy zkontrolujte výstup `--dump`
na reálném souboru – formát EPLANu se mění a mapování je záměrně tolerantní.

Pozn. k licenci: data z Data Portalu podléhají podmínkám EPLAN/ePulse; pro ostrou knihovnu preferujte
ETIM/BMEcat a PDF katalogy výrobců (viz docs/SOURCES.md).

CLI:
    python -m envocad.library.eplan_import commercial.csv -o out.csv [--dump]
    python -m envocad.library.eplan_import parts.xml -o out.csv [--dump]
    python -m envocad.library.eplan_import makra.zip --footprints <složka> [--scale 1.0]
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import zipfile
from pathlib import Path

from envocad.library.components import REQUIRED

# cílový sloupec → kandidáti názvů ve zdroji (porovnává se bez diakritiky, malými písmeny, bez mezer/podtržítek)
COLUMN_HINTS: dict[str, list[str]] = {
    "part_number": ["partnumber", "partno", "articlenumber", "p_article_partnr", "artikelnummer", "ordernumber",
                    "ordernr", "p_article_ordernr", "objednacicislo"],
    "manufacturer": ["manufacturer", "p_article_manufacturer", "hersteller", "vyrobce"],
    "name": ["description", "designation", "p_article_descr1", "bezeichnung", "popis", "name"],
    "type_number": ["typenumber", "typenr", "p_article_typenr", "typ"],
    "width_mm": ["width", "p_article_width", "breite", "sirka"],
    "height_mm": ["height", "p_article_height", "hoehe", "vyska"],
    "depth_mm": ["depth", "p_article_depth", "tiefe", "hloubka"],
    "un_v": ["voltage", "ratedvoltage", "p_article_voltage", "nennspannung", "napeti"],
    "in_": ["current", "ratedcurrent", "p_article_current", "nennstrom", "proud"],
    "p_loss_w": ["powerdissipation", "powerloss", "p_article_powerdissipation", "verlustleistung", "ztratovyvykon"],
    "price_czk": ["price", "p_article_price", "preis", "cena"],
    "datasheet_url": ["datasheet", "url", "p_article_url", "link", "weblink"],
    "macro": ["macro", "p_article_macro", "graphicmacro", "makro"],
    "weight_kg": ["weight", "p_article_weight", "gewicht", "hmotnost"],
    "group": ["productgroup", "p_article_productgroup", "produktgruppe", "category", "group"],
    "etim": ["etim", "etimclass", "p_article_etimclass"],
    "gtin": ["gtin", "ean"],
}

GROUP_TO_CATEGORY = [
    (r"leitungsschutz|miniature circuit|mcb|jisti", "mcb"), (r"leistungsschalter|moulded|mccb", "mccb"),
    (r"fehlerstrom|residual|rcd|rccb|chrani", "rcd"), (r"rcbo", "rcbo"), (r"berspannung|surge|spd|svodi", "spd"),
    (r"sicherung|fuse|pojist", "fuse"), (r"sch[uü]tz|contactor|styka", "contactor"),
    (r"lasttrenn|disconnect|switch|odp[ií]na|vyp[ií]na", "switch"), (r"klemm|terminal|svork", "terminal"),
    (r"geh[aä]use|enclosure|schrank|cabinet|rozvad|skr[ií]", "enclosure"), (r"z[aä]hler|meter|elektrom", "meter"),
    (r"wechselrichter|inverter|st[rř][ií]da", "inverter"), (r"batter|akku|speicher|bess", "battery"),
    (r"relais|relay|rel[eé]", "relay"),
]


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def map_columns(header: list[str]) -> dict[str, str]:
    """cílový sloupec → název zdrojového sloupce (podle nápověd)."""
    norm = {_norm(h): h for h in header}
    out: dict[str, str] = {}
    for target, hints in COLUMN_HINTS.items():
        for hint in (_norm(h) for h in hints):
            for n, orig in norm.items():
                if n == hint or (len(hint) > 5 and hint in n):
                    out.setdefault(target, orig)
                    break
            if target in out:
                break
    return out


def guess_category(*texts: str) -> str:
    blob = " ".join(t or "" for t in texts).lower()
    for pat, cat in GROUP_TO_CATEGORY:
        if re.search(pat, blob):
            return cat
    return "other"


def _num(v: str) -> str:
    v = re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d{3}(?!\d))", "", v or "")   # „1 234,50“ – mezera odděluje tisíce
    m = re.search(r"-?\d+(?:[.,]\d+)?", v)
    return m.group(0).replace(",", ".") if m else ""


def rows_from_commercial_csv(path: Path | str) -> tuple[list[dict], dict[str, str]]:
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    delim = ";" if text.splitlines()[0].count(";") >= text.splitlines()[0].count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    mapping = map_columns(reader.fieldnames or [])
    rows = [_convert(r, mapping, "user") for r in reader]
    return [r for r in rows if r], mapping


def rows_from_parts_xml(path: Path | str) -> tuple[list[dict], dict[str, str]]:
    import xml.etree.ElementTree as ET
    root = ET.parse(str(path)).getroot()
    parts = [el for el in root.iter() if any(k.upper().startswith("P_ARTICLE") for k in el.attrib)]
    if not parts:
        return [], {}
    header = sorted({k for el in parts for k in el.attrib})
    mapping = map_columns(header)
    rows = [_convert(dict(el.attrib), mapping, "user") for el in parts]
    return [r for r in rows if r], mapping


def _convert(src: dict, mapping: dict[str, str], source: str) -> dict | None:
    """source='user' – bez povinného datasheet_url (EPLAN exporty odkaz často nemají); ověřit ručně."""
    g = lambda k: (src.get(mapping[k]) or "").strip() if k in mapping else ""
    pn = g("part_number") or g("type_number")
    mfr = g("manufacturer")
    if not pn:
        return None
    cat = guess_category(g("group"), g("name"), g("etim"), pn)
    row = {
        "id": re.sub(r"[^a-z0-9._+-]+", "-", f"{mfr}-{pn}".lower()).strip("-"),
        "manufacturer": mfr, "part_number": pn, "name": g("name") or g("type_number") or pn, "category": cat,
        "symbol_id": "", "footprint_id": "", "datasheet_url": g("datasheet_url"), "source": source,
        "price_czk": _num(g("price_czk")), "in_": _num(g("in_")), "un_v": _num(g("un_v")),
        "width_mm": _num(g("width_mm")), "height_mm": _num(g("height_mm")), "depth_mm": _num(g("depth_mm")),
        "p_loss_w": _num(g("p_loss_w")),
        "note": "; ".join(x for x in (f"makro {g('macro')}" if g("macro") else "", f"ETIM {g('etim')}" if g("etim") else "",
                                      f"GTIN {g('gtin')}" if g("gtin") else "", "import EPLAN – ověřit") if x),
    }
    # moduly odvodit ze šířky (17,5 mm na modul), jen u modulových přístrojů
    try:
        w = float(row["width_mm"]) if row["width_mm"] else 0
        if cat in ("mcb", "rcd", "rcbo", "spd", "switch", "contactor", "meter", "relay") and 8 < w < 400:
            row["modules"] = f"{round(w / 17.5 * 2) / 2:g}"
    except ValueError:
        pass
    return row


def write_components_csv(rows: list[dict], out: Path | str) -> int:
    cols = REQUIRED + ["footprint_id", "price_czk", "in_", "un_v", "modules", "width_mm", "height_mm", "depth_mm",
                       "p_loss_w", "note"]
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return len(rows)


def footprints_from_zip(zip_path: Path | str, out_dir: Path | str, prefix: str = "fp.eplan", scale: float = 1.0) -> list[Path]:
    """DXF soubory v ZIP (Data Portal „DXF data“ nebo EDZ) → footprinty (symboly v mm)."""
    from envocad.library.dxf_import import import_dxf
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if not info.filename.lower().endswith(".dxf"):
                continue
            tmp = out_dir / Path(info.filename).name
            tmp.write_bytes(z.read(info))
            sid = f"{prefix}.{re.sub(r'[^a-z0-9]+', '-', Path(info.filename).stem.lower()).strip('-')}"
            try:
                sym = import_dxf(tmp, sid, Path(info.filename).stem, None, scale, center=False, snap=True,
                                 category="Rozložení/EPLAN")
            except Exception as ex:  # noqa: BLE001
                print(f"[přeskočeno] {info.filename}: {ex}", file=sys.stderr)
                continue
            finally:
                tmp.unlink(missing_ok=True)
            out = out_dir / f"{sid}.json"
            sym.to_json(out)
            written.append(out)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Import EPLAN exportů do knihovny EnvoCAD")
    ap.add_argument("src")
    ap.add_argument("-o", "--out")
    ap.add_argument("--footprints", help="složka pro JSON footprinty (vstup ZIP/EDZ)")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--dump", action="store_true", help="vypsat mapování sloupců a první řádky")
    a = ap.parse_args(argv)
    src = Path(a.src)
    if src.suffix.lower() in (".zip", ".edz"):
        if not a.footprints:
            ap.error("pro ZIP/EDZ zadejte --footprints <složka>")
        files = footprints_from_zip(src, a.footprints, scale=a.scale)
        print(f"{len(files)} footprintů → {a.footprints}")
        # XML artiklů uvnitř EDZ
        with zipfile.ZipFile(src) as z:
            xmls = [n for n in z.namelist() if n.lower().endswith(".xml")]
        if xmls and a.out:
            rows_all = []
            with zipfile.ZipFile(src) as z:
                for n in xmls:
                    tmp = Path(a.footprints) / "_tmp.xml"
                    tmp.write_bytes(z.read(n))
                    rows, mapping = rows_from_parts_xml(tmp)
                    tmp.unlink()
                    rows_all += rows
            print(f"{write_components_csv(rows_all, a.out)} artiklů → {a.out}")
        return 0
    if src.suffix.lower() == ".xml":
        rows, mapping = rows_from_parts_xml(src)
    else:
        rows, mapping = rows_from_commercial_csv(src)
    if a.dump or not a.out:
        print("Mapování sloupců:")
        for k, v in mapping.items():
            print(f"  {k:14s} ← {v}")
        print(f"Načteno {len(rows)} řádků; ukázka:")
        for r in rows[:3]:
            print("  ", {k: v for k, v in r.items() if v})
    if a.out:
        print(f"{write_components_csv(rows, a.out)} artiklů → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
