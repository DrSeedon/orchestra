import json
import inspect

import httpx
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta, timezone


def _mock_http(monkeypatch, module, handler):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )


async def _protocol_call(module, name, arguments):
    from mcp.types import CallToolRequest, CallToolRequestParams

    handler = module.mcp._mcp_server.request_handlers[CallToolRequest]
    wrapped = await handler(CallToolRequest(
        params=CallToolRequestParams(name=name, arguments=arguments),
    ))
    return wrapped.root


@pytest.mark.asyncio
async def test_t2_publish_artifact_sends_only_path_caption_and_ttl(monkeypatch):
    import app.mcp_stdio as m

    api = AsyncMock(return_value={
        "ok": True,
        "artifact_id": "A" * 22,
        "expires_at": 2_000_000_600,
        "message_id": 77,
    })
    monkeypatch.setattr(m, "_api", api)

    assert hasattr(m, "publish_artifact"), (
        "#294 missing contract: MCP publish_artifact tool is not registered"
    )
    result = await m.publish_artifact("/scope/report.html", "report", 600)

    api.assert_awaited_once()
    args, kwargs = api.await_args
    assert args == ("POST", "/api/artifacts/publish")
    assert kwargs["json"] == {
        "path": "/scope/report.html",
        "caption": "report",
        "ttl_seconds": 600,
    }
    serialized = str(result)
    assert "/scope/report.html" not in serialized
    assert "#" not in serialized


@pytest.mark.asyncio
async def test_t2_publish_failure_never_automatically_uses_document_fallback(monkeypatch):
    import app.mcp_stdio as m

    api = AsyncMock(return_value={
        "error": "artifact link failed; use send_file(path, as_document=True)",
    })
    auto_send = AsyncMock(side_effect=AssertionError("fallback must remain explicit"))
    monkeypatch.setattr(m, "_api", api)
    monkeypatch.setattr(m, "send_file", auto_send)

    assert hasattr(m, "publish_artifact"), (
        "#294 missing contract: MCP publish_artifact tool is not registered"
    )
    with pytest.raises(m.ApiToolError) as caught:
        await m.publish_artifact("/scope/report.html", "report", 600)

    auto_send.assert_not_awaited()
    assert "send_file" in str(caught.value)
    assert "as_document=True" in str(caught.value)
    assert "/scope/report.html" not in str(caught.value)


@pytest.mark.asyncio
async def test_api_429_preserves_typed_fields_and_request_id(monkeypatch):
    import app.mcp_stdio as m

    seen_request_id = ""

    def handler(request):
        nonlocal seen_request_id
        seen_request_id = request.headers["X-Request-ID"]
        return httpx.Response(
            429,
            json={"error": {
                "code": "rate_limited",
                "message": "slow down",
                "details": {"token": "do-not-leak", "limit": 10},
            }},
            headers={"Retry-After": "24", "X-Request-ID": "server-request"},
        )

    _mock_http(monkeypatch, m, handler)

    with pytest.raises(m.ApiToolError) as caught:
        await m._api("GET", "/limited")

    assert seen_request_id
    assert caught.value.envelope() == {
        "code": "rate_limited",
        "message": "slow down",
        "status": 429,
        "retryable": True,
        "request_id": "server-request",
        "retry_after_seconds": 24,
        "outcome_unknown": False,
        "details": {
            "method": "GET",
            "path": "/limited",
            "server": {"token": "[redacted]", "limit": 10},
        },
    }


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "-1", "invalid"])
def test_retry_after_rejects_non_finite_negative_and_invalid_values(value):
    import app.mcp_stdio as m

    assert m._retry_after_seconds(value) is None


@pytest.mark.asyncio
async def test_api_non_json_5xx_preserves_body_and_post_is_not_safe(monkeypatch):
    import app.mcp_stdio as m

    _mock_http(monkeypatch, m, lambda _request: httpx.Response(502, text="bad gateway"))

    with pytest.raises(m.ApiToolError) as caught:
        await m._api("POST", "/mutate", json={"x": 1})

    error = caught.value
    assert error.code == "http_5xx"
    assert error.message == "bad gateway"
    assert error.status == 502
    assert error.retryable is False
    assert error.outcome_unknown is True
    assert error.details["response_body"] == "bad gateway"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("server_fields", "expected_retryable", "expected_unknown"),
    [
        ({"retryable": True}, False, True),
        ({"retryable": True, "outcome_unknown": False}, True, False),
    ],
)
async def test_api_mutation_retry_requires_known_outcome(
    monkeypatch,
    server_fields,
    expected_retryable,
    expected_unknown,
):
    import app.mcp_stdio as m

    _mock_http(
        monkeypatch,
        m,
        lambda _request: httpx.Response(
            503,
            json={"error": {"message": "try later", **server_fields}},
        ),
    )

    with pytest.raises(m.ApiToolError) as caught:
        await m._api("POST", "/mutate", json={"x": 1})

    assert caught.value.retryable is expected_retryable
    assert caught.value.outcome_unknown is expected_unknown


@pytest.mark.asyncio
async def test_api_non_json_2xx_is_invalid_unknown_post_outcome(monkeypatch):
    import app.mcp_stdio as m

    _mock_http(monkeypatch, m, lambda _request: httpx.Response(200, text="accepted maybe"))

    with pytest.raises(m.ApiToolError) as caught:
        await m._api("POST", "/mutate", json={"x": 1})

    assert caught.value.code == "invalid_response"
    assert caught.value.status == 200
    assert caught.value.outcome_unknown is True
    assert caught.value.details["response_body"] == "accepted maybe"


@pytest.mark.asyncio
async def test_api_2xx_top_level_error_is_failure(monkeypatch):
    import app.mcp_stdio as m

    _mock_http(
        monkeypatch,
        m,
        lambda _request: httpx.Response(200, json={"error": "delivery rejected"}),
    )

    with pytest.raises(m.ApiToolError) as caught:
        await m._api("POST", "/send", json={"message": "x"})

    assert caught.value.code == "domain_error"
    assert caught.value.message == "delivery rejected"
    assert caught.value.status == 200
    assert caught.value.outcome_unknown is False


@pytest.mark.asyncio
async def test_api_empty_read_timeout_keeps_type_and_unknown_post_outcome(monkeypatch):
    import app.mcp_stdio as m

    def handler(request):
        raise httpx.ReadTimeout("", request=request)

    _mock_http(monkeypatch, m, handler)

    with pytest.raises(m.ApiToolError) as caught:
        await m._api("POST", "/send", json={"message": "x"})

    assert caught.value.code == "transport_timeout"
    assert caught.value.message == "ReadTimeout"
    assert caught.value.retryable is False
    assert caught.value.outcome_unknown is True
    assert caught.value.request_id


@pytest.mark.asyncio
async def test_api_connect_error_is_safe_to_retry_before_request(monkeypatch):
    import app.mcp_stdio as m

    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    _mock_http(monkeypatch, m, handler)

    with pytest.raises(m.ApiToolError) as caught:
        await m._api("POST", "/send", json={"message": "x"})

    assert caught.value.code == "connect_error"
    assert caught.value.message == "ConnectError: offline"
    assert caught.value.retryable is True
    assert caught.value.outcome_unknown is False


@pytest.mark.asyncio
async def test_api_rejects_unsupported_method_without_http_call():
    import app.mcp_stdio as m

    with pytest.raises(m.ApiToolError) as caught:
        await m._api("PATCH", "/thing")

    assert caught.value.code == "unsupported_method"
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_protocol_failure_is_typed_and_success_uses_same_shape(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "WORKER_NAME", "orch")
    monkeypatch.setattr(m, "SCOPE", "/scope")
    monkeypatch.setattr(m, "_api", AsyncMock(side_effect=m.ApiToolError(
        code="transport_timeout",
        message="ReadTimeout",
        retryable=False,
        request_id="req-1",
        outcome_unknown=True,
        details={"method": "POST"},
    )))

    failed = await _protocol_call(m, "send_message", {"to": "worker", "message": "hi"})

    assert failed.isError is True
    assert failed.structuredContent == {
        "result": None,
        "error": {
            "code": "transport_timeout",
            "message": "ReadTimeout",
            "status": None,
            "retryable": False,
            "request_id": "req-1",
            "retry_after_seconds": None,
            "outcome_unknown": True,
            "details": {"method": "POST"},
        },
    }
    assert "ReadTimeout" in failed.content[0].text

    monkeypatch.setattr(m, "_api", AsyncMock(return_value={"ok": True}))
    succeeded = await _protocol_call(m, "send_message", {"to": "worker", "message": "hi"})
    assert succeeded.isError is False
    assert succeeded.structuredContent == {
        "result": "Message sent to 'worker'",
        "error": None,
    }


