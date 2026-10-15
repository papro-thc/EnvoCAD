"""Dialogy editoru."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envocad.model import multipole as mp
from envocad.model.project import ENCLOSURE_PARAMS, MODULE_WIDTH, Layout, Sheet, Wire
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


CONDUCTOR_PRESETS = ["L1 L2 L3 N PE", "L1 L2 L3 PE", "L1 L2 L3 N", "L1 N PE", "L1 N", "L1", "N", "PE",
                     "DC+ DC-", "DC+", "DC-", "PEN"]


class WireDialog(AttrDialog):
    """Parametry vodiče + seznam žil (pro vícepólový pohled a svorkovnice)."""

    def __init__(self, attrs: dict[str, str], conductors: list[str], parent=None,
                 title: str = "Vodič", heading: str = ""):
        from envocad.model.project import WIRE_ATTRIBUTES
        super().__init__(WIRE_ATTRIBUTES, attrs, parent, title, heading)
        self.cond = QComboBox()
        self.cond.setEditable(True)
        self.cond.addItems(CONDUCTOR_PRESETS)
        self.cond.setCurrentText(" ".join(conductors))
        self.cond.setToolTip("Žíly vodiče oddělené mezerou – každá se ve vícepólu kreslí zvlášť")
        form = self.layout().itemAt(1 if heading else 0).layout()
        form.addRow("Žíly (vícepól)", self.cond)

    def conductors(self) -> list[str]:
        return mp.parse_conductors(self.cond.currentText())


class TerminalsDialog(QDialog):
    """Přiřazení svorek žilám vodiče: řádek = žíla, sloupce = svorka u začátku / konce."""

    def __init__(self, sheet: Sheet, wire: Wire, parent=None):
        super().__init__(parent)
        self.wire = wire
        ea, eb = sheet.element(wire.a.element_id), sheet.element(wire.b.element_id)
        self.setWindowTitle(f"Svorky vodiče {wire.attrs.get('ref', '')}")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{wire.attrs.get('ref', 'vodič')}</b>  {ea.ref}:{wire.a.port} → {eb.ref}:{wire.b.port}"
                             "<br><small>Svorka ve tvaru X1:3 (svorkovnice:číslo) nebo F2:1 (přístroj:svorka).</small>"))
        conds = mp.wire_conductors(wire)
        self.table = QTableWidget(len(conds), 3)
        self.table.setHorizontalHeaderLabels(["Žíla", f"Svorka u {ea.ref or 'A'}", f"Svorka u {eb.ref or 'B'}"])
        for r, c in enumerate(conds):
            it = QTableWidgetItem(c)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QTableWidgetItem(mp.terminal_text(wire, c, "a")))
            self.table.setItem(r, 2, QTableWidgetItem(mp.terminal_text(wire, c, "b")))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for r in range(self.table.rowCount()):
            c = self.table.item(r, 0).text()
            a = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
            b = (self.table.item(r, 2).text() if self.table.item(r, 2) else "").strip()
            t = {k: v for k, v in (("a", a), ("b", b)) if v}
            if t:
                out[c] = t
        return out


class StripDialog(QDialog):
    """Svorkovnice: přehled svorek jedné svorkovnice na listu a editace můstků (propojů)."""

    def __init__(self, project, sheet: Sheet, parent=None, strip: str = ""):
        super().__init__(parent)
        self.project, self.sheet = project, sheet
        self.setWindowTitle("Svorkovnice a můstky")
        self.setMinimumSize(640, 460)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Svorkovnice:"))
        self.strip = QComboBox()
        strips = sorted({e.ref for e in sheet.elements if e.symbol_id in mp.TERMINAL_SYMBOLS and e.ref},
                        key=lambda r: (len(r), r))
        self.strip.addItems(strips)
        if strip in strips:
            self.strip.setCurrentText(strip)
        top.addWidget(self.strip, 1)
        lay.addLayout(top)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Svorka", "Žíla", "Vnitřní strana", "Vnější strana", "Můstek"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.table, 1)
        lay.addWidget(QLabel("Můstky – jedna skupina na řádek, čísla svorek oddělená pomlčkou (např. <b>1-6-11</b>):"))
        from PySide6.QtWidgets import QPlainTextEdit
        self.bridges = QPlainTextEdit()
        self.bridges.setMaximumHeight(110)
        lay.addWidget(self.bridges)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._shown = ""
        self.strip.currentTextChanged.connect(self._load)
        self._load(self.strip.currentText())

    def _rows(self, strip: str) -> list[list[str]]:
        rows: list[list[str]] = []
        s = self.sheet
        for e in s.elements:
            if e.ref != strip or e.symbol_id not in mp.TERMINAL_SYMBOLS:
                continue
            ends: dict[str, list[tuple]] = {}  # port → [(wire, side)]
            for w in s.wires:
                for side, end in (("a", w.a), ("b", w.b)):
                    if end.element_id == e.id:
                        ends.setdefault(end.port, []).append((w, side))
            slots = sorted({c for lst in ends.values() for w, _ in lst for c in mp.wire_conductors(w)}, key=mp.canon_key)
            nums = mp.terminal_numbers(e, len(slots)) if mp.is_terminal_block(e) else [""] * len(slots)
            ports = [p.name for p in self._symbol_ports(e)]
            for c, num in zip(slots, nums):
                conn = []
                for port in ports[:2]:
                    txt = []
                    for w, side in ends.get(port, []):
                        if c in mp.wire_conductors(w):
                            other = w.b if side == "a" else w.a
                            try:
                                oe = s.element(other.element_id)
                                txt.append(f"{oe.ref or oe.symbol_id}:{other.port}" + (f" ({w.attrs['ref']})" if w.attrs.get("ref") else ""))
                            except KeyError:
                                pass
                    conn.append(", ".join(txt))
                if not mp.is_terminal_block(e):
                    # přívod/vývod/PE lišta: číslo z ručního přiřazení na vodiči
                    for w, side in [x for lst in ends.values() for x in lst]:
                        t = mp.terminal_text(w, c, side)
                        if t:
                            num = t.partition(":")[2] or t
                            break
                bridge = self.project.bridge_of(strip, num) if num else []
                rows.append([num, c, conn[0] if conn else "", conn[1] if len(conn) > 1 else "",
                             "-".join(bridge) if bridge else ""])
        rows.sort(key=lambda r: (not r[0].isdigit(), int(r[0]) if r[0].isdigit() else 0, r[0]))
        return rows

    def _symbol_ports(self, e):
        from envocad.library.store import LibraryStore
        try:
            lib = self.parent().library if self.parent() is not None and hasattr(self.parent(), "library") else LibraryStore()
            return lib.get_symbol(e.symbol_id).ports
        except Exception:  # noqa: BLE001
            return []

    def _load(self, strip: str) -> None:
        rows = self._rows(strip) if strip else []
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.bridges.setPlainText("\n".join("-".join(g) for g in self.project.bridge_groups(strip)))
        self._shown = strip

    def values(self) -> tuple[str, list[list[str]]]:
        groups = []
        for line in self.bridges.toPlainText().splitlines():
            toks = [t.strip() for t in line.replace(",", "-").replace(" ", "-").split("-") if t.strip()]
            if len(toks) >= 2:
                groups.append(toks)
        return self._shown, groups


class ElementDialog(AttrDialog):
    def __init__(self, symbol: Symbol, attrs: dict[str, str], parent=None, title: str | None = None,
                 library=None, component_id: str | None = None):
        super().__init__(symbol.attributes, attrs, parent, title or f"Vložit: {symbol.name}",
                         f"<b>{symbol.name}</b> <small>({symbol.id})</small>")
        self.library = library
        self.symbol = symbol
        self.component_id = component_id
        if library is not None:
            row = QHBoxLayout()
            self.comp_label = QLabel(self._comp_text())
            self.comp_label.setWordWrap(True)
            btn = QPushButton("Vybrat artikl z knihovny…")
            btn.clicked.connect(self.pick_component)
            clear = QPushButton("Zrušit")
            clear.clicked.connect(self._clear_component)
            row.addWidget(self.comp_label, 1)
            row.addWidget(btn)
            row.addWidget(clear)
            self.layout().insertLayout(1, row)

    def _comp_text(self) -> str:
        if self.library is not None and self.component_id:
            c = self.library.component(self.component_id)
            if c:
                return f"Artikl: <b>{c.label}</b>"
        return "<i>Artikl nepřiřazen</i> – parametry lze vyplnit ručně nebo vybrat z knihovny"

    def pick_component(self) -> None:
        from envocad.ui.component_picker import ComponentPicker
        preset = {k: self._edits[k].text() for k in ("in_", "poles", "char") if k in self._edits}
        dlg = ComponentPicker(self.library, symbol_id=self.symbol.id, parent=self, preset_filters=preset)
        if dlg.exec() == ComponentPicker.Accepted and dlg.selected:
            self.apply_component(dlg.selected)

    def apply_component(self, comp) -> None:
        """Propíše parametry artiklu do polí dialogu (uživatel je ještě může upravit)."""
        from envocad.library.components import PARAM_TO_ATTR
        self.component_id = comp.id
        src = {"part_number": comp.part_number, "manufacturer": comp.manufacturer, **comp.params}
        for pkey, akey in PARAM_TO_ATTR.items():
            v = src.get(pkey)
            if v not in (None, "") and akey in self._edits:
                self._edits[akey].setText(str(v))
        self.comp_label.setText(self._comp_text())

    def _clear_component(self) -> None:
        self.component_id = None
        self.comp_label.setText(self._comp_text())


class EnclosurePanel(QWidget):
    """Rozměry a parametry skříně – nemodální panel vedle rozložení; změny se promítají hned."""

    changed = Signal()

    def __init__(self, sheet: Sheet, parent=None, library=None):
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
        self.library = library
        name_row = QHBoxLayout()
        name_row.addWidget(self.name, 1)
        if library is not None:
            pick = QPushButton("Z knihovny…")
            pick.clicked.connect(self.pick_enclosure)
            name_row.addWidget(pick)
        f1.addRow("Označení skříně", name_row)
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

    def pick_enclosure(self) -> None:
        from envocad.ui.component_picker import ComponentPicker
        dlg = ComponentPicker(self.library, category="enclosure", parent=self, title="Vybrat skříň z knihovny")
        if dlg.exec() != ComponentPicker.Accepted or not dlg.selected:
            return
        c = dlg.selected
        self.name.setText(f"{c.manufacturer} {c.part_number}")
        mapping = {"manufacturer": c.manufacturer, "type": c.part_number}
        for k in ("width_mm", "height_mm", "depth_mm", "ip", "ik", "material", "mounting", "door"):
            if c.params.get(k):
                mapping[k] = c.params[k]
        for k, v in mapping.items():
            if k in self._edits:
                self._edits[k].setText(str(v))
        if c.num("rows"):
            self.rows.setValue(int(c.num("rows")))
        if c.num("modules_per_row"):
            self.mods.setValue(int(c.num("modules_per_row")))
        self._apply()

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

    def __init__(self, sheet: Sheet, parent=None, library=None):
        super().__init__(parent)
        self.setWindowTitle(f"Skříň rozvaděče – {sheet.name}")
        self.setMinimumWidth(480)
        self.panel = EnclosurePanel(sheet, library=library)
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
