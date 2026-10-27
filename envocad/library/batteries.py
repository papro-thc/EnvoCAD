"""Baterie z katalogu (`batteries.csv`, kategorie `battery`) pro průvodce a generátor – bez Qt.

Věž = základ (`master` = BMS + první modul, nebo `module` = modul bez BMS) + přídavné moduly (`slave`, odkaz
`bat_link` u masteru) nebo řídicí jednotka (`bms`, odkaz `bat_link` u modulu; u více variant se vybírá). Hotové
úložiště (`system`) je jeden kus. Role a sloupce: `docs/COMPONENTS.md`.

Ke střídači pasují jen některé baterie (`compatible`): sloupec `inv_compat` základu věže = vzory typů střídačů
z datasheetu baterie (`SUN2000-*KTL-M1`, oddělené čárkou, „-“ = k žádnému střídači, např. úložiště s vlastním PCS);
bez `inv_compat` pasuje baterie stejného výrobce jako střídač (BMS komunikuje protokolem výrobce).

Specifikace baterie pro generátor (`spec["battery"]`, `envocad/generate.py`): `component_id` (základ věže),
`modules` (celkový počet modulů věže, u masteru včetně něj), nepovinně `bms_id` (řídicí jednotka); hodnoty `type`,
`e_kwh`, `p_kw` zadané ve specifikaci mají přednost před artiklem (viz `apply_battery_component`).
"""
from __future__ import annotations

from fnmatch import fnmatchcase

from envocad.library.components import Component

BASE_ROLES = ("master", "module", "system")   # co lze zvolit jako baterii v průvodci


def _fmt(x: float) -> str:
    return f"{round(x, 3):g}"


def link_ids(comp: Component) -> list[str]:
    """Id artiklů z `bat_link` (oddělené čárkou nebo středníkem)."""
    raw = (comp.params.get("bat_link") or "").replace(";", ",")
    return [x.strip() for x in raw.split(",") if x.strip()]


def compat_patterns(battery: Component) -> list[str]:
    """Vzory typů střídačů z `inv_compat` (oddělené čárkou nebo středníkem); prázdné = podle výrobce."""
    raw = (battery.params.get("inv_compat") or "").replace(";", ",")
    return [x.strip() for x in raw.split(",") if x.strip()]


def compatible(battery: Component, inverter: Component) -> bool:
    """Pasuje baterie (základ věže) ke střídači? Vzory `inv_compat` na typ střídače (`part_number`, bez rozlišení
    velikosti, `*` a `?` jako v názvech souborů), bez vzorů stejný výrobce."""
    pats = compat_patterns(battery)
    if pats:
        pn = inverter.part_number.strip().upper()
        return any(fnmatchcase(pn, p.upper()) for p in pats)
    return battery.manufacturer.strip().lower() == inverter.manufacturer.strip().lower()


def choices(components, inverter: Component | None = None, only_compatible: bool = True) -> list[Component]:
    """Baterie k výběru (kategorie `battery`, role master / module / system s kapacitou). Se střídačem jen ty,
    které k němu pasují (`compatible`); s `only_compatible=False` všechny, výrobce stejný jako u střídače první.
    Řazení podle výrobce, kapacity a typu."""
    mfr = (inverter.manufacturer if inverter is not None else "").strip().lower()
    out = [c for c in components if c.category == "battery"
           and (c.params.get("bat_role") or "master") in BASE_ROLES and c.num("e_kwh")]
    if inverter is not None and only_compatible:
        out = [c for c in out if compatible(c, inverter)]
    return sorted(out, key=lambda c: (c.manufacturer.strip().lower() != mfr, c.manufacturer.lower(),
                                      c.num("e_kwh") or 0, c.part_number))


def parts(lib, base: Component) -> tuple[Component | None, list[Component]]:
    """(přídavný modul `slave` | None, řídicí jednotky `bms` k výběru) podle `bat_link` základu věže."""
    slave: Component | None = None
    bms: list[Component] = []
    for cid in link_ids(base):
        c = lib.component(cid)
        if c is None or c.category != "battery":
            continue
        role = c.params.get("bat_role") or ""
        if role == "slave" and slave is None:
            slave = c
        elif role == "bms":
            bms.append(c)
    return slave, bms


def module_range(base: Component) -> tuple[int, int]:
    """Povolený počet modulů věže (min, max) z `n_mod_min` / `n_mod_max`; chybějící: min 1, max 1 u `system`,
    jinak bez horní meze (99)."""
    lo = int(base.num("n_mod_min") or 1)
    hi = base.num("n_mod_max")
    if hi is None:
        hi = 1 if (base.params.get("bat_role") or "") == "system" else 99
    return lo, max(int(hi), lo)


