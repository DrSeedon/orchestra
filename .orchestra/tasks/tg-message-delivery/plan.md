# Plan — reliable Telegram topic delivery

## Scope and assumptions

Fix the observed sender-side losses without restarting Orchestra or changing system/proxy configuration. The live SOCKS route, local Bot API service, and topic map are healthy; implementation stays in `app/tg_bridge.py` plus focused tests.

Delivery policy:

- primary agent/user/error/file messages are **important** and use bounded at-least-once retry;
- the pretty-rendered `send_message` tool is also important because it is the user-visible record of inter-agent communication, not disposable tool diagnostics;
- timeout retry is ambiguous and may duplicate, so it is logged explicitly;
- tool/status/result-image/topic-icon traffic is **non-important** and drops before waiting when its chat is busy, flooded, or still inside the group interval;
- each chat has independent state; all topics in the primary supergroup share one lock and one 3.05-second interval;
- no explicit unbounded queue is added. Each `stream_logs()` coroutine already preserves its session's SQLite order while awaiting the per-chat lock.

## Changes

### `app/tg_bridge.py`

1. Replace scalar `_last_send`/`_flood_until` state with per-chat locks and timestamps.
2. Add `_tg_call_safe(chat_id, call, important, label)`:
   - serialize calls for the same chat;
   - use 3.05 seconds for negative group IDs and 1.05 seconds otherwise;
   - honor `TelegramRetryAfter` without a retry stampede;
   - retry `TelegramNetworkError` / `TelegramServerError` only for important calls, with a small bounded backoff and ambiguous-delivery logging;
   - reject non-important calls before queueing when the chat is already busy/throttled;
   - emit a distinct final `LOST` warning for an important call that still fails.
3. Make `_tg_send_safe()` use the generic limiter and retry a formatted `TelegramBadRequest` once without entities.
4. Add `_formatted_chunks()` that converts Markdown first, verifies final UTF-16 length, and sends multi-chunk output without entities.
5. Use `_formatted_chunks()` in agent text, generic log text, and pretty `send_message` rendering.
6. Route primary/mirror `sendMessage`, expandable sends, message edits, photos, documents, explicit files, result images, and topic-status edits through the per-chat limiter with the correct importance.
7. Reset limiter state in the existing bridge lifecycle so tests/restarts cannot inherit stale locks or flood timestamps.

### `tests/test_tg_bridge.py`

Add deterministic tests using fake/`AsyncMock` bots; no Telegram or proxy access:

- post-conversion Markdown table expansion is split into final payloads ≤4096 UTF-16 units with no cross-chunk entities;
- concurrent important sends to one group are serialized by the configured interval;
- separate chat IDs do not block each other;
- important 429 and transient network failures retry within bounds;
- formatted bad request retries once without entities;
- final important failure returns `None` and emits `LOST`;
- non-important traffic drops before queueing under contention/throttle;
- all send attempts retain the requested `message_thread_id`;
- explicit file delivery recreates its file object across retries and preserves topic routing.

## What not to touch

- no `.env`, `/etc/proxychains4.conf`, user proxychains config, systemd units, token, group IDs, or topic mappings;
- no incoming Telegram handlers, transcription, media batching, or topic creation/deletion behavior;
- no service restart or production Telegram send during verification;
- no broader `tg_bridge.py` split/refactor (a separate worker already owns that initiative).

## Migration and compatibility

No schema/config migration. Function signatures remain compatible except internal helpers may accept an `important` flag. The only intentional behavior change is shedding non-important TG chatter during bursts instead of triggering 429 and losing important text.

## Tickets

### T1 — Preserve formatted agent text end to end
- Files: `app/tg_bridge.py`, `tests/test_tg_bridge.py`
- AC:
  - three concurrent important sends to the same negative `chat_id` occur at least the configured interval apart;
  - different chat IDs can send independently;
  - `TelegramRetryAfter` and transient network/server errors retry important text within the configured bound;
  - important retry sleeps while retaining the per-chat lock, so later callers cannot stampede or overtake the retry;
  - an entity-related bad request retries the same visible text once with `entities=None`;
  - the historical table shape expands beyond 4096 only after Markdown conversion, yet every emitted chunk is ≤4096 UTF-16 units and multi-chunk output has no entities;
  - every attempt preserves the original non-null `message_thread_id`;
  - non-important send calls return without invoking the bot when the same chat is busy or inside its interval.
- blocked-by: none

### T2 — Put media, edits, files, mirrors, and topic status behind the same per-chat policy
- Files: `app/tg_bridge.py`, `tests/test_tg_bridge.py`
- AC:
  - no primary/mirror `bot.send_message`, `bot.send_photo`, `bot.send_document`, or high-frequency message edit in the delivery paths bypasses `_tg_call_safe` / `_tg_send_safe`, and the `"send_message"` tool pretty-render path uses `_formatted_chunks()`;
  - explicit `send_file_to_tg()` treats primary and mirror delivery as important, recreates `FSInputFile` for each transient retry, preserves each topic ID, and returns the primary delivered message ID;
  - result/diff images, `_edit_tool_with_result()`, `_edit_expandable()`, expandable output, and topic-icon updates are non-important; their `edit_message_text` / send call is not invoked while the chat lock is busy;
  - existing topic routing/file tests remain green.
- blocked-by: T1

### T3 — Verify the integrated regression and produce evidence
- Files: `docs/tasks/tg-message-delivery/codex-review-impl.md`, `docs/tasks/tg-message-delivery/report.md`, optional `retro.md`
- AC:
  - focused TG tests pass;
  - full `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q` passes;
  - adversarial diff review has no unresolved blocking finding;
  - `report.md` records test output, behavior tradeoffs, files, and the fact that no service restart occurred.
- blocked-by: T2
