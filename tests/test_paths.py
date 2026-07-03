from pathlib import Path

from agentpod import paths


def test_agent_root_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "custom"))
    assert paths.agent_root() == tmp_path / "custom"


def test_agent_root_defaults_to_home(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.agent_root() == tmp_path / ".agent"


def test_ensure_layout_creates_dirs_and_claude_json(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    paths.ensure_layout()
    assert paths.claude_creds_dir().is_dir()
    assert paths.contexts_dir().is_dir()
    assert paths.locks_dir().is_dir()
    assert paths.claude_json_path().is_file()


def test_ensure_layout_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    paths.ensure_layout()
    paths.claude_json_path().write_text('{"k": 1}')
    paths.ensure_layout()  # must not clobber existing content
    assert paths.claude_json_path().read_text() == '{"k": 1}'


def test_context_dir_matches_project_id(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    assert paths.context_dir("myrepo-abc") == tmp_path / "root" / "contexts" / "myrepo-abc"
