"""Úvodní obrazovka přes prázdný projekt: průvodce, otevřít, poslední projekty, nápověda ke vkládání značek.
Zmizí sama první změnou projektu nebo načtením jiného; křížkem ji jde zavřít."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget


class WelcomeOverlay(QFrame):
    wizard = Signal()
    open_project = Signal()
    open_recent = Signal(str)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("welcome")
        self.setFrameShape(QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        self.setStyleSheet("#welcome { background: palette(window); border: 1px solid palette(mid); border-radius: 6px; }"
                           " QPushButton { text-align: left; padding: 6px 10px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 18)
        head = QHBoxLayout()
        title = QLabel("<h2>EnvoCAD</h2>")
        head.addWidget(title, 1)
        close = QToolButton(text="×")
        close.setAutoRaise(True)
        close.setToolTip("Zavřít úvodní obrazovku")
        close.clicked.connect(self.hide)
        head.addWidget(close, 0, Qt.AlignTop)
        lay.addLayout(head)
        lay.addWidget(QLabel("Začněte novým projektem z průvodce, nebo otevřete rozpracovaný."))
        self.btn_wizard = QPushButton("Nový projekt z průvodce…  (Ctrl+Shift+N)")
        self.btn_wizard.clicked.connect(self.wizard.emit)
        self.btn_open = QPushButton("Otevřít projekt…  (Ctrl+O)")
        self.btn_open.clicked.connect(self.open_project.emit)
        lay.addWidget(self.btn_wizard)
        lay.addWidget(self.btn_open)
        self.recent_label = QLabel("<b>Poslední projekty</b>")
        lay.addSpacing(8)
        lay.addWidget(self.recent_label)
        self.recent_box = QVBoxLayout()
        lay.addLayout(self.recent_box)
        lay.addSpacing(8)
        hint = QLabel("Prázdné schéma: značku vložíte dvojklikem v panelu Knihovna nebo tlačítkem Vložit značku; "
                      "vodič = W, příkazy hledá Ctrl+K.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.setFixedWidth(440)

    def set_recent(self, paths: list[str]) -> None:
        while self.recent_box.count():
            w = self.recent_box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        shown = [p for p in paths if Path(p).exists()][:5]
        self.recent_label.setVisible(bool(shown))
        for p in shown:
            b = QPushButton(Path(p).name)
            b.setToolTip(p)
            b.setFlat(True)
            b.clicked.connect(lambda _c=False, p=p: self.open_recent.emit(p))
            self.recent_box.addWidget(b)
        self.adjustSize()

    def place(self) -> None:
        """Doprostřed rodiče (volá se při změně velikosti)."""
        par = self.parentWidget()
        self.adjustSize()
        self.move(max(0, (par.width() - self.width()) // 2), max(0, (par.height() - self.height()) // 3))
