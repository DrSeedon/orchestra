# Candidate cand-27

## ORIGIN commit 95672ac707 (2026-07-27): fix(95): T3 — session resume, and a race that silently disabled MCP isolation
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/backend_grok.py b/app/backend_grok.py
index 501c6eff6..36d0c0cc7 100644
--- a/app/backend_grok.py
+++ b/app/backend_grok.py
@@ -1,16 +1,17 @@
 """GrokBackend — wraps the Grok Build CLI (ACP over stdio) for agent sessions."""
 
 import asyncio
 import json
 import logging
 import os
 import shutil
 import tempfile
+import uuid
 from pathlib import Path
 from typing import AsyncIterator, Optional
 
 from app.events import AgentEvent
 
 logger = logging.getLogger(__name__)
 
 # Explicit configuration beats autodiscovery: an unrelated `grok` earlier in PATH must not
@@ -65,25 +66,49 @@ GROK_REASONING_EFFORTS = {"low", "medium", "high"}
 GROK_SILENCE_HEARTBEAT_SECONDS = 30
 GROK_MCP_INIT_TIMEOUT_SECONDS = 20
 
 
 class GrokMcpIsolationError(RuntimeError):
     """A worker session started MCP servers Orchestra did not ask for."""
 
 
+def _write_sandbox_config(config: Path) -> None:
+    """Publish the sandbox config atomically.
+
+    The home is shared by every Grok worker, so connects overlap. A plain write truncates
+    first, and a worker starting inside that window reads an EMPTY config — which means the
+    `mcps = false` toggle is absent and foreign MCP servers load with their secrets, exactly
+    the leak T2 closed. Measured before this fix: 57.9% of concurrent reads saw an empty
+    file. Same tmp+rename shape as workspace.sync_agents_md, and the tmp name is unique per
+    call so two writers cannot share one inode.
+    """
+    try:
+        if config.read_text(encoding="utf-8") == _GROK_SANDBOX_CONFIG:
+            return
+    except (FileNotFoundError, OSError):
+        pass
+    tmp = config.parent / f".config.toml.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
+    try:
+        tmp.write_text(_GROK_SANDBOX_CONFIG, encoding="utf-8")
+        tmp.replace(config)  # atomic within the directory
+    finally:
+        if tmp.exists():
+            tmp.unlink(missing_ok=True)
+
+
 def ensure_grok_home() -> Path:
     """Create/refresh the Orchestra-owned GROK_HOME and return it.
 
     `auth.json` is symlinked rather than copied so token refreshes stay shared with the
     user's login instead of silently expiring in a private copy.
     """
     home = GROK_HOME_DIR
     home.mkdir(parents=True, exist_ok=True)
-    (home / "config.toml").write_text(_GROK_SANDBOX_CONFIG, encoding="utf-8")
+    _write_sandbox_config(home / "config.toml")
     auth_link = home / "auth.json"
     real_auth = GROK_USER_HOME / "auth.json"
     if not real_auth.exists():
         raise RuntimeError(
             f"Grok credentials not found at {real_auth}. Run `grok login` first."
         )
     if auth_link.is_symlink():
         if auth_link.readlink() == real_auth:
@@ -212,16 +237,24 @@ class GrokBackend:
         self._disconnecting = False
         self._last_stderr = ""
         self._active_prompts = 0
         self._queue_depth = 0
         self._expected_servers = set(self._mcp_servers)
         self._started_servers = set()
         self._mcp_ready = asyncio.Event()
 
+        if not Path(self.cwd).is_dir():
+            # Otherwise this surfaces as a bare FileNotFoundError from process spawn, which
+            # names the path but not the reason — a worktree that was removed or relocated.
+            raise RuntimeError(
+                f"Grok worker cwd does not exist: {self.cwd} "
+                "(worktree removed or relocated?)"
+            )
+
         cmd = [GROK_BIN, "agent"]
         # The ONLY delivery route for a system prompt. ACP session/new has no such field:
         # systemPrompt / _meta.systemPrompt / instructions are all accepted and SILENTLY
         # ignored (measured) — a worker would run with no prompt and nobody would notice.
         profile = self._write_agent_profile()
         if profile:
             cmd += ["--agent-profile", str(profile)]
         cmd += ["--model", self.model, "--reasoning-effort", self.reasoning_effort]
