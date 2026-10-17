# Candidate cand-36

## ORIGIN commit ab8e392bd8 (2026-07-25): #codex-sleep: stop external-state wait polling
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 6c23654b8..109462f1e 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -840,17 +840,18 @@ def _read_codex_uuid(sessions_path: str, slug: str) -> str:
 @mcp.tool()
 async def codex_review(
     target: str = "",
     output: str = "CODEX_REVIEW.md",
     context: str = "",
     mode: str = "review",
     resume: bool = False,
 ) -> str:
-    """Run Codex (GPT-5.6 Sol) cross-LLM review in background. Returns immediately, notifies when done.
+    """Run Codex (GPT-5.6 Sol) cross-LLM review in background. Returns immediately.
+    After calling, END YOUR TURN NOW; Orchestra wakes you when the job completes.
     target: file path for review, or empty for git diff review.
     output: where to write results (relative to your cwd). Also the session key — reuse the SAME
         output filename to continue a debate.
     context: extra instructions for the review prompt.
     mode: 'review' (git diff, default) or 'exec' (review specific file).
     resume: continue the previous Codex session for this output (debate round). Falls back to a
         fresh session if none stored. On a resumed round put your counter-arguments / changelog
         in context (e.g. 'I fixed X and Y, re-review')."""
@@ -1004,17 +1005,18 @@ async def codex_review(
         "created_by": WORKER_NAME,
     })
     if isinstance(result, dict) and result.get("error"):
         return f"Error creating bg job: {result['error']}"
     job_id = result.get("id", "?")
     resumed_note = f" (resumed session {prev_uuid[:8]})" if is_resume else ""
     return (
         f"Codex {action} started{resumed_note} (bg job {job_id}, 10-min timeout). "
-        f"You WILL be notified on success, timeout, or failure — do NOT poll, just wait. "
+        f"END YOUR TURN NOW — this is required, not optional. Orchestra will wake you "
+        f"when the job succeeds, times out, or fails. "
         f"On success: read {output}. To continue this debate, call codex_review again with the "
         f"SAME output and resume=True. Do not start another codex_review until this one reports back."
     )
 
 
 if __name__ == "__main__":
     _apply_access_mode()
     logger.info(f"Orchestra MCP stdio (url={ORCHESTRA_URL}, scope={SCOPE})")
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 88fd95b73..53d082be3 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -1,14 +1,16 @@
 """Session routes: CRUD, send, stream, merge/switch, model/prompt/description management."""
 
 import asyncio
 import logging
 import re
 import sqlite3
+from contextlib import AsyncExitStack
+from math import ceil
 from pathlib import Path
 from typing import Optional
 
 from fastapi import APIRouter, Request
 from fastapi.responses import JSONResponse
 from starlette.responses import StreamingResponse
 from pydantic import BaseModel, field_validator, model_validator
 
@@ -16,16 +18,31 @@ from app.db import get_logs, get_logs_before, get_all_sessions
 from app.deps import manager
 from app.models import resolve_model, MODELS
 from app.session import AgentStatus
 
 logger = logging.getLogger("orchestra.sessions")
 
 router = APIRouter()
 
+MERGE_IDLE_GRACE_SECONDS = 2.0
+MERGE_IDLE_POLL_SECONDS = 0.05
+
+
+async def _wait_for_merge_idle(session) -> bool:
+    """Absorb the short DONE-message → turn-end transition before merging."""
+    if not session.loaded or session.status.value != "running":
+        return True
+    attempts = max(1, ceil(MERGE_IDLE_GRACE_SECONDS / MERGE_IDLE_POLL_SECONDS))
+    for _ in range(attempts):
+        await asyncio.sleep(MERGE_IDLE_POLL_SECONDS)
+        if session.status.value != "running":
+            return True
+    return False
+
 
 class CreateSessionRequest(BaseModel):
     name: str
     cwd: str
     model: str = "claude-sonnet-5[1m]"
     scope: Optional[str] = None
     system_prompt: str = ""
     use_worktree: bool = False
@@ -623,75 +640,80 @@ async def merge_session(name: str, req: dict):
     from app.workspace import merge_worktree_to_main
     from app import tm as _tm
     scope = req.get("scope", "")
     target = req.get("target", "main")
     next_task_id = req.get("next_task_id", "")
     found = manager.get_by_name(name, scope)
     if not found:
         return JSONResponse({"error": "not found"}, status_code=404)
-    if found.loaded and found.status.value == "running":
-        return JSONResponse({"error": "worker is running — wait for idle before merge"}, status_code=400)
     worktree_path = found.worktree_path
     scope = found.scope or scope
     session_id = found.id
     if not worktree_path:
         return JSONResponse({"error": "session has no worktree"}, status_code=400)
     if not scope:
         return JSONResponse({"error": "session has no scope"}, status_code=400)
     async with manager.get_session_lock(session_id):
-        try:
-            result = await asyncio.to_thread(merge_worktree_to_main, worktree_path, scope, target_branch=target)
-            if result.get("ok"):
-                link_results = {}
-                with _tm._conn() as _lc:
-                    _proj = _tm.get_project_by_scope(_lc, scope)
-                _link_project_id = _proj["id"] if _proj else ""
-                for task_ref, commits in result.pop("merged_commits", {}).items():
-                    try:
-                        link_results[task_ref] = _tm.link_commits_to_task(task_ref, commits, project_id=_link_project_id)
-                    except Exception as link_err:
-                        logger.error("Failed to link commits to %s: %s", task_ref, link_err)
-                        link_results[task_ref] = {"ok": False, "error": str(link_err)}
-                if link_results:
-                    result["linked_tasks"] = link_results
-                # RAG: re-index project's .md + logs now that knowledge is "frozen" into main.
-                # Fire-and-forget — merge must not fail if RAG is off/broken.
-                from app import rag_service
-                if rag_service.is_enabled():
-                    async def _rag_backfill(sc):
+        if not await _wait_for_merge_idle(found):
+            return JSONResponse({"error": "worker is running — wait for idle before merge"}, status_code=400)
+        async with AsyncExitStack() as stack:
+            if found.loaded:
+                await stack.enter_async_context(found._lifecycle_lock)
+                if found.status.value == "running":
+                    return JSONResponse({"error": "worker is running — wait for idle before merge"}, status_code=400)
+            try:
+                result = await asyncio.to_thread(merge_worktree_to_main, worktree_path, scope, target_branch=target)
+                if result.get("ok"):
+                    link_results = {}
+                    with _tm._conn() as _lc:
+                        _proj = _tm.get_project_by_scope(_lc, scope)
+                    _link_project_id = _proj["id"] if _proj else ""
+                    for task_ref, commits in result.pop("merged_commits", {}).items():
                         try:
-                            await rag_service.backfill_scope(sc)
-                        except Exception as e:
-                            logger.warning(f"RAG backfill after merge failed for {sc}: {e}")
-                    asyncio.create_task(_rag_backfill(scope))
-                if found.loaded:
-                    found.branch = target
-                    found.task_id = ""
-                    found.needs_switch = True
-                    found._persist()
-                if next_task_id and found.loaded:
-                    from app.workspace import switch_worktree_branch, _normalize_task_id
-                    par = _normalize_task_id(next_task_id)
-                    new_branch = f"task-{par}/{name}"
-                    switch_result = await asyncio.to_thread(
-                        switch_worktree_branch, worktree_path, new_branch, f"refs/heads/{target}", force=True)
-                    if switch_result.get("ok"):
-                        found.branch = switch_result.get("branch", new_branch)
-                        found.task_id = par
-                        found.needs_switch = False
+                            link_results[task_ref] = _tm.link_commits_to_task(task_ref, commits, project_id=_link_project_id)
+                        except Exception as link_err:
+                            logger.error("Failed to link commits to %s: %s", task_ref, link_err)
+                            link_results[task_ref] = {"ok": False, "error": str(link_err)}
+                    if link_results:
+                        result["linked_tasks"] = link_results
+                    # RAG: re-index project's .md + logs now that knowledge is "frozen" into main.
+                    # Fire-and-forget — merge must not fail if RAG is off/broken.
+                    from app import rag_service
+                    if rag_service.is_enabled():
+                        async def _rag_backfill(sc):
+                            try:
+                                await rag_service.backfill_scope(sc)
+                            except Exception as e:
+                                logger.warning(f"RAG backfill after merge failed for {sc}: {e}")
+                        asyncio.create_task(_rag_backfill(scope))
+                    if found.loaded:
+                        found.branch = target
+                        found.task_id = ""
+                        found.needs_switch = True
                         found._persist()
-                        try:
-                            _tm.api_update_task(par, status="in_progress")
-                        except Exception as e:
-                            logger.warning(f"task #{par} → in_progress failed after merge-switch: {e}")
-                    result["switch"] = switch_result
-            return result
-        except Exception as e:
-            return JSONResponse({"error": str(e)}, status_code=500)
+                    if next_task_id and found.loaded:
+                        from app.workspace import switch_worktree_branch, _normalize_task_id
+                        par = _normalize_task_id(next_task_id)
+                        new_branch = f"task-{par}/{name}"
+                        switch_result = await asyncio.to_thread(
+                            switch_worktree_branch, worktree_path, new_branch, f"refs/heads/{target}", force=True)
+                        if switch_result.get("ok"):
+                            found.branch = switch_result.get("branch", new_branch)
+                            found.task_id = par
+                            found.needs_switch = False
+                            found._persist()
+                            try:
+                                _tm.api_update_task(par, status="in_progress")
+                            except Exception as e:
+                                logger.warning(f"task #{par} → in_progress failed after merge-switch: {e}")
+                        result["switch"] = switch_result
+                return result
+            except Exception as e:
+                return JSONResponse({"error": str(e)}, status_code=500)
 
 
 @router.post("/api/sessions/{name}/switch-branch")
 async def switch_branch(name: str, req: dict):
     from app.workspace import switch_worktree_branch, _normalize_task_id
     from app import tm as _tm
     scope = req.get("scope", "")
     task_id = req.get("task_id", "")
diff --git a/tests/test_api.py b/tests/test_api.py
index 492e10011..b0cf97834 100644
--- a/tests/test_api.py
+++ b/tests/test_api.py
@@ -236,42 +236,191 @@ def test_create_request_base_branch_default_empty():
     # Sentinel "" = авто-резолв базовой ветки по стратегии пайплайна (DESIGN §10).
     # Резолв в "main" происходит в manager/workspace, а не в дефолте запроса.
     from app.routes.sessions import CreateSessionRequest
     req = CreateSessionRequest(name="w1", cwd="/tmp", model="claude-sonnet-5[1m]")
     assert req.base_branch == ""
 
 
 @pytest.mark.asyncio
-async def test_merge_endpoint_passes_target(monkeypatch):
+async def test_merge_endpoint_passes_target(db, monkeypatch):
     import app.main as mainmod
     import app.routes.sessions as sessmod
+    import asyncio
     captured = {}
 
     def fake_merge(worktree_path, repo_path, target_branch="main"):
         captured["target_branch"] = target_branch
         return {"ok": True, "commits_merged": 1, "branch": "task-1/w", "merged_commits": {}}
     monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)
 
     class FakeSession:
         loaded = True
         class _S:
             value = "idle"
         status = _S()
+        _lifecycle_lock = asyncio.Lock()
         worktree_path = "/wt"
         scope = "/s"
         id = "sid"
         name = "w"
+        def _persist(self):
+            pass
     monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: FakeSession())
 
-    import asyncio
     res = await sessmod.merge_session("w", {"scope": "/s", "target": "feature/auth"})
     assert captured["target_branch"] == "feature/auth"
 
 
+@pytest.mark.asyncio
+async def test_merge_waits_for_running_worker_to_finish_turn(db, monkeypatch):
+    import asyncio
+    import app.main as mainmod
+    import app.routes.sessions as sessmod
+
+    class Status:
+        value = "running"
+
+    class FakeSession:
+        loaded = True
+        status = Status()
+        _lifecycle_lock = asyncio.Lock()
+        worktree_path = "/wt"
+        scope = "/s"
+        id = "merge-finish"
+        name = "w"
+
+        def _persist(self):
+            pass
+
+    session = FakeSession()
+    merge_called = False
+
+    async def finish_turn(_delay):
+        session.status.value = "idle"
+
+    def fake_merge(*_args, **_kwargs):
+        nonlocal merge_called
+        merge_called = True
+        return {"ok": True, "merged_commits": {}}
+
+    monkeypatch.setattr(sessmod.asyncio, "sleep", finish_turn)
+    monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)
+    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: session)
+
+    result = await sessmod.merge_session("w", {"scope": "/s"})
+
+    assert result["ok"] is True
+    assert merge_called is True
+
+
+@pytest.mark.asyncio
+async def test_merge_rejects_worker_that_stays_running_without_merging(monkeypatch):
+    import asyncio
+    import app.main as mainmod
+    import app.routes.sessions as sessmod
+
+    class Status:
+        value = "running"
+
+    class FakeSession:
+        loaded = True
+        status = Status()
+        _lifecycle_lock = asyncio.Lock()
+        worktree_path = "/wt"
+        scope = "/s"
+        id = "merge-running"
+        name = "w"
+
+    session = FakeSession()
+    merge_called = False
+
+    async def no_wall_clock_wait(_delay):
+        return None
+
+    def fake_merge(*_args, **_kwargs):
+        nonlocal merge_called
+        merge_called = True
+        return {"ok": True, "merged_commits": {}}
+
+    monkeypatch.setattr(sessmod.asyncio, "sleep", no_wall_clock_wait)
+    monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)
+    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: session)
+
+    response = await sessmod.merge_session("w", {"scope": "/s"})
+
+    assert response.status_code == 400
+    assert merge_called is False
+
+
+@pytest.mark.asyncio
+async def test_merge_and_switch_hold_lifecycle_lock_against_worker_wakeup(db, monkeypatch):
+    import asyncio
+    import threading
+    import app.main as mainmod
+    import app.routes.sessions as sessmod
+
+    observed = {"persist_locked": []}
+
+    class Status:
+        value = "idle"
+
+    class FakeSession:
+        loaded = True
+        status = Status()
+        _lifecycle_lock = asyncio.Lock()
+        worktree_path = "/wt"
+        scope = "/s"
+        id = "merge-switch-lock"
+        name = "w"
+
+        def _persist(self):
+            observed["persist_locked"].append(self._lifecycle_lock.locked())
+
+    session = FakeSession()
+    loop = asyncio.get_running_loop()
+    wake_attempted = threading.Event()
+    wake_entered = asyncio.Event()
+
+    async def wake_worker():
+        wake_attempted.set()
+        async with session._lifecycle_lock:
+            wake_entered.set()
+
+    def fake_merge(*_args, **_kwargs):
+        observed["merge_locked"] = session._lifecycle_lock.locked()
+        loop.call_soon_threadsafe(lambda: asyncio.create_task(wake_worker()))
+        assert wake_attempted.wait(1)
+        return {"ok": True, "merged_commits": {}}
+
+    def fake_switch(*_args, **_kwargs):
+        observed["switch_locked"] = session._lifecycle_lock.locked()
+        observed["wake_blocked_during_switch"] = not wake_entered.is_set()
+        return {"ok": True, "branch": "task-43/w"}
+
+    monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)
+    monkeypatch.setattr("app.workspace.switch_worktree_branch", fake_switch)
+    monkeypatch.setattr("app.rag_service.is_enabled", lambda: False)
+    monkeypatch.setattr("app.tm.api_update_task", lambda *_args, **_kwargs: None)
+    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: session)
+
+    result = await sessmod.merge_session("w", {
+        "scope": "/s",
+        "target": "main",
+        "next_task_id": "43",
+    })
+    await asyncio.wait_for(wake_entered.wait(), timeout=1)
+
+    assert result["switch"]["ok"] is True
+    assert observed["merge_locked"] is True
+    assert observed["switch_locked"] is True
+    assert observed["wake_blocked_during_switch"] is True
+    assert observed["persist_locked"] and all(observed["persist_locked"])
+
+
 class TestPipelines:
     def test_list_valid_only(self, client):
         r = client.get("/api/pipelines")
         assert r.status_code == 200
         data = r.json()
         names = [p["name"] for p in data]
         assert "default" in names
         # все возвращённые — валидны (поле valid не отдаётся, но битых быть не должно)
diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index a882c1c7a..0b668b50c 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -191,16 +191,23 @@ class TestDefaultBuildSystemPrompt:
         assert "mcp__orchestra__send_message" in out
 
     def test_all_roles_forbid_acknowledgement_loops(self):
         for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle"):
             out = P.build_system_prompt(PIPELINE, role)
             assert "Never send acknowledgement-only messages" in out
             assert "do not reply and end the turn silently" in out
 
+    def test_all_roles_end_turn_instead_of_waiting_for_external_state(self):
+        for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle"):
+            out = P.build_system_prompt(PIPELINE, role)
+            assert "Never sleep or poll for a background job, review, or another agent" in out
+            assert "End the turn; Orchestra resumes you on completion" in out
+            assert "Sleeps inside tests or bounded restart checks are allowed" in out
+
     def test_orchestrator_prompt_contains_role_body_markers(self):
         """Характеризация: ключевые XML-секции тела orchestrator.md на месте."""
         out = P.build_system_prompt(PIPELINE, "orchestrator")
         # v2.16 upstream убрал секцию <parallel-tasks> из тела orchestrator —
         # её содержимое переехало в "Merge & kill safety"/правила.
         for marker in ("<decision-tree>", "<tools>", "<worker-management>",
                        "<task-workflow>"):
             assert marker in out, f"missing orchestrator marker {marker}"
diff --git a/tests/test_mcp_codex_review.py b/tests/test_mcp_codex_review.py
index 7d341981e..20c242456 100644
--- a/tests/test_mcp_codex_review.py
+++ b/tests/test_mcp_codex_review.py
@@ -14,21 +14,27 @@ async def test_codex_review_uses_temp_artifact_and_declares_success_contract(tmp
             return {"cwd": str(tmp_path), "worktree_path": str(tmp_path), "scope": str(tmp_path)}
         captured.update(kwargs["json"])
         return {"id": "bg-test"}
 
     monkeypatch.setattr(mcp, "_api", fake_api)
     monkeypatch.setattr(mcp, "WORKER_NAME", "sol-pilot")
     monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))
 
+    assert "END YOUR TURN NOW" in mcp.codex_review.__doc__
     result = await mcp.codex_review(
         target="research.md", output="docs/review.md", mode="exec",
     )
 
     assert "bg-test" in result
+    assert "END YOUR TURN NOW" in result
+    assert "required, not optional" in result
+    assert "Orchestra will wake you" in result
+    assert "do NOT poll" not in result
+    assert "just wait" not in result
     config = captured["config"]
     output = str(tmp_path / "docs/review.md")
     assert config["success_file"] == output
     assert "Verdict" in config["success_pattern"]
     command = config["command"]
     assert f"-o {output}.round" in command
     assert "codex_review_artifact.py" in command
     assert "--require-verdict" in command


## LATER FIX c3c9e20715 (23.3 days later): #313: #313: route merge helper for request fixture in tests
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

#313: #313: route merge helper for request fixture in tests


diff --git a/tests/test_api.py b/tests/test_api.py
index 5547ad24c..b2955981d 100644
--- a/tests/test_api.py
+++ b/tests/test_api.py
@@ -33,16 +33,24 @@ def client(db):
     from tests.conftest import make_backend_mock
     with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
         from app.main import app, manager
         manager.sessions.clear()
         with TestClient(app) as c:
             yield c
 
 
+def _merge_session_request():
+    return SimpleNamespace(cookies={}, headers={})
+
+
+async def _call_merge_session(sessmod, name: str, req: dict):
+    return await sessmod.merge_session(name, req, _merge_session_request())
+
+
 def _save_merge_session_record(session) -> None:
     from datetime import datetime, timezone
     from app.db import save_session
 
     save_session({
         "id": session.id,
         "name": session.name,
         "scope": session.scope,
@@ -939,17 +947,17 @@ async def test_merge_endpoint_passes_target(db, monkeypatch):
         id = "sid"
         name = "w"
         branch = "task-1/w"
         def _persist(self):
             pass
     session = FakeSession()
     monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: session)
 
-    res = await sessmod.merge_session("w", {"scope": "/s", "target": "feature/auth"})
+    res = await _call_merge_session(sessmod, "w", {"scope": "/s", "target": "feature/auth"})
     assert captured["session_id"] == "sid"
     assert captured["expected_branch"] == "task-1/w"
     assert captured["req"]["target"] == "feature/auth"
     assert res["ok"] is True
 
 
 @pytest.mark.asyncio
 @pytest.mark.parametrize("loaded", [False, True])
@@ -998,17 +1006,17 @@ async def test_merge_persists_actual_branch_and_base_for_loaded_or_detached(
         },
     )
     monkeypatch.setattr(
         "app.workspace.inspect_worktree_identity",
         lambda _path: ("task-90/w", "a" * 40),
     )
     monkeypatch.setattr("app.rag_service.is_enabled", lambda: False)
 
-    result = await sessmod.merge_session(f"merge-{loaded}", {"scope": "/s"})
+    result = await _call_merge_session(sessmod, f"merge-{loaded}", {"scope": "/s"})
 
     assert result["ok"] is True
     row = get_session(f"merge-{loaded}")
     assert (row["branch"], row["base_branch"], row["task_id"], row["needs_switch"]) == (
         "task-90/w", "master", "", 1,
     )
     assert found.branch == "task-90/w"
     assert found.base_branch == "master"
@@ -1049,17 +1057,17 @@ async def test_merge_rejects_ambiguous_legacy_base_before_git(db, monkeypatch):
         sessmod,
         "_session_base_branch",
         lambda *_args, **_kwargs: (_ for _ in ()).throw(
             ValueError("cannot resolve repository mainline; pass base_branch explicitly")
         ),
     )
     monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)
 
-    response = await sessmod.merge_session("legacy", {"scope": "/s"})
+    response = await _call_merge_session(sessmod, "legacy", {"scope": "/s"})
 
     assert response.status_code == 400
     assert merge_called is False
 
 
 @pytest.mark.asyncio
 async def test_merge_links_commits_with_normalized_sqlite_results(db, monkeypatch):
     import json
@@ -1104,17 +1112,17 @@ async def test_merge_links_commits_with_normalized_sqlite_results(db, monkeypatc
         },
     )
     monkeypatch.setattr(
         "app.workspace.inspect_worktree_identity",
         lambda _path: (session.branch, "a" * 40),
     )
     monkeypatch.setattr("app.rag_service.is_enabled", lambda: False)
 
-    result = await sessmod.merge_session("worker", {"scope": "/s"})
+    result = await _call_merge_session(sessmod, "worker", {"scope": "/s"})
 
     assert result["linked_tasks"]["90"] == {
         "ok": True,
         "added": 1,
         "task_id": task["id"],
     }
     assert result["linked_tasks"]["999"] == {
         "ok": False,
@@ -1158,17 +1166,17 @@ async def test_merge_links_duplicate_par_only_in_worker_scope_project(db, monkey
             "commits_merged": 1,
             "branch": session.branch,
             "merged_commits": {
                 "1": [{"hash": "abc123", "message": "#1: work"}],
             },
         },
     )
 
-    result = await sessmod.merge_session("worker", {"scope": "/lower"})
+    result = await _call_merge_session(sessmod, "worker", {"scope": "/lower"})
 
     assert result["linked_tasks"]["1"] == {
         "ok": True, "added": 1, "task_id": lower["id"],
     }
     with tm._conn() as conn:
         assert json.loads(tm.get_task_by_id(conn, upper["id"])["git_commits"]) == []
         linked = json.loads(tm.get_task_by_id(conn, lower["id"])["git_commits"])
         assert [item["hash"] for item in linked] == ["abc123"]
@@ -1200,17 +1208,17 @@ async def test_merge_rejects_invalid_or_missing_next_task_before_git(
         "app.workspace.inspect_worktree_identity",
         lambda *_args: (_ for _ in ()).throw(AssertionError("Git inspection must not run")),
     )
     monkeypatch.setattr(
         "app.workspace.merge_worktree_to_main",
         lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("merge must not run")),
     )
 
-    response = await sessmod.merge_session(
+    response = await _call_merge_session(sessmod,
         "worker", {"scope": "/s", "next_task_id": next_task_id},
     )
 
     assert response.status_code == 400
 
 
 @pytest.mark.asyncio
 async def test_execute_merge_session_rejects_removed_and_respawned_identity(db, monkeypatch):
@@ -1441,17 +1449,17 @@ async def test_merge_revision_change_keeps_git_success_and_skips_task_update(
                 "merged_commits": {}}
 
     monkeypatch.setattr("app.workspace.merge_worktree_to_main", merge_and_change_revision)
     monkeypatch.setattr(
         "app.workspace.switch_worktree_branch",
         lambda *_args, **_kwargs: {"ok": True, "branch": "task-43/worker"},
     )
 
-    result = await sessmod.merge_session(
+    result = await _call_merge_session(sessmod,
         "worker", {"scope": "/s", "next_task_id": "43"},
     )
 
     assert result["ok"] is True
     assert result["switch"]["ok"] is True
     assert result["task_status"]["ok"] is False
     assert "revision" in result["task_status"]["error"]
     assert result["task_status"]["quarantined"] is True
@@ -1487,17 +1495,17 @@ async def test_merge_next_updates_only_case_variant_in_worker_scope(db, monkeypa
             "merged_commits": {},
         },
     )
     monkeypatch.setattr(
         "app.workspace.switch_worktree_branch",
         lambda *_args, **_kwargs: {"ok": True, "branch": "task-43/worker"},
     )
 
-    result = await sessmod.merge_session(
+    result = await _call_merge_session(sessmod,
         "worker", {"scope": "/lower", "next_task_id": "43"},
     )
 
     assert result["task_status"]["ok"] is True
     with tm._conn() as conn:
         assert tm.get_task_by_id(conn, upper["id"])["status"] == "new"
         assert tm.get_task_by_id(conn, lower["id"])["status"] == "in_progress"
 
@@ -1531,17 +1539,17 @@ async def test_merge_switch_failure_stays_merge_success_and_keeps_quarantine(
             "merged_commits": {},
         },
     )
     monkeypatch.setattr(
         "app.workspace.switch_worktree_branch",
         lambda *_args, **_kwargs: {"ok": False, "error": "target is dirty"},
     )
 
-    result = await sessmod.merge_session(
+    result = await _call_merge_session(sessmod,
         "worker", {"scope": "/s", "next_task_id": "43"},
     )
 
     assert result["ok"] is True
     assert result["switch"] == {"ok": False, "error": "target is dirty"}
     assert result["task_status"]["ok"] is False
     with tm._conn() as conn:
         assert tm.get_task_by_id(conn, task["id"])["status"] == "new"
@@ -1582,17 +1590,17 @@ async def test_merge_switch_exception_stays_merge_success_and_keeps_quarantine(
     )
     monkeypatch.setattr(
         "app.workspace.switch_worktree_branch",
         lambda *_args, **_kwargs: (_ for _ in ()).throw(
             RuntimeError("simulated switch crash")
         ),
     )
 
-    result = await sessmod.merge_session(
+    result = await _call_merge_session(sessmod,
         "worker", {"scope": "/s", "next_task_id": "43"},
     )
 
     assert result["ok"] is True
     assert result["switch"]["ok"] is False
     assert "simulated switch crash" in result["switch"]["error"]
     assert result["task_status"]["ok"] is False
     with tm._conn() as conn:
@@ -1635,17 +1643,17 @@ async def test_merge_quarantine_persistence_retries_before_returning(
     monkeypatch.setattr(
         "app.workspace.merge_worktree_to_main",
         lambda *_args, **_kwargs: {
             "ok": True, "commits_merged": 1, "branch": session.branch,
             "merged_commits": {},
         },
     )
 
-    result = await sessmod.merge_session("worker", {"scope": "/s"})
+    result = await _call_merge_session(sessmod, "worker", {"scope": "/s"})
 
     assert result["ok"] is True
     assert result["lifecycle_status"] == {
         "ok": True, "recovered": True, "warning": "RuntimeError: transient DB failure",
     }
     assert persist_calls == 2
     row = get_session(session.id)
     assert (row["task_id"], row["needs_switch"], row["branch"]) == (
@@ -1693,17 +1701,17 @@ async def test_merge_switch_persistence_failure_is_partial_and_keeps_task_unchan
             "merged_commits": {},
         },
     )
     monkeypatch.setattr(
         "app.workspace.switch_worktree_branch",
         lambda *_args, **_kwargs: {"ok": True, "branch": "task-43/worker"},
     )
 
-    result = await sessmod.merge_session(
+    result = await _call_merge_session(sessmod,
         "worker", {"scope": "/s", "next_task_id": "43"},
     )
 
     assert result["ok"] is True
     assert result["switch"]["ok"] is False
     assert result["switch"]["state"] == "persistence_failed"
     assert "branch switched to task-43/worker" in result["switch"]["error"]
     assert result["task_status"]["ok"] is False
@@ -1749,17 +1757,17 @@ async def test_merge_task_db_exception_is_explicit_without_reversing_git_success
         lambda *_args, **_kwargs: {"ok": True, "branch": "task-43/worker"},
     )
     monkeypatch.setattr(
         tm,
         "api_update_task_if_current",
         lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()),
     )
 
-    result = await sessmod.merge_session(
+    result = await _call_merge_session(sessmod,
         "worker", {"scope": "/s", "next_task_id": "43"},
     )
 
     assert result["ok"] is True
     assert result["switch"]["ok"] is True
     assert result["task_status"] == {
         "ok": False, "error": "RuntimeError", "quarantined": True,
     }
@@ -2454,17 +2462,17 @@ async def test_merge_waits_for_running_worker_to_finish_turn(db, monkeypatch):
     monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "master")
 
     async def persist_lifecycle(_session, **_fields):
         return None
 
     monkeypatch.setattr(mainmod.manager, "persist_lifecycle", persist_lifecycle)
 
     merge_task = asyncio.create_task(
-        sessmod.merge_session("w", {"scope": "/s"}),
+        _call_merge_session(sessmod, "w", {"scope": "/s"}),
     )
     await asyncio.wait_for(wait_started.wait(), timeout=0.2)
     assert merge_called is False
     assert merge_task.done() is False
 
     session.status.value = "idle"
     turn_finished.set()
     result = await asyncio.wait_for(merge_task, timeout=0.2)
@@ -2506,17 +2514,17 @@ async def test_merge_rejects_waiting_worker_without_merging(db, monkeypatch):
     monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: session)
     monkeypatch.setattr(mainmod.manager, "get", lambda _session_id: session)
     monkeypatch.setattr(
         "app.workspace.inspect_worktree_identity",
         lambda _path: (session.branch, "a" * 40),
     )
     monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "master")
 
-    response = await sessmod.merge_session("w", {"scope": "/s"})
+    response = await _call_merge_session(sessmod, "w", {"scope": "/s"})
 
     assert response.status_code == 400
     assert "waiting" in response.body.decode()
     assert merge_called is False
 
 
 @pytest.mark.asyncio
 async def test_switch_waits_for_running_worker_to_finish_turn(db, monkeypatch):
@@ -2671,17 +2679,17 @@ async def test_merge_and_switch_hold_lifecycle_lock_against_worker_wakeup(db, mo
         lambda _path: (session.branch, "a" * 40),
     )
     monkeypatch.setattr(mainmod.manager, "persist_lifecycle", persist_lifecycle)
     monkeypatch.setattr(
         sessmod, "_session_base_branch",
         lambda _session, requested="": requested or "master",
     )
 
-    result = await sessmod.merge_session("w", {
+    result = await _call_merge_session(sessmod, "w", {
         "scope": "/s",
         "target": "main",
         "next_task_id": "43",
     })
     await asyncio.wait_for(wake_entered.wait(), timeout=1)
 
     assert result["switch"]["ok"] is True
     assert observed["merge_locked"] is True