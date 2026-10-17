# Context for item-42

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index 8e8d39d3c..da82e0e81 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -459,40 +459,166 @@ async def test_task_create_omits_project_to_use_callers_scope(monkeypatch):
         assert method == "POST"
         assert path == "/api/tm/tasks"
         assert "project" not in kwargs["json"]
         assert kwargs["json"]["scope"] == "/scope"
         captured.update(kwargs["json"])
         return {"par": "1", "id": 1, "project": "/scope"}
 
     with patch.object(m, "_api", side_effect=fake_api):
         raw = await m.task_create(title="Mapped task")
 
     assert json.loads(raw)["project"] == "/scope"
 
     class OldRouteRequest(BaseModel):
         title: str
         project: str
 
     with pytest.raises(ValidationError):
         OldRouteRequest.model_validate(captured)
 
 
+async def _call_tm_task_create(method, path, **kwargs):
+    from app import tm
+
+    assert method == "POST"
+    assert path == "/api/tm/tasks"
+    body = kwargs["json"]
+    return tm.api_create_task(
+        body.get("project", ""),
+        body["title"],
+        price=body["price"],
+        description=body["description"],
+        assignee=body["assignee"],
+        status=body["status"],
+        scope=body["scope"],
+        priority=body["priority"],
+        acceptance_command=body["acceptance_command"],
+    )
+
+
+def _register_session_scope(scope: str) -> None:
+    from app.db import _conn, init_db
+
+    init_db()
+    with _conn() as conn:
+        conn.execute(
+            """INSERT INTO sessions (id, name, scope, cwd, model, status, created_at)
+               VALUES (?, ?, ?, ?, ?, ?, ?)""",
+            (
+                "session-scope-authority",
+                "scope-authority",
+                scope,
+                scope,
+                "claude-sonnet-5[1m]",
+                "idle",
+                datetime.now(timezone.utc).isoformat(),
+            ),
+        )
+
+
+@pytest.mark.asyncio
+async def test_task_create_admits_exact_session_scope_when_tm_project_is_stale(monkeypatch):
+    import app.mcp_stdio as m
+    from app import tm
+
+    scope = "/home/kesha/projects/VPN-Service"
+    _register_session_scope(scope)
+    monkeypatch.setattr(m, "SCOPE", scope)
+
+    with tm._conn() as conn:
+        assert conn.execute(
+            "SELECT 1 FROM tm_projects WHERE scope = ?", (scope,)
+        ).fetchone() is None
+
+    with patch.object(m, "_api", side_effect=_call_tm_task_create):
+        raw = await m.task_create(title="VPN registration oracle")
+
+    result = json.loads(raw)
+    assert result["title"] == "VPN registration oracle"
+    with tm._conn() as conn:
+        stored_scope = conn.execute(
+            """SELECT p.scope
+               FROM tm_tasks AS t
+               JOIN tm_projects AS p ON p.id = t.project_id
+               WHERE t.id = ?""",
+            (result["task_id"],),
+        ).fetchone()[0]
+    assert stored_scope == scope
+
+
+@pytest.mark.asyncio
+async def test_task_create_rejects_scope_absent_from_session_and_projects(monkeypatch):
+    import app.mcp_stdio as m
+    from app import tm
+
+    scope = "/home/kesha/projects/does-not-exist"
+    from app.db import init_db
+    init_db()
+    monkeypatch.setattr(m, "SCOPE", scope)
+
+    with patch.object(m, "_api", side_effect=_call_tm_task_create):
+        with pytest.raises(ValueError, match="project '.*/does-not-exist' is not registered"):
+            await m.task_create(title="must be rejected")
+
+    with tm._conn() as conn:
+        assert conn.execute("SELECT COUNT(*) FROM tm_projects").fetchone()[0] == 0
+        assert conn.execute("SELECT COUNT(*) FROM tm_tasks").fetchone()[0] == 0
+
+
+@pytest.mark.asyncio
+async def test_task_create_keeps_caller_scope_and_registered_project_authorization(monkeypatch):
+    import app.mcp_stdio as m
+    from app import tm
+    from app.db import init_db
+
+    init_db()
+    now = tm._now()
+    with tm._conn() as conn:
+        for project_id, scope, prefix in (
+            ("lower", "/lower", "LOW"),
+            ("upper", "/upper", "UPR"),
+        ):
+            conn.execute(
+                """INSERT INTO tm_projects
+                   (id, name, prefix, scope, created_at)
+                   VALUES (?, ?, ?, ?, ?)""",
+                (project_id, project_id, prefix, scope, now),
+            )
+
+    monkeypatch.setattr(m, "SCOPE", "/lower")
+    with patch.object(m, "_api", side_effect=_call_tm_task_create):
+        await m.task_create(title="caller-scoped task")
+        await m.task_create(title="explicit registered task", project="/upper")
+
+    with tm._conn() as conn:
+        rows = conn.execute(
+            """SELECT t.title, p.scope
+               FROM tm_tasks AS t
+               JOIN tm_projects AS p ON p.id = t.project_id
+               ORDER BY t.id"""
+        ).fetchall()
+    assert [(row["title"], row["scope"]) for row in rows] == [
+        ("caller-scoped task", "/lower"),
+        ("explicit registered task", "/upper"),
+    ]
+
+
 @pytest.mark.asyncio
 async def test_task_get_and_update_prefer_explicit_project_over_scope(monkeypatch):
     import app.mcp_stdio as m
 
     monkeypatch.setattr(m, "SCOPE", "/lower")
     calls = []
 
     async def fake_api(method, path, **kwargs):
         calls.append((method, path, kwargs))
         return {"project": "Seedon", "par": "1", "updated": ["title"]}
 
     with patch.object(m, "_api", side_effect=fake_api):
         await m.task_get("1", project="Seedon")
         await m.task_update("1", title="changed", project="Seedon")
 
     assert calls[0][2]["params"] == {"project": "Seedon"}
     assert calls[1][2]["params"] == {"project": "Seedon"}
     assert calls[1][2]["json"] == {"title": "changed"}
 
 