@@ -248,20 +281,40 @@ class GrokBackend:
                 "protocolVersion": 1,
                 "clientCapabilities": {
                     "fs": {"readTextFile": False, "writeTextFile": False},
                     "terminal": False,
                 },
             })
             self._absorb_model_meta(result.get("_meta") or {})
             params = {"cwd": self.cwd, "mcpServers": self._mcp_server_configs()}
+            result = None
             if self._session_id:
-                params["sessionId"] = self._session_id
-                result = await self._request("session/load", params)
-            else:
+                try:
+                    result = await self._request(
+                        "session/load", {**params, "sessionId": self._session_id}
+                    )
+                except GrokProtocolError as exc:
+                    # A stale id must not brick the worker forever: the store is keyed by
+                    # (cwd, sessionId), so a moved or pruned worktree makes load fail
+                    # permanently. Start fresh — but never quietly, the lost history is
+                    # exactly what someone would otherwise spend an hour looking for.
+                    logger.warning(
+                        "Grok session/load failed for %s (%s) — starting a fresh session",
+                        self._session_id, exc,
+                    )
+                    self._notifications.put_nowait({
+                        "method": "_session/resume_failed",
+                        # NOT "sessionId": events() drops notifications whose sessionId is
+                        # not the current one, and this warning is about the OLD id — it
+                        # would filter out the very message announcing the lost history.
+                        "params": {"staleSessionId": self._session_id, "message": str(exc)},
+                    })
+                    self._session_id = None
+            if result is None:
                 result = await self._request("session/new", params)
                 session_id = result.get("sessionId")
                 if not session_id:
                     raise RuntimeError("Grok ACP returned no session id")
                 self._session_id = session_id
             self._absorb_models(result.get("models") or {})
             await self._verify_mcp_isolation()
         except BaseException:
@@ -556,16 +609,24 @@ class GrokBackend:
 
         if method == "_x.ai/session/prompt_complete":
             return self._finish_prompt(params.get("promptId"), params.get("stopReason"))
 
         if method == "_prompt/result":
             meta = params.get("_meta") or {}
             return self._finish_prompt(meta.get("promptId"), params.get("stopReason"), meta)
 
+        if method == "_session/resume_failed":
+            return [AgentEvent(
+                "warning",
+                f"grok could not resume session {params.get('staleSessionId')} "
+                f"({params.get('message')}) — continuing in a NEW session, "
+                f"previous conversation history is not available",
+            )]
+
         if method == "_prompt/failed":
             self._active_prompts = max(0, self._active_prompts - 1)
             return [
                 AgentEvent("error", params.get("message", "Grok prompt failed"),
                            {"model_error": "error"}),
                 self._turn_end_event(False, "error", "error"),
             ]
 
diff --git a/tests/test_backend_grok.py b/tests/test_backend_grok.py
index e7e3a869a..2cca884b8 100644
--- a/tests/test_backend_grok.py
+++ b/tests/test_backend_grok.py
@@ -387,16 +387,100 @@ def test_build_env_forces_orchestra_grok_home(tmp_path, monkeypatch):
     (fake_user_home / "auth.json").write_text("{}", encoding="utf-8")
     monkeypatch.setattr("app.backend_grok.GROK_HOME_DIR", home)
     monkeypatch.setattr("app.backend_grok.GROK_USER_HOME", fake_user_home)
     # An inherited GROK_HOME must not defeat isolation.
     monkeypatch.setenv("GROK_HOME", "/somewhere/else")
     assert _backend()._build_env()["GROK_HOME"] == str(home)
 
 
