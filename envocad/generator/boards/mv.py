"""Přípojka VN: hlavní rozvaděč nn HR, transformátor, rozvaděč VN, elektroměrový rozvaděč RE (bez Qt). Přesun 1:1 z `generate.py`
(refaktoring F1, krok 4)."""
from __future__ import annotations

import math
import re

from envocad.generator.boards.base import ChainContext, ChainPorts
from envocad.generator.context import (
    AC_SWITCHBOARD_REF,
    MAIN_LV_BOARD_REF,
    _num,
    _num_or,
    _s,
    log,
)
from envocad.library.templates import (
    AC_CONDUCTORS,
    _el,
    _feed,
    _place_sequential,
    _wire,
)
from envocad.model.feed import FEED_SYMBOL
from envocad.model.project import Element, Project, Sheet, Wire, WireEnd
from envocad.model.topology import ChainNode

# ---- přípojka VN: hlavní rozvaděč nn HR, transformátor, rozvaděč VN -------------------------------------------------
LV_BREAKER_SIZES = (100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3200, 4000)
# vývody hlavního rozvaděče nn (FVE, spotřeba): i menší jističe pod nejmenším hlavním jističem
LV_FEEDER_SIZES = (16, 20, 25, 32, 40, 50, 63, 80, *LV_BREAKER_SIZES)
CT_PRIMARY_SIZES = (5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 150, 200, 250, 300, 400, 500, 600, 750, 800, 1000,
                    1200, 1250, 1500, 1600, 2000, 2500, 3000, 4000)
VN_FUSE_SIZES = (6.3, 10, 16, 20, 25, 31.5, 40, 50, 63, 80, 100)
VN_FUSE_FACTOR = 1.8          # pojistka VN transformátoru ≈ 1,8 × In VN (tabulky výrobců pojistek – ověřit)
VN_BREAKER_FROM_KVA = 1000.0  # nad 1000 kVA transformátorové pole s vypínačem a ochranou místo pojistek
U_LV, U_MV_DEFAULT = 400.0, 22000.0
VN_CONDUCTORS = ["L1", "L2", "L3"]
# sekundár MTP / MTN k elektroměru po fázích – napětí na svorky 2 5 8 a n na 11 (`fve.meter` `multipole.terminals`)
CT_CONDUCTORS = ["1S1", "1S2", "2S1", "2S2", "3S1", "3S2"]
VT_CONDUCTORS = ["1a", "2a", "3a", "n"]


def _next_size(value: float, sizes) -> float:
    """Nejmenší normalizovaná hodnota ≥ value (nad řadou největší)."""
    return next((x for x in sizes if x >= value - 1e-9), sizes[-1])


U_MV_RANGE = (1000.0, 52000.0)   # vn (ČSN EN 50160: 1 kV < Un ≤ 35 kV; řada Um do 52 kV) – mimo = chyba zadání
_VOLTAGE_RE = re.compile(r"\s*(\d{1,3}(?:[ .]\d{3})+|\d+)(?:,(\d+)|\.(\d{1,2}|\d{4,}))?\s*(kv|v)?(?![a-z])",
                         re.IGNORECASE)


def parse_voltage(v, default: float = U_MV_DEFAULT) -> float:
    """Napětí vn ve V z textu specifikace – čte se číslo na začátku textu (zbytek, např. „, 50 Hz“, se ignoruje):
    „22 kV“, „22kV“, „22,5 kV“, „22.5 kV“, „35 kV, 50 Hz“, „22000 V“, „22 000 V“, „22.000 V“ (mezera i tečka
    jako oddělovač tisíců), „22000“, „22“. Bez jednotky: pod 1000 = kV (vn se zadává v kV), jinak V. Prázdné →
    `default`. Nečitelné nebo mimo rozsah vn (`U_MV_RANGE`, 1–52 kV) → ValueError s českou hláškou (žádné tiché
    dosazení 22 kV)."""
    raw = _s(v)
    t = raw.strip().replace("\u00a0", " ").replace("\u202f", " ")
    if not t:
        return default
    m = _VOLTAGE_RE.match(t)
    if not m:
        raise ValueError(f"Napětí vn „{raw}“ nelze přečíst – zadejte např. „22 kV“ nebo „22000 V“.")
    whole, dec_comma, dec_dot, unit = m.groups()
    unit = (unit or "").lower()
    if unit == "kv" and "." in whole and " " not in whole and not (dec_comma or dec_dot):
        whole, dec_dot = whole.split(".", 1)   # „22.500 kV“ = 22,5 kV (tečka u kV je desetinná)
    x = float(re.sub(r"[ .]", "", whole) + "." + (dec_comma or dec_dot or "0"))
    if unit == "kv" or (not unit and x < 1000):
        x *= 1000
    lo, hi = U_MV_RANGE
    if not lo <= x <= hi:
        shown = voltage_label(x) or "0 kV"
        raise ValueError(f"Napětí vn „{raw}“ = {shown} je mimo rozsah vn {lo / 1000:g}–{hi / 1000:g} kV "
                         "– zadejte např. „22 kV“.")
    return x


