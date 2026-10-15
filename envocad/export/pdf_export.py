"""Export scény do PDF přes QPdfWriter (vektorově)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter


def export_scene_pdf(scene, path: Path | str) -> None:
    sheet = scene.sheet
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QSizeF(sheet.width, sheet.height), QPageSize.Millimeter))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))
    writer.setPageLayout(QPageLayout(QPageSize(QSizeF(sheet.width, sheet.height), QPageSize.Millimeter),
                                     QPageLayout.Landscape if sheet.width > sheet.height else QPageLayout.Portrait,
                                     QMarginsF(0, 0, 0, 0)))
    writer.setResolution(300)
    writer.setTitle(scene.project.name)
    writer.setCreator("EnvoCAD")
    painter = QPainter(writer)
    painter.setRenderHint(QPainter.Antialiasing)
    scene.clearSelection()
    scene.draw_grid = False
    src = QRectF(0, -sheet.height, sheet.width, sheet.height)
    scene.render(painter, QRectF(0, 0, writer.width(), writer.height()), src)
    painter.end()
    scene.draw_grid = True
    scene.update()
