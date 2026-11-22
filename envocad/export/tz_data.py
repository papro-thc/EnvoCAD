"""Data technické zprávy a DSPS z modelu: kontext polí šablony a vkládané bloky (tabulky). Bez Qt.

Návrh `docs/design/tz_dsps.md`. `report_context` vrací slovník pro `doc_template.render` – jen údaje, které model má;
chybějící hodnota je `None` (šablona napíše „neuvedeno“ nebo sekci vynechá podmínkou). `BLOCKS` = vkládané bloky
`{{tabulka.*}}` / `{{blok.*}}` – funkce (dokument, kontext) připíší obsah na konec dokumentu.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime

from envocad.export import reports
from envocad.export.docx_export import _table, set_landscape
from envocad.library.store import LibraryStore
from envocad.model import calc
from envocad.model.advisory import ADVISORY_NOTE
from envocad.model.project import Element, Project, Sheet

INVERTERS = ("fve.inverter", "fve.inverter_hybrid")
FUSES = ("fve.fuse_disconnect", "fve.fuse")
BREAKERS = ("fve.breaker_mcb", "fve.breaker_mccb", "sb.rcbo")
DSPS_META = (("dsps_date", "Datum provedení"), ("dsps_inspection_report", "Revizní zpráva (číslo, datum)"),
             ("dsps_contractor", "Zhotovitel"))
LEVEL_TEXT = {"nn": "na hladině nn (0,4 kV)", "vn": "na hladině vn"}


def _f(v, d=0.0) -> float:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return d


def _cz(v: float, fmt: str = "g") -> str:
    """Číslo s desetinnou čárkou (2,44; 0,8)."""
    return format(v, fmt).replace(".", ",")


def _s(v) -> str:
    return str(v or "").strip()


def _num(v) -> float | None:
    return _f(v, None) if _s(v) else None


def _els(project: Project, *symbols: str) -> list[tuple[Sheet, Element]]:
    return [(s, e) for s in project.sheets for e in s.elements if e.symbol_id in symbols]


def _counted(items: list[str]) -> str | None:
    """[„a“, „a“, „b“] → „2× a, 1× b“ (pořadí výskytu); prázdné → None."""
    c = Counter(x for x in items if x)
    return ", ".join(f"{n}× {k}" for k, n in c.items()) or None


def _join(items) -> str | None:
    out = []
    for x in items:
        if x and x not in out:
            out.append(x)
    return ", ".join(out) or None


# ---- data pro DS (i výkaz „Data pro DS“) ---------------------------------------------------------------------------
def dso_data(project: Project, lib: LibraryStore) -> list[tuple[str, str]]:
    """Údaje pro žádost o připojení výrobny (ČEZ/EG.D/PRE formuláře): výkony, střídače, jištění, kabel."""
    strings = [e for s in project.sheets for e in s.elements if e.symbol_id == "fve.pv_string"]
    invs = [e for s in project.sheets for e in s.elements if e.symbol_id in INVERTERS]
    bats = [e for s in project.sheets for e in s.elements if e.symbol_id == "fve.battery"]
    p_dc = sum(_f(e.attrs.get("n_modules")) * _f(e.attrs.get("p_module")) for e in strings) / 1000
    p_ac = sum(_f(e.attrs.get("p_ac")) for e in invs)
    n_mod = int(sum(_f(e.attrs.get("n_modules")) for e in strings))
    mains = [e for s in project.sheets for e in s.elements if e.symbol_id == "sb.main_switch"]
    grid_wires = [w for s in project.sheets for w in s.wires
                  if any(s.element(end.element_id).symbol_id == "fve.grid" for end in (w.a, w.b))]
    grid = next((e for s in project.sheets for e in s.elements if e.symbol_id == "fve.grid"), None)
    e_bat = sum(_f(e.attrs.get("e_kwh")) for e in bats)
    p_bat = sum(_f(e.attrs.get("p_kw")) for e in bats)
    rows = [
        ("Investor / žadatel", project.meta.get("investor", "")),
        ("Místo výrobny", project.meta.get("place", "")),
        ("Distributor", grid.attrs.get("dso", "") if grid else ""),
        ("Napěťová soustava", grid.attrs.get("voltage", "3×400 V") if grid else "3×400 V"),
        ("Instalovaný výkon FV (DC)", f"{p_dc:g} kWp ({n_mod} modulů, {len(strings)} stringů)"),
        ("Instalovaný výkon střídačů (AC)", f"{p_ac:g} kW ({len(invs)} ks: " + ", ".join(
            f"{e.ref} {e.attrs.get('type', '')} {e.attrs.get('p_ac', '')} kW" for e in invs) + ")"),
        ("Fáze", ", ".join(sorted({e.attrs.get('phases', '3') for e in invs})) + "f" if invs else ""),
        ("Akumulace", f"{e_bat:g} kWh / {p_bat:g} kW" if bats else "bez akumulace"),
        ("Hlavní jištění / vypínač výrobny", ", ".join(f"{e.ref} {e.attrs.get('in_', '')} A" for e in mains)),
        ("Připojovací kabel", ", ".join(f"{w.attrs.get('cable', '')} {w.attrs.get('cross', '')} mm², {w.attrs.get('length', '?')} m"
                                        for w in grid_wires)),
        ("Režim", "paralelní provoz s DS, dodávka přetoků dle smlouvy"),
    ]
    return rows


# ---- kontext ----------------------------------------------------------------------------------------------------
def _fve(project: Project) -> dict:
    strings = [e for _, e in _els(project, "fve.pv_string")]
    invs = [e for _, e in _els(project, *INVERTERS)]
    bats = [e for _, e in _els(project, "fve.battery")]
    p_dc = sum(_f(e.attrs.get("n_modules")) * _f(e.attrs.get("p_module")) for e in strings) / 1000
    if p_dc <= 0:
        p_dc = _num(project.meta.get("p_installed_kwp")) or 0.0
    p_ac = sum(_f(e.attrs.get("p_ac")) for e in invs)
    n_mod = int(sum(_f(e.attrs.get("n_modules")) for e in strings))
    n_opt = int(sum(_f(e.attrs.get("n_optimizers")) for e in strings))
    inv_desc = _counted([" ".join(x for x in (_s(e.attrs.get("type")) or "střídač",
                                              f"{_cz(_f(e.attrs.get('p_ac')))} kW" if _s(e.attrs.get("p_ac")) else "")
                                  if x) for e in invs])
    return {
        "p_dc_kwp": round(p_dc, 3) if p_dc > 0 else None,
        "p_ac_kw": round(p_ac, 3) if p_ac > 0 else None,
        "pomer_dc_ac": round(p_dc / p_ac, 2) if p_dc > 0 and p_ac > 0 else None,
        "moduly_pocet": n_mod or None,
        "modul_typ": _join(_s(e.attrs.get("type")) for e in strings),
        "modul_p_w": _join(_s(e.attrs.get("p_module")) for e in strings),
        "stringy_pocet": len(strings) or None,
        "stridace_pocet": len(invs) or None,
        "stridace_popis": inv_desc,
        "hybrid": any(e.symbol_id == "fve.inverter_hybrid" for e in invs),
        "faze": _join(f"{_s(e.attrs.get('phases'))}f" for e in invs if _s(e.attrs.get("phases"))),
        "optimizery_pocet": n_opt or None,
        "optimizer_typ": _join(_s(e.attrs.get("optimizer")) for e in strings),
        "baterie": _join(" ".join(x for x in (e.ref, _s(e.attrs.get("type")),
                                              f"{_s(e.attrs.get('e_kwh'))} kWh" if _s(e.attrs.get("e_kwh")) else "",
                                              f"/ {_s(e.attrs.get('p_kw'))} kW" if _s(e.attrs.get("p_kw")) else "")
                                  if x) for e in bats),
        "baterie_kwh": round(sum(_f(e.attrs.get("e_kwh")) for e in bats), 2) or None,
        "baterie_kw": round(sum(_f(e.attrs.get("p_kw")) for e in bats), 2) or None,
        "zalohovani": any(_s(e.attrs.get("eps")) not in ("", "0") for e in invs),
    }


def _board_rows(project: Project, lib, cache: dict) -> list[dict]:
    from envocad.model.project import switchboard_header
    out = []
    for s in project.switchboards():
        hdr = dict(switchboard_header(project, s))
        out.append({"oznaceni": s.loc or s.name.split(" – ")[0], "nazev": s.name, "sit": hdr.get("Síť"),
                    "un": hdr.get("Un"), "in_": hdr.get("In"), "skrin": hdr.get("Skříň"), "rozmery": hdr.get("Rozměry"),
                    "kryti": hdr.get("Krytí"), "icw": hdr.get("Icw / Ipk"), "otepleni": _thermal(project, lib, s, cache)})
    return out


def _thermal(project: Project, lib, s: Sheet, cache: dict):
    key = ("thermal", s.id)
    if key not in cache:
        from envocad.model.thermal import layout_inputs, temperature_rise
        try:
            rdf, t_amb = layout_inputs(s.layout)
            cache[key] = temperature_rise(s, rdf=rdf, t_ambient_c=t_amb, project=project, lib=lib)
        except Exception:  # noqa: BLE001 – rozvaděč bez rozložení / poškozená data: bez výpočtu
            cache[key] = None
    r = cache[key]
    return r.verdict() if r is not None else None


def _blocks_by_ref(project: Project) -> dict[str, Element]:
    return {e.ref: e for _, e in _els(project, "fve.switchboard") if e.ref}


def _dc(project: Project, lib, cache: dict) -> dict:
    t_min, t_max = calc.design_temperatures(project)
    sc = cache["strings"]
    fuses = [e for _, e in _els(project, *FUSES) if "pv" in _s(e.attrs.get("char")).lower()]
    spds = [e for _, e in _els(project, "fve.spd")]
    dc_spd = [e for e in spds if "dc" in (_s(e.attrs.get("spd_type")) + _s(e.attrs.get("uc"))).lower()]
    cables = [c for c in cache["cables"] if c.system == "dc"]
    bad = [f"{x.ref}: {'; '.join(x.issues)}" for x in sc if not x.ok]
    from envocad.model.ratings import design_t_min_given
    return {
        "t_min": t_min, "t_max": t_max, "t_predpoklad": not design_t_min_given(project),
        "uoc_max_v": max((x.uoc_cold for x in sc if x.uoc_cold), default=None),
        "umpp_min_v": min((x.umpp_hot for x in sc if x.umpp_hot), default=None),
        "soustava": _join(_parts(cache["boards"], "un", dc=True)),
        "sit": _join(_parts(cache["boards"], "sit", dc=True)),
        "jisteni_stringu": _counted([" ".join(x for x in (f"{_s(e.attrs.get('in_'))} A" if _s(e.attrs.get("in_")) else "",
                                                          _s(e.attrs.get("char")), _s(e.attrs.get("type"))) if x)
                                     for e in fuses]),
        "svodice": _counted([" ".join(x for x in (_s(e.attrs.get("spd_type")), _s(e.attrs.get("type"))) if x)
                             for e in dc_spd]),
        "kabely": _join(_s(cache["wire_cable"].get(c.ref)) for c in cables),
        "vyhovuje": (None if not sc else ("všechny stringy vyhovují" if not bad else "nevyhovuje – " + "; ".join(bad))),
        "chybi_1500": _s(project.meta.get("dc_system_missing")) or None,
    }


def _ac(project: Project, cache: dict) -> dict:
    blocks = _blocks_by_ref(project)
    spds = [e for _, e in _els(project, "fve.spd")]
    ac_spd = [e for e in spds if "dc" not in (_s(e.attrs.get("spd_type")) + _s(e.attrs.get("uc"))).lower()]
    cables = [c for c in cache["cables"] if c.system != "dc" and _s(cache["wire_cable"].get(c.ref))
              and not _s(cache["wire_cable"].get(c.ref)).upper().startswith("CYA")]
    mains = [e for _, e in _els(project, "sb.main_switch")]
    main_txt = _join([f"{e.ref} {_s(e.attrs.get('in_'))} A".strip() for e in mains]
                     + [f"{ref}: {_s(b.attrs.get('main'))}" for ref, b in blocks.items()
                        if ref.startswith("RFVE") and _s(b.attrs.get("main"))])
    inv_prot = _join([f"{ref}: {_s(b.attrs.get('inv_protect'))}" for ref, b in blocks.items()
                      if _s(b.attrs.get("inv_protect"))]
                     + [" ".join(x for x in (e.ref, f"{_s(e.attrs.get('in_'))} A" if _s(e.attrs.get("in_")) else "",
                                             _s(e.attrs.get("char"))) if x)
                        for _, e in _els(project, *BREAKERS) if _s(e.attrs.get("chain")) == "inv"])
    rcds = [e for _, e in _els(project, "sb.rcd", "sb.rcbo")]
    sel = cache["selectivity"]
    tree = cache["selectivity_tree"]
    sel_txt = None
    if sel or tree:
        problems = [f"{lo} → {hi}: {msg}" for lo, hi, _il, _ih, msg in sel if msg != "OK"] + \
                   [f"{c.element.ref} → {c.upper.ref}: {c.msg}" for c in (tree or [])]
        sel_txt = "vyhovuje (poměr jmenovitých proudů)" if not problems else "; ".join(problems)
    return {
        "hlavni_vypinac": main_txt,
        "jisteni_stridacu": inv_prot,
        "vyvod_fve": _join(f"{ref}: {_s(b.attrs.get('fve_out'))}" for ref, b in blocks.items()
                           if _s(b.attrs.get("fve_out"))),
        "kabely": _join(_s(cache["wire_cable"].get(c.ref)) for c in cables),
        "svodice": _counted([" ".join(x for x in (_s(e.attrs.get("spd_type")), _s(e.attrs.get("type"))) if x)
                             for e in ac_spd]),
        "chranice": _counted([" ".join(x for x in (f"{_s(e.attrs.get('idn'))} mA" if _s(e.attrs.get("idn")) else "",
                                                   f"typ {_s(e.attrs.get('rcd_type'))}" if _s(e.attrs.get("rcd_type")) else "")
                                       if x) or "proudový chránič" for e in rcds]),
        "selektivita": sel_txt,
    }


def _ds(project: Project, cache: dict) -> dict:
    blocks = _blocks_by_ref(project)
    grids = [e for _, e in _els(project, "fve.grid")]
    hds = [e for _, e in _els(project, "fve.hds")]
    trs = [e for _, e in _els(project, "fve.transformer")]
    level = _s(project.meta.get("topology"))
    level = "vn" if level == "vn" or any("kV" in _s(g.attrs.get("voltage")) for g in grids) else ("nn" if grids else None)
    metering = _join(f"{ref}: {_s(b.attrs.get('metering'))}" for ref, b in blocks.items() if _s(b.attrs.get("metering")))
    meters = _join(" ".join(x for x in (e.ref, _s(e.attrs.get("kind")), _s(e.attrs.get("type"))) if x)
                   for _, e in _els(project, "fve.meter"))
    boundary = _join(" ".join(x for x in (e.ref or "HDS", "(hranice vlastnictví)") if x) for e in hds
                     if _s(e.attrs.get("boundary")) not in ("", "0"))
    grid_cable = []
    for s in project.sheets:
        for w in s.wires:
            ends = []
            for end in (w.a, w.b):
                try:
                    ends.append(s.element(end.element_id).symbol_id)
                except KeyError:
                    pass
            if ("fve.grid" in ends or "fve.hds" in ends) and _s(w.attrs.get("cable")):
                grid_cable.append(" ".join(x for x in (_s(w.attrs.get("ref")), _s(w.attrs.get("cable")),
                                                       f"{_s(w.attrs.get('length'))} m" if _s(w.attrs.get("length")) else "")
                                           if x))
    return {
        "distributor": _join(_s(g.attrs.get("dso")) for g in grids),
        "napeti": _join(_s(g.attrs.get("voltage")) for g in grids),
        "uroven": level,
        "uroven_text": LEVEL_TEXT.get(level or ""),
        "mereni": _join([metering, meters]),
        "hranice": boundary,
        "hds": _join(" ".join(x for x in (e.ref, _s(e.attrs.get("desc")),
                                          f"pojistky {_s(e.attrs.get('in_'))} A {_s(e.attrs.get('char'))}".strip()
                                          if _s(e.attrs.get("in_")) else "") if x) for e in hds),
        "transformator": _join(" ".join(x for x in (e.ref, _s(e.attrs.get("type")),
                                                    f"{_s(e.attrs.get('sn'))} kVA" if _s(e.attrs.get("sn")) else "",
                                                    _s(e.attrs.get("ratio")), _s(e.attrs.get("group")),
                                                    f"uk {_s(e.attrs.get('uk'))} %" if _s(e.attrs.get("uk")) else "")
                                           if x) for e in trs),
        "stanice": _join([_s(e.attrs.get("station")) for e in trs]
                         + [_s(b.attrs.get("station")) for b in blocks.values()]),
        "rvn": (_s(blocks["RVN"].attrs.get("main")) or "rozvaděč VN") if "RVN" in blocks else None,
        "kabel": _join(grid_cable),
        "hlavni_jisteni": _join(f"{ref}: {_s(b.attrs.get('main'))}" for ref, b in blocks.items()
                                if ref in ("HR", "RD", "RE") and _s(b.attrs.get("main"))),
    }


def _grid_protection(project: Project, kwp: float | None) -> dict:
    from envocad.model.checks import grid_protection_required
    limit = _num(project.meta.get("grid_protection_kwp")) or 30.0
    devs = [e for _, e in _els(project, "fve.grid_protection")]
    on_block = [e for _, e in _els(project, "fve.switchboard") if grid_protection_required(e)]
    required = kwp is not None and kwp > limit + 1e-9
    if devs:
        state = "navržena v projektu: " + ", ".join(" ".join(x for x in (e.ref, _s(e.attrs.get("type"))) if x) for e in devs)
    elif on_block:
        state = "požadována v rozvaděči " + ", ".join(e.ref for e in on_block) + " (dodá výrobce rozvaděče)"
    else:
        state = None
    return {
        "hranice_kwp": limit,
        "pozadovana": required,
        "stav": state,
        "nastaveni": _join(_s(e.attrs.get("settings")) for e in devs),
        "pusobi_na": _join(_s(e.attrs.get("acts_on")) for e in devs),
    }


def _earthing(project: Project) -> dict:
    earths = [(s, e) for s, e in _els(project, "fve.earth")]
    wires = []
    for s, e in earths:
        for w in s.wires:
            if e.id in (w.a.element_id, w.b.element_id) and _s(w.attrs.get("cable")):
                wires.append(_s(w.attrs.get("cable")))
    return {"hop": _join(_s(e.attrs.get("desc")) or "uzemnění" for _, e in earths), "vodic": _join(wires)}


def _parts(boards: list[dict], key: str, dc: bool) -> list[str]:
    """Části údaje hlavičky rozvaděče („3NPE, 50 Hz / DC IT“ – kombinovaný rozvaděč) jen pro DC nebo jen pro AC."""
    out = []
    for b in boards:
        for part in _s(b.get(key)).split(" / "):
            part = part.strip()
            if part and ("dc" in part.lower()) == dc:
                out.append(part)
    return out


def _networks(cache: dict) -> str | None:
    return _join(_parts(cache["boards"], "sit", dc=False))


def _sheets_rows(project: Project) -> list[dict]:
    from envocad.model.frame import sheet_number
    from envocad.model.revision import sheet_revision
    out = []
    for s in project.sheets:
        rev = sheet_revision(project, s)
        out.append({"cislo": sheet_number(project, s), "nazev": s.name, "format": s.paper,
                    "druh": "rozvaděč" if s.is_switchboard else "schéma", "revize": rev.label if rev else None})
    return out


def _change_rows(changes) -> list[dict]:
    from envocad.model.diff import MOVE_DETAIL
    return [{"list": c.sheet, "oznaceni": c.ref, "druh": c.kind, "co": c.what, "popis": c.detail}
            for c in changes if c.detail != MOVE_DETAIL]


def _change_list(project: Project) -> list[dict]:
    from envocad.model.diff import split_change_line
    out = []
    for line in _s(project.meta.get("changes")).splitlines():
        if line.strip():
            rev, dt, desc, author = split_change_line(line)
            out.append({"revize": rev, "datum": dt, "popis": desc, "zpracoval": author})
    return out


def report_context(project: Project, lib: LibraryStore, *, kind: str = "tz", old: Project | None = None,
                   fields: Mapping[str, str] | None = None, company: str = "", today: date | None = None) -> dict:
    """Kontext šablony TZ / DSPS (`kind` "tz" | "dsps"). `old` = projekt dle PD (DSPS – změny proti němu),
    `fields` = hodnoty z exportního dialogu (`pole.*`, u DSPS přepisují meta `dsps_*`), `company` = firemní standard."""
    m = project.meta
    cache: dict = {}
    t_min, t_max = calc.design_temperatures(project)
    try:
        cache["strings"] = calc.check_strings(project, t_min, t_max, lib=lib)
    except Exception:  # noqa: BLE001 – neúplný projekt: zpráva bez kontroly stringů
        cache["strings"] = []
    try:
        cache["cables"] = calc.check_cables(project)
    except Exception:  # noqa: BLE001
        cache["cables"] = []
    cache["wire_cable"] = {w.attrs.get("ref"): w.attrs.get("cable") for s in project.sheets for w in s.wires
                           if w.attrs.get("ref")}
    try:
        cache["selectivity"] = calc.check_selectivity(project)
    except Exception:  # noqa: BLE001
        cache["selectivity"] = []
    try:
        cache["selectivity_tree"] = calc.check_selectivity_tree(project, lib)
    except Exception:  # noqa: BLE001
        cache["selectivity_tree"] = None
    cache["boards"] = _board_rows(project, lib, cache)
    fve = _fve(project)
    from envocad.model.ratings import upstream_ik
    ik = upstream_ik(project)
    cc = cache["cables"]
    du = [c.du_pct for c in cc if c.du_pct is not None]
    fields = dict(fields or {})
    ctx: dict = {
        "projekt": {"nazev": project.name, "investor": m.get("investor"), "misto": m.get("place"),
                    "zakazka": m.get("order"), "zpracoval": m.get("author"), "datum": m.get("date"),
                    "revize": m.get("revision"), "objekt": m.get("building"), "firma": company or None},
        "dnes": (today or datetime.now().astimezone().date()).strftime("%d.%m.%Y"),
        "fve": fve,
        "topologie": {"id": m.get("topology"), "retezec": m.get("topology_chain"),
                      "uroven": None},
        "dc": _dc(project, lib, cache),
        "ac": _ac(project, cache),
        "ds": _ds(project, cache),
        "ochrana": {"sit": _networks(cache)},
        "sitova_ochrana": _grid_protection(project, fve["p_dc_kwp"]),
        "uzemneni": _earthing(project),
        "zkrat": {"ik_ka": ik[0] if ik else None, "zdroj": ik[1] if ik else None},
        "vypocty": {"kabely_pocet": len(cc) or None,
                    "nevyhovuje": [c.ref for c in cc if c.issues] or None,
                    "du_max": max(du) if du else None},
        "stridace": [{"oznaceni": e.ref, "typ": _s(e.attrs.get("type")) or None, "p_ac_kw": _s(e.attrs.get("p_ac")) or None,
                      "faze": _s(e.attrs.get("phases")) or None, "mppt": _s(e.attrs.get("mppt")) or None,
                      "u_dc_max": _s(e.attrs.get("u_dc_max")) or None, "hybrid": e.symbol_id == "fve.inverter_hybrid",
                      "list": s.name} for s, e in _els(project, *INVERTERS)],
        "rozvadece": cache["boards"],
        "listy": _sheets_rows(project),
        "revize": [{"oznaceni": r.label, "datum": r.date or None, "zpracoval": r.author or None,
                    "popis": r.description or None, "uzavrena": r.closed} for r in project.revisions],
        "zmenovy_list": _change_list(project),
        "meta": {k: v for k, v in m.items() if isinstance(v, str)},
        "pole": fields,
        "druh": kind,
        "_project": project, "_lib": lib, "_cache": cache,
    }
    ctx["topologie"]["uroven"] = ctx["ds"]["uroven"]
    if kind == "dsps":
        changes = []
        if old is not None:
            from envocad.model.diff import diff_projects, summary
            changes = diff_projects(old, project, lib)
            rows = _change_rows(changes)
            ctx["dsps_zmeny_souhrn"] = summary([c for c in changes if c.detail != _move_detail()])
        else:
            rows = []
        dsps = {key.removeprefix("dsps_"): (fields.get(key) or _s(m.get(key)) or None) for key, _ in DSPS_META}
        ctx["dsps"] = {"datum_provedeni": dsps["date"], "revizni_zprava": dsps["inspection_report"],
                       "zhotovitel": dsps["contractor"],
                       "porovnano_s": (" ".join(x for x in (old.name, f"rev. {_s(old.meta.get('revision'))}"
                                                           if _s(old.meta.get("revision")) else "") if x)
                                       if old is not None else None),
                       "zmeny": rows, "zmeny_pocet": len(rows) if old is not None else None,
                       "zmeny_souhrn": ctx.pop("dsps_zmeny_souhrn", None)}
    return ctx


def _move_detail() -> str:
    from envocad.model.diff import MOVE_DETAIL
    return MOVE_DETAIL


# ---- vkládané bloky -------------------------------------------------------------------------------------------------
def _p(ctx: Mapping) -> Project:
    return ctx["_project"]


def _none_paragraph(doc, text: str = "V projektu nejsou.") -> None:
    doc.add_paragraph(text)


def block_basic(doc, ctx) -> None:
    _table(doc, ["Údaj", "Hodnota"], [list(r) for r in dso_data(_p(ctx), ctx["_lib"])])


def block_strings(doc, ctx) -> None:
    strings = _els(_p(ctx), "fve.pv_string")
    if not strings:
        return _none_paragraph(doc, "Stringy v projektu nejsou.")
    _table(doc, ["String", "Typ modulu", "Modulů", "Optimizéry", "P [kWp]", "Uoc mod. [V]", "Isc mod. [A]", "List"],
           [[e.ref, e.attrs.get("type", ""), e.attrs.get("n_modules", ""),
             f"{e.attrs['n_optimizers']}× {e.attrs.get('optimizer', '')}".strip() if e.attrs.get("n_optimizers") else "–",
             e.attrs.get("p_string", ""), e.attrs.get("voc", ""), e.attrs.get("isc", ""), s.name] for s, e in strings])


def block_string_check(doc, ctx) -> None:
    project = _p(ctx)
    t_min, t_max = calc.design_temperatures(project)
    sc = ctx["_cache"]["strings"]
    if not sc:
        return _none_paragraph(doc, "Kontrolu stringů nelze provést – v projektu nejsou stringy připojené ke střídači.")
    classic = [x for x in sc if x.mode != "fixed_voltage"]
    fixed = [x for x in sc if x.mode == "fixed_voltage"]
    if classic:
        _table(doc, ["String", "Střídač", f"Uoc při {t_min:g} °C [V]", f"Umpp při {t_max:g} °C [V]",
                     "1,25·Isc [A]", "Umax / MPPT střídače", "Výsledek"],
               [[x.ref, x.inverter, x.uoc_cold, x.umpp_hot, round(calc.SAFETY_ISC * x.isc, 1),
                 f"{x.u_dc_max or '–'} / {x.u_mppt_min or '–'}–{x.u_mppt_max or '–'} V",
                 "vyhovuje" if x.ok else "; ".join(x.issues)] for x in classic])
        doc.add_paragraph("")
    if fixed:   # pevné napětí (SolarEdge): Uoc·n, okno MPPT ani 1,25·Isc nemají význam – vlastní tabulka
        doc.add_paragraph("Stringy s pevným napětím (optimizér na každém modulu, napětí řídí střídač):")
        _table(doc, ["String", "Střídač", "Modulů / optimizérů", "Pevné napětí", "P stringu / max [W]",
                     "Optimizérů min–max", "Umax střídače [V]", "Výsledek"],
               [[x.ref, x.inverter, f"{x.n} / {x.n_opt or '–'}", *reports.fixed_voltage_parts(x),
                 f"{x.n_opt_min or '–'}–{x.n_opt_max or '–'}", x.u_dc_max or "–",
                 "vyhovuje" if x.ok else "; ".join(x.issues)] for x in fixed])
        doc.add_paragraph("")


def block_inverters(doc, ctx) -> None:
    invs = _els(_p(ctx), *INVERTERS, "fve.battery")
    if not invs:
        return _none_paragraph(doc, "Střídače v projektu nejsou.")
    _table(doc, ["Označení", "Typ", "P AC [kW] / E [kWh]", "MPPT", "Fáze", "U DC max [V]", "List"],
           [[e.ref, e.attrs.get("type", ""), e.attrs.get("p_ac") or e.attrs.get("e_kwh", ""), e.attrs.get("mppt", ""),
             e.attrs.get("phases", ""), e.attrs.get("u_dc_max", ""), s.name] for s, e in invs])


def block_switchboards(doc, ctx) -> None:
    from envocad.model.project import switchboard_header
    project, lib = _p(ctx), ctx["_lib"]
    boards = project.switchboards()
    if not boards:
        return _none_paragraph(doc, "Listy rozvaděčů v projektu nejsou.")
    for s in boards:
        doc.add_heading(f"{{{{§}}}} {s.name}", 2)
        _table(doc, ["Parametr", "Hodnota"], [[k, v] for k, v in switchboard_header(project, s) if v])
        _thermal(project, lib, s, ctx["_cache"])
        r = ctx["_cache"].get(("thermal", s.id))
        if r is not None:
            src = r.loss_summary()
            doc.add_paragraph(f"Odhad oteplení dle IEC TR 60890: ΣPv = {r.p_total_w:.0f} W"
                              + (f" ({src})" if src else "") + f", Ae = {_cz(r.ae_m2, '.2f')} m², "
                              f"Δt uprostřed {_cz(r.dt_mid_k, '.1f')} K, v horní části {_cz(r.dt_top_k, '.1f')} K – "
                              f"{r.verdict()}.")
            losses = [x for x in r.losses if x.p_w > 0]
            if losses:
                # ztrátové výkony po přístrojích se zdrojem údaje (artikl / ruční / odhad z In)
                _table(doc, ["Přístroj", "Pv při In [W]", f"Pv při {_cz(r.rdf)}·In [W]", "Zdroj"],
                       [[x.ref or "?", _cz(x.p_rated_w) if x.p_rated_w is not None else "–", _cz(x.p_w), x.source]
                        for x in losses])
        head, rows = reports.device_list(project, lib, s)
        if rows:
            _table(doc, head[:6], [r[:6] for r in rows])
        doc.add_paragraph("")


def block_cables(doc, ctx) -> None:
    cc = ctx["_cache"]["cables"]
    if not cc:
        return _none_paragraph(doc, "Kabely s údaji pro výpočet v projektu nejsou.")
    _table(doc, ["Kabel", "I [A]", "S [mm²]", "L [m]", "Uložení", "Iz [A]", "Jistič In [A]", "ΔU [%]", f"Výsledek ({ADVISORY_NOTE})"],
           [[c.ref, c.i_a or "", c.cross or "", c.length or "", c.method, c.iz or "",
             f"{c.breaker_ref} {c.in_breaker:g}" if c.in_breaker else "",
             c.du_pct if c.du_pct is not None else "", "vyhovuje" if not c.issues else "; ".join(c.issues)] for c in cc])
    doc.add_paragraph(f"Zatížitelnost Iz dle ČSN 33 2000-5-52 (Cu, PVC, 30 °C) – {ADVISORY_NOTE}; "
                      "úbytek napětí činný, mez 3 % od rozvaděče k výrobně.")


def block_selectivity(doc, ctx) -> None:
    sel = ctx["_cache"]["selectivity"]
    tree = ctx["_cache"]["selectivity_tree"] or []
    if not sel and not tree:
        return _none_paragraph(doc, "Dvojice jisticích přístrojů k posouzení selektivity v projektu nejsou.")
    rows = [[lo, hi, il, ih, msg] for lo, hi, il, ih, msg in sel]
    rows += [[c.element.ref, c.upper.ref, c.element.attrs.get("in_", ""), c.upper.attrs.get("in_", ""), c.msg]
             for c in tree]
    _table(doc, ["Jistič", "Nadřazený", "In [A]", "In nadř. [A]", "Selektivita"], rows)


def block_spd(doc, ctx) -> None:
    spds = _els(_p(ctx), "fve.spd")
    if not spds:
        return _none_paragraph(doc, "Svodiče přepětí v projektu nejsou.")
    _table(doc, ["Označení", "Typ SPD", "Uc [V]", "Póly", "Typ", "List"],
           [[e.ref, e.attrs.get("spd_type", ""), e.attrs.get("uc", ""), e.attrs.get("poles", ""), e.attrs.get("type", ""),
             s.name] for s, e in spds])


def block_string_fuses(doc, ctx) -> None:
    fuses = [(s, e) for s, e in _els(_p(ctx), *FUSES) if "pv" in _s(e.attrs.get("char")).lower()]
    if not fuses:
        return _none_paragraph(doc, "Jištění stringů pojistkami gPV v projektu není.")
    _table(doc, ["Označení", "In [A]", "Char.", "Un [V]", "Typ", "Výrobce", "List"],
           [[e.ref, e.attrs.get("in_", ""), e.attrs.get("char", ""), e.attrs.get("un", ""), e.attrs.get("type", ""),
             e.attrs.get("manufacturer", ""), s.name] for s, e in fuses])


def block_sheets(doc, ctx) -> None:
    _table(doc, ["Číslo", "Název listu", "Formát", "Druh", "Revize"],
           [[x["cislo"], x["nazev"], x["format"], x["druh"], x["revize"] or ""] for x in ctx["listy"]])


def block_revisions(doc, ctx) -> None:
    revs = ctx["revize"]
    if not revs:
        return _none_paragraph(doc, "Projekt nemá zapsané revize.")
    _table(doc, ["Revize", "Datum", "Zpracoval", "Popis", "Stav"],
           [[r["oznaceni"], r["datum"] or "", r["zpracoval"] or "", r["popis"] or "",
             "uzavřena" if r["uzavrena"] else "otevřena"] for r in revs])


def block_change_list(doc, ctx) -> None:
    rows = ctx["zmenovy_list"]
    if not rows:
        return _none_paragraph(doc, "Změnový list projektu je prázdný.")
    _table(doc, ["Revize", "Datum", "Popis změny", "Zpracoval"],
           [[r["revize"], r["datum"], r["popis"], r["zpracoval"]] for r in rows])


def block_changes(doc, ctx) -> None:
    d = ctx.get("dsps") or {}
    rows = d.get("zmeny") or []
    if d.get("zmeny_pocet") is None:
        return _none_paragraph(doc, "Porovnání s projektovou dokumentací nebylo provedeno (nezvolen soubor projektu).")
    if not rows:
        return _none_paragraph(doc, "Proti projektové dokumentaci beze změn.")
    _table(doc, ["List", "Označení", "Druh", "Co", "Popis změny"],
           [[r["list"], r["oznaceni"], r["druh"], r["co"], r["popis"]] for r in rows])


def block_reports(doc, ctx) -> None:
    project, lib = _p(ctx), ctx["_lib"]
    set_landscape(doc, True)     # výkazy mají hodně sloupců – na šířku
    for name, fn in (("Výkaz materiálu", reports.bom), ("Kabely", reports.cables)):
        doc.add_heading(f"{{{{§}}}} {name}", 2)
        head, rows = fn(project, lib, None)
        _table(doc, head, rows)
        doc.add_paragraph("")


BLOCKS = {
    "tabulka.zakladni_udaje": block_basic,
    "tabulka.stringy": block_strings,
    "blok.kontrola_stringu": block_string_check,
    "tabulka.stridace": block_inverters,
    "blok.rozvadece": block_switchboards,
    "tabulka.kabely": block_cables,
    "tabulka.selektivita": block_selectivity,
    "tabulka.svodice": block_spd,
    "tabulka.jisteni_stringu": block_string_fuses,
    "tabulka.listy": block_sheets,
    "tabulka.revize": block_revisions,
    "tabulka.zmenovy_list": block_change_list,
    "tabulka.zmeny": block_changes,
    "blok.vykazy": block_reports,
}
