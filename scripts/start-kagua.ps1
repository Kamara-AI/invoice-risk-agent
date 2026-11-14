<#
.SYNOPSIS
    Start Kagua (FastAPI) on 127.0.0.1:8000 for the UiPath bot, if it is not already running.

.DESCRIPTION
    The TechByYou bot runs on this laptop (D9), and every Performer job starts
    with GET /health — so Kagua must be up before any job. This script is
    idempotent: if something already answers /health it exits without starting
    a second copy. Output goes to logs\kagua-<date>.log (EAT dates).

    Binds 127.0.0.1, never 0.0.0.0: Kagua is reachable only from this machine.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start-kagua.ps1
#>

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv\Scripts\python.exe'
$healthUrl = 'http://127.0.0.1:8000/health'

function Test-KaguaHealthy {
    try {
        $r = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
        return $r.status -eq 'ok'
    } catch {
        return $false
    }
}

if (Test-KaguaHealthy) {
    Write-Output "Kagua already running and healthy at $healthUrl"
    exit 0
}

if (-not (Test-Path $python)) {
    throw "Virtual environment not found at $python - run: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt"
}

# EAT date for the log file name, regardless of the machine's time zone.
$eatNow = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'E. Africa Standard Time')
$logDir = Join-Path $repo 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("kagua-{0:yyyy-MM-dd}.log" -f $eatNow)

Start-Process -FilePath $python `
    -ArgumentList '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000' `
    -WorkingDirectory $repo `
    -RedirectStandardOutput $log `
    -RedirectStandardError ($log -replace '\.log$', '.err.log') `
    -WindowStyle Hidden

# Wait up to 60 s for the first healthy answer (graph compilation takes a few seconds).
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if (Test-KaguaHealthy) {
        Write-Output "Kagua started and healthy at $healthUrl (log: $log)"
        exit 0
    }
}
throw "Kagua did not become healthy within 60 s - check $($log -replace '\.log$', '.err.log')"
