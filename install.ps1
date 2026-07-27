<#
AgentPod one-command installer for native Windows (PowerShell 5.1+).

    .\install.ps1              # deps + agentpod CLI + build the image
    .\install.ps1 -NoBuild     # skip the image build (build later with: agentpod build)

Installs the `agentpod` CLI into a dedicated venv, puts it on PATH (this
session and future ones), and builds the agent image. Idempotent -- safe to
re-run.
#>

param(
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"

function Log($msg)  { Write-Host "[agentpod] $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "[agentpod] $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "[agentpod] $msg" -ForegroundColor Red }

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoDir

# --- 1. Docker ----------------------------------------------------------------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Err "Docker not found. Install Docker Desktop (https://www.docker.com/products/docker-desktop/), start it, then re-run."
    exit 1
}
$dockerUp = $true
try { docker info *>$null } catch { $dockerUp = $false }
if ($LASTEXITCODE -ne 0) { $dockerUp = $false }
if (-not $dockerUp) { Warn "Docker daemon not reachable yet (start Docker Desktop to build/run)." }

# --- 2. Python version gate (>=3.10) -------------------------------------------
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Err "Python not found. Install Python 3.10+ from https://www.python.org/downloads/ (check 'Add python.exe to PATH'), then re-run."
    exit 1
}
python -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    Err "Python 3.10+ required; found $(python -V 2>&1). Install a newer Python and re-run."
    exit 1
}
Log "python = $(python -V 2>&1)"

# --- 3. Install the agentpod CLI into a dedicated venv -------------------------
$VenvDir = Join-Path $env:USERPROFILE ".venvs\agentpod"
$ScriptsDir = Join-Path $VenvDir "Scripts"
$AgentpodExe = Join-Path $ScriptsDir "agentpod.exe"

if (-not (Test-Path $VenvDir)) {
    Log "Creating venv at $VenvDir ..."
    python -m venv $VenvDir
}
Log "Installing agentpod (editable) ..."
$VenvPython = Join-Path $ScriptsDir "python.exe"
# `pip.exe install --upgrade pip` fails on Windows (can't replace its own running
# exe) -- `python -m pip` avoids that by not locking pip.exe itself.
& $VenvPython -m pip install -q --upgrade pip
& $VenvPython -m pip install -q -e .

# --- 4. Put agentpod on PATH (this window AND future ones) --------------------
if ($env:PATH -notlike "*$ScriptsDir*") { $env:PATH = "$ScriptsDir;$env:PATH" }
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($null -eq $userPath) { $userPath = "" }
if ($userPath -notlike "*$ScriptsDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$ScriptsDir;$userPath", "User")
    Log "Added $ScriptsDir to your user PATH (new terminal windows will see it automatically)."
}

# --- 5. Build the agent image ---------------------------------------------------
if (-not $NoBuild) {
    if ($dockerUp) {
        Log "Building the agent image (first build pulls Ubuntu/Node/Chromium - a few minutes)..."
        & $AgentpodExe build
    } else {
        Warn "Skipping build: Docker daemon not running. Run 'agentpod build' once it's up."
    }
}

# --- 6. Done ----------------------------------------------------------------------
Log "Installed. 'agentpod' is ready to use right now (this window included)."
Log "Next:"
Log "  1) authenticate Claude once - put ANTHROPIC_API_KEY in your project's .env,"
Log "     or run 'agentpod shell' then 'claude login'."
Log "  2) cd <your-project> ; agentpod run"
Log "  - or just double-click agentpod-menu.bat for a folder-picker menu."