def voltage_label(u_v: float | None) -> str:
    """22000 → „22 kV“, 22500 → „22,5 kV“ (text do výkresu); None (napětí nezadané) → "" – dosazená výchozí
    hodnota se do výkresu nepíše."""
    if not u_v:
        return ""
    return f"{u_v / 1000:g} kV".replace(".", ",")


STATIONS = {"kiosk": ("kiosková trafostanice", "P", "pole"),
            "kobky": ("zděná trafostanice", "K", "kobka"),
            "sloup": ("sloupová trafostanice", "", "")}
CELL_NAMES = {"pole": {"cable": "kabelové pole", "meas": "měřicí pole", "tr": "transformátorové pole"},
              "kobka": {"cable": "kabelová kobka", "meas": "měřicí kobka", "tr": "transformátorová kobka"}}


def station_kind(conn: dict) -> str:
    """Druh trafostanice: kiosk (výchozí, rozvaděč VN po polích) | kobky (zděná TS) | sloup (bez rozvaděče VN)."""
    k = _s(conn.get("station") or "kiosk").strip().lower()
    return k if k in STATIONS else "kiosk"


def station_label(conn: dict) -> str:
    """Text rámečku trafostanice v jednopólovém schématu (atribut `station` bloků): „TS1 kiosková trafostanice“."""
    ts = conn.get("ts") or {}
    desc = _s(ts.get("desc")) or STATIONS[station_kind(conn)][0]
    return f"{_s(ts.get('ref') or 'TS1')} {desc}".strip()


def connection_currents(conn: dict) -> dict:
    """Jmenovité proudy přípojky VN ze Sn transformátoru: In nn / vn, hlavní jistič nn, převod MTP, pojistky VN.
    Zadané `main_board.main_in`, `ct_ratio`, `fuse_vn` mají přednost. Sloupová TS měří vždy na nn."""
    tr = conn.get("transformer") or {}
    sn = _num_or(tr.get("sn"), 630.0)
    given_u = _s(conn.get("u_vn")).strip()
    u_mv = parse_voltage(given_u)          # nezadané: výpočet z 22 kV, do výkresu se napětí nepíše (`u_label` "")
    i_lv = sn * 1000 / (math.sqrt(3) * U_LV)
    i_mv = sn * 1000 / (math.sqrt(3) * u_mv)
    mb = conn.get("main_board") or {}
    main_in = _num_or(mb.get("main_in"), 0) or _next_size(i_lv, LV_BREAKER_SIZES)
    metering = _s(conn.get("metering") or "nn").strip().lower()
    if station_kind(conn) == "sloup":
        metering = "nn"
    i_ct = i_lv if metering == "nn" else i_mv
    ct = _s(conn.get("ct_ratio")) or f"{_next_size(i_ct, CT_PRIMARY_SIZES):g}/5 A"
    fuse = _s(conn.get("fuse_vn")) or f"{_next_size(i_mv * VN_FUSE_FACTOR, VN_FUSE_SIZES):g}".replace(".", ",")
    return {"sn": sn, "u_mv": u_mv, "u_label": voltage_label(u_mv if given_u else None), "i_lv": i_lv, "i_mv": i_mv,
            "main_in": f"{main_in:g}", "ct_ratio": ct,
            "fuse_vn": fuse, "metering": metering, "breaker_vn": sn > VN_BREAKER_FROM_KVA}


