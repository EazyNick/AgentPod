"""AgentPod CLI — spawn and drive per-project agent containers (BUILD-GUIDE §5)."""
from __future__ import annotations

import os
from pathlib import Path

import typer

from . import context as context_mod
from . import docker_ctl, naming, paths, registry, session
from .docker_ctl import Mount

app = typer.Typer(help="Docker-isolated AI coding agent containers.", no_args_is_help=True)

IMAGE_TAG = "agentpod:latest"
_DOCKERFILE = Path(__file__).resolve().parent.parent.parent / "Dockerfile"
_BUILD_CONTEXT = _DOCKERFILE.parent


def _fail(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def resolve_target(target: str) -> tuple[str, str]:
    """('.' or '') -> cwd. Returns (project_id, container_name)."""
    path = os.getcwd() if target in (".", "") else target
    pid = naming.project_id(path)
    return pid, naming.container_name(pid)


def build_mounts(project_id: str, project_path: str) -> list[Mount]:
    paths.ensure_layout()
    mounts = [
        Mount(str(Path(project_path).resolve()), f"/project/{project_id}"),
        Mount(str(paths.claude_creds_dir()), "/home/agent/.claude"),
        Mount(str(paths.claude_json_path()), "/home/agent/.claude.json"),
    ]
    ctx = context_mod.resolve_mount(project_id)
    if ctx is not None:
        mounts.append(Mount(ctx[0], ctx[1], ro=True))
    return mounts


def _require_docker() -> None:
    if not docker_ctl.docker_available():
        _fail("Docker is not available. Start the Docker daemon (WSL2) and retry.")


def _ensure_image() -> None:
    if not docker_ctl.image_exists(IMAGE_TAG):
        typer.echo(f"Image {IMAGE_TAG} not found; building...")
        docker_ctl.build_image(_DOCKERFILE, _BUILD_CONTEXT, IMAGE_TAG)


def ensure_container(project_id: str, project_path: str) -> str:
    cname = naming.container_name(project_id)
    state = docker_ctl.container_state(cname)
    if state == "running":
        return cname
    if state == "exited":
        docker_ctl.start(cname)
        return cname
    workdir = f"/project/{project_id}"
    env_file = None
    envp = Path(project_path) / ".env"
    if envp.is_file():
        env_file = str(envp)
    docker_ctl.run_detached(
        name=cname,
        image=IMAGE_TAG,
        mounts=build_mounts(project_id, project_path),
        workdir=workdir,
        env_file=env_file,
    )
    return cname


def _attach(project_id: str, cname: str, cmd: list[str]) -> None:
    prefix = naming.lock_prefix(project_id)
    lock = session.create_lock(prefix, session.new_session_id())

    def _cleanup() -> None:
        session.release_lock(lock, prefix, lambda: docker_ctl.stop(cname))

    session.install_signal_handlers(_cleanup)
    try:
        code = docker_ctl.exec_interactive(cname, cmd)
    finally:
        _cleanup()
    raise typer.Exit(code)


@app.command()
def build(force: bool = typer.Option(False, "--force", help="Rebuild even if present.")) -> None:
    """Build the agent container image."""
    _require_docker()
    if force or not docker_ctl.image_exists(IMAGE_TAG):
        docker_ctl.build_image(_DOCKERFILE, _BUILD_CONTEXT, IMAGE_TAG)
        typer.echo(f"Built {IMAGE_TAG}.")
    else:
        typer.echo(f"{IMAGE_TAG} already exists (use --force to rebuild).")


@app.command()
def run(
    tool: str = typer.Option(registry.DEFAULT_TOOL, "--tool", help="Tool to run."),
    extra: list[str] = typer.Argument(None, help="Extra args passed to the tool."),
) -> None:
    """Spawn/reuse this project's container and run the tool interactively."""
    _require_docker()
    _ensure_image()
    tdef = registry.get_tool(tool)
    pid, cname = resolve_target(".")
    ensure_container(pid, os.getcwd())
    cmd = [tdef.binary, *tdef.default_flags, *(extra or [])]
    _attach(pid, cname, cmd)


@app.command()
def shell() -> None:
    """Open an interactive bash shell in this project's container."""
    _require_docker()
    _ensure_image()
    pid, cname = resolve_target(".")
    ensure_container(pid, os.getcwd())
    _attach(pid, cname, ["bash"])


@app.command()
def status() -> None:
    """List all agent-* containers and their state."""
    _require_docker()
    rows = docker_ctl.list_agents()
    if not rows:
        typer.echo("No agent containers.")
        return
    for r in rows:
        pid = r["name"].removeprefix("agent-")
        n = len(session.active_sessions(naming.lock_prefix(pid)))
        typer.echo(f"{r['name']:50}  {r['state']:10}  sessions={n}")


@app.command()
def stop(target: str = typer.Argument(".")) -> None:
    """Stop a project's container (default: cwd)."""
    _require_docker()
    _, cname = resolve_target(target)
    docker_ctl.stop(cname)
    typer.echo(f"Stopped {cname}.")


@app.command()
def rm(target: str = typer.Argument(".")) -> None:
    """Stop and remove a project's container (default: cwd)."""
    _require_docker()
    _, cname = resolve_target(target)
    docker_ctl.remove(cname)
    typer.echo(f"Removed {cname}.")


@app.command()
def context(target: str = typer.Argument(".")) -> None:
    """Print this project's MD context folder path (§4.11)."""
    pid, _ = resolve_target(target)
    d = paths.context_dir(pid)
    typer.echo(str(d))
    if not d.is_dir():
        typer.echo(f"(does not exist yet — create it and add CLAUDE.md / *.md)", err=True)


if __name__ == "__main__":
    app()
