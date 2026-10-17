Write-Host "Starting AI Proctoring Backend Service..." -ForegroundColor Cyan
Set-Location $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" main.py
