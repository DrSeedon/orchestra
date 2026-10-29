"""Cgroup fixtures isolate live runner state and direct writes between tests."""
import os

import pytest

from app.agent_cgroups import agent_process_options
from tests.conftest import _AGENT_CGROUP_VARS, _restore_agent_cgroup_env


def test_a_test_leaves_cgroup_vars_set_directly():
    for name in _AGENT_CGROUP_VARS:
        os.environ[name] = "leak"


def test_b_next_test_starts_without_live_or_previous_test_state():
    assert all(name not in os.environ for name in _AGENT_CGROUP_VARS)


def test_inherited_required_state_is_isolated_and_restored(monkeypatch):
    inherited = {
        "ORCHESTRA_AGENT_CGROUP_REQUIRED": "1",
        "ORCHESTRA_AGENT_ROOT": "/unavailable-test-root",
        "ORCHESTRA_AGENT_JOB_CGROUP": "/unavailable-test-root/jobs",
    }
    for name, value in inherited.items():
        monkeypatch.setenv(name, value)
    fixture = _restore_agent_cgroup_env.__wrapped__()
    next(fixture)
    try:
        assert all(name not in os.environ for name in _AGENT_CGROUP_VARS)
        assert "preexec_fn" in agent_process_options()
        os.environ["ORCHESTRA_AGENT_CGROUP_REQUIRED"] = "test-direct-write"
        os.environ["ORCHESTRA_AGENT_CGROUP"] = "/test-direct-write"
    finally:
        with pytest.raises(StopIteration):
            next(fixture)
    assert {name: os.environ.get(name) for name in _AGENT_CGROUP_VARS} == {
        name: inherited.get(name) for name in _AGENT_CGROUP_VARS
    }


def test_explicit_required_group_still_refuses_provider_launch(monkeypatch):
    monkeypatch.delenv("ORCHESTRA_AGENT_CGROUP", raising=False)
    monkeypatch.setenv("ORCHESTRA_AGENT_CGROUP_REQUIRED", "1")
    with pytest.raises(RuntimeError, match="delegated agent cgroup is unavailable"):
        agent_process_options()
