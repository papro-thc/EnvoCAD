"""Seznam připomínek projektu (záložka docku navigátoru): filtr podle stavu, jen aktuální list, hledání;
tlačítka Vyřešit/Otevřít a Smazat jdou přes `ReplaceNoteCommand`, dvojklik skočí na připomínku."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envocad.model.notes import STATUS_COLORS, STATUS_LABELS, note_target_label
from envocad.ui import commands
from envocad.ui.notes_view import reopened_copy, resolved_copy

FILTERS = (("Otevřené", ("open",)), ("Vyřešené", ("resolved",)), ("Vše", ("open", "resolved")))


class NotesPanel(QWidget):
    goto_note = Signal(str, str)   # sheet_id, note_id

    def __init__(self):
        super().__init__()
        self.project = None
        self.undo = None
        self.current_sheet_id = ""
        self.status = QComboBox()
        for label, _st in FILTERS:
            self.status.addItem(label)
        self.only_sheet = QCheckBox("jen aktuální list")
        self.search = QLineEdit(placeholderText="Hledat v textu, autoru, prvku…")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Č.", "List", "Prvek", "Text", "Autor", "Datum", "Stav"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.btn_toggle = QPushButton("Vyřešit")
        self.btn_delete = QPushButton("Smazat")
        top = QHBoxLayout()
        top.addWidget(self.status)
        top.addWidget(self.only_sheet)
        bottom = QHBoxLayout()
        bottom.addWidget(self.btn_toggle)
        bottom.addWidget(self.btn_delete)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.addLayout(top)
        lay.addWidget(self.search)
        lay.addWidget(self.tree)
        lay.addLayout(bottom)
        self.status.currentIndexChanged.connect(lambda _i: self.refresh())
        self.only_sheet.toggled.connect(lambda _b: self.refresh())
        self.search.textChanged.connect(lambda _t: self.refresh())
        self.tree.itemDoubleClicked.connect(self._activated)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self.btn_toggle.clicked.connect(self.toggle_selected)
        self.btn_delete.clicked.connect(self.delete_selected)
        self._update_buttons()

    def set_project(self, project, undo) -> None:
        self.project, self.undo = project, undo
        self.refresh()

    def set_current_sheet(self, sheet_id: str) -> None:
        self.current_sheet_id = sheet_id
        if self.only_sheet.isChecked():
            self.refresh()

    # ---- obsah ----------------------------------------------------------------------
    def visible_notes(self) -> list:
        if self.project is None:
            return []
        statuses = FILTERS[self.status.currentIndex()][1]
        q = self.search.text().strip().lower()
        sheets = {s.id: s.name for s in self.project.sheets}
        out = []
        for n in sorted(self.project.notes, key=lambda n: n.no):
            if n.status not in statuses:
                continue
            if self.only_sheet.isChecked() and n.sheet_id != self.current_sheet_id:
                continue
            hay = " ".join((n.text, n.author, note_target_label(self.project, n), sheets.get(n.sheet_id, ""))).lower()
            if q and q not in hay:
                continue
            out.append(n)
        return out

    def refresh(self) -> None:
        keep = set(self.selected_ids())
        self.tree.clear()
        if self.project is None:
            self._update_buttons()
            return
        sheets = {s.id: s.name for s in self.project.sheets}
        for n in self.visible_notes():
            it = QTreeWidgetItem([str(n.no), sheets.get(n.sheet_id, "(smazaný list)"),
                                  note_target_label(self.project, n), n.text.replace("\n", " "), n.author,
                                  n.created.replace("T", " "), STATUS_LABELS.get(n.status, n.status)])
            it.setData(0, Qt.UserRole, (n.sheet_id, n.id))
            it.setToolTip(3, n.text)
            if n.status == "resolved":
                it.setForeground(3, QBrush(QColor(*STATUS_COLORS["resolved"])))
            self.tree.addTopLevelItem(it)
            if n.id in keep:
                it.setSelected(True)
        for i in (0, 1, 2, 4, 5, 6):
            self.tree.resizeColumnToContents(i)
        self._update_buttons()

    def selected_ids(self) -> list[str]:
        return [it.data(0, Qt.UserRole)[1] for it in self.tree.selectedItems()]

    def _selected_notes(self) -> list:
        from envocad.model.notes import note
        if self.project is None:
            return []
        return [n for n in (note(self.project, i) for i in self.selected_ids()) if n is not None]

    def _update_buttons(self) -> None:
        sel = self._selected_notes()
        all_resolved = bool(sel) and all(n.status == "resolved" for n in sel)
        self.btn_toggle.setText("Otevřít" if all_resolved else "Vyřešit")
        self.btn_toggle.setEnabled(bool(sel))
        self.btn_delete.setEnabled(bool(sel))

    # ---- akce -------------------------------------------------------------------------
    def _activated(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.UserRole)
        if data:
            self.goto_note.emit(*data)

    def toggle_selected(self) -> int:
        """Vybrané vyřeší, nebo (jsou-li všechny vyřešené) znovu otevře; jeden undo krok. Vrací počet změněných."""
        from envocad.settings import current_user
        sel = self._selected_notes()
        if not sel or self.undo is None:
            return 0
        reopen_all = all(n.status == "resolved" for n in sel)
        todo = [n for n in sel if (n.status == "resolved") == reopen_all]
        self.undo.beginMacro("Znovu otevřít připomínky" if reopen_all else "Vyřešit připomínky")
        user = current_user()
        for n in todo:
            new = reopened_copy(n) if reopen_all else resolved_copy(n, user)
            self.undo.push(commands.ReplaceNoteCommand(
                self.project, n, new, f"{'Znovu otevřít' if reopen_all else 'Vyřešit'} připomínku č. {n.no}"))
        self.undo.endMacro()
        return len(todo)

    def delete_selected(self) -> int:
        sel = self._selected_notes()
        if not sel or self.undo is None:
            return 0
        self.undo.beginMacro("Smazat připomínky")
        for n in sel:
            self.undo.push(commands.ReplaceNoteCommand(self.project, n, None, f"Smazat připomínku č. {n.no}"))
        self.undo.endMacro()
        return len(sel)
