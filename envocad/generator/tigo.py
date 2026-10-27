"""Optimizéry Tigo v blokovém schématu – bez Qt. Optimizéry Tigo (TS4) potřebují signál: řídicí jednotku CCA
s přístupovým bodem TAP (výchozí), nebo vysílač rychlého odpojení RSS. Kontrola `checks.tigo_findings` hlídá, že
v projektu jeden z nich je; generátor je doplní sám.

Specifikace: `spec["optimizer"]["tigo"]` = "cca" (výchozí – TAP na střeše u panelů → RS485 Gateway → CCA) | "rss" (vysílač RSS,
jádro na vodičích stringů) | "none" (nekreslit – projektant doplní, F7 pak hlásí `tigo_missing`). Bloky se kladou
po rozmístění JPS nad horní string – první poloha bez překryvu textů."""
from __future__ import annotations

from envocad.model.checks import TIGO_CCA, TIGO_RSS, TIGO_TAP, is_tigo_string
from envocad.model.project import Element, Wire, WireEnd

TIGO_MODES = ("cca", "rss", "none")
TIGO_GW_CONDUCTORS = ["A", "B", "+", "GND"]   # sběrnice Gateway CCA ↔ TAP: RS485 A/B a napájení TAP (= makro)
TAP_CCA_DX = 45.0                             # CCA vpravo od TAP (místo na popisky obou bloků)


def tigo_mode(spec: dict) -> str:
    """Volba `optimizer.tigo` (ValueError česky u neznámé hodnoty)."""
    v = str((spec.get("optimizer") or {}).get("tigo") or "cca").strip().lower()
    if v not in TIGO_MODES:
        raise ValueError(f"optimizer.tigo: neznámá volba „{v}“ – zadejte {', '.join(TIGO_MODES)}.")
    return v


def build(ctx) -> list[Element]:
    """Doplní bloky Tigo do blokového schématu (`ctx.sheet`), jsou-li v něm stringy s optimizéry Tigo. Vrací nové
    prvky (prázdné = bez Tigo, volba „none“ nebo už vložené ručně / makrem)."""
    s, p = ctx.sheet, ctx.project
    strings = [e for e in s.elements if is_tigo_string(e)]
    mode = tigo_mode(ctx.spec)
    if not strings or mode == "none" or any(e.symbol_id in (TIGO_CCA, TIGO_RSS) for sh in p.sheets
                                             for e in sh.elements):
        return []
    top = max(strings, key=lambda e: e.y)
    if mode == "rss":
        rss = Element(TIGO_RSS, top.x, top.y, attrs={
            "ref": p.next_ref("A"), "type": "Tigo RSS Transmitter", "manufacturer": "Tigo",
            "strings": ", ".join(e.ref for e in strings if e.ref), "desc": "rychlé odpojení optimizérů"})
        s.elements.append(rss)
        _place(ctx, [rss], top)
        return [rss]
    tap = Element(TIGO_TAP, top.x, top.y, attrs={"ref": p.next_ref("A"), "type": "Tigo TAP", "manufacturer": "Tigo",
                                                 "desc": "na střeše u FV panelů"})
    s.elements.append(tap)
    cca = Element(TIGO_CCA, top.x, top.y, attrs={"ref": p.next_ref("A"), "type": "Tigo CCA", "manufacturer": "Tigo",
                                                 "desc": "komunikace optimizérů"})
    s.elements.append(cca)
    s.wires.append(Wire(WireEnd(tap.id, "GW"), WireEnd(cca.id, "GW"), conductors=list(TIGO_GW_CONDUCTORS),
                        attrs={"ref": ""}))
    _place(ctx, [tap, cca], top)
    return [tap, cca]


def _place(ctx, els: list[Element], top: Element) -> None:
    """Bloky v řadě nad horním stringem (TAP vlevo, CCA o `TAP_CCA_DX` vpravo, porty GW proti sobě): výš po 10 mm,
    dokud se texty listu nepřekrývají (nejvýš 6 pokusů – jinak poslední poloha, F7 překryv ukáže)."""
    from envocad.generator import context
    from envocad.model.project import element_symbol
    from envocad.model.textlayout import symbol_box, text_overlaps
    lib = context._lib()
    p, s = ctx.project, ctx.sheet
    base = text_overlaps(p, s, lib)
    y_top = symbol_box(top, element_symbol(p, top, lib))[3]
    for k in range(6):
        y = round((y_top + 25.0 + 10.0 * k) / 2.5) * 2.5
        for j, e in enumerate(els):
            e.x, e.y = top.x + 2.5 + TAP_CCA_DX * j, y
        if len(text_overlaps(p, s, lib)) <= len(base):
            return
