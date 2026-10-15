"""Jednorázový generátor startovní sady symbolů FVE → envocad/library/builtin/fve/*.json.

Spustit: python tools/gen_builtin_fve.py
JSON soubory jsou zdroj pravdy; tento skript je jen pohodlný způsob, jak je vytvořit/přegenerovat.
Jednotky mm, Y nahoru, tok výkonu zleva doprava (vstup W, výstup E).
"""
from __future__ import annotations

import json
from pathlib import Path

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


def attr(key, label, default="", show=False):
    return {"key": key, "label": label, "default": default, "show": show}


REF = attr("ref", "Označení", "", True)
TYPE = attr("type", "Typ", "", True)

SYMBOLS = [
    {
        "id": "fve.pv_string", "name": "FV string", "category": "FVE/Zdroje", "iec_ref": "G",
        "description": "Řetězec FV modulů (jednopólově)",
        "primitives": [
            R(-10, -7.5, 15, 15), L(-10, -7.5, 5, 7.5),
            # slunce
            C(-15, 10, 2), L(-15, 13, -15, 14.5), L(-12, 10, -10.5, 10), L(-12.9, 12.1, -11.8, 13.2),
            L(-17.1, 12.1, -18.2, 13.2),
            T(-2.5, -11, "FV", 2.5),
            L(5, 2.5, 7.5, 2.5), L(5, -2.5, 7.5, -2.5), T(6.5, 4.5, "+", 2), T(6.5, -5.5, "–", 2),
        ],
        "ports": [P("DC+", 7.5, 2.5, "E"), P("DC-", 7.5, -2.5, "E")],
        "attributes": [REF, TYPE, attr("n_modules", "Počet modulů"), attr("p_module", "P modul [Wp]"),
                       attr("p_string", "P string [kWp]", "", True), attr("voc", "Uoc [V]"), attr("isc", "Isc [A]")],
        "label_pos": {"x": -10, "y": 10},
    },
    {
        "id": "fve.dc_disconnect", "name": "Odpínač DC", "category": "FVE/DC strana", "iec_ref": "Q",
        "description": "Odpínač DC (např. v DC rozvaděči nebo ve střídači)",
        "primitives": [L(-7.5, 0, -2.5, 0), L(-2.5, 0, 2, 4), L(2.5, 0, 7.5, 0), L(2.5, -1.5, 2.5, 1.5),
                       L(-2.5, -1.5, -2.5, 1.5), T(0, 6, "DC", 2)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, attr("un", "Un [V DC]"), attr("in_", "In [A]")],
        "label_pos": {"x": -5, "y": -6},
    },
    {
        "id": "fve.fuse", "name": "Pojistka", "category": "Obecné/Jištění", "iec_ref": "F",
        "description": "Pojistka (gPV / gG)",
        "primitives": [R(-5, -2.5, 10, 5), L(-7.5, 0, 7.5, 0)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, attr("in_", "In [A]", "", True), attr("char", "Charakteristika", "gPV")],
        "label_pos": {"x": -5, "y": 4},
    },
    {
        "id": "fve.spd", "name": "Svodič přepětí (SPD)", "category": "Obecné/Jištění", "iec_ref": "F",
        "description": "Svodič přepětí, typ 1/2, DC nebo AC",
        "primitives": [R(-2.5, -5, 5, 10), L(0, 5, 0, 7.5), L(0, -5, 0, -7.5), L(-2, -3.5, 2, 3.5),
                       L(1, 3.5, 2, 3.5), L(2, 2.5, 2, 3.5)],
        "ports": [P("L", 0, 7.5, "N"), P("PE", 0, -7.5, "S")],
        "attributes": [REF, TYPE, attr("spd_type", "Typ SPD", "T2", True), attr("uc", "Uc [V]")],
        "label_pos": {"x": 4, "y": 2},
    },
    {
        "id": "fve.inverter", "name": "Střídač", "category": "FVE/Střídače", "iec_ref": "T",
        "description": "Síťový střídač DC/AC",
        "primitives": [R(-10, -10, 20, 20), L(-10, -10, 10, 10), T(-5, 0.5, "DC", 2.5), T(5, -6, "AC", 2.5),
                       L(-5.5, 6, -1.5, 6), L(-5.5, 4.5, -3.5, 4.5), L(-2.5, 4.5, -1.5, 4.5),
                       A(2.5, -1.5, 1.5, 0, 180), A(5.5, -1.5, 1.5, 180, 360)],
        "ports": [P("DC+", -10, 5, "W"), P("DC-", -10, -5, "W"), P("AC", 10, 0, "E")],
        "attributes": [REF, TYPE, attr("p_ac", "P AC [kW]", "", True), attr("p_dc_max", "P DC max [kWp]"),
                       attr("mppt", "Počet MPPT"), attr("phases", "Fáze", "3")],
        "label_pos": {"x": -10, "y": 16},
    },
    {
        "id": "fve.inverter_hybrid", "name": "Hybridní střídač", "category": "FVE/Střídače", "iec_ref": "T",
        "description": "Hybridní střídač s bateriovým vstupem",
        "primitives": [R(-10, -10, 20, 20), L(-10, -10, 10, 10), T(-5, 0.5, "DC", 2.5), T(5, -6, "AC", 2.5),
                       L(-5.5, 6, -1.5, 6), L(-5.5, 4.5, -3.5, 4.5), L(-2.5, 4.5, -1.5, 4.5),
                       A(2.5, -1.5, 1.5, 0, 180), A(5.5, -1.5, 1.5, 180, 360), T(0, -13.5, "BAT", 2)],
        "ports": [P("DC+", -10, 5, "W"), P("DC-", -10, -5, "W"), P("AC", 10, 0, "E"), P("BAT", 0, -10, "S")],
        "attributes": [REF, TYPE, attr("p_ac", "P AC [kW]", "", True), attr("p_dc_max", "P DC max [kWp]"),
                       attr("mppt", "Počet MPPT"), attr("phases", "Fáze", "3")],
        "label_pos": {"x": -10, "y": 16},
    },
    {
        "id": "fve.battery", "name": "Bateriové úložiště", "category": "FVE/Zdroje", "iec_ref": "G",
        "description": "Akumulátor / BESS",
        "primitives": [L(0, 7.5, 0, 5), L(-5, 5, 5, 5), L(-2.5, 3, 2.5, 3), L(-5, 1, 5, 1), L(-2.5, -1, 2.5, -1),
                       L(0, -1, 0, -2.5), R(-7.5, -7.5, 15, 17.5), T(0, -6, "BESS", 2)],
        "ports": [P("DC", 0, 10, "N")],
        "attributes": [REF, TYPE, attr("e_kwh", "Kapacita [kWh]", "", True), attr("p_kw", "Výkon [kW]")],
        "label_pos": {"x": 9, "y": 2},
    },
    {
        "id": "fve.breaker_mcb", "name": "Jistič", "category": "Obecné/Jištění", "iec_ref": "F",
        "description": "Jistič (MCB)",
        "primitives": [L(-7.5, 0, -2.5, 0), L(-2.5, 0, 2, 4), L(2.5, 0, 7.5, 0),
                       L(-3.5, -1, -1.5, 1), L(-3.5, 1, -1.5, -1)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, attr("in_", "In [A]", "", True), attr("char", "Charakteristika", "B"),
                       attr("poles", "Póly", "3"), attr("icu", "Icu [kA]", "6")],
        "label_pos": {"x": -5, "y": -6},
    },
    {
        "id": "fve.breaker_mccb", "name": "Výkonový jistič", "category": "Obecné/Jištění", "iec_ref": "Q",
        "description": "Kompaktní výkonový jistič (MCCB)",
        "primitives": [L(-7.5, 0, -2.5, 0), L(-2.5, 0, 2, 4), L(2.5, 0, 7.5, 0),
                       L(-3.5, -1, -1.5, 1), L(-3.5, 1, -1.5, -1), R(-5, -3.5, 10, 7)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, attr("in_", "In [A]", "", True), attr("ir", "Ir [A]"), attr("poles", "Póly", "3"),
                       attr("icu", "Icu [kA]")],
        "label_pos": {"x": -5, "y": -7},
    },
    {
        "id": "fve.switch_disconnector", "name": "Odpínač", "category": "Obecné/Spínání", "iec_ref": "Q",
        "description": "Odpínač AC (hlavní vypínač, odpínač FVE)",
        "primitives": [L(-7.5, 0, -2.5, 0), L(-2.5, 0, 2, 4), L(2.5, 0, 7.5, 0), L(2.5, -1.5, 2.5, 1.5)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, attr("in_", "In [A]", "", True), attr("poles", "Póly", "3")],
        "label_pos": {"x": -5, "y": -6},
    },
    {
        "id": "fve.contactor", "name": "Stykač", "category": "Obecné/Spínání", "iec_ref": "K",
        "description": "Stykač (např. pro odpojení FVE od DS – NS)",
        "primitives": [L(-7.5, 0, -2.5, 0), L(-2.5, 0, 2, 4), L(2.5, 0, 7.5, 0), A(3.5, 0, 1, 90, 270)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, attr("in_", "In [A]", "", True)],
        "label_pos": {"x": -5, "y": -6},
    },
    {
        "id": "fve.meter", "name": "Elektroměr", "category": "Obecné/Měření", "iec_ref": "P",
        "description": "Elektroměr (fakturační / podružný)",
        "primitives": [C(0, 0, 5), T(0, -1, "kWh", 2), L(-7.5, 0, -5, 0), L(5, 0, 7.5, 0)],
        "ports": [P("1", -7.5, 0, "W"), P("2", 7.5, 0, "E")],
        "attributes": [REF, TYPE, attr("kind", "Druh", "fakturační")],
        "label_pos": {"x": -5, "y": 6.5},
    },
    {
        "id": "fve.grid", "name": "Distribuční síť", "category": "FVE/Síť", "iec_ref": "",
        "description": "Přípojka k distribuční soustavě",
        "primitives": [L(-7.5, 0, -2.5, 0), C(2.5, 0, 5), L(-1, 3.5, 6, -3.5), L(-1, -3.5, 6, 3.5),
                       T(2.5, 7, "DS", 2.5)],
        "ports": [P("1", -7.5, 0, "W")],
        "attributes": [REF, attr("voltage", "Napětí", "3×400 V, 50 Hz", True), attr("dso", "Provozovatel DS", "")],
        "label_pos": {"x": -5, "y": -8},
    },
    {
        "id": "fve.load", "name": "Spotřeba objektu", "category": "FVE/Síť", "iec_ref": "",
        "description": "Stávající rozvod / spotřeba objektu",
        "primitives": [L(-7.5, 0, -5, 0), R(-5, -5, 15, 10), T(2.5, -1, "Spotřeba", 2)],
        "ports": [P("1", -7.5, 0, "W")],
        "attributes": [REF, attr("desc", "Popis", "", True)],
        "label_pos": {"x": -5, "y": 6.5},
    },
    {
        "id": "fve.transformer", "name": "Transformátor", "category": "Obecné/Síť", "iec_ref": "T",
        "description": "Transformátor VN/NN",
        "primitives": [L(-10, 0, -7.5, 0), C(-2.5, 0, 5), C(2.5, 0, 5), L(7.5, 0, 10, 0)],
        "ports": [P("1", -10, 0, "W"), P("2", 10, 0, "E")],
        "attributes": [REF, TYPE, attr("sn", "Sn [kVA]", "", True), attr("ratio", "Převod")],
        "label_pos": {"x": -7.5, "y": 6.5},
    },
    {
        "id": "fve.terminal", "name": "Uzel / svorka", "category": "Obecné/Propojení", "iec_ref": "X",
        "description": "Spojovací uzel – větvení vodičů",
        "primitives": [C(0, 0, 1)],
        "ports": [P("N", 0, 2.5, "N"), P("E", 2.5, 0, "E"), P("S", 0, -2.5, "S"), P("W", -2.5, 0, "W")],
        "attributes": [REF],
        "label_pos": {"x": 2, "y": 2},
    },
    {
        "id": "fve.earth", "name": "Uzemnění", "category": "Obecné/Propojení", "iec_ref": "",
        "description": "Zemnicí svorka / PE",
        "primitives": [L(0, 5, 0, 0), L(-4, 0, 4, 0), L(-2.5, -1.5, 2.5, -1.5), L(-1, -3, 1, -3)],
        "ports": [P("PE", 0, 5, "N")],
        "attributes": [REF],
        "label_pos": {"x": 5, "y": 0},
    },
    {
        "id": "fve.switchboard", "name": "Rozvaděč (blok)", "category": "FVE/Rozvaděče", "iec_ref": "R",
        "description": "Rozvaděč jako blok (odkaz na samostatný list)",
        "primitives": [R(-15, -10, 30, 20), T(0, 11.5, "ROZVADĚČ", 2)],
        "ports": [P("1", -15, 0, "W"), P("2", 15, 0, "E"), P("3", 0, 10, "N"), P("4", 0, -10, "S")],
        "attributes": [REF, attr("desc", "Popis", "", True), attr("sheet", "Odkaz na list")],
        "label_pos": {"x": -15, "y": -13},
    },
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for s in SYMBOLS:
        (OUT / f"{s['id']}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(SYMBOLS)} symbolů → {OUT}")


if __name__ == "__main__":
    main()
