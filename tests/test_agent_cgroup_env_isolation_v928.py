"""V-928: direct os.environ writes by one test must not reach the next one."""
import os

_VARS = ("ORCHESTRA_AGENT_CGROUP", "ORCHESTRA_AGENT_ROOT", "ORCHESTRA_AGENT_CGROUP_REQUIRED")
_BASELINE = {name: os.environ.get(name) for name in _VARS}


def test_a_test_leaves_cgroup_vars_set_directly():
    for name in _VARS:
        os.environ[name] = "leak"


def test_b_next_test_sees_the_original_environment():
    assert {name: os.environ.get(name) for name in _VARS} == _BASELINE
