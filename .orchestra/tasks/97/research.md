# Task #97 — research: Codex worker stays `idle` until the next message

> Task-number collision: `docs/tasks/97/` previously described the June OpenCode
> SSE incident from commit `1244d7f`. Task #97 was reused for the July Codex
> inbox incident. Git retains the old artifact; this file now answers the current
> task.

## Question

- **Context:** a loaded Orchestra worker receives a message through
  `POST /api/sessions/{name}/send`; Codex uses a per-turn listener over one
  persistent app-server process and thread.
- **Change under test:** determine why the first message is followed by an
  externally visible `idle`, while the next message makes the earlier work and
  logs appear.
- **Baseline:** one idle send must start exactly one matching listener, and that
  listener must terminate only on the terminal event of the turn just started.
- **Outcome:** a mechanism is accepted only if it explains a real incident's
  timestamps and is reproduced through the real `CodexBackend` and
  `AgentSession` functions.

## Hypotheses and falsifiers

### H1 — AgentSession is internally `RUNNING`, the dashboard alone is stale

The proposed version was: the in-memory session remains `RUNNING`, the dashboard
shows `idle`, and `send()` therefore appends the first message to
`_pending_messages`.

**Falsifier:** the loaded-session API reads `AgentSession.to_dict()` directly,
the incidents contain a persisted terminal transition, no queue log, and the
real reproduction leaves `_pending_messages` unused.

**Result: REFUTED in that form.** There is a real status desynchronization, but
it is between the active Codex turn and `AgentSession`, not between the
in-memory session and dashboard/SQLite. Orchestra genuinely and incorrectly
sets its own state to `IDLE`.

### H2 — `_lifecycle_lock` is held by reconnect/compact/hibernate

**Falsifier:** the first `POST /send` returns `200`, records its user message,
starts a Codex turn, and reaches false `turn_end` immediately rather than
waiting on the lock.

**Result: REFUTED for every confirmed incident.** The journal records `200 OK`
in the same second; SQLite timestamps put false completion 2–56 ms after the
first message. A blocked lifecycle lock cannot produce that sequence.

### H3 — hibernate loses a message at the sleep/wake boundary

**Falsifier:** confirmed cases use a runtime with hibernate disabled, and the
same signature is absent from Claude rows.

**Result: REFUTED for this incident class.** Codex registers
`hibernate=False`; all seven completed cases and the eighth still-unwoken case
are Codex. Claude's hibernate and `send()` paths also serialize on the same
`_lifecycle_lock`. No independent hibernate case was found in the copied DB.

### H4 — native Codex compact leaves its terminal event in the next turn's queue

**Falsifier:** any of the following would refute it:

1. affected workers had no completed native compact before the bad send;
2. the first post-compact listener did not replay compact events;
3. terminal events were matched to the currently started turn;
4. the real compact/send/events/session path did not reproduce the lag.

**Result: CONFIRMED.** All four falsifiers failed.

## Root cause

Native Codex compact and ordinary turns share
`CodexBackend._notifications`, but only ordinary turns have a consumer:

1. `CodexBackend._read_stdout()` calls
   `_complete_compaction_from_notification(message)` and then unconditionally
   puts the same message into `_notifications`
   (`app/backend_codex.py:524-528`).
2. `compact_context()` completes as soon as a context-compaction completion
   notification resolves `_compact_future`; it does not consume or remove the
   compact's `item/started`, `item/completed`, or terminal `turn/completed`
   notifications (`app/backend_codex.py:384-427,577-603`).
3. During the next idle `AgentSession.send()`, Codex accepts a new
   `turn/start`; its RPC result contains the new turn id and `send()` stores it
   in `_active_turn_id`. Orchestra then creates the per-turn
   `_turn_event_loop` (`app/backend_codex.py:328-337`;
   `app/session.py:538-546,602-625`).
4. That listener does not snapshot the id returned by `turn/start`. It first
   drains the old compact notifications. The delayed compact `turn/started`
   overwrites `_active_turn_id` with the compact turn id
   (`app/backend_codex.py:621-625`).
5. The following compact `turn/completed` clears `_active_turn_id`, becomes an
   ordinary `AgentEvent("turn_end")`, and makes `events()` exit. Neither
   `_convert_notification()` nor `events()` checks the notification's
   `turn.id` against the id returned by the current `turn/start`
   (`app/backend_codex.py:339-369,763-766`).
6. `TurnManager` treats that stale terminal as the current turn's completion.
   `TurnManager` persists `IDLE` (and, on current main after #91, publishes
   `_turn_finished_event`) even though the newly started Codex turn is still
   working.
7. `_read_stdout()` continues buffering the real turn's text/tools/completion,
   but its per-turn listener has exited.