def _connection_blocks(p: Project, s: Sheet, spec: dict, blk: Element, x0: float) -> dict:
    """Bloky přípojky VN v blokovém schématu: RFVE.AC (XOUT) → hlavní rozvaděč nn HR → transformátor → rozvaděč VN → DS;
    u sloupové TS místo rozvaděče VN pojistky VN, svodiče přepětí a úsekový odpínač na sloupu. Rozvaděče nn a VN
    jsou napájené ze strany DS (přívod = XT u hlavního rozvaděče, XDS1/XDS2 u rozvaděče VN), FVE je vývod X1
    hlavního rozvaděče – bloky i transformátor jsou zrcadlené, aby přívody ležely vpravo (k DS) a vodiče vedly zleva
    doprava rovně. Spotřeba objektu (vývod X2) leží pod vývodem FVE, elektroměrový rozvaděč (měřicí obvody XMI/XMU
    od MTP/MTN) pod rozvaděčem s měřením. Všechny části trafostanice mají atribut `station` (rámeček TS)."""
    conn, ac = spec["connection"], spec["ac"]
    tr_spec, mb, vb = conn.get("transformer") or {}, conn.get("main_board") or {}, conn.get("mv_board") or {}
    eb = conn.get("meter_board") or {}
    kind = station_kind(conn)
    station = station_label(conn)
    c = connection_currents(conn)
    u = c["u_label"]
    x_hr = x0 + 85.0
    x_tr = x_hr + 75.0
    x_rvn = x_tr + 75.0
    x_grid = x_rvn + 70.0
    hr = Element("fve.switchboard", x_hr, 150.0, mirror=True, attrs={
        "ref": _s(mb.get("ref") or MAIN_LV_BOARD_REF), "desc": _s(mb.get("desc") or "hlavní rozvaděč nn"), "station": station})
    s.elements.append(hr)
    tr = Element("fve.transformer", x_tr, 150.0, mirror=True, attrs={
        "ref": p.next_ref("TR"), "type": _s(tr_spec.get("type")), "sn": _s(tr_spec.get("sn")),
        "ratio": _s(tr_spec.get("ratio")), "group": _s(tr_spec.get("group")), "uk": _s(tr_spec.get("uk")),
        "station": station})
    s.elements.append(tr)
    rvn = None
    pole: list[Element] = []
    if kind == "sloup":
        # na sloupu (tok zprava = od DS): úsekový odpínač → pojistky VN → transformátor, svodiče přepětí za pojistkami
        qs = Element("fve.switch_disconnector_vn", x_tr + 70.0, 150.0, mirror=True, attrs={
            "ref": p.next_ref("QS"), "type": "úsekový odpínač VN", "poles": "3", "station": station})
        fu = Element("fve.fuse_vn", x_tr + 40.0, 150.0, mirror=True, attrs={
            "ref": p.next_ref("FU"), "type": "pojistka VN", "in_": c["fuse_vn"], "poles": "3", "station": station})
        fv = Element("fve.surge_arrester", x_tr + 22.5, 130.0, rotation=270, attrs={
            "ref": p.next_ref("FV"), "type": "svodič přepětí VN", "poles": "3", "station": station})
        pole = [qs, fu, fv]
        s.elements.extend(pole)
        x_grid = x_tr + 110.0
    else:
        rvn = Element("fve.switchboard", x_rvn, 150.0, mirror=True, attrs={
            "ref": _s(vb.get("ref") or "RVN"), "desc": _s(vb.get("desc") or "rozvaděč VN"), "station": station})
        s.elements.append(rvn)
    re_ = Element("fve.switchboard", x_hr if c["metering"] == "nn" or rvn is None else x_rvn, 70.0, attrs={
        "ref": _s(eb.get("ref") or "RE"), "desc": _s(eb.get("desc") or "elektroměrový rozvaděč"), "station": station})
    s.elements.append(re_)
    grids = []
    for k in range(2 if conn.get("loop") and kind != "sloup" else 1):
        g = Element("fve.grid", x_grid, 150.0 - 10.0 * k, attrs={"ref": "", "voltage": f"3~ {u}, 50 Hz" if u else "3~ 50 Hz",
                                                                 "dso": _s(spec["grid"].get("dso"))})
        s.elements.append(g)
        grids.append(g)
    # spotřeba objektu: vývod X2 je vlevo (zrcadlený blok) – značka pod blokem, otočená portem nahoru
    load = Element("fve.load", x_hr, 110.0, attrs={"ref": "", "desc": _s(conn.get("load") or "spotřeba objektu")})
    s.elements.append(load)

    def cable(a, pa, b, pb, conductors, prefix, points=None, cross=None):
        s.wires.append(Wire(WireEnd(a.id, pa), WireEnd(b.id, pb), conductors=list(conductors), points=points or [],
                            attrs={"ref": p.next_ref("W"), "cable": _s(conn.get(f"{prefix}_cable")),
                                   "cross": _s(conn.get(cross or f"{prefix}_cross")),
                                   "length": _s(conn.get(f"{prefix}_length") or conn.get("meas_length")),
                                   "method": "D"}))

    def plain(a, pa, b, pb, conductors):          # spoj bez kabelu (na sloupu: vodiče, lana)
        s.wires.append(Wire(WireEnd(a.id, pa), WireEnd(b.id, pb), conductors=list(conductors), attrs={"ref": ""}))

    s.wires.append(Wire(WireEnd(blk.id, "XOUT"), WireEnd(hr.id, "X1"), conductors=list(AC_CONDUCTORS),
                        attrs={"ref": p.next_ref("W"), "cable": _s(ac.get("grid_cable")), "cross": _s(ac.get("grid_cross")),
                               "length": _s(ac.get("grid_length")), "method": "D"}))
    cable(hr, "XT", tr, "2", AC_CONDUCTORS, "tr")
    if rvn is not None:
        cable(tr, "1", rvn, "X1", VN_CONDUCTORS, "vn")
        for k, g in enumerate(grids):
            cable(rvn, f"XDS{k + 1}", g, "1", VN_CONDUCTORS, "vn")
    else:
        qs, fu, fv = pole
        plain(grids[0], "1", qs, "1", VN_CONDUCTORS)
        plain(qs, "2", fu, "1", VN_CONDUCTORS)
        plain(fu, "2", tr, "1", VN_CONDUCTORS)
        plain(fu, "2", fv, "1", VN_CONDUCTORS)
    # měřicí obvody do elektroměrového rozvaděče: proud z MTP (XMI), napětí z přípojnice nn / MTN (XMU)
    src = hr if c["metering"] == "nn" or rvn is None else rvn
    cable(src, "XMI", re_, "XMI", CT_CONDUCTORS, "meas_i", cross="meas_i_cross")
    cable(src, "XMU", re_, "XMU", AC_CONDUCTORS[:4] if src is hr else VT_CONDUCTORS, "meas_u", cross="meas_u_cross")
    # stávající rozvod objektu – bez kabelu (projektant doplní podle skutečnosti)
    s.wires.append(Wire(WireEnd(hr.id, "X2"), WireEnd(load.id, "1"), conductors=list(AC_CONDUCTORS), attrs={"ref": ""}))
    return {"hr": hr, "tr": tr, "rvn": rvn, "re": re_, "src": src, "pole": pole, "grids": grids, "load": load}


