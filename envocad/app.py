"""Vstupní bod GUI."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("EnvoCAD")
    app.setOrganizationName("ENVO")
    from envocad.model.project import Project
    from envocad.ui import theme
    from envocad.ui.main_window import MainWindow

    theme.apply(theme.load_saved(), app)

    project = Project.load(sys.argv[1]) if len(sys.argv) > 1 else None
    win = MainWindow(project=project)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
