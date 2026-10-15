"""Dialogy editoru."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from envocad.model.project import ENCLOSURE_PARAMS, MODULE_WIDTH, Layout, Sheet
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


class EnclosurePanel(QWidget):
    """Rozměry a parametry skříně – nemodální panel vedle rozložení; změny se promítají hned."""

    changed = Signal()

    def __init__(self, sheet: Sheet, parent=None):
        super().__init__(parent)
        self._sheet = sheet
        lay = sheet.layout
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        g1 = QGroupBox("Rozložení")
        f1 = QFormLayout(g1)
        f1.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.name = QLineEdit(lay.enclosure)
        self.name.setPlaceholderText("např. Hager Volta VU36, Schrack BK085…")
        self.rows = QSpinBox(minimum=1, maximum=20, value=lay.rows)
        self.mods = QSpinBox(minimum=4, maximum=120, value=lay.modules_per_row)
        f1.addRow("Označení skříně", self.name)
        f1.addRow("Počet řad DIN lišt", self.rows)
        f1.addRow("Modulů v řadě (17,5 mm)", self.mods)
        self.info = QLabel()
        self.info.setWordWrap(True)
        f1.addRow(self.info)
        root.addWidget(g1)

        g2 = QGroupBox("Parametry skříně")
        f2 = QFormLayout(g2)
        f2.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        hints = {"mounting": "nástěnná / zapuštěná / stojanová / volně stojící", "material": "plast / ocel / nerez",
                 "door": "plné / průhledné / bez dveří"}
        self._edits: dict[str, QLineEdit] = {}
        for key, label, default in ENCLOSURE_PARAMS:
            ed = QLineEdit(lay.params.get(key, default))
            ed.setPlaceholderText(hints.get(key, default))
            ed.setMinimumWidth(140)
            if key in hints:
                ed.setToolTip(hints[key])
            self._edits[key] = ed
            f2.addRow(label, ed)
        root.addWidget(g2)

        g3 = QGroupBox("Oteplení (IEC 60890, orientačně)")
        v3 = QVBoxLayout(g3)
        self.thermal = QLabel()
        self.thermal.setWordWrap(True)
        v3.addWidget(self.thermal)
        root.addWidget(g3)
        root.addStretch()

        self.name.editingFinished.connect(self._apply)
        self.rows.valueChanged.connect(self._apply)
        self.mods.valueChanged.connect(self._apply)
        for ed in self._edits.values():
            ed.editingFinished.connect(self._apply)
        self.refresh()

    def refresh(self) -> None:
        """Přepočítá informační texty (po změně rozložení nebo přístrojů)."""
        from envocad.model.thermal import temperature_rise
        lay = self._sheet.layout
        total = lay.total_modules
        used = lay.used_modules(self._sheet)
        pct = (used / total * 100) if total else 0
        self.info.setText(f"{total} modulů celkem, obsazeno {used:g} ({pct:.0f} %), rezerva {total - used:g} M; "
                          f"užitná šířka řady {lay.modules_per_row * MODULE_WIDTH:g} mm, "
                          f"skříň {lay.width_mm:g} × {lay.height_mm:g} mm")
        try:
            rdf = float((lay.params.get("rdf") or "0.8").replace(",", "."))
            t_amb = float((lay.params.get("t_ambient") or "35").replace(",", "."))
        except ValueError:
            rdf, t_amb = 0.8, 35.0
        r = temperature_rise(self._sheet, rdf=rdf, t_ambient_c=t_amb)
        txt = (f"Ztráty přístrojů ΣPv = {r.p_devices_w:g} W, celkem s vodiči {r.p_total_w:g} W\n"
               f"Účinná chladicí plocha Ae = {r.ae_m2:g} m²\n"
               f"Oteplení: střed Δt = {r.dt_mid_k:g} K, horní část Δt = {r.dt_top_k:g} K "
               f"→ ≈ {r.t_top_c:g} °C při okolí {r.t_ambient_c:g} °C\n"
               f"Hodnocení: {r.verdict()}")
        if r.notes:
            txt += "\n" + "; ".join(r.notes)
        self.thermal.setText(txt)

    def _apply(self, *_) -> None:
        self.apply()
        self.refresh()
        self.changed.emit()

    def apply(self) -> Layout:
        lay = self._sheet.layout
        lay.enclosure = self.name.text().strip()
        lay.rows = self.rows.value()
        lay.modules_per_row = self.mods.value()
        lay.params = {k: e.text().strip() for k, e in self._edits.items() if e.text().strip()}
        lay.placements = [p for p in lay.placements if p.row < lay.rows]
        return lay


class EnclosureDialog(QDialog):
    """Totéž jako panel, ale modálně (z menu List)."""

    def __init__(self, sheet: Sheet, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Skříň rozvaděče – {sheet.name}")
        self.setMinimumWidth(480)
        self.panel = EnclosurePanel(sheet)
        for sig in (self.panel.name.editingFinished, self.panel.rows.valueChanged, self.panel.mods.valueChanged):
            pass
        lay = QVBoxLayout(self)
        lay.addWidget(self.panel)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        # pohodlné aliasy pro testy
        self.name, self.rows, self.mods, self.info, self._edits = (self.panel.name, self.panel.rows, self.panel.mods,
                                                                   self.panel.info, self.panel._edits)

    def apply(self) -> Layout:
        return self.panel.apply()
