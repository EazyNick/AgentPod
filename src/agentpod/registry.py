"""Multi-tool registry (BUILD-GUIDE §4.10). Phase 1 ships only claude."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import paths


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    binary: str
    default_flags: list[str]
    install_command: list[str]
    update_command: list[str]
    credential_mounts: list[tuple[str, str]] = field(default_factory=list)


def _claude() -> ToolDefinition:
    return ToolDefinition(
        name="claude",
        binary="claude",
        default_flags=["--dangerously-skip-permissions"],
        install_command=["npm", "install", "-g", "@anthropic-ai/claude-code"],
        update_command=["npm", "update", "-g", "@anthropic-ai/claude-code"],
        credential_mounts=[(str(paths.claude_creds_dir()), "/home/agent/.claude")],
    )


REGISTRY: dict[str, ToolDefinition] = {"claude": _claude()}
DEFAULT_TOOL = "claude"


def get_tool(name: str) -> ToolDefinition:
    return REGISTRY[name]