@pytest.mark.asyncio
async def test_protocol_unexpected_empty_exception_keeps_class_name(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "_api", AsyncMock(side_effect=RuntimeError()))

    result = await _protocol_call(m, "send_message", {"to": "worker", "message": "hi"})

    assert result.isError is True
    assert result.structuredContent["error"]["code"] == "tool_error"
    assert result.structuredContent["error"]["message"] == "RuntimeError"
    assert result.content[0].text == "tool_error: RuntimeError"


def test_mcp_tool_result_preserves_arbitrary_domain_result():
    import app.mcp_stdio as m

    domain = {"operation_id": "op-1", "operation_state": "UNKNOWN"}
    error = {
        "code": "outcome_unknown",
        "message": "status check required",
        "status": None,
        "retryable": False,
        "request_id": "req-2",
        "retry_after_seconds": None,
        "outcome_unknown": True,
        "details": {},
    }

    success = m.mcp_tool_result(domain, text="partial")
    failure = m.mcp_tool_result(domain, error=error, is_error=True)

    assert success.isError is False
    assert success.structuredContent == {"result": domain, "error": None}
    assert failure.isError is True
    assert failure.structuredContent == {"result": domain, "error": error}

    redacted = m.mcp_tool_result(
        domain,
        error=error,
        is_error=True,
        text="Authorization: Basic dXNlcjpwYXNz",
    )
    assert "dXNlcjpwYXNz" not in redacted.content[0].text


def test_mcp_tool_result_never_marks_unknown_outcome_retryable():
    import app.mcp_stdio as m

    result = m.mcp_tool_result(
        None,
        error={
            "code": "unknown",
            "message": "check status",
            "retryable": True,
            "outcome_unknown": True,
            "details": {},
        },
        is_error=True,
    )

    assert result.structuredContent["error"]["retryable"] is False
    assert result.structuredContent["error"]["outcome_unknown"] is True


@pytest.mark.asyncio
async def test_mcp_boundary_preserves_complete_structured_domain_dict():
    import app.mcp_stdio as m
    from mcp.types import TextContent

    domain = {"result": 4, "operation_id": "op-1"}
    converted = ([TextContent(type="text", text="done")], domain)

    with patch.object(m.FastMCP, "call_tool", AsyncMock(return_value=converted)):
        result = await m.mcp.call_tool("domain_tool", {})

    assert result.structuredContent == {"result": domain, "error": None}


@pytest.mark.asyncio
async def test_mcp_boundary_preserves_singleton_domain_result_dict():
    import app.mcp_stdio as m

    server = m.OrchestraMCP("domain-probe")

    @server.tool()
    async def domain_tool() -> dict:
        return {"result": 4}

    result = await server.call_tool("domain_tool", {})

    assert result.structuredContent == {"result": {"result": 4}, "error": None}


@pytest.mark.asyncio
async def test_mcp_boundary_redacts_manual_error_before_log_and_serialization(caplog):
    import logging
    import app.mcp_stdio as m

    error = m.ApiToolError(
        code="manual_error",
        message="password=correct horse",
        details={"nested": {"api_key": "detail-secret"}},
    )

    with patch.object(m.FastMCP, "call_tool", AsyncMock(side_effect=error)):
        with caplog.at_level(logging.WARNING):
            result = await m.mcp.call_tool("domain_tool", {})

    emitted = json.dumps(result.structuredContent, ensure_ascii=False) + caplog.text
    assert "correct horse" not in emitted
    assert "detail-secret" not in emitted
    assert result.structuredContent["error"]["message"] == "password=[redacted]"
    assert result.structuredContent["error"]["details"] == {
        "nested": {"api_key": "[redacted]"},
    }


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("password=correct horse", "correct horse"),
        ('token="two words", reason=bad', "two words"),
    ],
)
def test_safe_response_text_redacts_complete_credentials(raw, secret):
    import app.mcp_stdio as m

    safe = m._safe_response_text(raw)

    assert secret not in safe
    assert "[redacted]" in safe


@pytest.mark.asyncio
async def test_mcp_boundary_normalizes_pre_shaped_result_to_two_keys():
    import app.mcp_stdio as m
    from mcp.types import CallToolResult, TextContent

    converted = CallToolResult(
        content=[TextContent(type="text", text="partial token=content-secret")],
        structuredContent={
            "result": {"operation_id": "op-1"},
            "error": {
                "code": "partial",
                "message": "token=secret-value",
                "retryable": False,
                "details": {},
            },
            "extra": "drop-me",
        },
        isError=False,
    )

    with patch.object(m.FastMCP, "call_tool", AsyncMock(return_value=converted)):
        result = await m.mcp.call_tool("domain_tool", {})

    assert set(result.structuredContent) == {"result", "error"}
    assert result.structuredContent["result"] == {"operation_id": "op-1"}
    assert result.structuredContent["error"]["message"] == "token=[redacted]"
    assert "content-secret" not in result.content[0].text


@pytest.mark.asyncio
async def test_task_create_returns_fields_needed_by_dashboard_card(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/scope")

    async def fake_api(method, path, **kwargs):
        assert method == "POST"
        assert path == "/api/tm/tasks"
        assert kwargs["json"]["description"] == "Long task description"
        return {
            "par": "113",
            "id": 987,
            "title": "Task card",
            "project": "orchestra",
            "price_rub": 0,
            "status": "new",
        }

    with patch.object(m, "_api", side_effect=fake_api):
        raw = await m.task_create(
            title="Task card",
            project="orchestra",
            description="Long task description",
            assignee="frontend",
            priority=1,
        )

    result = json.loads(raw)
    assert result["description"] == "Long task description"
    assert result["assignee"] == "frontend"
    assert result["priority"] == 1
    assert result["task_id"] == 987


@pytest.mark.asyncio
async def test_task_create_omits_project_to_use_callers_scope(monkeypatch):
    import app.mcp_stdio as m
    from pydantic import BaseModel, ValidationError

    monkeypatch.setattr(m, "SCOPE", "/scope")
    captured = {}

    async def fake_api(method, path, **kwargs):
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


async def _call_tm_task_create(method, path, **kwargs):
    from app import tm

    assert method == "POST"
    assert path == "/api/tm/tasks"
    body = kwargs["json"]
    return tm.api_create_task(
        body.get("project", ""),
        body["title"],
        price=body["price"],
        description=body["description"],
        assignee=body["assignee"],
        status=body["status"],
        scope=body["scope"],
        priority=body["priority"],
        acceptance_command=body["acceptance_command"],
    )


def _register_session_scope(scope: str) -> None:
    from app.db import _conn, init_db

    init_db()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO sessions (id, name, scope, cwd, model, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "session-scope-authority",
                "scope-authority",
                scope,
                scope,
                "claude-sonnet-5[1m]",
                "idle",
                datetime.now(timezone.utc).isoformat(),
            ),
        )


@pytest.mark.asyncio
async def test_task_create_admits_exact_session_scope_when_tm_project_is_stale(monkeypatch):
    import app.mcp_stdio as m
    from app import tm

    scope = "/home/kesha/projects/VPN-Service"
    _register_session_scope(scope)
    monkeypatch.setattr(m, "SCOPE", scope)

    with tm._conn() as conn:
        assert conn.execute(
            "SELECT 1 FROM tm_projects WHERE scope = ?", (scope,)
        ).fetchone() is None

    with patch.object(m, "_api", side_effect=_call_tm_task_create):
        raw = await m.task_create(title="VPN registration oracle")

    result = json.loads(raw)
    assert result["title"] == "VPN registration oracle"
    with tm._conn() as conn:
        stored_scope = conn.execute(
            """SELECT p.scope
               FROM tm_tasks AS t
               JOIN tm_projects AS p ON p.id = t.project_id
               WHERE t.id = ?""",
            (result["task_id"],),
        ).fetchone()[0]
    assert stored_scope == scope