8. The next `send()` sees the false `IDLE` and cleared `_active_turn_id`, starts
   another Codex turn and another listener. That listener drains the previous
   turn's buffered events. To the user, the old task suddenly starts after
   “ау”; internally, delivery is now one turn behind.

This is **not** `_flush_pending()`: no affected incident has
`message queued (...)`, and the reproduction does not populate
`AgentSession._pending_messages`. The next message's side effect is creation of
the next `_turn_event_loop`, not a pending-message flush.

## Production evidence

### Read-only acquisition

The live database was opened with SQLite `mode=ro` and backed up to
`/tmp/orchestra-97-OWPQXH.db`; the copy was then made mode `0444`. All SQL below
ran against that copy. The source DB was not mutated.

The exact signature was:

1. successful native Codex compact;
2. later first `user_message`;
3. replayed `codex compacting context` / `codex context compacted`;
4. false `turn ended` within one second and no model activity;
5. first model activity only after the next `user_message`.

Eight sessions match the compact/replay/false-end signature. Seven already have
a later wake message; `mcp-direct` had not received one at snapshot time.

| Session | First message UTC | Minutes after compact | False end after send | Next send after | First activity |
|---|---:|---:|---:|---:|---|
| `polish-tg` | 2026-07-25 13:20:40.685 | 45.8 | 10 ms | 909.5 s | 2 ms after next send |
| `terrain-dev` | 2026-07-25 18:32:56.287 | 212.6 | 3 ms | 474.3 s | 10 ms after next send |
| `legal-152fz` | 2026-07-26 15:42:20.227 | 37.7 | 21 ms | 883.5 s | 22 ms after next send |
| `kesha-tg-bot` | 2026-07-28 07:24:27.384 | 21.1 | 2 ms | 646.4 s | 234 ms after next send |
| `seo-cro` | 2026-07-28 09:28:42.497 | 151.4 | 41 ms | 989.8 s | 13 ms after next send |
| `audit-worktree` | 2026-07-28 09:30:36.697 | 141.2 | 34 ms | 816.2 s | 14 ms after next send |
| `impl-game-ux` | 2026-07-28 09:35:22.761 | 100.7 | 56 ms | 683.7 s | 126 ms after next send |
| `mcp-direct` | 2026-07-28 09:39:29.182 | 130.8 | 34 ms | not yet | no activity yet |

Across the seven completed cases, the first model activity appears 2–234 ms
after the next send (mean 60 ms). The same query found **zero Claude cases**.

### Concrete incident: `audit-worktree`

```text
07:08:55.842  compact started (native Codex, context 67%)
07:09:24.004  compact done (native Codex): 67% → 14%

09:30:36.697  first task from Orchestra-orchestrator
09:30:36.731  codex compacting context
09:30:36.731  codex context compacted
09:30:36.731  codex turn=019fa78e... started
09:30:36.731  turn ended (... $0.00 turn ...)       # false, +34 ms

09:44:12.886  "ау"
09:44:12.899  prior task's first text and buffered activity appear
```

The Codex rollout is the missing transport-side clock. It records when the
app-server emitted the events, while SQLite records when Orchestra later
consumed them:

| App-server event UTC | Actual turn id | Orchestra consumes/logs it |
|---|---|---|
| 07:08:55.854 `task_started` (compact) | `019fa78e-1aa2-75e2-bff6-9f79c59424df` | 09:30:36.731, after the first task |
| 07:09:24.001 `task_complete` (compact) | `019fa78e-1aa2-75e2-bff6-9f79c59424df` | 09:30:36.731, false `$0` terminal |
| 09:30:36.824 `task_started` (first task) | `019fa80f-d138-7c03-9506-af5cb2d829d1` | 09:44:12.899, after “ау” |
| 09:42:01.134 `task_complete` (first task) | `019fa80f-d138-7c03-9506-af5cb2d829d1` | 09:44:12.931, prior task ends |
| 09:44:12.922 `task_started` (“ау”) | `019fa81c-4562-7ee0-8b67-a5a992ac8263` | 09:46:28.564, after the next wake |

The compact and first-task ids are therefore both present and unequal. The
SQLite `codex turn=019fa78e... started` row at 09:30 is not the id returned by
the 09:30 `turn/start`; it is the compact's delayed `turn/started`. The first
task actually runs from 09:30:36 to 09:42:01 under `019fa80f...`, but its
listener has already exited on compact terminal `019fa78e...`. The same
one-listener-behind sequence repeats for “ау” under `019fa81c...`.

The systemd journal independently records:

```text
16:30:36 [audit-worktree] listen task exited without exception,
         status=AgentStatus.IDLE
16:30:36 POST /api/sessions/audit-worktree/send 200 OK
```

The same journal signature occurs for `impl-game-ux` at 16:35:22 and
`mcp-direct` at 16:39:29.

