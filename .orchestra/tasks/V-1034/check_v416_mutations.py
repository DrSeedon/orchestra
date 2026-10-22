"""V-416 overlap diagnostics and unrelated-dirt regression probes."""
import json
from pathlib import Path
import subprocess
import sys

NOTES = Path('.orchestra/tasks/V-1034')
SOURCE = Path('app/workspace.py')
CASES = [
    ('omit-target-repo-path', 'f"{label} working tree is dirty at \'{path.resolve()}\' "',
     'f"{label} working tree is dirty "',
     'test_t2_dirty_target_path_files_and_action_reach_merge_caller'),
    ('omit-overlap-guard', 'dirty == changed or dirty.startswith(changed + "/")',
     'False or dirty.startswith(changed + "/")',
     'test_t2_dirty_target_path_files_and_action_reach_merge_caller'),
    ('block-unrelated-dirt', 'if changed_paths is None or any(', 'if True or any(',
     'test_t2_unrelated_dirty_target_allows_merge_and_preserves_file'),
]


def main():
    original = SOURCE.read_text()
    results = []
    for name, old, new, test in CASES:
        assert original.count(old) == 1, name
        log = NOTES / f'v416-mutation-{name}.log'
        try:
            SOURCE.write_text(original.replace(old, new))
            with log.open('w') as output:
                proc = subprocess.run([
                    sys.executable, '-m', 'pytest',
                    f'tests/test_merge_reason_preservation_416.py::{test}', '-q', '--timeout=20',
                    f'--basetemp={NOTES}/v416-mutation-tmp',
                ], stdout=output, stderr=subprocess.STDOUT, timeout=30)
        finally:
            SOURCE.write_text(original)
        failures = [line for line in log.read_text().splitlines() if line.startswith('FAILED ')]
        results.append({'mutation': name, 'detected': proc.returncode == 1 and bool(failures),
                        'exit_code': proc.returncode, 'failed_tests': failures})
    assert SOURCE.read_text() == original
    (NOTES / 'v416-mutations.json').write_text(json.dumps(results, indent=2) + '\n')
    for result in results:
        print(result['mutation'], 'DETECTED' if result['detected'] else 'SURVIVED')
    return 0 if all(result['detected'] for result in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
