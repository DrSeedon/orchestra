"""Replay only the rejected b8fb cleanup function under the synthetic cancel regression."""
import ast
import hashlib
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[3]
notes = Path(__file__).parent
source = root / 'app/merge_operations.py'
original = source.read_bytes()
fixture = notes / 'unsafe-cleanup-b8fb.py.txt'
tree = ast.parse(original.decode())
node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_clean_worktree_after_merge')
lines = original.decode().splitlines(True)
mutant = (''.join(lines[:node.lineno - 1]) + fixture.read_text() + ''.join(lines[node.end_lineno:])).encode()
log = notes / 'raw/cancellation/committed-mutation.log'
try:
    source.write_bytes(mutant)
    with log.open('wb') as output:
        output.write(('safe_sha256=' + hashlib.sha256(original).hexdigest() + '\n'
                      + 'unsafe_fixture_sha256=' + hashlib.sha256(fixture.read_bytes()).hexdigest() + '\n'
                      + 'rejected_parent_commit=b8fb98bbeb52b44647d493e16530ac8be4dd4679\n').encode())
        output.flush()
        result = subprocess.run(['uv', 'run', '--frozen', 'python', '-m', 'pytest',
            'tests/test_native_cleanup_cancel_v1244.py', '-q', '--tb=short'], cwd=root,
            stdout=output, stderr=subprocess.STDOUT, timeout=60,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    evidence = log.read_text()
    assert result.returncode == 1, result.returncode
    assert "['publish43', 'thread_exit']" in evidence and '4 failed' in evidence
    print('Rejected cancellation boundary: four order regressions red; actual publication preceded thread exit')
finally:
    source.write_bytes(original)
assert source.read_bytes() == original
print('Safe source restored byte-for-byte')
