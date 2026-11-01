$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Test-Path ".venv")) {
    py -3.10 -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -e .

Write-Host ""
Write-Host "セットアップ完了。run.ps1 で起動できます。" -ForegroundColor Green
Write-Host "Ollamaを使う場合: ollama pull qwen2.5:3b"