+# ── session resume (T3) ──
+#
+# Measured against the live CLI: the session store is keyed by (cwd, sessionId).
+# Resume SURVIVES a branch switch inside the same worktree (main -> feature/x kept the id
+# and the recalled content), but rejects a different cwd with "Path not found". Two workers
+# sharing one GROK_HOME got distinct ids and did not cross-talk.
+
+def test_sandbox_config_write_is_atomic(tmp_path):
+    """A shared home means overlapping connects.
+
+    A plain write truncates first, and a worker starting in that window reads an empty
+    config — no `mcps = false`, isolation silently off. Measured before the fix: 57.9% of
+    concurrent reads saw an empty file; after: 0%.
+    """
+    import threading
+    import app.backend_grok as module
+
+    config = tmp_path / "config.toml"
+    module._write_sandbox_config(config)
+    seen: list[str] = []
+    stop = threading.Event()
+
+    def reader():
+        while not stop.is_set():
+            try:
+                seen.append(config.read_text(encoding="utf-8"))
+            except OSError:
+                seen.append("<enoent>")
+
+    def writer():
+        for _ in range(300):
+            config.write_text("", encoding="utf-8")  # force a rewrite each round
+            module._write_sandbox_config(config)
+
+    t = threading.Thread(target=reader)
+    t.start()
+    try:
+        writer()
+    finally:
+        stop.set()
+        t.join()
+    # Readers may observe the old content or the new one, never a torn/empty file.
+    assert seen, "reader never sampled the file"
+    assert all(text in ("", module._GROK_SANDBOX_CONFIG) for text in seen)
+    assert any(text == module._GROK_SANDBOX_CONFIG for text in seen)
+
+
+def test_sandbox_config_rewritten_when_content_drifts(tmp_path):
+    config = tmp_path / "config.toml"
+    config.write_text("[compat.claude]\nmcps = true\n", encoding="utf-8")
+    import app.backend_grok as module
+    module._write_sandbox_config(config)
+    assert config.read_text(encoding="utf-8") == module._GROK_SANDBOX_CONFIG
+    assert not list(tmp_path.glob(".config.toml.*.tmp"))  # no temp files left behind
+
+
+def test_resume_failure_warning_is_not_filtered_by_session_routing():
+    """events() drops notifications for a different sessionId.
+
+    The resume warning is about the OLD id, so carrying it under `sessionId` made the
+    message announcing the lost history get filtered out — silently.
+    """
+    b = _backend()
+    b._session_id = "new-id"
+    (warning,) = b._convert({"method": "_session/resume_failed", "params": {
+        "staleSessionId": "old-id", "message": "Path not found."}})
+    assert warning.type == "warning"
+    assert "old-id" in warning.content
+    assert "not available" in warning.content
+
+
+def test_connect_refuses_missing_worktree():
+    """A removed worktree otherwise surfaces as a bare FileNotFoundError from spawn."""
+    async def scenario():
+        await _backend(cwd="/tmp/definitely-not-here-95").connect()
+    with pytest.raises(RuntimeError, match="worktree removed or relocated"):
+        asyncio.run(scenario())
+
+
+def test_session_id_exposed_for_persistence():
+    b = _backend(resume_session_id="019f-abc")
+    assert b.session_id == "019f-abc"
+
+
 def test_explicit_grok_bin_env_beats_path_autodiscovery(monkeypatch):
     """A stray `grok` in PATH must not win over deliberate configuration."""
     import importlib
     monkeypatch.setenv("GROK_BIN", "/opt/pinned/grok")
     monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/grok")
     module = importlib.reload(importlib.import_module("app.backend_grok"))
     try:
         assert module.GROK_BIN == "/opt/pinned/grok"


## LATER FIX 5e11d8772f (19.7 days later): fix: stabilize Grok session replay and chat finalization
lines of origin it changed/deleted: 22
(code only, capped 400 lines)

fix: stabilize Grok session replay and chat finalization


