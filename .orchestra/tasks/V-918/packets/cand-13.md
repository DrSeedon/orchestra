# Candidate cand-13

## ORIGIN commit 9dc2401518 (2026-06-21): #83: feat(#83): real-time token streaming in dashboard
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/backend_claude.py b/app/backend_claude.py
index f96a9a8fe..2ae364300 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -15,16 +15,17 @@ from claude_agent_sdk import (
     ThinkingBlock,
     ToolUseBlock,
     PermissionResultAllow,
     PermissionResultDeny,
     TaskStartedMessage,
     TaskProgressMessage,
     TaskNotificationMessage,
     SystemMessage,
+    StreamEvent,
 )
 from claude_agent_sdk.types import (
     ToolResultBlock, ServerToolResultBlock, UserMessage,
 )
 
 from app.events import AgentEvent
 
 logger = logging.getLogger(__name__)
@@ -129,17 +130,17 @@ class ClaudeBackend:
         # orchestra (back-compat). expanduser — на случай "~" в config_dir.
         if self._config_dir:
             env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)
         agent_uid = os.environ.get("ORCHESTRA_AGENT_UID")
         options = ClaudeAgentOptions(
             model=self.model, cwd=self.cwd, cli_path=cli,
             permission_mode="default", can_use_tool=_make_auto_approve(self._is_orchestrator),
             disallowed_tools=_disallowed_tools(self._is_orchestrator),
-            include_partial_messages=False, max_turns=200,
+            include_partial_messages=True, max_turns=200,
             max_buffer_size=50 * 1024 * 1024,
             env=env,
             user=agent_uid,
         )
         if resume_id:
             options.resume = resume_id
         else:
             options.system_prompt = {"type": "preset", "preset": "claude_code", "append": self.system_prompt}
@@ -235,16 +236,33 @@ class ClaudeBackend:
             await asyncio.wait_for(self._client.connect(), timeout=60)
         except BaseException as e:
             logger.error(f"ClaudeBackend reconnect failed: {e}")
             await self._cleanup_failed_client()
             raise
 
     def _convert(self, msg) -> list[AgentEvent]:
         events = []
+        if isinstance(msg, StreamEvent):
+            # v1 streaming scope: ONLY main-agent text. Skip subagent partials
+            # (parent_tool_use_id set) and non-text deltas (thinking/tool-arg/sig).
+            # The final AssistantMessage still carries everything and is persisted.
+            ev = msg.event or {}
+            if msg.parent_tool_use_id is not None:
+                return events
+            if ev.get("type") != "content_block_delta":
+                return events
+            delta = ev.get("delta") or {}
+            if delta.get("type") != "text_delta":
+                return events
+            text = delta.get("text") or ""
+            if text:
+                events.append(AgentEvent("stream", text))
+            return events
+
         if isinstance(msg, AssistantMessage):
             for block in msg.content:
                 if isinstance(block, TextBlock) and block.text:
                     events.append(AgentEvent("text", block.text))
                 elif isinstance(block, ThinkingBlock) and block.thinking:
                     events.append(AgentEvent("thinking", block.thinking))
                 elif isinstance(block, ToolUseBlock):
                     try:
diff --git a/app/live_broker.py b/app/live_broker.py
new file mode 100644
index 000000000..5a23f86df
--- /dev/null
+++ b/app/live_broker.py
@@ -0,0 +1,44 @@
+"""In-memory pub/sub for live (ephemeral) stream partials — bypasses the DB.
+
+Single process, single event loop. Partials are best-effort: a slow consumer
+drops oldest chunks rather than blocking the session event loop. The final
+DB-persisted 'text' log is always authoritative on reload/reconnect.
+
+Not compatible with multi-worker uvicorn (in-memory, like the session manager).
+"""
+import asyncio
+from collections import defaultdict
+
+_MAXSIZE = 256  # per-subscriber backlog; drop-oldest beyond this
+
+
+class LiveBroker:
+    def __init__(self) -> None:
+        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
+
+    def subscribe(self, session_id: str) -> asyncio.Queue:
+        q: asyncio.Queue = asyncio.Queue(maxsize=_MAXSIZE)
+        self._subs[session_id].add(q)
+        return q
+
+    def unsubscribe(self, session_id: str, q: asyncio.Queue) -> None:
+        subs = self._subs.get(session_id)
+        if subs:
+            subs.discard(q)
+            if not subs:
+                self._subs.pop(session_id, None)
+
+    def publish(self, session_id: str, payload: dict) -> None:
+        for q in tuple(self._subs.get(session_id, ())):  # snapshot — safe if set mutates
+            if q.full():
+                try:
+                    q.get_nowait()  # drop oldest — partials are ephemeral
+                except asyncio.QueueEmpty:
+                    pass
+            try:
+                q.put_nowait(payload)
+            except asyncio.QueueFull:
+                pass
+
+
+broker = LiveBroker()
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 59fe8e93a..a4f96bc7b 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -273,37 +273,48 @@ async def get_session_context(name: str, scope: str):
 async def stream_session_logs(name: str, scope: str, request: Request, after_id: int = 0, limit: int = 500):
     limit = min(limit, 1000)
     import json
     session_id = manager.get_session_id(name, scope)
     if not session_id:
         return JSONResponse({"error": "not found"}, status_code=404)
     async def event_generator():
         from app.db import _conn
+        from app.live_broker import broker
         last_id = after_id
-        initial = True
-        idle_ticks = 0
         c = _conn()
+        q = broker.subscribe(session_id)  # session_id == manager.get_session_id == session.id
         try:
+            # initial history first (one-shot) — preserves load-more behavior
+            if after_id == 0:
+                for log in get_logs_before(session_id, before_id=2**31 - 1, limit=limit):
+                    yield f"data: {json.dumps(log)}\n\n"
+                    last_id = log["id"]
             while True:
                 if await request.is_disconnected():
                     return
