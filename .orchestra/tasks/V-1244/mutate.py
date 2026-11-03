"""Offline mutation check: remove the Hub runtime boundary, require its test to fail."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[3]
source = root / 'app/turn_signals.py'
original = source.read_bytes()
needle = b'worker.get("backend_type") != "hub" or worker.get("is_orchestrator")'
assert original.count(needle) == 1
mutant = original.replace(needle, b'False or worker.get("is_orchestrator")')
raw = Path(__file__).parent / 'raw'
raw.mkdir(exist_ok=True)
try:
    source.write_bytes(mutant)
    with (raw / 'mutation.log').open('wb') as output:
        output.write(('original_sha256=' + hashlib.sha256(original).hexdigest() + '\n'
                      + 'mutant_sha256=' + hashlib.sha256(mutant).hexdigest() + '\n').encode())
        output.flush()
        completed = subprocess.run(
            ['uv', 'run', '--frozen', 'python', '-m', 'pytest',
             'tests/test_hub_completion_directive_v1244.py::test_runtime_and_role_boundary', '-q'],
            cwd=root, stdout=output, stderr=subprocess.STDOUT, timeout=90,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
        )
    print(f'mutation_pytest_exit={completed.returncode}; expected 1')
    if completed.returncode != 1:
        sys.exit('mutation did not redden the boundary tests as required')
finally:
    source.write_bytes(original)
assert source.read_bytes() == original
print('source restored byte-for-byte')
