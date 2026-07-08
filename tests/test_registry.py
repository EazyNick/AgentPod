import pytest

from agentpod import registry


def test_default_tool_is_claude():
    assert registry.DEFAULT_TOOL == "claude"
    assert "claude" in registry.REGISTRY


def test_claude_definition_shape():
    claude = registry.get_tool("claude")
    assert claude.name == "claude"
    assert claude.binary == "claude"
    assert "--dangerously-skip-permissions" in claude.default_flags
    assert claude.creds_container_path == "/home/agent/.claude"
    assert claude.creds_key == "claude"
    assert claude.uses_claude_json is True


def test_codex_and_opencode_registered():
    codex = registry.get_tool("codex")
    assert codex.binary == "codex"
    assert "--dangerously-bypass-approvals-and-sandbox" in codex.default_flags
    assert codex.creds_container_path == "/home/agent/.codex"
    assert codex.uses_claude_json is False

    oc = registry.get_tool("opencode")
    assert oc.binary == "opencode"
    assert oc.creds_key == "opencode"


def test_get_tool_unknown_raises():
    with pytest.raises(KeyError):
        registry.get_tool("nope")


def test_definition_is_frozen():
    claude = registry.get_tool("claude")
    with pytest.raises(Exception):
        claude.name = "x"  # frozen dataclass
