# V-1145 — merge-gate diagnosis and recovery

Implemented in the supplied source copy. The broker must import/commit the result on
`task-V-1145/fix-merge-gate-diagnosis`; this worker has no Git metadata and did not
commit, push, deploy, restart, invoke providers or change a foreign environment.

## Change

`app/merge_operations.py` now derives recovery from structured gate reasons,
preserving the existing error codes and schema version. `error.details` includes
`reason`, `blocking_reasons`, `interpreter`, and `retry_operation="new"`.
Environment repair also includes `required_packages=["pytest", "pytest-timeout"]`.

| Reason | next_action.code |
| --- | --- |
| pytest_timeout_unavailable, pytest_unavailable | REPAIR_TEST_ENVIRONMENT_THEN_NEW_OPERATION |
| pytest_usage_error | FIX_PYTEST_INVOCATION_THEN_NEW_OPERATION |
| not_found, os_error | REPAIR_TEST_INTERPRETER_THEN_NEW_OPERATION |
| timeout, or batches whose only blocking reason is timeout | TEST_GATE_UNFINISHED |
| blocked skipped coverage | RESTORE_TEST_COVERAGE_THEN_NEW_OPERATION |
| unknown reason / legacy batch_inconclusive without child evidence | INSPECT_TEST_GATE_THEN_NEW_OPERATION |
| FAILED, including partial-red-before-timeout and mutation failure | FIX_TESTS_THEN_RETRY |

The environment action identifies the selected Python, requires an enabled
pytest-timeout plugin, names plugin-loading settings to inspect, and explains how
to discover timeout options with that Python's `-m pytest --help`. It performs no
installation, fallback interpreter switch or gate bypass.

`app/merge_test_gate.py` retains bounded, structured per-batch summaries (status,
reason, exit code and selected tests), without duplicating raw subprocess output.
This lets mixed environment/time-budget failures retain their actual repair path.
An aggregate containing skipped tests is SKIPPED, never PASSED; existing strict
mapped-gate admission decides whether it blocks. FAILED still takes precedence
over INCONCLUSIVE/SKIPPED. Per-node ceiling and interpreter selection are unchanged.

Added durable regressions to `tests/test_merge_operations.py`, batch regressions to
`tests/test_merge_test_gate.py`, and an Unreleased CHANGELOG entry. No frozen test
was weakened. Assertions use stable status/reason/action fields and real child
process outcomes, rather than recovery-message prose.

## Lifecycle finding

`accept_merge_operation` returns a terminal FAILED result unchanged for the same
operation ID after its identity check. `claim_operation` only accepts PENDING.
Only committed PARTIAL finalization has an explicit same-ID reopening path.
Thus even an actual budget timeout cannot be rerun by repeating this FAILED ID.
Recovery now calls for a fresh ID (or omitting it at the public tool boundary),
and neither the result nor error advertises blind same-ID retryability.

Tests execute the real accept/claim/runner/finish/query/public replay functions,
check persisted FAILED/NOT_REACHED, verify same-ID replay does not re-evaluate the
gate, and verify a newly accepted ID actually runs it again. Synthetic pinned
admission, sessions, idle status and a forbidden merge executor avoid real
managers/providers. Mutation failure retains its own cause even after green batches.

Already stored terminal receipts are not rewritten. Their historical prose may
remain stale; a fresh operation obtains the new diagnosis. No storage migration.

## Required runner and blocked integration checks

The provisioned runner exists: uv 0.11.28. Every Python command below used:

```sh
mkdir -p .orchestra/tasks/V-1145/tmp
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1145/tmp"
```

Default `.venv`, frozen lock, no substitute interpreter or lock changes. uv created
the copy's environment and installed 76 locked packages. Tests use synthetic local
data and no network. All test temporary state was kept under the task directory
(apart from pytest/Python caches in the source tree).

Before edits and after edits, ran the required focused command:

```sh
uv run --frozen python -m pytest tests/test_merge_operations.py tests/test_merge_test_gate.py -q
```

Both exit 2 during collection: `ModuleNotFoundError: No module named 'tests.task_seeds'`.
Evidence: `baseline.log`, `required-after.log`. This copy contains only the two
app modules and two test modules. Missing dependencies also include `app.db`,
`app.acceptance`, `app.task_refs`, `app.errtext`, `app.workspace`, receipt code and
`tests.test_acceptance`. This is an incomplete input copy; it does **not** establish
a known baseline failure in the full host checkout. Normal focused integration
tests remain unverified. The full runner `scripts/run_tests.py` was not supplied,
so the full suite and instruction-contract script were not run here.

## Supplemental source-copy evidence — not the required integration check

