from __future__ import annotations

import json

import pytest
from starlette.requests import Request


def _response_payload(response):
    from fastapi.responses import JSONResponse

    if isinstance(response, JSONResponse):
        return json.loads(response.body)
    return response


@pytest.mark.asyncio
async def test_complete_send_commit_merge_worker_promotes_explicit_task(
    monkeypatch, tmp_path,
):
    import app.mcp_stdio as mcp
    import app.routes.merge_operations as merge_route
    import app.routes.sessions as sessions_route
    import app.workspace as workspace
    from app import tm
    from app.db import get_session
    from app.session import AgentSession
    from app.mcp_proof import issue_mcp_proof
    from tests.test_task_tracker_integration import (
        _commit_file,
        _init_db,
        _make_git_scope,
        _prepare_merge,
        _save_worker,
    )
    from tests.task_seeds import create_task as seed_task

    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    name = "taskless-follow-up"
    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope=scope)
        first = seed_task(conn, "project", "First task", par_number=42, status="in_progress")
        next_task = seed_task(conn, "project", "Follow-up", par_number=43)
        conn.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            (name, first["id"]),
        )
    worktree = workspace.create_worktree(scope, name, task_id="42", base_branch="main")
    first_head = _commit_file(worktree.path, "first.txt", "#42: first task work")
    _save_worker(
        session_id=name, task_id="42", scope=scope,
        worktree_path=worktree.path, branch=worktree.branch,
    )
    _save_worker(
        session_id="orchestrator", task_id="", scope=scope,
        worktree_path=str(repo), branch="main", parent_name="",
    )
    with tm._conn() as conn:
        conn.execute(
            "UPDATE sessions SET is_orchestrator=1 WHERE id='orchestrator'",
        )
    tm.bind_task_to_session(scope, name, "42")
    found = _prepare_merge(monkeypatch, session_id=name, scope=scope)

    completed = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=name,
        expected_scope=scope,
        expected_branch=worktree.branch,
        expected_head=first_head,
        req={"scope": scope, "merge_schema_version": 2, "task_outcome": "complete"},
    )
    assert completed["ok"] is True, completed
    after_complete = get_session(found.id)
    assert after_complete["task_id"] == ""
    assert after_complete["needs_switch"] == 1

    async def record_send(_session, message, **_kwargs):
        return None

    monkeypatch.setattr(AgentSession, "send", record_send)
    monkeypatch.setattr(mcp, "SCOPE", scope)
    monkeypatch.setattr(mcp, "SESSION_ID", "")
    monkeypatch.setattr(mcp, "WORKER_NAME", "orchestrator")
    monkeypatch.setattr(mcp, "ROLE", "orchestrator")
    proof = issue_mcp_proof("orchestrator")
    request = Request({
        "type": "http",
        "headers": [
            (b"x-orchestra-session-id", b"orchestrator"),
            (b"x-orchestra-mcp-proof", proof.encode()),
        ],
    })
    adhoc_branch, _adhoc_head = workspace.inspect_worktree_identity(worktree.path)
    assert adhoc_branch == worktree.branch
    send_calls = []

    async def local_api(method, path, **kwargs):
        send_calls.append((method, path, kwargs))
        if method == "POST" and path == f"/api/sessions/{name}/send":
            response = await sessions_route.send_message(
                name, sessions_route.SendRequest(**kwargs["json"]), request,
            )
            return _response_payload(response)
        if method == "GET" and path == "/api/merge-operations/capabilities":
            return {
                "capabilities": ["task-lifecycle-v2", "work-review-v2"],
                "merge_schema_version": 2,
            }
        if method == "POST" and path == "/api/merge-operations":
            response = await merge_route.create_merge_operation(kwargs["json"], request)
            return _response_payload(response)
        if method == "GET" and path.startswith("/api/merge-operations/"):
            response = await merge_route.get_merge_operation(path.rsplit("/", 1)[-1])
            return _response_payload(response)
        raise AssertionError(f"unexpected API call: {method} {path}")

    monkeypatch.setattr(mcp, "_api", local_api)
    sent = await mcp.send_message(to=name, message="Continue with the follow-up.")
    assert "Message accepted" in sent, sent
    adhoc_branch, _adhoc_head = workspace.inspect_worktree_identity(worktree.path)
    assert adhoc_branch.startswith("adhoc-")
    assert get_session(found.id)["task_id"] == ""
    assert get_session(found.id)["needs_switch"] == 0
    followup_head = _commit_file(
        worktree.path, "follow-up.txt", "#43: committed follow-up work",
    )

    monkeypatch.setattr(
        "app.mcp_proof.work_acceptor_principal",
        lambda *_args, **_kwargs: "orchestrator",
    )
    output = await mcp.merge_worker(
        name=name,
        target="main",
        task_id="43",
        expected_head=followup_head,
        acceptance_note="Accepted the committed follow-up work after inspecting its exact HEAD.",
    )

    result = output.structuredContent["result"]
    assert result["operation_state"] == "SUCCEEDED", output
    assert (repo / "follow-up.txt").read_text(encoding="utf-8") == "#43: committed follow-up work"
    with tm._conn() as conn:
        closed = tm.get_task_by_id(conn, next_task["id"])
    assert closed["status"] == "done"
    request_body = next(kw["json"] for method, path, kw in send_calls
                        if method == "POST" and path == "/api/merge-operations")
    assert request_body["task_id"] == "43"
    assert request_body["task_outcome"] == "complete"
    assert request_body["merge_schema_version"] == 2