## Later history of the touched files on main (after this commit)

53 later commits touch these paths; the first 40 (oldest first):
b0b72d655 2026-08-16 #294: #294: plan secure artifact links
bd4f6e61a 2026-08-16 #304: #304: select codex review model explicitly
1e020d60e 2026-08-17 #311: #311: freeze durable delivery RED oracles
9a1e2d108 2026-08-17 #314: #314: freeze enforcement and analytics RED oracles
0707d9257 2026-08-19 #343: одно правило допуска по квоте, прежние квотные системы вырезаны
3e4d87982 2026-08-23 #279: #279: fix acceptance command contract
e2ecc033d 2026-08-23 #293: #293: freeze ownership lifecycle red tests
0a9ad8130 2026-08-23 #383: #383: expose acceptance command recovery via task update
71374ea56 2026-08-23 #385: #385: research deferred turn control and provenance
9d2627281 2026-08-24 Merge origin/main into main (2026-08-24 sync)
76b0504fd 2026-08-24 Resolve acceptance clear semantics after sync
6f874ace5 2026-08-24 #248: make task state platform-owned and restart-safe
e22368b06 2026-08-25 #348: #348: handle send_file version skew
08b75e851 2026-08-25 #359: reserve MCP slots for canonical tools
c885f10e5 2026-08-25 #360: reload MCP tools after Codex resume
abd0f4281 2026-08-30 #417: тест доставки проверяет поведение, а не дословный текст сообщения
57038767b 2026-08-30 #417: switch memory prompt to file-first retrieval
feff52e3b 2026-08-31 #423: freeze resolved-operation success oracle
9093641f3 2026-09-01 v2.41.0: аудит кодовой базы — 27 дефектов закрыто (3 P0 в tm.py), 2 фикса откачены как регрессии
5c0b0880f 2026-09-02 #431: attach UTF-8 text files to messages
4e5940ef6 2026-09-02 #433: research message provenance
2a048e616 2026-09-03 #465: research taskless adhoc merge deadlock
cda209407 2026-09-04 #491: freeze self-service context refusal oracle
b1c393ce3 2026-09-05 test: verify bounded knowledge packets and native instruction loading
b0f328975 2026-09-05 Reduce merge waiting and preserve Bash failure evidence
55b4b737f 2026-09-07 Restrict model review to executors and preserve approved design experiments
c61f56e85 2026-09-07 #533: repair stale CI regression tests and receipt migration
ad5d17664 2026-09-07 Merge VPS main with laptop runtime-control fixes
98574f427 2026-09-08 Replace duplicate task stores with private Git and one versioned SQLite projection
5f7e72c50 2026-09-08 Add reusable idle watches and label dashboard message channel
d9ce293fa 2026-09-08 Integrate current main before storage cutover
643d47211 2026-09-20 #V-597: модельное ревью заморожено — тул codex_review снят с регистрации, скилл и правила закомментированы
88c25b2a1 2026-09-20 #V-599: merge_worker снова синхронный — ждёт исход до 10 с и снимает лишнее пробуждение
f6d969c1c 2026-09-20 V-602: update MCP descriptions and parallelize agent listing
4bd1a5365 2026-09-21 V-603: clarify worker refusals and background receipts
de5d62a52 2026-09-22 V-576: #V-576: каталог проектов файлом и теги задач вместо второй сущности проекта
c31aa1ec7 2026-09-23 Тест замороженного ревью следует за сменой маршрута на GPT-6 Luna
63fd7ac22 2026-09-24 V-631: #V-631: merge taskless adhoc work against explicit task
7ae410f8d 2026-09-24 V-621: разбить общий каталог проектов на файлы по scope
9035836a0 2026-09-25 V-636: схемы функций для GigaChat без nullable/пустых object, панель допуска скрыта вне owner mode, текст про OpenRouter у харнеса нейтральный

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### b0b72d655 #294: #294: plan secure artifact links

diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index da82e0e81..9b90f8397 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -24,10 +24,63 @@ async def _protocol_call(module, name, arguments):
         params=CallToolRequestParams(name=name, arguments=arguments),
     ))
     return wrapped.root
 
 
+@pytest.mark.asyncio
+async def test_t2_publish_artifact_sends_only_path_caption_and_ttl(monkeypatch):
+    import app.mcp_stdio as m
+
+    api = AsyncMock(return_value={
+        "ok": True,
+        "artifact_id": "A" * 22,
+        "expires_at": 2_000_000_600,
+        "message_id": 77,
+    })
+    monkeypatch.setattr(m, "_api", api)
+
+    assert hasattr(m, "publish_artifact"), (
+        "#294 missing contract: MCP publish_artifact tool is not registered"
+    )
+    result = await m.publish_artifact("/scope/report.html", "report", 600)
+
+    api.assert_awaited_once()
+    args, kwargs = api.await_args
+    assert args == ("POST", "/api/artifacts/publish")
+    assert kwargs["json"] == {
+        "path": "/scope/report.html",
+        "caption": "report",
+        "ttl_seconds": 600,
+    }
+    serialized = str(result)
+    assert "/scope/report.html" not in serialized
+    assert "#" not in serialized
+
+
+@pytest.mark.asyncio
+async def test_t2_publish_failure_never_automatically_uses_document_fallback(monkeypatch):
+    import app.mcp_stdio as m
+
+    api = AsyncMock(return_value={
+        "error": "artifact link failed; use send_file(path, as_document=True)",
+    })
+    auto_send = AsyncMock(side_effect=AssertionError("fallback must remain explicit"))
+    monkeypatch.setattr(m, "_api", api)
+    monkeypatch.setattr(m, "send_file", auto_send)
+
+    assert hasattr(m, "publish_artifact"), (
+        "#294 missing contract: MCP publish_artifact tool is not registered"
+    )
+    with pytest.raises(m.ApiToolError) as caught:
+        await m.publish_artifact("/scope/report.html", "report", 600)
+
+    auto_send.assert_not_awaited()
+    assert "send_file" in str(caught.value)
+    assert "as_document=True" in str(caught.value)
+    assert "/scope/report.html" not in str(caught.value)
+
+
 @pytest.mark.asyncio
 async def test_api_429_preserves_typed_fields_and_request_id(monkeypatch):
     import app.mcp_stdio as m
 
     seen_request_id = ""
### bd4f6e61a #304: #304: select codex review model explicitly

diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index 9b90f8397..012c13b43 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -1816,5 +1816,143 @@ async def test_resolve_merge_operation_reports_server_refusal(monkeypatch):
     with patch.object(m, "_api", side_effect=fake_api):
         out = await m.resolve_merge_operation(operation_id="op-1", reason="nothing to close")
 
     assert out.isError is True
     assert "OPERATION_NOT_BLOCKING" in out.content[0].text or "only PARTIAL" in out.content[0].text
