"""Výběr artiklu z knihovny – tabulka s filtrem (výrobce, text, In, póly, charakteristika)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from envocad.library.components import Component
from envocad.library.store import LibraryStore
from envocad.ui.dialogs import button_box

COLUMNS = [("manufacturer", "Výrobce"), ("part_number", "Typ"), ("name", "Název"), ("in_", "In [A]"),
           ("poles", "Póly"), ("char", "Char."), ("icu_ka", "Icu [kA]"), ("idn_ma", "IΔn [mA]"),
           ("modules", "Moduly"), ("p_loss_w", "Pv [W]"), ("p_ac_kw", "P AC [kW]"), ("e_kwh", "kWh"),
           ("width_mm", "Š [mm]"), ("height_mm", "V [mm]"), ("depth_mm", "H [mm]"), ("source", "Zdroj")]


class ComponentPicker(QDialog):
    def __init__(self, library: LibraryStore, symbol_id: str | None = None, category: str | None = None,
                 parent=None, preset_filters: dict[str, str] | None = None, title: str = "Vybrat artikl"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1000, 520)
        self.library = library
        self._symbol_id, self._category = symbol_id, category
        self.selected: Component | None = None

        root = QVBoxLayout(self)
        f = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Hledat (výrobce, typ, název)…")
        self.manufacturer = QComboBox()
        self.manufacturer.addItem("Všichni výrobci", "")
        self.in_ = QLineEdit(placeholderText="In [A]")
        self.in_.setMaximumWidth(80)
        self.poles = QComboBox()
        self.poles.addItems(["Póly: vše", "1", "2", "3", "4"])
        self.char = QComboBox()
        self.char.addItems(["Char.: vše", "B", "C", "D", "A", "AC", "gPV", "gG"])
        for w in (self.search, self.manufacturer, self.in_, self.poles, self.char):
            f.addWidget(w)
        self.only_compatible = QComboBox()
        self.only_compatible.addItems(["Jen pro tuto značku", "Všechny artikly"])
        f.addWidget(self.only_compatible)
        root.addLayout(f)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self.accept)
        root.addWidget(self.table)
        self.info = QLabel()
        self.info.setOpenExternalLinks(True)
        root.addWidget(self.info)

        bb = button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        self._all = self._load()
        for m in sorted({c.manufacturer for c in self._all}):
            self.manufacturer.addItem(m, m)
        if preset_filters:
            if preset_filters.get("in_"):
                self.in_.setText(preset_filters["in_"])
            if preset_filters.get("poles") in ("1", "2", "3", "4"):
                self.poles.setCurrentText(preset_filters["poles"])
            if preset_filters.get("char"):
                i = self.char.findText(preset_filters["char"])
                if i > 0:
                    self.char.setCurrentIndex(i)
        for w in (self.search, self.in_):
            w.textChanged.connect(self.refresh)
        for w in (self.manufacturer, self.poles, self.char, self.only_compatible):
            w.currentIndexChanged.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._show_info)
        self.refresh()

    def _load(self) -> list[Component]:
        return self.library.components()

    def _filtered(self) -> list[Component]:
        out = self._all
        if self.only_compatible.currentIndex() == 0:
            if self._symbol_id:
                out = [c for c in out if c.symbol_id == self._symbol_id]
            elif self._category:
                out = [c for c in out if c.category == self._category]
        m = self.manufacturer.currentData()
        if m:
            out = [c for c in out if c.manufacturer == m]
        q = self.search.text().strip().lower()
        if q:
            out = [c for c in out if q in f"{c.manufacturer} {c.part_number} {c.name}".lower()]
        if self.in_.text().strip():
            try:
                v = float(self.in_.text().replace(",", "."))
                out = [c for c in out if c.num("in_") == v]
            except ValueError:
                pass
        if self.poles.currentIndex() > 0:
            out = [c for c in out if (c.params.get("poles") or "") == self.poles.currentText()]
        if self.char.currentIndex() > 0:
            out = [c for c in out if (c.params.get("char") or "") == self.char.currentText()]
        return sorted(out, key=lambda c: (c.manufacturer, c.num("in_") or 0, c.part_number))

    def refresh(self) -> None:
        rows = self._filtered()
        self._rows = rows
        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            vals = {"manufacturer": c.manufacturer, "part_number": c.part_number, "name": c.name, "source": c.source,
                    **c.params}
            for col, (key, _) in enumerate(COLUMNS):
                it = QTableWidgetItem(str(vals.get(key, "") or ""))
                if key in ("in_", "poles", "icu_ka", "idn_ma", "modules", "p_loss_w", "p_ac_kw", "e_kwh",
                           "width_mm", "height_mm", "depth_mm"):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, col, it)
        self.info.setText(f"{len(rows)} artiklů")
        if rows:
            self.table.selectRow(0)

    def _show_info(self) -> None:
        c = self.current()
        if not c:
            return
        link = f' – <a href="{c.datasheet_url}">katalog / datasheet</a>' if c.datasheet_url.startswith("http") else ""
        note = c.params.get("note", "")
        self.info.setText(f"<b>{c.label}</b>{link}<br><small>{note}</small>")

    def current(self) -> Component | None:
        r = self.table.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def accept(self) -> None:
        self.selected = self.current()
        super().accept()
