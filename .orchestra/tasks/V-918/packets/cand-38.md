# Candidate cand-38

## ORIGIN commit fa3e993dba (2026-08-23): Allow fresh model switches without handoff
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index b8350baef..a8641f042 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1510,18 +1510,18 @@ async def update_progress(percent: int, status: str) -> str:
     })
     if isinstance(result, dict) and result.get("error"):
         return f"Progress update failed: {result['error']}"
     return f"Progress: {percent}% — {status}"
 
 
 @mcp.tool()
 async def change_worker_model(name: str, model: str) -> str:
-    """Change a worker's model (e.g. sonnet→opus) without losing context. Worker must be idle."""
-    result = await _api("POST", f"/api/sessions/{name}/change-model", json={"scope": SCOPE, "model": model})
+    """Change an idle worker's model and start a fresh dialog on the target runtime."""
+    result = await _api("POST", f"/api/sessions/{name}/change-model", json={"scope": SCOPE, "model": model, "fresh": True})
     if isinstance(result, dict) and result.get("error"):
         return f"Model change failed: {result['error']}"
     if isinstance(result, dict) and result.get("changed"):
         return f"Model changed: {result.get('old_model')} → {result.get('model')}"
     return f"Model already {result.get('model', model)}"
 
 
 def _merge_local_result(
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index ab98d9c34..10c3f4925 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -866,17 +866,17 @@ async def change_model(name: str, req: dict):
     if not new_model:
         return JSONResponse({"error": "model required"}, status_code=400)
     new_model = resolve_model(new_model)
     if new_model not in MODELS:
         return JSONResponse({"error": f"unknown model: {new_model}"}, status_code=400)
     found = await manager.ensure_loaded(name, scope)
     if not found:
         return JSONResponse({"error": "not found"}, status_code=404)
-    result = await found.change_model(new_model)
+    result = await found.change_model(new_model, fresh=True)
     if not result.get("ok"):
         return JSONResponse(result, status_code=409)
     return result
 
 
 @router.post("/api/sessions/{session_id}/handoffs/{handoff_id}/events")
 async def runtime_handoff_events(
     session_id: str, handoff_id: str, request: Request, req: dict,
diff --git a/app/session.py b/app/session.py
index 49c92300b..07190a48d 100644
--- a/app/session.py
+++ b/app/session.py
@@ -62,19 +62,19 @@ from app.session_turns import TurnManager
 from app.usage_contract import KnownContext, current_context
 
 if TYPE_CHECKING:
     from app.backend_protocol import BackendLike
     from app.quota_gate import QuotaDecision
 from app.db import (
     add_log, allocate_runtime_handoff_attempt, confirm_runtime_handoff,
     enqueue_fact, get_history_logs, get_logs, get_profile, get_runtime_handoff,
-    prepare_runtime_handoff_snapshot, save_session, tool_error_add,
-    retire_runtime_handoff, update_runtime_handoff_attempt,
-    update_runtime_handoff_status,
+    get_latest_runtime_handoff_for_session, list_runtime_handoff_attempts,
+    prepare_runtime_handoff_snapshot, retire_runtime_handoff, save_session,
+    tool_error_add, update_runtime_handoff_attempt, update_runtime_handoff_status,
 )
 from app.errtext import err_text
 
 
 logger = logging.getLogger(__name__)
 
 _HANDOFF_STAGING_ROOT = (
     Path(__file__).parent.parent / "data" / "runtime-handoff-staging"
@@ -2862,22 +2862,145 @@ class AgentSession:
                 remaining = max_chars - total
                 if remaining > 200:
                     blocks.append(block[-remaining:])
                 break
             blocks.append(block)
             total += len(block)
         return "\n\n".join(reversed(blocks))
 
-    async def change_model(self, new_model: str) -> dict:
+    async def change_model(self, new_model: str, *, fresh: bool = False) -> dict:
         async with self._lifecycle_lock:
             if self._compacting:
                 return {"ok": False, "error": "cannot change model while compacting"}
+            if fresh:
+                return await self._change_model_fresh_locked(new_model)
             return await self._change_model_locked(new_model)
 
+    async def _discard_unfinished_handoff_for_fresh_switch(self) -> None:
+        """Retire staged handoff state because the operator chose to discard it."""
+        loop = asyncio.get_running_loop()
+        handoff = await loop.run_in_executor(
+            _db_executor(), get_latest_runtime_handoff_for_session, self.id,
+        )
+        if handoff is None:
+            return
+        attempts = await loop.run_in_executor(
+            _db_executor(), list_runtime_handoff_attempts, handoff["handoff_id"],
+        )
+        for attempt in attempts:
+            locator = str(attempt.get("cleanup_locator") or "")
+            if not locator:
+                continue
+            if not self._handoff_cleanup_locator_is_owned(locator):
+                raise RuntimeError("handoff cleanup locator is outside staging root")
+            await asyncio.to_thread(self._remove_handoff_cleanup_locator, locator)
+        await loop.run_in_executor(
+            _db_executor(),
+            partial(
+                retire_runtime_handoff,
+                handoff["handoff_id"],
+                status="failed",
+                failure_code="operator_discarded_for_fresh_model_switch",
+            ),
+        )
+
+    async def _change_model_fresh_locked(self, new_model: str) -> dict:
+        """Switch runtimes without importing or resuming the previous dialog."""
+        old_model = self.model
+        if old_model == new_model:
+            return {"ok": True, "model": new_model, "changed": False}
+        if self.status == AgentStatus.RUNNING:
+            return {"ok": False, "error": "cannot change model while running"}
+
+        old_runtime = self.backend_type or backend_for_model(old_model)
+        new_runtime = get_model_spec(new_model).runtime
+        old_session_id = self.session_id
+        await self._drain_persist()
+        try:
+            await self._disconnect_backend()
+            await self._discard_unfinished_handoff_for_fresh_switch()
+        except Exception as error:
+            return {
+                "ok": False,
+                "error": err_text(error),
+                "error_code": "fresh_switch_cleanup_failed",
+                "history_transfer": {"mode": "blocked"},
+            }
+
+        new_history = list(self.session_id_history)
+        if old_session_id:
+            new_history.append({
+                "session_id": old_session_id,
+                "runtime": old_runtime,
+                "model": old_model,
+                "discarded_at": datetime.now(timezone.utc).isoformat(),
+            })
+            new_history = new_history[-10:]
+
+        snapshot = self._to_db_dict()
+        snapshot.update({
+            "model": new_model,
+            "backend_type": new_runtime,
+            "session_id": "",
+            "runtime_handoff": "",
+            "history_import_source": None,
+            "last_summary": "",
+            "context_pct": 0,
+            "context_tokens": 0,
+            "session_id_history": json.dumps(new_history) if new_history else "[]",
+        })
+
+        try:
+            await asyncio.get_running_loop().run_in_executor(
+                _db_executor(), save_session, snapshot,
+            )
+        except Exception as error:
+            return {
+                "ok": False,
+                "error": err_text(error),
+                "error_code": "fresh_switch_persistence_failed",
+                "history_transfer": {"mode": "blocked"},
+            }
+
+        self.model = new_model
+        self.backend_type = new_runtime
+        self.session_id = ""
+        self.session_id_history = new_history
+        self.runtime_handoff = ""
+        self.history_import_source = None
+        self.last_summary = ""
+        self._last_context = {
+            "percentage": 0, "total_tokens": 0, "max_tokens": 0,
+        }
+        self._prompt_injected = False
+        self._hibernated = False
+        self._handoff_config_dir = ""
+        self._handoff_recovery_required = False
+        self._session_limit_hit = False
+        self._cancel_precompact_timer("fresh_model_switch")
+        self._log(
+            "status",
+            f"fresh model change: {old_model} ({old_runtime}) → "
+            f"{new_model} ({new_runtime}); previous dialog discarded",
+        )
+        return {
+            "ok": True,
+            "model": new_model,
+            "old_model": old_model,
+            "runtime": new_runtime,
+            "old_runtime": old_runtime,
+            "runtime_changed": old_runtime != new_runtime,
+            "native_session_reset": True,
+            "history_transfer": {
+                "mode": "fresh", "previous_dialog_discarded": True,
+            },
+            "changed": True,
+        }
+
     def _collect_handoff_project_docs(self) -> list[dict]:
         from app.workspace import tracked_paths
 
         root = Path(self.worktree_path or self.cwd)
         candidates = ["CLAUDE.md", "AGENTS.md"]
         try:
             tracked = tracked_paths(root, candidates)
         except (OSError, RuntimeError):
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 84bac088a..45475c1b0 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2559,16 +2559,22 @@ function _historyTransferMessage(transfer) {
         };
     }
     if (transfer.mode === 'native_resume') {
         return {
             type: 'status',
             text: 'native provider thread resumed after total-context preflight',
         };
     }
+    if (transfer.mode === 'fresh') {
+        return {
+            type: 'status',
+            text: 'fresh target session started; previous dialog discarded',
+        };
+    }
     if (transfer.mode === 'summary') {
         return {
             type: 'warning',
             text: `native history import unavailable: ${transfer.reason || 'unknown reason'}; summary fallback active`,
         };
     }
     if (transfer.mode !== 'native') return null;
     return {
@@ -2605,17 +2611,17 @@ async function _showModelPicker(agentName, currentModel, anchor) {
         item.textContent = `${isCurrent ? '● ' : ''}${m.label}`;
         if (!isCurrent) {
             item.addEventListener('mouseenter', () => item.style.background = 'rgba(51,65,85,0.5)');
             item.addEventListener('mouseleave', () => item.style.background = '');
             item.addEventListener('click', async (e) => {
                 e.stopPropagation();
                 dd.remove();
                 try {
-                    const resp = await api(`/api/sessions/${agentName}/change-model`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ model: m.id, scope: currentScope }) });
+                    const resp = await api(`/api/sessions/${agentName}/change-model`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ model: m.id, scope: currentScope, fresh: true }) });
                     if (resp && !resp.error) {
                         $('#ai-model').textContent = m.id;
                         _showHistoryTransfer(resp.history_transfer);
                         loadSessions();
                     }
                 } catch (e) {
                     const match = String(e.message || '').match(/^\d+:\s*(\{.*\})$/s);
                     if (match) {
diff --git a/tests/test_change_model_unloaded.py b/tests/test_change_model_unloaded.py
index f83cce989..a02cb12f8 100644
--- a/tests/test_change_model_unloaded.py
+++ b/tests/test_change_model_unloaded.py
@@ -30,17 +30,17 @@ async def test_change_model_loads_unloaded_idle_worker(monkeypatch):
     response = await routes.change_model(
         "feat-charts", {"scope": "/s", "model": "gpt-5.6-sol"},
     )
     status, body = _status_body(response)
     assert status == 200
     assert body["ok"] is True
     assert body["model"] == "gpt-5.6-sol"
     routes.manager.ensure_loaded.assert_awaited_once_with("feat-charts", "/s")
-    live.change_model.assert_awaited_once_with("gpt-5.6-sol")
+    live.change_model.assert_awaited_once_with("gpt-5.6-sol", fresh=True)
 
 
 @pytest.mark.asyncio
 async def test_change_model_missing_session_is_404(monkeypatch):
     from app.routes import sessions as routes
 
     monkeypatch.setattr(routes.manager, "get_by_name", lambda *_a, **_k: None)
     monkeypatch.setattr(routes.manager, "ensure_loaded", AsyncMock(return_value=None))
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 1eb089eb2..6f02bbcef 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -39,30 +39,32 @@ def test_html_preview_uses_protected_raw_url_and_opaque_origin_sandbox():
     match = re.search(r'<iframe[^`]+sandbox="([^"]+)"', html_branch)
 
     assert match
     assert "openBtn.href = rawUrl;" in html_branch
     assert set(match.group(1).split()) == {"allow-scripts"}
     assert "allow-same-origin" not in match.group(1)
 
 
-def test_model_picker_surfaces_validated_packet_native_resume_and_blocked_source():
+def test_model_picker_requests_fresh_session_and_surfaces_transfer_result():
     source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
     helper = source.split("function _historyTransferMessage", 1)[1].split(
         "async function _showModelPicker", 1,
     )[0]
     picker = source.split("async function _showModelPicker", 1)[1].split(
         "function updateAgentInfo", 1,
     )[0]
 
     assert "server state packet" in helper
     assert "bounded fallback packet" in helper
     assert "native provider thread resumed after total-context preflight" in helper
     assert "dialog switch blocked; source retained" in helper
+    assert "fresh target session" in helper
     assert "raw snapshot remains operator-only and untrusted" in helper
+    assert "fresh: true" in picker
     assert "_showHistoryTransfer(resp.history_transfer);" in picker
     assert "body.error_code" in picker
 
 
 @pytest.mark.asyncio
 @pytest.mark.parametrize("suffix", [".html", ".HTM"])
 async def test_raw_html_response_has_sandbox_csp(tmp_path, monkeypatch, suffix):
     from app.routes import system
diff --git a/tests/test_mcp_quota_gate.py b/tests/test_mcp_quota_gate.py
index dd23c7071..1d8e6d7da 100644
--- a/tests/test_mcp_quota_gate.py
+++ b/tests/test_mcp_quota_gate.py
@@ -180,8 +180,9 @@ async def test_review_defaults_to_luna_the_always_fast_lane(api):
 async def test_change_model_is_control_action_even_when_target_bucket_blocked(api):
     api.state["readiness"] = _readiness("blocked")
 
     result = await mcp.change_worker_model(name="w", model="gpt-5.6-sol")
 
     assert "Model changed" in result
     assert not [path for path, _body in api.calls if path == "/api/usage/readiness"]
     assert [path for path, _body in api.calls] == ["/api/sessions/w/change-model"]
+    assert api.calls[0][1]["fresh"] is True
diff --git a/tests/test_session.py b/tests/test_session.py
index 5a609bf1b..dca07c176 100644
--- a/tests/test_session.py
+++ b/tests/test_session.py
@@ -4026,16 +4026,70 @@ class TestRuntimeCapabilities:
             expected_packet_sha256="a" * 64,
         )
 
         assert get_runtime("codex").capabilities.validated_handoff is False
         assert receipt["ok"] is False
         assert receipt["failure"]["kind"] == "capability_unsupported"
         backend.connect.assert_not_awaited()
 
+    @pytest.mark.asyncio
+    async def test_fresh_model_switch_discards_source_context_without_handoff(
+            self, session, monkeypatch):
+        from app.session import AgentStatus
+
+        session.model = "claude-opus-5[1m]"
+        session.backend_type = "claude"
+        session.session_id = "quota-exhausted-claude-session"
+        session.status = AgentStatus.IDLE
+        session.runtime_handoff = "old packet"
+        session.history_import_source = "native_claude_jsonl"
+        session.last_summary = "old summary"
+        session._last_context = {
+            "percentage": 38, "total_tokens": 98_192, "max_tokens": 258_400,
+        }
+        session._session_limit_hit = True
+        source = AsyncMock()
+        session._backend = source
+        session._log = MagicMock()
+        session._prepare_runtime_handoff = AsyncMock(
+            side_effect=AssertionError("fresh switch must not build a handoff"),
+        )
+        session._make_backend = MagicMock(
+            side_effect=AssertionError("target starts on the next user turn"),
+        )
+        save = MagicMock()
+        monkeypatch.setattr("app.session.save_session", save)
+
+        result = await session.change_model("gpt-5.6-sol", fresh=True)
+
+        assert result["ok"] is True
+        assert result["runtime_changed"] is True
+        assert result["native_session_reset"] is True
+        assert result["history_transfer"] == {
+            "mode": "fresh", "previous_dialog_discarded": True,
+        }
+        assert session.model == "gpt-5.6-sol"
+        assert session.backend_type == "codex"
+        assert session.session_id == ""
+        assert session.runtime_handoff == ""
+        assert session.history_import_source is None
+        assert session.last_summary == ""
+        assert session._last_context == {
+            "percentage": 0, "total_tokens": 0, "max_tokens": 0,
+        }
+        assert session._session_limit_hit is False
+        assert session._backend is None
+        assert session.session_id_history[-1]["session_id"] == (
+            "quota-exhausted-claude-session"
+        )
+        source.disconnect.assert_awaited_once()
+        session._prepare_runtime_handoff.assert_not_awaited()
+        save.assert_called_once()
+
     @pytest.mark.asyncio
     async def test_codex_model_switch_preserves_native_thread(
             self, session, monkeypatch):
         from app.session import AgentStatus
 
         session.model = "gpt-5.5"
         session.backend_type = "codex"
         session.session_id = "codex-native-session"


## LATER FIX e26dcde852 (1.1 days later): fix: switch Codex models in place
lines of origin it changed/deleted: 5
(code only, capped 400 lines)

fix: switch Codex models in place


diff --git a/app/backend_codex.py b/app/backend_codex.py
index a08764060..e03b3000c 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -885,16 +885,28 @@ class CodexBackend(JsonRpcStdioTransport):
     @property
     def hibernate_unavailable_reason(self) -> str:
         return self._scope_reason
 
     @property
     def has_owned_processes(self) -> bool:
         return self._proc is not None or self._scope_unit is not None
 
+    def retarget_model(self, model: str) -> None:
+        """Use app-server's per-turn model override without replacing the thread."""
+        if self._active_turn_id or self._events_active:
+            raise RuntimeError("cannot retarget Codex model while a turn is active")
+        old_fallback = CODEX_CONTEXT_LIMITS.get(self.model, 258400)
+        new_fallback = CODEX_CONTEXT_LIMITS.get(model, 258400)
+        # Preserve a runtime-reported window (for example 828400 for GPT-5.6) across
+        # siblings that share the same catalog limit; switch fallbacks across families.
+        if old_fallback != new_fallback or self._model_context_window == old_fallback:
+            self._model_context_window = new_fallback
+        self.model = model
+
     async def _verify_history_version(self) -> None:
         if not self._history_import:
             return
         try:
             returncode, stdout, stderr = await _run_process(
                 CODEX_BIN,
                 "--version",
                 timeout=10,
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index c1a7a3a5a..2769b8a34 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -1168,17 +1168,20 @@ async def change_model(name: str, req: dict):
             ensure_spawn_allowed(new_model)
         else:
             ensure_dashboard_visible(new_model)
     except ValueError as exc:
         return JSONResponse({"error": str(exc)}, status_code=409)
     found = await manager.ensure_loaded(name, scope)
     if not found:
         return JSONResponse({"error": "not found"}, status_code=404)
-    result = await found.change_model(new_model, fresh=True)
+    fresh = req.get("fresh", False)
+    if not isinstance(fresh, bool):
+        return JSONResponse({"error": "fresh must be boolean"}, status_code=400)
+    result = await found.change_model(new_model, fresh=fresh)
     if not result.get("ok"):
         return JSONResponse(result, status_code=409)
     return result
 
 
 @router.post("/api/sessions/{session_id}/handoffs/{handoff_id}/events")
 async def runtime_handoff_events(
     session_id: str, handoff_id: str, request: Request, req: dict,
diff --git a/app/session.py b/app/session.py
index c657b797c..34a79fac8 100644
--- a/app/session.py
+++ b/app/session.py
@@ -4325,16 +4325,21 @@ class AgentSession:
         new_runtime = get_model_spec(new_model).runtime
         runtime_changed = old_runtime != new_runtime
         if runtime_changed:
             return await self._change_runtime_with_packet_locked(
                 new_model,
                 old_model,
                 old_runtime,
             )
+        if new_runtime == "codex":
+            return await self._change_codex_model_in_place_locked(
+                new_model,
+                old_model,
+            )
         runtime_capabilities = get_runtime(new_runtime).capabilities
         if not runtime_capabilities.resume_across_models:
             return {
                 "ok": False,
                 "error": "runtime cannot prove native resume across models",
                 "error_code": "handoff_native_resume_unsupported",
                 "history_transfer": {"mode": "blocked"},
             }
@@ -4561,16 +4566,99 @@ class AgentSession:
             "native_session_reset": False,
             "history_transfer": {
                 "mode": "native_resume",
                 "preflight": native_preflight.as_dict(),
             },
             "changed": True,
         }
 
+    async def _change_codex_model_in_place_locked(
+        self,
+        new_model: str,
+        old_model: str,
+    ) -> dict:
+        """Retarget the next Codex turn while preserving the exact native thread."""
+        total_tokens = int(self._last_context.get("total_tokens") or 0)
+        target_window = get_model_spec(new_model).context_length
+        if old_model.startswith("gpt-5.6-") and new_model.startswith("gpt-5.6-"):
+            target_window = max(
+                target_window,
+                int(self._last_context.get("max_tokens") or 0),
+            )
+        if total_tokens and target_window and total_tokens > target_window:
+            return {
+                "ok": False,
+                "error": "target context cannot fit the native Codex thread",
+                "error_code": "handoff_context_overflow",
+                "history_transfer": {
+                    "mode": "blocked",
+                    "preflight": {
+                        "fits": False,
+                        "total_tokens": total_tokens,
+                        "target_context_window": target_window,
+                    },
+                },
+            }
+        backend = self._backend
+        if backend is not None:
+            if (
+                getattr(backend, "active_turn_id", None)
+                or getattr(backend, "_events_active", False)
+            ):
+                return {
+                    "ok": False,
+                    "error": "cannot change Codex model while its turn is settling",
+                }
+            if not callable(getattr(backend, "retarget_model", None)):
+                return {
+                    "ok": False,
+                    "error": "Codex backend cannot retarget the active thread",
+                    "error_code": "codex_in_place_switch_unsupported",
+                }
+
+        await self._drain_persist()
+        snapshot = self._to_db_dict()
+        snapshot.update({
+            "model": new_model,
+            "backend_type": "codex",
+        })
+        try:
+            await asyncio.get_running_loop().run_in_executor(
+                _db_executor(), save_session, snapshot,
+            )
+        except Exception as error:
+            return {
+                "ok": False,
+                "error": err_text(error),
+                "error_code": "codex_in_place_switch_persistence_failed",
+            }
+
+        if backend is not None:
+            backend.retarget_model(new_model)
+        self.model = new_model
+        self.backend_type = "codex"
+        self._hibernated = False
+        self._log(
+            "status",
+            f"model change: {old_model} (codex) → {new_model} (codex); "
+            "native thread preserved",
+        )
+        return {
+            "ok": True,
+            "model": new_model,
+            "old_model": old_model,
+            "runtime": "codex",
+            "old_runtime": "codex",
+            "runtime_changed": False,
+            "native_session_reset": False,
+            "history_transfer": {"mode": "native_in_place"},
+            "changed": True,
+        }
+
     async def _disconnect_backend(self) -> None:
         if self._hibernate_task and not self._hibernate_task.done() and self._hibernate_task is not asyncio.current_task():
             self._hibernate_task.cancel()
             self._hibernate_task = None
         backend = self._backend
         if backend:
             await backend.disconnect()
             if self._backend is backend:
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 178ea773a..7538dcd7c 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2631,17 +2631,17 @@ async function _showModelPicker(agentName, currentModel, anchor) {
         item.textContent = `${isCurrent ? '● ' : ''}${m.label}`;
         if (!isCurrent) {
             item.addEventListener('mouseenter', () => item.style.background = 'rgba(51,65,85,0.5)');
             item.addEventListener('mouseleave', () => item.style.background = '');
             item.addEventListener('click', async (e) => {
                 e.stopPropagation();
                 dd.remove();
                 try {
-                    const resp = await api(`/api/sessions/${agentName}/change-model`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ model: m.id, scope: currentScope, fresh: true }) });
+                    const resp = await api(`/api/sessions/${agentName}/change-model`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ model: m.id, scope: currentScope }) });
                     if (resp && !resp.error) {
                         $('#ai-model').textContent = m.id;
                         _showHistoryTransfer(resp.history_transfer);
                         loadSessions();
                     }
                 } catch (e) {
                     const match = String(e.message || '').match(/^\d+:\s*(\{.*\})$/s);
                     if (match) {
diff --git a/tests/test_backend_codex.py b/tests/test_backend_codex.py
index 90e4004f4..80ccf5d4a 100644
--- a/tests/test_backend_codex.py
+++ b/tests/test_backend_codex.py
@@ -1031,16 +1031,40 @@ async def test_send_starts_turn_when_idle():
         "threadId": "thread-1",
         "input": [{"type": "text", "text": "do it"}],
         "model": "gpt-5.6-sol",
         "effort": "high",
     })
     assert backend._active_turn_id == "turn-2"
 
 
+@pytest.mark.asyncio
+async def test_retarget_model_keeps_thread_and_next_turn_uses_new_model():
+    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp")
+    proc = SimpleNamespace(returncode=None)
+    backend._proc = proc
+    backend._thread_id = "thread-1"
+    backend._model_context_window = 828_400
+    backend._request = AsyncMock(return_value={"turn": {"id": "turn-2"}})
+
+    backend.retarget_model("gpt-5.6-sol")
+    await backend.send("continue seamlessly")
+
+    assert backend.model == "gpt-5.6-sol"
+    assert backend.session_id == "thread-1"
+    assert backend._proc is proc
+    assert backend._model_context_window == 828_400
+    backend._request.assert_awaited_once_with("turn/start", {
+        "threadId": "thread-1",
+        "input": [{"type": "text", "text": "continue seamlessly"}],
+        "model": "gpt-5.6-sol",
+        "effort": "high",
+    })
+
+
 @pytest.mark.asyncio
 @pytest.mark.parametrize("loaded", [None, "old-config"])
 async def test_idle_turn_reconnects_stale_managed_config_and_preserves_thread(loaded):
     backend = CodexBackend(
         model="gpt-5.6-sol",
         cwd="/tmp",
         mcp_servers={"orchestra": {
             "command": "python",
diff --git a/tests/test_change_model_unloaded.py b/tests/test_change_model_unloaded.py
index a02cb12f8..d190031cc 100644
--- a/tests/test_change_model_unloaded.py
+++ b/tests/test_change_model_unloaded.py
@@ -30,24 +30,45 @@ async def test_change_model_loads_unloaded_idle_worker(monkeypatch):
     response = await routes.change_model(
         "feat-charts", {"scope": "/s", "model": "gpt-5.6-sol"},
     )
     status, body = _status_body(response)
     assert status == 200
     assert body["ok"] is True
     assert body["model"] == "gpt-5.6-sol"
     routes.manager.ensure_loaded.assert_awaited_once_with("feat-charts", "/s")
-    live.change_model.assert_awaited_once_with("gpt-5.6-sol", fresh=True)
+    live.change_model.assert_awaited_once_with("gpt-5.6-sol", fresh=False)
 
 
 @pytest.mark.asyncio
 async def test_change_model_missing_session_is_404(monkeypatch):
     from app.routes import sessions as routes
 
     monkeypatch.setattr(routes.manager, "get_by_name", lambda *_a, **_k: None)
     monkeypatch.setattr(routes.manager, "ensure_loaded", AsyncMock(return_value=None))
 
     response = await routes.change_model(
         "ghost", {"scope": "/s", "model": "gpt-5.6-sol"},
     )
     status, body = _status_body(response)
     assert status == 404
     assert "error" in body
+
+
+@pytest.mark.asyncio
+async def test_change_model_keeps_explicit_fresh_escape_hatch(monkeypatch):
+    from app.routes import sessions as routes
+
+    live = SimpleNamespace(
+        loaded=True,
+        change_model=AsyncMock(return_value={"ok": True, "changed": True}),
+    )
+    monkeypatch.setattr(routes.manager, "ensure_loaded", AsyncMock(return_value=live))
+
+    response = await routes.change_model(
+        "feat-charts",
+        {"scope": "/s", "model": "gpt-5.6-sol", "fresh": True},
+    )
+
+    status, body = _status_body(response)
+    assert status == 200
+    assert body["ok"] is True
+    live.change_model.assert_awaited_once_with("gpt-5.6-sol", fresh=True)
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index b6c396c99..68d4e8828 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -39,32 +39,32 @@ def test_html_preview_uses_protected_raw_url_and_opaque_origin_sandbox():
     match = re.search(r'<iframe[^`]+sandbox="([^"]+)"', html_branch)
 
     assert match
     assert "openBtn.href = rawUrl;" in html_branch
     assert set(match.group(1).split()) == {"allow-scripts"}
     assert "allow-same-origin" not in match.group(1)
 
 
-def test_model_picker_requests_fresh_session_and_surfaces_transfer_result():
+def test_model_picker_preserves_same_runtime_dialog_and_surfaces_transfer_result():
     source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
     helper = source.split("function _historyTransferMessage", 1)[1].split(
         "async function _showModelPicker", 1,
     )[0]
     picker = source.split("async function _showModelPicker", 1)[1].split(
         "function updateAgentInfo", 1,
     )[0]
 
     assert "server state packet" in helper
     assert "bounded fallback packet" in helper
     assert "native provider thread resumed after total-context preflight" in helper
     assert "dialog switch blocked; source retained" in helper
     assert "fresh target session" in helper
     assert "raw snapshot remains operator-only and untrusted" in helper
-    assert "fresh: true" in picker
+    assert "fresh: true" not in picker
     assert "_showHistoryTransfer(resp.history_transfer);" in picker
     assert "body.error_code" in picker
 
 
 @pytest.mark.asyncio
 @pytest.mark.parametrize("suffix", [".html", ".HTM"])
 async def test_raw_html_response_has_sandbox_csp(tmp_path, monkeypatch, suffix):
     from app.routes import system
diff --git a/tests/test_runtime_handoff_v2.py b/tests/test_runtime_handoff_v2.py
index b1b58b4f9..91967db9b 100644
--- a/tests/test_runtime_handoff_v2.py
+++ b/tests/test_runtime_handoff_v2.py
@@ -942,39 +942,48 @@ async def test_t5_same_provider_native_resume_preflights_smaller_target_window(
     assert result["ok"] is False
     assert result["error_code"] == "handoff_context_overflow"
     assert session.model == "gpt-5.6-sol"
     assert session.session_id == "large-sol-thread"
     source.disconnect.assert_not_awaited()
 
 
 @pytest.mark.asyncio
-async def test_t5_pending_effect_blocks_before_any_target_is_staged(session):
+async def test_t5_pending_effect_does_not_block_in_place_codex_retarget(
+    session, monkeypatch,
+):
     from app.session import AgentStatus
 
     session.model = "gpt-5.6-sol"
     session.backend_type = "codex"
     session.session_id = "source-thread"
     session.status = AgentStatus.IDLE
-    source = AsyncMock()
+    source = SimpleNamespace(
+        active_turn_id=None,
+        _events_active=False,
+        retarget_model=MagicMock(),
+    )
     session._backend = source
     session._log = MagicMock()
     session._prepare_runtime_handoff = AsyncMock(return_value=SimpleNamespace(
         ok=False, error_code="handoff_pending_effect", handoff_id=None,
     ))
     session._ensure_backend = AsyncMock()
+    monkeypatch.setattr("app.session.save_session", MagicMock())
 
     result = await session.change_model("gpt-5.6-luna")
 
-    assert result["ok"] is False
-    assert result["error_code"] == "handoff_pending_effect"
-    assert result["handoff_id"] is None
-    session._ensure_backend.assert_not_awaited()
-    source.disconnect.assert_not_awaited()
+    assert result["ok"] is True
+    assert result["history_transfer"] == {"mode": "native_in_place"}
+    assert session.model == "gpt-5.6-luna"
     assert session.session_id == "source-thread"
+    assert session._backend is source
+    source.retarget_model.assert_called_once_with("gpt-5.6-luna")
+    session._prepare_runtime_handoff.assert_not_awaited()
+    session._ensure_backend.assert_not_awaited()
 
 