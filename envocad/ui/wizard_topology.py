"""Průvodce novým projektem: objekt a připojení, stávající rozvaděče a skupiny střídačů (topologie F5).

Návrh `docs/design/topologie_f1_f2.md` (kap. 2, „Průvodce (F5)“), `docs/NAVRH_TOPOLOGIE.md` (kap. 3.8 a 8).
Panel vytváří jen pole a čte je zpět do specifikace (`topology`, `chain.<role>.*`, `inverters[].ac_group`); model
nemění – projekt vzniká až v generátoru. Do specifikace se zapíše jen to, co se liší od výchozího (preset topologie
a kód generátoru), takže bez zásahu uživatele vznikne stejná specifikace jako dřív. Prázdné pole = neuvedeno
(do popisku bloku se nic nepíše, žádná chyba).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from envocad.generator.spec import (
    AUTO_TOPOLOGY,
    ROLES,
    chain_flag,
    chain_options,
    chain_text,
    grid_protection_limit,
    installed_kwp,
    parse_number,
    parse_strings,
    select_topology,
)
from envocad.library.topologies import list_topologies
from envocad.model.topology import Topology

FUSE_MIN_IN = 80.0     # vývod FVE do 80 A včetně vždy jistič (rozhodnutí 4; `boards.house_board.FVE_FUSE_MIN_IN`)

# výchozí hodnoty, když je preset neuvádí (shodné s generátorem)
CODE_DEFAULTS = {"main_device": {"rd": "switch", "hr": "breaker"}, "fve_device": "breaker", "metering": "direct",
                 "boundary": "hds", "char": "gG", "grid_protection": "auto"}

_WRAP_STYLE = "color: palette(placeholder-text);"
_ERR_STYLE = "color: #b00020;"


def _note(text: str = "", error: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(_ERR_STYLE if error else _WRAP_STYLE)
    return lab


def _in_edit(tip: str) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText("neuvedeno")
    e.setToolTip(tip)
    e.setMaximumWidth(110)
    return e


def _row(*widgets: QWidget) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        h.addWidget(x)
    h.addStretch(1)
    return w


class TopologyPanel:
    """Pole průvodce pro topologii připojení. `wizard` = `ProjectWizard` (druh objektu `building`, úroveň
    `conn_level`, pole `strings` a `mod_p`). Skupiny polí: `add_object_rows(form)` (do „Objekt a připojení“),
    `existing_group` („Stávající rozvaděče“) a `inverter_group` („Skupiny střídačů“)."""

    def __init__(self, wizard):
        self.w = wizard
        self._topo: Topology | None = None       # topologie podle současných voleb (None = volba je neplatná)
        self._topo_key: str | None = None        # id topologie, pro kterou jsou pole naplněná výchozími hodnotami
        self._busy = False
        self._group_texts: dict[int, str] = {}   # umístění střídačů podle pořadí (přežije změnu počtu střídačů)
        self._group_edits: list[QLineEdit] = []

        # ---- Objekt a připojení ----
        self.preset = QComboBox()
        self.preset.setToolTip("Automaticky: rodinný dům = RD, firma a bytový dům = nn, připojení na vn = vn. "
                               "Seznam obsahuje i sdílené a vlastní topologie (složka topologies).")
        self.chain_label = QLabel()
        self.chain_label.setWordWrap(True)
        self.chain_label.setTextFormat(Qt.PlainText)
        self.chain_label.setStyleSheet("font-weight: 600;")
        self.topo_error = _note(error=True)
        self.topo_error.hide()
        self.metering_at = QComboBox()
        self.metering_at.addItem("v elektroměrovém rozvaděči RE (výchozí)", "re")
        self.metering_at.addItem("v hlavním rozvaděči HR", "hr")
        self.metering_at.setToolTip("Kde je fakturační měření distributora. V HR vznikne řetězec bez RE "
                                    "(topologie „Připojení na nn, měření v HR“).")
        self.dc_per_inv = QCheckBox("samostatný RFVE.DC pro každý střídač (jinak jeden společný)")
        self.dc_per_inv.setToolTip("Jen při 2 a více střídačích; výchozí je společný RFVE.DC")
        self.gp = QComboBox()
        self.gp.addItem("automaticky podle výkonu", "auto")
        self.gp.addItem("ano – vždy vložit", "1")
        self.gp.addItem("ne – nevkládat", "0")
        self.gp_info = _note()
        self.level_note = _note()
        self.eps_note = _note()

        # ---- Stávající rozvaděče ----
        self.main_device = QComboBox()
        self.main_device.addItem("hlavní vypínač", "switch")
        self.main_device.addItem("hlavní jistič", "breaker")
        self.main_in = _in_edit("In hlavního přístroje stávajícího rozvaděče [A]; prázdné = neuvedeno")
        self.fve_device = QComboBox()
        self.fve_device.addItem("jistič", "breaker")
        self.fve_device.addItem("pojistkový odpínač", "fuse_disconnect")
        self.fve_in = _in_edit("In vývodu FVE [A]; prázdné = dopočte se z proudů střídačů")
        self.fve_note = _note()
        self.re_in = _in_edit("In hlavního jističe před elektroměrem (HJ) [A]; prázdné = neuvedeno")
        self.meter_mode = QComboBox()
        self.meter_mode.addItem("přímé", "direct")
        self.meter_mode.addItem("nepřímé (přes MTP)", "indirect")
        self.ct_ratio = QLineEdit()
        self.ct_ratio.setPlaceholderText("podle In HJ, např. 200/5 A")
        self.ct_ratio.setMinimumWidth(200)
        self.ct_ratio.setToolTip("Převod měřicího transformátoru proudu; prázdné = podle In HJ")
        self.boundary = QComboBox()
        self.boundary.addItem("v HDS", "hds")
        self.boundary.addItem("na svorkách HJ (re_main)", "re_main")
        self.boundary.addItem("za elektroměrem (re_meter)", "re_meter")
        self.boundary.setToolTip("Hranice vlastnictví mezi distributorem a odběratelem (kreslí se v blokovém schématu)")
        self.hds_in = _in_edit("In pojistek HDS [A]; prázdné = neuvedeno")
        self.hds_char = QLineEdit()
        self.hds_char.setPlaceholderText("gG")
        self.hds_char.setMaximumWidth(70)
        self.hds_char.setToolTip("Charakteristika pojistek HDS; prázdné = gG")
        self.existing_note = _note()
        self.main_label = QLabel("Hlavní přístroj")
        self.re_label = QLabel("HJ v RE – In [A]")

        self.existing_group = self._build_existing()
        self.inverter_group = QGroupBox("Skupiny střídačů (umístění)")
        self._inv_form = QFormLayout(self.inverter_group)
        self.group_note = _note()

        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.metering_at.currentIndexChanged.connect(self._metering_at_changed)
        self.gp.currentIndexChanged.connect(self.refresh)
        self.meter_mode.currentIndexChanged.connect(self._sync_enabled)
        for w in (self.fve_in, self.fve_device):
            (w.textChanged if isinstance(w, QLineEdit) else w.currentIndexChanged).connect(self._check_fuse)
        for w in (self.w.building, self.w.conn_level):
            w.currentIndexChanged.connect(self.refresh)
        for w in (self.w.strings, self.w.mod_p):
            w.textChanged.connect(self._inputs_changed)

    # ---- sestavení polí ----
    def add_object_rows(self, form: QFormLayout) -> None:
        """Řádky předvolby topologie a souvisejících voleb pod druh objektu a úroveň připojení."""
        form.addRow("", self.level_note)
        form.addRow("Topologie", self.preset)
        form.addRow("Řetězec FVE", self.chain_label)
        form.addRow("", self.topo_error)
        form.addRow("Fakturační měření", self.metering_at)
        form.addRow("RFVE.DC", self.dc_per_inv)
        form.addRow("Síťová ochrana", self.gp)
        form.addRow("", self.gp_info)
        form.addRow("", self.eps_note)

    def _build_existing(self) -> QGroupBox:
        g = QGroupBox("Stávající rozvaděče (údaje se propíšou do popisku bloků)")
        f = QFormLayout(g)
        f.addRow("", self.existing_note)
        f.addRow(self.main_label, _row(self.main_device, QLabel("In [A]"), self.main_in))
        f.addRow("Vývod FVE", _row(self.fve_device, QLabel("In [A]"), self.fve_in))
        f.addRow("", self.fve_note)
        f.addRow(self.re_label, _row(self.re_in))
        f.addRow("Měření", _row(self.meter_mode, QLabel("převod MTP"), self.ct_ratio))
        f.addRow("Hranice vlastnictví", self.boundary)
        f.addRow("HDS", _row(QLabel("In [A]"), self.hds_in, QLabel("charakteristika"), self.hds_char))
        return g

    # ---- stav podle voleb ----
    def building(self) -> str:
        return self.w.building.currentData() or "company"

    def level(self) -> str:
        return self.w.conn_level.currentData() or "nn"

    def candidates(self) -> list[Topology]:
        b, lv = self.building(), self.level()
        return [t for t in list_topologies(ROLES) if (not t.buildings or b in t.buildings) and t.level == lv]

    def selected_id(self) -> str:
        return self.preset.currentData() or ""

    def _select(self, topology_id: str) -> Topology:
        """`select_topology` pro současný objekt a úroveň (ValueError česky)."""
        spec = {"building": self.building(), "connection": {"level": self.level()}}
        if topology_id:
            spec["topology"] = topology_id
        return select_topology(spec)

    def n_inverters(self) -> int:
        try:
            return len(parse_strings(self.w.strings.text()))
        except ValueError:
            return 0

    def kwp(self) -> float:
        try:
            strings = parse_strings(self.w.strings.text())
        except ValueError:
            return 0.0
        return installed_kwp({"module": {"p_wp": self.w.mod_p.text()}, "inverters": [{"strings": s} for s in strings]})

    def meter_role(self) -> str:
        """Role článku s měřením: RE, nebo HR (měření v HR bez RE); u vn / bez měření prázdné."""
        t = self._topo
        if t is None or t.level != "nn":
            return ""
        if t.node("re") is not None:
            return "re"
        return "hr" if t.node("hr") is not None else ""

    def board_role(self) -> str:
        t = self._topo
        if t is None or t.level != "nn":
            return ""
        return "rd" if t.node("rd") is not None else ("hr" if t.node("hr") is not None else "")

    def ac_role(self) -> str:
        t = self._topo
        if t is None:
            return ""
        return "rfve" if t.node("rfve") is not None else ("rfve_ac" if t.node("rfve_ac") is not None else "")

    def groups_enabled(self) -> bool:
        """Skupiny střídačů jen na nn s RFVE.AC a HR (generátor jinak ValueError)."""
        t = self._topo
        return bool(t is not None and t.level == "nn" and t.node("rfve_ac") is not None and t.node("hr") is not None
                    and self.building() != "house")

    def _default(self, role: str, key: str) -> str:
        """Výchozí hodnota volby článku: preset > kód generátoru."""
        v = str(chain_options({}, self._topo, role).get(key, "") or "").strip()
        if v:
            return v
        d = CODE_DEFAULTS.get(key, "")
        return d.get(role, "") if isinstance(d, dict) else d

    # ---- obnova ----
    def _inputs_changed(self) -> None:
        self.refresh()

    def refresh(self, *_a) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self._refresh()
        finally:
            self._busy = False

    def _refresh(self) -> None:
        cands = self.candidates()
        keep = self.selected_id()
        if keep and keep not in {t.id for t in cands}:
            keep = ""
        try:
            auto = self._select("")
            auto_name = auto.name
        except ValueError:
            auto_name = "není k dispozici"
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItem(f"Automaticky – {auto_name}", "")
        for t in cands:
            src = "" if t.source == "vestavěná" else f" ({t.source})"
            self.preset.addItem(f"{t.name}{src}", t.id)
        self.preset.setCurrentIndex(max(0, self.preset.findData(keep)))
        self.preset.blockSignals(False)

        lv, b = self.level(), self.building()
        if b == "house":
            self.level_note.setText("Rodinný dům se připojuje na nn (rozvaděč FVE do HDS) – přípojka VN u něj není "
                                    "možná. Pro připojení na vn zvolte druh objektu firma nebo bytový dům.")
        else:
            self.level_note.setText("")
        self.level_note.setVisible(bool(self.level_note.text()))
        try:
            self._topo = self._select(self.selected_id())
            self.topo_error.hide()
            self.chain_label.setText(chain_text(self._topo))
        except ValueError as ex:
            self._topo = None
            self.chain_label.setText("")
            self.topo_error.setText(str(ex))
            self.topo_error.show()
        t = self._topo
        key = t.id if t is not None else None
        if key != self._topo_key:
            self._topo_key = key
            self._reset_defaults()

        # měření v RE / v HR
        has_hr_variant = lv == "nn" and b != "house" and any(c.id == "nn_hr_meter" for c in cands)
        self.metering_at.blockSignals(True)
        self.metering_at.setCurrentIndex(1 if (t is not None and self.meter_role() == "hr") else 0)
        self.metering_at.blockSignals(False)
        self.metering_at.setEnabled(has_hr_variant or self.metering_at.currentData() == "hr")
        if not self.metering_at.isEnabled():
            self.metering_at.setToolTip("Měření v HR lze zvolit u firmy a bytového domu při připojení na nn; "
                                        "rodinný dům a vn mají vlastní řetězec.")
        # RFVE.DC
        dc_node = t.node("rfve_dc") if t is not None else None
        self.dc_per_inv.setEnabled(dc_node is not None and self.n_inverters() >= 2)
        # síťová ochrana
        self.gp.setEnabled(bool(self.ac_role()))
        kwp, limit = self.kwp(), grid_protection_limit()
        auto_txt = "se vloží" if kwp > limit + 1e-9 else "se nevloží"
        self.gp_info.setText(f"Instalovaný výkon {kwp:g} kWp, hranice {limit:g} kWp – při volbě „automaticky“ "
                             f"se síťová ochrana {auto_txt}.")
        self.eps_note.setText(
            "EPS: přepínač sítí a zálohovaný vývod se kreslí u hybridního střídače s baterií "
            "(specifikace „battery“); u firmy a bytového domu se EPS nekreslí." if b == "house" else "")
        self.eps_note.setVisible(b == "house")
        self._sync_enabled()
        self._rebuild_groups()

    def _reset_defaults(self) -> None:
        """Pole stávajících rozvaděčů a RFVE.DC se po změně topologie vrátí na výchozí hodnoty presetu."""
        br, mr = self.board_role(), self.meter_role()
        for w in (self.main_in, self.fve_in, self.re_in, self.ct_ratio, self.hds_in, self.hds_char):
            w.clear()
        self._set(self.main_device, self._default(br, "main_device") if br else "breaker")
        self._set(self.fve_device, self._default(br, "fve_device") if br else "breaker")
        self._set(self.meter_mode, self._default(mr, "metering") if mr else "direct")
        self._set(self.boundary, self._default(mr, "boundary") if mr else "hds")
        self._set(self.gp, "auto")
        node = self._topo.node("rfve_dc") if self._topo is not None else None
        self.dc_per_inv.setChecked(bool(node is not None and chain_flag(
            chain_options({}, self._topo, "rfve_dc").get("per_inverter", node.per_inverter))))
        ac = self.ac_role()
        if ac:
            self._set(self.gp, self._gp_default(ac))

    def _gp_default(self, role: str) -> str:
        v = chain_options({}, self._topo, role).get("grid_protection")
        return {"1": "1", "0": "0", "true": "1", "false": "0"}.get(str(v).strip().lower(), "auto")

    @staticmethod
    def _set(combo: QComboBox, data) -> None:
        i = combo.findData(data)
        if i >= 0:
            combo.setCurrentIndex(i)

    def _sync_enabled(self, *_a) -> None:
        t = self._topo
        nn = t is not None and t.level == "nn"
        br, mr = self.board_role(), self.meter_role()
        hr_meter = mr == "hr"
        for w in (self.main_device, self.main_in, self.fve_device, self.fve_in, self.re_in, self.meter_mode,
                  self.boundary, self.hds_in, self.hds_char, self.ct_ratio):
            w.setEnabled(nn)
        if t is None:
            self.existing_note.setText("Nejprve opravte volbu topologie.")
        elif not nn:
            self.existing_note.setText("U připojení na vn se údaje zadávají v poli „Připojení k DS“ "
                                       "(trafostanice, měření, Sn transformátoru); stávající rozvaděče RD / HR / RE "
                                       "se u vn nezadávají.")
        else:
            self.existing_note.setText("Prázdné pole = neuvedeno (do popisku bloku se nic nepíše a nic se nedopočítává).")
        self.main_label.setText({"rd": "Hlavní přístroj RD", "hr": "Hlavní přístroj HR"}.get(br, "Hlavní přístroj"))
        if hr_meter:
            self.main_label.setText("HJ v HR (před elektroměrem)")
            self._set(self.main_device, "breaker")
            self.main_device.setEnabled(False)
        self.re_label.setText("HJ v RE – In [A]")
        self.re_in.setEnabled(nn and mr == "re")
        self.re_label.setEnabled(nn and mr == "re")
        self.meter_mode.setEnabled(nn and bool(mr))
        self.boundary.setEnabled(nn and bool(mr))
        self.ct_ratio.setEnabled(nn and bool(mr) and self.meter_mode.currentData() == "indirect")
        has_hds = nn and t.node("hds") is not None
        self.hds_in.setEnabled(has_hds)
        self.hds_char.setEnabled(has_hds)
        self._check_fuse()

    def _fuse_blocked(self) -> bool:
        """Pojistkový odpínač je dostupný jen nad 80 A: zadané In vývodu FVE ≤ 80 A ho vylučuje."""
        t = self.fve_in.text().strip()
        if not t:
            return False
        try:
            return parse_number(t, "In vývodu FVE") <= FUSE_MIN_IN
        except ValueError:
            return False

    def _check_fuse(self, *_a) -> None:
        blocked = self._fuse_blocked()
        item = self.fve_device.model().item(1)
        if item is not None:
            flags = item.flags()
            item.setFlags(flags & ~Qt.ItemIsEnabled if blocked else flags | Qt.ItemIsEnabled)
        if blocked and self.fve_device.currentData() == "fuse_disconnect":
            self.fve_note.setText(f"Vývod FVE do {FUSE_MIN_IN:g} A musí být jistič – pojistkový odpínač je jen "
                                  f"nad {FUSE_MIN_IN:g} A. Zvolte jistič nebo zvyšte In vývodu.")
            self.fve_note.setStyleSheet(_ERR_STYLE)
        else:
            self.fve_note.setText(f"Pojistkový odpínač je dostupný jen pro vývod nad {FUSE_MIN_IN:g} A "
                                  f"(do {FUSE_MIN_IN:g} A včetně vždy jistič)." + (
                                      " Při zadaném In ≤ 80 A je nedostupný." if blocked else ""))
            self.fve_note.setStyleSheet(_WRAP_STYLE)

    def _preset_changed(self, *_a) -> None:
        if not self._busy:
            self.refresh()

    def _metering_at_changed(self, *_a) -> None:
        if self._busy:
            return
        want_hr = self.metering_at.currentData() == "hr"
        self._busy = True
        try:
            if want_hr:
                self._set(self.preset, "nn_hr_meter")
            else:
                self.preset.setCurrentIndex(0)      # automaticky = nn s RE
        finally:
            self._busy = False
        self.refresh()

    # ---- skupiny střídačů ----
    def _rebuild_groups(self) -> None:
        n = self.n_inverters()
        enabled = self.groups_enabled()
        for i, e in enumerate(self._group_edits):
            self._group_texts[i] = e.text()
        while self._inv_form.rowCount():
            self._inv_form.removeRow(0)
        self._group_edits = []
        self.group_note = _note(
            "Střídače na jiném místě (např. jiná budova) dostanou vlastní AC rozvaděč RFVE.AC{n} a vlastní vývod FVE "
            "ve stávajícím HR. Prázdné = hlavní skupina. Jen pro připojení na nn." if enabled else
            "Skupiny střídačů jsou jen pro firmu a bytový dům při připojení na nn (s RFVE.AC a HR); "
            "u rodinného domu a vn se nepoužijí.")
        self._inv_form.addRow(self.group_note)
        for i in range(n):
            e = QLineEdit(self._group_texts.get(i, ""))
            e.setPlaceholderText("hlavní")
            e.setToolTip("Umístění / skupina střídače, např. „Hala B“; střídače se stejným názvem sdílejí RFVE.AC")
            e.setEnabled(enabled)
            self._group_edits.append(e)
            self._inv_form.addRow(f"T{i + 1} – umístění / skupina", e)

    def ac_group_for(self, i: int) -> str:
        if not self.groups_enabled() or i >= len(self._group_edits):
            return ""
        return self._group_edits[i].text().strip()

    # ---- specifikace a kontrola ----
    def _number(self, edit: QLineEdit, label: str, errs: list[str]):
        """Číslo z pole (prázdné = ""), chyba se přidá do `errs`."""
        t = edit.text().strip()
        if not t:
            return ""
        try:
            return parse_number(t, label)
        except ValueError as ex:
            errs.append(str(ex))
            return ""

    def parts(self) -> tuple[dict, list[str]]:
        """({"topology"?, "chain"?}, české chyby): jen hodnoty odlišné od výchozích."""
        errs: list[str] = []
        out: dict = {}
        t = self._topo
        if t is None:
            errs.append(self.topo_error.text() or "Topologie: neplatná volba.")
            return out, errs
        chosen = self.selected_id()
        if chosen:
            auto_id = AUTO_TOPOLOGY["house" if self.building() == "house" else self.level()]
            if chosen != auto_id:
                out["topology"] = chosen
        chain: dict = {}

        def put(role: str, key: str, value) -> None:
            if role and value not in ("", None) and str(value) != self._default(role, key):
                chain.setdefault(role, {})[key] = value

        if t.node("rfve_dc") is not None and self.dc_per_inv.isEnabled():
            default = chain_flag(chain_options({}, t, "rfve_dc").get("per_inverter", t.node("rfve_dc").per_inverter))
            if self.dc_per_inv.isChecked() != default:
                chain.setdefault("rfve_dc", {})["per_inverter"] = "1" if self.dc_per_inv.isChecked() else "0"
        ac = self.ac_role()
        if ac and self.gp.currentData() != self._gp_default(ac):
            chain.setdefault(ac, {})["grid_protection"] = self.gp.currentData()
        if t.level == "nn":
            br, mr = self.board_role(), self.meter_role()
            main_in = self._number(self.main_in, "In hlavního přístroje", errs)
            fve_in = self._number(self.fve_in, "In vývodu FVE", errs)
            if br:
                if mr != "hr":
                    put(br, "main_device", self.main_device.currentData())
                put(br, "main_in", main_in)
                put(br, "fve_device", self.fve_device.currentData())
                put(br, "fve_in", fve_in)
                if self.fve_device.currentData() == "fuse_disconnect" and fve_in != "" and fve_in <= FUSE_MIN_IN:
                    errs.append(f"Vývod FVE: do {FUSE_MIN_IN:g} A musí být jistič – pojistkový odpínač je jen nad "
                                f"{FUSE_MIN_IN:g} A (zadáno {fve_in:g} A).")
            if mr:
                if mr == "re":
                    put("re", "main_in", self._number(self.re_in, "In HJ v RE", errs))
                put(mr, "metering", self.meter_mode.currentData())
                if self.meter_mode.currentData() == "indirect":
                    put(mr, "ct_ratio", self.ct_ratio.text().strip())
                put(mr, "boundary", self.boundary.currentData())
            if t.node("hds") is not None:
                put("hds", "in_", self._number(self.hds_in, "In HDS", errs))
                put("hds", "char", self.hds_char.text().strip())
        if chain:
            out["chain"] = chain
        return out, errs

    def errors(self) -> list[str]:
        return self.parts()[1]

    def has_changes(self) -> bool:
        parts, _errs = self.parts()
        return bool(parts) or any(self.ac_group_for(i) for i in range(len(self._group_edits)))
