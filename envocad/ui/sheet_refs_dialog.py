"""Dialog List → Přepsat označení listu: všechna označení prvků a vodičů jednoho listu v tabulce najednou
(stávající → nové). Dialog model nemění – změny vrací `changes()` / `all_changes()` a provede je příkaz."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from envocad.model.designation import LOCATION_SYMBOLS
from envocad.model.project import Project, Sheet, TextChange, rename_followups
from envocad.model.renumber import wire_cable_changes

NEW_COLUMN = 3


class SheetRefsDialog(QDialog):
    def __init__(self, project: Project, sheet: Sheet, parent=None, library=None):
        super().__init__(parent)
        self.setWindowTitle("Přepsat označení listu")
        self.project, self.sheet, self.library = project, sheet, library
        # řádky: (druh "element" | "wire", id, stávající označení)
        self._rows: list[tuple[str, str, str]] = []
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"List: {sheet.name}. Přepište sloupec „Nové“; ostatní sloupce jsou jen informativní. "
                             "Bloky rozvaděčů (označení = umístění listu) se tu nemění."))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Typ", "Popis", "Stávající", "Nové"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumSize(520, 320)
        lay.addWidget(self.table)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Přepsat")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        for e in sheet.elements:
            if "ref" in e.attrs and e.symbol_id not in LOCATION_SYMBOLS:
                self._add_row("element", e.id, self._type_name(e), e.attrs.get("desc", ""), e.ref)
        for w in sheet.wires:
            if w.attrs.get("ref"):
                self._add_row("wire", w.id, "Vodič", w.attrs.get("desc", ""), w.attrs["ref"])
        self.table.resizeColumnsToContents()

    def _type_name(self, e) -> str:
        if self.library is not None:
            try:
                return self.library.get_symbol(e.symbol_id).name
            except Exception:  # noqa: BLE001 – neznámá značka: ukáže se její id
                return e.symbol_id.rsplit(".", 1)[-1]
        return e.symbol_id.rsplit(".", 1)[-1]

    def _add_row(self, kind: str, target_id: str, type_name: str, desc: str, ref: str) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self._rows.append((kind, target_id, ref))
        for col, text in enumerate((type_name, desc, ref, ref)):
            it = QTableWidgetItem(text)
            if col != NEW_COLUMN:
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, col, it)

    def set_ref(self, target_id: str, new: str) -> None:
        """Nastaví nové označení prvku / vodiče `target_id` (jako přepsání buňky „Nové“)."""
        for r, (_, tid, _) in enumerate(self._rows):
            if tid == target_id:
                self.table.item(r, NEW_COLUMN).setText(new)
                return
        raise KeyError(target_id)

    def changes(self) -> list[TextChange]:
        """Jen řádky, kde se nové označení liší od stávajícího."""
        out = []
        for r, (kind, tid, old) in enumerate(self._rows):
            new = self.table.item(r, NEW_COLUMN).text().strip()
            if new != old:
                out.append(TextChange(kind, tid, "ref", old, new))
        return out

    def all_changes(self) -> list[TextChange]:
        """Změny označení + navázané změny jako u `RenumberDialog.all_changes`: automatické popisy („od T1“) a názvy
        listů přejmenovaných prvků (`rename_followups`), kabel přejmenovaného vodiče (`wire_cable_changes`)."""
        els = {e.id: e for s in self.project.sheets for e in s.elements}
        wires = {w.id: w for s in self.project.sheets for w in s.wires}
        base = self.changes()
        out = list(base)
        done = {(c.kind, c.target_id, c.key) for c in out}
        for c in base:
            if c.kind == "element" and c.old and c.target_id in els:
                extra = rename_followups(self.project, els[c.target_id], c.old, c.new)
            elif c.kind == "wire" and c.target_id in wires:
                extra = wire_cable_changes(self.project, wires[c.target_id], c.old or "", c.new)
            else:
                continue
            for f in extra:
                if (f.kind, f.target_id, f.key) not in done:
                    done.add((f.kind, f.target_id, f.key))
                    out.append(f)
        return out
