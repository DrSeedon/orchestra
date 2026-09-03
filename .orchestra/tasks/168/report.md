# #168 — centralized weekly provider quota gate

## Result

Implemented one fail-closed admission contract for every real start of a new non-orchestrator
worker turn. Exact `10080`-minute utilization at or above `95%` blocks the target subscription
bucket. Claude, ordinary Codex, and Codex Spark are evaluated independently; only a positively
resolved Grok runtime is outside this policy. Existing running turns and direct orchestrator chat
remain available, and quota admission is not called by stop or idle model-change control actions.

No production process was restarted or deployed. No Claude turn or API key was used.

## Tickets

### T1 — Weekly95 decision and fresh observation

- Added `app/quota_gate.py`: immutable structured decision/error contract, exact weekly-window
  selection, strict telemetry validation, model/runtime resolution, fresh dynamic alternatives,
  and fail-closed unknown handling.
- `app/routes/system.py` now performs a bounded requested-family refresh at age `>=300s`, with
  separate Anthropic/Codex family locks and a post-lock cache/time reread. Codex and Spark share
  one upstream refresh but remain separate policy buckets.
- `/api/usage/readiness` exposes `policy=worker-weekly-v1` and the same central decision used by
  execution boundaries. The independent 100%-based wake scheduler was not changed.

### T2 — Authoritative execution admission

- `AgentSession.send()` gates idle/waiting workers before logs, status transition, backend creation,
  or provider send. RUNNING steering/reconnect and orchestrator sends bypass the gate deliberately.
- Two-phase admission does provider I/O outside `_lifecycle_lock`, then revalidates model, stop
  generation, and decision expiry under the lock. Internal retry/auto-continue use this same path.
- Planned initial worker creation gets an early manager preflight before worktree/publish side
  effects; initial delivery still repeats the authoritative session check.
- Session create/send/compact routes return the canonical non-retryable HTTP 429 quota envelope.

### T3 — Lossless pending and compaction paths

- Pending flush checks quota at execution time. Denial retains the original message list unchanged,
  does not spin/retry, and emits one deduplicated exact-parent notification with undelivered fallback.
- Native Codex compaction and every idle Claude summary/ack start are admitted separately.
- Claude ack denial persists a bounded summary, restores the old native session, retains pending
  messages, and commits no history/prompt transition. A later explicit compact may repeat the
  idempotent summary; one successful ack performs one commit.
- Claude summary event consumption no longer holds `_lifecycle_lock`. Stop interrupts the active
  compaction backend, and generation checks prevent retry, ack, flush, or commit after cancellation.

### T4 — MCP preflight and control behavior

- MCP consumes the central versioned readiness response and fails closed for transport, legacy,
  malformed, unknown, stale, or unsupported model states.
- `spawn_worker` requests the side-effect-free server preflight and relies on authoritative delivery
  recheck. `codex_review` retains its no-job preflight. Hardcoded provider/alternative logic was
  removed.
- `change_worker_model` has no quota preflight. Switching an idle blocked worker remains possible;
  its next start is evaluated against the new bucket.

## Verification

### Behavioral tests

- Final affected-file suite, excluding one proven baseline-only assertion:
  `499 passed, 1 deselected in 99.69s`.
- Final async race matrix (Anthropic/Codex-family singleflight, newer-refresh waiter clock, stop/model/
  expiry during admission, blocked flush, stop during Claude summary, deferred ack) was run three
  consecutive times: `9 passed` in `5.21s`, `4.81s`, and `4.61s`.
- Final focused tests for the two Sol findings and deferred-ack contract: `3 passed, 185 deselected`.
- Final quota/readiness focus after reset/model edge fixes: `30 passed`.
- Earlier per-ticket gates before final integration: T1 `80 passed`; T2 `16 passed` plus complete
  session file `173 passed`; T3 `7 passed` plus compact/flush regression subset `66 passed`; T4 MCP
  focus `96 passed`.

