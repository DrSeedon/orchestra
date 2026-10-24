"""Run regression controls and in-process mutants; never edit production files."""
import subprocess
import sys

PREFIX = "tests/test_hub_file_policy_v1073.py::"
CASES = (
    ("filename protection", "hw._company_path = lambda rel: False",
     [PREFIX + "test_private_filename_never_in_initial_manifest_or_archive"]),
    ("retained history protection",
     "hw.WorkspaceState.assert_file_policy = lambda self: None; "
     "hw.assert_file_policy = lambda *paths: None",
     [PREFIX + "test_stale_history_blocks_turn_even_when_remote_file_is_gone"]),
    ("remote name-only protection",
     "hw.HubSsh.assert_file_policy = AsyncMock()",
     [PREFIX + "test_name_only_remote_check_uses_actual_shell_on_synthetic_files"]),
)


def check(label, mutation, selectors, expected):
    code = (
        "import pytest; from unittest.mock import AsyncMock; "
        "from app import hub_workspace as hw; " + mutation + "; "
        "raise SystemExit(pytest.main(" + repr([*selectors, "-q"]) + "))"
    )
    print(f"\n{label}: {mutation}", flush=True)
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    print(result.stdout, end="", flush=True)
    print(result.stderr, end="", flush=True)
    print(f"exit={result.returncode}, expected={expected}", flush=True)
    if result.returncode != expected:
        raise SystemExit(f"unexpected outcome for {label}")
    if expected == 1 and not any(s in result.stdout for s in ("AssertionError", "DID NOT RAISE")):
        raise SystemExit(f"mutant failed without a regression assertion: {label}")


for label, mutation, selectors in CASES:
    check(label + " control", "pass", selectors, 0)
    check(label + " mutant", mutation, selectors, 1)
print("\nAll three controls passed; all three mutants failed regression assertions.")
