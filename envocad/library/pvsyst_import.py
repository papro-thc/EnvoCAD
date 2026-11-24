"""Import FV modulů (.PAN) a střídačů (.OND) z PVsyst do artiklů EnvoCAD. Bez Qt.

Soubory PVsyst jsou text `klíč=hodnota` s vnořenými bloky (`PVObject_<x>=<typ>` … `End of PVObject <typ>`).
Typ artiklu se pozná podle obsahu kořene (`pvModule` / `pvGInverter`), ne podle přípony. Výsledek je artikl se
`source="user"` a poznámkou „import PVsyst – ověřit“ (hodnoty z cizího souboru je třeba zkontrolovat).
Jednotky: PVsyst udává rozměry v m (→ mm), muVocSpec v mV/°C a muISC v mA/°C (→ %/K), muPmpReq už v %/°C.
"""
from __future__ import annotations

import csv
import math
import re
import unicodedata
from pathlib import Path

from envocad.library.components import REQUIRED, Component, inverter_error, pv_module_error

MAX_BYTES = 5 * 1024 * 1024
NOTE = "import PVsyst – ověřit"
_END = re.compile(r"^End of PVObject\b", re.IGNORECASE)
_TECHNOLOGY = {"mtsimono": "monokrystalický", "mtsipoly": "polykrystalický"}


class _Block:
    def __init__(self, type_: str):
        self.type = type_
        self.values: dict[str, str] = {}
        self.children: list[_Block] = []

    def find(self, key: str) -> str | None:
        """Hodnota klíče (bez ohledu na velikost písmen); kořen má přednost, pak podbloky do hloubky."""
        k = key.lower()
        if k in self.values:
            return self.values[k]
        for ch in self.children:
            v = ch.find(key)
            if v is not None:
                return v
        return None


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _parse(text: str) -> _Block:
    root: _Block | None = None
    stack: list[_Block] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _END.match(line):
            if stack:
                stack.pop()
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key.lower().startswith("pvobject_"):
            blk = _Block(value)
            if root is None:
                root = blk
            elif stack:
                stack[-1].children.append(blk)
            stack.append(blk)
        elif stack:
            stack[-1].values.setdefault(key.lower(), value)
    if root is None:
        raise ValueError("Soubor není ve formátu PVsyst (chybí blok PVObject).")
    return root


def _number(text: str | None) -> float | None:
    if text is None or not text.strip():
        return None
    try:
        v = float(text.strip().replace(",", "."))
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _fmt(v: float) -> str:
    return format(round(v, 6), "f").rstrip("0").rstrip(".") or "0"


class _Reader:
    def __init__(self, root: _Block):
        self.root = root
        self.warnings: list[str] = []
        self.params: dict[str, str] = {}

    def num(self, key: str) -> float | None:
        raw = self.root.find(key)
        v = _number(raw)
        if raw is not None and raw.strip() and v is None:
            self.warnings.append(f"Hodnota {key} „{raw}“ není číslo – přeskočeno.")
        return v

    def put(self, column: str, key: str, scale: float = 1.0) -> None:
        v = self.num(key)
        if v is None:
            return
        scaled = v * scale
        if not math.isfinite(scaled):
            self.warnings.append(f"Hodnota {key} „{v}“ je mimo rozsah – přeskočeno.")
            return
        self.params[column] = _fmt(scaled)


def _common(r: _Reader) -> tuple[str, str, str]:
    mfr = (r.root.find("Manufacturer") or "").strip()
    pn = (r.root.find("Model") or "").strip()
    if not pn:
        raise ValueError("V souboru PVsyst chybí Model (typové označení).")
    if not mfr:
        r.warnings.append("V souboru PVsyst chybí Manufacturer (výrobce) – doplňte ho ručně.")
    for col, key in (("width_mm", "Width"), ("height_mm", "Height"), ("depth_mm", "Depth")):
        r.put(col, key, 1000.0)
    r.put("weight_kg", "Weight")
    return mfr, pn, f"{mfr} {pn}".strip()


def _coefficient(r: _Reader, key: str, target: str, base: float, unit: str) -> None:
    mu = r.num(key)
    if not mu:
        r.warnings.append(f"Chybí nebo je nulové {key} – '{target}' ({unit}) zůstává prázdné, doplňte z datasheetu.")
        return
    r.params[target] = _fmt(round(mu / 1000 / base * 100, 3))


def _module(r: _Reader) -> list[str]:
    voc, isc = r.num("Voc"), r.num("Isc")
    for key, v in (("Voc", voc), ("Isc", isc)):
        if v is None or v <= 0:
            raise ValueError(f"FV modul v souboru PVsyst nemá platnou hodnotu {key}.")
    for col, key in (("p_wp", "PNom"), ("voc_v", "Voc"), ("vmp_v", "Vmp"), ("isc_a", "Isc"), ("imp_a", "Imp"),
                     ("u_sys_max_v", "VMaxIEC")):
        r.put(col, key)
    _coefficient(r, "muVocSpec", "beta_voc", voc, "%/K")
    _coefficient(r, "muISC", "alpha_isc", isc, "%/K")
    gamma = r.num("muPmpReq")
    if gamma is not None:
        r.params["gamma_pmax"] = _fmt(round(gamma, 3))
    raw_tech = (r.root.find("Technol") or "").strip()
    tech = _TECHNOLOGY.get(raw_tech.lower())
    if tech:
        r.params["technology"] = tech
        return []
    return [f"Technol {raw_tech}"] if raw_tech else []