diff --git a/app/backend_grok.py b/app/backend_grok.py
index f33ae2d50..ce76723b9 100644
--- a/app/backend_grok.py
+++ b/app/backend_grok.py
@@ -164,26 +164,81 @@ def _grok_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens:
     # Deliberately a short-context fallback. ACP exposes a turn aggregate, while the 200k
     # tier applies per model request; a tool-loop can mix tiers. Runtime costUsdTicks remains
     # the only exact source until ACP exposes per-request usage (docs/tasks/251/research.md).
     return (fresh * prices["input"] + cached * prices["cached"]
             + max(0, output_tokens) * prices["output"]) / 1_000_000
 
 
 def _content_text(content) -> str:
-    """Flatten an ACP content block (or list of them) to text."""
+    """Flatten an ACP content block (or list of them) to text.
+
+    Grok wraps tool results as `{type: "content", content: {type: "text", text: ...}}`
+    and MCP results as `{type: "MCP", tool_name, output: {OkayOutput: ...}}`.
+    Dumping the outer object left the dashboard showing raw JSON grids instead of
+    the tool output itself.
+    """
     if isinstance(content, dict):
-        if content.get("type") == "text":
+        ctype = content.get("type")
+        if ctype == "text":
+            return str(content.get("text", ""))
+        # Grok MCP tool_call_update payload (measured 15.08.2026).
+        if ctype == "MCP" or (
+            isinstance(content.get("output"), dict)
+            and ("tool_name" in content or "server_name" in content)
+        ):
+            output = content.get("output")
+            if isinstance(output, dict):
+                for key in (
+                    "OkayOutput", "ErrorOutput", "output", "text", "result", "content",
+                ):
+                    if key in output and output[key] not in (None, ""):
+                        return _content_text(output[key])
+                # Last resort: first non-empty string value in output.
+                for value in output.values():
+                    if isinstance(value, str) and value.strip():
+                        return value
+                    inner = _content_text(value)
+                    if inner.strip():
+                        return inner
+            elif output is not None:
+                return _content_text(output)
+        # Nested content wrapper from Grok tool_call_update / MCP results.
+        if "content" in content and ctype in (None, "content", "resource", "resource_link"):
+            inner = _content_text(content.get("content"))
+            if inner:
+                return inner
+        if "text" in content and ctype is None:
             return str(content.get("text", ""))
         return json.dumps(bounded_tool_arguments(content), ensure_ascii=False)
     if isinstance(content, list):
-        return "\n".join(_content_text(part) for part in content)
+        parts = [_content_text(part) for part in content]
+        return "\n".join(part for part in parts if part)
     return str(content) if content is not None else ""
 
 
+def _headers_to_acp(headers) -> list[dict]:
+    """ACP rejects bare http/sse MCP entries without a `headers` array (even empty)."""
+    if not headers:
+        return []
+    if isinstance(headers, dict):
+        return [{"name": str(k), "value": str(v)} for k, v in headers.items()]
+    if isinstance(headers, list):
+        out = []
+        for item in headers:
+            if not isinstance(item, dict):
+                continue
+            name = item.get("name")
+            if name is None:
+                continue
+            out.append({"name": str(name), "value": str(item.get("value", ""))})
+        return out
+    return []
+
+
 def _mcp_server_identity(server: dict) -> tuple:
     """Canonical identity for an ACP MCP config, excluding discovery metadata."""
     raw_env = server.get("env") or []
     if isinstance(raw_env, dict):
         env = tuple(sorted((str(k), str(v)) for k, v in raw_env.items()))
     else:
         env = tuple(sorted(
             (str(item.get("name")), str(item.get("value", "")))
@@ -254,16 +309,26 @@ class GrokBackend(JsonRpcStdioTransport):
         self._last_stderr = ""
         self._profile_path: Path | None = None
         # Turn bookkeeping. `_active_prompts` counts prompts accepted but not yet completed —
         # the agent queues extras, so the event loop must not stop at the first completion.
         self._active_prompts = 0
         self._queue_depth = 0
         self._completed_prompts: set[str] = set()
         self._tool_names: dict[str, str] = {}
+        # Grok only streams message/thought chunks — never a final item-complete event.
+        # Session persists `text`/`thinking`, not live `stream`/`thinking_stream`, so without
+        # these buffers assistant replies vanish from history and leave the UI bubble open
+        # across turns (messages glue, reasoning floats as a live card forever).
+        self._message_buf: list[str] = []
+        self._thought_buf: list[str] = []
+        # session/load replays prior turns as session/update notifications. If those land
+        # in the event stream they are re-logged as "new" tool/text/thinking rows and bury
+        # real user messages under a flood (measured: full history dumped at 07:36 and 07:40).
+        self._suppress_history_replay = False
         # turn_completed carries usage; the turn_end is emitted by the prompt completion.
         self._pending_usage: dict = {}
         self._model_context_window = GROK_CONTEXT_LIMITS.get(model, GROK_DEFAULT_CONTEXT)
         self._context_tokens: int | None = None
         self._mcp_canary: str | None = None
         self._issue_mcp_canary()
         # A matching name is insufficient: a repository can define another command under it.
         expected_configs = self._mcp_server_configs()
@@ -351,47 +416,61 @@ class GrokBackend(JsonRpcStdioTransport):
                 "clientCapabilities": {
                     "fs": {"readTextFile": False, "writeTextFile": False},
                     "terminal": False,
                 },
             })
             self._absorb_model_meta(result.get("_meta") or {})
             params = {"cwd": self.cwd, "mcpServers": self._mcp_server_configs()}
             result = None
