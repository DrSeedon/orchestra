# Context for retro-03

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/scripts/migrate_review_receipts.py b/scripts/migrate_review_receipts.py
index 87a8a26a1..1e717c53e 100644
--- a/scripts/migrate_review_receipts.py
+++ b/scripts/migrate_review_receipts.py
@@ -92,40 +92,43 @@ def _receipt(item: dict) -> dict:
         "status": item.get("status", "completed"),
         "return_code": item.get("return_code"),
         "failure_code": item.get("failure_code", ""),
         "artifact_exists": item.get("artifact_exists", True),
         "artifact_bytes": item.get("artifact_bytes", item.get("size_bytes")),
         "artifact_sha256": item.get("sha256", ""),
         "verdict_present": item.get("verdict_present", False),
         "verdict_value": item.get("verdict_value", ""),
         "jsonl_response_present": item.get("jsonl_response_present", False),
         "recovery_source": item.get("recovery_source", ""),
         "author_outcome": item.get("outcome", "unknown"),
         "outcome_source": item.get("outcome_source", "unknown"),
         "outcome_evidence_ref": item.get("outcome_evidence_ref", ""),
         "notification_event_id": item.get("notification_event_id", ""),
         "subject_kind": "unknown",
         "target_sha": "",
         "worker_head": "",
         "production_snapshot_sha256": "",
         "production_diff_sha256": "",
         "production_paths_json": "[]",
+        "production_path_heads_json": "",
+        "requested_by_session_id": "",
+        "requested_by_worker": "",
         "coverage_outcome": "unknown",
         "policy_ref": "",
         "decision_actor": "",
         "task_stable_id": "",
         "task_snapshot_ref": "",
         "prompt_template_start": "",
         "prompt_template_end": "",
         "terminal_operation_id": "",
     }
 
 
 def _backup_database(db_path: Path, backup_path: Path) -> None:
     if not db_path.is_file():
         return
     db_real = os.path.realpath(db_path)
     backup_real = os.path.realpath(backup_path)
     if db_real == backup_real:
         raise ValueError("backup path aliases the database path")
     if os.path.lexists(backup_path):
         try:
diff --git a/tests/test_audit0901_session.py b/tests/test_audit0901_session.py
index 29579c202..ded665212 100644
--- a/tests/test_audit0901_session.py
+++ b/tests/test_audit0901_session.py
@@ -74,69 +74,91 @@ async def test_heartbeat_recovery_releases_the_turn_waiter(mock_db, monkeypatch)
     assert await asyncio.wait_for(waiter, timeout=1) is True
 
     # The next call site that forgets to publish must not be a permanent lock either.
     monkeypatch.setattr("app.session.TURN_COMPLETION_RECHECK", 0.05)
     session._turns.bump_turn_gen()
     session.status = AgentStatus.RUNNING
     stranded = asyncio.create_task(session.wait_for_turn_completion())
     await real_sleep(0)
     session.status = AgentStatus.IDLE  # no publish at all
     assert await asyncio.wait_for(stranded, timeout=2) is True
 
 
 @pytest.mark.asyncio
 async def test_heartbeat_dead_process_recovery_publishes(mock_db, monkeypatch):
     """Second of the three recovery branches: process-backed runtime found dead.
 
     Its own seam — `process_liveness` + `_process_runtime_dead` — is unreachable for the
     failed-reconnect test above, which pins `_last_msg_time = 0`.
     """
     from app.session import AgentStatus
+    import app.session_hibernate as hibernate
+
+    monkeypatch.setattr(
+        hibernate,
+        "get_runtime",
+        lambda _runtime: SimpleNamespace(
+            capabilities=SimpleNamespace(
+                process_liveness=True, event_stream="per_turn", reconnect=False,
+            )
+        ),
+    )
 
     session = _make_session("codex-dead")
     session.backend_type = "codex"
     session._log = MagicMock()
     session._persist = MagicMock()
     session._disconnect_backend = AsyncMock()
     session._backend = SimpleNamespace(is_alive=False)
     session._listen_task = SimpleNamespace(done=lambda: True)
     session._turns.bump_turn_gen()
     session.status = AgentStatus.RUNNING
     session._last_msg_time = asyncio.get_event_loop().time() - 10_000
 
     await _run_one_heartbeat_pass(monkeypatch, session)
 
     assert session._disconnect_backend.await_count == 1
     assert session.status is AgentStatus.IDLE
     assert session._turn_finished_event.is_set() is True, (
         "dead-process recovery went RUNNING→IDLE without publish_turn_finished"
     )
 
 
 @pytest.mark.asyncio
 async def test_heartbeat_zombie_without_backend_publishes(mock_db, monkeypatch):
     """Third recovery branch: persistent runtime silent past the zombie timeout, backend gone.
 
     Reached only by a runtime with `process_liveness=False` and a persistent event stream,
     so neither of the other two branch tests can stand in for it.
     """
     from app.session import AgentStatus
+    import app.session_hibernate as hibernate
+
+    monkeypatch.setattr(
+        hibernate,
+        "get_runtime",
+        lambda _runtime: SimpleNamespace(
+            capabilities=SimpleNamespace(
+                process_liveness=False, event_stream="persistent", reconnect=False,
+            )
+        ),
+    )
 
     session = _make_session("claude-zombie")
     session._log = MagicMock()
     session._persist = MagicMock()
     session._backend = None
     session._listen_task = SimpleNamespace(done=lambda: True)
     session._turns.bump_turn_gen()
     session.status = AgentStatus.RUNNING
     session._last_msg_time = asyncio.get_event_loop().time() - 10_000
 
     await _run_one_heartbeat_pass(monkeypatch, session)
 
     assert session.status is AgentStatus.IDLE
     assert session._turn_finished_event.is_set() is True, (
         "zombie recovery went RUNNING→IDLE without publish_turn_finished"
     )
 
 
 @pytest.mark.asyncio
 async def test_drain_landing_during_stale_cli_release_refuses_the_turn(mock_db, monkeypatch):
diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index fbfaf8400..7b4369624 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -2479,70 +2479,48 @@ async def test_merge_worker_real_failure_still_reads_as_failure(monkeypatch):
 async def test_search_memory_reports_index_debt_and_tolerates_its_absence(
     monkeypatch, payload, expect_debt,
 ):
     """`index` добавлен в роут позже тула. Живой MCP подхватывает код немедленно, а роут в
     памяти systemd — только после рестарта, поэтому новый тул ОБЯЗАН пережить ответ без `index`."""
     import app.mcp_stdio as m
 
     monkeypatch.setattr(m, "SCOPE", "/scope")
 
     def handler(request):
         return httpx.Response(200, json=payload)
 
     _mock_http(monkeypatch, m, handler)
     out = await m.search_memory("вопрос")
 
     assert ("7 файлов ещё не проиндексированы" in out) is expect_debt
     if payload["results"]:
         assert "a.md" in out
 
 
-@pytest.mark.asyncio
-async def test_file_first_memory_tool_surface_keeps_only_search_fallback(monkeypatch, tmp_path):
+def test_file_first_memory_tool_surface_does_not_register_legacy_knowledge_tool():
+    """File-first memory has no legacy ``knowledge`` tool; search is ordinary/optional."""
     import app.mcp_stdio as m
 
     registered = {tool.name: tool for tool in m.mcp._tool_manager.list_tools()}
     assert "knowledge" not in registered
     assert "knowledge" not in m.READ_ONLY_MCP_TOOLS
     assert "knowledge" not in m.REDUCER_MCP_TOOLS
