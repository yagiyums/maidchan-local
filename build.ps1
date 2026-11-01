$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "先に setup.ps1 を実行してください。"
}

Set-Location $ProjectRoot
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name "MaidchanLocal" `
    --collect-data "maidchan" `
    --collect-all "comtypes" `
    --collect-all "vosk" `
    --exclude-module "comtypes.test" `
    --exclude-module "PySide6.QtWebEngineCore" `
    --exclude-module "PySide6.QtWebEngineWidgets" `
    --exclude-module "PySide6.QtPdf" `
    --exclude-module "PySide6.QtPdfWidgets" `
    "src\maidchan\main.py"

if ($LASTEXITCODE -ne 0) {
    throw "PyInstallerのビルドに失敗しました（終了コード: $LASTEXITCODE）。"
}

Write-Host "ビルド完了: dist\MaidchanLocal\MaidchanLocal.exe" -ForegroundColor Green

