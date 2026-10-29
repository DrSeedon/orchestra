"""Quota admission constants must collect before any database fixture runs."""

from pathlib import Path
import subprocess
import sys
import textwrap


def test_quota_admission_collection_does_not_open_sqlite():
    # A fresh interpreter avoids an already-imported module hiding collection I/O.
    # Audit the actual SQLite boundary rather than replacing quota/DB functions.
    probe = textwrap.dedent("""\
        import sys
        import pytest

        attempts = []

        def forbid_sqlite(event, args):
            if event == "sqlite3.connect":
                attempts.append(event)
                raise AssertionError("SQLite opened during quota admission collection")

        sys.addaudithook(forbid_sqlite)

        class Collected:
            nodeids = []

            def pytest_collection_finish(self, session):
                self.nodeids = [item.nodeid for item in session.items]

        collected = Collected()
        result = pytest.main([
            "--collect-only", "-q", "--tb=no", "-n0", "-o", "addopts=",
            "tests/test_quota_admission_e2e.py",
        ], plugins=[collected])
        assert not attempts, "quota admission collection attempted SQLite I/O"
        assert result == pytest.ExitCode.OK, result
        assert any("test_gated_worker_is_refused_above_the_line[" in nodeid
                   for nodeid in collected.nodeids), collected.nodeids
        assert any("test_gated_worker_is_created_below_the_line[" in nodeid
                   for nodeid in collected.nodeids), collected.nodeids
        """)
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