-            if self._session_id:
-                try:
-                    result = await self._request(
-                        "session/load", {**params, "sessionId": self._session_id}
-                    )
-                except GrokProtocolError as exc:
-                    # A stale id must not brick the worker forever: the store is keyed by
-                    # (cwd, sessionId), so a moved or pruned worktree makes load fail
-                    # permanently. Start fresh — but never quietly, the lost history is
-                    # exactly what someone would otherwise spend an hour looking for.
-                    logger.warning(
-                        "Grok session/load failed for %s (%s) — starting a fresh session",
-                        self._session_id, exc,
-                    )
-                    self._notifications.put_nowait({
-                        "method": "_session/resume_failed",
-                        # NOT "sessionId": events() drops notifications whose sessionId is
-                        # not the current one, and this warning is about the OLD id — it
-                        # would filter out the very message announcing the lost history.
-                        "params": {"staleSessionId": self._session_id, "message": str(exc)},
-                    })
-                    self._session_id = None
-            if result is None:
-                result = await self._request("session/new", params)
-                session_id = result.get("sessionId")
-                if not session_id:
-                    raise RuntimeError("Grok ACP returned no session id")
-                self._session_id = session_id
-            self._absorb_models(result.get("models") or {})
+            # Drop session/update content while load/new runs — Grok replays the whole
+            # transcript into the notification queue, and the first turn after connect
+            # would re-persist it as brand-new logs.
+            self._suppress_history_replay = True
+            try:
+                if self._session_id:
+                    try:
+                        result = await self._request(
+                            "session/load", {**params, "sessionId": self._session_id}
+                        )
+                    except GrokProtocolError as exc:
+                        # A stale id must not brick the worker forever: the store is keyed by
+                        # (cwd, sessionId), so a moved or pruned worktree makes load fail
+                        # permanently. Start fresh — but never quietly, the lost history is
+                        # exactly what someone would otherwise spend an hour looking for.
+                        logger.warning(
+                            "Grok session/load failed for %s (%s) — starting a fresh session",
+                            self._session_id, exc,
+                        )
+                        self._notifications.put_nowait({
+                            "method": "_session/resume_failed",
+                            # NOT "sessionId": events() drops notifications whose sessionId is
+                            # not the current one, and this warning is about the OLD id — it
+                            # would filter out the very message announcing the lost history.
+                            "params": {
+                                "staleSessionId": self._session_id,
+                                "message": str(exc),
+                            },
+                        })
+                        self._session_id = None
+                if result is None:
+                    result = await self._request("session/new", params)
+                    session_id = result.get("sessionId")
+                    if not session_id:
+                        raise RuntimeError("Grok ACP returned no session id")
+                    self._session_id = session_id
+                self._absorb_models(result.get("models") or {})
+                # Anything already queued during load is history replay — drop content
+                # updates, keep MCP startup (isolation still needs them).
+                self._drain_history_replay_queue()
+            finally:
+                self._suppress_history_replay = False
             await self._verify_mcp_isolation()
         except BaseException:
