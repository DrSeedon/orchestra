from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("caller_is_orchestrator", "host", "expected"),
    [
        (False, "", True),
        (True, "", False),
        (False, "remote.example", False),
    ],
)
async def test_local_run_jobs_from_agents_are_marked_as_agent_workload(
    monkeypatch, tmp_path, caller_is_orchestrator, host, expected,
):
    import app.routes.bg as route
    import app.bg_jobs as bg_jobs

    worktree = tmp_path / "worker"
    worktree.mkdir()
    target = SimpleNamespace(id="target-session")
    sessions = {
        "caller-session": {
            "id": "caller-session",
            "name": "caller",
            "role": "orchestrator" if caller_is_orchestrator else "worker",
            "is_orchestrator": caller_is_orchestrator,
            "task_id": "V-924",
            "worktree_path": str(worktree),
            "cwd": str(worktree),
            "scope": str(tmp_path),
        },
        "target-session": {
            "id": "target-session",
            "name": "target",
            "role": "worker",
            "is_orchestrator": False,
            "task_id": "V-924",
            "worktree_path": str(worktree),
            "cwd": str(worktree),
            "scope": str(tmp_path),
        },
    }
    monkeypatch.setattr(route.manager, "get_by_name", lambda *_: target)
    monkeypatch.setattr("app.db.get_session", lambda session_id: sessions.get(session_id))
    monkeypatch.setattr("app.work_review.assignment", lambda *_: None)
    create = AsyncMock(return_value={"id": "bg-test", "type": "run", "status": "active"})
    monkeypatch.setattr(bg_jobs.bg_manager, "create", create)
    request = Request({
        "type": "http",
        "headers": [(b"x-orchestra-session-id", b"caller-session")],
    })
    config = {"command": "ffmpeg -version"}
    if host:
        config["host"] = host

    await route.bg_job_create(
        route.BgJobCreateRequest(
            type="run", config=config, target_name="target",
            target_scope=str(tmp_path), created_by="caller",
        ),
        request,
    )

    job_config = create.await_args.kwargs["config"]
    assert job_config.get("agent_workload", False) is expected
