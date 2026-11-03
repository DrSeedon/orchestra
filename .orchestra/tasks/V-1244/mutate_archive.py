"""Offline mutation: route ordinary archive to destructive purge; survival must fail."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[3]
source = root / 'app/hub_workspace.py'
original = source.read_bytes()
needle = b'await mcp.tool_call("t3_thread_organize", {"threadId": state.thread_id, "action": "archive"})'
assert original.count(needle) == 1
mutant = original.replace(needle, b'await mcp.tool_call("t3_project_delete", {"projectId": state.project_id, "force": True})')
raw = Path(__file__).parent / 'raw/approved'
raw.mkdir(parents=True, exist_ok=True)
try:
    source.write_bytes(mutant)
    with (raw / 'archive-mutation.log').open('wb') as output:
        output.write(('original_sha256=' + hashlib.sha256(original).hexdigest() + '\n'
                      + 'mutant_sha256=' + hashlib.sha256(mutant).hexdigest() + '\n').encode())
        output.flush()
        completed = subprocess.run(
            ['uv', 'run', '--frozen', 'python', '-m', 'pytest',
             'tests/test_hub_archive_v1244.py::test_archive_preserves_objects_and_idempotent_restart', '-q', '--tb=short'],
            cwd=root, stdout=output, stderr=subprocess.STDOUT, timeout=90,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
        )
    print(f'archive_mutation_pytest_exit={completed.returncode}; expected 1')
    if completed.returncode != 1:
        sys.exit('archive-to-purge mutation did not redden history survival')
finally:
    source.write_bytes(original)
assert source.read_bytes() == original
print('source restored byte-for-byte')
