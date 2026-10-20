"""Dialog volného textu listu: text (víc řádků) a výška písma."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QPlainTextEdit

from envocad.model.project import TEXT_HEIGHTS


class TextDialog(QDialog):
    def __init__(self, text: str = "", height: float = 2.5, parent=None, title: str = "Text"):
        super().__init__(parent)
        self.setWindowTitle(title)
        form = QFormLayout(self)
        self.edit = QPlainTextEdit(text)
        self.edit.setMinimumSize(320, 90)
        self.height_box = QComboBox()
        for h in TEXT_HEIGHTS:
            self.height_box.addItem(f"{h:g} mm".replace(".", ","), h)
        i = self.height_box.findData(height)
        if i < 0:
            self.height_box.addItem(f"{height:g} mm".replace(".", ","), height)
            i = self.height_box.count() - 1
        self.height_box.setCurrentIndex(i)
        form.addRow("Text:", self.edit)
        form.addRow("Výška písma:", self.height_box)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.edit.setFocus()

    def values(self) -> tuple[str, float]:
        return self.edit.toPlainText().rstrip(), float(self.height_box.currentData())
