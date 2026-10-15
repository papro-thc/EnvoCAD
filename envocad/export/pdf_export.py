"""Export scény do PDF přes QPdfWriter (vektorově)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter

from envocad.ui import theme

PAPERS = {"A4": (297.0, 210.0), "A3": (420.0, 297.0)}


def export_scene_pdf(scene, path: Path | str, paper: str | None = None) -> None:
    """PDF listu; `paper` = "A4"/"A3" vytiskne list zmenšený/zvětšený na daný formát (jinak skutečný rozměr)."""
    sheet = scene.sheet
    pw, ph = getattr(scene, "paper_size", (sheet.width, sheet.height))  # vícepól má roztažený list
    out_w, out_h = PAPERS.get(paper or "", (pw, ph))
    if paper and pw < ph:  # na výšku
        out_w, out_h = out_h, out_w
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QSizeF(out_w, out_h), QPageSize.Millimeter))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))
    # rozměr strany už orientaci nese (420×297 = na šířku); Landscape by ji otočil podruhé → strana na výšku
    writer.setPageLayout(QPageLayout(QPageSize(QSizeF(out_w, out_h), QPageSize.Millimeter), QPageLayout.Portrait,
                                     QMarginsF(0, 0, 0, 0)))
    writer.setResolution(300)
    writer.setTitle(scene.project.name)
    writer.setCreator("EnvoCAD")
    painter = QPainter(writer)
    painter.setRenderHint(QPainter.Antialiasing)
    scene.clearSelection()
    scene.draw_grid = False
    prev_dark = theme.is_dark()
    theme._current = theme.PRINT
    pages = getattr(scene, "pages", None) or [QRectF(0, -ph, pw, ph)]   # vícepól může mít víc stran
    for i, src in enumerate(pages):
        if i:
            writer.newPage()
        scene.render(painter, QRectF(0, 0, writer.width(), writer.height()), src, Qt.KeepAspectRatio)
    painter.end()
    theme._current = theme.DARK if prev_dark else theme.LIGHT
    scene.draw_grid = True
    scene.update()
