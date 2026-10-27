# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: jeden adresář (dist/EnvoCAD) s binárkou EnvoCAD(.exe). Build: pyinstaller envocad.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH)
datas = collect_data_files("envocad", includes=["library/builtin/**/*.json", "library/builtin/**/*.csv",
                                                 "library/builtin/**/*.md", "plugins_builtin/*.py", "cmd/aliases.json",
                                                 "resources/icons/*.svg", "resources/*.json", "resources/icons/*.txt"],
                           include_py_files=True)
# české překlady Qt (tlačítka Ano/Ne/Storno, souborový dialog) – envocad.app.install_qt_translations je hledá
# v adresáři překladů Qt; cílová cesta v balíčku = stejná relativní cesta vůči site-packages jako ve vývojovém
# prostředí (Linux PySide6/Qt/translations, Windows PySide6/translations), kam míří i runtime hook PyInstalleru
import PySide6
from PySide6.QtCore import QLibraryInfo

_tr_src = Path(QLibraryInfo.path(QLibraryInfo.TranslationsPath)).resolve()
_tr_dest = _tr_src.relative_to(Path(PySide6.__file__).resolve().parent.parent)
for _name in ("qtbase_cs.qm", "qt_cs.qm"):
    if (_tr_src / _name).exists():
        datas.append((str(_tr_src / _name), str(_tr_dest)))
# pypdf se importuje lokálně ve funkci (export/pdf_annots.py) → PyInstaller ho sám nemusí najít
hidden = ["envocad.plugins_builtin.example_counts", "PySide6.QtSvg", "openpyxl", "docx", "ezdxf", "pypdf"]

a = Analysis(
    ["envocad/__main__.py"],
    pathex=[str(root)],
    datas=datas,
    hiddenimports=hidden,
    # ezdxf volitelně importuje scipy/matplotlib/pandas/PIL – pro nás zbytečné (ušetří ~150 MB)
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtPdf", "tkinter",
              "scipy", "matplotlib", "pandas", "PIL", "IPython", "jupyter", "pytest", "ruff"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="EnvoCAD",
    console=False,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="EnvoCAD")
