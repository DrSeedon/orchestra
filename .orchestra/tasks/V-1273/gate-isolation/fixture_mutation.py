# sanitized-publication-copy
# Prior private originals: private/tasks/V-1273/originals/ (root-held; not accessed).
"""Restore just the old fixture setup in memory; the strict status must fail."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
import pytest
import tests.test_hub_untracked_delete_v1273 as regression

saved = Path(__file__).with_name('integration_before.txt')
exec(compile(saved.read_text(), '<fixture-before>', 'exec'), vars(regression))
real_git = regression._git

def observe_status(root, *args):
    result = real_git(root, *args)
    if args == ('status', '--porcelain'):
        print('Fixture rollback strict status:', repr(result))
    return result

regression._git = observe_status
raise SystemExit(pytest.main([
    'tests/test_hub_untracked_delete_v1273.py::test_two_imports_after_scanner_guard_commit_survivors',
    '-q', '--timeout=120', '--timeout-method=signal',
]))
