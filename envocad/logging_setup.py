"""Logování do ~/.envocad/log/ s rotací při každém startu + zachycení neošetřených výjimek.

Soubory: envocad.log (aktuální běh), envocad.log.1 … .5 (předchozí běhy). Pád tak zůstane čitelný
i po dalším spuštění. Na Windows: C:\\Users\\<uživatel>\\.envocad\\log\\envocad.log
"""
from __future__ import annotations

import faulthandler
import logging
import os
import platform
import sys
import traceback
from pathlib import Path

from envocad import __version__

KEEP = 5
SHUTTING_DOWN = False
_crash_file = None   # otevřený crash.log pro faulthandler
log = logging.getLogger("envocad")


def log_dir() -> Path:
    base = os.environ.get("ENVOCAD_HOME") or os.path.join(os.path.expanduser("~"), ".envocad")
    d = Path(base) / "log"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rotate(d: Path) -> None:
    """Posune staré logy (envocad.log → .1 → .2 …). Když log drží jiný běžící EnvoCAD (Windows: soubor otevřený
    jiným procesem nejde přejmenovat), rotace se přeskočí – druhá instance pak zapisuje do téhož logu, nespadne."""
    cur = d / "envocad.log"
    try:
        for i in range(KEEP - 1, 0, -1):
            src, dst = d / f"envocad.log.{i}", d / f"envocad.log.{i + 1}"
            if src.exists():
                src.replace(dst)
        if cur.exists():
            cur.replace(d / "envocad.log.1")
    except PermissionError:
        pass


def setup(show_dialog: bool = True) -> Path:
    global _crash_file
    d = log_dir()
    path = d / "envocad.log"
    root = logging.getLogger()
    # nejdřív zavřít soubory z předchozího volání – na Windows nejde otevřený soubor při rotaci přejmenovat
    for h in list(root.handlers):
        if getattr(h, "_envocad", False):
            root.removeHandler(h)
            h.close()
    if _crash_file is not None:
        faulthandler.disable()
        _crash_file.close()
        _crash_file = None
    _rotate(d)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for h in (logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler(sys.stderr)):
        h.setFormatter(fmt)
        h._envocad = True  # type: ignore[attr-defined]
        root.addHandler(h)
    root.setLevel(logging.INFO)
    # nativní pád (access violation / segfault) – Python by nic nevypsal; faulthandler zapíše zásobník
    _crash_file = open(d / "crash.log", "w", encoding="utf-8")  # noqa: SIM115 – musí zůstat otevřený
    faulthandler.enable(file=_crash_file, all_threads=True)
    log.info("EnvoCAD %s, Python %s, %s %s", __version__, platform.python_version(), platform.system(),
             platform.release())
    try:
        import PySide6
        log.info("PySide6 %s", PySide6.__version__)
    except Exception:  # noqa: BLE001, S110
        pass

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.critical("Neošetřená výjimka:\n%s", text)
        if show_dialog and not SHUTTING_DOWN:
            try:
                from PySide6.QtWidgets import QApplication, QMessageBox
                if QApplication.instance():
                    QMessageBox.critical(None, "EnvoCAD – chyba",
                                         f"Došlo k chybě (program může běžet dál, ale raději uložte práci).\n\n"
                                         f"{exc_type.__name__}: {exc}\n\nPodrobnosti: {path}")
            except Exception:  # noqa: BLE001, S110
                pass

    sys.excepthook = hook
    return path
