$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
Set-Location $projectRoot

$configFile = Join-Path $projectRoot "config.local.ps1"

if (-not (Test-Path $configFile)) {
    Write-Host "Missing config.local.ps1" -ForegroundColor Red
    Write-Host "Create config.local.ps1 with the required Tanglaw-Buhay environment variables."
    exit 1
}

. $configFile

$requiredVariables = @(
    "DATABASE_URL",
    "TANGLAW_USERNAME",
    "TANGLAW_PASSWORD",
    "SECRET_KEY"
)

foreach ($variable in $requiredVariables) {
    if ([string]::IsNullOrWhiteSpace((Get-Item "Env:$variable" -ErrorAction SilentlyContinue).Value)) {
        Write-Host "Missing environment variable: $variable" -ForegroundColor Red
        exit 1
    }
}

$python = Join-Path $projectRoot "venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Python virtual environment not found." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Starting Tanglaw-Buhay..." -ForegroundColor Cyan
Write-Host "http://127.0.0.1:5000"
Write-Host ""

& $python "app.py"