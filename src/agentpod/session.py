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
