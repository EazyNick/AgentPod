#!/bin/bash
set -euo pipefail

# 1. Git bot identity (BUILD-GUIDE §4.5).
#    Shared identity comes from the read-only mounted ~/.gitconfig (set once via
#    `agentpod git-setup`; contains user + safe.directory). We NEVER write that
#    bind-mounted file here. Per-project .env overrides are applied via git env
#    vars / a container-local credentials file instead.
if [ -n "${GIT_BOT_NAME:-}" ]; then
  export GIT_AUTHOR_NAME="$GIT_BOT_NAME" GIT_COMMITTER_NAME="$GIT_BOT_NAME"
fi
if [ -n "${GIT_BOT_EMAIL:-}" ]; then
  export GIT_AUTHOR_EMAIL="$GIT_BOT_EMAIL" GIT_COMMITTER_EMAIL="$GIT_BOT_EMAIL"
fi
if [ -n "${GITHUB_TOKEN:-}" ] && [ ! -f /home/agent/.git-credentials ]; then
  printf 'https://x-access-token:%s@github.com\n' "$GITHUB_TOKEN" > /home/agent/.git-credentials
  chmod 600 /home/agent/.git-credentials || true
  export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0=store
fi
# SSH remotes (Bitbucket/GitLab/GitHub): if a bot key is mounted at ~/.ssh, use it.
if [ -f /home/agent/.ssh/id_ed25519 ]; then
  chmod 700 /home/agent/.ssh 2>/dev/null || true
  chmod 600 /home/agent/.ssh/id_ed25519 2>/dev/null || true
  export GIT_SSH_COMMAND="ssh -i /home/agent/.ssh/id_ed25519 -o IdentitiesOnly=yes -o UserKnownHostsFile=/home/agent/.ssh/known_hosts -o StrictHostKeyChecking=accept-new"
fi

# 2. Auto-inject per-container MD context into Claude's user memory (§4.11).
#    Never touches the user's repo — only ~/.claude/CLAUDE.md.
CTX="/home/agent/context/CLAUDE.md"
MEM_DIR="/home/agent/.claude"
MEM="$MEM_DIR/CLAUDE.md"
LINE="@/home/agent/context/CLAUDE.md"
if [ -f "$CTX" ]; then
  mkdir -p "$MEM_DIR"
  touch "$MEM"
  grep -qxF "$LINE" "$MEM" || echo "$LINE" >> "$MEM"
fi

# 3. Install & enable the superpowers Claude Code plugin (idempotent, best-effort).
#    ~/.claude is bind-mounted from the host, so this persists and is shared
#    across containers (like login). Public git clone — no auth needed; never
#    fails the boot. Installed from the official marketplace (not obra/superpowers'
#    own "superpowers-dev" marketplace) so agents get the same plugin shown at
#    claude-plugins-official.
mkdir -p /home/agent/.claude
if ! claude plugin list 2>/dev/null | grep -q "superpowers@claude-plugins-official"; then
  claude plugin marketplace add anthropics/claude-plugins-official >/dev/null 2>&1 || true
  claude plugin install superpowers@claude-plugins-official >/dev/null 2>&1 || true
fi
# Remove any stale install from the old obra/superpowers-dev marketplace so it
# doesn't sit alongside the official one on a shared ~/.claude bind mount.
claude plugin uninstall superpowers@superpowers-dev >/dev/null 2>&1 || true
# `plugin install` leaves the plugin DISABLED, so its skills never load. Enable
# it on EVERY boot (idempotent) — this MUST live outside the guard above: once
# installed the plugin is already listed, so that block is skipped and the
# enable would never run. Log the outcome instead of swallowing it silently.
if claude plugin enable superpowers@claude-plugins-official >/dev/null 2>&1; then
  echo "[agent] superpowers plugin enabled."
else
  echo "[agent] WARN: could not enable superpowers plugin — run 'claude plugin enable superpowers@claude-plugins-official' inside the container." >&2
fi

# 3c. Auto-approve project-scoped MCP servers (.mcp.json) for autonomous runs
#     (merge into user settings, never clobber existing keys).
python3 - <<'PY' || true
import json, os
p = os.path.expanduser("~/.claude/settings.json")
try:
    with open(p) as f:
        d = json.load(f)
except Exception:
    d = {}
d["enableAllProjectMcpServers"] = True
with open(p, "w") as f:
    json.dump(d, f, indent=2)
PY

# 3d. Install skills declared in the project manifest (agent.toml / skills.toml)
#     from the project root (= workdir). Best-effort; never fails the boot.
python3 /usr/local/bin/agent-skills.py || true

# 3e. mise: trust the project config and install project-declared tools (§4.9).
#     Global python@3.12 + node are baked in the image; this adds per-project
#     versions declared in mise.toml / .mise.toml. Best-effort.
if command -v mise >/dev/null 2>&1; then
  export MISE_TRUSTED_CONFIG_PATHS="${MISE_TRUSTED_CONFIG_PATHS:-}:$PWD"
  if [ -f mise.toml ] || [ -f .mise.toml ]; then
    mise install -y >/dev/null 2>&1 || true
  fi
fi

# 4. Hand off to the container command (default: sleep infinity keep-alive).
exec "$@"
