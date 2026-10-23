# V-1051 — DONE (implementation; required pytest pending on the orchestrator)

Changed `app/backend_hub.py`, `app/hub_workspace.py`, `tests/test_hub_workspace.py`,
`CHANGELOG.md` and the existing runtimes KB topic. No service restart, deployment,
Git commit/push, credentials or live provider run was used. This private copy has no Git;
the platform must import/commit the result on `task-V-1051/fix-hub-thread-failed`.
Suggested commit: `#V-1051: retry empty hub failures with diagnostics and exclude virtualenvs`.

## Behavior

- Failed/cancelled runs without a reply retry twice, after 1 s and 2 s, on the same
  thread with the same prompt, provider/model and effort. Every retry emits a worker
  status event and a server warning including the failed run's reason.
- Work prevents retry: tool/command/file activity; changed/deleted files; conflicts,
  rejected imports, outbox content or manifest changes. Failed/incomplete activity
  reads and failed sync-back also prevent replay. Platform workspace preparation
  is distinguished by its observed item ID and does not count as provider work.
- Existing provider-limit classification takes priority and never retries. An
  uncertain/refused retry send propagates without another send or a new thread.
  Interrupting the backoff stops resend. Rolled-back and failed-with-reply runs
  retain their error behavior without retry.
- Error text preserves `hub thread ended with status failed` and appends run-scoped
  diagnostics from wait, read run records and failed/error activity items. No reason
  yields the explicit `no reason exposed by hub`. Old runs are filtered by run ID.
  Both `recentRuns` and the existing `runs` input are accepted.
- Sync-back identifies virtualenv directories by `pyvenv.cfg` before applying any
  member, regardless of archive order/name. It rejects the whole directory with a
  sync note and imports siblings. Previously imported files under a now-excluded
  environment are preserved, rather than interpreted as deleted. This does not
  remove an already-imported environment from an old branch.

## What was actually verified

`uv --version` and the required targeted invocation both failed with exit 127:
`uv: not found on the hub and not inside a Mutagen-synced project (cannot forward via on-remote)`.
`python3 -m pytest --version` also failed: `/usr/bin/python3: No module named pytest`.
Only three `app` source files are supplied; `app/hub_activity.py`, `app/events.py`,
other integrations and `scripts/` are absent. Dependencies were not installed.

Fallback, explicitly **not** the required runner:

```sh
nice -n 15 python3 .orchestra/tasks/V-1051/offline_checks.py
```

18 stdlib unittest scenarios passed, executing production retry/watch/read/sync-back
and tar validation code. Missing imports, provisioning, commit execution and activity
rendering are doubles; the fallback cannot prove their integration. Files stay under
this task directory; temporary files are removed. Output: `offline-results.txt`.
All edited Python files compiled in memory and passed a trailing-whitespace check.

Mutation, on the final source (runtime override `NO_WORK_RETRIES = 0`):

```sh
nice -n 15 python3 .orchestra/tasks/V-1051/offline_checks.py --disable-retry Checks.test_a_empty_failure_retries_then_success
```

Exit 1, the retry acceptance scenario fails with
`HubWorkspaceError('hub thread ended with status failed; hub reason: provider disconnected')`.
Output: `mutation-results.txt`. Production source was never left mutated.

Source modules exercised (absolute):
`<hub-copy>/app/backend_hub.py`
and `<hub-copy>/app/hub_workspace.py`.
Fallback substitutes a synthetic `app` package with that checkout's `app` directory;
there is no complete imported application or integration-suite result on this copy.

## Live evidence and limits

Read-only T3 inspection of this worker's running thread confirmed top-level
`thread`, `recentRuns`, `items`, `nextPosition`, `hasMore`; recent run entries
use `runId`. Activity contains a platform `command_execution`, title `Workspace ready`,
text `$ Preparing workspace\nWorkspace preparation completed.`, with
`:native-item:workspace-preparation` in its ID. This matters: treating every command
item as provider work would disable recovery for every empty failure.

Failed-thread list queries in this project, including settled threads, returned no
candidates. Therefore no real failed-run reason payload was observed; fields in
synthetic regressions are compatibility cases, not a claim about Sol's failure shape.
The KB records only the observed shape and this limitation. No raw thread payload,
user prompt or account/credential dump was saved.

## Required checks on the full checkout

```sh
uv run --frozen python -c 'import app; print(app.__file__)'
uv run --frozen python -m pytest tests/test_backend_hub.py tests/test_hub_workspace.py tests/test_multicode_client.py -q
uv run --frozen python scripts/check_instruction_contract.py
uv run --frozen python scripts/run_tests.py
```

To repeat the mutation with the full pytest integration test, temporarily set
`NO_WORK_RETRIES = 0` in `app/backend_hub.py`, run the following (must fail), and
restore `NO_WORK_RETRIES = 2` before rerunning the targeted suite:

```sh
uv run --frozen python -m pytest tests/test_hub_workspace.py -q -k failed_without_reply_and_without_work_retries_same_thread_then_succeeds
```

Remaining risk: full integration tests and real failed-run diagnostics are unverified
here. A hub version that hides its reason still produces the explicit absence message;
unavailable/incomplete activity prevents retry. Tar download still includes the environment
before the import filter rejects it; this change fixes branch contamination, not transfer
volume. Python changes take effect through the existing service lifecycle only.
