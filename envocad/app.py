"""Vstupní bod GUI."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication


def main() -> None:
    from envocad.logging_setup import log, setup

    log_path = setup()
    app = QApplication(sys.argv)
    app.setApplicationName("EnvoCAD")
    app.setOrganizationName("ENVO")
    from envocad.model.project import Project
    from envocad.ui import theme
    from envocad.ui.main_window import MainWindow

    theme.apply(theme.load_saved(), app)

    project = Project.load(sys.argv[1]) if len(sys.argv) > 1 else None
    win = MainWindow(project=project)
    win.statusBar().showMessage(f"Log: {log_path}", 5000)
    win.show()
    log.info("Okno zobrazeno")
    rc = app.exec()
    log.info("Konec, kód %s", rc)
    sys.exit(rc)


if __name__ == "__main__":
    main()