@pytest.mark.asyncio
async def test_task_create_rejects_scope_absent_from_session_and_projects(monkeypatch):
    import app.mcp_stdio as m
    from app import tm

    scope = "/home/kesha/projects/does-not-exist"
    from app.db import init_db
    init_db()
    monkeypatch.setattr(m, "SCOPE", scope)

    with patch.object(m, "_api", side_effect=_call_tm_task_create):
        with pytest.raises(ValueError, match="project '.*/does-not-exist' is not registered"):
            await m.task_create(title="must be rejected")

    with tm._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tm_projects").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM tm_tasks").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_task_create_keeps_caller_scope_and_registered_project_authorization(monkeypatch):
    import app.mcp_stdio as m
    from app import tm
    from app.db import init_db

    init_db()
    now = tm._now()
    with tm._conn() as conn:
        for project_id, scope, prefix in (
            ("lower", "/lower", "LOW"),
            ("upper", "/upper", "UPR"),
        ):
            conn.execute(
                """INSERT INTO tm_projects
                   (id, name, prefix, scope, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (project_id, project_id, prefix, scope, now),
            )

    monkeypatch.setattr(m, "SCOPE", "/lower")
    with patch.object(m, "_api", side_effect=_call_tm_task_create):
        await m.task_create(title="caller-scoped task")
        await m.task_create(title="explicit registered task", project="/upper")

    with tm._conn() as conn:
        rows = conn.execute(
            """SELECT t.title, p.scope
               FROM tm_tasks AS t
               JOIN tm_projects AS p ON p.id = t.project_id
               ORDER BY t.id"""
        ).fetchall()
    assert [(row["title"], row["scope"]) for row in rows] == [
        ("caller-scoped task", "/lower"),
        ("explicit registered task", "/upper"),
    ]


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


@pytest.mark.asyncio
async def test_task_get_and_update_fall_back_to_authoritative_scope(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/lower")
    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"project": "seedon", "par": "1", "updated": ["status"]}

    with patch.object(m, "_api", side_effect=fake_api):
        await m.task_get("1")
        await m.task_update("1", status="done")

    assert calls[0][2]["params"] == {"scope": "/lower"}
    assert calls[1][2]["params"] == {"scope": "/lower"}


@pytest.mark.asyncio
async def test_spawn_passes_base_branch(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "coder-auth")
    captured = {}
    async def fake_api(method, path, **kw):
        if path == "/api/sessions":
            captured.update(kw.get("json", {}))
            return {
                "worktree_path": "/worktrees/w-step1",
                "branch": "task-1/w-step1",
                "repo_path": "/s",
                "git_common_dir": "/s/.git",
            }
        return {"ok": True}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.spawn_worker(name="w-step1", task="do it", repo_path="/s",
                             model="claude-sonnet-5[1m]", base_branch="feature/auth")
    assert captured["base_branch"] == "feature/auth"
    assert captured["use_worktree"] is True


@pytest.mark.asyncio
async def test_spawn_base_branch_default_empty(monkeypatch):
    # Sentinel "" = авто-резолв базовой ветки по стратегии пайплайна (DESIGN §10):
    # parent → от ветки родителя, иначе main. Явная ветка переопределяет стратегию.
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "x")
    captured = {}
    async def fake_api(method, path, **kw):
        if path == "/api/sessions":
            captured.update(kw.get("json", {}))
            return {
                "worktree_path": "/worktrees/w",
                "branch": "task-1/w",
                "repo_path": "/s",
                "git_common_dir": "/s/.git",
            }
        return {"ok": True}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.spawn_worker(name="w", task="t", repo_path="/s", model="claude-sonnet-5[1m]")
    assert captured["base_branch"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,expected", [
    ("", None),
    ("pilot #227", "pilot #227"),
])
async def test_spawn_sends_model_policy_override_only_when_requested(
    monkeypatch, reason, expected,
):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orchestrator")
    captured = {}

    async def fake_api(method, path, **kw):
        if path == "/api/sessions":
            captured.update(kw["json"])
            return {
                "worktree_path": "/worktrees/w",
                "branch": "task-227/w",
                "repo_path": "/s",
                "git_common_dir": "/s/.git",
            }
        return {"ok": True}

    with patch.object(m, "_api", side_effect=fake_api):
        await m.spawn_worker(
            name="w", task="t", repo_path="/s", model="claude-opus-5[1m]",
            model_policy_override_reason=reason,
        )

    if expected is None:
        assert "model_policy_override_reason" not in captured
    else:
        assert captured["model_policy_override_reason"] == expected


@pytest.mark.asyncio
async def test_t3_spawn_marks_parent_as_initial_task_sender(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "parent-orchestrator")
    calls = []

    async def fake_api(method, path, **kw):
        calls.append((method, path, kw.get("json")))
        if path == "/api/sessions":
            return {
                "worktree_path": "/worktrees/child",
                "branch": "task-1/child",
                "repo_path": "/s",
                "git_common_dir": "/s/.git",
            }
        return {"ok": True}

    with patch.object(m, "_api", side_effect=fake_api):
        await m.spawn_worker(
            name="child",
            task="do it",
            repo_path="/s",
            model="claude-opus-5[1m]",
        )

    delivery_calls = [
        call for call in calls
        if call[1] == "/api/sessions/child/initial-deliveries"
    ]
    assert len(delivery_calls) == 1, (
        "#311 missing behavior: spawn still uses synchronous /send"
    )
    send_call = delivery_calls[0]
    assert send_call[2]["sender"] == "parent-orchestrator"


@pytest.mark.asyncio
async def test_spawn_reports_exact_repo_mapping_when_scope_differs(monkeypatch, tmp_path):
    import app.mcp_stdio as m

    repo = tmp_path / "new-project"
    monkeypatch.setattr(m, "SCOPE", "/logical/orchestrator-project")
    monkeypatch.setattr(m, "WORKER_NAME", "parent-orchestrator")
    calls = []

    async def fake_api(method, path, **kw):
        calls.append((method, path, kw.get("json")))
        if path == "/api/sessions":
            return {
                "worktree_path": "/actual/worktrees/child",
                "branch": "task-88/child",
                "repo_path": "/server/canonical/new-project",
                "git_common_dir": "/server/git/new-project",
            }
        return {"ok": True}

    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.spawn_worker(
            name="child", task="do it", repo_path=str(repo),
            model="gpt-5.6-sol", task_id="88",
        )

    create_body = calls[0][2]
    assert create_body["scope"] == "/logical/orchestrator-project"
    assert create_body["cwd"] == str(repo)
    assert create_body["repo_path"] == str(repo)
    assert "Worktree: /actual/worktrees/child" in out
    assert "Repository: /server/canonical/new-project" in out
    assert "Git common dir: /server/git/new-project" in out
    assert "Branch: task-88/child" in out


@pytest.mark.asyncio
async def test_spawn_api_error_does_not_send_initial_task(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/s")
    calls = []

    async def fake_api(method, path, **kw):
        calls.append(path)
        return {"error": "repo_path must be the Git repository root"}

    with patch.object(m, "_api", side_effect=fake_api):
        with pytest.raises(m.ApiToolError) as caught:
            await m.spawn_worker(
                name="child", task="do it", repo_path="/repo/nested",
                model="gpt-5.6-sol",
            )

    assert calls == ["/api/sessions"]
    assert caught.value.message == "Spawn failed: repo_path must be the Git repository root"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response, missing",
    [
        ({
            "branch": "task-88/child",
            "repo_path": "/repo",
            "git_common_dir": "/repo/.git",
        }, "worktree_path"),
        ({
            "worktree_path": "/actual/worktrees/child",
            "repo_path": "/repo",
            "git_common_dir": "/repo/.git",
        }, "branch"),
        ({
            "worktree_path": "/actual/worktrees/child",
            "branch": "task-88/child",
            "git_common_dir": "/repo/.git",
        }, "repo_path"),
        ({
            "worktree_path": "/actual/worktrees/child",
            "branch": "task-88/child",
            "repo_path": "/repo",
        }, "git_common_dir"),
        ({
            "worktree_path": 123,
            "branch": "task-88/child",
            "repo_path": "/repo",
            "git_common_dir": "/repo/.git",
        }, "worktree_path"),
        ({
            "worktree_path": "/actual/worktrees/child",
            "branch": [],
            "repo_path": "/repo",
            "git_common_dir": "/repo/.git",
        }, "branch"),
        ({
            "worktree_path": "/actual/worktrees/child",
            "branch": "task-88/child",
            "repo_path": " ",
            "git_common_dir": "/repo/.git",
        }, "repo_path"),
    ],
)
async def test_spawn_malformed_success_fails_loud_without_task(
    monkeypatch, response, missing,
):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/s")
    calls = []

    async def fake_api(method, path, **kw):
        calls.append(path)
        return response

    with patch.object(m, "_api", side_effect=fake_api):
        with pytest.raises(m.ApiToolError) as caught:
            await m.spawn_worker(
                name="child", task="do it", repo_path="/repo",
                model="gpt-5.6-sol",
            )

    assert calls == ["/api/sessions"]
    assert caught.value.code == "invalid_response"
    assert caught.value.outcome_unknown is True
    assert missing in caught.value.details["missing"]
    assert caught.value.result["created"] == "unknown"


@pytest.mark.asyncio
async def test_t3_spawn_task_delivery_error_reports_created_worker(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/s")
    calls = []

    async def fake_api(method, path, **kw):
        calls.append(path)
        if path == "/api/sessions":
            return {
                "worktree_path": "/worktrees/child",
                "branch": "task-88/child",
                "repo_path": "/repo",
                "git_common_dir": "/repo/.git",
            }
        raise m.ApiToolError(
            code="DELIVERY_ACCEPT_REJECTED",
            message="delivery transaction rolled back before commit",
            status=503,
            retryable=True,
            outcome_unknown=False,
            details={"commit_state": "NOT_COMMITTED"},
        )

    with patch.object(m, "_api", side_effect=fake_api):
        with pytest.raises(m.ApiToolError) as caught:
            await m.spawn_worker(
                name="child", task="do it", repo_path="/repo",
                model="gpt-5.6-sol",
            )

    assert calls == [
        "/api/sessions",
        "/api/sessions/child/initial-deliveries",
    ]
    assert "worker 'child' was created" in caught.value.message.lower()
    assert caught.value.outcome_unknown is False
    assert caught.value.result["worktree_path"] == "/worktrees/child"
    delivery_id = caught.value.result["delivery_id"]
    assert delivery_id
    assert caught.value.result["next_action"] == {
        "code": "RETRY_SAME_DELIVERY",
        "tool": "retry_initial_delivery",
        "arguments": {
            "name": "child",
            "task": "do it",
            "delivery_id": delivery_id,
        },
        "message": "Retry only this delivery id; do not create a new logical task.",
    }


@pytest.mark.asyncio
async def test_t3_spawn_unknown_delivery_preserves_mapping_and_forbids_resend(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/s")

    async def fake_api(_method, path, **_kwargs):
        if path == "/api/sessions":
            return {
                "worktree_path": "/worktrees/child",
                "branch": "task-88/child",
                "repo_path": "/repo",
                "git_common_dir": "/repo/.git",
            }
        raise m.ApiToolError(
            code="transport_timeout",
            message="ReadTimeout",
            retryable=False,
            request_id="send-request",
            outcome_unknown=True,
        )

    monkeypatch.setattr(m, "_api", fake_api)
    result = await _protocol_call(m, "spawn_worker", {
        "name": "child",
        "task": "do it",
        "repo_path": "/repo",
        "model": "gpt-5.6-sol",
    })

    assert result.isError is True
    structured = result.structuredContent
    assert structured["error"]["outcome_unknown"] is True
    assert structured["result"]["created"] is True
    assert structured["result"]["worktree_path"] == "/worktrees/child"
    assert "delivery_id" in structured["result"], (
        "#311 missing behavior: timeout result has no durable delivery id"
    )
    assert structured["result"]["delivery_id"]
    assert structured["result"]["next_action"]["code"] == "CHECK_DELIVERY_STATUS"
    assert structured["result"]["next_action"]["tool"] == "delivery_status"
    assert structured["result"]["next_action"]["arguments"] == {
        "delivery_id": structured["result"]["delivery_id"],
    }
    assert "do not resend" in structured["result"]["next_action"]["message"].lower()


@pytest.mark.asyncio
async def test_t3_spawn_delivery_posts_caller_key_and_returns_accepted_receipt(
    monkeypatch,
):
    import app.mcp_stdio as m

    delivery_id = "00000000-0000-4000-8000-000000000311"
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "parent-orchestrator")
    assert "delivery_id" in inspect.signature(m.spawn_worker).parameters, (
        "#311 missing behavior: spawn_worker has no caller delivery_id"
    )
    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/api/sessions":
            return {
                "worktree_path": "/worktrees/child",
                "branch": "task-311/child",
                "repo_path": "/repo",
                "git_common_dir": "/repo/.git",
            }
        assert path == "/api/sessions/child/initial-deliveries"
        body = kwargs["json"]
        assert body == {
            "delivery_id": delivery_id,
            "message": "do it",
            "scope": "/s",
            "sender": "parent-orchestrator",
        }
        return {
            "ok": True,
            "delivery_id": delivery_id,
            "delivery_state": "QUEUED",
            "payload_hash": "hash-311",
            "status_url": f"/api/initial-deliveries/{delivery_id}",
        }

    monkeypatch.setattr(m, "_api", fake_api)

    result = await m.spawn_worker(
        name="child",
        task="do it",
        repo_path="/repo",
        model="gpt-5.6-sol",
        delivery_id=delivery_id,
    )

    assert [(method, path) for method, path, _ in calls] == [
        ("POST", "/api/sessions"),
        ("POST", "/api/sessions/child/initial-deliveries"),
    ]
    assert delivery_id in result
    assert "accepted" in result.lower()
    assert "task sent" not in result.lower()


@pytest.mark.asyncio
async def test_t3_spawn_delivery_timeout_reconciles_without_second_post(monkeypatch):
    import app.mcp_stdio as m

    delivery_id = "00000000-0000-4000-8000-000000000312"
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "parent-orchestrator")
    assert "delivery_id" in inspect.signature(m.spawn_worker).parameters, (
        "#311 missing behavior: spawn_worker has no caller delivery_id"
    )
    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/api/sessions":
            return {
                "worktree_path": "/worktrees/child",
                "branch": "task-311/child",
                "repo_path": "/repo",
                "git_common_dir": "/repo/.git",
            }
        if method == "POST":
            raise m.ApiToolError(
                code="transport_timeout",
                message="response lost after durable acceptance",
                outcome_unknown=True,
            )
        assert method == "GET"
        assert path == f"/api/initial-deliveries/{delivery_id}"
        assert kwargs["params"] == {"scope": "/s"}
        return {
            "ok": True,
            "delivery_id": delivery_id,
            "delivery_state": "SUBMITTED",
            "payload_hash": "hash-312",
            "status_url": path,
            "provider_ref": "turn-312",
        }

    monkeypatch.setattr(m, "_api", fake_api)

    result = await m.spawn_worker(
        name="child",
        task="do it",
        repo_path="/repo",
        model="gpt-5.6-sol",
        delivery_id=delivery_id,
    )

    delivery_posts = [
        call for call in calls
        if call[0] == "POST" and "initial-deliveries" in call[1]
    ]
    assert len(delivery_posts) == 1
    assert ("GET", f"/api/initial-deliveries/{delivery_id}") in [
        (method, path) for method, path, _ in calls
    ]
    assert delivery_id in result
    assert "submitted" in result.lower()


@pytest.mark.asyncio
async def test_t3_spawn_delivery_unresolved_timeout_has_actionable_no_resend(
    monkeypatch,
):
    import app.mcp_stdio as m

    delivery_id = "00000000-0000-4000-8000-000000000313"
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "parent-orchestrator")
    assert "delivery_id" in inspect.signature(m.spawn_worker).parameters, (
        "#311 missing behavior: spawn_worker has no caller delivery_id"
    )

    async def fake_api(method, path, **_kwargs):
        if path == "/api/sessions":
            return {
                "worktree_path": "/worktrees/child",
                "branch": "task-311/child",
                "repo_path": "/repo",
                "git_common_dir": "/repo/.git",
            }
        raise m.ApiToolError(
            code="transport_timeout" if method == "POST" else "delivery_status_unavailable",
            message="outcome remains unknown",
            outcome_unknown=True,
        )

    monkeypatch.setattr(m, "_api", fake_api)

    result = await _protocol_call(m, "spawn_worker", {
        "name": "child",
        "task": "do it",
        "repo_path": "/repo",
        "model": "gpt-5.6-sol",
        "delivery_id": delivery_id,
    })

    assert result.isError is True
    structured = result.structuredContent
    assert structured["error"]["outcome_unknown"] is True
    assert structured["result"]["delivery_id"] == delivery_id
    assert structured["result"]["next_action"] == {
        "code": "CHECK_DELIVERY_STATUS",
        "tool": "delivery_status",
        "arguments": {"delivery_id": delivery_id},
        "message": (
            "Check this delivery id; do not resend the task with a new id."
        ),
    }


@pytest.mark.asyncio
async def test_t3_spawn_committed_then_500_unresolved_never_posts_again(
    monkeypatch,
):
    import app.mcp_stdio as m

    delivery_id = "00000000-0000-4000-8000-000000000315"
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "parent-orchestrator")
    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/api/sessions":
            return {
                "worktree_path": "/worktrees/child",
                "branch": "task-311/child",
                "repo_path": "/repo",
                "git_common_dir": "/repo/.git",
            }
        if method == "POST":
            raise m.ApiToolError(
                code="http_5xx",
                message="500 returned after the server committed acceptance",
                status=500,
                retryable=False,
                outcome_unknown=True,
            )
        raise m.ApiToolError(
            code="delivery_status_unavailable",
            message="status response also unavailable",
            status=503,
            retryable=True,
            outcome_unknown=False,
        )

    monkeypatch.setattr(m, "_api", fake_api)
    result = await _protocol_call(m, "spawn_worker", {
        "name": "child",
        "task": "do it",
        "repo_path": "/repo",
        "model": "gpt-5.6-sol",
        "delivery_id": delivery_id,
    })

    assert [call[0:2] for call in calls] == [
        ("POST", "/api/sessions"),
        ("POST", "/api/sessions/child/initial-deliveries"),
        ("GET", f"/api/initial-deliveries/{delivery_id}"),
    ]
    assert result.isError is True
    assert result.structuredContent["error"]["outcome_unknown"] is True
    assert result.structuredContent["result"]["next_action"] == {
        "code": "CHECK_DELIVERY_STATUS",
        "tool": "delivery_status",
        "arguments": {"delivery_id": delivery_id},
        "message": "Check this delivery id; do not resend the task with a new id.",
    }


@pytest.mark.asyncio
async def test_t3_spawn_idempotency_conflict_is_actionable_and_never_retries(
    monkeypatch,
):
    import app.mcp_stdio as m

    delivery_id = "00000000-0000-4000-8000-000000000316"
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "parent-orchestrator")
    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/api/sessions":
            return {
                "worktree_path": "/worktrees/child",
                "branch": "task-311/child",
                "repo_path": "/repo",
                "git_common_dir": "/repo/.git",
            }
        raise m.ApiToolError(
            code="IDEMPOTENCY_CONFLICT",
            message="delivery id is already bound to another payload",
            status=409,
            retryable=False,
            outcome_unknown=False,
        )

    monkeypatch.setattr(m, "_api", fake_api)
    result = await _protocol_call(m, "spawn_worker", {
        "name": "child",
        "task": "changed task",
        "repo_path": "/repo",
        "model": "gpt-5.6-sol",
        "delivery_id": delivery_id,
    })

    assert [call[0:2] for call in calls] == [
        ("POST", "/api/sessions"),
        ("POST", "/api/sessions/child/initial-deliveries"),
    ]
    assert result.isError is True
    assert result.structuredContent["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert result.structuredContent["result"]["next_action"] == {
        "code": "RESOLVE_IDEMPOTENCY_CONFLICT",
        "tool": "delivery_status",
        "arguments": {"delivery_id": delivery_id},
        "message": (
            "This delivery id belongs to another payload; inspect it and do not retry "
            "the changed task."
        ),
    }


@pytest.mark.asyncio
async def test_t3_delivery_status_and_known_precommit_retry_keep_the_same_key(
    monkeypatch,
):
    import app.mcp_stdio as m

    delivery_id = "00000000-0000-4000-8000-000000000314"
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "parent-orchestrator")
    assert hasattr(m, "delivery_status"), (
        "#311 missing behavior: delivery_status MCP tool is not registered"
    )
    assert hasattr(m, "retry_initial_delivery"), (
        "#311 missing behavior: retry_initial_delivery MCP tool is not registered"
    )
    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {
            "ok": True,
            "delivery_id": delivery_id,
            "delivery_state": "QUEUED",
            "payload_hash": "hash-314",
            "status_url": f"/api/initial-deliveries/{delivery_id}",
            "next_action": {
                "code": "WAIT_FOR_DELIVERY",
                "tool": "delivery_status",
                "arguments": {"delivery_id": delivery_id},
            },
        }

    monkeypatch.setattr(m, "_api", fake_api)

    retried = await _protocol_call(m, "retry_initial_delivery", {
        "name": "child",
        "task": "do it",
        "delivery_id": delivery_id,
    })
    looked_up = await _protocol_call(m, "delivery_status", {
        "delivery_id": delivery_id,
    })

    assert calls[0][0:2] == (
        "POST", "/api/sessions/child/initial-deliveries",
    )
    assert calls[0][2]["json"] == {
        "delivery_id": delivery_id,
        "message": "do it",
        "scope": "/s",
        "sender": "parent-orchestrator",
    }
    assert calls[1][0:2] == (
        "GET", f"/api/initial-deliveries/{delivery_id}",
    )
    assert calls[1][2]["params"] == {"scope": "/s"}
    assert retried.isError is False
    assert looked_up.isError is False
    assert retried.structuredContent["result"]["delivery_id"] == delivery_id
    assert looked_up.structuredContent["result"]["next_action"]["code"] == (
        "WAIT_FOR_DELIVERY"
    )


@pytest.mark.asyncio
async def test_acquire_test_lock_uses_worker_as_holder(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "coder-auth")
    captured = {}
    async def fake_api(method, path, **kw):
        captured["path"] = path
        captured["json"] = kw.get("json")
        return {"acquired": True, "holder": None}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.acquire_test_lock(reason="full suite before merge")
    assert captured["path"] == "/api/test-lock/acquire"
    assert captured["json"]["holder"] == "coder-auth"
    assert captured["json"]["scope"] == "/s"
    assert captured["json"]["reason"] == "full suite before merge"
    assert "acquired" in out.lower() or "взял" in out.lower()


@pytest.mark.asyncio
async def test_acquire_test_lock_reports_holder_when_busy(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "coder-b")
    async def fake_api(method, path, **kw):
        return {"acquired": False, "holder": "coder-a"}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.acquire_test_lock(reason="x")
    assert "coder-a" in out  # держатель указан в отказе


@pytest.mark.asyncio
async def test_release_and_status(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "coder-a")
    calls = {}
    async def fake_api(method, path, **kw):
        calls[path] = kw.get("json") or kw.get("params")
        if path == "/api/test-lock/release":
            return {"released": True}
        if path == "/api/test-lock":
            return {"held": True, "holder": "coder-a", "reason": "r", "acquired_at": "t"}
        return {}
    with patch.object(m, "_api", side_effect=fake_api):
        rel = await m.release_test_lock()
        st = await m.test_lock_status()
    assert "/api/test-lock/release" in calls
    assert "coder-a" in st  # статус упоминает держателя
    assert "released" in rel.lower() or "освобод" in rel.lower()

@pytest.mark.asyncio
async def test_merge_worker_with_next_task_id(monkeypatch):
    """MCP creates the idempotency key before the operation POST."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch")
    captured = {}
    async def fake_api(method, path, **kw):
        captured["path"] = path
        captured["json"] = kw.get("json", {})
        operation_id = captured["json"]["operation_id"]
        return {"result": {
            "schema_version": 1,
            "operation_id": operation_id,
            "operation_state": "SUCCEEDED",
            "retryable": False,
            "commit_point": "REACHED",
            "git": {"status": "SUCCEEDED", "worker_branch": "task-42/w", "commits_merged": 1},
            "error": None,
            "next_action": {"code": "NONE", "message": "done"},
        }, "error": None}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.merge_worker(name="coder", target="main", next_task_id="task-43")
    assert captured["path"] == "/api/merge-operations"
    assert captured["json"]["name"] == "coder"
    assert captured["json"]["scope"] == "/s"
    assert captured["json"]["operation_id"]
    assert captured["json"]["next_task_id"] == "task-43"
    assert captured["json"]["target"] == "main"
    assert out.isError is False
    assert out.structuredContent["result"]["operation_state"] == "SUCCEEDED"


