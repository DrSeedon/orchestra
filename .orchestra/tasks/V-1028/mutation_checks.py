"""Run bounded V-1028 mutations offline and always restore the source tree."""

import difflib
import json
import os
from pathlib import Path
import subprocess

TASK = Path(".orchestra/tasks/V-1028")
UV = os.environ.get("V1028_UV_BIN", "uv")
AUTO = "tests/test_v1028_auto_report.py"
HOLDS = "tests/test_v1028_report_holds.py"

MUTATIONS = [
    ("any-target-counts-as-report", "app/session_turns.py",
     [('if target and target in {parent, s.parent_id}:', 'if target:')],
     [AUTO, "-k", "only_successful_parent_send"]),
    ("failed-send-counts-as-report", "app/session_turns.py",
     [('            if not accepted:\n                return\n',
       '            if False:\n                return\n')],
     [AUTO, "-k", "failed_parent_send"]),
    ("harness-mcp-error-is-success", "app/harness/loop.py",
     [('f"[{name} error]", "[error]", "[mcp error]"', 'f"[{name} error]", "[error]"')],
     [AUTO, "-k", "harness_mcp_error"]),
    ("parent-id-only-is-dropped", "app/session_turns.py",
     [('not (s.parent_name or s.parent_id)', 'not s.parent_name')],
     [AUTO, "-k", "parent_id_alone"]),
    ("provider-interrupt-is-silenced", "app/session_turns.py",
     [('if s._manually_interrupted:', 'if s._manually_interrupted or s._last_stop_reason == "interrupted":')],
     [AUTO, "-k", "real_turn_end_path"]),
    ("signal-quota-hold-stays-silent", "app/report_holds.py",
     [("WHERE state='pending' AND last_error LIKE 'QuotaGateError:%'",
       "WHERE state='pending' AND 0 AND last_error LIKE 'QuotaGateError:%'")],
     [HOLDS, "-k", "signal_hold_visible_once"]),
    ("accepted-quota-report-stays-silent", "app/message_deliveries.py",
     [('        report_holds.ensure_runner()\n', '        pass\n')],
     [HOLDS, "-k", "explicit_report_parked"]),
    ("dispatch-quota-report-stays-silent", "app/message_deliveries.py",
     [('            report_holds.ensure_runner(manager)\n', '            pass\n')],
     [HOLDS, "-k", "gate_closes_after_acceptance"]),
    ("crash-repeats-upstream-notice", "app/report_holds.py",
     [('            if not accepted:\n', '            if True:\n')],
     [HOLDS, "-k", "notice_recovery_and_crash"]),
    ("quota-hold-not-in-dashboard-api", "app/manager.py",
     [('                r["report_quota_hold"] = report_holds[r["id"]]', '                pass')],
     [HOLDS, "-k", "list_sessions_exposes"]),
    ("quota-hold-not-in-worker-card", "app/static/js/app.js",
     [('    if (s.report_quota_hold) {', '    if (false) {')],
     ["tests/test_v1028_report_hold_frontend.py"]),
    ("auto-report-bypasses-quota", "app/turn_signals.py",
     [('                            origin="agent",', '                            origin="platform",')],
     [HOLDS, "-k", "signal_hold_visible_once"]),
    ("hub-outbox-done-followed-by-auto-report", "app/session.py",
     [('            on_parent_report=reported)', '            on_parent_report=None)')],
     ["tests/test_v1028_hub_outbox_report.py", "-k", "done_to_parent_prevents"]),
    ("failed-hub-outbox-counts-as-report", "app/hub_outbox.py",
     [('                and report_receipt_accepted(result)\n', '                and True\n')],
     ["tests/test_v1028_hub_outbox_report.py", "-k", "failed_hub_outbox_send"]),
]


def main():
    results = []
    for name, filename, changes, tests in MUTATIONS:
        path = Path(filename)
        original = path.read_text()
        changed = original
        for before, after in changes:
            assert changed.count(before) == 1, (name, before, changed.count(before))
            changed = changed.replace(before, after, 1)
        (TASK / f"mutation-{name}.patch").write_text("".join(difflib.unified_diff(
            original.splitlines(True), changed.splitlines(True),
            fromfile=filename, tofile=filename,
        )))
        try:
            path.write_text(changed)
            with (TASK / f"mutation-{name}.log").open("w") as log:
                result = subprocess.run(
                    [UV, "run", "--offline", "--frozen", "python", "-m", "pytest", *tests,
                     "--basetemp=" + str(TASK / "tmp/mutation"), "-q", "--timeout=30"],
                    stdout=log, stderr=subprocess.STDOUT, timeout=120,
                )
            # A mutation must fail a behavioural assertion, not collection/setup.
            text = (TASK / f"mutation-{name}.log").read_text()
            killed = (result.returncode == 1 and " failed" in text and "AssertionError" in text
                      and "ERROR collecting" not in text and "ERROR at setup" not in text)
            results.append({"mutation": name, "exit_code": result.returncode, "killed": killed})
        finally:
            path.write_text(original)
    (TASK / "mutations.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    assert all(result["killed"] for result in results)


if __name__ == "__main__":
    main()
