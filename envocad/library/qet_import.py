"""Import prvků QElectroTech (.elmt, XML) → symboly EnvoCAD. Bez Qt.

QElectroTech má přes 8 000 elektrotechnických značek (IEC 60617) pod licencí CC BY 3.0
(https://qelectrotech.org/wiki/doc/elements_license). Při šíření je nutné uvést autora – importér
zapíše do popisu symbolu „Zdroj: QElectroTech (CC BY 3.0)“ + autora z <informations>.

Formát .elmt: <definition width height hotspot_x hotspot_y> → <description> s primitivy
line / rect / ellipse / circle / arc / polygon / text / dynamic_text / terminal. Jednotky px, Y dolů,
mřížka 10 px. Převod: 10 px → 2,5 mm (SCALE = 0,25), Y převrátit, počátek = hotspot (vztažný bod).

CLI:
    python -m envocad.library.qet_import soubor.elmt [--id ...] [--category ...] -o out.json
    python -m envocad.library.qet_import --dir <složka> --prefix qet.fve --category "QET/Jištění" -o <výstupní složka>
"""
from __future__ import annotations

import argparse
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from envocad.model.symbol import GRID, Attribute, Port, Primitive, Symbol

SCALE = 0.25  # mm / px
ORIENT = {"n": "N", "e": "E", "s": "S", "w": "W"}
IEC_BY_KIND = {"protection": "F", "switch": "Q", "transformer": "T", "generator": "G", "motor": "M",
               "terminal": "X", "relay": "K", "converter": "T", "measurement": "P", "lamp": "E"}


