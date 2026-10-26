# Sestaví samostatnou aplikaci do dist\EnvoCAD (Windows). Výsledek: zabalit složku dist\EnvoCAD do ZIP.
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean envocad.spec
Write-Host "Hotovo: dist\EnvoCAD\EnvoCAD.exe" -ForegroundColor Green
