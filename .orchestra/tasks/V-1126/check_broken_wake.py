"""Negative control for the transport oracle; expected pytest exit code is 1.

Run with the provisioned uv and normal tests/conftest.py. This disables only
the synthetic backend's transport wake, without editing production source.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


class BrokenWake:
    def pytest_runtest_call(self, item):
        backend = item.funcargs["h"].backend
        item.funcargs["monkeypatch"].setattr(
            backend, "_fail_compact_transport", lambda _error: None,
        )


if __name__ == "__main__":
    sys.exit(pytest.main([
        "tests/test_codex_compact_state.py", "-q",
        "-k", "transport_failure_wakes_every_stage",
        "--tb=short", "--show-capture=no",
        "--basetemp=.orchestra/tasks/V-1126/runtime/pytest",
    ], plugins=[BrokenWake()]))
