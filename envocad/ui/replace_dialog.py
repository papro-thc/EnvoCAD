"""Dialog Najít a nahradit text (issue #74). Jen vstupy a počet nálezů; hledání i nahrazení dělá `envocad.cmd.edits`."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from envocad.cmd.edits import find_text


class ReplaceDialog(QDialog):
    def __init__(self, parent, project, library, current_sheet, apply):
        super().__init__(parent)
        self.setWindowTitle("Najít a nahradit")
        self._project, self._library, self._current_sheet, self._apply = project, library, current_sheet, apply
        self.find = QLineEdit()
        self.replace = QLineEdit()
        self.scope = QComboBox()
        self.scope.addItem("Celý projekt", "project")
        self.scope.addItem("Aktuální list", "sheet")
        if current_sheet() is None:                # bez aktivního listu (např. jednopólové schéma) nejde zvolit
            self.scope.model().item(self.scope.findData("sheet")).setEnabled(False)
        self.match_case = QCheckBox("Rozlišovat velká a malá písmena")
        self.count = QLabel("")
        form = QFormLayout()
        form.addRow("Najít:", self.find)
        form.addRow("Nahradit za:", self.replace)
        form.addRow("Rozsah:", self.scope)
        form.addRow("", self.match_case)
        form.addRow("Nalezeno:", self.count)
        self.buttons = QDialogButtonBox()
        self.btn_replace = self.buttons.addButton("Nahradit vše", QDialogButtonBox.AcceptRole)
        self.buttons.addButton("Zrušit", QDialogButtonBox.RejectRole)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.buttons)
        for sig in (self.find.textChanged, self.replace.textChanged, self.match_case.toggled,
                    self.scope.currentIndexChanged):
            sig.connect(self._update_count)
        self._update_count()

    def _update_count(self, *_) -> None:
        text = self.find.text()
        sheet = self._current_sheet() if self.scope.currentData() == "sheet" else None
        if self.scope.currentData() == "sheet" and sheet is None:     # nepočítat z celého projektu
            self.count.setText("žádný aktivní list")
            self.btn_replace.setEnabled(False)
            return
        if not text:
            self.count.setText("")
            self.btn_replace.setEnabled(False)
            return
        ms = find_text(self._project, self._library, text, self.replace.text(), sheet, self.match_case.isChecked())
        n = sum(m.count for m in ms)
        self.count.setText(f"{n} výskytů v {len(ms)} hodnotách" if n else "nic nenalezeno")
        self.btn_replace.setEnabled(n > 0)

    def _accept(self) -> None:
        self._apply(self.find.text(), self.replace.text(), self.scope.currentData(), self.match_case.isChecked())
        self.accept()
