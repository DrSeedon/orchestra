# Candidate cand-23

## ORIGIN commit 69f7e4c106 (2026-07-18): feat: render full Codex worker telemetry
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/backend_codex.py b/app/backend_codex.py
index 586b9d57a..f33f2beca 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -180,16 +180,17 @@ class CodexBackend:
         self._request_seq = 0
         self._write_lock = asyncio.Lock()
         self._active_turn_id: str | None = None
         self._events_active = False
         self._disconnecting = False
         self._last_stderr = ""
         self._last_turn_error: dict = {}
         self._started_items: set[str] = set()
+        self._subagent_descriptions: dict[str, str] = {}
         self._rollout_path: Path | None = None
         self._usage_baseline: dict[str, int] | None = None
         self._thread_usage_total: dict[str, int] | None = None
         self._last_call_usage: dict[str, int] | None = None
         self._model_context_window = CODEX_CONTEXT_LIMITS.get(model, 258400)
 
     @property
     def session_id(self) -> Optional[str]:
@@ -499,35 +500,132 @@ class CodexBackend:
             model_error = self._classify_error(error)
             if model_error == "rate_limit":
                 content = f"rate_limit: {content}"
             return [AgentEvent("error", content, metadata={"model_error": model_error})]
 
         if method == "model/rerouted":
             return [AgentEvent("status", f"model rerouted: {json.dumps(params, ensure_ascii=False)}")]
 
-        if method == "context/compacted":
+        if method in ("context/compacted", "thread/compacted"):
             return [AgentEvent("status", "codex context compacted")]
 
+        if method in (
+            "item/reasoning/summaryTextDelta",
+            "item/reasoning/textDelta",
+            "item/plan/delta",
+        ):
+            activity = "plan" if method == "item/plan/delta" else "reasoning"
+            return [AgentEvent(
+                "thinking_stream",
+                params.get("delta", ""),
+                metadata={
+                    "activity": activity,
+                    "item_id": params.get("itemId", ""),
+                },
+            )]
+
+        if method == "turn/plan/updated":
+            return [AgentEvent("plan", json.dumps({
+                "explanation": params.get("explanation"),
+                "plan": params.get("plan") or [],
+            }, ensure_ascii=False))]
+
+        if method == "turn/diff/updated":
+            return [AgentEvent(
+                "turn_diff",
+                params.get("diff", ""),
+                metadata={"turn_id": params.get("turnId", "")},
+            )]
+
+        if method in (
+            "item/commandExecution/outputDelta",
+            "item/fileChange/outputDelta",
+        ):
+            return [AgentEvent(
+                "tool_stream",
+                params.get("delta", ""),
+                metadata={"tool_use_id": params.get("itemId", "")},
+            )]
+
+        if method == "item/commandExecution/terminalInteraction":
+            return [AgentEvent(
+                "tool_stream",
+                params.get("stdin", ""),
+                metadata={
+                    "tool_use_id": params.get("itemId", ""),
+                    "stream": "stdin",
+                },
+            )]
+
+        if method == "item/fileChange/patchUpdated":
+            return [AgentEvent(
+                "tool_patch",
+                json.dumps({"changes": params.get("changes") or []}, ensure_ascii=False),
+                metadata={"tool_use_id": params.get("itemId", "")},
+            )]
+
         if method == "item/started":
             item = params.get("item") or {}
             item_id = str(item.get("id") or "")
             if item_id:
                 self._started_items.add(item_id)
             return self._item_started(item)
 
         if method == "item/completed":
             return self._item_completed(params.get("item") or {})
 
         if method == "item/mcpToolCall/progress":
-            return [AgentEvent("status", f"MCP: {params.get('message', '')}")]
+            return [AgentEvent(
+                "tool_stream",
+                params.get("message", ""),
+                metadata={"tool_use_id": params.get("itemId", "")},
+            )]
 
         if method == "item/agentMessage/delta":
             return [AgentEvent("stream", params.get("delta", ""))]
 
+        if method in ("warning", "guardianWarning", "deprecationNotice", "configWarning"):
+            content = (
+                params.get("message")
+                or params.get("summary")
+                or "Codex warning"
+            )
+            details = params.get("details")
+            if details:
+                content = f"{content}\n{details}"
+            return [AgentEvent("warning", content)]
+
+        if method == "mcpServer/startupStatus/updated":
+            name = params.get("name") or "unknown"
+            status = params.get("status") or "unknown"
+            detail = params.get("error") or params.get("failureReason") or ""
+            content = f"codex mcp {name}: {status}"
+            if detail:
+                content = f"{content} — {detail}"
+            event_type = "warning" if status in ("failed", "cancelled") else "status"
+            return [AgentEvent(event_type, content)]
+
+        if method in ("hook/started", "hook/completed"):
+            run = params.get("run") or {}
+            phase = "started" if method.endswith("/started") else "completed"
+            label = run.get("eventName") or run.get("id") or "hook"
+            status = run.get("status") or phase
+            duration = run.get("durationMs")
+            suffix = f" · {duration}ms" if duration is not None else ""
+            return [AgentEvent("status", f"codex hook {label}: {status}{suffix}")]
+
+        if method in ("item/autoApprovalReview/started", "item/autoApprovalReview/completed"):
+            phase = "started" if method.endswith("/started") else "completed"
+            return [AgentEvent("status", f"codex approval review {phase}")]
+
+        if method == "model/safetyBuffering/updated" and params.get("showBufferingUi"):
+            reasons = ", ".join(params.get("reasons") or [])
+            return [AgentEvent("warning", f"Codex safety buffering: {reasons or params.get('model', '')}")]
+
         if method == "turn/completed":
             turn = params.get("turn") or {}
             self._active_turn_id = None
             return self._turn_completed(turn)
 
         if method == "_process/exited":
             self._active_turn_id = None
             return [AgentEvent("turn_end", "stop_reason=process_exit", metadata={
@@ -545,38 +643,78 @@ class CodexBackend:
             })]
 
         return []
 
     def _item_started(self, item: dict) -> list[AgentEvent]:
         item_type = item.get("type", "")
         item_id = str(item.get("id") or "")
         if item_type == "commandExecution":
-            return [self._tool_use("Bash", item.get("command", ""), item_id)]
+            payload = {
+                "command": item.get("command", ""),
+                "cwd": item.get("cwd", self.cwd),
+                "command_actions": item.get("commandActions") or [],
+            }
+            return [self._tool_use(
+                "Bash",
+                json.dumps(payload, ensure_ascii=False),
+                item_id,
+            )]
+        if item_type == "fileChange":
+            payload = {
+                "changes": item.get("changes") or [],
+                "status": item.get("status", ""),
+            }
+            return [self._tool_use(
+                "FileChange",
+                json.dumps(payload, ensure_ascii=False),
+                item_id,
+            )]
         if item_type == "mcpToolCall":
             server, tool = item.get("server", ""), item.get("tool", "")
             name = f"mcp__{server}__{tool}" if server else tool
             return [self._tool_use(
                 name,
                 json.dumps(item.get("arguments") or {}, ensure_ascii=False)[:500],
                 item_id,
                 short_name=tool,
             )]
         if item_type == "dynamicToolCall":
             return [self._tool_use(
                 item.get("tool", "tool"),
                 json.dumps(item.get("arguments") or {}, ensure_ascii=False)[:500],
                 item_id,
             )]
         if item_type == "webSearch":
-            return [self._tool_use("WebSearch", item.get("query", ""), item_id)]
+            return [self._tool_use(
+                "WebSearch",
+                json.dumps({
+                    "query": item.get("query", ""),
+                    "action": item.get("action"),
+                }, ensure_ascii=False),
+                item_id,
+            )]
         if item_type == "imageView":
-            return [self._tool_use("ViewImage", item.get("path", ""), item_id)]
+            return [self._tool_use(
+                "ViewImage",
+                json.dumps({"file_path": item.get("path", "")}, ensure_ascii=False),
+                item_id,
+            )]
         if item_type == "imageGeneration":
-            return [self._tool_use("ImageGeneration", "", item_id)]
+            return [self._tool_use(
+                "ImageGeneration",
+                json.dumps({"status": item.get("status", "")}, ensure_ascii=False),
+                item_id,
+            )]
+        if item_type == "sleep":
+            return [self._tool_use(
+                "Sleep",
+                json.dumps({"duration_ms": item.get("durationMs", 0)}),
+                item_id,
+            )]
         if item_type == "collabAgentToolCall":
             return self._collab_events(item, completed=False)
         if item_type == "contextCompaction":
             return [AgentEvent("status", "codex compacting context")]
         return []
 
     def _item_completed(self, item: dict) -> list[AgentEvent]:
         item_type = item.get("type", "")
@@ -593,31 +731,35 @@ class CodexBackend:
             text = "\n".join(str(part) for part in parts if part)
             if text:
                 events.append(AgentEvent("thinking", text))
         elif item_type == "plan":
             if item.get("text"):
                 events.append(AgentEvent("thinking", item["text"]))
         elif item_type == "commandExecution":
             if unseen:
-                events.append(self._tool_use("Bash", item.get("command", ""), item_id))
+                events.extend(self._item_started(item))
             output = item.get("aggregatedOutput")
             if output is not None:
                 events.append(AgentEvent(
                     "tool_result",
                     str(output),
                     metadata={"exit_code": item.get("exitCode"), "tool_use_id": item_id},
                 ))
         elif item_type == "fileChange":
