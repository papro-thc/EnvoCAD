"""Artikly (komponenty): formát CSV v2, validace, propsání parametrů do prvku. Bez Qt.

CLI:
    python -m envocad.library.components validate soubor.csv [--symbols]
    python -m envocad.library.components stats soubor.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from envocad.model.calc import STRING_MODES   # režimy stringu (prázdné = classic) – jediná definice v calc
from envocad.model.project import Element

REQUIRED = ["id", "manufacturer", "part_number", "name", "category", "symbol_id", "datasheet_url", "source"]
CATEGORIES = {"mcb", "mccb", "rcd", "rcbo", "spd", "switch", "contactor", "fuse", "fuse_holder", "meter", "inverter",
              "inverter_hybrid", "battery", "pv_module", "enclosure", "terminal", "relay", "accessory", "connector",
              "cable", "optimizer", "other"}
NUMERIC = {"price_czk", "in_", "poles", "icu_ka", "idn_ma", "un_v", "modules", "width_mm", "height_mm", "depth_mm",
           "p_loss_w", "p_ac_kw", "p_dc_max_kwp", "mppt", "phases", "i_ac_max_a", "e_kwh", "p_kw", "u_dc_v", "p_wp",
           "voc_v", "isc_a", "vmp_v", "imp_a", "uc_v", "up_kv", "iimp_ka", "in_ka", "rows", "modules_per_row",
           "cross_mm2", "cross_max_mm2", "levels", "cores_n", "od_mm", "u_dc_max_v", "u_mppt_min_v", "u_mppt_max_v",
           "i_mppt_max_a", "strings_per_mppt", "beta_voc", "t_min_c", "t_max_c",
           # FV moduly (pv_modules.csv) a střídače – katalog pro průvodce (docs/design/katalog_fv.md)
           "alpha_isc", "gamma_pmax", "noct_c", "u_sys_max_v", "i_fuse_max_a", "weight_kg", "isc_mppt_max_a",
           "eff_max_pct", "eff_eu_pct",
           # optimizéry (optimizers.csv) a režim stringu střídače (docs/design/optimizery.md)
           "p_max_w", "p_tol_pct", "u_in_max_v", "isc_in_max_a", "i_out_max_a", "u_out_max_v", "modules_per_optimizer",
           "partial_ok", "n_min_1ph", "n_max_1ph", "p_string_max_1ph_w", "n_min_3ph", "n_max_3ph", "p_string_max_3ph_w",
           "u_string_v", "n_opt_min", "n_opt_max", "p_string_max_w"}
SOURCES = {"catalog", "datasheet", "web", "seed", "user"}

# výchozí schematická značka podle kategorie (když symbol_id chybí)
DEFAULT_SYMBOL = {
    "mcb": "fve.breaker_mcb", "mccb": "fve.breaker_mccb", "rcd": "sb.rcd", "rcbo": "sb.rcbo", "spd": "fve.spd",
    "switch": "fve.switch_disconnector", "contactor": "fve.contactor", "fuse": "fve.fuse", "fuse_holder": "fve.fuse",
    "meter": "fve.meter", "inverter": "fve.inverter", "inverter_hybrid": "fve.inverter_hybrid",
    "battery": "fve.battery", "pv_module": "fve.pv_string", "terminal": "sb.terminal_block",
}

# artikl.param → atribut prvku
PARAM_TO_ATTR = {
    "part_number": "type", "manufacturer": "manufacturer", "in_": "in_", "poles": "poles", "char": "char",
    "icu_ka": "icu", "idn_ma": "idn", "modules": "modules", "p_loss_w": "p_loss_w", "spd_type": "spd_type",
    "uc_v": "uc", "p_ac_kw": "p_ac", "p_dc_max_kwp": "p_dc_max", "mppt": "mppt", "phases": "phases",
    "e_kwh": "e_kwh", "p_kw": "p_kw", "un_v": "un", "p_wp": "p_module", "voc_v": "voc", "isc_a": "isc",
    "cross_mm2": "cross", "terminal_kind": "kind",
    "u_dc_max_v": "u_dc_max", "u_mppt_min_v": "u_mppt_min", "u_mppt_max_v": "u_mppt_max", "i_mppt_max_a": "i_mppt_max",
    "strings_per_mppt": "strings_per_mppt", "vmp_v": "vmp", "beta_voc": "beta_voc",
    # FV modul: Impp, max. napětí systému; střídač: max. zkratový proud na MPPT (kontrola stringů, `model/calc.py`)
    "imp_a": "imp", "u_sys_max_v": "u_sys_max", "isc_mppt_max_a": "isc_mppt_max",
    # FV modul: teplotní součinitele [%/K] – oba zadané → součinitel Umpp = γ_Pmax − α_Isc (`calc.ModuleData`)
    "gamma_pmax": "gamma_pmax", "alpha_isc": "alpha_isc",
    # rozsah provozní teploty okolí přístroje [°C] dle datasheetu – ověření oteplení po přístrojích (`thermal`)
    "t_min_c": "t_min", "t_max_c": "t_max",
    "contacts": "contacts",   # kontaktní obraz („1/2 3/4 5/6 13/14 21/22“) – zrcadlo kontaktů, kontroly kontaktů
    # střídač: režim stringu, pevné napětí stringu, pravidla stringu s optimizéry (`calc.InverterData`)
    "string_mode": "string_mode", "u_string_v": "u_string", "n_opt_min": "n_opt_min", "n_opt_max": "n_opt_max",
    "p_string_max_w": "p_string_max",
}

# optimizér: artikl.param → atribut stringu `fve.pv_string` (vlastní předpona, nekoliduje s typem/výrobcem modulu);
# pravidla stringu dané fáze (`n_min_1ph`…) doplní `Component.optimizer_values(phases)` jako opt_n_min/opt_n_max/
# opt_p_string_max
OPTIMIZER_ATTRS = {
    "part_number": "optimizer", "manufacturer": "opt_manufacturer", "p_max_w": "opt_p_max", "p_tol_pct": "opt_p_tol",
    "u_in_max_v": "opt_u_in_max", "u_mppt_min_v": "opt_u_mppt_min", "u_mppt_max_v": "opt_u_mppt_max",
    "isc_in_max_a": "opt_isc_in_max",
    "i_out_max_a": "opt_i_out_max", "u_out_max_v": "opt_u_out_max", "modules_per_optimizer": "opt_modules",
    "partial_ok": "opt_partial", "compat": "opt_compat",
}
OPTIMIZER_PHASE_ATTRS = {"n_min": "opt_n_min", "n_max": "opt_n_max", "p_string_max": "opt_p_string_max"}


@dataclass
class Component:
    id: str
    manufacturer: str
    part_number: str
    name: str
    category: str
    symbol_id: str
    datasheet_url: str = ""
    source: str = "user"
    footprint_id: str = ""
    params: dict[str, str] = field(default_factory=dict)
    price: float | None = None

    @property
    def label(self) -> str:
        return f"{self.manufacturer} {self.part_number} – {self.name}"

    def num(self, key: str) -> float | None:
        v = self.params.get(key)
        if v in (None, ""):
            return None
        try:
            return float(str(v).replace(",", "."))
        except ValueError:
            return None

    def attr_values(self) -> dict[str, str]:
        """Atributy prvku, které artikl zná (`PARAM_TO_ATTR`, jen neprázdné): klíč atributu → hodnota.
        Bez prvku – průvodce z nich předvyplní pole, `apply_to` je propíše do prvku."""
        out: dict[str, str] = {}
        src = {"part_number": self.part_number, "manufacturer": self.manufacturer, **self.params}
        for pkey, akey in PARAM_TO_ATTR.items():
            v = src.get(pkey)
            if v in (None, ""):
                continue
            out[akey] = str(v)
        return out

    def optimizer_values(self, phases=3) -> dict[str, str]:
        """Atributy stringu z artiklu optimizéru (`OPTIMIZER_ATTRS`, jen neprázdné) + `optimizer_id` a pravidla stringu
        pro danou fázi (1 → `*_1ph`, jinak `*_3ph`) jako `opt_n_min`, `opt_n_max`, `opt_p_string_max`."""
        src = {"part_number": self.part_number, "manufacturer": self.manufacturer, **self.params}
        out = {akey: str(src[pkey]) for pkey, akey in OPTIMIZER_ATTRS.items() if src.get(pkey) not in (None, "")}
        out["optimizer_id"] = self.id
        try:
            ph = "1ph" if float(str(phases).replace(",", ".")) == 1 else "3ph"
        except (TypeError, ValueError):
            ph = "3ph"
        for base, akey in OPTIMIZER_PHASE_ATTRS.items():
            v = self.params.get(f"{base}_{ph}" if base != "p_string_max" else f"p_string_max_{ph}_w")
            if v not in (None, ""):
                out[akey] = str(v)
        return out

    def apply_to(self, e: Element) -> dict[str, str]:
        """Propíše parametry do atributů prvku; vrátí změněné atributy (klíč → nová hodnota)."""
        changed = {k: v for k, v in self.attr_values().items() if e.attrs.get(k) != v}
        e.attrs.update(changed)
        e.component_id = self.id
        return changed

    @classmethod
    def from_row(cls, row: dict[str, str]) -> Component:
        fixed = {"id", "manufacturer", "part_number", "name", "category", "symbol_id", "datasheet_url", "source",
                 "footprint_id", "price_czk"}
        params = {k: v.strip() for k, v in row.items() if k and k not in fixed and v and v.strip()}
        price = None
        if row.get("price_czk"):
            try:
                price = float(row["price_czk"].replace(",", ".").replace(" ", ""))
            except ValueError:
                price = None
        cat = (row.get("category") or "other").strip()
        return cls(
            id=row["id"].strip(), manufacturer=row.get("manufacturer", "").strip(),
            part_number=row.get("part_number", "").strip(), name=row.get("name", "").strip(), category=cat,
            symbol_id=(row.get("symbol_id") or DEFAULT_SYMBOL.get(cat, "")).strip(),
            datasheet_url=row.get("datasheet_url", "").strip(), source=(row.get("source") or "user").strip(),
            footprint_id=(row.get("footprint_id") or "").strip(), params=params, price=price,
        )

    def to_db_row(self) -> dict:
        return {"id": self.id, "manufacturer": self.manufacturer, "part_number": self.part_number, "name": self.name,
                "symbol_id": self.symbol_id or None, "params": {**self.params, "category": self.category,
                                                                "datasheet_url": self.datasheet_url, "source": self.source,
                                                                "footprint_id": self.footprint_id},
                "price": self.price, "url": self.datasheet_url}

    @classmethod
    def from_db_row(cls, d: dict) -> Component:
        params = dict(d.get("params") or {})
        return cls(id=d["id"], manufacturer=d.get("manufacturer", ""), part_number=d.get("part_number", ""),
                   name=d.get("name", ""), category=params.pop("category", "other"), symbol_id=d.get("symbol_id") or "",
                   datasheet_url=params.pop("datasheet_url", "") or (d.get("url") or ""),
                   source=params.pop("source", "user"), footprint_id=params.pop("footprint_id", ""),
                   params=params, price=d.get("price"))


def read_csv(path: Path | str) -> list[Component]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        head = f.readline()
        delim = ";" if head.count(";") >= head.count(",") else ","
        f.seek(0)
        return [Component.from_row(r) for r in csv.DictReader(f, delimiter=delim) if r.get("id", "").strip()]


T_RANGE_C = (-60.0, 150.0)   # věrohodný rozsah provozní teploty okolí přístroje z datasheetu [°C]


def temperature_range_error(t_min, t_max) -> str | None:
    """Česká hláška k rozsahu provozní teploty okolí (`t_min_c` / `t_max_c`): mimo věrohodný rozsah −60…150 °C
    nebo t_min ≥ t_max. Prázdné hodnoty jsou v pořádku, nečíselné hlásí kontrola `NUMERIC` (tady se přeskočí)."""
    vals = []
    for key, v in (("t_min_c", t_min), ("t_max_c", t_max)):
        t = str(v or "").strip()
        if not re.fullmatch(r"-?\d+([.,]\d+)?", t):
            vals.append(None)
            continue
        x = float(t.replace(",", "."))
        if not T_RANGE_C[0] <= x <= T_RANGE_C[1]:
            return f"'{key}' = {t} °C je mimo věrohodný rozsah {T_RANGE_C[0]:g} až {T_RANGE_C[1]:g} °C"
        vals.append(x)
    if vals[0] is not None and vals[1] is not None and vals[0] >= vals[1]:
        return f"'t_min_c' ({vals[0]:g} °C) musí být menší než 't_max_c' ({vals[1]:g} °C)"
    return None


def _row_num(row: dict, key: str) -> float | None:
    """Číslo ze sloupce řádku CSV (desetinná čárka i tečka); prázdné / nečíselné → None (to hlásí `NUMERIC`)."""
    t = str(row.get(key) or "").strip()
    if not re.fullmatch(r"-?\d+([.,]\d+)?", t):
        return None
    return float(t.replace(",", "."))


P_WP_TOLERANCE = 0.03   # |p_wp − vmp·imp| / p_wp – opsané hodnoty STC musí sedět na 3 %


def pv_module_error(row: dict) -> str | None:
    """Česká hláška k řádku FV modulu (`category=pv_module`), nebo None. Povinné `voc_v` a `isc_a` (bez nich řádek
    neukládat), dál vmp < voc, imp < isc, −1 < β_Voc < 0 %/K, |p_wp − vmp·imp| ≤ 3 % p_wp. Prázdné nepovinné
    hodnoty se přeskočí; víc chyb najednou se spojí středníkem."""
    errs: list[str] = []
    voc, vmp, isc, imp = (_row_num(row, k) for k in ("voc_v", "vmp_v", "isc_a", "imp_a"))
    beta, p_wp = _row_num(row, "beta_voc"), _row_num(row, "p_wp")
    for key, v in (("voc_v", voc), ("isc_a", isc)):
        if v is None:
            errs.append(f"FV modul bez '{key}'")
        elif v <= 0:
            errs.append(f"'{key}' musí být kladné, je {v:g}")
    if voc and vmp is not None and not 0 < vmp < voc:
        errs.append(f"'vmp_v' ({vmp:g} V) musí být kladné a menší než 'voc_v' ({voc:g} V)")
    if isc and imp is not None and not 0 < imp < isc:
        errs.append(f"'imp_a' ({imp:g} A) musí být kladné a menší než 'isc_a' ({isc:g} A)")
    if beta is not None and not -1 < beta < 0:
        errs.append(f"'beta_voc' ({beta:g} %/K) musí být mezi −1 a 0 %/K")
    if p_wp and vmp and imp and abs(p_wp - vmp * imp) / p_wp > P_WP_TOLERANCE:
        errs.append(f"'p_wp' ({p_wp:g} Wp) nesedí na vmp·imp = {vmp * imp:.1f} W (odchylka > {P_WP_TOLERANCE:.0%})")
    return "; ".join(errs) or None


def inverter_error(row: dict) -> str | None:
    """Česká hláška k řádku střídače (`inverter`, `inverter_hybrid`), nebo None: u_mppt_min < u_mppt_max ≤ u_dc_max,
    strings_per_mppt ≥ 1, `string_mode` z `STRING_MODES`, fixed_voltage ⇒ `u_string_v`, u_string ≤ u_dc_max,
    n_opt_min ≤ n_opt_max. Prázdné hodnoty se přeskočí (vestavěné střídače se doplňují postupně)."""
    errs: list[str] = []
    u_dc, lo, hi = (_row_num(row, k) for k in ("u_dc_max_v", "u_mppt_min_v", "u_mppt_max_v"))
    spm = _row_num(row, "strings_per_mppt")
    if lo is not None and hi is not None and not lo < hi:
        errs.append(f"'u_mppt_min_v' ({lo:g} V) musí být menší než 'u_mppt_max_v' ({hi:g} V)")
    if hi is not None and u_dc is not None and hi > u_dc:
        errs.append(f"'u_mppt_max_v' ({hi:g} V) nesmí být větší než 'u_dc_max_v' ({u_dc:g} V)")
    if lo is not None and hi is None and u_dc is not None and lo >= u_dc:
        errs.append(f"'u_mppt_min_v' ({lo:g} V) musí být menší než 'u_dc_max_v' ({u_dc:g} V)")
    if spm is not None and (spm < 1 or not spm.is_integer()):
        errs.append(f"'strings_per_mppt' musí být celé číslo ≥ 1, je {spm:g}")
    mode = str(row.get("string_mode") or "").strip()
    if mode and mode not in STRING_MODES:
        errs.append(f"'string_mode' musí být prázdné nebo jedno z {', '.join(STRING_MODES)}, je '{mode}'")
    u_str = _row_num(row, "u_string_v")
    if mode == "fixed_voltage" and u_str is None:
        errs.append("'string_mode' = fixed_voltage vyžaduje 'u_string_v'")
    if u_str is not None and u_dc is not None and u_str > u_dc:
        errs.append(f"'u_string_v' ({u_str:g} V) nesmí být větší než 'u_dc_max_v' ({u_dc:g} V)")
    errs += _range_errors(row, "n_opt_min", "n_opt_max")
    return "; ".join(errs) or None


def _range_errors(row: dict, k_min: str, k_max: str) -> list[str]:
    """Celá čísla ≥ 1 a k_min ≤ k_max (prázdné se přeskočí)."""
    errs = []
    lo, hi = _row_num(row, k_min), _row_num(row, k_max)
    for key, v in ((k_min, lo), (k_max, hi)):
        if v is not None and (v < 1 or not v.is_integer()):
            errs.append(f"'{key}' musí být celé číslo ≥ 1, je {v:g}")
    if lo is not None and hi is not None and lo > hi:
        errs.append(f"'{k_min}' ({lo:g}) nesmí být větší než '{k_max}' ({hi:g})")
    return errs


def optimizer_error(row: dict) -> str | None:
    """Česká hláška k řádku optimizéru (`category=optimizer`), nebo None. Povinné `p_max_w`, `u_in_max_v`,
    `isc_in_max_a` (bez nich řádek neukládat), u_mppt_min < u_mppt_max ≤ u_in_max, `modules_per_optimizer` ∈ {1, 2}
    (povinné – rozhodnutí orchestrátora 8), `string_mode` z `STRING_MODES`, `partial_ok` 0/1, n_min ≤ n_max po fázích."""
    errs: list[str] = []
    for key in ("p_max_w", "u_in_max_v", "isc_in_max_a"):
        v = _row_num(row, key)
        if v is None:
            errs.append(f"optimizér bez '{key}'")
        elif v <= 0:
            errs.append(f"'{key}' musí být kladné, je {v:g}")
    u_in, lo, hi = (_row_num(row, k) for k in ("u_in_max_v", "u_mppt_min_v", "u_mppt_max_v"))
    if lo is not None and hi is not None and not lo < hi:
        errs.append(f"'u_mppt_min_v' ({lo:g} V) musí být menší než 'u_mppt_max_v' ({hi:g} V)")
    if hi is not None and u_in is not None and hi > u_in:
        errs.append(f"'u_mppt_max_v' ({hi:g} V) nesmí být větší než 'u_in_max_v' ({u_in:g} V)")
    if lo is not None and u_in is not None and lo >= u_in:
        errs.append(f"'u_mppt_min_v' ({lo:g} V) musí být menší než 'u_in_max_v' ({u_in:g} V)")
    mpo = _row_num(row, "modules_per_optimizer")
    if mpo not in (1.0, 2.0):
        errs.append("'modules_per_optimizer' musí být 1 nebo 2" + ("" if mpo is None else f", je {mpo:g}"))
    mode = str(row.get("string_mode") or "").strip()
    if mode and mode not in STRING_MODES:
        errs.append(f"'string_mode' musí být prázdné nebo jedno z {', '.join(STRING_MODES)}, je '{mode}'")
    part = str(row.get("partial_ok") or "").strip()
    if part and part not in ("0", "1"):
        errs.append(f"'partial_ok' musí být 0 nebo 1, je '{part}'")
    tol = _row_num(row, "p_tol_pct")
    if tol is not None and not 0 <= tol <= 100:
        errs.append(f"'p_tol_pct' musí být 0 až 100 %, je {tol:g}")
    for ph in ("1ph", "3ph"):
        errs += _range_errors(row, f"n_min_{ph}", f"n_max_{ph}")
    return "; ".join(errs) or None


def validate(path: Path | str, known_symbols: set[str] | None = None) -> list[str]:
    """Vrátí seznam chyb (prázdný = OK)."""
    errors: list[str] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        head = f.readline()
        delim = ";" if head.count(";") >= head.count(",") else ","
        f.seek(0)
        reader = csv.DictReader(f, delimiter=delim)
        cols = reader.fieldnames or []
        missing = [c for c in REQUIRED if c not in cols]
        if missing:
            errors.append(f"chybí sloupce: {', '.join(missing)}")
            return errors
        ids: set[str] = set()
        for n, row in enumerate(reader, start=2):
            rid = (row.get("id") or "").strip()
            if not rid:
                continue
            if not re.fullmatch(r"[a-z0-9][a-z0-9._+-]*", rid):
                errors.append(f"řádek {n}: id '{rid}' – jen malá písmena, čísla, . _ + -")
            if rid in ids:
                errors.append(f"řádek {n}: duplicitní id '{rid}'")
            ids.add(rid)
            for c in ("manufacturer", "part_number", "name"):
                if not (row.get(c) or "").strip():
                    errors.append(f"řádek {n} ({rid}): prázdné '{c}'")
            cat = (row.get("category") or "").strip()
            if cat not in CATEGORIES:
                errors.append(f"řádek {n} ({rid}): neznámá kategorie '{cat}'")
            src = (row.get("source") or "").strip()
            if src not in SOURCES:
                errors.append(f"řádek {n} ({rid}): source musí být jedno z {sorted(SOURCES)}")
            if src in ("catalog", "datasheet", "web") and not (row.get("datasheet_url") or "").startswith("http"):
                errors.append(f"řádek {n} ({rid}): datasheet_url musí být http(s) odkaz")
            sym = (row.get("symbol_id") or "").strip()
            if known_symbols is not None and sym and sym not in known_symbols:
                errors.append(f"řádek {n} ({rid}): neznámý symbol_id '{sym}'")
            for c in NUMERIC:
                v = (row.get(c) or "").strip()
                if v and not re.fullmatch(r"-?\d+([.,]\d+)?", v):
                    errors.append(f"řádek {n} ({rid}): '{c}' musí být číslo, je '{v}'")
            t_err = temperature_range_error(row.get("t_min_c"), row.get("t_max_c"))
            if t_err:
                errors.append(f"řádek {n} ({rid}): {t_err}")
            cat_err = (pv_module_error(row) if cat == "pv_module"
                       else inverter_error(row) if cat in ("inverter", "inverter_hybrid")
                       else optimizer_error(row) if cat == "optimizer" else None)
            if cat_err:
                errors.append(f"řádek {n} ({rid}): {cat_err}")
            contacts = (row.get("contacts") or "").strip()
            if contacts:
                from envocad.model.xref import parse_contact_image
                bad = parse_contact_image(contacts)[1]
                if bad:
                    errors.append(f"řádek {n} ({rid}): nečitelný kontaktní obraz 'contacts': {' '.join(bad)}")
    return errors


def stats(path: Path | str) -> dict[str, float]:
    comps = read_csv(path)
    if not comps:
        return {"count": 0}
    keys = sorted({k for c in comps for k in c.params})
    out = {"count": len(comps)}
    for k in keys:
        out[k] = round(100 * sum(1 for c in comps if c.params.get(k)) / len(comps))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["validate", "stats"])
    ap.add_argument("csv")
    ap.add_argument("--symbols", action="store_true", help="ověřit symbol_id proti knihovně")
    a = ap.parse_args(argv)
    if a.cmd == "validate":
        known = None
        if a.symbols:
            from envocad.library.store import LibraryStore
            known = {s[0] for s in LibraryStore(load_builtin=True).list_symbols()}
        errs = validate(a.csv, known)
        print("\n".join(errs) if errs else "OK")
        return 1 if errs else 0
    for k, v in stats(a.csv).items():
        unit = "" if k == "count" else " %"
        print(f"{k}: {v}{unit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
