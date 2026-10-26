@echo off
rem Instalace EnvoCAD na Windows - obejde zakaz spousteni skriptu PowerShellu (Execution Policy).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
