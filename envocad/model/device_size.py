"""Rozměry přístroje v rozložení rozvaděče z artiklu a atributů (bez Qt). Návrh `docs/design/rozlozeni_z_artiklu.md`.

Priorita (šířka): ruční `width_mm` prvku > ruční `modules` (liší se od artiklu, který moduly má) > artikl (`modules`,
jinak `width_mm`) > atribut `modules` (výchozí hodnota značky / projekt bez artiklu) > nic (není přístroj rozložení).
Výška a hloubka: atribut `height_mm` / `depth_mm` > artikl > výchozí `DEVICE_HEIGHT_MM` / neznámá.
Skupina řadových svorek: ruční `modules` > počet svorek × `width_mm` artiklu svorky (+ `end_mm`) > počet svorek ×
`TERMINAL_WIDTH_MM` (+ `end_mm`).

Knihovna `lib` je volitelná a duck-typed (`lib.component(id)` → artikl s `params`, `category`, `num()`); bez ní
(nebo bez artiklu) je výsledek stejný jako dřív (`Element.modules`, výška 45 mm) – staré projekty se nemění.
"""
from __future__ import annotations

from dataclasses import dataclass

from envocad.model.project import (
    AUTO_WIDTH_TERMINALS,
    DEVICE_HEIGHT_MM,
    MODULE_WIDTH,
    TERMINAL_WIDTH_MM,
    Element,
    terminal_count,
    terminal_group_modules,
)

SRC_ARTICLE, SRC_MANUAL, SRC_DEFAULT = "artikl", "ruční", "výchozí"
SHAPE_DIN, SHAPE_BOX, SHAPE_TERMINAL = "din", "box", "terminal"
# Kategorie artiklů, které nejsou modulové přístroje na DIN liště: kompaktní jističe (3VA, MCCB) se kreslí jako
# obdélník š × v z artiklu. Ostatní artikl bez `modules` je „box“, když je vyšší než `DIN_MAX_HEIGHT_MM` – modulové
# přístroje mají výšku základny ~80–95 mm (Eaton PL6 80 mm, Hager MBN 83 mm), odpínač 3VA1 130 mm.
BOX_CATEGORIES = {"mccb"}
DIN_MAX_HEIGHT_MM = 100.0


@dataclass(frozen=True)
class DeviceSize:
    """Rozměry přístroje v rozložení [mm]; `modules` = šířka v modulech 17,5 mm (na setiny), `depth_mm` None =
    neznámá. `source` = zdroj šířky („artikl“, „ruční“, „výchozí“)."""
    width_mm: float
    height_mm: float
    depth_mm: float | None
    shape: str
    source: str
    height_source: str = SRC_DEFAULT
    pitch_mm: float | None = None      # svorkovnice: šířka jedné svorky (rozteč) bez koncových desek
    end_mm: float = 0.0                # svorkovnice: přídavek na koncové desky / zarážky (atribut `end_mm`)
    width_from_mm: bool = False        # šířka ze skutečného rozměru v mm (artikl `width_mm` / ruční `width_mm`)

    @property
    def modules(self) -> float:
        return round(self.width_mm / MODULE_WIDTH, 2)

    @property
    def real(self) -> bool:
        """Šířka je skutečný rozměr (artikl nebo ruční `width_mm`), ne moduly z atributu / výchozí odhad."""
        return self.source == SRC_ARTICLE or self.width_from_mm

    def label(self, terminals: int | None = None) -> str:
        """Popisek pod přístrojem: „3 M“ (modulový), „76,2 × 130 mm“ (obdélník), svorkovnice z artiklu
        „5 × 3,5 mm“ (`terminals` = počet svorek)."""
        if self.shape == SHAPE_BOX:
            return f"{_g(self.width_mm)} × {_g(self.height_mm)} mm"
        if self.shape == SHAPE_TERMINAL and self.source == SRC_ARTICLE and self.pitch_mm and terminals:
            return f"{terminals} × {_g(self.pitch_mm)} mm"
        return f"{self.modules:g} M"


def _g(v: float) -> str:
    return f"{round(v, 1):g}".replace(".", ",")