-            changes = item.get("changes") or []
-            desc = ", ".join(
-                f"{change.get('kind', '')} {change.get('path', '')}".strip()
-                for change in changes
-            )
-            events.append(AgentEvent("file_change", desc, metadata={"tool_use_id": item_id}))
+            if unseen:
+                events.extend(self._item_started(item))
+            events.append(AgentEvent(
+                "tool_result",
+                json.dumps({
+                    "status": item.get("status", ""),
+                    "files": len(item.get("changes") or []),
+                }, ensure_ascii=False),
+                metadata={"tool_use_id": item_id},
+            ))
         elif item_type == "mcpToolCall":
             server, tool = item.get("server", ""), item.get("tool", "")
             name = f"mcp__{server}__{tool}" if server else tool
             if unseen:
                 events.append(self._tool_use(
                     name,
                     json.dumps(item.get("arguments") or {}, ensure_ascii=False)[:500],
                     item_id,
@@ -640,81 +782,130 @@ class CodexBackend:
                 events.extend(self._item_started(item))
             content = item.get("contentItems")
             if content is not None:
                 events.append(AgentEvent(
                     "tool_result",
                     self._result_text(content),
                     metadata={"tool_use_id": item_id},
                 ))
+            elif item.get("success") is False or item.get("status") == "failed":
+                events.append(AgentEvent(
+                    "tool_result",
+                    json.dumps({
+                        "status": item.get("status"),
+                        "success": item.get("success"),
+                    }),
+                    metadata={"tool_use_id": item_id},
+                ))
         elif item_type == "webSearch":
             if unseen:
                 events.extend(self._item_started(item))
             events.append(AgentEvent(
                 "tool_result",
-                f"Web search completed: {item.get('query', '')}",
+                json.dumps({
+                    "query": item.get("query", ""),
+                    "action": item.get("action"),
+                    "status": "completed",
+                }, ensure_ascii=False),
                 metadata={"tool_use_id": item_id},
             ))
         elif item_type == "imageView":
             if unseen:
                 events.extend(self._item_started(item))
+            events.append(AgentEvent(
+                "tool_result",
+                json.dumps({
+                    "status": "viewed",
+                    "file_path": item.get("path", ""),
+                }, ensure_ascii=False),
+                metadata={"tool_use_id": item_id},
+            ))
         elif item_type == "imageGeneration":
             if unseen:
                 events.extend(self._item_started(item))
-            result = item.get("result") or item.get("savedPath") or item.get("status", "")
-            events.append(AgentEvent("tool_result", str(result), metadata={"tool_use_id": item_id}))
+            events.append(AgentEvent(
+                "tool_result",
+                json.dumps({
+                    "result": item.get("result"),
+                    "saved_path": item.get("savedPath"),
+                    "status": item.get("status", ""),
+                    "revised_prompt": item.get("revisedPrompt"),
+                }, ensure_ascii=False),
+                metadata={"tool_use_id": item_id},
+            ))
+        elif item_type == "sleep":
+            if unseen:
+                events.extend(self._item_started(item))
+            events.append(AgentEvent(
+                "tool_result",
+                json.dumps({"status": "completed", "duration_ms": item.get("durationMs", 0)}),
+                metadata={"tool_use_id": item_id},
+            ))
         elif item_type == "collabAgentToolCall":
             events.extend(self._collab_events(item, completed=True))
         elif item_type == "subAgentActivity":
             sub_id = item.get("agentThreadId", "")
             kind = item.get("kind", "activity")
             agent_path = item.get("agentPath", "")
             events.append(AgentEvent(
                 "subagent_progress",
                 f"{agent_path} | type=codex | id={sub_id} | tool={kind}",
                 metadata={"subagent_id": sub_id, "status": kind, "phase": "progress"},
             ))
         elif item_type == "contextCompaction":
             events.append(AgentEvent("status", "codex context compacted"))
+        elif item_type in ("enteredReviewMode", "exitedReviewMode"):
+            phase = "entered" if item_type == "enteredReviewMode" else "exited"
+            events.append(AgentEvent("review", json.dumps({
+                "phase": phase,
+                "review": item.get("review", ""),
+            }, ensure_ascii=False)))
 
         if item_id:
             self._started_items.discard(item_id)
         return events
 
     def _collab_events(self, item: dict, *, completed: bool) -> list[AgentEvent]:
         tool = item.get("tool", "")
         receiver_ids = item.get("receiverThreadIds") or [item.get("id", "")]
         agent_states = item.get("agentsStates") or {}
         events = []
         for sub_id in receiver_ids:
-            description = item.get("prompt") or tool
+            prompt = item.get("prompt") or ""
+            if tool == "spawnAgent" and prompt:
+                self._subagent_descriptions[sub_id] = prompt
+            description = prompt or self._subagent_descriptions.get(sub_id) or tool
             agent_state = agent_states.get(sub_id) or {}
             agent_status = agent_state.get("status", "")
+            summary = agent_state.get("message") or ""
             metadata = {
                 "subagent_id": sub_id,
                 "tool_use_id": item.get("id", ""),
                 "description": description,
                 "task_type": "codex",
                 "status": agent_status or item.get("status", ""),
+                "summary": summary,
             }
             if tool == "spawnAgent" and not completed:
                 metadata["phase"] = "start"
                 content = (
                     f"{description} | type=codex | id={sub_id} | "
                     f"tool_use_id={item.get('id', '')}"
                 )
                 events.append(AgentEvent("subagent_start", content, metadata))
             elif completed and (
                 tool == "closeAgent"
                 or agent_status in {"interrupted", "completed", "errored", "shutdown", "notFound"}
             ):
                 metadata["phase"] = "end"
                 content = (
                     f"{description} | type=codex | id={sub_id} | "
                     f"tool_use_id={item.get('id', '')} | status={metadata['status']}"
+                    f"{' | ' + summary[:500] if summary else ''}"
                 )
                 events.append(AgentEvent("subagent_end", content, metadata))
             else:
                 metadata["phase"] = "progress"
                 content = (
                     f"{description} | type=codex | id={sub_id} | "
                     f"tool_use_id={item.get('id', '')} | tool={tool}"
                 )
@@ -807,16 +998,24 @@ class CodexBackend:
             "tls", "unexpected eof", "error sending request",
         )):
             return "server_error"
         return "error"
 
     @staticmethod
     def _tool_use(name: str, summary: str, item_id: str,
                   short_name: str | None = None) -> AgentEvent:
