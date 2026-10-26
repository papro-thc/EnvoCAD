Set-Location (Split-Path $PSScriptRoot -Parent)
# před startem nabídne aktualizaci na novou vydanou verzi (envocad\updater.py), viz run.cmd
& .\.venv\Scripts\python.exe -m envocad.updater check
if ($LASTEXITCODE -eq 10) { & .\.venv\Scripts\python.exe -m envocad.updater apply }
& .\.venv\Scripts\python.exe -m envocad $args