def inverters_ac_current(invs) -> float:
    """Součet jmenovitých AC proudů střídačů [A] z `p_ac` [kW] a `phases` (3f 400 V, 1f 230 V); neznámé p_ac = 0.
    Bere vygenerované prvky střídačů (`Element.attrs` – i s p_ac doplněným z artiklu `component_id`) nebo
    slovníky specifikace."""
    total = 0.0
    for inv in invs:
        a = inv.attrs if isinstance(inv, Element) else inv
        p_kw = _num(a.get("p_ac")) or 0.0
        one = (_num(a.get("phases")) or 3) == 1
        total += p_kw * 1000 / (230.0 if one else math.sqrt(3) * U_LV)
    return total


def fve_feeder_in(conn: dict, ac: dict, invs) -> tuple[str, str]:
    """In vývodu FVE v hlavním rozvaděči HR (přípojka VN) a důvod, když nejde splnit (jinak "").

    `invs` = vygenerované prvky střídačů (proud FVE z jejich `p_ac` a `phases`, i z artiklu) nebo slovníky
    specifikace. Zadané `main_board.fve_in` platí beze změny (selektivitu pak hlídá F7 `calc_selectivity`). Jinak
    nejbližší velikost ≥ max(Σ proudů střídačů, jistič střídače) (jako vývod FVE v RD / HR, B3; bez střídačů In
    hlavního vypínače RFVE.AC `ac.main_in`), omezená na největší jistič selektivní s hlavním jističem HR
    (In·1,6 ≤ hlavní jistič, `calc.SELECTIVITY_RATIO`; hlavní jistič je ze Sn transformátoru).

    Vývod musí unést proud FVE (součet střídačů) a nesmí být menší než jistič střídače v RFVE.AC (`ac.breaker_in`).
    Rozhodnutí: vývod FVE ≥ jistič střídače, NE 1,6 × jistič střídače – RFVE.AC má vlastní hlavní vypínač
    a selektivitu vůči jističům střídačů zajišťuje ten (a proud vývodu je součet střídačů); 1,6× by u malých
    trafostanic vývod zbytečně vyhnalo nad selektivní mez s hlavním jističem HR. Platí i pro zadané `ac.main_in`:
    menší než proud FVE → In se nedosadí. Když vyhovující vývod neexistuje, vrací ("", důvod) – In zůstane prázdné,
    prvek dostane `in_unresolved` a kontrola F7 hlásí chybu `breaker_no_in` s důvodem."""
    from envocad.model.calc import SELECTIVITY_RATIO
    mb = conn.get("main_board") or {}
    if _s(mb.get("fve_in")).strip():
        return _s(mb["fve_in"]).strip(), ""
    main_in = float(connection_currents(conn)["main_in"])
    given = _num_or(ac.get("main_in"), 125.0)
    from envocad.generator.currents import breaker_ins, fve_current
    i_fve = fve_current(invs)          # proud z artiklu (i_ac_max), jinak z P AC
    need = max([i_fve, *breaker_ins({"ac": ac}, invs)])
    # vývod jako u RD / HR na nn (B3): nejbližší velikost ≥ max(Σ proudů, jistič střídače); bez střídačů In hlavního
    # vypínače RFVE.AC. Zadaný hlavní vypínač RFVE.AC pod proudem FVE je chyba zadání (nedosazuje se)
    want = _next_size(need, LV_FEEDER_SIZES) if need else given
    selective = [x for x in LV_FEEDER_SIZES if x * SELECTIVITY_RATIO <= main_in + 1e-9]
    if selective and want <= selective[-1]:
        if not _s(ac.get("main_in_auto")) and given < need - 1e-9:
            why = (f"In vývodu FVE: hlavní vypínač RFVE.AC {given:g} A (ac.main_in) < proud FVE / jistič střídače "
                   f"{need:.0f} A – zvětšete ac.main_in, nebo zadejte main_board.fve_in")
            log.warning("Hlavní rozvaděč HR: %s", why)
            return "", why
        return f"{want:g}", ""
    if selective and selective[-1] >= need:
        log.info("Vývod FVE v HR omezen z %g A na %g A (selektivita s hlavním jističem %g A)",
                 want, selective[-1], main_in)
        return f"{selective[-1]:g}", ""
    why = (f"vývod FVE: In vývodu FVE < proud FVE – žádný jistič ≥ {need:.0f} A (proud FVE / jistič střídače) není "
           f"selektivní s hlavním jističem {main_in:g} A (poměr {SELECTIVITY_RATIO:g}) – zvětšete hlavní jistič / "
           "transformátor, nebo zadejte main_board.fve_in")
    log.warning("Hlavní rozvaděč HR: %s", why)
    return "", why