def totals(base: Component, n: int, slave: Component | None) -> dict[str, float | None]:
    """Celková kapacita [kWh] a výkon [kW] věže o n modulech: základ + (n − 1) × slave (jinak n × základ).
    Výkon jen když ho artikl (i slave) uvádí – jinak None (neodhaduje se)."""
    n = max(int(n), 1)
    rest = slave if slave is not None else base
    e0, e1 = base.num("e_kwh"), rest.num("e_kwh")
    p0, p1 = base.num("p_kw"), rest.num("p_kw")
    e = None if e0 is None or e1 is None else e0 + (n - 1) * e1
    p = None if p0 is None or p1 is None else p0 + (n - 1) * p1
    return {"e_kwh": e, "p_kw": p}


def battery_spec(lib, component_id: str, modules: int = 1, bms_id: str = "", every_inverter: bool = False) -> dict:
    """`spec["battery"]` z výběru v průvodci: id základu věže, počet modulů, (nepovinně) řídicí jednotka a baterie
    u každého střídače (`inverters: "all"`, jinak jen u prvního)."""
    out: dict = {"component_id": component_id, "modules": int(modules)}
    if bms_id:
        out["bms_id"] = bms_id
    if every_inverter:
        out["inverters"] = "all"
    return out


def battery_targets(spec: dict) -> list[int]:
    """Pořadí střídačů (od 0) s baterií podle `spec["battery"]["inverters"]`: „all“ = všechny, seznam označení
    (`["T1", "T3"]` nebo „T1 T3“) = ty, jinak (chybí) jen první. Bez baterie prázdné. Neznámé označení → ValueError."""
    b = spec.get("battery")
    invs = spec.get("inverters") or []
    if not b or not invs:
        return []
    which = b.get("inverters") if isinstance(b, dict) else None
    if which in (None, "", []):
        return [0]
    if isinstance(which, str) and which.strip().lower() == "all":
        return list(range(len(invs)))
    refs = which.replace(",", " ").split() if isinstance(which, str) else [str(x) for x in which]
    names = [inv.get("ref") or f"T{i + 1}" for i, inv in enumerate(invs)]
    bad = [r for r in refs if r not in names]
    if bad:
        raise ValueError(f"Baterie: neznámý střídač {', '.join(bad)} v battery.inverters (jsou {', '.join(names)}).")
    return [names.index(r) for r in dict.fromkeys(refs)]


def apply_battery_component(lib, battery: dict) -> dict:
    """Doplní `spec["battery"]` z artiklu (`component_id`): `type` ← part_number, `manufacturer`, `e_kwh` a `p_kw` věže,
    `n_modules`, `slave_type`, `bms`. Zadané neprázdné hodnoty specifikace mají přednost. Neznámý artikl nebo jiná
    kategorie než `battery` → beze změny. Počet modulů mimo `n_mod_min` / `n_mod_max` artiklu → ValueError (česky)."""
    out = dict(battery)
    comp = lib.component(battery.get("component_id")) if battery.get("component_id") else None
    if comp is None or comp.category != "battery":
        return out
    try:
        n = int(float(str(battery.get("modules") or 1).replace(",", ".")))
    except ValueError:
        raise ValueError(f"Baterie: počet modulů „{battery.get('modules')}“ není celé číslo.") from None
    lo, hi = module_range(comp)
    if not lo <= n <= hi:
        raise ValueError(f"Baterie {comp.part_number}: počet modulů {n} je mimo rozsah {lo}–{hi}.")
    slave, _bms_opts = parts(lib, comp)
    bms = lib.component(battery.get("bms_id")) if battery.get("bms_id") else None
    if bms is not None and (bms.category != "battery" or (bms.params.get("bat_role") or "") != "bms"):
        bms = None
    tot = totals(comp, n, slave)
    vals = {"type": comp.part_number, "manufacturer": comp.manufacturer,
            "e_kwh": None if tot["e_kwh"] is None else _fmt(tot["e_kwh"]),
            "p_kw": None if tot["p_kw"] is None else _fmt(tot["p_kw"]),
            "n_modules": str(n),
            "slave_type": slave.part_number if slave is not None and n > 1 else "",
            "bms": bms.part_number if bms is not None else ""}
    for k, v in vals.items():
        if out.get(k) in (None, "") and v not in (None, ""):
            out[k] = v
    out["component_id"] = comp.id
    return out
