"""Thin subprocess wrappers around the docker CLI (BUILD-GUIDE §3.3, §5.3)."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Mount:
    host: str
    container: str
    ro: bool = False

    def to_arg(self) -> str:
        return f"{self.host}:{self.container}:ro" if self.ro else f"{self.host}:{self.container}"


def _run(args: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=capture,
        text=True,
        check=False,
    )


def docker_available() -> bool:
    try:
        return _run(["docker", "version", "-f", "{{.Server.Version}}"]).returncode == 0
    except FileNotFoundError:
        return False


def image_exists(tag: str) -> bool:
    return _run(["docker", "image", "inspect", tag]).returncode == 0


def build_image(dockerfile: Path, context_dir: Path, tag: str) -> None:
    cp = _run(
        ["docker", "build", "-f", str(dockerfile), "-t", tag, str(context_dir)],
        capture=False,
    )
    if cp.returncode != 0:
        raise RuntimeError(f"docker build failed for {tag}")


def container_state(name: str) -> str | None:
    cp = _run(["docker", "inspect", "-f", "{{.State.Status}}", name])
    if cp.returncode != 0:
        return None
    return cp.stdout.strip() or None


def run_detached(
    name: str,
    image: str,
    mounts: list[Mount],
    workdir: str,
    env_file: str | None,
    memory: str | None = None,
    cpus: str | None = None,
    pids_limit: int | None = None,
) -> None:
    args = ["docker", "run", "-d", "--name", name, "-w", workdir]
    if env_file:
        args += ["--env-file", env_file]
    if memory:
        args += ["--memory", memory]
    if cpus:
        args += ["--cpus", str(cpus)]
    if pids_limit is not None:
        args += ["--pids-limit", str(pids_limit)]
    for m in mounts:
        args += ["-v", m.to_arg()]
    args.append(image)
    cp = _run(args)
    if cp.returncode != 0:
        raise RuntimeError(f"docker run failed: {cp.stderr.strip()}")


def start(name: str) -> None:
    cp = _run(["docker", "start", name])
    if cp.returncode != 0:
        raise RuntimeError(f"docker start failed: {cp.stderr.strip()}")


def exec_interactive(name: str, cmd: list[str]) -> int:
    # Interactive: inherit the terminal; do not capture.
    return subprocess.run(["docker", "exec", "-it", name, *cmd], check=False).returncode


def stop(name: str) -> None:
    _run(["docker", "stop", name])


def remove(name: str) -> None:
    _run(["docker", "stop", name])
    _run(["docker", "rm", name])


def list_agents() -> list[dict]:
    cp = _run(
        [
            "docker", "ps", "-a",
            "--filter", "name=agent-",
            "--format", "{{.Names}}\t{{.State}}",
        ]
    )
    rows: list[dict] = []
    for line in cp.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        name, _, state = line.partition("\t")
        rows.append({"name": name, "state": state})
    return rows
