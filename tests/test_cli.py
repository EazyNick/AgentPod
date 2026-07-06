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


def test_render_gitconfig():
    out = cli.render_gitconfig("agent-bot", "bot@users.noreply.github.com", False)
    assert "name = agent-bot" in out
    assert "email = bot@users.noreply.github.com" in out
    assert "directory = *" in out
    assert "helper = store" not in out
    assert "helper = store" in cli.render_gitconfig("b", "e", True)