`check_source_copy.py` explicitly provides missing import interfaces and a synthetic
SQLite schema. It refuses a complete checkout and is never loaded by normal pytest.
It executes the actual two supplied app modules; operation storage/runner/replay
functions and real pytest subprocesses are not replaced. Schema compatibility with
the real `app.db` remains for host verification. Imports through absolute paths:

```text
/proc/self/cwd/app/merge_operations.py
/proc/self/cwd/app/merge_test_gate.py
```

The harness asserts both origins are the supplied source files via `samefile()`.
`app` is a namespace package in this copy, so its own `__file__` is absent.
These exact absolute import origins avoid publishing private host/user identities.

Final supplemental command (exit 0, **53 passed, 71 deselected, 16.67 s**; `final.log`):

```sh
uv run --frozen python .orchestra/tasks/V-1145/check_source_copy.py \
  tests/test_merge_operations.py tests/test_merge_test_gate.py \
  -k 'gate_reason_controls_durable_recovery or batch_causes_reach_durable_recovery or batch_skips_and_red_controls or mutation_failure_keeps_durable or real_missing_timeout_plugin_reaches_durable_recovery or real_runner_causes_reach_durable_recovery or batch_with_unverified_tests or per_test_ceiling or hung_node or missing_timeout_plugin or real_failure_mentioning or timeout_that_saw or timeout_without_red or run_pytest_timeout or large_subset_preserves or each_batch_is_attempted or small_mapped_subset or large_subset_keeps_diagnostics or pytest_argv_carries or argv_verbosity or worktree_venv or repo_root_venv or linked_worktree or interpreter_marker or project_venv_is_absent' \
  --basetemp=.orchestra/tasks/V-1145/tmp/final -q
```

This covers all 27 new operation cases and two new batch cases, plus existing
timeout progress, hung-node continuation, batched failure priority, argv and
project/shared/linked-worktree interpreter controls. Real child cases include:

- Selected project Python with plugin autoload disabled: usage exit 4,
  `pytest_timeout_unavailable`, environment repair in a persisted operation.
- A new pip-free venv with no pytest: `pytest_unavailable`, environment repair.
- Explicitly loaded timeout plugin with an unknown pytest option: usage diagnosis.
- Genuine failing tests, genuine elapsed timeout, and red-before-elapsed-timeout.
- Existing hung-node test: signal ceiling produces a named red and runs the next node.

Earlier supplemental checkpoints: `operations.log` (24 passed), `gate.log`
(20 passed), `combined.log` (53 passed). Final log supersedes them.

Raw synthetic CLI evidence, exit 0, in `cli-probe.log`:

```sh
uv run --frozen python .orchestra/tasks/V-1145/check_source_copy.py --probe
```

The same selected project Python first rejects the production `--timeout=120`
and `--timeout-method=signal` options with autoload disabled. Explicit child-only
plugin loading then uses a shortened one-second ceiling: the hung node is FAILED,
the next node PASSED, and the gate remains FAILED. No host configuration writes.
Subprocess stdout/stderr is retained; only the private copy-root path is normalized
to `<COPY_ROOT>` in public logs. The probe creates only synthetic local test files.

Mutation evidence (intentional exit 1, no production files edited):

```sh
uv run --frozen python .orchestra/tasks/V-1145/check_source_copy.py \
  --mutate-coarse-recovery tests/test_merge_operations.py \
  -k 'gate_reason_controls_durable_recovery or batch_causes_reach_durable_recovery' \
  --basetemp=.orchestra/tasks/V-1145/tmp/mutation-recovery -q
# 14 failed, 4 passed, 49 deselected; mutation-recovery.log

uv run --frozen python .orchestra/tasks/V-1145/check_source_copy.py \
  --mutate-skipped-passed tests/test_merge_test_gate.py -k batch_with_unverified_tests \
  --basetemp=.orchestra/tasks/V-1145/tmp/mutation-batches -q
# 2 failed, 55 deselected; mutation-batches.log
```

These mutations restore the former coarse recovery action and skipped-batch PASSED
behavior in memory. They demonstrate regression sensitivity, not a full original
source integration run. The parent should repeat mutations against committed tests
with the real schema and fixtures. Final supplemental source is unmutated and green.

## Remaining verification and limits

Parent: run both focused modules and `uv run --frozen python scripts/run_tests.py`
on the full checkout, inspect the broker's resulting diff and commit, and repeat
the planned mutations. No live bug inbox or real report payload was used. Task
evidence is synthetic and public-safe; no secrets, private host identities or
credentials were copied. Python activation follows the existing service lifecycle;
this worker checked source behavior only.

Final housekeeping used the same frozen uv interpreter for AST parsing of all four
edited source/test modules, whitespace checks, path normalization and a secret-form
scan of edited text/evidence: all passed. Generated task test directories and the
new pytest cache were removed; source-copy logs and reproduction harness remain.
