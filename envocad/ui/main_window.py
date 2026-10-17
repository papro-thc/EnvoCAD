"""Hlavní okno EnvoCAD."""
from __future__ import annotations

import logging
import os
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
from envocad.ui.notes_panel import NotesPanel
from envocad.ui.terminal_plan_view import TerminalPlanScene, TerminalPlanView

DERIVED_VIEWS = (MultipoleView, TerminalPlanView)  # pohledy odvozené z modelu – po změně se přestaví
from envocad.ui.panels import LibraryPanel, PropertiesPanel

FILE_FILTER = "Projekt EnvoCAD (*.ecp)"
REJECTED_AUTOSAVE_DIR = "odmitnute"   # podsložka autosave pro kopie, které uživatel při startu odmítl obnovit
REJECTED_KEEP_DAYS = 30
log = logging.getLogger("envocad.ui")


def error_text(ex: BaseException) -> str:
    """Česky srozumitelný popis chyby souboru (uložení, otevření, import)."""
    import errno
    import xml.etree.ElementTree as ET
    import zipfile
    if isinstance(ex, ET.ParseError):
        line, col = getattr(ex, "position", (0, 0)) or (0, 0)
        return f"soubor není platné XML (chyba na řádku {line}, sloupci {col + 1})"
    if isinstance(ex, zipfile.BadZipFile):
        return "soubor není platný archiv ZIP/EDZ (poškozený nebo jiný formát)"
    if isinstance(ex, UnicodeDecodeError):
        return "soubor má neznámé kódování textu (čekám UTF-8)"
    if isinstance(ex, OSError) and not isinstance(ex, ValueError):
        what = {errno.ENOENT: "soubor nebo složka neexistuje", errno.EACCES: "chybí oprávnění",
                errno.EPERM: "chybí oprávnění", errno.ENOSPC: "na disku není místo", errno.EROFS: "disk je jen pro čtení",
                errno.EFBIG: "soubor je příliš velký (kvóta / plný disk)", errno.EISDIR: "cesta je složka",
                errno.EDQUOT: "překročena kvóta disku"}.get(ex.errno or 0)
        if what:
            return f"{what} ({ex.filename or ''})".replace(" ()", "")
        return f"chyba souboru: {ex.strerror or ex}"
    return str(ex) or type(ex).__name__