def _build_main_lv_board(p: Project, sheet: Sheet, conn: dict, ac: dict, invs=None,
                         fve_ref: str = AC_SWITCHBOARD_REF) -> None:
    """Hlavní rozvaděč HR (napájený z transformátoru): přívod XT → [MTP, měření na nn: sekundár → XMI, napětí
    z přípojnice → XMU k elektroměrovému rozvaděči] → hlavní jistič → přípojnice nn → vývody: FVE (jistič → X1
    k RFVE.AC, In `fve_feeder_in` z proudu vygenerovaných střídačů `invs`; vývod FVE ≥ jistič střídače, ne 1,6×),
    SPD T1, spotřeba objektu (jistič → X2, In nejvýš hlavní jistič / 1,6). In, které nejde splnit, zůstane prázdné
    s `in_unresolved` = důvod (chyba F7)."""
    from envocad.model.calc import SELECTIVITY_RATIO
    c = connection_currents(conn)
    mb = conn.get("main_board") or {}
    sheet.layout.params.setdefault("network", "3NPE, 50 Hz")
    sheet.layout.params.setdefault("un", "230/400 V")
    sheet.layout.params.setdefault("in_", c["main_in"])
    x0, y = 60.0, 165.0
    feed = _feed(p, sheet, "in", x0, y + 70, "", rot=180, desc="od transformátoru")
    feed.attrs["ref"] = "XT"
    qm = _el(p, sheet, "fve.breaker_mccb", x0, y + 10, "Q", rot=270, in_=c["main_in"], poles="3", modules="9")
    qm.attrs["chain"] = "main"
    bus = _el(p, sheet, "sb.busbar", x0 + 75, y - 25, "", desc="přípojnice nn", in_=c["main_in"],
              conductors=" ".join(AC_CONDUCTORS))
    bus.attrs["ref"] = "2"
    if c["metering"] == "nn":
        ta = _el(p, sheet, "fve.ct", x0, y + 40, "TA", rot=270, ratio=c["ct_ratio"], cls="0,5S", burden="5", n="3",
                 poles="3")
        # měřicí obvody vpravo nahoru: proud ze sekundáru MTP (XMI), napětí z přípojnice (XMU, jištění v RE)
        # svorky otočené portem dolů (kabel nahoru): vodič od MTP / z přípojnice přichází zespodu, ne přes kroužek
        xmi = _feed(p, sheet, "out", x0 + 105, y + 50, "", rot=180, desc="proudové obvody k RE")
        xmi.attrs["ref"] = "XMI"
        xmu = _feed(p, sheet, "out", x0 + 120, y + 50, "", rot=180, desc="napěťové obvody k RE")
        xmu.attrs["ref"] = "XMU"
        _wire(p, sheet, feed, "1", ta, "1", AC_CONDUCTORS)
        _wire(p, sheet, ta, "2", qm, "1", AC_CONDUCTORS)
        _wire(p, sheet, ta, "S", xmi, "1", CT_CONDUCTORS).points = [(x0 + 105, y + 40)]
        _wire(p, sheet, bus, "T8", xmu, "1", AC_CONDUCTORS[:4])
    else:
        _wire(p, sheet, feed, "1", qm, "1", AC_CONDUCTORS)
    _wire(p, sheet, qm, "2", bus, "IN", AC_CONDUCTORS)
    fve_in, why = fve_feeder_in(conn, ac, invs or [])
    qf = _el(p, sheet, "fve.breaker_mccb", x0 + 7.5, y - 60, "Q", rot=270, in_=fve_in, poles="3", modules="6")
    qf.attrs["chain"] = "fve_out"
    if not fve_in:
        qf.attrs["in_unresolved"] = why
    out_f = _feed(p, sheet, "out", x0 + 7.5, y - 95, "", desc=f"k {fve_ref} (FVE)" if fve_ref else "k AC rozvaděči FVE")
    out_f.attrs["ref"] = "X1"
    spd = _el(p, sheet, "fve.spd", x0 + 37.5, y - 60, "F", spd_type="T1", poles="4", modules="4")
    pe = _el(p, sheet, "sb.pe_bar", x0 + 37.5, y - 90, "X", kind="PE")
    # vývod spotřeby nejvýš In hlavního jističe / 1,6 (selektivita – poměr jako kontrola `calc_selectivity`);
    # žádný nevyhoví → prázdné In (F7), nic se nedosazuje
    sel = [x for x in LV_FEEDER_SIZES if x * SELECTIVITY_RATIO <= float(c["main_in"]) + 1e-9]
    load_in = _s(mb.get("load_in")) or (f"{sel[-1]:g}" if sel else "")
    qs = _el(p, sheet, "fve.breaker_mccb", x0 + 67.5, y - 60, "Q", rot=270, in_=load_in,
             poles="3", modules="6")
    if not load_in:
        qs.attrs["in_unresolved"] = (f"vývod spotřeby: žádný jistič není selektivní s hlavním jističem {c['main_in']} A"
                                     " – zadejte main_board.load_in")
    out_s = _feed(p, sheet, "out", x0 + 67.5, y - 95, "", desc=_s(conn.get("load") or "spotřeba objektu"))
    out_s.attrs["ref"] = "X2"
    _wire(p, sheet, bus, "1", qf, "1", AC_CONDUCTORS)
    _wire(p, sheet, qf, "2", out_f, "1", AC_CONDUCTORS)
    _wire(p, sheet, bus, "3", spd, "L", AC_CONDUCTORS[:4])
    _wire(p, sheet, spd, "PE", pe, "1", ["PE"])
    _wire(p, sheet, bus, "5", qs, "1", AC_CONDUCTORS)
    _wire(p, sheet, qs, "2", out_s, "1", AC_CONDUCTORS)
    _place_sequential(sheet, [qm, qf, qs, spd])


