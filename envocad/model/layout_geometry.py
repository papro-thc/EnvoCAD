"""Geometrie rozložení rozvaděče (bez Qt): skříň, DIN lišty, přístroje, texty – mm, Y nahoru.

Zdroj pro export DXF (`export/dxf_export.export_layout_dxf`); stejné rozměry a vzájemné polohy kreslí GUI
(`ui/layout_view.py`, scéna má Y dolů a počátek s odstupem `MARGIN`; zde je `y_model = -y_scény`). Generická
kresba přístroje (dělení svorek, páka a svorky boxu, páčky modulového přístroje) odpovídá `DeviceItem._paint_generic`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from envocad.model.device_size import SHAPE_BOX, SHAPE_TERMINAL, DeviceSize, device_size
from envocad.model.project import DEVICE_HEIGHT_MM, MODULE_WIDTH, Element, Project, Sheet, terminal_count

ROW_H = 90.0            # mm – výška řady (přístroj + prostor na vodiče)
MARGIN = 20.0           # odstup skříně od počátku scény
UNPLACED_X_GAP = 30.0   # mezera mezi skříní a sloupcem nerozmístěných přístrojů
UNPLACED_Y_GAP = 8.0    # mezera mezi nerozmístěnými přístroji pod sebou
RAIL_H = 35.0           # výška DIN lišty (pásu v rozložení)

Rect = tuple[float, float, float, float]            # (x, y, w, h), levý dolní roh
Text = tuple[float, float, str, float, str]         # (x, y, text, výška, zarovnání)


def device_width_mm(size: DeviceSize) -> float:
    """Šířka přístroje v rozložení: skutečný rozměr (nejméně 1 mm), jinak moduly (nejméně 1 modul)."""
    return max(size.width_mm, 1.0) if size.real else max(size.modules, 1.0) * MODULE_WIDTH


@dataclass
class LayoutDevice:
    """Přístroj v rozložení: obrys `x, y, w, h` (levý dolní roh), texty a generická kresba (absolutní mm)."""
    element_id: str
    ref: str
    x: float
    y: float
    w: float
    h: float
    placed: bool
    texts: list[Text] = field(default_factory=list)
    lines: list[tuple[float, float, float, float]] = field(default_factory=list)
    rects: list[Rect] = field(default_factory=list)
    circles: list[tuple[float, float, float]] = field(default_factory=list)      # (cx, cy, r)
    footprint_id: str | None = None      # má-li artikl footprint, kreslí se symbol (počátek v levém horním rohu)


@dataclass
class LayoutGeometry:
    enclosure: Rect
    rails: list[Rect] = field(default_factory=list)
    ticks: list[tuple[float, float, float, float]] = field(default_factory=list)
    devices: list[LayoutDevice] = field(default_factory=list)
    texts: list[Text] = field(default_factory=list)


def _generic(d: LayoutDevice, e: Element, size: DeviceSize, kind: str) -> None:
    """Generická kresba přístroje do `d` (stejná logika jako `DeviceItem._paint_generic`; lokální souřadnice
    scény s Y dolů převedené na absolutní model)."""
    w, h = d.w, d.h
    top = d.y + h            # horní hrana přístroje v modelu

    def ln(x1, y1, x2, y2):
        d.lines.append((d.x + x1, top - y1, d.x + x2, top - y2))

    def rc(x, y, rw, rh):
        d.rects.append((d.x + x, top - y - rh, rw, rh))

    def circ(x, y, dia):
        d.circles.append((d.x + x + dia / 2, top - y - dia / 2, dia / 2))

    poles = max(e.poles, 1)
    if size.shape == SHAPE_TERMINAL and size.real:
        n = terminal_count(e)
        tw = (w - size.end_mm) / max(n, 1)
        for i in range(1, n):
            ln(i * tw, 2, i * tw, h - 2)
        return
    if size.shape == SHAPE_BOX or kind in ("mccb",):
        hw = w * 0.5
        hh = min(10.0, h * 0.2)
        rc(w / 2 - hw / 2, h / 2 - hh / 2, hw, hh)
        pw = w / poles
        for i in range(poles):
            cx = (i + 0.5) * pw
            rc(cx - min(pw * 0.3, 6), 2, min(pw * 0.6, 12), 6)
            rc(cx - min(pw * 0.3, 6), h - 8, min(pw * 0.6, 12), 6)
        return
    mods = max(size.modules, 1.0)
    lever_y = 22 + (h - DEVICE_HEIGHT_MM) / 2
    pole_w = w / max(min(poles, mods), 1)
    n = int(min(poles, mods)) if mods >= 1 else 1
    for i in range(n):
        x = i * pole_w
        rc(x + pole_w * 0.25, lever_y, pole_w * 0.5, 9)
        circ(x + pole_w / 2 - 2.5, 2, 5)
        circ(x + pole_w / 2 - 2.5, h - 7, 5)


def _device_texts(d: LayoutDevice, e: Element, name: str, size: DeviceSize) -> list[Text]:
    """Texty přístroje jako `DeviceItem.paint`: ref, typ, In + charakteristika / průřez svorky, popisek rozměru."""
    cx, top = d.x + d.w / 2, d.y + d.h
    out: list[Text] = []
    if e.ref:
        out.append((cx, top - 8, e.ref, 3.0, "center"))
    typ = e.attrs.get("type") or name
    if typ:
        out.append((cx, top - 14, typ[:18], 2.0, "center"))
    info = " ".join(x for x in (e.attrs.get("in_", ""), e.attrs.get("char", "")) if x)
    if size.shape == SHAPE_TERMINAL and size.real:
        cross = e.attrs.get("cross", "")
        info = f"{cross} mm²" if cross else ""
    if info:
        out.append((cx, top - 19, info, 2.0, "center"))
    label = size.label(terminal_count(e))
    if label:
        out.append((cx, d.y + 2, label, 1.8, "center"))
    return out


def layout_geometry(project: Project, sheet: Sheet, lib) -> LayoutGeometry:
    """Geometrie rozložení listu rozvaděče (mm, Y nahoru) – stejné rozměry a polohy jako `ui/layout_view.LayoutScene`."""
    lay = sheet.layout
    inner_w = lay.modules_per_row * MODULE_WIDTH
    pitch = lay.row_pitch_mm
    inner_h = lay.rows * pitch
    ew, eh = lay.outline_mm
    ex, ey_s = MARGIN - (ew - inner_w) / 2, MARGIN - (eh - inner_h) / 2      # levý horní roh (scéna)
    g = LayoutGeometry(enclosure=(ex, -(ey_s + eh), ew, eh))
    for r in range(lay.rows):
        rail_y = MARGIN + r * pitch + (pitch - DEVICE_HEIGHT_MM) / 2          # horní hrana modulu (scéna)
        top = rail_y + DEVICE_HEIGHT_MM / 2 - RAIL_H / 2
        g.rails.append((MARGIN, -(top + RAIL_H), inner_w, RAIL_H))
        for m in range(lay.modules_per_row + 1):
            x = MARGIN + m * MODULE_WIDTH
            y0 = rail_y + DEVICE_HEIGHT_MM
            g.ticks.append((x, -y0, x, -(y0 + (3 if m % 6 else 6))))
    unplaced_y = MARGIN
    ux = MARGIN + inner_w + UNPLACED_X_GAP
    any_unplaced = False
    for e in lay.devices(sheet, project, lib):
        sym = lib.get_symbol(e.symbol_id)
        pl = lay.placement(e.id)
        fp_id, kind, comp = None, "", None
        if e.component_id:
            comp = lib.component(e.component_id)
            if comp:
                kind = comp.category
                if comp.footprint_id:
                    try:
                        lib.get_symbol(comp.footprint_id)
                        fp_id = comp.footprint_id
                    except KeyError:
                        fp_id = None
        size = device_size(e, comp=comp)
        w, h = device_width_mm(size), size.height_mm
        if pl:
            axis = MARGIN + (pl.row + 0.5) * pitch
            x, y_s = MARGIN + pl.pos * MODULE_WIDTH, axis - h / 2
        else:
            any_unplaced = True
            x, y_s = ux, unplaced_y
            unplaced_y += h + UNPLACED_Y_GAP
        d = LayoutDevice(e.id, e.ref, x, -(y_s + h), w, h, pl is not None, footprint_id=fp_id)
        d.texts = _device_texts(d, e, sym.name, size)
        if fp_id is None:
            _generic(d, e, size, kind)
        g.devices.append(d)
    dims = f"{lay.width_mm:g} × {lay.height_mm:g}" + (f" × {lay.depth_mm:g}" if lay.depth_mm else "") + " mm"
    used, total = lay.used_modules(sheet, project, lib), lay.total_modules
    enc = lay.enclosure or "–"
    line1 = f"{sheet.name}   skříň: {enc}   {dims}   {lay.params.get('ip', '')}"
    line2 = (f"{lay.rows} řad × {lay.modules_per_row} modulů = {total} M, obsazeno {used:g} M "
             f"({(used / total * 100) if total else 0:.0f} %), rezerva {total - used:g} M")
    top_m = -ey_s
    g.texts.append((ex, top_m + 13, line1, 3.5, "left"))
    g.texts.append((ex, top_m + 7, line2, 2.5, "left"))
    if any_unplaced:
        g.texts.append((ux, -(MARGIN - 6), "Nerozmístěno", 3.0, "left"))
    return g
