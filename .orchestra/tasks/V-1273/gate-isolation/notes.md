# sanitized-publication-copy
# Prior private originals: private/tasks/V-1273/originals/ (root-held; not accessed).

# Gate fixture isolation

Root reported merge gate: 163 passed, one failure at strict clean-status assertion, sole path `?? app/__pycache__/`. Earlier host checks inherited bytecode suppression; the gate does not. Reproduce before editing the test. Product fix and existing sanitized artifacts frozen; no live infrastructure or root-private access.

Test-first RED without bytecode env: 1 failed in 31.88s, exact strict-status mismatch `?? app/__pycache__/`, same assertion line 149 as root gate. New red.txt is normalized in memory before persistence. No product defect found.

GREEN without bytecode env: 1 passed in 19.53s. Only four fixture-setup lines added; existing assertions AST-identical. Independent synthetic Git probe confirms source/WIP and other caches still visible. Full mapped and both mutations started; all subprocesses explicitly remove PYTHONDONTWRITEBYTECODE.

Product rollback mutation: expected RED, 1 failed in 22.90s, exact second-turn NOT COMMITTED/pathspec `duplicate.txt` (mutation.txt). Fixture rollback mutation: expected RED, 1 failed in 23.98s at preserved clean-status assertion; pytest cannot rewrite an in-memory function, so rerun with a diagnostic that records the actual status without changing its assertion (first output retained as fixture-mutation-first.txt).

Completed canonical mapped subset: 163 passed, 1 failed in 355.58s, no skips, all 9 V-1273 regressions passed without bytecode env. Only failure is pre-existing prompt case at test_hub_workspace.py:1709; copied hub/worker.md is absent, original before-fix control remains preserved in prior prompt-baseline.txt. No test/source/dependency weakened to hide this limitation. Full-host green remains root acceptance.
Fixture rollback diagnostic run: expected RED 1 failed/27.39s; actual status exactly `?? app/__pycache__/`.
