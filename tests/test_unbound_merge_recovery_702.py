import pytest


@pytest.mark.asyncio
async def test_unbound_merge_action_distinguishes_completed_from_never_bound(
    monkeypatch, tmp_path,
):
    import app.routes.sessions as sessions_route
    from app import tm
    from app.db import task_run_receipt_finish, task_run_receipt_open
    from tests.test_task_tracker_integration import _make_taskless_adhoc_worker

    repo, _worktree, found, _target, branch, head = _make_taskless_adhoc_worker(
        monkeypatch, tmp_path, name="taskless-no-history",
    )
    never_bound = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=branch,
        expected_head=head,
        req={"scope": found.scope, "task_outcome": "complete", "merge_schema_version": 2},
    )
    assert never_bound["next_action"]["code"] == "ASSIGN_TASK"

    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope=str(repo))
        assert tm.resolve_task_ref(conn, "42", "project") is not None
        task_run_receipt_open(
            session_id=found.id,
            worker_name=found.name,
            scope=found.scope,
            task_id="42",
            task_stable_id="",
        )
        task_run_receipt_finish(
            session_id=found.id,
            task_id="42",
            status="completed",
            prompt_template_end="",
        )

    completed = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=branch,
        expected_head=head,
        req={"scope": found.scope, "task_outcome": "complete", "merge_schema_version": 2},
    )
    assert completed["error"] == "session has no bound task"
    assert completed["next_action"]["code"] == "PROMOTE_ADHOC_WORK"
    assert "promote_current=True" in completed["next_action"]["message"]
    import app.merge_operations as operations

    public_result = operations.normalize_merge_result(
        "taskless-operation",
        completed,
        operations.normalize_request(
            name=found.name, scope=found.scope, target="main",
        ),
    )
    assert public_result["error"]["code"] == "SESSION_HAS_NO_BOUND_TASK"
    assert public_result["next_action"]["code"] == "PROMOTE_ADHOC_WORK"
