"""Export scény do PDF přes QPdfWriter (vektorově)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter

from envocad.ui import theme

PAPERS = {"A4": (297.0, 210.0), "A3": (420.0, 297.0)}


def _set_notes_visible(scene, visible: bool | None) -> None:
    """Skryje/obnoví připomínky ve scéně (`notes_visible` doplní GUI; scéna bez něj se nemění)."""
    if visible is None or not hasattr(scene, "notes_visible"):
        return
    if hasattr(scene, "set_notes_visible"):
        scene.set_notes_visible(visible)
    else:
        scene.notes_visible = visible


def export_scene_pdf(scene, path: Path | str, paper: str | None = None, notes: bool = False) -> int:
    """PDF listu; `paper` = "A4"/"A3" vytiskne list zmenšený/zvětšený na daný formát (jinak skutečný rozměr).
    `notes=True` doplní otevřené připomínky listu jako anotace PDF (jen jednostránkové schéma, ne vícepól).
    Do obsahu PDF se připomínky nevypalují. Vrací počet přidaných připomínek."""
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
    prev_notes = getattr(scene, "notes_visible", None)
    _set_notes_visible(scene, False)     # připomínky jsou v PDF jen jako anotace, ne v obsahu
    prev_dark = theme.is_dark()
    theme._current = theme.PRINT
    pages = getattr(scene, "pages", None) or [QRectF(0, -ph, pw, ph)]   # vícepól může mít víc stran
    for i, src in enumerate(pages):
        if i:
            writer.newPage()
        scene.render(painter, QRectF(0, 0, writer.width(), writer.height()), src, Qt.KeepAspectRatio)
    painter.end()
    theme._current = theme.DARK if prev_dark else theme.LIGHT
    _set_notes_visible(scene, prev_notes)
    scene.draw_grid = True
    scene.update()
    from envocad.ui.canvas import SchematicScene
    if not notes or not isinstance(scene, SchematicScene):   # vícepól a plán svorkovnice připomínky nemají
        return 0
    from envocad.export.pdf_annots import PageMap, add_note_annotations
    from envocad.model.notes import notes_on_sheet
    ns = notes_on_sheet(scene.project, sheet.id, ("open",))
    return add_note_annotations(path, [(0, PageMap.fit(pw, ph, out_w, out_h), ns)], scene.project.name)
