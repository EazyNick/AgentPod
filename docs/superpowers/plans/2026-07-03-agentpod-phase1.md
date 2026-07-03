# AgentPod Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Python `agentpod` CLI that spawns one isolated Docker container per project and runs Claude Code inside it, with deterministic naming, session-counted auto-cleanup, credential isolation, and per-container MD context.

**Architecture:** A host-side Python orchestrator (Typer CLI) drives the `docker` CLI via `subprocess`. Each project maps to a deterministically-named long-lived container (`sleep infinity` as PID 1); the `claude` tool attaches via `docker exec -it`. Session lockfiles with PID-based reference counting stop the container when the last session leaves. Per-container `.md` context is bind-mounted and auto-injected into Claude's user memory.

**Tech Stack:** Python 3.12+, Typer, pytest, Docker CLI, Ubuntu 24.04 image with Node.js + `@anthropic-ai/claude-code`.

## Global Constraints

- Python 3.12+ (`requires-python = ">=3.12"`).
- `src/` package layout; package name `agentpod`; console entry point `agentpod`.
- Docker control via `subprocess` calling the `docker` CLI only. No docker SDK dependency.
- Host target is WSL2/Linux + Docker. POSIX-clean code (`os.kill`, `signal`, `~` expansion).
- App data root is `$AGENT_HOME` or `~/.agent`. Never touch the human's `~/.claude`.
- Container credential mount: host `~/.agent/claude` → container `/home/agent/.claude` (rw).
- Deterministic container name: `agent-<projectId>` where `projectId = <normalized-basename>-<sha256(realpath)[:12]>`.
- No `docker.sock` mount, no `--network host`, no host gitconfig/ssh mount, no Chromium (Phase 2).
- Autonomy flag `--dangerously-skip-permissions` runs **only inside the container**, never on the host.
- TDD: write the failing test first for every pure-logic unit. Frequent commits.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/agentpod/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: installable `agentpod` package, `agentpod.__version__`, console script `agentpod = "agentpod.cli:app"` (the `app` symbol is created in Task 9; the entry point is declared now but only resolves after Task 9).

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agentpod"
version = "0.1.0"
description = "Docker-isolated autonomous AI coding agent containers"
requires-python = ">=3.12"
readme = "README.md"
license = { text = "MIT" }
dependencies = ["typer>=0.12"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
agentpod = "agentpod.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/agentpod"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
markers = ["integration: requires a running Docker daemon (deselect with -m 'not integration')"]
```

- [ ] **Step 2: Create package and test init files**

`src/agentpod/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/__init__.py`:
```python
```

`tests/conftest.py`:
```python
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
```

- [ ] **Step 3: Create `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
*.egg-info/
build/
dist/
.venv/
venv/
.env
```

- [ ] **Step 4: Verify pytest collects an empty suite**

Run: `cd "c:/Users/user/Downloads/Project/AgentPod" && python -m pytest -q`
Expected: `no tests ran` (exit 5) — confirms pytest and pythonpath are wired.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/agentpod/__init__.py tests/__init__.py tests/conftest.py .gitignore
git commit -m "chore: scaffold agentpod package"
```

---

### Task 2: Deterministic naming (`naming.py`)

**Files:**
- Create: `src/agentpod/naming.py`
- Test: `tests/test_naming.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `normalize_basename(path: str) -> str`
  - `project_id(path: str) -> str`
  - `container_name(project_id: str) -> str`
  - `lock_prefix(project_id: str, profile: str | None = None) -> str`

- [ ] **Step 1: Write the failing test**

`tests/test_naming.py`:
```python
import hashlib
import os

from agentpod import naming


def test_normalize_basename_lowercases_and_replaces():
    assert naming.normalize_basename("My_Cool Project!") == "my-cool-project"
    assert naming.normalize_basename("a---b") == "a-b"
    assert naming.normalize_basename("---trim---") == "trim"


def test_project_id_is_deterministic_and_hashed(tmp_path):
    d = tmp_path / "MyRepo"
    d.mkdir()
    pid1 = naming.project_id(str(d))
    pid2 = naming.project_id(str(d))
    assert pid1 == pid2
    expected_hash = hashlib.sha256(os.path.realpath(str(d)).encode()).hexdigest()[:12]
    assert pid1 == f"myrepo-{expected_hash}"


def test_different_paths_differ(tmp_path):
    a = tmp_path / "repo"
    b = tmp_path / "other"
    a.mkdir()
    b.mkdir()
    assert naming.project_id(str(a)) != naming.project_id(str(b))


def test_container_name_prefixes():
    assert naming.container_name("myrepo-abc123def456") == "agent-myrepo-abc123def456"


def test_lock_prefix_with_and_without_profile():
    assert naming.lock_prefix("myrepo-abc") == "myrepo-abc"
    assert naming.lock_prefix("myrepo-abc", "bot") == "myrepo-abc--p--bot"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_naming.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentpod.naming'`

- [ ] **Step 3: Write minimal implementation**

`src/agentpod/naming.py`:
```python
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


def container_name(project_id: str) -> str:
    return f"agent-{project_id}"


def lock_prefix(project_id: str, profile: str | None = None) -> str:
    """Reference-counting key. Profiles (Phase 2) get a --p-- suffix."""
    if profile:
        return f"{project_id}--p--{profile}"
    return project_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_naming.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agentpod/naming.py tests/test_naming.py
git commit -m "feat: deterministic project/container naming"
```

---

### Task 3: App data layout (`paths.py`)

**Files:**
- Create: `src/agentpod/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `agent_root() -> Path`
  - `claude_creds_dir() -> Path`
  - `claude_json_path() -> Path`
  - `contexts_dir() -> Path`
  - `context_dir(project_id: str) -> Path`
  - `locks_dir() -> Path`
  - `ensure_layout() -> None`

- [ ] **Step 1: Write the failing test**

`tests/test_paths.py`:
```python
from pathlib import Path

from agentpod import paths


def test_agent_root_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "custom"))
    assert paths.agent_root() == tmp_path / "custom"


