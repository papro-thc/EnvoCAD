"""Protokol o kusovém ověření rozvaděče (ČSN EN 61439-1, čl. 11) do .docx.

Generuje se z modelu: hlavička zakázky, parametry rozvaděče, seznam přístrojů a kontrolní tabulka
kusového ověření s místem pro naměřené hodnoty a podpisy. Jakmile dodá ENVO vlastní šablonu (.docx),
stačí ji předat parametrem `template` – nadpisy, loga a styly se převezmou z ní.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm, Pt

from envocad.export import reports
from envocad.library.store import LibraryStore
from envocad.model.project import Project, Sheet

# Položky kusového ověření dle ČSN EN 61439-1, tab. (čl. 11.2–11.10)
ROUTINE_CHECKS = [
    ("11.2", "Stupeň ochrany krytem (IP)", "vizuální kontrola, shoda s dokumentací"),
    ("11.3", "Vzdušné vzdálenosti a povrchové cesty", "vizuální kontrola / měření"),
    ("11.4", "Ochrana před úrazem el. proudem a celistvost ochranných obvodů", "měření spojitosti PE ≤ 0,1 Ω"),
    ("11.5", "Vestavění přístrojů", "shoda s výkresem, upevnění"),
    ("11.6", "Vnitřní elektrické obvody a spoje", "kontrola zapojení, utahovací momenty"),
    ("11.7", "Svorky pro vnější vodiče", "počet, označení, průřezy"),
    ("11.8", "Mechanická funkce", "funkce ovládacích a blokovacích prvků"),
    ("11.9", "Dielektrické vlastnosti", "izolační odpor ≥ 1 000 Ω/V (min. 1 MΩ) nebo zkouška 2 U + 1 000 V"),
    ("11.10", "Zapojení, provozní funkce", "funkční zkouška, ověření nastavení ochran"),
]


def _set_cell(cell, text: str, bold: bool = False, size: int = 9) -> None:
    cell.text = ""
    run = cell.paragraphs[0].add_run(str(text))
    run.bold = bold
    run.font.size = Pt(size)


LANG = "cs-CZ"
PAGE_A4 = (210.0, 297.0)   # mm
MARGIN_MM = 20.0


def _usable_width_mm(doc) -> float:
    sec = doc.sections[-1]
    return (sec.page_width - sec.left_margin - sec.right_margin) / 36000.0   # EMU → mm


def setup_document(doc, title: str, author: str = "", subject: str = "") -> None:
    """Společné nastavení dokumentu: A4 na výšku s okraji 20 mm, jazyk čeština (kontrola pravopisu, dělení slov)
    a vlastnosti dokumentu (název, autor, datum, jazyk). Šablona ENVO (`template`) si okraje nese sama – rozměr
    strany se přepíše jen u výchozí šablony python-docx (Letter)."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    for sec in doc.sections:
        if abs(sec.page_width.mm - 215.9) < 1 or abs(sec.page_height.mm - 279.4) < 1:   # Letter → A4
            sec.page_width, sec.page_height = Mm(PAGE_A4[0]), Mm(PAGE_A4[1])
            sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Mm(MARGIN_MM)
    styles = doc.styles.element
    defaults = styles.find(qn("w:docDefaults"))
    if defaults is None:
        defaults = OxmlElement("w:docDefaults")
        styles.insert(0, defaults)
    rpr_default = defaults.find(qn("w:rPrDefault"))
    if rpr_default is None:
        rpr_default = OxmlElement("w:rPrDefault")
        defaults.insert(0, rpr_default)
    rpr = rpr_default.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        rpr_default.append(rpr)
    for style_rpr in [rpr] + [st.element.get_or_add_rPr() for st in doc.styles if st.type == 1]:   # odstavcové styly
        lang = style_rpr.find(qn("w:lang"))
        if lang is None:
            lang = OxmlElement("w:lang")
            style_rpr.append(lang)
        lang.set(qn("w:val"), LANG)
        lang.set(qn("w:eastAsia"), LANG)
    cp = doc.core_properties
    cp.title = title
    cp.subject = subject
    cp.author = author or cp.author
    cp.last_modified_by = author or cp.last_modified_by
    cp.language = LANG
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)    # core.xml ukládá čas v UTC
    cp.created = now
    cp.modified = now
    cp.comments = "Vygenerováno programem EnvoCAD"