+
+
+@pytest.mark.asyncio
+@pytest.mark.parametrize(
+    ("requested_model", "expected_model", "resume"),
+    [
+        ("gpt-5.6-luna", "gpt-5.6-luna", True),
+        ("gpt-5.6-sol", "gpt-5.6-sol", False),
+        ("gpt5.6luna", "gpt-5.6-luna", False),
+    ],
+)
+async def test_codex_review_model_reaches_quota_cli_job_and_accounting(
+    tmp_path, monkeypatch, requested_model, expected_model, resume,
+):
+    import app.mcp_stdio as m
+
+    if resume:
+        (tmp_path / "codex_sessions.json").write_text(json.dumps({
+            "sessions": {"review": {"uuid": "review-thread"}},
+        }))
+    calls = []
+
+    async def fake_api(method, path, **kwargs):
+        calls.append((method, path, kwargs))
+        if path == "/api/usage/readiness":
+            return {
+                "policy": "worker-weekly-v1",
+                "state": "available",
+                "model": expected_model,
+                "provider": "codex",
+                "observed_at": 2_000_000_000,
+                "valid_until": 2_000_000_300,
+            }
+        if method == "GET":
+            return {
+                "id": "requester-id",
+                "worktree_path": str(tmp_path),
+                "task_id": "304",
+            }
+        return {"id": "bg-review"}
+
+    monkeypatch.setattr(m, "_api", fake_api)
+    monkeypatch.setattr(m, "_codex_bin", lambda: "/usr/bin/codex")
+    monkeypatch.setattr(m, "WORKER_NAME", "review-author")
+    monkeypatch.setattr(m, "SCOPE", str(tmp_path))
+    monkeypatch.setattr(m.time, "time", lambda: 2_000_000_001)
+
+    result = await m.codex_review(
+        context="PROJECT CONTEXT: #304 model propagation fixture",
+        target="artifact.py",
+        output="review.md",
+        mode="exec",
+        resume=resume,
+        model=requested_model,
+    )
+
+    readiness = next(call for call in calls if call[1] == "/api/usage/readiness")
+    assert readiness[2]["params"] == {"model": expected_model}
+    job = next(call[2]["json"] for call in calls if call[1] == "/api/bg/jobs")
+    command = job["config"]["command"]
+    assert command.count(f"-m {expected_model}") == (2 if resume else 1)
+    assert f"--usage-model {expected_model}" in command
+    assert expected_model in job["message"]
+    assert expected_model in result
+    if resume:
+        assert "exec resume review-thread" in command
+
+
+@pytest.mark.asyncio
+async def test_codex_review_default_is_documented_and_stays_sol(tmp_path, monkeypatch):
+    import app.mcp_stdio as m
+
+    captured = {}
+
+    async def fake_api(method, path, **kwargs):
+        if path == "/api/usage/readiness":
+            captured["readiness"] = kwargs["params"]
+            return {
+                "policy": "worker-weekly-v1",
+                "state": "available",
+                "model": "gpt-5.6-sol",
+                "provider": "codex",
+                "observed_at": 2_000_000_000,
+                "valid_until": 2_000_000_300,
+            }
+        if method == "GET":
+            return {"id": "requester-id", "worktree_path": str(tmp_path)}
+        captured["job"] = kwargs["json"]
+        return {"id": "bg-review"}
+
+    monkeypatch.setattr(m, "_api", fake_api)
+    monkeypatch.setattr(m, "_codex_bin", lambda: "/usr/bin/codex")
+    monkeypatch.setattr(m, "SCOPE", str(tmp_path))
+    monkeypatch.setattr(m.time, "time", lambda: 2_000_000_001)
+
+    await m.codex_review(
+        context="PROJECT CONTEXT: #304 default fixture",
+        target="artifact.py",
+        output="review.md",
+        mode="exec",
+    )
+
+    tool = next(tool for tool in m.mcp._tool_manager.list_tools() if tool.name == "codex_review")
+    assert tool.parameters["properties"]["model"]["default"] == "gpt-5.6-sol"
+    assert "Omitted means gpt-5.6-sol" in tool.description
+    assert captured["readiness"] == {"model": "gpt-5.6-sol"}
+    assert "-m gpt-5.6-sol" in captured["job"]["config"]["command"]
+
+
+@pytest.mark.asyncio
+@pytest.mark.parametrize(
+    ("model", "message"),
+    [
+        ("not-a-model", "unknown model"),
+        ("claude-opus-5[1m]", "runtime 'claude'"),
+        ("grok-4.6", "runtime 'grok'"),
+        ("gpt-5.3-codex-spark", "Spark is forbidden"),
+    ],
+)
+async def test_codex_review_rejects_invalid_non_codex_and_spark_before_api(
+    monkeypatch, model, message,
+):
+    import app.mcp_stdio as m
+
+    api = AsyncMock(side_effect=AssertionError("invalid model must not reach any API"))
+    monkeypatch.setattr(m, "_api", api)
+
+    with pytest.raises(m.ApiToolError, match=message) as caught:
+        await m.codex_review(
+            context="PROJECT CONTEXT: #304 rejection fixture",
+            target="artifact.py",
+            mode="exec",
+            model=model,
+        )
+
+    assert caught.value.code == "invalid_argument"
+    assert caught.value.details["field"] == "model"
+    api.assert_not_awaited()
### 1e020d60e #311: #311: freeze durable delivery RED oracles

diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index 012c13b43..2dbab0df2 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -1,6 +1,7 @@
 import json
+import inspect
 
 import httpx
 import pytest
 from unittest.mock import AsyncMock, patch
 from datetime import datetime, timedelta, timezone
@@ -775,11 +776,11 @@ async def test_spawn_sends_model_policy_override_only_when_requested(
     else:
         assert captured["model_policy_override_reason"] == expected
 
 
 @pytest.mark.asyncio
-async def test_spawn_marks_parent_as_initial_task_sender(monkeypatch):
+async def test_t3_spawn_marks_parent_as_initial_task_sender(monkeypatch):
     import app.mcp_stdio as m
     monkeypatch.setattr(m, "SCOPE", "/s")
     monkeypatch.setattr(m, "WORKER_NAME", "parent-orchestrator")
     calls = []
 
@@ -800,11 +801,18 @@ async def test_spawn_marks_parent_as_initial_task_sender(monkeypatch):
             task="do it",
             repo_path="/s",
             model="claude-opus-5[1m]",
         )
 
-    send_call = next(call for call in calls if call[1] == "/api/sessions/child/send")
+    delivery_calls = [
+        call for call in calls
+        if call[1] == "/api/sessions/child/initial-deliveries"
+    ]
+    assert len(delivery_calls) == 1, (
+        "#311 missing behavior: spawn still uses synchronous /send"
+    )
+    send_call = delivery_calls[0]
     assert send_call[2]["sender"] == "parent-orchestrator"
 
 
 @pytest.mark.asyncio
 async def test_spawn_reports_exact_repo_mapping_when_scope_differs(monkeypatch, tmp_path):
@@ -933,11 +941,11 @@ async def test_spawn_malformed_success_fails_loud_without_task(
     assert missing in caught.value.details["missing"]
     assert caught.value.result["created"] == "unknown"
 
 
 @pytest.mark.asyncio
-async def test_spawn_task_delivery_error_reports_created_worker(monkeypatch):
+async def test_t3_spawn_task_delivery_error_reports_created_worker(monkeypatch):
     import app.mcp_stdio as m
 
     monkeypatch.setattr(m, "SCOPE", "/s")
     calls = []
 
@@ -948,28 +956,49 @@ async def test_spawn_task_delivery_error_reports_created_worker(monkeypatch):
                 "worktree_path": "/worktrees/child",
                 "branch": "task-88/child",
                 "repo_path": "/repo",
                 "git_common_dir": "/repo/.git",
             }
-        return {"error": "delivery unavailable"}
+        raise m.ApiToolError(
+            code="DELIVERY_ACCEPT_REJECTED",
+            message="delivery transaction rolled back before commit",
+            status=503,
+            retryable=True,
+            outcome_unknown=False,
+            details={"commit_state": "NOT_COMMITTED"},
+        )
 
     with patch.object(m, "_api", side_effect=fake_api):
         with pytest.raises(m.ApiToolError) as caught:
             await m.spawn_worker(
                 name="child", task="do it", repo_path="/repo",
                 model="gpt-5.6-sol",
             )
 
-    assert calls == ["/api/sessions", "/api/sessions/child/send"]
+    assert calls == [
+        "/api/sessions",
+        "/api/sessions/child/initial-deliveries",
+    ]
     assert "worker 'child' was created" in caught.value.message.lower()
     assert caught.value.outcome_unknown is False
     assert caught.value.result["worktree_path"] == "/worktrees/child"