-                if initial and after_id == 0:
-                    logs = get_logs_before(session_id, before_id=2**31 - 1, limit=limit)
-                    initial = False
-                else:
-                    logs = get_logs(session_id, after_id=last_id, conn=c)
-                    initial = False
+                # 1) drain live partials FIRST (ephemeral, no id) — they always
+                #    precede their final 'text' row, so emit before polling DB.
+                drained = 0
+                while drained < 500:  # cap per tick — don't starve disconnect check
+                    try:
+                        payload = q.get_nowait()
+                    except asyncio.QueueEmpty:
+                        break
+                    yield f"data: {json.dumps(payload)}\n\n"
+                    drained += 1
+                # 2) DB-persisted logs (finals + all other log types)
+                logs = get_logs(session_id, after_id=last_id, conn=c)
                 for log in logs:
                     yield f"data: {json.dumps(log)}\n\n"
                     last_id = log["id"]
-                idle_ticks = 0 if logs else idle_ticks + 1
-                # Back off to 3s after 2s of inactivity — reduces DB polling when idle
-                await asyncio.sleep(0.5 if idle_ticks < 4 else 3.0)
+                # 3) short poll while active (partials follow quickly), back off when idle
+                await asyncio.sleep(0.1 if (logs or drained) else 0.5)
         finally:
+            broker.unsubscribe(session_id, q)
             c.close()
     return StreamingResponse(event_generator(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
 
 
 @router.get("/api/sessions/{name}/logs")
 async def get_session_logs(name: str, scope: str, after_id: int = 0, before_id: int = 0, limit: int = 500):
     limit = min(limit, 1000)
diff --git a/app/session.py b/app/session.py
index 57fab47bc..6359d27b4 100644
--- a/app/session.py
+++ b/app/session.py
@@ -511,16 +511,22 @@ class AgentSession:
                 if self._pending_messages:
                     self._spawn_bg(self._flush_pending())
                 else:
                     self._hibernate.schedule()
 
     # ── Unified event handler ──
 
     def _handle_event(self, event: AgentEvent) -> None:
+        if event.type == "stream":
+            # Live partials: push to in-memory broker for SSE fan-out, NEVER persist.
+            # The final "text" event (below) is the DB source of truth.
+            from app.live_broker import broker
+            broker.publish(self.id, {"type": "stream", "content": event.content})
+            return
         if event.type == "text":
             self._log("text", event.content)
             self._turn_logs.append(event.content)
         elif event.type == "thinking":
             self._log("thinking", event.content)
         elif event.type == "tool_use":
             self.total_tool_calls += 1
             self._log("tool", event.content)
diff --git a/app/static/js/app.js b/app/static/js/app.js
index c8bb578e0..481a35845 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -181,20 +181,23 @@ function connectSSE() {
                     }
                 } else {
                     addChatEntry(l.type, l.content, l.ts);
                 }
             } else {
                 addChatEntry(l.type, l.content, l.ts);
             }
             if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0, firstId: null };
-            if (l.id > chatLogs[selectedAgent].lastId) chatLogs[selectedAgent].lastId = l.id;
-            if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
-                chatLogs[selectedAgent].firstId = l.id;
-                updateLoadMoreBtn();
+            // Live stream partials carry no id — skip id bookkeeping for them
+            if (Number.isFinite(l.id)) {
+                if (l.id > chatLogs[selectedAgent].lastId) chatLogs[selectedAgent].lastId = l.id;
+                if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
+                    chatLogs[selectedAgent].firstId = l.id;
+                    updateLoadMoreBtn();
+                }
             }
             if (scrollAfterLoad) {
                 $('#chat').scrollTop = $('#chat').scrollHeight;
                 clearTimeout(window._scrollResetTimer);
                 window._scrollResetTimer = setTimeout(() => { scrollAfterLoad = false; }, 500);
             }
         } catch (e) { console.warn('SSE parse:', e); }
     };
@@ -2144,19 +2147,23 @@ function addChatEntry(type, content, ts, anchor) {
             _insert(streamBubble);
         }
         streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(streamContent));
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
         if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
 
