#!/usr/bin/env bash
# AgentPod one-command installer for Linux / WSL2 / Raspberry Pi OS.
#
#   ./install.sh              # deps + agentpod CLI + build the image
#   ./install.sh --no-build   # skip the image build (build later with: agentpod build)
#
# Installs system packages (python3/venv/pip/pipx), installs the `agentpod`
# command on your PATH, and builds the agent image. Idempotent — safe to re-run.
set -euo pipefail

log()  { printf '\033[1;34m[agentpod]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[agentpod]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[agentpod]\033[0m %s\n' "$*" >&2; }

BUILD=1
[ "${1:-}" = "--no-build" ] && BUILD=0

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

# --- 1. Docker ---------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  err "Docker not found. Install Docker + start the daemon, then re-run."
  err "  WSL2: enable Docker Desktop 'WSL Integration' for this distro."
  exit 1
fi
DOCKER_UP=1
docker info >/dev/null 2>&1 || { DOCKER_UP=0; warn "Docker daemon not reachable yet (start Docker to build/run)."; }

# --- 2. System packages (Debian/Ubuntu/Raspberry Pi OS) ----------------------
if command -v apt-get >/dev/null 2>&1; then
  log "Installing system packages (python3, venv, pip, pipx)…"
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-venv python3-pip
  sudo apt-get install -y pipx || true   # older distros may lack the pipx package
else
  warn "Non-apt system: ensure python3 (>=3.10), pip, and venv are installed."
fi

# --- 3. Python version gate (>=3.10) -----------------------------------------
if ! python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)
PY
then
  err "Python 3.10+ required; found $(python3 -V 2>&1). Install a newer python3 and re-run."
  exit 1
fi
log "python3 = $(python3 -V 2>&1 | awk '{print $2}')"

# --- 4. Install the agentpod CLI on PATH (isolated) --------------------------
AGENTPOD_BIN=""
if command -v pipx >/dev/null 2>&1; then
  log "Installing agentpod via pipx…"
  pipx install --force .
  pipx ensurepath >/dev/null 2>&1 || true
  AGENTPOD_BIN="$HOME/.local/bin/agentpod"
else
  log "pipx unavailable — using a venv + symlink…"
  python3 -m venv "$HOME/.venvs/agentpod"
  "$HOME/.venvs/agentpod/bin/pip" install -q --upgrade pip
  "$HOME/.venvs/agentpod/bin/pip" install -q -e .
  mkdir -p "$HOME/.local/bin"
  ln -sf "$HOME/.venvs/agentpod/bin/agentpod" "$HOME/.local/bin/agentpod"
  AGENTPOD_BIN="$HOME/.local/bin/agentpod"
fi

# --- 5. Build the agent image ------------------------------------------------
if [ "$BUILD" = "1" ]; then
  if [ "$DOCKER_UP" = "1" ]; then
    log "Building the agent image (first build pulls Ubuntu/Node/Chromium — a few minutes)…"
    "$AGENTPOD_BIN" build
  else
    warn "Skipping build: Docker daemon not running. Run 'agentpod build' once it's up."
  fi
fi

# --- 6. Done -----------------------------------------------------------------
log "Installed. If 'agentpod' isn't found in THIS shell, open a new terminal (or: source ~/.bashrc)."
log "Next:"
log "  1) authenticate Claude once — put ANTHROPIC_API_KEY in your project's .env,"
log "     or run 'agentpod shell' then 'claude login'."
log "  2) cd <your-project> && agentpod run"
