"""Navigátor projektu (strom listy → prvky, vodiče) a seznam nálezů kontroly – oba skáčou do výkresu."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envocad.model.checks import ERROR, WARNING, Finding, summary


class NavigatorPanel(QWidget):
    goto = Signal(str, str, bool)  # sheet_id, target_id, is_wire

    def __init__(self, library):
        super().__init__()
        self.library = library
        self.project = None
        self.filter = QLineEdit(placeholderText="Hledat označení… (Ctrl+F)")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Prvek", "Typ / popis"])
        self.tree.setColumnWidth(0, 120)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.addWidget(self.filter)
        lay.addWidget(self.tree)
        self.filter.textChanged.connect(lambda _t: self._schedule())
        self.tree.itemActivated.connect(self._activated)
        self.tree.itemClicked.connect(self._activated)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)

    def set_project(self, project) -> None:
        self.project = project
        self.refresh()

    def _schedule(self) -> None:
        self._timer.start(150)

    def refresh(self) -> None:
        self.tree.clear()
        if self.project is None:
            return
        q = self.filter.text().strip().lower()
        for s in self.project.sheets:
            top = QTreeWidgetItem([s.name, "rozvaděč" if s.is_switchboard else "list"])
            top.setData(0, Qt.UserRole, (s.id, "", False))
            n = 0
            for e in sorted(s.elements, key=lambda e: (e.ref or "~", e.symbol_id)):
                try:
                    name = self.library.get_symbol(e.symbol_id).name
                except Exception:  # noqa: BLE001
                    name = e.symbol_id
                label = e.ref or "(bez označení)"
                desc = " ".join(x for x in (name, e.attrs.get("type", ""), e.attrs.get("desc", "")) if x)
                if q and q not in label.lower() and q not in desc.lower():
                    continue
                it = QTreeWidgetItem([label, desc])
                it.setData(0, Qt.UserRole, (s.id, e.id, False))
                top.addChild(it)
                n += 1
            for w in s.wires:
                label = w.attrs.get("ref") or "(vodič)"
                desc = " ".join(x for x in (w.attrs.get("cable", ""), w.attrs.get("cross", ""), " ".join(w.conductors)) if x)
                if q and q not in label.lower() and q not in desc.lower():
                    continue
                it = QTreeWidgetItem([label, desc])
                it.setData(0, Qt.UserRole, (s.id, w.id, True))
                top.addChild(it)
                n += 1
            if n or not q:
                self.tree.addTopLevelItem(top)
                top.setExpanded(bool(q) or s.is_switchboard is False)

    def _activated(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.UserRole)
        if data:
            self.goto.emit(*data)


class ChecksDialog(QDialog):
    goto = Signal(str, str, bool)

    def __init__(self, findings: list[Finding], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kontrola projektu")
        self.resize(760, 460)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{summary(findings)}</b> – dvojklik skočí na prvek"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Závažnost", "List", "Prvek", "Nález"])
        for f in findings:
            it = QTreeWidgetItem([f.severity, f.sheet_name, f.ref, f.text])
            it.setData(0, Qt.UserRole, (f.sheet_id, f.target_id, f.is_wire))
            if f.severity == ERROR:
                it.setForeground(0, Qt.red)
            elif f.severity == WARNING:
                it.setForeground(0, Qt.darkYellow)
            self.tree.addTopLevelItem(it)
        for i in range(3):
            self.tree.resizeColumnToContents(i)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.goto.emit(*it.data(0, Qt.UserRole)))
        lay.addWidget(self.tree)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
