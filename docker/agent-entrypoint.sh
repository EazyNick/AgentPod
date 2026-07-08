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
#    fails the boot. Marketplace name "superpowers-dev" is declared by the repo.
mkdir -p /home/agent/.claude
if ! claude plugin list 2>/dev/null | grep -q "superpowers@superpowers-dev"; then
  claude plugin marketplace add obra/superpowers >/dev/null 2>&1 || true
  claude plugin install superpowers@superpowers-dev >/dev/null 2>&1 || true
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

# 4. Hand off to the container command (default: sleep infinity keep-alive).
exec "$@"
