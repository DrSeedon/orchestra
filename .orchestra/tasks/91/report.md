# Task #91 — DONE→IDLE synchronization

## Result

Lifecycle operations no longer guess that a worker finished after a two-second
grace period. `AgentSession` now exposes one explicit per-turn completion event:
every new logical turn clears it, and terminal paths publish it only after the
in-memory status has been persisted as `IDLE` or `WAITING`.

`merge_worker` and branch switching wait for that event when a loaded worker is
`RUNNING`. `WAITING` is explicitly not lifecycle-ready. Neither path interrupts
or stops the worker. Both Git operations recheck `IDLE` while holding the
session lifecycle lock, so a concurrent interrupt must finish stopping the
backend before Git can touch the worktree.

## Files

- `app/session.py` — turn-completion event, waiter, and terminal publication on
  normal and abnormal turn exits.
- `app/session_turns.py` — clear on logical turn start; publish after
  `finish_turn_status()` calls `_persist()`.
- `app/routes/sessions.py` — explicit lifecycle wait for merge/switch; no grace
  polling; `WAITING` rejection; lifecycle-lock recheck.
- `tests/test_session.py` — persistent/per-turn event-loop coverage for Claude,
  Codex, Grok, and OpenCode; ordering, `WAITING`, and auto-continue coverage.
- `tests/test_api.py` — merge/switch wait behavior, no hidden interrupt, and
  switch serialization until backend interrupt acknowledgement.
- `docs/tasks/91/codex-review-impl.md` — adversarial review and resolved findings.

## Verification

- T4 focused tests: `13 passed in 4.69s`.
- Runtime/session/API/backend suite: `319 passed in 52.81s`.
- Full suite under the global test lock:
  `1086 passed, 20 skipped in 111.66s`; raw output:
  `/tmp/pytest-91.log`. The lock was released immediately after the run.
- `git diff --check`: clean.
- Codex review: first isolated round found the switch/interrupt race; the
  lifecycle-lock regression fix and real event-loop tests were re-reviewed.
  Final verdict: **APPROVED**, with no remaining blocking, suggestion, or
  question findings.

## Live read-only validation

The production SQLite DB was opened with `mode=ro` and `PRAGMA query_only=ON`.
Every live `backend_type` resolved through the runtime registry:

```text
registered=claude:persistent,codex:per_turn,grok:per_turn,opencode:per_turn
claude | idle    | <blank> | 1
claude | idle    | default | 49
claude | running | default | 1
codex  | idle    | default | 25
codex  | running | default | 4
codex  | waiting | default | 2
validated-live-backends=['claude', 'codex']
result=PASS
```

There were no live Grok/OpenCode rows at validation time. Their registered
per-turn paths are covered by the parameterized event-loop test and their
adapter suites in the 319-test focused run.

## Compatibility and remaining scope

- No MCP↔route request/response contract changed, so mixed old-route/new-MCP
  deployment behavior is unchanged.
- Activating these Python changes requires the later shared server restart; no
  restart was performed.
- No live worktree or DB row was mutated.
- General atomic spawn/switch/task sequencing remains T6; this slice only added
  the lock needed to keep its newly waiting switch path from racing interrupt.

## Reusable rule proposed

📝 RULE: When MCP stdio and route code can run different deployed versions →
design every wire-contract change for rolling compatibility and test new MCP
against old route, not only same-version pairs.
