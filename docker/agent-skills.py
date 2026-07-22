#!/usr/bin/env python3
"""Install skills/plugins declared in the project manifest (BUILD-GUIDE §4.8).

Reads `agent.toml` (general config) and/or `skills.toml` (skills only) from the
current directory (the mounted project root), and installs each declared skill
via `claude plugin`. Best-effort and idempotent — never fails the container boot.

Manifest schema (either file):

    [[skills]]
    name = "superpowers"                          # required (plugin name)
    source = "github:anthropics/claude-plugins-official"  # optional if name is in the catalog
    marketplace_name = "claude-plugins-official"  # optional; auto-detected from `add` output
    enabled = true                                # optional (default true)

Well-known skills need only `name` (resolved via CATALOG below).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

# name -> (marketplace source repo, registered marketplace name)
CATALOG = {
    "superpowers": ("anthropics/claude-plugins-official", "claude-plugins-official"),
}

MANIFESTS = ("agent.toml", "skills.toml")


def normalize_source(src: str | None) -> str | None:
    """Accept 'github:owner/repo' or 'owner/repo'; return the repo ref for `add`."""
    if not src:
        return None
    for prefix in ("github:", "git+", "https://github.com/"):
        if src.startswith(prefix):
            src = src[len(prefix):]
    return src.removesuffix(".git")


def resolve(entry: dict) -> dict | None:
    """Turn a manifest entry into {name, source, marketplace} or None if skipped."""
    name = entry.get("name")
    if not name or entry.get("enabled") is False:
        return None
    source = normalize_source(entry.get("source") or entry.get("marketplace"))
    marketplace = entry.get("marketplace_name")
    if name in CATALOG:
        cat_source, cat_market = CATALOG[name]
        source = source or cat_source
        marketplace = marketplace or cat_market
    return {"name": name, "source": source, "marketplace": marketplace}


def load_manifest(root: str = ".") -> list[dict]:
    """Collect [[skills]] entries from agent.toml + skills.toml under root."""
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11
        return []
    skills: list[dict] = []
    for fn in MANIFESTS:
        path = os.path.join(root, fn)
        if os.path.isfile(path):
            try:
                with open(path, "rb") as f:
                    skills += tomllib.load(f).get("skills", [])
            except Exception as e:  # noqa: BLE001 - never fail boot
                print(f"[skills] {fn} parse error: {e}")
    return skills


def _installed_list() -> str:
    try:
        return subprocess.run(
            ["claude", "plugin", "list"], capture_output=True, text=True
        ).stdout
    except Exception:  # noqa: BLE001
        return ""


def _add_marketplace(source: str) -> str | None:
    """Add the marketplace; return its registered name if we can detect it."""
    try:
        cp = subprocess.run(
            ["claude", "plugin", "marketplace", "add", source],
            capture_output=True, text=True,
        )
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"marketplace:\s*(\S+)", cp.stdout)
    return m.group(1) if m else None


def install(spec: dict, have: str) -> str:
    name, source, market = spec["name"], spec["source"], spec["marketplace"]
    if f"{name}@" in have and (not market or f"{name}@{market}" in have):
        return f"[skills] {name}: already installed"
    detected = _add_marketplace(source) if source else None
    market = market or detected or name
    target = f"{name}@{market}"
    try:
        cp = subprocess.run(
            ["claude", "plugin", "install", target], capture_output=True, text=True
        )
        ok = cp.returncode == 0 and "Failed" not in (cp.stdout + cp.stderr)
    except Exception:  # noqa: BLE001
        ok = False
    return f"[skills] install {target}: {'ok' if ok else 'skipped'}"


def main() -> None:
    entries = load_manifest(".")
    specs = [s for s in (resolve(e) for e in entries) if s]
    if not specs:
        return
    have = _installed_list()
    for spec in specs:
        print(install(spec, have))


if __name__ == "__main__":  # pragma: no cover
    try:
        main()
    except Exception:  # noqa: BLE001 - never fail the container boot
        sys.exit(0)
