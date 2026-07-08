import subprocess

from agentpod import docker_ctl
from agentpod.docker_ctl import Mount


def test_mount_to_arg():
    assert Mount("/h", "/c").to_arg() == "/h:/c"
    assert Mount("/h", "/c", ro=True).to_arg() == "/h:/c:ro"


def test_container_state_running(monkeypatch):
    def fake_run(args, **kw):
        assert args[:3] == ["docker", "inspect", "-f"]
        return subprocess.CompletedProcess(args, 0, stdout="running\n", stderr="")

    monkeypatch.setattr(docker_ctl.subprocess, "run", fake_run)
    assert docker_ctl.container_state("agent-x") == "running"


def test_container_state_absent(monkeypatch):
    def fake_run(args, **kw):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="No such object")

    monkeypatch.setattr(docker_ctl.subprocess, "run", fake_run)
    assert docker_ctl.container_state("agent-x") is None


def test_run_detached_assembles_command(monkeypatch):
    captured = {}

    def fake_run(args, **kw):
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(docker_ctl.subprocess, "run", fake_run)
    docker_ctl.run_detached(
        name="agent-x",
        image="agentpod:latest",
        mounts=[Mount("/proj", "/project/x"), Mount("/ctx", "/home/agent/context", ro=True)],
        workdir="/project/x",
        env_file="/proj/.env",
    )
    args = captured["args"]
    assert args[0:3] == ["docker", "run", "-d"]
    assert "--name" in args and "agent-x" in args
    assert "-w" in args and "/project/x" in args
    assert "--env-file" in args and "/proj/.env" in args
    assert "/proj:/project/x" in args
    assert "/ctx:/home/agent/context:ro" in args
    assert args[-1] == "agentpod:latest"


def test_run_detached_omits_env_file_when_none(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        docker_ctl.subprocess, "run",
        lambda args, **kw: (captured.setdefault("args", args), subprocess.CompletedProcess(args, 0, "", ""))[1],
    )
    docker_ctl.run_detached("agent-x", "img", [], "/w", None)
    assert "--env-file" not in captured["args"]


def _capture(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        docker_ctl.subprocess, "run",
        lambda args, **kw: (captured.setdefault("args", args), subprocess.CompletedProcess(args, 0, "", ""))[1],
    )
    return captured


def test_run_detached_resource_limits(monkeypatch):
    captured = _capture(monkeypatch)
    docker_ctl.run_detached(
        "agent-x", "img", [], "/w", None, memory="4g", cpus="2", pids_limit=512
    )
    a = captured["args"]
    assert a[a.index("--memory") + 1] == "4g"
    assert a[a.index("--cpus") + 1] == "2"
    assert a[a.index("--pids-limit") + 1] == "512"
    # resource flags precede the image (last arg)
    assert a[-1] == "img"


def test_run_detached_omits_limits_when_none(monkeypatch):
    captured = _capture(monkeypatch)
    docker_ctl.run_detached("agent-x", "img", [], "/w", None)
    a = captured["args"]
    assert "--memory" not in a and "--cpus" not in a and "--pids-limit" not in a


def test_list_agents_parses_lines(monkeypatch):
    out = "agent-a\trunning\nagent-b\texited\n"
    monkeypatch.setattr(
        docker_ctl.subprocess, "run",
        lambda args, **kw: subprocess.CompletedProcess(args, 0, out, ""),
    )
    rows = docker_ctl.list_agents()
    assert rows == [
        {"name": "agent-a", "state": "running"},
        {"name": "agent-b", "state": "exited"},
    ]
