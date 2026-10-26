@echo off
rem Instalace samostatne aplikace EnvoCAD ze sdilene slozky vydani (kopiruje ji tools\release.py publish).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_exe.ps1"
if errorlevel 1 pause
