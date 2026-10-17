# Context for item-48

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/.orchestra/projects-pre-v621-20261013T121451Z.yaml b/.orchestra/projects-pre-v621-20261013T121451Z.yaml
new file mode 100644
index 000000000..c3316456f
--- /dev/null
+++ b/.orchestra/projects-pre-v621-20261013T121451Z.yaml
@@ -0,0 +1,63 @@
+version: 1
+include_scopes:
+- /home/kesha/katya-work
+- /home/kesha/openrouter-lab
+- /home/kesha/projects/University
+- /home/kesha/projects/VPN-Service
+- /home/kesha/projects/comfy-image-pipeline
+- /home/kesha/projects/dnd-game-master
+- /home/kesha/projects/kesha-tg-bot
+- /home/kesha/projects/seedon
+- /opt/cog-second-brain
+projects:
+- tag: orchestra
+  name: Orchestra
+  scope: /home/kesha/orchestra
+  write_namespace: home-kesha-orchestra-8b68cd9600cc
+  namespaces:
+    home-kesha-orchestra-8b68cd9600cc: ''
+    orchestra: ноутбук
+    vps-orchestra: старый VPS
+    orchestra-15ebb64920a9: ноутбук
+    mnt-data-projects-python-orchestra-13dc8d0cd9fb: ноутбук
+- tag: polus
+  name: Полюс
+  namespaces:
+    polus: ноутбук
+- tag: sensar
+  name: Sensar
+  namespaces:
+    sensar-5e197e867bb2: ноутбук
+- tag: parsing-hub
+  name: Parsing Hub
+  namespaces:
+    parsing-hub: ноутбук
+- tag: stargate-tactics
+  name: Stargate Tactics
+  namespaces:
+    stargate-tactics: ноутбук
+- tag: family-tree
+  name: Семейное древо
+  archived: true
+  namespaces:
+    family-tree: ноутбук
+- tag: inscryption-ai
+  name: Inscryption AI
+  archived: true
+  namespaces:
+    inscryption-ai: ноутбук
+- tag: tradingcryptobot
+  name: Trading Crypto Bot
+  archived: true
+  namespaces:
+    tradingcryptobot: ноутбук
+- tag: webview
+  name: WebView
+  archived: true
+  namespaces:
+    webview-c212de852078: ноутбук
+- tag: zahoron-mobile
+  name: Захорон (мобильный)
+  archived: true
+  namespaces:
+    zahoron-mobile: ноутбук
diff --git a/.orchestra/projects.yaml b/.orchestra/projects.yaml
index c3316456f..dc4e227f2 100644
--- a/.orchestra/projects.yaml
+++ b/.orchestra/projects.yaml
@@ -1,42 +1,33 @@
 version: 1
 include_scopes:
 - /home/kesha/katya-work
 - /home/kesha/openrouter-lab
+- /home/kesha/orchestra
 - /home/kesha/projects/University
 - /home/kesha/projects/VPN-Service
 - /home/kesha/projects/comfy-image-pipeline
 - /home/kesha/projects/dnd-game-master
 - /home/kesha/projects/kesha-tg-bot
 - /home/kesha/projects/seedon
 - /opt/cog-second-brain
 projects:
-- tag: orchestra
-  name: Orchestra
-  scope: /home/kesha/orchestra
-  write_namespace: home-kesha-orchestra-8b68cd9600cc
-  namespaces:
-    home-kesha-orchestra-8b68cd9600cc: ''
-    orchestra: ноутбук
-    vps-orchestra: старый VPS
-    orchestra-15ebb64920a9: ноутбук
-    mnt-data-projects-python-orchestra-13dc8d0cd9fb: ноутбук
 - tag: polus
   name: Полюс
   namespaces:
     polus: ноутбук
 - tag: sensar
   name: Sensar
   namespaces:
     sensar-5e197e867bb2: ноутбук
 - tag: parsing-hub
   name: Parsing Hub
   namespaces:
     parsing-hub: ноутбук
 - tag: stargate-tactics
   name: Stargate Tactics
   namespaces:
     stargate-tactics: ноутбук
 - tag: family-tree
   name: Семейное древо
   archived: true
   namespaces:
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 1ac68267f..8e1a9b2af 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,29 +1,30 @@
 # Changelog
 
 > **Two environments merged, 04.08.2026.** Before this date, the laptop and VPS maintained
 > their CHANGELOGs independently, so versions 2.31.0-2.33.0 were used TWICE for different
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
 ### Added
+- **Live generation and running-tool activity in the dashboard chat** (`app/backend_claude.py`, `app/session.py`, `app/live_broker.py`, `app/task_output_tail.py`, `app/routes/sessions.py`, `app/static/js/live-activity.js`, `app/static/js/chat.js`; V-831). Claude partial messages are no longer filtered to `text_delta`: `input_json_delta` becomes `tool_input_stream` (tool id/name from `content_block_start`, keyed by parent and block index so sub-agents do not collide) and `thinking_delta` becomes `thinking_stream`, including the `estimated_tokens` counter the CLI sends when thinking text is omitted. The chat shows a card for the call being written — tool name, decoded argument text, character count, chars/s and elapsed time — replaced by the normal card when the persisted `tool` row lands. Every unanswered tool call shows a pulsing "running m:ss of m:ss" clock (Bash `timeout`, default 2:00, cap 10:00; elapsed only for tools without a timeout), and shell tasks (`local_bash`, foreground or background) show live output tailed from the CLI's `tasks/<task_id>.output` file. The SSE loop merges adjacent deltas of one block per ~100 ms tick, the broker keeps a capped tail of each open block so a reopened chat resumes it, and nothing partial is written to `logs`. Codex app-server 0.160.0 has no tool-argument delta notification, so Codex keeps its existing reasoning/output streams. Trigger: a 42 KB Bash heredoc took minutes to write with nothing visible, and running commands looked dead.
 - **CI and local agent-documentation integrity check** (`scripts/check_instruction_contract.py`, `.github/workflows/ci.yml`; V-826). The instruction contract command reuses `app.kb_index` to check KB topic/index coverage and resolves relative Markdown and backtick file references in `AGENTS.md` and `.orchestra/kb/*.md`; CI runs it once in the test shards. Trigger: KB topics can be invisible to agents when absent from its index, and stale paths misdirect readers.
 - **Optional event-synced sound layer for video-artifact** (`scripts/video_artifact/make.py`, `scripts/video_artifact/sound/`; V-824). HTML and Manim steps can declare timed `events`; `make.py` maps them from the voice-derived step plan into a cue sheet, mixes selected CC0 effects, looped music and the existing voice with ducking, then muxes and runs picture/audio QA. The CC0 kit defaults to `~/.local/share/orchestra-sfx/`; scenes without events retain the voice-only path. Trigger: the video builder had no sound beyond speech, and sparse effects alone produced an unusable loudness target and silence failures.
 
 ### Changed
 - **Consolidate visual skills and version the deployment workflow** (`.orchestra/pipelines/default/prompts/skills/`, `pipeline.yaml`, `app/prompting.py`, `app/session.py`, `scripts/video_artifact/`; V-819). Animation/playback guidance is part of the single visual-artifact skill, with its full player scaffold delivered as an on-demand reference so the entrypoint stays within the existing 16 KiB budget. The narrated-video skill and its internal script directory use one name, and the obsolete review skill is removed. The pipeline distributes the deployment skill only to orchestrator roles. On refresh, an untracked stale copy is removed only when its bytes match a historical canonical skill revision; tracked or locally edited copies remain untouched. Trigger: the owner requested one visual skill, removal of the frozen review skill, and an up-to-date owner-authorized deploy workflow.
 
 ### Added
 - **Hidden orchestrator menu shows live status and cache expiry** (`app/static/js/app.js`; V-820). Hidden rows use the same orchestrator status painter and cache pill as pinned tabs, and an open menu refreshes with orchestrator polling and live status updates. Waiting uses 📆 consistently with the Telegram status vocabulary. Trigger: the 👁 menu listed hidden orchestrators by name only, so it hid working/waiting and cache state.
 - **Quota-held first tasks follow the worker's current model and can be cancelled by delivery ID** (`app/initial_deliveries.py`, `app/routes/sessions.py`; V-810). A retry rechecks the current model's quota preflight and atomically queues/wakes the existing task when the gate is open; successful model changes run an immediate queue sweep, while the periodic sweep rechecks after a concurrent model switch. `cancel_message_delivery` now also cancels an initial task in `WAITING_QUOTA` or `QUEUED`; it refuses once the runner reaches `PREPARING` and verifies the original sender. Trigger: after an Opus worker changed to Luna, its first task still appeared Claude-blocked and the advertised cancel tool returned 404.
 - **Worker spawn validates `delivery_id` before creating or binding a session** (`app/mcp_stdio.py`, `app/routes/sessions.py`; V-808). MCP `spawn_worker` rejects a non-empty malformed ID as `invalid_argument`, and HTTP `/api/sessions` rejects it during request validation; empty IDs keep their existing behavior. Trigger: a non-UUID delivery ID created and task-bound a worker before initial delivery failed with a UUID parsing error.
 - **Telegram topics show waiting with a third icon and preserve their titles** (`app/tg_bridge.py`, `app/mailbox.py`, `app/quota_queue.py`, `app/workflow_scheduler.py`; V-804/V-805). A stable wait from a queued owner/dashboard message, an in-memory message queue, a quota-held delivery, a workflow waiting for a shared slot, or a session waiting on background work uses the available calendar icon 📆; active work keeps ⚡ ahead of waiting, and idle without pending work uses ☕. The icon reverts when waiting ends; the topic name never changes. Topic state changes coalesce per topic and share the group rate limiter. Trigger: the dashboard exposed waiting while Telegram topics showed only running/idle; the owner requested the wait state as a topic icon instead of a title prefix.
 - **Shared dynamic workflow admission and cgroup isolation** (`app/workflow_scheduler.py`, `app/agent_cgroups.py`, `app/routes/bg.py`, `scripts/wf_run.py`; V-782). Workflow model calls acquire durable SQLite leases through Orchestra; admission is shared and fair across runs, and the limit follows CPU capacity, delegated-slice memory headroom, measured per-call memory samples, and PSI pressure. Queued calls do not consume call budget or dispatch accounting. At startup, leftover processes in the delegated service root move into `orchestra-api` before CPU, IO, and memory controllers are enabled; dynamic workflow runners and provider CLIs then enter `agents`, with weights below the API sibling and memory limits derived from the service limits. The workflow card and manifest expose waiting position, active/queued slots, and the limit reason. Trigger: concurrent workflow fan-outs and test/model processes exhausted the Orchestra service cgroup and stalled the API on 2026-10-08.
 - **Claude API-credit usage ledger and dashboard estimate** (`app/claude_api_credits.py`, `app/db.py`, `app/static/js/analytics.js`; V-774, routing replaced by V-800). `turn_usage.billing_mode` identifies recorded credit charges and the owner dashboard shows the remaining estimate and expiry. The estimate starts from the verified Console balance and subtracts recorded API-credit usage; it does not observe usage from other Console clients. The initial session fallback was retired in V-800 after ordinary workers spent $202 from a $200 balance in 21 hours.
 - **Readable live cards for dynamic workflows** (`app/routes/bg.py`, `app/static/js/chat.js`, `app/static/js/i18n.js`, `scripts/wf_run.py`, `app/mcp_stdio.py`; V-776). The dashboard shows workflow mode, tasks, stages, models, limits and budget, then polls the read-only run endpoint for progress, cost, elapsed time, per-task answers, preparation errors and result links. Task labels connect journal events to their prompts; repeated prompts collapse to one template with differing values. Trigger: `dynamic_workflow` appeared as raw argument fields and a queued `run_id` line, leaving progress and `prepare_failed` outcomes hidden.
 - **Back up Orchestra's canonical task store and live SQLite database** (`scripts/orchestra_backup.py`, V-772/V-793). The task store is pushed hourly to a GitHub repository created private and checked through the API; each push scans unpublished commits with `scripts/secret_scan.py`, so a secret-form match blocks it. The daily database copy uses SQLite's backup API for the live WAL database and stores the two newest verified compressed local copies. The existing hourly task-store job checks laptop reachability, uploads the newest local archive when the reverse tunnel returns, and exits after a matching remote manifest without hashing the 1.3 GB archive; it stays silent while the laptop is offline and reports copies older than three days. Trigger: the live database and canonical task store had no confirmed backup, a sleeping laptop missed the daily upload, and hourly whole-archive verification burdened the laptop.
 - **Route bounded, oracle-checked work to Haiku 5.5 at low effort** (`.orchestra/pipelines/default/prompts/modules/model-routing.md`, `.orchestra/pipelines/default/pipeline.yaml`; V-766). The router excludes open-ended or delivery-critical work after 4/40 hard benchmark runs stalled waiting for background checks; every role's effort map selects low for Haiku. Trigger: V-758 measured 10/10 small-task passes at low, without a quality gain from higher effort and at substantially higher cost.
 - **Per-model generation speed to usage analytics** (`app/backend_claude.py`, `app/backend_codex.py`, `app/db.py`, `app/usage_analytics.py`, `app/static/js/analytics.js`; V-761). Turns store wall duration and provider API duration when available. Codex estimates model time by subtracting the union of local tool intervals from wall duration, while preserving raw interval sums and the measurement basis. The additive startup migration no-ops if `turn_usage` does not yet exist, so stubbed initialization and pre-schema harnesses cannot abort lifespan. The analytics view shows rolling one-hour and one-day medians plus a time series. Trigger: `turn_usage` stored tokens and timestamps but no duration; full Codex turn time included long command/test waits, while startup tests that stubbed `init_db()` hit a missing table.
 
 ### Fixed
 - **Restore Manim voice-scene setup and compile-check its Python sources** (`scripts/video_artifact/manim_voice.py`, `tests/test_video_artifact.py`; V-829). Indented the `VIDEO_ARTIFACT_VOICE` read inside `VoiceScene.setup()` and added a test compiling every `.py` under `scripts/video_artifact/`, including `sound/`. Trigger: V-819's moved Manim scene had an unindented function body, so every Manim render stopped with `IndentationError` before scene construction.
