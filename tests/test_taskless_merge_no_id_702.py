import json

import pytest
from starlette.requests import Request


def _response_payload(response):
    from fastapi.responses import JSONResponse

    if isinstance(response, JSONResponse):
        return json.loads(response.body)
    return response


@pytest.mark.asyncio
async def test_taskless_merge_without_task_id_returns_promotion_action(monkeypatch, tmp_path):
    import app.mcp_stdio as mcp
    import app.routes.merge_operations as merge_route
    from app import tm
    from app.db import task_run_receipt_finish, task_run_receipt_open
    from tests.test_task_tracker_integration import _make_taskless_adhoc_worker

    repo, _worktree, found, _target, _branch, _head = _make_taskless_adhoc_worker(
        monkeypatch, tmp_path, name="taskless-no-task-id",
    )
    with tm._conn() as conn:
        task_run_receipt_open(
            session_id=found.id,
            worker_name=found.name,
            scope=found.scope,
            task_id="42",
            task_stable_id="",
            connection=conn,
        )
        task_run_receipt_finish(
            session_id=found.id,
            task_id="42",
            status="completed",
            prompt_template_end="",
            connection=conn,
        )
    monkeypatch.setattr(mcp, "SCOPE", str(repo))
    monkeypatch.setattr(mcp, "SESSION_ID", "")
    monkeypatch.setattr(mcp, "ROLE", "orchestrator")
    request = Request({"type": "http", "headers": []})
    monkeypatch.setattr(
        "app.mcp_proof.work_acceptor_principal",
        lambda *_args, **_kwargs: "orchestrator",
    )

    async def local_api(method, path, **kwargs):
        if method == "GET" and path == "/api/merge-operations/capabilities":
            return {
                "capabilities": ["task-lifecycle-v2", "work-review-v2"],
                "merge_schema_version": 2,
            }
        if method == "POST" and path == "/api/merge-operations":
            return _response_payload(
                await merge_route.create_merge_operation(kwargs["json"], request)
            )
        if method == "GET" and path.startswith("/api/merge-operations/"):
            return _response_payload(
                await merge_route.get_merge_operation(path.rsplit("/", 1)[-1])
            )
        raise AssertionError(f"unexpected API call: {method} {path}")

    monkeypatch.setattr(mcp, "_api", local_api)
    output = await mcp.merge_worker(
        name=found.name,
        target="main",
        task_outcome="complete",
    )

    result = output.structuredContent["result"]
    assert result["operation_state"] == "FAILED"
    assert result["error"]["code"] == "SESSION_HAS_NO_BOUND_TASK"
    assert result["next_action"]["code"] == "PROMOTE_ADHOC_WORK"
