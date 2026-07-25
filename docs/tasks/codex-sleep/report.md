# Report — stop Codex/Sol external-state sleeping

## Result

Implemented the approved B → A → C sequence without adding a command blocker:

1. `codex_review` now requires `END YOUR TURN NOW` in both its MCP docstring and
   start result. It says Orchestra wakes the caller on success, timeout, or
   failure; the old `do NOT poll, just wait` wording is gone.
2. The shared base prompt forbids sleeping or polling for a background job,
   review, or another agent, and tells every role to end the turn. Test and
   bounded restart sleeps remain explicitly legal.
3. `merge_session()` absorbs the short DONE-message → turn-end race for up to
   2 seconds at 50 ms intervals. It then acquires the loaded worker lifecycle
   lock and rechecks status before merge. That lock remains held through merge,
   session persistence, and the optional `next_task_id` branch switch, so a
   completion notification cannot start a new turn inside the critical region.

No PreToolUse hook or global `sleep` ban was added.

## Tickets

- T1 — B: end-turn `codex_review` contract: done.
- T2 — A: shared external-wait rule: done.
- T3 — C: merge transition grace and lifecycle exclusion: done.
- T4 — focused/full verification and Codex review: done, with two unrelated
  repository test-fixture failures documented below.

## Files changed

- `app/mcp_stdio.py` — mandatory end-turn contract.
- `pipelines/default/prompts/base.md` — shared no-external-wait rule.
- `app/routes/sessions.py` — bounded merge grace and lifecycle critical section.
- `tests/test_mcp_codex_review.py` — schema/result wording contract.
- `tests/test_default_pipeline.py` — all-role prompt coverage.
- `tests/test_api.py` — running→idle success, persistent-running rejection, and
  merge-and-switch wake exclusion.
- `docs/tasks/codex-sleep/plan.md`
- `docs/tasks/codex-sleep/codex-review-plan.md`
- `docs/tasks/codex-sleep/codex-review-impl.md`
- `docs/tasks/codex-sleep/retro.md`

## Verification

### Affected tests

Command:

```text
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest \
  tests/test_mcp_codex_review.py \
  tests/test_default_pipeline.py \
  tests/test_api.py -q
```

Result: **95 passed in 33.49s**.

The four merge-specific endpoint tests also passed independently:
**4 passed in 2.23s**.

### Repository-wide checks

The required `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q` was run.
It stopped at an unrelated live-dashboard fixture failure after
**343 passed, 1 failed**:

- `tests/test_frontend.py::test_codex_web_search_renders_queries_without_transport_json`
  received 20 live SSE tool cards after its fixture cleared `#chat`; the changed
  files do not touch frontend code. The isolated rerun failed the same way.

A second run excluding the environment-coupled frontend module stopped after
**579 passed, 20 skipped, 1 failed**:

- `tests/test_session.py::TestStart::test_with_message_sets_running_then_idle`
  fails because its test database has no `bg_jobs` table. The isolated rerun
  reproduces `sqlite3.OperationalError: no such table: bg_jobs`; this task does
  not change session turn handling or DB schema.

`git diff --check` passes.

## Adversarial review

- Plan: three rounds. Codex found two real lifecycle-boundary blockers; both
  were accepted and fixed in the plan. Final verdict:
  `APPROVED` (`codex-review-plan.md`).
- Implementation: the first attempt hit a refused ChatGPT websocket and the
  second over-broad attempt timed out. A bounded review of the exact changed
  hunks completed. Verdict: **APPROVED**, with no blocking, suggestion, or
  question findings (`codex-review-impl.md`).

## Breaking changes and remaining work

- Breaking changes: none.
- Runtime Python changes require Orchestra to be restarted after merge.
- Measure the next 7 days or 30 Sol review jobs. Revisit a narrowly targeted
  standalone-sleep guard only if external-state sleeps remain.
- The two unrelated full-suite fixture failures remain; they were not modified
  in this surgical task.