@pytest.mark.asyncio
async def test_merge_worker_no_next_task_id(monkeypatch):
    """Caller may pin one operation id across retries."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch")
    # Заглушка НИКОГДА не отдаёт терминальное состояние, а тул теперь дожидается его —
    # без укороченного потолка тест досиживал бы до таймаута pytest.
    monkeypatch.setattr(m, "_MERGE_WAIT_SECONDS", 0.01)
    captured = {}
    async def fake_api(method, path, **kw):
        if method == "POST":
            captured["json"] = kw.get("json", {})
        return {"result": {
            "schema_version": 1,
            "operation_id": "00000000-0000-0000-0000-000000000001",
            "operation_state": "RUNNING",
            "retryable": True,
            "commit_point": "NOT_REACHED",
            "git": {"status": "NOT_STARTED"},
            "error": None,
            "next_action": {"code": "CHECK_SAME_OPERATION", "message": "do not merge manually"},
        }, "error": None}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.merge_worker(
            name="coder", operation_id="00000000-0000-0000-0000-000000000001",
        )
    assert captured["json"]["operation_id"] == "00000000-0000-0000-0000-000000000001"
    assert captured["json"]["next_task_id"] == ""
    assert captured["json"]["target"] == ""
    assert out.isError is False
    # Интент — ответ предостерегает от ручного мержа. Регистр не проверяем: текст
    # переписан так, чтобы «ещё идёт» нельзя было прочитать как отказ.
    assert "not merge manually" in out.content[0].text.lower()


@pytest.mark.asyncio
async def test_merge_worker_partial_keeps_domain_result_without_protocol_error(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/s")
    async def fake_api(*_args, **_kwargs):
        return {"result": {
            "schema_version": 1,
            "operation_id": "00000000-0000-0000-0000-000000000002",
            "operation_state": "PARTIAL",
            "retryable": True,
            "commit_point": "REACHED",
            "git": {"status": "SUCCEEDED", "target_after": "c" * 40},
            "rag": {"status": "NOT_READY"},
            "error": {
                "code": "RAG_NOT_READY", "message": "RAG backfill was not accepted",
                "status": None, "retryable": True, "request_id": "op-2",
                "retry_after_seconds": None, "outcome_unknown": False, "details": {},
            },
            "next_action": {"code": "FINALIZE_SAME_OPERATION", "message": "do not merge manually"},
        }, "error": None}

    with patch.object(m, "_api", side_effect=fake_api):
        output = await m.merge_worker(name="worker", target="main")

    assert output.isError is False
    assert output.structuredContent["error"] is None
    assert output.structuredContent["result"]["error"]["code"] == "RAG_NOT_READY"
    assert "PARTIAL" in output.content[0].text


@pytest.mark.asyncio
async def test_merge_worker_empty_timeout_returns_unknown_with_operation_id(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/s")
    operation_id = "00000000-0000-0000-0000-000000000003"

    async def fake_api(method, *_args, **_kwargs):
        if method == "POST":
            raise m.ApiToolError(
                code="transport_timeout", message="ReadTimeout",
                request_id="transport-request", outcome_unknown=True,
                details={"exception_type": "ReadTimeout"},
            )
        raise m.ApiToolError(
            code="connect_error", message="ConnectError",
            request_id="status-request", retryable=True,
            details={"exception_type": "ConnectError"},
        )

    with patch.object(m, "_api", side_effect=fake_api):
        output = await m.merge_worker(
            name="worker", target="main", operation_id=operation_id,
        )

    assert output.isError is True
    assert output.structuredContent["result"]["operation_id"] == operation_id
    assert output.structuredContent["result"]["operation_state"] == "UNKNOWN"
    assert output.structuredContent["error"]["message"]
    assert output.structuredContent["error"]["outcome_unknown"] is True
    assert output.content[0].text.strip()


@pytest.mark.asyncio
async def test_merge_worker_empty_connect_error_is_typed_and_nonempty(monkeypatch):
    import app.mcp_stdio as m

    operation_id = "00000000-0000-0000-0000-000000000010"

    async def fake_api(*_args, **_kwargs):
        raise m.ApiToolError(
            code="connect_error", message="ConnectError", retryable=True,
            details={"exception_type": "ConnectError"},
        )

    monkeypatch.setattr(m, "_api", fake_api)
    output = await m.merge_worker(name="worker", operation_id=operation_id)

    assert output.isError is True
    assert output.structuredContent["result"]["operation_state"] == "FAILED"
    assert output.structuredContent["error"]["message"]
    assert output.structuredContent["error"]["details"]["exception_type"] == "ConnectError"
    assert output.structuredContent["error"]["request_id"] == operation_id
    assert output.content[0].text.strip()


@pytest.mark.asyncio
async def test_merge_worker_invalid_json_outcome_is_typed_and_nonempty(monkeypatch):
    import app.mcp_stdio as m

    operation_id = "00000000-0000-0000-0000-000000000011"

    async def fake_api(method, *_args, **_kwargs):
        if method == "POST":
            raise m.ApiToolError(
                code="invalid_response", message="JSONDecodeError",
                outcome_unknown=True,
                details={"exception_type": "JSONDecodeError"},
            )
        raise m.ApiToolError(
            code="connect_error", message="ConnectError", retryable=True,
            details={"exception_type": "ConnectError"},
        )

    monkeypatch.setattr(m, "_api", fake_api)
    output = await m.merge_worker(name="worker", operation_id=operation_id)

    assert output.isError is True
    assert output.structuredContent["result"]["operation_state"] == "UNKNOWN"
    assert output.structuredContent["error"]["message"]
    assert output.structuredContent["error"]["details"]["exception_type"] == "JSONDecodeError"
    assert output.structuredContent["error"]["request_id"] == operation_id


@pytest.mark.asyncio
async def test_merge_worker_old_server_fails_closed_without_legacy_post(monkeypatch):
    import app.mcp_stdio as m

    paths = []
    async def fake_api(method, path, **_kwargs):
        paths.append((method, path))
        raise m.ApiToolError(code="http_4xx", message="HTTP 404", status=404)

    with patch.object(m, "_api", side_effect=fake_api):
        output = await m.merge_worker(name="worker")

    assert paths == [("POST", "/api/merge-operations")]
    assert output.isError is True
    assert output.structuredContent["error"]["code"] == "MERGE_API_UPGRADE_REQUIRED"
    assert output.structuredContent["error"]["message"]
    assert "/api/sessions/worker/merge" not in [path for _, path in paths]


@pytest.mark.asyncio
async def test_merge_worker_unknown_dto_keeps_nonempty_detail(monkeypatch):
    import app.mcp_stdio as m

    operation_id = "00000000-0000-0000-0000-000000000004"
    monkeypatch.setattr(m, "_api", AsyncMock(return_value={"unexpected": True}))

    output = await m.merge_worker(name="worker", operation_id=operation_id)

    assert output.isError is True
    assert output.structuredContent["result"]["operation_id"] == operation_id
    assert output.structuredContent["error"]["message"]
    assert output.structuredContent["error"]["details"]["exception_type"] == "ValueError"


@pytest.mark.asyncio
async def test_merge_worker_formatter_exception_is_caught_with_operation_id(monkeypatch):
    import app.mcp_stdio as m

    operation_id = "00000000-0000-0000-0000-000000000007"
    domain = {
        "schema_version": 1,
        "operation_id": operation_id,
        "operation_state": "SUCCEEDED",
        "retryable": False,
        "commit_point": "REACHED",
        "git": {"status": "SUCCEEDED", "worker_branch": "worker", "commits_merged": 1},
        "error": None,
        "next_action": {"code": "NONE", "message": "done"},
    }
    monkeypatch.setattr(m, "_api", AsyncMock(return_value={"result": domain, "error": None}))
    real_formatter = m._merge_tool_result
    calls = 0

    def flaky_formatter(result):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError()
        return real_formatter(result)

    monkeypatch.setattr(m, "_merge_tool_result", flaky_formatter)
    output = await m.merge_worker(name="worker", operation_id=operation_id)

    assert output.isError is True
    assert output.structuredContent["result"]["operation_id"] == operation_id
    assert output.structuredContent["error"]["message"]
    assert output.structuredContent["error"]["details"]["exception_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_merge_worker_empty_http_500_never_returns_empty_error(monkeypatch):
    import app.mcp_stdio as m

    operation_id = "00000000-0000-0000-0000-000000000008"

    async def fake_api(method, *_args, **_kwargs):
        if method == "POST":
            raise m.ApiToolError(
                code="http_5xx", message="", status=500,
                request_id="server-request", outcome_unknown=True,
                details={"exception_type": "HTTPStatusError"},
            )
        raise m.ApiToolError(code="connect_error", message="", retryable=True)

    monkeypatch.setattr(m, "_api", fake_api)
    output = await m.merge_worker(name="worker", operation_id=operation_id)

    assert output.isError is True
    assert output.structuredContent["error"]["message"]
    assert output.content[0].text.strip()
    assert output.content[0].text != "Error executing tool merge_worker:"


@pytest.mark.asyncio
async def test_switch_and_wip_defaults_defer_to_persisted_base(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path.endswith("/switch-branch"):
            return {"ok": True, "branch": "task-91/coder"}
        return {
            "uncommitted": [], "unmerged_commits": [], "changed_files": [],
            "context_pct": 0, "status": "idle",
        }

    with patch.object(m, "_api", side_effect=fake_api):
        await m.switch_worker_branch(name="coder", task_id="91")
        await m.worker_wip(name="coder")

    assert calls[0][2]["json"]["from_ref"] == ""
    assert calls[0][2]["json"]["force"] is False
    assert calls[1][2]["params"]["base_ref"] == ""


@pytest.mark.asyncio
async def test_switch_worker_branch_forwards_explicit_force(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    captured = {}

    async def fake_api(_method, _path, **kwargs):
        captured.update(kwargs["json"])
        return {"ok": True, "branch": "task-91/coder"}

    with patch.object(m, "_api", side_effect=fake_api):
        await m.switch_worker_branch(name="coder", task_id="91", force=True)

    assert captured["force"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"ok": False, "error": "target branch is busy"},
    {
        "ok": False,
        "state": "rollback_failed",
        "error": "checkout failed; rollback failed: restore HEAD denied",
        "actual_branch": "task-90/coder",
    },
])
async def test_switch_worker_branch_renders_failure_without_new_contract(
    monkeypatch, payload,
):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")

    async def fake_api(_method, _path, **_kwargs):
        return payload

    with patch.object(m, "_api", side_effect=fake_api):
        output = await m.switch_worker_branch(name="coder", task_id="91", force=True)

    assert output == f"Switch failed: {payload['error']}"


@pytest.mark.asyncio
async def test_kill_worker_force_param(monkeypatch):
    """force=True передаётся как строчный параметр в DELETE-запрос."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch")
    captured = {}
    async def fake_api(method, path, **kw):
        captured["method"] = method
        captured["path"] = path
        captured["params"] = kw.get("params", {})
        return {"ok": True}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.kill_worker(name="coder", force=True)
    assert captured["method"] == "DELETE"
    assert captured["path"] == "/api/sessions/coder"
    assert captured["params"]["force"] == "true"


