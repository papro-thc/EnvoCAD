"""Dialogy editoru."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envocad.library.macros import repeat_context_names, resolve_values
from envocad.model import multipole as mp
from envocad.model.designation import element_name
from envocad.model.project import (
    ENCLOSURE_PARAMS,
    MODULE_WIDTH,
    Layout,
    Project,
    Sheet,
    Wire,
    enclosure_param_error,
)
from envocad.model.symbol import Attribute, Symbol
from envocad.ui.wizard_topology import TopologyPanel

_CZECH_BUTTONS = (
    (QDialogButtonBox.Ok, "OK"), (QDialogButtonBox.Cancel, "Zrušit"), (QDialogButtonBox.Yes, "Ano"),
    (QDialogButtonBox.No, "Ne"), (QDialogButtonBox.Close, "Zavřít"), (QDialogButtonBox.Apply, "Použít"),
    (QDialogButtonBox.Save, "Uložit"), (QDialogButtonBox.Discard, "Neukládat"),
)


def czech_buttons(bb: QDialogButtonBox) -> QDialogButtonBox:
    """Česky popíše standardní tlačítka (OK/Zrušit/Ano/Ne/Zavřít/Použít…) – Qt bez překladů ukazuje anglické texty."""
    for which, text in _CZECH_BUTTONS:
        b = bb.button(which)
        if b is not None:
            b.setText(text)
    return bb


def button_box(buttons) -> QDialogButtonBox:
    """QDialogButtonBox se standardními tlačítky popsanými česky."""
    return czech_buttons(QDialogButtonBox(buttons))


class ChoiceEdit(QComboBox):
    """Výběr hodnoty atributu s nabídkou (`Attribute.choices`) se stejným rozhraním jako `QLineEdit` (`text`,
    `setText`) – dialog atributů i panel Vlastnosti s ním zacházejí jako s textovým polem. Hodnota mimo nabídku
    (ruční úprava souboru) se zobrazí jako další položka, aby se nic neztratilo."""

    def __init__(self, items: list[tuple[str, str]], value: str = "", parent=None):
        super().__init__(parent)
        # kolečko myši při posouvání panelu Vlastnosti / dialogu nesmí nechtěně změnit hodnotu (a přidat krok undo):
        # fokus jen klepnutím nebo tabulátorem, kolečko bez fokusu jde dál (posun okolí)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        for v, label in items:
            self.addItem(label, v)
        self.setText(value)

    def wheelEvent(self, event) -> None:
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)

    def text(self) -> str:
        return str(self.currentData() or "")

    def setText(self, value: str) -> None:
        i = self.findData(value)
        if i < 0 and value:
            self.addItem(value, value)
            i = self.count() - 1
        self.setCurrentIndex(max(i, 0))

    def setPlaceholderText(self, _text: str) -> None:
        pass

    def selectAll(self) -> None:
        pass


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
            items = a.choice_items() if hasattr(a, "choice_items") else []
            if items:                      # nabídka hodnot (směr přívodu/vývodu)
                ed = ChoiceEdit(items, attrs.get(a.key, a.default) or a.default)
            else:
                ed = QLineEdit(attrs.get(a.key, a.default))
                ed.setPlaceholderText(a.default)
            self._edits[a.key] = ed
            form.addRow(a.label + (" *" if a.show else ""), ed)
        lay.addLayout(form)
        lay.addWidget(QLabel("<small>* zobrazí se ve výkresu</small>"))
        bb = button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
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
                     "L+ L-", "L+", "L-", "PEN"]


def wire_auto_hints(project: Project, sheet: Sheet, w: Wire) -> dict[str, str]:
    """Automaticky určené hodnoty výrobních atributů vodiče rozvaděče (placeholdery): průřez, barva, koncovky."""
    from envocad.export.reports import wiring_base
    from envocad.model.wiring import WiringParams, conductor_color, end_for, wire_cross
    from envocad.model.xref import DeviceIndex
    params = WiringParams.resolve(sheet.layout, wiring_base())
    cross, _src = wire_cross(project, sheet, w, params, DeviceIndex.build(project))   # silový kontakt → In stykače
    conds = mp.wire_conductors(w)
    if len(conds) == 1:
        color = conductor_color(w, conds[0]) or "bez barvy"
    else:
        color = "podle žíly"
    wire_type = (w.attrs.get("cable") or "").strip() or params.wire_type
    hints = {"cross": f"{cross:g}".replace(".", ",") if cross else "", "color": color}
    for side in ("a", "b"):
        text, _f = end_for(w, side, cross, wire_type)
        hints[f"end_{side}"] = text or "bez koncovky"
    return hints


class WireDialog(AttrDialog):
    """Parametry vodiče + seznam žil (pro vícepólový pohled a svorkovnice).

    `attributes` – jiný seznam atributů (na listu rozvaděče WIRE_ATTRIBUTES + SWITCHBOARD_WIRE_ATTRIBUTES);
    `hints` – placeholdery s automatickou hodnotou podle klíče atributu."""

    def __init__(self, attrs: dict[str, str], conductors: list[str], parent=None,
                 title: str = "Vodič", heading: str = "", attributes: list[Attribute] | None = None,
                 hints: dict[str, str] | None = None):
        from envocad.model.project import WIRE_ATTRIBUTES
        attributes = list(attributes if attributes is not None else WIRE_ATTRIBUTES)
        self._has_prod = any(a.key == "prod" for a in attributes)
        super().__init__([a for a in attributes if a.key != "prod"], attrs, parent, title, heading)
        for k, h in (hints or {}).items():
            if k in self._edits and h and not attrs.get(k):
                self._edits[k].setPlaceholderText(h)
        self.cond = QComboBox()
        self.cond.setEditable(True)
        self.cond.addItems(CONDUCTOR_PRESETS)
        self.cond.setCurrentText(" ".join(conductors))
        self.cond.setToolTip("Žíly vodiče oddělené mezerou – každá se ve vícepólu kreslí zvlášť")
        form = self.layout().itemAt(1 if heading else 0).layout()
        form.addRow("Žíly (vícepól)", self.cond)
        self.prod: QCheckBox | None = None
        if self._has_prod:
            self.prod = QCheckBox("Do výrobního seznamu")
            self.prod.setChecked(str(attrs.get("prod", "")).strip() != "0")
            self.prod.setToolTip("Odškrtnutím se vodič vynechá z výrobního zapojovacího seznamu")
            form.addRow(self.prod)

    def values(self) -> dict[str, str]:
        v = super().values()
        if self.prod is not None:
            v["prod"] = "" if self.prod.isChecked() else "0"
        return v

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
        bb = button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
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
        from envocad.model.xref import natural_key
        strips = sorted({e.ref for e in sheet.elements if e.symbol_id in mp.TERMINAL_SYMBOLS and e.ref},
                        key=natural_key)
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
        bb = button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._shown = ""
        self._drafts: dict[str, str] = {}   # rozpracované texty můstků všech svorkovnic (přepnutí je neztratí)
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
                                txt.append(f"{element_name(oe)}:{other.port}" + (f" ({w.attrs['ref']})" if w.attrs.get("ref") else ""))
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
                bridge = self.project.bridge_of(strip, num, self.sheet) if num else []
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

    def _model_text(self, strip: str) -> str:
        return "\n".join("-".join(g) for g in self.project.bridge_groups(strip, self.sheet))

    def _load(self, strip: str) -> None:
        if self._shown:
            self._drafts[self._shown] = self.bridges.toPlainText()
        rows = self._rows(strip) if strip else []
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.bridges.setPlainText(self._drafts.get(strip, self._model_text(strip)))
        self._shown = strip

    def _texts(self) -> dict[str, str]:
        """Texty můstků všech svorkovnic, které uživatel otevřel (včetně zobrazené)."""
        texts = dict(self._drafts)
        if self._shown:
            texts[self._shown] = self.bridges.toPlainText()
        return texts

    def values(self) -> tuple[str, list[list[str]]]:
        """(zobrazená svorkovnice, její skupiny můstků)."""
        from envocad.model.terminal_plan import parse_bridges
        return self._shown, parse_bridges(self.bridges.toPlainText())

    def all_values(self) -> dict[str, list[list[str]]]:
        """Změněné můstky všech svorkovnic: {svorkovnice: skupiny} (jen ty, které se liší od modelu)."""
        from envocad.model.terminal_plan import parse_bridges
        out = {}
        for strip, text in self._texts().items():
            groups = parse_bridges(text)
            if groups != self.project.bridge_groups(strip, self.sheet):
                out[strip] = groups
        return out

    def errors(self) -> list[str]:
        """Chyby zadání můstků všech upravených svorkovnic (čísla svorek, které na svorkovnici nejsou…)."""
        from envocad.model.terminal_plan import bridge_errors, strip_numbers
        errs: list[str] = []
        for strip, text in self._texts().items():
            if text.strip() == self._model_text(strip).strip():
                continue
            errs += bridge_errors(strip, text, strip_numbers(self.project, self.sheet, strip))
        return errs

    def accept(self) -> None:
        errs = self.errors()
        if errs:
            QMessageBox.warning(self, "Svorkovnice a můstky", "Můstky nelze uložit:\n" + "\n".join(errs))
            return
        super().accept()


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
        bb = button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
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


_MODULE_WORDS = ("modul", "moduly", "modulů")
STRING_MODE_CHOICES = (("Automaticky (z artiklu)", ""), ("Klasický", "classic"), ("S optimizéry", "optimizer"),
                       ("Pevné napětí", "fixed_voltage"))


def parse_temperature_field(text: str, label: str, minimum: float = -60.0) -> float | int:
    """Návrhová teplota z pole formuláře (`calc.parse_temperature`: „−20 °C“, „-20,5“); neplatná nebo pod `minimum`
    → ValueError s českou hláškou s názvem pole. Celé číslo se vrací jako int."""
    from envocad.model.calc import parse_temperature
    t = parse_temperature(text)
    if t is None:
        raise ValueError(f"{label}: „{str(text).strip()}“ není číslo.")
    if t < minimum:
        raise ValueError(f"{label}: hodnota musí být alespoň {minimum:g}.")
    return int(t) if t.is_integer() else t


def _n_word(n: int, words: tuple[str, str, str]) -> str:
    """„1 modul“, „3 moduly“, „5 modulů“."""
    from envocad.model.notes import plural
    return f"{n} {plural(n, *words)}"


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
        self.grp_conn = QGroupBox("Objekt a připojení")
        cform = QFormLayout(self.grp_conn)
        form.addRow(self.grp_conn)
        self.building = QComboBox()
        self.building.addItem("firma (DC rozvaděče RFVE.DC a AC rozvaděč RFVE.AC zvlášť)", "company")
        self.building.addItem("rodinný dům (DC i AC v jednom rozvaděči RFVE)", "house")
        self.building.addItem("bytový dům (DC rozvaděče RFVE.DC a AC rozvaděč RFVE.AC zvlášť)", "apartment")
        self.building.setToolTip("Rodinný dům: pojistkové odpínače a SPD stringů jsou v rozvaděči FVE spolu s AC částí")
        cform.addRow("Druh objektu", self.building)
        self.mod_type = QLineEdit()
        self.mod_p = QLineEdit("450")
        self.mod_voc = QLineEdit("49.5")
        self.mod_vmp = QLineEdit("41.5")
        self.mod_isc = QLineEdit("13.9")
        self._mod_comp = None        # artikl z katalogu (Component) – id se uloží do spec, údaje navíc do asistenta
        self._inv_comp = None
        self._opt_comp = None        # artikl optimizéru (optimizers.csv) – `optimizer.component_id`, pravidla stringů
        self.mod_imp = QLineEdit()
        self.mod_beta = QLineEdit()
        self.mod_imp.setToolTip("Nepovinné – Impp modulu (hlášení omezení výkonu při paralelních stringích)")
        self.mod_beta.setToolTip("Nepovinné – teplotní součinitel Uoc [%/K], záporný; prázdné = −0,27 %/K")
        self.mod_label = QLabel()
        self.mod_label.setWordWrap(True)
        form.addRow("FV modul – typ", self.mod_type)
        form.addRow("", self._catalog_row("Z katalogu…", self.pick_module, self.clear_module, self.mod_label))
        form.addRow("P modulu [Wp]", self.mod_p)
        form.addRow("Uoc / Umpp modulu [V]", self._pair(self.mod_voc, self.mod_vmp))
        form.addRow("Isc / Impp modulu [A]", self._pair(self.mod_isc, self.mod_imp))
        form.addRow("β Uoc [%/K]", self.mod_beta)
        self.opt_type = QLineEdit("")
        self.opt_per = QLineEdit("1")
        self.opt_type.setToolTip("Prázdné = bez optimizérů")
        self.opt_label = QLabel()
        self.opt_label.setWordWrap(True)
        form.addRow("Optimizér – typ / ks na modul", self._pair(self.opt_type, self.opt_per))
        form.addRow("", self._catalog_row("Z katalogu…", self.pick_optimizer, self.clear_optimizer, self.opt_label))
        self.inv_type = QLineEdit()
        self.inv_p = QLineEdit("25")
        self.inv_udc = QLineEdit("1100")
        self.inv_mppt = QLineEdit("200")
        self.inv_mppt_max = QLineEdit("1000")
        self.inv_imax = QLineEdit("30")
        self.strings = QLineEdit("18,18,18,18; 18,18")   # Uoc 18 × 49,5 V při −20 °C ≈ 999 V < 1100 V
        self.strings.setToolTip("Stringy po střídačích: počty modulů oddělené čárkou, střídače středníkem")
        self.inv_isc_mppt = QLineEdit()
        self.inv_spm = QLineEdit()
        self.inv_isc_mppt.setToolTip("Nepovinné – max. zkratový proud na MPPT [A]")
        self.inv_spm.setToolTip("Nepovinné – počet stringů na jeden MPPT; prázdné = podle artiklu / 2")
        self.inv_label = QLabel()
        self.inv_label.setWordWrap(True)
        form.addRow("Střídač – typ", self.inv_type)
        form.addRow("", self._catalog_row("Z katalogu…", self.pick_inverter, self.clear_inverter, self.inv_label))
        form.addRow("P AC střídače [kW]", self.inv_p)
        form.addRow("U DC max / MPPT min / MPPT max [V]", self._triple(self.inv_udc, self.inv_mppt, self.inv_mppt_max))
        form.addRow("I max / Isc max na MPPT [A]", self._pair(self.inv_imax, self.inv_isc_mppt))
        form.addRow("Stringů na MPPT", self.inv_spm)
        self.string_mode = QComboBox()
        for text, data in STRING_MODE_CHOICES:
            self.string_mode.addItem(text, data)
        self.string_mode.setToolTip("Automaticky = režim z artiklu střídače, jinak z artiklu optimizéru, jinak klasický. "
                                    "Pevné napětí: SolarEdge – délka stringu daná počtem optimizérů, Uoc·n se nekontroluje")
        form.addRow("Režim stringů", self.string_mode)
        self.t_min = QLineEdit(str(std.get("pv_t_min", -20)))
        self.t_max = QLineEdit(str(std.get("pv_t_max", 70)))
        self.t_min.setToolTip("Návrhová teplota pro Uoc (za studena) [°C]; výchozí z firemního standardu")
        self.t_max.setToolTip("Návrhová teplota pro Umpp (za tepla) [°C]; výchozí z firemního standardu")
        form.addRow("Návrhové teploty min / max [°C]", self._pair(self.t_min, self.t_max))
        self.mod_total = QLineEdit()
        self.mod_total.setToolTip("Nepovinné – celkový počet modulů FVE; pro návrh stringů a počtu střídačů")
        form.addRow("Celkem modulů (nepovinné)", self.mod_total)
        form.addRow("Stringy (moduly; střídače ;)", self.strings)
        self.assist = QLabel()
        self.assist.setWordWrap(True)
        self.assist.setTextFormat(Qt.RichText)
        self.btn_propose = QPushButton("Navrhnout stringy")
        self.btn_propose.setToolTip("Rozdělí „Celkem modulů“ (jinak součet zadaných stringů) do stringů v mezích střídače")
        self.btn_propose.clicked.connect(self.propose_strings)
        form.addRow("Asistent stringů", self.assist)
        form.addRow("", self.btn_propose)
        self.dc_cable = QLineEdit(str(std.get("dc_cable") or "H1Z2Z2-K 1x6"))
        self.dc_cross = QLineEdit(str(std.get("dc_cross") or "6"))
        self.dc_len = QLineEdit("30")
        form.addRow("DC kabel / průřez / délka string → 1. DC rozvaděč [m]", self._triple(self.dc_cable, self.dc_cross, self.dc_len))
        self.dc_route_boxes = QLineEdit("1")
        self.dc_route_len = QLineEdit("20")
        self.dc_route_boxes.setToolTip("DC rozvaděče po trase (jen SPD na každý string, bez odpínače); 0 = žádný")
        form.addRow("DC rozvaděčů po trase / délka kabelu mezi nimi [m]", self._pair(self.dc_route_boxes, self.dc_route_len))
        self.dc_tech_box = QCheckBox("DC rozvaděč u technologie RFVE.DC (pojistkové odpínače + SPD)")
        self.dc_tech_box.setChecked(True)
        self.dc_tech_len = QLineEdit("5")
        self.dc_fuse_in = QLineEdit("")
        self.dc_fuse_in.setPlaceholderText("podle stringu")
        self.dc_fuse_in.setToolTip("Prázdné = podle stringu: gPV ≥ 1,5 × Isc modulu (do 2,4 × Isc a max. jištění "
                                   "modulu), SolarEdge 25 A. Pojistkový odpojovač ETI EFH 10 DC 2p (max 25 A).")
        self.dc_spd = QLineEdit("T1+T2")
        form.addRow("", self.dc_tech_box)
        form.addRow("Délka ke střídači [m] / In pojistek [A] / SPD DC", self._triple(self.dc_tech_len, self.dc_fuse_in, self.dc_spd))
        self.ac_cable = QLineEdit(str(std.get("ac_cable") or "CYKY-J 5x16"))
        self.ac_cross = QLineEdit(str(std.get("ac_cross") or "16"))
        self.ac_len = QLineEdit("30")
        form.addRow("AC kabel střídač–rozvaděč / průřez / délka", self._triple(self.ac_cable, self.ac_cross, self.ac_len))
        self.ac_breaker = QLineEdit("40")
        self.ac_main = QLineEdit("125")
        form.addRow("In jističe střídače / hlavního vypínače [A]", self._pair(self.ac_breaker, self.ac_main))
        self.ac_bus = QCheckBox("Rozvod v AC rozvaděči sběrnicí potenciálů (vodič jako v EPLAN); jinak svorky s můstky")
        self.ac_bus.setChecked(True)
        form.addRow("", self.ac_bus)
        self.grid_cable = QLineEdit(str(std.get("grid_cable") or "CYKY-J 5x35"))
        self.grid_cross = QLineEdit(str(std.get("grid_cross") or "35"))
        self.grid_len = QLineEdit("20")
        form.addRow("Kabel do HDS / průřez / délka", self._triple(self.grid_cable, self.grid_cross, self.grid_len))
        self.dso = QLineEdit("")
        form.addRow("Distributor (DSO)", self.dso)
        # připojení k DS: nn (AC rozvaděč FVE do HDS) nebo VN (hlavní rozvaděč nn, transformátor, rozvaděč VN)
        self.conn_level = QComboBox()
        self.conn_level.addItem("nn – AC rozvaděč FVE do HDS", "nn")
        self.conn_level.addItem("VN – trafostanice (rozvaděč VN, transformátor, hlavní rozvaděč nn, elektroměrový)", "vn")
        self.conn_station = QComboBox()
        self.conn_station.addItem("kiosková TS (rozvaděč VN po polích)", "kiosk")
        self.conn_station.addItem("zděná TS (kobky)", "kobky")
        self.conn_station.addItem("sloupová TS (odpínač, pojistky a svodiče na sloupu)", "sloup")
        self.conn_metering = QComboBox()
        self.conn_metering.addItem("fakturační měření na straně nn", "nn")
        self.conn_metering.addItem("fakturační měření na straně VN", "vn")
        self.tr_sn = QLineEdit("630")
        self.tr_sn.setPlaceholderText("Sn [kVA]")
        self.conn_loop = QCheckBox("smyčka (2 kabelová pole)")
        self.conn_loop.setChecked(True)
        cform.addRow("Připojení k DS", self.conn_level)
        cform.addRow("Trafostanice", self.conn_station)
        cform.addRow("Měření / Sn trafa [kVA]", self._triple(self.conn_metering, self.tr_sn, self.conn_loop))
        # topologie připojení (F5): předvolba, náhled řetězce, stávající rozvaděče, skupiny střídačů
        self.topo = TopologyPanel(self)
        self.topo.add_object_rows(cform)

        def _conn_enabled() -> None:
            house = self.building.currentData() == "house"   # rodinný dům: rozvaděč FVE do HDS, bez přípojky VN
            if house:
                self.conn_level.setCurrentIndex(0)
            self.conn_level.setEnabled(not house)
            on = self.conn_level.currentData() == "vn"
            pole = self.conn_station.currentData() == "sloup"      # sloupová TS: měření na nn, bez kabelových polí
            self.conn_station.setEnabled(on)
            self.tr_sn.setEnabled(on)
            self.conn_metering.setEnabled(on and not pole)
            self.conn_loop.setEnabled(on and not pole)
            if pole:
                self.conn_metering.setCurrentIndex(0)
        self.conn_level.currentIndexChanged.connect(lambda _i: _conn_enabled())
        self.conn_station.currentIndexChanged.connect(lambda _i: _conn_enabled())
        self.building.currentIndexChanged.connect(lambda _i: _conn_enabled())
        _conn_enabled()
        form.addRow(self.topo.existing_group)
        form.addRow(self.topo.inverter_group)
        self.topo.refresh()
        body = QWidget()      # dlouhý formulář v posuvné oblasti, tlačítka OK / Zrušit zůstávají vidět
        body.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        self.resize(920, 760)
        bb = button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for w in (self.mod_p, self.mod_voc, self.mod_vmp, self.mod_isc, self.mod_imp, self.mod_beta, self.inv_p,
                  self.inv_udc, self.inv_mppt, self.inv_mppt_max, self.inv_imax, self.inv_isc_mppt, self.inv_spm,
                  self.t_min, self.t_max, self.mod_total, self.strings, self.opt_type, self.opt_per):
            w.textChanged.connect(self.update_assistant)
        self.string_mode.currentIndexChanged.connect(self.update_assistant)
        self.opt_type.textChanged.connect(self._opt_type_changed)
        self.update_assistant()

    # ---- katalog (docs/design/katalog_fv.md §4): pole se vyplní z artiklu, ruční úprava pole vyhrává --------------
    def _catalog_row(self, text, pick, clear, label) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        btn = QPushButton(text)
        btn.setEnabled(self.library is not None)
        btn.clicked.connect(pick)
        x = QPushButton("×")
        x.setToolTip("Zrušit vazbu na artikl (pole zůstanou beze změny)")
        x.setMaximumWidth(28)
        x.clicked.connect(clear)
        h.addWidget(btn)
        h.addWidget(x)
        h.addWidget(label, 1)
        self._set_catalog_label(label, None)
        return w

    @staticmethod
    def _set_catalog_label(label: QLabel, comp) -> None:
        label.setText(f"Artikl: <b>{comp.label}</b>" if comp else "<i>Artikl nevybrán – údaje lze zadat ručně</i>")

    def _pick(self, categories: tuple[str, ...], title: str):
        from envocad.ui.component_picker import ComponentPicker
        dlg = ComponentPicker(self.library, category=categories[0], categories=categories, parent=self, title=title)
        return dlg.selected if dlg.exec() == ComponentPicker.Accepted else None

    def pick_module(self) -> None:
        comp = self._pick(("pv_module",), "Vybrat FV modul")
        if comp:
            self.set_module_component(comp)

    def pick_inverter(self) -> None:
        comp = self._pick(("inverter", "inverter_hybrid"), "Vybrat střídač")
        if comp:
            self.set_inverter_component(comp)

    @staticmethod
    def _fill(edit: QLineEdit, value) -> None:
        if value not in (None, ""):
            edit.setText(str(value).replace(",", "."))

    def pick_optimizer(self) -> None:
        comp = self._pick(("optimizer",), "Vybrat optimizér")
        if comp:
            self.set_optimizer_component(comp)

    def set_module_component(self, comp) -> None:
        """Vyplní pole modulu z artiklu a zapamatuje si ho (`module.component_id` ve `spec()`)."""
        a = comp.attr_values()
        self._mod_comp = comp
        for edit, key in ((self.mod_type, "type"), (self.mod_p, "p_module"), (self.mod_voc, "voc"),
                          (self.mod_vmp, "vmp"), (self.mod_isc, "isc"), (self.mod_imp, "imp"),
                          (self.mod_beta, "beta_voc")):
            self._fill(edit, a.get(key))
        self._set_catalog_label(self.mod_label, comp)
        self.update_assistant()

    def set_inverter_component(self, comp) -> None:
        """Vyplní pole střídače z artiklu a zapamatuje si ho (`inverters[i].component_id` ve `spec()`)."""
        a = comp.attr_values()
        self._inv_comp = comp
        for edit, key in ((self.inv_type, "type"), (self.inv_p, "p_ac"), (self.inv_udc, "u_dc_max"),
                          (self.inv_mppt, "u_mppt_min"), (self.inv_mppt_max, "u_mppt_max"),
                          (self.inv_imax, "i_mppt_max"), (self.inv_isc_mppt, "isc_mppt_max"),
                          (self.inv_spm, "strings_per_mppt")):
            self._fill(edit, a.get(key))
        self._set_catalog_label(self.inv_label, comp)
        self.update_assistant()

    def set_optimizer_component(self, comp) -> None:
        """Vyplní typ a ks/modul z artiklu optimizéru (1 nebo 0,5 při 2 modulech na optimizér) a zapamatuje si ho
        (`optimizer.component_id` ve `spec()`; generátor z něj doplní atributy `opt_*` a pravidla stringů)."""
        self._opt_comp = comp
        self.opt_type.setText(comp.part_number)
        mpo = 2 if comp.num("modules_per_optimizer") == 2 else 1
        self.opt_per.setText("0.5" if mpo == 2 else "1")
        self._set_catalog_label(self.opt_label, comp)
        self.update_assistant()

    def _opt_type_changed(self, text: str) -> None:
        """Vymazaný typ optimizéru = bez optimizérů: zruší i vazbu na artikl (jinak by generátor typ z artiklu doplnil)."""
        if not text.strip() and self._opt_comp is not None:
            self.clear_optimizer()

    def _opt_per_mismatch(self) -> str:
        """Poznámka, když ručně zadané „ks na modul“ neodpovídá artiklu optimizéru (generátor i asistent počítají
        s 1 / modulů na optimizér z artiklu); jinak ""."""
        if self._opt_comp is None:
            return ""
        mpo = 2 if self._opt_comp.num("modules_per_optimizer") == 2 else 1
        per = self._num(self.opt_per)
        if per is None or abs(per - 1 / mpo) < 1e-9:
            return ""
        return (f"Ručně zadané {per:g} ks/modul neodpovídá artiklu ({_n_word(mpo, _MODULE_WORDS)} na optimizér) – "
                f"počítá se s {1 / mpo:g} ks/modul z artiklu; pro jiný počet zrušte vazbu na artikl (×).")

    def clear_optimizer(self) -> None:
        self._opt_comp = None
        self._set_catalog_label(self.opt_label, None)
        self.update_assistant()

    def clear_module(self) -> None:
        self._mod_comp = None
        self._set_catalog_label(self.mod_label, None)
        self.update_assistant()

    def clear_inverter(self) -> None:
        self._inv_comp = None
        self._set_catalog_label(self.inv_label, None)
        self.update_assistant()

    # ---- asistent stringů (výpočty jen v model/calc) ---------------------------------------------------------------
    @staticmethod
    def _num(edit: QLineEdit) -> float | None:
        try:
            return float(edit.text().strip().replace(",", "."))
        except ValueError:
            return None

    def _calc_data(self):
        """(ModuleData | None, InverterData, t_min, t_max, OptimizerData | None) z polí a artiklů; neplatná pole se
        berou jako neznámá. Režim stringů a data optimizéru stejně jako generátor: volba průvodce > artikl střídače >
        artikl optimizéru > klasický; pravidla optimizéru pro fáze střídače (`Component.optimizer_values`)."""
        from envocad.model.calc import (
            T_MAX_DEFAULT,
            T_MIN_DEFAULT,
            InverterData,
            ModuleData,
            OptimizerData,
            parse_temperature,
        )
        ma = dict(self._mod_comp.attr_values()) if self._mod_comp else {}
        ia = dict(self._inv_comp.attr_values()) if self._inv_comp else {}
        for a, pairs in ((ma, (("p_module", self.mod_p), ("voc", self.mod_voc), ("vmp", self.mod_vmp),
                                ("isc", self.mod_isc), ("imp", self.mod_imp), ("beta_voc", self.mod_beta))),
                         (ia, (("p_ac", self.inv_p), ("u_dc_max", self.inv_udc), ("u_mppt_min", self.inv_mppt),
                               ("u_mppt_max", self.inv_mppt_max), ("i_mppt_max", self.inv_imax),
                               ("isc_mppt_max", self.inv_isc_mppt), ("strings_per_mppt", self.inv_spm)))):
            for key, edit in pairs:   # zadané pole má přednost před artiklem; prázdné/neplatné pole artikl nepřebije
                v = self._num(edit)
                if v is not None:
                    a[key] = str(v)
                elif edit.text().strip():
                    a.pop(key, None)
        opt = None
        if self._opt_comp is not None:
            oc = self._opt_comp
            opt = OptimizerData.from_attrs(oc.optimizer_values(ia.get("phases") or 3))
            if not str(ia.get("string_mode") or "").strip() and (oc.params.get("string_mode") or "").strip():
                ia["string_mode"] = oc.params["string_mode"].strip()
        if self.string_mode.currentData():
            ia["string_mode"] = self.string_mode.currentData()
        t_min, t_max = parse_temperature(self.t_min.text()), parse_temperature(self.t_max.text())
        return (ModuleData.from_attrs(ma), InverterData.from_attrs(ia),
                T_MIN_DEFAULT if t_min is None else t_min, T_MAX_DEFAULT if t_max is None else t_max, opt)

    def _n_optimizers(self, n: int, opt) -> int | None:
        """Počet optimizérů ve stringu o n modulech jako generátor: z artiklu ⌈n / modulů na optimizér⌉, jinak
        n · ks na modul (zaokrouhleno); bez optimizéru None."""
        import math
        if self._opt_comp is not None and opt is not None:
            return math.ceil(n / opt.modules)
        if self._opt_comp is not None:
            return math.ceil(n / (2 if self._opt_comp.num("modules_per_optimizer") == 2 else 1))
        per = self._num(self.opt_per)
        if self.opt_type.text().strip() and per:
            return round(n * per)
        return None

    def _manual_mpo(self) -> int | None:
        """Modulů na optimizér z ručního „ks na modul“ (bez artiklu optimizéru; 0,5 → 2), jinak None."""
        from envocad.model.calc import modules_per_optimizer
        if self._opt_comp is not None or not self.opt_type.text().strip():
            return None
        return modules_per_optimizer(self.opt_per.text())

    def _string_groups(self) -> list[list[int]]:
        from envocad.generate import parse_strings
        try:
            return parse_strings(self.strings.text())
        except ValueError:
            return []

    def string_results(self) -> list[list[tuple[int, list[str]]]]:
        """Stav každého zadaného stringu po střídačích [(počet modulů, hlášky)] – stejně jako kontrola F7
        (`calc.check_strings`) projektu z `spec()`: MPPT jako generátor (`calc.assign_mppt`), stringy na stejném MPPT
        `calc.mppt_groups`, stringy nad počet vstupů střídače `calc.capacity_issue`. Bez Uoc modulu → []."""
        from envocad.model.calc import (
            assign_mppt,
            capacity_issue,
            inverter_capacity,
            mppt_groups,
            parallel_issues,
            string_issues,
        )
        mod, inv, t_min, t_max, opt = self._calc_data()
        if mod is None:
            return []
        out = []
        for i, g in enumerate(self._string_groups()):
            n_par = mppt_groups(assign_mppt(len(g), inv))
            over = capacity_issue(f"T{i + 1}", inv, len(g))
            cap = inverter_capacity(inv) or 0
            row = [(n, string_issues(mod, inv, n, n_par[k], t_min, t_max, opt, self._n_optimizers(n, opt))
                    + ([over] if over and k >= cap else []))
                   for k, n in enumerate(g)]
            if inv.mode != "fixed_voltage":   # stringy na jednom MPPT: nestejná délka apod. (jako F7)
                by_mppt: dict[int, list[int]] = {}
                for k, m in enumerate(assign_mppt(len(g), inv)):
                    if m is not None:
                        by_mppt.setdefault(m, []).append(k)
                for idx in by_mppt.values():
                    msgs = parallel_issues([(g[k], mod, "") for k in idx]) if len(idx) > 1 else []
                    for k in idx:
                        row[k][1].extend(msgs)
            out.append(row)
        return out

    def assistant_text(self) -> str:
        """Text asistenta (HTML): rozsah modulů ve stringu, stav stringů, DC/AC a doporučený počet střídačů."""
        from envocad.model.calc import is_warning, string_limits, suggest_inverter_count
        mod, inv, t_min, t_max, opt = self._calc_data()
        if mod is None:
            return "<i>Zadejte Uoc modulu – asistent pak spočítá rozsah stringu.</i>"
        lim = string_limits(mod, inv, t_min, t_max, opt, self._manual_mpo())
        hi = "?" if lim.n_max is None else str(lim.n_max)
        step = f", po {lim.step} modulech" if lim.step > 1 else ""
        lines = [f"<b>Modulů ve stringu: {lim.n_min}–{hi}{step}</b>"
                 + (f" ({'; '.join(lim.reasons)})" if lim.reasons else "")
                 + f"<br>Stringů na MPPT ≤ {lim.n_par_max}"]
        lines += self._mode_lines(mod, inv, opt, lim, t_min, t_max)
        if note := self._opt_per_mismatch():
            lines.append(f"<span style='color:#b26a00'>{note}</span>")
        groups = self._string_groups()
        for i, results in enumerate(self.string_results()):
            res: dict[tuple, int] = {}
            for n, issues in results:
                key = (n, tuple(issues))
                res[key] = res.get(key, 0) + 1
            for (n, issues), cnt in res.items():
                warn_only = bool(issues) and all(is_warning(x) for x in issues)
                color = "#2e7d32" if not issues else ("#b26a00" if warn_only else INVALID_COLOR)
                state = "OK" if not issues else "; ".join(issues)
                lines.append(f"T{i + 1}: {cnt}× {_n_word(n, _MODULE_WORDS)} – <span style='color:{color}'>{state}</span>")
        total = self._num(self.mod_total)
        n_mod = sum(sum(g) for g in groups)
        n_all = int(total) if total else n_mod
        if mod.p_wp and n_all and not inv.p_ac:
            lines.append("DC/AC: P AC střídače není zadán")
        elif mod.p_wp and inv.p_ac and n_all:
            p_dc = n_all * mod.p_wp / 1000
            n_inv = max(len(groups), 1)
            lines.append(f"DC/AC = {p_dc / (n_inv * inv.p_ac):.2f} ({p_dc:.1f} kWp / {n_inv * inv.p_ac:g} kW); "
                         f"doporučeno {_n_word(suggest_inverter_count(p_dc, inv.p_ac), ('střídač', 'střídače', 'střídačů'))}")
        if total and total > n_mod:
            lines.append(f"Ve stringích zbývá umístit {_n_word(int(total) - n_mod, _MODULE_WORDS)}.")
        return "<br>".join(lines)

    @staticmethod
    def _mode_lines(mod, inv, opt, lim, t_min: float, t_max: float) -> list[str]:
        """Řádek režimu stringů (jen při optimizérech nebo neklasickém režimu) a řádek vstupu optimizéru."""
        from envocad.model.calc import is_warning, optimizer_issues, optimizer_rules
        out: list[str] = []
        mode = inv.mode
        n_lo, n_hi, p_max = optimizer_rules(inv, opt)
        if mode == "classic" and opt is None:
            return out
        parts = []
        if mode == "fixed_voltage":
            u = f"{inv.u_string:g} V" if inv.u_string else "neuvedeno"
            parts.append(f"pevné napětí {u} – Uoc·n se nekontroluje")
        elif mode == "optimizer":
            parts.append("s optimizéry")
        else:
            parts.append("klasický")
        if mode != "classic":
            if n_lo or n_hi:
                parts.append(f"optimizérů {n_lo or '?'}–{n_hi or '?'}")
            if p_max:
                parts.append(f"P stringu ≤ {p_max:g} W")
            if lim.n_max is not None:
                parts.append(f"modulů {lim.n_min}–{lim.n_max}")
        out.append("Režim stringů: " + "; ".join(parts))
        if opt is not None:
            unit = "modulu" if opt.modules == 1 else f"{opt.modules} modulů"
            uoc = round(opt.modules * mod.uoc(t_min), 1)
            vals = [f"Uoc {unit} při {t_min:g} °C {uoc:g} V (Uin max {opt.u_in_max:g} V)"]
            if mod.isc:
                vals.append(f"Isc {mod.isc:g} A" + (f" (max {opt.isc_in_max:g} A)" if opt.isc_in_max else ""))
            if mod.p_wp:
                vals.append(f"P {opt.modules * mod.p_wp:g} W (max {opt.p_max:g} W)")
            issues = optimizer_issues(mod, opt, t_min, t_max, inv.manufacturer)
            color = "#2e7d32" if not issues else ("#b26a00" if all(is_warning(x) for x in issues) else INVALID_COLOR)
            state = "OK" if not issues else "; ".join(issues)
            name = f" {opt.name}" if opt.name else ""
            out.append(f"Optimizér{name}: {'; '.join(vals)} – <span style='color:{color}'>{state}</span>")
        return out

    def update_assistant(self) -> None:
        self.assist.setText(self.assistant_text())

    def propose_strings(self) -> None:
        """Navrhne stringy (`calc.propose_strings`) pro „Celkem modulů“ (jinak součet zadaných) a vyplní pole."""
        from envocad.model.calc import propose_strings, string_limits, suggest_inverter_count
        mod, inv, t_min, t_max, opt = self._calc_data()
        groups = self._string_groups()
        total = self._num(self.mod_total)
        n_total = int(total) if total else sum(sum(g) for g in groups)
        if mod is None or not n_total:
            QMessageBox.information(self, "Navrhnout stringy", "Zadejte Uoc modulu a „Celkem modulů“ "
                                    "(nebo aspoň jeden string), pak lze stringy navrhnout.")
            return
        n_inv = len(groups) or 1
        if total and mod.p_wp and inv.p_ac:
            n_inv = max(n_inv, suggest_inverter_count(n_total * mod.p_wp / 1000, inv.p_ac))
        out, left = propose_strings(n_total, n_inv, string_limits(mod, inv, t_min, t_max, opt, self._manual_mpo()), inv)
        out = [g for g in out if g]
        if not out:
            QMessageBox.warning(self, "Navrhnout stringy", "Pro tento modul a střídač nelze stringy navrhnout – "
                                "viz důvody v asistentu.")
            return
        self.strings.setText("; ".join(",".join(str(n) for n in g) for g in out))
        if left:
            from envocad.model.notes import plural
            verb = plural(left, "Nevešel", "Nevešly", "Nevešlo")
            QMessageBox.warning(self, "Navrhnout stringy", f"{verb} se {_n_word(left, _MODULE_WORDS)} "
                                "(omezení střídače). Přidejte střídač nebo zvolte jiný.")

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

    # (pole, popisek v hlášce, parse_number kwargs) – kladná čísla, délky ≥ 0 (smí být prázdné), počty celé
    _NUMBERS = (
        ("mod_p", "P modulu [Wp]", {}), ("mod_voc", "Uoc modulu [V]", {}), ("mod_vmp", "Umpp modulu [V]", {}),
        ("mod_isc", "Isc modulu [A]", {}), ("inv_p", "P AC střídače [kW]", {}),
        ("inv_udc", "U DC max střídače [V]", {}), ("inv_mppt", "U MPPT min [V]", {}),
        ("inv_mppt_max", "U MPPT max [V]", {}), ("inv_imax", "I max na MPPT [A]", {}),
        ("dc_cross", "Průřez DC kabelu", {}), ("dc_len", "Délka DC kabelu [m]", {"strict": False, "allow_empty": True}),
        ("dc_route_boxes", "Počet DC rozvaděčů po trase", {"integer": True, "strict": False}),
        ("dc_route_len", "Délka kabelu mezi DC rozvaděči [m]", {"strict": False, "allow_empty": True}),
        ("dc_tech_len", "Délka ke střídači [m]", {"strict": False, "allow_empty": True}),
        ("ac_cross", "Průřez AC kabelu", {}),
        ("ac_len", "Délka AC kabelu [m]", {"strict": False, "allow_empty": True}),
        ("ac_breaker", "In jističe střídače [A]", {}), ("ac_main", "In hlavního vypínače [A]", {}),
        ("grid_cross", "Průřez kabelu do HDS", {}),
        ("grid_len", "Délka kabelu do HDS [m]", {"strict": False, "allow_empty": True}),
    )

    # nepovinná pole (prázdné = nezadáno); β a teploty smí být záporné
    _OPTIONAL = (
        ("mod_imp", "Impp modulu [A]", {}), ("mod_beta", "β Uoc [%/K]", {"minimum": -1.0}),
        ("inv_isc_mppt", "Isc max na MPPT [A]", {}), ("inv_spm", "Stringů na MPPT", {"integer": True}),
        ("dc_fuse_in", "In pojistek [A]", {}),
        ("t_min", "Návrhová teplota min [°C]", {"temperature": True}),
        ("t_max", "Návrhová teplota max [°C]", {"temperature": True}),
        ("mod_total", "Celkem modulů", {"integer": True}),
        ("tr_sn", "Sn transformátoru [kVA]", {}),
    )

    def _values(self) -> tuple[dict, list[str]]:
        """Čísla a stringy z polí: ({pole: hodnota}, české chyby). Chybné pole v hodnotách chybí."""
        from envocad.generate import parse_number, parse_strings
        vals: dict = {}
        errs: list[str] = []
        try:
            vals["strings"] = parse_strings(self.strings.text())
        except ValueError as ex:
            errs.append(str(ex))
        fields = list(self._NUMBERS)
        for name, label, kw in self._OPTIONAL:
            if getattr(self, name).text().strip():
                fields.append((name, label, kw))
        if self.opt_type.text().strip():
            fields.append(("opt_per", "Optimizérů na modul", {}))
        for name, label, kw in fields:
            try:
                if kw.get("temperature"):   # „−20 °C“, „-20,5“ (`calc.parse_temperature`)
                    vals[name] = parse_temperature_field(getattr(self, name).text(), label)
                else:
                    vals[name] = parse_number(getattr(self, name).text(), label, **kw)
            except ValueError as ex:
                errs.append(str(ex))
        if isinstance(vals.get("mod_beta"), (int, float)) and vals["mod_beta"] >= 0:
            errs.append("β Uoc [%/K]: hodnota musí být záporná (typicky −0,27).")
        if isinstance(vals.get("t_min"), (int, float)) and isinstance(vals.get("t_max"), (int, float)) \
                and vals["t_min"] >= vals["t_max"]:
            errs.append("Návrhová teplota min musí být menší než max.")
        return vals, errs

    def errors(self) -> list[str]:
        """Chyby vstupu česky (prázdné = lze generovat)."""
        return self._values()[1] + self.topo.errors()

    def generator_errors(self) -> list[str]:
        """Chyby, které ohlásí až generátor (ValueError česky) – jen když uživatel změnil topologii, stávající
        rozvaděče nebo skupiny střídačů; výchozí specifikace se tu nesestavuje."""
        if not self.topo.has_changes():
            return []
        from envocad.generate import build_project
        from envocad.settings import apply_standard_to_spec
        try:
            build_project(apply_standard_to_spec(self.spec()))
        except ValueError as ex:
            return [str(ex)]
        return []

    def accept(self) -> None:
        errs = self.errors() or self.generator_errors()
        if errs:   # dialog zůstane otevřený, uživatel opraví pole
            QMessageBox.warning(self, "Nový projekt FVE", "Opravte prosím zadání:\n\n" + "\n".join(f"• {e}" for e in errs))
            return
        super().accept()

    def spec(self) -> dict:
        """Specifikace pro `build_project`; neplatný vstup → ValueError s českými hláškami (viz `errors`)."""
        v, errs = self._values()
        topo_parts, topo_errs = self.topo.parts()
        if errs or topo_errs:
            raise ValueError("\n".join(errs + topo_errs))
        inverters = [{"ref": f"T{i + 1}", "type": self.inv_type.text().strip(), "p_ac": v["inv_p"],
                      "u_dc_max": v["inv_udc"], "u_mppt_min": v["inv_mppt"],
                      "u_mppt_max": v["inv_mppt_max"], "i_mppt_max": v["inv_imax"],
                      "strings": st} for i, st in enumerate(v["strings"])]
        for i, inv in enumerate(inverters):   # nepovinné údaje a artikl střídače
            if self.topo.ac_group_for(i):
                inv["ac_group"] = self.topo.ac_group_for(i)
            if v.get("inv_isc_mppt") not in (None, ""):
                inv["isc_mppt_max"] = v["inv_isc_mppt"]
            if v.get("inv_spm") not in (None, ""):
                inv["strings_per_mppt"] = v["inv_spm"]
            if self._inv_comp is not None:
                inv["component_id"] = self._inv_comp.id
            if self.string_mode.currentData():
                inv["string_mode"] = self.string_mode.currentData()
        module = {"type": self.mod_type.text().strip(), "p_wp": v["mod_p"], "voc": v["mod_voc"],
                  "vmp": v["mod_vmp"], "isc": v["mod_isc"]}
        if v.get("mod_imp") not in (None, ""):
            module["imp"] = v["mod_imp"]
        if v.get("mod_beta") not in (None, ""):
            module["beta_voc"] = v["mod_beta"]
        if self._mod_comp is not None:
            module["component_id"] = self._mod_comp.id
            u_sys = self._mod_comp.attr_values().get("u_sys_max")
            if u_sys:
                module["u_sys_max"] = float(u_sys.replace(",", "."))
        optimizer = {"type": self.opt_type.text().strip(), "per_module": v.get("opt_per") or 1}
        if self._opt_comp is not None and optimizer["type"]:   # bez typu = bez optimizérů, artikl se neposílá
            optimizer["component_id"] = self._opt_comp.id
        site = {k: v[k] for k in ("t_min", "t_max") if v.get(k) not in (None, "")}
        spec = {
            "name": self.name.text().strip() or "Nový projekt FVE",
            "meta": {"investor": self.investor.text().strip(), "place": self.place.text().strip(),
                     "order": self.order.text().strip(), "author": self.author.text().strip()},
            "building": self.building.currentData(),
            "module": module,
            "site": site,
            "optimizer": optimizer,
            "inverters": inverters,
            "dc": {"cable": self.dc_cable.text().strip(), "cross": v["dc_cross"], "length": v["dc_len"],
                   "route_boxes": v["dc_route_boxes"], "route_length": v["dc_route_len"],
                   "tech_box": self.dc_tech_box.isChecked(), "tech_length": v["dc_tech_len"],
                   "fuse_in": v.get("dc_fuse_in") or "", "spd": self.dc_spd.text().strip() or "T1+T2",
                   "disconnect": not self.dc_tech_box.isChecked() and not v["dc_route_boxes"]},
            "ac": {"cable": self.ac_cable.text().strip(), "cross": v["ac_cross"], "length": v["ac_len"],
                   "breaker_in": v["ac_breaker"], "main_in": v["ac_main"],
                   "grid_cable": self.grid_cable.text().strip(), "grid_cross": v["grid_cross"],
                   "grid_length": v["grid_len"], "distribution": "bus" if self.ac_bus.isChecked() else "terminals"},
            "grid": {"dso": self.dso.text().strip()},
            "connection": {"level": self.conn_level.currentData(), "metering": self.conn_metering.currentData(),
                           "station": self.conn_station.currentData(),
                           "loop": self.conn_loop.isChecked(), "transformer": {"sn": v.get("tr_sn") or 630}},
        }
        spec.update(topo_parts)   # topology a chain.* jen při změně od výchozího
        return spec


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
            form.addRow("Vodič v blokovém schématu", self.wire_combo)
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


INVALID_COLOR = "#d32f2f"   # zvýraznění neplatného pole a varování (čitelné ve světlém i tmavém motivu)


class EnclosurePanel(QWidget):
    """Rozměry a parametry skříně – nemodální panel vedle rozložení; změny se promítají hned.

    Bez `commit` panel zapisuje přímo do rozložení (`layout`, jinak `sheet.layout`) – dialog skříně tak pracuje
    na kopii. S `commit(before, after, key)` panel model sám nemění: předá snímky `Layout.to_dict()` před a po
    změně a klíč měněného pole (pro slučování kroků undo) – okno z nich udělá `SetLayoutCommand`. Po undo/redo
    se pole panelu načtou z modelu (`load_from_model`)."""

    changed = Signal()

    def __init__(self, sheet: Sheet, parent=None, library=None, project: Project | None = None,
                 layout: Layout | None = None, commit=None):
        super().__init__(parent)
        self._sheet = sheet
        self._project = project   # bez projektu se skupiny přístrojů (cívka × stykač) hledají jen na listu
        self._layout = layout
        self._commit = commit
        self._suspend = False     # načítání z modelu / výběr z knihovny – změny polí se nepropisují po jedné
        lay = self.layout
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
        # varování: záporná rezerva, přístroje za koncem řady / překryvy (kontrola `layout_problems`)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(f"color: {INVALID_COLOR};")
        self.warning.setVisible(False)
        f1.addRow(self.warning)
        root.addWidget(g1)

        g2 = QGroupBox("Parametry skříně")
        f2 = QFormLayout(g2)
        f2.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        hints = {"mounting": "nástěnná / zapuštěná / stojanová / volně stojící", "material": "plast / ocel / nerez",
                 "door": "plné / průhledné / bez dveří",
                 "t_ambient_min": "nepovinné – kontrola t_min přístrojů (např. −20)"}
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

        from envocad.export.reports import wiring_base
        from envocad.model.wiring import CHOICE_LABELS, WIRING_PARAMS, WiringParams, parse_param
        eff = WiringParams.resolve(None, wiring_base())   # firemní standard, jinak výchozí hodnoty
        self._wiring_keys = {k for k, _l, _d in WIRING_PARAMS}
        # zaškrtnutá skupina = vlastní parametry rozvaděče; odškrtnutím se klíče wire_* z parametrů odeberou
        # (platí firemní standard / výchozí), texty polí zůstanou do zavření panelu pro případné opětovné zaškrtnutí
        self.wiring_group = QGroupBox("Výrobní data (zapojení)")
        self.wiring_group.setCheckable(True)
        self.wiring_group.setChecked(any(k in lay.params for k in self._wiring_keys))
        self.wiring_group.setToolTip("Vlastní parametry výrobního zapojovacího seznamu pro tento rozvaděč; prázdné pole "
                                     "= firemní standard / výchozí. Odškrtnutím se vlastní parametry odeberou.")
        gl = QVBoxLayout(self.wiring_group)
        gl.setContentsMargins(0, 0, 0, 0)
        self._wiring_body = QWidget()
        f4 = QFormLayout(self._wiring_body)
        f4.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self._choices: dict[str, QComboBox] = {}   # výběrové parametry (české popisky, ukládá se kód)
        for key, label, _default in WIRING_PARAMS:
            if key in CHOICE_LABELS:
                combo = QComboBox()
                combo.addItem(f"výchozí ({eff.display(key)})", "")
                for code, text in CHOICE_LABELS[key].items():
                    combo.addItem(text, code)
                cur = parse_param(key, lay.params.get(key)) or ""
                combo.setCurrentIndex(max(combo.findData(cur), 0))
                f4.addRow(label, combo)
                self._choices[key] = combo
                continue
            ed = QLineEdit(lay.params.get(key, ""))
            ed.setPlaceholderText(eff.value(key))
            ed.setMinimumWidth(140)
            self._edits[key] = ed
            f4.addRow(label, ed)
        gl.addWidget(self._wiring_body)
        self._wiring_body.setVisible(self.wiring_group.isChecked())
        self.wiring_group.toggled.connect(self._wiring_body.setVisible)
        self.wiring_group.toggled.connect(lambda *_: self._apply("wiring"))
        self.unplaced = self._choices["wire_unplaced"]
        for key, combo in self._choices.items():
            combo.currentIndexChanged.connect(lambda *_, key=key: self._apply(key))
        root.addWidget(self.wiring_group)

        # neplatná čísla (pole se zvýrazní, do modelu se nepropíší – platí předchozí hodnota)
        self.errors = QLabel()
        self.errors.setWordWrap(True)
        self.errors.setStyleSheet(f"color: {INVALID_COLOR};")
        self.errors.setVisible(False)
        root.addWidget(self.errors)

        g3 = QGroupBox("Oteplení (IEC 60890, orientačně)")
        v3 = QVBoxLayout(g3)
        self.thermal = QLabel()
        self.thermal.setWordWrap(True)
        v3.addWidget(self.thermal)
        root.addWidget(g3)
        root.addStretch()

        self.name.editingFinished.connect(lambda: self._apply("enclosure"))
        self.rows.valueChanged.connect(lambda *_: self._apply("rows"))
        self.mods.valueChanged.connect(lambda *_: self._apply("modules_per_row"))
        for key, ed in self._edits.items():
            ed.editingFinished.connect(lambda k=key: self._apply(k))
        self.refresh()

    @property
    def layout(self) -> Layout:
        """Rozložení, které panel zobrazuje (kopie v dialogu, jinak rozložení listu)."""
        return self._layout if self._layout is not None else self._sheet.layout

    def load_from_model(self) -> None:
        """Načte pole z rozložení (po undo/redo); texty vypnuté skupiny „Výrobní data“ zůstanou."""
        from envocad.model.wiring import parse_param
        lay = self.layout
        self._suspend = True
        try:
            if self.name.text().strip() != lay.enclosure:
                self.name.setText(lay.enclosure)
            self.rows.setValue(lay.rows)
            self.mods.setValue(lay.modules_per_row)
            own_wiring = any(k in lay.params for k in self._wiring_keys)
            self.wiring_group.setChecked(own_wiring)
            defaults = {k: d for k, _l, d in ENCLOSURE_PARAMS}
            for key, ed in self._edits.items():
                if key in self._wiring_keys and not own_wiring:
                    continue
                text = lay.params.get(key, "" if key in self._wiring_keys else defaults.get(key, ""))
                if ed.text().strip() != text:
                    ed.setText(text)
            if own_wiring:
                for key, combo in self._choices.items():
                    cur = parse_param(key, lay.params.get(key)) or ""
                    combo.setCurrentIndex(max(combo.findData(cur), 0))
        finally:
            self._suspend = False
        self.refresh()

    def invalid_fields(self) -> dict[str, str]:
        """Pole s neplatným číslem → česká hláška (`project.enclosure_param_error`; vypnutá skupina výrobních dat
        se nekontroluje)."""
        own_wiring = self.wiring_group.isChecked()
        return {k: msg for k, ed in self._edits.items()
                if (own_wiring or k not in self._wiring_keys) and (msg := enclosure_param_error(k, ed.text()))}

    def _mark_invalid(self) -> None:
        bad = self.invalid_fields()
        for k, ed in self._edits.items():
            msg = bad.get(k)
            ed.setStyleSheet(f"border: 1px solid {INVALID_COLOR};" if msg else "")
            ed.setToolTip(msg or "")
        if bad:
            self.errors.setText("Neplatné hodnoty – nepoužity, platí předchozí: " + "; ".join(bad.values()))
        self.errors.setVisible(bool(bad))

    def refresh(self) -> None:
        """Přepočítá informační texty (po změně rozložení nebo přístrojů)."""
        from envocad.model.checks import layout_problems
        from envocad.model.thermal import layout_inputs, temperature_rise
        lay = self.layout
        total = lay.total_modules
        used = lay.used_modules(self._sheet, self._project, self.library)
        pct = (used / total * 100) if total else 0
        reserve = total - used
        self.info.setText(f"{total} modulů celkem, obsazeno {used:g} ({pct:.0f} %), rezerva {reserve:g} M; "
                          f"užitná šířka řady {lay.modules_per_row * MODULE_WIDTH:g} mm, "
                          f"skříň {lay.width_mm:g} × {lay.height_mm:g} mm")
        warn = []
        if reserve < -1e-6:
            warn.append(f"Skříň je přeplněná: rozmístěné přístroje zabírají o {-reserve:g} M víc, než skříň má.")
        probs = layout_problems(self._sheet, self._project, lay, self.library)
        n_over = sum(1 for x in probs if x.code == "layout_overflow" and x.element is not None)
        n_rows = sum(1 for x in probs if x.code == "layout_overflow" and x.element is None)
        n_lap = sum(1 for x in probs if x.code == "layout_overlap")
        if n_rows:
            warn.append(f"Přeplněné řady: {n_rows}.")
        if n_over:
            warn.append(f"Přístroje za koncem řady: {n_over} (zůstávají umístěné, upravte rozložení).")
        if n_lap:
            warn.append(f"Překryvy přístrojů v řadě: {n_lap}.")
        from envocad.model.device_size import size_problems
        sizes = size_problems(self._sheet, self._project, self.library, lay)   # rozměry z artiklu proti řadě / skříni
        for code, text in (("layout_height", "Přístroje vyšší než rozteč řad"),
                           ("layout_enclosure", "Přístroje přesahující skříň"),
                           ("layout_depth", "Přístroje hlubší než skříň")):
            n = sum(1 for x in sizes if x.code == code)
            if n:
                warn.append(f"{text}: {n}.")
        self.warning.setText(" ".join(warn))
        self.warning.setVisible(bool(warn))
        self._mark_invalid()
        rdf, t_amb = layout_inputs(lay)   # každá hodnota zvlášť; neplatná / nezadaná = výchozí
        r = temperature_rise(self._sheet, rdf=rdf, t_ambient_c=t_amb, project=self._project, layout=lay,
                             lib=self.library)
        src = r.loss_summary()      # zdroj ztrát: artikl / ruční / odhad
        txt = (f"Ztráty přístrojů ΣPv = {r.p_devices_w:g} W" + (f" ({src})" if src else "")
               + f", celkem s vodiči {r.p_total_w:g} W\n"
               f"Účinná chladicí plocha Ae = {r.ae_m2:g} m²\n"
               f"Oteplení: střed Δt = {r.dt_mid_k:g} K, horní část Δt = {r.dt_top_k:g} K "
               f"→ ≈ {r.t_top_c:g} °C při okolí {r.t_ambient_c:g} °C\n")
        if r.critical() is not None:
            txt += f"Kritický přístroj: {r.critical_text()}\n"
        txt += f"Hodnocení: {r.verdict()}"
        if r.notes:
            txt += "\n" + "; ".join(r.notes)
        self.thermal.setText(txt)

    def pick_enclosure(self) -> None:
        from envocad.ui.component_picker import ComponentPicker
        dlg = ComponentPicker(self.library, category="enclosure", parent=self, title="Vybrat skříň z knihovny")
        if dlg.exec() != ComponentPicker.Accepted or not dlg.selected:
            return
        self.set_enclosure_component(dlg.selected)

    def set_enclosure_component(self, c) -> None:
        """Skříň z knihovny: vyplní pole artiklem a propíše je jako jednu změnu (jeden krok undo)."""
        self._suspend = True
        try:
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
        finally:
            self._suspend = False
        self._apply(None)

    def _apply(self, key: str | None = None) -> None:
        if self._suspend:
            return
        self.apply(key)
        self.refresh()
        self.changed.emit()

    def apply(self, key: str | None = None) -> Layout:
        """Propíše pole do rozložení: bez `commit` přímo, s `commit` jako snímky před/po (model mění až příkaz)."""
        if self._commit is None:
            return self._write(self.layout)
        import copy
        before = copy.deepcopy(self.layout.to_dict())
        after = self._write(Layout.from_dict(copy.deepcopy(before))).to_dict()
        if self.real_change(before, after):
            self._commit(before, after, key)
        return self.layout

    @staticmethod
    def real_change(before: dict, after: dict) -> bool:
        """Liší se rozložení? `_write` výchozí hodnoty nevyplněných polí nedoplňuje, takže stačí porovnat obsah
        (průchod polem beze změny není změna ani krok undo)."""
        return after != before

    def _write(self, lay: Layout) -> Layout:
        # model-write-ok: `lay` je kopie rozložení – s `commit` kopie snímku (`apply`), bez něj pracovní kopie
        # dialogu (`EnclosureDialog.working`); do listu ho zapíše `SetLayoutCommand`
        lay.enclosure = self.name.text().strip()
        lay.rows = self.rows.value()   # model-write-ok: kopie rozložení (viz výše)
        lay.modules_per_row = self.mods.value()   # model-write-ok: kopie rozložení (viz výše)
        own_wiring = self.wiring_group.isChecked()
        # výchozí hodnotu pole, které v parametrech nebylo (panel ji jen ukazuje), nedoplňovat – jinak by se
        # rozložení změnilo pouhým zápisem jiného pole a krok undo by po návratu hodnoty nezmizel
        defaults = {k: d for k, _l, d in ENCLOSURE_PARAMS if d}
        bad = self.invalid_fields()
        edits = {k: e.text().strip() for k, e in self._edits.items()
                 if k not in bad and e.text().strip() and (own_wiring or k not in self._wiring_keys)
                 and (k in lay.params or defaults.get(k) != e.text().strip())}
        # neplatné číslo se do modelu nepropíše: zůstane předchozí hodnota (pole je zvýrazněné, viz `_mark_invalid`)
        edits.update({k: lay.params[k] for k in bad if k in lay.params})
        for key, combo in self._choices.items():
            if own_wiring and combo.currentData():
                edits[key] = combo.currentData()
        # klíče, které panel nezná, zůstanou; wire_* spravuje skupina „Výrobní data“
        unknown = {k: v for k, v in lay.params.items() if k not in self._edits and k not in self._wiring_keys}
        lay.params = {**unknown, **edits}   # model-write-ok: kopie rozložení (viz začátek `_write`)
        # umístění v řadách nad novým počtem řad zůstanou (vrátí se po zvětšení počtu řad); do té doby je rozložení
        # kreslí mezi nerozmístěnými a kontrola je hlásí (`outside_enclosure`)
        return lay


class EnclosureDialog(QDialog):
    """Totéž jako panel, ale modálně (z menu List). Pracuje na kopii rozložení – list se nemění; po OK si okno
    výsledek (`apply()`) propíše příkazem `SetLayoutCommand`, Zrušit = žádná změna."""

    def __init__(self, sheet: Sheet, parent=None, library=None, project: Project | None = None):
        super().__init__(parent)
        import copy
        self.setWindowTitle(f"Skříň rozvaděče – {sheet.name}")
        self.setMinimumWidth(480)
        self.working = Layout.from_dict(copy.deepcopy(sheet.layout.to_dict()))
        self.panel = EnclosurePanel(sheet, library=library, project=project, layout=self.working)
        lay = QVBoxLayout(self)
        lay.addWidget(self.panel)
        bb = button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        # pohodlné aliasy pro testy
        self.name, self.rows, self.mods, self.info, self._edits = (self.panel.name, self.panel.rows, self.panel.mods,
                                                                   self.panel.info, self.panel._edits)

    def apply(self) -> Layout:
        return self.panel.apply()


class SheetPropsDialog(QDialog):
    """Vlastnosti listu: název a strukturní označení (=funkce, +umístění)."""

    def __init__(self, sheet: Sheet, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vlastnosti listu")
        self.setMinimumWidth(340)
        form = QFormLayout(self)
        self.name = QLineEdit(sheet.name)
        self.func = QLineEdit(sheet.func)
        self.loc = QLineEdit(sheet.loc)
        form.addRow("Název:", self.name)
        form.addRow("Funkce (=):", self.func)
        form.addRow("Umístění (+):", self.loc)
        self.paper: QComboBox | None = None
        if sheet.is_switchboard:
            # formát stran schématu (vícepólu) a plánu svorkovnice listu rozvaděče
            from envocad.model.multipole import SHEET_PAPER, SWITCHBOARD_PAPERS
            from envocad.settings import switchboard_paper
            self.paper = QComboBox()
            self.paper.addItem(f"podle firemního standardu ({_paper_text(switchboard_paper())})", "")
            for key in SWITCHBOARD_PAPERS:
                self.paper.addItem(_paper_text(key), key)
            self.paper.addItem(f"jako list ({sheet.paper}, {sheet.width:g} × {sheet.height:g} mm)", SHEET_PAPER)
            i = self.paper.findData(sheet.mp_paper or "")
            self.paper.setCurrentIndex(max(i, 0))
            form.addRow("Formát stran schématu:", self.paper)
        bb = button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self) -> tuple[str, str, str]:
        return self.name.text().strip(), self.func.text().strip().upper(), self.loc.text().strip().upper()

    def mp_paper(self) -> str | None:
        """Zvolený formát stran schématu rozvaděče („“ = standard); None = list není rozvaděč."""
        return None if self.paper is None else str(self.paper.currentData() or "")


def _paper_text(key: str) -> str:
    """Popis formátu stran pro výběr: „A4“ → „A4 na šířku“."""
    return key if "výšku" in key else f"{key} na šířku"


class StructuresDialog(QDialog):
    """Registr strukturního označení projektu: tabulka aspekt (=/+), kód, popis."""

    def __init__(self, structures: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Strukturní označení")
        self.resize(480, 360)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Aspekt „=“ je funkce, „+“ umístění. Kód: A–Z, 0–9, _ a tečka uvnitř (RFVE.AC), začíná písmenem."))
        note = QLabel("Úprava kódu zde nepřejmenuje jeho použití na listech a prvcích. Umístění rozvaděče "
                      "přejmenuješ změnou označení jeho bloku.")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Aspekt", "Kód", "Popis"])
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)
        for x in structures:
            self._add_row(x.aspect, x.code, x.description)
        row = QHBoxLayout()
        b_add = QPushButton("Přidat")
        b_del = QPushButton("Odebrat")
        b_add.clicked.connect(lambda: self._add_row("+", "", ""))
        b_del.clicked.connect(self._remove_row)
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addStretch()
        lay.addLayout(row)
        bb = button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _add_row(self, aspect: str, code: str, desc: str) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        combo = QComboBox()
        combo.addItems(["=", "+"])
        combo.setCurrentText(aspect if aspect in ("=", "+") else "+")
        self.table.setCellWidget(r, 0, combo)
        self.table.setItem(r, 1, QTableWidgetItem(code))
        self.table.setItem(r, 2, QTableWidgetItem(desc))

    def _remove_row(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def values(self) -> list:
        from envocad.model.project import StructureId
        out = []
        for r in range(self.table.rowCount()):
            code = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip().upper()
            desc = (self.table.item(r, 2).text() if self.table.item(r, 2) else "").strip()
            if code:
                out.append(StructureId(self.table.cellWidget(r, 0).currentText(), code, desc))
        return out

    def _accept(self) -> None:
        from envocad.model.designation import validate_code
        seen = set()
        for x in self.values():
            issues = validate_code(x.code, x.aspect)
            if issues:
                QMessageBox.warning(self, "Strukturní označení", issues[0].text)
                return
            if (x.aspect, x.code) in seen:
                QMessageBox.warning(self, "Strukturní označení", f"Kód {x.aspect}{x.code} je v tabulce víckrát")
                return
            seen.add((x.aspect, x.code))
        self.accept()


class MacroValuesDialog(QDialog):
    """Hodnoty proměnných makra před vložením: sada hodnot, pole podle typu, artikl s přepočtem `from`.

    `.values()` = výsledné hodnoty (po `resolve_values`), `.value_set()` = zvolená sada nebo None."""

    CUSTOM = "— vlastní —"

    def __init__(self, macro, library, context: dict | None = None, parent=None, project=None, sheet=None):
        super().__init__(parent)
        self.macro, self.library, self.context = macro, library, dict(context or {})
        self.errors: list[str] = []
        self._fields: dict[str, QWidget] = {}
        self._loaded: dict[str, str] = {}   # hodnota pole nastavená dialogem (výchozí, kontext, sada) – ne uživatelem
        # navazující číslování podle listu (X9…, X3 „od T3“) – předvyplněné, ale posílá se jako zadané
        self._prefill: dict[str, str] = {}
        if project is not None and sheet is not None:
            from envocad.library.macros import suggest_numbering
            self._prefill = {k: v for k, v in suggest_numbering(project, sheet, macro).items() if k not in self.context}
        # názvy opakování (k, nk) doplní při vložení každá instance zvlášť → pole zakázaná
        self._per_run = repeat_context_names(macro) - set(self.context)
        self.setWindowTitle(f"Makro – {macro.name}")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        if macro.description:
            d = QLabel(macro.description)
            d.setWordWrap(True)
            root.addWidget(d)
        self.set_combo = QComboBox()
        self.set_combo.addItem(self.CUSTOM)
        for s in macro.value_sets:
            self.set_combo.addItem(s.name)
            if s.description:
                self.set_combo.setItemData(self.set_combo.count() - 1, s.description, Qt.ToolTipRole)
        top = QFormLayout()
        if macro.value_sets:
            top.addRow("Sada hodnot", self.set_combo)
            self.set_combo.currentIndexChanged.connect(self._apply_set)
        root.addLayout(top)
        main = QFormLayout()
        root.addLayout(main)
        count = macro.repeat.count if macro.repeat else ""
        auto = [v for v in macro.variables if v.auto and v.name != count]
        for v in macro.variables:
            if v in auto:
                continue
            # počet opakování je vždy povinný (hvězdička jako u povinných proměnných)
            main.addRow(self._label(v, required=v.required or v.name == count), self._make_field(v))
        self.extra = None
        self.k_start: QLineEdit | None = None
        editable = [v for v in auto if v.name not in self._per_run]
        if auto and (editable or macro.repeat):   # skupina jen s neaktivními poli (k, nk) se neukazuje
            self.extra = QGroupBox("Další (číslování)")
            self.extra.setCheckable(True)
            self.extra.setChecked(bool(self._prefill))   # navazující číslování: rovnou vidět, odkud se čísluje
            ef = QFormLayout()
            if macro.repeat:
                from envocad.library.macros import K_START
                self.k_start = QLineEdit(self._prefill.get(K_START, "1"))
                self.k_start.setToolTip("První pořadové číslo k opakování (X{k}…) – předvyplněno další volné na listu")
                ef.addRow("Číslovat od (k)", self.k_start)
            for v in auto:
                ef.addRow(self._label(v), self._make_field(v))
            holder = QWidget()
            holder.setLayout(ef)
            lay = QVBoxLayout(self.extra)
            lay.setContentsMargins(6, 6, 6, 6)
            lay.addWidget(holder)
            holder.setVisible(self.extra.isChecked())
            self.extra.toggled.connect(holder.setVisible)
            root.addWidget(self.extra)
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #c0392b;")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)
        bb = button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self._load_defaults()

    # ---- pole ----------------------------------------------------------------
    def _label(self, v, required: bool | None = None) -> QLabel:
        required = v.required if required is None else required
        text = v.title + (f" [{v.unit}]" if v.unit else "") + (" *" if required else "")
        lab = QLabel(text)
        if required:
            f = lab.font()
            f.setBold(True)
            lab.setFont(f)
        if v.help:
            lab.setToolTip(v.help)
        return lab

    def _make_field(self, v) -> QWidget:
        if v.type == "choice":
            w = QComboBox()
            for c in v.choices:
                w.addItem(c or "(prázdné)", c)
        elif v.type == "component":
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(readOnly=True, placeholderText="(bez artiklu)")
            pick = QPushButton("Vybrat…")
            clear = QPushButton("×")
            clear.setMaximumWidth(28)
            clear.setToolTip("Zrušit výběr artiklu")
            h.addWidget(edit, 1)
            h.addWidget(pick)
            h.addWidget(clear)
            w.edit = edit
            pick.clicked.connect(lambda _=False, var=v: self._pick_component(var))
            clear.clicked.connect(lambda _=False, var=v: self._set_component(var, ""))
        else:
            w = QLineEdit()
            if v.type == "number":
                from PySide6.QtCore import QRegularExpression
                from PySide6.QtGui import QRegularExpressionValidator
                w.setValidator(QRegularExpressionValidator(QRegularExpression(r"^([-+]?[0-9]*[.,]?[0-9]*|\{.*)$")))
        if v.help:
            w.setToolTip(v.help)
        self._fields[v.name] = w
        if v.name in self._per_run:
            w.setEnabled(False)
            if isinstance(w, QLineEdit):
                w.setPlaceholderText("doplní se automaticky")
            w.setToolTip("Doplní se automaticky při opakování makra (každá instance zvlášť).")
        return w

    def _get(self, name: str) -> str:
        w = self._fields[name]
        if isinstance(w, QComboBox):
            return w.currentData() if w.currentData() is not None else w.currentText()
        if isinstance(w, QLineEdit):
            return w.text()
        return w.edit.text()

    def _set(self, name: str, value: str) -> None:
        w = self._fields.get(name)
        if w is None or name in self._per_run:
            return
        if isinstance(w, QComboBox):
            key = value.replace(" ", "").lower()
            for i in range(w.count()):
                if str(w.itemData(i)).replace(" ", "").lower() == key:
                    w.setCurrentIndex(i)
                    break
        elif isinstance(w, QLineEdit):
            w.setText(value)
        else:
            w.edit.setText(value)
        self._loaded[name] = self._get(name)

    def _load_defaults(self) -> None:
        for v in self.macro.variables:
            self._set(v.name, v.default)
        for k, val in self.context.items():
            self._set(k, str(val))
        for k, val in self._prefill.items():
            self._set(k, str(val))

    def _apply_set(self) -> None:
        vs = self.macro.value_set(self.set_combo.currentText())
        if vs is None:
            return
        for k, val in vs.values.items():
            self._set(k, val)
        for v in self.macro.variables:
            if v.type == "component" and v.name in vs.values:
                self._refresh_from(v)

    # ---- artikl ----------------------------------------------------------------
    def _pick_component(self, v) -> None:
        from envocad.ui.component_picker import ComponentPicker
        dlg = ComponentPicker(self.library, category=v.category or None, parent=self, title=f"Vybrat artikl – {v.title}")
        if dlg.exec() and dlg.selected:
            self._set_component(v, dlg.selected.id)

    def _set_component(self, v, cid: str) -> None:
        self._set(v.name, cid)
        self._refresh_from(v)

    def _refresh_from(self, v) -> None:
        """Po změně artiklu přepočítá pole s `from` odkazujícím na tuto proměnnou."""
        cid = self._get(v.name).strip()
        if not cid:
            return
        vals, _ = resolve_values(self.macro, given={v.name: cid}, components=self.library.component)
        for o in self.macro.variables:
            if o.source.partition(".")[0] == v.name and vals.get(o.name):
                self._set(o.name, vals[o.name])

    # ---- výsledek ----------------------------------------------------------------
    def value_set(self) -> str | None:
        return self.set_combo.currentText() if self.set_combo.currentIndex() > 0 else None

    def _resolve(self) -> tuple[dict, list[str]]:
        # automatická pole pošle jen změněná uživatelem (jinak by výchozí „1“ u k přebilo číslování opakování),
        # pole opakování (k, nk) nikdy – doplní je `expand` v každé instanci
        auto = {v.name for v in self.macro.variables if v.auto}
        given = {name: self._get(name) for name in self._fields
                 if name not in self._per_run
                 and (name not in auto or name in self._prefill or self._get(name) != self._loaded.get(name, ""))}
        if self.k_start is not None and self.k_start.text().strip() not in ("", "1"):
            from envocad.library.macros import K_START
            given[K_START] = self.k_start.text().strip()
        vals, errs = resolve_values(self.macro, given=given, value_set=self.value_set(),
                                    components=self.library.component, context=self.context)
        if self.k_start is not None:
            raw = self.k_start.text().strip() or "1"
            if not raw.isdigit() or int(raw) < 1:
                errs = [*errs, f"Číslovat od (k): „{raw}“ není celé kladné číslo."]
        return vals, errs

    def values(self) -> dict[str, str]:
        vals, self.errors = self._resolve()
        return vals

    def accept(self) -> None:
        self._values, self.errors = self._resolve()
        if self.errors:
            self.error_label.setText("\n".join(self.errors))
            self.error_label.setVisible(True)
            return
        super().accept()


class NoteDialog(QDialog):
    """Připomínka: text, stav (otevřeno/vyřešeno), vyřízení; autor a datum vzniku jen ke čtení. Přepnutí na
    „vyřešeno“ vyplní, kdo a kdy ji vyřešil (aktuální uživatel, teď). Vrací upravenou kopii přes `result_note()`."""

    def __init__(self, note, parent=None, title: str = "Připomínka"):
        super().__init__(parent)
        import copy

        from envocad.model.notes import STATUS_LABELS
        self.note = copy.deepcopy(note)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.text = QPlainTextEdit(note.text)
        self.text.setMinimumHeight(90)
        form.addRow("Text:", self.text)
        self.status = QComboBox()
        for key in ("open", "resolved"):
            self.status.addItem(STATUS_LABELS[key], key)
        self.status.setCurrentIndex(0 if note.status == "open" else 1)
        form.addRow("Stav:", self.status)
        self.reply = QLineEdit(note.reply)
        self.reply.setPlaceholderText("Jak byla připomínka vyřízena")
        form.addRow("Vyřízení:", self.reply)
        self.author = QLabel(note.author or "–")
        form.addRow("Autor:", self.author)
        self.created = QLabel(note.created.replace("T", " ") or "–")
        form.addRow("Vytvořeno:", self.created)
        self.resolved_label = QLabel()
        form.addRow("Vyřešeno:", self.resolved_label)
        lay.addLayout(form)
        bb = button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.status.currentIndexChanged.connect(self._status_changed)
        self._show_resolved()

    def _show_resolved(self) -> None:
        n = self.note
        self.resolved_label.setText(f"{n.resolved_by}, {n.resolved.replace('T', ' ')}" if n.resolved else "–")

    def _status_changed(self, _i: int) -> None:
        from envocad.model.notes import reopen, resolve
        from envocad.settings import current_user
        from envocad.ui.notes_view import now_iso
        if self.status.currentData() == "resolved":
            if not self.note.resolved:
                resolve(self.note, current_user(), now_iso())
        else:
            reopen(self.note)
        self._show_resolved()

    def result_note(self):
        """Poznámka s hodnotami z dialogu (kopie, originál zůstává beze změny)."""
        import copy
        n = copy.deepcopy(self.note)
        # model-write-ok: `n` je kopie připomínky, do projektu ji zapíše příkaz volajícího
        n.text = self.text.toPlainText().strip()
        n.reply = self.reply.text().strip()   # model-write-ok: kopie (viz výše)
        n.status = self.status.currentData()   # model-write-ok: kopie (viz výše)
        return n


# Vlastnosti projektu: (klíč, popisek); „name“ = Project.name, ostatní Project.meta
PROJECT_META_FIELDS = [
    ("name", "Název projektu"), ("investor", "Investor"), ("order", "Číslo zakázky"), ("place", "Místo"),
    ("author", "Zpracoval"), ("date", "Datum"), ("revision", "Revize"),
    # návrhové teploty kontroly stringů (`calc.design_temperatures`); prázdné = výchozí −10 / 70 °C
    ("pv_t_min", "Návrhová teplota min pro stringy [°C]"), ("pv_t_max", "Návrhová teplota max pro stringy [°C]"),
]
PROJECT_CHANGES_LABEL = "Změnový list (řádek = revize | datum | popis | zpracoval)"


class ProjectMetaDialog(QDialog):
    """Vlastnosti projektu – všechna pole v jednom formuláři; Zrušit = žádná změna."""

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vlastnosti projektu")
        self.setMinimumWidth(480)
        self._project = project
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.edits: dict[str, QLineEdit] = {}
        for key, label in PROJECT_META_FIELDS:
            ed = QLineEdit(project.name if key == "name" else project.meta.get(key, ""))
            self.edits[key] = ed
            form.addRow(label, ed)
        self.changes = QPlainTextEdit(project.meta.get("changes", ""))
        self.changes.setMinimumHeight(90)
        form.addRow(QLabel(PROJECT_CHANGES_LABEL))
        form.addRow(self.changes)
        bb = button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def errors(self) -> list[str]:
        """Chyby polí česky: návrhové teploty musí být čísla (prázdné = výchozí), min < max."""
        errs, temps = [], {}
        for key, label in PROJECT_META_FIELDS:
            if key in ("pv_t_min", "pv_t_max") and self.edits[key].text().strip():
                try:
                    temps[key] = parse_temperature_field(self.edits[key].text(), label)
                except ValueError as ex:
                    errs.append(str(ex))
        if len(temps) == 2 and temps["pv_t_min"] >= temps["pv_t_max"]:
            errs.append("Návrhová teplota min musí být menší než max.")
        return errs

    def accept(self) -> None:
        errs = self.errors()
        if errs:   # dialog zůstane otevřený
            QMessageBox.warning(self, "Vlastnosti projektu", "Opravte prosím zadání:\n\n"
                                + "\n".join(f"• {e}" for e in errs))
            return
        super().accept()

    def values(self) -> tuple[str, dict[str, str]]:
        """(název, meta): ostatní klíče meta zůstanou; prázdné pole klíč, který v meta nebyl, nepřidá. Platné návrhové
        teploty se uloží normalizované („−20 °C“ → „-20“)."""
        from envocad.model.calc import parse_temperature
        meta = dict(self._project.meta)
        texts = {k: ed.text() for k, ed in self.edits.items() if k != "name"}
        for k in ("pv_t_min", "pv_t_max"):
            t = parse_temperature(texts.get(k))
            if t is not None:
                texts[k] = f"{t:g}"
        texts["changes"] = self.changes.toPlainText()
        for k, v in texts.items():
            if v or k in meta:
                meta[k] = v
        return self.edits["name"].text(), meta
