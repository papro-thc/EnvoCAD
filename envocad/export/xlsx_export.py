"""Výkazy do .xlsx (openpyxl). Jeden sešit, list na každý výkaz."""
from __future__ import annotations

import math
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from envocad.export import reports
from envocad.library.store import LibraryStore
from envocad.model.project import Project, Sheet

HEAD_FILL = PatternFill("solid", fgColor="DDE6F0")
THIN = Side(style="thin", color="999999")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


# sloupce, jejichž číselné hodnoty se zapisují jako čísla (Excel s nimi počítá a řadí je číselně)
NUMERIC_COLUMNS = {"Průřez [mm²]", "Délka [m]", "Č.", "Svorka", "Ks", "Spojů"}
# sloupce označení (číslo svorky / žíly): číslem jen čistě celé číslo bez úvodní nuly – „1.10“, „01“, „3,1“ = text
INTEGER_COLUMNS = {"Č.", "Svorka"}
_PLAIN_INT = re.compile(r"(0|[1-9][0-9]*)")


def _number(v):
    """Text čísla („6“, „1,5“, „2.5“) → int/float; jiné hodnoty (i „1/2“, „PE“, „“) beze změny."""
    if not isinstance(v, str):
        return v
    t = v.strip().replace(",", ".")
    if not t or t[0] in "+" or t.startswith("0") and len(t) > 1 and t[1] != ".":
        return v               # „+RDC1…“ a čísla s nulou na začátku („01“) zůstanou textem
    try:
        f = float(t)
    except ValueError:
        return v
    if not math.isfinite(f):
        return v
    return int(f) if f.is_integer() and "." not in t and "e" not in t.lower() else f


def _integer(v):
    """Text čistě celého čísla („3“, „12“) → int; jiné hodnoty („1.10“, „01“, „1,5“, „PE“) beze změny."""
    if isinstance(v, str) and _PLAIN_INT.fullmatch(v.strip()):
        return int(v.strip())
    return v


def _set_text_safe(cell) -> None:
    """Řetězec začínající „=“ (strukturní označení =AC+RDC1-F1) uložit jako text, ne jako vzorec."""
    if isinstance(cell.value, str) and cell.value.startswith("="):
        cell.data_type = "s"


def _write_table(ws, title: str, subtitle: str, head: list[str], rows: list[list], extra: list[str] = ()) -> None:
    """Nadpis, podnadpis (+ doplňkové řádky podnadpisu `extra`, např. parametry výpočtu), prázdný řádek, tabulka."""
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([subtitle])
    _set_text_safe(ws.cell(row=ws.max_row, column=1))
    for line in extra:
        ws.append([line])
        ws.cell(row=ws.max_row, column=1).font = Font(italic=True, size=9)
        _set_text_safe(ws.cell(row=ws.max_row, column=1))
    ws.append([])
    ws.append(head)
    hr = ws.max_row
    for c in range(1, len(head) + 1):
        cell = ws.cell(row=hr, column=c)
        cell.font = Font(bold=True)
        cell.fill = HEAD_FILL
        cell.border = BORDER
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    conv = [_integer if h in INTEGER_COLUMNS else (_number if h in NUMERIC_COLUMNS else None) for h in head]
    for r in rows:
        ws.append([conv[c](v) if c < len(conv) and conv[c] else v for c, v in enumerate(r)])
        for c in range(1, max(len(head), len(r)) + 1):
            cell = ws.cell(row=ws.max_row, column=c)
            _set_text_safe(cell)
            if c <= len(head):
                cell.border = BORDER
    for c, h in enumerate(head, start=1):
        width = max([len(str(h))] + [len(str(r[c - 1])) for r in rows if c - 1 < len(r)] + [6])
        ws.column_dimensions[get_column_letter(c)].width = min(width + 2, 50)
    ws.freeze_panes = ws.cell(row=hr + 1, column=1)


def _subtitle(project: Project, sheet: Sheet | None) -> str:
    scope = sheet.name if sheet else "celý projekt"
    return f"{project.name} – {scope}" + (f" – zak. {project.meta['order']}" if project.meta.get("order") else "")


def export_reports_xlsx(project: Project, lib: LibraryStore, path: Path | str, sheet: Sheet | None = None) -> None:
    from envocad.model.project import clean_view
    project, sheet = clean_view(project, sheet)     # vodiče na neexistující prvek se do výkazů nedostanou
    wb = Workbook()
    wb.remove(wb.active)
    sub = _subtitle(project, sheet)
    for name, fn in reports.ALL_REPORTS:
        head, rows = fn(project, lib, sheet)
        ws = wb.create_sheet(name[:31])
        extra = reports.REPORT_SUBTITLES.get(name)
        _write_table(ws, name, sub, head, rows, extra(project, sheet) if extra else [])
    wb.save(str(path))


def export_production_xlsx(project: Project, lib: LibraryStore, path: Path | str, sheet: Sheet | None = None,
                           base: dict | None = None) -> None:
    """Výrobní podklad pro dílnu: list „Výrobní seznam“ (výrobní zapojovací seznam; průřez a délka jako čísla)
    a list „Parametry“ (použité parametry po rozvaděčích se zdrojem hodnoty, pravidlo svorek, tabulky)."""
    from envocad.model.project import clean_view
    from envocad.model.wiring import FERRULE_DIN46228, IN_TO_CROSS, NUMBER_NOTE, TERMINAL_RULE, param_sources
    project, sheet = clean_view(project, sheet)
    base = reports.wiring_base() if base is None else base
    wb = Workbook()
    ws = wb.active
    ws.title = "Výrobní seznam"
    head, rows = reports.production_wiring_list(project, lib, sheet, base)
    _write_table(ws, "Výrobní zapojovací seznam", _subtitle(project, sheet), head, rows,
                 reports.production_subtitle(project, sheet, base))
    head, rows = reports.marking(project, lib, sheet)
    rows = [r for r in rows if r[0] == "Návlečka"]          # výroba rozvaděče: jen návlečky (štítky kabelů jsou JPS)
    if rows:
        _write_table(wb.create_sheet("Návlečky"), "Návlečky (ČSN EN 62491)", _subtitle(project, sheet), head, rows)
    wp = wb.create_sheet("Parametry")
    sheets = [s for s in ([sheet] if sheet else project.sheets) if s.is_switchboard]
    prow = [[s.name, key, label, value, src] for s in sheets for key, label, value, src in param_sources(s.layout, base)]
    _write_table(wp, "Parametry výrobního seznamu", TERMINAL_RULE, ["Rozvaděč", "Klíč", "Parametr", "Hodnota", "Zdroj"],
                 prow, [NUMBER_NOTE])
    wp.append([])
    wp.append(["Průřez podle In jištění (orientační, ČSN EN 61439-1 příl. H – schválí projektant)"])
    wp.cell(row=wp.max_row, column=1).font = Font(bold=True)
    wp.append(["In do [A]", "Průřez [mm²]"])
    for lim, cross in IN_TO_CROSS:
        wp.append([lim, cross])
    wp.append([])
    wp.append(["Dutinky DIN 46228"])
    wp.cell(row=wp.max_row, column=1).font = Font(bold=True)
    wp.append(["Průřez [mm²]", "Barva", "Délka [mm]"])
    for cross, (color, length) in FERRULE_DIN46228.items():
        wp.append([cross, color, length])
    wb.save(str(path))
