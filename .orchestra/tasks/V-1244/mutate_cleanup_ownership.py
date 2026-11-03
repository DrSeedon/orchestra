"""Replay only the rejected committed cleanup function against the frozen fake probe."""
import ast
import hashlib
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[3]
notes = Path(__file__).parent
source = root / 'app/merge_operations.py'
fixture = notes / 'unsafe-cleanup-50d2.py.txt'
original = source.read_bytes()

def replace_function(current, unsafe):
    tree = ast.parse(current)
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_clean_worktree_after_merge')
    lines = current.splitlines(True)
    return ''.join(lines[:node.lineno - 1]) + unsafe + ''.join(lines[node.end_lineno:])

mutant = replace_function(original.decode(), fixture.read_text()).encode()
log = notes / 'raw/ownership/committed-mutation.log'
try:
    source.write_bytes(mutant)
    with log.open('wb') as output:
        output.write(('safe_sha256=' + hashlib.sha256(original).hexdigest() + '\n'
                      + 'unsafe_fixture_sha256=' + hashlib.sha256(fixture.read_bytes()).hexdigest() + '\n'
                      + 'rejected_parent_commit=50d2b51be5d4a27fe13e7660c747dfd1f37883e3\n').encode())
        output.flush()
        run = subprocess.run(['uv', 'run', '--frozen', 'python', '-m', 'pytest',
            'tests/test_hub_cleanup_generation_v1244.py::test_stale_cleared_task_snapshot_does_not_close_published_generation',
            '-q', '-s', '--tb=short'], cwd=root, stdout=output, stderr=subprocess.STDOUT, timeout=60,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    evidence = log.read_text()
    assert run.returncode == 1, run.returncode
    assert 'thread-task-43' in evidence and '"current_db_task_id": "43"' in evidence
    assert '"local_cleanup_calls": 1' in evidence and '1 failed' in evidence
    print('committed unsafe cleanup: expected red reproduced; current generation43 was touched')
finally:
    source.write_bytes(original)
assert source.read_bytes() == original
print('safe source restored byte-for-byte')
