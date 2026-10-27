"""FV část generátoru (bez Qt): rozvržení řad střídačů (`plan`) a prvky před prvním AC článkem řetězce (`build`) –
střídače, stringy, DC rozvaděče (po trase a u technologie), DC vodiče, AC vodiče k hlavnímu AC článku, baterie.
Přesun 1. poloviny `generate._build_project` (refaktoring F1, krok 5) – pořadí prvků i `next_ref` beze změny."""
from __future__ import annotations

import math

from envocad.generator import context
from envocad.generator.boards.base import ChainContext, PvGeometry
from envocad.generator.boards.rfve_dc import dc_box_ref
from envocad.generator.context import (
    BATTERY_CABLE,
    BATTERY_ROW_EXTRA,
    DC_TECH_BOX_REF,
    INV_LABEL_SPACE,
    _int_attr,
    _s,
)
from envocad.generator.spec import (
    INVERTER_MODE_KEYS,
    _apply_inverter_component,
    _apply_optimizer_rules,
    _modules_per_optimizer,
    node_ref,
)
from envocad.library.templates import AC_CONDUCTORS, DC_CONDUCTORS
from envocad.model.calc import DC_INPUTS_PER_MPPT_DEFAULT, InverterData, string_ports
from envocad.model.project import PORT_PITCH, Element, Wire, WireEnd, element_symbol


def plan(spec: dict, combined: bool, per_inverter: bool = True) -> PvGeometry:
    """Pracovní souřadnice JPS ze sloučené specifikace: výšky řad střídačů, sloupce rozvaděčů, střídačů, hlavního
    AC článku a sítě. `combined` = rodinný dům s DC částí v rozvaděči FVE (stojí na místě DC rozvaděče u technologie).
    `per_inverter` False = jeden společný DC rozvaděč u technologie (RFVE.DC) pro 2+ střídače: lomy všech stringů
    před ním i za ním (před střídači) – `PvGeometry.common_dc`."""
    invs = spec.get("inverters") or []
    dc = spec["dc"]
    # svislé rozestupy řad střídačů podle počtu stringů; souřadnice jsou zatím pracovní – na list (formát, střed,
    # vnitřní rámeček, popisové pole) se obsah rozmístí až na konci (`frame.fit_sheet_to_content`)
    row_h = [max(60.0, 45.0 * max(len(inv.get("strings") or [1]), 1) + 15.0) for inv in invs]   # 45 mm na string (popisek nad ním)
    # hybridní střídač: baterie pod ním, v řadě se pro ni přidá místo (kabel jde krátce dolů, přes nic jiného)
    row_extra = [BATTERY_ROW_EXTRA if spec.get("battery") and i == 0 else 0.0 for i in range(len(invs))]
    total_h = sum(row_h) + sum(row_extra)
    y_top = 150.0 + total_h / 2
    n_route = max(0, int(dc.get("route_boxes") or 0))
    n_boxes = n_route + (1 if dc.get("tech_box") else 0)   # u rodinného domu je posledním „rozvaděčem“ rozvaděč FVE
    box_pitch = 85.0            # mezi rozvaděči se vejde popisek kabelu i dvojitý křížový odkaz
    x_str = 35.0
    n_max = max(len(inv.get("strings") or [1]) for inv in invs)
    n_all = sum(len(inv.get("strings") or [1]) for inv in invs)
    common_dc = not combined and bool(dc.get("tech_box")) and not per_inverter and len(invs) > 1
    lanes_in, lanes_fan = common_lanes(spec, row_h, row_extra, y_top, n_route) if common_dc else ([], [])
    # rozvaděč FVE: lomy všech stringů do jednoho bloku a vlevo od něj svislé úseky AC vodičů od střídačů; společný
    # RFVE.DC: vodiče shora a zdola sdílejí svislé dráhy (`common_lanes`) – jen tolik drah, kolik vodičů jde jedním směrem
    n_lanes = n_all + len(invs) if combined else ((max(lanes_in, default=-1) + 1) if common_dc else n_max)
    dc_first = len(invs) + (1 if (spec["ac"].get("distribution") or "bus") == "bus" else 2)   # za AC přívody (a svorkami X(n+1))
    # lomy stringů až za popisky kabelů u stringů; u společného RFVE.DC za rozvaděči po trase jen stringy jedné řady
    # (do rozvaděče po trase vede řada svého střídače) – lomy všech stringů jsou až před RFVE.DC
    n_first = n_max if common_dc and n_route else n_lanes
    x_box0 = x_str + 60.0 + 5.0 * n_first
    x_boxes = [x_box0 + j * box_pitch for j in range(n_boxes)]
    if (combined or common_dc) and n_boxes > 1:
        # rozvaděč FVE za rozvaděči po trase: popisek kabelu od rozvaděče po trase (~40 mm) se musí vejít před lomy
        # všech DC vodičů do RFVE (5 mm na string a na AC vodič střídače) – jinak popisek přetéká přes svůj lom
        # (společný RFVE.DC se sdílenými drahami: popisek kabelu ~40 mm + 2,5 mm volno před nejlevější drahou)
        x_boxes[-1] = x_boxes[-2] + max(box_pitch, (75.0 if common_dc else 70.0) + 5.0 * n_lanes)
    x_dc = 130.0                                                   # samostatný odpínač DC (bez rozvaděčů)
    # před střídačem: popisek kabelu za blokem rozvaděče + vějíř lomů (5 mm na string) před DC vstupy střídače
    # lomy před DC vstupy střídačů (u společného RFVE.DC sdílené dráhy střídačů nad a pod blokem)
    n_fan = lanes_fan[1] if common_dc else n_max
    x_inv = (x_boxes[-1] + max(80.0, 15.0 + INV_LABEL_SPACE + 5.0 * n_fan + 10.0)) if n_boxes else 200.0
    x_blk, x_grid = x_inv + 110.0, x_inv + 185.0   # mezi střídačem a rozvaděčem se vejde popisek AC kabelu
    if combined:   # rozvaděč FVE na místě DC rozvaděče u technologie (před střídači), síť za střídači
        x_blk, x_grid = x_boxes[-1], x_inv + 75.0
    return PvGeometry(row_h=row_h, row_extra=row_extra, y_top=y_top, n_route=n_route, n_boxes=n_boxes, x_str=x_str,
                      n_max=n_max, n_all=n_all, dc_first=dc_first, x_boxes=x_boxes, x_dc=x_dc, x_inv=x_inv,
                      x_blk=x_blk, x_grid=x_grid, common_dc=common_dc, lanes_in=lanes_in,
                      lanes_fan=lanes_fan[0] if common_dc else [], n_fan=n_fan)


