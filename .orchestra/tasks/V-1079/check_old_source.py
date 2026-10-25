"""Run the final behavioral oracles against the exact supplied production sources."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path.cwd()
task = root / '.orchestra/tasks/V-1079'
files = ('backend_codex', 'session', 'session_hibernate')
current = {name: (root / 'app' / (name + '.py')).read_bytes() for name in files}
old = {name: (task / (name + '.before.py')).read_bytes() for name in files}
selection = ' or '.join((
    'success_forms_and_order', 'terminal_failure_never_ok_or_timeout',
    'failed_beats_retry_hint_and_retains_cause', 'retryable_error_can_recover',
    'fatal_error_wakes_without_terminal', 'whole_operation_is_busy_after_item',
    'second_started_does_not_replace_owner', 'foreign_events_cannot_complete_or_contaminate',
    'ordinary_send_recovers_while_unresolved_with_early_events',
    'old_main_queue_and_stale_runtime_snapshot_are_not_evidence',
    'native_interrupt_uses_compact_turn', 'early_idle_compaction_cannot_be_shown_as_next_user_compact',
    'legacy_failure_without_started_is_not_hidden_by_timeout',
    'session_unknown_usage_does_not_reuse_precompact_percentage',
    'session_interrupt_does_not_disconnect_unknown_compact',
    'session_actual_send_and_listener_proceed_after_compact_timeout',
    'legacy_missing_ids_has_exclusive_lifecycle_boundary', 'missing_start_does_not_report_success',
))
command = ['uv', 'run', '--frozen', 'python', '-m', 'pytest', 'tests/test_codex_compact_state.py',
           '-k', selection, '-q', '-s', '-p', 'no:cacheprovider',
           '--basetemp=.orchestra/tasks/V-1079/tmp/old-final']
try:
    for name in files:
        (root / 'app' / (name + '.py')).write_bytes(old[name])
    with (task / 'old-source-final.stdout.txt').open('w') as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, timeout=55)
    print(json.dumps({'command': command, 'exit_code': result.returncode,
                      'old_source_sha256': {name: hashlib.sha256(value).hexdigest() for name, value in old.items()}}, indent=2))
finally:
    for name in files:
        (root / 'app' / (name + '.py')).write_bytes(current[name])
    assert all((root / 'app' / (name + '.py')).read_bytes() == value for name, value in current.items())
