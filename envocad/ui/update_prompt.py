"""Dialogy aktualizace (logika bez Qt je v `envocad/updater.py`).

* `ask_update` – dotaz „Aktualizovat?“; volá ho spouštěč (`python -m envocad.updater check`) i samostatná aplikace;
* `startup_exe_update` – samostatná aplikace (PyInstaller) při startu: nabídka ze sdílené složky, kopie s průběhem,
  spuštění nové verze;
* `show_update_result` – po startu okna oznámí výsledek aktualizace provedené spouštěčem.
"""
from __future__ import annotations

import sys

from envocad import updater

MANIFEST_TIMEOUT_S = 3.0


def ask_update(offer: updater.Offer, current: str) -> bool:
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])
        app.setApplicationName("EnvoCAD")
        from envocad.app import install_qt_translations
        install_qt_translations(app)
    box = QMessageBox(QMessageBox.Question, "Aktualizace EnvoCAD",
                      f"Je k dispozici nová verze EnvoCAD {offer.version} (teď máte {current}).\n\n"
                      "Aktualizovat teď? Rozpracované projekty to neovlivní.")
    if offer.notes:
        box.setDetailedText(offer.notes)
    yes = box.addButton("Aktualizovat", QMessageBox.AcceptRole)
    box.addButton("Teď ne", QMessageBox.RejectRole)
    box.setDefaultButton(yes)
    box.exec()
    return box.clickedButton() is yes


def startup_exe_update(args: list[str]) -> bool:
    """Samostatná aplikace nainstalovaná s verzemi: nabídne novou verzi ze sdílené složky. True = nová verze byla
    spuštěna a tento proces má skončit."""
    root = updater.frozen_install_root()
    if root is None or not updater.enabled():
        return False
    source = updater.update_source(root)
    if source is None:
        return False
    offer = updater.call_with_timeout(lambda: updater.exe_offer(source), MANIFEST_TIMEOUT_S)
    if offer is None:
        return False
    state = updater.load_state()
    if updater.is_skipped(state, offer.version):
        return False
    if not ask_update(offer, updater.__version__):
        updater.remember_skip(state, offer.version)
        updater.save_state(state)
        return False

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog
    dlg = QProgressDialog(f"Kopíruji EnvoCAD {offer.version}…", "Zrušit", 0, 100)
    dlg.setWindowTitle("Aktualizace EnvoCAD")
    dlg.setWindowModality(Qt.ApplicationModal)
    dlg.setMinimumDuration(0)

    def progress(done: int, total: int) -> bool:
        dlg.setValue(int(done * 100 / max(total, 1)))
        QApplication.processEvents()
        return not dlg.wasCanceled()

    running = updater.__version__
    try:
        exe = updater.install_version(root, offer, progress, keep=(running,))
    except updater.UpdateError as ex:
        dlg.close()
        updater.log.warning("aktualizace samostatné aplikace: %s", ex)
        QMessageBox.warning(None, "Aktualizace EnvoCAD", f"{ex}\n\nEnvoCAD se spustí ve verzi {running}.")
        return False
    dlg.close()
    state = updater.load_state()
    state["result"] = {"ok": True, "version": offer.version, "from": running}
    updater.save_state(state)
    updater.launch(exe, args)
    return True


def show_update_result(win) -> None:
    """Hlášení o aktualizaci provedené před startem (spouštěč klonu nebo předchozí verze aplikace)."""
    res = updater.take_result()
    if not res:
        return
    if res.get("ok"):
        what = "vrácen na verzi" if res.get("rollback") else "aktualizován na verzi"
        win.statusBar().showMessage(f"EnvoCAD {what} {res.get('version', '')}", 15_000)
        return
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.warning(win, "Aktualizace EnvoCAD",
                        f"Aktualizace na verzi {res.get('version', '')} se nepovedla:\n{res.get('error', '')}\n\n"
                        f"Zůstává verze {updater.__version__}. Podrobnosti v ~/.envocad/log/update.log.")
