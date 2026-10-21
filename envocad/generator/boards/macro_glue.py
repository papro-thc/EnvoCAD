"""Skládání rozvaděčů z maker knihovny (role dc_tech, dc_route, ac_feed, ac_core) (bez Qt). Přesun 1:1 z `generate.py`
(refaktoring F1, krok 4)."""
from __future__ import annotations

import re

from envocad.generator import context
from envocad.generator.context import (
    _s,
)
from envocad.library.templates import (
    _place_sequential,
)
from envocad.model.busbar import PITCH_ATTR, TAPS_ATTR, layout_of
from envocad.model.feed import FEED_SYMBOL
from envocad.model.project import Element, Project, Sheet, Wire


def _macro_vars(dc: dict, ac: dict) -> dict:
    """Základ hodnot proměnných maker ze specifikace (v `resolve_values` hned za výchozími hodnotami makra)."""
    # prázdné / „auto“ `fuse_in` (podle stringu) doplní `_fuse_in` před voláním; zůstane-li prázdné (žádná pojistka
    # nevyhoví), dosadí se zástupná hodnota a po rozvinutí makra se z prvků zase vymaže (`_blank_unresolved`)
    return {"fuse_in": _s(dc.get("fuse_in")).strip() or UNRESOLVED_IN, "disc_in": _s(dc.get("disconnect_in") or 32), "spd": _s(dc.get("spd") or "T2"),
            "breaker_in": _s(ac.get("breaker_in") or 40), "main_in": _s(ac.get("main_in") or 125), "ac_spd": _s(ac.get("spd") or "T1+T2")}


FUSE_SYMBOLS = ("fve.fuse_disconnect", "fve.fuse")
UNRESOLVED_IN = "987654321"   # zástupné In pro makro s povinnou proměnnou, když generátor In neurčil (→ prázdné)


def _blank_unresolved(elements: list[Element], wires: list[Wire] = ()) -> None:
    """Zástupné In (`UNRESOLVED_IN`) v atributech rozvinutého makra (prvky i vodiče, texty) → prázdné, bez zdvojených
    mezer po vynechané hodnotě; kontrola F7 pak hlásí chybějící In."""
    for obj in [*elements, *wires]:
        for k, v in obj.attrs.items():
            if isinstance(v, str) and UNRESOLVED_IN in v:
                obj.attrs[k] = re.sub(r"\s{2,}", " ", v.replace(UNRESOLVED_IN, "")).strip()


def _macro_ref(entry) -> tuple[str, str | None, dict]:
    """Položka `spec["macros"][role]`: název makra (řetězec) nebo {"name", "value_set", "values"} → (název, sada, hodnoty)."""
    if isinstance(entry, dict):
        return (_s(entry.get("name")).strip(), _s(entry.get("value_set")).strip() or None,
                {str(k): _s(v) for k, v in (entry.get("values") or {}).items()})
    return _s(entry).strip(), None, {}


def _macro_values(m, entry: tuple[str, str | None, dict], base: dict, context: dict, components) -> dict:
    """Hodnoty proměnných makra pro generátor; chyba → ValueError s názvem makra."""
    from envocad.library.macros import resolve_values
    _, value_set, given = entry
    vals, errs = resolve_values(m, given=given, value_set=value_set, components=components, context=context, base=base,
                                repeat=False,   # smyčku stringů drží generátor (počet není omezen max makra)
                                unresolved={k for k, v in base.items() if v == UNRESOLVED_IN})
    if errs:
        raise ValueError(f"Makro „{m.name}“: " + "; ".join(e.removeprefix(f"Makro „{m.name}“: ") for e in errs))
    return vals


def _insert_macro(project: Project, sheet: Sheet, m, values: dict, dx: float, lib) -> list[Element]:
    """Rozvine makro (bez opakování – smyčku drží generátor) a vloží ho do listu; vrací nové přístroje pro rozmístění."""
    from envocad.library.macros import expand, insert
    els, wires = expand(project, sheet, m, values, dx=dx, ref_prefix_of=lambda sid: lib.get_symbol(sid).iec_ref,
                        components=lib.component, repeat=False, copy=False)   # označení z makra beze změny
    _blank_unresolved(els, wires)
    insert(sheet, els, wires)
    return [e for e in els if e.modules > 0 and e.symbol_id not in (FEED_SYMBOL, "sb.busbar")]


