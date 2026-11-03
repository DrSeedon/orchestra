"""Offline old-admission mutation. Always restore source; never invoke a provider."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'app/models.py'
TASK = ROOT / '.orchestra/tasks/V-1240'
TEST = 'tests/test_hub_sol_only_v1240.py::test_all_non_sol_hub_requests_refuse_even_with_old_enabled_flags'
original = SOURCE.read_bytes()
before = hashlib.sha256(original).hexdigest()
needle = b'if spec.runtime == "hub" and model_id != HUB_SOL_MODEL:'
assert original.count(needle) == 1
mutant = original.replace(needle, b'if False and spec.runtime == "hub" and model_id != HUB_SOL_MODEL:')
env = dict(os.environ)
env.pop('NOTIFY_SOCKET', None)
runner = shutil.which('uv')
assert runner and '/orchestra/tools/uv/0.11.28/' in runner
command = [runner, 'run', '--frozen', 'python', '-m', 'pytest', TEST, '-q', '--tb=short']
try:
    SOURCE.write_bytes(mutant)
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    output = result.stdout + result.stderr
    (TASK / 'raw/mutation.log').write_text(output)
finally:
    SOURCE.write_bytes(original)
restored = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
assert restored == before
assert result.returncode == 1, output
assert 'DID NOT RAISE' in output, output
control = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
(TASK / 'raw/mutation-restored.log').write_text(control.stdout + control.stderr)
assert control.returncode == 0, control.stdout + control.stderr
proof = dict(test=TEST, command=command[1:], mutation='remove the non-Sol hub refusal branch (old hub allowance)',
             before_sha256=before, mutant_sha256=hashlib.sha256(mutant).hexdigest(),
             restored_sha256=restored, mutation_exit=result.returncode, control_exit=control.returncode,
             intended_failure='DID NOT RAISE', mutation_summary=output.splitlines()[-1],
             restored_summary=(control.stdout + control.stderr).splitlines()[-1])
(TASK / 'mutation-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps(proof, indent=2))
