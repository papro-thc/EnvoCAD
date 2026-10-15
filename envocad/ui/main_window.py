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
    QTabWidget,
    QToolBar,
)

from envocad import __version__
from envocad.library.store import LibraryStore
from envocad.model.project import Project, Sheet
from envocad.ui import theme
from envocad.ui.canvas import Mode, SchematicScene, SchematicView
from envocad.ui.layout_view import LayoutScene, LayoutView
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
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)
        self._panels_wired = False

        self.lib_panel = LibraryPanel(self.library)
        self.props_panel = PropertiesPanel()
        self._dock("Knihovna", self.lib_panel, Qt.LeftDockWidgetArea)
        self._dock("Vlastnosti", self.props_panel, Qt.RightDockWidgetArea)
        self.setStatusBar(QStatusBar())
        self._build_actions()
        self._load_project(self.project)
        self.resize(1400, 900)

    # ---- aktuální záložka ----------------------------------------------------
    @property
    def view(self):
        return self.tabs.currentWidget()

    @property
    def scene(self) -> SchematicScene | None:
        v = self.view
        return v.scene() if isinstance(v, SchematicView) else None

    @property
    def current_sheet(self) -> Sheet | None:
        v = self.view
        return v.scene().sheet if isinstance(v, (SchematicView, LayoutView)) else None

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

        m_sheet = mb.addMenu("&List")
        act(m_sheet, "Nový list schématu", self.new_schematic_sheet)
        act(m_sheet, "Přejmenovat list…", self.rename_sheet)
        act(m_sheet, "Odstranit list", self.delete_sheet)
        m_sheet.addSeparator()
        act(m_sheet, "Otevřít rozvaděč (schéma)", lambda: self._open_selected_switchboard("schematic"))
        act(m_sheet, "Otevřít rozvaděč (rozložení)", lambda: self._open_selected_switchboard("layout"))
        act(m_sheet, "Rozložení aktuálního rozvaděče", self.open_current_layout, "Ctrl+L", True)
        act(m_sheet, "Nastavení skříně…", self.edit_enclosure)
        act(m_sheet, "Vložit šablonu rozvaděče…", self.insert_template)

        m_out = mb.addMenu("&Výstupy")
        act(m_out, "Výkazy aktuálního listu (xlsx)…", lambda: self.export_xlsx(current_only=True))
        act(m_out, "Výkazy celého projektu (xlsx)…", lambda: self.export_xlsx(current_only=False))
        act(m_out, "Protokol kusového ověření (docx)…", self.export_routine_test)

        m_lib = mb.addMenu("&Knihovna")
        act(m_lib, "Importovat symbol z DXF…", self.import_dxf_symbol)

        m_help = mb.addMenu("&Nápověda")
        act(m_help, "Otevřít složku s logy", self.open_log_dir)
        act(m_help, "O programu", lambda: QMessageBox.about(
            self, "EnvoCAD", f"EnvoCAD {__version__}\nInterní nástroj ENVO pro elektro-dokumentaci FVE."))

    # ---- projekt ---------------------------------------------------------------
    def _load_project(self, project: Project) -> None:
        self.project = project
        self.undo.clear()
        while self.tabs.count():
            self.tabs.removeTab(0)
        if not self._panels_wired:
            self.lib_panel.symbol_chosen.connect(lambda sid: self.scene and self.scene.start_place(sid))
            self.props_panel.attr_edited.connect(lambda *a: self.scene and self.scene.set_attr(*a))
            self._panels_wired = True
        for sheet in project.sheets:
            self.open_sheet(sheet, "schematic")
        self.tabs.setCurrentIndex(0)
        self.props_panel.show_item(None)
        self._update_title()
        if self.view:
            self.view.zoom_fit()

    # ---- listy / záložky -------------------------------------------------------
    def _find_tab(self, sheet: Sheet, kind: str) -> int:
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if w.scene().sheet is sheet and (kind == "layout") == isinstance(w, LayoutView):
                return i
        return -1

    def open_sheet(self, sheet: Sheet, kind: str = "schematic") -> None:
        """Otevře (nebo aktivuje) záložku listu; kind = schematic | layout."""
        i = self._find_tab(sheet, kind)
        if i >= 0:
            self.tabs.setCurrentIndex(i)
            return
        if kind == "layout":
            scene = LayoutScene(self.project, sheet, self.library, self.undo)
            view = LayoutView(scene)
            scene.selection_info.connect(lambda it: self.props_panel.show_item(
                self._element_item_for(sheet, it.element.id) if it else None))
            title = f"{sheet.name} – rozložení"
        else:
            scene = SchematicScene(self.project, sheet, self.library, self.undo)
            view = SchematicView(scene)
            scene.selection_info.connect(self.props_panel.show_item)
            scene.attrs_changed.connect(lambda _id: self.props_panel.show_item(self._selected_item()))
            scene.mode_changed.connect(self._show_mode)
            scene.open_switchboard.connect(self.open_switchboard_from_block)
            title = sheet.name if not sheet.is_switchboard else f"{sheet.name} – schéma"
        scene.setParent(view)  # jinak by scénu sebral garbage collector
        idx = self.tabs.addTab(view, title)
        self.tabs.setCurrentIndex(idx)
        view.zoom_fit()

    def _element_item_for(self, sheet: Sheet, eid: str):
        i = self._find_tab(sheet, "schematic")
        if i < 0:
            return None
        return self.tabs.widget(i).scene().element_items.get(eid)

    def _close_tab(self, index: int) -> None:
        if self.tabs.count() <= 1:
            return
        w = self.tabs.widget(index)
        self.tabs.removeTab(index)
        w.deleteLater()

    def _tab_changed(self, _index: int) -> None:
        self.props_panel.show_item(None)
        if self.scene:
            self._show_mode(self.scene.mode)
        else:
            self.statusBar().showMessage("Rozložení – přetahujte přístroje na DIN lišty (snap 0,5 modulu)")

    def _refresh_tab_titles(self) -> None:
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            sh = w.scene().sheet
            self.tabs.setTabText(i, f"{sh.name} – rozložení" if isinstance(w, LayoutView)
                                 else (f"{sh.name} – schéma" if sh.is_switchboard else sh.name))

    def new_schematic_sheet(self) -> None:
        name, ok = QInputDialog.getText(self, "Nový list", "Název listu:", text=f"List {len(self.project.sheets) + 1}")
        if not ok or not name:
            return
        sheet = Sheet(name=name)
        self.project.sheets.append(sheet)
        self.open_sheet(sheet)
        self.undo.resetClean()

    def rename_sheet(self) -> None:
        sh = self.current_sheet
        if not sh:
            return
        name, ok = QInputDialog.getText(self, "Přejmenovat list", "Název:", text=sh.name)
        if ok and name:
            sh.name = name
            self._refresh_tab_titles()
            self.undo.resetClean()

    def delete_sheet(self) -> None:
        sh = self.current_sheet
        if not sh or len(self.project.sheets) <= 1:
            return
        if QMessageBox.question(self, "Odstranit list", f"Opravdu odstranit list „{sh.name}“ se vším obsahem?") != QMessageBox.Yes:
            return
        self.project.sheets.remove(sh)
        for kind in ("layout", "schematic"):
            i = self._find_tab(sh, kind)
            if i >= 0:
                self.tabs.removeTab(i)
        self.undo.clear()
        self.undo.resetClean()

    # ---- rozvaděče -------------------------------------------------------------
    def open_switchboard_from_block(self, block_id: str, kind: str = "schematic") -> None:
        # signál přichází z obsluhy dvojkliku ve scéně – dialogy a přepínání záložek odložit až po ní
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._open_switchboard_now(block_id, kind))

    def _open_switchboard_now(self, block_id: str, kind: str) -> None:
        sheet_of_block = self.project.sheet_of_element(block_id)
        if not sheet_of_block:
            return
        block = sheet_of_block.element(block_id)
        existing = self.project.switchboard_sheet(block_id)
        sheet = self.project.create_switchboard_sheet(block)
        if existing is None:
            self.undo.resetClean()
            if not self._choose_template(sheet):
                pass
        self.open_sheet(sheet, kind)

    def _open_selected_switchboard(self, kind: str) -> None:
        it = self._selected_item()
        from envocad.ui.items import ElementItem
        if isinstance(it, ElementItem) and it.symbol.id == "fve.switchboard":
            self.open_switchboard_from_block(it.element.id, kind)
        elif self.current_sheet and self.current_sheet.is_switchboard:
            self.open_sheet(self.current_sheet, kind)
        else:
            QMessageBox.information(self, "Rozvaděč", "Vyberte blok ROZVADĚČ ve schématu (nebo na něj dvakrát klikněte).")

    def open_current_layout(self) -> None:
        sh = self.current_sheet
        if sh and sh.is_switchboard:
            self.open_sheet(sh, "layout")
        else:
            self._open_selected_switchboard("layout")

    def _choose_template(self, sheet: Sheet) -> bool:
        from envocad.library.templates import TEMPLATES, apply_template
        names = [t.name for t in TEMPLATES]
        name, ok = QInputDialog.getItem(self, "Šablona rozvaděče", "Nový list rozvaděče – vložit šablonu:", names, 0, False)
        if not ok:
            return False
        t = next(t for t in TEMPLATES if t.name == name)
        params = {}
        for tp in t.params:
            v, ok = QInputDialog.getText(self, t.name, tp.label, text=tp.default)
            if not ok:
                return False
            params[tp.key] = v
        apply_template(self.project, sheet, t.id, params)
        self._rebuild_sheet_views(sheet)
        return True

    def insert_template(self) -> None:
        sh = self.current_sheet
        if not sh or not sh.is_switchboard:
            QMessageBox.information(self, "Šablona", "Šablonu lze vložit jen do listu rozvaděče.")
            return
        if self._choose_template(sh):
            self.undo.clear()
            self.undo.resetClean()

    def _rebuild_sheet_views(self, sheet: Sheet) -> None:
        for kind in ("schematic", "layout"):
            i = self._find_tab(sheet, kind)
            if i >= 0:
                self.tabs.widget(i).scene().rebuild()

    def edit_enclosure(self) -> None:
        sh = self.current_sheet
        if not sh or not sh.is_switchboard:
            QMessageBox.information(self, "Skříň", "Otevřete list rozvaděče.")
            return
        lay = sh.layout
        name, ok = QInputDialog.getText(self, "Skříň", "Typ skříně:", text=lay.enclosure)
        if not ok:
            return
        rows, ok = QInputDialog.getInt(self, "Skříň", "Počet řad DIN lišt:", lay.rows, 1, 12)
        if not ok:
            return
        mods, ok = QInputDialog.getInt(self, "Skříň", "Modulů v řadě:", lay.modules_per_row, 4, 96)
        if not ok:
            return
        lay.enclosure, lay.rows, lay.modules_per_row = name, rows, mods
        lay.placements = [p for p in lay.placements if p.row < rows]
        self._rebuild_sheet_views(sh)
        self.undo.resetClean()

    def set_dark(self, dark: bool) -> None:
        theme.apply(dark)
        for i in range(self.tabs.count()):
            sc = self.tabs.widget(i).scene()
            sc.retheme() if isinstance(sc, SchematicScene) else sc.rebuild()

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
        if not self.scene:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export DXF", "", "DXF (*.dxf)")
        if path:
            export_sheet_dxf(self.project, self.scene.sheet, self.library, path)
            self.statusBar().showMessage(f"Exportováno: {path}", 3000)

    def export_pdf(self) -> None:
        from envocad.export.pdf_export import export_scene_pdf
        if not self.scene:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", "", "PDF (*.pdf)")
        if path:
            export_scene_pdf(self.scene, path)
            self.statusBar().showMessage(f"Exportováno: {path}", 3000)

    def export_xlsx(self, current_only: bool) -> None:
        from envocad.export.xlsx_export import export_reports_xlsx
        sh = self.current_sheet if current_only else None
        base = (sh.name if sh else self.project.name).replace("/", "-")
        path, _ = QFileDialog.getSaveFileName(self, "Výkazy", f"{base} – výkazy.xlsx", "Excel (*.xlsx)")
        if path:
            export_reports_xlsx(self.project, self.library, path, sh)
            self.statusBar().showMessage(f"Exportováno: {path}", 3000)

    def export_routine_test(self) -> None:
        from envocad.export.docx_export import export_routine_test_docx
        sh = self.current_sheet
        if not sh or not sh.is_switchboard:
            QMessageBox.information(self, "Protokol", "Otevřete list rozvaděče, pro který se má protokol vygenerovat.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Protokol kusového ověření", f"{sh.name} – kusové ověření.docx",
                                              "Word (*.docx)")
        if path:
            export_routine_test_docx(self.project, self.library, sh, path)
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

    def open_log_dir(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from envocad.logging_setup import log_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir())))

    def closeEvent(self, ev) -> None:
        if self._confirm_discard():
            ev.accept()
        else:
            ev.ignore()