def _dc_box_from_macro(project: Project, sheet: Sheet, strings: list[str], name, dc: dict,
                       inv_no: int = 1, inv_ref: str = "", k0: int = 0, n: int | None = None, dx0: float = 0.0) -> bool:
    """DC rozvaděč složený z makra na string. Kontext: k (pořadí v rozvaděči), nk (n + k), n, string (G3),
    i (číslo střídače), j (string u střídače) – ENVO číslování FU{i}.{j}, XS{i}.{j}, STRING {i}.{j} –, inverter;
    základ ze specifikace fuse_in, disc_in, spd. `name` = položka `spec["macros"]` (název nebo objekt). False = makro chybí.
    Rozvaděč FVE rodinného domu: `k0` = počet přívodů před stringy (k = k0 + pořadí), `n` = stringů celkem v rozvaděči,
    `dx0` = posun DC části v listu."""
    from envocad.library.macros import find_macro, macro_pitch
    entry = _macro_ref(name)
    m = find_macro(entry[0]) if entry[0] else None
    if m is None:
        return False
    lib = context._lib()
    n = len(strings) if n is None else n
    pitch = macro_pitch(m)
    base = _macro_vars(dc, {})
    devices = []
    for j, g in enumerate(strings, start=1):
        k = k0 + j
        ctx = {"k": k, "nk": n + k, "n": n, "string": g, "i": inv_no, "j": j, "inverter": inv_ref}
        vals = _macro_values(m, entry, base, ctx, lib.component)
        devices += _insert_macro(project, sheet, m, vals, dx0 + (k - 1) * pitch, lib)
    _place_sequential(sheet, devices)
    return True


def _ac_box_from_macros(project: Project, sheet: Sheet, invs: list[dict], ac: dict, macros: dict) -> bool:
    """AC rozvaděč: makro přívodu na každý střídač (k, i, inverter; breaker_in, main_in) + makro jádra (spd = ac.spd, main_in)."""
    from envocad.library.macros import find_macro, macro_pitch
    ef, ec = _macro_ref(macros.get("ac_feed", "")), _macro_ref(macros.get("ac_core", ""))
    mf = find_macro(ef[0]) if ef[0] else None
    mc = find_macro(ec[0]) if ec[0] else None
    if mf is None or mc is None or (ac.get("distribution") or "bus") != "bus":
        return False
    lib = context._lib()
    pitch = macro_pitch(mf)
    devices = []
    base = _macro_vars({}, ac)
    base["spd"] = base["ac_spd"]
    for k, inv in enumerate(invs, start=1):
        ctx = {"k": k, "i": k, "inverter": inv.get("ref") or f"T{k}"}
        devices += _insert_macro(project, sheet, mf, _macro_values(mf, ef, base, ctx, lib.component), (k - 1) * pitch, lib)
    core_vals = _macro_values(mc, ec, base, {}, lib.component)
    if _feed_macro_from_below(mf):
        # jádro (XPE a SPD vlevo, hlavní vypínač + XOUT) se vkládá bez posunu; hlavní vypínač pak za poslední přívod.
        # Parametrická sběrnice (vestavěná makra: atribut `taps`) dostane počet přívodů a rozteč makra – každý přívod
        # B{k} rovně nad svým jističem; vlastní makro se sběrnicí bez atributu má pevnou sběrnici jako dřív
        bus = next((e for e in sheet.elements if e.symbol_id == "sb.busbar"), None)
        if layout_of(bus) is not None:
            bus.attrs[TAPS_ATTR] = str(len(invs))
            bus.attrs[PITCH_ATTR] = f"{pitch:g}"
        devices += _insert_macro(project, sheet, mc, core_vals, 0.0, lib)
        from envocad.generator.boards.rfve_ac import _ac_core_after_feeds  # rfve_ac importuje tento modul
        _ac_core_after_feeds(project, sheet)
    else:
        # vlastní makra ve starém rozložení (přívod shora do portu T{k}): jádro za přívody jako dřív, bez přesunu
        # hlavního vypínače a lomů odboček (ty počítají s přívody zdola B{k})
        devices += _insert_macro(project, sheet, mc, core_vals, len(invs) * pitch, lib)
    _place_sequential(sheet, devices)
    if ac.get("enclosure"):
        sheet.layout.params["type"] = _s(ac["enclosure"])
    return True


def _feed_macro_from_below(m) -> bool:
    """Makro přívodu střídače v rozložení „vše zespodu“ (makra v3: vodič do portu B{k} sběrnice). Vlastní makro
    v1/v2 nebo makro bez vodiče do portu B* má staré rozložení (přívod shora do T{k}) – jádro se pak vkládá za přívody
    jako dřív."""
    if m.version < 3:
        return False
    fr = m.fragment or {}
    buses = {e.get("id") for e in fr.get("elements", []) if isinstance(e, dict) and e.get("symbol_id") == "sb.busbar"}
    for w in fr.get("wires", []):
        for end in (w.get("a") or {}, w.get("b") or {}) if isinstance(w, dict) else ():
            if end.get("element_id") in buses and str(end.get("port", "")).startswith("B"):
                return True
    return False
