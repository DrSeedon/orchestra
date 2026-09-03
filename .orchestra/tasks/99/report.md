# Report #99 — recurring command monitors and Telegram topic hysteresis

## Outcome

Both approved tickets are complete.

- T1 is already deployed as commit `6346f72`: `cron_command` runs a command on
  schedule and wakes the agent only when completed output matches the configured
  pattern. Four no-match fires remain entirely server-side.
- T2 makes the running topic icon immediate and delays idle for five minutes.
  A new running signal cancels only the idle-delay phase. Once a Telegram edit
  has started, later edits remain in the same per-topic worker and execute
  sequentially, so remote responses cannot reorder the final icon.
- Startup status synchronization is immediate, idempotent, serialized across
  topics, and uses the same per-topic owner as runtime updates.
- Topic-status failures now log at warning level as
  `ExceptionClass: message`. `TOPIC_NOT_MODIFIED` remains a successful update,
  and failed edits do not update the local status cache.

## Startup failure diagnosis

The restart journal established the failure mechanism rather than merely
suggesting it:

- deferred startup completed at `15:38:43.026731`;
- 17 empty `TG topic_status failed:` records arrived together at offsets
  `+4.989` through `+4.992` seconds, followed by one at `+9.991` seconds;
- the outer topic-status timeout is exactly five seconds;
- the old startup sync scheduled all topic edits concurrently;
- the local `telegram-bot-api` journal showed outbound proxy activity throughout
  the burst, and an earlier equivalent burst later surfaced an explicit Telegram
  flood-control response.

Therefore the empty error was `TimeoutError()` from the outer
`asyncio.timeout(5)`, whose string is empty. The bot existed and deferred
startup was running; the failure was the 30-topic concurrent edit burst through
the local Bot API/proxy path, not an uninitialized bot. Serial startup edits
remove that burst.

Warning is the appropriate level because a failed primary edit leaves the
visible icon and local cache unchanged. Repeated failures disable status
reporting and require operator action; they are not expected debug noise.

## Files

- `app/tg_bridge.py`: topic-status scheduling, five-minute idle fade, startup
  serialization, manifest-defined orchestrator support, and actionable error
  logging (`+72/-11` before this report).
- `tests/test_tg_bridge.py`: deterministic event-driven coverage for
  hysteresis, cancellation, startup/runtime races, manifest roles, cache
  behavior, and exception logging (`+343/-9`).
- `docs/tasks/99/codex-review-impl.md`: three-round implementation review.

The Telegram delivery queue and all #100 image-ordering code were untouched.

## Verification

- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_tg_bridge.py -q`
  → `125 passed in 3.31s`; raw output:
  `/tmp/pytest-99-tg-bridge-r3.log`.
- `git diff --check` → clean.
- All new timing assertions use controlled events or an injected delay
  coroutine; none depends on elapsed wall-clock time.
- Codex review required three rounds. It found and reproduced two ordering
  races, both fixed. Final verdict in `codex-review-impl.md`: **APPROVED**, no
  new findings.

## Compatibility and remaining work

No public API or configuration contract changes in T2. The internal
`_topic_status_desired` value now includes whether idle delay applies.

No TODO remains for #99. Deploying T2 still requires the orchestrator to merge
this commit and restart the Python service; this worker did not restart it.
