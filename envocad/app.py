"""Vstupní bod GUI."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

QT_TRANSLATIONS = ("qtbase_cs", "qt_cs")   # české texty standardních tlačítek a dialogů Qt (Ano/Ne/Storno…)


def install_qt_translations(app) -> list:
    """Načte české překlady Qt (`qtbase_cs`, případně `qt_cs`) z adresáře překladů Qt (`QLibraryInfo`; v balíčku
    PyInstaller `PySide6/Qt/translations`) a nainstaluje je do aplikace. Vrací nainstalované překladače (aplikace si
    je musí držet – jinak je uvolní GC); chybějící soubor nevadí (zůstanou anglická tlačítka)."""
    from PySide6.QtCore import QLibraryInfo, QTranslator
    path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    out = []
    for name in QT_TRANSLATIONS:
        tr = QTranslator(app)
        if tr.load(name, path):
            app.installTranslator(tr)
            out.append(tr)
            if name == "qtbase_cs":
                break           # qt_cs je jen meta-soubor odkazující na qtbase_cs – stačí jeden
    app._envocad_translators = out
    return out


def main() -> None:
    from envocad.logging_setup import log, setup

    log_path = setup()
    app = QApplication(sys.argv)
    app.setApplicationName("EnvoCAD")
    app.setOrganizationName("ENVO")
    install_qt_translations(app)
    from envocad.ui import theme
    from envocad.ui.main_window import MainWindow

    theme.apply(theme.load_saved(), app)

    project, error = load_start_project(sys.argv[1:])
    win = MainWindow(project=project)
    win.statusBar().showMessage(f"Log: {log_path}", 5000)
    win.show()
    if error:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(win, "Projekt nelze otevřít", error)
    log.info("Okno zobrazeno")
    rc = app.exec()
    log.info("Konec, kód %s", rc)
    from envocad import logging_setup
    logging_setup.SHUTTING_DOWN = True  # chyby při likvidaci objektů už jen do logu, bez dialogu
    del win
    sys.exit(rc)


def _safe(fn, *args):
    """Krok aktualizace při startu – chyba se jen zaloguje, program se spustí v běžící verzi."""
    from envocad.logging_setup import log
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001
        log.exception("aktualizace při startu selhala")
        return None


def load_start_project(args: list[str]):
    """Projekt z příkazové řádky: (projekt, None), bez argumentu (None, None); vadný soubor → (None, česká hláška)
    a start s prázdným projektem."""
    from envocad.logging_setup import log
    from envocad.model.project import Project
    if not args:
        return None, None
    try:
        return Project.load(args[0]), None
    except Exception as ex:  # noqa: BLE001 – start nesmí spadnout na vadném souboru
        log.warning("projekt %s nejde otevřít: %s", args[0], ex)
        from envocad.ui.main_window import error_text
        return None, (f"Projekt nelze otevřít:\n{args[0]}\n\n{error_text(ex)}\n\n"
                      "EnvoCAD se spustí s prázdným projektem.")


if __name__ == "__main__":
    main()
