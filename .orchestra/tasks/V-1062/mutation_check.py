"""Run focused behavioral tests against two controlled mutations, restoring source each time."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
TASK = ROOT / '.orchestra/tasks/V-1062'
MUTANTS = [
    ('original_dirty_refusal', 'app/workspace.py',
     'if record[:2] == "??" and hub_inputs and record[3:] in hub_inputs:',
     'if False and record[:2] == "??" and hub_inputs and record[3:] in hub_inputs:',
     'test_unchanged_input_and_committed_output_merge_preserves_original'),
    ('ignore_input_digest', 'app/hub_workspace.py',
     'unchanged = regular and direct and sha256_file(full) == digest',
     'unchanged = regular and direct',
     'test_merge_refuses_dirty_or_colliding_work_without_losing_data[changed-input]'),
]
failed = False
for name, filename, before, after, test in MUTANTS:
    path = ROOT / filename
    original = path.read_text()
    assert original.count(before) == 1, (name, 'mutation site moved')
    try:
        path.write_text(original.replace(before, after))
        command = [str(Path.home() / '.local/share/orchestra/tools/uv/0.11.28/bin/uv'),
                   'run', '--frozen', 'python', '-m', 'pytest',
                   f'tests/test_hub_inputs_v1062.py::{test}', '-q']
        result = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, timeout=90,
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        (TASK / f'mutation-{name}.txt').write_text(result.stdout)
        killed = result.returncode == 1 and '1 failed' in result.stdout and 'AssertionError' in result.stdout
        print(f'{name}: exit={result.returncode}; behavioral mutant killed={killed}', flush=True)
        failed |= not killed
    finally:
        path.write_text(original)
raise SystemExit(1 if failed else 0)