def _ports_y(y0: float, n: int) -> list[float]:
    """y portů bloku rozvaděče s `n` přívody (`project.switchboard_symbol`, rozteč `PORT_PITCH`) se středem v `y0`."""
    half = max(20.0, n * PORT_PITCH + PORT_PITCH) / 2
    return [y0 + round((half - PORT_PITCH / 2 - k * PORT_PITCH) / 2.5) * 2.5 for k in range(n)]


def common_lanes(spec: dict, row_h: list[float], row_extra: list[float], y_top: float,
                 n_route: int) -> tuple[list[int], tuple[list[int], int]]:
    """Svislé dráhy vodičů společného RFVE.DC (2+ střídače, blok v y 150): (dráha každého přívodního vodiče – od stringu
    nebo rozvaděče po trase, 0 = nejvíc vlevo; (první dráha vějíře každého střídače před jeho DC vstupy, počet drah
    vějíře)). Vodiče shora (zdroj nad portem bloku) a zdola sdílejí dráhy – jejich svislé úseky leží v různých
    výškách a nekříží se (pořadí uvnitř směru doladí `layout._align_bends`). Vodorovný vodič (zdroj na výšce portu)
    dráhu nepotřebuje. Ve vějíři před střídači má střídač nejdál od bloku dráhy nejvíc vlevo (jako dřív), střídače
    nad blokem a pod ním počítají dráhy zvlášť."""
    invs = spec.get("inverters") or []
    n_strs = [len(inv.get("strings") or [1]) for inv in invs]
    n_all = sum(n_strs)
    ports = _ports_y(150.0, n_all)
    lanes, down_n, up_n, g = [], 0, 0, 0
    mids, port_mid = [], []
    y = y_top
    for i, n_str in enumerate(n_strs):
        y_mid = y - row_h[i] / 2
        mids.append(y_mid)
        src = _ports_y(y_mid, n_str) if n_route else [y - 35.0 - k * 45.0 for k in range(n_str)]
        own = []
        for k in range(n_str):
            own.append(ports[g])
            if src[k] > ports[g] + 1e-6:
                lanes.append(("d", down_n))
                down_n += 1
            elif src[k] < ports[g] - 1e-6:
                lanes.append(("u", up_n))
                up_n += 1
            else:
                lanes.append(("f", 0))
            g += 1
        port_mid.append(sum(own) / len(own))
        y -= row_h[i] + row_extra[i]
    total = max(down_n, up_n, 1)
    # dráhy shora: první vodič nejvíc vlevo, zdola: poslední nejvíc vlevo (`_align_bends` je stejně přeskládá)
    lane_in = [n if d == "d" else (up_n - 1 - n if d == "u" else total - 1) for d, n in lanes]
    lane_in = [x + (total - down_n if d == "d" else total - up_n if d == "u" else 0) for x, (d, _n) in zip(lane_in, lanes)]
    # vějíř: střídač nad svými porty (vodiče nahoru) / pod nimi – zvlášť, nejvzdálenější střídač vlevo
    lane0 = [0] * len(invs)
    acc = {"u": 0, "d": 0}
    order = sorted(range(len(invs)), key=lambda i: (-abs(mids[i] - port_mid[i]), i))
    for i in order:
        side = "u" if mids[i] > port_mid[i] else "d"
        lane0[i] = acc[side]
        acc[side] += n_strs[i]
    return lane_in, (lane0, max(acc.values()))


