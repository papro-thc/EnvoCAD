"""Dialogy editoru."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout

from envocad.model.symbol import Attribute, Symbol


class AttrDialog(QDialog):
    """Zadání všech atributů prvku nebo vodiče – při vložení i při dvojkliku na existující."""

    def __init__(self, attributes: list[Attribute], attrs: dict[str, str], parent=None,
                 title: str = "Parametry", heading: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        self._edits: dict[str, QLineEdit] = {}
        lay = QVBoxLayout(self)
        if heading:
            lay.addWidget(QLabel(heading))
        form = QFormLayout()
        for a in attributes:
            ed = QLineEdit(attrs.get(a.key, a.default))
            ed.setPlaceholderText(a.default)
            self._edits[a.key] = ed
            form.addRow(a.label + (" *" if a.show else ""), ed)
        lay.addLayout(form)
        lay.addWidget(QLabel("<small>* zobrazí se ve výkresu</small>"))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        first = next(iter(self._edits.values()), None)
        if first:
            first.setFocus()
            first.selectAll()

    def values(self) -> dict[str, str]:
        return {k: e.text().strip() for k, e in self._edits.items()}


class ElementDialog(AttrDialog):
    def __init__(self, symbol: Symbol, attrs: dict[str, str], parent=None, title: str | None = None):
        super().__init__(symbol.attributes, attrs, parent, title or f"Vložit: {symbol.name}",
                         f"<b>{symbol.name}</b> <small>({symbol.id})</small>")
