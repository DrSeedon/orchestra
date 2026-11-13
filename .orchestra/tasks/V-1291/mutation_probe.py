"""Prove the positive regression fails when only the new event branch is disabled."""

from pathlib import Path

import pytest

from app import error_watch as watch


def main() -> None:
    path = Path(watch.__file__).resolve()
    source = path.read_text()
    condition = 'and event.get("tool_name") == "read_file"'
    assert source.count(condition) == 1
    mutated = source.replace(condition, 'and event.get("tool_name") == "__disabled_v1291__"')
    # Mutate this process only. Source files, DB collection, aggregation, scan
    # and post-fix code otherwise remain unchanged.
    exec(compile(mutated, str(path), "exec"), watch.__dict__)
    result = pytest.main([
        "tests/test_error_watch.py::test_v1291_db_scan_separates_missing_reads_from_legacy_error_banners",
        "-q",
    ])
    assert result == pytest.ExitCode.TESTS_FAILED, result
    print("EXPECTED_FAILURE_CONFIRMED: disabling only the new branch breaks the positive regression")


if __name__ == "__main__":
    main()
