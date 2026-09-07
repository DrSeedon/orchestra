"""Restore the seeded backend temporarily; committed regression must reject it."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[3]
backend = root / 'app/backend_codex.py'
current = backend.read_bytes()
old = subprocess.check_output(['git', 'show', '7dbb425d:app/backend_codex.py'], cwd=root)
test = 'tests/test_codex_home_lifecycle.py::test_new_home_does_not_read_or_seed_shared_state'
try:
    backend.write_bytes(old)
    with (root / '.orchestra/tasks/523/private-home-mutation.log').open('w') as log:
        result = subprocess.run(['uv', 'run', '--frozen', 'python', '-m', 'pytest', test, '-q'],
                                cwd=root, stdout=log, stderr=subprocess.STDOUT)
    assert result.returncode == 1, result.returncode
    output = (root / '.orchestra/tasks/523/private-home-mutation.log').read_text()
    assert 'home preparation accessed SQLite instead of leaving state to Codex' in output
    print('Restoring pre-change seed: committed regression FAILED at shared SQLite read.', flush=True)
finally:
    backend.write_bytes(current)
    assert backend.read_bytes() == current
    print('Implementation restored byte-for-byte.', flush=True)
