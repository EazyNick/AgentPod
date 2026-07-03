"""Host-side ~/.agent data layout (BUILD-GUIDE §3.1)."""
from __future__ import annotations

import os
from pathlib import Path


def agent_root() -> Path:
    env = os.environ.get("AGENT_HOME")
    if env:
        return Path(env)
    home = os.environ.get("HOME")
    if home:
        return Path(home) / ".agent"
    return Path.home() / ".agent"


def claude_creds_dir() -> Path:
    return agent_root() / "claude"


def claude_json_path() -> Path:
    return agent_root() / "claude.json"


def contexts_dir() -> Path:
    return agent_root() / "contexts"


def context_dir(project_id: str) -> Path:
    return contexts_dir() / project_id


def locks_dir() -> Path:
    return agent_root() / "locks"


def ensure_layout() -> None:
    """Create the data layout. Idempotent; never clobbers existing files."""
    for d in (claude_creds_dir(), contexts_dir(), locks_dir()):
        d.mkdir(parents=True, exist_ok=True)
    cj = claude_json_path()
    if not cj.exists():
        cj.write_text("{}\n")
