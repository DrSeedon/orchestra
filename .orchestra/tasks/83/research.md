# Research #83 — Real-time token streaming in dashboard

**Status:** Phase 1 (research only). No implementation.
**SDK:** `claude-agent-sdk==0.2.87`, CLI = Claude Code.
**Captured live** via `docs/tasks/83/capture_partial.py` → `docs/tasks/83/partial_dump.jsonl`.

---

## TL;DR

- `include_partial_messages=True` works. The SDK emits a **`StreamEvent`** object (the Python name; the docstring's `SDKPartialAssistantMessage` is the TS SDK name) per partial update.
- `StreamEvent.event` is the **raw Anthropic API SSE event** (`message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`).
- **The CLI batches deltas** — text arrives in chunks of **~80–100 chars, ~5/sec**, NOT token-by-token. Good enough for "live typing" UX; not raw character streaming.
- Current architecture is **fundamentally pull-based** (SQLite poll over SSE, 0.5–3s latency). Real-time streaming needs an **in-memory pub/sub fan-out that bypasses the DB**.
- **Recommendation:** keep SSE (not WebSocket), add an in-process per-session pub/sub broker, stream partial text live, persist only the final assembled `AssistantMessage` to DB (as today). Effort: **~1.5–2.5 days**.

---

## 1. What `StreamEvent` / partial messages contain

### 1.1 SDK type (`claude_agent_sdk/types.py:1170`)

```python
@dataclass
class StreamEvent:
    """Stream event for partial message updates during streaming."""
    uuid: str
    session_id: str
    event: dict[str, Any]          # The raw Anthropic API stream event
    parent_tool_use_id: str | None = None
```

- Exported from package top-level: `from claude_agent_sdk import StreamEvent`.
- Part of the `Message` union (`types.py:1261`), so it arrives in the same `receive_messages()` async iterator we already consume in `backend_claude.events()`.
- Parsed in `_internal/message_parser.py:279` from wire `{"type": "stream_event", "uuid", "session_id", "event", "parent_tool_use_id"}`.
- `parent_tool_use_id` is set when the partial belongs to a **subagent** (Task tool) — lets us route subagent streaming separately from the main agent.

### 1.2 The flag (`types.py:1776`)

```python
include_partial_messages: bool = False
```
Adds `--include-partial-messages` to the CLI invocation. Orchestra currently sets it to **`False`** hardcoded at `app/backend_claude.py:137`.

### 1.3 Inner event shapes (captured live, haiku)

The `event` dict mirrors the [Anthropic Messages streaming API](https://docs.claude.com/en/api/messages-streaming). One full turn produces this sequence:

| order | `event.type`          | payload of interest |
|-------|-----------------------|---------------------|
| 1 | `message_start`         | `event.message` = full message stub (role, model, empty content, usage with input tokens) |
| 2 | `content_block_start`   | `index`, `content_block` = `{"type":"text","text":""}` (or `thinking` / `tool_use`) |
| 3 | `content_block_delta` × N | `index`, `delta` = `{"type":"text_delta","text":"…"}` |
| 4 | `content_block_stop`    | `index` |
| 5 | `message_delta`         | `delta.stop_reason`, **`usage`** (output_tokens, cache tokens) |
| 6 | `message_stop`          | (empty) |

**Delta variants** (`delta.type`) we care about:
- `text_delta` → `{"type":"text_delta","text":"chunk"}` — assistant text
- `thinking_delta` → `{"type":"thinking_delta","thinking":"chunk"}` — extended thinking
- `input_json_delta` → `{"type":"input_json_delta","partial_json":"…"}` — streaming tool-call arguments
- `signature_delta` → thinking signature (ignore for UI)

`content_block_start.content_block.type` tells you which block is streaming: `text`, `thinking`, `tool_use` (with `id` + `name`), `server_tool_use`, etc.

Captured `content_block_delta` sample:
```json
{
  "type": "content_block_delta",
  "index": 0,
  "delta": { "type": "text_delta", "text": "🤖 Окей, считаю как первоклассник" }
}
```

Captured `message_delta` (carries running usage — useful for live token counter):
```json
{
  "type": "message_delta",
  "delta": { "stop_reason": "end_turn", "stop_sequence": null },
  "usage": { "input_tokens": 3, "cache_creation_input_tokens": 43033,
             "cache_read_input_tokens": 0, "output_tokens": 291 }
}
```

### 1.4 Frequency / latency (measured)

From the capture (haiku, "count 1→30" ≈ 393 chars of output):

```
StreamEvent total:        9   (1 message_start, 1 block_start, 4 deltas,
                                1 block_stop, 1 message_delta, 1 message_stop)
text_delta events:        4
total chars:            393
avg chars/delta:         98.2
stream span:            0.74s
deltas/sec:              5.4
```

**Critical insight:** the Claude Code CLI **buffers/coalesces** the raw API stream before handing it to the SDK. We do NOT get per-token deltas — we get **~80–100 char chunks at ~5/sec**. (Raw Anthropic API streams ~1–5 chars/token at 20–60 tokens/sec.) The CLI's aggregation is fixed behavior; we can't make it finer.

**Implication:** UX will look like "fast paragraph-by-paragraph reveal," not a typewriter. Still a huge win over today's "nothing until the whole block is done." For longer outputs (real agent turns) there will be many more chunks, but cadence stays ~few-per-second.

### 1.5 Relationship to the existing full message

After all partials for a block, the SDK **still emits the assembled `AssistantMessage`** (confirmed in capture: `StreamEvent: 9` + `AssistantMessage: 1` + `ResultMessage: 1`). So partials are **additive** — enabling the flag does NOT remove the messages Orchestra already handles. We can:
- stream partials to the UI live (ephemeral), AND
- keep persisting the final `AssistantMessage` to DB exactly as today (`_convert` → `text` event → `add_log`).

No DB schema change required. No change to how cost/usage is computed (still from `ResultMessage`).

Also observed: `SystemMessage` ×2 (init + ...), `RateLimitEvent` ×1 — already handled/ignored upstream.

---

## 2. Pipeline map — where streaming must be injected

### 2.1 Current flow (turn output)

```
ClaudeSDKClient.receive_messages()             [SDK async iterator]
  └─ backend_claude.events()                   app/backend_claude.py:189
       └─ _convert(msg) → [AgentEvent]          app/backend_claude.py:241
            (AssistantMessage → "text"/"thinking"/"tool_use" events)
  └─ session._claude_event_loop()              app/session.py:414
       └─ _handle_event(event)                 app/session.py:518
            └─ self._log(type, content)        app/session.py:874
                 └─ add_log(id, ts, type, content)  app/db.py:633   [INSERT INTO logs]
                                                                      ▲ DB write
─────────────────────────────────────────────────────────────────────────────
GET /api/sessions/{name}/stream                app/routes/sessions.py:272
  └─ event_generator(): poll get_logs(after_id) every 0.5–3s   [DB read loop]
       └─ yield "data: {json}\n\n"             SSE frames
  app.js connectSSE() → EventSource.onmessage  app/static/js/app.js:159
       └─ addChatEntry(type, content, ts)      app/static/js/app.js:2020
```

**The bottleneck for real-time:** every event round-trips through SQLite, and the SSE endpoint **polls** the DB on a 0.5s→3s backoff timer. Even if we logged each partial, latency would be 0.5–3s + we'd write hundreds of throwaway rows per turn (DB churn, `logs` table bloat).

### 2.2 Where to inject streaming

Two clean seams:

**Seam A — backend emits partials.** In `backend_claude._convert` (`backend_claude.py:241`), add a branch:
```python
elif isinstance(msg, StreamEvent):
    # extract text_delta / thinking_delta / tool block start
    events.append(AgentEvent("stream", chunk, metadata={...}))
```
and set `include_partial_messages=True` at `backend_claude.py:137`.

**Seam B — session fans out live (bypass DB).** In `session._handle_event` (`session.py:518`), add:
```python
elif event.type == "stream":
    self._publish_live(event)     # push to in-memory broker, NOT add_log
```
The `"text"`/`"thinking"` events from the final `AssistantMessage` keep going to `add_log` as today (persistence).

> **Why two event kinds (`stream` vs `text`)?** `stream` = ephemeral live partials (in-memory, never persisted). `text` = the final assembled block (persisted to DB, source of truth on reload/reconnect). This avoids double-rendering and keeps the DB clean. The frontend coalesces `stream` chunks into a "live" bubble, then replaces it when the persisted `text` row arrives (matched by block index / a turn sequence id).

### 2.3 The DB-bypass problem (the real work)

Today the SSE endpoint reads **only** from SQLite. Live partials must reach the browser without touching the DB. Options for the transport layer evaluated in §3.

---

## 3. Transport: SSE + in-memory buffer vs WebSocket

### 3.1 Constraints from the codebase

- Server is **FastAPI/Starlette**, single process (`uvicorn app.main:app`), already serves SSE via `StreamingResponse`.
- Frontend already uses `EventSource` with auto-reconnect (`app.js:159`, `:201`).
- Sessions run in the **same event loop** as the HTTP server (`asyncio.create_task` in `session.py`), so an in-process broker is trivial — no IPC, no Redis.
- Auth is cookie/Bearer middleware that already covers the SSE route.

### 3.2 Option A — SSE + in-memory pub/sub broker (RECOMMENDED)

Add a tiny per-session broker (one `asyncio.Queue` per connected viewer, or an `asyncio.Event`+ring-buffer). Session publishes partials; the SSE generator drains the queue instead of (or in addition to) polling the DB.

```
session._publish_live(event)
   └─ broker[session_id].publish(event)        # in-memory, O(subscribers)
         └─ each subscriber asyncio.Queue.put_nowait(event)

GET /stream generator:
   - subscribe to broker[session_id]
   - on connect: replay last DB logs (history) as today
   - then: await queue.get()  → yield live frames immediately (no 0.5s poll)
   - persisted "text" rows still arrive via the same queue (published from _log) OR
     via a periodic catch-up read
```

**Pros**
- Reuses existing `EventSource` client + reconnect logic — **near-zero frontend rewrite** for transport.
- No DB writes for partials → no log-table bloat, no churn.
- Latency = network only (~tens of ms), vs 0.5–3s today.
- Same auth middleware, same route, same `text/event-stream`.
- Survives the existing "reconnect on error" path: on reconnect the client replays DB history (persisted finals) and resubscribes — partials lost mid-flight don't matter because the final `text` row is authoritative.

**Cons**
- Need to manage subscriber lifecycle (add on connect, remove on disconnect — `request.is_disconnected()` already polled at `sessions.py:287`).
- Multiple viewers of the same agent = multiple queues (fine; agents rarely have >2 viewers).
- SSE is one-directional (server→client) — but we don't need client→server over this channel (sends use POST `/send`).

### 3.3 Option B — WebSocket

Replace/augment the SSE channel with a WS endpoint.

**Pros**
- Bidirectional (could carry `/send` too), slightly lower per-message overhead.
- Cleaner backpressure semantics.

**Cons**
- **Rewrites the frontend transport** (`EventSource` → `WebSocket`), including the battle-tested reconnect/replay logic at `app.js:159–206`.
- New auth handling (WS upgrade doesn't always carry cookies the same way through proxies; Orchestra runs behind Hiddify proxy + on VPS behind nginx — `X-Accel-Buffering: no` is already set for SSE, WS needs its own nginx `Upgrade` config).
- No real benefit: we don't need client→server on this channel; sends already work via POST.
- More moving parts for the same outcome.

### 3.4 Verdict

**SSE + in-memory broker.** WebSocket buys bidirectionality we don't need at the cost of a frontend transport rewrite and proxy/nginx reconfig. The latency win comes entirely from **bypassing the DB poll**, which both options share — so pick the one that reuses the most existing code.

---

## 4. Recommended architecture

```
                        ┌────────────────────────────────────────────┐
                        │ ClaudeBackend (include_partial_messages=True)│
                        │  _convert: StreamEvent → AgentEvent("stream")│
                        │            AssistantMessage → "text" (final) │
                        └───────────────┬──────────────────────────────┘
                                        │ events()
                        ┌───────────────▼──────────────┐
                        │ session._handle_event         │
                        │  "stream" → _publish_live()   │ (in-memory, NO DB)
                        │  "text"   → _log() → add_log  │ (DB, as today)
                        └───────┬───────────────┬───────┘
                                │               │
                  ┌─────────────▼──┐      ┌─────▼──────────┐
                  │ LiveBroker      │      │ SQLite logs    │ (source of truth,
                  │ {sid: [queues]} │      │                │  history/reconnect)
                  └───────┬─────────┘      └─────┬──────────┘
                          │ live partials        │ persisted finals
                  ┌───────▼──────────────────────▼───────┐
                  │ GET /stream generator                 │
                  │  1. replay DB history (on connect)    │
                  │  2. subscribe to broker               │
                  │  3. yield live partials + finals      │
                  └───────────────┬───────────────────────┘
                                  │ SSE frames
                  ┌───────────────▼───────────────────────┐
                  │ app.js: EventSource.onmessage          │
                  │  type==="stream" → append to live bubble│
                  │  type==="text"   → finalize/replace     │
                  └────────────────────────────────────────┘
```

### Event contract additions
- New `AgentEvent.type = "stream"` with `metadata = {kind: "text"|"thinking"|"tool_input", block_index, turn_seq, parent_tool_use_id}`.
- Frontend: a "live" bubble keyed by `(turn_seq, block_index)`; partials append; the matching persisted `text`/`thinking` row replaces it (or we just stop appending and let the persisted row be canonical on reload).

### What NOT to change
- DB schema (`logs` table) — partials never persisted.
- Cost/usage accounting (`session_turns`/`ResultMessage`) — unchanged.
- POST `/send`, compact, hibernate, reconnect logic.
- WebSocket — not introduced.

---

## 5. Risks & edge cases

| # | Risk | Mitigation |
|---|------|------------|
| 1 | **Double rendering** — partial bubble + persisted `text` row both show. | Key live bubble by `(turn_seq, block_index)`; on persisted `text` arrival, replace the bubble (don't append). Or: render partials only, and on reconnect rely on DB history. |
| 2 | **Reconnect mid-stream** loses partials. | Final `text` row in DB is authoritative; client replays history on reconnect → no data loss. Partials are best-effort. |
| 3 | **Mid-turn inject** (`send()` during RUNNING) interleaves with stream. | Partials carry `turn_seq`; UI groups by turn. Inject already works via stdin (`session.py:298`). |
| 4 | **Subagent streaming** floods the channel. | `parent_tool_use_id != None` → route to subagent sub-bubble or drop partials for subagents (keep only `subagent_progress` summaries as today). Decide in plan. |
| 5 | **Multiple viewers** of one agent. | Broker fan-out: one queue per viewer; bounded `maxsize` + drop-oldest on slow consumer (partials are ephemeral). |
| 6 | **Slow/disconnected client** backpressure. | Bounded queue, `put_nowait` with drop-on-full. Never block the session event loop on a viewer. |
| 7 | **CLI buffers deltas** (~98 chars/chunk). | Accept it — still smooth. Don't over-engineer client-side typewriter. |
| 8 | **`thinking_delta`** streamed but UI may hide thinking (`HIDE_THINKING`, `app.js:2021`). | Respect existing toggle: drop `kind=="thinking"` partials when hidden. |
| 9 | **Cost** — `include_partial_messages` adds no API cost (same stream, just surfaced). Verified: usage in `message_delta` matches `ResultMessage`. | None. |
| 10 | **Other backends** (codex/opencode) don't have this. | `stream` events are claude-only; broker is backend-agnostic, just no partials from others. No regression. |
| 11 | **Tool-call args streaming** (`input_json_delta`) is partial JSON — not parseable until `content_block_stop`. | For tool calls, show a "calling X…" spinner from `content_block_start`, render full input from the persisted `tool` log. Don't try to parse partial JSON. |

---

## 6. Effort estimate

| Component | Work | Est. |
|-----------|------|------|
| Backend: enable flag + `StreamEvent`→`AgentEvent("stream")` in `_convert` | small, isolated | 0.25d |
| `LiveBroker` (in-memory pub/sub, per-session queues, lifecycle) | new module ~60 LOC | 0.5d |
| `session._publish_live` + `_handle_event` "stream" branch + turn_seq | small | 0.25d |
| SSE generator: subscribe to broker + replay history + merge | moderate (touches `sessions.py:272`) | 0.5d |
| Frontend: live bubble, append partials, finalize on persisted row, respect HIDE_THINKING | moderate (touches `app.js:159`, `:2020`) | 0.5d |
| Tests (broker fan-out, drop-on-full, reconnect replay) + Codex review | | 0.5d |
| **Total** | | **~2.5 days** (1.5d if subagent streaming + tool-arg streaming deferred) |

---

## 7. Open questions for the orchestrator (decide before planning)

1. **Subagent partials** — stream them too (nested bubbles), or keep only `subagent_progress` summaries as today? (Recommend: defer, summaries only for v1.)
2. **Thinking partials** — stream live, or only stream final text? (Recommend: stream both, respect `HIDE_THINKING`.)
3. **Persist nothing for partials** confirmed acceptable? (Recommend: yes — finals in DB are the record.)
4. **Scope** — v1 = main-agent text streaming only; defer tool-arg streaming + subagents? (Recommend: yes, ship the 1.5d version first.)

---

## References

- Anthropic Messages streaming API: https://docs.claude.com/en/api/messages-streaming
- SDK type: `claude_agent_sdk/types.py:1170` (`StreamEvent`), `:1776` (`include_partial_messages`)
- SDK parser: `claude_agent_sdk/_internal/message_parser.py:279`
- Capture script + raw dump: `docs/tasks/83/capture_partial.py`, `docs/tasks/83/partial_dump.jsonl`
- Key Orchestra files: `app/backend_claude.py:137,189,241`; `app/session.py:414,518,874`; `app/routes/sessions.py:272`; `app/db.py:633`; `app/static/js/app.js:159,2020`
