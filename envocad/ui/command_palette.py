"""Hledání příkazů (Ctrl+K): všechny akce z menu, filtr podle slov (bez ohledu na diakritiku a velikost písmen),
Enter spustí vybranou. Zdroj = menu okna, takže nové akce i pluginy se zařadí samy."""
from __future__ import annotations

import re
import unicodedata

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMenuBar, QVBoxLayout


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in t if not unicodedata.combining(c))


def _clean(text: str) -> str:
    return re.sub(r"&(.)", r"\1", text).rstrip("…").strip()


def collect_actions(menubar: QMenuBar) -> list[tuple[str, QAction]]:
    """(cesta „Soubor › Export DXF“, akce) pro všechny spustitelné akce menu (i v podmenu), bez oddělovačů."""
    out: list[tuple[str, QAction]] = []

    def walk(menu: QMenu, path: str) -> None:
        for a in menu.actions():
            if a.isSeparator():
                continue
            sub = a.menu()
            if sub is not None:
                walk(sub, f"{path} › {_clean(sub.title())}")
            elif a.text():
                out.append((f"{path} › {_clean(a.text())}", a))

    for a in menubar.actions():
        if a.menu() is not None:
            walk(a.menu(), _clean(a.menu().title()))
    return out


def matches(query: str, label: str) -> bool:
    words = _norm(query).split()
    lab = _norm(label)
    return all(w in lab for w in words)


class CommandPalette(QDialog):
    def __init__(self, menubar: QMenuBar, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hledat příkaz")
        self.resize(560, 420)
        self.entries = collect_actions(menubar)
        lay = QVBoxLayout(self)
        self.edit = QLineEdit(placeholderText="Napište část názvu příkazu… (Enter spustí, Esc zavře)")
        self.list = QListWidget()
        lay.addWidget(self.edit)
        lay.addWidget(self.list)
        self.edit.textChanged.connect(self.refresh)
        self.edit.returnPressed.connect(self.run_current)
        self.list.itemActivated.connect(lambda _it: self.run_current())
        self.edit.installEventFilter(self)
        self.chosen: QAction | None = None
        self.refresh()

    def refresh(self, _text: str = "") -> None:
        q = self.edit.text()
        self.list.clear()
        for label, a in self.entries:
            if not matches(q, label):
                continue
            keys = a.shortcut().toString(QKeySequence.NativeText)
            it = QListWidgetItem(f"{label}    {keys}" if keys else label)
            it.setData(Qt.UserRole, a)
            if not a.isEnabled():
                it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
            if not a.icon().isNull():
                it.setIcon(a.icon())
            self.list.addItem(it)
        for i in range(self.list.count()):
            if self.list.item(i).flags() & Qt.ItemIsEnabled:
                self.list.setCurrentRow(i)
                break

    def eventFilter(self, obj, ev):
        # šipky v poli hledání posouvají výběr v seznamu
        if obj is self.edit and ev.type() == ev.Type.KeyPress and ev.key() in (Qt.Key_Down, Qt.Key_Up):
            row = self.list.currentRow() + (1 if ev.key() == Qt.Key_Down else -1)
            if 0 <= row < self.list.count():
                self.list.setCurrentRow(row)
            return True
        return super().eventFilter(obj, ev)

    def run_current(self) -> None:
        it = self.list.currentItem()
        if it is None or not it.flags() & Qt.ItemIsEnabled:
            return
        self.chosen = it.data(Qt.UserRole)
        self.accept()
        # akce se spustí až po zavření palety (může otevřít vlastní dialog)
        QTimer.singleShot(0, self.chosen.trigger)
