"""Jednorázový generátor startovní sady symbolů FVE → envocad/library/builtin/fve/*.json.

Spustit: python tools/gen_builtin_fve.py
JSON soubory jsou zdroj pravdy; tento skript je jen pohodlný způsob, jak je vytvořit/přegenerovat.
Jednotky mm, Y nahoru, tok výkonu zleva doprava (vstup W, výstup E).
"""
from __future__ import annotations

import json
from pathlib import Path

BUSBAR_INPUTS = 12     # přívody T1…T12 sběrnice sb.busbar (= `generate.AC_MAX_INVERTERS_BUS`)
OUT = Path(__file__).resolve().parents[1] / "envocad" / "library" / "builtin" / "fve"


def L(x1, y1, x2, y2):
    return {"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2}


def R(x, y, w, h):
    return {"type": "rect", "x": x, "y": y, "w": w, "h": h}


def C(cx, cy, r):
    return {"type": "circle", "cx": cx, "cy": cy, "r": r}


def A(cx, cy, r, start, end):
    return {"type": "arc", "cx": cx, "cy": cy, "r": r, "start": start, "end": end}


def T(x, y, text, h=2.5, align="center"):
    return {"type": "text", "x": x, "y": y, "text": text, "height": h, "align": align}


def P(name, x, y, d):
    return {"name": name, "x": x, "y": y, "dir": d}


def attr(key, label, default="", show=False, fmt=""):
    d = {"key": key, "label": label, "default": default, "show": show}
    if fmt:
        d["fmt"] = fmt
    return d


# Kontakt dle IEC 60617: pohyblivý kontakt (nůž) je kloubem na straně portu 2 (výstup), volný konec u portu 1 –
# ve svislém kreslení shora dolů (vícepól) tedy kloub dole, nůž nahoře vychýlený do strany, jako v EPLAN.
CONTACT = [L(-7.5, 0, -2.5, 0), L(2.5, 0, -2, 4), L(2.5, 0, 7.5, 0)]          # spínací kontakt (jeden pól)
TRIP_X = [L(-4.3, 4.2, -2.3, 6.2), L(-4.3, 6.2, -2.3, 4.2)]                   # nadproudová spoušť (x) na volném konci nože
DISC_BAR = [L(-2.5, -1.5, -2.5, 1.5)]                                          # značka odpojovače/odpínače (pevný kontakt)


# kontaktní obraz přístroje (páry svorek, viz docs/LIBRARY_FORMAT.md) – prázdný = bez kontrol a rezerv v zrcadle
CONTACTS = attr("contacts", "Kontaktní obraz (např. 1/2 3/4 5/6 13/14)", "")


def MP(pole, common=None, link=True, link_at=(0, 2)):
    """Vícepólová podoba: `pole` se opakuje pro každý pól, `common` se kreslí jednou, `link` = vazba pólů."""
    return {"pole": pole, "common": common or [], "link": link, "link_at": list(link_at)}


REF = attr("ref", "Označení", "", True)
TYPE = attr("type", "Typ", "", True)
MFR = attr("manufacturer", "Výrobce")
POLES = attr("poles", "Póly", "3")
MOD = attr("modules", "Šířka [moduly]", "3")
PLOSS = attr("p_loss_w", "Ztrátový výkon při In [W]")
# rozsah provozní teploty okolí přístroje dle datasheetu (skryté; z artiklu t_min_c/t_max_c) – ověření oteplení
# po přístrojích (`model/thermal.py:device_temperatures`); prázdné = předpoklad DEFAULT_T_MAX_C
TEMP = [attr("t_min", "Teplota okolí min [°C]"), attr("t_max", "Teplota okolí max [°C]")]

SYMBOLS = [
    {
        "id": "fve.pv_string", "name": "FV string", "category": "Zdroje", "iec_ref": "G",
        "description": "Řetězec FV modulů (jednopólově)",
        "primitives": [
            R(-10, -7.5, 15, 15), L(-10, -7.5, 5, 7.5),
            # slunce
            C(-15, 10, 2), L(-15, 13, -15, 14.5), L(-12, 10, -10.5, 10), L(-12.9, 12.1, -11.8, 13.2),
            L(-17.1, 12.1, -18.2, 13.2),
            T(-2.5, -11, "FV", 2.5),
            L(5, 0, 7.5, 0),
        ],
        "ports": [P("DC", 7.5, 0, "E")],  # jednopólově: jedna čára = pár DC+/DC- (žíly vodiče)
        "attributes": [REF, TYPE, attr("n_modules", "Počet modulů", "", True, "{}× modul"), attr("p_module", "P modul [Wp]"),
                       attr("n_optimizers", "Počet optimizérů", "", True, "{}× optimizér"),
                       attr("optimizer", "Optimizér – typ", "", True),
                       attr("p_string", "P string [kWp]", "", True), attr("voc", "Uoc modulu STC [V]"),
                       attr("vmp", "Umpp modulu STC [V]"), attr("isc", "Isc modulu [A]"),
                       attr("beta_voc", "Tepl. součinitel Uoc [%/K]", "-0.27"),
                       # z artiklu FV modulu (skryté) – kontrola stringů a průvodce (`model/calc.py`)
                       attr("imp", "Impp modulu STC [A]"), attr("u_sys_max", "Max. napětí systému modulu [V]"),
                       # teplotní součinitele [%/K]: oba zadané → Umpp(t) s γ_Pmax − α_Isc místo β_Voc
                       attr("gamma_pmax", "Tepl. součinitel Pmax [%/K]"), attr("alpha_isc", "Tepl. součinitel Isc [%/K]")],
        "label_pos": {"x": -10, "y": 28},   # popisek nad značkou – vodič vpravo zůstane volný
    },
    {
        "id": "fve.dc_disconnect", "name": "Odpínač DC", "category": "Spínání", "iec_ref": "Q",
        "description": "Odpínač DC (např. v DC rozvaděči nebo ve střídači)",
        "primitives": [L(-7.5, 0, -2.5, 0), L(2.5, 0, -2, 4), L(2.5, 0, 7.5, 0), L(-2.5, -1.5, -2.5, 1.5),
                       L(-2.5, -1.5, -2.5, 1.5), T(0, 6, "DC", 2)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, MFR, attr("un", "Un [V DC]"), attr("in_", "In [A]", "", True),
                       attr("poles", "Póly", "2"), attr("modules", "Šířka [moduly]", "2"), *TEMP],
        "multipole": MP(CONTACT + DISC_BAR, [T(0, 6, "DC", 2)]),
        "label_pos": {"x": -5, "y": -6},
    },
    {
        "id": "fve.fuse", "name": "Pojistka", "category": "Jištění", "iec_ref": "F",
        "description": "Pojistka (gPV / gG)",
        "primitives": [R(-5, -2.5, 10, 5), L(-7.5, 0, 7.5, 0)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, MFR, attr("in_", "In [A]", "", True), attr("char", "Charakteristika", "gPV"),
                       attr("poles", "Póly", "1"), attr("modules", "Šířka [moduly]", "1"), PLOSS, *TEMP],
        "multipole": MP([R(-5, -2.5, 10, 5), L(-7.5, 0, 7.5, 0)], link=False),
        "label_pos": {"x": -5, "y": 4},
    },
    {
        "id": "fve.fuse_disconnect", "name": "Pojistkový odpínač", "category": "Jištění", "iec_ref": "F", "function_class": ["F", "Q"],
        "description": "Pojistkový odpínač (pojistka ve vyklápěcím držáku) – DC rozvaděč u technologie, gPV",
        "primitives": [L(-7.5, 0, -2.5, 0), L(2.5, 0, -2, 4), L(2.5, 0, 7.5, 0), L(-2.5, -1.5, -2.5, 1.5),
                       {"type": "polyline", "points": [[-1.84, 2.66], [-0.65, 4.00], [2.34, 1.34], [1.15, -0.00]], "closed": True}],  # pojistka na noži
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, MFR, attr("in_", "In [A]", "", True), attr("char", "Charakteristika", "gPV"),
                       attr("un", "Un [V DC]", "1000"), attr("poles", "Póly", "2"), attr("modules", "Šířka [moduly]", "2"), PLOSS, *TEMP],
        "multipole": MP([L(-7.5, 0, -2.5, 0), L(2.5, 0, -2, 4), L(2.5, 0, 7.5, 0), L(-2.5, -1.5, -2.5, 1.5), {"type": "polyline", "points": [[-1.84, 2.66], [-0.65, 4.00], [2.34, 1.34], [1.15, -0.00]], "closed": True}]),
        "label_pos": {"x": -5, "y": -6},
    },
    {
        "id": "fve.spd", "name": "Svodič přepětí (SPD)", "category": "Jištění", "iec_ref": "F", "function_class": ["F", "SPD"],
        "description": "Svodič přepětí, typ 1/2, DC nebo AC",
        "primitives": [R(-2.5, -5, 5, 10), L(0, 5, 0, 7.5), L(0, -5, 0, -7.5), L(-2, -3.5, 2, 3.5),
                       L(1, 3.5, 2, 3.5), L(2, 2.5, 2, 3.5)],
        "ports": [P("L", 0, 7.5, "N"), P("PE", 0, -7.5, "S")],
        "attributes": [REF, TYPE, MFR, attr("spd_type", "Typ SPD", "T2", True),
                       # do výkresu (proč SPD nemá vlastní pojistku): Uc, ochranná úroveň Up, zkratová odolnost ISCPV
                       attr("uc", "Uc [V]", "", True, "Uc {} V"), attr("up", "Up [kV]", "", True, "Up ≤ {} kV"),
                       attr("iscpv", "ISCPV [kA]", "", True, "ISCPV {} kA"),
                       POLES, attr("modules", "Šířka [moduly]", "4"), *TEMP],
        "multipole": MP([R(-2.5, -5, 5, 10), L(0, 5, 0, 7.5), L(0, -5, 0, -7.5), L(-2, -3.5, 2, 3.5), L(1, 3.5, 2, 3.5), L(2, 2.5, 2, 3.5)], link=False),
        "label_pos": {"x": 4, "y": 2},
    },
    {
        "id": "fve.inverter", "name": "Střídač", "category": "Střídače a měniče", "iec_ref": "T",
        "description": "Síťový střídač DC/AC",
        "primitives": [R(-10, -10, 20, 20), L(-10, -10, 10, 10), T(-5, 0.5, "DC", 2.5), T(5, -6, "AC", 2.5),
                       L(-5.5, 6, -1.5, 6), L(-5.5, 4.5, -3.5, 4.5), L(-2.5, 4.5, -1.5, 4.5),
                       A(2.5, -1.5, 1.5, 0, 180), A(5.5, -1.5, 1.5, 180, 360)],
        "ports": [P("DC1", -10, 5, "W"), P("DC2", -10, -5, "W"), P("AC", 10, 0, "E")],  # DC vstupy (MPPT)
        "attributes": [REF, TYPE, attr("p_ac", "P AC [kW]", "", True, "{} kW"), attr("p_dc_max", "P DC max [kWp]"),
                       attr("mppt", "Počet MPPT"), attr("phases", "Fáze", "3"), attr("u_dc_max", "U DC max [V]"),
                       attr("u_mppt_min", "U MPPT min [V]"), attr("u_mppt_max", "U MPPT max [V]"),
                       attr("i_mppt_max", "I max na MPPT [A]"), attr("strings_per_mppt", "Stringů na MPPT"),
                       attr("isc_mppt_max", "Isc max na MPPT [A]")],
        "label_pos": {"x": -10, "y": 20},
    },
    {
        "id": "fve.inverter_hybrid", "name": "Hybridní střídač", "category": "Střídače a měniče", "iec_ref": "T",
        "description": "Hybridní střídač s bateriovým vstupem",
        "primitives": [R(-10, -10, 20, 20), L(-10, -10, 10, 10), T(-5, 0.5, "DC", 2.5), T(5, -6, "AC", 2.5),
                       L(-5.5, 6, -1.5, 6), L(-5.5, 4.5, -3.5, 4.5), L(-2.5, 4.5, -1.5, 4.5),
                       A(2.5, -1.5, 1.5, 0, 180), A(5.5, -1.5, 1.5, 180, 360), T(0, -9.0, "BAT", 2)],
        "ports": [P("DC1", -10, 5, "W"), P("DC2", -10, -5, "W"), P("AC", 10, 0, "E"), P("BAT", 0, -10, "S")],
        "attributes": [REF, TYPE, attr("p_ac", "P AC [kW]", "", True, "{} kW"), attr("p_dc_max", "P DC max [kWp]"),
                       attr("mppt", "Počet MPPT"), attr("phases", "Fáze", "3"), attr("u_dc_max", "U DC max [V]"),
                       attr("u_mppt_min", "U MPPT min [V]"), attr("u_mppt_max", "U MPPT max [V]"),
                       attr("i_mppt_max", "I max na MPPT [A]"), attr("strings_per_mppt", "Stringů na MPPT"),
                       attr("isc_mppt_max", "Isc max na MPPT [A]")],
        "label_pos": {"x": -10, "y": 20},
    },
    {
        "id": "fve.battery", "name": "Bateriové úložiště", "category": "Zdroje", "iec_ref": "G",
        "description": "Akumulátor / BESS",
        "primitives": [L(0, 7.5, 0, 5), L(-5, 5, 5, 5), L(-2.5, 3, 2.5, 3), L(-5, 1, 5, 1), L(-2.5, -1, 2.5, -1),
                       L(0, -1, 0, -2.5), R(-7.5, -7.5, 15, 17.5), T(0, -6, "BESS", 2)],
        "ports": [P("DC", 0, 10, "N")],
        "attributes": [REF, TYPE, attr("e_kwh", "Kapacita [kWh]", "", True, "{} kWh"), attr("p_kw", "Výkon [kW]", fmt="{} kW")],
        "label_pos": {"x": 9, "y": 2},
    },
    {
        "id": "fve.breaker_mcb", "name": "Jistič", "category": "Jištění", "iec_ref": "F", "function_class": ["F", "Q"],
        "description": "Jistič (MCB)",
        "primitives": [L(-7.5, 0, -2.5, 0), L(2.5, 0, -2, 4), L(2.5, 0, 7.5, 0),
                       L(-4.3, 4.2, -2.3, 6.2), L(-4.3, 6.2, -2.3, 4.2)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, MFR, attr("in_", "In [A]", "", True), attr("char", "Charakteristika", "B"),
                       POLES, MOD, attr("icu", "Icu [kA]", "6"), PLOSS, *TEMP],
        "multipole": MP(CONTACT + TRIP_X),
        "label_pos": {"x": -5, "y": -6},
    },
    {
        "id": "fve.breaker_mccb", "name": "Výkonový jistič", "category": "Jištění", "iec_ref": "Q", "function_class": ["Q", "F"],
        "description": "Kompaktní výkonový jistič (MCCB)",
        "primitives": [L(-7.5, 0, -2.5, 0), L(2.5, 0, -2, 4), L(2.5, 0, 7.5, 0),
                       L(-4.3, 4.2, -2.3, 6.2), L(-4.3, 6.2, -2.3, 4.2), R(-6, -3.5, 12, 10.5)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, MFR, attr("in_", "In [A]", "", True), attr("ir", "Ir [A]"), POLES,
                       attr("modules", "Šířka [moduly]", "6"), attr("icu", "Icu [kA]"), PLOSS, *TEMP],
        "multipole": MP(CONTACT + TRIP_X, [R(-6, -3.5, 12, 10.5)]),
        "label_pos": {"x": -5, "y": -7},
    },
    {
        "id": "fve.switch_disconnector", "name": "Odpínač", "category": "Spínání", "iec_ref": "Q",
        "description": "Odpínač AC (hlavní vypínač, odpínač FVE)",
        "primitives": [L(-7.5, 0, -2.5, 0), L(2.5, 0, -2, 4), L(2.5, 0, 7.5, 0), L(-2.5, -1.5, -2.5, 1.5)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, MFR, attr("in_", "In [A]", "", True), POLES, MOD, PLOSS, *TEMP],
        "multipole": MP(CONTACT + DISC_BAR),
        "label_pos": {"x": -5, "y": -6},
    },
    {
        "id": "fve.contactor", "name": "Stykač", "category": "Spínání", "iec_ref": "K", "function_class": ["K", "Q"],
        "description": "Stykač (např. pro odpojení FVE od DS – NS)",
        "primitives": [L(-7.5, 0, -2.5, 0), L(2.5, 0, -2, 4), L(2.5, 0, 7.5, 0), A(-3.5, 0, 1, -90, 90)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, MFR, attr("in_", "In [A]", "", True), POLES, MOD, PLOSS, CONTACTS, *TEMP],
        "multipole": MP(CONTACT + [A(-3.5, 0, 1, -90, 90)]),
        "label_pos": {"x": -5, "y": -6},
    },
    {
        "id": "fve.meter", "name": "Elektroměr", "category": "Měření", "iec_ref": "P",
        "description": "Elektroměr (fakturační / podružný)",
        "primitives": [C(0, 0, 5), T(0, -1, "kWh", 2), L(-7.5, 0, -5, 0), L(5, 0, 7.5, 0)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, MFR, attr("kind", "Druh", "fakturační"), attr("modules", "Šířka [moduly]", "4"), *TEMP],
        "label_pos": {"x": -5, "y": 6.5},
    },
    {
        "id": "fve.grid", "name": "Distribuční síť", "category": "Síť a zátěž", "iec_ref": "",
        "description": "Přípojka k distribuční soustavě",
        "primitives": [L(-7.5, 0, -2.5, 0), C(2.5, 0, 5), L(-1, 3.5, 6, -3.5), L(-1, -3.5, 6, 3.5),
                       T(2.5, 7, "DS", 2.5)],
        "ports": [P("1", -7.5, 0, "W")],
        "attributes": [REF, attr("voltage", "Napětí", "3×400 V, 50 Hz", True), attr("dso", "Provozovatel DS", "")],
        "label_pos": {"x": -5, "y": -8},
    },
    {
        "id": "fve.load", "name": "Spotřeba objektu", "category": "Síť a zátěž", "iec_ref": "",
        "description": "Stávající rozvod / spotřeba objektu",
        "primitives": [L(-7.5, 0, -5, 0), R(-5, -5, 15, 10), T(2.5, -1, "Spotřeba", 2)],
        "ports": [P("1", -7.5, 0, "W")],
        "attributes": [REF, attr("desc", "Popis", "", True)],
        "label_pos": {"x": -5, "y": 6.5},
    },
    {
        "id": "fve.transformer", "name": "Transformátor", "category": "Síť a zátěž", "iec_ref": "T",
        "description": "Transformátor VN/NN",
        "primitives": [L(-10, 0, -7.5, 0), C(-2.5, 0, 5), C(2.5, 0, 5), L(7.5, 0, 10, 0)],
        "ports": [P("1", -10, 0, "W"), P("2", 10, 0, "E")],
        "attributes": [REF, TYPE, attr("sn", "Sn [kVA]", "", True), attr("ratio", "Převod")],
        "label_pos": {"x": -7.5, "y": 6.5},
    },
    {
        "id": "fve.terminal", "name": "Uzel / svorka", "category": "Svorky a propojení", "iec_ref": "X",
        "description": "Spojovací uzel – větvení vodičů",
        "primitives": [C(0, 0, 1)],
        "ports": [P("N", 0, 2.5, "N"), P("E", 2.5, 0, "E"), P("S", 0, -2.5, "S"), P("W", -2.5, 0, "W")],
        "attributes": [REF],
        "label_pos": {"x": 2, "y": 2},
    },
    {
        "id": "fve.interrupt", "name": "Přerušovací bod", "category": "Svorky a propojení", "iec_ref": "",
        "description": "Potenciál pokračuje jinde (na jiném listu / místě) – páruje se podle označení",
        "primitives": [L(-7.5, 0, -2.5, 0), {"type": "polyline", "points": [[-2.5, 2.5], [2.5, 0], [-2.5, -2.5]], "closed": True}],
        "ports": [P("1", -7.5, 0, "W")],
        "attributes": [attr("ref", "Označení potenciálu", "", True), attr("desc", "Popis"),
                       attr("star_source", "Zdroj hvězdy (1 = ano)", "")],
        "label_pos": {"x": -5, "y": 4},
    },
    {
        "id": "fve.earth", "name": "Uzemnění", "category": "Svorky a propojení", "iec_ref": "",
        "description": "Zemnicí svorka / PE",
        "primitives": [L(0, 5, 0, 0), L(-4, 0, 4, 0), L(-2.5, -1.5, 2.5, -1.5), L(-1, -3, 1, -3)],
        "ports": [P("PE", 0, 5, "N")],
        "attributes": [REF],
        "label_pos": {"x": 5, "y": 0},
    },
    {
        "id": "fve.switchboard", "name": "Rozvaděč (blok)", "category": "Rozvaděče", "iec_ref": "R", "function_class": [],
        "description": "Rozvaděč jako blok (odkaz na samostatný list)",
        "primitives": [R(-15, -10, 30, 20), T(0, 11.5, "ROZVADĚČ", 2)],
        "ports": [P("1", -15, 0, "W"), P("2", 15, 0, "E"), P("3", 0, 10, "N"), P("4", 0, -10, "S")],
        "attributes": [REF, attr("desc", "Popis", "", True), attr("sheet", "Odkaz na list")],
        "label_pos": {"x": -15, "y": -13},
    },
    {
        "id": "sb.rcd", "name": "Proudový chránič", "category": "Jištění", "iec_ref": "F", "function_class": ["F", "Q"],
        "description": "Proudový chránič (RCD)",
        "primitives": [L(-7.5, 0, -2.5, 0), L(2.5, 0, -2, 4), L(2.5, 0, 7.5, 0),
                       {"type": "polyline", "points": [[-1, -2], [1, -2], [0, -4.5]], "closed": True}],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, MFR, attr("in_", "In [A]", "", True), attr("idn", "IΔn [mA]", "30", True),
                       attr("rcd_type", "Typ", "A"), attr("poles", "Póly", "4"), attr("modules", "Šířka [moduly]", "4"), PLOSS, *TEMP],
        "multipole": MP(CONTACT, [{"type": "polyline", "points": [[-1, -2], [1, -2], [0, -4.5]], "closed": True}]),
        "label_pos": {"x": -5, "y": -7},
    },
    {
        "id": "sb.rcbo", "name": "Jistič s chráničem", "category": "Jištění", "iec_ref": "F", "function_class": ["F", "Q"],
        "description": "Proudový chránič s nadproudovou ochranou (RCBO)",
        "primitives": [L(-7.5, 0, -2.5, 0), L(2.5, 0, -2, 4), L(2.5, 0, 7.5, 0), L(-4.3, 4.2, -2.3, 6.2), L(-4.3, 6.2, -2.3, 4.2),
                       {"type": "polyline", "points": [[0, -2], [2, -2], [1, -4.5]], "closed": True}],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, MFR, attr("in_", "In [A]", "", True), attr("char", "Charakteristika", "B"),
                       attr("idn", "IΔn [mA]", "30", True), attr("poles", "Póly", "2"), attr("modules", "Šířka [moduly]", "2"), PLOSS, *TEMP],
        "multipole": MP(CONTACT + TRIP_X, [{"type": "polyline", "points": [[0, -2], [2, -2], [1, -4.5]], "closed": True}]),
        "label_pos": {"x": -5, "y": -7},
    },
    {
        "id": "sb.main_switch", "name": "Hlavní vypínač", "category": "Spínání", "iec_ref": "Q",
        "description": "Hlavní vypínač rozvaděče",
        "primitives": [L(-7.5, 0, -2.5, 0), L(2.5, 0, -2, 4), L(2.5, 0, 7.5, 0), L(-2.5, -1.5, -2.5, 1.5),
                       C(2.5, 0, 0.8), T(0, 6, "HV", 2)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, MFR, attr("in_", "In [A]", "", True), POLES, MOD, PLOSS, *TEMP],
        "multipole": MP(CONTACT + DISC_BAR, [C(2.5, 0, 0.8), T(0, 6, "HV", 2)]),
        "label_pos": {"x": -5, "y": -6},
    },
    {
        "id": "sb.busbar", "name": "Sběrnice (rozvodný vodič)", "category": "Svorky a propojení", "iec_ref": "",
        "description": "Rozvod potenciálů vodičem jako v EPLAN: ve vícepólu vodorovné čáry L1 L2 L3 N PE přes stranu "
                       "s názvy potenciálů na koncích, přístroje se na ně napojují odbočkou; 1 vstup, 12 přívodů shora, "
                       "12 vývodů zdola",
        "primitives": [{"type": "polyline", "points": [[-75, 0], [105, 0]], "closed": False},
                       {"type": "polyline", "points": [[-75, 1], [105, 1]], "closed": False}],
        # porty: IN vlevo nahoře, T1…T12 shora (přívody, jističe od střídačů – generátor: nejvýš 12 střídačů), 1…12 zdola (vývody) – šablona
        # AC rozvaděče potřebuje SPD + až 9 vývodů + PE (`templates.AC_MAX_OUTPUTS`, `BUSBAR_OUTPUTS`)
        "ports": [P("IN", -75, 5, "N")] + [P(f"T{i + 1}", -60 + i * 15, 5, "N") for i in range(BUSBAR_INPUTS)]
                 + [P(f"{i + 1}", -67.5 + i * 15, -5, "S") for i in range(12)],
        "attributes": [attr("ref", "Označení (předpona potenciálů, např. 1 → 1L1)", "", True), attr("desc", "Popis", "", True),
                       attr("in_", "In [A]"), attr("conductors", "Vodiče", "L1 L2 L3 N PE")],
        "label_pos": {"x": -75, "y": 7.5},
    },
    {
        "id": "sb.feed_in", "name": "Přívod", "category": "Svorky a propojení", "iec_ref": "X",
        "description": "Přívodní svorky rozvaděče (vazba na nadřazený list)",
        # jen svorka: kroužek, krátký vnější vývod nahoru (kabel zvenku) – bez šipek
        "primitives": [C(0, 0, 1.5), L(0, -1.5, 0, -5), L(0, 1.5, 0, 5), T(0, 7, "PŘÍVOD", 2)],
        "ports": [P("1", 0, -5, "S")],
        "attributes": [REF, attr("desc", "Popis", "", True), attr("from", "Odkud", "", True), attr("cable", "Kabel"),
                       attr("terminal", "Svorka č.", "")],
        # ve vícepólu: svorka na každou žílu (kroužek s číslem) a krátký vnější vývod, bez šipek a nápisů
        "multipole": MP([C(0, -2.5, 1.5), L(0, -4, 0, -5), L(0, -1, 0, 3)], [], link=False),
        "label_pos": {"x": 7, "y": 0},
    },
    {
        "id": "sb.feed_out", "name": "Vývod", "category": "Svorky a propojení", "iec_ref": "X",
        "description": "Vývodní svorky rozvaděče",
        "primitives": [C(0, 0, 1.5), L(0, 1.5, 0, 5), L(0, -1.5, 0, -5), T(0, -9, "VÝVOD", 2)],
        "ports": [P("1", 0, 5, "N")],
        "attributes": [REF, attr("desc", "Popis", "", True), attr("to", "Kam", "", True), attr("cable", "Kabel"),
                       attr("terminal", "Svorka č.", "")],
        "multipole": MP([C(0, 2.5, 1.5), L(0, 4, 0, 5), L(0, 1, 0, -3)], [], link=False),
        "label_pos": {"x": 7, "y": 0},
    },
    {
        "id": "sb.terminal_block", "name": "Svorkovnice", "category": "Svorky a propojení", "iec_ref": "X",
        "description": "Řadová svorkovnice – skupina svorek (čísla v atributu Svorka č.); šířka v rozložení = počet "
                       "svorek × 6,2 mm, pokud není zadaná",
        "primitives": [C(0, 0, 1.5), L(0, 5, 0, 1.5), L(0, -1.5, 0, -5)],
        "ports": [P("1", 0, 5, "N"), P("2", 0, -5, "S")],
        "attributes": [REF, attr("terminal", "Svorka č.", "", True), attr("cross", "Průřez [mm²]"),
                       # šířka celé skupiny; prázdné = počet svorek × 6,2 mm (`project.TERMINAL_WIDTH_MM`, 1 svorka ≈ 0,35 M)
                       attr("modules", "Šířka skupiny [moduly] (prázdné = počet svorek × 6,2 mm)", "")],
        "multipole": MP([C(0, 0, 1.5), L(0, 5, 0, 1.5), L(0, -1.5, 0, -5)], link=False),
        "label_pos": {"x": 2.5, "y": 1},
    },
    {
        "id": "sb.junction", "name": "Odbočka (uzel)", "category": "Svorky a propojení", "iec_ref": "",
        "description": "T-odbočka: uzel na vodiči, všechny porty mají stejný potenciál (vodič z vodiče)",
        "primitives": [{"type": "circle", "cx": 0, "cy": 0, "r": 0.8, "filled": True}],
        "ports": [P("N", 0, 2.5, "N"), P("E", 2.5, 0, "E"), P("S", 0, -2.5, "S"), P("W", -2.5, 0, "W")],
        "attributes": [attr("ref", "Označení", "", False)],
        "label_pos": {"x": 2, "y": 2},
    },
    {
        "id": "sb.pe_bar", "name": "PE/N můstek", "category": "Svorky a propojení", "iec_ref": "X",
        "description": "Ochranná / nulová sběrnice",
        # porty nahoře (N): vodiče přicházejí od přístrojů shora, lišta je dole a nic přes ni nevede
        "primitives": [{"type": "polyline", "points": [[-15, 0], [15, 0]], "closed": False},
                       {"type": "polyline", "points": [[-15, -1.5], [15, -1.5]], "closed": False}, T(17, -1.5, "PE", 2, "left")],
        "ports": [P(f"{i + 1}", -12.5 + i * 5, 2.5, "N") for i in range(6)],
        "attributes": [REF, attr("kind", "Druh", "PE")],
        "label_pos": {"x": -15, "y": -4.5},
    },
]