def _f(v: str | None, default: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except ValueError:
        return default


def _snap(v: float) -> float:
    return round(v / GRID) * GRID


class _Conv:
    """Převod souřadnic px (Y dolů, počátek v hotspotu – QET kreslí relativně k hotspotu) → mm (Y nahoru)."""

    def __init__(self, scale: float):
        self.s = scale

    def pt(self, x: float, y: float) -> tuple[float, float]:
        return (round(x * self.s, 3), round(-y * self.s, 3))

    def len(self, v: float) -> float:
        return round(v * self.s, 3)


def _font_size_px(font: str | None) -> float:
    # "Liberation Sans,9,-1,5,50,0,0,0,0,0,Regular" → 9 (pt v QET ≈ px)
    if not font:
        return 9.0
    parts = font.split(",")
    return _f(parts[1], 9.0) if len(parts) > 1 else 9.0


def parse_elmt(path: Path | str, symbol_id: str, category: str = "QET", scale: float = SCALE,
               lang: str = "cs") -> Symbol:
    root = ET.parse(str(path)).getroot()
    if root.tag != "definition":
        raise ValueError("Soubor není prvek QElectroTech (chybí <definition>)")
    c = _Conv(scale)
    names = {n.get("lang", ""): (n.text or "").strip() for n in root.iter("name")}
    name = names.get(lang) or names.get("en") or names.get("fr") or Path(path).stem
    kind = ""
    for ki in root.iter("kindInformation"):
        if ki.get("name") == "type":
            kind = (ki.text or "").strip()
    info = (root.findtext("informations") or "").strip()
    author = ""
    m = re.search(r"Author:\s*(.+)", info)
    if m:
        author = m.group(1).strip()

    prims: list[Primitive] = []
    ports: list[Port] = []
    label_pos: tuple[float, float] | None = None
    desc = root.find("description")
    if desc is None:
        raise ValueError("Prvek nemá <description>")
    for el in desc:
        t = el.tag
        a = el.attrib
        if t == "line":
            x1, y1 = c.pt(_f(a.get("x1")), _f(a.get("y1")))
            x2, y2 = c.pt(_f(a.get("x2")), _f(a.get("y2")))
            prims.append({"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2})
        elif t == "rect":
            x, y = c.pt(_f(a.get("x")), _f(a.get("y")) + _f(a.get("height")))  # levý dolní roh v mm
            prims.append({"type": "rect", "x": x, "y": y, "w": c.len(_f(a.get("width"))), "h": c.len(_f(a.get("height")))})
        elif t in ("ellipse", "circle"):
            if t == "circle":
                d = _f(a.get("diameter"))
                w = h = d
            else:
                w, h = _f(a.get("width")), _f(a.get("height"))
            cx, cy = c.pt(_f(a.get("x")) + w / 2, _f(a.get("y")) + h / 2)
            if abs(w - h) < 1e-6:
                prims.append({"type": "circle", "cx": cx, "cy": cy, "r": c.len(w / 2)})
            else:  # elipsu aproximovat polyline
                rx, ry = c.len(w / 2), c.len(h / 2)
                pts = [[round(cx + rx * math.cos(2 * math.pi * i / 32), 3), round(cy + ry * math.sin(2 * math.pi * i / 32), 3)]
                       for i in range(32)]
                prims.append({"type": "polyline", "points": pts, "closed": True})
        elif t == "arc":
            w, h = _f(a.get("width")), _f(a.get("height"))
            cx, cy = c.pt(_f(a.get("x")) + w / 2, _f(a.get("y")) + h / 2)
            start, span = _f(a.get("start")), _f(a.get("angle"))
            # QET/Qt: úhly proti směru hod. ručiček v Y-dolů systému = po převrácení stejné hodnoty v Y-nahoru
            if abs(w - h) < 1e-6:
                s, e = start, start + span
                if span < 0:
                    s, e = e, s
                prims.append({"type": "arc", "cx": cx, "cy": cy, "r": c.len(w / 2), "start": s % 360, "end": e % 360 or 360})
            else:
                rx, ry = c.len(w / 2), c.len(h / 2)
                n = max(8, int(abs(span) / 10))
                pts = []
                for i in range(n + 1):
                    ang = math.radians(start + span * i / n)
                    pts.append([round(cx + rx * math.cos(ang), 3), round(cy + ry * math.sin(ang), 3)])
                prims.append({"type": "polyline", "points": pts, "closed": False})
        elif t == "polygon":
            pts = []
            i = 1
            while f"x{i}" in a:
                pts.append(list(c.pt(_f(a.get(f"x{i}")), _f(a.get(f"y{i}")))))
                i += 1
            if len(pts) >= 2:
                prims.append({"type": "polyline", "points": pts, "closed": a.get("closed", "true") == "true"})
        elif t == "text":
            txt = (a.get("text") or "").replace("\n", " ").strip()
            if not txt:
                continue
            size = _font_size_px(a.get("font"))
            x, y = c.pt(_f(a.get("x")), _f(a.get("y")))
            prims.append({"type": "text", "x": x, "y": y, "text": txt, "height": round(size * scale * 0.9, 2), "align": "left"})
        elif t == "dynamic_text":
            if el.findtext("info_name") == "label" and label_pos is None:
                label_pos = c.pt(_f(a.get("x")), _f(a.get("y")) + 10)
        elif t == "terminal":
            x, y = c.pt(_f(a.get("x")), _f(a.get("y")))
            pname = (a.get("name") or "").strip() or str(len(ports) + 1)
            if any(p.name == pname for p in ports):
                pname = f"{pname}_{len(ports) + 1}"
            ports.append(Port(pname, _snap(x), _snap(y), ORIENT.get(a.get("orientation", "n"), "N")))

    sym = Symbol(id=symbol_id, name=name, category=category, iec_ref=IEC_BY_KIND.get(kind, ""),
                 description=f"Zdroj: QElectroTech (CC BY 3.0){', autor: ' + author if author else ''}; {Path(path).name}",
                 primitives=prims, ports=ports,
                 attributes=[Attribute("ref", "Označení", "", True), Attribute("type", "Typ", "", True)],
                 label_pos=label_pos or _default_label(sym_bounds(prims, ports)))
    return sym


def sym_bounds(prims, ports):
    return Symbol(id="t", name="t", primitives=prims, ports=ports).bounds()


def _default_label(b) -> tuple[float, float]:
    return (round(b[2] + 2.5, 2), round(b[3], 2))


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "x"


def import_dir(src: Path | str, prefix: str, category: str, out_dir: Path | str, scale: float = SCALE,
               lang: str = "cs", limit: int | None = None) -> list[Path]:
    """Hromadný import složky (rekurzivně). Vrací vytvořené JSON soubory."""
    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for f in sorted(src.rglob("*.elmt")):
        rel = f.relative_to(src)
        sid = f"{prefix}.{slug(str(rel.with_suffix('')).replace('/', '.'))}"
        sub = "/".join(p.split("_", 1)[-1].replace("_", " ") for p in rel.parts[:-1])
        cat = f"{category}/{sub}" if sub else category
        try:
            sym = parse_elmt(f, sid, cat, scale, lang)
        except Exception as ex:  # noqa: BLE001
            print(f"[přeskočeno] {rel}: {ex}", file=sys.stderr)
            continue
        issues = sym.validate()
        if issues:
            print(f"[varování] {rel}: {'; '.join(issues)}", file=sys.stderr)
        out = out_dir / f"{sid}.json"
        sym.to_json(out)
        written.append(out)
        if limit and len(written) >= limit:
            break
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Import prvků QElectroTech do EnvoCAD")
    ap.add_argument("elmt", nargs="?")
    ap.add_argument("--dir", help="hromadně: složka s .elmt")
    ap.add_argument("--id")
    ap.add_argument("--prefix", default="qet")
    ap.add_argument("--category", default="QET")
    ap.add_argument("--scale", type=float, default=SCALE)
    ap.add_argument("--lang", default="cs")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    if a.dir:
        files = import_dir(a.dir, a.prefix, a.category, a.out, a.scale, a.lang)
        print(f"{len(files)} symbolů → {a.out}")
        return 0
    if not a.elmt:
        ap.error("zadejte soubor .elmt nebo --dir")
    sid = a.id or f"{a.prefix}.{slug(Path(a.elmt).stem)}"
    sym = parse_elmt(a.elmt, sid, a.category, a.scale, a.lang)
    sym.to_json(a.out)
    print(f"{sym.name}: {len(sym.primitives)} primitiv, {len(sym.ports)} portů → {a.out}; problémy: {sym.validate() or 'žádné'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