def free_symbol_id(library, sid: str) -> str:
    """První volné ID ve tvaru `<sid>_2`, `<sid>_3`…"""
    n = 2
    while library.has_symbol(f"{sid}_{n}"):
        n += 1
    return f"{sid}_{n}"


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
        self.notes_panel = NotesPanel()
        self.notes_panel.goto_note.connect(self.goto_note)
        self.nav_tabs = QTabWidget()          # dock Navigátor: Prvky | Připomínky
        self.nav_tabs.addTab(self.nav_panel, "Prvky")
        self.nav_tabs.addTab(self.notes_panel, "Připomínky")
        self._dock("Navigátor", self.nav_tabs, Qt.LeftDockWidgetArea)
        self._dock("Vlastnosti", self.props_panel, Qt.RightDockWidgetArea)
        self.setStatusBar(QStatusBar())
        self._build_actions()
        self._load_plugins()
        import uuid
        self._autosave_token = uuid.uuid4().hex[:8]   # nepojmenovaný projekt: vlastní autosave pro každé okno
        # autosave patřící TOMUTO oknu: poslední zapsaná kopie a obnovená kopie (z ní okno vzniklo). Okno maže jen
        # tyto soubory – kopie jiného okna / procesu se stejným projektem se nikdy nedotkne.
        self._last_autosave: Path | None = None
        self._recovered_autosave: Path | None = None
        try:
            self._load_project(self.project)
        except Exception as ex:
            log.exception("projekt nejde zobrazit")
            QMessageBox.critical(self, "Projekt nelze otevřít",
                                 f"Projekt nelze otevřít:\n{ex}\n\nEnvoCAD se spustí s prázdným projektem.")
            self._load_project(Project())
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

    @property
    def draw_scene(self):
        """Scéna, do které jde kreslit (vkládat prvky, vodiče): JPS / jednopólová editace i schéma rozvaděče (vícepól)."""
        v = self.view
        sc = v.scene() if isinstance(v, SchematicView) else None
        return sc if sc is not None and hasattr(sc, "start_place") else None

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
        act(m_file, "Uzavřít revizi", self.close_revision_all)
        act(m_file, "Uzavřít revizi listu", self.close_revision_sheet)
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
        act(m_edit, "Otočit o 90°", lambda: self.draw_scene and self.draw_scene.rotate_selected(), "R")
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
        act(m_draw, "Vodič (W)", lambda: self.draw_scene and self.draw_scene.start_wire(), None, True)
        act(m_draw, "Výběr (Esc)", lambda: self.draw_scene and self.draw_scene.set_mode(Mode.SELECT), None, True)
        self.act_note = act(m_draw, "Připomínka", self.start_note, "Ctrl+Shift+P", True)

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
        self.act_notes = QAction("Připomínky", self, checkable=True)
        self.act_notes.setChecked(self._notes_visible_setting())
        self.act_notes.toggled.connect(self.set_notes_visible)
        m_view.addAction(self.act_notes)

        m_proj = mb.addMenu("&Projekt")
        act(m_proj, "Strukturní označení…", self.edit_structures)

        m_sheet = mb.addMenu("&List")
        act(m_sheet, "Nový list schématu", self.new_schematic_sheet)
        act(m_sheet, "Vlastnosti listu (název, =funkce, +umístění)…", self.rename_sheet)
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
        act(m_out, "Výrobní data rozvaděče (xlsx)…", self.export_production)
        act(m_out, "Protokol kusového ověření (docx)…", self.export_routine_test)
        act(m_out, "Technická zpráva (docx)…", self.export_tz)
        act(m_out, "Štítky pro tiskárnu (CSV)…", self.export_labels_csv)
        m_out.addSeparator()
        self.act_export_notes = QAction("Přidávat připomínky do exportu", self, checkable=True)
        self.act_export_notes.setChecked(self._export_notes())
        self.act_export_notes.toggled.connect(lambda on: self._settings().setValue("export/notes", bool(on)))
        m_out.addAction(self.act_export_notes)
        m_out.addSeparator()
        act(m_out, "Celá dokumentace (PDF)…", self.export_documentation, "Ctrl+Shift+E", True)

        m_lib = mb.addMenu("&Knihovna")
        act(m_lib, "Importovat symbol z DXF…", self.import_dxf_symbol)
        act(m_lib, "Importovat značku z QElectroTech (.elmt)…", self.import_qet_symbol)
        act(m_lib, "Prohlížet artikly…", self.browse_components)
        act(m_lib, "Importovat artikly z CSV…", self.import_components_csv)
        act(m_lib, "Importovat artikly z EPLAN (XML / CSV / ZIP)…", self.import_eplan)
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
        from envocad.plugins import failed_message
        msg = failed_message(self.plugins)
        if msg:   # až po startu (app.py hned po vytvoření okna ukazuje cestu k logu)
            log.warning(msg)
            QTimer.singleShot(0, lambda: self.statusBar().showMessage(msg, 20_000))
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
    def _verify_project(self, project: Project) -> int:
        """Ověří, že jde projekt zobrazit (značky, porty vodičů), dřív než se okno přepne. Chyba → ValueError
        s listem a prvkem. Vrací počet prvků se zástupnou (neznámou) značkou."""
        from envocad.model.project import element_symbol
        unknown = 0
        for sheet in project.sheets:
            syms = {}
            for e in sheet.elements:
                try:
                    syms[e.id] = sym = element_symbol(project, e, self.library)
                    sym.bounds()
                except Exception as ex:
                    raise ValueError(f"list „{sheet.name}“, prvek {e.ref or e.symbol_id} ({e.id}): {ex}") from ex
                unknown += sym.placeholder
            for w in sheet.wires:
                for end in (w.a, w.b):
                    sym = syms.get(end.element_id)
                    if sym is None:
                        continue   # vodič na neexistující prvek se nekreslí, kontrola ho hlásí
                    e = sheet.element(end.element_id)
                    try:
                        e.port_pos(sym, end.port)
                    except Exception as ex:
                        raise ValueError(f"list „{sheet.name}“, vodič {w.attrs.get('ref') or w.id} na prvek "
                                         f"{e.ref or e.symbol_id}: {ex}") from ex
        return unknown

    def _load_project(self, project: Project) -> None:
        """Zobrazí projekt. Nejdřív ověří projekt a postaví scény do dočasných objektů; okno (projekt, záložky,
        undo) se přepne až po úspěchu. Při chybě vyhodí výjimku s listem a prvkem a okno zůstane beze změny."""
        from envocad.model.project import sync_cables, sync_feed_links
        built = []
        try:
            sync_feed_links(project)
            sync_cables(project)
            unknown = self._verify_project(project)
            for sheet in project.sheets:
                try:
                    built.append(self._build_tab(project, sheet, "schematic"))
                except Exception as ex:
                    raise ValueError(f"list „{sheet.name}“ nejde zobrazit: {ex}") from ex
        except Exception:
            for widget, _view, _scene, _title in built:
                widget.deleteLater()
            raise
        self._clear_autosave()   # předchozí projekt byl uložen nebo zahozen (`_confirm_discard`) – jeho kopie okna pryč
        self.project = project
        self.nav_panel.set_project(project)
        self.notes_panel.set_project(project, self.undo)
        # undo-reset-ok: načtení projektu (otevření, nový, obnova autosave) – historie patří předchozímu projektu
        self.undo.clear()
        while self.tabs.count():
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            w.deleteLater()
        self._scenes.clear()
        self._closed_sheet_tabs: dict[str, list[str]] = {}   # druhy záložek smazaných listů (undo je obnoví)
        if not self._panels_wired:
            self.lib_panel.symbol_chosen.connect(lambda sid: self.draw_scene and self.draw_scene.start_place(sid))
            self.lib_panel.macro_chosen.connect(self.insert_macro)
            self.props_panel.attr_edited.connect(lambda *a: self.scene and self.scene.set_attr(*a))
            self._panels_wired = True
        for tab in built:
            self._add_tab(*tab)
        self.tabs.setCurrentIndex(0)
        self.props_panel.show_item(None)
        self._update_title()
        if self.view:
            self.view.zoom_fit()
        if unknown:
            self.statusBar().showMessage(f"Projekt obsahuje neznámé značky ({unknown}×) – kreslí se jako „?“, "
                                         "viz Kontrola projektu (F7)", 15_000)

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
        self._add_tab(*self._build_tab(self.project, sheet, kind))

    def _build_tab(self, project: Project, sheet: Sheet, kind: str):
        """Postaví pohled listu (scéna + view + případný boční panel) bez přidání záložky:
        (widget, view, scene, title). Chyba při stavbě okno nezmění."""
        if kind == "layout":
            from envocad.ui.dialogs import EnclosurePanel
            scene = LayoutScene(project, sheet, self.library, self.undo)
            view = LayoutView(scene)
            # panel model sám nemění – změna jde přes SetLayoutCommand (přestavbu pohledů dělá příkaz, i při undo)
            panel = EnclosurePanel(sheet, library=self.library, project=project,
                                   commit=lambda b, a, k, sh=sheet: self.commit_layout(sh, b, a, k))
            scene.layout_changed.connect(panel.refresh)
            scene.enclosure_requested.connect(lambda p=panel: p.name.setFocus())
            scene.selection_info.connect(lambda it: self.props_panel.show_item(
                self._element_item_for(sheet, it.element.id) if it else None))
            view.side_panel = panel
            title = f"{sheet.name} – rozložení"
        elif kind == "multipole":
            scene = MultipoleScene(project, sheet, self.library, self.undo)
            view = MultipoleView(scene)
            scene.selection_info.connect(lambda it: self.props_panel.show_item(
                self._element_item_for(sheet, it.element.id) if it is not None and hasattr(it, "element") else None))
            scene.edit_element_requested.connect(lambda eid, sh=sheet: self._edit_element_anywhere(sh, eid))
            scene.delete_requested.connect(lambda eids, wids, sh=sheet: self._delete_anywhere(sh, eids, wids))
            scene.mode_changed.connect(self._show_mode)
            scene.after_edit = lambda sh=sheet: self._rebuild_peer(sh, "schematic")
            title = f"{sheet.name} – schéma" if sheet.is_switchboard else f"{sheet.name} – vícepól"
        elif kind == "terminals":
            scene = TerminalPlanScene(project, sheet, self.library, self.undo)
            view = TerminalPlanView(scene)
            title = f"{sheet.name} – svorkovnice"
        else:
            scene = SchematicScene(project, sheet, self.library, self.undo)
            view = SchematicView(scene)
            scene.selection_info.connect(self.props_panel.show_item)
            scene.attrs_changed.connect(lambda _id: self.props_panel.show_item(self._selected_item()))
            scene.mode_changed.connect(self._show_mode)
            scene.open_switchboard.connect(self.open_switchboard_from_block)
            scene.ask_delete_block_sheets = self._ask_delete_block_sheets
            scene.sheet_presence_changed = self._sheet_presence_changed
            scene.notes_visible = self._notes_visible_setting()
            scene.rebuild_notes()
            title = sheet.name if not sheet.is_switchboard else f"{sheet.name} – jednopól (editace)"
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
        return widget, view, scene, title

    def _add_tab(self, widget, view, scene, title: str) -> None:
        self._scenes.append(scene)  # držet referenci – scéna musí přežít stejně dlouho jako pohled
        idx = self.tabs.addTab(widget, title)
        self.tabs.setCurrentIndex(idx)
        view.zoom_fit()

    def _rebuild_peer(self, sheet: Sheet, kind: str) -> None:
        i = self._find_tab(sheet, kind)
        if i >= 0:
            self._unwrap(self.tabs.widget(i)).scene().rebuild()

    def _edit_element_anywhere(self, sheet: Sheet, eid: str) -> None:
        """Parametry prvku z odvozeného pohledu: dialog jde přes JPS scénu listu (otevře se skrytě, záložka zůstane)."""
        cur = self.tabs.currentIndex()
        sc = self._jps_scene(sheet)
        if sc is None:
            self.open_sheet(sheet, "schematic")
            sc = self._jps_scene(sheet)
            self.tabs.setCurrentIndex(cur)
        if sc is not None:
            if eid not in sc.element_items:
                sc.rebuild()
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
        if self.current_sheet is not None:
            self.notes_panel.set_current_sheet(self.current_sheet.id)
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
        self.undo.push(commands.AddSheetCommand(self.project, sheet, on_change=self._sheet_presence_changed))
        self.open_sheet(sheet)

    def _close_sheet_tabs(self, sheet: Sheet) -> list[str]:
        """Zavře všechny záložky listu (i poslední – smazaný list nesmí zůstat zobrazený); vrátí jejich druhy."""
        kinds = []
        for i in reversed(range(self.tabs.count())):
            w = self._unwrap(self.tabs.widget(i))
            if w.scene().sheet is sheet:
                kinds.insert(0, self._kind_of(w))
                tab = self.tabs.widget(i)
                self.tabs.removeTab(i)
                tab.deleteLater()   # scéna zůstává v self._scenes – nesmí zaniknout dřív než (odložené) smazání pohledu
        return kinds

    def _sheet_presence_changed(self, sheet: Sheet, present: bool) -> None:
        """Příkazy přidání / smazání listu (redo i undo): záložky listu se zavřou a při návratu listu obnoví
        (stejné druhy pohledů); nadřazený list (blok ROZVADĚČ) a vazby se přepočítají."""
        from envocad.model.project import parent_sheet
        closed = self._closed_sheet_tabs
        if present:
            for kind in closed.pop(sheet.id, []):
                self.open_sheet(sheet, kind)
        else:
            kinds = self._close_sheet_tabs(sheet)
            if kinds:
                closed[sheet.id] = kinds
            if self.tabs.count() == 0 and self.project.sheets:
                self.open_sheet(self.project.sheets[0])
        ps = parent_sheet(self.project, sheet) if sheet.parent_element_id else None
        if ps is not None:
            self._rebuild_sheet_views(ps)   # blok dostane porty podle listu, nebo osiřelé porty „X1?“
        else:
            self._sync_links_and_blocks()
        for s in self.project.sheets:       # listy rozvaděčů odpojené / připojené k bloku na tomto listu
            if s.parent_element_id and any(e.id == s.parent_element_id for e in sheet.elements):
                self._rebuild_sheet_views(s)
        self._refresh_tab_titles()

    def rename_sheet(self) -> None:
        """Vlastnosti listu: název a strukturní označení (=funkce, +umístění)."""
        sh = self.current_sheet
        if not sh:
            return
        from envocad.ui.dialogs import SheetPropsDialog
        dlg = SheetPropsDialog(sh, self)
        if dlg.exec() != SheetPropsDialog.Accepted:
            return
        self.set_sheet_props(sh, *dlg.values())

    def set_sheet_props(self, sh: Sheet, name: str, func: str, loc: str) -> bool:
        """Název a označení listu jako jeden krok undo (makro). False = neplatný kód, nic se nezmění."""
        rename = bool(name) and name != sh.name
        designate = (func, loc) != (sh.func, sh.loc)
        if not (rename or designate):
            return True
        if designate and not self._valid_sheet_codes(sh, func, loc):
            return False
        self.undo.beginMacro("Vlastnosti listu")
        if designate:
            self.set_sheet_designation(sh, func, loc)
        if rename:
            self.undo.push(commands.RenameSheetCommand(sh, sh.name, name, on_change=self._refresh_tab_titles))
        self.undo.endMacro()
        return True

    def _valid_sheet_codes(self, sh: Sheet, func: str, loc: str) -> bool:
        from envocad.model.designation import FUNC, LOC, validate_code
        for aspect, code in ((FUNC, func), (LOC, loc)):
            issues = validate_code(code, aspect, f"listu {sh.name}")
            if issues:
                QMessageBox.warning(self, "Označení listu", issues[0].text)
                return False
        return True

    def set_sheet_designation(self, sh: Sheet, func: str, loc: str) -> bool:
        """=funkce / +umístění listu přes undo; nový kód se zapíše i do registru. False = neplatný kód."""
        from envocad.model.designation import FUNC, LOC
        from envocad.model.project import StructureId
        if (func, loc) == (sh.func, sh.loc):
            return True
        if not self._valid_sheet_codes(sh, func, loc):
            return False
        self.undo.beginMacro("Změnit označení listu")
        self.undo.push(commands.SetSheetDesignationCommand(sh, (sh.func, sh.loc), (func, loc)))
        old_list = list(self.project.structures)
        new_list = list(old_list)
        for aspect, code in ((FUNC, func), (LOC, loc)):
            if code and self.project.structure(aspect, code) is None:
                new_list.append(StructureId(aspect, code))
        if len(new_list) != len(old_list):
            self.undo.push(commands.SetStructuresCommand(self.project, old_list, new_list))
        self.undo.endMacro()
        return True

    def edit_structures(self) -> None:
        from envocad.ui.dialogs import StructuresDialog
        dlg = StructuresDialog(self.project.structures, self)
        if dlg.exec() == StructuresDialog.Accepted:
            self.set_structures(dlg.values())

    def set_structures(self, new_list: list) -> None:
        old = self.project.structures
        key = lambda lst: [(x.aspect, x.code, x.description) for x in lst]
        if key(old) != key(new_list):
            self.undo.push(commands.SetStructuresCommand(self.project, old, new_list))

    def _ask_delete_block_sheets(self, sheets: list) -> bool:
        """Mazání bloku ROZVADĚČ: smazat i list rozvaděče? (Ano = jeden krok undo s blokem.)"""
        names = ", ".join(f"„{s.name}“" for s in sheets)
        word = "list" if len(sheets) == 1 else "listy"
        r = QMessageBox.question(
            self, "Smazat rozvaděč",
            f"Mazaný blok ROZVADĚČ má {word} {names}.\n\nSmazat i {word} rozvaděče se vším obsahem?\n"
            f"(Ne = {word} zůstane bez bloku, Kontrola projektu ho ohlásí.)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        return r == QMessageBox.Yes

    def delete_sheet(self) -> None:
        """Odstraní aktuální list (s potvrzením). List rozvaděče: blok ROZVADĚČ v JPS zůstane a vodiče na jeho porty
        zůstanou na portech „X1?“ (hlásí je kontrola); listy rozvaděčů s blokem na mazaném listu se odpojí."""
        from envocad.model.project import parent_sheet
        sh = self.current_sheet
        if not sh or len(self.project.sheets) <= 1:
            return
        text = f"Opravdu odstranit list „{sh.name}“ se vším obsahem?"
        ps = parent_sheet(self.project, sh) if sh.is_switchboard else None
        if ps is not None:
            block = ps.element(sh.parent_element_id)
            n = sum(1 for w in ps.wires if w.touches(block.id))
            text = (f"„{sh.name}“ je list rozvaděče {block.ref or ''} (blok ROZVADĚČ na listu „{ps.name}“).\n\n"
                    "Odstranit list rozvaděče se vším obsahem?\n\nBlok ROZVADĚČ v jednopólovém schématu zůstane"
                    + (f" a {n} vodič(ů) na něm zůstane připojeno na portech označených „?“ (ukáže je Kontrola projektu)."
                       if n else "."))
        ids = {e.id for e in sh.elements}
        children = [s.name for s in self.project.sheets if s.parent_element_id in ids]
        if children:
            text += ("\n\nListy rozvaděčů, jejichž blok je na tomto listu, zůstanou bez nadřazeného bloku: "
                     + ", ".join(f"„{c}“" for c in children) + ".")
        if QMessageBox.question(self, "Odstranit list", text) != QMessageBox.Yes:
            return
        self.undo.push(commands.DeleteSheetCommand(self.project, sh, on_change=self._sheet_presence_changed))

    # ---- rozvaděče -------------------------------------------------------------
    def open_switchboard_from_block(self, block_id: str, kind: str = "schematic") -> None:
        # signál přichází z obsluhy dvojkliku ve scéně – dialogy a přepínání záložek odložit až po ní
        QTimer.singleShot(0, lambda: self._open_switchboard_now(block_id, kind))

    def _open_switchboard_now(self, block_id: str, kind: str) -> None:
        sheet_of_block = self.project.sheet_of_element(block_id)
        if not sheet_of_block:
            return
        block = sheet_of_block.element(block_id)
        sheet = self.project.switchboard_sheet(block_id)
        if sheet is None:
            # nový list rozvaděče + volitelná šablona = jeden krok undo
            self.undo.beginMacro(f"Nový list rozvaděče {block.ref}".strip())
            try:
                sheet = self.create_switchboard_sheet(block)
                self._choose_template(sheet)
            finally:
                self.undo.endMacro()
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

    def create_switchboard_sheet(self, block) -> Sheet:
        """Založí list rozvaděče pro blok ROZVADĚČ přes undo (`AddSheetCommand`: list, atribut „sheet“ bloku,
        +umístění v registru struktur). Existující list vrátí beze změny."""
        existing = self.project.switchboard_sheet(block.id)
        if existing is not None:
            return existing
        p = self.project
        attr_before = block.attrs.get("sheet")
        structs_before = list(p.structures)
        sheet = p.create_switchboard_sheet(block)       # model připraví list; změny se vrátí a provede je příkaz
        attr_after, structs_after = block.attrs.get("sheet"), list(p.structures)
        p.sheets.remove(sheet)
        p.structures = structs_before
        if attr_before is None:
            block.attrs.pop("sheet", None)
        else:
            block.attrs["sheet"] = attr_before
        self.undo.push(commands.AddSheetCommand(p, sheet, on_change=self._sheet_presence_changed,
                                                block_attr=(block, attr_before, attr_after),
                                                structures=(structs_before, structs_after),
                                                text=f"Nový list rozvaděče {sheet.name}"))
        return sheet

    def _ask_template(self) -> tuple[str, dict[str, str]] | None:
        """Výběr šablony a jejích parametrů: (id, parametry), nebo None (zrušeno)."""
        from envocad.library.templates import TEMPLATES
        names = [t.name for t in TEMPLATES]
        name, ok = QInputDialog.getItem(self, "Šablona rozvaděče", "Nový list rozvaděče – vložit šablonu:", names, 0, False)
        if not ok:
            return None
        t = next(t for t in TEMPLATES if t.name == name)
        params = {}
        for tp in t.params:
            v, ok = QInputDialog.getText(self, t.name, tp.label, text=tp.default)
            if not ok:
                return None
            params[tp.key] = v
        return t.id, params

    def _choose_template(self, sheet: Sheet) -> bool:
        chosen = self._ask_template()
        if chosen is None:
            return False
        return self.apply_template(sheet, *chosen)

    def apply_template(self, sheet: Sheet, tid: str, params: dict[str, str]) -> bool:
        """Vloží šablonu jako jeden krok undo (`SheetsStateCommand`): prvky, vodiče, rozmístění, můstky listu
        rozvaděče i navázání přívodu na vodič nadřazeného listu. Neplatný parametr (ValueError šablony) = hláška,
        nic se nevloží (list i projekt zůstanou beze změny); vrací False."""
        from envocad.library.templates import apply_template, template
        before = commands.sheets_state(self.project)
        try:
            apply_template(self.project, sheet, tid, params)
        except ValueError as ex:
            commands.restore_sheets_state(self.project, before)
            QMessageBox.warning(self, "Šablona", f"Šablonu nelze vložit: {ex}")
            return False
        after = commands.sheets_state(self.project)
        commands.restore_sheets_state(self.project, before)
        self.undo.push(commands.SheetsStateCommand(self.project, before, after, f"Šablona {template(tid).name}",
                                                   on_change=self._sheets_changed))
        return True

    def _sheets_changed(self, sheet_ids: list[str]) -> None:
        """Po `SheetsStateCommand`: přestaví pohledy změněných listů (prvky a vodiče jsou nové objekty). Nejdřív se
        přestaví všechny scény, až potom porty bloků ROZVADĚČ – staré položky vodičů by mířily na neplatné porty."""
        from envocad.model.project import sync_cables, sync_feed_links
        sync_feed_links(self.project)
        sync_cables(self.project)
        for i in range(self.tabs.count()):
            w = self._unwrap(self.tabs.widget(i))
            if w.scene().sheet.id in sheet_ids:
                w.scene().rebuild()
                if getattr(w, "side_panel", None) is not None:
                    w.side_panel.load_from_model()
        self._sync_links_and_blocks()
        self._refresh_tab_titles()

    def insert_template(self) -> None:
        sh = self.current_sheet
        if not sh or not sh.is_switchboard:
            QMessageBox.information(self, "Šablona", "Šablonu lze vložit jen do listu rozvaděče.")
            return
        if sh.elements and QMessageBox.question(
                self, "Šablona",
                f"List „{sh.name}“ už obsahuje {len(sh.elements)} prvků. Šablona přidá další přístroje a vodiče "
                "a rozmístí je do rozložení od první řady – mohou se překrývat s už rozmístěnými přístroji "
                "(upravte rozložení ručně).\n\nPřesto vložit šablonu?") != QMessageBox.Yes:
            return
        self._choose_template(sh)

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
        from envocad.ui.dialogs import EnclosureDialog, EnclosurePanel
        dlg = EnclosureDialog(sh, self, library=self.library, project=self.project)
        if dlg.exec() != EnclosureDialog.Accepted:
            return    # dialog pracoval na kopii rozložení – Zrušit nic nemění
        before, after = sh.layout.to_dict(), dlg.apply().to_dict()
        if EnclosurePanel.real_change(before, after):   # OK beze změny = bez kroku
            self.commit_layout(sh, before, after)

    def commit_layout(self, sheet: Sheet, before: dict, after: dict, key: str | None = None) -> None:
        """Změna skříně / rozložení jako `SetLayoutCommand`; `key` = pole panelu (po sobě jdoucí změny téhož pole
        se slučují do jednoho kroku)."""
        if before == after:
            return
        self.undo.push(commands.SetLayoutCommand(sheet, before, after, "Skříň rozvaděče",
                                                 on_change=self._layout_changed, merge_key=key))

    def _layout_changed(self, sheet: Sheet) -> None:
        """Po `SetLayoutCommand` (i undo/redo): pohledy listu, titulky a pole panelu skříně podle modelu."""
        self._rebuild_sheet_views(sheet)
        self._refresh_tab_titles()
        for i in range(self.tabs.count()):
            w = self._unwrap(self.tabs.widget(i))
            if w.scene().sheet is sheet and getattr(w, "side_panel", None) is not None:
                w.side_panel.load_from_model()

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
               Mode.WIRE: "Vodič – klikněte na port, pak na druhý port",
               Mode.NOTE: "Připomínka – klik = bod, tah = obdélník, Esc/pravé tl. ukončí"}[mode]
        self.statusBar().showMessage(txt)

    def _on_undo_changed(self, _value=None) -> None:
        self._update_title()
        self._sync_links_and_blocks()
        self._refresh_tab_titles()   # název listu se mění i navázaně (přejmenování bloku rozvaděče)
        self.nav_panel._schedule()
        self.notes_panel.refresh()
        for sc in self._scenes:   # popisky (označení, aspekty) a značky revize se po změně modelu přepočítají
            if hasattr(sc, "invalidate_text_layout"):
                sc.invalidate_text_layout()
                sc.update()
            if hasattr(sc, "rebuild_notes"):   # undo/redo/panel mění Project.notes mimo scénu
                sc.rebuild_notes()
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

    def goto_note(self, sheet_id: str, note_id: str) -> None:
        """Skok na připomínku: přepne list, zapne zobrazení připomínek, vybere ji a vycentruje pohled."""
        sheet = next((s for s in self.project.sheets if s.id == sheet_id), None)
        if sheet is None:
            return
        if not self.act_notes.isChecked():
            self.act_notes.setChecked(True)
        self.open_sheet(sheet, "schematic")
        sc = self.scene
        it = sc.note_items.get(note_id) if sc is not None else None
        if it is None:
            return
        sc.clearSelection()
        it.setSelected(True)
        self.view.centerOn(it)

    def start_note(self) -> None:
        """Nástroj Připomínka: zapne zobrazení připomínek (jinak by nová nebyla vidět) a přepne do režimu."""
        sc = self._active_schematic()
        if sc is None:
            return
        if not self.act_notes.isChecked():
            self.act_notes.setChecked(True)
        sc.start_note()

    def _notes_visible_setting(self) -> bool:
        return str(self._settings().value("view/notes", False)).lower() in ("true", "1")

    def _export_notes(self) -> bool:
        return str(self._settings().value("export/notes", False)).lower() in ("true", "1")

    def set_notes_visible(self, on: bool) -> None:
        """Zobrazit → Připomínky: zapne/vypne připomínky ve všech schématech (QSettings `view/notes`)."""
        self._settings().setValue("view/notes", bool(on))
        for sc in self._scenes:
            if hasattr(sc, "set_notes_visible"):
                sc.set_notes_visible(bool(on))

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
        for i in range(self.tabs.count()):
            sc = self._unwrap(self.tabs.widget(i)).scene()
            if isinstance(sc, SchematicScene):
                sc.invalidate_xrefs()
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
        changes = dlg.all_values()   # rozpracované můstky všech svorkovnic dialogu – jeden krok undo
        if not changes:
            return
        if len(changes) > 1:
            self.undo.beginMacro("Můstky " + ", ".join(changes))
        try:
            for strip, groups in changes.items():
                self.undo.push(commands.SetBridgesCommand(self.project, sh, strip,
                                                          self.project.bridge_groups(strip, sh), groups))
        finally:
            if len(changes) > 1:
                self.undo.endMacro()

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
        # Zahodit: kopie se smaže až po úspěšném otevření jiného projektu (`_load_project`) nebo zavření okna
        # (`closeEvent`) – když otevření selže, okno zůstane s neuloženou prací a ta musí být dál na disku.
        return r == QMessageBox.Discard

    def new_project(self) -> None:
        if self._confirm_discard():
            from envocad.settings import load_settings
            st = load_settings()["standard"]
            p = Project()
            p.meta.update({k: str(v) for k, v in (st.get("project_meta") or {}).items()})
            if st.get("author"):
                p.meta.setdefault("author", st["author"])
            self._load_project(p)   # prázdný nový projekt bez změn zůstane čistý

    def _mark_new_project_dirty(self) -> None:
        """Projekt z průvodce / ze specifikace ještě není uložený: zavření se zeptá a autosave běží. Čistý stav
        se zahodí (clean index -1) – na rozdíl od kroku undo ho uživatel nemůže omylem „vrátit“ do čistého stavu."""
        # undo-reset-ok: nový projekt (po založení) – neuložený stav, kterého undo nedosáhne
        self.undo.resetClean()

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
        """Dvojklik na makro v knihovně: má-li proměnné, zeptá se na hodnoty; vloží sestavu doprostřed pohledu."""
        from pathlib import Path

        from envocad.library.macros import load_macro, resolve_values
        from envocad.ui.dialogs import MacroValuesDialog
        sc = self._active_schematic() or self.draw_scene
        if sc is None:
            QMessageBox.information(self, "Makro", "Makro jde vložit jen do schématu (JPS nebo jednopólová editace rozvaděče).")
            return
        m = load_macro(Path(path))
        if m is None:
            QMessageBox.warning(self, "Makro", f"Makro se nepodařilo načíst (nebo je z novější verze programu): {path}")
            return
        if m.has_parameters:
            dlg = MacroValuesDialog(m, self.library, parent=self, project=self.project, sheet=sc.sheet)
            if not dlg.exec():
                return
            values = dlg.values()
        else:
            values, errs = resolve_values(m, components=self.library.component)
            if errs:
                QMessageBox.warning(self, "Makro", "\n".join(errs))
                return
        c = self.view.mapToScene(self.view.viewport().rect().center()) if self.view else None
        at = (c.x(), -c.y()) if c is not None else None
        try:
            n = sc.insert_macro(m, values, at)
        except ValueError as ex:
            QMessageBox.warning(self, "Makro", str(ex))
            return
        if n == 0:
            self.statusBar().showMessage("Makro nevložilo žádné prvky (počet 0)", 5000)
            return
        self.statusBar().showMessage(f"Vloženo makro {m.name} ({n} prvků)", 4000)

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
        self._mark_new_project_dirty()
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
        self._mark_new_project_dirty()

    def compare_revision(self) -> None:
        """Změnový list a značky revize z porovnání se starší verzí projektu (jeden krok undo)."""
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
        changes = diff_projects(old, self.project, self.library)
        dlg = DiffDialog(changes, self.project, self)
        dlg.goto.connect(self.goto_target)
        if dlg.exec() == DiffDialog.Accepted and changes and \
                self.record_revision(changes, dlg.rev.text().strip(), dlg.date.text().strip(),
                                     dlg.author.text().strip(), dlg.change_text()):
            self.statusBar().showMessage(f"Změnový list doplněn o {len(changes)} řádků", 4000)

    def record_revision(self, changes, label: str, date: str, author: str, change_text: str) -> bool:
        """Zapíše porovnání do revize: značky (`apply_changes`) + řádky `meta["changes"]`, jako jeden undo příkaz.
        False = označení patří uzavřené revizi (hláška, projekt se nezmění)."""
        from envocad.model.revision import (
            apply_changes,
            open_revision,
            restore_revisions_state,
            revisions_state,
        )
        before = revisions_state(self.project)
        try:
            rev = open_revision(self.project, label, date, author)
        except ValueError as ex:
            QMessageBox.warning(self, "Porovnání s revizí", f"{ex}.")
            return False
        apply_changes(self.project, rev, changes)
        cur = self.project.meta.get("changes", "")
        self.project.meta["changes"] = (cur + "\n" + change_text).strip() if cur else change_text
        after = revisions_state(self.project)
        restore_revisions_state(self.project, before)
        self.undo.push(commands.ReplaceRevisionsCommand(self.project, before, after, "Porovnání s revizí"))
        return True

    def close_revision_all(self) -> bool:
        return self.close_open_revision(None)

    def close_revision_sheet(self) -> bool:
        sh = self.current_sheet
        if sh is None:
            QMessageBox.information(self, "Uzavřít revizi listu", "Není otevřený žádný list.")
            return False
        return self.close_open_revision([sh.id])

    def close_open_revision(self, sheet_ids: list[str] | None) -> bool:
        """Uzavře otevřenou revizi (celou, nebo jen vybrané listy) jako jeden undo příkaz. False = není co uzavřít."""
        from envocad.model.revision import close_revision, restore_revisions_state, revisions_state
        rev = next((r for r in reversed(self.project.revisions) if not r.closed), None)
        if rev is None:
            QMessageBox.information(self, "Uzavřít revizi", "Není otevřená žádná revize – nejdřív porovnej projekt "
                                                            "se starší revizí.")
            return False
        from envocad.model.notes import notes_on_sheet
        closing = sheet_ids if sheet_ids is not None else [s.id for s in self.project.sheets]
        n_open = sum(len(notes_on_sheet(self.project, sid, ("open",))) for sid in closing)
        if n_open and not self._confirm_close_with_notes(n_open):
            return False
        before = revisions_state(self.project)
        close_revision(self.project, next(r for r in self.project.revisions if r.id == rev.id), sheet_ids)
        after = revisions_state(self.project)
        restore_revisions_state(self.project, before)
        text = f"Uzavřít revizi {rev.label}" if sheet_ids is None else f"Uzavřít revizi {rev.label} listu"
        self.undo.push(commands.ReplaceRevisionsCommand(self.project, before, after, text))
        self.statusBar().showMessage(f"Revize {rev.label} uzavřena", 4000)
        return True

    def _confirm_close_with_notes(self, n_open: int) -> bool:
        from PySide6.QtWidgets import QDialogButtonBox

        from envocad.model.notes import OPEN_NOTE_WORDS, count_label
        from envocad.ui.dialogs import czech_buttons
        box = QMessageBox(QMessageBox.Question, "Uzavřít revizi",
                          f"{count_label(n_open, OPEN_NOTE_WORDS)} – přesto uzavřít?", QMessageBox.Yes | QMessageBox.No,
                          self)
        box.setDefaultButton(QMessageBox.No)
        czech_buttons(box.findChild(QDialogButtonBox))
        return box.exec() == QMessageBox.Yes

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Otevřít projekt", "", FILE_FILTER)
        if path:
            self._open_file(path)

    def _open_file(self, path) -> bool:
        """Načte a zobrazí projekt; při chybě hláška a okno (projekt, záložky) zůstane beze změny."""
        try:
            self._load_project(Project.load(path))
        except Exception as ex:  # noqa: BLE001
            log.warning("projekt %s nejde otevřít: %s", path, ex)
            QMessageBox.critical(self, "Chyba", f"Projekt nelze otevřít:\n{path}\n\n{error_text(ex)}")
            return False
        return True

    def save_project(self) -> bool:
        if self.project.path is None:
            return self.save_project_as()
        return self._save_to(self.project.path)

    def _save_to(self, path) -> bool:
        """Uloží projekt do `path`. Cesta projektu se změní až po úspěšném zápisu (`Project.save` je atomický);
        chyba → česká hláška, projekt i titulek zůstanou, jak byly."""
        try:
            self.project.save(path)
        except Exception as ex:  # noqa: BLE001
            log.warning("uložení %s selhalo: %s", path, ex)
            QMessageBox.critical(self, "Uložení selhalo",
                                 f"Projekt se nepodařilo uložit do\n{path}\n\n{error_text(ex)}\n\n"
                                 "Předchozí verze souboru zůstala beze změny.")
            self._update_title()
            return False
        self.undo.setClean()
        self._update_title()
        self._add_recent(self.project.path)
        self._clear_autosave()   # jen kopie tohoto okna (stejný projekt může mít rozpracovaný i jiné okno)
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
        if self._open_file(path):
            self._add_recent(path)

    def _autosave_path(self) -> Path:
        """Soubor automatické kopie: jméno + otisk celé cesty projektu (stejně pojmenované projekty v různých
        složkách se nepřepisují); nepojmenovaný projekt má kopii pro každé okno zvlášť."""
        import hashlib

        from envocad.library.store import home_dir
        d = home_dir() / "autosave"
        d.mkdir(parents=True, exist_ok=True)
        if self.project.path:
            full = str(Path(self.project.path).expanduser().absolute())
            name = f"{self.project.path.stem}-{hashlib.sha1(full.encode('utf-8')).hexdigest()[:10]}"
        else:
            name = f"nepojmenovany-{self._autosave_token}"
        return d / f"{name}.autosave.ecp"

    def autosave(self) -> None:
        """Automatická kopie rozpracovaného projektu – zapisuje `to_dict()` do vlastního souboru, `project.path` se
        nemění (ani při chybě zápisu)."""
        if self.undo.isClean():
            return
        try:
            from envocad.model.project import write_json_atomic
            p = self._autosave_path()
            write_json_atomic(self.project.to_dict(), p)
            (p.with_suffix(".orig")).write_text(str(self.project.path or ""), encoding="utf-8")
        except Exception as ex:  # noqa: BLE001
            log.warning("autosave selhal: %s", ex)
            return
        log.info("autosave %s", p)
        old = {self._last_autosave, self._recovered_autosave} - {p, None}
        self._last_autosave = p
        self._recovered_autosave = None
        # obnovená (nebo starší, jinak pojmenovaná) kopie tohoto okna je teď nahrazena novou → smazat
        self._unlink_autosaves(old)

    @staticmethod
    def _unlink_autosaves(paths) -> None:
        for p in paths:
            try:
                p.unlink(missing_ok=True)
                p.with_suffix(".orig").unlink(missing_ok=True)
            except OSError as ex:
                log.warning("autosave %s nejde smazat: %s", p, ex)

    def _clear_autosave(self) -> None:
        """Smaže automatické kopie, které patří tomuto oknu (zapsaná `_last_autosave` a obnovená kopie) – po uložení,
        po zahození změn a otevření jiného projektu, po zavření okna. Čisté okno, které nic nezapsalo, nemaže nic."""
        self._unlink_autosaves({self._last_autosave, self._recovered_autosave} - {None})
        self._last_autosave = None
        self._recovered_autosave = None

    def offer_recovery(self) -> None:
        """Po startu: pokud existuje automaticky uložená kopie, nabídne její obnovení."""
        from envocad.library.store import home_dir
        d = home_dir() / "autosave"
        if not d.exists():
            return
        def mtime(f: Path) -> float:
            try:
                return f.stat().st_mtime
            except OSError:
                return 0.0
        own = {self._last_autosave, self._recovered_autosave}   # vlastní kopie okna se nenabízejí
        files = sorted((f for f in d.glob("*.autosave.ecp") if f not in own), key=mtime, reverse=True)
        if not files:
            return
        f = files[0]           # nejnovější; ostatní zůstanou a nabídnou se při dalším startu
        orig_file = f.with_suffix(".orig")
        try:
            orig = orig_file.read_text(encoding="utf-8-sig").strip() if orig_file.exists() else ""
        except (OSError, UnicodeDecodeError):
            orig = ""
        more = (f"\n\nDalší automaticky uložené kopie ({len(files) - 1}) zůstanou ve složce\n{d}\n"
                "a nabídnou se při příštím spuštění.") if len(files) > 1 else ""
        rejected = d / REJECTED_AUTOSAVE_DIR
        r = QMessageBox.question(self, "Obnova rozpracované práce",
                                 f"Byla nalezena automaticky uložená kopie projektu\n{orig or '(nepojmenovaný)'}.\n"
                                 f"Obnovit ji? (Ne = kopie se přesune do složky\n{rejected}\n"
                                 f"a už se nebude nabízet){more}", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if r != QMessageBox.Yes:
            # „Ne“ kopii nemaže: může patřit oknu, které právě běží (druhý proces se stejným projektem) nebo jde o
            # omyl. Přesune se do podsložky „odmitnute“ – nenabízí se znovu (ani při dalším startu), zůstává ručně
            # dostupná a běžící okno si při příštím autosave zapíše novou kopii. Staré odmítnuté kopie se promazávají.
            self._reject_autosave(f, rejected)
            return
        try:
            proj = Project.load(f)
            proj.path = Path(orig) if orig else None
            self._load_project(proj)
        except Exception as ex:  # noqa: BLE001 – kopie zůstává, nic se nemaže
            log.warning("autosave %s nejde načíst: %s", f, ex)
            QMessageBox.warning(self, "Obnova", f"Kopii nejde načíst:\n{error_text(ex)}\n\n"
                                f"Soubor zůstává ve složce\n{d}")
            return
        # obnovený projekt není uložený v původním souboru → neuložený stav (zavření se zeptá, autosave běží);
        # undo-reset-ok: obnova autosave – čistý stav se zahodí, žádný krok undo ho nevrátí
        self.undo.resetClean()
        self._update_title()
        # kopie zůstává na disku, dokud okno nezapíše novou (autosave) nebo projekt neuloží / nezahodí
        self._recovered_autosave = f

    @staticmethod
    def _reject_autosave(f: Path, rejected: Path) -> None:
        """Přesune odmítnutou kopii (a její .orig) do `rejected`; kopie starší než REJECTED_KEEP_DAYS tam smaže."""
        import time
        try:
            rejected.mkdir(parents=True, exist_ok=True)
            for src in (f, f.with_suffix(".orig")):
                if src.exists():
                    os.replace(src, rejected / src.name)
            limit = time.time() - REJECTED_KEEP_DAYS * 86400
            for old in rejected.iterdir():
                if old.is_file() and old.stat().st_mtime < limit:
                    old.unlink(missing_ok=True)
        except OSError as ex:
            log.warning("odmítnutou kopii %s nejde přesunout: %s", f, ex)

    def save_project_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Uložit projekt", "", FILE_FILTER)
        if not path:
            return False
        if not path.endswith(".ecp"):
            path += ".ecp"
        return self._save_to(Path(path))

    def edit_project_meta(self) -> None:
        """Vlastnosti projektu: jeden formulář; OK = jeden krok undo, Zrušit = žádná změna."""
        from envocad.ui.dialogs import ProjectMetaDialog
        dlg = ProjectMetaDialog(self.project, self)
        if dlg.exec() != ProjectMetaDialog.Accepted:
            return
        self.set_project_meta(*dlg.values())

    def set_project_meta(self, name: str, meta: dict[str, str]) -> bool:
        """Název a metadata projektu přes `SetProjectMetaCommand`; beze změny = bez kroku (False)."""
        old = (self.project.name, dict(self.project.meta))
        if old == (name, meta):
            return False
        self.undo.push(commands.SetProjectMetaCommand(self.project, old, (name, dict(meta)),
                                                      on_change=self._project_meta_changed))
        return True

    def _project_meta_changed(self) -> None:
        for sc in self._scenes:   # popisové pole listů ukazuje název a metadata projektu
            sc.update()

    # ---- export / import -------------------------------------------------------
    def export_dxf(self) -> None:
        from envocad.export.dxf_export import export_sheet_dxf
        if not self.scene:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export DXF", "", "DXF (*.dxf)")
        if path:
            export_sheet_dxf(self.project, self.scene.sheet, self.library, path, notes=self._export_notes())
            self.statusBar().showMessage(f"Exportováno: {path}", 3000)

    def export_pdf(self, paper: str = "") -> None:
        from envocad.export.pdf_export import export_scene_pdf
        sc = self.scene or (self.view.scene() if isinstance(self.view, DERIVED_VIEWS) else None)
        if not sc:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", "", "PDF (*.pdf)")
        if path:
            n = export_scene_pdf(sc, path, paper=paper or None, notes=self._export_notes())
            from envocad.model.notes import count_label
            self.statusBar().showMessage(f"Exportováno: {path}" + (f" ({count_label(n)})" if n else ""), 3000)

    def export_xlsx(self, current_only: bool) -> None:
        from envocad.export.xlsx_export import export_reports_xlsx
        sh = self.current_sheet if current_only else None
        base = (sh.name if sh else self.project.name).replace("/", "-")
        path, _ = QFileDialog.getSaveFileName(self, "Výkazy", f"{base} – výkazy.xlsx", "Excel (*.xlsx)")
        if path:
            export_reports_xlsx(self.project, self.library, path, sh)
            self.statusBar().showMessage(f"Exportováno: {path}", 3000)

    def export_production(self) -> None:
        """Výrobní zapojovací seznam pro dílnu: aktuální list rozvaděče, jinak všechny rozvaděče projektu."""
        from envocad.export.xlsx_export import export_production_xlsx
        cur = self.current_sheet
        sh = cur if cur is not None and cur.is_switchboard else None
        if sh is None and not self.project.switchboards():
            QMessageBox.information(self, "Výrobní data", "Projekt nemá žádný list rozvaděče.")
            return
        base = (sh.name if sh else self.project.name).replace("/", "-")
        path, _ = QFileDialog.getSaveFileName(self, "Výrobní data rozvaděče", f"{base} – výroba.xlsx", "Excel (*.xlsx)")
        if path:
            export_production_xlsx(self.project, self.library, path, sh)
            self.statusBar().showMessage(f"Exportováno: {path}", 3000)

    def export_documentation(self) -> None:
        from envocad.export.doc_pdf import export_documentation_pdf
        base = self.project.name.replace("/", "-") or "dokumentace"
        path, _ = QFileDialog.getSaveFileName(self, "Celá dokumentace", f"{base} – dokumentace.pdf", "PDF (*.pdf)")
        if path:
            n = export_documentation_pdf(self.project, self.library, path, notes=self._export_notes())
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

    def import_qet_symbol(self) -> None:
        """Značka QElectroTech (.elmt, XML) → knihovna. Poškozené XML → česká hláška, knihovna beze změny."""
        from envocad.library.qet_import import parse_elmt, slug
        path, _ = QFileDialog.getOpenFileName(self, "Import značky QElectroTech", "", "QElectroTech (*.elmt)")
        if not path:
            return
        sid = f"qet.{slug(Path(path).stem)}"
        if self.library.has_symbol(sid):
            sid = free_symbol_id(self.library, sid)
        try:
            sym = parse_elmt(path, sid, "QET")
            self.library.put_symbol(sym)
        except Exception as ex:  # noqa: BLE001 – ParseError, chybějící soubor, nesmyslná geometrie…
            log.warning("import QET %s selhal: %s", path, ex)
            QMessageBox.warning(self, "Import QElectroTech", f"Značku nejde načíst:\n{path}\n\n{error_text(ex)}")
            return
        self.lib_panel.refresh()
        QMessageBox.information(self, "Import QElectroTech", f"Značka {sid} importována ({len(sym.primitives)} primitiv, "
                                f"{len(sym.ports)} portů).")

    def import_eplan(self) -> None:
        """EPLAN: artikly z XML (Data Portal) nebo CSV, ZIP/EDZ s DXF footprinty a XML artikly → uživatelská
        knihovna (`~/.envocad/library/eplan/`). Poškozený soubor (ParseError, BadZipFile…) → česká hláška."""
        import tempfile
        import zipfile

        from envocad.library import eplan_import as ei
        from envocad.library.store import user_library_dir
        path, _ = QFileDialog.getOpenFileName(self, "Import z EPLAN", "", "EPLAN (*.xml *.csv *.zip *.edz)")
        if not path:
            return
        src = Path(path)
        out_dir = user_library_dir() / "eplan"
        n_fp = 0
        try:
            if src.suffix.lower() in (".zip", ".edz"):
                n_fp = len(ei.footprints_from_zip(src, out_dir / "footprints"))
                rows = []
                with zipfile.ZipFile(src) as z, tempfile.TemporaryDirectory() as tmp:
                    for name in (n for n in z.namelist() if n.lower().endswith(".xml")):
                        t = Path(tmp) / "parts.xml"
                        t.write_bytes(z.read(name))
                        rows += ei.rows_from_parts_xml(t)[0]
            elif src.suffix.lower() == ".xml":
                rows = ei.rows_from_parts_xml(src)[0]
            else:
                rows = ei.rows_from_commercial_csv(src)[0]
            n = 0
            if rows:
                out_dir.mkdir(parents=True, exist_ok=True)
                csv_path = out_dir / f"{src.stem}.csv"
                ei.write_components_csv(rows, csv_path)
                n = self.library.import_components_csv_v2(csv_path)
        except Exception as ex:  # noqa: BLE001
            log.warning("import EPLAN %s selhal: %s", path, ex)
            QMessageBox.warning(self, "Import z EPLAN", f"Soubor nejde načíst:\n{path}\n\n{error_text(ex)}")
            return
        if n_fp:
            self.library.sync_builtin()   # footprinty v uživatelské knihovně (jen u výchozí databáze)
            self.lib_panel.refresh()
        QMessageBox.information(self, "Import z EPLAN", f"Načteno {n} artiklů" + (f" a {n_fp} footprintů" if n_fp else "")
                                + f".\nUloženo do {out_dir}.")

    def import_dxf_symbol(self) -> None:
        from envocad.library.dxf_import import import_dxf, list_blocks
        path, _ = QFileDialog.getOpenFileName(self, "Import symbolu z DXF", "", "DXF (*.dxf)")
        if not path:
            return
        try:
            blocks = ["(modelspace)"] + list_blocks(path)
        except Exception as ex:  # noqa: BLE001 – poškozený / jiný soubor
            QMessageBox.warning(self, "Import DXF", f"Soubor nejde načíst jako DXF:\n{path}\n\n{error_text(ex)}")
            return
        blk, ok = QInputDialog.getItem(self, "Import DXF", "Zdroj geometrie:", blocks, 0, False)
        if not ok:
            return
        sid = ""
        while True:
            sid, ok = QInputDialog.getText(self, "Import DXF", "ID symbolu (např. fve.vyrobce.typ):", text=sid)
            sid = sid.strip()
            if not ok or not sid:
                return
            if not self.library.has_symbol(sid):
                break
            kind = "vestavěná značka" if self.library.is_builtin(sid) else "značka v knihovně"
            sid = free_symbol_id(self.library, sid)
            QMessageBox.warning(self, "Import DXF", f"ID už má {kind} – existující značky se importem nepřepisují.\n"
                                f"Zadejte jiné ID (návrh: {sid}).")
        name, ok = QInputDialog.getText(self, "Import DXF", "Název symbolu:", text=Path(path).stem)
        if not ok:
            return
        scale, ok = QInputDialog.getDouble(self, "Import DXF", "Měřítko (DXF jednotka → mm):", 1.0, 0.0001, 10000, 4)
        if not ok:
            return
        try:
            sym = import_dxf(path, sid, name, None if blk == "(modelspace)" else blk, scale, True, True)
            self.library.put_symbol(sym)
        except Exception as ex:  # noqa: BLE001
            log.warning("import DXF %s selhal: %s", path, ex)
            QMessageBox.warning(self, "Import DXF", f"Import se nezdařil:\n{error_text(ex)}")
            return
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
            self._clear_autosave()   # uloženo nebo zahozeno – kopie tohoto okna už není potřeba
            ev.accept()
        else:
            ev.ignore()
