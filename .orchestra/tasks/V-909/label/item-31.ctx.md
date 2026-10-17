# Context for item-31

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/merge_operations.py b/app/merge_operations.py
index 37c8a882e..ac94b3ded 100644
--- a/app/merge_operations.py
+++ b/app/merge_operations.py
@@ -1013,44 +1013,56 @@ def normalize_merge_result(
         return result
 
     raw_state = str(raw.get("state") or ("merged" if raw.get("ok") else "failed"))
     raw_point = str(raw.get("commit_point") or "unknown")
     commit_point = {
         "target_committed": "REACHED",
         "not_reached": "NOT_REACHED",
         "rolled_back": "NOT_REACHED",
         "unknown": "UNKNOWN",
     }.get(raw_point, "UNKNOWN")
     message = _text(raw.get("error"), "merge failed without an error detail")
     conflicts = raw.get("conflicts") if isinstance(raw.get("conflicts"), list) else []
     if raw.get("ok"):
         git_status = "SUCCEEDED"
     elif raw_state == "conflict" or conflicts:
         git_status = "CONFLICT"
     elif "working tree is dirty" in message.lower():
         git_status = "DIRTY"
     elif commit_point == "UNKNOWN":
         git_status = "UNKNOWN"
+    elif commit_point == "REACHED":
+        # Post-commit stages may set the aggregate outcome to false, but Git has
+        # already committed at this point and must not be reported as failed.
+        git_status = "SUCCEEDED"
     else:
         git_status = "FAILED"
 
-    link_status, link_items, link_failures, link_warnings = _link_status(raw.get("linked_tasks"))
+    finalization = raw.get("finalization")
+    linked_tasks = raw.get("linked_tasks")
+    if (
+        not linked_tasks
+        and isinstance(finalization, dict)
+        and finalization.get("links")
+    ):
+        linked_tasks = finalization["links"]
+    link_status, link_items, link_failures, link_warnings = _link_status(linked_tasks)
     lifecycle = raw.get("lifecycle_status")
     lifecycle_status = (
         "SUCCEEDED" if isinstance(lifecycle, dict) and lifecycle.get("ok")
         else "FAILED" if isinstance(lifecycle, dict)
         else "NOT_RUN"
     )
     rag_raw = raw.get("rag_backfill_status")
     if rag_raw == "not_ready" and rag_enabled is False:
         rag_status = "DISABLED"
     else:
         rag_status = {
             "accepted": "ACCEPTED",
             "coalesced": "COALESCED",
             "not_ready": "NOT_READY",
         }.get(rag_raw, "NOT_RUN" if rag_raw is None else "FAILED")
     if not request.get("next_task_id"):
         next_status = "NOT_REQUESTED"
     else:
         switch = raw.get("switch")
         task_status = raw.get("task_status")
@@ -1120,41 +1132,40 @@ def normalize_merge_result(
             "Verifying the merged artifact is expected — check the target branch and "
             "worker_wip before reporting this task done.",
             operation_id,
         )
     elif raw.get("ok") and not primary_failures:
         state = "SUCCEEDED"
         if warnings:
             next_action = _action(
                 "REVIEW_WARNINGS_OUTSIDE_MERGE",
                 "Merge committed; no merge retry is required. Handle these outside the merge: "
                 + "; ".join(warning["message"] for warning in warnings),
             )
     else:
         state = "FAILED"
         code, details, next_action = _classify_failure(raw, message)
         error = _error(
             code, message, operation_id=operation_id,
             status=raw.get("_http_status"), details=details,
         )
 
-    finalization = raw.get("finalization")
     if isinstance(finalization, dict) and finalization.get("stage") == "PENDING":
         # DB-стадия не доехала, но коммит есть и журнал его описывает: это чинится
         # повтором ТОГО ЖЕ operation_id и никогда вторым мержем.
         retryable = True
 
     result = {
         "schema_version": 1,
         "operation_id": operation_id,
         "operation_state": state,
         "retryable": retryable,
         "commit_point": commit_point,
         "git": {
             "status": git_status,
             "target_branch": str(raw.get("target_branch") or request.get("target") or ""),
             "target_before": raw.get("target_before") or None,
             "target_after": raw.get("target_after") or None,
             "worker_branch": str(raw.get("worker_branch") or raw.get("branch") or ""),
             "worker_head": raw.get("worker_head") or None,
             "conflicts": conflicts,
             "commits_merged": int(raw.get("commits_merged") or 0),
@@ -1426,40 +1437,51 @@ def _recover_lost_checkpoint(operation_id: str, raw: dict[str, Any]) -> dict[str
 
 async def _resume_finalization(record: dict[str, Any]) -> dict[str, Any]:
     """Finish the DB stage of an operation whose Git commit already exists."""
     from app.routes.sessions import apply_merge_finalization
 
     operation_id = record["operation_id"]
     payload = json.loads(record["finalization_json"] or "{}")
     result = dict(record["result"])
     try:
         applied = await apply_merge_finalization(payload)
     except Exception as exc:
         detail = f"merge finalization replay failed: {err_text(exc)}"
         logger.error("%s operation_id=%s", detail, operation_id)
         result["error"] = _error(
             "POST_COMMIT_PARTIAL", detail, operation_id=operation_id,
             retryable=True, details={"failed_stages": ["FINALIZATION_PENDING"]},
         )
         result["operation_state"] = "PARTIAL"
         result["retryable"] = True
         result["finalization"] = payload
+        link_status, link_items, _failures, link_warnings = _link_status(
+            payload.get("links"),
+        )
+        if link_items:
+            result["task_links"] = {"status": link_status, "items": link_items}
+            result["warnings"] = list(result.get("warnings") or []) + [
+                {"code": "TASK_LINK_NOT_FOUND", "message": text}
+                for text in link_warnings
+            ]
+        if result.get("commit_point") == "REACHED":
+            result["git"]["status"] = "SUCCEEDED"
         return result
     payload["stage"] = "APPLIED"
     await asyncio.to_thread(mark_finalization_applied, operation_id, payload)
     link_status, link_items, _failures, link_warnings = _link_status(
         applied.get("linked_tasks"),
     )
     result.update(
         operation_state="SUCCEEDED",
         commit_point="REACHED",
         retryable=False,
         error=None,
         finalization=payload,
         next_action=_action(
             "NONE", "Merge operation completed; no retry is required.",
         ),
     )
     result["task_links"] = {"status": link_status, "items": link_items}
     result["warnings"] = list(result.get("warnings") or []) + [
         {"code": "TASK_LINK_NOT_FOUND", "message": text} for text in link_warnings
     ]
diff --git a/app/tm.py b/app/tm.py
index b87972fa3..19e73c875 100644
--- a/app/tm.py
+++ b/app/tm.py
@@ -821,40 +821,44 @@ def release_merge_finalization(payload: dict) -> None:
             conn.execute(
                 "DELETE FROM tm_task_reservations WHERE task_id=? AND operation_id=?",
                 (task_id, reservation_id),
             )
 
 
 def finalize_merge_outcome(payload: dict) -> dict:
     """Apply the whole post-commit tracker stage of one merge. Safe to run twice.
 
     Commit links come first and each ref links on its own: after the commit point a
     vanished ref must not discard the links that do resolve. The status stage that
     follows — close current, bind next, drop reservations — is one transaction, so a
     handoff never leaves a taskless worker behind.
     """
     project_id = payload["project_id"] or payload["task"]["project_id"]
     task_db_id = payload["task"]["task_id"]
     links = {
         str(ref): link_commits_to_task(str(ref), commits, project_id)
         for ref, commits in (payload.get("commits") or {}).items()
     }
+    # Commit links are durable before the lifecycle transaction below. Keep their
+    # results on the payload so a later failure cannot make an applied link look
+    # like it was never attempted.
+    payload["links"] = links
     outcome = payload["outcome"]
     next_task = payload.get("next_task")
     reservation_id = payload["reservation_id"]
     with _conn() as conn:
         conn.execute("BEGIN IMMEDIATE")
         try:
             if outcome == "complete":
                 task = get_task_by_id(conn, task_db_id)
                 if not task:
                     raise ValueError(f"task {task_db_id} disappeared before finalization")
                 if task["status"] != "done":
                     update_task(conn, task_db_id, status="done")
                 conn.execute(
                     "UPDATE tm_tasks SET worker_session_id=NULL, "
                     "sync_revision=sync_revision+1, updated_at=? WHERE id=?",
                     (_now(), task_db_id),
                 )
                 conn.execute(
                     "DELETE FROM tm_task_reservations WHERE task_id=? AND operation_id=?",
                     (task_db_id, reservation_id),
diff --git a/docs/workers/fix-merge-report.md b/docs/workers/fix-merge-report.md
new file mode 100644
index 000000000..b682d423a
--- /dev/null
+++ b/docs/workers/fix-merge-report.md
@@ -0,0 +1,4 @@
+# Reusable workflow notes
+
+- Post-commit stages can fail after an earlier durable side effect. Preserve completed sub-results on the shared finalization payload before entering later transactions, then make response normalization fall back to that payload when the aggregate result is partial.
+- When acceptance names a mutation, keep the regression oracle in the repository and run that named test against the mutation; one-off probes only diagnose the defect.
diff --git a/tests/test_merge_operations.py b/tests/test_merge_operations.py
index 5162e0175..0a910536a 100644
--- a/tests/test_merge_operations.py
+++ b/tests/test_merge_operations.py
@@ -626,40 +626,64 @@ def test_post_commit_stage_failures_preserve_all_stage_statuses():
             "rag_backfill_status": "accepted",
             "switch": {"ok": False, "error": "branch busy"},
             "task_status": {"ok": False, "error": "switch skipped"},
         },
         operations.normalize_request(
             name="worker", scope="/scope", target="main", next_task_id="43",
         ),
     )
 
     assert result["operation_state"] == "PARTIAL"
     assert result["commit_point"] == "REACHED"
     assert result["task_links"]["status"] == "PARTIAL"
     assert result["lifecycle"]["status"] == "FAILED"
     assert result["rag"]["status"] == "ACCEPTED"
     assert result["next_task"]["status"] == "FAILED"
     assert set(result["error"]["details"]["failed_stages"]) == {
         "TASK_LINK_PARTIAL", "LIFECYCLE_FAILED", "NEXT_TASK_FAILED",
     }
 
 
+def test_post_commit_failure_keeps_git_status_succeeded():
+    """A later finalization failure cannot repaint an already committed Git stage."""
+    import app.merge_operations as operations
+
+    result = operations.normalize_merge_result(
+        "00000000-0000-0000-0000-000000000026",
+        {
+            "ok": False,
+            "state": "partial",
+            "commit_point": "target_committed",
+            "target_branch": "main",
+            "target_after": "c" * 40,
+            "commits_merged": 5,
+            "conflicts": [],
+            "error": "merge finalization failed: status stage exploded",
+            "finalization": {"stage": "PENDING"},
+        },
+        operations.normalize_request(name="worker", scope="/scope", target="main"),
+    )
+
+    assert result["commit_point"] == "REACHED"
+    assert result["git"]["status"] == "SUCCEEDED"
+
+
 def test_disabled_rag_is_explicit_terminal_policy_not_partial():
     import app.merge_operations as operations
 
     result = operations.normalize_merge_result(
         "00000000-0000-0000-0000-000000000006",
         {
             "ok": True, "state": "merged", "commit_point": "target_committed",
             "target_branch": "main", "target_before": "a" * 40,
             "target_after": "c" * 40, "worker_branch": "task-42/worker",
             "worker_head": "b" * 40, "conflicts": [],
             "lifecycle_status": {"ok": True}, "rag_backfill_status": "not_ready",
         },
         operations.normalize_request(name="worker", scope="/scope", target="main"),
         rag_enabled=False,
     )
 
     assert result["operation_state"] == "SUCCEEDED"
     assert result["rag"]["status"] == "DISABLED"
     assert result["error"] is None
 
diff --git a/tests/test_task_tracker_integration.py b/tests/test_task_tracker_integration.py
index 6496707c5..34bccf6d2 100644
--- a/tests/test_task_tracker_integration.py
+++ b/tests/test_task_tracker_integration.py
@@ -859,40 +859,92 @@ async def test_t3_complete_and_next_transition_is_one_atomic_finalizer(monkeypat
         req={
             "scope": "/scope",
             "task_outcome": "complete",
             "next_task_id": "43",
             "merge_schema_version": 2,
         },
     )
 
     assert result["ok"] is True
     with tm._conn() as connection:
         closed = tm.get_task_by_id(connection, current["id"])
         active = tm.get_task_by_id(connection, next_task["id"])
     assert (closed["status"], closed["worker_session_id"]) == ("done", None)
     assert (active["status"], active["worker_session_id"]) == (
         "in_progress", "handoff-worker",
     )
     durable = get_session(found.id)
     assert (durable["task_id"], durable["needs_switch"]) == ("43", 0)
 
 
+def test_t3_links_survive_late_finalizer_failure(monkeypatch):
+    """Links committed before status work remain visible when that work raises."""
+    from app import merge_operations as operations
+    from app import tm
+
+    _init_db()
+    _seed_project()
+    with tm._conn() as connection:
+        first = tm.create_task(connection, "project", "First", par_number=590)
+        second = tm.create_task(connection, "project", "Second", par_number=591)
+
+    def fail_status_update(*_args, **_kwargs):
+        raise RuntimeError("status stage exploded")
+
+    monkeypatch.setattr(tm, "update_task", fail_status_update)
+    finalization = {
+        "project_id": "project",
+        "task": {"task_id": first["id"]},
+        "commits": {
+            "590": [{"hash": "a" * 40, "message": "#590: first"}],
+            "591": [{"hash": "b" * 40, "message": "#591: second"}],
+        },
+        "outcome": "complete",
+        "reservation_id": "operation-398",
+        "session_id": "worker-398",
+    }
+
+    with pytest.raises(RuntimeError, match="status stage exploded"):
+        tm.finalize_merge_outcome(finalization)
+
+    with tm._conn() as connection:
+        linked = [
+            tm.get_task_by_id(connection, task["id"])["git_commits"]
+            for task in (first, second)
+        ]
+    assert all(json.loads(commits) for commits in linked)
+
+    result = operations.normalize_merge_result(
+        "operation-398",
+        {
+            "ok": False,
+            "state": "partial",
+            "commit_point": "target_committed",
+            "error": "merge finalization failed: status stage exploded",
+            "finalization": finalization,
+        },
+        operations.normalize_request(name="worker", scope="/scope", target="main"),
+    )
+    assert result["task_links"]["status"] == "SUCCEEDED"
+    assert set(result["task_links"]["items"]) == {"590", "591"}
+
+
 @pytest.mark.asyncio
 async def test_t3_removing_last_worker_requeues_in_progress_task(monkeypatch):
     """Worker liveness is a platform fact; an archived last worker cannot stay active."""
     from app import tm
     from app.manager import SessionManager
 
     _init_db()
     _seed_project()
     with tm._conn() as connection:
         task = tm.create_task(
             connection, "project", "Interrupted", par_number=42, status="in_progress",
         )
         connection.execute(
             "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
             ("last-worker", task["id"]),
         )
     _save_worker(session_id="last-worker", task_id="42")
     manager = SessionManager()
     found = manager.get_by_name("last-worker", "/scope")
     found.worktree_path = ""


## Later history of the touched files on main (after this commit)

61 later commits touch these paths; the first 40 (oldest first):
e15a5f443 2026-08-26 #400: freeze merge loss regression oracles
1b28729ec 2026-08-26 #406: #399-fix: freeze par collision regression oracle
43a96ed31 2026-08-28 #413: freeze merge delivery visibility oracle
d932e027d 2026-08-28 спавн заводит задачу через canonical, а не мимо него
a10f14517 2026-08-28 номер задачи выдаёт только один владелец, обход падает громко
7b8836462 2026-08-28 Merge remote-tracking branch 'origin/main'
8239760c7 2026-08-29 #416: research misleading zero-commit merge failure
cc15369de 2026-08-31 #423: report merge conflict paths
35bbbd6dd 2026-08-28 #416: serialize shadow task creation
7b5b2659f 2026-08-30 #417: freeze binding oracle
1ef306e2a 2026-08-30 #418: freeze canonical identity oracle
80588a71c 2026-08-30 #421: freeze dual-store completion oracle
7100b0766 2026-08-30 #422: freeze shadow repair oracle
65c794754 2026-08-30 #422: repair only status completion drift
af6ae1b74 2026-08-30 #422: freeze bulk repair performance oracle
31726eeba 2026-08-30 #422: freeze canonical identity repair oracle
8a7332690 2026-08-30 #422: freeze missing completion repair oracle
feff52e3b 2026-08-31 #423: freeze resolved-operation success oracle
0aa2d5953 2026-08-31 #424: freeze live merge progress oracle
75a1326d7 2026-09-01 #426: freeze shadow task creation oracle
81a6e27e8 2026-09-01 #428: freeze finalization mismatch oracles
748e81e37 2026-09-01 #395: eliminate task projection stalls and duplicate creates
9093641f3 2026-09-01 v2.41.0: аудит кодовой базы — 27 дефектов закрыто (3 P0 в tm.py), 2 фикса откачены как регрессии
a1037725b 2026-09-01 #435: merge laptop history and reserve VPS task range
498c0d149 2026-09-03 Orchestra: migrate project state to .orchestra
f8e00522e 2026-09-03 #430: research .orchestra path migration
cd39b74c9 2026-09-03 merge: забрать 38 коммитов контура VPS (#395,#426,#435,#500-#506) в переехавший main
1a86f403b 2026-09-03 #462: backtest review coverage gate
2a048e616 2026-09-03 #465: research taskless adhoc merge deadlock
efaf227a1 2026-09-04 тесты merge_operations: нейтрализовать активную политику покрытия там, где тест про арбитраж операций, и ограничить ожидание
975476622 2026-09-04 #466: research and freeze run receipt acceptance
cb052ede7 2026-09-04 #474: пер-тестовый потолок в merge-гейте и снятие хеша цели с идентичности ревью
480ca55c2 2026-09-04 refactor: extract privacy and error helpers, trim duplicated validation
bb2f98bb8 2026-09-05 #493: author signs the review outcome, verdict comes from the artifact, post-review delta needs a machine-checked attestation
e3d29ad1f 2026-09-05 #499: surface and repair derived lifecycle quarantine
36326164d 2026-09-05 #502: WIP #502: map merge subjects before emergency slice
42882844a 2026-09-05 #509: plan for explicit review subject and requester/subject split
979c46315 2026-09-06 мерж: чужой номер задачи в сообщении коммита — предупреждение, а не отказ всей операции
0f5888a58 2026-09-06 тесты: убраны ещё 17 проверок на дословный текст промптов и документов
067679f36 2026-09-07 #515, #432, #523, #520, #526: CI шардируется на 6 процессов — полный сьют в один процесс убивает OOM

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### e15a5f443 #400: freeze merge loss regression oracles

diff --git a/app/merge_operations.py b/app/merge_operations.py
index ac94b3ded..5881a718f 100644
--- a/app/merge_operations.py
+++ b/app/merge_operations.py
@@ -936,10 +936,15 @@ def _classify_failure(raw: dict[str, Any], message: str) -> tuple[str, dict[str,
         details["target_recheck"] = raw.get("target_recheck") or {}
         return "TARGET_HEAD_CHANGED", details, _action(
             "REFRESH_TARGET_THEN_NEW_OPERATION",
             "Target moved after admission; start a fresh merge operation.",
         )
+    if raw.get("code") == "NO_COMMITS_MERGED":
+        return "NO_COMMITS_MERGED", details, _action(
+            "CHECK_WORKER_THEN_NEW_OPERATION",
+            "No commits reached the target branch; verify the worker branch before retrying.",
+        )
     if raw.get("conflicts"):
         details["paths"] = list(raw["conflicts"])
         return "CONFLICT", details, _action(
             "RESOLVE_ON_WORKER_THEN_NEW_OPERATION",
             "Resolve and commit the conflict on the worker branch, then start a new operation; do not merge the target manually.",
diff --git a/docs/workers/fix-merge-report.md b/docs/workers/fix-merge-report.md
index b682d423a..9a9f8ed47 100644
--- a/docs/workers/fix-merge-report.md
+++ b/docs/workers/fix-merge-report.md
@@ -1,4 +1,6 @@
 # Reusable workflow notes
 
 - Post-commit stages can fail after an earlier durable side effect. Preserve completed sub-results on the shared finalization payload before entering later transactions, then make response normalization fall back to that payload when the aggregate result is partial.
 - When acceptance names a mutation, keep the regression oracle in the repository and run that named test against the mutation; one-off probes only diagnose the defect.
+- A Git switch followed by durable task binding needs compensation on binding exceptions: restore the prior branch and lifecycle before reporting failure, or the worker becomes permanently unmergeable.
+- A named acceptance command can be green while the requested regression oracle is absent; freeze newly authored red tests before changing production behavior.
diff --git a/tests/test_task_tracker_integration.py b/tests/test_task_tracker_integration.py
index 34bccf6d2..6d8c28519 100644
--- a/tests/test_task_tracker_integration.py
+++ b/tests/test_task_tracker_integration.py
@@ -355,10 +355,113 @@ async def test_t2_bound_task_and_outcome_are_validated_before_git(monkeypatch):
     )
     assert calls == [], "a contentful task merge needs an explicit continue/complete outcome"
     assert result["commit_point"] == "not_reached"
 
 
+@pytest.mark.asyncio
+async def test_t2_merge_rejects_target_equal_worker_branch_before_git(monkeypatch):
+    """A stale base pointing at the worker branch cannot close its bound task."""
+    import app.routes.sessions as sessions_route
+    from app import tm
+    from app.db import get_session
+
+    _init_db()
+    _seed_project()
+    with tm._conn() as connection:
+        task = tm.create_task(
+            connection, "project", "Bound task", par_number=42, status="in_progress",
+        )
+        connection.execute(
+            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
+            ("self-target-worker", task["id"]),
+        )
+    _save_worker(session_id="self-target-worker", task_id="42")
+    found = _prepare_merge(monkeypatch, session_id="self-target-worker")
+    monkeypatch.setattr(
+        sessions_route, "_session_base_branch", lambda *_args: found.branch,
+    )
+    merge = MagicMock()
+    monkeypatch.setattr("app.workspace.merge_worktree_to_main", merge)
+
+    result = await sessions_route.execute_merge_session(
+        session_id=found.id,
+        expected_name=found.name,
+        expected_scope=found.scope,
+        expected_branch=found.branch,
+        expected_head="a" * 40,
+        req={
+            "scope": "/scope",
+            "task_outcome": "complete",
+            "merge_schema_version": 2,
+        },
+    )
+
+    assert result["ok"] is False
+    assert result["commit_point"] == "not_reached"
+    assert "worker branch" in result["error"]
+    merge.assert_not_called()
+    with tm._conn() as connection:
+        unchanged = tm.get_task_by_id(connection, task["id"])
+    assert (unchanged["status"], unchanged["worker_session_id"]) == (
+        "in_progress", "self-target-worker",
+    )
+    assert get_session(found.id)["task_id"] == "42"
+
+
+@pytest.mark.asyncio
+async def test_t2_zero_commit_merge_does_not_close_task(monkeypatch):
+    """A no-op merge is a failed pre-commit outcome, not a completed task."""
+    import app.routes.sessions as sessions_route
+    from app import tm
+    from app.db import get_session
+
+    _init_db()
+    _seed_project()
+    with tm._conn() as connection:
+        task = tm.create_task(
+            connection, "project", "No-op task", par_number=42, status="in_progress",
+        )
+        connection.execute(
+            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
+            ("noop-worker", task["id"]),
+        )
+    _save_worker(session_id="noop-worker", task_id="42")
+    found = _prepare_merge(monkeypatch, session_id="noop-worker")
+    merge = MagicMock(return_value={
+        "ok": True,
+        "commits_merged": 0,
+        "branch": found.branch,
+        "merged_commits": {},
+        "target_before": "a" * 40,
+        "target_after": "a" * 40,
+    })
+    monkeypatch.setattr("app.workspace.merge_worktree_to_main", merge)
+
+    result = await sessions_route.execute_merge_session(
+        session_id=found.id,
+        expected_name=found.name,
+        expected_scope=found.scope,
+        expected_branch=found.branch,
+        expected_head="a" * 40,
+        req={
+            "scope": "/scope",
+            "task_outcome": "complete",
+            "merge_schema_version": 2,
+        },
+    )
+
+    assert result["ok"] is False
+    assert result["commit_point"] == "not_reached"
+    assert result["code"] == "NO_COMMITS_MERGED"
+    assert "no new commits" in result["error"]
+    merge.assert_called_once()
+    with tm._conn() as connection:
+        unchanged = tm.get_task_by_id(connection, task["id"])
+    assert unchanged["status"] == "in_progress"
+    assert get_session(found.id)["task_id"] == "42"
+
+
 @pytest.mark.asyncio
 async def test_t2_unknown_commit_header_is_rejected_before_target_mutation(
     monkeypatch, tmp_path,
 ):
### 1b28729ec #406: #399-fix: freeze par collision regression oracle

diff --git a/app/tm.py b/app/tm.py
index 19e73c875..c1fc16c5e 100644
--- a/app/tm.py
+++ b/app/tm.py
@@ -4,10 +4,11 @@ Takes sqlite3.Connection; callers manage transactions. External integrations are
 """
 
 import json
 import logging
 import sqlite3
+import threading
 from contextlib import contextmanager
 from contextvars import ContextVar
 from dataclasses import dataclass
 from datetime import datetime, timezone
 from hashlib import sha256
@@ -16,16 +17,18 @@ from typing import Iterator, TypedDict
 
 logger = logging.getLogger("tm")
 
 from app.db import _conn
 from app.ia.task_store import (
+    IdentityConflictError,
     ProjectionDebtError,
     TaskStore,
     build_migration_manifest,
 )
 
 VALID_STATUSES = {"backlog", "new", "in_progress", "done", "cancelled"}
+_TASK_CREATE_LOCK = threading.RLock()
 
 
 class TaskIdentity(TypedDict):
     id: int
     project_id: str
@@ -1001,11 +1004,12 @@ def api_create_task(project_id: str, title: str, price: int = 0,
                     description: str = "", assignee: str = "",
                     status: str = "new", scope: str = "",
                     priority: int = 2, acceptance_command: str = "",
                     acceptance_manifest: list[str] | None = None,
                     acceptance_required: bool = False,
-                    acceptance_actor: dict | None = None) -> dict:
+                    acceptance_actor: dict | None = None,
+                    _canonical_par_number: int | None = None) -> dict:
     with _conn() as conn:
         conn.execute("BEGIN IMMEDIATE")
         try:
             project = None
             if project_id:
@@ -1027,10 +1031,19 @@ def api_create_task(project_id: str, title: str, price: int = 0,
                     f"project '{requested}' is not registered; "
                     f"allowed project scopes: {allowed_text}"
                 )
 
             resolved_project_id = project["id"]
+            legacy_next = _next_par(conn, resolved_project_id)
+            if (
+                _canonical_par_number is not None
+                and legacy_next != _canonical_par_number
+            ):
+                raise IdentityConflictError(
+                    f"task display counter mismatch in {resolved_project_id}: "
+                    f"canonical={_canonical_par_number}, legacy={legacy_next}"
+                )
             task = create_task(
                 conn, resolved_project_id, title,
                 price_rub=price,
                 description=description,
                 assignee=assignee,
@@ -1038,10 +1051,11 @@ def api_create_task(project_id: str, title: str, price: int = 0,
                 priority=priority,
                 acceptance_command=acceptance_command,
                 acceptance_manifest=acceptance_manifest,
                 acceptance_required=acceptance_required,
                 acceptance_actor=acceptance_actor,
+                par_number=_canonical_par_number,
             )
             conn.commit()
         except Exception:
             conn.rollback()
             raise
@@ -1572,38 +1586,50 @@ def api_create_task(project_id: str, title: str, price: int = 0,
             )
         except Exception as error:
             return _shadow_failure(legacy, context, error)
         return _shadow_result(legacy, candidate, context, _CREATE_COMPARE_FIELDS)
 
-    with _conn() as conn:
-        project = resolve_project_selector(conn, project_id) if project_id else None
-        if project is None and scope:
-            project = _project_for_session_scope(conn, scope)
-        if not project or not str(project.get("scope") or "").strip():
-            raise ValueError(f"project '{project_id or scope}' is not registered")
-        resolved_project_id = project["id"]
-    candidate = store.task_create(
-        project_id=resolved_project_id,
-        title=title,
-        price=price,
-        description=description,
-        assignee=assignee,
-        status=status,
-        priority=priority,
-        acceptance_command=acceptance_command,
-        acceptance_manifest=acceptance_manifest,
-        acceptance_required=acceptance_required,
-        expected_head=store.canonical_head,
-    )
-    legacy = _legacy_api_create_task(
-        resolved_project_id, title, price, description, assignee, status,
-        priority=priority,
-        acceptance_command=acceptance_command,
-        acceptance_manifest=acceptance_manifest,
-        acceptance_required=acceptance_required,
-        acceptance_actor=acceptance_actor,
-    )
+    with _TASK_CREATE_LOCK:
+        with _conn() as conn:
+            project = resolve_project_selector(conn, project_id) if project_id else None
+            if project is None and scope:
+                project = _project_for_session_scope(conn, scope)
+            if not project or not str(project.get("scope") or "").strip():
+                raise ValueError(f"project '{project_id or scope}' is not registered")
+            resolved_project_id = project["id"]
+            legacy_next = _next_par(conn, resolved_project_id)
+        canonical_next = int(
+            store.task_list(project=resolved_project_id)["next_display_number"]
+        )
+        if canonical_next != legacy_next:
+            raise IdentityConflictError(
+                f"task display counter mismatch in {resolved_project_id}: "
+                f"canonical={canonical_next}, legacy={legacy_next}"
+            )
+        candidate = store.task_create(
+            project_id=resolved_project_id,
+            title=title,
+            price=price,
+            description=description,
+            assignee=assignee,
+            status=status,
+            priority=priority,
+            acceptance_command=acceptance_command,
+            acceptance_manifest=acceptance_manifest,
+            acceptance_required=acceptance_required,
+            display_number=canonical_next,
+            expected_head=store.canonical_head,
+        )
+        legacy = _legacy_api_create_task(
+            resolved_project_id, title, price, description, assignee, status,
### 43a96ed31 #413: freeze merge delivery visibility oracle

diff --git a/app/merge_operations.py b/app/merge_operations.py
index 5881a718f..91f554602 100644
--- a/app/merge_operations.py
+++ b/app/merge_operations.py
@@ -1015,10 +1015,28 @@ def normalize_merge_result(
             ),
         )
         result["git"]["status"] = "UNKNOWN"
         return result
 
+    # A successful response with an unchanged target and no transferred commits is
+    # not a merge. Keep this invariant here as well as in the route: operation results
+    # can come from an older server or a resumed runner, and neither may close a task.
+    no_commits_merged = (
+        raw.get("target_before")
+        and raw.get("target_before") == raw.get("target_after")
+        and int(raw.get("commits_merged") or 0) == 0
+    )
+    if no_commits_merged:
+        raw = {
+            **raw,
+            "ok": False,
+            "state": "failed",
+            "commit_point": "not_reached",
+            "code": "NO_COMMITS_MERGED",
+            "error": "merge produced no new commits",
+        }
+
     raw_state = str(raw.get("state") or ("merged" if raw.get("ok") else "failed"))
     raw_point = str(raw.get("commit_point") or "unknown")
     commit_point = {
         "target_committed": "REACHED",
         "not_reached": "NOT_REACHED",
diff --git a/tests/test_merge_operations.py b/tests/test_merge_operations.py
index 0a910536a..43f8442bb 100644
--- a/tests/test_merge_operations.py
+++ b/tests/test_merge_operations.py
@@ -298,10 +298,36 @@ def test_failed_not_reached_and_noop_are_not_permanently_deduped(merge_db):
     )
     assert created_after_noop is True and status == 202
     assert after_noop["operation_id"] != second_id
 
 
+def test_normalize_rejects_zero_commit_noop_even_when_upstream_is_failed():
+    import app.merge_operations as operations
+
+    result = operations.normalize_merge_result(
+        "noop-operation",
+        {
+            "ok": False,
+            "state": "partial",
+            "commit_point": "target_committed",
+            "target_branch": "main",
+            "target_before": "a" * 40,
+            "target_after": "a" * 40,
+            "worker_branch": "task-42/worker",
+            "worker_head": "b" * 40,
+            "commits_merged": 0,
+            "error": "post-merge accounting failed",
+        },
+        operations.normalize_request(name="worker", scope="/scope", target="main"),
+    )
+
+    assert result["operation_state"] == "FAILED"
+    assert result["commit_point"] == "NOT_REACHED"
+    assert result["git"]["status"] == "FAILED"
+    assert result["error"]["code"] == "NO_COMMITS_MERGED"
+
+
 def test_unresolved_partial_blocks_new_key_even_when_snapshot_drifted(merge_db):
     import app.merge_operations as operations
 
     request = operations.normalize_request(name="worker", scope="/scope", target="main")
     operation_id = str(uuid.uuid4())
@@ -444,11 +470,15 @@ async def test_restore_runs_pending_once_after_fingerprint_recheck(merge_db, mon
     monkeypatch.setattr("app.routes.sessions.execute_merge_session", fake_execute)
     await operations.restore_merge_operations()
     await asyncio.gather(*list(operations._runner_tasks.values()))
 
     assert calls == 1
-    assert operations.get_operation_result(operation_id)["operation_state"] == "SUCCEEDED"
+    result = operations.get_operation_result(operation_id)
+    assert result["operation_state"] == "FAILED"
+    assert result["git"]["status"] == "FAILED"
+    assert result["git"]["commits_merged"] == 0
+    assert result["error"]["code"] == "NO_COMMITS_MERGED"
 
 
 @pytest.mark.asyncio
 async def test_runner_pins_persisted_base_branch_before_execution(merge_db, monkeypatch):
     import app.db as dbmod
diff --git a/tests/test_task_tracker_integration.py b/tests/test_task_tracker_integration.py
index 6d8c28519..fae94c67b 100644
--- a/tests/test_task_tracker_integration.py
+++ b/tests/test_task_tracker_integration.py
@@ -396,10 +396,13 @@ async def test_t2_merge_rejects_target_equal_worker_branch_before_git(monkeypatc
     )
 
     assert result["ok"] is False
     assert result["commit_point"] == "not_reached"
     assert "worker branch" in result["error"]
+    assert found.branch in result["error"]
+    assert found.branch in result["target_branch"]
+    assert found.branch in result["worker_branch"]
     merge.assert_not_called()
     with tm._conn() as connection:
         unchanged = tm.get_task_by_id(connection, task["id"])
     assert (unchanged["status"], unchanged["worker_session_id"]) == (
         "in_progress", "self-target-worker",
@@ -710,10 +713,65 @@ async def test_t3_complete_merge_atomically_links_and_closes_current_task(monkey
     assert closed["worker_session_id"] is None
     assert closed["completed_at"]
     assert "abc123" in closed["git_commits"]
 
 
+@pytest.mark.asyncio
+async def test_t3_real_complete_merge_transfers_commits_before_closing_task(
+    monkeypatch, tmp_path,
+):
+    """The success control uses Git, so task closure cannot hide a no-op merge."""
+    import app.routes.sessions as sessions_route
+    import app.workspace as workspace
+    from app import tm
+
+    _init_db()
+    repo = _make_git_scope(monkeypatch, tmp_path)
+    scope = str(repo)
+    with tm._conn() as connection:
+        tm.ensure_project(connection, "project", scope=scope)
+        task = tm.create_task(
+            connection, "project", "Real transfer", par_number=42, status="in_progress",
+        )
+        connection.execute(
+            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
+            ("real-complete-worker", task["id"]),
+        )
+    worktree = workspace.create_worktree(scope, "real-complete-worker", task_id="42")
+    worker_head = _commit_file(worktree.path, "real.txt", "#42: real transfer")
+    _save_worker(
+        session_id="real-complete-worker", task_id="42", scope=scope,
+        worktree_path=worktree.path, branch=worktree.branch,
+    )
+    found = _prepare_merge(monkeypatch, session_id="real-complete-worker", scope=scope)
+    target_before = subprocess.run(
+        ["git", "rev-parse", "main"], cwd=repo,
+        check=True, capture_output=True, text=True,
+    ).stdout.strip()
+
### d932e027d спавн заводит задачу через canonical, а не мимо него

diff --git a/app/tm.py b/app/tm.py
index c1fc16c5e..88577b646 100644
--- a/app/tm.py
+++ b/app/tm.py
@@ -356,23 +356,30 @@ def create_task(conn: sqlite3.Connection, project_id: str, title: str,
         "sync_revision": 0,
     }
 
 
 def create_task_for_scope(scope: str, title: str) -> dict:
-    """Create an unbound task in the project owning ``scope``."""
+    """Create an unbound task in the project owning ``scope``.
+
+    Идёт тем же путём, что и `task_create` агента, и это ЕДИНСТВЕННАЯ причина, по которой
+    функция не пишет в legacy напрямую. Прямая запись была вторым владельцем нумерации: она
+    двигала legacy-счётчик, не трогая canonical, а `api_create_task` потом сверяет их и
+    отказывает НАВСЕГДА (`task display counter mismatch`). 28.08 веер из трёх детей развёл
+    счётчики на 3, и проект не мог завести ни одной задачи.
+    """
     with _conn() as conn:
-        conn.execute("BEGIN IMMEDIATE")
-        try:
-            project = get_project_by_scope(conn, scope.rstrip("/"))
-            if not project:
-                raise ValueError(f"scope '{scope}' has no task project")
-            task = create_task(conn, project["id"], title, status="new")
-            conn.commit()
-            return task
-        except Exception:
-            conn.rollback()
-            raise
+        project = get_project_by_scope(conn, scope.rstrip("/"))
+        if not project:
+            raise ValueError(f"scope '{scope}' has no task project")
+        project_id = project["id"]
+    created = api_create_task(project_id, title, status="new")
+    # Вызывающий (спавн, app/routes/sessions.py) строит имя ветки из `par_number`, а
+    # `api_create_task` отдаёт номер как строковый `par`. Отдаём оба, чтобы форма ответа
+    # осталась прежней и ветка не превратилась в `task-None/<worker>`.
+    if "par_number" not in created:
+        created = {**created, "par_number": int(created["par"])}
+    return created
 
 
 def discard_unbound_task(task_id: int) -> bool:
     """Remove a task allocated for a spawn that never published its worker."""
     with _conn() as conn:
### a10f14517 номер задачи выдаёт только один владелец, обход падает громко

diff --git a/app/tm.py b/app/tm.py
index 88577b646..3406bd2bf 100644
--- a/app/tm.py
+++ b/app/tm.py
@@ -306,11 +306,24 @@ def create_task(conn: sqlite3.Connection, project_id: str, title: str,
         raise ValueError(f"Invalid status: {status}")
     if price_rub < 0:
         raise ValueError("price_rub must be >= 0")
 
     now = _now()
-    par = par_number if par_number is not None else _next_par(conn, project_id)
+    # Номер выдаёт ОДИН владелец — `api_create_task`, который согласует его с canonical и
+    # передаёт сюда явно. Собственная выдача номера здесь и есть механизм, которым
+    # открывается новая дверь мимо canonical: legacy-счётчик уезжает вперёд, гейт
+    # `task display counter mismatch` заклинивает проект насмерть (28.08, comfy: разрыв 3 → 8
+    # за три часа, ни одной новой задачи). Fail loud вместо тихого расхождения.
+    if par_number is None:
+        if _ia_context() is not None:
+            raise RuntimeError(
+                "create_task cannot allocate a task number: call api_create_task, "
+                "which agrees the number with the canonical store first"
+            )
+        par = _next_par(conn, project_id)
+    else:
+        par = par_number
 
     command = (acceptance_command or "").strip()
     from app.acceptance import parse_acceptance_command
 
     parse_acceptance_command(command)
### 7b8836462 Merge remote-tracking branch 'origin/main'

### 8239760c7 #416: research misleading zero-commit merge failure

diff --git a/app/merge_operations.py b/app/merge_operations.py
index 91f554602..dd3dacdd9 100644
--- a/app/merge_operations.py
+++ b/app/merge_operations.py
@@ -937,10 +937,16 @@ def _classify_failure(raw: dict[str, Any], message: str) -> tuple[str, dict[str,
         return "TARGET_HEAD_CHANGED", details, _action(
             "REFRESH_TARGET_THEN_NEW_OPERATION",
             "Target moved after admission; start a fresh merge operation.",
         )
     if raw.get("code") == "NO_COMMITS_MERGED":
+        if "target working tree is dirty" in lower:
+            details["paths_text"] = message
+            return "NO_COMMITS_MERGED", details, _action(
+                "CLEAN_TARGET_THEN_NEW_OPERATION",
+                "Clean the target worktree, then start a new merge operation.",
+            )
         return "NO_COMMITS_MERGED", details, _action(
             "CHECK_WORKER_THEN_NEW_OPERATION",
             "No commits reached the target branch; verify the worker branch before retrying.",
         )
     if raw.get("conflicts"):
@@ -1030,11 +1036,11 @@ def normalize_merge_result(
             **raw,
             "ok": False,
             "state": "failed",
             "commit_point": "not_reached",
             "code": "NO_COMMITS_MERGED",
-            "error": "merge produced no new commits",
+            "error": raw.get("error") or "merge produced no new commits",
         }
 
     raw_state = str(raw.get("state") or ("merged" if raw.get("ok") else "failed"))
     raw_point = str(raw.get("commit_point") or "unknown")
     commit_point = {
@@ -1047,10 +1053,12 @@ def normalize_merge_result(
     conflicts = raw.get("conflicts") if isinstance(raw.get("conflicts"), list) else []
     if raw.get("ok"):
         git_status = "SUCCEEDED"
     elif raw_state == "conflict" or conflicts:
         git_status = "CONFLICT"
+    elif raw.get("code") == "NO_COMMITS_MERGED":
+        git_status = "FAILED"
     elif "working tree is dirty" in message.lower():
         git_status = "DIRTY"
     elif commit_point == "UNKNOWN":
         git_status = "UNKNOWN"
     elif commit_point == "REACHED":
### cc15369de #423: report merge conflict paths

diff --git a/app/merge_operations.py b/app/merge_operations.py
index dd3dacdd9..5cde45898 100644
--- a/app/merge_operations.py
+++ b/app/merge_operations.py
@@ -936,10 +936,16 @@ def _classify_failure(raw: dict[str, Any], message: str) -> tuple[str, dict[str,
         details["target_recheck"] = raw.get("target_recheck") or {}
         return "TARGET_HEAD_CHANGED", details, _action(
             "REFRESH_TARGET_THEN_NEW_OPERATION",
             "Target moved after admission; start a fresh merge operation.",
         )
+    if raw.get("conflicts"):
+        details["paths"] = list(raw["conflicts"])
+        return "CONFLICT", details, _action(
+            "RESOLVE_ON_WORKER_THEN_NEW_OPERATION",
+            "Resolve and commit the conflict on the worker branch, then start a new operation; do not merge the target manually.",
+        )
     if raw.get("code") == "NO_COMMITS_MERGED":
         if "target working tree is dirty" in lower:
             details["paths_text"] = message
             return "NO_COMMITS_MERGED", details, _action(
                 "CLEAN_TARGET_THEN_NEW_OPERATION",
@@ -947,16 +953,10 @@ def _classify_failure(raw: dict[str, Any], message: str) -> tuple[str, dict[str,
             )
         return "NO_COMMITS_MERGED", details, _action(
             "CHECK_WORKER_THEN_NEW_OPERATION",
             "No commits reached the target branch; verify the worker branch before retrying.",
         )
-    if raw.get("conflicts"):
-        details["paths"] = list(raw["conflicts"])
-        return "CONFLICT", details, _action(
-            "RESOLVE_ON_WORKER_THEN_NEW_OPERATION",
-            "Resolve and commit the conflict on the worker branch, then start a new operation; do not merge the target manually.",
-        )
     if "target working tree is dirty" in lower:
         details["paths_text"] = message
         return "TARGET_DIRTY", details, _action(
             "CLEAN_TARGET_THEN_NEW_OPERATION",
             "Clean the target worktree, then start a new merge operation.",
@@ -1028,10 +1028,11 @@ def normalize_merge_result(
     # can come from an older server or a resumed runner, and neither may close a task.
     no_commits_merged = (
         raw.get("target_before")
         and raw.get("target_before") == raw.get("target_after")
         and int(raw.get("commits_merged") or 0) == 0
+        and not raw.get("conflicts")
     )
     if no_commits_merged:
         raw = {
             **raw,
             "ok": False,