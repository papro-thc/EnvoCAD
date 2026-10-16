"""Dokovací panely: knihovna symbolů a vlastnosti vybraného prvku."""
from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from envocad.library.store import LibraryStore
from envocad.model.project import WIRE_ATTRIBUTES
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
                self._add_field(a.key, a.label, e.attrs.get(a.key, ""))
            sc = item.scene()
            sheet = getattr(sc, "sheet", None)
            self._add_field("func", "Funkce (=)", e.attrs.get("func", ""), getattr(sheet, "func", ""))
            self._add_field("loc", "Umístění (+)", e.attrs.get("loc", ""), getattr(sheet, "loc", ""))
        elif isinstance(item, WireItem):
            w = item.wire
            self._target = (w.id, True)
            self.form.addRow(QLabel(f"<b>Vodič</b><br><small>{w.a.element_id}:{w.a.port} → {w.b.element_id}:{w.b.port}</small>"))
            for a in WIRE_ATTRIBUTES:
                self._add_field(a.key, a.label, w.attrs.get(a.key, ""))
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

    def _add_field(self, key: str, label: str, value: str, inherited: str | None = None) -> None:
        ed = QLineEdit(value)
        if inherited is not None:   # prázdné = dědí z listu; placeholder ukáže zděděnou hodnotu
            ed.setPlaceholderText(inherited or "(z listu)")
            ed.setToolTip("Prázdné pole = hodnota se zděďí z listu")
        ed.editingFinished.connect(lambda k=key, w=ed: self._commit(k, w.text()))
        self.form.addRow(label, ed)

    def _commit(self, key: str, value: str) -> None:
        if not self._target:
            return
        tid, is_wire = self._target
        # změna modelu až po doběhnutí signálu editingFinished (jinak se panel přestaví uvnitř emitu)
        QTimer.singleShot(0, lambda: self.attr_edited.emit(tid, is_wire, key, value))
