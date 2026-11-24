"""Dokovací panely: knihovna symbolů a vlastnosti vybraného prvku."""
from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envocad.library.store import LibraryStore
from envocad.model.project import SWITCHBOARD_WIRE_ATTRIBUTES, WIRE_ATTRIBUTES
from envocad.ui.items import ElementItem, WireItem


class LibraryPanel(QWidget):
    symbol_chosen = Signal(str)
    macro_chosen = Signal(str)   # cesta k souboru makra

    def __init__(self, library: LibraryStore):
        super().__init__()
        self.library = library
        self.search = QLineEdit(placeholderText="Hledat symbol…")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.addWidget(self.search)
        lay.addWidget(self.tree)
        self.search.textChanged.connect(self.refresh)
        self.tree.itemDoubleClicked.connect(self._dbl)
        self.refresh()

    KIND_ORDER: ClassVar[list[str]] = ["Zdroje", "Střídače a měniče", "Jištění", "Spínání", "Měření", "Svorky a propojení", "Rozvaděče",
                  "Síť a zátěž", "Transformátory a napájení", "Relé a stykače", "Kabely", "Konektory", "Instalace",
                  "Elektronika", "Ostatní"]

    def refresh(self) -> None:
        """Strom: druh prvku (nadpis) → vlastní značky, pod nimi sbalená složka s cizími (QET…).
        Pól se nerozlišuje – v JPS je značka vždy jednopólová, ve vícepólu se rozkreslí sama."""
        self.tree.clear()
        searching = bool(self.search.text())
        kinds: dict[str, QTreeWidgetItem] = {}
        subs: dict[tuple[str, str], QTreeWidgetItem] = {}
        rows = self.library.list_symbols(self.search.text())
        order = {k: i for i, k in enumerate(self.KIND_ORDER)}
        rows.sort(key=lambda r: (order.get(r[2].split("/")[0], 99), "/" in r[2], r[1]))
        for sid, name, cat in rows:
            kind, _, sub = cat.partition("/")
            kind = kind or "Ostatní"
            parent = kinds.get(kind)
            if parent is None:
                parent = QTreeWidgetItem([kind])
                parent.setFlags(parent.flags() & ~Qt.ItemIsSelectable)
                kinds[kind] = parent
                self.tree.addTopLevelItem(parent)
            if sub:
                holder = subs.get((kind, sub))
                if holder is None:
                    holder = QTreeWidgetItem([sub])
                    holder.setFlags(holder.flags() & ~Qt.ItemIsSelectable)
                    subs[(kind, sub)] = holder
                    parent.addChild(holder)
                parent = holder
            it = QTreeWidgetItem([name])
            it.setData(0, Qt.UserRole, sid)
            it.setToolTip(0, sid)
            parent.addChild(it)
        for parent in kinds.values():
            parent.setExpanded(True)
        # makra (sestavy prvků) – vlastní, sdílená, vestavěná
        from envocad.library.macros import list_macros
        q = self.search.text().lower()
        macros = [m for m in list_macros() if not q or q in m.name.lower() or q in m.description.lower()]
        if macros:
            top = QTreeWidgetItem(["Makra"])
            top.setFlags(top.flags() & ~Qt.ItemIsSelectable)
            self.tree.addTopLevelItem(top)
            for m in macros:
                it = QTreeWidgetItem([f"{m.name} ({m.size})"])
                it.setData(0, Qt.UserRole, "macro:" + str(m.path))
                it.setToolTip(0, f"{m.description or m.name}\n{m.source}: {m.path}")
                top.addChild(it)
            top.setExpanded(True)
        for (kind, sub), holder in subs.items():
            holder.setText(0, f"{sub} ({holder.childCount()})")
            holder.setExpanded(searching)

    def _dbl(self, item: QTreeWidgetItem, _col: int) -> None:
        sid = item.data(0, Qt.UserRole)
        if sid and str(sid).startswith("macro:"):
            self.macro_chosen.emit(str(sid)[6:])
        elif sid:
            self.symbol_chosen.emit(sid)


CONTACTS_HINT = "1/2 3/4 5/6 13/14 21/22, NO:11/14 NC:11/12"
DESIGNATION_KEYS = ("func", "loc")    # override aspektů prvku – kód A–Z, 0–9, _, tečka uvnitř