diff --git a/app/backend_claude.py b/app/backend_claude.py
index bfe5c7030..79422f3c7 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -678,40 +678,44 @@ class ClaudeBackend:
         # F2: user-MCP из профильного .claude.json (базовый слой merge).
         self._user_mcp_servers = user_mcp_servers or {}
         self._effort = effort
         if history_import is not None and not isinstance(history_import, ClaudeHistoryImport):
             raise TypeError("history_import must be ClaudeHistoryImport")
         self._history_import = history_import
         self._validation_profile = validation_profile
         self._client: Optional[ClaudeSDKClient] = None
         self._session_id: str | None = resume_session_id
         self.resume_failed = False
         self._stderr_tail = ""
         self._pending_model_error = ""
         self._assistant_usage_by_message_id: dict[str, dict] = {}
         self._assistant_usage_incomplete = False
         # SDK content events point at parent tool_use_id, while Task* lifecycle
         # messages use task_id. Keep the bridge so live output and persisted
         # lifecycle records address the same UI card.
         self._subagent_tool_to_task: dict[str, str] = {}
         self._subagent_descriptions: dict[str, str] = {}
         self._subagent_types: dict[str, str] = {}
+        # Open streamed content blocks keyed by (parent_tool_use_id, index): a delta names
+        # only its index, while the tool id/name arrive once in content_block_start.
+        self._open_stream_blocks: dict[tuple[str, int], dict] = {}
+        self._stream_block_seq = 0
         # #224: имя файла конфига. Идентичность берём ТОЛЬКО из доверенного сервера
         # `orchestra` — плоский merge сюда пускать нельзя: кастомный сервер со спавна
         # перетирает чужие ключи и может подсунуть `../..` (см. CodexBackend).
         # Суффикс на ЭКЗЕМПЛЯР обязателен: при реконнекте создаётся новый бэкенд той же
         # сессии, и при общем имени файла `disconnect()` старого уносил бы конфиг живого —
         # перезапуск MCP-сервера остался бы без конфигурации.
         self._mcp_config_key = (
             _safe_config_key(
                 (self._mcp_servers.get("orchestra", {}).get("env") or {}).get("ORCHESTRA_SESSION_ID")
             )
             + "-" + uuid.uuid4().hex[:8]
         )
         self._mcp_config_path: Path | None = None
 
     @property
     def session_id(self) -> Optional[str]:
         return self._session_id
 
     async def retarget_model(self, model: str) -> None:
         """Switch the persistent SDK conversation at a native turn boundary."""
@@ -1396,50 +1400,98 @@ class ClaudeBackend:
             str(parent_tool_use_id),
         )
 
     @staticmethod
     def _tag_sub(event: AgentEvent, sub_id) -> AgentEvent:
         """Mark an event as belonging to a sub-agent so the UI nests it.
 
         sub_id None (main agent) → event unchanged. Otherwise stamp subagent_id;
         the type is preserved (tool_use stays tool_use) — the frontend groups by
         subagent_id, not by a renamed type."""
         if sub_id is not None:
             event.metadata = {**event.metadata, "subagent_id": sub_id}
         return event
 
     def _convert(self, msg) -> list[AgentEvent]:
         events = []
         if isinstance(msg, StreamEvent):
             # Main-agent text partials → "stream". Subagent partials (parent_tool_use_id
             # set) → "subagent_stream" tagged with sub_id so the UI nests them under the
             # sub-agent block instead of dropping them (which looked like a hang).
+            # Tool-call arguments (input_json_delta) and thinking (thinking_delta) are
+            # streamed the same way: live-only events, the final AssistantMessage blocks
+            # stay the persisted record.
             ev = msg.event or {}
-            if ev.get("type") != "content_block_delta":
+            ev_type = ev.get("type")
+            parent = str(msg.parent_tool_use_id or "")
+            sub_id = self._resolve_subagent_id(msg.parent_tool_use_id)
+            if ev_type == "message_start":
+                for key in [k for k in self._open_stream_blocks if k[0] == parent]:
+                    del self._open_stream_blocks[key]
+                return events
+            if ev_type == "content_block_start":
+                block = ev.get("content_block") or {}
+                key = (parent, int(ev.get("index") or 0))
+                if block.get("type") in ("tool_use", "server_tool_use", "mcp_tool_use"):
+                    name = str(block.get("name") or "")
+                    info = {"kind": "tool", "tool_use_id": str(block.get("id") or ""),
+                            "tool_name": name,
+                            "short_name": name.split("__")[-1] if "__" in name else name}
+                    self._open_stream_blocks[key] = info
+                    meta = {k: v for k, v in info.items() if k != "kind"}
+                    events.append(self._tag_sub(AgentEvent("tool_input_stream", "", metadata=meta), sub_id))
+                elif block.get("type") == "thinking":
+                    self._stream_block_seq += 1
+                    self._open_stream_blocks[key] = {
+                        "kind": "thinking", "item_id": f"claude-thinking-{self._stream_block_seq}"}
+                return events
+            if ev_type == "content_block_stop":
+                self._open_stream_blocks.pop((parent, int(ev.get("index") or 0)), None)
+                return events
+            if ev_type != "content_block_delta":
                 return events
             delta = ev.get("delta") or {}
-            if delta.get("type") != "text_delta":
+            delta_type = delta.get("type")
+            block = self._open_stream_blocks.get((parent, int(ev.get("index") or 0))) or {}
+            if delta_type == "input_json_delta":
+                chunk = delta.get("partial_json") or ""
+                if chunk and block.get("kind") == "tool":
+                    meta = {k: v for k, v in block.items() if k != "kind"}
+                    events.append(self._tag_sub(AgentEvent("tool_input_stream", chunk, metadata=meta), sub_id))
+                return events
+            if delta_type == "thinking_delta":
+                # With thinking display omitted the CLI streams empty text plus a running
+                # `estimated_tokens` count (CLI 2.1.x, 13.10.2026) — still a sign of life.
+                chunk = delta.get("thinking") or ""
+                estimated = delta.get("estimated_tokens")
+                if chunk or estimated:
+                    meta = {"activity": "reasoning",
+                            "item_id": block.get("item_id") or "claude-thinking"}
+                    if estimated:
+                        meta["estimated_tokens"] = int(estimated)
+                    events.append(self._tag_sub(AgentEvent("thinking_stream", chunk, metadata=meta), sub_id))
+                return events
+            if delta_type != "text_delta":
                 return events
             text = delta.get("text") or ""
             if not text:
                 return events
-            sub_id = self._resolve_subagent_id(msg.parent_tool_use_id)
             if sub_id is not None:
                 events.append(AgentEvent("subagent_stream", text, metadata={"subagent_id": sub_id}))
             else:
                 events.append(AgentEvent("stream", text))
             return events
 
         if isinstance(msg, AssistantMessage):
             self._remember_assistant_usage(msg)
             # Subagent messages carry parent_tool_use_id → tag events so the UI groups
             # them under the sub-agent block instead of mixing with the parent's stream.
             sub_id = self._resolve_subagent_id(
                 getattr(msg, "parent_tool_use_id", None)
             )
             for block in msg.content:
                 if isinstance(block, TextBlock) and block.text:
                     events.append(self._tag_sub(AgentEvent("text", block.text), sub_id))
                 elif isinstance(block, ThinkingBlock) and block.thinking:
                     events.append(self._tag_sub(AgentEvent("thinking", block.thinking), sub_id))
                 elif isinstance(block, ToolUseBlock):
                     try:
diff --git a/app/events.py b/app/events.py
index 955f95ecf..dc911382c 100644
--- a/app/events.py
+++ b/app/events.py
@@ -111,20 +111,24 @@ class InjectedMessage:
 class AgentEvent:
     type: str
     content: str = ""
     metadata: dict = field(default_factory=dict)
     usage: TurnUsage | None = None
 
 # type values:
 # "text"              — agent text output
 # "thinking"          — agent reasoning/thinking output
 # "tool_use"          — tool invocation (content = "tool_name: input_summary")
 # "tool_result"       — tool output
 # "file_change"       — file edit (content = "add /path" or "update /path")
 # "turn_end"          — turn completed (metadata: session_id, cost_usd, input_tokens, context_pct, ok, stop_reason, ...)
 # "provider_limit"    — provider-owned quota status (metadata: status, rate_limit_type, resets_at)
 # "error"             — error message
 # "status"            — lifecycle event
 # "subagent_start"    — sub-agent spawned    (metadata: subagent_id, phase, description, task_type, sdk_session_id, tool_use_id)
 # "subagent_progress" — sub-agent working     (metadata: + last_tool_name, total_tokens, tool_uses, duration_ms)
 # "subagent_end"      — sub-agent finished    (metadata: + status, summary, output_file, raw_json, usage)
 # "subagent_stream"   — sub-agent live text   (metadata: subagent_id) — broker only, ephemeral
+# "thinking_stream"   — live reasoning delta  (metadata: activity, item_id) — broker only
+# "tool_input_stream" — live tool-call argument JSON delta (metadata: tool_use_id, tool_name,
+#                       short_name; empty content = block started) — broker only
+# "tool_stream"       — live tool output delta (metadata: tool_use_id) — broker only
diff --git a/app/live_broker.py b/app/live_broker.py
index b51e96b46..d37651e77 100644
--- a/app/live_broker.py
+++ b/app/live_broker.py
@@ -1,82 +1,176 @@
 """In-memory pub/sub for live (ephemeral) stream partials — bypasses the DB.
 
 Single process, single event loop. Partials are best-effort: a slow consumer
 drops oldest chunks rather than blocking the session event loop. The final
 DB-persisted 'text' log is always authoritative on reload/reconnect.
 
 Not compatible with multi-worker uvicorn (in-memory, like the session manager).
 """
 import asyncio
+import time
 from collections import defaultdict
 
-_MAXSIZE = 256  # per-subscriber backlog; drop-oldest beyond this
+_MAXSIZE = 1024  # per-subscriber backlog; drop-oldest beyond this
 STREAM_CLOSE = object()
 
+# Live blocks a client opening the chat mid-generation must still see: the tool call being
+# written, current reasoning, running command output. Only the tail is kept for replay.
+_LIVE_KEYS = {
+    "tool_input_stream": ("tool_use_id", 64 * 1024),
+    "thinking_stream": ("item_id", 32 * 1024),
+    "tool_stream": ("tool_use_id", 16 * 1024),
+}
+
+
+def live_key(payload: dict) -> tuple[str, str] | None:
+    spec = _LIVE_KEYS.get(payload.get("type"))
+    if not spec or payload.get("activity") == "waiting":
+        return None
+    key = payload.get(spec[0])
+    return (payload["type"], str(key)) if key else None
+
+
+_MERGE_FIELDS = {
+    "stream": (),
+    "subagent_stream": ("subagent_id", "event_type", "item_id"),
+    "thinking_stream": ("item_id", "activity"),
+    "tool_input_stream": ("tool_use_id",),
+    "tool_stream": ("tool_use_id", "stream", "subagent_id"),
+}
+
+
+def coalesce(payloads: list) -> list:
+    """Glue adjacent deltas of the same live block into one SSE frame.
+
+    The SSE loop drains the queue every ~100 ms; a long tool call arrives as thousands of
+    tiny JSON fragments, and one frame per fragment would make the browser parse and
+    repaint per fragment. Only neighbours merge, so the order of blocks is preserved.
+    """
+    out: list = []
+    for payload in payloads:
+        fields = _MERGE_FIELDS.get(payload.get("type")) if isinstance(payload, dict) else None
+        prev = out[-1] if out else None
+        if (fields is not None and isinstance(prev, dict)
+                and prev.get("type") == payload.get("type")
+                and payload.get("activity") != "waiting"
+                and not payload.get("replace")
+                and all(prev.get(f) == payload.get(f) for f in fields)):
+            merged = {**prev, **payload, "content": prev.get("content", "") + payload.get("content", "")}
+            if prev.get("replace"):
+                merged["replace"] = True
+            out[-1] = merged
+        else:
+            out.append(payload)
+    return out
+
 
 class LiveBroker:
     def __init__(self) -> None:
         self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
         self._accum: dict[str, str] = {}
+        self._live: dict[str, dict[tuple[str, str], dict]] = {}
         self._closing = False
 
     def subscribe(self, session_id: str) -> asyncio.Queue:
         q: asyncio.Queue = asyncio.Queue(maxsize=_MAXSIZE)
         if self._closing:
             q.put_nowait(STREAM_CLOSE)
             return q
         # Replay accumulated stream text so reconnecting clients see what they missed
         current = self._accum.get(session_id, "")
         if current:
             try:
                 q.put_nowait({"type": "stream", "content": current})
             except asyncio.QueueFull:
                 pass
+        for item in tuple(self._live.get(session_id, {}).values()):
+            replay = {k: v for k, v in item.items() if not k.startswith("_")}
+            replay["replace"] = True
+            if "_started" in item:
+                replay["elapsed_ms"] = int((time.monotonic() - item["_started"]) * 1000)
+            try:
+                q.put_nowait(replay)
+            except asyncio.QueueFull:
+                pass
         self._subs[session_id].add(q)
         return q
 
     def unsubscribe(self, session_id: str, q: asyncio.Queue) -> None:
         subs = self._subs.get(session_id)
         if subs:
             subs.discard(q)
             if not subs:
                 self._subs.pop(session_id, None)
 
     def publish(self, session_id: str, payload: dict) -> None:
         if self._closing:
             return
         # Второй шов маскирования (#224): этот путь в БД не пишется вовсе ("NEVER persist"),
         # поэтому маскирование в db.add_log его не закрывает. Маскируем ДО _accum — иначе
         # реплей отдаст новому подписчику сырое значение.
         if payload.get("type") == "stream":
             self._accum[session_id] = self._accum.get(session_id, "") + payload.get("content", "")
+        key = live_key(payload)
+        if key is not None:
+            payload = self._remember_live(session_id, key, payload)
         for q in tuple(self._subs.get(session_id, ())):  # snapshot — safe if set mutates
             if q.full():
                 try:
                     q.get_nowait()  # drop oldest — partials are ephemeral
                 except asyncio.QueueEmpty:
                     pass
             try:
                 q.put_nowait(payload)
             except asyncio.QueueFull:
                 pass
 
