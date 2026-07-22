"""Tests for the host-side superpowers plugin seeding (src/agentpod/plugins.py)."""
import json

from agentpod import plugins


def test_seed_skips_when_already_present(tmp_path, monkeypatch):
    marker = tmp_path / "plugins" / "marketplaces" / plugins.MARKETPLACE
    marker.mkdir(parents=True)

    def fail_which(_name):
        raise AssertionError("should not check for claude binary when already seeded")

    monkeypatch.setattr(plugins.shutil, "which", fail_which)
    plugins.seed_superpowers(tmp_path)  # must not raise


def test_seed_skips_when_claude_not_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(plugins.shutil, "which", lambda _name: None)

    def fail_run(*a, **k):
        raise AssertionError("should not invoke subprocess without a claude binary")

    monkeypatch.setattr(plugins.subprocess, "run", fail_run)
    plugins.seed_superpowers(tmp_path)  # must not raise
    assert not (tmp_path / "plugins").exists()


def test_seed_runs_add_install_enable_and_cleans_stray_files(tmp_path, monkeypatch):
    monkeypatch.setattr(plugins.shutil, "which", lambda _name: "/usr/bin/claude")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1:4] == ["plugin", "marketplace", "add"]:
            (tmp_path / "plugins" / "marketplaces" / plugins.MARKETPLACE).mkdir(parents=True)
            (tmp_path / ".claude.json").write_text("{}")
            (tmp_path / "backups").mkdir()
        return None

    monkeypatch.setattr(plugins.subprocess, "run", fake_run)
    plugins.seed_superpowers(tmp_path)

    assert [c[1:] for c in calls] == [
        ["plugin", "marketplace", "add", plugins.MARKETPLACE_SOURCE],
        ["plugin", "install", plugins.PLUGIN],
        ["plugin", "enable", plugins.PLUGIN],
    ]
    assert not (tmp_path / ".claude.json").exists()
    assert not (tmp_path / "backups").exists()
    assert (tmp_path / "plugins" / "marketplaces" / plugins.MARKETPLACE).is_dir()


def test_seed_stops_early_if_a_step_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(plugins.shutil, "which", lambda _name: "/usr/bin/claude")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        raise RuntimeError("boom")

    monkeypatch.setattr(plugins.subprocess, "run", fake_run)
    plugins.seed_superpowers(tmp_path)  # must not raise
    assert len(calls) == 1


def _write_installed_plugins(creds_dir, entries):
    (creds_dir / "plugins").mkdir(parents=True, exist_ok=True)
    (creds_dir / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": {k: [{}] for k in entries}})
    )


def _write_settings(creds_dir, enabled: dict):
    (creds_dir / "settings.json").write_text(json.dumps({"enabledPlugins": enabled}))


def _write_known_marketplaces(creds_dir, marketplaces: dict):
    (creds_dir / "plugins" / "known_marketplaces.json").write_text(json.dumps(marketplaces))


def test_export_skills_excludes_baseline_and_disabled(tmp_path):
    creds = tmp_path / "creds"
    _write_installed_plugins(
        creds,
        {
            "superpowers@claude-plugins-official": None,
            "my-tool@my-market": None,
            "off-tool@my-market": None,
        },
    )
    _write_settings(
        creds,
        {
            "superpowers@claude-plugins-official": True,
            "my-tool@my-market": True,
            "off-tool@my-market": False,
        },
    )
    _write_known_marketplaces(creds, {"my-market": {"source": {"source": "github", "repo": "acme/my-tool"}}})

    manifest = tmp_path / "agent.toml"
    added = plugins.export_skills(creds, manifest)

    assert added == ["my-tool"]
    text = manifest.read_text()
    assert 'name = "my-tool"' in text
    assert 'source = "github:acme/my-tool"' in text
    assert 'marketplace_name = "my-market"' in text
    assert "superpowers" not in text
    assert "off-tool" not in text


def test_export_skills_is_idempotent(tmp_path):
    creds = tmp_path / "creds"
    _write_installed_plugins(creds, {"my-tool@my-market": None})
    _write_settings(creds, {"my-tool@my-market": True})
    _write_known_marketplaces(creds, {})

    manifest = tmp_path / "agent.toml"
    assert plugins.export_skills(creds, manifest) == ["my-tool"]
    assert plugins.export_skills(creds, manifest) == []  # already declared now
    assert manifest.read_text().count('name = "my-tool"') == 1


def test_export_mcp_servers_externalizes_secrets_to_env(tmp_path):
    claude_json = tmp_path / "claude.json"
    claude_json.write_text(
        json.dumps(
            {
                "projects": {
                    "/project/jira-abc": {
                        "mcpServers": {
                            "jira-mcp": {
                                "command": "npx",
                                "args": ["-y", "jira-mcp"],
                                "env": {"API_KEY": "super-secret-token"},
                            }
                        }
                    }
                }
            }
        )
    )
    project_path = tmp_path / "repo"
    project_path.mkdir()

    added = plugins.export_mcp_servers(claude_json, "/project/jira-abc", project_path)

    assert added == ["jira-mcp"]
    mcp_json = json.loads((project_path / ".mcp.json").read_text())
    assert mcp_json["mcpServers"]["jira-mcp"]["env"]["API_KEY"] == "${JIRA_MCP_API_KEY}"
    assert "super-secret-token" not in (project_path / ".mcp.json").read_text()
    env_text = (project_path / ".env").read_text()
    assert "JIRA_MCP_API_KEY=super-secret-token" in env_text


def test_export_mcp_servers_skips_already_declared(tmp_path):
    claude_json = tmp_path / "claude.json"
    claude_json.write_text(
        json.dumps({"projects": {"/project/x": {"mcpServers": {"foo": {"command": "npx"}}}}})
    )
    project_path = tmp_path / "repo"
    project_path.mkdir()
    (project_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"foo": {"command": "existing"}}}))

    added = plugins.export_mcp_servers(claude_json, "/project/x", project_path)

    assert added == []
    mcp_json = json.loads((project_path / ".mcp.json").read_text())
    assert mcp_json["mcpServers"]["foo"]["command"] == "existing"  # untouched


def test_export_mcp_servers_no_servers_is_noop(tmp_path):
    claude_json = tmp_path / "claude.json"
    claude_json.write_text(json.dumps({"projects": {}}))
    project_path = tmp_path / "repo"
    project_path.mkdir()

    assert plugins.export_mcp_servers(claude_json, "/project/x", project_path) == []
    assert not (project_path / ".mcp.json").exists()
