"""Bounded offline mutations against the committed V-1244 host regressions."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess


parser = argparse.ArgumentParser()
parser.add_argument('case', choices=['identity', 'native-positive', 'fixture-loading'])
case = parser.parse_args().case
root = Path(__file__).resolve().parents[3]
notes = Path(__file__).parent
common = ['-q', '--tb=short']
if case == 'identity':
    source = root / 'app/backend_hub.py'
    before = '''                role = getattr(who, "role", "")
                action = hub_completion_action(
                    {"id": getattr(who, "session_id", ""), "name": getattr(who, "name", ""),
                     "branch": getattr(who, "branch", ""), "backend_type": "hub",
                     "is_orchestrator": not role or role in {"orchestrator", "sub-orchestrator"}},'''
    after = '''                action = hub_completion_action(
                    {"id": who.session_id, "name": who.name, "branch": who.branch,
                     "backend_type": "hub", "is_orchestrator": who.role in {"orchestrator", "sub-orchestrator"}},'''
    tests = ['tests/test_hub_completion_directive_v1244.py::test_incomplete_legacy_identity_finishes_sync_without_directive']
    evidence = ['4 failed, 2 passed', 'AttributeError', 'assert actions == [{}]']
elif case == 'native-positive':
    source = root / 'app/merge_operations.py'
    before = 'return clean_worktree(worktree, main_checkout=str(repo), target_ref=target, apply=True)'
    after = 'return {"state": "skipped"}'
    tests = ['tests/test_worktree_cleanup_v984.py::test_successful_merge_cleans_the_worker_copy',
             'tests/test_worktree_cleanup_v984.py::test_failed_merge_does_not_clean']
    evidence = ['1 failed, 1 passed', 'assert calls ==']
else:
    source = root / 'tests/test_hub_cleanup_generation_v1244.py'
    before = ('from tests.test_hub_archive_v1244 import history\n'
              'from tests.test_merge_operations import merge_db')
    after = 'pytest_plugins = ("tests.test_hub_archive_v1244", "tests.test_merge_operations")'
    tests = ['tests/test_hub_archive_v1244.py::test_archive_preserves_objects_and_idempotent_restart',
             'tests/test_hub_cleanup_generation_v1244.py', '-n', '2', '--dist', 'loadscope']
    evidence = ["fixture 'history' not found", '1 passed, 1 error']

original = source.read_bytes()
assert original.decode().count(before) == 1
mutant = original.decode().replace(before, after, 1).encode()
log = notes / 'raw/host-outcomes' / f'mutation-{case}.log'
try:
    source.write_bytes(mutant)
    with log.open('wb') as output:
        output.write(('source=' + str(source.relative_to(root)) + '\n'
                      + 'safe_sha256=' + hashlib.sha256(original).hexdigest() + '\n'
                      + 'mutant_sha256=' + hashlib.sha256(mutant).hexdigest() + '\n').encode())
        output.flush()
        result = subprocess.run(['uv', 'run', '--frozen', 'python', '-m', 'pytest', *tests, *common],
                                cwd=root, stdout=output, stderr=subprocess.STDOUT, timeout=55,
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    observed = log.read_text()
    assert result.returncode == 1, result.returncode
    assert all(marker in observed for marker in evidence), observed[-2500:]
finally:
    source.write_bytes(original)
assert source.read_bytes() == original
print(f'{case}: expected RED; safe source restored byte-for-byte')