-    assert caught.value.result["next_action"]["code"] == "SEND_INITIAL_TASK"
+    delivery_id = caught.value.result["delivery_id"]
+    assert delivery_id
+    assert caught.value.result["next_action"] == {
+        "code": "RETRY_SAME_DELIVERY",
+        "tool": "retry_initial_delivery",
+        "arguments": {
+            "name": "child",
+            "task": "do it",
+            "delivery_id": delivery_id,
+        },
+        "message": "Retry only this delivery id; do not create a new logical task.",
+    }
 
 
 @pytest.mark.asyncio
-async def test_spawn_unknown_delivery_preserves_mapping_and_forbids_resend(monkeypatch):
+async def test_t3_spawn_unknown_delivery_preserves_mapping_and_forbids_resend(monkeypatch):
     import app.mcp_stdio as m
 
     monkeypatch.setattr(m, "SCOPE", "/s")
 
     async def fake_api(_method, path, **_kwargs):
@@ -999,14 +1028,370 @@ async def test_spawn_unknown_delivery_preserves_mapping_and_forbids_resend(monke
     assert result.isError is True
     structured = result.structuredContent
     assert structured["error"]["outcome_unknown"] is True
     assert structured["result"]["created"] is True
     assert structured["result"]["worktree_path"] == "/worktrees/child"
-    assert structured["result"]["next_action"]["code"] == "CHECK_DELIVERY_STATE"
+    assert "delivery_id" in structured["result"], (
+        "#311 missing behavior: timeout result has no durable delivery id"
+    )
+    assert structured["result"]["delivery_id"]
+    assert structured["result"]["next_action"]["code"] == "CHECK_DELIVERY_STATUS"
+    assert structured["result"]["next_action"]["tool"] == "delivery_status"
+    assert structured["result"]["next_action"]["arguments"] == {
+        "delivery_id": structured["result"]["delivery_id"],
+    }
     assert "do not resend" in structured["result"]["next_action"]["message"].lower()
 
 
+@pytest.mark.asyncio
+async def test_t3_spawn_delivery_posts_caller_key_and_returns_accepted_receipt(
+    monkeypatch,
+):
+    import app.mcp_stdio as m
+
+    delivery_id = "00000000-0000-4000-8000-000000000311"
+    monkeypatch.setattr(m, "SCOPE", "/s")
+    monkeypatch.setattr(m, "WORKER_NAME", "parent-orchestrator")
+    assert "delivery_id" in inspect.signature(m.spawn_worker).parameters, (
+        "#311 missing behavior: spawn_worker has no caller delivery_id"
+    )
+    calls = []
+
+    async def fake_api(method, path, **kwargs):
+        calls.append((method, path, kwargs))
+        if path == "/api/sessions":
### 9a1e2d108 #314: #314: freeze enforcement and analytics RED oracles

diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index 2dbab0df2..bc3b920c1 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -2270,22 +2270,22 @@ async def test_codex_review_model_reaches_quota_cli_job_and_accounting(
     if resume:
         assert "exec resume review-thread" in command
 
 
 @pytest.mark.asyncio
-async def test_codex_review_default_is_documented_and_stays_sol(tmp_path, monkeypatch):
+async def test_codex_review_default_is_server_owned_luna_fast(tmp_path, monkeypatch):
     import app.mcp_stdio as m
 
     captured = {}
 
     async def fake_api(method, path, **kwargs):
         if path == "/api/usage/readiness":
             captured["readiness"] = kwargs["params"]
             return {
                 "policy": "worker-weekly-v1",
                 "state": "available",
-                "model": "gpt-5.6-sol",
+                "model": "gpt-5.6-luna",
                 "provider": "codex",
                 "observed_at": 2_000_000_000,
                 "valid_until": 2_000_000_300,
             }
         if method == "GET":
@@ -2304,14 +2304,14 @@ async def test_codex_review_default_is_documented_and_stays_sol(tmp_path, monkey
         output="review.md",
         mode="exec",
     )
 
     tool = next(tool for tool in m.mcp._tool_manager.list_tools() if tool.name == "codex_review")
-    assert tool.parameters["properties"]["model"]["default"] == "gpt-5.6-sol"
-    assert "Omitted means gpt-5.6-sol" in tool.description
-    assert captured["readiness"] == {"model": "gpt-5.6-sol"}
-    assert "-m gpt-5.6-sol" in captured["job"]["config"]["command"]
+    assert tool.parameters["properties"]["model"]["default"] == "gpt-5.6-luna"
+    assert "Omitted means the server-owned gpt-5.6-luna Fast tier" in tool.description
+    assert captured["readiness"] == {"model": "gpt-5.6-luna"}
+    assert "-m gpt-5.6-luna" in captured["job"]["config"]["command"]
 
 
 @pytest.mark.asyncio
 @pytest.mark.parametrize(
     ("model", "message"),
### 0707d9257 #343: одно правило допуска по квоте, прежние квотные системы вырезаны

diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index bc3b920c1..f9878d126 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -739,46 +739,10 @@ async def test_spawn_base_branch_default_empty(monkeypatch):
     with patch.object(m, "_api", side_effect=fake_api):
         await m.spawn_worker(name="w", task="t", repo_path="/s", model="claude-sonnet-5[1m]")
     assert captured["base_branch"] == ""
 
 
-@pytest.mark.asyncio
-@pytest.mark.parametrize("reason,expected", [
-    ("", None),
-    ("pilot #227", "pilot #227"),
-])
-async def test_spawn_sends_model_policy_override_only_when_requested(
-    monkeypatch, reason, expected,
-):
-    import app.mcp_stdio as m
-    monkeypatch.setattr(m, "SCOPE", "/s")
-    monkeypatch.setattr(m, "WORKER_NAME", "orchestrator")
-    captured = {}
-
-    async def fake_api(method, path, **kw):
-        if path == "/api/sessions":
-            captured.update(kw["json"])
-            return {
-                "worktree_path": "/worktrees/w",
-                "branch": "task-227/w",
-                "repo_path": "/s",
-                "git_common_dir": "/s/.git",
-            }
-        return {"ok": True}
-
-    with patch.object(m, "_api", side_effect=fake_api):
-        await m.spawn_worker(
-            name="w", task="t", repo_path="/s", model="claude-opus-5[1m]",
-            model_policy_override_reason=reason,
-        )
-
-    if expected is None:
-        assert "model_policy_override_reason" not in captured
-    else:
-        assert captured["model_policy_override_reason"] == expected
-
-
 @pytest.mark.asyncio
 async def test_t3_spawn_marks_parent_as_initial_task_sender(monkeypatch):
     import app.mcp_stdio as m
     monkeypatch.setattr(m, "SCOPE", "/s")
     monkeypatch.setattr(m, "WORKER_NAME", "parent-orchestrator")
### 3e4d87982 #279: #279: fix acceptance command contract

diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index f9878d126..22d6ede7f 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -499,10 +499,43 @@ async def test_task_create_returns_fields_needed_by_dashboard_card(monkeypatch):
     assert result["assignee"] == "frontend"
     assert result["priority"] == 1
     assert result["task_id"] == 987
 
 
+@pytest.mark.asyncio
+async def test_task_update_distinguishes_omitted_and_explicitly_cleared_command(monkeypatch):
+    import app.mcp_stdio as m
+
+    captured = []
+
+    async def fake_api(method, path, **kwargs):
+        captured.append((method, path, kwargs))
+        return {"updated": ["acceptance_command"]}
+
+    with patch.object(m, "_api", side_effect=fake_api):
+        assert await m.task_update("42") == "Nothing to update"
+        await m.task_update("42", acceptance_command="new-command")
+        await m.task_update("42", acceptance_command="")
+
+    assert captured[0][2]["json"]["acceptance_command"] == "new-command"
+    assert captured[1][2]["json"]["acceptance_command"] == ""
+
+
+@pytest.mark.asyncio
+async def test_task_update_empty_ordinary_fields_do_not_enter_put_body(monkeypatch):
+    import app.mcp_stdio as m
+
+    api = AsyncMock()
+    with patch.object(m, "_api", api):
+        result = await m.task_update(
+            "42", title="", description="", status="", assignee="",
+        )
+
+    assert result == "Nothing to update"
+    api.assert_not_awaited()
+
+
 @pytest.mark.asyncio
 async def test_task_create_omits_project_to_use_callers_scope(monkeypatch):
     import app.mcp_stdio as m
     from pydantic import BaseModel, ValidationError
 
### e2ecc033d #293: #293: freeze ownership lifecycle red tests

diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index 22d6ede7f..14c8c26f2 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -1753,10 +1753,28 @@ async def test_switch_worker_branch_forwards_explicit_force(monkeypatch):
         await m.switch_worker_branch(name="coder", task_id="91", force=True)
 
     assert captured["force"] is True
 
 
+@pytest.mark.asyncio
+async def test_switch_worker_branch_forwards_owned_dirs_json(monkeypatch):
+    import app.mcp_stdio as m
+    monkeypatch.setattr(m, "SCOPE", "/s")
+    captured = {}
+
+    async def fake_api(_method, _path, **kwargs):
+        captured.update(kwargs["json"])
+        return {"ok": True, "branch": "task-91/coder"}
+
+    with patch.object(m, "_api", side_effect=fake_api):
+        await m.switch_worker_branch(
+            name="coder", task_id="91", owned_dirs='["new/path"]',
+        )
+
+    assert captured["owned_dirs"] == ["new/path"]
+
+
 @pytest.mark.asyncio
 @pytest.mark.parametrize("payload", [
     {"ok": False, "error": "target branch is busy"},
     {
         "ok": False,
### 0a9ad8130 #383: #383: expose acceptance command recovery via task update

diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index f9878d126..ff3682da5 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -693,10 +693,71 @@ async def test_task_get_and_update_fall_back_to_authoritative_scope(monkeypatch)
 
     assert calls[0][2]["params"] == {"scope": "/lower"}
     assert calls[1][2]["params"] == {"scope": "/lower"}
 
 
+@pytest.mark.asyncio
+async def test_task_update_sends_orchestrator_acceptance_command_in_caller_scope(monkeypatch):
+    import app.mcp_stdio as m
+
+    monkeypatch.setattr(m, "ROLE", "orchestrator")
+    monkeypatch.setattr(m, "SCOPE", "/lower")
+    api = AsyncMock(return_value={
+        "project": "lower",
+        "par": "383",
+        "updated": ["acceptance_command"],
+    })
+    monkeypatch.setattr(m, "_api", api)
+
+    result = json.loads(await m.task_update(
+        "383", acceptance_command="  uv run pytest -q tests/test_acceptance.py  ",
+    ))
+
+    api.assert_awaited_once_with(
+        "PUT",
+        "/api/tm/tasks/383",
+        json={"acceptance_command": "uv run pytest -q tests/test_acceptance.py"},
+        params={"scope": "/lower"},
+    )
+    assert result["updated"] == ["acceptance_command"]
+    assert "acceptance_command" not in result
+
+
+@pytest.mark.asyncio
+async def test_task_update_empty_acceptance_is_omitted_and_clear_is_explicit(monkeypatch):
+    import app.mcp_stdio as m
+
+    monkeypatch.setattr(m, "ROLE", "orchestrator")
+    monkeypatch.setattr(m, "SCOPE", "/scope")
+    api = AsyncMock(return_value={"updated": ["acceptance_command"]})
+    monkeypatch.setattr(m, "_api", api)
+
+    assert await m.task_update("383", acceptance_command="") == "Nothing to update"
+    api.assert_not_awaited()
+
+    await m.task_update("383", clear_acceptance_command=True)
+    api.assert_awaited_once_with(
+        "PUT",
+        "/api/tm/tasks/383",
+        json={"clear_acceptance_command": True},
+        params={"scope": "/scope"},
+    )
+
+
+@pytest.mark.asyncio
+async def test_worker_task_update_cannot_change_acceptance_command(monkeypatch):
+    import app.mcp_stdio as m
+
+    monkeypatch.setattr(m, "ROLE", "worker")
+    api = AsyncMock()
+    monkeypatch.setattr(m, "_api", api)
+
+    assert await m.task_update("383", acceptance_command="true") == "Nothing to update"
+    assert await m.task_update("383", clear_acceptance_command=True) == "Nothing to update"
+    api.assert_not_awaited()
+
+
 @pytest.mark.asyncio
 async def test_spawn_passes_base_branch(monkeypatch):
     import app.mcp_stdio as m
     monkeypatch.setattr(m, "SCOPE", "/s")
     monkeypatch.setattr(m, "WORKER_NAME", "coder-auth")