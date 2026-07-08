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


def test_container_name_with_profile():
    assert naming.container_name("myrepo-abc", "bot") == "agent-myrepo-abc--p--bot"


def test_lock_prefix_with_and_without_profile():
    assert naming.lock_prefix("myrepo-abc") == "myrepo-abc"
    assert naming.lock_prefix("myrepo-abc", "bot") == "myrepo-abc--p--bot"