+        if item_id:
+            try:
+                payload = json.loads(summary)
+            except (json.JSONDecodeError, TypeError):
+                payload = None
+            if isinstance(payload, dict):
+                payload["_codex_item_id"] = item_id
+                summary = json.dumps(payload, ensure_ascii=False)
         short = short_name or name
         return AgentEvent(
             "tool_use",
             f"{name}: {summary}",
             metadata={
                 "tool_name": name,
                 "short_name": short,
                 "tool_use_id": item_id,
diff --git a/app/session.py b/app/session.py
index cf69e223c..54dcaa328 100644
--- a/app/session.py
+++ b/app/session.py
@@ -623,16 +623,28 @@ class AgentSession:
             return
         if event.type == "subagent_stream":
             # Live sub-agent output → broker only (ephemeral, like main stream).
             # subagent_id lets the UI nest it under the right sub-agent block.
             from app.live_broker import broker
             broker.publish(self.id, {"type": "subagent_stream", "content": event.content,
                                      "subagent_id": event.metadata.get("subagent_id", "")})
             return
+        if event.type in ("thinking_stream", "tool_stream", "tool_patch", "turn_diff"):
+            # Codex app-server exposes fine-grained activity that is valuable live but
+            # would flood the DB. The authoritative thinking/tool/file events are still
+            # persisted when their item completes.
+            from app.live_broker import broker
+            payload = {"type": event.type, "content": event.content}
+            for key in ("activity", "item_id", "tool_use_id", "turn_id", "stream"):
+                value = event.metadata.get(key)
+                if value:
+                    payload[key] = value
+            broker.publish(self.id, payload)
+            return
         # Sub-agent tool_use/text/tool_result (tagged with subagent_id) → broker ONLY
         # (ephemeral live nesting under the sub-agent block). NOT persisted — the DB
         # record is subagent_start/end; persisting these too would double-render them
         # (once in the accordion via broker, once in the main flow on reload).
         sub_id = event.metadata.get("subagent_id")
         if sub_id and event.type in ("tool_use", "tool_result", "text", "thinking"):
             from app.live_broker import broker
             broker.publish(self.id, {"type": "subagent_event", "event_type": event.type,
@@ -656,16 +668,18 @@ class AgentSession:
             tool_name = event.metadata.get("tool_name", event.content)
             if "send_message" in tool_name or "mcp__orchestra__send_message" in tool_name:
                 self._did_report = True
         elif event.type == "tool_result":
             self._log("tool_result", event.content)
         elif event.type == "file_change":
             self._log("tool", f"file: {event.content}")
             self._turn_logs.append(f"[tool] file: {event.content[:60]}")
+        elif event.type in ("plan", "warning", "review"):
+            self._log(event.type, event.content)
         elif event.type == "turn_end":
             self._turns.handle_turn_end(event)
         elif event.type == "error":
             # rate_limit → single retry-status log (skip raw error to avoid duplicate
             # "model error: rate_limit" + "rate limited — retry" on one event)
             if "rate_limit" in event.content:
                 # Session limit text arrives BEFORE the error event as text "You've hit your session limit"
                 if self._session_limit_hit:
diff --git a/app/static/css/style.css b/app/static/css/style.css
index 2b520a09b..edb904be2 100644
--- a/app/static/css/style.css
+++ b/app/static/css/style.css
@@ -98,16 +98,53 @@ textarea:disabled, button:disabled { opacity: 0.4; cursor: not-allowed; }
 .waiting-dots span { animation: dot-blink 1.4s infinite; opacity: 0.2; font-size: 18px; line-height: 1; }
 .waiting-dots span:nth-child(2) { animation-delay: 0.2s; }
 .waiting-dots span:nth-child(3) { animation-delay: 0.4s; }
 @keyframes dot-blink { 0%,80%,100% { opacity: 0.2; } 40% { opacity: 1; } }
 .streaming { animation: stream-in 200ms ease-out; }
 @keyframes stream-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
 .typing-cursor { display: inline; animation: cursor-blink 800ms steps(2) infinite; color: #818cf8; font-weight: 300; user-select: none; pointer-events: none; }
 @keyframes cursor-blink { 0%,100% { opacity: 1; } 50% { opacity: 0; } }
+.codex-activity-card { position: relative; margin: 3px 0; padding: 8px 10px; border: 1px solid rgba(56,189,248,0.16); border-left: 3px solid #38bdf8; border-radius: 7px; background: linear-gradient(110deg, rgba(8,47,73,0.22), rgba(15,23,42,0.72)); color: #cbd5e1; font-size: 11px; overflow: hidden; }
+.codex-activity-header { display: flex; align-items: center; gap: 7px; width: 100%; padding: 0; border: 0; background: transparent; color: #7dd3fc; font-size: 11px; font-weight: 600; text-align: left; cursor: pointer; }
+.codex-activity-caret { width: 10px; color: #475569; }
+.codex-activity-body { margin-top: 7px; padding: 7px 9px; border-top: 1px solid rgba(56,189,248,0.12); color: #94a3b8; font-size: 11px; max-height: 320px; overflow-y: auto; }
+.codex-thinking-live { border-left-color: #818cf8; background: linear-gradient(110deg, rgba(49,46,129,0.18), rgba(15,23,42,0.72)); }
+.codex-live-label { color: #a5b4fc; font-size: 10px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
+.codex-live-thinking-body { margin-top: 5px; color: #94a3b8; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 160px; overflow-y: auto; }
+.codex-thinking-live::after { content: ''; position: absolute; inset: auto 0 0 0; height: 1px; background: linear-gradient(90deg, transparent, #818cf8, transparent); animation: codex-scan 1.6s ease-in-out infinite; }
+@keyframes codex-scan { 0%,100% { transform: translateX(-70%); opacity: .15; } 50% { transform: translateX(70%); opacity: .8; } }
+.codex-plan-card { border-left-color: #22c55e; background: linear-gradient(110deg, rgba(20,83,45,0.16), rgba(15,23,42,0.74)); }
+.codex-plan-title { color: #86efac; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
+.codex-plan-explanation { margin-top: 3px; color: #64748b; }
+.codex-plan-steps { display: grid; gap: 4px; margin-top: 7px; }
+.codex-plan-step { display: grid; grid-template-columns: 15px 1fr; gap: 5px; color: #94a3b8; }
+.codex-plan-icon { font-family: 'JetBrains Mono', monospace; text-align: center; }
+.codex-plan-completed { color: #4ade80; }
+.codex-plan-inprogress { color: #7dd3fc; }
+.codex-plan-inprogress .codex-plan-icon { animation: cursor-blink 900ms infinite; }
+.codex-warning { position: relative; display: flex; gap: 8px; align-items: flex-start; margin: 3px 0; padding: 7px 10px; border-left: 3px solid #f59e0b; border-radius: 6px; background: rgba(120,53,15,0.13); color: #fcd34d; font-size: 11px; white-space: pre-wrap; overflow-wrap: anywhere; }
+.codex-warning-icon { color: #f59e0b; font-weight: 800; }
+.codex-review { position: relative; margin: 3px 0; padding: 7px 10px; border-left: 3px solid #f472b6; border-radius: 6px; background: rgba(131,24,67,0.12); font-size: 11px; }
+.codex-review-title { color: #f9a8d4; font-weight: 700; }
+.codex-review-body { margin-top: 3px; color: #94a3b8; white-space: pre-wrap; }
+.codex-live-output { max-height: 180px; margin: 6px 0 0; padding: 6px 8px; overflow: auto; border: 1px solid rgba(56,189,248,0.12); border-radius: 5px; background: #080d14; color: #a5f3fc; font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 10px; line-height: 1.45; white-space: pre-wrap; }
+.codex-command-actions { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 5px; }
+.codex-command-action { max-width: 100%; padding: 1px 6px; border: 1px solid #273548; border-radius: 999px; color: #64748b; background: rgba(15,23,42,.7); font-size: 9px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
+.codex-command-read { color: #7dd3fc; }
+.codex-command-search { color: #c4b5fd; }
+.codex-tool-image { display: block; max-width: 100%; max-height: 260px; margin-top: 7px; border: 1px solid #273548; border-radius: 7px; object-fit: contain; cursor: zoom-in; background: #080d14; }
+.codex-image-prompt { margin-top: 5px; color: #64748b; font-size: 10px; line-height: 1.4; }
+.codex-turn-diff { border-left-color: #f59e0b; }
+.codex-diff-file { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
+.codex-change-kind { padding: 1px 5px; border-radius: 999px; font-size: 8px; text-transform: uppercase; }
+.codex-change-add { color: #4ade80; background: rgba(34,197,94,.12); }
+.codex-change-delete { color: #f87171; background: rgba(239,68,68,.12); }
+.codex-change-update { color: #fbbf24; background: rgba(245,158,11,.12); }
+.codex-diff-more { cursor: pointer; text-align: center; color: #38bdf8; }
 .file-item { padding: 2px 4px; cursor: pointer; border-radius: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
 .file-item:hover { background: rgba(99, 102, 241, 0.15); }
 .file-item.drag-over { background: rgba(99, 102, 241, 0.3); }
 .file-dir { color: #38bdf8; }
 .file-file { color: var(--ink-soft); }
 .file-children { padding-left: 12px; }
 select { appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%2394a3b8' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10z'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 8px center; }
 .no-scrollbar::-webkit-scrollbar { display: none; }
diff --git a/app/static/js/app.js b/app/static/js/app.js
index a69deb2aa..f7f484b0e 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1131,16 +1131,17 @@ async function onOrchestratorChange() {
     localMessages.clear();
     pendingUserMsgs = [];
     pendingBubble = null;
     _finalizedBubble = null;
     if (_streamRafId) { cancelAnimationFrame(_streamRafId); _streamRafId = null; }
     streamBubble = null;
     streamContent = '';
     streamPending = '';
+    _resetCodexActivityState();
     selectedAgent = opt?.dataset?.name || null;
     if (currentScope && selectedAgent) {
         localStorage.setItem('lastOrchScope', currentScope);
         localStorage.setItem('lastOrchName', selectedAgent);
     }
     $('#chat').innerHTML = '';
     scrollAfterLoad = true;
     updateAgentInfo(null);
@@ -1161,16 +1162,17 @@ async function selectAgent(name) {
     pendingBubble = null;
     _finalizedBubble = null;
     selectedAgent = name;
     _hideRateLimitBanner();
     if (_streamRafId) { cancelAnimationFrame(_streamRafId); _streamRafId = null; }
     streamBubble = null;
     streamContent = '';
     streamPending = '';
+    _resetCodexActivityState();
     $('#chat').innerHTML = '';
     chatLogs[name] = { lastId: 0, firstId: null, initialCount: 0 };
     scrollAfterLoad = true;
     updateInputState();
     restoreDraft();
     renderAgentList();
     fetchAgentContext(name);
     await refreshSessions();
@@ -1932,17 +1934,17 @@ function _streamFlush() {
 }
 
 function _renderJsonGrid(obj, container, maxDepth) {
     if (maxDepth === undefined) maxDepth = 2;
     const grid = document.createElement('div');
     grid.style.cssText = 'display:grid;grid-template-columns:auto 1fr;gap:1px 10px;font-size:10px;align-items:baseline';
     const entries = Object.entries(obj);
     for (const [key, val] of entries) {
-        if (key === 'system_prompt' || key === 'error_trace') continue;
+        if (key === 'system_prompt' || key === 'error_trace' || key === '_codex_item_id') continue;
         const keyEl = document.createElement('span');
         keyEl.style.cssText = 'color:#64748b;white-space:nowrap;font-family:monospace';
         keyEl.textContent = key;
         grid.appendChild(keyEl);
         const valEl = document.createElement('span');
         valEl.style.cssText = 'overflow:hidden;text-overflow:ellipsis;overflow-wrap:anywhere;min-width:0';
         if (val === null || val === undefined) {
             valEl.textContent = 'null';
@@ -2060,16 +2062,23 @@ function buildCompactToolLine(type, content, ts) {
             else if (rawName === 'mcp__orchestra__compact_worker') preview = `🗜 Compact: ${parsed.name || '?'}`;
             else if (rawName === 'mcp__orchestra__list_jobs') preview = '📊 Jobs';
             else if (rawName === 'mcp__orchestra__rename_worker') preview = `✏️ ${parsed.old_name || '?'} → ${parsed.new_name || '?'}`;
             else if (rawName === 'mcp__orchestra__change_worker_model') preview = `🔄 ${parsed.name || '?'} → ${parsed.model || '?'}`;
             else if (rawName === 'mcp__orchestra__update_worker_description') preview = `✏️ ${parsed.name || '?'} — description`;
             else if (rawName === 'mcp__orchestra__merge_worker') preview = `🔀 Merge: ${parsed.name || '?'}`;
             else if (rawName === 'Glob') preview = `🔎 ${parsed.pattern || '?'}`;
             else if (rawName === 'Skill') preview = `⚡ ${parsed.skill || '?'}`;
+            else if (rawName === 'FileChange') {
+                const changes = parsed.changes || [];
+                preview = `📝 ${changes.length} file${changes.length === 1 ? '' : 's'}`;
+            }
+            else if (rawName === 'ViewImage') preview = `🖼 ${(parsed.file_path || '').split('/').pop() || 'image'}`;
+            else if (rawName === 'ImageGeneration') preview = '🎨 generating image';
+            else if (rawName === 'Sleep') preview = `⏱ ${Math.round((parsed.duration_ms || 0) / 1000)}s`;
             else if (rawName === 'mcp__orchestra__task_create') { const _pp = {0:'🔴',1:'🟠',3:'🟢'}[parsed.priority]||''; preview = `📋 New: ${_pp}"${parsed.title || '?'}"${parsed.price ? ' | '+parsed.price+' ${CUR}' : ''}`; }
             else if (rawName === 'mcp__orchestra__task_update') { const _f = Object.keys(parsed).filter(k=>k!=='par').map(k=>`${k}→${parsed[k]}`).join(', '); preview = `✏️ #${taskNum(parsed.par) || '?'}: ${_f}`; }
             else if (rawName === 'mcp__orchestra__task_list') { const _fl = [parsed.status,parsed.project,parsed.assignee].filter(Boolean).join(', '); preview = `📋 Tasks${_fl ? ' ('+_fl+')' : ''}`; }
             else if (rawName === 'mcp__orchestra__task_get') preview = `📋 #${taskNum(parsed.par) || '?'}`;
             else if (rawName === 'mcp__orchestra__payment_receive') preview = `💰 +${parsed.amount || '?'} ${CUR}`;
             else if (rawName === 'mcp__orchestra__payment_status') preview = '💰 Balance';
             else if (rawName === 'mcp__orchestra__bg_create') { const _bi = {'timer':'⏰','file':'📄','command':'🖥️','ssh':'🔗','run':'▶️'}[parsed.type]||'⚙️'; preview = `${_bi} BG: ${parsed.type||'?'} ${parsed.message ? '"'+parsed.message.slice(0,30)+'"' : ''}`; }
             else if (rawName === 'mcp__orchestra__bg_list') preview = '📊 BG Jobs';
@@ -2116,16 +2125,23 @@ function buildCompactToolLine(type, content, ts) {
         const resultSpan = document.createElement('span');
         resultSpan.className = 'compact-result shrink-0';
         resultSpan.style.color = '#475569';
 
         line.append(iconSpan, nameSpan, descSpan, previewSpan, resultSpan);
         line.dataset.compactTool = '1';
         line.dataset.toolContent = content;
         line.dataset.toolRaw = rawName;
+        try {
+            const parsed = JSON.parse(body);
+            if (parsed._codex_item_id) {
+                line.dataset.toolUseId = parsed._codex_item_id;
+                _flushCodexToolUpdates(line, parsed._codex_item_id);
+            }
+        } catch {}
 
         line.addEventListener('mouseenter', () => line.style.backgroundColor = 'rgba(30,41,59,0.5)');
         line.addEventListener('mouseleave', () => line.style.backgroundColor = '');
 
         let fullBubble = null;
         line.addEventListener('click', () => {
             if (fullBubble) {
                 fullBubble.remove();
@@ -2225,21 +2241,155 @@ function _flushPendingSubagentLogs(sourceId, targetId) {
     const pending = _pendingSubagentLogs.get(sourceId);
     if (!pending) return;
     _pendingSubagentLogs.delete(sourceId);
     for (const [evType, content] of pending) {
         appendSubagentLog(targetId, evType, content);
     }
 }
 
+let _codexThinkingLive = null;
+let _codexThinkingKey = '';
+let _codexTurnDiffBubble = null;
+const _pendingCodexToolUpdates = new Map();
+
+function _resetCodexActivityState() {
+    _removeCodexThinkingLive();
+    _codexTurnDiffBubble = null;
+    _pendingCodexToolUpdates.clear();
+}
+
+function _removeCodexThinkingLive(activity) {
+    if (!_codexThinkingLive) return;
+    if (activity && _codexThinkingLive.dataset.activity !== activity) return;
+    _codexThinkingLive.remove();
+    _codexThinkingLive = null;
+    _codexThinkingKey = '';
+}
+
+function _codexToolHost(chat, payload, anchor) {
+    const itemId = payload && payload.tool_use_id;
+    if (itemId) {
+        const exact = chat.querySelector(`[data-tool-use-id="${CSS.escape(itemId)}"]`);
+        if (exact) return exact;
+    }
+    return _findLastBefore(chat, '[data-last-tool], [data-compact-tool]', anchor);
+}
+
+function _applyCodexToolUpdate(host, type, content) {
+    if (!host) return;
+    if (type === 'tool_patch') {
+        const patch = renderCodexFileChange(content);
+        if (!patch) return;
+        const old = host.querySelector('.codex-file-change');
+        if (old) old.replaceWith(patch);
+        else host.appendChild(patch);
+        return;
+    }
+    if (host.dataset.compactTool) {
+        const result = host.querySelector('.compact-result');
+        if (result) {
+            const lastLine = String(content).trim().split('\n').pop() || 'working';
+            result.textContent = `⚡ ${lastLine.slice(0, 42)}`;
+            result.style.color = '#38bdf8';
+        }
+        return;
+    }
+    let pre = host.querySelector('.codex-live-output');
+    if (!pre) {
+        pre = document.createElement('pre');
+        pre.className = 'codex-live-output';
+        host.appendChild(pre);
+    }
+    const prefix = type === 'tool_stream' && host.dataset.toolStream === 'stdin' ? '› ' : '';
+    pre.textContent = (pre.textContent + prefix + content).slice(-20_000);
+    pre.scrollTop = pre.scrollHeight;
+}
+
+function _queueOrApplyCodexToolUpdate(chat, type, content, payload, anchor) {
+    const host = _codexToolHost(chat, payload, anchor);
+    const itemId = payload && payload.tool_use_id;
+    if (host) {
+        if (itemId) host.dataset.toolUseId = itemId;
+        if (payload && payload.stream) host.dataset.toolStream = payload.stream;
+        _applyCodexToolUpdate(host, type, content);
+        return;
+    }
+    if (!itemId) return;
+    const pending = _pendingCodexToolUpdates.get(itemId) || [];
+    pending.push([type, content, payload || {}]);
+    if (pending.length > 100) pending.shift();
+    _pendingCodexToolUpdates.set(itemId, pending);
+}
+
+function _flushCodexToolUpdates(host, itemId) {
+    if (!host || !itemId) return;
+    const pending = _pendingCodexToolUpdates.get(itemId);
+    if (!pending) return;
+    _pendingCodexToolUpdates.delete(itemId);
+    for (const [type, content, payload] of pending) {
+        if (payload.stream) host.dataset.toolStream = payload.stream;
+        _applyCodexToolUpdate(host, type, content);
+    }
+}
+
+function _renderCodexThinking(content, label) {
+    const card = document.createElement('div');
+    card.className = 'codex-activity-card codex-thinking-card';
+    const header = document.createElement('button');
+    header.className = 'codex-activity-header';
+    header.innerHTML = `<span class="codex-activity-caret">▶</span><span>${label || 'Reasoning'}</span>`;
+    const body = document.createElement('div');
+    body.className = 'codex-activity-body markdown-body';
+    body.innerHTML = DOMPurify.sanitize(marked.parse(content || ''));
+    body.style.display = 'none';
+    header.addEventListener('click', () => {
+        const expanded = body.style.display !== 'none';
+        body.style.display = expanded ? 'none' : 'block';
+        header.querySelector('.codex-activity-caret').textContent = expanded ? '▶' : '▼';
+    });
+    card.append(header, body);
+    return card;
+}
+
+function _renderCodexPlan(content) {
+    let data;
+    try { data = JSON.parse(content); } catch { data = {explanation: '', plan: []}; }
+    const card = document.createElement('div');
+    card.className = 'codex-activity-card codex-plan-card';
+    const title = document.createElement('div');
+    title.className = 'codex-plan-title';
+    title.textContent = '▦ Plan';
+    card.appendChild(title);
+    if (data.explanation) {
+        const explanation = document.createElement('div');
+        explanation.className = 'codex-plan-explanation';
+        explanation.textContent = data.explanation;
+        card.appendChild(explanation);
+    }
+    const steps = document.createElement('div');
+    steps.className = 'codex-plan-steps';
+    for (const step of data.plan || []) {
+        const row = document.createElement('div');
+        const status = String(step.status || 'pending');
+        row.className = `codex-plan-step codex-plan-${status.toLowerCase()}`;
+        const icon = status === 'completed' ? '✓' : status === 'inProgress' ? '●' : '○';
+        row.innerHTML = `<span class="codex-plan-icon">${icon}</span><span></span>`;
+        row.lastChild.textContent = step.step || '';
+        steps.appendChild(row);
+    }
+    card.appendChild(steps);
+    return card;
+}
+
 // Central renderer for all log entry types (text, tool, tool_result, stream, user_message, etc.)
 // anchor = insert before this node instead of appending — used by loadMoreLogs for prepend
 // payload = full SSE log object (carries subagent_id for sub-agent nesting)
 function addChatEntry(type, content, ts, anchor, payload) {
-    if (HIDE_THINKING && type === 'thinking') return;
+    if (HIDE_THINKING && (type === 'thinking' || type === 'thinking_stream')) return;
     // Live sub-agent output → nest inside the sub-agent accordion, not the main flow
     if ((type === 'subagent_stream' || type === 'subagent_event') && payload && payload.subagent_id) {
         appendSubagentLog(payload.subagent_id, payload.event_type || 'stream', content);
         return;
     }
     if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
     const chat = $('#chat');
     let _insertedBeforeStream = false;
@@ -2250,16 +2400,62 @@ function addChatEntry(type, content, ts, anchor, payload) {
             return chat.insertBefore(el, streamBubble);
         }
         chat.appendChild(el);
     };
 
     // Heuristic: detect base64 image payloads from tool results (e.g. screenshot tools)
     const _isBase64Image = content.includes("'type': 'image'") || content.includes('"type": "image"') || content.includes('"type":"image"') || /['"]?data['"]?\s*[:=]\s*['"][A-Za-z0-9+/=\s]{500,}['"]/.test(content);
 
+    if (type === 'thinking_stream') {
+        const activity = (payload && payload.activity) || 'reasoning';
+        const key = `${activity}:${(payload && payload.item_id) || ''}`;
+        if (!_codexThinkingLive || _codexThinkingKey !== key) {
+            _removeCodexThinkingLive();
+            _codexThinkingLive = document.createElement('div');
+            _codexThinkingLive.className = 'codex-activity-card codex-thinking-live';
+            _codexThinkingLive.dataset.activity = activity;
+            const label = document.createElement('div');
+            label.className = 'codex-live-label';
+            label.textContent = activity === 'plan' ? '▦ Planning live' : '◇ Reasoning live';
+            const body = document.createElement('div');
+            body.className = 'codex-live-thinking-body';
+            _codexThinkingLive.append(label, body);
+            _codexThinkingKey = key;
+            _insert(_codexThinkingLive);
+        }
+        const body = _codexThinkingLive.querySelector('.codex-live-thinking-body');
+        body.textContent = (body.textContent + content).slice(-30_000);
+        return;
+    }
+
+    if (type === 'tool_stream' || type === 'tool_patch') {
+        _queueOrApplyCodexToolUpdate(chat, type, content, payload, anchor);
+        return;
+    }
+
+    if (type === 'turn_diff') {
+        const patch = renderCodexFileChange({
+            changes: [{path: 'Current turn', kind: 'update', diff: content}],
+        });
+        if (!_codexTurnDiffBubble) {
+            _codexTurnDiffBubble = document.createElement('div');
+            _codexTurnDiffBubble.className = 'codex-activity-card codex-turn-diff';
+            const title = document.createElement('div');
+            title.className = 'codex-live-label';
+            title.textContent = '± Live turn diff';
+            _codexTurnDiffBubble.appendChild(title);
+            _insert(_codexTurnDiffBubble);
+        }
+        const old = _codexTurnDiffBubble.querySelector('.codex-file-change');
+        if (old && patch) old.replaceWith(patch);
+        else if (patch) _codexTurnDiffBubble.appendChild(patch);
+        return;
+    }
+
     if (_isBase64Image && type !== 'tool' && type !== 'tool_result') {
         const div = document.createElement('div');
         div.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot';
         const b64Match = content.match(/['"]?data['"]?\s*[:=]\s*['"]([A-Za-z0-9+/=\s]{500,})['"]/);
         if (b64Match) {
             const img = document.createElement('img');
             img.src = 'data:image/png;base64,' + b64Match[1].replace(/\s/g, '');
             img.style.cssText = 'max-width:100%;max-height:300px;border-radius:6px;cursor:pointer';
@@ -2384,32 +2580,87 @@ function addChatEntry(type, content, ts, anchor, payload) {
         addCopyBtn(streamBubble, finalText);
         addTimestamp(streamBubble, ts);
         streamBubble = null;
         streamContent = '';
         streamPending = '';
         return;
     }
 
+    if (type === 'thinking') {
+        _removeCodexThinkingLive('reasoning');
+        const card = _renderCodexThinking(content, '◇ Reasoning');
+        addTimestamp(card, ts);
+        _insert(card);
+        return;
+    }
+
+    if (type === 'plan') {
+        _removeCodexThinkingLive('plan');
+        const card = _renderCodexPlan(content);
+        addTimestamp(card, ts);
+        _insert(card);
+        return;
+    }
+
+    if (type === 'warning') {
+        const warning = document.createElement('div');
+        warning.className = 'codex-warning';
+        warning.innerHTML = '<span class="codex-warning-icon">⚠</span><span></span>';
+        warning.lastChild.textContent = content;
+        addTimestamp(warning, ts);
+        _insert(warning);
+        return;
+    }
+
+    if (type === 'review') {
+        let reviewData = {};
+        try { reviewData = JSON.parse(content); } catch {}
+        const review = document.createElement('div');
+        review.className = 'codex-review';
+        const phase = reviewData.phase === 'exited' ? 'Review completed' : 'Review mode';
+        review.innerHTML = `<div class="codex-review-title">◎ ${phase}</div><div class="codex-review-body"></div>`;
+        review.querySelector('.codex-review-body').textContent = reviewData.review || '';
+        addTimestamp(review, ts);
+        _insert(review);
+        return;
+    }
+
     if (type === 'status') {
         const rl = _parseRateLimitStatus(content);
         const codexReconnect = content.startsWith('codex reconnecting:');
         const codexSteer = content === 'message steered into active Codex turn';
+        const codexReroute = content.startsWith('model rerouted:');
+        const codexHook = content.startsWith('codex hook ');
+        const codexMcp = content.startsWith('codex mcp ');
+        const codexCompaction = content.includes('codex context compact');
         const badge = document.createElement('div');
         if (rl) {
             // Rate limit: trigger the global banner (live logs only, not history/initial replay)
             if (!anchor && !scrollAfterLoad) _showRateLimitBanner(selectedAgent, rl.retry, rl.max, rl.delay);
             badge.className = 'text-center text-xs py-1 text-amber-400 italic';
             badge.textContent = `⏳ Rate limit — Anthropic временно ограничил запросы, повтор ${rl.retry}/${rl.max} через ${rl.delay}с (это НЕ твой лимит подписки)`;
         } else if (codexReconnect) {
             badge.className = 'text-center text-xs py-1 text-amber-400 italic';
             badge.textContent = `🔌 Codex reconnecting — ${content.slice('codex reconnecting:'.length).trim()}`;
         } else if (codexSteer) {
             badge.className = 'text-center text-xs py-1 text-cyan-400 italic';
             badge.textContent = '↪ Message steered into the current Codex turn';
+        } else if (codexReroute) {
+            badge.className = 'text-center text-xs py-1 text-fuchsia-400 italic';
+            badge.textContent = `⇄ Codex model rerouted — ${content.slice('model rerouted:'.length).trim()}`;
+        } else if (codexHook) {
+            badge.className = 'text-center text-xs py-1 text-sky-400 italic';
+            badge.textContent = `⌁ ${content}`;
+        } else if (codexMcp) {
+            badge.className = 'text-center text-xs py-1 text-emerald-400 italic';
+            badge.textContent = `🔌 ${content}`;
+        } else if (codexCompaction) {
+            badge.className = 'text-center text-xs py-1 text-amber-300 italic';
+            badge.textContent = '🗜 Codex context compacted';
         } else {
             badge.className = 'text-center text-xs py-1 text-slate-500 italic';
             badge.textContent = `⚡ ${content}`;
         }
         addTimestamp(badge, ts);
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
         _insert(badge);
         if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
@@ -2466,17 +2717,17 @@ function addChatEntry(type, content, ts, anchor, payload) {
                     host.appendChild(prog);
                 }
                 prog.textContent = line;
                 return;  // updated in place, no new bubble
             }
             el.style.cssText += ';color:#64748b';
             el.textContent = `⏳ ${isBackground ? 'Background task' : 'Sub-agent'} "${desc}" — ${line}`;
         } else {  // subagent_end → mark the accordion done + collapse
-            const ok = !meta.status || meta.status === 'completed';
+            const ok = !meta.status || ['completed', 'shutdown'].includes(meta.status);
             const host = subId ? chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`) : null;
             const summaryText = textParts.slice(1).join(' | ').trim();
             if (host) {
                 const hdr = host.querySelector('div');
                 const noun = host.dataset.subagentKind === 'background' ? 'Background task' : 'Sub-agent';
                 if (hdr) hdr.innerHTML = `<span class="sa-caret">▶</span> ${ok ? '✅' : '❌'} <span style="color:#e2e8f0">${noun} ${ok ? 'done' : 'failed'}: "${DOMPurify.sanitize(desc)}"</span>`;
                 const prog = host.querySelector('.sa-progress');
                 if (prog) prog.remove();
@@ -2553,16 +2804,24 @@ function addChatEntry(type, content, ts, anchor, payload) {
         const icon = toolIcon(rawName);
         const short = toolShortName(rawName);
         const isOrch = rawName.startsWith('mcp__orchestra__');
 
         div.dataset.lastTool = '1';
         div.dataset.toolContent = content;
         div.dataset.toolRawName = rawName;
         div.style.cursor = 'pointer';
+        let codexItemId = '';
+        try {
+            const parsed = JSON.parse(body);
+            if (parsed._codex_item_id) {
+                codexItemId = parsed._codex_item_id;
+                div.dataset.toolUseId = codexItemId;
+            }
+        } catch {}
 
         const header = document.createElement('div');
         header.className = 'flex items-center gap-1.5 text-xs font-medium mb-1';
         header.style.color = isOrch ? '#a78bfa' : '#38bdf8';
         let toolDesc = '';
         try { toolDesc = JSON.parse(body).description || ''; } catch {}
         header.innerHTML = `${icon} ${DOMPurify.sanitize(short)}${toolDesc ? ` <span style="color:#64748b;font-weight:normal">— ${DOMPurify.sanitize(toolDesc)}</span>` : ''}`;
         div.appendChild(header);
@@ -2925,17 +3184,21 @@ function addChatEntry(type, content, ts, anchor, payload) {
                     div.appendChild(idEl);
                 }
             } catch {}
         }
         const isBashTool = rawName === 'Bash';
         if (isBashTool) {
             try {
                 let cmd = body;
-                try { const d = JSON.parse(body); cmd = d.command || body; } catch {}
+                let commandData = {};
+                try {
+                    commandData = JSON.parse(body);
+                    cmd = commandData.command || body;
+                } catch {}
                 cmd = cmd.replace(/^\/(?:usr\/)?bin\/(?:bash|zsh) -lc /, '').replace(/^["']|["']$/g, '');
                 const cmdLines = cmd.split('\n');
                 const PREVIEW_LINES = 3;
                 const previewCmd = cmdLines.slice(0, PREVIEW_LINES).join('\n');
                 const restCmd = cmdLines.slice(PREVIEW_LINES).join('\n');
                 const hasMoreCmd = cmdLines.length > PREVIEW_LINES;
                 const cmdWrap = document.createElement('div');
                 cmdWrap.className = 'diff-view';
@@ -2954,16 +3217,33 @@ function addChatEntry(type, content, ts, anchor, payload) {
                     hint.className = 'diff-file';
                     hint.dataset.role = 'bash-hint';
                     hint.dataset.count = cmdLines.length - PREVIEW_LINES;
                     hint.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
                     hint.textContent = `▼ ${cmdLines.length - PREVIEW_LINES} more lines`;
                     cmdWrap.appendChild(hint);
                 }
                 div.appendChild(cmdWrap);
+                const actions = commandData.command_actions || [];
+                if (actions.length) {
+                    const actionRow = document.createElement('div');
+                    actionRow.className = 'codex-command-actions';
+                    for (const action of actions) {
+                        const pill = document.createElement('span');
+                        pill.className = `codex-command-action codex-command-${action.type || 'unknown'}`;
+                        const actionIcon = action.type === 'read' ? '📖' :
+                            action.type === 'search' ? '🔎' :
+                            action.type === 'listFiles' ? '🗂' : '⌁';
+                        const detail = action.query || action.path || action.name || '';
+                        pill.textContent = `${actionIcon} ${action.type || 'command'}${detail ? ': ' + detail : ''}`;
+                        pill.title = action.command || '';
+                        actionRow.appendChild(pill);
+                    }
+                    div.appendChild(actionRow);
+                }
                 div.dataset.isBash = '1';
                 div.style.cursor = 'pointer';
                 let bashExpanded = false;
                 div.addEventListener('click', (e) => {
                     if (e.target.tagName === 'A') return;
                     bashExpanded = !bashExpanded;
                     const restPre = cmdWrap.querySelector('[data-role="bash-rest"]');
                     const hint = cmdWrap.querySelector('[data-role="bash-hint"]');
@@ -2971,16 +3251,51 @@ function addChatEntry(type, content, ts, anchor, payload) {
                     if (hint) hint.textContent = bashExpanded ? '▲ collapse' : `▼ ${hint.dataset.count} more lines`;
                     const resWrap = div.querySelector('[data-role="bash-result"]');
                     const resHint = div.querySelector('[data-role="bash-result-hint"]');
                     if (resWrap) resWrap.style.display = bashExpanded ? 'block' : 'none';
                     if (resHint) resHint.textContent = bashExpanded ? '▲ collapse result' : `▼ ${resHint.dataset.count} more lines`;
                 });
             } catch {}
         }
+        const isFileChangeTool = rawName === 'FileChange';
+        if (isFileChangeTool) {
+            const patch = renderCodexFileChange(body);
+            header.textContent = '📝 Applying file changes';
+            header.style.color = '#f59e0b';
+            if (patch) div.appendChild(patch);
+            div.dataset.isFileChange = '1';
+        }
+        const isViewImageTool = rawName === 'ViewImage';
+        if (isViewImageTool) {
+            try {
+                const data = JSON.parse(body);
+                const path = data.file_path || '';
+                header.textContent = `🖼 Viewing ${(path.split('/').pop() || 'image')}`;
+                const img = document.createElement('img');
+                img.src = `/api/files/raw?path=${encodeURIComponent(path)}&t=${Date.now()}`;
+                img.loading = 'lazy';
+                img.className = 'codex-tool-image';
+                img.addEventListener('click', () => openImageLightbox(img.src));
+                div.appendChild(img);
+            } catch {}
+        }
+        const isImageGenerationTool = rawName === 'ImageGeneration';
+        if (isImageGenerationTool) {
+            header.textContent = '🎨 Generating image';
+            header.style.color = '#f472b6';
+        }
+        const isSleepTool = rawName === 'Sleep';
+        if (isSleepTool) {
+            try {
+                const data = JSON.parse(body);
+                header.textContent = `⏱ Waiting ${((data.duration_ms || 0) / 1000).toFixed(1)}s`;
+                header.style.color = '#94a3b8';
+            } catch {}
+        }
         const isAgentTool = rawName === 'Agent';
         if (isAgentTool) {
             try {
                 const d = JSON.parse(body);
                 const desc = d.description || '';
                 const prompt = d.prompt || '';
                 header.textContent = '🤖 Agent';
                 header.style.color = '#a78bfa';
@@ -3076,17 +3391,22 @@ function addChatEntry(type, content, ts, anchor, payload) {
                 const moreEl = diffEl.querySelector('.diff-file[style*="cursor"]');
                 if (restEl && moreEl) {
                     const showing = restEl.style.display !== 'none';
                     restEl.style.display = showing ? 'none' : 'block';
                     const restCount = moreEl.dataset.count || '0';
                     moreEl.textContent = showing ? `▼ ${restCount} more lines` : `▲ collapse`;
                 }
             });
-        } else if (!isProgress && !isSendMsg && !isGrepTool && !isBashTool && !isAgentTool && !isSpawnWorker && !isWebSearchCall && !isToolSearchCall && !isBugReport && !isWebFetch && !isSendFile && !isOrchSimple && !isGlob && !isSkill && !isYougile) {
+        } else if (!isProgress && !isSendMsg && !isGrepTool && !isBashTool &&
+                   !isAgentTool && !isSpawnWorker && !isWebSearchCall &&
+                   !isToolSearchCall && !isBugReport && !isWebFetch &&
+                   !isSendFile && !isOrchSimple && !isGlob && !isSkill &&
+                   !isYougile && !isFileChangeTool && !isViewImageTool &&
+                   !isImageGenerationTool && !isSleepTool) {
             let _inputJsonRendered = false;
             if (body) {
                 try {
                     const _inputParsed = JSON.parse(body);
                     if (_inputParsed && typeof _inputParsed === 'object' && !Array.isArray(_inputParsed)) {
                         const gridWrap = document.createElement('div');
                         gridWrap.className = 'text-xs opacity-80 tool-body';
                         gridWrap.style.cssText = 'margin-top:2px';
@@ -3123,20 +3443,81 @@ function addChatEntry(type, content, ts, anchor, payload) {
                     if (tb && tb.dataset.full) tb.textContent = expanded ? tb.dataset.full : tb.dataset.preview;
                     const hint = div.querySelector('[data-role="expand-hint"]');
                     if (hint) hint.style.display = expanded ? 'none' : 'block';
                     const rb = div.querySelector('.result-body');
                     if (rb && rb.dataset.full) rb.innerHTML = '📎 ' + DOMPurify.sanitize(expanded ? rb.dataset.full : rb.dataset.preview, {ADD_ATTR: ['target']});
                 });
             }
         }
+        if (codexItemId) _flushCodexToolUpdates(div, codexItemId);
     }
     else if (type === 'tool_result') {
         const chat = $('#chat');
         const lastTool = _findLastBefore(chat, '[data-last-tool]', anchor);
+        if (lastTool) {
+            const liveOutput = lastTool.querySelector('.codex-live-output');
+            if (liveOutput) liveOutput.remove();
+            if (lastTool.dataset.isFileChange) {
+                let data = {};
+                try { data = JSON.parse(content); } catch {}
+                const header = lastTool.querySelector('.flex.items-center');
+                const ok = !data.status || data.status === 'completed';
+                if (header) {
+                    header.textContent = `${ok ? '✅' : '❌'} File changes ${ok ? 'applied' : 'failed'}${data.files != null ? ` · ${data.files} file${data.files === 1 ? '' : 's'}` : ''}`;
+                    header.style.color = ok ? '#4ade80' : '#f87171';
+                }
+                delete lastTool.dataset.lastTool;
+                addTimestamp(lastTool, ts);
+                return;
+            }
+            if (lastTool.dataset.toolRawName === 'ImageGeneration') {
+                let data = {};
+                try { data = JSON.parse(content); } catch {}
+                const header = lastTool.querySelector('.flex.items-center');
+                if (header) {
+                    header.textContent = data.status === 'failed' ? '❌ Image generation failed' : '✅ Image generated';
+                    header.style.color = data.status === 'failed' ? '#f87171' : '#f472b6';
+                }
+                if (data.saved_path) {
+                    const img = document.createElement('img');
+                    img.src = `/api/files/raw?path=${encodeURIComponent(data.saved_path)}&t=${Date.now()}`;
+                    img.loading = 'lazy';
+                    img.className = 'codex-tool-image';
+                    img.addEventListener('click', () => openImageLightbox(img.src));
+                    lastTool.appendChild(img);
+                }
+                if (data.revised_prompt) {
+                    const prompt = document.createElement('div');
+                    prompt.className = 'codex-image-prompt';
+                    prompt.textContent = data.revised_prompt;
+                    lastTool.appendChild(prompt);
+                }
+                delete lastTool.dataset.lastTool;
+                addTimestamp(lastTool, ts);
+                return;


## LATER FIX 376be1c273 (1.0 days later): fix: hide successful codex MCP startup noise
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

fix: hide successful codex MCP startup noise


diff --git a/app/backend_codex.py b/app/backend_codex.py
index 6428f6318..5ab63653f 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -729,16 +729,18 @@ class CodexBackend:
             details = params.get("details")
             if details:
                 content = f"{content}\n{details}"
             return [AgentEvent("warning", content)]
 
         if method == "mcpServer/startupStatus/updated":
             name = params.get("name") or "unknown"
             status = params.get("status") or "unknown"
+            if status in ("starting", "ready"):
+                return []
             detail = params.get("error") or params.get("failureReason") or ""
             content = f"codex mcp {name}: {status}"
             if detail:
                 content = f"{content} — {detail}"
             event_type = "warning" if status in ("failed", "cancelled") else "status"
             return [AgentEvent(event_type, content)]
 
         if method in ("hook/started", "hook/completed"):
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 15984a7c8..7b869115c 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2687,16 +2687,17 @@ function addChatEntry(type, content, ts, anchor, payload) {
         _insert(review);
         return;
     }
 
     if (type === 'status') {
         // precompact timer scheduled/cancelled = internal housekeeping noise, never show in chat
         if (content && content.startsWith('precompact timer')) return;
         if (/^codex hook .+: (?:running|started|completed)(?: · \d+ms)?$/i.test(content || '')) return;
+        if (/^codex mcp .+: (?:starting|ready)$/i.test(content || '')) return;
         const rl = _parseRateLimitStatus(content);
         const codexReconnect = content.startsWith('codex reconnecting:');
         const codexSteer = content === 'message steered into active Codex turn';
         const codexReroute = content.startsWith('model rerouted:');
         const codexHook = content.startsWith('codex hook ');
         const codexMcp = content.startsWith('codex mcp ');
         const codexCompaction = content.includes('codex context compact');
         const badge = document.createElement('div');
diff --git a/tests/test_backend_codex.py b/tests/test_backend_codex.py
index 26cad998d..51c951c77 100644
--- a/tests/test_backend_codex.py
+++ b/tests/test_backend_codex.py
@@ -459,17 +459,17 @@ def test_file_change_exposes_unified_diff_and_patch_updates():
     assert started[0].metadata["tool_name"] == "FileChange"
     assert json.loads(started[0].content.split(": ", 1)[1])["changes"][0]["diff"]
     assert patch[0].type == "tool_patch"
     assert patch[0].metadata["tool_use_id"] == "patch-1"
     assert completed[0].type == "tool_result"
     assert json.loads(completed[0].content)["status"] == "completed"
 
 
-def test_reasoning_plan_warning_and_compaction_telemetry_are_visible():
+def test_reasoning_plan_warning_compaction_and_mcp_failure_telemetry():
     backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
 
     reasoning = backend._convert_notification({
         "method": "item/reasoning/summaryTextDelta",
         "params": {
             "threadId": "thread-1",
             "turnId": "turn-1",
             "itemId": "reason-1",
@@ -501,34 +501,54 @@ def test_reasoning_plan_warning_and_compaction_telemetry_are_visible():
     warning = backend._convert_notification({
         "method": "warning",
         "params": {"threadId": "thread-1", "message": "Transport is degraded"},
     })
     compacted = backend._convert_notification({
         "method": "thread/compacted",
         "params": {"threadId": "thread-1"},
     })
+    mcp_starting = backend._convert_notification({
+        "method": "mcpServer/startupStatus/updated",
+        "params": {
+            "threadId": "thread-1",
+            "name": "orchestra",
+            "status": "starting",
+        },
+    })
     mcp_ready = backend._convert_notification({
         "method": "mcpServer/startupStatus/updated",
         "params": {
             "threadId": "thread-1",
             "name": "orchestra",
             "status": "ready",
         },
     })
+    mcp_failed = backend._convert_notification({
+        "method": "mcpServer/startupStatus/updated",
+        "params": {
+            "threadId": "thread-1",
+            "name": "orchestra",
+            "status": "failed",
+            "failureReason": "process exited",
+        },
+    })
 
     assert reasoning[0].type == "thinking_stream"
     assert reasoning[0].metadata["activity"] == "reasoning"
     assert plan_delta[0].type == "thinking_stream"
     assert plan_delta[0].metadata["activity"] == "plan"
     assert plan[0].type == "plan"
     assert json.loads(plan[0].content)["plan"][1]["status"] == "inProgress"
     assert warning[0].type == "warning"
     assert compacted[0].content == "codex context compacted"
-    assert mcp_ready[0].content == "codex mcp orchestra: ready"
+    assert mcp_starting == []
+    assert mcp_ready == []
+    assert mcp_failed[0].type == "warning"
+    assert mcp_failed[0].content == "codex mcp orchestra: failed — process exited"
 
 
 def test_long_mcp_arguments_remain_valid_structured_json():
     backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
     events = backend._convert_notification({
         "method": "item/started",
         "params": {
             "item": {
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 53105e451..74650a9dc 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -205,16 +205,29 @@ def _open_tool_fixture_page(browser: Browser) -> Page:
             eventSource = null;
         }
         window.compactMode = false;
         document.querySelector('#chat').innerHTML = '';
     }""")
     return page
 
 
+def test_codex_successful_mcp_startup_status_is_hidden(
+    dashboard_browser: Browser,
+):
+    page = _open_tool_fixture_page(dashboard_browser)
+    page.evaluate("""() => {
+        addChatEntry('status', 'codex mcp orchestra: starting');
+        addChatEntry('status', 'codex mcp orchestra: ready');
+    }""")
+
+    expect(page.locator("#chat").locator("text=codex mcp")).to_have_count(0)
+    page.close()
+
+
 def test_codex_web_search_renders_queries_without_transport_json(
     dashboard_browser: Browser,
 ):
     page = _open_tool_fixture_page(dashboard_browser)
     page.evaluate("""() => {
         addChatEntry(
             'tool',
             'WebSearch: {"query":"","action":null,"_codex_item_id":"web-1"}',


## LATER FIX bb42ed21e0 (6.0 days later): fix: stop agent ack loops and restore Codex previews
lines of origin it changed/deleted: 3
(code only, capped 400 lines)

fix: stop agent ack loops and restore Codex previews

Squashed commits:
- fix: stop agent ack loops and restore Codex previews
- fix: abort Claude compact on subscription limits


diff --git a/app/session.py b/app/session.py
index 1aabc7793..5dbeaa8e4 100644
--- a/app/session.py
+++ b/app/session.py
@@ -40,16 +40,43 @@ def _is_terminal_subscription_limit(text: str) -> bool:
         "hit your session",
         "hit your usage limit",
         "usage limit",
         "monthly spend limit",
         "weekly usage limit",
         "weekly limit",
     ))
 
+
+def _claude_subscription_limit_active() -> bool:
+    try:
+        from app.routes.system import _usage_cache
+        usage = _usage_cache.get("data") or {}
+    except Exception:
+        return False
+    now = datetime.now(timezone.utc)
+    for name in ("five_hour", "seven_day"):
+        window = usage.get(name) or {}
+        utilization = window.get("utilization")
+        if not isinstance(utilization, (int, float)) or utilization < 100:
+            continue
+        resets_at = window.get("resets_at")
+        if not resets_at:
+            return True
+        try:
+            reset = datetime.fromisoformat(str(resets_at).replace("Z", "+00:00"))
+            if reset.tzinfo is None:
+                reset = reset.replace(tzinfo=timezone.utc)
+            if reset > now:
+                return True
+        except (TypeError, ValueError):
+            return True
+    return False
+
+
 import concurrent.futures
 _DB_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None
 
 
 def _db_executor() -> concurrent.futures.ThreadPoolExecutor:
     """Dedicated pool for DB writes so logs/persists don't contend with git ops
     on the default executor (used by asyncio.to_thread)."""
     global _DB_EXECUTOR
@@ -744,17 +771,16 @@ class AgentSession:
             self._turns.handle_turn_end(event)
         elif event.type == "error":
             # rate_limit → single retry-status log (skip raw error to avoid duplicate
             # "model error: rate_limit" + "rate limited — retry" on one event)
             if "rate_limit" in event.content:
                 # Terminal subscription/usage limits — never retry
                 if self._session_limit_hit or _is_terminal_subscription_limit(event.content):
                     self._log("error", "⏳ subscription limit — ждём сброса квоты. НЕ ретраим")
-                    self._session_limit_hit = False
                 elif self._rate_limit_retries < self.RATE_LIMIT_MAX_RETRIES:
                     self._rate_limit_retries += 1
                     delay = self.RATE_LIMIT_DELAY * self._rate_limit_retries
                     self._log("status", f"⏳ rate limit (Anthropic сервер) — повтор через {delay}s ({self._rate_limit_retries}/{self.RATE_LIMIT_MAX_RETRIES})")
                     self._spawn_bg(self._rate_limit_retry(delay))
                 else:
                     self._log("error", f"rate limit — gave up after {self.RATE_LIMIT_MAX_RETRIES} retries")
             else:
@@ -967,21 +993,33 @@ class AgentSession:
         COMPACT_RETRY_DELAY = 30
         COMPACT_MIN_SUMMARY_LEN = 200
         _GARBAGE_PATTERNS = ["rate limit", "rate_limit", "api error", "overloaded", "temporarily limiting", "server error", "session limit", "hit your session"]
 
         if self._compacting:
             return {"ok": False, "error": "compact already in progress"}
         if self.status == AgentStatus.RUNNING:
             return {"ok": False, "error": "cannot compact while agent is running"}
+        if _claude_subscription_limit_active():
+            error = "Claude subscription limit active; compact postponed until quota reset"
+            self._log("error", error)
+            return {"ok": False, "error": error}
+        self._session_limit_hit = False
         self._compacting = True
         before_pct = self._last_context.get("percentage", 0)
         pre_compact_session_id = self.session_id
         self._log("status", f"compact started (context {before_pct}%, pre_session={pre_compact_session_id})")
 
+        def abort_compact(error: str) -> dict:
+            self.session_id = pre_compact_session_id
+            self._compacting = False
+            if self._pending_messages:
+                self._spawn_bg(self._flush_pending())
+            return {"ok": False, "error": error, "before_pct": before_pct}
+
         if self._listen_task and not self._listen_task.done():
             self._listen_task.cancel()
             try:
                 await self._listen_task
             except asyncio.CancelledError:
                 pass
             except Exception as e:
                 logger.warning(f"[{self.name}] listen task failed during compact: {e}")
@@ -1017,56 +1055,60 @@ class AgentSession:
                     await backend.disconnect()
                 except Exception:
                     pass
                 self._backend = None
                 if attempt < COMPACT_MAX_RETRIES:
                     self._log("status", f"compact retry in {COMPACT_RETRY_DELAY * attempt}s...")
                     await asyncio.sleep(COMPACT_RETRY_DELAY * attempt)
                     continue
-                self._compacting = False
-                return {"ok": False, "error": last_error, "before_pct": before_pct}
+                return abort_compact(last_error)
             finally:
                 try:
                     await backend.disconnect()
                 except Exception:
                     pass
                 self._backend = None
 
             summary = "".join(summary_parts).strip()
 
+            summary_lower = summary.lower()
+            terminal_limit = (
+                len(summary) < COMPACT_MIN_SUMMARY_LEN
+                and summary.count("\n") <= 2
+                and _is_terminal_subscription_limit(summary)
+            )
+            provider_error = (
+                len(summary) < COMPACT_MIN_SUMMARY_LEN
+                and summary.count("\n") <= 2
+                and any(pattern in summary_lower for pattern in _GARBAGE_PATTERNS)
+            )
             if not summary:
                 last_error = "empty summary"
+            elif terminal_limit:
+                last_error = "Claude subscription limit active; compact aborted"
+            elif provider_error:
+                last_error = "provider error returned instead of compact summary"
+            else:
+                last_error = ""
+
+            if last_error:
                 self._log("error", f"compact attempt {attempt}/{COMPACT_MAX_RETRIES}: {last_error}")
-                if attempt < COMPACT_MAX_RETRIES:
+                self.session_id = pre_compact_session_id
+                if not terminal_limit and attempt < COMPACT_MAX_RETRIES:
                     self._log("status", f"compact retry in {COMPACT_RETRY_DELAY * attempt}s...")
                     await asyncio.sleep(COMPACT_RETRY_DELAY * attempt)
                     continue
-                self._compacting = False
-                return {"ok": False, "error": last_error, "before_pct": before_pct}
+                return abort_compact(last_error)
 
             if attempt > 1:
                 self._log("status", f"compact succeeded on attempt {attempt}")
             break
-        self.last_summary = _bounded_summary(summary)
-        self._persist()
-        await self._drain_persist()
-        self._log("text", f"📋 **Compact summary:**\n\n{summary}")
 
         preamble = PREAMBLE.format(summary=summary)
-        if pre_compact_session_id:
-            self.session_id_history.append({
-                "session_id": pre_compact_session_id,
-                "runtime": self.backend_type,
-                "model": self.model,
-                "compacted_at": datetime.now(timezone.utc).isoformat(),
-                "context_pct": before_pct,
-            })
-            MAX_HISTORY = 10
-            self.session_id_history = self.session_id_history[-MAX_HISTORY:]
         self._compact_ack_event = asyncio.Event()
         ack_event = self._compact_ack_event
         try:
             async with self._lifecycle_lock:
                 self._manually_interrupted = False
                 self._did_report = False
                 self._turns.bump_turn_gen()
                 self._compact_ack_gen = self._turn_gen
@@ -1080,26 +1122,48 @@ class AgentSession:
                 await backend.send(preamble + "Acknowledge briefly.")
 
             try:
                 await asyncio.wait_for(ack_event.wait(), timeout=60)
             except asyncio.TimeoutError:
                 self._log("error", "compact ack turn did not complete (60s)")
                 # stop the still-running ack turn so it can't interleave with the next send
                 await self._disconnect_backend()
+                self.session_id = pre_compact_session_id
                 self.status = AgentStatus.IDLE
                 self._persist()
                 return {"ok": False, "error": "ack turn did not complete", "before_pct": before_pct}
+            if self._session_limit_hit:
+                error = "Claude subscription limit hit during compact acknowledgement"
+                self._log("error", error)
+                await self._disconnect_backend()
+                self.session_id = pre_compact_session_id
+                self.status = AgentStatus.IDLE
+                self._persist()
+                return {"ok": False, "error": error, "before_pct": before_pct}
         finally:
             self._compact_ack_event = None
             self._compact_ack_gen = -1
             self._compacting = False
             if self._pending_messages:
                 self._spawn_bg(self._flush_pending())
 
+        self.last_summary = _bounded_summary(summary)
+        if pre_compact_session_id:
+            self.session_id_history.append({
+                "session_id": pre_compact_session_id,
+                "runtime": self.backend_type,
+                "model": self.model,
+                "compacted_at": datetime.now(timezone.utc).isoformat(),
+                "context_pct": before_pct,
+            })
+            self.session_id_history = self.session_id_history[-10:]
+        self._persist()
+        await self._drain_persist()
+        self._log("text", f"📋 **Compact summary:**\n\n{summary}")
         after_pct = self._last_context.get("percentage", 0)
         self._log("status", f"compact done: {before_pct}% → {after_pct}%")
         return {"ok": True, "before_pct": before_pct, "after_pct": after_pct, "summary_chars": len(summary), "summary": summary}
 
     async def _notify_scope_idle(self) -> None:
         # wired callback (set by tg_bridge.start_bridge) — session does not import tg_bridge
         if on_scope_idle is None:
             return
diff --git a/app/session_turns.py b/app/session_turns.py
index d2920887a..b81d88db1 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -77,26 +77,28 @@ class TurnManager:
         """Новый ход начался — инвалидируем отложенный авто-репорт прошлого хода."""
         self.s._turn_gen += 1
         self.cancel_auto_report()
 
     def fire_auto_report(self) -> None:
         """Send auto-report to parent immediately when worker goes idle.
         Orchestrators don't auto-report — they reply to user directly.
         Skipped if worker already sent explicit send_message, has pending messages,
-        or was interrupted/stopped by user.
+        completed a successful silent turn, or was interrupted/stopped by user.
 
         Without this, silent workers (those that don't call send_message) would
         leave the orchestrator waiting forever for a signal that never comes.
         """
         s = self.s
         if s.is_orchestrator or not s.on_idle or s._did_report or s._manually_interrupted:
             return
         if s._pending_messages or s._compacting:
             return
+        if s._last_turn_ok and not s._turn_logs:
+            return
         # An unparented worker started directly from dashboard/TG has nobody to report
         # to. A parented child must still report: parent_name survives service restarts
         # even when the transient last_task_sender metadata does not.
         if not s.last_task_sender and not s.parent_name:
             return
         last_texts = s._turn_logs[-5:] if s._turn_logs else []
         stop_reason = s._last_stop_reason
 
@@ -116,23 +118,27 @@ class TurnManager:
 
     def handle_turn_end(self, event: AgentEvent) -> None:
         s = self.s
         meta = event.metadata
         s._turn_start = 0
         ok, sr, nt = s._cost.apply_turn_result(meta)
         s._cost.update_context_from_turn(meta)
         s._spawn_bg(s._refresh_context_from_api())
+        subscription_limited = s._session_limit_hit
 
         if not ok:
             # CLI injects [ede_diagnostic] telemetry on interrupt — cosmetic noise, not real errors
             errors = [e for e in (meta.get("errors") or []) if not str(e).startswith("[ede_diagnostic]")]
-            if errors:
+            if errors and not (
+                subscription_limited
+                and all(str(error).lower() == "rate_limit" for error in errors)
+            ):
                 s._log("error", f"turn FAILED: {'; '.join(str(e) for e in errors)}")
-            else:
+            elif not subscription_limited:
                 s._log("status", f"turn interrupted ({sr})")
 
         # max_turns: SDK hit per-turn ceiling — auto-continue so agent doesn't stop mid-task.
         # tool_use is NOT included: it means external interrupt (stop/kill/permission), not agent wanting more.
         if sr in ("error_max_turns", "max_turns") and ok:
             if s._auto_continue_count >= s.AUTO_CONTINUE_MAX:
                 logger.warning(f"[{s.name}] auto-continue cap ({s.AUTO_CONTINUE_MAX}) reached — staying idle")
                 s._log("error", f"auto-continue cap reached ({s.AUTO_CONTINUE_MAX}) — agent stuck at {sr}")
@@ -169,16 +175,17 @@ class TurnManager:
             return f"{v:.4f}" if v < 0.01 and v > 0 else f"{v:.2f}"
         limits_s = _format_limits()
         s._log("status", f"turn ended ({sr}, {nt} turns, ${_fc(s._turn_cost)} turn, ${_fc(s._context_cost)} ctx, ${_fc(s._session_cost)} session, ${_fc(s.cost_usd)} total {ctx_s}){limits_s}")
 
         self.finish_turn_status()
         self.after_turn_idle_actions(
             live_pct,
             allow_auto_report=server_error_retry is None,
+            allow_precompact=not subscription_limited,
         )
         if server_error_retry is not None:
             s._spawn_bg(s._retry_after_server_error(*server_error_retry))
 
     def finish_turn_status(self) -> None:
         """Set IDLE or WAITING based on bg jobs, then persist."""
         s = self.s
         from app.bg_jobs import bg_manager
@@ -187,27 +194,30 @@ class TurnManager:
             s._log("status", "waiting for bg jobs")
         else:
             s.status = AgentStatus.IDLE
             s.progress_pct = 0
             s.progress_status = ""
         s._persist()
 
     def after_turn_idle_actions(
-            self, live_pct: int, *, allow_auto_report: bool = True) -> None:
+            self, live_pct: int, *, allow_auto_report: bool = True,
+            allow_precompact: bool = True) -> None:
         """Post-turn actions: compact ack, scope idle, auto-compact, auto-report, flush/hibernate."""
         s = self.s
         if s._compact_ack_event is not None and s._turn_gen == s._compact_ack_gen:
             s._compact_ack_event.set()
 
-        s._schedule_precompact_timer(live_pct)
+        if allow_precompact:
+            s._schedule_precompact_timer(live_pct)
         s._spawn_bg(s._notify_scope_idle())
 
         if (
-            live_pct > 90
+            allow_precompact
+            and live_pct > 90
             and s.backend_type != "codex"
             and not s.is_orchestrator
             and not s._compacting
         ):
             # Workers auto-compact to stay operational; orchestrators are left for
             # the user to compact manually since they hold long-running session state.
             # Codex app-server compacts the current thread natively; replacing that
             # thread with Orchestra's generic handoff loses native thread continuity.
diff --git a/app/static/css/style.css b/app/static/css/style.css
index 27eab5825..d7679fc65 100644
--- a/app/static/css/style.css
+++ b/app/static/css/style.css
@@ -207,16 +207,17 @@ textarea:disabled, button:disabled { opacity: 0.4; cursor: not-allowed; }
 .codex-search-index {
     color: #38bdf8;
     font-family: 'JetBrains Mono', monospace;
     font-size: 8px;
     font-weight: 700;
 }
 .codex-search-detail { color: #64748b; font-size: 10px; }
 .codex-tool-image { display: block; max-width: 100%; max-height: 260px; margin-top: 7px; border: 1px solid #273548; border-radius: 7px; object-fit: contain; cursor: zoom-in; background: #080d14; }
+.codex-tool-image-error { min-height: 44px; padding: 12px; color: #f87171; font-size: 12px; }
 .codex-image-prompt { margin-top: 5px; color: #64748b; font-size: 10px; line-height: 1.4; }
 .codex-turn-diff { border-left-color: #f59e0b; }
 .codex-diff-file { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
 .codex-change-kind { padding: 1px 5px; border-radius: 999px; font-size: 8px; text-transform: uppercase; }
 .codex-change-add { color: #4ade80; background: rgba(34,197,94,.12); }
 .codex-change-delete { color: #f87171; background: rgba(239,68,68,.12); }
 .codex-change-update { color: #fbbf24; background: rgba(245,158,11,.12); }
 .codex-diff-more { cursor: pointer; text-align: center; color: #38bdf8; }
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 3c72d0748..6029c412f 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -3347,18 +3347,26 @@ function addChatEntry(type, content, ts, anchor, payload) {
         const isViewImageTool = rawName === 'ViewImage';
         if (isViewImageTool) {
             try {
                 const data = JSON.parse(body);
                 const path = data.file_path || '';
                 header.textContent = `🖼 Viewing ${(path.split('/').pop() || 'image')}`;
                 const img = document.createElement('img');
                 img.src = `/api/files/raw?path=${encodeURIComponent(path)}&t=${Date.now()}`;
-                img.loading = 'lazy';
+                img.loading = 'eager';
                 img.className = 'codex-tool-image';
+                img.alt = path.split('/').pop() || 'Viewed image';
+                img.addEventListener('error', () => {
+                    img.classList.add('codex-tool-image-error');
+                    img.alt = 'Image unavailable';
+                });
+                img.addEventListener('load', () => {
+                    img.classList.remove('codex-tool-image-error');
+                });
                 img.addEventListener('click', () => openImageLightbox(img.src));
                 div.appendChild(img);


## LATER FIX e7d521de52 (37.0 days later): fix: preserve generated images across chat switches
lines of origin it changed/deleted: 19
(code only, capped 400 lines)

fix: preserve generated images across chat switches


diff --git a/app/db.py b/app/db.py
index ee220ec16..515164c99 100644
--- a/app/db.py
+++ b/app/db.py
@@ -1945,26 +1945,77 @@ def get_logs_before(session_id: str, before_id: int, limit: int = 500, max_bytes
             size = len((d.get("content") or "").encode())
             if max_bytes and out and used + size > max_bytes:
                 break
             out.append(d)
             used += size
         return list(reversed(out))
 
 
-_SYNC_COLS = "id, session_id, ts, type, content, event_id"
+_SYNC_COLS = (
+    "id, session_id, ts, type, content, event_id, "
+    "tool_use_id, tool_name, tool_is_error"
+)
+
+
+def _project_image_generation_result(row: dict, cap: int) -> dict | None:
+    """Return the useful, bounded part of a persisted ImageGeneration result.
+
+    The PNG already lives at ``saved_path``. Shipping its multi-megabyte base64 field in
+    dashboard history both blows the row cap and cuts off the path/prompt stored after it.
+    """
+    if row.get("type") != "tool_result" or row.get("tool_name") != "ImageGeneration":
+        return None
+    source = row.get("content") or ""
+    try:
+        data = json.loads(source)
+    except (json.JSONDecodeError, TypeError):
+        return None
+    if not isinstance(data, dict) or not any(
+        key in data for key in ("saved_path", "revised_prompt", "status")
+    ):
+        return None
+
+    projected = {
+        "status": str(data.get("status") or ""),
+        "saved_path": str(data.get("saved_path") or ""),
+        "revised_prompt": str(data.get("revised_prompt") or ""),
+    }
+    encoded = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
+    if cap and len(encoded.encode()) > cap:
+        # Keep valid JSON and the path even when an abnormal revised prompt alone exceeds
+        # the row cap. The ordinary byte-prefix truncation would make JSON unparsable again.
+        prompt = projected["revised_prompt"].encode()
+        projected["revised_prompt"] = ""
+        base_size = len(json.dumps(
+            projected, ensure_ascii=False, separators=(",", ":"),
+        ).encode())
+        available = max(0, cap - base_size)
+        projected["revised_prompt"] = prompt[:available].decode(errors="ignore")
+        encoded = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
+    if cap and len(encoded.encode()) > cap:
+        return None
+
+    row["content"] = encoded
+    row["projection"] = "image_generation"
+    row["source_bytes"] = len(source.encode())
+    row.pop("trunc", None)
+    return row
 
 
 def _cap_content(row: dict, cap: int) -> dict:
     """Обрезать content до cap БАЙТ (не символов) и пометить обрезку.
 
     Байты, а не символы: бюджет клиентского зеркала считается в байтах, а кириллица
     в UTF-8 даёт 2 байта на символ — по символам потолок уехал бы вдвое. Срез может
     разрубить символ пополам, поэтому errors="ignore".
     """
+    projected = _project_image_generation_result(row, cap)
+    if projected is not None:
+        return projected
     raw = (row.get("content") or "").encode()
     if len(raw) <= cap:
         return row
     row["content"] = raw[:cap].decode(errors="ignore")
     row["trunc"] = len(raw)  # исходная длина в байтах — её показывает кнопка «загрузить целиком»
     return row
 
 
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 3cd867a32..178ea773a 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1185,16 +1185,17 @@ async function loadMoreLogs() {
                 if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
                     chatLogs[selectedAgent].firstId = l.id;
                 }
             }
         } finally {
             _chatTrimLimit = previousTrimLimit;
             _replayingHistory = false;
         }
+        await _storePut(logs);
         chat.scrollTop = chat.scrollHeight - oldHeight;
         // Full page (500) returned → more may exist, re-add button. Fewer → reached the start.
         if (logs.length >= 500) _addLoadMoreBtn();
     } catch (e) {
         if (btn) { btn.textContent = '▲ Load 500 more'; btn.style.pointerEvents = ''; }
         console.warn('loadMoreLogs error:', e);
     }
 }
@@ -2289,23 +2290,43 @@ function _prependHistory(name, scope, rows) {
 // поэтому нужен второй.
 function _afterPaint(fn) {
     if (typeof requestAnimationFrame !== 'function') return setTimeout(fn, 0);
     requestAnimationFrame(() => requestAnimationFrame(fn));
 }
 
 // Кладём в зеркало то, что уже скачали и показали. Отдельно от _storeSync: тот ходит
 // за инкрементом по watermark, а здесь строки СТАРШЕ watermark, и трогать отметку нельзя.
+function _compactImageGenerationLogRow(row) {
+    if (row?.type !== 'tool_result' || row?.tool_name !== 'ImageGeneration') return row;
+    try {
+        const data = JSON.parse(row.content || '{}');
+        if (!data.saved_path && !data.revised_prompt && !data.status) return row;
+        const compact = {
+            ...row,
+            content: JSON.stringify(_imageGenerationProjection(data)),
+            projection: 'image_generation',
+            source_bytes: Number(row.source_bytes) || new Blob([row.content || '']).size,
+        };
+        delete compact.trunc;
+        return compact;
+    } catch {
+        return row;
+    }
+}
+
 async function _storePut(rows) {
     const db = await _storeOpen();
     if (!db || !rows || !rows.length) return;
     try {
         await _storeTx('readwrite', ['logs'], (tx) => {
             const logs = tx.objectStore('logs');
-            for (const row of rows) if (Number.isFinite(row.id)) logs.put(row);
+            for (const row of rows) {
+                if (Number.isFinite(row.id)) logs.put(_compactImageGenerationLogRow(row));
+            }
         });
     } catch (e) { _storeDisable('не пишется в IndexedDB', e); }
 }
 
 // Промах зеркала: тянем историю обычным маршрутом. Он отдаёт application/json, который
 // nginx жмёт, — те же 100 сообщений едут в 5 раз меньшим объёмом, чем через SSE (D1).
 //
 // СТРАНИЦА БЕРЁТСЯ ОДНИМ ЗАПРОСОМ. Раньше здесь стояла порция в 25 строк, а остальные три
@@ -4296,16 +4317,79 @@ function _flushCodexToolUpdates(host, itemId) {
     if (!pending) return;
     _pendingCodexToolUpdates.delete(itemId);
     for (const [type, content, payload] of pending) {
         if (payload.stream) host.dataset.toolStream = payload.stream;
         _applyCodexToolUpdate(host, type, content);
     }
 }
 
+function _imageGenerationProjection(data) {
+    return {
+        status: String(data?.status || ''),
+        saved_path: String(data?.saved_path || ''),
+        revised_prompt: String(data?.revised_prompt || ''),
+    };
+}
+
+function _completeImageGenerationTool(host, data) {
+    const projected = _imageGenerationProjection(data);
+    const header = host.querySelector('.flex.items-center');
+    const failed = projected.status === 'failed';
+    if (header) {
+        header.textContent = failed ? '❌ Image generation failed' : '✅ Image generated';
+        header.style.color = failed ? '#f87171' : '#f472b6';
+    }
+    host.querySelectorAll('.codex-tool-image, .codex-image-prompt').forEach(el => el.remove());
+    if (projected.saved_path) {
+        const img = document.createElement('img');
+        img.src = `/api/files/raw?path=${encodeURIComponent(projected.saved_path)}&t=${Date.now()}`;
+        img.loading = 'lazy';
+        img.className = 'codex-tool-image';
+        img.addEventListener('click', () => openImageLightbox(img.src));
+        host.appendChild(img);
+    }
+    if (projected.revised_prompt) {
+        const prompt = document.createElement('div');
+        prompt.className = 'codex-image-prompt';
+        prompt.textContent = projected.revised_prompt;
+        host.appendChild(prompt);
+    }
+    return projected;
+}
+
+async function _restoreImageGenerationResult(host, payload) {
+    const logId = Number(payload?.id);
+    if (!host || !Number.isFinite(logId) || host.dataset.imageRestore === 'loading') return;
+    host.dataset.imageRestore = 'loading';
+    const header = host.querySelector('.flex.items-center');
+    if (header) header.textContent = '↻ Restoring generated image';
+    try {
+        const row = await api(`/api/logs/${logId}`);
+        const data = JSON.parse(row.content || '{}');
+        const projected = _imageGenerationProjection(data);
+        if (host.isConnected) _completeImageGenerationTool(host, projected);
+        const compactRow = {
+            ...row,
+            content: JSON.stringify(projected),
+            projection: 'image_generation',
+            source_bytes: Number(payload.trunc) || String(row.content || '').length,
+        };
+        delete compactRow.trunc;
+        _storePut([compactRow]);
+    } catch (error) {
+        if (host.isConnected && header) {
+            header.textContent = `❌ Image unavailable · ${error.name}`;
+            header.style.color = '#f87171';
+        }
+    } finally {
+        delete host.dataset.imageRestore;
+    }
+}
+
 function _renderCodexThinking(content, label) {
     const card = document.createElement('div');
     card.className = 'codex-activity-card codex-thinking-card';
     const header = document.createElement('button');
     header.className = 'codex-activity-header';
     header.innerHTML = `<span class="codex-activity-caret">▶</span><span>${label || 'Reasoning'}</span>`;
     const body = document.createElement('div');
     body.className = 'codex-activity-body markdown-body';
@@ -5683,37 +5767,23 @@ function addChatEntry(type, content, ts, anchor, payload) {
                 }
                 delete lastTool.dataset.lastTool;
                 addTimestamp(lastTool, ts);
                 return;
             }
             if (lastTool.dataset.toolRawName === 'ImageGeneration') {
                 let data = {};
                 try { data = JSON.parse(content); } catch {}
-                const header = lastTool.querySelector('.flex.items-center');
-                if (header) {
-                    header.textContent = data.status === 'failed' ? '❌ Image generation failed' : '✅ Image generated';
-                    header.style.color = data.status === 'failed' ? '#f87171' : '#f472b6';
-                }
-                if (data.saved_path) {
-                    const img = document.createElement('img');
-                    img.src = `/api/files/raw?path=${encodeURIComponent(data.saved_path)}&t=${Date.now()}`;
-                    img.loading = 'lazy';
-                    img.className = 'codex-tool-image';
-                    img.addEventListener('click', () => openImageLightbox(img.src));
-                    lastTool.appendChild(img);
-                }
-                if (data.revised_prompt) {
-                    const prompt = document.createElement('div');
-                    prompt.className = 'codex-image-prompt';
-                    prompt.textContent = data.revised_prompt;
-                    lastTool.appendChild(prompt);
-                }
                 delete lastTool.dataset.lastTool;
                 addTimestamp(lastTool, ts);
+                if (payload?.trunc && payload?.id) {
+                    void _restoreImageGenerationResult(lastTool, payload);
+                    return;
+                }
+                _completeImageGenerationTool(lastTool, data);
                 return;
             }
             if (lastTool.dataset.toolRawName === 'ViewImage') {
                 const header = lastTool.querySelector('.flex.items-center');
                 if (header) header.style.color = '#7dd3fc';
                 const img = lastTool.querySelector('.codex-tool-image');
                 if (img && (!img.complete || !img.naturalWidth)) {
                     img.src = img.src.replace(/([?&])t=\d+/, `$1t=${Date.now()}`);
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 62cca257b..b6c396c99 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -3553,16 +3553,202 @@ def test_truncated_read_image_restores_full_log_when_source_file_is_gone(
         }"""
     )
     expect(page.locator("#chat")).to_contain_text("Image unavailable")
     assert page.locator("#chat img").count() == 0
     assert requests == {"file": 3, "log": [42, 42, 43]}
     page.close()
 
 
+def test_image_generation_history_replaces_stale_mirror_and_survives_chat_reentry(
+    dashboard_browser: Browser,
+):
+    page = dashboard_browser.new_page()
+    _route_frontend_sources(page)
+    _goto_dashboard(page)
+    page.wait_for_function("() => typeof _showChatFor === 'function'")
+
+    filler = [
+        {"id": i, "session_id": "sid-a", "type": "text", "content": f"row-{i}",
+         "ts": "2026-08-24T08:00:00+00:00"}
+        for i in range(1, 39)
+    ]
+    call = {
+        "id": 39,
+        "session_id": "sid-a",
+        "type": "tool",
+        "tool_name": "ImageGeneration",
+        "tool_use_id": "image-1",
+        "content": 'ImageGeneration: {"status":"in_progress","_codex_item_id":"image-1"}',
+        "ts": "2026-08-24T08:02:36+00:00",
+    }
+    stale = {
+        "id": 40,
+        "session_id": "sid-a",
+        "type": "tool_result",
+        "tool_name": "ImageGeneration",
+        "tool_use_id": "image-1",
+        "content": '{"result":"AAAA',
+        "trunc": 2_200_000,
+        "ts": "2026-08-24T08:03:04+00:00",
+    }
+    full_row = {
+        **stale,
+        "content": json.dumps({
+            "result": "AAAA",
+            "status": "completed",
+            "saved_path": "/tmp/generated-product.png",
+            "revised_prompt": "Exact product on a warm neutral marketplace background",
+        }),
+    }
+    full_row.pop("trunc")
+
+    state = page.evaluate(
+        """async ({mirrorRows, fullRow}) => {
+            if (eventSource) { eventSource.close(); eventSource = null; }
+            selectedAgent = 'agent-a';
+            currentScope = '/scope-a';
+            window.compactMode = false;
+            window.__imageHistoryFetches = 0;
+            window.__imageLogFetches = 0;
+            _storeSessionId = async () => 'sid-a';
+            _storeRead = async () => mirrorRows;
+            _fetchHistory = async () => {
+                window.__imageHistoryFetches += 1;
+                return [];
+            };
+            api = async (path) => {
+                if (path === '/api/logs/40') {
+                    window.__imageLogFetches += 1;
+                    return fullRow;
+                }
+                throw new Error(`unexpected API ${path}`);
+            };
+            connectSSE = () => {};
+
+            await _showChatFor('agent-a', '/scope-a');
+            await new Promise(resolve => setTimeout(resolve, 0));
+            const first = {
+                prompt: document.querySelector('.codex-image-prompt')?.textContent || '',
+                src: document.querySelector('.codex-tool-image')?.getAttribute('src') || '',
+                title: document.querySelector('[data-tool-raw-name="ImageGeneration"] .flex.items-center')?.textContent || '',
+            };
+
+            document.querySelector('#chat').replaceChildren();
+            selectedAgent = 'agent-b';
+            _renderHistory('agent-b', [{id: 41, session_id: 'sid-b', type: 'text', content: 'other chat'}]);
+            document.querySelector('#chat').replaceChildren();
+            selectedAgent = 'agent-a';
+            await _showChatFor('agent-a', '/scope-a');
+            await new Promise(resolve => setTimeout(resolve, 0));
+            return {
+                historyFetches: window.__imageHistoryFetches,
+                logFetches: window.__imageLogFetches,
+                first,
+                prompt: document.querySelector('.codex-image-prompt')?.textContent || '',
+                src: document.querySelector('.codex-tool-image')?.getAttribute('src') || '',
+                title: document.querySelector('[data-tool-raw-name="ImageGeneration"] .flex.items-center')?.textContent || '',
+            };
+        }""",
+        {
+            "mirrorRows": filler + [call, stale],
+            "fullRow": full_row,
+        },
+    )
+    page.close()
+
+    assert state["historyFetches"] <= 1
+    assert state["logFetches"] == 2
+    for rendered in (state["first"], state):
+        assert rendered["prompt"] == (
+            "Exact product on a warm neutral marketplace background"
+        )
+        assert "generated-product.png" in rendered["src"]
+        assert "Image generated" in rendered["title"]
+
+
+def test_truncated_image_generation_history_recovers_without_server_restart(
+    dashboard_browser: Browser,
+):
+    page = dashboard_browser.new_page()