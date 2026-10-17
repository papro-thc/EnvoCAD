"""Výběr artiklu z knihovny – tabulka s filtrem (výrobce, text, In, póly, charakteristika)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QFont, QPalette
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

# Katalog FV (docs/design/katalog_fv.md §4): sloupce podle kategorie. Klíč začínající „=“ je složený sloupec.
MODULE_CATEGORIES = ("pv_module",)
INVERTER_CATEGORIES = ("inverter", "inverter_hybrid")
MODULE_COLUMNS = [("manufacturer", "Výrobce"), ("part_number", "Typ"), ("p_wp", "P [Wp]"), ("voc_v", "Voc [V]"),
                  ("isc_a", "Isc [A]"), ("vmp_v", "Vmp [V]"), ("imp_a", "Imp [A]"), ("beta_voc", "β Voc [%/K]"),
                  ("u_sys_max_v", "Usys [V]"), ("technology", "Technologie"), ("=size", "Š×V [mm]"),
                  ("source", "Zdroj")]
INVERTER_COLUMNS = [("manufacturer", "Výrobce"), ("part_number", "Typ"), ("p_ac_kw", "P AC [kW]"),
                    ("p_dc_max_kwp", "P DC max [kWp]"), ("phases", "Fáze"), ("mppt", "MPPT"),
                    ("strings_per_mppt", "Str./MPPT"), ("u_dc_max_v", "U DC max [V]"), ("=mppt_window", "MPPT [V]"),
                    ("i_mppt_max_a", "I/MPPT [A]"), ("isc_mppt_max_a", "Isc/MPPT [A]"), ("=hybrid", "Hybrid"),
                    ("source", "Zdroj")]
NUMERIC_COLUMNS = {"in_", "poles", "icu_ka", "idn_ma", "modules", "p_loss_w", "p_ac_kw", "e_kwh", "width_mm",
                   "height_mm", "depth_mm", "p_wp", "voc_v", "isc_a", "vmp_v", "imp_a", "beta_voc", "u_sys_max_v",
                   "p_dc_max_kwp", "phases", "mppt", "strings_per_mppt", "u_dc_max_v", "i_mppt_max_a",
                   "isc_mppt_max_a", "=size", "=mppt_window"}
UNVERIFIED_SOURCES = ("web", "seed")


def _has(c: Component, *keys: str) -> bool:
    return all(c.num(k) is not None for k in keys)


def incomplete_reasons(c: Component) -> list[str]:
    """Důvody, proč je řádek FV modulu / střídače neúplný nebo neověřený (prázdné = v pořádku nebo jiná kategorie)."""
    out: list[str] = []
    if c.category in MODULE_CATEGORIES:
        out += [f"chybí {lab}" for key, lab in (("voc_v", "Voc"), ("isc_a", "Isc")) if not _has(c, key)]
    elif c.category in INVERTER_CATEGORIES:
        if not _has(c, "u_dc_max_v"):
            out.append("chybí U DC max")
        if not _has(c, "u_mppt_min_v", "u_mppt_max_v"):
            out.append("chybí okno MPPT")
    else:
        return out
    if c.source in UNVERIFIED_SOURCES:
        out.append(f"neověřeno (zdroj: {c.source}) – zkontrolujte podle datasheetu")
    return out


class ComponentPicker(QDialog):
    def __init__(self, library: LibraryStore, symbol_id: str | None = None, category: str | None = None,
                 parent=None, preset_filters: dict[str, str] | None = None, title: str = "Vybrat artikl",
                 categories: tuple[str, ...] | None = None):
        super().__init__(parent)
        self.categories = tuple(categories) if categories else None
        self.kind = ("module" if self.categories and set(self.categories) <= set(MODULE_CATEGORIES) else
                     "inverter" if self.categories and set(self.categories) <= set(INVERTER_CATEGORIES) else "")
        self.columns = {"module": MODULE_COLUMNS, "inverter": INVERTER_COLUMNS}.get(self.kind, COLUMNS)
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
        self.p_from = QLineEdit(placeholderText="Výkon od")
        self.p_to = QLineEdit(placeholderText="do")
        self.p_unit = QLabel("[Wp]" if self.kind == "module" else "[kW]")
        self.phases = QComboBox()
        self.phases.addItems(["Fáze: vše", "1", "3"])
        for w in (self.p_from, self.p_to):
            w.setMaximumWidth(80)
        if self.kind:
            widgets = [self.search, self.manufacturer, self.p_from, self.p_to, self.p_unit]
            if self.kind == "inverter":
                widgets.append(self.phases)
            for w in (self.in_, self.poles, self.char):
                w.setVisible(False)
        else:
            widgets = [self.search, self.manufacturer, self.in_, self.poles, self.char]
            for w in (self.p_from, self.p_to, self.p_unit, self.phases):
                w.setVisible(False)
        for w in widgets:
            f.addWidget(w)
        self.only_compatible = QComboBox()
        self.only_compatible.addItems(["Jen pro tuto značku", "Všechny artikly"])
        f.addWidget(self.only_compatible)
        root.addLayout(f)

        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels([c[1] for c in self.columns])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        if not self.kind:
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
        for w in (self.search, self.in_, self.p_from, self.p_to):
            w.textChanged.connect(self.refresh)
        for w in (self.manufacturer, self.poles, self.char, self.only_compatible, self.phases):
            w.currentIndexChanged.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._show_info)
        self.refresh()

    def _load(self) -> list[Component]:
        return self.library.components()

    def _filtered(self) -> list[Component]:
        out = self._all
        if self.only_compatible.currentIndex() == 0:
            if self.categories:
                out = [c for c in out if c.category in self.categories]
            elif self._symbol_id:
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
        if self.kind:
            key = "p_wp" if self.kind == "module" else "p_ac_kw"
            for edit, cmp in ((self.p_from, lambda v, lim: v >= lim), (self.p_to, lambda v, lim: v <= lim)):
                try:
                    lim = float(edit.text().strip().replace(",", ".")) if edit.text().strip() else None
                except ValueError:
                    lim = None
                if lim is not None:
                    out = [c for c in out if c.num(key) is not None and cmp(c.num(key), lim)]
            if self.kind == "inverter" and self.phases.currentIndex() > 0:
                out = [c for c in out if c.num("phases") == float(self.phases.currentText())]
        if self.poles.currentIndex() > 0 and not self.kind:
            out = [c for c in out if (c.params.get("poles") or "") == self.poles.currentText()]
        if self.char.currentIndex() > 0 and not self.kind:
            out = [c for c in out if (c.params.get("char") or "") == self.char.currentText()]
        if self.kind:
            key = "p_wp" if self.kind == "module" else "p_ac_kw"
            return sorted(out, key=lambda c: (c.manufacturer, c.num(key) or 0, c.part_number))
        return sorted(out, key=lambda c: (c.manufacturer, c.num("in_") or 0, c.part_number))

    @staticmethod
    def _composite(key: str, c: Component) -> str:
        g = c.params.get
        if key == "=size":
            w, h = g("width_mm"), g("height_mm")
            return f"{w} × {h}" if w and h else ""
        if key == "=mppt_window":
            lo, hi = g("u_mppt_min_v"), g("u_mppt_max_v")
            return f"{lo}–{hi}" if lo and hi else ""
        if key == "=hybrid":
            return "ano" if c.category == "inverter_hybrid" else ""
        return ""

    def refresh(self) -> None:
        rows = self._filtered()
        self._rows = rows
        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            vals = {"manufacturer": c.manufacturer, "part_number": c.part_number, "name": c.name, "source": c.source,
                    **c.params}
            reasons = incomplete_reasons(c)
            for col, (key, _) in enumerate(self.columns):
                text = self._composite(key, c) if key.startswith("=") else str(vals.get(key, "") or "")
                it = QTableWidgetItem(text)
                if key in NUMERIC_COLUMNS:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if reasons:   # neúplný / neověřený řádek: šedě kurzívou, důvod v tooltipu
                    f = QFont(it.font())
                    f.setItalic(True)
                    it.setFont(f)
                    it.setForeground(QBrush(self.palette().color(QPalette.Disabled, QPalette.Text)))
                    it.setToolTip("; ".join(reasons))
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
