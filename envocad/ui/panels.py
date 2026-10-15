"""Dokovací panely: knihovna symbolů a vlastnosti vybraného prvku."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envocad.library.store import LibraryStore
from envocad.model.project import WIRE_ATTRIBUTES
from envocad.ui.items import ElementItem, WireItem


class LibraryPanel(QWidget):
    symbol_chosen = Signal(str)

    def __init__(self, library: LibraryStore):
        super().__init__()
        self.library = library
        self.search = QLineEdit(placeholderText="Hledat symbol…")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.addWidget(self.search)
        lay.addWidget(self.tree)
        self.search.textChanged.connect(self.refresh)
        self.tree.itemDoubleClicked.connect(self._dbl)
        self.refresh()

    def refresh(self) -> None:
        self.tree.clear()
        cats: dict[str, QTreeWidgetItem] = {}
        for sid, name, cat in self.library.list_symbols(self.search.text()):
            parent = cats.get(cat)
            if parent is None:
                parent = QTreeWidgetItem([cat or "Ostatní"])
                parent.setFlags(parent.flags() & ~Qt.ItemIsSelectable)
                cats[cat] = parent
                self.tree.addTopLevelItem(parent)
            it = QTreeWidgetItem([name])
            it.setData(0, Qt.UserRole, sid)
            it.setToolTip(0, sid)
            parent.addChild(it)
        self.tree.expandAll()

    def _dbl(self, item: QTreeWidgetItem, _col: int) -> None:
        sid = item.data(0, Qt.UserRole)
        if sid:
            self.symbol_chosen.emit(sid)


class PropertiesPanel(QWidget):
    attr_edited = Signal(str, bool, str, str)  # target_id, is_wire, key, value

    def __init__(self):
        super().__init__()
        self.form = QFormLayout(self)
        self.form.setContentsMargins(4, 4, 4, 4)
        self._target: tuple[str, bool] | None = None
        self.show_item(None)

    def _clear(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)

    def show_item(self, item) -> None:
        self._clear()
        if isinstance(item, ElementItem):
            e, sym = item.element, item.symbol
            self._target = (e.id, False)
            self.form.addRow(QLabel(f"<b>{sym.name}</b><br><small>{sym.id}</small>"))
            for a in sym.attributes:
                self._add_field(a.key, a.label, e.attrs.get(a.key, ""))
        elif isinstance(item, WireItem):
            w = item.wire
            self._target = (w.id, True)
            self.form.addRow(QLabel(f"<b>Vodič</b><br><small>{w.a.element_id}:{w.a.port} → {w.b.element_id}:{w.b.port}</small>"))
            for a in WIRE_ATTRIBUTES:
                self._add_field(a.key, a.label, w.attrs.get(a.key, ""))
        else:
            self._target = None
            self.form.addRow(QLabel("<i>Nic není vybráno</i>"))

    def _add_field(self, key: str, label: str, value: str) -> None:
        ed = QLineEdit(value)
        ed.editingFinished.connect(lambda k=key, w=ed: self._commit(k, w.text()))
        self.form.addRow(label, ed)

    def _commit(self, key: str, value: str) -> None:
        if self._target:
            self.attr_edited.emit(self._target[0], self._target[1], key, value)