def _num(v) -> float | None:
    try:
        x = float(str(v).replace(",", ".").strip()) if v not in (None, "") else None
    except ValueError:
        return None
    return x if x is not None and x > 0 else None


def component_of(e: Element, lib):
    """Artikl prvku z knihovny, nebo None (bez knihovny, bez artiklu, neznámé id, chyba knihovny)."""
    if lib is None or not e.component_id or not hasattr(lib, "component"):
        return None
    try:
        return lib.component(e.component_id)
    except Exception:  # noqa: BLE001 – knihovna nedostupná → jen atributy
        return None


def _comp_num(comp, key: str) -> float | None:
    return _num(comp.params.get(key)) if comp is not None else None


def is_box(comp) -> bool:
    """Artikl, který není modulový přístroj (kompaktní jistič, skříňový odpínač) – obdélník š × v z artiklu."""
    if comp is None or _comp_num(comp, "width_mm") is None:
        return False
    if comp.category in BOX_CATEGORIES:
        return True
    h = _comp_num(comp, "height_mm")
    return _comp_num(comp, "modules") is None and h is not None and h > DIN_MAX_HEIGHT_MM


def terminal_end_mm(e: Element) -> float:
    """Přídavek skupiny svorek na koncové desky / zarážky [mm] (atribut `end_mm`, nezadaný / neplatný = 0). Katalog
    šířku koncových desek (AEP) ani zarážek (AEB) nemá, proto žádná výchozí konstanta."""
    return _num(e.attrs.get("end_mm")) or 0.0


def device_size(e: Element, lib=None, comp=None) -> DeviceSize:
    """Rozměry přístroje (viz modul). `comp` = artikl, už-li ho volající má (jinak se hledá v `lib`)."""
    if comp is None:
        comp = component_of(e, lib)
    a_width, a_height, a_depth = (_num(e.attrs.get(k)) for k in ("width_mm", "height_mm", "depth_mm"))
    raw_mod = str(e.attrs.get("modules") or "").strip()
    a_mod = _num(raw_mod) if raw_mod else None
    c_mod, c_width = _comp_num(comp, "modules"), _comp_num(comp, "width_mm")
    c_height, c_depth = _comp_num(comp, "height_mm"), _comp_num(comp, "depth_mm")
    height = a_height or c_height or DEVICE_HEIGHT_MM
    h_src = SRC_MANUAL if a_height else (SRC_ARTICLE if c_height else SRC_DEFAULT)
    depth = a_depth or c_depth
    common = {"height_mm": height, "depth_mm": depth, "height_source": h_src}
    if e.symbol_id in AUTO_WIDTH_TERMINALS:
        end = terminal_end_mm(e)
        n = terminal_count(e)
        term = {**common, "shape": SHAPE_TERMINAL, "end_mm": end}
        if a_width:
            return DeviceSize(a_width, source=SRC_MANUAL, width_from_mm=True, pitch_mm=(a_width - end) / n, **term)
        if raw_mod:
            w = (a_mod or 0.0) * MODULE_WIDTH
            return DeviceSize(w, source=SRC_MANUAL, pitch_mm=max(w - end, 0.0) / n, **term)
        if c_width:
            return DeviceSize(round(n * c_width + end, 2), source=SRC_ARTICLE, width_from_mm=True, pitch_mm=c_width,
                              **term)
        # bez artiklu přesně jako `Element.modules` (`terminal_group_modules` – moduly na setiny)
        w = terminal_group_modules(n, TERMINAL_WIDTH_MM) * MODULE_WIDTH + end
        return DeviceSize(w, source=SRC_DEFAULT, pitch_mm=TERMINAL_WIDTH_MM, **term)
    dev = {**common, "shape": SHAPE_BOX if is_box(comp) else SHAPE_DIN}
    if a_width:
        return DeviceSize(a_width, source=SRC_MANUAL, width_from_mm=True, **dev)
    if c_mod is not None:
        if a_mod is not None and abs(a_mod - c_mod) > 1e-9:
            return DeviceSize(a_mod * MODULE_WIDTH, source=SRC_MANUAL, **dev)
        return DeviceSize(c_mod * MODULE_WIDTH, source=SRC_ARTICLE, **dev)
    if c_width:
        # artikl bez modulů: skutečná šířka (kompaktní jistič 76,2 mm); atribut `modules` je tu výchozí hodnota
        # značky (MCCB „6“), ruční přepis rozměru jde přes `width_mm`
        return DeviceSize(c_width, source=SRC_ARTICLE, width_from_mm=True, **dev)
    # bez dat artiklu: jako dřív (atribut `modules`, výška 45 mm)
    return DeviceSize(max(e.modules, 0.0) * MODULE_WIDTH, source=SRC_MANUAL if raw_mod else SRC_DEFAULT, **dev)


