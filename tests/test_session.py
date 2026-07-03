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
