"""Host-side one-time seed of the superpowers Claude Code plugin (BUILD-GUIDE §4.x).

Agent containers share a per-profile creds directory (paths.claude_creds_dir)
that's bind-mounted onto /home/agent/.claude, so whatever plugin state lives
there is available to every container for that profile. Previously that state
only got populated by agent-entrypoint.sh cloning the marketplace at container
boot -- meaning the first agent to boot for a fresh profile always paid for a
live git clone.

This seeds the shared directory once, using the HOST's own `claude` CLI, before
any container ever mounts it -- so in the common case no container has to clone
anything at boot; the entrypoint's install guard just finds it already there.
Best-effort and silent: if `claude` isn't on the host PATH, or the install
fails, we simply fall back to the existing runtime install in
agent-entrypoint.sh. Never blocks or fails `agentpod run`/`shell`/`build`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

MARKETPLACE = "claude-plugins-official"
MARKETPLACE_SOURCE = "anthropics/claude-plugins-official"
PLUGIN_NAME = "superpowers"
PLUGIN = f"{PLUGIN_NAME}@{MARKETPLACE}"

# Plugins guaranteed by the container's own baseline install (agent-entrypoint.sh
# + seed_superpowers above), so exporting them into a project manifest would
# just be redundant noise -- every project gets them regardless.
BASELINE_SKILL_NAMES = {"superpowers"}

MANIFESTS = ("agent.toml", "skills.toml")


def _is_fully_seeded(creds_dir: Path) -> bool:
    """Verify the plugin actually has usable content on disk, not just registry
    bookkeeping. `installed_plugins.json` is NOT checked here -- observed
    empty (`"plugins": {}`) even for a fully working install (confirmed via
    `claude plugin details`, which lists all skills correctly) on the claude
    CLI versions this was tested against, so it's not a trustworthy signal.
    The plugin cache directory actually holding files IS trustworthy: it's
    exactly what's missing in the broken case (e.g. a cross-OS `claude`
    binary -- a Windows install reached through WSL PATH interop -- that
    registers the marketplace/enables the plugin but never fetches its
    content).
    """
    cache_dir = creds_dir / "plugins" / "cache" / MARKETPLACE / PLUGIN_NAME
    if not cache_dir.is_dir() or not any(cache_dir.iterdir()):
        return False
    enabled = _read_json(creds_dir / "settings.json").get("enabledPlugins", {})
    return enabled.get(PLUGIN) is True


def _remove_key(path: Path, *key_path: str) -> None:
    if not path.exists():
        return
    data = _read_json(path)
    node = data
    for k in key_path[:-1]:
        node = node.get(k)
        if not isinstance(node, dict):
            return
    node.pop(key_path[-1], None)
    try:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 - best-effort cleanup
        pass


def _undo_partial_seed(creds_dir: Path) -> None:
    """Best-effort rollback after a seed attempt that raised, or ran to
    completion but left an inconsistent installed+enabled state -- e.g.
    `claude` on PATH resolved to a cross-OS binary (a Windows install reached
    through WSL PATH interop) that can't interpret a same-OS CLAUDE_CONFIG_DIR
    path, and silently no-ops or half-writes instead of erroring. Removes
    exactly what a clean seed would have created, so the shared dir goes back
    to "nothing seeded" and the container's own (guaranteed same-OS)
    entrypoint install can complete it instead of inheriting a broken
    half-state.
    """
    for rel in ("marketplaces", "cache"):
        p = creds_dir / "plugins" / rel / MARKETPLACE
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    _remove_key(creds_dir / "plugins" / "known_marketplaces.json", MARKETPLACE)
    _remove_key(creds_dir / "plugins" / "installed_plugins.json", "plugins", PLUGIN)
    _remove_key(creds_dir / "settings.json", "enabledPlugins", PLUGIN)
    _remove_key(creds_dir / "settings.json", "extraKnownMarketplaces", MARKETPLACE)


def seed_superpowers(creds_dir: Path) -> None:
    """Install+enable superpowers into creds_dir if not already there (best-effort).
    Verifies the result and rolls back to a clean slate on any inconsistency
    (see _undo_partial_seed) rather than trusting a lack of exceptions.
    """
    if (creds_dir / "plugins" / "marketplaces" / MARKETPLACE).is_dir():
        return
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return
    creds_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(creds_dir)}
    for args in (
        ["plugin", "marketplace", "add", MARKETPLACE_SOURCE],
        ["plugin", "install", PLUGIN],
        ["plugin", "enable", PLUGIN],
    ):
        try:
            subprocess.run(
                [claude_bin, *args],
                env=env,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except Exception:  # noqa: BLE001 - best-effort, never block the CLI
            _undo_partial_seed(creds_dir)
            return

    if not _is_fully_seeded(creds_dir):
        _undo_partial_seed(creds_dir)
        return

    # CLAUDE_CONFIG_DIR also writes a top-level .claude.json/backups here, which
    # isn't meaningful in this spot (the container mounts .claude.json
    # separately) -- drop it so the seeded dir only holds real .claude state.
    for stray in (".claude.json", ".claude.json.lock", "backups"):
        p = creds_dir / stray
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink(missing_ok=True)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - missing/corrupt state just yields nothing
        return {}


def _existing_skill_names(project_path: Path) -> set[str]:
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11
        return set()
    names: set[str] = set()
    for fn in MANIFESTS:
        p = project_path / fn
        if not p.is_file():
            continue
        try:
            with p.open("rb") as f:
                names |= {e.get("name") for e in tomllib.load(f).get("skills", []) if e.get("name")}
        except Exception:  # noqa: BLE001 - a broken manifest just yields nothing new
            continue
    return names


def export_skills(creds_dir: Path, manifest_path: Path) -> list[str]:
    """Append [[skills]] entries to manifest_path for every plugin installed
    AND enabled in creds_dir that isn't already declared (in agent.toml or
    skills.toml) and isn't part of the guaranteed baseline. Returns the names
    actually added. Best-effort: missing/corrupt state just yields nothing.
    """
    installed = _read_json(creds_dir / "plugins" / "installed_plugins.json").get("plugins", {})
    enabled = _read_json(creds_dir / "settings.json").get("enabledPlugins", {})
    known_marketplaces = _read_json(creds_dir / "plugins" / "known_marketplaces.json")
    existing = _existing_skill_names(manifest_path.parent)

    to_add: dict[str, str] = {}
    for key in installed:
        if not enabled.get(key):
            continue
        name, _, marketplace = key.partition("@")
        if name in BASELINE_SKILL_NAMES or name in existing or name in to_add:
            continue
        to_add[name] = marketplace
    if not to_add:
        return []

    blocks = []
    for name, marketplace in sorted(to_add.items()):
        lines = ["[[skills]]", f'name = "{name}"']
        repo = known_marketplaces.get(marketplace, {}).get("source", {}).get("repo")
        if repo:
            lines.append(f'source = "github:{repo}"')
        lines.append(f'marketplace_name = "{marketplace}"')
        blocks.append("\n".join(lines))
    prefix = "\n" if manifest_path.exists() and manifest_path.stat().st_size > 0 else ""
    with manifest_path.open("a", encoding="utf-8") as f:
        f.write(prefix + "\n\n".join(blocks) + "\n")
    return sorted(to_add)


def export_mcp_servers(claude_json_path: Path, container_project_path: str, project_path: Path) -> list[str]:
    """Copy MCP servers added ad-hoc during a session (default `claude mcp add`
    scope is "local", stored per-project inside the shared .claude.json) into
    this project's own .mcp.json (project scope), so `git clone` + `agentpod
    run` reproduces them for anyone else.

    Literal env/header values are NEVER inlined into .mcp.json -- they're
    always externalized to .env (already gitignored repo-wide) as ${VAR}
    placeholders, matching the existing agents/n8n/.mcp.json convention, so an
    export can never leak a secret into a committed file.
    """
    servers = (
        _read_json(claude_json_path).get("projects", {}).get(container_project_path, {}).get("mcpServers", {})
    )
    if not servers:
        return []

    mcp_json_path = project_path / ".mcp.json"
    existing = _read_json(mcp_json_path).get("mcpServers", {})
    env_path = project_path / ".env"
    env_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    env_keys = {ln.split("=", 1)[0] for ln in env_lines if "=" in ln and not ln.strip().startswith("#")}

    added: dict[str, dict] = {}
    for name, cfg in servers.items():
        if name in existing:
            continue
        cfg = json.loads(json.dumps(cfg))  # deep copy via round-trip
        for field in ("env", "headers"):
            values = cfg.get(field)
            if not values:
                continue
            for key, val in list(values.items()):
                var = f"{name.upper().replace('-', '_')}_{key}"
                values[key] = f"${{{var}}}"
                if var not in env_keys:
                    env_lines.append(f"{var}={val}")
                    env_keys.add(var)
        existing[name] = cfg
        added[name] = cfg
    if not added:
        return []

    mcp_json_path.write_text(
        json.dumps({"mcpServers": existing}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if env_lines:
        env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    return sorted(added)