def _build_mv_board(p: Project, sheet: Sheet, conn: dict) -> None:
    """Rozvaděč VN napájený z DS, samostatná pole (kiosková TS) / kobky (zděná TS) pod přípojnicí – každý přístroj
    nese atribut `cell` (název pole, v jednopólovém schématu vlastní rámeček):
    kabelová pole (přívod XDS1, u smyčky i XDS2 ← kabelová koncovka ← odpínač VN z přípojnice; uzemňovač
    a kapacitní indikátor napětí na straně kabelu) → přípojnice VN → [měřicí pole: odpínač, MTP, MTN, sekundáry →
    XMI/XMU k elektroměrovému rozvaděči → přípojnice odběratele] → transformátorové pole (odpínač + pojistky VN
    s úderníkem, nad 1000 kVA vypínač VN s ochranou; uzemňovač, kabelová koncovka) → vývod XT k transformátoru.
    Přístroje se na DIN lišty nerozmísťují, rozvaděč nemá vícepól ani plán svorkovnice."""
    c = connection_currents(conn)
    u = c["u_label"]
    _desc, letter, word = STATIONS[station_kind(conn)]
    names = CELL_NAMES[word]
    sheet.layout.params.setdefault("network", "3~ 50 Hz")
    sheet.layout.params.setdefault("un", u)
    sheet.layout.params["voltage_level"] = "vn"     # bez vícepólu a plánu svorkovnice (`multipole.has_multipole`)
    x0, y = 60.0, 240.0 if c["metering"] == "vn" else 210.0
    cell_no = 0

    def cell(kind: str) -> str:
        nonlocal cell_no
        cell_no += 1
        return f"{letter}{cell_no} {names[kind]}"

    def el(sid, x, yy, prefix, cell_name, rot=270, **attrs):
        e = _el(p, sheet, sid, x, yy, prefix, rot=rot, **attrs)
        e.attrs["cell"] = cell_name
        return e

    bus = _el(p, sheet, "sb.busbar", x0 + 75, y, "", desc="přípojnice VN", conductors=" ".join(VN_CONDUCTORS))
    bus.attrs["ref"] = "1"
    port_x = lambda b, k: b.x - 67.5 + 15 * (k - 1)      # spodní port k přípojnice
    for k in range(2 if conn.get("loop") else 1):
        cn = cell("cable")
        x = port_x(bus, 1 + 3 * k)
        ql = el("fve.switch_disconnector_vn", x, y - 22.5, "Q", cn, type="odpínač VN", poles="3", modules="0")
        ke = el("fve.cable_end", x, y - 67.5, "XK", cn, poles="3", modules="0")
        qe = el("fve.earthing_switch", x + 12.5, y - 45, "Q", cn)
        pv = el("fve.voltage_indicator", x - 12.5, y - 45, "P", cn, type="VDS")
        feed = el(FEED_SYMBOL, x, y - 97.5, "", cn, rot=0, dir="in", desc="z DS")
        feed.attrs["ref"] = f"XDS{k + 1}"
        _wire(p, sheet, feed, "1", ke, "2", VN_CONDUCTORS)
        _wire(p, sheet, ke, "1", ql, "2", VN_CONDUCTORS)
        _wire(p, sheet, ql, "2", qe, "1", VN_CONDUCTORS).points = [(x + 12.5, y - 30)]
        _wire(p, sheet, ql, "2", pv, "1", VN_CONDUCTORS).points = [(x - 12.5, y - 30)]
        _wire(p, sheet, bus, str(1 + 3 * k), ql, "1", VN_CONDUCTORS)
    k_next = 7 if conn.get("loop") else 4
    xc = port_x(bus, k_next)
    last, port = bus, str(k_next)
    y_t = y
    if c["metering"] == "vn":
        cn = cell("meas")
        qm = el("fve.switch_disconnector_vn", xc, y - 22.5, "Q", cn, type="odpínač VN", poles="3", modules="0")
        ta = el("fve.ct", xc, y - 45, "TA", cn, ratio=c["ct_ratio"], cls="0,2S", burden="5", n="3", poles="3")
        tv = el("fve.vt", xc + 30, y - 62.5, "TV", cn, ratio=f"{u.split()[0]}/√3 / 0,1/√3 kV" if u else "", cls="0,2", n="3")
        # sekundáry vpravo dolů do vývodů měřicích obvodů (k elektroměrovému rozvaděči)
        xmi = el(FEED_SYMBOL, xc + 50, y - 60, "", cn, rot=0, dir="out", desc="proudové obvody k RE")
        xmi.attrs["ref"] = "XMI"
        xmu = el(FEED_SYMBOL, xc + 50, y - 95, "", cn, rot=0, dir="out", desc="napěťové obvody k RE")
        xmu.attrs["ref"] = "XMU"
        _wire(p, sheet, bus, port, qm, "1", VN_CONDUCTORS)
        _wire(p, sheet, qm, "2", ta, "1", VN_CONDUCTORS)
        _wire(p, sheet, ta, "2", tv, "1", VN_CONDUCTORS).points = [(xc + 30, y - 52.5)]
        _wire(p, sheet, ta, "S", xmi, "1", CT_CONDUCTORS).points = [(xc + 50, y - 45)]
        _wire(p, sheet, tv, "S", xmu, "1", VT_CONDUCTORS).points = [(xc + 30, y - 85), (xc + 50, y - 85)]
        # přípojnice odběratele pod měřicím polem (měření je v sérii s transformátorovým polem)
        y_t = y - 115
        bus2 = _el(p, sheet, "sb.busbar", xc + 60, y_t, "", desc="přípojnice VN odběratele",
                   conductors=" ".join(VN_CONDUCTORS))
        bus2.attrs["ref"] = "1.1"
        _wire(p, sheet, ta, "2", bus2, "T1", VN_CONDUCTORS)
        last, port = bus2, "1"
        xc = port_x(bus2, 1)
    cn = cell("tr")
    if c["breaker_vn"]:
        qt = el("fve.breaker_vn", xc, y_t - 22.5, "Q", cn, type="vypínač VN", protection="nadproudová 50/51",
                poles="3", modules="0")
        _wire(p, sheet, last, port, qt, "1", VN_CONDUCTORS)
        prot = qt
    else:
        qt = el("fve.switch_disconnector_vn", xc, y_t - 22.5, "Q", cn, type="odpínač VN", poles="3", modules="0")
        fu = el("fve.fuse_vn", xc, y_t - 45, "F", cn, in_=c["fuse_vn"], poles="3", modules="0", type="pojistka VN")
        _wire(p, sheet, last, port, qt, "1", VN_CONDUCTORS)
        _wire(p, sheet, qt, "2", fu, "1", VN_CONDUCTORS)
        prot = fu
    ke = el("fve.cable_end", xc, y_t - 85, "XK", cn, poles="3", modules="0")
    qe = el("fve.earthing_switch", xc + 12.5, y_t - 67.5, "Q", cn)
    out = el(FEED_SYMBOL, xc, y_t - 110, "", cn, rot=0, dir="out", desc="k transformátoru")
    out.attrs["ref"] = "X1"          # řadí se před vývody měřicích obvodů XMI/XMU (port bloku nahoře, k transformátoru)
    _wire(p, sheet, prot, "2", ke, "1", VN_CONDUCTORS)
    _wire(p, sheet, prot, "2", qe, "1", VN_CONDUCTORS).points = [(xc + 12.5, y_t - 55)]
    _wire(p, sheet, ke, "2", out, "1", VN_CONDUCTORS)


