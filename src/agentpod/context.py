"""Per-container MD context mounting (BUILD-GUIDE §4.11). No fallback."""
from __future__ import annotations

from . import paths

CONTAINER_CONTEXT_PATH = "/home/agent/context"


def resolve_mount(project_id: str) -> tuple[str, str] | None:
    """(host_dir, container_path) if the context folder exists, else None."""
    d = paths.context_dir(project_id)
    if d.is_dir():
        return (str(d), CONTAINER_CONTEXT_PATH)
    return None
