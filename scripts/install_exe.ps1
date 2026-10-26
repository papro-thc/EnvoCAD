# Instalace samostatné aplikace EnvoCAD (bez Pythonu) ze sdílené složky vydání – kolega spustí
# „Instalovat EnvoCAD.cmd“ přímo ze sdílené složky. Program se pak sám aktualizuje odtud (envocad\updater.py).
# Opakované spuštění = oprava instalace / ruční aktualizace na poslední verzi.
# Soubor musí zůstat v UTF-8 s BOM (tests/test_scripts_encoding.py).
$ErrorActionPreference = "Stop"
$source = $PSScriptRoot
$manifest = Get-Content (Join-Path $source "latest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$version = [string]$manifest.version
$zip = Join-Path $source ([IO.Path]::GetFileName([string]$manifest.zip))
if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() -ne ([string]$manifest.sha256).ToLower()) {
    Write-Host "Soubor $zip je poškozený (nesouhlasí SHA-256)." -ForegroundColor Red; exit 1
}
$root = Join-Path $env:LOCALAPPDATA "Programs\EnvoCAD"
$versions = Join-Path $root "versions"
$target = Join-Path $versions $version
New-Item -ItemType Directory -Force $versions | Out-Null
if (-not (Test-Path (Join-Path $target "EnvoCAD.exe"))) {
    Write-Host "Rozbaluji EnvoCAD $version do $target…"
    $tmp = "$target.tmp"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Expand-Archive -Path $zip -DestinationPath $tmp
    if (Test-Path $target) { Remove-Item -Recurse -Force $target }
    Rename-Item $tmp $target
}
$ascii = New-Object System.Text.ASCIIEncoding
[IO.File]::WriteAllText((Join-Path $root "current.txt"), $version, $ascii)
[IO.File]::WriteAllText((Join-Path $root "update_source.txt"), $source, (New-Object System.Text.UTF8Encoding $false))
$launcher = "@echo off`r`nset /p VER=<`"%~dp0current.txt`"`r`nstart `"`" `"%~dp0versions\%VER%\EnvoCAD.exe`" %*`r`n"
[IO.File]::WriteAllText((Join-Path $root "EnvoCAD.cmd"), $launcher, $ascii)

$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))) {
    $lnk = $shell.CreateShortcut((Join-Path $dir "EnvoCAD.lnk"))
    $lnk.TargetPath = Join-Path $root "EnvoCAD.cmd"
    $lnk.WorkingDirectory = $root
    $lnk.WindowStyle = 7          # minimalizovaně – okno spouštěče jen probleskne na liště
    $lnk.Description = "EnvoCAD – elektro-dokumentace FVE"
    $lnk.Save()
}
Write-Host ""
Write-Host "Hotovo: EnvoCAD $version, zástupce na ploše a v nabídce Start." -ForegroundColor Green