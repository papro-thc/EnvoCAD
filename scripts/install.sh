#!/usr/bin/env bash
# Instalace EnvoCAD na Linuxu (Fedora/Ubuntu/…). Spusťte v kořeni repozitáře: bash scripts/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)
echo "Používám $PY ($($PY --version))"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -e ".[dev]" -q
if ! .venv/bin/python -c "import PySide6.QtWidgets" 2>/dev/null; then
  echo "PySide6 se nepodařilo importovat – na Fedoře zkuste: sudo dnf install qt6-qtwayland libxkbcommon mesa-libGL" >&2
fi
echo
echo "Hotovo. Spuštění: scripts/run.sh   (Wayland potíže → QT_QPA_PLATFORM=xcb scripts/run.sh)"
