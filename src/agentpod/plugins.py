"""Host-side one-time seed of the superpowers Claude Code plugin (BUILD-GUIDE §4.x).

Agent containers share a per-profile creds directory (paths.claude_creds_dir)
that's bind-mounted onto /home/agent/.claude, so whatever plugin state lives
there is available to every container for that profile. Previously that state
only got populated by agent-entrypoint.sh cloning the marketplace at container
boot -- meaning the first agent to boot for a fresh profile always paid for a
live git clone.

This seeds the shared directory once, using the HOST's own `claude` CLI, before
any container ever mounts it -- so in the common case no container has to clone
anything at boot; the entrypoint's install guard just finds it already there.
Best-effort and silent: if `claude` isn't on the host PATH, or the install
fails, we simply fall back to the existing runtime install in
agent-entrypoint.sh. Never blocks or fails `agentpod run`/`shell`/`build`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

MARKETPLACE = "claude-plugins-official"
MARKETPLACE_SOURCE = "anthropics/claude-plugins-official"
PLUGIN = f"superpowers@{MARKETPLACE}"


def seed_superpowers(creds_dir: Path) -> None:
    """Install+enable superpowers into creds_dir if not already there (best-effort)."""
    if (creds_dir / "plugins" / "marketplaces" / MARKETPLACE).is_dir():
        return
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return
    creds_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(creds_dir)}
    for args in (
        ["plugin", "marketplace", "add", MARKETPLACE_SOURCE],
        ["plugin", "install", PLUGIN],
        ["plugin", "enable", PLUGIN],
    ):
        try:
            subprocess.run(
                [claude_bin, *args],
                env=env,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except Exception:  # noqa: BLE001 - best-effort, never block the CLI
            return
    # CLAUDE_CONFIG_DIR also writes a top-level .claude.json/backups here, which
    # isn't meaningful in this spot (the container mounts .claude.json
    # separately) -- drop it so the seeded dir only holds real .claude state.
    for stray in (".claude.json", ".claude.json.lock", "backups"):
        p = creds_dir / stray
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink(missing_ok=True)
