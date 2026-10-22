"""Restore each mutant in finally; run only offline regression tests in this copy."""

import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
ARTIFACTS = Path(".orchestra/tasks/V-1026")
mutants = [
    (
        "context-reset", "app/session.py",
        '''            self._last_context.update(
                percentage=after_pct if post_tokens else 0,
                total_tokens=post_tokens,
                known=bool(post_tokens and max_tokens),
            )
''', "",
        "test_success_replaces_usage_before_release_and_restart",
    ),
    (
        "deferred-gate", "app/session_turns.py",
        "allow_context_compaction and context_known and not context_deferred",
        "allow_context_compaction and context_known",
        "test_restored_high_usage_waits_for_new_reading_then_can_trigger",
    ),
    (
        "stale-refresh", "app/session.py",
        '''            if backend is not self._backend or generation != (self._turn_gen, self.session_id):
                return
''', "",
        "test_refresh_from_previous_context_cannot_restore_high_usage",
    ),
]
for name, filename, before, after, test in mutants:
    source = Path(filename)
    original = source.read_text()
    assert original.count(before) == 1, name
    try:
        source.write_text(original.replace(before, after, 1))
        command = [
            os.environ.get("UV_BIN", "uv"), "run", "--frozen", "--offline", "python", "-m", "pytest",
            f"tests/test_double_compaction_v1026.py::{test}", "-q",
            f"--basetemp={ARTIFACTS}/pytest-mutation-{name}",
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
        output = (result.stdout + result.stderr).replace(str(ROOT), ".")
        output = re.sub(r"/home/[^'\s]*?\.\.\.", "./...", output)
        (ARTIFACTS / f"mutation-{name}.log").write_text(output)
        print(f"{name}: exit={result.returncode}", flush=True)
        if result.returncode != 1 or "AssertionError" not in output:
            print(output)
            sys.exit("mutant did not fail at a behavior assertion")
    finally:
        source.write_text(original)
print("All 3 mutants detected; original sources restored.")