AC1_CONDUCTORS = ["L1", "N", "PE"]     # jednofázový střídač (ČSN EN 60445)
AC1_MIN_CROSS = 2.5                    # nejmenší průřez AC kabelu jednofázového střídače [mm²]
AC1_MAX_DROP_PCT = 3.0                 # úbytek napětí na AC kabelu (jako kontrola `calc.check_cables`)


def ac1_breaker_in(t: Element) -> str:
    """In jističe přívodu jednofázového střídače (`currents.inverter_breaker`: artikl, jinak 1,25 × P AC / 230 V);
    neznámý výkon / nad řadou → ""."""
    from envocad.generator.currents import inverter_breaker
    return inverter_breaker(t)[0]


def ac_cable_of(t: Element, ac: dict) -> tuple[list[str], str, str]:
    """Žíly, typ a průřez AC kabelu střídač → AC rozvaděč. Třífázový: `ac.cable` / `ac.cross` (5 žil). Jednofázový
    (`phases` 1): 3 žíly L1 N PE, průřez podle proudu střídače (P AC / 230 V, uložení B1, 2 zatížené žíly –
    `calc.min_cross` i pro In jističe přívodu `ac1_breaker_in`, nejméně 2,5 mm², a úbytek do 3 % na `ac.length`) a typ „CYKY-J 3x{průřez}“ (řada a izolace z `ac.cable`); neznámý výkon →
    průřez z `ac.cross`."""
    from envocad.generator.context import _num
    from envocad.model.calc import min_cross
    if (_num(t.attrs.get("phases")) or 3) != 1:
        return list(AC_CONDUCTORS), _s(ac.get("cable")), _s(ac.get("cross"))
    from envocad.model.calc import IZ_3, voltage_drop
    p_kw = _num(t.attrs.get("p_ac"))
    i_a = p_kw * 1000 / 230.0 if p_kw else 0.0
    i_n = _num(ac1_breaker_in(t)) or i_a
    x = min_cross(max(i_a, i_n), "B1", loaded=2) if i_a else None     # Iz ≥ In jističe přívodu (In ≤ Iz)
    length = _num(ac.get("length"))
    while x and length and voltage_drop(i_a, length, x, "1f", 230.0)[1] > AC1_MAX_DROP_PCT:
        x = next((c for c in sorted(IZ_3["B1"]) if c > x), None)     # i úbytek napětí (kontrola F7 3 %)
    cross = f"{max(x, AC1_MIN_CROSS):g}".replace(".", ",") if x else _s(ac.get("cross"))
    family = (_s(ac.get("cable")).split() or ["CYKY-J"])[0]
    return list(AC1_CONDUCTORS), f"{family} 3x{cross}", cross


