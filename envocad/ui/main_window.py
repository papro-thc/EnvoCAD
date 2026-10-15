"""Hlavní okno EnvoCAD."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QToolBar,
)

from envocad import __version__
from envocad.library.store import LibraryStore
from envocad.model.project import Project
from envocad.ui import theme
from envocad.ui.canvas import Mode, SchematicScene, SchematicView
from envocad.ui.panels import LibraryPanel, PropertiesPanel

FILE_FILTER = "Projekt EnvoCAD (*.ecp)"


class MainWindow(QMainWindow):
    def __init__(self, library: LibraryStore | None = None, project: Project | None = None):
        super().__init__()
        self.library = library or LibraryStore()
        self.undo = QUndoStack(self)
        self.project = project or Project()
        self.undo.indexChanged.connect(self._on_undo_changed)
        self.undo.cleanChanged.connect(self._on_undo_changed)
        self.scene: SchematicScene | None = None
        self.view: SchematicView | None = None
        self._panels_wired = False

        self.lib_panel = LibraryPanel(self.library)
        self.props_panel = PropertiesPanel()
        self._dock("Knihovna", self.lib_panel, Qt.LeftDockWidgetArea)
        self._dock("Vlastnosti", self.props_panel, Qt.RightDockWidgetArea)
        self.setStatusBar(QStatusBar())
        self._build_actions()
        self._load_project(self.project)
        self.resize(1400, 900)

    # ---- sestavení UI --------------------------------------------------------
    def _dock(self, title: str, w, area) -> None:
        d = QDockWidget(title, self)
        d.setWidget(w)
        d.setObjectName(title)
        self.addDockWidget(area, d)

    def _build_actions(self) -> None:
        mb = self.menuBar()
        tb = QToolBar("Hlavní")
        tb.setObjectName("main_toolbar")
        self.addToolBar(tb)

        def act(menu, text, slot, shortcut=None, toolbar=False):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.triggered.connect(slot)
            menu.addAction(a)
            if toolbar:
                tb.addAction(a)
            return a

        m_file = mb.addMenu("&Soubor")
        act(m_file, "&Nový", self.new_project, "Ctrl+N", True)
        act(m_file, "&Otevřít…", self.open_project, "Ctrl+O", True)
        act(m_file, "&Uložit", self.save_project, "Ctrl+S", True)
        act(m_file, "Uložit &jako…", self.save_project_as, "Ctrl+Shift+S")
        m_file.addSeparator()
        act(m_file, "Export &DXF…", self.export_dxf)
        act(m_file, "Export &PDF…", self.export_pdf)
        m_file.addSeparator()
        act(m_file, "Vlastnosti projektu…", self.edit_project_meta)
        m_file.addSeparator()
        act(m_file, "Konec", self.close, "Ctrl+Q")

        m_edit = mb.addMenu("&Úpravy")
        u = self.undo.createUndoAction(self, "Zpět")
        u.setShortcut(QKeySequence.Undo)
        r = self.undo.createRedoAction(self, "Znovu")
        r.setShortcuts([QKeySequence.Redo, QKeySequence("Ctrl+Y")])
        m_edit.addAction(u)
        m_edit.addAction(r)
        tb.addSeparator()
        tb.addAction(u)
        tb.addAction(r)
        m_edit.addSeparator()
        act(m_edit, "Smazat", lambda: self.scene and self.scene.delete_selected(), "Delete")
        act(m_edit, "Otočit o 90°", lambda: self.scene and self.scene.rotate_selected(), "R")

        m_draw = mb.addMenu("&Kreslit")
        tb.addSeparator()
        act(m_draw, "Vodič (W)", lambda: self.scene and self.scene.start_wire(), None, True)
        act(m_draw, "Výběr (Esc)", lambda: self.scene and self.scene.set_mode(Mode.SELECT), None, True)

        m_view = mb.addMenu("&Zobrazit")
        act(m_view, "Přizpůsobit list", lambda: self.view and self.view.zoom_fit(), "Home", True)
        self.act_dark = QAction("Tmavý režim", self, checkable=True)
        self.act_dark.setShortcut(QKeySequence("Ctrl+D"))
        self.act_dark.setChecked(theme.is_dark())
        self.act_dark.toggled.connect(self.set_dark)
        m_view.addAction(self.act_dark)

        m_lib = mb.addMenu("&Knihovna")
        act(m_lib, "Importovat symbol z DXF…", self.import_dxf_symbol)

        m_help = mb.addMenu("&Nápověda")
        act(m_help, "O programu", lambda: QMessageBox.about(
            self, "EnvoCAD", f"EnvoCAD {__version__}\nInterní nástroj ENVO pro elektro-dokumentaci FVE."))

    # ---- projekt ---------------------------------------------------------------
    def _load_project(self, project: Project) -> None:
        self.project = project
        self.undo.clear()
        sheet = project.sheets[0]
        self.scene = SchematicScene(project, sheet, self.library, self.undo)
        self.view = SchematicView(self.scene)
        self.setCentralWidget(self.view)
        self.scene.selection_info.connect(self.props_panel.show_item)
        self.scene.attrs_changed.connect(lambda _id: self.props_panel.show_item(self._selected_item()))
        self.scene.mode_changed.connect(self._show_mode)
        if not self._panels_wired:
            self.lib_panel.symbol_chosen.connect(lambda sid: self.scene and self.scene.start_place(sid))
            self.props_panel.attr_edited.connect(lambda *a: self.scene and self.scene.set_attr(*a))
            self._panels_wired = True
        self.props_panel.show_item(None)
        self._update_title()
        self.view.zoom_fit()

    def set_dark(self, dark: bool) -> None:
        theme.apply(dark)
        if self.scene:
            self.scene.retheme()

    def _selected_item(self):
        sel = self.scene.selectedItems() if self.scene else []
        return sel[0] if len(sel) == 1 else None

    def _show_mode(self, mode: Mode) -> None:
        txt = {Mode.SELECT: "Výběr", Mode.PLACE: "Vkládání symbolu – klik umístí, Esc/pravé tl. ukončí",
               Mode.WIRE: "Vodič – klikněte na port, pak na druhý port"}[mode]
        self.statusBar().showMessage(txt)

    def _on_undo_changed(self, _value=None) -> None:
        self._update_title()

    def _update_title(self) -> None:
        name = self.project.path.name if self.project.path else "nepojmenovaný"
        dirty = "*" if not self.undo.isClean() else ""
        self.setWindowTitle(f"{name}{dirty} – EnvoCAD")

    def _confirm_discard(self) -> bool:
        if self.undo.isClean():
            return True
        r = QMessageBox.question(self, "Neuložené změny", "Projekt má neuložené změny. Uložit?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save_project()
        return r == QMessageBox.Discard

    def new_project(self) -> None:
        if self._confirm_discard():
            self._load_project(Project())

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Otevřít projekt", "", FILE_FILTER)
        if path:
            try:
                self._load_project(Project.load(path))
            except Exception as ex:  # noqa: BLE001
                QMessageBox.critical(self, "Chyba", f"Projekt nelze otevřít:\n{ex}")

    def save_project(self) -> bool:
        if self.project.path is None:
            return self.save_project_as()
        self.project.save()
        self.undo.setClean()
        self._update_title()
        self.statusBar().showMessage(f"Uloženo: {self.project.path}", 3000)
        return True

    def save_project_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Uložit projekt", "", FILE_FILTER)
        if not path:
            return False
        if not path.endswith(".ecp"):
            path += ".ecp"
        self.project.path = Path(path)
        return self.save_project()

    def edit_project_meta(self) -> None:
        for key, label in [("name", "Název projektu"), ("investor", "Investor"), ("order", "Číslo zakázky"),
                           ("place", "Místo"), ("author", "Zpracoval")]:
            cur = self.project.name if key == "name" else self.project.meta.get(key, "")
            val, ok = QInputDialog.getText(self, "Vlastnosti projektu", label, text=cur)
            if not ok:
                return
            if key == "name":
                self.project.name = val
            else:
                self.project.meta[key] = val

    # ---- export / import -------------------------------------------------------
    def export_dxf(self) -> None:
        from envocad.export.dxf_export import export_sheet_dxf
        path, _ = QFileDialog.getSaveFileName(self, "Export DXF", "", "DXF (*.dxf)")
        if path:
            export_sheet_dxf(self.project, self.scene.sheet, self.library, path)
            self.statusBar().showMessage(f"Exportováno: {path}", 3000)

    def export_pdf(self) -> None:
        from envocad.export.pdf_export import export_scene_pdf
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", "", "PDF (*.pdf)")
        if path:
            export_scene_pdf(self.scene, path)
            self.statusBar().showMessage(f"Exportováno: {path}", 3000)

    def import_dxf_symbol(self) -> None:
        from envocad.library.dxf_import import import_dxf, list_blocks
        path, _ = QFileDialog.getOpenFileName(self, "Import symbolu z DXF", "", "DXF (*.dxf)")
        if not path:
            return
        blocks = ["(modelspace)"] + list_blocks(path)
        blk, ok = QInputDialog.getItem(self, "Import DXF", "Zdroj geometrie:", blocks, 0, False)
        if not ok:
            return
        sid, ok = QInputDialog.getText(self, "Import DXF", "ID symbolu (např. fve.vyrobce.typ):")
        if not ok or not sid:
            return
        name, ok = QInputDialog.getText(self, "Import DXF", "Název symbolu:", text=Path(path).stem)
        if not ok:
            return
        scale, ok = QInputDialog.getDouble(self, "Import DXF", "Měřítko (DXF jednotka → mm):", 1.0, 0.0001, 10000, 4)
        if not ok:
            return
        sym = import_dxf(path, sid, name, None if blk == "(modelspace)" else blk, scale, True, True)
        self.library.put_symbol(sym)
        self.lib_panel.refresh()
        QMessageBox.information(self, "Import DXF", f"Symbol {sid} importován ({len(sym.primitives)} primitiv).\n"
                                "Porty zatím doplňte v JSON (viz docs/LIBRARY_FORMAT.md).")

    def closeEvent(self, ev) -> None:
        if self._confirm_discard():
            ev.accept()
        else:
            ev.ignore()
