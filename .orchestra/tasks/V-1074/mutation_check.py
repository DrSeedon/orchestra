"""Local, sequential behavioral mutation checks; never edits acceptance tests.

Run with the provisioned uv: uv run --frozen python .orchestra/tasks/V-1074/mutation_check.py
Each source mutation is restored in finally. All fixtures and logs remain task-local.
"""

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = Path(__file__).resolve().parent
UV = Path.home() / ".local/share/orchestra/tools/uv/0.11.28/bin/uv"
TEST = "tests/test_cron_drain_delivery_v1074.py::"
MUTATIONS = (
    (
        "drain-drop", "app/message_deliveries.py",
        '            _update_state(delivery_id, "QUEUED", clear_user_log=True)\n'
        '            return\n        elif isinstance(error, QuotaGateError):',
        '            mark_message_delivery_failed_before_submit(delivery_id, error)\n'
        '            return\n        elif isinstance(error, QuotaGateError):',
        "test_actual_drain_keeps_accepted_fire_through_cancel_restore_restart[cron_command]",
    ),
    (
        "truncate-source", "app/bg_jobs.py", "source_output=raw_output,",
        "source_output=output[-3000:],",
        "test_nonmatch_cannot_overwrite_full_accepted_source_or_display",
    ),
    (
        "rerun-command", "app/bg_jobs.py",
        "            if _row(delivery_id) is not None:\n                return",
        "            if False:\n                return",
        "test_double_observer_reuses_fire_but_next_occurrence_is_new",
    ),
    (
        "ignore-generation", "app/manager.py",
        "if current_generation != target_generation:", "if False:",
        "test_changed_recipient_fails_visibly_without_executing_stale_body[task]",
    ),
    (
        "split-acceptance", "app/message_deliveries.py",
        '            connection.execute(\n                """INSERT INTO message_deliveries (',
        '            connection.commit()\n'
        '            connection.execute(\n                """INSERT INTO message_deliveries (',
        "test_acceptance_failure_rolls_back_fire_marker",
    ),
    (
        "abort-no-wake", "app/manager.py",
        "                resume_queued_message_deliveries()", "                pass",
        "tests/test_cron_drain_abort_v1074.py::"
        "test_actual_abort_resumes_cron_once_after_nonmatch_without_command_replay[False]",
    ),
    (
        "abort-orphan-recovery", "app/message_deliveries.py",
        '    """Reopen known-unsubmitted queues after drain abort, without orphan recovery."""',
        '    """Reopen known-unsubmitted queues after drain abort, without orphan recovery."""\n'
        '    _recover_message_deliveries(None)',
        "tests/test_cron_drain_abort_v1074.py::"
        "test_abort_keeps_ambiguous_head_and_its_queued_follower_unchanged[DISPATCHING]",
    ),
    (
        "direct-without-preflight", "app/routes/sessions.py",
        "quota_wait = await _preflight_or_quota_wait(target.id)", "quota_wait = None",
        "tests/test_cron_drain_abort_v1074.py::"
        "test_canonical_direct_preflight_switches_before_generation_capture_and_dispatches",
    ),
)


def main():
    env = dict(os.environ, TMPDIR=str(ARTIFACTS / "tmp"))
    Path(env["TMPDIR"]).mkdir(exist_ok=True)
    for name, relative, before, after, test in MUTATIONS:
        test_path = test if "::" in test else TEST + test
        source = ROOT / relative
        original = source.read_text()
        if before not in original:
            raise AssertionError(f"mutation anchor missing: {name}")
        try:
            source.write_text(original.replace(before, after))
            log = ARTIFACTS / f"mutation-{name}.stdout.txt"
            with log.open("w") as stdout:
                result = subprocess.run(
                    [str(UV), "run", "--frozen", "python", "-m", "pytest",
                     test_path, "-q", "--basetemp", str(ARTIFACTS / "tmp" / name)],
                    cwd=ROOT, env=env, stdout=stdout, stderr=subprocess.STDOUT, timeout=60,
                )
            output = log.read_text()
            if result.returncode != 1 or f"FAILED {test_path}" not in output:
                raise AssertionError(f"mutation did not fail its behavioral oracle: {name}; {log.name}")
            print(f"KILLED {name}: {test_path}", flush=True)
        finally:
            source.write_text(original)
    print("All source restored; acceptance tests unchanged.", flush=True)


if __name__ == "__main__":
    main()
