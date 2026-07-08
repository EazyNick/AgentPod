"""Tests for the container-side skills installer (docker/agent-skills.py).

The script is self-contained (runs inside the image without the agentpod
package), so we load it by path and test its pure resolution/parsing logic.
"""
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "docker" / "agent-skills.py"


@pytest.fixture(scope="module")
def skills():
    spec = importlib.util.spec_from_file_location("agent_skills", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_normalize_source_strips_prefixes(skills):
    assert skills.normalize_source("github:obra/superpowers") == "obra/superpowers"
    assert skills.normalize_source("obra/superpowers") == "obra/superpowers"
    assert skills.normalize_source("https://github.com/obra/superpowers.git") == "obra/superpowers"
    assert skills.normalize_source(None) is None


def test_resolve_name_only_uses_catalog(skills):
    r = skills.resolve({"name": "superpowers"})
    assert r == {"name": "superpowers", "source": "obra/superpowers", "marketplace": "superpowers-dev"}


def test_resolve_custom_source(skills):
    r = skills.resolve({"name": "foo", "source": "github:me/foo", "marketplace_name": "foo-mkt"})
    assert r == {"name": "foo", "source": "me/foo", "marketplace": "foo-mkt"}


def test_resolve_disabled_and_nameless(skills):
    assert skills.resolve({"name": "x", "enabled": False}) is None
    assert skills.resolve({"source": "me/x"}) is None


def test_load_manifest_reads_both_files(skills, tmp_path):
    (tmp_path / "agent.toml").write_text('[[skills]]\nname = "superpowers"\n')
    (tmp_path / "skills.toml").write_text('[[skills]]\nname = "foo"\nsource = "me/foo"\n')
    entries = skills.load_manifest(str(tmp_path))
    names = {e["name"] for e in entries}
    assert names == {"superpowers", "foo"}


def test_load_manifest_empty_when_absent(skills, tmp_path):
    assert skills.load_manifest(str(tmp_path)) == []