class PropertiesPanel(QWidget):
    attr_edited = Signal(str, bool, str, str)  # target_id, is_wire, key, value

    def __init__(self, library=None):
        super().__init__()
        self._library = library
        self.form = QFormLayout(self)
        self.form.setContentsMargins(4, 4, 4, 4)
        self._target: tuple[str, bool] | None = None
        self.show_item(None)

    def _clear(self) -> None:
        # removeRow() maže widgety okamžitě – kdyby zrovna QLineEdit vysílal editingFinished, Qt by
        # po návratu sahalo do smazané paměti (access violation). Proto takeRow + deleteLater.
        while self.form.rowCount():
            row = self.form.takeRow(0)
            for item in (row.labelItem, row.fieldItem):
                if item is None:
                    continue
                w = item.widget()
                if w is not None:
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()

    def show_item(self, item) -> None:
        self._clear()
        if isinstance(item, ElementItem):
            e, sym = item.element, item.symbol
            self._target = (e.id, False)
            comp = ""
            if e.component_id and self._library is not None:
                c = self._library.component(e.component_id)
                comp = f"<br><small>Artikl: {c.label}</small>" if c else ""
            self.form.addRow(QLabel(f"<b>{sym.name}</b><br><small>{sym.id}</small>{comp}"))
            for a in sym.attributes:
                if sym.id == "fve.interrupt" and a.key == "star_source":
                    self._add_check(a.key, "Zdroj hvězdy", e.attrs.get(a.key, "") == "1",
                                    "Bod se stejným označením, ze kterého vede hvězda k ostatním bodům "
                                    "(jinak se body řetězí)")
                elif a.choice_items():
                    self._add_choice(a.key, a.label, e.attrs.get(a.key, "") or a.default, a.choice_items())
                else:
                    self._add_field(a.key, a.label, e.attrs.get(a.key, ""))
            sc = item.scene()
            sheet = getattr(sc, "sheet", None)
            if self._is_mirror_host(sc, sheet, e):
                self._add_check("mirror", "Zobrazit zrcadlo kontaktů", str(e.attrs.get("mirror", "")).strip() != "0",
                                "Tabulka kontaktů s odkazy pod přístrojem (cívka, jistič, relé…)",
                                on_value="", off_value="0")
            self._add_field("func", "Funkce (=)", e.attrs.get("func", ""), getattr(sheet, "func", ""))
            self._add_field("loc", "Umístění (+)", e.attrs.get("loc", ""), getattr(sheet, "loc", ""))
            self._add_field("note", "Poznámka", e.attrs.get("note", ""))
            self.form.itemAt(self.form.rowCount() - 1, QFormLayout.FieldRole).widget().setToolTip(
                "Interní poznámka – do výkresu ani výkazů se nepropisuje")
            # rámečky jednopólového schématu: pole / kobka rozvaděče, trafostanice (bloky a prvky blokového schématu)
            if sheet is not None and sheet.is_switchboard and sym.id not in ("sb.busbar",):
                self._add_field("cell", "Pole / kobka (JPS)", e.attrs.get("cell", ""))
                self._add_size_fields(e)
            elif sheet is not None and not sheet.is_switchboard:
                self._add_field("station", "Trafostanice (JPS)", e.attrs.get("station", ""))
        elif isinstance(item, WireItem):
            w = item.wire
            self._target = (w.id, True)
            self.form.addRow(QLabel(f"<b>Vodič</b><br><small>{w.a.element_id}:{w.a.port} → {w.b.element_id}:{w.b.port}</small>"))
            sc = item.scene()
            sheet = getattr(sc, "sheet", None)
            if sheet is None or not sheet.is_switchboard:   # vnitřní vodič rozvaděče: bez kabelu a průřezu
                for a in WIRE_ATTRIBUTES:
                    self._add_field(a.key, a.label, w.attrs.get(a.key, ""))
            else:
                from envocad.model.wiring import wire_end_labels
                from envocad.ui.dialogs import wire_auto_hints
                hints = wire_auto_hints(sc.project, sheet, w)
                end_labels = wire_end_labels(sheet, w)   # „Koncovka A (F2:2)“
                for a in SWITCHBOARD_WIRE_ATTRIBUTES:
                    if a.key == "prod":
                        self._add_check("prod", "Do výrobního seznamu", str(w.attrs.get("prod", "")).strip() != "0",
                                        "Odškrtnutím se vodič vynechá z výrobního zapojovacího seznamu",
                                        on_value="", off_value="0")
                    else:
                        self._add_field(a.key, end_labels.get(a.key, a.label), w.attrs.get(a.key, ""),
                                        placeholder=hints.get(a.key, ""))
            conds = " ".join(w.conductors) or "–"
            terms = "<br>".join(f"{c}: {t.get('a', '')} → {t.get('b', '')}" for c, t in w.terminals.items()) or "–"
            self.form.addRow("Žíly", QLabel(conds))
            self.form.addRow("Svorky", QLabel(f"<small>{terms}</small>"))
            sc = item.scene()
            if sc is not None and hasattr(sc, "project") and self._library is not None:
                from envocad.model.potential import net_of_wire
                pots = net_of_wire(sc.project, self._library, w.id)
                txt = "<br>".join(f"{c}: {n.name}" + (f" <span style='color:#c33'>({n.short_issue()})</span>" if n.short_issue() else "")
                                  for c, n in pots.items()) or "–"
                self.form.addRow("Potenciál", QLabel(f"<small>{txt}</small>"))
        else:
            self._target = None
            self.form.addRow(QLabel("<i>Nic není vybráno</i>"))

    def _add_field(self, key: str, label: str, value: str, inherited: str | None = None,
                   placeholder: str = "") -> None:
        ed = QLineEdit(value)
        if placeholder:   # automatická hodnota, která se použije při prázdném poli
            ed.setPlaceholderText(placeholder)
            ed.setToolTip("Prázdné pole = automaticky")
        if inherited is not None:   # prázdné = dědí z listu; placeholder ukáže zděděnou hodnotu
            ed.setPlaceholderText(inherited or "(z listu)")
            ed.setToolTip("Prázdné pole = hodnota se zděďí z listu")
        if key == "contacts":
            ed.setPlaceholderText(CONTACTS_HINT)
            ed.setToolTip("Kontaktní obraz přístroje, páry svorek oddělené mezerou.\n"
                          f"Příklad: {CONTACTS_HINT}\nBez předpony druhu se určí podle čísel svorek (IEC 60947-5-1).")
        ed.editingFinished.connect(lambda k=key, w=ed: self._commit(k, w.text()))
        self.form.addRow(label, ed)

    def _add_size_fields(self, e) -> None:
        """Rozměry v rozložení rozvaděče (ruční přepis artiklu, `model/device_size`): prázdné pole = z artiklu /
        modulů – zástupný text ukáže použitou hodnotu a zdroj. Skupina svorek navíc koncové desky a artikl můstku."""
        from envocad.model.device_size import device_size
        from envocad.model.project import AUTO_WIDTH_TERMINALS, NON_DEVICE_SYMBOLS
        if e.symbol_id in NON_DEVICE_SYMBOLS:
            return
        sz = device_size(e, self._library)
        auto = {"width_mm": f"{sz.width_mm:g} ({sz.source})", "height_mm": f"{sz.height_mm:g} ({sz.height_source})",
                "depth_mm": f"{sz.depth_mm:g}" if sz.depth_mm else "neznámá"}
        for key, label in (("width_mm", "Šířka v rozložení [mm]"), ("height_mm", "Výška v rozložení [mm]"),
                           ("depth_mm", "Hloubka přístroje [mm]")):
            self._add_field(key, label, e.attrs.get(key, ""), placeholder=auto[key].replace(".", ","))
        if e.symbol_id in AUTO_WIDTH_TERMINALS:
            self._add_field("end_mm", "Koncové desky / zarážky [mm]", e.attrs.get("end_mm", ""), placeholder="0")
            self._add_choice("bridge_id", "Artikl můstku", e.attrs.get("bridge_id", ""), self._bridge_items(e))

    def _bridge_items(self, e) -> list[tuple[str, str]]:
        """Nabídka artiklů můstku pro skupinu svorek: obecný můstek + `bridge_candidates` (s artiklem svorky jen
        téhož výrobce). Uložené id mimo nabídku ukáže `ChoiceEdit` jako další položku."""
        items = [("", "(obecný můstek bez artiklu)")]
        if self._library is None:
            return items
        from envocad.library.components import bridge_candidates
        term = self._library.component(e.component_id) if e.component_id else None
        for c in bridge_candidates(self._library.components(category="accessory"), term):
            items.append((c.id, f"{c.manufacturer} {c.part_number} – {c.name}"))
        return items

    def _add_choice(self, key: str, label: str, value: str, items: list[tuple[str, str]]) -> None:
        """Nabídka hodnot atributu (`Attribute.choices`, např. směr přívodu/vývodu); změna = jeden příkaz undo."""
        from envocad.ui.dialogs import ChoiceEdit
        cb = ChoiceEdit(items, value)
        cb.currentIndexChanged.connect(lambda _i, k=key, w=cb: self._commit(k, w.text()))
        self.form.addRow(label, cb)

    @staticmethod
    def _is_mirror_host(sc, sheet, e) -> bool:
        """Prvek je hostitelem zrcadla kontaktů (skupina s kontakty nebo kontaktním obrazem) – jen ve schématu."""
        project = getattr(sc, "project", None)
        if project is None or sheet is None:
            return False
        from envocad.model.xref import is_mirror_host
        index = sc.device_index() if hasattr(sc, "device_index") else None
        try:
            return is_mirror_host(project, sheet, e, index)
        except Exception:  # noqa: BLE001 – panel nesmí spadnout na neúplném modelu
            return False

    def _add_check(self, key: str, label: str, checked: bool, tip: str = "", on_value: str = "1",
                   off_value: str = "") -> None:
        """Zaškrtávátko pro příznakový atribut (výchozí hodnoty "1" / "")."""
        cb = QCheckBox(label)
        cb.setChecked(checked)
        cb.setToolTip(tip)
        cb.toggled.connect(lambda on, k=key: self._commit(k, on_value if on else off_value))
        self.form.addRow(cb)

    @staticmethod
    def normalize(key: str, value: str) -> str:
        """Kód funkce/umístění prvku: ořez a velká písmena (jako dialog Vlastnosti listu); ostatní beze změny."""
        return value.strip().upper() if key in DESIGNATION_KEYS else value

    def _commit(self, key: str, value: str) -> None:
        value = self.normalize(key, value)
        if not self._target:
            return
        tid, is_wire = self._target
        # změna modelu až po doběhnutí signálu editingFinished (jinak se panel přestaví uvnitř emitu)
        QTimer.singleShot(0, lambda: self.attr_edited.emit(tid, is_wire, key, value))
