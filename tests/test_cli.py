import os
from pathlib import Path

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


def test_list_agent_folders_sorted(tmp_path):
    (tmp_path / "agents" / "n8n").mkdir(parents=True)
    (tmp_path / "agents" / "jira").mkdir(parents=True)
    (tmp_path / "agents" / "verify").mkdir(parents=True)
    (tmp_path / "agents" / "not_a_dir.txt").write_text("x")

    names = [p.name for p in cli._list_agent_folders(tmp_path / "agents")]
    assert names == ["jira", "n8n", "verify"]


def test_list_agent_folders_empty_when_dir_missing(tmp_path):
    assert cli._list_agent_folders(tmp_path / "agents") == []


def test_resolve_agents_dir_prefers_base_slash_agents(tmp_path):
    (tmp_path / "agents").mkdir()
    assert cli._resolve_agents_dir(tmp_path) == tmp_path / "agents"


def test_resolve_agents_dir_falls_back_to_base_itself_when_already_agents(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "jira").mkdir()
    # cd'd straight into agents\ -- there's no agents\agents, so use agents_dir itself.
    assert cli._resolve_agents_dir(agents_dir) == agents_dir


def test_resolve_agents_dir_neither_exists_returns_base_slash_agents(tmp_path):
    other = tmp_path / "not-agents"
    other.mkdir()
    assert cli._resolve_agents_dir(other) == other / "agents"


def test_interactive_menu_lists_folders_when_run_from_inside_agents(monkeypatch, tmp_path):
    agents_dir = tmp_path / "agents"
    (agents_dir / "jira").mkdir(parents=True)
    (agents_dir / "n8n").mkdir(parents=True)
    monkeypatch.chdir(agents_dir)  # simulate `cd agents && agentpod`

    seen = []
    monkeypatch.setattr(cli.typer, "echo", lambda msg="": seen.append(str(msg)))
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: "Q")

    cli._interactive_menu()

    joined = "\n".join(seen)
    assert "jira" in joined and "n8n" in joined
    assert "아래에 폴더가 없습니다" not in joined


def test_interactive_menu_quits_immediately(monkeypatch, tmp_path):
    (tmp_path / "agents" / "jira").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: "Q")
    cli._interactive_menu()  # must not raise / not touch docker


def test_interactive_menu_invalid_choice_then_quit(monkeypatch, tmp_path):
    (tmp_path / "agents" / "jira").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    responses = iter(["9", "Q"])  # 9 is out of range
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: next(responses))
    cli._interactive_menu()


def test_interactive_menu_selects_folder_and_backs_out(monkeypatch, tmp_path):
    (tmp_path / "agents" / "jira").mkdir(parents=True)
    (tmp_path / "agents" / "n8n").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    responses = iter(["1", "B", "Q"])
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: next(responses))
    cli._interactive_menu()
    assert Path.cwd() == tmp_path  # cwd restored after visiting the sub-menu


def test_interactive_menu_custom_path(monkeypatch, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(tmp_path)
    responses = iter(["P", str(other), "B", "Q"])
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: next(responses))
    cli._interactive_menu()


def test_agent_action_menu_run_invokes_run_in_target_dir(monkeypatch, tmp_path):
    target = tmp_path / "agents" / "jira"
    target.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    calls = []

    def fake_run(**kwargs):
        calls.append((Path.cwd(), kwargs))

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: "R")

    cli._agent_action_menu(target)

    assert len(calls) == 1
    assert calls[0][0] == target
    assert Path.cwd() == tmp_path  # cwd restored after run() returns


def test_agent_action_menu_shell_invokes_shell(monkeypatch, tmp_path):
    target = tmp_path / "agents" / "jira"
    target.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    calls = []
    monkeypatch.setattr(cli, "shell", lambda **kw: calls.append(kw))
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: "S")

    cli._agent_action_menu(target)
    assert len(calls) == 1


def test_agent_action_menu_export_loops_back(monkeypatch, tmp_path):
    target = tmp_path / "agents" / "jira"
    target.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    export_calls = []
    monkeypatch.setattr(cli, "export", lambda **kw: export_calls.append(kw))
    responses = iter(["E", "", "B"])
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: next(responses))

    cli._agent_action_menu(target)
    assert len(export_calls) == 1
    assert Path.cwd() == tmp_path


def test_agent_action_menu_back_does_nothing(monkeypatch, tmp_path):
    target = tmp_path / "agents" / "jira"
    target.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    for name in ("run", "shell", "export"):
        monkeypatch.setattr(
            cli, name, lambda **kw: (_ for _ in ()).throw(AssertionError(f"{name} should not be called"))
        )
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: "B")

    cli._agent_action_menu(target)


def test_skillset_root_finds_repo_agents_dir():
    root = cli._skillset_root()
    assert root is not None
    assert root.name == "agents"
    assert root.is_dir()


def test_resolve_skillset_none_when_not_given():
    assert cli._resolve_skillset(None) is None
    assert cli._resolve_skillset("") is None


def test_resolve_skillset_accepts_literal_path(tmp_path):
    preset = tmp_path / "my-preset"
    preset.mkdir()
    assert cli._resolve_skillset(str(preset)) == preset.resolve()