+    def _remember_live(self, session_id: str, key: tuple[str, str], payload: dict) -> dict:
+        blocks = self._live.setdefault(session_id, {})
+        item = blocks.get(key)
+        content = payload.get("content", "")
+        if item is None:
+            item = {"content": "", "chars": 0, "_started": time.monotonic()}
+            blocks[key] = item
+        item.update({k: v for k, v in payload.items() if k != "content"})
+        item["content"] = (item["content"] + content)[-_LIVE_KEYS[key[0]][1]:]
+        item["chars"] += len(content)
+        if key[0] != "tool_input_stream":
+            return payload
+        # The writer's speed is computed server-side: browser and server clocks differ.
+        return {**payload, "chars": item["chars"],
+                "elapsed_ms": int((time.monotonic() - item["_started"]) * 1000)}
+
+    def end_live(self, session_id: str, kind: str, key: str = "") -> None:
+        """Forget a replayable live block once its persisted record exists (all of a kind
+        when key is empty)."""
+        blocks = self._live.get(session_id)
+        if not blocks:
+            return
+        for live in [k for k in blocks if k[0] == kind and (not key or k[1] == key)]:
+            del blocks[live]
+        if not blocks:
+            self._live.pop(session_id, None)
+
+    def clear_live(self, session_id: str) -> None:
+        self._live.pop(session_id, None)
+
     def clear_accum(self, session_id: str) -> None:
         """Clear accumulated stream text — call when final 'text' event arrives."""
         self._accum.pop(session_id, None)
 
     def close_subscribers(self) -> None:
         """Ask all current SSE generators to finish before graceful shutdown."""
         self._closing = True
         for queues in tuple(self._subs.values()):
             for q in tuple(queues):
                 if q.full():
                     try:
                         q.get_nowait()
                     except asyncio.QueueEmpty:
                         pass
                 try:
                     q.put_nowait(STREAM_CLOSE)
                 except asyncio.QueueFull:
                     pass
 
 
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index a73882951..e2cb7318b 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -662,70 +662,76 @@ async def stream_session_logs(name: str, scope: str, request: Request, after_id:
     def with_status(payload: dict) -> dict:
         # Живую сессию перерешаем на КАЖДОМ событии: на коннекте её может не быть в
         # реестре (idle-воркер не загружен), а через минуту её грузит `ensure_loaded`
         # и она идёт ход по ЭТОМУ же стриму. Клиент верит `agent_status` каждого
         # события, поэтому статус, замороженный на коннекте, затирал бы верный.
         live_session = manager.get(session_id)
         status = (
             live_session.status.value
             if live_session is not None
             else str((stored or {}).get("status") or "idle")
         )
         result = annotate_user_message({**payload, "agent_status": status})
         if payload.get("type") == "status":
             result["status_hidden"] = is_internal_telemetry_status(
                 str(payload.get("content") or "")
             )
         return result
 
     async def event_generator():
         from app.db import _conn
-        from app.live_broker import STREAM_CLOSE, broker
+        from app.live_broker import STREAM_CLOSE, broker, coalesce
         last_id = after_id
         c = _conn()
         q = broker.subscribe(session_id)  # session_id == manager.get_session_id == session.id
         try:
             # Первым делом называем сессию, которую мы разрешили из name+scope. Клиент
             # держит историю по session_id и до этого события знает её лишь по своей карте,
             # которая могла устареть (агента убили и подняли под тем же именем). Правду
             # знает только сервер, и он обязан сказать её ДО первой строки истории.
             yield f"data: {json.dumps(with_status({'type': '__session', 'session_id': session_id}))}\n\n"
             # initial history first (one-shot) — preserves load-more behavior
             if after_id == 0:
                 for log in get_logs_before(session_id, before_id=2**31 - 1, limit=limit):
                     yield f"data: {json.dumps(with_status(log))}\n\n"
                     last_id = log["id"]
             while True:
                 if await request.is_disconnected():
                     return
                 # 1) drain live partials FIRST (ephemeral, no id) — they always
                 #    precede their final 'text' row, so emit before polling DB.
-                drained = 0
-                while drained < 500:  # cap per tick — don't starve disconnect check
+                batch = []
+                closing = False
+                while len(batch) < 500:  # cap per tick — don't starve disconnect check
                     try:
                         payload = q.get_nowait()
                     except asyncio.QueueEmpty:
                         break
                     if payload is STREAM_CLOSE:
-                        return
+                        closing = True
+                        break
+                    batch.append(payload)
+                drained = len(batch)
+                for payload in coalesce(batch):
                     yield f"data: {json.dumps(with_status(payload))}\n\n"
-                    drained += 1
+                if closing:
+                    return
                 # 2) DB-persisted logs (finals + all other log types)
                 logs = get_logs(session_id, after_id=last_id, conn=c)
                 for log in logs:
                     yield f"data: {json.dumps(with_status(log))}\n\n"
                     last_id = log["id"]
                 # 3) short poll while active (partials follow quickly), back off when idle
                 await asyncio.sleep(0.1 if (logs or drained) else 0.5)
         finally:
             broker.unsubscribe(session_id, q)
             c.close()
     return StreamingResponse(event_generator(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
 
 
 @router.get("/api/sessions/{name}/logs")
 async def get_session_logs(name: str, request: Request, scope: str,
                            after_id: int = 0, before_id: int = 0,
                            limit: int = 500, max_bytes: int = 0, cap: int = 0):
     # Live chat snapshots are authoritative state, not an asset. A browser/intermediary
     # replaying an older 200 here recreates the exact "old messages, then SSE catches up"
diff --git a/app/session.py b/app/session.py
index b3fb47f84..726e421e9 100644
--- a/app/session.py
+++ b/app/session.py
@@ -1,41 +1,41 @@
 """AgentSession — backend-agnostic wrapper with persistent event loop."""
 
 import asyncio
 from collections import Counter
 import inspect
 import hashlib
 import json
 import logging
 import os
 import re
 import shutil
 import sqlite3
 import tempfile
 import time
 import uuid
 from dataclasses import dataclass, field, replace
 from datetime import datetime, timezone, timedelta
 from functools import partial, wraps
 from pathlib import Path
 from types import SimpleNamespace
-from typing import TYPE_CHECKING, Awaitable, Callable, Optional
+from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional
 from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
 
 from app import agentic_compact
 from app.events import AgentEvent, InjectedMessage, MessageProvenance
 from app.models import backend_for_model, get_model_spec
 from app.prompting import (
     codex_project_doc_preflight, inject_skills_to_worktree,
     inject_skills_to_worktree_report, is_orchestrator_role,
     prompt_template_hash, refresh_worker_memory,
 )
 from app.quota_gate import QuotaGateError
 from app.runtime_registry import (
     BackendBuildContext,
     _load_scope_mcp_servers,
     _load_user_mcp_servers,
     build_backend,
     get_runtime,
 )
 from app.runtime_history import (
     CLAUDE_CLI_HISTORY_VERSION,
@@ -471,40 +471,41 @@ class AgentSession:
     total_cache_create_tokens: int = 0
     total_tool_calls: int = 0
 
     _backend: Optional["BackendLike"] = field(default=None, repr=False)
     _runtime_error: str = field(default="", repr=False)
     _listen_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _heartbeat_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _background_tasks: set = field(default_factory=set, repr=False)
     _log_futures: set = field(default_factory=set, repr=False)
     _log_write_generation: int = field(default=0, repr=False)
     _log_write_failure_generation: int = field(default=0, repr=False)
     _log_write_failure: str = field(default="", repr=False)
     _failed_log_writes: dict[int, tuple[Callable | None, str]] = field(
         default_factory=dict, repr=False,
     )
     _last_context: dict = field(default_factory=empty_context, repr=False)
     _did_report: bool = field(default=False, repr=False)
     _turn_logs: list = field(default_factory=list, repr=False)
     _last_text_output: Optional[str] = field(default=None, repr=False)
     _tool_names_by_id: dict = field(default_factory=dict, repr=False)
+    _output_tails: Any = field(default=None, repr=False)
     _prompt_injected: bool = field(default=False, repr=False)
     _current_prompt: str = field(default="", repr=False)
     _template_hash: str = field(default="", repr=False)
     _turn_start: float = field(default=0.0, repr=False)
     _last_msg_time: float = field(default=0.0, repr=False)
     _last_event: str = field(default="", repr=False)
     _pending_messages: list = field(default_factory=list, repr=False)
     _pending_owner_initiated_turn: bool = field(default=False, repr=False)
     _owner_initiated_turn: bool = field(default=False, repr=False)
     on_idle: Optional[callable] = field(default=None, repr=False)
     on_turn_blocked: Optional[callable] = field(default=None, repr=False)
     _quota_block_notice_signature: str = field(default="", repr=False)
     _hibernate_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _hibernated: bool = field(default=False, repr=False)
     _compacting: bool = field(default=False, repr=False)
     _compact_ack_event: Optional[asyncio.Event] = field(default=None, repr=False)
     _compact_ack_gen: int = field(default=-1, repr=False)
     _last_cost: float = field(default=0.0, repr=False)
     _turn_cost: float = field(default=0.0, repr=False)
     _context_cost: float = field(default=0.0, repr=False)
@@ -2378,66 +2379,106 @@ class AgentSession:
                         self._spawn_bg(self._flush_pending())
                     else:
                         self._hibernate.schedule()
             if not self._compacting:
                 self._wake_durable_message_deliveries()
 
     def _wake_durable_message_deliveries(self) -> None:
         try:
             from app.message_deliveries import ensure_target_runner
 
             ensure_target_runner(self.id)
         except Exception as error:
             logger.warning(
                 "[%s] durable message-delivery wake failed: %s",
                 self.name,
                 err_text(error),
             )
 
     # ── Unified event handler ──
 
+    def _sync_live_activity(self, event: AgentEvent) -> None:
+        """Retire replayable live partials once their persisted record exists, and
+        follow shell-task output files while the task runs."""
+        from app.live_broker import broker
+        meta = event.metadata
+        if meta.get("subagent_id") and event.type in ("tool_use", "tool_result", "text", "thinking"):
+            return
+        if event.type == "tool_use":
+            broker.end_live(self.id, "tool_input_stream", str(meta.get("tool_use_id") or ""))
+        elif event.type in ("thinking", "text"):
+            # Omitted thinking has no persisted block; the answer closes it instead.
+            broker.end_live(self.id, "thinking_stream")
+        elif event.type == "tool_result":
+            broker.end_live(self.id, "tool_stream", str(meta.get("tool_use_id") or ""))
+        elif event.type == "turn_end":
+            broker.clear_live(self.id)
+        elif event.type == "subagent_start" and meta.get("task_type") == "local_bash":
+            if self._output_tails is None:
+                from app.task_output_tail import TaskOutputTails
+                self._output_tails = TaskOutputTails(lambda payload: broker.publish(self.id, payload))
+            self._output_tails.start(str(meta.get("subagent_id") or ""),
+                                     str(meta.get("tool_use_id") or ""),
+                                     str(meta.get("sdk_session_id") or self.session_id or ""))
+        elif event.type == "subagent_end" and self._output_tails is not None:
+            task_id = str(meta.get("subagent_id") or "")
+            self._output_tails.stop(task_id)
+            broker.end_live(self.id, "tool_stream", str(meta.get("tool_use_id") or ""))
+
     def _handle_event(self, event: AgentEvent) -> None:
         if event.type == "stream":
             # Live partials: push to in-memory broker for SSE fan-out, NEVER persist.
             # The final "text" event (below) is the DB source of truth.
             from app.live_broker import broker
             broker.publish(self.id, {"type": "stream", "content": event.content})
             return
         if event.type == "subagent_stream":
             # Live sub-agent output → broker only (ephemeral, like main stream).
             # subagent_id lets the UI nest it under the right sub-agent block.
             from app.live_broker import broker
             broker.publish(self.id, {"type": "subagent_stream", "content": event.content,
                                      "subagent_id": event.metadata.get("subagent_id", "")})
             return
-        if event.type in ("thinking_stream", "tool_stream", "tool_patch", "turn_diff"):
-            # Codex app-server exposes fine-grained activity that is valuable live but
-            # would flood the DB. The authoritative thinking/tool/file events are still
-            # persisted when their item completes.
+        if event.type in ("thinking_stream", "tool_input_stream", "tool_stream",
+                          "tool_patch", "turn_diff"):
+            # Fine-grained live activity (reasoning, tool arguments being written, command
+            # output) is valuable live but would flood the DB. The authoritative
+            # thinking/tool/file events are still persisted when their item completes.
             from app.live_broker import broker
+            sub_id = event.metadata.get("subagent_id")
+            if sub_id:
+                broker.publish(self.id, {
+                    "type": "subagent_stream", "event_type": event.type,
+                    "content": event.content, "subagent_id": sub_id,
+                    "item_id": event.metadata.get("tool_use_id") or event.metadata.get("item_id") or "",
+                    "tool_name": event.metadata.get("short_name") or "",
+                })
+                return
             payload = {"type": event.type, "content": event.content}
-            for key in ("activity", "item_id", "tool_use_id", "turn_id", "stream"):
+            for key in ("activity", "item_id", "tool_use_id", "turn_id", "stream",
+                        "tool_name", "short_name", "estimated_tokens"):
                 value = event.metadata.get(key)
                 if value:
                     payload[key] = value
             broker.publish(self.id, payload)
             return
+        self._sync_live_activity(event)
         tool_use_id = str(event.metadata.get("tool_use_id") or "")
         tool_name_for_log = str(event.metadata.get("tool_name") or "")
         if event.type == "tool_use" and tool_use_id:
             self._tool_names_by_id[tool_use_id] = (
                 event.metadata.get("tool_name") or "unknown"
             )
         elif event.type == "tool_result" and tool_use_id:
             remembered_name = self._tool_names_by_id.pop(tool_use_id, "unknown")
             tool_name = event.metadata.get("tool_name") or remembered_name
             tool_name_for_log = str(tool_name)
             if event.metadata.get("is_error"):
                 self._submit_db_write(
                     tool_error_add,
                     self.name,
                     self.scope,
                     tool_name,
                     event.content,
                     runtime=self.backend_type,
                     tool_use_id=tool_use_id,
                 )
@@ -4303,40 +4344,42 @@ class AgentSession:
             "max_tokens": target_window,
         }
         self._log(
             "status",
             f"model change: {old_model} ({runtime}) → {new_model} ({runtime}); "
             "native session preserved",
         )
         return {
             "ok": True,
             "model": new_model,
             "old_model": old_model,
             "runtime": runtime,
             "old_runtime": runtime,
             "runtime_changed": False,
             "native_session_reset": False,
             "history_transfer": {"mode": "native_in_place"},
             "changed": True,
         }
 
     async def _disconnect_backend(self) -> None:
+        if self._output_tails is not None:
+            self._output_tails.stop_all()
         if self._hibernate_task and not self._hibernate_task.done() and self._hibernate_task is not asyncio.current_task():
             self._hibernate_task.cancel()
             self._hibernate_task = None
         backend = self._backend
         if backend:
             await backend.disconnect()
             if self._backend is backend:
                 self._backend = None
         if (self._heartbeat_task and not self._heartbeat_task.done()
                 and self._heartbeat_task is not asyncio.current_task()):
             self._heartbeat_task.cancel()
             try:
                 await self._heartbeat_task
             except asyncio.CancelledError:
                 pass
             except Exception as e:
                 logger.warning(f"[{self.name}] heartbeat task failed on disconnect: {e}")
             self._heartbeat_task = None
         if (self._listen_task and not self._listen_task.done()
                 and self._listen_task is not asyncio.current_task()):
diff --git a/app/static/css/style.css b/app/static/css/style.css
index 0827c4631..ca0af925e 100644
--- a/app/static/css/style.css
+++ b/app/static/css/style.css
@@ -1139,20 +1139,37 @@ select { appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmln
 .job-state { font-size:10px; margin-left:auto; }
 .job-cancel-btn { color:#64748b; padding:0 4px; } .job-cancel-btn:hover { color:#f87171; }
 .job-msg { color:#cbd5e1; cursor:pointer; margin:2px 0; white-space:pre-wrap; word-break:break-word; }
 .job-clamp { display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
 .job-who { color:#64748b; font-size:10px; }
 .job-line { font-size:10px; color:#94a3b8; } .job-next { color:#7dd3fc; } .job-past { color:#a1a1aa; }
 .job-stale { border-radius:4px; padding:0 4px; font-weight:700; }
 .job-stale-1 { background:rgba(245,158,11,.2); color:#fbbf24; }
 .job-stale-2 { background:rgba(248,113,113,.25); color:#fca5a5; }
 .job-detail { margin-top:4px; padding-top:4px; border-top:1px dashed #334155; font-size:10px; color:#94a3b8; }
 .job-full { color:#e2e8f0; white-space:pre-wrap; word-break:break-word; margin-bottom:4px; max-height:220px; overflow-y:auto; }
 .job-k { color:#475569; }
 .job-out { margin:3px 0; padding:3px 6px; background:#0d1117; border-radius:4px; white-space:pre-wrap; word-break:break-all; max-height:80px; overflow-y:auto; color:#cbd5e1; }
 .job-day { padding:6px 6px 0; font-size:10px; font-weight:700; color:#64748b; text-transform:uppercase; }
 .job-now { margin:6px 4px; padding:1px 6px; font-size:10px; font-weight:700; color:#fff; background:#4f46e5; border-radius:4px; }
 .job-ev { display:flex; gap:4px; }
 .job-ev-t { width:46px; flex:none; text-align:right; padding-top:6px; font-size:11px; font-weight:700; color:#cbd5e1; }
 .job-ev-t span { font-weight:400; font-size:9px; color:#64748b; }
 .job-ev.is-future .job-ev-t { color:#7dd3fc; }
 .job-ev-c { flex:1; min-width:0; }
+
+/* V-831: живая активность — вызов, который модель ещё пишет, и инструмент, который ещё идёт. */
+.live-tool-input-card { position: relative; margin: 3px 0; padding: 8px 10px; border: 1px solid rgba(250,204,21,0.18); border-left: 3px solid #facc15; border-radius: 7px; background: linear-gradient(110deg, rgba(66,32,6,0.22), rgba(15,23,42,0.72)); color: #cbd5e1; font-size: 11px; overflow: hidden; }
+.live-tool-input-card::after { content: ''; position: absolute; inset: auto 0 0 0; height: 1px; background: linear-gradient(90deg, transparent, #facc15, transparent); animation: codex-scan 1.6s ease-in-out infinite; }
+.live-tool-input-head { display: flex; align-items: center; gap: 6px; color: #fde68a; font-weight: 500; }
+.live-tool-input-stats { margin-left: auto; color: #94a3b8; font-weight: normal; font-variant-numeric: tabular-nums; }
+.live-tool-input-body { max-height: 260px; margin: 6px 0 0; padding: 6px 8px; overflow: auto; border-radius: 5px; background: #080d14; color: #e2e8f0; font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 10px; line-height: 1.45; white-space: pre-wrap; overflow-wrap: anywhere; }
+.live-dot { width: 7px; height: 7px; border-radius: 50%; background: #facc15; flex: none; animation: live-dot-pulse 1.1s ease-in-out infinite; }
+@keyframes live-dot-pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: .35; transform: scale(.7); } }
+.tool-run-clock { margin-left: 8px; color: #38bdf8; font-size: 10px; font-weight: normal; font-variant-numeric: tabular-nums; animation: sa-clock-pulse 1.6s ease-in-out infinite; }
+.tool-running { position: relative; }
+.tool-running::after { content: ''; position: absolute; inset: auto 0 0 0; height: 1px; background: linear-gradient(90deg, transparent, #38bdf8, transparent); animation: codex-scan 1.6s ease-in-out infinite; }
+.sa-live { margin-top: 2px; color: #fde68a; white-space: pre-wrap; }
+@media (prefers-reduced-motion: reduce) {
+  .live-tool-input-card::after, .tool-running::after { animation: none; }
+  .live-dot, .tool-run-clock { animation: none; }
+}
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 5eb758e47..58b51fce1 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1164,41 +1164,44 @@ function connectSSE(fromHistoryLoad) {
     // Пустая подтверждённая история — валидный snapshot. limit остаётся страховкой от
     // сообщения, вставленного между SELECT snapshot и подключением потока.
     const limitParam = lastId === 0 ? `&limit=${_CHAT_PAGE}` : '';
     _armCallNotifications(lastId);
     const url = `/api/sessions/${selectedAgent}/stream?scope=${encodeURIComponent(currentScope)}&after_id=${lastId}${limitParam}`;
     const source = new EventSource(url);
     eventSource = source;
     source.onmessage = (event) => {
         if (eventSource !== source
             || selectedAgent !== targetAgent
             || currentScope !== targetScope
             || targetGeneration !== _chatLoadGeneration) return;
         try {
             const l = JSON.parse(event.data);
             // Живые куски стрима идут без session_id — их пропускаем, их финал придёт
             // строкой журнала, и вот она уже будет подписана.
             if (l.session_id) {
                 if (_chatSessionId && l.session_id !== _chatSessionId) return _onForeignSession(targetAgent, l.session_id);
                 if (!_chatSessionId) _chatSessionId = l.session_id;
             }
-            if (l.agent_status) _applyLiveAgentStatus(targetAgent, l.agent_status);
+            if (l.agent_status) {
+                _applyLiveAgentStatus(targetAgent, l.agent_status);
+                liveAgentStatus(l.agent_status);
+            }
             else if (Number.isFinite(l.id)) _wakeStatusRefreshFromStream();
             if (l.type === '__session') return;  // рукопожатие: сессию уже сверили выше
             if (l.type === 'user_message' && localMessages.size > 0) {
                 const isLocal = localMessages.has(l.content) ||
                     [...localMessages].some(m => l.content.endsWith(m)) ||
                     [...localMessages].some(m => l.content.includes(m));
                 if (isLocal) {
                     for (const m of localMessages) {
                         if (l.content === m || l.content.endsWith(m) || l.content.includes(m)) {
                             localMessages.delete(m);
                             break;
                         }
                     }
                 } else {
                     addChatEntry(l.type, l.content, l.ts, null, l);
                 }
             } else {
                 addChatEntry(l.type, l.content, l.ts, null, l);
             }
             _maybeNotifyCall(l, targetAgent);
diff --git a/app/static/js/chat.js b/app/static/js/chat.js
index 1592968b1..75e446f27 100644
--- a/app/static/js/chat.js
+++ b/app/static/js/chat.js
@@ -1278,99 +1278,120 @@ function _adoptOrphanResults(chat, toolUseId) {
     for (const node of [...chat.querySelectorAll(selector)]) {
         const saved = node._orphanResult;
         if (!saved) continue;
         // Узел НЕ удаляем: он может быть якорем текущей пачки истории или load-more;
         // удаление роняет вставку следующей строки
         // с NotFoundError. Гасим его и перерисовываем результат ровно на его месте.
         delete node.dataset.orphanResultFor;
         delete node.dataset.unmatchedToolResult;
         node._orphanResult = null;
         node.textContent = '';
         node.style.display = 'none';
         addChatEntry('tool_result', saved.content, saved.ts, node, saved.payload);
     }
 }
 
 const HIDE_THINKING = document.body.dataset.hideThinking === 'true';
 
 // SDK stream events can beat TaskStarted by a few milliseconds. Buffer those
 // lines by parent tool id, then move them into the task-id card once it exists.
 const _pendingSubagentLogs = new Map();
-function appendSubagentLog(subId, evType, content) {
+function appendSubagentLog(subId, evType, content, payload) {
     const chat = $('#chat');
     const host = chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`);
     if (!host) {
         if (!_pendingSubagentLogs.has(subId) && _pendingSubagentLogs.size >= 50) {
             _pendingSubagentLogs.delete(_pendingSubagentLogs.keys().next().value);
         }
         const pending = _pendingSubagentLogs.get(subId) || [];
-        pending.push([evType, content]);
+        pending.push([evType, content, payload]);
         if (pending.length > 100) pending.shift();
         _pendingSubagentLogs.set(subId, pending);
         return;
     }
     const body = host.querySelector('.sa-body');
     if (!body) return;
-    if (evType === 'stream') {
+    if (evType === 'thinking_stream' || evType === 'tool_input_stream') {
+        // One growing line per live block; its persisted event (subagent_event) replaces it.
+        const key = `${evType}:${(payload && payload.item_id) || ''}`;
+        let live = [...body.querySelectorAll('.sa-live')].find(el => el.dataset.liveKey === key);
+        if (!live) {
+            live = document.createElement('div');
+            live.className = 'sa-live';
+            live.dataset.liveKey = key;
+            live.dataset.liveType = evType;
+            live._decoder = evType === 'tool_input_stream' ? new LiveArgsDecoder() : null;
+            live._text = '';
+            body.appendChild(live);
+        }
+        if (live._decoder) live._decoder.feed(content);
+        else live._text += content;
+        const name = (payload && payload.tool_name) || '';
+        const text = live._decoder ? live._decoder.text : live._text;
+        live.textContent = `${live._decoder ? `✍ ${name}` : '💭'} ${text.slice(-600)}`;
+    } else if (evType === 'stream') {
         // Coalesce contiguous stream text into one line (typewriter feel)
         let last = body.lastElementChild;
         if (last && last.classList.contains('sa-stream')) {
             last.textContent += content;
         } else {
             last = document.createElement('div');
             last.className = 'sa-stream';
             last.textContent = content;
             body.appendChild(last);
         }
     } else {
+        const settled = evType === 'tool_use' ? 'tool_input_stream' : evType === 'thinking' ? 'thinking_stream' : '';
+        if (settled) body.querySelectorAll(`.sa-live[data-live-type="${settled}"]`).forEach(el => el.remove());
         const line = document.createElement('div');
         const icon = evType === 'tool_use' ? '🔧' : evType === 'tool_result' ? '↳' : evType === 'thinking' ? '💭' : '';
         line.style.cssText = 'margin-top:2px;color:' + (evType === 'tool_use' ? '#c4b5fd' : '#94a3b8');
         const short = content.length > 300 ? content.slice(0, 300) + '…' : content;
         line.textContent = `${icon} ${short}`;
         body.appendChild(line);
     }
     body.scrollTop = body.scrollHeight;
 }
 
 function _flushPendingSubagentLogs(sourceId, targetId) {
     if (!sourceId || !targetId) return;
     const pending = _pendingSubagentLogs.get(sourceId);
     if (!pending) return;
     _pendingSubagentLogs.delete(sourceId);
-    for (const [evType, content] of pending) {
-        appendSubagentLog(targetId, evType, content);
+    for (const [evType, content, payload] of pending) {
+        appendSubagentLog(targetId, evType, content, payload);
     }
 }
 
 let _codexThinkingLive = null;
 let _codexThinkingKey = '';
 let _codexTurnDiffBubble = null;
 const _pendingCodexToolUpdates = new Map();
 
 function _resetCodexActivityState() {
     _removeCodexThinkingLive();
     _codexTurnDiffBubble = null;
     _pendingCodexToolUpdates.clear();
 }
 
 function resetChatTransientState() {
+    liveResetActivity();
     localMessages.clear();
     pendingUserMsgs = [];
     pendingBubble = null;
     _finalizedBubble = null;
     if (uiDebounceTimer) clearTimeout(uiDebounceTimer);
     uiDebounceTimer = null;
     if (_streamRafId) cancelAnimationFrame(_streamRafId);
     _streamRafId = null;
     streamBubble = null;
     streamContent = '';
     streamPending = '';
     _streamDeferredFinal = null;
     _lastFinalizedStreamText = '';
     _resetCodexActivityState();
 }
 
 function _removeCodexThinkingLive(activity) {
     if (!_codexThinkingLive) return;
     if (activity && _codexThinkingLive.dataset.activity !== activity) return;
     _codexThinkingLive.remove();
@@ -1802,40 +1823,41 @@ function _renderSendChartResult(card, content, ts) {
         const image = document.createElement('img');
         image.src = `/charts/${encodeURIComponent(filename)}`;
         image.alt = 'Chart';
         image.loading = 'lazy';
         image.decoding = 'async';
         image.style.cssText = 'display:block;margin-top:6px;max-width:100%;max-height:360px;border-radius:8px;border:1px solid rgba(99,102,241,0.2);cursor:pointer';
         image.addEventListener('click', () => openImageLightbox(image.src));
         image.addEventListener('error', () => {
             image.remove();
             chartStatus.textContent = T('⚠️ Chart unavailable: file not found — {path}', {path: chartPath});
             chartStatus.style.color = '#fbbf24';
             card.appendChild(chartStatus);
         }, {once: true});
         card.appendChild(image);
     }
     addTimestamp(card, ts);
     return true;
 }
 
 function _updateCompactToolResult(card, content, isBase64Image) {
+    liveStopToolClock(card);
     const resultSpan = card.querySelector('.compact-result');
     if (isBase64Image) {
         if (resultSpan) resultSpan.textContent = T('🖼 image');
         card.dataset.resultContent = '[image]';
         return;
     }
 
     const clean = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
     const rawName = card.dataset.toolRaw || '';
     const isSendChart = rawName === 'mcp__orchestra__send_chart' || rawName === 'send_chart';
     if (isSendChart && _renderSendChartResult(card, content, null)) {
         card.dataset.resultContent = content;
         return;
     }
     const isTask = COMPACT_TASK_TOOLS.has(rawName);
     const isAgentList = COMPACT_AGENT_LIST_TOOLS.has(rawName);
     if (!resultSpan) {
         card.dataset.resultContent = (isTask || isAgentList) ? content : clean;
         return;
     }
@@ -1926,42 +1948,44 @@ function _updateCompactToolResult(card, content, isBase64Image) {
         } catch {}
         resultSpan.textContent = '📖 ' + readShort;
     } else {
         const singleLine = clean.replace(/\n/g, ' ');
         resultSpan.textContent = '📎 ' + (singleLine.length > 40 ? singleLine.slice(0, 40) + '…' : singleLine);
     }
     card.dataset.resultContent = (isTask || isAgentList) ? content : clean;
 }
 
 function _renderCompactToolEntry(type, content, ts, payload, chat, anchor, insertAndFollow, isBase64Image) {
     if (!window.compactMode || (type !== 'tool' && type !== 'tool_result')) return false;
     if (type === 'tool_result') {
         const card = _toolForResult(chat, payload, anchor, true);
         if (card) {
             _updateCompactToolResult(card, content, isBase64Image);
             return true;
         }
     }
 
     const line = buildCompactToolLine(type, content, ts, payload);
+    if (type === 'tool' && line.dataset.toolUseId) liveRemoveToolInput(line.dataset.toolUseId);
     insertAndFollow(line, () => {
         _trimChatNodes(chat);
+        if (type === 'tool' && line.dataset.compactTool) liveStartToolClock(line, line.dataset.toolRaw, content, ts);
         if (type === 'tool') _adoptOrphanResults(chat, line.dataset.toolUseId);
     });
     return true;
 }
 
 function _renderStatusEntry(type, content, ts, anchor, insertAndFollow, payload) {
     if (type !== 'status') return false;
     if (payload?.status_hidden === true) return true;
     if (/^(?:compact started \(context |compact done:|agentic compact )/i.test(content || '')) return true;
     // A status row may beat the authoritative `text` row through async logging.
     // Never finalize streamBubble here or the later text becomes a duplicate answer.
     if (content?.startsWith('precompact timer')) return true;
     if (/^codex hook .+: (?:running|started|completed)(?: · \d+ms)?$/i.test(content || '')) return true;
     if (/^codex mcp .+: (?:starting|ready)$/i.test(content || '')) return true;
     if (/^compact started \(native Codex,/i.test(content || '')) return true;
 
     if (/^grok mcp ready\b/i.test(content || '')) {
         const badge = document.createElement('div');
         badge.className = 'text-center text-xs py-1 text-emerald-400 italic';
         badge.dataset.i18nSkip = '1';  // строка приходит готовой с сервера
@@ -2014,141 +2038,159 @@ function _renderStatusEntry(type, content, ts, anchor, insertAndFollow, payload)
     } else {
         badge.className = 'text-center text-xs py-1 text-slate-500 italic';
         badge.dataset.i18nSkip = '1';  // строка приходит готовой с сервера
         badge.textContent = `⚡ ${content}`;
     }
     addTimestamp(badge, ts);
     insertAndFollow(badge);
     return true;
 }
 
 const SUBAGENT_LIFECYCLE_TYPES = new Set([
     'subagent_start',
     'subagent_end',
     'subagent_progress',
 ]);
 
 // Часы живой фоновой задачи. Единственный владелец интервала — сам узел: таймер
 // снимается и при финише (`_stopSubagentClock`), и при исчезновении узла из DOM, иначе
 // обрезка чата по MAX_CHAT_NODES оставила бы вечно тикающие таймеры на удалённых баблах.
 const _SA_CLOCK_TICK_MS = 1000;
+const _SA_CLOCK_MAX_AGE_MS = 6 * 3600 * 1000;
 
 function _formatSubagentElapsed(seconds) {
     const total = Math.max(0, Math.floor(seconds));
     const mins = Math.floor(total / 60);
     return mins ? `${mins}:${String(total % 60).padStart(2, '0')}` : `${total}s`;
 }
 
 function _startSubagentClock(element, ts) {
     const started = ts ? new Date(ts).getTime() : Date.now();
     const base = Number.isFinite(started) ? started : Date.now();
+    // A start row from a session that died without its end row must not tick forever.
+    if (Date.now() - base > _SA_CLOCK_MAX_AGE_MS) return;
     const clock = document.createElement('span');
     clock.className = 'sa-clock';
     clock.style.cssText = 'margin-left:6px;color:#a78bfa;font-size:10px;font-variant-numeric:tabular-nums';
-    element.appendChild(clock);
+    (element.firstElementChild || element).appendChild(clock);
     const tick = () => {
-        if (!element.isConnected) return _stopSubagentClock(element);
-        clock.textContent = T('⏳ running {elapsed}', {elapsed: _formatSubagentElapsed((Date.now() - base) / 1000)});
+        // The first tick runs before the card is inserted: only a card that WAS in the
+        // DOM and left it (chat trimming) stops its clock. Checking isConnected alone
+        // removed every clock at birth, so background tasks never showed one.
+        if (!element.isConnected) {
+            if (element._saClockSeen) return _stopSubagentClock(element);
+        } else {
+            element._saClockSeen = true;
+        }
+        // A foreground Bash call runs as a task too: its own timeout bounds the task.
+        const callId = element.dataset.saToolUseId;
+        const call = callId ? document.querySelector(`[data-tool-use-id="${CSS.escape(callId)}"]`) : null;
+        const timeoutMs = Number(call?.dataset.toolTimeoutMs || 0);
+        clock.textContent = timeoutMs
+            ? liveRunLabel(Date.now() - base, timeoutMs)
+            : T('⏳ running {elapsed}', {elapsed: _formatSubagentElapsed((Date.now() - base) / 1000)});
     };
     tick();
     element._saClockId = setInterval(tick, _SA_CLOCK_TICK_MS);
 }
 
 function _stopSubagentClock(element) {
     if (element?._saClockId) {
         clearInterval(element._saClockId);
         element._saClockId = null;
     }
     element?.querySelector?.('.sa-clock')?.remove();
 }
 
 function _renderSubagentLifecycleEntry(type, content, ts, payload, chat, insertAndFollow) {
     if (!SUBAGENT_LIFECYCLE_TYPES.has(type)) return false;
     const parts = content.split('|').map(part => part.trim());
     const meta = {};
     const textParts = [];
     for (const part of parts) {
         const separator = part.indexOf('=');
         if (separator > 0 && /^\w+$/.test(part.slice(0, separator))) {
             meta[part.slice(0, separator)] = part.slice(separator + 1);
         } else if (part) {
             textParts.push(part);
         }
     }
     const description = textParts[0] || textParts[1] || '';
     const subagentId = payload?.subagent_id || meta.id || '';
     const isBackground = meta.type === 'local_bash';
     const element = document.createElement('div');
     element.style.cssText = 'font-size:11px;padding:4px 10px;margin:2px 0;border-radius:6px;overflow-wrap:anywhere';
 
     if (type === 'subagent_start') {
         element.style.cssText += ';border-left:3px solid #a78bfa;background:rgba(99,102,241,0.06);color:#c4b5fd';
         if (subagentId) element.dataset.subagentId = subagentId;
+        if (meta.tool_use_id) element.dataset.saToolUseId = meta.tool_use_id;
         element.dataset.subagentKind = isBackground ? 'background' : 'agent';
         const header = document.createElement('div');
         header.style.cssText = 'cursor:pointer;user-select:none';
         const noun = isBackground ? T('Background task') : T('Sub-agent');
         header.innerHTML = `<span class="sa-caret">▶</span> ${isBackground ? '⚙️' : '🤖'} <span style="color:#e2e8f0">${noun}: "${DOMPurify.sanitize(description)}"</span>${meta.type ? ` <span style="color:#64748b;font-size:10px">(${DOMPurify.sanitize(meta.type)})</span>` : ''}`;
         // Между `subagent_start` и `subagent_end` НЕТ ни одного события (замер 28.08:
         // 239 задач, только два события на задачу). Поэтому единственный честный признак
         // жизни — часы, которые идут у клиента. Медиана задачи 3.5 с, но p90 = 34 с и
         // максимум 598 с: без тикающего счётчика долгая задача неотличима от повисшей.
-        _startSubagentClock(element, ts);
         const body = document.createElement('div');
         body.className = 'sa-body';
         body.style.cssText = 'margin-top:4px;padding-left:14px;border-left:1px dashed #4c1d95;display:none;font-size:10px;color:#94a3b8;white-space:pre-wrap;max-height:300px;overflow-y:auto';
         let expanded = false;
         header.addEventListener('click', () => {
             expanded = !expanded;
             body.style.display = expanded ? 'block' : 'none';
             header.querySelector('.sa-caret').textContent = expanded ? '▼' : '▶';
         });
         element.append(header, body);
+        _startSubagentClock(element, ts);
     } else if (type === 'subagent_progress') {
         const tokenCount = parseInt(meta.tokens || '0');
         const tokens = meta.tokens ? (tokenCount >= 1000 ? (tokenCount / 1000).toFixed(1) + 'k' : meta.tokens) : '';
         const line = `⏳ ${meta.tool ? T('using {tool}', {tool: meta.tool}) : T('working')}`
             + (tokens ? ` | ${T('{n} tokens', {n: tokens})}` : '');
         const host = subagentId ? chat.querySelector(`[data-subagent-id="${CSS.escape(subagentId)}"]`) : null;
         if (host) {
             let progress = host.querySelector('.sa-progress');
             if (!progress) {
                 progress = document.createElement('div');
                 progress.className = 'sa-progress';
                 progress.style.cssText = 'font-size:10px;color:#64748b;padding-left:14px;margin-top:2px';
                 host.appendChild(progress);
             }
             progress.textContent = line;
             return true;
         }
         element.style.cssText += ';color:#64748b';
         element.textContent = `⏳ ${isBackground ? T('Background task') : T('Sub-agent')} "${description}" — ${line}`;
     } else {
         const succeeded = !meta.status || ['completed', 'shutdown'].includes(meta.status);
         const host = subagentId ? chat.querySelector(`[data-subagent-id="${CSS.escape(subagentId)}"]`) : null;
         const summary = textParts.slice(1).join(' | ').trim();
         if (host) {
             const header = host.querySelector('div');
             const noun = host.dataset.subagentKind === 'background' ? T('Background task') : T('Sub-agent');
             if (header) header.innerHTML = `<span class="sa-caret">▶</span> ${succeeded ? '✅' : '❌'} <span style="color:#e2e8f0">${noun} ${succeeded ? T('done') : T('failed')}: "${DOMPurify.sanitize(description)}"</span>`;
             host.querySelector('.sa-progress')?.remove();
             _stopSubagentClock(host);
+            host.dataset.subagentDone = '1';
             if (summary) {
                 const summaryElement = document.createElement('div');
                 summaryElement.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:14px;white-space:pre-wrap';
                 summaryElement.textContent = summary;
                 host.appendChild(summaryElement);
             }
             host.style.borderLeftColor = succeeded ? '#22c55e' : '#ef4444';
             return true;
         }
         element.style.cssText += `;border-left:3px solid ${succeeded ? '#22c55e' : '#ef4444'};background:rgba(${succeeded ? '34,197,94' : '239,68,68'},0.06);color:${succeeded ? '#86efac' : '#fca5a5'}`;
         const noun = isBackground ? 'Background task' : 'Sub-agent';
         element.innerHTML = `${succeeded ? '✅' : '❌'} <span style="color:#e2e8f0">${noun} ${succeeded ? 'completed' : 'failed'}${description ? ': "'+DOMPurify.sanitize(description)+'"' : ''}</span>`;
         if (summary) {
             const summaryElement = document.createElement('div');
             summaryElement.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:20px;white-space:pre-wrap';
             summaryElement.textContent = summary.length > 300 ? summary.slice(0, 300) + '…' : summary;
             element.appendChild(summaryElement);
         }
     }
 
@@ -3184,40 +3226,41 @@ function _renderFullToolCall(content, payload, div) {
         _flushCodexToolUpdates(div, codexItemId);
     }
 }
 
 function _renderFullToolResult(content, ts, payload, anchor, div, _insertAndFollow, isBase64Image) {
     const chat = $('#chat');
     const resultToolId = payload?.tool_use_id || '';
     const lastTool = _toolForResult(chat, payload, anchor, false);
     if (!lastTool) {
         div.dataset.unmatchedToolResult = '1';
         if (resultToolId) {
             div.dataset.orphanResultFor = resultToolId;
             div._orphanResult = {content, ts, payload};
         }
         const warning = document.createElement('div');
         warning.className = 'text-amber-400 text-xs font-medium mb-1';
         warning.textContent = T('⚠️ Result without call{toolId}', {toolId: resultToolId ? ` · ${resultToolId}` : ''});
         div.appendChild(warning);
     }
     if (lastTool) {
+        liveStopToolClock(lastTool);
         const liveOutput = lastTool.querySelector('.codex-live-output');
         if (liveOutput) liveOutput.remove();
         completeCodexToolCard(lastTool);
         if (lastTool.dataset.isFileChange) {
             let data = {};
             try { data = JSON.parse(content); } catch {}
             const header = lastTool.querySelector('.flex.items-center');
             const ok = !data.status || data.status === 'completed';
             if (header) {
                 header.textContent = `${ok ? '✅' : '❌'} ${ok ? T('File changes applied') : T('File changes failed')}`
                     + (data.files != null ? ` · ${T('{n} files', {n: data.files})}` : '');
                 header.style.color = ok ? '#4ade80' : '#f87171';
             }
             delete lastTool.dataset.lastTool;
             addTimestamp(lastTool, ts);
             return;
         }
         if (lastTool.dataset.toolRawName === 'ImageGeneration') {
             let data = {};
             try { data = JSON.parse(content); } catch {}
@@ -4488,100 +4531,116 @@ function _renderCompactEvent(type, content, ts, anchor, insertAndFollow, payload
 function addChatEntry(type, content, ts, anchor, payload) {
     if (type === 'provider_limit') return; // Runtime telemetry; the status/error row carries the user notice.
     if (type === 'done_gate_verdict') return; // V-614 (removed 30.09): old rows stay in logs, never render them.
     if (type === 'error' && /^compact attempt \d+\/\d+ failed:/.test(content || '')) return;
     if (_isSilentTurnMarker(type, content)) {
         // The marker already streamed into a live bubble; without this it stays with a cursor.
         if (streamBubble) {
             _streamFlush();
             streamBubble.remove();
             streamBubble = null;
             streamContent = '';
             streamPending = '';
             _streamDeferredFinal = null;
             if (typeof _recomputeChatTimelineFinals === 'function') _recomputeChatTimelineFinals();
         }
         return;
     }
     if (HIDE_THINKING && (type === 'thinking' || type === 'thinking_stream')) return;
     // Live sub-agent output → nest inside the sub-agent accordion, not the main flow
     if ((type === 'subagent_stream' || type === 'subagent_event') && payload && payload.subagent_id) {
-        appendSubagentLog(payload.subagent_id, payload.event_type || 'stream', content);
+        appendSubagentLog(payload.subagent_id, payload.event_type || 'stream', content, payload);
         return;
     }
     if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
     const chat = $('#chat');
     let _insertedBeforeStream = false;
     const _insert = (el) => {
         _tagChatTimelineNode(el, type, ts);
         _stampChatLogNode(el, payload);
         if (payload && payload.trunc && type !== 'compact_event') _attachTruncNotice(el, payload, type, ts);
         if (anchor) return chat.insertBefore(el, anchor);
         const wasAtBottom = _chatAtBottom(chat);
         let inserted;
         if (streamBubble && streamBubble.parentNode === chat) {
             _insertedBeforeStream = true;
             inserted = chat.insertBefore(el, streamBubble);
         } else {
             inserted = chat.appendChild(el);
         }
         if (!scrollAfterLoad && !wasAtBottom) _markChatHasNewBelow();
         return inserted;
     };
     const _insertAndFollow = (el, afterInsert) => {
         const wasAtBottom = _chatAtBottom(chat);
         const inserted = _insert(el);
         if (afterInsert) afterInsert(inserted);
         if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return inserted;
     };
 
     if (_renderCompactEvent(type, content, ts, anchor, _insertAndFollow, payload, chat)) return;
 
     // Heuristic: detect base64 image payloads from tool results (e.g. screenshot tools)
     const _isBase64Image = content.includes("'type': 'image'") || content.includes('"type": "image"') || content.includes('"type":"image"') || /['"]?data['"]?\s*[:=]\s*['"][A-Za-z0-9+/=\s]{500,}['"]/.test(content);
 
+    if (type === 'tool_input_stream') {
+        removeWaitingIndicator();
+        liveRenderToolInput(payload || {}, content, _insert);
+        return;
+    }
+
+    if (type === 'tool_stream' && payload && payload.subagent_id) {
+        liveRouteTaskOutput(payload, content);
+        return;
+    }
+
     if (type === 'thinking_stream') {
         const activity = (payload && payload.activity) || 'reasoning';
         const key = `${activity}:${(payload && payload.item_id) || ''}`;
         if (!_codexThinkingLive || _codexThinkingKey !== key) {
             _removeCodexThinkingLive();
             _codexThinkingLive = document.createElement('div');
             _codexThinkingLive.className = 'codex-activity-card codex-thinking-live';
             _codexThinkingLive.dataset.activity = activity;
             const label = document.createElement('div');
             label.className = 'codex-live-label';
             label.textContent = activity === 'plan'
                 ? T('▦ Planning live')
                 : activity === 'waiting'
                     ? T('⌁ Codex still working')
                     : T('◇ Reasoning live');
             const body = document.createElement('div');
             body.className = 'codex-live-thinking-body';
             _codexThinkingLive.append(label, body);
             _codexThinkingKey = key;
             _insert(_codexThinkingLive);
         }
         const body = _codexThinkingLive.querySelector('.codex-live-thinking-body');
-        body.textContent = activity === 'waiting'
+        body.textContent = activity === 'waiting' || (payload && payload.replace)
             ? content
             : (body.textContent + content).slice(-30_000);
+        // Claude with thinking display omitted streams only a token estimate.
+        if (payload && payload.estimated_tokens) {
+            _codexThinkingLive.querySelector('.codex-live-label').textContent =
+                T('◇ Reasoning live · ~{n} tokens', {n: Number(payload.estimated_tokens).toLocaleString()});
+        }
         return;
     }
 
     if (type === 'tool_stream' || type === 'tool_patch') {
         _queueOrApplyCodexToolUpdate(chat, type, content, payload, anchor);
         return;
     }
 
     if (type === 'turn_diff') {
         const patch = renderCodexFileChange({
             changes: [{path: T('Current turn'), kind: 'update', diff: content}],
         });
         if (!_codexTurnDiffBubble) {
             _codexTurnDiffBubble = document.createElement('div');
             _codexTurnDiffBubble.className = 'codex-activity-card codex-turn-diff';
             const title = document.createElement('div');
             title.className = 'codex-live-label';
             title.textContent = T('± Live turn diff');
             _codexTurnDiffBubble.appendChild(title);
             _insert(_codexTurnDiffBubble);
@@ -4619,40 +4678,41 @@ function addChatEntry(type, content, ts, anchor, payload) {
         if (_rateLimitAgent) _hideRateLimitBanner();  // agent resumed → rate limit cleared
         if (!streamBubble) {
             streamBubble = document.createElement('div');
             streamBubble.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot markdown-body streaming';
             streamBubble.style.position = 'relative';
             const agentColor = agentColors[selectedAgent];
             if (agentColor) streamBubble.style.borderLeft = `3px solid ${agentColor}`;
             _insert(streamBubble);
             if (typeof _recomputeChatTimelineFinals === 'function') _recomputeChatTimelineFinals();
             if (typeof _syncChatTimelineControls === 'function') _syncChatTimelineControls();
             _streamLastParse = 0;
         }
         streamPending += content;
         if (!_streamRafId) _streamRafId = requestAnimationFrame(_streamRenderTick);
         return;
     }
 
     // 'text' event signals streaming finished — flush typewriter buffer,
     // replace with authoritative DB content, finalize with copy/timestamp.
     if (type === 'text') {
+        _removeCodexThinkingLive('reasoning');


## Later history of the touched files on main (after this commit)

56 later commits touch these paths; the first 40 (oldest first):
97b80e290 2026-10-13 V-831: откатить случайно влитую миграцию каталога V-621 (projects.yaml)
e13658c20 2026-10-13 V-833: #V-833: guard catalog migration against worktrees
35ea16735 2026-10-13 V-832: Parallelize video voice synthesis and HTML rendering
83a921481 2026-10-13 V-834: add chat-ready export guidance
d0e5f8d9a 2026-10-13 V-835: Add quick video previews and early timing checks
ed2669873 2026-10-14 V-837: #V-837: clean retired managed skill copies
cebb03d02 2026-10-14 V-839: #V-839: accept scoped file delivery keys
4bd9c2eaf 2026-10-14 V-821: #V-821: sparse worker worktrees for all projects: manifest rule, task-switch retarget, merge refusal with fix, converter, prompt, tests
4a73b690f 2026-10-14 V-843: #V-843: reopen task run after binding release
f7433c822 2026-10-14 V-842: compact chat upload chips
8dd5befc3 2026-10-14 V-845: #V-843: preserve same-task switch no-op contract
d5e33acfd 2026-10-14 V-841: #V-841: bound worker log snapshots on server
9c0289b99 2026-10-14 V-849: Preserve subtitle symbols and normalize Vosk punctuation
57156329d 2026-10-14 V-848: #V-848: profile merge phases and reject busy workers
25403c018 2026-10-14 V-850: #V-848: restore bounded identity-safe merge wait
b52b2aa01 2026-10-14 V-851: #V-851: перенос V-831: live tool streaming
57f85fcd1 2026-10-14 V-846: #V-846: enforce shell wait and search policy
69a88105c 2026-10-14 V-853: #V-846: keep recursive search usable without rg
aa7a76100 2026-10-14 V-847: #V-847: parallelize full pytest and isolate fixtures
8a4f93f98 2026-10-14 V-852: add pinned local TeraTTSv2 voice
543b17722 2026-10-14 V-854: #V-854: resync LivePacer in stream tick so pending text always drains; fix browser test harness
1383b04ce 2026-10-14 V-855: #V-855: cover pytest config isolation for foreign worktrees
642990877 2026-10-14 V-856: #V-856: distinguish interruptions and stale listeners
76489fd9c 2026-10-15 V-859: #V-859: keep quota usage lines monotone within reset windows
eeaf5b2e7 2026-10-15 V-861: #V-861: cover changed-test mutation gate outcomes
0cdc5d563 2026-10-15 V-862: #V-862: persist quota gate expiry override
94c38aba7 2026-10-15 V-866: #V-866: clarify quota timing in delivery receipts
9f8f89ba4 2026-10-15 V-867: calibrate orchestrator numerical claims
66121be42 2026-10-15 V-858: implement dashboard info panel and task approvals
5a6de6094 2026-10-15 V-869: rebuild Tailwind styles for info panel
9dd2c1856 2026-10-15 V-860: #V-860: preserve dashboard voice recordings and return transcripts to draft
59cf84d21 2026-10-15 V-863: #V-863: restore unread dots on orchestrator tabs
e1b2ee6bb 2026-10-15 V-870: #V-870: reproduce duration failure on Chromium chunked WebM
f8bdbeee3 2026-10-15 V-871: show full proposal details and deliver owner decisions
f04e662d5 2026-10-15 V-872: #V-872: union append-only gitignore merge conflicts
b45042823 2026-10-15 V-873: remove proposal cards and child work summary
f0ebe7a7c 2026-10-15 V-879: refresh public project guides
fd255ed68 2026-10-15 V-874: send voice transcriptions automatically
edfac4356 2026-10-15 V-876: WIP #V-876: design tokens, theme.js, model/status badges from one source
a20c1e2c6 2026-10-15 V-878: Tera stress beside markers, timed pauses, silent steps, rate 1.0, Manim 3B1B defaults

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 97b80e290 V-831: откатить случайно влитую миграцию каталога V-621 (projects.yaml)

diff --git a/.orchestra/projects-pre-v621-20261013T121451Z.yaml b/.orchestra/projects-pre-v621-20261013T121451Z.yaml
deleted file mode 100644
index c3316456f..000000000
--- a/.orchestra/projects-pre-v621-20261013T121451Z.yaml
+++ /dev/null
@@ -1,63 +0,0 @@
-version: 1
-include_scopes:
-- /home/kesha/katya-work
-- /home/kesha/openrouter-lab
-- /home/kesha/projects/University
-- /home/kesha/projects/VPN-Service
-- /home/kesha/projects/comfy-image-pipeline
-- /home/kesha/projects/dnd-game-master
-- /home/kesha/projects/kesha-tg-bot
-- /home/kesha/projects/seedon
-- /opt/cog-second-brain
-projects:
-- tag: orchestra
-  name: Orchestra
-  scope: /home/kesha/orchestra
-  write_namespace: home-kesha-orchestra-8b68cd9600cc
-  namespaces:
-    home-kesha-orchestra-8b68cd9600cc: ''
-    orchestra: ноутбук
-    vps-orchestra: старый VPS
-    orchestra-15ebb64920a9: ноутбук
-    mnt-data-projects-python-orchestra-13dc8d0cd9fb: ноутбук
-- tag: polus
-  name: Полюс
-  namespaces:
-    polus: ноутбук
-- tag: sensar
-  name: Sensar
-  namespaces:
-    sensar-5e197e867bb2: ноутбук
-- tag: parsing-hub
-  name: Parsing Hub
-  namespaces:
-    parsing-hub: ноутбук
-- tag: stargate-tactics
-  name: Stargate Tactics
-  namespaces:
-    stargate-tactics: ноутбук
-- tag: family-tree
-  name: Семейное древо
-  archived: true
-  namespaces:
-    family-tree: ноутбук
-- tag: inscryption-ai
-  name: Inscryption AI
-  archived: true
-  namespaces:
-    inscryption-ai: ноутбук
-- tag: tradingcryptobot
-  name: Trading Crypto Bot
-  archived: true
-  namespaces:
-    tradingcryptobot: ноутбук
-- tag: webview
-  name: WebView
-  archived: true
-  namespaces:
-    webview-c212de852078: ноутбук
-- tag: zahoron-mobile
-  name: Захорон (мобильный)
-  archived: true
-  namespaces:
-    zahoron-mobile: ноутбук
diff --git a/.orchestra/projects.yaml b/.orchestra/projects.yaml
index dc4e227f2..c3316456f 100644
--- a/.orchestra/projects.yaml
+++ b/.orchestra/projects.yaml
@@ -1,18 +1,27 @@
 version: 1
 include_scopes:
 - /home/kesha/katya-work
 - /home/kesha/openrouter-lab
-- /home/kesha/orchestra
 - /home/kesha/projects/University
 - /home/kesha/projects/VPN-Service
 - /home/kesha/projects/comfy-image-pipeline
 - /home/kesha/projects/dnd-game-master
 - /home/kesha/projects/kesha-tg-bot
 - /home/kesha/projects/seedon
 - /opt/cog-second-brain
 projects:
+- tag: orchestra
+  name: Orchestra
+  scope: /home/kesha/orchestra
+  write_namespace: home-kesha-orchestra-8b68cd9600cc
+  namespaces:
+    home-kesha-orchestra-8b68cd9600cc: ''
+    orchestra: ноутбук
+    vps-orchestra: старый VPS
+    orchestra-15ebb64920a9: ноутбук
+    mnt-data-projects-python-orchestra-13dc8d0cd9fb: ноутбук
 - tag: polus
   name: Полюс
   namespaces:
     polus: ноутбук
 - tag: sensar
### e13658c20 V-833: #V-833: guard catalog migration against worktrees

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 8e1a9b2af..b305f142a 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -13,10 +13,11 @@
 
 ### Changed
 - **Consolidate visual skills and version the deployment workflow** (`.orchestra/pipelines/default/prompts/skills/`, `pipeline.yaml`, `app/prompting.py`, `app/session.py`, `scripts/video_artifact/`; V-819). Animation/playback guidance is part of the single visual-artifact skill, with its full player scaffold delivered as an on-demand reference so the entrypoint stays within the existing 16 KiB budget. The narrated-video skill and its internal script directory use one name, and the obsolete review skill is removed. The pipeline distributes the deployment skill only to orchestrator roles. On refresh, an untracked stale copy is removed only when its bytes match a historical canonical skill revision; tracked or locally edited copies remain untouched. Trigger: the owner requested one visual skill, removal of the frozen review skill, and an up-to-date owner-authorized deploy workflow.
 
 ### Added
+- **Protect V-621 catalog migration from worktrees and self-includes** (`app/catalog_migration_v621.py`, `app/project_catalog.py`; V-833). Startup migration now writes only the canonical catalog in the primary checkout and skips when a foreign scope resolves to that same file or Git repository. Catalog loading rejects an `include_scopes` entry that resolves back to its own file with a direct diagnostic. Trigger: a demo server started in a worker worktree rewrote and committed the main catalog into its worker branch, and the resulting self-include duplicated catalog tags after merge.
 - **Hidden orchestrator menu shows live status and cache expiry** (`app/static/js/app.js`; V-820). Hidden rows use the same orchestrator status painter and cache pill as pinned tabs, and an open menu refreshes with orchestrator polling and live status updates. Waiting uses 📆 consistently with the Telegram status vocabulary. Trigger: the 👁 menu listed hidden orchestrators by name only, so it hid working/waiting and cache state.
 - **Quota-held first tasks follow the worker's current model and can be cancelled by delivery ID** (`app/initial_deliveries.py`, `app/routes/sessions.py`; V-810). A retry rechecks the current model's quota preflight and atomically queues/wakes the existing task when the gate is open; successful model changes run an immediate queue sweep, while the periodic sweep rechecks after a concurrent model switch. `cancel_message_delivery` now also cancels an initial task in `WAITING_QUOTA` or `QUEUED`; it refuses once the runner reaches `PREPARING` and verifies the original sender. Trigger: after an Opus worker changed to Luna, its first task still appeared Claude-blocked and the advertised cancel tool returned 404.
 - **Worker spawn validates `delivery_id` before creating or binding a session** (`app/mcp_stdio.py`, `app/routes/sessions.py`; V-808). MCP `spawn_worker` rejects a non-empty malformed ID as `invalid_argument`, and HTTP `/api/sessions` rejects it during request validation; empty IDs keep their existing behavior. Trigger: a non-UUID delivery ID created and task-bound a worker before initial delivery failed with a UUID parsing error.
 - **Telegram topics show waiting with a third icon and preserve their titles** (`app/tg_bridge.py`, `app/mailbox.py`, `app/quota_queue.py`, `app/workflow_scheduler.py`; V-804/V-805). A stable wait from a queued owner/dashboard message, an in-memory message queue, a quota-held delivery, a workflow waiting for a shared slot, or a session waiting on background work uses the available calendar icon 📆; active work keeps ⚡ ahead of waiting, and idle without pending work uses ☕. The icon reverts when waiting ends; the topic name never changes. Topic state changes coalesce per topic and share the group rate limiter. Trigger: the dashboard exposed waiting while Telegram topics showed only running/idle; the owner requested the wait state as a topic icon instead of a title prefix.
 - **Shared dynamic workflow admission and cgroup isolation** (`app/workflow_scheduler.py`, `app/agent_cgroups.py`, `app/routes/bg.py`, `scripts/wf_run.py`; V-782). Workflow model calls acquire durable SQLite leases through Orchestra; admission is shared and fair across runs, and the limit follows CPU capacity, delegated-slice memory headroom, measured per-call memory samples, and PSI pressure. Queued calls do not consume call budget or dispatch accounting. At startup, leftover processes in the delegated service root move into `orchestra-api` before CPU, IO, and memory controllers are enabled; dynamic workflow runners and provider CLIs then enter `agents`, with weights below the API sibling and memory limits derived from the service limits. The workflow card and manifest expose waiting position, active/queued slots, and the limit reason. Trigger: concurrent workflow fan-outs and test/model processes exhausted the Orchestra service cgroup and stalled the API on 2026-10-08.
### 35ea16735 V-832: Parallelize video voice synthesis and HTML rendering

diff --git a/CHANGELOG.md b/CHANGELOG.md
index b305f142a..0eb36a83f 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,10 +6,11 @@
 
 ## Unreleased
 
 ### Added
 - **Live generation and running-tool activity in the dashboard chat** (`app/backend_claude.py`, `app/session.py`, `app/live_broker.py`, `app/task_output_tail.py`, `app/routes/sessions.py`, `app/static/js/live-activity.js`, `app/static/js/chat.js`; V-831). Claude partial messages are no longer filtered to `text_delta`: `input_json_delta` becomes `tool_input_stream` (tool id/name from `content_block_start`, keyed by parent and block index so sub-agents do not collide) and `thinking_delta` becomes `thinking_stream`, including the `estimated_tokens` counter the CLI sends when thinking text is omitted. The chat shows a card for the call being written — tool name, decoded argument text, character count, chars/s and elapsed time — replaced by the normal card when the persisted `tool` row lands. Every unanswered tool call shows a pulsing "running m:ss of m:ss" clock (Bash `timeout`, default 2:00, cap 10:00; elapsed only for tools without a timeout), and shell tasks (`local_bash`, foreground or background) show live output tailed from the CLI's `tasks/<task_id>.output` file. The SSE loop merges adjacent deltas of one block per ~100 ms tick, the broker keeps a capped tail of each open block so a reopened chat resumes it, and nothing partial is written to `logs`. Codex app-server 0.160.0 has no tool-argument delta notification, so Codex keeps its existing reasoning/output streams. Trigger: a 42 KB Bash heredoc took minutes to write with nothing visible, and running commands looked dead.
+- **Parallel voice synthesis and incremental HTML rendering** (`scripts/video_artifact/make.py`, `tts_worker.py`, `tts_worker_en.py`; V-832). Each speech environment loads its model once and synthesizes up to four phrases concurrently; ordered cache results preserve the step timeline, while HTML frame segments start when their phrase and all preceding phrases are ready. Manim still waits for the complete timing plan before `construct()`. Trigger: cold video builds spent 66–77 s loading Vosk and then synthesized phrases serially before starting any HTML frames.
 - **CI and local agent-documentation integrity check** (`scripts/check_instruction_contract.py`, `.github/workflows/ci.yml`; V-826). The instruction contract command reuses `app.kb_index` to check KB topic/index coverage and resolves relative Markdown and backtick file references in `AGENTS.md` and `.orchestra/kb/*.md`; CI runs it once in the test shards. Trigger: KB topics can be invisible to agents when absent from its index, and stale paths misdirect readers.
 - **Optional event-synced sound layer for video-artifact** (`scripts/video_artifact/make.py`, `scripts/video_artifact/sound/`; V-824). HTML and Manim steps can declare timed `events`; `make.py` maps them from the voice-derived step plan into a cue sheet, mixes selected CC0 effects, looped music and the existing voice with ducking, then muxes and runs picture/audio QA. The CC0 kit defaults to `~/.local/share/orchestra-sfx/`; scenes without events retain the voice-only path. Trigger: the video builder had no sound beyond speech, and sparse effects alone produced an unusable loudness target and silence failures.
 
 ### Changed
 - **Consolidate visual skills and version the deployment workflow** (`.orchestra/pipelines/default/prompts/skills/`, `pipeline.yaml`, `app/prompting.py`, `app/session.py`, `scripts/video_artifact/`; V-819). Animation/playback guidance is part of the single visual-artifact skill, with its full player scaffold delivered as an on-demand reference so the entrypoint stays within the existing 16 KiB budget. The narrated-video skill and its internal script directory use one name, and the obsolete review skill is removed. The pipeline distributes the deployment skill only to orchestrator roles. On refresh, an untracked stale copy is removed only when its bytes match a historical canonical skill revision; tracked or locally edited copies remain untouched. Trigger: the owner requested one visual skill, removal of the frozen review skill, and an up-to-date owner-authorized deploy workflow.
### 83a921481 V-834: add chat-ready export guidance

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 0eb36a83f..4b9ab0369 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -5,10 +5,11 @@
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
 ### Added
+- **Chat-ready export for interactive HTML artifacts** (`.orchestra/pipelines/default/prompts/skills/html-artifacts.md`; V-834). User-entered values are copied with field labels using one prominent button, with a selected-textarea fallback when clipboard access is unavailable; export is client-side without server storage, localStorage synchronization, or external requests. Trigger: the owner rejected public links and server storage as unsafe.
 - **Live generation and running-tool activity in the dashboard chat** (`app/backend_claude.py`, `app/session.py`, `app/live_broker.py`, `app/task_output_tail.py`, `app/routes/sessions.py`, `app/static/js/live-activity.js`, `app/static/js/chat.js`; V-831). Claude partial messages are no longer filtered to `text_delta`: `input_json_delta` becomes `tool_input_stream` (tool id/name from `content_block_start`, keyed by parent and block index so sub-agents do not collide) and `thinking_delta` becomes `thinking_stream`, including the `estimated_tokens` counter the CLI sends when thinking text is omitted. The chat shows a card for the call being written — tool name, decoded argument text, character count, chars/s and elapsed time — replaced by the normal card when the persisted `tool` row lands. Every unanswered tool call shows a pulsing "running m:ss of m:ss" clock (Bash `timeout`, default 2:00, cap 10:00; elapsed only for tools without a timeout), and shell tasks (`local_bash`, foreground or background) show live output tailed from the CLI's `tasks/<task_id>.output` file. The SSE loop merges adjacent deltas of one block per ~100 ms tick, the broker keeps a capped tail of each open block so a reopened chat resumes it, and nothing partial is written to `logs`. Codex app-server 0.160.0 has no tool-argument delta notification, so Codex keeps its existing reasoning/output streams. Trigger: a 42 KB Bash heredoc took minutes to write with nothing visible, and running commands looked dead.
 - **Parallel voice synthesis and incremental HTML rendering** (`scripts/video_artifact/make.py`, `tts_worker.py`, `tts_worker_en.py`; V-832). Each speech environment loads its model once and synthesizes up to four phrases concurrently; ordered cache results preserve the step timeline, while HTML frame segments start when their phrase and all preceding phrases are ready. Manim still waits for the complete timing plan before `construct()`. Trigger: cold video builds spent 66–77 s loading Vosk and then synthesized phrases serially before starting any HTML frames.
 - **CI and local agent-documentation integrity check** (`scripts/check_instruction_contract.py`, `.github/workflows/ci.yml`; V-826). The instruction contract command reuses `app.kb_index` to check KB topic/index coverage and resolves relative Markdown and backtick file references in `AGENTS.md` and `.orchestra/kb/*.md`; CI runs it once in the test shards. Trigger: KB topics can be invisible to agents when absent from its index, and stale paths misdirect readers.
 - **Optional event-synced sound layer for video-artifact** (`scripts/video_artifact/make.py`, `scripts/video_artifact/sound/`; V-824). HTML and Manim steps can declare timed `events`; `make.py` maps them from the voice-derived step plan into a cue sheet, mixes selected CC0 effects, looped music and the existing voice with ducking, then muxes and runs picture/audio QA. The CC0 kit defaults to `~/.local/share/orchestra-sfx/`; scenes without events retain the voice-only path. Trigger: the video builder had no sound beyond speech, and sparse effects alone produced an unusable loudness target and silence failures.
 
### d0e5f8d9a V-835: Add quick video previews and early timing checks

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 4b9ab0369..648edb9ed 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -5,10 +5,11 @@
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
 ### Added
+- **Fast video drafts, static Manim timing checks, build queue, and progress estimates** (`scripts/video_artifact/make.py`, `manim_timing.py`, `manim_voice.py`; V-835). Scenes can render selected stop frames before TTS, and supported Manim `self.left()` timings are analyzed before any frame render; unsupported Python falls back to Manim `--dry_run`. A host-wide `flock` queues builds, speech/frame/step progress includes ETA, and Deepgram matching normalizes common spoken numbers to digits while reporting omitted numerals separately from strict ordinary-word recall. Trigger: the 39-step University Manim draft/contact sheet appeared only after a 237 s full still render, and dry-run timing validation took 198 s.
 - **Chat-ready export for interactive HTML artifacts** (`.orchestra/pipelines/default/prompts/skills/html-artifacts.md`; V-834). User-entered values are copied with field labels using one prominent button, with a selected-textarea fallback when clipboard access is unavailable; export is client-side without server storage, localStorage synchronization, or external requests. Trigger: the owner rejected public links and server storage as unsafe.
 - **Live generation and running-tool activity in the dashboard chat** (`app/backend_claude.py`, `app/session.py`, `app/live_broker.py`, `app/task_output_tail.py`, `app/routes/sessions.py`, `app/static/js/live-activity.js`, `app/static/js/chat.js`; V-831). Claude partial messages are no longer filtered to `text_delta`: `input_json_delta` becomes `tool_input_stream` (tool id/name from `content_block_start`, keyed by parent and block index so sub-agents do not collide) and `thinking_delta` becomes `thinking_stream`, including the `estimated_tokens` counter the CLI sends when thinking text is omitted. The chat shows a card for the call being written — tool name, decoded argument text, character count, chars/s and elapsed time — replaced by the normal card when the persisted `tool` row lands. Every unanswered tool call shows a pulsing "running m:ss of m:ss" clock (Bash `timeout`, default 2:00, cap 10:00; elapsed only for tools without a timeout), and shell tasks (`local_bash`, foreground or background) show live output tailed from the CLI's `tasks/<task_id>.output` file. The SSE loop merges adjacent deltas of one block per ~100 ms tick, the broker keeps a capped tail of each open block so a reopened chat resumes it, and nothing partial is written to `logs`. Codex app-server 0.160.0 has no tool-argument delta notification, so Codex keeps its existing reasoning/output streams. Trigger: a 42 KB Bash heredoc took minutes to write with nothing visible, and running commands looked dead.
 - **Parallel voice synthesis and incremental HTML rendering** (`scripts/video_artifact/make.py`, `tts_worker.py`, `tts_worker_en.py`; V-832). Each speech environment loads its model once and synthesizes up to four phrases concurrently; ordered cache results preserve the step timeline, while HTML frame segments start when their phrase and all preceding phrases are ready. Manim still waits for the complete timing plan before `construct()`. Trigger: cold video builds spent 66–77 s loading Vosk and then synthesized phrases serially before starting any HTML frames.
 - **CI and local agent-documentation integrity check** (`scripts/check_instruction_contract.py`, `.github/workflows/ci.yml`; V-826). The instruction contract command reuses `app.kb_index` to check KB topic/index coverage and resolves relative Markdown and backtick file references in `AGENTS.md` and `.orchestra/kb/*.md`; CI runs it once in the test shards. Trigger: KB topics can be invisible to agents when absent from its index, and stale paths misdirect readers.
 - **Optional event-synced sound layer for video-artifact** (`scripts/video_artifact/make.py`, `scripts/video_artifact/sound/`; V-824). HTML and Manim steps can declare timed `events`; `make.py` maps them from the voice-derived step plan into a cue sheet, mixes selected CC0 effects, looped music and the existing voice with ducking, then muxes and runs picture/audio QA. The CC0 kit defaults to `~/.local/share/orchestra-sfx/`; scenes without events retain the voice-only path. Trigger: the video builder had no sound beyond speech, and sparse effects alone produced an unusable loudness target and silence failures.
### ed2669873 V-837: #V-837: clean retired managed skill copies

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 648edb9ed..fdfcb64c7 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -5,10 +5,11 @@
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
 ### Added
+- **Retire historical managed skill copies across directory moves** (`app/prompting.py`; V-837). Skill cleanup follows Git renames when collecting approved historical hashes, so exact copies from the pre-`.orchestra` `pipelines/default/prompts/skills/` path are recognized. Refresh also removes orphaned temp files only when they match the injector's `.SKILL.md.<pid>.<8-hex>.tmp` naming pattern under a retired skill; tracked paths, symlinks, changed content, and unrelated temp files remain untouched. Trigger: V-819 removed `codex-debate` and renamed `explainer-video`, but copies from the old canonical path and an interrupted atomic write remained.
 - **Fast video drafts, static Manim timing checks, build queue, and progress estimates** (`scripts/video_artifact/make.py`, `manim_timing.py`, `manim_voice.py`; V-835). Scenes can render selected stop frames before TTS, and supported Manim `self.left()` timings are analyzed before any frame render; unsupported Python falls back to Manim `--dry_run`. A host-wide `flock` queues builds, speech/frame/step progress includes ETA, and Deepgram matching normalizes common spoken numbers to digits while reporting omitted numerals separately from strict ordinary-word recall. Trigger: the 39-step University Manim draft/contact sheet appeared only after a 237 s full still render, and dry-run timing validation took 198 s.
 - **Chat-ready export for interactive HTML artifacts** (`.orchestra/pipelines/default/prompts/skills/html-artifacts.md`; V-834). User-entered values are copied with field labels using one prominent button, with a selected-textarea fallback when clipboard access is unavailable; export is client-side without server storage, localStorage synchronization, or external requests. Trigger: the owner rejected public links and server storage as unsafe.
 - **Live generation and running-tool activity in the dashboard chat** (`app/backend_claude.py`, `app/session.py`, `app/live_broker.py`, `app/task_output_tail.py`, `app/routes/sessions.py`, `app/static/js/live-activity.js`, `app/static/js/chat.js`; V-831). Claude partial messages are no longer filtered to `text_delta`: `input_json_delta` becomes `tool_input_stream` (tool id/name from `content_block_start`, keyed by parent and block index so sub-agents do not collide) and `thinking_delta` becomes `thinking_stream`, including the `estimated_tokens` counter the CLI sends when thinking text is omitted. The chat shows a card for the call being written — tool name, decoded argument text, character count, chars/s and elapsed time — replaced by the normal card when the persisted `tool` row lands. Every unanswered tool call shows a pulsing "running m:ss of m:ss" clock (Bash `timeout`, default 2:00, cap 10:00; elapsed only for tools without a timeout), and shell tasks (`local_bash`, foreground or background) show live output tailed from the CLI's `tasks/<task_id>.output` file. The SSE loop merges adjacent deltas of one block per ~100 ms tick, the broker keeps a capped tail of each open block so a reopened chat resumes it, and nothing partial is written to `logs`. Codex app-server 0.160.0 has no tool-argument delta notification, so Codex keeps its existing reasoning/output streams. Trigger: a 42 KB Bash heredoc took minutes to write with nothing visible, and running commands looked dead.
 - **Parallel voice synthesis and incremental HTML rendering** (`scripts/video_artifact/make.py`, `tts_worker.py`, `tts_worker_en.py`; V-832). Each speech environment loads its model once and synthesizes up to four phrases concurrently; ordered cache results preserve the step timeline, while HTML frame segments start when their phrase and all preceding phrases are ready. Manim still waits for the complete timing plan before `construct()`. Trigger: cold video builds spent 66–77 s loading Vosk and then synthesized phrases serially before starting any HTML frames.
 - **CI and local agent-documentation integrity check** (`scripts/check_instruction_contract.py`, `.github/workflows/ci.yml`; V-826). The instruction contract command reuses `app.kb_index` to check KB topic/index coverage and resolves relative Markdown and backtick file references in `AGENTS.md` and `.orchestra/kb/*.md`; CI runs it once in the test shards. Trigger: KB topics can be invisible to agents when absent from its index, and stale paths misdirect readers.
### cebb03d02 V-839: #V-839: accept scoped file delivery keys

diff --git a/CHANGELOG.md b/CHANGELOG.md
index fdfcb64c7..40774bbb7 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -5,10 +5,11 @@
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
 ### Added
+- **Accept scoped caller keys for durable file delivery** (`app/file_delivery_ids.py`, `app/mcp_stdio.py`; V-839). `send_file` and `send_files` now accept any non-empty `event_id`; non-UUID keys map deterministically to UUIDv5 using project scope and sender, while UUID keys keep their existing canonical identity for queued receipts. The internal `/api/tg/send_file` contract remains canonical UUID because the delivery table and receipt-status route use it as the durable storage key. Trigger: agents supplied readable retry keys such as `lada-kp27-0810`, which the MCP layer rejected before sending.
 - **Retire historical managed skill copies across directory moves** (`app/prompting.py`; V-837). Skill cleanup follows Git renames when collecting approved historical hashes, so exact copies from the pre-`.orchestra` `pipelines/default/prompts/skills/` path are recognized. Refresh also removes orphaned temp files only when they match the injector's `.SKILL.md.<pid>.<8-hex>.tmp` naming pattern under a retired skill; tracked paths, symlinks, changed content, and unrelated temp files remain untouched. Trigger: V-819 removed `codex-debate` and renamed `explainer-video`, but copies from the old canonical path and an interrupted atomic write remained.
 - **Fast video drafts, static Manim timing checks, build queue, and progress estimates** (`scripts/video_artifact/make.py`, `manim_timing.py`, `manim_voice.py`; V-835). Scenes can render selected stop frames before TTS, and supported Manim `self.left()` timings are analyzed before any frame render; unsupported Python falls back to Manim `--dry_run`. A host-wide `flock` queues builds, speech/frame/step progress includes ETA, and Deepgram matching normalizes common spoken numbers to digits while reporting omitted numerals separately from strict ordinary-word recall. Trigger: the 39-step University Manim draft/contact sheet appeared only after a 237 s full still render, and dry-run timing validation took 198 s.
 - **Chat-ready export for interactive HTML artifacts** (`.orchestra/pipelines/default/prompts/skills/html-artifacts.md`; V-834). User-entered values are copied with field labels using one prominent button, with a selected-textarea fallback when clipboard access is unavailable; export is client-side without server storage, localStorage synchronization, or external requests. Trigger: the owner rejected public links and server storage as unsafe.
 - **Live generation and running-tool activity in the dashboard chat** (`app/backend_claude.py`, `app/session.py`, `app/live_broker.py`, `app/task_output_tail.py`, `app/routes/sessions.py`, `app/static/js/live-activity.js`, `app/static/js/chat.js`; V-831). Claude partial messages are no longer filtered to `text_delta`: `input_json_delta` becomes `tool_input_stream` (tool id/name from `content_block_start`, keyed by parent and block index so sub-agents do not collide) and `thinking_delta` becomes `thinking_stream`, including the `estimated_tokens` counter the CLI sends when thinking text is omitted. The chat shows a card for the call being written — tool name, decoded argument text, character count, chars/s and elapsed time — replaced by the normal card when the persisted `tool` row lands. Every unanswered tool call shows a pulsing "running m:ss of m:ss" clock (Bash `timeout`, default 2:00, cap 10:00; elapsed only for tools without a timeout), and shell tasks (`local_bash`, foreground or background) show live output tailed from the CLI's `tasks/<task_id>.output` file. The SSE loop merges adjacent deltas of one block per ~100 ms tick, the broker keeps a capped tail of each open block so a reopened chat resumes it, and nothing partial is written to `logs`. Codex app-server 0.160.0 has no tool-argument delta notification, so Codex keeps its existing reasoning/output streams. Trigger: a 42 KB Bash heredoc took minutes to write with nothing visible, and running commands looked dead.
 - **Parallel voice synthesis and incremental HTML rendering** (`scripts/video_artifact/make.py`, `tts_worker.py`, `tts_worker_en.py`; V-832). Each speech environment loads its model once and synthesizes up to four phrases concurrently; ordered cache results preserve the step timeline, while HTML frame segments start when their phrase and all preceding phrases are ready. Manim still waits for the complete timing plan before `construct()`. Trigger: cold video builds spent 66–77 s loading Vosk and then synthesized phrases serially before starting any HTML frames.
### 4bd9c2eaf V-821: #V-821: sparse worker worktrees for all projects: manifest rule, task-switch retarget, merge refusal with fix, converter, prompt, tests

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 40774bbb7..cbd9574ff 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -5,10 +5,11 @@
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
 ### Added
+- **Partial (sparse) worker worktrees for every project** (`app/sparse_worktree.py`, `app/workspace.py`, `app/pipeline.py`, `.orchestra/pipelines/default/pipeline.yaml`, `scripts/sparse_convert.py`; V-821). New worker worktrees are created with `git worktree add --no-checkout` and a per-worktree non-cone sparse rule from `defaults.worktree.sparse`: `artifacts/` and `.orchestra/tasks/` stay out, the task's own directories (`.orchestra/tasks/{id}`, `artifacts/{id}`, `artifacts/task-{id}`, `…-*`) come in by task number, `include` adds fixed directories (katya-work: `artifacts/task-2/tooling`), and `reference_scan` pulls in directories that tracked KB notes and tests mention (orchestra: KB links and test fixtures such as `.orchestra/tasks/224`, found by `git grep` at spawn, so a new fixture needs no list edit). Projects override by glob on the repository root; `enabled: false` gives a full copy; a failed rule setup falls back to a full copy instead of blocking the spawn. `switch_worktree_branch` and `promote_worktree_branch` recompute the own directories for the new task number from the rule stored in the worktree. `_clean_worktree_error` now recognises dirty paths that git cannot stage because they lie outside the sparse checkout (`git add -A` returns 0 and commits nothing for a modified tracked file there) and tells the worker which `git sparse-checkout add /<dir>/` to run, so `merge_worker` refuses with a way out instead of the old "commit or discard". `convert_worktree_to_sparse` and `scripts/sparse_convert.py` move existing worktrees over (dry run by default; refuses on modified or untracked files, a merge in progress or a process working inside; ignored and untracked files stay). The worker prompt (`git-workflow.md`) says to read absent history from the main checkout or `git show main:<path>` and to load a directory only when changing a file in it. Triggering case: the VPS disk reached 95% on 11.10.2026 with ~58 GB in katya-work worker copies. Measured on temporary clones: katya-work copy 4246 MB → 40 MB (+ own directories), seedon 1305 → 99 MB, orchestra 324 → ≈57 MB. Known tradeoff: a task that reworks an earlier result changes files that are not in the copy until `git sparse-checkout add`; in the 30-day replay that was 29% of katya-work tasks, 24% of seedon and 6% of orchestra tasks. Python changes take effect after a restart.
 - **Accept scoped caller keys for durable file delivery** (`app/file_delivery_ids.py`, `app/mcp_stdio.py`; V-839). `send_file` and `send_files` now accept any non-empty `event_id`; non-UUID keys map deterministically to UUIDv5 using project scope and sender, while UUID keys keep their existing canonical identity for queued receipts. The internal `/api/tg/send_file` contract remains canonical UUID because the delivery table and receipt-status route use it as the durable storage key. Trigger: agents supplied readable retry keys such as `lada-kp27-0810`, which the MCP layer rejected before sending.
 - **Retire historical managed skill copies across directory moves** (`app/prompting.py`; V-837). Skill cleanup follows Git renames when collecting approved historical hashes, so exact copies from the pre-`.orchestra` `pipelines/default/prompts/skills/` path are recognized. Refresh also removes orphaned temp files only when they match the injector's `.SKILL.md.<pid>.<8-hex>.tmp` naming pattern under a retired skill; tracked paths, symlinks, changed content, and unrelated temp files remain untouched. Trigger: V-819 removed `codex-debate` and renamed `explainer-video`, but copies from the old canonical path and an interrupted atomic write remained.
 - **Fast video drafts, static Manim timing checks, build queue, and progress estimates** (`scripts/video_artifact/make.py`, `manim_timing.py`, `manim_voice.py`; V-835). Scenes can render selected stop frames before TTS, and supported Manim `self.left()` timings are analyzed before any frame render; unsupported Python falls back to Manim `--dry_run`. A host-wide `flock` queues builds, speech/frame/step progress includes ETA, and Deepgram matching normalizes common spoken numbers to digits while reporting omitted numerals separately from strict ordinary-word recall. Trigger: the 39-step University Manim draft/contact sheet appeared only after a 237 s full still render, and dry-run timing validation took 198 s.
 - **Chat-ready export for interactive HTML artifacts** (`.orchestra/pipelines/default/prompts/skills/html-artifacts.md`; V-834). User-entered values are copied with field labels using one prominent button, with a selected-textarea fallback when clipboard access is unavailable; export is client-side without server storage, localStorage synchronization, or external requests. Trigger: the owner rejected public links and server storage as unsafe.
 - **Live generation and running-tool activity in the dashboard chat** (`app/backend_claude.py`, `app/session.py`, `app/live_broker.py`, `app/task_output_tail.py`, `app/routes/sessions.py`, `app/static/js/live-activity.js`, `app/static/js/chat.js`; V-831). Claude partial messages are no longer filtered to `text_delta`: `input_json_delta` becomes `tool_input_stream` (tool id/name from `content_block_start`, keyed by parent and block index so sub-agents do not collide) and `thinking_delta` becomes `thinking_stream`, including the `estimated_tokens` counter the CLI sends when thinking text is omitted. The chat shows a card for the call being written — tool name, decoded argument text, character count, chars/s and elapsed time — replaced by the normal card when the persisted `tool` row lands. Every unanswered tool call shows a pulsing "running m:ss of m:ss" clock (Bash `timeout`, default 2:00, cap 10:00; elapsed only for tools without a timeout), and shell tasks (`local_bash`, foreground or background) show live output tailed from the CLI's `tasks/<task_id>.output` file. The SSE loop merges adjacent deltas of one block per ~100 ms tick, the broker keeps a capped tail of each open block so a reopened chat resumes it, and nothing partial is written to `logs`. Codex app-server 0.160.0 has no tool-argument delta notification, so Codex keeps its existing reasoning/output streams. Trigger: a 42 KB Bash heredoc took minutes to write with nothing visible, and running commands looked dead.