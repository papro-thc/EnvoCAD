"""Dialog Úpravy → Přečíslovat označení: rozsah, režim, co číslovat a náhled změn (staré → nové)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from envocad.model import renumber
from envocad.model.project import Project, Sheet, TextChange, rename_followups


class RenumberDialog(QDialog):
    def __init__(self, project: Project, library, sheet: Sheet | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Přečíslovat označení")
        self.project, self.library, self.sheet = project, library, sheet
        self.changes: list[TextChange] = []
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.scope = QComboBox()
        if sheet is not None:
            self.scope.addItem(f"Aktuální list ({sheet.name})", "sheet")
        self.scope.addItem("Celý projekt", "project")
        self.mode = QComboBox()
        for key, label in renumber.MODES.items():
            self.mode.addItem(label, key)
        self.mode.setCurrentIndex(self.mode.findData(renumber.FIX))
        self.devices = QCheckBox("Přístroje")
        self.devices.setChecked(True)
        self.wires = QCheckBox("Vodiče (kabely W)")
        self.wires.setChecked(True)
        form.addRow("Rozsah:", self.scope)
        form.addRow("Režim:", self.mode)
        form.addRow("Číslovat:", self.devices)
        form.addRow("", self.wires)
        lay.addLayout(form)
        hint = QLabel("Pořadí: listy podle projektu, v listu po sloupcích zleva doprava a shora dolů. Kontakty jdou "
                      "s cívkou, kabel s vodičem. Svorkovnice, přerušovací body, bloky rozvaděčů a firemní označení "
                      "(„Q1.2“) se nemění.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["List", "Staré", "Nové"])
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumSize(420, 240)
        lay.addWidget(self.tree)
        self.summary = QLabel()
        lay.addWidget(self.summary)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Přečíslovat")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        for w in (self.scope, self.mode):
            w.currentIndexChanged.connect(self.refresh)
        for w in (self.devices, self.wires):
            w.toggled.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        sheets = [self.sheet] if self.scope.currentData() == "sheet" else None
        self.changes = renumber.plan(self.project, self.library, self.mode.currentData(), sheets,
                                     wires=self.wires.isChecked(), devices=self.devices.isChecked())
        name_of = {}
        for s in self.project.sheets:
            for x in (*s.elements, *s.wires):
                name_of[x.id] = s.name
        self.tree.clear()
        shown: set[tuple[str, str]] = set()
        for c in self.changes:
            if c.key != "ref" or c.kind == "cable" or (c.old, c.new) in shown:
                continue                  # kontakty a kabel jako jeden řádek s přístrojem / vodičem
            shown.add((c.old, c.new))
            self.tree.addTopLevelItem(QTreeWidgetItem([name_of.get(c.target_id, ""), c.old or "–", c.new]))
        self.summary.setText(f"Změní se {renumber.summary(self.changes)}." if self.changes
                             else "Není co přečíslovat.")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self.changes))

    def all_changes(self) -> list[TextChange]:
        """Změny označení + navázané automatické popisy („od T1“) přejmenovaných prvků, každý text jen jednou."""
        els = {e.id: e for s in self.project.sheets for e in s.elements}
        out = list(self.changes)
        done = {(c.kind, c.target_id, c.key) for c in out}
        for c in self.changes:
            if c.kind == "element" and c.old and c.target_id in els:
                for f in rename_followups(self.project, els[c.target_id], c.old, c.new):
                    if (f.kind, f.target_id, f.key) not in done:
                        done.add((f.kind, f.target_id, f.key))
                        out.append(f)
        return out
