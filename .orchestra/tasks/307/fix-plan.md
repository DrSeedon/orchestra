# #307 downstream behavior contract and local mitigation map

This is a research handoff, not an implementation plan for this worker. Orchestra code/tests were
owned by #306/#319 and were not edited here. The minimum behavior below is already represented on
`main` by `b11ba9be` and `db8708aa`; this file preserves the acceptance contract and rejected fixes.

## Required behavior

### 1. Bounded native resume

- For a stored native `threadId` resume (no history import), initialize with
  `capabilities.experimentalApi=true` and send `excludeTurns:true`.
- Accept the response only when `thread.id` equals the requested id.
- Preserve the live subscription/status and all runtime/config metadata; do not fetch historical
  turns because Orchestra does not consume them during connect.
- Keep explicit history import unchanged: it intentionally sends `history` and may receive a fresh
  id according to that contract.
- Unsupported CLI/capability must fail with an actionable protocol/version error. Do not silently
  retry an unbounded default resume on a thread already known to exceed the transport cap.

### 2. Oversized JSONL is terminal transport corruption

- A `readline()` size failure occurs before the envelope can be parsed. The client cannot know
  whether it lost a response, client request, notification, or terminal event.
- Stop/close only the poisoned app-server generation immediately; do not scan forward and trust
  later records.
- Reject all pending JSON-RPC futures and any compact future with a typed oversized-record error.
- Clear native active-turn state, surface `reader_failure`, finish false `RUNNING`, and recover
  queued messages through a bounded fresh-session/handoff path.
- Perform at most one bounded recovery attempt; repeated failure must stay loud.

### 3. Compact phase observability and late completion

- Distinguish these waits: request acknowledgement, context-compaction completion item, and
  terminal turn lifecycle.
- A timeout message must contain exception class, configured seconds, and phase. Never display a
  blank `str(TimeoutError())`.
- Late terminal notifications must not leak into the next ordinary turn or falsely complete it.
- A longer timeout may reduce false failures (the measured compact took ~135 s), but increasing the
  number alone is not a correctness fix; cancellation/detachment and late-event isolation remain
  mandatory.

## RED behavioral tests / acceptance checks

The code owner should preserve these behaviors as immutable oracles. Current-main names are included
where the merged mitigation already supplies them.

### T1 — metadata-only resume negotiates the experimental contract

- Production path: `connect()` request sequence, not a direct helper.
- Assert `initialize.capabilities == {"experimentalApi": True}` for stored-thread resume.
- Assert `thread/resume` has the requested `threadId`, `excludeTurns is True`, and no `history`.
- Assert a substituted response id fails before any turn starts.
- Existing coverage: `tests/test_backend_codex.py` resume-substitution/history-import cases around
  the `excludeTurns` assertions.

### T2 — losing any oversized record poisons the generation

- Feed `>16 MiB` without a newline; the reader must return without waiting for EOF, close/kill only
  that generation, fail the pending request with `CodexOversizedRecordError`, and emit one actionable
  `reader_failure` terminal event.
- Feed an oversized record followed by a syntactically valid `turn/completed`; it must not be trusted.
- Existing coverage:
  - `test_oversized_record_is_terminal_and_following_message_is_not_trusted`
  - `test_oversized_record_without_eof_aborts_instead_of_waiting_for_newline`
  - `test_oversized_record_closes_adopted_transport_and_verified_process`
  - `test_non_oversize_reader_value_error_is_loud`

### T3 — process exit and session status recover end to end

- Oversized resume fails the connect future, retires the backend, clears the native thread id, and
  performs no more than one fresh retry with bounded log handoff.
- An active lost turn becomes IDLE/finished and queued input is preserved for the replacement path.
- Existing coverage:
  - `test_codex_oversized_resume_retries_fresh_once_with_log_handoff`
  - `test_codex_oversized_resume_fallback_is_bounded_to_one_retry`
  - `test_active_codex_oversized_turn_retires_backend_before_next_send`
  - `test_codex_listener_without_active_turn_fails_idle_and_flushes_queue`
  - `test_codex_connect_failure_clears_running_status`

### T4 — compact lifecycle is actionable and isolated

- Ack arrives but completion never arrives: timeout must name `completion notification`, the class,
  and 120 s; compact listeners/futures detach.
- Completion item arrives but terminal turn does not: timeout must name `turn lifecycle`.
- A successful compact drains its terminal event before returning.
- A stale/late compact completion cannot finish the next ordinary turn.
- Existing coverage:
  - `test_native_compact_drains_terminal_before_returning`
  - `test_native_compact_missing_terminal_times_out_and_detaches`
  - `test_codex_compact_timeout_log_names_exception_and_stage`
  - `test_stale_compact_lifecycle_cannot_false_idle_current_turn`
  - `test_native_codex_compact_is_gated_before_backend`

## Rejected fixes

- **Raise `CODEX_STREAM_LIMIT`:** finite threshold only; upstream records already range far above
  16 MiB and can grow without a bound.
- **Discard one record and continue:** F1 proves the record can be the only required resume response.
- **Treat code-zero process exit as success:** pending request and lost framing still make connect fail.
- **Blame `codex_models_manager` stderr:** no causal link to the deterministic `id=2` replay.
- **Only increase compact timeout:** hides this 135 s case but does not identify phase or isolate late
  terminal events.
- **Open a new upstream issue or PR:** #21988 is the exact response-size family; upstream policy does
  not accept external PRs.

## Ownership and merged lineage

- Production/test ownership: `app/backend_codex.py`, `app/session.py`,
  `tests/test_backend_codex.py`, `tests/test_session.py` — #306/#319 code owner only.
- [`b11ba9be`](https://github.com/DrSeedon/orchestra/commit/b11ba9be1a7c54e936be00ebecbc69ca50fcff4f)
  (#307 on main): `excludeTurns`, terminal oversized transport, compact phase detail.
- `db8708aa` (#319 on local main; not yet on `origin/main` at measurement time): bounded
  cleanup/future rejection/message preservation on current main.
- This worker owns only `docs/tasks/307/` and `docs/workers/fix-codex-jsonl-reader.md`.
