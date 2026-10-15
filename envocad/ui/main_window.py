"""Hlavní okno EnvoCAD."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QToolBar,
)

from envocad import __version__
from envocad.library.store import LibraryStore
from envocad.model.project import Project, Sheet
from envocad.ui import commands, theme
from envocad.ui.canvas import Mode, SchematicScene, SchematicView
from envocad.ui.layout_view import LayoutScene, LayoutView
from envocad.ui.multipole_view import MultipoleScene, MultipoleView
from envocad.ui.terminal_plan_view import TerminalPlanScene, TerminalPlanView

DERIVED_VIEWS = (MultipoleView, TerminalPlanView)  # pohledy odvozené z modelu – po změně se přestaví
from envocad.ui.panels import LibraryPanel, PropertiesPanel

FILE_FILTER = "Projekt EnvoCAD (*.ecp)"
log = logging.getLogger("envocad.ui")


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
        self._scenes: list = []

        from envocad.ui.navigator import NavigatorPanel
        self.lib_panel = LibraryPanel(self.library)
        self.props_panel = PropertiesPanel(self.library)
        self.nav_panel = NavigatorPanel(self.library)
        self.nav_panel.goto.connect(self.goto_target)
        self._dock("Knihovna", self.lib_panel, Qt.LeftDockWidgetArea)
        self._dock("Navigátor", self.nav_panel, Qt.LeftDockWidgetArea)
        self._dock("Vlastnosti", self.props_panel, Qt.RightDockWidgetArea)
        self.setStatusBar(QStatusBar())
        self._build_actions()
        self._load_plugins()
        self._load_project(self.project)
        self.resize(1400, 900)
        # automatické ukládání rozpracovaného projektu (obnova po pádu)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(120_000)
        self._autosave_timer.timeout.connect(self.autosave)
        self._autosave_timer.start()
        QTimer.singleShot(0, self.offer_recovery)

    # ---- aktuální záložka ----------------------------------------------------
    @staticmethod
    def _unwrap(w):
        """Záložka rozložení je QSplitter(pohled, panel) – vrátí vlastní pohled."""
        return getattr(w, "_view", w)

    @property
    def view(self):
        return self._unwrap(self.tabs.currentWidget())

    @property
    def scene(self) -> SchematicScene | None:
        v = self.view
        return v.scene() if isinstance(v, SchematicView) and not isinstance(v, DERIVED_VIEWS) else None

    def _jps_scene(self, sheet: Sheet) -> SchematicScene | None:
        """JPS scéna listu (i když je aktivní jiná záložka) – příkazy nad vodiči jdou přes ni."""
        i = self._find_tab(sheet, "schematic")
        return self._unwrap(self.tabs.widget(i)).scene() if i >= 0 else None

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
        act(m_file, "Nový projekt z průvodce…", self.new_project_wizard, "Ctrl+Shift+N")
        act(m_file, "Nový projekt ze specifikace (JSON)…", self.new_project_from_spec)
        act(m_file, "&Otevřít…", self.open_project, "Ctrl+O", True)
        self.m_recent = m_file.addMenu("Poslední projekty")
        self._refresh_recent_menu()
        act(m_file, "&Uložit", self.save_project, "Ctrl+S", True)
        act(m_file, "Uložit &jako…", self.save_project_as, "Ctrl+Shift+S")
        m_file.addSeparator()
        act(m_file, "Export &DXF…", self.export_dxf)
        act(m_file, "Export &PDF…", self.export_pdf)
        act(m_file, "Export PDF na A4 (zmenšeno)…", lambda: self.export_pdf("A4"))
        m_file.addSeparator()
        act(m_file, "Vlastnosti projektu…", self.edit_project_meta)
        act(m_file, "Porovnat s revizí (.ecp)…", self.compare_revision)
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
        act(m_edit, "Kopírovat", lambda: self.scene and self.scene.copy_selected())
        act(m_edit, "Vložit kopii", lambda: self.scene and self.scene.paste())
        act(m_edit, "Uložit výběr jako makro…", self.save_macro, "Ctrl+Shift+S")
        act(m_edit, "Smazat makro…", self.delete_macro)
        act(m_edit, "Smazat", lambda: self.scene and self.scene.delete_selected(), "Delete")
        act(m_edit, "Otočit o 90°", lambda: self.scene and self.scene.rotate_selected(), "R")
        m_edit.addSeparator()
        act(m_edit, "Svorky vybraného vodiče…", self.edit_wire_terminals, "Ctrl+T")
        act(m_edit, "Očíslovat svorky automaticky", self.auto_number_terminals)
        act(m_edit, "Svorkovnice a můstky…", self.edit_strip, "Ctrl+Shift+T")
        act(m_edit, "Kabel vybraného vodiče (žíly, barvy, stínění)…", self.edit_cable, "Ctrl+Shift+K")
        m_edit.addSeparator()
        act(m_edit, "Najít označení…", self.find_ref, "Ctrl+F")
        act(m_edit, "Kontrola projektu…", self.run_checks, "F7", True)

        m_draw = mb.addMenu("&Kreslit")
        tb.addSeparator()
        act(m_draw, "Vodič (W)", lambda: self.scene and self.scene.start_wire(), None, True)
        act(m_draw, "Výběr (Esc)", lambda: self.scene and self.scene.set_mode(Mode.SELECT), None, True)

        m_view = mb.addMenu("&Zobrazit")
        act(m_view, "Přizpůsobit list", lambda: self.view and self.view.zoom_fit(), "Home", True)
        act(m_view, "Vícepólový pohled", self.open_multipole, "Ctrl+M", True)
        act(m_view, "Jednopólové schéma", self.open_singlepole, "Ctrl+J")
        act(m_view, "Plán svorkovnice", lambda: self.current_sheet and self.open_sheet(self.current_sheet, "terminals"),
            "Ctrl+Shift+M")
        act(m_view, "Vícepól: rozmístit automaticky", lambda: isinstance(self.view, MultipoleView)
            and self.view.scene().reset_layout())
        self.act_dark = QAction("Tmavý režim", self, checkable=True)
        self.act_dark.setShortcut(QKeySequence("Ctrl+D"))
        self.act_dark.setChecked(theme.is_dark())
        self.act_dark.toggled.connect(self.set_dark)
        m_view.addAction(self.act_dark)
        from envocad.model.frame import frame_enabled
        self.act_frame = QAction("Rámeček a popisové pole", self, checkable=True)
        self.act_frame.setChecked(frame_enabled())
        self.act_frame.toggled.connect(self.set_frame)
        m_view.addAction(self.act_frame)

        m_sheet = mb.addMenu("&List")
        act(m_sheet, "Nový list schématu", self.new_schematic_sheet)
        act(m_sheet, "Přejmenovat list…", self.rename_sheet)
        act(m_sheet, "Odstranit list", self.delete_sheet)
        m_sheet.addSeparator()
        act(m_sheet, "Otevřít rozvaděč (schéma)", lambda: self._open_selected_switchboard("schematic"))
        act(m_sheet, "Rozvaděč – jednopólová editace", lambda: self._open_selected_switchboard("edit"))
        act(m_sheet, "Otevřít rozvaděč (rozložení)", lambda: self._open_selected_switchboard("layout"))
        act(m_sheet, "Rozložení aktuálního rozvaděče", self.open_current_layout, "Ctrl+L", True)
        self.act_enclosure = act(m_sheet, "Skříň rozvaděče (rozměry a parametry)…", self.edit_enclosure, "Ctrl+K", True)
        act(m_sheet, "Vložit šablonu rozvaděče…", self.insert_template)

        m_out = mb.addMenu("&Výstupy")
        act(m_out, "Výkazy aktuálního listu (xlsx)…", lambda: self.export_xlsx(current_only=True))
        act(m_out, "Výkazy celého projektu (xlsx)…", lambda: self.export_xlsx(current_only=False))
        act(m_out, "Protokol kusového ověření (docx)…", self.export_routine_test)
        act(m_out, "Technická zpráva (docx)…", self.export_tz)
        act(m_out, "Štítky pro tiskárnu (CSV)…", self.export_labels_csv)
        m_out.addSeparator()
        act(m_out, "Celá dokumentace (PDF)…", self.export_documentation, "Ctrl+Shift+E", True)

        m_lib = mb.addMenu("&Knihovna")
        act(m_lib, "Importovat symbol z DXF…", self.import_dxf_symbol)
        act(m_lib, "Prohlížet artikly…", self.browse_components)
        act(m_lib, "Importovat artikly z CSV…", self.import_components_csv)
        m_lib.addSeparator()
        act(m_lib, "Sdílená knihovna (síťová složka)…", self.set_shared_library)
        act(m_lib, "Firemní standard (výchozí kabely, zpracoval)…", self.edit_standard)

        m_help = mb.addMenu("&Nápověda")
        act(m_help, "Otevřít složku s logy", self.open_log_dir)
        act(m_help, "O programu", lambda: QMessageBox.about(
            self, "EnvoCAD", f"EnvoCAD {__version__}\nInterní nástroj ENVO pro elektro-dokumentaci FVE."))

    # ---- pluginy ---------------------------------------------------------------
    def _load_plugins(self) -> None:
        from envocad.plugins import load_plugins
        self.plugins = load_plugins(self.library)
        menus = {m.title().replace("&", ""): m for m in self.menuBar().findChildren(QMenu) if m.title()}
        for menu_name, text, cb in self.plugins.menu_actions:
            menu = menus.get(menu_name)
            if menu is None:
                menu = self.menuBar().addMenu(menu_name)
                menus[menu_name] = menu
            a = QAction(text, self)
            a.triggered.connect(lambda _c=False, cb=cb: cb(self))
            menu.addAction(a)
        if self.plugins.importers:
            m_lib = menus.get("Knihovna")
            if m_lib is not None:
                m_lib.addSeparator()
                for text, cb in self.plugins.importers:
                    a = QAction(text, self)
                    a.triggered.connect(lambda _c=False, cb=cb: cb(self))
                    m_lib.addAction(a)
        act_dir = QAction("Otevřít složku knihovny a pluginů", self)
        act_dir.triggered.connect(self.open_home_dir)
        menus["Knihovna"].addSeparator()
        menus["Knihovna"].addAction(act_dir)

    def open_home_dir(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from envocad.library.store import home_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(home_dir())))

    # ---- projekt ---------------------------------------------------------------
    def _load_project(self, project: Project) -> None:
        from envocad.model.project import sync_feed_links
        self.project = project
        sync_feed_links(project)
        from envocad.model.project import sync_cables
        sync_cables(project)
        self.nav_panel.set_project(project)
        self.undo.clear()
        while self.tabs.count():
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            w.deleteLater()
        self._scenes.clear()
        if not self._panels_wired:
            self.lib_panel.symbol_chosen.connect(lambda sid: self.scene and self.scene.start_place(sid))
            self.lib_panel.macro_chosen.connect(self.insert_macro)
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
            w = self._unwrap(self.tabs.widget(i))
            if w.scene().sheet is not sheet:
                continue
            wk = self._kind_of(w)
            if wk == kind:
                return i
        return -1

    @staticmethod
    def _kind_of(view) -> str:
        for cls, kind in ((LayoutView, "layout"), (MultipoleView, "multipole"), (TerminalPlanView, "terminals")):
            if isinstance(view, cls):
                return kind
        return "schematic"

    def open_sheet(self, sheet: Sheet, kind: str = "schematic") -> None:
        """Otevře (nebo aktivuje) záložku listu; kind = schematic | layout | multipole."""
        log.info("open_sheet %s (%s)", sheet.name, kind)
        i = self._find_tab(sheet, kind)
        if i >= 0:
            self.tabs.setCurrentIndex(i)
            return
        if kind == "layout":
            from envocad.ui.dialogs import EnclosurePanel
            scene = LayoutScene(self.project, sheet, self.library, self.undo)
            view = LayoutView(scene)
            panel = EnclosurePanel(sheet, library=self.library)
            panel.changed.connect(lambda sc=scene, sh=sheet: (sc.rebuild(), self._rebuild_sheet_views(sh),
                                                            self._refresh_tab_titles(), self.undo.resetClean()))
            scene.layout_changed.connect(panel.refresh)
            scene.enclosure_requested.connect(lambda p=panel: p.name.setFocus())
            scene.selection_info.connect(lambda it: self.props_panel.show_item(
                self._element_item_for(sheet, it.element.id) if it else None))
            view.side_panel = panel
            title = f"{sheet.name} – rozložení"
        elif kind == "multipole":
            scene = MultipoleScene(self.project, sheet, self.library, self.undo)
            view = MultipoleView(scene)
            scene.selection_info.connect(lambda it: self.props_panel.show_item(
                self._element_item_for(sheet, it.element.id) if it is not None and hasattr(it, "element") else None))
            scene.edit_element_requested.connect(lambda eid, sh=sheet: self._edit_element_anywhere(sh, eid))
            scene.delete_requested.connect(lambda eids, wids, sh=sheet: self._delete_anywhere(sh, eids, wids))
            title = f"{sheet.name} – schéma" if sheet.is_switchboard else f"{sheet.name} – vícepól"
        elif kind == "terminals":
            scene = TerminalPlanScene(self.project, sheet, self.library, self.undo)
            view = TerminalPlanView(scene)
            title = f"{sheet.name} – svorkovnice"
        else:
            scene = SchematicScene(self.project, sheet, self.library, self.undo)
            view = SchematicView(scene)
            scene.selection_info.connect(self.props_panel.show_item)
            scene.attrs_changed.connect(lambda _id: self.props_panel.show_item(self._selected_item()))
            scene.mode_changed.connect(self._show_mode)
            scene.open_switchboard.connect(self.open_switchboard_from_block)
            title = sheet.name if not sheet.is_switchboard else f"{sheet.name} – jednopól (editace)"
        self._scenes.append(scene)  # držet referenci – scéna musí přežít stejně dlouho jako pohled
        view._scene_ref = scene
        widget = view
        if getattr(view, "side_panel", None) is not None:
            from PySide6.QtWidgets import QScrollArea, QSplitter
            widget = QSplitter()
            widget.addWidget(view)
            sa = QScrollArea()
            sa.setWidget(view.side_panel)
            sa.setWidgetResizable(True)
            sa.setMinimumWidth(300)
            widget.addWidget(sa)
            widget.setStretchFactor(0, 1)
            widget.setSizes([900, 340])
            widget.scene = view.scene  # záložka se chová jako pohled
            widget.zoom_fit = view.zoom_fit
            widget._view = view
        idx = self.tabs.addTab(widget, title)
        self.tabs.setCurrentIndex(idx)
        view.zoom_fit()

    def _edit_element_anywhere(self, sheet: Sheet, eid: str) -> None:
        sc = self._jps_scene(sheet)
        if sc is None:
            self.open_sheet(sheet, "schematic")
            sc = self._jps_scene(sheet)
        if sc is not None:
            sc.edit_element(eid)

    def _delete_anywhere(self, sheet: Sheet, eids: list, wids: list) -> None:
        """Mazání z odvozeného pohledu: příkaz jde přes JPS scénu listu (otevře se skrytě, záložka se nepřepne)."""
        cur = self.tabs.currentIndex()
        sc = self._jps_scene(sheet)
        if sc is None:
            self.open_sheet(sheet, "schematic")
            sc = self._jps_scene(sheet)
            self.tabs.setCurrentIndex(cur)
        if sc is not None and (eids or wids):
            sc.undo.push(commands.RemoveItemsCommand(sc, eids, wids))

    def _element_item_for(self, sheet: Sheet, eid: str):
        i = self._find_tab(sheet, "schematic")
        if i < 0:
            return None
        return self._unwrap(self.tabs.widget(i)).scene().element_items.get(eid)

    def _close_tab(self, index: int) -> None:
        log.info("close_tab %s", index)
        if self.tabs.count() <= 1:
            return
        w = self.tabs.widget(index)
        self.tabs.removeTab(index)
        w.deleteLater()

    def _tab_changed(self, _index: int) -> None:
        log.info("tab_changed %s", _index)
        self.props_panel.show_item(None)
        v = self.view
        if isinstance(v, DERIVED_VIEWS) and getattr(v, "_dirty", False):
            v._dirty = False
            v.scene().rebuild()
        if self.scene:
            self._show_mode(self.scene.mode)
        elif isinstance(self.view, MultipoleView):
            self.statusBar().showMessage("Vícepól – odvozený z JPS; dvojklik na žílu = svorky, Ctrl+T, "
                                         "Úpravy → Očíslovat svorky")
        elif isinstance(self.view, TerminalPlanView):
            self.statusBar().showMessage("Plán svorkovnice – odvozený z listu; Soubor → Export PDF")
        else:
            self.statusBar().showMessage("Rozložení – přetahujte přístroje na DIN lišty (snap 0,5 modulu)")

    def _refresh_tab_titles(self) -> None:
        for i in range(self.tabs.count()):
            w = self._unwrap(self.tabs.widget(i))
            sh = w.scene().sheet
            if isinstance(w, LayoutView):
                self.tabs.setTabText(i, f"{sh.name} – rozložení")
            elif isinstance(w, MultipoleView):
                self.tabs.setTabText(i, f"{sh.name} – schéma" if sh.is_switchboard else f"{sh.name} – vícepól")
            elif isinstance(w, TerminalPlanView):
                self.tabs.setTabText(i, f"{sh.name} – svorkovnice")
            else:
                self.tabs.setTabText(i, f"{sh.name} – jednopól (editace)" if sh.is_switchboard else sh.name)

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
        # schéma rozvaděče je vícepólové; jednopólová podoba je jen editační (Ctrl+J)
        self.open_sheet(sheet, "multipole" if kind == "schematic" else kind)
        self._sync_links_and_blocks()

    def _open_selected_switchboard(self, kind: str) -> None:
        if kind == "edit":
            kind = "schematic"
            sh = self.current_sheet
            if sh is not None and sh.is_switchboard:
                self.open_sheet(sh, "schematic")
                return
        it = self._selected_item()
        from envocad.ui.items import ElementItem
        if isinstance(it, ElementItem) and it.symbol.id == "fve.switchboard":
            self.open_switchboard_from_block(it.element.id, kind)
        elif self.current_sheet and self.current_sheet.is_switchboard:
            self.open_sheet(self.current_sheet, "multipole" if kind == "schematic" else kind)
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
        self._sync_links_and_blocks()
        for kind in ("schematic", "layout", "multipole", "terminals"):
            i = self._find_tab(sheet, kind)
            if i >= 0:
                sc = self._unwrap(self.tabs.widget(i)).scene()
                sc.rebuild()
                sc.update()

    def edit_enclosure(self) -> None:
        sh = self.current_sheet
        if not sh or not sh.is_switchboard:
            QMessageBox.information(self, "Skříň", "Otevřete list rozvaděče.")
            return
        from envocad.ui.dialogs import EnclosureDialog
        dlg = EnclosureDialog(sh, self, library=self.library)
        if dlg.exec() != EnclosureDialog.Accepted:
            return
        dlg.apply()
        self._rebuild_sheet_views(sh)
        self._refresh_tab_titles()
        self.undo.resetClean()

    def set_frame(self, on: bool) -> None:
        """Zapne/vypne rámeček s popisovým polem a QR na všech listech (uloží se do ~/.envocad/settings.json)."""
        from envocad.settings import load_settings, save_settings
        data = load_settings()
        data["frame"] = bool(on)
        save_settings(data)
        if self.view is not None:
            self.view.viewport().update()

    def set_dark(self, dark: bool) -> None:
        log.info("set_dark %s", dark)
        theme.apply(dark)
        for i in range(self.tabs.count()):
            sc = self._unwrap(self.tabs.widget(i)).scene()
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
        self._sync_links_and_blocks()
        self.nav_panel._schedule()
        # odvozené pohledy (vícepól, plán svorkovnice): viditelný se přestaví hned, ostatní až při přepnutí
        for i in range(self.tabs.count()):
            w = self._unwrap(self.tabs.widget(i))
            if isinstance(w, DERIVED_VIEWS):
                if i == self.tabs.currentIndex():
                    w.scene().rebuild()
                else:
                    w._dirty = True

    # ---- navigace --------------------------------------------------------------
    def goto_target(self, sheet_id: str, target_id: str, is_wire: bool) -> None:
        """Skok na prvek/vodič: otevře (editační) list, vybere položku a vycentruje pohled."""
        sheet = next((s for s in self.project.sheets if s.id == sheet_id), None)
        if sheet is None:
            return
        self.open_sheet(sheet, "schematic")
        sc = self.scene
        if sc is None or not target_id:
            return
        it = sc.wire_items.get(target_id) if is_wire else sc.element_items.get(target_id)
        if it is None:
            return
        sc.clearSelection()
        it.setSelected(True)
        self.view.centerOn(it)

    def find_ref(self) -> None:
        text, ok = QInputDialog.getText(self, "Najít", "Označení prvku nebo vodiče (např. F2, X1, W3):")
        if not ok or not text.strip():
            return
        q = text.strip().lower()
        for s in self.project.sheets:
            for e in s.elements:
                if e.ref.lower() == q:
                    self.goto_target(s.id, e.id, False)
                    return
            for w in s.wires:
                if w.attrs.get("ref", "").lower() == q:
                    self.goto_target(s.id, w.id, True)
                    return
        self.nav_panel.filter.setText(text.strip())
        self.statusBar().showMessage(f"„{text}“ nenalezeno – v navigátoru je nastavený filtr", 4000)

    def run_checks(self) -> None:
        from envocad.model.checks import check_project
        from envocad.ui.navigator import ChecksDialog
        findings = check_project(self.project, self.library)
        dlg = ChecksDialog(findings, self)
        dlg.goto.connect(self.goto_target)
        dlg.exec()

    def _sync_links_and_blocks(self) -> None:
        """Po změně modelu: vazby přívodů/vývodů na vodiče JPS (odvozené, mimo undo) a porty bloků ROZVADĚČ."""
        from envocad.model.project import sync_cables, sync_feed_links
        sync_feed_links(self.project)
        sync_cables(self.project)
        self._refresh_switchboard_blocks()

    def _refresh_switchboard_blocks(self) -> None:
        """Bloky ROZVADĚČ v JPS mají porty podle přívodů/vývodů svého listu – po změně listu se přestaví."""
        from envocad.model.project import element_symbol
        for i in range(self.tabs.count()):
            w = self._unwrap(self.tabs.widget(i))
            sc = w.scene()
            if not isinstance(sc, SchematicScene):
                continue
            for e in sc.sheet.elements:
                if e.symbol_id != "fve.switchboard":
                    continue
                it = sc.element_items.get(e.id)
                sym = element_symbol(self.project, e, self.library)
                if it is not None and [p.to_dict() for p in it.symbol.ports] != [p.to_dict() for p in sym.ports]:
                    it.symbol = sym
                    it._path = __import__("envocad.ui.render", fromlist=["symbol_path"]).symbol_path(sym)
                    it.sync_from_model()
                    sc.update_wires_of(e.id)

    # ---- vícepól ---------------------------------------------------------------
    def open_multipole(self) -> None:
        sh = self.current_sheet
        if sh is None:
            return
        self.open_sheet(sh, "multipole")

    def open_singlepole(self) -> None:
        sh = self.current_sheet
        if sh is None:
            return
        self.open_sheet(sh, "schematic")

    def _selected_wire_id(self) -> tuple[Sheet, str] | None:
        v = self.view
        sh = self.current_sheet
        if sh is None or not hasattr(v, "scene"):
            return None
        sel = v.scene().selectedItems()
        if len(sel) == 1 and hasattr(sel[0], "wire"):
            return sh, sel[0].wire.id
        return None

    def edit_wire_terminals(self) -> None:
        hit = self._selected_wire_id()
        if not hit:
            QMessageBox.information(self, "Svorky", "Vyberte vodič (ve schématu nebo žílu ve vícepólu).")
            return
        sh, wid = hit
        sc = self._jps_scene(sh) or self.view.scene()
        sc.edit_terminals(wid)

    def edit_strip(self) -> None:
        sh = self.current_sheet
        if sh is None:
            return
        from envocad.ui.dialogs import StripDialog
        strip = ""
        it = self._selected_item() if self.scene else None
        if it is not None and hasattr(it, "element"):
            strip = it.element.ref
        dlg = StripDialog(self.project, sh, self, strip)
        if dlg.strip.count() == 0:
            QMessageBox.information(self, "Svorkovnice", "Na listu nejsou žádné svorky (X…).")
            return
        if dlg.exec() != StripDialog.Accepted:
            return
        strip, groups = dlg.values()
        if strip and groups != self.project.bridge_groups(strip, sh):
            self.undo.push(commands.SetBridgesCommand(self.project, sh, strip, self.project.bridge_groups(strip, sh), groups))

    def edit_cable(self) -> None:
        hit = self._selected_wire_id()
        if not hit:
            QMessageBox.information(self, "Kabel", "Vyberte vodič v JPS.")
            return
        sh, wid = hit
        from envocad.model.project import sync_cables
        sync_cables(self.project)
        w = next(w for w in sh.wires if w.id == wid)
        c = self.project.cable_of_wire(w)
        if c is None:
            QMessageBox.information(self, "Kabel", "Vodič nemá označení ani typ kabelu – vyplňte je v dialogu vodiče (dvojklik).")
            return
        from envocad.ui.dialogs import CableDialog
        dlg = CableDialog(c, self, library=self.library)
        if dlg.exec() != CableDialog.Accepted:
            return
        old, new = c.to_dict(), dlg.values()
        if old != new:
            self.undo.push(commands.SetCableCommand(self.project, c.id, old, new))

    def auto_number_terminals(self) -> None:
        sh = self.current_sheet
        if sh is None:
            return
        sc = self._jps_scene(sh)
        if sc is None:
            self.open_sheet(sh, "schematic")
            sc = self._jps_scene(sh)
        n = sc.auto_number_terminals()
        self.statusBar().showMessage(f"Očíslovány svorky u {n} vodičů" if n else "Všechny svorky už jsou přiřazené", 4000)

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
            from envocad.settings import load_settings
            st = load_settings()["standard"]
            p = Project()
            p.meta.update({k: str(v) for k, v in (st.get("project_meta") or {}).items()})
            if st.get("author"):
                p.meta.setdefault("author", st["author"])
            self._load_project(p)

    def _active_schematic(self) -> SchematicScene | None:
        """Scéna JPS / jednopólové editace v aktivní záložce (ne vícepól, rozložení…)."""
        v = self.view
        sc = v.scene() if v is not None and hasattr(v, "scene") else None
        return sc if isinstance(sc, SchematicScene) else None

    def save_macro(self) -> None:
        """Vybrané prvky + vodiče mezi nimi uloží jako makro (~/.envocad/macros, nebo do sdílené knihovny)."""
        from envocad.library.macros import save_macro, shared_dir
        from envocad.model.project import copy_fragment
        sc = self._active_schematic()
        eids = [it.element.id for it in sc.selectedItems() if hasattr(it, "element")] if sc else []
        if not eids:
            QMessageBox.information(self, "Makro", "Vyberte prvky (a vodiče mezi nimi), které má makro obsahovat.")
            return
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Uložit makro", "Název makra:")
        if not ok or not name.strip():
            return
        desc, _ = QInputDialog.getText(self, "Uložit makro", "Popis (volitelný):")
        shared = False
        if shared_dir() is not None:
            shared = QMessageBox.question(self, "Makro", "Uložit do sdílené knihovny (pro všechny)?",
                                          QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes
        p = save_macro(name.strip(), desc.strip(), copy_fragment(sc.sheet, eids), shared)
        self.lib_panel.refresh()
        self.statusBar().showMessage(f"Makro uloženo: {p}", 5000)

    def delete_macro(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        from envocad.library.macros import delete_macro, list_macros
        ms = [m for m in list_macros() if m.source != "vestavěné"]
        if not ms:
            QMessageBox.information(self, "Makro", "Žádná vlastní ani sdílená makra.")
            return
        name, ok = QInputDialog.getItem(self, "Smazat makro", "Makro:", [m.name for m in ms], 0, False)
        if ok and delete_macro(next(m for m in ms if m.name == name)):
            self.lib_panel.refresh()

    def insert_macro(self, path: str) -> None:
        """Dvojklik na makro v knihovně: vloží sestavu doprostřed viditelné části listu."""
        import json
        from pathlib import Path
        sc = self._active_schematic()
        if sc is None:
            QMessageBox.information(self, "Makro", "Makro jde vložit jen do schématu (JPS nebo jednopólová editace rozvaděče).")
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            QMessageBox.warning(self, "Makro", f"Makro se nepodařilo načíst: {path}")
            return
        c = self.view.mapToScene(self.view.viewport().rect().center()) if self.view else None
        at = (c.x(), -c.y()) if c is not None else None
        n = sc.insert_fragment(data.get("fragment", {}), at)
        self.statusBar().showMessage(f"Vloženo makro {data.get('name', '')} ({n} prvků)", 4000)

    def set_shared_library(self) -> None:
        from envocad.settings import load_settings, save_settings
        st = load_settings()
        d = QFileDialog.getExistingDirectory(self, "Sdílená knihovna (složka s *.json a *.csv)", st.get("shared_library_dir") or "")
        if not d:
            return
        st["shared_library_dir"] = d
        save_settings(st)
        n = self.library.sync_builtin()
        self.lib_panel.refresh()
        self.statusBar().showMessage(f"Sdílená knihovna: {d} (načteno, {n} nových značek)", 5000)

    def edit_standard(self) -> None:
        from envocad.settings import load_settings, save_settings
        st = load_settings()
        s = st["standard"]
        for key, label in (("author", "Zpracoval (výchozí)"), ("dc_cable", "DC kabel"), ("dc_cross", "DC průřez [mm²]"),
                           ("ac_cable", "AC kabel střídač–rozvaděč"), ("ac_cross", "AC průřez [mm²]"),
                           ("grid_cable", "Kabel do HDS"), ("grid_cross", "průřez do HDS [mm²]")):
            v, ok = QInputDialog.getText(self, "Firemní standard", label, text=str(s.get(key, "")))
            if not ok:
                return
            s[key] = v.strip()
        save_settings(st)
        self.statusBar().showMessage("Firemní standard uložen (~/.envocad/settings.json)", 4000)

    def new_project_wizard(self) -> None:
        if not self._confirm_discard():
            return
        from envocad.generate import build_project
        from envocad.ui.dialogs import ProjectWizard
        dlg = ProjectWizard(self, library=self.library)
        if dlg.exec() != ProjectWizard.Accepted:
            return
        from envocad.settings import apply_standard_to_spec
        try:
            project = build_project(apply_standard_to_spec(dlg.spec()))
        except Exception as ex:  # noqa: BLE001
            QMessageBox.warning(self, "Průvodce", f"Projekt se nepodařilo vygenerovat: {ex}")
            return
        self._load_project(project)
        self.statusBar().showMessage(f"Vygenerováno: {project.meta.get('p_installed_kwp')} kWp – zkontrolujte F7", 6000)

    def new_project_from_spec(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Specifikace projektu", "", "JSON (*.json)")
        if not path:
            return
        from envocad.generate import build_project, load_spec
        try:
            project = build_project(load_spec(path))
        except Exception as ex:  # noqa: BLE001
            QMessageBox.warning(self, "Specifikace", f"Projekt se nepodařilo vygenerovat: {ex}")
            return
        self._load_project(project)

    def compare_revision(self) -> None:
        """Změnový list z porovnání se starší verzí projektu."""
        path, _ = QFileDialog.getOpenFileName(self, "Starší revize projektu", "", "EnvoCAD projekt (*.ecp)")
        if not path:
            return
        from envocad.model.diff import diff_projects
        from envocad.ui.navigator import DiffDialog
        try:
            old = Project.load(path)
        except Exception as ex:  # noqa: BLE001
            QMessageBox.warning(self, "Porovnání", f"Soubor nejde načíst: {ex}")
            return
        changes = diff_projects(old, self.project)
        dlg = DiffDialog(changes, self.project, self)
        dlg.goto.connect(self.goto_target)
        if dlg.exec() == DiffDialog.Accepted and changes:
            text = dlg.change_text()
            cur = self.project.meta.get("changes", "")
            self.project.meta["changes"] = (cur + "\n" + text).strip() if cur else text
            self.project.meta["revision"] = dlg.rev.text().strip()
            self.undo.resetClean()
            self.statusBar().showMessage(f"Změnový list doplněn o {len(changes)} řádků", 4000)

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
        self._add_recent(self.project.path)
        self._clear_autosave()
        self.statusBar().showMessage(f"Uloženo: {self.project.path}", 3000)
        return True

    # ---- poslední projekty, autosave ------------------------------------------
    @staticmethod
    def _settings():
        from PySide6.QtCore import QSettings
        return QSettings("ENVO", "EnvoCAD")

    def _recent(self) -> list[str]:
        v = self._settings().value("files/recent", [])
        return [str(x) for x in (v if isinstance(v, list) else [v] if v else [])]

    def _add_recent(self, path) -> None:
        lst = [str(path)] + [x for x in self._recent() if x != str(path)]
        self._settings().setValue("files/recent", lst[:10])
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        if not hasattr(self, "m_recent"):
            return
        self.m_recent.clear()
        for p in self._recent():
            a = self.m_recent.addAction(p)
            a.triggered.connect(lambda _c=False, p=p: self.open_path(p))
        if self.m_recent.isEmpty():
            self.m_recent.addAction("(zatím nic)").setEnabled(False)

    def open_path(self, path: str) -> None:
        if not self._confirm_discard():
            return
        try:
            self._load_project(Project.load(path))
            self._add_recent(path)
        except Exception as ex:  # noqa: BLE001
            QMessageBox.critical(self, "Chyba", f"Projekt nelze otevřít:\n{ex}")

    def _autosave_path(self) -> Path:
        from envocad.library.store import home_dir
        d = home_dir() / "autosave"
        d.mkdir(parents=True, exist_ok=True)
        name = (self.project.path.stem if self.project.path else "nepojmenovany") + ".autosave.ecp"
        return d / name

    def autosave(self) -> None:
        if self.undo.isClean():
            return
        try:
            p = self._autosave_path()
            orig = self.project.path
            self.project.path = p
            self.project.save()
            self.project.path = orig
            (p.with_suffix(".orig")).write_text(str(orig or ""), encoding="utf-8")
            self._last_autosave = p
            log.info("autosave %s", p)
        except Exception as ex:  # noqa: BLE001
            log.warning("autosave selhal: %s", ex)

    def _clear_autosave(self) -> None:
        for p in {self._autosave_path(), getattr(self, "_last_autosave", None)}:
            if p is None:
                continue
            try:
                p.unlink(missing_ok=True)
                p.with_suffix(".orig").unlink(missing_ok=True)
            except OSError:
                pass

    def offer_recovery(self) -> None:
        """Po startu: pokud existuje automaticky uložená kopie, nabídne její obnovení."""
        from envocad.library.store import home_dir
        d = home_dir() / "autosave"
        if not d.exists():
            return
        files = sorted(d.glob("*.autosave.ecp"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not files:
            return
        f = files[0]
        orig_file = f.with_suffix(".orig")
        orig = orig_file.read_text(encoding="utf-8").strip() if orig_file.exists() else ""
        r = QMessageBox.question(self, "Obnova rozpracované práce",
                                 f"Byla nalezena automaticky uložená kopie projektu\n{orig or '(nepojmenovaný)'}.\n"
                                 "Obnovit ji? (Ne = kopie se smaže)", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if r == QMessageBox.Yes:
            try:
                proj = Project.load(f)
                proj.path = Path(orig) if orig else None
                self._load_project(proj)
                self.undo.resetClean()
            except Exception as ex:  # noqa: BLE001
                QMessageBox.warning(self, "Obnova", f"Kopii nejde načíst: {ex}")
        for x in files:
            x.unlink(missing_ok=True)
            x.with_suffix(".orig").unlink(missing_ok=True)

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
                           ("place", "Místo"), ("author", "Zpracoval"), ("date", "Datum"), ("revision", "Revize"),
                           ("changes", "Změnový list (řádek = revize | datum | popis | zpracoval)")]:
            cur = self.project.name if key == "name" else self.project.meta.get(key, "")
            if key == "changes":
                val, ok = QInputDialog.getMultiLineText(self, "Vlastnosti projektu", label, cur)
            else:
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

    def export_pdf(self, paper: str = "") -> None:
        from envocad.export.pdf_export import export_scene_pdf
        sc = self.scene or (self.view.scene() if isinstance(self.view, DERIVED_VIEWS) else None)
        if not sc:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", "", "PDF (*.pdf)")
        if path:
            export_scene_pdf(sc, path, paper=paper or None)
            self.statusBar().showMessage(f"Exportováno: {path}", 3000)

    def export_xlsx(self, current_only: bool) -> None:
        from envocad.export.xlsx_export import export_reports_xlsx
        sh = self.current_sheet if current_only else None
        base = (sh.name if sh else self.project.name).replace("/", "-")
        path, _ = QFileDialog.getSaveFileName(self, "Výkazy", f"{base} – výkazy.xlsx", "Excel (*.xlsx)")
        if path:
            export_reports_xlsx(self.project, self.library, path, sh)
            self.statusBar().showMessage(f"Exportováno: {path}", 3000)

    def export_documentation(self) -> None:
        from envocad.export.doc_pdf import export_documentation_pdf
        base = self.project.name.replace("/", "-") or "dokumentace"
        path, _ = QFileDialog.getSaveFileName(self, "Celá dokumentace", f"{base} – dokumentace.pdf", "PDF (*.pdf)")
        if path:
            n = export_documentation_pdf(self.project, self.library, path)
            self.statusBar().showMessage(f"Exportováno {n} stran: {path}", 5000)

    def export_labels_csv(self) -> None:
        """Štítky pro Brady/Partex apod.: CSV se středníkem, UTF-8 s BOM (Excel/tiskárna to otevře přímo)."""
        import csv

        from envocad.export import reports
        path, _ = QFileDialog.getSaveFileName(self, "Štítky", "stitky.csv", "CSV (*.csv)")
        if not path:
            return
        head, rows = reports.labels(self.project, self.library, None)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(head)
            w.writerows(rows)
        self.statusBar().showMessage(f"Exportováno {len(rows)} štítků: {path}", 3000)

    def export_tz(self) -> None:
        from envocad.export.tz_export import export_tz_docx
        base = self.project.name.replace("/", "-") or "projekt"
        path, _ = QFileDialog.getSaveFileName(self, "Technická zpráva", f"{base} – TZ.docx", "Word (*.docx)")
        if path:
            export_tz_docx(self.project, self.library, path)
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

    def browse_components(self) -> None:
        from envocad.ui.component_picker import ComponentPicker
        dlg = ComponentPicker(self.library, parent=self, title="Knihovna artiklů")
        dlg.only_compatible.setCurrentIndex(1)
        dlg.exec()

    def import_components_csv(self) -> None:
        from envocad.library.components import validate
        path, _ = QFileDialog.getOpenFileName(self, "Import artiklů z CSV", "", "CSV (*.csv)")
        if not path:
            return
        known = {s[0] for s in self.library.list_symbols()}
        errs = validate(path, known)
        if errs:
            QMessageBox.warning(self, "Import artiklů", "CSV má chyby (viz docs/COMPONENTS.md):\n\n" + "\n".join(errs[:20]))
            return
        n = self.library.import_components_csv_v2(path)
        QMessageBox.information(self, "Import artiklů", f"Načteno {n} artiklů.")

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
