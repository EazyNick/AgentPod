"""Tests for the host-side superpowers plugin seeding (src/agentpod/plugins.py)."""
from agentpod import plugins


def test_seed_skips_when_already_present(tmp_path, monkeypatch):
    marker = tmp_path / "plugins" / "marketplaces" / plugins.MARKETPLACE
    marker.mkdir(parents=True)

    def fail_which(_name):
        raise AssertionError("should not check for claude binary when already seeded")

    monkeypatch.setattr(plugins.shutil, "which", fail_which)
    plugins.seed_superpowers(tmp_path)  # must not raise


def test_seed_skips_when_claude_not_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(plugins.shutil, "which", lambda _name: None)

    def fail_run(*a, **k):
        raise AssertionError("should not invoke subprocess without a claude binary")

    monkeypatch.setattr(plugins.subprocess, "run", fail_run)
    plugins.seed_superpowers(tmp_path)  # must not raise
    assert not (tmp_path / "plugins").exists()


def test_seed_runs_add_install_enable_and_cleans_stray_files(tmp_path, monkeypatch):
    monkeypatch.setattr(plugins.shutil, "which", lambda _name: "/usr/bin/claude")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1:4] == ["plugin", "marketplace", "add"]:
            (tmp_path / "plugins" / "marketplaces" / plugins.MARKETPLACE).mkdir(parents=True)
            (tmp_path / ".claude.json").write_text("{}")
            (tmp_path / "backups").mkdir()
        return None

    monkeypatch.setattr(plugins.subprocess, "run", fake_run)
    plugins.seed_superpowers(tmp_path)

    assert [c[1:] for c in calls] == [
        ["plugin", "marketplace", "add", plugins.MARKETPLACE_SOURCE],
        ["plugin", "install", plugins.PLUGIN],
        ["plugin", "enable", plugins.PLUGIN],
    ]
    assert not (tmp_path / ".claude.json").exists()
    assert not (tmp_path / "backups").exists()
    assert (tmp_path / "plugins" / "marketplaces" / plugins.MARKETPLACE).is_dir()


def test_seed_stops_early_if_a_step_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(plugins.shutil, "which", lambda _name: "/usr/bin/claude")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        raise RuntimeError("boom")

    monkeypatch.setattr(plugins.subprocess, "run", fake_run)
    plugins.seed_superpowers(tmp_path)  # must not raise
    assert len(calls) == 1
