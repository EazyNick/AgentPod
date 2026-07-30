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
    epilog=(
        "Tool selection (claude | codex | opencode) is a per-command flag, not shown "
        "above - see `agentpod run --help` / `agentpod shell --help`.\n\n"
        "Examples:\n\n"
        "agentpod run --tool codex\n\n"
        "agentpod shell --tool opencode"
    ),
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Docker-isolated AI coding agent containers. Run with no arguments for a folder-picker menu."""
    if ctx.invoked_subcommand is None:
        _interactive_menu()

IMAGE_TAG = "agentpod:latest"
_DOCKERFILE = Path(__file__).resolve().parent.parent.parent / "Dockerfile"
_BUILD_CONTEXT = _DOCKERFILE.parent


def _fail(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def _skillset_root() -> Path | None:
    """Locate the agentpod repo's own agents/ folder (skillset presets: agent.toml/
    skills.toml/.mcp.json per subfolder) independent of cwd -- so an unrelated dev
    project elsewhere can still borrow one. Editable-install source tree first,
    then cwd."""
    for root in (Path(__file__).resolve().parent.parent.parent, Path.cwd()):
        agents = root / "agents"
        if agents.is_dir():
            return agents
    return None


def _resolve_skillset(name: str | None) -> Path | None:
    """--skillset value -> an absolute folder path. Accepts either a literal
    path or a bare name resolved under _skillset_root() (an agentpod agents/*
    preset)."""
    if not name:
        return None
    p = Path(name)
    if p.is_dir():
        return p.resolve()
    root = _skillset_root()
    if root is not None and (root / name).is_dir():
        return root / name
    _fail(f"Skillset '{name}' not found (checked as a path, and under {root or '<agentpod repo>/agents'}).")


def skillset_mounts(project_id: str, skillset: Path) -> list[Mount]:
    """Read-only overlay of a borrowed agents/<name> preset's CLAUDE.md, MCP config,
    skills manifest, and project-local .claude/ (settings.local.json, project-scoped
    .claude/skills/*, etc.) onto this project's container paths -- so an unrelated
    dev project can borrow a ready-made skillset without the preset's files ever
    touching the project's own files on the host (bind mounts only affect the
    container's view of these specific paths). If the preset has its own .claude/,
    it fully replaces whatever the target project would otherwise have at that path.
    """
    workdir = f"/project/{project_id}"
    mounts: list[Mount] = []
    for fn in ("CLAUDE.md", "agent.toml", "skills.toml", ".mcp.json"):
        src = skillset / fn
        if src.is_file():
            mounts.append(Mount(str(src), f"{workdir}/{fn}", ro=True))
    claude_dir = skillset / ".claude"
    if claude_dir.is_dir():
        mounts.append(Mount(str(claude_dir), f"{workdir}/.claude", ro=True))
    return mounts


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
    skillset: Path | None = None,
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
    if skillset is not None:
        mounts += skillset_mounts(project_id, skillset)
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
    skillset: Path | None = None,
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
        mounts=build_mounts(project_id, project_path, tool, profile, skillset),
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
        # Short timeout: on Windows this can run from a console-close handler,
        # which only gets a few seconds before the OS force-kills the process --
        # docker's own default stop timeout (10s) risks losing the race.
        session.release_lock(lock, prefix, lambda: docker_ctl.stop(cname, timeout=3))

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
_SKILLSET_OPT = typer.Option(
    None,
    "--skillset",
    help=(
        "Borrow tools/MCP/skills (agent.toml/skills.toml/.mcp.json) from an agentpod "
        "agents/<name> preset -- or a literal path -- without touching this project's "
        "own files. Useful for an unrelated dev project that wants a ready-made skillset."
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
    skillset: str = _SKILLSET_OPT,
    extra: list[str] = typer.Argument(None, help="Extra args passed to the tool."),
) -> None:
    """Spawn/reuse this project's container and run the tool interactively (--tool claude|codex|opencode)."""
    _require_docker()
    _ensure_image()
    prof = _profile(profile)
    tdef = registry.get_tool(tool)
    pid, cname = resolve_target(".", prof)
    ensure_container(pid, os.getcwd(), _resources(memory, cpus, pids), tool, prof, _resolve_skillset(skillset))
    cmd = [tdef.binary, *tdef.default_flags, *(extra or [])]
    _attach(pid, cname, cmd, prof)


@app.command()
def shell(
    profile: str = _PROFILE_OPT,
    tool: str = _TOOL_OPT,
    memory: str = _MEM_OPT,
    cpus: str = _CPU_OPT,
    pids: int = _PID_OPT,
    skillset: str = _SKILLSET_OPT,
) -> None:
    """Open an interactive bash shell in this project's container (--tool claude|codex|opencode)."""
    _require_docker()
    _ensure_image()
    prof = _profile(profile)
    pid, cname = resolve_target(".", prof)
    ensure_container(pid, os.getcwd(), _resources(memory, cpus, pids), tool, prof, _resolve_skillset(skillset))
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


@app.command()
def export(target: str = typer.Argument("."), profile: str = _PROFILE_OPT) -> None:
    """Write installed claude plugins/skills + MCP servers into agent.toml/.mcp.json for sharing."""
    path = os.getcwd() if target in (".", "") else target
    project_path = Path(path).resolve()
    pid = naming.project_id(str(project_path))
    prof = _profile(profile)

    added_skills = plugins.export_skills(
        paths.claude_creds_dir(creds_profile(prof, pid)), project_path / "agent.toml"
    )
    added_mcp = plugins.export_mcp_servers(
        paths.claude_json_path(prof), f"/project/{pid}", project_path
    )

    if not added_skills and not added_mcp:
        typer.echo("Nothing new to export (already declared, or nothing beyond the baseline).")
        return
    if added_skills:
        typer.echo(f"agent.toml: added skill(s) {', '.join(added_skills)}")
    if added_mcp:
        typer.echo(f".mcp.json: added MCP server(s) {', '.join(added_mcp)} (secrets written to .env)")
    typer.echo("Review the diff, then commit agent.toml / .mcp.json. Never commit .env.")


def _resolve_agents_dir(base: Path) -> Path:
    """base/agents if that exists; otherwise base itself if it's already an
    "agents" folder (e.g. the user cd'd straight into agents\\ and ran
    `agentpod` from there, rather than from the repo root)."""
    candidate = base / "agents"
    if candidate.is_dir():
        return candidate
    if base.name == "agents":
        return base
    return candidate


def _list_agent_folders(agents_dir: Path) -> list[Path]:
    if not agents_dir.is_dir():
        return []
    return sorted((p for p in agents_dir.iterdir() if p.is_dir()), key=lambda p: p.name)


def _agent_action_menu(target: Path) -> None:
    """Sub-menu for one selected project: run / shell / export it, or go back."""
    while True:
        typer.echo(f"\n  선택: {target}")
        typer.echo("  R) 실행 (agentpod run)")
        typer.echo("  S) 셸 접속 (agentpod shell)")
        typer.echo("  E) 공유용으로 내보내기 (agentpod export)")
        typer.echo("  B) 뒤로")
        action = typer.prompt("동작 선택", default="B").strip().lower()

        old_cwd = os.getcwd()
        os.chdir(target)
        try:
            if action == "r":
                run(tool=registry.DEFAULT_TOOL, profile=None, memory=None, cpus=None, pids=None, extra=[])
                return
            if action == "s":
                shell(profile=None, tool=registry.DEFAULT_TOOL, memory=None, cpus=None, pids=None)
                return
            if action == "e":
                export(target=".", profile=None)
                typer.prompt("계속하려면 Enter", default="", show_default=False)
                continue
            if action == "b":
                return
            typer.echo("잘못된 선택입니다.")
        finally:
            os.chdir(old_cwd)


def _interactive_menu() -> None:
    """No subcommand given: a folder-picker menu (BUILD-GUIDE §5).

    If cwd has its own agents/* (or cwd is itself an "agents" folder), pick one
    of those and treat it as the project -- unchanged original behavior. Otherwise
    cwd is an unrelated dev project outside the agentpod repo: offer to borrow a
    skillset preset from the agentpod repo's own agents/* instead, applied on top
    of this project rather than replacing it.
    """
    cwd = Path.cwd()
    agents_dir = _resolve_agents_dir(cwd)
    if agents_dir.is_dir():
        _own_agents_menu(agents_dir)
    else:
        _skillset_menu(cwd)


def _own_agents_menu(agents_dir: Path) -> None:
    """cwd has its own agents/* -- pick one and treat it as the project."""
    while True:
        typer.echo("=== AgentPod ===\n")
        folders = _list_agent_folders(agents_dir)
        if not folders:
            typer.echo(f"{agents_dir} 아래에 폴더가 없습니다.")
        else:
            for i, f in enumerate(folders, 1):
                typer.echo(f"  {i}) {f.name}")
        typer.echo("\n  P) 다른 경로 직접 입력")
        typer.echo("  Q) 종료\n")
        choice = typer.prompt("실행할 에이전트 번호", default="Q").strip()

        if choice.lower() == "q":
            return
        target: Path | None
        if choice.lower() == "p":
            target = Path(typer.prompt("프로젝트 경로 입력"))
        elif choice.isdigit() and 1 <= int(choice) <= len(folders):
            target = folders[int(choice) - 1]
        else:
            typer.echo("잘못된 선택입니다.")
            continue

        if not target.is_dir():
            typer.echo(f"경로가 없습니다: {target}")
            continue
        _agent_action_menu(target)


def _skillset_menu(project_dir: Path) -> None:
    """cwd has no agents/ of its own -- treat cwd as an external dev project and
    offer to borrow a skillset preset (tools/MCP/skills) from the agentpod repo's
    own agents/*, applied on top of this project without touching its files."""
    presets_root = _skillset_root()
    presets = _list_agent_folders(presets_root) if presets_root else []
    while True:
        typer.echo("=== AgentPod ===\n")
        typer.echo(f"현재 폴더: {project_dir}")
        typer.echo("(이 폴더에는 agents\\ 가 없어 외부 프로젝트로 인식했습니다)\n")
        if not presets:
            typer.echo("빌려올 스킬셋 프리셋도 찾지 못했습니다 — 스킬셋 없이 실행합니다.\n")
        else:
            typer.echo("이 프로젝트에 빌려올 스킬셋(도구/MCP/스킬)을 고르세요:\n")
            for i, p in enumerate(presets, 1):
                typer.echo(f"  {i}) {p.name}")
        typer.echo("\n  N) 스킬셋 없이 이 프로젝트만 실행")
        typer.echo("  Q) 종료\n")
        choice = typer.prompt("스킬셋 번호", default="N").strip()

        if choice.lower() == "q":
            return
        skillset: Path | None = None
        if choice.lower() != "n":
            if choice.isdigit() and 1 <= int(choice) <= len(presets):
                skillset = presets[int(choice) - 1]
            else:
                typer.echo("잘못된 선택입니다.")
                continue
        _project_action_menu(project_dir, skillset)
        return


def _project_action_menu(project_dir: Path, skillset: Path | None) -> None:
    """Sub-menu for the current (non-agents) project dir, optionally with a
    borrowed skillset: run / shell / export it, or go back."""
    label = str(project_dir) + (f"  (skillset: {skillset.name})" if skillset else "")
    while True:
        typer.echo(f"\n  선택: {label}")
        typer.echo("  R) 실행 (agentpod run)")
        typer.echo("  S) 셸 접속 (agentpod shell)")
        typer.echo("  E) 공유용으로 내보내기 (agentpod export)")
        typer.echo("  B) 뒤로")
        action = typer.prompt("동작 선택", default="B").strip().lower()

        skillset_arg = str(skillset) if skillset else None
        old_cwd = os.getcwd()
        os.chdir(project_dir)
        try:
            if action == "r":
                run(
                    tool=registry.DEFAULT_TOOL, profile=None, memory=None, cpus=None, pids=None,
                    skillset=skillset_arg, extra=[],
                )
                return
            if action == "s":
                shell(
                    profile=None, tool=registry.DEFAULT_TOOL, memory=None, cpus=None, pids=None,
                    skillset=skillset_arg,
                )
                return
            if action == "e":
                export(target=".", profile=None)
                typer.prompt("계속하려면 Enter", default="", show_default=False)
                continue
            if action == "b":
                return
            typer.echo("잘못된 선택입니다.")
        finally:
            os.chdir(old_cwd)


if __name__ == "__main__":
    app()