def build(ctx: ChainContext) -> None:
    """Střídače, stringy, DC rozvaděče a vodiče až po přívody X1…Xn hlavního AC článku (`ctx.main`, vznikl dřív –
    `chain.create_main_block`), baterie pod prvním (hybridním) střídačem. Výsledek v `ctx` (inverters, strings, rows,
    ac_wires, dc_boxes, kwp)."""
    spec, p, s, geo, combined = ctx.spec, ctx.project, ctx.sheet, ctx.geo, ctx.combined
    blk = ctx.main
    invs = spec.get("inverters") or []
    mod, dc, ac = spec["module"], spec["dc"], spec["ac"]
    opt = spec.get("optimizer") or {}
    opt_per = float(opt.get("per_module") or 1) if opt.get("type") else 0.0
    opt_comp = ctx.opt_comp
    row_h, row_extra = geo.row_h, geo.row_extra
    n_route, n_boxes, x_boxes, dc_first, n_all = geo.n_route, geo.n_boxes, geo.x_boxes, geo.dc_first, geo.n_all
    x_str, x_dc, x_inv = geo.x_str, geo.x_dc, geo.x_inv
    p_total = 0.0
    ac_wires = ctx.ac_wires
    k_all = 0                   # pořadí stringu v rozvaděči FVE (přes všechny střídače)
    y = geo.y_top
    inverter_elements = ctx.inverters
    rows = ctx.rows             # prvky řady střídače (střídač, stringy, DC rozvaděče…) – rozdělení JPS na listy
    inverter_strings = ctx.strings
    dc_boxes = ctx.dc_boxes     # (blok, stringy, druh, č. střídače, střídač)
    common = geo.common_dc      # jeden společný RFVE.DC (2+ střídače) – přívody X1…Xn všech stringů, vývody za nimi
    n_tech = len(invs) if dc.get("tech_box") and not combined and not common else 0   # DC rozvaděče u technologie na střídač
    tech_ref = node_ref(spec, ctx.topology, "rfve_dc", default=DC_TECH_BOX_REF)
    common_gens: list[Element] = []
    lane0 = geo.lanes_fan if common else []
    n_in_lanes = max(geo.lanes_in, default=0) + 1
    for i, inv in enumerate(invs):
        strings = inv.get("strings") or [1]
        y_mid = y - row_h[i] / 2
        ref_t = inv.get("ref") or f"T{i + 1}"
        t = Element("fve.inverter_hybrid" if spec.get("battery") and i == 0 else "fve.inverter", x_inv, y_mid, attrs={
            "ref": ref_t, "type": _s(inv.get("type")), "p_ac": _s(inv.get("p_ac")), "phases": _s(inv.get("phases", 3)),
            "mppt": _s(inv.get("mppt")), "strings_per_mppt": _s(inv.get("strings_per_mppt")),
            "u_dc_max": _s(inv.get("u_dc_max")), "u_mppt_min": _s(inv.get("u_mppt_min")),
            "u_mppt_max": _s(inv.get("u_mppt_max")), "i_mppt_max": _s(inv.get("i_mppt_max")),
            "p_dc_max": _s(inv.get("p_dc_max"))}, component_id=inv.get("component_id"))
        for key in ("isc_mppt_max", *INVERTER_MODE_KEYS):   # jen zadané – starší specifikace beze změny výstupu
            if inv.get(key) not in (None, ""):
                t.attrs[key] = _s(inv[key])
        # artikl dřív než dopočet MPPT: jeho strings_per_mppt / mppt určí počet DC vstupů
        _apply_inverter_component(t, inv)
        if opt_comp is not None:
            _apply_optimizer_rules(t, inv, opt_comp)
        if t.symbol_id == "fve.inverter_hybrid" and ctx.topology is not None and ctx.topology.node("rfve") is not None:
            from envocad.generator.boards.eps import prepare_inverter
            prepare_inverter(t)            # rodinný dům: EPS vývod (BACKUP) vede na přepínač sítí v RFVE
        # pás svorek typu střídače (záloha, komunikace – `inverter_io`) visí pod značkou: místo v řadě
        from envocad.model.inverter_io import inverter_io
        row_extra[i] += 5.0 * len(inverter_io(t.attrs, t.symbol_id == "fve.inverter_hybrid"))
        # neznámé stringů na MPPT zůstane prázdné (kontrola pak proudy na MPPT nesčítá); výchozí 2 jen pro DC vstupy
        spm_known, mppt_known = _int_attr(t.attrs.get("strings_per_mppt")), _int_attr(t.attrs.get("mppt"))
        t.attrs["strings_per_mppt"] = str(spm_known) if spm_known else ""
        spm = spm_known or DC_INPUTS_PER_MPPT_DEFAULT
        # známé mppt: stringy rovnoměrně po MPPT (string k → MPPT k mod mppt), jinak DC1, DC2… za sebou (`calc.string_ports`)
        ports = string_ports(len(strings), InverterData(mppt=mppt_known, strings_per_mppt=spm_known))
        n_mppt = mppt_known or max(1, -(-len(strings) // spm))
        t.attrs["mppt"] = str(n_mppt)          # i „2.0“ / „2,0“ ze specifikace nebo artiklu → „2“
        s.elements.append(t)
        inverter_elements.append(t)
        row = [t]
        rows.append(row)
        gens: list[Element] = []
        inverter_strings.append(gens)
        for k, n_mod in enumerate(strings):
            ys = y - 35.0 - k * 45.0
            p_str = round(n_mod * float(str(mod.get("p_wp") or 0).replace(",", ".")) / 1000, 2)
            p_total += p_str
            g = Element("fve.pv_string", x_str, ys, attrs={
                "ref": p.next_ref("G"), "type": _s(mod.get("type")), "n_modules": _s(n_mod), "p_module": _s(mod.get("p_wp")),
                "p_string": f"{p_str:g} kWp", "voc": _s(mod.get("voc")), "vmp": _s(mod.get("vmp")),
                "isc": _s(mod.get("isc")), "beta_voc": _s(mod.get("beta_voc")),
                "n_optimizers": _s(round(n_mod * opt_per)) if opt_per else "", "optimizer": _s(opt.get("type")) if opt_per else ""},
                component_id=mod.get("component_id") or None)
            if opt_comp is not None and opt_per:
                # artikl optimizéru: parametry pro kontrolu stringů, počet zaokrouhlený nahoru (2:1 a lichý počet)
                g.attrs.update(opt_comp.optimizer_values(t.attrs.get("phases") or 3))
                g.attrs["optimizer"] = _s(opt.get("type"))
                g.attrs["n_optimizers"] = _s(math.ceil(n_mod / _modules_per_optimizer(opt_comp)))
            for key in ("imp", "u_sys_max", "manufacturer", "alpha_isc", "gamma_pmax"):   # jen zadané – starší specifikace beze změny výstupu
                if mod.get(key) not in (None, ""):
                    g.attrs[key] = _s(mod[key])
            s.elements.append(g)
            gens.append(g)
            row.append(g)
        # DC rozvaděče: po trase (jen SPD) a u technologie (pojistkové odpínače + SPD); stringy jimi procházejí odděleně
        boxes: list[Element] = []
        for j in range(n_boxes):
            kind = "tech" if (dc.get("tech_box") and j == n_boxes - 1) else "route"
            if kind == "tech" and combined:
                boxes.append(blk)
                break
            if kind == "tech" and common:
                if ctx.dc_common is None:   # blok vznikne u prvního střídače, list až za rozvaděči po trase
                    ctx.dc_common = Element("fve.switchboard", x_boxes[j], 150.0,
                                            attrs={"ref": tech_ref, "desc": "DC rozvaděč u technologie"})
                    s.elements.append(ctx.dc_common)
                boxes.append(ctx.dc_common)
                break
            desc = f"DC rozvaděč u {ref_t}" if kind == "tech" else (f"DC rozvaděč po trase {ref_t}" + (f" ({j + 1})" if n_route > 1 else ""))
            b = Element("fve.switchboard", x_boxes[j], y_mid, attrs={"ref": dc_box_ref(kind, i, n_tech, p, tech_ref), "desc": desc})
            s.elements.append(b)
            boxes.append(b)
            row.append(b)
            dc_boxes.append((b, gens, kind, i + 1, ref_t))
        n_str = len(gens)
        # porty bloku DC rozvaděče (viz switchboard_symbol): rozteč PORT_PITCH, shora dolů
        half = max(20.0, n_str * PORT_PITCH + PORT_PITCH) / 2
        port_y = [y_mid + round((half - PORT_PITCH / 2 - k * PORT_PITCH) / 2.5) * 2.5 for k in range(n_str)]
        n_in = max(2, n_mppt * spm, n_str)   # DC vstupy střídače (viz inverter_symbol)
        for k, g in enumerate(gens):
            port_inv = f"DC{ports[k]}"   # každý string má na střídači vlastní vstup – stringy se nespojují
            j_in = ports[k] - 1          # pořadí vstupu shora (DC1 nahoře)
            if boxes:
                prev, prev_port = g, "DC"
                for j, b in enumerate(boxes):
                    length = dc.get("length") if j == 0 else dc.get("route_length")
                    # string → 1. rozvaděč: lom každého stringu na vlastním x, aby se svislé úseky nekryly
                    pts = [] if j else [(b.x - 15.0 - 5.0 * (n_str - k), g.y), (b.x - 15.0 - 5.0 * (n_str - k), port_y[k])]
                    port_in, port_out = f"X{k + 1}", f"X{n_str + k + 1}"
                    if b is blk:   # rozvaděč FVE: stringy všech střídačů za AC přívody, lomy (doladí `_align_bends`)
                        port_in, port_out = f"X{dc_first + k_all}", f"X{dc_first + n_all + k_all}"
                        xj = b.x - 15.0 - 5.0 * len(invs) - 5.0 * (n_all - k_all)
                        pts = [(xj, prev.y if j == 0 else port_y[k]), (xj, port_y[k])]
                    elif b is ctx.dc_common:   # společný RFVE.DC: přívody X1…Xn všech stringů, vývody X(n+1)…
                        port_in, port_out = f"X{1 + k_all}", f"X{1 + n_all + k_all}"
                        xj = b.x - 15.0 - 5.0 * (n_in_lanes - geo.lanes_in[k_all])   # sdílené dráhy (`common_lanes`)
                        pts = [(xj, prev.y if j == 0 else port_y[k]), (xj, port_y[k])]
                    s.wires.append(Wire(WireEnd(prev.id, prev_port), WireEnd(b.id, port_in), conductors=list(DC_CONDUCTORS),
                                        points=pts,
                                        attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                               "length": _s(length), "method": "E"}))
                    prev, prev_port = b, port_out
                # vějíř lomů těsně před DC vstupy střídače (5 mm rozestup) – za popiskem kabelu, mimo značku střídače;
                # pořadí lomů bez křížení doladí `_align_bends`
                xb = t.x - 10.0 - 5.0 * ((geo.n_fan - lane0[i] - k) if common else (n_str - k))
                y_inv = t.y + (2.5 * (n_in - 1) - 5.0 * j_in if n_in > 2 else (5.0 if j_in == 0 else -5.0))
                s.wires.append(Wire(WireEnd(prev.id, prev_port), WireEnd(t.id, port_inv), conductors=list(DC_CONDUCTORS),
                                    points=[(xb, port_y[k]), (xb, y_inv)],
                                    attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                           "length": _s(dc.get("tech_length")), "method": "E"}))
            elif dc.get("disconnect"):
                q = Element("fve.dc_disconnect", x_dc, g.y, attrs={"ref": p.next_ref("Q"), "in_": _s(dc.get("disconnect_in") or 32),
                                                                  "poles": "2", "modules": "2"})
                s.elements.append(q)
                row.append(q)
                s.wires.append(Wire(WireEnd(g.id, "DC"), WireEnd(q.id, "1"), conductors=list(DC_CONDUCTORS),
                                    attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                           "length": _s(dc.get("length")), "method": "E"}))
                s.wires.append(Wire(WireEnd(q.id, "2"), WireEnd(t.id, port_inv), conductors=list(DC_CONDUCTORS), attrs={"ref": ""}))
            else:
                s.wires.append(Wire(WireEnd(g.id, "DC"), WireEnd(t.id, port_inv), conductors=list(DC_CONDUCTORS),
                                    attrs={"ref": p.next_ref("W"), "cable": _s(dc.get("cable")), "cross": _s(dc.get("cross")),
                                           "length": _s(dc.get("length")), "method": "E"}))
            k_all += 1
        common_gens.extend(gens)
        # AC vodič ke bloku rozvaděče – port podle přívodu (X1, X2…), doplní se po vytvoření listu
        conductors, cable, cross = ac_cable_of(t, ac)
        target, port_k = blk, i + 1
        for g in ctx.groups:              # skupina střídačů na jiném místě: vlastní RFVE.AC{n}, přívody od X1
            if i in g["idx"]:
                target, port_k = g["block"], g["idx"].index(i) + 1
        w_ac = Wire(WireEnd(t.id, "AC"), WireEnd(target.id, f"X{port_k}"), conductors=conductors,
                    attrs={"ref": p.next_ref("W"), "cable": cable, "cross": cross,
                           "length": _s(ac.get("length")), "method": "B1"})
        s.wires.append(w_ac)
        ac_wires.append(w_ac)
        y -= row_h[i] + row_extra[i]
    if ctx.dc_common is not None:   # list společného RFVE.DC za listy rozvaděčů po trase
        dc_boxes.append((ctx.dc_common, common_gens, "tech", 0, ""))
    if spec.get("battery"):
        b = spec["battery"]
        t0 = inverter_elements[0]
        # baterie přímo pod svým (hybridním) střídačem: port BAT dole (pod pásem svorek, je-li) → port DC baterie
        # nahoře, svisle 15 mm
        bat_y = element_symbol(p, t0, context._lib()).port("BAT").y
        bat = Element("fve.battery", t0.x, t0.y + bat_y - 25.0, attrs={
            "ref": "G" + str(len([e for e in s.elements if e.symbol_id == "fve.pv_string"]) + 1),
            "type": _s(b.get("type")), "e_kwh": _s(b.get("e_kwh")), "p_kw": _s(b.get("p_kw")),
            # katalogová baterie (`spec.battery.component_id`): výrobce, počet modulů věže, slave a BMS pro výkaz
            **{k: _s(b.get(k)) for k in ("manufacturer", "n_modules", "slave_type", "bms") if b.get(k)}},
            component_id=b.get("component_id") or None)
        s.elements.append(bat)
        rows[0].append(bat)
        bc = {k: b.get(k) if b.get(k) not in (None, "") else v for k, v in BATTERY_CABLE.items()}
        s.wires.append(Wire(WireEnd(t0.id, "BAT"), WireEnd(bat.id, "DC"), conductors=list(DC_CONDUCTORS),
                            attrs={"ref": p.next_ref("W"), "cable": _s(bc["cable"]), "cross": _s(bc["cross"]),
                                   "length": _s(bc["length"])}))
    ctx.kwp = p_total
