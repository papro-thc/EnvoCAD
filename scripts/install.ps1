# Instalace EnvoCAD pro vývoj/používání na Windows (PowerShell).
# Spusťte v kořeni repozitáře:  scripts\install.cmd   (= powershell -ExecutionPolicy Bypass -File scripts\install.ps1)
# Soubor musí zůstat v UTF-8 s BOM – Windows PowerShell 5.1 jinak čte češtinu jako ANSI a „–“ rozbije řetězce
# (hlídá tests/test_scripts_encoding.py).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# Najít Python 3.11–3.14: spouštěč „py“, jinak „python“ z PATH
$py = $null
foreach ($v in @("3.14", "3.13", "3.12", "3.11")) {
    try { & py -$v -c "import sys" 2>$null; if ($LASTEXITCODE -eq 0) { $py = "py -$v"; break } } catch {}
}
if (-not $py) {
    try {
        & python -c "import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 14) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $py = "python" }
    } catch {}
}
if (-not $py) {
    Write-Host "Python 3.11–3.14 nenalezen. Nainstalujte ho: py install 3.13   (nebo z python.org)" -ForegroundColor Yellow
    exit 1
}
Write-Host "Používám $py"
if (-not (Test-Path ".venv")) {
    Invoke-Expression "$py -m venv .venv"
    if ($LASTEXITCODE -ne 0) { Write-Host "Virtuální prostředí .venv nejde vytvořit." -ForegroundColor Red; exit 1 }
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip -q
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]" -q
if ($LASTEXITCODE -ne 0) { Write-Host "Instalace balíčků selhala (viz výpis pip výše)." -ForegroundColor Red; exit 1 }
Write-Host ""
Write-Host "Hotovo. Spuštění:  scripts\run.cmd   (nebo .venv\Scripts\python.exe -m envocad)" -ForegroundColor Green
