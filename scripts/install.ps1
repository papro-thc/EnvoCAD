# Instalace EnvoCAD pro vývoj/používání na Windows (PowerShell).
# Spusťte v kořeni repozitáře:  powershell -ExecutionPolicy Bypass -File scripts\install.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# Najít Python 3.11–3.13 (3.14 zatím nedoporučujeme – PySide6 na něm není prověřené)
$py = $null
foreach ($v in @("3.13", "3.12", "3.11")) {
    try { & py -$v -c "import sys" 2>$null; if ($LASTEXITCODE -eq 0) { $py = "py -$v"; break } } catch {}
}
if (-not $py) {
    Write-Host "Python 3.11–3.13 nenalezen. Nainstalujte ho: py install 3.13   (nebo z python.org)" -ForegroundColor Yellow
    exit 1
}
Write-Host "Používám $py"
if (-not (Test-Path ".venv")) { Invoke-Expression "$py -m venv .venv" }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip -q
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]" -q
Write-Host ""
Write-Host "Hotovo. Spuštění:  scripts\run.ps1   (nebo .venv\Scripts\python.exe -m envocad)" -ForegroundColor Green