def _inverter(r: _Reader) -> list[str]:
    for col, key in (("p_ac_kw", "PNomConv"), ("mppt", "NbMPPT"), ("un_v", "VOutConv"),
                     ("i_ac_max_a", "IMaxAC"), ("u_dc_max_v", "VAbsMax"), ("u_mppt_min_v", "VMppMin"),
                     ("u_mppt_max_v", "VMPPMax"), ("eff_max_pct", "EfficMax"), ("eff_eu_pct", "EfficEuro")):
        r.put(col, key)
    phases = (r.root.find("MonoTri") or "").strip()
    if phases.lower() in ("mono", "tri"):
        r.params["phases"] = "1" if phases.lower() == "mono" else "3"
    elif not phases:
        r.warnings.append("V souboru PVsyst chybí MonoTri – 'phases' zůstává prázdné.")
    else:
        r.warnings.append(f"MonoTri „{phases}“ nelze převést na 'phases' (Mono/Tri) – sloupec zůstává prázdný.")
    notes: list[str] = []
    pmax_dc = r.num("PMaxDC")
    if pmax_dc is not None:
        notes.append(f"PMaxDC {_fmt(pmax_dc)} kW")
    imax_dc, nb_mppt = r.num("IMaxDC"), r.num("NbMPPT")
    if imax_dc is not None:
        if nb_mppt == 1:
            r.params["i_mppt_max_a"] = _fmt(imax_dc)
        else:
            notes.append(f"IMaxDC {_fmt(imax_dc)} A (celý střídač)")
            r.warnings.append("IMaxDC v PVsyst je proud celého střídače – 'i_mppt_max_a' zůstává prázdné, "
                              "doplňte proud jednoho MPPT z datasheetu.")
    nb_inputs = (r.root.find("NbInputs") or "").strip()
    if nb_inputs:
        notes.append(f"NbInputs {nb_inputs}")
    return notes


def _make_id(mfr: str, pn: str) -> str:
    ascii_text = "".join(ch for ch in unicodedata.normalize("NFKD", f"{mfr}-{pn}")
                         if not unicodedata.combining(ch))
    cid = re.sub(r"[^a-z0-9._+-]+", "-", ascii_text.lower()).strip("-")
    if not cid:
        raise ValueError("Z výrobce a typu nejde vytvořit id artiklu (jen znaky mimo latinku) – "
                         "doplňte Model nebo Manufacturer latinkou.")
    return cid


def import_pvsyst(path: Path | str) -> tuple[Component, list[str]]:
    """Načte `.PAN` (FV modul) nebo `.OND` (střídač) z PVsyst → (artikl, varování). Chybný soubor → `ValueError`."""
    p = Path(path)
    if p.stat().st_size > MAX_BYTES:
        raise ValueError(f"Soubor je příliš velký ({p.stat().st_size // 1024} kB, limit {MAX_BYTES // 1024} kB).")
    root = _parse(_decode(p.read_bytes()))
    kind = root.type.strip().lower()
    if kind not in ("pvmodule", "pvginverter"):
        raise ValueError(f"Nepodporovaný typ objektu PVsyst „{root.type}“ (očekává se FV modul nebo střídač).")
    r = _Reader(root)
    mfr, pn, name = _common(r)
    notes = [NOTE]
    if kind == "pvmodule":
        notes += _module(r)
        category, symbol = "pv_module", "fve.pv_string"
        err_fn = pv_module_error
    else:
        notes += _inverter(r)
        category, symbol = "inverter", "fve.inverter"
        err_fn = inverter_error
    r.params["note"] = "; ".join(notes)
    cid = _make_id(mfr, pn)
    comp = Component(id=cid, manufacturer=mfr,
                     part_number=pn, name=name, category=category, symbol_id=symbol, datasheet_url="", source="user",
                     params=r.params)
    err = err_fn({"id": comp.id, "category": category, **r.params})
    if err:
        r.warnings.append(f"Kontrola hodnot: {err}")
    return comp, r.warnings


def write_components_csv(components: list[Component], out: Path | str) -> int:
    """Artikly → CSV v2 (`;`, UTF-8) pro `LibraryStore.import_components_csv_v2`."""
    extra: list[str] = []
    for c in components:
        extra += [k for k in c.params if k not in extra and k not in REQUIRED]
    cols = REQUIRED + extra
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for c in components:
            w.writerow({"id": c.id, "manufacturer": c.manufacturer, "part_number": c.part_number, "name": c.name,
                        "category": c.category, "symbol_id": c.symbol_id, "datasheet_url": c.datasheet_url,
                        "source": c.source, **c.params})
    return len(components)
