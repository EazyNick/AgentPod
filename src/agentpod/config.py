"""Runtime configuration — per-container resource limits (BUILD-GUIDE §4.12).

Autonomous agents run with --dangerously-skip-permissions, so a runaway task
could exhaust host RAM/CPU/PIDs. These caps bound the blast radius. Defaults
apply to every container; override per-host via env, or per-run via CLI flags.
Set an env var to empty to disable that particular limit.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MEMORY = "4g"       # docker --memory
DEFAULT_CPUS = "2"          # docker --cpus
DEFAULT_PIDS_LIMIT = 512    # docker --pids-limit


@dataclass(frozen=True)
class Resources:
    memory: str | None
    cpus: str | None
    pids_limit: int | None


def _env(name: str, default: str) -> str | None:
    """Return the env value, or default if unset. Empty string disables (None)."""
    v = os.environ.get(name, default)
    return v if v else None


def _int_or_none(v: str | None) -> int | None:
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def resource_limits() -> Resources:
    """Host-level defaults, overridable via AGENT_MEMORY / AGENT_CPUS / AGENT_PIDS_LIMIT."""
    return Resources(
        memory=_env("AGENT_MEMORY", DEFAULT_MEMORY),
        cpus=_env("AGENT_CPUS", DEFAULT_CPUS),
        pids_limit=_int_or_none(_env("AGENT_PIDS_LIMIT", str(DEFAULT_PIDS_LIMIT))),
    )


def merge(base: Resources, memory: str | None, cpus: str | None, pids: int | None) -> Resources:
    """Overlay explicit (CLI) values on top of base; None means 'keep base'."""
    return Resources(
        memory=memory if memory is not None else base.memory,
        cpus=cpus if cpus is not None else base.cpus,
        pids_limit=pids if pids is not None else base.pids_limit,
    )
