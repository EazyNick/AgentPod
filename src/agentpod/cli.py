"""AgentPod CLI — spawn and drive per-project agent containers (BUILD-GUIDE §5)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import typer

from . import context as context_mod
from . import config, docker_ctl, naming, paths, plugins, registry, session
from .docker_ctl import Mount

app = typer.Typer(
    help="Docker-isolated AI coding agent containers.",
    no_args_is_help=True,
    epilog=(
        "Tool selection (claude | codex | opencode) is a per-command flag, not shown "
        "above - see `agentpod run --help` / `agentpod shell --help`.\n\n"
        "Examples:\n\n"
        "agentpod run --tool codex\n\n"
        "agentpod shell --tool opencode"
    ),
)

IMAGE_TAG = "agentpod:latest"
_DOCKERFILE = Path(__file__).resolve().parent.parent.parent / "Dockerfile"
_BUILD_CONTEXT = _DOCKERFILE.parent


def _fail(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def resolve_target(target: str, profile: str | None = None) -> tuple[str, str]:
    """('.' or '') -> cwd. Returns (project_id, container_name)."""
    path = os.getcwd() if target in (".", "") else target
    pid = naming.project_id(path)
    return pid, naming.container_name(pid, profile)


def creds_profile(profile: str | None, project_id: str) -> str:
    """Plugin/skill install state is isolated per project by default (keyed by
    project_id) so an install in one project's container never leaks into
    another's. Pass --profile explicitly to opt into sharing/copying another
    project's plugin state under a shared name instead. Login (.claude.json)
    is untouched by this -- it stays on the shared root unless --profile is
    given (see build_mounts)."""
    return profile or project_id


def build_mounts(
    project_id: str,
    project_path: str,
    tool: str = registry.DEFAULT_TOOL,
    profile: str | None = None,
) -> list[Mount]:
    paths.ensure_layout()
    tdef = registry.get_tool(tool)
    creds = paths.tool_creds_dir(tdef.creds_key, creds_profile(profile, project_id))
    creds.mkdir(parents=True, exist_ok=True)
    mounts = [
        Mount(str(Path(project_path).resolve()), f"/project/{project_id}"),
        Mount(str(creds), tdef.creds_container_path),
    ]
    if tdef.uses_claude_json:
        cj = paths.claude_json_path(profile)  # shared across projects unless --profile given
        if not cj.exists():
            cj.write_text("{}\n")
        mounts.append(Mount(str(cj), "/home/agent/.claude.json"))
    ctx = context_mod.resolve_mount(project_id)
    if ctx is not None:
        mounts.append(Mount(ctx[0], ctx[1], ro=True))
    # Shared bot git identity (BUILD-GUIDE §4.5) — mounted read-only into every
    # container (entrypoint must not rewrite a bind-mounted file).
    mounts.append(Mount(str(paths.gitconfig_path()), "/home/agent/.gitconfig", ro=True))
    if paths.git_credentials_path().exists():
        mounts.append(
            Mount(str(paths.git_credentials_path()), "/home/agent/.git-credentials", ro=True)
        )
    # Bot SSH keys (deploy/account key) for SSH remotes (Bitbucket/GitLab/GitHub).
    # rw so ssh can update known_hosts; keys/perms come from the host dir.
    if paths.ssh_dir().is_dir():
        mounts.append(Mount(str(paths.ssh_dir()), "/home/agent/.ssh"))
    return mounts


def render_gitconfig(name: str, email: str, credential_store: bool) -> str:
    """Render the shared bot ~/.gitconfig contents."""
    lines = [
        "[user]",
        f"\tname = {name}",
        f"\temail = {email}",
        "[safe]",
        "\tdirectory = *",
    ]
    if credential_store:
        lines += ["[credential]", "\thelper = store"]
    return "\n".join(lines) + "\n"


def _require_docker() -> None:
    if not docker_ctl.docker_available():
        _fail("Docker is not available. Start the Docker daemon (WSL2) and retry.")


def _ensure_image() -> None:
    if not docker_ctl.image_exists(IMAGE_TAG):
        typer.echo(f"Image {IMAGE_TAG} not found; building...")
        docker_ctl.build_image(_DOCKERFILE, _BUILD_CONTEXT, IMAGE_TAG)


def ensure_container(
    project_id: str,
    project_path: str,
    resources: config.Resources | None = None,
    tool: str = registry.DEFAULT_TOOL,
    profile: str | None = None,
) -> str:
    cname = naming.container_name(project_id, profile)
    state = docker_ctl.container_state(cname)
    if state == "running":
        return cname
    if registry.get_tool(tool).uses_claude_json:
        plugins.seed_superpowers(paths.claude_creds_dir(creds_profile(profile, project_id)))
    if state == "exited":
        docker_ctl.start(cname)
        return cname
    res = resources or config.resource_limits()
    workdir = f"/project/{project_id}"
    env_file = None
    envp = Path(project_path) / ".env"
    if envp.is_file():
        env_file = str(envp)
    docker_ctl.run_detached(
        name=cname,
        image=IMAGE_TAG,
        mounts=build_mounts(project_id, project_path, tool, profile),
        workdir=workdir,
        env_file=env_file,
        memory=res.memory,
        cpus=res.cpus,
        pids_limit=res.pids_limit,
    )
    return cname


def _attach(project_id: str, cname: str, cmd: list[str], profile: str | None = None) -> None:
    prefix = naming.lock_prefix(project_id, profile)
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


_MEM_OPT = typer.Option(None, "--memory", help="Memory cap (e.g. 4g). Default AGENT_MEMORY or 4g.")
_CPU_OPT = typer.Option(None, "--cpus", help="CPU cap (e.g. 2). Default AGENT_CPUS or 2.")
_PID_OPT = typer.Option(None, "--pids", help="Max PIDs. Default AGENT_PIDS_LIMIT or 512.")
_TOOL_OPT = typer.Option(registry.DEFAULT_TOOL, "--tool", help="Tool: claude | codex | opencode.")
_PROFILE_OPT = typer.Option(
    None,
    "--profile",
    help=(
        "Share/copy plugin state with another project under this name (plugins/"
        "skills are isolated per project by default; login stays shared either way). "
        "Default AGENT_PROFILE."
    ),
)


def _resources(memory: str | None, cpus: str | None, pids: int | None) -> config.Resources:
    """CLI overrides layered on the host defaults."""
    return config.merge(config.resource_limits(), memory, cpus, pids)


def _profile(opt: str | None) -> str | None:
    return opt or os.environ.get("AGENT_PROFILE") or None


@app.command()
def run(
    tool: str = _TOOL_OPT,
    profile: str = _PROFILE_OPT,
    memory: str = _MEM_OPT,
    cpus: str = _CPU_OPT,
    pids: int = _PID_OPT,
    extra: list[str] = typer.Argument(None, help="Extra args passed to the tool."),
) -> None:
    """Spawn/reuse this project's container and run the tool interactively (--tool claude|codex|opencode)."""
    _require_docker()
    _ensure_image()
    prof = _profile(profile)
    tdef = registry.get_tool(tool)
    pid, cname = resolve_target(".", prof)
    ensure_container(pid, os.getcwd(), _resources(memory, cpus, pids), tool, prof)
    cmd = [tdef.binary, *tdef.default_flags, *(extra or [])]
    _attach(pid, cname, cmd, prof)


