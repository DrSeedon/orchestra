# Plan #83 — Real-time token streaming (v1, strict scope)

**Phase 2 plan.** Scope locked by orchestrator:
- ONLY main-agent **text** streaming (no subagent, no thinking, no tool-arg).
- SSE + in-memory pub/sub (NOT WebSocket).
- Partials ephemeral (NOT persisted); finals persist as today.
- Dashboard: typing bubble that finalizes on completion.
- TG: **no changes** (final-only).
- Must not break existing flow.

---

## 0. Key discovery (changes the effort)

**The frontend already handles `type: "stream"` events** — `app/static/js/app.js:2135-2167` (added 2026-05-01, commit `c82e725`). It's currently **dead code**: no backend emits `stream`, and `include_partial_messages=False`.

Existing client behavior (verified):
- `type === 'stream'` → accumulate into `streamContent`, create/update a `streamBubble`, re-render markdown each chunk (`app.js:2135`).
- `type === 'text'` while a `streamBubble` is open → finalize it (copy btn + timestamp), clear (`app.js:2153`).
- Any non-`text` event (tool call, status) while a bubble is open → also finalizes it (`app.js:2162`, `:2121`).
- `streamBubble`/`streamContent` reset on agent switch (`app.js:1093,1120`).

**Consequence:** v1 is **backend-only** + **one frontend reconciliation fix** (the dead-code path makes an ordering assumption we must satisfy or patch). No new client rendering needed.

---

## 1. Files changed

| File | Change | LOC |
|------|--------|-----|
| `app/backend_claude.py` | `include_partial_messages=True`; emit `AgentEvent("stream")` from `StreamEvent` text deltas | ~25 |
| `app/live_broker.py` | **NEW** — per-session in-memory pub/sub | ~55 |
| `app/session.py` | `_handle_event` "stream" branch → publish to broker (no DB) | ~10 |
| `app/routes/sessions.py` | SSE generator: merge DB-poll logs with live broker partials | ~35 |
| `app/static/js/app.js` | reconciliation fix + `firstId` guard (see §6, §6.1) | ~14 |
| `tests/test_live_broker.py` | **NEW** — broker fan-out / drop-on-full / unsubscribe | ~70 |
| `tests/test_backend_stream.py` | **NEW** — `_convert(StreamEvent)` scope filter | ~50 |

No DB schema change. No cost/usage change. No TG change.

---

## 2. `app/backend_claude.py` — emit stream events

### 2.1 Enable flag
`backend_claude.py:137`:
```python
include_partial_messages=True, max_turns=200,
```

### 2.2 Import
Add `StreamEvent` to the `from claude_agent_sdk import (...)` block (`backend_claude.py:9`).

### 2.3 Emit in `_convert` (`backend_claude.py:241`)
Add a branch BEFORE the `AssistantMessage` branch (StreamEvent is NOT an AssistantMessage, order-independent, but keep it first for clarity):

```python
def _convert(self, msg) -> list[AgentEvent]:
    events = []
    if isinstance(msg, StreamEvent):
        ev = msg.event or {}
        # v1: ONLY main-agent text. Skip subagent partials and non-text deltas.
        if msg.parent_tool_use_id is not None:
            return events                      # subagent → no streaming (scope)
        if ev.get("type") != "content_block_delta":
            return events
        delta = ev.get("delta") or {}
        if delta.get("type") != "text_delta":  # skip thinking/input_json/signature
            return events
        text = delta.get("text") or ""
        if text:
            events.append(AgentEvent("stream", text))
        return events

    if isinstance(msg, AssistantMessage):
        ...  # unchanged — final text/thinking/tool_use still emitted & persisted
```

**Why skip everything but main-agent `text_delta`:** scope is strict. `thinking_delta`, `input_json_delta`, and `parent_tool_use_id != None` (subagents) are explicitly out. The final `AssistantMessage` still carries thinking/tool/text and is persisted unchanged → no regression.

**Why no metadata:** v1 client only needs `content`. Keeping `AgentEvent("stream", text)` minimal matches the existing client contract (`addChatEntry('stream', content, ...)`).

---

## 3. `app/live_broker.py` — NEW in-memory pub/sub

Single-process, same event loop as the HTTP server. One module-level broker; per-session subscriber sets of bounded `asyncio.Queue`.

```python
"""In-memory pub/sub for live (ephemeral) stream partials — bypasses the DB.

Single process, single event loop. Partials are best-effort: a slow consumer
drops oldest chunks rather than blocking the session event loop. The final
DB-persisted 'text' log is always authoritative on reload/reconnect.
"""
import asyncio
from collections import defaultdict

_MAXSIZE = 256  # per-subscriber backlog; drop-oldest beyond this

class LiveBroker:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=_MAXSIZE)
        self._subs[session_id].add(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(session_id)
        if subs:
            subs.discard(q)
            if not subs:
                self._subs.pop(session_id, None)

    def publish(self, session_id: str, payload: dict) -> None:
        for q in tuple(self._subs.get(session_id, ())):  # snapshot — safe if set mutates
            if q.full():
                try: q.get_nowait()       # drop oldest — partials are ephemeral
                except asyncio.QueueEmpty: pass
            try: q.put_nowait(payload)
            except asyncio.QueueFull: pass

broker = LiveBroker()
```

