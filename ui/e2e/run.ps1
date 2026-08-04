# Session orchestrator for the E2E loop.
#
# Keeps ONE backend alive across consecutive `playwright test` runs (the
# backend's embedding model is lazy-cached for the process lifetime and a
# full report.pdf index costs ~6-9 CPU minutes), warms report.pdf into it,
# boots vite, runs the suite, and optionally re-warms report.pdf afterwards
# so the next run starts warm again.
#
# Usage (from anywhere):
#   powershell -File ui/e2e/run.ps1          # warm -> run -> re-warm (unless -NoRewarm)
#   powershell -File ui/e2e/run.ps1 -NoRewarm
#   powershell -File ui/e2e/run.ps1 -Cleanup # stop vite + backend
param(
    [switch]$NoRewarm,
    [switch]$Cleanup
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$ui = Resolve-Path '..'
$root = Resolve-Path '..\..'

function Test-Port($port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Stop-Port($port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue }
}

if ($Cleanup) {
    Stop-Port 5173
    Stop-Port 8000
    Write-Host 'stopped vite and backend'
    exit 0
}

# -- 1. Backend -----------------------------------------------------------
if (-not (Test-Port 8000)) {
    Start-Process -FilePath 'python' -ArgumentList '-m', 'uvicorn', 'bfpc.api.app:app', '--host', '127.0.0.1', '--port', '8000' `
        -WorkingDirectory $root -WindowStyle Hidden
}
$up = $false
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/status' -TimeoutSec 2; $up = $true; break } catch { }
}
if (-not $up) { throw 'backend did not start on :8000' }

function Get-ActiveName {
    $s = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/status'
    if ($s.indexed) { return $s.filename }
    return $null
}

# -- 2. Warm report.pdf (only if not already active) ----------------------
function Warm-Report {
    $name = Get-ActiveName
    if ($name -eq 'report.pdf') { return }
    Write-Host 'warming index with report.pdf (first index can take several minutes)...'
    & curl.exe -sS --max-time 1800 -X POST -F "file=@$($root)\tests\fixtures\report.pdf" 'http://127.0.0.1:8000/api/index'
    $name = Get-ActiveName
    if ($name -ne 'report.pdf') { throw 'warm-up index of report.pdf failed' }
    Write-Host 'report.pdf is active and warm'
}
Warm-Report

# -- 3. Vite --------------------------------------------------------------
if (-not (Test-Port 5173)) {
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm run dev' -WorkingDirectory $ui -WindowStyle Hidden
}
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    try { $null = Invoke-WebRequest -Uri 'http://localhost:5173/' -UseBasicParsing -TimeoutSec 2; break } catch { }
}

# -- 4. Playwright --------------------------------------------------------
Set-Location $ui
npx playwright test --reporter=line
$exit = $LASTEXITCODE
Write-Host ("playwright exited: $exit")

# -- 5. Re-warm for the next run ------------------------------------------
if (-not $NoRewarm) {
    $name = Get-ActiveName
    if ($name -ne 'report.pdf') {
        Write-Host 're-warming report.pdf for the next run...'
        & curl.exe -sS --max-time 1800 -X POST -F "file=@$($root)\tests\fixtures\report.pdf" 'http://127.0.0.1:8000/api/index' | Out-Null
    }
}

exit $exit
