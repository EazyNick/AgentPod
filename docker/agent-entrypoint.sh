#!/bin/bash
set -euo pipefail

# 1. Git: allow operating on the bind-mounted project regardless of owner.
#    (Dedicated bot identity is Phase 2.)
git config --global --add safe.directory '*' || true

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
#    across containers (like login). Requires network; never fails the boot.
CLAUDE_DIR="/home/agent/.claude"
mkdir -p "$CLAUDE_DIR"
# 3a. Enable it in user settings (merge, never clobber existing settings).
python3 - <<'PY' || true
import json, os
p = os.path.expanduser("~/.claude/settings.json")
try:
    with open(p) as f:
        d = json.load(f)
except Exception:
    d = {}
d.setdefault("enabledPlugins", {})["superpowers@claude-plugins-official"] = True
with open(p, "w") as f:
    json.dump(d, f, indent=2)
PY
# 3b. Fetch/install it if not present yet (official marketplace is built-in).
if ! claude plugin list 2>/dev/null | grep -q "superpowers"; then
  claude plugin install superpowers@claude-plugins-official 2>/dev/null || true
fi

# 4. Hand off to the container command (default: sleep infinity keep-alive).
exec "$@"
