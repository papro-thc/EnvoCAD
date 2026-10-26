@echo off
rem Spusteni EnvoCAD na Windows (dvojklik nebo z prikazove radky).
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo EnvoCAD neni nainstalovany - spustte nejdriv scripts\install.cmd
  pause
  exit /b 1
)
"%PY%" -m envocad %*