+            self._suppress_history_replay = False
             await self.disconnect()
             raise
 
     async def _verify_mcp_isolation(self) -> None:
         """Fail connect unless the observed MCP roster exactly matches the launch plan.
 
         The GROK_HOME sandbox suppresses Claude-compat discovery, and a repo `.mcp.json` is
         additionally gated behind folder trust. Neither guarantee is ours to enforce, so the
@@ -691,16 +770,22 @@ class GrokBackend(JsonRpcStdioTransport):
                                 "method": "_prompt/result",
                                 "params": result,
                             })
                     continue
                 if message.get("method"):
                     # Track MCP startup here, not in events(): isolation is verified during
                     # connect(), before any consumer starts draining the event stream.
                     self._track_mcp(message)
+                    if (
+                        self._suppress_history_replay
+                        and message.get("method") == "session/update"
+                    ):
+                        # session/load replays prior turns; do not surface them as new events.
+                        continue
                     await self._notifications.put(message)
         except asyncio.CancelledError:
             return
         except Exception as exc:
             logger.exception("Grok ACP reader failed: %s", exc)
         finally:
             returncode = await proc.wait()
             error = RuntimeError(f"Grok ACP agent exited with code {returncode}")
@@ -846,17 +931,17 @@ class GrokBackend(JsonRpcStdioTransport):
                 "warning",
                 f"grok could not resume session {params.get('staleSessionId')} "
                 f"({params.get('message')}) — continuing in a NEW session, "
                 f"previous conversation history is not available",
             )]
 
         if method == "_prompt/failed":
             self._active_prompts = max(0, self._active_prompts - 1)
-            return [
+            return self._flush_open_streams() + [
                 AgentEvent("error", params.get("message", "Grok prompt failed"),
                            {"model_error": "error"}),
                 self._turn_end_event(False, "error", "error"),
             ]
 
         if method == "_x.ai/mcp/server_status":
             return self._mcp_status(params)
 
@@ -883,79 +968,136 @@ class GrokBackend(JsonRpcStdioTransport):
             turn_usage = TurnUsage(
                 AggregateUsage.normalized(),
                 current_context(
                     None,
                     self._model_context_window,
                     unknown_reason="Grok exited before reporting current context",
                 ),
             )
-            return [AgentEvent("turn_end", "stop_reason=process_exit", metadata={
-                "session_id": self._session_id,
-                "ok": False,
-                "stop_reason": f"process_exit_{params.get('returncode')}",
-                "returncode": params.get("returncode"),
-                "stderr_tail": params.get("stderr", ""),
-                "model_error": "server_error",
-                "errors": ["server_error"],
-                "cost_usd": 0,
-                **turn_usage.metadata(),
-            }, usage=turn_usage)]
+            return self._flush_open_streams() + [AgentEvent(
+                "turn_end", "stop_reason=process_exit", metadata={
+                    "session_id": self._session_id,
+                    "ok": False,
+                    "stop_reason": f"process_exit_{params.get('returncode')}",
+                    "returncode": params.get("returncode"),
+                    "stderr_tail": params.get("stderr", ""),
+                    "model_error": "server_error",
+                    "errors": ["server_error"],
+                    "cost_usd": 0,
+                    **turn_usage.metadata(),
+                }, usage=turn_usage,
+            )]
 
         return []
 
+    def _drain_history_replay_queue(self) -> None:
+        """Remove session/update content left in the queue after session/load."""
+        kept: list[dict] = []
+        while True:
+            try:
+                message = self._notifications.get_nowait()
+            except asyncio.QueueEmpty:
+                break
+            if message.get("method") == "session/update":
+                continue
+            kept.append(message)
+        for message in kept:
+            self._notifications.put_nowait(message)
+
+    def _flush_message(self) -> list[AgentEvent]:
+        text = "".join(self._message_buf)
+        self._message_buf.clear()
+        if not text:
+            return []
+        return [AgentEvent("text", text)]
+
+    def _flush_thought(self) -> list[AgentEvent]:
+        text = "".join(self._thought_buf)
+        self._thought_buf.clear()
+        if not text:
+            return []
+        return [AgentEvent("thinking", text)]
+
+    def _flush_open_streams(self) -> list[AgentEvent]:
+        # Thought before message: reasoning precedes the answer that used it.
+        return self._flush_thought() + self._flush_message()
+
     def _session_update(self, params: dict) -> list[AgentEvent]:
         update = params.get("update") or {}
         kind = update.get("sessionUpdate", "")
         meta = params.get("_meta") or {}
         total = meta.get("totalTokens")
         if isinstance(total, int) and total >= 0:
             self._context_tokens = total
 
         if kind == "agent_message_chunk":
-            return [AgentEvent("stream", _content_text(update.get("content")))]
+            chunk = _content_text(update.get("content"))
+            if chunk:
+                self._message_buf.append(chunk)
+            return [AgentEvent("stream", chunk)]
 
         if kind == "agent_thought_chunk":
-            return [AgentEvent("thinking_stream", _content_text(update.get("content")),
+            chunk = _content_text(update.get("content"))
+            if chunk:
+                self._thought_buf.append(chunk)
+            return [AgentEvent("thinking_stream", chunk,
                                {"activity": "reasoning",
                                 "item_id": str(meta.get("promptId") or "")})]
 
         if kind == "tool_call":
+            # Flush answer text before the tool so order is text → tool → result → text.
+            # Do NOT flush thinking here: Grok thinks between nearly every tool, and that
+            # produced 50+ reasoning cards per turn. One thinking card lands at turn_end.
+            events = self._flush_message()
             tool_id = str(update.get("toolCallId") or update.get("id") or "")
             name = str(update.get("title") or update.get("kind") or "tool")
             self._tool_names[tool_id] = name
-            return [AgentEvent(
+            events.append(AgentEvent(
                 "tool_use",
                 f"{name}: {json.dumps(bounded_tool_arguments(update.get('rawInput') or {}), ensure_ascii=False)}",
                 metadata={"tool_name": name, "short_name": name, "tool_use_id": tool_id},
-            )]
+            ))
+            return events
 
         if kind == "tool_call_update":
             return self._tool_call_update(update)
 
         if kind == "plan":
-            return [AgentEvent("plan", json.dumps(update.get("entries") or [],
-                                                  ensure_ascii=False))]
+            # Plan is mid-turn structure; keep reasoning open until the turn ends.
+            events = self._flush_message()
+            events.append(AgentEvent("plan", json.dumps(update.get("entries") or [],
+                                                        ensure_ascii=False)))
+            return events
         return []
 
     def _tool_call_update(self, update: dict) -> list[AgentEvent]:
         tool_id = str(update.get("toolCallId") or update.get("id") or "")
         status = update.get("status")
         title = update.get("title")
         if title and tool_id:
             # Grok routes MCP tools through a search_tool/use_tool meta-layer; the concrete
             # name (e.g. orchestra__list_agents) arrives on the update, not the initial call.
             self._tool_names[tool_id] = str(title)
         if status not in ("completed", "failed"):
             return []
         name = self._tool_names.get(tool_id, "tool")
         content = update.get("content")
-        text = _content_text(content) if content is not None else json.dumps(
-            {"status": status}, ensure_ascii=False
-        )
+        text = _content_text(content) if content is not None else ""
+        if not text.strip():
+            raw = update.get("rawOutput")
+            if raw is not None:
+                if isinstance(raw, (dict, list)):
+                    text = _content_text(raw)
+                    if not text.strip():
+                        text = json.dumps(bounded_tool_arguments(raw), ensure_ascii=False)
+                else:
+                    text = str(raw)
+        if not text.strip():