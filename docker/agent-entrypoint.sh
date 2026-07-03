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

# 3. Hand off to the container command (default: sleep infinity keep-alive).
exec "$@"