def test_agent_root_defaults_to_home(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.agent_root() == tmp_path / ".agent"


def test_ensure_layout_creates_dirs_and_claude_json(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    paths.ensure_layout()
    assert paths.claude_creds_dir().is_dir()
    assert paths.contexts_dir().is_dir()
    assert paths.locks_dir().is_dir()
    assert paths.claude_json_path().is_file()


def test_ensure_layout_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    paths.ensure_layout()
    paths.claude_json_path().write_text('{"k": 1}')
    paths.ensure_layout()  # must not clobber existing content
    assert paths.claude_json_path().read_text() == '{"k": 1}'


def test_context_dir_matches_project_id(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    assert paths.context_dir("myrepo-abc") == tmp_path / "root" / "contexts" / "myrepo-abc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentpod.paths'`

- [ ] **Step 3: Write minimal implementation**

`src/agentpod/paths.py`:
```python
"""Host-side ~/.agent data layout (BUILD-GUIDE §3.1)."""
from __future__ import annotations

import os
from pathlib import Path


def agent_root() -> Path:
    env = os.environ.get("AGENT_HOME")
    if env:
        return Path(env)
    return Path.home() / ".agent"


def claude_creds_dir() -> Path:
    return agent_root() / "claude"


def claude_json_path() -> Path:
    return agent_root() / "claude.json"


def contexts_dir() -> Path:
    return agent_root() / "contexts"


def context_dir(project_id: str) -> Path:
    return contexts_dir() / project_id


def locks_dir() -> Path:
    return agent_root() / "locks"


def ensure_layout() -> None:
    """Create the data layout. Idempotent; never clobbers existing files."""
    for d in (claude_creds_dir(), contexts_dir(), locks_dir()):
        d.mkdir(parents=True, exist_ok=True)
    cj = claude_json_path()
    if not cj.exists():
        cj.write_text("{}\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_paths.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agentpod/paths.py tests/test_paths.py
git commit -m "feat: ~/.agent data layout helpers"
```

---

### Task 4: Tool registry (`registry.py`)

**Files:**
- Create: `src/agentpod/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `paths.claude_creds_dir()`.
- Produces:
  - `ToolDefinition` dataclass with fields: `name: str`, `binary: str`, `default_flags: list[str]`, `install_command: list[str]`, `update_command: list[str]`, `credential_mounts: list[tuple[str, str]]`
  - `REGISTRY: dict[str, ToolDefinition]`
  - `DEFAULT_TOOL: str = "claude"`
  - `get_tool(name: str) -> ToolDefinition`

- [ ] **Step 1: Write the failing test**

`tests/test_registry.py`:
```python
import pytest

from agentpod import registry


def test_default_tool_is_claude():
    assert registry.DEFAULT_TOOL == "claude"
    assert "claude" in registry.REGISTRY


def test_claude_definition_shape():
    claude = registry.get_tool("claude")
    assert claude.name == "claude"
    assert claude.binary == "claude"
    assert "--dangerously-skip-permissions" in claude.default_flags
    assert claude.credential_mounts  # non-empty
    host, container = claude.credential_mounts[0]
    assert container == "/home/agent/.claude"


def test_get_tool_unknown_raises():
    with pytest.raises(KeyError):
        registry.get_tool("nope")


def test_definition_is_frozen():
    claude = registry.get_tool("claude")
    with pytest.raises(Exception):
        claude.name = "x"  # frozen dataclass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentpod.registry'`

- [ ] **Step 3: Write minimal implementation**

`src/agentpod/registry.py`:
```python
"""Multi-tool registry (BUILD-GUIDE §4.10). Phase 1 ships only claude."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import paths


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    binary: str
    default_flags: list[str]
    install_command: list[str]
    update_command: list[str]
    credential_mounts: list[tuple[str, str]] = field(default_factory=list)


def _claude() -> ToolDefinition:
    return ToolDefinition(
        name="claude",
        binary="claude",
        default_flags=["--dangerously-skip-permissions"],
        install_command=["npm", "install", "-g", "@anthropic-ai/claude-code"],
        update_command=["npm", "update", "-g", "@anthropic-ai/claude-code"],
        credential_mounts=[(str(paths.claude_creds_dir()), "/home/agent/.claude")],
    )


REGISTRY: dict[str, ToolDefinition] = {"claude": _claude()}
DEFAULT_TOOL = "claude"


def get_tool(name: str) -> ToolDefinition:
    return REGISTRY[name]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_registry.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agentpod/registry.py tests/test_registry.py
git commit -m "feat: minimal claude tool registry"
```

---

### Task 5: Context resolution (`context.py`)

**Files:**
- Create: `src/agentpod/context.py`
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: `paths.context_dir(project_id)`.
- Produces:
  - `CONTAINER_CONTEXT_PATH: str = "/home/agent/context"`
  - `resolve_mount(project_id: str) -> tuple[str, str] | None`

- [ ] **Step 1: Write the failing test**

`tests/test_context.py`:
```python
from agentpod import context


def test_resolve_mount_none_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    assert context.resolve_mount("myrepo-abc") is None


def test_resolve_mount_present(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    ctx = tmp_path / "root" / "contexts" / "myrepo-abc"
    ctx.mkdir(parents=True)
    host, container = context.resolve_mount("myrepo-abc")
    assert host == str(ctx)
    assert container == context.CONTAINER_CONTEXT_PATH
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentpod.context'`

- [ ] **Step 3: Write minimal implementation**

`src/agentpod/context.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_context.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agentpod/context.py tests/test_context.py
git commit -m "feat: per-container MD context resolution"
```

---

### Task 6: Session lifecycle (`session.py`)

**Files:**
- Create: `src/agentpod/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `paths.locks_dir()`.
- Produces:
  - `pid_alive(pid: int) -> bool`
  - `new_session_id() -> str`
  - `lock_path(prefix: str, session_id: str) -> Path`
  - `parse_lock_name(filename: str) -> tuple[str, str] | None`
  - `create_lock(prefix: str, session_id: str) -> Path`
  - `active_sessions(prefix: str) -> list[Path]`  (sweeps stale locks as a side effect)
  - `release_lock(lock: Path, prefix: str, on_last: Callable[[], None]) -> None`
  - `install_signal_handlers(cleanup: Callable[[], None]) -> None`

- [ ] **Step 1: Write the failing test**

`tests/test_session.py`:
```python
import os

import pytest

from agentpod import session


def test_parse_lock_name_roundtrip():
    assert session.parse_lock_name("myrepo-abc--deadbeef.lock") == ("myrepo-abc", "deadbeef")
    # profile prefix contains --p--; session id is the final --segment
    assert session.parse_lock_name("myrepo-abc--p--bot--feed01.lock") == (
        "myrepo-abc--p--bot",
        "feed01",
    )
    assert session.parse_lock_name("garbage.txt") is None


def test_pid_alive_true_for_self():
    assert session.pid_alive(os.getpid()) is True


def test_pid_alive_false_for_dead(monkeypatch):
    def fake_kill(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(session.os, "kill", fake_kill)
    assert session.pid_alive(424242) is False


def test_pid_alive_true_on_permission_error(monkeypatch):
    def fake_kill(pid, sig):
        raise PermissionError

    monkeypatch.setattr(session.os, "kill", fake_kill)
    assert session.pid_alive(1) is True


def test_create_and_active_and_stale_sweep(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths

    paths.ensure_layout()

    live = session.create_lock("proj-abc", "alive1")
    live.write_text(str(os.getpid()))
    dead = session.create_lock("proj-abc", "dead1")
    dead.write_text("424242")

    monkeypatch.setattr(
        session, "pid_alive", lambda pid: pid == os.getpid()
    )

    active = session.active_sessions("proj-abc")
    assert live in active
    assert dead not in active
    assert not dead.exists()  # stale lock swept


def test_release_calls_on_last_when_no_active(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths

    paths.ensure_layout()
    lock = session.create_lock("proj-abc", "only")
    lock.write_text(str(os.getpid()))
    monkeypatch.setattr(session, "pid_alive", lambda pid: True)

    called = []
    session.release_lock(lock, "proj-abc", lambda: called.append(True))
    assert called == [True]
    assert not lock.exists()


def test_release_skips_on_last_when_others_active(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths

    paths.ensure_layout()
    mine = session.create_lock("proj-abc", "mine")
    mine.write_text(str(os.getpid()))
    other = session.create_lock("proj-abc", "other")
    other.write_text(str(os.getpid()))
    monkeypatch.setattr(session, "pid_alive", lambda pid: True)

    called = []
    session.release_lock(mine, "proj-abc", lambda: called.append(True))
    assert called == []  # other still active
    assert not mine.exists()
    assert other.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_session.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentpod.session'`

- [ ] **Step 3: Write minimal implementation**

`src/agentpod/session.py`:
```python
"""Session lockfiles + reference counting + crash recovery (BUILD-GUIDE §4.3)."""
from __future__ import annotations

import atexit
import os
import signal
import uuid
from pathlib import Path
from typing import Callable

from . import paths

_SUFFIX = ".lock"


def pid_alive(pid: int) -> bool:
    """os.kill(pid, 0): success/PermissionError => alive, ProcessLookupError => dead."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def lock_path(prefix: str, session_id: str) -> Path:
    return paths.locks_dir() / f"{prefix}--{session_id}{_SUFFIX}"


def parse_lock_name(filename: str) -> tuple[str, str] | None:
    """Split '<prefix>--<sessionId>.lock' on the LAST '--'. Session ids have no '--'."""
    if not filename.endswith(_SUFFIX):
        return None
    stem = filename[: -len(_SUFFIX)]
    if "--" not in stem:
        return None
    prefix, session_id = stem.rsplit("--", 1)
    if not prefix or not session_id:
        return None
    return prefix, session_id


def create_lock(prefix: str, session_id: str) -> Path:
    lp = lock_path(prefix, session_id)
    lp.write_text(str(os.getpid()))
    return lp


def active_sessions(prefix: str) -> list[Path]:
    """Live locks for prefix. Deletes stale (dead-PID) locks as a side effect."""
    result: list[Path] = []
    ldir = paths.locks_dir()
    if not ldir.is_dir():
        return result
    for lock in ldir.glob(f"*{_SUFFIX}"):
        parsed = parse_lock_name(lock.name)
        if parsed is None or parsed[0] != prefix:
            continue
        try:
            pid = int(lock.read_text().strip())
        except (ValueError, OSError):
            lock.unlink(missing_ok=True)
            continue
        if pid_alive(pid):
            result.append(lock)
        else:
            lock.unlink(missing_ok=True)
    return result


def release_lock(lock: Path, prefix: str, on_last: Callable[[], None]) -> None:
    """Delete my lock; if no other live session for prefix remains, call on_last()."""
    lock.unlink(missing_ok=True)
    if not active_sessions(prefix):
        on_last()


def install_signal_handlers(cleanup: Callable[[], None]) -> None:
    done = {"cleaned": False}

    def _run() -> None:
        if done["cleaned"]:
            return
        done["cleaned"] = True
        cleanup()

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, lambda *_: (_run(), os._exit(130)))
        except (ValueError, OSError):
            pass  # e.g. not in main thread / unsupported signal
    atexit.register(_run)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_session.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agentpod/session.py tests/test_session.py
git commit -m "feat: session lockfiles with refcount and crash recovery"
```

---

### Task 7: Docker control (`docker_ctl.py`)

**Files:**
- Create: `src/agentpod/docker_ctl.py`
- Test: `tests/test_docker_ctl.py`

**Interfaces:**
- Consumes: nothing (shells out to `docker`).
- Produces:
  - `Mount` dataclass: `host: str`, `container: str`, `ro: bool = False`, with `.to_arg() -> str`
  - `docker_available() -> bool`
  - `image_exists(tag: str) -> bool`
  - `build_image(dockerfile: Path, context_dir: Path, tag: str) -> None`
  - `container_state(name: str) -> str | None`
  - `run_detached(name, image, mounts: list[Mount], workdir: str, env_file: str | None) -> None`
  - `start(name: str) -> None`
  - `exec_interactive(name: str, cmd: list[str]) -> int`
  - `stop(name: str) -> None`
  - `remove(name: str) -> None`
  - `list_agents() -> list[dict]`

- [ ] **Step 1: Write the failing test**

`tests/test_docker_ctl.py`:
```python
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
        lambda args, **kw: captured.setdefault("args", args) or subprocess.CompletedProcess(args, 0, "", ""),
    )
    docker_ctl.run_detached("agent-x", "img", [], "/w", None)
    assert "--env-file" not in captured["args"]


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_docker_ctl.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentpod.docker_ctl'`

- [ ] **Step 3: Write minimal implementation**

`src/agentpod/docker_ctl.py`:
```python
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
) -> None:
    args = ["docker", "run", "-d", "--name", name, "-w", workdir]
    if env_file:
        args += ["--env-file", env_file]
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_docker_ctl.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agentpod/docker_ctl.py tests/test_docker_ctl.py
git commit -m "feat: docker CLI subprocess wrappers"
```

---

### Task 8: Container image (`Dockerfile` + entrypoint)

**Files:**
- Create: `Dockerfile`
- Create: `docker/agent-entrypoint.sh`

**Interfaces:**
- Consumes: nothing (built by `docker_ctl.build_image`).
- Produces: image `agentpod:latest` with user `agent` (uid 1000), Node.js, `claude` CLI on PATH, entrypoint that injects MD context and execs `sleep infinity`.

- [ ] **Step 1: Create the entrypoint script**

`docker/agent-entrypoint.sh`:
```bash
#!/bin/bash
set -euo pipefail

# 1. Git: allow operating on the bind-mounted project regardless of owner.
#    (Dedicated bot identity is Phase 2.)
git config --global --add safe.directory '*' || true

# 2. Auto-inject per-container MD context into Claude's user memory (§4.11).
#    Never touches the user's repo — only ~/.claude/CLAUDE.md.
CTX="/home/agent/context/CLAUDE.md"
MEM_DIR="/home/agent/.claude"
MEM="$MEM_DIR/CLAUDE.md"
LINE="@/home/agent/context/CLAUDE.md"
if [ -f "$CTX" ]; then
  mkdir -p "$MEM_DIR"
  touch "$MEM"
  grep -qxF "$LINE" "$MEM" || echo "$LINE" >> "$MEM"
fi

# 3. Hand off to the container command (default: sleep infinity keep-alive).
exec "$@"
```

- [ ] **Step 2: Create the Dockerfile**

`Dockerfile`:
```dockerfile
# AgentPod agent container (BUILD-GUIDE §4.1, Phase 1 slim variant).
FROM ubuntu:24.04

# LAYER 1 (rarely changes): base deps, locales, tzdata
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl git ca-certificates unzip locales tzdata \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*
ENV LANG=en_US.UTF-8 LANGUAGE=en_US:en LC_ALL=en_US.UTF-8

# LAYER 2 (occasionally): Node.js (for claude CLI + npx-based MCP later)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# LAYER 3 (occasionally): non-root agent user (uid 1000) + home
RUN useradd -m -u 1000 -s /bin/bash agent \
    && mkdir -p /home/agent/.claude /home/agent/context /project \
    && chown -R agent:agent /home/agent /project

# LAYER 4 (occasionally): claude CLI installed globally
RUN npm install -g @anthropic-ai/claude-code

# LAYER 5 (frequently): entrypoint
COPY docker/agent-entrypoint.sh /usr/local/bin/agent-entrypoint.sh
RUN chmod +x /usr/local/bin/agent-entrypoint.sh

USER agent
WORKDIR /project
ENTRYPOINT ["/usr/local/bin/agent-entrypoint.sh"]
CMD ["sleep", "infinity"]
```

- [ ] **Step 3: Build the image to verify it succeeds**

Run: `cd "c:/Users/user/Downloads/Project/AgentPod" && docker build -f Dockerfile -t agentpod:latest .`
Expected: build completes; final line `naming to docker.io/library/agentpod:latest done` (or equivalent success).

- [ ] **Step 4: Smoke-test the image**

Run: `docker run --rm agentpod:latest bash -lc "node --version && claude --version && whoami"`
Expected: prints a Node version, a claude version string, and `agent`.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker/agent-entrypoint.sh
git commit -m "feat: agent container image + entrypoint with MD injection"
```

---

### Task 9: CLI wiring (`cli.py`)

**Files:**
- Create: `src/agentpod/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `naming`, `paths`, `registry`, `context`, `session`, `docker_ctl`, `Mount`.
- Produces:
  - `app: typer.Typer`
  - `IMAGE_TAG: str = "agentpod:latest"`
  - `resolve_target(target: str) -> tuple[str, str]`  (returns `(project_id, container_name)`; `"."` or `""` = cwd)
  - `build_mounts(project_id: str, project_path: str) -> list[docker_ctl.Mount]`
  - `ensure_container(project_id: str, project_path: str) -> str`  (spawns/starts, returns container name)
  - commands: `build`, `run`, `shell`, `status`, `stop`, `rm`, `context`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
import os

from agentpod import cli
from agentpod.docker_ctl import Mount


def test_resolve_target_cwd(monkeypatch, tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    monkeypatch.chdir(d)
    from agentpod import naming

    pid, cname = cli.resolve_target(".")
    assert pid == naming.project_id(str(d))
    assert cname == f"agent-{pid}"


def test_build_mounts_includes_core_and_context(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths

    paths.ensure_layout()
    project_path = str(tmp_path / "repo")
    # create a context dir for this project id
    pid = "repo-abc"
    (tmp_path / "root" / "contexts" / pid).mkdir(parents=True)

    mounts = cli.build_mounts(pid, project_path)
    containers = {m.container for m in mounts}
    assert f"/project/{pid}" in containers
    assert "/home/agent/.claude" in containers
    assert "/home/agent/.claude.json" in containers
    assert "/home/agent/context" in containers
    # context mount is read-only
    ctx = next(m for m in mounts if m.container == "/home/agent/context")
    assert ctx.ro is True


def test_build_mounts_omits_context_when_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "root"))
    from agentpod import paths

    paths.ensure_layout()
    mounts = cli.build_mounts("repo-none", str(tmp_path / "repo"))
    assert all(m.container != "/home/agent/context" for m in mounts)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentpod.cli'`

- [ ] **Step 3: Write minimal implementation**

`src/agentpod/cli.py`:
```python
"""AgentPod CLI — spawn and drive per-project agent containers (BUILD-GUIDE §5)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import typer

from . import context, docker_ctl, naming, paths, registry, session
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
    ctx = context.resolve_mount(project_id)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full unit suite (excluding integration)**

Run: `python -m pytest -m "not integration" -q`
Expected: all tests pass (Tasks 2–9).

- [ ] **Step 6: Commit**

```bash
git add src/agentpod/cli.py tests/test_cli.py
git commit -m "feat: agentpod CLI (build/run/shell/status/stop/rm/context)"
```

---

### Task 10: End-to-end verification + docs

**Files:**
- Modify: `README.md`
- Create: `.env.example`

**Interfaces:**
- Consumes: the installed `agentpod` CLI.
- Produces: user-facing usage docs; a committed `.env.example` key manifest.

- [ ] **Step 1: Create `.env.example`**

`.env.example`:
```dotenv
# Secrets for the agent container. Copy to .env (gitignored) and fill in.
# If ANTHROPIC_API_KEY is set it is used; otherwise run `agentpod shell` once
# and `claude login` interactively — the login persists via the bind mount.
ANTHROPIC_API_KEY=
# Phase 2: GITHUB_TOKEN=
```

- [ ] **Step 2: Rewrite `README.md`**

`README.md`:
````markdown
# AgentPod

Docker로 격리된 자율 AI 코딩 에이전트 컨테이너. 프로젝트마다 격리된 컨테이너를
하나씩 띄우고 그 안에서 Claude Code를 실행합니다.

> 설계 근거: [BUILD-GUIDE](docs/dev/BUILD-GUIDE.md) · Phase 1 스펙:
> [design](docs/superpowers/specs/2026-07-03-agentpod-phase1-design.md)

## 요구사항

- WSL2/Linux + Docker
- Python 3.12+

## 설치

```bash
pip install -e .
```

## 사용

```bash
agentpod build                 # 에이전트 이미지 빌드 (최초 1회)
cd /path/to/your/project
agentpod run                   # 컨테이너 스폰/재사용 → Claude Code 대화형 실행
agentpod shell                 # 같은 컨테이너에 bash로 접속
agentpod status                # 모든 agent-* 컨테이너 + 활성 세션 수
agentpod stop                  # 이 프로젝트의 컨테이너 stop
agentpod rm                    # stop + remove
agentpod context               # 이 컨테이너의 MD 컨텍스트 폴더 경로
```

## 인증 (둘 다 지원)

- **API 키**: 프로젝트 루트 `.env`에 `ANTHROPIC_API_KEY=...` → 자동 주입.
- **대화형 로그인**: `agentpod shell` 후 `claude login`. `~/.agent/claude` 바인드
  마운트로 영속되어 컨테이너가 죽어도 로그인 유지.

## 컨테이너별 MD 컨텍스트

`agentpod context`가 출력하는 폴더(`~/.agent/contexts/<projectId>/`)에 `CLAUDE.md`와
참고 `.md`를 넣으면, 그 컨테이너의 Claude 세션에 자동으로 반영됩니다. 코드 수정 불필요.

## 개발

```bash
pip install -e ".[dev]"
pytest -m "not integration"
```
````

- [ ] **Step 3: Install and run the full suite**

Run: `cd "c:/Users/user/Downloads/Project/AgentPod" && pip install -e ".[dev]" && python -m pytest -m "not integration" -q`
Expected: install succeeds; all unit tests pass.

- [ ] **Step 4: Manual end-to-end check (requires Docker + WSL2)**

Run these and confirm behavior:
```bash
agentpod build
mkdir -p /tmp/demo-proj && cd /tmp/demo-proj
mkdir -p ~/.agent/contexts/$(python -c "from agentpod import naming; print(naming.project_id('/tmp/demo-proj'))")
echo "# Demo agent instructions" > ~/.agent/contexts/$(python -c "from agentpod import naming; print(naming.project_id('/tmp/demo-proj'))")/CLAUDE.md
agentpod status          # shows nothing running yet
agentpod shell           # should drop into the container; verify: cat ~/.claude/CLAUDE.md shows the @import line, then exit
agentpod status          # container auto-stopped after last session left
```
Expected: `shell` enters the container as `agent`, `~/.claude/CLAUDE.md` contains `@/home/agent/context/CLAUDE.md`, and after exit the container is stopped (session refcount hit zero).

> If `agentpod run` is used with a valid `ANTHROPIC_API_KEY` in `.env` (or after `claude login`), it enters an interactive Claude Code session bound to the project.

- [ ] **Step 5: Commit**

```bash
git add README.md .env.example
git commit -m "docs: usage README and .env.example for Phase 1"
```

---

## Self-Review

**Spec coverage** (against `2026-07-03-agentpod-phase1-design.md`):
- §5.1 naming → Task 2 ✓
- §5.2 paths → Task 3 ✓
- §5.3 docker_ctl (sleep-infinity + exec model) → Task 7 (+ Dockerfile CMD in Task 8) ✓
- §5.4 session (lock/refcount/crash/signals) → Task 6 ✓
- §5.5 registry → Task 4 ✓
- §5.6 context resolve + entrypoint injection → Task 5 + Task 8 ✓
- §5.7 CLI commands (build/run/shell/status/stop/rm/context) → Task 9 ✓
- §5.8 Dockerfile + entrypoint → Task 8 ✓
- §3 host layout (`~/.agent`, claude.json) → Task 3 ✓
- §4 container layout (mounts) → Task 9 `build_mounts` ✓
- Auth both ways (.env + bind mount) → Task 9 (env_file + creds mount) + Task 10 docs ✓
- §8 tests → Tasks 2–9 unit tests ✓
- §9 DoD → Task 10 E2E check ✓

**Placeholder scan:** No TBD/TODO; every code step contains full code. ✓

**Type consistency:** `Mount(host, container, ro)` used identically in Tasks 7 & 9; `resolve_mount -> tuple|None` consumed correctly in Task 9; `active_sessions`/`release_lock`/`create_lock` signatures match between Task 6 and Task 9 usage; `project_id`/`container_name`/`lock_prefix` consistent Tasks 2/9. ✓

**Note on `run` extra args:** `agentpod run -- <args>` passes trailing args to the tool via Typer's `list[str]` argument. Autonomy flag stays inside the container command only.
