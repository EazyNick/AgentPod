@echo off
rem AgentPod one-command installer for native Windows.
rem Double-click this file, or run it from a terminal: install.bat [--no-build]
rem Thin wrapper around install.ps1 (PowerShell has better error handling / venv setup).

chcp 65001 >nul
set "NOBUILD_FLAG="
if /I "%~1"=="--no-build" set "NOBUILD_FLAG=-NoBuild"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %NOBUILD_FLAG%
if errorlevel 1 (
    echo.
    echo [agentpod] Install failed - see the messages above.
    pause
    exit /b 1
)

echo.
pause