**Design notes / edge cases:**
- `publish` is **sync** (called from the session event loop via `_handle_event`), never awaits → can't block the agent.
- Bounded queue + drop-oldest → a stalled SSE client can't grow memory or wedge the session.
- Iterating `self._subs[sid]` while a concurrent `subscribe`/`unsubscribe` mutates the same set: both run in the **same single-threaded event loop** with no `await` between mutation and iteration, so no race. (Documented assumption — Orchestra is single-process asyncio.)
- No session_id → empty publish, no-op.

---

## 4. `app/session.py` — route stream events to broker

`_handle_event` (`session.py:518`), add a branch. Stream events go to the broker, **NOT** `add_log` (ephemeral):

```python
elif event.type == "stream":
    from app.live_broker import broker
    broker.publish(self.id, {"type": "stream", "content": event.content})
    return
```

**Broker key = `self.id`** (the Orchestra session UUID). VERIFIED: `manager.get_session_id(name, scope)` returns `s.id` (`manager.py:1078-1081`), and `add_log` writes `logs.session_id = self.id` (`session.py:876`). So the SSE endpoint subscribes by exactly this id. Do **NOT** use `self.session_id` — that's the Claude resume token, often `None` on the first turn, and not what SSE/DB key on. `self.id` always exists.

No DB write, no `_turn_logs` append (partials aren't part of the auto-report digest).

---

## 5. `app/routes/sessions.py` — merge live partials into SSE

Current generator (`sessions.py:279-302`) only polls the DB. Add broker subscription so live partials interleave with DB-polled finals.

```python
async def event_generator():
    from app.db import _conn
    from app.live_broker import broker
    last_id = after_id
    initial = True
    c = _conn()
    q = broker.subscribe(session_id)          # session_id here == manager.get_session_id == session.id
    try:
        # initial history first (one-shot) — preserves load-more behavior
        if after_id == 0:
            for log in get_logs_before(session_id, before_id=2**31 - 1, limit=limit):
                yield f"data: {json.dumps(log)}\n\n"
                last_id = log["id"]
        while True:
            if await request.is_disconnected():
                return
            # 1) drain live partials FIRST (ephemeral, no id) — they always
            #    precede their final 'text' row, so emit them before polling DB.
            drained = 0
            while drained < 500:               # cap per tick — don't starve disconnect check
                try:
                    payload = q.get_nowait()
                except asyncio.QueueEmpty:
                    break
                yield f"data: {json.dumps(payload)}\n\n"
                drained += 1
            # 2) DB-persisted logs (finals + any other log types)
            logs = get_logs(session_id, after_id=last_id, conn=c)
            for log in logs:
                yield f"data: {json.dumps(log)}\n\n"
                last_id = log["id"]
            # 3) sleep — short while streaming, back off when idle
            await asyncio.sleep(0.1 if (logs or drained) else 0.5)
    finally:
        broker.unsubscribe(session_id, q)
        c.close()
```

**Changes vs today:**
- Initial history hoisted out of the loop (one-shot), then steady-state loop.
- Subscribe/unsubscribe around the loop.
- **Drain the live queue BEFORE reading DB logs** each tick (the ordering fix).
- Tighter sleep (0.1s) when active → finals follow partials quickly; 0.5s idle. (Dropped the 3s deep-idle backoff to keep finalize latency low; revisit if DB load matters — see risk #4.)

**Ordering guarantee (critical, revised per Codex):** the final `text` row is written to DB by `_log` AFTER all partials were published (partials = `StreamEvent`; final = the later `AssistantMessage`). By draining the broker **before** the DB read in every tick, all queued partials are flushed before their final `text`. Worst case the final lands in the SAME tick: partials drain first → then `text`. So the client always sees `stream…stream, text(final)` — never `text` then orphan `stream`. The §6 body-replace fix then makes the final authoritative. ✓

---

## 6. `app/static/js/app.js` — reconciliation fix

The existing dead-code path (`app.js:2153`) finalizes the stream bubble when a `text` event arrives — but it keeps `streamContent` (the accumulated partials) as the bubble body and just adds copy/timestamp. The persisted `text` log's `content` is the **authoritative full text**. Two issues:

1. **Partials may be incomplete** (dropped chunks, or the `text` final arrives in the same tick before the last partial). The bubble would show truncated text.
2. **Reconnect/reload:** no partials replayed (ephemeral) — only the DB `text` row arrives, with NO open `streamBubble` → it must render as a normal final bubble (this already works via the normal `text` path below `:2167`... **VERIFY**: confirm `text` with no open bubble falls through to a normal markdown bubble render).

**Fix:** on `type === 'text'` finalize, replace the bubble body with the authoritative `content`:
```javascript
if (type === 'text' && streamBubble) {
    streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(content || streamContent));
    addCopyBtn(streamBubble, content || streamContent);
    addTimestamp(streamBubble, ts);
    streamBubble = null;
    streamContent = '';
    return;
}
```
This makes the final DB text canonical (handles dropped/truncated partials) while partials drove the live typing effect. Minimal, surgical.

**VERIFY in impl:** the normal `text` render path (no open bubble) exists and renders markdown — needed for reconnect/reload and for agents where partials were dropped entirely. If absent, add a fallthrough.

### 6.1 `firstId`/`lastId` guard (per Codex)
Partial `stream` payloads have **no `id`** (ephemeral). The shared SSE handler updates `chatLogs.lastId/firstId` from `l.id` unconditionally (`app.js:188-193`). If a partial were the first message processed, `firstId` would become `undefined` and break Load-More. Guard it:
```javascript
if (Number.isFinite(l.id)) {
    if (l.id > chatLogs[selectedAgent].lastId) chatLogs[selectedAgent].lastId = l.id;
    if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
        chatLogs[selectedAgent].firstId = l.id;
        updateLoadMoreBtn();
    }
}
```
(In practice a `user_message` DB row precedes any stream, but the guard is one line and removes the edge case.)

---

## 7. What is NOT touched

- DB schema, `add_log`, `get_logs*` — unchanged.
- Cost/usage/`ResultMessage` handling — unchanged.
- TG bridge — unchanged (operates on finals/logs, never sees `stream`).
- `compact`, hibernate, reconnect, `_flush_pending` — unchanged.
- Codex/opencode backends — emit no `StreamEvent`, so no `stream` events; broker simply has nothing to publish. No regression.
- Subagent/thinking/tool-arg streaming — explicitly out of scope (filtered in `_convert`).

---

## 8. Risks & edge cases

| # | Risk | Mitigation |
|---|------|------------|
| 1 | **Broker key mismatch** (`self.id` vs Claude `session_id`). | Use `self.id`; SSE polls by the same id (`manager.get_session_id` == `session.id`). VERIFY in impl with a print/test. |
| 2 | **`text` final arrives before last partial** (same-tick ordering). | §6 fix: final `text` replaces bubble body with authoritative `content`. Truncated partials don't matter. |
| 3 | **Reconnect mid-stream** loses partials. | Finals in DB are authoritative; client replays history on reconnect. Partials best-effort. VERIFY normal `text`-no-bubble render path. |
| 4 | **0.1s SSE poll** raises DB read load while streaming. | Only 0.1s during active turns (logs or partials present); 0.5s idle. Per-conn `get_logs(after_id)` is an indexed lookup. Acceptable for dashboard scale (few viewers). If load matters, gate the tight poll behind "broker had traffic." |
| 5 | **Slow client** backpressure. | Bounded queue (256) + drop-oldest in `publish`; SSE drains ≤500/tick. Session loop never blocks. |
| 6 | **Multiple viewers** same agent. | Broker fan-out: one queue per viewer. Independent drop. |
| 7 | **Memory leak** if unsubscribe missed. | `finally: broker.unsubscribe(...)`; empty session sets popped. `request.is_disconnected()` already breaks the loop. |
| 8 | **Stream bubble persists across tool call** mid-turn. | Existing client finalizes bubble on any non-`text` event (`app.js:2121,2162`). ✓ |
| 9 | **Double render** (partial bubble + final text bubble). | Single bubble: partials fill it, final `text` finalizes the SAME bubble (no new node). ✓ |
| 10 | **Thinking leak** — we filter `thinking_delta` in backend. | Only `text_delta` emitted. Thinking still persists via final AssistantMessage as today. |

---

## 9. Test plan

- `tests/test_live_broker.py` (NEW): subscribe→publish→get; fan-out to N subs; drop-oldest when full; unsubscribe removes queue; empty-session publish no-ops.
- `tests/test_backend_stream.py` (NEW, per Codex): `_convert(StreamEvent(...))` scope filter — main-agent `text_delta` → one `stream` event; `thinking_delta`/`input_json_delta`/`signature_delta` → no event; `parent_tool_use_id != None` (subagent) → no event; non-`content_block_delta` (message_start/stop) → no event.
- Manual: spawn a worker, send a long prompt, watch dashboard bubble type in ~80-char chunks, confirm it finalizes to full text, confirm DB has the final `text` log and NO `stream` rows.
- Regression: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q` (full suite).
- Codex review on implementation diff (Phase 3).

---

## 10. Effort

~1.0–1.5 days (frontend mostly pre-existing). Backend broker + SSE merge is the bulk.