### Prior named incident: `legal-152fz`

The earlier report is the same bug, not a separate compaction/session-reset
theory:

```text
15:04:36.432  native compact done
15:42:20.227  Phase 2 task received
15:42:20.248  false turn end (+21 ms), compact events replayed
15:57:03.718  explicit ping
15:57:03.739  first Phase 2 model text (+22 ms after ping)
```

### Queue/error counter-evidence

The whole copied database contains only one queue-status row:
`inject failed, queued (1 pending)` for `upgrade-claude5` on July 25. It was
followed by manual interrupt and server restart, not the “next message releases
the previous task” signature. There are no `message queued (N pending)` or
`message queued (race, ...)` rows.

## Reproduction through real project functions

The isolated `/tmp` experiment used:

- real `CodexBackend.compact_context()`;
- real `CodexBackend._read_stdout()` over JSONL notifications;
- real `CodexBackend.send()` and `events()`;
- real `AgentSession.send()` and `_turn_event_loop()`;
- DB persistence and external callbacks replaced with no-op functions.

It fed the compact lifecycle actually observed in logs, then one real turn.
Raw output:

```text
after compact: ok=True queued_transport_notifications=3
after FIRST send/listener: status=idle active_turn=None
FIRST logs: ['FIRST', 'codex compacting context',
             'codex context compacted', 'turn ended (... $0.00 turn ...)']
while externally idle: buffered_first_turn_notifications=3
after SECOND send/listener: status=idle active_turn=None
SECOND flushed FIRST: ['FIRST_PROCESSED']
REPRO=PASS: first work stayed buffered until second send created the next listener
```

This reproduction passes on current main too, so #91 does not fix it.

Existing focused tests are green:

```text
tests/test_backend_codex.py native compact/send tests: 3 passed
tests/test_session.py Codex compact tests:             4 passed
```

They miss the defect because backend compact tests call
`_complete_compaction_from_notification()` directly and never exercise
`_read_stdout()`'s unconditional enqueue; session compact tests replace the
backend with `MagicMock`, so no shared notification queue exists.

## Runtime and deployment findings

- `claude`: persistent event listener, `mid_turn_inject=True`,
  `hibernate=True`. It does not use the affected native Codex compact queue.
- `codex`: per-turn listener, `mid_turn_inject=True`, `hibernate=False`.
  Confirmed affected.
- `grok` / `opencode`: per-turn listeners, `mid_turn_inject=False`,
  `hibernate=False`, but they do not use `CodexBackend` or its native compact
  queue. No matching live evidence was found.

The task brief said the server had not restarted since July 25. The live process
shows otherwise:

```text
ExecMainStartTimestamp=Tue 2026-07-28 12:27:44 +07
PID 398929 /.../.venv/bin/python3 -m uvicorn app.main:app ...
```

Main's latest commit before that start was `2c33547`; #91 (`92da149`) was
committed at 13:24:33 +07, so today's 16:28–16:39 incidents ran without #91.
The relevant `backend_codex.py`, compact, and send/listener paths are unchanged
between deployed `2c33547` and current main. The reproduction against current
main proves that a restart would not remove this defect. After #91, the stale
compact terminal additionally publishes the new lifecycle completion event,
so merge/switch waiters can trust the same false completion.

## Confidence by finding

1. **CONFIRMED — native compact terminal poisons the next Codex listener.**
   Tier 1: seven complete production sequences, one pending sequence, systemd
   journal, exact app-server rollout turn ids, and deterministic reproduction
   through the real functions.
2. **CONFIRMED — the next message creates a listener; it does not flush
   `_pending_messages`.** Tier 1/2: reproduction plus actual send/flush code and
   absence of queue logs.
3. **CONFIRMED — the precise bug is Codex-specific.** Tier 1/2: all matching DB
   rows are Codex and the cause lives in `CodexBackend`; runtime registry
   disables hibernate for Codex.
4. **REFUTED — #91 introduced today's incidents.** Tier 1/2: process start and
   Git timestamps show #91 was not loaded; current-main reproduction shows it
   also does not solve them.
5. **REFUTED for this incident class — lifecycle-lock hang or hibernate race.**
   Tier 1/2: immediate `200`/false-end timestamps, runtime capability, and
   matching code paths.
6. **UNCERTAIN — unrelated rare causes may produce a superficially similar
   “idle/no output” report.** The copied DB has one old inject failure and one
   old persistent-listener anomaly, but neither matches the two-message
   sequence. No second independent cause is proven.

## Counter-evidence and limits

- SQLite timestamps record when Orchestra consumes and persists a notification,
  not when Codex originally emitted it. That is why a whole prior turn appears
  in a millisecond burst after the wake message. The independent rollout
  timestamps close this limitation and prove the notification stream is one
  turn behind.
