<#
.SYNOPSIS
  Stops the AI Chatbot backend and frontend dev servers started by run-dev.ps1.
  Only touches processes whose command line resolves inside this repo -
  it will not kill unrelated services that happen to share a port.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

foreach ($port in @(8001, 5173)) {
    $ownerPids = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($ownerPid in $ownerPids) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue
        $isOurs = $proc -and $proc.CommandLine -and (
            $proc.CommandLine.Contains($root) -or $proc.CommandLine -like "*uvicorn*app.main:app*"
        )
        if ($isOurs) {
            Write-Host "Stopping PID $ownerPid on port $port" -ForegroundColor Yellow
            Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
        }
    }
}
Write-Host "Done." -ForegroundColor Green