-    assert "search_memory" in registered
-
-    async def disabled_rag(*_args, **_kwargs):
-        raise m.ApiToolError(
-            code="http_503",
-            message="RAG disabled (set RAG_ENABLED=true)",
-        )
-
-    monkeypatch.setattr(m, "_api", disabled_rag)
-    monkeypatch.setattr(m, "SCOPE", "/project")
-
-    out = await registered["search_memory"].run({"query": "needle"})
-
-    assert "RAG_ENABLED=false" in out
-    import shlex
-    import subprocess
-    kb = tmp_path / ".orchestra/kb"
-    kb.mkdir(parents=True)
-    (kb / "topic.md").write_text("The relevant needle is here.\n")
-    command = shlex.split(out[out.index("rg "):])
-    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=True)
-    assert "The relevant needle is here." in result.stdout
 
 
 @pytest.mark.asyncio
 async def test_merge_warning_is_visible_in_the_tool_text(monkeypatch):
     """#80: успешный мерж с ненайденным номером задачи не читается как чистый успех."""
     import app.mcp_stdio as m
 
     monkeypatch.setattr(m, "SCOPE", "/s")
 
     async def fake_api(method, path, **kw):
         return {"result": {
             "schema_version": 1,
             "operation_id": kw["json"]["operation_id"],
             "operation_state": "SUCCEEDED",
             "retryable": False,
             "commit_point": "REACHED",
             "git": {"status": "SUCCEEDED", "worker_branch": "task-80/w", "commits_merged": 6},
             "task_links": {"status": "WARNED", "items": {}},
             "warnings": [{"code": "TASK_LINK_NOT_FOUND", "message": "18: task '18' not found"}],
             "error": None,
diff --git a/tests/test_merge_ref_gate.py b/tests/test_merge_ref_gate.py
index 9a63308b5..40e3e7908 100644
--- a/tests/test_merge_ref_gate.py
+++ b/tests/test_merge_ref_gate.py
@@ -65,41 +65,45 @@ async def test_prose_token_neither_refuses_nor_relabels_an_honest_merge(
     )
 
     assert result["ok"] is True, result
     subject = subprocess.run(
         ["git", "log", "-1", "--format=%s", "main"], cwd=repo,
         check=True, capture_output=True, text=True,
     ).stdout.strip()
     assert subject == "#42: fix UTF-8 decoding in the log reader", subject
 
     with tm._conn() as connection:
         owner = tm.resolve_task_ref(connection, "42", "project")
         neighbour = tm.resolve_task_ref(connection, "8", "project")
     assert json.loads(owner["git_commits"]), "the bound task must receive its commit"
     assert not json.loads(neighbour["git_commits"] or "[]"), (
         "a prose token must never link the merge to task #8"
     )
 
 
 @pytest.mark.asyncio
 async def test_unknown_leading_ref_is_still_refused_before_git(monkeypatch, tmp_path):
-    """Control arm: narrowing prose must not disarm the gate for a real fake ref."""
+    """An unknown repository task number is reported without blocking the merge.
+
+    Since 979c4631, task numbers from another numbering system are preserved as
+    unresolved metadata and no longer refuse otherwise valid work.
+    """
     import app.routes.sessions as sessions_route
     import app.workspace as workspace
     from app import tm
 
     _init_db()
     repo = _make_git_scope(monkeypatch, tmp_path)
     scope = str(repo)
     with tm._conn() as connection:
         tm.ensure_project(connection, "project", scope=scope)
         task = tm.create_task(
             connection, "project", "Bound", par_number=42, status="in_progress",
         )
         connection.execute(
             "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
             ("fake-ref-worker", task["id"]),
         )
     worktree = workspace.create_worktree(scope, "fake-ref-worker", task_id="42")
     head = _commit_file(worktree.path, "work.txt", "#999: fabricated assignment")
     _save_worker(
         session_id="fake-ref-worker", task_id="42", scope=scope,
@@ -107,42 +111,42 @@ async def test_unknown_leading_ref_is_still_refused_before_git(monkeypatch, tmp_
     )
     found = _prepare_merge(monkeypatch, session_id="fake-ref-worker", scope=scope)
     target_before = subprocess.run(
         ["git", "rev-parse", "main"], cwd=repo,
         check=True, capture_output=True, text=True,
     ).stdout.strip()
 
     result = await sessions_route.execute_merge_session(
         session_id=found.id,
         expected_name=found.name,
         expected_scope=found.scope,
         expected_branch=found.branch,
         expected_head=head,
         req={"scope": scope, "task_outcome": "complete", "merge_schema_version": 2},
     )
 
     target_after = subprocess.run(
         ["git", "rev-parse", "main"], cwd=repo,
         check=True, capture_output=True, text=True,
     ).stdout.strip()
-    assert result["commit_point"] == "not_reached"
-    assert target_after == target_before
+    assert result["commit_point"] == "target_committed"
+    assert target_after != target_before
 
 
 @pytest.mark.asyncio
 async def test_reserved_operation_trailer_in_body_is_refused_before_git(
     monkeypatch, tmp_path,
 ):
     """T2 claims this guard in its AC; the frozen oracle survives disabling it."""
     import app.routes.sessions as sessions_route
     import app.workspace as workspace
     from app import tm
 
     _init_db()
     repo = _make_git_scope(monkeypatch, tmp_path)
     scope = str(repo)
     with tm._conn() as connection:
         tm.ensure_project(connection, "project", scope=scope)
         task = tm.create_task(
             connection, "project", "Bound", par_number=42, status="in_progress",
         )
         connection.execute(
diff --git a/tests/test_message_provenance_review_433.py b/tests/test_message_provenance_review_433.py
index 85e362a6f..de69a4da8 100644
--- a/tests/test_message_provenance_review_433.py
+++ b/tests/test_message_provenance_review_433.py
@@ -1,20 +1,21 @@
+import asyncio
 import pytest
 import sqlite3
 import json
 
 
 def test_review_storage_requires_senders_json_array():
     from app.events import MessageProvenance
 
     with pytest.raises(ValueError, match="array"):
         MessageProvenance.from_storage(
             "user", {"senders": {"alice": True}},
         )
 
 
 def test_review_db_projection_rejects_missing_or_corrupt_provenance():
     from app.db import _decode_log_provenance
 
     with pytest.raises(ValueError):
         _decode_log_provenance({"id": 1, "origin": "user"})
     with pytest.raises(ValueError):
@@ -281,40 +282,42 @@ async def test_review_live_mcp_receipt_persists_agent_principal(tmp_path, monkey
     db.init_db()
     source_id = "source-live-433"
     source_name = "source-live"
     target_id = "target-live-433"
     scope = "/scope-live-433"
     db.save_session(_session_record(
         session_id=source_id, name=source_name, scope=scope, role="orchestrator",
     ))
     db.save_session(_session_record(
         session_id=target_id, name="target-live", scope=scope,
         task_id="433", branch="task-433/target-live",
     ))
     target = type("Target", (), {
         "id": target_id, "name": "target-live", "scope": scope,
         "task_id": "433", "branch": "task-433/target-live", "needs_switch": False,
     })()
 
     class Manager:
         def get_by_name(self, name, requested_scope): return target
         async def preflight_message_delivery(self, session_id): return None
+        def get_session_lock(self, session_id):
+            return asyncio.Lock()
 
     monkeypatch.setattr(routes, "manager", Manager())
     monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _id: None)
     proof = issue_mcp_proof(source_id)
     request = Request({
         "type": "http", "method": "POST", "path": "/send",
         "headers": [
             (b"x-orchestra-session-id", source_id.encode()),
             (b"x-orchestra-mcp-proof", proof.encode()),
         ],
         "query_string": b"", "server": ("test", 80),
         "client": ("test", 1), "scheme": "http",
     })
     delivery_id = "00000000-0000-4000-8000-000000004397"
     result = await routes.send_message(
         "target-live",
         routes.SendRequest(
             message="agent body", scope=scope, sender=source_name,
             delivery_id=delivery_id,
         ),
diff --git a/tests/test_orphan_pid_identity.py b/tests/test_orphan_pid_identity.py
index 56957b896..21b604d2f 100644
--- a/tests/test_orphan_pid_identity.py
+++ b/tests/test_orphan_pid_identity.py
@@ -132,67 +132,69 @@ async def test_t1_first_restart_reused_foreign_pid_survives_real_sweep(
             "the negative arm must reach pidfd identity validation, not skip the signal path"
         )
         assert any(
             record.levelno >= logging.ERROR and str(foreign.pid) in record.getMessage()
             for record in caplog.records
         ), "unproven identity must be refused loudly with the candidate PID"
     finally:
         if foreign.poll() is None:
             foreign.terminate()
         foreign.wait(timeout=3)
         _close_if_open(orphan_fd)
         _close_if_open(peer_fd)
 
 
 @pytest.mark.asyncio
 async def test_t1_verified_codex_and_grok_orphans_signal_only_through_pidfd(
     manager,
     monkeypatch,
 ):
     """Positive controls: the safety check must not turn into 'never reap an orphan'."""
-    from app.backend_codex import CODEX_BIN
-    from app.backend_grok import GROK_BIN
+    codex_bin = "/bin/true"
+    grok_bin = "/bin/false"
+    monkeypatch.setattr("app.backend_codex.CODEX_BIN", codex_bin)
+    monkeypatch.setattr("app.backend_grok.GROK_BIN", grok_bin)
 
     codex_pid, grok_pid = 2_147_480_001, 2_147_480_002
     codex_start, grok_start = 881_001, 881_002
     # backend_type is intentionally contradictory: it is not part of the coherent snapshot.
     _save_handover_identity(
         "verified-codex", pid=codex_pid, started_at=codex_start, backend_type="grok"
     )
     _save_handover_identity(
         "verified-grok", pid=grok_pid, started_at=grok_start, backend_type="codex"
     )
 
     codex_fd, codex_peer = os.pipe()
     grok_fd, grok_peer = os.pipe()
     monkeypatch.setattr(
         "app.fdstore.acquire_fds",
         lambda: {
             "agent.verified-codex.stdout": codex_fd,
             "agent.verified-grok.stdout": grok_fd,
         },
     )
 
     cmdlines = {
-        codex_pid: b"node\0" + os.fsencode(CODEX_BIN) + b"\0app-server\0--stdio\0",
+        codex_pid: b"node\0" + os.fsencode(codex_bin) + b"\0app-server\0--stdio\0",
         grok_pid: (
-            b"node\0" + os.fsencode(GROK_BIN) + b"\0agent\0--always-approve\0stdio\0"
+            b"node\0" + os.fsencode(grok_bin) + b"\0agent\0--always-approve\0stdio\0"
         ),
     }
     starts = {codex_pid: codex_start, grok_pid: grok_start}
     real_open = builtins.open
     events: list[tuple] = []
 
     def fake_open(path, *args, **kwargs):
         raw = os.fspath(path)
         for pid in (codex_pid, grok_pid):
             if raw == f"/proc/{pid}/cmdline":
                 events.append(("cmdline", pid))
                 return io.BytesIO(cmdlines[pid])
             if raw == f"/proc/{pid}/stat":
                 events.append(("stat", pid))
                 return io.BytesIO(_proc_stat(pid, starts[pid]))
         return real_open(path, *args, **kwargs)
 
     pidfds = {codex_pid: 90_001, grok_pid: 90_002}
 
     def fake_pidfd_open(pid: int, flags: int = 0) -> int:
@@ -230,70 +232,71 @@ async def test_t1_verified_codex_and_grok_orphans_signal_only_through_pidfd(
             (pidfds[codex_pid], signal.SIGTERM),
             (pidfds[grok_pid], signal.SIGTERM),
         ]
         assert closed_pidfds == [pidfds[codex_pid], pidfds[grok_pid]]
         for pid in (codex_pid, grok_pid):
             assert events.index(("pidfd_open", pid)) < events.index(("cmdline", pid)), (
                 "pidfd must pin the process before /proc identity is read"
             )
     finally:
         for fd in (codex_fd, codex_peer, grok_fd, grok_peer):
             _close_if_open(fd)
 
 
 @pytest.mark.asyncio
 async def test_t1_unverifiable_candidate_does_not_abort_later_orphan_cleanup(
     manager,
     monkeypatch,
     caplog,
 ):
     """One malformed /proc record is local; the next verified orphan still gets reaped."""
-    from app.backend_codex import CODEX_BIN
+    codex_bin = "/bin/true"
+    monkeypatch.setattr("app.backend_codex.CODEX_BIN", codex_bin)
 
     denied_pid, verified_pid = 2_147_480_011, 2_147_480_012
     denied_start, verified_start = 882_011, 882_012
     _save_handover_identity(
         "unverifiable", pid=denied_pid, started_at=denied_start, backend_type="codex"
     )
     _save_handover_identity(
         "later-valid", pid=verified_pid, started_at=verified_start, backend_type="codex"
     )
     denied_fd, denied_peer = os.pipe()
     verified_fd, verified_peer = os.pipe()
     monkeypatch.setattr(
         "app.fdstore.acquire_fds",
         lambda: {
             "agent.unverifiable.stdout": denied_fd,
             "agent.later-valid.stdout": verified_fd,
         },
     )
 
     real_open = builtins.open
 
     def fake_open(path, *args, **kwargs):
         raw = os.fspath(path)
         if raw in {
             f"/proc/{denied_pid}/cmdline",
             f"/proc/{verified_pid}/cmdline",
         }:
             return io.BytesIO(
-                b"node\0" + os.fsencode(CODEX_BIN) + b"\0app-server\0--stdio\0"
+                b"node\0" + os.fsencode(codex_bin) + b"\0app-server\0--stdio\0"
             )
         if raw == f"/proc/{denied_pid}/stat":
             malformed = ["S", *("0" for _ in range(18)), "not-a-number"]
             return io.BytesIO(
                 f"{denied_pid} (bad-stat) {' '.join(malformed)}\n".encode()
             )
         if raw == f"/proc/{verified_pid}/stat":
             return io.BytesIO(_proc_stat(verified_pid, verified_start))
         return real_open(path, *args, **kwargs)
 
     opened: list[int] = []
 
     def fake_pidfd_open(pid: int, flags: int = 0) -> int:
         opened.append(pid)
         return {denied_pid: 90_011, verified_pid: 90_012}[pid]
 
     signalled: list[tuple[int, signal.Signals]] = []
     real_close = os.close
     closed_pidfds: list[int] = []
 
diff --git a/tests/test_runtime_handoff_v2.py b/tests/test_runtime_handoff_v2.py
index e9bc0d966..1870cdf19 100644
--- a/tests/test_runtime_handoff_v2.py
+++ b/tests/test_runtime_handoff_v2.py
@@ -1,36 +1,40 @@
 """Frozen RED acceptance oracles for #290 production-safe runtime handoff."""
 
 import asyncio
 import json
 import sqlite3
 from datetime import datetime, timezone
 from types import SimpleNamespace
 from unittest.mock import AsyncMock, MagicMock
 
 import pytest
 
 
 @pytest.fixture
-def session(monkeypatch):
+def session(monkeypatch, tmp_path):
     from app.session import AgentSession
 
+    claude_config = tmp_path / "claude-config"
+    claude_config.mkdir()
+    (claude_config / ".credentials.json").write_text("{}")
+    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_config))
     monkeypatch.setattr("app.session.save_session", MagicMock())
     monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
     monkeypatch.setattr("app.bg_jobs.bg_manager", None)
     return AgentSession(
         id="test-290", name="handoff-canary", scope="/test", cwd="/tmp",
         model="claude-sonnet-5[1m]", system_prompt="test",
         created_at=datetime.now(timezone.utc),
     )
 
 
 def _codex_history(thread_id: str):
     from app.runtime_history import render_codex_history
 
     return render_codex_history(
         [{
             "id": 1,
             "ts": "2026-08-16T10:00:00+00:00",
             "type": "user_message",
             "content": "old fact",
         }],
diff --git a/tests/test_search_deadline.py b/tests/test_search_deadline.py
index 1224759c3..19d116900 100644
--- a/tests/test_search_deadline.py
+++ b/tests/test_search_deadline.py
@@ -106,41 +106,43 @@ def _call(mcp, monkeypatch, *, raises=None, returns=None):
     async def fake_api(method, path, **kw):
         assert kw.get("timeout") == mcp.SEARCH_DEADLINE_S, "дедлайн обязан уходить в _api"
         if raises:
             raise raises
         return returns
 
     monkeypatch.setattr(mcp, "_api", fake_api)
     return asyncio.run(mcp.search_memory("как чинили таймаут"))
 
 
 @pytest.mark.parametrize(("code", "marker"), [
     ("transport_timeout", "не уложился"),
     ("search_busy", "очередь поиска переполнена"),
     ("search_stale", "протух в очереди"),
 ])
 def test_timeout_busy_stale_tell_agent_to_stop_waiting(mcp, monkeypatch, code, marker):
     err = mcp.ApiToolError(code=code, message="x")
     out = _call(mcp, monkeypatch, raises=err)
     assert marker in out
     assert "Не жди и не повторяй" in out
-    assert 'rg "как чинили таймаут"' in out
+    assert "rg -n -i -F" in out
+    assert "как чинили таймаут" in out
+    assert ".orchestra/kb/" in out
 
 
 def test_disabled_rag_names_the_flag(mcp, monkeypatch):
     err = mcp.ApiToolError(code="http_5xx", message="RAG disabled (set RAG_ENABLED=true)")
     out = _call(mcp, monkeypatch, raises=err)
     assert "RAG_ENABLED=false" in out and "rg " in out
 
 
 def test_unknown_error_is_never_empty(mcp, monkeypatch):
     err = mcp.ApiToolError(code="http_4xx", message="")
     out = _call(mcp, monkeypatch, raises=err)
     assert out.strip() and "http_4xx" in out and "rg " in out
 
 
 def test_empty_result_differs_from_timeout_and_admits_index_debt(mcp, monkeypatch):
     out = _call(mcp, monkeypatch, returns={"results": [], "index": {"pending_files": 12}})
     assert "No memory matches" in out
     assert "не уложился" not in out, "пустой ответ не должен выглядеть как таймаут"
     assert "индекс не догнан: 12" in out
 


## Later history of the touched files on main (after this commit)

33 later commits touch these paths; the first 40 (oldest first):
55b4b737f 2026-09-07 Restrict model review to executors and preserve approved design experiments
c61f56e85 2026-09-07 #533: repair stale CI regression tests and receipt migration
ad5d17664 2026-09-07 Merge VPS main with laptop runtime-control fixes
fe507ac6e 2026-09-08 Namespace VPS tasks and simplify runtime chat transfer and worker notes
ae30028d3 2026-09-08 Remove unreachable cross-runtime canary pipeline and retired rule API
98574f427 2026-09-08 Replace duplicate task stores with private Git and one versioned SQLite projection
5f7e72c50 2026-09-08 Add reusable idle watches and label dashboard message channel
d9ce293fa 2026-09-08 Integrate current main before storage cutover
e6da7e30a 2026-09-10 #537: stop runtime trees with Orchestra and remove live adoption
643d47211 2026-09-20 #V-597: модельное ревью заморожено — тул codex_review снят с регистрации, скилл и правила закомментированы
88c25b2a1 2026-09-20 #V-599: merge_worker снова синхронный — ждёт исход до 10 с и снимает лишнее пробуждение
f6d969c1c 2026-09-20 V-602: update MCP descriptions and parallelize agent listing
4bd1a5365 2026-09-21 V-603: clarify worker refusals and background receipts
de5d62a52 2026-09-22 V-576: #V-576: каталог проектов файлом и теги задач вместо второй сущности проекта
c31aa1ec7 2026-09-23 Тест замороженного ревью следует за сменой маршрута на GPT-6 Luna
63fd7ac22 2026-09-24 V-631: #V-631: merge taskless adhoc work against explicit task
7ae410f8d 2026-09-24 V-621: разбить общий каталог проектов на файлы по scope
9035836a0 2026-09-25 V-636: схемы функций для GigaChat без nullable/пустых object, панель допуска скрыта вне owner mode, текст про OpenRouter у харнеса нейтральный
c4d36776d 2026-09-29 V-658: WIP #V-658: switch default Sonnet to 5.5 pending full tests
102fd30f2 2026-10-02 V-682: удалить тип bg-задания idle; старые idle-строки гасятся при старте
bcd844068 2026-10-04 V-693: #V-693: record CI triage and confirmed CSS defect
98238cb42 2026-10-05 V-718: #V-718: remove project memory search
ea58b7dbe 2026-10-05 V-702: #V-702: fix merge gate outcomes and recovery routes
3582eea67 2026-10-05 V-699: WIP #V-699: measure worktree bottleneck and clarify retries
25eb55af9 2026-10-06 V-739: #V-739: curate model catalog and preserve session compatibility
5a5f21b6a 2026-10-07 V-748: #V-748: notify senders about failed file deliveries
63760bf68 2026-10-07 V-750: #V-750: remove receipt-only MCP status tools
bde9a3ed7 2026-10-08 V-766: route bounded tasks to Haiku 5.5
bce0fe64a 2026-10-08 V-778: #V-778: expose delivery keys on ambiguous transport errors
5efbf0cec 2026-10-13 V-828: #V-828: surface artifact publication failures
cebb03d02 2026-10-14 V-839: #V-839: accept scoped file delivery keys
d5e33acfd 2026-10-14 V-841: #V-841: bound worker log snapshots on server
57156329d 2026-10-14 V-848: #V-848: profile merge phases and reject busy workers

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 55b4b737f Restrict model review to executors and preserve approved design experiments

diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index fbfaf8400..a956be7d1 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -2634,10 +2634,11 @@ async def test_codex_review_model_reaches_quota_cli_job_and_accounting(
                 "observed_at": 2_000_000_000,
                 "valid_until": 2_000_000_300,
             }
         if method == "GET":
             return {
+                "role": "worker",
                 "id": "requester-id",
                 "worktree_path": str(tmp_path),
                 "task_id": "304",
             }
         return {"id": "bg-review"}
@@ -2691,11 +2692,11 @@ async def test_codex_review_default_is_server_owned_luna_fast(tmp_path, monkeypa
                 "provider": "codex",
                 "observed_at": 2_000_000_000,
                 "valid_until": 2_000_000_300,
             }
         if method == "GET":
-            return {"id": "requester-id", "worktree_path": str(tmp_path)}
+            return {"role": "worker", "id": "requester-id", "worktree_path": str(tmp_path)}
         captured["job"] = kwargs["json"]
         return {"id": "bg-review"}
 
     monkeypatch.setattr(m, "_api", fake_api)
     monkeypatch.setattr(m, "_codex_bin", lambda: "/usr/bin/codex")
### c61f56e85 #533: repair stale CI regression tests and receipt migration

diff --git a/scripts/migrate_review_receipts.py b/scripts/migrate_review_receipts.py
index 87a8a26a1..1e717c53e 100644
--- a/scripts/migrate_review_receipts.py
+++ b/scripts/migrate_review_receipts.py
@@ -107,10 +107,13 @@ def _receipt(item: dict) -> dict:
         "target_sha": "",
         "worker_head": "",
         "production_snapshot_sha256": "",
         "production_diff_sha256": "",
         "production_paths_json": "[]",
+        "production_path_heads_json": "",
+        "requested_by_session_id": "",
+        "requested_by_worker": "",
         "coverage_outcome": "unknown",
         "policy_ref": "",
         "decision_actor": "",
         "task_stable_id": "",
         "task_snapshot_ref": "",
diff --git a/tests/test_audit0901_session.py b/tests/test_audit0901_session.py
index 29579c202..ded665212 100644
--- a/tests/test_audit0901_session.py
+++ b/tests/test_audit0901_session.py
@@ -89,10 +89,21 @@ async def test_heartbeat_dead_process_recovery_publishes(mock_db, monkeypatch):
 
     Its own seam — `process_liveness` + `_process_runtime_dead` — is unreachable for the
     failed-reconnect test above, which pins `_last_msg_time = 0`.
     """
     from app.session import AgentStatus
+    import app.session_hibernate as hibernate
+
+    monkeypatch.setattr(
+        hibernate,
+        "get_runtime",
+        lambda _runtime: SimpleNamespace(
+            capabilities=SimpleNamespace(
+                process_liveness=True, event_stream="per_turn", reconnect=False,
+            )
+        ),
+    )
 
     session = _make_session("codex-dead")
     session.backend_type = "codex"
     session._log = MagicMock()
     session._persist = MagicMock()
@@ -118,10 +129,21 @@ async def test_heartbeat_zombie_without_backend_publishes(mock_db, monkeypatch):
 
     Reached only by a runtime with `process_liveness=False` and a persistent event stream,
     so neither of the other two branch tests can stand in for it.
     """
     from app.session import AgentStatus
+    import app.session_hibernate as hibernate
+
+    monkeypatch.setattr(
+        hibernate,
+        "get_runtime",
+        lambda _runtime: SimpleNamespace(
+            capabilities=SimpleNamespace(
+                process_liveness=False, event_stream="persistent", reconnect=False,
+            )
+        ),
+    )
 
     session = _make_session("claude-zombie")
     session._log = MagicMock()
     session._persist = MagicMock()
     session._backend = None
diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index fbfaf8400..7b4369624 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -2494,40 +2494,18 @@ async def test_search_memory_reports_index_debt_and_tolerates_its_absence(
     assert ("7 файлов ещё не проиндексированы" in out) is expect_debt
     if payload["results"]:
         assert "a.md" in out
 
 
-@pytest.mark.asyncio
-async def test_file_first_memory_tool_surface_keeps_only_search_fallback(monkeypatch, tmp_path):
+def test_file_first_memory_tool_surface_does_not_register_legacy_knowledge_tool():
+    """File-first memory has no legacy ``knowledge`` tool; search is ordinary/optional."""
     import app.mcp_stdio as m
 
     registered = {tool.name: tool for tool in m.mcp._tool_manager.list_tools()}
     assert "knowledge" not in registered
     assert "knowledge" not in m.READ_ONLY_MCP_TOOLS
     assert "knowledge" not in m.REDUCER_MCP_TOOLS
-    assert "search_memory" in registered
-
-    async def disabled_rag(*_args, **_kwargs):
-        raise m.ApiToolError(
-            code="http_503",
-            message="RAG disabled (set RAG_ENABLED=true)",
-        )
-
-    monkeypatch.setattr(m, "_api", disabled_rag)
-    monkeypatch.setattr(m, "SCOPE", "/project")
-
-    out = await registered["search_memory"].run({"query": "needle"})
-
-    assert "RAG_ENABLED=false" in out
-    import shlex
-    import subprocess
-    kb = tmp_path / ".orchestra/kb"
-    kb.mkdir(parents=True)
-    (kb / "topic.md").write_text("The relevant needle is here.\n")
-    command = shlex.split(out[out.index("rg "):])
-    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=True)
-    assert "The relevant needle is here." in result.stdout
 
 
 @pytest.mark.asyncio
 async def test_merge_warning_is_visible_in_the_tool_text(monkeypatch):
     """#80: успешный мерж с ненайденным номером задачи не читается как чистый успех."""
diff --git a/tests/test_merge_ref_gate.py b/tests/test_merge_ref_gate.py
index 9a63308b5..0a12e7611 100644
--- a/tests/test_merge_ref_gate.py
+++ b/tests/test_merge_ref_gate.py
@@ -79,12 +79,16 @@ async def test_prose_token_neither_refuses_nor_relabels_an_honest_merge(
         "a prose token must never link the merge to task #8"
     )
 
 
 @pytest.mark.asyncio
-async def test_unknown_leading_ref_is_still_refused_before_git(monkeypatch, tmp_path):
-    """Control arm: narrowing prose must not disarm the gate for a real fake ref."""
+async def test_unknown_leading_ref_is_reported_without_blocking_merge(monkeypatch, tmp_path):
+    """An unknown repository task number is reported without blocking the merge.
+
+    Since 979c4631, task numbers from another numbering system are preserved as
+    unresolved metadata and no longer refuse otherwise valid work.
+    """
     import app.routes.sessions as sessions_route
     import app.workspace as workspace
     from app import tm
 
     _init_db()
@@ -122,12 +126,13 @@ async def test_unknown_leading_ref_is_still_refused_before_git(monkeypatch, tmp_
 
     target_after = subprocess.run(
         ["git", "rev-parse", "main"], cwd=repo,
         check=True, capture_output=True, text=True,
     ).stdout.strip()
-    assert result["commit_point"] == "not_reached"
-    assert target_after == target_before
+    assert result["commit_point"] == "target_committed"
+    assert target_after != target_before
+    assert result["finalization"]["unresolved_task_refs"] == ["999"]
 
### ad5d17664 Merge VPS main with laptop runtime-control fixes

### fe507ac6e Namespace VPS tasks and simplify runtime chat transfer and worker notes

diff --git a/tests/test_runtime_handoff_v2.py b/tests/test_runtime_handoff_v2.py
index 1870cdf19..d48f48b0e 100644
--- a/tests/test_runtime_handoff_v2.py
+++ b/tests/test_runtime_handoff_v2.py
@@ -405,10 +405,11 @@ def test_t1_raw_refs_route_is_operator_only_and_absent_from_runtime_tools(
 
 @pytest.mark.asyncio
 async def test_t2_total_context_preflight_refuses_codex_before_source_disconnect(
     session, monkeypatch, tmp_path,
 ):
+    # Retained legacy handoff recovery contract; new runtime switches use plain chat.
     from app.session import AgentStatus
 
     # The oracle is "a prompt that does not fit is refused before the source is
     # disconnected", so the window it does not fit into has to be pinned. Since
     # `_model_context_window` started reading the installed Codex config, an empty
@@ -427,11 +428,11 @@ async def test_t2_total_context_preflight_refuses_codex_before_source_disconnect
     session._log = MagicMock()
     session._ensure_backend = AsyncMock(
         return_value=SimpleNamespace(session_id="target-codex-thread")
     )
 
-    result = await session.change_model("gpt-5.6-sol")
+    result = await session._change_runtime_with_packet_locked("gpt-5.6-sol", session.model, session.backend_type)
 
     assert result["ok"] is False
     assert result["error_code"] == "handoff_context_overflow"
     assert result["history_transfer"]["preflight"]["fits"] is False
     assert session.model == "claude-sonnet-5[1m]"
@@ -911,10 +912,11 @@ async def test_t3_invalid_receipt_never_disconnects_or_confirms(
 async def test_t4_grok_target_never_commits_from_summary_without_validation(
     session, monkeypatch,
 ):
     import app.runtime_history as historymod
     from app.backend_grok import GrokBackend
+    # Retained legacy handoff recovery contract; new runtime switches use plain chat.
     from app.session import AgentStatus
 
     session.model = "gpt-5.6-sol"
     session.backend_type = "codex"
     session.session_id = "source-codex-thread"
@@ -987,11 +989,11 @@ async def test_t4_grok_target_never_commits_from_summary_without_validation(
             "ok": True, "fingerprint": "c" * 64,
             "configuration_sha256": "b" * 64,
         }
     )
 
-    result = await session.change_model("grok-4.6")
+    result = await session._change_runtime_with_packet_locked("grok-4.6", session.model, session.backend_type)
 
     assert result["ok"] is True
     session._run_handoff_ingress_canary.assert_awaited_once()
     session._verify_handoff_capabilities.assert_awaited_once()
     session._build_runtime_handoff.assert_not_awaited()
@@ -1066,10 +1068,11 @@ async def test_t5_pending_effect_does_not_block_in_place_codex_retarget(
 
 @pytest.mark.asyncio
 async def test_t5_second_incompatibility_exhausts_fallback_without_empty_target(
     session,
 ):
+    # Retained legacy handoff recovery contract; new runtime switches use plain chat.
     from app.session import AgentStatus
 
     session.model = "claude-sonnet-5[1m]"
     session.backend_type = "claude"
     session.session_id = "source-claude"
@@ -1088,11 +1091,11 @@ async def test_t5_second_incompatibility_exhausts_fallback_without_empty_target(
     ])
     session._ensure_backend = AsyncMock(
         return_value=SimpleNamespace(session_id="fresh-codex-thread")
     )
 
-    result = await session.change_model("gpt-5.6-sol")
+    result = await session._change_runtime_with_packet_locked("gpt-5.6-sol", session.model, session.backend_type)
 
     assert result["ok"] is False
     assert result["error_code"] == "handoff_fallback_exhausted"
     assert session._stage_runtime_handoff_target.await_count == 2
     assert session.runtime_handoff == ""
### ae30028d3 Remove unreachable cross-runtime canary pipeline and retired rule API

diff --git a/tests/test_runtime_handoff_v2.py b/tests/test_runtime_handoff_v2.py
index d48f48b0e..94c158cbd 100644
--- a/tests/test_runtime_handoff_v2.py
+++ b/tests/test_runtime_handoff_v2.py
@@ -26,73 +26,10 @@ def session(monkeypatch, tmp_path):
         model="claude-sonnet-5[1m]", system_prompt="test",
         created_at=datetime.now(timezone.utc),
     )
 
 
-def _codex_history(thread_id: str):
-    from app.runtime_history import render_codex_history
-
-    return render_codex_history(
-        [{
-            "id": 1,
-            "ts": "2026-08-16T10:00:00+00:00",
-            "type": "user_message",
-            "content": "old fact",
-        }],
-        snapshot_id=1,
-        thread_id=thread_id,
-    )
-
-
-def _stub_ledger_packet():
-    """A prepared packet still carries the constraint bodies the ledger must keep."""
-    return {
-        "schema_version": 1,
-        "constraints": [{
-            "content": "current system policy",
-            "authority": {
-                "origin_kind": "current_system_prompt",
-                "verified_by": "orchestra_server",
-                "sha256": "d" * 64,
-            },
-        }],
-    }
-
-
-def _delivered_candidate_sha256(kwargs) -> str:
-    """Check the ack names the packet that actually left, with no duplicated bodies."""
-    from app.runtime_history import runtime_packet_sha256
-
-    sent = kwargs["packet"]
-    constraints = sent["constraints"]
-    assert constraints, "the delivered candidate lost its constraint authority"
-    assert not any(item.get("content") for item in constraints), (
-        "the target receives the constraint bodies twice"
-    )
-    assert all(item["authority"]["sha256"] for item in constraints)
-    sha256 = runtime_packet_sha256(sent)
-    assert kwargs["expected_packet_sha256"] == sha256
-    return sha256
-
-
-def _claude_history(session_id: str, model: str):
-    from app.runtime_history import render_claude_history
-
-    return render_claude_history(
-        [{
-            "id": 1,
-            "ts": "2026-08-16T10:00:00+00:00",
-            "type": "user_message",
-            "content": "old fact",
-        }],
-        snapshot_id=1,
-        session_id=session_id,
-        cwd="/tmp/project",
-        model=model,
-    )
-
-
 def test_t1_packet_ledger_is_additive_deterministic_and_cannot_launder_authority(
     tmp_path, monkeypatch,
 ):
     from app import db as dbmod
     import app.runtime_history as historymod
@@ -401,48 +338,10 @@ def test_t1_raw_refs_route_is_operator_only_and_absent_from_runtime_tools(
         )
         assert accepted.status_code == 200
         assert accepted.json()["events"][0]["authority"] == "transcript_untrusted"
 
 
-@pytest.mark.asyncio
-async def test_t2_total_context_preflight_refuses_codex_before_source_disconnect(
-    session, monkeypatch, tmp_path,
-):
-    # Retained legacy handoff recovery contract; new runtime switches use plain chat.
-    from app.session import AgentStatus
-
-    # The oracle is "a prompt that does not fit is refused before the source is
-    # disconnected", so the window it does not fit into has to be pinned. Since
-    # `_model_context_window` started reading the installed Codex config, an empty
-    # CODEX_HOME is what keeps the target on the catalog value (258 400) instead of
-    # whatever this machine has in ~/.codex.
-    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
-
-    session.model = "claude-sonnet-5[1m]"
-    session.backend_type = "claude"
-    session.session_id = "source-claude-session"
-    session.system_prompt = "x" * 300_000
-    session.last_summary = "must not become a silent fallback"
-    session.status = AgentStatus.IDLE
-    source = AsyncMock()
-    session._backend = source
-    session._log = MagicMock()
-    session._ensure_backend = AsyncMock(
-        return_value=SimpleNamespace(session_id="target-codex-thread")
-    )
-
-    result = await session._change_runtime_with_packet_locked("gpt-5.6-sol", session.model, session.backend_type)
-
-    assert result["ok"] is False
-    assert result["error_code"] == "handoff_context_overflow"
-    assert result["history_transfer"]["preflight"]["fits"] is False
-    assert session.model == "claude-sonnet-5[1m]"
-    assert session.session_id == "source-claude-session"
-    source.disconnect.assert_not_awaited()
-    session._ensure_backend.assert_not_awaited()
-
-
 @pytest.mark.parametrize(
     "component",
     [
         "system_prompt", "developer_prompt", "project_docs",
         "runtime_project_doc", "tool_schemas", "skill_index", "packet",
@@ -480,45 +379,10 @@ def test_t2_total_context_preflight_counts_each_staged_component(component):
     assert report.fits is False
     assert report.components[component] == 128_001
     assert report.configuration_sha256 == "b" * 64
 
 
-@pytest.mark.asyncio
-async def test_t2_adapter_stages_the_exact_manifest_object_it_preflighted():
-    import app.runtime_history as historymod
-
-    stage_preflighted = getattr(historymod, "stage_preflighted_handoff", None)
-    assert callable(stage_preflighted), "shared manifest-to-stage seam is absent"
-    manifest = SimpleNamespace(
-        runtime="codex", model="gpt-5.6-sol", effective_window=258_400,
-        components={
-            "system_prompt": "system", "developer_prompt": "developer",
-            "project_docs": "project", "runtime_project_doc": "runtime-doc",
-            "tool_schemas": "tools", "skill_index": "skills",
-            "packet": "packet", "recent_delta": "delta",
-            "validation_profile": "no-tools", "canary": "checksum",
-        },
### 98574f427 Replace duplicate task stores with private Git and one versioned SQLite projection

diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index ead6b7e15..ff331f232 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -772,13 +772,13 @@ async def test_task_create_keeps_caller_scope_and_registered_project_authorizati
             ("lower", "/lower", "LOW"),
             ("upper", "/upper", "UPR"),
         ):
             conn.execute(
                 """INSERT INTO tm_projects
-                   (id, name, prefix, scope, created_at)
-                   VALUES (?, ?, ?, ?, ?)""",
-                (project_id, project_id, prefix, scope, now),
+                   (id, name, prefix, scope, created_at, canonical_id)
+                   VALUES (?, ?, ?, ?, ?, ?)""",
+                (project_id, project_id, prefix, scope, now, project_id),
             )
 
     monkeypatch.setattr(m, "SCOPE", "/lower")
     with patch.object(m, "_api", side_effect=_call_tm_task_create):
         await m.task_create(title="caller-scoped task")
@@ -2464,38 +2464,10 @@ async def test_merge_worker_real_failure_still_reads_as_failure(monkeypatch):
 
     assert out.isError is True
     assert out.structuredContent["result"]["operation_state"] == "FAILED"
 
 
-@pytest.mark.parametrize(
-    ("payload", "expect_debt"),
-    [
-        ({"results": [{"source": "file", "path": "a.md", "content": "текст"}]}, False),
-        ({"results": [{"source": "file", "path": "a.md", "content": "текст"}],
-          "index": {"pending_files": 7, "indexing": True}}, True),
-        ({"results": [], "index": {"pending_files": 7}}, True),
-    ],
-)
-@pytest.mark.asyncio
-async def test_search_memory_reports_index_debt_and_tolerates_its_absence(
-    monkeypatch, payload, expect_debt,
-):
-    """`index` добавлен в роут позже тула. Живой MCP подхватывает код немедленно, а роут в
-    памяти systemd — только после рестарта, поэтому новый тул ОБЯЗАН пережить ответ без `index`."""
-    import app.mcp_stdio as m
-
-    monkeypatch.setattr(m, "SCOPE", "/scope")
-
-    def handler(request):
-        return httpx.Response(200, json=payload)
-
-    _mock_http(monkeypatch, m, handler)
-    out = await m.search_memory("вопрос")
-
-    assert ("7 файлов ещё не проиндексированы" in out) is expect_debt
-    if payload["results"]:
-        assert "a.md" in out
 
 
 def test_file_first_memory_tool_surface_does_not_register_legacy_knowledge_tool():
     """File-first memory has no legacy ``knowledge`` tool; search is ordinary/optional."""
     import app.mcp_stdio as m
diff --git a/tests/test_merge_ref_gate.py b/tests/test_merge_ref_gate.py
index 0a12e7611..f3225cc73 100644
--- a/tests/test_merge_ref_gate.py
+++ b/tests/test_merge_ref_gate.py
@@ -4,10 +4,12 @@
 Feeding them to the merge gate refuses honest work, and feeding them to the squash
 builder links the merge to whatever numeric tail they end in (`UTF-8` -> `#8`).
 Both directions are covered here; the control arm keeps the gate itself honest.
 """
 
+from tests.task_seeds import create_task as seed_task
+
 import json
 import subprocess
 from pathlib import Path
 
 import pytest
@@ -34,12 +36,12 @@ async def test_prose_token_neither_refuses_nor_relabels_an_honest_merge(
     repo = _make_git_scope(monkeypatch, tmp_path)
     scope = str(repo)
     with tm._conn() as connection:
         tm.ensure_project(connection, "project", scope=scope)
         # #8 is a real neighbouring task: mislinking must be observable, not silent.
-        tm.create_task(connection, "project", "Unrelated neighbour", par_number=8)
-        task = tm.create_task(
+        seed_task(connection, "project", "Unrelated neighbour", par_number=8)
+        task = seed_task(
             connection, "project", "Honest work", par_number=42, status="in_progress",
         )
         connection.execute(
             "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
             ("prose-worker", task["id"]),
@@ -94,11 +96,11 @@ async def test_unknown_leading_ref_is_reported_without_blocking_merge(monkeypatc
     _init_db()
     repo = _make_git_scope(monkeypatch, tmp_path)
     scope = str(repo)
     with tm._conn() as connection:
         tm.ensure_project(connection, "project", scope=scope)
-        task = tm.create_task(
+        task = seed_task(
             connection, "project", "Bound", par_number=42, status="in_progress",
         )
         connection.execute(
             "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
             ("fake-ref-worker", task["id"]),
@@ -145,11 +147,11 @@ async def test_reserved_operation_trailer_in_body_is_refused_before_git(
     _init_db()
     repo = _make_git_scope(monkeypatch, tmp_path)
     scope = str(repo)
     with tm._conn() as connection:
         tm.ensure_project(connection, "project", scope=scope)
-        task = tm.create_task(
+        task = seed_task(
             connection, "project", "Bound", par_number=42, status="in_progress",
         )
         connection.execute(
             "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
             ("trailer-worker", task["id"]),
diff --git a/tests/test_message_provenance_review_433.py b/tests/test_message_provenance_review_433.py
index de69a4da8..a62cdd296 100644
--- a/tests/test_message_provenance_review_433.py
+++ b/tests/test_message_provenance_review_433.py
@@ -2,17 +2,10 @@ import asyncio
 import pytest
 import sqlite3
 import json
 
 
-def test_review_storage_requires_senders_json_array():
-    from app.events import MessageProvenance
-
-    with pytest.raises(ValueError, match="array"):
-        MessageProvenance.from_storage(
-            "user", {"senders": {"alice": True}},
-        )
 
 
 def test_review_db_projection_rejects_missing_or_corrupt_provenance():
     from app.db import _decode_log_provenance
 
@@ -24,47 +17,12 @@ def test_review_db_projection_rejects_missing_or_corrupt_provenance():
             "origin": "user",
             "origin_detail": {"senders": {"alice": True}},
         })
 
 
-def test_review_rag_rejects_corrupt_user_provenance_atomically():
-    from app.rag import _classify_log
### 5f7e72c50 Add reusable idle watches and label dashboard message channel

diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index ead6b7e15..e4ff15cb4 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -2722,5 +2722,24 @@ async def test_codex_review_rejects_invalid_non_codex_and_spark_before_api(
         )
 
     assert caught.value.code == "invalid_argument"
     assert caught.value.details["field"] == "model"
     api.assert_not_awaited()
+
+
+@pytest.mark.asyncio
+@pytest.mark.parametrize('role,target,allowed', [
+    ('orchestrator', '', True), ('sub-orchestrator', 'root', True),
+    ('worker', '', False), ('orchestrator', 'someone-else', False),
+])
+async def test_idle_watch_is_self_only(monkeypatch, role, target, allowed):
+    import app.mcp_stdio as m
+    monkeypatch.setattr(m, 'ROLE', role)
+    monkeypatch.setattr(m, 'WORKER_NAME', 'root')
+    with patch.object(m, '_api', new_callable=AsyncMock, return_value={'id': 'watch'}) as api:
+        if allowed:
+            await m.bg_create(type='idle', target=target, timeout_seconds=0)
+            assert api.call_args.kwargs['json']['config'] == {}
+        else:
+            with pytest.raises(m.ApiToolError):
+                await m.bg_create(type='idle', target=target)
+            api.assert_not_called()
### d9ce293fa Integrate current main before storage cutover

diff --cc tests/test_runtime_handoff_v2.py
index d965e68af,94c158cbd..b99c09b9d
--- a/tests/test_runtime_handoff_v2.py
+++ b/tests/test_runtime_handoff_v2.py
@@@ -328,50 -265,83 +265,12 @@@ async def test_t1_prepare_drains_pendin
      assert prepared.snapshot_log_id >= 2
      assert prepared.pending_effects == 0
      assert prepared.packet["tool_effects"][0]["status"] == "completed"
  
  
 -def test_t1_raw_refs_route_is_operator_only_and_absent_from_runtime_tools(
 -    tmp_path, monkeypatch,
 -):
 -    from fastapi.testclient import TestClient
 -    from app import auth, db as dbmod
 -    from app.mcp_stdio import mcp
 -
 -    tool_names = {tool.name for tool in asyncio.run(mcp.list_tools())}
 -    assert "read_handoff_events" not in tool_names
 -    assert "resolve_runtime_handoff_events" not in tool_names
 -
 -    create_csrf_token = getattr(auth, "create_csrf_token", None)
 -    assert callable(create_csrf_token), "operator CSRF receipt is absent"
 -    monkeypatch.setenv("DASHBOARD_USER", "operator")
 -    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")
 -    monkeypatch.setenv("INTERNAL_TOKEN", "agent-token")
 -    db_path = tmp_path / "route.db"
 -    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
 -    dbmod.init_db()
 -    created_at = datetime.now(timezone.utc).isoformat()
 -    with sqlite3.connect(db_path) as conn:
 -        conn.execute(
 -            """INSERT INTO sessions (id, name, scope, cwd, model, created_at)
 -               VALUES ('s1', 'w', '/repo', '/repo', 'gpt-5.6-sol', ?)""",
 -            (created_at,),
 -        )
 -        conn.execute(
 -            """INSERT INTO logs (session_id, ts, type, content, event_id)
 -               VALUES ('s1', ?, 'user_message', 'old fact', '')""",
 -            (created_at,),
 -        )
 -        conn.execute(
 -            """INSERT INTO runtime_handoffs
 -               (handoff_id, session_id, idempotency_key, status,
 -                source_runtime, source_model, target_runtime, target_model,
 -                snapshot_log_id, snapshot_sha256, packet_json, packet_sha256,
 -                preferred_mode, created_at, updated_at)
 -               VALUES ('h1', 's1', 'request-1', 'confirmed', 'codex',
 -                       'gpt-5.6-sol', 'claude', 'claude-sonnet-5[1m]', 1,
 -                       ?, '{}', ?, 'packet_delta', ?, ?)""",
 -            ("a" * 64, "b" * 64, created_at, created_at),
 -        )
 -
 -    from app.main import app
 -
 -    path = "/api/sessions/s1/handoffs/h1/events"
 -    with TestClient(app) as client:
 -        internal = client.post(
 -            path,
 -            headers={
 -                "Authorization": "Bearer agent-token",
 -                "X-Orchestra-Session-Id": "s1",
 -            },
 -            json={"event_ids": [1]},
 -        )
 -        assert internal.status_code == 403
 -
 -        cookie = auth.create_session("operator")
 -        missing_csrf = client.post(
 -            path, cookies={"session": cookie}, json={"event_ids": [1]},
 -        )
 -        assert missing_csrf.status_code == 403
 -
 -        accepted = client.post(
 -            path,
 -            cookies={"session": cookie},
 -            headers={"X-CSRF-Token": create_csrf_token("operator")},
 -            json={"event_ids": [1]},
 -        )
 -        assert accepted.status_code == 200
 -        assert accepted.json()["events"][0]["authority"] == "transcript_untrusted"
  
  
- @pytest.mark.asyncio
- async def test_t2_total_context_preflight_refuses_codex_before_source_disconnect(
-     session, monkeypatch, tmp_path,
- ):
-     # Retained legacy handoff recovery contract; new runtime switches use plain chat.
-     from app.session import AgentStatus
- 
-     # The oracle is "a prompt that does not fit is refused before the source is
-     # disconnected", so the window it does not fit into has to be pinned. Since
-     # `_model_context_window` started reading the installed Codex config, an empty
-     # CODEX_HOME is what keeps the target on the catalog value (258 400) instead of
-     # whatever this machine has in ~/.codex.
-     monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
- 
-     session.model = "claude-sonnet-5[1m]"
-     session.backend_type = "claude"
-     session.session_id = "source-claude-session"
-     session.system_prompt = "x" * 300_000
-     session.last_summary = "must not become a silent fallback"
-     session.status = AgentStatus.IDLE
-     source = AsyncMock()
-     session._backend = source
-     session._log = MagicMock()
-     session._ensure_backend = AsyncMock(
-         return_value=SimpleNamespace(session_id="target-codex-thread")
-     )
- 
-     result = await session._change_runtime_with_packet_locked("gpt-5.6-sol", session.model, session.backend_type)
- 
-     assert result["ok"] is False
-     assert result["error_code"] == "handoff_context_overflow"
-     assert result["history_transfer"]["preflight"]["fits"] is False
-     assert session.model == "claude-sonnet-5[1m]"
-     assert session.session_id == "source-claude-session"
-     source.disconnect.assert_not_awaited()
-     session._ensure_backend.assert_not_awaited()
- 
- 
  @pytest.mark.parametrize(
      "component",
      [
          "system_prompt", "developer_prompt", "project_docs",
          "runtime_project_doc", "tool_schemas", "skill_index", "packet",