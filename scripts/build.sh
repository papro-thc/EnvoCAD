#!/usr/bin/env bash
# Sestaví samostatnou aplikaci do dist/EnvoCAD (Linux). Výsledek zabalit: tar czf EnvoCAD-linux.tar.gz -C dist EnvoCAD
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -m PyInstaller --noconfirm --clean envocad.spec
echo "Hotovo: dist/EnvoCAD/EnvoCAD"
