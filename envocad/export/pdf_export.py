"""Export scény do PDF přes QPdfWriter (vektorově)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter

from envocad.ui import theme


def export_scene_pdf(scene, path: Path | str) -> None:
    sheet = scene.sheet
    pw, ph = getattr(scene, "paper_size", (sheet.width, sheet.height))  # vícepól má roztažený list
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QSizeF(pw, ph), QPageSize.Millimeter))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))
    writer.setPageLayout(QPageLayout(QPageSize(QSizeF(pw, ph), QPageSize.Millimeter),
                                     QPageLayout.Landscape if pw > ph else QPageLayout.Portrait,
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
    src = QRectF(0, -ph, pw, ph)
    scene.render(painter, QRectF(0, 0, writer.width(), writer.height()), src)
    painter.end()
    theme._current = theme.DARK if prev_dark else theme.LIGHT
    scene.draw_grid = True
    scene.update()
