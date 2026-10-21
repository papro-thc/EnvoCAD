"""Sběrnice `sb.busbar` – parametrická délka a porty podle počtu přívodů (bez Qt).

Základní značka z knihovny má pevnou délku (čára x −75…120, přívody shora T1…T12, vývody zdola 1…13, přívody zdola
B1…B12 – B7…B12 leží mezi B1…B6). Tak se kreslí každá sběrnice **bez** atributu `taps` (staré projekty, vlastní
makra, ručně vložená sběrnice) – beze změny.

Sběrnice s atributem `taps` (počet přívodů zdola) je parametrická – geometrii skládá `busbar_symbol` (jako
`inverter_symbol` / `feed_symbol` přes `project.element_symbol`); jen atributy prvku – formát projektu v14 bez
migrace dat (verze zvednutá, aby program v13 soubor odmítl místo kreslení pevné sběrnice):

- přívody zdola B1…Bn po rozteči `tap_pitch` (výchozí 30 mm = `templates.GROUP_PITCH`), B1 v x −60 (jako pevná
  sběrnice – přívod X1 pod B1 zůstává na místě); přívody shora T1…Tn přímo nad nimi,
- vývody vlevo před přívody: 1 v B1 − 45 (PE → XPE), 2 v B1 − 22,5 (SPD),
- vývody vpravo za posledním přívodem: 3 v Bn + 37,5 (hlavní vypínač; místo pro popisky svorek ve spodní řadě),
  4… po rozteči; počet vpravo = atribut `outs` (výchozí 1),
- vstup IN vlevo nahoře na začátku čáry, čára o 7,5 mm za krajními porty.

Počty se nikdy nezmenší pod porty, na které vedou vodiče (B9 při `taps=7` → 9 přívodů), takže ruční přidání
přívodu nebo vývodu sběrnici prodlouží a nic se neodpojí. Návrh: `docs/LIBRARY_FORMAT.md` („Sběrnice“).
"""
from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

BUS_SYMBOL = "sb.busbar"
TAPS_ATTR = "taps"            # počet přívodů zdola (prázdné = pevná sběrnice z knihovny)
OUTS_ATTR = "outs"            # počet vývodů vpravo za přívody (výchozí 1)
PITCH_ATTR = "tap_pitch"      # rozteč přívodů [mm] (výchozí 30)
PARAM_KEYS = (TAPS_ATTR, OUTS_ATTR, PITCH_ATTR)

B1_X = -60.0                  # x přívodu B1 vůči prvku (= pevná sběrnice)
DEFAULT_PITCH = 30.0
MIN_PITCH = 7.5
LEFT_OUTS = {"1": -45.0, "2": -22.5}   # vývody vlevo vůči B1: PE (XPE), SPD
RIGHT_GAP = 37.5              # první vývod vpravo za posledním přívodem
PORT_DY = 5.0                 # porty 5 mm nad / pod čarou
END_MARGIN = 7.5              # čára přesahuje krajní port
MAX_TAPS = 99
_NUM = re.compile(r"\d+")


def _attrs(e: Any) -> dict:
    a = e.get("attrs") if isinstance(e, dict) else getattr(e, "attrs", None)
    return a if isinstance(a, dict) else {}


def _int(v: Any) -> int | None:
    try:
        f = float(str(v).strip().replace(",", "."))
    except ValueError:
        return None
    return int(f) if f.is_integer() else None