def _build_meter_board(p: Project, sheet: Sheet, conn: dict) -> None:
    """Elektroměrový rozvaděč: přívody měřicích obvodů XMI (proud z MTP) a XMU (napětí z přípojnice nn / MTN) →
    fakturační elektroměr (DS)."""
    c = connection_currents(conn)
    sheet.layout.params.setdefault("network", "měřicí obvody")
    sheet.layout.params.setdefault("un", "3×230/400 V, 5 A" if c["metering"] == "nn" else "3×100/√3 V, 5 A")
    x0, y = 60.0, 165.0
    xmi = _feed(p, sheet, "in", x0, y + 40, "", rot=180, desc="proudové obvody z MTP")
    xmi.attrs["ref"] = "XMI"
    xmu = _feed(p, sheet, "in", x0 + 30, y + 40, "", rot=180, desc="napěťové obvody")
    xmu.attrs["ref"] = "XMU"
    # elektroměr svisle (jako dřív v hlavním rozvaděči): proud zleva shora do 1, napětí zprava zdola do 2 – ve
    # vícepólu žíly míjí popisek elektroměru
    pm = _el(p, sheet, "fve.meter", x0 + 15, y, "P", rot=270, kind="fakturační (DS)", modules="0")
    xmi.x, xmu.x = x0 - 15, x0 + 45
    _wire(p, sheet, xmi, "1", pm, "1", CT_CONDUCTORS).points = [(x0 - 15, y + 20), (x0 + 15, y + 20)]
    _wire(p, sheet, xmu, "1", pm, "2", AC_CONDUCTORS[:4] if c["metering"] == "nn" else VT_CONDUCTORS).points = [
        (x0 + 45, y - 20), (x0 + 15, y - 20)]


