#!/usr/bin/env bash
# Spuštění EnvoCAD; před startem nabídne aktualizaci na novou vydanou verzi (envocad/updater.py).
cd "$(dirname "$0")/.."
.venv/bin/python -m envocad.updater check
if [ $? -eq 10 ]; then
  .venv/bin/python -m envocad.updater apply
fi
exec .venv/bin/python -m envocad "$@"