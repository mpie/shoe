$ErrorActionPreference = "Stop"

$AppName = "SoleboxMonitor"
$IconIco = "assets\$AppName.ico"
$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "py -3.11" }

Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "==> Build venv maken"
Remove-Item -Recurse -Force ".build-venv", "build", "dist", "$AppName.spec" -ErrorAction SilentlyContinue
Invoke-Expression "$PythonBin -m venv .build-venv"
.\.build-venv\Scripts\python.exe -m pip install --upgrade pip
.\.build-venv\Scripts\pip.exe install -r requirements.txt -r requirements-build.txt

Write-Host "==> App icon maken"
.\.build-venv\Scripts\python.exe scripts\make_icon.py --ico $IconIco

Write-Host "==> Windows exe bouwen"
.\.build-venv\Scripts\pyinstaller.exe `
  --noconfirm `
  --windowed `
  --name $AppName `
  --icon $IconIco `
  --add-data "static;static" `
  --collect-all scrapling `
  --collect-all browserforge `
  --collect-all apify_fingerprint_datapoints `
  --collect-all playwright `
  --collect-all patchright `
  desktop_launcher.py

Write-Host ""
Write-Host "Klaar: dist\$AppName\$AppName.exe"
Write-Host ""
Write-Host "Als Playwright Chromium nog mist op een doelmachine:"
Write-Host "  py -3.11 -m pip install playwright==1.59.0"
Write-Host "  py -3.11 -m playwright install chromium"
