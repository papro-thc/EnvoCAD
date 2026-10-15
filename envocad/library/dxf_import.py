"""Import symbolu z DXF (knihovny výrobců) → Symbol. Bez Qt.

Podporované entity: LINE, CIRCLE, ARC, LWPOLYLINE, POLYLINE, TEXT, MTEXT, INSERT (rekurzivně, bloky).
Vše se promítne do 2D, volitelně přeškáluje a vycentruje. Porty se doplňují ručně.

CLI:
    python -m envocad.library.dxf_import soubor.dxf --id fve.xyz --name "XYZ" [--block NAZEV]
        [--scale 1.0] [--center] [--snap] -o out.json
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import ezdxf
from ezdxf.math import Matrix44, Vec3

from envocad.model.symbol import GRID, Primitive, Symbol


def _snap(v: float, grid: float) -> float:
    return round(v / grid) * grid


def _entities_to_primitives(entities, m: Matrix44, out: list[Primitive], doc, depth: int = 0) -> None:
    if depth > 8:
        return
    for e in entities:
        t = e.dxftype()
        try:
            if t == "LINE":
                a = m.transform(e.dxf.start)
                b = m.transform(e.dxf.end)
                out.append({"type": "line", "x1": a.x, "y1": a.y, "x2": b.x, "y2": b.y})
            elif t == "CIRCLE":
                c = m.transform(e.dxf.center)
                r = e.dxf.radius * _scale_of(m)
                out.append({"type": "circle", "cx": c.x, "cy": c.y, "r": r})
            elif t == "ARC":
                c = m.transform(e.dxf.center)
                r = e.dxf.radius * _scale_of(m)
                rot = _rotation_of(m)
                out.append({"type": "arc", "cx": c.x, "cy": c.y, "r": r,
                            "start": e.dxf.start_angle + rot, "end": e.dxf.end_angle + rot})
            elif t in ("LWPOLYLINE", "POLYLINE"):
                pts = []
                if t == "LWPOLYLINE":
                    raw = [(p[0], p[1]) for p in e.get_points()]
                else:
                    raw = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
                for x, y in raw:
                    p = m.transform(Vec3(x, y, 0))
                    pts.append([p.x, p.y])
                if len(pts) >= 2:
                    out.append({"type": "polyline", "points": pts, "closed": bool(e.closed)})
            elif t in ("TEXT", "MTEXT"):
                pos = m.transform(e.dxf.insert)
                text = e.plain_text() if t == "MTEXT" else e.dxf.text
                h = (e.dxf.char_height if t == "MTEXT" else e.dxf.height) * _scale_of(m)
                out.append({"type": "text", "x": pos.x, "y": pos.y, "text": text, "height": h, "align": "left"})
            elif t == "INSERT":
                blk = doc.blocks.get(e.dxf.name)
                if blk is None:
                    continue
                sub = Matrix44.chain(
                    Matrix44.scale(e.dxf.xscale, e.dxf.yscale, 1),
                    Matrix44.z_rotate(math.radians(e.dxf.rotation)),
                    Matrix44.translate(e.dxf.insert.x - blk.base_point.x, e.dxf.insert.y - blk.base_point.y, 0),
                    m,
                )
                _entities_to_primitives(blk, sub, out, doc, depth + 1)
        except Exception:  # noqa: BLE001 – vadná entita nesmí shodit celý import
            continue


def _scale_of(m: Matrix44) -> float:
    v = m.transform_direction(Vec3(1, 0, 0))
    return math.hypot(v.x, v.y)


def _rotation_of(m: Matrix44) -> float:
    v = m.transform_direction(Vec3(1, 0, 0))
    return math.degrees(math.atan2(v.y, v.x))


def import_dxf(path: Path | str, symbol_id: str, name: str, block: str | None = None,
               scale: float = 1.0, center: bool = True, snap: bool = False,
               category: str = "Import", iec_ref: str = "") -> Symbol:
    doc = ezdxf.readfile(str(path))
    source = doc.blocks.get(block) if block else doc.modelspace()
    if source is None:
        raise ValueError(f"Blok {block!r} v DXF není")
    prims: list[Primitive] = []
    _entities_to_primitives(source, Matrix44.scale(scale, scale, 1), prims, doc)

    sym = Symbol(id=symbol_id, name=name, category=category, iec_ref=iec_ref, primitives=prims)
    if center and prims:
        x0, y0, x1, y1 = sym.bounds()
        dx, dy = -(x0 + x1) / 2, -(y0 + y1) / 2
        if snap:
            dx, dy = _snap(dx, GRID), _snap(dy, GRID)
        _translate(prims, dx, dy)
    if snap:
        _round_all(prims)
    return sym


def _translate(prims: list[Primitive], dx: float, dy: float) -> None:
    for p in prims:
        t = p["type"]
        if t == "line":
            p["x1"] += dx; p["y1"] += dy; p["x2"] += dx; p["y2"] += dy
        elif t == "rect":
            p["x"] += dx; p["y"] += dy
        elif t in ("circle", "arc"):
            p["cx"] += dx; p["cy"] += dy
        elif t == "polyline":
            p["points"] = [[x + dx, y + dy] for x, y in p["points"]]
        elif t == "text":
            p["x"] += dx; p["y"] += dy


def _round_all(prims: list[Primitive], nd: int = 3) -> None:
    for p in prims:
        for k, v in list(p.items()):
            if isinstance(v, float):
                p[k] = round(v, nd)
            elif k == "points":
                p[k] = [[round(x, nd), round(y, nd)] for x, y in v]


def list_blocks(path: Path | str) -> list[str]:
    doc = ezdxf.readfile(str(path))
    return [b.name for b in doc.blocks if not b.name.startswith("*")]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Import symbolu z DXF do formátu EnvoCAD")
    ap.add_argument("dxf")
    ap.add_argument("--id", required=False)
    ap.add_argument("--name", required=False)
    ap.add_argument("--block", help="název bloku (jinak modelspace)")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--no-center", action="store_true")
    ap.add_argument("--snap", action="store_true", help="zaokrouhlit souřadnice")
    ap.add_argument("--list-blocks", action="store_true")
    ap.add_argument("-o", "--out")
    a = ap.parse_args(argv)
    if a.list_blocks:
        print("\n".join(list_blocks(a.dxf)))
        return
    if not a.id or not a.name:
        ap.error("--id a --name jsou povinné")
    sym = import_dxf(a.dxf, a.id, a.name, a.block, a.scale, not a.no_center, a.snap)
    out = a.out or f"{a.id}.json"
    sym.to_json(out)
    print(f"{len(sym.primitives)} primitiv → {out}")


if __name__ == "__main__":
    main()