@app.command()
def shell(
    profile: str = _PROFILE_OPT,
    tool: str = _TOOL_OPT,
    memory: str = _MEM_OPT,
    cpus: str = _CPU_OPT,
    pids: int = _PID_OPT,
) -> None:
    """Open an interactive bash shell in this project's container (--tool claude|codex|opencode)."""
    _require_docker()
    _ensure_image()
    prof = _profile(profile)
    pid, cname = resolve_target(".", prof)
    ensure_container(pid, os.getcwd(), _resources(memory, cpus, pids), tool, prof)
    _attach(pid, cname, ["bash"], prof)


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
def stop(target: str = typer.Argument("."), profile: str = _PROFILE_OPT) -> None:
    """Stop a project's container (default: cwd)."""
    _require_docker()
    _, cname = resolve_target(target, _profile(profile))
    docker_ctl.stop(cname)
    typer.echo(f"Stopped {cname}.")


@app.command()
def rm(target: str = typer.Argument("."), profile: str = _PROFILE_OPT) -> None:
    """Stop and remove a project's container (default: cwd)."""
    _require_docker()
    _, cname = resolve_target(target, _profile(profile))
    docker_ctl.remove(cname)
    typer.echo(f"Removed {cname}.")


def _setup_ssh(ssh_host: str) -> None:
    """Generate a bot SSH key under ~/.agent/ssh and print the public key to register."""
    d = paths.ssh_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    key = d / "id_ed25519"
    if not key.exists():
        try:
            subprocess.run(
                ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "agentpod-bot", "-f", str(key)],
                check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            _fail("ssh-keygen unavailable. Install OpenSSH, or create ~/.agent/ssh/id_ed25519 manually.")
    try:
        os.chmod(key, 0o600)
    except OSError:
        pass
    kh = d / "known_hosts"
    try:
        out = subprocess.run(["ssh-keyscan", ssh_host], capture_output=True, text=True).stdout
        existing = kh.read_text() if kh.exists() else ""
        if out and ssh_host not in existing:
            kh.write_text(existing + out)
    except (FileNotFoundError, OSError):
        pass
    pub = (d / "id_ed25519.pub").read_text().strip()
    typer.echo("")
    typer.secho(f"아래 공개키를 원격({ssh_host})에 등록하세요:", fg=typer.colors.GREEN)
    typer.echo("  Bitbucket: Personal settings → SSH keys → Add key (또는 repo Access keys)")
    typer.echo(pub)


@app.command("git-setup")
def git_setup(
    name: str = typer.Option(..., "--name", help="Bot commit author name."),
    email: str = typer.Option(..., "--email", help="Bot commit author email."),
    token: str = typer.Option(
        None, "--token", help="PAT for HTTPS push/pull (stored in ~/.agent/git-credentials)."
    ),
    host: str = typer.Option("github.com", "--host", help="Git host for the token."),
    ssh: bool = typer.Option(False, "--ssh", help="Generate a bot SSH key (for SSH remotes like Bitbucket)."),
    ssh_host: str = typer.Option("bitbucket.org", "--ssh-host", help="Host added to known_hosts."),
) -> None:
    """Register a shared bot git identity used by ALL agent containers (§4.5)."""
    paths.ensure_layout()
    use_cred = token is not None
    paths.gitconfig_path().write_text(render_gitconfig(name, email, use_cred))
    if use_cred:
        cred = paths.git_credentials_path()
        cred.write_text(f"https://x-access-token:{token}@{host}\n")
        os.chmod(cred, 0o600)
    typer.echo(
        f"Bot git identity saved under {paths.agent_root()} "
        f"(shared by all containers){' with push token' if use_cred else ''}."
    )
    if ssh:
        _setup_ssh(ssh_host)


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
