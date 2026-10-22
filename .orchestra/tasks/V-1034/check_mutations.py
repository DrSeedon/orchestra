"""Run V-1034 regression mutations offline, restoring every source in finally."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
NOTES = Path('.orchestra/tasks/V-1034')
CASES = [
    ('headline-first-commit', 'app/workspace.py', 'summary = messages[-1]', 'summary = messages[0]', 'test_squash_uses_last_commit_subject'),
    ('headline-ignore-acceptance', 'app/workspace.py', 'if acceptance_note.strip():', 'if False and acceptance_note.strip():', 'test_squash_uses_acceptance_first_line_with_validated_refs'),
    ('count-task-evidence', 'app/diff_budget.py', 'if fields[2].startswith(".orchestra/tasks/"):', 'if False:', 'test_evidence_excluded_and_reported_but_lookalike_counts'),
    ('block-all-target-dirt', 'app/workspace.py', 'if changed_paths is None or any(', 'if True or any(', 'test_unrelated_dirty_target_survives_and_stays_out_of_commit'),
    ('accept-placeholder-note', 'app/merge_operations.py', 'if len(note) < 15 or note.casefold() in {"placeholder", "-", "tbd"}:', 'if False:', 'test_acceptance_is_enforced_before_operation_creation'),
    ('accept-short-sha', 'app/merge_operations.py', 'r"[0-9a-fA-F]{40}"', 'r"[0-9a-fA-F]{7,40}"', 'test_short_sha_is_refused_before_operation_creation'),
    ('full-output-by-default', 'app/mcp_stdio.py', 'result if verbose else _compact_merge_result(result)', 'result if True else _compact_merge_result(result)', 'test_compact_receipt_retains_only_failure_ids_and_required_fields'),
    ('ignore-verbose-option', 'app/mcp_stdio.py', '_merge_tool_result(result, verbose=True) if verbose else', '_merge_tool_result(result, verbose=False) if verbose else', 'test_public_merge_worker_verbose_is_presentation_only'),
]


def run(label, node):
    log = NOTES / f'mutation-{label}.log'
    cmd = [sys.executable, '-m', 'pytest', node, '-q', '--timeout=30', f'--basetemp={NOTES}/mutation-tmp']
    with log.open('w') as out:
        proc = subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, timeout=60)
    lines = log.read_text().splitlines()
    return proc.returncode, [line for line in lines if line.startswith('FAILED ')], lines[-1] if lines else ''


def main():
    results = []
    control, failed, summary = run('control', 'tests/test_merge_worker_v1034.py')
    results.append({'case': 'control', 'exit_code': control, 'summary': summary})
    if control:
        raise RuntimeError(f'control must pass: {summary}')
    for label, source, old, new, test in CASES:
        path = ROOT / source
        original = path.read_text()
        if old not in original:
            raise RuntimeError(f'mutation anchor missing: {label}')
        try:
            path.write_text(original.replace(old, new))
            code, failed, summary = run(label, f'tests/test_merge_worker_v1034.py::{test}')
        finally:
            path.write_text(original)
        killed = code == 1 and bool(failed)
        results.append({'case': label, 'exit_code': code, 'killed': killed, 'failing_ids': failed, 'summary': summary})
        print(label, 'KILLED' if killed else 'SURVIVED', flush=True)
    (ROOT / NOTES / 'mutations.json').write_text(json.dumps(results, indent=2) + '\n')
    return 0 if all(r.get('killed', True) for r in results) else 1


if __name__ == '__main__':
    os.chdir(ROOT)
    sys.exit(main())