# ---- ovládací obvody: cívka a kontakty (svislý tok shora dolů, číslování svorek dle IEC) -------------------
SYMBOLS += [
    {
        "id": "ctl.coil", "name": "Cívka (stykač / relé)", "category": "Relé a stykače", "iec_ref": "K",
        "description": "Cívka stykače nebo relé A1–A2; kontakty se k ní vážou označením (zrcadlo kontaktů pod cívkou)",
        "primitives": [R(-5, -4, 10, 8), L(0, 7.5, 0, 4), L(0, -4, 0, -7.5), T(-6.5, 5, "A1", 1.8, "right"),
                       T(-6.5, -7, "A2", 1.8, "right")],
        "ports": [P("A1", 0, 7.5, "N"), P("A2", 0, -7.5, "S")],
        "attributes": [REF, TYPE, MFR, attr("un", "Un cívky [V]", "230"), attr("desc", "Funkce", "", True), MOD,
                       CONTACTS, *TEMP],
        "label_pos": {"x": 7, "y": 2},
    },
    {
        "id": "ctl.contact_no", "name": "Kontakt spínací (NO)", "category": "Relé a stykače", "iec_ref": "",
        "description": "Pomocný spínací kontakt (13/14) – označení = cívka/přístroj, ke kterému patří",
        "primitives": [L(0, 7.5, 0, 2.5), L(0, -2.5, -3.5, 3.5), L(0, -2.5, 0, -7.5)],
        "ports": [P("13", 0, 7.5, "N"), P("14", 0, -7.5, "S")],
        "attributes": [attr("ref", "Označení (cívka / přístroj)", "", True), attr("terminals", "Svorky", "13/14", True),
                       attr("desc", "Funkce")],
        "label_pos": {"x": 3, "y": 2},
    },
    {
        "id": "ctl.contact_nc", "name": "Kontakt rozpínací (NC)", "category": "Relé a stykače", "iec_ref": "",
        "description": "Pomocný rozpínací kontakt (21/22)",
        "primitives": [L(0, 7.5, 0, 2.5), L(0, -2.5, 3.5, 3.5), L(0, -2.5, 0, -7.5), L(0, 2.5, 3, 2.5)],
        "ports": [P("21", 0, 7.5, "N"), P("22", 0, -7.5, "S")],
        "attributes": [attr("ref", "Označení (cívka / přístroj)", "", True), attr("terminals", "Svorky", "21/22", True),
                       attr("desc", "Funkce")],
        "label_pos": {"x": 3, "y": 2},
    },
    {
        "id": "ctl.contact_power", "name": "Hlavní kontakt (silový)", "category": "Relé a stykače", "iec_ref": "",
        "description": "Silový kontakt stykače (1/2, 3/4, 5/6) pro silové schéma – patří k cívce stejného označení",
        "primitives": CONTACT + [A(-3.5, 0, 1, -90, 90)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [attr("ref", "Označení (cívka)", "", True), attr("in_", "In [A]", "", True), POLES, MOD, PLOSS],
        "multipole": MP(CONTACT + [A(-3.5, 0, 1, -90, 90)]),
        "label_pos": {"x": -5, "y": -6},
    },
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sb = OUT.parent / "switchboard"
    sb.mkdir(parents=True, exist_ok=True)
    ctl = OUT.parent / "control"
    ctl.mkdir(parents=True, exist_ok=True)
    for s in SYMBOLS:
        folder = sb if s["id"].startswith("sb.") else (ctl if s["id"].startswith("ctl.") else OUT)
        (folder / f"{s['id']}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(SYMBOLS)} symbolů → {OUT}")


if __name__ == "__main__":
    main()
