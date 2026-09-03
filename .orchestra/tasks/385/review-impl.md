# #385 — Mechanical implementation review

Date: 2026-08-23

## Review decision gate

- Author metadata: `model=gpt-5.6-sol`, `runtime=codex`, `role=full-cycle` from the live session record.
- Risk floor: high — shared session/message delivery and a lifecycle/authorization boundary.
- Changed production files: `app/mcp_stdio.py`, `app/backend_codex.py`, `app/session.py`,
  `app/events.py`, `app/bg_jobs.py`, `app/manager.py`, and
  `pipelines/default/prompts/base.md`.
- Consumers: Codex app-server turn stream; `TurnManager` usage/status; bg job success/failure/timeout
  wake; session pending-message queue; immutable SQLite logs/history/sync; all assembled default
  role prompts; direct Python tests of `codex_review`.
- Frozen oracle: `f6460dcf7db8038debf842d15a767c3c27099ade`; all test paths remain byte-identical.
- Exact AC commands: the T1, T2, and compatibility commands recorded below.

The canonical high-risk route would be a Sol implementation review. The task sender explicitly
forbade any live `codex_review` or provider call in Phase 3, so no model review was run and no
substitute reviewer was spawned. This file is the required mechanical/adversarial implementation
artifact, not an independent model verdict. The earlier plan review remains independent and ended
`APPROVED` in `docs/tasks/385/codex-review-plan.md`.

## Diff reviewed

Implementation range: `0268dae4cbc89c5d9086cc01244b3dd6489b33d5..6d0508e1c0dada6df076aee3adaca2bf9a735e12`

```text
app/backend_codex.py              +201/-9
app/bg_jobs.py                     +22/-3
app/events.py                      +19/-0
app/manager.py                      +2/-1
app/mcp_stdio.py                   +31/-7
app/session.py                     +19/-5
pipelines/default/prompts/base.md   +1/-0
```

## Adversarial findings

### Structured authority

- `codex_review` returns `CallToolResult` on every non-exception path. Human-readable content is
  preserved; structured control is added only after a nonempty bg job id is returned.
- `CodexBackend` reads the completed `mcpToolCall` item, never `_result_text()` output.
- The predicate requires exact server/tool, bound thread/turn, no item/structured error, exactly five
  control keys, exact fixed values, and an event id derived from the same nonempty job id.
- Wrong/missing transport ids, wrong tool/server, text-only/malformed output, tool errors, fixed-value
  changes, mismatched event id, and extra keys all remain ordinary content and never interrupt.

Result: no blocking issue found.

### Turn state, quarantine, and accounting

- Control state is armed before the tool result is yielded, so concurrent real input sees
  `deferred_interrupt_pending` and queues instead of steering the dying turn.
- Only `item/agentMessage/delta` and completed `agentMessage` for the bound turn are quarantined.
  Another-turn assistant output and same-turn reasoning/warning/tool results remain visible.
- Exactly one `turn/interrupt` is requested. Its acknowledgement starts a five-second absolute
  terminal deadline; it is not treated as completion.
- Native `status=interrupted` keeps native turn id and usage, `ok=false`, and
  `stop_reason=interrupted`; generic `model_error/errors` are cleared, so no provider retry is armed.
- A non-interrupted native terminal becomes `deferred_interrupt_not_honored`, not `end_turn`.
- RPC failure/terminal timeout emits an explicit failure terminal with `cost_unaccounted=true`,
  clears `_active_turn_id`, and calls real `disconnect()` once. Clearing the id before disconnect is
  required because the existing disconnect method otherwise issues a second interrupt.
- Public `AgentSession.interrupt()` and `_manually_interrupted` are untouched; no early `IDLE` is
  published on the successful path.

Result: no blocking issue found.

### Real bg provenance and persistence

- `InjectedMessage` is frozen and created only by the three terminal `run` job paths in this task.
- Origin is `orchestra.bg_jobs`; event ids are `bgjob:v1:<job_id>:completed|failed|timed_out`.
- `SessionManager.send` passes the object internally. `AgentSession.send` projects `event_id` onto
  the one `user_message` row and passes/queues text only.
- The running-race oracle proves the queued provider submission does not write a second user row and
  history/sync retain the original event id.
- Legacy tests that inspect the manager mock's argument remain compatible through read-only string
  views (`__contains__`, `lower`, `__str__`) while `InjectedMessage` remains non-`str` and immutable.
- `logs` schema/indexes are unchanged. No exactly-once claim is made; the existing
  `triggering -> send -> triggered` crash gap remains out of scope.

Result: no blocking issue found.

### Prompt and merge compatibility

- The exact sentence occurs once in `base.md` and zero times in `CLAUDE.md`.
- No frontend code changed.
- `main...HEAD` changes only the `SessionManager.send` import/signature and the planned
  `codex_review` hunk. #379's later `drain_restart_persistence()` hunk is not touched; #384 changes
  only `app/acceptance.py`, `app/routes/tm.py`, and `app/tm.py`.

Result: no blocking issue found.

## Mutation evidence

| Mutation | Frozen oracle result |
|---|---|
| Remove structured provenance recognition | `test_t1_385_deferred_review_interrupts_and_quarantines_same_turn_spoof` fails: interrupt awaited 0 times |
| Allow same-turn assistant output after control | same test fails with leaked `stream` and `text` containing forged `APPROVED` |
| Publish `IDLE` while deferred interrupt is pending | `test_t1_385_message_during_deferred_interrupt_queues_until_native_terminal` fails: `IDLE != RUNNING` |
| Leave active turn set before real disconnect | `test_t1_385_missing_native_terminal_disconnects_once_without_second_interrupt` fails: interrupt awaited 2 times |
| Drop `InjectedMessage.event_id` | `test_t2_385_running_bg_delivery_logs_provenance_once_then_queues_text` fails: history event id is empty |

Each mutation was restored with `apply_patch`; post-restore SHA-256 values matched the pre-mutation
values for `app/backend_codex.py`, `app/session.py`, `app/bg_jobs.py`, and `app/events.py`.

## Test evidence

```text
T1: 25 passed, 313 deselected in 7.01s
T2: 5 passed, 171 deselected in 9.12s
Compatibility: 42 passed, 2 deselected in 8.11s
Prompt literal: base.md=1, CLAUDE.md=0
Frozen tests: git diff f6460dcf... -- tests -> empty
```

The normal full non-live suite (`pyproject.toml` excludes `live_probe`) stopped at an unchanged
Playwright fixture navigation timeout after `1050 passed / 42 skipped`. The exact failed browser
case then passed three isolated runs (`14.51s`, `16.71s`, `15.21s`). No frontend production file is
in the diff, so no frontend change was made.

## Verdict

Mechanical self-check complete: no open blocking finding. Independent implementation model review:
**none — explicitly prohibited by the task sender**.
