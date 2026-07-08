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
