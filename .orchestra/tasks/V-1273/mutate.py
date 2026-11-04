# sanitized-publication-copy
# Private originals: private/tasks/V-1273/originals/ (root-held SHA-256/bytes manifest; not accessed here).

"""Run the committed sequence regression with the pre-fix function in memory."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import pytest
from app import hub_workspace as hw

original = Path(__file__).with_name("commit_sync_before.txt")
exec(compile(original.read_text(), str(original), "exec"), vars(hw))
raise SystemExit(pytest.main([
    *(sys.argv[1:] or ["tests/test_hub_untracked_delete_v1273.py::test_two_imports_after_scanner_guard_commit_survivors"]), "-q",
]))
