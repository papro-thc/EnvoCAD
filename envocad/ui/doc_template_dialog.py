"""Dialog exportu technické zprávy / DSPS: výběr šablony (vestavěná, sdílená, vlastní, soubor .docx), u DSPS
projekt dle PD k porovnání a údaje o provedení. Návrh `docs/design/tz_dsps.md`. Model nemění – údaje DSPS vrací
`meta_updates()` a zapíše je volající přes `SetProjectMetaCommand`."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
)

from envocad.export.tz_data import DSPS_META
from envocad.library import doc_templates
from envocad.model.project import Project
from envocad.ui.dialogs import button_box

TITLES = {"tz": "Technická zpráva", "dsps": "Dokumentace skutečného provedení (DSPS)"}
OTHER = "__soubor__"


class DocExportDialog(QDialog):
    def __init__(self, project: Project, kind: str = "tz", parent=None):
        super().__init__(parent)
        self.kind = kind
        self._project = project
        self.setWindowTitle(TITLES[kind])
        self.setMinimumWidth(520)
        form = QFormLayout(self)
        self.template = QComboBox()
        default = doc_templates.default_template(kind)
        for t in doc_templates.list_templates(kind):
            self.template.addItem(t.label, str(t.path))
        if self.template.findData(str(default.path)) < 0:
            self.template.insertItem(0, default.label, str(default.path))
        self.template.addItem("Jiný soubor šablony (.docx)…", OTHER)
        self.template.setCurrentIndex(max(0, self.template.findData(str(default.path))))
        self.template.activated.connect(self._template_chosen)
        row = QHBoxLayout()
        row.addWidget(self.template, 1)
        save = QPushButton("Uložit šablonu jako .docx…")
        save.setToolTip("Vestavěná šablona s poli {{…}} jako dokument Word – základ firemní šablony. Upravenou ji "
                        "ulož do knihovny (složka doc_templates), název začni „tz“ nebo „dsps“.")
        save.clicked.connect(self._save_builtin)
        row.addWidget(save)
        form.addRow("Šablona", _wrap(row))
        self.old_path = QLineEdit()
        self.meta_edits: dict[str, QLineEdit] = {}
        if kind == "dsps":
            self.old_path.setPlaceholderText("projekt dle projektové dokumentace (.ecp) – změny proti němu")
            pick = QPushButton("Vybrat…")
            pick.clicked.connect(self._pick_old)
            r2 = QHBoxLayout()
            r2.addWidget(self.old_path, 1)
            r2.addWidget(pick)
            form.addRow("Porovnat s", _wrap(r2))
            for key, label in DSPS_META:
                ed = QLineEdit(str(project.meta.get(key, "") or ""))
                self.meta_edits[key] = ed
                form.addRow(label, ed)
            form.addRow(QLabel("Údaje o provedení se uloží do vlastností projektu."))
        bb = button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Exportovat…")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    # ---- volby ---------------------------------------------------------------------------------------------
    def template_path(self) -> Path | None:
        """Zvolená šablona; vestavěná výchozí → None (export použije vestavěnou)."""
        data = self.template.currentData()
        if not data or data == OTHER:
            return None
        p = Path(data)
        return None if p == doc_templates.builtin_template(self.kind) else p

    def old_project_path(self) -> str:
        return self.old_path.text().strip()

    def meta_updates(self) -> dict[str, str]:
        """Změněné údaje DSPS (klíč meta → hodnota); nezměněné a prázdné nové se nevrací."""
        out = {}
        for key, ed in self.meta_edits.items():
            v = ed.text().strip()
            if v != str(self._project.meta.get(key, "") or "") and (v or key in self._project.meta):
                out[key] = v
        return out

    def fields(self) -> dict[str, str]:
        return {key: ed.text().strip() for key, ed in self.meta_edits.items()}

    # ---- akce ----------------------------------------------------------------------------------------------
    def _template_chosen(self, index: int) -> None:
        if self.template.itemData(index) != OTHER:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Šablona dokumentu", "", "Šablona (*.docx *.md)")
        if not path:
            self.template.setCurrentIndex(0)
            return
        self.template.insertItem(index, f"{Path(path).name} (soubor)", path)
        self.template.setCurrentIndex(index)

    def _pick_old(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Projekt dle projektové dokumentace", "", "EnvoCAD projekt (*.ecp)")
        if path:
            self.old_path.setText(path)

    def _save_builtin(self) -> None:
        from envocad.export.tz_export import save_template_docx
        path, _ = QFileDialog.getSaveFileName(self, "Uložit šablonu", f"{self.kind}_firma.docx", "Word (*.docx)")
        if not path:
            return
        try:
            save_template_docx(self.kind, path)
        except OSError as ex:
            QMessageBox.warning(self, "Šablona", f"Šablonu nelze uložit: {ex}")


def _wrap(layout) -> QWidget:
    w = QWidget()
    layout.setContentsMargins(0, 0, 0, 0)
    w.setLayout(layout)
    return w
