"""Protokol o kusovém ověření rozvaděče (ČSN EN 61439-1, čl. 11) do .docx.

Generuje se z modelu: hlavička zakázky, parametry rozvaděče, seznam přístrojů a kontrolní tabulka
kusového ověření s místem pro naměřené hodnoty a podpisy. Jakmile dodá ENVO vlastní šablonu (.docx),
stačí ji předat parametrem `template` – nadpisy, loga a styly se převezmou z ní.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

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


def _table(doc, head: list[str], rows: list[list], style: str = "Table Grid") -> None:
    t = doc.add_table(rows=1, cols=len(head))
    t.style = style
    for i, h in enumerate(head):
        _set_cell(t.rows[0].cells[i], h, bold=True)
    for r in rows:
        cells = t.add_row().cells
        for i, v in enumerate(r):
            _set_cell(cells[i], "" if v is None else v)


def export_routine_test_docx(project: Project, lib: LibraryStore, sheet: Sheet, path: Path | str,
                             template: Path | str | None = None) -> None:
    doc = Document(str(template)) if template else Document()
    m = project.meta
    lay = sheet.layout
    devs = reports.devices(project, lib, sheet)
    mains = [e for e in devs if e.symbol_id in ("sb.main_switch", "fve.breaker_mccb")]
    i_n = mains[0].attrs.get("in_", "") if mains else ""

    h = doc.add_heading("Protokol o kusovém ověření rozvaděče", level=1)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph("dle ČSN EN 61439-1 ed. 3, čl. 11 (kusové ověření)").alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_heading("1. Identifikace", level=2)
    _table(doc, ["Položka", "Hodnota"], [
        ["Zakázka", f"{project.name}" + (f" (č. {m['order']})" if m.get("order") else "")],
        ["Investor", m.get("investor", "")],
        ["Místo", m.get("place", "")],
        ["Rozvaděč", sheet.name],
        ["Typ skříně", " ".join(x for x in (lay.params.get("manufacturer", ""), lay.params.get("type", "") or lay.enclosure) if x)],
        ["Rozměry (š × v × h)", f"{lay.width_mm:g} × {lay.height_mm:g} × {lay.depth_mm:g} mm" if lay.depth_mm else f"{lay.width_mm:g} × {lay.height_mm:g} mm"],
        ["Rozložení", f"{lay.rows} řad × {lay.modules_per_row} modulů ({lay.total_modules} M), obsazeno {lay.used_modules(sheet):g} M"],
        ["Montáž / materiál / dveře", " / ".join(lay.params.get(k, "") for k in ("mounting", "material", "door"))],
        ["Jmenovitý proud In", (lay.params.get("in_") or i_n) + " A" if (lay.params.get("in_") or i_n) else ""],
        ["Jmenovité napětí Un", lay.params.get("un", "3×400/230 V, 50 Hz")],
        ["Zkratová odolnost", lay.params.get("icw", "")],
        ["Síť / uzemnění", lay.params.get("network", "TN-S")],
        ["Krytí / IK", " / ".join(x for x in (lay.params.get("ip", ""), lay.params.get("ik", "")) if x)],
        ["Výrobce rozvaděče", "ENVO s.r.o."],
        ["Datum", date.today().strftime("%d.%m.%Y")],
    ])

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