@pytest.mark.asyncio
async def test_kill_worker_force_false_default(monkeypatch):
    """force=False (default) → params force='false'."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch")
    captured = {}
    async def fake_api(method, path, **kw):
        captured["params"] = kw.get("params", {})
        return {"ok": True}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.kill_worker(name="coder")
    assert captured["params"]["force"] == "false"


@pytest.mark.asyncio
async def test_send_message_cross_scope_warning(monkeypatch):
    """Если worker принадлежит другому parent → warning в ответе."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch-a")
    async def fake_api(method, path, **kw):
        return {"ok": True, "parent_name": "orch-b"}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.send_message(to="coder", message="hi")
    assert "⚠️" in out or "warning" in out.lower() or "orch-b" in out


@pytest.mark.asyncio
async def test_send_message_same_parent_no_warning(monkeypatch):
    """Сообщение воркеру того же родителя → нет предупреждения."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch-a")
    async def fake_api(method, path, **kw):
        return {"ok": True, "parent_name": "orch-a"}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.send_message(to="coder", message="hi")
    assert "⚠️" not in out


@pytest.mark.asyncio
async def test_list_agents_groups_by_parent(monkeypatch):
    """list_agents группирует сессии на Orchestrators / Your workers / Other workers."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "orch-a")
    monkeypatch.setattr(m, "ROLE", "orchestrator")
    sessions = [
        {"name": "orch-a", "scope": "/s", "role": "orchestrator", "parent_name": "", "status": "idle", "model": "opus"},
        {"name": "my-coder", "scope": "/s", "role": "worker", "parent_name": "orch-a", "status": "idle", "model": "sonnet"},
        {"name": "their-coder", "scope": "/s", "role": "worker", "parent_name": "orch-b", "status": "idle", "model": "sonnet"},
    ]
    async def fake_api(method, path, **kw):
        if path == "/api/sessions":
            return sessions
        if path == "/api/role-icons":
            return {}
        return {}
    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.list_agents()
    assert "## Orchestrators" in out
    assert "## Your workers" in out
    assert "## Other orchestrators' workers" in out
    assert "orch-a" in out
    assert "my-coder" in out
    assert "their-coder" in out


