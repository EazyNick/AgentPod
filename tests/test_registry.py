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
    assert claude.credential_mounts  # non-empty
    host, container = claude.credential_mounts[0]
    assert container == "/home/agent/.claude"


def test_get_tool_unknown_raises():
    with pytest.raises(KeyError):
        registry.get_tool("nope")


def test_definition_is_frozen():
    claude = registry.get_tool("claude")
    with pytest.raises(Exception):
        claude.name = "x"  # frozen dataclass
