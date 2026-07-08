"""Multi-tool registry (BUILD-GUIDE §4.10) — claude / codex / opencode.

Each tool's differences (binary, autonomy flag, install/update, credential
store) live here as data; the rest of the code doesn't branch on tool type.
Adding a tool = one entry. Credential host paths are resolved at mount time
from `creds_key` (tool-scoped, profile-aware) — see cli.build_mounts.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    binary: str
    default_flags: list[str]           # autonomy flags (applied ONLY in-container)
    install_command: list[str]
    update_command: list[str]
    creds_container_path: str          # e.g. "/home/agent/.claude"
    creds_key: str                     # host store name under ~/.agent[/profiles/<p>]
    uses_claude_json: bool = False     # claude-only onboarding file


REGISTRY: dict[str, ToolDefinition] = {
    "claude": ToolDefinition(
        name="claude",
        binary="claude",
        default_flags=["--dangerously-skip-permissions"],
        install_command=["npm", "install", "-g", "@anthropic-ai/claude-code"],
        update_command=["npm", "update", "-g", "@anthropic-ai/claude-code"],
        creds_container_path="/home/agent/.claude",
        creds_key="claude",
        uses_claude_json=True,
    ),
    "codex": ToolDefinition(
        name="codex",
        binary="codex",
        default_flags=["--dangerously-bypass-approvals-and-sandbox"],
        install_command=["npm", "install", "-g", "@openai/codex"],
        update_command=["npm", "update", "-g", "@openai/codex"],
        creds_container_path="/home/agent/.codex",
        creds_key="codex",
    ),
    "opencode": ToolDefinition(
        name="opencode",
        binary="opencode",
        default_flags=[],
        install_command=["npm", "install", "-g", "opencode-ai"],
        update_command=["npm", "update", "-g", "opencode-ai"],
        creds_container_path="/home/agent/.local/share/opencode",
        creds_key="opencode",
    ),
}
DEFAULT_TOOL = "claude"


def get_tool(name: str) -> ToolDefinition:
    return REGISTRY[name]