@pytest.mark.asyncio
async def test_list_agents_optional_icons_failure_is_visible_success(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "ROLE", "orchestrator")

    async def fake_api(_method, path, **_kwargs):
        if path == "/api/sessions":
            return [{"name": "orch", "role": "orchestrator", "status": "idle", "model": "opus"}]
        raise m.ApiToolError(code="http_5xx", message="icons unavailable", status=503)

    monkeypatch.setattr(m, "_api", fake_api)
    result = await _protocol_call(m, "list_agents", {})

    assert result.isError is False
    assert result.structuredContent["error"] is None
    assert "Role icons unavailable" in result.structuredContent["result"]
    assert "**orch**" in result.structuredContent["result"]


def test_cache_pill_uses_exact_and_approximate_runtime_policies():
    import app.mcp_stdio as m

    recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    expired = (datetime.now(timezone.utc) - timedelta(minutes=37)).isoformat()

    assert m._cache_pill({
        "status": "running",
        "cache_ttl_seconds": 1800,
        "cache_ttl_approximate": True,
    }) == "🔥 hot ≈30m"
    assert m._cache_pill({
        "status": "idle",
        "last_turn_ts": recent,
        "cache_ttl_seconds": 1800,
        "cache_ttl_approximate": True,
    }).startswith("🔥 hot ≈")
    assert m._cache_pill({
        "status": "idle",
        "last_turn_ts": expired,
        "cache_ttl_seconds": 1800,
        "cache_ttl_approximate": True,
    }) == "🧊? unknown (+7m past ≈30m)"
    assert m._cache_pill({
        "status": "idle",
        "last_turn_ts": expired,
        "cache_ttl_seconds": 3600,
        "cache_ttl_approximate": False,
    }).startswith("🟡 warm ")
    assert m._cache_pill({
        "status": "idle",
        "last_turn_ts": recent,
        "cache_ttl_seconds": 0,
        "cache_ttl_approximate": True,
    }) == ""
    assert m._cache_pill({"status": "running"}) == ""


