"""Dialog editoru symbolů (fáze 1): porty a atributy existující značky. Kresba se needituje.

Žádná business logika – vše dělá `envocad.library.symbol_edit`; dialog edituje pracovní kopii značky
(není to model projektu, proto bez `QUndoCommand`).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envocad.library import symbol_edit as se
from envocad.model.grid import GRID
from envocad.model.symbol import DIRS, Port, Symbol
from envocad.ui.render import draw_text, paint_symbol, sp

PORT_COLOR = QColor("#d32f2f")


class SymbolPreview(QWidget):
    """Náhled kresby značky se zvýrazněnými porty (Y nahoru převrací `render.sp` / `paint_symbol`)."""

    def __init__(self, sym: Symbol, parent=None):
        super().__init__(parent)
        self.symbol = sym
        self.setMinimumSize(QSize(260, 220))

    def set_symbol(self, sym: Symbol) -> None:
        self.symbol = sym
        self.update()

    def paintEvent(self, _event) -> None:
        x0, y0, x1, y1 = self.symbol.bounds()
        pad = 4 * GRID
        w, h = max(x1 - x0, GRID) + 2 * pad, max(y1 - y0, GRID) + 2 * pad
        scale = min(self.width() / w, self.height() / h)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), Qt.white)
        p.translate(self.width() / 2, self.height() / 2)
        p.scale(scale, scale)
        p.translate(-(x0 + x1) / 2, (y0 + y1) / 2)        # střed značky do středu widgetu (scéna: Y dolů)
        paint_symbol(p, self.symbol)
        r = 0.9
        for port in self.symbol.ports:
            p.setPen(QPen(PORT_COLOR, 0.3))
            p.setBrush(PORT_COLOR)
            p.drawEllipse(sp(port.x, port.y), r, r)
            p.setPen(PORT_COLOR)
            draw_text(p, port.x + 1.5, port.y + 1.5, port.name, 2.2, "left")
        p.end()


class SymbolEditorDialog(QDialog):
    def __init__(self, library, symbol_id: str, parent=None):
        super().__init__(parent)
        self.library = library
        self.original: Symbol = library.get_symbol(symbol_id)      # KeyError → volající ohlásí
        self.symbol: Symbol = se.editable_copy(self.original)
        self.saved_symbol: Symbol | None = None
        self._read_only = se.is_read_only(library, symbol_id)
        self._port_names: list[str] = []
        self._attr_keys: list[str] = []
        self.setWindowTitle(f"Upravit značku – {self.original.name} ({symbol_id})")
        self.resize(820, 560)

        lay = QVBoxLayout(self)
        if self._read_only:
            info = QLabel("Vestavěná nebo souborová značka knihovny se nepřepisuje – uloží se kopie do "
                          "uživatelské knihovny pod novým ID.")
            info.setWordWrap(True)
            info.setObjectName("builtin_info")
            lay.addWidget(info)
        body = QHBoxLayout()
        lay.addLayout(body, 1)
        self.preview = SymbolPreview(self.symbol)
        body.addWidget(self.preview, 1)

        right = QVBoxLayout()
        body.addLayout(right, 2)
        right.addWidget(QLabel("Porty (souřadnice v mm, mřížka 2,5 mm, Y nahoru)"))
        self.ports_table = QTableWidget(0, 4)
        self.ports_table.setHorizontalHeaderLabels(["Název", "X", "Y", "Směr"])
        self.ports_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.ports_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.ports_table.itemChanged.connect(self._port_item_changed)
        right.addWidget(self.ports_table)
        row = QHBoxLayout()
        b_add = QPushButton("Přidat port")
        b_add.clicked.connect(lambda: self.add_port())
        b_del = QPushButton("Smazat port")
        b_del.clicked.connect(self.remove_selected_port)
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addStretch(1)
        right.addLayout(row)

        right.addWidget(QLabel("Atributy"))
        self.attrs_table = QTableWidget(0, 4)
        self.attrs_table.setHorizontalHeaderLabels(["Klíč", "Popisek", "Výchozí hodnota", "Zobrazovat"])
        self.attrs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.attrs_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.attrs_table.itemChanged.connect(self._attr_item_changed)
        right.addWidget(self.attrs_table)
        row = QHBoxLayout()
        a_add = QPushButton("Přidat atribut")
        a_add.clicked.connect(self.add_attribute)
        a_del = QPushButton("Smazat atribut")
        a_del.clicked.connect(self.remove_selected_attribute)
        row.addWidget(a_add)
        row.addWidget(a_del)
        row.addStretch(1)
        right.addLayout(row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        b_save = QPushButton("Uložit")
        b_save.setDefault(True)
        b_save.clicked.connect(self.save)
        b_cancel = QPushButton("Zrušit")
        b_cancel.clicked.connect(self.reject)
        buttons.addWidget(b_save)
        buttons.addWidget(b_cancel)
        lay.addLayout(buttons)

        self._fill_ports()
        self._fill_attrs()

    # ---- pomocné ---------------------------------------------------------------
    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "Editor značky", text)

    def _refresh_preview(self) -> None:
        self.preview.set_symbol(self.symbol)

    @staticmethod
    def _num_item(v: float) -> QTableWidgetItem:
        return QTableWidgetItem(f"{v:g}")

    # ---- porty -------------------------------------------------------------------
    def _make_dir_combo(self, direction: str) -> QComboBox:
        cb = QComboBox()
        cb.addItems(list(DIRS))
        cb.setCurrentText(direction)
        cb.currentTextChanged.connect(lambda d, c=cb: self._port_dir_changed(c, d))
        return cb

    def _fill_ports(self) -> None:
        t = self.ports_table
        t.blockSignals(True)
        t.setRowCount(0)
        self._port_names = []
        for p in self.symbol.ports:
            r = t.rowCount()
            t.insertRow(r)
            self._port_names.append(p.name)
            t.setItem(r, 0, QTableWidgetItem(p.name))
            t.setItem(r, 1, self._num_item(p.x))
            t.setItem(r, 2, self._num_item(p.y))
            t.setCellWidget(r, 3, self._make_dir_combo(p.dir))
        t.blockSignals(False)
        self._refresh_preview()

    def _free_port_name(self) -> str:
        used = {p.name for p in self.symbol.ports}
        n = len(used) + 1
        while str(n) in used:
            n += 1
        return str(n)

    def add_port(self, name: str | None = None, x: float = 0.0, y: float = 0.0, direction: str = "E") -> Port | None:
        try:
            port = se.add_port(self.symbol, self._free_port_name() if name is None else name, x, y, direction)
        except se.SymbolEditError as ex:
            self._warn(str(ex))
            return None
        self._fill_ports()
        return port

    def _selected_row(self, table: QTableWidget) -> int:
        rows = table.selectionModel().selectedRows()
        return rows[0].row() if rows else table.currentRow()

    def remove_selected_port(self) -> None:
        r = self._selected_row(self.ports_table)
        if not 0 <= r < len(self._port_names):
            return
        try:
            se.remove_port(self.symbol, self._port_names[r])
        except se.SymbolEditError as ex:
            self._warn(str(ex))
            return
        self._fill_ports()

    def _port_item_changed(self, item: QTableWidgetItem) -> None:
        r, c = item.row(), item.column()
        if not 0 <= r < len(self._port_names):
            return
        name = self._port_names[r]
        t = self.ports_table
        error: str | None = None
        try:
            if c == 0:
                port = se.update_port(self.symbol, name, new_name=item.text())
                self._port_names[r] = port.name
            else:
                port = self.symbol.port(name)
                try:
                    val = float(item.text().replace(",", "."))
                except ValueError as ex:
                    raise se.SymbolEditError("Souřadnice musí být číslo.") from ex
                x, y = (val, port.y) if c == 1 else (port.x, val)
                se.move_port(self.symbol, name, x, y)
        except se.SymbolEditError as ex:
            error = str(ex)
        finally:
            port = self.symbol.port(self._port_names[r])
            t.blockSignals(True)
            try:
                t.item(r, 0).setText(port.name)
                t.item(r, 1).setText(f"{port.x:g}")
                t.item(r, 2).setText(f"{port.y:g}")
            finally:
                t.blockSignals(False)
            self._refresh_preview()
        if error:
            self._warn(error)

    def _port_dir_changed(self, combo: QComboBox, direction: str) -> None:
        for r in range(self.ports_table.rowCount()):
            if self.ports_table.cellWidget(r, 3) is combo:
                try:
                    se.update_port(self.symbol, self._port_names[r], direction=direction)
                except se.SymbolEditError as ex:
                    self._warn(str(ex))
                break
        self._refresh_preview()

    # ---- atributy ----------------------------------------------------------------
    def _fill_attrs(self) -> None:
        t = self.attrs_table
        t.blockSignals(True)
        t.setRowCount(0)
        self._attr_keys = []
        for a in self.symbol.attributes:
            r = t.rowCount()
            t.insertRow(r)
            self._attr_keys.append(a.key)
            key = QTableWidgetItem(a.key)
            key.setFlags(key.flags() & ~Qt.ItemIsEditable)
            t.setItem(r, 0, key)
            t.setItem(r, 1, QTableWidgetItem(a.label))
            t.setItem(r, 2, QTableWidgetItem(a.default))
            show = QTableWidgetItem()
            show.setFlags((show.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
            show.setCheckState(Qt.Checked if a.show else Qt.Unchecked)
            t.setItem(r, 3, show)
        t.blockSignals(False)

    def add_attribute(self) -> None:
        key, ok = QInputDialog.getText(self, "Nový atribut", "Klíč atributu (např. power):")
        if not ok:
            return
        if any(a.key == key.strip() for a in self.symbol.attributes):
            self._warn(f"Atribut „{key.strip()}“ už na značce je.")
            return
        try:
            se.set_attribute(self.symbol, key)
        except se.SymbolEditError as ex:
            self._warn(str(ex))
            return
        self._fill_attrs()

    def remove_selected_attribute(self) -> None:
        r = self._selected_row(self.attrs_table)
        if not 0 <= r < len(self._attr_keys):
            return
        try:
            se.remove_attribute(self.symbol, self._attr_keys[r])
        except se.SymbolEditError as ex:
            self._warn(str(ex))
            return
        self._fill_attrs()

    def _attr_item_changed(self, item: QTableWidgetItem) -> None:
        r, c = item.row(), item.column()
        if not 0 <= r < len(self._attr_keys) or c == 0:
            return
        key = self._attr_keys[r]
        try:
            if c == 1:
                se.set_attribute(self.symbol, key, label=item.text())
            elif c == 2:
                se.set_attribute(self.symbol, key, default=item.text())
            else:
                se.set_attribute(self.symbol, key, show=item.checkState() == Qt.Checked)
        except se.SymbolEditError as ex:
            self._warn(str(ex))
            self._fill_attrs()

    # ---- uložení -----------------------------------------------------------------
    def save(self) -> bool:
        issues = se.check(self.symbol)
        if issues:
            self._warn("Značku nelze uložit:\n- " + "\n- ".join(issues))
            return False
        lost = se.removed_ports(self.original, self.symbol)
        if lost and not self._read_only:
            answer = QMessageBox.question(
                self, "Ubyly porty",
                f"Zmizely porty: {', '.join(lost)}.\n\nVodiče v projektech, které tuto značku používají, "
                "zůstanou na neexistujících portech (zobrazí se jako „název?“); nic se automaticky nepřepojuje.\n\n"
                "Uložit přesto?")
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            self.saved_symbol = se.save_user_symbol(self.library, self.symbol)
        except (se.SymbolEditError, ValueError) as ex:
            self._warn(str(ex))
            return False
        self.accept()
        return True