-    // 'text' event signals that streaming finished — finalize the bubble with timestamp/copy
+    // 'text' event signals streaming finished — the DB-persisted content is
+    // authoritative (partials may have been dropped/truncated), so replace the
+    // bubble body with it, then finalize with copy/timestamp.
     if (type === 'text' && streamBubble) {
-        addCopyBtn(streamBubble, streamContent);
+        const finalText = content || streamContent;
+        streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(finalText));
+        addCopyBtn(streamBubble, finalText);
         addTimestamp(streamBubble, ts);
         streamBubble = null;
         streamContent = '';
         return;
     }
 
     // Any non-text log after a stream (e.g. tool call) also terminates the stream bubble
     if (streamBubble && type !== 'text') {
diff --git a/docs/tasks/83/capture_partial.py b/docs/tasks/83/capture_partial.py
new file mode 100644
index 000000000..2b98b79cb
--- /dev/null
+++ b/docs/tasks/83/capture_partial.py
@@ -0,0 +1,122 @@
+"""Capture SDKPartialAssistantMessage (StreamEvent) shapes from claude-agent-sdk.
+
+Run: UV_CACHE_DIR=/tmp/uv-cache uv run python docs/tasks/83/capture_partial.py
+Writes a sample dump to docs/tasks/83/partial_dump.jsonl
+"""
+import asyncio
+import json
+import os
+import shutil
+import time
+from collections import Counter
+
+from claude_agent_sdk import (
+    ClaudeSDKClient, ClaudeAgentOptions, StreamEvent,
+    AssistantMessage, ResultMessage,
+)
+
+OUT = os.path.join(os.path.dirname(__file__), "partial_dump.jsonl")
+
+
+async def main():
+    cli = shutil.which("claude") or os.environ.get("CLAUDE_CLI_PATH", "claude")
+    env = {}
+    for k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"):
+        if os.environ.get(k):
+            env[k] = os.environ[k]
+    env["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] = "1"
+    env["DISABLE_TELEMETRY"] = "1"
+
+    options = ClaudeAgentOptions(
+        model="claude-haiku-4-5-20251001",
+        cwd=os.getcwd(),
+        cli_path=cli,
+        permission_mode="default",
+        include_partial_messages=True,   # ← the flag under test
+        max_turns=1,
+        env=env,
+        system_prompt={"type": "preset", "preset": "claude_code"},
+    )
+
+    client = ClaudeSDKClient(options=options)
+    await client.connect()
+
+    # A prompt long enough to produce many text deltas; measure streaming cadence.
+    await client.query(
+        "Count slowly from 1 to 30, one number per line, with a short word after each. "
+        "Do not use any tools."
+    )
+
+    event_types = Counter()       # inner Anthropic event['type']
+    sdk_types = Counter()         # SDK message class names
+    samples = {}                  # first sample of each inner event type
+    n_partial = 0
+    first_t = None
+    last_t = None
+    text_deltas = 0
+    text_chars = 0
+
+    f = open(OUT, "w")
+    try:
+        async for msg in client.receive_messages():
+            now = time.monotonic()
+            cls = type(msg).__name__
+            sdk_types[cls] += 1
+
+            if isinstance(msg, StreamEvent):
+                n_partial += 1
+                if first_t is None:
+                    first_t = now
+                last_t = now
+                ev = msg.event or {}
+                etype = ev.get("type", "?")
+                event_types[etype] += 1
+                rec = {
+                    "sdk_class": cls,
+                    "uuid": msg.uuid,
+                    "session_id": msg.session_id,
+                    "parent_tool_use_id": msg.parent_tool_use_id,
+                    "event": ev,
+                }
+                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
+                if etype not in samples:
+                    samples[etype] = rec
+                # measure text delta cadence
+                if etype == "content_block_delta":
+                    delta = ev.get("delta", {})
+                    if delta.get("type") == "text_delta":
+                        text_deltas += 1
+                        text_chars += len(delta.get("text", ""))
+
+            elif isinstance(msg, AssistantMessage):
+                # full assembled message — what Orchestra uses today
+                f.write(json.dumps({"sdk_class": cls, "blocks": [type(b).__name__ for b in msg.content]}) + "\n")
+
+            elif isinstance(msg, ResultMessage):
+                break
+    finally:
+        f.close()
+        await client.disconnect()
+
+    print("=== SDK message class counts ===")
+    for k, v in sdk_types.most_common():
+        print(f"  {k}: {v}")
+    print("\n=== StreamEvent inner event['type'] counts ===")
+    for k, v in event_types.most_common():
+        print(f"  {k}: {v}")
+    print(f"\nTotal StreamEvents: {n_partial}")
+    print(f"text_delta events: {text_deltas}, total chars: {text_chars}")
+    if text_deltas:
+        print(f"avg chars/delta: {text_chars/text_deltas:.1f}")
+    if first_t and last_t and last_t > first_t and text_deltas:
+        span = last_t - first_t
+        print(f"stream span: {span:.2f}s, deltas/sec: {text_deltas/span:.1f}")
+    print("\n=== One sample of each inner event type ===")
+    for k, rec in samples.items():
+        print(f"\n--- {k} ---")
+        print(json.dumps(rec, ensure_ascii=False, indent=2)[:1200])
+    print(f"\nFull dump: {OUT}")
+
+
+if __name__ == "__main__":
+    asyncio.run(main())
diff --git a/docs/tasks/83/partial_dump.jsonl b/docs/tasks/83/partial_dump.jsonl
new file mode 100644
index 000000000..073c91e15
--- /dev/null
+++ b/docs/tasks/83/partial_dump.jsonl
@@ -0,0 +1,10 @@
+{"sdk_class": "StreamEvent", "uuid": "2f7795c9-f5d6-4c87-bb16-68370337f906", "session_id": "9a368b29-7840-44f8-84d7-6c0f8bfcb41d", "parent_tool_use_id": null, "event": {"type": "message_start", "message": {"model": "claude-haiku-4-5-20251001", "id": "msg_01HDgViQjKnTr2Bz9BAUvHnQ", "type": "message", "role": "assistant", "content": [], "stop_reason": null, "stop_sequence": null, "stop_details": null, "usage": {"input_tokens": 3, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 43033, "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}, "output_tokens": 1, "service_tier": "standard", "inference_geo": "not_available"}}}}
+{"sdk_class": "StreamEvent", "uuid": "f12dcbe5-8f3a-401f-a285-e86769780578", "session_id": "9a368b29-7840-44f8-84d7-6c0f8bfcb41d", "parent_tool_use_id": null, "event": {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}}
+{"sdk_class": "StreamEvent", "uuid": "dcddd10e-9196-48f5-a50f-6480c7637288", "session_id": "9a368b29-7840-44f8-84d7-6c0f8bfcb41d", "parent_tool_use_id": null, "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "1 один\n2 два\n3 три\n4 четыре\n5 пять\n6 шесть\n7 семь\n8 восемь\n9 девять\n10 десять\n11 "}}}
+{"sdk_class": "StreamEvent", "uuid": "6b26ebcf-4418-45e8-8159-9b8e6afe4271", "session_id": "9a368b29-7840-44f8-84d7-6c0f8bfcb41d", "parent_tool_use_id": null, "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "одиннадцать\n12 двенадцать\n13 тринадцать\n14 четырнадцать\n15 пятнадцать\n16 шестнадцать\n17 семнадцать\n18 вос"}}}
+{"sdk_class": "StreamEvent", "uuid": "8fb11b92-5b12-415f-b2b0-6e917b1d4f8b", "session_id": "9a368b29-7840-44f8-84d7-6c0f8bfcb41d", "parent_tool_use_id": null, "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "емнадцать\n19 девятнадцать\n20 двадцать\n21 двадцать один\n22 двадцать два\n23 двадцать три"}}}
+{"sdk_class": "StreamEvent", "uuid": "4f4c99e1-0db7-4421-aca8-b62ccffc10de", "session_id": "9a368b29-7840-44f8-84d7-6c0f8bfcb41d", "parent_tool_use_id": null, "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "\n24 двадцать четыре\n25 двадцать пять\n26 двадцать шесть\n27 двадцать семь\n28 двадцать восемь\n29 двадцать девять\n30 тридцать"}}}
+{"sdk_class": "AssistantMessage", "blocks": ["TextBlock"]}
+{"sdk_class": "StreamEvent", "uuid": "cfd02545-98be-46ec-a02c-8d95df98e72c", "session_id": "9a368b29-7840-44f8-84d7-6c0f8bfcb41d", "parent_tool_use_id": null, "event": {"type": "content_block_stop", "index": 0}}
+{"sdk_class": "StreamEvent", "uuid": "082f4a85-8c26-4e79-8ca6-04b11bfdcf9f", "session_id": "9a368b29-7840-44f8-84d7-6c0f8bfcb41d", "parent_tool_use_id": null, "event": {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": null, "stop_details": null}, "usage": {"input_tokens": 3, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 43033, "output_tokens": 226}, "context_management": {"applied_edits": []}}}
+{"sdk_class": "StreamEvent", "uuid": "73d8a018-7f22-4149-98f1-10053e8f9102", "session_id": "9a368b29-7840-44f8-84d7-6c0f8bfcb41d", "parent_tool_use_id": null, "event": {"type": "message_stop"}}
diff --git a/tests/test_backend_stream.py b/tests/test_backend_stream.py
new file mode 100644
index 000000000..bfbf4d517
--- /dev/null
+++ b/tests/test_backend_stream.py
@@ -0,0 +1,82 @@
+"""Task #83 — ClaudeBackend._convert StreamEvent scope filter.
+
+v1 streaming: ONLY main-agent text_delta becomes a "stream" AgentEvent.
+Everything else (thinking/tool-arg deltas, subagent partials, non-delta events)
+is dropped — the final AssistantMessage still carries them and is persisted.
+"""
+from claude_agent_sdk import StreamEvent
+
+from app.backend_claude import ClaudeBackend
+
+
+def _backend():
+    return ClaudeBackend(model="claude-sonnet-4-6", cwd="/tmp")
+
+
+def _stream(event, parent_tool_use_id=None):
+    return StreamEvent(uuid="u", session_id="s", event=event,
+                       parent_tool_use_id=parent_tool_use_id)
+
+
+def test_text_delta_emits_stream_event():
+    b = _backend()
+    msg = _stream({
+        "type": "content_block_delta", "index": 0,
+        "delta": {"type": "text_delta", "text": "hello"},
+    })
+    events = b._convert(msg)
+    assert len(events) == 1
+    assert events[0].type == "stream"
+    assert events[0].content == "hello"
+
+
+def test_empty_text_delta_emits_nothing():
+    b = _backend()
+    msg = _stream({
+        "type": "content_block_delta", "index": 0,
+        "delta": {"type": "text_delta", "text": ""},
+    })
+    assert b._convert(msg) == []
+
+
+def test_thinking_delta_dropped():
+    b = _backend()
+    msg = _stream({
+        "type": "content_block_delta", "index": 0,
+        "delta": {"type": "thinking_delta", "thinking": "hmm"},
+    })
+    assert b._convert(msg) == []
+
+
+def test_input_json_delta_dropped():
+    b = _backend()
+    msg = _stream({
+        "type": "content_block_delta", "index": 0,
+        "delta": {"type": "input_json_delta", "partial_json": '{"a":'},
+    })
+    assert b._convert(msg) == []
+
+
+def test_signature_delta_dropped():
+    b = _backend()
+    msg = _stream({
+        "type": "content_block_delta", "index": 0,
+        "delta": {"type": "signature_delta", "signature": "sig"},
+    })
+    assert b._convert(msg) == []
+
+
+def test_subagent_text_delta_dropped():
+    b = _backend()
+    msg = _stream({
+        "type": "content_block_delta", "index": 0,
+        "delta": {"type": "text_delta", "text": "sub"},
+    }, parent_tool_use_id="toolu_123")
+    assert b._convert(msg) == []
+
+
+def test_non_delta_events_dropped():
+    b = _backend()
+    for etype in ("message_start", "content_block_start",
+                  "content_block_stop", "message_delta", "message_stop"):
+        assert b._convert(_stream({"type": etype})) == []
diff --git a/tests/test_live_broker.py b/tests/test_live_broker.py
new file mode 100644
index 000000000..2ec9a9ab3
--- /dev/null
+++ b/tests/test_live_broker.py
@@ -0,0 +1,79 @@
+"""Tests for app.live_broker — in-memory pub/sub for stream partials."""
+import pytest
+
+from app.live_broker import LiveBroker, _MAXSIZE
+
+
+@pytest.mark.asyncio
+async def test_subscribe_publish_get():
+    b = LiveBroker()
+    q = b.subscribe("sid")
+    b.publish("sid", {"type": "stream", "content": "hi"})
+    assert q.get_nowait() == {"type": "stream", "content": "hi"}
+
+
+@pytest.mark.asyncio
+async def test_fanout_to_multiple_subscribers():
+    b = LiveBroker()
+    q1 = b.subscribe("sid")
+    q2 = b.subscribe("sid")
+    b.publish("sid", {"content": "x"})
+    assert q1.get_nowait() == {"content": "x"}
+    assert q2.get_nowait() == {"content": "x"}
+
+
+@pytest.mark.asyncio
+async def test_publish_to_unknown_session_is_noop():
+    b = LiveBroker()
+    # no subscribers — must not raise
+    b.publish("nobody", {"content": "x"})
+
+
+@pytest.mark.asyncio
+async def test_drop_oldest_when_full():
+    b = LiveBroker()
+    q = b.subscribe("sid")
+    for i in range(_MAXSIZE + 5):
+        b.publish("sid", {"n": i})
+    # queue capped at _MAXSIZE; oldest dropped, newest kept
+    assert q.qsize() == _MAXSIZE
+    first = q.get_nowait()
+    assert first["n"] == 5  # 0..4 dropped
+    # drain rest, last must be the newest
+    last = first
+    while not q.empty():
+        last = q.get_nowait()
+    assert last["n"] == _MAXSIZE + 4
+
+
+@pytest.mark.asyncio
+async def test_unsubscribe_stops_delivery_and_cleans_up():
+    b = LiveBroker()
+    q = b.subscribe("sid")
+    b.unsubscribe("sid", q)
+    b.publish("sid", {"content": "x"})
+    assert q.empty()
+    # session set removed once empty
+    assert "sid" not in b._subs
+
+
+@pytest.mark.asyncio
+async def test_unsubscribe_one_of_two_keeps_other():
+    b = LiveBroker()
+    q1 = b.subscribe("sid")
+    q2 = b.subscribe("sid")
+    b.unsubscribe("sid", q1)
+    b.publish("sid", {"content": "x"})
+    assert q1.empty()
+    assert q2.get_nowait() == {"content": "x"}
+    assert "sid" in b._subs
+
+
+@pytest.mark.asyncio
+async def test_isolated_sessions():
+    b = LiveBroker()
+    qa = b.subscribe("a")
+    qb = b.subscribe("b")
+    b.publish("a", {"content": "for-a"})
+    assert qa.get_nowait() == {"content": "for-a"}
+    assert qb.empty()


## LATER FIX 1473e37459 (9.8 days later): #proxy-fix: check liveness via Anthropic, ipinfo geo best-effort
lines of origin it changed/deleted: 12
(code only, capped 400 lines)

#proxy-fix: check liveness via Anthropic, ipinfo geo best-effort

Squashed commits:
- #proxy-fix: check liveness via Anthropic, ipinfo geo best-effort
- docs: subagent-visibility research + revert-note on no-subagents ban
- feat: subagent visibility — live stream partials + accordion, tag subagent_id


diff --git a/app/backend_claude.py b/app/backend_claude.py
index 34abc9fd4..b5408e17f 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -235,79 +235,102 @@ class ClaudeBackend:
         self._client = self._make_client()
         try:
             await asyncio.wait_for(self._client.connect(), timeout=60)
         except BaseException as e:
             logger.error(f"ClaudeBackend reconnect failed: {e}")
             await self._cleanup_failed_client()
             raise
 
+    @staticmethod
+    def _tag_sub(event: AgentEvent, sub_id) -> AgentEvent:
+        """Mark an event as belonging to a sub-agent so the UI nests it.
+
+        sub_id None (main agent) → event unchanged. Otherwise stamp subagent_id;
+        the type is preserved (tool_use stays tool_use) — the frontend groups by
+        subagent_id, not by a renamed type."""
+        if sub_id is not None:
+            event.metadata = {**event.metadata, "subagent_id": sub_id}
+        return event
+
     def _convert(self, msg) -> list[AgentEvent]:
         events = []
         if isinstance(msg, StreamEvent):
-            # v1 streaming scope: ONLY main-agent text. Skip subagent partials
-            # (parent_tool_use_id set) and non-text deltas (thinking/tool-arg/sig).
-            # The final AssistantMessage still carries everything and is persisted.
+            # Main-agent text partials → "stream". Subagent partials (parent_tool_use_id
+            # set) → "subagent_stream" tagged with sub_id so the UI nests them under the
+            # sub-agent block instead of dropping them (which looked like a hang).
             ev = msg.event or {}
-            if msg.parent_tool_use_id is not None:
-                return events
             if ev.get("type") != "content_block_delta":
                 return events
             delta = ev.get("delta") or {}
             if delta.get("type") != "text_delta":
                 return events
             text = delta.get("text") or ""
-            if text:
+            if not text:
+                return events
+            sub_id = msg.parent_tool_use_id
+            if sub_id is not None:
+                events.append(AgentEvent("subagent_stream", text, metadata={"subagent_id": sub_id}))
+            else:
                 events.append(AgentEvent("stream", text))
             return events
 
         if isinstance(msg, AssistantMessage):
+            # Subagent messages carry parent_tool_use_id → tag events so the UI groups
+            # them under the sub-agent block instead of mixing with the parent's stream.
+            sub_id = getattr(msg, "parent_tool_use_id", None)
             for block in msg.content:
                 if isinstance(block, TextBlock) and block.text:
-                    events.append(AgentEvent("text", block.text))
+                    events.append(self._tag_sub(AgentEvent("text", block.text), sub_id))
                 elif isinstance(block, ThinkingBlock) and block.thinking:
-                    events.append(AgentEvent("thinking", block.thinking))
+                    events.append(self._tag_sub(AgentEvent("thinking", block.thinking), sub_id))
                 elif isinstance(block, ToolUseBlock):
                     try:
                         inp = _json.dumps(block.input, ensure_ascii=False, indent=2)
                     except Exception:
                         inp = str(block.input)
                     short_name = block.name.split('__')[-1] if '__' in block.name else block.name
-                    events.append(AgentEvent("tool_use", f"{block.name}: {inp}",
-                                             metadata={"tool_name": block.name, "short_name": short_name}))
+                    events.append(self._tag_sub(AgentEvent("tool_use", f"{block.name}: {inp}",
+                                             metadata={"tool_name": block.name, "short_name": short_name}), sub_id))
                 elif isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
-                    events.append(AgentEvent("tool_result", _extract_tool_result(block)))
+                    events.append(self._tag_sub(AgentEvent("tool_result", _extract_tool_result(block)), sub_id))
             err = getattr(msg, "error", None)
             if err:
                 events.append(AgentEvent("error", f"model error: {err}"))
 
         elif isinstance(msg, UserMessage):
+            sub_id = getattr(msg, "parent_tool_use_id", None)
             if hasattr(msg, 'content') and isinstance(msg.content, list):
                 for block in msg.content:
                     if isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
-                        events.append(AgentEvent("tool_result", _extract_tool_result(block)))
+                        events.append(self._tag_sub(AgentEvent("tool_result", _extract_tool_result(block)), sub_id))
 
         elif isinstance(msg, TaskStartedMessage):
             desc = getattr(msg, "description", "") or ""
             task_type = getattr(msg, "task_type", "") or ""
             task_id = getattr(msg, "task_id", "") or ""
-            events.append(AgentEvent("subagent_start", f"{desc} | type={task_type} | id={task_id}"))
+            events.append(AgentEvent("subagent_start", f"{desc} | type={task_type} | id={task_id}",
+                                     metadata={"subagent_id": task_id}))
 
         elif isinstance(msg, TaskProgressMessage):
             desc = getattr(msg, "description", "") or ""
             last_tool = getattr(msg, "last_tool_name", "") or ""
+            task_id = getattr(msg, "task_id", "") or ""
             usage = getattr(msg, "usage", None)
             tokens = usage.total_tokens if usage and hasattr(usage, "total_tokens") else 0
-            events.append(AgentEvent("subagent_progress", f"{desc} | tool={last_tool} | tokens={tokens}"))
+            events.append(AgentEvent("subagent_progress", f"{desc} | tool={last_tool} | tokens={tokens}",
+                                     metadata={"subagent_id": task_id}))
 
         elif isinstance(msg, TaskNotificationMessage):
             desc = getattr(msg, "description", "") or ""
             status = getattr(msg, "status", "") or ""
             summary = getattr(msg, "summary", "") or ""
-            events.append(AgentEvent("subagent_end", f"{desc} | status={status} | {summary[:500]}"))
+            task_id = getattr(msg, "task_id", "") or ""
+            events.append(AgentEvent("subagent_end", f"{desc} | status={status} | {summary[:500]}",
+                                     metadata={"subagent_id": task_id}))
 
         elif isinstance(msg, ResultMessage):
             sr = getattr(msg, "stop_reason", None) or "unknown"
             nt = getattr(msg, "num_turns", 0) or 0
             if msg.session_id:
                 self._session_id = msg.session_id
 
             is_err = bool(getattr(msg, "is_error", False))
diff --git a/app/proxy_manager.py b/app/proxy_manager.py
index f4aad0e0f..c21b8fe70 100644
--- a/app/proxy_manager.py
+++ b/app/proxy_manager.py
@@ -21,18 +21,23 @@ COUNTRY_FLAGS = {
     "RU": "🇷🇺", "UA": "🇺🇦", "KZ": "🇰🇿", "BY": "🇧🇾",
     "JP": "🇯🇵", "KR": "🇰🇷", "SG": "🇸🇬", "AU": "🇦🇺",
     "CA": "🇨🇦", "BR": "🇧🇷", "IN": "🇮🇳", "TR": "🇹🇷",
     "PL": "🇵🇱", "CZ": "🇨🇿", "RO": "🇷🇴", "BG": "🇧🇬",
     "HK": "🇭🇰", "TW": "🇹🇼", "IE": "🇮🇪", "ES": "🇪🇸",
     "IT": "🇮🇹", "PT": "🇵🇹", "DK": "🇩🇰", "LT": "🇱🇹",
     "LV": "🇱🇻", "EE": "🇪🇪", "IS": "🇮🇸", "MD": "🇲🇩",
 }
-IP_CHECK_URL = "https://ipinfo.io/json"
-IP_CHECK_TIMEOUT = 8
+# Liveness = can we reach Anthropic (what we actually use)? ANY HTTP response
+# (200/401/403/404) means the proxy tunnels fine. ipinfo.io was giving false
+# "dead" for live proxies (intermittent timeouts) — it's now best-effort geo only.
+LIVENESS_URL = "https://api.anthropic.com"
+GEO_URL = "https://ipinfo.io/json"
+CHECK_TIMEOUT = 8
+GEO_TIMEOUT = 5
 
 
 @dataclass
 class ProxyEntry:
     id: str
     name: str
     url: str
 
@@ -83,34 +88,46 @@ class ProxyManager:
     async def check_proxy(self, proxy_id: str) -> dict:
         entries = self._get_entries()
         entry = next((e for e in entries if e.id == proxy_id), None)
         if not entry:
             return {"error": f"proxy '{proxy_id}' not found"}
         return await self._do_check(entry)
 
     async def _do_check(self, entry: ProxyEntry) -> dict:
+        """Two-tier: liveness via Anthropic (any HTTP response = alive), geo via
+        ipinfo (best-effort — its flakiness must NOT mark a live proxy dead)."""
+        proxy = entry.url if entry.url and entry.url != "direct" else None
         try:
-            kwargs = {"timeout": IP_CHECK_TIMEOUT, "verify": False}
-            if entry.url and entry.url != "direct":
-                kwargs["proxy"] = entry.url
-            async with httpx.AsyncClient(**kwargs) as client:
-                resp = await client.get(IP_CHECK_URL)
+            async with httpx.AsyncClient(timeout=CHECK_TIMEOUT, verify=False, proxy=proxy) as client:
+                await client.get(LIVENESS_URL)  # any response (200/401/403/404) = tunnel works
+        except Exception as e:
+            return {"id": entry.id, "ok": False, "error": str(e) or "unreachable"}
+        result = {"id": entry.id, "ok": True}
+        try:
+            result.update(await self._geo(proxy))  # best-effort, never flips ok
+        except Exception:
+            pass  # geo is decoration — its failure must not mark a live proxy dead
+        return result
+
+    async def _geo(self, proxy: str | None) -> dict:
+        try:
+            async with httpx.AsyncClient(timeout=GEO_TIMEOUT, verify=False, proxy=proxy) as client:
+                resp = await client.get(GEO_URL)
                 if resp.status_code != 200:
-                    return {"id": entry.id, "ok": False, "error": f"HTTP {resp.status_code}"}
+                    return {}
                 data = resp.json()
-                country = data.get("country", "??")
+                country = data.get("country", "")
                 return {
-                    "id": entry.id, "ok": True,
-                    "ip": data.get("ip", "?"), "country": country,
+                    "ip": data.get("ip", ""), "country": country,
                     "city": data.get("city", ""), "org": data.get("org", ""),
                     "flag": COUNTRY_FLAGS.get(country, "🏳️"),
                 }
-        except Exception as e:
-            return {"id": entry.id, "ok": False, "error": str(e)}
+        except Exception:
+            return {}  # geo unavailable — proxy still reported alive
 
     async def list_proxies(self) -> dict:
         """List proxies from .env. `active` = current HTTPS_PROXY (read-only).
 
         No liveness here — call check/{id} or check_all for that (on-demand).
         """
         entries = self._get_entries()
         active_id = _active_id(entries)
diff --git a/app/session.py b/app/session.py
index 36880bfb9..debc318f2 100644
--- a/app/session.py
+++ b/app/session.py
@@ -521,16 +521,33 @@ class AgentSession:
 
     def _handle_event(self, event: AgentEvent) -> None:
         if event.type == "stream":
             # Live partials: push to in-memory broker for SSE fan-out, NEVER persist.
             # The final "text" event (below) is the DB source of truth.
             from app.live_broker import broker
             broker.publish(self.id, {"type": "stream", "content": event.content})
             return
+        if event.type == "subagent_stream":
+            # Live sub-agent output → broker only (ephemeral, like main stream).
+            # subagent_id lets the UI nest it under the right sub-agent block.
+            from app.live_broker import broker
+            broker.publish(self.id, {"type": "subagent_stream", "content": event.content,
+                                     "subagent_id": event.metadata.get("subagent_id", "")})
+            return
+        # Sub-agent tool_use/text/tool_result (tagged with subagent_id) → broker ONLY
+        # (ephemeral live nesting under the sub-agent block). NOT persisted — the DB
+        # record is subagent_start/end; persisting these too would double-render them
+        # (once in the accordion via broker, once in the main flow on reload).
+        sub_id = event.metadata.get("subagent_id")
+        if sub_id and event.type in ("tool_use", "tool_result", "text", "thinking"):
+            from app.live_broker import broker
+            broker.publish(self.id, {"type": "subagent_event", "event_type": event.type,
+                                     "content": event.content[:2000], "subagent_id": sub_id})
+            return
         if event.type == "text":
             from app.live_broker import broker
             broker.clear_accum(self.id)
             self._log("text", event.content)
             self._turn_logs.append(event.content)
         elif event.type == "thinking":
             self._log("thinking", event.content)
         elif event.type == "tool_use":
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 1bab70e59..760752b90 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -175,20 +175,20 @@ function connectSSE() {
                 if (isLocal) {
                     for (const m of localMessages) {
                         if (l.content === m || l.content.endsWith(m) || l.content.includes(m)) {
                             localMessages.delete(m);
                             break;
                         }
                     }
                 } else {
-                    addChatEntry(l.type, l.content, l.ts);
+                    addChatEntry(l.type, l.content, l.ts, null, l);
                 }
             } else {
-                addChatEntry(l.type, l.content, l.ts);
+                addChatEntry(l.type, l.content, l.ts, null, l);
             }
             if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0, firstId: null };
             // Live stream partials carry no id — skip id bookkeeping for them
             if (Number.isFinite(l.id)) {
                 if (l.id > chatLogs[selectedAgent].lastId) chatLogs[selectedAgent].lastId = l.id;
                 if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
                     chatLogs[selectedAgent].firstId = l.id;
                     updateLoadMoreBtn();
@@ -2058,20 +2058,58 @@ function _findLastBefore(parent, selector, anchor) {
     while (node) {
         if (node.matches(selector)) return node;
         node = node.previousElementSibling;
     }
     return null;
 }
 
 const HIDE_THINKING = document.body.dataset.hideThinking === 'true';
+
+// Append a live sub-agent log line into its accordion body. If the accordion
+// isn't there yet (race: stream before start), no-op — the sub-agent block owns
+// its own rendering; live lines are best-effort decoration.
+function appendSubagentLog(subId, evType, content) {
+    const chat = $('#chat');
+    const host = chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`);
+    if (!host) return;
+    const body = host.querySelector('.sa-body');
+    if (!body) return;
+    if (evType === 'stream') {
+        // Coalesce contiguous stream text into one line (typewriter feel)
+        let last = body.lastElementChild;
+        if (last && last.classList.contains('sa-stream')) {
+            last.textContent += content;
+        } else {
+            last = document.createElement('div');
+            last.className = 'sa-stream';
+            last.textContent = content;
+            body.appendChild(last);
+        }
+    } else {
+        const line = document.createElement('div');
+        const icon = evType === 'tool_use' ? '🔧' : evType === 'tool_result' ? '↳' : evType === 'thinking' ? '💭' : '';
+        line.style.cssText = 'margin-top:2px;color:' + (evType === 'tool_use' ? '#c4b5fd' : '#94a3b8');
+        const short = content.length > 300 ? content.slice(0, 300) + '…' : content;
+        line.textContent = `${icon} ${short}`;
+        body.appendChild(line);
+    }
+    body.scrollTop = body.scrollHeight;
+}
+
 // Central renderer for all log entry types (text, tool, tool_result, stream, user_message, etc.)
 // anchor = insert before this node instead of appending — used by loadMoreLogs for prepend
-function addChatEntry(type, content, ts, anchor) {
+// payload = full SSE log object (carries subagent_id for sub-agent nesting)
+function addChatEntry(type, content, ts, anchor, payload) {
     if (HIDE_THINKING && type === 'thinking') return;
+    // Live sub-agent output → nest inside the sub-agent accordion, not the main flow
+    if ((type === 'subagent_stream' || type === 'subagent_event') && payload && payload.subagent_id) {
+        appendSubagentLog(payload.subagent_id, payload.event_type || 'stream', content);
+        return;
+    }
     if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
     const chat = $('#chat');
     let _insertedBeforeStream = false;
     const _insert = (el) => {
         if (anchor) return chat.insertBefore(el, anchor);
         if (streamBubble && streamBubble.parentNode === chat) {
             _insertedBeforeStream = true;
             return chat.insertBefore(el, streamBubble);
@@ -2234,48 +2272,79 @@ function addChatEntry(type, content, ts, anchor) {
             const eq = p.indexOf('=');
             if (eq > 0 && /^\w+$/.test(p.slice(0, eq))) meta[p.slice(0, eq)] = p.slice(eq + 1);
             else if (p) textParts.push(p);
         }
         const desc = textParts[0] || textParts[1] || '';
         const el = document.createElement('div');
         el.style.cssText = 'font-size:11px;padding:4px 10px;margin:2px 0;border-radius:6px;overflow-wrap:anywhere';
 
+        const subId = (payload && payload.subagent_id) || meta.id || '';
+
         if (type === 'subagent_start') {
+            // Collapsible accordion: header + body where live sub-agent logs nest.
             el.style.cssText += ';border-left:3px solid #a78bfa;background:rgba(99,102,241,0.06);color:#c4b5fd';
-            el.innerHTML = `🤖 <span style="color:#e2e8f0">Sub-agent: "${DOMPurify.sanitize(desc)}"</span>`;
-            if (meta.type) {
-                const sub = document.createElement('div');
-                sub.style.cssText = 'font-size:10px;color:#64748b;margin-top:1px;padding-left:20px';
-                sub.textContent = `type: ${meta.type}`;
-                el.appendChild(sub);
-            }
+            if (subId) el.dataset.subagentId = subId;
+            const header = document.createElement('div');
+            header.style.cssText = 'cursor:pointer;user-select:none';
+            header.innerHTML = `<span class="sa-caret">▶</span> 🤖 <span style="color:#e2e8f0">Sub-agent: "${DOMPurify.sanitize(desc)}"</span>${meta.type ? ` <span style="color:#64748b;font-size:10px">(${DOMPurify.sanitize(meta.type)})</span>` : ''}`;
+            const body = document.createElement('div');
+            body.className = 'sa-body';
+            body.style.cssText = 'margin-top:4px;padding-left:14px;border-left:1px dashed #4c1d95;display:none;font-size:10px;color:#94a3b8;white-space:pre-wrap;max-height:300px;overflow-y:auto';
+            let _expanded = false;
+            header.addEventListener('click', () => {
+                _expanded = !_expanded;
+                body.style.display = _expanded ? 'block' : 'none';
+                header.querySelector('.sa-caret').textContent = _expanded ? '▼' : '▶';
+            });
+            el.appendChild(header);
+            el.appendChild(body);
         } else if (type === 'subagent_progress') {
-            el.style.cssText += ';color:#64748b';
+            // Update the live progress line inside the matching accordion (or standalone)
             const tokens = meta.tokens ? (parseInt(meta.tokens) >= 1000 ? (parseInt(meta.tokens) / 1000).toFixed(1) + 'k' : meta.tokens) : '';
-            el.textContent = `⏳ "${desc}" — ${meta.tool ? 'using ' + meta.tool : ''}${tokens ? ' | ' + tokens + ' tokens' : ''}`;
-        } else {
+            const line = `⏳ ${meta.tool ? 'using ' + meta.tool : 'working'}${tokens ? ' | ' + tokens + ' tokens' : ''}`;
+            const host = subId ? chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`) : null;
+            if (host) {
+                let prog = host.querySelector('.sa-progress');
+                if (!prog) {
+                    prog = document.createElement('div');
+                    prog.className = 'sa-progress';
+                    prog.style.cssText = 'font-size:10px;color:#64748b;padding-left:14px;margin-top:2px';
+                    host.appendChild(prog);
+                }
+                prog.textContent = line;
+                return;  // updated in place, no new bubble
+            }
+            el.style.cssText += ';color:#64748b';
+            el.textContent = `⏳ "${desc}" — ${line}`;