def test_read_only_access_mode_hides_mutating_tools():
    import app.mcp_stdio as m

    visible = m._tool_names_for_access_mode(
        {"list_agents", "get_worker_logs", "send_message", "spawn_worker", "kill_worker"},
        "read-only",
    )

    assert visible == {"list_agents", "get_worker_logs"}


def test_full_access_mode_preserves_all_tools():
    import app.mcp_stdio as m

    names = {"list_agents", "send_message", "spawn_worker"}
    assert m._tool_names_for_access_mode(names, "full") == names


def test_unknown_access_mode_is_rejected():
    import app.mcp_stdio as m

    with pytest.raises(ValueError, match="ORCHESTRA_ACCESS_MODE"):
        m._tool_names_for_access_mode({"list_agents", "spawn_worker"}, "typo")


@pytest.mark.asyncio
async def test_bg_create_cron_command_sends_fail_closed_type(monkeypatch):
    import app.mcp_stdio as m

    monkeypatch.setattr(m, "SCOPE", "/scope")
    monkeypatch.setattr(m, "WORKER_NAME", "intent-hunter")
    captured = {}

    async def fake_api(method, path, **kwargs):
        captured.update(kwargs["json"])
        return {"id": "bg-monitor", "type": "cron_command", "status": "active"}

    with patch.object(m, "_api", side_effect=fake_api):
        result = await m.bg_create(
            type="cron_command",
            message="new intent found",
            cron_expr="*/15 * * * *",
            command="python3 monitor.py",
            pattern="^FOUND:",
            timeout_seconds=0,
        )

    assert captured == {
        "type": "cron_command",
        "config": {
            "cron_expr": "*/15 * * * *",
            "command": "python3 monitor.py",
            "pattern": "^FOUND:",
        },
        "message": "new intent found",
        "target_name": "intent-hunter",
        "target_scope": "/scope",
        "timeout_seconds": 0,
        "created_by": "intent-hunter",
    }
    assert "type=cron_command" in result


# ── merge_worker: RUNNING не должен читаться как отказ ──

def _merge_payload(operation_id: str, state: str, **over):
    """Ответ /api/merge-operations в форме, которую разбирает MCP."""
    payload = {
        "schema_version": 1,
        "operation_id": operation_id,
        "operation_state": state,
        "retryable": False,
        "commit_point": "REACHED" if state == "SUCCEEDED" else "NOT_REACHED",
        "git": {"status": state, "worker_branch": "task-1/w", "commits_merged": 2},
        "error": None,
        "next_action": {"code": "CHECK_SAME_OPERATION", "message": "check it"},
    }
    payload.update(over)
    return {"result": payload, "error": None}


@pytest.mark.asyncio
async def test_merge_worker_waits_out_running_and_returns_the_outcome(monkeypatch):
    """Главный контракт: один вызов — один ответ, второй шаг не нужен вызывающему."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    calls = []

    async def fake_api(method, path, **kw):
        calls.append(method)
        if method == "POST":
            return _merge_payload(kw["json"]["operation_id"], "RUNNING")
        op = path.rsplit("/", 1)[-1]
        # Готово только с 6-го опроса. Прежний бюджет допускал максимум ТРИ
        # (0.0+0.5+1.5), поэтому на до-фиксовом коде этот тест обязан падать —
        # иначе он не отличает новое поведение от старого.
        state = "RUNNING" if calls.count("GET") < 6 else "SUCCEEDED"
        return _merge_payload(op, state)

    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.merge_worker(name="w", target="main")

    assert out.structuredContent["result"]["operation_state"] == "SUCCEEDED"
    assert out.isError is False
    assert "GET" in calls, "тул обязан дождаться, а не вернуть RUNNING сразу"


@pytest.mark.asyncio
async def test_merge_worker_does_not_poll_when_already_terminal(monkeypatch):
    """Быстрый мерж не должен становиться медленнее из-за ожидания."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    calls = []

    async def fake_api(method, path, **kw):
        calls.append(method)
        return _merge_payload(kw["json"]["operation_id"], "SUCCEEDED")

    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.merge_worker(name="w", target="main")

    assert out.structuredContent["result"]["operation_state"] == "SUCCEEDED"
    assert calls == ["POST"], f"лишние опросы на терминальном ответе: {calls}"


