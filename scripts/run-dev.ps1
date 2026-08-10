<#
.SYNOPSIS
  Starts the Lumina AI backend (FastAPI/uvicorn) and frontend (Vite) dev
  servers for local development.

.DESCRIPTION
  Automatic: run this script with no arguments and both servers come up,
  health-checked, with the frontend opened in your browser.

  Manual: each server is launched in its own new, visible PowerShell window
  (via -NoExit), so you can read live logs, Ctrl+C just one side, or copy
  the exact command it ran to start it yourself later. The commands used
  are printed below before each window opens.

  The backend ALWAYS runs on backend\.venv\Scripts\python.exe - that venv has
  the full stack (FastAPI/LangGraph and every RAG parser/OCR dependency:
  pypdf, docx, pptx, openpyxl, rapidocr_onnxruntime, fitz, pytesseract, ...).
  This script never silently falls back to the system Python or PATH: doing
  so previously caused uploads to fail at runtime with "No module named
  'pypdf'"/"No module named 'docx'" because the system interpreter doesn't
  have the RAG stack installed. If the venv is missing or incomplete, the
  script now fails loudly with the exact `pip install` command to fix it
  instead of quietly launching a broken backend.

.PARAMETER SkipBrowser
  Don't auto-open the frontend URL when both servers are healthy.
#>
param(
    [switch]$SkipBrowser
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$backendPort = 8001
$frontendPort = 5173

function Resolve-BackendPython {
    $venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        throw "backend\.venv not found at '$venvPython'. Create it and install deps:`n  cd backend; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt"
    }

    # Critical modules across the whole backend: web framework/agent stack
    # plus every RAG parser/OCR dependency. Checked as one list (not just
    # langgraph/fastapi/uvicorn) so a partially-installed venv fails loudly
    # here instead of surfacing later as a per-upload "No module named 'x'".
    $criticalModules = "langgraph", "fastapi", "uvicorn", "pypdf", "docx", "pptx", "openpyxl", "pandas", "bs4", "rapidocr_onnxruntime", "fitz", "pytesseract"
    $importExpr = ($criticalModules -join ", ")
    # Routed through cmd.exe so a failing import's stderr doesn't get
    # wrapped into a terminating NativeCommandError under $ErrorActionPreference=Stop.
    $checkOutput = cmd /c "`"$venvPython`" -c `"import $importExpr`" 2>&1"
    if ($LASTEXITCODE -ne 0) {
        throw "backend\.venv is missing required packages:`n$checkOutput`nFix with: cd backend; .venv\Scripts\pip install -r requirements.txt"
    }
    return $venvPython
}

function Stop-StaleProject($port) {
    $ownerPids = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($ownerPid in $ownerPids) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        # The backend is launched as `python -m uvicorn app.main:app`, whose
        # command line never contains the repo path (cwd isn't part of it) -
        # so match its distinctive module target too, not just the path.
        $isOurs = ($proc.CommandLine -and $proc.CommandLine.Contains($root)) -or
                  ($proc.CommandLine -like "*uvicorn*app.main:app*")
        if ($isOurs) {
            Write-Host "Stopping stale ai-chatbot process on port $port (PID $ownerPid)" -ForegroundColor Yellow
            Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
        } else {
            Write-Warning "Port $port is already held by an unrelated process (PID ${ownerPid}: $($proc.CommandLine)). Not touching it - free the port manually if startup fails."
        }
    }
}

Stop-StaleProject $backendPort
Stop-StaleProject $frontendPort
Start-Sleep -Seconds 1

$python = Resolve-BackendPython
$backendCmd = "& '$python' -m uvicorn app.main:app --host 127.0.0.1 --port $backendPort"
Write-Host "`nBackend  (window 1): cd backend; $backendCmd" -ForegroundColor Cyan
Start-Process powershell -ArgumentList @("-NoExit", "-Command", "cd '$backendDir'; $backendCmd")

$frontendCmd = "npm run dev -- --host 127.0.0.1 --port $frontendPort --strictPort"
Write-Host "Frontend (window 2): cd frontend; $frontendCmd" -ForegroundColor Cyan
Start-Process powershell -ArgumentList @("-NoExit", "-Command", "cd '$frontendDir'; $frontendCmd")

Write-Host "`nWaiting for both servers to come up..."
$backendUp = $false
$frontendUp = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if (-not $backendUp) {
        try {
            if ((Invoke-WebRequest "http://127.0.0.1:$backendPort/health" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200) {
                $backendUp = $true
                Write-Host "Backend is up  -> http://127.0.0.1:$backendPort/docs" -ForegroundColor Green
            }
        } catch {}
    }
    if (-not $frontendUp) {
        try {
            if ((Invoke-WebRequest "http://127.0.0.1:$frontendPort/" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200) {
                $frontendUp = $true
                Write-Host "Frontend is up -> http://127.0.0.1:$frontendPort" -ForegroundColor Green
            }
        } catch {}
    }
    if ($backendUp -and $frontendUp) { break }
}

if ($backendUp -and $frontendUp) {
    Write-Host "`nLumina AI is running. Use 127.0.0.1, not localhost (localhost can resolve to a different project's dev server over IPv6 on this machine)." -ForegroundColor Green
    if (-not $SkipBrowser) { Start-Process "http://127.0.0.1:$frontendPort" }
} else {
    Write-Warning "One or both servers did not come up within 60s. Check the two opened terminal windows for errors."
}
