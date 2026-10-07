# V-756: repeated workflow prompts and terminal notification

## Diagnosis

`WorkflowEngine._call_key()` correctly gave identical payloads distinct occurrence suffixes (`:0`, `:1`, …). `_run_attempt()` then built the writable worktree name from only `call_key[:12]`, omitting that suffix. All byte-identical calls therefore raced for the same `create_worktree()` path; the repository mutation lock serialized them, and later calls hit `ValueError: worktree already exists`. The first preparation exception escaped one `agent()` task; `asyncio.gather()` propagated it out of the stage while sibling tasks were still preparing. The runner could not finish the stage and promptly publish its partial manifest.

The manifest's `wake_message` is resume metadata, not an event listener. `BgJobManager` does not read that field: it sends a terminal message when the run process exits, times out, is interrupted on restart, or is cancelled through the manager. In the supplied first run, job `bg-2612e7a3f2` expired at `2026-10-07T17:26:44Z`; session log row 587105 proves the target eventually received `[Background job TIMED OUT]` then, 60 minutes after launch. That message contained only the initial `WF_BG_MESSAGE` line because the command had not produced a final manifest. The second run's job `bg-f86e6c1ac2` was explicitly cancelled at 16:26Z; its target log has zero `bgjob:v1:bg-f86e6c1ac2:*` terminal messages. Before this fix `_run_exec()` swallowed `CancelledError`, so manual run cancellation had no wake path. Terminal notifier code also returned silently when the target session was unavailable, and failure/timeout/restart send exceptions had no parent fallback.

Evidence checked: both complete journal files (2 lines for `V-193-148ed0301cef`, 11 for `V-193-a5888d6ae59a`), both manifests, both `bg_jobs` rows, the target session's terminal-message records for both job IDs, and Orchestra journal output around the first timeout. The first timed-out notification is present; the second cancelled run has no terminal message. The retained records do not identify whether the first run reached its deadline through `asyncio.timeout()` or startup expiry recovery, so that sub-path is unresolved; both paths now notify.

## Changes

Worktree names now include the full call key, including its occurrence suffix, so equal prompts get separate worktrees. Workspace preparation errors are recorded verbatim with exception type and message in `journal.jsonl` and the manifest step. They roll back the model-call dispatch count, return `None` for that task, set `partial_reason="error"`, and allow sibling tasks to finish; the incomplete manifest then fails the background job's `complete: true` artifact check and wakes the caller immediately. Failed preparation records remain retryable by `wf_run --resume` and completed calls replay from the journal.

Background terminal notifications now share one send path. Failed, timed-out, restarted, and manually cancelled run jobs wake their pinned target; missing targets or send exceptions are reported to the scope orchestrator through `report_undelivered`. Startup expiry recovery notifies expired run jobs, session shutdown reports active run jobs as undelivered to their scope orchestrator, and unexpected `_run_exec()` exceptions use the failed notification path.

## Verification

- `uv run --frozen python -m pytest tests/test_wf_run.py -q` — 43 passed.
- `uv run --frozen python -m pytest tests/test_dynamic_workflows.py -q` — 18 passed.
- `uv run --frozen python -m pytest tests/test_bg_jobs.py -q` — 62 passed, 1 skipped.
- The repeated-prompt test uses 10 identical calls at concurrency 3 and writable temporary git worktrees; the preparation-failure test checks error detail, zero billed dispatches, and resume retry. The background tests verify that an incomplete manifest with a preparation error wakes its caller, explicit cancellation wakes its caller, and a vanished target reports through the scope orchestrator.
- The repeated-prompt regression test was run before the fix and failed with `ValueError: worktree already exists`; after the fix it passes.
- Merge-gate follow-up: the isolated `test_workspace_setup_failure_is_recorded_retryable_and_not_paid_unknown` initially failed with `NameError: wf_run is not defined`; importing `scripts.wf_run` fixed it. The isolated rerun passed.
- Full merge-gate command `uv run --frozen python -m pytest tests/test_wf_run.py tests/test_dynamic_workflows.py tests/test_bg_jobs.py -m 'not live_probe and not browser' -q` — 123 passed, 1 skipped in 50.59s. Raw output: `acceptance-gate.log`.
- Imported `app` module path: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-workflow-tool/app/bg_jobs.py`.
- `python -m compileall -q app/bg_jobs.py scripts/wf_run.py`, `python scripts/check_instruction_contract.py`, and `git diff --check` — passed.

No live Luna call was needed. No database schema change was made. Python changes need an owner-initiated Orchestra restart; none was performed.