### Independent mutation matrix

Every mutation used a fresh backup, made its focused behavioral test red, restored the original,
and checked the unique restore marker. Total: **31/31 detected**.

| Slice | Mutations detected |
|---|---|
| T1 (9) | `>=95` polarity; wrong weekly selector; Spark collapsed into Codex; unknown model exempted; stale age check removed; stale alternative admitted; post-lock cache reread removed; target-provider isolation ignored; exact age-300 boundary inverted |
| T2 (9) | idle admission removed; admission moved before RUNNING steering; stop-generation recheck removed; model recheck removed; decision-expiry recheck removed; create preflight removed; orchestrator exemption removed; quota added to change-model; quota added to reconnect |
| T3 (7) | flush admission removed; pending cleared on denial; parent notice removed; Claude summary admission removed; Claude ack admission removed; native Codex compact admission removed; session/history committed before successful ack |
| T4 (4) | planned-initial-turn flag removed; `codex_review` preflight removed; change-model preflight restored; unknown MCP readiness made fail-open |
| Sol follow-up (2) | waiter reused pre-lock timestamp (`calls == 8`, expected `1`); interrupt ignored active compaction backend (focused test timed out) |

### Full suite

Required command after final fixes:

```text
uv run python -m pytest -x -q > /tmp/pytest-168-postfix.log 2>&1
1 failed, 72 passed in 29.30s
```

It stops at the pre-existing assertion
`tests/test_api.py::test_merge_quarantine_persistence_retries_before_returning`: production returns
`RuntimeError: transient DB failure`, while the baseline test expects `transient DB failure`.
Both the `err_text(error)` production behavior and incompatible assertion exist in parent commit
`f2e1063`; #168 does not touch this merge-lifecycle path.

The rest of the post-fix suite, excluding that assertion and two separately proven baseline-only
UI/snapshot checks, completed:

```text
1987 passed, 42 skipped, 3 deselected, 2 warnings in 314.00s
```

The two other exclusions are `test_header_has_orch_tabs`, which reads the live server rather than
this worktree, and `test_route_surface_snapshot`, whose parent snapshot already omitted the existing
`/api/usage/readiness` route. The 42 skips are the suite's explicit unavailable-embedding/RAG skips;
#168 does not touch RAG. `uv.lock` remained unchanged.

## Codex/Sol review

Artifact: `docs/tasks/168/codex-review-impl.md`.

- The first filesystem-based attempt was infrastructure-blocked, so the same persistent session was
  resumed with a self-contained production diff and test evidence.
- Substantive review found three blockers: waiter-clock singleflight, lifecycle lock held through the
  Claude summary stream, and a question about deferred-ack persistence.
- The first two were fixed with behavioral and independent mutation coverage. The third was resolved
  against the approved explicit idempotent-repeat contract and strengthened exactly-once transition
  assertions.
- Final re-review: all three findings `FIXED`, no new findings, verdict **APPROVE**.

## Changed files

- Runtime: `app/quota_gate.py`, `app/routes/system.py`, `app/session.py`, `app/manager.py`,
  `app/routes/sessions.py`, `app/mcp_stdio.py`.
- Tests: `tests/conftest.py`, `tests/test_quota_gate.py`, `tests/test_usage_readiness.py`,
  `tests/test_session.py`, `tests/test_manager.py`, `tests/test_api.py`,
  `tests/test_mcp_quota_gate.py`, `tests/test_mcp_codex_review.py`,
  `tests/test_codex_bin_resolution.py`.
- Evidence: `docs/tasks/168/codex-review-impl.md`, this report.

## Compatibility and follow-up

- No schema migration, credential, API-key, frontend, wake-scheduler, Grok-quota, or deployment
  change.
- HTTP readiness response intentionally changes to the versioned worker-weekly contract; its path is
  unchanged.
- The three baseline test inconsistencies above remain outside #168 scope.
