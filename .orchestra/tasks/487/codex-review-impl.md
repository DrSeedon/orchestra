<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

🧾 Predictably, the happy path is healthier than the restart path. Reviewed the complete pinned diff `c8a6fd7...472ba02d`; no unrelated files or history inspected.

Focused suite: `uv run pytest -q tests/test_wf_run.py` → **12 passed**.

Implementation proof: `output_free = free_sources | ({own_id} if runtime == "harness" else set())` from [scripts/wf_run.py:514](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:514).

## Findings

blocking: [scripts/wf_run.py:303](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:303) — Replay ignores write-ahead `dispatched` events and reconstructs attempts only from `attempt_finished`. If the process dies after `turn_usage_add` commits but before `attempt_finished`, resume dispatches the provider call again with the same event ID; the ledger deduplicates it while the provider charges twice. Reproduction: **2 provider calls, 1 ledger row**. Restore must explicitly reconcile dispatched-but-unfinished attempts before redispatch.

blocking: [scripts/wf_run.py:391](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:391) — Budget capacity is checked without reserving a call under the state lock. Every parallel job can pass before any completion increments `dispatched_calls`; queued jobs are never rechecked after acquiring the semaphore. Reproduction with `max_calls=1`: **2 adapter calls and `dispatched_calls=2`**. Reserve the call at write-ahead dispatch time and restore reservations from the journal.

blocking: [scripts/wf_run.py:506](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:506) — Schema exhaustion and adapter failures complete the step with `None` without setting `partial_reason`. Consequently `write_manifest()` records `complete: true`; the pilot writes that manifest before its validation raises. Reproduction produced `step_reason="schema", complete=true`. This corrupts the durable completion signal.

blocking: [scripts/wf_pilot.py:61](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_pilot.py:61) — The pilot supplies itself as `workflow_path`, so the manifest wake command becomes `python scripts/wf_run.py scripts/wf_pilot.py --resume ...`. That executes the pilot as workflow source and fails at its top-level `__file__` reference instead of resuming it. The report contains a separate correct command, but the manifest and wake text—the interruption artifacts—contain the crashing one.

suggestion: [scripts/wf_run.py:403](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:403) — Quota and memory skips call `_finish(..., None)`, permanently caching a transient failure. A later resume returns cached `None` before rechecking readiness or memory. Reproduction after changing readiness from blocked to available made **zero new adapter calls**. Transient skips should remain resumable.

suggestion: [scripts/wf_run.py:315](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:315) — Any historical budget skip permanently restores `partial_reason="budget"`. Even after resuming with a larger budget and successfully completing the skipped call, the manifest remains incomplete. Recompute current incompleteness rather than retaining the historical reason indefinitely.

question: [scripts/wf_run.py:367](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:367) — Is verification required to use a non-free lane? An explicit `purpose="verify", model="<free>", loss_tolerant=True` is allowed, and line 515 then marks the original free sources verified. If the contract requires independent paid verification, the current check enforces only a workflow label and allows free-lane self-certification.

## Verdict

**❌ Needs work — confidence 0.99.**

The acceptance happy paths pass, but the snapshot has four blocking durability/accounting failures. The write-ahead journal currently behaves like a flight recorder that logs takeoff, then forgets whether the plane already flew.

## Round (2026-09-04T15:28:33Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

🔁 The restart logic now survives one more crash boundary—just not the next one. Reviewed the complete pinned diff `7d0aa55...958363e`; only the three authorized files were inspected.

Prior findings:

- **STILL BROKEN** — interrupted-attempt replay/accounting; the earlier window is fixed, but a later duplicate-charge window remains.
- **FIXED** — parallel `max_calls` reservation.
- **FIXED** — schema/adapter failures mark the manifest partial.
- **FIXED** — pilot-specific resume command.
- **FIXED** — quota/memory skips remain resumable.
- **FIXED** — historical pre-dispatch budget skips no longer poison successful resume.
- **FIXED** — harness models cannot verify free-derived inputs.

Verification: `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_wf_run.py` → **17 passed**.

Implementation evidence: `self._completed_reason[call_key] = str(row.get("reason") or "completed")` from [scripts/wf_run.py:326](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:326).

## Findings

blocking: [scripts/wf_run.py:328](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:328) — An interrupted call is classified unknown only when `dispatched > attempt_finished`. If the process dies after `attempt_finished` is durable but before `completed`, replay finds neither a completed nor unknown call and dispatches attempt 1 again with the same ledger event ID. Deterministic reproduction: **2 provider calls, 1 ledger row, `_unknown_calls=[]`**. Any dispatched call without a durable `completed` outcome must not be blindly replayed, or the result must be durably stored before `attempt_finished`.

blocking: [scripts/wf_run.py:534](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:534) — When budget exhaustion prevents a schema retry, `result` still contains the previous invalid response and `schema_error` remains set, so the step is terminally completed as `reason="schema"`. Resuming with a larger `max_calls` returns cached `None` without invoking the adapter. Reproduction with `max_calls=1`: first manifest reports `partial_reason="budget"` but the step records `reason="schema"`; resume with `max_calls=2` performs **0 calls**. Track that the loop stopped for budget and leave this call resumable.

## Verdict

**❌ Needs work — confidence 0.99.**

Five prior findings are fully fixed and one original budget scenario is fixed, but two blocking durability paths remain. The journal now locks the first restart door and politely leaves the second one open.

## Round (2026-09-04T15:32:29Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

🧪 Both previous blockers are fixed, and naturally the new checkpoint found two narrower ways to lie.

- **FIXED** — crash after `attempt_finished` no longer redispatches the charged call.
- **FIXED** — a budget-deferred schema retry resumes at the next attempt with the validation-error prompt.

Verification: `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_wf_run.py` → **19 passed**.

Implementation evidence: `current_prompt = _schema_retry_prompt(rendered, schema_error, schema)` from [scripts/wf_run.py:480](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:480).

## Findings

blocking: [scripts/wf_run.py:328](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:328) — An outcome-unknown call reserves its call count but restores no dollar cost when the process dies after `turn_usage` commits and before `attempt_finished`. The workflow may then dispatch other calls against an incorrectly full dollar budget. Reproduction with a `$1` budget: a committed `$1.10` unknown call followed by resume allowed another `$0.10` call; actual ledger spend was `$1.20`, while the engine reported `$0.10`. Unknown spend must conservatively exhaust the dollar budget or be reconciled from the authoritative ledger before further dispatch.

blocking: [scripts/wf_run.py:567](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:567) — If the third invalid response writes `schema_invalid(next_attempt=3)` and the process dies before `_finish`, replay enters an empty `range(3, 3)`. Because `result` is `None`, it terminally records `reason="budget"` instead of the already-proven schema exhaustion. Reproduction produced **0 replay calls** but both `partial_reason` and step reason became `budget`. A restored `next_attempt >= 3` checkpoint should finish as `schema`.

## Verdict

**❌ Needs work — confidence 0.99.**

The two requested regressions are fixed, but the same replay seam still permits budget under-accounting and durable reason corruption. The checkpoint now remembers the page number and occasionally forgets which book it was reading.
