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


def profiles_dir() -> Path:
    return agent_root() / "profiles"


def _base(profile: str | None) -> Path:
    """Credential root: ~/.agent, or ~/.agent/profiles/<profile> when set (§4.4)."""
    return profiles_dir() / profile if profile else agent_root()


def tool_creds_dir(tool: str, profile: str | None = None) -> Path:
    """Host credential store for a tool (profile-aware). e.g. ~/.agent/claude."""
    return _base(profile) / tool


def claude_creds_dir(profile: str | None = None) -> Path:
    return tool_creds_dir("claude", profile)


def claude_json_path(profile: str | None = None) -> Path:
    return _base(profile) / "claude.json"


def contexts_dir() -> Path:
    return agent_root() / "contexts"


def context_dir(project_id: str) -> Path:
    return contexts_dir() / project_id


def locks_dir() -> Path:
    return agent_root() / "locks"


def gitconfig_path() -> Path:
    """Shared bot git config, mounted into every container (BUILD-GUIDE §4.5)."""
    return agent_root() / "gitconfig"


def git_credentials_path() -> Path:
    """Shared bot push/pull credentials (token). Present only after git-setup."""
    return agent_root() / "git-credentials"


def ssh_dir() -> Path:
    """Shared bot SSH keys (deploy key / account key). Mounted to ~/.ssh."""
    return agent_root() / "ssh"


def ensure_layout() -> None:
    """Create the data layout. Idempotent; never clobbers existing files."""
    for d in (claude_creds_dir(), contexts_dir(), locks_dir()):
        d.mkdir(parents=True, exist_ok=True)
    cj = claude_json_path()
    if not cj.exists():
        cj.write_text("{}\n")
    gc = gitconfig_path()
    if not gc.exists() or not gc.read_text().strip():
        # Default (pre git-setup): just safe.directory. The entrypoint never
        # rewrites this file (it's bind-mounted read-only), so it must be valid.
        gc.write_text("[safe]\n\tdirectory = *\n")
