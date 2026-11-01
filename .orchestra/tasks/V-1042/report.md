# V-1042 — implementation complete; full-suite verification delegated to parent

## Changes

- `app/forbidden_strings.py`: `scan_range` checks `git merge-base`. Exit 1 selects a
  two-tree diff against `4b825dc642cb6eb9a060e54bf8d69288fbee4904`, so the entire orphan
  worker tree is scanned. Exit 0 retains the existing three-dot diff; other exits raise
  `RuntimeError`. Commit-message, pathname and added-line scanning remain in place.
- `tests/test_fan_terminal_kind.py`: `_Child` now supplies the established session `_log`
  interface and stores diagnostics separately from `_turn_logs`. The existing terminal/wake
  assertions remain; the test also checks one status log without freezing its prose.
  Production V-1028 logging is unchanged.
- `tests/conftest.py`: autouse isolation overrides `forbidden_strings.ENV_VAR` with an
  absent per-test sandbox file, including inherited environment settings. Tests may opt
  into a synthetic ruleset; subprocesses inherit the isolated path.
- `tests/test_publish_guard.py`: isolation regression; orphan content, shared content,
  pathname, commit-message and clean cases; Git-error propagation; merge-entrypoint
  rejection with unchanged worker/target heads and clean working trees.
- `CHANGELOG.md`: documented fallback and its restart lifecycle.
- `TODO.md`: recorded a separate existing diagnostic issue: when a forbidden value appears
  in a pathname, scan findings repeat the full pathname. The fallback does not change this.
  The pathname test checks blocking; content/message cases also check value-free diagnostics.

The scanner module was missing in the initial hub copy. The parent supplied it on the second
turn; the implementation blocker reported in the first turn is resolved.

## Checks actually run

Required command attempted:
`uv run --frozen python -m pytest tests/test_fan_terminal_kind.py tests/test_workspace.py tests/test_publish_guard.py -q`.
The available `uv` is a forwarding shim and exits before running tests:
`uv: not found on the hub and not inside a Mutagen-synced project (cannot forward via on-remote)`.
Output: `required-tests.log`.

Fallback pytest attempted with `nice -n 15 python3 -m pytest` and the same paths:
`/usr/bin/python3: No module named pytest`. Output: `fallback-pytest.log`.

`nice -n 15 python3 .orchestra/tasks/V-1042/check_offline.py` passes, using only the standard
library and temporary Git fixture repositories beneath this task directory. It executes
11 actual test-function cases extracted from `tests/test_publish_guard.py` against the real
`app.forbidden_strings` module: related additions, commit/path scanning, clean/removal,
missing list, isolation, five orphan cases, and genuine merge-base errors. It also compiles
changed Python files and executes the actual AST-extracted `fire_auto_report` method against
the real `_Child` test stub, substituting only the unavailable silent-marker/fan collaborators.
Output: `offline-checks.log`. These checks are **not** a full pytest or fan-barrier run.

Imported `app` search location:
`<hub-workspace>`.
It is a namespace package in this partial copy: `app.__file__` is `None`.
The real imported scanner is `app/forbidden_strings.py` beneath that absolute path.

## Reversion evidence

All mutations are in memory; fixed source remains on disk. The offline check repeats them.

1. Remove `_Child._log`: the actual explicit-report skip method raises the original
   `AttributeError("'_Child' object has no attribute '_log'")`.
2. Remove the isolation fixture's environment override: the added isolation regression fails.
3. Restore the original unconditional three-dot `git diff` and remove merge-base selection:
   all five added orphan regression cases fail with `no merge base`.
4. Replace the empty-tree fallback with a target-tip diff: the shared-content orphan test
   fails, proving that scanning only lines different from the target can miss forbidden
   worker content. This test contains the same forbidden line at the same pathname in
   unrelated target and worker histories.

## Remaining verification and lifecycle

The parent explicitly offered to run tests in the full environment. Still unrun here:
complete fan/V-1028 tests, workspace rollback test, merge-entrypoint orphan test, pre-push
hook test, full suite and instruction-contract script. Other application modules and
`scripts/` remain absent from the hub copy. No complete-checkout result or CI success is claimed.

There is no `.git` or remote in this hub copy; the platform copies changes back and commits
on `task-V-1042/fix-ci-1042`. No repository commit/push, deployment, service restart or live
forbidden-list read was performed. The Python guard change requires an owner-authorized
restart before a running service uses it. Pre-push processes import the source on each run.
