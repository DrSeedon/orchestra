"""Temporarily mutate only broker code, run the offline regression, restore bytes."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
source = ROOT / 'app/backend_hub.py'
original = source.read_bytes()
needle = '        pending = state.pending_sync\n        if pending["phase"] == "import":'
replacement = '''        pending = state.pending_sync
        if pending["phase"] == "import":
            with tarfile.open(out, "r:") as archive:
                for member in archive:
                    if hw._member_path(member.name) == OUTBOX_NAME:
                        await self._run_outbox(ssh, state, archive.extractfile(member).read())
        if pending["phase"] == "import":'''
assert original.decode().count(needle) == 1
try:
    source.write_text(original.decode().replace(needle, replacement))
    env = dict(os.environ, TMPDIR='/tmp')
    result = subprocess.run([
        sys.executable, '-m', 'pytest',
        'tests/test_hub_report_order_v1213.py::test_parent_observes_committed_result_and_final_head', '-q',
    ], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    (ROOT / '.orchestra/tasks/V-1213/mutation.log').write_text(result.stdout + result.stderr)
    assert result.returncode == 1, f'early-report mutation unexpectedly returned {result.returncode}'
    assert 'report arrived before local commit' in result.stdout
    print('Early-report mutation killed: parent observed stale committed contents.')
finally:
    source.write_bytes(original)