- The user's wording says work “starts” on the second message. The evidence
  shows Codex starts and completes the first task from 09:30:36 to 09:42:01;
  its output is invisible because its listener terminated on the compact
  event. The second send makes the previous output observable and starts
  another backend turn.
- `mcp-direct` had not received its wake message in the snapshot, so only its
  compact replay and false terminal are confirmed; the final release step is
  predicted by the seven complete cases and reproduced behavior.
- The first adversarial Codex review rejected the proposed identity guard:
  the reproduction did not record both ids, and a delayed `turn/started` could
  still overwrite `_active_turn_id`. The rollout supplies both unequal ids,
  and the fix direction below now matches both lifecycle edges against an
  immutable expected id before `_convert_notification()` can mutate state.
  On resume, the same reviewer marked both findings resolved and returned
  **APPROVED** with no remaining finding; the two-round record is preserved in
  `docs/tasks/97/codex-review-research.md`.

## Affected files, risks, and edge cases

- `app/backend_codex.py`
  - one shared notification queue for compact and turns;
  - `events()` terminates without turn-id matching;
  - unrelated terminal events clear `_active_turn_id`.
- `app/session.py`
  - each idle Codex send creates one per-turn listener;
  - false `turn_end` becomes real `IDLE`.
- `app/session_turns.py`
  - current #91 code publishes lifecycle completion for the false terminal.
- `tests/test_backend_codex.py`
  - missing integrated `_read_stdout` → compact → next turn test.
- `tests/test_session.py`
  - missing cross-component session status/listener regression.

Edge cases for a fix:

1. compact notifications can arrive before or after the compact future resolves;
2. a stale `turn/started` must not overwrite the id returned synchronously by
   the current `turn/start`;
3. mismatched `turn/completed` must not clear or terminate the current turn;
4. process exit still must terminate the current listener;
5. steering must keep using the immutable id returned for the real current
   turn, not the latest lifecycle notification consumed;
6. do not blindly clear the whole queue and lose legitimate current-turn
   notifications.

## Proposed fix direction (no code in Phase 1)

Enforce turn identity at the transport boundary:

1. `events()` snapshots an immutable `expected_turn_id` from the id stored from
   the immediately preceding `turn/start`, before dequeuing any notification.
2. Before calling `_convert_notification()`, `events()` compares both
   `turn/started` and `turn/completed` lifecycle ids with
   `expected_turn_id`. A mismatched delayed start must not mutate
   `_active_turn_id`; a mismatched terminal must not clear it, emit
   `turn_end`, or terminate the iterator. A matching start may be logged but
   does not replace the RPC-returned identity; only the matching terminal
   clears the active id and ends the iterator.
3. Native compact should also drain or suppress its own lifecycle notifications
   through its matching terminal event before releasing the lifecycle lock.
   Identity matching remains the safety invariant even if compact cleanup
   regresses later.
4. Add an integrated regression using the exact sequence from the reproduction:
   compact through `_read_stdout`, start one session turn, inject stale compact
   `turn/started` plus terminal followed by current-turn output, and assert:
   - `_active_turn_id` stays equal to the current `turn/start` result after
     both stale lifecycle events;
   - steering sends that same id as `expectedTurnId`;
   - session stays `RUNNING` after the stale terminal;
   - current output arrives without a second send;
   - `_pending_messages` remains empty;
   - only the matching current terminal publishes `IDLE` /
     `_turn_finished_event`.

Do not “fix” this by increasing sleeps, flushing `_pending_messages`, or clearing
the entire notification queue. None establishes which turn a terminal belongs
to.

## Sources

1. **Tier 1 — direct measurement:** read-only backup
   `/tmp/orchestra-97-OWPQXH.db`, SQL sequences and aggregate timings above.
2. **Tier 1 — direct measurement:** `journalctl -u orchestra`,
   2026-07-28 16:25–16:50 +07.
3. **Tier 1 — direct measurement:** isolated real-function reproduction, raw
   output recorded above.
4. **Tier 2 — primary source:** `app/backend_codex.py`,
   `app/session.py`, `app/session_turns.py`, `app/session_hibernate.py`,
   `app/runtime_registry.py`.
5. **Tier 2 — primary source:** deployed Git commit `2c33547`, #91 commit
   `92da149`, current main, and `git reflog main`.
6. **Tier 2 — primary source:** `tests/test_backend_codex.py`,
   `tests/test_session.py`.
7. **Tier 1 — direct measurement / primary runtime artifact:** Codex rollout
   `/home/maxim/.codex/sessions/2026/07/26/`
   `rollout-2026-07-26T21-57-49-019f9eee-aaac-7dc1-a941-64bb8b26f867.jsonl`,
   lines 2421–2710.