@dataclass(frozen=True)
class BusLayout:
    """Rozložení parametrické sběrnice (x vůči prvku, Y nahoru)."""
    taps: int
    outs: int = 1
    pitch: float = DEFAULT_PITCH

    def tap_x(self, k: int) -> float:
        """x přívodu B{k} (a T{k} nad ním), k od 1."""
        return B1_X + self.pitch * (k - 1)

    def out_x(self, name: str) -> float:
        """x vývodu „1“, „2“ (vlevo) nebo „3“… (vpravo za posledním přívodem)."""
        if name in LEFT_OUTS:
            return B1_X + LEFT_OUTS[name]
        return self.tap_x(self.taps) + RIGHT_GAP + self.pitch * (int(name) - 3)

    def out_names(self) -> list[str]:
        return [*LEFT_OUTS, *(str(i + 3) for i in range(self.outs))]

    @property
    def left(self) -> float:
        return min(self.out_x(n) for n in LEFT_OUTS) - END_MARGIN

    @property
    def right(self) -> float:
        return self.out_x(str(self.outs + 2)) + END_MARGIN

    def right_out_name(self, x_rel: float) -> str | None:
        """Vývod vpravo přesně v x (vůči prvku), nebo None."""
        for i in range(self.outs):
            if abs(self.out_x(str(i + 3)) - x_rel) < 1e-6:
                return str(i + 3)
        return None


def layout_of(e: Any, used: Iterable[str] = ()) -> BusLayout | None:
    """Rozložení sběrnice s atributem `taps`; None = pevná sběrnice (bez atributu, neplatná hodnota, jiný prvek).
    Počty se zvětší podle použitých portů (`used`: B{k}/T{k} → přívody, číslo ≥ 3 → vývody vpravo)."""
    sid = e.get("symbol_id") if isinstance(e, dict) else getattr(e, "symbol_id", "")
    if sid != BUS_SYMBOL:
        return None
    a = _attrs(e)
    taps = _int(a.get(TAPS_ATTR, ""))
    if taps is None or not 1 <= taps <= MAX_TAPS:
        return None
    outs = _int(a.get(OUTS_ATTR, "")) or 1
    outs = max(1, min(outs, MAX_TAPS))
    try:
        pitch = float(str(a.get(PITCH_ATTR) or DEFAULT_PITCH).replace(",", "."))
    except ValueError:
        pitch = DEFAULT_PITCH
    if not (pitch >= MIN_PITCH and abs(pitch / 2.5 - round(pitch / 2.5)) < 1e-9):
        pitch = DEFAULT_PITCH       # mimo mřížku nebo příliš hustě: výchozí rozteč
    for p in used:
        m = re.fullmatch(r"[BT](\d+)", p)
        if m and 1 <= int(m.group(1)) <= MAX_TAPS:
            taps = max(taps, int(m.group(1)))
        elif _NUM.fullmatch(p) and 3 <= int(p) <= MAX_TAPS + 2:
            outs = max(outs, int(p) - 2)
    return BusLayout(taps, outs, pitch)


def busbar_symbol(e: Any, base, used: Iterable[str] = ()):
    """Značka sběrnice: s atributem `taps` délka a porty podle počtu přívodů (`layout_of`), jinak základní značka
    z knihovny beze změny."""
    from envocad.model.symbol import Port
    lay = layout_of(e, used)
    if lay is None:
        return base
    x0, x1 = lay.left, lay.right
    prims = [{"type": "polyline", "points": [[x0, 0], [x1, 0]], "closed": False},
             {"type": "polyline", "points": [[x0, 1], [x1, 1]], "closed": False}]
    ports = [Port("IN", x0, PORT_DY, "N")]
    ports += [Port(f"T{k}", lay.tap_x(k), PORT_DY, "N") for k in range(1, lay.taps + 1)]
    ports += [Port(n, lay.out_x(n), -PORT_DY, "S") for n in lay.out_names()]
    ports += [Port(f"B{k}", lay.tap_x(k), -PORT_DY, "S") for k in range(1, lay.taps + 1)]
    lx = base.label_pos[1] if base.label_pos else 7.5
    return dataclasses.replace(base, primitives=prims, ports=ports, label_pos=(x0, lx))


def line_span(sym) -> tuple[float, float]:
    """(levý, pravý) konec čáry sběrnice (x vůči prvku, rotace 0) – pevné i parametrické."""
    xs = [x for pr in sym.primitives if pr.get("type") == "polyline" for x, _y in pr.get("points", [])]
    return (min(xs), max(xs)) if xs else (0.0, 0.0)


def line_end(sym) -> float:
    """Pravý konec čáry sběrnice (x vůči prvku)."""
    return line_span(sym)[1]
