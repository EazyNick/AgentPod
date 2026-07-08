"""Deterministic container/project naming from a filesystem path (BUILD-GUIDE §4.3)."""
from __future__ import annotations

import hashlib
import os
import re

_INVALID = re.compile(r"[^a-z0-9]+")


def normalize_basename(name: str) -> str:
    """Lowercase, collapse non-[a-z0-9] runs to a single hyphen, trim edges."""
    slug = _INVALID.sub("-", name.lower())
    return slug.strip("-")


def project_id(path: str) -> str:
    """<normalized-basename>-<sha256(realpath)[:12]>. Stable per canonical path."""
    real = os.path.realpath(path)
    base = normalize_basename(os.path.basename(real)) or "project"
    digest = hashlib.sha256(real.encode()).hexdigest()[:12]
    return f"{base}-{digest}"


def container_name(project_id: str, profile: str | None = None) -> str:
    """agent-<projectId>[--p--<profile>]. Same suffix scheme as lock_prefix."""
    return "agent-" + lock_prefix(project_id, profile)


def lock_prefix(project_id: str, profile: str | None = None) -> str:
    """Reference-counting key. Profiles get a --p-- suffix."""
    if profile:
        return f"{project_id}--p--{profile}"
    return project_id