def test_resolve_skillset_resolves_name_under_skillset_root(monkeypatch, tmp_path):
    root = tmp_path / "agents"
    (root / "n8n").mkdir(parents=True)
    monkeypatch.setattr(cli, "_skillset_root", lambda: root)
    assert cli._resolve_skillset("n8n") == root / "n8n"


def test_resolve_skillset_fails_when_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_skillset_root", lambda: tmp_path / "agents")
    try:
        cli._resolve_skillset("does-not-exist")
        raise AssertionError("expected typer.Exit")
    except cli.typer.Exit:
        pass


def test_skillset_mounts_only_existing_files(tmp_path):
    preset = tmp_path / "preset"
    preset.mkdir()
    (preset / "agent.toml").write_text("")
    (preset / ".mcp.json").write_text("{}")
    # no skills.toml

    mounts = cli.skillset_mounts("proj-123", preset)
    containers = {m.container for m in mounts}
    assert containers == {"/project/proj-123/agent.toml", "/project/proj-123/.mcp.json"}
    assert all(m.ro for m in mounts)


def test_skillset_mounts_empty_when_preset_has_none_of_the_files(tmp_path):
    preset = tmp_path / "preset"
    preset.mkdir()
    assert cli.skillset_mounts("proj-123", preset) == []


def test_build_mounts_includes_skillset_overlay(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths

    paths.ensure_layout()
    preset = tmp_path / "preset"
    preset.mkdir()
    (preset / ".mcp.json").write_text("{}")

    mounts = cli.build_mounts("proj-1", str(tmp_path / "repo"), tool="claude", skillset=preset)
    containers = {m.container for m in mounts}
    assert "/project/proj-1/.mcp.json" in containers


def test_interactive_menu_branches_to_skillset_menu_when_no_agents_dir(monkeypatch, tmp_path):
    other = tmp_path / "dev-project"
    other.mkdir()
    monkeypatch.chdir(other)

    called = []
    monkeypatch.setattr(cli, "_skillset_menu", lambda project_dir: called.append(project_dir))
    monkeypatch.setattr(
        cli, "_own_agents_menu", lambda agents_dir: (_ for _ in ()).throw(AssertionError("wrong menu"))
    )

    cli._interactive_menu()
    assert called == [other]


def test_interactive_menu_uses_own_agents_menu_when_agents_dir_present(monkeypatch, tmp_path):
    (tmp_path / "agents" / "jira").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    called = []
    monkeypatch.setattr(cli, "_own_agents_menu", lambda agents_dir: called.append(agents_dir))
    monkeypatch.setattr(
        cli, "_skillset_menu", lambda project_dir: (_ for _ in ()).throw(AssertionError("wrong menu"))
    )

    cli._interactive_menu()
    assert called == [tmp_path / "agents"]


def test_skillset_menu_no_skillset_selected(monkeypatch, tmp_path):
    project_dir = tmp_path / "dev-project"
    project_dir.mkdir()
    monkeypatch.setattr(cli, "_skillset_root", lambda: None)

    called = []
    monkeypatch.setattr(cli, "_project_action_menu", lambda pd, sk: called.append((pd, sk)))
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: "N")

    cli._skillset_menu(project_dir)
    assert called == [(project_dir, None)]


def test_skillset_menu_selects_a_preset(monkeypatch, tmp_path):
    project_dir = tmp_path / "dev-project"
    project_dir.mkdir()
    presets_root = tmp_path / "agentpod-agents"
    (presets_root / "n8n").mkdir(parents=True)
    (presets_root / "jira").mkdir(parents=True)
    monkeypatch.setattr(cli, "_skillset_root", lambda: presets_root)

    called = []
    monkeypatch.setattr(cli, "_project_action_menu", lambda pd, sk: called.append((pd, sk)))
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: "2")  # sorted: jira(1), n8n(2)

    cli._skillset_menu(project_dir)
    assert called == [(project_dir, presets_root / "n8n")]


def test_skillset_menu_quit(monkeypatch, tmp_path):
    project_dir = tmp_path / "dev-project"
    project_dir.mkdir()
    monkeypatch.setattr(cli, "_skillset_root", lambda: None)
    monkeypatch.setattr(
        cli, "_project_action_menu", lambda pd, sk: (_ for _ in ()).throw(AssertionError("should not reach"))
    )
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: "Q")

    cli._skillset_menu(project_dir)  # must not raise


def test_project_action_menu_run_passes_skillset(monkeypatch, tmp_path):
    project_dir = tmp_path / "dev-project"
    project_dir.mkdir()
    skillset = tmp_path / "preset"
    skillset.mkdir()
    monkeypatch.chdir(tmp_path)

    calls = []
    monkeypatch.setattr(cli, "run", lambda **kw: calls.append(kw))
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: "R")

    cli._project_action_menu(project_dir, skillset)

    assert len(calls) == 1
    assert calls[0]["skillset"] == str(skillset)
    assert Path.cwd() == tmp_path


def test_project_action_menu_run_without_skillset(monkeypatch, tmp_path):
    project_dir = tmp_path / "dev-project"
    project_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    calls = []
    monkeypatch.setattr(cli, "run", lambda **kw: calls.append(kw))
    monkeypatch.setattr(cli.typer, "prompt", lambda *a, **k: "R")

    cli._project_action_menu(project_dir, None)
    assert calls[0]["skillset"] is None