def build_blocks(ctx: ChainContext) -> None:
    """Bloky přípojky VN za hlavním AC článkem (`_connection_blocks`): HR, TR, RVN / přístroje na sloupu, RE, DS.
    Kabel RFVE.AC → HR: `ac.grid_*` jen zadané uživatelem, jinak nejmenší průřez pro In vývodu FVE v HR (D3)."""
    ctx.mv = _connection_blocks(ctx.project, ctx.sheet, ctx.spec, ctx.main, ctx.geo.x_blk)
    ctx.grid = ctx.mv["grids"][0]
    raw_ac = ctx.raw.get("ac") if isinstance(ctx.raw.get("ac"), dict) else {}
    if _s(raw_ac.get("grid_cable")).strip() or _s(raw_ac.get("grid_cross")).strip():
        return
    from envocad.generator.chain import cable_for
    from envocad.model.calc import min_cross
    hr = ctx.mv["hr"]
    w = next((w for w in ctx.sheet.wires if w.touches(ctx.main.id) and w.touches(hr.id)), None)
    fin, _why = fve_feeder_in(ctx.spec.get("connection") or {}, ctx.spec["ac"], ctx.inverters)
    x = min_cross(_num(fin) or 0.0, "D")
    if w is not None and x:
        w.attrs.update({"cable": cable_for(ctx.spec, x), "cross": f"{x:g}".replace(".", ",")})


def _boards(ctx: ChainContext) -> list[tuple[str, Element, object]]:
    """(role, blok, funkce listu) rozvaděčů přípojky VN: HR, RVN (ne u sloupové TS), RE."""
    conn = ctx.spec.get("connection") or {}
    chain = ctx.mv
    out = [("hr", chain["hr"], lambda p, sh: _build_main_lv_board(p, sh, conn, ctx.spec["ac"], ctx.inverters,
                                                                  ctx.main.ref))]
    if chain["rvn"] is not None:
        out.append(("rvn", chain["rvn"], lambda p, sh: _build_mv_board(p, sh, conn)))
    out.append(("re", chain["re"], lambda p, sh: _build_meter_board(p, sh, conn)))
    return out


def build_sheets(ctx: ChainContext) -> None:
    """Listy přípojky VN (HR, RVN, RE) jen s volbou vestavěného kódu (`chain.<role>.builtin` / standard
    `ac_builtin`); jinak jsou rozvaděče trafostanice bloky bez listu (`block_attrs`, rozhodnutí 12)."""
    from envocad.generator.spec import builtin_wanted
    p = ctx.project
    for role, blk, make in _boards(ctx):
        if builtin_wanted(ctx.spec, ctx.topology, role):
            make(p, p.create_switchboard_sheet(blk))


def block_attrs(ctx: ChainContext) -> None:
    """Rozvaděče trafostanice bez listu (výchozí rozsah): porty bloku z přívodů / vývodů vestavěného listu (sestaví se
    naslepo v pomocném projektu – porty i jejich pořadí jako s listem) a údaje v popisku – hlavní jistič, vývod FVE,
    měření, pojistky / vypínač VN; jištění vývodu FVE `protect` (kontrola kabelu od RFVE.AC)."""
    from envocad.generator.spec import builtin_wanted
    from envocad.model.feed import is_feed_in, is_feed_out
    conn = ctx.spec.get("connection") or {}
    c = connection_currents(conn)
    for role, blk, make in _boards(ctx):
        if builtin_wanted(ctx.spec, ctx.topology, role):
            continue
        tmp = Sheet(kind="switchboard")
        make(Project(), tmp)
        blk.attrs["ports_in"] = " ".join(e.ref for e in tmp.elements if is_feed_in(e) and e.ref)
        blk.attrs["ports_out"] = " ".join(e.ref for e in tmp.elements if is_feed_out(e) and e.ref)
        if role == "hr":
            fin, _why = fve_feeder_in(conn, ctx.spec["ac"], ctx.inverters)
            blk.attrs["main"] = f"hlavní jistič {c['main_in']} A"
            blk.attrs["fve_out"] = f"jistič {fin} A" if fin else "jistič (In neurčené)"
            if fin:
                blk.attrs["protect"] = f"X1={fin}"
            if c["metering"] == "nn":
                blk.attrs["metering"] = f"na nn, MTP {c['ct_ratio']}"
        elif role == "rvn":
            blk.attrs["main"] = ("vypínač VN s ochranou" if c["breaker_vn"]
                                 else f"pojistky VN {c['fuse_vn']} A")
            if c["metering"] == "vn":
                blk.attrs["metering"] = f"na vn, MTP {c['ct_ratio']}, MTN"
        else:
            blk.attrs["metering"] = "fakturační elektroměr"


class MvBuilder:
    """Přípojka VN jako jeden složený builder (role hr, tr, rvn, grid a odbočka re topologie `vn`): bloky
    `_connection_blocks` (přívod HR = X1 od RFVE.AC, DS na XDS); HR, RVN, RE výchozí jen bloky (porty a údaje
    v atributech), listy s volbou `builtin`. Volá se jednou za průchod."""
    name = "mv"

    def block(self, ctx: ChainContext, node: ChainNode) -> Element | None:
        build_blocks(ctx)
        block_attrs(ctx)
        return ctx.mv["hr"]

    def ports(self, ctx: ChainContext, node: ChainNode) -> ChainPorts:
        return ChainPorts(("X1",), "XT")

    def build(self, ctx: ChainContext, node: ChainNode) -> None:
        build_sheets(ctx)


BUILDER = MvBuilder()
MV_ROLES = ("hr", "tr", "rvn", "re", "grid")   # role topologie `vn`, které obslouží `MvBuilder`
