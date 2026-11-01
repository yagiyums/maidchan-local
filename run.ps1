$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "先に setup.ps1 を実行してください。"
}

Set-Location $ProjectRoot
& $Python -m maidchan.main

