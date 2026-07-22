import os

from agentpod import cli
from agentpod.docker_ctl import Mount


def test_resolve_target_cwd(monkeypatch, tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    monkeypatch.chdir(d)
    from agentpod import naming

    pid, cname = cli.resolve_target(".")
    assert pid == naming.project_id(str(d))
    assert cname == f"agent-{pid}"


def test_build_mounts_includes_core_and_context(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths

    paths.ensure_layout()
    project_path = str(tmp_path / "repo")
    # create a context dir for this project id
    pid = "repo-abc"
    (tmp_path / "root" / "contexts" / pid).mkdir(parents=True)

    mounts = cli.build_mounts(pid, project_path)
    containers = {m.container for m in mounts}
    assert f"/project/{pid}" in containers
    assert "/home/agent/.claude" in containers
    assert "/home/agent/.claude.json" in containers
    assert "/home/agent/context" in containers
    # context mount is read-only
    ctx = next(m for m in mounts if m.container == "/home/agent/context")
    assert ctx.ro is True


def test_build_mounts_omits_context_when_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths

    paths.ensure_layout()
    mounts = cli.build_mounts("repo-none", str(tmp_path / "repo"))
    assert all(m.container != "/home/agent/context" for m in mounts)


def test_build_mounts_gitconfig_always_credentials_when_present(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths

    paths.ensure_layout()
    mounts = cli.build_mounts("repo-x", str(tmp_path / "repo"))
    containers = {m.container for m in mounts}
    assert "/home/agent/.gitconfig" in containers          # always shared
    assert "/home/agent/.git-credentials" not in containers  # not set yet

    paths.git_credentials_path().write_text("https://x-access-token:t@github.com\n")
    containers2 = {m.container for m in cli.build_mounts("repo-x", str(tmp_path / "repo"))}
    assert "/home/agent/.git-credentials" in containers2


def test_build_mounts_ssh_when_dir_present(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths

    paths.ensure_layout()
    assert all(m.container != "/home/agent/.ssh" for m in cli.build_mounts("r", str(tmp_path / "repo")))
    paths.ssh_dir().mkdir(parents=True)
    mounts = cli.build_mounts("r", str(tmp_path / "repo"))
    ssh = next(m for m in mounts if m.container == "/home/agent/.ssh")
    assert ssh.ro is False  # rw so ssh can update known_hosts


def test_render_gitconfig():
    out = cli.render_gitconfig("agent-bot", "bot@users.noreply.github.com", False)
    assert "name = agent-bot" in out
    assert "email = bot@users.noreply.github.com" in out
    assert "directory = *" in out
    assert "helper = store" not in out
    assert "helper = store" in cli.render_gitconfig("b", "e", True)


def test_build_mounts_codex_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths

    paths.ensure_layout()
    conts = {m.container for m in cli.build_mounts("r", str(tmp_path / "repo"), tool="codex")}
    assert "/home/agent/.codex" in conts
    assert "/home/agent/.claude" not in conts       # codex, not claude
    assert "/home/agent/.claude.json" not in conts  # codex has no claude.json


def test_setup_ssh_generates_key_and_known_hosts(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths
    import subprocess as sp

    def fake_run(args, **kw):
        if args[0] == "ssh-keygen":
            f = args[args.index("-f") + 1]
            open(f, "w").write("PRIV")
            open(f + ".pub", "w").write("ssh-ed25519 AAAA agentpod-bot\n")
            return sp.CompletedProcess(args, 0, "", "")
        if args[0] == "ssh-keyscan":
            return sp.CompletedProcess(args, 0, "bitbucket.org ssh-ed25519 AAAA\n", "")
        return sp.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    cli._setup_ssh("bitbucket.org")
    assert (paths.ssh_dir() / "id_ed25519").exists()
    assert "bitbucket.org" in (paths.ssh_dir() / "known_hosts").read_text()


def test_build_mounts_profile_changes_creds_host(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths

    paths.ensure_layout()
    mounts = cli.build_mounts("r", str(tmp_path / "repo"), tool="claude", profile="bot")
    creds = next(m for m in mounts if m.container == "/home/agent/.claude")
    assert "profiles" in creds.host and creds.host.endswith("claude")
    cj = next(m for m in mounts if m.container == "/home/agent/.claude.json")
    assert "profiles" in cj.host


def test_creds_profile_defaults_to_project_id():
    assert cli.creds_profile(None, "jira-abc123") == "jira-abc123"
    assert cli.creds_profile("bot", "jira-abc123") == "bot"


def test_build_mounts_default_isolates_plugins_but_shares_login(monkeypatch, tmp_path):
    """No --profile: plugin/skill state is auto-isolated per project (keyed by
    project_id), but login (.claude.json) stays on the shared root."""
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths

    paths.ensure_layout()
    mounts = cli.build_mounts("jira-abc123", str(tmp_path / "repo"), tool="claude")
    creds = next(m for m in mounts if m.container == "/home/agent/.claude")
    assert creds.host == str(paths.claude_creds_dir("jira-abc123"))
    cj = next(m for m in mounts if m.container == "/home/agent/.claude.json")
    assert cj.host == str(paths.claude_json_path())  # shared root, no profile

    # A different project gets a different, isolated creds dir.
    other = cli.build_mounts("n8n-def456", str(tmp_path / "repo2"), tool="claude")
    other_creds = next(m for m in other if m.container == "/home/agent/.claude")
    assert other_creds.host != creds.host


def test_build_mounts_default_isolates_codex_creds_too(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths

    paths.ensure_layout()
    mounts = cli.build_mounts("jira-abc123", str(tmp_path / "repo"), tool="codex")
    creds = next(m for m in mounts if m.container == "/home/agent/.codex")
    assert creds.host == str(paths.tool_creds_dir("codex", "jira-abc123"))


def test_export_writes_skills_and_mcp_for_the_current_project(monkeypatch, tmp_path):
    import json

    from agentpod import naming, paths

    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    paths.ensure_layout()

    project_path = tmp_path / "repo"
    project_path.mkdir()
    monkeypatch.chdir(project_path)
    pid = naming.project_id(str(project_path))

    creds = paths.claude_creds_dir(pid)
    (creds / "plugins").mkdir(parents=True)
    (creds / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"my-tool@my-market": [{}]}})
    )
    (creds / "settings.json").write_text(json.dumps({"enabledPlugins": {"my-tool@my-market": True}}))
    (creds / "plugins" / "known_marketplaces.json").write_text(
        json.dumps({"my-market": {"source": {"source": "github", "repo": "acme/my-tool"}}})
    )

    cj = paths.claude_json_path()
    cj.write_text(
        json.dumps(
            {"projects": {f"/project/{pid}": {"mcpServers": {"foo": {"command": "npx", "env": {"KEY": "s3cr3t"}}}}}}
        )
    )

    cli.export(target=".", profile=None)

    manifest = (project_path / "agent.toml").read_text()
    assert 'name = "my-tool"' in manifest
    mcp = json.loads((project_path / ".mcp.json").read_text())
    assert mcp["mcpServers"]["foo"]["env"]["KEY"] == "${FOO_KEY}"
    assert "s3cr3t" not in (project_path / ".mcp.json").read_text()
    assert "FOO_KEY=s3cr3t" in (project_path / ".env").read_text()