def doc_author(project: Project) -> str:
    """Autor dokumentu: „Zpracoval“ projektu, jinak `standard.author` z firemního standardu."""
    author = str(project.meta.get("author") or "").strip()
    if author:
        return author
    try:
        from envocad.settings import load_settings
        return str(load_settings()["standard"].get("author") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def set_landscape(doc, landscape: bool) -> None:
    """Nová sekce na šířku / na výšku (široké tabulky). Na začátku prázdného dokumentu přepne první sekci."""
    from docx.enum.section import WD_ORIENT, WD_SECTION
    sec = doc.sections[-1]
    if (sec.orientation == WD_ORIENT.LANDSCAPE) == landscape:
        return
    w, h = sec.page_width, sec.page_height
    new = doc.add_section(WD_SECTION.NEW_PAGE)
    new.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
    new.page_width, new.page_height = h, w


def _col_widths_mm(head: list[str], rows: list[list], avail: float) -> list[float]:
    """Šířky sloupců podle délky textu (nejdelší slovo jako minimum), součet = šířka strany."""
    n = len(head)
    nat, mn = [0.0] * n, [0.0] * n
    for i in range(n):
        for t in [str(head[i])] + [str(r[i]) for r in rows[:300] if i < len(r) and r[i] is not None]:
            nat[i] = max(nat[i], len(t))
            mn[i] = max(mn[i], max((len(w) for w in t.split()), default=0))
    char = 1.9   # mm na znak při 9 pt
    nat = [max(10.0, c * char + 2.5) for c in nat]
    mn = [min(nat[i], max(10.0, min(mn[i], 18) * char + 2.5)) for i in range(n)]
    if sum(nat) <= avail:
        return [w * avail / sum(nat) for w in nat]
    if sum(mn) >= avail:
        return [w * avail / sum(mn) for w in mn]
    k = (avail - sum(mn)) / (sum(nat) - sum(mn))
    return [mn[i] + k * (nat[i] - mn[i]) for i in range(n)]


def _table(doc, head: list[str], rows: list[list], style: str = "Table Grid") -> None:
    """Tabulka s hlavičkou; šířky sloupců podle obsahu v šířce strany (aktuální sekce), text se v buňce zalomí.
    Širokou tabulku (víc než 8 sloupců) písmo 8 pt."""
    t = doc.add_table(rows=1, cols=len(head))
    t.style = style
    t.autofit = False
    size = 8 if len(head) > 8 else 9
    widths = _col_widths_mm(head, rows, _usable_width_mm(doc))
    for i, h in enumerate(head):
        _set_cell(t.rows[0].cells[i], h, bold=True, size=size)
    for r in rows:
        cells = t.add_row().cells
        for i, v in enumerate(r):
            _set_cell(cells[i], "" if v is None else v, size=size)
    for i, w in enumerate(widths):
        t.columns[i].width = Mm(w)
        for cell in t.columns[i].cells:
            cell.width = Mm(w)


def _with_unit(value, unit: str) -> str:
    """„125“ → „125 A“; hodnota, která jednotku už má („125 A“, „125A“), zůstane; prázdná → „“."""
    v = str(value or "").strip()
    if not v:
        return ""
    return v if v.replace(" ", "").lower().endswith(unit.replace(" ", "").lower()) else f"{v} {unit}"


def _count(n, one: str, few: str, many: str) -> str:
    """„1 řada, 3 řady, 5 řad“ – počet se správným tvarem slova."""
    from envocad.model.notes import plural
    try:
        k = float(n)
    except (TypeError, ValueError):
        return f"{n} {many}"
    return f"{k:g} {plural(int(k), one, few, many) if k.is_integer() else few}"


def _thermal_text(project: Project, lib: LibraryStore, sheet: Sheet) -> str:
    """Řádek protokolu: teplota v horní části skříně a hodnocení po přístrojích (`ThermalResult.verdict`)."""
    from envocad.model.thermal import layout_inputs, temperature_rise
    try:
        rdf, t_amb = layout_inputs(sheet.layout)
        r = temperature_rise(sheet, rdf=rdf, t_ambient_c=t_amb, project=project, lib=lib)
    except Exception:  # noqa: BLE001 – protokol se vygeneruje i bez výpočtu
        return ""
    src = r.loss_summary()     # zdroj ztrát přístrojů: artikl / ruční / odhad
    return (f"ΣPv {r.p_total_w:.0f} W" + (f" ({src})" if src else "") + f", okolí {r.t_ambient_c:.0f} °C, "
            f"horní část ≈ {r.t_top_c:.0f} °C – {r.verdict()}")


def export_routine_test_docx(project: Project, lib: LibraryStore, sheet: Sheet, path: Path | str,
                             template: Path | str | None = None) -> None:
    doc = Document(str(template)) if template else Document()
    m = project.meta
    lay = sheet.layout
    devs = reports.devices(project, lib, sheet)
    mains = [e for e in devs if e.symbol_id in ("sb.main_switch", "fve.breaker_mccb")]
    i_n = mains[0].attrs.get("in_", "") if mains else ""
    from envocad.model.frame import company_names
    company = company_names()[1]
    setup_document(doc, f"Protokol o kusovém ověření rozvaděče {sheet.name}", doc_author(project),
                   f"{project.name}" + (f" (č. {m['order']})" if m.get("order") else ""))

    h = doc.add_heading("Protokol o kusovém ověření rozvaděče", level=1)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph("dle ČSN EN 61439-1 ed. 3, čl. 11 (kusové ověření)").alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_heading("1. Identifikace", level=2)
    if lay.depth_mm:
        dims = ("Rozměry (š × v × h)", f"{lay.width_mm:g} × {lay.height_mm:g} × {lay.depth_mm:g} mm")
    else:
        dims = ("Rozměry (š × v)", f"{lay.width_mm:g} × {lay.height_mm:g} mm")
    parts = [(lbl, str(lay.params.get(k, "") or "").strip()) for k, lbl in
             (("mounting", "montáž"), ("material", "materiál"), ("door", "dveře"))]
    parts = [(lbl, v) for lbl, v in parts if v]
    mount = (" / ".join(lbl for lbl, _ in parts).capitalize(), " / ".join(v for _, v in parts)) if parts else None
    rows = [
        ["Zakázka", f"{project.name}" + (f" (č. {m['order']})" if m.get("order") else "")],
        ["Investor", m.get("investor", "")],
        ["Místo", m.get("place", "")],
        ["Rozvaděč", sheet.name],
        ["Typ skříně", " ".join(x for x in (lay.params.get("manufacturer", ""), lay.params.get("type", "") or lay.enclosure) if x)],
        list(dims),
        ["Rozložení", (f"{_count(lay.rows, 'řada', 'řady', 'řad')} × "
                       f"{_count(lay.modules_per_row, 'modul', 'moduly', 'modulů')} "
                       f"({lay.total_modules} M), obsazeno {lay.used_modules(sheet, project, lib):g} M")],
        list(mount) if mount else None,
        ["Jmenovitý proud In", _with_unit(lay.params.get("in_") or i_n, "A")],
        ["Jmenovité napětí Un", lay.params.get("un", "3×400/230 V, 50 Hz")],
        ["Zkratová odolnost", _with_unit(lay.params.get("icw", ""), "kA")],
        ["Síť / uzemnění", lay.params.get("network", "TN-S")],
        ["Krytí / IK", " / ".join(x for x in (lay.params.get("ip", ""), lay.params.get("ik", "")) if x)],
        ["Oteplení (IEC TR 60890, výpočet)", _thermal_text(project, lib, sheet)],
        ["Výrobce rozvaděče", company],
        ["Datum", datetime.now().astimezone().strftime("%d.%m.%Y")],   # dnešní datum v místním čase
    ]
    _table(doc, ["Položka", "Hodnota"], [r for r in rows if r is not None])

    doc.add_heading("2. Osazené přístroje", level=2)
    head, rows = reports.device_list(project, lib, sheet)
    _table(doc, head[:5], [r[:5] for r in rows])

    doc.add_heading("3. Kusové ověření", level=2)
    _table(doc, ["Čl.", "Kontrola / zkouška", "Způsob", "Výsledek", "Naměřeno / poznámka"],
           [[a, b, c, "☐ vyhovuje  ☐ nevyhovuje", ""] for a, b, c in ROUTINE_CHECKS])

    doc.add_heading("4. Měření", level=2)
    _table(doc, ["Měření", "Hodnota", "Přístroj / v. č."], [
        ["Spojitost ochranného obvodu [Ω]", "", ""],
        ["Izolační odpor L–PE [MΩ]", "", ""],
        ["Izolační odpor N–PE [MΩ]", "", ""],
        ["Izolační odpor L–N [MΩ]", "", ""],
        ["Zkouška chráničů (IΔn, t) ", "", ""],
    ])

    doc.add_heading("5. Závěr", level=2)
    doc.add_paragraph("Rozvaděč ☐ vyhovuje  ☐ nevyhovuje požadavkům ČSN EN 61439-1 a je schopen bezpečného provozu.")
    doc.add_paragraph("")
    _table(doc, ["Zkoušku provedl", "Datum", "Podpis"], [["", "", ""]], style="Table Grid")
    doc.add_paragraph("")
    doc.add_paragraph(f"Vygenerováno EnvoCAD – {project.name}").runs[0].font.size = Pt(8)
    doc.save(str(path))
