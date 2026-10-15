"""Dialogy editoru."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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

    used_refs: set[str] | None = None  # označení už použitá v projektu (varování na duplicitu)
    own_ref: str = ""                  # vlastní původní označení (není duplicita)

    def __init__(self, attributes: list[Attribute], attrs: dict[str, str], parent=None,
                 title: str = "Parametry", heading: str = ""):
        super().__init__(parent)
        self.own_ref = attrs.get("ref", "")
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

    def accept(self) -> None:
        ref = self.values().get("ref", "")
        if ref and self.used_refs and ref != self.own_ref and ref in self.used_refs:
            from PySide6.QtWidgets import QMessageBox
            r = QMessageBox.question(self, "Duplicitní označení",
                                     f"Označení <b>{ref}</b> už v projektu existuje. Použít přesto?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        super().accept()


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


class CableDialog(QDialog):
    """Kabel jako objekt: žíly s čísly a barvami, stínění, délka/trasa/poznámka, artikl kabelu z knihovny."""

    def __init__(self, cable, parent=None, library=None):
        super().__init__(parent)
        from envocad.model.project import Cable
        self.cable: Cable = cable
        self.library = library
        self.component_id = cable.component_id
        self.setWindowTitle(f"Kabel {cable.ref}")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.type = QLineEdit(cable.type)
        self.cross = QLineEdit(cable.cross)
        self.length = QLineEdit(cable.length)
        self.route = QLineEdit(cable.route)
        self.note = QLineEdit(cable.note)
        form.addRow("Označení", QLabel(f"<b>{cable.ref}</b>"))
        form.addRow("Typ kabelu", self.type)
        form.addRow("Průřez [mm²]", self.cross)
        form.addRow("Délka [m]", self.length)
        form.addRow("Trasa / uložení", self.route)
        form.addRow("Poznámka", self.note)
        self.shield = QCheckBox("stíněný kabel")
        self.shield.setChecked(cable.shield)
        form.addRow("Stínění", self.shield)
        lay.addLayout(form)
        if library is not None:
            row = QHBoxLayout()
            self.comp_label = QLabel(self._comp_text())
            btn = QPushButton("Vybrat kabel z knihovny…")
            btn.clicked.connect(self.pick_component)
            row.addWidget(self.comp_label, 1)
            row.addWidget(btn)
            lay.addLayout(row)
        lay.addWidget(QLabel("Žíly (barvy dle ČSN 33 0165 – lze přepsat):"))
        self.table = QTableWidget(len(cable.cores), 3)
        self.table.setHorizontalHeaderLabels(["Žíla", "Číslo", "Barva"])
        for r, c in enumerate(cable.cores):
            it = QTableWidgetItem(c.name)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QTableWidgetItem(c.number))
            self.table.setItem(r, 2, QTableWidgetItem(c.color))
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _comp_text(self) -> str:
        if self.library is not None and self.component_id:
            c = self.library.component(self.component_id)
            if c:
                return f"Artikl: <b>{c.label}</b>"
        return "Artikl: –"

    def pick_component(self) -> None:
        from envocad.ui.component_picker import ComponentPicker
        dlg = ComponentPicker(self.library, category="cable", parent=self, title="Vybrat kabel")
        if dlg.exec() == ComponentPicker.Accepted and dlg.selected is not None:
            comp = dlg.selected
            self.component_id = comp.id
            self.type.setText(comp.part_number)
            if comp.params.get("cross_mm2"):
                self.cross.setText(comp.params["cross_mm2"])
            self.comp_label.setText(self._comp_text())

    def values(self) -> dict:
        d = self.cable.to_dict()
        d.update(type=self.type.text().strip(), cross=self.cross.text().strip(), length=self.length.text().strip(),
                 route=self.route.text().strip(), note=self.note.text().strip(), shield=self.shield.isChecked(),
                 component_id=self.component_id)
        d["cores"] = [{"name": self.table.item(r, 0).text(),
                       "number": (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip(),
                       "color": (self.table.item(r, 2).text() if self.table.item(r, 2) else "").strip()}
                      for r in range(self.table.rowCount())]
        return d


class ProjectWizard(QDialog):
    """Průvodce novým projektem FVE → specifikace pro `envocad.generate.build_project`."""

    def __init__(self, parent=None, library=None):
        super().__init__(parent)
        self.library = library
        self.setWindowTitle("Nový projekt FVE – průvodce")
        self.setMinimumWidth(560)
        try:
            from envocad.settings import load_settings
            std = load_settings()["standard"]
        except Exception:  # noqa: BLE001
            std = {}
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit("FVE ")
        self.investor = QLineEdit()
        self.place = QLineEdit()
        self.order = QLineEdit()
        self.author = QLineEdit(str(std.get("author", "")))
        form.addRow("Název projektu", self.name)
        form.addRow("Investor", self.investor)
        form.addRow("Místo", self.place)
        form.addRow("Číslo zakázky", self.order)
        form.addRow("Zpracoval", self.author)
        self.mod_type = QLineEdit()
        self.mod_p = QLineEdit("450")
        self.mod_voc = QLineEdit("49.5")
        self.mod_vmp = QLineEdit("41.5")
        self.mod_isc = QLineEdit("13.9")
        form.addRow("FV modul – typ", self.mod_type)
        form.addRow("P modulu [Wp]", self.mod_p)
        form.addRow("Uoc / Umpp modulu [V]", self._pair(self.mod_voc, self.mod_vmp))
        form.addRow("Isc modulu [A]", self.mod_isc)
        self.inv_type = QLineEdit()
        self.inv_p = QLineEdit("25")
        self.inv_udc = QLineEdit("1100")
        self.inv_mppt = QLineEdit("200")
        self.inv_mppt_max = QLineEdit("1000")
        self.inv_imax = QLineEdit("30")
        self.strings = QLineEdit("20,20,18,18; 20,20")
        self.strings.setToolTip("Stringy po střídačích: počty modulů oddělené čárkou, střídače středníkem")
        form.addRow("Střídač – typ", self.inv_type)
        form.addRow("P AC střídače [kW]", self.inv_p)
        form.addRow("U DC max / MPPT min / MPPT max [V]", self._triple(self.inv_udc, self.inv_mppt, self.inv_mppt_max))
        form.addRow("I max na MPPT [A]", self.inv_imax)
        form.addRow("Stringy (moduly; střídače ;)", self.strings)
        self.dc_cable = QLineEdit(str(std.get("dc_cable") or "H1Z2Z2-K 1x6"))
        self.dc_cross = QLineEdit(str(std.get("dc_cross") or "6"))
        self.dc_len = QLineEdit("30")
        form.addRow("DC kabel / průřez / délka string → 1. DC rozvaděč [m]", self._triple(self.dc_cable, self.dc_cross, self.dc_len))
        self.dc_route_boxes = QLineEdit("1")
        self.dc_route_len = QLineEdit("20")
        self.dc_route_boxes.setToolTip("DC rozvaděče po trase (odpínač DC + SPD na každý string); 0 = žádný")
        form.addRow("DC rozvaděčů po trase / délka kabelu mezi nimi [m]", self._pair(self.dc_route_boxes, self.dc_route_len))
        self.dc_tech_box = QCheckBox("DC rozvaděč u technologie (pojistkové odpínače + SPD)")
        self.dc_tech_box.setChecked(True)
        self.dc_tech_len = QLineEdit("5")
        self.dc_fuse_in = QLineEdit("15")
        self.dc_spd = QLineEdit("T2")
        form.addRow("", self.dc_tech_box)
        form.addRow("Délka ke střídači [m] / In pojistek [A] / SPD DC", self._triple(self.dc_tech_len, self.dc_fuse_in, self.dc_spd))
        self.ac_cable = QLineEdit(str(std.get("ac_cable") or "CYKY-J 5x16"))
        self.ac_cross = QLineEdit(str(std.get("ac_cross") or "16"))
        self.ac_len = QLineEdit("30")
        form.addRow("AC kabel střídač–rozvaděč / průřez / délka", self._triple(self.ac_cable, self.ac_cross, self.ac_len))
        self.ac_breaker = QLineEdit("40")
        self.ac_main = QLineEdit("125")
        form.addRow("In jističe střídače / hlavního vypínače [A]", self._pair(self.ac_breaker, self.ac_main))
        self.grid_cable = QLineEdit(str(std.get("grid_cable") or "CYKY-J 5x35"))
        self.grid_cross = QLineEdit(str(std.get("grid_cross") or "35"))
        self.grid_len = QLineEdit("20")
        form.addRow("Kabel do HDS / průřez / délka", self._triple(self.grid_cable, self.grid_cross, self.grid_len))
        self.dso = QLineEdit("")
        form.addRow("Distributor (DSO)", self.dso)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    @staticmethod
    def _pair(a, b) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(a)
        h.addWidget(b)
        return w

    @staticmethod
    def _triple(a, b, c) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        for x in (a, b, c):
            h.addWidget(x)
        return w

    @staticmethod
    def _num(ed: QLineEdit):
        t = ed.text().strip().replace(",", ".")
        try:
            return float(t) if "." in t else int(t)
        except ValueError:
            return t

    def spec(self) -> dict:
        inv_strings = []
        for part in self.strings.text().split(";"):
            nums = [int(x) for x in part.replace(" ", "").split(",") if x.strip().isdigit()]
            if nums:
                inv_strings.append(nums)
        inverters = [{"ref": f"T{i + 1}", "type": self.inv_type.text().strip(), "p_ac": self._num(self.inv_p),
                      "u_dc_max": self._num(self.inv_udc), "u_mppt_min": self._num(self.inv_mppt),
                      "u_mppt_max": self._num(self.inv_mppt_max), "i_mppt_max": self._num(self.inv_imax),
                      "strings": st} for i, st in enumerate(inv_strings or [[1]])]
        return {
            "name": self.name.text().strip() or "Nový projekt FVE",
            "meta": {"investor": self.investor.text().strip(), "place": self.place.text().strip(),
                     "order": self.order.text().strip(), "author": self.author.text().strip()},
            "module": {"type": self.mod_type.text().strip(), "p_wp": self._num(self.mod_p), "voc": self._num(self.mod_voc),
                       "vmp": self._num(self.mod_vmp), "isc": self._num(self.mod_isc)},
            "inverters": inverters,
            "dc": {"cable": self.dc_cable.text().strip(), "cross": self._num(self.dc_cross), "length": self._num(self.dc_len),
                   "route_boxes": self._num(self.dc_route_boxes) or 0, "route_length": self._num(self.dc_route_len),
                   "tech_box": self.dc_tech_box.isChecked(), "tech_length": self._num(self.dc_tech_len),
                   "fuse_in": self._num(self.dc_fuse_in), "spd": self.dc_spd.text().strip() or "T2",
                   "disconnect": not self.dc_tech_box.isChecked() and not self._num(self.dc_route_boxes)},
            "ac": {"cable": self.ac_cable.text().strip(), "cross": self._num(self.ac_cross), "length": self._num(self.ac_len),
                   "breaker_in": self._num(self.ac_breaker), "main_in": self._num(self.ac_main),
                   "grid_cable": self.grid_cable.text().strip(), "grid_cross": self._num(self.grid_cross),
                   "grid_length": self._num(self.grid_len)},
            "grid": {"dso": self.dso.text().strip()},
        }


class ElementDialog(AttrDialog):
    def __init__(self, symbol: Symbol, attrs: dict[str, str], parent=None, title: str | None = None,
                 library=None, component_id: str | None = None, wire_choices: list[tuple[str, str]] | None = None):
        super().__init__(symbol.attributes, attrs, parent, title or f"Vložit: {symbol.name}",
                         f"<b>{symbol.name}</b> <small>({symbol.id})</small>")
        self.library = library
        self.symbol = symbol
        self.component_id = component_id
        self.wire_combo: QComboBox | None = None
        if wire_choices is not None:
            # přívod/vývod rozvaděče: vazba na vodič nadřazeného JPS (přebere kabel, žíly, křížový odkaz)
            self.wire_combo = QComboBox()
            self.wire_combo.addItem("(bez vazby)", "")
            for wid, label in wire_choices:
                self.wire_combo.addItem(label, wid)
            cur = attrs.get("wire_id", "")
            idx = self.wire_combo.findData(cur)
            self.wire_combo.setCurrentIndex(max(idx, 0))
            form = self.layout().itemAt(1).layout()
            form.addRow("Vodič v JPS", self.wire_combo)
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

    @property
    def wire_id(self) -> str:
        return self.wire_combo.currentData() if self.wire_combo is not None else ""

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