@pytest.mark.asyncio
async def test_merge_worker_running_past_the_cap_reads_as_progress_not_failure(monkeypatch):
    """Потолок будет превышен — у времени операции длинный хвост.

    Корректность держится не на числе, а на том, что этот ответ невозможно
    прочитать как отказ: раньше на нём рапортовали «merge worker failed».
    """
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "_MERGE_WAIT_SECONDS", 0.01)

    async def fake_api(method, path, **kw):
        op = kw["json"]["operation_id"] if method == "POST" else path.rsplit("/", 1)[-1]
        return _merge_payload(op, "RUNNING")

    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.merge_worker(name="w", target="main")

    text = out.content[0].text
    result = out.structuredContent["result"]
    assert out.isError is False, "нетерминальное состояние — не ошибка протокола"
    assert text.startswith("STILL RUNNING"), text
    assert "NOT a failure" in text
    assert "do NOT report an error" in text.lower() or "do NOT report an error" in text
    assert result["operation_id"] in text, "нечем повторить — нет operation_id в тексте"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_merge_worker_real_failure_still_reads_as_failure(monkeypatch):
    """Ожидание не должно проглотить настоящий отказ."""
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")

    async def fake_api(method, path, **kw):
        return _merge_payload(
            kw["json"]["operation_id"], "FAILED",
            error={"code": "DIRTY_TREE", "message": "worktree is dirty"},
        )

    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.merge_worker(name="w", target="main")

    assert out.isError is True
    assert out.structuredContent["result"]["operation_state"] == "FAILED"


@pytest.mark.parametrize(
    ("payload", "expect_debt"),
    [
        ({"results": [{"source": "file", "path": "a.md", "content": "текст"}]}, False),
        ({"results": [{"source": "file", "path": "a.md", "content": "текст"}],
          "index": {"pending_files": 7, "indexing": True}}, True),
        ({"results": [], "index": {"pending_files": 7}}, True),
    ],
)
@pytest.mark.asyncio
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
            "next_action": {"code": "REVIEW_WARNINGS_OUTSIDE_MERGE", "message": "review"},
        }, "error": None}

    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.merge_worker(name="sales")

    assert out.isError is False
    text = out.content[0].text
    assert "SUCCEEDED" in text
    assert "task '18' not found" in text


@pytest.mark.asyncio
async def test_resolve_merge_operation_reports_upgrade_required_on_old_server(monkeypatch):
    """Старый роут молча проглотил бы запрос — вызывающий решил бы, что снял блокировку."""
    import app.mcp_stdio as m

    async def fake_api(method, path, **kw):
        raise m.ApiToolError(
            code="http_4xx", message="Not Found", status=404,
            request_id="r", details={"method": "POST", "path": path},
        )

    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.resolve_merge_operation(operation_id="op-1", reason="reconciled")

    assert out.isError is True
    assert "restart" in out.content[0].text
    assert "still blocking" in out.content[0].text


@pytest.mark.asyncio
async def test_resolve_merge_operation_reports_server_refusal(monkeypatch):
    import app.mcp_stdio as m

    async def fake_api(method, path, **kw):
        raise m.ApiToolError(
            code="domain_error", message="conflict", status=409, request_id="r",
            details={"method": "POST", "path": path},
            result={
                "operation_id": "op-1",
                "operation_state": "SUCCEEDED",
                "error": {
                    "code": "OPERATION_NOT_BLOCKING",
                    "message": "operation is SUCCEEDED: only PARTIAL or UNKNOWN block new merges",
                },
            },
        )

    with patch.object(m, "_api", side_effect=fake_api):
        out = await m.resolve_merge_operation(operation_id="op-1", reason="nothing to close")

    assert out.isError is True
    assert "OPERATION_NOT_BLOCKING" in out.content[0].text or "only PARTIAL" in out.content[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_model", "expected_model", "resume"),
    [
        ("gpt-5.6-luna", "gpt-5.6-luna", True),
        ("gpt-5.6-sol", "gpt-5.6-sol", False),
        ("gpt5.6luna", "gpt-5.6-luna", False),
    ],
)
async def test_codex_review_model_reaches_quota_cli_job_and_accounting(
    tmp_path, monkeypatch, requested_model, expected_model, resume,
):
    import app.mcp_stdio as m

    if resume:
        (tmp_path / "codex_sessions.json").write_text(json.dumps({
            "sessions": {"review": {"uuid": "review-thread"}},
        }))
    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/api/usage/readiness":
            return {
                "policy": "worker-weekly-v1",
                "state": "available",
                "model": expected_model,
                "provider": "codex",
                "observed_at": 2_000_000_000,
                "valid_until": 2_000_000_300,
            }
        if method == "GET":
            return {
                "id": "requester-id",
                "worktree_path": str(tmp_path),
                "task_id": "304",
            }
        return {"id": "bg-review"}

    monkeypatch.setattr(m, "_api", fake_api)
    monkeypatch.setattr(m, "_codex_bin", lambda: "/usr/bin/codex")
    monkeypatch.setattr(m, "WORKER_NAME", "review-author")
    monkeypatch.setattr(m, "SCOPE", str(tmp_path))
    monkeypatch.setattr(m.time, "time", lambda: 2_000_000_001)

    result = await m.codex_review(
        context="PROJECT CONTEXT: #304 model propagation fixture",
        target="artifact.py",
        output="review.md",
        mode="exec",
        resume=resume,
        model=requested_model,
    )

    readiness = next(call for call in calls if call[1] == "/api/usage/readiness")
    assert readiness[2]["params"] == {"model": expected_model}
    job = next(call[2]["json"] for call in calls if call[1] == "/api/bg/jobs")
    command = job["config"]["command"]
    assert command.count(f"-m {expected_model}") == (2 if resume else 1)
    assert f"--usage-model {expected_model}" in command
    assert expected_model in job["message"]
    assert expected_model in result
    if resume:
        assert "exec resume review-thread" in command


@pytest.mark.asyncio
async def test_codex_review_default_is_server_owned_luna_fast(tmp_path, monkeypatch):
    import app.mcp_stdio as m

    captured = {}

    async def fake_api(method, path, **kwargs):
        if path == "/api/usage/readiness":
            captured["readiness"] = kwargs["params"]
            return {
                "policy": "worker-weekly-v1",
                "state": "available",
                "model": "gpt-5.6-luna",
                "provider": "codex",
                "observed_at": 2_000_000_000,
                "valid_until": 2_000_000_300,
            }
        if method == "GET":
            return {"id": "requester-id", "worktree_path": str(tmp_path)}
        captured["job"] = kwargs["json"]
        return {"id": "bg-review"}

    monkeypatch.setattr(m, "_api", fake_api)
    monkeypatch.setattr(m, "_codex_bin", lambda: "/usr/bin/codex")
    monkeypatch.setattr(m, "SCOPE", str(tmp_path))
    monkeypatch.setattr(m.time, "time", lambda: 2_000_000_001)

    await m.codex_review(
        context="PROJECT CONTEXT: #304 default fixture",
        target="artifact.py",
        output="review.md",
        mode="exec",
    )

    tool = next(tool for tool in m.mcp._tool_manager.list_tools() if tool.name == "codex_review")
    assert tool.parameters["properties"]["model"]["default"] == "gpt-5.6-luna"
    assert "Omitted means the server-owned gpt-5.6-luna Fast tier" in tool.description
    assert captured["readiness"] == {"model": "gpt-5.6-luna"}
    assert "-m gpt-5.6-luna" in captured["job"]["config"]["command"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "message"),
    [
        ("not-a-model", "unknown model"),
        ("claude-opus-5[1m]", "runtime 'claude'"),
        ("grok-4.6", "runtime 'grok'"),
        ("gpt-5.3-codex-spark", "Spark is forbidden"),
    ],
)
async def test_codex_review_rejects_invalid_non_codex_and_spark_before_api(
    monkeypatch, model, message,
):
    import app.mcp_stdio as m

    api = AsyncMock(side_effect=AssertionError("invalid model must not reach any API"))
    monkeypatch.setattr(m, "_api", api)

    with pytest.raises(m.ApiToolError, match=message) as caught:
        await m.codex_review(
            context="PROJECT CONTEXT: #304 rejection fixture",
            target="artifact.py",
            mode="exec",
            model=model,
        )

    assert caught.value.code == "invalid_argument"
    assert caught.value.details["field"] == "model"
    api.assert_not_awaited()
