@echo off
rem Double-click launcher: starts backend + frontend dev servers.
rem Bypasses PowerShell's default script-execution policy for this run only.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-dev.ps1" %*
