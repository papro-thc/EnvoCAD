"""Technická zpráva (docx) z modelu + data pro žádost o připojení k DS.

Kostra TZ s tabulkami doplněnými z projektu: FV pole (stringy), střídače, rozvaděče (skříň, oteplení),
kabely (průřezy, úbytky, Iz), jištění, výsledky kontrol. Text kapitol je šablonový – po vygenerování se dopisuje.
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Pt

from envocad.export import reports
from envocad.export.docx_export import _table, doc_author, set_landscape, setup_document
from envocad.library.store import LibraryStore
from envocad.model import calc
from envocad.model.project import Project, without_dangling


def _f(v, d=0.0) -> float:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return d


def dso_data(project: Project, lib: LibraryStore) -> list[tuple[str, str]]:
    """Údaje pro žádost o připojení výrobny (ČEZ/EG.D/PRE formuláře): výkony, střídače, jištění, kabel."""
    strings = [e for s in project.sheets for e in s.elements if e.symbol_id == "fve.pv_string"]
    invs = [e for s in project.sheets for e in s.elements if e.symbol_id in ("fve.inverter", "fve.inverter_hybrid")]
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


def export_tz_docx(project: Project, lib: LibraryStore, path: Path | str, template: Path | str | None = None) -> None:
    project = without_dangling(project)   # vodiče na neexistující prvek (poškozený soubor) se do zprávy nedostanou
    doc = Document(str(template)) if template else Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10)
    m = project.meta
    setup_document(doc, f"Technická zpráva – {project.name}", doc_author(project),
                   " ".join(x for x in (m.get("order", ""), m.get("place", "")) if x))
    doc.add_heading(f"Technická zpráva – {project.name}", 0)
    for items in ((("Investor", m.get("investor", "")), ("Místo", m.get("place", "")), ("Zakázka", m.get("order", ""))),
                  (("Zpracoval", m.get("author", "")), ("Datum", m.get("date", "")), ("Revize", m.get("revision", "")))):
        line = "    ".join(f"{k}: {v}" for k, v in items if str(v or "").strip())   # prázdné údaje vynechat
        if line:
            doc.add_paragraph(line)

    doc.add_heading("1. Základní údaje stavby", 1)
    _table(doc, ["Údaj", "Hodnota"], [list(r) for r in dso_data(project, lib)])
    doc.add_paragraph("")

    doc.add_heading("2. Fotovoltaické pole", 1)
    strings = [(s, e) for s in project.sheets for e in s.elements if e.symbol_id == "fve.pv_string"]
    _table(doc, ["String", "Typ modulu", "Modulů", "Optimizéry", "P [kWp]", "Uoc mod. [V]", "Isc mod. [A]", "List"],
           [[e.ref, e.attrs.get("type", ""), e.attrs.get("n_modules", ""),
             f"{e.attrs['n_optimizers']}× {e.attrs.get('optimizer', '')}".strip() if e.attrs.get("n_optimizers") else "–",
             e.attrs.get("p_string", ""), e.attrs.get("voc", ""), e.attrs.get("isc", ""), s.name] for s, e in strings])
    doc.add_paragraph("")
    doc.add_heading("2.1 Kontrola stringů proti střídači", 2)
    t_min, t_max = calc.design_temperatures(project)
    sc = calc.check_strings(project, t_min, t_max)
    classic = [x for x in sc if x.mode != "fixed_voltage"]
    fixed = [x for x in sc if x.mode == "fixed_voltage"]
    if classic or not fixed:
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

    doc.add_heading("3. Střídače a akumulace", 1)
    invs = [(s, e) for s in project.sheets for e in s.elements if e.symbol_id in ("fve.inverter", "fve.inverter_hybrid", "fve.battery")]
    _table(doc, ["Označení", "Typ", "P AC [kW] / E [kWh]", "MPPT", "Fáze", "U DC max [V]", "List"],
           [[e.ref, e.attrs.get("type", ""), e.attrs.get("p_ac") or e.attrs.get("e_kwh", ""), e.attrs.get("mppt", ""),
             e.attrs.get("phases", ""), e.attrs.get("u_dc_max", ""), s.name] for s, e in invs])
    doc.add_paragraph("")

    doc.add_heading("4. Rozvaděče", 1)
    from envocad.model.thermal import layout_inputs, temperature_rise
    for s in project.switchboards():
        doc.add_heading(s.name, 2)
        from envocad.model.project import switchboard_header
        _table(doc, ["Parametr", "Hodnota"], [[k, v] for k, v in switchboard_header(project, s) if v])
        try:
            rdf, t_amb = layout_inputs(s.layout)
            r = temperature_rise(s, rdf=rdf, t_ambient_c=t_amb, project=project, lib=lib)
            doc.add_paragraph(f"Odhad oteplení dle IEC TR 60890: ΣPv = {r.p_total_w:.0f} W, Ae = {r.ae_m2:.2f} m², "
                              f"Δt uprostřed {r.dt_mid_k:.1f} K, v horní části {r.dt_top_k:.1f} K – {r.verdict()}.")
        except Exception:  # noqa: BLE001, S110
            pass
        head, rows = reports.device_list(project, lib, s)
        _table(doc, head[:6], [r[:6] for r in rows])
        doc.add_paragraph("")

    doc.add_heading("5. Kabely a jištění", 1)
    cc = calc.check_cables(project)
    _table(doc, ["Kabel", "I [A]", "S [mm²]", "L [m]", "Uložení", "Iz [A]", "Jistič In [A]", "ΔU [%]", "Výsledek"],
           [[c.ref, c.i_a or "", c.cross or "", c.length or "", c.method, c.iz or "", f"{c.breaker_ref} {c.in_breaker:g}" if c.in_breaker else "",
             c.du_pct if c.du_pct is not None else "", "vyhovuje" if not c.issues else "; ".join(c.issues)] for c in cc])
    doc.add_paragraph("Zatížitelnost Iz dle ČSN 33 2000-5-52 (Cu, PVC, 30 °C) – tabulkové hodnoty orientační; "
                      "úbytek napětí činný, mez 3 % od rozvaděče k výrobně.")
    sel = calc.check_selectivity(project)
    if sel:
        _table(doc, ["Jistič", "Nadřazený", "In [A]", "In nadř. [A]", "Selektivita"],
               [[lo, hi, il, ih, msg] for lo, hi, il, ih, msg in sel])
    doc.add_paragraph("")

    doc.add_heading("6. Ochrana před přepětím a uzemnění", 1)
    spds = [(s, e) for s in project.sheets for e in s.elements if e.symbol_id == "fve.spd"]
    _table(doc, ["Označení", "Typ SPD", "Uc [V]", "Póly", "Typ", "List"],
           [[e.ref, e.attrs.get("spd_type", ""), e.attrs.get("uc", ""), e.attrs.get("poles", ""), e.attrs.get("type", ""), s.name]
            for s, e in spds])
    doc.add_paragraph("Doplnit: způsob uzemnění konstrukce FV pole, pospojování, ochrana před bleskem (LPS) dle ČSN EN 62305.")

    doc.add_heading("7. Ochrana před úrazem elektrickým proudem, síťová ochrana", 1)
    doc.add_paragraph("Doplnit: síť TN-C-S / TN-S, automatické odpojení od zdroje, proudové chrániče, nastavení síťové ochrany "
                      "(NS ochrana) dle PPDS přílohy 4 / EN 50549-1: U>, U<, f>, f<, ROCOF, LVRT, omezení výkonu.")

    set_landscape(doc, True)     # výkazy mají hodně sloupců – na šířku
    doc.add_heading("8. Výkazy", 1)
    for name, fn in (("Výkaz materiálu", reports.bom), ("Kabely", reports.cables)):
        doc.add_heading(name, 2)
        head, rows = fn(project, lib, None)
        _table(doc, head, rows)
        doc.add_paragraph("")
    doc.save(str(path))
