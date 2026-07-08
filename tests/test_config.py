from agentpod import config


def test_defaults(monkeypatch):
    for k in ("AGENT_MEMORY", "AGENT_CPUS", "AGENT_PIDS_LIMIT"):
        monkeypatch.delenv(k, raising=False)
    r = config.resource_limits()
    assert r.memory == config.DEFAULT_MEMORY
    assert r.cpus == config.DEFAULT_CPUS
    assert r.pids_limit == config.DEFAULT_PIDS_LIMIT


def test_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_MEMORY", "8g")
    monkeypatch.setenv("AGENT_CPUS", "4")
    monkeypatch.setenv("AGENT_PIDS_LIMIT", "1024")
    r = config.resource_limits()
    assert (r.memory, r.cpus, r.pids_limit) == ("8g", "4", 1024)


def test_empty_env_disables(monkeypatch):
    monkeypatch.setenv("AGENT_MEMORY", "")
    monkeypatch.setenv("AGENT_PIDS_LIMIT", "")
    r = config.resource_limits()
    assert r.memory is None
    assert r.pids_limit is None


def test_bad_pids_is_none(monkeypatch):
    monkeypatch.setenv("AGENT_PIDS_LIMIT", "notanint")
    assert config.resource_limits().pids_limit is None


def test_merge_overlays_cli_over_base():
    base = config.Resources(memory="4g", cpus="2", pids_limit=512)
    merged = config.merge(base, memory="8g", cpus=None, pids=None)
    assert merged.memory == "8g"      # CLI override
    assert merged.cpus == "2"          # kept from base
    assert merged.pids_limit == 512    # kept from base
