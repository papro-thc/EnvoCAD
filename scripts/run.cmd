@echo off
rem Spusteni EnvoCAD na Windows (dvojklik nebo z prikazove radky).
rem Pred startem nabidne aktualizaci na novou vydanou verzi (envocad\updater.py); po souhlasu ji provede
rem v samostatnem procesu bez Qt, aby pip mohl prepsat i PySide6.
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo EnvoCAD neni nainstalovany - spustte nejdriv scripts\install.cmd
  pause
  exit /b 1
)
"%PY%" -m envocad.updater check
if errorlevel 10 "%PY%" -m envocad.updater apply
"%PY%" -m envocad %*