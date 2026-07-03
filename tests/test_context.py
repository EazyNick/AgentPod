from agentpod import context


def test_resolve_mount_none_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    assert context.resolve_mount("myrepo-abc") is None


def test_resolve_mount_present(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    ctx = tmp_path / "root" / "contexts" / "myrepo-abc"
    ctx.mkdir(parents=True)
    host, container = context.resolve_mount("myrepo-abc")
    assert host == str(ctx)
    assert container == context.CONTAINER_CONTEXT_PATH
