---
slug: review-impl
topic: implementation review #83 real-time streaming
model: gpt-5.5
reasoning: high
---

# Codex Implementation Review — #83 real-time token streaming

## Verdict: APPROVED — 0 blocking bugs

Codex (gpt-5.5, high reasoning, read-only) reviewed the four highest-risk areas and found no reproducible defects.

## Findings (по 4 риск-зонам)

1. **Subscription leak** — NONE. `event_generator()` wraps the whole streaming loop in `try/finally`; every exit path (`return`, client disconnect, cancel, exception on `yield`/`get_logs`/`sleep`) passes through `finally`, which calls `broker.unsubscribe(session_id, q)` + `c.close()`. No hanging subscription.

2. **Broker race** — NONE. `subscribe`/`publish`/`unsubscribe` are all synchronous (no `await`); the session listener runs via `asyncio.create_task` in the SAME event loop. No dangerous mutation between the `tuple(...)` snapshot and `put_nowait`.

3. **Ordering / orphan bubble** — NONE. The generator drains the live queue BEFORE polling the DB. Even if the final `text` already landed in the DB in the same tick, the client receives `partial…` then `text`, and `streamBubble` is replaced with the authoritative final content. No orphan bubble.

4. **`_convert` scope filter** — CORRECT. `parent_tool_use_id is not None` cuts subagents; `event.type != content_block_delta` cuts service events; `delta.type != text_delta` cuts `thinking_delta`, `input_json_delta`, `signature_delta`. Only main-agent `text_delta` reaches the live stream.

## Notes

- Earlier `codex exec review --uncommitted` and a plan-style run did not write the `-o` file (sandbox write quirk); this verdict is from a focused read-only ephemeral run with full stdout captured. Raw session id: `019eea3c-9f82-70e3-9fdc-9f0bdba70e9b`.
- Tests: +14 new (test_live_broker 7, test_backend_stream 7), all green. Full suite: 14 pre-existing failures (event-loop pollution from `manager._spawn_queue`, unrelated — see BUGS.md), +14 added by this task all passing, 0 new regressions.