def device_modules(e: Element, lib=None) -> float:
    """Šířka přístroje v modulech pro rozložení (`device_size`); bez knihovny = `Element.modules`."""
    if lib is None:
        return e.modules
    return device_size(e, lib).modules


# ---- kontroly rozměrů (F7) ----------------------------------------------------------------------------------
@dataclass
class SizeProblem:
    """Problém rozměru přístroje v rozložení: `layout_height` (vyšší než rozteč řad – zasahuje do sousední řady),
    `layout_enclosure` (přesahuje skříň), `layout_depth` (hlubší než skříň)."""
    code: str
    element: Element
    text: str


def _mm(v: float) -> str:
    return f"{round(v, 1):g}".replace(".", ",")


def size_problems(sheet, project=None, lib=None, layout=None) -> list[SizeProblem]:
    """Rozměry umístěných přístrojů proti řadě a skříni. Bez knihovny se kontrolují jen ruční rozměry prvků
    (`height_mm`, `depth_mm`); výchozí výška 45 mm se nehlásí nikdy (staré projekty beze změny)."""
    lay = layout if layout is not None else sheet.layout
    out: list[SizeProblem] = []
    pitch = lay.row_pitch_mm
    inner_h = lay.rows * pitch
    h_encl = max(lay.height_mm, inner_h)
    usable_w = lay.modules_per_row * MODULE_WIDTH
    for e in lay.devices(sheet, project, lib):
        sz = device_size(e, lib)
        pl = lay.placement(e.id)
        # šířka v modulech nad délku řady hlásí `layout_overflow`; tady jen skutečný rozměr (artikl / `width_mm`)
        if sz.real and sz.width_mm > usable_w + 1e-6:
            out.append(SizeProblem("layout_enclosure", e,
                                   f"Přístroj je široký {_mm(sz.width_mm)} mm ({sz.source}), řada má užitnou šířku "
                                   f"{_mm(usable_w)} mm"))
        if pl is not None and sz.height_source != SRC_DEFAULT:
            if sz.height_mm > pitch + 1e-6:
                out.append(SizeProblem("layout_height", e,
                                       f"Přístroj v řadě {pl.row + 1} je vysoký {_mm(sz.height_mm)} mm "
                                       f"({sz.height_source}), rozteč řad je {_mm(pitch)} mm – zasahuje do sousední "
                                       "řady"))
            # osa řady od dna skříně (řady svisle na střed, jako kreslí rozložení a `thermal.row_height_ratio`)
            axis = h_encl / 2 + (lay.rows / 2 - pl.row - 0.5) * pitch
            if axis + sz.height_mm / 2 > h_encl + 1e-6 or axis - sz.height_mm / 2 < -1e-6:
                out.append(SizeProblem("layout_enclosure", e,
                                       f"Přístroj v řadě {pl.row + 1} (výška {_mm(sz.height_mm)} mm) přesahuje "
                                       f"skříň výšky {_mm(h_encl)} mm"))
        d_encl = lay.depth_mm
        if d_encl and sz.depth_mm and sz.depth_mm > d_encl + 1e-6:
            out.append(SizeProblem("layout_depth", e,
                                   f"Hloubka přístroje {_mm(sz.depth_mm)} mm je větší než hloubka skříně "
                                   f"{_mm(d_encl)} mm"))
    return out
