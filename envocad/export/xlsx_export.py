"""Výkazy do .xlsx (openpyxl). Jeden sešit, list na každý výkaz."""
from __future__ import annotations

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


def _write_table(ws, title: str, subtitle: str, head: list[str], rows: list[list]) -> None:
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([subtitle])
    ws.append([])
    ws.append(head)
    hr = ws.max_row
    for c in range(1, len(head) + 1):
        cell = ws.cell(row=hr, column=c)
        cell.font = Font(bold=True)
        cell.fill = HEAD_FILL
        cell.border = BORDER
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for r in rows:
        ws.append(r)
        for c in range(1, len(head) + 1):
            ws.cell(row=ws.max_row, column=c).border = BORDER
    for c, h in enumerate(head, start=1):
        width = max([len(str(h))] + [len(str(r[c - 1])) for r in rows if c - 1 < len(r)] + [6])
        ws.column_dimensions[get_column_letter(c)].width = min(width + 2, 50)
    ws.freeze_panes = ws.cell(row=hr + 1, column=1)


def export_reports_xlsx(project: Project, lib: LibraryStore, path: Path | str, sheet: Sheet | None = None) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    scope = sheet.name if sheet else "celý projekt"
    sub = f"{project.name} – {scope}" + (f" – zak. {project.meta['order']}" if project.meta.get("order") else "")
    for name, fn in reports.ALL_REPORTS:
        head, rows = fn(project, lib, sheet)
        ws = wb.create_sheet(name[:31])
        _write_table(ws, name, sub, head, rows)
    wb.save(str(path))
